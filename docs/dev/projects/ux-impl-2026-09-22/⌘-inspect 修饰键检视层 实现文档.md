# ⌘-Inspect 修饰键检视层（按住揭示 + ⌘+click peek）

实现于 2026-09-26：v1 `3b60a33d`（按住揭示 + ⌘+click peek 三 pane 全通）+ `272bc14b`（命中分面收紧/揭示强化/句级联动共轨）。覆盖 pdf/dom/html 三 pane 臂。

## 目标

阅读器内的「可查元素」分布在三层——DOM 锚（`a[href^="#"]`/`.cite-ref`/`[data-bib-key]`/math 宿主）、pdf 链接批注（linkAnnotation）、pdf 命名落点（named dest：式/图/表/节目标区，无锚面）。裸阅读下三者不可见也不可点。检视层用「按住 ⌘」作显式模态：arm 后给出统一揭示（锚面虚线/命中行带染色/容器 cursor），⌘+click 原地开 peek 卡——不抢裸点击的原生跳链/选区语义，不滚动、不改 hash。

## 交互规格

| 手势             | 行为                                                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| ⌘ 按住           | `.panes.insp-armed`：锚面 `a[href^="#"]`/`.cite-ref` 出虚线下划线；松开即卸                                                   |
| ⌘+hover          | 逐命中揭示：锚→锚标热；浮动体本体→宿主标热（section 限标题域）；pdf 非锚命中→落点行带 `insp-hot` 底色 + 容器 `cursor:pointer` |
| ⌘+click 锚       | `cite.*` → CiteCard；其他 dest → UsagesCard                                                                                   |
| ⌘+click pdf 非锚 | `inspectDestName` 分面命中 → UsagesCard（卡落点击矩形）；无命中吞点击（不跳不滚不选区）                                       |
| ⌘+click math     | LatexCard（copylatex 冒泡委托臂存活）                                                                                         |
| ⌘+Alt+click      | 对侧镜像跳（`mirrorDest`）                                                                                                    |
| 裸 click         | 原语义全放行（pdf.js 锚跳/文本选区）                                                                                          |
| Esc              | Esc 栈统一解卡 → 解 arm                                                                                                       |

## 命中模型

### dom/html 臂

`ANCHOR_SEL` 锚族（`a[href^="#"]`/`.cite-ref`/`[data-bib-key]`/math 宿主选择器）+ `usageIndex().forEl(el)` 宿主反查双路；`body.contains(el)` 域校验防越 pane 误染。命中在 `hoverEval` 内出 `hots[]`（锚自身或宿主单元素）。

### pdf 臂分面容差

旧单一 `INSPECT_TOL=0.1` 页分位容差被废的根因：0.1≈±100px，落点上下五六行正文全被吸进最近 dest——「没放到文字上也被判在点」实证。现行模型按指针元素分两路（`PdfPane.inspectDestName`）：

| 落点              | 判定链                                                                                                                                    |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| textLayer 字形上  | `destAtPoint(0.02)` 行级紧收 → 落空再 `destAtPoint(0.045, kinds=float)` 补——文字行级判定；浮动体二窗补「式号右置锚在左/多行式跨数行」形态 |
| 非字形（图/空白） | `destAtPoint(0.09, kinds=float, maxDx:0.45)`——中窗收图面本体（图面无字可点，窗是「点在图上」语义）；`maxDx 0.45`≈一栏宽，挡跨栏同高误吸   |

`destAtPoint` 本体：同页 `destPos` 候选 → `other` 类拒收 + `|Δfy|≤tol` + `opts.kinds` 白名单 + `opts.maxDx` 栏距闸 → `Δfy + 0.25·Δfx` 最近邻；`bestHit`（destSites 非空=真被引过）优先于 `bestAny`。`INSPECT_TOL(0.1)` 常量仅存作 dom/html 臂参考值——pdf 臂判定已全部收进 pane 内分面模型。

### dest 数据面（pdf）

- `scanDests` 页序=视口页为中心螺旋外扫——annotations/seqmap 可用性跟着用户视线走（原序扫时非首页读者的本体反查/Inspect 命中要干等全文档扫完）。idle 分片。
- `resolveDestPoints` 与页扫**并行**起跑——dest 落点表独立于 annot 扫描，串行时 `destAtPoint`/Inspect 命中面存在全文档时长的死窗。
- `destSites` 携 `{page,y,frac,fx}`——annot rect 经 `page.view[]` 反算页内分位，供卡站行语境抽取。
- `destPoint` = `destPos` 反查（dest 名 → `{page,frac,fx}`）——落定闪/行带揭示/行文本抽取的点名寻址面。

## 卡片路由与标签派生

`inspectAt`：锚命中 → `cite.*` 走 CiteCard、他走 `openUsagesFor`；非锚 → `inspectDestName` → `openUsagesFor`（卡落点击矩形）；`other` 类 dest 不出卡、无命中吞点击返 true（防穿到原生跳链）。

**UsagesCard 标签**：`anchorTextOf`（锚矩形下 textLayer 印刷文本）→ 碎片判据（空/<2 字符/无 `\p{L}\p{N}`）落 `destRowLabel` 落点行派生：

- equation 抓 `\(\s*\d{1,3}[a-zA-Z]?\s*\)`（"(N)"）；
- 浮动体抓 `Fig(ure)?s?|Tab(le)?s?|Sec(tion)?s?|Eq(uation)?s?|Theorem|Lemma|Proposition|Corollary|Algorithm|Appendix|图|表|式|节|章|定理|引理|命题|推论|算法|附录` 词族 + 尾随 `[\w.:-]{0,10}`；
- 兜底行首 4 词。

根因实证：eq 号 span 按字切块、锚矩形只罩开括号 → 卡标题曾显示 `"("`。

**站行语境**：`p.N` → `p.N · 引用行文本（≤60 字符）`——`destLineText` 按站 `frac/fx` 取行文本；`bandElsNear` 按 `[0,±0.008,±0.016]` 页分位五档微探（锚分位取自批注矩形顶缘、常悬行带上沿白缝，直取常空）。`destHotAt` 揭示面同源——返回 `{dest, els=落点行带元素集}` 给 inspect.ts 染 `insp-hot`。

## 与 sent-align 的共轨（闪示单轨纪律）

- `saFlash` 单轨：sentalign 句级闪与 `goToDestination` 包装落定闪共用一轨——`saFlashAt` 记最近打闪时刻，`landingFlash` 见 400ms 内已有新闪则整场免打（迟到整锚闪会把句闪踩回段闪——实机回归实证 54 叶/284px 全 seq 闪）；`flashDest` 首拍延 180ms 让句级闪先落定。
- `mirrorDest` 直调 `origGoTo` 不经包装——`ReaderView.mirrorTo` 成功支补 `dh.flashDest(dest)`；包装支同接 flashDest。usages 站跳/cite 锚跳/镜像跳三路落定揭示自此同源。
- `landingFlash` 落点 Pos→`seqAtPoint` 多 x 采样（dest 常在块间白/栏缝/图区，单点易落空）→ seq 锚叶闪；无 seq 退 `bandElsAt` 行带；懒渲页两路皆空时 200ms 步最多重试两拍。

## 文件级落点

- `web/src/reader/features/inspect.ts`：armed 状态机/`hoverEval` 双路（body 锚族+宿主 / pdf `destHotAt`）/`hotEls[]` 元素集/pend 节流/Esc 挂栈；`InspectHandle` 增 `destHotAt` 可选口。
- `web/src/reader/PdfPane.tsx`：`inspectAt`/`inspectDestAt`/`destHotAt`/`flashDest`/`tintEls` handle + `scanDests` 螺旋序 + `resolveDestPoints` 并行 + `destPoint`/`destLineText`/`destRowLabel`/`bandElsNear` + `landingFlash`/`saFlashAt` + `destAtPoint` opts（kinds/maxDx）。
- `web/src/reader/DomPane.tsx`/`HtmlPane.tsx`：armed 揭示（锚面标热/宿主标热）+ `inspectAt` 臂。
- `web/src/reader/ReaderView.tsx`：三臂挂 inspect 会话、`mirrorTo` 成功支 `flashDest` 补点、`pdfTintEls` dep 桥（句级悬停色）。
- `web/src/styles/inspect.css`：`.insp-armed` 揭示面 + textLayer 行带 `insp-hot` 底色带（浅 14%/深 20% 朱砂，`border-radius:2px`）——逐 span outline 会碎成一列方盒，统一改底色带读作「这一行/式可检视」。
- `web/src/test/inspect.test.ts` + `sentalign.test.ts`：pdf 臂 mock 走 `destHotAt` 形、peer 随 pos 重算语义。

## 验证

- vitest：inspect 套 + sentalign 套全绿，全量 961/961；tsc/eslint 净。
- playwright 实机（`tmp/inspect-verify/` 探针组、真任务真 PDF 臂）：`pw_inspect.mjs` **12/12**——armed/disarm、cite→CiteCard、非 cite→UsagesCard、空白吞（无卡无滚动）、裸点击原生跳回归、⌘+Alt 镜像滚、html 臂 cite/host/math/blank 四面；`pw_seq_repro.mjs` **14/14**——eq 号 dy0 中卡/dy60+ 他行 dest 属正当、段文不开卡、eq 行带 insp-hot、hover 句级（hot 18/215 叶、peer 21 叶）、点击落定闪 21 叶/15.7px（对照 seq 块 358px）。

## 已知边界

- named dest 覆盖天花板：29% 文档零 dest、cite dest 仅 59.6% 文档有（fu-dest-vocab）——pdf 臂恒机会型，UI 不承诺全覆盖；dom/html 依赖锚面存活（zh id ~92%，见 find-usages 档 P2 修复项）。
- 死文本「(N)」式引用字面（非 dest 落点）⌘+click 不开卡是**正确语义**——点在引用目标本体（式号/图/表区）才有卡；段内散文提及不产假卡。
- `destHotAt` 行带染色按 dest 落点行（非点击行）——式号右置时染色带落式体行是预期（锚的本体位）。
