# TeXlate

arXiv LaTeX 源码经段落翻译和中文重编译产出双语 PDF；另有 HTML、PDF 与电子书路径。项目说明见 [README](README.md)，文档入口见 [docs/README.md](docs/README.md)。

## 修改与验证

- 产品代码使用 Python 3.12+ 与 uv：`uv sync`，按改动范围运行 `uv run pytest tests/`。`src/` 采用 Ruff 严格规则；配置以 `pyproject.toml`、`ruff.toml` 为准。
- 前端在 `web/`：`npm ci --prefix web`，运行该目录的 `typecheck`、`lint`、`test`、`build`。Zotero 插件使用 `zotero/` 自身工具链；其宿主测试需要真实 Zotero。
- 解析唯一实现为 `latex/gullet/` 与 `latex/segmenter/`；共同管线策略放 `pipecore/`，避免 worker、CLI 和 bench 复制实现。
- `bench/py/kernel/` 与纯 stdlib 动词可使用系统 Python；引用产品包的 spec 使用 `uv run python bench/py/bench …`。
- `bench/fixtures/*.tex` 字节即测试语义，禁止格式化或润色。语料 manifest 不随意改写；付费译文与实验载荷在仓外 `TEXLATE_BENCH_ROOT`，不作为可重建垃圾清理。
- 写注释、命名和改持久格式前读 [贡献约定](docs/dev/conventions.md) 与 [冻结格式登记](docs/spec/glossary.md)。
- 仅暂存明确路径；保留无关工作树改动，不使用整树 stash 或私有 index 提交。提交使用英文 Conventional Commits。

## 文档与决策

统一采用 `.agents/skills/` 的 `maintain-docs`、`maintain-prose`、`maintain-decision-notes`。区域规则见 [docs/AGENTS.md](docs/AGENTS.md)，文档契约见 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。

当前行为归 `docs/spec/`，用户操作归 `docs/guide/`，开发操作归 `docs/dev/`，实验证据归 `docs/research/`，长期理由归 `.agents/notes/`。每项事实维护一个归属，变更时修复链接和代码注释。文档与实现冲突时先核对代码和测试；不得把拟议行为写成已实现。

根指令仅保存持续需要的规则和入口，不维护包树、测试计数、历史里程碑或任务流水。维护材料来源与许可见 [.agents/README.md](.agents/README.md)。

## 工具链

安装入口为 `npm ci`、`pre-commit install --hook-type pre-commit --hook-type pre-push`；系统工具依赖与操作见 [开发手册](docs/dev/development.md)。

提交使用既有 git-format-staged 链；Markdown 使用 markdownlint、显示宽度表格对齐、Python 栅栏 Ruff 与 AutoCorrect，不使用 Prettier。Python 字符串不经过 AutoCorrect。Shell 使用 shfmt/shellcheck，zsh 原样透传；YAML 使用 Prettier 和注释宽度检查；TOML 使用 taplo。具体配置由根配置文件维护。

`uv run --no-sync python scripts/run_checks.py --config scripts/checks.json --mode ci` 检查维护契约与行为测试。产品验证仍按现有 CI 执行；维护检查通过不证明产品正确。

## 本机入口

`AGENTS.md` 与 `.agents/` 为入库事实源。`bash scripts/agent-links.sh` 创建被忽略的 `.claude/skills -> ../.agents/skills`，清理旧版 `CLAUDE.md` 软链；不覆盖外来实体。`.zcode/`、`.crossnote/` 和 `tmp/` 均为本机层。
