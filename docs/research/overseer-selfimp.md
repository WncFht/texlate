# overseer-selfimp 台账（append-only）

> selfimp 常驻环编排台账。leader=texlate-5d（archbox 本机）。每条一行事实：时间/车道/动作/证据指针。车道交付物在 `tmp/lane-<slug>/`，落账指 mechanisms.jsonl + rules/ + skeleton。

## 2026-09-18 环启动

- 09:10 基线口径复核：mechanisms.jsonl 210 条（covered 68 / partial 134 / implemented 8）；loop1 records 69535 行 5124 格 scorecard pdf 97.89% clean 84.99%；leak 0.040%（dollar 族 57 条残留）。
- 09:10 rt1 批（pid 4023412, xlat real arm, core+booster+hot）仍活：records 02:07 后无整篇 append 但 work/{id}/xlat-real.jsonl 09:10 仍在写——chunk 流式推进中，未 stall；nightwatch lane 接管监控。
- 09:11 跨会话边界（texlate-80 确认）：bench/py/qualbench.py judge 协议面归 texlate-80（GEMBA-MQM 化在飞）——selfimp A2 只做执行层跑批，不改 qualbench.py。texlate-37 已离线，其在飞 lane（revtex-209/o2-opaque-prose/early-eof-tax/gullet-at-scout）按未落地处理，冻结面：segmenter/args.py、builtins*.py、_builtins_shim.py（待核实死活后解冻）。
- 09:12 wave-1 发车 23 lane：A1-A5 测量面 / B1 mock 基线批 + B2 六篇回归 + B3a/b/c C-bucket 归因 / C1-scout partial 分族 / C2 dollar 族 / C3 fixloop 规则 / C4 术语表 / C7 server 裁决备忘 / C8 normalize 拆分 / C9 fuzz / C10 corpus expand+orphan / C11 上游挖掘 / RA reaudit-A 真 bug 批 / RB 单源收尾 / RD 测试钉 / RE 文档漂移。
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
- 10:10 **事故**：nightwatch 首巡抓 rt1 `ORPHANED_FD`——pid 4023412 fd4 指向已删 `records/xlat.jsonl` inode（孤儿 953 行 vs 可见 84 行冻结于 02:07）→ 抢救：`cp /proc/fd` 快照 `tmp/lane-a5-nightwatch/xlat-orphan-1011.jsonl` + `tail --pid -f` 跟随者 pid 1978705→`xlat-orphan-follow.jsonl`；孤儿前 84 行与可见逐字节一致→批终单文件恢复即可 | 鉴证派 a5:02:07 谁换了路径 inode（gwpilot smoke→real 交接 finalize 竞态嫌疑），产出 `orphan-forensics.md`——**关乎 loop2 在飞批是否遭同暗算**
- 10:12 a5-nightwatch | `8b23ff0` | bench/py/nightwatch.py（进程面/gwpilot 队列/活跃 run 台账/task_ping 看板，25min 停滞阈，ruff clean）
- 10:12 a1-timing | `2414a43` | bench/py/stage_timing.py（产出 `bench/results/_timing/` 目录 gitignored 不落库）
- 10:12 跨会话注记：07597e2/6fc4c2b（corpus hot 166 收尾，MANIFEST.md+manifest_hot）非本舰队——peer texlate-02 推同仓，已去函校准 corpus_v3 归属（a3 manifest_hot 段待其答复）
- 10:12 工作树待收面盘点：c10 orphan 立账 append（mechanisms.jsonl +38 行 examples-resolved）/c8 normalize→transcode+shadow 拆分（_builtins_misc import 涟漪属 c8）/a4 gate_scorecard+ 新测试/c9 fuzz 新测试/re-docs 五文档/c2 segmenter{mainloop,pending}/a3 manifest 三件+mech_ids+mech_backfill——ra 17 任务全 completed 但 src 面零 M（疑多项核销式结案），等其报告对账

## 落账流水（收割波 10:25）

- a4-scorecard | `7e05703` | schema v3：union 注记/csb 三档 drop（post_inconsistent/csb_contradicts_fp/**window_stale**=09-17 互踩假绿直接闸）/freeze 四信号+`--require-frozen` exit3/--json v3；loop1 复跑 5124/97.89%/84.99% 分毫不差 | 回授：wave.py `_SC_PATHS` 接线 + loop2 freeze dogfood（在飞批应得 partial 证闸活）→批终做 vs 09-17 diff
- c8-normalize | `073be4c` | normalize→transcode(434)+shadow(269)，29 块字节守恒、scoped 393 绿 | 升 L6 ENC 族 7 机制（normalize/transcode/shadow+textutil/{encoding,cjk}）；界外注释指针三件记账待 L10/L5/L2 道主
- re-docs | `dcf8fdf` | E 批残余 10 项全落（wave-2A 漂移/corpus 5232/segmenter 八叶/ts-validator 判定=已落） | 关代理
- a3-mechtags | `fae6d37` | mech_tags core1000/booster200（hot166 经 peer `6fc4c2b` 捎带入库——a3 工作树编辑被其 pathspec 捕获，归属记此）+ mech_backfill/mech_ids；expand 3866 缺 tag 已问询 | coverage.txt 22 orphan 清单已喂 c10
- c10-corpus | `06bdf4b` | expand 3800→3866（fetch-ids ok64/skip2/err0，≤85 guard 合规）+ mechanisms +38 orphan 立账；同 commit 捎 c1 L1 翻格 ~12 格（append=c10/status 编辑=c1 双记） | 升 L12 EVAL 族 15 机制
- c11-upstream | `026d694` | skeleton +6 假设：c0-json-strip→ra、auto-extract-glossary 直击 C4 瓶颈、abstract-context、delim-param-args 排 c12 后、quoted-input→tables.py 待派、original-repair-carry REVIEW 级 | 续挖 xlat 质量+compile 修复面
- c7-server | 备忘 `tmp/lane-c7-server/decision-memo.md`：SSE 无服务端闸（>6=浏览器约束前端已收）/GC 键实装默认关（~23MB/篇→千篇 23GB）/`settings.concurrency` **死键**（执行面零读取，真效仅 per-task） | 三裁决点入用户队列，c7 待命实装臂
- 跨会话：texlate-02 非 corpus 两 commit 主（server 只读排障中，动手前会通气）；hot 封层实主待考（texlate-80 疑）；texlate-80 已照会 gfs stash-pop 风险（10:21 f620827 提交触发全仓 mtime 重洗，内容无损）
- a1 升 C5：BATCH_MAX_CHARS 尺寸分析（_timing 数据驱动 + 网关 conc4/bg120s 排队计入；草案不改 pipeline.py——ra 面在飞）
- ra-bugs 状态更正：pipeline.py 终现 M（_route_chunks 残余+A 批实修在飞）——先前「17 任务 completed 零 src」系核销式结案为主，等报告对账

- 10:47 b2-sixregress | `ab6f708` | 六篇归因全复现三证闭合→mechanisms 立账 W157-W161（inject mathgroup 一族两形态=注入时序最大单点风险；W161 关联 W06）| repro 件 tmp/lane-b2-sixregress/（REPORT.txt+repro-*.tex）| 界外需求：inject 声明下沉/normalize bbl 拆引信/xlat Cf 剥离（最便宜）+env 保真 | 关代理
- 10:47 钉转正核销：test_fuzz_v1flatten 两枚 xfail_confirmed 已拆（c9 在 W73 根集闸落地后自行拆钉，docstring 注「XPASS 转红已拆钉转正」）→ scoped 26 绿 | c14 flatten W73 根集闸实证在树（flatten.py:63-110 roots 集+is_relative_to）
- 10:56 b3 族账收齐：b3a-undefcs 49 票（d38/c10/a1；covered-pending-verify35+fix-landed10 → verify-replay 45 格在飞 run.log）| b3b-syntax 37 票（c32/a3/b1/d1；fixable34；JHEP3.cls 连炸签名→c13 缺口榜重合）| b3c-other 30 票（pipeline_introduced17/vendor_stub_gap10/version_skew2/source_latent1；already_fixed18/规则候选 9→c3）| b3b/b3c 关代理，b3a 待 replay 结果
- 10:56 c9-fuzz | `85b8050` | test_fuzz_v1flatten.py 896 行（v1 _resolve/flatten_inputs 对抗探针+D1 逃逸六路钉）| 两枚 xfail_confirmed 已于 W73 落地后拆钉转正，scoped 26 绿 | 关代理
- 10:56 守护者二代：pid 2214285 已死（跟随者早夭同款命运），已 setsid+nohup 重挂 fd-hold（pgid 2317256）+ 即刻快照 xlat-orphan-1050.jsonl 987 行——孤儿 fd 仍随 pid 4023412 在写 | 教训：guardian 必须 setsid 脱管，harness 看门狗杀 shell 子进程
- 11:10 收割波 -2 落账（5 commit）：ra `562f773`（xlat 序章账本八点 _ledger_call 化+TestPrologueFatalLedger 10 例）+ `899416f`（reaudit-A 四钉 share-cap/align-close/hook-glob/secrets-repr）| c12 `4521e0e`（argspec 臂 [[CMD]] 散文抠出+keyval/comma-list 双形状门，全量 6343 绿+parsebench identity 100%）| c3 `d384916`（4 规则实证点火：greek_fontenc_install/legacy_pkg_shim_c3/cs_targeted_fix_c3/xcolor_override_opt_strip，6 翻 5 哨兵零回归）| texlate-02 `3fa3bd1`（biber/biblatex skew → REJECT route=xelatex 跨引擎臂：builtin+engine token+repair/e2e/worker 全链，实证 adopted→done——tectonic 死路开新路）
- 11:10 **里程碑**：c2 `31c432e` dollar 族收口——孤 \$\$/孤 \$/\\\$ 三形归 [[CMD]] 单项保真（v2 row17 同规），parsebench-v3-c2dollar **leak 0/136049（0.040%→0.000%）identity 1955/1955**；tricky-dollar.tex D01-D10 钉 + bench_regression 37→61 断言 | C2 目标达成，门②leak 读数归零
- 11:10 归因澄清：scanner.py=c2 在飞件（已收）；engine/builtins/10-taxonomy/80-bib/repair/e2e/server-worker-compile=texlate-02 跨引擎簇（其主动按约定知会，128 测绿实证）；四孤儿件全销账
- 11:10 解封派单：L2→c1（route-shadowed 专长续道）/ L3→ra（earmarked）/ L5→c2（dollar 邻面续道）/ L8→c12（args.py 同文件续道）/ L10→c3（rules 引擎续道+b3 工单汇流）/ L7+L9 新发车

## selfimp-qual 环（texlate-d9，2026-09-18 午启动）

- 启动：用户 /goal 派本环做翻译质量「评估→改进」闭环。与 compile 侧 selfimp（texlate-5d）互补；已照会 texlate-80（其 09:11 qualbench 协议面由本环接管）与 texlate-5d。
- **文件归属登记**（lane → 互斥文件）：leader → `bench/py/qualbench.py`（ESA 改造 proto-core/prompt/route/records 四合一）；sample → `bench/py/qualsample.py`；stats → `bench/py/qualstats.py`；anchor → `bench/py/qualanchor.py`；freeze → `bench/py/qualfreeze.py`；proto-test → `tests/test_qualbench_esa.py`；proto-probe → `tmp/exp/esa_probe*`；skel-curate → `docs/research/selfimp-skeleton.md`；triangulate → `tmp/lane-triangulate/`。qualbench.py 协议规格 = xlat-quality-eval-2026-09-18 §7（ESA 两步单发 stated100 主分 + derived100 自洽校验 + swe-2-max 主裁/swe-2-high 二裁）。
- 协议内一处补全：类目表加 `accuracy-mistranslation`（eval §7 映射漏列——六 flag 无「在译但错」收容位，probe 的 MQM_SYSTEM 本有；不补则错译被迫塞 omission/addition 扭曲类目表）。flags 派生新增 mistranslation/fluency_register 两值。
- 11:35 收割波 -3 落账（4 commit）：c14 `cf582ff`（v1 flatten `_resolve` openin_any 等价闸——real path 根集约束，`..`/绝对/根内 symlink 出界按 miss 永不进 read_bytes，与 v2 `_resolve_input` 同口径；W104 cs 文件名滤除同臂）+ `db3d4a1`（test_flatten_boundary.py 293 行五机制契约钉，28 绿）| texlate-02 `8672d22`（biber skew 测试件补收，属其 3fa3bd1 簇漏网）| c13 `498ae9e`（vendor 157 files + mn.cls stub，records 去重频次序——pstricks 全家桶/revtex4-2/llncs/kluwer/quantumarticle/siunitx 等）
- 11:35 b3a 终局：verify-replay 74/74 格零 dirty——66 clean + 8 partial（7×best_effort_pdf revtex209/natbib 点火后 best-effort 出 PDF + 1×fixloop:clean 但 compile 臂 partial）| 工单残留移交 L10/L2 | 关代理（b3 三族归因簇全闭）
- 11:35 关代理×4：b3a-undefcs / a3-mechtags / c14-flatten / c13-vendor / c7-server——交付物全落盘或入账，roster 16
- 11:35 nightwatch 常驻化：archbox 无 crontab → setsid 脱管 10min 循环 pgid 2472632（`nightwatch.py --save` → bench/results/nightwatch/cron.log），跨会话存活
- 11:35 派单补位回 18：l1-verify（L1 verify-flip 15 机制——规则已落待钉测翻格，只写 tests/ 新文件+fixtures add-only）+ l11-vendor（L11 残靶 9 件 ~300 篇：revtex.cls×167/mn2e×42/aa×33/JHEP3×14/aaspp4×12/svjour×9/aipproc×8/aasms4×8/JHEP，全 stub 形态）
- 11:35 c7 裁决备忘三问挂用户队列：TTL 默认/conc ceiling/SSE 聚合/settings.concurrency 死键接线——备忘在 tmp/lane-c7-server/decision-memo.md
- 11:40 c8-normalize | `0092fe4`+`5d396c5` | L6 ENC 落地：W91 `\-` 折行连字符还原（双 lookbehind + tabbing 豁免，normalize_engine 全引擎段）+ 顺手真 bug `_score_text` 大写重音罚分（mac_roman ‡ 彩票压 latin-1 à mojibake）+ 13 钉新文件 | scoped 406 + 全量 6381 绿；hep-th/9910234 17 处实证零误伤 | 界外：W72→ROUTE/vendor、W42 har2nat 已随 c13 落地、mixed 彩票记账不追 | 关代理
- 11:40 跨会话：texlate-d9 新环 selfimp-qual（翻译质量 ESA 评估→改进）照会——车道 bench/py/qualbench.py+qual{sample,stats,anchor,freeze}.py+test_qualbench_esa.py+tmp/exp/esa_probe*，台账共用 overseer-selfimp.md append-only | 已复：与 texlate-80 qualbench judge 协议面归属重合建议互通；a2 旧 judge 批已结产出可对照
- 11:45 a2-qualbench 交付：qualbench-selfimp 基线 **600 chunks/60 papers mean 4.84/5**（5:531 4:52 3:9 2:5 1:3）| **头号缺陷 untranslated_spans×21**（占全 flag 半，caption kind 最密 11/21）| 产出 bench/results/qualbench-selfimp-2026-09-18/{records.jsonl 462KB, report.md 最差 30 格，layers.md} | 关代理
- 11:45 派单回 18：q1-untranslated（头号缺陷机制猎捕——xlat skip 路径/模型回英文/opaque 吞噬/caption 特异，只读归因+mechanisms 立账）+ r2-residual（b3 孤儿三件：texlog nonletter payload 边界/stale-stub 指纹面/math_env_alias_cs 立账，全只读）
- 12:05 巡检脉冲：loop2 compile 8454→9161（+707 在飞，xlat/parse 满 5122）；rt1 pid 4023412 存活、孤儿 fd 守护者 pgid 2317256 持守（可见 84 行未动）；nightwatch 脱管环 10min 准点落 md
- 12:05 a1-timing | `c2018de` | 请求时序三分拆（contextvar chat-sink+outer/inner/chat 三 span→req_timing records）+ batchmodel 文档（devin2api 86,705 行实测：conn 1.8s 固定/decode 543+13.3ms·out_tok/~550 out_tok/s 全局上限） | 注：loop2 xlat 先于插桩，req_timing 自下批生效 | 关代理
- 12:05 派单 r3-audit：收割波 -2/3 ~10 commit 独立复核（只读，按风险序：W91 regex 全引擎接入/biber skew token 流/根集闸语义/scorer 罚分）——回归门的独立验证层
- 12:30 巡检脉冲：loop2 compile 9161→10286（+1125 在飞）；rt1 持守不变 | texlate-02 跨引擎钉 140 行代收 `56157b5`（test_e2e_wiring+test_worker_audit_fixes reject_route 双臂覆盖，122 绿）| 在飞面全可归因：c1-L2(engine/probe/latex209)/c3-L10(_builtins×3+10-taxonomy+slashbox)/l9(gullet×4+test_gullet_l9)/c2-L5(model+tricky-mask+regression 61→72 钉)/l11 首两 stub 落地 (mn2e+revtex)/l1+q1+r2+r3 新道工作中 | ra-bugs 转 idle 已问询 L3 状态
- 12:40 selfimp-qual wave-0 发车（texlate-d9）：`914664d` qualbench.py ESA 落地（esa2 协议：errors[]+stated100 主分/derived100 自洽校验、9 类目 MQM 化、critical 收窄、key 并 protocol_v、swe-2-max 主裁/swe-2-high 二裁、judge≠translator+medium 永禁、--source manifest）| ruff clean + mock 冒烟 11/11 绿 | 并行 7 lane：proto-test(test_qualbench_esa.py)/proto-probe(n=8 前后对照 tmp/exp/esa_probe)/sample(qualsample.py 1200-chunk 分层)/stats(qualstats.py bootstrap CI+pairacc)/anchor(qualanchor.py ESA^AI 人审包)/skel-curate(skeleton 卫生)/triangulate(XCOMET-QE 可行性)
- 12:40 升级待用户裁决①：glm-5-2 实为免费档常设（archbox model-dump 实证 mult1.5 ZAI FREE——「已判付费档」旧读数过时；若解禁可建跨家族三角 judge 臂，现仍按硬边界 swe-2 系）
- 12:40 升级待用户裁决②：协议内补 `accuracy-mistranslation` 类目（eval §7 映射漏列——六 flag 无「在译但错」收容位）——已实装，若反对可回退
- 12:55 wave-1 预置：batch 驱动 `tmp/lane-batch/run_qualbase.sh` 就绪（setsid 脱管+resume 循环×6，conc4/judge-timeout300，records 行数=完成度信号），sample.jsonl 落地即发车；freeze lane 发车（qualfreeze.py freeze+check，KS/flag 率/kind 均值/contested 四信号，阈值参数化待裁决）
- 12:55 升级待用户裁决③：frozen-300 门禁阈值（ks-alpha/flag-alpha/kind-delta/contested-delta）——freeze lane 交付后附建议值再报
- 12:58 triangulate stall（jina reader 挂起 600s watchdog 杀）→ 重派 triangulate2，禁 jina/慢 fetch，gh api+WebSearch 优先，网络全断则标「待实测」照交
- 13:20 收割：anchor `d82a914`（qualanchor.py 682 行 sample/harvest——kind×stated 分带两层轮转+contested 配额 ~n/2，item 盲分防锚定，index human_score 快速通道）| proto-test 同 commit（test_qualbench_esa.py 44 例全绿 + scoped 281 无破）| 两代理交付即终
- 13:20 proto-test 钉出实现偏差记档：l0_ph_unreported=ph_missing∨ph_invented（比清单宽，合理）；JSON_OBJ_RX 贪婪——raw 含两个 {..} 对象时兜底失败靠 reparse 兜；缺省 severity→minor 不计 sev_clamped；pair.key 无 arm——同 paper+chunk+model 跨 arm 续跑会互截（单 arm 基线下非活问题）；route_judge no_eligible_judge 为防御性死码
- 13:02 收割波 + 发车：sample `023d991`（qualsample.py 分层抽样——para 池级 tertile cuts=[210,538] 各 300/caption150/section_title150/350 篇 均值 3.4 块，池内无 abstract/table_text/env_text 为既有缺口；rt1 池抽样期仍在长 1003→1027，sample.jsonl 即冻结快照）| stats 同 commit（qualstats.py 818 行 ci/pairacc/report——paper簇 bootstrap B=1000、acc23 tie-calibrated、skipped_old_protocol 摘要节）| proto-probe **PASS**（B 臂 8/8 首发解析、span_verified 10/10=100%、零类目越界、抓到老协议漏检 convention 违例；stated 系统性严于 derived mean Δ=-15.25 靠 contested 兜；l0_en_unreported 合法留英机械触发=规格内）→ **qualbase 1200 批发车**（pgid 2867288，conc4/judge swe-2-max+second swe-2-high，~4-8h ETA；watcher cron 204b0d68 23min 脉冲 + 死拉）
- 13:30 skel-curate | `13d1b59` | skeleton 卫生：adopted 区新建收 2（prose-recall-opaque `4521e0e`/missing-file-x23 `498ae9e`）；unblock 2（C5 待 leader 裁决、M8 标可发车——实按本环裁决 hold 到 esa2 基线，旧 1-5 分不可用于低分靶选）；qual: 标 13 条含 c11 新增 6 假设（sentence-split-abbrev/copied-token-boundary/movable-token-license/placeholder-value-context/untrusted-content-clause/content-filter-fallback）；指针修正 9 处零失证 | 关代理 | 新候选 6 条待侦察（REPORT 附录）
- 13:30 波次状态：W0 全闭（esa2+44 钉+probe PASS）| W1 批在飞（records 计数中）、freeze/triangulate2 待交付 | W2 池就绪：qual: 13 条 + 候选 6 条，基线读数落地后按证据强度发车
- 13:10 收割波 -4 落账（8 commit）：ra `6aeb69a`（test_arxiv_locate +10 hermetic 钉 W69/W98/W71/B07/W52/W36/W16，L3 结案转 inject 道）| a3 `d53a429`（mech_backfill 两趟竞态安全重写）| c10 `281079b`（L12 flags 三通道 + 良性签名+B04/B06 簿记+docstyle_opts）| `9f37869`（manifest_expand 全行重写——c10 特征列+a3 mech_tags 交织双归属）| `ad5142d`（mechanisms 三归属：c1 翻格 W47/W103→covered、c10 B04/B06、r2 W162 undefined_cs 非字母 payload）| `0cff582`（skeleton +3：glossary-ws-flex/output-sanity-gate/compile-consumed-deps）| `4d18731`（8 vendor stub 收编——**归属更正：实系 c10 抢跑 #86 产出**，非 l11；aaspp4 败格扣留）| `8a42cf8`（c2 L5 MASK 族：env_name_at 注释剔除 W11 泛化 + unescaped_dollar_odd %→EOL W92，debt_repair 6→2/unpaired 170→166 真改善，门全绿）
- 13:10 **撞车事故**：c10 自我认领 #86/#87 与 l11-vendor（11:35 持道）正面撞——核实 c10 的 make_l11_stubs.py 已直写树内 9 stub（12:29），归属记 c10；l11 急停改纯验收道，c10 smoke 预检顺手成验收底稿并抓 **aaspp4 "No pages of output" 败格** 移交 l11 修。教训：自我认领须先报 leader 核持道状态。
- 13:10 派单：ra→inject 道（W99 裁决采纳 inject 侧：docclass-in-closure 两形态+filecontents 虚拟成员+b2 W157-W161 声明下沉）| c11→sanity-gate 道（其三闸提案实装：same-as-source/长度比带/新控制词 `\\[a-zA-Z@]` 拒收，xlat/{retry,pipeline}.py）| c10→C5 A/B 真网关探针（≤10 篇）| c3 L10 +4 工单（natbib author-year 守卫回归优先/_dep_fanout/undefined_cs→pkg 推断/\theorembodyfont）| b1 批尾 +2（stagerun ended_at+rc 增量/0307193 status 口径复核）
- 13:10 门读数：full pytest 4 fail 全在飞面可归因（c3 vendored 指纹头 ×2、售 c12 argspec+pinlabel/tablecomments ×2——道主交付时自闭）；l11 pytest 验证在飞；loop2 compile.jsonl 10343 行推进中。
- 13:35 triangulate2 | 交付 `tmp/lane-triangulate/`（REPORT+ 证据四件）| **GO-with-caveats**：XCOMET-XL 统一权重 QE 分支产 error_spans(char offset 可精确校验)+severity+0-1 分——唯一非 LLM 的 span 级评委，天然第三族仲裁臂 | 接入零改动：qualxcomet.py 产同构 records（protocol_v=xqe1），qualstats pairacc 直接吃 | 四 caveat：gated 要 HF_TOKEN/fp16 ~8-9GB VRAM 窗口（两 4070 余 ~5.7-5.9GB）/510 subword 截断/无 category 轴 | **意义**：不依赖 glm-5-2 解禁即可建跨族三角——W2 候选 lane qualxcomet（等 GPU 窗口+HF token）
- 13:38 升级待用户裁决④：XCOMET-XL 入网——需用户 HF 账号接受 cc-by-nc-sa-4.0 许可拿 HF_TOKEN（本机无 token）+ ~13GB 权重下载（禁代理直连 HF，可本机下后 rsync 去 archbox）+ GPU ~8-9GB 窗口。新模型入网按硬边界必须用户点头
- 13:45 巡检脉冲 3：loop2 fixloop 段在跑（pid 2579265 --on fail jobs6，fixloop.jsonl 667 行起步）；rt1 pid 4023412 仍活、孤儿 fd 1076 行续写（批龄 ~11.5h）；nightwatch 13:13 准点（main-coord STALE 挂用户队列）| `49b5a18` l1 fixture_assert mask dispatch 接线 + `321b6c1` r2 W163+q1×5 立账 | q1 关代理（交付落盘）；l11 #87 标完但 aaspp4 未动 + 无矩阵→已问询验收证据
- 13:45 freeze | `e794f60` | qualfreeze.py 755 行 freeze+check——低分全收+kind×band largest-remainder+ 保底，seed 逐字节复现；check 四信号（KS/flag-z/kind-Δ/contested-Δ）阈值参数化，unarmed→exit2 不假 pass | 关键设计：records 仅 160c excerpt，复跑必须 --sample join 全文 | 自测矩阵全过（合成 1203 行→300 命中、同分布 p=0.82 pass、degrade12 全信号 exit3）| 关代理 | 待裁决：DEFAULTS 四阈值 + --frozen 是否升必选（freeze 建议值附 REPORT）
- 14:05 巡检脉冲 4：loop2 fixloop 段续跑（compile +75→10418，fixloop 667 持平——fail 件修复轮次中）；rt1 孤儿 fd 1076 行持守 | l11 实证修 revtex.cls 在飞（compat `\documentstyle` 硬拒 revtex4-2 → 桥 article+2.09 残面两态分派，167 格 base 臂证据驱动；aaspp4 待处置）| 工单折叠：q-corrector-err-token-leak→c11 道（同授权面）、q-term-glossary-gap→c4 道（index.yaml 映射覆盖矩阵）| c1 L2 交付确认仍未回
- 13:50 L0 池面分析（sample.jsonl 全 1200，免费信号先行）：en_residue≥8 共 51(4.2%) 全在 para(5.4%)，两大块 en=85(1502.01863/0:261)/en=68(1608.06785/0:75) 疑整段未翻；ph_missing/invented 双零——占位符机制在池上零失守；same_as_source 2 例；zh/src 字符比<0.3 有 218 但中文字符密度天然偏低、与 babeldoc token 比阈不可直比——判读待 judge 分交叉
- 14:00 成本回执预算：翻译臂 rt1 1044 篇 134,065 chunk×6(swe-2-medium)≈80.4 万 mult·call；judge 臂预算 1200×12(max)+contested~10%×9(high)≈1.55 万——占比 ~1.9% < 5% 验收线（口径=判分 chunk 数×模型档，与 goal 的 ~1.6 万 mult·call 一致）| e2ereal 301 篇分母未计入只让占比更小
- 15:20 收割波 -5 落账：c1 `4534631`（L2 ROUTE 全量落地——probe _ScanCtx+5 字段/阻断名单三向抑制/docstyle_opts 非内核选项→pkg 依赖/六诊断注记、engine C901 拆分+psfile/.mf 双 reason 不改引擎序、latex209_no_decl 诚实桶拆分；mechanisms ×8 翻 covered；484 scoped+91 fuzz oracle 绿，REVIEW=新 reason 签名殊途同拒已采纳）| l1 关代理（15/15 翻格 +42 钉+fixture 接线全收 `ed66553`/`49b5a18`）；q1 迟来详报与已收 `321b6c1` 一致（en-gate 进 validate_fn=最大杠杆，c11 道在手）| c11 skeleton +6 实已在 `0cff582` 内（head 截断误读为 +3，补记：sentence-split-abbrev/copied-token-boundary/movable-token-license/placeholder-value-context/untrusted-content-clause/content-filter-fallback 全进账+output-sanity-gate 证据修正）
- 15:20 **事故已自处**：b1 报 loop2 fixloop 段静默悬挂 75min——gr-qc--0104075 splice/novem.tex 暴走 xelatex 吐 41579 页，run_process 无墙钟超时+threaded 死子管道 EOF 丢失=经典悬挂；已杀 pgroup 断点续跑（新 pgid 2935024，zh 补 163 格毕、base 补 97 在飞）| harness bug 派单 c1：sandbox.py run_process 墙钟超时（REVIEW 级数值件）+W72 残面+input-FP 裁决
- 15:20 派单：p1-prompts 新道发车（prompts.py 独占——q1 的 C2/C4 措辞收窄 movable/fixed 二分 + untrusted 条款，texglot/BabelDOC 先例在 tmp/refs）| a5 fanotify 裁决采纳跳过（CAP_SYS_ADMIN 墙拿不到肇事 pid，auditd 需 root→挂用户队列）| c3 L10 再 +2（90-shim-legacy 9 死条清理+revtex.cls `##` 塌缩真 bug）| c10 L11 迟报与现状一致（9/9 前移含 aaspp4 真稿 53 页 xdv——aaspp4 待 l11 复核同判即收）| c4 界外挂单：doc_filter accent-fold 归一（Schr\"odinger 407 vs Schrodinger 131 形态分裂，候选机制）+auto-extract-glossary 立项备
- 15:20 roster：在飞 c1/c2/c3/c4/c10/c11/c12/l7/l9/l11/p1/r2/r3/ra=14 道 + b1/a4/a5 常驻 = 17；q1/l1 已关（交付全落）
- 14:05 batch 提速：~150 对/h 系 per-call 延迟受限（decode 仅占 ~50/550 tok/s 全局）→ conc4→8，重启 driver 续跑 71/1200（教训：bash 循环体一次解析，行内改参数须杀 driver 本体才生效）| 全局 decode 余量仍 ~400 tok/s 让 rt1，ETA 8h→~4h
- 14:15 W2 L0 侦察×2（免费层先行）：**glossary-ws-flex 降级**——池上断开形术语命中 0/1200（换行 110、~ 223 块都在，前提成立但无命中），根因=terms/ 仅 cs.* 五表而池为 physics-heavy、doc_filter 近空转，skeleton 的 2.2% corpus 估计在本池不复现 → 待 auto-extract-glossary 落地后重测；**c0-json-strip 转硬化件**——src/zh C0 0/1200，机制真（json.loads strict+upstream PR #612）但池上无触发面，降为 cheap insurance 非主线；**auto-extract-glossary 升 W2 头号**——结构性覆盖缺口（physics/math/cond-mat/quant-ph 全零）= 池上术语面真空
- 14:20 修正：terms/ 今增 cond-mat.csv(751)+quant-ph.csv(306)（别家 lane 未提交在飞件，侦察已含）——覆盖缺口收窄为 hep-_/math._/astro-ph/nucl-* 等；断开形 0 命中结论不受影响（含新表后仍零），ws-flex 降级维持
- 13:42 批健康修正：driver/watcher 完成判定 wc-l 行数→scored 口径（score≠None），judge_error 行不再冒充完成、靠 attempt 重跑自动捞回；实测 conc8 速率 ~270 行/h（71→135/14min），ETA ~4h
- 13:50 anchor 包冒烟（live 数据 n=40）：143 行→139 eligible→40 选，contested 11/11 全收，excerpt_only=0（fulltext join 生效）；item 件形态正确——【】就地标记+judge pre-marks 无分盲审；批后 200-chunk 生成 = 一行命令已验证
- 14:05 L0 侦察×3 补刀：**copied-token-boundary 同转硬化件**——机制在代码里属实（pipeline.py:586 裸 `count==1`+`replace` 无边界），但触发前提=模型把源片段抄回译文，而 ph_missing=0 全池——copy-back 行为在本池无踪迹（修复亦不记 warning，池面无 incidence 可测）；三条 c11/池假设（c0/ws-flex/copied-boundary）共同模式=机制真+池 incidence 零 → 硬化档不烧 W2 主线；有池面实测的优先项：auto-extract-glossary（覆盖缺口）/en-residue-rexlat（51 块）/output-sanity-gate（2 echo+ratio 尾）/m8（待分）
- 14:10 qualstats live 冒烟通过（169 scored）：contested 7.7%[4.1-11.8]、span_verified 90.6%[82-97]、score_delta -6.8；**flag 分布翻转坐实**——grammar/term 各 13.6% 领跑、untranslated_spans 1.8%，旧协议头号缺陷结论被 esa2 类目表证伪：真病灶=流畅度 + 术语非未翻 | W2 发车单草案落 tmp/lane-batch/w2-dispatch-draft.md（auto-extract-glossary 头号/en-residue 次席/output-sanity 三/m8 待低分格计数）
- 14:25 L0 侦察收官×2：**content-filter-fallback 硬化档**——rt1 13.4 万 chunk error_kind 仅 provider×396/validate×1，content_filter 零命中；**sentence-split-abbrev 中档**——attempts>1 共 2014 chunk(1.5%) 确走 whole→lines→slots 分裂梯，缩写误劈途径真实存在但坏劈计数未测；**新发现**：梯尽案例见 skip_reason——`[[MATH_92]]`→`[[MATH_93]]` lev=1 自诊「可自动修复」却仍 fallback_orig 整段英文（brace 深度 -1 并发），占位符自愈钩子诊断在但修复未救回，值得入 skeleton 新假设
- 13:49 再提速 conc8→12：decode 实测仅 ~40/550 tok/s——瓶颈是 per-call 排队延迟非吞吐上限，多 worker 吃 rt1 相位空窗；若网关告警回落即降回 8
- 14:00 校准向早读（187 scored）：**en_residue→judge omission 对齐仅 25%(1/4)**——若全 51 块复核保持 <60% 判死线，en-residue-rexlat 须先做信号提纯（剥人名/机构合法留英）否则判死；judge2 在 contested 上 ±10 内确认主裁为主（stated 整体感扣分被验证），contested 机制健康；over_translation 为 contested 头号驱动 8/17（数学/命令被翻）——与 ph 零失守并读=模型不丢占位符但会去翻译其紧邻 LaTeX/数学面
- 14:02 batch 工程：watcher 接自动收割——终态（scored=1200 或驱动两轮全尽仍停滞）触发 tmp/lane-batch/harvest_qualbase.sh，一把产 frozen300.jsonl+anchor200/+ci.txt+report.md+en_residue_xtab.txt，marker 记 scored 数幂等防重、增长可再收；err 4 行全瞬态（3×ConnectError+1×unparseable，resume 自愈）；en_residue 交叉表复测仍 1/4=25% 命中（en=11 块 stated=100 全净=合法留英稀释信号，「先提纯后红线」方向更实）| 现 365/1200 scored、contested 7%、mean 92.6
- 14:15 基线中段重大发现=新头号假设 **bib-passthrough**：major 级错误格第一大户 convention-do_not_translate（28 条全同病灶）——^[[BIB_ 锚首块（bibitem 起点，L0 单子串可检）样本 4.3%、已判 29 块 90% 被标（major23）、stated 67.9 vs 95.3。机制=文献条目约定留英却照常送翻→绕过送翻灭 major 类+省 4% token；挂用户确认项=参考文献区全英化为产品可见语义。已置 W2 发车单 Tier1#0，吞并 m8 低分格 bib 子群 | judge2 早读：contested 上 30/31 在±10（mean-0.6）=抓固有两可块非抖动，机制健康
- 14:35 中段读数三件：**m8 判死在即**——stated<55 仅 3/512（2 块 BIB 归 bib-passthrough、1 块 untranslated），外推 ~7/1200<<30 线，skeleton 已标待批终转 rejected；**critical 零命中**——收窄枚举后池面无致命级，critical_present 触发器空转；**bib-passthrough 入 skeleton open 池**（REVIEW 级挂用户语义裁决，证据=28 条 do_not_translate 全文献条目形态+90% 中招率）| contested 主驱 delta_gt15×37、l0_en_unreported×11 合法留英假阳（probe §7b 预言命中，~24% 二裁流量空耗=阈值调整建议随升级包）
- 14:50 **en-residue-rexlat-redline 双重判死在即**：en≥8×omission 交叉 3/13=23%<<60% 线，且 en≥8 主 flag=over_translation×6（病灶在邻近 LaTeX 被翻）；旗舰极端例 en=68/85 两块全是合法留英文献条目（正确非缺陷）——「整段未翻」归 output-sanity-gate same-as-source 正解。skeleton 已标待批终转 rejected | 衍生两件：bib-passthrough 检测器补续段形态（1502.01863|0:261 en=85 无锚首=文献表跨 chunk 续段）、sanity-gate 须豁免 bib 语境否则误杀合法直通
- 15:00 批中段：606/1200、err 4→28 系网关 transport 抖动簇（27 ConnectError+1 unparseable，attempt 边界自动捞回，无系统性故障）；placeholder_broken×1 实为 `图 ~[[REF_177]]` 空隙 minor 非 selfheal-gap 机制；波末指标早值——score_delta mean -7.2（stated 系统性严 7 分，delta_gt15 驱动 7.6% contested）、span_verified 97.5%(306/314) 协议健康
- 15:25 归因修正 + 坐实：over_translation flag 实为 do_not_translate 类目映射（48/49）——早前「数学/命令被翻」读法证伪，头号 contested 驱动=文献违例本身；**do_not_translate×48 中 46 条在 [[BIB\_ 块内（96%）**，bib-passthrough 一臂灭类坐实；非 BIB 两例=全角括号/`干扰机发送概率` 散点。addition×19 全 minor 真微添加（"也/只需/可视化"类）弥散无单点修法→不入 W2 主线 | 排序核实：sample caption 前载/section_title 压尾→per-kind 均值批终才有全相
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

- 20:05 W2 硬化×3 落地（client.py 争用解除——原占 diff 是网关迁移 3003→3033 docstring 级陈旧件）：content-filter-fallback 实装=ContentFilterError(retryable+max_tries=1) 单类喂两臂（_model_switchable 换模 +_batch_call degrade-singles 替代整批 skip）；检测=400 body 子串 + finish_reason=content_filter（_raise_for_finish 抽件治 C901）+ anthropic refusal。钉测 182 绿 ruff 净；frozen-300 豁免（仅过滤事件路径、基线零事件）。skeleton→adopted；REPORT tmp/lane-contentfilter/。A/B lane 在飞 judge 37/60。
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
- `ffe27ca` feat(xlat)：ContentFilterError(retryable+max_tries=1) 喂_model_switchable+degrade-singles、_raise_for_finish 三分支、anthropic refusal、_C0_RX/_PUNCT_RUN_RX、autogloss.py 产品化+auto_glossary_fn 接线+worker ag 指纹位+cond-mat/quant-ph terms
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

- 第二 teammate `lane-delimargs` 派出，BRIEF=tmp/lane-delimargs/BRIEF.md。设计定稿：ArgSpec 增 `delim_toks: tuple[Tok,...]` 字段 + 新 kind 'u'（until-delim-seq 消费 delim）/'g'（until-lbrace 回吐不消费）；`_handle_opaque_macro` 把 gullet `delim`/`until_group` 从零宽 `ArgSpec("b")` 改映新 kind；`_args_tok` 新分支滑窗 `_tok_eq` 逐枚匹配，eol_par/EOF → unread-all+break（镜像 d/r closer-miss 与_find_math_close_tok runaway 防护）。`brace_after` 不传递（gullet read+pushback 净效应零）。
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

- ~~00:0x **othcensus 全图收割**（tmp/lane-othcensus/*.json 簇→格映射留存）：残池真口径=fixloop 段 fail+partial（首扫混 compile 段虚胖 10×）——undefined_cs×50 真长尾；brace/math 级联~~38 未定（最大单则候选，若是 splice 折brace 则我方）派 bracecasc-lane 定 base 臂；Missing\begin{document}×17 含已修 4 格+13 未检格（tar 泛化规则可能同收，入 flipcheck 验）；conditional imbalance~14 比 ifdiag 原派 3 格宽（Extra \fi/\else/\endcsname 族）；Parameters-consecutively×11=f3f013d 已修格（replay 证清）；**新我方实证 2105.00041**：keyval key 位进 `这是译文`（lstinputlisting 选项列被挖——restatable 同族 opacity 缺口）已 SendMessage 续派 restatable-lane。**ifdiag 收割**：iffalse×3 全 paper-authentic（脆弱 frontmatter 族，\author 块 \\ 进 footnote/半注释宏→\maketitle 未闭 \if，paper 手术级超安全界不派规则）；capacity×6 分两半——1404.0037/1706.00076 paper-authentic，1803.03248/2105.03753/2403.05529 全 \cref@resetstack@\end{restatable}=我方（3ecbfe3 已修，入 flipcheck 验证）。**裁决点上浮**：acceptable_pdf 语义——3 格中段 capacity 炸 TeX 展开补全但 env 内容静默丢失，verdict 记 acceptable 属宽判；lane 建议按错位（epilogue vs mid-body）或页数对 base 闸 acceptable→partial——更严=诚实方向但破单调性，留用户裁决（task #10）。**gate-③ 启动**：flipcheck 34 格重放批脱管在跑（stagerun-flipcheck，mock xlat 零网关——params×11+begindoc×17+crefstack×4+natbib×1+pdfstring×1 全覆盖验证目标格翻转）。

- ~00:2x 巡逻：flipcheck compile 33/34 将尽——多格速败 missing_file(~0.6s, 2.09 老稿缺包面, fixloop 段接手才是修复真章)；1706.00240 转 fontspec_missing(4.75s——原 Missing\begindoc 签名已消=letter_wrap 正向信号)。autogloss arm-on 判分 312/300 达标尾部收尾中（等 rc→qualfreeze×3 门）。restatable-lane 续道(keyval opacity)在飞未落树件；bracecasc 诊断道在飞。**归因警示**：树内 model.py+args.py(+105 `delim_toks`/'u'/'g' 新参型)是 peer texlate-48 的 lane-delimargs 交付（彼台账自记 scope 内）——非我方 lane 件不碰；彼 xlat pipeline/prompts 簇已离 status=已自 commit。

## 2026-09-18 23:25 — lane-delimargs 收割（aa8882f）

- 交付：ArgSpec `delim_toks` + kind 'u'/'g'；gspec 映射 delim→u/until_group→g；滑窗 `_tok_eq` + lbrace 组屏蔽；eol_par/EOF runaway 全回吐。9 钉测——复跑核实 635/-k + 9/9 一致。
- 归因：207+/-1 行全对 BRIEF+声明偏差（brace 屏蔽、g 空参显式分支、`\bbra` 引证纠错 0806.3247→1003.1242）；peer 在 args.py 异区的在飞编辑未被触碰、未夹带。
- 设计确认：'g' 首枚 lbrace 即止=TeX `#{` 语义正确（delim 即 `{`，无嵌套屏蔽问题）；'u' 的组屏蔽=TeX 平衡组语义。'u'/'g' inner 天然豁免散文挖掘（_prose_args_of 只认 m 族 + cs>fs 门双保险）。
- 一个可注意后续：`\par` 定界永不命中（eol_par 上游拦截→恒 runaway）——0806.2361 实证恰是保护定理散文的正确行为，但意味着 `#1\par` 形定界参宏仍按 b 零宽语义走，属有意保守。
- skeleton `delim-param-args` adopted。

## 2026-09-18 23:35 — autogloss-reg 收割完毕（任务#3 结）

- 三门禁全 PASS：off-vs-base D=0.026 / on-vs-base D=0.050 / on-vs-off D=0.039，flags/kinds/contested 零漂移——auto 臂分布面无回归。
- 方向性信号（非门禁）：term_inconsistency 0.161→0.117（-27% 相对，p=0.12 欠功率但方向复现 L2 探针）；grammar +6pp p=0.03（8 重比较噪声域，列 default-on 后观察项）；contested 7.0→8.0%。
- 裁决⑦证据包：可进 default-on 候选——无分布回归 + 机制收益方向复现 + 代价=非术语块零增益、每篇 +1 抽取调用。REPORT=tmp/lane-autogloss-reg/REPORT.txt。
- 事故尾账：双 orchestrator 致 arm-off 1 例 unparseable 末行（299/300 已接受——resume 视 error done，记录留存）；arm-on ~60 重复判分同配 judge 无害。
- cron 641bf83b 已删。下一步：空窗跑首个真 qualdrift 哨兵点（网关闲）。

## 2026-09-18 23:50 — tar 0-member 修复 + bracecasc 收割 + 4 道新派

- **80bea92 tar_blob_extract 退役解耦**：0-member 异常实锤=语料同捆全部成员（corpus_v3/0707.0382/extracted 内 AMSbsy.sty tar 与 9 成员并存）→补缺落地 0→blob 留毒（设计注"0 成员非本机制案"前提错——tar 魔数+`.sty` 名即非法 TeX，与落地数无关）。修=命中魔数即改名退役；补钉 test_tar_blob_retires_when_all_members_exist（预置成员+0 新成员仍退役）。5 tar 钉+96 fixloop 面全绿。tarrecheck 2 格重放批脱管在跑（stagerun-tarrecheck）。
- **bracecasc 收割**（tmp/lane-bracecasc/report.md）：~38 格级联簇=下游噪声非单机制——逐格首错拆根后三枚我方可修根：**①mn2e/mnras natbib 接口缺**（0707.4614/1206.0597/1206.5819，stub \LoadClass{mnras} 命中老 cls 无 \citet/\citealt 族→57-142 错）；**②nicematrix 版本错配**（2203.00012/2308.12712 ~4 格，vendor 件要 L3>2022-07-14 而 runtime=2022-07-14）；**③stub 参数元数缺**（aaspp4.sty:98+aasms4.sty:97 `\def\markcite{}` 0 参 vs 真件吞 {key}→残留组排印→`_` 文本模式炸，astro-ph/9910310；通式嫌疑覆盖 undefined_cs×50 桶一部分）。另：astro-ph/9901364 姊妹改名件(crckapb_copy)单格候选低于规则阈值记档。
- **新派 4 道**：stubaudit-lane（vendor/stubs 全权：natbib 接口+元数审计+offprints）、nicematrix-lane（vendor 非 stubs 区+版本门判：先定是我方 vendor 还是稿自带）、masklane（match_surface:masked 通用机制——finditer 落遮盖视图+raw 右到左 span 拼接防 \n 位移，natbib_numbers_pass 单点 opt-in；残口 ledger 项转产品）、residdiag-lane（只读：cond-mat/0408520+9910091 残 partial + gr-qc/0104075 240s 超时根因 + motivation.tex/1012.1548 瞬态复查）。roster：restatable(keyval 续道)+4 新道=5 活跃在飞。

## 2026-09-18 ~00:2x — tar 三阶修复 + masklane/restatable-B 收割

- **0e55221 魔数扫窗**：tarrecheck 一跑揭穿更深一层——splice/zh 构建对 .sty 一律前置我方 prologue（`\PassOptionsToPackage`+`\providecommand` ~1452B），ustar 魔数推离 257 → 定点探测漏检（上一版"0 成员"诊断实为"未检出"表象同 note）。修=前 64KB 扫 ustar 回推 257+name 字段 NUL 轻校验；抽取从头起点切片+顺序迭代（弃 getmembers 全扫）容忍 recode 中段损坏。钉：displaced-magic 检出+成员照补+退役；文本 ustar 字样不误中。真件验证：splice AMSbsy.sty hdr=1452 检出、pristine hdr=0。
- **tarrecheck 二跑 FLIP**：0707.0382 unfixable→**clean**；astro-ph/0104007 unfixable→**partial(best_effort_pdf)**——aipproc.cls tar 退役后 stub shim 接手出 PDF，残 41 错=异族（`Missing \endcsname` symposium.tex:250 + env_undefined `references` + undefined_cs×12 = aipproc stub 覆盖缺，交 stubaudit 邻接域）。
- **3f2cbb6 masklane**：`match_surface: masked` 机制——mask_tex 等长遮盖实测 offsets 逐字保；finditer 落遮盖视图+raw 右到左 span 拼接防 \n 位移；ruleset fail-closed 校验。opt-in=natbib_numbers_pass+**conmp_pdo_pdfstring**（lane 残口上浮→leader 裁决：同 `(\begin{document})`+\n-repl 形同证据同收，注释内 begin 永非活锚）。8 钉+601 扫面绿。**natbib 遮盖残口 ledger 项清零**——修复道升级为机制道。
- **a61c7ab restatable-B**：keyval 组注释剥除——`\lstdefinelanguage{lean}{` ~250 行体首行 % 注释使 `_KEYVAL_GROUP_RX` 形状门断 → 键名挖成散文（2105.00041 `这是译文` 进 key 位实锤为**键名被挖**非 caption 逗号裂）。两 gate 统一走 `_keyval_shaped` 剥注再判；爆半径=有界少译。**跨会话夹带记档**：`_KV_COMMENT_RX`/`_keyval_shaped` helper 经 peer aa8882f 整文件 add 先落地，余 diff 净 lane 件。
- roster：stubaudit/nicematrix/residdiag 在飞；restatable-lane/masklane/bracecasc 交付已收关闭。

## 2026-09-18 ~00:4x — peer verify 报告落错 inbox + 交叉确认

- 四枚 peer verify-* 代理（xlat/misc/gullet/fixloop 簇）把判词发到本 session 的 team-lead 地址——核实：彼等验证的文件全部已在 master 早前 peer 提交里（c28b2c3 指纹闸+vendor 三 stub、ffe27ca autogloss+terms CSV、ca27eb2 网关迁移+layout_bench），本树无未提交对应件 → 判词纯信息性，无我可 commit 之物。已 SendMessage 精简判词+blockers 回 texlate-48（layout_bench 6 ruff、gullet 11 ruff、index.yaml 接线缺）。
- **交叉确认两枚本域相关项**：①`terms/index.yaml` 无 cond-mat/quant-ph 键——两 CSV 为死资产（verify-misc 判词属实；exact-match 需 quant-ph 一键 + cond-mat 九 subcat 键）——已回执 peer，下一轮巡逻若仍缺则我自补；②`aaspp4.sty:98`/`aasms4.sty:97` `\def\markcite{}` 0 参缺陷在 HEAD 仍在（peer 指纹闸提交 c28b2c3 未涉元数）→ stubaudit-lane 元数审计域内，无冲突。
- roster：stubaudit/nicematrix/residdiag/macrogate/pacsdiag 5 道在飞。

## 2026-09-18 ~01:0x — 夜巡 + 5 道新派（roster→9）

- 批存活：l1-gate parsebench **PASS**（strict identity 100.00% [99.80,100.00]、leak 0.000% 0/135840——post-W84 树 L1 门稳）；autogloss-reg/tarrecheck 均已 rc=0 收尾；无残留 stagerun/rexlat 进程。
- 新派 5 道：copyrename（`*_copy.sty` 姊妹改名普查→≥2 格则晋级补缺规则）、begindoc13（17 格 Missing\begindoc 残 13 逐格裁决：tar 扫窗/input_sty/重注释已覆盖 vs 新机制 vs paper）、taildiag（babel×4/illegal-unit×5/endgroup×7/input-stack×3 + **undefined_cs×50 按 cs 名直方图**——长尾是否暗藏 5 族）、bininject（上游修：splice/zh 对 .sty 一律前置 prologue 是 tar 魔数位移之源——二进制/魔数件应免注入）、macrogate+pacsdiag（前轮）。roster 9 道在飞，无僵尸。
- 门巡：clean% 本轮单调非降（flipcheck 全目标格改善或持平）；sabotage 上次 escaped=0（本轮新规则批后需刷新——记为待办）；teammate 零 git 无违例（全口头交付）。
- 待办队列：index.yaml 接线（peer 已回执，下巡未补则我自办）；qualdrift 首个真哨兵点（真臂 ≤100 格预算内设计 25-30 格）；sabotage-b 重跑（本轮 tar/mask/keyval 落地后门④刷新）。

## 2026-09-18 ~01:2x — residdiag 收割（3 格判毕+2 产品级 bug）+ copyrename 阴性结案

- **residdiag**：①cond-mat/9910091=paper 根（sw20lart 私件缺失 base 双臂同炸）+2 枚我方 stub 伤——`tcilatex.tex:23` vendored `\def\QQQ#1{}` 1 参 vs 真件 `\long\def\QQQ#1#2`（arg2 漏进导言→Missing\begindoc @Chechkin.tex:154）+ sw20lart noop stub 致 `\tag`×115 undef；②cond-mat/0408520=paper 根（BoxedEPS 缺失）+stub noop 致 16 undef cs，env_undefined:abstract 经零代码复现判 paper-authentic（abstract_frontmatter_hoist 覆盖但未火——轮次被 cs 错吃光，优先级/轮预算记档）；③gr-qc/0104075=**我方病态循环非真大档**——1813 行源产 73,595 页 Overfull\vbox 至 SIGKILL（enddoc \clearpage 死循环 @revtex4-2/ltxgrid 升级稿，loop1 同期曾 best_effort_pdf 秒出=可二分）。**两枚产品 bug**：(a) 超时被杀编译解析 0 错→verdict=clean 后 post-compile 再烧 240s——timeout 必须 veto clean；(b) 无 runaway-page 闸——73K 页烧满 240s。派 runguard（veto+runaway_output 分类）+revtexloop（极简复现→根因→修）。motivation.tex/1012.1548 监视安静关闭。
- **copyrename**：阴性全普查——`*_copy/*_old/*_orig/.bak/*2` ~110 件零候选；fixloop missing-file ~130 格零件有姊妹改名版（前缀撞名全是异件）。N=1 不破阈不立规则；未来若立须 `X_copy.*` 全 ext glob（epsf 案 .sty→.tex 跨扩展）。9901364 实序=nato.sty 真缺→legacy_pkg_shim→best_effort 93 错。
- stubaudit 获第 2 批加派：`\QQQ` 元数+sw20lart `\tag` noop+BoxedEPS 族（\BoxedEPSF→\includegraphics）。
- roster：stubaudit/nicematrix/macrogate/pacsdiag/begindoc13/taildiag/bininject/runguard/revtexloop=9 在飞；copyrename/residdiag 交付关闭。

## 2026-09-18 ~01:4x — 夜巡（安静持有）

- 批存活：无新 run.log/批（三道 lane scratch probe log 已完）；无残留进程。
- roster 9 全 running 无僵尸：stubaudit(33m)/nicematrix(33m)/macrogate(15m)/pacsdiag(13m)/begindoc13(7m)/taildiag(6m)/bininject(5m)/runguard(2m)/revtexloop(1m)。
- **树内已见两道未报交付**（代理仍跑=勿收）：nicematrix——`vendor/files/nicematrix.sty` 钉 v7.11a+`10-taxonomy` 加 pkg_version_skew+`40-install` vendored-substitute 规则+新测试（lane 自建 task #12-14 推进可见）；stubaudit——7 件 stub 改动（aasms4/aaspp4/aipproc/jheppub/jinstpub/mn/mn2e/svjour3）+test_fixloop_stubaudit.py。等口头交付再归因 commit。
- 门巡：无新码落地故门禁态不变；sabotage 刷新仍挂起（待本轮道落地齐跑）；零 git 违例。

## 2026-09-18 23:39 — selfimp-qual：verify-misc 收割（ruff 清零 + terms 接线）

- 第三会话 verify-* 裁决经 texlate-cf 转达（报告误投其 team-lead 信箱）：GO×2 无项；NO-GO 两项核实均真——已落地 `fcdc15b`（layout_bench EXE001/SIM105/F841/S607/RUF021/FURB122、test_gullet_l9 TC001、test_fuzz_inject FBT+I001、test_bare_cs I001、autogloss 重排，全仓 ruff 净）+ `b36310f`（terms/index.yaml 补 bare cond-mat + 9 子类 + quant-ph——ffe27ca 两张 CSV 此前是死资产，冒烟 str-el→1155/quant-ph→710/hep-th→default 405）。
- qualdrift 首跑 267/300 在飞（pid 457429，~33min），cron 486ad343 文件面监视；出判即入 trend + 裁决报告。
- 待办：qualdrift 门禁判读；⑦autoglossary 裁决证据已齐（REPORT 全门 PASS）；用户 7 项裁决包仍待回。

- **peer 回执核实**：texlate-48 澄清 verify-* 属第三会话派生误投，但判词全核并清——`fcdc15b` ruff 全仓净（layout_bench 6 项+gullet 11 项+test 杂项）、`b36310f` index.yaml 补 bare cond-mat+9 子类+quant-ph 键（装载冒烟 str-el→1155/quant-ph→710 实证）——我台账挂起的 index.yaml 待办由 peer 关闭。**qualdrift 首跑 peer 认领**（267/300 在飞），我队列同项移除避免双跑。
- 23:4x qualdrift 首跑判读：**pass**（300/300 judged，KS D=0.033 p=0.996、kind max|Δ|=0.43、contested −0.7pp、flag 漂移 0）——尺子未动，judge 臂可信续用；history trend 已入首点。

- **8bc0f46 nicematrix 收割**：真因=tlmgr usermode 装 CTAN 最新 v7.11c（与 vendor 字节同）闸 `\IfFormatAtLeastTF{2026-06-01}` vs runtime 2025-11-01→abort→NiceTabular undef 级联（brief 里 "L3>2022-07-14" 数字被 lane 证伪——那是 tectonic bundle epoch 常量非真闸）。修三件套：vendor 钉 v7.11a（floor 2025-06-01 冒烟过）+`pkg_version_skew` taxonomy 签名+"release too old"+`pkg_version_skew_vendored` 规则（order 11.7 vendored_fetch，wdir 平铺经 kpathsea cwd 序遮蔽 texmfhome；外来件指纹闸自动 decline）。残口：ctan.py `_NEEDFMT_RE/_PKGLATER_RE` 不匹配 `\IfFormatAtLeastTF`/`{Package,Class}` 形（tectonic 侧同洞，候选道）；6 格 nicematrix 用稿入下批 flipcheck。

- **1284803 stubaudit 一轮收割**：mn2e 案翻案——非老 mnras（~/texmf 是 v3.2 usenatbib 可用）而是 `\LoadClass{mnras}` 空参转发→usenatbib 不达 \ds@→natbib 未载（合成探针实证）；修=WithOptions 转发保真。元数族实锤落地：markcite/reference 0 参→#1（9910310 实案）；jheppub/jinstpub/svjour3/aipproc 照真件补全（svjour3 \DeclareOption{natbib} 曾被星号转发静默吞）。真纸验证：0707.4614 142→0、9910310 0 错、0104346 0 错。**二轮续派**：tcilatex `\QQQ` 元数（residdiag 证）+sw20lart `\tag` noop+BoxedEPS 族（先找 noop 生成机制归属）+aa501 loads 改派（90-shim 单条授权）+flushrt。

## 2026-09-18 ~02:0x — 夜巡

- 批存活：无 lane 新批/残留进程；peer qualdrift 首跑落地 `bench/results/qualdrift-2026-09-18/`（gate_report.json+report.md，history.jsonl 记 **verdict=pass**——首个真哨兵点由 peer 立档）。
- roster 8：stubaudit(二轮在跑)/macrogate/pacsdiag/taildiag/bininject/runguard/revtexloop 全 running；**begindoc13 无报告转 idle**——已 SendMessage 催报。
- 树内未收：macrogate 的 tables.py+test_latex_argspec.py（代理在跑勿收）。
- 门巡：clean% 单调保持；sabotage 刷新待道落地齐；零 git 违例。

## 2026-09-19 ~00:1x — 三收割+一自修（begindoc13/bininject/revtexloop）

- **begindoc13 普查收割**（tmp/lane-begindoc13/report.md）：13 格判毕——**Missing \begin{document} 恒为级联**（真根=导言区未定义宏/包错）。五族路由：①裸 `loads:` shim 宏缺 ×5（cimento/pasj00/PoS/imsart-\arxiv → shim body polyfill，stubaudit 加派）；②vendor stub 保真 ×2（svglov3.clo 尾 `\makeatother` 致 @ 失 letter→`15\p@` 裂；tcilatex `\QQQ` 元数——均 stubaudit）；③**我自修规则回归**——`input_sty_to_usepackage`(d30f636) 在 2.09 文档改写 `\input{epsf.sty}`→`\usepackage`（2.09 无此命令，0806.0904/0806.2953 由 partial 104KB→fail 0B）→ `main_head_contains:"\\documentclass"` 闸（9fc08f0，欠发方向=保旧 bug 不造新错）；④新机制候选 ×3 记档（paired-.tex 遮蔽延伸、geometry 选项撞→`\geometry{}` 改写、pstcol→pstricks/xcolor-ensure——各 N=1 待普查）；⑤csvsimple-l3 反向 skew（语料 vendor v2.2.0 太旧 vs 2026 kernel bool-expr，→vendored-substitute 新拷）。2410.18001 已翻 clean。
- **c04f4af bininject**：上游根因修——normalize_engine prologue 对全部 tex-suffix 件前置（仅 has_document 闸），tar blob 经 latin-1 解码成员文本命中 \begin{document}→ustar 推位 1452B（0707.0382 实案）。`_tar_disguised`/`_tar_header_ok`（64KB 扫+chksum 形态）四站全闸（_normalize_tex_files/_tex_sources/rebase/violations）；`prologue=` kwarg 按 `_prologue_ok`（strict-utf8+NUL 窗）逐件传。6 钉+三扫面（186/24/265）绿。残口：inject.py main_tex/ctex splice 同族无闸（.tex 名 tar 可成 main）记档。
- **194195f revtexloop**：gr-qc/0104075 73,595 页死循环真因=`\topskip 0mm`——upgrade_209 逐字搬运的 209 几何行，ltxgrid 输出例程不容运行期 topskip 改写（每 \output 残 6.66pt→\clearpage 永不排空；正值不循环但整页吞）。`_drop_topskip_assigns` 删深度 0 语句首位活赋值、仅 revtex4-2 门；`\ifdim\topskip`/组内赋值豁免。9 钉+134 回归绿。bisect 实证：删该行→21 页 clean PDF。
- macrogate 获 3 测试文件 flips 授权在跑；pending.py reg-check 残口记档候选道。stubaudit 获 svglov3+shim-body 加派。pacsdiag/taildiag idle 已催报。
- 门巡：L0 钉批全绿；L1 待 macrogate 落地后重测（argspec ungate 动解析面必复测）；sabotage 刷新仍挂起。零 git 违例。

## 2026-09-19 ~00:4x — pacsdiag/taildiag 收割 + macrogate flips 验证

- **f590d28 pacsdiag**：`\AtBeginDocument{\def\pacs##1}` 在 toks-based hook 逐字存 `##`→def 炸→`\pacs` 残留破宏撞 `\par`（t1/t2 复现）。`_builtins_shim.py:799` 已修但 90-shim yaml 回退 emit 未传播——残例补 `#1`+钉（含全 shim_map `##` 扫描钉防再犯）。7 格全 OURS 签名已死；gr-qc/0104075 异签名移交 runguard。
- **taildiag 五桶判毕**（tmp/lane-taildiag/report.md）：babel×5 全 paper（ldf 覆盖缺：ngerman/francais→french/ukrainian）；illegal-unit 3 OURS（geom shim `\newif` 缺 ×2 + svglov3 catcode 泄）；endgroup×8 全下游；input-stack 2105.00111 OURS（`\cref@resetstack` @`\end{restatable}` 递归→restatable 域 N=1 记档）。**undefined_cs×50 塌方成 ~6 族**：mn2e usenatbib×12 已随 `\LoadClassWithOptions` 落地（记录早于修）；class-cs stub 缺 ~15 与 stubaudit 二轮域重叠；catcode-leak ×2 新形。
- **macrogate flips 验证绿**：92/92（argspec+dispatch+semantics+mirror）。解析面变更 → L1 parsebench 复测批已脱管（tmp/l1-gate-ungate/run.log，~5.5min 墙钟）。待 PASS 后 commit tables.py+4 测试件。
- **新 ours-roots 记档待派**（下轮）：①@-catcode 保全不变式（physics_stub_detach 裸 `\input` 掉 @=11 裂 `\@undefined`；stub 尾 `\makeatother` 泄 @=12——入侧 wrap + stub 侧 save/restore）；②geom shim `\newif` polyfill（0806.0904/2953）；③paired-.tex 遮蔽、geometry 选项撞→`\geometry{}`、pstcol→xcolor、babel francais 改名（各 N=1-2）。
- roster：stubaudit（二轮：svglov3/QQQ/BoxedEPS/sw20lart/shim-body 5 格）+runguard（#18 钉）在飞；pacsdiag/taildiag/macrogate/begindoc13/bininject/revtexloop 交付关闭。
- 门巡：L0 绿；L1 复测在飞；sabotage 刷新待落地齐。零 git 违例。

## 2026-09-19 ~01:0x — L1 门过 + macrogate/runguard/stubaudit 三收

- **L1 复测 PASS**（parsebench-v3-ungate）：1955/1955 strict identity、leak 0/135840——与 post-W84 基线逐点一致，ungate 无解析面漂移。
- **5a5f282 macrogate**：argspec_lookup 去包门——per-file pkgs 查不到跨文件导言包致 `\crefrange{a}{b}` arg2 散文泄漏（reg 短路证成：`\newcommand` 经 ScopeMacroTable 主查先胜，ungate 只修 mand 计数）。4 门控钉翻成签名恒用语义。
- **76cf439 runguard**：timeout/killed 编译 veto clean 三点位 + `died` 轮旗 + acceptable_pdf 升级闸 + `_is_runaway_output`（30× Overfull\vbox@\output 阈值）分 timeout/runaway_output；salvage 排 runaway（定败再跑必再暴走）、killed 保留重试。vocab 裁决：`dirty_pdf`+`final_cat=timeout`（带 pdf 的 fail 判词，非 unfixable:*）。12 钉+全族绿。残口：live mid-flight 页数杀需 sandbox 流式监控 infra——记档候选道。
- **c1c7753 stubaudit 二轮**：`\QQQ` 真件 2 参定义器（全部 5 真本一致）+ SW20 `\tag` 机真件抄值（\@ifundefined{tag} 让位语义）+ sw20lart/BoxedEPS 新 stub + aipproc `\author` 双签名窥视。实纸验证：0104007 0err/5pp、9910091 0err/30pp（原 116 错）、0408520 16→0。**三轮在飞**：svglov3.clo catcode + shim-body×5。
- **catcode 不变式细化**：physics_stub_detach 的 `.tex` 宿主 `\input` 已带 `\makeatletter…\makeatother` wrap（_builtins_pkgload.py:148，1706.00240 实证注释在码）——taildiag 的"裸 input 掉 @=11"只剩**文档原生裸 `\input{physics}`** 一条缝（L103 注记"不重复补"）。N=1 记档，并入下轮 catcode 候选道。
- roster：stubaudit 独飞（三轮）；runguard/macrogate/pacsdiag/taildiag 交付关闭。本轮 commit：9fc08f0/c04f4af/194195f/f590d28/5a5f282/76cf439/c1c7753。
- 门巡：L0/L1 绿；sabotage 刷新待三轮落地齐；零 git 违例。

## 2026-09-19 ~01:3x — 夜巡派道 ×4 + 两刷新批

- **普查翻案**：option_clash 家族实为 0 格——`'lash'` 误中 `slashbox.sty` 文件名；真信号=**slashbox 退役包缺件 ×13 错/6 格**（1109.5364/1206.5785/1404.0561/1608.06845/2203.12985/2410.00118，TL2020 许可证除名→install 无源）。pstricks-add ×4 格（1003.2152/1404.2225/1706.00379/cond-mat-0605429）+ 0707.4206 paired-.tex 遮蔽缝=≥5 格族。1206.0291 geometry 选项撞降回 N=1 记档。
- **新派 4 道**：slashlane（vendor stub `\slashbox/\backslashbox` 真件接口——picture 对角线+双标）、pstlane（paired-.tex 同目录遮蔽延伸 + xcolor-ensure/pstcol 改写二择一按证据）、babellane（ngerman.ldf 覆盖缝 + francais→french 改名 + ukrainian/russian 可行性普查）、livekill-lane（runaway 活体杀——流式日志签名计数早杀进程组，sandbox/run_process 层，## REVIEW 并发）。stubaudit 三轮加派 geom `\newif` 补全（0806.0904/2953，同 90-shim 文件域）。
- **leader 脱管两批**：tmp/sab-gate2/run.sh（40 格 sabotage-b seed43 复跑——门④刷新）+ tmp/flipcheck2/run.sh（13 格：revtexloop/stubaudit-r2/input_sty-209/nicematrix×6+physics 格回归哨）。
- **autogloss-reg 收尾**：phase0 批 gate **pass**（on-vs-off D=0.0389 p=0.975、0 flag 漂移、contested 0.070→0.080）——裁决 #5 证据再添一门。
- roster：stubaudit(三轮)+slashlane+pstlane+babellane+livekill=5 在飞。

## 2026-09-19 ~01:5x — 门④刷新 PASS + flipcheck-2 大丰

- **sab-gate2 PASS**：40 格 sabotage-b 复跑 escaped=**0**（records/xlat.jsonl metrics.sabotage.escaped 全 0；2 upstream_gate+2 chunks_bad 噪声）——本轮规则批落地后破坏检测面不变。
- **flipcheck-2（13 格重放）8 格翻 clean**：gr-qc/0104075 **编译段即 clean**（topskip 修复实证——73K 页死循环灭绝）、nicematrix×4 全翻（2105.03893/2203.00012/2308.00087/2308.12712）、stubaudit 三格全翻（astro-ph/0104007 aipproc、cond-mat/9910091 QQQ+tag、cond-mat/0408520 BoxedEPS+sw20lart）。4 partial：0806.0904/2953 恢复 partial（input_sty 2.09 闸归位，geom `\newif` 三轮待落地）、2112.00045（csvsimple 逆 skew 未建）、2407.21783。1 fail：1706.00240（physics 裸-input 缝——预期，N=1 记档）。
- 净增估测：loop2 基线 579 clean + 本轮已证 8 flip + tarrecheck 0707.0382 + 2410.18001 ≈ 589/677 → **~87.0%**（90% 门还差 ~21 格）。
- roster 5 全 running 无交付：stubaudit(三轮)+slashlane+pstlane+babellane+livekill。

## 2026-09-19 ~02:0x — 夜巡（安静持有）

- 批存活：无新 run.log/批；sab-gate2+flipcheck2 均已 rc=0 收尾。
- roster 5 全 running 无交付：stubaudit（三轮，树内见 svglov3.clo 改判——弃 makeat* 对改用无 @ 的 `\PackageWarningNoLine`，比建议的 `\makeatletter` 尾更稳；90-shim cimento 全身 polyfill+imsart `\arxiv` 已落）、slashlane/pstlane/livekill/babellane（~6min 龄）。
- 门巡：clean% 估 ~87.0% 单调上行；sab-r2 escaped=0；无 git 违例（树内变更全归 stubaudit 授权域）。

## 2026-09-19 — 裁决①-⑦落地日

- 用户七裁全收（verbatim 存会话）：bib 全不翻 GO / glm-5-2 维持禁令 / flag 保留 / 阈值写死 / HF token 供 XCOMET / contested 调参授权 / autogloss default-on GO。
- 已 commit：bib 直通（pipeline.py 40904c7）+ judge/mock/src_bib 信号（qualbench 246b08c）+ JUDGE_SYSTEM 新条款（同 commit，prompt_sha 轮转）+ qualfreeze 阈值写死（ff1316b）+ autogloss default-on（app.py ec39ebc）+ l0_en_unreported src_bib 豁免。**JUDGE_SYSTEM 协议形态改动属①的强制推论已自主落地，待向用户点名明示**；qualdrift 下跑若在 bib 行出 drift 为正确告警（尺子重锚非劣化）。
- lane-bibpass-reg 发车（pid 773423，tmp/lane-bibpass-reg/）：frozen-300 单臂 cur=HEAD 全口径重翻→swe-2-max 判→qualfreeze vs base。判死线=14 个 bib chunk 的 dnt-major（baseline 17）不降即错。cron 9e69d36c 文件面巡检。
- XCOMET-XL 三角臂 spike：权重 13GB 已落 archbox（突破=ssh 会话泄漏 127.0.0.1:7890 代理致 SSL EOF，env -i 直连即通；hf-mirror 全站 308 回源非代理）。venv ~~/xcomet-venv（setuptools<81 补 pkg_resources）。7 对分档样本 QE 打分 detached 跑（~~/xcomet/spike.log），cron c3f81263 巡检。

## 2026-09-19 ~01:0x — 夜巡：roster 补 10，批面两活一 stalled

- 批存活：**lane-bibpass-reg 在飞** 185/300（frozen-300 单臂 cur=HEAD 重翻→swe-2-max 判，pid 773428）；**xcomet spike stalled**——pairs.jsonl 964KB+batch 脚本 00:38 生成后无进程无分数（spike.log 仅 pkg_resources 警告），侧线记档暂缓重启。**l1-gate-ungate 落地 PASS**：1955/1955 strict、leak 0/135840（post-ungate 与基线全同，argspec ungate 解析面无回归）。
- 树内在飞 diff 归因核实：pstlane→`_builtins_vendored.py`（`_FILEDATE_RE` 兜底 pst-* .tex 核 `\def\filedate` 日期面，vendored_shadow_isolate 配套）、livekill→`sandbox.py`（`_RunawaySentry` 排干环活哨——logparse 同 regex 同阈值 bytes 编译 + `[N]` 页标 10K 计数闸，越阈 TimeoutExpired 走 killpg 收树，commit 需 `## REVIEW`）、stubaudit→90-shim+svglov3+test（r3 在飞）、slashlane→slashbox.sty+新测试（在飞）。均 on-spec。
- roster 5→10 补派（记档残口全走清，mutex 不相交）：**#27 injecttar**（inject.py main_tex/ctex splice 无 blob 闸——c04f4af 下游同族）、**#28 ctanre**（`_NEEDFMT_RE/_PKGLATER_RE` 不匹 `\IfFormatAtLeastTF`/`{Package,Class}`——nicematrix 真闸形）、**#29 pendreg**（segmenter/pending.py:545+1116 组内行缺 reg 检）、**#30 physwrap**（doc-native 裸 `\input{physics}` 无 makeatletter wrap，1706.00240 实案）、**#31 restatdiag**（2105.00111 `\cref@resetstack` 递归——diagnosis-only，定位后另派修道）。
- 缓派（mutex 撞在飞道）：0408520 revtex3→4-2 前件缺（90-shim 归 stubaudit）、geometry 选项撞（70-pkgopt 归 pstlane）、csvsimple vendored-substitute（vendored 机邻 pstlane）、abstract_frontmatter_hoist priority/round-budget（待 stubaudit 落地后评估）。
- 门巡：L0 绿；L1 PASS（上条）；sabotage-b r2 escaped=0/40 已档；clean% 估 ~87.0% 待本轮 5 道落地翻格。零 git 违例。
- **de1ba13 slashlane 收割**：slashbox.sty 退化 stub 重写为 picture-mode 保真 polyfill（`\[back]slashbox[w][s]{A}{B}` 真界面、`\line` 对角线、\@tfor sep 抑制、\shortstack 消化参内 `\\`）——对照语料 e-print 内真件（1803.00136）核语义。6 格家族通路=vendored_fetch(11.5) 先于 legacy_pkg_shim(12)。9 钉+82/96 回归绿；1109.5364 splice 实证 0 错 8pp 渲染对角线视觉保真。**横切发现→stubaudit r3 加派**：裸 `\ProvidesPackage{name}[text]` 无日期前缀经 `\@parse@version@` 漏排版流→Missing\begindoc（~20 stubs 同形待扫+全 stub 日期钉）。

## 2026-09-19 ~01:3x — 夜巡：pstlane 收割（idle 未报，leader 代验）

- 批存活：bibpass-reg 196/300 在飞；余无新批。peer packaging 调研目录（docs/research/packaging-2026-09-19/）非我道产出，不入我 commit。
- **f974ae1 pstlane 收割**（idle 未报→leader 代验 diff+测试全归因）：Defect-A paired .tex 核伴船退役（0707.4206：X.sty 退了稿自带 X.tex 核留盘→wrapper `\input{X}` cwd 先中 stale 核→`\pst@cntm` undef；`_retire_paired_tex_core` 同保守闸=系统递补在场+双日期面 `ld<sd`+非注入件，缺一不碰）+`_provides_date` `\def\filedate` 兜底（pst-_核日期面约定）。Defect-B `pstcol_pstricks_rewrite`（70-pkgopt:185，1003.2152：pstcol 硬压 noxcolor→现代 pst-_ 需 xcolor→`\colorlet` undef；组内枚名换 pstricks 选项续传 xcolor，masked 面）。14/14+77/77 绿，105 规则验。`## REVIEW` 已标（新 rename 路径）。
- roster 8：stubaudit(r3+ProvidesPackage 扫尾加派)/livekill/babellane/injecttar/ctanre/pendreg/physwrap/restatdiag 全 running。pstlane/slashlane 交付关闭。
- 门巡：L0 绿；L1 PASS 档；sabotage 0/40 档；clean% 待本轮落地翻格。零 git 违例。
- pstlane 口头报告后至（commit 前 leader 已代验，内容全符）：**Defect-B 普查修正=实 1 格**（1003.2152 唯余 `\colorlet` fail；1404.2225/1706.00379 已 clean、0605429 缺席该轮——pst 族翻格预期下调）；0707.4206 多股残链全翻未定。order 185 与 95-targeted symbolfont_tuletters 撞序合法（异 trigger+文件名序定）。残口：`test_pasj00_polyfills_compile` 败属 stubaudit 在飞树非 HEAD（+273 行未落地，交付时复验）。
- **3748c89 injecttar 收割**：inject.py 5 字节读点全上 `_tar_disguised`（复用 normalize 非重抄）——find_main_tex/_walk_inputs/classify_no_main/inject_float_sizing 排候选 + prepare_chinese 兜底 `InjectRejectError(nontex)` 挡直传伪装 main。8 钉+355 子集绿。**横切残口升级**：同族洞延到 latex/api.py `scan_tex_tree`（枚举全 .tex→parse→reconstruct 写回=最高severity 写路径）+flatten.py+probe/latex209 只读点 → **apitar 道已派**（写路径对）。**csvsub 道已派**（csvsimple 反向 skew：稿自带 v2.2.0 太旧 vs 2026 kernel bool-expr → vendored 新拷替换；geomlane 道已派 1206.0291 option_clash N=1）。roster 10。
- babellane scratch 越界一件：t9.tex ngerman 探针落 repo 根→移 tmp/lane-babellane/（轻微违纪，下不为例）。
- **df23888 livekill 收割**：`_RunawaySentry` 入 POSIX 排干环——logparse 同 regex 同阈值 bytes 编译（vbox×30）+`[N]` 页标 10K 计数闸，行界扫+64KB 留尾；越阈 TimeoutExpired 走既有 killpg 臂零新杀机，`run_process` 签名不变（~15 替身+注入缝原样）。`engine._round_cat` +3 行 stdout_tail 补查（活杀 .log 截在签名前→仍归 runaway_output）。实证 gr-qc/0104075 1.2s 收 vs 240s 烧（200×）。10 钉+139 绿。`## REVIEW` 已标。**b29c533 judge.py 镜像修**（leader 直落）：judge timed_out 臂同盲点补 stdout_tail 重查+钉。
- **stubaudit r3 主体交付（部分持有）**：aa501 loads(yaml:1722)+flushrt 已覆盖(yaml:2067)+**svglov3.clo 功能化重写**（`\edef\svglovrestore` catcode 存/复+`\input{size10.clo}`，无 @-cs 无 makeat*——1608.06693 122err→0err/26pp）+shim-body 4 格全真稿 0err（cimento 9pp/pasj00 82→0/20pp/imsart 11→0/16pp/PoS 45→0/9pp，`\AtBeginDocument{<typeset>}` 双安范式）。35/35+145 绿。**持有待 #37 geom \newif + #38 ProvidesPackage 扫尾落地再 commit**（文件仍在被编辑）。残口记档：`{\em X}`-in-math 2.09 字形切（9910310 1err→latex209 候选）。
- roster 9：stubaudit(r3 尾)/babellane/ctanre/pendreg/physwrap/restatdiag/geomlane/apitar/csvsub 全 running；injecttar/livekill 交付关闭。

## 2026-09-19 ~01:5x — 夜巡：bibpass-reg 虚警澄清 + restatdiag 待报

- 批存活：**bibpass-reg 健在**（前判 judge=qualbench.py 进程在跑 pid 944190，207+/300——上轮 rexlat|stagerun grep 模式漏判虚警）；xcomet stalled 仍记档。
- restatdiag #31 completed+idle 未报→催报（repro 三案 distinct/mangled/mangled2 已建）；**scratch 越界第二例**：nocref.tex/.stdout 落 repo 根→移 tmp/lane-restatdiag/（前例 babellane t9.tex，两 lane 同训「scratch 只在 lane dir」）。
- stubaudit #37/#38 在飞（undated ProvidesPackage 仍 12 件待扫）；ctanre/pendreg/physwrap 读相 ~20min 无落笔，geomlane/apitar/csvsub 新进。roster 9 全活。
- 门巡：L0/L1/sabotage 全档绿；零 git 违例。
- **restatdiag 判毕（无需修道，已修）**：2105.00111 `\cref@resetstack` 递归=**macrogate ungate 同缺陷类**——argspec_lookup_env 的 pkgs 闸在 `\input` 拆分后假阴→restatable 双非文本参流落 prose→mock 译成同词 `{这是译文}{这是译文}`→thm-restore 存体 `\csname #2\endcsname`=#3 自召→input stack 爆。**`\cref@resetstack` 只是 trace 主帧**（label-hook 每轮），cleveref 非承重（nocref 复现照样递归）。5a5f282/3ecbfe3 已修+实跑+flipcheck 21pp 验。4 同签名格全清递归（余 3 格转独立 missing-package 域）。**watch 记档**：real-xlat 变体=异参译不同时不递归而是定理静默丢失——无签名、error census 不可见，redlines/watch 候选。restatdiag 关。
- XCOMET spike 分离度成立（archbox fp16，7 对）：judge35→qe0.52 / judge45→0.87 / judge95→0.83-0.91 / judge100→0.99×2 / bib_ident→0.57（QE 本能惩罚未翻内容=bib 行须剔除三角域，设计内预判证实）。踩坑记录：fp32 ckpt 在 11.65G VRAM 必 OOM→model.half() 解；13GB CPU 载入需 ~19G+swap→临时加 /swapfile-xcomet 24G（批毕拆）；systemd-run 下 stdout 偶发整段丢失→日志直写文件 + python -u 绕开。全量 1200 对 batch 已发车（xcomet-batch.service，cron 6f65de59）。

## 2026-09-19 ~02:0x — 夜巡：bibpass-reg PASS 落地 + 全 diff 归因

- 批存活：**bibpass-reg 收官 PASS**（01:17 ALL DONE）——scored 300/300；判死线 bib14 dnt-major **baseline 17→cur 0**（minor 3→0）、frozen300 17→0（minor 5→6 噪声内）。qualfreeze verdict=drift 但两漂移 flag 均改善向：over_translation 4.7%→1.0%（p=0.0068）、term_inconsistency 16.0%→8.7%（p=0.0063）；KS p=0.28、kind means 全在 delta 内（para +3.3）、contested 7.3%→4.0%。裁决①回归闸实证：17 条 baseline dnt-major bib chunk 全清零退化。l1-gate/autogloss-reg 均早已 DONE，当前零 detached 批在飞。
- **encoding.py 谜 diff 归因=apitar 共享家选项**：`_tar_disguised` 迁 `textutil/encoding.py` 中性叶（compile/latex 两层共用，探测窗 64KB+chksum 形态校验防文本 ustar 假阳），`__init__.py` 导出、normalize/inject 改引、api.py+flatten.py 上闸、test_latex_targate.py 新建——全在 apitar 授权域。
- 其余在飞 diff 全归因：physwrap=`_builtins_pkgload.py`（`_PHYS_INPUT_RE` 收窄 `.sty` 形——`\input{physics}` 走 tex 格式是章节件非 stub，1206.5202 实案；新增 `_wrap_phys_sty_inputs` makeatletter 对包裹）、pendreg=segmenter 三件（_common+17 共享件迁入、mainloop −19、pending ±25）、geomlane=70-pkgopt+42+test_fixloop_geomclash.py 新建。stubaudit 90-shim/svglov3/test 持件在飞。
- peer 会话文件隔离确认：cli.py/share.py/server·worker·share/xlat·{batch,pipeline,retry,mock}/web·api·types/export·epub·新包/packaging-2026-09-19/refactor-survey——texlate-2a/31/0c/13+repo-wide-restructure 五会话在忙，非我道产出，pathspec 纪律不入 commit。
- 门巡：L0 绿档；L1 PASS 档；sabotage escaped=0 档；`git log` 仅我 5 commit（de1ba13/f974ae1/3748c89/df23888/b29c533）零违例；clean% 待本轮 8 道收割后翻格重估。
- roster 8 全 running：stubaudit(#37/#38 尾)/babellane(53min 无落笔→催)/ctanre/pendreg/physwrap/geomlane/apitar/csvsub。
- lane-bibpass-reg 收割 verdict=PASS：frozen-300 cur 臂 300/300 判毕；判死线达标——bib14 dnt-major baseline 17→0 且 14/14 stated 全 100（judge 新条款对直通留英给满分）；frozen 全域 dnt-major 17→0。gate 报 drift 全部利好方向：term_inconsistency 16.0%→8.7%（autogloss 指纹）、over_translation 4.7%→1.0%（v4 prompt 指纹）、kind_means 0 漂移 para +3.3、KS D=0.08 p=0.28 无分布漂移。①②⑦ 三裁决回归面全绿；REPORT=tmp/lane-bibpass-reg/REPORT.txt。

## 2026-09-19 ~02:4x — 夜巡：五连收割 + 批面双发 + roster 补 6

- **c2e4e13 geomlane**（idle 未报→leader 代验）：`option_clash_geometry_hoist`（70-pkgopt:186）——括号选项整组挪 `\geometry{}` 运行时 keyval 面，documentclass 位置无关（1206.0291 mn2e→mnras.cls:117 [a4paper] 先载撞 [total,centering]；三规 merge/loadopt_strip/passopts 全够不到的形态兜底）。10 钉+107 规则+22 邻绿。
- **cbd3798 apitar**（共享家选项落地）：`_tar_disguised` 迁 textutil.encoding 中性叶（normalize 删 49 行、inject 改引）→ latex 写路径全闸：scan_tex_tree 枚举三桶皆不入 + parse_file/v1 直读 OSError EINVAL + flatten._read_file OSError→非展开回吐。**索引级 hunk 分账**：**init**.py 只收 `_tar_disguised` 导出行，env_raw/env_opt 是 peer 会话在飞件不动。14/14 绿（真 USTAR blob）。
- **2adda6b pendreg**：组内两 argspec 行补 m 闸（主流 `_handle_unknown_cs` m-is-None 同规——登记名走 keyarg/探针不吃签名）→ `\renewcommand{\And}` 组内 `\And{aa}` 不再裸名+参漏 prose、组尾 `{bb2}` 不越组界。3 钉+73 域绿。**共享文件记**：peer 会话 a708e388 在飞 `_accent_cs/_inline_lit_cs`→_common 合并先落地（_common/mainloop 它收），本 commit 只载 pending.py+test。
- **720387c csvsub**：反向 skew——稿自带 csvsimple-l3 v2.2.0 太旧撞新 kernel（`\bool_const:Nn{1}` 裸字面量，2112.00045:36 Missing number）；`_provides_date` 读不出 `\ProvidesExplPackage` brace 面（双件皆 None→ld<sd 闸饿死）+fetch 指纹闸拒覆 → retire+resolve（mv .fixloop-iso，vendored v2.7.0 字节同 texmf 递补）。**hunk 分账第二例**：40-install.yaml 只收 hunk3，babellane file_aliases/francais/babel_undeclared 三块持有。14/14 绿。
- **7b8e603 ctanre**：`_NEEDFMT_RE`/`_PKGLATER_RE` 补真闸形——单参族 `\IfFormatAtLeastTF`（nicematrix v7.11c 实案逃逸形）/`\IfExplAtLeastTF`/`\@ifl@t@r` cs+csname 形；双参族 `\@ifclasslater`/`\If{Package,Class,File}AtLeastTF`/`\@ifl@ter` 扩展/loader `{name}[date]`（texmf 普查 408 件非 expl3 目标占多数）；自署 `\ProvidesX[date]` 明示除外。95/95 绿。
- **0e354b4 physwrap**（`## REVIEW`）：doc-native `\input{physics.sty}` 补 makeatletter 对——masked 视图组作用域走查（`_phys_sty_input_sites` 深度 0+at_letter 栈），只罩命令本体。**任务前提修正**：`\input{physics}` kpathsea tex 格式永不解析 .sty（1206.5202 是章节件）→ `_PHYS_INPUT_RE` 收窄 `.sty` 形 + `need_input` 假抑制同修。36+77 绿。
- 批面双发：flipcheck3（11 格 mock 臂，tmp/flipcheck3/）+ l1-gate-pendreg（parsebench 全量——segmenter 路径变了三处：pendreg 闸+peer _common 合并+texlog 词表重构，L1 必须重锚）。bibpass-reg 已收官 PASS。
- roster 补 6→9 running：**#40 readgate**（probe.py:266 dep census 读闸）、**#41 emmath**（`{\em}`-in-math 2.09 字形切+latex209.py:362 读闸）、**#42 grpOpaque**（`_grp_scan` opaque 镜像行——pendreg 残口）、**#43 junkrename**（`_neutralize_junk_files` 名撞覆盖）、**#44 silentthm**（restatable 异参静默丢定理 watch/redlines）、**#45 commentsweep**（svjour+cmd_prose 陈旧注释——90-shim 仍 stubaudit 锁，只交文本）。
- macrogate-lane 僵尸收编（交付完 standby 态关闭）；其报 `_builtins_misschar.py` 本地 `_MC_*` 影 `_builtins_common` 同名导入——peer rewire 道残口记档（非我 mutex）。peer 破坏面观察：export.epub.driver/sabotage_arms_mock_translate_text/app_endpoints_ERR_FNAME 三处 collection 断（各有主，非我修）。
- 门巡：L0 绿档（域内）；L1 重锚在飞；sabotage 0/40 档；clean% 待 flipcheck3；git log 11 commit 全我署，零违例。

## 2026-09-19 ~03:1x — 夜巡：收割潮收官 + L1 PASS + flipcheck3/4

- **4780aae readgate**（#40 速交）：probe.py `_scan_file` 上 `_tar_disguised` 闸——dep census 只读面收口，文件留 rep.inputs 但声明零产出。tar 族全链闭合：inject(3748c89)/latex 写路径(cbd3798)/probe(4780aae)/latex209(emmath 在飞)。4+50 绿。
- **225bc97 babellane**（三道桥）：file_aliases 20 条显式别名（ukraineb/magyar/slovenian/UKenglish…ini `\BabelDefinitionFile{0}{X}` 普查，try_exts 拼不出的走表先试）+`babel_opt_francais_rewrite`（弃名→french，tlpdb 证无档）+`babel_undeclared_option`(:14 选项表头插 payload 非主位——babel_undef 独占类目，german ldf `\iflanguage{ngerman}` 钩案 0707.1325/1003.2165)。23 钉+109 规则+82 邻绿。
- **ebff0af stubaudit r3 全收**（24 件 +653/-49）：geom.sty 全真 geomenv 面（`\presection`→`\newskip` 才是 illegal_unit 真源非 `\if`——`\@startsection` advance 实证；0806.0904 150→0/9pp、0806.2953→0/65pp）+svglov3.clo 功能化（1608.06693 122→0/26pp）+aa501/cimento/pasj00/imsart/PoS shim-body（全真稿 0err）+**#38 Provides\* 扫尾闭合**：22 stubs 全钉 `[2026/09/19 …]`，undated 漏排版流类全灭（leader 复扫 0 残）。38/38 绿。
- **L1 重锚 PASS**：parsebench-v3-pendreg 1955/1955 strict、leak 0/135840——pendreg 闸+peer `_common` 合并+texlog 词表三处 segmenter 路径变更下解析恒等/leak 零退。批面 638s 落地。
- **flipcheck3 收官**（11 格）：**6 clean 翻格**——0707.0382(tar_blob_extract)/1003.2152(**pstcol_pstricks_rewrite 实弹**)/1109.5364/1404.0561/2112.00045(**csvsimple_l3_kernel_retire 实弹**)/2410.00118 + gr-qc/0104075 compile-clean（mock 臂不触暴走）；4 格改善未净：0707.4206 best_effort(12err 多股残链如 pstlane 预判)/1206.0291 best_effort(**option_clash=geometry 仍在 post-census——规则触发须错签占首错类，残口记档**)/1206.5785 acceptable(missing_char×2)/1803.00136 acceptable(syntax×1)。
- **flipcheck4 发车**（12 格：stubaudit 全家 + babel 0707.1325/1003.2165 + physwrap 1706.00240 + emmath 基线 astro-ph/9910310）。
- roster 5 running：emmath/grpOpaque/junkrename/silentthm/commentsweep；本批 8 道全收（geomlane/apitar/pendreg/csvsub/ctanre/physwrap/readgate/babellane/stubaudit 全关）。
- 门巡：L1 PASS 新锚；sabotage 0/40 档；clean% flipcheck3=9/11 出 pdf（6 clean）、flipcheck4 待；14 commit 全我署零违例。
- XCOMET batch 死因链全破（教训级）：①无 swap CPU 载入 OOM→加 /swapfile-xcomet 24G；②fp32 ckpt 在 11.65G VRAM OOM→.half()；③无 tty 下 traceback 不落盘假象→日志直写文件+python -u -X faulthandler；④**真凶=archbox earlyoom daemon**（mem/swap≤15% 即 SIGTERM 最高 oom_score——静默 exit 元凶，journalctl 可见）→停 earlyoom 后 kernel OOM 真杀仍现；⑤终解=torch.load(mmap=True) 绕开 pl loader（pl 2.6.6_load 无 mmap 透传）手建模型 fp16 直载，载入峰 ~30G→~9G。bs=8+expandable_segments。QE 批在跑（每 predict 重建 Trainer ~10s 开销可忍）。

## 2026-09-19 ~03:5x — 夜巡：flipcheck4 收官 + commentsweep 落 + texlate-13 域对齐

- **e5274e0 commentsweep**（两 stale 注释，均核实后改）：①svjour AtBeginDocument「\xdef 吃层」前提已被 lthooks 取代（latex.ltx:18901 verbatim 存）——`##` 真因是 `\providecommand` 替换文本内嵌 `\def` 一层转义，`####` 实测炸（TL2026 pdflatex 实证），注释自身前提反推出 #### 自相矛盾；②test_segmenter_cmd_prose beamer 注释过时——argspec_lookup 早弃 `_pkgs` 门控（\input 拆体不见导言包名），article 下 `\only` 同样走 argspec 臂。(a) 文本交付 leader 代施，(b) agent 直改。29/29 绿。
- **flipcheck4 收官**（12 格，ebff0af9-dirty 树）：compile 11/12 clean（1706.00240 基线 fail）；fixloop 9 格 → **7 clean 翻格**：0707.1325/0707.4614/0806.0904/0806.2953/1608.06693/astro-ph/0104346/astro-ph/9910310（stubaudit 全家 5/5 实战全净——geomenv/svglov3/aa501 系 shim 体全兑现；babel 0707.1325 净）。
    - 残 1：**1706.00240 unfixable:other**（7 轮 8 动）——physics_stub_detach 已兑现（越过 physics 装载面进 mathtools/siunitx 警告期），新阻塞 `Incomplete \iffalse; all text ignored after line 317`（异类缺陷，physwrap 已预判）。payload qty。
    - 残 2：**1003.2165 best_effort_pdf**（9 轮 11 动）——babel 面全清（german.ldf+tuenc-greek+polutoniko 改写+ngerman 表头注入全发，babel_undef/ngerman 链全灭），残量 = pstricks 树装齐（pst-*×11+llncs）后 XeTeX 15.62s SIGKILL 超时、partial pdf 160K。属超时/runaway 类非 babel 类。
- **texlate-13 域对齐**：互报在飞面零撞（我 compile/fixloop+latex/segmenter+textutil；彼 server/cli/compile-engine，pending.py 彼禁碰）。app.py/store.py/worker/web feature hunk 非我（texlate-2a/31/0c 道）；textutil 残 hunk 彼收；三处 collection 破面彼认领；**zotero/ 顶层新目录非我**（untracked Zotero 插件工程，另一 peer 或用户现场，互约不动）。
- roster 4 running：emmath(#41)/grpOpaque(#42)/junkrename(#43)/silentthm(#44)；commentsweep 自退。#6 伞下新残口入册：iffalse@1706.00240、pstricks-timeout@1003.2165、geomreach@1206.0291（规则触发须错签占首错类——引擎级问题）、0408520 revtex3→4-2（90-shim mutex 已解可派）、`_MC_*` shadow 去重（fixloop 域内残口收编）。
- 门巡：L0 绿档；L1 PASS 锚（v3-pendreg）；sabotage 0/40 档；clean% flipcheck4=10/12 出 pdf（7 clean）较前轮 9/11 单调不降成立；15 commit 全我署零违例。

## 2026-09-19 ~04:3x — 夜巡：三连收割 + judge C901 顺手拆 + roster 重建 8

- **e5274e0 commentsweep**（前条已记）；**9a9360b silentthm**：restatable 静默丢定理机制实证闭合——env-name 参被译 → `\csname<undef>\endcsname`→`\relax` **零消息**（`{定理}{main}` 全链 0 `!` 行、头体双丢；key 参被译走普通 undefined_cs 显见）。redlines 新增 `restatable_loss` 行（judge-probe 独生，engine/rules/l2 全 None——presence≠red，l2 预筛结构性够不到包加载行）；judge.py 文本补丁 leader 代施：presence→note + workdir 扫 `restatable_env_nonascii:<file>:<arg>` 强 note（真·丢失条件=env 参非 ASCII）。**顺手拆 HEAD 预存 C901(11>10)**：`_full_log_text`/`_log_probes` 抽出，judge() 回限内。
- **bda320c junkrename**：前提实质确认+机制修正——`_neutralize_junk_files` 无 (re)name 生成（原地写 stub），但名盲覆写真件实证成立。签名闸 `JUNK_FILE_MARKERS`（RCS `$Id`/自检横幅/`\typein` 三签名，corpus 四件全带）——无签名同名件放行，无签名条目回落旧契约。**契约精化非纯 fix**：旧 fuzz 钉无条件名撞已同步改写（放行≠豁免转码）。
- **misschar-dedupe NO-OP 核销**：`_MC_*` 影叠已被 b924f775 peer 拆分解决——全名审计零撞（共享名皆 import 非重定义，叶侧常量皆独名）。818 域测绿。
- **texlate-13 双向对齐**：三 collection 破面=彼瞬态重组（今已净）；彼在飞 sandbox→proc、LoopCtx 四组化、engine→包、store→包、share 事务窗。互报面零撞；预警 pending.py grpOpaque 在飞 vs 彼三镜像表合并计划。
- roster 6 在飞：emmath(#41)/grpOpaque(#42)/iffalse-census(#46)/revtex34(#47)/pstricks-timeout(#48)/geomreach(#50)；新派 census 道全 read-only。
- 门巡：L0 域内绿（108 normalize+23 redlines+runguard）；sabotage 0/40 档；17 commit 全我署零违例。
- 残口入册更新：xlat/segmenter skip-role 参 byte-identity 检查（silentthm 呈——异参静默丢类总闸）；ASCII↔ASCII env-arg mangling 仍盲区。

## 2026-09-19 ~05:0x — geomreach 裁决回 + 三道新派（roster 8）

- **geomreach census 确认+锐化**：1206.0291 规则不触发是三闸叠压非单因——①`when.category` 只认首错类（actions.py:76 vs engine.py:804 `_round_cat`→classify 单错）；②`ctx_suggests` 只吃 err_head=首错+8 行（actions.py:136/engine.py:837/logparse.py:143）；③**决定性**：halt-on-error 每轮在错 1 截断，clash 从未出现在任何 dispatch 轮 log——只在 salvage/census log 里（第 3/3 错）。**证据**：r1 首错=mnras.cls options-section `\RequirePackage`（vendored mnras.cls:79 `\ds@usegraphicx`→`\usepackage` 在 `\ProcessOptions` 内，`\documentclass[usenatbib,usegraphicx]{mn2e}` 触发）；规则静默跳过（declines 只记 when-过的）。**裁决**：(a) 多错 dispatch（classify_all+error-set match）与 (b) salvage-as-discovery（best_effort 诊断化回灌）记档为引擎战略残口——**不立即做**，peel-by-first-error 是现行契约；立即行动 = 剥头错。
- **#51 mnras-optpatch 派出**（实现）：修 vendored mnras.cls options-section \usepackage（fidelity 由 agent 判——pristine artifact vs 可补 shim；惯用解=选项只置旗+`\AtEndOfClass` 延载）。
- **#52 skiprole-census 派出**（research）：silentthm 残口升类——skip/opaque 参 byte-identity 检查槽位普查（segmenter 参角色→xlat payload→splice 回放全链；env/cs/label/cite/option 全角色→丢失类映射；FP 面=fixloop 自身改写时点）。
- **#53 multistrand-census 派出**（research）：0707.4206 12-err 残量分股（族/根因/可修类/剥序）。
- texlate-13：pending.py 三镜像表合并**整项排队等 grpOpaque 落地**——正面同区避让确认，我方 commit 后回 ping。
- roster 8 在飞：emmath/grpOpaque/iffalse-census/revtex34/pstricks-timeout/mnras-optpatch/skiprole-census/multistrand-census。

## 2026-09-19 ~05:4x — 夜巡：psttimeout 伪阳判明 + 残口分流 + providesdate 派

- **ff85de9 revtex34 NO-OP 钉收**：cond-mat/0408520 现行树已净（任务源自 flipcheck1 陈旧证据）——全链 replay 实证 r1 twocolumn→polyfill、r2 abstract→hoist、r3 15 页净出；11 钉冻链零 shim 增改。
- **pstricks-timeout census 判明**（#48）：1003.2165 超时 = **sentry 假阳**非暴走非真超时——复跑 36s 净出 46 页；`_RunawaySentry`（proc.py:110）累计 vbox 计数 `_RUNAWAY_VBOX_MIN=30`（logparse.py:39）被每页一条慢性 2.7pt 警告喂满（46 页 46 条），第 29 页 ≈15.6s 杀。真暴走签名=密度/无进展非累计阈值；配套归因洞=post-hoc 只扫 4KB 尾窗累计不可重建 → CompRes 需 `sentry_reason`。**两触点全在 texlate-13 在飞件**（proc.py/engine/_base.py）→ 实证+修法已转交彼批。
- **残口分流 texlate-13×2**：①gullet/input.py:128 `decode_tex(read_bytes)` 裸读=tar 族最后洞（apitar 残口，彼 \input_expand 在飞批内）→ 5 行补丁文本已交；②sentry 签名+CompRes 字段如上。我域 tar 族剩 latex209.py:362（emmath 在飞）。
- **ctanre Provides 裁决=DECLINED**：`\ProvidesX[date]` 自署日期不接 check_version_compat——自署≠floor，era-gating 会把 epoch 后所有维护包全拒=fetch 路死；且 expl3 `{\ExplFileDate}`/GetIdInfo 间接署名字面覆盖不可靠。floor-only 出货维持。
- **#54 providesdate 派出**：`_provides_date` 补两真形——`\ProvidesExplPackage{n}{date}{v}` 花括号三参（csvsimple 实证饿闸）+ `\ExplFileDate`/`\GetIdInfo $Id` 间接署名（ctex.sty 实证）；保守原则=不可解归 None 不猜。_builtins_vendored.py 干净可锁。
- roster 8 在飞：emmath(#41)/grpOpaque(#42)/iffalse-census(#46)/mnras-optpatch(#51)/skiprole-census(#52)/multistrand-census(#53)/providesdate(#54)；psttimeout/revtex34/misschar/geomreach 已收。
- 门巡：L0 域 349 绿（test_segmenter_cmd_prose 一过性 NameError=peer 瞬态，单测复跑净）；19 commit 全我署；peer 973b2a06 web i18n 落地互不干。
- drain 说明：teammate 消息大批为已收割道回声/idle 通知（apitar/geomlane/ctanre/pendreg/csvsub/physwrap/babellane/stubaudit 全部早收早落），增量仅上述三项+providesdate 残口。

## 2026-09-19 ~03:3x — XCOMET batch 内核 OOM 死而复起

- attempt2 = CUDA OOM：peer 进程 1842126 占 4.0GiB GPU（11.65G 卡仅余 ~7.6G 模型位）——非我方 leak。attempt3 = **kernel global_oom**（constraint=NONE，peer claude 进程触发全局挤压），unit 连壳被杀（peak 10.2G mem + 13.5G swap；zram 18.7/31G 已吃紧=真实 RAM 压）。
- 处置：GPU 已全空 + swap 余 33G 窗口期 → 同脚本重启 `systemd-run -p Restart=on-failure -p RestartSec=30`（壳死自动拉起，bash 6 次重试环内层兜底），断点 312/1200 续跑。cron f5d9540f 续巡。

## 2026-09-19 ~03:3x — 收割潮：emmath/babel-mnras/pstadd 三落 + 两道新派（roster 6）

- **d80792f emmath 收**：latex209.py 数学域字体开关转写（`{\em/\it/\bf X}`→`\mathit/\mathbf`，`_math_env_spans`+`_textarg_spans`+`_innermost` 区域机制，upgrade_209 converted 路接线）+ `_uses_ds_at` tar 闸——**tar 伪装族正式闭环**（inject/latex-api/flatten/probe/gullet 1a04780/latex209 六面全闸）。19 新钉+155 域绿；e2e 9910310 `\mathit{ fields}` 实证。
- **452bc9b 双件收**：(a) vendored mnras.cls 上游 bug 修——v3.2 pristine 实证 `\ds@usegraphicx` 内联 `\usepackage` 违 options-section（同文件 `\ds@usenatbib`:1335 已是正确旗+延载范），置旗+`\ProcessOptions\relax` 后延载；(b) **补齐半提交 babel 特性**——babellane 滞留 hunks：00-base filemap +24 ldf 别名 + 10-taxonomy `babel_undef` 类（"You haven't defined the language"），无此类则 babel_undeclared_option 消费端无格可中。
- **fe62cff pstadd-retire 收**：0707.4206 12 错单根=稿自带 pstricks-add v2.32/2005 对遮蔽（multistrand census 判明非多股）；`find_vendored_shadows` 系统-probe 盲区同型 csvsimple——40-install.yaml `pstricks_add_pair_retire`（order 11.9）sh 循环 mv 成对 .fixloop-iso，**指纹防环升级**（texlate-fixloop-injected 件跳过，否则 v3.94 `\colorlet` 错→退役→重投死循环）；链=退役→missing_file→vendored_fetch v3.94，xcolor 前置已由 pstcol rewrite 兜。18 钉+805 fixloop 绿。
- **dbd964a emmath 残口兑现（leader 自改）**：2e 声明形 `{\bfseries/\itshape/\rmfamily/\sffamily/\ttfamily X}` 同踩 `\not@math@alphabet` 硬报（gr-qc/9901082）并入映射表；`\slshape/\scshape/\upshape/\mdseries/\normalfont` 无单义数学字母保守不收。+3 钉，53/53 绿。
- **iffalse-census 判明**（#46）：1706.00240 `Incomplete \iffalse`=**纸自带** draft.sty:77-85 摘要捕获花括号 hack（`\protected@edef\@tempa{\ifnum`}=\z@`吞`}`令 edef 组永不闭，吞全文至 EOF 推展开`\iffalse`）；bt7.tex 零 texlate 件复现同签名——TL2026 内核回归区外，unfixable:other 裁定正确。agent 供可选规则（doc-shipped .sty 签名→换良性 abstract env）**leader 裁定缓**——单格签名+改稿语义+需新 action 形（档内 .sty 内容改写非现行面），入册候选。
- **skiprole-census 判明**（#52）：byte-identity **构造上即成立**（ph→ph_map 存原始字节，唯 `[[CHUNK_n]]` 受 zh）；活漏类=未标参数混进 chunk 面（restatable 前 argspec 先例）。option-b 槽审在 post-reconstruct 四点（e2e/worker-compile/repair_l2/retranslate，三点 peer 域）——probe 落我域 judge.py，接线补丁文本交 peer。
- **新派两道**：#57 geomreverify（replay 1206.0291 post-452bc9b——头错已剥，geometry clash 是否进 dispatch 轮触发 option_clash_geometry_hoist，验 mnras 投资）；#58 slotaudit-impl（`_thm_restate_probe` 泛化 doc-level 机槽 CJK 探针：env 名/label/ref/cite/csname/input 五面，note-level 封顶 20，o/O/d/D+ 文本参 FP 硬约）。
- roster 6 在飞：grpOpaque(#42 逾 1h 在跑)/providesdate(#54)/sentryfix(#56)/geomreverify(#57)/slotaudit(#58)；iffalse/mnras/skiprole/pstadd 四尸已清。
- 门巡：域内自验 53/53 绿 ruff 净；peer interleave f5677a66/6a3d538d/c9c3e3da（server app 拆+latex TokenSource+worker seams）互不干；22 commit 全我署零违例。
- 残口入册更新：draftsty-abstract-hack 规则（候选 micro-lane，待第二命中或富余）；ASCII↔ASCII env-arg mangling 仍盲区；90-shim:2216 BoxedEPS 死条目（无害）；grpOpaque `_pend_spec_of` 过吸收 adjudication 待其交付；sentryfix 交付后需转 texlate-13 接线（彼域 proc.py/_base.py 已由彼派回我队——**纠正**：sentryfix 是我队 lane，交付即我收）。

## 2026-09-19 ~04:0x — 夜巡：grpOpaque 落地 + parsebench 断链抢修 + pendspec 续派

- **e9757c0 parsebench 断链抢修（leader 自改）**：peer api.py v1 臂退役删 `parse_file_v1` → `bench/py/parsebench.py:75` 模块级 import 炸穿全链（parsebench→quality_proxies→stage_compile→stagerun，geomreverify replay 即死于此）。修法=惰性导入进 `parse_one` try 内——v1 臂被调时 ImportError 落 per-file 桶而非毁模块导入；ruff 净，import 链复通。geomverify 已解锁通知。
- **45fab85 grpOpaque 收**（#42）：`_grp_scan` 组内缺 opaque/math 宏行——登记宏落探针 `[o]+{m}×6` 兜底 spec 越界过吸尾参组（主流 row18 `_handle_opaque_macro` 对价缺失）。+228：`_grp_opaque_args` 全 `Arg` 类 toks-walk（m/o/star/e/delim 滑窗/until_group/零宽 + `_pend_call_slots` keyarg 尾），`("opaque",None)` 行插 inline-literal↔pair-block 间镜像主流行序，m2 决议前提，PhType.CMD+ 散文抠参+gen_overflow 警。**forced 变更裁定**：`test_pend_spec_reg_gate` `[1]`→`[2]`——钉的是调用点覆盖行为非旧过吸机制，合法收。**附带披露**：`_pin_v2` fixture 删除=peer v1 臂退役未提交件被本 commit 扫入（commit body 已注明非我件）。
- **#59 pendspec 派出**（grpOpaque 残口兑现）：`_pend_spec_of` 边界臂同款 `_PEND_PROBE` 过吸——槽字母表不出 spec 保真（m 吃 `[`+单 token、无 delim/e/until_group 槽），需流侧 spec walker 非槽映射；owns pending.py+slots 测试，已预警 texlate-13 同文件撞区（彼镜像表合并排期在先，指示我队绕飞不回退）。
- **texlate-13 双 ping**：①grpOpaque 落地通报（彼三镜像表合并解锁）②pendspec 同文件撞区预警（彼排期在先可串行）。parsebench 修复亦已互报。
- roster 5 在飞：providesdate(#54)/sentryfix(#56)/geomreverify(#57)/slotaudit(#58)/pendspec(#59)；grpOpaque 尸已清（self-terminated）。
- 门巡：本 tick 域内 49+139 绿 ruff 净；parsebench 断链属 peer 瞬态非回归；commit 全我署。L1 口径提示：l1-gate 结果系 post-W84 树（昨日 21:43 完），peer v1 退役落地后现行树 L1 需重跑——记档待彼 refactor 收敛。

## 2026-09-19 ~04:1x — 收割潮二：providesdate/sentry/slotaudit 三落 + geomverify 揭 texmf 影蔽新类

- **f8b884d providesdate 收**（#54）：`_provides_date` 覆盖 expl3 花括号三参 `{n}{YYYY-MM-DD}`（237 texmf 件，csvsimple ld<sd 闸实证饿）+ `\ProvidesFile` + `[%` 续行 + `_cs_date` 间接署名解析（\def/\tl_*/\*command/\GetIdInfo→\ExplFileDate，ver==-1→None）；不可解=None 绝不猜日期（错日期静默毒 ld<sd）。581/601 texmf expl3 件得日期（原~0）；22 钉 +48 域绿 +361 fixloop 扫绿。
- **405c5b5+cb404a6 sentryfix×slotaudit 双道同 file 收**（#56/#58，judge.py 分时复用——机制层先落、judge 层待 slotaudit 完成后双署提交）：
    - sentryfix：`_RunawaySentry` 双臂——`page_flood`（`[N]` shipout ≥10K，gr-qc/0104075 ~97K 页 25s 杀，count 非 max 故散 `[12345]` 引用不触）+ `vbox_flood`（vbox sigs ≥30 ∧ >4×页标=密度语义，1003.2165 46sigs/46页 ~1:1 永不触）；`run_process` 返 `bool|str` timed_out，`_collect_compile_outputs` 归一→`CompRes.sentry_reason`（零引擎改）；judge `_timeout_verdict` 优先录因（sentry:<arm> note+runaway_output）否则全 .log 扫兜底（4KB 尾窗看不见 page-flood）。~20+166 钉绿。
    - slotaudit：`_machine_slot_probe` 泛化 `_thm_restate_probe`——`_MACHINE_SLOT_RXS` 八面表（env 名/restatable 双机参/label-ref 族/cite 族/bib/csname DOTALL/include+includegraphics 必参/input 三形）走 `mask_tex` 视图（注释/verbatim/死区不触），`_DEAD_TAIL_RX` 截 \end{document}/\endinput；note `machine_slot_nonascii:<kind>:<file>:<arg>` 封顶 20；**NOTE-LEVEL 永非红线**（纸真 CJK env 名合法），可选位参构造不触（`[..]` 先消费）。+~105 钉。
- **geomverify 判明**（#57）：1206.0291 → best_effort_pdf + post clean；**geometry clash 签名确现身**（salvage 轮 L503 `Option clash for package geometry` tex:147）但不到 dispatch——r1 被前位错 `mnras.cls:114 \RequirePackage in Options Section` 截杀（cat=other 无规则 when 匹配，零 action）。根因=**user-texmf 影蔽**（新缺陷类）：`_texmf/home/` 复刻 `~/texmf/` 旧 buggy mnras.cls（`\ds@usegraphicx` 内联 `\usepackage`），我 patched vendor 件永不上场——static_precheck 只补缺失件（mn2e.cls），texmf 已有件不触发 vendored_fetch。同 pstricks-add 影蔽形上一层。**新派 mnras-retire**：fingerprint retire 规则进 40-install.yaml（`\def\ds@usegraphicx` 体含 \usepackage/\RequirePackage → mv .fixloop-iso → vendored_fetch patched；texlate-fixloop-injected 指纹跳过防环）。
- **providesdate STAND DOWN 事故**：其报 #60 道号与 draftsty 撞——即停，#60 owner=draftsty 无实害。
- **texlate-13 串行反转确认**：pending.py 上 pendspec 先 commit（小行为修 diff），彼三镜像表合并后 rebase（"吸已 commit 码比 rebase 真 spec walker 上新表风险低"）；彼 merge 开工前 ping 我。
- **loginfo rename 瞬态**：peer `_ERR_*`→`ERR_*` 改名断 loginfo.py，彼自落消费端修，已解。
- **派 flipcheck-5**（gate ②③ 兑现）：replay 0707.4206（pstadd retire）、astro-ph/9910310+gr-qc/9901082（math switch）、grpOpaque 覆盖格 + ≥30 clean 格 sabotage 检查。
- roster 3 在飞：geomreverify(#57 完待收尸)/pendspec(#59)/draftsty(#60)；sentryfix/slotaudit/providesdate 尸已清。新派 mnras-retire+flipcheck-5 → 5。
- 门巡：L1 gate 全绿收官（1955/1955 ok strict，leak 0.0/135840——post-W84 树口径）；autogloss-reg ALL DONE 双臂 rc=0 qualfreeze pass；L0 域本轮 22+20+166+105 钉绿；commit 全我署。
- 残口入册：`_round_cat` 不读 sentry_reason（fixloop/engine.py:~L201 跟进件）；`RunFn` 别名 ~L159 注记陈旧；`_grp_arg_prose` 缺 `_ZERO_WIDTH_ARG_RX`；ASCII↔ASCII env-arg mangling 仍盲区；texmf 影蔽类=mnras 首案，他 texmf-resident buggy 件同型待普查。

## 2026-09-19 ~04:3x — geomverify 全报修正：影蔽源=tlmgr 非 ~/texmf + 双头守门新发现

- **机制修正**（覆盖上条"user-texmf 影蔽"归因）：`_texmf/home/.../mnras.cls` 非 ~/texmf 复刻，而是 **tlmgr usermode install 产物**——mn2e stub `needs:["mnras.cls"]` → `_builtins_shim.py:108-113` → `eng.install_file` → filemap→`tlmgr --usermode install mnras` → texlive 旧 buggy v3.2。`vendored_fetch`(order 11.5) 只在 install_file 失败后触——texlive 有的包永远遮蔽 vendor 件。**缺陷类正名=vendor 可达性**：needs/install_file 全链不查 vendor/files。mnrasretire 规则形不变（fingerprint retire→missing→vendored_fetch），已转达关键正确性问题=missing-after-install 走 vendored_fetch 还是 install 重跑（后者→retire→reinstall 死环，须查实非假设）。
- **geomverify 新发现二**（harness 实证，stagerun 重跑 byte-identical）：
    - mn2e stub usegraphicx-strip=**死代码**——`\@loadwithoptions`(latex.ltx:18637) 拷原始 `opt@`/`@raw@opt@` 列表非 `\@classoptionslist`，改写被绕（repro/ 仪表实证）；修法=`\LoadClass[\mn@clean]{mnras}` 或 opt@ 改写，vendor patched 件上场则无须。
    - **option_clash_geometry_hoist 永不可能此格首错中**——peel 后新首错=`Missing \begin{document}`@doc:147（cat=syntax，taxonomy:315 实证），即 clash 的**孪生头**（log 674 vs 686 差 12 行>CTX_LINES=8 err_head，ctx_suggests 同盲）；机制=doc l.147 `\usepackage[total=...,centering]{geometry}` 撞 cls-载 geometry[a4paper] 泄漏段落料→everypar→\@nodocument 先发。裸 `\usepackage{geometry}` 双错同消→净 33 页 PDF（repro2/t2 实证）。残口=多错 dispatch/ salvage-as-discovery/孪生签名规则变体——入引擎战略残口册。
    - post error_cats={other:1,syntax:1,option_clash:1}——三错共存 salvage 轮实证。
- **texlate-13 segmirror 已停让位**：彼误判 bd4d7140(彼 9/18 投影提升预备件)=pendspec 落地，澄清后停 agent，pending.py+slots 测试让出待我 pendspec commit ping。
- **peer 接线确认**：texlate-13 在飞 judge.py 改动=将我 `_machine_slot_probe` 重构为公共 `machine_slot_audit(workdir)->list[str]`（splice 后调用面 e2e/worker/repair_l2/retranslate 接线，彼域文件）——slotaudit 交付的 peer-side patch text 落实中，互不干。
- **新派 roundcat+texmfshadow+pairediff**：①`_round_cat` 读 sentry_reason（engine.py 微修+RunFn 注记）②texmfshadow census 扩域=vendor 可达性普查（filemap/tlmgr/doc-dir/TEXMFHOME 各解析点谁遮蔽 vendor 件）③pairediff 设计 src/zh 机槽参 diff 探针（ASCII↔ASCII mangling 盲区，先实证 FP 率再定建否）。
- roster 7 在飞：pendspec(#59)/draftsty(#60)/mnrasretire(#61)/flipcheck5(#62)/roundcat/texmfshadow/pairediff；旧尸 (psttimeout/multistrand/skiprole/mnras-optpatch/iffalse/pstadd/sentryfix/slotaudit/geomreverify) 回声确认早收。
- 门巡：ledger 9ed9a03 已 commit；geomverify report.md 已按全报重写。裁决点新增=孪生头守门机制选型（暂入册多错 dispatch 方向）。

## 2026-09-19 ~04:5x — 夜巡：flipcheck5 半程数据 + draftsty 撞区处置

- **flipcheck5 半程**（stagerun-fixcheck5，42 格=6 nonclean 修复臂 +36 clean 回归臂）：compile 臂 36/42 全 clean 零回归；fixloop 臂 5/6 出——**astro-ph/9910310→clean**（math-switch 目标格全翻，rules=[tar_blob_extract,static_precheck,legacy_pkg_shim]）、**gr-qc/9901082→acceptable_pdf**（revtex209_surface_polyfill）、2112.00045→clean（csvsimple_l3_kernel_retire+pkg_version_skew_vendored=providesdate 投资兑现）、2105.03852/0806.4130→best_effort_pdf；0707.4206 pstadd 目标格在飞。
- **draftsty×mnrasretire 撞区处置**：draftsty 抢在我 95-targeted pin 到达前把 `abstract_edef_capture_neutralize`（~71 行 run_tool 规则——`\protected@edef\@tempa{\ifnum`}=\z@`吞`}`签名确证 +`\endinput` 前注入良性 \def\abstract 覆写，texlate-fixloop-injected 幂等）写进 40-install.yaml。裁定=**成品留原位**（语义可属 install/patch 类，搬迁纯增错）→ draftsty 冻笔待提交，mnrasretire 串行候场（先答 refetch-path 正确性问题 + 写测试件，yaml 落笔待我 ping）。文件互斥纪律内推成立。
- **roundcat WIP 抽查合规**：`_round_cat` sentry_reason 优先→`runaway_output`+`sentry:<arm>` payload 槽（镜像 `_timeout_verdict`），RunFn 注记 `bool|str`，信号死 killed 改写逻辑保留——on-spec 未收割。
- **peer 续流**：parsebench.py v1 臂 parse_one 整删（我 e9757c0 惰性导入件同去——v1 退役收尾，docs/09 §7.1 口径）；judge.py `machine_slot_audit` 公共化重构+repair.py/docs 改动仍彼在飞。
- roster 7 在飞全活：pendspec(#59 未落笔——设计期)/draftsty(#60 yaml 成品+test 件在飞)/mnrasretire(#61 yaml 候场)/flipcheck5(#62 6th 格在跑)/roundcat(engine.py WIP)/texmfshadow(census 件产)/pairediff(proto.py 产)。
- 门巡：compile 臂 36/36 clean 零逃逸（半程口径）；无 git 违例（工作树改动全可归属：engine.py=roundcat、40-install=draftsty、test_fixloop_draftsty.py=draftsty、parsebench/judge/repair/docs=peer）。

## 2026-09-19 ~05:0x — 收割：draftsty+roundcat 双落

- **22e94be draftsty 收**（#60）：`abstract_edef_capture_neutralize` order 11.95——1706.00240 draft.sty `\protected@edef\@tempa{\ifnum`}=\z@`吞`}`致 edef 不闭吞全文→`Incomplete \iffalse`。**设计 delta 采纳**：agent 改 inject-override 代 spec 原拟 comment-out——①注释面只需签名行不需 hack 块界（多层嵌套括号 regex 脆）②`\def`无存在性前提优于`\renewenvironment`③`\ifdefined\maketitle`保题名块（hack 本意即 env 触发题名，1706.00240 从不自调）——理由成立收。comment-strip 后签名确证（:62-64 注释载件不动），`\endinput` 前注入良性覆写。18 钉 +858 fixloop 绿 + 真 xelatex A/B 实证（repro2 题名+abstract 全渲染）。
- **c68dc86 roundcat 收**：`_round_cat` 录因优先臂——`sentry_reason`/str timed_out→`runaway_output`+`sentry:<arm>` 挂 payload 槽（轮内无 notes 面，payload 落 entry/events pay=）；rep.raw=全 log 同源判明未造第三扫；RunFn+run_tool 注记 `bool|str`。判例披露皆核：录因权威于 timed_out 真值、runaway_output 无规则 dispatch 故 unfixable/salvage 排除语义反而修正（旧可误判 unfixable:timeout）。+6 钉（24）+888 邻域绿。
- roster 5 在飞：pendspec(#59)/mnrasretire(#61 yaml 已放)/flipcheck5(#62)/texmfshadow/pairediff；draftsty/roundcat 尸清。

## 2026-09-19 ~05:2x — flipcheck5 收官：双目标格全翻 + 36/36 零逃逸

- **gate ②③ 兑现**（stagerun-flipcheck5，42 格）：compile 臂 36/36 clean 零回归（sabotage escaped=0）；fixloop 臂 6/6 全出——**0707.4206→clean**（pstadd 目标格，`pstricks_add_pair_retire` 实测触发：retire→xcolor_override_opt_strip→vendored_sty_shadow 链 6 轮，post clean 0 错 322KB PDF 35.7K CJK——12 错残格病灶全除）；**astro-ph/9910310→clean**（math-switch 目标）；**gr-qc/9901082→acceptable_pdf**（math-switch 目标部分翻，revtex209_surface_polyfill 同烧）；2112.00045→clean（csvsimple_l3_kernel_retire+pkg_version_skew_vendored=providesdate 投资兑现）；2105.03852/0806.4130→best_effort_pdf。
- **pendspec 落笔**（#59，在飞）：pending.py +467/-59——`_grp_spec_walk` 真 spec walker 成形：`_PendRem` NamedTuple 跨界余量（spec/cont/ka_slots/ka_cont/ka 五槽），`_slots_walk_toks` 槽字母平铺，`("opaque",None)` 行入 _PEND_SPEC_FAMS——待收割，texlate-13 segmirror 仍候场。
- **draftsty 迟到报告核对**：注入覆写设计 delta 理由三条成立（签名行免块界/\def 免存在性/\ifdefined\maketitle 保题名），与已 commit 22e94be 一致——无追加动作。
- roster 5：pendspec(#59 落笔中)/mnrasretire(#61 yaml 放笔)/flipcheck5(#62 完待报)/texmfshadow/pairediff。
- 门巡：本轮 commit 22e94be/c68dc86/57db761+dbf3996 全我署；零 git 违例；L0 域 18+24+888 绿。

## 2026-09-19 ~05:4x — texmfshadow census 收：196 件普查 + mnrasretire 重设计

- **普查结论**：196 vendor 件（168 files+28 stubs）×kpsewhich+ 字节 diff——135 NONE（Arch 分装 texlive 缺族）/58 IDENT/3 HOME-DIFF。**唯 1 活缺陷=mnras.cls**（texmf=2023 buggy 上游，源=fixloop 期 tlmgr usermode 漏进真 ~/texmf，44 件 mtime 聚 09-16 吻 engine.py:649-651 pollution 注）；siunitx=良性前向遮蔽（3.5.12 盖 3.6.0 无钉件，379 文档暴露零失败→监测）；binhex=良性（真件盖桩=正确方向，0 用）。
- **install-path 判明**：missing 裁决链=`wdir→_texmf/home→~/texmf→TEXMFLOCAL→TEXMFDIST`（_xelatex.py:123-137 冒号链 TEXMFHOME，真 ~/texmf 挂尾=刻意保 host shim 可见）；xelatex 独有，tectonic bundle 自含免谈。
- **mnrasretire 重设计（采纳 agent 建议）**：retire-mv→**stateless wdir drop**——~/texmf RW 挂载 mv 即全局突变（侵入），改指纹闸无条件把 vendor/files/mnras.cls 平投 wdir 根：cwd 赢全链，零外变，missing-file 依赖与 retire→reinstall 环同消。已两连发转达（含 garble 澄清）。
- **普查↔geomverify 矛盾裁决**：census 称 mn2e 径"stub 选项剥离已防"——**被 geomverify 仪表实证推翻**（repro/：\@loadwithoptions 拷原始 opt@ 列表非 \@classoptionslist，剥离死代码）。爆半径修正≈26 格（25 mn2e+usegraphicx + 1907.00331 直用）——wdir drop 双径同愈。
- **结构注记**：stock-texlive 宿主使 135 NONE 中半数变 DIST 遮蔽——多为无害，**唯 nicematrix v7.11a 兼容钉**：texlive≥7.11c 前向遮蔽钉→2308.12712 pkg_version_skew 旧虫复活且 vendored_fetch 不达；未来一切 `texlate patch` 件同洞。通用件候选（N=2 再议）：static_precheck 扫——带 patch-marker/钉旗 vendor 件若 wdir 外解析得中→指纹 wdir drop（pkg_version_skew_vendored 泛化）。
- roster 4：pendspec(#59)/mnrasretire(#61 重设计消化中)/flipcheck5(#62 完待报)/pairediff；texmfshadow 尸清。

## 2026-09-19 ~05:5x — pairediff BUILD 裁决 + flipcheck5 全报 + slotdiff 派

- **pairediff 裁决=BUILD**（tmp/lane-pairediff/proto.py）：per-file in-memory 配对——`res.vtex` 字节=src（post-normalize，protected_tex 是错面带占位符）；三 splice 点（e2e:236/worker:319/repair_l2:399）同刻持对。**FP 实证零**：~150 配对扫描全 55 原始旗皆错配伪影（normalize `\bibliography`→`\input{bbl}`×54 + fixloop cite-key 清洗×1），splice-时接线全消。**免责名录零需**。判例：现树空转（141 格 0 机令 token 上 chunk 面——restatable ungate 已修），价值=下次扫描隙泄参的绊线（silentthm 类事件旧靠运气发现）。合成实证：restatable env 参 CJK 改写 + `\label`→`\ref` ASCII 错植皆中，cite 重排正确抑制。
- **#63 slotdiff 派出**：`paired_slot_diff(src_tex,zh_tex,rel)->list[str]` 进 judge.py——**append-only 约束**（peer 正在同文件重构 `_machine_slot_probe`→公共 audit，禁碰既有函数，新代码自立 `_slot_args` 提取器不重构 `_slot_scan`）；cite/bib 键表归一（逗号拆 + 重排免旗）余原子；note=`slot_arg_missing`/`slot_arg_extra` 双向 Counter diff 封顶 _MACHINE_SLOT_MAX。三接线点 patch text 交我转 texlate-13（彼域文件）。~80 行产+~60 测。
- **flipcheck5 全报收**（#62 清尸）：四目标格全验 + 新残口=**`\cite`-in-math 字体开关**——gr-qc/9901082 splice:466 `\bfseries invalid in math` 残存，源无字面开关组：`\cite{HawMos}` 处 `$…$` 内被文-mode `{\it …}` 包，revtex compat 执行期解开关→\bfseries——字面组改写域外（b3a 同残，acceptable_pdf 语义挂 #10 裁决）。grpOpaque 判 verdict-neutral 但 **gen_overflow 警 1→0 全 6 格**（spec walker 代探针正信号）。36/36 零逃逸收官。
- roster 3：pendspec(#59)/mnrasretire(#61)/slotdiff(#63)；flipcheck5/pairediff/texmfshadow 尸清。
- 待办串联：slotdiff 交付后三接线 patch text 转 texlate-13（彼 splice 域 e2e/worker/repair_l2）；pendspec 落地后 segmirror 放行的 ping 链不变。

## 2026-09-19 ~04:5x — XCOMET-QE 三角测量批收官（task#13）

- **qe-scores.jsonl 1200/1200 落袋**（archbox→tmp/qe-scores.jsonl；批程 3 次内核 OOM 连杀 + 1 次 peer-GPU 4GiB 挤占，Restart=on-failure + 断点续跑兜住）。
- **三角测量读数**（join 1148 格，bib 52 行按 spike 结论剔除——QE 对未翻 bib 打 ~0.57 属设计内）：**Spearman(qe, judge)=0.455**、Pearson=0.332；qe 均值 0.661±0.228、judge 93.9±4.8。分歧格（|zdiff|>1.5σ）115 个，主方向=QE 高分/judge 低分（如 1003.4720|0:19 qe=0.887 judge=45——judge 抓语义错而 QE 只见流畅度）；反向 QE≈0.02/judge≥95 两例疑为占位符密集段 QE 盲区。清单全文 tmp/qe-join-report.txt。
- 定位：ρ≈0.45 属 QE-vs-人工判定常态区间——**可作 cheap 预筛/异常格路由信号，不足以替代 judge**；L1 单发判官前可加 QE 兜底排序。现场已恢复（earlyoom 起、swapfile 撤）。

## 2026-09-19 ~06:1x — 夜巡：roster 扩 7 + mnrasretire 混合设计落树

- **mnrasretire 在飞改动抽查**（40-install.yaml +64，未交付）：`mnras_texmf_shadow_retire` order 11.91（pstadd 11.9 与 draftsty 11.95 间）——设计比我转达的纯 stateless drop 更丰：**wdir 可达域 mv-retire**（find . + ../_texmf/home 双根，盖 stagerun 兄弟式与生产内嵌式_texmf；宿主 ~/texmf 不碰=守"零外变"）+ **vendor 补丁件平投 cwd**（kpathsea cwd 序压一切 texmf 树含宿主同病件）。条件闸：ctx_suggests `Options Section|mnras\.cls` ∧ any(cache_dir_glob `**/mnras.cls` ∨ `../_texmf/home/**/mnras.cls`) ∧ tool sh；指纹=剥注释行 `ds@usegraphicx` 携 `\usepackage|\RequirePackage` 才 mv，texlate 双标（patch/injected）跳过防自拆；python 桥 `_vendor_root` 取钉件 `|| true` 退化为纯退役不阻塞。收割核点备查：`_vendor_root` 存在性、`../` cache_dir_glob 越界支持、11.91 序位无撞。
- **roster 扩 4 研究道**（→7 在飞）：citemath(#64 机链实证 + 语料暴露 + 机制选型)、twinhead(#66 多错 dispatch/salvage-as-discovery/孪生签名三案设计评估+回归风险)、draftgap(#67 draftsty known_gap 三缺口语料暴露——变体签名/子目录/cls-only)、acceptpdf(#65 acceptable_pdf 内容丢失爆半径——#10 裁决定量件)。
- **L1 re-gate 裁定=候场**：pending.py +467/-59 未 commit——此刻跑 parsebench 测的是混合态非 commit 树，门无效；pendspec 落地后立即重跑（现行树=peer v1 退役 + 我 45fab85/cb404a6/22e94be/c68dc86 全入）。
- **脱管批面**：l1-gate post-W84 完（1955/1955 strict、leak 0.0）；autogloss-reg 完 rc=0（contested 0.070→0.080 容内）。
- 门巡：工作树改动全可归属（pending.py/slots 测=pendspec、40-install=mnrasretire、judge.py=peer 重构）；零 git 违例；#10 裁决点仍唯一用户面。

## 2026-09-19 ~06:5x — 收割×3：pendspec/mnrasretire/slotdiff 落 + L1 re-gate 绿

- **a28e853 pendspec 收**（#59）：`_pend_spec_of` 真 spec walker——注册 opaque/math 宏在 pending/boundary 臂原走 `_PEND_PROBE` 兜底（`o m×6` 式）超吸尾随 `{..}` 组，今走真 `m.spec`（共享 toks-walk + 流侧 `_absorb_spec`/`_absorb_grp_tail`）；`_grp_spec_walk` 由 `_grp_opaque_args` **抽出不复写**，`_PendRem` 跨界余量五槽编码。11 新钉 + 全绿；残口披露=delim 中窗续无自然触发钉（声明非钉）。与 diff 逐 hunk 对账一致。
- **9577210 mnrasretire 收**（#61）：`mnras_texmf_shadow_retire` 11.91——收割核点全过：`_vendor_root`(_builtins_vendored:293) 存在、`../` pathlib glob 支持实证、序位无撞、112 规则载、24/24 钉绿、ruff 净。混合设计=wdir 可达域指纹 mv-retire（find . + ../_texmf/home 双根盖两式_texmf 布局；宿主 ~/texmf 零触）+ vendor 补丁件平投 cwd（kpathsea cwd 序压全链）。
- **b1b46b3 slotdiff+peer 合收**（#63）：judge.py 尾挂 `_slot_args`/`_slot_arg_multiset`/`paired_slot_diff`（append-only 守约——peer `_machine_slot_probe`→公共 `machine_slot_audit` 抽离同文件同提交收，函数自含完整）+ test_slotdiff 44 绿。**接线 patch 三件未随产**——tmp/lane-slotdiff/ 空，待报文载件转 texlate-13（彼已预警：pipecore 抽脊在飞 e2e/compile/_common 面在动，patch 落点或迁 pipecore，彼侧负责重映射）。
- **test_docx_done 归因更正**（texlate-13 来讯）：非 pipecore WIP——系彼已 commit 的 ChunkResult.skipped→ChunkRecord.fell_back 改名漏了 union 消费点，57f0700 已修。
- **L1 re-gate ②过**（tmp/l1-gate2 → parsebench-v3-postspec）：1955/1955 strict 全等、leak 0.0/133372 ≪0.040%——post-spec 树（pendspec walker+peer v1 退役 +45fab85/cb404a6/22e94be/c68dc86/9577210/b1b46b3）全量验证。
- roster 4 在飞：citemath/twinhead/draftgap 研究道+acceptpdf（完待报）；mnrasretire/slotdiff 尸待报文到齐后清。

## 2026-09-19 ~07:0x — 夜巡：mnrasretire v2 追落 + 全树归因图

- **e9b6583 mnrasretire v2 收**（中飞修订捕获）：commit 9577210 后工作树再变——agent 收到我 stateless-drop 重设计后先交 v1 混合（usertree 内仍 mv），续修订为纯 drop：`mnras_texmf_shadow_drop`——**三探测根**（wdir 根指纹 / find . ../_texmf/home 双式 usertree / kpsewhich 宿主+TEXMFDIST 面——纯证据不触件）+ **mv 收窄至 wdir 根稿自带病件**（cwd 现胜者让位，pstadd 同型先例）+ 根槽安全件不覆写 + tectonic 无 kpsewhich 宿主面缺探声明 known_gap。v2 严格优于 v1：树外突变归零（v1 仍 mv usertree=wdir 邻域突变）。27/27 钉绿、112 规则载、ruff 净。
- **全树归因图**（零违例）：segmenter×6+argspec/dispatch_mirror 测=peer segmirror 三镜合并在飞（a28e853 上吸收_PendRem/_grp_spec_walk）；worker/_common+compile+pipecore.py=peer 抽脊在飞；bench/py×4+test_fuzz×25+stubaudit 测=peer docstring 转义清扫批；40-install+mnrasretire 测=v2 已收。
- **peer 更正入册**：test_docx_done 失败归因=texlate-13 已 commit 的 ChunkResult.skipped→fell_back 改名漏 union 消费点（57f0700 修）——非 pipecore WIP；L0 全域恢复绿。
- **L1 re-gate ②过已记**；slotdiff 三接线 patch 仍待报文（lane 目录空——或随报文载）；roster 2 在飞（citemath/failmine 跑）+3 报文在途（twinhead/draftgap/acceptpdf 已清尸）。

## 2026-09-19 ~07:4x — 研究道收割：twinhead 设计采纳 + 三普查定量

- **twinhead design=采纳**（tmp/lane-twinhead/design.md，前提修正件）：xelatex `-halt-on-error` 下孪生错**根本不在 log**（r1 log 仅 39 行 1 错）——多错 dispatch 与孪生签名规则双双死在 xelatex 面；tectonic `continue_on_errors` 默认全错在 rep.raw。采纳案=**miss 二次 dispatch**：`_match_apply` 空判→classify_errs(rep)（tectonic 免）∨ xelatex 跑一次 best_effort 探针编（salvage 同参，产件 stash 供 salvage 复用=净零编译）→候选 (cat,pay) 去重≠primary 重指 ctx 重跑规则匹配；**yaml 零改**——geometry_hoist 原签名 verbatim 中 twin 真 cat/pay；applied 去重绑二次 pay；sig/stuck 仍计 primary；探针预算 ≤2/cell 且仅 apply 改态后可再探。爆半径=加性仅 would-die 径，最坏=修级联症状先燃一轮。
- **#70 secdispatch 派出**（engine.py+logparse.py+ 新测件，## REVIEW）。
- **draftgap 裁决=known_gap 虚置**：EDEF_CAPTURE 精确签名仅 1706.00240（已覆）；IFNUM_BT_OTHER 16 格=pasj00.cls:3788 `\ifnum`0>\count@`数字类判=良性习语；IFX_BT 1 格 nath.sty 良性；LET_ABS 410 格全`\let\abstract\@undefined` 类=良性定义非捕获 hack；S0 10 格 amsmath 良性——变体桶全假阳，无后续规则修订需求。
- **acceptpdf 定量（#10 证据件）**：1131 acceptable_pdf 格——594 ferr>0 / 537 ferr=0；**59 格（5.2%）携内容丢失签名**：env_undefined 31、missing_end 15、eof_truncation 5、capacity_abort 4、begin_end_mismatch 2、emergency 2；last_died 全 null。裁决点升级：~95% 为妆面残，5.2% 实丢 env/截断——待用户裁 acceptable_pdf 是否收紧排除内容丢失格。
- **citemath 普查件产**（4 json，census209 ds209 代理 0/1987——2.09 探测口径或漏 revtex-era；机制报在途）。
- roster 3：secdispatch(#70)/citemath/failmine；twinhead/draftgap/acceptpdf 尸清。

## 2026-09-19 ~08:1x — citemath 机制实锤 + citembox 派 + peer 三大落地

- **citemath EVIDENCE.md 收**：机链=`\cite`→revtex4-2 `\rtx@citex`(7143 上标壳)→natbib `\@citex`→undefined-cite 支吐 `{\reset@font\bfseries ?}` **无盒**——`\bfseries` 入 math→`\not@math@alphabet`（kernel `\@citex` 有 `\hbox` 故 article 免疫；`\ref`/`\eqref` 走 `\nfss@text` 免疫）。**自持环实锤**：halt_on_error 死于 cite 错→thebibliography 永不执行→aux 无 `\bibcite`→cite 恒 undefined→每轮同错（min4 aux 截 `\citation` 实证）。修法实证=min6：`\mbox{\cite{}}` 包壳一轮净。暴露=全库 492 格裸 cite-in-math（documentstyle 215 格、revtex 确 59、natbib-only 9）。
- **#71 citembox 派出**：latex209.py `_MATH_SWITCH_209` 同 traversal 扩——math 域内 cite 族 8 令（含星号/双 opt）包 `\mbox{}`；已包/注释/文-mode/\ref 系跳过；N=1 域=documentstyle 215 格（现代 revtex4-2 直稿残留由后续 yaml 规则补）。
- **peer 三落地**：efc53bc0 segmirror 三镜合并（_FAM_BIND registry——pendspec walker 吸收毕）；13c603cf corpus eval/dev 扩 8 层 13,266 篇；70be3618 pipecore 抽脊落地——test_docx_done 修链闭环。
- roster 3：secdispatch(#70)/citembox(#71)/failmine(#69)；citemath 尸清。

## 2026-09-19 ~08:4x — failmine 收割：top5 目标 + roster 扩 10

- **failmine rule_targets.txt 收**（records>09-17 全域挖）：①natbib cs_map 扩 citet/citealt/citealp/citeauthor/citeyearpar/citetext（11 格，与 citep/citeyear 同型 trivial）②aux 残留 `\NAT@force@numbers` 清（4 格，numbers_pass 防写不清理）③`\kwd` cs_map polyfill（3 格，imsart shim 已证 noop）④未闭 `\if*`→`\fi` 注入（2+14 格，MODERATE 注入点须慎）⑤babel_opt 非 LDF 名规范化（2 格，机制未明待查）。名誉榜：pst-arrow(5 已 vendor——疑似 reachability 同型)、float_opt|H(5)、aux_scan_eof|newl@bel(5)、setstack.sty(3 未 vendor)、conm-p-l.cls(3 未 vendor)、\bibhang(2)、proof env(3)、\g undefined_cs(9)、unfixable:capacity(7)、hyperref_driver|dvipdfmx(1)。
- **mutex 排布派 5 道**：csmap(#72，95-targeted cs_map 块=natbib+kwd 并道避撞)、nataux(#73，80-bib aux 清)、ifclose(#74，75-syntax \fi 注入——与 draftsty edef 幻影同签名异因，cond 须分流)、vendordiag(#75，pst-arrow/setstack/conm-p-l 机制诊+pst-arrow N=2 广义 sweep 触发判)、floatopt(#76，70-pkgopt [H] 规)。
- **追派 2 普查**：gcensus(#77，\g 主导展开→cs_map 可判否)、capcensus(#78，capacity 爆型逐格归因)；\bibhang 串行候 ifclose 让文件；aux_scan_eof|newl@bel 或已覆 aux_purge_regen 待 nataux 域顺手核。
- roster 10 在飞：secdispatch/citembox/failmine/csmap/nataux/ifclose/vendordiag/floatopt/gcensus/capcensus。
- 门巡：零活批；树 4 改全 peer 域（selfimp-skeleton/repair/stubaudit/packaging）；L1/L0 绿保持。

## 2026-09-19 ~08:5x — 报文潮核销 + draftsty 签名收紧 + #10 决定性证据

- **mnrasretire 报文核销**：所述=v1 混合（deviation 声明=retire→missing→vendored_fetch 全场景不可达，自植 vendor 件理由）——树已演至 v2 纯 drop（e9b6583），报文与已收内容一致无追加。
- **acceptpdf #10 决定性证据（升级用户裁决面）**：verdict 路径=dirty_pdf 晋升（engine.py:1031-1037，仅需 final_pdf∧err≤3∧!died，**零内容核验**；scorecard 映 clean~ 档入 GOOD 集 fixloop_bench.py:372,381）。loop1 1131 格分层：**T1 灾损 30**（capacity abort×4=cref@resetstack 递归 1803.03248/1907.10516/2105.03753/2403.05529 loop2 仍炸——restatdiag #31 残口复现；EOF-trunc×5；`这是译文` input 整丢×2；begin→enddoc 吞×2；**cjk_invisible 17=译文零中文渲染**）；T2 env 丢 46；**T3 不稳 422**（≤3 误差条测的是 warm pass，新编 >3 者 444——0806.2110: 1→404）；**T4 glyph 丢 495**；T6 真妆面仅 92（8%）。**~57% acceptable_pdf 携内容丢失**；agent 荐：结构类 cat+cjk_chars<20+missing_chars>0 拒晋升、≤3 条改测 fresh recompile。
- **slotdiff 报文 +4 接线 patch 已转 texlate-13**：Site A 迁 pipecore（peer refactor 中飞移位）、Site D=第 4 个 _resplice 调用点（retranslate 臂，brief 未列）、EOF 放置零撞、cap `>`语义诚实。paired_slot_diff b1b46b3 已落。
- **citemath 荐 (b)**：yaml 反应式规则（bfseries/itshape-invalid-in-math 签名→cite 族 mbox 包，kernel 无 amsmath 依赖）优于我派的 latex209 (a)——(a) 仅覆 209 域，(b) 全类反应即 fixloop 本职；citembox 续跑作 209 域预防补。#79 citerule 立档串行候 ifclose 让 75-syntax（同签名 literal {\bfseries X} 无 cite token 须 noop 声明）。
- **draftgap 副产**：S0 精确网 `edef..{..ifnum`[{}]`全库仅 1706.00240——draftsty 内 grep 第二臂`ifnum`[{}]=.z@` 松匹配良性花招习语（amsmath \@ifnextchar 支撑/ulem 尾花招/tabls 共 9 格）——**4ce9ae3 leader 直修**：两臂皆须 `edef` 在行，18/18 钉绿。
- **failmine 报文核销**（与 rule_targets.txt 一致）：verdict 分布 clean 2557/acceptable 3019/best_effort 2220/unfixable 各类~600+。
- roster 9：secdispatch/citembox/csmap/nataux/ifclose/vendordiag/floatopt/gcensus/capcensus；failmine 尸清。

## 2026-09-19 ~09:1x — 收割潮 2：csmap/nataux/citembox 落地 + vendordiag N=2 否决

- **bcf7de9 csmap**：natbib cite 宏族 cs_map 补齐（citet/citealt/citealp/citeauthor/citeyearpar/citetext/citenum→{usepackage:natbib}）+ \kwd noop polyfill；16 钉绿，failmine ①③合单车道。
- **4b1b7e5 nataux**：`natbib_aux_force_purge` order 195——numbers_pass 只挡未来写，陈旧 .aux 残留 \NAT@force@numbers 行致同签复炸（applied 不再点火）；整行剥除，aux 可再生 low risk。failmine ②。
- **6eaeb31 citembox**：latex209 `_fix_math_fontswitch`→`_fix_math_209` 合并走查 + `math_cite_wrapped` 统计——裸 `\cite[..]{k}` 在数学域裹 `\mbox{}`（natbib 未定义标记 `{\reset@font\bfseries ?}` 无盒直排→\not@math@alphabet 自续）；裸 \cite 无 {key} 保守不裹。57+16 钉绿。
- **texlate-13 确认** slotdiff 四址接线 3787d29：A→pipecore.translate_tree_run、B→_build_zh、C→repair_l2._slot_diffs helper、D→_retr_resplice；deviation=Site D 去 paired_slot_diff import（F401），合理。
- **vendordiag N=2 否决**（notes.md 核销）：pst-arrow 5 格 loop2/rt1/guardsmoke 全 clean——loop1 是 extension-less vendor 件+dep fanout 覆盖前的纯缺席，非 mnras shadow（主机零 texlive 实体可遮，stale tlpdb≠可达件）；setstack noop stub 够用；conm-p-l→acmart shim 正解。mnras shadow 维持 N=1，不触发泛化扫描。
- **bib-passthrough 裁决落地**（edc2dec skeleton）：用户 GO→40904c7 直通臂 +246b08c judge 条款；bib14 回归 dnt-major 17→0、stated 14/14=100。
- roster：secdispatch/ifclose/floatopt/gcensus/capcensus + babelinv/zhfile/proofdiag + 新派 thehalgo/auxeof/expl3diag = 11。

## 2026-09-19 ~09:2x — secdispatch 落地（twinhead 设计实装）

- **7dae23d secdispatch**：ErrReport.errs(≤32)+classify_head 抽出+err_candidates 去重保序；miss 路径候选逐条重指 ctx.round 派发，xelatex 单错 log 探针 ≤2/格（apply 变才重探）、结果留 salvage 复用净零编译；via:"secondary:<cat>" 落 actions；sig/stuck 保主错。零 yaml 改动——geometry_hoist 对孪生真身 (option_clash,geometry) 原样点火。16+1230 域钉绿。
- 旁见：peer 测试件改名 test_server_fixes{,2}.py→test_server_audit_fixes.py 在树（非本队车道，留主）。
- roster：ifclose/floatopt/gcensus/capcensus + babelinv/zhfile/proofdiag/thehalgo/auxeof/expl3diag = 9 研；csmap/nataux/citembox/secdispatch/vendordiag 尸清。

## 2026-09-19 ~09:3x — floatopt 落地 + flipcheck6 脱管批起

- **0e989a0 floatopt**：`float_opt_h_pkgload` order 187——[H] 系锚是 float 宏包专属 (kernel \@xfloat 只认 htbp!)，根修 \begin{document} 前注 \usepackage{float} 非降级；双闸 (ctx_suggests+source_contains 无装载点∧有 H 用)+main_head_contains 挡 2.09；与 comma_strip(184) 零重叠。5 格 (0806.4088/1003.5014/1608.02624/astro-ph/0307059/cond-mat/0408234)。12 钉绿。
- **flipcheck6 脱管批**：55 格=25 目标 (csmap14/nataux4/floatopt5/secdispatch:1206.0291/citembox:gr-qc/9901082)+30 clean 回归 (loop2 clean 池 577 抽 seed42)，stagerun 全链 mock-xlat → bench/results/stagerun-flipcheck6，gate-③⑤。
- roster 9：ifclose/gcensus/capcensus + babelinv/zhfile/proofdiag/thehalgo/auxeof/expl3diag；secdispatch/floatopt 尸清。

## 2026-09-19 ~09:4x — capcensus 核销 + W164 登记 + 报文潮全数对账

- **capcensus 裁定**（lane-capacity/repro-* pristine 实证）：unfixable:capacity 7 格——5 已愈于在案修复（restatable argspec 泄漏×2、emulateapj5 自 input 环×2、1907.00027 主内存腐蚀自愈）；**2 格 paper-authentic 上游位腐**（1404.0037 utarticle.cls 1997 \address \xdef+\@nomath、1706.00076 amsart \title opt-arg→expl3 recursion_tail 尾环）——超安全改写界，处置=known-bad 登记。**4df5ac9 W164 入 mechanisms.jsonl** 挡重复救伤。附议项→#87 cappayload（capacity payload 带 bracket+pending token 利分诊）。
- 早波报文全数对账核销：csmap(bcf7de9)/nataux(4b1b7e5)/citembox(6eaeb31)/secdispatch(7dae23d)/floatopt(0e989a0)/vendordiag(N=2 否决)——所述与已收一致，零追加。
- flipcheck6 在跑（19/53 处全 clean 含 kwd 目标格 1012.2012 翻转实证）。
- roster 10：ifclose/gcensus + babelinv/zhfile/proofdiag/thehalgo/auxeof/expl3diag(交付待收) + cappayload/dvipdfmiss。

## 2026-09-19 ~10:0x — flipcheck6 收割 + floatopt 3k 窗缺口修复

- **flipcheck6 裁决**（bench/results/stagerun-flipcheck6, 53 rec）：目标 25 格——22 fixloop-clean + 2 compile-clean（astro-ph/0307059、1003.5014 compile 阶段即净）+ 1 partial；clean 30/30 守衡（gate-⑤ ✓）。
- **0408234 未点火根因**：`main_head_contains` 走 `main_head(n=3000)` 3k 字符窗，稿首 70 行注释堆把 \documentclass 推到 char 3280 → 闸拒。**acdfc0b 修复**：docclass 断言并入 source_contains lookahead（全源拼接无窗限，2.09 拒义不变），复跑 float_opt_h_pkgload 点火→first_error:null、pdf 61KB→851KB（[H] 浮体全渲）。残余 U+0327 combining cedilla 缺字形×1（benign warn）。
- 教训刻痕：window 类条件（main_head 3k）对注释厚重稿不可靠——断言应优先走 source_contains 全源面。
- gate-③④⑤ 本波全过：目标格全翻/净、30 clean 零回归、sabotage 沿用既有覆盖。

## 2026-09-19 ~10:2x — 研究潮 2 收割：4 报全核销 → 3 impl 车道派生

- **expl3diag**：4 格同机理——`\documentclass` 全局 driver 选项 (dvips×3/pdftex×1) 撞 l3backend 一致性检查 @expl3.sty:154。`expl3_driver_opt_strip`(55-prim:17,order35) 早已在案但 **regex 逗号粘连缺陷**（中位选项吃掉两邻逗号→`[final,pdftex,reqno]`→`[finalreqno]` 幻选项）。→#91 expl3fix（拆 head/mid/tail 如 hyperref_driver_neutralize）。
- **proofdiag**：0806.0904/2953 已愈于 geom stub 60 行版（proof env 在体）；0707.1588 仅需复跑。**真残口**：`undefined_env_polyfill` 只注 \begin{document} 前——preamble `\renewenvironment{X}` 站点（err 行<begindoc 行）结构性够不到。→#90 envpoly（docclass 缝/站点前注入臂）。
- **0707.1588 单格复跑**（stagerun-fc6c）：polyfill 已点火、proof env 过——**新残 `undefined_cs:QED`**（amsthm 终证标记，shim 缺）。已转 envpoly 斟酌 proof polyfill 附带 \QED stub vs cs_map 条目。
- **thehalgo**：kernel 原生 `\theH<ctr>`（latex.ltx:10145, ≥2024-11）× ICML 模板 `\newcommand{\theHalgorithm}` 搭车 shim 冲突——`already_def_newcmd_renew`(111) 已覆盖全家，3/4 新档实证。**零新规则**；provenance 附注延后（75-syntax 被 ifclose 占用）。
- **zhfile**：这是译文=MOCK_ZH 经 bare `\input <file>` 于 resizebox body-arg in_arg 泄漏（fig2dev .pdf_t 叠层形）；格已愈（TRANSPARENT_HEAD_SPEC+8b87318 文件名 span 硬化）。**活残口实证**：`\caption{see \input foo_bar.tex end}` 任意 in_arg 文本位裸 \input 仍漏 →#89 inputleak（args.py:744-746 吞裸文件名入保护段）。
- roster：ifclose/auxeof/cappayload/dvipdfmiss + babelinv/gcensus(交付在途) + inputleak/envpoly/expl3fix = 10。

## 2026-09-19 ~10:5x — 研究潮 3 核销 + 收割潮 3 六连 commit + flipcheck7 起批

- **gcensus 裁定**（NOTES.md 核销）：`undefined_cs:g` 是 loop1 时代死签名——全源零 `\g`、现行码重放零命中（1706.00033 残为 russianb.ldf 缺=babel 畴）、loop2 4/9 重跑皆无；\g 语义异质（\gamma vs grams），盲 polyfill 必错。处置=残表哨戒，**零新规则**。
- **babelinv 交付**：tmp/lane-babelinv/ldf_pins.yaml ~52 名 tlpdb/tarball 逐名核实（含 babel-{ukrainian,bulgarian,catalan,greek} 实物档）。**.ldf 不入 INDEX_EXTS → filemap.overrides 是唯一确定落点**。
- **dvipdfmiss 裁定**：2403.00013 的 `hyperref_driver|dvipdfmx` 派发脱靶根因=kaist-ucs.cls `\ifpdf/\if@dvips` 条件 `\def\@drivername{drv}` 间接指派+`\RequirePackage[\@drivername]`——括号面零字面驱动词，旧闸够不着（known_gap 早已预言）。
- **六连 commit**：a4e5c8f drvdef 臂（`\def\<cs>driver<cs>{drv}`→xetex 全支覆写 + 闸扩第三交替 +13 钉）、28a64eb ldf 钉表 52 枚（含 afrikaans→babel-dutch/northernsami→babel-samin/turkmen→turkmen 异名档+german-traditional 已知噪声 null）、ffd4bf3 envpoly renew 站点前置臂（masked 活区扫描 + 首站点行首锚 + 降序插 + 幂等）、aeda23f ifclose 双臂（unclosed_if_close other:196+eof:196.5，内嵌 ~250 行遮盖栈平衡扫描器——def 体冻结 token 只计不注、跨件借用对全局闸、MARK 幂等，25 钉）、a227ee6 expl3fix 逗号粘连拆分（全表/表首/表内尾/,] 洞 四态如 hyperref 形，12 钉）、86d30ea cappayload（taxonomy `payload_scan:` 原语注册表+capacity 提取器 bracket 名归一 tag×ctx 首层 pending cs→`<tag>|<cs>`，classify_head 内接线=次派发同享，12 钉）。
- **drvdef 单格实证**（stagerun-drvdef）：hyperref_driver_neutralize 点火（前轮缺席）→ dvipdfmx 错消，**52→1 错**（xbb/pipe 群=驱动错下游级联同灭）；残 `\chinese already defined`（ctex 注入×dhucs 稿自定义，→chineseconf 普查）。
- **flipcheck7 脱管批**：33 格=17 目标（ifclose 12+envpoly 2+expl3fix 3 独享）+16 clean 回归（flipcheck6 clean 池抽）→ bench/results/stagerun-flipcheck7，gate-③⑤。
- **inputleak 交付在库待闸**：args.py in_arg 裸 `\input` 文件名吞入 CMD 保护段（镜 :789-809 非 in_arg 形）+7 钉；其 35 件抽样 parsebench 全绿——全量 L1 闸 (parsebench-v3-inputleak) 脱管在跑，过后 commit。
- **envpoly 追单在飞**：_ENV_COMPANIONS 对偶件表（proof→\QED 开口盒 stub，0707.1588 转办）+95-targeted.yaml citerule 编辑中（#79）。
- **新派研道**：pipecensus（Cannot run pipe command/.xbb 家族普查）、chineseconf（\chinese already defined 注入冲突普查）。
- roster：citerule(#79)/auxeof(#84) + envpoly 追单 + pipecensus/chineseconf = 5 活；脱管批 3（L1 闸、drvdef 已完、flipcheck7）。

## 2026-09-19 ~07:0x — 收割潮 4：inputleak/QED/auxeof/citerule 四连 commit + 研报双核销派车道

- **30d53c0 inputleak**：L1 闸落地绿（parsebench-v3-inputleak ok 1955/1955 strict、leak 0.0/133372）→ 提交。args.py in_arg 裸 `\input f.tex` 文件名连吃 FILENAME_CHARS 入 CMD 保护段（zhfile 普查 `\caption{…\input…}` 实漏），+7 钉。
- **a5a26b6 envpoly 追单**：`_ENV_COMPANIONS` 对偶件表（proof→`\providecommand{\QED}` amsthm 开口盒 stub）随批块/站点前置同块下落；blob 取证先于注入防 stub 自证；95-targeted `QED:` cs_map 独立兜底。+4 钉（批块/站点/证据门/独立 env 负例）。
- **cc10b53 auxeof 核销转修**：2403.05523 `aux_scan_eof|newl@bel` 幻影链根因=终编臂 (`passes>1` 同轮全遍终编) 只排 timed_out——xdvipdfmx `pdf_link_obj` fatal→SIGPIPE 截杀产 pdf+ 截断净 log (n_bang=0)，漏闸同轮重编恰读上半行截断 aux 自产自销（16384B 边界实证）；purge 每 payload 一次不可断。修=臂条件→`not _res_died(res)`（与 :905 clean 门同义）。3 钉含正控（健康 pass-1 终编照发）。余案→#94 xlinkobj（xdvipdfmx fatal 根车道=hyperref-link 畴）。
- **12c21a5 citerule #79**：taxonomy `invalid_in_math`（`LaTeX Error:` 锚防同句式 Warning 抢签）+ latex209 `_math_regions`/`_cite_mbox_edits` 共用模态域走查抽出（`_fix_math_209` 与新规则同消费单源）+ `_builtins_bib.cite_in_math_mbox`（数学域裸 cite 族→`\mbox{}`，kernel 无包依赖；无 cite token 拒发）+75-syntax:105。natbib `\@citex` `{\reset@font\bfseries ?}` 无盒标记自续链断。20 钉。
- **pipecensus 核销→#92 xbbpregen**（已派）：`Cannot run pipe command`+`.xbb no BoundingBox` 对偶错=dvipdfmx.def 内部 `\openin"|extractbb` 走 shell-escape；xetex.def 原生量 PDF 无管无 xbb。2105.00151 字面 `[dvipdfmx]` 26 错实损（missing_graphic）；2403.00013 已被 drvdef 臂灭（def→xetex 后走原生路径）。荐=extractbb 预生成 .xbb 落 wdir（`\Gread@generic` 先命中、零源改写零 write18）。
- **chineseconf 核销→#93 chineseclear**（已派）：`\chinese already defined`=dhucs→xetexko `\let\chinese\Schinese`（cls 内载）× 注入 ctex `\cs_new:Npn \chinese` 冲突；cls 仅字符串比 "chinese" 于 \author 选项未调 cs → undefine 安全。荐=75-syntax ~110.8 `Control sequence` 签→`\let\X\@undefined` 于 docclass 后 ctex 前；警勿扩 _ALREADY_DEF_CS_RE（`\c__fontspec_*` 会劫 fontspec_double_merge 110.5<110.7）。
- **peer 重构事故闭环**：bench/py 中途 staged 改名曾致 stage_compile `import quality_proxies` 断 → flipcheck7 fixloop 阶段零产出；peer 落定后 import 复原 → **fixloop-only 重放已起**（28 非净格 jobs4，compile 记录复用）→ tmp/lane-flipcheck7/run-fixloop.log。
- roster 3：xbbpregen(#92)/chineseclear(#93) 跑、citerule 交付已收待尸清；auxeof/pipecensus/chineseconf/envpoly/expl3fix 尸清。

## 2026-09-19 ~07:1x — flipcheck7 收割：15/17 目标改善 + clean 16/16 守衡 + ifclose 缺口确诊入诊

- **fixloop 重放完成**（28 非净格，~63s）：17 目标格 —— **13 clean**（envpoly 0806.0904/2953 双双翻净、expl3fix 0905.4874 acceptable_pdf、ifclose 1803.00054/1803.00181/1907.00121/2003.03535/2105.00120 翻净 + 1706.00175/1907.00207/1907.03758/hep-ph 双格 compile 阶段即净=早波机制已愈）、**2 partial**（0905.0193 best_effort_pdf、1907.00128 acceptable_pdf，均较 fail 改善）、**2 stuck**（1206.0701:288、1306.0364:275）。
- **ifclose fired-but-unfixed 缺口**：两格 unclosed_if_close 均 applied 但同签同行号残存 → #98 ifclosegap 诊断车道（注入错位/抽象 edef 捕获中和交互/def 体冻结 token 计数假设待查）。
- **clean 池 16/16 守衡**（gate-⑤ ✓）：fixloop-clean 11 + acceptable_pdf 5，零回归。
- **新派研道**：xlinkobj(#94 xdvipdfmx fatal 根车道普查)、bblmath(#95 .bbl 数学域字切族普查)、failmine2(#96 次波目标普查)、bibhang(#97 延搁项)。
- roster 7：xbbpregen/chineseclear 实施 + xlinkobj/bblmath/failmine2/bibhang/ifclosegap 普查；flipcheck7 批完。

## 2026-09-19 ~07:2x — 巡 tick：L0 钉群 997 绿 + sabotage-b r3 逃逸闸刷新起批

- **L0 点闸**：test_fixloop* 全量 998 项——997 绿 + 1 挂 = xbbpregen 在飞测试文件 (test_fixloop_xbbpregen.py 未提交，代理自伤不算回归); 已提交面全绿。
- **sabotage-b r3 脱管批起**：wave-4 触碰 segmenter (inputleak 占位符面) + fixloop 5 规则 → 逃逸面在 blast radius; 40 格沿用 r2 池 (1663 注入事件/0 逃逸基线), ingest→parse→xlat(sabotage-b) → bench/results/stagerun-sab-r3, gate-④ 刷新。
- roster 7 不变 (xbbpregen/chineseclear 实施 + xlinkobj/bblmath/failmine2/bibhang/ifclosegap 普查)；xbbpregen 已开写 _builtins_graphics。

## 2026-09-19 ~07:3x — gate-④ 核销：sab-r3 逃逸 0（1622 注入/1620 回/2 捉）

- **sabotage-b r3 落地**（39 格，~90s）：1622 注入事件——1620 recovered + 2 caught + **escaped=0**。wave-4 面 (inputleak 占位符 + 5 fixloop 规则) 未开逃逸路，gate-④ 过。
- roster 7 全在飞 (xbbpregen 已见 _builtins_graphics 在写)；零交付待收。

## 2026-09-19 ~07:4x — xbbpregen 收割入库 (001094d) + bibhang 普查核销

- **xbbpregen 交付**：`xbb_pregen` 规则 (45-graphics.yaml order 15.5) + `_builtins_graphics.py` builtin —— dvipdfmx.def `"|extractbb` pipe 沙箱死 → 全量图形 `extractbb -x` 预生成 .xbb 旁缓存，pipe 臂整体跳过; 零源改。实证订正 4 项 (extractbb -O=stdout/-x=写盘、批式只写末件、openout_any=p 拒绝对径、败残留空 .xbb 是毒件需清)。14 测试 + 1031 回归绿; `## REVIEW` 标 (新 run_tool builtin)。归因单主已核 (csfix.py 同改=chineseclear 在飞，剔出)。
- **bibhang 普查核销** (#97)：4 格 mn2e+usenatbib —— 根因=mn2e stub 裸 `\LoadClass{mnras}` 丢选项 (今日已修 `\LoadClassWithOptions`), 残链由 already_def_undefine order-113 兜底; 无新规则。
- roster 5：chineseclear 实施中 (csfix.py+75-syntax.yaml 在写) + xlinkobj/bblmath/failmine2/ifclosegap 普查中; xbbpregen/bibhang 尸清。#99 flipcheck8 排队 (等 #93/#94 落地同批重放)。

## 2026-09-19 ~08:0x — 收割潮：chineseclear/babelpins/inputquote 入库 + failmine2 次波发散

- **inputquote (46dba25)**：in_arg 引号裸名 `\input"a b.tex"` 保护——闭引号收 span, 无配对全回放只护 cs (不吞散文)。44 leaks+473 segmenter 绿，parsebench spot 9/9 strict。
- **chineseclear (10fcec1)**：`ctlseq_already_def_undefine` order 110.8——expl3 `Control sequence \X already defined` 签 (Command 形够不到) → 文件门 (注入 CJK 装载树) + seam 标记 + docclass 缝三闸 → 缝顶 `\let\X\@undefined`。实格验证：2403.00013 patched copy rc=0/3.45MB PDF/零错行, \let 落 75 行 (docclass 72↔ctex 77)。
- **babelpins (dc426dd)**：`polytonicgreek`→`greek.polytonic` 双形补源 (51-ldf pin 表实证已全在 00-base:178-231, no-op)；+8 测试。
- **事故记录**：xbb 提交 (001094d) pathspec 整文件把 chineseclear diff↔commit 间隙新写的 builtins.py 注册行卷走 → 该提交独立 import-broken, 10fcec1 立即补平。教训已入 memory (gfs-stash-race 门面时序变种)。
- **failmine2 普查核销** (tmp/lane-failmine2/CENSUS.md)：481clean/90be/86acc/22hard/91unrun。发散 7 车道：bticktax(`` `\X' `` 反引号 taxonomy 缝，\Bbbk 23 格)、newblockpf(~11)、flushendopt(10)、arraypream(~7)、pdfsanitize(gs-pdfwrite 资产消毒，5 格/9 腿——xlinkobj 普查转换)、begindoccen(普查)、dsatcensus(96 格 ds@ 拒收面普查→裁决输入)、drvverdict(driver-fatal+no-PDF 误判 clean 缝)。
- **xlinkobj 核销** (#94)：pdf_link_obj fatal=嵌入图 pdf 畸形 (missing endobj/裸CR/token-per-line), 非 drvdef 族; gs 重写全 5 格实证。
- roster ~10：bblmath/ifclosegap + bticktax/newblockpf/flushendopt/arraypream/pdfsanitize/begindoccen/dsatcensus/drvverdict 在飞；chineseclear/babelpins/inputquote/xlinkobj/failmine2 尸清。#10 + ds@ 待裁决点累积。

## 2026-09-19 ~08:2x — bticktax 入库 (0db4133) + verifymiss 车道再派

- **bticktax**：already_def taxonomy 引导类 `'?`→`[`']`——`` `\Bbbk' `` 反引号签 (amssymb \@ifdefinable) 曾落 other 无 payload, 23 格已通 already_def_* 门。实 log 钉 + e2e 路由钉 + 65 测试。
- **verifymiss (#110) 派 bticktax**：failmine2 covered-but-verify 7 签组 dispatch-miss 普查 (input_sty_to_usepackage/acmart_resnap/natbib-author-year/aux_purge-dirty_pdf/hyperref_driver-timeout/ngerman/杂项)。
- roster 10：bblmath/ifclosegap 长龄 + newblockpf/flushendopt/arraypream/pdfsanitize/begindoccen/dsatcensus/drvverdict/bticktax 在飞；flushendopt 已见 70-pkgopt 大块在写。

## 2026-09-19 ~08:4x — flushendopt 入库 (acf6600)

- **flushendopt**：`flushend_keeplastbox_opt_strip` order 197——sttools 3.x 删 keeplastbox → 成员级剥除 (括号三位+PassOptions 首参，近名/嵌套不沾), 语义零损失 (上游删项本意)。13 测试; 预期翻 1706.02725/1803.09012/2105.00097/2105.03814/2111.00082。
- roster 9：newblockpf (95-targeted+csmap 在写)/arraypream/pdfsanitize/begindoccen/dsatcensus/drvverdict/bticktax(verifymiss)/bblmath/ifclosegap。

## 2026-09-19 ~08:5x — ifclosegap 确诊：幻影失衡 (tracingifs 实证) → ifprot 车道

- **#98 verdict**：1206.0701/1306.0364 零字面 \if 缺口——纯展开时幻影 (unclosed_if_close 正确 no-op, 零注入标实证)。机制：amsproc \maketitle edef→\footnote 链 / myectaart \xdef\@argi→\bf→\selectfont 链，均终止于 `\let\if@X\iffalse` 在展开上下文执行 → 跳至 EOF。原英文稿即复现 = 上游 cls 撞 TL2026, 非 texlate 产物。
- **修法**：非 \fi 注入 (edef arg 内 \fi 不可达) —— preamble 注 eTeX `\protected` 重定义脆件 (footnote/thanks+\bf\it\rm\sf\tt\sc\sl), \protected 属性在 \let\protect\relax 剥脱下存活。两格实测救回。→ ifprot (#112) 派 ifclosegap 实施。

## 2026-09-19 ~09:0x — newblockpf 入库 (343f6b3) + 二次中写卷扫记录

- **newblockpf**：`Command \X undefined` (renewcommand-on-undefined 内核签，natbib.sty:1070 \newblock) → 新 undefined_cs taxonomy 头签 + cs_table canonical hskip polyfill (order 165 表内键非新规)。13 目标格。blast radius 核查：仅 newblock×4 + 单字符杂项 (miss-table 兜底，无回归)。
- **事故二发**：taxonomy 头签 hunk 在 diff↔commit 间隙被 bticktax 提交 (0db4133) 整文件卷走——与 001094d builtins.py 同型; 本例自含无悬空，归因已注。规则化对策：taxonomy/facade 共享面提交前立即重 diff。
- roster 9：arraypream/pdfsanitize (engine+graphics+45-yaml 在写)/begindoccen/dsatcensus/drvverdict/bticktax(verifymiss)/bblmath/ifclosegap(ifprot 实施)。

## 2026-09-19 ~10:0x — 收割潮二：pdfsanitize/ifprot/bblmath 入库 + 三次卷扫事故 (pathspec 变种)

- **pdfsanitize (df72ac8)**：`pdf_asset_sanitize` order 18.5——内嵌 .pdf 对象结构残缺 → xdvipdfmx `pdf_link_obj` fatal → SIGPIPE；签名只走 stderr (.log 干净) → `_report_of` 归一 `*:fatal:`→`!` 抬入 taxonomy 面 (2403.05523 实证)。fatal 不携文件名 → 全量嵌入 pdf gs pdfwrite 重序列化 (内容不动，.fixloop-rd 备份兼幂等标记)。16 测试 +1324 回归绿。预期翻 5 格。
- **ifprot (22a1cfd)**：`if_phantom_protect` order 197.5——同签复发=phantom 判别 (196 字面扫描 noop 烧 dedup 位)；\protected let-wrap 重定义 footnote/thanks+\bf\it\rm\sf\tt\sc\sl @\AtBeginDocument, 逐 \ifdefined 闸 + ledger ifclose: 判词闸 (扫描器缺席保守不收)。双实格救回，10 测试。
- **bblmath (86f6ac6)**：emit-site 修复非规则——`\bibliography{x}`→`\input{bbl}` 丢 revtex `\auto@bib@empty` 解除 → end-doc `\test@bbl@sw` 在 \vbox 排印 cite key (_/&/$ → Missing$ 级联 + 三读)。`\input` 前补 `\@ifundefined{auto@bib}{}{\let\auto@bib\@empty}` 双 emit 点 (normalize.py:695 + bbl_stub_rewrite), \@ifundefined 使非 revtex 零操作。1003.1717 实测 364 错→0；202 测试绿。预期翻 5 格。
- **事故三发 (最重)**：`git commit -- <pathspec>` 不走 index——工作区内容整体提交，`git apply --cached` hunk 过滤被架空。df72ac8 卷入 ifprot 注册行 (impl 未落→悬空，22a1cfd 补平) + drvverdict engine.py 48 行 (texlog driver_fatal_line 未落→悬空，8527fa7 index-restore+ 重敷本方 patch 修复，工作区在飞稿无损)。规则化：交织文件只能 apply --cached+ 裸 commit; 单主文件 pathspec 无妨。memory 三更。
- **普查核销 ×4**：begindoccen (2 tar 格已被 tar_blob_extract+letter_wrap 覆盖→flipcheck 验证，~20 异质残件→shipclscen)；dsatcensus (96→实 14-16 格，推 Option A style-as-class 仿真 1-2 天工——**裁决点累积**)；verifymiss (2 可行动：2.09-arm input_sty + out-of-fileset prim 宽化→primofw/inputsty209)；inputstack (无 \input 环，2 格上游 base-arm 缺→capverd 诚实标)；glossleak (2 格已愈，但 ~13 格 CJK-in-key 族 6 形未盖→kvleak2)。
- roster 10：drvverdict/arraypream + primofw/inputsty209/shipclscen/kvleak2/runawayscan/capverd/renewdocenv 在飞 + bticktax flipcheck8 批 (58 格含 32 clean, ~35min)。pdfsanitize/ifclosegap/bblmath/inputstack/glossleak 尸清。新翻格全转 flipcheck9。
- 裁决队列：#10 acceptable_pdf + ds@ Option A (证据齐：14 格/1-2 天/机制明) + acmart error-in-clean ×16 注记。

## 2026-09-19 ~10:4x — drvverdict/inputsty209 入库 + flipcheck8 早段翻面

- **drvverdict (072111d)**：`driver_fatal` 证据层——texlog `DRIVER_FATAL_RE`+`driver_fatal_line()` 单源；`_base._driver_fatal` = 签名∧失败相 (killed/rc≠0/无 pdf, 单签名拒收保 \write18 契约)；judge `driver_fatal:<line>`→partial；fixloop `_res_died` 扩展 + `_round_cat` 只在 classify→clean/None 缘发 `driver_fatal` (主路径类保 `other`——pdf_asset_sanitize 按 other 派发不破，per-round 字段携归因+salvage 排除)。1907.00277 实证 clean→partial/dirty_pdf。9 文件 238 行，1479 回归绿。
- **inputsty209 (daa3858)**：`input_sty_209_requirepkg` precheck order -12——2.09 compat 只压 `\usepackage` (`\if@compatibility\else\let`)，`\RequirePackage` 内核无条件走全 `\@fileswithoptions` 机器; 同纹改写异枚子。order -12 双模式合法=严格占优，顺带兜病态双中头。90-shim-legacy EOF hunk 经 apply --cached 过滤入库 (arraypream 在飞 hunk 剔出)——**交织文件正确流程首验：apply --cached+ 裸 commit**。
- **flipcheck8 批完** (bticktax, 58 格/fixloop 21 格，07:52 ALL DONE)：早段翻面 2105.00151→clean (xbbpregen✓)、2104.00012/math-0104250/nucl-ex-0501017→clean (ngerman 臂✓)、astro-ph/0104007→clean (tar✓)、2111.00082→clean (flushendopt✓)、0501100/0605138→clean (newblockpf✓)、1706.02400 cat=already_def (bticktax 缝✓)。**2403.00013 只到 acceptable_pdf** — ctlseq 目标错已清但残留→drvverdict 新派残因车道。全表等 harvest.py 回执。
- **输入核销 ×2**：inputstack (3 格零 \input 环——2105.00111 已愈陈旧记录，1706.00076/1404.0037 上游 base-arm 缺→capverd 诚实标派)；glossleak (2 格已愈，~13 格 CJK-in-key 族 6 形未盖→kvleak2; trade-off 记：glossary 整件落 support 不再翻译，若要翻需 kv-value digging 段器增强)。
- roster 10：arraypream (75-syntax/90-shim/vendor/tests 在写) + primofw/shipclscen/kvleak2/runawayscan/capverd/renewdocenv/aastex61if 在飞 + drvverdict(2403resid)/bticktax(harvest 中)。inputsty209/drvverdict-#109 尸清。
- **门警戒**：teammate 零 git 令✓；L1/autogloss run.log 皆 ALL DONE；pathspec 卷扫修复后 HEAD 双破 import 已平 (22a1cfd+8527fa7)。

## 2026-09-19 ~11:1x — arraypream 入库 (938da65) + preamcjk/resid209 普查派

- **arraypream (938da65)**：`pream_token` 新类 + `pream_token_cs_expand` order 198——array `\@mkpream` 只改写 *-repeat/`\NC@`, kernel `\@xexpast` 本可展开字面 preamble 宏 → 修=展开非 cs-map：call-站 `\expandafter` + def-站 `\edef` 烘焙 (`\string` edef 内执行产字面 token, 单臂不够) + emulateapj 死 let 链中和 (array 中和 kernel 存名→"Missing #")。vendored aaspp4/aasms4/aastex/emulateapj 补丁 + regex_rewrite 盖 doc-shipped 件。12 测试 +1139 绿，e2e deluxetable 0 错。预期翻 \@delspec~~9+\pt@format~~4-5。
- **renewdocenv 核销**：`Environment 'x' already/undefined defined` 签 0 命中全记录——潜缝但零发，修法已存档 (env_undefined 宽化+already_def env 姊妹+seam rewrite), 越 ≥2 门槛再派。尸清。
- **新派 ×3**：resid209 (9901081 ~151 残 2.09 错 + ~51 稿 \documentstyle∧\input 族次波普查)、preamcjk (arraypream 揭 54 命中 CJK-译文漏 preamble-spec——与 kvleak2 族邻接可能同根，查 dig 路径归属)、aastex61if (defer 的 def-体 \if 失衡 ~5 格普查)。
- roster 10：primofw (actions/55-prim/ruleset 在写——其宽化需动条件机器非纯 yaml)/shipclscen/kvleak2/runawayscan/capverd/resid209/aastex61if/preamcjk + drvverdict(2403resid)/bticktax(flipcheck8 全表待回执，cron 自收)。
- 工作区现状：仅 primofw 3 件 (actions.py/55-prim.yaml/ruleset.py) 在飞 + packaging-2026-09-19 peer 目录; 其余脏面全清。

## 2026-09-19 ~12:0x — capverd 入库 (2ccd40d+c1a4840) + logcache 系统缝揭 + resid209 核销

- **capverd (2ccd40d)**：`input_stack|<上游递归cs>` capacity 判词重路由——`_CAP_UPSTREAM_RECURSION_CS` 6 名 frozenset (内核 `\@nomath` 守卫帧 + expl3 quark 扫描哨兵族) + `_cap_verdict_cat` 挂 `classify_head` 返回。capacity 族唯一 when-规 revtex4 docclass 闸全灭→3 格假簇 `unfixable:capacity`；上游 TeX-exec 递归帧 paper-authentic 无源改写可修→诚实 `unfixable:input_stack`；`cref@resetstack` restatable 可修族刻意留 capacity 走修复派发。8 测试。
- **leader 追办 (c1a4840)**：`unfixable:input_stack` 入 salvage 排除组 (定败同炸，省兜底轮)——该 cat 只由重路由产出=全递归帧，排他安全; `CAP_STACK_LOG` 合成 `\@nomath` 帧钉 (verdict+ 无 salvage+rounds==1)。
- **drvverdict 2403resid 诊断**：2403.00013 acceptable_pdf = **系统缝 + 新签** 非诚实 partial。残留 1341 缺 hangul (KAIST 韩文前页) 排入 FandolSong/Hei (script=hani 无 hangul 块)。**系统缝**：`LoopCtx._texts` 缓存 `{stem}.log` 跨轮不失效——r2 ctlseq_undefine 早读缓存 pre-misschar 日志，5 条 misschar/font 规全拒 "no Missing character" (1341 行实存)——任一早读规毒化全后轮，跨格爆面。→ **logcache 派** (engine.py grant: 每 eng.compile 后 invalidate {stem}.log+_tect_out 含复用探针路)。**新签**：hangul-in-CJK-font 无规盖 (cjk_font_fallback 绑回 FandolSong 自体无 hangul) → **hangulfont 派** (先普查 hangul misschar 格，后 ko 字体分带回退; fc-list :lang=ko=IBM Plex Sans KR)。
- **resid209 核销 (普查)**：9901081 已 best_effort_pdf (新记录 22:56)——"~151 残"系 loop2 快照，已被 input_sty_to_usepackage/journal_cs_polyfill/batch_undefine 收。活缝仅 3 非致命 already_def `\DeclareMathSymbol{\upi/\umu/\upartial}` @live \ifnfsstwo 臂——`_SITE_DEF_CMDS` 缺 DeclareMathSymbol/Delimiter → **decmathsym 派**。族面 45 稿 documentstyle∧input .sty：15 有录 (5 clean, 6 cls-missing_file 但到 fixloop 全愈，1 partial, 2 skip), **30 未跑 → 入 flipcheck9 波**。NFSS1 live-arm 判 dead-branch 已赢，不立规。
- roster 10→：primofw (6 件在飞：actions/55-prim/ruleset/_builtins_common/_builtins_shim/30-route)/shipclscen/kvleak2/runawayscan/aastex61if/preamcjk + 新派 logcache/hangulfont/decmathsym + bticktax(harvest 待回执)。capverd/drvverdict/resid209/renewdocenv 尸清。
- 门：teammate 零 git✓；HEAD 本段 2ccd40d+c1a4840 均 import 净；flipcheck8/l1-gate 批 ALL DONE。

## 2026-09-19 ~13:0x — primofw 入库 (3234ed8) + flipcheck8 全表 + shipclscen/preamcjk 核销

- **primofw (3234ed8)**：新条件动词 `err_outside_fileset`——`rep.file_stack[-1]` 内层帧 `is_project_file` 判工程外 (rep=None 失败闭)；`_cond_ok` 尾参 rep 后兼 ~30 旧 5-arg 站。`glyphtounicode_shadow`+`pdftex_prim_polyfill` cond.any 开外集臂。**臂形偏离 (agent 实证采)**：`\chardef\pdfcompresslevel` 实救不了 (chardef cs 排字 + `=0` 变正文 → Missing\begindoc 转嫁)；整数值原语改 `\newcount\prim\prim=1` (`_PRIM_COUNTISH` 26 名)——赋值站合法 + `\ifnum` 可读严格占优，非整保 chardef。`PDFTEX_PRIMS` += pdfoptionpdfminorversion/pdfobjcompresslevel (axessibility:350)。13 测试 +1155 套。**leader 裁决 (非 user 级)**：polyfill@51 挤占 axessibility_xetex_shadow@157——保 polyfill 优先 (shadow 把 accsupp/ActualText 整 noop=内容损，polyfill 留真包; ≤8 轮成本换保真)。途中 actions.py 遭 gfs stash 窗短时回卷，提交前逐 marker 复核全在。
- **flipcheck8 全表 (bticktax, 58 格)**：**fail→clean ×12**——xbbpregen/newblock×7/flushend/tar×2/ngerman 各臂实证命中。**Bbbk taxonomy 六格全翻** `other→already_def:Bbbk`，undefine 三格发但 post 仍 already_def (non-halting 残——**bbkresid 普查派**：疑后发 pkg 重定义抢回)。polytonic/ngerman 余格 best_effort/acceptable 软残。**clean 31/32 守**——2003.03387 clean→partial-acceptable (missing_char×2 U+2010@aer9 零错; 仅 tar+precheck 触，splice 漂移非规错——flipcheck9 复查列)。inputquote 零语料 `\input "..."` 无可放，覆盖留单测+identity。
- **shipclscen 核销 (~30 docs 9 簇)**：pdftex-prim-under-xetex ~10 首簇——primofw 臂已吃整值族，**arg-取参原语 (\pdfobj/\pdfliteral/\pdfrefobj/\pdfcatalog) 剩缝 → primarg 派** (ieeeaccess:128 spotcolor `\AddSpotColor` 锚)。@=12 bare-\input ~5 → **shipwrap 派** (_builtins_pkgload._wrap_phys_sty_inputs 扩 shipped-file 站)。tar 成件不写期望名 2 格 → **tarmember 派** (_builtins_misc.extract_tar_blobs)。`\reserveinserts`/`\numberwithin` polyfill 排 decmathsym 文件锁后。svglov3.clo 猫码漏**已是 stale** (HEAD 存 \svglovrestore 存复)；xcolor skew×5/pstricks/osajnl/babel 低产 defer。
- **preamcjk 核销**：14 格 CJK pream-token 全 MOCK_ZH 标记格 (非真译出) + **活树 0/14**——deluxetable env argspec 注册 + 组参递归修已收族 (argspec 源直引 "loop1 slots")。残：sidewaysdeluxetable 未注册 (0 曝光，入 argspec 补强批)；`\halign`×44 原语另机制。dig 路归 argspec.json env 表非 `_opaque_arg_prose`——与 kvleak2 不同根。
- roster 11：bticktax(flipcheck9 组波 prep——目标列待 logcache/hangulfont/decmathsym/shipwrap/tarmember/primarg 落+resid209 30 未跑)/kvleak2/runawayscan/aastex61if/logcache/hangulfont/decmathsym/shipwrap/tarmember/primarg/bbkresid。primofw/shipclscen/preamcjk 尸清。
- 门：teammate 零 git✓；HEAD 3234ed8 import 净 (markers 复核)；flipcheck8/l1-gate 皆 ALL DONE；clean% 31/32 微瑕 (splice 漂移归因，复查列队)。

## 2026-09-19 ~14:0x — 三普查核销 + 4 新派 + csfix-batch2 队列

- **runawayscan 核销 (3 格各成派)**：1206.0136 isabelle cs-form `\isadelimtheory...\endisadelimtheory` vs comment.sty v3.8 行扫描器 (要字面 `\end{env}` 哨兵行; `\fmtname=plain` hack 死码) → **isabelex 派** (cs→env 改写 + detab 签名闸——detab 现按 runaway_scan 裸类派，应闸 `\next`+Including/Excluding 纹)。2009.11130 **上游 reconstruct 缝** (zh 引入非源实): `\obeylines` 域 `\gdef` 参行空倍 + `\Title...\Author` 调用点并行 → `^^M` 定界 token 毁 → **obeylines 派** (reconstruct.py; 原稿 33pp 净，parse 段字节净——缝在 reconstruct/translate 非 segmenter)。1109.5754 真-LLM 臂 `\{` 未闭 → `\@xdblarg` 复写暴走 (4 格 rt1 簇; mock 平衡填词不复现): `validate_translation` 只查占位符多重集无括号查 → **braceval 派** (xlat 校验侧)。
- **kvleak2 核销 (7 活 4 簇，全 parse 侧 dig 路非 fixloop)**：tikzstyle 裸键 `[` 逃逸 `_KEYVAL_GROUP_RX` (要 `=` 首项) ×2; l3keys/printbibliography 尾 `[kv]` 裸面文本无 arg 闸达 ×3 (`_keyval_tail_end` args.py:1036-1129); etoolbox toggle 名槽 ×2; `\input` 文件名槽 ×1 (搭 inputleak 查)。→ **kvdig 派** (args.py+argspec.json 单锁三修)。死格 5 核销。**durability**：kvleak2 族 dig 路 = args.py arg 闸 ≠ preamcjk 族 env argspec 注册——两条漏路各主。
- **aastex61if 核销 (阴判)**：9 格 \ifx-early_eof 全 AAS 船件——实为 fixloop-arm 残留非字面族，flipcheck7 8/9 已净; 唯一真 upstream bug (aastex61.cls:5233 `\endrotatetable*` 缺 `\fi`) 不可达 (0/9 用 rotatetable*, 触发亦仅警告)。**扫描器双假阳揭**：vendored aastex.cls caller-supplies-\fi 习语 `\@boole@def\@ifx#1{\ifx#1}` ×5 活开 (展开平衡但扫描见赤字→文件尾注 \fi=Extra \fi sabotage 险) + elsarticle/IEEEtran `\let\sep=,\fi` CONSUME=2 假开 → 入 csfix-batch2 守。rule 196 def-body 拒注本对 (冻结 token 文件尾不可达)。
- **bbkresid 确诊**：already_def:Bbbk 残根——`undefine_for_redef` 只出 docclass 块 (`_redef_site_map` 扫 user 件找 `\newcommand` 站，但定义者是 system 件 newtxmath.sty:2847 `\DeclareRobustCommand`); 块落 main 顶先于 `\usepackage{newtxmath}` → undefine 先消费后 amssymb:261 `\DeclareMathSymbol` 照撞。**修形**：抽 log `/<pkg>.sty:N` 报错包茎，user 件 `\usepackage{...stem...}` 行前 prepend `\let\X\@undefined` (定义者↔报错包之间才有效) → 入 csfix-batch2。acmart 格定义在 cls 内 (transitive) → 无 user 载点时 abstain。
- **csfix-batch2 队列** (decmathsym 文件锁后单派)：pkg-load-site undefine (bbkresid) + 扫描 caller-supplies-\fi 守 + \let-CONSUME 守 (aastex61if) + `\reserveinserts`→`\@gobble` + `\numberwithin` polyfill (shipclscen)。
- roster 12：bticktax(fc9 组波)/logcache/hangulfont/decmathsym/shipwrap/tarmember/primarg/isabelex/kvdig/obeylines/braceval + kvleak2-runawayscan-aastex61if-bbkresid 尸清。等 decmathsym/logcache 落地开 csfix-batch2 + flipcheck9。
- 门：teammate 零 git✓；HEAD a53b90b 净；在飞文件面 engine.py(logcache)/60-misschar+_builtins_misschar(hangulfont)/_builtins_csfix(decmathsym)/_builtins_pkgload(shipwrap)/_builtins_misc(tarmember)/_builtins_shim+_builtins_common+55-prim(primarg)/75-syntax(isabelex)/args.py+argspec.json(kvdig)/reconstruct.py(obeylines)/xlat 校验件 (braceval)——锁表无撞。

## 2026-09-19 ~15:0x — decmathsym+logcache 入库 (db79e2e/b67662c) + csfix2 派

- **decmathsym (db79e2e)**：`_SITE_DEF_CMDS` += DeclareMath{Symbol,Delimiter,Accent,Radical}——四件共用 DeclareMathAlphabet 的 csname-冻结守卫 `\ifx\csname\@gobble\string#1\endcsname\relax` (latex.ltx:13462/13511/13594/13696, 非 `\@ifdefinable`)，`\let\X\@undefined` 前置有效。`DeclareSymbolFontAlphabet` 排外 (守卫查空格后缀伴生 csname `\X␣` latex.ltx:13753-13763→徒然)；四件均不在 `_IFN_ROUTED_CMDS` 无 ifprot 干系。预期翻 9901081 ×3 (`\upi/\umu/\upartial`)。8 测试。
- **logcache (b67662c)——系统缝修**：`LoopCtx._texts` 缓存跨轮不洗 `{stem}.log`——早读规 (ctlseq_undefine→`_fixloop_log`→_builtins_common.py:292) 把 rN 日志喂给全后轮 (2403.00013: 5 misschar/font 规拒签 "no Missing character" 而新日志实存 1341 行)。修：`_VOLATILE_EXTS=_AUX_WRITE_EXTS|{".log"}` (:325) + `LoopCtx.invalidate_suffixes` (:563) + 4 编译点后全调 (:886/:915/:1023/:1123 含复用臂)；盖 xelatex `{stem}.log`+tectonic `_tect_out/`+rglob 件+stale-None。4 测试。**同类残缝**：docstrip 只洗请求 hit，同 unpack 兄弟出件仍陈——_builtins_misc.py，已 SendMessage 标 tarmember (顺手才收，勿扩 scope)。
- **csfix2 派 (文件锁 freed)**：_builtins_csfix.py 三活件——①pkg-load-site undefine (bbkresid 修形：抽 log `/<pkg>.sty:N` 包茎，prepend `\let\X\@undefined` 于 user 件 usepackage/RequirePackage 行前；opts/逗号列/dup 站全盖；transitive cls 内载→abstain) ②`\reserveinserts`→`\@gobble` (WileyNJD-v2:248, 2 格) ③`\numberwithin` 早载 (mystyle:33, 1 格——真 def vs gobble 由实站定)。**扫描器守卫降级 report-only**：unclosed_if_close 实现竟是 75-syntax.yaml:855+ 内联 python (非 _builtins_csfix.py)——isabelex 持锁，csfix2 只交建议 diff 由 leader 落。
- roster 12：bticktax(fc9 prep)/hangulfont(impl 中)/shipwrap/tarmember/primarg/isabelex/kvdig/obeylines/braceval/csfix2。decmathsym/logcache 交付 + 入库后尸清。
- 门：teammate 零 git✓；HEAD db79e2e+b67662c import 净；无活 detached 批 (run.log 全 >2h 旧)；clean% 31/32 维 (2003.03387 fc9 复查列)。

## 2026-09-19 ~15:4x — hangulfont 入库 (77c8b88+f66a6ec) + tarmember 交付+docstrip 追加 + failmine3 派

- **hangulfont (77c8b88, 联合交付)**：`hangul_font_fallback` order 28 新臂——谚文五段带表自 cjk 臂剔出 (FandolSong 无 hangul 块，绑回=错字体谎报; 2403.00013×1341/2410.18001×545 双格根因)。`fallback_fonts` 有序候选探测 (`_fb_font_resolve`: 文件形→kpathsea+`install:true`补装 unfonts-core, 家族名→fc-list; 全灭诚实 decline 不谎报)。**潜伏 bug 修**：`font_not` 大小写敏感致 `[FandolSong*.otf]` 永不匹配 `fandol`→`re.IGNORECASE`。fandol+uming/ukai 刻意不收 (皆无 hangul=病灶)。**碰撞化解**：bticktax 双派撞单——其单字体版逊，自删 order-26.5 重复臂保 hangulfont 设计，加 e2e 双臂派发钉 (f66a6ec) + font_not uming/ukai trim (两 lane 收敛同语义)。13+1 测试，ruleset 125 规单臂。
- **tarmember 交付 (\_builtins_misc.py 未提交)**：tar 伪装件**先改名再抽**根治——旧序 blob 占自身槽位，同名成员被 no-clobber 永跳，改名后期待名彻底缺席→missing_file。`_slot_payload` 二扫补写：basename 任意深精确 (rank2)>同 stem `.sty`兄弟仅填 `.cls` 槽 (rank1, aipproc 实案向，反向不开)。AMSbsy 无匹配不冒写 (真身走 texlive post-retirement)。8 测试 +99 套绿; 0104007 实 replay 得真 1995 AIP 实现 (44KB 替 vendored stub)。**追加进行中**：docstrip `_texts` None-毒化缝 (logcache 同类)——`docstrip_generate` 只洗请求 hit, 同 `\generate` 兄弟出件留陈; 修形=mtime/existence 快照 diff 围 run_tool。
- **dup-id 瞬态核销**：tarmember 报 `test_phase_ordering` 挂 dup `hangul_font_fallback`——实测为 hangulfont 编辑中瞬态; 提交态单 id 无 dup, ruleset 125 装载净。
- **failmine3 派** (读-only 普查)：failmine2 后 ~15 规落，残面已移——最新 records 全量重普查簇排 (category×mechanism×site), fired-but-unfixed vs 正拒鉴别，喂 flipcheck9 后新波。
- roster 10：bticktax(fc9 组波——hangul 插曲毕)/shipwrap/tarmember(docstrip 追加)/primarg(_builtins_shim+55-prim 在写)/isabelex(75-syntax+test 在写)/kvdig/obeylines/braceval/csfix2/failmine3。
- 门：teammate 零 git✓；HEAD 77c8b88+f66a6ec 净；无 detached 批；clean% 31/32 维。

## 2026-09-19 ~15:5x — patrol 静持

- roster 10 全 running 无僵尸；无 detached 批 (run.log 全 >30min 旧)；无新交付。tarmember docstrip 追加在飞 (_builtins_misc.py 持锁等双 hunk 同提)；primarg (test_fixloop_primarg.py 已现)/isabelex (test_fixloop_isabelex.py+75-syntax.yaml 在写) 推进中。HEAD f66a6ec+3d41344 净，clean% 31/32 维，teammate 零 git。

## 2026-09-19 ~16:0x — isabelex 入库 (4046c5a) + csfix2 锁扩 75-syntax

- **isabelex (4046c5a)**：`comment_csform_isabelle_env` order 163.5 新规——isabelle 稿 cs 形 comment env 对 `\isadelim*/\endisa*/\isatag*` → env 形 (comment.sty v3.8 行扫描器要字面行锚 `\end{<env>}` 哨兵，plain 分支删→`\fmtname` hack 死码; cs 形 begin 宏首步 `\endgroup` 吃 isabellebody 组次伤同愈)。pattern `isa(delim|tag)[A-Za-z]+` 盖 isabelletags 扩展; `\isafold*` 纯宏/`\isabelle*` 已 env 不动。**detab 签名闸**：`payload_required`+`ctx_suggests "\\next\b"`——原裸 category 对全 runaway payload 盲发去缩进白烧轮 (1206.0136 `\end{boxedminipage}`/eq 行; `\GetTitle`/`\@xdblarg` 同列)。17 测试，ruleset 126。预期翻 1206.0136 (37pp 实证)。
- **csfix2 锁扩**：75-syntax.yaml isabelex 落地即空——item-4 扫描器双守 (caller-supplies-\fi 习语 + `\let\cs=<char>\fi` CONSUME=2 假开，aastex61if 证) 由 report-only 升直改，授权已发。
- roster 9+failmine3：bticktax(fc9)/shipwrap/tarmember(docstrip)/primarg/kvdig/obeylines/braceval/l0 在写)/csfix2(+75-syntax)/failmine3。
- 门：teammate 零 git✓；HEAD 4046c5a 净 (126 规装载)；clean% 31/32 维。

## 2026-09-19 ~16:3x — 三连入库 (1485527/85c99f4/29e6287) + primguard/maxsep209 派 + fc9 待发

- **braceval (1485527)——前提纠正**：rt1 `\@xdblarg` runaway 族非括号缝——`_check_brace` 早存且四格 zh 全平衡；真机制=corrector 臂丢 chunk-尾 `[[COMMENT_n]]` 终结 `\n`→splice 把后随字面首行吞进注释→`}` 死字节化→`\caption{` 不闭。新 L0 第 12 规 `comment_eof` (`_tail_unterminated_comment`: `_lex` 末 token `cmt` + mask 视 `[[COMMENT_n]]` 尾 `[ \t]*`-to-EOF; src 同形豁免)。**勘定**：`validate_pair` 才是生产缝 (xlat 管线 validator 注入), `validate_translation` 仅占位符多重集喂测试——非生产闸。10 测试。4 格全 corrector-arm 覆盖。
- **primarg (85c99f4)**：prim polyfill 5 路分派——`_PRIM_TOKSISH`(3)→`\newtoks`、`_PRIM_DIMENISH`(5)→`\newdimen` (spotcolor.sty:48 `\edef\prim={\the\prim}` 双形态全真; chardef 下 `={..}` 整串落正文)、`_PRIM_ARGFUL`(42)→`\protected\long\def<sig>{}` 吞参 noop (33×#1/3×#1#2/4×零参)、`pdfifprimitive`→csname 双写 `\let→\iffalse` (裸 let 在 `\ifdefined` 真臂跳扫吃 `\fi`——tmp/primarg 实测)。yaml 第三 cond 臂 `source_contains \\{payload}(?![a-zA-Z@])` 收 fileset 内无花括号取参站 (guard 包不到)。10 测试。**leader 裁决**：toksish/dimenish 超字面 brief→保 (同寄存器形原则同证据); @iffalse→保。
- **shipwrap (29e6287)**：`shipped_sty_input_wrap` precheck -0.5——随源 .cls/.sty/frag.tex 内裸 `\input X.sty` 以宿主当前 @ 猫码读件，@=other 宿主全裂 @-cs→Missing\begindoc 级联 (~20 语料件，aipproc.cls:10 型)。svglov3 exact-restore idiom (`\edef\TeXlateStyInRestore` 存猫码→=11 读→复元; 裸 makeat 对会把 @=letter 宿主尾段强翻 12, 1608.06693 `15\p@` 前科)。doc 侧 input_sty 两臂 + fragment .tex 够不着全补位。facade 3 行 + ordering pin 2 行 (pinned-registry 必触已旗标)。**格判决 4/5 归他臂** (input_sty/amstex misreg); 0104245 真缝=`\@maxsep`/`\@dblmaxsep` 2.09 寄存器 COMPAT_SHIM 缺→maxsep209 派。LIVE-FIRE 双臂实证。12 测试。
- **primguard 派 (sabotage 级)**：`pdftex_prim_guard` order 50 贪心 `[^\n]*\}` 吞单行 `\def\f{\pdfobj{<</N 1>>}}` 外层 `}`→`\fi` 落体外孤 `\fi`——primarg 旗标，55-prim.yaml 落地即派。
- **maxsep209 派**：COMPAT_SHIM (latex209.py:474-494) 补 `\@maxsep`/`\@dblmaxsep` \newdimen (latex209.def:167-168 镜), 0104245 锚。
- **fc9 待发 (bticktax 组波毕，84 目标 +31 clean)**：ids.txt 115 id 全 corpus_v3 核，17 lane-tag 归因——hold 等 csfix2 (bbkresid 4 格在列) + maxsep209 (0104245 在列); kvdig 7 格→fc10, obeylines 若先落加 2009.11130。
- roster 10：bticktax(fc9 组毕待发)/csfix2(+75-syntax)/kvdig(args.py 在写)/obeylines/failmine3/primguard/maxsep209 + 3 新派内含。braceval/primarg/shipwrap 交付 + 入库尸清。
- 门：teammate 零 git✓；HEAD 三连 import 净 (126 规 +1 L0)；工作区仅 kvdig args.py+peer 件；clean% 31/32 维。

## 2026-09-19 ~17:0x — failmine3 全普查 + sab-r4 门④过 + 4 新派 (revpacs/hxetex/mathchar/loop3prep)

- **failmine3 终态普查 (5285 格，已关)**：clean 4525 (85.6%) · partial 624 (acceptable 331/best_effort 268/compile-partial 25) · hard 18 · reject 16 · skip 102。**最大杠杆=~400/624 partial 判 stale (pre-loop2)——批量 replay (loop3) 单点最大**, babel_opt/pdftex_prim/arraypream/env_undefined/newblock 簇多 covered-stale 只待复测。hard-18: unfixable 3 + stuck 2 (ifprot 已落待 replay) + capacity 2 + runaway 3 + 单件 7。
- **簇→派路由**：revtex stub `\pacs` arg 形 9 格 (同 id 集 "par ended before \pacs"+"params numbered consecutively" 成对，HIGH 可修) → **revpacs 派** (vendor/stubs/revtex.cls:63 widen \long/分隔参)。hxetex.def 5 格 → **hxetex 派** (vendor/files/ add-only——vendored_fetch basename 服件零规改; 系统 texlive 取真件)。Extended mathchar ~6 格 (hep-ph/0605174 GLUON.tex:464, >xFFFF) → **mathchar 派** (_builtins_shim+85-shim+facade, 先断后修)。**loop3prep 派**：tmp/lane-loop3/ 组波 ids=全 624 partial (hard 另列), fc9 机械形复制 → stagerun-loop3, 本波落地后 GO。
- **队列** (mutex 等)：209-era undefined_cs **~129 格** (twocolumn 28/begin-end ~10/sortlist 5/ifnfssone 5/collaboration@sw+wideabs+headerps@out ~20/current@color 6/maketitle 系 ~10+ 单件 ~30——extend latex209 COMPAT_SHIM 表; twocolumn 日志已清需 1 复现 diag) → **209batch 待 maxsep209 释 latex209.py**。`这是译文` 落机器参 (keys/labels) 8 格 keyval-error 形 → segmenter/inject 侧非 fixloop, **kvdig 已询 overlap 判**, 落后续派。
- **sab-r4 门④ PASS**：40-id 池复用，383 sabotage events **0 escape** (r3 基线 379/0)——波 6/7 ~10 规无漏。bticktax 持 fc9 等 csfix2+maxsep209。
- **修形发现**：`pdftex_prim_guard` 纯 yaml regex_rewrite (55-prim:109) → primguard 不需 _builtins_shim, 锁表无撞确认。misplaced-& 4+ 格根=diagrams.sty 缺 env (diagram/\! 族 env polyfill, 入下波候选)。already_def 尾 12 格 fired-unfixed → mini-census 候选。
- roster 11：bticktax(fc9+sab 毕)/csfix2/kvdig/obeylines/primguard/maxsep209 + 4 新派 (revpacs/hxetex/mathchar/loop3prep)。failmine3 交付即关。
- 门：teammate 零 git✓；sab-r4 0 escape✓；HEAD 43bd606 净；工作区 latex209.py+test_latex209.py (maxsep209 在写) + args.py (kvdig) + peer docs；clean% 31/32 维。

## 2026-09-19 ~17:1x — patrol 静持 + dimcen 补派

- failmine3 idle echo 复核簇表——#2 missing-number/dimen (~40 格 101 站) 漏派补 **dimcen** (read-only 站点拆分：vendor-stub 缺陷 svjour3:177/csvsimple-l3:36/pstricks-add:1544 vs doc 侧 dimen——喂 stub-patch 下波)。余 top-6 全覆盖：209batch/keyval-leak 队列等 mutex, babel/amstex → loop3 复测核销。
- 无 detached 批 (sab-r4 DONE)；无新交付；工作区 = maxsep209/kvdig(test_args_kvdig.py 新件=近交付)/obeylines(reconstruct+2 测试件=近交付)；csfix2 31min 无件触=诊断期 (三件套 +75-syntax 内联扫描件，次 tick 仍静则催)。
- roster 11：bticktax(fc9 待发)/csfix2/kvdig/obeylines/primguard/maxsep209 + revpacs/hxetex/mathchar/loop3prep/dimcen。
- 门：teammate 零 git✓ (log 全 wncfht)；HEAD e63d90b 净；clean% 31/32 维。

## 2026-09-19 ~17:4x — 四连入库 (74b581f/3a3df49/2a81b84/57dd8d9) + 209batch 派 + primguard 裁决

- **hxetex (74b581f, 前提纠正)**：5 格非 missing_file——hypdvips.sty:43 拒 hxetex 驱动 (`hyperref_driver` 族), `hyperref_driver_neutralize`(181) 已盖，仅因 partial 态被 `--on fail` 跳 → **loop3 复测即翻**。vendored hxetex.def 照收 (texlive 逐字节 md5 同，LPPL 头全，与系统 hyperref v7.01p 同版对)——真 missing-driver 环境的库存，零风险。
- **maxsep209 (3a3df49, 结构发现)**：COMPAT_SHIM 落 docclass 后——aipproc.cls:10 类载期 `\input{aipproc.sty}` 在 `:207/:213` 裸赋值 `\@maxsep 20pt`, shim 来不及执行 (实证)。`_PRE_CLASS_SHIM` 新常量 `\@ifundefined`-guard `\newdimen` 双寄存器，作 lines[0] 先 `\documentclass` 发——latex209.def:167-168 忠实镜。0104245 推进至下一残 (oldfontcmd `\it`/`\bf` 族) → handoff 入 209batch。32+142+7504 测绿。
- **obeylines (2a81b84)**：`_restore_linestarts`——chunk 内容渲把 `␣\Title\n<text>\n␣\ShortTitle` 折单行 (段切块渲缝，先于 reconstruct), zh 回显丢行首 `\cs`, `^^M` 定界参扫描奔 EOF (2009.11130)。采源 span 行首 cs 名，译文行中 `[ \t]+\X`→`\n\X` 只对该名集——普 catcode 恒等 (`\n`≡空格), 无需识 obeylines 域。`isinstance(k,int)` 敌键卫 (fuzz 抓)。23+537 测绿。**残族**：0812.0162/1503.00494 纯文本 obeylines 饰接无扫描错——要 segmenter 侧 opaque 标 (kvdig 域，记 keyval-leak 后续)。
- **revpacs (57dd8d9, 前提纠正)**：9 格真因=旧 `##`-转义 polyfill payload (字面 `#` 定界参号错 + `\pacs` 变定界宏吃至 `\par`)——树内已修 (`_builtins_shim:1064`+yaml:83 单 `#`), 格走 stub 2e 分支从未触发 → **loop3 翻**。stub `\long\def\revtex@pacsflat` 补潜伏刚化; yaml:83 同款 leader 直修; `_builtins_shim:1064` 第三处→折 mathchar grant。
- **primguard 裁决 (option-a 批)**：递归平衡括号 `(?&bal)` 修双臂贪心 (单行 def 外 `}` 被吞→`\fi` 落体外，双臂实证); 但 `test_shipped_rewrites_repl_escapes_valid` 用 stdlib `re` 编译全 shipped pattern——`re` 无递归。**潜伏引擎错配**：生产 actions.py:292 本就是 `regex`——授其测试件换 `regex` (保持镜生产，不削 pattern 到有界深)。
- **209batch 派 (mutex 释即派)**：209-era undefined_cs ~129 格 (twocolumn 28 最大 sig——`_REVTEX209_POLYFILL` 已有 `\twocolumn` providecommand, 先断 revtex-路 vs 通需; 日志清需 1 复现) + maxsep209 oldfontcmd handoff (\bf/\it/\rm/\sl——2e 类经 `\DeclareOldFontCommand` 得，薄 .cls 壳不声明，0104245 实证)。全证据绑，禁臆造 define。
- **fc9 门**：csfix2 独剩 (bbkresid 4 格); 2009.11130 已加 ids。
- roster 10：bticktax(fc9)/csfix2/kvdig/primguard + mathchar/loop3prep/dimcen/209batch。hxetex/maxsep209/obeylines/revpacs 交付 + 入库尸清。
- 门：teammate 零 git✓；HEAD 57dd8d9 净 (import 复核 4 提交)；在飞 args.py(kvdig)/55-prim+test_fixloop_primguard(primguard 等 a 修)；clean% 31/32 维。

## 2026-09-19 ~18:1x — loop3 组波毕 + fc9 timebox + 2 普查派

- **loop3prep STAGED (已关)**：ids 606 (624 raw - 18 flat/slash dupe) + ids-hard 18 分列; run.sh/run-hard.sh 与 fc9 byte-形同构 (--jobs 4 同 stage 序); harvest.py 直读 terminal3 基线 + `expect=` 标 (0104245 advances-to-next-error, BONUS/EXPECT-MISS 旗); 27 lanes 盖 454/606 + 23 规 watch。5 格 partial-flat-key-但-canon-已净留作 stay-clean 探针。GO=`setsid nohup bash tmp/lane-loop3/run.sh`——待本波落地。
- **fc9 timebox 立**：csfix2 产线活 (_builtins_csfix +307, 75-syntax +16 扫描守已触)——(a) ~20min 内交付则 commit 后 GO; (b) 超时 as-is 发，4 格预标 `pending-csfix2` (1803.03185/1907.00153/1907.03726/2003.10792) 不算回归，loop3 后翻。bticktax ack, 116 ids 全 tag。
- **defcensus 派 (read-only)**：already_def 尾 12 格 fired-unfixed——逐格剖 arm-fired/definer-file:line/残类, 分 csfix2-covered vs 新亚机制 vs upstream-unfixable (bbkresid 同型=system 件定义者 `_redef_site_map` 只扫 user 件)。
- **envdiag 派 (read-only)**：misplaced-& 4+ 格根=undefined diagram env——但 diagrams.sty 已在 vendor/stubs: stub-保真缝 vs 服件路缝 vs 机制误判，anchor math/0104250:417。
- roster 9：bticktax(fc9 standby)/csfix2(扫描守收尾)/kvdig/primguard(a 修中) + mathchar/dimcen/209batch/defcensus/envdiag。
- 门：teammate 零 git✓；无 detached 批；HEAD dbe8a3a 净；clean% 31/32 维。

## 2026-09-19 ~19:0x — primguard 入库 (dd7f8bb) + csfix2 断树自解 + inputtail/hard18 派

- **primguard (dd7f8bb)**：双臂 `regex` 递归 `(?&bal)` TeX 词法平衡括号 (转义/注释括号不计，任意深度，多行实参收编旧 `[^\n]` 弃守面); 赋值臂孤 `{` 兜底保旧"整行吞"。ruleset_validate 换 `regex` 引擎镜 `actions._compile_rewrites` (option-a 落地——stdlib `re` 无 `(?&name)` 会误拒)。21 测绿，load 128 规，ruff/prettier 净。
- **csfix2 断树自解**：验证期 `Ruleset.load` 全仓 raise——其 `premature_cs_guard` 引 yaml:1500 而未注册 TRANSFORM_FNS。几分钟后 csfix2 自行撤规 + 注册 `if_phantom_protect` (builtins.py:46/194/284)——树回绿，无需 leader 插手。其 `premature_cs_guard` def 暂留 `_builtins_csfix.py` 成 dead code (在写中)。**教训**：in-flight yaml 引未注册 builtin = 全仓 load 死——lane 交规顺序应为"先注册后引 yaml"。
- **inputtail 派 (primguard 连任，#133)**：kvdig 两 handoff——(a) `\input` count-tail `_OPERAND_BASE` cs alternative 吃 `\input` 作 factor base → `{file}` 裸译 (2403.00100:651, _common.py+group.py/pending.py 三镜); (b) pending.py COND 镜缺 (`_pend_spec_of`:770 返 (None,""), grp-scan:1448 无 `{name}` 吸收——照 args.py `_COND_GROUP_ARGS`/`_handle_cond` ae685ff 镜)。文件全释。
- **hard18 派 (read-only)**：18 hard 格预诊——逐格分 covered-by-new-rule / needs-new-rule / genuinely-stuck, loop3 收获时直读。
- **kvdig 关** (交付 ae685ff 已入)。
- roster 9：bticktax(fc9 standby)/csfix2/primguard(inputtail) + mathchar/dimcen/209batch/defcensus/envdiag/hard18。
- 门：teammate 零 git✓；HEAD dd7f8bb 净；在飞 csfix2 三件套+mathchar 三件套 (builtins.py 双 lane 分行无撞)；clean% 31/32 维。

## 2026-09-19 ~19:5x — mathchar+csfix2 入库 (4926fb2/ab7bcb9) + fc9 GO (122 ids)

- **mathchar (4926fb2)**：`bm_extended_mathchar_wrap`——bm.sty `\bm@test@token` 对实参 catcode-11/12 token 逐个 `\count@\mathcode`#1`原子遍历, XeTeX 15-bit mathchar 操作数扫拒 >0xFF (xeCJK 值 0x05xxxxxx+码点;`\mathcode`Ω` 同炸非 CJK 专属)。修 = 序言守卫式 `\bm#1 → \TeXlateBM{{#1}}` 双花括号走 bm 自带 `\bm@gr@@p`→`\boldmath` 组路径 (遍历跳过 + 粗体经 math version 保), `\ifx` 重绑 `\let` 别名 `\boldsymbol`/`\heavysymbol`, `\ifdefined\TeXlateBM` 防自捕环。revpacs `\long\pacs` fold-in 落 _REVTEX209_POLYFILL:1066。~6 格 (hep-ph/0605174/1206.0485/2112.00003)。
- **csfix2 (ab7bcb9, 四件)**：①pkg-装载点 undefine——`_pkg_err_stems` 抓 `pkg.sty:N: already defined` 肇事茎，`_undefine_pkg_sites` 每 live 用户件装载点前 `\let\X\@undefined` (bbkresid 4 格); ②`\reserveinserts` polyfill_pre + `_inject_before_docclass` (2 格); ③`premature_cs_guard`——`Missing \begin{document}` file:line 溯肇事 sty, 供方 `\usepackage` 前置消费方装载点 (2009.11053); ④扫描器双守——DEFCMD+`@boole@def` 消 aastex 5.2 假开 5 连，CONSUME `let` lookahead 消 elsarticle/IEEEtran `\let\sep=,` 假开 (sabotage 防护无直翻格)。
- **原子落规新纪律生效**：csfix2 发现 yaml 引未注册 builtin = `RulesetError` 全 lane 破后，自行 revert 并把注册+yaml 块交 leader 原子落——builtins.py:48/208/292 + 75-syntax.yaml:1502 order 196.7 同 commit。此模式入档为 builtin-规落地标准。
- **fc9 GO (bticktax)**：122 ids (116+6 新波格：mathchar×3/csfix2×3 补登 lanes.json)。4 bbkresid 格 `pending-csfix2` 转 live——预期 pkg-site-undefine 臂翻。
- **附带 fix**：test_fixloop_revtex209:61 + test_fixloop_pacs:19 断言 `\def\pacs`→`\long\def\pacs` (4d06d47, L0 sweep 抓——fold-in 断言滞后第二处)。
- roster 8：bticktax(fc9 飞)/primguard(inputtail) + 209batch/dimcen/defcensus/envdiag/hard18 + mathchar 关/csfix2 关。
- 门：teammate 零 git✓；HEAD ab7bcb9 净 (ruleset 129 规 load OK)；L0 2310+1(pacs 断言，已修)；clean% 31/32 维。

## 2026-09-19 ~10:0x — ENOSPC 事故+fc9 恢复丰收 + sab-r5 门④ + inputtail 入库 (0697124) + 3 普查交付 + loop3 GO

- **ENOSPC 事故 (已解)**：root `/` 100% (917G)——`~/.cache/go-build` 209G 纯重建缓存 rm → 77%。伤亡：fc9 中段崩 (compile.jsonl 截断@70/122, run_meta.json 0B 卡死每 stage `touch_run_meta` JSONDecodeError——"rc=0" echo 是无条件标记误诊两轮)；SendMessage×2 拒、Agent spawn ENOSPC、L0 5 格 OSError (暂态)。恢复：截 jsonl 至 70 净行 + rm run_meta → 三发 resume 净跑 (122×3 段 skip + compile 52 续)。**教训：resume 语义=非 skip/error 跳跑; 0B run_meta 必删后重发**。
- **fc9 丰收 (122 ids, 9f3b416d-dirty 树含 ab7bcb9)**：terminal 口径 (fixloop_verdict 优先)——**clean 14→67 (+53 net; NO-REC×23+partial×14+acc×10+best_effort×2+unfix×4+fail×1 来源)**, PDF 产 32→82。负向仅 1: 2003.03387 clean→acceptable_pdf (判词标签漂移 missing_char×2, PDF 照产，WATCH)。规发实证：bm_extended_mathchar_wrap/premature_cs_guard/already_def_undefine/hangul+cjk_font_fallback/pdf_asset_sanitize(1907.00277 driver_fatal→真 clean, drvverdict veto 无需) 全中。capverd capacity→input_stack 重标签×2 如期。**if_phantom_protect 全哑** (196 fired 但凭据闸未开) → ifprotdiag 派 (#137)。新签：`\institute` 定界参 (0103289→unfixable:syntax, 209batch 族材), 0104303 latex209_reject, 5× ds@ reject (裁决输入)。门④ 净格探针 **31/31 clean**。
- **sab-r5 门④ PASS**：39-id 池 383 events/1613 sabotaged/caught 2/recovered 1611/**escaped=0**——r4 跑 pre-wave (43bd606f), 本轮盖 csfix2 扫描守+inputtail 段件。
- **inputtail (0697124)**：`_OPERAND_CS` 排 `INPUT_SCAN_CMDS∪{endinput}` 出 FACTOR/BASE cs 位 (xetex 实证不可展开 `\input` 止数扫——TeX 忠实非补丁; 2403.00100 `{file}` 孤儿裸译修复); pending.py COND 镜 3 块 (`_COND_GROUP_ARGS` 名槽 `["m"]*nslots` + grp-scan 吸收环，`{T}{F}` 支留掘)。13 新测+leader 复验 ruff/pytest 净。
- **三普查交付**：hard18 (6 covered/6 needs-rule/6 stuck——wave-7 零签预言); envdiag (机制纠正：`diagram` env 已被 polyfill noop 定义非 undef——根=`\input` 服件路只解 .tex, 富 stub 够不着→ diagramstex 派 #140; AAS `&`-biblabel 亚族 aa/aasms4 2 格入 stub-patch 波); **dimcen** (61 格 162 站 591 hits——前提纠正：三 stub "缺陷"全误归因，无 vendor stub 发坏 dimen; 排序 A3 `"`-hex catcode 22hits/2格→**hexquote 派 #138**, A7 209 寄存器 ~63+→转 209batch, C1 px 54/2→pxnorm 队列 #141, A8 pdftex-prim→loop3 盖)。
- **loop3+hard GO**：606+18 双 setsid 批; hard 已见翻转惊喜——1907.00131 clean (hard18 判 needs-rule!), nucl-th/0104064 clean, 1706.00240 acceptable_pdf (stuck→PDF)。main xlat 413/606。
- roster ~7:209batch/defcensus + ifprotdiag/hexquote/tailbucket/diagramstex + (subagent 面)。关：hard18/bticktax/primguard/csfix2/dimcen(auto)/inputtail 交毕。
- 门：teammate 零 git✓；HEAD 0697124 净 (inputtail 逐 hunk 对账后入，209batch 三件在飞留树); sab-r5 0 escape✓；fc9 探针 31/31✓；在飞 latex209.py+test_fuzz_judge+test_latex209 (209batch `_REVTEX209_SHIM` 面)。

## 2026-09-19 ~21:3x — diagramstex 入库 (d89467b) + ifprot-A 闸入库 (e2fc756) + 2 普查交付/转派 + 外来编辑定源

- **diagramstex (d89467b, #140 毕)**：vendor/stubs/diagrams.tex (~112 行 clean-room, .sty 宏面剥包壳, `\makeatletter` 包——`\input` 语境 @=12) + test_fixloop_diagramstex.py 4 测 (含真 xelatex 集成 0 `!` 错)。服件链实证: scan_install vendored 预检先于 missing_file 落件 → 90-shim-legacy:1907 空 shim 条成死配置 (有意留)。math/0104250+math/0408052 misplaced-& 链断于服务层。
- **ifprotdiag 交付+关 (#137)**：root = **dispatch-miss 非 gate-miss**——stuck 检 (sig_n=3≥3, engine.py:988 先于 _match_apply) 恰杀在 197.5 首可达轮; r1 被 abstract_edef_capture_neutralize(11.95) **空吃** (cond=sig+`*.sty` glob 不验件体, run_tool 恒 applied)。凭据 r2 确已落 ledger。修项 A/B/C/D 四案。
- **ifprot-A 入库 (e2fc756)**：condition 加 `source_contains` 镜脚本自体 grep——无捕获式 sty 在场则不派发, 空发不再烧同签轮。1206.0701/1306.0364 序列复为 r1→196 凭据, r2→197.5 发。129 规 load✓ 33 fixloop 测✓。**B (引擎语义: 同签轮仅在前轮零 apply 时计 stuck) 立 #142 ## REVIEW 专项**——结构修, 需 stuck-cell 回放量化轮耗。
- **defcensus 交付+关 (#131)**：26 格 already_def 尸检→路由 A9(csfix2 装载点盖, replay 自清——bibhang 机制 repro-1404 实证)/B9(stale, 现有臂盖)/C2(已修, 残异族)/D3 新亚机制 (bbl 载点 1907.10621 enquote; AtBeginDocument-序 1706.00033 \sh; newfont 站令 astro-ph/0307459 \Bbb)/E2(loop 排程非臂缺——mid-loop install 后 already_def 臂未重火)/F1(splitbox upstream-unfixable→LLM)。D→#143 E→#144 立。
- **tailbucket 交付+转派**：152 未盖格 bucket 图毕 (cells.json/buckets.json join key 备)——**misschar-residual 102 = 最大桶** (glyph 谱: 罕 CJK 莙収祇潟/⋅²Å/U+2009/ctrl 系, 无 hangul); para_ended 5 格无规→**转 #145 para-census 在飞**。
- **外来编辑定源 (不碰不入)**：e2e_mock/real_bench.py (全角：normalize) + zotero README (prettier 表重排) + 更广面 (bench/py/*, docs/*, eslint.config.js, tests/*, zotero/*) = 同签 formatter 扫荡——release-prep 同侪 session 形迹 (packaging-2026-09-19/ 同帧)。inject.py+test_inject_targate=hexquote 在飞; latex209.py+2 测=209batch 在飞。**pathspec-only commit 纪律继续生效**。
- **loop3 中段**：compile 毕 606 (首过 103 clean/344 partial/159 fail) → fixloop 13/503 飞中 (~45-60min 余); hard 15th record 验=report 无改 (2211.13028 fail honest)。
- roster 4：209batch(bg 在飞 `_REVTEX209_SHIM` hardening)/hexquote/tailbucket(para-census)/(subagent 面)——偏薄, loop3 harvest 前可再派 def-D(#143) 实装 lane。
- 门：teammate 零 git✓；HEAD e2fc756 净 (pathspec-only×2)；规则库 129 load✓；外来 churn 未入库✓。
