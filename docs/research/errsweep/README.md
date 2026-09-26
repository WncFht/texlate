# `errsweep/` — 错误清扫报告索引

每日 errsweep agent 的工作报告归档位。agent 由 `scripts/errsweep.sh` 定时唤起，按 `docs/dev/errsweep-runbook.md` 契约工作：双臂（soak records + web 任务库）签名普查 → ≤5 签名分诊 → fixloop 规则/builtin/产品修复 → 三门验收 → 本目录落 `<date>-sweep.md` 报告（同份复制到 XDG state 根）。

| 文件                  | 内容                                                                                                |
| --------------------- | --------------------------------------------------------------------------------------------------- |
| `2026-09-20-sweep.md` | 首份 sweep 报告（clobber 类根修 + era 面补齐）——实体在 `errsweep/2026-09-20` 分支待人工合入，见下注 |
| `2026-09-22-sweep.md` | l0 名单块双闸豁免——实体在 `errsweep/2026-09-22` 分支待人工合入                                      |
| _后续报告_            | `<date>-sweep.md` → 当日处置摘要，合入后在此登记                                                    |

注：报告先落 `errsweep/<date>` 分支、经人工评审后合入本目录（runbook §2 以 `git branch -a 'errsweep/*'` 发现，merge/cherry-pick 是人工步骤）。截至 2026-09-26 分支面：`errsweep/2026-09-20`、`errsweep/2026-09-22` 各持一份待合入报告；`errsweep/2026-09-19` 只含 fixloop 修复提交（无报告件，基线在文档库重建前）。读最新报告请先查分支。
