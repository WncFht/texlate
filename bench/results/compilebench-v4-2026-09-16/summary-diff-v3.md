# compilebench-v4 vs v3 + fixloop 臂——compile 层净收益归因（2026-09-16）

> 同一样本复跑：`sample.json` 复用 `compilebench-v3-2026-09-15`（180 篇
> corpus_v3 分层抽样）。v4 臂跑在 HEAD `c7a7679`（compile 三层+校正在内）；
> fixloop 臂 `--cases-from` v4 cases.jsonl × `--corpus corpus_v3`，
> 344 格 1133s。本文是人工归因层；`summary.md` 由脚本生成。

## 1. baseline 臂（v4 vs v3，逐格 join）

| 指标 | v3 | v4 |
|---|---|---|
| tectonic clean/pdf~/FAIL | 53/56/66 (n=175) | 53/55/64 (n=172) |
| xelatex clean/pdf~/FAIL | 43/16/116 | 41/16/115 |
| 联合 pdf / clean | 129/71 (71.7%/39.4%) | 127/69 (70.6%/38.3%) |
| 全死 | 51 | 53 |

共同格 344 中**仅 1 格 verdict 迁移**：1404.5668 xel clean→pdf~——
9c3d4e2 上线 killed_signal 归因（SIGPIPE 一直被杀、v3 看不见），
判定更正非回归。另 6 格消失 = 3 篇新 no_main_tex（§4 bug 所致，修复后
预期回 2 篇 pdf）。stdin=DEVNULL 后 xel FAIL 均时 0.2→0.1s、
tec 3.9→0.6s，verdict 面无影响。

**inert 声明**：tlmgr/repository/salvage/--web-bundle 在本 harness 不触发
（install_file 只被 fixloop 调；tectonic 无 bundle 参数时不下 flag）——
v3 tectonic 臂未被 --bundle bug 污染，两臂可比。

## 2. fixloop 臂实测（真净收益）

- 联合 pdf 127/172→**154/172（89.5%）**；clean 层 149/172（86.6%）。
  折算全样本 154/180 = **85.6%**。
- **xel missing_file FAIL 109 格→84 出 pdf**（77 格 clean 层）；
  89 格 tlmgr 真装（top：revtex4.cls×31、algorithm.sty×20、
  revtex4-1.cls×15）。未救回 25 = 真阴性 unfixable:missing_file×15
  （espcrc2/svjour/mn2e/aastex63/binhex 等 TL 未收）+ latex209_reject×7
  + 装后新错×3。与 fixloop-v3-missing-file 子集（111→90 装/85 pdf）
  数字级一致。
- tec missing_file 12 格 FAIL→0 救回（ctan_fetch 对 publisher class
  无解，符合预期）；eps_image 45→**37 出 pdf**（eps_to_pdf）；
  missing_pfb 3/3。
- tectonic 344 格 0 例 bundle 错误——--web-bundle 修复在真实 URL pin
  场景验证通过。
- salvage：best_effort_pdf×13 全在 xelatex（cond-mat/0111097、
  0707.2833、1109.5931、1109.5963、1206.5628、1404.5668、1803.02994、
  2105.03798、2203.13055、2308.04174、2308.04212、2403.05475、
  2410.17992）。
- documentstyle suspect 13 篇：3 篇假阳性（cond-mat/9703223、
  hep-ph/9703402、hep-th/9703099）**双引擎全 clean**（旧硬拒会冤杀，
  降级决策实证成立）；7 篇真 2.09 gate 拒 ×14 格（设计终态）；
  2211.04503 tec 意外 acceptable_pdf；0806.0904/q-alg/9703046 其他死法。

## 3. fixloop 内回归（base 有 pdf→fix 无 pdf，7 格）

全部 tectonic gate 类正确拒：5×latex209_reject + 2×pstricks_route
（0905.4371、1803.08846）。**无引擎/规则真回归**。另 7 格档内降
clean→acceptable/best_effort，唯一值得抽查 2403.05475 xel
clean→best_effort_pdf（本 clean 被规则点火降级）。

## 4. 实锤 bug：mask_tex env 终点 overshoot（已修）

`src/texlate/textutil.py` `mask_tex`：
`stop = _env_stop(text, env[1], i + env.end())`——`env.end()` 已是绝对
offset，加 `i` 双计 → `\end{env}` 搜索起点推后 ~i 字节；真实 `\end`
落窗内即被跳过，遮盖延至下一 `\end` 或 EOF。

实证：2003.03510 `\begin{comment}`@1141 应闭 1576 实遮 10900
（`\begin{document}`@1895 被吞 → no_main_tex）；1608.06693
`\begin{filecontents*}`@815→`\end`@1136 被跳→全文 100% 遮盖；
quant-ph/0111094 `\begin{filecontents}`@3081→`\end`@5841 被 6182
起点跳过。

暴露史：同式 overshoot 旧 mask.py 已有（`text[i + env.end():]`），但旧
`i += command.end()` 蛙跳 bug 使多数 `\begin` 根本没被测 + alternation
未 escape 使 `filecontents*` 从不匹配——第一层 bug 掩盖第二层，
4287794 修蛙跳时漏修同行。

**修复（已落地）**：`_env_stop(text, env[1], env.end())` 一行 +
回归测试 `test_visible_tex_env_end_no_offset_overshoot`（深位
`\begin{comment}`/`\begin{filecontents*}` 短体断言
`\begin{document}` 可见）。pytest 1090 全绿；parsebench 涉事 3 篇
抽查 strict 全过。影响面：flatten/api 的 `\begin{document}` 壳标记、
inject 的 documentclass/CJK/figure 检测、engine route 分类——全部为
正向修正。

## 5. 遗留

- v4 无格 8 篇 = 5 历史 no_main_tex + 3 新增（即 §4 bug）——bug 修后
  联合预计 +2 pdf（2003.03510、quant-ph/0111094 v3 本出 pdf）。
- 三级漏斗：v3 71.7% → v4 70.6%（校正面）→ **v4+fixloop 89.5%**。
