# unified-latex 深度评测报告

- 库: `@unified-latex/*` v1.8.4 (siefkenj/unified-latex, monorepo 20 个子包)
- 评测日期: 2026-09-14, 全部实测 (node + 已装 `index.cjs` 包)
- 结果文件: `unified-latex-parse.json` / `unified-latex-tricky.json` / `unified-latex-roundtrip.json` / `unified-latex-leak.json`
- 脚本: `bench/ts/ul_common.js`, `ul_worker.js`, `ul_corpus.js`, `ul_tricky.js`

## 1. 架构总览 (源码实测)

`parse()` 是一条 4 段流水线 (util-parse/index.js):

1. **PEG 词法层** (`unified-latex-util-pegjs`, 15k 行生成代码): `LatexPegParser.parse(str)` 产出**扁平 AST**——宏参数此时**不挂载**, `\foo{bar}` 是相邻的 macro 节点 + group 节点。PEG 是**带兜底的严格文法**: 顶层要求吃完全部输入, 但几乎所有"畸形"构造都有 fallback 产生字符串/裸宏 (见 §4)。
2. **catcode 重扫** (`unifiedLatexProcessAtLetterAndExplMacros`): 识别 `\makeatletter/\makeatother` 与 `\ExplSyntaxOn` 区域, 区域内宏名重切分 (`\@ifnextchar` 合成单宏名, T25 实测正确)。
3. **签名表参数挂载** (`unifiedLatexProcessMacrosAndEnvironmentsWithMathReparse` + util-arguments): 合并 `unified-latex-ctan` 全部签名表 (404 宏 + 128 环境, 覆盖 latex2e/amsmath(mathtools)/hyperref/cleveref/xparse/listings/xcolor/tikz/beamer 等 17 包), 用 argspec (xparse 风格 `m o s d<> u e +` 前缀) 从扁平 token 流里"吃掉"参数, `gobbleSingleArgument` 找不到参数时返回空 arg 节点——**静默, 不报错**。
4. **数学重解析**: `inlinemath/displaymath/mathenv` 已由 PEG 直接产出; ctan 表里 `renderInfo.inMathMode` 的环境 (cases/matrix 族等) 内容再用 `parseMathMinimal` 重切。

关键设计事实:
- **数学环境名硬编码在 PEG 里**: `equation* equation align* align alignat* alignat gather* gather multline* multline flalign* flalign split math displaymath` → `mathenv` 节点。其余数学环境 (subequations/eqnarray/IEEEeqnarray) 是普通 `environment` 节点 + 常规模式内容 (内部嵌套 `\begin{align}` 仍会识别为 mathenv)。
- **verbatim 族硬编码**: `\verb*|\verb|\lstinline|\mintinline|\mint` + 环境 `verbatim* verbatim filecontents* filecontents comment lstlisting minted`, body 为原样字符串。注意: `lstlisting` 因在 ctan 表里有签名 (`o`), 后处理把节点 type 从 `verbatim` 改写成 `environment`——**verbatim 判定要按环境名不能只看 node.type**。
- **`$$...$$` → displaymath**; `\[...\]` → displaymath; `\(...\)`/`$...$` → inlinemath。节点 type 齐全。
- **每个 PEG 节点带 `position.start/end.offset`** (实测与原文 slice 精确一致), 但后处理生成的 `argument` 节点**无 position** (可由子节点或相邻 group 位置推断)。
- **不做文件 IO**: `\input/\include` 只是带 `m` 参数的宏, 不展开 (T14)。

## 2. 语料解析鲁棒性

**90/90 文件全部成功**, 含 LaTeX 2.09 (`hep-th/9901001`, `\documentstyle`), 多文件项目, 自带宏定义文件 (`math_commands.tex/custom.tex/symbol.tex`)。

耗时: min 19ms, median 43ms, p90 99ms, max 451ms (149KB neurips_2021.tex), 总计 5.2s / ~3MB 源码。无超时, 无 worker 崩。

## 3. 陷阱断言矩阵 (fixtures/tricky.tex 逐条实测)

`tricky.tex` 整体 `parse()` 成功。下表"状态"为**分类正确性**, 非能否解析:

| ID | 构造 | 状态 | 实测行为 |
|---|---|---|---|
| T01 | `\be..\ee` (newcommand→equation env) | **FAIL** | `\be/\ee` 是裸宏 (无名签名), 中间 `\wt{A} = \Tr(M^2)` 以普通 token 泄漏进可译块。经受限展开+重解析可修复 (见 §6) |
| T02 | `\dR` (\mathbb{R}) | partial | 数学内使用随 inlinemath 保护; 文本中 `\dR{}` 是裸宏+空 group, 展开后 `\mathbb{R}` 的 `R` 仍会按文本泄漏 |
| T03 | `\def\wt{\widetilde}` | partial | `\def` 无签名→裸宏; 定义体 `{\mathop{\rm Tr}\nolimits}` 中字符串 `Tr` 泄漏为文本; **不被识别为定义** |
| T04 | natbib 全族 + ref 族 | **FAIL** | `\citep\citet\citealp\citeauthor\citeyear\nameref` **全不在 ctan 表** → 0 args, key 以孤儿 group 泄漏: `vaswani2017 kingma2015 he2016 devlin2019 sec:a` 全部进入可译块; `\citet` 的 `[see][chap.~2]` 可选参数也泄漏为文本。`\cite\ref\eqref\autoref\cref\pageref\label` 有签名 (o m / s m / d<> o m) → key 正确隔离 |
| T05 | `\section[Short]{Long}` | pass | 4 args 挂载 `s d<> o m`, 长标题 arg 可提取 |
| T06 | verbatim/lstlisting 内 % | pass(注意) | `verbatim` env→`verbatim` 节点原样保护; `lstlisting`→`environment` 节点但 content 为原样字符串 `%` 完好——需按 env 名保护 |
| T07 | `\url{..%20..}` `\verb|a%b|` | **FAIL** | `\verb|a%b|` → `verb` 节点正确; 但 `\url` 的 `m` 参数是普通 group, **组内 `%` 仍当注释** → `a` 之后全被吞成行注释 (`20b%20c.pdf} now.` 成为 comment 节点), url 参数损坏为 `{`——静默数据损坏, 不报错 |
| T08 | 注释含不平衡 `{`/数学, `\%`, `\\%` | pass | 注释为 comment 节点不进可译块; `\%`→宏节点 `%`; `\\%`→`\\`+注释 (语义正确) |
| T09 | `\author[1]{..\thanks..\and..}` | info | `o m` 挂载; `\thanks` arg 挂, `\and` 裸宏; author 文本进可译块 (可配置行为) |
| T10 | subequations/align/flalign | pass | align/flalign→`mathenv`; subequations→普通 env 但内容仅包嵌套 align, 内部数学仍保护 |
| T11 | `\begin{theorem}[Main Result]` | pass | env `o` 签名挂上 `[Main Result]`, 正文可译 |
| T12 | caption 内 \footnote | pass | caption `o m` 参数内 footnote `o m` 参数嵌套可达 |
| T13 | `\ifdraft..\else..\fi` | pass | `\newif\ifdraft\drafttrue\else\fi` 全部裸宏不崩; **两个分支文本都会进可译块**——语义选择归管线 |
| T14 | \input/\include + 注释掉的 | info | 库不读文件; `\input`/`include` 有 `m` 签名可定位; 注释掉的 `\input` 在 comment 节点内安全; **展平须自写** (可用 arg position 做源码级替换) |
| T16 | `\NewDocumentCommand` | partial | 定义 `m m m` 挂载正确; 使用点 `\vect` 裸宏+`{v}`→`v` 泄漏; 且含 `#1` 的展开会崩 (§6) |
| T17 | 数学内 `\text{}` | pass | 整体在 inlinemath 内保护 |
| T18 | figure 内 \caption | pass | caption 文本可译, `\label` 保护, figure env 结构保留 |
| T20 | itemize/enumerate/description | pass | `\item` 签名 `d<> o d<>`, item 文本与 `[Term]` 都可取 |
| T22 | `\href{url}{text}` | pass | `o m m` 三参: url(arg1) 保护, text(arg2) 可译 |
| T23 | `\emph\textbf\textit` | pass | `m` 参数文本可译 |
| T24 | `\bibliography{refs}` | pass | `m` 参数保护 |
| T25 | `\makeatletter` 区 | pass | 区域内 `\@ifnextchar \@with \@without` 正确重切为 @ 宏名 |
| T26 | `\[ \]` `\(` `\)` `$$ $$` | pass | displaymath/inlinemath 节点, 无泄漏 |
| T27 | `\'e \"u \~n` | pass | 重音=单字符宏+后续字母不吞; printRaw 往返一致 |
| T29 | `\footnote` | pass | 文本可译 |
| T19 | abstract env | pass | 普通 env, 文本可译 |
| T21 | `\includegraphics[..]{..}` | pass | `s o o m` 参数, 路径保护 |
| T-209 | LaTeX2.09 (`\documentstyle`, `\def`, `{\bf }`) | partial | 不崩; `\documentstyle` 裸宏+孤儿 group `[epsf,seceq,preprint]ptptex` 泄漏; `\def` 同 T03; `{\bf bold}` 组内 `bold` 可译 (语义可接受) |
| T14-multi | 多文件展平 | info | `\input{sub/intro}` `\include{sub/methods}` 可定位; 注释的 `\input` 在 comment 节点; 展开自写 |

**计分**: 明确 pass 20 项; partial/info 7 项 (T02 T03 T09 T13* T14 T16 T-209, 其中 T13 不崩算过但无语义); **明确 FAIL 3 项: T01 (宏展开数学环境), T04 (natbib key 泄漏), T07 (\url{%} 静默截断)**。

## 4. 错误容忍: 不崩, 但会静默降级

全部畸形输入都"成功"解析 (最小复现见 ul_tricky.js 边缘测试):

| 输入 | 结果 |
|---|---|
| `\begin{a} x \end{b}` 不匹配 | 不崩; 退化为 `\begin`+`{a}` 裸宏+组, 环境丢失 |
| `$x^2` 未闭合 | 不崩; `$` 和 `x^2` 退化为普通字符串→**数学漏为文本** |
| `{` 未闭合 | 不崩; `{` 退化为字符串 |
| `\end{a}` 孤立 / `\verb|abc` 未闭合 / `a^b_c` / `a & b` / `\def\foo#1#2{..}` | 全部不崩, 字符串或裸宏降级 |

后果: **解析成功 ≠ 结构正确**。管线必须自检 (mathenv 之外出现 `^ _ = \begin{` 裸串即警报)。真实语料中确实发生: `2501.14787/psets/Pset1sol.tex:209` 原文 `$dx^T x = x^T dx` 尾缺 `$` (真·源码笔误), 被降级为文本——这是全语料唯一一个协议泄漏块。

## 5. Round-trip 保真

12 个主文件 parse→`printRaw`→diff: **0 identical, 0 normalized(按行), 12 diverged**。

差异性质 (逐字节实测):
- **所有单个换行折叠为空格** (whitespace 节点只存"有空白"不存内容), 段落变成一行; parbreak→`\n\n`, 注释前后换行重排, 注释 leadingWhitespace 归一化为单空格。
- **语义等价但非字节等价的归一化**: `\newcommand\mc{..}`→`\newcommand{\mc}{..}` (无括号宏名补括号), `$^1$`→`$^{1}$`, `\renewcommand\arraystretch{1.2}`→`{\arraystretch}{1.2}`, 未带参宏后补 `{}` 等。忽略全部空白后 10/12 文件仍不同 (差异全是此类 brace 归一化), 2/12 完全等价。
- 长度变化 ±2% 以内, 无内容丢失证据。

**结论: printRaw 不能用于区间重建**。但每个 PEG 节点 `position.start/end.offset` 精确 → 正确做法是**位置驱动重建**: 只对要替换的文本块做 printRaw/译文替换, 其余区间原样拷贝源码。argument 节点无 position 是缺口, 可用其 content 首尾子节点 offset (或 openMark 推断 `{x}` → -1/+1) 补齐。

## 6. 受限宏展开能力 (util-macros 实测)

- `listNewcommands(tree)` 找到 `\newcommand/\renewcommand/\providecommand` + 全部 `\NewDocumentCommand` 族定义 (tricky.tex: `be ee dR vect secretmacro`); **`\def` 不收** (TeX 原语, 无签名也无 AST 结构)。
- `expandMacrosExcludingDefinitions` + `printRaw` + **二次 parse** 后, `\be \wt{A}=\Tr(M^2) \ee` → 真 `mathenv:equation`, 内容 `\wt{A}= \Tr(M^{2})` —— **T01 可修**。一次展开不重排 AST 结构 (`\begin` 仍是宏+group), 必须过 printRaw 重新词法化。
- **两个坑**: (a) `expandMacros`(非 Excluding 版) 会把 `\newcommand{\be}` **定义点内的名字参数也展开**, 破坏定义——必须用 ExcludingDefinitions; (b) **替换体含 `#1` 即抛异常** (`\vect` → `Cannot read properties of undefined (reading 'charCodeAt')`, 因为 body 里 `#`/`1` 被 PEG 存成普通字符串而非 hash_number, `parseMacroSubstitutions` 预处理也修不好)——需逐宏 try/catch 跳过, 实测 5 宏中 4 个可展开。
- 展开 `\dR`→`\mathbb{R}` 在文本模式下 R 仍按文本泄漏 (真实 LaTeX 里 `\mathbb` 脱离数学模式本来就错, 属忠实)。

## 7. 签名表覆盖评估 (util-ctan)

- 覆盖: latex2e 全套 (`\cite o m` `\ref s m` `\label d<> o m` `\section s d<> o m` `\item d<> o d<>`, section 还有 `namedArguments: [starred,null,tocTitle,title]`), hyperref (`\href o m m` `\url m` `\autoref`), cleveref 20 宏, mathtools 55 宏+60 环境, xparse/listings/xcolor/tikz/beamer/exam/multicol 等。
- **缺失**: natbib 全家 (`citep citet citealp citeauthor citeyear citenum`), `\nameref`(hyperref 表里有 hyperref 其它项但无 nameref), ams 常用 (`\dfrac \intertext \boxed \overset \left \right \nonumber \tag`), booktabs (`\toprule \cline`), `\hline`, `\todo`, `\def \newif \if \else \fi \makeatletter \today \and \LaTeX \rm \bf \it`, `\includepdf \PassOptionsToPackage`。
- **注入验证**: `getParser({macros:{citep:{signature:'o o m'},citet:{..},nameref:{signature:'s m'},documentstyle:{signature:'o m'}}})` → `\citep[see][chap.~2]{key9}` 三个参数完整挂载, 真实语料 8/8 citep/citet 全挂。**natbib 修复=纯配置, 零代码改动**。
- 全语料"裸宏+孤儿 group"共 **2463 对**, top: `citep:232 bm:123 textsubscript:123 vec:93 citet:77 multirow:74 etens:54 mc:53 tens:52 hl:46 boxed:46 …`。其中数学/表格/导言区内的孤儿 group 无害 (父节点已保护); **真正有害的是文本区的 natbib key (310 处实测全部泄漏) + 自定义数学宏在文本中的使用**。

## 8. 泄漏率 (协议口径)

提取可译块 (ul_common.extractTranslatableBlocks: 跳过 math/verbatim/comment 节点与保护宏参数): 2287 块中协议正则命中 **1 块 (0.04%)**——Pset1sol.tex 的源码 `$` 笔误。**但协议正则测不到孤儿 key**: 310 个 natbib key 以无反斜杠裸文本形态混入可译块, 会被当普通词翻译。注入 natbib 签名后此泄漏归零 (实测)。

## 9. 对翻译管线的可复用性

**可直接用**:
- `parse()` 本体 + AST (90/90 鲁棒, 节点 type 体系干净: string/whitespace/macro/group/inlinemath/displaymath/mathenv/environment/verbatim/verb/comment/parbreak)
- **`position.offset` 区间重建** —— 比 printRaw 可靠得多, 是本库对我们的最大价值
- ctan 签名表 + `getParser({macros})` 注入机制 —— 自写一张 natbib/booktabs/amsmath/项目自定义签名表 (~50 行) 即解决 T04 与大部分孤儿 group
- `listNewcommands`+`expandMacrosExcludingDefinitions`+printRaw+re-parse 做受限展开 (救 T01), 加逐宏 try/catch
- `walk/visit/match` 工具包 + `printRaw` 用于块级序列化 (不做全文 round-trip)

**必须自写/加固**:
- **\input/\include 展平** (库无文件 IO) —— 用 arg position 做源码替换或独立 pre-pass
- **`\url{..%..}` / `\href{..%..}` 类**: group 内 `%` 仍当注释 → 参数静默截断。需在解析前用正则对 `\url`/`\verb`-arg 族做保护替换 (库无法用签名表达 verbatim-arg)
- **未知宏+后续 group 的兜底规则**: 文本区裸宏后跟 `{`/`[` → 保守保护整段 (防 natbib 类泄漏的通用网)
- **`\def` 识别** (T03): 裸宏序列 `\def \name {#n...} {body}` 模式自识别; 定义体不进可译块
- **降级自检**: 文本块含裸 `$ ^ _ = \begin{` 或孤立 `\begin/\end` 宏 → 标记"疑似数学泄漏" (覆盖未闭合 `$`、env-mismatch、宏展开 env 等所有降级路径)
- **`\if...\fi` 语义**: 两分支都会提取, 翻译哪支归管线决定
- mathenv 之外的数学 env 名清单 (subequations/eqnarray/IEEEeqnarray…) + verbatim env 名清单 (lstlisting/minted 的 node.type 不是 verbatim)

**改造工作量评估**: 管线可用的核心 = parse+AST+positions (零改造); natbib 修复 = 签名注入 (小时级); \be 类展开 = 已有工具串联+try/catch (天级); \url{%} 与 \def = 自写小 pass (天级)。**综合: 本库适合做解析底座, 但"拿来即用"会漏 natbib key、\be 数学与 \url 内容, 必须叠加上述加固层。**
