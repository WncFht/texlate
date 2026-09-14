# pylatexenc 深度评测报告

- 评测对象: **pylatexenc 2.11**(主) + **3.0b2**(对照),纯 Python,零依赖
- 环境: `bench/py/.venv` (Python 3.12);脚本 `bench/py/bench_pylatexenc.py`
- 数据: `results/pylatexenc-parse.json` (v2.11 全量), `results/pylatexenc3-parse.json` (v3.0b2)
- 语料: 90 个真实 arXiv `.tex`(12 个项目), fixtures/tricky*.tex

---

## 0. TL;DR

| 维度 | 结论 |
|---|---|
| tolerant 解析成功率 | **90/90(100%)** — 但"成功"无意义：容错模式把灾难静默吞掉 |
| strict 成功率 | 84/90;v3 同样 84/90(失败集合不同) |
| 速度 | 中位 11-16ms,最大 ~340ms(149KB),约 0.4-0.5MB/s,无超时 |
| pos/len round-trip | **90/90 字节级 identical**(区间切片重建，天然零损耗) |
| 陷阱断言 | 数学环境/引用家族/章节参数 OK;**`\be..\ee`、`\begin`-in-`\newcommand`、`\url/\href` 内 `%` 三处灾难性失败** |
| 泄漏率(参考提取器) | 0/2135 块命中字面泄漏正则 —— 但被吞文件可译产出趋近 0,字面泄漏率掩盖了真泄漏 |
| ieeA 弃用原因 | **验证成立**：容错模式静默吞噬 + 无 `\newcommand` 注册 + 签名表缺口，AST 提取器拿不到正确结构 |
| 可复用性 | **pos/len+latex_verbatim 可直接复用**；签名表思路可抄内容太浅；**建议自写 scanner,pylatexenc 最多作带损伤门控的备选** |

一句话：pylatexenc 给了我们最想要的东西(每个节点带 `pos/len`,`latex_verbatim()` 就是源切片，重建免费），但它的**单遍无展开解析 + `\begin` 贪婪环境识别 + 容错静默**三个架构决定叠加，会在 arXiv 最常见的一批惯用法上产出**结构性错误且无任何错误信号**的树。

---

## 1. 解析模型深读（v2.11 源码）

文件：`latexwalker/__init__.py`(2752 行）+ `macrospec/`(~1200 行）+ `latexwalker/_defaultspecs.py`(443 行）。

### 1.1 架构：单遍递归下降，不做宏展开

- `LatexWalker.get_latex_nodes(pos, stop_upon_*)` 是主循环；`get_token()` 读单 token(`char/macro/begin_environment/end_environment/comment/brace_open/brace_close/mathmode_inline/mathmode_display/specials`)。空白挂在下一个 token 的 `pre_space` 上，`\n\n` 是独立的 char token。
- 宏参数由 `LatexContextDb` 里的 `MacroSpec.args_parser` 驱动；**未知宏回退 `MacroSpec('')`=0 参数**，后面的 `{...}` 变成裸 `LatexGroupNode`——这是"参数落进裸组"模式的根源，后面所有 nameref/href/caption/thanks 泄漏都是它。
- `\begin{X}`/`end{X}` 在 `get_token` 里**硬编码识别**（正则 `[\w* ._-]+` 匹配环境名），签名表只能改"环境是否数学模式/有什么参数",**无法关闭 `\begin` 的环境语义**。
- 节点：`LatexChars/Comment/Macro/Group/Environment/Specials/Math` 七种，每个都有 `pos/len/parsing_state`,`latex_verbatim()` ≡ `s[pos:pos+len]`。

### 1.2 错误容忍的真实语义（重点）

`LatexWalker(s, tolerant_parsing=True, strict_braces=False)`（默认）。所谓 strict 只有 `tolerant_parsing=False`（没有叫 `strict_mode` 的开关）。

容错模式的恢复机制分两层，**其中一层有致命黑洞**:

1. 中途错误（括号不匹配、`\end{env}` 不预期、环境名不匹配）→ `LatexWalkerParseError` → `_report_ignore_parse_error` → `logger.info` 记录后**跳过该 token 继续**。有日志可查。
2. **EOF 截断无信号**:`do_read()` 里 `except LatexWalkerEndOfStream → return e`(把异常当返回值），而外层 while 循环里"期望 `}`/`\end{env}` 却遇到 EOF"的错误分支只在 `do_read` raise 时才执行——tolerant 下永远走不到。**组/环境/数学未闭合吞到 EOF 时，零错误、零日志**。实测 `a {b % c} d` 全文被吞进组，`logger` 一条都没有。

这就是为什么 ieeA 的 `validate_assumptions.py` 里 `pylatexenc_success_rate: 10/10` 是假象——**它不崩，但它安静地撒谎**。

### 1.3 `new_parsing_state` 钩子（v2 的"半展开"残桩）

`do_read` 宏分支里：`margsresult` 若返回 4 元组，第 4 个 dict 的 `'new_parsing_state'` 会替换当前 `p.parsing_state`——这是**唯一的状态推进钩子**。但默认签名表**没有任何宏用它**：`\newcommand` 只按 `*{[[{` 解析参数，**不注册**（实测解析后 `ctx.get_macro_spec('vect')` → None)。

我们自己验证了这个钩子可用（`bench_pylatexenc.py::check_newcommand`，约 40 行）：自定义 `newcommand` 参数解析器从 argnlist 抽宏名+参数个数，`filter_context()` 复制 db、`add_context_category(prepend=True)` 注册新 `MacroSpec`,`sub_context(latex_context=...)` 生成新 parsing_state 返回——此后 `\vect{v}` 正常拿到 1 个参数。**机制在、默认空**，这就是任务里说的"半展开"残桩。

### 1.4 默认签名表覆盖（`_defaultspecs.py`)

~110 宏 / ~40 环境 / 8 specials，分类：latex-base、nonascii-specials、verbatim、theorems、enumitem、natbib、latex-ethuebung（一堆德语作业宏）。

- **有的**:natbib 全族(`cite/citep/citet/citealp/citeauthor/citeyear...` `*[[{`)、`\section` 系 `*[{`、`\newcommand` 系、数学环境（equation/eqnarray/align/gather/flalign/multline/alignat/split+星号版，`is_math_mode=True`)、定理环境 `[`、enumitem、`verbatim` 环境+`\verb`、`includegraphics`/`\input`/`\include`/`bibliography`、重音命令(`'` `"` `~` `c` `v` 等 1 参）、`~`/`&`/``--``/``---``/``` ``/``''`` specials。
- **缺的（实测影响）**:`caption`、`href`、`pageref`、`nameref`、`thanks`、`bibliographystyle`、`lstlisting`、`minted`、`algorithm`/`algorithmic`、`bmatrix`/`pmatrix`/`cases`/`subequations`/`IEEEeqnarray`、`\def`、`\url` 有签名但是**普通 `{` 参数**（不是 verbatim 读取，灾难见下）。还有 `std_macro('pagagraph',...)` 拼写错误——paragraph 环境在 v2.11 里其实没签名。
- `verbatim` 环境的 `VerbatimArgsParser` 是**硬编码 `s.find(r'\end{verbatim}')`**——只认这一个环境名，`verbatim*`/`lstlisting`/`minted` 都不沾边。

### 1.5 v3.0b2 的差异（简评）

重写为 `latexnodes` 层（token reader + node collector + `parse_content`)。关键改进：

- `href`/`url` 参数用 `LatexDelimitedVerbatimParser` —— **`%` 在 URL 里的灾难根治**(lectures 系列文件 strict 全过）。
- 新增 `lstlisting` 环境 verbatim body parser;`href` 签名（url verbatim + text 普通参）;`paragraph` 拼写修正；`^`/`_` 成为数学感知 specials;`LatexNodesLatexRecomposer` 序列化器（实测 normalized：仅段间空行归一，其余字节一致）。
- `ParsingStateDelta` 体系（`DeltaExtendLatexContextDb` + `make_after_parsing_state_delta`）是**正式版**的半展开钩子，`extended_with()` 文档原话"behaves as you'd imagine immediately after issuing a `\newcommand`"——但**默认 `newcommand` 依然不接这个钩子**(v3 实测 `\vect{v}` 仍 0 参数）。
- 兼容层 `get_latex_nodes()` 会丢 `info`（解析态变更报告）并打 warning。
- **架构级缺陷原样保留**:`\begin`-in-def-body 吞噬在 v3 完全复现（iclr2016 top_chars=29/41199)。

---

## 2. Corpus 实测

### 2.1 解析鲁棒性

| | v2.11 | v3.0b2 |
|---|---|---|
| tolerant 成功 | 90/90 | 90/90 |
| strict 成功 | 84/90 | 84/90 |
| 中位/最大耗时 | 11.5ms / 337ms | 15.7ms / 282ms |
| 超时（30s) | 0 | 0 |

v2.11 strict 失败（6):iclr2016(`\newcommand` 参数里 `\begin{bmatrix}`)、lectures 04/06/10/12（全是 `\href{..%xx..}` 注释吃括号到 EOF)、Pset1sol（源文件 `\begin{multline*}`/`\end{multline}` 真笔误，LaTeX 也救不了）。

v3 strict 失败（6，不同集合）:iclr2016（同因）、2501 main(`\renewcommand` 参数严格化）、lectures 01/07(`\frac` 期望表达式遇 `}`)、Pset1sol（同源笔误）、hep-th/9901001(2.09 文件 `\newcommand` 参数）。**v3 修好了 `%`-in-URL，但对 def 参数/`\frac` 更挑剔**。

### 2.2 静默吞噬（tolerant 模式的真伤害）

按 AST 实测签名（环境节点出现在宏参数/裸组子树且 >2KB 或到 EOF；组未闭合到 EOF):

| 文件 | 机制 | 吞噬量 |
|---|---|---|
| `1511.06432/iclr2016_conference.tex` | `\newcommand{\bmx}{\begin{bmatrix}}` → 假 bmatrix 环境 | **40326/41199 = 97.9%,到 EOF** |
| `lectures/04-FiniteDifferences` | `\href{...Finite%20difference...}{...}` | **14648/14699 = 99.7%,到 EOF** |
| `lectures/06-RootFinding` | 2 处 `\href{...%27/%3A..}` | **~95%,到 EOF** |
| `lectures/10-CalculusofVariations` | `\href{...%E2%80%93..}` | 11.1% |
| `lectures/12-Hessian` | `\href{...%E2%80%93..}` + `\todo{` 未闭合组 | ~12%(v2 检测器漏报：文件以 `}` 结尾） |
| `Pset1sol` | `multline*`/`\end{multline}` 源笔误 | 局部 |
| `1906.08237/custom.tex` 等 | `\begin{pmatrix}`+`\end{pmatrix}` 同层在 def 体内 | **良性**（同一扫描层有 `\end`，环境正确闭合） |

**良性对照**也实测了：`\resizebox{..}{..\begin{tabular}..\end{tabular}..}`、`\newcommand{\tabincell}{\begin{tabular}..\end{tabular}}` 这类 `\begin/\end` 同在 def 体内的情况环境能正确闭合——**只有 `\begin` 的 `\end` 不在同一扫描层时才灾难**。residual_v1/1810 各表格文件里的 `tabular` 嵌组均属良性。

### 2.3 破坏机制总表（源码级）

| # | 机制 | 位置 | 触发 | 错误信号 |
|---|---|---|---|---|
| M1 | `\begin{X}` 在 `{}` 组内（含宏参）就开真环境，环境体扫描无视 `}` 边界，找不到同层 `\end{X}` 就到 EOF | `get_latex_environment` 内层 `get_latex_nodes(stop_upon_end_environment=X)` 不继承 `stop_upon_closing_brace`;`}` 在环境体内是"不匹配括号"容错跳过 | `\newcommand{\be}{\begin{equation}}`、`\bmx` | 中途有错会 log;**到 EOF 零信号** |
| M2 | `%` 在任何 `{}` 参数/组内变注释吃掉 `}`，组延伸到下一个 `}` 或 EOF | `get_latex_braced_group` 内注释 token 化 | `\url{..%..}`、`\href{..%20..}`（普通 `{` 参）、任何裸组内 `%` | **完全静默**(EOF 分支被 do_read 吞掉） |
| M3 | 未知宏 0 参，参数落进裸 GroupNode | `MacroSpec('')` 回退 | `\nameref{sec:a}`、`\href{u}{t}`(v2)、`\thanks{}`、`\caption{}` | 无（设计如此） |
| M4 | `\end{X}` 在组内被判"不预期"跳过，不闭合外层环境 | do_read `end_environment` 分支 | `\newcommand{\ee}{\end{equation}}` | log 有，语义已错 |
| M5 | 宏展开不存在：`\be..\ee` 是裸宏节点，数学内容碎成 chars+macros | 架构本身 | T01 | 无 |

### 2.4 Round-trip

`''.join(s[n.pos:n.pos+n.len] for n in nodelist)`:**v2.11 90/90 identical,v3.0b2 90/90 identical**。pos/len 是源切片，覆盖连续无缝隙——**重建保真与 AST 语义正确性解耦**，这正是区间重建管线需要的性质。

`nodelist_to_latex()`(v2 自带序列化）:**有损不可用**（环境边界、括号丢字节）。v3 `LatexNodesLatexRecomposer`:normalized（段间空行归一 `\n\n`)，可用。

### 2.5 可译块提取 + 泄漏率

参考提取器（`Extractor`:MathNode/保护宏/结构环境→占位符；`TEXT_ARG_MACROS` 最后一参、格式化宏、裸组递归→可译；注释跳过）:

- v2.11:**2135 块，字面泄漏 0/2135**(`$`/`\cite{`/`\ref{`/`\begin{` 正则）；前一轮把注释混入正文时 107 例"泄漏"全部是注释内容，排除后为 0。
- v3.0b2:711 块（`^`/`_` specials 化后块更少更聚合）,0 泄漏。

**但字面泄漏率为 0 掩盖了两类真泄漏**:

1. `\be..\ee` 展开的数学碎成 chars+宏混进可译流——没有 `$` 标记，正则抓不到（T01);
2. 吞噬文件产出崩塌：iclr2016 全文件被保护成一个占位符，**可译产出 237/41199 字符**(0.6%);lectures/04 靠组递归勉强榨出 12109/14699 字符但 url/锚文本已碎裂混排。

泄漏率指标的真正用法是"可译块里有没有保护失败的内容"——在 pylatexenc 上它测不出来，要用 **AST 损伤扫描**(2.2 节签名）当门控。

---

## 3. Fixtures 逐条断言

注意：tricky.tex 本身含 T01 的 `\newcommand{\be}{\begin{equation}}`,**整个 fixture 从 pos 540 到 EOF 被一个假 equation 环境吞掉**——下面每条是隔离验证后的真实结论。

| ID | 期望 | 实测 verdict | 细节 |
|---|---|---|---|
| T01 | `\be..\ee` 整体保护 | **FAIL（双杀）** | 定义侧：`\begin{equation}` 在 def 体内开真环境→吞到 EOF(M1)；使用侧：`\be \wt{A} = \Tr(M^2) \ee` → `Macro(be)+Macro(wt)+Group+Chars(' = ')+Macro(Tr)+Chars('(M^2) ')+Macro(ee)`，数学碎进文本流（M5) |
| T02 | `\dR` 保护 | 半过 | 裸 MacroNode 无参；`$..\dR..$` 里随数学保护；正文中 `\dR{}` 是宏+组可保护，但"它是数学"无从知晓 |
| T03 | `\def` 识别为定义 | 半过 | `def` 不在表→0 参宏，`\wt` 独立宏节点，`{\widetilde}` 裸组；def 关系丢失但不崩、内容不外翻 |
| T04 | cite/ref key 不入可译块 | **部分 FAIL** | natbib 全族 `*[[{`/`[[{` 参数形状正确（`\citet[see][chap.~2]{kingma2015}` 两可选参都在）;`\ref\eqref\autoref\cref\label` OK;**`\pageref`/`\nameref` 无签名→0 参+裸组，`{sec:a}` key 落进可递归裸组=泄漏**(M3) |
| T05 | 长标题可译 | PASS | `*[{` → opt=`[Short]`,mand=长标题，`\section*` 星号在 argnlist[0](CharsNode '*') |
| T06 | verbatim/lstlisting 保护 % | 半过 | `verbatim` 环境：`VerbatimArgsParser` 硬编码 find `\end{verbatim}`,verbatim_text='100% real data' ✓;`lstlisting` 无签名→普通环境，`code%with%percent` 内部 tokenized 成 chars+CommentNode（环境整体仍保护，但 `%` 误分类；若 `\end` 与 `%` 同行则 EOF 吞） |
| T07 | `\url{..%..}` `\verb|a%b|` | **FAIL / PASS** | `\url` 是普通 `{` 参→`%` 吃掉 `}`→组吞 ~950 字符到 EOF(M2，实测 node_len=954);`\verb|a%b|` → verbatim_text='a%b' ✓ |
| T08 | 注释边界 | PASS | 注释内不平衡 `{`/数学不影响；`\%` 宏 ✓;`\\%` 中 `\\` 走 `optional_arg_no_space` 签名，`%` 正确开注释 |
| T09 | author 保护/可配 | 半过 | `author` 签名只有 `{` → `\author[1]` 的参=单字符 `'['`(!),`1]` 成字符流，`{Alice..\and Bob}` 裸组可经组递归取出——形状全错但文本可达；`\thanks` 同样 0 参+裸组 |
| T10 | subequations/align/flalign | PASS | subequations 无签名但内嵌 align 是 `is_math_mode` 环境，嵌套保护成立；flalign 在表 |
| T11 | theorem[opt] | PASS | `theorem` 签名 `[`,optarg='Main Result'，正文 chars 可译 |
| T12 | caption 内 footnote | 半过 | `caption` **无签名**→0 参+裸组（文本可经组递归取，但 caption 身份丢失）;`footnote` `[{` → `{computed by hand}` 可译 |
| T13 | `\ifdraft..\else..\fi` | PASS（加分） | 三个都按未知宏处理，中间文本是普通 chars 可译；条件不求值（两支都收） |
| T14 | input 展平+注释 input 不展开 | PASS（分工） | `\input{sub/intro}`/`include` 参数给文件名，**不读文件**（展平是我们的活）；注释掉的 `\input` 在 CommentNode 内，正确不可见 |
| T16 | NewDocumentCommand | PASS- | 0 参+3 裸组；不崩，但定义体 `\mathbf{#1}` 进裸组，组递归会摸到 `#1` 垃圾文本 |
| T17 | 数学内 `\text{}` | PASS | 在 MathNode 内，`text` 的 `{` 参 `{if and only if}` 随数学保护 |
| T18 | figure 内 caption | 半过 | figure `[` 签名在；caption 同上，可经组递归但无标记 |
| T20 | 列表 | PASS | itemize/enumerate/description `[` 环境签名，`\item[Term]` 的 opt='[Term]'，文本 chars 可译 |
| T22 | href url 保护/text 可译 | **v2 FAIL / v3 PASS** | v2:`href` 无签名→0 参+2 裸组，**url 进可译组=泄漏**;v3:url 是 verbatim 参、text 是普通参，正确 |
| T23 | emph/textbf/textit | PASS | 全部 `{` 参，内部文本可译 |
| T24 | bibliography | PASS | `\bibliography{refs}` 有参；`\bibliographystyle` 0 参+组，不崩 |
| T25 | makeatletter | PASS | `\@ifnextchar` → 宏 `'@'`+chars `ifnextchar`，怪但不崩 |
| T27 | 重音 | PASS | `\'e`→宏`'`+单字符参 `e`,`\"u`,`\~n` 同 |
| T19 | abstract | PASS | 环境在表 |
| T21 | includegraphics | PASS | `[{` 签名 |
| T26 | `\[..\]` `\(..\)` `$$` | PASS | LatexMathNode displaytype=display/inline;`$$a$$` 有 `math_mode_delimiter` 消歧 |
| T29 | footnote | PASS | `[{` 签名 |
| T209 | LaTeX 2.09 | 半过 | `\documentstyle` 0 参+`[epsf..]` chars+组；`\def` 0 参；`\beq \Im z \eeq` 同 T01 碎裂；不崩 |

---

## 4. ieeA 弃用原因验证

证据链（`/Users/fanghaotian/src/ieeA/`):

1. `src/ieeA/parser/chunker.py` 文件头：**"DEPRECATED: This module is not currently used. The main parser is latex_parser.py which uses regex-based parsing."** —— pylatexenc AST 方案被 regex 方案正式替换；`pyproject.toml` 里 pylatexenc 还留着但只剩 `scripts/validate_assumptions.py` 当"能否 parse"指标用（`pylatexenc_success_rate: 10/10` 是个假指标，见 §1.2)。
2. chunker 里的挣扎原话："pylatexenc doesn't easily give us 'macro without arg 1'"、"This is getting complex to reconstruct perfectly"、"The Chunker must preserve EVERYTHING"、对 `\section*` 形状的不确定——**AST→重建的摩擦**是表面原因。
3. 深层原因（本次实测坐实）:
   - **静默吞噬**:iclr2016 式 `\bmx` 定义把 98% 文件藏进一个宏参子树，AST 提取器取出的可译文本只剩零头，且**没有任何错误信号可查**(tolerant 下 EOF 截断连 logger 都没有）——"parse 成功但提取全错"正是会让人弃坑的体验；
   - **`\be..\ee` 这类 arXiv 第一大惯用法两头输**：定义处开假环境吞文档，使用处数学碎进文本；
   - **签名表缺口**:`caption/href/pageref/nameref/lstlisting/bmatrix/subequations` 全缺，参数落裸组，引文 key/URL 混进可译流；
   - **无 `\newcommand` 注册**：任何自定义宏的参数个数都不知道，`\vect v` 和 `\vect{v}` 的边界只能靠裸组猜。

结论：**ieeA 弃用 pylatexenc 是正确的决定，而且原因不是"重构麻烦"，是它在真实 arXiv 文件上的结构性错误是静默的、无法靠配置消除的。**

---

## 5. 对我们"段落提取+占位+区间重建"管线的可复用性

### 5.1 可以直接用的

- **`pos/len` + `latex_verbatim()`**:90/90 字节级 identical，区间重建零成本——这是 pylatexenc 唯一无可替代的资产。
- **`LatexContextDb`/`MacroSpec` 机制**：参数形状声明式（`*[[{` 迷你 DSL)，自定义 args_parser 可以返回 `new_parsing_state` 推进上下文——**我们验证了 40 行代码就能实现 `\newcommand` 注册**，v3 还有正式的 `DeltaExtendLatexContextDb`。
- `LatexWalkerParseError.open_contexts`（错误上下文栈）设计可参考。

### 5.2 不能靠配置解决的（架构负债）

- `\begin`/`end` 硬编码在 tokenizer，组内 `\begin` 贪婪开环境——**唯一修法是给 `newcommand`/`def`/`\renewenvironment` 等写"定义体按原文吞"的自定义参数解析器**(~30 行，把 body 当 verbatim 读），再加上 `\if`/`\ifthenelse` 等场景只能祈祷；
- 宏不展开是设计前提，`\be..\ee` 类"宏界数学"只能靠**自己先扫 `\newcommand` 定义体、建 opener/closer 注册表**再去保护使用点——pylatexenc 不帮忙；
- EOF 静默截断无错误信号——**必须外挂损伤扫描**(env-in-arg-subtree、组到 EOF 未闭合、注释内含 `}{` 三个签名，~80 行）当质量门；
- 签名表缺口：caption/href/pageref/nameref/lstlisting/minted/bmatrix/subequations/IEEEeqnarray/`\def`——**补丁容易（每行一个），但说明这张表本来就是"常见教科书命令"级别，不是 arXiv 实战级别**;
- `\input/\include` 只给参数不展平——展平本来就该我们做（注释里的 `\input` 正确不可见这点倒是白送的）。
- `LatexNodes2Text`：输出纯文本丢全部位置信息，`\be` 未知→内容照样漏成文本——对重建管线无用。

### 5.3 结论

- **AST 直接可用？否。** tolerant 模式 100% "成功"与结构性正确无关；要用必须同时上：签名表增补（~15 条）+ newcommand/def verbatim-body 参数解析器 + url/href verbatim 参数解析器（v2 需自写，v3 自带）+ 损伤扫描门控 + 宏界环境 opener/closer 预扫描。这套补丁的复杂度≈自写 scanner 的一半，但**剩下的 M1/M2 静默吞噬风险依然无法证明消除**——它是对抗一个"默认信任 AST"的架构。
- **签名表可抄？思路抄，内容只作种子。** `*[[{` 参数 DSL、按参数索引标记可译位、verbatim 参数解析器的设计都值得抄进我们自己的 scanner；natbib/theorem/amsmath 覆盖可以直接搬成我们签名表的 v0。
- **建议**：主链路自写 scanner/分段器（区间天然是我们的产物，不依赖第三方 AST 正确性）；若保留 pylatexenc，只作为"带损伤门控的备选解析器"或宏参数级工具，且**只用 v3.0b2+**(verbatim args、lstlisting、recomposer、正式 delta 钩子），v2.11 不建议上新代码。
