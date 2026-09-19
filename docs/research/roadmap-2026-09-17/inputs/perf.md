# 性能热点侦察输入（roadmap-2026-09-17）

> 只读侦察，2026-09-17。数据源：`bench/results/stagerun-loop1-2026-09-16/records/*.jsonl`（63,316 行、~5043 ids、corpus_v3 全层、mock n≈11.6k + real n=48 双 xlat 臂）+ `bench/results/realn200-2026-09-17/records.jsonl`（200 ids e2e 实网关）。`dur_s` 为行级 `time.monotonic()` 墙钟；行内 `metrics.*.seconds` 分引擎/管线内耗时与 harness 外耗。

## 1. 头条口径修正：xlat `dur_s` 是排队等待不是功

`stage_xlat.py:186` 的 `t0` 打在 `async with paper_sem`（`:188`，jobs=8 跨 ~5k 篇）**之前**——xlat `dur_s` ≈ 99.6% 跨论文排队等待（mock 臂 dur 合计 7,143,562s vs inner 26,235s；dur 与 chunks/src_chars/files/inner 相关 ≈ 0.0，0–1900s 均匀排队分布）。compile/fixloop/parse 走 `ThreadPoolExecutor`，dur_s 是净功。**在 t0 挪进 sem（~1 行）或加 `queue_wait_s` 字段前，任何用 xlat dur_s 算的 stage 占比都不可信**——本条同时是热点 #4（度量件自身缺陷）。

## 2. 真实功占比（排队修正后）

| stage   | 真实功                                                                              | 单位量                                          | 注                                                 |
| ------- | ----------------------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------- |
| xlat    | real 臂 ~24s/id inner；realn200 e2e 中位 77.7s、均值 111s = **单篇 e2e 墙钟 96.8%** | ~15.5s 有效网关延迟/次                          | mock 臂 inner 2.3s/id 证机制本身便宜               |
| fixloop | 97,946s / 7004 行 ≈ 14s/行（中位 9.1，p90 23.6）                                    | 4.55s/round × 均 2.09 rounds + 复核编译         | 69% 引擎墙 + 31% post-verify 编译 + ~1% 外层       |
| compile | 77,054s / 5043 ids ≈ 15.3s/id                                                       | 3.17 引擎调用/id、5.84 passes/id、4.58s 引擎/次 | 行 dur 的 94.7% 是 xelatex 本体；85% 行跑 2 passes |
| parse   | 32,823s / 15,779 ≈ 2.1s（中位 0.85）                                                | —                                               | 小头                                               |
| ingest  | ~0.5s                                                                               | —                                               | 可忽略                                             |

## 3. Top-5 热点

1. **网关翻译延迟 ≈ e2e 墙钟 97%**——分解为 `ceil(batches/concurrency) × ~15.5s`；realn200 中位 97.5 chunks → 49 batches，attempts/chunks 仅 1.013（重试非罪魁，裸延迟是）。**server 任务跑 concurrency=3**（`worker/translate.py:120`）而管线 `DEFAULT_CONCURRENCY=10`（`pipeline.py:66`）：49-batch 论文 server 侧 ≈ 17 波 ≈ 260s vs 10 并发 ≈ 5 波 ≈ 78s。杠杆：server 默认 3→10（多 batch 论文估 ~3×）、`batch_max_chars` 上调（调用数减）、供应商延迟。
2. **xelatex 调用体量**——compile stage 引擎 72,989s / 15,948 次；85% 行吃 2 passes（TOC/refs 二遍）；fixloop 每行再补 ~~4.3s post-verify 编译（合计 30,045s）实质重跑一遍引擎刚跑过的编译。杠杆：无 ref/toc delta 时单遍跳过；fix-end verdict 已 clean 时去重 post-verify；估 fail-path 群 −40~~50% 引擎秒。
3. **fixloop 引擎墙**——67,121s、4.55s/round × 均 2.09 rounds；`unfixable:*` 行（437）仍烧完 rounds 才宣判。杠杆：已知不可修签名前置 category 预判跳轮。
4. **xlat dur_s 度量件伪影**（§1）——堵住诚实 stage 核算；修 = t0 挪进 sem 或记 `queue_wait_s`。
5. **重复 scan + O(n²) 状态写**——`_translate_tree` 每臂重跑 `e2e._scan_tree`（parse.json 已存在，xlat 重分整树，在未计时外区）；`StateStore.save_every=1`（`state.py:169-176`）每 chunk 重写整份 state.json（自注 O(n²)），`save_cache` 同模式按文件重写。有界未测；估秒级/篇非分钟级。

## 4. 并行余量

stagerun 按设计 stage-barrier（度量隔离）；server worker 单任务端到端串行——**多任务 worker 池是吞吐量最平杠杆**。单篇内 xlat 已并行（queue workers）；compile/fixloop 每 id 本质串行。

## 5. Caveats

- `translate.seconds` 只罩 `pipe.run`；外层（scan/copytree/reconstruct/write）未计时但被 corr≈0 限界（stagerun 内由排队主导）。
- `translate_s` 内网关上游延迟无 per-call 计时字段，不可再分。
- realn200 为 n=200 最新语料；loop1 mock 臂 ≈ 语料规模压力形态，非真实延迟。
- `post` metrics 行 6981 vs 实行 6822——少数行缺 metrics；合计只取 `fixloop_wall_s` 在场行（n=7004）。
