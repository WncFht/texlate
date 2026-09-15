# xlatbench B4a 硬契约回归 — 2026-09-15

> 目的：glm-5-2 promo（2026-09-16T07:59Z 到期）前的契约基线 + E22 定案复核 + 网关特性补测（docs/05 §8 开放项 10）。
> Harness：`bench/py/xlatbench.py`（tmp/exp/gwbench/bench_free.py 扶正版，E22 口径：hard_ok = validator 无 error ∧ 无丢/造占位符 ∧ 无丢脆弱命令；ph_order 降软信号）。
> 样例池：与 E22 逐字节一致（36 真实 chunk 等距抽 + S1–S4 合成压力 = 40 样例 × 2 轮 = 80 调用/模型，temp 0.2、max_tokens 8192、串行）。
> 产物：`results.jsonl`（240 调用明细）、`models.json`（聚合+失败现场含 src/zh）、`http_errors.jsonl`（8 条网关错误原始记录）、`feature_probe.json`（特性探针 34 条）、`models_panel.json`/`models_v1.json`/`free-tier-snapshot.md`（免费集快照）。

## 0. TL;DR

**E22 定案复核通过**：`swe-2-medium` 仍是默认（99% 硬契约、rsn p50=98 思考地板、out 中位 133 tok、6.4s/chunk）。但 **"100% 硬契约"要修正为 ~99%**——本轮它在 `1207.7214#0` 上首次犯案，犯的正是 swe-2-max 在 E22 C 组犯过的 `\ `+中文熔合（`\和`/`\道…`）。glm-5-2 维持 90% 垫底且复现了"连吞 9 占位符"灾难级失败。

**网关新发现**：

1. **本地限流真实存在**：`rate_limit_exceeded` 429，body 带结构化 `retry_after`（秒）——docs/08 重试阶梯的 "Retry-After 从其值" 在此要读 JSON body 字段而非 header。
2. **SSE 对流支持但 swe-2 系假流式**：glm-5-2 真流式（TTFT 0.5s、54 chunks 摊开 1.1s），swe-2-medium/max 全部 delta 在最后 ~0.3s 一次性倒下（上游缓存后转发）；`stream_options.include_usage` 可用。
3. **`response_format` 静默忽略**：json_object/json_schema/非法值同输出——slots-JSON 兜底阶梯在此网关只能靠 prompt 自觉。
4. **并发**：x16/x32 突发零拒绝，延迟随并发平缓退化（glm-5-2 在 x8 起 p50 3.9→13.8s 排队）——docs/08 的 `Semaphore(10)` 在余量内。
5. 隐藏 prompt token 仍在且按族分档：swe-2 系 468-469、claude 566、swe-1-7 系 350-384、glm 系 391；glm-5-2 实测命中 prompt cache（`cached_tokens=320`，GLM 线首次观测到）。

## 1. 契约回归总表（vs E22 基线）

| model | n | hard_ok | E22 | ph_miss | ph_inv | cs_drop | ord_soft | lat p50/p95 | rsn p50/p95 | in_tok med | out_tok med |
|---|---|---|---|---|---|---|---|---|---|---|---|
| swe-2-high | 80 | 80 (100%) | 79 (99%) | 0 | 0 | 0 | 19 | 11.4/19.5s | 442/1301ch | 273 | 453 |
| swe-2-medium | 80 | 79 (99%) | 80 (100%) | 0 | 0 | 1 | 20 | 6.4/14.6s | 98/144ch | 273 | 133 |
| glm-5-2 | 80 | 72 (90%) | 73 (91%) | 9 | 0 | 7 | 19 | 3.3/10.3s | 1603/3765ch | 189 | 677 |

（另：8 次传输层错误已从 results.jsonl 挪 `http_errors.jsonl` 并以 4s 间隔补齐——7×429 全在 glm-5-2 run0 的一个 ~30s 窗口、1×502 `server closed idle connection` 在 swe-2-medium；补跑全部 200 且契约通过。）

## 2. 失败现场归因

| 失败 | 形态 | 判读 |
|---|---|---|
| glm-5-2 `1111.4914#3` run1 | **连吞 9 个 MATH 占位符**（[[MATH_1566]]–[[MATH_1574]]），validator error | E22 同一样例同一灾难以同规模复现——确定性缺陷，非抖动 |
| glm-5-2 `1207.7214#{0,1,2,4}` 4 例 + `S1`×2 | `\ `/`\,` 脆弱命令计数掉（8→4、2→0 等），`\ ` 与中文熔合 | 与 swe-2-max 同族的 `\和` 型熔合；S1 两轮丢 `\ ` 复现 E22 |
| swe-2-medium `1207.7214#0` run1 | `\ `×4 全熔（`\和`×3 + `\道的改进…`），validator warn 新增 cs | **swe-2-medium 首次观测到熔合**——E22 的 100% 是样本运气；该样例是可靠触发器 |
| swe-2-high | 无硬失败 | ord_soft 19 全是合法中文换序（抽查同 E22） |

**机理更新**：`\ 和`/`\ 道` 熔合不是 swe-2-max 独有——它是"控制空格 `\ ` 后随英文词（and/channels）被译成中文单字直接黏在 `\` 后"的通用失败模式，swe-2 系和 glm-5-2 都会犯，`1207.7214`（ATLAS，`\ and`/`\  channels` 密集）是天然触发器。cs_dropped 硬判据 100% 捕获了全部 10 例。

## 3. 网关特性探测（`feature_probe.json`）

### 3.1 隐藏 prompt 开销（"Say OK" ×2，`usage.prompt_tokens`）

| model | prompt_tokens | 对照 E21/E22 |
|---|---|---|
| glm-5-2 | 391 (2/2 同值) | GLM 线开销最小（一致） |
| swe-2-medium | 469 (2/2 同值) | ~465-477（一致） |
| swe-2-high | 469 (2/2 同值) | 同上 |
| swe-2-max | 468 (2/2 同值) | 同上 |
| swe-1-7 | 384 (2/2 同值) | — |
| swe-1-7-medium | 350 (2/2 同值) | ~350-500（一致） |
| glm-5-3-low | 391 (2/2 同值) | 同上 |
| claude-sonnet-5-medium | 566 (2/2 同值) | 566（一致） |

结论：每请求固定 ~350–570 注入 token **仍在**，按上游族分档；E20 上调口径正确。

### 3.2 流式 SSE（chat/completions stream=true）

| model | TTFT | total | chunks | 时间分布 | rsn/content 分离 | `[DONE]` | include_usage |
|---|---|---|---|---|---|---|---|
| swe-2-medium | 9.91s | 10.13s | 18 | **假流式**：delta 挤在末 ~0.3s | 是 | ✓ | – |
| glm-5-2 | 0.52s | 1.63s | 28 | 真流式 | 是 | ✓ | – |
| swe-2-max | 12.23s | 12.52s | 18 | **假流式**：delta 挤在末 ~0.3s | 是 | ✓ | – |

补测 `stream_options:{include_usage:true}`：两家均下发 usage 帧；swe-2-medium 24 chunks 全落在 10.11–10.39s（0.28s 内），glm-5-2 54 chunks 摊在 0.77–1.86s。**swe-2 系经本网关拿不到渐进输出**——流式 UX/早期中止只能靠 glm/sonnet 系；对 swe-2 而言 stream=true 仅剩 include_usage 价值。

### 3.3 并发上限（同一 ~450 字符样例，每级 n 请求）

| level | swe-2-medium p50/max/err/rps | glm-5-2 p50/max/err/rps |
|---|---|---|
| x1 | 9.4s / 10.2s / 0 / 0.108 | 3.9s / 9.2s / 0 / 0.232 |
| x4 | 8.0s / 10.5s / 0 / 0.417 | 4.2s / 6.9s / 0 / 0.605 |
| x8 | 9.2s / 10.8s / 0 / 0.738 | 13.8s / 15.8s / 0 / 0.508 |
| x16 | 7.9s / 17.9s / 0 / 0.446 | 13.0s / 16.4s / 0 / 0.489 |
| x32 | 6.3s / 16.1s / 0 / 0.993 | — |

无硬拒绝到 32 并发；吞吐 x8 饱和（swe-2 rps 0.74→x16 反降因尾部）。glm-5-2 x8 起排队翻倍——上游 ZAI 侧排队而非网关拒绝。**Semaphore(10) 安全**；429 是 per-window 消息配额（`local gate`），与并发宽度无关，由共享租户流量触发（healthz 常驻 ~22-26 active_requests 他户）。

### 3.4 response_format（`Return a JSON object` 任务）

| variant | swe-2-medium | glm-5-2 |
|---|---|---|
| `json_object` | 200，合法 JSON | 200，合法 JSON |
| `json_schema` strict | 200，合法 JSON | 200，合法 JSON |
| `bogus_type`（非法值） | 200，合法 JSON | 200，合法 JSON |

**字段被静默透传/忽略**（同 free-swe.md 对未知字段的观察）：非法 type 也不报错，输出靠 prompt 自觉。docs/08 重试阶梯的 slots JSON 兜底（`response_format json_object`）在本网关**无强制力**——只能当提示词增强用，`⟪S0000⟫` 槽位解析失败仍要按解析失败路径退避。

### 3.5 熔合复现（swe-2-max × `1207.7214#0` ×3）

- rep0: 24.75s fragile 8→4 fused=['\\和', '\\衰变道的改进分析结果相结合']
- rep1: 26.22s fragile 8→4 fused=['\\和', '\\衰变道的改进分析结果相结合']
- rep2: 14.19s fragile 8→8 fused=[]

2/3 复现熔合、1/3 干净——**已知坑仍在，概率性 ~2/3**。该样例可作 fixtures 级常驻回归。

## 4. 对 E22 / docs 的修订建议

1. **E22 表修正**：swe-2-medium 硬契约率 100%→**~99%**（同池复测仍有 ~1% 熔合尾部）；swe-2-high 99%→100% 本轮全绿但应同样按 ~99% 读（两模型差异在单事件级别，排序不变）。
2. **glm-5-2 窗口期数据封存**：90%（72/80），失败模式全复现（吞占位符+熔合），promo 到期后退出免费集不影响默认链。
3. **`\ `+中文熔合是通用模式**：建议 `1207.7214#0` 提为 xlat fixtures（`@Tnn` 级别），cs_dropped 判据有效性再次确认（10/10 捕获）。
4. **重试阶梯补丁**：429 的 `retry_after` 在 JSON body `error.retry_after`（秒，实测 22s），非 HTTP header——docs/08 §1.6 "Retry-After 从其值"需补"或 body 字段"。
5. **流式/JSON 条款**：swe-2 系 SSE 无渐进价值；slots JSON 兜底在本网关不依赖 response_format。
6. 网关版本已升至 **v0.10.0**（E21 时 v0.9.0-13-gcc28e95），健康检查显示多租户共享——429 风险随他户流量波动，429-退避必须进运行时。

## 5. 复现命令

```bash
python3 bench/py/xlatbench.py run --models glm-5-2,swe-2-medium,swe-2-high \
    --runs 2 --out bench/results/xlatbench-contract-2026-09-15
# 429 补齐：先把 http!=200 记录挪出 results.jsonl 再 --resume --gap 4
python3 bench/py/xlatbench.py report bench/results/xlatbench-contract-2026-09-15
python3 tmp/exp/gwbench/feature_probe.py {hidden|sse|concur|jsonmode|fusion} ...
python3 tmp/exp/gwbench/make_summary.py   # 本文件
```
