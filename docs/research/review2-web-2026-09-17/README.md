# Web 前后端二轮审查汇总（2026-09-17）

一轮 30+ 发现全部修复落地后（commit 9add538/c820fed/2b01cfb/86eba03），三个只读 reviewer 对**新状态**再扫一遍，专挖优化/升级/重构机会。本报告只含新发现；一轮已修项见 `../review-web-2026-09-17/README.md`。

## 优先级建议（综合三层）

**第一批（小改动大收益）**：worker#1 编译段孤儿收敛（`run_process` 加 `should_cancel` 轮询——一轮 wontfix 的更优解，cancel 常落最长编译段，5s drain 预算在长编译下不成立）；fe-M1 `st-*` 横幅 CSS 失配（fault/partial 渲染成中性灰，一行级修）；fe-M2 Reader 卸载不 unwatch（pin+SSE 槽泄漏，浏览 3+ 活动任务后全降级轮询）；be#1 loop 线程残余重 I/O（upload sniff/write_bytes、share_pack manifest/index_lookup、rmtree 三处 to_thread 收口）；be#4 `options["share"]` 64KB 闸后注入（manifest contributor 无字段上限）。

**第二批（性能热点，可打包一次做）**：`all_chunks` 每任务 5~7 次全量物化（worker#2）；事件写路径双跳事务 + fixloop/babeldoc 日志逐行扇出合批（worker#3 = be#3 同发现）；translate 段 50ms `store.get` 降频（worker#4）；`_PerCallTranslator` 每 unit 建 client 改 loop 绑定缓存（worker#5）；`_emit_html_dom` 4 次全树解析→2 次（worker#6）；babeldoc 进度帧节流（worker#7）；fe-M4 单栏保存抹对侧位置（server positions 字段级合并）；fe-M7 `request()` 无超时；fe-M9 任务行引用重建换 keyed/Index。

**第三批（UX 升级，用户最可感知）**：fe-U1 翻译中流式预览（chunks 实时预览或 arxiv.org 原文预读）；fe-U2 DomPane 加载 veil+失败重试；fe-U3 切栏重挂 PDF（display:none 保活）；fe-U4 HtmlPane content-visibility 分批渲染；fe-U5 任务搜索/筛选/批量管理；fe-U6 暗色主题（CSS 已全变量，~15 变量覆盖）；fe-U7 fatal 页重试钮；fe-U9 document.title 进度；fe-U10 完成通知；fe-U11 partial 嵌 ProgressGrid 显示失败格；fe-U12 html/dom 缩放死控件改 font-size 档；fe-U13 键盘面；fe-U14 小项打包（详见下）。

**第四批（重构/运维面，roadmap 级）**：Reader.tsx 1127 行拆分（texlate-2d 已认领，切口见 fe-R1）；client.ts 748 行拆 types/rest/sse/idem；`ctx.set_option` 收口 options 四步散落 5 处（worker#11）；TaskCtx 17 字段分组（worker#12）；app.py 1876 行拆 APIRouter（be#20）；store.conn 三处逃逸收口 + list_tasks 死代码（be#13）；并行槽位前置盘点（worker#8，改动面已摸清：`_current` 单槽→dict、实例态 per-run 化、编译独立 Semaphore）；产物 GC/TTL + index.jsonl 重建策略（be#15）；server 模式 health 深度 + metrics 面（be#16、worker#13 stage 耗时）。

**测试缺口（med）**：smoke.mjs 两处恒真/零断言（:140 页码、:161 fault seed 只截图）；无 retry 流程冒烟（mock 已天然复现旧 done 重放场景，一轮 #1 回归缺 e2e 面）；DomPane/Toolbar/FindBar/ProgressGrid 无组件测。

---

## Worker 编排层（review2-worker）

### High

1. **drain 预算外孤儿仍写任务目录，retry 进入即交错** — `events.py:124-139` 等 5s 后 warning 放走，retry 立即受理；`engine.compile`（sandbox.py:282 `communicate(timeout=240)` 单点阻塞无轮询面）与 `run_fixloop`（repair.py:170 无 cancel 钩，≤8 轮）孤儿寿命 30min+，继续写 `build-zh/`/`build-en/`；新 run `_compile_zh`（compile.py:913-915）`rmtree+copytree` 与孤儿并发写同路径。cancel 最常落在编译段，窗口是常态。修：`run_process` 加 `should_cancel` 形参（communicate 在 TimeoutExpired 后可合法重入，小步轮询+`_kill_tree` 收进既有超时臂，sandbox.py:282-298 一处改动），`Engine.compile` 透传、调用点喂 `ctx.cancel_flag.is_set`（`run_babeldoc(should_cancel=…)` 同款已验证）；`run_fixloop` 加 per-round 轮询钩。兜底：run 级 epoch 目录 `build-zh-{epoch}` 物理隔离。

### Med

2. **`all_chunks` 全量物化每任务 5~7 次全在 loop** — translate.py:84、_common.py:554（DBStateBridge.load）、translate.py:354、compile.py:277/652/1004/1018、share.py:190/146；`SELECT *` 含全文，5k 块≈每次几十 MB + 百 ms loop 阻塞。修：DBStateBridge 吃段头已读 rows 省一次；`_invalidate_splice`/`_flush_chunk_updates` 只需窄列。
3. **事件写路径每条 = 守卫 SELECT + 3 语句事务 + `_on_loop` 往返** — events.py:196-198 + store.py:895-913；fixloop 逐行扇出（compile.py:561-562）一场上百次双跳事务。修：日志行合批（`\n` join 一条事件）；守卫先查 ctx 本地 terminal 旗标短路，未置才读库。
4. **`_stage_translate` 轮询每 50ms 一次 `store.get` SELECT *** — translate.py:141-148；cancel 事实经 task.cancel() 即达，DB 轮询只是兜底，0.5~1s 一拍不损时效；顺手换 `asyncio.wait`。
5. **doc 路 `_PerCallTranslator` 每 unit 新建 AsyncClient** — _common.py:690-718 + pdf.py:277-285；数百 unit = 数百次 TCP+TLS 握手。修：loop 绑定懒 client 缓存于 self，export 侧 run 包装 finally 收（`_translator_clients`/`_aclose_clients` 现成）。
6. **`_emit_html_dom` 同一 marked 文档 lxml 全树解析 4 次** — html.py:307-318；en/zh sanitize 输入相同可单树先序列化 en 再原地 reinsert 成 zh；marked_html/parse_arxiv_html 给复用变体再省一次，4→2。
7. **`_run_pdf.on_progress` 每帧 `_on_loop`+SELECT+commit 无节流** — pdf.py:211-220；babeldoc tqdm 帧密集重绘每秒数十次双跳事务。修：pct≥1 或 ≥200ms 节流；on_log 并入合批。
8. **并行槽位前置障碍盘点** — runner.py:171 严格串行；翻译段天然可并行，前置改动小：`_current`→dict、`_loop`/`_loop_tid`/`_mock_warned` per-run 化、编译子进程独立 Semaphore。建议记 roadmap 不动手。

### Low

9. `_materialize_reuse` copyfile TOCTOU → 错配错误码（fetch.py:224-235，FileNotFoundError→parse fault 而非 reuse_dead 回退）；copyfile 包 try OSError→按缺失计。
10. `_teardown_translate` 的 `suppress(CancelledError)` 吞二次 cancel（translate.py:193-194）；换 `run_task.cancel(); await asyncio.wait({run_task})`。
11. options「读-改-写-同步 row」四步散落 5 处（fetch.py:80/129/265、parse.py:107、share.py:271/317/348）——`ctx.set_option` 单点封装。
12. TaskCtx 17 字段平铺隐式传递（_common.py:200-256）——namespace 分组或分节注释。
13. 无每阶段耗时结构化度量——`run()` 在 `_stage` 进入点记 monotonic，done 载荷附 `stage_seconds`。
14. `_compile_zh` 抛异常时无降级产物臂——`_build_dual` 可挪进异常臂。
15. 小项：`enqueue` 在 `_queue is None` 时登记 secrets 不排队的启动窗；`_mock_warned` 集合单调增长；`_make_glossary`/`collect_doc_placeholders`/`_make_cache` 每任务重复 2~3 次可按 ctx 备忘。

### 已验证安全（worker）

`_to_thread`/`in_flight`/`_drain_threads` 三处配合正确；cancel 置位链完整无竞态窗；`_drain` 收尸 task_done 语义正确；`_load_resumed` intercept-再过滤顺序正确；`_share_apply` 零命中 raise 先于 flush；`_l2_writeback` 全量重算无漂移；`_FallbackTranslator`/`_AbortingTranslator` 设计正确；无死锁环；teardown exc_info 守卫正确。

## 前端（review2-fe）

### 正确性

- **M1（med）终态横幅警示色全灭** — Reader.tsx:1046/1074 渲染 `st-${status}`，app.css 只有 `.result-banner.warn/.bad`（1684/1689），`st-*` 零匹配 → fault 不红 partial 不黄。修：st→warn/bad 映射或补 CSS；顺手删死 `.err-line`。
- **M2（med）Reader 卸载从不 unwatch → pin+SSE 槽泄漏** — Reader.tsx:135 watch 返回值丢弃、onCleanup 无 unwatch；channel close() 不摘 wanted，rebalance 复活。浏览 3+ 活动任务后槽位被不可见任务占满。修：onCleanup unwatch + 统一 handle close→detach 语义。
- **M3（med-low）dom/html 页码死显示** — pageNums 仅 PdfPane 回写；dom 输 50 可跳但显示恒 "1"；html 禁用仍显 "1 / N"。修：pane onScroll 上报 capturePos(handle).page 或隐藏控件。
- **M4（low-med）单栏保存抹对侧位置** — saveNow 只发可见侧、server keep 整覆写。修：positions 字段级合并。
- **M5（low-med）关 tab 丢最后位置** — saveNow 普通 fetch+1s 防抖。修：pagehide + keepalive。
- **M6（low）pin 任务被删 → 404 重连循环** — 每次 rebalance 重建→404。修：closed 后探活失败即 dropTask。
- **M7（low-med）`request()` 无超时** — health 挂起→首页恒「检测中」。修：`AbortSignal.timeout(15_000)`。
- **M8（low）transport 徽标误显两面** — 降级轮询显「连接已关闭」说谎；首连 reconnecting 闪现误导。修：polling/connecting 态。
- **M9（low-med）任务行引用重建 → SSE 更新整行重挂** — `<For>` 引用判等。修：`<Index>` 或 keyed by task_id。
- **M10（low）onTryHtml 丢任务选项** — Reader.tsx:501-507 只透传 model/lang，glossary/concurrency/guidance 全丢。

### UX 提升（重点）

- **U1（med-high）翻译中零可读内容** — 最长阶段只有格子+日志。a) `GET /api/task/{id}/chunks` + 进度页内嵌只读流式预览（后端小改）；b) 零成本版：iframe/新窗 arxiv.org/pdf/{id} 预读原文。
- **U2（med）DomPane 拉取期全白、失败与空同文案** — 加 veil + 失败文案/重试钮。
- **U3（med）split↔单栏切换重挂 PdfPane → 整份 PDF 重载** — 隐藏侧 display:none 保活（需实测）或先给预期提示。
- **U4（med）HtmlPane 一次性同步渲染全部 chunks** — `.chunk{content-visibility:auto}` 一招先吃大半收益，或 IO 懒渲/rIC 分批。
- **U5（med）任务列表无搜索/筛选/分组** — 标题/arxiv_id 过滤 + 状态 chip + 活动置顶 + 批量清理。
- **U6（med）暗色主题** — CSS 已全变量，`[data-theme=dark]` 覆盖 ~15 变量 + color-scheme + localStorage。
- **U7（low-med）fatal 死路页无重试** — 加「重试」重走 onMount。
- **U8（low-med）行内无快捷操作** — 活动行 ⏻/fault 行 ↻ 省一跳。
- **U9（low-med）document.title 恒定** — 进度页 `${pct}% · 标题`，一行成本多 tab 可辨。
- **U10（low-med）完成无通知** — title 闪烁/favicon 角标/Notification opt-in。
- **U11（low-med）partial 不指出哪些段失败** — ProgressGrid 嵌进 result-banner。
- **U12（low-med）html/dom 缩放死控件** — font-size 档位让控件全域生效。
- **U13（low-med）键盘面太薄** — `1/2/3` 模式、`s` 同步、`[`/`]` 翻页、`?` 帮助。
- **U14（low）小项打包** — needs_auth 加 #/settings 链接；上传客户端预检+处理中不定态+批量拖放；渲染外链 target=_blank；toolbar arxiv.org/abs 直达；≤640px 默认单栏译文；切模式前批注将丢提示；PdfPane 错误 veil 重试钮；fmtRel 静态不刷新 60s tick；列表/reader 骨架屏；Settings providers preset 一键填；share_key 复制钮；分栏拖拽 divider。
- **U15（low）a11y 散点** — `.tp-bar` 无 progressbar 语义；auth-key-input 无 label；`.tb-menu` 无 roving；菜单关闭焦点不回触发源；Segmented 无 Home/End。

### 性能

- P1 Reader chunk 1.03MB：katex/marked/dompurify 仅 html 视图用——HtmlPane 再 lazy 挪 ~300KB 出常用路。
- P2 ProgressGrid 每帧 O(total)：mergeChunkItems slice+copy + cells() 全量重算——5000 段×5000 帧≈25M。
- P3 capturePos 每滚动帧 `[...pages].reverse()`——反向索引遍历不复制。
- P4 loadReader 串行——Promise.all 省 1 RTT。
- P5 其余已干净：index.js 65KB 壳、pdf.worker 单份、lazy+预取在位。

### 重构

- R1 Reader.tsx 1127 行【texlate-2d 已认领】切口：useReadingPosition/useSyncEngine/ProgressView.tsx/ResultPanel.tsx/useSharePack。
- R2 client.ts 748 行拆 api/types+rest+sse+idem。
- R3 TaskChannel.close 双轨语义统一（见 M2）。

### 已验证无问题（fe）

chunk seq 0-based 与 dense 合并自洽；事件 seq 单调不随 retry 重置水位线正确；sanitize 双 profile+CSSOM 净化完整；/pdfjs/* Range 可用；mock retry 保留事件流可复用做冒烟；SyncEngine rAF/回声抑制/dispose 正确；幂等键生命周期正确；watch 幂等/终态收敛/404 dropTask 正确；Toolbar draft/Segmented roving 正确；Home 拖放/busy/alive 正确；Reader retry 全态复位顺序正确。

## 后端 API/存储层（review2-be）

无 high。

### Med

1. **loop 线程重 I/O 残余** — upload sniff+write_bytes ≤80MB（app.py:1239/1255）、share_pack manifest+index_lookup（app.py:1428/1446，worker 侧同面已 _to_thread 而 API 侧在 loop）、rmtree 任务目录（app.py:1643/1694/1272）。修：to_thread 包一层。
2. **quota 形同虚设 + key 轮转绕过** — incoming_bytes 只计 upload/share_import（app.py:843-871）；tenant=sha256(key) 换 key 即新桶。定位设计缺口：文档明示或加全局/每 IP 兜底。
3. **事件写路径双跳事务**（同 worker#3）。
4. **`options["share"]` 在 64KB 闸之后注入** — app.py:1328 闸后 :1330-1335 塞 share 载荷，manifest contributor 无字段上限 → options_json 可膨胀 ~1MB 拖累每次 store.get。修：`_manifest_checked` 加字段级上限或注入后重跑闸。

### Low

5. task_retry 复用创建侧归一化器覆写 `options.source`（app.py:1624，html 任务被改 "eprint"——现按 kind 路由无影响，库内不一致是雷）。修：retry 用不注默认的校验器。
6. reader_get/put 串发 4-5 次 file_record mini-N+1（app.py:1706/1758/1777；file_record 内部全量 SELECT）。修：开头一次 store.files 复用。
7. snapshot() 每次全扫 warning+json.loads（store.py:979-999）。修：DESC LIMIT n 反序或独立小表。
8. 对已 DELETE 任务的 force publish → FK IntegrityError 炸回 worker（events.py:46-48 → store.py:895-913；share force=True 审计行恰是触发面）。修：`INSERT…SELECT…WHERE EXISTS` 或 publish 捕 IntegrityError。
9. 4xx `code` 字段覆盖不一致——`_json_error` 加 code 参数统一。
10. 静默吞错：`?status=` 不校验返空 200；`has_api_key` 伪字段丢弃返 200。修：枚举校验/未识别字段告警。
11. 全部 /api `no-store` 含 `?version=` 内容寻址产物——`/api/files/` GET+version 匹配可放 `private, immutable`。
12. settings 标量字段不查类型——dict/list 被 str() 持久化成字面量（settings.py:281-303）。修：标量拒非 str。
13. `store.conn` 三处逃逸（app.py:605/1640、runner.py:81）+ `list_tasks` 死代码——收口 + 删/改名。
14. `SettingsStore.load()` 浅拷贝共享嵌套容器（settings.py:425-449）——deepcopy 或只读封装。
15. 无产物 GC/TTL——tasks/{id}、translation_cache、share_dir、index.jsonl 只增不减；`_sweep_orphan_task_dirs` 仅启动时跑。TTL+周期 sweep；index.jsonl 可由包重派生。
16. server 模式 health 过度脱敏 + 无 metrics——保留 ok+db+queue_depth；无任务计数/排队时长暴露面。
17. JSON 端点共享 80MB body 上限（app.py:807-841）——JSON 单独 cap 1-4MB。
18. SSE 重放缺口无信号——last_id 落已淘汰区段静默跳过；检出 `first.seq > last_id+1` 补 resync 帧。
19. pack_share ≤300MB 全量 RAM——`ZipFile.open(member,'w')` 流式写。
20. upload multipart 全量回拉 RAM ~2×80MB×并发（app.py:222-302）——`copyfileobj` 直落盘；app.py 1876 行建议拆 APIRouter。

### 已验证安全（be）

zip 声明值硬截断+CRC 无 bomb 旁路；FileResponse Range+ETag 可用；幂等检查+insert 单进程原子；EventBus subscribe-before-replay+去重+_RESYNC 完整；单写者无死锁环；insert_chunks/flush_chunk_batch BEGIN IMMEDIATE 原子；unpack_share 对账+tmp→rename 零半包；一轮修复全复验在位；request_gate 四层自洽；_service_lock/thin client 正确。
