# devin-2api fg/bg 分级准入 — 需求规格

提出方：texlate（bench 批跑流量）。目标仓库：archbox `~/src/devin-2api`（Go）。日期：2026-09-17。

## 背景与动机

texlate 的 bench 批跑（stagerun xlat、e2e_real_bench、qualbench 等，单批可达数万请求）与交互式 Claude 会话、texlate server 产品链共用同一个 devin-2api 网关（fht-mba:3003）。当前在客户端侧有一个旁挂调度器 `bench/py/gwpilot.py`：轮询 `/admin/accounts` 拿每 lane 精确桶状态，用「剩余配额 − 外部需求预测」做自我节流，效果已验证（外部打满时让到 0，空闲时吃满）。

但客户端方案有三个结构性上限，只有把调度下沉进网关才能解决：

1. **双边礼让会撞车**：每个礼貌客户端各自估算对方需求，窗口边界上两个客户端同时放行即双双计桶；而被拒也计上游额度，撞车=浪费。
2. **空闲尾槽没人敢填**：分钟桶配额不用即废。客户端保守起见必须留安全边际；网关自己知道真实 `bucketUsed/waiters`，可以精确地把 fg 不用的尾槽放给 bg。
3. **请求无类别**：网关眼里所有请求同权，fg（交互会话，人在等）和 bg（无人值守批跑）排队顺序纯 FIFO——正确语义应该是 fg 永远插队、bg 只填空隙。

## 已核实的现状（开发前请先再读一遍，行号可能漂移）

- 闸门：`internal/adapter/devin/rategate.go`。`GateConfig{MaxRPM, MaxHold, DripInterval, DefaultLatch, WindowOffset, WindowGuard}`；准入入口 `gate.wait(ctx)`（≈L464），判定核心 `tryAdmit()`（≈L548，现为 `bucketUsed < quota && waiters == 0` 的严格 FIFO）；等待预估 `admissionSnapshot()`（≈L379）→ `gateAdmission`；闩管理 `noteUpstreamError/Success`；`stats()`→`GateStats` 喂 `/admin/accounts`。
- 调用点：`internal/adapter/devin/devin.go` ≈L769（chat 主路径）、`websearch.go` ≈L63。
- Token：`internal/authtoken/authtoken.go` 的 `Token` 已是富模型——Hash、IsActive、`IsModelAllowed`、Success/FailureCount、5h/daily/monthly 成本窗口、`TokenRow` 持久化全有。**加 `Class` 是字段级增量，不是新机制。**
- 配置：`internal/config/config.go` 现有 `gate_max_hold_seconds`、`gate_drip_interval_seconds`、`gate_default_latch_seconds`、`gate_window_offset_seconds`、`gate_window_guard_seconds`——新参数按同款命名落。
- 管理面：`internal/ccpanel/`（tokens.go 管 auth-tokens、accounts.go 管 accounts、quota.go）；`/admin/active-requests` 已有 per-request `api_key_used` 哈希归因。

## 需求

### R1 — key → class 映射（分类在认证层，不在路径/模型层）

- `Token` 增 `Class string` 字段：`"fg"`（默认）|`"bg"`。持久化进 `TokenRow`，`POST /admin/auth-tokens` 与 token 更新接口接受 `class` 参数，token 列表接口回显。
- 认证中间件解析 api_key → Token 后把 class 放进 request ctx，供下游（gate、active-requests、日志）读取。
- **默认 fg**：存量 key、匿名请求、未标 class 的全部按 fg 处理——行为与今天完全一致，零回归面。
- 不需要 per-request 头覆盖（`X-Request-Class`）：key 级粒度够用，header 覆盖反而开了自助降权的口子。

### R2 — 闸内分级准入（核心）

`tryAdmit` 按 class 分支，fg 语义完全不变，bg 加两条约束：

**a) fg 预留量（reserve）**，动态而非静态：

```
fg_rate    = fg 准入速率的 EMA（条/秒，可按 lane 计也可池级计后摊派）
reserve    = fg_rate × 本桶剩余秒数 + waiters_fg + margin   (margin 默认 4，可配)
bg 准入条件 = bucketUsed + 1 ≤ quota − reserve   （其余 sendable/latch/窗口死区判定照旧）
```

动态 reserve 的副产品正好是「work-conserving 尾槽填充」：`t_left→0` 时 reserve→`waiters_fg+margin`，桶尾无人用的槽自动放给 bg——不需要单独的收尾逻辑。margin 在 `t_left` 极小时也可随之收缩（如 `min(margin, ceil(t_left))`），细节实现者自定。

**b) 排队优先级**：现在 `tryAdmit` 里 `waiters == 0` 是严格 FIFO 公平。分级后需要：唤醒/准入时 fg waiter 永远先于 bg waiter（waiters 按类分开计数 `waiters_fg`/`waiters_bg`，容量释放先喂 fg 队列；`admissionSnapshot` 的等待预估对 bg 要把 fg 排队也算进去）。

**c) bg 的持有与快败语义**：bg 请求是无人值守负载，等得起——`gate_max_hold` 对 bg 放宽到可配的 `gate_bg_max_hold_seconds`（建议默认 120）。bg 因桶满/预留不足被快败时，`Retry-After` 应给**到下个窗口的秒数**（而不是 latch 剩余或泛化值），让批跑客户端直接睡到开桶；因闩被拒照旧给闩剩余。

### R3 — 响应头闸门遥测（`X-Gate-*`，每个响应都带）

gate 已经算出了所有这些值，零成本 piggyback：

| 头 | 含义 |
| --- | --- |
| `X-Gate-Lane` | 实际服务的 lane 名 |
| `X-Gate-Class` | 回显分类 fg/bg |
| `X-Gate-Window-Used` / `X-Gate-Window-Quota` | 准入时该 lane 桶用量/配额 |
| `X-Gate-Window-Reset` | 到 `window_next` 的秒数 |
| `X-Gate-Wait-Ms` | 本次在闸内排队耗时 |
| `X-Gate-Reason` | 仅 429：`quota`（桶满/预留不足）\| `latch`（冷却闩）\| `hold`（排队超时） |

客户端拿到这些后可以从轮询 /admin/accounts（3s 粒度、有额外流量）降级为**纯被动调度**：429+`X-Gate-Reason: quota` 就直接睡 `Retry-After` 秒，成功响应带 reset/used 就实时校准自己的余量模型。落点：devin.go L769 `gate.wait` 返回处已知 wait 耗时与 lane 身份，往响应 writer/ctx 里stamp 即可；429 路径 L632 附近同理。

### R4 — 管理面增量（可选，便宜就上）

- `/admin/accounts` 每 lane 增 `window_used_fg`/`window_used_bg` 分列（gate 里把 `bucketUsed` 拆成两个计数器即可），用于验证 bg 没有吃 fg 预留。
- `/admin/active-requests` 每请求增 `class` 字段。
- `GateStats` 增 `reject_bg_reserve_count`（因预留不足拒掉的 bg 数）——观测礼让强度的直接指标。

### R5 — 配置（`config.yaml`，沿用现有 gate_* 命名）

```yaml
gate_bg_max_hold_seconds: 120   # bg waiter 最长闸内排队（fg 仍 15s）
gate_bg_reserve_margin: 4       # reserve 里的固定安全边际
# fg_rate EMA 半衰期如需可配再加，不建议第一版就加
```

## 明确不做

- **周配额配速**：已确认本场景用的是免费 promo 模型，没有周限额概念；`quota.weekly` 字段纯信息展示，不要为它做 pacing。
- **lane 偏好/steering**：bg 不挑 lane，pool 选择逻辑不变，分级只发生在闸内。
- **按模型分类**：class 跟 key 走不跟 model 走；bg key 请求什么模型是它的自由。
- **向后兼容零破坏**：不发 class 的 key = fg = 今天的精确行为。

## 验收口径

1. bg key 满速打 + 模拟 fg 间歇打：fg 的闸内等待分布与今天（无 bg 时）统计不可区分；bg 被 429 时 `Retry-After` ≈ 到 window_next 的秒数、`X-Gate-Reason: quota`。
2. 网关完全空闲：bg 能把桶吃到 `quota − margin` 附近（不留静态 headroom 的死配额）。
3. fg 持续占满某 lane：bg 在该 lane 饿死但在其他 lane 正常漏——饿死期间不产生上游 `resource_exhausted`（被拒也计数的坑不能踩）。
4. 不带 class 的旧 key：全路径字节级行为不变。

## 客户端配套（texlate 侧，落地后我做）

- 给批跑签一个 `class=bg` 的 token；bench 直接 `Authorization: Bearer <bg-token>` 打网关，gwpilot 从「调速代理」退化回纯队列驱动（或保留做 job 编排，闸职能上交网关）。
- 读 `X-Gate-*`：成功响应校准余量模型；`quota` 型 429 睡满 `Retry-After`；`latch` 型退避并降并发。
