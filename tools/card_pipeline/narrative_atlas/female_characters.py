#!/usr/bin/env python3
"""纯规则中文女性角色与特征提取器（不联网、不使用 AI）。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    from .book_profile import resolve_profile
    from .evidence_sample import select_category_evidence, select_category_evidence_with_lines
except ImportError:  # python .../female_characters.py 脚本入口
    from book_profile import resolve_profile
    from evidence_sample import select_category_evidence, select_category_evidence_with_lines


CJK = r"\u3400-\u4dbf\u4e00-\u9fff"
DIALOGUE_QUOTE_RE = re.compile(r"(?:“[^”]{4,}”|「[^」]{4,}」|『[^』]{4,}』|\"[^\"]{4,}\")")

# --encoding 的取值。auto = 按 BOM 与常见中文编码依次尝试（默认）。
ENCODING_CHOICES = ("auto", "utf-8", "utf-8-sig", "gb18030", "big5", "utf-16", "utf-16-le", "utf-16-be")


class TextDecodeError(ValueError):
    """显式指定的编码解不开输入文件。

    与自动探测不同：自动探测解不开会退化为替换字符，显式指定解不开必须报错，否则用户拿到的是一份乱码成果。
    """

# 句末标点之后会紧跟的收尾符号：句号（或折行）把引号切出来时，它必须回接到上一句。
CLOSING_MARKS = "”’\"'）)】》」』"
# 收尾符号 → 对应的开符号。回接前要确认上一句确实还欠一个收尾符号，否则会把下一句的开引号抢过来。
QUOTE_PAIRS = {
    "”": "“", "’": "‘", "）": "（", ")": "(", "】": "【", "》": "《", "」": "「", "』": "『",
}
# 直引号/单引号既可作开引号也可作收引号：配对检查退化为「上一句里的个数是否为奇数」。
AMBIGUOUS_MARKS = "\"'"
# 撇号与直引号共用码位：两侧都是 ASCII 字母/数字时它属于词内（don't / it's / I’m），不是引号。
APOSTROPHE_MARKS = "'’"
# 只由标点构成、又无从归属的片段不含任何可用于识别的信息：丢弃，而不是把它当成一句话。
PUNCTUATION_ONLY = set(CLOSING_MARKS) | set(QUOTE_PAIRS.values()) | set("。！？!?；;，,、：:…—～·")


def load_text(path: Path, encoding: str | None = None) -> tuple[str, str]:
    """读取文本，返回 (文本, 实际使用的编码)。

    encoding 为 None 或 "auto" 时按 BOM 与常见中文编码依次尝试；显式指定时**只用该编码**，
    解不开就抛 TextDecodeError，绝不静默替换——猜不出来的编码必须让人显式指定，而不是给一份乱码。
    """
    data = path.read_bytes()
    if encoding and encoding != "auto":
        if encoding not in ENCODING_CHOICES:
            raise ValueError(f"不支持的编码：{encoding}；可选 {', '.join(ENCODING_CHOICES)}")
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError as exc:
            # 打**路径**而不是 basename：--recursive 下各卷常有同名文件（vol1/ch1.txt 与 vol2/ch1.txt），
            # 只点名文件名时用户无法判断是哪一卷（与 output_stem 的短哈希去冲突思路对齐）。
            raise TextDecodeError(f"{path}：按编码 {encoding} 解不开（{exc}）") from exc
        # 显式编码同样要吃掉前导 BOM：U+FEFF 在 Python 3 里不是空白，留在正文里会让第一个章标题
        # 识别不到，整本书的章号随之前移一位（实测 chapters 从 [1,2] 变成 [0,1]）。
        return (text[1:] if text.startswith("\ufeff") else text), encoding

    # UTF-16 只认 BOM：没有 BOM 时 'utf-16' 按本机字节序硬解，会把 GB18030/Big5 的双字节文本抢先
    # 解成乱码（字节数为偶数时尤其隐蔽，表现为「扫完一整本书 0 个角色」）。无 BOM 的 UTF-16 请用
    # --encoding utf-16-le / utf-16-be 显式指定。
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            pass
    for candidate in ("utf-8", "gb18030", "big5"):
        try:
            return data.decode(candidate), candidate
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace"), "utf-8(replace)"


def configure_stdio() -> None:
    """把 stdout/stderr 固定为 UTF-8。

    Windows 下管道或重定向时 Python 用 locale 编码（cp936/cp1252）写标准输出，中文要么乱码，
    要么在非中文区域设置下直接抛 UnicodeEncodeError 让整次运行失败。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 标准流被替换或不支持重配置时保持原样：日志编码不该让主流程崩掉。
            pass


def load_rules(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def count_quote_marks(sentence: str, mark: str) -> int:
    """数这个符号在该句里充当**引号**的次数。

    撇号与引号共用码位：`don't` / `it's` / `I’m` 里的撇号两侧都是 ASCII 字母或数字，它是词的一部分，
    既不开引号也不收引号。把它算进去会让「上一句里的个数是否为奇数」这个判定凭空翻转，
    于是下一句的开引号被粘到上一句句末（实测：`张强说道 don't know。\n'林婉儿'笑了。`）。
    """
    if mark not in APOSTROPHE_MARKS:
        return sentence.count(mark)
    total = 0
    for match in re.finditer(re.escape(mark), sentence):
        before = sentence[match.start() - 1] if match.start() > 0 else ""
        after = sentence[match.end()] if match.end() < len(sentence) else ""
        if before.isascii() and before.isalnum() and after.isascii() and after.isalnum():
            continue  # 词内撇号
        total += 1
    return total


def _owes_closing_mark(sentence: str, mark: str) -> bool:
    """这一句是否还欠这个收尾符号。欠才回接；不欠说明它属于下一句（开引号）或本就是多余标点。"""
    if mark in AMBIGUOUS_MARKS:
        # 直引号既是开也是收：只看这一句里（词内撇号除外）的个数是否为奇数。
        return count_quote_marks(sentence, mark) % 2 == 1
    opening = QUOTE_PAIRS.get(mark)
    if not opening:
        return False
    return sentence.count(opening) > count_quote_marks(sentence, mark)


def _quote_owner(owing: list[int], sentence_count: int, cross_sentence: bool) -> int | None:
    """这个收尾符号该回接到哪一句；没有归属时返回 None（调用方维持原样，纯标点片段随后被丢弃）。

    owing 是"欠这个收尾符号"的句子下标栈（递增），栈顶即**最近的**欠符号句子。

    - cross_sentence=True（该片段去掉开头这些收尾符号后只剩标点，因此**不可能**是下一句的开引号）：
      回接到栈顶。跨句引语（`她说：“今天很好。\n我们去散步吧。”`）的收尾引号因此归属到开引号所在句，不再被丢掉。
    - cross_sentence=False（片段后面还有内容）：只有紧邻的上一句欠它时才回接。带内容的片段可能本身就是
      下一句的开引号，跨句去找会把它抢走，所以这里保守。
    """
    if not owing:
        return None
    if cross_sentence:
        return owing[-1]
    return owing[-1] if owing[-1] == sentence_count - 1 else None


def _append_owing(sentences: list[str], owing: dict[str, list[int]], index: int) -> None:
    """新句子入栈：它欠哪些收尾符号，就在那些符号的栈里记下它的下标。

    维护"欠符号句子"的下标栈，而不是每次回接都从后往前扫（无从归属的孤立片段会让扫描退化成 O(句数²)，
    2 万行实测 113 秒）。新句子的下标必然大于栈里已有的一切，所以直接追加到栈顶。
    """
    for mark in CLOSING_MARKS:
        if _owes_closing_mark(sentences[index], mark):
            owing[mark].append(index)


def _settle_owing(sentences: list[str], owing: dict[str, list[int]], index: int, mark: str) -> None:
    """回接之后收拾栈：这一句只可能**失去**欠账，而且只可能失去刚回接的这个符号
    （追加一个收尾符号只改变它自己的计数），且它原本就是这个符号的栈顶（由 _quote_owner 保证）。

    因此这里只看一眼栈顶，不按下标判存在——按下标判存在会让"每句都欠符号"的输入退化成 O(句数²)：
    早先的句子可能仍欠**另一个**符号而已经不在栈顶（实测：句子 0 同时欠 ” 与 "、句子 1 也欠 " 时，
    只看栈顶会把 0 重复压栈并盖住更近的句子 1），那种情况本来就不需要动它。
    """
    stack = owing[mark]
    if stack and stack[-1] == index and not _owes_closing_mark(sentences[index], mark):
        stack.pop()


def split_sentences_with_lines(text: str, base_line: int = 1) -> list[tuple[str, int]]:
    text = re.sub(r"\r\n?", "\n", text)
    # 终止符与换行都成组匹配：连续的终止符（？！、。。）只算一个分隔符，不会切出只由标点构成的伪句。
    # 终止符留在句内，换行不是句子内容，因此两种分隔符的截取位置不同。
    pieces: list[tuple[str, int]] = []
    start = 0
    for match in re.finditer(r"([。！？!?；;]+|\n+)", text):
        end = match.start() if match.group(0).startswith("\n") else match.end()
        pieces.append((text[start:end], start))
        start = match.end()
    pieces.append((text[start:], start))

    sentences: list[str] = []
    sent_lines: list[int] = []
    owing: dict[str, list[int]] = {mark: [] for mark in CLOSING_MARKS}
    for piece, piece_offset in pieces:
        cleaned = re.sub(r"\s+", " ", piece).strip()
        if not cleaned:
            continue
        # 跳过前导空白/换行，定位到该句第一个非空字符所在的 1-based 原文行号。
        lead_ws = len(piece) - len(piece.lstrip())
        line_no = base_line + text.count("\n", 0, piece_offset + lead_ws)
        head = 0
        while head < len(cleaned) and cleaned[head] in CLOSING_MARKS:
            head += 1
        cross_sentence = all(ch in PUNCTUATION_ONLY for ch in cleaned[head:])
        cut = 0
        while cut < len(cleaned) and cleaned[cut] in CLOSING_MARKS:
            mark = cleaned[cut]
            owner = _quote_owner(owing[mark], len(sentences), cross_sentence)
            if owner is None:
                break
            sentences[owner] += mark
            cut += 1
            _settle_owing(sentences, owing, owner, mark)
        if cut:
            cleaned = cleaned[cut:].strip()
        if not cleaned or all(ch.isspace() or ch in PUNCTUATION_ONLY for ch in cleaned):
            continue
        sentences.append(cleaned)
        sent_lines.append(line_no)
        _append_owing(sentences, owing, len(sentences) - 1)
    return list(zip(sentences, sent_lines))


def split_sentences(text: str) -> list[str]:
    return [s for s, _ in split_sentences_with_lines(text)]


def chapter_map_with_lines(text: str, rules: dict) -> list[tuple[int, str, int]]:
    # 先归一化换行：章标题正则用 $ 收行，CRLF 的 \r 会让「以章标记开头的正文行」重新命中。
    text = re.sub(r"\r\n?", "\n", text)
    chapter_re = re.compile(rules["chapter_pattern"], re.MULTILINE)
    matches = list(chapter_re.finditer(text))
    if not matches:
        return [(1, text, 1)]
    result: list[tuple[int, str, int]] = []
    if matches[0].start() > 0:
        result.append((0, text[: matches[0].start()], 1))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        base_line = 1 + text.count("\n", 0, match.start())
        result.append((i + 1, text[match.start() : end], base_line))
    return result


def chapter_map(text: str, rules: dict) -> list[tuple[int, str]]:
    return [(ch, body) for ch, body, _ in chapter_map_with_lines(text, rules)]


def collect_full_mention_lines(
    chapters_with_lines: list[tuple[int, str, int]],
    names: list[str],
    cap: int,
    strategy: str = "earliest_mid_latest",
) -> tuple[list[str], list[int], list[int]]:
    """按原文自然段收集角色所有提及行（带章节号与 1-based 行号）；超 cap 时按早中晚抽样。"""
    labels = [n for n in names if n]
    if not labels or cap <= 0:
        return [], [], []
    texts: list[str] = []
    chs: list[int] = []
    lns: list[int] = []
    seen_lines: set[int] = set()
    for chapter_no, chapter_text, base_line in chapters_with_lines:
        for offset, raw_line in enumerate(chapter_text.splitlines()):
            cleaned = raw_line.strip()
            if not cleaned:
                continue
            line_no = base_line + offset
            if line_no in seen_lines:
                continue
            if any(lbl in cleaned for lbl in labels):
                seen_lines.add(line_no)
                texts.append(cleaned)
                chs.append(chapter_no)
                lns.append(line_no)
    if len(texts) <= cap:
        return texts, chs, lns
    temp_rules = {"max_evidence_per_category": cap, "sample_strategy": strategy}
    return select_category_evidence_with_lines(temp_rules, texts, chs, lns, category=None, names=labels)


def contains_any(text: str, words: Iterable[str], compound_exceptions: Iterable[str] = ()) -> list[str]:
    """返回 text 里出现的词。

    compound_exceptions 只作用于**单字词**（可选，默认空 = 旧行为）：单字词很容易在复合词内部被误命中
    （「他」之于「其他/他们/吉他」），当它在 text 里的每一次出现都落在某个例外词内部时就不算命中。
    多字词（「他的」「男子」）不参与这层过滤——它们本身已经是完整的词。
    """
    hits: list[str] = []
    compounds = tuple(w for w in compound_exceptions if w)
    for word in words:
        if not word or word not in text:
            continue
        if compounds and len(word) == 1 and not _has_free_occurrence(text, word, compounds):
            continue
        hits.append(word)
    return hits


def _has_free_occurrence(text: str, word: str, compounds: Iterable[str]) -> bool:
    """word 是否至少有一次出现不在任何例外词内部。"""
    covered: list[tuple[int, int]] = []
    for compound in compounds:
        if word in compound:
            covered.extend(match.span() for match in re.finditer(re.escape(compound), text))
    if not covered:
        return True
    for match in re.finditer(re.escape(word), text):
        if not any(start <= match.start() and match.end() <= end for start, end in covered):
            return True
    return False


def index_by_first_char(names: Iterable[str]) -> dict[str, list[str]]:
    """按首字给名字建索引（T8-1）。

    「name 是 text 的子串」的必要条件是「name 的首字出现在 text 里」，所以先按首字预筛不会漏掉任何命中：
    它只是把 O(候选 × 分句) 的逐个包含检查，降成 O(分句里出现过的不同字符 + 该首字下的候选)。
    空串没有首字，直接丢掉——候选名从 reject_reason 起就要求长度 ≥ 2，本就不该出现在这里。
    """
    index: dict[str, list[str]] = {}
    for name in names:
        if name:
            index.setdefault(name[0], []).append(name)
    return index


def names_present(index: dict[str, list[str]], text: str) -> list[str]:
    """返回 text 里出现过的名字，按**首字分组**的顺序（可变字典的插入序）返回。

    预筛用的是「名字的首字是否出现在 text 里」——这是包含关系的必要条件，不会漏命中；
    代价从"每个名字都做一次子串搜索"降成"只在文本里出现过的首字上做子串搜索"。

    **关于返回顺序**：它**不是**建索引时 names 的顺序，而是"文本里首字首次出现的顺序"。
    结果仍然一致，正确性依赖下面这条（**不是**"顺序恰好相同"）：
    代码里唯一读取顺序的地方是 extract_traits 的 explicit[0]，而 last_owner 与 sentence_owner 的赋值
    都带 "len(explicit) == 1" 这个守卫——同句出现多个候选人时两者都退化为 None，后续分句不会因此改归属；
    同句内 owners = explicit 会把特征记到**每一个**候选人上，与顺序无关。
    这份依据由 tests/test_index.py 的固定对照用例守住（含"候选正序/逆序得到相同 traits"一条）。
    **若将来新增一处读取 explicit[0] 的逻辑（例如把它当主 owner），必须重新评估本函数的顺序语义。**
    """
    present: list[str] = []
    for char in dict.fromkeys(text):
        for name in index.get(char, ()):
            if name in text:
                present.append(name)
    return present


def exclusive_spans(sentence: str, name: str, longer: Iterable[str] = ()) -> list[tuple[int, int]]:
    """name 在 sentence 里**没有被 longer 中任何一个更长名字覆盖**的出现区间（不重叠、按位置升序）。

    longer 只应传「姓氏 + 本名」型的更长候选（见 Extractor.surname_extensions）：
    别的超串（「姜望缓缓」这类切坏的片段）不扣，否则真名的计数会被噪声候选吃掉（实测姜望 45508 → 25307）。
    """
    covered: list[tuple[int, int]] = []
    for other in longer:
        start = sentence.find(other)
        while start != -1:
            covered.append((start, start + len(other)))
            start = sentence.find(other, start + 1)
    spans = []
    start = sentence.find(name)
    while start != -1:
        end = start + len(name)
        if not any(a <= start and end <= b for a, b in covered):
            spans.append((start, end))
        start = sentence.find(name, end)
    return spans


def clean_candidate(name: str) -> str:
    return name.strip(" ，。！？；：、‘’“”（）()《》<>\t\r\n")


@dataclass
class Candidate:
    name: str
    mentions: int = 0
    # T9-1：独占提及——扣掉落在「姓氏+本名」更长候选里的出现（叶青雨 ⊃ 青雨）。
    # mentions（字面子串计数）保留原语义，继续给别名合并用；报告 / --min-mentions / 排序用这一个。
    exclusive_mentions: int = 0
    # T9-3 名字性信号的原料：本名每次字面出现的左/右邻字（句首/句末记 ""）。只记本名，不随合并累加。
    left_chars: Counter = field(default_factory=Counter)
    # T9-5：本名每次出现后、同一句内（不跨引号）先出现的是「她」还是「他」——按出现次数归一的性别证据。
    she_follow: int = 0
    he_follow: int = 0
    right_chars: Counter = field(default_factory=Counter)
    chapters: set[int] = field(default_factory=set)
    female_score: float = 0.0
    male_score: float = 0.0
    source_score: float = 0.0
    aliases: set[str] = field(default_factory=set)
    # 被四个识别模式命中的次数（T8-2）：用来区分"名字"与"字面高频的词"。
    # source_score 是加权分，这里单独记纯计数，便于规则读取。
    pattern_mentions: int = 0
    gender_evidence: list[str] = field(default_factory=list)
    # T9-1 元数据：与 gender_evidence / trait_evidence 逐条对齐的章节号（口径同 chapters）与 1-based 原文行号。
    gender_evidence_chapters: list[int] = field(default_factory=list)
    gender_evidence_lines: list[int] = field(default_factory=list)
    traits: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    trait_evidence: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    trait_evidence_chapters: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    trait_evidence_lines: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))

    @property
    def net_score(self) -> float:
        # 候选姓名可信度与性别证据必须分开；“经常说话”不等于“女性”。
        return self.female_score - self.male_score


# 归因输出的格式版本：schema 变化时必须递增，让下游能识别自己读到的是哪一版。
DIAGNOSTICS_VERSION = 1

# T9-6：这两种拒绝只说明「不像中文姓名」，音译名（佛尔思、嘉德丽雅）会落在这里；有外部佐证时可收回。
RESCUABLE_REJECTIONS = ("not_surname_3char_no_feminine", "not_surname_long")

# T9-5：名字后紧跟的第一个人称代词（同句、不跨引号、20 字内）。
PRONOUN_WINDOW = 20
PRONOUN_STOP = re.compile(r"[。！？!?\n“”\"]")

# 产物顶层 tool_version：必须与 pyproject.toml 的 [project].version 一致（tests/test_metadata.py 钉住）。
TOOL_VERSION = "0.1.0"

# 「姓氏 + 称谓」合并到同前缀候选时，目标被识别成名字的比例下限（T8-2 / D3）。
# 定义：目标的模式命中次数 / 目标的 mentions。名字的特征是"出现时总在名字的句法位置"，
# 而"文本里恰好包含这几个字"的词（灰雾、是一、天使…）这个比值极低。实测依据见 merge_aliases 的注释。
MIN_PATTERN_RATIO_FOR_MERGE_TARGET = 0.005


def new_diagnostics() -> dict:
    """空归因骨架。只有显式打开 --diagnostics 才创建，默认路径上不存在这个对象。"""
    return {
        "version": DIAGNOSTICS_VERSION,
        "input_bytes": 0,
        "input_chars": 0,
        "chapters": 0,
        "patterns": {},
        "rejection_reasons": defaultdict(int),
        "candidates": 0,
        "candidates_after_merge": None,
        "reported": None,
        "min_mentions": None,
        "min_score": None,
        "timings": {},
        "stage": "all",
    }


class Extractor:
    def __init__(self, rules: dict):
        self.rules = rules
        # 最近一次 run_pipeline 中 --protagonist 点名、却没有任何候选（含别名）与之同名的名字；
        # CLI 据此打提示（"你点名的角色没进报告"不能静默）。每次 run_pipeline 开头重置。
        self.unmatched_includes: list[str] = []
        # T9-4：最近一次 merge_aliases 里被守卫拦下 / 由同位语并入的 (别名, 目标, 原因)，供 --diagnostics 读取。
        self.merge_guard_log: list[tuple[str, str, str]] = []
        self._n_chapters = 0
        self.name_initials: set[str] | None = None
        self.surnames = set(rules["surnames"])
        self.stopwords = set(rules["name_stopwords"])
        self.female_titles = list(rules["female_titles"])
        self.male_titles = list(rules["male_titles"])
        # 单字性别标记的复合词例外（旧规则文件里没有这个键时为空 = 旧行为，不崩）。
        self.marker_compounds = list(rules.get("marker_compound_exceptions", []))
        # 特征组合规则（数据驱动；旧规则文件无此键时为空）：颜色/材质修饰词 × 衣物后缀字这类枚举不完的组合。
        self.trait_combo_patterns: dict[str, list[re.Pattern[str]]] = {}
        for combo in rules.get("trait_combo_rules", []):
            category, pattern = combo.get("category"), combo.get("pattern")
            if category and pattern:
                self.trait_combo_patterns.setdefault(category, []).append(re.compile(pattern))
        self.speech_verbs = "|".join(map(re.escape, rules["speech_verbs"]))
        self.action_verbs = "|".join(map(re.escape, rules["action_verbs"]))
        titles = "|".join(map(re.escape, self.female_titles + self.male_titles))
        self.patterns = [
            # 姓名使用非贪婪匹配，避免把“林婉儿笑道”误切成“林婉儿笑 + 道”。
            (re.compile(rf"(?<![{CJK}])([{CJK}]{{2,4}}?)(?=(?:{self.speech_verbs}|{self.action_verbs}))"), 1.7),
            (re.compile(rf"(?<![{CJK}])([{CJK}]{{1,3}}(?:{titles}))"), 2.0),
            (re.compile(rf"(?:名叫|名为|叫作|叫做|自称|唤作)([{CJK}]{{2,4}})"), 2.5),
            (re.compile(rf"[“\"]([{CJK}]{{2,4}})[”\"](?=(?:{self.speech_verbs}|{self.action_verbs})?)"), 0.7),
        ]

    def normalize_name(self, name: str) -> str:
        name = clean_candidate(name)
        for prefix in sorted(self.rules.get("candidate_leading_noise", []), key=len, reverse=True):
            if name.startswith(prefix) and len(name) - len(prefix) >= 2:
                name = name[len(prefix) :]
                break
        for suffix in sorted(self.rules.get("candidate_trailing_noise", []), key=len, reverse=True):
            if name.endswith(suffix) and len(name) - len(suffix) >= 2:
                name = name[: -len(suffix)]
                break
        return name

    def reject_reason(self, name: str) -> str | None:
        """名字被拒的**具体原因**；通过时返回 None。

        这是 plausible_name 的**唯一**实现：判定条件与本函数逐条一一对应，
        所以"拒绝原因直方图"（--diagnostics）的每个键都对应一条真实可达的拒绝路径，
        不会出现"统计说有这条分支、代码里却没有"的假证据。
        每个 return 的字符串就是直方图里的键名；新增拒绝分支时**必须同时补键**，
        tests/test_diagnostics.py 会用 AST 枚举本函数的 return 条数来钉住这一点。
        """
        name_length = len(name)
        if not (2 <= name_length <= 5):
            return "len_out_of_range"
        if name in self.stopwords:
            return "stopword"
        if any(w in name for w in self.rules["name_forbidden_fragments"]):
            return "forbidden_fragment"
        # 称谓只能出现在**末尾**：中间的称谓说明这是被切坏的片段（实测 沈师姐回 = 沈 + 师姐 + 回）。
        for title in self.female_titles + self.male_titles:
            position = name.find(title)
            if 0 < position and position + len(title) < name_length:
                return "title_in_middle"
        # 禁前缀检查必须在称谓分支**之前**：否则 他是大师兄 会因为"以称谓结尾"而绕过它（实测）。
        if name[0] in self.rules.get("forbidden_name_prefixes", ""):
            return "forbidden_prefix"
        # T9-2：末字是常见虚词（P1/P2 的惰性匹配会吃进右邻：昧月轻 / 昧月一 / 昧月却 / 也是）。
        # 放在称谓分支之前；以称谓结尾的名字末字不会落在这个集合里。旧规则文件无此键时为空 = 旧行为。
        if name[-1] in self.rules.get("forbidden_name_tail_chars", ""):
            return "forbidden_tail_char"
        matched_title = next((t for t in self.female_titles + self.male_titles if name.endswith(t)), None)
        if matched_title:
            prefix = name[: -len(matched_title)]
            if not prefix:
                return "empty_title_prefix"
            if prefix in self.rules.get("forbidden_title_prefixes", []):
                return "forbidden_title_prefix"
            return None
        if name.endswith(tuple(self.rules.get("forbidden_name_suffixes", []))):
            return "forbidden_suffix"
        # 下面必须与旧实现末行**逐字等价**：旧式是
        #   name[0] in surnames or len(name) == 2 or (len(name) == 3 and has_feminine_char)
        # 这里只是把同一个析取式拆成"哪个方向命中了"，接受/拒绝集合必须一模一样——
        # 本卡是纯观测卡，任何召回变化（例如把"姓氏开头"当成 2 字/3 字分支的前置条件，
        # 从而拒掉沈青梧、李慕白这类"姓氏开头但无女性化用字"的名字）都属于 T8-4，不属于这里。
        # 注意 2 字名要么是姓氏开头、要么满足 len == 2，两条都通向"接受"：
        # 所以 not_surname_2char 在旧式下**不可达**，不能为了好看把它写成一条真假分支。
        if name[0] in self.surnames:
            return None
        if name_length == 2:
            # 旧式的 len(name) == 2 是**无条件接受**：所以 2 字名在这里同样通过，而不是走下面的拒绝分支。
            # 结果是 2 字名一律接受（「转身」「是一」都过），这也是 T8-4 要收紧的那道闸门本身。
            return None
        if name_length == 3:
            has_feminine_char = any(ch in self.rules["feminine_name_chars"] for ch in name)
            return None if has_feminine_char else "not_surname_3char_no_feminine"
        return "not_surname_long"

    def plausible_name(self, name: str) -> bool:
        """接受/拒绝判定。等于 reject_reason(name) is None——两条路径共用同一份条件，不会漂移。"""
        return self.reject_reason(name) is None

    def find_candidates(
        self,
        chapters: list[tuple[int, str]],
        diagnostics: dict | None = None,
    ) -> dict[str, Candidate]:
        """扫描四个模式产出候选。diagnostics 非 None 时**顺带**记归因（不改判定、不改结果）。"""
        found: dict[str, Candidate] = {}
        # 诊断用：每个模式的原始命中/存活命中/见过的名字；None 时整段是死代码，零开销。
        stats: dict | None = None
        rejections: dict | None = None
        known_names: set[str] = set()
        counted_rejections: set[str] = set()
        # T9-6 召回：只因「非姓氏开头的 3/4 字名」被拒的名字先暂存，扫完后有**外部佐证**才收回（见 _rescue）。
        rescue_cfg = self.rules.get("candidate_rescue") or {}
        rescue_cfg = rescue_cfg if rescue_cfg.get("enabled") else None
        pool: dict[str, Candidate] = {}
        if diagnostics is not None:
            stats = {}
            rejections = diagnostics["rejection_reasons"]
            # 按模式下标做键：正则串本身太长不适合作 JSON 键，下标还顺带钉住了四个模式的身份。
            for pattern_index, (pattern, _) in enumerate(self.patterns):
                stats[pattern_index] = {
                    "pattern": pattern.pattern, "raw_hits": 0, "kept_hits": 0, "names": set(),
                }
        for chapter_no, chapter_text in chapters:
            for sentence in split_sentences(chapter_text):
                for pattern_index, (pattern, weight) in enumerate(self.patterns):
                    pattern_stats = None if stats is None else stats[pattern_index]
                    for match in pattern.finditer(sentence):
                        if pattern_stats is not None:
                            pattern_stats["raw_hits"] += 1
                        name = self.normalize_name(match.group(1))
                        if not self.plausible_name(name):
                            if rescue_cfg and self.reject_reason(name) in RESCUABLE_REJECTIONS:
                                held = pool.setdefault(name, Candidate(name=name))
                                held.source_score += weight
                                held.pattern_mentions += 1
                                held.chapters.add(chapter_no)
                            if rejections is not None and name not in counted_rejections:
                                counted_rejections.add(name)
                                rejections[self.reject_reason(name)] += 1
                            continue
                        if pattern_stats is not None:
                            pattern_stats["kept_hits"] += 1
                            pattern_stats["names"].add(name)
                        item = found.setdefault(name, Candidate(name=name))
                        item.source_score += weight
                        item.pattern_mentions += 1
                        item.chapters.add(chapter_no)
        if stats is not None and diagnostics is not None:
            # distinct_names 是该模式产出过的**全部**不同名字；new_names 只算此前任何模式都没产出的那些。
            # 两者都按模式下标（P1..P4 的先后）做前缀账：P1 的 new_names 恒等于它的 distinct_names，
            # 各模式 new_names 之和 == 候选数（已在 tests/test_diagnostics.py 里钉住）。
            for pattern_index in sorted(stats):
                pattern_stats = stats[pattern_index]
                names = pattern_stats.pop("names")
                diagnostics["patterns"][pattern_index] = {
                    "pattern": pattern_stats["pattern"],
                    "raw_hits": pattern_stats["raw_hits"],
                    "kept_hits": pattern_stats["kept_hits"],
                    "distinct_names": len(names),
                    "new_names": len(names - known_names),
                }
                known_names |= names
        if rescue_cfg:
            self._rescue(found, pool, chapters, rescue_cfg)
        return found

    def _rescue(self, found: dict[str, Candidate], pool: dict[str, Candidate], chapters, cfg: dict) -> None:
        """收回被「非姓氏长名」拒掉的名字（佛尔思、嘉德丽雅这类音译名）。需要两条之一的外部佐证：
          a) 「名字+女称谓」本身已是候选（佛尔思女士 / 佛尔思小姐），模式命中合计 ≥ min_titled_mentions
             （只出现一次的「告诉我母亲」「吸血鬼女王」不算）；
          b) 原文里「“称号”名字」引号同位语反复出现（“隐者”嘉德丽雅），且称号本身是候选。
        外加名字自己的模式命中数 ≥ min_pattern_hits。收回的名字之后照常过名字性信号与报告门槛。"""
        self.rescued_names = []
        self._dot_heads = Counter()
        for _, chapter_text in chapters:
            for m in re.finditer(rf"(?<![{CJK}])([{CJK}])·[{CJK}]", chapter_text):
                self._dot_heads[m.group(1)] += 1
        # T9-8：能当「单字前缀+称谓」归属的首字——已收或暂存的 3/4 字非称谓名（模式命中 ≥ min_pattern_hits）的首字。
        titles_all = tuple(self.female_titles + self.male_titles)
        #    要求模式命中 ≥ min_initial_pattern_hits，且前两字本身不是候选（好像在 = 好像 + 在，不是名字）。
        self.name_initials = {
            k[0] for src in (found, pool) for k, v in src.items()
            if len(k) >= 3 and not k.endswith(titles_all) and k[:2] not in found
            and v.pattern_mentions >= cfg.get("min_initial_pattern_hits", 10)
        }
        if not pool:
            return
        quoted: Counter = Counter()
        appos = re.compile(rf"[“\"‘]([{CJK}]{{2,6}})[”\"’]([{CJK}]{{3,4}})")
        for _, chapter_text in chapters:
            for m in appos.finditer(chapter_text):
                if m.group(1) in found:
                    tail = m.group(2)
                    for k in (3, 4):
                        if tail[:k] in found:  # “正义”奥黛丽本… 的真名已是候选：不另收更长的切片
                            break
                        if tail[:k] in pool:
                            quoted[tail[:k]] += 1
                            break
        for name, held in pool.items():
            if name in found or held.pattern_mentions < cfg.get("min_pattern_hits", 3):
                continue
            titled = sum(found[name + t].pattern_mentions for t in self.female_titles if name + t in found)
            titled = titled >= cfg.get("min_titled_mentions", 3)
            # c) T9-8：「名字首字 + 女称谓」是候选（夜姑娘→夜阑儿、照师姐→照无颜、卓师姐→卓清如）：
            #    单字非姓前缀的称呼只有这样才说得通；要求名字自己模式命中更多（min_initial_pattern_hits）。
            #    该首字下已有 3 字以上的已收全名（竹素瑶 之于 竹姑娘）时称呼已有归属，不再收第二个（竹碧琼 留作已知漏抽）。
            #    「已收全名」= 同首字、3 字、非称谓结尾、模式命中 ≥ min_pattern_hits 的候选（非姓首字的 3 字名能进候选，
            #    本身就因为带女性化用字，如 竹素瑶）；4 字串（夜之侵袭）不算。
            explained = name[:2] in found or any(k[0] == name[0] and len(k) == 3 and not k.endswith(tuple(self.female_titles + self.male_titles))
                            and v.pattern_mentions >= cfg.get("min_pattern_hits", 3) for k, v in found.items())
            #    T10：姐妹（竹碧琼/竹素瑶）由合并侧的 ambiguous_siblings 判归属，这条挡板可关（block_when_initial_explained）。
            if not cfg.get("block_when_initial_explained", True) and name[:2] not in found:
                explained = False  # 「么些年」= 么些 + 年：前两字本身是候选的仍挡
            if not titled and not explained and cfg.get("min_initial_pattern_hits") and held.pattern_mentions >= cfg["min_initial_pattern_hits"]:
                # 只数自身被识别 ≥2 次的称谓形：「么圣女」「么妹妹」各 1 次是「那么/怎么」后的切片。
                initial = sum(found[name[0] + t].pattern_mentions for t in self.female_titles
                              if name[0] + t in found and found[name[0] + t].pattern_mentions >= 2)
                titled = initial >= cfg.get("min_titled_mentions", 3)
            # d) T9-8：名字后接「她」占压倒多数（特雷茜）。只对模式命中够多的暂存名逐句数一次，开销有限。
            she_ok = False
            if not titled and cfg.get("min_she_follow") and held.pattern_mentions >= cfg.get("min_initial_pattern_hits", 10) // 3:
                she = he = 0
                for _, chapter_text in chapters:
                    start = chapter_text.find(name)
                    while start != -1:
                        tail = PRONOUN_STOP.split(chapter_text[start + len(name) : start + len(name) + PRONOUN_WINDOW], 1)[0]
                        a, b = tail.find("她"), tail.find("他")
                        if a >= 0 and (b < 0 or a < b):
                            she += 1
                        elif b >= 0:
                            he += 1
                        start = chapter_text.find(name, start + 1)
                share = (she + 1) / (she + he + 2)
                she_ok = she >= cfg["min_she_follow"] and share >= cfg.get("min_she_share", 0.7)
            if titled or she_ok or quoted[name] >= cfg.get("min_quoted_hits", 3):
                found[name] = held
                self.rescued_names.append(name)

    def expand_mentions(self, candidates: dict[str, Candidate], chapters: list[tuple[int, str]] | list[tuple[int, str, int]]) -> None:
        # 长度降序：旧实现用它决定同句多候选的处理顺序；索引化之后每个候选只做累加 / 集合写入 /
        # 逐候选打分，顺序已无行为含义（见 names_present 的说明）。保留排序只为让桶内顺序**稳定**，
        # 免得将来有人从"顺序为何变了"这种症状开始查（复审 r003 F5）。
        names = sorted(candidates, key=len, reverse=True)
        # T8-1：包含关系的必要条件是首字在句子里。全书 4,559 候选 × 约 15 万分句的逐个包含检查
        # 是 25 分钟里最大的一笔开销；按首字建索引后只对「首字确实出现过」的候选做检查，
        # 这里的每个候选只做累加 / 集合写入 / 逐候选打分，与同句内的先后无关（见 names_present 的说明）。
        name_index = index_by_first_char(names)
        extensions = self.surname_extensions(candidates)
        for ch_entry in chapters:
            if len(ch_entry) == 3:
                chapter_no, chapter_text, base_line = ch_entry
            else:
                chapter_no, chapter_text = ch_entry
                base_line = 1
            for sentence, line_no in split_sentences_with_lines(chapter_text, base_line):
                present = names_present(name_index, sentence)
                for name in present:
                    item = candidates[name]
                    count = sentence.count(name)
                    item.mentions += count
                    start = sentence.find(name)
                    while start != -1:
                        item.left_chars[sentence[start - 1 : start]] += 1
                        item.right_chars[sentence[start + len(name) : start + len(name) + 1]] += 1
                        tail = PRONOUN_STOP.split(sentence[start + len(name) : start + len(name) + PRONOUN_WINDOW], 1)[0]
                        she, he = tail.find("她"), tail.find("他")
                        if she >= 0 and (he < 0 or she < he):
                            item.she_follow += 1
                        elif he >= 0:
                            item.he_follow += 1
                        start = sentence.find(name, start + 1)
                    longer = [x for x in extensions.get(name, ()) if x in sentence]
                    item.exclusive_mentions += len(exclusive_spans(sentence, name, longer)) if longer else count
                    item.chapters.add(chapter_no)
                    self.score_gender(item, sentence, chapter_no, line_no)

    def surname_extensions(self, candidates: dict[str, Candidate]) -> dict[str, list[str]]:
        """短名 → 以「1–2 字姓氏前缀 + 短名」构成的更长候选（叶青雨 → 青雨）。只有这类超串参与独占扣减。"""
        compound = self.rules["surnames"]
        result: dict[str, list[str]] = defaultdict(list)
        for longer in candidates:
            for k in (1, 2):
                short, prefix = longer[k:], longer[:k]
                if len(short) < 2 or short not in candidates:
                    continue
                if (k == 1 and prefix in self.surnames) or (k == 2 and prefix in compound):
                    result[short].append(longer)
        return result

    def _labels(self, candidates: dict[str, Candidate]) -> set[str]:
        """候选名 + 已并入的别名（合并后「莎伦小姐」只是莎伦的别名，「和莎伦小姐」也得认出是吸收前缀）。按字典身份缓存。"""
        cache = getattr(self, "_label_cache", None)
        if cache is None or cache[0] is not candidates or cache[1] != len(candidates):
            labels = set(candidates)
            for item in candidates.values():
                labels |= item.aliases
            cache = (candidates, len(candidates), labels)
            self._label_cache = cache
        return cache[2]

    def _initial_exempt(self, head: str, item: Candidate, candidates, cfg: dict) -> bool:
        """T9-9：单字前缀没有 3/4 字名佐证时的两条豁免（orphan_initial_exempt）：
          dot    —— 原文里「该字·」（音译名的间隔号写法，休·迪尔查）出现 ≥ min_dot_hits 次；
          single —— 该字只和**一种**称谓连用（静贵妃、湘夫人；普通说法 好妹妹/好姐姐/好弟弟、本姑娘/本公主…
                    会跟多种称谓搭配），且本称呼模式命中 ≥ min_pattern、出现 ≥ min_mentions。"""
        ex = cfg.get("orphan_initial_exempt") or {}
        if not ex:
            return False
        dots = getattr(self, "_dot_heads", None)
        if dots is not None and dots.get(head, 0) >= ex.get("min_dot_hits", 5):
            return True
        titles_all = self.female_titles + self.male_titles
        combos = {t for t in titles_all if head + t in self._labels(candidates)}
        return (len(combos) == 1 and item.pattern_mentions >= ex.get("min_pattern", 5)
                and item.mentions >= ex.get("min_mentions", 10))

    def _speech_opener(self, item: Candidate, cfg: dict) -> bool:
        so = cfg.get("speech_opener") or {}
        lo, ro = sum(item.left_chars.values()), sum(item.right_chars.values())
        if not so or lo < so.get("min_occ", 30) or not ro:
            return False
        left_q = sum(item.left_chars.get(c, 0) for c in "“\"") / lo
        right_q = sum(item.right_chars.get(c, 0) for c in "”\"") / ro
        return left_q >= so["min_left_open_quote"] and right_q < so["max_right_close_quote"]

    def _right_closure(self, item: Candidate) -> float:
        cfg = self.rules.get("name_signal") or {}
        closed = set(cfg.get("boundary_chars", "")) | {"", "的"} | {t[0] for t in self.female_titles + self.male_titles}
        occ = sum(item.right_chars.values())
        return sum(v for k, v in item.right_chars.items() if k in closed) / occ if occ else 1.0

    def name_signal(self, item: Candidate, candidates: dict[str, Candidate], skip_stem: bool = False) -> tuple[str | None, dict]:
        """T9-3 名字性信号（与性别无关）：返回 (拒绝键或 None, 特征)。规则键 name_signal 缺省 / enabled=false 时恒通过。

        特征（全部来自本名的字面出现，见 流程书/女角色改进计划.md T9-3 (a)(b)(d)）：
          pattern_ratio  = 四个识别模式命中数 / 字面 mentions（名字总在名字的句法位置，词不是）；
          boundary_ratio = 左邻是句首/标点的占比；左邻若被同一个字垄断（≥ fullname_left_share，叶青雨→青雨、
                           罗刹明月净→明月净）也算边界——那是更长全名的一部分，不是词内碎片；
          stem_share     = 右邻被同一个非虚词汉字垄断的占比（魔术→魔术师、卡特→卡特琳）。
        """
        cfg = self.rules.get("name_signal") or {}
        name = item.name
        occ = max(1, sum(item.left_chars.values()))
        boundary = set(cfg.get("boundary_chars", ""))
        followers = set(cfg.get("follower_chars", ""))
        cjk = re.compile(rf"[{CJK}]")
        b = sum(v for k, v in item.left_chars.items() if k == "" or k in boundary)
        left_top = max((v for k, v in item.left_chars.items() if k and cjk.match(k)), default=0)
        if left_top / occ >= cfg.get("fullname_left_share", 1.1):
            b += left_top
        stem = max((v for k, v in item.right_chars.items() if k and cjk.match(k) and k not in followers), default=0)
        feats = {
            "pattern_ratio": item.pattern_mentions / max(1, item.mentions),
            "boundary_ratio": b / occ,
            "stem_share": stem / occ,
        }
        if not cfg.get("enabled"):
            return None, feats
        # T12 群体称呼（尤氏等、邢王二夫人、众位小姐）：封闭的结构标记，不是人名词表。
        grp = cfg.get("group_term") or {}
        if grp.get("enabled") and (name.endswith(tuple(grp.get("suffixes", ()))) or any(m in name for m in grp.get("contains", ()))):
            return "name_signal_group_term", feats
        if not skip_stem and feats["stem_share"] >= cfg["stem_right_share"] and feats["pattern_ratio"] < cfg["stem_max_pattern_ratio"]:
            return "name_signal_stem", feats
        if feats["pattern_ratio"] < cfg["literal_max_pattern_ratio"] and feats["boundary_ratio"] < cfg["literal_min_boundary"]:
            return "name_signal_literal", feats
        if name[-1] in cfg.get("pronoun_tail_chars", ""):
            return "name_signal_pronoun_tail", feats
        # T9-6 右侧封闭度：名字后面多是标点 / 的 / 称谓首字（叶青雨，、叶青雨的、奥黛丽小姐）；
        # 词后面多接动词、代词（毕竟是 / 直到现在 / 跟你说 / 有个人）。称谓结尾的名字不查（称谓后接什么都正常）。
        titles_all = tuple(self.female_titles + self.male_titles)
        closure = feats["right_closure"] = self._right_closure(item)
        rocc = sum(item.right_chars.values())
        if (cfg.get("right_closure_min", 0) and not name.endswith(titles_all)
                and rocc >= cfg.get("right_closure_min_occ", 30) and closure < cfg["right_closure_min"]):
            return "name_signal_right_open", feats
        # 更长称呼的切片（今皇后 ⊂ 当今皇后）：称谓结尾、左邻被同一个字垄断、且「该字+本名」本身是候选。
        if cfg.get("title_fragment_left_share", 0) and name.endswith(titles_all):
            top = max(((k, v) for k, v in item.left_chars.items() if k and cjk.match(k)), key=lambda kv: kv[1], default=None)
            if top and top[1] / occ >= cfg["title_fragment_left_share"] and top[0] + name in self._labels(candidates):
                return "name_signal_title_fragment", feats
        # T9-7 开口语：左邻多是开引号、右邻几乎不是闭引号（“多谢…” “敢问…” “走吧。”）——说话的开头，不是名字；
        # 两侧都是引号的（“审判”“仲裁人”）是被引起来的代号，不算。
        if not name.endswith(titles_all) and self._speech_opener(item, cfg):
            return "name_signal_speech_opener", feats
        # T9-8「单字 + 称谓」：前缀是单个非姓字时，只有这个字确实是某个 3/4 字名的首字才算称呼真人
        #（夜姑娘←夜阑儿、照师姐←照无颜、凰姑娘←凰今默）；否则是普通说法（好妹妹、叫姐姐、本姑娘、傻姑娘）。
        initials = getattr(self, "name_initials", None)
        if cfg.get("orphan_initial_title") and initials is not None and name.endswith(titles_all) and len(name) >= 2:
            t = next(t for t in sorted(titles_all, key=len, reverse=True) if name.endswith(t))
            head = name[: -len(t)]
            if len(head) == 1 and head not in self.surnames and head not in initials and not self._initial_exempt(head, item, candidates, cfg):
                return "name_signal_orphan_initial", feats
        # 「词 + 称谓」（毕竟娘亲、相较于妹妹、多谢姑娘）：前缀本身是候选、且前缀被判为词（右侧不封闭 / 开口语）。
        if cfg.get("right_closure_min", 0) and name.endswith(titles_all):
            t = next(t for t in sorted(titles_all, key=len, reverse=True) if name.endswith(t))
            head = candidates.get(name[: -len(t)])
            if head is not None and len(head.name) >= 2 and not head.name.endswith(titles_all):
                hocc = sum(head.right_chars.values())
                if hocc >= cfg.get("right_closure_min_occ", 30) and (
                        self._right_closure(head) < cfg["right_closure_min"] or self._speech_opener(head, cfg)):
                    return "name_signal_word_prefix", feats
        titles = set(self.female_titles + self.male_titles)
        if any(w in name and w != name for w in self.stopwords if len(w) >= 2 and w not in titles):
            return "name_signal_stopword_inside", feats
        if len(name) >= 3 and name[0] in cfg.get("absorbed_prefix_chars", "") and name[1:] in self._labels(candidates):
            return "name_signal_absorbed_prefix", feats
        return None, feats

    def merge_guard_reason(self, alias: str, prefix: str, target_name: str, candidates: dict[str, Candidate]) -> str | None:
        """「X+女称谓 → 同前缀全名」的 T9-4 必要条件；返回拦截原因或 None。

        1) 前缀不是目标全名本身时必须是姓氏（1 字在 surnames、2 字在复姓串里）：好姐姐→好像、当姐姐→当然 这类
           "词首字+称谓"不是"姓+称谓"；
        2) 目标必须通过 T9-3 名字性信号（温姑娘→温柔、静贵妃→静默：目标是词）；
        3) 性别不矛盾：目标自身（合并前）的男性证据不得多于女性证据（林姑娘→林正仁、李姑娘→李龙川、姜姑娘→姜望）。
        """
        cfg = self.rules.get("merge_guard") or {}
        if not cfg.get("enabled"):
            return None
        target = candidates[target_name]
        ratio = target.pattern_mentions / max(1, target.mentions)
        if prefix != target_name:
            is_surname = (len(prefix) == 1 and prefix in self.surnames) or (len(prefix) == 2 and prefix in self.rules["surnames"])
            # 非姓氏前缀（戏姑娘→戏命、蛛姑娘→蛛兰若）只在目标自己**强烈**像名字时放行（模式命中比 ≥ 阈值）。
            # 单字前缀 = 3 字以上全名的首字（竹姑娘→竹素瑶：首字不在姓氏表的人名）也放行，名字性在下面再查。
            full_name_initial = len(prefix) == 1 and len(target_name) >= 3 and target_name.startswith(prefix)
            if not is_surname and not full_name_initial and ratio < cfg.get("non_surname_min_pattern_ratio", 1.1):
                return "prefix_not_surname"
        # 名字性：只用"字面词"与结构判据；右邻垄断（stem）不用——霍尔→霍尔伯爵 这类"名字是更长称呼的前半"不是词干。
        reason = self.name_signal(target, candidates, skip_stem=True)[0] if self.rules.get("name_signal", {}).get("enabled") else None
        if reason is not None:
            return "target_not_name"
        # T9-5：「只有姓相同」的合并（前缀 ≠ 目标全名）还要有共指证据，且性别不矛盾（按出现次数归一）：
        #   lift  = 别名所在章里目标也出现的比例 / 目标全书章覆盖率——目标几乎章章都在（主角）时 lift≈1，说明不了共指
        #           （姜姑娘/姜仙子/姜女侠→姜望 lift 1.12）；
        #   she   = 目标本名后紧跟「她」的平滑比例 (她+1)/(她+他+2)。同章共现不足且 she 低 = 另一个人（林姑娘→林正仁、
        #           李姑娘→李龙川、雷贵妃→雷占乾）。绝对性别分不用（a985a84 实测误拦真女角色）。
        t97 = cfg.get("alias_context") or {}
        if t97.get("enabled"):
            reason = self._alias_context_reason(alias, prefix, target_name, candidates, t97)
            if reason:
                return reason
        coref = cfg.get("coref") or {}
        if prefix != target_name and coref.get("enabled") and self._n_chapters:
            alias_ch = candidates[alias].chapters
            overlap = len(alias_ch & target.chapters) / max(1, len(alias_ch))
            base = len(target.chapters) / self._n_chapters
            lift = overlap / max(base, 1e-9)
            she = (target.she_follow + 1) / (target.she_follow + target.he_follow + 2)
            # 两条都要：共指证据弱（目标处处都在 / 很少同章）**且**目标本身后接「她」的比例低。
            # 只看共指会误拦短文本（examples/sample.txt 的 林小姐→林婉儿：两章都在，lift=1）。
            weak_coref = lift < coref["min_lift"] or overlap < coref["min_overlap"]
            if weak_coref and she < coref["max_she_share"]:
                return "coref_gender_conflict"
        return None

    def _alias_context_reason(self, alias: str, prefix: str, target_name: str, candidates, cfg: dict) -> str | None:
        """T9-7 别名语境：
          longer_prefix  —— 别名以「比姓更长、且不是目标」的候选开头（宁王妃 = 宁王 + 妃，不是 宁 + 王妃）；
          named_other    —— 原文在别名前紧挨着点了另一个同前缀全名（“竹碧琼……竹师姐”），别名指那个人；
          concessive     —— 前缀字是让步框架的引导字、且别名每次出现后都紧跟框架尾字（“连皇后都知道了”，连=甚至）；
          low_she_title  —— 「全名+称谓」并回全名时，称谓形只占全名出现的极小比例、且全名本身后接「她」极少
                            （有个媳妇→有个、会儿师妹→会儿：前缀是词，不是人）。"""
        text = getattr(self, "_merge_text", "") or ""
        # T12 配偶所属格单独出现（旺儿媳妇、周瑞家的）：别名 = 目标全名 + 配偶称谓，且目标本身按已有代词信号偏男
        #（全名后「他」多于「她」）——说的是他的妻子，不是他。不并，别名单独成条。
        sp = cfg.get("spouse_of_male") or {}
        if sp.get("enabled") and alias != target_name and alias.startswith(target_name) \
                and alias[len(target_name):] in sp.get("titles", ()):
            t = candidates.get(target_name)
            if t is not None and t.he_follow > t.she_follow:
                return "alias_spouse_of_male"
        # 所属格（“特雷茜母亲卡特琳娜”）：称谓形后面紧跟另一个候选名——称谓说的是那个人，不是前缀里的人。
        if cfg.get("possessive_followed_by_name") and text and alias != target_name:
            spans = [m.end() for m in re.finditer(re.escape(alias), text)]
            labels = self._labels(candidates)
            # 只认 3/4 字、自己反复被识别成名字的候选（模式命中比 ≥ 合并门槛）：2 字串太容易撞上「不必」「笑道」之类。
            def is_name(x: str) -> bool:
                c = candidates.get(x)
                return c is not None and c.pattern_mentions / max(1, c.mentions) >= MIN_PATTERN_RATIO_FOR_MERGE_TARGET
            followed = sum(1 for e in spans if any(text[e : e + k] != target_name and is_name(text[e : e + k])
                                                   for k in (4, 3)))
            if spans and followed * 2 >= len(spans):
                return "alias_possessive"
        if prefix != target_name:
            for k in range(len(alias) - 1, len(prefix), -1):
                head = alias[:k]
                if head in candidates and head != target_name and not target_name.startswith(head):
                    return "alias_longer_prefix"
            if text:
                gap = re.escape(cfg.get("named_other_gap_chars", "…，、 "))
                hits = re.findall(rf"({re.escape(prefix)}[{CJK}]{{1,2}})[{gap}]{{0,3}}{re.escape(alias)}", text)
                others = [h for h in hits if h != target_name and not target_name.startswith(h) and h != alias[: len(h)]]
                if others and len(others) >= len(hits) - len(others):
                    return "alias_named_other"
            frame = cfg.get("concessive_frame") or {}
            if text and prefix in frame.get("lead_chars", ""):
                tails = [text[m.end() : m.end() + 1] for m in re.finditer(re.escape(alias), text)]
                if tails and all(t and t in frame.get("tail_chars", "") for t in tails):
                    return "alias_concessive_frame"
        else:
            target = candidates[target_name]
            alias_item = candidates[alias]
            share = alias_item.pattern_mentions / max(1, target.mentions)
            she = (target.she_follow + 1) / (target.she_follow + target.he_follow + 2)
            if share < cfg.get("low_she_max_title_share", 0) and she < cfg.get("low_she_max_she_share", 0):
                return "alias_low_she_title"
        return None

    def quoted_apposition_pairs(self, candidates: dict[str, Candidate], text: str) -> list[tuple[str, str]]:
        cfg = (self.rules.get("merge_guard") or {}).get("quoted_apposition") or {}
        if not cfg.get("enabled"):
            return []
        pattern = re.compile(rf"[“\"‘]([{CJK}]{{2,6}})[”\"’]([{CJK}]{{2,6}})")
        partners: dict[str, Counter] = defaultdict(Counter)
        for m in pattern.finditer(text):
            code = m.group(1)
            if code not in candidates:
                continue
            tail = m.group(2)
            real = next((tail[:k] for k in range(len(tail), 1, -1) if tail[:k] in candidates and tail[:k] != code), None)
            if real is not None and self._apposition_target_ok(candidates[real], candidates):
                partners[code][real] += 1
        pairs = []
        for code, counter in partners.items():
            real, hits = counter.most_common(1)[0]
            total = sum(counter.values())
            if hits < cfg.get("min_hits", 3) or hits / total < cfg.get("min_dominance", 0.8):
                continue
            if hits / max(1, candidates[code].mentions) < cfg.get("min_share_of_code", 0.1):
                continue
            # 性别一致（女性抽取器的同位语只并女性称号）：称号以女称谓结尾，或真名本身后接「她」多于「他」。
            # 没有这一条时 “红玛瑙”占卜 / “傲慢”面具 / “红天使”恶灵 都会回来（a1ace4f 实测）。
            if cfg.get("require_female_side", True):
                target = candidates[real]
                if not code.endswith(tuple(self.female_titles)) and target.she_follow <= target.he_follow:
                    continue
            pairs.append((code, real))
            self.merge_guard_log.append((code, real, "quoted_apposition_merge"))
        return pairs

    def _apposition_target_ok(self, item: Candidate, candidates: dict[str, Candidate]) -> bool:
        """同位语的"真名"一侧必须自己像名字：过名字性信号，且模式命中比不低于合并目标门槛（挡 “水手”途径 这类）；
        并且它自己就能进报告（独占提及 / 性别分都过本次门槛）——挡 “红玛瑙”占卜、“傲慢”面具 这类词并词。"""
        # T9-5 整合裁定：真名一侧不再要求过报告频次门槛 / 模式命中比，只要求过名字性信号的候选检查。
        if self.rules.get("name_signal", {}).get("enabled") and self.name_signal(item, candidates)[0]:
            return False
        return True

    def score_gender(self, item: Candidate, sentence: str, chapter_no: int = 1, line_no: int = 1) -> None:
        windows = []
        for match in re.finditer(re.escape(item.name), sentence):
            windows.append(sentence[max(0, match.start() - 18) : min(len(sentence), match.end() + 24)])
        local_text = " ".join(windows) if windows else sentence
        window_terms = contains_any(local_text, self.rules["female_markers"], self.marker_compounds)
        male_terms = contains_any(local_text, self.rules["male_markers"], self.marker_compounds)
        title_hits = [t for t in self.female_titles if item.name.endswith(t)]
        male_title_hits = [t for t in self.male_titles if item.name.endswith(t)]

        delta_f = min(3.0, len(window_terms) * 1.15) + len(title_hits) * 3.0
        delta_m = min(3.0, len(male_terms) * 1.2) + len(male_title_hits) * 3.0
        item.female_score += delta_f
        item.male_score += delta_m
        if (delta_f or delta_m) and sentence not in item.gender_evidence:
            item.gender_evidence.append(sentence)
            item.gender_evidence_chapters.append(chapter_no)
            item.gender_evidence_lines.append(line_no)

    def merge_aliases(self, candidates: dict[str, Candidate], text: str) -> dict[str, Candidate]:
        self._merge_text = text
        # 显式别名语句：甲（乙）、甲又名乙、甲人称乙。
        alias_pairs: list[tuple[str, str]] = []
        alias_re = re.compile(
            rf"([{CJK}]{{2,4}})(?:[（(]([{CJK}]{{1,5}})[）)]|(?:又名|別名|别名|人称|人稱|绰号|綽號|小名为?|小名為?|乳名为?|乳名為?|化名|名字?(?:叫做|叫作|叫|为|為))([{CJK}]{{1,5}}))"
        )
        for m in alias_re.finditer(text):
            alias_pairs.append((self.normalize_name(m.group(1)), self.normalize_name(m.group(2) or m.group(3))))
        titled_alias_re = re.compile(
            rf"([{CJK}]{{1,3}}(?:{'|'.join(map(re.escape, self.female_titles))}))(?:本名|名叫|名为|叫作|叫做)([{CJK}]{{2,4}})"
        )
        alias_pairs.extend((m.group(1), m.group(2)) for m in titled_alias_re.finditer(text))
        renamed_re = re.compile(rf"([{CJK}]{{2,4}})的名字.{{0,45}}?(?:換做|换做|改作|改名為|改名为)[“\"']?([{CJK}]{{2,4}})")
        alias_pairs.extend((self.normalize_name(m.group(1)), self.normalize_name(m.group(2))) for m in renamed_re.finditer(text))

        parent = {name: name for name in candidates}

        def root(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            if a not in parent or b not in parent:
                return
            ra, rb = root(a), root(b)
            if ra == rb:
                return
            # 优先保留不带称谓、更长、出现更多的名称。
            def quality(n: str) -> tuple[int, int, int]:
                has_title = int(any(n.endswith(t) for t in self.female_titles + self.male_titles))
                return (-has_title, len(n), candidates[n].mentions)
            keep, lose = (ra, rb) if quality(ra) >= quality(rb) else (rb, ra)
            parent[lose] = keep

        # 数据驱动的别名映射（T8-3 / D4）：塔罗会代号这类"同一个人的两个名字"之间没有显式句式
        #（实测本书里只有「"正义"奥黛丽」这种引号并置，alias_re 的三条句式都推不出来），
        # 所以让规则文件直接给映射，代码只负责并起来。**旧规则文件没有这个键时行为完全不变**（.get 兜底）。
        # 只在两侧都真的是候选时才并：映射到本书里从不出现的名字（如「嘉德丽雅」）是无操作，不报错。
        # isinstance(alias_map, dict) 是**容器级**守卫：手写规则文件时把整张表写成列表或字符串
        #（"alias_map": ["正义:奥黛丽"]）同样会整批崩栈（AttributeError → 退出码 1），
        # 与"规则文件写错不能崩栈"的意图冲突（复审 r001 F1）。
        alias_map = self.rules.get("alias_map")
        if isinstance(alias_map, dict):
            for code_name, real_name in alias_map.items():
                if isinstance(code_name, str) and isinstance(real_name, str):
                    union(code_name, real_name)

        # T13-3 别名句式的「枢纽词」：「如今化名X」把 如今 同时配给 陈清流/谢狗/灵验/邵坡仙…，并查集一连就全进一条。
        # 一个词在显式别名句里配到的不同候选超过 max_partners 个，说明它是句式里的虚词而不是名字，它的配对全部不用。
        hub_cfg = (self.rules.get("merge_guard") or {}).get("alias_pair_hub") or {}
        hubs: set[str] = set()
        if hub_cfg.get("enabled"):
            partners: dict[str, set[str]] = defaultdict(set)
            for a, b in alias_pairs:
                if a in parent and b in parent and a != b:
                    partners[a].add(b)
                    partners[b].add(a)
            hubs = {w for w, ps in partners.items() if len(ps) > hub_cfg.get("max_partners", 2)}
            for w in sorted(hubs):
                self.merge_guard_log.append((w, "、".join(sorted(partners[w])), "alias_pair_hub"))
        for a, b in alias_pairs:
            if a in hubs or b in hubs:
                continue
            union(a, b)

        # T9-4：引号同位语「“称号”真名」（“神秘女王”贝尔纳黛）。只认原文里反复出现、且对象唯一占优的并置。
        for code_name, real_name in self.quoted_apposition_pairs(candidates, text):
            # 同位语方向已知（称号→真名）：真名做根，不走 quality（否则 通灵者 会因更长而吞掉 戴莉）。
            rc, rr = root(code_name), root(real_name)
            if rc != rr:
                parent[rc] = rr

        # “姓氏+称谓”合并到**有明确赢家**的同姓全名上。
        # 旧规则要求"同姓全名唯一"，于是只要多出一个同姓候选（哪怕是被切坏的噪声片段）整族都不再合并，
        # 长篇小说里主角会分裂成多条（实测 demo：沈青梧/沈姑娘/沈师姐/沈姐姐/沈师姐回 全都没并）。
        # 新规则：同姓全名候选按 (出现次数, 长度) 排序；唯一候选直接合并，
        # 多于一个时只有第一名**严格多于**第二名才合并——两个同姓人物势均力敌时保留歧义，不猜。
        mg_cfg = self.rules.get("merge_guard") or {}
        gen_cfg = mg_cfg.get("title_generation") or {}
        gen_of = {t: g for g, ts in (gen_cfg.get("groups") or {}).items() for t in ts} if gen_cfg.get("enabled") else {}
        gen_seen: dict[str, set[str]] = defaultdict(set)
        alias_order = list(candidates)
        if gen_of:
            alias_order.sort(key=lambda n: -candidates[n].mentions)
        for alias in alias_order:
            matched_title = next((t for t in self.female_titles if alias.endswith(t)), None)
            if not matched_title:
                continue
            surname = alias[: -len(matched_title)]
            all_titles = tuple(self.female_titles + self.male_titles)
            possible = [n for n in candidates if n != alias and n.startswith(surname) and not n.endswith(all_titles)]
            if not possible:
                continue
            # T9-9：单字非姓前缀（夜姑娘）时，先剔掉过不了名字性信号的同首字候选（夜晚 是字面词），再排序。
            mg = self.rules.get("merge_guard") or {}
            if mg.get("initial_prefix_skip_words") and len(surname) == 1 and surname not in self.surnames:
                # 只让「靠首字称谓佐证收回」的名字（夜阑儿）越过排在前面的字面词；其余同首字候选照旧按出现次数排。
                rescued = set(getattr(self, "rescued_names", ()) or ())
                named = [n for n in possible if n in rescued and len(n) >= 3 and n[:2] not in candidates
                         and self.name_signal(candidates[n], candidates, skip_stem=True)[0] is None]
                if named and any(self.name_signal(candidates[n], candidates, skip_stem=True)[0] for n in possible if len(n) == 2):
                    possible = named
            ranked = sorted(possible, key=lambda n: (-candidates[n].mentions, -len(n), n))
            # T8-2 / D3：合并目标必须**自己被反复识别成名字**，否则它只是一个字面高频的词。
            #
            # 反例（实测）：「灰姑娘」→「灰雾」。前缀「灰」下只有「灰雾」一个候选，于是 3 次出现的童话引用
            # 被并进一个完全无关的词；而「灰雾」全书 1711 次 mentions 里只有 2 次是"姓名 + 动词/称谓"
            # 这类模式命中（比值 0.0012），其余都是"文本里恰好包含这两个字"。
            #
            # 阈值 0.005 是对**全书 86 组合并**横扫定的（脚本与全表见 T8-2 的执行报告），不是拍的：
            #   比值 < 0.005 这一档：灰雾 0.0012 / 是一 0.0018 / 天使 0.0048 / 伯爵 0.0043 / 神秘 0.0005…
            #     —— 目标全是"字面高频的词"，挡住它们消掉 30 组噪声合并；
            #   比值 >= 0.005 这一档：玛丽 0.0063（最低的真名）、莎伦 0.0183、信使 0.0156、多丽丝 0.0256、
            #     梅丽莎 0.0639、奥黛丽 0.0546 —— **没有任何一个已知真名被挡住**；
            #   仓库内语料同样成立（实测，可由 tests/test_merge_rules.py::measured_stats 复算）：
            #     examples/sample.txt：目标 林婉儿 (mentions 4, pattern 2) → 比值 0.5，保留；
            #     tests/fixtures/demo_novel.txt：目标 苏婉娘 (3, 1) → 0.333、沈青梧 (5, 4) → 0.8，都保留。
            # 用比值而不是绝对次数，是因为绝对阈值在 159 字的 examples/sample.txt 上会误挡林婉儿
            #（**目标 林婉儿 只有 2 次模式命中**，绝对阈值 >= 3 直接判死）——这条是实测踩出来的，不是推演。
            #
            # **已知的薄余量（复审 r001 F2 / r002 F3）**：仓库内语料的比值是 0.33-1.0，
            # 但真书上离门槛最近的两个真名只有 1.24x 余量（安娜 0.0062、玛丽 0.0063 对 0.005）。
            # 更薄的是结构性问题：mentions 是**字面子串**计数，"X小姐"的每次出现都抬高 X 的分母、
            # 却不给 X 记分子，所以**越是被以称谓称呼的角色，分母越被抬高**。
            # 失败模式是"同一个人分裂成两条"（X 与 X小姐 各成一条），不是角色消失——不会告警。
            # 阈值复核挂在 T8-4（清单 §2 要求先重建候选闸门与评测基线）。
            #
            # 判据只能放在合并侧：reject_reason 看不到候选集合——在那里加"前缀必须是姓氏"实测会砍掉
            # 72/73 组合并，连主角「奥黛丽」一起消失。
            target = candidates[ranked[0]]
            if target.pattern_mentions / max(1, target.mentions) < MIN_PATTERN_RATIO_FOR_MERGE_TARGET:
                continue
            # T9-4 合并守卫（规则键 merge_guard；缺省/enabled=false = 旧行为）：
            guard_reason = self.merge_guard_reason(alias, surname, ranked[0], candidates)
            if guard_reason is not None:
                self.merge_guard_log.append((alias, ranked[0], guard_reason))
                continue
            # T10 姐妹/同前缀多真名（竹碧琼、竹素瑶）：两个以上同前缀候选都像真名时，按别名与各自的章节共现 lift
            # 选归属；最好的不比第二好的高出 min_lift_ratio 倍就不并（拿不准不并）。
            sib = mg_cfg.get("ambiguous_siblings") or {}
            winner = ranked[0]
            if (sib.get("enabled") and self._n_chapters >= sib.get("min_chapters", 20) and len(ranked) > 1
                    and surname not in candidates and len(surname) == 1 and surname not in self.surnames):
                # 只用于「单字非姓前缀」家族（竹）：姓氏家族里同姓男名太多（叶凌霄、宁剑客…），lift 会把称呼打散，实测弃用。
                def realish(n: str) -> bool:
                    c = candidates[n]
                    # 「名字+虚字」切片（叶青雨端、昧月好）不算：任何 ≥2 字的真前缀本身是候选就排除。
                    if any(n[:k] in candidates for k in range(2, len(n))):
                        return False
                    return (len(n) >= sib.get("min_len", 3) and c.pattern_mentions / max(1, c.mentions) >= MIN_PATTERN_RATIO_FOR_MERGE_TARGET
                            and self.name_signal(c, candidates, skip_stem=True)[0] is None)
                real = [n for n in ranked if realish(n)]
                # 只在同家族里有「收回名」（竹碧琼）参与竞争时启用：收回名是新增的歧义来源，其余家族维持旧的出现次数判定。
                rescued_set = set(getattr(self, "rescued_names", ()) or ())
                if len(real) >= 2 and any(n in rescued_set for n in real):
                    ach = candidates[alias].chapters
                    def lift(n: str) -> float:
                        ch = candidates[n].chapters
                        return (len(ach & ch) / max(1, len(ach))) / max(len(ch) / self._n_chapters, 1e-9)
                    scored = sorted(real, key=lambda n: -lift(n))
                    best, second = lift(scored[0]), lift(scored[1])
                    if best <= 0 or best < sib.get("min_lift_ratio", 2.0) * second:
                        self.merge_guard_log.append((alias, scored[0], "ambiguous_siblings"))
                        continue
                    winner = scored[0]
                    if winner != ranked[0] and self.merge_guard_reason(alias, surname, winner, candidates):
                        continue
            # T10 辈分冲突：同一主名下不同时收「长辈」称呼与「晚辈」称呼（宋姨娘 与 宋姑娘、叫我奶奶 与 叫我姐姐）。
            g = gen_of.get(matched_title)
            # T13-2 称呼比本名还常见：长辈称呼（邢夫人 271 次）挂到同姓晚辈（邢岫烟+岫烟 94 次）上，多半是另一个人。
            # 称呼次数 / (本名 + 去姓短名) 超过 max_ratio 就不并。探针：对的最高 0.92（诺玛夫人），错的最低 2.88。
            og = gen_cfg.get("outnumber_guard") or {}
            if g is not None and og.get("enabled") and g in og.get("groups", ["elder"]):
                txt = getattr(self, "_merge_text", "") or ""
                n_alias = txt.count(alias)
                n_name = txt.count(winner)
                if len(winner) - len(surname) >= 2:
                    n_name += txt.count(winner[len(surname):]) - txt.count(winner)
                if n_alias > og.get("max_ratio", 1.5) * max(1, n_name):
                    self.merge_guard_log.append((alias, winner, "title_outnumbers_name"))
                    continue
            if g is not None:
                r = root(winner)
                if gen_seen[r] - {g}:
                    self.merge_guard_log.append((alias, winner, "title_generation_conflict"))
                    continue
            if winner != ranked[0] or len(ranked) == 1 or candidates[ranked[0]].mentions > candidates[ranked[1]].mentions:
                union(alias, winner)
                if g is not None:
                    gen_seen[root(winner)].add(g)

        # T12 丢姓重复（兰芬 ⊂ 米兰芬）：短名整体是「姓 + 短名」这条长名的后缀，且全书候选里没有第二个以短名结尾的名字，
        # 才把短的并进长的；有第二个（宝钗/薛宝钗/…）或长名自己不像名字就不并。
        sfx = mg_cfg.get("surname_drop_suffix") or {}
        if sfx.get("enabled"):
            all_titles = tuple(self.female_titles + self.male_titles)
            names = [n for n in candidates if not n.endswith(all_titles)]
            for short in names:
                if len(short) < sfx.get("min_len", 2):
                    continue
                longs = [n for n in names if n != short and n.endswith(short)]
                if len(longs) != 1:
                    continue
                long = longs[0]
                c = candidates[long]
                if (len(long) == len(short) + 1 and long[0] in self.surnames
                        and c.pattern_mentions / max(1, c.mentions) >= MIN_PATTERN_RATIO_FOR_MERGE_TARGET
                        # 长名自己要过名字性信号：「和叶青雨」「和莎伦」的「和」是连词（absorbed_prefix），不是姓。
                        and self.name_signal(c, candidates, skip_stem=True)[0] is None
                        # 短名也要过：两边都不像名字（宝石→蓝宝石、笑话→人笑话）就是词并词。
                        and self.name_signal(candidates[short], candidates, skip_stem=True)[0] is None
                        # 长名自己至少 min_pattern_hits 次被识别成名字、且后接「她」不少于「他」：挡 蓝宝石(1/34)、人笑话(1/19, 他>她)。
                        #（古典小说「她」少，故不要求 she_follow ≥ 1。）
                        and c.pattern_mentions >= sfx.get("min_pattern_hits", 2) and c.she_follow >= c.he_follow):
                    self.merge_guard_log.append((short, long, "surname_drop_suffix_merged"))
                    union(short, long)

        merged: dict[str, Candidate] = {}
        for name, item in candidates.items():
            key = root(name)
            target = merged.setdefault(key, Candidate(name=key))
            target.mentions += item.mentions
            target.exclusive_mentions += item.exclusive_mentions
            target.pattern_mentions += item.pattern_mentions
            if name == key:
                target.left_chars = item.left_chars
                target.right_chars = item.right_chars
                target.she_follow, target.he_follow = item.she_follow, item.he_follow
            target.chapters |= item.chapters
            target.female_score += item.female_score
            target.male_score += item.male_score
            target.source_score += item.source_score
            lines_seq = item.gender_evidence_lines or [1] * len(item.gender_evidence)
            for sentence, chapter_no, line_no in zip(item.gender_evidence, item.gender_evidence_chapters, lines_seq):
                if sentence not in target.gender_evidence:
                    target.gender_evidence.append(sentence)
                    target.gender_evidence_chapters.append(chapter_no)
                    target.gender_evidence_lines.append(line_no)
            if name != key:
                target.aliases.add(name)
            target.aliases |= item.aliases
        return merged

    def find_trait_hits(self, clause: str, category: str, words: Iterable[str]) -> list[str]:
        """一个分句里命中这一类特征的词。

        词表命中记词表里的那个词；组合规则命中记**整个短语**（例如「素白衣」）——颜色 × 衣物枚举不完，
        而人要看的是"她穿了什么"。同一分句里的重复命中按首次出现去重，计数与旧行为一致。
        """
        hits = list(contains_any(clause, words))
        for pattern in self.trait_combo_patterns.get(category, ()):
            hits.extend(match.group(0) for match in pattern.finditer(clause))
        return list(dict.fromkeys(hits))

    def extract_traits(self, candidates: dict[str, Candidate], chapters: list[tuple[int, str]] | list[tuple[int, str, int]]) -> None:
        # T8-1：这里同样是「每个分句对每个候选重建 labels 再逐个包含检查」，是第二大开销。
        # 建一份 label → 候选 的索引。**前提：label 全局唯一**——即没有任何 label 同时属于两个候选。
        # 该前提在本管线里成立：aliases 只在 merge_aliases 里被写入，而任一候选的 name == root(name)，
        # 于是"A 的别名 == B 的名字"会推出两者本属同一合并项（详见 test_index.py 与复审 r001 §3.3）。
        # 若将来在 merge_aliases 之外给 Candidate.aliases 赋值，这里会静默丢掉一个候选，必须重审。
        # explicit 的顺序与旧实现不同（索引按首字分组的顺序返回），归属不受影响见 names_present 的说明。
        label_owner: dict[str, Candidate] = {}
        for item in candidates.values():
            # sorted(item.aliases)：aliases 是 set，直接展开的顺序受 PYTHONHASHSEED 影响，
            # 会让 explicit 的顺序跨进程不可复现（结果虽不受影响，但"时好时坏"比"稳定"难查）。
            # 排序消掉这层不确定性，代价是每次调用一次 ~O(别名数 log) 的排序。
            for label in (item.name, *sorted(item.aliases)):
                if label:
                    label_owner.setdefault(label, item)
        label_index = index_by_first_char(label_owner)
        for ch_entry in chapters:
            if len(ch_entry) == 3:
                chapter_no, chapter_text, base_line = ch_entry
            else:
                chapter_no, chapter_text = ch_entry
                base_line = 1
            last_owner: Candidate | None = None
            for sentence, line_no in split_sentences_with_lines(chapter_text, base_line):
                # 原声对白槽位：引号外归属唯一说话人时，收录整句供 W2 第四节「说话指纹与原声标本」使用。
                if DIALOGUE_QUOTE_RE.search(sentence):
                    outside = DIALOGUE_QUOTE_RE.sub("", sentence)
                    seen_dlg: set[int] = set()
                    dlg_owners: list[Candidate] = []
                    for label in names_present(label_index, outside):
                        cand = label_owner[label]
                        if id(cand) not in seen_dlg:
                            seen_dlg.add(id(cand))
                            dlg_owners.append(cand)
                    speaker: Candidate | None = None
                    if len(dlg_owners) == 1:
                        speaker = dlg_owners[0]
                    elif not dlg_owners and "她" in outside and last_owner is not None:
                        speaker = last_owner
                    if speaker is not None and sentence not in speaker.trait_evidence["原声对白"]:
                        speaker.trait_evidence["原声对白"].append(sentence)
                        speaker.trait_evidence_chapters["原声对白"].append(chapter_no)
                        speaker.trait_evidence_lines["原声对白"].append(line_no)

                clauses = [c.strip() for c in re.split(r"[，,。！？!?；;：:]", sentence) if c.strip()]
                sentence_owner: Candidate | None = None
                for clause in clauses:
                    explicit = []
                    # label_index 保持 candidates 的迭代顺序（每个候选 name 在前、别名在后），
                    # id() 去重则对应旧实现的"同一候选只记一次"：Candidate 是可变 dataclass，
                    # 用身份而不是相等性/可哈希性去重，语义与旧实现一致且不受字段可变性影响。
                    seen_owners: set[int] = set()
                    for label in names_present(label_index, clause):
                        item = label_owner[label]
                        if id(item) not in seen_owners:
                            seen_owners.add(id(item))
                            explicit.append(item)

                    # “她……”优先承接上一分句的角色，避免把关系宾语误当成被描述者。
                    starts_with_pronoun = bool(re.match(r"^[‘’“”\"'（(\s]*她(?:是|有|的|很|性格|身穿|穿着|擅长|精通|看起来|显得)?", clause))
                    inherits_sentence_owner = bool(
                        sentence_owner is not None
                        and (not explicit or re.match(r"^(?:是|为|乃|作为)", clause))
                    )
                    if starts_with_pronoun and last_owner is not None:
                        owners = [last_owner]
                    elif inherits_sentence_owner:
                        owners = [sentence_owner]
                    else:
                        owners = explicit
                    if explicit and not starts_with_pronoun and not inherits_sentence_owner:
                        last_owner = explicit[0] if len(explicit) == 1 else None
                    if owners and sentence_owner is None:
                        sentence_owner = owners[0] if len(owners) == 1 else None
                    if starts_with_pronoun and last_owner is not None:
                        sentence_owner = last_owner
                    if not owners:
                        continue

                    for item in owners:
                        for category, words in self.rules["trait_lexicons"].items():
                            for hit in self.find_trait_hits(clause, category, words):
                                if re.search(rf"(?:不|并不|并非|不是|从不|未曾).{{0,3}}{re.escape(hit)}", clause):
                                    continue
                                item.traits[category][hit] += 1
                                if clause not in item.trait_evidence[category]:
                                    item.trait_evidence[category].append(clause)
                                    item.trait_evidence_chapters[category].append(chapter_no)
                                    item.trait_evidence_lines[category].append(line_no)

    def run_pipeline(
        self,
        text: str,
        min_mentions: int,
        min_score: float,
        diagnostics: dict | None = None,
        stop_after_candidates: bool = False,
        include_names: Iterable[str] = (),
        full_mentions_cap: int = 0,
    ) -> tuple[dict[str, Candidate], list[dict] | None]:
        """抽取管线。返回 (候选集, 结果列表)；stop_after_candidates=True 时只跑候选发现，结果列表为 None。

        把管线从 extract 里提出来，是为了让 --diagnostics 能在**不复制**任何判定逻辑的前提下，
        对同一条管线按阶段取数（复制一份"只跑到候选发现"的实现迟早会和主路径漂移）。
        不传 diagnostics 时只多两次 dict 判空，行为与原实现逐行相同。

        include_names（--protagonist / --include-name）是**用户点名**的角色（典型是男性主角）：
        它只做一件事——让命中的候选绕过 min_mentions/min_score 两道门槛进入报告，并打上
        requested 标记；**不参与任何性别打分**。默认空元组时与原实现逐行等价（零漂移）。
        点名而没命中任何候选（含别名）时记进 self.unmatched_includes，由调用方提示。
        """
        timings = None if diagnostics is None else diagnostics["timings"]
        mark = None if timings is None else time.perf_counter()

        def lap(stage: str) -> None:
            nonlocal mark
            if timings is None or mark is None:
                return
            now = time.perf_counter()
            timings[stage] = round(now - mark, 3)
            mark = now

        chapters_with_lines = chapter_map_with_lines(text, self.rules)
        chapters = [(ch, body) for ch, body, _ in chapters_with_lines]
        if diagnostics is not None:
            diagnostics["chapters"] = len(chapters)
        candidates = self.find_candidates(chapters, diagnostics)
        # 用户显式点名（--protagonist / --include-name）的角色，只要正文里确实出现过，
        # 即使被中文姓氏规则挡掉（如音译配角「辛西娅」），也强制注入候选池参与后续提及、别名合并与特征抽取。
        for label in include_names:
            if label and label not in candidates and label in text:
                candidates[label] = Candidate(name=label)
        if diagnostics is not None:
            # candidates = 合并**前**的候选（4,559 那一级的量）；candidates_after_merge = 交给门槛判决的那一级。
            diagnostics["candidates"] = len(candidates)
        lap("find_candidates")
        if stop_after_candidates:
            return candidates, None
        self.expand_mentions(candidates, chapters_with_lines)
        lap("expand_mentions")
        self.merge_guard_log = []
        self._n_chapters = len(chapters)
        candidates = self.merge_aliases(candidates, text)
        if diagnostics is not None:
            diagnostics["merge_guard"] = [list(x) for x in self.merge_guard_log]
        if diagnostics is not None:
            diagnostics["candidates_after_merge"] = len(candidates)
        lap("merge_aliases")
        # 明确女性称谓是强证据；旧文本常以“他”通指男女，不应反向覆盖称谓。
        for item in candidates.values():
            labels = [item.name, *item.aliases]
            has_female_title = any(any(label.endswith(t) for t in self.female_titles) for label in labels)
            has_male_title = any(any(label.endswith(t) for t in self.male_titles) for label in labels)
            if has_female_title and not has_male_title:
                item.male_score = 0.0
        # 女性化用字只能提供一次弱证据，不能随出现次数无限累加。
        for item in candidates.values():
            feminine_chars = max(
                (sum(ch in self.rules["feminine_name_chars"] for ch in label) for label in [item.name, *item.aliases]),
                default=0,
            )
            if feminine_chars:
                item.female_score += min(4.0, feminine_chars * 2.0)
        self.extract_traits(candidates, chapters_with_lines)
        lap("extract_traits")

        # 点名纳入（--protagonist/--include-name）在**合并之后**解析：合并会把"姓氏+称谓"并进全名、
        # 也会按 alias_map 把代号并进真名，所以点名的那个名字可能已经成了别人的别名——那也算命中，
        # 报告里出的是合并后的主名（点名的人至少在 aliases 里看得见）。
        forced: dict[int, str] = {}
        self.unmatched_includes = []
        for label in include_names:
            owner = next(
                (item for item in candidates.values() if label == item.name or label in item.aliases),
                None,
            )
            if owner is None:
                self.unmatched_includes.append(label)
            else:
                forced.setdefault(id(owner), label)  # 用 id() 而不是 name：Candidate 是可变对象，且已按身份去重

        results = []
        for item in candidates.values():
            requested_label = forced.get(id(item))
            passes_gate = item.exclusive_mentions >= min_mentions and item.net_score >= min_score
            if passes_gate and requested_label is None:
                signal_reason, _ = self.name_signal(item, candidates)
                if signal_reason is not None:
                    if diagnostics is not None:
                        diagnostics.setdefault("name_signal_rejections", {}).setdefault(signal_reason, []).append(item.name)
                    passes_gate = False
            if not passes_gate and requested_label is None:
                continue
            confidence = max(0.01, min(0.99, 0.50 + item.net_score / (12 + abs(item.net_score))))
            entry = {
                "name": item.name,
                "aliases": sorted(item.aliases),
                "gender": "female",
                "gender_confidence": round(confidence, 3),
                "score": round(item.net_score, 2),
                "candidate_score": round(item.source_score, 2),
                "mentions": item.exclusive_mentions,
                "chapters": sorted(item.chapters),
                "traits": {k: [w for w, _ in v.most_common()] for k, v in item.traits.items() if v},
                "evidence": {},
                # T9-1：键同 evidence，值与 evidence 对应键逐条对齐、长度相等（0=首个标题前；无标题一律 1）。
                "evidence_chapters": {},
                # 1-based 原文行号，与 evidence / evidence_chapters 逐条对齐。
                "evidence_lines": {},
            }
            names = [item.name, *sorted(item.aliases)]
            gender_ev, gender_ch, gender_ln = select_category_evidence_with_lines(
                self.rules, item.gender_evidence, item.gender_evidence_chapters,
                item.gender_evidence_lines,
                category="gender", names=names,
            )
            entry["evidence"]["gender"] = gender_ev
            entry["evidence_chapters"]["gender"] = gender_ch
            entry["evidence_lines"]["gender"] = gender_ln
            for k, v in item.trait_evidence.items():
                if not v:
                    continue
                ev, ch, ln = select_category_evidence_with_lines(
                    self.rules, v, item.trait_evidence_chapters[k],
                    item.trait_evidence_lines[k],
                    category=k, names=names,
                )
                entry["evidence"][k] = ev
                entry["evidence_chapters"][k] = ch
                entry["evidence_lines"][k] = ln
            if full_mentions_cap > 0 and (requested_label is not None or not include_names):
                fm_ev, fm_ch, fm_ln = collect_full_mention_lines(
                    chapters_with_lines, names, full_mentions_cap,
                    strategy=self.rules.get("sample_strategy") or "earliest_mid_latest",
                )
                if fm_ev:
                    entry["evidence"]["全文提及"] = fm_ev
                    entry["evidence_chapters"]["全文提及"] = fm_ch
                    entry["evidence_lines"]["全文提及"] = fm_ln
            if requested_label is not None:
                # 点名纳入的条目一律带 requested 标记；**点名到本条主名**时 gender 改写为 protagonist。
                # 为什么连"本来就通过女性门槛"的主名也要改：分数是**绝对值累加**，主角这种几十万字的角色
                # 光是"她/姑娘/妹妹"出现在邻近窗口里就能把 net_score 堆到几千（实测姜望 45508 次 mentions →
                # net 2160，比全书任何真女性角色都高）。点名本身就是"用户比分类器更清楚这是谁"，
                # 这时候继续写 female 是编造，不是保守。
                # 点名到**别名**（如 林小姐 → 林婉儿）时保留原分类，只加 requested：用户点的是称谓，
                # 没有对"林婉儿是谁"下判断。
                entry["requested"] = True
                if requested_label == item.name:
                    entry["gender"] = "protagonist"
            results.append(entry)
        return candidates, sorted(results, key=lambda x: (-x["mentions"], -x["score"], x["name"]))

    def extract(
        self,
        text: str,
        min_mentions: int,
        min_score: float,
        include_names: Iterable[str] = (),
        full_mentions_cap: int = 0,
    ) -> list[dict]:
        """默认路径：不带归因跑完整管线。--diagnostics 关闭时走的就是这一条。"""
        _, results = self.run_pipeline(
            text, min_mentions, min_score,
            include_names=include_names,
            full_mentions_cap=full_mentions_cap,
        )
        return results or []

    def diagnose(
        self,
        text: str,
        min_mentions: int,
        min_score: float,
        stage: str = "all",
        input_bytes: int = 0,
        include_names: Iterable[str] = (),
    ) -> tuple[dict, list[dict] | None]:
        """跑管线并把归因汇总成可序列化的 dict（只由 --diagnostics 调用）。

        返回 (归因, 结果列表)；stage="candidates" 时结果列表为 None。
        stage="candidates" 只跑到候选发现：真书几秒内就能复算出每模式的原始命中/存活命中，
        这使得"规则改动的红/绿对照"不必等一次 25 分钟的端到端。
        """
        diagnostics = new_diagnostics()
        diagnostics["stage"] = stage
        diagnostics["input_bytes"] = input_bytes
        diagnostics["input_chars"] = len(text)
        diagnostics["min_mentions"] = min_mentions
        diagnostics["min_score"] = min_score
        started = time.perf_counter()
        _, results = self.run_pipeline(
            text, min_mentions, min_score, diagnostics=diagnostics, stop_after_candidates=(stage == "candidates"),
            include_names=include_names,
        )
        diagnostics["timings"]["total"] = round(time.perf_counter() - started, 3)
        diagnostics["rejection_reasons"] = dict(diagnostics["rejection_reasons"])
        if results is not None:
            diagnostics["reported"] = len(results)
        return diagnostics, results


def write_diagnostics(path: Path, source: Path, encoding: str | None, diagnostics: dict) -> None:
    """写归因 JSON。与产物分开：诊断是**观测**，不是抽取结果，也不该被产物扫描当成结果读走。"""
    payload = {
        "source": Path(source).as_posix(),
        "encoding": encoding or "unspecified",
        **diagnostics,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def rules_sha256(path: Path) -> str:
    """character_rules.json 的 64 位十六进制 sha256（按文件字节算，与 sha256sum 一致）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(
    path: Path,
    source: Path,
    results: list[dict],
    encoding: str | None = None,
    tool_version: str | None = None,
    rules_digest: str | None = None,
) -> None:
    """写 JSON 产物。

    encoding 是**实际读取该文件用的编码**；调用方没提供时写 "unspecified" 而不是 null——
    null 在机器可读产物里既不是 codec 名、也读不出"是没提供还是读不出来"，"unspecified" 是自解释的占位。
    """
    payload = {
        "source": Path(source).as_posix(),
        "encoding": encoding or "unspecified",
        "character_count": len(results),
    }
    # T9-1 可选元数据：调用方给了才写（CLI 总是给）；放在 characters 之前，便于人读。
    if tool_version is not None:
        payload["tool_version"] = tool_version
    if rules_digest is not None:
        payload["rules_sha256"] = rules_digest
    payload["characters"] = results
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def write_csv(path: Path, results: list[dict], encoding: str | None = None) -> None:
    """写 CSV（UTF-8 带 BOM，便于 Excel）。

    encoding 列重复出现在每一行：CSV 没有"文件级元数据"的位置，而按行重复能让任何只读一行的
    程序也知道这份产物是按哪种编码读出来的（取值语义同 write_json）。
    """
    categories = sorted({k for r in results for k in r["traits"]})
    fields = ["name", "aliases", "encoding", "gender_confidence", "score", "mentions", "chapters", *categories]
    # requested 列只在**确实点名纳入过**时出现：默认路径（无人点名）的 CSV 字节不允许漂移。
    # 列名取 requested，取值只区分"是/空"，与 JSON 的 requested: true 一一对应。
    has_requested = any(r.get("requested") for r in results)
    if has_requested:
        fields.insert(1, "requested")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in results:
            row = {
                "name": r["name"], "aliases": "、".join(r["aliases"]),
                "encoding": encoding or "unspecified",
                "gender_confidence": r["gender_confidence"], "score": r["score"],
                "mentions": r["mentions"], "chapters": "、".join(map(str, r["chapters"])),
            }
            row.update({k: "、".join(r["traits"].get(k, [])) for k in categories})
            if has_requested:
                row["requested"] = "是" if r.get("requested") else ""
            writer.writerow(row)


def write_markdown(path: Path, source: Path, results: list[dict], encoding: str | None = None) -> None:
    # 点名纳入的条目（--protagonist）不是女性候选，标题与汇总行都要改口径；
    # 没有这类条目时下面两行与旧实现**逐字相同**（默认路径产物零漂移）。
    protagonists = [r for r in results if r.get("gender") == "protagonist"]
    if protagonists:
        title = f"# 角色提取结果（含命令行点名纳入）"
        summary = f"共 {len(results)} 条记录，其中 {len(protagonists)} 条为命令行点名纳入（本工具未对其做性别判定）。"
    else:
        title = f"# 女性角色提取结果"
        summary = f"共识别 {len(results)} 名候选女性角色。"
    lines = [
        title, "",
        f"来源：`{source.name}`（编码：{encoding or 'unspecified'}）", "",
        summary, "",
    ]
    for r in results:
        entry_lines = [
            f"## {r['name']}", "",
            f"- 别名：{'、'.join(r['aliases']) or '无'}",
        ]
        if r.get("gender") == "protagonist":
            entry_lines.append("- 纳入方式：命令行点名（本工具未对其做性别判定）")
        entry_lines.extend([
            f"- 女性置信度：{r['gender_confidence']:.1%}",
            f"- 出现次数：{r['mentions']}",
            f"- 出现章节：{'、'.join(map(str, r['chapters']))}", "",
        ])
        lines.extend(entry_lines)
        for category, words in r["traits"].items():
            lines.extend([f"### {category}", "", "、".join(words), ""])
        if r["evidence"]:
            lines.extend(["### 原文证据", ""])
            for category, sentences in r["evidence"].items():
                for sentence in sentences:
                    lines.append(f"- **{category}**：{sentence}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def iter_inputs(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    pattern = "**/*.txt" if recursive else "*.txt"
    return sorted(p for p in path.glob(pattern) if p.is_file())


def output_stem(source: Path, used: set[str]) -> str:
    """输出文件前缀。

    --recursive 扫描时不同子目录下常有同名文件（各卷的 ch1.txt），旧实现直接用
    source.stem，后写的会静默覆盖先写的。冲突时追加来源路径的短哈希，保证一一对应。
    """
    base = f"{source.stem}_female_characters"
    stem = base
    if stem in used:
        # 用解析后的绝对路径做哈希输入：同一个文件无论用相对路径还是绝对路径扫描，产物名都一致。
        digest = hashlib.sha1(source.resolve().as_posix().encode("utf-8")).hexdigest()[:8]
        stem = f"{base}_{digest}"
        index = 1
        while stem in used:
            index += 1
            stem = f"{base}_{digest}_{index}"
    used.add(stem)
    return stem


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="离线提取中文文本中的女性角色及其特征")
    parser.add_argument("input", type=Path, help="一个 TXT 文件或包含 TXT 的目录")
    parser.add_argument("-o", "--output", type=Path, default=Path("character_output"), help="输出目录")
    parser.add_argument("--rules", type=Path, default=Path(__file__).with_name("character_rules.json"), help="规则 JSON")
    parser.add_argument(
        "--book-profile",
        type=Path,
        default=None,
        help="按书配置 JSON，可覆盖 evidence.sample_strategy 与 evidence.max_evidence_per_category；"
             "不提供则沿用规则文件的各类最早 N 条截断（不改旧口径）。本轮不实现词表或自动 N",
    )
    parser.add_argument("--format", choices=("json", "csv", "md", "all"), default="all")
    parser.add_argument(
        "--encoding",
        choices=ENCODING_CHOICES,
        default="auto",
        help="输入文本编码；auto 为按 BOM 与常见中文编码依次尝试（默认）",
    )
    parser.add_argument("--min-mentions", type=int, default=2, help="最低出现次数")
    parser.add_argument("--min-score", type=float, default=3.0, help="最低女性判定分数")
    parser.add_argument(
        "--full-mentions-cap",
        type=int,
        default=0,
        help="为点名纳入（或无点名时的全部）角色追加「全文提及」完整原文行槽位，最多保留 N 行（0 表示关闭，推荐中配设 150）",
    )
    # 主角这类**明知性别、又必然被女性门槛拒掉**的角色：让用户点名纳入，而不是放宽全局门槛
    # （放宽门槛会把整本书的噪声一起放进来）。--include-name 是它的同义词，供非小说场景使用。
    parser.add_argument(
        "--protagonist",
        "--include-name",
        action="append",
        default=[],
        metavar="名字",
        help="点名纳入报告的角色名（可重复，或用逗号分隔；典型用法是主角）。绕过 --min-mentions/--min-score，"
             "点名到主名时该条 gender 记为 protagonist 并带 requested 标记（点名到别名则保留原分类）；"
             "点名而没命中候选时在 stderr 提示，退出码不变",
    )
    parser.add_argument("--recursive", action="store_true", help="递归扫描输入目录")
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="批处理时跳过读取失败的文件（编码解不开 / 无法读取）继续处理其余文件；最后仍以退出码 2 结束（默认遇错立即中止）",
    )
    parser.add_argument(
        "--diagnostics",
        type=Path,
        default=None,
        help="把候选归因（每模式原始命中/存活命中、拒绝原因直方图、各阶段耗时）写成 JSON 到该路径；默认关闭，不影响 stdout 与产物",
    )
    parser.add_argument(
        "--diagnostics-stage",
        choices=("all", "candidates"),
        default="all",
        help="--diagnostics 的深度：all=跑完整管线（含 mentions 与报告条数），candidates=只跑到候选发现（真书秒级，用于规则改动的红/绿对照）",
    )
    args = parser.parse_args()

    # --protagonist 既可重复给，也可以一次给一串（中英文逗号都认）。去重保序，避免同一名字算两次。
    include_names: list[str] = []
    for raw in args.protagonist:
        for name in re.split(r"[,，]", raw):
            name = name.strip()
            if name and name not in include_names:
                include_names.append(name)

    if not args.input.exists():
        parser.error(f"输入不存在：{args.input}")
    if not args.rules.exists():
        parser.error(f"规则文件不存在：{args.rules}")

    rules = load_rules(args.rules)
    rules_digest = rules_sha256(args.rules)
    snapshot = None
    if args.book_profile is not None:
        if not args.book_profile.exists():
            parser.error(f"book profile 不存在：{args.book_profile}")
        try:
            rules, snapshot, _profile_raw = resolve_profile(args.book_profile, rules, rules_digest)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"错误：book profile 无效：{exc}", file=sys.stderr)
            return 2
    else:
        rules, snapshot, _profile_raw = resolve_profile(None, rules, rules_digest)
    files = iter_inputs(args.input, args.recursive)
    if not files:
        parser.error("没有找到 TXT 文件")
    args.output.mkdir(parents=True, exist_ok=True)
    if snapshot is not None:
        (args.output / "run-meta.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    extractor = Extractor(rules)

    total = 0
    processed = 0
    # 只存路径：失败原因已经在 [跳过] 那一行原样打出来了，这里再存一份也没有读取点。
    failures: list[Path] = []
    used_stems: set[str] = set()
    for source in files:
        try:
            text, used_encoding = load_text(source, encoding=args.encoding)
        except (TextDecodeError, OSError) as exc:
            # OSError 也要接住：扫描到读取之间文件被删、被其它进程占用（Windows 上的 PermissionError）、
            # 目录项无读权限——不接住就会整批崩栈、退出码变成 1，与 --keep-going 的字面承诺（跳过失败文件
            # 继续处理其余文件）和约定的退出码 2 都不符。
            if not args.keep_going:
                # 默认行为不变：立刻中止，并把失败原因原样打出来。
                print(f"错误：{exc}", file=sys.stderr)
                return 2
            # --keep-going：跳过这一个文件继续，但要留下痕迹，最后仍然以退出码 2 结束。
            print(f"[跳过] {exc}", file=sys.stderr)
            failures.append(source)
            continue
        diagnosed: list[dict] | None = None
        if args.diagnostics is None:
            results = extractor.extract(
                text, args.min_mentions, args.min_score,
                include_names=include_names,
                full_mentions_cap=args.full_mentions_cap,
            )
        else:
            # 诊断模式：同一条管线跑一次，归因写进**独立文件**，stdout 与三个产物一字不改。
            diagnostics, diagnosed = extractor.diagnose(
                text, args.min_mentions, args.min_score, stage=args.diagnostics_stage,
                input_bytes=source.stat().st_size, include_names=include_names,
            )
            # 父目录不存在时自己建：同一次运行里 --json（冒烟脚本）会建，这里不建就会以未捕获的
            # FileNotFoundError（退出码 1）结束，用户按 README 换个路径就会踩到（复审 F5）。
            args.diagnostics.parent.mkdir(parents=True, exist_ok=True)
            write_diagnostics(args.diagnostics, source, used_encoding, diagnostics)
            results = diagnosed or []
        # 点名的角色没进报告必须说出来：用户按名字问"这个人在哪"，静默漏掉比报错更难查。
        # 只提示、不改退出码——批处理里一个名字没命中不该让整批判失败。
        if extractor.unmatched_includes:
            missing = "、".join(extractor.unmatched_includes)
            print(f"[提示] {source}：--protagonist 点名的名字没有候选与之匹配（未纳入）：{missing}", file=sys.stderr)
        total += len(results)
        processed += 1
        if args.diagnostics is not None and diagnosed is None:
            print(f"[完成] {source}（{used_encoding}）: 仅归因（--diagnostics-stage candidates，未产出角色文件）")
            continue  # candidates 阶段没跑完管线，自然没有产物可写
        stem = output_stem(source, used_stems)
        if args.format in ("json", "all"):
            write_json(args.output / f"{stem}.json", source, results, used_encoding,
                       tool_version=TOOL_VERSION, rules_digest=rules_digest)
        if args.format in ("csv", "all"):
            write_csv(args.output / f"{stem}.csv", results, used_encoding)
        if args.format in ("md", "all"):
            write_markdown(args.output / f"{stem}.md", source, results, used_encoding)
        print(f"[完成] {source}（{used_encoding}）: {len(results)} 名候选女性角色")
    print(f"共处理 {len(files)} 个文件，成功 {processed} 个，输出 {total} 条角色记录 -> {args.output.resolve()}")
    if failures:
        names = "、".join(str(path) for path in failures)
        print(f"失败 {len(failures)} 个文件（{names}）：本批结果不完整，请修正后重跑", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        raise SystemExit(130)
