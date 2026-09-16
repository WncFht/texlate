# worker-resid-audit — worker.py 全量残件审计交付

> 2026-09-17 收口。落地 `8f40700`（worker.py + 两测试文件，+209/-10）。scope：worker.py 全量 4101 行 + TaskRunner/事件/store 交互面。探针 `tmp/worker-resid-audit/{probes.py,verify.py}`（gitignored，先复现后逐条翻转）。

## 修复（worker.py 5 处，全部探针实证）

- **D1 dispatcher 猝死（高）** `_dispatch_loop` ~4052：前置段 `store.get`/`claim`/`TaskCtx` 构造的 sqlite3.Error 透出 → dispatcher task 死亡 → 后续全部 enqueue 静默饿死 + 该条 secrets 残留。实证：flaky get 炸一次后 `dispatcher.done()=True`、B 永不分发、secrets 泄漏。修法：外层 `except Exception` → log + `secrets.pop` + continue；行仍 queued，重启 `_replay_queued` 兜底。
- **D2 heartbeat 猝死（中）** `_heartbeat_loop` ~4099：`except (StoreError, OSError)` 漏 `sqlite3.Error`（3.12.13 实证 OperationalError 非 OSError 子类）→ 一次 DB 错杀 ticker，全实例 updated_at 停摆。修法：`except Exception`（心跳本就是活性信号）。
- **D3 share_apply 编码面（中）** `_share_apply` ~2183：`dual.json` 非 UTF-8 → `UnicodeDecodeError`（ValueError 但非 JSONDecodeError）逃出捕获面 → `run()` 的 `except ValueError` → `_fail "parse"` 不可重试 fault。隐式 arxiv 路违反「隐式命中是优化不是承诺」（应回退自译），kind=share 应归 partial+share_verify 而非 fault。修法：捕 `UnicodeDecodeError` → `_ShareRejectError`——隐式路 unmark+回退自译，share 路 `_reject share_verify` partial。
- **D4 glossary load 异常面（中）** `_make_glossary` ~3886：`except (OSError, ValueError)` 漏 `Glossary.load` 的 TypeError（flatten_terms 非 mapping / load_index 非 dict）与 yaml.YAMLError → 任务 fault "internal" 而非 log+降级无表。实证：顶层 list 的 glossary.local.yaml → TypeError 逃逸；语法坏 yaml → ParserError 逃逸。修法：`except Exception`。
- **D5 share_pack 无终态闸（低中）** `_share_pack_try` ~3387：cancel 竞态窗（`_build_md_zip`/`_no_pdf_finish` 的 to_thread 期间翻转、或 retry 把终态挪回 queued）→ cancelled/queued 任务仍发布进公共 index。实证：cancelled+share_pack opt-in → publish 被调。修法：新取行按正列 `status in (done,partial,fault)` 闸——弃单系与 retry-queued 同拦，§9 fault 放行语义不变。

## 测试

- tests/test_worker_audit_fixes.py 尾部 +4 类 8 钉：TestResidAuditLoops（dispatcher/heartbeat 对 sqlite3 面存活+secrets 清）、TestResidAuditShareApply（bad-utf8→_ShareRejectError）、TestResidAuditGlossary（list/bad yaml→None）、TestResidAuditSharePackGate（cancelled/interrupted 不打、fault 照打）。
- tests/test_share_hook.py::test_direct_call_missing_artifacts：直调 `_share_pack_try` 前先 transition done——钩本只在终态后调，闸下 queued 态直返是新设计行为。

## 只报不修（低/info 或超 scope）

- `_run_doc` cancel 留孤儿 export 线程继续烧 token（export_document 同步接口的结构限制）；`_doc_emit` total=0 属刻意（终态才齐）。
- `_materialize_reuse` 命中行被删 → done 零产物（窄窗）；OSError→"parse" 把 ENOSPC 归不可重试（错误码映射裁决）；delete-竞态 FK IntegrityError 噪声（已 contain 不扩散）。
- `enqueue` 先于 `start()` 会丢队列项但已登记 secrets（lifespan 里 API 不可能先于 runner.start，仅 header-auth 秘钥残留至进程死）。
- `_share_pack_try` fetch→publish 之间仍有微窗（无锁不可消，属线性化边界）。
- `share_pack_publish` 的 `index_append` 失败留孤儿 bundle 文件（同 key 重打覆盖同名，不累积）。

## 证伪项（读了契约确认非缺陷）

glossary_csv/workdir 自 mkdir、cancel 端点 done 覆盖、delete-活跃 409、retry 哨兵/`src/` 保全、secrets.model=row["model"]、share 目录由端点解包、XlatPipeline/ChunkRecord/flush_chunk_batch/share_key 契约、`run_babeldoc` 回调在 loop 线程（should_cancel→store.get 同线程安全）、`_on_loop` 全程无越线程直调。

## 自验

`pytest -k "worker or share"`：269 passed, 5 xfailed；`ruff check`/`format` 三文件全净。leader 复核：test_worker_audit_fixes + test_share_hook 103 passed，ruff 净。
