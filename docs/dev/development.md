# 开发与验证

Python 产品代码位于 `src/texlate/`，浏览器前端位于 `web/`，Zotero 插件位于 `zotero/`，评测机制位于 `bench/`。职责关系见 [架构](../spec/architecture.md)，用户命令见 [CLI](../guide/cli.md)。

## 安装

需要 Python 3.12+、uv、Node 22+ 和 Git。在仓库根执行：

```sh
uv sync
npm ci
bash scripts/agent-links.sh
pre-commit install --hook-type pre-commit --hook-type pre-push
```

根 npm 依赖负责格式和 lint。安装钩子前准备 pre-commit、AutoCorrect、Ruff、shfmt、shellcheck、actionlint、taplo 与 gitleaks；本仓 Python 开发依赖由 uv 管理，外部工具按本机包管理器安装。配置文件与 CI 定义检查行为和版本，避免另建一份版本表。

产品编译需要 tectonic 或带中文支持的 XeLaTeX；用户安装入口为 `uv run texlate tools install-tectonic`。`uv run texlate doctor` 检查实际环境，缺失的可选件只影响相应路径。

源码服务不携带已构建的 SPA；需要浏览器界面时执行 `bash scripts/build-web.sh`。只使用 API 或 `run --server` 时可不构建前端。

## 选择验证

| 改动            | 验证入口                                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------------------------- |
| Python 产品行为 | `uv run pytest tests/` 或所属测试目录；`ruff format --check .` 与 `ruff check .`                            |
| 类型契约        | `uvx ty@0.0.82 check src`；已有排除范围由 pyproject 管理                                                    |
| Web             | `npm ci --prefix web` 后运行该工程的 `typecheck`、`lint`、`test`、`build`                                   |
| Zotero          | `npm ci --prefix zotero` 后运行 `lint:check` 与 `build`；宿主测试见 `zotero/README.md`                      |
| 文档与维护机制  | `uv run --no-sync python scripts/run_checks.py --config scripts/checks.json --mode ci` 与 `npm run lint:md` |
| 配置            | 根 `npm run format:check`、YAML 注释检查和 actionlint；TOML 使用 taplo                                      |

`tests/fuzz/` 为额外的解析与边界回归。依赖语料、网络、Node 或 TeX 的测试会按环境选择；跳过不代表对应能力已验证。真实编译、浏览器和安装产物各有独立验证面，不能用单元测试替代。

## 格式与提交

提交钩子对暂存内容运行 formatter；Markdown 原地修复后可能需要重新暂存。Markdown 不经 Prettier，表格按显示宽度对齐，Python 字符串不经 AutoCorrect。不要格式化 `bench/fixtures/` 或实验生成数据。

维护契约钩子导出完整 index 快照，防止未暂存修复掩盖提交中的断链。推送钩子运行维护工具测试，产品全量与跨平台检查由 CI 承担。只暂存任务相关路径；格式修复、功能变更与无关工作树内容分开。

## 诊断

`scripts/server-smoke.sh` 验证 HTTP、SSE 和产物摘要；`scripts/dev-smoke.sh` 验证前端实际服务。运行前读脚本参数，使用隔离数据目录和本次创建的进程，退出时只清理自己拥有的资源。

日志由 `logsetup.py` 统一脱敏与装配。编译错误从文件栈和首错定位；进程无进展时可用 `scripts/pyspy-triage.sh` 对照多次调用栈与 CPU 变化。固定调用栈加 CPU 增长提示计算循环，固定调用栈无 CPU 增长更接近等待，仍需结合实际调用判断。

本机预览与诊断工具不是产品运行依赖。完整工具用途见 `tools/README.md`；模块和 CLI 的最新清单直接查询源码、help 与生成 API，不再维护平行目录大全。
