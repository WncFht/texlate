# gwpilot — 见缝插针网关调度器

`bench/py/gwpilot.py`：纯 stdlib 单文件，两个半件——自适应并发闸代理（`serve`）、断点续跑队列驱动（`run`）、单行状态（`status`）。动机：晚上 API 富裕时把 swe-2-medium 并发打满（默认 `max_cap=40`），白天其他会话/产品链要用网关时自动让路，全程不需要人盯。

## 上游限流语义（archbox devin-2api `internal/adapter/devin/rategate.go` 实读）

- 上游按自然分钟桶限约 80rpm（`max_rpm: 80`，**被拒的尝试也计数**——硬闯会把 1 分钟小限流续成十几分钟自封）。网关把发送对齐到同一套分钟桶（桶界约 :59–:00，两端各 2s 死区）。
- 桶内配额耗尽 → 本地排队，预估等超 `gate_max_hold=15s` 直接快败 `429 + Retry-After`。
- 上游 `resource_exhausted` → 上冷却闩至声明 reset（无声明兜底 60s）；闩内只放 8s 间隔滴灌探针，其余立即 429+`Retry-After=闩剩余`；任一成功帧提前解闩。
- 观测面：`GET /healthz` → `active_requests`（全局在途，跨所有客户端）；`GET /admin/stats`（Bearer）→ `rpm_stats.recent_rpm`（全局近一分钟速率）、`recent.s60`（ttfb/dur/cache_pct）。
- 别名 `claude-opus-4-6 → swe-2-max` 意味着本机 Claude 会话与 bench 共喝同一 lane——这正是「让路」的对象。

## 调速算法（Governor）

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
# 常驻代理（任何 bench 指 --base-url 即过闸）
python3 bench/py/gwpilot.py serve [--max-cap 40] [--rpm-budget 72]

# 队列驱动——内嵌代理；3398 已活则自动 attach
python3 bench/py/gwpilot.py run bench/queue/night.jsonl --follow

# 脱管（>30min 纪律：setsid + run.log）
setsid nohup python3 bench/py/gwpilot.py run bench/queue/night.jsonl --follow \
    >> bench/results/gwpilot/run.log 2>&1 </dev/null &

# 观测 / 热调
python3 bench/py/gwpilot.py status
curl -XPOST localhost:3398/__gwpilot/control -d '{"max_cap":8,"pause":true}'
touch bench/work_gwpilot/PAUSE   # 或 --pause-file 指定哨兵：存在即全员让路
```

各 bench 的接入点：`stagerun xlat --base-url {GW}`、`e2e_real_bench --base-url {GW}`、`qualbench --base-url {GW}`、`fixloop llm_hook`/texlate server 读 `TEXLATE_BASE_URL` env（run 驱动已默认注入）。客户端的 `--sem/--concurrency` 变成「意愿值」，真实在途由代理裁。

## 队列文件（`bench/queue/*.jsonl`，可入库）

每行 `{"id": "唯一", "sh": "shell 串"}` 或 `{"argv": [...]}`，可选 `"env": {}`、`"cwd"`。`{GW}` 占位符展开成代理 URL。`#` 注释/空行允许。语义：

- 串行执行（任务内部已并发，闸在代理层）；`done` 跳过、`failed` 重试 ≤3 次（`--retry-failed` 重置计数）、中断回 `pending`。
- 状态 `bench/work_gwpilot/state/<queue>.state.json`；日志 `bench/work_gwpilot/logs/<queue>/<id>.log`。
- `--follow`：排空后每 60s 重扫——随时往里 append 新行即续命，断断续续的真正含义。
- `--max-load N`：load1 超阈值不发新任务（在跑的不杀）。
- `task_ping` 约定上报 status_panel（`bench/results/status-panel/`）。

## 现成的大活（按网关消耗排序）

| 任务                               | 量级                        | 备注                               |
| ---------------------------------- | --------------------------- | ---------------------------------- |
| `stagerun xlat --arm real` 全层    | ~1335 篇 × ~50块 ≈ 6 万请求 | 最大池；`--dir` 钉死防跨零点拆批   |
| `e2e_real_bench --n N`             | 每篇≈块数+fixloop           | 全链基线；records 续跑             |
| `qualbench run --source state`     | 每 chunk 1 次 judge         | judge/被评模型解耦 `--judge-model` |
| `stagerun fixloop --llm` / wave.py | 每难格数次                  | `llm_hook` 走 env                  |
| `xlatbench run --models ...`       | docs×per-kind×runs          | 多模型横评                         |

CPU 侧不占网关的阶段（ingest/parse/compile/fixloop/mock xlat）可同队列混排，夜批一条线跑完。
