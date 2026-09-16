# doc 管线 polish — Phase B 报告（worker._run_doc 接线）

## 范围

`src/texlate/server/worker.py`（`_run_doc` + `_make_translator` 兜底）+ `tests/test_server_upload.py`（TestDocPipeline 新增 5 例）。`_stage_compile`/share 臂未碰。Phase A（export glossary 透传 + CLI `--glossary`）已先 commit（ac710a5）。

## 改动（worker.py）

1. **glossary 无条件透传**：`export_document(..., glossary=self._make_glossary(ctx), on_result=...)`（:2699）——与 tex 链 :1553、babeldoc :2496 同款裁决（leader 裁定：parity 优于 opt-in，doc_filter 逐词相关性闸保护非 CS 文本）。doc 任务无 `base/` → local 层自然 None；`options.glossary` 相对路径经 `_glossary_path` confine（任务 base/ + settings `glossary_dir` 双根）；无 options 时 `Glossary.load(local_path=None)` 仍返回带 default 层的 Glossary 实例。
2. **on_result 回弹**（`_doc_on_result` 工厂 :2762 + `_doc_emit` :2796）：逐 unit 计数 done/failed、`ctx.tokens_est += (len(src)+len(zh))//4` 字符估算、SSE `chunk` 事件（items 带 `error_code` via `chunk_error_code`，`_PIPE_TO_DB` 状态映射与 tex 路一致）；DB/事件写经 `_on_loop` 回弹单写者面。progress = `min(hi-1, lo+done)`（translating 区间 25–85 逐 unit 自增，终态 100 仍由 transition 写）——不再钉 25。
3. **tokens 持久化**：终态 `update_fields(..., tokens=ctx.tokens_est)`（:2729）；另 `_doc_persist_usage`（:2814）在 `finally` 段跑「有真账用真账」——usage_sink 接到 `_translator_clients(translator)` 的 ChatClient 上，有真账则 `tokens_est` 换真值 + `record_usage` 落表；ExportError/crash 早退也留已发调用的账。clients 收尾 `_aclose_clients` 尽力而为（顺带修复 `_FallbackTranslator` 备路 client 泄漏——审计批 item 8）。
4. **MockTranslator 兜底留痕**（:2870-2878）：无 `TEXLATE_TRANSLATOR=mock`、无 api_key、无 factory 落到 Mock 时 `_warning(ctx, "mock_translator", "未配置 API key——回退 MockTranslator，产出为占位译文而非真实翻译")`；`self._mock_warned: set[str]`（:1019）按 task_id 去重——`_make_translator` 有 4 个调用点（translate/env_judge/L2/doc），同一任务只警一次。

结构：`on_result` 闭包抽成 `_doc_on_result` 工厂后 `_run_doc` 语句数回落阈值内，原 `# noqa: C901` 已摘。

## 测试（tests/test_server_upload.py::TestDocPipeline +5 例，15 全绿）

| 用例 | 断言 |
|---|---|
| `test_glossary_kwarg_unconditional` | fake export 收到 `kw["glossary"]` 为 `Glossary` 实例且含 default 层词条（无条件传，非 None） |
| `test_glossary_reaches_prompt_real_path` | **prompt 直证真链路**：真 docx（python-docx 造，含 "transformer"）+ `options={"glossary":"g.yaml"}` + settings `glossary_dir` confine → 无 monkeypatch 走真 `export_document` → `MockTranslator.calls[*].system` 含 `- transformer: 变形金刚` |
| `test_on_result_counters_chunk_event_progress` | 快照面：`counters.done==1`、`counters.tokens==3`（(11+4)//4 估算持久化）、无 `usage` 键（Mock 无 client 不落账）；落盘事件 `chunk` 载荷精确 `{done:1,total:0,cached:0,failed:0,items:[{seq:1,status:ok}]}`；`update_fields` 探针录得 `progress==[26]`（离 25 自增） |
| `test_mock_fallback_warns` | 无 factory/key/env → warning 事件恰一条 `code=="mock_translator"`，任务仍 done |
| `test_explicit_mock_env_no_warning` | `TEXLATE_TRANSLATOR=mock` 显式 → 无 `mock_translator` 警告 |

## 验证

- `ruff check` + `format --check`：8 个触及文件（export/common|__init__|epub|docx、cli、worker、test_export_glossary、test_server_upload）全干净
- `pytest tests/ -k "export or glossary" -x -q`：88 passed
- `pytest tests/test_server_worker.py test_server_sse.py test_server_api.py`：66 passed
- 全量 `pytest tests/`：1986 passed，唯二失败均不在本面：`test_compile_engine_judge.py::test_tectonic_map_flags_subset`（compile/engine 在飞）、`test_segmenter_expand_surface.py`（latex expander 在飞，red-by-design 等 patch 落地）
- `test_pdf_no_babeldoc_501` 两处环境挂本轮自愈（babeldoc-e2e 侧已收/隔离）

Phase A+B 合并改动面：`export/{common,__init__,epub,docx}.py`、`cli.py`、`worker.py`、`tests/test_export_glossary.py`（新）、`tests/test_server_upload.py`。
