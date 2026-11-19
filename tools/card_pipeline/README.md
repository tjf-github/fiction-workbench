# 上游建卡流水线（atlas + prompt-compiler → W2 人物书）

本目录将 `narrative-atlas`（纯规则原文抽证）、`prompt-os` 提示包编译器（`atlas_import`）与 `fic-pipeline` 胶水脚本收拢为统一本地工具，服务于：

`原文 txt → atlas 抽证（带 原本:L<行号> 与 原声对白） → prompt_compiler 编 W2 六段式提示包 → grokbot 批量初建卡 → import-result 逐字防幻觉校验 → export_cards 导出 W2 待审草稿 → Gemini + 人工（配合 scripts/review_material_ui.py）精审定稿 → W2-人物书定稿/`

---

## 目录说明

- `narrative_atlas/`：纯规则抽取器（已补 1-based `evidence_lines` 原文行号、早中晚跨度抽样、阶段节点追加与 `原声对白` 槽位）
- `prompt_compiler/`：`atlas_import.py` 与 CLI（默认输出对齐 v3 `W2 六段式` 与防红烧肉铁律的建卡提示包）
- `pipeline/`：`run_pipeline.py`、`confirm.py`、`export_cards.py`、`export_atlas_feedback.py`
- `schemas/`：统一单一事实源（`atlas-export.v1` / `staging-card.v1` / `atlas-feedback.v1`）
- `books/`：按书配置 profile（如 `gmzz.json`）
- `staging/` & `output/`：运行期目录（已写入 `.gitignore`）

---

## 标准用法（5 步闭环）

### 1. 抽取原文证据 + 编译 W2 建卡提示包（喂给 grokbot）

```powershell
python -X utf8 -B tools/card_pipeline/pipeline/run_pipeline.py run `
  --book <原文.txt> `
  --book-name 诡秘之主 `
  --book-profile tools/card_pipeline/books/gmzz.json `
  --run-id gmzz-w2-001 `
  --limit 10
```

产出：`tools/card_pipeline/staging/gmzz-w2-001/prompt.md`（每条证据自带 `〔第X章 / 原本:L行号〕`）。

### 2. 把 `prompt.md` 交给 grokbot 生成 JSON，导回并做逐字防幻觉校验

```powershell
python -X utf8 -B tools/card_pipeline/pipeline/run_pipeline.py import-result `
  --run-id gmzz-w2-001 `
  --result <grokbot返回.json> `
  --model grokbot `
  --cloud yes
```

- 任一 `raw_quote` 与原文证据不一致，或反馈缺原文 `quotes`，整份拒收（退出码 3）。
- 校验通过后自动回填 `sources[].chapter` 与 `sources[].line`，卡片写入 `staging/<run>/cards/*.json`（强制 `pending` 态）。

### 3. 导出 W2 待审草稿，交给 Gemini + 你在 `review_material_ui.py` 里精审

```powershell
python -X utf8 -B tools/card_pipeline/pipeline/export_cards.py `
  --run-id gmzz-w2-001 `
  --format w2-md `
  --include-pending
```

- 输出 `tools/card_pipeline/output/<书名>/<run>/character-<角色>-待审草稿.md`。
- 文末自带 `## 原文出处核对表`（`原本:L<行号>`），可直接打开 `python -B scripts/review_material_ui.py` 与原著并排核对。

### 4. 审核通过后确认定稿，导出正式 W2 人物书

```powershell
python -X utf8 -B tools/card_pipeline/pipeline/confirm.py --run-id gmzz-w2-001 --set <card_id> confirmed --note "Gemini+人工核对通过"
python -X utf8 -B tools/card_pipeline/pipeline/export_cards.py --run-id gmzz-w2-001 --format w2-md
```

### 5. （可选）导出已确认的 atlas 纠错反馈

```powershell
python -X utf8 -B tools/card_pipeline/pipeline/export_atlas_feedback.py --run-id gmzz-w2-001
```
