# xlatbench corpus_v3 smoke — 2026-09-15

抽样源切换（bench/corpus → corpus_v3 manifest 切层）后的首轮实跑冒烟。

## 配置

- `run --models swe-2-medium --runs 1 --docs 30 --per-kind 20`（seed=0，manifest 全量 core 层）
- 48 样例：caption 20 / footnote 4 / para 20 + S1–S4 合成压力（= fixtures xlat-traps 遮蔽输出逐字节）
- 中途网关断连一次（17 条 http=-1），`--resume` 补齐（修复后只跳成功记录）

## 结果

| kind | hard_ok |
|---|---|
| caption | 20/20 |
| footnote | 4/4 |
| para | 19/20 |
| stress | 4/4 |
| **total** | **47/48 = 98%** |

唯一 fail：2403.15129#44 —— 模型丢 `~` 脆弱间距命令（src 1→zh 0，`cs_dropped` error），真阳性非口径问题。

- ord_soft（ph_order 违例，软信号）14/48 = 29%——佐证 E22「换序降软」定位
- 延迟 p50 7.9s / p95 19.1s；reasoning p50 98ch
- 对照 contract-2026-09-15 同模型 79/80 = 98.75%（旧 corpus）——口径变化可接受

## rejudge 口径对拍（rejudge 子命令首轮实战）

存量 results.jsonl 按现口径（validate_pair + ph_order 软）重判：

| 目录 | 时代 | n | flips F→T | T→F |
|---|---|---|---|---|
| tmp/exp/gwbench/out_a | E22 | 240 | 53 | 0 |
| tmp/exp/gwbench/out_b_high | E22 | 80 | 17 | 0 |
| tmp/exp/gwbench/out_c | E22 | 14 | 2 | 0 |
| tmp/exp/gwbench/out_b_17 | E22 | 28 | 6 | 0 |
| xlatbench-contract-2026-09-15 | 产品口径 | 240 | 0 | 0 |

结论：E22 时代 `judge.ok` 把 ph_order 当硬判；新口径严格项不变、order 降 warn
（E22 定案落地）。重判后排名不变、绝对值上移：swe-2-medium 61→80/80、
swe-2-high 62→79/80、glm-5-2 55→73/80。
