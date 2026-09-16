# crosscut-sweep — 全仓横切扫（死代码/异常吞没/资源泄漏/重复实现）

> 2026-09-17 收口。只读任务，零代码改动——可写 scope 内无确认缺陷，全部疑点属取舍层已分流。探针 `tmp/crosscut-sweep/`（scan.py/resources.py/swallow.py/dupes.py，gitignored）。方法：vulture（60/80 置信）+ 自写 AST 扫描（私有 def/常量引用计数、except-handler 形态、with 外资源获取、可变默认参/类属性、跨文件同值常量与同体函数）+ 逐处人工核实。

## 1. 死代码 —— 全数「存疑待裁」，无一敢确认删

src/ 内零可确认死函数。vulture 命中 60+ 项绝大多数是框架假阳性（typer 命令、FastAPI 路由/exception_handler、pytest autouse fixture、sqlite row_factory、`__getattr__` 动态分派）。真疑点全是**写后从不读**的字段/方法，判定全属取舍层：

- `src/texlate/xlat/client.py:42` `HIDDEN_PROMPT_TOKENS` — 零引用常量（前次 xlat-sweep 已标「去留 leader 定」，本扫复核仍零引用）→ dedupe-pass 收编
- `src/texlate/xlat/client.py:304` `FreeModel.max_output_tokens` — client.py:890 从 panel 响应填充，无任何 `.max_output_tokens` 读点；FreeModel 无 asdict 序列化路径 → 纯 write-only → dedupe-pass 收编
- `src/texlate/arxiv/meta.py:82` `VersionInfo.source_type` — meta.py:214 从 OAI `<source_type>` 填充，零读点；meta.json 是手搭 dict 不含 versions → 字段到不了产物 → dedupe-pass 收编
- `src/texlate/validate/l1.py:211` `TsValidator.ensure_deps` — 公开 bootstrap API（`npm i --prefix` 首装），模块 docstring 当它是首装路径，但 src/tests/bench 零调用。要么接线到 doctor/首用自动装，要么删 → dedupe-pass 收编
- `src/texlate/latex/model.py:160` `Signature.guessed` — tables.py:655 填充、零读点；docstring 自述「命中可审计回滚」（latex/ 只读，报 1d 裁）
- `src/texlate/latex/gullet.py:1089` `expand_all` — 零调用（docstring 称测试/分段器便利法，但测试也没用）（只读，报 1d）
- `src/texlate/compile/fixloop/cases.py:144,146` `verdict_before`/`final_pdf` 字段 — 构造填充零读点（只读，报 peer1）
- `src/texlate/compile/fixloop/engine.py:404` `capabilities` — yaml 装载后零读点（只读，报 peer1）
- `tests/test_bench_regression.py:138` `wall_ms` — 测试未用变量（微小）

## 2. 异常吞没 —— 零确认缺陷

全仓 except 面走 AST 全量盘点（130+ handler）+ 逐处人工读。统一约定很干净：旁路臂 `noqa: BLE001` + log/落账（worker/pipeline/engine 的「崩不拖主链」族）、类型化错误转换（ShareError/CtanFetchError/SniffError/MalformedEpubError）、cleanup+reraise。三个 `except BaseException`（xlat/state.py:50、compile/cjkmap.py:119、compile/sandbox.py:235）全部是清理后 raise；fixloop/llm_hook.py:139 是跨线程 ferry（box["e"] 在调用方重抛）。`contextlib.suppress` 全窄型。两处取舍值得留痕（非缺陷）：

- `src/texlate/server/worker.py:2024` `suppress(asyncio.CancelledError)` 裹 `_flush_translate`——当前语义正确（flush 体内无 await，pending cancel 实际落在 suppress 块**外**的 `await _aclose_clients`）；但属脆性结构——未来给 flush 加任何 await 会变成静默截断 flush + 吞 cancel。建议加一行「本函数体不得出现 await」注释或改 try/except 化 → worker-share-fix 收编
- `src/texlate/compile/engine.py:1393` `suppress(Exception)` 裹 `fetch_package` 候选循环——注释有取舍说明、`probe_file` 复核是真值；但失败细节零留痕（无 debug log），ENOSPC/权限类会在全部候选上静默重试。建议补 `log.debug` 一行 → 报 peer1（engine 在飞面）

## 3. 资源泄漏 —— 零确认缺陷

AST 扫 with 外资源获取 + 人工追生命周期：ZipFile×3（share.py:414/epub.py:244/worker.py:936）全 `with`；mkdtemp×3（share.py:427/worker.py:1104/cli.py:331）全 finally-rmtree；state.py mkstemp fd 走 os.fdopen；babeldoc pty/pipe fd 失败路全关、成功路 `_pump_fd` finally os.close（test_worker_audit_fixes 有专门防回归测试）；sqlite conn（cli.py:870/store.py:259）finally/lifespan close；httpx Client/AsyncClient 调用方全覆盖（cli.py:763 finally aclose、worker.py:1593 finally fetcher.close、worker.py:2028 `_aclose_clients` 处于 `_teardown_translate` 的 finally 下）；l1 常驻 Popen 有 close/kill 兜底；babeldoc proc 外部 cancel 走 finally `_kill_tree`。`time.time()-t0` 测耗时仅 sandbox.py:204 一处（NTP 跳变可致负/飘，显示级语义非缺陷）。

## 4. 可变默认参/共享可变类属性 —— 零命中

AST 全扫：def 默认参（字面量与 list()/dict()/set() 调用）、dataclass 可变字段缺 default_factory、类级可变属性、模块级可变表运行时改写——全净。

## 5. 重复实现 —— 15 组，只报告不合并

高优先级（同值多点、静默漂移风险）：
1. `DEFAULT_BASE_URL`/`DEFAULT_MODEL` — `server/settings.py:40-41` ↔ `compile/fixloop/llm_hook.py:47-48`：网关默认 URL/模型两处硬编码（只读侧，报 peer1）
2. `_NEW_ID_RE`/`_OLD_ID_RE` — `arxiv/fetch.py:148-149` ↔ `server/app.py:100-101`：arxiv id 校验正则 web 入口与取源层各一份（逐字相同）；建议单源到 arxiv/meta.py 或 textutil → dedupe-pass 收编
3. `_DOS_EPS_MAGIC`+`_is_dos_eps`+`_GRAPHIC_EXTS`+`_last_open_graphic_token` — `compile/engine.py:202-235` ↔ `validate/l2.py:268-300`（`compile/normalize.py:181` 第三处 magic）：前波已知的四点复制，l2 注释标「engine.py 同款」；裁断：维持复制（归并需动 normalize↔engine 边界口径，engine 在 peer 飞面）——留档
4. `_JSON_FENCE_RX` — `xlat/pipeline.py:212` ↔ `fixloop/llm_hook.py:71`（llm_hook 在 peer 飞面，报 peer1）
5. `_TAILNET_V4` — `xlat/client.py:359` ↔ `server/settings.py:62` → dedupe-pass 收编
6. `_LOCAL_HOSTS` — `server/app.py:103` ↔ `server/settings.py:59` → dedupe-pass 收编
7. `_ERR_FILELINE_RE` — `compile/engine.py:168` ↔ `fixloop/logparse.py:37`（报 peer1）
8. `_TEX_EXT` — `arxiv/unpack.py:44` ↔ `arxiv/locate.py:33` → dedupe-pass 收编
9. `_BEGIN_DOC_RE` — `arxiv/sniff.py:142` ↔ `compile/inject.py:203`（同正则）→ dedupe-pass 收编
10. `_unique_rename`/`_zip_unique` — `arxiv/unpack.py:161` ↔ `server/worker.py:896` 逐字同体（worker 注释已标同款语义）→ dedupe-pass 收编

近重复/有意分叉（报告留痕）：
11. `_INPUT_BRACED_RE` — inject.py:198 非捕获组 vs probe.py:49 捕获组（消费面各异）
12. `PH_FUZZY_RX` — xlat/placeholders.py:43 vs validate/l0.py:80：l0 版每臂加 ASCII-字母 lookahead（注释注明防【图1】误命中），有意分叉但基础 pattern 会漂
13. `_DOC_RE` — inject.py:191 带 `(?![a-zA-Z])` vs fixloop/engine.py:55 无断言（宽松版会误吃 `\documentclasses`，边缘）（报 peer1）
14. `_CTX_LINES`/`_TAIL_LINES` — l2.py:121-122 ↔ logparse.py:24-25 同值 8/30（巧合或对齐未知）
15. latex/ 内部簇（只读，报 1d）：`_DOC_BEGIN_RX`×3（flatten:35/segmenter:4278/api:30）、`_PREAMBLE_RX`×2、scanner↔segmenter 七个同体常量（`_CLEAN_CMD_RX`/`_LETTER_TAIL_RX`/`_PROTECT_TYP`/`_CHUNK_SPEC_CACHE` 等 v1/v2 平行臂）、`_extract_tag_region`（flatten:96/gullet:2241 同体）

## 自验

未改代码故无新测试。`uv run ruff check src/ tests/` 现 17 错，全在 latex/segmenter 复杂度项与 tests/ 若干文件——对照 git status 属其它 teammate 在飞改动，与本扫无关。
