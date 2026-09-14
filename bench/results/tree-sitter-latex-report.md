# tree-sitter-latex 评测报告

- **版本**: @pfoerster/tree-sitter-latex 0.6.0（latex-lsp 组织，texlab 同款文法）+ `tree-sitter` 0.25.1 native binding（已编译 `build/Release/tree_sitter_latex_binding.node`)
- **实现**: tree-sitter GLR 容错解析器：`grammar.js` ~1400 行文法 DSL → 生成 `src/parser.c` 94 万行状态机 + `scanner.c` 外部扫描器（处理 verbatim/lstlisting/minted/comment 等 trivia 环境的原始内容）
- **入口**: `parser.parse(src)` → `Tree`,**永不抛异常**；错误以 `ERROR`/`MISSING` 节点形式留在 CST 里
- **评测脚本**: `bench/ts/bench-tsl.js`；数据 `bench/results/tree-sitter-latex-{parse,traps,validator}.json`

## 1. 语料鲁棒性（corpus/ 全部 90 个 .tex)

| 指标 | 值 |
|---|---|
| 解析不抛异常 | **90 / 90(100%)** |
| 完全干净（无 ERROR/MISSING) | **47 / 90** |
| 微小错误（ERROR 覆盖 <2% 字节） | **38 / 90** |
| 灾难性错误（>97% 字节进 ERROR) | **2 / 90** |
| 总耗时 | **236ms**(90 文件） |
| 中位 / p90 / 最大 | **1.15ms / 6.49ms / 25.96ms**（比 latex-utensils 快 ~5.5×) |
| ERROR 总字节 | 54564 / 1225378(4.45%，几乎全部来自那 2 个文件） |

**两类错误的性质完全不同**:

**A. 微小错误（38 文件，合计 ~2500 字节）——文法词法缺口，不是真语法错误**:
- **主因 1:`\ref/\eqref/\label` 的 label 词法不含下划线**。`grammar.js` 里 `label: /[^\\\[\]\{\}\$\(\)=&%\s_\^\#\~,]+/` 显式排除 `_`,arXiv 高频的 `\ref{fig:bert_overall}` 被打断 → 在 `bert` 后插一个 `MISSING "}"` 节点、遗留的 `}` 成 1 字节 ERROR。每个错误 1~3 字节，解析恢复极好（bert.tex 12 处、iclr2022 91 处，全是这类）。**注意:`\cite{a_b}` 走另一条词法（citation keys）却接受下划线**——同一文法对 ref 和 cite 的 key 规则不一致。
- **主因 2:`\DeclarePairedDelimiter\abs{|}{|}`** 等声明式命令的参数形状文法不覆盖（custom.tex、math_commands.tex 里的定义区）。
- 个别零散：`{\tt ...}` 旧式字体切换、`\,` 后跟特定字符等。

**B. 灾难性错误（2 文件）——真实缺陷输入，恢复策略把整个剩余文件吞进一个 ERROR**:
- `1511.06432/iclr2016_conference.tex`(97.93%):L33 `\newcommand{\bmx}[0]{\begin{bmatrix}}`——**`\begin{env}` 半边宏出现在花括号组内**，文法试图把它当环境开头，找不到配对的 `\end` 后 GLR 恢复策略把 offset 852→41198（近全文）归成一个 ERROR 节点。
- `2501.14787/psets/Pset1sol.tex`(97.34%):L209 少一个闭合 `$`（真·源文件缺陷，与 latex-utensils 拒识同一文件、同一原因）——未配对 `$` 之后 97% 字节进一个 ERROR。

**最小复现**:`{\begin{equation}}`（组内不平衡 `\begin`)→ ERROR；平衡组 `{\begin{a}x\end{a}}` 正常；`\newcommand{\ee}{\end{equation}}`（半边 `\end`）反而正常——**只有组内孤立 `\begin{` 触发灾难**。

## 2. 陷阱断言（fixtures/tricky.tex)

整文件解析：`hasError=true`,**2 个 ERROR 节点，其中一个覆盖 16~159 行**——就是 T01 的 `\newcommand{\be}{\begin{equation}}` 触发了 §1-B 灾难模式，余下所有陷阱区都被裹进该 ERROR。

**消毒对照实验**：把 `\begin{equation}`/`\end{equation}` 换成 `BEGIN_EQ/END_EQ` 重解析 → **0 ERROR、0 MISSING，全文件结构完好**。即在宏半边问题之外：

- `\url{..%20..}` → `hyperlink` + `curly_group_uri`(% 保留）✅
- natbib 全族 → 专用 `citation` 节点（keys: `curly_group_text_list`,prenote 支持 `[see][chap.2]`)✅ 比 latex-utensils 语义更深
- `\href` → `hyperlink`(uri + label 字段分离）✅
- `\section[Short]{Long}` → `section` 节点嵌套进层级树 ✅
- `theorem[Main Result]`、`description/item[Term]`、caption+footnote、`\ifdraft…\fi`、`\@`-宏、重音命令、`$$/\[/\($`、verbatim/lstlisting（外部扫描器原样吞 content)→ 全部结构完好 ✅
- `\input/\include/\subfile/\import` → `latex_include`/`import_include` 节点带 `path` 字段；注释掉的 \input 是 `line_comment`——展平器天然跳过 ✅(T14)
- **`\verb|a%b|` → 无 ERROR，但 `%b|` 被静默解析成 `line_comment`** ⚠️ 文法不认识 `\verb` 行内分隔符，% 当注释吞到行尾——**不产生错误信号的静默语义错误**，校验器视角是隐患（latex-utensils 有专用 `verb` 节点，此处完胜）
- `\be \wt{A} = \Tr(M^2) \ee` 使用点 → generic_command + text，与 latex-utensils 同样不做宏展开（T01 两家都盲）

## 3. "翻译后校验器"可行性评估（核心问题）

给 8 类人为破坏输入跑 `validate()`(ERROR/MISSING 收集 + 环境名比对原型，~35 行）:

| 破坏 | tree-sitter 裸检测 | 说明 |
|---|---|---|
| 删一个 `}`(`\textbf{w`) | ✅ ERROR 节点 | 但 ERROR 常覆盖 0→文件尾，**粒度粗** |
| `\citep{key2020` 少 `}` | ✅ **MISSING "}" 精确插在缺失点** | 定位最漂亮的一例 |
| `$` 未闭合 | ✅ `MISSING "$"` 精确位置 | |
| `\begin{itemize}` 无 `\end` | ✅ ERROR | |
| `\begin{equation}…\end{eqnarray}` 名不匹配 | ❌ **文法不报错** | `\begin/\end` 各自独立成节点，名匹配从来不在文法层检查（tree-sitter 无法在规则内比对两个位置的文本） |
| 悬空 `\end{table}` | ❌ **不报错** | 顶部 `\end` 直接解析成 generic_command + curly_group |
| 交叉嵌套 `a{b}b{a}` | ❌ 文法不报错 | |
| unclosed-group `\section{X` | ✅ ERROR | |

**但：配 ~35 行 CST 语义遍历后全部可检出**——原型（`/tmp` 验证过）在 `generic_environment`/`math_environment`/`verbatim_environment` 等 `*_environment` 节点上比对 `begin.name` 与 `end.name` 的源文本，成功检出 `equation→eqnarray` 不匹配、交叉嵌套（两个 env 各自报一对错配）；悬空 `\end` 补一条"顶层 generic_command 名为 `\end`"规则即可。**结论：tree-sitter-latex 的 ERROR/MISSING 检测硬语法损伤（括号/$/环境未闭合）开箱即用，语义一致性（名匹配、悬空 end）需一层薄薄的自有规则——但 CST 干净，这层规则很好写。**

**加分项：增量解析**。`tree.edit` + `parse(src, oldTree)` 实测 0.37ms——翻译管线改一段只重解析增量，做实时校验器零压力。

## 4. 架构分析

- **GLR 容错**:tree-sitter 为编辑器场景设计，任何输入都产出完整 CST，错误以 `ERROR`（意外内容）/`MISSING`（应有但未出现的 token，零宽度插入）标记。`hasError`/`isMissing` 一查便知。
- **错误收容粒度差**：恢复策略是"吞到可恢复点"。对未闭合 `$`/组内 `\begin` 这类故障，恢复点可能远到文件尾 → **一个 ERROR 节点吃掉 97% 文件**。对比之下 latex-utensils 是"全或无",tree-sitter 是"坏一处可能烂全文（但仍给你 AST)"。
- **语义深度高于 latex-utensils 的命令层**：专用节点 `citation`（带 keys/prenote 字段）、`label_reference`/`label_definition`、`latex_include`(path 字段）、`caption`、`new_command_definition`/`old_command_definition`/`theorem_definition`、**section/chapter/subsection 形成真·层级树**（小节嵌在章节内——latex-utensils 是扁平流）；但**数学内部是浅的**:inline_formula/displayed_equation 内部只是 word/operator/subscript 流，不如 latex-utensils 的 math.character 体系细。
- **词法不一致点**:ref 系 key 禁 `_`,cite 系 key 允许（§1-A);`\verb` 不认识（§2)。这些是 grammar.js 的 bug/缺口，理论上可以给上游提 PR。
- **部署形态**:native `.node` binding(node-gyp 编译，已有）,`web-tree-sitter` WASM 备选；node-types.json 460 种节点类型随包发布。
- **序列化**：无 stringify——CST 唯一可靠的"序列化"就是按 node.startIndex/endIndex **切原文**(tree-sitter 的 token 流是无损覆盖原文的，这点和 latex-utensils 的 stringify 哲学不同）。

## 5. 对本管线的可复用性

| 角色 | 适配度 | 说明 |
|---|---|---|
| **翻译后 AST 校验器** | ✅ **胜任** | 容错解析天然匹配"翻译输出可能不完美"的场景；ERROR/MISSING 定位+自定义 env 名匹配规则(~35 行）= 可用校验器；增量解析支持只校验改动段 |
| 段落提取器 | ❌ 不推荐 | 三个硬伤：(1) 灾难性 ERROR 收容——一个 `\begin` 半边宏毁掉全文 AST(iclr2016 实测）;(2) 数学内部语义浅，提取保护边界反而不如 latex-utensils 清晰；(3) ref-key 下划线缺口会在含 `fig:x_y` 的文件里撒一地假 ERROR，干扰"结构是否可信"判断 |
| 占位符保护/区间重建 | ⚠️ 间接 | 切原文可行，但提取决策已经由 latex-utensils 做更顺 |
| 双解析器交叉验证 | ✅ 可选 | 两端 AST 互证（如环境计数、命令计数一致性）可作为管线自检 |

**必须自己补的**:
1. **env 名匹配 + 悬空 \end 语义检查**(~35 行 CST 遍历，原型已验证）;
2. **`\begin`-in-group 灾难的预案**——校验器场景下它表现为巨大 ERROR，可作为"输入本身有宏半边"的特征信号，但要意识到它会掩盖同一文件里的其他错误；
3. **label-key 下划线等词法缺口的白名单**——否则 `\ref{fig:x_y}` 会在校验阶段产生假阳性。建议：把"ERROR/MISSING 节点 text 是否匹配 label-key-with-underscore"做成误报过滤器。

**一句话**：定位完全不同——它是管线的**出口校验器**而非入口提取器。容错解析 + ERROR/MISSING 定位 + 增量重解析正好补齐 latex-utensils 的短板（后者一坏全拒）；但要清楚它的两个坑：组内 `\begin` 半边宏会让 ERROR 吞掉全文、`\ref` key 下划线缺口会撒假错误——前者当信号用，后者加白名单过滤。
