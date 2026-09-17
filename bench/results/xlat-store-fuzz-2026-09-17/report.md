# xlat-store-fuzz — xlat/ + store/events 离线 fuzz（交付 tests/test_fuzz_xlat.py + test_fuzz_store.py）

> 2026-09-17 收口。交付 `tests/test_fuzz_xlat.py`（38 items）+ `tests/test_fuzz_store.py`（25 items），未动 src/ 与既有测试，无 git 操作，纯离线（ScriptedTranslator 内容驱动 + httpx.MockTransport）。自验：`uv run pytest` 52 passed + 11 xfailed（2.8s）；`ruff check`/`ruff format --check` 双净。

## 覆盖矩阵

### xlat（内容驱动 fault 注入 ScriptedTranslator：auth/non-retryable-5xx/retryable-5xx/裸崩/校验拒）

- codec：`encode/decode_newlines` round-trip（\r\n/\r 归一 + 三层转义 + RAW 形）、`source_sl/pl` 计数独立 oracle、sentinel 字面族（→xfail）
- batch：`pack_batches` 保序划分+容量界、`encode→parse` 往返、垃圾 parse 不错位不抛、`split_long_chunk` 覆盖/非空/≤limit+64、whitespace-member 毒批钉
- placeholders：`diff` missing/misspelled/extra oracle、`is_placeholder_only` oracle、src_literal 豁免（→xfail）
- pipeline：200 iters × 随机 marker 矩阵 × concurrency{1,2,4}——结果序==输入序、chunk 零丢失、批内连坐（非 retryable 全批同罪 skip；retryable/裸崩整批降级单翻逐块定罪）、skipped⇒translation==source、全字段对账；60-iter 八元组确定性；40-iter resume done-set 重放；all-auth→AuthTrippedError；空 doc
- client/keys：ChatError 文本不含明文 key（MockTransport 401 echo canary）、redact 形态表、segment_key/file_cache_key/cache_key_for sha256 oracle+成分敏感（api_key 永不明文）、AuthGate 1500-iter 记账 oracle
- state：atomic_json 0600+无残留、record→load 往返、load/load_cache 300-iter 字节/结构变异（缺陷族内断言复现）

### store/events

- `transition`：13 cur×15 to 全矩阵（含 force 钉脏态拒非 force 出）、TransitionError 载荷、拒迁行原状、1500-iter 游走 oracle、字段副作用表、缺失行 StoreError
- `valid_task_id` 形态 oracle + int(,16) 宽容度钉（大写 hex/空白填充过闸）
- `append_event`/`events_since`/`last_seq` 逐任务连续单调+回放界；EVENT_CAP 滚动窗
- `insert_chunks` 中段 UNIQUE/PK 冲突全回滚（has_chunks 不假阳）；flush_chunk_batch 脏列名全回滚、cache REPLACE 保 hit_count、counters 缺键清零钉
- `delete_task` FK CASCADE + 幂等 False；recover_startup 40-task 随机混合 oracle+幂等+worker_id 口径
- 并发：6 线程×15 ops 自持连接同库写不死锁、seq 各自连续；越线程直调→ProgrammingError；claim 无 CAS last-writer-wins 钉
- snapshot.counters↔chunk_counts 对账；list_tasks 租户隔离、find_active_by_cache_key、tenant_usage、delete_file 幂等
- EventBus：扇出保序保 seq、溢出→_RESYNC+摘除、stream 重放→实时→done 终结+finally 退订实效（spy 验）、终态行/行删短路、close_all 唤醒 parked、sse_frame 映射

## 钉住的确认缺陷（4 族 / 11 xfail case）

1. **placeholders.diff 缺 L0 src_literal 净差豁免** — `src/texlate/xlat/placeholders.py:236-241`（对照 `validate/l0.py:468-480`）。复现：`ph.diff("see [RS80]", "see [RS80]")` → extra 非空；而 `validate_pair(src,src).ok` True。后果：verbatim 字面源 chunk 在默认 validator 下恒 invalid→阶梯三振→恒 fallback_orig。
2. **encode/decode_newlines sentinel 字面 round-trip 破坏** — placeholders.py 转义三相最内层无转义。复现：`decode_newlines(encode_newlines("a [[__TEXLATE_SL_LIT__]] b"))` → 落成 `[[SL_RAW]]` 裸 token。失败安全（下游 diff 拦截升格 fallback），未进 splice。
3. **StateStore.load/load_cache 漏 UnicodeDecodeError** — `state.py:197-198`（load）、`113-119`（load_cache）。`except (JSONDecodeError, OSError)` 不收解码错。复现：state.json 写 `b"\xff\xfe\x00garbage"` → load() 抛，不隔离不改名，续跑入口崩在脏文件上。
4. **StateStore.load 字段级类型脏穿兜网** — `state.py:220-247`。top-level dict 检查只管容器外形：真值非可迭代 completed/results/errors_report→TypeError、completed 含不可哈希成员→TypeError、真值非 dict meta→AttributeError、meta.total_chunks 非数值→ValueError。复现：`{"meta": "x"}` → load() AttributeError。8-param xfail 钉族谱；test_fuzz_state_load_never_raises 用 _load_escape_exc oracle 断言族内逐例复现（修复后连同 xfail 一并转红）。

## 未钉观察项

- stream 的 seq<=delivered 去重分支单线程下不可达（subscribe 先于 events_since，无 interleave 窗）——防御性死码
- `_safe_cut` ±64 窗可拦腰切巨型假 `[[X_n]]` token（上界已覆盖，token 完整性不在契约内）
- 纯 whitespace 成员毒化整批 parse→全批降级；solo whitespace 批经 @@ fallback 产 `"[1]"` 译文 status ok——极端构造才达
- load_cache 非 dict JSON 静默回 `{}` 不隔离（load 同情形隔离改名）——口径不对称
- recover_startup 对终态行保留 worker_id（认领标记不清）
- split merge 接缝恒插 `" "`（原文无空也插）；split parent attempts=0 不聚合
- auth-gate 把 circuit-open skip 也计入记账（auth 失败数含被熔断跳过的块）
