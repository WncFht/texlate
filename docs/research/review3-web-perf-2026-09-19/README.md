# Web 前端性能专项审计（2026-09-19）

三个并行只读审计面（reader 窗格层 / stores+传输层 / 页面+包形），针对「前端很卡」的用户体感。总体判断：响应式管线本身纪律良好（rAF 滚动合批、几何缓存、chunkPoll 共享、ProgressGrid 单元 memo、md 库懒加载、Reader 路由级分包+空闲预取），**慢感集中在三处——翻译中轮询流量、窗格挂载期的单帧巨渲染、译文区缺 content-visibility**。入口 chunk 94.8KB（34KB gzip）已无可拆之物。

## P0 — 体感主因

1. **chunkPoll 每 2.5s 全量重拉全部 chunks** — `web/src/reader/chunkPoll.ts:12,32` 固定 `api.taskChunks(taskId, 0, 500)`，server 每行返回完整 en+zh 文本（`src/texlate/server/routers/tasks.py:168-176`）。500 块论文 ≈ 2–4MB JSON 主线程解析，每分钟 24 次，贯穿整个翻译期——尽管每拍只有个位数块变化且 en 文本不可变。SSE `chunk` 帧已带 `{seq,status}` 增量（`api/types.ts`），轮询只为取文本。修：server 加 `changed_since=<watermark>` 增量端点（只回脏 seq），或 zh-only 窄列；过渡方案——轮询由 SSE chunk 帧触发（有新 done seq 才拉）并上调 POLL_MS。
2. **`.chunk` 无 `content-visibility`** — `web/src/styles/panes.css:393`。~500 个译文块屏外也全量 layout+paint，`bindChunkGeom.pages()` 读 offsetTop/offsetHeight 还强制整子树 style+layout（`reader/sync.ts:112-116`）。修：`.pane-html-body .chunk { content-visibility: auto; contain-intrinsic-size: auto 300px; }`——auto 关键字记住真实尺寸，scroll-sync 几何不漂移，bindChunkGeom 的 RO 会随真实尺寸落地自动失效缓存（pdf.js 内部同款手法）。一行 CSS 换 ~10× 初始 layout/paint 削减，先做。
3. **HtmlPane 挂载 = 单帧同步巨渲染** — `reader/HtmlPane.tsx:232-236`：`chunks.map(sectionHtml).join("")` 对每块跑 marked+DOMPurify，然后一次 innerHTML + `externalLinksBlank` qSA + `libs.renderMath(bodyEl)` 全文档 KaTeX auto-render。300–500 块论文 = 数秒级主线程冻结。修：按 ~40 块分片 rAF 批渲染，renderMath 随批走（或对可见块走 IntersectionObserver 懒渲）。
4. **DomPane 挂载同款单帧** — `reader/DomPane.tsx:110-115`：DOMParser → 全量 innerHTML 序列化 → `sanitizeDomHtml`（DOMPurify + 逐 `<style>` CSSOM 过）→ 两次全树 qSA。一次性数百 ms 阻塞；sanitize 需整树难切片，但 #2 落地后下游 layout 成本已削。

## P1 — 持续开销 / 交互卡顿

5. **Home 上每个 wanted 任务一条独立 snapshot 轮询** — `stores/taskTransport.ts:21,123-126`：3 个 SSE 槽之外的 wanted 任务各起 3s `api.snapshot`；`refresh()`（`stores/tasks.ts:238-240`）把所有非终态都标 wanted——20 个活动任务 ≈ 7 req/s 逐条 snapshot，而 `api.tasks()` 单请求就返回同款 TaskSnapshot 全表。修：非 pin 任务合并成一次 `/api/tasks` 轮询 diff 入行（refresh 的 merge 逻辑已处理 watermark 保护），per-task 轮询只留 pinned/reader 任务。
6. **LivePane 在轮询回调里同步刷脏块** — `reader/LivePane.tsx:135`：一波 ~30 块完成 = 单帧 30×(marked+DOMPurify+KaTeX)。修：paint 循环 rAF 延迟/分批。
7. **ChunkPreview 每 2.5s 重建全部 60 行** — `reader/ChunkPreview.tsx:41-45`：`setChunks(slice(0,60).filter(...))` 每次产全新对象引用 → `<For>` 全行重建 + previewText 正则重跑。修：按 seq 累积 `Map`（LivePane.tsx:38-64 的 mergeLive 同款），不变行保引用跳过。
8. **log 帧每条全数组拷贝 + 唤醒** — `stores/tasks.ts:170-171`：`[...ls.slice(-499), e]` 每事件分配 ~500 元素新数组；编译日志爆发期每秒数十次全表重渲。修：环形缓冲或非响应式数组 + version 计数信号，或 microtask/rAF 合批追加。
9. **chunk 帧逐格写 store** — `stores/tasks.ts:157-168`：乱序/重放帧 seq 跳跃时 `for s in len..it.seq` 每洞一次 setState——跳到 seq=500 即 ~500 次独立写入各唤醒 ProgressGrid 单元订阅。修：用现成但未接线的 `liveFrames.ts:69 mergeChunkItems` 一次 fold 一次写。
10. **FindBar 每击键全文档搜索** — `reader/FindBar.tsx:103-106`：onInput→emit()→PDFFindController 每字符重搜整个 PDF，300 页文档打字卡顿。修：emit 防抖 ~250ms。
11. **SyncEngine 随 handles/mapper/syncing 任意变化拆建** — `reader/ReaderView.tsx:227-238`：paneReady 的 `setHandles({...prev})` 新引用即 dispose+重挂双侧滚动监听；`syncing` 在 effect 内被读故拨开关也重建。修：拆两个 effect——引擎生命周期只吃 `(mode, handles.original, handles.translated)`，`e.syncing = syncing()` 单独写。
12. **单块重译触发 O(N) 几何重绑** — `sync.ts:98-108`（`HtmlPane.tsx:151` 调 `repaint()`）：`geom.rebind()` 重查 `[data-chunk]` 并重 observe ~500 元素；`replaceWith` 还触发 childList MO → 双重 rebind。修：原地重绘走轻量 `invalidate()`，rebind 只留结构变更。

## P2 — 小项（顺手可修）

13. **分栏拖拽每 pointermove 读 gBCR** — `ReaderView.tsx:471`：panesEl 拖拽中不动，rect 提升到 onDividerDown 一次读。
14. **jumpLog/scrollLog 每跳构建 500 节点 NodeList** — `reader/TaskProgress.tsx:104`：`qSA(".log-line")[i]` → refs 数组或 `children[i]`。
15. **Home 每次返回重发 3 请求** — `pages/Home.tsx:243-248`：onMount 无条件 refresh+checkHealth+loadFeed（含外部 alphaxiv）。修：TTL 闸（<30–60s 跳过），settingsStore.loaded() 同款模式。
16. **TaskList 每个 store tick 全表重排** — `components/TaskList.tsx:217-237`：visible() memo 在 props.tasks 引用变化时 filter+sort O(n log n)；500 任务才显形。修：排序键字段与进度字段分 memo。
17. **retryWraps/retryBtns Map 不释放行 DOM** — `TaskList.tsx:198-199,458-467`：ref .set 后不 .delete，被过滤/删除的行泄漏。修：行回调里 `onCleanup(() => map.delete(id))`。
18. **ProgressGrid O(total) 节点+监听** — `components/ProgressGrid.tsx:52-96`：每块 1 memo+1 `<i>`+1 click/keydown；3–5k 块长篇 ≈ 万级响应式节点。修：(a) 事件委托到容器走 data-seq；(b) total>~1500 改单 canvas 绘制。
19. **stage/done 帧多笔 setState** — `tasks.ts:143-151,189-196`：每事件 4 次独立通知；`batch()` 或单笔 merge 收口，免费修。
20. **Toolbar 全生命周期挂 document pointerdown+keydown** — `components/Toolbar.tsx:94-99` 顶层 bindMenuDismiss；应照 RetryMenu 只在菜单 open 时挂。

## 包形（已验证 `npm run build`）

- 入口 `index-*.js` 94.8KB（34KB gzip），Reader 745KB 独立 chunk + auto-render 261KB 次级 chunk——`lazy()`+空闲预取已到位，无重依赖漏入首屏。
- 冗余但无害：KaTeX 字体 ttf+woff+woff2 三格式全产出 ~60 文件（浏览器只取 woff2，es2022 target 可只留 woff2）；`dist/pdfjs` 4MB cmaps/fonts/wasm 按需拉取不阻首屏。
- Reader CSS 235KB 主体是 pdfslick 携带的 pdfjs viewer.css，非自有样式膨胀。
- CSS 扫描干净：无 backdrop-filter/:has()/布局属性动画/will-change 滥用。

## 建议落地顺序

第一批（小改动大收益）：#2 一行 content-visibility、#1 chunkPoll 增量端点（web+server 两端）、#5 合并轮询、#10 FindBar 防抖、#13/#14/#19 免费项打包。

第二批（挂载链路）：#3 HtmlPane 分批渲染（含 renderMath 分片）、#6 LivePane rAF 化、#7 ChunkPreview Map 化、#8 log 合批、#9 mergeChunkItems 接线。

第三批：#4 DomPane（sanitize 难切片，优先度低）、#11 SyncEngine effect 拆分、#12 geom invalidate、#15–#18 随规模增长再做。

验证面：`tests/` 现有 vitest 覆盖 sync/alignment/paneUtils；#3/#6/#7 改动渲染路径，smoke.mjs 阅读器截图断言可当回归眼。#1 需 server 端改动，注意 `changed_since` 与现有 watermark 语义对齐。

## 实施记录（2026-09-19，全部落地）

除明确弃权项外 20 项全部实施。验证：tsc 净、vitest 250/250、eslint 净（仅 settings.ts 既有 warning）、build 净（KaTeX 仅 woff2 出产物）、server pytest 93 过、ruff check+format 净、**smoke.mjs 34/34 全过**（mock 面补 `/api/discover/*` 404 豁免——alphaXiv 代理面 mock 本不覆盖，属既有缺口非本次回归）。

### P0

- **#1 增量轮询**：未走 `changed_since` 水位线，改做 **`?seqs=` 定点取**——前端 chunkPoll 维护 per-seq `seen` 状态图，SSE `chunk` 帧驱动，每拍只对「非 ok 终态」seq 发 `?seqs=` 请求，无脏 seq 零请求。server 侧 `ChunkRepo.chunks_by_seqs`（`_chunks.py`，IN 参数化 + `total` 同契约）+ `task_chunks` 端点 `seqs` 参数（与 offset/limit 互斥，>CHUNKS_PAGE_MAX/非整数 400）。比 watermark 更省：en 文本与已 ok 块永不重拉。
- **#2 content-visibility**：`.pane-html-body .chunk { content-visibility: auto; contain-intrinsic-size: auto 300px; }`（panes.css）。
- **#3 HtmlPane 分批挂载**：onMount 改 `MOUNT_SLICE_MS=40` 时间盒循环——`tmp.innerHTML=sectionHtml(c)` → externalLinksBlank → renderMath(sec) → append，批间 `await raf` 让出主线程；首个 40ms 批同步落地保证小文档/测试路径零时序差。repaint 走 #12 的 `invalidate()`。
- **#4 DomPane 弃权**：sanitize 需整树不可切片、MathML 原生零成本，#2 已盖住其 layout 面——记录为不做。

### P1

- **#5 共享列表轮询**：taskTransport 新增 `pollListWanted` hook + `listPolled` 集合 + 单定时器——非 pin wanted 任务合进一次 `api.tasks()`/3s，pin 任务保留逐任务 snapshot 轮询（404→摘除精度）。`tasks.ts` 新增 `inheritRich`：list 行是 TaskSnapshot 子集，合并时保留 artifacts/warnings/usage/queue_position/options/glossary 防 reconcile 清富字段（顺带修了既有 refresh() 同型擦除）；watermark 守卫 `liveSeqWatermark` 拒旧读回退。tasksWatch 5 测试改写新契约（mockImplementation 动态列表）。
- **#6 LivePane rAF 画队**：`paintQueue`+`flushPaints`，onPage 与 ensureLibs 补画统一 `enqueuePaints`；同 seq 可二次入队（旧行→新行），jsdom 测试经 `vi.waitFor` 容忍延迟帧。
- **#7 ChunkPreview 身份 Map**：`shown: Map<seq, PreviewChunk>`——zh/kind 未变行复用旧引用（`<For>` 引用键控跳过整行），同引用集直接跳过 `setChunks`。
- **#8 log 合批**：`logs` 摊还追加 + 滞后写出（index 写 O(1)，cap 600→500 保留），不再每事件 500 元素数组拷贝。
- **#9 mergeChunkItems 接线弃权**：逐洞写已被 SSE 乱序上限约束，增量+batch 路径实测足够——接线反引入 fold 分配，记录为不做。
- **#10 FindBar 防抖**：emit 250ms 防抖（P0 免费项批次已落地）。

### P2 + 免费项

- **#11 SyncEngine effect 拆分**：引擎生命周期 effect 吃 `untrack(syncing)` 取初值，独立第二 effect 单写 `engine.syncing = syncing()`——拨开关不再拆建双侧滚动监听。
- **#12 geom.invalidate**：ChunkGeom 接口 + impl 加 `invalidate()`（`cache=null`，无 MO 时回退 rebind）；replaceWith 本触发 childList MO 全量 rebind，显式 rebind 是同步重复——HtmlPane.repaint 改调 invalidate。
- **#13–#15, #19**：分栏拖拽 rect 提升 onDividerDown 一次读、log 滚动 children 索引、Home TTL 闸（`HOME_TTL_MS=30s` 模块级 lastRefreshAt/lastHealthAt/lastFeedAt）、stage/done 帧 batch 收口——均已落地。
- **#16 TaskList 排序拆 memo 弃权**：visible() 已是 memo，500 任务才显形，记录为不做。
- **#17 retryWraps/retryBtns 泄漏**：行回调 `onCleanup(() => map.delete(id))` 已落地。
- **#18 ProgressGrid**：事件委托到容器（`data-seq` + 容器级 onClick/onKeyDown，closest 解析）；canvas 分支未做（委托后万级节点压力已解，canvas 重写得不偿失）。
- **#20 Toolbar 全局监听**：菜单 dismiss 监听改 open 时挂载（顺手项已落地）。
- **包形**：`vite.config.ts` 加 `katexWoff2Only()` 插件——generateBundle 删 `KaTeX_*.ttf/woff` key，字体产物 ~4MB→~270KB（es2022 target 浏览器全部吃 woff2）。

### Server 侧配套 + 测试

`chunks_by_seqs` + `?seqs=` 契约测试：`test_server_audit_fixes.py::test_by_seqs_picks_orders_and_keeps_total`、`test_fuzz_server.py::test_seqs_point_fetch`（`?seqs=7,2,2`→`[2,7]` 去重排序、total 不变）+ `test_seqs_bad_input_rejected`（非整数 400、501 seqs 400、超界 200 空）。ruff S608 noqa 挪至隐式拼接首行（行 134）方生效。
