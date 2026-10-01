# parsebench v1：miniscanner 在 137 篇无偏 arXiv 语料上的解析基准

> **结论**：在自然分布（非手挑）的 137 篇 arXiv 源码语料上，miniscanner 半解析器达到 parse ok 223/223=100%、strict identity 100%、泄漏率 15/17,375 chunks=0.086% [0.05%,0.14%] Wilson、死占位/孤儿 0——与手挑陷阱集口径一致（0.086% vs 0.11%），无偏总体上手挑集没有美化也没有夸大。
> **状态**：时点证据（2026-09-14 口径）。miniscanner 已退役（v2 `gullet/`+`segmenter/` 为唯一解析路径）；corpus_v2 语料已并入统一物理根 `bench/corpus/`（139 在场 / 217 manifest 行）。本文保留该时点的漏斗、归因与对照数据。
> **日期**：2026-09-14

依据：`bench/corpus/`（原 corpus_v2，`manifest_v2.jsonl` / `MANIFEST_v2.md`；137 篇分层随机源码语料，钉死版本）+ `bench/py/parsebench.py`。口径方法学：`research/methods/parse-metrics-literature.md`（unarXive 漏斗/归因、olmOCR 断言桶、GROBID 三档、Wilson CI）。

## 1. 语料构成（benchmark 底材）

- **来源**：190 发分层 HEAD 抽样 + 60 篇早轮，取源码阳性 id，按 HEAD content-disposition 中的 **vN 钉版本** GET `/src/{id}vN` → 魔数三态解包 + 路径安全过滤。
- **规模**：139 篇入库 / 137 篇进榜 / 254MB / 1,178 文件 / **223 个 .tex**（tar 107 : 单文件.gz 32；旧式 37 : 新式 102）。
- **年代跨度**：1996–2026；**类目**：hep-th/hep-ph/hep-ex/astro-ph/cond-mat/gr-qc/nucl-th/quant-ph/math/cs + 新式全类随机。
- **documentclass 多样性**：40 种——revtex 全家（revtex/4/4-1/4-2）、amsart、article、IEEEtran、llncs、elsart/elsarticle、mn2e、aastex、emulateapj、iopart、ptptex、lamuphys、caps、hnp06、JHEP3、MRM、bmc_article、lipics、optica-article、geophysics 等。
- **注意偏倚**：旧式样本全为物理/数学 archive（arXiv 原生生态如此）；新式 id 随机未按类目分层（cs/econ 等 Word 重度领域代表性靠随机覆盖）。
- **抓取受阻记录**：arXiv 在 ~150 发/日后触发 406 累计配额惩罚——这是后来全面转向 IA/HF 批量源的直接动因（渠道裁决见 `v3-plan.md`/`post2020-sourcing.md`）。

## 2. 度量定义（学理对齐）

| 口径             | 学名/惯例来源                 | 定义                                                                     |
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
143 reached ──unpack──▶ 139 source trees（fetch 段丢弃：pdf_only 2、unpack_error 1、not_found 1；另有 74 发 406 阻断未计入）──has .tex──▶ 137 papers（丢弃：nucl-ex/0203009 零 .tex tar、quant-ph/0207092 仅含大写 test.TEX——当时 *.tex glob 大小写敏感；2026-09-15 起 is_tex 已大小写不敏感，重跑为 138 papers/224 files）
137 papers ──locate──▶ 137 rooted（3 multi_doc、0 rootless）
223 .tex ──parse──▶ 223 ok（0 crash/timeout）
223 recon ──▶ 223 strict identical / 0 normalized / 0 diverged
17,375 chunks ──leak──▶ 15 hits（0.086%）
fake-translate rebuild ──▶ 0 dead / 0 orphan
```

泄漏归因分解（15 hits 逐条人工复核）：

| 机制                                                                  | 次数 | 严重度                                       | 例证                                                                                                     |
| --------------------------------------------------------------------- | ---- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `%` 注释残留在被挖的 caption/footnote 参数内，注释里恰好有 `$`/`\ref` | ≥4   | 低 - 中                                      | `2109.12648` caption 内 `%$\vec x\mathcal{L}_\kappa...`；`hep-ph/0411093` 两个 caption 内 `%DAMA/NaI...` |
| 散文中字面 `$`（货币/单位/排版习惯写法）                              | ~8   | 低（多数良性——`$` 本就是可译文本的合法字符） | `0808.2824` 段落、`2207.12086` 数据集描述                                                                |
| footnote 内条件式排版 hack                                            | 1    | 低                                           | `1404.4155` `\footnotetext{...\ifnum...\thehours}` 页脚日期戳                                            |
| caption 内 ref_family 漏保护                                          | 1    | 中                                           | `1409.6539` caption 内 `\eq{key}` 自定义宏引用未入 KEY 占位                                              |

→ 产生的 rewrite 规格项：**`_arg_inline` 挖掘时剥参数内注释**（注释文本会混进 chunk 送 LLM）。

## 4. 论文级发现

- **multi_doc 全部命中**：2101.07948（acmart×3）、2101.08358（article×2）、2312.11468（MRM×2）。
- **路由标签分布**：`reject`（LaTeX 2.09-era：documentstyle/revtex 旧版/psfig）**12 篇全在旧式 id 区**（1996–2001，~32% of old 样本）——与「老物理论文 2.09 浓度高」预期一致，编译侧 reject 率的分母来源在此；`xelatex`（eps/pstricks）~35；`non-utf8` 5；`no-hyperref` 在旧区占绝对多数（hyperref 普及是后期现象）。
- **orphan tex 31 个**：主因 `\input file` 裸形式（已知缺口，1502.01589 同型；1107.4465 贡献 16）、`.sty` 间接装载、注释掉的 `\input`（正确不展开）。
- **chunk 尺度**：median 199 字符 / p90 794——批量翻译的打包协议（<300 字符入批）自然适配。

## 5. 对照表

| 语料                         | n 文件  | ok%     | strict ident% | leak%     | 死/孤儿 |
| ---------------------------- | ------- | ------- | ------------- | --------- | ------- |
| corpus39（手挑陷阱）         | 256     | 100     | 100           | 0.11      | 0/0     |
| **corpus_v2（无偏随机）**    | **223** | **100** | **100**       | **0.086** | **0/0** |
| ieeA 旧基线（90 文件旧语料） | 90+     | 100     | 0             | 10.24     | 16 dead |

## 6. 局限

- n=137 → "100% ok" 的 Wilson 下界是 98.3%；要证明 ≥99.5% 需要 n≥800——这是 v3 核心层 n=1,000 的直接动因。
- 语料偏物理/astro（旧式 id 的固有生态）；cs/econ 等新式领域靠 102 篇新式随机覆盖，未按类目分层——v3 以 HF 快照显式分层补齐。
- 泄漏口径是保守正则（字面 `$` 在散文中合法）——15 hits 里 ~8 条是良性字面 `$`，真实「保护失败」约 4–6 条（≈0.03%）。
- 本 benchmark 只覆盖「解析」段；编译成功率、翻译质量需另建。
- 2/139 入库论文无 .tex 进榜（nucl-ex/0203009 零 .tex tar、quant-ph/0207092 仅大写 test.TEX——见 §3 漏斗注）；pdf_only/unpack_error/not_found 属 fetch 段丢弃、从未入库，与进榜丢弃分计。
