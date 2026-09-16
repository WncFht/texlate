# upload docx/epub 501 → export_document 通路：worker.py 补丁 + 契约

> 交付：本文件（契约说明）+ `tmp/upload501-worker.patch`（`git apply` 直接可用，已对**含 babeldoc-sidecar 改写的当前 worker.py** 验证 `git apply --check` 通过）+ `tmp/worker_patched.py`（应用后全文）+ `tmp/check_run_doc.py`（独立加载验证脚本，实测 done/fault 两路全绿）。
>
> **注意**：worker.py 正被 babeldoc-sidecar / worker-l2 活跃编辑——若 patch 落时第 3 个 hunk 撞车，锚点是 `_run_pdf` 收尾的 `bus.publish(...done...)` 块与 `# ---- translator` 分节头之间，把 `_run_doc` 整段插到 translator 分节之前即可。当前树上 `_run_pdf` 自带 2 个 ruff 复杂度告警（C901/PLR0912，babeldoc agent 在修的段），与本补丁无关——`_run_doc` 自身 check/format 全净。

## 背景

`POST /api/upload` 的 docx/epub 魔数路由此前一律 501（"M2 之前不可用"）。`src/texlate/export/` 已落地 `export_document(src, dst, translator)`：内容嗅探分派 epub/docx → `XlatPipeline` 全编排（`[n]` 批协议 + retry 阶梯 + `StateStore` 断点），产物是原文段落后跟译文的**双语同构文档**——不是 tex 转换，与 `_run_tex` 是不同管线。

## app.py 已落（本 agent 文件归属内）

- `_check_upload_route` 删除 docx/epub 501 块：路由放行，任务以 `kind="docx"|"epub"` 建行入队（复用既有 upload handler：blob → `tasks/{id}/upload/{safe_name}`，quota/CORS/auth/idempotency 全走老路）。
- `_MEDIA` 新增 `"zh.docx"`/`"zh.epub"` 两个 URL kind 的 media type。
- `tests/test_server_api.py::test_docx_501` → `test_docx_202`（旧 501 断言已与新行为冲突，最小改动）。

## worker.py 补丁内容（3 处）

1. `KIND_URL` 新增 `"zh_docx": "zh.docx"`、`"zh_epub": "zh.epub"`（URL_KIND 反查自动获得）。
2. `run()` dispatch：`elif ctx.row["kind"] in ("docx", "epub"): await self._run_doc(ctx)`，夹在 `upload_pdf` 与 `_run_tex` 兜底之间。
3. 新增 `_run_doc` 方法（置于 `_run_pdf` 之后、`# translator` 分节之前）。

## 契约要点（为什么这么写）

- **`export_document` 内部 `asyncio.run(XlatPipeline)`**——主 loop 直调即 RuntimeError，必须 `asyncio.to_thread` 起独立线程 loop。`on_result` 回调在 thread 内触发，所有 `bus.publish`/`store` 写都走 `self._on_loop` 回弹 loop 线程（单写者纪律不破）。
- **ChatClient 生命周期**：translator 由 `self._make_translator(ctx)` 在 loop 线程构造，但 client 的实际 I/O 发生在 to_thread 的 ephemeral loop 里；`finally` 里 `await client.aclose()` 是尽力而为（包 try/except，跨 loop 的 anyio 资源可能拒绝 close——只降级为 debug log，不炸任务）。
- **错误映射**：`ExportError` 族（DrmError/FixedLayoutError/MalformedEpubError/UnsupportedFormatError）→ `fault(unsupported_format, retryable=False)`；translator 抛的 `ChatError/AuthError/RetryableHTTPError` 自然穿透到 `run()` 既有 provider_* 映射。export 侧 `except BaseException` 会先写一本半成品双语书再上抛——半成品不落 files 表，retry 走 `export-state/` 断点续跑。
- **断点**：`state_dir=tasks/{id}/export-state/` 持久于任务目录，`StateStore` 的 job_id 前缀校验让 retry/resume 免疫书内容漂移（漂移即拒续重翻——export 语义自带）。
- **终态**：`report.skipped + report.fault == 0` → `done`；否则 `partial` + error_json（fault 存在时 `provider_error` retryable，纯 skipped 时 `validate` 非 retryable）——与 `_stage_compile` 的 done/partial 口径一致。
- **SSE**：`chunk` 事件按 unit 发 `{done, total:0, failed, items:[{seq,status}]}`——units 总数在 export 内部枚举，事前不可知，前端对 total=0 应有兜底（或忽略 total 只画 done）。终态 `update_fields` 回填 `total/done/failed_chunks` 真值。
- **产物**：原 blob 登记 `src_tar`（与 `_fetch_upload` 同款 provenance + 配额计字节）；双语书登记 `zh_docx`/`zh_epub`（dst 名 = `{src.stem}_bilingual{.docx|.epub}`，后缀缺失时按 kind 兜底）。无 dual.json——`GET /api/task/{id}/reader` 对 doc 任务仍 404，前端拿到 done 事件 artifacts 里的 `zh.docx`/`zh.epub` 走下载，不进 PDF 阅读器视图。
- **cancel**：`task_cancel` cancel asyncio task → `await to_thread` 抛 CancelledError，`run()` 收敛；**thread 内 export 不可杀**——孤儿线程会跑完并在磁盘留 dst/state_dir，但状态已 cancelled 不会被覆盖（`_current_status` 终态检查挡住）。与既有 to_thread 段同语义。

## 验证

- `tmp/check_run_doc.py`：importlib 独立加载 patched 模块（不碰真 worker.py），fake `texlate.export.export_document`——docx→done + `zh_docx` 登记 + counters 回填；DrmError→fault `unsupported_format` retryable=false。实测输出 `ALL OK`。
- 补丁后 `uv run ruff check`/`format --check` 净。
- `tests/test_server_upload.py`：路由层 6 例全绿；`TestDocPipeline` 3 例（docx done/epub done/Drm fault）以 `hasattr(PipelineWorker, "_run_doc")` 为闸休眠——补丁应用后自动激活，预期全绿。

## 未覆盖（后续项，非本补丁范围）

- `docs/research/product/web-layer.md` §2.4 表仍写 "docx/epub M2 之前 501"、§2.2 kind enum 缺 `docx|epub`、§2.3 文件表缺 `zh.docx/zh.epub`——规格文档待同步。
- reader 视图不支持 doc 任务（404 by design）；如需预览层另开题。
- `on_result` 的 `total:0` 是粗粒度妥协——要在 SSE 给真 total 需 export 侧暴露 units 计数回调（export 包改动，超出本补丁）。
