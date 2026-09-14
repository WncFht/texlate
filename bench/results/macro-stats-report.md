# LaTeX 高级构造使用频率统计 — 真实 arXiv 语料

语料: `bench/corpus/` 39 篇 arXiv 论文, 256 个 .tex, 164,687 行。
论文跨度 hep-th/9901001 (1999, **LaTeX 2.09**) → 2609.x (2026)。文档类混合: article / IEEEtran / acmart / revtex4 / elsarticle / amsart / llncs / aa / quantumarticle / cms-tdr / eptcs / cambridge7A / jfp / book(subfiles) / Agda-lhs2TeX。

两套口径:
- **ALL**: 全部 256 文件。
- **CLEAN**: 剔除 2 个捆绑实现文件(1712.01208/`acmart_old.tex` = acmart 类源码改名 .tex, 465 个 \def; 1902.03178/`preamble.tex` = quantumarticle 包文件)。以下默认 CLEAN (254 文件, 161,974 行)。

脚本: `bench/py/macro_scan.py` → 数据: `bench/results/macro-stats.json`(含每条定义的文件:行号)。

---

## 1. 宏定义命令: 覆盖率与密度

| 命令 | 论文覆盖 | 总定义数 | 备注 |
|---|---|---|---|
| `\newcommand` | **36/39 (92%)** | 2764 | 绝对主力 |
| `\renewcommand` | 23/39 (59%) | 116 | |
| `\def` (TeX 原语) | **20/39 (51%)** | 1126 | 一半论文直接用 plain-TeX 定义 |
| `\newtheorem` | 15/39 (38%) | 148 | 标题是可译文本 |
| `\DeclareMathOperator` | 8/39 (21%) | 115 | |
| `\newenvironment` | 8/39 (21%) | 30 | |
| `\providecommand` | 8/39 (21%) | 61 | |
| `\let` | 9/39 (23%) | 15 | |
| `\newif` | 1/39 | 8 | 见 §5 自定义旗标 |
| `\gdef/\edef/\xdef` | ~3/39 | 7 | 全局/展开式定义, 罕见 |
| `\NewDocumentCommand` (xparse) | **0/39 (0%)** | 0 | 语料中完全缺席 |
| `\DeclarePairedDelimiter` 等 | ≤2/39 | 少量 | mathtools 族 |
| **任一宏定义** | **37/39 (95%)** | **4433** | mean 114 / median 47 / max 446 |

分桶: 0 定义 2 篇(1412.6980, 2203.02155) | 1–20 个 8 篇 | 21–100 个 16 篇 | 101–300 个 7 篇 | >300 个 6 篇 (2106.09685=446, 1906.08237=427, 1502.01589=402)。

**定义不在序言**: 268 个定义出现在 `\begin{document}` 之后, 分布在 **20/39 (51%)** 论文中。1207.7214 有 81 个正文内定义(如 `\def\Figref{Figure~\ref{#1}}`, `\def\secref{Section~\ref{#1}}`), 2512.03164 有 54 个, 1207.7235 有 43 个。→ 只扫 preamble 会漏一半论文的全部定义。

## 2. 致命陷阱型定义体

对命令型定义(`\newcommand/\renewcommand/\providecommand/\def*/\DeclareMathOperator` 等, 不含 `\newenvironment` 的体)统计定义体内容:

| 陷阱类型 | 定义数 | 论文覆盖 | 说明 |
|---|---|---|---|
| 体含数学命令 (\frac/\sum/\mathbb/…) | 1790 | **31/39 (79%)** | 最普遍的陷阱 |
| 体含 `^`/`_` 上下标 | 255 | 20/39 (51%) | |
| 体含 `$`/`\(`/`\[` | 273 | 20/39 (51%) | |
| **体含 `\begin`/`\end`** | **180** | **12/39 (31%)** | `\be` 型 + 结构宏 |
| └ 体含**数学环境** `\begin{equation/align/…}` | 20 | 6/39 | |
| └ 体含非数学环境 (itemize/center/color/tabular…) | ~160 | ~10/39 | 同样致命 |
| 体含可译文本 (>20 字母) | 207 | **19/39 (49%)** | 不展开 → 漏译 |
| **命令型定义带任一上述旗标** | — | **34/39 (87%)** | |

### 真实例子

**`\be/\ee` 模式** (0906.4725/preamble.tex:196-208 — IOP 物理论文整套环境宏):
```latex
\newcommand{\bit}{\begin{itemize}}     \newcommand{\eit}{\end{itemize}\par\noindent}
\newcommand{\beq}{\begin{equation}}    \newcommand{\eeq}{\end{equation}\par\noindent}
\newcommand{\beqx}{\begin{equation*}}  \newcommand{\beqa}{\begin{eqnarray*}}
```
同型: 1502.01589/macros.tex `\newcommand{\be}{\begin{equation}}`, `\ba`/`\bea`→eqnarray; 1507.02284 `\newcommand{\be}{\begin{eqnarray} \begin{aligned}}`; 1502.01589 `\newcommand{\twoonesig}{\begin{equation}\left.\begin{aligned}#1 \\ #2\end{aligned}\right\}...\end{equation}}` — 整条公式模板藏在宏里。

**`\end{env}` 单独成宏** (0906.4725): `\def\e{\end{color}}` `\def\ec{\end{center}}` — 不展开连环境配对都做不到。

**宏体含可译文本**:
```latex
\def\cmsMessage{Submitted to Physics Letters B}          % 1207.7235
\def\ieeesc{IEEE Trans. Appl. Supercon.}                 % 1403.3985 (期刊名缩写宏族)
\newcommand{\papertitle}{Observation of a New Particle in the Search for
  the Standard Model Higgs Boson ...}                     % 1207.7214 — 标题本体在宏里!
\def\allearlypapers{planck2011-1.1, planck2011-1.3, ...} % 1502.01589 — cite key 列表
\newcommand{\TODO}{{WARNING!!! there is still a TODO left}{{!TODO: }{blue}{{#1}}}}
```

**`\ifmmode` 双分支宏** (1502.01589/Planck.tex, 一族 15+ 个):
```latex
\def\L2{\ifmmode L_2\else $L_2$\fi}
\def\solar{\ifmmode{\rm M}_{\mathord\odot}\else${\rm M}_{\mathord\odot}$\fi}
\def\expo#1{\ifmmode \times 10^{#1}\else $\times 10^{#1}$\fi}
```
→ 宏体同时含文本分支和数学分支, 翻译器必须求值 `\ifmmode` 或至少识别这是"数学安全的宏"。`\ensuremath` 更普遍: 542 次 / 18 篇 (46%)。

## 3. natbib vs 基础 \cite

| 族 | 论文覆盖 | 总次数 |
|---|---|---|
| 基础 `\cite` | 36/39 (92%) | 2554 |
| natbib 族 (`\citep`776 `\citet`269 `\citealt`57 `\citeauthor`18 `\citeyear*`…) | **14/39 (36%)** | ~1120 |
| biblatex 族 (`\parencite/\textcite/\citestyle`) | 3/39 | 少量 |

- **natbib-only 论文 = 0**: 14 篇用 natbib 的全部也混用 `\cite` —— 必须同时支持。
- natbib 重度用户: 1502.01589 (citep 238+citet 107), 1106.1445 (134), 2106.09685 (80), 1706.03762 (49), 1801.02634 (citep 47+citealt 39)。
- 意外: 1612.09375 用 `\citestyle` (chicago/自定义) 再自封装: `\newcommand{\citeCWM}{\citestyle{Mac~Lane (1971)}}` `\newcommand{\citeKel}{\citestyle{Kelly (1982)}}` — **引用命令本身是被定义的宏**, key 藏在展开层。
- `\bibliography`/`\bibliographystyle`: 27-29 篇 (BibTeX 仍主流); biblatex 仅 1 篇。`\bibitem` 直接内嵌 400 条 (bbl 贴进 .tex)。

## 4. `\section[opt]{…}` 可选参数

**仅 3 处 / 2 篇 (5%)**: 1502.01589/conclusions.tex `\section[Conclusions]{Conclusions\footnote{…}}`, 2501.14787/main.tex 2 处长标题换行。语料中 \subsection/\chapter 可选参数 0 处。→ 低频, 但 1502.01589 这处体内还套了 `\footnote`。

## 5. 条件 / makeatletter / 逐字

| 构造 | 论文覆盖 | 总量 |
|---|---|---|
| 任一 `\if*` 族 token | 12/39 (31%) | ~200 |
| TeX 原语 if (`\ifmmode`36 `\ifnum`4 `\ifx`1 `\ifhmode`1 `\iffalse`3) | ~5/39 | 45 |
| `\else` / `\fi` | 6 / 10 篇 | 47 / 60 |
| `\newif` 自定义旗标 (`\ifAppendicesIncluded`×9 `\ifAnonymous`×6 `\ifshowtodo`…) | 2-3/39 | 27 |
| `\ifthenelse` / etoolbox 族 | 2/39 | ~23 |
| `\makeatletter` | 10/39 (26%) | 16 |
| `\verb` | **1/39 (3%)** | 1 |
| `verbatim` env | **0/39** | 0 |
| `lstlisting` env | **0/39** | 0 |
| `minted` env | 1/39 | 25 |
| `comment` env (comment 宏包, 整段不可译) | 3/39 | 4 |
| Agda/lhs2TeX `code` env | 1/39 | 333 |

自定义旗标实例 (2005.11401): `\newif\ifAppendicesIncluded` + `\ifAppendicesIncluded …\fi` 控制附录编译。2201.05989: `\ifnum\commentType=0..3` 计数器驱动的条件批注引擎。`\iff` (30 次) 是数学"iff", 已排除。

→ verbatim 系在正文中近乎绝迹 (cs 论文代码用 minted/自定义 env, 物理/数学论文根本不贴代码); `\makeatletter` 却出现在 1/4 论文的**作者序言**里。

## 6. `\input/\include` 多文件

- **23/39 (59%) 论文 >1 个 .tex**; 同样 23 篇实际调用 `\input`(174) / `\include`(16) / `\subfile`(11)。
- 文件数分布: 1 文件 16 篇 | 2-7 个 10 篇 | 10-20 个 9 篇 | ≥20 个 4 篇, max **35 个** (1502.01589, Planck 全套 grid_*.tex)。
- subfiles 宏包实战: 2609.06443 (12 个子文件各自带 `\documentclass[main.tex]{subfiles}` — 每个文件都是完整文档), 1706.03762。
- ~15 篇附带专用宏文件: `macros.tex`/`defs.tex`/`math_commands.tex`/`symbol.tex`/`custom.tex`/`preamble.tex`/`Setup.tex`。
- 隐含结论: **多文件展平是前置条件** —— 定义在 macros.tex、用在 body.tex, 单文件扫描必漏。

## 7. 数学环境长尾

| 环境 | \begin 总数 | 论文覆盖 |
|---|---|---|
| equation | 2539 | ~35/39 |
| align/align* | 1417 | ~30/39 |
| **eqnarray/eqnarray*** | 96 | **~10/39** (deprecated 仍高活) |
| array | 355 | 高 |
| pmatrix/bmatrix/matrix/smallmatrix | 228 | 高 |
| cases | 36 | 中 |
| aligned/split/gathered/multlined | ~45 | 中 |
| multline | 83 | 3/39 |
| subequations | 3 | 3/39 |
| flalign | 2 | 1/39 |
| alignat* | 1 | 1/39 |
| empheq | 2 | 1/39 |
| IEEEeqnarray | 0 | 0 |
| dmath (breqn) | 0 | 0 |

→ 真"长尾"(subequations/flalign/alignat/empheq/IEEEeqnarray/dmath) 合计 8 次 / 5 篇 (~13%); 但 **eqnarray 在 ~1/4 论文中仍活跃**, 内部环境 (aligned/cases/array) 高频。自定义数学环境更常见: mathpar (mathpartir 推理规则) 23 次, bprooftree (bussproofs 证明树) 72 次, Agda `code` 333 次 —— 这些是"非标准数学/代码环境", 翻译面同样需要保护策略。

## 8. LaTeX 2.09 与引擎特征

- `\documentstyle`: **1/39** — hep-th/9901001 `\documentstyle[epsf,seceq,preprint]{ptptex}` (整篇 2.09 语法: 无 \usepackage, \rm 切字体)。
- `inputenc`: 12/39 (31%) | `fontenc`: 11/39 (28%) — pdflatex 签名仍普遍。
- `fontspec`/`\setmainfont` (Xe/Lua 签名): **0/39**。
- 其他旧时代物: `epsfig` 6 篇, `subfigure` (deprecated) 3 篇, `\usepackage{times}` 9 篇。

## 9. 意外发现 (扫描中的怪异构造)

1. **active 字符 + plain `\halign` 表** (1502.01589/grid_DM.tex:111):
   `\catcode`*=\active \def*{\kern\digitwidth}` `\catcode`!=\active \def!{\kern\signwidth}`, 内嵌 `\halign{\tabskip…\cr}` + `\leaderfil` + `\omit` — 这是纯 plain-TeX, 不是 LaTeX。
2. **类文件混进 .tex**: 1712.01208/`acmart_old.tex` 是整个 acmart.cls 改名 (含 `\ProvidesClass`, 465 \def, 全部 `if@ACM@*` 内部开关); 1902.03178/preamble.tex 是 quantumarticle 包文件。→ 决定语料统计要分"作者源文件/实现文件"两口径。
3. **正文中批量定义**: 1207.7214 在 `\begin{document}` 后一口气定义 81 个宏; `\def\Figref{Figure~\ref{#1}}` 这类**文本+引用混合宏**必须在展开层判断 (Figure~ 可译, \ref 不可译)。
4. **宏包装引用命令**: `\citeCWM`/`\citeKel` (§3) — 引用类宏族没有上限。
5. **lhs2TeX 产物**: 2609.08578 `*.processed.tex` 带 `code` 环境 333 处 + `if@ACM` 开关 — 机器生成源码是真实存在的一类输入。
6. **comment 环境** 3 篇: 整段被 LaTeX 跳过, 翻译器不应翻 (但应知道它是 verbatim 类)。
7. **正文里写死的出版社模板宏**: `\def\cmsMessage{Submitted to Physics Letters B}` — 是页眉文本, 翻译管线会把它当正文。
8. 环境名小语种化: math/0404188 全文法语 (`\begin{preuve}`84 `\begin{lemme}`52), env 白名单永远不完整。
9. `\expandafter`(3 篇) `\csname`(3 篇) `\AtBeginDocument`(2 篇) `\bgroup`(4 篇) — 存在但低频; 全在宏作者向论文中。

## 10. 结论: 宏展开层必要性评级

**总评级: 阻断性 (blocker)。** 数字依据:

- **95%** 论文有宏定义 (median 47 个/篇, max 446); **87%** 论文的命令型定义带"体变数学/环境/可译文本"旗标 —— 不展开就无法判定宏调用点的块类型。
- **79%** 论文有"数学宏"(体含数学命令, 1790 个), **46%** 的全部定义带数学特征 —— `\dR`-型保护必须走展开。
- **31%** 论文有"环境宏"(180 个体含 \begin/\end), 其中真 `\be→\begin{equation}` 6 篇、含 `\end{env}` 单出宏 —— 不展开则数学环境边界判错、甚至 begin/end 配对失败。
- **49%** 论文宏体藏 >20 字母可译文本 (论文标题、期刊名、TODO、引用 key 表) —— 不展开 = 漏译真实内容。
- **59%** 论文多文件 (max 35 文件) —— `\input` 展平与宏定义收集互为前置。
- **51%** 论文在 `\begin{document}` 之后定义宏 —— 定义收集必须贯穿全文, 不能只读 preamble。
- **51%** 论文直接用 `\def` (plain-TeX 参数语法 `#1`), 加上 `\newcommand[n]` 的两种参数模型都要实现; `\ensuremath` 542 次证明"数学安全宏"是常态。

### 分维度评级

| 能力 | 评级 | 依据 |
|---|---|---|
| `\newcommand/\def` 定义收集 + 参数代入 + 嵌套展开 | **阻断性** | 95%/51% 覆盖, 无此一切无从谈起 |
| `\input/\include/\subfile` 展平 | **阻断性** | 59% 论文; 宏文件与正文分离 |
| 展开体含 `\begin/\end` 的结构宏 (环境判定走展开后文本) | **高** | 31% 论文; 命中即边界判错 |
| 展开体含数学/`$`/`\ensuremath` 的宏 → 保护判定 | **阻断性** | 79% 论文; 这是数学保护的主路径 |
| 宏体可译文本提取 | **高** | 49% 论文漏译风险; 但可降级为"宏名当命令处理" |
| `\ifmmode/\ifx/\ifnum/\else/\fi` 求值 (至少识别双分支) | **高** | 12 篇用 if 族 + `\ifmmode` 族宏; 最低限度要能把 `\ifmmode…\else…\fi` 当整体处理 |
| `\makeatletter` 包裹段 | 中 | 26% 论文出现; 多数在类文件, 作者序言也有 |
| natbib `\citep/\citet/\citealt` 全族 | **高** | 36% 论文, 且与 `\cite` 并存 |
| 正文内 `\newcommand` 支持 | 高 | 51% 论文 |
| `\section[opt]` | 低 | 5%, 但实现便宜 |
| verbatim/`\verb` | 低 (出现率 ~3%), 但 `\begin{code}`/minted/comment 等"逐字类环境"中频 | 按"环境黑名单"处理更实际 |
| xparse `\NewDocumentCommand` | 低 | 0/39 — 可以不实现 |
| 长尾数学环境 (subequations/flalign/alignat/empheq) | 中 | 5 篇; `eqnarray` 必须支持 (~10 篇) |
| `\documentstyle` 2.09 | 低 | 2.5%, 但出现即全篇异构, 检出即可 |
| `\catcode`/active chars/`\halign`/`\expandafter` | **低 — 可放弃** | 1-3 篇, 属于 plain-TeX 深度特性; 预期损失可接受 |
| `\newif` 自定义旗标 | 中 | 少见但存在真实条件编译 |

**底线建议**: 不需要完整 TeX 求值器。需要的是: ①定义表 (newcommand/renewcommand/def/providecommand/newtheorem/newenvironment 六类语法) ②参数代入 + 迭代展开 (有深度上限) ③`\input` 递归展平 (注释掉的不展开) ④`\if…\else\fi` 结构化处理 (至少 ifmmode/ifx/自定义 newif 旗标) ⑤展开后文本再做环境/数学边界判定。放弃: catcode/halign/active chars/全 e-TeX 求值 —— 预期损失 ≤1/39 论文。
