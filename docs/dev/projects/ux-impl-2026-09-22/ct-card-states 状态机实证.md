# ct-card-states spike — 结果摘要

> **结论**：卡片按钮的 idle→queued→running→done/failed 状态机可行但**有环非 DAG**（retry 终态→running 回边合法，靠「终态帧后再见 stage 帧」判新轮）；裸 done/total 百分比不可行需 band 映射——真值口径 = tasks.progress 列锚点（translating 段本地插值 25+⌊60·done/total⌋）。此稿是 cite-translate `RefTaskChip` 七态机（`citeTranslate.ts`）的判据底。
>
> **状态**：时点证据（329 任务 1,255 tick 全量回放口径）——结论已落地 cite-translate lane
> **日期**：2026-09-22

问题：卡片按钮能否用 idle→queued→running→done/failed 状态机 + chunks done/total 百分比驱动？

答：状态机可行（但有环、需要快照兜底）；裸 done/total 百分比不可行——需 band 映射。

## 数据面

- 17 个真实 texlate.db（ux-research 现场既有实验产物 + ct-status 同步在写）
- 329 任务、1255 有效 tick（stage/chunk/done 帧）全量回放
- 终态分布：done 129 / cancelled 13 / fault 9 / partial 9 / needs_auth 1 / interrupted 1 / queued 165（含从未起跑的 backlog）

## 状态机结论

观测到的相位路径（phase_paths）：

- queued→running→done ×131、queued→running→failed ×8
- **环边实测存在**：failed→running→{done|failed}（retry 新轮，7 次 rerun 全在流内）、done→running→done ×1
- queued→failed ×2：needs_auth / 排队即取消——**零 stage 帧**
- idle→done 直达：dedupe 复用行建出来就是 done（0 事件、progress=0）

即状态机不是 DAG：终态→queued/running 必须合法（retry 复用同一 task_id 与同一 append-only 事件流，无轮次标记——靠「终态帧后再见 stage 帧」判新轮，参考实现 run_id 钩子已验证 7/7 复位）。

## 进度口径结论

真值 P_col = tasks.progress 列：fetch 3→9 / parse 9→25 / translate 25+⌊60·done/total⌋→85 / compile 90→99 / done·partial 钉 100；fault/cancelled/interrupted **冻结末值**（实测 fault@3/30/85/95/99、cancelled@0/3/25/73、interrupted@3）。

裸 done/total（P_raw）在 9615s 活动墙钟上的失真：

- 29.2%（2804s）停在 0%——fetch/parse 无 chunks（fetching 段实测可占 40402s 总时长，含卡死 mock）
- 7.8%（748s）已 100% 仍在跑——编译尾 + resume 轮计数器不回零（retry 首帧 flush 即 done==total，86 次单跳 0→100）
- 时间加权 |P_raw−P_col| = 108,741 pct·s ≈ 平均每活动秒偏 11.3pt

正确口径（P_card）：running 且 stage=translating 时本地算 25+⌊60·done/total⌋（chunk 帧**不携带** progress 字段，SSE 路必须自己插值）；其它段用 stage 帧锚点；queued=0；done/partial=100；failed=冻结锚点。list/snapshot 路直接读 progress 列即可（同值）。

## 关键陷阱

1. **done 含 failed**：done 计数=已解决集（ok+fallback_orig+failed），done==total 且 failed=5 实测存在→终态 partial。done/total 不能当成功判据，failed 要单独取数做徽标。
2. **无事件终态**：14/329（4.3%）任务零/近零事件帧（dedupe-done、排队取消、needs_auth、重启 interrupted）——纯 SSE 归约永不收敛，必须经 snapshot/list/探活兜底（transport 的 probeAfterClose/列表轮询已覆盖此面）。
3. **interrupted 无 done 帧**：启动清扫直接改行，流直接死——convergeTerminal 合成路径是按钮终态的唯一来源。
4. **retry 不清 progress 列**：queued 期间残留上轮读数（如 73%）直到下一 stage 帧；且同流内 done→stage 直接续写无分隔。
5. **partial 语义**：是降级交付不是失败——按钮应归 done 相（能开 reader）+ failed_chunks 徽标；needs_auth 单独 CTA（去设置），cancelled/fault/interrupted → retry CTA。
6. **chunk 帧节奏**：translating 段内 p50=3.0s / p90=50.7s / p99=769s 突发式——进度条按帧跳变即可，勿做匀速动画假设。
7. **queue_position**：仅 status=queued 时下发（1 基，queued_rows 按 created_at,id 序），离队即缺席——按钮排队态可显示，其它态勿继承旧值（store inheritRich 同口径）。

## 复算校验（validate.py）

- 1255/1255 tick：phase ∈ 四相、pct ∈ [0,100]
- rerun 复位 7/7（终态后 stage 帧 → pct ≤25）
- snapshot 路终判与行终态一致 329/329（SSE 路 315/329——缺的 14 个全是零事件任务，印证第 2 条）
- 终态 done/partial pct==100:133/133（经 SSE 收敛的）

## 产物

ux-research 现场 spike 件（tmp 现场不入库，结论已摘要上文；归约器已移植 `reader/cite/citeTranslate.ts`）：

- replay.py — 全库流回放 + 逐 tick 三口径采样 → metrics.json / traces.json
- metrics2.py — 真值修正口径：阶段墙钟、raw 失真、节奏、队列位次 → metrics2.json
- cardbutton.py — 参考归约器（纯函数，SSE/snapshot 双入口，run_id 轮次钩）
- validate.py — 不变量断言 → validate.json
