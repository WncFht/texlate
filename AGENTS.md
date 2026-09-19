# TeXlate

> 开源版「幻觉翻译」(hjfy.top)：arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF，双语对照阅读。
> 当前状态：**M0 已验收、M1 实质达成、M2/M3 推进中**（2026-09-16 全仓审计 `docs/research/audit-2026-09-16/`）。调研完成、方案冻结；决策史 `docs/01–05`，最终技术规格 `docs/06–10`（实现按此执行），过程证据归档 `docs/research/`。已落 `src/texlate/`：`arxiv/`（获取层）、`latex/`（半解析 + 展开机——**v2 `gullet/`+`segmenter/` 包为唯一解析路径**；corpus_v3 identity 100%/leak 0.040%（parsebench 实测，时点 3937 文件））、`xlat/`（编排 + 网关客户端 + `terms/` 术语表资产）、`validate/`（L0/L1/L2 + `ts/` tree-sitter node 校验件）、`compile/`（引擎/注入/normalize/probe/sandbox/loginfo/deps/judge/latex209/mask/toolchain + `cmaps/` GB1 ToUnicode 资产，cjkmap 消费）+ `compile/fixloop/`（yaml 修复引擎 engine/actions/ruleset 三件套 + cases/ctan/logparse/_yamlish 支撑件 + llm_hook；规则库 = `rules/` 分片目录，自 rules.yaml 拆出，条目数以生成源为准；builtins facade + `_builtins_*` 八叶 + `vendor/` files/stubs 离线宏包资产）、`server/`（FastAPI+SSE+SQLite+BYOK 实装 + babeldoc sidecar + SPA staticfiles + upload 安全解包 + `worker/` 包管线）、`export/`（EPUB/DOCX 双语插译）、`repair.py`+`repair_l2.py`（e2e/worker 双臂共享修复低层件 + L2 回灌/env judge 归因簇，C4 拆分）、`redlines.py`（红线概念注册表）、`share.py`、`cli.py`（typer：fetch/parse/run/web/export/share/doctor/version/tools）。

## 仓库布局

- `src/texlate/` — 产品代码（uv 管理，`uv sync` 起 .venv；Python 3.12+）：`arxiv/` 获取层、`latex/` 半解析管线（mouth + `gullet/`/`segmenter/` 包）、`xlat/` 翻译编排（+`terms/` 术语表）、`validate/` 校验三层（+`ts/` node 校验件）、`compile/` 引擎 + 注入+normalize+probe/sandbox+loginfo/deps+judge/latex209/mask/toolchain+`fixloop/` yaml 修复引擎（engine/actions/ruleset 三件套 + cases/ctan/logparse/_yamlish + llm_hook；`rules/` 分片 + `_builtins_*` 八叶 + `vendor/` 资产）+ `cmaps/` GB1 cmap、`server/`（FastAPI+SSE+SQLite+BYOK+worker 包管线，web 后端实装；app/settings/store/upload/events/staticfiles/babeldoc/`worker/`/`__main__`）、`cli.py`（typer）、`align.py`（named-dest 锚点同步）、`e2e.py`（整链编排）、`repair.py`+`repair_l2.py`（双臂共享修复件 + L2 归因簇）、`redlines.py`（红线注册表）、`texlog.py`（编译日志 file stack）、`logsetup.py`（日志装配单源：RichHandler stderr + RedactFilter 脱敏 + 轮转文件；`TEXLATE_LOG`/`TEXLATE_LOG_FILE` env）、`textutil/`（编码/文本工具包——cjk/decls/encoding/mask 四叶 + facade；`TEXLATE_*` env/正则词表单源）、`share.py`、`export/`（EPUB/DOCX）
- `web/` — SolidJS+Vite+pdfslick 阅读器前端（独立 package.json/tsconfig/vitest；TypeScript 全量，CI web job 跑 tsc/eslint/vitest）
- `tests/` — pytest（corpus/网关/node 依赖用例均有 skipif/env 守卫，干净 clone 全绿）
- `docs/` — `README.md` 总索引；决策史 01–05 + 最终技术规格 06–10 + `docs/research/` 调研档案（arxiv/latex/corpus/product/audit-* 子目录，`lit/` 文献原件与 `gateway/` 网关调研 gitignored）
- `bench/` — 解析/编译库 benchmark 现场（`bench/PROTOCOL.md` 是评测协议：每库测解析鲁棒性/陷阱断言/round-trip/输出物 4 项）
    - `bench/py/` — python 侧 bench（pylatexenc/TexSoup/plasTeX/fixloop/compile/parsebench 等；miniscanner spike 已退役，断言矩阵移植 `tests/test_bench_regression.py`），`report/`=一次性审计/横评/归因、`corpus/`=语料管线、`scratch/`=一次性探针
    - `bench/py/.venv_babeldoc/` — babeldoc 对照实验专用 venv（gitignored）
    - `bench/ts/` — js 侧 bench（latex-utensils/unified-latex/tree-sitter-latex），独立 package.json，CommonJS
    - `bench/corpus/` — 39 篇手挑陷阱语料（子目录 gitignored，`MANIFEST.md` 入库）
    - `bench/corpus_v2/` — 139 篇分层随机语料（同上惯例；`MANIFEST.md`+`build_corpus.py` 入库）
    - `bench/corpus_v3/` — 核心随机层 + 策展补强层 + 热层（OpenAlex 高引近期）+ expand 扩展层，最新分层口径以 `MANIFEST.md` 为准（`manifest*.jsonl`/`mechanisms.jsonl`/`select_booster.py` 等入库、数据 gitignored；管线 `bench/py/corpus/build_corpus_v3.py` + `build_hot_layer.py` + `build_corpus_expand.py`）
    - `bench/fixtures/` — 陷阱构造 `.tex`（`% @Tnn` 标记；**逐字节即语义——不要格式化/润色这些文件**）
    - `bench/results/` — bench 产出目录（report/walkthrough/json 均由脚本重写；**全链划出**——改写型 formatter 与 check 类链都不覆盖：prettier/gfs/eslint/autocorrect 经 ignore/exclude，markdownlint 经 cli2 ignores，ruff 经 extend-exclude，shfmt/shellcheck/taplo 无对应文件类型属 vacuous）
    - `bench/work_*/` — 编译/fixloop 工作区（gitignored 重产物）
- `tmp/` — scratch 实验区（整目录 gitignored；`tmp/exp/` 实验现场、`tmp/refs/` 参考仓库 clone）

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

`AGENTS.md` 与 `.agents/` 是入库的唯一事实源（skill 约定放 `.agents/skills/`，各带 `agents/openai.yaml` 元数据——现有 `improve-codebase-architecture/` 一例）。`CLAUDE.md` 与 `.claude/skills/` 是指向它们的软链，属本机便利层、不入库；clone 后跑 `scripts/agent-links.sh` 重建。

## 项目运维约定

- 本仓处于 M1–M3 推进阶段（M0 已验收，详见 `docs/research/audit-2026-09-16/README.md`）：`src/texlate/` 产品代码 + `tests/` pytest；`bench/` 下是评测 harness 与语料管线。
- 产品代码一律走 uv venv：`uv sync`（web/server 形态加 `--extra server`）后 `uv run pytest tests/` / `uv run texlate`；**`src/**` 吃 ruff select=ALL 严格集（docstring/类型标注/异常纪律），bench/tests 的脚本豁免在 per-file-ignores**。
- `bench/py/` 脚本分两档：纯 bench 工具用系统 python3（依赖见各文件头部注释）；**import `texlate.*` 产品代码的（e2e_mock_bench/parsebench v2 等）必须 `uv run python bench/py/…`**——venv 才有 httpx/typer。`babeldoc` 对照实验用 `bench/py/.venv_babeldoc/` 专用 venv。
- `bench/ts/` 自带 `package.json` + `node_modules`（latexjs/unified-latex/tree-sitter 依赖），与根 toolchain 的 package.json 无关——在 `bench/ts/` 里 `npm ci`。
- `bench/corpus*/` 语料是 arXiv e-print 解压原样，不改写；新增语料登记对应 `MANIFEST.md`。
- 参考实现 [ieeA](https://github.com/zcyisiee/ieeA) 只借鉴模式不搬代码。
