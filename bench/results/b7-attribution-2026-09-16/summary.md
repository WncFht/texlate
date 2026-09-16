# B7 低保留对归因——壳完好于 zh tex，全灭于编译段截断

日期：2026-09-16。数据：`attribution.jsonl`（逐对结构化记录）。被测对子来自 `v3-100-2026-09-15`（Mac worktree）产物；n100(archbox) 同 first_error 复现 → 确定性 tex 缺陷，非抖动。

## 总结论

壳（章节/label/bibitem/cite key/`\end{document}`）在 splice 后 zh main.tex 里逐项齐平 en 侧——**丢失统一发生在编译段**：zh tex 内错误点触发 xelatex 错误洪流，nonstopmode 仍受 ~100-error 上限截断 → partial PDF → 截断点后锚点全灭。`cite.*` 必丢因为 thebibliography 永远在文末。

## 逐对归因

| pair | ret | en→zh 页 | 首个丢壳环节 | 机制 |
| --- | --- | --- | --- | --- |
| 1706.07924 | 0.026 | 35→1 | compile | zh tex 完整（41sec/112label/27bib)。Mac 上 `Missing \endcsname`@396→百错→1 页；archbox 更早在 preamble 死（缺 epsf.sty+stmaryrd.sty，en 基线同病=环境非管线）；pipe-fix 装包后 37 页 clean |
| 2203.13039 | 0.377 | 9→4 | compile | zh tex 完整（9sec/25label/18bib)。`Missing number`@433→百错截断；postcutover 新译文已 clean→10 页，复测 ret=0.962 ok |
| 2403.15096 | 0.186 | 73→11 | splice/xlat 残留→compile 放大 | 翻译 581/581 ok 但 leftover_ph=572（模型回显幻觉 `[[MATH_1200]]`/`[[SL]]`，当时 ladder 漏拦 → dangling 留字面）；`_` 触发 `Missing $`@287→274 错→11 页残骸。postcutover 已 fallback 干净→82 页，复测 ret=1.0 ok |

## 修复面

1. xlat/splice（2403.15096 类，主修面）：`src/texlate/xlat/retry.py` 阶梯终点 + `src/texlate/latex/reconstruct.py`——带未识别 ph 的译文必须 fallback 原文不得写盘；dangling 目前只 log.warning，建议 `leftover_ph>0` 提为 verdict reason 固化（postcutover 行为已正确）。
2. 译文 tex 语法质量（2203.13039、1706.07924 上层）：Missing number/\endcsname 级错误硬顶是 TeX 百错上限，修法在上游 L0/L2 校验或 fixloop 规则面（F1/F2 方向）；segmenter/splice 无责。
3. 编译环境（1706.07924 底层）：archbox texlive 缺老包，static_precheck 已覆盖——建议 B7 的 B 侧改用 pipe-fix 产物进对子。
4. B7 口径：low-retention 应联判 b 侧编译 verdict——partial/no_pdf 时是编译截断而非「壳没译」；跑 B7 前应先冻结对子快照（本次 10:00 量到的是活跃复跑覆写中的混合快照）。

关联：2403.15096 即 n100 报告「splice 残留 1524 集中 7 篇」榜首，与 splice-residue-probe 同案——残留不是孤立噪声，是 B7 红灯主因之一。
