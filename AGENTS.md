# TeXlate

> 开源版「幻觉翻译」(hjfy.top)：arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF，双语对照阅读。
> 当前状态：**M0 已验收、M1 实质达成、M2/M3 推进中**（2026-09-16 全仓审计 `docs/research/audit-2026-09-16/`；当日交接 `docs/HANDOFF-2026-09-16.md`）。调研完成、方案冻结；决策史 `docs/01–05`，最终技术规格 `docs/06–10`（实现按此执行），过程证据归档 `docs/research/`。已落 `src/texlate/`：`arxiv/`（获取层）、`latex/`（半解析 + 展开机——**v2 Gullet+Segmenter 为默认产品路径**，`TEXLATE_NO_EXPAND=1` 回退 v1；corpus_v3 3937 文件 identity 100%/leak 0.040%）、`xlat/`（编排 + 网关客户端）、`validate/`（L0/L1/L2）、`compile/`（引擎/注入/normalize/probe/sandbox）+ `compile/fixloop/`（yaml 修复引擎 67 规则 + llm_hook）、`server/`（FastAPI+SSE+SQLite+BYOK 实装 + babeldoc sidecar + SPA staticfiles + `cmaps/` GB1 ToUnicode）、`export/`（EPUB/DOCX 双语插译）、`share.py`、`cli.py`（typer：fetch/parse/run/web/export/version/tools）。

## 仓库布局

- `src/texlate/` — 产品代码（uv 管理，`uv sync` 起 .venv；Python 3.12+）：`arxiv/` 获取层、`latex/` 半解析管线（mouth/gullet/segmenter v2 默认 + v1 对照臂）、`xlat/` 翻译编排、`validate/` 校验三层、`compile/` 引擎 + 注入+normalize+`fixloop/` yaml 修复引擎、`server/`（FastAPI+SSE+SQLite+BYOK+worker 管线，web 后端实装；app/settings/store/worker/events/staticfiles/babeldoc/`__main__`）、`cli.py`（typer）、`align.py`（named-dest 锚点同步）、`e2e.py`（整链编排）、`texlog.py`（编译日志 file stack）、`textutil.py`（编码/文本工具）、`share.py`、`export/`（EPUB/DOCX）
- `web/` — SolidJS+Vite+pdfslick 阅读器前端（独立 package.json/tsconfig/vitest；TypeScript 全量，CI web job 跑 tsc/eslint/vitest）
- `tests/` — pytest（corpus/网关/node 依赖用例均有 skipif/env 守卫，干净 clone 全绿）
- `docs/` — `README.md` 总索引；决策史 01–05 + 最终技术规格 06–10 + `docs/research/` 调研档案（arxiv/latex/corpus/gateway/product/audit-* 子目录，`lit/` 文献原件 gitignored）
- `bench/` — 解析/编译库 benchmark 现场（`bench/PROTOCOL.md` 是评测协议：每库测解析鲁棒性/陷阱断言/round-trip/输出物 4 项）
    - `bench/py/` — python 侧 bench（pylatexenc/TexSoup/plasTeX/miniscanner/fixloop/compile/parsebench），`scratch/` 是一次性探针
    - `bench/py/.venv_babeldoc/` — babeldoc 对照实验专用 venv（gitignored）
    - `bench/ts/` — js 侧 bench（latex-utensils/unified-latex/tree-sitter-latex），独立 package.json，CommonJS
    - `bench/corpus/` — 39 篇手挑陷阱语料（子目录 gitignored，`MANIFEST.md` 入库）
    - `bench/corpus_v2/` — 139 篇分层随机语料（同上惯例；`MANIFEST.md`+`build_corpus.py` 入库）
    - `bench/corpus_v3/` — 1000 篇核心随机层 + 200 篇补强层 + 热层（OpenAlex 高引近期，分批取源中）（`manifest.jsonl`/`manifest_booster.jsonl`/`manifest_hot.jsonl`/`mechanisms.jsonl`/`MANIFEST.md`/`select_booster.py` 等入库、数据 gitignored；管线 `bench/py/build_corpus_v3.py` + `build_hot_layer.py`）
    - `bench/fixtures/` — 陷阱构造 `.tex`（`% @Tnn` 标记；**逐字节即语义——不要格式化/润色这些文件**）
    - `bench/results/` — bench 产出目录（report/walkthrough/json 均由脚本重写；**全链划出**——改写型 formatter 与 check 类链都不覆盖：prettier/gfs/eslint/autocorrect 经 ignore/exclude，markdownlint 经 cli2 ignores，ruff 经 extend-exclude，shfmt/shellcheck/taplo 无对应文件类型属 vacuous）
    - `bench/work_*/` — 编译/fixloop 工作区（gitignored 重产物）
- `tmp/` — scratch 实验区（整目录 gitignored；`tmp/exp/` 实验现场、`tmp/refs/` 参考仓库 clone）

## 格式化工具链

`git commit` 会走 pre-commit：formatter 经 git-format-staged 改写暂存内容并同步工作区（两侧一致，commit 不被格式化阻断，未暂存编辑不受污染）；check 类 hook 失败才拦。前置条件：`npm install`、`brew install autocorrect ruff shfmt shellcheck actionlint taplo`、`pre-commit install`。版本以 `package.json` 为唯一事实源，编辑器（`.vscode/settings.json` 的 prettierPath）与 hook 同源。

- `*.sh`：`shfmt -i 2`（gfs）+ `shellcheck -S warning`。zsh 脚本不在链内——两者都不支持 zsh，`scripts/fmt-shell.sh` 对 zsh shebang 原样透传。
- `*.py`：`ruff format`（gfs）+ `ruff check`（`ruff.toml` 是 `select=ALL` + 逐条注明豁免）。
- `*.js`/`*.json`：`prettier`（gfs）+ `eslint`（flat config，根目录是 CommonJS bench 脚本无 tsc；`web/` 是 TypeScript，走 `web/` 自己的 toolchain + CI web job——pre-commit eslint glob 只盖 `js/mjs/cjs`，web `.ts` 本地零 eslint 门是有意取舍：不假设 `web/node_modules` 在场，lint 由 web toolchain/CI 把关）。
- `*.md`：`markdownlint-cli2 --fix` 原地改写（改写会 fail 一次，重新 `git add` 再提交）→ `autocorrect --stdin | prettier`（gfs）。
- `*.yaml`/`*.yml`：`prettier`（gfs）。缩进规则：yaml 2 空格、md 4 空格，见 `.prettierrc` overrides。
- `*.toml`：`taplo`（gfs）。
- `.github/workflows/*`：`actionlint`（check）。
- `*.tex`：**不进链**——`bench/fixtures/` 是陷阱输入，字节即语义。
- `bench/results/`：**全链划出**（改写型 formatter 与 check 类链都不覆盖）——脚本产出目录，重跑会重写。formatter 经 ignore 文件与 hook `exclude` 划出；check 侧 markdownlint 经 `.markdownlint-cli2.jsonc` ignores、ruff 经 `ruff.toml` extend-exclude 划出，shfmt/shellcheck/taplo 因目录无对应文件类型而 vacuous。若日后往此目录入库脚本/源文件，需重新评估链覆盖。
- gitleaks 拦 secret；`.gitleaks.toml` 目前只用默认规则。

CI（`.github/workflows/ci.yml`）与本地同源，本地不过 CI 必挂。

## Agent 入口约定

`AGENTS.md` 与 `.agents/` 是入库的唯一事实源（skill 约定放 `.agents/skills/`，各带 `agents/openai.yaml` 元数据——当前仓内尚无 skill 实例）。`CLAUDE.md` 与 `.claude/skills/` 是指向它们的软链，属本机便利层、不入库；clone 后跑 `scripts/agent-links.sh` 重建。

## 项目运维约定

- 本仓处于 M1–M3 推进阶段（M0 已验收，详见 `docs/research/audit-2026-09-16/README.md`）：`src/texlate/` 产品代码 + `tests/` pytest；`bench/` 下是评测 harness 与语料管线。
- 产品代码一律走 uv venv：`uv sync` 后 `uv run pytest tests/` / `uv run texlate`；**`src/**` 吃 ruff select=ALL 严格集（docstring/类型标注/异常纪律），bench/tests 的脚本豁免在 per-file-ignores**。
- `bench/py/` 脚本分两档：纯 bench 工具用系统 python3（依赖见各文件头部注释）；**import `texlate.*` 产品代码的（e2e_mock_bench/parsebench v2 等）必须 `uv run python bench/py/…`**——venv 才有 httpx/typer。`babeldoc` 对照实验用 `bench/py/.venv_babeldoc/` 专用 venv。
- `bench/ts/` 自带 `package.json` + `node_modules`（latexjs/unified-latex/tree-sitter 依赖），与根 toolchain 的 package.json 无关——在 `bench/ts/` 里 `npm ci`。
- `bench/corpus*/` 语料是 arXiv e-print 解压原样，不改写；新增语料登记对应 `MANIFEST.md`。
- 参考实现 `~/src/ieeA`（zcyisiee/ieeA）只借鉴模式不搬代码。
