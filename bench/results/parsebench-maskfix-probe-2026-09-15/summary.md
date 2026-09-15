# parsebench summary — corpus_v3

- papers: 2   files (.tex): 3   wall: 0.5s
- parse ok: **3/3** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **3** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **0/88** chunks = 0.00%   hits={}
- chunk chars: median 229.0   p90 763
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- flatten coverage: 3 reached / 0 orphan tex / 0 rootless   (触及率 100.0%)

## funnel

| stage | n |
|---|---|
| fetched (manifest rows) | 1000 |
| source ok | 1000 |
| papers discovered | 2 |
| .tex files | 3 |
| rooted papers | 2 (multi_doc 0, rootless 0) |
| parse ok | 3 |
| identity | strict 3 / normalized 0 / diverged 0 |
| translatable chunks | 88 |
| leaked chunks | 0 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 3 / 0 / 0 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [43.85, 100.00] | 100% & Wilson lb ≥99.5% | PASS(low-n) |
| strict identity | 100.00% CI [43.85, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.000% CI [0.000, 4.183] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 100.0% (3/3) | ≥99% † | PASS |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## v1 vs v2 — segmenter.parse_tex_v2

| 指标 | v1 (scanner) | v2 (segmenter) |
|---|---|---|
| parse ok | 3/3 | 3/3 |
| identity strict/normalized/diverged | 3/0/0 | 3/0/0 |
| translatable chunks | 88 | 23 |
| leaked chunks | 0 | 0 |
| Σ chunks | 88 | 23 |
| Σ placeholders | 462 | 344 |
| wall ms p50 / p95 | 7 / 8 | 4 / 37 |
| vtex_vs_src 展开足迹 | — | strict 3 / normalized 0 / diverged 0 |

### v1↔v2 差异文件 (2/3)

| file | v1 id | v2 id | chunks | leaked | ms | vtex_vs_src | flags |
|---|---|---|---|---|---|---|---|
| astro-ph/0111094/extracted/pbar.tex | strict | strict | 27→23 | 0→0 | 8.4→36.9 | strict | chunks |
| quant-ph/0111094/extracted/interfr1.tex | strict | strict | 61→0 | 0→0 | 7.4→4.1 | strict | chunks |

## 统计口径 (docs/09 §7.2)

- 权重: post-strat w=N_cell/n_cell (核心层), 2/2 篇有权; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (3/3) | 100.000% | 100.000% | [43.850, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (3/3) | 100.000% | 100.000% | [43.850, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.000% (0/88) | 0.000% | 0.000% | [0.000, 4.183] | [0.000, 0.000] |
| flatten coverage | 100.00% (3/3) | 100.00% | 100.00% | — | [100.00, 100.00] |

## per-paper

| paper | class | options | roots | tags | tex | ok | strict | leak% | orphan-tex |
|---|---|---|---|---|---|---|---|---|---|
| astro-ph/0111094 | revtex4 | twocolumn,showpacs,superscriptaddress,prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0111094 | article | 12pt | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| article | 1 | 2 | 100.0 | 100.0 | 0.00 |
| revtex4 | 1 | 1 | 100.0 | 100.0 | 0.00 |

## by era

| era | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| old | 2 | 3 | 100.0 | 100.0 | 0.00 |

## by archive

| archive | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| astro-ph | 1 | 1 | 100.0 | 100.0 | 0.00 |
| quant-ph | 1 | 2 | 100.0 | 100.0 | 0.00 |

## by stratum_cell

| stratum_cell | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| a_pre2007|astro-ph | 1 | 1 | 100.0 | 100.0 | 0.00 |
| a_pre2007|quant-ph | 1 | 2 | 100.0 | 100.0 | 0.00 |

## by cluster_id

| cluster_id | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| C03 | 2 | 3 | 100.0 | 100.0 | 0.00 |

## by layer

| layer | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| core | 2 | 3 | 100.0 | 100.0 | 0.00 |
