# B7 门全量复跑（post THEOREM_ANCHOR_SHIM, 0888962）

2026-09-16 · 任务 #49 · 产出 `bench/results/alignbench-post-shim-2026-09-16/`

## 结论

**B7 门绿**。`--check` 退出码 0，三项门全过：no_pair_errors ✅ / hyperref_retention(≥0.95) ✅ / degraded_path_ok ✅。488 对中 487 对与基线逐字节一致，唯一变化对 2410.17902 由 low(0.750) → ok(1.000)，无任何退化对。

## 方法

基线取最近的 `b7-pipefix-2026-09-16`（488 对：en=base-xel/base-rescue，zh=pipe-fix∪pipe-xel union 口径，records=`e2e-real-n100-postcutover-2026-09-16/results.json`）。复跑方式：从基线 `pairs.jsonl` 逐行还原 pair 清单为 manifest（冻结 pair 集防 drift，已验证基线后 `bench/work_e2ereal` 内 0 个 PDF 变动），走 `--pairs` 模式重分析。唯一替换：2410.17902 的 b 侧由 pre-shim `pipe-xel/…/exceptional.pdf` 换为 post-shim 重编产物 `tmp/exp/b7-241017902-ctex/zh_rerun/exceptional.pdf`（ctex-anchor 现场，`prepare_chinese` 真路径 ctex+shim 注入后 xelatex×3）。

复跑命令：

```text
uv run --with pypdf python bench/py/alignbench.py \
  --pairs bench/results/alignbench-post-shim-2026-09-16/manifest.jsonl \
  --out bench/results/alignbench-post-shim-2026-09-16 --check
```

## 聚合对照

| 指标 | 基线 b7-pipefix | post-shim |
|---|---|---|
| pairs | 488 | 488（id 集同一） |
| hyperref / degraded / invalid / error | 35 / 450 / 3 / 0 | 35 / 450 / 3 / 0 |
| low | 1（2410.17902） | **0** |
| retention min / p50 / mean | 0.750 / 1.0 / 0.9918 | **0.962 / 1.0 / 0.9989** |
| gates_pass | false | **true** |

## 逐对 diff（488 对全量比对）

仅 1 对变化，487 对 verdict/retention/common/dests 全同——shim 未掰坏任何既有对：

| pair | verdict | ret | common | dests a→b |
|---|---|---|---|---|
| 2410.17902 | low → **ok** | 0.750 → **1.000** | 39 → 52 | 52 → 65（+13 孪生 dest） |

3 个 invalid_pdf 对与基线完全相同（`1206.5921:figure1`、`1404.2164`、`1404.5720`，均 side=a 的编译截断 stub，B3/B5 已计 FAIL，不占 B7 门）。

## 现行 retention 地板

`2203.13039` ret=0.9623（51/53，arm=pipe-xel，zh_v=clean），与基线同值。丢的 `lemma.3.1`/`remark.1.2` 对应 zh 侧多出 `theorem.3.1`/`theorem.1.2`——与 2410.17902 同族共享计数器签名（env 名 ↔ 根计数器名分叉），其 zh PDF 为 pre-shim 产物；shim 重编后大概率同样补到 1.0。已在 0.95 门之上，不阻塞。

## 口径边界

- 487 对的 zh PDF 是 pre-shim 产物（输入未变，不可能被 shim 掰坏），本次「无退化」由构造保证 + shim 纯增量孪生设计（ctex-anchor 报告 L1/L2 已验）互证。
- 更强的「全量 zh post-shim 重编」复跑未做：需对 ~100 id 走 prepare_chinese+xelatex 全链（小时级）。若 leader 要这版，2410.17902 与 2203.13039 是仅有的预期变化点（均向上）。
- 2410.17902 行 meta 带 `b_variant="post-shim zh_rerun"` 标注，attribution.jsonl 可溯源。

## 文件

- `bench/results/alignbench-post-shim-2026-09-16/`：manifest.jsonl（488 对冻结清单）、pairs.jsonl、cells.json、attribution.jsonl、summary.md
- 基线：`bench/results/b7-pipefix-2026-09-16/`
- post-shim zh 产物：`tmp/exp/b7-241017902-ctex/zh_rerun/exceptional.pdf`（gitignored scratch）
