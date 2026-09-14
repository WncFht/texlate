# latex-utensils 评测报告

- **版本**: 7.0.0(`~/src/texlate/bench/ts/node_modules/latex-utensils`)
- **维护者**: tamuratak — VS Code LaTeX-Workshop 的 LaTeX 解析器
- **实现**: Peggy(PEG.js 后继)文法编译出的递归下降解析器，纯 JS，零 native 依赖
- **代码量**: 生成的解析器 `out/src/latex/latex_parser_simple.js` 约 8600 行；另有 trace 版、`bibtexParser`、`latexLogParser`
- **入口**: `latexParser.parse(src, {timeout, enableComment, startRule})` → 抛 `SyntaxError` 或返回 `{kind:'ast.root', content:[...]}`
- **评测脚本**: `bench/ts/bench-lu.js`；数据 `bench/results/latex-utensils-{parse,traps,roundtrip,leak}.json`

## 1. 语料鲁棒性（corpus/ 全部 90 个 .tex)

| 指标 | 值 |
|---|---|
| 解析成功 | **89 / 90(98.9%)** |
| 失败 | 1:`2501.14787/psets/Pset1sol.tex` — SyntaxError @L223 |
| 总耗时 | 1306ms(90 文件，含 JIT 预热） |
| 中位 / p90 / 最大 | 4.56ms / 45.78ms / 144.35ms(usecases-if.tex;149KB 的 neurips_2021.tex 仅 ~26ms) |
| 超时 (>30s) / 慢 (>500ms) | 无 / 无 |

**唯一失败文件的根因**:Pset1sol.tex 第 209 行末尾 `$dx^T x = x^T dx.` **少一个闭合 `$`**——全文非转义 `$` 共 417 个（奇数），是真·源文件缺陷（arXiv 上确实存在的脏数据）。latex-utensils 的报错是正确的，但报在 **L223 col 2**(`\end{enumerate}` 处），离真实故障点 L209 差 14 行：PEG farthest-failure 报的是"最后一个备选死在哪"，不是"哪里开始错"。**对管线含义：错误位置不可直接信任，需自行二分定位或用降级策略。**

LaTeX 2.09 旧格式（`hep-th/9901001/imamura2.tex`、fixture tricky-209)**解析正常**——`\documentstyle`/`\def`/`{\bf ...}` 都不在话下（`\def` 甚至有专用 `command.def` 节点）。

## 2. 陷阱断言（fixtures/tricky.tex,26 项）

**24 PASS / 2 PART / 0 FAIL**。逐项见 `latex-utensils-traps.json`，要点：

| ID | 结果 | 实测行为 |
|---|---|---|
| T01 `\be/\ee` 宏展开数学环境 | **PART** | `\newcommand{\be}{\begin{equation}}` 解析为普通 command（正确）；但使用点 `\be \wt{A} = \Tr(M^2) \ee` **不被识别为数学**——无宏展开器，`= \Tr(M^2)` 以 text.string 泄漏为"可译文本"。**这是本库最大的语义盲区** |
| T02 `\dR` | PASS | 定义=command；在 `$...$` 内是受保护数学内容；裸文本处是普通命令 |
| T03 `\def` | PASS | 专用节点 `command.def`(token + args)，可精确排除 |
| T04 natbib+ref 全族 | **PART** | `\citep\citet\citealp\citeauthor\citeyear` = **普通 command**,key 是 arg.group 里的裸 text.string（与可译文本同构，naive 提取必漏）；`\ref\eqref\autoref\cref` 有专用 `command.label` 节点（label 字段）,**但 `\pageref\nameref` 不在文法白名单**，也是普通 command |
| T05 `\section[Short]{Long}` | PASS | args=[arg.optional, arg.group]，长标题=text.string 可译 |
| T06 verbatim/lstlisting 单行含% | PASS | 专用 `env.verbatim`/`env.lstlisting`,content 为原样字符串，% 不当注释 |
| T07 `\url{..%20..}` `\verb\|a%b\|` | PASS | 专用 `command.url`(url 字段保留 %20)、`verb` 节点（escape+content) |
| T08 注释边界 | PASS | 注释不译且含不平衡 `{`/数学也不崩；`\%`=command '%',`\\%`=linebreak+comment |
| T09 `\author[1]{…}` | PASS | 普通 command;author 姓名是 group 内 text.string——**结构上与可译文本无区别，需策略表保护** |
| T10 subequations/align/flalign | PASS | align/flalign=`env.math.align`（受保护）,subequations=generic env 包裹 |
| T11 theorem[Main Result] | PASS | generic env + arg.optional，正文 text.string 可译 |
| T12 caption 内 footnote | PASS | footnote 参数 text.string 可提取 |
| T13 `\ifdraft…\else…\fi` | PASS | 不崩；分支内文本保持 text.string（可译） |
| T14 `\input` | PASS（管线侧） | 普通 command(name=input)；注释掉的 \input 进 comment，不进 content——展平器可安全区分 |
| T16 `\NewDocumentCommand` | PASS | 普通 command;`#1`=commandParameter 节点（非文本，不泄漏） |
| T17 `\text{}` 在数学内 | PASS | 专用 `command.text` 节点（在 inlineMath 内） |
| T18 figure 内 caption | PASS | figure=generic env 保留；caption 参数 text.string 可译 |
| T20 itemize 等 | PASS | generic env + `item` command;text.string 是**词级 token**("First" "item" 分开），提取器按序拼接即可 |
| T22 `\href{url}{text}` | PASS | 专用 `command.href`:url 字段保护 + content 节点数组可译——**理想形状** |
| T23 `\emph\textbf\textit` | PASS | 普通 command,args 内 text.string 可译 |
| T24 `\bibliography` | PASS | 普通 command，不崩 |
| T25 `\makeatletter` | PASS | `@`-宏正常解析为 command(name 含 @) |
| T26 `\[ \]` `\(` \)` | PASS | displayMath + inlineMath 正确分类 |
| T27 `\'e \"u \~n` | PASS | 重音=command(name=`'` 等）+后续字符，不崩 |
| T29 footnote 独立 | PASS | 参数 text.string 可译 |

## 3. Round-trip 保真（parse → stringify → 对比原文）

`latexParser.stringify` 存在但**不追求保真**,90 文件分级：

| 级别 | 数量 | 说明 |
|---|---|---|
| identical | 1 | |
| normalized(-nocomments) | 3 | 仅空白差异（去注释后） |
| ws+comment+par-only | **56** | 剥掉注释+`\par`+全部空白后逐字节相同——**无 token 级内容丢失** |
| math-delim-style | 0(并入上行） | `$$`→`\[`、`\(`→`$` 改写会被 delim 归一化吸收 |
| **serializer-bug** | **22** | **`command.text` 序列化为 `[object Object]`**——`stringify` 对 `\text{}` 分支直接拼接 `node.arg`(Group 对象）而非递归序列化，**是真 bug**:`'\text{' + node.arg + '}'`(out/src/latex/stringify.js:46) |
| diverged | 7 | 深度归一化后仍有差异：`\\` 在表格中被写成 `{\\}`、tabular 重排等 |
| parse-error | 1 | Pset1sol（源文件坏） |

**结论：不能用 stringify 做区间重建。**注释默认不进 AST(`enableComment` 后挂在 root.comment 列表，但 stringify 无 comment 分支）；空白/缩进/空行全部被重写（parbreak→`\par`)。管线应走"**原文 offset 切片 + 占位符**"方案——latex-utensils 的每个节点都带 `{start:{offset,line,column},end}`，完全够支撑。

## 4. 泄漏率（提取器视角）

naive 提取（收集所有 text.string):124675 个词中 **3713 个（约 3%）位于受保护子树**——cite key(`extendedngpu<-citep`)、`\documentclass`/`\usepackage` 参数、includegraphics 路径、`\text{}` 内文本、数学内字符。即"抓 text.string"这种最朴素的用法会把 ~3% 的保护内容送进翻译器。

用**策略表提取器**(PROTECTED_CMDS 名单跳过参数、TRANSPARENT_CMDS 递归进参数、parbreak 切段、保护 env/math 跳过）在 89 个可解析文件上产出 **1424 个可译块，残余泄漏 0 块**。策略表 ~40 行正则即可覆盖语料。

## 5. 架构分析

- **文法**:PEG，有序选择 + 无限回溯 + 表达式级记忆化。硬编码白名单：数学环境名（`equation/align/...` 两组 → `env.math.align`/`env.math.aligned`)、特殊命令（label/ref/eqref/autoref/cref、url、href、verb、def、text)、trivia 环境（verbatim/minted/lstlisting/comment)。**白名单外的命令/环境统一走 generic command/env 规则**——这是它鲁棒的根源（未知命令永远不致命），也是 T04 `\pageref` 漏分类的根源。
- **错误处理 = 没有**。任何语法违例直接抛 peggy SyntaxError,farthest-failure 报位，无部分 AST、无恢复。配套提供 `timeout` 选项（解析中周期性查表）防病态输入卡死——实测语料最快 0.4ms、最慢 144ms，远未到需要它的程度。
- **AST 形状**：扁平 children 列表，语义靠 `kind` 标签区分；词级 text.string + space/softbreak/parbreak 显式节点；`arg.optional`/`arg.group` 区分 `[]`/`{}`；数学内部也是结构化节点（math.character/superscript/subscript/matching_delimiters)。
- **工具**:`find/findAll/findAllSequences/findNodeAt`(find_all.js)、`pattern` DSL(matcher.js)、`stringify`（有损，见 §3)。
- **输入边界**：单文件，不展开 `\input`、不展开宏、不做 catcode。语义上限 = "语法树 + 少量命令特判"。

## 6. 对本管线（段落提取+占位符保护+区间重建+AST 校验）的可复用性

| 角色 | 适配度 | 说明 |
|---|---|---|
| **段落提取器** | ✅ **主力候选** | 语义化 kind + 精确 offset，策略表 ~40 行即可做保护/透明决策；`env.math.*`/`inlineMath`/`displayMath`/`verb`/`verbatim` 天然就是占位符边界 |
| 占位符保护 | ✅ | 命令级位置 → 直接切片原文 |
| 区间重建 | ⚠️ | 用 location.offset 切原文，**不要**用 stringify |
| AST 校验 | ⚠️ | 可做"翻译后文本是否仍是合法 text.string 序列"的弱校验；整文档 re-parse 校验不行（翻译后文本不一定合法 LaTeX) |
| 鲁棒性兜底 | ⚠️ | 无恢复：遇 Pset1sol 式脏文件整篇失败，需预检（如 `$` 配平扫描）或按行/段降级 |

**必须自己补的三件事**:
1. **命令策略表**——`\cite*/\ref*/\label/\url/\includegraphics/\author` 参数=保护，`\emph/\textbf/\footnote/\caption` 参数=透明。库不区分，全看调用方。
2. **`\input/\include` 展平器**——command name 匹配 + 注释排除（comment 节点天然帮你跳过注释掉的 \input)。
3. **宏展开盲区（T01）决策**——`\newcommand{..}{\begin{env}}` 半边宏在 arXiv 常见（iclr2016 语料就有 `\bmx/\emx`)。latex-utensils 不展开 ⇒ `\be ... \ee` 会漏成文本。**可选**:pre-scan `\newcommand` 表 + 源级宏替换（我们自己的展平层做，不贵）,或接受该泄漏。

**改造成本**：作为提取器几乎零改造（API 直给）；把 stringify 修到可用（\text bug + comment 回写）也就几十行，但重建路线本来就该走原文切片，不建议投。

**一句话**：目前 TS 侧最适合当"提取器"的库——真实 arXiv 语料 98.9% 成功率、毫秒级、AST 语义粒度正好卡在"段落/数学/命令"这一层，加上一张命令策略表就能上线；短板是无错误恢复（脏文件全篇拒识）和宏展开盲区。
