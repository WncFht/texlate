# 贡献指南

## 环境

```bash
git clone https://github.com/WncFht/texlate && cd texlate
uv sync                        # Python 侧全量（含 dev group：pytest/ruff/ty）
npm ci                         # md/js/yaml/toml 工具链（版本事实源 = package.json）
npm ci --prefix web            # SPA 前端（要动 web/ 才需要）
npm ci --prefix zotero         # Zotero 插件（要动 zotero/ 才需要）
pre-commit install             # 提交钩子：formatter 走 git-format-staged，check 类拦截
```

pre-commit 前置工具：`ruff shfmt shellcheck actionlint taplo gitleaks`（Linux 各发行版同名包或 `cargo install`/`go install`；macOS 走 brew）。**本地不过的检查 CI 必挂**——CI 与本仓钩子完全同源。

## 验证（提交前）

```bash
uv run pytest tests/ -q              # 测试（干净 clone 全绿是基线）
ruff format --check . && ruff check .   # src/** 是 select=ALL 严格集
npm run format:check                 # prettier
npm run lint:md                      # markdownlint（MD060 按显示宽度对齐，CJK=2）
npm run lint:js                      # eslint
python3 tools/docs_linkcheck.py      # docs/ 死链 + 未登记闸
```

改了 web/ 或 zotero/ 再加各自 `npm run typecheck && npm run lint && npm run test`（zotero 是 `lint:check + build`）。

## 仓库地图

- `src/texlate/` — 产品包，按层分包（`latex/` 半解析、`xlat/` 翻译、`compile/` 引擎+fixloop、`server/` Web、`cli/` 命令行）
- `docs/` — 六分区文档库：**用户改动检查 `guide/` 是否要更新；实现细节事实源在 `spec/`；结构性决定写 ADR 进 `decisions/`**；维护规则见 `docs/MAINTENANCE.md`
- `docs/dev/repository.md` — 全仓现状基线（模块职责逐文件核实版），动目录结构后同步它
- `tests/` — pytest，`tests/conftest.py` 有全部共享 fixture；新 server 依赖的测试文件无需额外登记
- `bench/` — 评测 harness；语料与产物在仓外 `$TEXLATE_BENCH_ROOT`，勿提交大文件

## 提交约定

- Conventional Commits：`type(scope): 主题`——type/scope 用英文，正文用中文，一个提交一个逻辑变更。
- `style:` 提交只装格式化产出，不混功能改动。
- 文档与代码注释跟随仓库现有语言（中文）。
- 不要提交真实 API key、内网地址、token——gitleaks 钩子会拦，拦不住的 review 也会拦。

## PR 要求

- CI 全绿（format / secrets / python / ty / shell / pytest ubuntu+windows / fuzz / web / zotero / engine 冒烟）。
- Windows 兼容是硬约束：新增文件/目录名避开 `CON PRN AUX NUL COM1-9 LPT1-9` 保留名；进程/信号/fcntl 语义要 `sys.platform` 门控降级（windows CI leg 真跑测试套件，红了按发现修，不许 skip）。
- 发行版本号只由 maintainer 在 release 时动（pyproject `version` + `zotero/package.json` + tag 三方一致，`release.yml` 有断言）。

## 报告 bug / 提需求

- Bug 与功能走 issue 模板；安全问题走 [私密 advisory](https://github.com/WncFht/texlate/security/advisories/new)（见 SECURITY.md）。
