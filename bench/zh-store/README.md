# zh-store — 付费译文资产库

2026-09-20 大清理产物：`bench/results/` 全部旧 run 中 **arm=="real"** 的 `work/{id}/{zh,splice}` 按 canon id 归并提取至此。**这是唯一不可再生资产**——swe-2 promo 2026-10-16 到期后同等译文同价买不回。

## 结构

- `{canon_id}/zh/` — LLM 译文树（段落级中文 .tex + 结构件），内含 `.xlat-arm.json` 臂标记
- `{canon_id}/splice/` — 中文成品树（最终 `<main>.pdf` + `.fixloop-entry.pdf` 快照 + fixloop 修复现场 + 编译 log）
- `{canon_id}/provenance.json` — `{id, source_run, arm, moved_at}`
- `_alt/{canon_id}/{run}/` — 30 个 id 被两个 run 重复翻译的落选副本（正主按 run 优先级 m1k>rt1>smoke>soak 选出）

## 规模

2247 个唯一 id（+30 重译副本）/ 26.1G。来源：`stagerun-m1k-2026-09-19`（995）、`stagerun-rt1`（1277）、`stagerun-m1k-smoke`（5）。`soak-2026-09-18` 的 9 个 real 格因活工单（tickets.jsonl repro_path）暂留原 run，工单结清后补提。

## 消费约定

- 要中文译文文本 → `zh/`；要成品双语 PDF → `splice/<main>.pdf`
- replay/修复播种 → 整 `{id}/` 拷回 `work/{id}/` 即可续跑 compile+fixloop
- 语料原件 → `bench/corpus/{canon_id}/`（统一物理根）
