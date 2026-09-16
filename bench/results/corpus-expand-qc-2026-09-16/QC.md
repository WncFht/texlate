# corpus expand 层 QC（2026-09-16）

对象：`bench/corpus_v3/manifest_expand.jsonl`（corpus-expand agent 运行 `bench/py/build_corpus_expand.py` 产出，13:22 完成）。独立 QC，未改动任何产物。

## 结论

**总收 3800 篇 / 计划 3740（+60），QC 全项通过；唯一偏差：`a_pre2007|astro-ph` 超配 +60（实测 216 vs 配额 156），来源已定位为当日 12:56 smoke-test 批次残留（60 条记录时间戳 12:56:01–08），全部为唯一 id、完整物化、sha 校验通过，属良性超收但冻结分布有偏。**

## 逐项结果

| 检查项 | 结果 |
| --- | --- |
| a) 行数 / schema / layer | 3800 行；19 字段全一致；`layer=expand` 100%。schema = booster 减 `mech_tags` 加 `pool`（层语义差异，合理） |
| b) 物化完整性 | 3800/3800 有 `{id}/` + `meta.json` + `raw.*` + `extracted/` 非空；**全部含 ≥1 .tex**（大小写不敏感；4 篇为 `.TEX`） |
| c) 与存量 manifest 去重 | 与 core(1000)/booster(200)/hot(72) **0 重叠**；expand 内部 **0 重复 id** |
| d) blob_sha256 抽查 | 计划抽 50 → 实际**全量 3800 通过**：`sha256(raw.*)` == `blob_sha256`、`bytes` == 文件大小、`meta.raw_sha256` 一致；另抽 50 验 `main_tex_sha256` ∈ extracted tex 哈希，全中 |
| e) stratum_cell 分布 vs `expand_plan.json` | 39/40 cell 精确命中配额；唯一偏差 `a_pre2007|astro-ph` 216 vs 156（+60，见下） |
| f) format==stub 占比 | **0**（tar 3076 / gz 724）；无 withdrawn 物化行 |

## +60 超收定位

`extract_records.jsonl`（3800 条，state 全 ok）中恰有 60 条 `ts < 13:07:18`（extract 阶段起点）：全部 `a_pre2007|astro-ph`，pool 拆 old=47/new=13，item 跨 8 个（0501/0605/0307/9910/0111/9703/9901/0408）。这是 task#2 smoke test 批次的落盘记录被 append 模式（`build_corpus_expand.py:15` "逐行 append, id 幂等"）带入最终 manifest。select 阶段 `existing_ids()` 只排除 core/booster/hot（`build_corpus_expand.py:106-107`），不排除已物化的 expand id——但本轮 3740 picks 与 smoke 60 无 id 碰撞，故无重复行。

影响：实收分布 astro-ph×pre2007 偏重（+38% cell 超配），其余 39 cell 精确。对"求全"目标无害；若后续按 manifest 行数做分层统计需注意该 cell 口径。

## 附加一致性检查（全过）

- `band ↔ yymm`：3800/3800 一致（如 0501→a_pre2007）
- `cluster_id`：同 yymm 全库一致
- `archive`：null 恰好 = era=new 的 2939 行，与 core/booster/hot 既有约定一致（new era 行一律 null）
- `main_tex_sha256` null = 842：全部 724 个 gz（单文件 blob 即 tex）+ 118 个多 tex tar 未识别主文件，与 booster 约定一致
- `n_files`/`n_tex` vs 实际 extracted（递归计数）：200 抽样 0 失配
- `license_class`：arxiv-nonexclusive 2456 / missing 916 / cc-by 298 / 其他 130
- pool：old 1172 / new 2628（= select 1125+2615 + smoke 47+13，账平）

## 不合格清单

无硬不合格项。记录偏差一项：`a_pre2007|astro-ph` +60 超配（良性，建议要么接受为扩收、要么在下游统计时按 quota 截断到 156）。
