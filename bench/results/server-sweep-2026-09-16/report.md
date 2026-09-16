# server-sweep — server/ 残余审计收口

> 2026-09-16。scope `src/texlate/server/` + 对应测试。114 测试绿、ruff 全净。

## 处置

- **TODO/FIXME/XXX/HACK**：全 server/*.py 0 命中。
- **死代码**：`store.ALL_STATUSES`（0 引用）删；`TaskRunner.secrets_for`（死访问器）删；`settings.INFLATED_CAP/MAX_FILES`（§2.4 spec 常量死副本）——worker 本地 `_MAX_UNPACK_FILES` 与硬编码 300MB 收编回 spec 常量唯一事实源。vulture 误报 5 件保留（鸭子协议/测试引用/sqlite3 属性/PEP 562/装饰器注册）。
- **真修复 `_heartbeat_loop` 双重缺陷**（worker.py）：(a) `except (StoreError,OSError): continue` 吞错零留痕 → `log.debug(exc_info)`；(b) `self._current` check-then-use 竞态——dispatch finally 清 None 与 `[0]` 访问间可插 TypeError → ticker 静默死亡、updated_at 永停。改快照读。测试 `TestHeartbeatLoop.test_survives_store_error_and_current_clear`（StoreError 连打 + 中途清 _current，断言 ticker 不死且真打过拍）。
- **错误路径抽查净**：run() 顶层漏斗全分支留痕；stage 内宽 except 均 `_log`/`_warning`；store mutator 事务配对干净（`update_chunk`/`_set_fields` 不 commit 系设计——仅 flush_chunk_batch 事务内/update_fields 内）。

## 残余建议（结构性，记档不动）

- `stop()` 关停 `except (CancelledError, Exception): continue` 连真 bug 也吞——noqa 明示的设计，关停期异常完全不可见（若要可见留 log.debug）。
- `store.cache_get` 每命中 UPDATE+独立 commit——热缓存每读一写事务，量级上来后可批量回写。
- `transition` get→UPDATE 无乐观并发守卫——§3.2 单写者纪律覆盖。
