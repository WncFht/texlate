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

- 10:47 b2-sixregress | `ab6f708` | 六篇归因全复现三证闭合→mechanisms 立账 W157-W161（inject mathgroup 一族两形态=注入时序最大单点风险；W161 关联 W06）| repro 件 tmp/lane-b2-sixregress/（REPORT.txt+repro-*.tex）| 界外需求：inject 声明下沉/normalize bbl 拆引信/xlat Cf 剥离（最便宜）+env 保真 | 关代理
- 10:47 钉转正核销：test_fuzz_v1flatten 两枚 xfail_confirmed 已拆（c9 在 W73 根集闸落地后自行拆钉，docstring 注「XPASS 转红已拆钉转正」）→ scoped 26 绿 | c14 flatten W73 根集闸实证在树（flatten.py:63-110 roots 集+is_relative_to）
- 10:56 b3 族账收齐：b3a-undefcs 49 票（d38/c10/a1；covered-pending-verify35+fix-landed10 → verify-replay 45 格在飞 run.log）| b3b-syntax 37 票（c32/a3/b1/d1；fixable34；JHEP3.cls 连炸签名→c13 缺口榜重合）| b3c-other 30 票（pipeline_introduced17/vendor_stub_gap10/version_skew2/source_latent1；already_fixed18/规则候选9→c3）| b3b/b3c 关代理，b3a 待 replay 结果
- 10:56 c9-fuzz | `85b8050` | test_fuzz_v1flatten.py 896 行（v1 _resolve/flatten_inputs 对抗探针+D1 逃逸六路钉）| 两枚 xfail_confirmed 已于 W73 落地后拆钉转正，scoped 26 绿 | 关代理
- 10:56 守护者二代：pid 2214285 已死（跟随者早夭同款命运），已 setsid+nohup 重挂 fd-hold（pgid 2317256）+ 即刻快照 xlat-orphan-1050.jsonl 987 行——孤儿 fd 仍随 pid 4023412 在写 | 教训：guardian 必须 setsid 脱管，harness 看门狗杀 shell 子进程
- 11:10 收割波-2 落账（5 commit）：ra `562f773`（xlat 序章账本八点 _ledger_call 化+TestPrologueFatalLedger 10 例）+ `899416f`（reaudit-A 四钉 share-cap/align-close/hook-glob/secrets-repr）| c12 `4521e0e`（argspec 臂 [[CMD]] 散文抠出+keyval/comma-list 双形状门，全量 6343 绿+parsebench identity 100%）| c3 `d384916`（4 规则实证点火：greek_fontenc_install/legacy_pkg_shim_c3/cs_targeted_fix_c3/xcolor_override_opt_strip，6 翻 5 哨兵零回归）| texlate-02 `3fa3bd1`（biber/biblatex skew → REJECT route=xelatex 跨引擎臂：builtin+engine token+repair/e2e/worker 全链，实证 adopted→done——tectonic 死路开新路）
- 11:10 **里程碑**：c2 `31c432e` dollar 族收口——孤 \$\$/孤 \$/\\\$ 三形归 [[CMD]] 单项保真（v2 row17 同规），parsebench-v3-c2dollar **leak 0/136049（0.040%→0.000%）identity 1955/1955**；tricky-dollar.tex D01-D10 钉 + bench_regression 37→61 断言 | C2 目标达成，门②leak 读数归零
- 11:10 归因澄清：scanner.py=c2 在飞件（已收）；engine/builtins/10-taxonomy/80-bib/repair/e2e/server-worker-compile=texlate-02 跨引擎簇（其主动按约定知会，128 测绿实证）；四孤儿件全销账
- 11:10 解封派单：L2→c1（route-shadowed 专长续道）/ L3→ra（earmarked）/ L5→c2（dollar 邻面续道）/ L8→c12（args.py 同文件续道）/ L10→c3（rules 引擎续道+b3 工单汇流）/ L7+L9 新发车

## selfimp-qual 环（texlate-d9，2026-09-18 午启动）

- 启动：用户 /goal 派本环做翻译质量「评估→改进」闭环。与 compile 侧 selfimp（texlate-5d）互补；已照会 texlate-80（其 09:11 qualbench 协议面由本环接管）与 texlate-5d。
- **文件归属登记**（lane → 互斥文件）：leader → `bench/py/qualbench.py`（ESA 改造 proto-core/prompt/route/records 四合一）；sample → `bench/py/qualsample.py`；stats → `bench/py/qualstats.py`；anchor → `bench/py/qualanchor.py`；freeze → `bench/py/qualfreeze.py`；proto-test → `tests/test_qualbench_esa.py`；proto-probe → `tmp/exp/esa_probe*`；skel-curate → `docs/research/selfimp-skeleton.md`；triangulate → `tmp/lane-triangulate/`。qualbench.py 协议规格 = xlat-quality-eval-2026-09-18 §7（ESA 两步单发 stated100 主分 + derived100 自洽校验 + swe-2-max 主裁/swe-2-high 二裁）。
- 协议内一处补全：类目表加 `accuracy-mistranslation`（eval §7 映射漏列——六 flag 无「在译但错」收容位，probe 的 MQM_SYSTEM 本有；不补则错译被迫塞 omission/addition 扭曲类目表）。flags 派生新增 mistranslation/fluency_register 两值。
- 11:35 收割波-3 落账（4 commit）：c14 `cf582ff`（v1 flatten `_resolve` openin_any 等价闸——real path 根集约束，`..`/绝对/根内 symlink 出界按 miss 永不进 read_bytes，与 v2 `_resolve_input` 同口径；W104 cs 文件名滤除同臂）+ `db3d4a1`（test_flatten_boundary.py 293 行五机制契约钉，28 绿）| texlate-02 `8672d22`（biber skew 测试件补收，属其 3fa3bd1 簇漏网）| c13 `498ae9e`（vendor 157 files + mn.cls stub，records 去重频次序——pstricks 全家桶/revtex4-2/llncs/kluwer/quantumarticle/siunitx 等）
- 11:35 b3a 终局：verify-replay 74/74 格零 dirty——66 clean + 8 partial（7×best_effort_pdf revtex209/natbib 点火后 best-effort 出 PDF + 1×fixloop:clean 但 compile 臂 partial）| 工单残留移交 L10/L2 | 关代理（b3 三族归因簇全闭）
- 11:35 关代理×4：b3a-undefcs / a3-mechtags / c14-flatten / c13-vendor / c7-server——交付物全落盘或入账，roster 16
- 11:35 nightwatch 常驻化：archbox 无 crontab → setsid 脱管 10min 循环 pgid 2472632（`nightwatch.py --save` → bench/results/nightwatch/cron.log），跨会话存活
- 11:35 派单补位回 18：l1-verify（L1 verify-flip 15 机制——规则已落待钉测翻格，只写 tests/ 新文件+fixtures add-only）+ l11-vendor（L11 残靶 9 件 ~300 篇：revtex.cls×167/mn2e×42/aa×33/JHEP3×14/aaspp4×12/svjour×9/aipproc×8/aasms4×8/JHEP，全 stub 形态）
- 11:35 c7 裁决备忘三问挂用户队列：TTL 默认/conc ceiling/SSE 聚合/settings.concurrency 死键接线——备忘在 tmp/lane-c7-server/decision-memo.md
- 11:40 c8-normalize | `0092fe4`+`5d396c5` | L6 ENC 落地：W91 `\-` 折行连字符还原（双 lookbehind + tabbing 豁免，normalize_engine 全引擎段）+ 顺手真 bug `_score_text` 大写重音罚分（mac_roman ‡ 彩票压 latin-1 à mojibake）+ 13 钉新文件 | scoped 406 + 全量 6381 绿；hep-th/9910234 17 处实证零误伤 | 界外：W72→ROUTE/vendor、W42 har2nat 已随 c13 落地、mixed 彩票记账不追 | 关代理
- 11:40 跨会话：texlate-d9 新环 selfimp-qual（翻译质量 ESA 评估→改进）照会——车道 bench/py/qualbench.py+qual{sample,stats,anchor,freeze}.py+test_qualbench_esa.py+tmp/exp/esa_probe*，台账共用 overseer-selfimp.md append-only | 已复：与 texlate-80 qualbench judge 协议面归属重合建议互通；a2 旧 judge 批已结产出可对照
- 11:45 a2-qualbench 交付：qualbench-selfimp 基线 **600 chunks/60 papers mean 4.84/5**（5:531 4:52 3:9 2:5 1:3）| **头号缺陷 untranslated_spans×21**（占全 flag 半，caption kind 最密 11/21）| 产出 bench/results/qualbench-selfimp-2026-09-18/{records.jsonl 462KB, report.md 最差30格, layers.md} | 关代理
- 11:45 派单回 18：q1-untranslated（头号缺陷机制猎捕——xlat skip 路径/模型回英文/opaque 吞噬/caption 特异，只读归因+mechanisms 立账）+ r2-residual（b3 孤儿三件：texlog nonletter payload 边界/stale-stub 指纹面/math_env_alias_cs 立账，全只读）
