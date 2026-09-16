# server-security-sweep — SEC-1..7 修复落地交付

> 2026-09-17 收口（修复批）。落地 `80539fd`（share.py + app.py + settings.py + tests/ 共 8 文件 +568/-37，新增 tests/test_server_gate.py 376 行 28 例）。只读审计报告见同目录 `report.md`。worker.py / texlog.py 未碰。

## 逐项实现

### SEC-1 share 解压炸弹（share.py）

新增 `_ARTIFACT_MAX=64`（manifest artifacts 条目数上限，`_manifest_checked` 里拒）+ `_INFLATED_MAX=300MB`（manifest 声明 bytes 合计预检）。两闸都 raise ShareError，HTTP 面 /api/share/import → 400 share_invalid，与 test_fuzz_share 的语义域一致。`_extract_verified` 改为 `zf.open` + `fp.read(art.size+1)` 有界读——目录 file_size 谎报时不再先分配整段内存；成员真实尺寸与声明不符在既有对账里拒，声明总量即解压上界。bzip2/lzma 评估结论：上界钉在解压后字节，与压缩率无关，常数 docstring 已注明。

### SEC-2 server 匿名回落（settings.py resolve_auth + app.py 闸）

server 形态无 X-Texlate-Key 时 `resolve_auth` 不再回落 settings/env，`api_key=""` `source="none"`；读面落固定匿名桶 `tenant_for("")`，永不含部署方凭据。app.py `request_gate_mw` 里 server 形态 mutation 无 key → 401 auth_required（仅 POST/PUT/DELETE/PATCH on /api/*；读面开放）。带 key 请求行为不变，既有 server 测试 fixture 未破。

### SEC-3 CSRF+Content-Type（app.py）

`local_only_mw` 扩展为 `request_gate_mw`（local+server 共用）：mutation 且 /api 时，Origin 在 `app.state.cors_origins` allowlist → 放行（CORS 部署面）；`Sec-Fetch-Site: cross-site` → 403；Origin 存在且 scheme+netloc（含端口）≠ 请求 scheme+Host → 403（localhost:9999 端口洞已封，loopback 族内跨 origin 也拒）；两者皆无 → 放行（curl/非浏览器）。`_read_body` 非空 body 要求 `Content-Type: application/json`（容许 charset 参数），违则 415 unsupported_media_type；空 body 无 CT 的 curl 式 POST（retry/cancel）照旧。local 形态同样吃这套同源闸。

### SEC-4 settings/test 跨槽（app.py）

`body.base_url` 提供且 `body.api_key` 缺 → 400「覆盖 base_url 须同给 api_key」，与 settings.save 新槽位 key 查找设计对齐；不带覆盖走已存 pair 不触发。

### SEC-5 ".." 文件名（app.py upload）

safe-name 计算提前到 mkdir 前，re.sub 白名单后 `safe in (".", "..")` → 400 无孤儿目录；mkdir+write 移入 try cleanup 块（两都做）。

### SEC-6 local Host 校验（app.py）

local 形态 Host 剥端口须 ∈ {localhost,127.0.0.1,::1}（`_host_only` 处理 `[::1]:p` 与裸 `::1`），违则 403——DNS rebinding 收口。server 形态不查（反代/域名部署面）。Vite dev proxy 不受影响：no changeOrigin，转发 Host 仍 loopback。tests/conftest.py 加 autouse fixture 把 TestClient 默认 base_url 改为 `http://localhost`（setdefault，仅补未指定者），60 处 TestClient 调用零改动。

### SEC-7 model 控制字符（settings.py validate_model）

新增 `not v.isprintable()` 拒控制字符（`\n \r \t \x00 \x1b` 等），日志/事件注入面收口；正常名与 CJK 放行。

## 测试

tests/test_server_gate.py 新增 28 例全覆盖——解压两维（count>64、aggregate 声明 2×200MB>300MB→ShareError；HTTP 面 400 share_invalid）；server 匿名 translate/upload/delete/cancel/PUT settings→401 auth_required；匿名 GET tasks 空桶、带 key 任务对匿名 404；resolve_auth 单元钉 server→("","none") / local→settings key；local+server cross-site 403、Origin localhost:9999 403、same-origin 202、CORS allowlist 放行、无头 curl 过闸；text/plain→415、charset 容差、空 body 无 CT 过；base_url 无 key→400；upload ".."→400 无孤儿目录，`"."`/`"a/b/c.tex"` 等→202；local 外域 Host→403、loopback 各形态→200；model 控制字符→ValueError、translate 带控制字符→400。

既有测试适配：3 处 bad-JSON 用例补 `Content-Type: application/json` 保持原断言意图；2 处 server-mode 403 用例补 X-Texlate-Key（匿名现在 401）；2 处 loopback-origin-ok 语义翻转改钉 403（新同源规则）；byok test_unreachable_endpoint 补 api_key（SEC-4）。

## 自验

`pytest -k "server or share or app or byok or settings or gate"` → 637 passed, 2 skipped, 5 xfailed；ruff check 净、ruff format --check 净。全量套件 2995 passed，4 处失败在 test_bench_regression/test_segmenter_semantics（latex 层在飞，非本批引入）。leader 复核：test_server_gate+byok+api+fuzz_share 94 passed + 5 xfailed。

## 追加单（SEC-8..12，fuzz-roundtrip 钉住的 5 项 share 缺陷）

交付时遗漏，leader 复核后已派回：UnicodeDecodeError 逃逸（share.py:300-304）、zlib.error 缺 except（:387-395/:291-299）、NotImplementedError 构造侧缺（:415-421）、pack 侧 manifest 尺寸闸、rename 非原子发布 + test_fuzz_share 5 个 xfail 摘钉。另起 commit 落地。
