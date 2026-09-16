# 文档漂移审计 — 2026-09-16（HEAD f461683）

只读审计：文档声明 vs 代码/仓库现实。逐条给出 `文件:行` 与实测证据。

## 1. AGENTS.md（= CLAUDE.md 软链目标）

| 位置        | 声明                                                            | 现实                                                                                                                                                                                         | 判定     |
| ----------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| L4 / L45    | 「M0 实施中（2026-09-15 起）」                                  | M1 范围（Mouth/Gullet/Segmenter 移植 + xlat 编排）已全落且 f461683 已切 v2 为默认产品路径；M2 范围（fixloop/tlmgr/normalize）已落，compilebench-v4 联合 pdf 89.5%；M3 范围 server/web 已实装 | **陈旧** |
| L4 / L8     | `latex/`「半解析管线」「半解析 + 展平+splice」                  | v2 切换后默认路径 = Gullet 展开流 → Segmenter；v1 scanner 退役为 parsebench 对照臂（docs/07 §12）。「半解析」未提展开机                                                                      | **陈旧** |
| L4          | `compile/fixloop/`「yaml 修复引擎 25 规则」                     | `rules.yaml` `rules:` 段实测 **31 条**（v3，HANDOFF-2026-09-16 §2.2「29→31」）；另有 taxonomy 段 28 个 pattern 条目                                                                          | **陈旧** |
| L8          | `server/`（M3 占位）                                            | 实装 3639 行：`app.py` 862 / `worker.py` 1474 / `store.py` 705 / `settings.py` 441 / `events.py` 92（FastAPI+SSE+SQLite+BYOK+11 态机，d400669/005488e）                                      | **陈旧** |
| L8 仓库布局 | 无 `web/` 条目                                                  | `web/` 存在：SolidJS+Vite+pdfslick 阅读器，独立 package.json/tsconfig/vitest（ecb1e08 起），CI 有 web job                                                                                    | **缺失** |
| L8 模块列举 | 无顶层 `align.py`/`e2e.py`/`texlog.py`/`textutil.py`            | 四者均存在且被 server/cli/compile 消费                                                                                                                                                       | 不完整   |
| L16         | `corpus_v2/`「137 篇」                                          | MANIFEST.md 与 manifest.jsonl 均为 **139 篇**（嵌套目录实测 139）                                                                                                                            | **错误** |
| L17         | corpus_v3「manifest.jsonl+MANIFEST.md 入库」                    | 实际 tracked 还有 `mechanisms.jsonl`(144 行)/`manifest_booster.jsonl`/`booster_selection.jsonl`(各 200 行)/`select_booster.py`/`selection_report.md`                                         | 不完整   |
| L17         | 「`build_corpus_v3.py` 管线可重建」（语境暗示在 corpus_v3/ 内） | 实在 `bench/py/build_corpus_v3.py`；corpus_v2 的 build 脚本才在语料目录内                                                                                                                    | 易误导   |
| L25         | brew 前置清单无 `taplo`                                         | `.pre-commit-config.yaml` 有 `taplo`（toml）hook（language: system 需本机二进制）；CI 亦 `brew install taplo`。缺装则 pre-commit 必挂                                                        | **缺失** |
| L29         | 「无 ts 故无 tsc」                                              | `web/` 全量 TypeScript（tsc --noEmit/eslint/vitest 在 CI web job）。根 eslint.config.js 首行注释同病                                                                                         | **陈旧** |
| L25–35 链条 | 未列 `*.toml` → taplo                                           | pre-commit 有 taplo hook                                                                                                                                                                     | 缺失     |
| L41         | 「skill 本体在 `.agents/skills/`，各带 `agents/openai.yaml`」   | `.agents/skills/` 为**空目录**，仓内零 skill；`.claude/skills/` 亦空。约定成立但无实例                                                                                                       | 现状不符 |
| L10         | research「五子目录」                                            | 实际六个：arxiv/corpus/gateway/latex/product + `lit/`（句内已括注 lit，轻微）                                                                                                                | 轻微     |

正确未漂：`uv sync`/Python 3.12+/`uv run texlate` 入口、pre-commit 机制描述、`.tex` 不进链、`bench/results/` 划出、`agent-links.sh` 存在且 `CLAUDE.md→AGENTS.md` 软链正确、`.claude/` gitignored。

## 2. README.md（根）

| 位置 | 声明                                          | 现实                                                                                     | 判定     |
| ---- | --------------------------------------------- | ---------------------------------------------------------------------------------------- | -------- |
| L5   | 「状态：M0 实施中」                           | 同 §1                                                                                    | **陈旧** |
| L9   | 「M1 解析加固」                               | 05 §6 修订为「M1 展开 + 翻译」（03 里程碑已被替代，文内未注）                            | 陈旧     |
| L16  | `latex/`「miniscanner 重写」叙事              | 默认已是 v2 展开机路径                                                                   | **陈旧** |
| L18  | `validate/`「L0 规则校验（7 规则）」          | l0.py 实有 7 个 `_check_*`（placeholder/brace/env/key/math/length/macro）                | 正确     |
| L19  | `compile/`「pipe-xel 13/39」                  | compilebench-v4+fixloop 臂联合 pdf 154/172=89.5%（bench/results 有归因文档）             | **陈旧** |
| L20  | `fixloop/`「25 规则全移植」                   | 31 条                                                                                    | **错误** |
| L22  | corpus_v2「137 篇」；mechanisms「143 条」     | 139 篇；mechanisms.jsonl 144 行                                                          | **错误** |
| L22  | 评测器只列 parsebench/fixtures/validbench     | compilebench(B3)/xlatbench(B4)/e2e_mock+e2e_real(B5)/alignbench(B7) 均已存在于 bench/py/ | 不完整   |
| 全表 | 无 `server/`、`web/`、`align.py`、`e2e.py` 行 | 均已实装                                                                                 | 不完整   |

## 3. docs/README.md 与 docs/research/README.md

- docs/README.md L19：`research/`「45 篇调研报告」→ 实测非 README 的 .md **58 篇**（含审计进行中的 audit-2026-09-16/）。
- docs/README.md 表格缺 `HANDOFF-2026-09-16.md`（已存在于盘，untracked）。
- docs/README.md L4「各文档表头均有状态注记」：06/08/09/10 表头只有「最终技术方案 + 证据基础」，无状态字段；有实质落地记录的仅 07 §12 与 10 B1。
- docs/README.md L22 所列 4 个暂居 research/ 的后置规范文件全部存在 ✓。
- research/README.md 索引缺 5 篇：`latex/segmenter-integration.md`、`latex/2026-09-15-adversarial-audit.md`、`latex/2026-09-16-aux-cjk-truncation.md`、`corpus/2026-09-15-parsebench-icc.md`、`product/2026-09-16-xlat-resume-review.md`；本轮审计新增 `audit-2026-09-16/*` 亦需补登。

## 4. docs/06–10 规格抽查

- 07 §12「v2 产品面切换落地记录（2026-09-16）」数字与 HANDOFF-2026-09-16 一致（identity 1955/1955、leak 0.046%、dead_ph 0、unresolved 111）✓ **最新**。
- 08 §5.1「taxonomy（log→类别，18 regex）」→ rules.yaml taxonomy 段实测 **28** 个 pattern 条目（v2/v3 扩过）。
- 08 §5 标题路径 `compile/fixloop.py` → 实为 `compile/fixloop/` 包（engine/cases/ctan/logparse/_yamlish/rules.yaml）。
- 08 §2.2 与 05 §6 M1 均承诺可选组件 `texlate[ts-validator]` → pyproject extras 只有 `server`；实现侧 `validate/ts/validator.js`+node 子进程已在（无 node 优雅降级 L0），extra 名从未建立。
- 08 §5.2「沉淀队列头号 case：soul_cjk_mbox」→ taxonomy 已有 `soul_err`（L186），该句可能已被 v2/v3 规则消化（低置信提示）。
- 10 §0「现状」列：B3「spike 已验证，需产品化」→ 已产品化（compilebench-v4）；B4「gwbench 雏形」→ xlatbench 冒烟 47/48=98%；B5「mock 16/16」→ e2e-real n100 已跑（chunk ok 99.97%）；B7「probe 已验证」→ alignbench 55 对全量复跑。该列整体停留在实施前快照。
- 10 §8 M0 门「corpus39+v2 479 文件全绿」：corpus_v2 实际 224 个 .tex、corpus39 约 35 个 .tex（spike 口径 259/259），「479」与现有语料口径对不上（低置信，可能含非 .tex 文件）。
- 09 表头「~1,200 篇」：核心 1000 已入库；booster 200 已选（manifest_booster.jsonl 200 行）、docs/10 B1 记 187 篇已解析。规范是计划口径，无矛盾，但 booster 层现状只散见于 10 B1。
- 06 无落地记录小节；其描述的获取层模块面与 `src/texlate/arxiv/`（fetch/unpack/cache/locate/ratelimit/sniff）一致 ✓。
- 02 §目录结构 仍画「uv workspace 预留」树（fixrules/、tests/corpus/ 等旧名），与现行 src 布局有出入——决策史文档，按纪律可不改。

## 5. bench 协议与语料清单

- `bench/PROTOCOL.md` fixtures 清单只有 tricky.tex/tricky-209/tricky-multi → 实际还有 `tricky-w.tex`、`tricky-w73/`、`tricky-wenc.tex`、`escape-outside.tex`、`xlat-traps.tex`。
- PROTOCOL「tricky.tex 30 个陷阱构造」→ 实测 27 个唯一 `@Tnn` 标记（28 行出现）。
- PROTOCOL 注记与 4 项评测法本身仍准确；corpus39 描述与 MANIFEST 一致（39 篇，目录 40=39+MANIFEST）。
- `bench/corpus_v3/MANIFEST.md`「入库的只有此清单、manifest.jsonl、mechanisms.jsonl 与 bench/py/build_corpus_v3.py」→ tracked 实际还有 `manifest_booster.jsonl`、`booster_selection.jsonl`、`select_booster.py`、`selection_report.md`、`.gitignore`。
- corpus_v2 MANIFEST（139 篇/1178 文件/224 tex）与目录实测一致 ✓；manifest.jsonl 217 行含丢弃记录（丢弃小计与 MANIFEST 表头吻合）。
- corpus_v3 manifest.jsonl 1000 行与 MANIFEST「1000 篇/1955 tex」一致 ✓；本地 {id}/ 目录 976 个（数据 gitignored、rsync 管理，booster 层另计），非文档错误但值得知道。

## 6. Agent 入口层

- `scripts/agent-links.sh` 存在且可用；`CLAUDE.md→AGENTS.md` 软链正确；`.agents/skills/` 与 `.claude/skills/` 皆空目录（无断链）。
- `.claude/agents/repo-scout.md` 是本机未跟踪文件，`.agents/` 无对应 `agents/` 层——脚本只同步 skills 不同步 agents，该 agent 定义换机即失（提示，非错误）。
- `.claude/scheduled_tasks.lock` 运行时产物，gitignored，正常。

## 7. pyproject.toml

- `version=0.1.0` == `src/texlate/__init__.py.__version__` ✓；`texlate = texlate.cli:app` ✓（cli 实有 version/fetch/parse/run/web 五命令）。
- extras 仅 `server`（fastapi/python-multipart/uvicorn/sse-starlette）与 server/ 实装及 web/README「`texlate[server]`」一致 ✓；spec 承诺的 `texlate[ts-validator]` extra 缺位（见 §4）。
- `[[tool.uv.index]]` tuna pin 与本机 `UV_DEFAULT_INDEX` churn 的处置口径在 HANDOFF-2026-09-16 §1 有记（uv.lock 不 commit）——当前 `git status` 里 uv.lock modified 正是此已知现象。

## 8. 未漂/健康面（抽查通过项）

- docs/07 §12 落地记录 = 当前事实；HANDOFF-2026-09-16 内容与新提交一一对应。
- tests/ 49 个测试文件，README「全绿」声明与 HANDOFF「1090 passed/16 skipped」一致。
- bench/ts package.json 实为 unified-latex+tree-sitter+latex-utensils（无 latexjs 包名——latex-utensils 是其继承者，CLAUDE.md「latexjs」属旧称，轻微）。
- docs/05 §3 裁决表与 research/ 证据链互引正常。
