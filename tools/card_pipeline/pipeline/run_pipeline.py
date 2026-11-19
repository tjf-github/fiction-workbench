#!/usr/bin/env python3
"""链路第①②段：调用 atlas 抽取 → 校验 → 生成 staging/<run>/ 提示包；import-result 导回模型结果。

用法见 scripts/README.md。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

CARD_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROMPTS_DIR = WORKBENCH_ROOT / "prompts"
DEFAULT_ATLAS_DIR = CARD_PIPELINE_ROOT / "narrative_atlas"
sys.path.insert(0, str(CARD_PIPELINE_ROOT / "prompt_compiler"))
import atlas_import as AI  # noqa: E402

ATLAS_CLI_CANDIDATES = (
    Path("female_characters.py"),
    Path("src/narrative_atlas/female_characters.py"),
)
ATLAS_RULES_CANDIDATES = (
    Path("character_rules.json"),
    Path("src/narrative_atlas/character_rules.json"),
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()


def _git_meta(repo: Path) -> tuple[str, str, str]:
    try:
        return (
            git(repo, "rev-parse", "HEAD"),
            git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            git(repo, "status", "--porcelain"),
        )
    except (subprocess.CalledProcessError, OSError):
        return ("local-non-git", "local", "")


def _locate_in(base: Path, candidates: tuple[Path, ...]) -> Path:
    for rel in candidates:
        p = base / rel
        if p.is_file():
            return p
    return base / candidates[0]


# ---------------------------------------------------------------- run
def cmd_run(a) -> int:
    book = Path(a.book).resolve()
    repo = Path(a.atlas_repo).resolve() if a.atlas_repo else DEFAULT_ATLAS_DIR
    if not book.is_file():
        sys.exit(f"书文件不存在：{book}")
    cli = _locate_in(repo, ATLAS_CLI_CANDIDATES)
    rules = Path(a.rules).resolve() if a.rules else _locate_in(repo, ATLAS_RULES_CANDIDATES)
    if not cli.is_file() or not rules.is_file():
        sys.exit(f"atlas CLI 或规则文件不存在：{cli} / {rules}")
    run_dir = C.staging_dir(a.run_id)
    if run_dir.exists():
        sys.exit(f"{run_dir} 已存在；换一个 --run-id（脚本不覆盖已有 run）")

    commit, branch, dirty = _git_meta(repo)
    rules_sha = C.sha256_file(rules)

    atlas_out = run_dir / "atlas"
    atlas_out.mkdir(parents=True)
    argv = [sys.executable, "-X", "utf8", "-B", str(cli), str(book), "-o", str(atlas_out), "--format", "json", "--rules", str(rules)]
    if a.book_profile:
        argv += ["--book-profile", str(Path(a.book_profile).resolve())]
    full_cap = a.full_mentions_cap if a.full_mentions_cap is not None else (150 if a.full_mentions else 0)
    if full_cap > 0:
        argv += ["--full-mentions-cap", str(full_cap)]
    for p in a.protagonist or []:
        argv += ["--protagonist", p]
    argv += a.atlas_arg or []
    proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (run_dir / "atlas-stderr.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        sys.exit(f"atlas 退出码 {proc.returncode}，见 {run_dir/'atlas-stderr.log'}")
    export = atlas_out / f"{book.stem}_female_characters.json"
    if not export.is_file():
        sys.exit(f"未找到 atlas 产物 {export}")
    data = C.load_json(export)
    C.validate(data, "atlas-export.v1")
    export_rel = export.relative_to(C.root()).as_posix()
    export_sha = C.sha256_file(export)
    if data.get("rules_sha256") and data["rules_sha256"] != rules_sha:
        print(f"[警告] 产物 rules_sha256 与胶水层计算值不符：{data['rules_sha256']} vs {rules_sha}", file=sys.stderr)

    chars = list(enumerate(data["characters"]))
    if a.characters is not None:
        try:
            idx = [int(t) for t in a.characters.split(",") if t.strip()]
        except ValueError:
            sys.exit(f"--characters 须为逗号分隔的序号：{a.characters}")
        if not idx or len(set(idx)) != len(idx) or any(not 0 <= i < len(chars) for i in idx):
            sys.exit(f"--characters 序号为空、重复或越界（共 {len(chars)} 个候选）：{a.characters}")
        chars = [chars[i] for i in sorted(idx)]
    elif a.character_name:
        wanted = {n.strip() for raw in a.character_name for n in re.split(r"[,，]", raw) if n.strip()}
        matched = [
            (i, c) for i, c in chars
            if c["name"] in wanted or any(al in wanted for al in c.get("aliases") or [])
        ]
        if not matched:
            sys.exit(f"--character-name 未在 {len(chars)} 个候选中找到：{sorted(wanted)}（可尝试同时传 --protagonist）")
        chars = matched
    elif a.limit is not None:
        chars = chars[: a.limit]

    inputs = {
        "run_id": a.run_id,
        "book_name": a.book_name,
        "book": str(book),
        "book_sha256": C.sha256_file(book),
        "atlas_repo": str(repo),
        "atlas_commit": commit,
        "atlas_branch": branch,
        "atlas_dirty": bool(dirty),
        "atlas_dirty_files": dirty.splitlines(),
        "atlas_rules": str(rules),
        "atlas_rules_sha256": data.get("rules_sha256") or rules_sha,
        "atlas_rules_sha256_computed": rules_sha,
        "atlas_tool_version": data.get("tool_version"),
        "atlas_argv": argv,
        "atlas_export": export_rel,
        "atlas_export_sha256": export_sha,
        "selected_indices": [i for i, _ in chars],
        "limit": a.limit,
        "characters_arg": a.characters,
        "prompt_profile": a.profile,
        "prompt_source": "prompt-compiler",
        "prompt_os_cmd": None,
        "prompt_os_run_id": None,
        "created_at": C.now_iso(),
    }
    po_cmd = a.prompt_os_cmd or os.environ.get("FIC_PROMPT_OS_CMD")
    if po_cmd:
        inputs.update(prompt_source="prompt-os", prompt_os_cmd=po_cmd)
        inputs["prompt_os_run_id"] = prompt_os_hook(po_cmd, run_dir, inputs)
    else:
        po_run_id = AI.make_run_id(export_sha, inputs["selected_indices"])
        inputs["prompt_os_run_id"] = po_run_id
        pack_text = AI.compile_pack(
            data, export_rel, inputs["selected_indices"], a.book_name, po_run_id,
            export_sha=export_sha, profile=a.profile,
        )
        (run_dir / "prompt.md").write_text(pack_text, encoding="utf-8")
    prompt_copy: Path | None = None
    if a.prompt_out:
        prompt_copy = Path(a.prompt_out).resolve()
    elif os.environ.get("FIC_PIPELINE_ROOT") is None:
        tag = C.safe_name(chars[0][1]["name"]) if len(chars) == 1 else f"{len(chars)}人"
        prompt_copy = DEFAULT_PROMPTS_DIR / f"{C.safe_name(a.book_name)}-{tag}-{C.safe_name(a.run_id)}.md"
    if prompt_copy is not None:
        prompt_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run_dir / "prompt.md", prompt_copy)
        inputs["prompt_copy"] = str(prompt_copy)

    C.dump_json(run_dir / "inputs.json", inputs)
    C.dump_json(run_dir / "sent-log.json", {
        "run_id": a.run_id,
        "model": None,              # 人工交给模型后用 import-result --model 填
        "cloud_model_sent": None,   # 同上 --cloud yes/no
        "sent_at": None,
        "atlas_export": export_rel,
        "characters": [{"atlas_index": i, "name": c["name"],
                        "evidence_count": sum(len(v) for v in c["evidence"].values())} for i, c in chars],
        "note": "链路约定 §4：只发 prompt.md 中列出的证据句，不整本上传",
    })
    print(f"atlas: {commit[:10]} ({branch}{', dirty' if dirty else ''})，{len(data['characters'])} 个候选，本次送 {len(chars)} 个")
    print(f"提示包：{run_dir/'prompt.md'}")
    if prompt_copy is not None:
        print(f"提示词产物：{prompt_copy}")
    return 0


def prompt_os_hook(cmd_template: str, run_dir: Path, inputs: dict):
    """prompt-os 编译接入点：调用外部命令生成 prompt.md，返回 prompt-os run id。

    命令来自 --prompt-os-cmd 或环境变量 FIC_PROMPT_OS_CMD，按 shlex 切分后逐段替换占位符：
      {export}      atlas 产物绝对路径
      {export_ref}  inputs.json 的 atlas_export（ref 前缀，须原样用于证据 ref）
      {characters}  选中角色序号，逗号分隔
      {out}         须写出的 prompt.md 路径
      {book_name}   --book-name 的值（与卡片 book_name 一致）
    （具体参数名待 prompt-os 定；这里只约定占位符。）
    命令须以退出码 0 结束并写出 {out}；stdout 最后一个非空行若是含 run_id 的 JSON 则取之，否则回退 `prompt_os_run_id=<id>` 行（都没有记 null）。
    prompt-os 仓库由「创作基座-prompt-os」负责，本仓库不修改它。
    """
    out = run_dir / "prompt.md"
    vals = {"export": str(C.root() / inputs["atlas_export"]), "export_ref": inputs["atlas_export"],
            "characters": ",".join(map(str, inputs["selected_indices"])), "out": str(out),
            "book_name": inputs["book_name"]}
    argv = [tok.format(**vals) for tok in shlex.split(cmd_template)]
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (run_dir / "prompt-os.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0 or not out.is_file():
        raise C.ValidationError(f"prompt-os 命令失败（退出码 {proc.returncode}，或未写出 {out}），见 prompt-os.log")
    return parse_run_id(proc.stdout)


def parse_run_id(stdout: str):
    """优先把最后一个非空行当 JSON 读 run_id；失败再回退 `prompt_os_run_id=<id>` 行。"""
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if lines:
        try:
            obj = json.loads(lines[-1])
            if isinstance(obj, dict) and isinstance(obj.get("run_id"), str) and obj["run_id"]:
                return obj["run_id"]
        except json.JSONDecodeError:
            pass
    m = re.findall(r"^prompt_os_run_id=(\S+)\s*$", stdout, re.M)
    if not m:
        print("[警告] prompt-os 未输出 run id", file=sys.stderr)
    return m[-1] if m else None


def build_prompt(inputs: dict, chars) -> str:
    ex = inputs["atlas_export"]
    out = [f"# 建卡与筛选提示包（run {inputs['run_id']}，《{inputs['book_name']}》）", "",
           "你会收到 narrative-atlas 用纯规则抽出的“候选女性角色”。atlas 精确率约 24%，候选里有大量普通词、男性角色，",
           "别名也经常并错（例如“姜姑娘”被并进“姜望”）。请逐个判断并输出 **一个 JSON 对象**，不要输出其他文字。", "",
           "## 输出格式", "```json",
           json.dumps({
               "cards": [{
                   "kind": "character", "title": "角色名",
                   "aliases": [{"name": "别名", "basis": "推断", "note": "为何认为是同一人"}],
                   "items": [
                       {"field": "外貌", "text": "容貌清秀", "basis": "原文", "source_kind": "imported", "confidence": "observed",
                        "sources": [{"ref": f"{ex}#characters[0].evidence.外貌[0]", "raw_quote": "容貌清秀"}]},
                       {"field": "总结", "text": "……", "basis": "推断", "source_kind": "ai_inferred", "confidence": "inferred", "sources": []}],
                   "atlas": {"index": 0}}],
               "feedback": [{"type": "reject_not_person", "candidate": "候选名", "atlas_index": 3,
                             "reason": "……", "judged_by": "model", "quotes": ["原文句"]}],
           }, ensure_ascii=False, indent=2), "```", "",
           "## 规则",
           "1. 卡片按 staging-card.v1 子集：kind、title、aliases、items、atlas.index（=下面的 #编号）。card_id/inputs/review 由脚本补，不要写。",
           "2. 每条 item 标 basis：`原文`（必须带 sources，ref 照抄下面证据旁的 ref，raw_quote 必须与证据句逐字一致）或 `推断`（source_kind=ai_inferred）。",
           "3. 别名一律 basis=推断，并在 note 写理由；你认为并错的别名不要放进卡片，改写 feedback（split_alias）。",
           "4. 不要填 sources[].chapter（脚本会按 atlas 的 evidence_chapters 自动补；无此字段时不得猜）。",
           "5. 不是人名 → feedback reject_not_person；男性 → reject_male；碎片名 → rename（suggested 填全名）；两条同一人 → merge_alias；",
           "   这些候选不建卡。你的所有剔除都只是建议，会由用户逐条确认。feedback 不要写 confirmed。",
           "6. traits.关系 只有关系词没有对象；如需关系卡（kind=relationship，含 relationship.source_name/target_name），一律推断。",
           "", "## 候选角色", ""]
    for i, c in chars:
        out.append(f"### #{i} {c['name']}")
        out.append(f"- atlas 别名（未核实）：{'、'.join(c['aliases']) or '无'}")
        out.append(f"- gender={c['gender']} score={c['score']} mentions={c['mentions']} 章节数={len(c['chapters'])}"
                   + (" requested" if c.get("requested") else ""))
        for k, v in c["traits"].items():
            out.append(f"- 特征 {k}：{'、'.join(v)}")
        out.append("- 证据句：")
        for k, quotes in c["evidence"].items():
            chs = (c.get("evidence_chapters") or {}).get(k) or []
            for j, q in enumerate(quotes):
                ch = f"（第{chs[j]}章）" if j < len(chs) else ""
                out.append(f"  - `{ex}#characters[{i}].evidence.{k}[{j}]`{ch} {q}")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------- import-result
def resolve_ref(ref: str, atlas_data: dict, export_rel: str):
    """解析 '<export>#characters[i].evidence.<类>[j]'，返回 (原文句, 章节|None, 行号|None)；格式或前缀不符抛 ValidationError。"""
    m = re.fullmatch(r"(.+)#characters\[(\d+)\]\.evidence\.(.+)\[(\d+)\]", ref)
    if not m:
        raise C.ValidationError(f"ref 无法解析（应为 <atlas_export>#characters[i].evidence.<类>[j]）：{ref}")
    if m.group(1) != export_rel:
        raise C.ValidationError(f"ref 前缀与 inputs.json atlas_export（{export_rel}）不符：{ref}")
    i, cat, j = int(m.group(2)), m.group(3), int(m.group(4))
    try:
        q = atlas_data["characters"][i]["evidence"][cat][j]
    except (IndexError, KeyError):
        raise C.ValidationError(f"ref 指向不存在的证据：{ref}")
    chs = (atlas_data["characters"][i].get("evidence_chapters") or {}).get(cat) or []
    lns = (atlas_data["characters"][i].get("evidence_lines") or {}).get(cat) or []
    return q, (chs[j] if j < len(chs) else None), (lns[j] if j < len(lns) else None)


def feedback_quote_pool(inputs: dict, atlas_data: dict):
    """feedback.quotes 校验池：书原文（可读时）+ 全部 atlas 证据句。"""
    texts = []
    book = Path(inputs.get("book") or "")
    if book.is_file() and C.sha256_file(book) == inputs.get("book_sha256"):
        texts.append(book.read_text(encoding="utf-8", errors="replace"))
    for ch in atlas_data["characters"]:
        for sents in ch["evidence"].values():
            texts.extend(sents)
    return texts


def quote_in_pool(q, pool) -> bool:
    q = (q or "").strip()
    return bool(q) and any(q in t for t in pool)


def cmd_import(a) -> int:
    run_dir = C.staging_dir(a.run_id)
    inputs = C.load_json(run_dir / "inputs.json")
    atlas_data = C.load_json(C.root() / inputs["atlas_export"])
    if C.sha256_file(C.root() / inputs["atlas_export"]) != inputs["atlas_export_sha256"]:
        sys.exit("atlas 产物 sha256 与 inputs.json 不符，拒绝导入")
    raw = Path(a.result).read_text(encoding="utf-8").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(raw)
    cards_dir = run_dir / "cards"
    if (cards_dir.exists() and any(cards_dir.iterdir())) or (run_dir / "feedback.json").exists():
        if not a.force:
            sys.exit("该 run 已导入过结果；如需重导请加 --force（只覆盖 pending 卡片，已确认/已拒绝的保留）")
    cloud = {"yes": True, "no": False}[a.cloud]
    anchor = {k: inputs[k] for k in ("atlas_export", "atlas_export_sha256", "atlas_commit", "atlas_rules_sha256")}
    anchor.update(model=a.model, cloud_model_sent=cloud)
    if inputs.get("prompt_os_run_id"):
        anchor["prompt_os_run_id"] = inputs["prompt_os_run_id"]

    cards, warnings = [], []
    for n, mc in enumerate(result.get("cards", [])):
        card = {k: v for k, v in mc.items() if k not in ("card_id", "card_version", "inputs", "review", "run_id", "book_name")}
        card["card_version"] = 1
        card["run_id"] = a.run_id
        card["book_name"] = inputs["book_name"]
        card["inputs"] = dict(anchor)
        card["review"] = {"status": "pending"}
        for al in card.get("aliases", []):
            if al.get("basis") != "推断":
                warnings.append(f"卡 {card.get('title')}: 别名 {al.get('name')} basis 改为推断（约定 §6.1）")
                al["basis"] = "推断"
        idx = (card.get("atlas") or {}).get("index")
        if idx is not None:
            if not (0 <= idx < len(atlas_data["characters"])):
                raise C.ValidationError(f"卡 {card.get('title')}: atlas.index={idx} 越界")
            ac = atlas_data["characters"][idx]
            at = {"index": idx}
            for k in ("gender", "gender_confidence", "score", "mentions", "chapters", "requested"):
                if k in ac:
                    at[k] = ac[k]
            card["atlas"] = at
        for it in card.get("items", []):
            it.setdefault("source_kind", "imported" if it.get("basis") == "原文" else "ai_inferred")
            for s in it.get("sources", []):
                q, ch, ln = resolve_ref(s.get("ref", ""), atlas_data, inputs["atlas_export"])
                if "chapter" not in s and ch is not None:
                    s["chapter"] = ch
                    s["chapter_source"] = "atlas"
                if "line" not in s and ln is not None:
                    s["line"] = ln
                    s["line_source"] = "atlas"
                if "raw_quote" not in s:
                    s["raw_quote"] = q
                elif s["raw_quote"] != q:
                    raise C.ValidationError(f"卡 {card.get('title')}: raw_quote 与 {s['ref']} 原文不一致")
                if "chapter" in s and s.get("chapter_source") != "atlas":
                    warnings.append(f"卡 {card.get('title')}: sources 含 chapter={s['chapter']}，须人工核实原文（约定 §6.1）")
        card["card_id"] = f"{a.run_id}-{n:03d}-{C.safe_name(card.get('kind', 'x'))}-{C.safe_name(str(card.get('title', '')))}"
        C.validate(card, "staging-card.v1")
        cards.append(card)

    entries = []
    pool = None
    for e in result.get("feedback", []):
        e = dict(e)
        if not isinstance(e.get("quotes"), list) or not any(isinstance(q, str) and q.strip() for q in e["quotes"]):
            raise C.ValidationError(f"反馈 {e.get('type')} {e.get('candidate')}: 缺少 quotes（每条反馈必须带原文句）")
        if pool is None:
            pool = feedback_quote_pool(inputs, atlas_data)
        for q in e.get("quotes") or []:
            if not quote_in_pool(q, pool):
                raise C.ValidationError(f"反馈 {e.get('type')} {e.get('candidate')}: quotes 不是原文逐字摘录：{q[:40]}")
        e["confirmed"] = False
        e.setdefault("judged_by", "model")
        entries.append(e)
    fb = {"feedback_version": 1, **{k: inputs[k] for k in ("atlas_export", "atlas_export_sha256", "atlas_commit", "atlas_rules_sha256")},
          "entries": entries}
    if inputs.get("prompt_os_run_id"):
        fb["prompt_os_run_id"] = inputs["prompt_os_run_id"]
    C.validate(fb, "atlas-feedback.v1")

    # 全部校验通过后才写盘
    cards_dir.mkdir(exist_ok=True)
    kept = 0
    for card in cards:
        p = cards_dir / f"{card['card_id']}.json"
        if p.exists() and C.load_json(p)["review"]["status"] != "pending":
            kept += 1
            continue
        C.dump_json(p, card)
    fbp = run_dir / "feedback.json"
    if fbp.exists():  # 重导：保留已确认的条目
        old = C.load_json(fbp)["entries"]
        key = lambda e: (e["type"], e["candidate"], e.get("alias"))  # noqa: E731
        done = [e for e in old if e.get("confirmed")]
        seen = {key(e) for e in done}
        fb["entries"] = done + [e for e in entries if key(e) not in seen]
    C.dump_json(fbp, fb)
    shutil.copyfile(a.result, run_dir / "model-result.json")
    sl = C.load_json(run_dir / "sent-log.json")
    sl.update(model=a.model, cloud_model_sent=cloud, sent_at=sl.get("sent_at") or C.now_iso())
    C.dump_json(run_dir / "sent-log.json", sl)
    for w in warnings:
        print("[警告]", w, file=sys.stderr)
    print(f"导入 {len(cards)} 张卡（pending；保留已审 {kept} 张），反馈 {len(fb['entries'])} 条（confirmed=false）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="（默认）调用 atlas 并生成提示包")
    r.add_argument("--book", required=True)
    r.add_argument("--book-name", required=True)
    r.add_argument("--atlas-repo", default=None, help="atlas 目录（默认内置 tools/card_pipeline/narrative_atlas）")
    r.add_argument("--book-profile", help="按书配置 JSON（如 tools/card_pipeline/books/gmzz.json），透传给 atlas")
    r.add_argument("--rules", help="规则文件，默认 atlas 目录内 character_rules.json")
    r.add_argument("--protagonist", action="append")
    r.add_argument("--full-mentions", action="store_true", help="为点名角色开启全量原文提及行打包（默认上限 150 行，适合中配角色）")
    r.add_argument("--full-mentions-cap", type=int, default=None, help="自定义全量原文提及行上限 N（覆盖 --full-mentions 默认的 150）")
    sel = r.add_mutually_exclusive_group()
    sel.add_argument("--limit", type=int, help="只把前 N 个角色放进提示包")
    sel.add_argument("--characters", help="只把指定序号的角色放进提示包，逗号分隔，如 0,1,4（与 --limit 互斥）")
    sel.add_argument("--character-name", action="append", help="按角色主名/别名筛选进提示包（可重复或逗号分隔，与 --limit/--characters 互斥）")
    r.add_argument("--atlas-arg", action="append", help="透传给 atlas 的额外参数，如 --atlas-arg=--min-mentions=1")
    r.add_argument("--run-id", required=True)
    r.add_argument("--profile", choices=AI.PROMPT_PROFILES, default="w2", help="提示包模板口径（默认 w2 六段式；legacy 为旧版）")
    r.add_argument("--prompt-out", help="额外把生成的提示词复制到指定路径（默认自动落盘到根目录 prompts/ 下）")
    r.add_argument("--prompt-os-cmd", help="外部提示包编译命令模板（占位符 {export} {export_ref} {characters} {out}）；也可用环境变量 FIC_PROMPT_OS_CMD")
    i = sub.add_parser("import-result", help="导入模型返回的 JSON")
    i.add_argument("--run-id", required=True)
    i.add_argument("--result", required=True)
    i.add_argument("--model", required=True, help="实际使用的模型名")
    i.add_argument("--cloud", choices=["yes", "no"], required=True, help="原文证据是否发给了云端模型")
    i.add_argument("--force", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in ("run", "import-result", "-h", "--help"):
        argv = ["run", *argv]
    a = ap.parse_args(argv)
    try:
        return cmd_import(a) if a.cmd == "import-result" else cmd_run(a)
    except C.ValidationError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
