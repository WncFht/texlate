# LaTeX 解析/编译大对比 — 总结论报告

日期: 2026-09-14 | 语料: 39 个 arXiv 项目 / 256 个 .tex(16.5 万行,LaTeX2.09→2026 全年代)+ fixtures 30 陷阱
评测面: 8 个第三方库(4 TS / 4 PY)+ ieeA 基线 + 自研 miniscanner spike,PROTOCOL.md 同口径
单项报告: 本目录 `*-report.md` / `*-walkthrough.md` 共 19 份

## 0. TL;DR — 最终架构定案

**解析层: 自研 Python 半解析器(路线已验证), 不采用任何现有库作主解析器。**

miniscanner spike(1176 行,单次正向逐字符扫描→pieces→占位符保护→区间 splice 重建)在 256 文件语料上:

| 指标 | miniscanner | 最好第三方 | ieeA |
| --- | --- | --- | --- |
| 陷阱断言 | **32/32 全过** | 24/26 (latex-utensils) | 16/3/7 |
| 泄漏率 | **0.11%** | ~需要+40行策略才接近 | 10.24% |
| identity 重建 | **259/259 字节一致** | 62/89 (TexSoup) | 0/93 |
| 宏展开陷阱 T01 | **pass** | **全库 fail** | fail |
| 中位耗时 | 1.3ms | 4.56ms | 22.6ms |

**编译层: 自动修复循环可行,救回率 16/16=100%(94% clean)。** 16 条规则已实测触发,`static_precheck+install_file/install_tfm/install_sysfont` 四招承担 90% 修复。hjfy 的"人肉固化修复库"可由规则表+LLM 自动修复替代,且更好(白盒可贡献)。

**覆盖层: e-print 源码 87% → arXiv HTML 同覆盖异构降级 → BabelDOC/MinerU PDF 兜底 13%。** BabelDOC 实测 60s/15页、质量高、AGPL sidecar 隔离方案成立。

---

## 1. 解析库能力矩阵(全部实测,非文档宣称)

| 库 | 语料成功 | 陷阱(过/半/败) | 泄漏率 | identity | 速度 | 对我们的价值 |
| --- | --- | --- | --- | --- | --- | --- |
| **miniscanner (自研)** | 259/259 | **32/0/0** | **0.11%** | **259/259** | 1.3ms | **主解析器** |
| latex-utensils (TS) | 89/90 | 24/2/0 | 低(需策略) | — | 4.56ms | 命令族表/签名参考;错误位置不可信(PEG farthest-failure) |
| unified-latex (TS) | 90/90 | 19/4/3 | 中 | 差 | 43ms | **CTAN 签名表(404宏+128环境)+受限展开参考实现**;interval 重建思路 |
| tree-sitter-latex (TS) | 90/90 不崩 | 灾难性 ERROR | — | — | **1.15ms** | **译文校验器**(ERROR/MISSING+~35行 CST env 配对);`\verb | a%b | ` 静默错 |
| TexSoup (PY) | 84→89/90 | 4 fails | 中 | 62/89 | 69ms | tokenizer 内核 + 4 处手术参考 |
| plasTeX (PY) | ~75/90 诚实 | — | — | — | 29ms | **展开层设计 oracle**(mouth/gullet+UnrecognizedMacro);真.sty 加载=静默截断,须屏蔽 |
| pylatexenc (PY) | 假 90/90 | 静默截断 | — | — | — | **REJECTED**:M1 组内`\begin`吞至EOF 97.9%、M2 `%`吃`}` 99.7%损失,零报错 |
| LaTeX.js (TS) | — | 无展开 | — | — | — | 签名参数表+~50行 groups 机;非真 TeX |
| ieeA (PY) | 93/93 | 16/3/7 | 10.24% | 0/93 | 22.6ms | 反面基线;翻译编排可借鉴 |

### 关键架构事实(实测发现)

1. **宏展开是所有现成库的共同盲区。** T01(`\be→\begin{equation}`)8/8 库全灭;真实语料 12/39 篇存在结构性宏(macro-stats)。半解析器+宏表是唯一正确路线。
2. **"能 parse"≠"parse 对"。** pylatexenc 90/90 是假象(静默截断零报错);TexSoup 93%@t0 但注释降级为裸文本不可区分;tree-sitter `\verb|a%b|` 静默把 `%b|` 当注释。**无错误信号比崩溃更危险** — 我们的校验器必须独立。
3. **AST round-trip 不可行,区间 splice 是唯一保真路径。** 严格解析器在真实脏语料上必破(Pset1sol.tex 真·缺`$`);miniscanner 的 pieces 覆盖全文、identity=逐字节一致,证明"宁粗勿断"正确。
4. **piece 边界纪律是 ieeA 死 token 的根治。** 块级结构(`\begin/\end/\item`/条件命令)必须 `_emit` 独立 piece 而非并入 run——否则边界 token 并入 chunk,复刻 ieeA 16 处死 token 机制。
5. **`\%` vs `\\%` 逐字符 tokenize 天然消解**,无需 lookback;verbatim/`\url`/`%\verb` 的 `%` 判定顺序: 逐字环境先吃→宏表→注释。

## 2. 宏展开层 — 必要性量化(macro-stats,39 篇实测)

| 事实 | 数 | 含义 |
| --- | --- | --- |
| 论文含宏定义 | **95%** (median 47/篇,max 446) | 不展开=普遍失明 |
| `\be` 模式(体含`\begin/\end`) | **12/39 篇 / 180 个** | 结构性陷阱真实普遍 |
| 宏体含数学命令 | 79% 论文 / 1790 个 | `\dR` 类数学宏必保护 |
| 宏体藏>20字母可译文本 | **49%** 宏 | 不展开→标题/期刊名泄漏或漏翻 |
| `\begin{document}`后定义宏 | **51%** 论文(268个) | 只扫 preamble 必漏 |
| `\if`族 / `\makeatletter` | 31% / 26% | 条件结构须按 boundary 处理 |
| `\NewDocumentCommand` | 0 | xparse 可暂缓 |
| natbib 族(与`\cite`并存) | 36% | 词族匹配,不能只认`\cite` |

**最小可行范围**(macro-stats 结论): 六类定义语法收集(含正文内)+ 参数代入 + 迭代展开(不动点)+ `\input`展平 + `\if/\else/\fi`结构化(至少 ifmmode/自定义旗标)+ 展开后环境/数学边界判定。**可放弃**: catcode/halign/active-chars(预期损失 ≤1/39)。

## 3. 编译层 — 修复循环 spike(fixloop,12项目×3条件)

| 口径 | 数 | 率 |
| --- | --- | --- |
| 原始 xelatex 即失败(冷环境) | 16/22 | |
| **循环救回 pdf** | **16/16** | **100%** |
| 救回且 clean(≤3错) | 15 | 94% |
| 终态出pdf | 22/22 | 100% |

- **四招承担全部修复**: `static_precheck`(kpsewhich 预检+批量 tlmgr)×22、`install_file`×26、`install_sysfont`×14、`install_tfm`×13。其余 12 条规则(pdftex_prim_guard/px_to_bp/microtype_off/hyphenation_sane…)低频但真实触发。
- **唯一非 clean**: 2005.11401/zh `soul_err`(soul 族命令参数含 CJK)——正是 `soul_cjk_mbox` 规则的目标场景,已定位修法。
- **tectonic 陷阱确认**: 静默降级,"出PDF"≠成功,须用 `'!'错误数≤3` 的 clean 阈值判定。
- **路由**: LaTeX2.09(hep-th)标记拒绝→latex+dvips,不进 xelatex 循环。
- **hjfy 对比**: 人肉固化 5000+ 文件修复 → 我们规则表(yaml 可贡献)+ LLM 修复器(log+源文件→最小patch),白盒可复现。

## 4. 覆盖率与降级链(arxiv-coverage,60 篇实测抽样)

| 层 | 覆盖 | 说明 |
| --- | --- | --- |
| e-print LaTeX 源码 | **86.7%** | 主管线;84.6% 多文件 tar(中位7文件),38.5% 自带 .cls/.sty,**42.5% 有.bbl无.bib→编译直接消费.bbl** |
| arXiv HTML | **=源码覆盖** | LaTeXML 从源码生成,救不了 PDF 直投;作同覆盖下异构降级(扛怪宏) |
| 仅 PDF(PDF直投) | **13.3%** | 唯一救星=PDF 通路(BabelDOC/MinerU) |

降级链: `e-print → arXiv HTML 最新版 → MinerU/BabelDOC PDF`。要 ~100% 覆盖 PDF 通路不可省。

## 5. BabelDOC sidecar(babeldoc-smoke 实测)

- **可行**: 0.6.4 独立 venv(702MB 无 Torch,ONNX 布局),Adam 15页 60s,~156k tokens/篇($0.02–0.05),峰值 1.1GB。
- **质量**: 正文/公式/算法框/参考文献保持好,**图内矢量文字也翻译且无溢出**,中文收缩49%利于排布。短板: 密集内联数学段落占位符乱序/碎片交叠(恰是源码路线能规避的)。
- **两坑**: ①网关拒绝 `temperature=0`→`--no-send-temperature`;②**翻译失败静默 fallback 原文,不报错**→sidecar 必须校验 token 数/监控 fallback 日志防"假成功"。
- **落地**: subprocess 调 CLI 的 FastAPI 封装 ~200行/1–2天,同时解决 AGPL 隔离+崩溃隔离。**禁止 import 进主进程**。

## 6. 最终组件选型(修订 docs/01)

| 组件 | 选型 | 依据 |
| --- | --- | --- |
| 主解析器 | **自研 miniscanner 路线**(Python) | 唯一过 T01+32/32+0.11%+identity 100%;所有现成库在宏展开上全灭 |
| 宏表/展开参考 | plasTeX(设计)+ unified-latex(签名表) | mouth/gullet+UnrecognizedMacro;404宏+128环境 CTAN argspec |
| 命令族表 | miniscanner ~150行表 + latex-utensils/unified-latex 签名交叉验证 | 词族匹配优于白名单 |
| 译文校验器 | **tree-sitter-latex**(CST ERROR/MISSING+env配对) | 1.15ms 永不崩;补 token-diff/brace-diff |
| 编译 | **xelatex 主 + tectonic 便携降级 + fixloop 规则表** | 救回率实测 100%;clean阈值判定 |
| ctex 注入 | `\usepackage[fontset=windows,UTF8]{ctex}` hjfy 同款 | 0% 破坏(compile-bench) |
| 源码获取 | e-print→HTML→PDF 三级降级 | 87%/=源码/13% |
| PDF 通路 | BabelDOC sidecar(AGPL) | 实测可行,唯一覆盖 PDF 直投 |

## 7. 残留风险与下一步

- **miniscanner 残留 25 处泄漏**(0.11%): 18×`$`错配(保护段吞`$`致配对错位)+ 7×`\begin/\if` 字面残留——边界退化非架构缺陷,修法: 保护段内`$`计数参与配对/未配对`$`后验局部重扫。
- **fixloop 12 条规则未触发**(低频场景语料未覆盖)——随语料扩到 100/200 篇补齐案例库。
- **hjfy 未覆盖能力**: 数学内 `\text{}` 中英混排、`\includegraphics` 图内文字(我们也不翻,BabelDOC 反而翻)、arXiv HTML 版直接翻译(更轻量 fallback)。
- **M0 开工就绪**: 语料 39 篇已超目标(≥20),miniscanner 即 M1 级解析器雏形,fixloop 即 M2 级修复循环雏形——**两大护城河的可行性都已实证,不再是假设。**
