#!/usr/bin/env python3
"""第⑤段：把 staging/<run>/feedback.json 中 confirmed=true 的条目导出为给 atlas 的 Markdown 建议清单。
不修改 atlas 仓库；由人手工应用到 curation.json / 规则。

  export_atlas_feedback.py --run-id R [-o 输出.md]   默认 staging/R/atlas-feedback.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

LANDING = {  # 约定 §6.3
    "reject_not_person": "curation.json 判定 / 停用词建议",
    "reject_male": "curation.json 判定",
    "split_alias": "合并守卫（T9-4）反例",
    "merge_alias": "alias_map 建议",
    "rename": "curation.json",
    "missed": "召回反例（T9-6）",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("-o", "--output")
    a = ap.parse_args(argv)
    run_dir = C.staging_dir(a.run_id)
    fb = C.load_json(run_dir / "feedback.json")
    C.validate(fb, "atlas-feedback.v1")
    ok = [e for e in fb["entries"] if e.get("confirmed") is True]
    out = ["# 给 narrative-atlas 的反馈建议（仅供人工应用）", "",
           f"- run：{a.run_id}", f"- atlas 产物：`{fb['atlas_export']}`（sha256 {fb.get('atlas_export_sha256', '?')[:12]}）",
           f"- atlas 提交：{fb['atlas_commit']}", f"- 规则 sha256：{fb['atlas_rules_sha256']}",
           f"- 已确认 {len(ok)} 条 / 共 {len(fb['entries'])} 条", ""]
    for t, land in LANDING.items():
        es = [e for e in ok if e["type"] == t]
        if not es:
            continue
        out += [f"## {t}（建议落点：{land}）", ""]
        for e in es:
            extra = "".join(f"；{k}={e[k]}" for k in ("atlas_index", "alias", "suggested") if k in e)
            out.append(f"- **{e['candidate']}**{extra}：{e['reason']}（判定：{e.get('judged_by', '?')}，已人工确认）")
            for q in e.get("quotes", []):
                out.append(f"  - > {q}")
            if not e.get("quotes"):
                out.append("  - ⚠ 无原文出处（约定 §6.3 要求带出处）")
        out.append("")
    dest = Path(a.output) if a.output else run_dir / "atlas-feedback.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"导出 {len(ok)} 条已确认反馈 → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
