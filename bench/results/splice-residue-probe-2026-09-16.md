# splice 残留 1524 根因归因（e2e-real n100 新信号）

- date: 2026-09-16，调查对象：`bench/results/e2e-real-n100-2026-09-15/` 中
  leftover_ph 合计 1524、集中 7 篇（2403.15096×572、2403.15118×236、
  1608.02516×212、2105.03750×205、1206.5602×204、2308.12712×53、
  physics/9703012×42）。
- 结论：**续跑状态污染**——`_xlat_state` resume 仅按位置性 chunk_id 命中、
  无内容指纹校验；parse 漂移后陈旧译文被嫁接到新 chunk，其 `[[X_n]]` id 在
  新 ph_map 中缺席 → splice 留字面量，且 state.json 重写把污染固化为
  `ok` 永久自锁。

## 1. 残留形态

残留 token 全是规整 `[[TYPE_n]]`，非截断/变体。2403.15096 一篇：
MATH×276、REF×189、CITE×42、MACRO×29、CMD×19、BIB×17，合计恰 =572
（与 leftover_ph 计数精确吻合）。位置在正文译文行内（如
`与量子 [[MATH_2]]--(余)矩阵对`），集中在译文 chunk 区。

附注：2403.15096 源文本另有 51 个 `[[G\hskip1,5pt]]`/`[[ r , s ]]` 类
**Lie 双括号字面量**（非 `[[TYPE_n]]` 形态，PH_RX 不匹配，不属残留，
过 pipeline 原样透传正确）。次级隐患：这些字面 `[[..]]` 进 chunk 喂模型，
可能诱导模型「正规化」出形似占位符的 token——本次未实证，列为观察项。

## 2. 根因链（每环有实证）

1. **签发侧无 bug**：对 2403.15096 复刻 bench 全路径
   （copytree → `normalize_project` → `parse_file(flatten=False)`），
   全部 chunk.content 与 pieces.text 中 `[[X_n]]` 引用 100% 命中
   res.ph_map，悬空引用 = 0。
2. **state 记录与新 parse 不一致**：`_xlat_state/2403.15096/state.json`
   记录 `0:1`.source = `{Quantum Group Deformations \\ and Quantum
   [[MATH_2]]--(co)matrices ...}`；而 HEAD parse 的 chunk id=0 =
   `Quantum Group Deformations \\ and Quantum [[MATH_1]]--(co)matrices`
   （无 `{}` 包裹、ph 编号也不同）。同一 `0:1` id 下内容不同——
   记录出自另一 parse 版本。
3. **模型无罪**：逐条核对 state.json 全部 results，没有任何一条
   translation 含有其自身 source 中不存在的 `[[X_n]]`（2403.15096
   597 条、1608.02516 87 条、1206.5602 127 条全绿）——幻觉/改号
   假说排除。
4. **跨跑次表 = 漂移点与残留点一一对应**：

   | paper | s40 | s40-r2 | v3-100 | n100 |
   |---|---|---|---|---|
   | 2403.15096 | 580ch/0ph | 580/0 | **581/572** | 581/572 |
   | 2403.15118 | 158/0 | 158/0 | **155/236** | 155/236 |
   | 1608.02516 | — | — | 85/0 | **87/212** |
   | 2105.03750 | 105/0 | **105/205** | 105/205 | 105/205 |
   | 1206.5602 | 118/0 | 118/0 | 118/0 | **127/204** |
   | 2308.12712 | 120/0 | **119/53** | 119/53 | 119/53 |
   | physics/9703012 | — | — | 54/0 | **52/42** |

   残留恰在 chunk 计数/编号发生变化的跑次首现；总数不变也可污染
   （2105.03750 同 105 但 s40→r2 0→205）——中段 chunk 内容重排即可，
   不必总数变。一旦写入 state 即自锁：2403.15096 的 572 残留在
   v3-100→n100 间原样传染（两次 parse 已同形仍残留）。
5. **错位机理**：`_route_chunks`（`src/texlate/xlat/pipeline.py:652`
   附近）`cid in completed and cid in done_map → continue`——只比
   `chunk_id`，不比 `rec.source == c.content`。陈旧记录的
   `[[MATH_2]]` 型译文被 splice 进当前 res，`expand()`
   （`latex/reconstruct.py:138-153`）trans→ph_map→CHUNK 三查全落空 →
   返回字面 token → `leftover_ph` 计数（`e2e_real_bench.py:222`）。

## 3. 归属层与连带

- 归属：**xlat/pipeline 续跑装载层**（`_load_resumed`/`_route_chunks`，
  pipeline.py:606-671）。不是 segmenter/ph_map 签发问题，不是模型问题。
- 「管线引入失败」8 篇中重叠的 1206.5602、physics/9703012 大概率同根因：
  1206.5602 的 `Missing $ inserted`（bessatsu_arXiv.tex:357）报错行上
  即有 `[[REF_119]]`/`[[CITE_*]]` 残留——ph 字面量进数学环境扰动 TeX
  状态。
- 移交 Task #10（xlat-review 正在同文件改 resume 语义，611-614 已有
  skipped/fault 重试修订）：本发现是其紧邻片区。

## 4. 修复建议（按性价比）

1. **最小正确修复**：`_route_chunks` resume 命中处加内容校验
   `done_map[cid].source == c.content`（或存 content hash/segment_key
   比对），不匹配转入 pending 重翻。一行量级，顺带自愈存量污染
   （不匹配记录自然被重翻覆盖）。
2. state 记录加 parse/pipeline fingerprint 字段，版本变整体不命中
   （粗粒度兜底，与 1 互补不互替）。
3. 存量清理：7 篇受影响 `_xlat_state` 删除重跑，或靠修复 1 自愈。
4. 可观测性：`reconstruct` 的 expand 对 ph_map 查无的 PH_RX token
   记 warning（现静默留字面）；e2e bench 把 `leftover_ph>0` 纳入
   门槛断言（当前只统计不报警）。
