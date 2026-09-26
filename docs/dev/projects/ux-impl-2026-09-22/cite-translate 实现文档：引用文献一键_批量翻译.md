# cite-translate（引用文献翻译）实现文档

调研基础：tmp/ux-research-20260922/exp/ 下 9 个 ct-* 实验（ct-card-id / ct-dedupe(+verify) / ct-status / ct-toast / ct-badge / ct-notify / ct-card-states(+verify) / ct-batch / ct-anon），全部已在真实代码与真实数据上实测。本文档是综合实现规格。

## 目标

在阅读器内把「被引文献」变成可消费的一等任务对象：

1. **单条**：引用悬浮卡（CiteCard）脚部新增「翻译此文」动作——凡能解出 arXiv id 的条目（本地 L1 抽取或 L2 S2 externalIds 反补）都可一键建任务，按钮自身承载任务状态机（idle→queued→running→done/failed）。
2. **批量**：文献表面板列出全部可解析条目（本地抽取 + L2 元数据），三桶分类（已译/在队/新）+ ETA 区间 + 大批量警告后一次性灌队。
3. **后台可达**：批任务串行跑期间用户可离开——Toolbar 任务徽标（reader 内补 .topnav 隐藏的真空洞）、app 级 toast、系统通知三层承接回执。
4. **凭证门**：无 API key 时拦截并给内联输入——实证动机是 local 形态无 key 提交会静默产出 Mock 占位译文且段缓存跨凭证残留（67% 段毒化，`prefer=fresh` 也救不回）。

非目标（本期不做）：DOI-only 条目的非 arXiv 翻译通道（本刊只能翻 arXiv 源）；无 id 条目（56.7%）的 title-search 解析；kept-refs 收藏（另有独立设计稿 kept-refs-design.md）。

### 数据底盘（实测值，写进文案与闸值）

- 语料普查：1,228 文档 75,373 条 `\bibitem`，**36.3%** 带文本级 arXiv/DOI；放宽 DOI 正则后 **43.3%**；**56.7% 永不可译**。单文档可译率 p25=6% / p50=19% / p75=47%，155 篇零覆盖。
- 可译量：每篇 arXiv 可译条数 p50=4 / mean=15.1 / p90=28 / p99=134；批桶分布 1–5 篇占多数（536/1458），>60 篇 43 例。
- 服务时长（4391 条历史任务）：p50=47s / p75=122s / p90=236s / mean=91s——串行队列下 N 篇 ETA ≈ N×[47s, 236s]。
- 灌队成本：串行 POST ~1.2ms/条（22 条 0.026s），提交从来不是瓶颈。

## 交互规格

### A. 卡内单条翻译

- CiteCard 脚部（`cite-card-foot`）在「跳到文献表 / arXiv ↗ / DOI ↗」旁加第四动作「翻译」。
- **可见性**：`entry.arxivId ?? meta()?.arxivId` 存在才出（DOI-only 条目经 S2 externalIds.ArXiv 反补后同样可译——refs.py:154 已回传该字段）。都无时不出钮（不占位、不置灰出死钮）。
- **点击**：带当前任务的 model/target_lang/glossary/options 全量透传（createHtmlFallback 同款 M10 口径，删 `options.idempotency_key`），POST /api/arxiv/{id}/translate，每条独立 Idempotency-Key（`createFp("translate",{arxivId,body},byok)` 天然含 id——**绝不能跨条目复用 key**：idem key 是「独断」层，同 key 异 id 会回旧行，V5 实证）。
- **回执分派**（实测契约）：
    - 202 `cache:miss` → toast「已加入队列 · 查看」→ 按钮进 queued。
    - 200 `reused:true` → toast「已有译文」→ 按钮直接 done 相，点击开 `#/reader/{task_id}`。
    - 409 `duplicate_active` → 静默收编为「已在队列」，指向回包 task_id（覆盖 interrupted 占键槽、别名形态归一全中同一行的情形）。
    - 401 `auth_required`（server 形态）→ 弹内联 key 面板（复用 ResultBody needs_auth 的 authKey 模式），key 随 X-Texlate-Key 头重发同请求。
    - 429 `quota_exceeded` → err toast「配额已满」。
    - 400 invalid id → 不该发生（本地已校验），兜底 err toast。
- **按钮状态机**（ct-card-states 实证，带环非 DAG）：`idle→queued→running→{done|failed}`；`failed→running`（retry 同 task_id 同 append-only 事件流复用，靠「终态帧后再见 stage 帧」判新轮，参考归约器 run_id 钩 7/7 复位成功）；`queued→failed` 零 stage 帧直达（needs_auth/排队即取消）；`idle→done` 直达（dedupe 复用行 0 事件）。**4.3% 任务零事件帧**——纯 SSE 归约永不收敛，必须经行状态（snapshot/列表轮询）兜底。
- **进度口径**：裸 done/total 不可用（29.2% 活动墙钟停 0%、7.8% 已 100% 仍在跑、均值偏 11.3pt）。卡钮只显示粗相（排队中/翻译中/编译中/完成/失败）；若显示百分比用 band 映射：translating 段 `25+⌊60·done/total⌋`（chunk 帧不带 progress 字段，SSE 路必须本地插值），其它段用 stage 锚点（fetch 3–9 / parse 9–25 / translate→85 / compile 90–99 / 终态 100）。
- **终态语义**：done 与 partial 都归「可读」相（partial=降级交付，按钮文案「打开译文」+ failed_chunks 角标）；needs_auth 单独 CTA「去设置/输 key」；cancelled/fault/interrupted → ↻ 重试相。
- **卡生命周期兼容**：滚动/scalechanging/pagesdestroy 即关卡（ADR-0021 既有语义）——提交已派发后卡消失无妨，反馈由 toast 承接；卡重开时按 task 行重建状态。

### B. 文献表面板 + 批量翻译

- **入口**：Toolbar 新增「文献」钮（`citeIndex.size>0` 才显；计数角标=可译条数）；卡内脚部加「全部文献」次入口。≤640px 收进 ⋯ 菜单（`role="menuitem"` 才入 menuRoving 漫游圈）。
- **面板**：modal/抽屉列出 citeIndex.entries() + lazy-dest 已抽条目——每行 label、截断正文、id 徽标（arXiv/DOI/无）、状态钮（同卡内状态机）、meta 标题（L2 已到包时）。
- **顶部批量 CTA「翻译全部」**：点击先 preflight——1 次 `GET /api/tasks`（实测 ~2ms）按双侧 canon 归一 `arxiv_id` 分 done/active/new 三桶。**这步不可省**：bare-id 对已 done 钉版行重提会产幽灵 202 行（REST find_reusable 查裸键错失钉版键，~55ms 才被 worker reuse_hit 物化兜底），preflight 直接免掉。
- **确认弹层文案**（实测产出的 copy 表，zh）：
    - 标题「翻译引用文献」；计数行「共 30 篇可翻译：22 篇新任务，3 篇已在队列，5 篇已有译文」；
    - 等待行「串行处理，预计全部完成约需 {lo}–{hi}」（lo/hi = (n_active+n_new)×[p50 47s, p90 236s]，对齐实测表 N=15→12min–1h、N=28→22min–1.8h、N=60→47min–3.9h）；
    - 提示行「已译文献不重复排队；任务在后台运行，可随时离开」；
    - CTA「翻译 {n_new} 篇」；全 done 时「全部已有译文」置灰；
    - **warn_big**：n_new>15 时加警示条「一次提交 {n} 篇将占用队列约 {lo}–{hi}——建议分批或先译高优先」（p90 批量即 22min–1.8h 串行）。
- **灌队**：仅对 new 臂发 POST，串行 `await`（保序、~1.2ms/条）或 gather 等价墙钟；每条各自 Idempotency-Key（重试安全）。409/200 响应照常收编进对应桶重渲。
- **观测**：批任务不开独立 SSE（MAX_SSE_TASKS=3 硬顶）——pin 只给当前 reader 任务，批行骑共享 `/api/tasks` 3s 轮询（一拍与任务数无关）。queue_position 只在单任务快照有，面板行不显示位次。
- **done/active 行**渲染为链接直跳 `#/reader/{task_id}`。

### C. Toolbar 任务徽标（reader 内）

- 数字源 = `taskStore.state.tasks.filter(!isTerminal)` ——与 App.tsx:83-87 `activeCount` 同口径（active=queued/fetching/parsing/translating/compiling 5 态；interrupted 属 UI 终态不计）。派生成本实测 n=100k 仅 3.6ms，细粒度订阅只跟 status 叶（progress 帧不重算）。
- **落点 B（推荐）**：独立 chip「任务 N」点击→`#/tasks`（hash 写 ≡ nav()）。桌面常显（不能挂 `.tb-opt`——≤640px 会随控件一起 display:none）；窄屏在 ⋯ 菜单放 `role="menuitem"` 副本（menuNav.ts:9 roving 只认该 role）。
- 备选排除：A 返回钮角标语义错配（onBack→`#/` 非 `#/tasks`）；C 仅 ⋯ 菜单桌面不可见。
- 新鲜度：reader 内已知任务 ≤3s（SSE 槽内即时 / 槽外共享轮询）；**已知缺口**——reader 停留期间外部新任务不可见（pollListWanted 只 merge wanted ids）。零成本升级：pollListWanted 响应本含全表，顺带 merge 未登记行即对外来任务也精确（建议顺手做）。

### D. 完成通知（toast + 系统通知）

- **挂点**：`live.done` 物化是唯一汇聚面——7 条终态入径（SSE done 帧 / snapshot 终态 / 共享列表轮询 / refresh / 独轮询 tick / 探活 / resync）全部收敛到 2 个写点（tasks.ts convergeTerminal:148 合成 + done handler:284）。推荐挂法 A=store 内 emit：convergeTerminal 既有 `if (!live.done)` 守卫内发一次、done handler 在 batch 前快照 hadDone 后置守卫发一次。等价挂法 B=App 根 createEffect 扫 `state.live` done 翻转（零 store 改动）。harness 实测 10 场景：守卫版 8 次恰一次/轮；naive 版在「snapshot 终态+迟到 done」序下真发 2 次。refresh 初见终态不报存量（天然免打扰）、deleted 帧不报、retry 新轮再报一次（resetLive 复位即 rearm）。
- **显示门**：`document.hidden && permission==='granted'` → `new Notification`（`tag=texlate-${taskId}` 幂等去重）；否则 in-app toast。isFailed(status) 分 ok/err 变体。
- **权限流**：Chrome 153 实测无手势 requestPermission → denied（1s 后 resolve），deny 后秒拒不再弹。故权限只能在用户手势内请求——Settings 页加「任务完成通知」开关，onClick 里 requestPermission；granted 后 show 事件 <300ms；`PermissionStatus.onchange` 可热追撤销（granted→prompt）。
- **toast**：移植 ct-toast spike（toastStore.ts 127 行 + ToastHost.tsx 38 行，14/14 探针过）：模块级 createSignal + 纯对象门面（对齐 settings.ts/tasks.ts 落地形），栈上限 3 逐最旧、默认 TTL 4500ms（与 RETX_TOAST_MS 同口径）、err 9000ms、key 去重刷计时器、行内 action（「查看」「重试」）。宿主挂 App.tsx 顶层一处，role 分档 err→alert 其余→status。**vitest 注记**：store 依赖 window——测试文件须 `@vitest-environment jsdom`（node 环境 push 抛 ReferenceError，spike 已实证）。
- 与既有 .pane-toast（HtmlPane 单段重译条）关系：窗格条保留原位（就近语义），本件收 SSE 断流/删除回执/提交回执等窗格外事件，不强制替换。

### E. 凭证门（匿名/无 key）

- **判据**：`settingsStore.settings()?.has_api_key === false` 且无 per-request key 时，单条与批量提交前先出面板的内联 key 框（不裸跳设置页——深链参数实测全丢，`#/settings?next=…` 4/4 变体只解析出 `{page}`，丢任务上下文）。
- **理由（实测）**：local 形态无 key 点翻译 = 202 直受、MockTranslator 占位译文 10.7s 跑完、唯一告知是 1 条 warning；且 `file_cache_key=(prompt_version,base_url,model,lang,glossary,context)` **不含 api_key**——存 key 后 `prefer=fresh` 重跑仍有 114/170（67%）段命中 mock 缓存、warnings=0 静默毒化。批量场景会把毒化放大到 N 篇，必须在客户端闸。
- **server 形态**：匿名 mutation 三件套（translate/upload/PUT settings）全 401 `auth_required`；401 响应一律进同一内联 key 面板（X-Texlate-Key 头重发），不渲裸 detail 文本。
- **needs_auth 任务行**：批任务里混 needs_auth 态时行内给「输 key 重试」CTA（同 taskActions authKey 通道）——注意设置页存的 key 不解 header 源任务（server 401 实证），必须重带请求头。

## 数据/管线改动

**本特性对 LaTeX 翻译管线零改动**——全部走既有 `POST /api/arxiv/{id}/translate` 任务面。变更集中在「条目→id」抽取侧：

1. **`extractRefIds` DOI 正则放宽**（web/src/reader/citations.ts:67）：现行要求 `doi.org/` 或 `doi:` 前缀，漏 `\doi{}`/`\mn@doi{}`/`doi={}` 裸形共 5,325 条（7.1%）；加裸 `10.\d{4,9}/\S+` 臂（条界止于 `.,;)]}` 尾）覆盖 36.3%→43.3%。
2. **客户端 canon 归一**（新建小函数，或按 tmp/ux-research-20260922/arxiv-id-canon-spec.md 落地共享 canon）：cite 条目 arxivId 可能带 `vN`、task 行 `arxiv_id` 是服务端 `normalize_arxiv_id` 落库的裸 base（tasks.py:59,95）——preflight 匹配与状态映射必须双侧剥版本+剥 class+小写化 archive。
3. **L2 反补已可用**：refs.py 的 S2 回包已带 `externalIds.ArXiv`→`meta().arxivId`（refs.py:154-155），DOI-only 条目自动升级出 arXiv 链，前端零改动。
4. **已知数据缺口（接受，不堵）**：dual.json `ph` 仅 8/128 文档有（eprint 链主路专属）→ citeIndex 覆盖率天然受限，lazy dest 兜底条目不进 refsLookup（refMeta 只从 citeIndex.entries() 播种）——面板对该类条目显示「无可解析 id」；arxiv_html 链 `_build_dual_html` 不写 ph → dom 视图 citeIndex=0。这些是上游产物面问题，不在本特性面修。
5. **可选**：refs.py `_MAX_REFS=400` 超限整包 400（前端 `.catch` 静默）→ 4/1228 巨型文献表文档 L2 全灭；改「截断 400 + truncated 标志」或前端分片提交。

## 前端改动（文件级）

| 文件                                     | 改动                                                                                                                                                                                                                                                                                                                            |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web/src/reader/citations.ts`            | `extractRefIds` 加裸 DOI 臂；导出 `canonRefId(id)`（剥 vN/前缀/class）供匹配用                                                                                                                                                                                                                                                  |
| `web/src/reader/CiteCard.tsx`            | `CiteCardBody` 加 props：`refStatus?(): "idle"\|"queued"\|"running"\|"done"\|"failed"\|"needs_auth"`、`onTranslate?()`、`onOpenTranslation?()`；脚部按状态渲「翻译/排队中/翻译中 %/打开译文/重试/输 key」                                                                                                                       |
| `web/src/reader/PdfPane.tsx`             | `openCard`/CardState 透传 `props.onTranslateRef?.(entry)`；`entry.arxivId ?? meta()?.arxivId` 作为可译判据传给卡体                                                                                                                                                                                                              |
| `web/src/reader/PaneSlot.tsx`            | props 加 `onTranslateRef`、`refStatusOf` 透传 PdfPane；**顺手修 DomPane 缺口**（:92-104 不传 citeIndex/citeMeta——dom 卡引用条无 id 通道）                                                                                                                                                                                       |
| `web/src/reader/ReaderView.tsx`          | 建 `refTaskOf(arxivBase)` memo（state.tasks 双侧 canon 匹配，多行取 done>active>failed、updated_at 最新）；挂 RefsPanel open 信号；给 Toolbar 传 `onRefs`/`refsCount`                                                                                                                                                           |
| `web/src/reader/RefsPanel.tsx`（新）     | 文献表弹层：条目行（label/正文截断/id 徽标/meta 标题/状态钮）+ 顶部批量 CTA + 确认弹层（三桶计数+ETA+warn_big 文案按 §B）                                                                                                                                                                                                       |
| `web/src/reader/citeTranslate.ts`（新）  | 编排工厂：`preflight()`（api.tasks + canon 分桶）、`submitOne(entry)`、`submitAll(newArm)`（串行 await、per-ref `createFp` idem key、409/200/202/401/429 分派）、`estimateMinutes(n)`（47s/236s 带）                                                                                                                            |
| `web/src/stores/toastStore.ts`（新）     | 移植 exp/ct-toast/toastStore.ts（127 行，已验证）                                                                                                                                                                                                                                                                               |
| `web/src/components/ToastHost.tsx`（新） | 移植 exp/ct-toast/ToastHost.tsx（38 行）；App.tsx 顶层挂一处                                                                                                                                                                                                                                                                    |
| `web/src/stores/tasks.ts`                | **前置必修**：refresh() 的 `reconcile(merged,{key})` 在列表变短时产稀疏数组→`task()` find 遇洞 TypeError→传输层瘫痪（sparse.test.ts 双实证；retention_loop 每 10min 删终态行即触发）。修法=改 merge-only 归并或 reconcile 后 filter 洞。可选：convergeTerminal 守卫内 + done handler hadDone 守卫后 emit 完成事件（通知挂点 A） |
| `web/src/components/Toolbar.tsx`         | 「任务 N」chip（桌面常显位，点→`#/tasks`）+ ⋯ 菜单 `role="menuitem"` 副本；「文献」入口钮（`refsCount>0` 才显）                                                                                                                                                                                                                 |
| `web/src/App.tsx`                        | 挂 `<ToastHost/>`；方案 B 时加 createEffect 扫 live.done 翻转发通知                                                                                                                                                                                                                                                             |
| `web/src/pages/Settings.tsx`             | 「任务完成通知」开关行——onClick 手势内 `Notification.requestPermission()`，`permissions.query`+`onchange` 追态                                                                                                                                                                                                                  |
| `web/src/i18n/zh.ts` + `en.ts`           | `t.cite` 扩 6 键（translate/queued/translating/openZh/retryRef/authNeed）+ `t.citeTran` 新组（panelTitle/counts/waitEta/hint/cta/ctaAllDone/warnBig/toast* 按 §B copy 表）                                                                                                                                                      |
| `web/src/styles/cite.css` + `app.css`    | 卡钮/徽标 chip/refs 面板/toast-host 样式；徽标复用 `.nav-badge`（base.css:205 朱砂药丸，主题感知）                                                                                                                                                                                                                              |
| `web/src/pages/Reader.tsx`               | 透传 citeTranslate 工厂产物给 ReaderView（nav prop 已有）                                                                                                                                                                                                                                                                       |

## 后端改动

**最小面=零改动**：任务创建/dedup/SSE/重试全走既有端点。建议顺手小修（独立 commit，不阻塞主线）：

1. `src/texlate/server/routers/tasks.py` retry 路径：`IntegrityError` 裸 500（V3c 实证——fault/cancelled/partial 后继行持键时 retry 旧行炸 500）→ 捕获转 409 `duplicate_active` 或语义化 409。needs_auth 行同路径返 401 属正确（header 源须重带 key）。
2. `src/texlate/server/routers/refs.py` `_MAX_REFS=400`：超界整包 400 → 改截断 + `truncated:true`，或前端分片（≥400 条仅 4 文档，优先级低）。
3. **管线级另案（不在本特性面）**：`file_cache_key` 不含凭证指纹 → mock 段跨凭证命中。前端 has_api_key 门拦截已覆盖本特性，根治需键成分加 `sha256(api_key)[:8]` 之类——动它会让全量存量段缓存换桶，须单独评估。

## 测试计划

**vitest 单测**（jsdom 环境注记：涉 window/localStorage 的文件头加 `// @vitest-environment jsdom`）：

- `canonRefId`/`extractRefIds`：裸 DOI 五形、`\doi{}`/`\mn@doi{}`/`doi={}`、arXiv vN 剥壳、class 剥壳、`math.GT/0309136`→`math/0301001` 类用例（canon spec §6 实证表直接转断言）。
- `citeTranslate` 编排：mock api 矩阵——202/200 reused/409 duplicate_active/401/429/网络错；preflight 三桶分类（done5/active3/new22 全中模式照抄 confirm_flow.json）；idem key 每篇独立。
- `refStatus` 归约器：带环状态机——queued→running→done、failed→running→done（retry 复位）、queued→failed 零帧、idle→done 直达；band 映射 translating 插值。
- `toastStore`：14 项探针移植（push/ttl/key 去重/cap 逐出/action）。
- Toolbar 徽标 memo：status 叶订阅不重算（progress patch 零成本实证口径）、activeCount 口径与 App.tsx 一致。
- `tasks.ts` 稀疏回归：refresh 列表收缩→无洞、`task(id)` 不炸（ct-status sparse.test.ts 直接搬）。
- 通知守卫：8 真终态恰一次、refresh 存量不报、deleted 不报（ct-notify harness 10 场景搬入）。

**e2e（隔离数据目录实例）**：

- 30 篇批流：preflight 分类→22×202 burst（实测 0.026s）→30/30 done 收编。
- local 无 key：提交前出内联 key 面板，不建 mock 任务。
- server 401→输 key→202 同批续跑。
- retry-500 修复回归：fault 后继持键时 retry 旧行 → 409 非 500。

**手测面**：reader 内徽标新鲜度（≤3s）、批提交后离开回 reader 的 toast/通知、≤640px ⋯ 菜单漫游圈、dom/html 视图降级（无面板或空面板文案）。

## 工作量与分期

| 期      | 内容                                                                                        | 估时   |
| ------- | ------------------------------------------------------------------------------------------- | ------ |
| M0 前置 | tasks.ts reconcile 稀疏修复（独立正确性 bug，批流放大触发面）                               | 0.5d   |
| M1      | toastStore+ToastHost 移植、CiteCard 翻译钮 + 单条编排 + refStatus 状态机、Toolbar 徽标 chip | 1.5–2d |
| M2      | RefsPanel + preflight 三桶 + 批量确认（ETA/warn_big）+ 401/429 处理 + 内联 key 面板         | 2d     |
| M3      | 完成通知（emit 挂点 + Notification 门 + Settings 开关）                                     | 1d     |
| M4      | extractRefIds 裸 DOI、DomPane citeIndex/citeMeta 接线、refs.py 截断、retry-500 修复         | 1d     |

合计 ~6d。M1 即交付可用闭环（单条翻译+徽标+toast）；M2 是批量主功能；M3/M4 可独立并行。

## 风险

| 风险                | 证据                                                                 | 缓解                                                                                                 |
| ------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 覆盖率天花板        | 56.7% 条目无任何 id；单文档可译率 p50 仅 19%；155/1228 文档零覆盖    | 面板明示「可翻译 N/共 M 条」；无 id 行不出钮；文案不报「全部文献」绝对值                             |
| mock 段毒化         | 无 key 跑批 → 占位译文进段缓存，keyed rerun+prefer=fresh 仍 67% 残留 | has_api_key 门前置拦截（§E）；管线根治另案                                                           |
| 幽灵 202 行         | bare-id 重提钉版 done 行 → 新行 ~55ms 物化                           | preflight 双侧 canon 归一（§B），不依赖服务端兜底                                                    |
| 批观测降档          | MAX_SSE_TASKS=3；列表轮询行无 queue_position                         | 批行只显粗状态；位次文案不进批面板；pin 只给当前 reader 任务                                         |
| idem key 独断       | 同 key 异 id 回旧行（V5 实证）                                       | per-ref `createFp` 含 arxivId 天然隔离；跨会话重发靠服务端 cache_key 层兜底（409/200 收编）          |
| 429 半途截断        | quota_exceeded 存在；批中第 k 条起 429                               | 串行 await 遇 429 即停，toast「已提交 k/N，配额满」+ 面板重分类                                      |
| 通知双发            | snapshot 终态+迟到 done 序下 naive 版真发 2 次                       | 守卫内 emit（convergeTerminal 的 `!live.done` 检查内 / hadDone 快照）；Notification `tag` 幂等双保险 |
| 无手势权限拒        | Chrome 153 无手势 requestPermission→denied 且不再弹                  | 只在 Settings 开关 onClick 内请求                                                                    |
| 稀疏数组炸传输      | reconcile 收缩产洞→find 遇洞 TypeError→全 transport 瘫               | M0 必修前置                                                                                          |
| 租户串扰读感        | 409 跨租户泄露 task_id，但 GET 即 404 死链                           | 409 一律渲「已有任务」+ 跳转过 reader 404 兜底，文案不承诺可开                                       |
| 卡生命周期          | 滚动即关卡；提交后卡消失                                             | toast 承接回执；重开按 task 行重建状态                                                               |
| queue_position 语义 | header 源行不计位次、重译 job 不占位、跨租户混算                     | 徽标/面板不显示绝对位次，只用「排队中」粗相                                                          |
| dom/html 视图       | dom 无 citeIndex 接线（PaneSlot:92）、html 无卡                      | v1 面板仅 pdf 视图；dom 接线列 M4；html 维持无入口                                                   |
