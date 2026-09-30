# TeXlate

> 开源版「幻觉翻译」(hjfy.top)：arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF，双语对照阅读。
> 当前状态：**M0 已验收、M1 实质达成、M2/M3 推进中**（2026-09-16 全仓审计 `docs/log/audit-2026-09-16/`）。调研完成、方案冻结；决策史 `docs/decisions/`（ADR + background），最终技术规格 `docs/spec/`（实现按此执行），过程证据归档 `docs/research/` 与 `docs/log/`。已落 `src/texlate/`：`arxiv/`（获取层：acquire/cache/fetch/html/locate/meta/ratelimit/sniff/unpack/`_texutil`）、`latex/`（半解析 + 展开机——**v2 `gullet/`+`segmenter/` 包为唯一解析路径**；corpus identity 100%/leak 0.040%（parsebench 实测，时点 3937 文件））、`xlat/`（编排 + 网关客户端 16 叶 + `terms/` 术语表资产）、`validate/`（L0/L1/L2 + report + `ts/` tree-sitter node 校验件）、`compile/`（`engine/` 引擎包 + inject/normalize/probe/sandbox/proc/loginfo/logparse/ctan/deps/judge/latex209/mask/toolchain/layout/mainfile/marks/shadow/transcode/cjkmap/`_yamlish` + `patchseams.py` monkeypatch 缝注册面 + `_docseams.py` docclass 注入缝原语 + `cmaps/` GB1 ToUnicode 资产，cjkmap 消费）+ `compile/fixloop/`（yaml 修复引擎 engine/actions/ruleset 三件套 + cases + llm_hook；规则库 = `rules/` 17 分片目录，自 rules.yaml 拆出，条目数以生成源为准；`builtins/` 子包（facade + 14 叶） + `vendor/` files/shims/stubs 离线宏包资产）、`server/`（FastAPI+SSE+SQLite+BYOK 实装 + babeldoc sidecar + SPA staticfiles + upload 安全解包；`routers/`/`store/`/`worker/` 三包 + `seqpos/`（PDF 锚位子包：facade + stream/docorder/match/assemble 四叶）+ auth/providers/srccut/validate/http/logredact/`_common`/`_ttlcache`/`__main__` 域件）、`export/`（EPUB/DOCX 双语插译，`epub/` 子包）、`pipecore.py`+`repair.py`+`repair_l2.py`（e2e/worker/bench 三臂共享管线 policy 脊 + 修复机械低层件 + L2 回灌/env judge 归因簇，C4 拆分）、`redlines.py`（红线概念注册表）、`share.py`（共享包 + `cache_key_for`/`cache_scope`/`PIPELINE_VERSION` dedup 键单源）、`cli/`（typer 包：命令叶 fetch/parse/run/web/export/share/tools/version/doctor + `thin` 瘦客户端 + `_common`/`_output` 底座 + 惰性 facade）。

## 仓库布局

- `src/texlate/` — 产品代码（uv 管理，`uv sync` 起 .venv；Python 3.12+）：`arxiv/` 获取层、`latex/` 半解析管线（mouth + `gullet/`/`segmenter/` 包 + api/chars/flatten/macro_table/model/placeholder/prose/reconstruct/tables 单层叶 + `data/argspec.json`）、`xlat/` 翻译编排（16 叶 + `terms/` 术语表）、`validate/` 校验三层 + report（+`ts/` node 校验件）、`compile/`（`engine/` 引擎包 + 注入/normalize/probe/sandbox/proc/loginfo/logparse/ctan/deps/judge/latex209/mask/toolchain/layout/mainfile/marks/shadow/transcode/cjkmap/`patchseams`/`_docseams`/`_yamlish` + `fixloop/` yaml 修复引擎（engine/actions/ruleset 三件套 + cases + llm_hook；`rules/` 17 分片 + `builtins/` 子包（facade + 14 叶） + `vendor/` 资产）+ `cmaps/` GB1 cmap）、`server/`（FastAPI+SSE+SQLite+BYOK+worker 包管线，web 后端实装；app/settings/upload/events/staticfiles/babeldoc/auth/providers/srccut/validate/logredact/`_common`/`_ttlcache`/`__main__` + `seqpos/` 锚位子包（facade + 四叶）+ `routers/`/`store/`/`worker/` 三包）、`cli/`（typer 包 + `thin` 瘦客户端叶）、`align.py`（named-dest 锚点同步）、`e2e.py`（整链编排）、`pipecore.py`（e2e/worker/bench 三臂共享管线 policy 脊）、`repair.py`+`repair_l2.py`（双臂共享修复件 + L2 归因簇）、`chunk.py`（xlat 输入契约共享位）、`redlines.py`（红线注册表）、`texlog.py`（编译日志 file stack）、`logsetup.py`（日志装配单源：RichHandler stderr + RedactFilter 脱敏 + 轮转文件；`TEXLATE_LOG`/`TEXLATE_LOG_FILE` env）、`textutil/`（编码/文本工具包——cite/cjk/decls/encoding/ifscan/jsonl/mask/nets/osutil/targate 十叶 + facade；`TEXLATE_*` env/正则词表单源）、`share.py`（共享包 + dedup 键单源）、`export/`（EPUB/DOCX，`epub/` 子包）
- `web/` — SolidJS+Vite+pdfslick 阅读器前端（独立 package.json/tsconfig/vitest；TypeScript 全量，CI web job 跑 tsc/eslint/vitest/build）
- `zotero/` — Zotero 7 插件（TypeScript 瘦客户端：条目右键 → 远端 texlate 翻译 → `zh.pdf` 回挂附件；独立 package.json/tsconfig/eslint.config.mjs）
- `tests/` — pytest（约 1.03 万用例；corpus/网关/node 依赖用例均有 skipif/env 守卫，干净 clone 全绿；`bench_kernel/`=bench 内核套件，经 pyproject `pythonpath=["bench/py"]` 直 import）
- `docs/` — 六分区文档库（`README.md` 总索引）：`guide/` 用户文档、`spec/` 技术规范（实现唯一事实源，与代码冲突以代码为准改文档）、`decisions/` ADR 决策史、`dev/` 贡献者文档（仓布局/工具手册/评测协议/errsweep runbook）、`research/` 调研档案（arxiv/latex/corpus/methods/product/errsweep 域 + `model-selection.md`/`bibliography.md` 单件）、`log/` 工程日志（编年时间线 + 审计快照）；**写/改任何文档先读维护规则 `docs/MAINTENANCE.md`**（分区生命周期、格式契约、公开发布敏感政策、索引登记）
- `bench/` — 评测 harness 现场。**trizone-ledger v2 已切换**（终态设计 `docs/spec/bench-trizone.md`；评测器规格 `docs/spec/benchmark.md`；分层契约 `bench/TIERS.md` L0–L3）：代码仓只留机制与清单，数据四区在 `$TEXLATE_BENCH_ROOT`（缺省 `~/.local/share/texlate-bench`，git checkout 之外，各区可经 `TEXLATE_{LEDGER,RUNS,VAULT,LAKE}_ROOT` 分卷）——`ledger/` 追加账 + `runs/` 执行档案 + `vault/` 付费字节（zh/splice 译文真身，不可再生）+ `lake/` 免费载荷（corpus 载荷/cache/durable/tmp）
    - `bench/py/` — trizone 内核与评测件：`kernel/`（30 件：ledger/runs/vault/lake/cas/dedup/importer（PEP-562 门面 + `_import_{core,records,zhstore,lake}` 四私有叶）/index/spec/sweep/doctor/paths 等 + `__main__`）、`specs/`（评测 spec 件 39：e2e_mock/e2e_real/compilebench/parsebench/fixloop_bench/gullet/soak/census/validbench/xlatbench/qualbench/errsweep/frame_build 等 + corpus_{v3,expand,hot,layers,sw,hydrate} 语料管线 + `_bootstrap`/`_shared`/`_sabotage` 辅助件）、`verbs/`（triage/gate/dossier/xlat/qual/booster/rundiff 分析动词）、`iclr/`（ICLR 章节长度研究件六叶，暂停至 10 月）、`ops/`（status_panel 只读面板/task_ping 看板心跳）；统一入口 `bench/py/bench`（可执行 shim → `kernel.cli`，动词面 `init|run|plan|status|vault|ledger|lake|derive|sweep|prune|backup|doctor|fsck|spec|triage|gate|dossier`）。断言矩阵在 `tests/bench_kernel/test_bench_regression.py` + `tests/bench_kernel/`
    - `bench/py/.venv_babeldoc/` — babeldoc 对照实验专用 venv（gitignored；现 absent，按需重建）
    - `bench/ts/` — js 侧 bench（latex-utensils/unified-latex/tree-sitter-latex），独立 package.json，CommonJS
    - `bench/corpus/` — 语料清单层：层化 manifest（core/booster/dev_*/expand/hot/holdout + v1/v2/m1k/iclr 多版本），口径以 `MANIFEST.md` 为准（勘误至八层合计 13,266 篇）；`manifest*.jsonl`/`mechanisms.jsonl`/`select_booster.py`/`selection_report.md`/`eval_coverage.json`/`nominations/` 入库、`{id}/` 载荷 gitignored——trizone 下载荷真身驻 `lake/corpus/{source}/{safe_id}/`
    - `bench/fixtures/` — 陷阱构造 `.tex`（`@Tnn`/`@Wnn`/`@Xn` 标记；**逐字节即语义——不要格式化/润色这些文件**）
    - `bench/frame/` — 抽样框架数据（`frame.parquet` + allocation/cluster 统计 csv/json——脚本重写产物，formatter 划出同 `bench/results/` 政策）
    - `bench/nominations/` — 评测提名层 jsonl（e2e_real/qualframe/wrapfloat 等 id 集）
    - `bench/results/`、`bench/work_*/`、`bench/zh-store/`、`bench/corpus_iclr_pdf/`、`bench/archive-*/` — 旧式产出/工作区/资产目录：现 absent（产出走 `runs/` 区、付费字节走 `vault/`、免费载荷走 `lake/`），对应 ignore/exclude 划出条款仍留在各 formatter/lint 配置里防复生
- `tools/` — tracked 可复用诊断/度量脚本（seqpos 对位度量组、qc_replay、docs_linkcheck、`_env.py`/`_seqpos_lib.py` 共享件等；逐件登记 `tools/README.md`；一次性探针不写这里，去 `tmp/`）
- `scripts/` — 仓级 shell 工具（agent-links/build-web/fmt-shell/errsweep/systemd 单元等）
- `shots/` — README/文档配图 PNG
- `tmp/` — scratch 实验区（整目录 gitignored）

## 格式化工具链

`git commit` 会走 pre-commit：formatter 经 git-format-staged 改写暂存内容并同步工作区（两侧一致，commit 不被格式化阻断，未暂存编辑不受污染）；check 类 hook 失败才拦。前置条件：`npm install`、`autocorrect ruff shfmt shellcheck actionlint taplo`（macOS 全走 `brew install`；Linux 对应 `pacman -S shfmt shellcheck ruff taplo-cli` + `cargo install autocorrect` + `go install github.com/rhysd/actionlint/cmd/actionlint@latest`）、`pre-commit install`。版本以 `package.json` 为唯一事实源，编辑器（`.vscode/settings.json` 的 prettierPath）与 hook 同源。

- `*.sh`：`shfmt -i 2`（gfs）+ `shellcheck -S warning`。zsh 脚本不在链内——两者都不支持 zsh，`scripts/fmt-shell.sh` 对 zsh shebang 原样透传。
- `*.py`：`ruff format`（gfs）+ `ruff check`（`ruff.toml` 是 `select=ALL` + 逐条注明豁免）。
- `*.js`/`*.json`：`prettier`（gfs）+ `eslint`（flat config，根目录是 CommonJS bench 脚本无 tsc；`web/` 是 TypeScript，走 `web/` 自己的 toolchain + CI web job——pre-commit eslint glob 只盖 `js/mjs/cjs`，web `.ts` 本地零 eslint 门是有意取舍：不假设 `web/node_modules` 在场，lint 由 web toolchain/CI 把关）。
- `*.md`：`markdownlint-cli2 --fix` 原地改写（改写会 fail 一次，重新 `git add` 再提交）→ md 内 python 栅栏 `ruff format`（文件名模式原位改写，同属 fail 一次 re-add 语义；gfs stdin 拿不到文件名识别不了栅栏）→ `autocorrect --stdin | prettier`（gfs）。裸跑 `markdownlint-cli2` 无参扫 0 文件——默认 globs 在 `.markdownlint-cli2.jsonc`，或显式传 `"**/*.md"`。
- `*.yaml`/`*.yml`：`prettier`（gfs）。缩进规则：yaml 2 空格、md 4 空格，见 `.prettierrc` overrides。
- `*.toml`：`taplo`（gfs）。
- `.github/workflows/*`：`actionlint`（check）。
- `*.tex`：**不进链**——`bench/fixtures/` 是陷阱输入，字节即语义。
- `bench/results/`：**全链划出**（改写型 formatter 与 check 类链都不覆盖）——脚本产出目录，重跑会重写。formatter 经 ignore 文件与 hook `exclude` 划出；check 侧 markdownlint 经 `.markdownlint-cli2.jsonc` ignores、ruff 经 `ruff.toml` extend-exclude 划出，shfmt/shellcheck/taplo 因目录无对应文件类型而 vacuous。若日后往此目录入库脚本/源文件，需重新评估链覆盖。
- gitleaks 拦 secret；`.gitleaks.toml` 目前只用默认规则。

CI（`.github/workflows/ci.yml`）与本地同源，本地不过 CI 必挂。

## Agent 入口约定

`AGENTS.md` 与 `.agents/` 是入库的唯一事实源（skill 约定放 `.agents/skills/`，各带 `agents/openai.yaml` 元数据——现有 `diagram-design`/`huashu-design`/`improve-codebase-architecture`/`writing-user-docs` 四例）。`CLAUDE.md` 与 `.claude/skills/` 是指向它们的软链，属本机便利层、不入库；clone 后跑 `scripts/agent-links.sh` 重建。

## 项目运维约定

- 本仓处于 M1–M3 推进阶段（M0 已验收，详见 `docs/log/audit-2026-09-16/README.md`）：`src/texlate/` 产品代码 + `tests/` pytest；`bench/` 下是评测 harness 与语料管线。
- 产品代码一律走 uv venv：`uv sync`（web/server 形态加 `--extra server`）后 `uv run pytest tests/` / `uv run texlate`；**`src/**` 吃 ruff select=ALL 严格集（docstring/类型标注/异常纪律），bench/tests 的脚本豁免在 per-file-ignores**。
- `bench/py/` 分两档：kernel/verbs/顶层工具纯 stdlib，系统 `python3 bench/py/bench <verb>` 即可跑；**`specs/` 里 import `texlate.*` 的 spec（e2e_mock/compilebench 等）要走装了依赖的 venv**——`uv run python bench/py/bench run <spec>`（`specs/_bootstrap.ensure()` 负责把 `src/` 准入 sys.path，但 httpx/typer 只在 venv 里）。`babeldoc` 对照实验用 `bench/py/.venv_babeldoc/` 专用 venv（现 absent，按需重建）。
- `bench/ts/` 自带 `package.json` + `node_modules`（latexjs/unified-latex/tree-sitter 依赖），与根 toolchain 的 package.json 无关——在 `bench/ts/` 里 `npm ci`。
- `bench/corpus/` 语料清单是 arXiv e-print 解压原样的索引面，不改写；语料载荷在 `$TEXLATE_BENCH_ROOT/lake/corpus/`（git checkout 之外）；新增语料登记对应 `MANIFEST.md`/`manifest*.jsonl`。
- 写注释/起新名/改旧名先读 `docs/dev/conventions.md`（注释引用纪律 + 命名纪律：新键日期戳、禁编号代号）；冻结名与撞名登记在 `docs/spec/glossary.md`。
- 参考实现 [ieeA](https://github.com/zcyisiee/ieeA) 只借鉴模式不搬代码。
