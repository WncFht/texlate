# babeldoc-e2e：upload_pdf → BabelDOC sidecar 真链路 e2e（2026-09-16）

结论：**这条路此前从未真正跑通过**——4 个 spawn 契约 bug 每个都独立致败，已全部修复并逐轮复验到 partial 终态。

## 环境

- `uv tool install babeldoc==0.6.4` → `~/.local/bin/babeldoc`（调研钉版 0.6.4；`bench/py/.venv_babeldoc` 是 Mac 残留、shebang 已失效）
- `TEXLATE_DATA_DIR=tmp/babeldoc-e2e-data uv run texlate web --port 8795`；settings 写 base_url=http://100.105.212.52:3003 + key + swe-2-medium；输入 = 15 页 Adam PDF（534KB）
- 运行史：run1 fault(argparse) → run2 fault(192/384 段 404) → run3-6 全绿 partial

## 修复的 bug（全部 src/texlate/server/babeldoc.py + worker.py 一处）

1. **babeldoc.py:167 write_config TOML key 写下划线 `openai_api_key`** —— configargparse TomlConfigParser 把 key 字面转成 `--openai_api_key=…`，与注册的 `--openai-api-key` 不匹配 → `unrecognized arguments` 直接拒跑。**upload_pdf 通路 100% 致败**。改 `openai-api-key`。
2. **babeldoc.py:211 `--openai-base-url` 缺 `/v1`** —— job.base_url 是 texlate 归一化裸根，但 babeldoc 直接喂 `openai.OpenAI(base_url=…)`，SDK 拼 `chat/completions` → 打 `/chat/completions` 被网关 404，半数段错→judge `failed/babeldoc_translate`。新增 `_openai_sdk_root()`（babeldoc.py:174）剥已知后缀再补 `/v1`，对齐 ChatClient 约定。
3. **`_spawn` stdout=DEVNULL 丢掉了 babeldoc 全部真实输出** —— rich Progress 和 RichHandler 日志都写 **stdout**（main.py:809 `Progress()` 无 console 参 + basicConfig RichHandler 默认 stdout）。stderr 上只有 Python warnings。后果：进度卡 30、`Total tokens:` 等统计行全丢、stage 行全丢。改 stdout+stderr 合并进同一 pty；PIPE 退化期 `stdout=STDOUT` 并入。
4. **pty winsize 0×0 → rich 窄宽渲染把 `52/100` 截成 `52/…`** —— `_OVERALL_RE` 永不命中，且每帧重绘行漏进 on_log（单次任务 400+ 条重复 SSE log）。spawn 前 `TIOCSWINSZ` 钉 24×120（babeldoc.py:~570）。
5. **`_ANSI_RE` 不剥 OSC-8 超链接转义** —— RichHandler 的 `\x1b]8;id=…\x1b\\` file-link 残留在每条日志尾。扩 `_ANSI_RE` 加 OSC 分支（babeldoc.py:69）。
6. **worker.py `_finish_pdf` token 不落账** —— `ctx.tokens_est` 只在内存，`tasks.tokens` 列与 `task_usage` 表恒 0（主链在 worker.py:1614/2830 都落）。补 `update_fields(tokens=…)` + `record_usage(model, calls=0, prompt, completion, latency)`（worker.py:2524-2534，babeldoc 不报调用次数）。

## 验证点（全过）

- BYOK 凭证链：settings → Secrets → TOML-only（0600，pgrep 实测 argv 无 key、无 `--max-pages-per-part`）
- `--working-dir` → `translate_tracking.json` 落盘 `<workdir>/adam-main/`（1.2MB/193 段）
- 产物收割：`*.no_watermark.zh-CN.{mono,dual}.pdf` → zh.pdf/dual.pdf + en.pdf + dual.json 登记
- **失败面也真验了**：run2 网关 404 → 192/384 段 error → `failed/babeldoc_translate` + error_sample 上抛，过半阈值判定正确
- degraded→partial：references 作者列表段 "same as input" fallback（1 err/1 fb）——babeldoc 同文质量门正常
- zero_tokens 闸不误伤：全 cache 命中 run（total_tokens=0 但 tracking total=193）正确放行
- 进度：30→64→77→100（translate N/100 刮到）；token 统计 total/prompt/completion/cache_hit/peak_memory 全采集；任务行 tokens=1425 + task_usage 行落账
- zh.pdf：15 页 CJK 0.378，正文真中文（"我们提出了Adam，这是一种针对随机目标函数的一阶梯度优化算法…"）
- 日志面：OSC 修复后 70 事件/单（修复前 1330，其中 400+ 是重复进度帧）
- `pytest tests/test_server_babeldoc.py tests/test_server_worker.py` 37 绿；ruff format+check 绿（改了两个测试断言：TOML key 形 + base_url /v1）

## 残留/备注

- babeldoc 内嵌 ToUnicode 含奇数长 hex dst（非 BMP 码点如 `1f100` 写成裸码点而非代理对）→ pypdf "Skipping broken line"，稀有字符抽取失败。上游问题，我们的 GB1 cmap 无此问题（且未注入——babeldoc 字体自带 ToUnicode）
- `Translation completed. Total/Successful/Fallback` 行仍被 Live 收尾重绘切碎（`_COMPLETED_RE` 不命中）——tracking json 已覆盖该统计，低价值
- SSE 端点是 `GET /api/task/{id}` + `Accept: text/event-stream`（`events_url` 字段误导性地就叫 `/api/task/{id}`，无 `/events` 路径）
- 15 页耗时：冷 510s / 热 ~30-56s（babeldoc SQLite cache 有效）
- 现场件齐：`bench/results/babeldoc-e2e-2026-09-16/`（input.pdf、4 产物、tracking.json、babeldoc.toml、glossary head、SSE×6、task events/row/usage、server.log）
