"""atlas-export.v1 → 建卡与筛选提示包（fic-pipeline 第二段，链路约定 v3.2）。

只读 atlas 产物、编译提示包；不调用模型、不写卡片。模型结果由 fic-pipeline
``run_pipeline.py import-result`` 导回并校验（ref 前缀、raw_quote 逐字、quotes 逐字）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_NAMES = ("atlas-export.v1", "atlas-feedback.v1", "staging-card.v1")
RUN_ID_PREFIX = "atlaspack_"
FEEDBACK_TYPES = ("reject_not_person", "reject_male", "split_alias", "merge_alias", "rename", "missed")
W2_FIELDS = (
    "基础身份与阶段边界",
    "外貌与衣着物理结构",
    "习惯动作与职业感官",
    "说话指纹与原声标本",
    "关系杠杆与专属面具",
    "人物心理底色与防御边界",
)
PROMPT_PROFILES = ("w2", "legacy")


class AtlasImportError(Exception):
    """输入不合约定（退出码 3）。"""


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def schema_path(name: str) -> Path:
    return SCHEMA_DIR / f"{name}.schema.json"


def verify_schema_copies(originals: Path | None = None) -> dict:
    """校验本地统一 schemas 目录下的三份 Schema 存在且为合法 JSON。返回 {name: sha12}。"""
    out = {}
    for name in SCHEMA_NAMES:
        p = schema_path(name)
        if not p.is_file():
            raise AtlasImportError(f"缺少 schema 文件：{p}")
        data = p.read_bytes()
        try:
            json.loads(data.decode("utf-8"))
        except Exception as e:
            raise AtlasImportError(f"schema {name} 不是合法 JSON：{e}") from e
        if originals is not None:
            orig = originals / f"{name}.schema.json"
            if orig.is_file() and orig.read_bytes() != data:
                raise AtlasImportError(f"schema {name} 与 {orig} 不一致")
        out[name] = _sha256_bytes(data)[:12]
    return out


def load_schema(name: str) -> dict:
    return json.loads(schema_path(name).read_text(encoding="utf-8"))


def _validate(data: Any, name: str) -> None:
    import jsonschema
    v = jsonschema.Draft202012Validator(load_schema(name))
    errs = sorted(v.iter_errors(data), key=lambda e: list(e.path))
    if errs:
        msg = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs[:10])
        raise AtlasImportError(f"{name} 校验失败：{msg}")


def validate_export(data: Any) -> None:
    """atlas-export.v1 + evidence_chapters / evidence_lines 与 evidence 逐条对齐。"""
    _validate(data, "atlas-export.v1")
    for i, c in enumerate(data["characters"]):
        ec = c.get("evidence_chapters")
        if ec is not None:
            for k, chs in ec.items():
                if k not in c["evidence"]:
                    raise AtlasImportError(f"characters[{i}].evidence_chapters.{k} 没有对应的 evidence 键")
                if len(chs) != len(c["evidence"][k]):
                    raise AtlasImportError(
                        f"characters[{i}].evidence_chapters.{k} 有 {len(chs)} 项，evidence 有 {len(c['evidence'][k])} 句")
                if any(type(x) is not int for x in chs):
                    raise AtlasImportError(f"characters[{i}].evidence_chapters.{k} 须为整数")
        el = c.get("evidence_lines")
        if el is not None:
            for k, lns in el.items():
                if k not in c["evidence"]:
                    raise AtlasImportError(f"characters[{i}].evidence_lines.{k} 没有对应的 evidence 键")
                if len(lns) != len(c["evidence"][k]):
                    raise AtlasImportError(
                        f"characters[{i}].evidence_lines.{k} 有 {len(lns)} 项，evidence 有 {len(c['evidence'][k])} 句")
                if any(type(x) is not int or x < 1 for x in lns):
                    raise AtlasImportError(f"characters[{i}].evidence_lines.{k} 须为正整数行号")


def load_export(path: Path) -> tuple[dict, str]:
    """读取并校验产物，返回 (data, sha256)。I/O 错误原样抛出（OSError）。"""
    raw = Path(path).read_bytes()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise AtlasImportError(f"atlas 产物不是合法 UTF-8 JSON：{e}") from e
    validate_export(data)
    return data, _sha256_bytes(raw)


def parse_indices(spec: str | Sequence[Any], total: int) -> list[int]:
    """'0,2,5' 或整数列表 → 升序序号。拒绝空、bool、非整数、重复、越界。"""
    if isinstance(spec, str):
        toks = [t.strip() for t in spec.split(",")]
        if not spec.strip() or any(not t for t in toks):
            raise AtlasImportError(f"--characters 为空或含空项：{spec!r}")
        vals: list[Any] = []
        for t in toks:
            if not t.isdigit() or not t.isascii():
                raise AtlasImportError(f"--characters 须为逗号分隔的非负整数：{t!r}")
            vals.append(int(t))
    else:
        vals = list(spec)
        if not vals:
            raise AtlasImportError("角色序号列表为空")
    for v in vals:
        if type(v) is not int:  # 排除 bool
            raise AtlasImportError(f"角色序号须为整数（不接受 {type(v).__name__}）：{v!r}")
        if not 0 <= v < total:
            raise AtlasImportError(f"角色序号 {v} 越界（共 {total} 个候选）")
    if len(set(vals)) != len(vals):
        raise AtlasImportError(f"角色序号重复：{vals}")
    return sorted(vals)


class ExportRefError(AtlasImportError):
    """--export-ref 本身不合法（参数错误，CLI 退出码 2）。"""


_DRIVE = re.compile(r"^[A-Za-z]:")


def check_export_ref(ref: str) -> str:
    """ref 前缀须为相对、正斜杠、无 '..' 段、不含 '#' 的非空路径。"""
    if type(ref) is not str or not ref.strip() or ref != ref.strip():
        raise ExportRefError(f"--export-ref 须为非空路径：{ref!r}")
    if "#" in ref:
        raise ExportRefError(f"--export-ref 不能含 '#'：{ref!r}")
    if "\\" in ref:
        raise ExportRefError(f"--export-ref 不能含反斜杠：{ref!r}")
    if ref.startswith("/") or _DRIVE.match(ref):
        raise ExportRefError(f"--export-ref 须为相对路径（不接受绝对路径或盘符）：{ref!r}")
    if ".." in ref.split("/"):
        raise ExportRefError(f"--export-ref 不能含 '..' 段：{ref!r}")
    return ref


def make_run_id(export_sha: str, indices: Iterable[int], now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))
    h = hashlib.sha256(f"{export_sha}|{','.join(map(str, indices))}|{now.isoformat()}".encode()).hexdigest()[:8]
    return f"{RUN_ID_PREFIX}{now.strftime('%Y%m%dT%H%M%S')}_{h}"


def output_template(export_ref: str, profile: str = "w2") -> dict:
    ev = f"{export_ref}#characters[0].evidence.外貌[0]"
    ev_other = f"{export_ref}#characters[0].evidence.原声对白[0]" if profile == "w2" else f"{export_ref}#characters[0].evidence.外貌[1]"
    if profile == "w2":
        items = [
            {"field": "外貌与衣着物理结构", "text": "（阶段：只写可拍摄的五官/衣着/随身物件，不写空泛形容）", "basis": "原文",
             "source_kind": "imported", "confidence": "observed",
             "sources": [{"ref": ev, "raw_quote": "（与该 ref 的证据句逐字相同）"}]},
            {"field": "说话指纹与原声标本", "text": "（语气/谈话习惯概括 + 原声台词定位）", "basis": "原文",
             "source_kind": "imported", "confidence": "observed",
             "sources": [{"ref": ev_other, "raw_quote": "（与该 ref 的证据句逐字相同）"}]},
            {"field": "人物心理底色与防御边界", "text": "（有依据的阶段驱动力或物理防御机制；禁止写负向禁令与抽象态势总结）",
             "basis": "推断", "source_kind": "ai_inferred", "confidence": "inferred", "sources": []},
        ]
    else:
        items = [
            {"field": "外貌", "text": "（证据支持的阶段：概括该句；不明时写阶段不明）", "basis": "原文", "source_kind": "imported",
             "confidence": "observed", "sources": [{"ref": ev, "raw_quote": "（与该 ref 的证据句逐字相同）"}]},
            {"field": "外貌", "text": "（另一独立特征/有证据的阶段；仅在确有支持时另列）", "basis": "原文", "source_kind": "imported",
             "confidence": "observed", "sources": [{"ref": ev_other, "raw_quote": "（与该 ref 的证据句逐字相同）"}]},
            {"field": "总结", "text": "（注明阶段的归纳；未知则写阶段不明，不补事实）", "basis": "推断", "source_kind": "ai_inferred",
             "confidence": "inferred", "sources": []},
        ]
    return {
        "cards": [{
            "kind": "character",
            "title": "角色名",
            "aliases": [{"name": "别名", "basis": "推断", "note": "词面依据：待核（补可核验引句及 ref，否则保持待核）；归属状态：待审（说明同一人依据/错并风险）"}],
            "items": items,
            "atlas": {"index": 0},
        }],
        "feedback": [{
            "type": "reject_not_person", "candidate": "候选名", "atlas_index": 3,
            "reason": "……", "judged_by": "model", "quotes": ["（原文句，逐字照抄）"],
        }],
    }


def _chapter_span(chapters: Sequence[int]) -> str:
    """人物出现范围只是粗定位，不是证据出处或状态有效期。"""
    if not chapters:
        return "未知（无出现章节）"
    first, last = min(chapters), max(chapters)
    def label(n: int) -> str:
        return "首个标题前" if n == 0 else f"第{n}章"
    return label(first) if first == last else f"{label(first)}—{label(last)}"


def _loc_tag(ch: int | None, line: int | None) -> str:
    parts = []
    if ch is not None:
        parts.append("首个标题前" if ch == 0 else f"第{ch}章")
    if line is not None:
        parts.append(f"原本:L{line}")
    return f"〔{' / '.join(parts)}〕" if parts else ""


def compile_pack(data: dict, export_ref: str, indices: Sequence[int], book_title: str, run_id: str,
                 export_sha: str = "", profile: str = "w2") -> str:
    if profile not in PROMPT_PROFILES:
        raise AtlasImportError(f"不支持的 profile：{profile}（可选：{'/'.join(PROMPT_PROFILES)}）")
    ex = check_export_ref(export_ref)
    tmpl = json.dumps(output_template(ex, profile=profile), ensure_ascii=False, indent=2)
    w2_rules = []
    has_full_mentions = any("全文提及" in (data["characters"][i].get("evidence") or {}) for i in indices)
    if profile == "w2":
        w2_rules = [
            f"- **W2 六段式字段对齐**：每条 item 的 `field` 必须且只能取以下六个标准大节之一：{' / '.join(f'`{f}`' for f in W2_FIELDS)}。",
            "- **防红烧肉铁律（v3）**：只写可拍摄的物理动作、随身物件、原声台词与客观阶段边界；**严禁**写「不做第二次试探」「不顶撞也不讨好」「禁止……」等负向行为概括，**严禁**写上帝视角抽象态势总结句。",
            "- **原声对白优先归位**：`原声对白` 或 `全文提及` 中的代表性台词优先写入 `说话指纹与原声标本`，保留人物真实口吻与语境。",
        ]
        if has_full_mentions:
            w2_rules.append(
                "- **全量原文充分利用**：下文已提供该角色的 `全文提及` 完整原文自然段（均带 `原本:L<行号>`），请通读全部段落，全面提取外貌衣着、微动作、说话标本、关系面具与心理驱动力，按阶段填满 W2 六段式（仍须严守 `raw_quote` 逐字一致，无依据不编造）。"
            )
    L = [f"# 建卡与筛选提示包（《{book_title}》）", "",
         f"- prompt-os run：`{run_id}`（profile：`{profile}`）",
         f"- atlas 产物 ref 前缀：`{ex}`" + (f"（sha256 {export_sha[:12]}）" if export_sha else ""),
         f"- atlas 工具版本：{data.get('tool_version') or '未提供'}；规则 sha256：{(data.get('rules_sha256') or '未提供')[:12]}",
         f"- 本次候选序号：{','.join(map(str, indices))}", "",
         "## 任务",
         "下面是 narrative-atlas 用纯规则抽出的“候选女性角色”。atlas 精确率约 24%：候选里有大量普通词和男性角色，",
         "别名也经常并错（例如“姜姑娘”被并进“姜望”）。请逐个候选判断：",
         "1. 剔除误报：不是人名的、男性角色，不建卡，写进 feedback。",
         "2. 纠正别名：并错的别名不放进卡片，写 feedback（split_alias）；两条候选其实是同一人，写 merge_alias；碎片名写 rename。",
         "3. 对确认是女性角色的候选建人物卡，卡片每条 item 标注 `原文` 或 `推断`。",
         "", "## 输出要求",
         "只输出 **一个 JSON 对象**，顶层只有 `cards` 和 `feedback` 两个键，不要输出任何其他文字、注释或 Markdown 包裹以外的说明。格式模板：",
         "```json", tmpl, "```", "",
         "### cards（staging-card.v1 子集）",
         "- 每张卡只写 `kind`、`title`、`aliases`、`items`、`atlas.index` 五项；`atlas.index` 填下文候选的 #编号。",
         "- `card_id`、`card_version`、`run_id`、`book_name`、`inputs`、`review` 由脚本补，不要写；卡片和条目里都不要写 `confirmed`。",
         "- `kind` 取 `character`、`world_entry` 或 `relationship`；relationship 卡另需 `relationship.source_name/target_name`，且条目一律 `推断`（atlas 只有关系词，没有对象）。",
         *w2_rules,
         "- `basis=原文` 的条目：`source_kind=imported`，`confidence=observed`，`sources` 至少一条；`ref` 照抄下文证据句前的 ref，`raw_quote` 与该证据句**逐字一致**（整句照抄，不增删改任何字符和标点）。任一 raw_quote 不一致，整份结果会被拒收。",
         "- `basis=推断` 的条目：`source_kind=ai_inferred`，`confidence=inferred`，`sources` 可为空数组；改名、归纳、关系都算推断。",
         "- 同一 `field` 可有多条 item：独立特征或不同阶段分别写，每条各自标 basis/sources；模板仅演示结构，不设固定字数，不要求凑足条数，无证据不补条。",
         "- 阶段范围：每条 item 的 `text` 注明有依据的阶段/时间范围（早期／晋升后／近期等，有依据才写）；无法确定就写“阶段不明”。不得把早期证据写成当前状态，未知阶段不得凭人物章节跨度补事实，也不得推定有后期发展；总结跨阶段时注明或拆条。",
         "- 具体情境与行动界限：已抽到的具体场景、顾虑、退出或界限证据，必须在对应 item 的 `text` 里保留场景范围（例如「该次聚会中……」「面对该请求时……」），不得只收成「谨慎」「冷静」「细心」这类空标签，也不得把单次情境写成无时态的习惯通例。无足够依据时宁可保留场景并写「阶段不明」，也不要抽空概括。反例：把「该次聚会上，她压低声音，在对方追问前先切断话题」只写成「谨慎」。",
         "- 入卡先核主语：先判断该句描述的对象是不是这个人，再决定能否写入对应 field。反例：把「看见一位黑发褐瞳」当成她的外貌；把牌面「正义女神」当成她的性格；把「通过她掌握了哥哥和妹妹」当成她的家人。对象不是此人的句子不要入卡。",
         "- 称号与身份：「正义小姐」等称呼可作称号或 gender 证据，不得单独支撑身份阶段。",
         "- 能力默认指途径／序列及其界限；画画、厨艺等日常技艺若写必须标明是日常技艺，且不得当成非凡天赋。",
         "- 别名词面：仅在 atlas.aliases 列表中出现，不足以证明词面来自原文。`note` 分写 `词面依据：…` 与 `归属状态：…`；无可核验原文引句及 ref 时，词面保持“待核”，有引句时写清引句、ref 及待核依据，不把模型自述当已核验。",
         "- 别名归属：`aliases` 每项 `basis` 一律写 `推断`，`note` 的归属状态写“待审”，并说明同一人依据或错并风险；词面出现不等于同一人，归属须用户审核，不因词面有引句自动确认。",
         "- 下文 traits 已按候选完整列出，不要重复抄写成第二份词表；特征词只是机械命中线索，不能代替逐字 evidence 或证明词的归属。",
         "- 不要写 `sources[].chapter` 或 `sources[].line`：产物带章节号/原文行号时脚本会自动填，没有时不得猜。",
         "", "### feedback（atlas-feedback.v1 的 entries 子集）",
         f"- `type` 取：{'、'.join(FEEDBACK_TYPES)}。",
         "- 每条写 `type`、`candidate`（atlas 中的名字；missed 写原文中的名字）、`reason`、`judged_by`（固定 `model`）、`quotes`；有对应候选时写 `atlas_index`；split_alias/merge_alias 写 `alias`；rename 在 `suggested` 写全名。",
         "- 每条反馈都必须带非空 `quotes`（至少一句支持判断的原文；缺失或为空整份结果会被拒收）；每句必须是下文证据句或书原文的逐字片段。",
         "- 不要写 `confirmed`：所有反馈都只是建议，由用户逐条确认。",
         "", "## 候选角色", ""]
    chars = data["characters"]
    for i in indices:
        c = chars[i]
        L.append(f"### #{i} {c['name']}")
        L.append(f"- atlas 别名（未核实，可能并错）：{'、'.join(c['aliases']) or '无'}")
        L.append(f"- gender={c['gender']} gender_confidence={c['gender_confidence']} score={c['score']} "
                 f"mentions={c['mentions']} 出现章节数={len(c['chapters'])}" + ("，点名纳入" if c.get("requested") else ""))
        L.append(f"- 人物级粗章节跨度：{_chapter_span(c['chapters'])}（仅出现范围，非逐句出处或状态有效期）")
        for k, v in c["traits"].items():
            if v:
                L.append(f"- 特征 {k}：{'、'.join(v)}")
        L.append("- 证据句（ref → 原文）：")
        ec = c.get("evidence_chapters") or {}
        el = c.get("evidence_lines") or {}
        for k, quotes in c["evidence"].items():
            chs = ec.get(k) or []
            lns = el.get(k) or []
            for j, q in enumerate(quotes):
                ch_val = chs[j] if j < len(chs) else None
                ln_val = lns[j] if j < len(lns) else None
                loc = _loc_tag(ch_val, ln_val)
                L.append(f"  - `{ex}#characters[{i}].evidence.{k}[{j}]`{loc} {q}")
        L.append("")
    return "\n".join(L).rstrip() + "\n"
