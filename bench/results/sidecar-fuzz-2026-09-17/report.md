# sidecar-fuzz — server settings/babeldoc/staticfiles 边界对抗测试

> 2026-09-17 收口。交付 `tests/test_fuzz_sidecar.py`（1436 行，commit `d5b545c`）：**49 passed + 11 xfailed(strict, 0 xpass)**，ruff check/format 双净。全量 collect 4083 tests 零破坏。

## 缺陷台账（11 族，全实证 repro）

| # | 位置 | repro | 影响 | 修法 |
|---|------|-------|------|------|
| D1 | settings.py:260-278 `_load_quota`/`_load_concurrency` | settings.json `"concurrency": 1e999`/`Infinity`/`"quota_max_tasks": 1e999` → `int(inf)` OverflowError 逃逸 `(TypeError, ValueError)` catch | **最强**：每次 load() 都炸 → GET/PUT /api/settings + `_auth` 全 500 直到手删文件 | except 元组补 OverflowError |
| D2 | settings.py:223 `_normalize_updates` + :205 `_check_quota` | `save({"concurrency": None\|[3]\|inf})`、PUT `{"quota_max_tasks": 1e999}` | TypeError/OverflowError 逃逸 `except ValueError` → PUT 500（app.py:1488）；`_clean_task_options` 已兜同款（app.py:333-335）settings 路漏 | catch TypeError/OverflowError → ValueError |
| D3 | settings.py:310-333 + xlat/state.py:46 | settings.json `"model": "x\ud800y"`（lone surrogate）→ save() atomic_json `ensure_ascii=False` UnicodeEncodeError | 全 save 砖化；**部分写**：connections.json 先写成功 settings.json 后死 | load 时 sanitize 字符串字段（isprintable 闸）或 atomic_json 容错 |
| D4 | settings.py:320-333 | `engine:"nuclear"`、`target_lang:"klingon"` load 时 `str()` 直通 | public() 回垃圾；任务创建永 400；与 quota/concurrency/origins 容错不一致 | load 白名单校验枚举，回落默认 |
| D5 | settings.py:118-138 + :169-185 | `validate_base_url("http://h:abc")`、`_parse_origin("https://h:99999")`、`"http://h:80:90"`、`"http://h:-1"`、`"http://@host"` 全收 | urlsplit 端口校验延迟到 `.port` 无人触；空 userinfo 滑过 `u.username or u.password` 真值判。origin 侧死 CORS 条目；base_url 侧存值在请求时才炸（httpx InvalidURL） | `u.port` 探针 + `'@' in u.netloc` 闸 |
| D6 | settings.py:169-185 | `_parse_origin("HTTP://EXAMPLE.COM")` 原样返回 | 存下的 CORS 条目永不字节匹配浏览器归一化 Origin 头——静默死配置 | return 前 scheme/hostname 小写化或拒收 |
| D7 | settings.py:414-431 | `server_salt` 双线程首调竞态（patched token_hex 确定性复现） | 败者返回的 salt ≠ 文件内容 → 其 `tenant_for` 指纹重启后不可解 | `O_CREAT\|O_EXCL` 原子创建或加锁 |
| D8 | settings.py:555-569 | `logger.exception` 异常文本含 api key | filter 只洗 `record.msg`/`args`——`Formatter.formatException(exc_info)` 绕过 → key 随 traceback 明文打印；恰恰违背其自述「第二道防线」场景（第三方库把请求体塞进异常） | format exc_info → scrub → 写 `record.exc_text` |
| D9 | babeldoc.py:270-285 | tracking json `{"page": "x"}`、`{"page": [{"paragraph": [None]}]}`、trackers `[None]`/`["nope"]`/`[123]` | 内层 `.get` 无防御 → AttributeError 穿 assess_tracking → run_babeldoc → 任务 fault（非干净 failed verdict） | 每层 `isinstance(x, dict)` 闸（顶层已有） |
| D10 | babeldoc.py:86 `_STAGE_ROW_RE` | `Error in part (3/5): kaboom`、`Retrying batch (2/10) after rate limit` | `text (n/m)` 行被当 stage-table 行 → 不到 `on_log`；error regex 要 `part \d+:` 也不进 errors——**静默吞没** | 要 rich-table 标记（━/%）或 stage 名白名单才算 stage 行 |
| D11 | babeldoc.py:177 | `write_config(api_key="k-\U0001f600")` | `json.dumps` 出 `😀` surrogate-pair 转义——合法 JSON 非法 TOML 标量 → tomllib/configargparse 拒 → sidecar 配置成死文件 | `ensure_ascii=False`（UTF-8 是合法 TOML） |

## 未钉观察（实证非缺陷）

- `_judge_run` 全 rc×timeout×scanned×outputs×track 矩阵：0 违例（status∈{ok,degraded,failed}、code iff failed、retryable=False iff scanned_pdf）。
- `_classify_rc` 优先级正确：auth>rate>compile；空 feed 合理默认。
- `harvest_outputs` glob-meta 词干（`a[1]`/`a*b`/`a?c`/`a b`）经 glob_escape 正确 round-trip；`a?` 不误配 `aX`；`.no_watermark.` 优先。
- `_Feed` 抗任意字节/ANSI/截断 UTF-8；errors 有界去重；`_tail`≤40；`\r`/`\n`/`\r\n` 帧等价。
- `progress >100` 下游 worker 已夹（`30 + min(65, …)`）。
- `_openai_sdk_root("http://h/v1/v1")` 原样返回——validate_base_url 已闸输入，不可达。
- `__main__._port` int() 怪癖（`" 80"`/`"+80"`/`"8_0"`/`"８０"`）均收敛合法端口——matrix 记档，无闸违。
- `_load_concurrency(0)` → 3（falsy-`or` 怪癖——0 本就存不进）。
- `{"api_key": 123}`/`{"model": 123}` str-coerce 非拒——与 D4 不一致注记同族容错语义。
- `install_log_scrub` 幂等（每 logger/handler 恰一 RedactFilter）。
- 符号链接 `TEXLATE_SPA_DIR` → realpath 下缓存头正确；穿越（`..`/`%2e`/double-write）全 4xx；子目录 index.html no-cache；深层 `assets/` immutable。
- `token[=:]\S+` 洗全 span（key+载体）——强于需要，无碍。
- `https://a.com/?`（空 query）收且归一——合理。
- 空 userinfo `http://@host` 双校验器均滑——并入 D5 钉。
- PUT body 收非严格 JSON `Infinity` 字面量（Python json.loads 默认）——即 D2 投递载体。
- `write_glossary_csv` 敌意字段（引号/换行/NUL）csv round-trip 正确；空表不写文件。
- `cjk_ratio` 对垃圾输入不抛 → None（sanity 信号断不了链）。
