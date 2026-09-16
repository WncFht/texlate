# latex-audit — latex/ 全目录只读审计（复活版收口）

> 2026-09-17 收口。只读任务，零产品文件改动（latex/ 归 texlate-1d lane，发现全部外路由）。13 文件全读 + 14 个实证探针 `tmp/latex-audit/`（gitignored），行号对 HEAD。本报告与 latex-audit-seg / latex-audit-core 两分裂审计并行产出——重叠已去重（seg S1 ≡ 本报告 F2；seg S2-S5、core C1-C5 为互补发现；core 的 unregistered-if* 注记与本报告 F5 IfSetter 同族不同因）。已文档化弱点（docs/07 §8 math_depth/\ifmmode/input 序）未重报。v2=默认产品路径，v1=TEXLATE_NO_EXPAND 回退臂。

## 确认缺陷 → 全部路由 texlate-1d

### F1 [高，v2 回归] `_new_chunk` 无死位保护 → 源内字面 `[[CHUNK_n]]` 撞号 — segmenter.py:685-701

`cid = len(self.state.chunks)` 直接追加不查 `ph_reserved`；v1 scanner.py:258-286 有死位循环。源里手写 `[[CHUNK_0]]` 字面与 0 号 chunk 撞号，`expand_body` 无差别展开。probe1：正文含字面 `[[CHUNK_0]]` → v2 identity BROKEN（字面展开成 chunk0 全文；翻译模式注入 chunk0 译文）。v1 存活。修法：v1 死位循环移植 v2 `_new_chunk`（遇 reserved id 插自字面占位 Chunk 再 ++）。

### F2 [高] `ph_reserved` 只采 fid-0 — segmenter.py:4477（≡ seg S1）

`\input` 子文件内 `[[X_n]]` 字面签发器不避让 → 同名占位符签发 → reconstruct 把字面当 ph 展开；verbatim 内字面同样命中；**无 ph_collision 警告**。修法：扫描结束对 `file_texts.values()` 全量 `PH_RX.findall` 并入 reserved，或 `push_source` 时点增量采。

### F3 [中] `flatten_inputs` 对 `\\` 第二根反斜杠重新起词法 — flatten.py:191-192

`\\input{b}`（TeX：换行+字面 input）被当 `\input{b}` 内联；`x\\endinput\nY` 把 Y 丢掉。probe3 实证。消费面：v1 回退臂/parsebench/test_bench_regression——v2 默认路径不吃 flatten。修法：`c=='\\'` 且下一字符非字母时两字节当一个控制符号吞（`i += 2`）。

### F4 [低中] `_args_tok` t/d/r/R 分支定界符不查 kind → cs 被当字面定界符 — segmenter.py:3443-3496

`x.text == s.delim[0]`/`y.text == cl` 均无 `kind != "cs"` 闸（'e' 分支 :3510 有排除）。probe4：`\onslide\+{A}` 的 `\+` 被 `t+` 吃掉；`\<`/`\>` cs 对被 `d<>` 当定界符；`\frametitle\<nosuch` 扫到 EOF→abort→全 literal。identity 恒存活但分组偏离 TeX。修法：四分支补 `x.kind != "cs"`。

### F5 [中] `process_if` 把 IfSetter 计入 `\if` 嵌套 — gullet.py:2608-2614

排除 `(MacroDef, Tok)` 但漏 `IfSetter`：`\newif\ififx` 注册的 `\ifxtrue`（名以 "if" 开头）→ 死代码收集 `nesting += 1` → `\fi` 错配 → `if_unterminated` + 文件余量被吞。附带：死支收集走 `next_expanded`，IfSetter 副作用照跑（被跳过分支的 `\Xtrue` 仍改旗标）。修法：排除元组加 `IfSetter`；死支收集用 raw read 或抑制 setter 副作用。（core 审计另报**未注册** if* 宏名同型伤——两因并修。）

### F10 [低，v1] filecontents 闭环境裸 find 无行首锚 — scanner.py:1017-1026

`tex.find(pat, j)` 行中 `\end{filecontents}` 诱饵截断；v2 segmenter.py:2637-2642 已修（`(?m)^[ \t]*\end{…}`）。v1 移植同款锚定正则。

### F9a [低中] `register_macros_in` 不跳 verbatim 环境 — macro_table.py:501-531

`\begin{verbatim}\def\fake{PWNED}\end{verbatim}` → `fake` 注册成功污染宏表（lstlisting 同款；注释里 `\def` 正确跳过）。修法：扫前 VERBATIM 环境清单预遮蔽（textutil.VERBATIM_ENVS 已有）。

### F9b [低] `\protected` 不在 _PRIMS；`\global\let` 链断 — gullet.py:331-399/:1566-1586

`\protected\def\pd{A}` → `\protected` 泄独立 LITERAL piece（`\def` 照常登记）；`{\global\let\gl\relax}` → `\global` 泄 literal、`\let` 当局部执行（组弹表，TeX 应 global）→ 组外 `\gl` 不展开。`_do_prefix` 链目标只 `def/edef/gdef/xdef`。修法：_PRIMS 加 `protected`；链目标扩 `let/catcode/count/…` 或给 `global` scope 传递。

### F11 [低中] 组内 literal 覆盖时 `}` 泄进可翻译 chunk — segmenter 主流水线

`{\let\gl\relax}Body…` → `{`+`\let\gl\relax` literal 覆盖，孤立 `}` token 进 run → 译面孤立 `}`（probe10；`{\def\gd{G}}` 同款）。identity OK；翻译模式 LLM 丢/改 `}` → 下游花括失衡（L0 只管 [[ph]] 不管裸括号）。修法：group-close token 与 env_stack/group 深度对账，孤立 `}` 盖 literal。

## 口径分歧/设计注记（非字节级破坏，请裁决）

- **F6** 定界扫描用 raw `src.read()`：`_find_math_close_tok`(:4075)、`_handle_verb`(:2387)、`_collect_group`(:3291)、`_args_tok`(:3338) 全绕开 `next_expanded` → 跨文件/展开生成的闭符不可见 → 静默 de-ph 成 literal/para。identity 恒存活（`_cover_text` `end<=a` 零宽闸）。有意取舍 or 缺陷待裁；建议至少文档化「闭符必须同文件同层字面可见」。
- **F7** `_doc_begin_of`(:4451) 只看 masked fid-0：`\begin{document}` 只在子文件 → preamble 模式不启动，前文散文成可译 chunk（v1 全 literal）。修法：`_preamble_tok` 流见 `env_begin document` token 现场翻模式。
- **F8** `_resolve`(flatten.py:55-88)/`_resolve_input`(gullet.py:2208) 候选序 `[fname, fname.tex, fname.TEX]` 无扩展名文件优先——e-print 树里 `foo` 垃圾文件压过 `foo.tex`（TeX 对无扩展名 `\input` 追加 `.tex`）。低危，建议无 `.` 时先试 `fname+".tex"`。

## 已核实非缺陷

- `\r` catcode：decode_tex 前级归一，扫描层永不见 `\r`。
- TokenSource read/next_expanded 双轨：有意设计（raw 扫防宏体闭符骗配对）。
- preamble 整体在子文件：gullet 流式供给正常。
- 组内 `\def` 局部作用域正确；`\global\def` 存活——scope 语义对。
- `expand_all` 零调用、`_do_xparse` docstring 漂移——crosscut 已记账。

## 严重度建议

F1/F2 同根（占位符保留集覆盖不全）可合并修；F3 是 v1 回退臂唯一真吞/假插字节者；F5 命中即整文 0 chunk。C1（core 审计报的 `_resolve_input` 任意路径读——SECURITY 面）优先级最高，与本报告 F8 同函数可一并处理。
