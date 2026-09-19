# bench 账本归档 — 2026-09-20

大清理第一步：`bench/results/` 的**账本层**完整镜像（不含 `work/` 现场树）。598M / 460 项。

## 内容

- `results/` — `rsync -a --exclude=work/` 镜像：每个 run 的 `records/`（判定账本）、`cases.jsonl`、`run_meta.json`、`summary.md`、`papers|cells|files.json`；评测器三件套目录整体保留；75 个顶层报告 `.md`；`nightwatch/` 快照。
- `sig-attributions.txt` — 656 个唯一失败签名 → 归属面（rules/mechanisms/fixtures/tests）映射，蒸馏审计产出。**结论：24 个 stagerun 全部榨干，唯一未归属记录是 flipcheck4 的 1 条 `no_item`（无机制价值）**。
- `doc-keep-list.txt` — `docs/` 引用计数降序的 results 目录名单；被引目录是史料锚点。

## 里程碑指针

`docs/research/metrics-2026-09-19/` 已是成稿的指标史：`data/milestones.md`（D0-D2+ 时间线）、`refs/00-grand-comparison.md`、完整 LaTeX 报告。本归档是它的数据底座备份。

## 审计结论（2026-09-20 三路审计）

1. **蒸馏覆盖**：所有 run 的失败签名 100% 归属——删树不丢机制证据。
2. **文档归属**：~280 个一次性 probe/smoke/scout 目录零文档引用（合计 <0.5G）；基线目录全部在 keep 名单。
3. **活 fence**：`sab-r*`/`flipcheck*` 迭代波不在 results/（是 `tmp/lane-*` 现场）；flipcheck10 波在飞期间所有 run 的 `zh/`/`splice/` 是潜在 replay donor。

## work/ 树去向

树本体留在 `bench/results/*/work/`：real 臂 `zh/`（付费译文，swe-2 promo 2026-10-16 到期前不可再生）与 `splice/`（时间点产物 + replay donor）按「分级删」决议全保留；mock 臂 `zh/` 待 flipcheck10 收官后删除（确定性可重建 + 蒸馏已榨干）；`src/`/`_texmf/`/`build-base/` 已于 2026-09-19 A 档删除 17.15G。
