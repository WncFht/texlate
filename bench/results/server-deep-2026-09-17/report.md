# server-deep — store/events 持久层+推送层纵深审计

> 2026-09-17。scope：store.py/events.py + 两测试文件。242 store/event/sse/server 测试绿、ruff 净。

## 结论

线程亲和纪律**干净**：`_on_loop` 弹跳机制（worker.py:1167-1184，`_loop_tid` 判定 + `call_soon_threadsafe`）覆盖了所有 to_thread 段；sqlite conn 无偷渡。发现的真实问题是**热查询索引缺位 + 订阅队列无界**，已修。

## 改动文件（4）

- `src/texlate/server/store.py` — ① `idempotency_key` 从 options_json 提升为一等列：`_COLUMN_MIGRATIONS` 扩为 `(table,col,ddl,backfill)` 四元组带 options_json 回填，新 `_POST_DDL` 段在列迁移后建 `idx_tasks_idem(tenant, idempotency_key, created_at DESC) WHERE idempotency_key IS NOT NULL`（`CREATE INDEX` 引用迁移列必须在 ALTER 之后，否则老库 open 即炸）；② `idx_tasks_cachekey ON tasks(cache_key) WHERE cache_key IS NOT NULL`——`find_reusable` 的 done/partial 臂吃不到 ACTIVE 部分唯一索引，此前是建行热路径全表扫；③ `_warnings` 下推 `type='warning'` SQL 过滤——snapshot 每次调用不再全量 json.loads ≤2000 事件（chunk 事件 KB 级载荷）；④ `create_task` 建行时从 options 提取 idem 列。
- `src/texlate/server/events.py` — 订阅队列 `_SUB_QUEUE_MAX=512` 限界；`QueueFull` → 摘除订阅 + `_cut` 清积压压 `_resync` 哨兵断流（客户端按 SSE 协议带 Last-Event-ID 重连走 events_since 补齐，落盘即重放凭据）；`close_all` 给全员压哨兵唤醒 parked 等待者（原先只靠传输层取消兜底）。
- `tests/test_server_store.py` — `TestIdempotencyKey`（建行提取 + 老库迁移回填）+ `TestHotQueryPlans`（EXPLAIN QUERY PLAN 钉索引使用）。
- `tests/test_server_sse.py` — `test_overflow_cuts_stalled_sub`（cap=2 溢出断流 + 重连全量重放）+ `test_close_all_wakes_parked`。

## 验证

`uv run pytest tests/ -k "store or event or sse or server"` → 242 passed；ruff check + format 四文件全净。

## 索引选型决策（EXPLAIN 实证）

`json_extract` 表达式索引会输给 `idx_tasks_tenant` 的 ORDER BY 红利（planner 为免 temp b-tree 选 tenant 前缀扫）——`+tenant` disqualify 或 `INDEXED BY` 都是 hack；正解是与 `cache_key` 同款的真列 + 复合索引，三列复合 `SEARCH (tenant,idem_key)` + 免排序兼得。`list_tasks(tenant,status)` 不加复合：现有 status/tenant 两索引各供单列选择性，复合边际太小。

## 取证清单（app.py/worker.py 只读发现，均未动）

1. worker.py:2973 `_build_md_zip` / 2472 `_expect_cjk` —— 直连 store 但靠调用方在 loop 的隐式契约（`_expect_cjk` 有注释明示，`_build_md_zip` 没有）；未来谁把它挪进 to_thread 段会 fail-loud（check_same_thread ProgrammingError），值得在 `_build_md_zip` docstring 补一句线程约束。
2. worker.py:1173 `_on_loop` 的 `self._loop is None` 静默直通分支——`run()` 入口才设 `_loop`（1360），pre-run 的 worker 线程调用会错线程跑 conn（同样 fail-loud，非静默损坏）。
3. store.py:681-684 `put_file` 在调用线程读全文件 + sha256——经 `_register`→`_on_loop` 落回 loop，50MB src.tar 哈希 ~100-300ms loop 停顿。修法在 worker 侧（线程内预算 size/sha 再传参），归 worker-followup 类。
4. store.py:393-433 `transition` 读-判-写两语句、app.py:531-572 check-then-insert——只在「单写者 loop 串行 + 同步调用不 yield」不变量下安全；若将来引入第二写者（多进程/多连接）即开 cancel-vs-worker lost-guard 窗。现状成立，记为架构约束。
5. app.py:1169-1174 `task_delete` 先发 done 再删行——内存扇出已送达，落盘 done 行随 FK 级联消失；task 本体 404 后重放无意义，语义自洽。
6. events.py `stream`：任务在订阅等待中被删 → 生成器 parked 到客户端断连才清理——良性，传输层 teardown 兜底。
7. babeldoc.py:663-669 `should_cancel`/`on_progress` 在 `run_babeldoc` 的 loop 轮询内触发——`_current_status`→`store.get` 亲和成立；`on_progress` 里的 `_on_loop` 包裹是防御性冗余但无害。
8. SegmentCache（worker.py:499-513）/DBStateBridge（625-651）直连 conn——`pipe.run` 是 loop 上 asyncio.Task（worker.py:1879），`_run_doc` 的 export 臂用 `state_dir` 文件态不碰 DB，均合规。

## 未做（判断：现状正确）

`transition` 原子化 UPDATE-guard、close_all 之外的任务删除主动断流——都属不变量内的假想场景，按纪律不预防性加。
