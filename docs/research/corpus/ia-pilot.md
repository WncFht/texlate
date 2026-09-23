# IA arxiv-bulk → 语料管线 pilot（实测）

> **结论**：管线完全可行且廉价——索引 3,242 个 src item / 352 个月 1991-07→2020-10 无缺；整 tar 下载 ~11MB/s；单遍流式扫描即得成员清单+逐成员特征（~150-290 成员/s）；成员名无版本号但 id 与月强绑定（实测零跨月重叠）；`zipsum.tsv` 成员序 == tar 序，offset 可纯算术重建，单成员 Range 抽取与本地解包逐字节一致；48 篇抽样语料 parsebench 全绿（79/79 ok，100% identical）。
> **状态**：已完成（一次性 pilot，2026-09-14 执行；全部结论已并入 v3-plan/frame-and-allocation 并驱动实际构建）。开发机现场产物（`tmp/exp/ia-pilot/`）不在公开库，结论已摘要进本文。
> **日期**：2026-09-14

验证链路：Internet Archive `arxiv-bulk` 集合 → 月度 src tar → 成员 e-print → 特征/抽样 → corpus 目录 → parsebench。总下载 ~1.17GB（3 个整 tar 984MB + Range walk 189MB + zipsum/探针 ~100MB）。数据来源只有 `archive.org`（advancedsearch / metadata / download，全部匿名无凭据）。

## 1. Item 索引（advancedsearch）

`GET https://archive.org/advancedsearch.php?q=collection:arxiv-bulk&fl[]=identifier&fl[]=item_size&fl[]=date&rows=8000&output=json`

- numFound **6,767**（src+pdf 混合）；正则 `arXiv_src_(\d{4})_(\d{3})` 滤出 **3,242 个 src item**。
- `fl[]=item_size` 有效；`fl[]=date` 返回空（item 未设 date 元数据）。
- 覆盖 **352 个月，1991-07 → 2020-10 逐月无缺**（脚本验证 gap 列表为空）。总 src 体量 **1,655.85GB**；item 中位 528MB，最大 2.1GB（arXiv_src_2007_xxx 区间），最小 0.1MB。
- 单月 chunk 数随年代暴涨：1998-2001 每月 **1 chunk**（130-360MB）；2012-2014 每月 9-21 chunk（4.4-11.9GB/月）；2019-2020 每月 33-92 chunk（17-55GB/月，2010=92 chunks/55GB）。

## 2. Pilot 三个月份

| era      | 月份    | item                                         | 大小  | 处理                                  |
| -------- | ------- | -------------------------------------------- | ----- | ------------------------------------- |
| 旧式 ID  | 1998-02 | `arXiv_src_9802_001`（全月唯一 chunk）       | 130MB | **整下**，urllib 12.2s = **10.7MB/s** |
| 中期     | 2012-01 | `arXiv_src_1201_001`（当月 9 chunk 之一）    | 543MB | 整下（curl -L，与下个合计 ~50s）      |
| 冻结前夕 | 2020-01 | `arXiv_src_2001_040`（当月 40 chunk 之尾块） | 311MB | 整下 + 另做 Range 头扫描验证          |

注：中期/晚期「整月」已不现实（4-55GB），单位下载天然是 chunk；chunk 内成员全部带该月 yymm 前缀，取一块即得该月真实成员子集。补充实测 bulk 吞吐：对 `arXiv_src_1901_001` 做 100MB Range GET = **12.4MB/s**。bulk 下载速率口径 **~11MB/s**。

## 3. 成员清单 + 三态格式

单遍 `tarfile` `r|` 流式扫，同时产出成员清单（name/size/offset）与逐成员特征 jsonl。

| chunk    | 成员数    | 耗时          | tar.gz        | 单 .gz      | PDF-only  | 成员大小 med / p90 / max |
| -------- | --------- | ------------- | ------------- | ----------- | --------- | ------------------------ |
| 9802_001 | **1,668** | 5.8s（286/s） | 1,123 (67.3%) | 541 (32.4%) | 4 (0.2%)  | 32K / 202K / 969K        |
| 1201_001 | **881**   | 5.0s（176/s） | 580 (65.8%)   | 216 (24.5%) | 85 (9.6%) | 130K / 1.5M / 11.9M      |
| 2001_040 | **214**   | 2.1s（102/s） | 163 (76.2%)   | 33 (15.4%)  | 18 (8.4%) | 419K / 4.5M / 11.7M      |

成员命名逐字：`9802/adap-org9802001.gz`、`9802/astro-ph9802001.gz`、`1201/1201.0610.gz`、`1201/1201.0235.pdf`、`2001/2001.11958.gz`——即 `{chunk_yymm}/{id}.{gz|pdf}`：旧式 id 把 archive 与编号连写（`astro-ph9802001` → `astro-ph/9802001`），新式即 `1201.0610`。顶层有 1 个 `{yymm}/` 目录项（typeflag 5）。

- **版本号不可得**：3 个 tar 共 2,763 成员，**无一**成员名带 `vN`；item 元数据亦无版本字段。publicdate 显示 tar 由 arXiv 在提交月之后数月构建（2001 月的块 2020-07 上传；≤2017 的块集中在 2017-09 批量上传）⇒ 成员 blob ≈「构建时点的 e-print 状态」，非钉版 v1。语料侧记 `resolved_version=null` + sha256。
- **跨月 id 重叠 = 0**（实测两两交集均空）；且三个 chunk 中**每个成员 id 内嵌的 yymm 都等于 chunk 月**——月度 chunk 只收当月新提交，换版不进 src 月块（本样本 2,763 成员无一例外）⇒ 按 id 去重在月块层面天然成立。

## 4. 逐成员特征

单遍解 blob：魔数三态（`%PDF` / `\x1f\x8b`+ustar-or-cksum / 其他）、gunzip、内层 tar 遍历、文本文件（tex/sty/cls/bbl 等）strict-UTF-8 探测、docclass 正则（剥注释）、`\input/\include` 引用链最长深度（环安全 BFS）、7 项用途 flag。

| chunk    | docclass top                                                    | documentstyle   | non-utf8  | flag 要点                                         | input 深度分布                                     |
| -------- | --------------------------------------------------------------- | --------------- | --------- | ------------------------------------------------- | -------------------------------------------------- |
| 9802     | article 779 · revtex 496 · mn 35 · amsart 35                    | **1,357 (81%)** | 52 (3.1%) | amsmath 1,178 · epsfig 193                        | 0:1634 · 1:27 · 2:2 · **32:1（循环 \input 触顶）** |
| 1201_001 | article 221 · revtex4* 192 · amsart 122 · IEEEtran 25 · mn2e 22 | 6               | 159 (18%) | amsmath 674 · epsfig 326 · hyperref 130 · tikz 24 | 0:745 · 1:44 · 2:6 · 3:1                           |
| 2001_040 | article 62 · amsart 31 · IEEEtran 23 · revtex4-1 18             | 0               | 10 (4.7%) | amsmath 185 · hyperref 89 · **tikz 45**           | 0:167 · 1:28 · 3:1                                 |

提取全程：2,763 成员 / 12.9s ≈ **214 成员/s**（解压 + 内层 tar + 特征全开），零成员级异常。年代趋势清晰：`\documentstyle` 81%→0%、tikz 0→21%、hyperref 0→42%、PDF-only 0.2%→~9%。

## 5. Range 流式/单点抽取（关键实测）

- **窗口头扫描**（4MB 预取窗，越界按 size 跳 offset）：2001_040 全程 46 请求 / 189MB 拉取 / 166.8s → 成员清单与本地 tar **逐字节核验 214/214 全对**（name+size+offset）。结论：可行但受成员密度影响——大成员块窗口会吞数据体（本例拉了 61% 文件）。
- **512B/头极简 walk** 未全跑（单 Range 请求固定延迟 ~1.6s，215 成员串行 ~6min，字节量仅 ~110KB——延迟换字节）。
- **zipsum 捷径（本次最大发现）**：`{item}_zipsum.tsv`（sha1/sha256/md5/大小/成员名，~150-300KB/item）**成员顺序与 tar 完全一致**（9802: 1668/1668、1201_001: 881/881 逐序相同）；补 1 个顶层目录头偏移（512B）后**全体成员 data offset 纯算术重建、0 失配** ⇒ 不下 tar 也能得「名字 + 大小 + offset + 校验」全索引。但 **zipsum 并非每 item 必有**：9802/0506/1006/1201/1506/1806/2009/2010 有，1912/2001_001/2001_040 无（晚期不规律）。
- **单点 Range 抽取验证**：按 walk 所得 offset Range GET `2001/2001.11876.gz`（13,895B，2.1s）与本地 tar 解出的成员**逐字节一致**。
- curl 坑：`/download/` 会 302 到 `dn*.archive.org` 节点，必须 `-L`（`-sf` 不带 L 得到 0 字节空文件）。

## 6. 配额抽样 + parsebench

docclass 组（revtex/amsart/article/IEEEtran/llncs/astro/other）× 文件档（1 / 2-5 / >5）循环配额，seed=42。从 1201_001 抽 **40 篇**（19/21 格非空；`llncs×1` 与 `astro×1` 天然空格）+ 9802 老时代探针 **8 篇**（覆盖 documentstyle 拒绝路径）。组装为 corpus_v2 同款布局 `corpus/{id}/raw.*+extracted/+meta.json`（meta 增 `source:ia / ia_item / ia_member / features`；旧式 id 按 `archive/name` 嵌套）。产物 71MB / 79 个 .tex。

parsebench 结果（7.7s）：papers **48**，.tex **79**；parse ok **79/79 (100%)**；recon **identical 79 (100%)**；泄漏 **2/6,824 chunks (0.03%)**；fake-translation 死占位/孤儿 chunk 全 0。flatten 覆盖：56 reached / 22 orphan（全部来自 1201.0682，24 tex 的 llncs 会议稿，根只触 2 个）/ 1 rootless。路由标签生效：reject 5（9802 的 documentstyle）· xelatex 16 · non-utf8 7 · no-hyperref 43。

## 7. 规模推算（30 月度簇 × ~35 篇 ≈ 1,050 篇）

实测速率：bulk 下载 ~11MB/s；全成员扫 + 特征 ~150/s（保守）；parsebench ~10 .tex/s；Range 请求延迟 ~1.6s。

| 方案                               | 下载量                                               | 墙钟估算                                                                              | 磁盘峰值                            |
| ---------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------- |
| A. 每月整块（选最小 chunk ~450MB） | 30 × 450MB ≈ **13.5GB**                              | DL ~21min + 扫 ~24k 成员 ~3min + 组装 ~1min + bench ~4min ≈ **30min**                 | tar 13.5G + corpus ~2-3G ≈ **16GB** |
| B. zipsum+Range 精选               | 索引 ~6MB + 1,050 成员 × ~400KB ≈ **0.4-0.5GB**      | 索引 <1min + 串行 1,050×1.6s ≈ 28min（**8 路并发 ~4min**）+ bench 4min ≈ **10-33min** | <1GB                                |
| C. 混合（推荐）                    | 小月（≤2 chunk，≈2007 前基本全月单块）整下；大月走 B | ≈ 分钟级                                                                              | <2GB                                |

注意：2019-2020 月份整块采 35 篇若坚持「全月覆盖」需 17-55GB/月，**不可行**；要么接受单 chunk 子集，要么走方案 B。

## 8. 坑与建议

- **微成员 stub**：`1201/1201.0517.gz` 42B，解压出 12B `%auto-ignore`——arXiv 自动忽略占位，抽样须加最小尺寸或 docclass 门槛（本次它混进了样本，成了那篇 rootless）。
- 单 .gz 成员解压后偶为非 tex（PS/PDF），嗅探魔数再定扩展名。
- zipsum 晚期 item 不规律缺失；缺时退化到窗口头扫描或直接整下（~11MB/s 下 300-550MB 也就 30-50s，比串行 Range 更省时）。
- 9802 有 1 个循环 `\input` 成员把深度顶到上限 32——特征提取需环保护。
- item `date`/`publicdate` 不映射提交月，月归属只能信 identifier 的 YYMM。
- 本次 0 解压失败；但 tar.gz 无法随机读——若只要极少数成员，Range 抽取依赖 offset 索引（zipsum 重建或头扫描获得）。

## 9. 对 corpus_v3 管线的设计建议（已全部采纳）

1. **两级索引**：advancedsearch 一次建 item 索引（月→chunk→size）；成员级索引用 **zipsum 优先**（~200KB 得名字 + 大小 + offset + sha256；第 i 个成员的 data offset = `512·(i+2) + Σ_{j<i} ceil(size_j/512)·512`——1 个目录头 + 逐成员 512B 头 + 512 对齐数据体，已验证 2,549 成员 0 失配），缺失 item 再退化到头扫描。
2. **按月分层抽样走「zipsum 索引 → Range 精选」**：选定月份后先拉其全部 chunk 的 zipsum（几十 KB 级）做全月成员池，配额抽样后仅 Range 拉中选成员——晚期大月成本从几十 GB 降到几十 MB。
3. **去重键直接用成员路径 `{yymm}/{id}`**：实测月块内 id-yymm == chunk-yymm、跨月零重叠，无需额外版本维；meta 记 `resolved_version=null` + `raw_sha256` 即可。
4. **成员三态分流在扫描时一次完成**：`%PDF` 直接标 pdf_only 跳过抽样；`\x1f\x8b` 后 ustar/cksum 判内层 tar vs 单文件；加 `member_bytes < 100B` 或解压后 `%auto-ignore` 前缀的 stub 过滤。
5. **抽样池分层键**沿用本 pilot：`docclass 组（首 docclass 归一化）× n_total_files 档`，循环配额 + 固定 seed；老时代月必须保留——`\documentstyle`/非 UTF-8/epsfig 的拒绝路由只在那里覆盖得到。
6. **吞吐无需并行化**：下载 (~11MB/s) 是唯一瓶颈，扫描/特征/组装/bench 合计为分钟级；若走 Range 精选路线，唯一需要并发的是成员拉取（1.6s/req 延迟，8 路足够）。
