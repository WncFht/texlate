# LaTeX 半解析 + 展开机规范

> 实现唯一事实源：`src/texlate/latex/`。本文与代码现状对齐；调研与实测证据引用 `research/latex/` 档案，不复述。

## 1. 定位与边界

TeXlate 的 LaTeX 层做的是**半解析**（semi-parsing）：单遍正向扫描产出 token/段流，把输入文本切成无缝平铺的 `pieces`——可译段登记为 `chunks[]`、受保护段替换为 `[[TYPE_n]]` 占位符、其余原样字面。不建 AST、不求值 TeX 语义全集——LaTeX 是图灵完备宏语言，全量解析等价于实现 TeX 求值器，现成库在真实语料的宏展开上全灭，故走自研半解析路线[^adr-semi][^miniscanner]。

层内边界：

- **输入**：单文件文本（`parse_tex`）或磁盘文件树（`parse_file`/`scan_tex_tree`）。
- **输出**：`ScanResult`（`model.py`）——`protected_tex`（占位符化文本）、`chunks`（可译段）、`ph_map`（占位符→原文段）、`pieces`（平铺段列）、`inputs`（`\input` 事件）、`warnings`、`vtex`（坐标系文本）、`ph_reserved`（源文自带占位符形字面）、`macros`（scope 宏表终态）。
- **下游**：译文侧按 `chunks` 逐段翻译，`reconstruct/core.py::reconstruct` 按 pieces + 占位符 DAG splice 回完整文档；`validate/` 层做 src↔zh 相对校验（L0 契约见 §9）。
- **明确不做**：排版、数学求值、完整 TeX 语义（`\the`/计数器寄存器/`kpathsea` 库查找等）。一切未覆盖构造退化到保守保护路径，首要不变式是 splice-safe——字节全保、identity 重建逐字节等于原文。

唯一解析路径是 **v2 token 流**（`gullet/` + `segmenter/` 包），`api.py` 顶部即声明；v1 字节扫描器已删除，`flatten.py::flatten_inputs` 仅存为独立字节级展平 API（bench/外部调用），不在解析主链上。

## 2. 总览

### 2.1 三层结构

借 TeX 的 mouth/gullet/stomach 分层[^exp-design]，本实现止于「胃」之前（不排版）：

- **Mouth**（`mouth.py::Mouth` + `CatTable`）：文件字节 → `Tok` 流。逐文件一个词法器，`Gullet.inputs` 栈管理多文件。
- **Gullet**（`gullet/` 包，`Gullet` = `_Core`+`_Args`+`_DefCmd`+`_Decls`+`_Input`+`_Expand`+`_Cond`+`_Classify`）：全仓唯一宏展开点。`next_expanded()` 主循环做查表展开/原语执行的回压不动点，产出「已展开」token 流。
- **Segmenter**（`segmenter/` 包，`Segmenter` = `_Core`+`_Group`+`_Pending`+`_MainLoop`+`_Env`+`_Args`）：消费展开流，发 `pieces`/`chunks`/占位符，维护 vtex 覆盖账本。

装配：`api.py::parse_tex` → `segmenter.parse_tex_v2`（内存源）；`parse_file` → `Gullet(root_dir, top_dir)` + `push_source` → `scan_v2`（`segmenter/__init__.py`）。

### 2.2 五条铁律（设计公理）

旧规格的五条公理在 v2 全部成立，且全部落到具体机制上：

1. **单遍正向、绝不抛异常**：参数不匹配是 `ArgMismatch` 控制流信号（`entries.py::ArgMismatch`），调用方 `unread(trace)` 回吐后把触发 token 本体交下游——任何解析失败都退化成字面/保护段，字节不丢。
2. **分支序即语义**：分派表行序是规范本身——主流 `_DISPATCH_FAMS`（`mainloop.py`）、组内 `_GRP_SURFACE_FAMS`、跨界 `_PEND_SPEC_FAMS`（`pending.py`）三面共享名→判据绑定 `_common._FAM_BIND`，行序各面自排，`tests/latex/test_dispatch_mirror.py` 逐名裁决三面族序。
3. **含 `%` 的构造先于 `%` 分支消费**：注释在 Mouth 层吞掉（永不成为 token），下游所有「`%` 分支」只处理渲染串里的字面 `%`（`_arg_comment_ph`）。
4. **splice 只用调用点/原始字节 span**：`Tok.origin` 记最外层调用点坐标；展开组 identity 面收拢为 `[[EXPAND_n]]`，其体 = 调用点 vtex 切片——译文侧展开时落回原字节，绝不落展开产物。
5. **一切降级 splice-safe**：所有 bail 路径（参不匹配、组未闭、跨界、超代数）都以「回吐 + 字面/保护」收尾，identity 不破是硬验收。

### 2.3 头号不变式与坐标系

`pieces` 无缝平铺 `[0, len(vtex))`（`Piece.span` 首尾相接）是头号不变式，`validate_result` 的 `pieces_gap` 规则专门校验。

`vtex` = 叙事序虚拟文本（`segmenter/_common/rec.py::_Vtex`）：一切 span/piece/chunk 坐标都在 vtex 系。`Segmenter._cover_to(fid, end)` 把 `file_texts[fid][cons:end]` 追加映射进 vtex——token 之间的间隙字节（注释残骸、折叠空白）随覆盖自动进 vtex，这是 Mouth 吞注释后 identity 不破的机制。多文件 `\input` 内联后 vtex 即展平文本的同构面。

### 2.4 run 双轨与展开组

Segmenter 的 run 项是 `(surface, ident, vspan)` 三元组：surface 进 `chunk.content`/译文面，ident 进 identity 面——gen=0 项取 vtex 切片、ph 项取 token 自身、展开组取 `[[EXPAND_n]]`。run 含展开组时 `ph_map["[[CHUNK_k]]"]` 登记 ident 串，`reconstruct` 的 `trans → ph_map → content` 优先级自动回落原文（零 schema 变更）[^exp-design]。

**展开组**：`gen>0` 且同 `origin` 的连续 token 为一组，pos 落调用区间内的 gen=0 参数 token 同属。surface 正常流过分段（组内经 `_grp_scan` 再生保护段），ident 收拢为单个 `[[EXPAND_n]]`。组内含副作用（`\def`/`\let`/`\catcode` 等）→ 整组转 literal。

## 3. Mouth：字符 → token

### 3.1 Tok

`mouth.py::Tok` 字段：`kind`、`text`、`pos=(file_id, start, end)`、`gen`（展开代数，0=源文）、`origin`（最外层调用点 pos）、`xprotect`（`\noexpand` 打标，见 §4.5）。`src` 属性 = `origin or pos`——占位符体/告警定位一律用 src。

token 种类：`cs`（控制序列，text 为去 `\` 的名字）、`lbrace`/`rbrace`、`mathshift`（`$`）、`param`（`#`）、`space`（连续空白折叠，text 含 `\n` 时标记盖了源换行）、`eol_par`（`\n\n` 段落界/`\par` 原语）、`letter`/`other`（按 catcode）、`active`（`~` 等 active 字符）、`consumed`（gullet 静默消费段的界标 token，§4.6）。

### 3.2 CatTable

`mouth.py::CatTable` 是共享可变 catcode 表：默认 TeX 初值 + `~`=active；`{`/`}` 等组事件走**组作用域撤销栈**（`push`/`pop` 与宏表对称推弹）；`_v` 版本计数器——`\makeatletter`/`\catcode` 改表即 +1，派生缓存（`_text_run_rx` 批扫正则等）按 `_v` 失效重建。`\makeatletter` 的存在是 tokenize 必须 pull-based（逐 token 产出、随时可被 catcode 变更影响后续字符）的根本原因——预词法整文件会把 `@`-宏名切错。

### 3.3 产出与快路

- `%` 注释吞到行尾（含 `\n`），不产 token——注释字节靠 vtex 覆盖账本进 identity 面。
- `\n\n`（含中间空白）折叠成单枚 `eol_par`；`\par` 原语在 gullet 里也翻译成 `eol_par`（`_exec_prim` par 分支）。
- `Mouth.resync(pos, keep)`/`skip_text`：分段器在字节级找到 verbatim 闭符后把词法游标直推闭合位（`skip_past` 的源侧对价）。
- `Mouth.from_tokens(toks, cats)`：token 回放合成源（`file_id<0`）——`unread`/case 选支回放的载体。
- `text_run_end`/`_text_run_rx`：run 批量化快路——栈顶 Mouth 刚产 gen=0 文本 token 且 tokbuf 空、游标对齐时，猫码派生正则把游标直推 run 尾，run 内字符永不物化 token（`gullet/core.py::text_run_end` 三守卫不满足即回退逐 token）。

## 4. Gullet：展开机

### 4.1 主循环分派序

`gullet/core.py::next_expanded` 每轮：`read()` 拉原始 token → 非 cs 直交 → `xprotect` 见标消费一次跳过展开 → **宏表先行**（`macros.lookup` + `resolve`——`\ifb` 单位宏/`\ifAnonymous{T}{F}` 宏不落入 if 族）→ `_PRIMS` 原语表/`if*` 前缀 → 都不中直交分段器。宏命中且 `kind ∈ _EXPAND_KINDS` 且 `_can_expand` → `_invoke` 读参代入、`unread` 推回、不 return（不动点）。单遍即时展开相对二遍展开的语料依据见实测[^exp-timing]。

`_EXPAND_KINDS = {"transparent_expand"}`（`gullet/names.py`）——env_begin/env_end **不展开**：展开产物的 `\begin` 是 gen>0 token，会被分段器收进 `[[EXPAND]]` 组、env 配对丢失；raw cs 交分段器按 `target_env` 走环境路径。

### 4.2 展开限制（UBD）

三级闸门 `core.py::_can_expand`：`t.gen >= MAX_GEN`（32）→ `gen_overflow` 告警一次后不再展开；`steps >= BUDGET`（100_000）→ `expansion_overflow`；超限 token 原样交出。子扫描/组内递归复用同一 `MAX_GEN`（`segmenter` 侧 `gen` 计数触底即停挖，记 `gen_overflow`）。

### 4.3 宏登记与分类

登记原语全覆盖 `\def` 族（`\def`/`\edef`/`\gdef`/`\xdef` + `\long`/`\outer`/`\global`/`\protected` 前缀链，`defcmd.py::_do_def`/`_do_prefix`）、`\newcommand` 族（`decls.py::_do_newcmd`）、`\newenvironment`/`\newtheorem`（`EnvDef`，`env_scopes` 表）、`\DeclareMathOperator`、`xparse` `*DocumentCommand` 族（`v`/`b`/`E`/`x` 型参数不支持 → 该定义不登记）、`\let`（`Alias` 快照：MacroDef/IfCond/IfSetter/Tok/原语名/None）、`\newif`（注册 `IfCond` + `\Xtrue`/`\Xfalse` 两个 `IfSetter`）、`\catcode`/`\makeatletter`/`\makeatother`。

`\def` 参数文本编译（`defcmd.py`）支持 `#1`-`#9` 编号、定界参数（`#1<delim>` → `Arg("delim")`）、`#{` 尾（`brace_after`）、`##` 折叠；`\edef`/`\xdef` 体走 `_expand_eager` 哨兵先展开再存。参数模型 `entries.py::Arg`：kind ∈ `m|o|star|eq|delim|until_group|literal_match` + `delim`/`default`/`open`/`close`/`char`/`brace_after`。

**体分类在登记时一次完成**（`classify.py::_classify` → `MacroDef.kind` 六值）：

- `env_begin`/`env_end`：`classify_body`（`macro_table.py`）表面匹配——`env_end` 放宽为尾匹配（`\def\eea{\relax\end{eqnarray}}` 形）加前缀闸，`\csname endX\endcsname` 整体形同认；
- 体含 `@`-cs → `opaque`（内部宏不展开）；
- 体无自然文本（`body_has_text`：剥 cs/参数/非字母后无 ≥2 连续字母）→ 单枚裸 cs 纯别名收 `transparent_expand`（吐出走正常分派），否则 `math`（含数学特征 `_MATH_CS`/`$`/`^`/`_`）或 `opaque`；
- 体有文本 → 剥 `#i` 参数位后仍有文本 = `transparent_expand`（真展开）；文本只经参数位进入 = `transparent_inline`（不展开，交调用点保护链）。

`protected_param_positions` 顺带算出 `protect_args` 位图（`#i` 落 `\ref/\cite/\label/\url` 参数位）——v2 下该字段写而不读：key 保护由展开产物在组内再生分派（`\ref{key}` → `[[REF]]`）与 `_keyarg_tail` 调用点链兜底实现。

### 4.4 scope 模型

`entries.py::ScopeMacroTable` 双链：`scopes`（命令表）+ `env_scopes`（环境表），底帧=全局。推弹事件由**分段器**回报驱动（`lbrace`/`rbrace`/`\begin`/`\end`/数学开关），唯一例外是 `\begingroup`/`\bgroup`/`\endgroup`/`\egroup`——cs 形原语由 `_exec_prim` 在分派点直接推弹（含 gen>0 展开产物）。`\gdef`/`\xdef`/`\global` 写底帧；`\providecommand` 走 `setdefault` 全链查无才写。实参组（gullet `_invoke` 与分段器 `_args_tok` 消费的分界括号）不建作用域，与 TeX 语义一致。`env_sig(target)` 全链快照 `(name, kind, scope_depth)` 集——分段器 env 墓标（§5.7）的作废键。

### 4.5 展开原语

`_exec_prim` 表（`core.py`）：定义族见 §4.3；`\begingroup` 族见 §4.4；`\input` 族见 §4.7；`\expandafter`/`\csname`/`\endcsname`（`expand.py`）；`\noexpand` → 下一 token 打 `xprotect`；`\ifundefined`/含 `@` 变体（界标夹心同 `\if`）；`\romannumeral`（≤3999，超界回吐本体）；`\uppercase`/`\lowercase`；`\par` → `eol_par` token；`if*` → `_do_if`；`\else`/`\or`/`\fi` 散件与 `endcsname` → 直交分段器作界标。

`\noexpand`、`\expandafter` 等读的是「下一个 raw token」——`read()`/`unread()` 的 trace 账本（`gullet/input.py` 读取器把已消费 token 记 `_trace`，`ArgMismatch` 时整体回放）保证控制流可回滚。

### 4.6 consumed 界标

gullet 静默消费的字节段（`\def` 串、`\if` 条件区、`\input` 调用点、`\endinput`）产出 `consumed` marker token（`core.py::_consumed`）：`text` = `family:payload`（如 `def:foo`、`if:ifnum`、`input:chap`），`pos` = 消费区间。分段器收到即 flush run + LITERAL 盖面——`\def` 串不落 chunk（译文会删 def）、`input:` 型按 payload 记 `inputs[]`。gen>0 的 marker 是组内边界，不驱覆盖。

### 4.7 `\if` 两档处理

`cond.py::_eval_if` 可求值表：`iftrue`/`iffalse` 常量、`ifnum`/`ifodd`/`ifdim`/`ifcase`（`_read_number` TeX number 全形态）、`if`/`ifcat`（字符比较）、`ifx`（`_tok_eq` 宏比较——宏定义比对走 `expand_def`）、`ifdefined`/`ifcsname`/`ifundefined` 族（宏表 + `_BUILTINS` 内建名集）、`ifeof`/`ifvoid`/`ifhbox`/`ifvbox`/`ifinner`/`ifpdf*`/`ifabs*` 常量 False、`ifhmode`=True/`ifvmode`=False、`\newif` 旗标查 `ifflags`。

- **可求值** → `process_if` 收集 case 列到 `\fi`（`\else`/`\or` 分案；嵌套只计真条件：`IfCond`/str-if 别名/未定义原语 if），选支 `unread` 回放并夹**界标三明治**：lead `consumed` token（`if:name`，盖 `\ifX`+死支）+ 尾 `fi:name`（盖选支末到 `\fi` 末）。`\ifcase` 超界落 `\else` 支。
- **不可求值**（`\ifx` 宏比较失败、未知 `if*`、溢界）→ 条件 token 照常消费成 gap，`\ifX` 本体作界标直交分段器，**双支自流**——`\else`/`\fi` 各自再到分段器出 LITERAL 界标，嵌套免计深。

### 4.8 `\input` 内联展开

`gullet/input.py::_do_input` 处理八形态：`\input`/`\include`/`\InputIfFileExists`/`\subfile`/`\import`/`\subimport`/`\includestandalone`/`\CatchFileBetweenTags` + 裸文件名形（`\input file`，`FILENAME_CHARS` 连扫）与引号裸名（`\input"a b.tex"`）。

- **解析序** `_resolve_input`：当前文件目录 → `root_dir` → `top_dir`（e-print 顶层兜底）→ basename 补 `.tex`/`.TEX` → 裸名。`openin_any` 等价闸：候选 real path 必须落在已解析根集内——`..`/绝对路径逃逸、根内 symlink 指出界一律按 miss，永不 `read_bytes`。
- **防环**：`_seen` 祖先栈（进栈压、弹栈撤）——只断真环，兄弟位合法重包含照常内联；主文件路径由 `parse_file` 预种，`\input{self}` 直接断。`MAX_INPUTS=8` 深度上限。
- **壳剥离**：`\subfile`/`\includestandalone` 展开时 `flatten.py::strip_doc_shell` 剥 document 壳；`\CatchFileBetweenTags` 按 `%<*tag>…%</tag>` 提区。`\includeonly` 忽略。
- **`\endinput`**：弹当前输入源 + `consumed("endinput")` marker；`\end{document}` 只在顶层截停。
- **漏网**：解析失败/`flatten=False` 内存源 → 命令本体交分段器（`missing_input` 告警 + `inputs[]` 记原始名；含 cs 的动态文件名不算输入尝试）。

`gullet/file` 侧 `_read_input_blob` 同走 `_tar_disguised` 闸（tar 伪装 `.tex` 拒绝读入）。字节级独立版 `flatten.py::flatten_inputs` 是同判据的单遍实现（库外/bench 用），`gullet/input.py` 复用其 `_resolve`/`strip_doc_shell`/`_extract_tag_region`。

### 4.9 TokenSource 契约

`segmenter/_common/tok.py::TokenSource` Protocol 是分段器对源的全部要求：`macros`/`pop_seq`/`push_seq`/`unmatched_open`/`eof_pops`/`read`/`unread`/`skip_past`/`scope_push`/`scope_pop`/`live_inputs`/`env_sig`/`input_expand`/`text_run_end`。`Gullet` 是生产实现；`_ListSource`（deque 回放源，`eof_pops=False`、`unmatched_open` 持真集）供参数/组内子扫描重放 token 列。

## 5. Segmenter：展开流 → pieces/chunks

### 5.1 主循环四态

`mainloop.py::scan` 逐 token：`preamble` 档（`_preamble_tok`，见 §5.3）→ `consumed` marker（flush + LITERAL）→ 展开组界（gen>0 连续组进 §5.6 组机制）→ `_dispatch` 分派（cs/mathshift/eol_par/文本 run）。纯文本 run 走 `text_run_end` 快路整段进 run。

### 5.2 分派表

`_dispatch` 按 `_DISPATCH_FAMS` 22 行序判（`mainloop.py`，绑定单源 `_FAM_BIND`；各族名集常量单源 `tables/names.py`——`CITE_NAMES`/`PROTECT_NAMES`/`CHUNK_ARG_NAMES`/`VERBATIM_ENVS` 等）：

| 序    | 族               | 行为                                                                                                                     |
| ----- | ---------------- | ------------------------------------------------------------------------------------------------------------------------ |
| 1     | verb             | `\verb`/`\verb*`/`\lstinline` 定界体 → `[[VERB]]`（`_handle_verb`；EOL 上限，字节级 `skip_past` resync）                 |
| 2     | env              | `\begin`/`\end` → 环境路径（§5.7）                                                                                       |
| 3     | cite-ref         | `CITE_NAMES`/`REF_NAMES` 族整调用 → `[[CITE]]`/`[[REF]]`/`[[LABEL]]`/`[[BIB]]`（`_protect_cs`，mand=签名内 m/v/n 位数）  |
| 4     | protect          | `PROTECT_NAMES`（`\url`/`\path`/`\includegraphics`/`\bibliography` 等）→ 整调用 ph（`url`/`path` 支持定界形）            |
| 5     | href             | `\href{url}{text}`：url 组 → `[[HREF]]`，text 组留主流（`_handle_href`）                                                 |
| 6     | input-scan       | `\input` 族漏网 → LITERAL/`[[CMD]]` + `inputs[]`（`_handle_input_cs` 四形）                                              |
| 7     | chunk-arg        | `CHUNK_ARG_NAMES`（`\section`/`\caption`/`\footnote` 等）→ 头参保护 + 可译位独立 chunk（§5.5）                           |
| 8     | protect-block    | `PROTECT_BLOCK_NAMES`（`\author`/`\date` 等）整块 → `[[AUTHOR]]`；散文白名单名先走 `_mine_prose_block`                   |
| 9     | transparent-head | `TRANSPARENT_HEAD_SPEC`（`\textcolor{red}{text}` 族）：头参 → `[[CMD]]`，文本参留主流                                    |
| 10    | box-tail         | `BOX_TAIL_NAMES`（`\hbox to\hsize{..}`）：`to\|spread`+dimen 规格随 cs 进 `[[CMD]]`，`{body}` 照主流                     |
| 11    | transparent      | `TRANSPARENT_NAMES` → 名逐字进 run                                                                                       |
| 12    | boundary         | `BOUNDARY_NAMES` → flush + LITERAL；`BOUNDARY_TAIL`/`DIMEN_TAIL_KIND` 尾参并入盖面；`\item` 置 `force_chunk`             |
| 13    | endinput         | 漏网档：flush + 本文件余下逐字 + `_stop`                                                                                 |
| 14    | cond             | `\if` 族界标/`if*` 双参宏/`\Xtrue` 散件 → LITERAL/`[[COND]]`（`_handle_cond`，`_COND_GROUP_ARGS` 名槽并入盖面）          |
| 15/16 | math-open/close  | `\[`/`\(` 定界数学 → `[[MATH]]`（`_on_math_delim`）；`\]`/`\)` 未配对 → 逐字                                             |
| 17    | bsbs             | `\\` 的 `[dimen]` 可选参命中 → 整调用 `[[CMD]]`（`_handle_bsbs`）                                                        |
| 18    | accent           | `\'e`/`\c{c}` 单参保护 → `[[CMD]]`（`_handle_accent`；参缺席回吐逐字）                                                   |
| 19    | inline-literal   | `INLINE_LITERAL_CMDS`/`FONT_SWITCHES`/单字符非字母命令 → 零参逐字                                                        |
| 20    | macro            | 宏表命中：`env_begin`/`env_end` 走环境路径，`opaque`/`math` → `[[MACRO]]`（`_handle_opaque_macro` spec 走参 + 散文挖掘） |
| 21    | pair-block       | `PAIR_BLOCK_CMDS` cs 对界 DSL（`\labellist…\endlabellist` 形）→ 整段 `[[ENV]]`/孤闭 `[[CMD]]`（`_handle_pair_block`）    |
| 22    | unknown          | 尾参扫 → keyarg → argspec → 探针 → 逐字（`_handle_unknown_cs`，§5.9）                                                    |

组内对价（`_GRP_SURFACE_FAMS`）与跨界待绑对价（`_PEND_SPEC_FAMS`）是同一绑定的另两面投影，行序各自适配组内/槽形语义（`pending.py` 表头注释逐行标注差异点）。

### 5.3 preamble 档

`\begin{document}` 检出前为 preamble 态：`_doc_begin_of`（`_common.py`）双重闸——`mask_tex` 视图 + `BEGIN_DOC_RX` 命中 + `DOCCLASS_RX` 见过 `\documentclass`。态内 token 一律 `_cover_to` 字面盖过，不发 piece（EOF flush 一次性 LITERAL）；例外是 `front_matter` 白名单（`ScanState.front_matter`，`{"abstract","title","author"}` 子集）——命中项走 `_preamble_chunk_arg`/`_preamble_doc_end` 照常 emit chunk（`abstract` env 前置发射、`title`/`author` 经 `_preamble_chunk_arg`）。`\usepackage`/`\RequirePackage`/`\documentclass` 在此态由 `_note_pkgs` 登记 `state.pkgs`（argspec 门控语料，§5.9）；无 `\begin{document}` 的文档在 boundary 行 `_PKG_CMDS` 同点补登记。

### 5.4 覆盖账本与 piece 发射

`_Core` 持 `cons[fid]` 已消费位、`_cover_to`/`_cover_gap`/`_cover_text`/`_emit`/`_emit_ph`/`_rappend`/`_rappend_ph` 一族账本原语：覆盖到指定位 = 间隙字节先收尾当前 piece，目标区间进 vtex 后发 LITERAL/PROTECTED piece 或 run 项。`_ph` 签发经 `PlaceholderIssuer`（§6.2），零宽覆盖不签发。栈弹事件（`pop_seq` 变化）触发源尾字节补盖——`\input` 文件弹栈前其尾部未引字节不蒸发。

### 5.5 chunk-arg 与子扫描

`_handle_chunk_arg`（`segmenter/args/chunk.py`）：`*`? + `CHUNK_ARG_SPEC` 位序头参经 `_args_tok` 拉出，可译位（`tidx` 指定槽）内容 token 喂 `_ListSource` 子扫（`spawn(in_arg=True)`）得渲染串 `_subscan_render`——`_split_rendered` 二次切分（`_pick_cut` 优先级：占位符尾 > `\n\n` > 句读 > 硬切），逐段 `_new_chunk` + `CHUNK_REF` piece。`in_arg` 内嵌套 chunk-arg 内联化并入父 run。可译槽缺席/空参/单 token 参/`gen` 触底 → 全参回放 + 名逐字（`_preamble_chunk_arg` 同判但 bail 一律 `_cover_to`，preamble 档永不中途冲刷）。

`_emit_argspec_chunks` 是其多参推广：argspec `chunk-arg` policy 命令按参序交替发「字面段 → 子扫 chunk」，单 token 文本参起截停回吐；无文本参但有消费 → 整调用 `[[CMD]]`。

### 5.6 展开组机制

`gen>0` token 攒 `_open_toks`/`_open_origin`/`_open_vspan`；组闭合（gen=0 界外 token/副作用 marker/EOF）时：

- `_group_surface` → `_grp_scan`（`pending.py`/`group.py`）：组内 token 列上重走 `_GRP_SURFACE_FAMS` 分派，结构命令再生保护段（`[[MATH]]`/`[[VERB]]`/`[[ENV]]`/`[[CITE]]` 等，体 = 展开表面切片），`eol_par` 切段为同一 run 的 `\n\n` 分隔段；保护族 env 开端点无配对 → 整组 bail 转 literal。
- `_grp_pending`/`_absorb_pending`：组尾右起首个有待绑槽形的 cs 若参扫未尽，从主流 `read()` 拉回调用点参数入组（`\def\r{\ref}` + `\r{key}` 的 `{key}` 跨界绑回 `[[EXPAND]]` 覆盖）；槽形分派 `_pend_spec_of` 镜像主流各行的待绑位，opaque/math 宏走 `_PendRem`（spec 余量 + `("grp",族,残深)`/`("delim",列)`/`("e-arg",)` 续扫态 + key-arg 尾槽）。key-arg 族待绑而未绑到 `{`/`[` 参 → `keyarg_unbound` 告警。
- 副作用组（组内含 `\def`/`\let`/`\catcode` 消费 marker）→ 整组 literal——定义位字节不能折进 `[[EXPAND]]`（译文侧会把 def 删丢）。

### 5.7 环境路径

`_handle_env_begin`/`_handle_env_end`（`env.py`）：`env_name_at` 读名（名内 `%` 段剔除）→ env 查表分派：

- `VERBATIM_ENVS` → 字节级找 `\end{env}`，整段 `[[VERB]]` + `skip_past` resync；`DEAD_ENVS`（comment 族）行锚整行终结、`filecontents*` 行首独占锚。
- `MATH_ENVS`/`_env_dead`/`env-macro` 端点 → `[[MATH]]`。
- `PROTECTED_ENVS`（figure/table/tikzpicture 等）→ `[[ENV]]` 整段保护。
- `ARG_TRANSPARENT_ENVS`/`env_opt_is_format`（`model.py`，F6）：`[opt]` 版式参吃掉、标题正文参放行。
- `ENV_MANDATORY_ARG`/argspec env 条目/`EnvDef.spec` → `_eat_env_args`/`_eat_env_args_spec` 尾参走参（位序 spec 驱动，非文本槽不裸进 surface）。
- 其余 env：`\begin` 行 → `[[ENVTAG]]`，体照常主流（透明容器）；`\end` 配对弹 scope。

`_find_env_end` 五路找尾（`env.py`）：`\begin`/`\end` 计深、`\end<env>` 字面宏端点、csname 合成端点、宏端点事件、verb/verbatim 体跳扫。失败配对进 `_env_dead` 墓标（`_EnvDeadTok`：`env_sig` scope 快照为作废键，迟到 `\def` 改义端点宏即失效重扫；surplus-equality S(seq) 应答防同构重扫）。`unclosed_env`/`env_mismatch`/`stray_end` 告警按实际失败形态记。

### 5.8 数学配对

`_on_math`（`mainloop.py`）：`$`/`$$` 开 → token 级闭符扫描——`pictex` 环境内与内层 env 里的 `eol_par` 不判界；`\)`/`\]` 混排闭符认作闭符（LaTeX 数学态语义同 `$`/`$$`）；`\text` 族正文参整段跳扫（`_math_skip_textarg`）；闭符到达 → `[[MATH]]` 进 run。未配对 → 不产 MATH 段：孤 `$`/`$$` 折 `[[CMD]]` 单项保真 + `unpaired_dollar` 告警（EOF 中止且 `eof_pops` 时余下字节整盖 LITERAL）。v1 的 math_debt 记账已并入主流退役，`debt_repair` 告警种不再产出（名留存于 `ScanWarning.kind` 枚举注释）。

### 5.9 未知命令链与 argspec

`_handle_unknown_cs`（`segmenter/args/handlers.py`）五段链：

1. **尾参扫**：`DIMEN_TAIL_KIND`/通用 `=ATOM` 赋值扫（`_tail_scan_end`）命中 → `[[CMD]]` 整调用（裸 `3pt`/`to\hsize` 操作数不落译文面）。
2. **keyarg**：宏表命中未展开（xprotect/gen-cap/bail）时 `_keyarg_tail` 解宏体尾 cs（`\def\r{\ref}` 形，别名链深 ≤4）→ 命中 cite/ref/PROTECT 族按该族 protect 调用；参缺席 → cs-only 保护 + `keyarg_unbound`。
3. **argspec**：`m is None` 才查 `tables.argspec_lookup(name, state.pkgs)`[^ctan-argspec]——`data/argspec.json` 的 `ArgspecEntry`（signature + `arg_roles` text/opt-text/key/verbatim/skip + `policy`）驱动 `_handle_argspec_cs`：`verbatim` → 逐字读参整调用；`literal`/`transparent` → 名进 run；`boundary` → flush+LITERAL；`protect`/`key` → 整调用 `[[CMD]]`；`chunk-arg` → §5.5 推广。transparent/boundary 条目实际被同名族表先截获（到即记 `argspec_shadowed`）。
4. **探针**：`[o]`? + `{m}`×6 投机读参（`allow_single_token=False`——禁单 token 参，`\foo x` 的 `x` 是正文）；命中 → `[[CMD]]` + 散文参挖掘（`_prose_args_of`/`_opaque_arg_prose`：keyval 形状门 `_kv_list_shaped`/`_KEYVAL_GROUP_RX`、逗号名单 `_COMMA_LIST_RX`、零宽 `\index`/`\label` 剥除后 ≥4 连词判据；`_SWALLOW/_DEAD/_DEAD_TAIL` 名闸先滤），散文参抠出子扫渲 surface，结构段仍 `[[CMD]]`。
5. **逐字**：全不命中 → `_rappend_tok`。

尾随 keyval 组（`\author{n}[orcid=..]`、`\printbibliography[title={..}]`）由 `_keyval_tail_end` 续吃并入保护段。`\tikz` 裸路径形（`\tikz <path>;`）在 argspec protect/key 臂有 `;`-定界专扫 `_tikz_tail_end`。

### 5.10 in_arg 子扫

`spawn(in_arg=True)` 子扫共享 `ScanState` 单引用（issuer/ph_map/chunks/macros/inputs/warnings/ph_reserved/pkgs/front_matter）：参内容 token 经 `_ListSource` 重放走同一主循环，产出 piece 渲染串回填父 run/chunk。in_arg 下 env 整段/`[[COND]]`/`[[ENVTAG]]`/`[[COMMENT]]`（`_arg_comment_ph` 把渲染串裸 `%` 段折 COMMENT ph）等只在参内出现的 ph 类在此产出；边界命令/pair-block 等在参内折 `[[CMD]]` 进 run。子扫消费位经共享覆盖账本直落父区间。

### 5.11 scope 回报与告警汇流

分段器在 lbrace/rbrace/`\begin`/`\end`/数学开关处 `src.scope_push/pop` 回报 gullet 宏表（§4.4）。`scan_v2` 收尾把 `gullet.warnings`（pos 已按 fid 前缀）并入 `state.warnings` 输出。

## 6. chunk 契约

### 6.1 Chunk/Piece/PhType

`model.py::Chunk`：`id`（`chunks[]` 索引）、`content`（渲染形，可内嵌 `[[TYPE_n]]`）、`context`（`"para"`|`"item"`|`"abstract"`|chunk-arg 命令名——`"paragraph"` 专指 `\paragraph`）、`span`（vtex 区间）、`env`（env 栈顶名）、`placeholders`（体内占位符多重集——译文契约校验基准）。

`Piece.kind` 三态：`LITERAL`（原文切片）/`PROTECTED`（`[[TYPE_n]]`，体在 `ph_map`）/`CHUNK_REF`（`[[CHUNK_n]]`，体在 `chunks`）。`PhType` 18 枚举：`MATH|VERB|ENV|CITE|REF|LABEL|URL|GRAPHICS|BIB|CMD|HREF|MACRO|KEY|AUTHOR|COMMENT|COND|ENVTAG|EXPAND`；`COMMENT`/`COND`/`ENVTAG` 只出现在 chunk 内部（in_arg 产物）。嵌套无深度限：`[[ENV_n]]` 体可含 `[[CHUNK_k]]`，展开按 DAG（构造无环，`expand` 活动集兜底）。

### 6.2 占位符签发

`placeholder.py::PlaceholderIssuer` 单一单调计数器，跨子扫描共享；`new(typ, body, ph_map, reserved)` 签发 `[[TYPE_n]]` 并登记 `ph_map`。`ph_reserved`（`ScanResult.ph_reserved`/`ScanState.ph_reserved`）= 源文自带 `[[X_n]]` 形字面集——签发撞上顺延编号（identity 不破），且字面原样过 pieces 时 `validate_result`/`reconstruct` 据此豁免 dangling 误报；采样在 scan 主循环按 `file_texts` 懒增长。`[[CHUNK_n]]` 与 `[[TYPE_n]]` 同语法不同表（`CHUNK_RX` vs `PH_RX`），reconstruct 统一按 DAG 展开。

### 6.3 chunk 切分

`CHUNK_MIN`（20，去命令/非字母后字符数下限，低于则 run 不冲刷成 chunk）/`CHUNK_MAX`（4000，超限 `_split_rendered`/`_split_bounds` 二次切分）；切点 `_pick_cut` 优先级：占位符尾 > `\n\n` > 句读断点 > 硬切。`force_chunk`（`\item` 后首 run）豁免 MIN 闸。

### 6.4 散文门与树扫描

`prose.py`：`is_prose` = `context ∈ PROSE_CONTEXTS`（标题/脚注/caption 类结构名）∨ 剥占位符后 ≥3 字母词中 ≥3 个不同 `FUNCWORDS` 功能词（PS 算子 `and|not|or|if|for` 不入表）。`file_has_prose` 任一块命中即内容件。

`api.py::scan_tex_tree` 四级分流：dotfile 跳过 → `.rtx.tex`（REVTeX 转储）跳过 → `.code.tex` 记 `support` → tar 伪装件跳过 → 解析崩记 `fault`（按原文保留）→ 无散文记 `support` → 余者 `parsed`（`flatten=False` 单文件语义）。`NAME_GATED_TEX_SUFFIXES` 是 `.tex` 名闸单源。

## 7. 陷阱与边界

- **参数扫描不跨 `eol_par`**：`ws_skip_arg`（`model.py`）`\n\n` 即停、`%` 注释透明跳过（幂等停位）；token 版 `_peek_nonspace`/`_args_tok`/`_collect_group`/`_absorb_*` 同规——`eol_par`/`gen>0`/异 fid token 是参扫硬界（回放不消费）。
- **回放纪律**：一切拉取路径放弃时必须全量 `unread`（pulled + 目标 token）——否则 ws/参字节从 surface 消失；`_collect_group` EOF 截断回吐全部已拉（`unmatched_open` memo 只在 `_ListSource` 等回放源生效，Gullet 恒 `None`）。
- **`%` 与 verbatim**：注释在 Mouth 即吞；verbatim env/`\verb` 内 `\input`/`\end{document}`/数学符全不触发；`skip_past` resync 失败记 `verb_resync_failed` 退化逐字流。`\url`/`\href{url}`/verbatim-policy 参按字节级 `match_brace(verbatim=True)` 读——`%` 在参内是字面。
- **`\if` 界标**：非求值档双支自流靠「`\else`/`\fi` 各自出 LITERAL 界标」等价收集回放，verb 体假 `\fi` 由 verb 处理器天然挡；`_COND_GROUP_ARGS` 白名单的名/表达式槽 `{..}` 并入界标盖面（机器槽不译），`{T}{F}` 支留主流。
- **尾参**：`BOUNDARY_TAIL`（位序 spec）、`DIMEN_TAIL_KIND`（`dimen`/`assign`/`boxspec` 字节扫 `_tail_scan_end`，`_TAIL_CAP` 上限）、`_keyval_tail_end`（keyval 续组）三族——裸操作数/单位/键值位不裸进 surface（illegal_unit/`Package keyval Error` 防线）。
- **`\end{document}`/`\endinput`**：前者只顶层截停（preamble `_preamble_doc_end`/主流 `_tail_scan_end` 后整盖 LITERAL + `_stop`）；后者弹当前文件 + consumed marker，漏网档整盖本文件余下。
- **active 字符**：`~` 等作 `active` token 进 run（nbxp 语义保留），`\ifcat` 等比对按 kind+text。
- **跨 fid 字节**：组内/`in_arg` 的异 fid token 不做字节切片判形（判据失效），回放/保守路径兜底。
- **告警面**：`unclosed_env|unpaired_dollar|stray_end|def_parse_fail|letters_cut|expansion_overflow|if_unterminated|missing_input|gen_overflow|ph_collision|env_mismatch|argspec_shadowed|expand_tail_dropped|keyarg_unbound|bibitem_paren|cite_range_key|verb_resync_failed|pieces_gap|dangling_ph|dangling_chunk_ref|orphan_chunk|dead_ph`（`ScanWarning.kind` 实际产出集；`debt_repair` 名存无产）。

## 8. splice 重建与译文修正

`reconstruct/core.py::reconstruct(res, translations=None)`：`None` → identity（逐字节 = 原文，硬验收）；否则 `{chunk_id: 译文}` 预处理（`_restore_linestarts` 行首 `\cs` 归位 → `unicode_math_fix` 游离数学字符包 `$..$` → `LATIN_ITEM_RX` `\item大写` 融合保险丝）后经 `expand`/`expand_body` DAG 递归展开：token 优先级 `trans → ph_map → chunks[content]`，memo 化 O(总规模)，活动集防译文侧自指环；查无实体且非 `ph_reserved` → 留字面记 dangling。短参 chunk（`context` 非 `para`/`item`）展开后 `\n\n` 压单 `\n`（`PAR_RUN_RX`——`\caption` 等非 `\long` 参内 runaway 防线）。`seg_join` 接缝守卫（`\cs` 尾 + 字母头插空格）在段级与总段级两级生效，仅译文路径启用。译文存在时再跑 `cjk_glue_fix`（`\cmd这是` → 插空格）与 `cjk_punct_close_guard`（CJK 标点后贴 `\end{`/`\)`/`\]` → 插 `{}` 断 xeCJK CheckFullRight 前瞻链），均取 `mask_tex` 视图命中、逆序回放。

## 9. 校验

层内两件（`reconstruct/validate.py`）：`validate_result(res)` 结构校验——pieces 平铺（`pieces_gap`）、protected_tex→ph/chunk 递归可达性（`dangling_ph`/`dangling_chunk_ref`/`orphan_chunk`/`dead_ph`，`ph_reserved` 字面豁免）；`validate_translation(chunk, text)` 译文契约——`chunk.placeholders` 多重集逐枚在译文出现（`missing`/`extra` 差集）。

层外契约：L0 规则校验 `validate/l0/main.py::validate_pair`——14 项 src↔zh **相对**判定（「译文不得比原文更坏」，src 自带不平衡不追责）：placeholder multiset + 序守恒 warn + 结构占位符脱位、brace/env/key/math 配对、length 代理比带、same_source 回显、residual_en 残英、macro/item_glue/bare_cs 新增 cs 防线、protocol_echo 协议回显、comment_eof 注释终结。stdlib 零依赖 always-on，独立于本层解析器（异构校验原则）[^validator]；完整规则表见 `spec/validate.md`。

## 10. 限制清单

- 展开面只有 `transparent_expand` 一类真展开；env_begin/env_end/opaque/math/transparent_inline 均不展开（调用点保护链兜底）。可展开原语集 = §4.3/§4.5 表，表外 TeX 原语（`\the`/`\number`/`\string`/`\advance`/寄存器赋值等）不展开，落 unknown/argspec/探针路径。
- xparse `v`/`b`/`E`/`x` 参数型的 `\NewDocumentCommand` 定义不登记；`\romannumeral` 只到 3999；`\includeonly` 忽略。
- `flatten=False`/纯内存源下 `\input` 恒不解析；`MAX_INPUTS=8`/`BUDGET=100_000`/`MAX_GEN=32` 三道闸触底即停展开（记告警，内容保守保真）。
- `\if` 非求值档不裁支——双支都进译文面（结构界标保护）；求值档只认 §4.7 表内谓词。
- 旧规格有而当前未落地/已退役：v1 字节扫描器（删除）、`math_debt`/`debt_repair` 修债 pass（并入 `_on_math` 主流退役）、`protect_args` 调用点位序保护（字段照算、无消费方——由展开再生 + keyarg 链替代）、`\includeonly` 过滤（有意不做）。

### 参考文献

[^adr-semi]: TeXlate 决策记录。ADR-0002 LaTeX 半解析：自研 scanner + pieces 区间 splice. 本库 `decisions/adr/0002-semi-parsing.md`.

[^miniscanner]: TeXlate 调研档案。miniscanner 扶正重写实施规格。本库 `research/latex/miniscanner-rewrite-spec.md`（主仓 `docs/research/latex/` 同名件）.

[^exp-design]: TeXlate 调研档案。宏展开层设计规格——扫描中即时展开（gullet 模式）. 本库 `research/latex/expansion-design.md`.

[^exp-timing]: TeXlate 调研档案。宏展开时机语料实验——即时展开 vs 二遍展开。本库 `research/latex/expansion-timing.md`.

[^ctan-argspec]: TeXlate 调研档案。CTAN argspec 签名表导出 + 语料覆盖率实验。本库 `research/latex/ctan-argspec.md`.

[^validator]: TeXlate 调研档案。规则校验器原型——译文机械不变量校验。本库 `research/latex/validator-rules.md`.
