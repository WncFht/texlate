# worker-consistency — worker stage 一致性 13 修（F1–F10 + 追加 3 项）

> 2026-09-17 收口。scope：`src/texlate/server/worker.py`（±105 行）+ `src/texlate/server/store.py`（put_file 签名扩展 +10/-4）+ `tests/test_worker_audit_fixes.py`（+209）。leader 复核：diff 逐 hunk 对账一致，46 测试自验通过。

## F1–F10 stage 一致性/取消语义

1. `_ensure_scans` 改 async——`_parse_all` 全量解析走 `asyncio.to_thread` 不占 loop。
2. `_stage_parse` 尾部补 `_check_cancelled`（parse 完到 translate 前的取消窗）。
3. `_harvest_pdf_outputs` / `_prep_pdf_dirs` 挪 to_thread（产物收割+目录准备含文件 IO）。
4. `_build_md_zip` 经 `_on_loop` 回弹 + to_thread 包裹（zip 构建出 loop）。
5. share index.jsonl 读取补 `UnicodeDecodeError` 捕获（脏字节不再炸 stage）。
6. `_persist_usage` 增 `replace_est` kwarg——doc 臂用量登记走替换语义。
7. `_doc_emit` 终态守卫：`TERMINAL_STATUSES` 内不再发进度事件。
8. `aclose` try/except ×3（env_judge/llm_hook/l2 客户端关失败降 debug log）。
9. `_run_fixloop` `engine_for("xelatex", halt_on_error=False)`——fixloop 不因单错停车。
10. `_register` 重排：bytes/sha256 调用线程实测，`_on_loop` 只回弹 DB 写。

## 追加 scope（leader 路由 3 项）

- **`int(options[...])` 崩溃类**：新增 `_opt_int(ctx, options, key, default)`（worker.py:1379）——falsy→默认、`TypeError/ValueError`→`warning(bad_option)`+默认；应用 `qps`（_babeldoc_job）+ `concurrency`（_stage_translate 同款隐患并修）。
- **`.TEX` 大写盲区**：`_parse_all` `rglob("*.tex")` → `rglob("*")` + `is_file() and suffix.lower()==".tex"`（与 compile 侧 `7a78b66` 同款）。
- **put_file loop-block**（server-deep 取证 #3）：`store.put_file` 加 keyword-only `size`/`sha256`——预算值跳过读盘直写库，缺省走原 `data_dir` 实测（非 worker 调用面零变化）；`_register` 调用线程读+哈希；`_run_doc` 两处 on-loop `_register` 包进 to_thread。

## 验证

- `tests/test_worker_audit_fixes.py`：**46 passed**（leader 复跑同值）。
- `tests/ -k "worker or share or pipeline or store"`：268 passed；put_file 直调面回归 161 passed。
- `ruff format --check` + `ruff check`：3 文件净。
