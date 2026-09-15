# TeXlate

> 开源版「幻觉翻译」(hjfy.top)：arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF，双语对照阅读。
> 当前状态：调研完成，方案冻结（`docs/05-reproduction-plan.md`），可按里程碑开工。决策与架构见 `docs/`（01 技术栈 ADR、02 架构、03 roadmap、04 选型上下文、05 复现方案）。

## 仓库布局

- `docs/` — ADR/架构/路线图（01–05）+ `docs/research/` 调研档案（`README.md` 总索引；arxiv/latex/corpus/gateway/product 五子目录，`lit/` 文献原件 gitignored）
- `bench/` — 解析/编译库 benchmark 现场（`bench/PROTOCOL.md` 是评测协议：每库测解析鲁棒性/陷阱断言/round-trip/输出物 4 项）
    - `bench/py/` — python 侧 bench（pylatexenc/TexSoup/plasTeX/miniscanner/fixloop/compile/parsebench），`scratch/` 是一次性探针
    - `bench/py/.venv_babeldoc/` — babeldoc 对照实验专用 venv（gitignored）
    - `bench/ts/` — js 侧 bench（latexjs/unified-latex/tree-sitter-latex），独立 package.json，CommonJS
    - `bench/corpus/` — 39 篇手挑陷阱语料（子目录 gitignored，`MANIFEST.md` 入库）
    - `bench/corpus_v2/` — 137 篇分层随机语料（同上惯例；`MANIFEST.md`+`build_corpus.py` 入库）
    - `bench/fixtures/` — 陷阱构造 `.tex`（`% @Tnn` 标记；**逐字节即语义——不要格式化/润色这些文件**）
    - `bench/results/` — bench 产出目录（report/walkthrough/json 均由脚本重写；不在 format/lint 链内）
    - `bench/work_*/` — 编译/fixloop 工作区（gitignored 重产物）
- `tmp/` — scratch 实验区（整目录 gitignored；`tmp/exp/` 实验现场、`tmp/refs/` 参考仓库 clone）

## 格式化工具链

`git commit` 会走 pre-commit：formatter 经 git-format-staged 改写暂存内容并同步工作区（两侧一致，commit 不被格式化阻断，未暂存编辑不受污染）；check 类 hook 失败才拦。前置条件：`npm install`、`brew install autocorrect ruff shfmt shellcheck actionlint`、`pre-commit install`。版本以 `package.json` 为唯一事实源，编辑器（`.vscode/settings.json` 的 prettierPath）与 hook 同源。

- `*.sh`：`shfmt -i 2`（gfs）+ `shellcheck -S warning`。zsh 脚本不在链内——两者都不支持 zsh，`scripts/fmt-shell.sh` 对 zsh shebang 原样透传。
- `*.py`：`ruff format`（gfs）+ `ruff check`（`ruff.toml` 是 `select=ALL` + 逐条注明豁免）。
- `*.js`/`*.json`：`prettier`（gfs）+ `eslint`（flat config，CommonJS bench 脚本；无 ts 故无 tsc）。
- `*.md`：`markdownlint-cli2 --fix` 原地改写（改写会 fail 一次，重新 `git add` 再提交）→ `autocorrect --stdin | prettier`（gfs）。
- `*.yaml`/`*.yml`：`prettier`（gfs）。缩进规则：yaml 2 空格、md 4 空格，见 `.prettierrc` overrides。
- `.github/workflows/*`：`actionlint`（check）。
- `*.tex`：**不进链**——`bench/fixtures/` 是陷阱输入，字节即语义。
- `bench/results/`：整目录划出 format/lint——脚本产出目录，重跑会重写。
- gitleaks 拦 secret；`.gitleaks.toml` 目前只用默认规则。

CI（`.github/workflows/ci.yml`）与本地同源，本地不过 CI 必挂。

## Agent 入口约定

`AGENTS.md` 与 `.agents/` 是入库的唯一事实源（skill 本体在 `.agents/skills/`，各带 `agents/openai.yaml` 元数据）。`CLAUDE.md` 与 `.claude/skills/` 是指向它们的软链，属本机便利层、不入库；clone 后跑 `scripts/agent-links.sh` 重建。

## 项目运维约定

- 本仓处于调研/bench 阶段：没有产品代码，`bench/` 下脚本即全部可执行内容。
- `bench/py/` 脚本用系统 python3（依赖见各文件头部注释）；`babeldoc` 对照实验用 `bench/py/.venv_babeldoc/` 专用 venv。
- `bench/ts/` 自带 `package.json` + `node_modules`（latexjs/unified-latex/tree-sitter 依赖），与根 toolchain 的 package.json 无关——在 `bench/ts/` 里 `npm ci`。
- `bench/corpus*/` 语料是 arXiv e-print 解压原样，不改写；新增语料登记对应 `MANIFEST.md`。
- 参考实现 `~/src/ieeA`（zcyisiee/ieeA）只借鉴模式不搬代码。
