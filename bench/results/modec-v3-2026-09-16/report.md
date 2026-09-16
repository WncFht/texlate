# e2e_mock_bench Mode B/C — corpus_v3 首跑（2026-09-16）

`e2e_mock_bench.py` 新增 `--corpus`（v3 manifest 布局自动识别：`manifest*.jsonl` → `{id}/extracted/`）、`--layers/--sample/--seed/--ids` 采样面、非默认语料隔离到 `work_e2emock/<corpus名>/`，并修 `_seg_of` CRLF 归一化（旧实现下 sabotage 事件蒸发、escaped 指标失真偏低）。代码已入库 `7f165eb`。

## 采样与矩阵

`--corpus bench/corpus_v3 --sample 50 --seed` 抽样 50 篇，实跑 48（0806.3179、1608.02631 无 main tex 跳过）。四臂：base-xel（原样编译基线）/ pipe-xel（mock 翻译+注入+编译）/ pipeB-xel（Mode B 占位符破坏）/ pipeC-xel（Mode C 段落挪位+splice）。逐篇矩阵见 `matrix.md`，台账见 `results.json`/`records.jsonl`。

- base-xel clean 22/48；pipe-xel clean 27/48；pipeB-xel clean 24/48；pipeC-xel clean 17/48
- pipe-xel 失败且 base-xel clean（管线引入退化）：仅 `0806.3472`（base clean → pipe partial）
- tectonic 臂本轮未开（xel 单引擎）

## Mode B：破坏哨兵台账 — escaped==0 PASS

注入破坏块 **1564**（事件 4932）→ caught **1345** / recovered **219** / **escaped 0**。门槛 `escaped==0`：**PASS**。

| 破坏类型 | caught | recovered | escaped |
| --- | --- | --- | --- |
| fabricate_ph | 752 | 70 | 0 |
| drop_ph | 272 | 147 | 0 |
| drop_ph+fabricate_ph（混合） | 321 | 2 | 0 |

`_seg_of` CRLF 修复后事件不再蒸发，本数字是真实全量。新增 `by_kind` 分类账 + `escaped_detail` 字段落 `results.json`，逃逸个案可直接定位块。

## Mode C：挪位 splice 台账

挪位 2537 处 / 涉块 1590 → 进 splice **1575（99.1%）** / 回退 15。编译 verdict 分布 `{clean:17, fail:8, partial:18, reject:5}`；存活 35/42 篇出 pdf。

对 pipe-xel 基线退化 7 篇，**全部 harness 归因，零扰动致编译回归**：

- 5 篇 inject_reject `latex209` 门不对称（astro-ph/0104134、astro-ph/0501428、cond-mat/9910284、math/9901064、nucl-th/0307063）：pipe-xel 臂同标 latex209 但放行出 partial pdf；Mode C 挪位后注入臂的 latex209 保守门触发 reject 无 pdf——harness 门宽严不对称，非挪位产物本身编译坏。
- 2 篇 missing cls/sty（hep-th/0408076、quant-ph/0307209）：pipe-xel clean，pipeC 编译 missing_file——Mode C 工作区姊妹文件不齐，harness 侧文件拷贝问题。

## corpus39 / v3-180 重述对照

用修复后 `_seg_of` 重计历史臂：corpus39 + v3-180 联合重述出 **escaped 1**——一例 fabricate-into-comment（伪造占位符落进注释区），**L0 `mask_comments` 掩码洞**：注释内出现的 `[[TAG_n]]` 不被规则层检出。vs v3-50 本轮 escaped 0。该洞为产品侧真实缺口，已立项待修（L0 mask_comments 需覆盖注释区占位符模式，或 sabotage 注入面排除注释）。

## 已知边界

- pipeC 臂缺 L2+fixloop 尾段（harness 不对称项：pipe 臂走完整编译链，pipeC 止于首编 verdict）——`pipe_mode_condition` 口径待拉齐。
- Mode B 的 caught/recovered 判据是占位符哨兵层面，不直接等价"编译是否通过"；编译面由 base/pipe 臂对照承载。
