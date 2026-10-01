# docs-health — 文档面健康度侦察（roadmap 输入件）

> **结论**：文档健康侦察：规则计数四处全漂、当日拆包再灭约 10 行号锚点、上手断点七处；三条改进建议。
> **状态**：时点证据（2026-09-17 口径）
> **日期**：2026-09-17（2026-09-20 迁入重编）
>
> 只读侦察产物，供「未来发展计划 + 排期」文档引用。时点 2026-09-17。断言带 `file:line`；行号以当日工作区快照为准。

## 1. 确凿漂移清单（docs/01–10 及入口文档 vs 当前代码）

### 1.1 计数面漂移

`src/texlate/compile/fixloop/rules.yaml` 现为 **70 条规则**（64 loop + 3 gate + 2 precheck）、**48 个 taxonomy 条目**、4 条 warning 类（invalid_utf8/missing_char/missing_graphic/tectonic_degrade）、状态分布 proposed×35/validated×6/verified×4/stub×1。对照面全线滞后：`CLAUDE.md:4` 写「36 规则」（更早版本曾写 67）、`README.md:31` 写「33 规则 + taxonomy 28 类」、`docs/08` §5.1 勘误链末次计数为「46 taxonomy / 62 rules」、`docs/10:79` 勘误写「现 67 条」——同一真实数字在四处各不同，且都错。同类：`README.md:29` 写 `validate/`「L0 规则校验（7 规则）」，实际 `src/texlate/validate/l0.py` 有 12 个 `_check_*` 函数；`README.md:36` 语料行只写「1000 核心 + 200 补强」，实际 `bench/corpus_v3/MANIFEST.md:7` 四层共 5133（+hot 133 +expand 3800，expand 层为 2026-09-16 增补、`docs/09:29` 勘误已记但 README 未跟）。`README.md:26` 写 arxiv「189 tests」，实测约 190 个 test 函数（轻微）。

> **勘误（2026-09-21 补注）**：本节「70 条规则（64 loop + 3 gate + 2 precheck）」拆分自相矛盾（64+3+2=69）且总数亦误——同一真实数字本节自身即第五个错值。按状态分布钉定的快照时点（rules.yaml @ `e078e995`–`969a9868`，2026-09-17 ~16:12–16:44）复核，真实计数为 **68 条 = 64 loop + 2 gate + 2 precheck**：「3 gate」系注释行 `# phase: gate(每轮分类后最先评估)…` 被朴素 grep 误计，真实 gate 规则为 2；48 个 taxonomy 条目与 4 条 warning 无误。另，状态分布（proposed×35/validated×6/verified×4/stub×1）仅覆盖 68 条中携带 `stats.status` 字段的 46 条，余 22 条无 stats 块；taxonomy 条目无 status 字段、不在该分布口径内。

### 1.2 结构面漂移（含当日再漂）

`latex/segmenter.py` 已拆为 `src/texlate/latex/segmenter/` 8 文件包（args/_common/core/env/group/mainloop/pending/`__init__`，工作区 mtime 2026-09-17 12:15–15:13）；`docs/07` §1 勘误（同为今日所加）仍写 `segmenter.py`，属同日再漂移。`server/worker.py` 已拆为 `src/texlate/server/worker/` 11 文件包（mtime ~14:27），`__pycache__` 内残留 `worker.cpython-312.pyc` 佐证拆分为当日事——由此 `docs/08:157`（`worker.py:3046`）、`docs/08:194`（`worker.py::_probe_target`）、`docs/HANDOFF-2026-09-16.md:139-140` 共约 10 处 `worker.py:*` 锚点全部失效。`src/texlate/redlines.py`（redline 注册表）与 `src/texlate/repair.py`（e2e↔worker 共享修复层）已落地——即 `docs/research/refactor-audit-2026-09-17/report.md` 的 ★1/★2 建议实现——但 `CLAUDE.md:8` 的 server/ 模块清单（缺 `upload.py`、worker 仍写单文件）与 `docs/02` §目录结构树均未反映。`docs/02` 目录树整体是旧名集合：`compile/` 写 `fixrules/`（实 `fixloop/`）、`latex/` 只列 4 文件、`validate/` 写 `rules, ts_latex`（实 l0/l1/l2/report/ts/）、无 `export/`、`share.py`、`e2e.py`。`docs/05` §4 架构图出现 `texlate.core` 模块，代码中不存在。`docs/10:48` 写 B2「98 用例」，实测 `tests/test_bench_regression.py` 18 个 test 函数（参数化展开口径可解释，但单位表述易误读）。

### 1.3 命令/配置面漂移

`CLAUDE.md:4` CLI 清单 `fetch/parse/run/web/export/version/tools` 漏 `share`（pack/unpack）与 `doctor`——`src/texlate/cli.py` 实装命令集为 version/fetch/parse/run/web/export/share/tools/doctor。`docs/05` §5.10 写「`texlate <id>` 瘦客户端自动拉服务」，实装为 `texlate run <id> --server URL`（cli.py:295/755），裸 `texlate <id>` 会被 typer 当未知命令拒绝。`README.md:8` 给 `uv tool install 'texlate[server]'`，但 `pyproject.toml` extras 仅有 `server` 一项、包未见发布痕迹，且 `docs/08` §2.2 与 `docs/05` §6 M1 承诺的 `texlate[ts-validator]` extra 至今未建（audit-2026-09-16/docs.md 已标记，未愈）。`bench/PROTOCOL.md:12-17` fixtures 清单 6 项，实际 `bench/fixtures/` 8 件，漏 `escape-outside.tex`、`xlat-traps.tex`。`src/texlate/xlat/client.py:5` docstring 仍写 `127.0.0.1:<内部网关端口>`，而 `client.py:51` `DEFAULT_BASE_URL = "http://127.0.0.1:<内部网关端口>"` 为私有内网 地址（docs/08 §1.7 勘误已记录后者，docstring 残留未清）。代码内共 28 个 `TEXLATE_*` 环境变量，docs/README/CLAUDE.md 对 `TEXLATE_BABELDOC_TIMEOUT`/`TEXLATE_MODEL_PROBE`/`TEXLATE_NODE`/`TEXLATE_SHARE_DIR`/`TEXLATE_TS_WORKER` 等零提及，全仓无环境变量总表。

## 2. research/ 档案组织与索引健康

`docs/README.md:19` 称 research/ 存「73 篇调研/审计报告」，实际 research/ 下 .md 共 99 篇（含各子目录 README），口径含糊且数字已陈旧。`docs/research/README.md` 索引缺口五处：整目录未登记 `preclean-2026-09-16/`（含自身 README+9 件）与 `refactor-audit-2026-09-17/`（其中 report.md 正是 worker/segmenter 拆包、repair/redlines 的决策出处——不索引则 §1.2 的结构性变化在档案面不可发现）；根目录散件 `overseer-2026-09-16.md`、`2026-09-16-loop1-status-and-next.md` 未登；`gateway/2026-09-16-free-tokens.md` 不在 gateway 表；`audit-2026-09-16/wave2-findings.md` 不在该目录自带 README 的分报告表。组织约定未成文：日期化快照目录（audit-_/preclean-_/refactor-audit-*）与主题目录（arxiv/latex/corpus/…）并存，何时新建日期目录 vs 归入主题目录无规则，散件文件直接堆 research/ 根。superseded 标记执行不一：正面例 `docs/research/audit-2026-09-16/m3.md` 顶部有「⚠️ SUPERSEDED 2026-09-17」横幅并指向裁决文；反例 `docs/research/gateway/free-glm.md` TL;DR 仍推 `glm-5-3-low` 免费档默认，已被 `gateway/free-model-ranking.md`（swe-2-medium 默认）改判且无注记，glm-5-2 promo 已于 09-16 到期这类时效结论亦无时效标。档案面外引用：`docs/05` 两处勘误引「m3gap 裁决」指向 `bench/results/m3gap-scout-2026-09-17/report.md`——该文件当前 untracked 且在 research/ 视线外，裁决证据有丢失与断链双重风险。

## 3. 上手摩擦推演（clone → e2e mock 跑通）

理论路径 `clone → uv sync → uv run pytest tests/` 可达「测试绿」——`tests/conftest.py` 对 corpus/网关/node 依赖用例有 env 守卫，干净 clone 应全绿。断点依次：`uv sync` 默认不含 `server` extra，跑 `texlate web` 会缺 fastapi，`--extra server` 此前只在内部交接文档提及、README 开发形态未写；`texlate run <id>` 是 mock 端到端（`src/texlate/cli.py:358` 硬编码 MockTranslator），README 把它写成「CLI 直跑整链 → 双语 PDF」却不说明默认假译文——新人产出 PDF 后才发现译文是占位；mock 链仍需 TeX 引擎，`texlate tools install-tectonic` 与 `texlate doctor` 存在但 README/CLAUDE.md 均未列（仅 `docs/research/` 系 runbook §1 表收录），引擎缺位时的引导路径无文档；真翻译需 BYOK，`TEXLATE_BASE_URL/API_KEY/MODEL` 三 env 只在 runbook 提及，且代码默认 base_url 是本机网关 `127.0.0.1:<内部网关端口>`（client.py:51），外部贡献者不配置即打不可达地址；SPA 需先跑 `scripts/build-web.sh`（需 node/npm）否则 `texlate web` 起服后 `/` 404，`web/README.md` 写清了但根 README 无导流；pre-commit 前置条件 `brew install autocorrect ruff shfmt shellcheck actionlint taplo`（CLAUDE.md 格式化工具链节）面向 macOS，本仓主开发环境为 Linux，无 apt/pacman 等价说明；bench 语料（corpus*/results）gitignored 走 内部同步管理（`bench/corpus_v3/MANIFEST.md`），新贡献者无法复跑 parsebench 等，可接受但上手指引未声明。总结：到测试绿 3 步无障碍；到 mock PDF 需 +1 步（tectonic）但无文档指引；到真翻译需 +BYOK 三 env 或 web settings，且默认网关值对外部用户是死值。

## 4. 决策可追溯性（01–05 ↔ 06–10 映射与无出处实现）

`docs/05` §5 头部给出显式映射：§5.1→06、§5.2–5.3→07、§5.4–5.5→08§1–2、§5.6→08§3–5、bench→09/10、§5.7–5.10 留 research/——22 条 E1–E22 裁决基本都能在 06–10 或 research/ 找到落点，映射机制本身是完整的。断点集中在「规格→当日新增实现」的回写：`repair.py`/`redlines.py`/`latex/segmenter/`/`server/worker/` 拆包的决策出处是 `docs/research/refactor-audit-2026-09-17/report.md`，但该目录未入索引（§2）；m3gap「维持现状」裁决被 docs/05 两处勘误引用，裁决书却在 untracked 的 `bench/results/m3gap-scout-2026-09-17/report.md`；`TEXLATE_OFFLINE` 离线总闸只有 tools-runbook 与 commit 痕迹，`docs/06` §1 请求纪律节无对应规格条目——用户可见行为缺规范出处；xlat 占位符 token 全族（SL/PL/SP/NBSP/THINSP/MEDSP/THICKSP/NEGSP）的扩充决策无决策史条目，仅 docs/08 勘误记录实装差异；`compile/toolchain.py`/`cjkmap.py`/`latex209.py`/`mask.py` 属实现期新增模块，docs/08 章节未逐一点名（latex209 仅在 §3.3 勘误旁及）。结论：05→06–10 的静态映射不缺；缺的是 refactor-audit 这类结构性裁决「当日落地、当夜漂移」的登记闭环——勘误制在补精度（行号级），但补不上「出处文档本身不在档案面」这类断链。

## 5. 三条文档面改进建议（按防误导价值排序）

**一、入口文档数字面清零重建（README.md 表格 + CLAUDE.md 布局行）**。理由：新读者第一站同时是漂移重灾区——规则数一处文内四个版本（36/33/62/67 对真实 70）、L0「7 规则」对实 12、语料「1200」对实 5133、CLI 清单漏 share/doctor、目录树整体旧名。建议：易腐数字从散文中移除，改为指向生成源（rules.yaml 自注释、MANIFEST.md、`texlate doctor --counts` 类自检输出）或「见最新 audit」链接；目录树只保留包级结构不列文件清单。防误导价值最高：消除「文档把错数字教给第一天读者」的全部渠道。

**二、research/ 索引补登 + 登记约定成文（档案注册表）**。理由：证据链完整性缺口集中在此——refactor-audit 未索引导致拆包决策不可发现、m3gap 裁决书在 untracked 区、free-glm 该标 superseded 未标、「73 篇」口径失真。建议：`docs/research/README.md` 补登 preclean/refactor-audit 两目录与根散件、各子目录 README 补漏件；并写 3–5 行约定：新报告/新目录必须登记索引、被改判报告必带 SUPERSEDED 横幅（`audit-2026-09-16/m3.md` 为范例）且裁决证据须落 research/ 或入库 bench/results（untracked 区不作引用源）。防误导价值次之：修复的是「查不到」而非「看到错」。

**三、勘误引用粒度从 `file:line` 改「模块 + 符号」（外加一条总注）**。理由：worker/segmenter 拆包当日让 docs/08 约 10 处 `worker.py:NNNN` 锚点全灭，证明裸行号半衰期以小时计；勘误正文改用 `worker/compile.py::_probe_target` 级粒度（文件名 + 符号名、省行号）可显著延寿，docs/README 加一行「行号锚点为时点快照」总注兜底既有存量。防误导价值第三：不消错、只降衰减速度。备选并列项：README 补「从零到 mock e2e」段（server extra / install-tectonic / doctor / mock-vs-real / BYOK env / 中性默认网关）——若 roadmap 含「对外开源发布」项，此条应与第三条合并或替换（私有内网 默认 base_url 对公网用户属功能性误导而非文档瑕疵）。
