# server-residual — server/ 残余待办 + 死角清扫（5 真修 + 9 新测试，483+55 绿）

> 2026-09-17 收口。scope=src/texlate/server/（worker.py 冻结未动）+ tests。自验：`pytest -k "server or app or share"` 483 passed；`test_worker_audit_fixes.py` 55 passed；ruff format/check 双净。

## 待办核销

1. **store.transition() 竞态**——无竞态，已记档：函数体同步无 await；所有写路径串行在 uvicorn 单 loop 线程（worker 线程经 `_on_loop` call_soon_threadsafe+Future.result）；check_same_thread=True 越线程直接炸。docstring 补原子性论证。
2. **_build_md_zip to_thread**——合规：`_on_loop` 回弹 store/bus 调用，无 loop 亲和性假设被违。
3. **events.py**——无回归未改：Queue(512) 满 put_nowait 弃旧发 _RESYNC；close_all 投递关闭哨兵；overflow/close_all/replay 有既有测试。
4. **app.py**——`_auth` 每请求重复读盘 → request.state.auth_ctx 缓存（isinstance(AuthContext) 校验，失败路径不缓存）；连带 arxiv_translate/_upload_fields/_check_quota 三处 settings_store.load() 复用 auth.settings 同一请求快照。settings_put/share_import/retry/health/providers/local-mode 核对无问题。

## 死角真修（4）

1. **settings.save() connections 槽污染**：换 endpoint 未带 key 时原实现先 `old["api_key"]=新endpoint历史key` 再 conns 回写——按 cfg.base_url 分槽，旧槽被错写新 key，切回旧 endpoint 会把新 key 发给它。改为只动 merged（old 不可动），注释记档。
2. **settings.load() concurrency 崩溃**：非数字/0/负值直接进 int() 或 0 并发 → `_load_concurrency`：max(1, int(value or 3))，非法/0→3，负→1。
3. **server_salt 空文件返回 ""**（空盐下 tenant_for 退成裸 sha256(key)）→ 空/全空白视为未初始化重新生成。
4. **babeldoc._spawn 双 bug**：(a) 兜底路径 `stdout=asyncio.subprocess.STDOUT` 非法——STDOUT(-2) 只对 stderr= 合法，stdout= 让子进程 dup2(-2) EBADF，**最小 repro 实证该路径从未工作过**；改匿名 os.pipe() 两流合并。(b) pty ioctl 失败 master/slave 两 fd 泄漏 → except 分支 suppress(OSError) 双关。_spawn 现返回 (proc, read_fd)，泵统一 asyncio.to_thread(_pump_fd)，_pump_stream 删除。docstring 记 STDOUT-illegal 史。

## 新测试（test_worker_audit_fixes.py +9）

TestAuthOncePerRequest（spy load 每请求 1 次）、TestConnectionsSlotPreserve ×2（换 endpoint 找回新槽历史 key 且旧槽不污染）、TestSettingsLoadTolerant ×3（abc→3/0→3/-2→1）、TestServerSaltEmpty ×2、TestSpawnPtyFdCleanup ×2（ioctl 翻车 fd 零泄漏 + pipe 兜底双流合并）。

## 触碰文件

store.py（docstring）、app.py、settings.py、babeldoc.py、test_worker_audit_fixes.py。events.py 未改。
