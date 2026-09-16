# 会话保全 53215cda —「项目体验方式」[77d91e] 数据侧 bulk 批跑

- 会话：`53215cda-d3ae-4c05-abf2-ad6cf04844d0`，cwd `~/src/texlate`，10.9MB jsonl，18 个子代理。
- 12:04 从 d69c497a（"体验一下项目"）fork 的后台 bypassPermissions 会话；HANDOFF 所称"项目体验方式"。
- 分工（三方收敛文档 `docs/research/2026-09-16-loop1-status-and-next.md` `b909f01`）：**1d=leader**（latex/e2e/fixloop/bench/tests/横切），**本会话=数据侧+loop 执鞭**（compile/engine.py、xlat/pipeline.py、rules.yaml、语料/批跑），**1e**（server/worker/probe/web）。
- 挖掘时点 2026-09-16 ~19:00 本地，会话仍在运行；transcript 渲染件 `_sess-53215cda-render.md`（同目录，临时）。

## 目标

用户 03:25 两条转向指令的产物化：① 入库走 IA bulk 数据集大批量抽取而非逐篇拉新；② 管线改分阶段批量执行（stagerun：ingest→parse→xlat→compile→fixloop，每阶段扫全集、append 式 records jsonl、按 (id,arm,upstream) resume、论文靠 `work/{id}/` 产物树衔接）。本会话认领：语料扩库 ingest 数据面 + 全部基线测量 + loop1 批跑 + fixloop 规则面修复。

## 时间线（UTC，本地 +8）

- 03:14 写 `docs/research/product/2026-09-16-batch-hardening-design.md`（v2 分阶段批量设计）。
- 03:34–04:07 SSH 隧道掉线→改 tailscale 直连 `http://100.105.212.52:3003`；通知全部 6 个 CC 会话；CGNAT http 放行落 `70dab0f`/`1bb213d`（settings.py:62 `_TAILNET_V4`，tests/test_base_url_tailnet.py 边界用例）。
- 04:31 spawn `corpus-expand`：IA 扩库 +~3740 → 总 5000。
- 05:22 一波放 8 个 agent（abase-compile / aparse-1259 / asabotage-run / asabotage-adapter / areplay-baseline / acorpus-qc / arunbook / asig-miner）+ allm-hook + acompile-sandbox。
- 05:24 `e9bba9c` 扩库管线入库（build_corpus_expand.py + manifest_expand.jsonl 3800 行 + corpus_v3/.gitignore 白名单放行）。
- 05:36 loop1 链点火（bg `bdwfpc23s`）：ingest/parse/xlat-mock 全 5059 → xlat-real n=50 → compile zh → fixloop。
- 06:28 base-v3-full 首批 1259 交付；07:59 expand 增量并入 → 全量 5059/9968 cases。
- 06:33 sabotage 基线交付（escaped 真值 1 例）。
- 07:46–08:11 loop1 compile zh + fixloop（--on fail 647 / --on misschar 663）落 records。
- 09:39–09:49 定点 rerun 19 格两轮（early_eof 簇 13/13 救回）。
- 09:54 `5acb956` loop1 records 层入库（work/ 44G 由 run 内 .gitignore 排除）。
- 10:22/10:27 loop2 全量 rerun 两次点火（`b9ujhngzu`/`bw8czngot`）。
- 10:44 发现 `--layers` 默认 core——loop2 首轮只覆盖 227 格（104 fail + 123 misschar），非全 1310。
- 10:45 生成 `rerun-ids-loop2delta.txt`（fail/misschar 全集 minus 已跑 227）并起 delta rerun——**清理时点仍在跑**（fail 池 xelatex 活跃编译中，misschar 池 `&&` 链后排队）。

## 交付台账（本会话与其 agent）

| 交付 | 落点 | 状态 |
| --- | --- | --- |
| 扩库管线 plan/scan/extract/qc | `bench/py/build_corpus_expand.py` + `bench/corpus_v3/manifest_expand.jsonl`（3800 行，白名单入库） | `e9bba9c` 已入库；QC 全过（0 重复、sha256 全过、39/40 cell 命中，`a_pre2007|astro-ph` +60 冒烟残留属良性超收），报告 `bench/results/corpus-expand-qc-2026-09-16/QC.md` |
| 语料物化 | `bench/corpus_v3/{id}/{raw.*,meta.json,extracted/}` 总 5072 行 manifest / 5059 物化 | 在盘 gitignored；expand 层即插即用进 stagerun |
| base 编译基线（源健康对照） | `bench/results/base-v3-full-2026-09-16/`（sample/cases/cells/summary/REPORT/SUMMARY/run_meta/run.log） | **已入库（tracked）**；5059 papers × 2 引擎 9968 cases 0 crash；联合 pdf 71.3%、双死 28.7%、revtex 一族 ~1300 格 = xel FAIL 42% 最大可修簇 |
| sabotage 逃逸基线 | `bench/results/mock-sabotage-v3-2026-09-16/`（12 文件 + v3/ 子目录） | **已入库**；corpus39 0 逃逸 PASS、corpus_v3 n=180 真逃逸 1 例（1012.5411 fabricate-into-comment → L0 `mask_comments` 洞，HEAD 已堵）；harness `_seg_of` CRLF 归一已修 |
| parse 基线 | `bench/results/parse-v3-full-2026-09-16/`（files.jsonl resume 式） | v2 100% identity / 0.042% leak，干净 |
| replay 门基线 | fixloop_bench 40/40 replay 0 回归，shim 扩列救回 7 | 已交付 |
| stagerun loop1 批 | `bench/results/stagerun-loop1-2026-09-16/` records 五件 + cases 1925 + tickets 455 + metrics + report + REPORT-fixloop-analysis | records 层 `5acb956`+`64bd7f7` 已入库；**在飞 rerun 正 append 改 fixloop.jsonl（git M 态累积中）** |
| fixloop 规则/引擎修复 | rules.yaml plea 路由 `18ff106`、prim-guard lookbehind+spotcolor→xespotcolor `88d0ab9`、shim_map+17 `622fc04`、early_eof `efa1fa3`、taxonomy derive `5d195c2`、buf_size=8M `26b760e` | 均已入库 |
| llm_hook 实装 | `src/texlate/compile/fixloop/llm.py`（LlmFixer/make_llm_hook/Patch，Translator 协议注入缝，BoundedSemaphore(4) 对 swe-2-medium 硬闸）+ tests 23 例 | 已落盘；stagerun fixloop 未接 llm_hook（rules-only 基线，有意如此） |
| compile 沙箱 | engine.py：xelatex `-no-shell-escape` + tectonic `--untrusted` + bwrap（unshare pid/ipc/uts/net、$HOME 影子白名单、texmf ro 挂载）+ env 白名单（TEXMF*/openin_any=p/shell_escape=f）+ `CompRes.sandbox_mode` + `TEXLATE_NO_BWRAP` | 已落；tests 11/11 |
| runbook + 批前闸 | `bench/py/runbook_loop.md`、`scripts/gw-health.sh`（gwcap/direct/tunnel 三探，`GW_HEALTH_SKIP_TUNNEL=1` 旁路）、`bench/py/preflight_batch.py`（import walk+mock 链+磁盘门+网关认证） | 已落盘 |
| 签名挖掘 | `docs/research/product/2026-09-16-signature-mining.md`（top5 未覆盖签名→修复面映射） | 已入库 |
| 收敛文档 | `docs/research/2026-09-16-loop1-status-and-next.md`（1d 主笔 `b909f01`，本会话对稿同步） | 已入库 |

## 产物引用表（三个重产物逐项）

### `bench/work_v3/`（28G，其中 `tars/` 26G / 56 个 chunk tar）

- 来源：`build_corpus_v3.py`（WORK=bench/work_v3，TARS=tars/）为 corpus_v3 core/booster/hot 层下载的 IA chunk 整包缓存；`chunks.json` 56 条全 `state:done`+sha256 核验，`download_progress.jsonl` 168 行全 done。
- 抽取完成度：四层 manifest（core 1000 + booster 200 + hot 72 + expand 3800 = 5072 行 / 5059 物化）全部抽完并 QC 过；expand 的 1172 篇"旧池"就是从这 56 个本地 tar 直读的（`build_corpus_expand.py:589 fetch_blob`：item 命中 old_tars 走本地，否则 Range-GET）。
- 还会不会从 tars 补抽：**管线已演示无 tar 路径**——expand 新池 2628 篇全走 `{tar_url}+Range` 成员级回取，扫完即删整包（磁盘峰值 <2G）。tars 删除的唯一代价：旧池 56 chunk 的成员再取/再扫需重新下载整包（~26G）；成员级单抽不受影响（manifest 有 item/member/blob_sha256/bytes）。
- 同目录小件（建议保留，共 ~30M）：`chunks.json`、`download_progress.jsonl`、`features/`（20M 成员扫描特征，重选样不必重扫包）、`expand/`（9.1M：expand_plan/members/features/qc.md）、`frame_lookup.tsv.gz`、`booster_pool.json`、`hot/`、fetch 日志。

### `bench/results/stagerun-loop1-2026-09-16/`（44G，其中 `work/` 独占 44G / 5059 格）

- run 根（已入库，`5acb956`+`64bd7f7`）：`records/{ingest,parse,xlat,compile,fixloop}.jsonl`（5072/5059/5109/5187/1942 行）、`cases.jsonl` 1925、`tickets.jsonl` 455、`metrics.json`、`report.md`、`REPORT-fixloop-analysis.md`（含补记 2/3/4）、`rerun-ids.txt`（19 格）、`run_meta.json`（15 条 invocation 全账）、`.gitignore`（内容 `work/`）。
- `rerun-ids-loop2delta.txt`（**未入库**，在飞）：`--on fail/misschar` 全集 minus 首轮已跑 227 格的 delta 清单（首行注释 + ~1083 ids CSV）。
- `work/{id}/` 每格内容（0707.0005 实测）：`src/`（ingest 从 corpus_v3/{id}/extracted copytree）、`parse.json`、`xlat-mock.jsonl`、`xlat-state/{arm}/state.json`（xlat resume 态）、`zh/`（译文树，**.xlat-arm.json 记 provenance，臂间共享就地覆写**）、`splice/`（拼接后源 + 编译产物 main.pdf/.log/.fls + **fixloop 就地修复面**）。全树 61519 个 pdf（含 src 内图档）。
- 删除后果：① **当前在飞 delta rerun 正在写 work/**（PID 429166/429194 + 活 xelatex），删=杀跑；② tickets.jsonl 455 条的 `repro_path=work/{id}/` 全部失锚；③ 重建路径存在但贵：`stagerun ingest`（免费，corpus_v3 在盘）→`parse`（CPU 小时级）→`xlat --arm mock`（免费）→`compile`（小时级）→`fixloop`；**xlat-real n=50 的 zh/ 覆写态不可免费重建**（LLM 抽样，seed42 可选同 id 但要花 token）；fixloop 修复后的 splice/ 末态是 rerun/审计的真值面。
- 结论：**rerun 落地前不可动**；落地后若要回收，先确认 tickets/repro 策略（records 已含 signature/verdict，work 是逐案取证层）。

### `bench/work_base_v3full/`（17G）与 `bench/work_sabotage_v3/`（5.2G）+ `work_sabotage_mock/`（694M）

- base：compilebench_v3 全集裸编工作区（每格 paper×engine 构建目录）；results 全件已入库（35M，含 cases.jsonl 逐格 signature）。工作区价值 = 逐格完整 .log/中间文件的深取证层；重建 = 镜像树 `tmp/exp/cbv3-base` + 快照 `tmp/exp/src-snapshot-base` 重跑（~2h 全量）。**注意口径**：快照早于 bwrap（env 白名单），与 v3/v4 历史同口径——删了重跑会得到 bwrap 口径不同基线。
- sabotage：emb Mode B/C 臂编译产物；真值已全部提成 `recount39.jsonl`/`v3/recount.jsonl`（逃逸逐案含 src/zh 快照），复现器 `tmp/exp/escape_probe.py --v3 1012.5411` 走活 src 不依赖工作区。可删性高于 base 工作区。
- 同族还有 `tmp/exp/` 下 driver/snapshot/recount/probe 脚本（gitignored 小件，复跑链咽喉，删前归档清单见上表）。

### 其它在飞/未入库产物

- `bench/results/postfix-2026-09-16/`（296K 增长中）：e2e_real_bench `--tag postfix --base onfail --fixloop onfail` n≈96 真 LLM 后修验证批，17:55 起 PID 38737/38740，写 records/results/matrix/summary。
- `bench/results/repro-*-2026-09-16/`（0806/1306/2203/2410b/2501 等，几十 K–1.4M）：逐案证据包，其中 repro-1306/repro-2410b/repro-2501 **未入库**（git ??），1e 的规则缺口证据 `repro-2501/README.md` + modec-misschar 报告被本会话引用排期。
- `bench/results/stagerun-smoke-2026-09-16/`：stagerun 冒烟产物（小）。

## 不可删信号（红旗清单）

1. `stagerun-loop1-2026-09-16/work/` — **在飞写入中**，且是 455 张 ticket 的 repro_path 基底。删前必须等 PID 429166 退出 + 确认 misschar 池链也跑完。
2. `records/fixloop.jsonl` 等 tracked 文件正被 rerun append——清理后应再 commit 一轮把 loop2 终态落库（当前 git M 态 + `rerun-ids-loop2delta.txt` 未跟踪）。
3. `bench/work_v3/tars` 删除 = 放弃旧池 56 chunk 的本地免下载再扫能力；成员级回取不受影响。若 gate 批（10000 规模档，设计稿 §7）还要从同 chunk 加抽，留；否则可删。
4. `tmp/exp/{src-snapshot-base,cbv3-base,src-snapshot-sabotage,escape_probe.py,sabotage_recount.py,run_sabotage_v3.py,run_parsebench_snap.py,corpus-cbh}` 是 base/sabotage/parse 三基线的复跑咽喉，体量小建议留。
5. `~/texmf` 被 fixloop ctan 装包污染（youngtab.sty 等）——跨跑污染 base 对照线的实证记录（1306.1931 fail→clean 假象），清理时**不要**顺手"修复"用户 texmf，那是证据态。

## 决策教训

- **`--layers` 默认 core**：loop2 首轮静默只跑子集（227/1310），靠 delta 清单补救——批跑命令必须显式 `--layers core,booster,hot,expand`。
- **zh/ 单槽共享演化树**：xlat 臂就地覆写（real 臂把 48 个 id 的 mock 译文盖掉 → 这些 id 永无 mock compile 对照）；臂序约束：compile-mock 必先、sabotage 臂殿后，严格隔离需独立 --tag 目录。
- **records append=resume**：终态格不会自动重试，`--rerun --ids` 定点是唯一重归类路径；run_meta.json 记全 invocation 是溯源关键。
- **跨段退化须直编复验**：partial→fail 17 格复验后真退化仅 4（13 格是 pre-`6b23435` 引擎基建杀伤）；TEXMFHOME 不对称（ambient vs fixloop 冷 env）遮蔽 ~/texmf 包是主要假象源。
- **台账口径**：emb `_seg_of` CRLF 失配使 escaped 漏报——门槛数字必须事件无关口径重算（recount 已立例）。
- **swe-2-medium 硬闸 4**：llm_hook BoundedSemaphore(4)、stagerun xlat `--sem 4`、preflight 网关认证全是围绕 gwcap limit=4 的设计。
- FORCE_COLOR 污染 CliRunner→`env -u FORCE_COLOR uv run pytest`。

## 在飞事项（清理时点快照）

1. **loop2 delta rerun**：fail 池 ~400 ids 编译中（19:00 仍在跑），misschar 池 `&&` 排队；落完需 rundiff vs loop1 + 更新 REPORT + commit records。
2. **postfix 真翻批**：e2e_real_bench n≈96 tag=postfix，验证规则修复在真 LLM 臂的效果（~12h budget）。
3. **TEXMFHOME 串链裁决**：1d 请本会话保持 `_env` 签名稳定、内部改读 ambient TEXMFHOME/$HOME（engine.py 面）；.rtx 翻译集边界待定。
4. **1e 路来两条 rules.yaml 缺口**（Undefined control sequence payload 等）待排期。
5. 译文腐蚀超簇 407 格（`\vskip3这是译文` illegal_unit 138 / csname 粘连 undefined_cs 104）= 非文本槽位被翻，归 segmenter/fixer-slots 面，不在本侧。
