# e2e-verify-residue — splice 残留修复实证（2026-09-16)

验证对象：e2e-n100(`e2e-real-n100-2026-09-15`）检出 splice 残留的 7 篇，
在含修复的 HEAD 快照（worktree `texlate-wt-verify` @ c88f458，经 `TEXLATE_SRC`
隔离，共享主仓 `_xlat_state` 缓存）下复跑。网关 `http://100.105.212.52:3003`
swe-2-medium。结果集：`bench/results/e2e-verify-residue-2026-09-16/`。

## leftover_ph 前后对照

| 论文 | 前 leftover_ph | 后 leftover_ph | ok/chunks（后） | pipe-xel 前→后 |
| --- | --- | --- | --- | --- |
| 2403.15096 | 572 | **0** | 581/581 | partial→partial |
| 2403.15118 | 236 | **0** | 155/155 | partial→clean |
| 1608.02516 | 212 | **0** | 86/87 | partial→partial |
| 2105.03750 | 205 | **0** | 105/105 | fail→fail |
| 1206.5602 | 204 | **0** | 127/127 | partial→clean |
| 2308.12712 | 53 | **0** | 119/119 | fail→fail |
| physics/9703012 | 42 | **0** | 52/52 | partial→clean |

**gate 判定：PASS**(summary.md:「splice 残留占位符： 0 — gate PASS」)。
chunk 终态 ok 1225/1226、partial 1、fault 0、skipped 0。

## 机制实证

运行日志逐条打出 `source drifted (recorded XB != current YB) → re-translate`
——污染缓存记录被新增的 `prev.source == c.content` 检查拦下并重译；
physics/9703012 全部 52 chunk 漂移重译（positional id 全错位样本），其余论文
部分命中缓存。译文抽查含正常中文与合法 `[[MATH_n]]`/`[[REF_n]]` 占位，
splice 后无残留。

## 失败模式（无新增）

pipe-xel 非 clean 且 base-xel clean（管线引入）= **[]**。两处 fail 均为
上游编译问题且 base 同败：2105.03750 缺 `aastex63.cls`(missing_file),
2308.12712 hyperxmp/hyperref 加载序（hyperxmp.sty:279)。partial 三篇
与 base 一致（missing_character/warn)。相较 n100 基线，3 篇由 partial
升 clean（残留占位符进编译面曾致 warn)。
