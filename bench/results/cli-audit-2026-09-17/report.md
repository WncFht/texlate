# cli-audit — cli.py 深度审计（14 面修复 + ~40 新测试，167 绿）

> 2026-09-17 收口。scope：`src/texlate/cli.py` + `tests/test_cli*.py`。`pytest -k cli` **167 passed**（含 share_cli/export_glossary 回归 46 项）；ruff 双净。落地 `253d21c`。

## 修复清单

### 资源泄漏

- `cli.py:114` `_acquire` 收口：`Fetcher()` 内建 httpx.Client 连接池原在 `fetch`/`_resolve_source` 永不关闭 → try/finally `fetcher.client.close()`。
- `cli.py:346` `_populate_work_dir`：`run` 的 `shutil.copytree` 原在 try/finally **之外**——copytree 抛错（盘满/权限）时 mkdtemp 的 `texlate-run-*` 目录泄漏。现整体纳入 try/finally，OSError 归一 exit 1。测试断言 tmpdir 无残留。

### 异常路径吞错/裸 traceback → 归一报错

- `_share_row`：db 在场但非 sqlite/缺 tasks 表 → `sqlite3.Error` 裸崩 → `任务库不可读` exit 1。
- `_thin_wait`：快照 200 但非对象 JSON → `.get` AttributeError → isinstance 判 lost；`counters` 非 dict 同 guard。
- `_thin_submit`：409/2xx body 非 dict → isinstance guard 落通用错误行。
- `share_pack`/`share_unpack`：except 仅 ShareError——mkdir/read_bytes/zf.write/_extract_verified 的 OSError 裸崩 → 扩 `(ShareError, OSError)`。
- `parse --out`：`out.open()` 父目录缺失 OSError → 干净报错；**--out 与输入同路径拒写**（exit 2）——原先读毕再写截断源 .tex。
- `web`：`settings.data_dir()` mkdir OSError + `uvicorn.run` bind/gaierror → 各归一 exit 1。

### 瘦客户端

- lost/needs_auth 短路下载：lost 时快照通道已失联清单必同挂、needs_auth 从未产出；fault/cancelled/interrupted 保留下载尝试（部分件由 server 404 决定）。
- `_thin_download` 重写流式：`client.stream` → `.{name}.part` 临时件 → 增量 sha256 → 过了才 `replace`（原 `r.content` 全量进内存 + 半成品留正名）。产物名 `.`/`..`/`\` 非法跳过（原 `dest/".."` IsADirectoryError 崩）。清单/rec 非 dict guard。
- `--wait` 默认值改 `None` 哨兵：原 `wait != 1800.0` 值比较让 `run src --wait 1800`（无 --server）静默漏过 server-only 检查。

### typer 边界

- `--timeout`/`--wait` `min=0.0`；`web --port` `min=1, max=65535`。实测 `--wait -3`、`--port 70000` 均 exit 2。

### 语义边界

- `_export_translator` 重排：显式 `--mock`/`TEXLATE_TRANSLATOR=mock` 最优先；`gateway`+无 key → **exit 2 显式拒**（原静默走网关必败）；无 key 隐式回落 Mock 打 stderr 提示（原静默产占位译文双语书易当真）。硬编码 `100.105.212.52:3003`/`swe-2-medium` → `settings.DEFAULT_BASE_URL/DEFAULT_MODEL`。
- `_doc_gateway` 改读 settings.json **原始键**（新 `_doc_settings_raw`）：`load()` 把缺省 base_url 回填成默认网关——空 settings.json 也探测 tailnet，非 tailnet 用户误诊 fail 且 doctor exit 1。现"什么都没配"→ n/a。

### path 处理

- source/`--cache`/`--work-dir`/`--out`/export 输入/`share unpack -o`/thin `dest` 补 `expanduser()`（与既有惯例对齐；`share pack -o` 未加——C901 预算 + 显式输出路径边缘）。

## 新测试（全离线）

`TestParse`（out 写/同路径拒/不可写）、`TestFetch`（client.is_closed）、`TestThinRun` 9 例（MockTransport：done 下载+sha 对账、409 attach、lost/needs_auth 不碰 files、非 dict 快照、`--wait 0` 超时、submit 422、sha 不符无 .part 残留、`..` 名跳过零请求）、`TestShareErrors`（腐坏 db、-o 落文件下）、`TestRun`（--wait 无 server exit 2 含显式 1800 回归、expanduser、copytree 失败清理）；export/doctor 对应断言。

## 考虑过未修

- `_thin_wait` 单次非 200 即 lost 无容忍：文档化语义 + attach 重跑即恢复，加容忍超 scope。
- `parse` fifo/设备文件 `read_bytes` 悬挂：typer dir_okay=False 不排 fifo，显式喂才触发。
- thin 模式 garbage arxiv id 本地预检：`_valid_id` 是 fetch.py 私有，server 4xx 已干净 exit 2。
- `TEXLATE_TRANSLATOR` 未知值静默忽略、`--server` 子路径前缀被 join 丢弃、`--offline`+`--server` 静默忽略——边缘/已文档化。

## 外部路由

- **share.py**：`unpack_share` 校验中途失败留已写出部分成员，CLI 调用方无法安全清理（dest 可能是用户已有目录）——需按成员名单删或库层 atomic-temp-dir → share 车道（leader 已记 backlog）。
- **latex/api.py**：`parse_file` 的 `main.read_bytes()` OSError 在 cli `parse` 未捕获（exists+readable 后仍有 TOCTOU 窗）；fifo 悬挂同属 → 1d（latex 车道）。
- **arxiv/fetch.py**：`Fetcher` 无 `close()`/`__enter__` 门面，cli 手动 `fetcher.client.close()`——建议 fetch 层补 `close()` → arxiv 车道（leader 记 backlog，小件）。
- **server/settings.py**：`load()` 回填默认值与"是否已配置"不可分——`_doc_settings_raw` 在 cli 侧手解原始 JSON；settings 层可考虑 `raw()`/`has_key` 面（注意 cli.py:1359 helper 与 settings-infoleak 在飞改动可能相邻）。
