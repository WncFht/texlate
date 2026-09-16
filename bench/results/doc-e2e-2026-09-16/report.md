# doc-e2e：server 编排层 doc 管线真链路验证（2026-09-16）

`POST /api/upload`（epub/docx）→ worker `_run_doc` → 双语产物下载的全链路实跑。export 库层已由 `export-verify-2026-09-16` 验证（12 文件全绿），本报告覆盖 server 编排面：路由/建行/入队/worker 分派/产物登记/SSE/下载/边缘错误面。

## 环境

- 实例 A（mock）：`TEXLATE_DATA_DIR=tmp/doc-e2e-data TEXLATE_TRANSLATOR=mock uv run texlate web --port 8793`（`server.log`）
- 实例 B（真网关）：`TEXLATE_DATA_DIR=tmp/doc-e2e-data2 uv run texlate web --port 8794`（无 mock env；`PUT /api/settings` 写 `base_url=http://100.105.212.52:3003` + Bearer，`server-gw.log`）。上量前 gwcap `inflight:0/queued:0`
- 输入：`tmp/refs/bilingual_book_maker/test_books/lemo.epub`（148486B，青空文库『檸檬』日文）+ `bench/results/stagerun-loop1-2026-09-16/work/2009.11007/src/Response_letter_final.docx`（14847B）

## 编排约定（读码确认）

`app.py:670` `POST /api/upload`：multipart `file` 必填；`Content-Length > UPLOAD_CAP(80MiB)+64KiB` 预检 413 不读体（`app.py:139`）；payload 复检 `app.py:680`。魔数路由 `sniff_upload`（`worker.py:762`）：`%PDF`→upload_pdf → `PK\x03\x04`→`_zip_kind`（`word/document.xml`→docx；mimetype=`application/epub+zip` 或含 `content.opf`→epub；否则 upload_tex）→ gzip/tar→upload_tex → UTF-8 文本→upload_tex → 否则 unknown→400。**魔数恒压扩展名**。blob 先落 `tasks/{new_id}/upload/`（`app.py:693-696`）再 `_create_and_enqueue`（幂等/dedup 在建行前）——B4 孤儿目录根因位置。

worker 分派 `worker.py:1149-1152`：`docx|epub`→`_run_doc`（`:2465`）→ 登记 `src_tar`（`:2488`）→ `asyncio.to_thread(export_document)`（export 内部 `asyncio.run(XlatPipeline)`，必须独立 loop）→ 登记 `zh_{kind}` → `skipped+fault==0`→done 否则 partial。translator 工厂（`:2554` `_make_translator`）：`translator_factory` > `TEXLATE_TRANSLATOR=mock` > `=gateway` 或有 api_key → ChatClient+GatewayTranslator > 兜底 MockTranslator。

产物 URL 面（`KIND_URL` `worker.py:154`）：`zh_epub`→`zh.epub`（`application/epub+zip`）、`zh_docx`→`zh.docx`（OOXML mime）、`src_tar`→`src.tar`（`application/gzip`）。

## 时间线

| 时刻 | 事件 |
|---|---|
| T+0 | :8793 起服务（mock），/api/health ok（babeldoc 缺，仅影响 upload_pdf 路由） |
| T+0 | POST lemo.epub → 202 `t_f07192f77c5b4343` kind=epub |
| T+0.2s | done（45u；stats.seconds=0.2 tokens=2625） |
| T+107s | POST Response_letter_final.docx → `t_60d1b3ce5379a6fa` kind=docx → done（18u） |
| T+~5min | :8794 起服务（网关）→ PUT settings → POST lemo.epub → `t_394b309587b3eb55` → 61.6s done（真实中文译文落盘） |
| 边缘批 | 18 用例（`edge-cases.txt` 原文） |

## 产物校验矩阵

| 校验 | lemo.zh.epub(mock) | resp.zh.docx(mock) | lemo.gw.zh.epub(网关) |
|---|---|---|---|
| HTTP 链路 | 202→done→files→200 | 同 | 同（61.6s） |
| zip testzip | pass | pass | pass |
| mimetype 首条+STORED | pass | n/a | pass |
| 成员集合 == 源 | pass | pass | pass |
| 与 export-verify 产物成员级字节一致 | **16/16 一致** | **12/12 一致** | n/a（译文内容不同） |
| zh 节点数 | 2 body + 1 NCX（translated=3/unchanged=42，同库层口径） | 18 zh_paras / 18 SimSun run | 42 节点真实中文 |
| dup id / marker 泄漏 / nav li 塌 | 0/0/0 | n/a | 抽查 pass |
| dc:language=zh-CN / CSS 注入 | pass | n/a | — |
| src.tar 回读 == 上传字节 | sha256 一致 | — | sha256 一致 |

字节级一致性说明：服务端产物与 `export-verify` 同源产物逐成员 byte-identical，该批 12 项库层断言（adjacency/RSC-005/NCX 双串/sectPr 等）对服务端产物传递成立。mock 下 lemo 仅 3u translated：日文文本无拉丁 run，`_mock_translate_text` 原样返回→判 unchanged——与库层同口径，非缺陷。网关臂同书 42 zh 节点、译文真实中文，证明 ChatClient 在 `to_thread` ephemeral loop 内工作正常、`finally` 中 `aclose` 无残留错误（server-gw.log 无 error/warn/traceback）。

## SSE / 快照行为

- `GET /api/task/{id}` + `Accept: text/event-stream`：seq0 snapshot → `stage`(translating,25) → 45×`chunk`（`done` 递增，`total:0`——units 枚举在 export 内部、total 未知是设计内行为）→ `done`（artifacts+stats）。终态后重连可全量回放（`sse-lemo.log`/`sse-lemo-gw.log`）
- `?download=1`：`Content-Disposition: attachment; filename="texlate-{task_id}-zh.epub"` + 正确 mime

## 边缘用例（`edge-cases.txt`）

| # | 输入 | 结果 |
|---|---|---|
| E1 | epub 字节命名 `.txt` | routed **epub** → done（魔数压扩展名） |
| E2 | 文本命名 `.epub` | routed upload_tex → partial `route_reject: no main tex` |
| E3 | 随机二进制 | 400 `unsupported_format` |
| E4 | 空文件 | 400 `empty upload` |
| E5 | options 非 JSON | 400 |
| E6 | target_lang=fr | 400 白名单 |
| E7 | 缺 file 字段 | 400 |
| E8 | model 201 字符 | 400；`model="  "`（空白）被表单层吃掉后回退 `_auth` 默认 model |
| E9 | Idempotency-Key 重复 | 202 `cache:idempotent` 返回原 task_id ✅ + 孤儿目录复现（见 B4） |
| E10 | 81MiB | 413 `upload_too_large`（Content-Length 预检即时返回） |
| E11 | `?download=1` | attachment + `application/epub+zip` ✅ |
| E12 | `?version=bad` | 409 `version_mismatch` |
| E13 | retry done 任务 | 409 `invalid_transition` |
| E14 | docx 命名 `.epub` | routed **docx** → done |
| E15 | retry partial | 202 重入队 → 同 route_reject → partial（确定性） |
| E16 | DELETE done 任务 | 200 + 任务目录删除 |
| E17 | `options.idempotency_key` 表单字段 | 同 header 路 dedup ✅ + 第二个孤儿目录 |
| E18 | 伪造 docx（xml 垃圾） | fault `unsupported_format` retryable=false |

上传 `prefer="fresh"` + `cache_key=None`：同内容无 key 重复上传 = 各自建任务（fake.epub ×3 均独立 partial），无内容级 dedup——设计内。

## 发现的 bug / 缺口

1. **B4 孤儿目录复现 ×2**（已知，share-apply 修复中）：`app.py:693-696` 在 `_create_and_enqueue` 幂等查询（`:411-416`）**之前**写 `tasks/{new_id}/upload/`。命中即弃目录：实证 `t_fe6fc79667d93e2e`（header key）与 `t_4febdaf6b27d3369`（options key），各含 `upload/fake.epub`、无 DB 行。
2. **doc 任务无 reader 视图**：`GET /api/task/{id}/reader`（`app.py:856`）硬依赖 `dual.json`——doc 管线不产出 → 恒 404 `dual.json 未产出`。而 upload 202 响应仍发 `reader_url`（`app.py:186`）。**UI 上 docx/epub 任务点不进阅读器**——需 doc 专用 view（直接下载/嵌入）或在 `_accepted` 按 kind 省掉 reader_url。
3. **glossary 对 doc 管线静默丢弃**：`options.glossary` 正常入 config（`app.py:441`），但 `export_document` 签名（`export/__init__.py:109`）无 glossary 参、export 内 `XlatPipeline(translator, state=, on_result=)` 不传 glossary（`export/epub.py:973`、`docx.py:343`）→ 用户传了术语表 docx/epub 不生效且无提示。（修复中：doc-polish Phase A）
4. **进度/计数器运行期不可见**：`_run_doc` 只在入口 `_stage(translating,25)`（`worker.py:2489`），全程 progress 钉 25，DB counters 到 export 返回才 `update_fields`（`:2530`）。`export_document` 的 `on_result` 回调口存在（已接 chunk 事件）但没回写 store/progress——长书 UI 列表 0/0 不动、进度条 25% 定格；SSE chunk 事件有 done 计数但 `total:0`。网关臂 lemo 61.6s 全程如此。
5. **tokens 未持久化**：`_run_doc` 只累加内存 `ctx.tokens_est`（`worker.py:2503`），tex 路在 `:1538` 有 `update_fields(tokens=...)` 而 doc 路没有 → 终态后快照 `counters.tokens` 恒 0，与 done 事件 `stats.tokens`（2625/2288）不一致。
6. ~~**错误消息泄漏服务端绝对路径**~~（**已修 a8fafe9**）：E18 fault 消息曾含 `/home/fanghaotian/.../tasks/{id}/upload/fake.docx`（`export/docx.py:305` `f"不是可读 DOCX: {src}"` 直接拼 Path）。
7. **无 key 静默 Mock**：无 `TEXLATE_TRANSLATOR` 且无 api_key 时 `_make_translator` 兜底 `MockTranslator`（`worker.py:2589`）——生产部署忘配 key 会得到满篇「这是译文」的 done 任务、无 warning。docstring 明示属故意设计，建议 server 形态下无 key 直接 fault 或至少 warning。
8. **次要**：`src_tar` 以 `application/gzip` mime 提供 epub/docx 原文下载（`app.py:100` `_MEDIA`，字节正确但浏览器按 gzip 处理，另存联想 `.tar`）；`options.main` 表单字段被收进 options 但 doc 路不用（无害）。

## 残留风险

- **partial 终态未实测**：需「部分 unit fault/skipped」的书——mock 下造不出 fault（MockTranslator 不失败），网关臂 lemo 全绿。`_run_doc` 的 `provider_error/validate` 错误映射（`worker.py:2537-2548`）只经读码确认。
- **cancel 中断未实测**：doc 任务太快抢不到运行窗；`_check_cancelled` 在 export 返回后才执行，`to_thread` 内任务不可中断、等出口再判的时序面未验证。
- **大书/长时**：45u/424u 均秒级–分钟级；未测大 epub（如 animal_farm 510KB）在网关臂的时长/超时面。
- `export-state/` 断点续跑：成功后按文档自述被清理（data2 现场确认已清），retry 续跑未实测。

## 现场文件

`dl/`（4 个下载产物 + src.tar 响应头）、`sse-lemo.log`（mock 全事件流）、`sse-lemo-gw.log`（网关臂回放）、`upload-*.resp.json`、`files-*.json`、`snap-lemo.json`、`edge-cases.txt`（18 用例原文）、`server.log`/`server-gw.log`、本报告。数据目录现场：`tmp/doc-e2e-data{,2}/`（含 2 个孤儿任务目录实证）。
