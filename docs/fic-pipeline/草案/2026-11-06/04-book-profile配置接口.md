# book profile 配置接口草案（2026-11-06，v3.9 对齐）

只文档。**不改** schema / 代码。已批准行为以 `链路约定.md` §11 为准；本页补键名与实现建议，标「待两边技术确认」者不视为用户已批细节。

## 1. 命名与落点
- 建议路径：`fic-pipeline/books/<book_id>.json`（或 `book_profiles/<book_id>.json`）。
- `book_id`：稳定 ASCII slug（如 `gmzz`）；展示名另写 `book_name`（如 `诡秘之主`），与 run 的 `--book-name` / 卡片顶层一致。
- **待技术确认**：是否允许中文文件名；与现有 `runs/`、`output/<书名>/` 目录如何对照。

## 2. 建议 JSON 形状（未冻结构）
```json
{
  "book_id": "gmzz",
  "book_name": "诡秘之主",
  "supernatural": {
    "mode": "on",
    "system_profile": "gmzz-pathways",
    "lexicon_ref": "books/gmzz.supernatural-lexicon.json"
  },
  "evidence": {
    "max_evidence_per_category": 6,
    "sample_strategy": "earliest_plus_latest"
  }
}
```
- 键名 **`max_evidence_per_category`** 对齐 atlas `character_rules.json` 现键；按书覆盖时合并进生效规则，缺省 6。
- `sample_strategy` 已批默认值：`earliest_plus_latest`。枚举保留 `earliest`（legacy/对照）；`spread` **未批准为默认**，实现可预留但不得偷切默认。
- `supernatural.mode`：`on`|`off`|`unset`。缺字段 = `unset`（新书）。

## 3. 已批准语义（实现必须遵守）
| 项 | 行为 |
|---|---|
| unset | atlas 可抽可落盘；**阻断**第二段建卡；**不做**默认 off 过滤 |
| on/off | 只影响新抽取/新提示；不删原文；不回写 confirmed / 不改写 legacy 产物 |
| N | 上限；不足不补齐；不凑数 |
| 旧 run | 用当时 **生效参数快照** 复现，不读「今天的 profile」重放过滤/抽样 |

## 4. 生效快照与 hash（建议，待技术确认）
每个 run 的 `inputs.json`（或等价）应抄写：
- `book_id` / `book_name`
- 生效 `supernatural.mode`、`system_profile`、`lexicon_ref`（或「无」）
- 生效 `max_evidence_per_category`、`sample_strategy`
- `profile_sha256`、`rules_sha256`（合并后规则文件字节）、atlas/prompt-os 提交号  

**待技术确认**：hash 是对 profile 原文、合并后 rules，还是二者都要；prompt-os CLI 回执字段名。

## 5. 体系层与按书词表（设计方向，**未实现**）
- `system_profile`：如 `gmzz-pathways` / `generic-xianxia` / `none`——**名字与词表内容均未落地**，不得写进代码假装已有。
- `lexicon_ref`：按书超凡词；`off` 时不启用超凡层，日常技能仍可按非超凡词保留（技能/能力命名 **待用户或技术另定**，本草案不 freeze）。
- 语境误报边界见既有答复文档；词面命中 ≠ 能力事实。

## 6. earliest_plus_latest 细节（整合建议 → 待 atlas 技术确认）
用户已批策略名与「不凑数」；下列切分规则为**建议**，实现前两边确认，不升格为已批公式：
1. 对每类证据列表（截断前）与对齐的 `evidence_chapters` 同步取样。
2. 奇数 N：建议 `ceil(N/2)` 取最早、`floor(N/2)` 取最晚（或反之，确认时钉死一种）。
3. 去重：同一句（或同章同文）被早晚两边选中时只保留一条，**不因此补抽**凑满 N。
4. 列表长度 ≤ N：原样全留，不补齐。
5. 空类：输出空，不造句。

## 7. schema
- 短期：**不必**改 staging-card / atlas-export schema；profile 为胶水侧文件。
- 若以后要校验 profile：另增可选 schema，与本草案同步；**本回合不做**。

## 8. 明确未批准 / 非本接口范围
- `spread` 作全局默认；按 mentions/章数**自动调 N** 的公式。
- 体系词表内容、技能 vs 能力字段最终命名。
- UI/业务代码实现。
