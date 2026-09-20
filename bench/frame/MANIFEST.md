# bench/frame/ — 语料抽样框资产清单

全 arXiv universe 分层抽样框：v3 系 corpus builder 的采样宇宙 + parsebench 分层权重输入。数据 gitignored（派生探测产物），本清单入库。

## 数据源与版本

- 上游：HF `librarian-bots/arxiv-metadata-snapshot`（CC0，日更 parquet，10 shards）——上游仓库保留 git 历史，旧 revision 可按 sha 找回
- 本快照：上游 lastModified **2026-09-14**，拉取 ~2026-09-15，覆盖至 tar_yymm=2609（当月部分量 ~11.9k 行）
- 构建口径：`docs/research/corpus/frame-and-allocation.md`（30 月簇 + 年代带配额论证）；IA/TIGER 索引件另记

## 内容

| 文件                                                                                                                                                                                               | 说明                                                                                                        |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `frame.parquet`                                                                                                                                                                                    | 主资产：3,164,528 行 × 14 列派生 frame（schema：`docs/spec/corpus.md` §4；新式 id 覆盖 99.9994%）           |
| `frame_raw.parquet`                                                                                                                                                                                | 原始快照 10 列（id/id_style/v1_ts/categories/license_uri/n_versions/update_date 等），派生输入即 provenance |
| `item-index.csv`                                                                                                                                                                                   | IA arxiv-bulk item 索引（09-19 重建）                                                                       |
| `tiger-files.csv`                                                                                                                                                                                  | HF TIGER-Lab/arxiv-latex-5T 文件索引                                                                        |
| `cluster_pick.json` / `cluster-cat-mix.csv` / `allocation-{core,booster}.csv` / `strata-{era-cat,license}.csv` / `counts_by_yymm.csv` / `coverage_newstyle.csv` / `{ia,tiger}_chunks_by_yymm.json` | 分层/簇/配额/覆盖率规划件                                                                                   |

## 消费者

- `bench/py/corpus/build_corpus_v3.py`（frame-lookup 子命令读 frame.parquet）与 expand/hot 层 builder
- `bench/py/parsebench.py`（strata-era-cat.csv 分层权重）

## 刷新口径

抽样框要的是覆盖完备性不是实时性：当前快照 ~5 日龄，对选样无影响。**下次扩语料前重拉上游快照重建即可**（此时把新 lastModified 记回本文件）；scale-roadmap 提议的 OAI-PMH 日增量对账管线未建、按当前需求量级不需要——增量论文流由 `daily_arxiv.py`/soak 语料独立承担。
