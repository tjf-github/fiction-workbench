"""抽样前的归属过滤：名字出现但属性明显不属于此人的句子不进该类窗。

只覆盖本批已核对的保守模式，不做泛用 NLP。
过滤是正确性修正：配书与未配书的抽取都要过滤。不改全局 character_rules.json。
"""

from __future__ import annotations

import re
from typing import Sequence

# 能力句里用于判断「不是纯日常技艺」的途径线索（通用，不是某书途径名表）。
PATHWAY_CUES = ("魔药", "晋升", "序列", "读心")
EVERYDAY_SKILLS = ("厨艺", "画画")
TALENT_WORDS = ("擅长", "天赋")
SEE_OTHER = re.compile(r"(看见|望见|看到)一位")
KIN = r"(哥哥|妹妹|弟弟|姐姐|兄妹)"
THROUGH_GRASP = re.compile(
    r"通过(?P<mid>.{0,30}?)(?:掌握|了解|得知).{0,12}" + KIN
)
QUOTED_NAME = re.compile("[“「\"『]([^”」\"』]{2,12})[”」\"』]")
MODIFIER_NAME = re.compile(r"(?P<name>[一-鿿]{2,4})的[“「\"『]")
CJK = re.compile(r"[一-鿿]")


def _names(names: Sequence[str]) -> list[str]:
    seen = set()
    out = []
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return sorted(out, key=len, reverse=True)


def name_spans(text: str, names: Sequence[str]) -> list[tuple[int, int, str]]:
    """候选人名／别名在句中的跨度。最长优先；「正义」不吃掉「正义女神」。"""
    ordered = _names(names)
    taken = [False] * len(text)
    spans = []
    for name in ordered:
        start = 0
        while True:
            i = text.find(name, start)
            if i < 0:
                break
            j = i + len(name)
            start = i + 1
            if any(taken[i:j]):
                continue
            # 「正义女神」不是别名「正义」
            if text.startswith("女神", j) and not any(
                other != name and other.startswith(name + "女神") for other in ordered
            ):
                continue
            if taken[i:j].count(True) == 0:
                for k in range(i, j):
                    taken[k] = True
                spans.append((i, j, name))
    spans.sort()
    return spans


def _has_pathway(text: str) -> bool:
    return any(cue in text for cue in PATHWAY_CUES)


def _has_everyday(text: str) -> bool:
    return any(skill in text for skill in EVERYDAY_SKILLS)


def _other_name_spans(text: str, names: Sequence[str]) -> list[tuple[int, int]]:
    mine = {(s, e) for s, e, _ in name_spans(text, names)}
    aliases = set(_names(names))
    out = []
    for m in QUOTED_NAME.finditer(text):
        if m.group(1) in aliases:
            continue
        span = (m.start(1), m.end(1))
        if span not in mine:
            out.append(span)
    for m in MODIFIER_NAME.finditer(text):
        if m.group("name") in aliases:
            continue
        span = (m.start("name"), m.end("name"))
        if span not in mine:
            out.append(span)
    return out


def _min_dist(pos: int, spans: Sequence[tuple[int, int]]) -> float:
    if not spans:
        return float("inf")
    best = float("inf")
    for s, e in spans:
        if s <= pos < e:
            return 0.0
        best = min(best, abs(pos - s), abs(pos - e))
    return best


def talent_closer_to_other_name(text: str, names: Sequence[str]) -> bool:
    """「擅长／天赋」更靠近句中另一个专名，而不是候选人。"""
    mine = [(s, e) for s, e, _ in name_spans(text, names)]
    others = _other_name_spans(text, names)
    if not others:
        return False
    hit = False
    for word in TALENT_WORDS:
        start = 0
        while True:
            i = text.find(word, start)
            if i < 0:
                break
            hit = True
            d_mine = _min_dist(i, mine)
            d_other = _min_dist(i, others)
            if d_other < d_mine:
                return True
            start = i + len(word)
    return False


def keep_evidence(category: str, text: str, names: Sequence[str]) -> bool:
    """True 表示该句可以进入这类证据窗。"""
    if not text:
        return False
    if category == "外貌":
        return not SEE_OTHER.search(text)
    if category == "能力":
        if _has_everyday(text) and not _has_pathway(text):
            return False
        if re.search(r"在这方面.{0,8}(天赋|擅长)", text) and not _has_pathway(text):
            return False
        if talent_closer_to_other_name(text, names) and not _has_pathway(text):
            return False
        return True
    if category == "性格":
        if "正义女神" in text:
            return False
        if "牌面" in text and ("正义" in text or "塔罗" in text):
            return False
        return True
    if category == "关系":
        aliases = _names(names)
        for m in THROUGH_GRASP.finditer(text):
            mid = m.group("mid") or ""
            if any(alias and alias in mid for alias in aliases):
                return False
        return True
    return True
