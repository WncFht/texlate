# scanner.py 审计报告（2026-09-15）

**结论**：`src/texlate/latex/scanner.py` 整体健康——400 篇 corpus_v3 抽样 identity 重建 100%、`validate_result` 零告警、官方泄漏口径 3 例且全是 `\$` 度量误报；但发现 12 个可辩护缺陷：1 个崩溃级（`match_bracket` 递归爆栈，违反铁律 1）、4 个语料实测有频率的语义缺陷（`\title[opt]` 错位 6.4%、`\newenvironment` `[n][d]` 丢弃 1.5%、命令与参数间注释断参 1.5%、数学闭合符不跳注释 ~0.3%）、1 个规格级召回缺口（theorem 类环境 `[opt]` 标题被吃 8.3%）、外加切分/`if` 求值/verbatim 收尾/`e`-spec/`\url|delim|`/性能悬崖各一。

方法：全文通读 scanner.py(1499 行）+ model.py/placeholder.py/reconstruct.py/tables.py/macro_table.py/textutil.py + docs/07 契约；`uv run python` 实跑 parse_tex/reconstruct 验证每条疑点；触发频率用 corpus_v2+v3 共 1919 个 .tex 统计。

## 处置状态（2026-09-15 同日修复批）

| # | 处置 |
|---|---|
| F1 | 已修：`match_bracket` 迭代化（model.py），1500 层不爆栈 |
| F2 | 已修：CHUNK_ARG_SPEC 五条 `("m",0)`→`("om",1)`（tables.py） |
| F3 | 已修：`newenvironment` 双 bracket 循环对齐 `newcommand`（macro_table.py） |
| F4 | 已修：`ws_skip_arg` 注释透明 + par 对内重入幂等（model.py；含 `% c\n\n` 仍停边界） |
| F5 | 已修：`$$`/`$` 闭合扫描跳注释、新行态 `\n` 即 par（scanner.py `_on_dollar`） |
| F6 | 待决：规格层召回缺口（theorem 类 `[opt]` 标题 8.3%）——需 leader 定口径 |
| F7 | 已修：`_split_core` 硬切改全 core PH_RX 扫描（scanner.py） |
| F8 | 误报：真实 TeX 的 verbatim 收尾就是字面 `\end{verbatim}`，`%` 在体内惰性——裸 `find` 行为正确，不改 |
| F9 | 已修：`` `\X `` 转义形消费 3 字符取 `ord(X)`（scanner.py `_read_number`） |
| F10 | 已修：`e` token 表入 `ArgSpec.delim` + `_args` 消费 `^{..}`/`_{..}` 全段；`b`/无 delim/未知 kind 一律零宽占位——`len(args)==len(spec)` 位序不变式成立 |
| F11 | 已修：`_protect_call` 增定界符形 `\url|…|`（scanner.py，EOL 上限对齐 `\verb`） |
| F12 | 待修：未闭合 env O(N·n) 悬崖（需缓存/限距，排入下一批） |

修复均有 `tests/test_latex_audit.py` F 系列钉（9 条）防回归。

---

## Findings（按严重度排序）

### F1. `match_bracket` 递归 → RecursionError（违反铁律 1「绝不抛异常」）

- 位置：`src/texlate/latex/model.py:269-272`（`if c == "[": e = match_bracket(tex, j)` 自递归）；scanner 侧入口 `_args` scanner.py:535（o/m 参）、`_protect_call` scanner.py:1472、`_eat_env_args` scanner.py:967、`skip_verb_at` model.py:338（`\lstinline[`）、`scan_macro_def` macro_table.py（`[n]`/`[def]` 读取）。
- 触发输入：`\cite` + `[`×1500 + `x` + `]`×1500（或 `\section[`/任意未知命令 `\foo[`/`%\begin{env}[` 后接深嵌套 `[`）。
- 实测：`depth=1500 RecursionError`（depth=500 正常；Python 默认 limit=1000，每级一帧 → ~990 嵌套即崩）。`parse_tex` 整体抛异常，该文件在 e2e/parsebench 里直接判死。
- 预期 vs 实际：铁律 1 要求绝不抛异常；实际深嵌套 `[` 直接 `RecursionError`。
- 严重度：**崩溃**（真语料中 >990 层 `[` 嵌套概率≈0，但单篇病理文件即可杀死整个文档解析）。修法：改迭代（与 `match_brace` 的 depth 计数同形）。

### F2. `\title`/`\subtitle`/`\thanks`/`\abst`/`\keywords` spec=`"m"` → `[opt]` 被当正参，真标题落正文 chunk

- 位置：`src/texlate/latex/tables.py:150-154`（`CHUNK_ARG_SPEC` 五条 `"m"` 规格）+ `_args` 'm' 分支读 `[` 走 `match_bracket`（scanner.py:521-526）+ 目标选取 scanner.py:1037-1042。
- 触发输入：`\title[Short Cap]{The Real Full Title Of The Paper}`。
- 实测：chunk=`"Short Cap"`；`{The Real Full Title Of The Paper}` 连带花括号并入下一段 chunk。acmart/sigconf 模板 `\title[短题]{长题}` 是标准用法。
- 预期 vs 实际：应取 `{...}` 为可译参数（spec 应为 `"om",1`）；实际 `[...]` 被当唯一参数，真标题连同花括号变成正文文本。
- 严重度：**输出污染**（翻译稿标题换成短题、正文出现 `{长题}` 花括号残留）；corpus 命中 `\title[` 共 123/1919 篇（6.4%）。

### F3. `\newenvironment{env}[n][dflt]` 第二个 `[` 参数未读 → 登记整体丢弃 + 定义尾部回落成文本

- 位置：`src/texlate/latex/macro_table.py:234-241`——`newenvironment` 分支只读一个 `[n]`，`bb` 落在 `[dflt]` 上 `match_brace` 失败 → `return pos`（name 后一位）。
- 触发输入：`\newenvironment{mybox}[1][dflt]{\textbf{#1} begintext}{endtext}`。
- 实测：preamble 里 `envs` 表为空（env 未登记，`kind`/`nargs` 启发全丢）；**正文内**更糟——dispatch 2 `emit` 只覆盖 `\newenvironment`，`{mybox}[1][dflt]{\textbf{#1} begintext}{endtext}` 整段被重扫进 run，实测直接成 chunk：含 `\textbf`、`#1` 等原命令/参数记号泄漏。
- 预期 vs 实际：与 `\newcommand`（macro_table.py:261-276 `for k in range(2)` 读两个 bracket）同形处理；实际整个定义尾巴进可译 chunk。
- 严重度：**泄漏 + 登记丢失**；corpus 命中 `[n][d]` 形态 28/1919 篇（1.5%）。

### F4. 命令与参数之间的 `%` 注释打断一切参数读取

- 位置：`ws_skip_arg`（`src/texlate/latex/model.py:205-220`）不跳过 `%`→EOL；所有经它预读的入口全中：`_args` scanner.py:509、`_protect_call` scanner.py:1471/1480、`env_name_at` model.py:302、`_handle_chunk_arg` scanner.py:1030、dispatch 12 `PROTECT_BLOCK` scanner.py:753、dispatch 9 `\href` scanner.py:706、dispatch 10 `\input` scanner.py:720、dispatch 19 scanner.py:836、`_read_number`/`_read_if_token`（scanner.py:1313/1355）。
- 触发输入：`\section% 注释\n{My Title}`、`\cite% note\n{key2020}`、`\begin%\n{itemize}`。
- 实测：`\section%\n{Title}` → `\section` 逐字 + `{My Title}` 以花括号组落正文 chunk（标题降级为正文）；`\cite%\n{key}` → `\cite` 成 `[[CITE]]`（无参），`{key2020}` 键名+花括号进 chunk 被翻译。
- 预期 vs 实际：TeX 把 `%`→EOL 当空白，参数照常读；实际所有参数读取遇 `%` 即停，参数整体错位。
- 严重度：**语义错位**（键名/标题进译文、花括号残留）；corpus 命中 `\(cite|ref|section|footnote|caption|label)%` 29/1919 篇（1.5%）。

### F5. `$`/`$$` 数学配对不跳注释，与 `_find_math_close` 不一致

- 位置：`scanner.py:449` `tex.find("$$", i+2)` 裸 find；单 `$` 扫描循环 scanner.py:455-471 无 `%` 分支。对照 `_find_math_close`（scanner.py:857-859）与 `_find_env_end`（582-585）都有注释跳过。
- 触发输入：`Math $$ a % b $$ still comment\nc $$ done`。
- 实测：`[[MATH_1]]`=`$$ a % b $$`（吞了注释内的 `$$` 当闭合），注释尾巴 `still comment` 落进 chunk 会被翻译成正文，尾部 `c $$ done` 再留一个未配对 `$$` 进 chunk。
- 预期 vs 实际：注释内 `$`/`$$` 不该作闭合符（与 `\[`-系一致）；实际注释内 `$` 提前关数学 → 注释文本 + 裸 `$$` 都进可译 chunk。
- 严重度：**输出污染**（注释内容排进译文、残留 `$$` 可能让编译端再开数学）；corpus 实测含「数学 ph 体内 `%` 同行还有 `$`」6/1919 篇（~0.3%，多在本来就病态的输入上）。

### F6. `\begin{theorem}[标题]` 的 `[opt]` 被当格式参数吃掉 → 定理标题永不翻译（规格级召回缺口）

- 位置：`_eat_env_args`（scanner.py:962-980）对**任何** transparent/未知环境无条件吃 `[opt]`（966-969），随后 `_emit(i, pos)` 把 `\begin{env}[opt]` 整段 LITERAL。
- 触发输入：`\begin{theorem}[Pythagoras 定理] ... \end{theorem}`。
- 实测：chunk 只有 env 正文，`[Pythagoras 定理]` 整段 LITERAL 不进任何 chunk → 译文里定理名保留英文。对照 `\item[Label]`：`\item` 只 emit 命令名，`[Label]` 随文本流进 chunk——两种可选参数一个翻译一个不翻译，口径不一致。
- 预期 vs 实际：theorem/lemma/proposition/definition/remark 等环境的 `[opt]` 是标题正文，应进 chunk；实际被当版式参数。
- 严重度：**召回缺口**（不破坏 identity，但 8.3% 论文的定理名不翻译）；corpus 命中 160/1919 篇。注：docs/07 §3.5 明写了「吞 `[opt]`」，属规格层缺口而非实现笔误。

### F7. `_split_core` 硬切点可把 `[[X_n]]` 切成两半

- 位置：`scanner.py:305-316`——`PH_RX.search(tail)` 只看 `core[hard-16:hard+16]` 探测窗内**第一个** token 是否横跨切点；token 的 `[[` 落在窗外（长度>16 且起点<hard-16）或窗内首个 token 不横跨而第二个横跨时，`cut=hard` 直接切在 token 中间。
- 触发输入（实测）：core=`"a"*3983 + "[[GRAPHICS_99999]]" + "b"*…`（>4000 且无空格/空行/token 尾切点）→ parts[0] 以 `[[GRAPHICS_99999]` 结尾（少一个 `]`），token 被腰斩。
- 预期 vs 实际：注释承诺「不许切在 `[[X_n]]` 中间」；实际超长 token 起点在探测窗外即失守。
- 严重度：**译文侧契约破坏**（断裂 token 喂给翻译，validate_translation 必报 missing/extra）；identity 不破（parts 拼接逐字节还原）。触发需 >4000 字符 chunk 且自然切点全缺席 + token 卡位——低频但确定存在。

### F8. verbatim 环境收尾用裸 `find`：注释内 `\end{env}` 提前关闭、`\end {env}`/`\end{ env }` 永不匹配

- 位置：`scanner.py:893-901` `pat="\\end{"+env+"}"; tex.find(pat, j)`——不跳注释、不容 `\end` 与 `{` 间空白（对比 `env_name_at` 用 `ws_skip_arg` 容空格）。
- 触发输入 A：`\begin{verbatim}` 体内一行 `% \end{verbatim}` → VERB 段在注释处提前闭合，真实 `\end{verbatim}` 及其后的代码尾巴按正文重扫；B：`\end {verbatim}`（带空格）→ `find` 不中 → `unclosed_env` + 整个 verbatim 体按正文解析（`$`/`%`/`\cmd` 全泄漏进 chunks）。
- 预期 vs 实际：注释内 `\end` 不应收尾（TeX 语义）；带空白的 `\end` 应可识别（`env_name_at` 本来支持）。
- 严重度：**泄漏面**（代码行/注释进可译 chunk）；`\end {verbatim}` 变体 corpus 0/1919，注释内假 `\end` 频率未单独统计但属于同一行修复。

### F9. `_read_number` 对 `` ` `` 字符码把 `` `\X `` 读成 ord('\\')=92 且只吃两字符

- 位置：`scanner.py:1328-1329`——`if c in "'`" and pos+1<n: return sign*ord(tex[pos+1]), pos+2`。
- 触发输入：`\ifnum`\A=65 yes…\else no…\fi`（`` `\A `` TeX 语义=A 的字符码 65）。
- 实测：读到的是 `ord('\\')=92` 且只消费 `` `\ ``，`A` 留在外面 → 后续 `A=65` 残片直接进 chunk（实测 chunk=`"A=65 yes-branch text that is long enough…"`），且求值结果错误（`92` 而非 65）。
- 预期 vs 实际：`` `\ `` 转义形应取转义字符的码、消费 `\`+`X` 两个字符；实际值错、消费错位、条件残片落文本。
- 严重度：**低-中**（`` `\X `` 在正文条件里少见，但错值会选错分支）。

### F10. `_args` 对 `e`/`b` 型 ArgSpec 静默跳过：参数位序错位 + 后续 `{arg}` 落文本

- 位置：`scanner.py:568`（注释「不消费」）——`for s in items` 对 `e`/`b`/未知 kind 无分支、不 append ArgSpan、pos 不前进。
- 触发输入：`\NewDocumentCommand{\x}{m e{^} m}{…}` + `\x{first}^{sup}{second}`。
- 实测：`e` 项不占位 → `m2` 读到单 token `^` 就停，MACRO 占位符只盖 `\x{first}^`，`{sup}{second}` 以花括号组形式落 chunk；同时 `protect_args[k]` 的位序（按 len(spec) 计）与 `args`（缺 e/b 项）错位——`e` 夹在中间时保护位会指错参数。
- 预期 vs 实际：`e` 修饰参应按 `^{…}`/`_{…}` 消费并入 args（维持位序）；实际既不消费也不占位。
- 严重度：**低-中**（xparse `e` 签名真实存在但不多见；错位后果是参数文本带花括号进 chunk）。

### F11. `\url|delim|` 定界形未识别 → URL 文本进 chunk

- 位置：dispatch 8 `PROTECT_NAMES`（scanner.py:699-702）→ `_protect_call`（1462-1489）只认 `*`/`[..]`/`{..}`，不认定界符形。
- 触发输入：`See \url|http://example.com| for …`。
- 实测：`[[URL_1]]` 只盖 `\url` 三个字符，`|http://example.com|` 原样进 chunk 被翻译。
- 预期 vs 实际：url 包允许 `\url<delim>…<delim>`（同 `\verb` 规则，EOL 上限）；实际 URL 全文进可译文本。
- 严重度：**低**（corpus 1/1919 篇命中）。

### F12. 未闭合 math/protected env → 每个 `_find_env_end` 扫到 EOF → O(N·n) 性能悬崖

- 位置：`scanner.py:904`（MATH_ENVS）、916（PROTECTED_ENVS）、940（in_arg 未知 env）调 `_find_env_end`（571-630），未命中时整段扫到文件尾。
- 触发输入：52KB 文件含 800 个未闭合 `\begin{equation}`（重复 `\begin{equation} x+y\n\n`）。
- 实测：719ms，超 docs/07 §11 的 max≤500ms 门；200/800 次实测 47ms/719ms，随 N 平方增长。
- 预期 vs 实际：无界扫描；可加「同 env 未闭合位置缓存/限距」或直接接受留档。
- 严重度：**性能**（真实语料 unclosed_env 已见 28 处/200 文件抽样——单篇密集未闭合时会撞破 30s/文件解析门）。

---

## 次要观察（不进 Top12，留档）

- `\\]` 会提前关闭 `\[..\]`：`_find_math_close`（scanner.py:861）`startswith(closer,pos)` 不跳 `\\X` 转义对，`\\]` 的第二个字符被当 `\]`。corpus 0/1919。
- 未闭合 `\[` 可吞掉 `\end{document}`（`_find_math_close` 找 `\]` 不截 document 尾），其后文本进 chunks——罕见病理输入。
- preamble 内 `\input` 不进 `res.inputs`（api.py:51-54 只扫正文区间）；`parse_file` 路径由 `flatten_inputs` 兜底，`parse_tex` 直调时 preamble input 漏记。
- BOUNDARY 命令的参数落正文：`\setlength{\parindent}{0pt}` → chunk 含 `{\parindent}{0pt}` 裸命令（不在官方六组泄漏正则内，但确是可译文本里的 `\命令`）。`\item` 的 `force_chunk` 也会被中间插入的 protected env `_flush_run` 提前消费，作用到错误的 run。
- `_split_core`/`_handle_chunk_arg` 切出的多个 chunk 共用同一 `gspan`（scanner.py:351-355、1065-1068）——元数据不精确，无功能影响。
- `\cite{a}{b}` 形会被 `_protect_call` 的 3 参循环整体吞——`{b}` 组文本被藏；低频。
- `_ph` 的 `letters_cut` 检查用子扫描切片的 `self._tex`（scanner.py:182-189），切片边界处的切断检测不到——仅观测信号缺角。
- `\endcsname` 的 `tex.find`（scanner.py:1296）可匹配到很远处的 `\endcsname`，`\ifcsname` 界标可能吞大段文本为 LITERAL——召回损失边缘情形。

## 排查过且**未发现缺陷**的范畴（显式声明）

- **masked/raw 视图错位**：scanner 完全不碰 `mask_comments`/`mask_tex`，全部偏移都在原始 tex 上；pieces 平铺不变式在 400 篇抽样上 `validate_result` 零 `pieces_gap`。
- **多字节 UTF-8 切断**：全程 Python str 下标，无字节级切割点。
- **模块级可变状态/跨文件残留**：唯一模块态 `_CHUNK_SPEC_CACHE` 是纯函数 memo；两次 `parse_tex` 结果逐项相等（已验证）。
- **identity/tiling**：400 篇抽样 identity 100%、无 orphan/dead ph；`_run` 字节覆盖连续性、`_emit_text` 的 lead/trail 空白-字节对齐（ph token 永不在边缘产出空白）均推理+抽查通过。
- **math_debt**：LIFO pop 合并 run 尾为 MATH ph，600 层嵌套 identity 仍逐字节；`_run` 无跨段残留（`_flush_run` 无条件 `math_debt.clear()`）。
- **ph 碰撞/dead-slot**：`[[CHUNK_n]]` 字面撞号 → 死位 chunk + 自指展开防护，已验证机制正确。
- **`\end{document}`/`\endinput` 截停**：仅顶层截停，in_arg/MINED_ONLY 子扫不受影响。
- **正则灾难性回溯**：无嵌套量词模式；最大真实文件 2MB→36ms、1MB→160ms，正常。
