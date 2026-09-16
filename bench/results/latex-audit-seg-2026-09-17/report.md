# latex-audit-seg — segmenter/tables/flatten/reconstruct/prose/api 只读审计

> 2026-09-17 收口。只读任务，零产品文件改动（latex/ 归 texlate-1d lane，发现全部外路由）。探针 `tmp/latex-audit-seg/`（probe1-3.py 可重跑 + notes.txt 台账，gitignored）。

## 确认缺陷（全部实证复现）→ 已路由 texlate-1d

### S1 [v2-only 回归] ph_reserved 只覆盖 fid-0 — segmenter.py:4477

`reserved = PH_RX.findall(g.file_texts[0])`；v1 api.py:50 对 flatten 后全文保留。`\input` 子文件内含 `[[X_n]]` 形字面 → 签发器不避让 → 同名占位符签发 → reconstruct `expand_body` 把字面文本当 ph 展开。复现：sub.tex 含 `literal [[MATH_1]] markers` + main `\input{sub}` → v2 输出 `literal $x+y$ markers`（identity 破，无 warning）；v1 正确保留+告警 ph_collision。修复注意：`g.file_texts` 随 \input 懒增长，扩 findall 到当前 file_texts 仍盖不住「先发签后加载」序——需挂 push_source 时点逐文件扫描（已签发 token 与后加载文件字面碰撞只能告警）或 ScanState 层等价挂钩。

### S2 `\author[opt]` 无 `{arg}` abort 路径字节双计 — segmenter.py:3872/3889/3891

`_handle_protect_block` 吃到 `[opt]` 后 `end=closer.pos[2]`；无 `{arg}` 时 :3889 `src.unread` 回放 opt token，但 :3891 `cover_to(fid,end)` 仍把 `[opt]` 段盖进 `[[AUTHOR_n]]` 体 → 同段字节既在 ph 体又重进 run surface → 译者翻译已保护文本 → 译文双份。复现：`\author[Short Names]Then body prose…` → `[[AUTHOR_1]]`=`\author[Short Names]` 且 chunk0 content 亦含 `[Short Names]`。identity 不破；修法任选：abort 时 `end` 退回 `b`（只护 `\author`）或不回放 opt_toks。

### S3 short_arg `\n\n→\n` 折叠穿透嵌套 ph 体 — reconstruct.py:217-218

`expand()` 先 `expand_body` 递归展开嵌套占位符，再对 `expanded` 整体跑 `_PAR_RUN_RX.sub("\n")` → 命中 `[[ENV_n]]` 等体内段落边界。复现：`\footnote{Before \begin{unknownenv}x\n\ny\end{unknownenv} after…}` → 译文输出 `x\ny`（env 体 \n\n 被毁）。正确语义只压译文顶层接缝；修法：折叠作用于展开前译文模板，或只对字面段折叠、ph 展开结果不压。

### S4 `_handle_chunk_arg` fallback `real[-1]` 选错参数 — segmenter.py:3773-3774

tidx 位空（零宽/越界）时退最后实参，未区分 braced vs optional。复现：`\captionof{figure}\n\end{document}` → chunk(context=captionof, content="figure") → 译文 `\captionof{图注译文}`，float 类型名被翻译、LaTeX 坏。同机理 `\section[Draft Short]` 无 `{arg}` → opt 被当 chunk 翻译。仅畸形输入触发，严重度中低；建议 fallback 仅在 real[-1] 为对应 kind（非 'o'）时使用或直接 bail。

### S5 PROSE_CONTEXTS 缺 "subsect"/"abst" — prose.py:38 vs tables.py:136/146

segmenter 对 `\subsect`/`\abst`（CHUNK_ARG_NAMES 内）发 chunk.context=命令名；is_prose 语境白名单无此两名 → `file_has_prose` 召回缺口（仅以短 \subsect 标题为散文信号的文件被丢）。复现：`is_prose(Chunk("TRIS antennas", context="subsect"))` → False vs "subsection" → True。修法：PROSE_CONTEXTS 补两名。

## 存疑待裁（实证过，次要/装饰性）

- flatten MAX_INPUTS 静默截断：warnings=[]；gullet.py:2158 有 `missing_input depth>8`；flatten 内联到第 9 层文件但不扫其内部 \input，gullet 栈长>8 拒压第 9 层——可观测性不对称，非正确性缺陷。
- `_slice_items` 整项重叠保留：`_split_bounds` lo/hi 是 surface 偏移非项界 → chunk content 可带边界空白（v1 精确字节切）。cosmetic drift。
- has_expand run 跳 strip：chunk content 尾可带 `\n\n`。cosmetic。
- segmenter.py:2439 `\verb` 定界符取 `file_texts[fid][d.pos[1]]`：d.gen>0 时 pos 指向 def 体位置 → 取错字节 → 大概率 find<0 退化字面。优雅降级。
- flatten.py:135-144 verbatim end-tag `find` 无行首约束：verbatim 体内 mid-line `\end{env}` 字面会提前关闭 → 尾部 `\input` 被展开。病理输入。
- api.py:62 preamble 判定不查 documentclass 与 begin{document} 先后序——v2 segmenter.py:4451 同形，两版一致。
- segmenter.py:3904 `\item` in_arg → `_protect_cs(CMD)` 默认 mand=3 吞后续花括号组——in_arg 限定，边际。

## 非缺陷复核结论（实证/逐字节比对）

- identity 重建 7 构造全过（plain/math/env/author{}/unclosed_env/verbatim/`\ifx` 条件段）。
- circular \input 祖先栈断环正确（a↔b 二次 `\input{a}` 留字面）；兄弟重包含正常。
- `\endinput`：子文件尾 v1≡v2 均丢弃且字面保留（P7c 逐字节同）；fid-0 尾两版均保留（parity）；in_arg → CMD 保护。
- 保护环境 mined caption：figure 内 `\caption` 正确挖为 chunk，`[[CHUNK_0]]` 嵌 ENV 体，译文 splice 正确。
- `$x$$y$` 顺序配对成两 MATH（=TeX 语义），「组版缺 pos 邻接」疑点消解。
- `\emph[opt]`：`[opt]` 不绑参留字面，identity 不破。
- `_extract_tag_region` 两份逐字节一致（flatten.py:96-104 ≡ gullet.py:2241-2249）；`_DOC_BEGIN_RX`/`_PREAMBLE_RX` 各副本一致（`.end()` vs `.start()` 有意）。
- `decode_tex` 永不抛（latin-1 兜底）→ flatten `except OSError` 覆盖充分。
- api.py:128 `top_dir=""` → gullet.py:883 `top_dir or root_dir` 回落，无语义差。
