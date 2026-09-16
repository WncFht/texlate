# live-smoke 真链路活烟 — PASS

> 2026-09-16，live-smoke agent。真实服务 + 真实网关 + 真实 arXiv 取源，一篇论文全链路 `queued → done`，六件产物齐备，zh.pdf 为可抽中文的 19 页成品。端到端 **168.2s**。

## 环境

- 服务：`uv run texlate web --host 127.0.0.1 --port 8791`（8765 被另一会话实例占用），`TEXLATE_DATA_DIR=tmp/live-smoke-data` 隔离真实数据
- BYOK：`PUT /api/settings` 写入网关+key+model；`POST /api/settings/test` 探活 `ok:true`，swe-2-medium 在列
- `/api/health`：tectonic=true、xelatex=true、babeldoc=false（PDF 上传路 501，本次不涉及）
- 论文：`0707.0110`（corpus_v3 已物化小篇；revtex4 单文件 Artikel.tex 1401 行，latin-1，EPS 图）

## 时间线

| 阶段 | 耗时 |
| --- | --- |
| 提交 → 202 `t_6cc3d2948f12bb38` `cache:miss` | 13:57:35 |
| fetching | 3.8s（真从 arXiv 拉） |
| parsing | 0.9s |
| translating | 150.4s（96 chunks，concurrency=3，**0 failed**） |
| compiling | 13.1s |
| 合计 | **168.2s**（与 done.stats.seconds 一致） |

## 事件序列

`snapshot → stage:fetching×2 → stage:parsing → log×3 → stage:translating → chunk×48（全 ok）→ stage:compiling → log×4 → done`。关键 log：`route: eps_files → xelatex 优先（tectonic xdvipdfmx 硬墙）`、`normalize: latin-1→utf-8 rewritten=1`、`inject: ctex line 27`、`tounicode: 3 个 GB1 字体补 cmap`、`verdict: clean errs=0`。

## 产物（sha256 全部自验通过）

| kind | bytes | 说明 |
| --- | --- | --- |
| src_tar | 122,914 | e-print 原包 |
| zh_src_zip | 140,150 | 注入后中文工程 |
| en_pdf | 229,643 | 18 页 |
| zh_pdf | 654,465 | 19 页，pdftotext 抽出流畅中文（标题/摘要/章节全译） |
| dual_json | 122,902 | alignment=landmarks，129 entries |
| compile_log | 37,834 | xelatex 全日志 |

`GET /api/task/{id}/reader` → `view:pdf`、双侧 documents 齐。server.log 全程仅 INFO，无 warning/error，key 未泄入日志。

## 发现的问题

1. **tokens 口径不一致（服务端 cosmetic bug）**：终态快照 `counters.tokens=15499`（`tasks.tokens` 列 = 翻译期字符估算累计）vs done 事件 `stats.tokens=67344`（真账 prompt+completion）。`worker.py:1504` teardown 把真账写 `task_usage` 表并改 `ctx.tokens_est`，但 `tasks.tokens` 列此后再无回写——走快照的 UI 恒低估约 4.3×。修法建议：teardown 后补 `update_fields(tokens=)` 或快照改读 task_usage。
2. natbib undefined citations endnote23–26：revtex endnote 单遍编译已知现象，非管线缺陷。
3. font substitution 警告（`TU/ppl`、rsfs 尺寸）：xelatex+ctex 常态，verdict 判 clean 合理。
4. `file` 误报 zh.pdf "4 page(s)"，pdfinfo 实 19——`file` 解析器问题，非产物问题。

## 现场

- `bench/results/live-smoke-2026-09-16/`：`server.log`、`sse.log`（完整事件流 seq 0–63）、`poll.log`、`artifacts/`（六件产物原件）
- 任务工作目录 `tmp/live-smoke-data/tasks/t_6cc3d2948f12bb38/` 完整保留（base/zh/build-*/src 可复查）
- 服务与轮询已停（端口 8791 已释放）
