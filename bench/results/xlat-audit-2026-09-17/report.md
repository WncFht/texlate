# xlat-audit — src/texlate/xlat/ 审计交付

> 2026-09-17 收口。落地 `af1ca16`（xlat/{client,pipeline,batch,state,glossary}.py + 8 测试文件，+438/-75）。自验 xlat 全家+消费方 417 绿、ruff 双净。探针 tmp/xlat-audit/。

## 修复清单（14 项）

### client.py（契约面硬化）

1. **DecodingError 逃逸**：`httpx.DecodingError` 是 RequestError 非 TransportError（gzip 损坏形态），四请求点 except 漏接 → 逃逸归 crash 零重试。统一接 `(TransportError, DecodingError, SSLError)` → RetryableHTTPError。
2. **InvalidURL 逃逸**：plain Exception（坏端口 base_url 请求期抛）。四处前置 `→ ChatError(retryable=False)`（确定性配置错）。
3. **BYOK api_key 泄漏**：`classify_status` 嵌 `body[:300]`——网关回显 Authorization 时 key 进异常+降级 log。四处改传 `redact(resp.text, api_key)`；非 JSON 200/anthropic error 分支同过 redact（两 parse 转实例方法取 key）。
4. **non-JSON/畸形 200 永久 skipped**：代理 HTML 错误页是瞬时形态。新 `MalformedResponseError`（status=200/retryable/max_tries=2，EmptyContentError 同族，可切模）。
5. **list_models 崩溃面**：JSON-list 顶层 `data.get` AttributeError、str 成员 `"id" in m` 子串误判。非 dict/data 非 list → Malformed；成员 dict 过滤。
6. **畸形 base_url 构造期炸**：`urlsplit` 裸 ValueError → provider_for_url 落 "custom"、is_free_gateway_url 落 False。
7. LengthTruncatedError docstring 修正（降级臂实际 ~16 调用非 4）。

### pipeline.py

8. **切片丢 ph_fragments**：`ChunkIn(f"{cid}~{i}")` 不传 → 抄回修复臂对切片失效。
9. **二次 run prompt 陈旧**：`_materialize` 重建 `_doc_glossary` 但 `_prompts` memo 不清 → 换文档旧术语块残留。补 `_prompts.clear()`。
10. **段级缓存毒化不自愈**：`_cache_store` 只挡 leftover_ph；ph_in_cs/bare_cs 毒译落缓存 → 命中旁路校验每轮降 fault 永不修。新 `_interceptable` 三网合并：写入侧全挡 + 命中侧 `_cache_hit` 删旧毒落回重翻自愈（三条契约测试语义重写：旧「命中→fault」钉的是 bug）。
11. **concurrency=0 挂死**：`range(0)` 无 worker `queue.join()` 永等。`__post_init__` 钳 ≥1（hard_limit 同）。

### batch.py / state.py / glossary.py

12. `split_long_chunk(max_chars=0)` 死循环 → `<1` 直返 `[text]`。
13. corrupt state.json 不隔离+顶层非 dict 炸 → 按 load_cache 同口径改名 `state-invalid-<rand>.json` 隔离。
14. BOM CSV 首行黏 U+FEFF → `utf-8-sig`。

## 新测试（+21，契约重写 3）

TestTransportAndContract ×11、TestConfigClamps/TestSplitPieces/TestPromptReset/TestCachePoisonGuard×3、state 隔离×2、batch max_chars、glossary BOM；三条 `test_poisoned_cache_hit_*` 重写为 evicted_and_retranslated。

## 未修（理由） / 外部路由

- `RetryPolicy.max_tries≤0` 无行为差未钳；chat_stream SSE 坏行按设计跳过；`_parse_anthropic` error 分支保留 non-retryable（OpenAI 方言主路径）；discover_free_models 不对称是既有测试钉的设计。
- **cli.py `_export_translator`(:766-803)** ChatClient 不 aclose——同款 httpx 泄漏 → **leader 已认领修**。
- **e2e.py `_env_judge_pass`(~187)** `asyncio.run` 在 running loop 上下文会 RuntimeError + pipeline 绑错 loop → 1d。
- **worker.py `_opt_int`(~1350)** 整型旋钮无零/负钳 → server-persist-audit 在飞区已转。
