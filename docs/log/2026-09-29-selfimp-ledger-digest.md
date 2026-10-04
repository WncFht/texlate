# selfimp 常驻环台账蒸馏（2026-09-18~20）

> **结论**：selfimp 常驻环（overseer-selfimp）在 2026-09-18 09:10 至 09-20 21:15 约六十小时内，以「派 lane → 收割 → 逐 hunk 归因 → 落账 → 门禁复验」循环驱动九十余条车道/普查、约一百二十个 leader 署名提交，fixloop 规则库由约 125 条扩至 209 条（09-20 口径）。质量侧建成 esa2 评审协议与 frozen-300 回归门（qualbase n=1200，stated 92.86 / median 95）；修复侧以门①–⑤门禁配套 flipcheck/loop/sabotage 复放机制，loop2 清盘重建面救回 526/619（85%），loop3 单波翻净 271/606。原稿为 `tmp/blob-ledger{,2..9}.md` 九份 append-only 快照，本文件是归档蒸馏，逐格取证以原稿为准。
>
> **状态**：已完成
>
> **日期**：2026-09-29

## 源件与口径

- 源：`tmp/blob-ledger.md` 与 `tmp/blob-ledger{2..9}.md` 共九份快照。逐字节比对确认卷 1–8 均为 `blob-ledger9.md`（1,774 行）的严格前缀——卷 9 即全量，前八卷按其增量行段各自归节，不重复叙述。
- 卷段划分（以 blob-ledger9.md 行号为口径）：卷 1 = L1–1380；卷 2 = L1381–1390（+10 行，约 19:15 巡检）；卷 3 = L1391–1399（+9 行，约 19:35 nfssfd 收割）；卷 4 = L1400–1407（+8 行，约 19:55 missmath 收割）；卷 5 = L1408–1414（+7 行，约 20:15 共享 index 警报）；卷 6 = L1415–1422（+8 行，约 20:35 wrapromote 收割）；卷 7 = L1423–1430（+8 行，约 21:00 静默巡）；卷 8 = L1431–1434（+4 行，约 21:20 守衡）；卷 9 独占增量 = L1435–1774（+340 行，约 21:45 至 09-20 21:15 收官）。
- 时间口径：台账 tick 时标非单调（多会话并行 append 互插），本蒸馏按事件链组织而非逐 tick 复述；一切计数注明口径日期，loop 格数差异源自层化扩展与冻结快照时点。
- 会话代号沿台账原样保留（leader 会话接力 texlate-5d → texlate-ff → texlate-cf 等，qual 侧 texlate-d9，跨会话 peer texlate-02/13/21/48/bb 等仅在对账与撞区协调处出现）。敏感面已按 `docs/MAINTENANCE.md` §8 政策改写为语义形。
- 同日粒度大事记见本目录 [README.md](README.md) 的 09-18/19/20 三节；机制族谱与假设生命周期见 [../research/methods/2026-09-19-selfimp-skeleton.md](../research/methods/2026-09-19-selfimp-skeleton.md)，esa2 协议规格见 [../research/methods/2026-09-18-xlat-quality-eval.md](../research/methods/2026-09-18-xlat-quality-eval.md)，selfimp 环设计见 [../research/methods/2026-09-18-xlat-selfimp-prompt.md](../research/methods/2026-09-18-xlat-selfimp-prompt.md)。

## 战役总貌

三日战役由双环并行构成：compile/修复侧 selfimp（texlate-5d 系）与翻译质量侧 selfimp-qual（texlate-d9），共享同一 append-only 台账。修复侧主线是「records 驱动普查 → 车道归因/实修 → flipcheck 复放实证」：failmine/tailbucket/firedunfixed/chronic347 等普查道逐轮把残池切成同质族，车道以「先证根因、后落规则、顺带真纸验证」为常态工艺，规则库、taxonomy、vendor stub、segmenter/argspec、inject/normalize 各面同时推进。质量侧主线是「协议换代 → 基线 → 回归门」：esa2 单发协议（stated100 主分 + derived100 自洽校验 + 双裁 contested 通道）替换旧 1–5 分制，qualbase 1200 chunk 基线落地后冻结 300 钉子集作回归门，XCOMET-QE 建第三族三角臂。全程伴生的是多会话共仓工艺：私 index + pathspec-only 提交、共享 index staged-D 巡检、peer 撞区互斥协调、replay 波与 impl 车道之间的活树读写互斥（replay-mutex）。

## 卷 1 主体（blob-ledger.md，L1–1380）

### 环启动与 wave-1 二十三车道（09-18 09:10 起）

- 基线口径（09-18 09:10）：mechanisms.jsonl 210 条（covered 68 / partial 134 / implemented 8）；loop1 records 5124 格 scorecard pdf 97.89% / clean 84.99%；leak 0.040%（dollar 族 57 条残留为最大单族）。pytest 基线钉 6213 绿（HEAD eafa7b5）。
- wave-1 发车 23 lane：A1–A5 测量面、B1 mock 基线批、B2 六篇回归、B3a/b/c 分族归因、C1-scout 分族（122 唯一机制 → 12 族 L1–L12 车道图）、C2 dollar 族、C3 规则、C4 术语表、C7 server 裁决备忘、C8 normalize 拆分、C9 fuzz、C10 corpus expand+orphan、C11 上游挖掘、RA–RE 重审计批。
- 里程碑 11:10：c2 `31c432e` dollar 族收口——孤 `$$`/孤 `$`/`\$` 三形归 `[[CMD]]` 单项保真，parsebench-v3-c2dollar leak 0/136049（0.040%→0.000%）、identity 1955/1955，单类四年债清零。
- b3 族归因收齐：undefcs 49 票 / syntax 37 票 / other 30 票；verify-replay 74/74 零 dirty（66 clean + 8 partial）。b2 六篇回归三证闭合立账 W157–W161（inject mathgroup 注入时序被定为最大单点风险源）。
- 事故：nightwatch 首巡抓 rt1 批 `ORPHANED_FD`——进程持有已删 `records/xlat.jsonl` inode（孤儿 953 行 vs 可见 84 行），经 `/proc` 快照 + tail-follower 抢救，批终单文件恢复；鉴证指向 smoke→real 交接 finalize 竞态。教训钉：守护件必须 setsid 脱管（harness 看门狗杀 shell 子进程）。

### selfimp-qual 环与 esa2 评测落地（09-18 午–傍晚）

- texlate-d9 午启动，qualbench.py ESA 改造落地（`914664d`）：esa2 协议 = errors[] + stated100 主分 / derived100 自洽校验、9 类目 MQM 化（补 `accuracy-mistranslation` 收容位）、critical 收窄、swe-2-max 主裁 + swe-2-high 二裁、judge≠translator 且 medium 永禁。配套 qualsample（1200 chunk 分层）、qualstats（bootstrap CI + pairacc）、qualanchor（ESA∩AI 人审包）、qualfreeze（freeze/check 四信号门禁）四件当日齐。
- 旧协议基线对照：600 chunk/60 篇 mean 4.84/5，头号缺陷记为 untranslated_spans×21——esa2 类目表随后将其证伪（真病灶 = 流畅度 + 术语，非未翻），这是「协议换代表面结论」的首次实证。
- qualbase 批发车与收割（conc4→12 提速，约四小时）：1200/1200 全 key 落判，终值 stated 92.86 [92.35,93.31] / median 95、derived 99.20 Δ−6.34、contested 97 = 8.1% [6.5,9.8]、span_verified 98.8%、critical 零命中；cat×sev 第一大户 = do_not_translate 57（major 47）。frozen300 与 anchor200 备样随批产出。
- 中段发现链：bib-passthrough 升为头号假设（`[[BIB_` 锚块约定留英却照常送翻，do_not_translate×48 中 46 条在 BIB 块内 = 96%，单臂灭类 + 省约 4% token）；en-residue-rexlat 与 m8 低分重翻双双触判死线转 rejected；judge2 在 contested 上 ±10 内 30/31 确认主裁稳健，contested 机制定位 = 固有两可块而非 judge 噪声；unparseable 根因 = judge reasoning 烧满 max_tokens（finish=length）。

### 09-18 傍晚—深夜收割潮（16:20 磁盘清理起）

- 磁盘清理（用户裁决）：`/` 由 81% 回至 63%（714G→547G，回收约 167G）——stagerun-loop{1,2} work 残留约 124G 与 16 个冷 bench/work_* 约 38G 出清；HF hub 与语料资产按用户明示保留。教训钉：清盘 work/ 前须核该目录是否承载在飞驱动的工作树。
- texlate-5d 会话上下文耗尽，texlate-ff 接力：inject 道收官（`6599444`，W157–161 声明下沉 + filecontents 虚拟成员 + zihao=false + emergencystretch，suite 6610 全绿）、run_process 有界排干环（`93b4bdd`，单调钟 deadline + selector 读，子死即收）、`_patch_files` ReDoS 时限闸初形（`5295c04`）。
- loop2 楔死取证（py-spy 现场）：三并发失速模态——ReDoS 纯 CPU 暴走（stdlib re 不可中断）、communicate→select 墙钟 bug + 管 EOF 丢失复合、xelatex↔xdvipdfmx 孙进程 EOF 死锁。同晚 ReDoS 实锤修复落地（`dc0b886`）：「超时返 None」的线程弃守被证为假兜底（泄漏 spinner 在 C 层回溯不放 GIL），真解 = regex 模块原生 timeout；同四楔死格重跑全部正常返回。
- output-sanity-gate 三门全 ERROR 实装（`faf2dc0`/`184` 族）：same_source、length 换 token 代理带 [0.30,3.00]（qualbase 全池标定零假阳）、new-cs WARN→ERROR；e24-incidence 实测 esa2 全池 1200 对三门 ERROR 命中全零、边际翻转零。autogloss 产品化同日落地（`ffe27ca`）：auto 抽取作底座、curated doc_filter 同 key 覆盖赢；L2 A/B 60/60 判毕 term_inconsistency 100%→43%、stated +2.0，进 default-on 候选。
- 自伤链实锤与修复（`f3f013d`）：revtex209 polyfill 注入 `##` 双写首触即伤（hook 逐字存 token、内层 `\def` 携字面 `##` 炸）；sabotage-b r-w84 门④实证 1698 注入块 escaped=0。门② L1 复测 PASS：core 1955 文件 identity 100% / leak 0/135840，expand 7229 文件 strict 99.990% / leak 1/517487。

### 09-19 凌晨夜巡潮（约 00:1x–05:5x 台账刻）

- tar 伪装件族三段修复（`4509e5a`/`80bea92`/`0e55221` → 后续 `cbd3798`/`3748c89`/`4780aae`/`d80792f` 六面全闸）：W164 ustar 魔数探针 + 0-member 退役解耦 + 前 64KB 扫窗（我方 prologue 前置会把魔数推离 257 定点）→ 上移到 textutil/encoding 中性叶供 inject/latex 写路径/probe/flatten/gullet/latex209 全消费面复用；0707.0382 unfixable→clean 实证。
- natbib/restatable 收割：`62b9235` begindoc_tail_recomment（注释内 `\begin{document}` 被 `\n` 切成活行的自伤修复）、`3ecbfe3` env argspec 拆门（per-file 包扫在 `\input` 拆体后必假阴 → restatable 双非文本参被挖成散文送译，`\cref@resetstack` 递归炸栈实案）。
- 09-19 01:0x 段三收：`9fc08f0` input_sty 2.09 闸（自导回归修正——2.09 无 `\usepackage`，欠发方向=保旧 bug 不造新错）、`c04f4af` bininject（prologue 对全部 tex-suffix 前置是 tar 魔数位移之源，改 `_prologue_ok` 逐件闸）、`194195f` revtexloop（gr-qc/0104075 七万三千页死循环真因 = `\topskip 0mm` 逐字搬运进 ltxgrid 输出例程）。
- `5a5f282` macrogate（argspec_lookup 去包门，`{key}` 参漏散文同族）、`76cf439` runguard（timeout/killed veto clean + runaway_output 分类 + `died` 轮旗）、`c1c7753` stubaudit 二轮（`\QQQ` 元数、`\tag` noop、BoxedEPS 族）接连落地；L1 复测 PASS（ungate 无解析面漂移）。
- 普查翻案迭出：option_clash 家族实为 slashbox 退役包缺件（TL2020 许可证除名）6 格；`if_prot` 系幻影失衡确诊（`\let\if@X\iffalse` 在展开上下文执行跳至 EOF，非字面 `\if` 缺口）；geomverify 揭「user-texmf 影蔽」缺陷类（tlmgr usermode 装的旧 buggy 件遮蔽 vendor 补丁件）再修正为「vendor 可达性」——install_file 全链不查 vendor/files。

### 09-19 白天：裁决①–⑦落地与批面推进（台账刻 08:1x–13:1x）

- 用户七裁全收并当日落地：bib 全不翻 GO（`40904c7` 直通臂 + `246b08c` judge/mock/src_bib 信号 + JUDGE_SYSTEM 条款）、glm-5-2 维持禁令、flag 类目保留、frozen-300 门禁阈值写死（`ff1316b`）、HF 访问令牌供 XCOMET（权重约 13G 落远端 GPU 开发机，突破点 = 干净环境直连绕开 ssh 泄漏的本机代理）、contested 调参授权、autogloss default-on GO（`ec39ebc`）。bibpass-reg 回归闸 PASS：frozen-300 内 dnt-major 基线 17→0、stated 14/14=100，over_translation 4.7%→1.0%、term_inconsistency 16.0%→8.7% 双漂移皆改善向。
- anchor200 人工评审面撤出（用户裁决「懒得评审」）：口径降级为 judge 内部一致、未对人工校准——不影响臂间对比回归门，只放弃 pairacc≥0.65 的绝对校准宣称；兜底 = leader 跨分段抽验 12 格全合理。
- XCOMET-QE 入网五坑全记录：无 swap CPU 载入 OOM → 临时 swapfile；fp32 ckpt 在 11.65G VRAM OOM → `.half()`；无 tty 下 traceback 不落盘 → 日志直写 + `python -u`；earlyoom 守护静默 SIGTERM 高 oom_score 进程 → 停用；终解 = `torch.load(mmap=True)` 绕开 pl loader 手建 fp16 直载（载入峰约 30G→9G）。批程三度内核 OOM 连杀 + 一次 peer GPU 挤占，靠 Restart=on-failure + 断点续跑兜住。
- XCOMET-QE 三角测量收官：1200/1200 落袋、join 1148 格（52 行 bib 剔除——QE 对未翻 bib 天然打低分属设计内）；Spearman(qe, judge)=0.455、Pearson=0.332。定位 = cheap 预筛/异常格路由信号，不足以替代 judge；115 个高分歧格主方向是 QE 高分/judge 低分（judge 抓语义错，QE 只见流畅度）。
- fixloop 车道继续高密度收割：secdispatch `7dae23d`（miss 二次派发——halt-on-error 下孪生错根本不在 log，xelatex 单错探针 ≤2/格，yaml 零改原标记 verbatim 中真身）、floatopt `0e989a0`（[H] 浮体选项根修，顺带揭 `main_head_contains` 3k 字符窗对注释厚重稿不可靠 → `acdfc0b` 修）、csmap `bcf7de9`（natbib cite 宏族补齐）、nataux `4b1b7e5`（陈旧 .aux `\NAT@force@numbers` 整行剥除）、citembox `6eaeb31`（数学域裸 `\cite` 裹 `\mbox{}`，自持环实锤：cite 错→bibliography 不执行→aux 无 bibcite→恒 undefined）。
- failmine 目标榜驱动新波：csmap/nataux/ifclose/vendordiag/floatopt 五道 + gcensus/capcensus 两普查；unfixable:capacity 7 格裁定 = 5 格已愈于在案修复 + 2 格 paper-authentic 上游位腐（known-bad 登记 W164 防重复救伤）。

### 09-19 午后至深夜：收割潮 1–4 与 loop3/fc9/loop4 波（台账刻 14:0x–23:5x）

- ifclose `aeda23f`（未闭 `\if*`→`\fi` 注入，内嵌遮盖栈平衡扫描器）、envpoly `ffd4bf3`（`\renewenvironment` 站点前置臂）、expl3fix `a227ee6`（regex 逗号粘连幻选项修复）、cappayload `86d30ea`（capacity payload 归因）、drvdef `a4e5c8f`（间接指派驱动词缴械）、inputleak `30d53c0`（in_arg 裸 `\input` 文件名吞入保护段）六连落地；ldf 钉表 52 枚入 `28a64eb`。
- loop3 主收获（606 格复放）：**271 格翻 clean**（252 partial→clean + 19 partial_nofix→clean；基线该批仅约 4 clean）——修复机器「重跑波驱动」的首次大规模实证；哑规照实记档（hangul_font_fallback 等发而未翻），7 负翻格全部分诊入册。
- fc9 波（122 ids）：clean 14→67（+53 net），PDF 产 32→82，负向仅 1（判词标签漂移非真退）；途中 ENOSPC 事故（`/` 100%，go-build 缓存 209G 元凶）致 run_meta 0B 卡死——「0B run_meta 必删后重发」入册。
- loop4 波判 INVALID 与复活：160/160 跑完但 152 格死同一标记 `Incomplete \ifdefined`——`--rerun` 重建 splice 读活工作树，烙进 fontgate 中段破损版注入件；净树重跑 wave-2 = **46 升 0 降**（44 partial→clean + 1 partial_nofix→clean + 1 hard→clean，含 1206.0701 最难标记 if_phantom_protect 野外实证）。沉淀纪律：splice-重烘焙 replay 波必须等 inject-路径 mutex 全释（或钉 committed rev）。
- 原子落地 `18d8fc7`（131 规）：para_longize（def 站补 `\long` + 内核宏 `\par`-strip wrap）+ macro_glyph_fix stage-B + px_to_bp ×1.0 对齐三宗归一——自此「builtin 注册 + yaml 引用同 commit」成为落规标准（反向序曾致全仓 RulesetError 毒窗）。
- L1 新低（09-19 口径）：parsebench corpus_v3 全量 identity strict 1955/1955 = 100%、leak **0/128460 = 0.000%**（前轮 0.040% → 归零）；operandfix `2f4a905` 的 626 名扫描终止表把 log-payload/裸括号泄面归零是主功。
- 深夜波：wave-5 组 17 dir-arm 复放 + catchup 自动点火（canon/raw id 双侧归一修复 253 格 norecord 漏跑；loop2 work/ 早前被清致 401 格 rerun_no_zh → B 段 580 格全链重建）；重建终态 526/619 clean 态（85%）。verify-wave1 收割 **83 up / 0 down**；clean% 门⑤审计 PASS（结构性：波只触 `--on nonclean`）。规则库此夜冲至 139。

### 卷 1 末段（09-19 约 17:55–19:00，L1280–1380）

- `7b865317` slotrev（slot_arg_revert 约 605 行 builtin + 约 30 行机位扩展表——zh 机位实参对 pristine 基线逐 kind 序号对齐 revert，分歧整 kind 跳防错位）落地；`8ec129ce` ifscanner（新 textutil 叶 477 行活位扫描器，253 行内嵌双壳收窄为薄壳，phantom 类显式化）落地；`22304933` subfile_docclass_strip 经 verifier164b 裁定 KEEP 后复落（三格子档归属与 pre-docclass 执行面均实证）。
- pathspec 卷扫事故三连发（`001094d`/`0db4133`/`df72ac8`）：交织文件在 diff↔commit 间隙被别家新写内容整文件卷走，最重一次卷入未落地注册行致 HEAD 悬空——沉淀规则：交织文件只能 `apply --cached` + 裸 commit，单主文件 pathspec 无妨；taxonomy/facade 共享面提交前立即重 diff。
- `4509653d` 陈树横扫事故：peer 车道以陈旧基线成树提交，静默回退 wave-10 全部修复面（16 件回退 + 3 测试档删除）；检出路径 = `git show HEAD:` marker 复查 → `git log` 二分，恢复 = `d34d08f1` 经 blob-sha 复用重落 13 件。此后「每次 harvest 复验 HEAD marker」成为门巡常项。
- 门①–⑤ 口径在卷内成形并全程巡守：①L0 pytest 绿 ②L1 parsebench identity/leak ③目标格翻转实证 ④sabotage escaped=0 ⑤clean% 单调无回归；至卷 1 末全绿（L0 7259+1 隔绿、L1 1955/1955+0.000%、sab-r7 40 格 escaped=0、clean 池 32/32 单调）。

## 卷 2–8 增量（blob-ledger2.md–blob-ledger8.md）

### blob-ledger2.md（L1381–1390，约 19:15 巡检脉冲）

脱管批全数 DONE 清点（l1gate3 / sab-r7 / wave-10 replay 4/4 / autogloss-reg 门 rc=0）；roster 由 5 补至 9（endcsresid/stucklatin/epsconv/micro2 新派）；undef13 普查 intel 转交 cstablesweep；文件归属预警与门 vigilance 常项。

### blob-ledger3.md（L1391–1399，约 19:35 nfssfd 收割）

`f2abce2c`：`No file X.fd` 先于 NFSS 硬错落首错前向盲区 → ErrReport.pre（≤4 行）+ taxonomy `use_pre` opt-in + `_fd_case_variants` 探序，8 格真 classify 实证（LGRcmr×7+OT2lmr×1），无新规则（payload 走 install_file）；cross-lane 在飞编辑致 450 瞬态测试失败复跑全绿——replay-mutex 代价再添实证。

### blob-ledger4.md（L1400–1407，约 19:55 missmath 收割）

`9a5cdb36`：4 规 + 闸扩（verdate_pad/endcomment_tail_split/missingdollar_blankline/ifnum_typeout_banner + revtex4_array_swap_guard 包包装类），Ruleset.load()=155；orphan-check 1 红 = wrapromote 在飞 churn 非入库破（规则/注册/builtin 三件已在树待同步）。

### blob-ledger5.md（L1408–1414，约 20:15 共享 index 警报）

quiet tick；核心发现 = peer 会话把 4 个已入库测试档在共享 index 暂存为 `D`（磁盘与 HEAD 均完好）——若 peer 带此 index 提交即重演 4509653d 删除事故；私 index 纪律免疫，后续每次 harvest 续做 HEAD marker 复验。

### blob-ledger6.md（L1415–1422，约 20:35 wrapromote 收割）

`1a4b6fff` main_wrapper_promote（门③实证：2609.19170 unfixable:emergency→clean，relocate 归位后翻真 wrapper）；stucklatin 解剖出三缺陷（vendored 落件对嵌套 main_dir 不可见 / 外部落件 dedup 键过期 / stuck 标记取签口径错）→ vendorcwd/stucksig 两修派；promote-on-cascade 变体入 backlog。

### blob-ledger7.md（L1423–1430，约 21:00 静默巡）

roster 10 全活无交付；在飞 diff 全可归因（gfx 系/peer tolerant-load 线）；共享 index staged-D 污染仍挂、HEAD markers 全在。

### blob-ledger8.md（L1431–1434，约 21:20 守衡）

quiet hold：无交付无新批，roster 10 全活，census 类长爬属正常。

## 卷 9 独占增量（blob-ledger9.md L1435–1774）

### 09-19 深夜至 09-20 凌晨收割尾潮（约 21:45–03:10）

- 收割波×4：`01803f7c` renewguard（cs_targeted_fix guard 键入列）、`501ef778` micro2、`806e428a` epsconv（X-eps-converted-to.pdf 资产族补链）、`81c364ff` cstablesweep 测试档；继而 `4c90b81a` endcsfix（aas 三 stub `\gdef&` csname 双态）、`79799d5a` letltxmacro、`9e6e520d` fmsinglesadopt、`22ee44aa` blxdlist（pre-dlist 裸 `\entry` .bbl polyfill）、`890cb486` statsync2（17 规 fires 再同步）。
- `c8f337b9` axodraw、`6ef65772` sitehoist（resolve_site 单源化 + 全 wdir-drop 站点转 main_dir）、`fe4e4384` haltsweep（halt-on-error 跨轮 missing-gfx 累积枚举）、`847b931e` pgffix 落地；flipcheck9 波 8 replay 7/9 目标翻 clean、sabotage 44/44 escaped=0；aaai2027 增程 15/15 clean。
- texlate-21 跨会话重构协调：ownership map 互发（_builtins_* 归 sitehoist 至交付等），peer tolerant-load 线（Ruleset.load(tolerant=True)）与 PROTOCOL 退役面核查均定源非我方。

### 09-20 冻结令与解禁（约 19:05–20:35）

- 冻结令（用户经 peer 转达）：在飞 impl 批落地后停开新 lane/新波——仓级 git 最终对齐需 tracked 工作区零写；巡逻职责收窄为只收割落账。
- 末批 4-lane 全落：`f64d2d0d` implw13（w13spec Part-A 6 bundles）、`f86500f0` b5aseam（nested-docclass 缝走查）、`f2e1fc31` armgapimpl（soul_multi_mbox/inputenc noop/bib_backend_biber_swap 三臂，209 规 load）、`6c30281c` b6reverify（写后复验槽 + verdict 公式修）；外加 `54b2078f` vendored_shadow_isolate 守卫与 `9606959b`/`33148e67`/`660cbb91` 等前批收割。
- wave-14/15 早产事故：run.sh 在 zh 未播种时提前发车致 flip14 全 222 格 0.0s 空跑——作废隔离（fixloop.jsonl → .void-1749 forensic 留档），种子完好；peer all-clear（三方对齐 HEAD=6b45a8a3）后两波重发。
- 余伤处置：repoint 越界吃掉 00-base.yaml 闭引号致全仓 Ruleset.load() 灭（`b379e4d7` 修 + peer 复扫 13 处吞字符伤 `6d7ca9cd` 全量还原）；共享 index 陈旧 staged-D/反向 diff 周期性复现，私 index 免疫并持续告警 peer。

### 收官：wave-14/15 重发与结算（09-20 约 20:35–21:15）

- wave-15（69 格）结算：目标翻转 27/34（fail→clean×13+、partial→clean×6、fail→partial×8），batch-B 3 格 clean/partial/fail 各一；**sabotage 逃逸 2/33**——1107.0063 clean→partial（sabdeg 已知退化格，待确认环境性）与 2505.21476 clean→fail（新下翻排队 autopsy），门④首次违反，已报用户裁决。
- wave-14（222 格）在飞推进正常（台账截至于 176/222）；tfmslot 收官交付 5/5 TFM-slot 诊断（arg-hoist/fam-baked mathchar/char_table+exts/produced_by 注册四 bundle 入队列）；roster 清零，replay-mutex 守衡至波终。
- 台账末端状态：规则库 209 条 load 绿、门①–③⑤绿、门④ 2 逃逸待裁；裁决队列与未决面见末节。

## 跨卷机制产出（持久资产）

- **门禁与观测**：门①–⑤ 巡守制；qualfreeze 四信号门禁 + qualdrift 哨兵（zh 钉集复判，判分漂移与翻译漂移解耦，首点 verdict=pass）；scorecard schema v3（union 注记、csb 三档 drop、freeze 四信号、`--require-frozen`）；metrics.gate_fired 盲位修复（REJECT 绕 actions 不可见面收口）。
- **批编排**：nightwatch 进程面/队列/活跃 run 台账脱管巡；stage_timing 请求时序三分拆（req_timing records，顺带坐实网关延迟模型：固定连接耗时 + 每输出 token 线性项 + 全局吞吐上限）；harvest.py/flipcheck/verify-wave/replay 复放工具链；canon/raw id 双侧归一化；0B run_meta/截断 jsonl 恢复规程；ENOSPC 复产流程。
- **健壮性**：run_process POSIX 有界排干环（子死即收 + 超时输出随异常带出）；regex 模块原生 timeout 真中断（「超时返 None」线程弃守被证伪——stdlib re 在 C 层回溯不可中断，py-spy --native 是 GIL 饿死案唯一取证链）；`_RunawaySentry` page_flood/vbox_flood 双哨兵 + timeout veto clean + sentry_reason 归因链；`_landing_sync` 外部落件指纹失效 + dedup 键过期；LoopCtx 日志缓存逐编译点失效（logcache 系统缝）。
- **修复引擎**：stuck 语义改 exhaustion-settled（同标记轮在派发耗尽点才结算——旧预判制曾正杀可救格）；secdispatch miss 二次派发（halt-on-error 孪生错）；slot_arg_revert 机位参 revert 机制；paired_slot_diff/machine_slot_audit 机槽探针（src/zh 八类机位参数 diff，note 级封顶）；tar 伪装件六面闸（magic+version+checksum 三验）；vendor 可达性族（mnras_texmf_shadow_drop/revtex_era_retire/pstricks_add_pair_retire/paired-.tex 退役/`./` 路径限定回填 shim）。
- **质量面**：esa2 协议全套（qualbench+qualsample+qualstats+qualanchor+qualfreeze 五件）；autogloss 术语抽取产品化（default-on）；output-sanity-gate 三门 ERROR；bib-passthrough 直通臂；XCOMET-QE 第三族评委臂（ρ=0.455，定位 cheap 预筛）。
- **工艺纪律（事故驱动沉淀）**：私 index + pathspec-only 提交（私 index 2026-10-01 起禁用，改常规 add/commit）；交织文件 `apply --cached` + 裸 commit 分账；commit 前 `diff --cached --name-only` 对账暂存集==意图集；每次 harvest 复验 `git show HEAD:` marker；builtin 注册先于引用它的 yaml（反向序=全仓 RulesetError 毒窗，replay 波在飞期禁落引用新 builtin 的 yaml）；replay-mutex（splice-重烘焙波在飞期 impl 车道禁触 inject/segmenter 等活树读面）；scratch 只在 `tmp/lane-*/`；脱管批一律 setsid+nohup+run.log 直写（扛宿主进程死亡）；「超时返 None」≠安全、resume-safe≠duplicate-safe、清单外测试件不可信（emit 面车道 commit 后必跑全目录测试不信交付清单）。

## 事故录

| 时点口径       | 事故                                                        | 后果与处置                                                                                                                              |
| -------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 09-18 10:10    | rt1 xlat.jsonl inode 被换（ORPHANED_FD）                    | 孤儿 953 行经 /proc 快照+tail 跟随者抢救；判 smoke→real 交接竞态；沉淀=守护件 setsid 脱管                                               |
| 09-18 15:20    | loop2 fixloop 段悬挂（novem.tex 4.1 万页暴走+ReDoS+EOF 丢） | 三失速模态取证，run_process 排干环 + regex timeout 落地；清盘误删 work/ 致重启零产出——清盘前核在飞工作树                                |
| 09-18 21:55    | `_bounded_sub` 线程弃守假安全                               | spinner C 层不放 GIL 致批冻结；regex 原生 timeout 修复（`dc0b886`），「超时返 None≠安全」入册                                           |
| 09-18 22:05    | revtex209 polyfill `##` 双写自伤                            | 首触即伤把排序错换成更糟错；单 `#` 修 + `##` 禁入断言（`f3f013d`）                                                                      |
| 09-18 22:50    | autogloss-reg 双 orchestrator                               | 巡检误判死亡重拉起第二 driver，孤儿 judge 并发写 records ~5min（PIPE_BUF 内未撕行）；「kill 父≠灭门」「resume-safe≠duplicate-safe」入册 |
| 09-19 白天     | pathspec 卷扫三连（`001094d`/`0db4133`/`df72ac8`）          | 交织文件被整文件卷入别家在飞 hunk 致 HEAD 悬空；规则化=交织件 apply --cached 分账                                                       |
| 09-19 约 10:0x | ENOSPC：`/` 100%（go-build 缓存 209G）                      | fc9 中段崩 + 0B run_meta 每 stage 卡死；恢复=截 jsonl 净行 + 删 run_meta 重发，「0B 必删」入册                                          |
| 09-19 约 11:0x | loop4 波烙进在飞破损注入件                                  | 152/160 格同标记全灭，波判 INVALID；净树重跑 46 升 0 降——沉淀=replay-mutex                                                              |
| 09-19 午间     | 裸 commit 卷走 peer 预 staged 12 件（`c0cf77d`）            | 共享 index 不设防；reset --soft 逐件退回零损，commit 前 diff --cached 对账入册                                                          |
| 09-19 下午     | B5 毒窗：yaml 先落于 builtin 注册                           | 338 格 RulesetError 全灭 + 恢复波在飞再毒约 30 格；standing rule=fixloop 写件即验 Ruleset.load()，波在飞禁落引用新 builtin 的 yaml      |
| 09-19 18:45    | `4509653d` 陈树横扫                                         | peer 以陈旧基线成树提交静默回退 wave-10 全修复面；marker 复验 + 二分检出，`d34d08f1` blob-sha 复用恢复 13 件                            |
| 09-20 17:49    | wave-14/15 早产空跑                                         | zh 未播种 222 格 0.0s 全错；作废隔离 .void-1749，all-clear 后重发                                                                       |
| 09-20 18:20    | repoint 越界吃 yaml 闭引号                                  | Ruleset.load() 全灭，`b379e4d7` 修 + `6d7ca9cd` 全量还原 14 处吞字符伤                                                                  |
| 全程           | canon/raw id 两形混存                                       | seeder 发 canon、records 记 raw → 253 格 norecord 漏跑；双侧 canon() 归一修复（与现有 id 归一须知同族）                                 |

## 关键数字簿

- 基线（09-18 09:10 口径）：mechanisms.jsonl 210 条（covered 68 / partial 134 / implemented 8）；loop1 5124 格 pdf 97.89% / clean 84.99%；leak 0.040%；pytest 6213 绿。
- 解析门 L1（09-19 口径）：corpus_v3 全量 identity strict 1955/1955=100%、leak 0/128460=0.000%（历史新低；09-19 全量语料面 leak 0.004%、核心层 0/135840 亦零）。
- 修复产率：loop3 606 格翻 clean 271（+19 partial_nofix→clean）；fc9 122 ids clean 14→67；loop4 wave-2 净波 46 升 0 降；wave-5 收割 925 格 up 21 / down 1 / firsts 225；verify-wave1 83 up / 0 down；rebuild-loop2 清盘重建 526/619 clean 态（85%）；aaai2027 增程 15/15 clean；wave-15 目标翻转 27/34。
- 破坏闸门④：sab-r3 1622 事件 escaped=0、r4 383/0、r5 383 事件 1613 sabotaged/0、r6/r7/r8 逐格零差 0、flipcheck9-10 44/44=0——直至 wave-15 逃逸 2/33 首次违反（已报裁决）。
- 质量面（09-18/19 口径）：qualbase n=1200 stated 92.86 [92.35,93.31] / median 95 / derived 99.20 / contested 8.1% / span_verified 98.8% / critical 0；bibpass-reg 判死线 dnt-major 17→0；autogloss A/B term_inconsistency 100%→43%、回归门 D≤0.05 三臂全过；XCOMET-QE Spearman ρ=0.455（n=1148）；qualdrift 首哨兵 KS D=0.033 p=0.996 pass。
- 工程规模（09-20 口径）：规则库约 125→209 条；pytest 全仓 7259+ 绿（1 环境 flake 隔离绿）；leader 署名提交约 120 个；磁盘 `/` 自 81% 清至 63%（约 167G）；roster 峰值 10–12 车道并行。
- 成本与判官配比（09-18 口径）：翻译臂 rt1 约 1044 篇 13.4 万 chunk；judge 臂预算约 1.55 万档·次，占翻译臂约 1.9%（<5% 验收线）。

## 裁决与未决队列

- 已落地用户裁决（09-19）：bib 全不翻 GO（bib-passthrough 直通臂 + judge 新条款，回归实证 dnt-major 17→0）、glm-5-2 维持禁令（跨家族三角改由 XCOMET-QE 承担）、flag 类目保留、frozen-300 门禁阈值写死、HF 访问令牌供 XCOMET-XL（远端 GPU 开发机落权重）、contested 调参授权、autogloss default-on GO、anchor200 人工评审豁免（judge 口径降为内部一致）。
- 未决队列（09-20 收官时点，台账累计）：acceptable_pdf 语义收紧（1131 格分层：约 5.2% 携内容丢失标记、约 57% 带各类残损记号——T1 灾损 30 格含 cjk_invisible 17）；ds@ Option A（约 96 格 latex209_reject 族放行与否）；verdict 排序（同 artifact 下 unfixable:* 是否应排 best_effort_pdf 之下）；warn-level dispatch 政策（48 zh 格/run 带覆盖标记不派发）；covgap REVIEW-2（有界 `\fi` vs preamble 中和）；宿主 TEXMFHOME pstricks.sty 影蔽（mnras 姊妹形）；`_closure_has_end` inject pass-1/W99 准入闸；osajnl.cls `\makeatother` vendor-shadow；amsart opt-arg size-decl 清理；ctex `\baselineskip` 注入负效应（2404.14219 自伤 6.5 万页洪）；biberbreadth 两项（swap 臂 misfire 归因条件 + shipped latin-1 .bbl 退役臂）；tfmslot 四 bundle；blxdlist v2.3 位置名重读器；promote-on-cascade 变体；2505.21476 下翻 autopsy（门④违反单元）。

## 原始台账位置与调阅

- 原稿：`tmp/blob-ledger.md` 与 `tmp/blob-ledger{2..9}.md`（未跟踪工作面，append-only；九快照逐前缀包含，取证只需卷 9）。车道交付与报告散在 `tmp/lane-*/`（report.md/REPORT.txt/repro/ 族），批产出在 `bench/results/{qualbase,qualdrift,parsebench,stagerun-*}-*` 目录。tmp/ 为易失工作面，原稿去留由 tmp 清理波另行处置，本文件即归档蒸馏。
- 调阅姿势：按卷段行号定位（卷段划分见「源件与口径」）；commit 短哈希在原稿中逐条随附，可与 git 历史互证；台账内「裁决点/未决」表述以本节归并为准。
