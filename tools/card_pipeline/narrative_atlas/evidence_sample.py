"""证据句抽样：earliest、earliest_plus_latest、earliest_mid_latest。

位置窗：earliest_mid_latest 仍按过滤后候选的章节跨度三等分，N 只约束这一段，不足不凑数。
阶段节点：仅 earliest_mid_latest 在位置抽样之后追加（不删已选句），实际条数可以大于 N。
未在此实现均匀抽样（spread）、自动 N，也不再使用「最多 2 个优先名额」的替换限额。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional, Sequence, Tuple

try:
    from .evidence_filter import keep_evidence
except ImportError:
    from evidence_filter import keep_evidence

STRATEGIES = ("earliest", "earliest_plus_latest", "earliest_mid_latest")
UNPROFILED_STRATEGY = "earliest"
PROFILE_DEFAULT_STRATEGY = "earliest_mid_latest"

# 阶段节点通用线索与轻量专名，写在抽样模块，不进全局 character_rules.json。
ABILITY_TITLE_MARKERS = (
    "心理医生", "催眠师", "梦境行者", "操纵师", "织梦人", "读心者",
)
ABILITY_GENERIC_CUES = ("魔药", "晋升", "序列")
DRINK_POTION = re.compile(r"喝[下了]?.{0,20}魔药")
PROMO_BOUND = re.compile(r"尚未正式晋升|正式晋升前")
QUOTED = re.compile("[\u201c\u300c\"\u300e]([^\u201d\u300d\"\u300f]{2,12})[\u201d\u300d\"\u300f]")
IDENTITY_MARKERS = (("理事", "职务:理事"), ("委员", "职务:委员"), ("成年", "身份:成年"))
NODE_CATEGORIES = ("能力", "身份", "关系")
# 关系贯穿对象：至少 3 个不同章节共现。
RELATION_MIN_CHAPTERS = 3
RELATION_STOP = frozenset(
    "朋友们 朋友 人们 他们 她们 自己 别人 大家 小姐 女士 先生 侍女 "
    "哥哥 妹妹 弟弟 姐姐 父母 母亲 父亲 妈妈 爸爸 孩子 贵族 同好 "
    "仪式 聚会 情况 时候 一些 这些 那些 什么 怎么 可以 已经 还是 "
    "不是 只是 还没 旁边 臂弯 脑袋 下意识 同情".split()
)
BARE_NAME = re.compile(r"(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,3})(?![\u4e00-\u9fff])")
DOT_NAME = re.compile(r"[\u4e00-\u9fff]{1,4}·[\u4e00-\u9fff]{1,4}")

Pair = Tuple[Optional[int], str]


def _strategy_error() -> str:
    return "sample_strategy 必须是 " + "、".join(STRATEGIES)


def mid_quota(cap: int) -> tuple[int, int, int]:
    """返回 (n_early, n_mid, n_late)。N=6 → 2+2+2；N=7 → 3+2+2。"""
    n_early = (cap + 2) // 3
    n_late = cap // 3
    n_mid = cap - n_early - n_late
    return n_early, n_mid, n_late


def _trisect_bounds(pairs: Sequence[Pair]) -> str:
    """按章节跨度三等分；缺章节号或跨度为 0 时改用阅读顺序下标。"""
    chapters = [ch for ch, _ in pairs]
    if chapters and all(ch is not None for ch in chapters) and min(chapters) != max(chapters):
        return "chapter"
    return "index"


def _bucket(pairs: Sequence[Pair], mode: str, idx: int) -> int:
    n = len(pairs)
    if mode == "index":
        if idx < n / 3:
            return 0
        if idx < 2 * n / 3:
            return 1
        return 2
    lo = min(ch for ch, _ in pairs)
    hi = max(ch for ch, _ in pairs)
    ch = pairs[idx][0]
    span = hi - lo
    if ch < lo + span / 3:
        return 0
    if ch < lo + 2 * span / 3:
        return 1
    return 2


def _unique_append(selected, item, seen_text, seen_pair):
    _ch, text = item
    if item in seen_pair or text in seen_text:
        return False
    selected.append(item)
    seen_pair.add(item)
    seen_text.add(text)
    return True


def sample_earliest_mid_latest(pairs: Sequence[Pair], cap: int) -> list[Pair]:
    ordered = list(pairs)
    if len(ordered) <= cap:
        selected: list[Pair] = []
        seen_text: set[str] = set()
        seen_pair: set[Pair] = set()
        for item in ordered:
            _unique_append(selected, item, seen_text, seen_pair)
        return selected
    n_early, n_mid, n_late = mid_quota(cap)
    mode = _trisect_bounds(ordered)
    buckets = {i: _bucket(ordered, mode, i) for i in range(len(ordered))}
    groups = {0: [], 1: [], 2: []}
    for i, item in enumerate(ordered):
        groups[buckets[i]].append(item)
    picked: list[Pair] = []
    seen_text: set[str] = set()
    seen_pair: set[Pair] = set()
    for item in groups[0][:n_early]:
        _unique_append(picked, item, seen_text, seen_pair)
    for item in groups[1][:n_mid]:
        _unique_append(picked, item, seen_text, seen_pair)
    late = groups[2]
    if n_late and late:
        if all(ch is not None for ch, _ in late):
            # 「最晚」按章节，不按列表末尾（候选若未按章排也不会拿错）。
            late_pick = sorted(late, key=lambda it: it[0])[-n_late:]
        else:
            late_pick = late[-n_late:]
        for item in late_pick:
            _unique_append(picked, item, seen_text, seen_pair)
    return picked


def ability_node_key(text: str) -> Optional[str]:
    """同一晋升／同一称号归为一类，避免「读心者配方」重复堆条。"""
    if PROMO_BOUND.search(text):
        for title in ABILITY_TITLE_MARKERS:
            if title in text:
                return "bound:" + title
        return "bound:未晋升"
    for title in ABILITY_TITLE_MARKERS:
        if title in text:
            return "title:" + title
    m = re.search(
        r"[\u201c\u300c]([^\u201d\u300d]{2,12})[\u201d\u300d].{0,6}魔药|"
        r"魔药.{0,8}[\u201c\u300c]([^\u201d\u300d]{2,12})[\u201d\u300d]",
        text,
    )
    if m:
        return "title:" + (m.group(1) or m.group(2))
    if any(cue in text for cue in ABILITY_GENERIC_CUES) or DRINK_POTION.search(text):
        return "generic:途径"
    return None


def _ability_rep_score(text: str) -> int:
    score = 0
    if PROMO_BOUND.search(text):
        score += 5
    if DRINK_POTION.search(text):
        score += 4
    if "晋升" in text:
        score += 3
    if "魔药" in text:
        score += 2
    if "序列" in text:
        score += 1
    return score


def _pick_representative(items: Sequence[Pair]) -> Pair:
    return max(items, key=lambda it: (_ability_rep_score(it[1]), -items.index(it)))


def identity_node_key(text: str) -> Optional[str]:
    for word, key in IDENTITY_MARKERS:
        if word in text:
            return key
    return None


def _self_name_set(names: Sequence[str]) -> set[str]:
    out = set()
    for name in names:
        if name:
            out.add(name)
            for part in re.split(r"[·•．.]", name):
                if len(part) >= 2:
                    out.add(part)
    return out


DELIMS = set("的与和跟、，。！？；： “”「」\"『』·•．")

def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _is_name_delim(text: str, idx: int) -> bool:
    if idx < 0 or idx >= len(text):
        return True
    ch = text[idx]
    if (ch in DELIMS) or (not _is_cjk(ch)):
        return True
    # 「大狗苏茜」：把「大狗」视为名前界
    if idx >= 1 and text.startswith("大狗", idx - 1):
        return True
    return False


def _bounded_names(text: str, banned: set[str]) -> list[str]:
    found = []
    for m in DOT_NAME.finditer(text):
        raw = m.group(0)
        if raw not in banned and raw not in found:
            found.append(raw)
    for m in QUOTED.finditer(text):
        raw = m.group(1)
        if raw and raw not in banned and raw not in found:
            found.append(raw)
    n = len(text)
    for i in range(n):
        for length in (2, 3):
            j = i + length
            if j > n:
                continue
            raw = text[i:j]
            if not all(_is_cjk(c) for c in raw) or raw.endswith("们") or raw in banned:
                continue
            left_ok = _is_name_delim(text, i - 1)
            right_ok = _is_name_delim(text, j)
            # 「进入苏茜的」：右侧「的」为界
            if left_ok or right_ok:
                if raw not in found:
                    found.append(raw)
    return found


def relation_other_names(text: str, self_names: Sequence[str], lexicon: Optional[Sequence[str]] = None) -> list[str]:
    banned = set(RELATION_STOP) | _self_name_set(self_names)
    found = _bounded_names(text, banned)
    if lexicon:
        for name in lexicon:
            if name in banned or name not in text:
                continue
            if name not in found:
                found.append(name)
    return found


def _ability_appends(candidates: Sequence[Pair], selected: Sequence[Pair]) -> list[Pair]:
    have = {ability_node_key(t) for _ch, t in selected}
    have.discard(None)
    grouped = defaultdict(list)
    selected_texts = {t for _ch, t in selected}
    for item in candidates:
        if item[1] in selected_texts:
            continue
        key = ability_node_key(item[1])
        if not key or key in have:
            continue
        grouped[key].append(item)
    extras = []
    for key, items in grouped.items():
        extras.append(_pick_representative(items))
        have.add(key)
    return extras


def _identity_rep_score(text: str) -> int:
    score = 0
    if re.search(r"将成为|成为|任命|当选|担任", text):
        score += 3
    if "委员" in text:
        score += 2
    if re.search(r"理事(?!休息室)", text):
        score += 2
    if "休息室" in text:
        score -= 1
    return score


def _identity_appends(candidates: Sequence[Pair], selected: Sequence[Pair]) -> list[Pair]:
    have = {identity_node_key(t) for _ch, t in selected}
    have.discard(None)
    grouped = defaultdict(list)
    selected_texts = {t for _ch, t in selected}
    for item in candidates:
        if item[1] in selected_texts:
            continue
        key = identity_node_key(item[1])
        if not key or key in have:
            continue
        grouped[key].append(item)
    extras = []
    for key, items in grouped.items():
        extras.append(max(items, key=lambda it: (_identity_rep_score(it[1]), -items.index(it))))
    return extras


def _relation_appends(
    candidates: Sequence[Pair], selected: Sequence[Pair], self_names: Sequence[str]
) -> list[Pair]:
    lexicon = []
    seen_n = set()
    for _ch, text in candidates:
        for name in relation_other_names(text, self_names):
            if name not in seen_n:
                seen_n.add(name)
                lexicon.append(name)
    chapters_by = defaultdict(set)
    items_by = defaultdict(list)
    for item in candidates:
        ch, text = item
        for name in relation_other_names(text, self_names, lexicon=lexicon):
            chapters_by[name].add(ch)
            items_by[name].append(item)
    extras = []
    selected_texts = {t for _ch, t in selected}
    for name, chapters in chapters_by.items():
        distinct = {c for c in chapters if c is not None}
        if len(distinct) < RELATION_MIN_CHAPTERS:
            continue
        items = items_by[name]
        for item in (items[0], items[-1]):
            if item[1] not in selected_texts:
                extras.append(item)
                selected_texts.add(item[1])
    return extras


def append_stage_nodes(
    candidates: Sequence[Pair],
    sampled: Sequence[Pair],
    category: Optional[str],
    names: Optional[Sequence[str]] = None,
) -> list[Pair]:
    """追加未入窗的阶段节点，不删除已抽中的位置窗句子；不设 2 条限额。"""
    selected = list(sampled)
    if category not in NODE_CATEGORIES:
        return selected
    if category == "能力":
        extras = _ability_appends(candidates, selected)
    elif category == "身份":
        extras = _identity_appends(candidates, selected)
    else:
        extras = _relation_appends(candidates, selected, names or [])
    seen_text = {t for _ch, t in selected}
    seen_pair = set(selected)
    for item in extras:
        _unique_append(selected, item, seen_text, seen_pair)
    rank = {item: i for i, item in enumerate(candidates)}
    selected.sort(key=lambda item: rank.get(item, 10**9))
    return selected


def sample_pairs(
    pairs: Sequence[Pair],
    cap: int,
    strategy: str,
) -> list[Pair]:
    if type(cap) is not int or cap < 1:
        raise ValueError("max_evidence_per_category 必须是正整数")
    if strategy not in STRATEGIES:
        raise ValueError(_strategy_error())
    ordered = list(pairs)
    if strategy == "earliest":
        return ordered[:cap]
    if strategy == "earliest_mid_latest":
        return sample_earliest_mid_latest(ordered, cap)
    if len(ordered) <= cap:
        return ordered
    n_early = (cap + 1) // 2
    n_late = cap // 2
    selected: list[Pair] = []
    seen_text: set[str] = set()
    seen_pair: set[Pair] = set()
    for item in ordered[:n_early]:
        _unique_append(selected, item, seen_text, seen_pair)
    for item in (ordered[-n_late:] if n_late else []):
        _unique_append(selected, item, seen_text, seen_pair)
    return selected


def sample_aligned(
    texts: Sequence[str],
    chapters: Optional[Sequence[int]],
    cap: int,
    strategy: str,
    category: Optional[str] = None,
    names: Optional[Sequence[str]] = None,
) -> Tuple[list[str], list[int]]:
    """对并行的证据句与章节号抽样，保持对齐。"""
    text_list = list(texts)
    if chapters is None:
        ch_list: list[Optional[int]] = [None] * len(text_list)
        had_chapters = False
    else:
        ch_list = list(chapters)
        had_chapters = True
        if len(ch_list) != len(text_list):
            raise ValueError("evidence 与 evidence_chapters 长度必须一致")
    pairs = list(zip(ch_list, text_list))
    out = sample_pairs(pairs, cap, strategy)
    if strategy == "earliest_mid_latest":
        out = append_stage_nodes(pairs, out, category, names)
    out_texts = [t for _, t in out]
    if not had_chapters:
        return out_texts, []
    return out_texts, [int(ch) for ch, _ in out]


def strategy_from_rules(rules: dict) -> str:
    return rules.get("sample_strategy") or UNPROFILED_STRATEGY


def select_category_evidence(
    rules: dict,
    texts: Sequence[str],
    chapters: Optional[Sequence[int]],
    category: Optional[str] = None,
    names: Optional[Sequence[str]] = None,
):
    """先按类过滤，再做位置抽样；earliest_mid_latest 再追加阶段节点。

    category／names 可缺省，以兼容旧调用（不过滤、不追加节点）。
    正式抽取应传入类别与候选人姓名／别名。
    """
    text_list = list(texts)
    if chapters is None:
        ch_list: Optional[list] = None
    else:
        ch_list = list(chapters)
        if len(ch_list) != len(text_list):
            raise ValueError("evidence 与 evidence_chapters 长度必须一致")
    if category is not None:
        kept_t = []
        kept_c = []
        name_list = list(names or [])
        for i, text in enumerate(text_list):
            if keep_evidence(category, text, name_list):
                kept_t.append(text)
                if ch_list is not None:
                    kept_c.append(ch_list[i])
        text_list = kept_t
        ch_list = kept_c if ch_list is not None else None
    cap = rules["max_evidence_per_category"]
    return sample_aligned(
        text_list, ch_list, cap, strategy_from_rules(rules),
        category=category, names=names,
    )


def select_category_evidence_with_lines(
    rules: dict,
    texts: Sequence[str],
    chapters: Optional[Sequence[int]],
    lines: Optional[Sequence[int]],
    category: Optional[str] = None,
    names: Optional[Sequence[str]] = None,
) -> Tuple[list[str], list[int], list[int]]:
    """与 select_category_evidence 相同，但同步保持 1-based 原文行号逐条对齐。"""
    text_list = list(texts)
    ch_list = None if chapters is None else list(chapters)
    ln_list = None if lines is None else list(lines)
    if ch_list is not None and len(ch_list) != len(text_list):
        raise ValueError("evidence 与 evidence_chapters 长度必须一致")
    if ln_list is not None and len(ln_list) != len(text_list):
        raise ValueError("evidence 与 evidence_lines 长度必须一致")
    if category is not None:
        kept_t: list[str] = []
        kept_c: list[int] = []
        kept_l: list[int] = []
        name_list = list(names or [])
        for i, text in enumerate(text_list):
            if keep_evidence(category, text, name_list):
                kept_t.append(text)
                if ch_list is not None:
                    kept_c.append(ch_list[i])
                if ln_list is not None:
                    kept_l.append(ln_list[i])
        text_list = kept_t
        ch_list = kept_c if ch_list is not None else None
        ln_list = kept_l if ln_list is not None else None

    line_by_pair: dict[tuple[Optional[int], str], int] = {}
    if ln_list is not None:
        for i, text in enumerate(text_list):
            ch = ch_list[i] if ch_list is not None else None
            line_by_pair.setdefault((ch, text), int(ln_list[i]))

    cap = rules["max_evidence_per_category"]
    out_texts, out_chs = sample_aligned(
        text_list, ch_list, cap, strategy_from_rules(rules),
        category=category, names=names,
    )
    if ln_list is None:
        return out_texts, out_chs, []
    out_lines: list[int] = []
    for idx, text in enumerate(out_texts):
        ch = out_chs[idx] if idx < len(out_chs) else None
        out_lines.append(line_by_pair[(ch, text)])
    return out_texts, out_chs, out_lines
