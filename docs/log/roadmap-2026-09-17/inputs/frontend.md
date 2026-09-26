# 前端面侦察（web/ + server 契约缝）

> **结论**：前端侦察：26 源文件 5.6k 行边界清晰；SSE 每任务一 EventSource 无界是真规模缝；Reader.tsx 1005 行三合一是最大工程债。
> **状态**：时点证据（2026-09-17 口径）
> **日期**：2026-09-17（2026-09-20 迁入重编）
>
> 侦察日期 2026-09-17，只读。范围：`web/`（SolidJS+Vite+pdfslick 阅读器）与其对 `src/texlate/server/` 的 API/SSE 消费。规格基准：`docs/research/product/2026-09-15-web-layer.md`（下称 §x.y 指其节号）、`docs/research/product/2026-09-14-hjfy-site.md`（hjfy 对照）、`docs/02-architecture.md` §5、`docs/03-roadmap.md` M3 行。

## 1. 目录结构与模块边界

`web/` 是独立 npm 工程（`web/package.json:1`——`solid-js@^1.9`、`@pdfslick/solid@^4.0.2`、`pdfjs-dist@^6.3`、`marked@^18`、`katex@^0.18`、`dompurify@^3.4`；vite@^8 + vitest@^5 + tsc + eslint flat）。源码总盘：`web/src` 下 26 个源文件约 5600 行（含 1868 行 app.css），`web/src/test/` 23 个测试文件约 2900 行，`web/dev/mock-api.ts` 1524 行 mock 中间件，`web/scripts/smoke.mjs` 247 行 playwright 冒烟。

模块边界与体量：

- `src/api/client.ts`（653 行）——全部 /api 封装：fetch `request()` 与 XHR `xhrRequest()`（multipart 上传进度，`client.ts:336`）、`ApiError{status,detail,code,taskId}`（`client.ts:294`）、BYOK 头 `X-Texlate-*`（`client.ts:382`）、Idempotency-Key 生命周期 `pendingCreate`（`client.ts:401-456`）、SSE `openTaskEvents`（`client.ts:607`）。
- `src/stores/`——`tasks.ts`（195 行，solid `createStore` 承载任务列表 + 每任务 `TaskLive` SSE 累积态，`tasks.ts:56`）与 `settings.ts`（38 行，signal 组）。两个 store 形态不一致（store vs signal 组）但都小而可读。
- `src/pages/`——`Home.tsx`（426 行：arxiv 输入/上传/任务选项格栅/健康指示/任务列表）、`Reader.tsx`（**1005 行**，进度视图 + 阅读器壳 + 结果面板三合一）、`Settings.tsx`（242 行 BYOK 表单）。
- `src/reader/`——`PdfPane.tsx`（208，`usePDFSlick` 封装 + `PaneHandle` 几何接口）、`HtmlPane.tsx`（120，marked+DOMPurify+KaTeX，`[data-chunk]` 当页）、`sync.ts`（119，`SyncEngine`：20% 焦点线/ignoreTop 回声抑制/rAF+epoch 合帧，`sync.ts:60`）、`alignment.ts`（174，线性坐标 + 二分插值 + regions 优先 + pages 退化，`alignment.ts:85`）、`PaneSidebar.tsx`（308，缩略图/大纲/附件/查找/信息/高亮批注 icon 栏）、`FindBar.tsx`（191，pdf.js find 协议全封装）、`DocInfo.tsx`（89）、`paneUtils.ts`/`view.ts`/`sanitize.ts` 三个纯函数层。
- `src/components/`——`Toolbar.tsx`（201，阅读器顶栏）、`TaskList.tsx`（171）、`ProgressGrid.tsx`（56，段落棋盘格）、`Segmented.tsx`（44，radiogroup 语义 + roving tabindex）。
- `src/i18n/zh.ts`（230 行文案常量表，`zh.ts:1` 注明「M3 先中文单语」）；`src/styles/app.css`（1868 行单文件，`:root` 自定义属性调色板，`app.css:4-24`）；`src/pdfjs.ts`（12 行 worker 接线，`pdfjs.ts:10`）；路由是 `App.tsx:11-16` 手写 hash 解析（`#/`、`#/reader/:id`、`#/settings`），无 router 依赖。
- `dev/mock-api.ts` 是 vite 中间件级全流程假后端（手写 SSE 帧 `mock-api.ts:731-742`、迷你 PDF 生成器、seed 任务矩阵含 fault/partial/doc/share 演示），`vite.config.ts:14` `VITE_MOCK_API` 默认 ON；`scripts/smoke.mjs` 是 playwright-core 冒烟（21 断言，打 mock dev server）。

## 2. 规格对照：承诺 vs 实装

§5.2 骨架清单（`2026-09-15-web-layer.md:440-457`）逐条在：api/client、stores、三 pages、PdfPane/HtmlPane/sync/alignment、四个 components 全部对应落位；§5.3 同步伪码逐行落地为 `sync.ts`（20% 焦点线 `sync.ts:23`、ignoreTop `sync.ts:103`、epoch `sync.ts:107`）；§5.4 `view:"html"` 降级 + `dual.json` chunks + KaTeX 容错在 `HtmlPane.tsx:84-97`、`view.ts:14`；§5.5 vite 侧 pdfjs 资产拷贝 + 许可证聚合在 `vite.config.ts:17-54`；§2 端点面全部有调用点；§2.2 SSE 七事件全消费（`client.ts:620-632`），`ping` 走 sse-starlette 注释行无需客户端处理（`app.py:911`）；模式切换保位置（`Reader.tsx:212-233`）、位置防抖 1s 落盘（`Reader.tsx:289-292`）、`document_version` 409 语义（`Reader.tsx:283`）、`needs_auth` 内联 key 重试（`Reader.tsx:660-669`）、share pack 三挂载点（`Reader.tsx:929/681/986`）、上传进度 XHR（`client.ts:336-380`）均实装。

规格/对标承诺但**前端未实装**的点：

- **任务列表无「继续」入口**：§3.4.4（`2026-09-15-web-layer.md:380`）明确「前端列表面向用户"继续"按钮」——`TaskList.tsx` 行内只有删除钮（`TaskList.tsx:151-160`），interrupted/needs_auth/fault 任务须点进 Reader 结果面板才有重试（`Reader.tsx:670-677`）。
- **`?status=` 过滤面有 API 无 UI**：`api.tasks(status?)`（`client.ts:461`）与服务端 `?status=`（`app.py:1304-1307`）都通，Home 无过滤控件（`Home.tsx:404-423`）。
- **左右互换不持久**：`swapped` 是 Reader 本地 signal（`Reader.tsx:47`），`putPosition` 只保 positions/active/mode/zoom/sync 五键（`app.py:1518-1522`）；hjfy 用 `localStorage.translatePosition` 持久（`2026-09-14-hjfy-site.md:66`）。
- **document.title 不随任务变**：只在 `main.tsx:7` 静态设置一次；hjfy 翻译中改标题（`2026-09-14-hjfy-site.md:30`）。
- **默认视图不随视口**：`mode` 恒 `"split"` 起（`Reader.tsx:43`）；hjfy 按 `innerWidth>1080` 选 split/translated（`2026-09-14-hjfy-site.md:63`）。
- **无拖拽上传、无示例论文链、无版本回退提示**：上传只有点选 file input（`Home.tsx:222-232`）；hjfy 有拖拽区 + 三篇示例 + `v\d+` 失败剥版本重试链（`2026-09-14-hjfy-site.md:19,22,34`）。
- **工具条薄于 hjfy**：无旋转/全屏/打印/首末页/暗色主题；批注只有单色高亮 + 带批注副本下载（`PaneSidebar.tsx:104-110,139-150`），hjfy 有多色高亮 + freetext（`2026-09-14-hjfy-site.md:70`）。规格 §5.2 本未承诺这些，属对标差距而非违约。
- **i18n 单语中文**：`i18n/zh.ts:1` 自述 M3 先中文单语，`import { t }` 直接钉死 zh——属有意取舍，不是债。

实装了但**规格没写**的点（多为 hjfy parity 或加固，非镀金）：完整 pdf.js 侧栏三 tab + FindBar 全协议 + DocInfo（hjfy 对等件）、高亮批注与 `saveDocument` 下载、`Idempotency-Key` 意图级生命周期（规格只写了「可选头」，`client.ts:391-456` 做了未决复用/结案语义）、`>500px` 漂移跳回（`Reader.tsx:32,294-320`，hjfy §2 行为）、transport 徽标（`Reader.tsx:776-780`）、doc 类任务 files 面板（`view.ts:12` 五态视图机）、mock dev server 与 playwright 冒烟基建。

## 3. UX / 工程债

- **Reader.tsx 1005 行单文件三合一是最大工程债**：数据装载 + SSE 装阅读器 + 同步引擎接线 + 模式迁移 + 位置持久化 + 重试 + 分享 + 进度视图 + 三种结果面板同驻（`Reader.tsx:37-1005`）；`renderResultBody`/`renderShareBlock`/`renderPane`/`renderDownloads` 四个返回 JSX 的内部函数（`Reader.tsx:488,584,687,705`）已自然分出组件边界——进度视图与结果面板各提成子组件可砍掉一半体量。
- **SSE 扇出无界**：`taskStore.refresh()` 对**每个**非终态任务 `watch()` 一条 `EventSource`（`tasks.ts:85`、`client.ts:608`）；Reader 卸载不 unwatch（`Reader.tsx:139-147` 只清引擎与防抖），排队任务也常年挂流。HTTP/1.1 浏览器每域约 6 连接——队列里 6+ 个在途任务时后续 EventSource 与普通 fetch 一起排队，表现为进度停更、API 假死。「所有 arXiv 论文」批量场景必撞。
- **死代码/只写字段**：`SyncEngine.expectedTop`（`sync.ts:92`）与 `counterpart`（`sync.ts:97`）全仓无调用；`TaskLive.stage` 只写不读（声明 `tasks.ts:22`、写 `tasks.ts:105`、读侧零命中——Reader 用 `task()?.stage` 与 `live()?.stages`）。全 web/ 无 TODO/FIXME。
- **错误/空态/加载态覆盖度高**：`ApiError` 统一出口（`client.ts:310-329`）、`role="alert"`/`role="status"`/`aria-live` 在错误行、transport 徽标、上传进度、settings 消息上都在；空态有 `t.home.empty`、`pane-empty`、`chunkEmpty`、`side-empty`、`reader.notReady`；加载态有 spinner veil（`PdfPane.tsx:192-196`）与 `view()=="loading"` 页（`Reader.tsx:998`）。已知沉默面：`putPosition` 409/网络失败被 `catch(()=>undefined)` 吞（`Reader.tsx:277-287`）——位置静默丢失无任何提示；`saveNow` 的 per-side `capturePos` try/catch 同理静默（`Reader.tsx:269-274`）。
- **可访问性**：radiogroup + roving tabindex（`Segmented.tsx:26-41`）、progressbar 三属性带任务名 label（`TaskList.tsx:133-139`）、`role="dialog"`（`DocInfo.tsx:64`）、`aria-pressed`/`aria-expanded`/`aria-haspopup`、Escape 关菜单弹层、统一焦点环（`app.css:52` 起）、`prefers-reduced-motion`（`app.css:1856`）。缺口：菜单/弹层无焦点圈定与焦点返还、缩略图钮用非标准 `page-number` 属性（`PaneSidebar.tsx:227`）缺 aria-label、无 skip-link、pane 滚动容器本身不可聚焦——整体是「散点达标、未成体系」。
- **样式组织**：单 `app.css` 1868 行按节注释分块、`:root` 变量调色板（纸面书房主题）、响应式五断点收尾（`app.css:1802-1854`）——干净但单文件；**无暗色主题**（无 `prefers-color-scheme`、无 localStorage 偏好），阅读器产品夜间场景是显性短板。
- **打包形态**：单 `index-*.js` 1069KB（`server/static/assets/` 实测）——App 静态 import Reader（`App.tsx:5`）→ pdfjs API + KaTeX + marked 全进首屏 chunk，KaTeX 字体全量 emit；`chunkSizeWarningLimit: 3200`（`vite.config.ts:73`）是把警告静默而非拆分。本地面向 localhost 影响有限，server 形态外发时首屏税明显。

## 4. 测试面

vitest 23 文件 154 `it()`：纯函数层覆盖最厚（alignment 5、sync 8、view 9、paneUtils 11、taskFiles 9、taskStats 6+8、sanitize 4、i18n 4），store 行为（tasks 7、settings 3），client 契约经 fetch mock（byok 5、idempotency 8、uploadProgress 7、sharePack 10+11），jsdom 组件级（a11y 3、htmlPane 1、homeByok 4、homeByokUpload 6、homeUploadProgress 8、settingsForm 11、taskDelete 4、readerZoom 2）。`vite.config.ts:75-78` 默认 node 环境、jsdom 逐文件 pragma。

缺口：`openTaskEvents` 的 SSE 解析/重连/坏帧丢弃零覆盖（`client.ts:607-653` 全靠 smoke 间接）；`request()` 错误映射（非 JSON 体、204、taskId 提取）无直接用例；Reader 主流程（模式切换/pendingJump/drift/持久化防抖）除 readerZoom 外近乎裸奔；FindBar/Toolbar/Segmented/ProgressGrid/App 路由无测试；`dev/mock-api.ts` 自身无测试而它同时是 smoke 的判据后端——契约漂移会造成假绿。另有 `scripts/smoke.mjs` 21 断言 playwright e2e（mock 后端，覆盖 home→提交→进度→阅读器→下载菜单→模式切换→doc 面板→settings→窄屏）。

## 5. 与后端的契约缝

**对得齐的部分**（抽验过）：全部调用点命中 `app.py` 路由表（translate `app.py:837`、task GET/SSE `886`、files `915/930`、upload `1024`、share/import `1082`、share/pack `1177`、health `1286`、tasks `1304`、cancel `1341`、retry `1368`、DELETE `1435`、reader `1462`、position `1507`、settings `1530/1539/1561`、providers `1591`）；`X-Texlate-*`/`Idempotency-Key` 头名双侧一致（`app.py:645-647,753`）；409 `duplicate_active` 体带 `task_id` 前端 `ApiError.taskId` 正确提取（`app.py:770`→`client.ts:320`）；upload 的 `options.glossary` 服务端按 `options.get("glossary")` 收（`app.py:782-784`）与前端把 glossary 塞进 options（`Home.tsx:149`）咬合；`done{status:"deleted"}` 收尾帧两侧语义一致（`tasks.ts:125-137`）；reader 404 双条件与 `view` 字段按 `2026-09-15-web-layer.md §2.5` 勘误口径消费；`Last-Event-ID` 走 EventSource 原生 + 服务端 int64 夹取（`app.py:897-903`）。

**缝/隐患**：

- SSE 扇出无界（见 §3）是契约层的真实规模缝——服务端 `EventBus` 每任务订阅队列有界（`events.py:25`）但前端连接数无治理。
- `TaskSnapshot` 类型允许 `kind`/`status`/`error.code` 落 `| string` 兜底（`client.ts:23,41`）——服务端加新枚举前端不炸但徽标/文案退化裸串，属有意的向前兼容。
- `landingHash` 对 `reader_url` 做正则提取、失败回退 task_id（`client.ts:598-601`）——URL 形状变化不会白屏，设计健康。
- `putPosition` 的 `document_version` 409 被静默吞（`Reader.tsx:286`）——服务端拒写旧版位置是正确行为，但前端不可见，用户只表现为「偶尔位置没存上」。
- `GET /api/tasks` 返回 `{tasks:[...]}`、providers 返回 `{providers:[...]}`，客户端做了「数组或包装对象」双兼容（`tasks.ts:83`、`settings.ts:22`）——服务端实际恒为包装形，双兼容是无害冗余。
- 前端 `main` 字段只在 upload 路传（`Home.tsx:163-171`），`translate` 路 body 无 `main`——arxiv 任务换主文件无入口（后端 retry body 收 `main`，`2026-09-15-web-layer.md:255` 勘误），UI 未暴露。

## 6. 三个最值得做的改进（按用户感知价值排序）

1. **SSE watch 收敛 + 批量任务可观测（M）**：`tasks.ts:85` 的全量 watch 改为「仅可见任务/详情页任务挂流 + 列表行轻轮询（如 5–10s `GET /api/tasks` 快照差量）或服务端加 tasks 级聚合流」，Reader 卸载补 `unwatch`。消掉 6+ 在途任务时进度停更/API 假死，为批量预译（项目终极目标）扫清前端正门。工作量 M：store 层改调度 + Reader onCleanup 补 unwatch + 一处轮询定时器，核心代码 <150 行，但需要把 `live()` 降级路径补测。
2. **列表行恢复/重试直达 + 状态过滤（S）**：`TaskList` 行内对 `interrupted`/`needs_auth`/`fault`/`cancelled`/`partial` 出「继续」钮（命中 `api.retry`，needs_auth 弹内联 key 或跳详情），并在任务列表上加 `?status=` 过滤 segmented——补 §3.4.4 承诺的「继续」入口，也把已存在的过滤 API 透出。工作量 S：`TaskList.tsx` 加一个分支按钮 + Home 一个 Segmented + refresh 传参，约 100 行含测试。
3. **阅读器打磨包（M）**：a) 暗色主题（CSS 变量已有调色板基座，加 `[data-theme="dark"]` 覆盖 + toolbar 切换 + localStorage——hjfy parity，阅读场景高频）；b) `swapped` 并入 `putPosition` 持久化面（服务端 keep 列表加一键 + client 恢复）；c) `document.title` 随任务态更新；d) 默认 mode 按视口宽选；e) Reader 路由级 `lazy()` 拆包让 pdfjs/katex 不进首屏。工作量 M：a 是主体（调色板反相 + PDF 画布不反相的取舍说明），b–e 均为 <30 行小改。
