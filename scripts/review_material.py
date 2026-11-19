"""回查资料出处，检查人工选定的候选条目。只读，使用 Python 标准库。"""

import argparse
import hashlib
from pathlib import Path
import re


FACT_COLUMNS = ("证据ID", "属性/关系", "值")
WORLD_COLUMNS = ("证据ID", "主体", "属性/关系", "值", "出处", "origin", "status")
ANCHOR_COLUMNS = ("原句", "证据ID", "可拍摄", "人物相关性", "origin")
MANUAL_COLUMNS = ("证据ID", "主体", "属性/关系", "值")
SUPPORTED_COLUMNS = (FACT_COLUMNS, WORLD_COLUMNS, ANCHOR_COLUMNS, MANUAL_COLUMNS)
LINE_SPAN = re.compile(r"L([1-9][0-9]*)(?:\s*[-–—]\s*L([1-9][0-9]*))?")
PENDING = re.compile(r"待裁定|待核|待补|待确认|未核验|未确认|〔缺〕|【缺】|needs_rework|unverified", re.I)
EXCLUDED_SECTION = re.compile(r"^(?:[A-Z][0-9]*\s+)?(?:附录|附记|矛盾清单|缺口)|\bC4\b|不挂载")


def read_text(path, expected_sha=None):
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if expected_sha is not None and actual_sha != expected_sha.lower():
        raise ValueError(f"{path} 的 SHA-256 不符，实际为 {actual_sha}")
    return raw.decode("utf-8-sig").splitlines(), actual_sha


def line_spans(reference, line_count, require_original=False):
    reference = reference.strip().strip("`")
    parts = re.split(r"\s*[,，;；、]\s*", reference)
    if require_original and not parts[0].startswith(("原本:", "原本：")):
        raise ValueError(f"证据 ID 应以「原本:」开头，实际为「{reference}」")
    spans = []
    for part in parts:
        match = LINE_SPAN.fullmatch(re.sub(r"^原本[:：]\s*", "", part))
        if not match:
            raise ValueError(f"无法解析行号「{part}」，请使用 L12 或 L12–L14")
        start = int(match[1])
        end = int(match[2] or match[1])
        if not start <= end <= line_count:
            raise ValueError(f"行段 L{start}–L{end} 无效，文件共 {line_count} 行")
        spans.append((start, end))
    return spans


def table_cells(line):
    text = line.strip()
    if not (text.startswith("|") and text.endswith("|")):
        return ()
    return tuple(cell.strip() for cell in re.split(r"(?<!\\)\|", text[1:-1]))


def selected_rows(lines, selected=None):
    headings = []
    columns = ()
    fence = ""
    for number, line in enumerate(lines, start=1):
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if opening:
            marker, tail = opening.groups()
            if not fence:
                fence = marker
            elif marker.startswith(fence) and not tail.strip():
                fence = ""
            columns = ()
            continue
        if fence:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if heading:
            depth, title = len(heading[1]), heading[2]
            while headings and headings[-1][0] >= depth:
                headings.pop()
            headings.append((depth, title))
        cells = table_cells(line)
        if not cells:
            columns = ()
            continue
        if not columns and cells in SUPPORTED_COLUMNS and number < len(lines):
            separator = table_cells(lines[number])
            if len(separator) == len(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
                columns = cells
            continue
        if columns and (selected is None or number in selected) and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            yield number, columns, cells, tuple(title for _, title in headings)


def check_row(columns, cells, headings, source):
    if len(cells) != len(columns) or any(cell in {"", "-", "—", "——"} for cell in cells):
        raise ValueError("列数不符或有必填项为空")
    row = dict(zip(columns, cells))
    if any(EXCLUDED_SECTION.search(title) for title in headings) or any(PENDING.search(cell) for cell in cells):
        raise ValueError("位于隔离章节或含待处理标记，请人工核对")
    if row.get("status", "confirmed") != "confirmed" or row.get("origin", "原本") not in {"原本", "first_book"}:
        raise ValueError("条目状态或来源未满足原本条目的检查口径")
    for start, end in line_spans(row["证据ID"], len(source), require_original=True):
        if not any(line.strip() for line in source[start - 1:end]):
            raise ValueError(f"出处 L{start}–L{end} 全为空行")


def check_material(args, source):
    lines, digest = read_text(args.candidate)
    print(f"候选文件 SHA-256 {digest}")
    selected = {number for start, end in line_spans(args.rows, len(lines)) for number in range(start, end + 1)}
    found = set()
    issues = 0
    for number, columns, cells, headings in selected_rows(lines, selected):
        found.add(number)
        try:
            check_row(columns, cells, headings, source)
        except ValueError as error:
            print(f"L{number}  {error}")
            issues += 1
    for number in sorted(selected - found):
        print(f"L{number}  未找到受支持的证据表数据行")
        issues += 1
    if issues:
        print(f"检查未通过，共 {issues} 行需要处理。")
        return 1
    if args.reviewed_sha256 is None:
        print(f"{len(selected)} 行通过机械检查。所选行仍需人工核对并确认当前文件版本。")
        return 1
    if args.reviewed_sha256.lower() != digest:
        print("已核对版本的 SHA-256 与当前文件不符，请核对当前版本。")
        return 1
    print(f"{len(selected)} 行通过入库前检查。可由人工加入对应资料书。")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    locate = commands.add_parser("locate", help="显示指定文件的出处行段")
    locate.add_argument("source", type=Path)
    locate.add_argument("reference", help="如 原本:L12–L14；L20")
    locate.add_argument("--source-sha256", help="核对来源版本")
    check = commands.add_parser("check", help="检查人工选定的世界书或人物书候选行")
    check.add_argument("candidate", type=Path)
    check.add_argument("--rows", required=True, help="候选 Markdown 的实际行号，如 L19,L22–L24")
    check.add_argument("--source", type=Path, required=True, help="证据 ID 指向的原本 UTF-8 文件")
    check.add_argument("--source-sha256", required=True, help="资料清单中登记的原本 SHA-256")
    check.add_argument("--reviewed-sha256", help="人工已核对所选行时，填写该候选版本的 SHA-256")
    args = parser.parse_args()
    try:
        source, digest = read_text(args.source, args.source_sha256)
        if args.command == "check":
            return check_material(args, source)
        spans = line_spans(args.reference, len(source))
        print(f"来源 SHA-256 {digest}")
        for start, end in spans:
            for number, line in enumerate(source[start - 1:end], start=start):
                print(f"L{number}\t{line}")
        return 0
    except (OSError, ValueError) as error:
        parser.exit(2, f"无法检查：{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
