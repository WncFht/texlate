# server-security-sweep — server 面只读安全审计

> 2026-09-17 收口。只读任务零代码改动；探针 `tmp/server-security-sweep/`（probe1_share_zipbomb.py / probe2_app.py 可重跑，进程内 daemon HTTP server 已随退）。修复路由 → server-security-fix（新 agent，本批全部落我方 lane：share.py/app.py/settings.py）。

## 端点矩阵结论

auth 覆盖除匿名回落外**净**：_auth 覆全部 mutation、tenant 经 _get_task 统一 404、密钥不进 log/SSE（RedactFilter/scrub）、settings.json 0600。path traversal 净（_name_ok 扁平白名单、index url confine、valid_task_id+_get_task 双闸、starlette 内建遍历检查）。注入净（SQL 全参数化、SSE json.dumps、错误响应 scrub、babeldoc TOML 0600）。SSRF 净（fetch 钉死 arxiv 域、share import 无出站）除 BYOK 设计内残余。

## 确认缺陷（实证级标 ★）

### SEC-1 [高★] share import 解压炸弹 — share.py:337-442

`_manifest_checked`/`_extract_verified`/`unpack_share`：每成员仅 `_name_ok` 扁平名 + sha256 + `≤_MEMBER_MAX(256MB)`；**无聚合解压上限、无成员数上限**。实证：74KB bundle→75MB 落盘；322KB→3002 文件。上限面：80MB 上传闸内 ~320×256MB 高压缩成员 → ~80GB 磁盘。对比 worker.py `unpack_zip` 有 MAX_FILES=4000+INFLATED_CAP=300MB——share 面不对称。修法：artifacts 数上限（真 bundle 2-4 件，16/64 足够）+ 解前聚合 infolist file_size 预算或复用 INFLATED_CAP。**拒绝须落在 ShareError 语义域内**（fuzz_roundtrip 在飞 test_fuzz_share 消费此面）。

### SEC-2 [中高★] server 模式匿名回落烧部署方 key — settings.py:456-497 + app.py:522-545

无 X-Texlate-Key → 回落 settings.json api_key：实证 translate 无 header→202、`secrets.api_key='sk-deployer-key'`；全体匿名调用方共享同 tenant → 匿名 cancel/delete 实证 200。偏离 web-layer.md §6 tenant 强制 header 指纹。修法：server 模式无 header → mutation 401 needs_auth；读面归匿名 tenant（不得继承 settings key）。

### SEC-3 [中★] server 模式无 CSRF + text/plain JSON — app.py:455-471/564-574

CORS 仅 cors_origins 配置时在；simple request 无需 CORS：实证跨站 multipart upload→202、text/plain body JSON→202。与 SEC-2 叠加=任意网页访客烧部署方 key+磁盘。修法：mutation 加 Origin/Sec-Fetch-Site 同源校验（存在才查，保非浏览器 CLI）；`_read_body` 校验 Content-Type: application/json。

### SEC-4 [中★] settings/test 跨槽 key exfil oracle — app.py:1427-1434

`api_key = body.api_key or cur.api_key` × `base_url = body.base_url or cur.base_url` → 已存 key 被打向任意 URL 作 `Authorization: Bearer`。实证 local 模式 sink 捕获 `Bearer sk-victim-key`；local_only_mw 只查 Origin hostname 不查端口（localhost:9999 Origin 实证过）。server 模式被 write_gate 挡（403）。修法：body 给 base_url 时强制同给 api_key（禁跨槽组合）。

### SEC-5 [低★] upload 文件名 ".." → 500 + 孤儿目录 — app.py:915-919

`Path("..").name`=".." 过 re.sub 白名单 → write_bytes 打目录 IsADirectoryError→500；write 在 try 清理块外留孤儿 `tasks/{tid}/upload/`。修法：safe 名排 "."/".."，或 write 挪进 try。

### SEC-6 [低中，推理] local 模式 DNS rebinding 读面

无 Host 校验；rebind 后同源 GET（tasks/files/snapshot）可读；mutation 被 Origin loopback 检查挡。修法：local 模式校验 Host ∈ {localhost,127.0.0.1,::1}（含端口剥离）。

### SEC-7 [低，推理] model 名 log 注入

validate_model 放行 ≤200 字符含 \n → 原样进 log.warning。修法：字符集收紧或 log 前 repr。

### 记档不修（设计内/已记取舍）

- BYOK base_url SSRF 残余：tenant 可令服务端打任意内网主机 /v1/* 并经 redact 错误文本读回响应片段——弱读写 oracle，docs §4 已记取舍。
- upload 内存×并发：每请求 ≤80MB 驻留 RAM 无速率闸——design-internal。
- local_only_mw Origin 端口不查（SEC-4 修法内顺带覆盖）。

## 净项（第 1-6 矩阵逐项声明见正文）

- CORS/Host：除 SEC-3/SEC-6 外净。
- DoS/资源：_cap_request_body 流式闸、starlette multipart caps、manifest≤1MB、EVENT_CAP=2000、订阅队列 512 有界、settings 单写、babeldoc killpg——除 SEC-1/内存并发外净。
