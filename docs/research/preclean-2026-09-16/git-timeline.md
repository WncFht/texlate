# git 历史时间线 — 清理前知识保全

范围：349 commits，2026-09-14 14:07 (`7da5e8b` init) → 2026-09-16 18:44 (`67debb6`)。数据源 `tmp/preclean/gitlog-full.txt`；入库状态以 `git ls-files bench/results/` + 各级 `.gitignore` 实测为准。

作者分布：Claude Opus 4.6 ×219、Claude Code ×116、Devin ×5（Devin 的 5 条全部在 09-15 深夜 23:33–23:49：S2/双跑/fixloop v2/HANDOFF/noqa）。

## 1. 阶段划分

| Phase | 时段 | commits | 主题 |
|---|---|---|---|
| P0 | 09-14 全天 | 9 | 调研定型 + 工具链：大对比 bench（8 库全灭于宏展开、miniscanner spike 扶正、pylatexenc REJECTED、fixloop spike 16/16 救回）、ADR/roadmap、format/lint/pre-commit 全链 + 一次性格式化 |
| P1 | 09-15 08:38–09:25 | 5 | 文档入库 + 骨架：bench/py 归位 + corpus_v2 137 篇、docs/research 45 篇、最终规格 docs/06–10、uv 骨架 + ruff select=ALL 分层 |
| P2 | 09-15 09:51–13:30 | 18 | M0 产品骨架一波：parsebench/compilebench 基线、validate L0/L1/L2、xlat 编排层全套、arxiv 获取层、latex 九文件正式实现、fixloop yaml 引擎 25 规则、compile 引擎层、CLI mock 全链、CI pytest |
| P3 | 09-15 13:35–15:29 | 39 | corpus_v3 补强层 + 机制台账：W07–W109 机制合流（5 波 merge）、booster 200 篇选择+物化、bench 扶正（parsebench v2/validbench/fixtures 移植/xlatbench 切产品 L0）、miniscanner spike 退役 tmp/exp、textmask/texlog/lev 三收敛 |
| P4 | 09-15 15:52–19:33 | 45 | 对抗性审计修复潮：visible_tex i+=end 位移 bug、fixloop bench 救回 36/40、xlat 编排收口（join 死锁/resume 冻结/混批/fence）、sandbox 三盲区（mktexpk→SIGPIPE 链）、stdin=DEVNULL 确定性裁决、W11/W12、scanner-audit F1–F12、Mouth+Gullet 展开机落地 |
| P5 | 09-15 20:28–23:49 | 16 | v2 前夜：audit 次要三条、gullet bench 995 篇（非幂等发现）、§4 接线面、segmenter S1（vtex 账本+run 双轨）、web SolidJS 阅读器、server 服务层全套（FastAPI+SSE+SQLite+BYOK）、align named-dest、fixloop 规则库 v2、S2 dispatch、parsebench --v2 双跑、HANDOFF-09-15 |
| P6 | 09-16 01:40–07:32 | 15 | 深夜冲刺：resume 三修（splice 残留根因=source 漂移）、tlmgr 装包层+documentstyle 降级、非 UTF-8 转码层、texlate web CLI、S3 展开语义、mask_tex env overshoot 第二击、compilebench-v4+fixloop 89.5%、S4 \if 界标、**f461683 v2 产品面切换（BREAKING）** |
| P7 | 09-16 08:02–11:55 | 36 | 全仓审计 + 打包部署链：audit-2026-09-16（13 维 verdict + 5 个 P0 安全发现）、thin-client/docker/CI 引擎矩阵/release 流水线/SPA 入包、tectonic 钉版安装、web 单实例锁、tar 加固+aux 截断、server 安全五件、hot 语料层、export EPUB/DOCX、e2e fixloop+L2 接线、argspec.json 入包（M1 收官）、gwcap tailscale 三连修 |
| P8 | 09-16 12:03–13:54 | 34 | 批量强化 sprint：tailnet http 放行、docx/epub 上传路由、triage.py、records append 化+benchlib、n100 postcutover 终态、auth 熔断+usage sink、O(n²) 性能双杀（0278602/55db9bc）、web observability、worker 三区（babeldoc sidecar+L2 回灌+_run_doc+dispatch 死锁）、corpus expand +3800、F3 verdict 语义、stagerun、sabotage/perturb arms、loop runbook、target_probe、llm_hook、arxiv metadata、qualbench、share 核心 |
| P9 | 09-16 13:57–16:01 | 45 | 产品面收口 + live-smoke：真网关 e2e PASS（0454e57）、l0 两洞+leftover_ph 升级 fault、DELETE endpoint+GB1 cmap、bwrap sandbox、B7 0.9918、graphic repair、figure regions、sdist 白名单（24G 吞包事故）、sidebar/findbar、argspec verbatim/hyperref、Mode B/C 全链 parity、doc pipeline e2e、base-v3-full 5059 基线、share import |
| P10 | 09-16 16:02–18:44 | 87 | audit wave2 落地 + loop1 会战：worker/server/compile/fixloop 四线审计修复（6b23435/3c5aae2/9368872/6b71018）、taxonomy 单源化、shim_map +17、early_eof 分类、cls-plea tail 规则、never-regress floor、filemap 三路、repro 证据包（0806/2203/2501/1306/2410b）、loop1 stagerun 5059 records 入库、rerun 13/13、rundiff、clean-clone 两轮验证 |

体量观感：09-15 白天≈P1–P3（骨架+语料），09-15 下午–深夜≈P4–P5（审计修复+展开机+server/web），09-16 凌晨≈P6（v2 切换），09-16 白天≈P7–P9（审计+批量+收口），09-16 傍晚≈P10（loop1 大会战，单日 40 commits/h 峰值在 17:00 档）。

## 2. 产物→commit 映射

### 2a. bench/results/ —— 入库部分（tracked）

按证据族归并；`入库` 均经 `git ls-files` 核实。

| 路径 | 产生 commit | 内容 |
|---|---|---|
| `00-grand-comparison.md` + `pylatexenc*/plastex*/texsoup*/latex-utensils*/unified-latex*/tree-sitter-latex*/latexjs*/latexml*/latextrans*/texglot*/ieeA*/miniscanner*/macro-stats*/arxiv-coverage/fixloop-*/compile-*` 等 20+ 件 | `a7db4ee` | 09-14 大对比：8 库实测、spike 救回率、宏统计、源码覆盖率、babeldoc 冒烟报告（`babeldoc-smoke*.md`） |
| `parsebench-corpus39/corpusv2-*`（files.jsonl/papers/summary） | `d4f53cb` | B1 契约化基线 + ph_tail 首测 |
| `parsebench-corpus_v3-2026-09-15` | `afb1621` 跑、`c750da7` 扶正后复测 | corpus_v3 1000 篇首测（leak 0.144%→修后 0.04%） |
| `parsebench-corpus_v3-booster` | `601d065` | 补强层 200 篇首测 |
| `parsebench-audit-{defnl,fix,full,final}-2026-09-15` | `a88c5ce`/`785b4d8` | 对抗性二审复跑 |
| `parsebench-{v3-post-wfix,postf,postf6,maskfix-probe}-*` | `0c6c6ce`/`a9e07c8`/`7a13735` | W11/W12/F6/mask overshoot 修复对照 |
| `parsebench-textutil-{full,full2,verbatim}-*` | `4287794` 窗口 | textutil 收敛期回归 |
| `parsebench-v2dual200`、`v2-diff-*`、`v2-census-*.md` | `db707d0` | S2 双跑对照 + UNKNOWN 兜底普查 |
| `parsebench-v2full-{s3b,s3c}`、`v2reg-s3grp{,2}` | `bf31377` | S3 展开语义验收 |
| `parsebench-v2full-s4` | `f730dc0` | S4 \if 界标验收（conditional leak 27→0） |
| `parsebench-v2prod-{cutover,final}` | `f461683` | v2 切换验收门 |
| `parsebench-v2full1955-*` | `c88f458` | S5 全量双跑基线 |
| `parsebench-argspec-smoke`、`argspec-verbatim-2026-09-16/` | `401e9bb`、`c2d17b2`+`af7bf2e` | argspec 接线 + verbatim/hyperref dispatch 证据 |
| `parsebench-v2textfix-2026-09-16`、`parse-v3-full-2026-09-16` | `06032b5`、`0932439` | textfix 复跑 leak 3979→60；3937 文件全量 |
| `compilebench-corpusv2` | `a85628d` | B3 联合 clean 22.5% 定标 |
| `compilebench-v3-2026-09-15` | `a455fd4` | n=180 双引擎原文基线（联合 pdf 71.7%） |
| `compilebench-v4`、`fixloop-cbv4` | `61a9e16` | 同 180 样本 fixloop 臂 70.6%→89.5% |
| `compilebench-v3-zh`、`fixloop-zh-cbv3`、`e2e-modes` | `d066c66` | zh 条件臂 + Mode B/C 首跑 |
| `fixloop-corpusv2`、`fixloop-results.json` | `beaf1db` | 规则库救回率首测 26→36/40 |
| `fixloop-v2-rules-2026-09-15` | `d087f54` | ps_image 确证链 + legacy shim 族 |
| `fixloop-v3-{missing-file{,-r2},docstyle{,-tec-r2}}`、`fixloop-tlmgr-search-cache.json` | `38cc0a7` | tlmgr 装包层 90 格真装实证 |
| `fixloop-rules-2026-09-16` | `8c8c1c3` | inputenc_strip/cs_targeted_fix 实测 |
| `fixloop-replay-baseline`、`fixloop-v2-salvage`、`fixloop-tickets-F{1F2,3F4}-*.md` | replay/救回波次 | fixloop 迭代证据 |
| `filemap-fix-2026-09-16/summary.md` | `9299802` | filemap 三路修复证据（cs glue-split 24/24） |
| `e2e-real-s40{,-r2}` | `7ba3050`（r2 归因 `dbc58a4`） | 真实网关 E2E 基线 + stdin 不确定性裁决 |
| `e2e-real-n100-2026-09-15{,-report.md}` | `b8e81ce`+`c88f458` | pre-gullet n100：splice 残留 1524 集中 7 篇 |
| `e2e-real-n100-postcutover-2026-09-16` | `5b37831` | postcutover 终态 + B7 归因 |
| `e2e-postcutover-n10-2026-09-15` | `6a256b2` | v2 切换后首证（残留 0 硬门） |
| `e2e-verify-residue-2026-09-16{,-report.md}`、`splice-residue-probe-*.md` | `b55269d` | leftover_ph 572→0 复验 |
| `e2emock-{smoke,corpus39,v2prod-smoke}`、`e2e-hotfix-smoke` | `a200f2e`/`645ff71`/`6a256b2`/`360a810` | mock 链冒烟矩阵 |
| `xlatbench-contract`、`xlatbench-v3-{smoke,matrix}` | `34d067a`/`149719a`+`d6aa43d`/`dbc58a4` | B4a 网关契约（swe-2-medium ~99%、glm-5-2 封存）、corpus_v3 抽样 98%、296 调用放大矩阵 |
| `validbench-{corpus_v2,replay1636}` | `5579fa1` | B6 校验段基准 |
| `alignbench-{selftest,e2ereal-09-15}` | `a0c8713`/`d0b8984` | named-dest 保留率（babeldoc 锚全丢实证） |
| `alignbench-e2ereal-2026-09-16`、`b7-pipefix`、`b7-attribution`、`ctex-anchor`、`alignbench-post-shim` | `d066c66`/`27d2096`/`5b37831`/`0888962`/`9edbfdc` | B7 链：0.9918→定理锚 shim→零回归 |
| `gullet-corpus-2026-09-15{,.md}` | `ee3f90f` | 995 篇展开 bench + 非幂等发现（66 篇二次驱动发散） |
| `f12-env-tomb-2026-09-15.md`、`scanner-audit-2026-09-15.md`、`audit-minor-fixes-2026-09-15.md` | `0216849`/`55101a2`+`785b4d8`/`4efd3b8` | latex 审计留档 |
| `stagerun-smoke`/`stagerun-sabsmoke`（work/ 各自 dir-local gitignore） | `7ba0ece`/`f4d9ec8`+`c187025` | stagerun 冒烟 + sabotage arms |
| `stagerun-loop1-2026-09-16/`（records/metrics/report/tickets 入库，work/ 44G gitignored） | `5acb956`+`86908bc` | loop1：n=5059、fixloop 1310 cells、zh pdf 86.1% |
| `modec-{v3,tec-v3,v3-tailfix,expand,misschar,tail}-2026-09-16` | `c0127e9`/`44383c1`/`2acdcfb`/`7b87546`/`8fead4c`/`c69353e` | Mode B/C 各轮：escaped==0 门禁 |
| `mock-sabotage-v3-2026-09-16` | `e947192`+`7f165eb` | sabotage v3 recount |
| `repro-{0806,0806-head,0806-textfix,2203,2501}-2026-09-16` | `6b96c34`/`06032b5`/`1abf2af`/`8fead4c` | 根因证据包（3 连 bug/侧效应守卫/DUC-XeTeX） |
| `live-smoke`/`live-smoke2`/`server-smoke` | `0454e57`/`0aa11da`/`59a874d` | 真网关/真机冒烟 |
| `share-{wire,apply,live}` | `ad00af3`/`8dc644d`+`c3a3c3c`/`0dfc93e` | share 包三段验证 |
| `doc-e2e`/`doc-polish`/`export-realbook`/`export-verify` | `628f478`/`b56c2d6`/`360a810`/`54c5e66`+`628f478` | docx/epub 管线证据 |
| `docker-smoke`/`dist-smoke` | `bfbe31e`/`60bc027` | 镜像 + sdist 白名单验证 |
| `clean-clone-2026-09-16` | `96bfd67`+`8370268` | clean clone 两轮验证（11 guard 缺陷→绿） |
| `web-docview`/`web-resmoke` | `ce7834c`/`ecae14d` | web 侧冒烟 |
| `api-cover`/`cli-doctor`/`probe-wire`/`demo-2026-09-16`/`upload501-worker-patch.md`/`f3-patch-notes.md`/`nominations-merge-*.md`/`encoding-probe-*.json`/`l2-attr-probe`/`perf-tail`/`qual-run`/`qualbench`/`base-v3-full`/`corpus-expand-qc`/`b7-*` | `545f485`/`3631c75`/`254e683`/`2b7d1c2`/`3ee827b`/`daf6a2a`/`4e89bbb`/`4a8d5ce`/`bb1da3d`/`55db9bc`+`0278602`/`0c88a79`/`c81d695`/`0932439`/`e9bba9c`+`0932439` | 各自 commit body 已注明 |
| `metrics.jsonl` | `4f2e9cd`（`8b126d7` 加 --no-global） | triage 全局趋势文件，入库；smoke 跑不写它 |

### 2b. bench/results/ —— 未入库/部分入库

| 路径 | 状态 | 关联 commit | 说明 |
|---|---|---|---|
| `bench/results/babeldoc/` | **gitignored**（`a7db4ee` 同 commit 立的规则） | `a7db4ee`、`add5618`（babeldoc-e2e） | BabelDOC 冒烟重产物：Adam PDF mono/dual + PNG 帧 + full_run.log；报告 `babeldoc-smoke*.md` 入库、数据不入 |
| `stagerun-loop1-2026-09-16/work/` | dir-local `.gitignore` | `5acb956`/`86908bc` | 44G 中间树；records/metrics/report 入库 |
| `stagerun-{smoke,sabsmoke}/work/` | 同上 | `7ba0ece`/`f4d9ec8` | 同模式 |
| `postfix-2026-09-16/` | **untracked**（git status ??） | loop1 修复后验证跑（run_meta started 2026-09-16T09:55Z≈本地 17:55，即 18ff106+2f12955 之后） | e2e_real_bench 65 篇 swe-2-medium：pipe-xel clean 40/fail 5/partial 20，splice 残留 0——loop1 修复波的验收跑，未提交 |
| `repro-1306-2026-09-16/` | **untracked** | `88d0ab9`（loop1-1306.0036 prim-guard）、`7b87546`（1306.0067 tabular 腐蚀 dispatchable） | revtex 探针 pack（probe-*.tex/log/aux） |
| `repro-2410b-2026-09-16/` | **untracked** | `7b87546`（2410.17957 Mode-B 编译死）、`88d0ab9`（loop1-2410.00012 spotcolor） | report.md 已写致命现场：[[COMMENT_n]] 内嵌 `}` 致 \caption 块结构崩 |
| `stagerun-loop1-2026-09-16/rerun-ids-loop2delta.txt` | untracked 文件（目录本身 tracked） | `64bd7f7`/`20ad50b` rerun 系列 | loop2 delta 复跑名单 |

### 2c. bench/ 下其它产物

| 路径 | 状态 | 关联 commit | 说明 |
|---|---|---|---|
| `bench/work_*/`（18 个：work_v3 28G、work_base_v3full 17G、work_sabotage_v3 5.2G、work_e2emock/e2ereal、work_compile{,_v2,_v3,_v4}、work_fixloop{,_cbv4,_replay,_v2,_v3,_v3_ds,_zh}、work_sabotage_{mock,probe}） | 全部 gitignored（`a7db4ee` 立 `bench/work_*/` 规则），合计 ~63G | 对应各 bench commit | 编译/fixloop/sabotage 工作区重产物；`work_v3/.venv` 是 corpus 构建 venv |
| `bench/corpus/*/`、`corpus_v2/*/`、`corpus_v3/*/` | 数据 gitignored；`MANIFEST.md`/`manifest*.jsonl`/`mechanisms.jsonl`/`select_booster.py`/`booster_selection.jsonl`/`selection_report.md`/`nominations/` 入库 | `648212c`(v2)、`afb1621`(v3 core)、`52d490e`(booster)、`e9bba9c`(expand manifest_expand.jsonl)、`7b6d83c`(hot manifest_hot.jsonl)、`ab7a8c9`(nominations unignore) | corpus_v3 磁盘 20G；v3 .gitignore 是 `*` + 白名单式 |
| `bench/py/scratch/`、`bench/py/.venv*` | gitignored | `36e195a` 删 17 个死 spike、`ea48193` 删 texsoup_rt | 一次性探针，选型期使命完成 |
| `bench/results/` 整体 | 划出 format/lint（`a615c87`） | — | 脚本产出目录，重跑即重写；不是 gitignore，是 gfs/lint 豁免 |

### 2d. tmp/ 与其余 gitignored 引用

| 路径 | 关联 commit | 说明 |
|---|---|---|
| `tmp/exp/miniscanner{,_test}.py` | `06c3fa9` | spike 原件退役处；断言矩阵已移植 tests/test_bench_regression.py（54 例） |
| `tmp/exp/corpus-cbh` | `c2d17b2`/`af7bf2e` 的 "corpus-cbh" 标签 | parsebench 3937 文件 rerun 的现场工作区；证据摘要在 `argspec-verbatim-2026-09-16/`（入库） |
| `tmp/exp/rule-validator` | `a9b6a16` | xlatbench 曾 sys.path 插这里——clean clone 必炸，已改产品 L0 |
| `tmp/exp/` 其余 ~90 项（s3probe/s4probe/s3dead*/run_sabotage*/src-snapshot-*/trace-0806/escape_probe 等） | P4–P10 各修复/跑批 commit | 全部 gitignored；segmenter S3/S4 调试探针集群 |
| `tmp/refs/`（BabelDOC/plasTeX/texglot/ieeA/LaTeX.js 等 12 个 clone） | `4a37980`（pytest norecursedirs 修 INTERNALERROR） | 参考实现，不删 |
| `tmp/research/` | `3f4107a` | 已升格为 docs/research/（45 篇入库），原目录废弃 |
| `tmp/upload501-worker.patch` | `3ee827b` | worker _run_doc 落地前的交接 patch；`8d50c38` 已真正落地，patch 已具历史意义 |
| `tmp/` 其余（live-smoke-data、doc-e2e-data、realbook、stash-recovery-0958、transcript-mining、preclean 等） | 对应各冒烟/运维 commit | 整目录 gitignored |
| `docs/research/lit/` | `3f4107a` | 文献原件 PDF/HTML，可再生 |
| `src/texlate/server/static/` | `fbb138d`/`60bc027` | SPA 构建产物拷入位；sdist/wheel 经 hatch artifacts 携带，git+ 安装无此目录（CLI-only 已知缺口） |
| `~/.cache/texlate/`、`tasks/{id}/`、`work/`（server 侧） | `d400669`/`836f0b0` 等 | 运行时数据，不在仓内 |

## 3. 重要修复/决策 commit（精华 22 条）

| commit | 主题 | 为什么重要 |
|---|---|---|
| `a7db4ee` | 大对比 20 份报告 | 路线裁决原点：8 库全灭于宏展开 T01、pylatexenc 静默截断 99% 被 REJECT、miniscanner spike 扶正、fixloop 16/16、tree-sitter 降为校验器 |
| `f461683` | v2 产品面切换 | 唯一 BREAKING CHANGE：parse_tex/parse_file 默认 token 流，`TEXLATE_NO_EXPAND=1` 回退；验收 1955/1955 strict |
| `4287794` | visible_tex i+=end 位移 bug | 全仓影响最深的单字符级 bug：遮盖视图大面积漏遮，且揪出 `verbatim*` 未 escape 从未生效 |
| `7a13735` | mask_tex env 终点 overshoot | 同族第二击：`env.end()` 已是绝对 offset 再加 i，`\begin{document}` 被吞→no_main_tex；旧蛙跳 bug 曾掩盖它 |
| `dbc58a4` | run_process stdin=DEVNULL | 确定性裁决：TeX 缺文件问名吃 harness stdin 导致同论文 r1 partial/r2 fail 翻转；钉死后 missing_file 归因稳定 |
| `98cfb11` | sandbox profile 三盲区 | mktexpk→xdvipdfmx fatal→xelatex SIGPIPE 的完整归因链；TMPDIR canonical/subpath 不匹自身/HOME metadata 三修 |
| `38ff9fa` | resume 语义三修 | n100 splice 残留 1524 根因=source 漂移嫁接陈旧译文；prev.source 比对+[[SL]] 装配解码（s40 幻觉占位符真根因） |
| `5a23571` | 429 body retry_after | 网关契约实证：retry_after 在 body 不在 header；PROMPT_VERSION→v2 缓存键纪律 |
| `d087f54` | fixloop 规则库 v2 | eps_route 拆 ps_image 确证链；repl f-string 转义 bug 使 font_sub_shim/bbl_stub_rewrite 从未真正运行 |
| `38cc0a7` | tlmgr 装包层 | M2 第一杠杆实证：missing_file 111 格 90 真装 85 出 pdf；documentstyle 降级 ~23% 假阳性纠正 |
| `6c2e582` | tar 加固 + aux 截断更正 | 根因更正：非我方截断而是 XeTeX 写缓冲在 8192B 边界劈断多字节字符 |
| `b6ba25a` | 截断中间件 line-boundary trim | 上条的闭环修法：可再生中间件截尾回行界/删除重跑 |
| `6b23435` | audit wave2 compile 簇 | bwrap resolve/TMPDIR 私挂/tectonic -Z shell-escape 后门白名单/sandbox=env 剥 \write18 |
| `3c5aae2` | audit wave2 fixloop | when/condition key fail-open 修 fail-closed；CtanFetcher 不再原地 mutation 共享 index；llm_hook 四接点 |
| `5d195c2` | taxonomy 单源化 | engine 删 _ERROR_RULES 改由 rules.yaml lazy 派生——"a copy is a drift source" |
| `9299802` | filemap 三路 | overrides 全引擎前置（原 tectonic-only）；INDEX/OVERLAY 解耦（.tex 只索引不平铺防遮蔽项目源）；cs glue-split 通用规则 |
| `2f12955` | never-regress floor | fixloop 保底不变式：entry pdf 快照、tree-kill 时回填；floor_restored 计入回归 |
| `daf6a2a` | F3 verdict 语义 | reject 不是 status：三路 reject 综合点为 partial+reject_at{fixloop,inject,route}，cli 退出码改挂 reject_at |
| `165d23f` | leftover_ph 升级 fault | 幻觉占位符不可 splice 解析→fault+fallback 原文+cache 防毒+resume 自愈；14 新例 |
| `60bc027` | sdist 白名单 | 默认 sdist 吞了 24G bench/results（152k 文件、14min、tmpfs 爆）；白名单后 15s/4.6M |
| `add5618` | babeldoc spawn 契约 | upload_pdf 链从未真跑通：TOML key 错名/缺 /v1/stdout=DEVNULL 吞进度/pty 0×0 四连致命 |
| `1bb213d`+`70dab0f`+`ce842ef`+`8b62efb` | tailscale 网关通路 | 默认 base_url 改 tailnet 直连（loopback 会绕过 gwcap 且随会话死）；CGNAT http 放行；gwcap redirect 限 gateway IP + tailscaled 重启后再断言 bypass |

## 4. 未入库引用清单（清理判定核心）

commit 提到、但磁盘上是 gitignored 或 untracked 的产物：

1. `bench/results/babeldoc/`——显式 gitignored（a7db4ee 自立规则），BabelDOC 冒烟 PDF/PNG/log；报告件已入库，数据可重跑再生。
2. `bench/results/postfix-2026-09-16/`——untracked；loop1 修复波后 e2e_real 65 篇验收跑（pipe-xel clean 40/65、残留 0）。**是 09-16 傍晚修复有效性的唯一汇总证据，建议入库后再清。**
3. `bench/results/repro-1306-2026-09-16/`、`repro-2410b-2026-09-16/`——untracked；7b87546/88d0ab9  dispatchable 的根因包，report.md 已含完整现场。**建议入库（其它 repro-* 同族都已入库）。**
4. `bench/results/stagerun-loop1-2026-09-16/rerun-ids-loop2delta.txt`——untracked 单文件，loop2 delta 名单。
5. `bench/results/stagerun-*/work/`——dir-local gitignore，loop1 的 44G 中间树是最大单块；records/metrics 已入库，work/ 可重建可删。
6. `bench/work_*/`——18 目录 ~63G 全 gitignored；均为对应 bench 的可重建工作区。
7. `bench/corpus*/` 数据层——~20.5G gitignored；manifest/台账/nominations 入库，论文数据可从 IA 重取（`manifest_expand.jsonl`/`manifest_hot.jsonl`/`manifest_booster.jsonl` 均入库）。
8. `tmp/` 整目录——gitignored；`tmp/exp/` 有 ~90 个探针现场（S3/S4 调试、sabotage、corpus-cbh、src-snapshot-*、miniscanner spike 原件）、`tmp/refs/` 12 个参考 clone、`tmp/upload501-worker.patch`（已被 8d50c38 取代）。删除前注意 `tmp/preclean/` 自身也在其内。
9. `docs/research/lit/`——文献原件，可再生。
10. `src/texlate/server/static/`——build-web.sh 产物，wheel 另有携带路径。

反向注意（勿误判）：`bench/corpus_v3/nominations/` 是**入库**的（ab7a8c9 unignore）；`bench/results/metrics.jsonl` 是入库的全局趋势文件；corpus_v3 的五个 manifest + mechanisms.jsonl + select_booster.py + booster_selection.jsonl + selection_report.md 均入库；`tests/fixtures/*.log` 有 `!` 豁免（2f94899 特意放开）。
