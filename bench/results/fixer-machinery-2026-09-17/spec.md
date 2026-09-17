# fixer-machinery spec — segmenter.py 机制波（2026-09-17）

Owner file: `src/texlate/latex/segmenter.py`（**等 fixer-keyarg 交付后开工**——
同文件互斥）。测试写 `tests/test_machinery_audit.py`（新文件）。
交付 = 实现 + 测试全绿 + report.md；**不 commit**（leader 统一提交，
parse 侧无 41 signal）。

## M1 — `_emit_argspec_chunks` in_arg 臂字面字节泄漏（2310.16788 真机理）

现场（segmenter.py ~4934-4954）：`if self.in_arg:` 分支把 ops 逐段拼
`texts`——`lit` op 直接 `self.vt.slice(v.start, v.end)` 取**字面字节**
进 run surface，`arg` op 走 `_subscan_render`。结果：argspec 命令在
另一命令文本参内出现时，其非文本参（`[origin=c]`/`{90}`）的字面字节
落进 chunk surface 被译。实证：`\multirow{5}{*}{\rotatebox[origin=c]{90}{2D}}`
→ `[这是译文]`。

修法（argtab 规格）：in_arg 臂 `lit` op 不拼 texts，改
`self._rappend_ph(self._ph(PhType.CMD, self.vt.slice(v.start, v.end)), v)`
——字面段成 `[[CMD]]` 占位（与非 in_arg 臂 `not text_k` 路径同款形）；
`arg` op 的 rendered 串仍入 run。注意 run/ph 交替时先 flush 已累计
文本段再 append ph（参照 `_flush_run`/`_emit` 序），piece 平铺无缝。

回归：`test_rotatebox_inside_multirow_arg`（test_argtab_audit.py:251）
现应已绿（TRANSPARENT_HEAD 侧）——本项补一条**未经** TRANSPARENT_HEAD
覆盖的 chunk-arg 命令嵌套形（如 `\multirow{2}{*}{\parbox{3cm}{x}}` 或
参数表内 chunk-arg env），断言 in_arg 字面段不进 chunk。

## M2 — bare-cs 参种别缺（`\setlength\parskip{4pt}` → `{4pt}` 漏）

现场：`argspec.json` 无表达「参 = 裸 cs（不带花括号）」的 kind；
`\setlength{\parskip}{4pt}` 花括号形正常，`\setlength\parskip{4pt}`
的 `\parskip` 成未知 cs 探针、`{4pt}` 落 chunk。

修法：新 ArgSpec kind（建议 `n` = bare-cs-name arg，消费一个 cs token
作不可译参名）+ `_tail_scan_end`/`_grp_spec_args_end`/`_args_tok`
三消费路径各加 `n` 臂（cs token 直收、不吃 ws 后组）；`_pend_slot_of`
补 `n → "n"`、`s == "n"` 槽 = `x.kind == "cs"` 则收（强制槽——失配
终止）。argspec.json 登记：setlength/addtolength/setcounter/
addtocounter/settowidth 等首参 `n`（先核每命令真签名再写）。
测试：`\setlength\parskip{4pt}` → `{4pt}` 不漏、`\parskip` 不进 chunk。

## M3 — `\\[dim]` 尾参（换行 dim 可选参）

`\\` 后 `[3pt]` 是竖距可选参非文本。`_pend_spec_of` 已有 `"\\"→["s","b"]`
跨界槽；主流侧 `_tail_scan_end` 是否已收 `\\[dim]` 待核实——若
BOUNDARY_TAIL/`\\` 处理臂未盖 `[dim]` 形，补 `b` 档消费
（`_GRP_BSBS_CONTENT_RX` fullmatch 判 dim 内容）。测试：`a\\[4pt]b`
`[4pt]` 不进 chunk；`a\\[text]b` 非 dim 形保守不吸（留主流）。

## M4 — `\parindent=` assign-tail 复核

`\parindent=4pt`/`\parindent 4pt`（无等号）赋形尾参是否已随命令进
LITERAL——`_tail_scan_end` assign 臂（:4763 `kind or "assign"`）对
`=`-less 形覆盖核对。测试双形各一条。

## M5 — `_grp_spec_args_end` 组内 `m` 不认 `[` 组（argtab 残留）

`_args_tok`（segmenter.py:3940）`m`/`v` 吃 `lbrace` 或 `other "["`，
组内对价 `_grp_spec_args_end` 的 `m` 臂只认 `{`——`[note]` 形 env 参在
brace 组内漏 `]{env}{cs}`。修法：组内 `m` 臂对齐 `_args_tok` 加 `[`
定界组分支（`_grp_bal(brace=False)`）。测试：`\foo{\begin{restatable}[N]{t}{c}…}`
嵌套形 `]{t}{c}` 不进 chunk。

## M6 — BOUNDARY_TAIL 组内/参内 spec-blind（文档化裁决）

组内 `_grp_boundary_args_end` 与 in_arg 路径只数 mand 个数、不按
spec 位序消费交错签名——裁定**只记档不改码**（多参结构命令全走
TRANSPARENT_HEAD_SPEC，BOUNDARY_TAIL 仅尾参单参族）。report.md
记一句即可，无代码无测试。

## 测试纪律

- 每 M 项 ≥1 测试，三件套：`reconstruct(res) == tex` +
  `validate_result(res) == []` + pieces 无缝平铺（参 test_argtab_audit.py
  `check_invariants`）；
- `uv run pytest tests/ -k "argtab or machinery or segmenter or macro_table"` 全绿；
- `uv run ruff check src/texlate/latex/segmenter.py` 全绿（complexity noqa
  按现有惯例带注释理由）。

## 交付报告写到 bench/results/fixer-machinery-2026-09-17/report.md

列：每项 状态/改动位置/测试名/deviation。SendMessage texlate-1d 交付摘要即关。
