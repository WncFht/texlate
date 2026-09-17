# nullfont-scout — nullfont misschar clean-vs-partial 裁决证据（只读）

> 2026-09-17 收口。配额故障中完成——census 经 repo-scout 子代理执行，全部 file:line 直接 Read 核实。

## (a) 决策点清单——misschar → partial 住在两个独立闸（皆产品码非 bench 侧）

- **GATE 1 — engine 红线**：`compile/engine.py:186` `("missing_chars", r"Missing character: There is no")` 在 WARNING_RED_LINES → `engine.py:296` 全文本 `re.search` → `info.warnings_hit` → `judge.py:170` `reasons.extend("warn:missing_chars")` → partial。全臂触发（不依赖 expect_cjk）。
- **GATE 2 — 计数**：`judge.py:91-93` `count_missing_chars` = 裸 `findall("Missing character:")` → `judge.py:181-183` `expect_cjk and missing_chars>0` → `missing_character×N`。另有 `judge.py:121-122` fallback（pdftotext 缺席时 `cjk_unverified+missing_chars`）。
- 实证：1404.0447 zh/mock（stagerun-loop1 records/compile.jsonl 最新 append）reasons=`["warn:missing_chars","missing_character×251"]`，n_errors=0，cjk_chars=4952，pdf 在——纯 nullfont。
- nullfont 在任一闸均无特判。fixloop 侧**已排除**（peer 在飞）：rules.yaml:150-153 missing_char 签名用 tempered lookahead（处理 ~79 列折行续行，不跨下一条 misschar——邻接真字体行仍命中）；builtins.py:1392 `_mc_parse_log` `font=="nullfont"` belt 过滤。tests/test_misschar_audit.py（untracked）已钉。
- 下游 sig 路径：benchlib.verdict_sig（benchlib.py:180-181）从 reason 串导 cat=missing_character → sig `missing_character:xN` → triage.py:274 F4 桶；stagerun.py:1335-1342 `_on_misschar` 选 `partial ∧ missing_chars>0` 格进定向 fixloop。
- L2 侧：l2.py:85 missing_glyph 类捕全部 `Missing character:` 行 → _REDLINE_CLASSES（:137-145）→ warnings.redlines。但 **redlines 无 gating 消费方**——grep 仅 l2 自身/fixture 提取/tests；e2e._l2_localize（:626-641）只消费 verdict.errors/n_errors。注意：tests/fixtures/logs/xelatex-multierror-stack.log 有 2 行 nullfont，manifest 断言 by_class_min.missing_glyph=2 + redline_contains=missing_glyph——L2 重分类需同步改 manifest。

## (b) 格普查——stagerun-loop1-2026-09-16 compile.jsonl（recut 批 561368d，last-record-wins/id+upstream），zh 臂 10102 格，338 misschar-partial 格，日志全在盘 work/{safe_id}/splice/*.log

- **纯 nullfont：37 格**（2402.07927 在 mock+real 双臂均中）。**混合：1 格**——2403.00125（115 nullfont + 恰 1 真字体缺 U+0327 @ cmmi10，邻接 `LaTeX Warning: Command \c invalid in math mode`）。**无 nullfont：300**。
- 37 纯格中 7 格带**独立脏因**（errors>3：0806.3242/2211.00110/1511.06948/0806.3683/2112.00073/2403.15085；first_error=undefined_cs:relax：1306.0036）——裁决下仍非 clean。**~30 格翻 clean**（与 ~32 估值一致，估计器口径不同）。
- 字符普查（纯格 1009 nullfont 命中）：`;`×577（57%），余为 ASCII 标点/数字/坐标（`,`44 `1`27 `.`22 `2`20 `+`12 `=`10 括号/`<>`…），稀疏字母解码为包机制 token。**零 CJK**。38 格全部 pdf_bytes>0（98K–7.3MB）。

## (c) 上下文裁决——良性试排，零正文吞字

11 格 ±12 行上下文：TikZ/pgfplots 测量（`;` 风暴、`every node/.style={fill,circle,inner sep=1pt}`×2、`,anchor=north`×3、pgfplots colorspace/data-file 读、dot2tex TikZ 输入）、epic/picture 坐标对 `(1.5,-2.3);`、babel `.ldf` 探针名（Missing-\begin-document 错误恢复期）、diagram 方向字母 `wuuwuwuw`、自家 `TeXlate-Float-Fit` 测量盒（2402.07927 单 `p`）。最长字母串全解码为包机制 token 非散文。**无段长 nullfont 行，无真字体 pass 缺同字符**。

## (d) 若裁 clean——精确改点

1. `engine.py:186`——missing_chars pattern 换成 rules.yaml:152 的 tempered lookahead（peer 测试已含 wrap case 实战）。修 `warn:missing_chars` 全臂。
2. `judge.py:91-93`——`count_missing_chars` 须排除 nullfont：同 lookahead 正则 findall（全文本、wrap 安全）；**勿**做逐行 `"nullfont" in line`——TeX ~79 列折行可让 `in font nullfont` 落续行。
3. `judge.py:121-122` fallback 自动继承修后计数。
4. `l2.py`——可选/可观测性：加 `missing_glyph_nullfont` 类（匹配 `in font nullfont` 含折行形）置于 missing_glyph **之前**于 _WARNING_RULES；**不进** _REDLINE_CLASSES——by_class/samples 留计数而 redlines 保净。需同步更新 xelatex-multierror-stack manifest 期望（missing_glyph:2→missing_glyph_nullfont:2）。
5. 可观测性**无需新 reason_kind**：judge `notes` 通道已载非门控 `sys_warn:`/`cjk_unverified` 项——纯 nullfont 缺字符存在时发 `missing_character_nullfont×N` 进 notes；`verdict.missing_chars` 保持门控计数。
6. Bench 消费方零代码改动：`_on_misschar` 不再选中翻格（missing_chars=0）；verdict_sig 导 ""（clean）；triage F4 桶对 300 真缺格不受影响。

**SCOPE WARNING**：judge/engine 是产品码——worker.py:3203 zh.pdf 生产 verdict 走同一组闸，裁决同时翻**生产侧** partial→clean，不只 bench 格。

混合格边界：2403.00125 经其 1 个真字体缺（cmmi10 U+0327 真丢字形）保持 missing_chars 门控——lookahead 设计下混合日志两闸仍同触。
