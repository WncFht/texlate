# server-sidecar-audit — babeldoc/staticfiles/__main__/cjkmap 交付

> 2026-09-17 收口。落地 `3cd4148`（server/{babeldoc,staticfiles,__main__}.py + compile/cjkmap.py + tests/test_server_sidecar.py 新建 14 条，+460/-18）。leader 复核 `-k "sidecar or babeldoc or staticfiles or cjkmap or server_main"` 39 绿。探针 `tmp/server-sidecar-audit/`（gitignored）。

## 已修（file:line + 机理 + 修法）

1. **`src/texlate/server/babeldoc.py` — 孙进程孤儿 + 泵线程吊死（主缺陷）**
   机理：timeout/cancel/异常逃逸三处 `proc.kill()` 只杀直接子进程。实证 tmp/server-sidecar-audit/probe_orphan.py：假 babeldoc fork `sleep` 孙进程（真 babeldoc 的 pdf_creater.py:556,583 用 multiprocessing.Process 做字体子集化/clean-save——不是假想敌），修复前孙进程存活且继承 pty slave 写端 → `_pump_fd` 读不到 EOF 卡满 5s wait_for → `pump.cancel()` 杀不掉 to_thread 线程 → 线程+fd 泄漏（run 总耗时 7.0s = 2s 超时 + 5s 泵死等）。
   修法：`_spawn` 加 `start_new_session=True`（pgid=pid；POSIX 生效/Windows 忽略）+ 新 `_kill_tree(proc)` 做 `os.killpg(pid, SIGKILL)`（组空退化 proc.kill()，与 sandbox._kill_proc 同语义），三处 kill 点全换。修后探针：2.0s 收工、孙进程 DEAD、泵即时 EOF。

2. **`src/texlate/server/babeldoc.py` — drain 缓冲无界**
   `buf` 全程累积子进程输出（cursor 只前移不回收），1h 长跑内存无界。改为锁内 `bytes(buf); buf.clear()`，cursor 删除。

3. **`src/texlate/server/babeldoc.py` — `_Feed.errors` 无界 + O(n²) 去重**
   每行错误 `msg not in self.errors` 全表扫，全篇报错时把消费线程（worker loop）拖住。改 `deque(maxlen=_MAX_ERRORS=64)`——keep-last 窗保住 `_classify_rc` 的 `errors[-1]` 语义，去重窗 O(64)。

4. **`src/texlate/server/babeldoc.py` — write_config key 文件 0644 窗口**
   `write_text`+`chmod` 两步间 key 短暂 0644。改 `os.open(O_CREAT|O_WRONLY|O_TRUNC, 0o600)` 落盘即 0600（chmod 保留兜预存文件）。data dir 虽 0700，窗口仍是凭证卫生面。

5. **`src/texlate/server/staticfiles.py` — SPA 无 Cache-Control**
   Starlette 只给 ETag/Last-Modified，index.html 会被启发式缓存 → 发版吃旧壳。挂 `_SpaFiles` 子类（定义收在 `mount_spa` 内——模块级 import StaticFiles 会破 server/__init__ 的轻依赖纪律），覆写 `file_response` 按**实际 serve 的文件**判（关键：starlette 把 `/` normpath 成 `.`，按请求路径判会漏根路径）：serve 产物名 `index.html` → `no-cache`；`assets/` 下哈希产物 → `public, max-age=31536000, immutable`；pdfjs bcmap 等稳定名 → 默认不贴。relpath 基准用 `realpath(static)`（lookup_path 产 realpath，不同尺会得到 `..` 前缀误判）。

6. **`src/texlate/server/__main__.py` — --port 无范围闸**
   `--port 70000`/负数跑到 uvicorn bind 才炸。改 `type=_port` 校验函数，argparse 层 exit 2。

7. **`src/texlate/compile/cjkmap.py` — 半截 `.mapped.pdf` 孤儿 + 间接引用盲区**
   `writer.write(tmp)` 翻车时 tmp 半截留盘（任务目录里成幽灵产物）；`/CIDSystemInfo` 若是间接引用（dict.get 不解引用），`.get` AttributeError 把整篇注入炸没（调用方 best-effort 壳吞成一行 log → ToUnicode 静默全丢）。修：write 失败 `tmp.unlink(missing_ok=True)`；`system` 非 dict 先 `get_object()`；单字体判定包 try（AttributeError/KeyError/IndexError/TypeError）→ skip 该字体不拖全篇。
   scope 说明：teammate 指令写的 `cmaps/` 数据件实际在 `compile/cmaps/`，`cjkmap.py` 是它的唯一读取路径——按「读取路径」归属处理；compile-core-audit 的 scope 是 engine/sandbox/inject/l2，不冲突。

## 新测试（tests/test_server_sidecar.py，14 条）

- TestKillTree：timeout/cancel 两路 killpg——孙进程死 + elapsed<4.5s（修复前≈6s 泵卡死判别阈值）
- TestFeedBounds：errors deque 窗口
- TestWriteConfig：0600
- TestSpaCacheHeaders：index no-cache / assets immutable / 稳定名无 CC / `..` 穿越 404
- TestMainEntry：合法透传 / 70000 exit 2 / --data-dir→env
- TestCjkmapResource：间接 CIDSystemInfo 注入 / 缺件 FileNotFoundError 且原 pdf 不动 / write 翻车无 tmp 孤儿

## 自验

- `uv run pytest tests/test_server_sidecar.py tests/test_server_babeldoc.py tests/test_server_polish.py tests/test_app_endpoints.py` → 166 全绿
- `uv run pytest tests/ -k "server or cjk or babeldoc or e2e_wiring"` → 328 全绿
- `uv run ruff check + format --check` 五文件全净
- wheel 实证：`uv build` 后 `texlate/compile/cmaps/Adobe-GB1-UCS2` 确认随包（dist/ 旧 wheel 是 cmap 落地前的陈旧产物，非打包缺陷）；starlette 1.6 `follow_symlink=False` 默认已防符号链接逃逸；`.mjs`→`text/javascript` MIME 正常。

## 未修 + 理由

- `_Feed._STAGE_ROW_RE` 误吃形如 `Error in part 0: boom (1/2)` 的日志行——只影响 SSE log 流展示，errors 采集与 stderr_tail 仍完整保留，判定不受影响；收窄规则误伤 stage 行风险更大，留。
- `harvest_outputs` 对 rc=0 但只产 dual 缺 mono 的边例不判 degraded——babeldoc 双产物同写路径，未实证到真形态，留。
- `spa_dir()` env override 不 `.resolve()`——cosmetic，StaticFiles 内部自行处理。
- pty 分支 `except OSError` 未扩到 Exception——已知 8d 修复覆盖的就是 openpty/ioctl 的 OSError 面，更宽捕获无实据。

## 外部路由

- 无跨 scope 遗留缺陷。worker.py 的 `_run_pdf` kill 语义无需改（走 `run_babeldoc` 内部）。
- 提示：`dist/` 里现有 wheel 是 2026-09-16 09:32 陈旧产物（缺 compile/cmaps）——下次发版前 `uv build` 重打即可，无需代码动作。
