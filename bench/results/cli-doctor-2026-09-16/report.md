# `texlate doctor` 环境自检子命令

2026-09-16。新增 `texlate doctor`：逐项 `ok`/`warn`/`fail`/`n/a` + 一行说明，任一 fail → 退出码 1，全 ok/warn/n-a → 0。改动全部在 `src/texlate/cli.py`（文件尾 doctor 段，约 L985–1290）+ 新增 `tests/test_cli_doctor.py`（17 测）。

## 检查项与判定口径

| 检查 | 探测方式 | fail 条件 |
| --- | --- | --- |
| python | `sys.version_info[:2] >= (3,12)` | <3.12 |
| tectonic | `toolchain.resolve_tool`（PATH→macOS 落点→托管件，与 `/api/health` 同函数）+ `--version` 首行 | 双引擎全缺才 fail |
| xelatex | `find_tool` + `--version` 首行 | 同上（单缺 warn） |
| cjk-fonts | `kpsewhich ctex.sty` + `kpsewhich FandolSong-Regular.otf` + `fc-list :lang=zh` | 永不 fail：双探测器缺席 → n/a；fandol 或系统 zh 确认 → ok；可探但全空 → warn |
| pdftotext | `find_tool` + `-v` 首行 | 永不 fail：缺席 warn（judge 降级 log 判据） |
| gateway | settings.json（`SettingsStore.load`）+ env 兜底（与 `resolve_auth` 同序）→ `GET {base}/v1/models` 5s | 传输层错误 fail；2xx ok；401/403 warn；未配置 n/a |
| data-dir | `TEXLATE_DATA_DIR` > `~/.texlate`：mkdir(0700) + 试写删 | OSError → fail |
| server-extra | `find_spec("fastapi"/"uvicorn")` | 永不 fail：缺 → warn + `texlate[server]` 提示 |
| babeldoc | `find_tool` + `--version` | 永不 fail：缺席 n/a（可选件） |

## 两处与任务书的偏差

- 网关探活端点用 `{base}/v1/models`（非 `{base}/models`）：`xlat/client.py:646` `list_models` 走的就是 `/v1/models`，`normalize_base_url` 会剥掉用户配置里的 `/v1` 尾巴再拼——`/models` 在真实 OpenAI 兼容网关上必 404。
- 引擎缺席分级：单缺记 warn（auto 路由还有另一腿），双缺才 fail——与 `engine=auto` 的真实可用性对齐。

## 实现要点

- 探测子进程统一走 `_doc_run`（15s 上限，异常/超时归一 None——doctor 只报告不炸）；argv[0] 恒为 `find_tool` 绝对路径。
- 版本行 stdout 优先 stderr 兜底取首个非空行；tectonic 0.15 `--version` 把 `tectonic 0.15.0`+`Tectonic 0.15.0` 无分隔打进同一行，semver 后紧跟大写粘连段即截断。
- gateway 检查懒 import `texlate.server.settings`（`texlate.server.__init__` 是 PEP 562 延迟面，无 server extra 也可 import）；key 只进 `Authorization` 头，绝不进输出（测试有断言钉住）。
- `resolve_tool`/`find_tool`/`find_managed` 复用 `compile.toolchain`/`compile.sandbox`——与 `/api/health`（app.py:715-727）同一探测面，未重写。

## 验证

- `uv run pytest tests/test_cli_doctor.py` — 17 测全绿：各检查三态、退出码语义、`--help`、网关 200/401/unreachable/env-only 配置面、key 不外泄断言。
- `uv run ruff check` + `format` — 净。
- 全 CLI 回归（test_cli*.py + test_share_cli.py）54 绿。

## 本机实跑（exit 0）

```text
ok   python       3.12.13（≥3.12）
ok   tectonic     tectonic 0.15.0（系统件 /home/fanghaotian/.local/bin/tectonic）
ok   xelatex      XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026/Arch Linux) @ /usr/bin/xelatex
ok   cjk-fonts    ctex、fandol、sys-zh
ok   pdftotext    pdftotext version 26.08.0 @ /usr/bin/pdftotext
ok   gateway      GET http://100.105.212.52:3003/v1/models → 200，214 models
ok   data-dir     /home/fanghaotian/.texlate 可写
ok   server-extra fastapi/uvicorn 可 import
n/a  babeldoc     可选件缺席——PDF 降级通路不可用（pipx install babeldoc）
—— 8 ok / 0 warn / 0 fail / 1 n/a（9 项）
```
