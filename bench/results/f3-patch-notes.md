# F3 patch notes — reject→partial 下游一致性（#85, 2026-09-16）

F3 已改 `e2e.py`/`judge.py`/`cli.py`：合成 verdict status 不再出现 `reject`，一律 `partial` + 顶层 `reject_at ∈ {"fixloop","inject","route"}` + `verdict.reasons` 保留 reject token。以下文件属其他 teammate 或未在 #85 文件面内，仅给补丁建议。

## `src/texlate/server/worker.py`（#80/#81 文件）

- **L1058-1065 `InjectRejectError → _fail("inject_reject")`**：语义等价于 e2e 的 inject 拒绝。按 F3 这不再是终态失败而属降级交付——建议改成任务以 `partial`/`degraded` 态收尾（zh-src 已产出，仅注入被拒），至少把 fault code 从 `inject_reject` 复用现有降级通道；若保留 fault 语义，task status 映射表应把 `inject_reject` 计入 partial 档而非 fail 档。
- **L1193-1195 `route.reject → _StageError(code="parse")`**：同上，route 拒绝目前记 parse fault；F3 下应归 partial 档（或新增 `route_reject` 软终态）。
- **L1697-1732 `_run_fixloop`**：只回 `rec.last or first`，cell verdict（含 `reject:<rid>`）不进 task status——`reject:*` 是引擎内部分诊枚举，F3 不变更，此处**无需改**；但 `_fixloop_summary`（L224）把 `cell["verdict"]` 原样进 `ctx.fixloop`/`task_events`，消费方（web 面板/fixloop-cases.jsonl 分析）需知 `reject:*` 是 cell 级枚举而非合成状态——展示侧可原样保留。
- L689-711 `reject_size`/`reject_dir_clash`/`reject_totalcap` warnings：unpack 层警告，与 verdict 无关，不动。

## `bench/py/e2e_real_bench.py`（bench harness）

- **L296-298**：`InjectRejectError → rec["status"]="reject"; verdict.status="reject"` → 改 `status="partial"` + `rec["reject_at"]="inject"`（与 e2e.py 同形），`verdict.reasons=[e.reason]` 保留。
- **L322 `_want_fix`**：`v == "reject"` 分支在 F3 后永远摸不到——verdict.status 已是 partial；改判 `(rec.get("pipe-xel") or {}).get("reject_at")`，同时保留 `v=="reject"` 兼容旧结果文件。
- **L398/410/422**：`no extracted/`、`no main tex`、`route.reject` → `rec["status"]="reject"` → `partial` + `reject_at`（"route"）。注意 L410 `no main tex` 在 e2e.py 里就是 `reject_at="route"` 同支。
- **L486**：`"reject" if rec.get("route",{}).get("reject")` 路由列展示不变（读的是 route.reject 字段，不是 status）。
- **L562 rank dict**：`{"clean":0,"partial":1,"fail":2,"reject":3,"?":4}` 保留 `reject:3` 兼容旧文件即可；F3 后新数据不会再产出 status=reject 的 verdict。

## `bench/py/fixloop_bench.py`

- **L299**：`verdict=f"reject:inject_{e.reason}"` 是 **cell 级** verdict（引擎内部分诊枚举），F3 覆盖面外，不动。
- **L359-360 `tier_of`**：`reject:* → "reject"` 同样是 cell 枚举 tier——bench 统计层保留该档是正确做法（它统计的是 fixloop cell verdict 分布，非合成 status）；若想让报表与 F3 术语对齐可把该 tier 改名 `reject_cell`，非必须。
- L532/571/585 报表 `reject` 列同上：cell 层枚举，不动。

## 顺带 flag（#85 范围外）

`rules.yaml` tail 的 `latex209` 模式 `documentstyle|LaTeX ?2\.09` 会在 aastex 类样板注释（如 `Original \LaTeX2.09 style`）上误命中——n100 复跑中造成 3 格 `unfixable:latex209` 假阳。建议 pattern 收紧到行首 `\\documentstyle` 或要求 `!` 错同行；属 F1/F2（#84）规则面范围。
