# latex/ 对抗性二审结题报告 — 16 处修复 + 31 探针

> **结论**：对照五条铁律逐行对抗审查 + 探针验证 + fuzz/property 测试，确认并修复 16 处真 bug——P0 两处（`\if` 宏毒化、界标丢条件串）可致整文件 chunks 全丢或条件码泄入可译文本，P1 六处正确性硬伤，P2 八处以「静默降级零信号」为主；全部局部规则修正，pieces 平铺不变式与 splice-safe 降级两条铁律在所有修复点上保持。
> **状态**：时点证据（2026-09-15 口径；审计对象为当时的 v1 单文件 scanner 代码，16 处修复全部入库，其后 v2 gullet+segmenter 重写消化了等价语义——探针族仍在回归网中，`tests/test_latex_audit.py` 已随 v2 API 更新，另有 `test_gullet_audit.py`/`test_segmenter_audit.py` 等后续审计族）
> **日期**：2026-09-15

审计对象为 `latex/` 七文件（约 3200 行，miniscanner spike 扶正重写产物）；方法是对照管线五条铁律（现行规范见 `spec/latex-pipeline.md`）逐行对抗审查，专找 corpus 门（identity 100% / leak 0.04%）照不到的死角。验收门：corpus_v3 1955/1955 parse + strict identity 100% + leak 58/135575（0.04%）与基线持平零退化；pytest 775 passed / 3 skipped；ruff select=ALL 全净。

## 1. 确认问题清单（每条：根因 / 修法 / 验证探针）

### P0 — 灾难性

1. **`_process_if`：`if*` 宏毒化嵌套深度。** if-case 字节收集把 `\ifXxx` 形态的已定义宏（非 LITERAL，如 `\newcommand{\ifAnonymous}`）计入 `\if/\fi` 嵌套深度 → `\else`/`\fi` 配对毒化 → 该命令之后整文件尾部降级 LITERAL、chunks 全丢。corpus 0 命中，纯对抗构造。修：仅字面 `\if/\else/\fi/\or` 计深度。证：`test_audit_if_macro_inside_case_no_poison`。
2. **`_handle_cond` + `_read_number`：界标丢条件串。** 不可求值 `\if` 转界标 literal 时只 emit `\if` 命令名，`\ifnum\count0<5` 的条件串留进正文 → `\count`、`<5` 泄入可译 chunk；配套 `_read_number` 不消费 `\cs` 后寄存器下标（`\count0`）与 `'`/`{group}` 数字形态。修：界标覆盖 `\if`+条件整段，`_read_number` 补三形态。证：`test_audit_unevaluable_if_landmark_covers_condition`、`test_audit_read_number_register_index`。

### P1 — 正确性

3. **math-debt 误报。** VERB/COMMENT/URL/HREF 占位符体内的 `$` 是逐字死字符却计入奇偶判定压 math_debt → `\verb|$HOME|` 之后第一个真 `$` 被「债务修复」吞错配对。修：四类豁免。corpus debt_repair 13→12。
4. **`_WS` 缺 `\r`。** CRLF 文件（corpus_v3 占 6.7%）中 `\newcommand{\x}\r\n{body}` 的 ws_skip 停在 `\r` → 宏不登记、`{body}` 泄为正文。修：补 `\r`，参数读取全线换 `ws_skip_arg`。
5. **flatten verb 吞 `\input`。** flatten 层 `\verb` 定界符搜索无 EOL 上限、不识 `\lstinline[opt]` 前缀 → 未闭合 verb 跨行吞掉真实 `\input`。修：复用共享 `skip_verb_at`（EOL 上限 + `[opt]` + `{...}` 三形态）。
6. **`\endinput` 不截停（corpus 24 文件）。** TeX 语义是「当前文件到此为止」，实现照常扫 marker 后内容。修：flatten 丢弃余下并 break；scanner 顶层 emit 后截停（in_arg 内降级 CMD）。warning diff 见 §3。
7. **占位符撞号。** 源文自带 `[[CMD_1]]` 形字面与签发占位符同号 → reconstruct 把原文当占位符展开，identity 注入破坏（spec 声称有 assert 实际没有）。修：入口 `ph_reserved` 预占全量 `[[X_n]]` 形字面 + `ph_collision` warning；CHUNK 撞号补自指死位。
8. **reconstruct 自指译文 RecursionError。** DAG 递归展开无环防护，LLM 幻觉出的自指 `[[CHUNK_k]]` 译文无限递归。修：`active` 集合检出即留 token 字面（ph_map 构造上无环，只防译文侧）。

### P2 — 信号与边界

9. **`_env_pop` 双静默。** 栈空 `\end{X}` 与隐式弹栈零信号 → 补 `stray_end`（栈空也发）与 `env_mismatch`（`\end{A}` 隐式关闭栈内 B/C 时发）。
10. **三处 gen-cap 静默。** `_env_with_mined`/`_handle_chunk_arg`/`_handle_macro` 超 MAX_GEN 降级零信号 → 补 `gen_overflow`。
11. **`_find_math_close`。** `\[`/`\(` 闭符搜索命中注释内 `\]`/`\)` 提前闭合。修：逐字符跳注释 + 遇段界弃配。
12. **`_find_env_end` 不识逐字体。** `\verb|\end{equation}|` 内假闭合早截 env 体。修：复用 `skip_verb_at` + verbatim-env 跳体。
13. **`ws_skip_arg` 参数吸收跨 `\n\n`。** TeX 不定界参数遇 `\par` 停；实现跨段吞 `{arg}`/`[opt]`。修：新原语（`\n[ \t\r]*\n` 即段界，停在首个 `\n`）替换各参数读取点。
14. **`parse_argspec` `t*` 双字符定界。** xparse `t` 取单字符定界符，原实现读两字符吞掉下一 spec 项（`t*m` → `t{*m}`）。修：单字符。
15. **`_on_dollar` 段界判据不一致。** `$$`/`$` 配对只认紧邻 `\n\n`，主循环认 `\n[ \t\r]*\n` → 游离 `$` 跨软空行吞文本成假 MATH。修：统一 `_PAR_BREAK_RX`（行为权衡见 §5）。
16. **`_scan_def_params` `\def` 参数文本 `\n` 硬停。** TeX 里换行=space token，`\def\a#1\n#2{B}` 合法；实现 `\n` 硬停 → ok=True 但 body 位对不上 → 静默不登记且零 warning。修：单 `\n` 作 ws、`\n\n` 停；ok 但无 `{` body 时补 `def_parse_fail`。

次修：TRANSPARENT 宏缺省可选参的零宽占位不再签发空 `[[KEY]]`。

## 2. 测试映射与验证

31 条探针按 §1 编号一一对应入 `tests/test_latex_audit.py`，另含四条不变式：fuzz token 汤 + 随机字节 800 例零异常 + pieces 无缝平铺 `[0,n)` + reconstruct identity；corpus 抽样平铺（skipif 守卫）；protected_tex/chunks/ph_map 内所有 `[[X_n]]` 可解析不悬空。

## 3. parsebench warning 分布变化逐条解释

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

**stray_end 4→18 是新检测灵敏度、非回归。** 增量集中在 `0905.4503/ms.tex`（+10）、`1811.03607`（三文件各 +1）、`0707.2108/pmeyerxi.TEX`（+1），全部同一形态——`\ifemulate \begin{deluxetable*}…\else \end{deluxetable}\fi`：env 的 begin/end 分居 `\if` 两分支，双分支 literal 扫描下 `\else` 分支的 `\end` 在栈上确无匹配。此前零信号静默通过，现在如实名化；扫描行为本身不变。

**env_mismatch 唯一一例**在 `2403.05444/elsdoc-cas.tex`：`\end{vquote}` 闭合时栈内还压有三个 `enumerate`（文档把 vquote 当行内引用壳跨列表使用，env 非嵌套）→ 隐式弹栈发 `env_mismatch`，连带后续三个 `\end{enumerate}` 命中 stray_end。栈状态属实。

**def_parse_fail −108 / missing_input −27 同源**：`pstricks.tex` 的 `\endinput` 在 offset 925，其后还有 828 个 `\def` 与 2 个 `\input`；`aps.rtx.tex` marker 后 131 个 `\def`；`gtoutput.tex` marker 后 268 个 `\def` + 16 个 `\input`。TeX 本身也读不到 marker 之后的内容——截停是正确语义，减少的 warning 都是「本来就不该扫到」。

**unpaired_dollar 净 +1**：`2410.17903` +2 是 #15 的行为变化——`$$…\n\t\t\n…$$` 数组夹只含 tab 的空白行（TeX 同样视为 `\par`），旧代码跨段配对救回、新判据弃配 + 告警并级联出第二个 unpaired；`1306.2365` −1 是 #3 豁免消掉的误报。chunk 总数 −442 可解释：endinput 截停去掉本就不该译的 marker 后文本 + 宏登记改善后参数归位；identity/leak 两硬指标不变。

## 4. 留档未修项与残余风险

- **INLINE_MAX=8000 声明未接线**：CHUNK_MAX 切分已兜住单 chunk 体积，接线反而丢覆盖——保持现状。
- **`parse_file` 的 warnings.pos 混排两套坐标系**（flatten 前文件偏移 vs 展平后串偏移）：诊断信息级问题，修要动 warning 契约。→ v2 落地后坐标系由 vtex 统一承载（pieces/chunk.span/warning.pos 均为 int 偏移；`ScanWarning.pos` 仍是 int 装不下 fid——gullet 侧 warning 记 fid 本地偏移并以 `f{fid}` detail 前缀区分文件，segmenter 侧为 vtex 偏移；见 `segmenter-integration.md` §1）。
- **小项（0 corpus 命中或 cosmetic）**：`match_bracket` 的 `\\X` 跳二对 `\]` 过匹配；`e`/`b` argspec 参数位错位；`_INPUT_SCAN_CMDS` 缺 `CatchFileBetweenTags`（仅 inputs 记账口径）；`cjk_glue_fix` 会动 verbatim 体内文本；`test_validate_result` 中 pieces[0] 重复检查死代码。
- **判断点**：#15 段界判据若需恢复旧 rescue 语义，回退 `_on_dollar`/`_find_math_close` 内 `has_par_break` 一处即可；建议保留——与主循环判据一致、有 warning、且符合 TeX 语义。

## 5. 结论

corpus 门（identity 100% / leak 0.04%）此前掩盖了一批低频但真实的正确性缺陷——本轮最重的两处（if\* 宏毒化、界标丢条件串）都是 corpus 0 命中的对抗形态，靠逐行对照铁律 + 探针构造暴露。16 处修复全部局部化、信号化（新 warning kind：`gen_overflow`/`ph_collision`/`env_mismatch`），31 条探针把每个修复点钉死在回归网上。v2 重写后这批语义由 gullet/segmenter 承载，审计方法论（铁律对照 + 对抗构造 + warning 分布逐条归因）继续沿用于后续 `test_gullet_audit`/`test_segmenter_audit`/`test_machinery_audit` 等族。
