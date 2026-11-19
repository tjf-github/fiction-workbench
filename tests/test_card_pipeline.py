from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CARD_PIPELINE = ROOT / "tools" / "card_pipeline"
ATLAS_DIR = CARD_PIPELINE / "narrative_atlas"
COMPILER_DIR = CARD_PIPELINE / "prompt_compiler"
PIPELINE_DIR = CARD_PIPELINE / "pipeline"
SCRIPTS_DIR = ROOT / "scripts"

for p in (ATLAS_DIR, COMPILER_DIR, PIPELINE_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import atlas_import as AI  # noqa: E402
import female_characters as FC  # noqa: E402
import review_material as RM  # noqa: E402


SAMPLE_BOOK = """\
第一章 初遇
林婉儿推开木门，她身着素白长裙，腰间挂着一枚旧玉佩。
林婉儿轻声道：“我先看看账本再答复你，别急着催。”
她抬手拢了拢袖口，眼神平静地盯着桌面上的黄铜镇纸。

第二章 变故
林婉儿站在窗边，她性格冷静，擅长草药调配。
林婉儿开口道：“这笔货单对不上，今晚谁都别离港。”
她翻过纸页，指尖停在背面的炭笔记号上。

第三章 终局
林婉儿已是商行理事，她戴着银边眼镜，身穿深蓝披风。
林婉儿淡淡说道：“既然沾到船上的人，这件事我来查清。”
"""


def test_atlas_evidence_lines_and_dialogue_alignment():
    rules = FC.load_rules(ATLAS_DIR / "character_rules.json")
    rules["sample_strategy"] = "earliest_mid_latest"
    extractor = FC.Extractor(rules)
    results = extractor.extract(SAMPLE_BOOK, min_mentions=1, min_score=0.0, include_names=["林婉儿"])
    assert results, "应抽取到林婉儿"
    rec = next(r for r in results if r["name"] == "林婉儿")

    # 1. evidence / evidence_chapters / evidence_lines 逐条严格对齐
    assert set(rec["evidence"]) == set(rec["evidence_chapters"]) == set(rec["evidence_lines"])
    book_lines = SAMPLE_BOOK.splitlines()
    for cat, quotes in rec["evidence"].items():
        chs = rec["evidence_chapters"][cat]
        lns = rec["evidence_lines"][cat]
        assert len(quotes) == len(chs) == len(lns)
        for q, ln in zip(quotes, lns):
            assert 1 <= ln <= len(book_lines)
            # 抽出的分句/整句必须能在对应原文行找到核心文本
            assert q[:6] in book_lines[ln - 1]

    # 2. 原声对白槽位命中且行号准确
    assert "原声对白" in rec["evidence"]
    assert len(rec["evidence"]["原声对白"]) >= 2
    assert any("我先看看账本再答复你" in s for s in rec["evidence"]["原声对白"])
    # 第 3 行是“林婉儿轻声道：……”
    idx_first_dlg = next(i for i, s in enumerate(rec["evidence"]["原声对白"]) if "我先看看账本" in s)
    assert rec["evidence_lines"]["原声对白"][idx_first_dlg] == 3


def test_prompt_compiler_w2_profile_includes_line_numbers_and_sections():
    rules = FC.load_rules(ATLAS_DIR / "character_rules.json")
    rules["sample_strategy"] = "earliest_mid_latest"
    results = FC.Extractor(rules).extract(SAMPLE_BOOK, min_mentions=1, min_score=0.0, include_names=["林婉儿"])
    export_data = {
        "source": "sample.txt",
        "encoding": "utf-8",
        "character_count": len(results),
        "characters": results,
        "tool_version": FC.TOOL_VERSION,
        "rules_sha256": FC.rules_sha256(ATLAS_DIR / "character_rules.json"),
    }
    AI.validate_export(export_data)
    pack = AI.compile_pack(
        export_data,
        export_ref="staging/r1/atlas/sample_female_characters.json",
        indices=[0],
        book_title="测试书",
        run_id="atlaspack_test_001",
        profile="w2",
    )
    for field in AI.W2_FIELDS:
        assert field in pack
    assert "防红烧肉铁律" in pack
    assert "原本:L3" in pack


def test_end_to_end_pipeline_to_w2_md_and_review_material_check(tmp_path: Path):
    book_path = tmp_path / "demo_book.txt"
    book_path.write_text(SAMPLE_BOOK, encoding="utf-8")
    env = dict(os.environ)
    env["FIC_PIPELINE_ROOT"] = str(tmp_path)

    run_script = PIPELINE_DIR / "run_pipeline.py"
    confirm_script = PIPELINE_DIR / "confirm.py"
    export_script = PIPELINE_DIR / "export_cards.py"

    # Step 1: run atlas + compile W2 prompt pack
    p1 = subprocess.run(
        [
            sys.executable, "-X", "utf8", "-B", str(run_script), "run",
            "--book", str(book_path),
            "--book-name", "测试书",
            "--book-profile", str(CARD_PIPELINE / "books" / "gmzz.json"),
            "--protagonist", "林婉儿",
            "--run-id", "t-e2e-01",
            "--atlas-arg=--min-mentions=1",
            "--atlas-arg=--min-score=0",
        ],
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert p1.returncode == 0, p1.stdout + p1.stderr
    run_dir = tmp_path / "staging" / "t-e2e-01"
    prompt_md = (run_dir / "prompt.md").read_text(encoding="utf-8")
    assert "基础身份与阶段边界" in prompt_md
    assert "原本:L" in prompt_md

    # Step 2: 模拟 grokbot 返回（带 1 条原文外貌 + 1 条原文对白 + 1 条推导心理）
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    export_rel = inputs["atlas_export"]
    atlas_data = json.loads((tmp_path / export_rel).read_text(encoding="utf-8"))
    char_idx = next(i for i, c in enumerate(atlas_data["characters"]) if c["name"] == "林婉儿")
    char = atlas_data["characters"][char_idx]
    dlg_quote = char["evidence"]["原声对白"][0]
    dlg_line = char["evidence_lines"]["原声对白"][0]
    first_cat = next(k for k in char["evidence"] if k not in ("gender", "原声对白") and char["evidence"][k])
    first_quote = char["evidence"][first_cat][0]
    first_line = char["evidence_lines"][first_cat][0]

    model_out = {
        "cards": [
            {
                "kind": "character",
                "title": "林婉儿",
                "aliases": [],
                "items": [
                    {
                        "field": "外貌与衣着物理结构",
                        "text": "早期穿素白长裙或深蓝披风，配旧玉佩/银边眼镜",
                        "basis": "原文",
                        "source_kind": "imported",
                        "confidence": "observed",
                        "sources": [
                            {
                                "ref": f"{export_rel}#characters[{char_idx}].evidence.{first_cat}[0]",
                                "raw_quote": first_quote,
                            }
                        ],
                    },
                    {
                        "field": "说话指纹与原声标本",
                        "text": f"谈条件先看账本与实证：「{dlg_quote}」",
                        "basis": "原文",
                        "source_kind": "imported",
                        "confidence": "observed",
                        "sources": [
                            {
                                "ref": f"{export_rel}#characters[{char_idx}].evidence.原声对白[0]",
                                "raw_quote": dlg_quote,
                            }
                        ],
                    },
                    {
                        "field": "人物心理底色与防御边界",
                        "text": "面对账目异常习惯先扣留核对再做决定",
                        "basis": "推断",
                        "source_kind": "ai_inferred",
                        "confidence": "inferred",
                        "sources": [],
                    },
                ],
                "atlas": {"index": char_idx},
            }
        ],
        "feedback": [],
    }
    result_file = tmp_path / "grokbot_result.json"
    result_file.write_text(json.dumps(model_out, ensure_ascii=False, indent=2), encoding="utf-8")

    p2 = subprocess.run(
        [
            sys.executable, "-X", "utf8", "-B", str(run_script), "import-result",
            "--run-id", "t-e2e-01",
            "--result", str(result_file),
            "--model", "grokbot-test",
            "--cloud", "yes",
        ],
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert p2.returncode == 0, p2.stdout + p2.stderr
    card_files = list((run_dir / "cards").glob("*.json"))
    assert len(card_files) == 1
    card = json.loads(card_files[0].read_text(encoding="utf-8"))
    assert card["review"]["status"] == "pending"
    assert card["items"][0]["sources"][0]["line"] == first_line
    assert card["items"][1]["sources"][0]["line"] == dlg_line

    # Step 3: 导出待审 W2 草稿，并验证能被 scripts/review_material.py 直接核对行号
    p3 = subprocess.run(
        [
            sys.executable, "-X", "utf8", "-B", str(export_script),
            "--run-id", "t-e2e-01",
            "--format", "w2-md",
            "--include-pending",
        ],
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert p3.returncode == 0, p3.stdout + p3.stderr
    draft_md = tmp_path / "output" / "测试书" / "t-e2e-01" / "character-林婉儿-待审草稿.md"
    assert draft_md.is_file()
    content = draft_md.read_text(encoding="utf-8")
    assert "林婉儿 · 人物书（待审草稿）" in content
    assert "## 原文出处核对表" in content
    assert f"原本:L{dlg_line}" in content

    # 联动 scripts/review_material.py 核对所有行号（含 check_row 全套门禁）
    rows = list(RM.selected_rows(content.splitlines()))
    assert len(rows) == 2
    book_lines = SAMPLE_BOOK.splitlines()
    for _num, columns, cells, headings in rows:
        RM.check_row(columns, cells, headings, book_lines)
        row_map = dict(zip(columns, cells))
        spans = RM.line_spans(row_map["证据ID"], len(book_lines), require_original=True)
        assert spans and spans[0][0] in (first_line, dlg_line)

    # 验证防幻觉闸门：raw_quote 篡改一个字必须拒收（退出码 3）
    tampered = json.loads(json.dumps(model_out, ensure_ascii=False))
    tampered["cards"][0]["items"][0]["sources"][0]["raw_quote"] += "（编造）"
    bad_file = tmp_path / "tampered.json"
    bad_file.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    p_bad = subprocess.run(
        [
            sys.executable, "-X", "utf8", "-B", str(run_script), "import-result",
            "--run-id", "t-e2e-01",
            "--result", str(bad_file),
            "--model", "grokbot-test",
            "--cloud", "yes",
            "--force",
        ],
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert p_bad.returncode == 3
    assert "raw_quote" in p_bad.stderr

    # Step 4: confirm 后导出正式定稿版
    p4 = subprocess.run(
        [
            sys.executable, "-X", "utf8", "-B", str(confirm_script),
            "--run-id", "t-e2e-01",
            "--set", card["card_id"], "confirmed",
            "--note", "Gemini+人工核对通过",
        ],
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert p4.returncode == 0, p4.stdout + p4.stderr
    p5 = subprocess.run(
        [
            sys.executable, "-X", "utf8", "-B", str(export_script),
            "--run-id", "t-e2e-01",
            "--format", "w2-md",
        ],
        env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert p5.returncode == 0, p5.stdout + p5.stderr
    final_md = tmp_path / "output" / "测试书" / "t-e2e-01" / "character-林婉儿.md"
    assert final_md.is_file()
    assert "林婉儿 · 人物书（定稿版）" in final_md.read_text(encoding="utf-8")
