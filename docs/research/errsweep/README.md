# `errsweep/` — 错误清扫报告索引

每日 errsweep agent 的工作报告归档位。agent 由 `scripts/errsweep.sh` 定时唤起，按 `docs/dev/errsweep-runbook.md` 契约工作：双臂（soak records + web 任务库）签名普查 → ≤5 签名分诊 → fixloop 规则/builtin/产品修复 → 三门验收 → 本目录落 `<date>-sweep.md` 报告（同份复制到 XDG state 根）。

| 文件 | 内容 |
| --- | --- |
| _尚无报告_ | 首份 sweep 报告入库后在此登记（`<date>-sweep.md` → 当日处置摘要） |
