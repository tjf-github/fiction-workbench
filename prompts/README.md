# 建卡提示词产物目录（`prompts/`）

集中存放由 `tools/card_pipeline/pipeline/run_pipeline.py` 生成的 W2 建卡提示词产物，方便直接打开复制给 **grokbot** 等大吞吐模型成卡。

## 命名规则

- 单角色抽取：`<书名>-<角色名>-<run_id>.md`（如 `诡秘之主-辛西娅-gmzz-cynthia-001.md`）
- 多角色批量抽取：`<书名>-<N>人-<run_id>.md`

## 注意事项

- 本目录下的提示词是 `tools/card_pipeline/staging/<run_id>/prompt.md` 的便于查阅副本；`import-result` 仍按 `--run-id` 对应 `staging/<run_id>/` 执行逐字校验。
- 提示词内包含原著逐字证据句，请勿对外公开分享。
