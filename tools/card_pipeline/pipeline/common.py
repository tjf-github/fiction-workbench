"""fic-pipeline 胶水脚本公用函数（标准库 + jsonschema）。"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("FIC_PIPELINE_ROOT") or Path(__file__).resolve().parent.parent)
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
TZ = _dt.timezone(_dt.timedelta(hours=8))  # 用户时区 Asia/Shanghai


def root() -> Path:
    return Path(os.environ.get("FIC_PIPELINE_ROOT") or ROOT)


def staging_dir(run_id: str) -> Path:
    return root() / "staging" / run_id


def now_iso() -> str:
    return _dt.datetime.now(TZ).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


class ValidationError(Exception):
    pass


def validate(data, schema_name: str) -> None:
    """用 schemas/<schema_name>.schema.json 校验；失败抛 ValidationError（列出全部错误）。"""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        sys.exit("缺少 jsonschema：请安装 jsonschema（如 pip install jsonschema）")
    schema = load_json(SCHEMA_DIR / f"{schema_name}.schema.json")
    v = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errs = sorted(v.iter_errors(data), key=lambda e: list(e.path))
    if errs:
        msg = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs[:20])
        raise ValidationError(f"{schema_name} 校验失败：{msg}")


_BAD = re.compile(r'[\\/:*?"<>|\s]+')


def safe_name(s: str) -> str:
    s = _BAD.sub("_", s).strip("._")
    return s or "untitled"
