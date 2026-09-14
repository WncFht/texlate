# TexSoup 0.3.3 评测报告

库: `TexSoup` (alvinwan/TexSoup), tokenizer + 递归下降半解析器。
评测数据: `results/texsoup-parse.json`(90 个 corpus .tex 逐条记录)。
README 自称 "parsed 50 out of 50 arXiv papers" — 我们的语料验证见 §2。

## 1. 架构分析(源码层)

管线三级,全部在 `TexSoup/` 包内:

| 层 | 文件 | 机制 |
|---|---|---|
| 字符归类 | `category.py` | 每字符查**静态** catcode 表 → `Token(char, position, CC)`。position 就是源串下标 |
| 分词 | `tokens.py` | 有序 tokenizer 函数链(`@token` 注册):转义符号→注释→`$$`/`$`→`\[`…→换行→ignore→spacer 合并→单字符符号→命令名→文本串。产出带 TC 类别的 Token 流 |
| 递归下降 | `reader.py` | `read_expr` 分发:数学开关→`TexMathEnv` 等无名环境;`\begin`→`TexNamedEnv`(MATH_ENV_NAMES 进数学模式,SKIP_ENV_NAMES 走 `read_skip_env` 原文吞);命令→`read_command` |
| 树 | `data.py` | `TexNode`/`TexExpr`(TexCmd/TexNamedEnv/TexText/BraceGroup),节点记 `position`(首 token 的字符偏移),`str(node)` 重排输出 |

**关键设计事实**:

1. **无宏展开、无 catcode 动态性**。`\be` 永远是 `TexCmd('be')`,不会被识别为 `\begin{equation}`。`\makeatletter` 只影响命令名字符集(`at_letter` 标志,tokens.py:36-97),不做语义。
2. **参数推断靠贪心兜底**。`SIGNATURES` 表只有 9 个命令(def/section/label/newcommand 等);其余命令走默认 spec `(optional∞, required∞, optional∞, required∞)` — **任何命令都会把后面连续的 `[...]`/`{...}` 全吞成参数**。这是崩溃和失真的共同根因。
3. **注释进树但丢类别**。`tokenize_line_comment` 产出 `TC.Comment` token;但 `TexText.__init__` 做 `text=str(text)` 把 Token 降级成裸 str(data.py:1143)——**树中注释与普通文本不可区分**,只能靠 `src[node.position]=='%'` 回查。
4. **position 全程可靠**。所有 Token/Expr 记首字符偏移;不记 end,需用兄弟节点 position 推算区间。
5. **`\verb` 与 verbatim 环境走两条路**。`\verb` 用分隔符扫描(read_verbatim_contents),verbatim 环境用 `forward_until(startswith('\end{env}'))` 在 **token 流**上扫——两条路容错能力不一致(见 T06)。

## 2. Corpus 解析鲁棒性(90 文件)

| 指标 | 结果 |
|---|---|
| tolerance=0 成功 | **84/90 (93.3%)** |
| tolerance=1 追加恢复 | +5 → **89/90 (98.9%)** |
| 耗时 | 中位 69ms,均值 357ms,最大 3.0s(150KB 文件);语料全量 ~30s |
| README "50/50" | 我们语料上 93% @t0,远高于 README 自述 — 可能其统计口径更严或语料更脏;注意 50/50 是"能 parse"而非"parse 正确" |

### 6 个失败的逐案分析(全部有最小复现)

**F1. `\@ifnextchar[` — 贪心可选参数吞到 EOF(1 文件 + fixture T25)**

```tex
\newcommand{\secretmacro}{\@ifnextchar[{\@with}{\@without}}
```
`\@ifnextchar` 无签名 → 默认 spec 可选参数∞ → `[` 开 BracketGroup → 扫描 `]` 到 EOF 都找不到 → `TypeError Malformed argument`。@t1 能"恢复",但恢复方式是**把整个剩余文档吞进这个假参数**,树结构全错(序列化尾巴多 `]}`)。
corpus/1906.08237/custom.tex:1321 同款(`\def\rbr{\@ifnextchar[...}`)。**这是 LaTeX 内部宏的标准写法,真实宏文件里满地都是**(corpus 里 fancyhdr.sty/natbib.sty/IEEEtran.cls 共 20+ 处)。

**F2. `%` 出现在非 verbatim 参数内 — 注释吃掉闭合 `}`(4 文件)**

```tex
\href{https://github.com/...Finite%20difference%20checks.ipynb}{Julia notebook}
```
BraceGroup 内 `%` 被注释 tokenizer 吃掉直到行尾 — `}` 和第二个参数全进注释 → `Malformed argument`。@t1 可恢复但尾部结构仍错。
2501.14787 的 04/06/10/12 四个 lecture 全是这个模式(YouTube/Wikipedia URL 带 `%20`/`%3A`/`%E2`)。**`\url` 有特判(SPECIAL_ARG_READERS 里 raw 读取),`\href` 没有 — 同族命令待遇不一致**。

**F3. `\item` 内 env 名不匹配 — read_item 丢 tolerance(1 文件,唯一不可恢复)**

```tex
\item xxx
\begin{multline*} ... \end{multline}   % 源文件真的 mismatched
```
`read_expr` 里 `contents = read_item(src)` **不传 tolerance**(reader.py:123)→ item 内容按 t=0 解析 → env 不匹配必崩。
Pset1sol.tex:139-143 源文件本身 `\begin{multline*}...\end{multline}` 不匹配(真实 arXiv 脏数据),t=0/t=1 都死 — **tolerance=1 的覆盖面有洞:只在 read_env 生效,read_math_env/read_skip_env/read_verbatim_contents/\item 都不认它**。

## 3. Fixtures 逐条断言(tricky.tex)

tricky.tex **t=0 直接崩**(T25 `\@ifnextchar[`),t=1 文本完整但结构损坏。T25/T06 用独立小样例测,其余在去该构造的变体上测:

| ID | 结果 | 实测行为 |
|---|---|---|
| T01 `\be..\ee` | **FAIL(架构性)** | `\be` 只是 TexCmd,中间 `\wt{A} = \Tr(M^2)` 成普通文本/命令,**整体泄漏为"可译"块**。无宏表则无解 |
| T02 `\dR` | PASS(语义缺失) | `$x\in\dR$` 内随数学保护;但文本里 `\dR{}` 是裸命令残留 |
| T03 `\def\wt` | PASS | `TexCmd('def')` + 2 args(`\wt`,`{\widetilde}`),签名表识别 |
| T04 natbib+ref 全族 | **PASS** | citep/citet/citealp/citeauthor/citeyear/ref/eqref/autoref/cref/pageref/nameref/label 全部成 TexCmd+BraceGroup,key 可整体保护 |
| T05 `\section[S]{L}` | PASS | args=[Short]{Long},签名表命中 |
| T06 单行 verbatim 含 `%` | **FAIL(不可恢复)** | `\begin{verbatim}100% real\end{verbatim}`:`%` 注释 token 吃掉 `\end{verbatim}` → EOFError,**t=0/t=1 都死**。多行 verbatim 正常。`read_skip_env` 在 token 流上扫 `\end{env}` 前缀匹配,但 `\end` 已被注释吞进 token 内部 — tokenizer 与 skip 扫描层级错位 |
| T07 `\url{..%20..}` `\verb|a%b|` | **PASS** | url 有 raw-arg 特判;`\verb` 用分隔符 contains 扫描,% 不截断(与 T06 对比,两条路一好一坏) |
| T08 注释/`\%`/`\\%` | PASS(带坑) | 注释文本在树中(round-trip 保留),`\%` 为转义 token;但类别已丢,提取端要 position 回查 |
| T09 `\author[1]{..}` | PASS | 2 args 正确 |
| T10 subequations/align/flalign | PASS | 均入 MATH_ENV_NAMES 数学模式 |
| T11 theorem[Main Result] | PASS | 环境完整,`[Main Result]` 是内容文本 |
| T12 caption 内 footnote | PASS | footnote 节点可达 |
| T13 `\ifdraft..\else..\fi` | PASS(无语义) | 不崩;两支都进树,`newif/ifdraft/else/fi` 是裸命令 — 无分支求值(也不该要求) |
| T14 `\input` 递归 | **FAIL(架构性)** | `TexCmd('input')`+arg,**不读文件系统**。注释掉的 `\input` 不会误展开(注释被吃) |
| T16 `\NewDocumentCommand` | PASS | 3 args 全被抓,不泄漏不崩 |
| T17 `\text{..}` 在数学内 | PASS | 数学模式中 optional 参数关闭,`{if and only if}` 成 required arg |
| T18 figure 内 caption | PASS | |
| T20 itemize/enumerate/description | PASS | `\item` 特判,item 文本为 contents |
| T22 `\href{url}{text}` | PASS | 2 args;但 F2 的 `%` 隐患在 |
| T23 emph/textbf/textit | PASS | |
| T24 `\bibliography` | PASS | |
| T25 `\makeatletter` 区 | **FAIL(崩溃)** | F1 |
| T26 `\[ \]` `\( \)` | PASS | →TexDisplayMathEnv/TexMathEnv |
| T27 `\'e` `\"u` `\~n` | PASS | 转义符号 token,保留原文 |
| T19 abstract | PASS | |

## 4. Round-trip 保真(89 个可解析文件)

| 结果 | 数量 | 说明 |
|---|---|---|
| identical | **62** | |
| diverged | **27** | 差异**全部**是"参数边界空白被吃" + 1 类 `\def` 误用 |
| normalized | 0 | |

最小复现(全部实测):

```tex
{\tt [CLS]}            -> {\tt[CLS]}     % 空格被吃 + [CLS] 被绑定为 \tt 的可选参数(语义也错)
\newblock {\em X}      -> \newblock{\em X}
\begin{figure*}[h]\n{\includegraphics{x}}  % [h] 后 \n 被吃,且 {..} 被并进 env 的 args 而非 contents
```

**根因同 F1**:默认 spec 的 optional∞/required∞ 阶段;`read_arg_optional` 吃掉 spacer 后见 `[`/`{` 就绑参数,spacer 不进 args → 丢失。TeX 语义上多数无害(控制字后空格本来就被吃),但**破坏了 `str(node)==src[pos:pos+len]` 的逐字节对应**(位置审计:62330/62574=99.6% 节点切片精确;失败节点全是这类)。另有 223 个裸 str 子节点(raw brace arg/verbatim 内容)无 position,但它们是叶子、本来就按不透明区间处理。
tricky-209 特例:正文里 "old \def macros" 的 `\def` 被签名表抓 2 参数并**合成 `{}` 包裹文本**(`'{%s}' % token`),+2 字符失真。

## 5. 泄漏率(自建提取器,89 文件)

提取模型:数学环境/$…$/\[…\]/verbatim 保护,cite/ref/label/url/结构/定义族命令保护,emph/textbf/footnote/caption/section/item 内部文本可译,未知命令源码并入块文本。

- **protocol 泄漏率(`$`/`\cite`/`\ref`/`\begin{` 入块):39/1190 块 = 3.3%**
- 块内含任意 `\cmd` 残留:324/1190 = 27%(含 `\'e`、`\LaTeX` 这类良性残留,口径偏宽)

主要泄漏形态:`\resizebox{}{}{\begin{tabular}}`(表格包在盒子参数里)、`\preprintnumber{...}` 等期刊私有命令、`\be` 式宏(架构性无解)、`\ifshowtodo` 条件区、`{\tt X}` 声明式字体。注释已靠 position 回查排除(否则 `%%` 注释行全算泄漏)。

## 6. 对我们管线的可复用性评估

**结论:能当半解析器内核,但需要 ~4 处外科手术;不要直接用它的容错分支。**

可用资产:
- tokenizer/reader 干净分层,`Token.position` 全链路可靠 → 区间重建底座成立(建议 span = [node.pos, next_sibling.pos) 而不是 pos+len(str),避开吃空白节点)
- verbatim/数学/`\verb`/`\url` 的特判点都已标识(SKIP_ENV_NAMES/MATH_ENV_NAMES/VERBATIM_COMMANDS/SPECIAL_ARG_READERS),保护语义可配置
- 速度可接受(69ms 中位);t=1 在多数文件无损恢复
- round-trip 62/89 逐字节一致;差异点已知且集中(参数边界空白)

必须修(按优先级):
1. **默认参数 spec 收敛**:optional∞→有界(或命令表驱动)。F1/F2/吃空白/`{\tt[CLS]}` 全是它。改造成本小(改 `SIGNATURES` + `read_args` 默认行为),是我们语义宏表的挂载点。
2. **verbatim/skip-env 的 `\end` 扫描移到字符层**(或容忍注释 token 内部含 `\end{env}` 时回切 token)。T06 单行 verbatim 是 arXiv 真实写法。
3. **`\item`/数学环境/skip 路径透传 tolerance**(reader.py:123 一行 bug)。
4. **TexText 保留 token category**(注释/转义/文本三类),或在提取层统一做 position 回查(已实现,成本 0)。
5. `\href` 等 url 族进 SPECIAL_ARG_READERS(raw 参数),`\url` 已有先例。

做不了(需自补,本就计划内):宏展开(`\be`→env)、`\input` 展平、catcode 动态性。这些在我们的宏表层解决 — TexSoup 的节点模型(TexCmd+args+position)正好承载展开前后的双重视图。

风险点:assert 语句当校验用(reader.py 多处 `assert`),`python -O` 下行为会变;Buffer 的 peek/forward 语义绕,改动需配测试。

## 附:数据文件
- `results/texsoup-parse.json` — 90 行 {file, ok, error, ms, ok_t1, ms_t1, roundtrip, rt_len_delta}
- 复现脚本: `bench/py/texsoup_bench.py`, `texsoup_diverge.py`, `scratch/texsoup_probe*.py`, `scratch/pos_audit.py`, `scratch/texsoup_rt.py`
