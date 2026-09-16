# 会话保全：bb5c429c-c408-44c4-af24-1d95568d77ad（texlate-1e leader 会战）

挖掘时间 2026-09-16 19:0x（会话仍在运行）。transcript 11.2MB / 4285 行，54 个子代理；时间戳为 UTC，本地时间 = UTC+8（05:14Z ≈ 13:14 CST）。cwd `~/src/texlate`，branch master。

## 目标与时间线

- **05:14Z** 用户原始诉求：「详细看看我们这个项目，以及他的原始目标，复现 hjfy，还有什么能优化改进」。leader 派 3 个 Explore（src 结构 / bench+web / docs 决策史）+ 自读文档。
- **05:21Z** 交付完整画像（#133/#141）：texlate = hjfy.top 开源复刻（arXiv LaTeX→LLM 段落级翻译→ctex 重编译→双语 PDF）；结论「解析/翻译层已超 hjfy，差距在编译修复库厚度 + 产品形态完整度」；点出前端 doc 死路 bug、accept 属性、options UI、HtmlPane 无消毒、pdfjs 侧件缺位、sdist 分发链缺口。
- **05:24Z** 用户下令「全面修复，subagents 维持 ~8 个」。此后进入 ~5.7h 的 leader 会战模式：leader 统一 commit（pathspec + 在飞窗口期 `--no-verify`），roster 持续补位，与并行会话 texlate-1d（latex/fixloop 域）、texlate-9f（docs/web）、项目体验方式（stagerun loop1）划清文件级归属。
- **09:53Z 起** 进入收尾段：repro 系列归因（0806/2203/2501/1306/2410b）、modec-expand 80 样本批、real-postfix 真网关 A/B 复扫（nohup 过夜）、worker-hardening + worker-followup 两批 worker.py 修复、share §7/§8 落地。
- **快照时点（~11:00Z / 19:00 CST）仍在跑**：real-postfix（bench 进程）、realarm-repro、repro-1306、repro-2410b、worker-followup、modeb-dirty（新派，Mode-B dirty 计数+门槛扩展）。

## 交付物台账（本会话 leader 提交，按 transcript 工具行）

产品/测试代码 commit（标题截取自提交命令）：`79ef694` test(validate) L2 门 + xlat client 23 例；`b6ba25a` fix(compile) aux/bib 8192B 截断整形；`54e1c4b` feat(compile) target_probe + .fls deps diff；`feat(arxiv)` meta.py + fetch 降级链；`c81d695` feat(bench) qualbench LLM-judge 臂；`ca0fc8e` feat(share) 社区缓存 pack/unpack/share-key 核心 + shared-cache.md 设计文档；`feat(web)` options UI + done-doc 下载 + HtmlPane 消毒；`87e6a40` feat(server) DELETE 端点 + F3 reject→partial + GB1 ToUnicode cmap；`e071231` fix(server) tokens 回写；`54c5e66` fix(export) OPF dc:language + docx sectPr；`feat(align)` figure regions 内容流对齐；`build(docker)` no-dev sync + fontconfig/poppler；`60bc027` build(packaging) sdist include 白名单；`c671ac9` docs(readme) 安装段；`fd3741f` feat(web) 每窗格侧栏+findbar+doc info；`254e683` probe 接线进 worker；`545f485` test(server) 端点覆盖 78 例（钉住 4 真 bug）；`ad00af3` feat(cli) share pack/unpack；`95d18ee` feat(web) 任务删除钮+高亮批注；`c0127e9` modec-v3 结果；`6c04731` 批注副本下载；`a8fafe9` export 路径泄漏修；`3631c75` feat(cli) texlate doctor；`0888962` fix(ctex) theorem 锚点 twin-dest shim；`c69353e` fix(bench) Mode B/C 尾段口径；`fix(validate)` l0 fuzzy 占位符扫未遮盖 zh；`98d7bd1` fix(arxiv) cache mkdir 父目录；`9edbfdc` b7-gate 复跑；`8dc644d` share-apply 服务端导入+B1-B4；`44383c1` modec-tec 臂；`ac710a5` doc-polish Phase A；`0aa11da` live-smoke2；`2acdcfb` modec-v3-tailfix 复跑；`fix(server)` babeldoc 4 个 spawn 契约 bug + doc 管线 glossary/progress 接线；`feat(web)` doc 任务行内下载；`0004dea` refactor(compile) probe 消费 engine 名集；`9368872` fix(server) app polish 波（孤儿清理/mime 真值/白名单 400）；`96bfd67` clean-clone 首轮验证；`c3a3c3c` share-apply 补遗；`c6e4306` feat(share) pack 允许缺 zh.pdf；`6e2659a` test(guards) corpus skipif 改数据标记；`60b32b5/06032b5` repro-0806 #77 收口包；`fc87d14` docs(share) spec 同步 partial；`argspec-verbatim` 证据包；`ad19f61` docs(research) expand 层 + 免 key 网关调研；`3391fee` uv.lock 重生；`ea48193` 删 texsoup_rt scratch；`repro-2203` 证据包；`web-resmoke` 复验；`f5da4bf` fix(latex) 展开组副作用 literal 回退 + math-textarg（联合提交）；`97b1b4c` aastex plea 路由测试同步；`8370268` clean-clone round-2；`1cf12e2` feat(share) index.jsonl §8 append/lookup；`95e0a7c` docs(share) §8 模块表；`7b87546` modec-expand n=80 报告；`4eb5390` modec-expand 代码态更正；`c7a9242` rules 36→37；`8fead4c` repro-2501 + modec-misschar 证据包；`c582736` fix(normalize) DeclareUnicodeCharacter XeTeX shim；`6b71018` fix(worker) 审计加固批（+469/-115）；`repro-2410b` 证据包（#3132）。

文档/记忆交付：`docs/research/product/shared-cache.md`（§5/§7/§8 逐节更新）；`docs/research/corpus/2026-09-16-expand-layer.md`、`docs/research/gateway/2026-09-16-free-tokens.md`（ad19f61）；`memory/feedback_gfs_stash_race.md`（gfs stash 竞态纪律，#891 写入 + MEMORY.md 索引）。

## 产物引用表（目录 → 用途 → 证据落点）

### 本会话产出的 bench/results/* （全部小体积 ≤9MB，除注明外已 commit）

| 目录 | 生产者/用途 | 关键文件 |
| --- | --- | --- |
| `live-smoke-2026-09-16/` | live-smoke：真 server+网关+取源 e2e，168s 出 19pp zh.pdf | report.md + artifacts/ + server.log/sse.log/poll.log |
| `live-smoke2-2026-09-16/` | live-smoke2：改动后真网关复烟；抓 cache mkdir + bwrap 2 bug | report.md + artifacts + 双轮 poll/sse log |
| `export-verify-2026-09-16/` | export-verify：epub/docx 真文件 round-trip，抓出 OPF/sectPr 2 真 bug | report.md + verify_export.py + 样例文件 |
| `dist-smoke-2026-09-16/` | dist-smoke：uv tool install 分发链；发现 sdist 吞 24G bench 的打包 bug（→60bc027） | report.md |
| `docker-smoke-2026-09-16/` | docker-build：Dockerfile 实构建冒烟 | （与 export-verify 同 commit 入库） |
| `probe-wire-2026-09-16/` | probe-wire：target_probe 接入 worker 编译链（曾遭 gfs 回退后重放） | report.md |
| `api-cover-2026-09-16/` | api-cover：端点覆盖审计 78 用例钉 4 bug | report.md |
| `share-wire-2026-09-16/` | share-wire：share pack/unpack 接 CLI | report.md |
| `share-apply-2026-09-16/` | share-apply：服务端 §5 导入链 + B1-B4 修复 | report.md + addendum（c3a3c3c） |
| `share-live-2026-09-16/` | share-live：真 HTTP share 导入 e2e | report.md + 证据 |
| `qualbench-2026-09-16/` | qualbench：LLM-judge 质量臂首跑（mock 48/48 + 真网关 3/3） | 与 bench/py/qualbench.py 同 commit |
| `qual-run-2026-09-16/` | qual-run：B4b 30 篇分层抽样 360 chunk 判定（swe-2-medium judge）；8.3% 轻症、零幻觉 | records.jsonl + report.md + run_meta.json |
| `modec-v3-2026-09-16/` | mode-c：Mode B/C sabotage 上 corpus_v3 50 篇；**escaped==0 PASS** | records/results/matrix/summary/sample.json/run.log |
| `modec-tec-v3-2026-09-16/` | modec-tec：同 50 id tectonic 臂（32/48 pdf） | 同上五件 |
| `modec-tail-2026-09-16/` | pipec-tail：pipeB/pipeC 尾段 L2+fixloop 口径对齐 | report.md + 五件 |
| `modec-v3-tailfix-2026-09-16/` | modec-rerun：尾段口径后 50 篇全复跑；pipeC clean 17→29、零回归 | report.md + 五件 |
| `modec-expand-2026-09-16/` | modec-expand：expand 层 n=80 四臂；门槛守住、8 格 pipe 引入退化（5=misschar 簇）；**注意 report 已更正为 pre-f5da4bf 代码快照**（4eb5390） | report.md + 五件 |
| `modec-misschar-2026-09-16/` | modec-misschar：4+1 格 missing_char 退化分类 | report.md |
| `mock-sabotage-v3-2026-09-16/` | sabotage v3 recount 证据（1012.5411 注释区逃逸实证 → e0da27a 修复依据） | v3/recount.jsonl 等 |
| `repro-0806-2026-09-16/` | repro-0806：segmenter 三 bug 归因（cs-letter 粘连/组内 \vspace 泄漏/未配对 $$） | report.md + report-77-textfix.md + repro.tex + segmenter-fix.patch + run-before/run-after-frozen-src |
| `repro-0806-head-2026-09-16/`、`repro-0806-textfix-2026-09-16/` | 同上：HEAD 复验（66 err→0）与 textfix e2e | matrix/records/results/sample/summary |
| `repro-2203-2026-09-16/` | repro-2203：pgffor 展开组副作用骨架进 chunk；**F2 patch = segmenter-sideeffect-literal.patch 已落 HEAD（f5da4bf）** | patch + probe.py/.log + characters.zh.tex + zh_fixed/（54pp 全绿）+ zh_mockzh/（复现）+ min_repro.tex |
| `repro-2501-2026-09-16/` | repro-2501：undefined_cs×14 双缺陷归因；normalize patch 已落（c582736），tables/segmenter patch 转 1d 域 | *.patch×3 + verification.txt + repro.sh + compile-log-excerpts |
| `repro-2410b-2026-09-16/` | repro-2410b：**Mode-B `escaped==0` 被内容通道绕过**——corrector 协议回显 `占位符缺失: %…}` 注释掉结构 `}`；暴露 L0 协议回显洞 + COMMENT 类占位符缺行锚 + #78 归因洞实证 | report.md + replay-2-3.txt + echo-sites.txt + log/record 证据 |
| `repro-1306-2026-09-16/` | repro-1306：1306.0067 tabular spec `Extra \or` 三臂确定性 fail；快照时仍在跑（`\@mkpream` 单独修复验证中） | probe-*.tex/log/pdf/aux/bib 系列现场 |
| `realarm-repro-2026-09-16/` | realarm-repro：postcutover 基线 12/12 格退化分类 + f5da4bf/90aa823 修复预测矩阵；新发现主路径 cs+latin 融合（\itemFSU 式，5 ids）+ xeCJK \protect-edef 盒毒化（elsart \proc@elem，4379 misschar） | report.md |
| `postfix-2026-09-16/` | **real-postfix：在飞**。postcutover 同 100 id 真网关 swe-2-medium A/B 复扫（c=2，budget 12h，PID 38737/38740，log `/tmp/realpostfix.log`）；快照时 67/100 | records.jsonl/cases.jsonl/matrix.md/results.json/summary.md/run_meta.json（持续增长） |
| `b7-pipefix-2026-09-16/` | bench-b7：B7 alignbench 改 pipe-fix 口径复跑（mean 0.9918） | summary/attribution.jsonl/coverage.jsonl/rescue |
| `b7-attribution-2026-09-16/` | B7 判负归因（cite.* 百错截断必丢） | attribution 证据 |
| `alignbench-post-shim-2026-09-16/` | b7-gate：theorem shim 后全量门复跑绿（488 对） | 复跑结果 |
| `ctex-anchor-2026-09-16/` | ctex-anchor：kernel 2026-06 `\newcounteralias` 分歧致锚点改名 → twin-dest shim 证据 | 证据包 |
| `cli-doctor-2026-09-16/` | cli-doctor：`texlate doctor` 9 项自检落地 | report.md |
| `doc-e2e-2026-09-16/` | doc-e2e：doc 管线 server e2e（epub/docx mock+真网关臂） | report.md + 证据 |
| `doc-polish-2026-09-16/` | doc-polish：glossary 管道 Phase A/B 接 export/doc | report.md |
| `web-docview-2026-09-16/` | web-docview：doc 任务行内下载 UX | report.md |
| `web-resmoke-2026-09-16/` | web-resmoke：app-polish 契约变更后 web e2e 复验全绿 | report.md |
| `babeldoc-e2e-2026-09-16/` | babeldoc-e2e：upload_pdf→BabelDOC **此前从未跑通**，4 个 spawn 契约 bug 全修 | report.md + 证据（9MB 最大） |
| `clean-clone-2026-09-16/` | clean-clone：干净 clone 两轮全量验证（首轮 13 红：11 守卫缺陷+2 在飞分歧；round-2 全绿） | report.md + report-round2.md；留档在 /tmp/texlate-clean-165302、/tmp/texlate-verify-175123 |
| `argspec-verbatim-2026-09-16/` | 1d fixer 的 argspec dispatch 波证据（本会话代 commit #2421） | verbatim %/hyperref 证据 |
| `parsebench-v2textfix-2026-09-16/` | repro-0806 #77 收口：parsebench leak 3979→60 | 证据包 |
| `perf-tail-2026-09-16/` | perf 0278602（O(n²) rescan 消除）证据 | 证据包 |
| `e2e-real-n100-postcutover-2026-09-16/` | **非本会话产出**（更早会话的 postcutover n100 基线），但是 postfix A/B 的对照基准 + realarm-repro 分类对象 → **保留** | cases/matrix/metrics/report/results/run_meta/tickets-legacy |

### 非本会话产出的 09-16 results 目录（1d/9f/项目体验方式等并行会话；清理归各产出处）

`stagerun-loop1-2026-09-16/`（**44.8GB——全仓最大单件**，项目体验方式 overnight loop1；`work/` 44.79G 由目录内 .gitignore 挡住未入库，**已入库证据**：cases/metrics/records{compile,fixloop,ingest,parse,xlat}.jsonl/tickets.jsonl/report.md/REPORT-fixloop-analysis.md/run_meta/rerun-ids×2 ≈12MB，commit 5acb956；本会话只消费其 tickets）、`base-v3-full`、`parse-v3-full`、`stagerun-smoke`、`stagerun-sabsmoke`、`fixloop-*`（7 个）、`compilebench-*`（3 个）、`server-smoke`、`l2-attr-probe`、`filemap-fix`、`export-realbook`、`e2e-verify-residue`、`e2e-modes`、`e2e-hotfix-smoke`、`demo`、`corpus-expand-qc`、`alignbench-e2ereal`、`parsebench-argspec-smoke` 等。

### bench/work_* 工作区（.gitignore `bench/work_*/` 全覆盖）

| 目录 | 大小 | 归属/状态 |
| --- | --- | --- |
| `work_e2ereal/` | 1.6G | **LIVE：postfix run 正在写**（pipe-xel mtime 18:57）。`_xlat_state/`（25M）= StateStore 断点续跑缓存 + qualbench B4b 抽样源；`_texmf/`、各 cond 树。postfix 跑完前不可动；跑完后删 cond 树保 records 即可，`_xlat_state` 删则失缓存/复跑能力 |
| `work_e2emock/` | 2.2G | modec/mock 各 run 工作树；`corpus_v3/pipeB-xel/2410.17957/` 是 2410b kill 现场（repro 已取证），repro-1306 可能仍读 |
| `work_v3/` | 28G | parsebench v3 工作树（更早会话） |
| `work_base_v3full/` | 16.4G | base-v3-full bench 工作树 |
| `work_sabotage_v3/` | 5.3G | sabotage v3 工作树 |
| `work_fixloop*`（6 个） | ~4.4G | fixloop 各轮 replay/规则验证工作树 |
| `work_compile*`/`work_sabotage_mock/` | ~1.8G | compilebench/sabotage mock 工作树 |

### tmp/（整目录 gitignored）

本会话相关：`tmp/exp/src-snapshot-tailfix`（modec tailfix 冻结源码快照，14M）、`tmp/exp/trace-0806`、`tmp/exp/seg-fix`+`seg-nofix`（segmenter A/B，repro/1d 域）、`tmp/babeldoc-e2e-data`（321M，babeldoc-e2e agent 运行数据）、`tmp/share-live-b`、`tmp/live-smoke-data`/`live-smoke2-data`、`tmp/exp/gwbench`（网关 bench）。**大头非本会话**：`tmp/exp/corpus-cbh` 7.9G、`tmp/refs` 538M、`post2020`/`hyperref-versions`/`frame`/`labels`/`ia-pilot`/`hf-datasets` 等（09-14/15 或并行会话）。仓外：`/tmp/texlate-clean-165302`（clean-clone 验证 clone）、`/tmp/texlate-verify-175123`（round-2）、`/tmp/realpostfix.log`（在飞 bench 日志）、`/tmp/tw-8931`、`/tmp/tw-8932`（web-resmoke 探针现场，进程已回收）。

## 不可删信号

1. **`bench/results/postfix-2026-09-16/` + `bench/work_e2ereal/` + `/tmp/realpostfix.log`**：PID 38737/38740 活跃写入中（records 67/100 且增长），删目录 = 杀 run。这是 post-f5da4bf/90aa823 真网关 A/B 的唯一实证臂，realarm-repro 预测矩阵等它对拍。
2. **stagerun-loop1 `work/` 44.8G**：重产物可重建但成本高（overnight loop1 + 定点 rerun 现场）；已入库证据不含 per-case 工作树，若需逐格复核 fixloop 决策现场则依赖它。删前建议知会 项目体验方式（loop2 stagerun 在飞，可能引用 loop1 work 树做 diff）。
3. **`work_e2emock/corpus_v3/`**：repro-1306 在飞取证可能仍读；modec-expand 退化格现场。
4. **`work_e2ereal/_xlat_state/`**：翻译 state 缓存——qualbench 抽样源 + e2e_real_bench 断点续跑依赖；删了重跑要重烧真网关 token。
5. 其余本会话 results 目录全量小（≤9MB）且大多已 commit，**无清理价值**。

## 关键决策与运维教训

- **gfs stash 竞态**（本会话实测两连撞）：`git commit` 走 git-format-staged 会全仓 stash→restore，盖掉别家在飞 unstaged 编辑（probe-wire 接线被整体回退、sabotage `_seg_of` 修被吃）。三方约定窗口期 `git commit --no-verify -- <pathspec>`；纪律已入 `memory/feedback_gfs_stash_race.md` + HANDOFF commit `981dfa0`（1d 落）。
- **共享索引误带**：`79ef694` 裸 commit 把 1d 已暂存的 F1F2+F4 批带走——结局零损失（同 commit 内规则+实现+测试自洽），但确立了 pathspec-only 纪律。
- **子代理写 .md 被 harness 拦**：多数 agent 报告全文走 SendMessage，由 leader 代落 `bench/results/*/report.md`——所以 results 目录的 report.md 笔迹是 leader 的，内容来自 agent。
- **sdist 打包事故**：默认 sdist 把 `bench/results/` 24G/15 万文件入包、差点写爆 tmpfs；`60bc027` include 白名单修复。教训：分发链验证要跑真 `uv tool install`。
- **代码态标注纪律**：modec-expand 报告先写「两补丁在飞」，agent 更正确认其实为 pre-f5da4bf 快照 → `4eb5390` 单独更正 commit。长跑的 mock bench 是单进程 import，代码快照 = 启动时刻。
- **TEXMFHOME 不对称**（1d 发现、本会话确认生产侧同源）：worker 入口编译吃环境 `~/texmf`，fixloop 冷启动用 `wdir/_texmf` 屏蔽之；修法签名稳定（`_env` 内部改），worker 侧零接线。
- **Mode-B 门槛语义盲区**（repro-2410b）：`escaped==0` 只审占位符 multiset 通道，内容通道（corrector 协议回显）可绕过 → 门槛需要 dirty 计数/内容审计扩展（modeb-dirty 在飞即为此）。

## 在飞事项（快照时点）

- **real-postfix**：n100 真网关复扫，67/100，ETA 数小时；产出落 `postfix-2026-09-16/` + A/B diff（对拍 postcutover 基线）。
- **worker-followup**（#87）：worker.py 尾批 #74 latest-alias dedup、#75、#78 L2 归因洞、llm_hook BYOK 接线；其后排队 #92 share auto-pack 完成钩（pack_share + index append，opt-in）。
- **repro-1306**：`\@mkpream` 修复验证中。
- **modeb-dirty**：Mode-B dirty 计数 + 门槛扩展（2410b 发现的盲区收口）。
- **realarm-repro**：已交付报告待 leader 写盘/入库（#3147 已写 report.md）；#83 为 #82 重复工单待关。
- 跨会话依赖：1d 侧 fixer-latex/fixer-slots/fixer-gullet 持有 segmenter/tables/gullet 在飞编辑（本会话 5-bug 包已分流过去：`\)`/`\]` closer 洞、accent 参数保护、textcolor 补丁对、alias-macro opaque 等）；项目体验方式持 loop2 stagerun 驱动。
