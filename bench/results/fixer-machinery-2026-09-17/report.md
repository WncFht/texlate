# fixer-machinery 交付报告 (#221)

**Lane**: segmenter.py + argspec.json + tests（原 spec 批的 tables.py/macro_table.py 扩展车道经裁决未用——见 M2 deviation）。验证：`tests/test_machinery_audit.py` 15 绿（新文件）；`-k "argtab or machinery or segmenter or macro_table"` 166 绿；全量 3758 绿；ruff 触碰文件全净。

## M1 done — `_emit_argspec_chunks` in_arg 臂 lit 段 → `[[CMD]]`（segmenter.py ~L5183）

lit op 改 `_cover_to`+`_rappend_ph(CMD)`，`vmark` 追踪 run/ph 交替界；arg op 仍 `_subscan_render` 内联。**既有测试随规格更新**：`test_chunk_arg_nested_in_arg_inlines` 期望面 `Title \alert{inner words} rest` → `Title [[CMD_1]]inner words[[CMD_2]] rest`（规格明知：不挖洞的代价是 `[origin=c]` 漏译）。测试：test_parbox_inside_multirow_arg_no_lit_leak、test_framebox_opt_inside_caption_arg。

## M2 done — 新参种 `n`（裸 cs 名参：cs 直收 或 {..}/[..] 组；强制，失配终止）

消费臂：`_args_tok` ~L4051、`_grp_spec_args_end` ~L1356、`_pend_slot_of` n→"n"、`_slots_walk_toks`/`_absorb_slots` n 槽、槽注释 L186；`_handle_boundary` 顶层经 `_args_tok` 自吃、in_arg 臂补 spec 消费支（原 `_protect_cs` 不认裸 cs）。

**注册裁决（deviation）**：setlength/addtolength 在 BOUNDARY_NAMES——argspec.json 同名条目被 row14 先截全遮蔽，"argspec.json 登记"系 inert。真注册点 BOUNDARY_TAIL 在 tables.py（车道外）→ 落 segmenter 本地覆盖 `_BOUNDARY_TAIL_N` + `_boundary_spec_of` 单一口替三处 `.get`。**未往 argspec.json 写 `n` 字母**——parse_argspec（车道外）无 n 臂会静默跳字致签名-角色错位。

签名核验：setcounter/addtocounter 首参是计数器**名**非 cs → 留 `[m,m]`；settowidth/settoheight/settodepth 不在 BOUNDARY_NAMES，argspec `key` 条目两形已全保（裸 cs 形经重分派+探针兜住），n 语义需 BOUNDARY_NAMES 扩列 → 留 leader 裁决。

mand 计数点含 `n`（花括号形不回归）：_group_surface 两臂、_handle_argspec_cs verbatim 臂、_pend_spec_of 两臂（改按位映射 n→"n" 槽）。
测试：test_setlength_bare_cs_arg / _braced_form_unchanged / test_addtolength_bare_cs_arg / test_setlength_bare_cs_in_arg / test_setcounter_keeps_m_spec。

## M3 已覆盖 — `\\[4pt]`→`[[CMD]]`（_handle_bsbs/_BSBS_OPT_RX），`\\[text]` 保守不吸。测试 ×2。

## M4 已覆盖 — `\parindent=4pt`/`\parindent 4pt` 双形经 DIMEN_TAIL dimen 尾（`=?` 可选）。测试 ×2。

## M5 done — `_grp_spec_args_end` ~L1340 `m`/`v` 臂认 `[` 组（_grp_bal brace=False，对齐 _args_tok）。restatable `m m m` 的 `[N]` 走 m 臂，旧漏 `]{t}{c}`。测试 test_restatable_note_inside_brace_group。

## M6 记档不改码 — 组内 spec-blind 维持；连带残留：全在 brace 组内的裸 cs 形（`{..\setlength\parskip{4pt}..}`）仍漏（gen=0 源组无 pending）；跨界形 `{..\setlength\parskip}{4pt}` 由 n 槽吸纳。

## 残留 done — `_cite_ref_mand`（~L1884）：cite/ref 名查签名计 m/v/n 位，三调用点（_dispatch/_group_surface/_pend_spec_of）。argspec.json 加 `joref`（`m m m m m`，package "manual" 恒激活）→ mand=5 全收；`crefrange`（cleveref 门控 `s m m`）自动修复；`\cite{a}{b}` mand=1 `{b}` 仍当正文（test_cite_two_groups_unchanged 闸）。

## 移交

- model.py:113 ArgSpec kind 注释枚举未含 'n'（leader 车道一行 doc，未动）。
- tests/test_fuzz_logpipe.py::test_xfail_fffd_nullfont_benign strict-xfail 现 XPASS（engine.py nullfont 豁免已随 misschar/logpipe 波落地，非本 wave 改动）——该文件 untracked 属别家车道，全量 `-x` 被它拦，去标由 leader 处理。
- 若日后 setlength 族迁回 argspec 表：先补 macro_table.py parse_argspec 的 `n` 臂。

触碰文件：src/texlate/latex/segmenter.py、src/texlate/latex/data/argspec.json（joref 一行）、tests/test_machinery_audit.py（新）、tests/test_segmenter_semantics.py（一条期望更新）。

（交付原文由 leader 代落盘——subagent report.md 写盘被协议拦。）
