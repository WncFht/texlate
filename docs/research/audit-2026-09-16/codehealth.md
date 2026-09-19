# 代码健康 + 安全面审计（codehealth）

HEAD `f461683`，审计范围 `src/texlate/`（61 个 py 文件）。只读审计：跑 ruff/grep、逐文件阅读，无代码改动。

## 结论速览

- `grep -rn "TODO|FIXME|XXX|HACK" src/`：**0 命中**，无标记债务。
- `uv run ruff check src/`：全绿；`uv run ruff format --check src/`：61 文件全部已格式化。
- 异常纪律：全库 **无裸 `except`**；broad except 要么带 `noqa: BLE001`+原因注释，要么是 log+degrade 语义；两枚 `except` cleanup+raise（`xlat/state.py:50`、`server/store.py:552`）语义正确。无静默吞错返回错误值的点。
- 死代码结论：v1 管线不是死代码（`TEXLATE_NO_EXPAND` 回退 + `*_v1` 显式入口 + bench 双跑，文档明记"并存期基准对照"），但 dispatch 路径零测试覆盖；真正死了的是 `RedactFilter`（见下）。

## 债清单（按严重度排）

### H1. `server/worker.py:840-848` — `options.main` 越界逃逸（真实漏洞）

```python
cand = ctx.base_dir / override  # override 来自 retry body / upload form 字段
```

无 confinement 检查：`override` 为绝对路径时 `Path / absolute` 直接丢弃 base_dir；`..` 串也能逃出任务目录。`is_file()` 通过后 `ctx.main_rel` 指向树外文件 → `compile()` 以 `cwd=parent`、`-output-directory=<parent>` 在树外写构建产物；`normalize`/`inject` 的 in-tree 假设被架空。server 模式下任意租户对自身任务即可触发，本机模式下是自伤。修复：`cand.resolve().is_relative_to(ctx.base_dir.resolve())` + 拒绝绝对路径。

### H2. `server/settings.py:350` `RedactFilter` 是死代码 + `xlat/client.py:161` 远端回显落盘

`RedactFilter` docstring 自称"防线 #2"（logging filter 擦 api_key），但全库无任何 `addFilter`/`install` 调用——**从未挂载**。叠加 `xlat/client.py:161`：

```python
msg = f"HTTP {status}: {body[:300]}"  # body = 远端响应体，攻击者可控
```

该字符串进异常 → `worker._fail` → `error_json` 持久化到 SQLite + `log.exception` 进日志。恶意/被控网关可在响应体里回显 `Authorization: Bearer sk-...` 形状的串（或任何 secret 形态），写进 DB 与日志，直接击穿"key 绝不进 tasks/files/日志"的不变量。目前只有 `settings_test` 端点和 compile.log 调 `scrub()`。修复：app 启动时把 `RedactFilter` 挂到 root logger，且 `_fail` 前对 `str(e)` 做 `redact()`/`scrub()`。

### H3. `compile/fixloop/ctan.py::_overlay_members` — `"tree"` 模式路径穿越 + 远端解压无上限（latent）

`overlay="tree"` 分支只挡 `name.startswith("../")` 前缀：中段 `a/../../x`、绝对名 `/x`、`\x`（POSIX 下按相对处理但语义不定）均漏过 → `dest / rel` 逃逸 + `mkdir(parents=True)` 树外建目录写文件。当前生产路径只用 `"flat"`（basename，安全），`"tree"` 仅被 `tests/test_fixloop_ctan.py:113` 覆盖——**带洞的死参数**，接线前必须修（`PurePosixPath` parts 全量 reject `..` + abs）。同文件 `fetch_package`/`fetch_tlpdb`/`_http_get`：`httpx.get` 无大小上限、`lzma.decompress(raw)` 无上限 → 恶意/失陷 CTAN 镜像 xz-bomb → 内存 DoS。

### M1. `server/app.py::_create_and_enqueue` 复用查询跨租户（存在性预言机 + 功能缺陷）

`store.py:292-309` 的 `find_reusable`/`find_active_by_cache_key` **不带 tenant 过滤**。server 模式下 A 租户可借 `cache_key` 探测 B 租户任务是否存在（timing/复用命中差异），且命中后返回的 task_id 会被 `_get_task` 的租户检查 404 掉——既是预言机又是破的功能路径（local 模式 tenant 恒 `local` 不受影响）。

### M2. `server/worker.py:1321-1332` `_make_glossary` — 任意文件读 + 提示词外泄通道

`options["glossary"]` → `Path(gpath)` 无 confinement：可读任意 `.csv`/`.yaml`；内容注入 LLM system prompt → 发到远端 endpoint。server 模式下等于给租户一条"读宿主文件 → 经自己控制的网关外泄"的通道。应限制在任务目录内。

### M3. `compile/sandbox.py` — Linux 无沙箱（设计声明但值得复核）

`sandbox_wrap` 的 SBPL profile 只在 macOS 生效，Linux 原样返回 cmd——真实隔离只剩环境白名单 + `openin_any=p`/`shell_escape=f` + `-no-shell-escape`。kpathsea 变量靠 TeX 侧执行，非内核强制。`docs/` 有声明，但与 H1 叠加后（编译 cwd 可到树外）风险被放大。

### M4. `compile/sandbox.py::child_env` — `env_extra` 可覆盖强制变量（footgun）

`env.update(extra)` 在 `_ENV_FORCED` 之后执行：任何未来调用者传 `env_extra={"TEXMFCNF": ...}`/`shell_escape` 类键即可拆掉 `openin_any=p`/`shell_escape=f` 防线。当前无调用者传 extra——在 update 前对 extra 键做白名单/拒绝 `_ENV_FORCED` 键即可。

### M5. `validate/l1.py::_env` — `dict(os.environ)` 全量传给 node 子进程

L1 校验器拿到完整环境（含 `TEXLATE_API_KEY` 等），与 compile 侧白名单策略不一致。node 脚本若在沙箱外跑被污染工程触发，等于扩大 secret 暴露面。

### M6. `server/worker.py` babeldoc 子进程 — `proc.communicate()` 无 timeout + cancel 孤儿

`_run_pdf` 里 babeldoc `communicate()` 无超时，任务卡死即永久挂；cancel 路径杀不干净时子进程成孤儿。

### M7. `server/worker.py` `Secrets`/`TaskCtx` dataclass — repr 含 `api_key`（latent）

默认 `__repr__` 打印全字段；今天没有 `repr(ctx)`/`repr(secrets)` 调用点，但任何将来的 debug log 都会泄密。`field(repr=False)` 一行可堵。

### L1. v1 fallback dispatch（`TEXLATE_NO_EXPAND`）零测试覆盖

`latex/api.py:79-114` 的环境变量分叉无任何用例；v1 自身有测试，但"env 置位→真的走了 v1"没有。要么补两个 monkeypatch 用例，要么定 EOL 把 v1 面收进 `bench/`。

### L2. 杂项低危

- `app.py` `_parse_multipart` 的 `Content-Length` 只作 advisory，`_read_body` 无字节上限（有 80MB `UPLOAD_CAP` 但检查在读完之后——已读进内存）。
- `options.concurrency` `int()` ValueError 冒成 500 而非 400。
- `unpack_zip` 重名成员静默覆盖（tar 侧有 warning，zip 侧无）；tar dir 成员不做 casefold 碰撞检查（文件成员做了）。
- `fetch.py` GET body 全读进内存才查 `DL_CAP`（post-hoc；arXiv 可信度高，风险低）。
- `settings.save()` 把未知键合入 settings.json，load 时丢弃——cosmetic。

## 死代码判定

| 代码                                                  | 判定                                                             |
| ----------------------------------------------------- | ---------------------------------------------------------------- |
| v1 `flatten.py`/`scanner.py`/`parse_*_v1`/`new_state` | 活：`TEXLATE_NO_EXPAND` 回退 + bench 对照，文档明记并存；但见 L1 |
| `RedactFilter`（settings.py:350）                     | **死**：从未挂载，docstring 虚报"防线 #2"——见 H2                 |
| `ctan.py overlay="tree"`                              | **死参数带洞**：生产只走 `"flat"`——见 H3                         |
| `macro_table.parse_argspec`/`flatten.strip_doc_shell` | 活：v2 gullet/segmenter 共享                                     |
| `mouth`/`batch`/`placeholders`/`retry` 等模块         | 活：修正 FQN 后 grep 均有消费者                                  |

## 已验证干净（抽查过、无 finding）

- `arxiv/unpack.py` `_TarWalker`：NUL/abs/drive/`..`、raw linkname + 解析后 `_in_tree`、setuid/gid、20k 成员/100MB 单文件/512MB 总量、casefold 改名、按 header 大小截读——遍历闭包全程 in-tree。
- `server/store.py`：全参数化 SQL；4 处 `S608` noqa 的 f-string 只插内部白名单列名。
- `server/app.py`：`valid_task_id` 白名单、`file_get` kind 白名单 + `resolve().is_relative_to`、local 模式 CSRF middleware、上传文件名 sanitize。
- `compile/engine.py`：全部 list-argv 无 shell；`main_path.name` 只取 basename；`install_file` 的 pkg 来自 tlpdb 索引 + `[\w.-]+` 正则，payload 不进 tlmgr argv；`compiled_dependencies` `is_relative_to(root)`。
- `fixloop` `{payload}` 链路：log → classify → rules.yaml → install_file/run_tool/builtins，argv 恒 list 单元素不可分词，shim 写盘被 `shim_map`/`cs_set` 键门禁。
- `unpack_zip`：`..`/abs/`_BAD_ZIP_NAME` + parts 过滤，4000 文件/100MB 单/300MB 总上限；实测 CPython `ZipExtFile` 按声明 `file_size` 截断 + CRC 校验，伪造声明大小的 zip 直接被 `BadZipFile` 拒——cap 可信。
- `compile.log` 已 `scrub()`（worker.py:1180）；settings.json 0600；`settings.public()` 剥 api_key；`validate_base_url` 拒 userinfo/query/fragment 且远端强制 https。
- `xlat/pipeline.py` broad except 全部为文档化降级（batch→singles、chunk crash→skip），worker 线程不会死。
- `normalize.py:555` 外部引用检查（`..`/abs/`\input{|cmd}` 都 flag）；写盘限 rglob 出的 in-tree 路径。
