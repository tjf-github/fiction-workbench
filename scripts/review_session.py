"""多原本资料核对、进度保存和 Markdown 导出。"""

import hashlib
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from review_material import FACT_COLUMNS, MANUAL_COLUMNS, check_row, line_spans, read_text, selected_rows


REVIEWED, PENDING, QUESTION = "已核对", "待核对", "有疑问"
CHINESE_DIGITS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
NEGATIVE_SUMMARY_HINT = re.compile(r"不做第二次|不顶撞也不讨好|保留(?:是否.*的)?决定权|没表态|未表态|不要写|禁止写")


def _chapter_tokens(chapter_num):
    tokens = [f"第{chapter_num}章", f"第{chapter_num:02d}章", f"第{chapter_num:03d}章", f"{chapter_num:02d}", str(chapter_num)]
    if chapter_num in CHINESE_DIGITS:
        tokens.insert(0, f"第{CHINESE_DIGITS[chapter_num]}章")
    elif 10 < chapter_num < 20:
        tokens.insert(0, f"第十{CHINESE_DIGITS[chapter_num - 10]}章")
    return tokens


def workshop_hint(columns, cells):
    fields = dict(zip(columns, cells))
    text = " ".join(fields.get(col, "") for col in ("值", "原句", "属性/关系") if fields.get(col))
    if NEGATIVE_SUMMARY_HINT.search(text):
        return "写作工坊提示：含负向概括或抽象态度表述，后续转录场面卡时建议改写为具体物理动作（防红烧肉效应）。"
    return ""


def markdown_row(values):
    return "| " + " | ".join(value.replace("\n", " ").replace("|", r"\|") for value in values) + " |"


def atlas_markdown(text):
    payload = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("characters"), list):
        raise ValueError("JSON 缺少 Atlas 导出的 characters 列表")
    lines = ["# Atlas 提取候选", ""]
    quotes = {}
    for person in payload["characters"]:
        if not isinstance(person, dict) or not isinstance(person.get("evidence"), dict):
            raise ValueError("Atlas 人物条目缺少 evidence")
        lines.extend([f"## {person['name']}", "", markdown_row(FACT_COLUMNS), "| --- | --- | --- |"])
        for category, excerpts in person["evidence"].items():
            chapters = person.get("evidence_chapters", {}).get(category, [])
            for index, quote in enumerate(excerpts):
                chapter = chapters[index] if index < len(chapters) else None
                label = category if chapter is None else f"{category} · Atlas 章号 {chapter}"
                lines.append(markdown_row(("〔缺〕", label, quote)))
                quotes[str(len(lines))] = quote
        lines.append("")
    return lines, quotes


class ReviewSession:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lines, digest = read_text(self.path)
        self.quotes = {}
        if self.path.suffix.lower() == ".json":
            self.lines, self.quotes = atlas_markdown("\n".join(self.lines))
        self.rows = {str(number): (columns, cells, headings)
                     for number, columns, cells, headings in selected_rows(self.lines)}
        self.sidecar = self.path.with_name(f"{self.path.name}.{digest[:16]}.review.json")
        self.digest = digest
        self.saved = self.sidecar.read_bytes() if self.sidecar.exists() else None
        self.state = json.loads(self.saved) if self.saved else {"candidate_sha256": digest, "sources": {}, "items": {}}
        if self.state["candidate_sha256"] != digest:
            raise ValueError("保存的核对进度与候选文件版本不符")
        self.cache = {}

    def save(self, **updates):
        state = {**self.state, **updates}
        payload = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        current = self.sidecar.read_bytes() if self.sidecar.exists() else None
        if current != self.saved:
            raise ValueError("本次核对进度已被另一窗口修改，请重新打开候选文件")
        with NamedTemporaryFile(dir=self.sidecar.parent, suffix=".tmp", delete=False) as output:
            temp = Path(output.name)
            try:
                output.write(payload)
                output.close()
                temp.replace(self.sidecar)
            finally:
                output.close()
                temp.unlink(missing_ok=True)
        self.state, self.saved = state, payload

    def add_sources(self, paths):
        sources = dict(self.state["sources"])
        problems = []
        for path in paths:
            path = Path(path).resolve()
            try:
                _, digest = read_text(path)
                sources[str(path)] = digest
            except (OSError, ValueError) as error:
                problems.append(f"{path.name}  {error}")
        if sources != self.state["sources"]:
            self.save(sources=sources)
        return problems

    def source(self, path, digest):
        file = Path(path)
        stat = file.stat()
        key = (stat.st_size, stat.st_mtime_ns, digest)
        cached_key, lines = self.cache.get(path, (None, None))
        if key != cached_key:
            lines, _ = read_text(file, digest)
            self.cache[path] = (key, lines)
        return lines

    def item(self, key):
        return self.state["items"].get(key, {})

    def keys(self):
        return [*self.rows, *(key for key in self.state["items"] if key.startswith("M"))]

    def row(self, key):
        item = self.item(key)
        columns, cells, headings = self.rows.get(key, (MANUAL_COLUMNS, (), ("人工补充",)))
        return columns, tuple(item.get("cells", cells)), headings

    def check(self, key):
        binding = self.item(key).get("source")
        if not binding:
            raise ValueError("请先绑定这条证据的原本文件")
        source = self.source(*binding)
        columns, cells, headings = self.row(key)
        check_row(columns, cells, headings, source)

    def status(self, key):
        status = self.item(key).get("status", PENDING)
        if status == REVIEWED:
            try:
                self.check(key)
            except (OSError, ValueError):
                return QUESTION
        return status

    def set_status(self, key, status):
        if status == REVIEWED:
            self.check(key)
        self.save(items={**self.state["items"], key: {**self.item(key), "status": status}})

    def update_item(self, key, cells, path):
        if key is None:
            key = f"M{1 + sum(item.startswith('M') for item in self.keys())}"
        old = self.item(key)
        binding = None
        if path:
            path = str(Path(path).resolve())
            digest = self.state["sources"].get(path)
            if not digest:
                raise ValueError("请先登记要绑定的原本")
            binding = [path, digest]
        if cells == self.row(key)[1] and binding == old.get("source"):
            return key
        self.save(items={**self.state["items"], key: {"cells": cells, "source": binding, "status": PENDING}})
        return key

    def bind_unbound(self, path):
        digest = self.state["sources"][path]
        source = self.source(path, digest)
        items = dict(self.state["items"])
        count = 0
        for key in self.keys():
            item = self.item(key)
            if item.get("source"):
                continue
            columns, cells, _ = self.row(key)
            reference = dict(zip(columns, cells)).get("证据ID", "")
            try:
                line_spans(reference, len(source), require_original=True)
            except ValueError:
                continue
            items[key] = {**item, "source": [path, digest]}
            count += 1
        if count:
            self.save(items=items)
        return count

    def counts(self):
        stats = {REVIEWED: 0, QUESTION: 0, PENDING: 0, "total": 0, "unbound": 0}
        for key in self.keys():
            stats["total"] += 1
            st = self.status(key)
            stats[st] = stats.get(st, 0) + 1
            if not self.item(key).get("source"):
                stats["unbound"] += 1
        return stats

    def auto_bind(self):
        if not self.state["sources"]:
            return 0
        loaded = {}
        by_name = {}
        for path, digest in self.state["sources"].items():
            try:
                loaded[path] = (digest, self.source(path, digest))
                by_name.setdefault(Path(path).name, []).append(path)
            except (OSError, ValueError):
                continue
        if not loaded:
            return 0
        items = dict(self.state["items"])
        count = 0
        single_source = next(iter(loaded)) if len(loaded) == 1 else None
        for key in self.keys():
            item = self.item(key)
            if item.get("source"):
                continue
            columns, cells, _ = self.row(key)
            fields = dict(zip(columns, cells))
            reference = fields.get("证据ID", "").strip()
            target_path = None
            source_name = fields.get("出处", "").strip()
            if source_name and len(by_name.get(source_name, ())) == 1:
                candidate_path = by_name[source_name][0]
                try:
                    line_spans(reference, len(loaded[candidate_path][1]), require_original=True)
                    target_path = candidate_path
                except ValueError:
                    pass
            if target_path is None and single_source is not None:
                try:
                    line_spans(reference, len(loaded[single_source][1]), require_original=True)
                    target_path = single_source
                except ValueError:
                    pass
            if target_path is not None:
                items[key] = {**item, "source": [target_path, loaded[target_path][0]]}
                count += 1
                continue
            if reference in {"", "〔缺〕", "【缺】", "-"}:
                quote = (self.quotes.get(key) or fields.get("原句", "")).strip()
                if quote:
                    try:
                        matches, unavailable = self.find_quote(quote)
                    except ValueError:
                        continue
                    if len(matches) == 1 and not unavailable:
                        match_path, match_line, _ = matches[0]
                        new_cells = list(cells)
                        if "证据ID" in columns:
                            new_cells[columns.index("证据ID")] = f"原本:L{match_line}"
                        items[key] = {
                            **item,
                            "cells": tuple(new_cells),
                            "source": [match_path, loaded[match_path][0]],
                            "status": item.get("status", PENDING),
                        }
                        count += 1
        if count:
            self.save(items=items)
        return count

    def find_quote_candidates(self, excerpt, chapter_hint=None):
        excerpt = excerpt.strip()
        if not excerpt:
            raise ValueError("请输入要找的原文摘句")
        matches, unavailable = self.find_quote(excerpt)
        exact = True
        if not matches:
            exact = False
            clauses = [
                part.strip()
                for part in re.split(r"[，。！？；：、…—\s“”‘’\"'（）()《》【】]+", excerpt)
                if len(part.strip()) >= 4
            ]
            clauses.sort(key=len, reverse=True)
            seen = set()
            for clause in clauses[:4]:
                sub_matches, unavailable = self.find_quote(clause)
                for match in sub_matches:
                    if (match[0], match[1]) not in seen:
                        seen.add((match[0], match[1]))
                        matches.append(match)
                        if len(matches) >= 200:
                            break
                if matches:
                    break
        if chapter_hint is not None and matches:
            try:
                tokens = _chapter_tokens(int(chapter_hint))
                matches.sort(key=lambda item: 0 if any(tok in Path(item[0]).stem for tok in tokens) else 1)
            except (TypeError, ValueError):
                pass
        return matches, unavailable, exact

    def reset_item(self, key):
        if key not in self.state["items"]:
            return
        items = dict(self.state["items"])
        if key.startswith("M"):
            del items[key]
        else:
            old = items[key]
            items[key] = {"source": old.get("source"), "status": PENDING} if old.get("source") else {"status": PENDING}
        self.save(items=items)

    def find_quote(self, excerpt):
        excerpt = excerpt.strip()
        if not excerpt:
            raise ValueError("请输入要找的原文摘句")
        matches = []
        unavailable = []
        for path, digest in self.state["sources"].items():
            try:
                source = self.source(path, digest)
            except (OSError, ValueError):
                unavailable.append(Path(path).name)
                continue
            for number, text in enumerate(source, start=1):
                if excerpt in text:
                    matches.append((path, number, text))
                    if len(matches) >= 200:
                        return matches, unavailable
        return matches, unavailable

    def export_sections(self, split=False):
        lines = self.lines.copy()
        keys_by_line = {int(key): key for key in self.rows}
        for key in self.rows:
            item = self.item(key)
            if "cells" in item and tuple(item["cells"]) != self.rows[key][1]:
                lines[int(key) - 1] = markdown_row(value.replace(r"\|", "|") for value in item["cells"])

        manual = [key for key in self.keys() if key.startswith("M")]
        if manual:
            lines.extend(["", "## 人工补充", "", markdown_row(MANUAL_COLUMNS), "| --- | --- | --- | --- |"])
            for key in manual:
                _, cells, _ = self.row(key)
                lines.append(markdown_row(cells))
                keys_by_line[len(lines)] = key

        boundaries = [0]
        if split:
            headings = {1: [], 2: [], 3: []}
            fence = ""
            for index, line in enumerate(lines):
                marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
                if marker:
                    if not fence:
                        fence = marker[1]
                    elif marker[1].startswith(fence) and not marker[2].strip():
                        fence = ""
                    continue
                heading = re.match(r"^(#{1,3})\s+", line)
                if heading and not fence:
                    headings[len(heading[1])].append(index)
            for positions in headings.values():
                if len(positions) > 1:
                    boundaries.extend(positions[1:])
                    break
        boundaries.append(len(lines))

        parts = []
        for start, end in zip(boundaries, boundaries[1:]):
            section = lines[start:end]
            # Keep the review record beside its source section when the file is split.
            records = []
            for number in range(start + 1, end + 1):
                key = keys_by_line.get(number)
                if key is None:
                    continue
                item = self.item(key)
                columns, cells, _ = self.row(key)
                fields = dict(zip(columns, cells))
                summary = (fields.get("值") or fields.get("原句") or "〔缺〕").replace(r"\|", "|")
                if len(summary) > 40:
                    summary = summary[:40] + "…"
                binding = item.get("source")
                source = f"{Path(binding[0]).name}（{binding[1][:12]}）" if binding else "未绑定"
                reference = fields.get("证据ID", "〔缺〕")
                added_by = "人工" if key.startswith("M") else "Atlas" if key in self.quotes else "候选表"
                records.append(markdown_row((key if key.startswith("M") else f"L{key}", summary, source, reference, self.status(key), added_by)))
            if records:
                section.extend(["", "### 核对记录", "", "| 条目 | 内容 | 来源文件 | 行号 | 核对状态 | 整理来源 |",
                                "| --- | --- | --- | --- | --- | --- |", *records])
            parts.append("\n".join(section).rstrip() + "\n")
        return parts

    def export(self, path, split=False):
        path = Path(path).resolve()
        sources = {Path(name) for name in self.state["sources"]}
        if path in {self.path, self.sidecar, *sources}:
            raise ValueError("请为导出文件选择不同的位置或文件名")
        parts = self.export_sections()
        volumes = self.export_sections(split=True) if split else []
        if len(volumes) > 1:
            parts.extend(volumes)
        reserve = [path, *(path.with_name(f"{path.stem}-第{index:02d}卷.md") for index in range(1, len(parts)))]
        if any(output.exists() for output in reserve):
            raise FileExistsError("导出文件已存在，请换个文件名，原文件会继续保留")
        created = []
        try:
            for output, contents in zip(reserve, parts):
                with output.open("x", encoding="utf-8", newline="\n") as stream:
                    created.append(output)
                    stream.write(contents)
        except OSError:
            for output in created:
                output.unlink(missing_ok=True)
            raise
        return reserve
