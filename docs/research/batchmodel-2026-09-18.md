# 批大小-延迟-吞吐模型：devin2api 日志实测与 batch 设定推荐（2026-09-18）

> 数据：fht-mba 生产实例 `~/Library/Application Support/devin-2api/devin-2api.db` `logs` 表，archbox→swe-2-medium 86,705 行（2026-09-16→18，全部为 texlate 流量）。分析脚本与中间产物 `tmp/exp/batchmodel/`（gitignored）。回答的问题：batch 大小、并发 K、单请求延迟与整篇耗时之间的定量关系。

## 1. 单请求延迟分解（85,893 条可解析 200 响应）

`logs` 的 timing 字段全是自请求到达的 ms 偏移，拆出四段：

| 段 | 含义 | p50 | 随规模变化 |
| --- | --- | --- | --- |
| `gw_queue = upstream_sent` | 网关内部排队（等上游派发） | 2ms（忙时 p75=34s） | 与自身大小无关，与池子饱和度有关 |
| `conn = open − sent` | 上游建连 | 1788ms（p90 4.4s） | 固定开销 |
| `ttft = first_upstream − open` | 上游首字节（内部流式） | ~600ms | **对 input token 不敏感**：tin 0→85K 分桶 p50 全在 580–640ms（线性系数 0.005ms/tok≈0）；cache 命中仅省 ~40ms |
| `decode = dur − first_upstream` | 流式生成段 | ~1.6s | **= 543 + 13.3·out_tok（RMSE 5.2s）**，即 ~75 tok/s/流，分桶验证 10–12ms/tok 到 2000+ tok 不衰减 |

非排队单请求 ≈ **2.9s 固定 + 13.3ms × 输出 token**。「输入大请求慢」的直觉被证伪：大到 85K tok 的输入对延迟几乎无影响，decode 是唯一随规模增长的段。

## 2. 池子上限：~550 out_tok/s 全局 decode 吞吐

- 上游账号池 = `yanjian` + `randall` 两账号轮转（各 ~35K 请求）。
- 最忙 7 个小时（09-18 02:00–09:00）out_tok/s = **555/549/547/520/473/435/410**——随 req/s 在 1.6→2.3 波动而 token 吞吐钉在 ~550，是共享 decode 吞吐上限的特征，不是 RPM 闸。
- 550 ÷ 75 tok/s/流 ≈ **7.3 条有效 decode 流**：上游满速只够 ~7 条流同时吐 token；在飞数（重建 `[sent, dur]` 区间重叠）忙时冲到 40–68，超出部分只是摊薄每流速率、制造 gw_queue。
- 满负荷下单流 decode 速率 = 550/在飞数——在飞 25 时 ~22 tok/s，与实测吻合。

## 3. 耗时方程

整篇论文（输出 token 总量 T_out 固定、K 个 worker、n_req 个请求）：

```
slot_seconds = n_req × 2.9s + 13.3ms × T_out        ← 对池子的总需求（竞争期决定你的完成时间）
makespan(空闲) ≈ max(slot_s / K, 最长单请求)          ← 离散事件模拟验证
makespan(饱和) ≈ T_out / 你分到的 550 tok/s 份额      ← decode 主导，批大小无关
```

推论：批放大只削 `n_req × 2.9s` 固定项；**decode 总量不变**。空闲时 makespan 下限 = decode_total/K（K=10 → ~40s）；饱和时上限 = T_out/份额（独占全池也 ~55s/p50 论文）。

## 4. 策略扫描（38 篇真实 chunk 分布，cost-model stats.json，K=10，p50 论文）

out_tok ≈ 0.40 × src_chars 换算；in_tok = 3500 固定摊销 + chars/4。

| 策略 | n_req | makespan | slot_s | in_tok | 最长单请求 |
| --- | --- | --- | --- | --- | --- |
| 现状 <300 入批 / ≤2000 | 94 | 72.3s | 702s | 347K | 13.1s |
| 全量入批 ≤2000 | 46 | 59.1s | 551s | 182K | 13.4s |
| 全量入批 ≤4000 | 22 | 60.8s | 480s | 97K | 23.7s |
| 全量入批 ≤4000 cap20 | 23 | 59.0s | 483s | 100K | 23.7s |
| 全量入批 ≤6000 cap20 | 15 | 61.0s | 467s | 73K | 34.0s |
| 全量入批 ≤8000 cap20 | 12 | 59.1s | 461s | 64K | 44.3s |
| 全量入批 ≤12000 cap40 | 8 | 65.5s | 441s | 46K | 65.3s |

K 敏感度（makespan p50）：现状 K=3→235s / K=10→72s / K=20→38s；≤6000cap20 K=3→163s / K=10→61s / K=20→34s。**K=3 模拟 235s vs server 实测 ~260s（perf.md）、K=10 模拟 72s vs 估 ~78s——模型与真实 e2e 吻合**。

读法：

- makespan 在 ≤4000 之后就平了（~59–61s）——decode 主导项 `r·T_out/K` 封底，继续放大只削固定开销。
- slot_s（竞争期真正成本）随批大持续下降但收益递减：2000→4000 砍 13%，4000→8000 再砍 4%。
- in_tok 收益最大：现状 347K → ≤4000 全量批 97K（-72%）→ ≤8000 64K（-82%），与 cost-model「~40% 总 token」方向一致（口径差异：本文只计 input）。
- ≤12000/cap40 反而变慢：n_req=8 < K=10，worker 空闲 + 65s 巨请求拖尾——**n_req 必须 ≥ ~1.5×K**。

## 5. 推荐设定

- `SHORT_CHAR_LIMIT` 取消（全量入批）——≥300 单发的 34% chunk 占 89% 请求数，纯浪费固定开销。
- `BATCH_MAX_CHARS` 2000→**4000–6000**（p50 论文 n_req≈15–23 ≈ 1.5–2×K=10）。再大对耗时无补，徒增单请求 44s+ 的拖尾与 max_tokens=8192 截断风险。
- 新增**每批条数上限 ~20**（`[n]` 协议失败时整批退单翻的爆炸半径；p50 chunk ~300 字符时 4000 字符批天然 ~13 条，cap 只在碎 chunk 多时生效）。
- K：管线 `DEFAULT_CONCURRENCY=10` 保持；**server `worker/translate.py` 的 3→10**（实测上 e2e 236s→72s 级别的 3× 杠杆）；K>15 只在空闲池有边际收益，饱和池 ~7 条流即分完 550 tok/s。
- 真要再压耗时，杠杆不在 batch：`跳译参考文献/附录` 直接削 T_out（hjfy 低 3× 的解释之一），或换 decode 更快的模型档。
