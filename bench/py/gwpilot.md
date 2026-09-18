# gwpilot — 见缝插针批跑驱动

`bench/py/gwpilot.py`：纯 stdlib 单文件。主件是断点续跑队列驱动（`run`），另留一个自适应并发闸代理（`serve`）作兜底。

**2026-09-18 起网关侧 fg/bg 分级准入已上线**（需求规格 内部网关准入设计文档）：批跑拿 `class=bg` 令牌直连 网关 base-url，fg 动态预留、bg 闸内排队（~120s 预算）、快败 `429+Retry-After+X-Gate-Reason` 全由网关做——客户端**不需要**任何本地调速，`serve` 仅留给无分级网关的场景。

bg 令牌存放：`bench/work_gwpilot/bg.token`（gitignored）或 env `GWPILOT_BG_KEY`。队列里 `{BGKEY}` 占位符自动展开；`run` 注入 `TEXLATE_API_KEY`/`TEXLATE_GATEWAY_KEY`/`TEXLATE_BASE_URL` 默认值覆盖 env 驱动的入口（llm_hook 等）。

## 网关侧语义（直连模式要懂的）

- bg 请求可在闸内排队最长 ~120s 才出首字节——`xlat/client.py` 的 `read` 超时已抬到 300s 覆盖此；429 只代表预算真耗尽，按 `Retry-After` 睡满再试（xlat `call_with_backoff` 已直接信 `retry_after`，不叠加退避）。
- `X-Gate-Reason`：`quota`=桶满/被 fg 预留挡住（睡到下一窗口）；`latch`=上游冷却闩（睡闩剩余，可能几分钟）；`hold`=闸内排队超预算（睡到下一窗口）。
- 每响应带 `X-Gate-Class/Lane/Window-Used/Window-Quota/Window-Reset/Wait-Ms`——排障与节奏校准用，正常跑批不依赖。
- 观测可选：`/admin/runtime-metrics` 的 `window_used_fg/bg`、`waiters_fg/bg`、`reject_bg_reserve_count`；`/admin/active-requests` 每行带 class。

## 上游限流语义（网关 rategate 实现实读）

- 上游按自然分钟桶限约 80rpm/lane（**被拒的尝试也计数**——硬闯会把 1 分钟小限流续成十几分钟自封）。网关把发送对齐到同一套分钟桶（桶界约 :59–:00，两端各 2s 死区）。
- fg/bg 分级：`fg_rate` EMA × 桶剩余秒 + `waiters_fg` + margin(4) = fg 预留量；bg 只用预留外槽位，fg waiter 永远先于 bg waiter 出队。fg 排队上限 15s 快败，bg 120s。
- 上游 `resource_exhausted` → 上冷却闩至声明 reset（无声明兜底 60s）；闩内只放 8s 间隔滴灌探针，任一成功帧提前解闩。
- 别名 `claude-opus-4-6 → swe-2-max` 意味着本机 Claude 会话是 fg 流量——bg 预留机制正是为它让路。

## 调速算法（`serve` 模式内部件——本网关已不需要）

每个打向 `/v1/chat/completions|/v1/messages` 的 POST 先过闸，其余路径直通。v2 起有两层：**精确桶算术**（主）+ **AIMD 兜底**（accounts 数据过期或上游行为漂移时接管）。

### 精确桶算术（/admin/accounts，默认 3s 轮询）

网关多 lane 池（当前 yanjian + randall 两条，每条 window_quota=80/自然分钟桶）。每轮读出每 lane `window_used/window_quota/latched/sendable/waiters/inflight`，聚合：

```
win_remaining = Σ_可用lane (window_quota − window_used)     # 本桶还剩多少条
ext_rate      = EMA( (Δused_total − Δ我方发送) / Δt )        # 外部到达率（条/秒）
reserve       = ext_rate × t_left + ext_waiters + margin(4)  # 给外部留的余量
allowance     = max(0, win_remaining − reserve)              # 我方本桶还能发几条
我方已发 sent_win ≥ allowance → 睡到 min(window_next) 开新桶；换桶自动清零计数。
```

`latched`/`sendable=false`/`lane.healthy=false` 的 lane 不进 remaining——冷却闩在**吃 429 之前**就看见了。`ext_waiters` 进 reserve 是因为排队请求在窗口一开就落桶。

### 兜底与并发顶

```
eff_cap = min(cap, ceiling)；ceiling = min(max_cap, C_rpm, C_burst)
  C_rpm   = (quota_total 或 rpm_budget=72 — 外部速率) × lat_ewma / 60   # Little 定律
  C_burst = ext_inflight=0 → max_cap；否则 max(min_cap, max_cap − 8×ext_inflight)
cap AIMD：2xx +0.5；上游 429 → 砍半 + 冷却至 Retry-After；5xx/传输错 ×0.85。
```

accounts 数据 >12s 未刷新 → 精确桶门失效回退到纯天花板路径，啥都不假设。

排队语义与网关不同：请求**排队等待**而非快败——队满（128）或排队超 `queue_wait=100s` 才合成 `429+Retry-After`（body `error.retry_after` 与 xlat client 解析口径一致），客户端按自有退避再来。因为冷却闩期上游把被拒也计数，闸内等待比放出去吃 429 更省。

轮询：`/admin/accounts` 每 3s（闸门全态）；`/healthz` 每 4s（up_ok 活性 + accounts 过期时的 ext_inflight 兜底）。healthz 连续 3 次失败 → `up_ok=false`，`run` 暂停发新任务。

效果实测（2026-09-17 晚）：外部 143rpm 把可用 lane 桶打到剩 1 条时 `win_allowance=0` 全让、显示 23.9s 后开新桶；无人时 cap 爬坡至 40 顶格。

## 用法

```bash
# 队列驱动——默认直连网关（fg/bg 分级在网关侧）
python3 bench/py/gwpilot.py run bench/queue/night.jsonl --follow

# 脱管（>30min 纪律：setsid + run.log）
setsid nohup python3 bench/py/gwpilot.py run bench/queue/night.jsonl --follow \
    >> bench/results/gwpilot/run.log 2>&1 </dev/null &

# 调速代理（无 fg/bg 分级的网关兜底；本网关不需要）
python3 bench/py/gwpilot.py serve [--max-cap 40] [--rpm-budget 72]
python3 bench/py/gwpilot.py status                    # 代理模式观测
curl -XPOST localhost:3398/__gwpilot/control -d '{"max_cap":8,"pause":true}'
touch bench/work_gwpilot/PAUSE   # 或 --pause-file 指定哨兵：存在即全员让路
```

各 bench 的接入点：`stagerun xlat --base-url {GW} --api-key {BGKEY}`、`e2e_real_bench --base-url {GW} --api-key {BGKEY}`、`qualbench` 同款、`fixloop llm_hook`/texlate server 读 `TEXLATE_BASE_URL`/`TEXLATE_API_KEY` env（run 驱动已注入 bg 令牌）。客户端的 `--sem/--concurrency` 是「意愿值」，真实节奏由网关闸裁——可以往大填，bg 排队由网关消化。

## 队列文件（`bench/queue/*.jsonl`，可入库）

每行 `{"id": "唯一", "sh": "shell 串"}` 或 `{"argv": [...]}`，可选 `"env": {}`、`"cwd"`。`{GW}` 展开为网关 URL（`--serve` 时为本地代理），`{BGKEY}` 展开为 bg 令牌。`#` 注释/空行允许。语义：

- 串行执行（任务内部已并发，闸在代理层）；`done` 跳过、`failed` 重试 ≤3 次（`--retry-failed` 重置计数）、中断回 `pending`。
- 状态 `bench/work_gwpilot/state/<queue>.state.json`；日志 `bench/work_gwpilot/logs/<queue>/<id>.log`。
- `--follow`：排空后每 60s 重扫——随时往里 append 新行即续命，断断续续的真正含义。
- `--max-load N`：load1 超阈值不发新任务（在跑的不杀）。
- `task_ping` 约定上报 status_panel（`bench/results/status-panel/`）。

## 现成的大活（按网关消耗排序）

| 任务                               | 量级                         | 备注                               |
| ---------------------------------- | ---------------------------- | ---------------------------------- |
| `stagerun xlat --arm real` 全层    | ~1335 篇 × ~50 块 ≈ 6 万请求 | 最大池；`--dir` 钉死防跨零点拆批   |
| `e2e_real_bench --n N`             | 每篇≈块数+fixloop            | 全链基线；records 续跑             |
| `qualbench run --source state`     | 每 chunk 1 次 judge          | judge/被评模型解耦 `--judge-model` |
| `stagerun fixloop --llm` / wave.py | 每难格数次                   | `llm_hook` 走 env                  |
| `xlatbench run --models ...`       | docs×per-kind×runs           | 多模型横评                         |

CPU 侧不占网关的阶段（ingest/parse/compile/fixloop/mock xlat）可同队列混排，夜批一条线跑完。
