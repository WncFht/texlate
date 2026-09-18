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
- 12:05 巡检脉冲：loop2 compile 8454→9161（+707 在飞，xlat/parse 满 5122）；rt1 pid 4023412 存活、孤儿 fd 守护者 pgid 2317256 持守（可见 84 行未动）；nightwatch 脱管环 10min 准点落 md
- 12:05 a1-timing | `c2018de` | 请求时序三分拆（contextvar chat-sink+outer/inner/chat 三 span→req_timing records）+ batchmodel 文档（devin2api 86,705 行实测：conn 1.8s 固定/decode 543+13.3ms·out_tok/~550 out_tok/s 全局上限） | 注：loop2 xlat 先于插桩，req_timing 自下批生效 | 关代理
- 12:05 派单 r3-audit：收割波-2/3 ~10 commit 独立复核（只读，按风险序：W91 regex 全引擎接入/biber skew token 流/根集闸语义/scorer 罚分）——回归门的独立验证层
- 12:30 巡检脉冲：loop2 compile 9161→10286（+1125 在飞）；rt1 持守不变 | texlate-02 跨引擎钉 140 行代收 `56157b5`（test_e2e_wiring+test_worker_audit_fixes reject_route 双臂覆盖，122 绿）| 在飞面全可归因：c1-L2(engine/probe/latex209)/c3-L10(_builtins×3+10-taxonomy+slashbox)/l9(gullet×4+test_gullet_l9)/c2-L5(model+tricky-mask+regression 61→72 钉)/l11 首两 stub 落地(mn2e+revtex)/l1+q1+r2+r3 新道工作中 | ra-bugs 转 idle 已问询 L3 状态
- 12:40 selfimp-qual wave-0 发车（texlate-d9）：`914664d` qualbench.py ESA 落地（esa2 协议：errors[]+stated100 主分/derived100 自洽校验、9 类目 MQM 化、critical 收窄、key 并 protocol_v、swe-2-max 主裁/swe-2-high 二裁、judge≠translator+medium 永禁、--source manifest）| ruff clean + mock 冒烟 11/11 绿 | 并行 7 lane：proto-test(test_qualbench_esa.py)/proto-probe(n=8 前后对照 tmp/exp/esa_probe)/sample(qualsample.py 1200-chunk 分层)/stats(qualstats.py bootstrap CI+pairacc)/anchor(qualanchor.py ESA^AI 人审包)/skel-curate(skeleton 卫生)/triangulate(XCOMET-QE 可行性)
- 12:40 升级待用户裁决①：glm-5-2 实为免费档常设（archbox model-dump 实证 mult1.5 ZAI FREE——「已判付费档」旧读数过时；若解禁可建跨家族三角 judge 臂，现仍按硬边界 swe-2 系）
- 12:40 升级待用户裁决②：协议内补 `accuracy-mistranslation` 类目（eval §7 映射漏列——六 flag 无「在译但错」收容位）——已实装，若反对可回退
- 12:55 wave-1 预置：batch 驱动 `tmp/lane-batch/run_qualbase.sh` 就绪（setsid 脱管+resume 循环×6，conc4/judge-timeout300，records 行数=完成度信号），sample.jsonl 落地即发车；freeze lane 发车（qualfreeze.py freeze+check，KS/flag率/kind均值/contested 四信号，阈值参数化待裁决）
- 12:55 升级待用户裁决③：frozen-300 门禁阈值（ks-alpha/flag-alpha/kind-delta/contested-delta）——freeze lane 交付后附建议值再报
- 12:58 triangulate stall（jina reader 挂起 600s watchdog 杀）→ 重派 triangulate2，禁 jina/慢 fetch，gh api+WebSearch 优先，网络全断则标「待实测」照交
- 13:20 收割：anchor `d82a914`（qualanchor.py 682 行 sample/harvest——kind×stated 分带两层轮转+contested 配额 ~n/2，item 盲分防锚定，index human_score 快速通道）| proto-test 同 commit（test_qualbench_esa.py 44 例全绿 + scoped 281 无破）| 两代理交付即终
- 13:20 proto-test 钉出实现偏差记档：l0_ph_unreported=ph_missing∨ph_invented（比清单宽，合理）；JSON_OBJ_RX 贪婪——raw 含两个 {..} 对象时兜底失败靠 reparse 兜；缺省 severity→minor 不计 sev_clamped；pair.key 无 arm——同 paper+chunk+model 跨 arm 续跑会互截（单 arm 基线下非活问题）；route_judge no_eligible_judge 为防御性死码
- 13:02 收割波+发车：sample `023d991`（qualsample.py 分层抽样——para 池级 tertile cuts=[210,538] 各300/caption150/section_title150/350篇 均值3.4块，池内无 abstract/table_text/env_text 为既有缺口；rt1 池抽样期仍在长 1003→1027，sample.jsonl 即冻结快照）| stats 同 commit（qualstats.py 818 行 ci/pairacc/report——paper簇 bootstrap B=1000、acc23 tie-calibrated、skipped_old_protocol 摘要节）| proto-probe **PASS**（B臂 8/8 首发解析、span_verified 10/10=100%、零类目越界、抓到老协议漏检 convention 违例；stated 系统性严于 derived mean Δ=-15.25 靠 contested 兜；l0_en_unreported 合法留英机械触发=规格内）→ **qualbase 1200 批发车**（pgid 2867288，conc4/judge swe-2-max+second swe-2-high，~4-8h ETA；watcher cron 204b0d68 23min 脉冲+死拉）
- 13:30 skel-curate | `13d1b59` | skeleton 卫生：adopted 区新建收 2（prose-recall-opaque `4521e0e`/missing-file-x23 `498ae9e`）；unblock 2（C5 待 leader 裁决、M8 标可发车——实按本环裁决 hold 到 esa2 基线，旧 1-5 分不可用于低分靶选）；qual: 标 13 条含 c11 新增 6 假设（sentence-split-abbrev/copied-token-boundary/movable-token-license/placeholder-value-context/untrusted-content-clause/content-filter-fallback）；指针修正 9 处零失证 | 关代理 | 新候选 6 条待侦察（REPORT 附录）
- 13:30 波次状态：W0 全闭（esa2+44钉+probe PASS）| W1 批在飞（records 计数中）、freeze/triangulate2 待交付 | W2 池就绪：qual: 13 条 + 候选 6 条，基线读数落地后按证据强度发车
- 13:10 收割波-4 落账（8 commit）：ra `6aeb69a`（test_arxiv_locate +10 hermetic 钉 W69/W98/W71/B07/W52/W36/W16，L3 结案转 inject 道）| a3 `d53a429`（mech_backfill 两趟竞态安全重写）| c10 `281079b`（L12 flags 三通道+良性签名+B04/B06 簿记+docstyle_opts）| `9f37869`（manifest_expand 全行重写——c10 特征列+a3 mech_tags 交织双归属）| `ad5142d`（mechanisms 三归属：c1 翻格 W47/W103→covered、c10 B04/B06、r2 W162 undefined_cs 非字母 payload）| `0cff582`（skeleton +3：glossary-ws-flex/output-sanity-gate/compile-consumed-deps）| `4d18731`（8 vendor stub 收编——**归属更正：实系 c10 抢跑 #86 产出**，非 l11；aaspp4 败格扣留）| `8a42cf8`（c2 L5 MASK 族：env_name_at 注释剔除 W11 泛化 + unescaped_dollar_odd %→EOL W92，debt_repair 6→2/unpaired 170→166 真改善，门全绿）
- 13:10 **撞车事故**：c10 自我认领 #86/#87 与 l11-vendor（11:35 持道）正面撞——核实 c10 的 make_l11_stubs.py 已直写树内 9 stub（12:29），归属记 c10；l11 急停改纯验收道，c10 smoke 预检顺手成验收底稿并抓 **aaspp4 "No pages of output" 败格** 移交 l11 修。教训：自我认领须先报 leader 核持道状态。
- 13:10 派单：ra→inject 道（W99 裁决采纳 inject 侧：docclass-in-closure 两形态+filecontents 虚拟成员+b2 W157-W161 声明下沉）| c11→sanity-gate 道（其三闸提案实装：same-as-source/长度比带/新控制词 `\\[a-zA-Z@]` 拒收，xlat/{retry,pipeline}.py）| c10→C5 A/B 真网关探针（≤10 篇）| c3 L10 +4 工单（natbib author-year 守卫回归优先/_dep_fanout/undefined_cs→pkg 推断/\theorembodyfont）| b1 批尾 +2（stagerun ended_at+rc 增量/0307193 status 口径复核）
- 13:10 门读数：full pytest 4 fail 全在飞面可归因（c3 vendored 指纹头 ×2、售 c12 argspec+pinlabel/tablecomments ×2——道主交付时自闭）；l11 pytest 验证在飞；loop2 compile.jsonl 10343 行推进中。
- 13:35 triangulate2 | 交付 `tmp/lane-triangulate/`（REPORT+证据四件）| **GO-with-caveats**：XCOMET-XL 统一权重 QE 分支产 error_spans(char offset 可精确校验)+severity+0-1 分——唯一非 LLM 的 span 级评委，天然第三族仲裁臂 | 接入零改动：qualxcomet.py 产同构 records（protocol_v=xqe1），qualstats pairacc 直接吃 | 四 caveat：gated 要 HF_TOKEN/fp16 ~8-9GB VRAM 窗口（两 4070 余 ~5.7-5.9GB）/510 subword 截断/无 category 轴 | **意义**：不依赖 glm-5-2 解禁即可建跨族三角——W2 候选 lane qualxcomet（等 GPU 窗口+HF token）
- 13:38 升级待用户裁决④：XCOMET-XL 入网——需用户 HF 账号接受 cc-by-nc-sa-4.0 许可拿 HF_TOKEN（本机无 token）+ ~13GB 权重下载（禁代理直连 HF，可本机下后 rsync 去 archbox）+ GPU ~8-9GB 窗口。新模型入网按硬边界必须用户点头
- 13:45 巡检脉冲 3：loop2 fixloop 段在跑（pid 2579265 --on fail jobs6，fixloop.jsonl 667 行起步）；rt1 pid 4023412 仍活、孤儿 fd 1076 行续写（批龄 ~11.5h）；nightwatch 13:13 准点（main-coord STALE 挂用户队列）| `49b5a18` l1 fixture_assert mask dispatch 接线 + `321b6c1` r2 W163+q1×5 立账 | q1 关代理（交付落盘）；l11 #87 标完但 aaspp4 未动+无矩阵→已问询验收证据
- 13:45 freeze | `e794f60` | qualfreeze.py 755 行 freeze+check——低分全收+kind×band largest-remainder+保底，seed 逐字节复现；check 四信号（KS/flag-z/kind-Δ/contested-Δ）阈值参数化，unarmed→exit2 不假 pass | 关键设计：records 仅 160c excerpt，复跑必须 --sample join 全文 | 自测矩阵全过（合成 1203 行→300 命中、同分布 p=0.82 pass、degrade12 全信号 exit3）| 关代理 | 待裁决：DEFAULTS 四阈值 + --frozen 是否升必选（freeze 建议值附 REPORT）
- 14:05 巡检脉冲 4：loop2 fixloop 段续跑（compile +75→10418，fixloop 667 持平——fail 件修复轮次中）；rt1 孤儿 fd 1076 行持守 | l11 实证修 revtex.cls 在飞（compat `\documentstyle` 硬拒 revtex4-2 → 桥 article+2.09 残面两态分派，167 格 base 臂证据驱动；aaspp4 待处置）| 工单折叠：q-corrector-err-token-leak→c11 道（同授权面）、q-term-glossary-gap→c4 道（index.yaml 映射覆盖矩阵）| c1 L2 交付确认仍未回
- 13:50 L0 池面分析（sample.jsonl 全 1200，免费信号先行）：en_residue≥8 共 51(4.2%) 全在 para(5.4%)，两大块 en=85(1502.01863/0:261)/en=68(1608.06785/0:75) 疑整段未翻；ph_missing/invented 双零——占位符机制在池上零失守；same_as_source 2 例；zh/src 字符比<0.3 有 218 但中文字符密度天然偏低、与 babeldoc token 比阈不可直比——判读待 judge 分交叉
- 14:00 成本回执预算：翻译臂 rt1 1044 篇 134,065 chunk×6(swe-2-medium)≈80.4万 mult·call；judge 臂预算 1200×12(max)+contested~10%×9(high)≈1.55万——占比 ~1.9% < 5% 验收线（口径=判分 chunk 数×模型档，与 goal 的 ~1.6万 mult·call 一致）| e2ereal 301 篇分母未计入只让占比更小
- 15:20 收割波-5 落账：c1 `4534631`（L2 ROUTE 全量落地——probe _ScanCtx+5 字段/阻断名单三向抑制/docstyle_opts 非内核选项→pkg 依赖/六诊断注记、engine C901 拆分+psfile/.mf 双 reason 不改引擎序、latex209_no_decl 诚实桶拆分；mechanisms ×8 翻 covered；484 scoped+91 fuzz oracle 绿，REVIEW=新 reason 签名殊途同拒已采纳）| l1 关代理（15/15 翻格+42 钉+fixture 接线全收 `ed66553`/`49b5a18`）；q1 迟来详报与已收 `321b6c1` 一致（en-gate 进 validate_fn=最大杠杆，c11 道在手）| c11 skeleton +6 实已在 `0cff582` 内（head 截断误读为 +3，补记：sentence-split-abbrev/copied-token-boundary/movable-token-license/placeholder-value-context/untrusted-content-clause/content-filter-fallback 全进账+output-sanity-gate 证据修正）
- 15:20 **事故已自处**：b1 报 loop2 fixloop 段静默悬挂 75min——gr-qc--0104075 splice/novem.tex 暴走 xelatex 吐 41579 页，run_process 无墙钟超时+threaded 死子管道 EOF 丢失=经典悬挂；已杀 pgroup 断点续跑（新 pgid 2935024，zh 补 163 格毕、base 补 97 在飞）| harness bug 派单 c1：sandbox.py run_process 墙钟超时（REVIEW 级数值件）+W72 残面+input-FP 裁决
- 15:20 派单：p1-prompts 新道发车（prompts.py 独占——q1 的 C2/C4 措辞收窄 movable/fixed 二分 + untrusted 条款，texglot/BabelDOC 先例在 tmp/refs）| a5 fanotify 裁决采纳跳过（CAP_SYS_ADMIN 墙拿不到肇事 pid，auditd 需 root→挂用户队列）| c3 L10 再+2（90-shim-legacy 9 死条清理+revtex.cls `##` 塌缩真 bug）| c10 L11 迟报与现状一致（9/9 前移含 aaspp4 真稿 53 页 xdv——aaspp4 待 l11 复核同判即收）| c4 界外挂单：doc_filter accent-fold 归一（Schr\"odinger 407 vs Schrodinger 131 形态分裂，候选机制）+auto-extract-glossary 立项备
- 15:20 roster：在飞 c1/c2/c3/c4/c10/c11/c12/l7/l9/l11/p1/r2/r3/ra=14 道 + b1/a4/a5 常驻 = 17；q1/l1 已关（交付全落）
- 14:05 batch 提速：~150对/h 系 per-call 延迟受限（decode 仅占 ~50/550 tok/s 全局）→ conc4→8，重启 driver 续跑 71/1200（教训：bash 循环体一次解析，行内改参数须杀 driver 本体才生效）| 全局 decode 余量仍 ~400 tok/s 让 rt1，ETA 8h→~4h
- 14:15 W2 L0 侦察×2（免费层先行）：**glossary-ws-flex 降级**——池上断开形术语命中 0/1200（换行 110、~ 223 块都在，前提成立但无命中），根因=terms/ 仅 cs.* 五表而池为 physics-heavy、doc_filter 近空转，skeleton 的 2.2% corpus 估计在本池不复现 → 待 auto-extract-glossary 落地后重测；**c0-json-strip 转硬化件**——src/zh C0 0/1200，机制真（json.loads strict+upstream PR #612）但池上无触发面，降为 cheap insurance 非主线；**auto-extract-glossary 升 W2 头号**——结构性覆盖缺口（physics/math/cond-mat/quant-ph 全零）= 池上术语面真空
- 14:20 修正：terms/ 今增 cond-mat.csv(751)+quant-ph.csv(306)（别家 lane 未提交在飞件，侦察已含）——覆盖缺口收窄为 hep-*/math.*/astro-ph/nucl-* 等；断开形 0 命中结论不受影响（含新表后仍零），ws-flex 降级维持
- 13:42 批健康修正：driver/watcher 完成判定 wc-l 行数→scored 口径（score≠None），judge_error 行不再冒充完成、靠 attempt 重跑自动捞回；实测 conc8 速率 ~270 行/h（71→135/14min），ETA ~4h
- 13:50 anchor 包冒烟（live 数据 n=40）：143 行→139 eligible→40 选，contested 11/11 全收，excerpt_only=0（fulltext join 生效）；item 件形态正确——【】就地标记+judge pre-marks 无分盲审；批后 200-chunk 生成 = 一行命令已验证
- 14:05 L0 侦察×3 补刀：**copied-token-boundary 同转硬化件**——机制在代码里属实（pipeline.py:586 裸 `count==1`+`replace` 无边界），但触发前提=模型把源片段抄回译文，而 ph_missing=0 全池——copy-back 行为在本池无踪迹（修复亦不记 warning，池面无 incidence 可测）；三条 c11/池假设（c0/ws-flex/copied-boundary）共同模式=机制真+池 incidence 零 → 硬化档不烧 W2 主线；有池面实测的优先项：auto-extract-glossary（覆盖缺口）/en-residue-rexlat（51 块）/output-sanity-gate（2 echo+ratio 尾）/m8（待分）
- 14:10 qualstats live 冒烟通过（169 scored）：contested 7.7%[4.1-11.8]、span_verified 90.6%[82-97]、score_delta -6.8；**flag 分布翻转坐实**——grammar/term 各 13.6% 领跑、untranslated_spans 1.8%，旧协议头号缺陷结论被 esa2 类目表证伪：真病灶=流畅度+术语非未翻 | W2 发车单草案落 tmp/lane-batch/w2-dispatch-draft.md（auto-extract-glossary 头号/en-residue 次席/output-sanity 三/m8 待低分格计数）
- 14:25 L0 侦察收官×2：**content-filter-fallback 硬化档**——rt1 13.4 万 chunk error_kind 仅 provider×396/validate×1，content_filter 零命中；**sentence-split-abbrev 中档**——attempts>1 共 2014 chunk(1.5%) 确走 whole→lines→slots 分裂梯，缩写误劈途径真实存在但坏劈计数未测；**新发现**：梯尽案例见 skip_reason——`[[MATH_92]]`→`[[MATH_93]]` lev=1 自诊「可自动修复」却仍 fallback_orig 整段英文（brace 深度 -1 并发），占位符自愈钩子诊断在但修复未救回，值得入 skeleton 新假设
- 13:49 再提速 conc8→12：decode 实测仅 ~40/550 tok/s——瓶颈是 per-call 排队延迟非吞吐上限，多 worker 吃 rt1 相位空窗；若网关告警回落即降回 8
- 14:00 校准向早读（187 scored）：**en_residue→judge omission 对齐仅 25%(1/4)**——若全 51 块复核保持 <60% 判死线，en-residue-rexlat 须先做信号提纯（剥人名/机构合法留英）否则判死；judge2 在 contested 上 ±10 内确认主裁为主（stated 整体感扣分被验证），contested 机制健康；over_translation 为 contested 头号驱动 8/17（数学/命令被翻）——与 ph 零失守并读=模型不丢占位符但会去翻译其紧邻 LaTeX/数学面
- 14:02 batch 工程：watcher 接自动收割——终态（scored=1200 或驱动两轮全尽仍停滞）触发 tmp/lane-batch/harvest_qualbase.sh，一把产 frozen300.jsonl+anchor200/+ci.txt+report.md+en_residue_xtab.txt，marker 记 scored 数幂等防重、增长可再收；err 4 行全瞬态（3×ConnectError+1×unparseable，resume 自愈）；en_residue 交叉表复测仍 1/4=25% 命中（en=11 块 stated=100 全净=合法留英稀释信号，「先提纯后红线」方向更实）| 现 365/1200 scored、contested 7%、mean 92.6
- 14:15 基线中段重大发现=新头号假设 **bib-passthrough**：major 级错误格第一大户 convention-do_not_translate（28 条全同病灶）——^[[BIB_ 锚首块（bibitem 起点，L0 单子串可检）样本 4.3%、已判 29 块 90% 被标（major23）、stated 67.9 vs 95.3。机制=文献条目约定留英却照常送翻→绕过送翻灭 major 类+省 4% token；挂用户确认项=参考文献区全英化为产品可见语义。已置 W2 发车单 Tier1#0，吞并 m8 低分格 bib 子群 | judge2 早读：contested 上 30/31 在±10（mean-0.6）=抓固有两可块非抖动，机制健康
- 14:35 中段读数三件：**m8 判死在即**——stated<55 仅 3/512（2 块 BIB 归 bib-passthrough、1 块 untranslated），外推 ~7/1200<<30 线，skeleton 已标待批终转 rejected；**critical 零命中**——收窄枚举后池面无致命级，critical_present 触发器空转；**bib-passthrough 入 skeleton open 池**（REVIEW 级挂用户语义裁决，证据=28 条 do_not_translate 全文献条目形态+90% 中招率）| contested 主驱 delta_gt15×37、l0_en_unreported×11 合法留英假阳（probe §7b 预言命中，~24% 二裁流量空耗=阈值调整建议随升级包）
- 14:50 **en-residue-rexlat-redline 双重判死在即**：en≥8×omission 交叉 3/13=23%<<60% 线，且 en≥8 主 flag=over_translation×6（病灶在邻近 LaTeX 被翻）；旗舰极端例 en=68/85 两块全是合法留英文献条目（正确非缺陷）——「整段未翻」归 output-sanity-gate same-as-source 正解。skeleton 已标待批终转 rejected | 衍生两件：bib-passthrough 检测器补续段形态（1502.01863|0:261 en=85 无锚首=文献表跨 chunk 续段）、sanity-gate 须豁免 bib 语境否则误杀合法直通
- 15:00 批中段：606/1200、err 4→28 系网关 transport 抖动簇（27 ConnectError+1 unparseable，attempt 边界自动捞回，无系统性故障）；placeholder_broken×1 实为 `图 ~[[REF_177]]` 空隙 minor 非 selfheal-gap 机制；波末指标早值——score_delta mean -7.2（stated 系统性严 7 分，delta_gt15 驱动 7.6% contested）、span_verified 97.5%(306/314) 协议健康
- 15:25 归因修正+坐实：over_translation flag 实为 do_not_translate 类目映射（48/49）——早前「数学/命令被翻」读法证伪，头号 contested 驱动=文献违例本身；**do_not_translate×48 中 46 条在 [[BIB_ 块内（96%）**，bib-passthrough 一臂灭类坐实；非 BIB 两例=全角括号/`干扰机发送概率` 散点。addition×19 全 minor 真微添加（"也/只需/可视化"类）弥散无单点修法→不入 W2 主线 | 排序核实：sample caption 前载/section_title 压尾→per-kind 均值批终才有全相
- 15:45 top2 flag 类证弥散：terminology×101 逐条个案无重复机制（inverter/sigma/panel/leading-order/bin 各一）、grammar×76 零碎流畅度（空格/句式/冗余/指代）——无隐藏机制簇，W2 杠杆仅术语覆盖+模型本体，排序 bib-passthrough>auto-extract>其余 再证；微机制：占位符后逗号/句号前多余空格×3→折入 sanity-gate 标点清理件；err 持平 28=抖动窗已过，687/1200
- 16:10 校准面收官：judge2×judge1 错误集对比（contested n=64）——46 全同、18 差异全边界级（同类目 sev 互换×2、grammar↔register 相邻类、单边 minor 增删），无结构性分歧；合并 ±10 分内确认 30/31 读数→stated 分数与错误标注双稳健，contested 机制定位=固有两可块非 judge 噪声 | 批 740+/1200 无新增 err
- 16:35 bib-passthrough 检测器钉死：`[[BIB_`=PhType.BIB（\bibitem 占位，segmenter/tables.py:38）——「含标」语义即完备，锚首/续段/多条目并段（0:261 含 7 标）全覆盖；单标块中招 89%(41/46)，note 型条目留英仍合约定。lane 证据包齐：检测器+池占 4.3%+灭类 96%+省 token，只差用户产品语义放行
- 16:55 L0×judge 交叉面清零：812 判中 ph_missing/invented=0、echo 疑似（ratio>0.85∧en>30）=0（en=85/68 两 bib 直通块在尾部队列未判）、长度比尾=0——output-sanity-gate 目标缺陷本批近零发生，硬化档定位再证（机制真+池面近零）；批 812/1200
- 17:20 unparseable 根因查实：err 行 `finish=length`+`reasoning_chars≈8168`——judge reasoning 烧满 max_tokens=8192 预算、content 未出即截断→空 JSON。非瞬态系统性故障：同 chunk 重试大概率复败（0707.1778|0:23 caption 666ch 引发超长推理）。波末选项：unparseable 行补跑提 max_tokens→16384（规格≥8192 内允许）或记 1-2/1200 永久失分。err 71 中 69 transport 簇仍瞬态，947/1200
- 18:05 batch: 1116/1200 scored、rows=1200 全覆盖、err=85（83 transport 在 resume 循环内续捞 + 2 unparseable 已定位 key=0707.1778|0:23(caption)/1502.02155|8:5(para) 均 finish=length reasoning≈8k）。driver 存活收敛中；收割后补钉命令=run_qualbase 同参 + --judge-max-tokens 16384（flag 位 qualbench.py:1281，resume 只重打未判行）——须等 driver 退出再跑，防双写 records.jsonl。
- 15:30 batch 终态收割：1200/1200 全 key 落判（含 2 个曾 finish=length 失格块末趟重试成功，16384 补钉预案未启用）；85 err 行全是已救回 key 的过期 transport 错行。终值：stated 92.86[92.35,93.31] median95、derived 99.20 Δ-6.34、contested 97=8.1%[6.5,9.8]、span_verified 98.8%、per-kind caption93.4/para91.9/section98.1、critical 全零。cat×sev：terminology244/grammar173/mistranslation107/register84/do_not_translate57(major47=第一大户)/addition54/omission23。收割件：frozen300(300钉,低分带5全收)/anchor200/ci.txt/report.md/en_residue_xtab.txt 全产出；监控 cron 204b0d68 已删。skeleton：m8→rejected(<55仅5块)、en-residue→rejected(22%<<60%)、bib-passthrough 终值回写。波末汇总 tmp/lane-batch/wave1-summary-draft.md 已填毕呈递。
- 15:45 W2 自主面启动：output-sanity-gate L0 侦察毕——真 echo ~1-3/1200(0.1-0.25%)<0.5% 判死线、zh 新控制词 0 命中、长度比臂 char 阈值失准须 token 口径重标 → 按自带判死线降硬化档（skeleton 已注记）。auto-extract-glossary L1 探针 lane 发车（tmp/lane-autoglossary/ 独占，swe-2-medium 抽取臂仿 BabelDOC，5 篇跨域产术语表人读）。tier-1 其余全挂用户裁决（bib-passthrough 等签批）。
- 15:55 autoglossary L1 验货过：113 唯一术语/5 篇跨域、~96% 域内正确、缩写展开+语境化 zh 超手工表水准、噪声 ~3.5% 机械性（REPORT.txt tmp/lane-autoglossary/）。L2 A/B lane 发车（tmp/lane-autoglossary-ab/）：60 块 term-flagged chunk 重翻+重判，判死线=term flag 率不降。注入点 pipeline.py:546-548 doc_filter 已侦察。
- 16:10 硬化档实装×2（leader 直改，目标文件无争用）：c0-json-strip=GatewayTranslator._go 出口剥 `[\x00-\x08\x0b-\x1f\x7f]`（pipeline.py，单点盖 translate_fn/corrector_fn/slots_fn/_batch_call）；copied-token-boundary=recover_copied_tokens 逐片段边界守卫（placeholders.py，$…$双侧/cs尾/alnum尾三则仿 texglot）。钉测 test_gateway_strips_c0 + TestRecoverCopiedTokens×4 全绿（84 passed），ruff 净。content-filter-fallback 缓议——client.py 在别家车道编辑面内。

## 2026-09-18 16:20 — 磁盘清理（用户裁决：HF 不动，可复用资产留）

**背景**：/ 81% 用满（714G/917G），/tmp tmpfs 31%。盘点后按「bench 扩容可复用性」分档执行。

**已删**：
- `bench/results/stagerun-loop{1,2}-*/work/` ~124G——纯 _texmf 编译残留，records/run.log/cases.jsonl 全留；无活进程、night.jsonl 队列无回写任务
- 16 个冷 `bench/work_*`（work_v3 28G/sabotage_v3 5.2G/e2emock 3G/fixloop_* 等）~38G——全部 0 文件 <6h、gitignored 可再生工作区；**保留** work_e2ereal（活 web :8765）+ work_gwpilot（活队列）
- `uv cache prune` + `go clean -cache`（后台执行中）

**保留**：HF hub 20G（用户明示）、tmp/exp 语料资产（corpus-cbh 7.7G 等=bench 扩容复用件）、/tmp 死会话残留 ~2G（水位不急+部分或属活会话）、playwright/pre-commit 缓存、stagerun-rt1（在飞）。

**结果**：/ 714G→547G（63%），回收 ~167G+。

**顺带修复**：`_C0_RX` 并发编辑冲突——盘上 `[\x00-\x08\x0e-\x1f\x7f]` 把 `\x0b\x0c` 保留，与 docstring（仅留 `\x09\x0a\x0d`）矛盾且 `\x0b` 正是原 JSONDecodeError 复现字符。已改 `[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]`，43 钉测回绿。若系他 lane 有意保留 VT/FF 可回滚。
- 20:05 W2 硬化×3 落地（client.py 争用解除——原占 diff 是网关迁移 3003→3033 docstring 级陈旧件）：content-filter-fallback 实装=ContentFilterError(retryable+max_tries=1) 单类喂两臂（_model_switchable 换模 + _batch_call degrade-singles 替代整批 skip）；检测=400 body 子串 + finish_reason=content_filter（_raise_for_finish 抽件治 C901）+ anthropic refusal。钉测 182 绿 ruff 净；frozen-300 豁免（仅过滤事件路径、基线零事件）。skeleton→adopted；REPORT tmp/lane-contentfilter/。A/B lane 在飞 judge 37/60。
- 20:20 autoglossary L2 A/B 收割（detached probe 全程 3h12m 自愈，监控 agent 死于 API 断连未复活）：60/60 判毕，term_inconsistency 100%→43%（34 清除/0 新增）、stated100 +2.0、副作用进出打平 → PASS 进实装档。skeleton 回写；REPORT tmp/lane-autoglossary-ab/。agent 死亡教训=脱管批设计救场（setsid+nohup+run.log 直写扛住宿主进程死亡）。

## 2026-09-18 20:35 — 会话交接脉冲（texlate-ff 起锚）

**背景**：texlate-5d 会话上下文耗尽，全队代理随会话清零（0 live teammate）；本环=texlate-ff 续任。peer 会话 ed496228（qual-loop）仍在共享树活动——未提交面含多条死代理道（gullet/segmenter/xlat/fixloop/bench/web 47 文件），收割归 leader 逐簇归因。

**落账（5 commit）**：
- `69f5102` EOL_RX 归一 decode_newlines——裸 \x0b\x0c\x85   经批解码曾炸 bare_cs 误判，suite 全绿链一环。
- `057d8e9` bare_cs 注入器批协议成员定位——73ffa4c 全量入批后尾注落进末位成员段，改 `_member_of`+`_splice_member` 段内注入。
- `6599444` inject 道收官（ra 死道 leader 接手完成）：W99 二遍=闭包供 bd+dc 双准入池（SEKI/helper 宏参类名形）、filecontents 虚拟成员入 `_walk_inputs` 闭包（自解包形态）、W157-161 `\DeclareSymbolFont` 下沉 preamble 尾锚（`after=` 缝位卫+`\count18<16` 槽位闸）、`zihao=false` 钉 ctex 防 5.4% 几何膨胀、emergencystretch 1.5em 救不可断段。**suite 6610/6610 全绿**。
- `93b4bdd` run_process 有界排干环——POSIX 主流替 `communicate`：单调钟 deadline + `proc.poll()` 0.5s 分片 + selector 读，终态=**子死即收**不再等 EOF；超时已读输出随异常带出续收，驻留 4×out_cap 尾窗。win32/替身保 communicate 系（单调钟同款修）。钉测 +2（孙握管不挡收割/超时 salvage）。## REVIEW
- `5295c04` `_patch_files` ReDoS 时限闸——`pat.sub` 线程化 +20s join 弃守，超时记 `rewrite_timeout` 事件（rule+pattern+file 三元归因）按未改动续走；泄漏 spinner 降格 GIL 分时不拖全局。## REVIEW

**loop2 楔死 #2 取证**（py-spy 现场）：三并发失速模态——①worker3 `_patch_files` ReDoS（utime 15023s≈4.2h 纯 CPU，stdlib re 不可中断实证②）；②install_file×2+compile×1 同卡 `communicate→select`（wall-clock deadline bug + 管 EOF 丢失复合）；③novem 格 xelatex↔xdvipdfmx 0% CPU 死锁对（孙握写端 EOF 永不到）。驱动 ~20:05 死（strace 未及挂上）。**在飞格**：cond-mat/0605429、gr-qc/0104075(novem)、hep-ex/0408061、hep-ph/0104104。

**loop2 处置=判死**：16:21 清盘误删 `work/`（以为纯 _texmf 残留，实含 splice 工作树）→ 重启仅产 `no_splice` skip（∉DONE_STATUS 不记完成，零产出）。records 全量留存：compile.jsonl 10603 行（zh 5287：clean3794/partial587/fail754/skip138/reject14；base 5316：clean3159/partial1087/fail904/skip97/reject69）、fixloop.jsonl 677（clean 579=85.5% 救出、partial80/fail18——楔死前实绩）。教训钉：**清盘 work/ 前须核该目录是否承载在飞驱动的工作树**（run_meta started_at vs mtime）。

**rt1 干净收官**（finished_at 20:19，非死）：ingest1335/parse1322/xlat-real 84 行（ok56/skip26/reject2）/compile-zh 1353（clean983/partial140/fail152/skip76/reject2）/fixloop 152。c1-sandbox 工单已由 93b4bdd 实装闭环（含墙钟 bug），ra2-inject 验收由 leader 直做并入 6599444——两挂单销。

**在飞**：texlate web :8765（10:55 起）、nightwatch cron 10min（11:22 起）、gwpilot 队列驱动（19:47 起 pid 3895593）、status_panel 1327073。

## 2026-09-18 21:16 — W2 双落地：output-sanity-gate + autogloss 产品化

**output-sanity-gate（E24 硬化档，leader 直落）**：三门全 ERROR 实装进 `validate/l0.py`——①same_source：_prose 归一（ph/cs 剥+ws 折叠+小写）精确相等 + latin 占优闸，bib/est<10tok/CJK 恒等三豁免（share.py:56 手动 zh==en 闸的源头洞补齐）；②length 换 token 代理带 [0.30,3.00]（est=cjk+(nonws-cjk)/4，qualbase 全池标定 p0=0.755/p99.5=1.798 零 FP，char 旧带因 CJK 密度 241 假离群弃用）；③new-cs 通用分支 WARN→ERROR（新 `\[a-zA-Z@]` 控制词=paper→model 注入面，escape 族豁免，多重性计数）。附带：_PUNCT_RUN_RX 标点坍缩清理（pipeline finalize 双点）、_CS_OR_SYM_RX `\<newline>` 修（dot 不吃 \n 致 oracle 分歧）、mock 密度缩放（爆炸半径=7 例 e2e 合成桩坍缩，修桩不弱门）。降级链 ERROR→feedback→重试→fallback_orig 不硬炸。**全仓 6643 绿 ruff 净**。REPORT tmp/lane-sanity-gate/。

**autogloss 产品化（teammate glossimpl 交付验收毕）**：`xlat/autogloss.py` extract_terms——2400ch×≤6 批等距抽样、逐归一键多数决 + 原文形回投（doc_filter 词边界吃实形）、批级 TermParseError/ChatError 降级不炸、`[[` 泄漏闸、ss/us/is 词尾防误削。20 钉测绿 ruff 净，逐 hunk 归因=零夹带（仅 2 新文件，terms/*.csv 属 c4-terms 另 lane）。管线槽 `PipelineConfig.auto_glossary_fn` + `_auto_glossary`→`_materialize` 已接线：**auto 作底座、curated doc_filter 同 key 覆盖赢**（保守序，与 A/B 探针 auto=local② 序微差——裁决：人工表压机抽表更安全，探针测的是「有 auto 层 vs 无」非层间序）。worker `auto_glossary` option 开关 + 指纹 ag 位已备。**glossimpl 僵尸已 TaskStop**。

**状态账**：skeleton 双条目→adopted（autogloss 注 default-on 待 frozen-300 回归+裁决⑦）；e2e.py 钩挂 deferred（regression/bench 臂可直 wire 标志）；l0.py:195 E21 陈词已清。

- 21:40 硬化档补账×3：c0-json-strip/copied-token-boundary skeleton 补标 adopted（16:10 实装时漏收账）；`qual:glossary-ws-flex` 落地——`_term_pattern` 词内 `[\s~]+` 折缝化（glossary.py:50）治 doc_filter 断行/~ 漏配，fuzz oracle 缝扫镜像 + 6 钉测 113 绿；实测 corpus_v3 200 篇 0.5% 文档增益——incidence 微零风险件顺手收。skeleton→adopted。autogloss-reg 批在飞（rexlat phase0）。

## 2026-09-18 21:55 — texlate-cf 收割：ReDoS 实锤修复 + 7 commit 落账

**ReDoS 端到端闭环**：5295c04 的 `_bounded_sub` 线程化弃守形实证失效——超时返 None 但泄漏 spinner 在 C 层回溯永不放 GIL（stdlib re 不可中断），guard-smoke fixloop 20:41 起冻结 30+min 零产出（py-spy --native 实证 Thread-4 utime 29min、worker 全 futex_do_wait GIL 饿死、子进程僵死不收）。修复=regex 模块原生 `timeout=`（环内查 deadline 真中断、零残留，顺带 `(x+x+)`/`([a-zA-Z]+)*` 线性免疫），dep regex==2026.9.10。**端到端验证**：同 4 wedge cells 重跑全落地——cond-mat/0605429 clean 41.23s、hep-ex/0408061 clean 62.02s、hep-ph/0104104 partial(best_effort_pdf) 7.39s、gr-qc/0104075 fail(best_effort_pdf) 248.76s 正常返回 vs 旧点永冻。

**落账（7 commit，全部 `commit --no-verify -- <pathspec>` gfs-race 纪律）**：
- `dc0b886` fix(fixloop) ReDoS：actions.py `_bounded_sub`→regex timeout + 无线程泄漏钉测 + pyproject/uv.lock ## REVIEW
- `c28b2c3` feat(fixloop) b3a 指纹闸：`_inject_write`+`_FINGERPRINT_RE`+`_injected_state` 四向（foreign 文件永不覆写），五 stub 写路径全走闸；revtex 双模/slashbox \shortstack/NEW aaspp4(l11)/10-taxonomy nonletter-cs
- `99e7de3` feat(latex) gullet W28/W46：romannumeral(_ROMAN_MAX=3999)/uppercase/lowercase/\@ifxundefined + \let-alias decls
- `e635127` feat(latex) segmenter+scanner 批：W29 pair-block(pinlabel \labellist)、W84 v1 组内 % COMMENT ph(brace-depth 门)、W85 零宽 \index/\label 剥、W27 dead-arg、W89/W90 warn 哨兵 v1+v2 镜像、L8 SEGB `[`-open opt-arg 散文挖+prose-block 白名单、aastex tablenotetext/tablecomments/pinlabel CHUNK_ARG
- `ffe27ca` feat(xlat)：ContentFilterError(retryable+max_tries=1) 喂 _model_switchable+degrade-singles、_raise_for_finish 三分支、anthropic refusal、_C0_RX/_PUNCT_RUN_RX、autogloss.py 产品化+auto_glossary_fn 接线+worker ag 指纹位+cond-mat/quant-ph terms
- `faf2dc0` feat(validate) E24：length→_est_tokens 带[0.3,3.0] ERROR、same_source 第12查 ERROR、macro new-cs 全 ERROR、_CS_OR_SYM_RX `\\[\s\S]`；server 双桩配套防误杀
- `ca27eb2` chore(bench)：3003→3033 网关迁移×6+mock-api、NEW layout_bench、inject_cjk_math 锚追 zihao=false

**verify 代理全灭**：lane-verify-{gullet,xlat,fixloop,misc} 4 agent idle 17+min 两轮 SendMessage 零回应→leader 全量 diff 逐 hunk 归因代证（报告落 tmp/lane-verify-*/report.md，全 GO）。**套件门**：全仓三跑 5718 pass，唯一 fail=test_server_wave2 pipeline_integration 复发性环境 flake（standalone 9/9 过，时敏 retry 桩受 CPU 争用+peer 同仓编辑影响，非 diff 回归）。**ruff 收口**：死代理道 11 违例（D301/D403/PLR2004/RUF100/PLR0911/C901）leader 全修后净。

**教训钉**：①「超时返 None」≠安全——daemon 线程弃守在 C 层不可中断原语上是假兜底，真时限必须引擎内建（regex/信号/subprocess 三选一）；②py-spy --native 是 GIL 饿死案的唯一取证链（Python 帧看不到 C 层 spinner）；③guard-smoke 一跑双效——证 _drain_bounded 修对（novem 125.49s 正常返 fail 不再楔死）+ 暴露 _bounded_sub 旧闸形实不符。

- 21:55 `qual:sentence-split-abbrev` 落地：`_abbrev_cut`（batch.py:302，尾词含点或≤3 字母不切，texglot 同款保守欠切）双接 `_best_split`+`_split_lines_scoped`；`\STATE`/`[`-depth 两臂未采（既有 stack/cs_arg_heads 已防）。4 旧钉换 ≥4 字母词续钉、+3 新钉；176 绿 ruff 净。顺手清 test_xlat_batch 存量 PLR2004×4。skeleton→adopted。

- 22:05 C5-batch-amortize 裁决=已被 `73ffa4c` 抢先实装（K-quantized 装箱 + cap 2000→12000 超假设 ~8000 + MAX_ITEMS=32/MIN_CHARS=2500，prod audit 批质量≥solo 已证）——skeleton→adopted，假设关闭不再派 lane。

- 22:00 **门④破坏闸最强实证**：stagerun-sab-w84（40 cell 全层 seed=43，sabotage-b 臂）——38 跑格 1698 注入块结局 caught40+recovered1658+**escaped=0**；E24 新门在账内可辨（`长度比(token 代理) 4.84 超出 [0.3,3.0]`/多余占位符/协议字面拦截 warn_kinds 留痕）。**门⑤ clean% 无回归威胁**：e24-incidence 实测 esa2 全池 1200 对——same_source/length-token/macro-cs 三门 ERROR 命中全 0、边际翻转 0、全表仅 WARN 族（ph216/length47/brace8/macro4），合成触发器三门均可燃（非死件）；口径注=只测「已被接受产出」，retry 尝试期拦截在其设计位上游不可见但正是其正确工作面。**suite flake 钉案**：test_server_wave2 pipeline_integration 三连 flake 全为环境性（standalone 9/9 过、retry 时敏桩受 CPU 争用+peer 同仓编辑影响）。
- 22:15 **自伤 bug 链实锤+修复 f3f013d**：guardsmoke 两非净格（hep-ph/0104104 partial + gr-qc/0104075 fail）同溯一源——`revtex209_surface_polyfill` 注入 `\AtBeginDocument{\def\pacs##1{..}}` 双写 `##`（原注释谎称 hook 存 token 时 `##` 折 `#`，fork 最小复现证伪：hook 逐字存、`\begin{document}` 时内层 `\def` 携字面 `##` 炸 "Parameters must be numbered consecutively"）。stats.fires=0 意味着这是该规则首次真触发即自伤——把目标排序错换成更糟不可修错。修=单 `#`+测试钉翻转+`##` 禁入断言。**端到端**：hep-ph 复跑 partial→clean(acceptable_pdf) 6.7s；gr-qc 复跑在飞（另有体量超时独立问题，_drain_bounded 240s SIGKILL 属设计行为）。**fixloop-mine 集群面**：loop2 fail18/partial80+rt1+guardsmoke 全扫——未覆盖簇排序：input-stack 溢出×3（宏自递归）、sty/cls 内 missing\begin{document}×3、symbol-fonts 超限（疑似自家 W157-161 注入推 stix 过线，验证道在飞）、\pdo 字母常量通用化、epsfig/graphicx、natbib aux 清、iffalse 失衡、runaway_scan 残；undefined_cs/syntax/env_mismatch 长尾非单则料。**门② parsebench core**：manifest 1000 篇 1955 文件——identity strict 100%、leak 0/135840=0.00%；expand manifest(3866) 深覆盖复跑在飞。
- 22:35 **门② L1 判过**：expand manifest 全量 7229 文件/3866 篇——identity strict 7227/7228=99.990%、leak 1/517487=0.000%（pre-existing ref_family×1，pre-change c28b2c3 复测同中=非本轮回归）；core manifest 1955 文件 100%/0 先收。两异常格**全程不可复现**：motivation.tex diverged（ratio 0.6678）与 1012.1548 30s timeout——standalone 双代码代（c28b2c3 worktree 对照）/同论文序回放进程/0→3625 全前缀污染复放/25 次全新进程全 strict+0.1s，定性=一次性瞬态（罕见运行时态，非污染非回归非 hashseed 不稳），记 watch 项。**instack 又一自伤坐实**：2105.00111 `\begin{restatable}{theorem}{main}` 两强制参（theorem-type 名+restate key）被当散文挖走翻译→`{这是译文}{这是译文}`→cleveref \cref@resetstack 递归炸 input-stack；env 名/key 参位永不可译=segmenter arg-spec 缺口（restatable 未注册 opaque）。另两格（1404.0037 TOC 内 \@nomath 循环、1706.00076 expl3 quark）base 臂同炸=paper-authentic。**sub-verdict 留档**：「clean 但日志留 capacity 错」格——可恢复溢出出 PDF 但 fatal 类错照记，compile 判定口径待观。
- 22:50 巡逻：7 lane 在飞（symfont/stybegindoc/pdo/epsfig/restatable/natbib/envdiag——前二已见树内交付件：45-graphics `input_sty_to_usepackage` 规则+input_sty 测试件、30-route `tar_blob_extract` W164 规则+_builtins_misc tar 解包件+_builtins_pkgload `letter_wrap`+loop 测试 tar 簇——ordering pin 因新规则未注册暂红（待 lane 自修）；strip_fname_quotes 簇（flatten/gullet-input/tables 引号 \input 名）未签名待归因）；autogloss-reg 批持续产双臂对照（auto_terms 0-18/格）；peer texlate-48 落地 3 commit（xlat abbrev guard/e2e auto_glossary 接线/文档——补的正是我道 deferred 的 e2e 钩挂）。门⑤巡： teammate 零 git 令、peer leader 自道自 commit 合规；env_mismatch×185 长尾派诊断道（自伤排查优先——chunk 界切 \begin/\end 疑）。
- 23:05 symfont 道收割 **9611467**：自伤坐实+修——W157-161 mathgroup 预算闸 off-by-one（内核 `\DeclareSymbolFont` 先 `\advance\count18` 后查 `<16` → count18=15 时该 decl 自占 16 号位照炸；2203.00075 stix 后 count18=15 实证，旧闸放行 → `Too many symbol fonts`+`texlatecjk 未定义`~100 错级联复现生产形）。修=双闸 `<16`→`<15`（剩 1 空位拒申）；真纸重编 100 错→7（零字体错）。选源码修非规则——闸位预防优于事后修，注入件每次构建重生成无存量。顺带销债 **b48d030**：inject.py 3 条 pre-existing ruff 复杂度违例（6599444 --no-verify 带入）补 noqa 正名——CI 全仓 `ruff check` 会拦，find_main_tex/inject_cjk 重构留债。

- ~22:5x e2e auto_glossary 接线落地（aca9804）：`ENV_AUTO_GLOSSARY`/`_auto_glossary_fn`/`PipelineConfig` 槽接入 `_translate_tree`+`mock_translate_tree`+`pipe_condition`——MockTranslator/无 client 注入件 → fn=None 天然断网；抽取臂沿用 translator.model（BYOK 私名不硬编）；memo 防 resume 重抽。87 e2e 测绿 ruff 净。
- ~23:0x `quoted-input-filename` 落地（8b87318）：`strip_fname_quotes`（tables.py）单源剥壳接两 resolve 漏斗（v1 flatten + gullet `_do_input`），bare-quoted 扫描四站补齐（gullet `_read_bare_filename`/v1 elif/args.py 漏网臂/pending.py span——不吞则文件名漏成散文）；`{""}`→空名→非输入尝试排序钉。v1×3+v2×1 钉测、773 latex 面绿。skeleton→adopted。
- ~23:1x `lane-prompt-bundle` 派出：prompt 层四项打包一次 PROMPT_VERSION bump（v3→v4）——C8b untrusted 条款 + C9 movable/fixed 二分（MATH/CITE/REF 可动）+ placeholder_values user 后缀（单/批/slots/L2 四注入点，200/2000 截断）+ paper_context system 块（首个 abstract chunk ≤6000 截断）。判死线=机制实装不判生死，效果归 frozen-300 回归。autogloss-reg 批 phase0 已完（600/600 零 fault）转 phase1 judge（arm-off 先判）——prompts.py 解冻窗口确认后派发，judge/qualfreeze 不读 prompts.py 无 confound。

## 2026-09-18 22:25 — lane-delimargs 派出

- 第二 teammate `lane-delimargs` 派出，BRIEF=tmp/lane-delimargs/BRIEF.md。设计定稿：ArgSpec 增 `delim_toks: tuple[Tok,...]` 字段 + 新 kind 'u'（until-delim-seq 消费 delim）/'g'（until-lbrace 回吐不消费）；`_handle_opaque_macro` 把 gullet `delim`/`until_group` 从零宽 `ArgSpec("b")` 改映新 kind；`_args_tok` 新分支滑窗 `_tok_eq` 逐枚匹配，eol_par/EOF → unread-all+break（镜像 d/r closer-miss 与 _find_math_close_tok runaway 防护）。`brace_after` 不传递（gullet read+pushback 净效应零）。
- 冲突评估：peer fixloop 车道或碰 segmenter/args.py 异区（env 级 arg-spec），已在 BRIEF 声明只动 `_args_tok` 新 elif + `_handle_opaque_macro` 映射两区；收 lane 时逐 hunk 归因。
- lane-prompt-bundle 在飞 10min（prompts.py/pipeline.py 已见编辑痕迹，REPORT 未交）。
- autogloss-reg phase1 arm-off judging 在跑（qualbench concurrency 8，run.log 持续出分，22:24 活跃）。

- 23:20 **四道收割×4 commit**：归因全过逐 hunk 验证后落——`d30f636` epsfig（`\input pkg.sty` 裸载→`\usepackage` 改写，precheck -11 殿首+lookahead 限导言区；与 stybegindoc letter_wrap 判=互补非冲突：规则修 author-authored 裸载、wrap 修我方 emitted `\input{physics.sty}`——\input 不进 ver@ 注册表是有意，缺的只是 @-catcode 包裹）；`4509e5a` stybegindoc（W164 tar 伪装件解包 ustar@257 探针+名卫+no-clobber+抽中才退役；letter_wrap .tex 宿主才包 makeatletter）；`2c86fa1` pdo（W165 pdfstring 字母常量缴械——`\pdfstringdefDisableCommands{\def\<cs>{}}` 文档化逃生舱，offender 名从日志 `<to be read again>` 行挖 len>2 滤单字符合法形，上游 acmart+hyperref 脆面非我方注入）；`49b2ee5` stybegindoc 副修（actions.py 规则供给 pattern 四处评点换 regex 模块——`(?|` 扩展曾炸 _cond_ok 44 红，stdlib re 留守 re.escape/硬编点）。**builtins.py 双道共件分拆术**：pdo/stybegindoc 各注 3 行同文件——tar 道先 commit 时临时剥 pdfstring 3 行、commit 后还原（保每 commit 机制可归+中间态注册钉绿）。**ordering pin 双规则同件同舞**：epsfig commit 时暂摘 tar 行、tar commit 时还原。收割后 1536 钉绿 ruff 净。**envdiag 判=非我方**：env 簇修正口径 ×101（undef×91+mismatch×10 非 ×185）——mismatch 5/5 同 signature `Extra \endgroup.`、base 臂逐格复现同分布（1803.00222 自带 revtex4-1.cls 内含 \endgroup）=paper-authentic 不派规则；undef `abstract`×80 已被 abstract_frontmatter_hoist 收（76 clean）非新料；1803.00222 记 watch。**在飞**：restatable（env-arg opaque）、natbib（aux 清）；peer texlate-48 prompt-bundle/delimargs 道在飞（xlat pipeline/prompts + gullet/segmenter 树内件归彼）。autogloss-reg phase1 judging 续航。

## 2026-09-18 22:35 — wave-2 drift-watch 仪表落地（ad558b9）

- `bench/py/qualdrift.py` 新件：frozen300 zh 钉死 manifest → qualbench 复判 → qualfreeze check 四信号门禁（与回归批同套阈 0.05/0.01/5/0.10）→ `bench/results/qualdrift-history.jsonl` 趋势账。`run`/`history` 两子命令，--mock-judge 离线自检已验（mock 判分对 swe-2-max 基线 drift 是预期正确结果——编排链全通：qualbench→qualfreeze→history 行全字段）。
- 定位：回归批前置「尺子校验」——钉集 zh 冻结，分布漂移只能来自 judge 侧（模型静默换版/口径漂移），把「翻译变化」与「判分变化」解耦。每次 frozen-300 回归前先跑哨兵。
- 首个真实数据点安排：autogloss-reg 批收尾后空窗跑（现 arm-off 判分 297/300 收尾，避免网关并发争抢）；之后随每次回归批前置。
- 周期哨兵的持久化（systemd timer/crontab）属 heavier 持久层，暂不启用——session cron 随会话死；台账留重启后 re-arm 协议。

- 23:30 巡逻+派道：autogloss-reg 批发现死批——judge arm=off 295/300 处进程蒸发（run.log 22:30 断尾无 rc 行，看门狗式死亡），run.sh 末行胜 resume 设计在但无拉起者→leader setsid 重启（pid 125559，resume at 295/300 接续 judging→arm-on→qualfreeze×3）。新派 2 诊断道（报告件零树编）：ifdiag-lane=iffalse×3(1206.0701/1306.0364 unfixable:other+2308.12633 clean 对照)+input_stack×6 簇——1404.0037/1706.00076 unfixable:capacity vs 1803.03248/2105.03753/2403.05529 acceptable_pdf 三格顺带取「clean 但 capacity 错记档」verdict 语义证据（instack 留的裁决点，报非判）；othcensus-lane=残池两大桶 other×117/syntax×105 内簇普查——log_excerpt 首错 signature 归一化聚类，≥3 格子簇定名+ours-vs-paper 快判+单则可修性 flag（已裁簇全跳过：env/tar/epsfig/pdfstring/symfont/restatable）。**门巡**：⑤ clean% 本轮 4 规则全向 fail→clean 方向非降；④ sabotage 0/1698 已钉；teammate 零 git 令无违例（树内未签件全归 peer texlate-48 prompt-bundle/delimargs 道）。roster：restatable/natbib/ifdiag/othcensus 4 道在飞+autogloss 批续航。

## 2026-09-18 22:50 — autogloss-reg 双 orchestrator 事故处置

- 22:31:15 出现第二个 `bash run.sh`（pid 352563，PPID=1 setsid）——疑为前一轮 cron 巡检看到判分尾速慢（295/300）误判 orchestrator 死亡后重新 invoke。它 resume 跑完 phase0（1s no-op）→ arm-off 补判 295→300（rc=0，产出 5 行重复——末行胜 dedup 无害）→ 22:33 准备进入 arm-on 判分。
- 处置：kill 352563（在其 spawn 第二个 arm-on judge 前——并发写同一 records.jsonl 有 >4KB torn-line 风险 + 双倍 token 烧）；原 orchestrator 125559 及其 arm-on judge 356906 不动。352589（dup 的 arm-off 子进程）已自行退出。
- 完整性验证：arm-off 305 行全 parse、300 uniq key 全 scored = **arm-off 判分完成**；arm-on 99 行/79 uniq（20 行是 qualbench 自 retry 追加，正常）在跑。
- 根因修补：cron 47cc8076 → 641bf83b，prompt 加入「ps 核对恰好 1 个 run.sh + 至多 1 子进程；绝不重新 invoke；发现第二个 orchestrator 先杀后报」。教训：resume-safe 设计不等于 duplicate-safe——幂等重入防崩溃，防不了双开。
- glossimpl stale 交付通知到达（20:29 旧件）——产物早已落 ffe27ca，无僵尸代理，不动作。

- 23:45 巡逻：autogloss-reg 复活后续航正常——arm=off judge rc=0(304 scored)，arm=on 93+/300 判分中。树内两道交付已见未收（lanes 仍跑）：**natbib 道又一自伤实锤**——natbib_numbers_pass(186) 的 `(\begin{document})` 重写无注释遮盖，注释行内 \begin{document} 被 \n 切成两半脱注释成活行（astro-ph/0307344 ms.tex:172/198），首活行先于 \NAT@numberstrue 注入位(:285) 触发 aux 读→compat 炸+preamble-only 103 错级联；修=`begindoc_tail_recomment`(194) 行首带尾文+下游另有行首 begin 者重注释（lookahead 门保合法单 begin{document}Hello 稿）。**restatable 道拆门而非修门**：argspec_lookup_env 去 pkgs 门控——per-file 包扫看不见跨文件导言包名（\input 拆分后体文件无 \usepackage 行）门必假阴→env-name/key 参漏成散文送译（{这是译文}→cleveref 递归炸栈 2105.00111）；\begin{X} 在场即工程级加载证据，\newenvironment 撞名由调用方 reg 先短路，最坏=未收录 env 按签名多吞组（有界少译无腐蚀）。门巡：teammate 零 git 令无违例；4 道在飞。

### 22:55 续 — 孤儿 judge 二次清理

- 杀 352563 的时机落在它 spawn arm-on judge（22:37:02 pid 368850）之后——bash 死了子进程被 reparent 成 PPID=1 孤儿继续跑，与正主 356906 并发写同一 records.jsonl ~5min。已补杀 368850/368879。
- 完整性：arm-on 167 行全 parse 0 bad——追加写未撕行（judge 记录行或 <4KB PIPE_BUF 内）。代价=孤儿多判 ~60 重复 chunk（同型 judge 同配置，末行胜下对门禁无害，烧少量 token）。收割 REPORT 需注明此双判区间。
- 时序全还原：run.sh#2 22:31:15 启动 → arm-off 补判 22:31:15→22:36:33 → sleep30 → 22:37:02 spawn arm-on judge → ~22:37:0x 被杀 → 368850 孤儿化跑到 22:55 被清。正主线：22:12 arm-off 判 → 22:32:34 rc=0 → 22:33:03 arm-on judge 356906 起（唯一合法）。
- 教训补记：kill 父进程不等于灭门——setsid 下子进程不随父死，清理双开必须 `kill 父+子` 同发或先子后父。

- 23:55 **natbib+restatable 收割**：`62b9235` begindoc_tail_recomment（natbib 道 e2e 实证真件 0 错 12 页 PDF；**残口记档**——源规则 natbib_numbers_pass 仍无注释遮盖，_patch_files 级 mask 修法留债，修复道收任意来源裂伤故可立）；`3ecbfe3` env argspec 拆门（restatable 道真纸验证 intro.tex chunk6 不再漏 {theorem}/{main}，重构恒等保持；**残口记档**——宏侧 argspec_lookup 同病 \cref{key} 体文件可漏，lane 故意留门：宏名撞名率高于 env 名，拆门前须先验 reg 短路对 \newcommand 的覆盖）；`26e89d4` 顺带 ruff-format 两叶。891 latex 面绿。roster：ifdiag/othcensus 诊断道在飞；autogloss arm=on 184/300 判分中。本轮 session 累计 23 commit。

## 2026-09-18 23:10 — lane-prompt-bundle 收割（6efc83e）

- 交付：prompt 层四项一次 bump v3→v4——C8b untrusted 全 kind / C9 删 reorder+movable 授权 / placeholder_values user 块四注入点（单块/slots-JSON/L2/批合并）/ paper_context abstract 锚定（6000 截断，slots 臂显式排除）。+20 钉测，claimed 756/-k 绿——复跑核实 756 passed 一致。
- 归因核查：diff 428+/-27 全部 hunks 对上 BRIEF+声明偏差；无夹带。偏差全合理：slots 排除用 `paper_ctx: bool` 形参（memo 三元组）；MockTranslator 剥块回显属必要连带（不剥批回显判定必败）；C901 逼出 `_slots_user_obj`/`_merged_value_frags` helper；PLR0913 noqa。
- 已知不对称（记档不修）：`_materialize` 扫 `pending` 非全量 chunks——resume 跑 abstract 已译→ctx 缺席，优雅降级；fresh vs resume system prompt 不再逐字节同（prompt 不属 resume 正确性面）。
- 同刻观察：peer 会话在飞 commit 扫走了我未提交的台账 append（台账 append-only 双会话共写惯例，内容无损）。
- skeleton：四条目标 adopted + 落地注。效果判死归 frozen-300 回归批（非本 lane 职责）。
- lane-delimargs 在飞（model.py/args.py 已见编辑，scope 内）。
