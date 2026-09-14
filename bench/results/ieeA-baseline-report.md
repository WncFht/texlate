# ieeA 解析器基线评测报告

- **库**: ieeA (zcyisiee/ieeA)，本地源码 `~/src/ieeA`，git `04f3cb0`，安装版本 `0.0.post129`(editable 装入 `bench/py/.venv`)
- **被测入口**: `ieeA.parser.latex_parser.LaTeXParser.parse_file(path)` → `LaTeXDocument`; 重建 `doc.reconstruct(translated_chunks)`(与 `cli.py` 生产路径一致；`parser/chunker.py` 的 pylatexenc AST 实现已标记 DEPRECATED，不测)
- **数据**: `bench/results/ieeA-parse.json`;脚本 `bench/py/ieeA_bench.py`
- **日期**: 2026-09-14

## 1. 一句话结论

纯 regex + 括号计数的手写解析器:**永不崩溃**(93/93 成功）但语义理解薄——宏展开、natbib 全族、可选参数、verbatim/url 内 `%` 全部失守；重建管线存在**嵌套占位符顺序 bug**,10 个语料文件的最终输出残留 `{{CHUNK_uuid}}` 死 token 并丢失对应 caption 译文。可译块泄漏率 **10.24%**。

## 2. 语料解析鲁棒性 (PROTOCOL §1)

| 指标 | 值 |
|---|---|
| 文件总数 | 93(90 corpus + 3 fixture) |
| 成功 | **93/93 (100%)** |
| 失败/超时 | 0(30s 阈值远未触及） |
| 耗时 | min 15.9ms / 中位 22.6ms / p95 105.8ms / max 740.3ms(2501.14787/main.tex,递归展平 15+ 文件） |
| 总 wall | 5.6s |

零崩溃是 regex 方案的天然属性：任何不认识的构造都按"普通文本"放过。每次 `parse_file` 会 fork 一次 `fc-list :lang=zh` 探测 CJK 字体（无缓存）,~15ms 底噪由此而来。

## 3. Fixtures 陷阱断言 (PROTOCOL §2)

tricky.tex 实测矩阵（pass 16 / partial 3 / **fail 7**):

| ID | 构造 | 结果 | 证据 |
|---|---|---|---|
| T01 | `\be…\ee` 宏展开公式环境 | **FAIL** | `\be \wt{A} = \Tr(M^2) \ee` 原样进入 paragraph chunk（不展开 `\newcommand`，看不见背后是 equation) |
| T02 | `\dR` 自定义数学宏 | **FAIL** | `\dR{}`、`\vect{v}` 以裸文本留在 chunk，翻译模型可直接破坏 |
| T03 | `\def\wt` | PASS | 在 preamble，原样保留（但靠的是位置而非识别 `\def`) |
| T04 | natbib 全族 + ref 族 | **FAIL** | 白名单仅 `\cite \ref \eqref \label \url \href`;`\citep \citet \citealp \citeauthor \citeyear \autoref \cref \pageref \nameref` 连同 key(`vaswani2017` 等）全部进入可译块 |
| T05 | `\section[Short]{Long}` | **FAIL** | 正则 `\\section(\*?)(\s*\{)` 不支持可选参数 → 长标题留在模板里**永不翻译** |
| T06 | 单行 verbatim 含 `%` | **FAIL** | `_remove_comments` 先于环境保护运行 → `100% real data\end{verbatim}` 中 `%` 之后全被删，`\end{verbatim}` 消失、env 不闭合（多行 lstlisting `code%with%percent` 幸存） |
| T07 | `\url{..%20..}` `\verb\|a%b\|` | **FAIL** | 同根因：`%` 被当注释 → 输出残留断掉的 `\url{http://example.com/a`、`\verb|a`(**产物不可编译**);`\url{` 括号计数找不到闭包后回退保留字面量，未吞掉后续文本 |
| T08 | 注释边界 `{`/数学/`\%`/`\\%` | PARTIAL | 整行与行尾注释正确剥离、`\%` 保留、不崩；但 `\\%` 被误判为转义百分号 → 其后注释文本 "followed by real comment" 进入可译块 |
| T09 | `\author[1]{…\and…}` | PASS | 位于 preamble 不译（注：`_protect_author_block` 的 `\\author\s*\{` 不支持 `[1]`，若在正文区会漏） |
| T10 | subequations/align/flalign | PARTIAL | `align` 在保护清单 → `[[ENV]]`;`subequations`、`flalign` **不在**清单，env 与内容仅以字面行幸存（`x &= y` 凑巧 <20 字符不成 chunk；行稍长即泄漏） |
| T11 | `theorem[opt]` | PASS | 正文成 chunk,env 行保留 |
| T12 | caption 内 `\footnote` | PASS | footnote 文本随 caption chunk 一起可译 |
| T13 | `\ifdraft…\else…\fi` | PARTIAL | 不崩，但 `\newif \drafttrue \ifdraft \else \fi` **全部进入同一个 paragraph chunk** —— 译文若丢失这些 token，条件结构即毁 |
| T16 | `\NewDocumentCommand` | PASS | preamble 保留，不泄漏 |
| T17 | 数学内 `\text{}` | PASS | 随 `[[MATH]]` 保护 |
| T18 | figure 内 caption | PASS | caption 抽出可译；注意 `figure` **不在**保护清单（`table` 在），靠 env 行字面保留幸存 |
| T19 | abstract | PASS | |
| T20 | itemize/enumerate/description | PASS | `\item` 文本入 chunk |
| T21 | `\includegraphics[opt]` | PASS | → `[[GRAPHICS_n]]` |
| T22 | `\href{url}{text}` | PASS | 只把 `\href{url}` 换成 `[[HREF_n]]`,`{text}` 留给翻译 —— 设计正确 |
| T23 | `\emph\textbf\textit{文本}` | **FAIL** | 行内命令连同参数被 `_maybe_chunk_paragraph` 的清洗正则剥光后剩余 <20 字符 → **整行不成 chunk，永不翻译** |
| T24 | `\bibliography` | PASS | 保留字面量（fixture 无 .bbl/.bib) |
| T25 | `\makeatletter` | PASS | preamble 保留 |
| T26 | `\[ \]` `\( \)` | PASS | → `[[MATH_n]]` |
| T27 | `\'e \"u \~n` | PASS | 原样保留 |
| T29 | 独立 footnote | PASS | `{%s}` wrapper 抽取正确 |

**tricky-multi / T14**（多文件）:

| 子项 | 结果 | 证据 |
|---|---|---|
| `\input{sub/intro}` | PASS | 展平成功 |
| `\include{sub/methods}` | PASS | 展平成功 |
| 嵌套 `\input`(methods.tex 内 `\input{sub/nested}`) | **FAIL** | 递归时按**被包含文件所在目录**解析 → 找 `sub/sub/nested.tex` 失败（print Warning)，留下字面 `\input{sub/nested}`;LaTeX 语义应相对主文件/TEXINPUTS |
| 注释掉的 `\input` | PASS（侥幸） | `(^\|[^%])\\input` 只看 `%` 前一个字符：`% \input` 前是空格→**其实被展开了**，因被 include 文件只有一行，展开结果留在 `%` 行内被后续注释剥离顺带清除；**多行文件则第 2 行起必泄漏** |

**tricky-209**(LaTeX 2.09):`\documentstyle` PASS、`\def` PASS、`\beq…\eeq` **FAIL**（同 T01 宏展开陷阱，真实老论文 hep-th/9901001 亦中招）。

## 4. 泄漏率 (PROTOCOL §4)

可译 chunk 中仍含 `$`、`\cite`、`\ref` 族、`\begin{`、条件命令的比例：

| 指标 | 值 |
|---|---|
| 可译 chunk 总数 | 3536 |
| 含泄漏 chunk | **362 (10.24%)** |
| `\cite` 族命中 | 201 chunk(最大头，natbib `\citep` 在 attention/BERT 论文里铺天盖地） |
| `$` 命中 | 97 |
| `\ref` 族命中 | 88 |
| `\begin{` 命中 | 22 |
| 条件命令命中 | 1 |
| 零泄漏文件 | 37/93 |

泄漏最高的文件：`iclr2022_conference.tex` 75/166 (45%)、`neurips_2021.tex` 54/473、`ms.tex`（注意力论文）27/145、`expt.tex` 14/23。

**两大结构性泄漏源**（比"命令漏网"更深）:
1. **caption/title chunk 在保护管线之前抽取** —— `_extract_captions`/`_extract_title_command` 先于 `_protect_inline_math`/`_protect_commands` 执行，chunk 内 `$…$`、`\cite{key}` **永远是裸的**(corpus 实例：`iclr2016` caption 内含 `\cite{...}`)。
2. **白名单命令族不全** —— natbib 全族、`\autoref \cref \pageref \nameref`、自定义宏、非清单环境（`subequations flalign figure`）不保护。

## 5. 重建保真度 + 占位符残留 (PROTOCOL §3 + 假译文重建）

- **identity 重建**:93/93 全部 diverged(0 identical / 0 normalized),median quick_ratio 0.958 —— **by design，非保真解析器**：注释剥离、`\input` 展平、xeCJK 字体注入、`\usepackage[T1]{fontenc}`/`[utf8]{inputenc}` 被删除都在 `parse_file` 内完成，不可逆。对无 `\documentclass` 的子文件，还会**前置幽灵 xeCJK 头**（空 preamble 被追加注入块，实测 `abstract.tex` 重建开头多出 `\usepackage{xeCJK}\setCJKmainfont{Songti SC}…`)。
- **假译文重建残留**:10 个 corpus 文件的最终输出含 `{{CHUNK_uuid}}` 死 token（共 16 处：iclr2022×5、neurips_2020×2、hep-th 9901001×2，其余 7 文件各 1);`[[X_n]]` 保护占位符残留 0；孤儿 chunk（从未挂回模板）0。
- **残留机制（已定位）**：段落 chunk 会把相邻的 `[[ENV_n]]` 占位符行吞进自己的 content → 重建时单次遍历 chunks，该 paragraph 替换后 `[[ENV_n]]` 才落地 → 最后的 global-placeholder 循环还原 env → env 内部的 `\caption{{{CHUNK_id}}}` 此刻才出现，**chunk 遍历早已结束 → token 永久残留，caption 译文无处落地**。即"三层嵌套占位符"(chunk→ENV→CHUNK)逃出单层替换顺序。`\label{tab:…}` 附近 `\caption{{{CHUNK_…}}}` 字面可见。

## 6. 失败最小复现

```latex
% T01/T02: 宏展开陷阱 —— 进 chunk
\newcommand{\be}{\begin{equation}}\newcommand{\ee}{\end{equation}}
\newcommand{\dR}{\mathbb{R}}
Text \be x=1 \ee and \dR.          % chunk 内含 \be \dR 裸文本

% T04: natbib —— key 进 chunk
Text \citep{vaswani2017}, \autoref{s:a}, \cref{t:b}.

% T05: 可选参数 —— 不成 chunk,永不翻译
\section[Short]{Long Title Here}

% T06/T07: % 在注释剥离阶段被删 —— 产物不可编译
\begin{verbatim}100% x\end{verbatim}   % → \begin{verbatim}100
\url{http://a/b%20c}                    % → \url{http://a/b

% T14: 子文件内 \input 相对主目录 —— 找不到,留字面量
% (sub/methods.tex 内) \input{sub/nested}

% T23: <20 字符阈值 —— 不成 chunk
This is \emph{very important} and \textbf{bold claim}.

% 死占位符: caption 在 table 内 + table 后紧跟文本行(无空行分隔)
\begin{table}\caption{..\begin{tabular}..\end{tabular}\end{table}
Some following text.   % paragraph chunk 吞入 [[ENV]] → caption chunk 失修
```

## 7. 架构分析与可复用性

**实现方式**：无 AST，全文 regex + 手写括号计数；双轨占位符（`{{CHUNK_id}}` 可译 / `[[X_n]]` 保护）；流程 `flatten \input → resolve bib → 删注释 → 抽 abstract/title/author → caption 预抽 → 环境保护 → 数学保护 → 命令保护 → section/列表/footnote/段落抽块`。

**为什么会这样失败**:
1. **管线顺序性根因**：注释剥离跑在一切保护之前 → verbatim/url/verb 内 `%` 全灭（T06/T07，产物不可编译）;caption/title 抽取跑在保护之前 → chunk 内部永不受保护（泄漏第一大源）。
2. **零宏语义**：不读 `\newcommand`/`\def` → 宏展开陷阱全灭（T01/T02/209)；白名单硬编码 → natbib 全族、`\section[opt]`、`\author[opt]` 漏（T04/T05)。
3. **启发式阈值**:<20 字符不成 chunk → 短行静默不译（T23)，条件命令混入正文 chunk(T13)。
4. **单层重建**：占位符可三层嵌套，替换只扫一遍 → 死 token + 译文丢失（§5)。
5. **副作用前置**：注释剥离/展平/中文注入/包删除全在 parse 阶段 → 重建永 diverged，且对 preamble-less 文件注入幽灵头。

**改造成本**：修 T01/T02 要加宏表+一轮展开；修 T06/T07 要把注释识别做成 verbatim/url 感知（即半个 tokenizer)；修泄漏要让保护管线对 chunk 内容递归；修死 token 要把重建改成迭代至不动点。四者合计 ≈ 重写核心，**不建议在其上修补**。

**可借鉴的设计**:caption/footnote 预抽取+`{%s}` wrapper、双轨占位符、`_protect_nested_command` 的括号计数、`validate_translated_placeholders` 的 typo/幻觉修复思路、`\href` 只保护 url 留 anchor 文本的粒度。
