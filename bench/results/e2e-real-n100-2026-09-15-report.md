# e2e-real n=100 扩样报告（archbox）

- 运行日期 2026-09-16（UTC 仍为 09-15，故结果目录 `e2e-real-n100-2026-09-15/`）
- 快照：`TEXLATE_SRC=~/src/texlate-wt-e2e/src`（HEAD `4e06299` worktree，运行期仓库在并行改动）
- 命令：`--base-url http://100.105.212.52:3003 --n 100 --layers core --concurrency 10 --time-budget 21600`；
  manifest 只有 core 层（1000 篇），booster 不存在 → `--layers core`。
- 前置修补：`uv sync --extra server`（preflight 全量 import 需要 fastapi）。
- 用时 ~11 min（_xlat_state 缓存命中 92 篇旧译；`--time-budget` 远未触顶）。

## 头部数字（对 s40 基线）

| 指标 | s40（36 执行） | n100（91 执行） |
|---|---|---|
| chunk ok | 4354/4365 = 99.7% | **10715/10718 = 99.97%**（partial 3、fault/skipped 0） |
| splice 残留 | 0 | **1524（7 篇集中）** |
| pipe-xel clean | 16/36 = 44% | 28/91 = 30.8%（partial 19、fail 44） |
| base-xel | — | clean 10 / fail 50 / partial 11 /71 |
| 管线引入失败 | 2 篇 | **8 篇**（见下） |
| route reject | — | 9 篇（8× latex209_documentstyle + 1 unknown） |

## 失败构成（pipe-xel first_error 类别）

`missing_file`×41 绝对主导（与 compilebench-v3 一致——tlmgr 装包层是第一杠杆），
syntax×8、latex209×3、undefined_cs×1、other×1；`missing_character` 在 warn 侧高频
（×1513/×11869 等大字数缺失 = Fandol 类缺字形）。

## 管线引入失败（pipe 非 clean 且 base clean）8 篇

`0905.4907` `1206.5602` `1511.02908` `2203.13039` `2203.13109`
`cond-mat/0307508` `physics/0111119` `physics/9703012`

## 新信号

1. **splice 残留 1524（s40 为零）**——集中 7 篇：`2403.15096`(572) `2403.15118`(236)
   `1608.02516`(212) `2105.03750`(205) `1206.5602`(204) `2308.12712`(53)
   `physics/9703012`(42)。其中 1206.5602、physics/9703012 同时在管线引入失败清单
   → 残留与管线失败相关而非孤立噪声。建议立项：逐篇看 leftover ph 的 id 形态
   （模型幻觉新 ph id vs ph_map 缺键 vs 阶梯 fallback 路径漏替换）。
2. **reject 9 篇全是 documentstyle 系**（8 latex209 + 1 unknown）——正是
   compile 引擎层「documentstyle 降级实试编」的受益面；其中 `math/0111203` 等
   base=clean 已证可编。
3. `skipped=completed`：本轮 skipped=0，瞬断样本未出现；语义评审仍按 xlat-review
   线推进。
4. n100 失败样本里 2403/2105/2308 等近代篇目占比上升——残留/失败分析建议优先
   这几篇（s40 全是 07-12 老样本，机制覆盖面不同）。
