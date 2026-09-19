# 任务：texlate Zotero 插件开发（verifier 先行，再开发）

你是本任务 leader 兼主开发者，工作目录 `/home/fanghaotian/src/texlate`（uv 管理的 Python 3.12 项目：arXiv LaTeX→LLM 翻译→重编译中文 PDF）。交付物：仓内 `zotero/` 完整 Zotero 插件 + `zotero/dev/` 可复用验证工具链。**必须用 ≥18 个 subagent 并行推进**；teammate 纪律：禁一切 git 命令、文件级归属、交付落盘即 TaskStop 关代理；commit 由你统一做（在飞期间 `--no-verify`，本仓格式化链有 stash 竞态）。

## 必读（按序）

1. `docs/research/packaging-2026-09-19/zotero-design.md`——**设计规格，实施按此执行**（产品形态、MVP 切片、架构、坑清单、验证方案 §六）
2. `docs/research/packaging-2026-09-19/pdf2zh-read.md`、`pdf-translate-read.md`——对照插件源码深读（可抄模式清单）
3. `tmp/refs/` 四个 clone：`zotero-plugin-template`（起手骨架，MIT 可用）、`zotero-pdf2zh`、`zotero-plugin-hjfy`、`zotero-pdf-translate`——**三个对照全 AGPL-3.0，只抄模式、零代码搬运**

## 环境硬事实（已实测，勿重复验证）

- `/usr/bin/zotero` = Zotero 140.10.0esr（Zotero 10 线）；无 DISPLAY，有 `xvfb-run`
- 本机 Zotero 库是用户真库——**只许用独立 dev profile**：`zotero --profile <path>`（注意 `--profile` 接路径，`-P` 是 profile 名）
- mock 服务：`TEXLATE_TRANSLATOR=mock TEXLATE_DATA_DIR=<repo>/tmp/zotero-dev/texlate-data uv run texlate web`——确定性假翻译零 token、产出真 zh.pdf；不配 key 不设 mock → 任务落 `needs_auth` 态
- **scratch 一律 `tmp/`（gitignored），严禁 `/tmp`**——usrquota tmpfs 写爆 Bash 全灭
- API：`POST /api/arxiv/{id}/translate`（body `{}`）、`GET /api/task/{id}`（11 态机：queued/fetching/parsing/translating/compiling → done/partial/fault/cancelled/interrupted/needs_auth）、`GET /api/files/{id}`、`GET /api/files/{id}/{kind}`、reader `http://{server}/#/reader/{taskId}`、远程实例 `X-Texlate-Key` 头
- 插件沙箱**无 EventSource/ReadableStream/AbortController**——只能 setTimeout 轮询

## 阶段 A：先把 verifier 造出来（全绿才准开 B）

目标：一条命令回答「插件在真 Zotero 里端到端工作吗」。交付 `zotero/dev/` 工具集：

- `dev-server`：起 mock server（env+data dir 隔离）→ 等 `/api/health` 200 → curl 走通 建任务→轮询→files→下载 zh.pdf，逐步断言
- `dev-profile`：建 `tmp/zotero-dev/profile` + 夹具（魔法棒导入 2–3 个 arXiv 条目，含一个老格式 id 若支持）
- `dev-zotero`：`xvfb-run zotero --profile <profile>` 拉起 + 插件装载（scaffold serve 或手动装 xpi，选更稳的）
- `rdp`：最小 devtools 客户端——在 main window context evaluate 任意 JS 拿返回值（`--start-debugger-server 6100` RDP，或 `--remote-debugging-port` Marionette chrome-context executeScript）。**这是验证链咽喉，先证明打通再往下**；退路：插件读 pref 开关起跑自测 + `Zotero.debug`→stdout 捕获，RDP 不通就用它
- `selftest`：插件埋 `Zotero.texlate.selftest(itemId)`——跑 探测→建任务→轮询→挂附件→读 Extra 标记→拼 reader URL 全链，返回结构化结果对象
- `dev-verify`：一串到底输出逐项 PASS/FAIL + 失败归因

**每条反馈通道满足三性质**（写进工具头注释 + `zotero/dev/README.md`，并作为你验收每个 subagent 交付的自检标准）：

1. 局部可归因：断言失败绑到具体参数/代码路径/输入条件（例：「attach 断言失败：getAttachments() 未含 texlate_*.pdf——临时文件名未 ASCII 化」），不许只报「e2e 挂了」「指标掉了」
2. 廉价及时：单步断言用最小探针（health、task 快照、files 清单），30 秒 micro 能答的不跑 20 分钟 e2e；全链只作终验
3. 客观可验证：比对数值/字段/字节（sha256、PDF magic、附件计数差、状态枚举），不凭日志文本目测；相关不等于因果，结论要有受控对照

**每件工具按 optimization skeleton 四字段留档**（`zotero/dev/README.md`）：适用条件（什么输入形状/平台/约束下成立）、变换方法（具体怎么做）、资源约束（牺牲什么换什么，如 dev profile 隔离换可重复干净态）、验证证据（当时怎么测、输出什么样——让下一个人复核而非盲信）。

A 完成判据：`dev-verify` 全绿；且人为破坏任一环节（杀 server、错 port、删附件）时报告给出可归因 FAIL 而非笼统错误。

## 阶段 B：插件开发

`zotero/` 用 windingwind 模板起骨架；模块 `menu/client/poller/attach/prefs/arxivId`；Apache-2.0；manifest strict_min `7.0.*` / max `10.*`。MVP 切片逐项照设计文档 §二实现，**每落地一项即过对应 selftest 断言**，不许攒到最后统验。明确不做（§四清单）：LLM 配置表、多 server 槽位、非 arXiv 条目、reader 注入、自造任务队列。

## 分工建议（≥18，按实际收敛）

侦察复读 ×2（模板+scaffold 文档）、A 工具 ×6–8、模块实现 ×6、locale/manifest/打包 ×2、对抗 review ×3（每模块做完派一个挑刺）、文档 ×1。中途有发现/卡住/变向随时通气。最终交付：`zotero/` 源码、`zotero/dev/` 工具链、skeleton 留档、验证报告（PASS 矩阵 + 每断言归因样本 + `zotero-plugin build` 出的 xpi）。
