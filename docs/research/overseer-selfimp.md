# overseer-selfimp 台账（append-only）

> selfimp 常驻环编排台账。leader=texlate-5d（archbox 本机）。每条一行事实：时间/车道/动作/证据指针。车道交付物在 `tmp/lane-<slug>/`，落账指 mechanisms.jsonl + rules/ + skeleton。

## 2026-09-18 环启动

- 09:10 基线口径复核：mechanisms.jsonl 210 条（covered 68 / partial 134 / implemented 8）；loop1 records 69535 行 5124 格 scorecard pdf 97.89% clean 84.99%；leak 0.040%（dollar 族 57 条残留）。
- 09:10 rt1 批（pid 4023412, xlat real arm, core+booster+hot）仍活：records 02:07 后无整篇 append 但 work/{id}/xlat-real.jsonl 09:10 仍在写——chunk 流式推进中，未 stall；nightwatch lane 接管监控。
- 09:11 跨会话边界（texlate-80 确认）：bench/py/qualbench.py judge 协议面归 texlate-80（GEMBA-MQM 化在飞）——selfimp A2 只做执行层跑批，不改 qualbench.py。texlate-37 已离线，其在飞 lane（revtex-209/o2-opaque-prose/early-eof-tax/gullet-at-scout）按未落地处理，冻结面：segmenter/args.py、builtins*.py、_builtins_shim.py（待核实死活后解冻）。
- 09:12 wave-1 发车 23 lane：A1-A5 测量面 / B1 mock 基线批 + B2 六篇回归 + B3a/b/c C-bucket 归因 / C1-scout partial 分族 / C2 dollar 族 / C3 fixloop 规则 / C4 术语表 / C7 server 裁决备忘 / C8 normalize 拆分 / C9 fuzz / C10 corpus expand+orphan / C11 上游挖掘 / RA reaudit-A 真bug批 / RB 单源收尾 / RD 测试钉 / RE 文档漂移。
- 冻结窗：C5(BATCH_MAX_CHARS)/C6(低分重翻) 分别待 A1/A2 落盘后发车；优化类改动在 Phase A 就绪前只允许归因/L0 钉/草案。

## 落账流水

- rb-singlesrc | `166201b` | classify_status→redacted_body 签名契约 + texlog _PS_GRAPHIC_EXTS 三集注释 | 348+218 scoped 绿；B7/B9/B10/B11 验收无改结案 | 关代理，补位 c12-probe-prose
- 09:18 冻结窗全解：37 遗产核实全落 commit（4bca3a1/d4b5a2c/b5d79c9）→ args.py/builtins*/_builtins_shim.py 可派；c2 知会 args.py 转授 c12
- 09:18 基线钉：pytest 6213 passed/4 skipped/127.3s（HEAD eafa7b5）
- 09:35 b1-baseline | loop2 批起（pgid 1767620，tmp/src-snap-loop2 冻结 6d7c4a3）：ingest 5135/parse 5122 齐、xlat mock 在跑、零报错；监控=其 cron 61ec5e51+task_ping b1-loop2；sabotage b/c 裁决=批末第二段脱管跑（已纠正勿追加在飞脚本）；估 10-14h 过夜 | 副产品：preflight mock-chain warn=探针文档过小伪 warn（bench 面待办）
- 09:38 a2-qualbench | rt1 finished 池实盘点 core734/booster116/hot37（远超 ledger 的 84 口径——state.json finished_at 口径）→ seed=20260918 分层 60 篇零补跑；judge 批 600 chunks 脱管 ~255/h ETA ~2.4h 零 judge_error | 界外需求定稿：judge 协议缺「学术腔/register」维→texlate-80
- 10:05 rd-tests | `466382c` | tests/test_latex_env_dispatch_v1arm.py（12 用例）+ test_xlat_collect_fatal.py（8 用例） | D4 实证 A1 `_ledger_call` 双档网已在树（pipeline.py:1146-1186）→ ra A1 直接核销；残余面 `_route_chunks`:1052 散文豁免裸 except 并入 ra A 批 | 关代理
- 10:05 c1-scout | 蓝图落盘 `tmp/lane-c1-scout/`（family-plan + tickets-overview + fams_final 校验 122/122） | 122 唯一机制→12 族 L1-L12 车道图；最大杠杆=vendor missing_file 877 事件 ~500 篇 | 关代理，原地接 L1 verify-flip（V 族 15 条 + stale 候选翻格，mechanisms.jsonl 行级 status 编辑，与 c10 append 互不冲突）
- 10:05 wave-1.5 发车：c13-vendor（L11 `fixloop/vendor/**` 量产，库存核对后真缺口 revtex×167/mn2e/aa/mn/tensor/llncs/JHEP3 等）+ c14-flatten（L4 `latex/flatten.py` B03/W19/W51/W73/W104——L1 identity 门高风险面，前后双跑 parsebench）
- 10:10 **事故**：nightwatch 首巡抓 rt1 `ORPHANED_FD`——pid 4023412 fd4 指向已删 `records/xlat.jsonl` inode（孤儿 953 行 vs 可见 84 行冻结于 02:07）→ 抢救：`cp /proc/fd` 快照 `tmp/lane-a5-nightwatch/xlat-orphan-1011.jsonl` + `tail --pid -f` 跟随者 pid 1978705→`xlat-orphan-follow.jsonl`；孤儿前 84 行与可见逐字节一致→批终单文件恢复即可 | 鉴证派 a5：02:07 谁换了路径 inode（gwpilot smoke→real 交接 finalize 竞态嫌疑），产出 `orphan-forensics.md`——**关乎 loop2 在飞批是否遭同暗算**
- 10:12 a5-nightwatch | `8b23ff0` | bench/py/nightwatch.py（进程面/gwpilot 队列/活跃 run 台账/task_ping 看板，25min 停滞阈，ruff clean）
- 10:12 a1-timing | `2414a43` | bench/py/stage_timing.py（产出 `bench/results/_timing/` 目录 gitignored 不落库）
- 10:12 跨会话注记：07597e2/6fc4c2b（corpus hot 166 收尾，MANIFEST.md+manifest_hot）非本舰队——peer texlate-02 推同仓，已去函校准 corpus_v3 归属（a3 manifest_hot 段待其答复）
- 10:12 工作树待收面盘点：c10 orphan 立账 append（mechanisms.jsonl +38 行 examples-resolved）/c8 normalize→transcode+shadow 拆分（_builtins_misc import 涟漪属 c8）/a4 gate_scorecard+新测试/c9 fuzz 新测试/re-docs 五文档/c2 segmenter{mainloop,pending}/a3 manifest 三件+mech_ids+mech_backfill——ra 17 任务全 completed 但 src 面零 M（疑多项核销式结案），等其报告对账

## 落账流水（收割波 10:25）

- a4-scorecard | `7e05703` | schema v3：union 注记/csb 三档 drop（post_inconsistent/csb_contradicts_fp/**window_stale**=09-17 互踩假绿直接闸）/freeze 四信号+`--require-frozen` exit3/--json v3；loop1 复跑 5124/97.89%/84.99% 分毫不差 | 回授：wave.py `_SC_PATHS` 接线 + loop2 freeze dogfood（在飞批应得 partial 证闸活）→批终做 vs 09-17 diff
- c8-normalize | `073be4c` | normalize→transcode(434)+shadow(269)，29 块字节守恒、scoped 393 绿 | 升 L6 ENC 族 7 机制（normalize/transcode/shadow+textutil/{encoding,cjk}）；界外注释指针三件记账待 L10/L5/L2 道主
- re-docs | `dcf8fdf` | E 批残余 10 项全落（wave-2A 漂移/corpus 5232/segmenter 八叶/ts-validator 判定=已落） | 关代理
- a3-mechtags | `fae6d37` | mech_tags core1000/booster200（hot166 经 peer `6fc4c2b` 捎带入库——a3 工作树编辑被其 pathspec 捕获，归属记此）+ mech_backfill/mech_ids；expand 3866 缺 tag 已问询 | coverage.txt 22 orphan 清单已喂 c10
- c10-corpus | `06bdf4b` | expand 3800→3866（fetch-ids ok64/skip2/err0，≤85 guard 合规）+ mechanisms +38 orphan 立账；同 commit 捎 c1 L1 翻格 ~12 格（append=c10/status 编辑=c1 双记） | 升 L12 EVAL 族 15 机制
- c11-upstream | `026d694` | skeleton +6 假设：c0-json-strip→ra、auto-extract-glossary 直击 C4 瓶颈、abstract-context、delim-param-args 排 c12 后、quoted-input→tables.py 待派、original-repair-carry REVIEW 级 | 续挖 xlat 质量+compile 修复面
- c7-server | 备忘 `tmp/lane-c7-server/decision-memo.md`：SSE 无服务端闸（>6=浏览器约束前端已收）/GC 键实装默认关（~23MB/篇→千篇 23GB）/`settings.concurrency` **死键**（执行面零读取，真效仅 per-task） | 三裁决点入用户队列，c7 待命实装臂
- 跨会话：texlate-02 非 corpus 两 commit 主（server 只读排障中，动手前会通气）；hot 封层实主待考（texlate-80 疑）；texlate-80 已照会 gfs stash-pop 风险（10:21 f620827 提交触发全仓 mtime 重洗，内容无损）
- a1 升 C5：BATCH_MAX_CHARS 尺寸分析（_timing 数据驱动+网关 conc4/bg120s 排队计入；草案不改 pipeline.py——ra 面在飞）
- ra-bugs 状态更正：pipeline.py 终现 M（_route_chunks 残余+A 批实修在飞）——先前「17 任务 completed 零 src」系核销式结案为主，等报告对账

