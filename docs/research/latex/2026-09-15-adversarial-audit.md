# latex/ 对抗性二审结题报告 — 16 处修复 + 31 探针

> 对象：`src/texlate/latex/` 七文件（~3200 行，miniscanner spike 扶正重写产物）。
> 方法：对照 `docs/07-latex-pipeline.md` 五条铁律逐行对抗审查 + 探针验证 + fuzz/property 测试，专找 corpus 门照不到的死角。
> 入库：a88c5ce（`fix(latex): 对抗性二审修复一批 + 31 条回归探针`）。
> 门：corpus_v3 1955/1955 parse + strict identity 100% + leak 58/135575（0.04%），与基线逐项持平零退化；pytest 775 passed / 3 skipped（全是 TEXLATE_LIVE 网络门）；ruff select=ALL 全净。

## 0. 结论速览

1. 确认并修复 16 处真 bug：P0 两处（`\if` 宏毒化、界标丢条件串）可致整文件 chunks 全丢或条件码泄漏进可译文本；P1 六处为正确性硬伤（math-debt 误报、CRLF、flatten verb 吞 `\input`、`\endinput` 不截停、占位符撞号、reconstruct 自指崩溃）；P2 八处以"静默降级零信号"为主。
2. 全部修复为局部规则修正，无架构改动；pieces 平铺不变式与 splice-safe 降级两条铁律在所有修复点上保持。
3. parsebench 复测 warning 分布变化逐条有解释（§3）：stray_end 4→18 与 env_mismatch 0→1 是**新检测灵敏度**（真阳性，此前静默），不是回归；def_parse_fail 420→312、missing_input 186→159、if_unterminated 2→1 同源归于 `\endinput` 截停生效。
4. 唯一行为权衡点：`$`/`$$` 配对段界判据从"紧邻 `\n\n`"改为与主循环一致的 `\n[ \t\r]*\n`——对跨软空行的非法数学从 rescue 配对改为弃配 + 告警（TeX 语义上数学本就不能跨 `\par`）。spec-correct，但见 §5 留单点回退路径。

## 1. 确认问题清单

每条：位置 / 根因 / 修法 / 验证探针（`tests/test_latex_audit.py`）。

### P0 — 灾难性

1. **`scanner.py:1363 _process_if` — `if*` 宏毒化嵌套深度。** 根因：if-case 字节收集循环把 `\ifXxx` 形态的已定义宏（非 LITERAL，如 `\newcommand{\ifAnonymous}`）计入 `\if/\fi` 嵌套深度 → `\else`/`\fi` 配对毒化 → 该命令之后整文件尾部降级 LITERAL、chunks 全丢。corpus 0 命中，纯对抗构造。修：仅字面 `\if/\else/\fi/\or` 计深度。证：`test_audit_if_macro_inside_case_no_poison`。
2. **`scanner.py:1176 _handle_cond` + `1310 _read_number` — 界标丢条件串。** 根因：不可求值 `\if` 转界标 literal 时只 emit `\if` 命令名，`\ifnum\count0<5` 的条件串留进正文 → `\count`、`<5` 泄入可译 chunk；配套 `_read_number` 不消费 `\cs` 后寄存器下标（`\count0`）与 `'`/`{group}` 数字形态。修：界标覆盖 `\if`+条件整段（`emit(i, cond_end)`），`_read_number` 补三形态。证：`test_audit_unevaluable_if_landmark_covers_condition`、`test_audit_read_number_register_index`。

### P1 — 正确性

3. **`scanner.py:117 _DEBT_EXEMPT` + `:209` — math-debt 误报。** 根因：VERB/COMMENT/URL/HREF 占位符体内的 `$` 是逐字死字符，却被计入奇偶判定压 math_debt → `\verb|$HOME|` 之后第一个真 `$` 被"债务修复"吞错配对。修：四类豁免。证：三条 `*_dollar_no_false_debt` 探针；corpus debt_repair 13→12。
4. **`model.py:193 _WS` 缺 `\r`。** 根因：CRLF 文件（corpus_v3 占 6.7%）中 `\newcommand{\x}\r\n{body}` 的 ws_skip 停在 `\r` → 宏不登记、`{body}` 泄为正文。修：`_WS` 补 `\r`，参数读取全线换 `ws_skip_arg`。证：`test_audit_crlf_ws_skip`。
5. **`flatten.py:147` — verb 吞 `\input`。** 根因：flatten 层 `\verb` 定界符搜索无 EOL 上限、不识 `\lstinline[opt]` 前缀 → 未闭合 verb 跨行吞掉真实 `\input`，或 lstinline 体内 `\input` 被当真展开。修：复用共享 `skip_verb_at`（`model.py:324`，EOL 上限+`[opt]`+`{...}` 三形态）。证：`test_audit_flatten_verb_eol_cap`、`test_audit_flatten_lstinline_opt_prefix`。
6. **`\endinput` 不截停（corpus 24 文件）。** 根因：TeX 语义是"当前文件到此为止"，实现照常扫 marker 后内容。修：`flatten.py:144` 丢弃余下并 break；`scanner.py:790` 顶层 emit 后截停（in_arg 内降级 CMD）。证：`test_audit_flatten_endinput_truncates`、`test_audit_scanner_endinput_cutoff`；warning diff 见 §3。
7. **`api.py:45` — 占位符撞号。** 根因：源文自带 `[[CMD_1]]` 形字面与签发占位符同号 → reconstruct 把原文当占位符展开，identity 注入破坏（spec §6 声称有 assert，实际没有）。修：入口 `ph_reserved` 预占全量 `[[X_n]]` 形字面 + `ph_collision` warning；`scanner.py:250 _new_chunk` 对 CHUNK 撞号补自指死位（经 reconstruct 环防护还原为字面）。证：`test_audit_ph_collision_identity`、`test_audit_chunk_collision_identity`。
8. **`reconstruct.py:43` — 自指译文 RecursionError。** 根因：DAG 递归展开无环防护，LLM 幻觉出的自指 `[[CHUNK_k]]` 译文无限递归。修：`active` 集合检出即留 token 字面（ph_map 构造上无环，只防译文侧）。证：`test_audit_reconstruct_self_ref_no_recursion`。

### P2 — 信号与边界

9. **`scanner.py:982 _env_pop` 双静默。** 栈空 `\end{X}` 与隐式弹栈此前零信号 → 补 `stray_end`（栈空也发）与 `env_mismatch`（`\end{A}` 隐式关闭栈内 B/C 时发）。证：`test_audit_stray_end_empty_stack_warns`；corpus 表现见 §3。
10. **`scanner.py:1017/1045/1157` 三处 gen-cap 静默。** `_env_with_mined`/`_handle_chunk_arg`/`_handle_macro` 超 MAX_GEN 降级零信号 → 补 `gen_overflow`。证：`test_audit_gen_cap_emits_warning`。
11. **`scanner.py:847 _find_math_close`。** `\[`/`\(` 闭符搜索命中注释内 `\]`/`\)` 提前闭合。修：逐字符跳注释 + 遇段界弃配。证：`test_audit_display_math_bracket_skips_comment`。
12. **`scanner.py:571 _find_env_end` 不识逐字体。** `\verb|\end{equation}|` 内假闭合早截 env 体。修：复用 `skip_verb_at` + verbatim-env 跳体。证：`test_audit_find_env_end_skips_verb`。
13. **`model.py:205 ws_skip_arg` — 参数吸收跨 `\n\n`。** TeX 不定界参数遇 `\par` 停；实现跨段吞 `{arg}`/`[opt]`。修：新原语（`\n[ \t\r]*\n` 即段界，停在首个 `\n`）替换 `_args`/`_protect_call`/`env_name_at`/`_eat_env_args`/dispatch 各参数读取点。证：`test_audit_unknown_cmd_arg_not_across_parbreak`、`test_audit_protect_call_opt_not_across_parbreak`。
14. **`macro_table.py parse_argspec` — `t*` 双字符定界。** xparse `t` 取单字符定界符，原实现读两字符吞掉下一 spec 项（`t*m` → `t{*m}`）。修：单字符。证：`test_audit_argspec_t_single_char_delim`。
15. **`scanner.py:435 _on_dollar` 段界判据不一致。** `$$`/`$` 配对只认紧邻 `\n\n`，主循环 §3.1.4 认 `\n[ \t\r]*\n` → 游离 `$` 跨软空行吞文本成假 MATH。修：统一 `_PAR_BREAK_RX`（`model.py:194`）。证：`test_audit_math_dollar_soft_blank_line`、`test_audit_math_ddollar_soft_blank_line`、`test_audit_paren_math_soft_blank`。行为权衡见 §5。
16. **`macro_table.py:385 _scan_def_params` — `\def` 参数文本 `\n` 硬停。** TeX 里换行=space token，`\def\a#1\n#2{B}` 合法；实现 `\n` 硬停 → `ok=True` 但 body 位对不上 → 静默不登记且**零 warning**（正中大忌）。修：单 `\n` 作 ws、`\n\n` 停；ok 但无 `{` body 时补 `def_parse_fail`。证：`test_audit_def_params_span_newline`、`test_audit_def_bodyless_warns`。

次修：`scanner.py` TRANSPARENT 宏缺省可选参的零宽占位不再签发空 `[[KEY]]`（`test_audit_empty_protect_arg_no_ph`）。

## 2. 测试映射与验证

`tests/test_latex_audit.py` 31 条探针按 §1 编号一一对应（上表"证"列），另含四条不变式：

- `test_audit_fuzz_never_raises_tiles_identity` / `test_audit_fuzz_random_bytes`：token 汤 + 随机字节共 800 例——零异常（铁律 1）、pieces 无缝平铺 `[0,n)`（头号不变式）、protected_tex 自洽、reconstruct identity。
- `test_audit_corpus_pieces_tiling_sample`：corpus_v3 60 文件抽样平铺 + 自洽（skipif 守卫，corpus 是 gitignored 数据层）。
- `test_audit_no_dangling_ph_re`：protected_tex/chunks/ph_map 内所有 `[[X_n]]` 可解析不悬空。

复跑证据：`pytest tests/ -x` = 775 passed / 3 skipped；`uv run python bench/py/parsebench.py --corpus bench/corpus_v3` 末轮 = ok 1955/1955、strict identity 1955、leak 58/135575，归档 `bench/results/parsebench-audit-defnl-2026-09-15/`。

## 3. parsebench warning 分布变化逐条解释

基线 `parsebench-corpus_v3-2026-09-15` vs 修复后 `parsebench-audit-defnl-2026-09-15`：

| warning         | 基线 | 修复后 | 归因                                           |
| --------------- | ---- | ------ | ---------------------------------------------- |
| stray_end       | 4    | 18     | #9 新信号，全真阳性（见下）                    |
| env_mismatch    | 0    | 1      | #9 新信号，真阳性                              |
| def_parse_fail  | 420  | 312    | #6 `\endinput` 截停（marker 后 `\def` 不再扫） |
| missing_input   | 186  | 159    | 同上（marker 后 `\input` 不再尝试）            |
| unpaired_dollar | 172  | 173    | #15 判据收紧 +2 / #3 豁免消误报 −1             |
| debt_repair     | 13   | 12     | #3 豁免去掉的误报                              |
| if_unterminated | 2    | 1      | #6 截停（pstricks marker 后 `\if`）            |
| unclosed_env    | 53   | 53     | 不变                                           |

**stray_end 4→18 确认是新检测灵敏度、非回归。** 逐文件核实：增量集中在 `0905.4503/ms.tex`（+10）、`1811.03607`（三文件各 +1）、`0707.2108/pmeyerxi.TEX`（+1），全部是同一形态——`\ifemulate \begin{deluxetable*}…\else \end{deluxetable}\fi`：env 的 begin/end 分居 `\if` 两分支，双分支 literal 扫描下 `\else` 分支的 `\end` 在栈上确无匹配。此前该情形零信号静默通过；现在如实名化。扫描行为本身（平铺、identity、chunk 切分）不变，只是把本来就存在的不配对讲出来。

**env_mismatch 唯一一例**在 `2403.05444/elsdoc-cas.tex`：`\end{vquote}` 闭合时栈内还压有三个 `enumerate`（文档把 vquote 当行内引用壳跨列表使用，env 非嵌套）→ 隐式弹栈发 `env_mismatch`，连带后续三个 `\end{enumerate}` 命中 stray_end。栈状态属实，真阳性。

**def_parse_fail −108 / missing_input −27 同源**：`pstricks.tex` 的 `\endinput` 在 offset 925，其后还有 828 个 `\def` 与 2 个 `\input`；`aps.rtx.tex` marker 后 131 个 `\def`；`gtoutput.tex` marker 后 268 个 `\def` + 16 个 `\input`。TeX 本身也读不到 marker 之后的内容——截停是正确语义，减少的 warning 都是"本来就不该扫到"。`2001-22.tex` 的 −12 是 `\input gtoutput` 内联传染，同一根因。

**unpaired_dollar 净 +1**：`2410.17903` +2 是 #15 的行为变化——`$$…\n\t\t\n…$$` 的数组里夹了只含 tab 的空白行（TeX 同样视为 `\par`，数学本就不能跨段），旧代码跨段配对救回、新判据弃配 + 告警并级联出第二个 unpaired；`1306.2365` −1 是 #3 豁免消掉的误报。

chunk 总数 136017→135575（−442）可解释：endinput 截停去掉本就不该译的 marker 后文本 + 宏登记改善后参数归位；identity/leak 两硬指标不变。

## 4. 留档未修项与残余风险

- **INLINE_MAX=8000 声明未接线**：CHUNK_MAX 切分已兜住单 chunk 体积，接线反而丢覆盖——建议保持现状或单独决策。
- **parse_file 的 warnings.pos 混排两套坐标系**（flatten 前文件偏移 vs 展平后串偏移）：诊断信息级问题，修要动 warning 契约，留 leader 决策。
- **小项（0 corpus 命中或 cosmetic）**：`match_bracket` 的 `\\X` 跳二对 `\]` 过匹配；`e`/`b` argspec 参数位错位；scanner 侧 `_INPUT_SCAN_CMDS` 缺 `CatchFileBetweenTags`（flatten 侧已支持，仅 inputs 记账口径）；`cjk_glue_fix` 会动 verbatim 体内文本；`test_validate_result` 中 pieces[0] 重复检查死代码。
- **判断点**：#15 段界判据若需恢复旧 rescue 语义，回退 `_on_dollar`/`_find_math_close` 内 `has_par_break` 一处即可；建议保留——与主循环判据一致、有 warning、且符合 TeX 语义。

## 5. 结论

latex/ 的 corpus 门（identity 100% / leak 0.04%）此前掩盖了一批低频但真实的正确性缺陷——本轮最重的两处（if* 宏毒化、界标丢条件串）都是 corpus 0 命中的对抗形态，靠逐行对照铁律 + 探针构造暴露。16 处修复全部局部化、信号化（新 warning kind：`gen_overflow`/`ph_collision`/`env_mismatch`），31 条探针把每个修复点钉死在回归网上。残余风险如 §4，均为留档级，不阻塞当前管线。
