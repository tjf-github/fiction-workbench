#!/usr/bin/env python3
"""第④段：导出人物卡到 output/<书名>/<run>/。

默认只导出 review.status=confirmed 的卡片；
传入 --include-pending 时，额外把 pending 卡片导出为 `<stem>-待审草稿.md`
供 Gemini + 人工精审（配合 scripts/review_material_ui.py 并排核对原文行号），绝不覆盖正式定稿。

用法：
  export_cards.py --run-id R [--book-name 名] [--format w2-md|legacy] [--include-pending]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

KIND_CN = {"character": "角色", "world_entry": "世界书", "relationship": "关系"}
W2_SECTIONS = (
    ("一、基础身份与阶段边界", "基础身份与阶段边界"),
    ("二、外貌与衣着物理结构", "外貌与衣着物理结构"),
    ("三、习惯动作与职业感官", "习惯动作与职业感官"),
    ("四、说话指纹与原声标本", "说话指纹与原声标本"),
    ("五、关系杠杆与专属面具", "关系杠杆与专属面具"),
    ("六、人物心理底色与防御边界", "人物心理底色与防御边界"),
)
W2_FIELD_SET = {field for _, field in W2_SECTIONS}


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _source_tag(it: dict) -> str:
    if it.get("basis") != "原文":
        return "〔推导〕"
    locs: list[str] = []
    for s in it.get("sources") or []:
        if s.get("line") is not None:
            loc = f"L{s['line']}"
        elif s.get("chapter") is not None:
            loc = f"第{s['chapter']}章"
        else:
            loc = "原文"
        if loc not in locs:
            locs.append(loc)
    return f"〔原文·{', '.join(locs)}〕" if locs else "〔原文〕"


def render_md(card: dict) -> str:
    """旧版扁平 Markdown 渲染（兼容 legacy 模式）。"""
    out = [f"# {card['title']}", "", f"- 类型：{KIND_CN.get(card['kind'], card['kind'])}"]
    if card.get("aliases"):
        out.append("- 别名：" + "、".join(a["name"] for a in card["aliases"]))
    if card.get("relationship"):
        r = card["relationship"]
        out.append(f"- 关系：{r['source_name']} → {r['target_name']}")
    rv = card["review"]
    out.append(f"- 确认：{rv['status']} @ {rv.get('reviewed_at') or rv.get('confirmed_at', '?')}" + (f"（{rv['note']}）" if rv.get("note") else ""))
    groups: dict[str, list] = {}
    for it in card["items"]:
        groups.setdefault(it["field"], []).append(it)
    for field, items in groups.items():
        out += ["", f"## {field}", ""]
        for it in items:
            out.append(f"- [{it['basis']}] {it['text']}")
            for s in it.get("sources", []):
                q = f"“{s['raw_quote']}”" if s.get("raw_quote") else ""
                loc_parts = []
                if "chapter" in s:
                    loc_parts.append(f"第 {s['chapter']} 章")
                if "line" in s:
                    loc_parts.append(f"原本:L{s['line']}")
                loc = f"（{'，'.join(loc_parts)}）" if loc_parts else ""
                out.append(f"  - 出处：{q}{loc} `{s['ref']}`")
    inp = card["inputs"]
    out += ["", "---", f"来源：atlas {inp['atlas_commit'][:10]}，产物 sha256 {inp['atlas_export_sha256'][:12]}，模型 {inp.get('model', '?')}", ""]
    return "\n".join(out)


def render_w2_md(card: dict) -> str:
    """按 v3 标准 W2 六段式渲染人物书，并附可供 review_material_ui.py 直接核对的原文出处表。"""
    rv = card["review"]
    is_confirmed = rv["status"] == "confirmed"
    status_label = "定稿版" if is_confirmed else "待审草稿"
    out = [
        f"{card['title']} · 人物书（{status_label}）",
        "",
        "档案定位：本文件为纯常驻人物档案（W2 资产底座），已剥离单场剧本、负向禁令与元规则总结句。下游装配 W3 场面卡时，仅按需摘录对应阶段的物理锚点与说话样本。",
        "证据标注说明：〔原文·L行号〕 为原作明确事实；〔推导〕 为基于原作设定的合理推演。",
    ]
    if not is_confirmed:
        out.append("> ⚠️ 状态：待审草稿（pending）—— 请经 Gemini + 人工核对原文行号并精修后再 confirm 定稿，勿直接覆盖 `W2-人物书定稿/`。")
    if card.get("aliases"):
        aliases_str = "、".join(
            f"{a['name']}（{a.get('basis', '推断')}）" for a in card["aliases"]
        )
        out += ["", f"别名线索：{aliases_str}"]

    groups: dict[str, list] = {}
    for it in card["items"]:
        groups.setdefault(it["field"], []).append(it)

    for heading, field in W2_SECTIONS:
        out += ["", heading, ""]
        items = groups.get(field) or []
        if not items:
            out.append("- （本轮抽取无直接证据，待 Gemini / 人工核对补充）")
            continue
        for it in items:
            out.append(f"- {it['text']}{_source_tag(it)}")

    extras = [(f, its) for f, its in groups.items() if f not in W2_FIELD_SET]
    if extras:
        out += ["", "七、其他待归类条目", ""]
        for field, items in extras:
            for it in items:
                out.append(f"- [{field}] {it['text']}{_source_tag(it)}")

    # 原文出处核对表：标题刻意不带“附录”字样，避免被 scripts/review_material.py 的 EXCLUDED_SECTION 跳过。
    table_rows: list[str] = []
    for it in card["items"]:
        if it.get("basis") != "原文":
            continue
        for s in it.get("sources") or []:
            if s.get("line") is None:
                continue
            ev_id = f"原本:L{s['line']}"
            val = _escape_cell(it["text"])
            if s.get("raw_quote"):
                val = f"{val}（原句：{_escape_cell(s['raw_quote'])}）"
            table_rows.append(
                f"| {ev_id} | {_escape_cell(card['title'])} | {_escape_cell(it['field'])} | {val} |"
            )

    if table_rows:
        out += [
            "",
            "## 原文出处核对表",
            "",
            "| 证据ID | 主体 | 属性/关系 | 值 |",
            "|---|---|---|---|",
            *table_rows,
        ]

    inp = card["inputs"]
    out += [
        "",
        "---",
        f"来源：run `{card.get('run_id', '?')}` · atlas `{inp['atlas_commit'][:10]}` · 产物 sha256 `{inp['atlas_export_sha256'][:12]}` · 初建模型 `{inp.get('model', '?')}` · 审核状态 `{rv['status']}`",
        "",
    ]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--book-name")
    ap.add_argument("--format", choices=("w2-md", "legacy"), default="w2-md", help="Markdown 导出格式（默认 w2-md 六段式）")
    ap.add_argument("--include-pending", action="store_true", help="同时导出 pending 卡片为 *-待审草稿.md，供 Gemini + 人工精审")
    a = ap.parse_args(argv)
    run_dir = C.staging_dir(a.run_id)
    book = a.book_name or C.load_json(run_dir / "inputs.json")["book_name"]
    dest = C.root() / "output" / C.safe_name(book) / a.run_id
    allowed_statuses = {"confirmed", "pending"} if a.include_pending else {"confirmed"}
    rows, used = [], set()
    cards = []
    for p in sorted((run_dir / "cards").glob("*.json")):
        c = C.load_json(p)
        if c["review"]["status"] not in allowed_statuses:
            continue
        C.validate(c, "staging-card.v1")
        cards.append(c)
    dest.mkdir(parents=True, exist_ok=True)
    renderer = render_w2_md if a.format == "w2-md" else render_md
    for c in cards:
        is_confirmed = c["review"]["status"] == "confirmed"
        stem = f"{c['kind']}-{C.safe_name(c['title'])}"
        if not is_confirmed:
            stem += "-待审草稿"
        if stem in used:  # 重名时追加 card_id 尾段
            stem += "-" + C.safe_name(c["card_id"])
        used.add(stem)
        C.dump_json(dest / f"{stem}.json", c)
        (dest / f"{stem}.md").write_text(renderer(c), encoding="utf-8")
        y = sum(1 for it in c["items"] if it["basis"] == "原文")
        rows.append(
            f"| [{c['title']}]({stem}.md) | {KIND_CN.get(c['kind'], c['kind'])} | {c['review']['status']} | {len(c['items'])} | {y} | {len(c['items'])-y} |"
        )
    scope_desc = "已确认与待审草稿" if a.include_pending else "已确认卡片"
    idx = [
        f"# 《{book}》{scope_desc}（run {a.run_id}）",
        "",
        f"导出时间：{C.now_iso()}，格式 `{a.format}`，共 {len(rows)} 张",
        "",
        "| 名字 | 类型 | 状态 | 条目 | 原文 | 推断 |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    (dest / "index.md").write_text("\n".join(idx), encoding="utf-8")
    print(f"导出 {len(rows)} 张卡片（{scope_desc}，格式 {a.format}）→ {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
