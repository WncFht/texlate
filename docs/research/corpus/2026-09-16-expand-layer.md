# corpus_v3 expand 层（+3,800 篇）落地记录

> **结论**：corpus_v3 在核心 1,000 + 补强 200 + hot 之外新增 **expand 层 3,800 篇**——规模轴定位：把底材推到 ~5,000 量级喂 stagerun 批量回路（triage 聚类需要失败样本量），抽样框沿用 30 簇 + 渠道钉版，但**不进池化估计**（配额按故障率加权而非均匀，属定向扩容）。QC 独立复核全过（0 重叠、sha256 全量校验通过、39/40 cell 精确命中）。
> **状态**：时点证据（2026-09-16 落地口径；expand 后续增至 3,866，现行八层 13,266 口径见 `bench/corpus/MANIFEST.md`）。
> **日期**：2026-09-16

## 定位

核心层回答「成功率多少」（配额随机、可池化），补强层回答「坑处理了吗」（agent 策展），hot 层回答「真实用户负载」（高引近期）。expand 层是**规模轴**：把底材推到 ~5,000 量级喂 stagerun 批量回路（triage 聚类需要失败样本量），抽样框仍是 corpus_v3 的 30 簇 + 渠道钉版，但**不进池化估计**——配额按 n100 故障率加权而非均匀，属定向扩容。

## 配额与选样

`plan` 阶段读三份既有 manifest 算 stratum_cell 分布 → 以 e2e-real n100 故障率加权（`w = n_cell × (1 + λ·((rel_band+rel_cat)/2 −1))`——失败率高的带×类目 cell 配额上调）定 3,740 配额 → 簇月优先、月内低 chunk、跨月 round-robin 摊月份。新旧两池：已扫未选的 ~41.5k 合格成员（旧池，本地 tar 随机读零带宽）默认三成复用，七成走 Range-GET 取新月份成员（e 带 2021+ IA 无索引走 tiger channel）。`extract` 逐行 append manifest、id 幂等、`extract_records.jsonl` 记账。

## QC 结论（独立复核，全过）

- 3,800/3,800 物化完整（meta.json + raw.* + extracted 非空、≥1 .tex）；与 core/booster/hot **0 重叠**、内部 0 重复；blob_sha256 全量校验通过。
- 39/40 cell 精确命中配额；唯一偏差 `a_pre2007|astro-ph` 216 vs 156（**+60 良性超收**——来源已定位为当日 smoke-test 批次 append 残留，全部唯一 id 且校验通过；下游按行数做分层统计时注意该 cell 口径）。
- schema = booster 加 `pool`（落地时点差为 −mech_tags +pool；`mech_tags` 已于 2026-09-18 全层回填，3,866 行均带键、2,264 非空——commit 9f378696）；format=stub 0；band↔yymm、cluster_id、archive-null 约定与存量层一致。

## 运维教训

`extract_records.jsonl` append 语义会把冒烟残留带进正式 manifest——扩库/批跑前清场或用独立 `--dir`；select 的 `existing_ids()` 只排除 core/booster/hot，不排除已物化 expand id（本轮无碰撞故无重复）。（2026-09-19 已修复：`existing_ids()` 改走 `benchlib.corpus_ids` 全层并集，新层入库自动入排除集——build_corpus_expand.py:157 / benchlib.py:424，commit b3365fc8）
