# Web 前后端三方审查汇总（2026-09-17）

三个只读 reviewer 分头通读：`server/` API+基础设施层、`server/worker/` 编排层、`web/` SolidJS 前端。leader 抽验了前端 #1 属实（EventSource 首连无 Last-Event-ID → 重放旧 done → close）。已验证安全的面附在各层尾部，避免误报噪音。

## 后端 API/基础设施层（app.py / store.py / settings.py / upload.py / events.py / staticfiles.py / babeldoc.py / __main__.py / share.py）

### High

1. **非回环绑定 + 可伪造 Host 闸 = local 形态全 API 无鉴权暴露，含 key 外泄通道** — `app.py:574-577`、`cli.py:758`、`__main__.py:32`。`request_gate_mw` 在 local 形态只查 `Host` 剥端口 ∈ loopback 白名单（防 DNS rebinding 而非鉴权），非浏览器客户端发 `Host: localhost` 即绕过；`host` 缺席时 `if host and ...` 直接放行（HTTP/1.0 无 Host 可通过）。`--host 0.0.0.0` 无警告。且 local 形态 `PUT /api/settings` 开放；**`X-Texlate-Base-Url: https://attacker` + 无 header key → `resolve_auth`（settings.py:672-675）回落 settings.api_key → 建任务后把部署方 key 发到攻击者端点**。`settings/test` 堵过同类跨槽外泄（app.py:1625-1628），任务建链没堵。修：非 loopback 绑定拒启/强警告；header 给 base_url 时禁止回落 settings key。

### Med

2. **`share_import` 在事件循环上同步整包校验解包** — `app.py:1145-1153`：`write_bytes` + `unpack_share()`（80MB zip 逐成员 sha256 + 解压）同步跑在 async handler；同模块 `share_pack` 已用 `asyncio.to_thread`（app.py:1311）不对称。修：to_thread 卸载。
3. **`task_retry` 破坏性清理在守卫迁移之前，双发可删活任务新鲜 chunks** — `app.py:1415-1473`：守卫读旧 status（1419）→ `DELETE FROM chunks`+`rmtree(base/zh/build-*)`（1453-1466）无条件执行 → `store.transition`（1469）才原子校验。并发 retry：A 转 queued 入队，B 照样 DELETE 抹掉 worker 重插的 chunks；且 B 的 options merge（1467）在 409 前已落库。修：先 transition（原子守卫）再清理再 enqueue。
4. **`RedactFilter` 每条日志记录都 `settings_store.load()` 读盘+解析 JSON** — `app.py:524-528`、`settings.py:734-739`：filter 挂 logger+handler 两处，uvicorn.access 每请求至少 2 次 settings.json 读盘。修：key provider TTL 缓存，或先跑便宜正则命中再取 key。
5. **server 形态跨租户 reuse 返回对方永远读不到的 task_id** — `app.py:797-799`：`find_reusable` 不带 tenant（设计如此），命中他租户行返回 200 + reader_url，但 `_get_task` tenant 检查使其全 404——存在性 oracle + 死链。修：命中时物化 `reuse_hit` 行，或 server 形态直出产物 URL。
6. **`task_delete` 与 retry TOCTOU** — `app.py:1483-1497`：ACTIVE 检查基于旧读，并发 retry 可激活后再被删行+rmtree，dispatcher 出队 `store.get`→None 静默跳过而 retry 方已拿 202。修：`DELETE ... WHERE status NOT IN (active)` 条件写。

### Low

7. 每请求 `settings_store.load()` 同步读盘（`app.py:665-676`）——mtime 缓存。
8. `tasks_list` 无分页 + `SELECT *`（`store.py:350-365`）；`_clean_task_options` 不限 options 体积（80MB body 可落库）。修：选列+分页+入参尺寸上限。
9. `file_get` is_file→FileResponse TOCTOU 变裸 500（`app.py:985-1006`）。修：try OSError→404。
10. `reader_get`/`reader_put` 在 loop 上同步读+解析数 MB dual.json（`app.py:1511`）。修：to_thread 或按版本缓存。
11. 杂项：`recover_startup`（store.py:511-530）不清 stage/不写 finished_at，与 `transition` 终态清理不一致；`_read_body`（app.py:722）非 dict JSON 静默归 `{}`（`PUT /api/settings` 收 `[1]` 返 200 无操作）；upload blob 建行前落盘，崩溃留孤儿 `tasks/{id}/`；`cache_get` 每命中单独 commit；HTTPException 无 `code` 字段、IntegrityError 无专属 handler 裸 500。

### 已验证安全

Host/Origin/Sec-Fetch-Site/Content-Type 四层 CSRF 闸自洽；multipart 字节闸盖 chunked 无 CL；unpack_share/unpack_zip 白名单+对账+tmp 隔离封死 zip-slip/炸弹；transition 单写者无插入窗；server_salt O_EXCL、atomic_json mkstemp+rename、babeldoc 0600 均无泄露窗；`_get_task` 三检 tenant 隔离全覆盖；`_replay_queued` 在 server 形态用部署方 key 重决议实际不可达（设计对但脆，值得注释）。

## Worker 编排层（server/worker/ 全部 12 文件）

### High

1. **to_thread 段不可取消：孤儿线程继续写库/产物/烧 token，retry 竞态毁目录，拖住进程退出** — `compile.py:164-174`、parse.py:53-55、fetch.py:51-60、pdf.py:265、share.py:441 全走 `asyncio.to_thread`；cancel 只在段边界收敛，coroutine 收 CancelledError 后线程照跑。最重的 `_compile_zh`（compile.py:874-921）孤儿可活 30min+（主编译+L2 重译烧 BYOK token+fixloop≤8 轮），期间 `_register` 无终态守卫往已 cancelled 任务的 files 表写产物；用户立即 retry → 新 run `rmtree(zh_dir)` 与孤儿写同目录交错 → 产物树损坏；shutdown `shutdown_default_executor` 被孤儿拖住。修：长段传 `should_cancel` 轮询（`run_babeldoc`/`run_process` killpg 已有模式）+ `_register`/`_log`/`_warning` 终态守卫 + retry 等孤儿退出或拒重进。
2. **`XlatPipeline._drain` 取消时 N 个 worker 协程孤儿化** — `xlat/pipeline.py:1142` `queue.join()` 被 cancel 后 `:1143` gather 不执行，concurrency 个 `_worker` task 无属主继续消费队列打请求烧 token；shutdown 出 "Task was destroyed but it is pending"。修：`_drain` try/finally 里 cancel workers + gather(return_exceptions=True)。

### Med

3. **跨 event loop `aclose` 三处半** — `translate.py:386/395`、compile.py:704/770、611/628、pdf.py:292：client 在 loop-A 用、loop-B 关，loop 已 closed → `call_soon` RuntimeError 被吞 → 连接/FD 泄漏。修：aclose 收进消费它的同一 `asyncio.run` 的 finally。
4. **dispatch 前置段失败 → 行滞留 queued 同进程永不复活** — `runner.py:168-173`：`store.get`/`claim`/`TaskCtx` 抛错 → log+task_done，行仍 queued 但队列项已丢，只有重启救回。修：setup 失败转 fault 或有界重入队。
5. **`_stage_translate` 段头在 loop 线程做多重 O(全文) 同步扫** — `translate.py:83-145`：all_chunks 全量物化、collect_doc_placeholders、`_ph_frag_map`、`_make_glossary`、SegmentCache 每块同步 SELECT——5k 块规模累计秒级 loop 阻塞。修：物化/计算进 to_thread。
6. **`options.concurrency`/`qps` 无上限钳制** — `_opt_int`（events.py:244-266）只钳 `<1→1`：concurrency=500 → Semaphore(500)（translate.py:121）可打爆自己网关。修：加 `hi` 参数钳位+warning。

### Low

7. `stop()` 对 `_current[1]` 二次 cancel + `except (CancelledError, Exception)` 吞自身取消（`runner.py:97-111`）。
8. 终态后非状态写无守卫（compile.py:166/171 progress、`_register`、teardown 的 publish——`_doc_emit` pdf.py:385 有守卫没拉齐）。
9. 错误码出枚举：`html.py:116` `no_html_source`、`:256` `translate` 不在 store.py:169 `ERROR_CODES`。
10. `_emit_html_dom` 每块 `zh.find(data-chunk=…)` 全树扫 O(n²)（`html.py:302-316`）。修：一遍 find_all 建索引。
11. doc 路每 unit 一条 chunk 事件打满 EVENT_CAP=2000，Last-Event-ID 重放丢早期事件（`pdf.py:355-368`）。修：与 tex 路对齐批量合并。
12. `find_reusable` 命中行被并发删除 → 零产物判 done（`fetch.py:190-213`）。修：物化计数 0 降级自译/fault。

### 已验证安全

单写者纪律贯彻（worker 线程 store/bus 全经 `_on_loop` 回弹）；`stream` subscribe-before-replay+seq 去重+终态兜底正确；recover_startup+_replay_queued+chunks 三级断点恢复完整；transition 守卫/put_file upsert/显式事务/run_babeldoc should_cancel+killpg/append_event 滚动截断均正确；secrets 不入库、scrub 面齐。

## 前端（web/ 全部）

### High

1. **retry 后 SSE 全量重放旧事件 → live feed 永久假死、任务行回写成 done** — `stores/tasks.ts:182`、`api/client.ts:623-648`、`pages/Reader.tsx:134-139`。【leader 抽验属实】`new EventSource` 首连无 `Last-Event-ID` → server `events_since(0)` 全量重放（retry 不清 task_events，EVENT_CAP=2000 滚动）→ 命中上一轮 `done` 帧即断流，客户端 `close()`——此后本轮真实事件无人监听，任何 retry 过的任务进度页冻结/显示旧 done。`on()` 已把 lastEventId 递回调但 handler 全丢弃。修：按 task 记 seq 水位线丢 `seq≤水位线` 的非 snapshot 帧（snapshot seq=0 恒放行），或服务端加 run 世代号。
2. **PdfPane 卸载不销毁 pdf.js 文档，每次切栏泄漏整份 PDF** — `reader/PdfPane.tsx:146-147` onCleanup 只 cancel rAF；上游 `@pdfslick/solid` effect 无 `loadingTask.destroy()`。`paneVisible` Show 切栏/keyed 重挂/离开 Reader 每次泄漏一份 PDFDocumentProxy+worker 解析态（arXiv PDF 10-50MB）。修：`onCleanup` 里 `s?.unbindEvents(); void s?.document?.loadingTask.destroy()`。
3. **每任务一条 EventSource → HTTP/1.1 六连接上限饿死全部 API** — `stores/tasks.ts:85` `refresh()` 对所有非终态任务 `watch`；uvicorn 裸 h11 同源。≥6 活动任务时 6 条连接被 SSE 占满，其余 /api fetch+pdf.js range 拉取全排队 → 应用假死。修：聚合事件流端点 `/api/events` 单连接多路，或只 watch 聚焦任务其余轮询。

### Med

4. **`event: error` 具名帧连带触发 `es.onerror` → transport 永久误显"重连中"** — `client.ts:650-653`：SSE `event: error` 帧 dispatch type=error 的 MessageEvent，`onerror` 同样被调且 readyState=OPEN → "reconnecting" 卡死（`Reader.tsx:876` 徽标误显）。修：`if (ev instanceof MessageEvent || "data" in ev) return;`。
5. **DomPane 异步 onMount 无销毁守卫 → stale handle 注册** — `reader/DomPane.tsx:82-99`：fetch 在途时卸载，`onReady` 仍把 handle 挂到死 DOM，`saveNow` 可能持久化 `{page:1,fraction:0}` 覆盖真实阅读位置。修：disposed 旗标。
6. **滚动路径每事件 3×O(N) DOM 几何查询** — `sync.ts:101-118`+`Reader.tsx:326-329`：每 scroll 事件（含对侧回声）触发 3 次 `querySelectorAll("[data-chunk]")`+逐元素 offsetTop（强制同步布局）→ 大文档滚动掉帧。修：几何缓存+ResizeObserver 失效+rAF 节流。
7. **HtmlPane `data-chunk="${c.seq}"` 未转义插值 → 属性逃逸 XSS** — `HtmlPane.tsx:81`：inner 过 DOMPurify 但外层 section 字符串拼接，`c.seq` 含 `"` 即注入任意 HTML 绕过白名单；dual.json 经 .share.zip 导入是外部输入。修：`Number.isInteger(c.seq)` 闸或 setAttribute。
8. **两个 sanitize profile 都放行 `<style>` 标签与 `style` 属性** — `sanitize.ts:9-27`：`<style>body{display:none}` 或 `position:fixed;inset:0` 遮蔽整个应用 chrome（LLM 译文与 arXiv DOM 两路可达）。修：HtmlPane PROFILE 禁 style tag+attr；DomPane 至少禁行内 style。
9. **`parseArxivId` 不认 legacy 形态 URL** — `Home.tsx:25`：`hep-th/9901001` URL 形态被拒（node 实测），裸 id 可以。修：捕获组 `[^\s?#]+?`。

### Low

10. 构建产物双份 pdf.worker（各 ~1.26MB，vendored + `?url` 死重）+ `index.js` 单 chunk 1.08MB 全量 eager（Home/Settings 也付 pdfjs+katex+marked）——Reader lazy() 分包；`chunkSizeWarningLimit:3200` 淹了真告警。
11. TaskList：删除在飞时其它行删除按钮点了静默无响应（`TaskList.tsx:74`）；doc-kind 行缺 artifacts 时每行一次 `api.files` 懒拉 N 请求突发（`:35-38`）。
12. transport badge 对 closed/初态也显示"重连中"（`Reader.tsx:876-879`）——三态分文案。
13. 零星：Settings `catch` 死代码（refresh 永不抛，加载失败静默出默认表单）；`t.files` 缺 `src.html` 标签；`mergeChunkItems` 不防超大 seq OOM；live 条目终态后常驻单调增长；`.pane-html` 无 tabindex 键盘不可滚；zoom 控件对 html/dom 是死控件仍显示；`swapped` 不持久化刷新丢失；reader 404 任务反复触发 `loadReader`。

### 覆盖缺口

`openTaskEvents`（SSE 层）零测试——恰是 #1/#4 所在层，值得补假 EventSource 单测面。

## 优先级建议

**第一批（用户能直接踩到）**：前端 #1（retry 假死）、#2（PDF 内存泄漏）、worker #1+#2（取消孤儿，同根因一起修）、前端 #3（六连接上限）。

**第二批（安全/健壮）**：后端 #1（Host 闸+key 外泄通道）、#3（retry 清理顺序）、#6（delete TOCTOU）、前端 #4/#7/#8（error 帧误显、两处 XSS 面）、worker #4/#6（queued 滞留、并发无上限）。

**第三批（性能/打磨）**：后端 #2/#4/#7/#10（to_thread 不对称、读盘热点）、worker #5/#10（loop 阻塞、O(n²)）、前端 #6/#10（滚动几何、分包）、后端 #8 分页。
