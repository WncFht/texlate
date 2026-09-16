# 清理前知识保全 — 中号会话批次（9 个）

挖掘时间 2026-09-16。全部会话 cwd=`~/src/texlate`。磁盘级不可删信号集中在 **`tmp/`（整目录 gitignored）**：`tmp/transcript-mining/`（27bd911f 的 10 份挖掘报告）、`tmp/exp/`、`tmp/web-check/check.mjs`（已被扶正为 `web/scripts/smoke.mjs`，但原件是历史现场）。入库交付物均已核实 `git ls-files` 在册、相关 commit 存在。

---

## 31ba05f0 — "项目多少代码"（0.3MB，01:46–01:49）

- **目标**：统计全项目代码量。
- **干了什么**：git 跟踪文件 + cloc 统计，剥离生成数据。
- **交付物/结论**：手写代码合计 ~81k 行——`src/texlate/` ~29.7k、`tests/` ~11.5k、`web/` ~4.0k、`bench/` 工具与管线 ~22.2k、`docs/` ~13.6k；另有 ~3.4k 未提交新代码。按语言 cloc code：Python 44.4k / Markdown 42.9k / TS 2.8k / JS 2.6k / YAML 1.2k。入库 `bench/results/*/papers.json` 等评测快照 ~158 万行 JSON 不算开发量。**口径后来被固化成 `scripts/loc.sh`**（27bd911f 沉淀，已入库）。
- **有价值知识**：「手写 ~81k vs 数据快照 174 万」的剔数据口径本身（loc.sh 即其脚本化）。

## f05b39dc — "谁在疯狂打 swe-2-medium，降并发"（2.0MB，02:12–03:49）

- **目标**：找出打爆 swe-2-medium 的会话并降并发；随后加本机硬闸使聚合并发 ≤4。
- **干了什么**：定位到 `texlate-1d` 的 `an100-postcutover` 子任务 `e2e_real_bench.py --n 100 --concurrency 10` 直连 tailscale（PID 1847937，常驻 8 条在途连接，57min 47/100）；跨会话消息让其重启到 `--concurrency 4`（脚本并发启动时定死，results.json 逐篇落盘 + `_paper_done` 断点续跑使重启零损失）。随后建本机硬闸。
- **交付物**：`scripts/gwcap/` 六件（已入库）：`gw-cap-proxy.py`（stdlib 代理，:3399 监听 127.0.0.1+::1，body `model` 命中 `swe-2-medium*` 过 `threading.Semaphore(4)`，其余透传）、`gw-cap-proxy.service`+`gw-cap-redirect.service`（systemd 双单元 enable，redirect `BindsTo` 代理 fail-open）、`install.sh`（install/uninstall/status）、`ensure-bypass.sh`、`tailscaled-gwcap.conf`。机制：nftables `inet gwcap` output 链 REDIRECT 本机出向 tcp/3003→:3399，代理自身按 `meta skuid != 958`（gwcap user）豁免。健康端点 `127.0.0.1:3399/__gwcap/healthz`。
- **事故与根因**：部署中途 nft 中间态造成全局 ConnectionRefused——代理回包 unNAT 后以网关 tailscale IP 为源走 `lo`，被 tailscaled `ts-input` 反欺骗规则丢；修复=`ip filter INPUT` 的 ts-input 跳板前插 `iifname "lo" tcp sport 3003 accept`。
- **未入库知识（值得保留）**：nftables 三坑——①base-chain `accept` 是链局部的，不终止同 hook 其它 base chain；②`srcnat` priority 只在 postrouting 合法，output 不行；③tailscale ts-input 丢 `100.64.0.0/10 iifname != "tailscale*"`。验证法：healthz 在真实流量下 `inflight:4`、8 路压测见 `queued:7`。
- **并发约定（已广播）**：archbox 本机 swe-2-medium 聚合硬闸 4；`e2e_real_bench`/`stagerun xlat` 等一律 `--concurrency/--sem 4`。

## 15803cd2 — "AGENTS.md 偏好节排序重构"（0.9MB，08:25–09:26）

- **目标**：`~/.agents/AGENTS.md` 偏好节 19 条 bullet 分组排序，保留原文；随后全文标点格式化；同步到 fht-mba。
- **干了什么**：19 条分 4 个 `###` 节（多代理协作 6 / 调研与验证 6 / MVP 与演进 4 / 过程与环境 3），条目逐字保留。全文标点统一（半角→全角、枚举顿号、句末补。）、commit 模板收进 fenced block、`## browser`→`## Browser`。跑了仓库 format 链（markdownlint+autocorrect+prettier）验证全绿。scp 同步 fht-mba，两端 sha256 `632297c8…` 一致。
- **交付物**：`~/.agents/AGENTS.md`（本机文件，非仓内；两端 `~/.agents` git 仓库当时同停 `6b720dd`，改动当时未 commit——**注意确认 `~/.agents` 仓后续是否已提交，否则清理时别丢**）。fht-mba 侧 `~/.claude`/`~/.codex`/`~/.kimi-code`/`~/AGENTS.md` 软链已存在直接生效。
- **价值**：这份文件就是当前全局 CLAUDE.md 的源头——多代理协作/调研/MVP/过程四节结构诞生于此会话。

## a0ff44ab — "claude code 暂停/断网续跑 best practice 调研"（3.5MB，07:07–07:21）

- **目标**：调研 Claude Code 中途暂停、断网后恢复的最佳实践（1 个 claude-code-guide 子代理核对官方文档）。
- **交付物**：纯结论，未写文件（曾提议塞进 `docs/tools-runbook.md` §5，会话结束时未落地——**tools-runbook.md 里没有这一节，属未入库知识**）。
- **结论（保全如下，防止丢失）**：
  - 核心：transcript 逐条 append 落盘 `~/.claude/projects/<proj>/<sid>.jsonl`，任何时候中断都不丢上下文；技巧全在恢复侧。
  - 暂停：`Esc` 取消当前 turn（本地操作）；`Ctrl+Z`+`fg` 挂起进程；断网/合盖什么都不用做。**坑：主线程空闲时 `Ctrl+C` 会无确认杀掉全部后台 subagent**（issue #87140）；专杀后台 agent 用 `Ctrl+X Ctrl+K`（3s 内两次）。
  - 断网：API 指数退避 ~10 次，耗尽后 turn 报错但会话不关；流式断一半标 "may be incomplete"，回 `continue` 续走。
  - 恢复：`claude -c`（当前目录最近会话）；`-r` picker（Space 预览/`/` 搜索/Ctrl+A 全机/Ctrl+R 改名）；`-r <名字>`（`claude -n`/plan 接受自动命名）；v2.1.223 起 `-r <id>` 全机搜；`-r <jsonl路径>` 直接恢复。**别两终端同开一会话**（交错写同一 transcript），分叉用 `--fork-session`。
  - 恢复后不回：在途 tool call、后台 bash、`--mcp-config/--settings/--add-dir` flag、会话内权限授权。**权限模式坑**：`-c`/`-r <id>` 恢复原模式，picker/`/resume` 用当前默认（plan-mode 会话从 picker 恢复会掉出 plan mode）；bypass 永不恢复。
  - 时效：prompt cache ~1h 过期，恢复后首请求重算全部历史；>100k tokens 且闲置 >1h 弹 "Resume from summary" 选择；transcript 默认保留 30 天（`cleanupPeriodDays` 可调）。
  - 工作流建议：跨时段任务先 `claude -n <name>` 命名；离开前写 handoff 文件（本仓 `docs/HANDOFF-*.md` 惯例）；远程干活在远端 `tmux new -A -s claude`（SSH 断了进程归 tmux server）；跨机迁移无官方支持，社区方案 ccsession/claude-sync（拷 jsonl+改写 cwd），**勿整拷 `~/.claude`**（含 `.credentials.json` 活凭据）；编码目录名对含 `-` 路径有损，找回原目录读 jsonl 第一行 `cwd` 字段。

## add0b7ec — "自己找免费 token" + 合并 segmenter 三 bug（2.7MB，07:58–09:02，3 调研子代理）

- **目标**：自主找免费 LLM 额度接入 texlate（只用官方免费档，不碰泄露 key）；中途接收 1e 会话转交的 segmenter 三 bug 修复合并。
- **干了什么**：盘点本机"找 token"基建（`ai-key-manage/bootstrap.json` 保险库 ~80 endpoint、`any-auto-register`（账号库空）、`cliproxyapi`（vendored，支持 antigravity/claude/codex/devin/kimi/vertex/xai 上游）、`ccLoad` :23141、`devin-2api` 本机 :3033+:3973）；批量探活；3 个子代理分头调研 CLI 订阅转 API 生态/国际官方免费/国内官方免费+公益。
- **交付物（入库）**：`docs/research/gateway/2026-09-16-free-tokens.md`（全景档案）；`~/.texlate/connections.json` 写入 6 槽（127.0.0.1:3003/:3033、100.105.212.52:3003、Prism、llm7、pollinations）；memory `free-token-landscape`（已在 MEMORY.md）。
- **免费 token 结论**：主粮=devin-2api `swe-2-medium`（Windsurf promo 免费至 **2026-10-16**，契约 7/8）；Prism `ai.prism.uno`（newapi 系，key 在保险库，gpt-4o-mini 7/8 最快 3.5–8s，23 模型全活，haiku 有掉 `\` 史）；llm7.io 与 Pollinations 匿名档可用但属**机会型**（llm7 下午连发空响应、pollinations 共享预算见底；llm7 真免 key 仅 4 个：GLM-5.3-Flash/minimax-m2.7/codestral/mistral-Nemo）。保险库 80 条 endpoint 只活 2 条（公益站按月腐烂）；GitHub Models、Qwen OAuth、iFlow、Cerebras 免费档全死。自助注册被堵死：活着的公益站全要 gmail/qq/foxmail 白名单或 Turnstile。
- **待用户动手的 ROI 排序**：ModelScope（2000 req/天，须绑阿里云账号，token `ms-` 开头，base `api-inference.modelscope.cn/v1`）＞智谱 GLM-4.7-Flash（永久免费，`open.bigmodel.cn/api/paas/v4`，并发 ~1）＞cliproxyapi 挂 Google 号（一次 OAuth 吃 Antigravity+Gemini CLI 两份）＞SiliconFlow（`tencent/Hunyuan-MT-7B` 专用翻译模型对照臂）/百炼/OpenCode Zen；给 QQ IMAP 授权码可自助注册白名单公益站。archbox 有 RTX 4070 SUPER 12GB，建议 ollama 跑 Qwen3-14B 做永久兜底。
- **segmenter 三 bug 修复**（1e 在 0806.3472 pipe<base 退化归因中发现，本会话合并进在飞版，未自行 commit）：Bug A detokenize 空格——新增 `_cat_surf`（segmenter.py:804 附近），控制词后随字母开头元素补空格，`_grp_surfs`/`_group_surface` 21 处 `out.append` 全走它；Bug B 组内 BOUNDARY_TAIL——env-macro 后插 `BOUNDARY_NAMES` 分支，`\vspace{2mm}` 整调用进 `[[CMD]]`；Bug C 未配对 `$$`——disp 盖第二枚 `$` pos，扫描耗尽时改 `_flush_run`+余下字节 LITERAL，`$\omega$` 不再静默消失。验证：`test_segmenter_unpaired_0806.py` 7/7、全量 pytest 2001、corpus_v3 随机 40 篇 identity 100%。
- **引用路径**：`tmp/exp/rule-validator/`（契约冒烟探针现场，gitignored）、`tmp/exp/gwbench/out_smoke_{3033,prism,llm7}/results.jsonl`、`/tmp/probe_vault_results.json`（探活原始数据，/tmp 易失）。

## d69c497a — "体验项目" + 批量强化管线设计（3.2MB，01:09–04:03，6 精读子代理；12:04 fork 出 53215cda）

- **目标**：体验全项目；用 devin2api key 跑 2602.05933 全流程验证（重点 latex 解析+fixloop）；修网关转发；设计可 scale 的大批量 arXiv 强化管线。
- **干了什么**：起后端 `uv run texlate web` :8765（env `TEXLATE_API_KEY=240127`/`TEXLATE_MODEL=swe-2-medium`）+ 前端 :5173 真 API 模式，走完全流程；顺手修 `worker.py:446 pdf_pages()` 裸字节 regex 找 `/Count N` 对压缩 xref 流永远返回 0 的真 bug（改 pypdf 惰性导入，reader API `pages:0`→正常）；用 `\usepackage{psfig}` 注入验证 fixloop 引擎活着但**当时不在 `_compile_zh` 调用链**（审计 P0 缺口）；6 个子代理精读 worker/compile/fixloop/xlat/corpus/bench 出 file:line 事实清单。
- **交付物（commit 已核）**：`4f4910b` T1 e2e_real_bench 补 ph_map（bench 修复阶梯与产品一致）；`fb84bd3` T5 CaseSink lock+flock；`9145077`+`655ea4e` `docs/research/product/2026-09-16-batch-hardening-design.md` v2（分阶段批量设计稿）。数据目录 `~/.texlate`（tasks/SQLite/产物）。
- **设计稿要点（知识浓缩）**：`stagerun.py` 分阶段批量（ingest→parse→xlat→compile→fixloop 各扫全集，各写 `records/{stage}.jsonl` append 即 resume）；executor 按资源分型（parse=ProcessPool / xlat=asyncio / compile+fixloop=线程池）；臂成 stage 参数（`xlat --arm mock|real|sabotage`、`compile --arm zh|base`）；规模按签名可分辨度 n≈3/p：parse 全集每轮、xlat real 250–300 子集（gwcap sem=4 → ~56 篇/h → 5–7h 隔夜）、fixloop ~600 fail 格+100 clean 幂等格；go/no-go 线（parse leak≤0.05%、契约≥99.9%、sabotage 零逃逸、rescue 单调不降）；工单制 T1–T7/F1–F4/E1–E5，subagent=复现→修→回放三段式，rules.yaml 单写热点归 leader。
- **事实更正**：corpus_v3 manifest 1272 行=1259 实体在盘+13 withdrawn stub（缺口为零，IA 拉取留 stub）；IA 成员级单抽 URL `/{item}.tar/{member}` sha256 对上 manifest，未来扩层走这条。
- **运维事实**：SSH 隧道正确形态 `ssh -N -L 3003:100.105.212.52:3003 fht-mba`（远端 dial tailscale 口；`-L 3003:127.0.0.1:3003` 撞 Mac VS Code `Code H` 黑洞）；tailscaled 重启会带走 ssh 隧道（exit 144）→ 带 `while true`+keepalive 自动重连（后固化为 `scripts/gw-tunnel.sh`）；候选改：`validate_base_url` 放行 `100.64.0.0/10` http 可摆脱隧道（记为工单未动）。
- **服务/端口现场**：:8765 后端、:5173 前端、:3003 隧道——均为临时进程，产物在 `~/.texlate` 与 `bench/results/`。

## 2f162cce — "展示全流程" + hot 层 + pipe-fix 臂（5.1MB，00:11–03:30，5 汇总子代理）

- **目标**：全流程演示；详述所有 bench 及结果；扩 benchmark（用户定调"扩展不删除"，终极目标=全 arXiv 可译）。
- **干了什么**：1412.6980/2105.11479 两篇走 mock+真翻译全链（2105.11479：51/51 chunk ok、tectonic 0.82s clean、xelatex 1.02s）；5 个子代理汇总 B1–B7 全部结果；建 hot 语料层；e2e_real_bench 加 pipe-fix 救回臂；9 篇 hot 联合冒烟。
- **交付物（commit 已核）**：`bench/py/build_hot_layer.py`（OpenAlex `S4306400194`：hot-cite 120 篇 2024+ 按引用降序 + hot-recent 40 篇 2025-06+ 随机；产品 `acquire_source` 钉版取源；首日 85 发预算入库 72 篇 594 tex/671MB，13 pdf_only 跳过）；`manifest_hot.jsonl`+`MANIFEST.md` 热层节+`.gitignore` 白名单；`e2e_real_bench.py` pipe-fix 臂（`--fixloop onfail|always|never`，fixloop 配方 `import fixloop_bench` 单源）；`9c50057` docs/09 §4.3+docs/10 B5 注记+`docs/research/product/2026-09-16-e2e-pipefix-hotlayer.md` 证据文；memory `project-goal-all-arxiv`。
- **关键实证**：fixloop 跑 partial 会回退（halt_on_error 把已有 PDF 弄丢，smoke 2/3 回退）→ `onfail` 只接 `fail`；9 篇冒烟 fixloop 实救 3 篇（含 1893-chunk 巨型综述 fail→partial），union usable 5/9→8/9。
- **B1–B7 汇总数字（保全）**：B1 parsebench v2 终码 1955/1955 identity、leak 0.046%（58/124772 全 dollar 假阳）、flatten 94.5%（orphan=未被 \input 触及的随附 tex）、性能长尾 p50 43ms/p95 428ms/max 8.4s；B2 fixtures 34 断言；B3 compilebench+fixloop 180 抽 172 有效：baseline 70.6% → fixloop 31 规则后 89.5%（xel missing_file 109 格救 84，tec eps_image 45 格救 37），缺口=化石 publisher 文件 vendored stub ~15 格+真 2.09 七篇；B4 xlatbench swe-2-high 契约 100%、swe-2-medium 97–99%（默认）、区分度全在 `cs_dropped`；B5 e2e n100 chunk ok 99.97%、1524 残留修复后复验归零、真管线引入仅 8/91；B6 validbench L0 十类破坏 100% 检出/0 FP/0.374ms；B7 alignbench 18 对有锚 p50=1.000 但 cite.* 锚丢失长尾未过 gate。
- **引用路径**：`bench/results/e2e-hotfix-smoke-2026-09-16/`（已随 `360a810` 入库）；遗留 durable cron 09:30 续取 75 候选——**CronList 已空，已触发或随清理消失**；若 hot 层仍 72/160，需手动续跑 `build_hot_layer.py`。
- **协作事故背景**：texlate-1d 通报 `git stash -u` 误伤多 agent 在途工作（已恢复），本会话起遵守 git 冻结；后确认禁令仅 sprint 范围、单会话 cron 可自 commit。

## 22208ece — "前端改进+可观测性+修 bug /frontend-design"（2.8MB，04:33–05:21，4 子代理）

- **目标**：web 前端整体改进+可观测性+修 bug。
- **分工**：A-impl（api/stores/reader/App/Reader）+ B-impl（components/pages/i18n/mock）+ C-audit（契约只读）+ D-audit（设计/a11y 只读）；文件级归属互不重叠。
- **交付物（commit `da3acf7` 已核，17 文件 +1358/−158 仅 web/）**：修复——chunk 事件 `items[]` 增量 delta 被整帧覆盖致棋盘格回退（新 `mergeChunkItems` 按 seq 累积）；下载全 404（manifest 按 db kind `en_pdf` 索引被当 URL kind `en.pdf` 用→映射 db→url 用 `entry.url`）；阅读器单侧缺失崩溃（`documents.{original,translated}` 可选→veil 占位）；retry 死按钮（`POST /retry` 复用 task_id 返 202→`resetLive` 重订阅；needs_auth 内联 key 带 `X-Texlate-Key`）；pendingJump split→single 丢失；同路由切任务不 remount（taskId keyed）；终态 404 改"任务已清理"面板。可观测性——transport 徽章（live/reconnecting/closed）、阶段时间线、统计条（完成/缓存/失败/tokens/耗时）、自动滚动日志抽屉、warning 列表、任务列表第二行徽章。D-audit 实测对比度落地：`--ochre-deep #7d5f00`（ochre 文本 3.15:1→4.76:1）、`--ink-3` 文本用途降装饰、focus-visible 朱砂环、`prefers-reduced-motion` 兜底、<640px panes 纵排。
- **验证**：tsc 0 错、eslint 净、vitest 25/25、playwright e2e 21/21（`web/scripts/smoke.mjs`）；`scripts/build-web.sh --no-install` 部署 263 产物到 `src/texlate/server/static/`（StaticFiles 按请求读盘无需重启）。
- **留后端跟进（未修）**：glossary 语义错位（UI 收内容字符串、后端要文件路径，功能目前 no-op）；docx/epub 未接线（`_run_doc` 未实现+`KIND_URL` 缺 `zh_docx/zh_epub`，前端 accept 特意不放）；`EVENT_CAP=2000` 可能截断 SSE 回放；local 模式 CSRF origin 检查。
- **引用路径**：`tmp/web-check/check.mjs`（playwright 冒烟原型，gitignored，已扶正 web/scripts/smoke.mjs）。

## 27bd911f — "整理更新所有文档+读所有聊天记录+总结可复用脚本工具"（3.4MB，06:03–07:05，5 挖掘+1 审计子代理）

- **目标**：全仓文档整理更新 + 挖全部会话 transcript 提炼可复用脚本。
- **干了什么**：6 子代理并行（5 挖 transcript+1 文档审计）；等待期间自己盘 scripts/、补 research/README 索引、修 docs/README 计数、更 AGENTS.md 布局节（fixloop 33 规则、corpus_v3 5072 篇）；按报告线索逐个固化脚本；文档审计 44 项逐条核销。
- **挖掘报告（gitignored，清理即丢）**：`tmp/transcript-mining/`——`31ba05f0.md`/`2f162cce.md`/`d69c497a.md`/`22208ece.md`/`f05b39dc.md`/`bb5c429c.md`/`53215cda.md`/`484a9c38.md`+`484a9c38-tools.md`（53 子代理巨型会话，最有价值：stash 事故取证、stagerun 命令面、挂死诊断三件套）+`docs-audit.md`（44 项一致性审计）+`subagent-bash.txt`。**如需保全这些报告，拷出 tmp/ 或入库**。
- **沉淀脚本（全部已入库 `scripts/`+`web/scripts/`）**：`gw-tunnel.sh`（ssh 隧道常驻化 setsid+重连，抗 tailscaled 重启）、`find-gateway-hog.sh`（"谁在打网关"进程→会话归因链）、`gw-health.sh`（已有，网关三探）、`demo.sh`（CLI e2e 冒烟）、`dev-smoke.sh`（vite 起服→log 解析真实端口→mock 鉴别→smoke.mjs→只杀自己 PID）、`server-smoke.sh`（server curl 全链）、`git-stash-export.sh`（stash 事故无损取证 tracked+untracked `^3` 两树导出）、`tcp-relay.py`（30 行 asyncio 转发）、`loc.sh`（剔数据代码量统计）、`web/scripts/smoke.mjs`（21 断言 playwright e2e，texlate-1e 随 `fd3741f` 入库）。
- **手册**：`docs/tools-runbook.md`（已入库）——产品 CLI/scripts/bench/py 评测器全表+运维手法（隧道三坑、nft 调试、xelatex ~100 错截断、ruff --fix F841 删出 bug、`command grep` 反 alias、stash 并发事故定式、zh/ 共享演化树排序、records append 语义）。
- **文档核销**：docs/08（rules 31→33、documentstyle suspect 试编、F3 reject→partial+reject_at、sandbox/probe 注记、`_transcode_aux_bib`）、docs/05 裁决 13 推翻注记、docs/07 perf 数、docs/06 元数据层、docs/09/10 规模与评测器现状；docs/README 73 篇+tools-runbook 行、research/README product/ 4 篇+expand-layer+aux-cjk 标注、corpus_v3/MANIFEST.md、AGENTS.md；audit README 加"午后已收口"注记；HANDOFF §0/§3 快照划销对账；新档 `research/corpus/2026-09-16-expand-layer.md`（3800 扩库+QC+60 良性超收）。
- **新增网关规则（用户当场面谕）**：:3003 只走 tailscale 直连或 `scripts/gw-tunnel.sh` 隧道，**禁 VS Code 端口透传**（自动转发的 :3003 是黑洞，能连不响应）——已写 memory `devin2api-gateway`+runbook §5.1。
- **verify_export.py**：绑死输入路径未扶正，留档于挖掘报告。

---

## 横向提醒

- `tmp/transcript-mining/`（10 文件）与 `tmp/exp/rule-validator/`、`tmp/web-check/` 均在 gitignored tmp/——本批保全文档之外**唯一真正会因磁盘清理丢失的知识载体**；其中 mining 报告是 27bd911f 整场挖掘的一手产物，建议拷入 `docs/research/` 或随 preclean 包带走。
- `~/.texlate/connections.json`（6 槽含 Prism key）与 `~/.agents/AGENTS.md` 在仓库外；`~/.agents` 仓 08:33 时停在 `6b720dd` 未提交当次改动，清理前值得确认已 commit。
- `bench/results/` 属脚本产出目录（不入 lint、脚本重写），其中 `e2e-hotfix-smoke-2026-09-16/` 已入库；`stagerun-loop1-2026-09-16/`、`postfix-2026-09-16/`、`repro-*-2026-09-16/` 在 git status 里为 M/??——属 1d  fleet 产物，非本批会话。
- 本批涉及的 memory 条目均已存在：devin2api-gateway、free-token-landscape、project-goal-all-arxiv、texlate-team-discipline、gfs-stash-race。
