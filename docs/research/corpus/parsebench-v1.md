# parsebench v1：miniscanner 在 137 篇无偏 arXiv 语料上的解析基准

日期：2026-09-14 · 依据：`bench/corpus_v2/`（137 篇分层随机源码语料，钉死版本）+ `bench/py/parsebench.py` + `bench/results/parsebench-corpusv2-*`。
口径方法学：`docs/research/corpus/parse-metrics-literature.md`（unarXive 漏斗/归因、olmOCR 断言桶、GROBID 三档、Wilson CI）。

## 0. TL;DR

在**自然分布**（非手挑）的 137 篇 arXiv 源码语料上，miniscanner 半解析器：

| 指标                                 | 数值                                                  | Wilson 95% CI  |
| ------------------------------------ | ----------------------------------------------------- | -------------- |
| 解析成功率                           | **223/223 = 100%**                                    | [98.3%, 100%]  |
| round-trip strict identity           | **223/223 = 100%**                                    | [98.3%, 100%]  |
| 泄漏率（leak）                       | **15/17375 chunks = 0.086%**                          | [0.05%, 0.14%] |
| fake-translation 死占位符/孤儿 chunk | **0 / 0**                                             | —              |
| 主文件定位                           | 137/137 找到根（3 篇 multi_doc 正确标记，0 rootless） | —              |
| wall                                 | 17.6s 全量（~13 文件/s，含 recon/leak/fake 三测）     | —              |

与手挑陷阱集 corpus39（256 文件）口径一致：泄漏 0.09% vs 0.11%，identity 均 100%——**无偏总体上手挑集没有美化也没有夸大**。

## 1. 语料构成（benchmark 底材）

- **来源**：`tmp/exp/arxiv-serial2/sample.jsonl`（190 发分层 HEAD 抽样）+ `/tmp/arxiv_cov.jsonl`（60 篇早轮）取源码阳性 id，按 HEAD content-disposition 中的 **vN 钉版本** GET `/src/{id}vN` → 魔数三态解包 + 路径安全过滤。
- **规模**：137 篇入库 / 254MB / 1178 文件 / **223 个 .tex**（tar 107 : 单文件.gz 32；旧式 37 : 新式 102）。
- **年代跨度**：1996–2026；**类目**：hep-th/hep-ph/hep-ex/astro-ph/cond-mat/gr-qc/nucl-th/quant-ph/math/cs + 新式全类随机。
- **documentclass 多样性**：40 种——revtex 全家（revtex/4/4-1/4-2）、amsart、article、IEEEtran、llncs、elsart/elsarticle、mn2e、aastex、emulateapj、iopart、ptptex、lamuphys、caps、hnp06、JHEP3、MRM、bmc_article、lipics、optica-article、geophysics 等。
- **注意偏倚**：旧式样本全为物理/数学 archive（arXiv 原生生态如此）；新式 id 随机未按类目分层（cs/econ 等 Word 重度领域代表性靠随机覆盖）。后续扩样时可用 HF 元数据快照做类目分层补齐。
- **复现**：`bench/corpus_v2/build_corpus.py` 断点续跑（剩余 63 条可恢复 + 补至 300）；清单 `bench/corpus_v2/MANIFEST.md`（入库）；抓取受阻记录：arXiv 在 ~150 发/日后触发 406 累计配额惩罚（已回填 arxiv-layer §2.3）。

## 2. 度量定义（学理对齐）

| 我们的口径       | 学名/惯例来源                 | 定义                                                                     |
| ---------------- | ----------------------------- | ------------------------------------------------------------------------ |
| parse ok         | —                             | `parse_file` 无异常返回（30s 超时）                                      |
| strict identity  | GROBID strict match           | `reconstruct()` 输出与原文逐字节一致                                     |
| normalized       | GROBID soft                   | 仅空白差异                                                               |
| diverged         | —                             | 有实质差异（报首差异位置）                                               |
| leak rate        | UTB 残留同族（BabelDOC 借名） | 可译 chunk 内含 `$`/`\cite*`/`\*ref`/`\begin{`/`\if*`/`\input{` 的块占比 |
| dead/orphan      | —                             | fake-translation 重建后残留 CHUNK 占位符数 / 孤儿 chunk 数               |
| flatten coverage | unarXive 漏斗项               | .tex 文件是否被主文件 `\input` 图触及                                    |

## 3. 漏斗与失败归因（unarXive 式）

```
139 fetched ──unpack──▶ 137 papers with .tex（丢弃：pdf_only 2、unpack_error 1）
137 papers ──locate──▶ 137 rooted（3 multi_doc、0 rootless）
223 .tex ──parse──▶ 223 ok（0 crash/timeout）
223 recon ──▶ 223 strict identical / 0 normalized / 0 diverged
17,375 chunks ──leak──▶ 15 hits（0.086%）
fake-translate rebuild ──▶ 0 dead / 0 orphan
```

**泄漏归因分解（15 hits 逐条人工复核）**：

| 机制                                                                  | 次数 | 严重度                                       | 例证                                                                                                     |
| --------------------------------------------------------------------- | ---- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `%` 注释残留在被挖的 caption/footnote 参数内，注释里恰好有 `$`/`\ref` | ≥4   | 低 - 中                                      | `2109.12648` caption 内 `%$\vec x\mathcal{L}_\kappa...`；`hep-ph/0411093` 两个 caption 内 `%DAMA/NaI...` |
| 散文中字面 `$`（货币/单位/排版习惯写法）                              | ~8   | 低（多数良性——`$` 本就是可译文本的合法字符） | `0808.2824` 段落、`2207.12086` 数据集描述                                                                |
| footnote 内条件式排版 hack                                            | 1    | 低                                           | `1404.4155` `\footnotetext{...\ifnum...\thehours}` 页脚日期戳                                            |
| caption 内 ref_family 漏保护                                          | 1    | 中                                           | `1409.6539` caption 内 `\eq{key}` 自定义宏引用未入 KEY 占位                                              |

→ 新进 rewrite 规格项：**`_arg_inline` 挖掘时剥参数内注释**（注释文本现在会混进 chunk 送 LLM）。整条路径已列入 `miniscanner-rewrite-spec.md` 增补清单。

## 4. 论文级发现

- **multi_doc 全部命中**：2101.07948（acmart×3）、2101.08358（article×2）、2312.11468（MRM×2）。
- **路由标签分布**：`reject`（LaTeX 2.09-era：documentstyle/revtex 旧版/psfig）**12 篇全在旧式 id 区**（1996–2001，~32% of old 样本）——与"老物理论文 2.09 浓度高"预期一致，编译侧 reject 率的分母来源在此；`xelatex`（eps/pstricks）~35；`non-utf8` 5；`no-hyperref` 在旧区占绝对多数（hyperref 普及是后期现象——滚动同步的"无锚退化"在老论文上会是常态，E18 的 31% 退化占比方向吻合）。
- **orphan tex 31 个**：主因 `\input file` 裸形式（已知缺口，1502.01589 同型；1107.4465 贡献 16）、`.sty` 间接装载、注释掉的 `\input`（正确不展开）。rewrite 已含裸 `\input` 修复。
- **chunk 尺度**：median 199 字符 / p90 794——批量翻译的打包协议（<300 字符入批）自然适配。

## 5. 对照表

| 语料                         | n 文件  | ok%     | strict ident% | leak%     | 死/孤儿 |
| ---------------------------- | ------- | ------- | ------------- | --------- | ------- |
| corpus39（手挑陷阱）         | 256     | 100     | 100           | 0.11      | 0/0     |
| **corpus_v2（无偏随机）**    | **223** | **100** | **100**       | **0.086** | **0/0** |
| ieeA 旧基线（90 文件旧语料） | 90+     | 100     | 0             | 10.24     | 16 dead |

## 6. 这个 benchmark 能干什么

1. **M0 重写验收门**：`src/texlate/latex/` 9 文件重写的验收从"259 文件手挑集"升级为"479 文件混合集"（corpus39 + corpus_v2），跑 `parsebench.py --corpus` 两次即可；建议门槛：ok 100%、strict identity ≥99.5%（允许 normalized 容差）、leak ≤0.15%、0 死占位符。
2. **fixloop/编译侧共用底材**：同一语料可直接喂编译 benchmark（路由标签已随 papers.json 产出）——reject/xelatex/minted/non-utf8 标签即静态路由金标准。
3. **回归机制**：每改一行 scanner 重跑 17.6s 出差异表；`files.jsonl` 逐文件 diff 可定位回归点。
4. **扩容路径已备**：`build_corpus.py` 续跑至 ~300（等 406 窗口解除）；上千篇走 IA `arxiv-bulk` 月 tar（免费、1991–2020）或 scholarweave parquet（2020 后、有损仅文本层）；规模 ~2k+ 再上 S3 付费通道。
5. **可发布子集**：license 分层表（HF 快照 license 字段 85.7% 覆盖）→ CC0/PD/BY/BY-SA 圈出 ~64 万候选池，若要公开分发 benchmark 走这个子集。

## 7. 局限（诚实清单）

- n=137 → "100% ok" 的 Wilson 下界是 98.3%；要证明 ≥99.5% 需要 n≥800（续跑+IA tar 补）。
- 语料偏物理/astro（旧式 id 的固有生态）；cs/econ 等新式领域靠 102 篇新式随机覆盖，未按类目分层——补样时用 HF 快照显式分层。
- 泄漏口径是保守正则（字面 `$` 在散文中合法）——15 hits 里 ~8 条是良性字面 `$`，真实"保护失败"约 4–6 条（≈0.03%）。
- 本 benchmark 只覆盖"解析"段；编译成功率、翻译质量需另建（编译可用同语料 + 路由标签金标准；翻译质量等 LLM key 实测 + `tmp/exp/modelbench/`）。
- 2/139 入库论文无 .tex 进榜（pdf_only/unpack 丢弃），漏斗第一段的丢弃率已被 capture。

## 8. 产物索引

- 跑分器：`bench/py/parsebench.py`（`--corpus DIR [--manifest M.jsonl] [--out P]`，corpus39 零差异对拍通过）
- 数据：`bench/corpus_v2/`（139 目录/含 meta.json+raw+extracted）+ `manifest.jsonl` + `build_corpus.py`（可续跑）
- 结果：`bench/results/parsebench-corpusv2-{files.jsonl,papers.json,summary.md}`、`parsebench-corpus39-*`（对拍基线）
- 清单：`bench/corpus_v2/MANIFEST.md`（入库）
- 方法学：`docs/research/corpus/parse-metrics-literature.md`；语料源调研：`hf-latex-datasets.md`、`bulk-channels.md`、`corpus-arxmliv-unarxive.md`、`corpus-labels.md`
