# ADR-0021 引用跳转/跳回与文献悬浮卡：同锚双语义 + 自研跳回栈 + 本地条目三路兜底

> **状态**：现行
> **日期**：2026-09-21（初次裁决）

## 上下文

阅读器引用链 `[n]` 原来只有 pdf.js 裸 `goToDestination` 一跳——跳过去回不来，也看不到条目内容。126-subagent 生态调研（`docs/research/product/2026-09-21-citation-ux.md`）给出三条铁律约束：①pdf.js `PDFHistory` 写真 `window.history`+`#nameddest` hash，进 SPA 即触发 `App.tsx` hash 路由兜底跳 home——绝不可用；②`preventDefault/stopPropagation` 拦不住 onclick 属性处理器，唯一拦截点是包装 `linkService.goToDestination`；③浏览器绝不按 hover 直连 S2/OpenAlex——免 key 池 429 常态，必须服务端代理+TTL+ 负缓存。

## 裁决

- **同锚双语义（Zotero 模式）**：同一 `[n]` 锚 hover=悬浮卡、click=跳文献表 + 压栈；触屏 tap=出卡（卡内「跳到文献表」钮承担跳转）。时序取 Wikipedia PagePreviews 常量：150ms dwell 开、350ms 宽限关；scroll/scalechanging/pagesdestroy 收卡；Esc capture 关；`focusin` 立即开（WCAG 1.4.13）；MO 给无文本 `.linkAnnotation>a` 渐进注 `aria-label`。
- **自研跳回栈（sioyek 语义）**：`web/src/reader/navstack.ts` `NavStack`——`entries[]+idx` 游标，跳时把跳前活态写回当前槽再推入落点，回跳瞬间同样回写活态（返回点=按返回那刻的位置）。每 pane 一栈；滚动永不入栈。浮动 `.nav-chip`（↩/↪）+ Backspace/Alt+←/Alt+→；导航栈与 drift 钮同框时导航栈优先（程序跳转窗口内 `navHolds` 抑 `updateDrift`）。
- **单点劫持**：PdfPane 包装 `ls.goToDestination`——所有跳转（用户点击 + 镜像）经 per-pane `navChain` Promise 队列串行落定（pdf.js 内部多 worker 往返，裸并发乱序落定 + 栈失真）；`navSeq`/`mirrorSeq` last-wins 作废在队旧任务，`pre` 在任务执行时现捕。入队即 `onNavBegin`+收卡；string dest 先 `getDestination` 预检死链（pdf.js 静默 no-op 不抛——不预检会产 pre≈post 幻影栈项并截断前进栈）；`_ignoreDestinationZoom` 常置（dest 自带缩放会让双侧发散且 store 无回写）。`onNavBegin`：`navHolds++`+`navMuteUntil.at`（共享时间戳访问器注入 SyncEngine——引擎重建后新实例仍读到未逝截止点，计数器 release 绑旧实例会丢）600ms 自释放。
- **split 镜像**：`onDestJump` 在 `mode()=="split"` 时 `mirrorTo(对侧,dest,2,pair)`——dst handle 缺席挂 `pendingMirror`（paneReady 补投 +1200ms 重试，槽位覆盖即弃）；成功且 `!samePos(pre,post)` 才记 dst 栈（pre≈post 不记——已在视口内的点击压栈会截断前进栈）。**pair 配对回跳**：每次 cite 跳发 `navPairSeq` 号双侧同号入栈，一侧 ↩/↪ 命中 pair 项且对侧栈顶/前进票同号即联动——双侧各自回自己跳前位，非 pair 历史不受影响（用户实证「一边返回另一边不动」反直觉后加）。镜像与 syncing 无关（cite 跳是刻意导航）；`onDestJump` 本侧同样 samePos 去重。
- **卡片内容三路兜底**：①`buildCiteIndex(dual)`——eprint 链 dual.json `ph` 的 `[[BIB_n]]`→`\bibitem`（按 ph 值前缀滤 `\bibliography{x}`），条目正文=同 chunk en 中该 token 至下一 BIB token 子串，经 `cleanBibText`（`phText`+`RESIDUE_RULES` 文本级版）清洗；②`extractBibAtDest` 懒抽取——pdf.js getDestination→getTextContent 按 y 分行，落点行起向下收（段距>1.7×行高/行首 `[n]` 标签/左缩进回退三类边界）；③DomPane 克隆 `li.ltx_bibitem` 剥 id/href。
- **远端元数据增强（机会型）**：`POST /api/refs/lookup`（`routers/refs.py`）——S2 `/paper/batch` 主路（`ARXIV:`/`DOI:` 前缀同批解，≤450/批）+ Crossref `/works/{doi}` 兜底（≤24，并发闸 4）；命中 24h + miss 负缓存 10min；上游整挂 `degraded=true` 仍 200——绝不 502，卡字段缺位静默隐藏。浏览器从不直连上游。
- **暂不实现**：多键 `[3-7]` 卡、pin 钉卡、M3 refs.json 产物（懒 dest 抽取同覆盖零管线改动）、OpenAlex 上游。

## 理由

- hover 卡消灭大部分跳转需求（Distill/arXiv Vanity 哲学），跳回栈只兜真跳的场景——两个需求一个锚点解决。
- 包装 `goToDestination` 是全部内链（cite/figure/section/大纲）唯一漏斗，一次劫持全收；`capturePos` zoom 无关复用 sync.ts 几何。
- 本地 bib 串 0ms/0 网络即出卡——texlate 的 dual.json ph 结构天然承载（BIB 域 zh=src passthrough，卡只出英文条目，无中文幻觉）。
- 服务端代理 + 双桶 TTL 缓存把 S2 429 风暴关在服务端——hover 触发面 ×免 key 池必死是调研实测结论。

## 现状

实现面（含对抗 review 修复）：`web/src/reader/{citations,navstack}.ts`、`CiteCard.tsx`、`PdfPane.tsx`（wrap+navChain 串行 + 委托）、`DomPane.tsx`（内链代理 + 克隆卡+flash 单轨）、`PaneSlot.tsx`（chip）、`ReaderView.tsx`（栈持有 + 远端拉取+navMuteUntil+pendingMirror 重试）、`styles/cite.css`（chip/drift 撞位让行）、i18n cite/help 段；服务端 `routers/refs.py`+注册+lifespan 收尾（`_read_body` 统一闸、S2 非 list 整挂、截短数组=unknown 不毒负缓存、Crossref `except Exception`+`return_exceptions`、doi/arxivId 长度帽）。
review 修复要点：dest 各 fit 型 y 提取（ICLR/ICML/CoRL `pdfview=FitH` 的 cite.* 锚是 len-3 数组，len<4 早退是实测踩中坑）、死链预检+samePos 幻影栈项、navSeq/mirrorSeq 乱序作废、focusin/out 挂 paneEl/scrollEl（焦点 锚→卡→卡外 三段路全程可见）、`:focus-visible` 挡指针源 focus 闪卡、`e.detail!==0` 挡键盘合成 click 误判触屏、MO 只扫 addedNodes（全容器 qSA 是滚动期热路径浪费）、meta 活访问器（远端回包晚于开卡——快照永久缺字段）、全空 meta 整块不显、aria-label 首 rect 取 `getClientRects()[0]`、开卡后 600ms 滚动宽限（tap/键盘 focus 半可见锚的浏览器 focus-scroll 会触发 scroll→close 杀刚开的卡——cite_verify 触屏断言翻车实证）、镜像跳 pair 配对回跳/前跳（NavStack entries 带 pair，对侧同号栈顶联动）。
验证：`web/scripts/cite_verify.mjs` **16/16 PASS**（hover 卡内容/Esc/复悬/click 跳 + 镜像/chip ↩↪/Backspace/触屏 tap 出卡不跳/远端 meta/零 console 错）——修复后复跑同绿；ruff/tsc/eslint/build 全过。playwright 环境坑（与功能无关）：`--disable-dev-shm-usage` 使 chromium 共享内存落 /tmp tmpfs，写满即渲染进程 SIGTRAP——脚本以 `TMPDIR=~/.cache/pw-tmp` 根治并注记。
