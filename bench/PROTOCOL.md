# LaTeX 解析库 Benchmark 协议

目标: 评测各语言 LaTeX 库对**真实 arXiv 源码**的处理能力, 为"段落级提取+保护+重建"管线选型。

## 语料
- `corpus/` — 39 篇真实 arXiv 源码 (见 MANIFEST.md): NIPS/ICLR/CVPR/ICML/IEEEtran/ptptex(LaTeX2.09!), amsart/revtex4-4.1-4.2/aastex61/aa/elsarticle/acmart×4/llncs/iopart/quantumarticle/cms-tdr/eptcs/jfp-epi/subfiles/cambridge7A/book, 法语 babel, 中文注释, latin-5 编码, bussproofs/mathpartir 推导树, tikz 重度, algorithm2e/algorithmic, xy/pstricks, 自带 cls/sty/bst, 2.2MB 单文件书, subfiles/\include 多文件项目
- `fixtures/tricky.tex` — 30 个陷阱构造, 每处标 `% @Tnn`
- `fixtures/tricky-209.tex` — LaTeX 2.09 旧格式 (\documentstyle/\def)
- `fixtures/tricky-multi/` — \input/\include 多文件 + 注释掉的 \input(不得展开)

## 每个库测 4 项

### 1. 解析鲁棒性 (corpus 全部 .tex)
- 成功/失败(异常类型)/耗时, 30s 超时
- 产出: `results/{lib}-parse.json` — [{file, ok, error, ms}]

### 2. 陷阱断言 (fixtures)
逐条检查分类是否正确:
| ID | 构造 | 期望 |
|---|---|---|
| T01 | `\be…\ee`(\newcommand展开的公式环境) | 整体保护,不泄漏到可译块 |
| T02 | `\dR` (\newcommand数学宏) | 保护 |
| T03 | `\def\wt` | 识别为宏定义,不翻 |
| T04 | natbib全族 \citep\citet\citealp\citeauthor\citeyear + \ref\eqref\autoref\cref\pageref\nameref\label | key绝不出现可译块 |
| T05 | `\section[Short]{Long…}` | 长标题成可译块 |
| T06 | 单行verbatim/lstlisting含% | 原样保护,%不当注释 |
| T07 | `\url{..%20..}` `\verb|a%b|` | 保护,%不截断 |
| T08 | 注释(含不平衡{和数学) `\%` `\\%` | 注释不译,转义%保留,不崩 |
| T09 | `\author[1]{…\thanks…\and…}` | 保护(或可配置) |
| T10 | subequations/align/flalign | 保护 |
| T11 | `\begin{theorem}[Main Result]` | 正文可译,环境不破坏 |
| T12 | caption内\footnote | footnote文本可译 |
| T13 | `\ifdraft…\else…\fi` | 不崩(内部文本可译加分) |
| T14 | \input/\include递归 + 注释掉的\input | 展平;注释掉的不出现 |
| T16 | \NewDocumentCommand | 不泄漏不崩 |
| T17 | `\text{…}`在数学内 | 随数学保护 |
| T18 | figure内\caption | caption可译,figure结构保留 |
| T20 | itemize/enumerate/description | item文本可译 |
| T23 | \emph\textbf\textit{文本} | 内部文本可译 |
| T22 | \href{url}{text} | url保护,text可译 |
| T24 | \bibliography{refs} | 不崩 |
| T25 | \makeatletter区 | 不崩 |
| T27 | \'e \"u \~n 重音命令 | 保留为文本 |

### 3. Round-trip 保真 (corpus 主文件)
parse→serialize→与原文对比: identical / normalized(仅空白差异) / diverged(报告差异位置和大小)。只测声称支持序列化的库。

### 4. 泄漏率 (corpus 全部文件)
提取可译段落块后, 统计块内含 `$`、`\cite`、`\ref`、`\begin{`(数学/保护环境名) 的块比例 = 泄漏率。越低越好。

## 报告格式
`results/{lib}-report.md`: 能力矩阵 + 每个失败案例的最小复现 + 源码层面的架构分析(怎么实现的、为什么这样失败、改造成本) + 对"我们的管线"的可复用性评估。
