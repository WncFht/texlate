# corpus_m1k — 1000 篇全流程评测语料（实到 997）

最严全流程测试专用语料：4 个 strata 共 997 篇（目标 1000，3 篇 axhot 系 arXiv 真无源码 pdf_only），走 `TEXLATE_CORPUS=bench/corpus_m1k` 供 stagerun 全链（ingest→parse→xlat→compile→fixloop）消费。构建脚本 `bench/py/corpus/build_corpus_m1k.py`（select→materialize→emit 三子命令），选样与现场在 `bench/work_m1k/`（selection.jsonl / fetch.jsonl / report.md / run.log），seed=42。

## 层构成（manifest_{layer}.jsonl）

| 层       | n   | 来源                                                                                                                                                                                         | 物化方式                                                            |
| -------- | --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `recent` | 300 | `corpus_daily` 2026-09-18 层 `announce_type∈{new,cross}` 已物化池（最新公告日批次，周末 feed 冻结前最后一天）                                                                                | copytree                                                            |
| `axhot`  | 247 | alphaXiv `/papers/v3/feed`：Hot/90d+Hot/30d+Views/All+Likes/All 四榜按最佳榜位排序，`pdf_only=false` 预筛、arXiv id 形校验（feed 混入过 `2609.good-healthspan-practice-n-of-1` 类自有 slug）；3 篇选后实抓仍 pdf_only（2409.11686/2504.00698/2505.10468） | 本地已有则 copy（47 篇命中 corpus_daily），否则 `acquire_source` 抓 |
| `iclr`   | 200 | `work_iclr/map.jsonl` 5296 个已映射 arXiv id，年份加权（2024:80/2023:50/2022:35/2021:20/≤2020:15）                                                                                           | 同上（几乎全需抓；1 篇 cache_hit 命中本地源缓存直拷）                                                  |
| `v3`     | 250 | `corpus_v3` dev 层（core/booster/dev_vol/dev_failmine/dev_recent/expand/hot；**排除 holdout**——评测贞操层不烧在 QA 跑上）                                                                    | copytree                                                            |

## 规则

- 取数顺序 recent→axhot→iclr→v3，逐层对已选集去重；manifest 行带 `id/layer/cat_group/src/title`（cat_group 走 arXiv API 批量补全，喂 stagerun 术语表 cat_map）。
- 老 id（`cat/NNNNNNN`）按嵌套目录存（`corpus_m1k/hep-th/0103037/`），新 id 平铺——同 corpus_v3/daily 惯例。
- 每篇目录 = `{meta.json, raw.*, extracted/, files.txt, mtree.txt}`，acquire_source 钉版产物。
- 语料数据目录 gitignored；manifest_* + 本文件入库。
