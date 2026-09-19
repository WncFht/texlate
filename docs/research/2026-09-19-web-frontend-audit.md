# Web 前端审计：卡顿归因 + 导读差距 + UX/设计清单（2026-09-19）

> 方法：三路代码审计（性能/导读差距/UX 设计）+ 真后端实测（`~/.texlate` 真实任务 1706.03762v7「Attention Is All You Need」，vite 代理 → 127.0.0.1:8765，playwright 探针采长任务/rAF 帧间隔/DOM 体量）。探针脚本 `web/scripts/probe-ux.mjs`+`probe2.mjs`，截图 `web/scripts/shots/r*.png`。

## 一、卡顿实测数据（真数据）

| 场景 | 测量 | 结论 |
|---|---|---|
| wheel 滚动（split + 同步开，PDF 双栏） | 150 帧采样：p50=17ms，**p95=67ms，max=100ms，28% 帧 >33ms** | 真掉帧，源在联动侧 pdf.js 被迫连续渲新页 |
| 模式切换（对照→单栏→对照） | 401ms / 801ms | 隐藏侧 display:none→visible 触发 pdf.js 重排重渲 |
| 导读展开 | ax-ov-body 实测 6073px/955 节点塞进 420px `overflow:auto` 盒 | scroll-in-scroll + 巨型图（1520×2239 渲到 1178px 宽） |
| 阅读器首屏 chrome | toolbar+导读横幅+分享横幅 ≈ 215px，双侧 rail ≈ 68px | 900px 视口内容区只剩 ~660px |
| 长任务 | 会话内 10 次 50–85ms | 与滚动同步/pdf.js 渲染同源 |

## 二、卡顿根因（代码实锤，按嫌疑排序）

1. **html/dom 窗格首轮滚动必卡**：`.chunk` 用 `content-visibility:auto` + `contain-intrinsic-size:auto 300px`（panes.css:393-401），同时 `bindChunkGeom` 给**每个** chunk 挂 ResizeObserver（sync.ts:110-112）。首轮滚过每块从 300px 占位撑回真实高度 → RO 触发 `cache=null` → 下一滚动帧 `pages()` 对全部块重读 offsetTop/Height（sync.ts:118-124）→ 强制 layout flush 连环，scrollHeight 持续漂移、同步锚点抖动。修法：RO 只盯 scroller+body（几何失效由 MO/rebind 覆盖已够），或几何表在「该块渲染后」再锁定。
2. **PDF 同步滚动联动渲染**：SyncEngine 本身没问题（rAF 合帧+回声抑制，sync.ts:171-193），掉帧来自联动后果——src 滚一屏，dst 被写 scrollTop，pdf.js 为新进视口的页连续渲 canvas，双份齐发。这是「开同步必顿」的结构性成本。方向：目标侧 scrollTop 写入后 pdf.js 渲染不可避，但可把 `alignNow` 的触发频率再降一档（滚动结束才对齐 vs 逐帧跟）做成可选档；或对非活动侧重渲降优先级。
3. **dual.json 无版本每次全量重拉**：Reader.tsx:112 直拉 `dual.json` 不带 `?version=`，服务端 no_store → 每次进 reader 重下 + `res.json()` 主线程解析（大论文数 MB，en+zh 全文双份常驻）。records 已有 sha256——走内容寻址 `?version=` 让 304/磁盘缓存生效；或把 chunks 文本与 alignment 拆端点按需拉。
4. **DomPane 挂载一次性冻结**：整文档 fetch→DOMParser→`sanitizeDomHtml`→一次 innerHTML（DomPane.tsx:105-117），arXiv HTML 1–3MB 主线程冻结数百 ms。修法：按 `.ltx_page` 顶层节点分片注入，复用 HtmlPane 40ms 时间盒。
5. **SSE chunk 乱序补齐 O(seq) 写**：tasks.ts:219-224 对 seq 空洞逐格 setState 补 pending——一跳到 seq=N 的帧写 N 次，病态 seq（上限 100k）一帧冻结。修法：构造补丁数组单写。
6. **LivePane 折叠仍全量绘制**：`<details>` 合上后 onPage→enqueuePaints→paint 照跑（LivePane.tsx:146-168），marked+KaTeX 白做。修法：closed 只记 acc，展开 backfill。
7. **进行中视图总线繁忙**：LivePane 分片绘制 + ChunkPreview + ProgressGrid 逐格 + log 追加 + 秒表同跑——单项不贵，合起来持续掉帧感；且 ChunkPreview 与 LivePane 是同批 chunk 的两份列表（UX 重复，见下）。
8. **轻项**：`capturePos` 线性扫（sync.ts:40-46 可二分）；`.task-bar`/`.tp-bar` width transition 每 SSE 帧重启动画（progress.css:58、tasklist.css:352）；JSON 端点无压缩（server 形态远程访问 ×3-10 流量）。

**已做对不要回退**：SyncEngine rAF+回声抑制、几何缓存、ProgressGrid 逐格订阅、chunkPoll 增量 seqs、HtmlPane/LivePane 40ms 分片、SSE 3 槽+轮询降级、store 字段级补丁、usePDFSlick keyed 重挂纪律、panes U3 常驻不重挂。

## 三、导读功能差距（对照 alphaxiv 逆向报告）

当前 `AxBlock.tsx` = 220px OG 分享图 + badge + title + 截 4 行的 summary + `<details>` 全文。实测与代码共同暴露：

1. **OG 卡是纸浪费**：alphaxiv 分享图缩到 220px 文字不可读零信息量，img 无 aspect-ratio 加载推挤版面（CLS）；与右上 `ax-link` 双外链互抢（AxBlock.tsx:57-88）。
2. **scroll-in-scroll**：6073px 正文塞 420px 滚动盒（observability.css:290-296）；图只限宽不限高，单图 ~1735px 占 4 倍盒高。
3. **结构抹平**：blog h1/h2/h3 全压 14px（observability.css:303-308），alphaxiv overview 是动态分节（7 节含 `$$`+插图），压平后无节可辨、无导航。
4. **拿到的数据没用**：`summary.{originalProblem[], solution[], keyInsights[], results[], feedDescription}` 六件套只渲 `summary.summary` 且截 4 行；`citations[]`（带 justification+alphaxivLink）**完全没渲染**（types.ts:459 声明后无消费方）。
5. **en-only 无兜底动作**：我们是翻译产品——en 导读命中 zh 缺席时挂个「· EN」徽标就完事（AxBlock.tsx:77-79），自家网关补译 ~12KB markdown 是主场却不提供。
6. **未生成=整块消失**：`available:false` 静默（AxBlock.tsx:26），「在 alphaXiv 上打开/请求生成」的口子都没有。
7. **横幅常驻吃高度**：挂 ReaderView banner 槽（ReaderView.tsx:574），三种模式都压在 PDF 上方不可收。

### 改造方案（推荐 A）

- **A. 导读窗格**：mode segmented 加「导读」档或 PaneSidebar 加 tab——导读是文档形内容给文档级版面：title + 字段卡（问题/方案/洞察/结果四格）+ 全高 blog + 节锚 mini-TOC + citations 页脚；复用现有 pane/scroll/sync 机制，消灭横幅与 scroll-in-scroll。OG 卡缩成文字链或挪进 ShareBlock（它本来就是分享图）。
- B. 横幅重构：OG img 换 compact chip；summary 渲成字段格；展开放开 max-height+sticky 节锚。改动最小但仍「页面顶上一条」。
- C. 右侧抽屉：toolbar 加「导读」钮，右拉 drawer 承载 A 的内容——pane 不动但多一套 overlay。

三案共通两件顺手活：blog 内 h2 提取生成节锚；en-only 挂「翻译此导读」钮走自家管线。

### 值得继续借鉴的 alphaxiv 功能（按 ROI）

- 高：渲染已拿到的 summary 六字段+citations（纯前端活）；en→zh 导读自译兜底。
- 中：「问这篇论文」QA——alphaxiv 侧需 auth，但 texlate 有 dual.json chunks+BYOK 网关，grounded QA 可自建且是差异点。
- 低：references 解析（其覆盖 1/15）——texlate 有 LaTeX 源可自抽 `.bbl` 边，要做自建不抄。
- 不做：逐行评论/社区件（需账号体系）、`request-ai` 代触发（auth，只能给外链）。

## 四、UX/设计清单（按档位）

### 必须改

1. `.result-banner` 布局实为坏的：`display:flex` 单行无 wrap 摊 ResultBody 全部件横向挤压溢出（observability.css:151 + Reader.tsx:429）→ banner 改 `flex-direction:column` 或 ResultBody 做紧凑变体。
2. ax-suggest 搜索建议键盘不可达（Home.tsx:688-739）：无 ↓↑ 导航无 aria-activedescendant。
3. Serif 身份字体不落网：`Source Han Serif SC/Songti SC` 全靠系统装有（base.css:23），Linux 下 CJK 掉回 sans，wordmark/h2 衬线层级静默降级 → 打包 Noto Serif SC 子集 woff2 或接受 sans 兜底重调字重对比。
4. share/result 横幅不可 dismiss（Reader.tsx:439-450）：done 任务每次打开顶两三条横条 → 加 ✕ + localStorage 记已读。
5. 进度页一面墙（TaskProgress.tsx:148-427）：stepper+bar+ETA+统计+时间线+棋盘格+ChunkPreview+LivePane+fixloop+L2+警告+日志全同级，且 ChunkPreview 与 LivePane 是同批 chunk 两份列表 → 合并预览进 LivePane，细节收进「运行细节」分组。

### 应该改

6. Home 信息流倒置（Home.tsx:867-937）：alphaXiv 热榜卡在 hero 与自己任务列表之间 → 任务列表提前，热榜移下方或收横滚条。
7. split 双栏每窗格各挂 34px rail+196px 侧栏（panes.css:14-64）→ 侧栏跟随 active 窗格共用一份。
8. `window.confirm` 删任务（TaskList.tsx:251、307）→ 行内二次确认或 toast 撤销。
9. `?` 快捷键帮助不可发现（ReaderView.tsx:166-167）→ toolbar 加 `?` 钮。
10. 任务选项 14 行全堆一个 details（Home.tsx:813-830）→ 分「常用/高级」两组。
11. 文案：`fFailed`「异常」桶混 cancelled/needs_auth→「未完成」；`srcHtml`「无源时降级」→「无 LaTeX 源时」；`statsL2`「L2 校验」→「校验重译」；needs_auth 面板错误行与操作行重复→留一处；`fxDied`「编译器崩溃」→「编译中断」。
12. html 视图页码输入整体禁用（Toolbar.tsx:179）但有段定位能力 → 放开按 chunk seq 跳。

### 锦上添花

13. 页码 `type=number` 52px 自带 spin 钮 → `appearance:textfield`。
14. `.task-time`/`.tb-title` 窄屏 display:none → 截断或移 meta 行。
15. `#/arxiv/{id}` 深链落地即自动提交翻译（Home.tsx:354-364）→ 预填待确认。
16. rail 图标 ⧉⌕ 冷僻 unicode 部分字体出 tofu（PaneSidebar.tsx:154-157）→ svg 或常见字形。
17. 「——」破折号风格不统一 → 统一逗号句式。

## 五、建议动手顺序

1. **导读重做（方案 A）**：用户主诉 + 纯前端收益最大，一次消灭 OG 浪费/scroll-in-scroll/字段浪费三件。
2. **RO-per-chunk 修复（卡顿 #1）**：一行级改动消首轮滚动卡顿。
3. **横幅三件套瘦身**：result-banner flex 修复 + 可 dismiss + ax 横幅撤掉（并入 A）。
4. **dual.json 版本化 + DomPane 分片（卡顿 #3/#4）**。
5. **进度页重组 + Home 信息流**：进行中体验与首屏秩序。
6. **其余 should-fix 批量过**。

## 附：实测环境

真后端 `uv run python -m texlate.server`（:8765，`~/.texlate` 库 31 任务）+ vite `VITE_MOCK_API=0` 代理（:5199）。探针：wheel 事件驱动滚动 + PerformanceObserver longtask + rAF 间隔采样；alphaxiv overview 走真上游（1706.03762 命中 zh 导读全文）。
