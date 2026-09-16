# server-persist-audit — server 持久化面审计交付

> 2026-09-17 收口。落地 `89d71d5`（store/app/events/worker + test_server_persist 新文件 + test_app_endpoints 契约更新，+561/-42）。自验 server+worker+share 面 15 文件 432 绿、ruff 双净。探针 tmp/server-persist-audit/（probe_defects / probe_b / probe_cachekey 三组）。

## 修复清单（7 项 / 4 源文件 + 2 测试文件）

1. `store.py:541 insert_chunks` 显式事务——executemany 中途失败留下未提交隐式事务，下一个无关 `commit()` 把半成品 chunks 静默落库（`has_chunks` 误判 parsing 完成 → resume 拿残缺块集跑翻译）。改 `BEGIN IMMEDIATE` + except rollback，与 `flush_chunk_batch` 同口径。
2. `store.py:772` 新增 `Store.delete_file(task_id, kind) -> str | None`——删 files 登记行返回被删行 path，无行返 None；磁盘件清理由调用方按 path 负责（与 `delete_task` 表行/`tasks/{id}/` 文件分两层同分工）。
3. `worker.py:220 _SPLICE_STALE_KINDS` + `:2080 _invalidate_splice` 产物清理——译文变更摘 `.splice-done` 后 zh/ 会 rmtree 重建，但旧产物 files 行与磁盘件全残留：重编失败/resume 未到编译段就以 partial 终态时，`/api/files` 与 reader 端点照发上一轮旧译文（reader 直读 `dual.json` 磁盘件，仅删行不够）。摘哨兵后按 `_SPLICE_STALE_KINDS`（zh_pdf/zh_src_zip/dual_json/compile_log/md_zip——全是 chunk 派生）删行 + confinement 校验后 unlink 磁盘件；en_pdf（base/ 编译，不依赖 chunks）与 src_tar（源）保留。覆盖 `_teardown_translate`/`_stage_share_apply` 两 callsite。
4. `app.py:1235 task_retry` 换 main 清理面——(a) 原清理只删 chunks + rmtree base/zh/build-*，files 行与 en.pdf/dual.json/md.zip 磁盘件残留 → retry 后 files 端点仍 200 发旧字节；(b) 原判定只比 `body["main"]`，`options.main` 写入 options_json 但不触发清理且 resume 走 has_chunks 跳过 _build_base——死配置。修：body.main 与 options.main 统一汇进 opts 再比 `row["main_tex"]`；触发时删 chunks + rmtree 四目录 + 全部非 src_tar files 行/磁盘件（en.pdf 随 base/ 同死）。`.fetch-done`/src/ 保留。
5. `app.py:1299 reader_get` 登记行闸门——原只查磁盘 `dual.json` 存在性：登记前崩溃或失效清理后的孤儿磁盘件也会被服务。现以 `dual_json` 登记行 + 磁盘件双条件为准。
6. `events.py:97 stream` 行缺席守卫——`_get_task` 后 stream 开始前任务被删：delete 端点先发 done 再删行，晚注册订阅者错过该 done；`row is None` 时原判定不落终态分支 → `await q.get()` 永 parked，SSE 连接挂死。现 `row is None or row["status"] in TERMINAL_STATUSES` 即 return。
7. `worker.py:1360 _opt_int` ≤0 钳位（外部路由收编，xlat-audit 转出）——存量 options_json 的整型旋钮只防非数值；`qps` 收负值/`"0"` 串原样返，`concurrency` 有 `__post_init__` 兜底而 `qps` 裸奔直进 BabeldocJob → sidecar。修：`v < 1` → `bad_option` warning + 钳 1，与 `_clean_task_options`/xlat `__post_init__` 同口径；两 callsite（concurrency/qps）自动受益。

## 新测试（+11）+ 存量契约更新（7 条）

test_server_persist.py（新文件）：delete_file ×2、insert_chunks txn 回滚 ×1、splice 失效产物清理 ×2、retry 换 main 清理 ×3、reader 孤儿闸门 ×1、stream 行缺席 ×1、_opt_int 钳位 ×1。
test_app_endpoints.py：`_write_dual` helper 补 `put_file` 登记（一处修 5 调用方），corrupted_dual_500/dual_non_dict_500 改 `_reg_file` 登记后写损坏 blob——「已登记但盘件损坏」仍走解析 500；原 7 条 404 全复绿（漏网因：agent 自验清单只跑 test_server_* 前缀，未含 test_app_endpoints——已补跑）。

## 未修（理由）

- `append_event` INSERT+DELETE 修剪对失败留 open tx——下一次 append 的 trim 自愈，窗口内 task_events 短暂超 EVENT_CAP 无害；在 publish 热路径加 try/rollback 改全部事件写错误语义，收益不匹配。记档。
- upload_pdf/docx plain-retry 残留产物不清——同推导输入旧产物仍有效；invalidation 只在输入变更（main/chunks）时 warranted。记档。

## 外部路由（spec 级决策，未改行为）

- **`cache_key_for` 排除项**（worker.py:476）——实证：无 glossary 的 done 任务，带 glossary/options.main/options.engine/options.l2 的请求全 200 reuse 命中；异 target_lang/model 正确 202 miss。「带术语表任务命中无术语表缓存产物」是 §4.3 "intentionally excluded" 显性后果——glossary/base_url/engine/l2 影响产物但不进键。缓存仅作进度 shortcut 可保持现状；要产物正确性口径需把 glossary 摘进键材料——spec 修订决策。
- **`_parse_multipart` str 文本字段无界**（app.py:177-205）——Content-Length 缺席（chunked/HTTP2）时 413 预检失效；文件字段有 UPLOAD_CAP 累计闸，str 字段经 `request.form()` 整体进 RAM 无上限——server 公网部署内存 DoS 面。修需 parser 层（starlette form 无 per-field limit），建议 upload 边界加 body-size 闸或换流式 parser——跨模块决策。

## 审计清白面

store：transition 读-判-写单写者串行、claim、全量绑定参数无 SQLi、migration DDL 幂等、状态机口径。app：file_get confinement 双侧、_get_task 先于 mutation、CSRF/CORS gating、upload 魔数路由、share_import orphan 清理、_auth 时序。events：订阅队列有界 + _cut/_RESYNC、unsubscribe finally、seq 去重、EVENT_CAP 重放面。
