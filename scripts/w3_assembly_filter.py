#!/usr/bin/env python3
"""OpenFic / DSH W3 场面卡上游装配转录过滤器（防红烧肉效应）。

检查并拦截：
1. 非成年向模式下违规挂载 X1-成年向隔离词表；
2. 整份塞入 W2 人物书全文或单角色锚点超出 3–5 条上限；
3. 负向禁令清单与否定概括词（如“未做第二次试探”“不顶撞也不讨好”“禁止……”）；
4. 抽象态势总结句（如“保留……决定权”“没表态去不去”“把一段话收在半截”）。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


W2_FULL_DUMP_MARKERS = (
    "一、基础身份与阶段边界",
    "二、外貌与衣着物理结构",
    "三、习惯动作与职业感官",
    "四、说话指纹与原声标本",
    "五、关系杠杆与专属面具",
    "六、人物心理底色与防御边界",
)

X1_ISOLATION_PATTERNS = (
    re.compile(r"X1-成年向隔离词表"),
    re.compile(r"高张力(?:物理与感官)?词表"),
)

# (正则, 类别, 建议正面物理改写)
REWRITE_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"(?:未|不)做第二次试探"),
        "负向概括词（防红烧肉效应）",
        "先看书面资料再点头",
    ),
    (
        re.compile(r"未表现出明显异常"),
        "负向概括词（防红烧肉效应）",
        "神色平静，抬眼继续看手头资料",
    ),
    (
        re.compile(r"不顶撞也不讨好"),
        "负向概括词（防红烧肉效应）",
        "沉默几秒后平稳接话，只谈眼下正事",
    ),
    (
        re.compile(r"保留[^，。；\n]{0,12}决定权"),
        "抽象态势总结句",
        "靠回椅背，暂不表态而先留下来等结果",
    ),
    (
        re.compile(r"没表态去不去"),
        "抽象态势总结句",
        "靠回椅背默认留下来等这一晚",
    ),
    (
        re.compile(r"两人刚把一段话收在半截[，、]?谁都不打算重[头新]?说(?:一遍)?"),
        "抽象态势总结句",
        "推门时屋里安静下来，两人都没先开口",
    ),
]

NEGATIVE_PROHIBITION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:^|[\s\-•*])(?:严禁|禁止)(?:写|问|提|出现|展开)[^，。；\n]*"), "负向禁令清单（请改为客观留白边界）"),
    (re.compile(r"(?:^|[\s\-•*])不要(?:写|问|提|让角色)[^，。；\n]*"), "负向禁令清单（请改为正向物理起点或留白边界）"),
]


@dataclass
class FilterIssue:
    line_no: int
    rule: str
    matched: str
    suggestion: str


def check_w3_card(text: str, *, adult_mode: bool = False, max_anchors_per_char: int = 5) -> list[FilterIssue]:
    issues: list[FilterIssue] = []
    lines = text.splitlines()

    # 1. X1 isolation gate
    if not adult_mode:
        for idx, line in enumerate(lines, start=1):
            for pat in X1_ISOLATION_PATTERNS:
                m = pat.search(line)
                if m:
                    issues.append(
                        FilterIssue(
                            line_no=idx,
                            rule="X1隔离门禁",
                            matched=m.group(0),
                            suggestion="常规非18+流水线默认关闭 X1-成年向隔离词表，请移除该引用或显式开启 --adult-mode",
                        )
                    )

    # 2. Full W2 dump gate
    hit_w2_sections = [marker for marker in W2_FULL_DUMP_MARKERS if marker in text]
    if len(hit_w2_sections) >= 3:
        issues.append(
            FilterIssue(
                line_no=1,
                rule="禁止整份塞入W2全文",
                matched="、".join(hit_w2_sections[:3]),
                suggestion="严禁将整份 W2 人物书塞入 W3 场面卡，请按需仅摘录每角色 3–5 条本场实际用到的物理特征与原声标本",
            )
        )

    # 3. Per-character anchor count gate in Section 五
    in_anchor_section = False
    current_char: str | None = None
    char_start_line = 1
    char_anchor_count = 0

    def flush_char() -> None:
        if current_char is not None and char_anchor_count > max_anchors_per_char:
            issues.append(
                FilterIssue(
                    line_no=char_start_line,
                    rule="单角色锚点超限",
                    matched=f"{current_char}（共 {char_anchor_count} 条）",
                    suggestion=f"单角色本场挂载锚点须控制在 3–{max_anchors_per_char} 条以内，请删减本场未直接用到的条目",
                )
            )

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if re.match(r"^#{2,3}\s*五、", stripped):
            in_anchor_section = True
            continue
        if in_anchor_section and re.match(r"^#{2,3}\s*[六七八九十]、", stripped):
            flush_char()
            in_anchor_section = False
            current_char = None
            continue
        if in_anchor_section:
            char_match = re.match(r"^-\s*\*\*([^*]+)\*\*", stripped)
            if char_match:
                flush_char()
                current_char = char_match.group(1).strip()
                char_start_line = idx
                char_anchor_count = 0
                # If inline anchors separated by semicolons on the same line
                rest = stripped[char_match.end():].lstrip("：: ")
                if rest and not rest.startswith("（"):
                    char_anchor_count = len([seg for seg in re.split(r"[；;]", rest) if seg.strip()])
                continue
            if current_char is not None and re.match(r"^(?:\d+\.|-|\*)\s+", stripped):
                char_anchor_count += 1
    flush_char()

    # 4. Negative generalizations, abstract state summaries, negative prohibition lists
    for idx, line in enumerate(lines, start=1):
        # Skip meta callout / blockquote calibration notes at top of file
        if line.lstrip().startswith(">"):
            continue
        for pat, category, suggestion in REWRITE_RULES:
            for m in pat.finditer(line):
                issues.append(
                    FilterIssue(
                        line_no=idx,
                        rule=category,
                        matched=m.group(0),
                        suggestion=f"建议改写为：{suggestion}",
                    )
                )
        for pat, category in NEGATIVE_PROHIBITION_PATTERNS:
            for m in pat.finditer(line):
                issues.append(
                    FilterIssue(
                        line_no=idx,
                        rule=category,
                        matched=m.group(0).strip(),
                        suggestion="请删除负向禁令，改为只陈述本场写到哪一步为止、哪些信息留给后文",
                    )
                )

    return issues


def sanitize_w3_card(text: str) -> tuple[str, int]:
    """自动将常见负向概括词与抽象态势总结句转译为正面物理动作。"""
    replacements = 0
    out_lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            out_lines.append(line)
            continue
        new_line = line
        for pat, _category, replacement in REWRITE_RULES:
            new_line, count = pat.subn(replacement, new_line)
            replacements += count
        out_lines.append(new_line)
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(out_lines) + suffix, replacements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenFic / DSH W3 场面卡上游装配转录过滤器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_check = subparsers.add_parser("check", help="检查 W3 场面卡是否触犯 v3 装配与防红烧肉规则")
    p_check.add_argument("file", type=Path, help="W3 场面卡 Markdown 文件路径")
    p_check.add_argument("--adult-mode", action="store_true", help="显式开启成年向模式（放行 X1 词表挂载）")
    p_check.add_argument("--max-anchors", type=int, default=5, help="单角色最大锚点数（默认 5）")

    p_san = subparsers.add_parser("sanitize", help="自动转译常见负向概括词与抽象态势总结句")
    p_san.add_argument("file", type=Path, help="W3 场面卡 Markdown 文件路径")
    p_san.add_argument("--in-place", action="store_true", help="直接写回原文件（默认输出到 stdout）")

    args = parser.parse_args(argv)
    if not args.file.is_file():
        print(f"错误：找不到文件 {args.file}", file=sys.stderr)
        return 2

    content = args.file.read_text(encoding="utf-8")

    if args.command == "check":
        issues = check_w3_card(content, adult_mode=args.adult_mode, max_anchors_per_char=args.max_anchors)
        if not issues:
            print(f"PASS: {args.file} 通过 v3 上游装配与防红烧肉检查。")
            return 0
        print(f"FAIL: {args.file} 检出 {len(issues)} 项上游装配问题：")
        for item in issues:
            print(f"  - L{item.line_no} [{item.rule}] 命中「{item.matched}」 -> {item.suggestion}")
        return 1

    sanitized, count = sanitize_w3_card(content)
    if args.in_place:
        args.file.write_text(sanitized, encoding="utf-8")
        print(f"已清洗 {args.file}，共转译 {count} 处触发词。")
    else:
        sys.stdout.write(sanitized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
