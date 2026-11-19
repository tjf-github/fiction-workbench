"""prompt-os atlas 提示包编译命令（fic-pipeline 编译钩子）。

  python -B phase-4/app/atlas_import_cli.py compile --atlas-export PATH --export-ref REF \
      --characters 0,2 --prompt-file OUT [--book-name 书名]

退出码：0 成功；2 参数或读写错误；3 校验失败。
成功时 stdout 只有一行 JSON（含 run_id）；出错时 stderr 只有一行 JSON（error、exit_code）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas_import as A  # noqa: E402

EXIT_OK, EXIT_ARGS, EXIT_INVALID = 0, 2, 3


def _emit_error(code: int, msg: str) -> None:
    print(json.dumps({"error": msg, "exit_code": code}, ensure_ascii=False), file=sys.stderr)


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # 参数错误：stderr 一行 JSON，退出码 2
        _emit_error(EXIT_ARGS, message)
        raise SystemExit(EXIT_ARGS)


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(allow_abbrev=False, prog="atlas_import_cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("compile", allow_abbrev=False, help="atlas-export.v1 → 建卡与筛选提示包")
    c.add_argument("--atlas-export", required=True, help="atlas 产物 JSON 路径")
    c.add_argument("--export-ref", required=True, help="证据 ref 前缀（= fic-pipeline inputs.json 的 atlas_export）")
    c.add_argument("--characters", required=True, help="候选序号，逗号分隔，如 0,1,4")
    c.add_argument("--prompt-file", required=True, help="提示包输出路径")
    c.add_argument("--book-name", dest="book_name", help="书名（提示包标题；缺省用产物文件名）")
    c.add_argument("--profile", choices=A.PROMPT_PROFILES, default="w2", help="提示包模板口径（默认 w2 六段式；legacy 为旧版）")
    return ap


def _fail(code: int, msg: str) -> int:
    _emit_error(code, msg)
    return code


def cmd_compile(a) -> int:
    export = Path(a.atlas_export)
    try:
        A.check_export_ref(a.export_ref)
    except A.ExportRefError as e:
        return _fail(EXIT_ARGS, str(e))
    try:
        A.verify_schema_copies()
    except A.AtlasImportError as e:
        return _fail(EXIT_INVALID, str(e))
    if a.book_name is not None and not a.book_name.strip():
        return _fail(EXIT_ARGS, "--book-name 不能为空")
    try:
        data, sha = A.load_export(export)
    except OSError as e:
        return _fail(EXIT_ARGS, f"读不到 atlas 产物：{e}")
    except A.AtlasImportError as e:
        return _fail(EXIT_INVALID, str(e))
    try:
        idx = A.parse_indices(a.characters, len(data["characters"]))
    except A.AtlasImportError as e:
        return _fail(EXIT_INVALID, str(e))
    book = a.book_name.strip() if a.book_name else export.stem
    run_id = A.make_run_id(sha, idx)
    text = A.compile_pack(data, a.export_ref, idx, book, run_id, sha, profile=a.profile)
    out = Path(a.prompt_file)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    except OSError as e:
        return _fail(EXIT_ARGS, f"写不出提示包：{e}")
    print(json.dumps({
        "run_id": run_id,
        "profile": a.profile,
        "prompt_file": str(out),
        "prompt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "atlas_export": str(export),
        "atlas_export_sha256": sha,
        "export_ref": a.export_ref,
        "characters": idx,
        "book_name": book,
        "book_name_source": "arg" if a.book_name else "export_stem",
        "tool_version": data.get("tool_version"),
        "rules_sha256": data.get("rules_sha256"),
    }, ensure_ascii=False))
    return EXIT_OK


def main(argv=None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd != "compile":
        return _fail(EXIT_ARGS, "缺少子命令（只支持 compile）")
    return cmd_compile(a)


if __name__ == "__main__":
    sys.exit(main())
