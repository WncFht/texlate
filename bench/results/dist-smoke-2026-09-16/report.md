# dist-smoke：`uv tool install` 分发链验证（2026-09-16）

环境：uv 0.11.29，Python 3.12（tool venv），hatchling 打包，`--out-dir /tmp/texlate-{wheel,dist}`（不污染仓库根；仓库自带 `dist/` 目录且内含 `*` .gitignore，直接 `uv build` 也安全）。

## 结论速览

- wheel 构建正常（4.6M、355 项），SPA/cmaps/argspec/entry point 全部入包，`uv tool install` 后 `texlate version` / `--help` 可用。
- **发现并修复一个打包 bug**：sdist 无文件选择配置，默认把整棵工作树入包——`bench/results/` 未 gitignore 的 15.2 万文件、24G（含 3.78 万 PDF、2.18 万 .tex）全量拷贝，构建 14 分钟未完、残档 8.3G，且 `/tmp` 是 16G tmpfs，继续跑会打爆内存盘（已手工终止清理）。已在 `pyproject.toml` 加 sdist `include` 白名单，修复后 15s 出 4.6M 包。
- **推翻「sdist 缺 SPA」的预设**：`[tool.hatch.build] artifacts` 是全局档，对 sdist 同样生效——`server/static/` 263 个文件确在 sdist 内。从 sdist 直接 install 可拿到完整 SPA。
- 真正的 SPA 缺口在 `uv tool install git+...`：git clone 不含 gitignored 的 `static/`，构建出的 wheel 天然无 SPA（`app.py:965` 的 `static_dir.is_dir()` 守护下优雅降级为纯 API，web UI 404）。

## wheel 内容核对表（`texlate-0.1.0-py3-none-any.whl`）

| 检查项 | 结果 |
| --- | --- |
| `texlate/server/static/index.html` | OK（static/ 共 263 文件，含 assets/pdfjs/THIRD_PARTY_LICENSES.txt） |
| `texlate/server/cmaps/Adobe-GB1-UCS2` | OK |
| `texlate/latex/data/argspec.json` | OK |
| `entry_points.txt` → `texlate = texlate.cli:app` | OK |
| `__pycache__`/`*.pyc` 泄漏 | 0 |
| 顶层目录 | 仅 `texlate/`（351）+ dist-info（4），无越界文件 |

## sdist 修复

`pyproject.toml` 追加：

```toml
[tool.hatch.build.targets.sdist]
# 默认 sdist = 整棵工作树（bench/results 24G+ 全入包，构建不可行）——白名单收敛
include = ["/src", "/tests", "/README.md", "/pyproject.toml"]
```

理由：wheel 档已有 `packages=["src/texlate"]` 收敛，sdist 档此前裸奔；白名单取「包源码 + 测试 + 元数据自变量」的最小完备集（无 LICENSE 文件，license 内联声明）。修复后 sdist 内容：437 项 = `src/`（351，含 static/ 263 + cmaps + argspec.json）+ `tests/`（82）+ `pyproject.toml`/`README.md`/`PKG-INFO`，无 `.gitignore` 残留。

## 安装冒烟矩阵

| 来源 | 命令 | 结果 |
| --- | --- | --- |
| wheel | `uv tool install --python 3.12 texlate-0.1.0-py3-none-any.whl` | `texlate version` → `texlate 0.1.0`；`--help` 列出 version/fetch/parse/run/web/export/tools 全命令 |
| sdist | `uv tool install --python 3.12 texlate-0.1.0.tar.gz` | 同上；site-packages 内 `static/index.html`、`cmaps/Adobe-GB1-UCS2`、`argspec.json` 均落盘 |
| wheel + server extra | `uv tool install --python 3.12 'texlate-….whl[server]'` | fastapi 0.141.1 / uvicorn 0.53.0 / sse-starlette 3.4.11 可 import |

注：裸 wheel 安装（无 `[server]`）时 `texlate web --help` 正常（惰性 import），实际启动才需 extra——`texlate web` 帮助文本已写明「需 extra」，UX 自洽。建议安装文档写 `uv tool install 'texlate[server]'` 作为 web 形态标准命令。

## `git+` 安装路径的真实缺口与建议

`uv tool install git+https://…` 走 clone → 本地 build wheel；clone 里 `static/` 不存在（gitignore、未入库），`artifacts` 配置救不了不存在的文件 → 产出 wheel 无 SPA。运行时 `app.py:965` 判 `is_dir()` 跳过挂载，结果：API 全可用、浏览器根路径 404——对「uv tool install 出完整产品」的承诺是隐性残缺。

建议（按代价排序）：

1. **发版只发 wheel 为主路径**（现状即可）：文档明确 `uv tool install texlate[server]`（PyPI wheel）或 release 页 wheel URL；`git+` 标注为 CLI-only 开发者路径。零代码改动，推荐。
2. 若想 `git+` 也带 SPA：hatch build hook 在构建时探测并在缺失时跑 `scripts/build-web.sh`——把 npm 依赖塞进 Python 安装路径很脏，不推荐。
3. 折中：`static/` 入库（去 gitignore）——代价是仓库长期携带 8.8M 产物、build-web 后 diff 噪音；换「clone 即可完整安装」。

## 复现命令

```bash
uv build --wheel --out-dir /tmp/texlate-wheel      # 15s 内，4.6M
uv build --sdist --out-dir /tmp/texlate-dist       # 修复后 15s，4.6M；修复前 >14min 且写爆 tmpfs
uv tool install --python 3.12 /tmp/texlate-wheel/texlate-0.1.0-py3-none-any.whl
texlate version && texlate --help
```
