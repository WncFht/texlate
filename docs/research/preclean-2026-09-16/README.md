# 清理前知识保全总账（2026-09-16 磁盘 99% 触发）

> 触发：磁盘 `/` 917G 用 855G 余 16G（99%），准备清理 bench 重产物前做知识保全。
> 方法：多矿工并行挖掘 —— 会话 transcript（session-transcripts 工具）+ git 历史 + 磁盘实测（run_meta/git ls-files/ps）。
> 本目录即保全包：`README.md`（本文件，总账）+ `artifact-map.md`（逐目录判定表原件）+ `git-timeline.md`（349 commit 分期与产物→commit 映射）+ `docs-inventory.md`（docs 90 篇→磁盘产物引用对账：被引用者必须保留或先在文档标注已删）+ `gitlog-full.txt`（`git log` 全量原文）+ `sess-*.md`（三个大会战会话 + 中号批次共 12 会话的挖掘报告）+ `transcript-mining/`（更早一轮 27bd911f 会话的 10 份挖掘报告，从 gitignored `tmp/` 抢救入库）。
> 状态快照时点：2026-09-16 ~19:15 本地。**loop2 delta rerun 与 postfix n96 均在飞**——清理动作必须等它们落地（见 §4 红旗）。

## 1. 项目状态（快照）

- 目标：开源复刻 hjfy.top —— arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF，双语对照。终极目标：**所有 arXiv 论文干净翻译**（语料/bench 只加层不删层）。
- 里程碑：M0 已验收、M1 实质达成、M2/M3 推进中（全仓审计 `docs/research/audit-2026-09-16/`：13 维 verdict + 5 个 P0 安全发现 + wave2-findings ~75 条台账）。
- 关键数字（loop1，corpus_v3 n=5059 解析成功集，`stagerun-loop1-2026-09-16/`）：ingest 99.7% → parse 98.4% → xlat mock 98.0% → 终态 **pdf 86.1%（4355/5059）、clean 49.0%**；对照裸源双引擎 71.3%。fixloop rescue 84.0%。
- 代码规模：手写 ~81k 行（src 29.7k + tests 11.5k + web 4.0k + bench 22.2k + docs 13.6k）；`scripts/loc.sh` 是同口径脚本。
- 结构：`src/texlate/` 产品（latex v2 Gullet+Segmenter 默认、`TEXLATE_NO_EXPAND=1` 回退）；`bench/py/` 评测器（stagerun/triage/rundiff/parsebench/compilebench/fixloop_bench/e2e_real_bench/qualbench/alignbench…）；`bench/results/` 119+ 证据目录；`bench/corpus*/` 三层语料 20.5G；`web/` SolidJS 阅读器；`server/` FastAPI+SSE+SQLite+BYOK+babeldoc sidecar。
- 三方会话协作模型（本周期独创）：**texlate-1d**（leader：latex/e2e/fixloop/bench/tests + 统一 commit 己侧）、**项目体验方式/53215cda**（数据侧：语料扩库 + loop1/loop2 执鞭 + rules.yaml + engine.py）、**texlate-1e/bb5c429c**（server/worker/probe/web + share + 真网关验证）。文件级归属 + 跨会话消息路由。

## 2. 决策史（为什么是现在这个样子）

按 `git-timeline.md` 的 P0–P10 分期浓缩；每条给「决策 → 依据 → 落点」。

### 路线层

1. **自研半解析管线，弃一切现成库**（09-14 P0，`a7db4ee`）：pylatexenc/TexSoup/plasTeX/unified-latex/tree-sitter/latexjs/latexml/LaTeXTrans 8 库全灭于宏展开 T01；pylatexenc 静默截断 99% 被 REJECT。→ `src/texlate/latex/` 自研，tree-sitter 降为校验器。
2. **v2 Gullet+Segmenter 为产品默认**（`f461683`，唯一 BREAKING）：plasTeX 移植展开机 + S1–S4 切片（vtex 账本/run 双轨/展开组/`\if` 界标档）；验收 corpus_v3 3937 文件 identity 100%/leak 0.040%；`TEXLATE_NO_EXPAND=1` 留 v1 对照臂。
3. **fixloop = yaml 规则引擎 + 三类 fallback**（spike 16/16 扶正 → v2/v3 扩到 37 规则）：rules.yaml 单写热点归 leader；taxonomy 单源化 `5d195c2`（engine 删 `_ERROR_RULES` 改派生——"a copy is a drift source"）。
4. **分阶段批量 stagerun**（设计稿 `docs/research/product/2026-09-16-batch-hardening-design.md`）：ingest→parse→xlat→compile→fixloop 各扫全集、`records/{stage}.jsonl` append 即 resume、`work/{id}/` 产物树衔接、臂成 stage 参数。**语义坑已实证**：`--rerun` 就地 append（loop1 基线=最后入库版）；`--layers` 默认 core（loop2 首轮静默只跑 227/1310 → delta 清单补救）；zh/ 单槽被 real 臂覆写（48 id 永无 mock 对照，臂序须 compile-mock 先）。
5. **评测门禁**：escaped==0（sabotage）、leak≤0.05%、契约≥99.9%、rescue 单调不降；`triage.py` 末条胜去重 + `fixloop_degraded` 跨段探测 + upstream-gate 豁免；`rundiff.py` 两 run 迁移矩阵。

### 产品层

- server：FastAPI+SSE+SQLite 任务队列+BYOK+share bundle 社区缓存（pack/unpack/index.jsonl §8）+babeldoc sidecar（4 个 spawn 契约 bug 修复后首通）+SPA 入包 staticfiles。
- 编译：xelatex 主 + tectonic 备；ctex/xeCJK 注入；bwrap sandbox（unshare+texmf ro+env 白名单）；`documentstyle` 从硬拒改 suspect 试编→受限 209→2e 升级器（在飞 latex209.py，探针估 40-65% 可转化）。
- 翻译：网关 swe-2-medium 主粮（Windsurf promo 免至 **2026-10-16**）；gwcap 本机硬闸 4（nftables REDIRECT :3003→:3399 代理）；只走 tailscale 直连或 gw-tunnel.sh，**禁 VS Code 端口透传**（黑洞）。兜底档：Prism/llm7/pollinations 机会型 + 建议 ollama Qwen3-14B 永久兜底。

### 血泪教训（已验证的坑，别重踩）

- **gfs stash 竞态**：`git commit` 走 git-format-staged 全仓 stash→restore，会盖别会话在飞编辑。多会话窗口期一律 `git commit --no-verify -- <pathspec>`；恢复查 `~/.cache/pre-commit/patch*`、`scripts/git-stash-export.sh`。
- **TEXMFHOME 遮蔽不对称**：入口编译见 ambient `~/texmf`，fixloop/出口复判冷 `_texmf` 把 ~/texmf 整树遮掉——loop1 真退化 4 格里 3 格是这假象。修法=engine `_env` 内部串链（裁决中）。**反向同理：`~/texmf` 被 ctan 装包污染过（youngtab.sty），别顺手"修"它，那是证据态。**
- **uv.lock churn**：`UV_DEFAULT_INDEX=aliyun` 覆写 tuna pin——commit 前 `git checkout uv.lock`，lock 本身不 commit。
- **sdist 吞包事故**：默认 sdist 把 bench/results 24G/152k 文件入包爆 tmpfs → `60bc027` 白名单（15s/4.6M）。分发链验证必须跑真 `uv tool install`。
- **stdin=DEVNULL 裁决**：TeX 问名吃 harness stdin 致同论文 r1/r2 翻转（`dbc58a4`）。
- **subagent 写文件被拦**：agent 报告全走 SendMessage，leader 代落盘——results/*/report.md 笔迹是 leader 的。
- **代码态标注**：长跑单进程 bench 的代码快照=启动时刻（modec-expand 报告先写错后 `4eb5390` 更正）。
- **Mode-B `escaped==0` 盲区**：只审占位符通道，内容通道（corrector 回显）可绕过（repro-2410b 实证）→ modeb-dirty 门槛扩展在飞。
- **跨段退化必须直编复验**：记录面 partial→fail 17 格，真退化仅 4。
- **主线程空闲时 Ctrl+C 会杀全部后台 subagent**（#87140）；`Ctrl+X Ctrl+K` 专杀后台。
- 更多：`docs/tools-runbook.md`（隧道三坑/nft 调试/xelatex ~100 错截断/zh/ 共享树排序/records append 语义等）。

## 3. 产物→证据映射（结论速查；逐项明细见 `artifact-map.md`/`git-timeline.md` §2）

证据链分四层：**入库证据**（results/*/report|summary|jsonl，已 commit）→ **会话台账**（本目录 sess-*.md）→ **在飞未入库**（?? 态）→ **可再生的重产物**（work_*/tmp/）。

- loop1 总账：`stagerun-loop1-2026-09-16/`（records 五件+cases 1925+tickets 455+metrics+REPORT-fixloop-analysis 已入库 `5acb956`/`86908bc`/`64bd7f7`）→ 解读文档 `docs/research/2026-09-16-loop1-status-and-next.md`。
- 审计全账：`docs/research/audit-2026-09-16/`（README+14 分报告+wave2-findings.md）。
- 语料：`bench/corpus_v3/`（5072 manifest，数据 20G gitignored 可重取）+ `work_v3/` 构建状态库；expand 层报告 `corpus-expand-qc-2026-09-16/QC.md`、文献 `docs/research/corpus/2026-09-16-expand-layer.md`。
- 基线对照系：`base-v3-full-2026-09-16/`（5059×2 引擎裸编 71.3%）、`parse-v3-full-2026-09-16/`、`e2e-real-n100{,-postcutover}`（**真 token 产物**）。
- 修复证据包：`repro-{0806,0806-head,0806-textfix,2203,2501}` 已入库；`repro-1306`/`repro-2410b`/`realarm-repro`/`postfix`/`modec-misschar` 未入库或在飞（见 §4）。
- 网关/运维：`scripts/gwcap/`、`gw-tunnel.sh`、`gw-health.sh`、`find-gateway-hog.sh`、`preflight_batch.py`、`runbook_loop.md`、`tools-runbook.md`；`docs/research/gateway/2026-09-16-free-tokens.md`（免费额度全景：保险库 80→2 存活）。

## 4. 在飞清单（20:2x 本地 `ps` 实锤复核——清理前必须等/确认）

| 在飞项 | 进程/产物 | 依赖面 |
| --- | --- | --- |
| ~~loop2 delta rerun~~ **已收官** | records 落库 `e769ebb`（targeted rerun 21/22 named-cluster cells → pdf）；run_meta/REPORT 增量已入库 | `stagerun-loop1` 不再是活写面；但 work/ 转挂 fixer-slots preserve-list + tickets repro_path 决策（见下） |
| ~~postfix 真网关 A/B~~ **已跑完** | records.jsonl 满 100/100，进程已退出 | `postfix-2026-09-16/` 待 1e 落库 commit；之后 `work_e2ereal/` 转 A 类可删（`_xlat_state` 25M 保留） |
| **fixer-slots preserve-list（当前唯一阻塞项）** | 20:21 实测 bwrap+xelatex 正在 `work_e2emock/corpus_v3/pipe-xel/1206.0197` 复验（CandFtransformFinalDouble.tex）——fixer 真在用 | `work_e2emock` + `stagerun-loop1/work/` 挂同一张名单（1d 在催；#147 取证用的就是 loop1 cell 树）。兜底口径：名单不到则只留报告里出现过的 cell id 子目录 |
| 1d fixer 波 | `latex209.py`、`test_latex209.py`、`test_inject_cjk_math.py` 未入库；inject.py/normalize.py 等 M 态 | `tmp/latex209-probe/`（57M，RESULTS.md 台账+convert.py 草稿）、`tmp/cjkfont/`、`tmp/latex209-verify/` 配套现场 |
| 已收口的在飞项（落库记录） | `repro-1306` `d2d82e8`、`repro-2410b` `cc50507`、`realarm-repro` `253caab`、TEXMFHOME 串链 `6752bb0`、prim-guard `1e0e5c8`、loop2 records `e769ebb` | 同类 untracked 证据包（`postfix`、`gtrap-scout`、`rerun-ids-loop2delta.txt`）照此办理：先入库再判删 |
| 1e 队列 | worker-followup #74/#75/#78、modeb-dirty、share 完成钩 #92；**postfix 结果待落库** | worker.py M 态在飞 |
| peer 待办 | rules.yaml 五项（prim_guard 交替表/char_table/backstop×2/latex209 gate 改路由/.rtx 边界/install_file 闭包） | status doc §5 分工表 |
| 1d 补充红线 | tmp 清理一律按 mtime 过滤，~2h 内动过的跳过；仓外 `/tmp/loop1-snap/`（1d rundiff 基线快照）、`/tmp/cmrepro`（1e bug-G 复核脚本）备忘勿删 | tickets.jsonl 455 条 `repro_path→work/` 树：删 work/ 前须在报告里标注 repro_path 已失效（或保 tickets 引用语义） |

## 5. 可删/不可删判定（汇总 `artifact-map.md` + `docs-inventory.md` 交叉；清理动作请等 §4 落地）

**文档引用对账结论（`docs-inventory.md`）**：docs/ 90 篇共点名 **60 个 results 目录（40 EXACT + 20 STEM）+ 23 个散文件 + 7 个 work_ 目录 + corpus 全层 + fixtures 全部 + tmp/exp 20 余子目录 + tmp/refs 8 clone——全部在盘、零缺引**（仅 4 个仓外 `/tmp/` 易失件 + 1 个规划即未产出的 oracle/report.json，全部可解释）。ORPHAN 侧（文档从未点名）：results 目录 55 个 + 散文件 43 个 + work_ 11 个 + tmp/ ~33 项。注意 ORPHAN ≠ 可删：55 个 results ORPHAN 基本已入库且体量小（总收益 <150M），删它们无意义；真正的大头全在 work_*/tars/tmp 数据面。其中 8 库横评单体报告簇（plastex/texsoup/tree-sitter/unified/latex-utensils/ieeA/latexjs/latexml 等 43 散文件里的多数）是被引的 `00-grand-comparison.md` 的原始证据——保守保留，若要删先在 docs/01、04 加注「原始单体报告已删、汇总保留」。

### A. 立即可删（无在飞依赖，证据已入库/可再生）≈ 63G

- `bench/work_base_v3full/` 17G（**已删 19:2x**，磁盘 16G→29G 空闲）、`work_sabotage_v3` 5.2G、`work_e2emock` 2.2G（**名单已到（09-17 fixer-slots 终报）：全目录零引用可删——唯一保留格 = 1e 指定的 `corpus_v3/pipe-xel/1206.0197` 与 `corpus_v3/pipeB-xel/2410.17957` 两 cell 子目录**）、`work_fixloop*` 全家 ~4.6G、`work_compile*` 全家 ~2.0G、`work_sabotage_{mock,probe}` ~0.8G
- `bench/work_v3/tars/`+`staging/` ~27.5G（IA chunk 整包缓存；**留 `chunks.json`/`features/`/`expand/`/`frame_lookup.tsv.gz` 等小件 ~30M**——成员级回取不依赖整包，但删 tars = 放弃旧池 56 chunk 本地再扫能力，若后续要加抽同 chunk 需重下 26G）
- `tmp/exp/` 除散装脚本外 ~1.6G（corpus-cbh 是硬链接幻象，删只省 0.6M；`src-snapshot-*`/`cbv3-base`/`escape_probe.py`/`run_*.py`/`s3*.py` 是复跑咽喉小件建议留）；`tmp/` 其余冒烟数据 ~0.5G
- `bench/py/.venv_babeldoc` 664M（失效 venv）、`dist/` 21M、`web/dist` 8.9M、`web/scripts/node_modules`+shots ~13M、（可选）`web/node_modules` 295M、`bench/ts/node_modules` 70M
- `docs/research/lit/` 文献原件（可再生）、`tmp/refs/` 538M 参考 clone（可再拉，标保守）

### B. 在飞勿动 ≈ 46G+（等 §4 收官）

- **`stagerun-loop1-2026-09-16/`（44G，work/ 独占）**：loop2 已收官（`e769ebb`），不再是活写面——**(a) preserve-list 已到（09-17 fixer-slots 终报）：只保 11 格的 `src/` 子树**——`1012.1321`、`1206.1808`、`2003.10959`、`2105.03900`、`math--0307301`（bug-B 复验）+ `0707.1320`、`hep-ph--0605151`、`2105.00037`、`1306.2067`、`0806.3104`、`0905.2120`（slots 复验），其余可删；**(b)** tickets.jsonl 455 条 `repro_path` 指向 work/ 树，删前须在报告标注已失效或只保名单内 cell。解锁后按「结论留、现场销」可释放 ~44G。
- `postfix-2026-09-16/`（100/100 已跑完，待 1e 落库）+ `work_e2ereal/` 1.6G（落库后转 A 类；**`_xlat_state/` 25M 永留**——真网关翻译缓存+断点续跑+qualbench 抽样源）。
- `tmp/latex209-probe`/`cjkfont`/`latex209-verify`（latex209 交付前需引用）、`work_e2emock`（等 slots 名单）。
- 未入库代码交付件（§4 表内 ?? 文件）。

### C. 资产勿删 ≈ 21G

- `bench/corpus_v3/` 20G（5059 篇四层语料，重取需 IA 再跑管线）、`corpus_v2` 255M、`corpus` 114M。
- `work_e2ereal/_xlat_state/` 25M、`e2e-real-*` 系列（真 token）。
- `bench/results/` 全部已入库目录（总收益 <150M，不建议动）。

### D. 再确认（问属主后再动）

- `bench/results/babeldoc/` 9.1M（刻意 gitignore 的对照原件）、`tmp/exp/` 散装 `run_*.py`/`s3*.py`（若未入库=唯一留存，建议先挪 `bench/py/`）、`tmp/stash-recovery-0958/`（事故恢复备份）、`tmp/latex209-probe/`（随 fixer-209up 交付后转可删）、`tmp/web-check/check.mjs`（已扶正 `web/scripts/smoke.mjs`，原件是历史现场）。
- 仓外：`~/.texlate/connections.json`（6 槽含 Prism key）、`~/.agents` 仓确认已 commit、`/tmp/texlate-{clean,verify}-*`、`/tmp/realpostfix.log`（在飞日志）、`~/texmf`（证据态勿动）。

## 6. 本次保全包自身

- `tmp/preclean/` 原始挖掘件：全部七份矿工报告 + `gitlog-full.txt` 已拷入本目录；唯一未拷入的是 `_sess-53215cda-render.md`（317K transcript 渲染稿，可再生）。
- `tmp/transcript-mining/` 10 件（27bd911f 会话一轮挖掘：各会话报告 + docs-audit 44 项 + subagent-bash 语料 + 五份小会话导出）已整体拷入 `transcript-mining/` 子目录——**这是清理 tmp/ 时唯一会真丢的知识载体**。
- 入库状态：本目录 21 件已由 texlate-1d 于 `5cfd678` 落库（19:59）；本文件 §4/§5 的最新在飞状态在其后续补。
