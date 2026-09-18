# 批大小 - 延迟 - 吞吐模型：devin2api 日志实测与 batch 设定推荐（2026-09-18）

> 数据：fht-mba 生产实例 `~/Library/Application Support/devin-2api/devin-2api.db` `logs` 表，archbox→swe-2-medium 86,705 行（2026-09-16→18，全部为 texlate 流量）。分析脚本与中间产物 `tmp/exp/batchmodel/`（gitignored）。回答的问题：batch 大小、并发 K、单请求延迟与整篇耗时之间的定量关系。

## 1. 单请求延迟分解（85,893 条可解析 200 响应）

`logs` 的 timing 字段全是自请求到达的 ms 偏移，拆出四段：

| 段                              | 含义                       | p50                 | 随规模变化                                                                                                   |
| ------------------------------- | -------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------ |
| `gw_queue = upstream_sent`      | 网关内部排队（等上游派发） | 2ms（忙时 p75=34s） | 与自身大小无关，与池子饱和度有关                                                                             |
| `conn = open − sent`            | 上游建连                   | 1788ms（p90 4.4s）  | 固定开销                                                                                                     |
| `ttft = first_upstream − open`  | 上游首字节（内部流式）     | ~600ms              | **对 input token 不敏感**：tin 0→85K 分桶 p50 全在 580–640ms（线性系数 0.005ms/tok≈0）；cache 命中仅省 ~40ms |
| `decode = dur − first_upstream` | 流式生成段                 | ~1.6s               | **= 543 + 13.3·out_tok（RMSE 5.2s）**，即 ~75 tok/s/流，分桶验证 10–12ms/tok 到 2000+ tok 不衰减             |

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

| 策略                   | n_req | makespan | slot_s | in_tok | 最长单请求 |
| ---------------------- | ----- | -------- | ------ | ------ | ---------- |
| 现状 <300 入批 / ≤2000 | 94    | 72.3s    | 702s   | 347K   | 13.1s      |
| 全量入批 ≤2000         | 46    | 59.1s    | 551s   | 182K   | 13.4s      |
| 全量入批 ≤4000         | 22    | 60.8s    | 480s   | 97K    | 23.7s      |
| 全量入批 ≤4000 cap20   | 23    | 59.0s    | 483s   | 100K   | 23.7s      |
| 全量入批 ≤6000 cap20   | 15    | 61.0s    | 467s   | 73K    | 34.0s      |
| 全量入批 ≤8000 cap20   | 12    | 59.1s    | 461s   | 64K    | 44.3s      |
| 全量入批 ≤12000 cap40  | 8     | 65.5s    | 441s   | 46K    | 65.3s      |

K 敏感度（makespan p50）：现状 K=3→235s / K=10→72s / K=20→38s；≤6000cap20 K=3→163s / K=10→61s / K=20→34s。**K=3 模拟 235s vs server 实测 ~260s（perf.md）、K=10 模拟 72s vs 估 ~78s——模型与真实 e2e 吻合**。

读法：

- makespan 在 ≤4000 之后就平了（~59–61s）——decode 主导项 `r·T_out/K` 封底，继续放大只削固定开销。
- slot_s（竞争期真正成本）随批大持续下降但收益递减：2000→4000 砍 13%，4000→8000 再砍 4%。
- in_tok 收益最大：现状 347K → ≤4000 全量批 97K（-72%）→ ≤8000 64K（-82%），与 cost-model「~40% 总 token」方向一致（口径差异：本文只计 input）。
- ≤12000/cap40 反而变慢：n_req=8 < K=10，worker 空闲 + 65s 巨请求拖尾——**n_req 必须 ≥ ~1.5×K**。

## 5. 活实验 A：`[n]` 协议稳健性网格（swe-2-medium 钉死，temp 0.2，CONC=6）

原料 = stagerun state.json 真实 masked chunk（含 `[[TYPE_n]]`），请求侧与产线完全一致（`build_system_prompt(kind, batch=True)` + `encode_batch` + `parse_batch_response`）。两轴扫描，每格 12 请求：

| cell                            | 批构成                      | 结果                                                                                         |
| ------------------------------- | --------------------------- | -------------------------------------------------------------------------------------------- |
| chars2000/4000/8000/12000/20000 | 字符上限 2K→20K，条数不封顶 | **60/60 全 parse_ok**；chars20000 格实测 n=44–53、chars ~19K、out_tok ~5–5.7K                |
| items10                         | 小 chunk 条数隔离轴         | 12/12 parse_ok                                                                               |
| items20/40/80                   | 同上                        | 中途遭遇 tailnet 断连（全部 `transport error`、ms 整齐钉在 connect timeout 10s），非协议失败 |

**结论：`[n]` 协议本身对批大小（字符与条数）不敏感**——n=53、19K 字符、5.7K 输出 token 的批全部干净解析。网格中 items40/80 两格全军覆没曾疑似协议崩塌，实为断连（items20 格 6 条失败全是 transport error、其中一条挂 462s 后断；chars20000 格的 n=44–53 批反而全过，反证条数非因）。网关恢复后重跑 solo/batch 臂 80+9 请求全成功，佐证。

## 6. 活实验 B：同 chunk 批翻 vs 单翻配对对比（80 chunk × 两臂）

同一 80 个 para chunk（<2500 字符）先逐条单翻、再装成 9 个 ~4000 字符批重翻：

- ph_missing/ph_misspelled：两臂全 0。
- ph_extra：**batch 臂 13/80 成员出现 extra（全部是 `[[NBSP]]`），solo 臂 0**——机制 = 模型把源文字面 `~`（如 `Fig.~[[REF_5]]`、`H.~Tan`）规范化成 `[[NBSP]]` 占位符。语义上反而是**更正确**的掩码恢复（`~` 本就是 NBSP），但 `validator=placeholders.diff().describe()` 把 extra 当失败 → 该成员 `_degrade_one` 单发重翻，白烧一次调用。
- en_resid：batch_better=1 / solo_better=6 / tie=73（±0.1），基本打平。
- len_ratio：batch 0.450 vs solo 0.436，打平。
- 耗时：solo 合计 809s slot vs batch 合计 279s（~3× 省，且批成员摊 ~3.5s/chunk vs 单发 ~10.1s/chunk）。

## 7. 产线对账（4320 对真实请求/响应 + 129K chunk state.json 全扫）

从 fht-mba sqlite 捞出 texlate 流量全部 debug 请求/响应体（prod_pairs.jsonl，416 批 + 3904 单发）：

- **批解析成功率 415/416 = 99.76%**，唯一失败是空响应（非格式错）。产线实际存在 12–14K 字符、40+ 条的批（早期/旁路大 cap 流量），全部 parse 成功——与活实验互证协议对大小不敏感。
- **成员级 ph 错（missing+misspelled，不含 benign extra）：batch 0.32% vs solo 8.93%（按占位符数归一）**；chunk 级同长度桶全部 batch 更优（300–600 字符桶 1.92% vs 3.91%；600–1200 桶 0% vs 6.3%）。solo 错率随块内占位符数陡升：0–5 个→3.8%，25–30 个→27.3%。
- extra 在产线几乎不存在：batch 成员 only_extra=2/5969（0.03%），solo 8/3903——活实验的 NBSP 喷发是小样本 + 源文 `~` 密度事件，但触发条件真实存在，值得在 validator 层豁免。
- 成员位置无效应（批内前/中/后段 ph_bad 0.36–0.61% 平）。
- en_resid 同长度桶两臂一致（0.03–0.05）；早先粗看 batch 21.5% vs solo 2.4% 是纯长度混淆（入批的都是 <300 短块，专名/引文占比天然高）。
- state.json 全扫（129K chunk）：修复链后 ph 问题清到 0.00%，`[n]`/`@@` 协议残码漏进译文 batch 0.041% vs solo 0.035%——泄漏面无差异。

## 8. 装箱策略终版模拟（38 篇真实分布，K=10，p50 论文）

等大装箱（n_req=ceil(total/cap)，顺序填到 target=total/n_req）+ K 量化（n_req 向上取 K 的整数倍）：

| 策略                     | n_req   | makespan  | slot_s   | 最长单请求 |
| ------------------------ | ------- | --------- | -------- | ---------- |
| 现状 <300/≤2000          | 92      | 72.2s     | 699s     | 13.5s      |
| 贪心 ≤4000 / ≤6000 cap20 | 22 / 15 | ~61s      | ~470s    | 24–35s     |
| 等大 cap=8000            | 10      | 51.2s     | 445s     | 49.4s      |
| **K 量化等大 cap=12000** | **10**  | **50.6s** | **444s** | **48.2s**  |
| K 量化等大 cap=8000      | 13      | 51.2s     | 458s     | 34.7s      |
| LPT 不保序参照界         | 14      | 66.5s     | 455s     | 33.8s      |

读法：等大装箱消除了「贪心首装造出 65s 巨请求」的拖尾问题（每批 ~等大 → maxreq≈makespan/K 波），makespan 压到 decode 下限 ~50s；K 量化保证 n_req 是 K 整数倍、不留半空波次。LPT 不保序反而更差（大 chunk 聚集破坏了 K 量化对齐）。

## 9. 最终推荐设定（修订版）

> 落地状态（2026-09-18）：1–6 已实装（`pack_batches` K 量化等大装箱 + `PipelineConfig.batch_*` 旋钮 + `extra=[[NBSP]]` 豁免 + server worker concurrency 10），7 缓做、8 留作后续杠杆。

1. **`SHORT_CHAR_LIMIT` 取消，全量入批**：批质量 ≥ 单翻（per-placeholder 错率 0.32% vs 8.93%），34% 单发 chunk 占 89% 请求数纯烧固定开销。>6000 仍走 `split_long_chunk`。
2. **装箱改 K 量化等大**：`n_req = ceil(max(K, total_chars/cap) / K) × K`，顺序填到 `target = total/n_req`。p50 论文 ~83K 字符 → n_req=10=K，每批 ~8.3K 字符。
3. **`BATCH_MAX_CHARS` 2000→12000**：协议实测 19K/53 条干净解析；out_tok/字符 p90=0.348 → 12K 字符 ≈ 4.2K 输出 token，max_tokens=8192 安全（20K 字符会逼近上限，不取）。cap 只在长论文上生效（p50 论文 K 量化后自然 ~8.3K/批）。
4. **条数软上限 ~32**：不为协议（53 条实测无恙），只为整批退单翻的爆炸半径兜底——产线批失败率 0.24%，但失败时 32 条退化的代价可接受。
5. **validator 豁免 `extra=[[NBSP]]`**：模型把 `~` 规范成 `[[NBSP]]` 是正确掩码恢复而非缺陷；当前 describe() 把 extra 判负 → 白触发 `_degrade_one` 单发重翻。产线 0.03% 但触发场景真实（源文 `~` 密度高的段落型批）。
6. **K：管线 10 保持，server worker 3→10**（e2e 实测级 236s→~72s）；K>15 饱和池无收益（~7 条流分完 550 tok/s）。
7. 可选小改：`caption` 批碎（p50=4 条/批，765 批）可并入 para 桶——需 prompt 并集，收益小（~百级请求），缓做。
8. 再压耗时的杠杆在 T_out 不在 batch：跳译参考文献/附录直接削 decode 总量（hjfy 低 3× 的主因之一）。

预计净收益（p50 论文，K=10，空闲池）：makespan 72s→~51s（-30%），slot_s 699s→~444s（-36%，高峰竞争期完成时间同比例改善），in_tok ~347K→~50K（-86%）。
