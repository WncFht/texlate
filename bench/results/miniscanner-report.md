# miniscanner 半解析器 spike 评测报告

- **实现**: `bench/py/miniscanner.py`(~1180 行，其中 ~150 行命令族表；单文件、零依赖、纯 Python)
- **架构**: 容错分割 + 占位符保护 + 区间替换重建。**不做 AST**：单次正向逐字符扫描 → pieces 流(`literal` / `[[TYPE_n]]` 保护占位符 / `[[CHUNK_n]]` 可译块）→ `protected_tex` + `chunks[]` + 宏表 → `reconstruct` 按 pieces splice + 占位符统一**不动点展开**
- **测试**: `bench/py/miniscanner_test.py`；数据 `bench/results/miniscanner-parse.json`
- **基线**: ieeA(`bench/results/ieeA-baseline-report.md`,16 过/3 半/7 败，泄漏 10.24%,identity 重建 0/93)
- **日期**: 2026-09-14

## 1. 一句话结论

架构验证成功：**陷阱断言 32/32 全过**(ieeA 16/3/7)，语料泄漏率 **0.11%**(ieeA 10.24%，约 93 倍改善）,**identity 重建 259/259 字节级一致**(ieeA 0/93 全 diverged)，假译文重建 **0 死占位符 / 0 孤儿 chunk**(ieeA 10 文件 16 处死 token)。单次正向扫描 + 区间替换模型可行，且天然免疫 ieeA 的全部五类结构性 bug。

## 2. 语料解析鲁棒性 (PROTOCOL §1)

语料已扩充至 39 个 arXiv 项目、**256 个 .tex**（含 amsart/revtex4/elsarticle/aastex/法语 babel/bussproofs/LaTeX2.09 ptptex 等）。

| 指标 | miniscanner | ieeA(90 文件旧语料) |
|---|---|---|
| 成功 | **259/259 (100%)** | 93/93 (100%) |
| 失败/超时 | 0 | 0 |
| 耗时 | min 0.0ms / 中位 **1.3ms** / p95 22.5ms / max 253ms | 中位 22.6ms / max 740ms |
| 总 wall | 102.7s(含 flatten+recon+leak 统计) | 5.6s |

零崩溃同样是"不认识的构造按字面放过"的容错收益；比 ieeA 快 ~17×（无每文件 `fc-list` 15ms 底噪 + 单遍扫描）。最慢文件 `qit-notes.tex` 253ms(44 万字符，长 `$` 配对扫描）。

## 3. Fixtures 陷阱断言矩阵 (PROTOCOL §2)

tricky.tex 全 25 项 **pass**(ieeA: 16 pass / 3 partial / **7 fail**):

| ID | 构造 | miniscanner | ieeA | 关键机制差异 |
|---|---|---|---|---|
| T01 | `\be…\ee` 宏展开数学环境 | **pass** `[[MATH_n]]` | FAIL | 宏表 `env_begin`/`env_end` 类属 + `_find_env_end` 识别宏端点 |
| T02 | `\dR` 数学宏 | **pass** `[[MACRO_n]]` | FAIL | 宏体无自然文本→`opaque`→整调用保护 |
| T03 | `\def\wt` | pass | pass(侥幸) | preamble 逐字 + `\def` 显式登记宏表（非靠位置） |
| T04 | natbib 全族 + ref 族 | **pass** | FAIL | cite/ref 词族匹配（`cite*` 前缀、`*ref` 后缀），`[see][chap.~2]` 双可选参+key 整段保护 |
| T05 | `\section[Short]{Long}` | **pass** | FAIL | `_args` 通用参数读取：`[opt]` 跳过、`{arg}` 括号计数→chunk |
| T06 | verbatim 内 `%` | **pass** | FAIL | 逐字环境**先识别**(整段 `find(\end{verbatim})`)，注释判定时其内容已被吃掉 |
| T07 | `\url{..%20..}` `\verb\|a%b\|` | **pass** | FAIL | `\verb` 按分隔符原样吞；`\url` 参数用 `verbatim=True` 括号匹配（`%` 不当注释） |
| T08 | 注释边界 `\%` `\\%` | **pass** | partial | 逐字符 tokenize:`\%` 先被单字符命令吃掉→裸 `%` 必为注释；`\\%` 自然判对，无需 lookback |
| T09 | `\author[1]{…\and…}` | pass | pass | `[opt]`+`{arg}` 整段 `[[AUTHOR_n]]`，正文区同样有效（ieeA 只在 preamble 碰巧对） |
| T10 | subequations/align/flalign | **pass** | partial | 数学环境族 25+ 全量（含 `*`),`_find_env_end` 同名嵌套计数 |
| T11 | `theorem[Main Result]` | pass | pass | 未知环境=透明：`\begin` 行字面 piece，正文正常分块 |
| T12 | caption 内 footnote | pass | pass | caption arg 子扫描 `_arg_inline` → footnote 文本并入父 chunk |
| T13 | `\ifdraft…\else…\fi` | **pass** | partial | 条件命令=`boundary` 字面 piece，不进 chunk;`\newif` 注册 `\drafttrue/false` |
| T14 | `\input` 递归+注释掉的 | **pass ×4** | FAIL(嵌套) | `flatten_inputs` 先当前文件目录再主目录（LaTeX 语义）；逐字符扫 `%` 行内 `\input` 不展开 |
| T16 | `\NewDocumentCommand` | **pass** | pass | spec 串 `m`/`o` 解析参数形状 |
| T17 | 数学内 `\text{}` | pass | pass | 随 `[[MATH]]` 整体保护 |
| T18 | figure 内 caption | **pass** | pass(侥幸) | `figure` 显式在保护表；内部 `mined_only` 子扫描挖 `\caption{→chunk}` |
| T19 | abstract | pass | pass | 透明环境，内部文本正常分块 |
| T20 | itemize 等 | **pass** | pass | `\item`=边界+`_force_chunk`（短 item 不受 20 字符阈值弃译） |
| T21 | `\includegraphics[opt]` | pass | pass | `[[GRAPHICS_n]]` |
| T22 | `\href{url}{text}` | pass | pass | url→`[[HREF_n]]`,text 并入段落 chunk（注意 `endswith("ref")` 需显式排除 `href`，踩过一次） |
| T23 | `\emph\textbf\textit` | **pass** | FAIL | 透明命令：命令字面+参数内联扫描并入段落 chunk，无"洗文本后 <20 字符弃译" |
| T24 | `\bibliography` | pass | pass | `[[BIB_n]]` |
| T25 | `\makeatletter` | pass | pass | 边界字面 |
| T26 | `\[ \]` `\( \)` | pass | pass | `[[MATH_n]]` |
| T27 | `\'e \"u \~n` | pass | pass | 单字符重音命令=行内字面 |
| T29 | 独立 footnote | pass | pass | footnote arg→独立 chunk（不受阈值限制） |

tricky-209:**3/3 pass**(`\beq…\eeq` 同 T01 机制；`\documentstyle` 走 preamble 判定）。tricky-multi:**4/4 pass**（嵌套 `\input` 相对主目录解析成功——ieeA 在此找 `sub/sub/nested` 失败；注释掉的 `\input` 逐字符扫描天然不展开）。

## 4. 泄漏率 (PROTOCOL §4)

| 指标 | miniscanner (256 文件) | ieeA (90 文件) |
|---|---|---|
| 可译 chunk 总数 | 23,427 | 3,536 |
| 含泄漏 chunk | **25 (0.11%)** | 362 (10.24%) |
| `$` 命中 | 18 | 97 |
| `\cite` 族 | **0** | 201 |
| `\ref` 族 | **0** | 88 |
| `\begin{` | 3 | 22 |
| 条件命令 | 4 | 1 |
| 零泄漏文件 | 239/256 (93%) | 37/93 (40%) |

`\cite`/`\ref` 命中归零——词族匹配 + 透明宏参数位置保护（`\figref{key}`→`\figref{[[KEY_n]]}`）覆盖了 ieeA 最大泄漏源（natbib 201 处）。

**残留 25 处的失败模式**（均为边界退化，非架构缺陷）:
- **`$` 错配**(18)：某保护段（如 `\newcommand` 体内的 `$…$`、unknown-with-braces→`[[CMD]]`）吞掉一个 `$` 后，后续 `$` 配对错位，留下奇数裸 `$`。例：`[[CMD_319]]ta\from \Set \to …[[MATH_322]]\Delta$.`——修法案：保护段内的 `$` 计数参与配对，或对未配对 `$` 做后验局部重扫。
- **`\begin{`/条件命令**(7)：个别 chunk-arg 参数扫描在 `mined_only` 下遇到未注册 `\if` 变体或 `\begin` 字面——字面保留不破坏文档，仅少翻一句。

## 5. 重建保真 + 占位符残留 (PROTOCOL §3)

| 指标 | miniscanner | ieeA |
|---|---|---|
| identity 重建 | **259/259 identical**(对展平文本字节级一致） | 0 identical / 0 normalized / 93 diverged |
| 假译文 `[[CHUNK_n]]` 残留 | **0** | 10 文件 16 处 |
| `[[X_n]]` 保护残留 | **0** | 0 |
| 孤儿 chunk（占位符不可达） | **0** | 0 |

identity 满分来自区间模型的两条不变式：(1) pieces 覆盖全文——注释/preamble/`\end{document}` 之后全部逐字保留，无任何信息在 parse 阶段被删除（ieeA 在 parse 里删注释/展平/注字体→不可逆）;(2) chunk 占位符可出现在任意位置（顶层 piece、`\caption{[[CHUNK_n]]}`、`[[ENV]]` 体、另一 chunk 内）,reconstruct 用**同一张替换表迭代至不动点**——嵌套深度不限，天然消灭 ieeA"chunk→ENV→CHUNK 三层逃出单层遍历"的死 token。

## 6. 架构心得

### 最难的规则（按调试耗时排序）

1. **piece 边界纪律**。最大的坑不是识别命令，而是"什么东西进 run、什么东西独立成 piece"。初版把 `\item`/`\end{env}`/`\section{…}` 前缀/`[[ENV_n]]` 都 `run.append` → 边界 token 并入相邻段落 chunk(T13 `\ifdraft` 泄漏）或段落 chunk 吞掉 `[[ENV]]` 占位符（复刻 ieeA 死 token 机制）。规则收敛为：**块级结构（`\begin/\end/\item`/条件命令/保护/逐字环境/chunk-arg 命令三段）一律 `_emit` 独立 piece；行内保护（数学/cite/ref/verb/宏）留在 run 内作占位符**。
2. **占位符计数器跨子扫描器共享**。`_env_with_mined`/chunk-arg/宏参数都要递归子扫描；`int` 计数器值传递导致子扫描器内占位符与后续父扫描器**编号冲突**——两个不同内容共用 `[[ENV_7]]`,replace 阶段互相串扰出重复文本。改共享 `list[int]` 计数器解决。教训：递归子扫描的所有可变状态（chunks/ph_map/计数器）必须引用共享。
3. **`%` 的三态**（注释/`\%`/`\\%`)。逐字符 tokenizer 里这题自动消解：`\` 开头的单字符命令先把 `\%` 吃掉，能到达 `%` 分支的必是真注释——**不需要 ieeA 的 lookback 正则**。但前提是 verbatim/`\verb`/`\url` 参数在 `%` 判定前已被整段吃掉（顺序即一切）。
4. **`$` 配对**。只判"下一个未转义 `$`"+"不含空行"就够；难点在保护段吞 `$` 后的错配（§4 残留）。未配对回退为字面 `$` 是正确容错。
5. **宏表三分类**:`env_begin`（纯 `\begin{X}`)/`opaque`（无自然文本，整调用保护）/`transparent`（有文本，按参数位置分流——`\ref`/`cite` 位→`[[KEY]]`，文本位→子扫描）。`\figref#1→figure~\ref{#1}` 这类半文本半引用宏靠 `_protected_param_positions` 逐参数判定，是防 key 泄漏又不误伤文本的关键。

### 递归/边界处理

- **环境端点**:`_find_env_end` 同名 `\begin/\end` 计数 + 宏端点识别（`\ee`≡`\end{equation}`)+ 注释安全（`%` 行内 `\end` 不计）。verbatim 类用**字面 find**（内部 `\end` 注释也算真结束——与 TeX 一致）。
- **chunk-arg 递归**:`\caption{A \emph{B} $x$ \footnote{C}}` → 子扫描产 rendered(`\emph{B}` 内联、`$x$`→`[[MATH]]`、footnote 内联）→ rendered 作 chunk 内容。嵌套 chunk-arg 用 `_arg_inline` 内联化（footnote-in-caption 并入父 chunk,footnote 独立时自为 chunk)。
- **保护环境递归**:`figure→[[ENV_n]]`，体内 `mined_only` 子扫描（段落不分块，只挖 `\caption/\footnote`)→ `[[ENV]]` 值内嵌 `[[CHUNK]]`，不动点展开兜底。
- **容错总原则**：任何匹配失败（找不到 `\end`、括号不闭、`$` 无对）→ 已识别的最小前缀保留为字面/并入 run,**扫描指针绝不回退、绝不抛异常**——这是 259/259 零崩溃的来源。

### 与 ieeA 管线的本质差异（教训落地）

| ieeA 病灶 | miniscanner 对应设计 |
|---|---|
| 注释剥离跑在 verbatim 识别前 → `%` 全灭 | 单遍扫描内 verbatim **先整段消费**,`%` 判定后到 |
| caption/title 先于保护抽取 → 块内 `\cite` 裸漏 | chunk 抽取在保护扫描**之中**递归，块内先占位 |
| 零宏语义 → `\be`/`\dR`/natbib 全灭 | 前置宏表 + 调用点三分类查表 |
| 逐行正则 → `[opt]`/`\\%`/`\verb` 全错 | 逐字符 tokenizer + 通用 `_args` 读参 |
| 单层替换 → 三层嵌套死 token | chunk+保护占位符统一不动点 |
| `<20` 阈值弃译 + 条件命令混入 chunk | `\item` 后 force-chunk；条件命令 boundary piece；阈值仍保留（防碎块） |

### 已知边界 / 后续方向

- tabular 单元格文本在 `[[ENV]]` 内不挖（保护环境内只挖 caption/footnote)→ 表格正文不译，协议允许，产品上可配。
- 未知命令带 `{arg}` 一律 `[[CMD]]` 保守保护：防 key 泄漏有效，代价是自定义文本宏（`\ours{方法名}`）不译——需要宏表覆盖率补充或配置开关。
- `\input` 展平在 parse 前置做（注释/verbatim 感知）；协议允许的"只记引用点不展开"由 `inputs[]` 保留支持。
- 超长 `$` 配对最坏 O(n²)（实测 253ms/44 万字符，可接受）。
- 体积 ~1180 行，超 spike 目标（600-900)；命令族表与宏定义扫描占大头，可压缩但当前形态利于审计规则顺序。
