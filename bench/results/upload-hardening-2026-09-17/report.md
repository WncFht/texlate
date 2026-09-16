# upload-hardening — share-audit 两条残余修复交付

> 2026-09-17。scope：app.py（_parse_multipart + share_import）+ 两个测试文件。111 相关测试绿、ruff 净。

## 修复内容

**1. `_parse_multipart` 413 旁路**（`src/texlate/server/app.py:177`）

Content-Length 缺席（chunked/HTTP2）时预检失效、`val.read()` 全量进 RAM 的问题已堵：文件字段改有界读 `val.read(UPLOAD_CAP + 1 - file_bytes)`，**累计**文件字节超 `UPLOAD_CAP` 即抛 `_ApiError(413, upload_too_large)`——与端点既有 413 同 body 同 code。累计口径比逐字段更严：多文件字段合计超限也拒（与 CL 预检「总量约束」意图一致），单字段语义不变。文本字段按 brief 放小量。两端点 handler 的 `len(data) > UPLOAD_CAP` 检查保留为兜底。

**2. `share_import` 孤儿 task 目录**（`src/texlate/server/app.py:861-923`）

原两段 try 合并为单 region（mkdir → write_bytes → unpack → 校验 → 建行/入队全覆盖），except 序：`ShareError`→400、`sqlite3.IntegrityError`→409 duplicate_active、`Exception`→`rmtree(tdir)`+重抛——照抄 upload 端点 B4 口径。`_ApiError` 经 `except Exception` 统一收现场后原样重抛（原 `except _ApiError` 语义保留）；非预期异常（sqlite3.OperationalError 等）从「500+孤儿目录」变「500+现场收净」。顺手把 `mkdir`/`write_bytes` 也圈进守卫区（原先其失败同样留孤儿，零成本覆盖）。

已知边界（未改，供知晓）：`request.form()` 本身对 chunked 大文件仍会把完整体 spool 到 /tmp 临时盘（Starlette 内部行为），有界读只保证 RAM 不爆；堵盘侧需自实现流式计数解析，超出本次处方范围。

## 改动文件

- `src/texlate/server/app.py` — `_parse_multipart` 有界读 + `share_import` 单守卫 try
- `tests/test_app_endpoints.py` — `test_chunked_no_content_length_oversize_413`（parametrize 覆盖 /api/upload 与 /api/share/import；`content=iter([...])` 走 httpx chunked 实无 CL 头）+ `test_chunked_small_upload_accepted`（限额内 chunked 正路径不受影响）
- `tests/test_share_apply.py` — 新 `TestShareImportCleanup.test_import_mid_error_no_orphan_dir`：monkeypatch `store.create_task` 抛 `sqlite3.OperationalError` → 断言 500 且 `tasks/` 无残留目录

## 验证

- `uv run pytest tests/ -k "share or upload or app"` — **266 passed**
- `ruff check` + `ruff format --check` 三文件全净（其间修掉 TRY003/EM101 与一处 format 折行）

零接触 share.py/worker.py；与 share-wire 在飞区域无交集（本代理只动 app.py + 两个 tests 文件）。
