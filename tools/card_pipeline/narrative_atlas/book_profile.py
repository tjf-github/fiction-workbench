"""按书 profile：覆盖抽样策略与每类证据上限，并给出可复现快照。

不修改全局 character_rules.json。未提供 profile 时不改旧口径（各类最早 N 条）。
本轮不实现体系词表、supernatural 开关的词表过滤、均匀抽样或自动 N。
supernatural.mode 如出现仅记入快照，不改变本轮抽取。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

try:
    from .evidence_sample import PROFILE_DEFAULT_STRATEGY, STRATEGIES, UNPROFILED_STRATEGY
except ImportError:  # python .../female_characters.py 脚本入口
    from evidence_sample import PROFILE_DEFAULT_STRATEGY, STRATEGIES, UNPROFILED_STRATEGY


ALLOWED_TOP = frozenset({"book_id", "book_name", "supernatural", "evidence"})
ALLOWED_EVIDENCE = frozenset({"max_evidence_per_category", "sample_strategy"})
ALLOWED_SUPERNATURAL = frozenset({"mode", "system_profile", "lexicon_ref"})
BOOK_ID_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(data, name: str, allowed: frozenset) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"{name} 必须是 JSON 对象")
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{name} 有未知配置项：{', '.join(sorted(unknown))}")
    return data


def _unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"配置项重复：{key}")
        value[key] = item
    return value


def resolve_profile(profile_path: Optional[Path], rules: dict, rules_digest: Optional[str] = None):
    """返回 (effective_rules, snapshot_or_none, profile_raw_or_none)。

    snapshot 仅在提供了 book profile 时生成，未配书不写快照、不改策略默认。
    """
    if not isinstance(rules, dict):
        raise ValueError("规则必须是 JSON 对象")
    if profile_path is None:
        effective = dict(rules)
        effective.setdefault("sample_strategy", UNPROFILED_STRATEGY)
        return effective, None, None

    raw = profile_path.read_bytes()
    profile = _object(json.loads(raw, object_pairs_hook=_unique_keys), "book profile", ALLOWED_TOP)
    book_id, book_name = profile.get("book_id"), profile.get("book_name")
    if not isinstance(book_id, str) or not BOOK_ID_RE.fullmatch(book_id):
        raise ValueError("book_id 必须是 ASCII 小写标识符，例如 gmzz")
    if not isinstance(book_name, str) or not book_name.strip() or book_name != book_name.strip():
        raise ValueError("book_name 必须是没有首尾空格的非空书名")

    supernatural = _object(profile.get("supernatural", {}), "supernatural", ALLOWED_SUPERNATURAL)
    mode = supernatural.get("mode", "unset")
    if mode not in ("on", "off", "unset"):
        raise ValueError("supernatural.mode 必须是 on、off 或 unset")
    for field in ("system_profile", "lexicon_ref"):
        if field in supernatural and (not isinstance(supernatural[field], str) or not supernatural[field].strip()):
            raise ValueError(f"supernatural.{field} 必须是非空字符串")

    evidence = _object(profile.get("evidence", {}), "evidence", ALLOWED_EVIDENCE)
    cap = evidence.get("max_evidence_per_category", rules.get("max_evidence_per_category", 6))
    strategy = evidence.get("sample_strategy", PROFILE_DEFAULT_STRATEGY)
    if type(cap) is not int or cap < 1:
        raise ValueError("max_evidence_per_category 必须是正整数")
    if strategy not in STRATEGIES:
        raise ValueError("sample_strategy 必须是 " + "、".join(STRATEGIES))

    effective = dict(rules)
    effective["max_evidence_per_category"] = cap
    effective["sample_strategy"] = strategy

    ev_snap = {"max_evidence_per_category": cap, "sample_strategy": strategy}
    if strategy == "earliest_mid_latest":
        # N 仍是位置窗上限，不是写出条数；追加节点时实际条数可以大于 N。
        ev_snap["appended_stage_nodes"] = True
    snapshot = {
        "book_id": book_id,
        "book_name": book_name,
        "evidence": ev_snap,
        "supernatural": {**supernatural, "mode": mode},
        "profile_sha256": sha256_bytes(raw),
    }
    if rules_digest:
        snapshot["rules_sha256"] = rules_digest
    return effective, snapshot, raw
