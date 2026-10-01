# sent-align：阅读器句级双语对位高亮/跳转

> 综合 `tmp/ux-research-20260922/` 下 10 条 `align-*` 实验道（全部 verdict=works/confirmed）与生产代码共读产出。所有指标均为真实语料实测：`~/.texlate/tasks/` 10 篇 dual.json（repo 内 128 份 dual.json 全是 stub/mock，不可用作 fixture）、7 篇真实 arXiv HTML、2695 条翻译 cohort。

## 目标

在 texlate 双语阅读器内提供**句级（sentence-level）英中对位**能力：

1. **悬停对位高亮**：鼠标悬停在任一侧某句上时，本侧该句与对侧对应"珠"（bead，m:n 句组）同时着色；覆盖 DomPane（arxiv_html 链 en.html/zh.html）、HtmlPane（dual.json chunk 渲染）、LivePane（翻译进行中增量）。
2. **点击对位跳转**：点击某句跳转到对侧对应句，复用现有 navstack/mirror 机制（`ReaderView.tsx` `onDestJump`/`mirrorTo`/`pendingMirror`，Alt+←/→ 回退前进）。
3. **分期覆盖 PDF 侧**：v1 只做 DOM↔DOM；v1.5 加 DOM→PDF 点击跳（合成 XYZ dest，无后端改动）；v2 加 PDF 句锚（`\pdfdest` 原语注入）+ 文本层 quad 高亮，双向完整；v3 让译文携带句标打破序位对位上限。
4. 默认开、可关；对文本零污染（textContent 字节恒等已实证），对渲染零布局扰动。

**证据基座**（各 lane 关键数字在后文引用处标注）：

- align-sample：真实 dual.json 取样 3 篇（400/164/85 chunks），zh/en 长比中位 0.38–0.43。
- align-en-split：2020 en chunk → 5548 句（均值 2.75/chunk），join 恒等 2020/2020，过切率 0.03%。
- align-zh-split：1048 zh DOM 节点，Intl.Segmenter vs 正则 97.7% 一致；**RAW 变体 Intl 在 `\n` 处乱切（4571 vs 4025）——必须切扁平化文本**。
- align-monotonic：贪心单调对位器 1930 chunks → 3450 beads，87.6% 为 1:1，抽验 87.5% 正确，误差全部是 zh 句界滑移；DP 对照差异率 48.3% 不优于贪心。
- align-edge：`[data-chunk]` 锚白名单——footnote（内联 `span.ltx_note` 窃宿主尾 8395 字符/38 锚）与 doomed 嵌套锚须剔除，过滤后 en/zh 锚集 7/7 文档全对齐。
- align-inject：en 侧 wrap 注入 640 句 → 1197 span/163 chunk，textContent 恒等，gzip +12.89%，1.13ms/chunk。
- align-hover-perf：事件委托 vs 逐 span 监听——真实鼠标延迟两臂无差别（med ~59ms@128k spans），但绑定成本 0.05ms vs 323ms，增量重绑 0 vs 8–40ms → **必须委托**。
- align-mismatch-stats：渲染级句数不等 chunk 占 **7.53%**（|Δ|=1 占 6.97%），方向极不对称 zh>en 89.2%（翻译只拆不合）；按 kind para 10.5%、caption 4.7%、section_title 0%。
- align-pdf-dest：PDF 句锚必须用裸 `\pdfdest`/`\special{pdf:dest}` XYZ 原语（类级 pdfview=FitH 会把 `\hypertarget` 降级丢 x）；26B/锚、编译 +5%、布局字节不变；31.5% 现役 splice PDF 完全无 dest。
- align-zh-sid：zh sid 注入 A（emit 时包 span）vs B（前端再切）→ **选 B**：A 有致命盲区（HtmlPane repaint/LivePane 增量/单块重译全部绕过 emit，且 dual.json zh 字段是裸 markdown 会被 span 污染）；B 单一实现覆盖全部渲染/更新路径，~105 LOC、~1100 span、0 产物字节。A/B sid 集 107/110 chunk 一致。**49% sid 是多片段**（跨多文本节点）→ UI 契约必须是 sid→元素集合。

## 交互规格

### sid 协议

- `sid = "{data-chunk 值}.{k}"`，k 为块内句序位（0 起）。`data-chunk` 值在 DomPane 是键串（`S3.SS2.SSS1.p1`），在 HtmlPane/LivePane 是数字 seq——同一窗格对内两侧键集一致，直接作字符串用。
- DOM 形态：`<span class="ens" data-sid="…">`（en 侧）/`<span class="zhs" data-sid="…">`（zh 侧）。span 本身无样式，仅作锚。
- **契约：sid→元素集合**。任何消费方一律 `blockEl.querySelectorAll('[data-sid="…"]')`，禁止假设单元素（实测 182/361≈49% sid 跨多文本节点）。

### bead 语义（对位单位）

- 每个 chunk 内，en 句列与 zh 句列经**贪心单调对位器**切成 bead 序列；bead 是 m:n 句组（实测 87.6% 1:1，其余 1:2/2:1/2:2/3:1…，单侧上限 MAXG=4）。
- 交互单位是 bead 不是句：悬停/点击高亮与跳转的粒度 = 整个 bead。句数不等时（7.53% chunk）天然降级为组高亮——**绝不伪装 1:1**，这是 mismatch 实测结论决定的交互底线。
- sid 同时携带 bead 标引：注入后对每 chunk 跑一次对位，给每个 span 补 `data-bead="{chunk}.{b}"`；悬停时取 `data-bead` 查两侧元素集。

### 悬停

- 委托监听挂在各 pane 的 `bodyEl`/容器上（与 DomPane 现有 cite-card 委托同址）：`pointerover`/`pointerout` 冒泡取 `closest('[data-sid]')` → 得 sid/bead → 本侧元素集加 `.sa-hot`，对侧 pane 同 bead 元素集加 `.sa-peer`。
- 对侧 bead 不可见时**不自动滚动**（滚动只发生在点击跳转；悬停只着色——避免与 SyncEngine 滚动同步打架）。
- 离开即清。增量注入（repaint/paint）后新 span 自动生效（委托无重绑成本——实测 ~0ms vs 逐 span 8–40ms/+2000 spans）。
- 无 bead 的 span（support 块噪声 sid、对侧 chunk 缺失）悬停只给本侧 `.sa-hot`。

### 点击跳转

- DOM→DOM：对侧 bead 首元素 `jumpToEl` + `flash`（DomPane 已有）；跳转前后 `capturePos` 记 `navStacks[side].recordJump(pre, post, pair)`，`mirrorTo` 的 pair 机制原样复用——Backspace/Alt+← 回退成对生效。
- DOM→PDF（v1.5）：源 bead → 所在 chunk 的 Pos + 句内分位（bead 起始字符偏移/chunk 字符数）→ `createPositionMapper`（`alignment.ts`，已支持 pairs/regions 插值）→ 目标 `{page, fraction}` → 合成 `[page, /XYZ, x, y]` dest 走 `handle.goToDestination`（PdfPane 已支持显式 dest 对象，`:774` 实例在案）。精度=chunk 内线性插值，本版即此口径；真句级等 v2。
- PDF→DOM（v2）：文本层命中句锚 quad → sid → 对侧 bead 跳转同上。
- 点击后 `.sa-flash` 闪目标 bead（复用 flash 动效，深色主题变量见 §前端改动-CSS）。

### 开关与发现性

- Settings 页加开关（默认开），`localStorage` 键 `texlate-sent-align`，信号面与 `paperTheme` 同构（`settings.ts:24` `PAPER_KEY` 模式）。
- 悬停高亮本身即发现通道，不另加引导。

## 数据/管线改动

**v1/v1.5：双.json schema 与后端零改动。** sid/bead 全部由前端在挂载后对两侧 DOM 文本重切派生；dual.json 的 `chunks[].zh` 保持裸 markdown（A 方案被否的根因之一即防污染 copy/search/md.zip 消费面）。

**v2（PDF 句锚，管线 additive）**：

- `worker/compile.py::_build_zh`（`:342` `reconstruct(res, by_int)` 之后、`prepare_chinese` 之前）：按 en 侧 `sentence_ends` 口径在 zh tex 句界处插裸锚原语——pdftex `\pdfdest name{tl.{chunk}.{k}} xyz`、xelatex `\special{pdf:dest (tl.{chunk}.{k}) [@thispage /XYZ @xpos @ypos null]}`。实测 26B/锚、编译 +~20ms（+5%）、PDF 文本层与布局字节不变（46,393 字符恒等）。**严禁 `\hypertarget`**——类级 `pdfview=FitH` 会把它降级丢 x 坐标（pdftex/xelatex 双臂实证）。
- 锚名进 `⟪⟫` 名字空间管理体系以防与用户宏撞名（`xlat/placeholders.py` 哨兵 codec 同族）。
- 存量任务无锚（仅 31.5% splice PDF 有 dest）→ 前端无 `tl.*` dest 时整体降级到 chunk 级（现行为），不报错。

**v3（译文携带句标，打破序位上限）**：

- 序位对位天花板实测 ~93.4% chunk 全对 / ~6% 句级漂移；真提准只有让模型输出句界标。扩展 `xlat/retry.py` 现有 `⟪S0000⟫` 槽位协议（`SLOTS_PER_BATCH=8`、`SLOT_MAX_CHARS=1500`、`_SLOT_ECHO_RX` 回显拒收、`_SLOT_ZW_CHARS` 零宽清洗全套现成）到全量 chunk：翻译产物中句间嵌 `⟪S{k}⟫`，splice/emit 时剥离成 sidecar `dual.json.chunks[i].sent_marks`（additive 可选字段，`web/src/api/types.ts` 同步），前端直接读 marks 跳过重切。
- 备选 spike-C 形态：后端在 zh 文本注 `⟦S{seq}.{i}⟧` 文本级标记（任何路径都存活为文本，前端物化成 span；不占 `ANY_PH_RX` 名字空间）。

## 前端改动（文件级）

### 新增 `web/src/reader/sentalign.ts`（核心模块，~300 LOC）

四段纯逻辑 + 一段会话，全部可单测：

1. **`zhSentenceSpans(text)`**——`zhseg.py` 的 JS 移植（~50 行）：终结 run `[。！？!?…]+closers` 吸收闭标点；ASCII `.` 由 `_abbrev_dot` 闸（尾词含 `.` 或 ≤3 字母、数字相邻则豁免）；`_GUARD_RX` 跳 `[[..]]`/`$..$`/`$$..$$`/`\(...\)`/URL；`{}` 深度>0 抑制切点；`\\` 双跳；`;；,，` 永不为界；句尾吸收随行空白进前句。用 `/dg` flag 的 `m.indices` 取区间。**与生产 `sentence_ends`（`xlat/batch.py:327`）同款不对称修正**——这是 chunk-exact 从 84.0%→93.4% 的来源，不许用裸 Intl 替代 zh 侧。
2. **`enSentenceSpans(text)`**——`Intl.Segmenter("en",{granularity:"sentence"})`，输入必须是扁平化文本（**禁对含 `\n` 原文直切**：RAW 变体多切 13.5%，nl-break-after 假阳性）。
3. **`injectSentSpans(blockEl, lang)`**——TreeWalker(SHOW_TEXT) 逐 `[data-chunk]` 块：acceptNode 拒 `SKIP_TAGS`（math/svg/script/style/noscript/template/annotation/pre/code/textarea/select）、`SKIP_CLASS_PREFIX`（ltx_tag/ltx_pagination/ltx_role_newpage/ltx_note_mark/ltx_TOC/ltx_tocentry/ltx_toclist/ltx_verbatim）、**`closest('[data-chunk]') !== block` 的嵌套节点**（footnote-in-para 幽灵 '。' sid 回归闸）；`RESTRICTED_SPAN_PARENTS`（table/tbody/thead/tfoot/tr/colgroup/ul/ol/dl/select/optgroup/datalist/map/frameset/picture）内文本留裸片不包 span。串接受文本→切句→**倒序** `splitText` 逐片包同 sid span。实测 1.13ms/chunk、textContent 字节恒等、幂等。
4. **`alignBeads(enLens, zhLens)`**——贪心单调对位器移植（`exp/align-monotonic/align.py`）：`rho=zh_len/en_len` per-chunk，两侧谁严格缩小 `|log(zl/(el·rho))|` 就扩谁，MAXG=4/侧，残差并入末 bead。返回 bead 列 `{en:[i..j), zh:[p..q)}`。
5. **`SentAlignSession`**——持两侧 pane `el`；`mount()` 用 `forEachSliced`（`sync.ts:37`，SLICE_MS=40 同口径防大文档卡顿）跑 inject+ 对位并建 `bead → {side → Element[]}` 索引；`attach(bodyEl)` 挂委托 pointerover/pointerout/click；`destroy()` 摘监听清索引。~120 行。

### `web/src/reader/DomPane.tsx`

- 挂载尾部（分片 append 完、`geom.rebind()` 后）调 `session.mountSide(side, bodyEl)`。
- 委托监听与现有 cite-card click/pointerover/pointerout **同址并列**（bodyEl 上再加三行 delegate）。
- 点击跳：现有 `jumpToEl`/`flash` 直接复用；把 `recordJump`/`mirrorTo` 回调经 props 接进 ReaderView 现有对（`onDestJump` 同型）。

### `web/src/reader/HtmlPane.tsx` 与 `LivePane.tsx`

- 注入点=共享上色管线尾：`HtmlPane.tsx:69` 本地 `finishChunk`（`:138` repaint、`:232` 分片 mount 两处调用）与 `LivePane.tsx:143-144` paint 内 `unmaskLatex`+`renderMath` 之后各加一行 `injectSentSpans(sec, 'zh'|'en')`。**必须在 renderMath 之后**（math 子树是 SKIP 类）。`markdown.ts:279` 共享 `finishChunk` 同步加（三处同口径注释处）。
- `repaint(seq)` 重建 section → 注入自然随 paint 重跑（B 方案覆盖增量路径的关键论据），session 对该 chunk 重建 bead。

### `web/src/reader/PdfPane.tsx`（v1.5 + v2）

- v1.5：无改动——`goToDestination(dest)`/`mirrorDest`（`:66,:70`）已接受合成 XYZ dest 数组。
- v2：文本层（textLayer div）上跑句锚 quad 派生——相邻 `tl.*` 锚间文本发射切片按基线行切 quad（两相法则：最近基线 + 同行 x-span，60/60 双栏+CJK 段中 dy=0 实证）；quad 叠层 div 加 `.sa-hot`/`.sa-peer`。zh 文本抽取需 `cMapUrl`+`standardFontDataUrl`。页尾 folio 吞锚用 leading-gap 闸（>2× median leading）。委托监听挂 `viewer.container`（cite-card 委托同址）。

### `web/src/reader/ReaderView.tsx`

- 持 `SentAlignSession` 生命周期：双侧 handle ready（`paneReady` 补投口 `:554` 同款）且开关开 → mount；`planModeChange`/换视图/关开关 → destroy 重挂。
- 点击跳回调接入 `navStacks`/`pendingMirror`/`mirrorTo`（`:132,:389`）——跳转对共用一个 pair 计数，drift 抑制窗（`:369`）复用。

### `web/src/stores/settings.ts` / `Settings.tsx` / `Toolbar.tsx`

- `settings.ts`：仿 `PAPER_KEY`（`:24`）加 `SENT_ALIGN_KEY="texlate-sent-align"` + `sentAlign` 信号（默认 true）。
- `Settings.tsx`：开关行；`Toolbar.tsx` 可选 chip（v1 可不做）。

### `web/src/i18n/en.ts` / `zh.ts`

- `settings.sentAlign`、tooltip、`reader.sentAlignJumped` 等 3–4 键。

### `web/src/styles/reader.css`

- `.ens,.zhs{display:inline}`（零样式锚）；`.sa-hot`/`.sa-peer` 用主题变量底色（须兼容 blender 深色——ADR-0020 变量族）；`.sa-flash` 跳转动效。PDF quad 叠层类同名复用。

### `web/src/reader/sanitize.ts`（防御性一行）

- `ADD_ATTR` 补 `"data-sid","data-bead"`（`:36` 同处）——v1 运行时注入不经 sanitizer，此行为 v3 emit 期注 sid 与防回归预备，并配一条 sanitize 回归测试。

### `sync.ts` / `alignment.ts` / `navstack.ts` / `citations.ts`

- **零改动**。bead 跳转走元素级 `jumpToEl`/合成 dest，不触 `pages()` 几何与 PosMap 内部。

## 后端改动

**v1：零。**（B 方案选型结论：前端再切覆盖 emit/repaint/LivePane/重译全部路径；emit 期包 span 反而留盲区并污染 markdown 产物。）

**v2**：`worker/compile.py::_build_zh` 内在 `reconstruct` 后插锚（见 §数据/管线改动）；`xlat/placeholders.py` 哨兵族加 `tl.` 锚名生成/剥离一对函数（~40 行）；`worker/html.py::_emit_html_dom` 不变。

**v3**：`xlat/retry.py` 槽位协议推广 + `worker/html.py::_build_dual_html` 写 `chunks[].sent_marks`；`_emit_html_dom` 可选直出 `data-sid`（届时 sanitize.ts 的 ADD_ATTR 生效）。

**可选项（非本 feature 阻塞项）**：align-edge 白名单可用于 `bindChunkGeom` 的 `els` 过滤（footnote/doomed 锚窃宿主尾导致 fraction 插值偏移——38 锚窃 8395 字符、99 doomed 锚）；影响面是既有 chunk 级 scroll sync，建议独立工单，v1.5 的 DOM→PDF 分位插值精度会间接受益。

## 测试计划

fixture 来源：**必须**从 `~/.texlate/tasks/` 拷真实 dual.json/en.html/zh.html 快照入 fixture 目录（repo 内现存 128 份全是 stub/mock「这是译文」，覆盖为零——选 2–3 篇 85–164 chunk 的小型任务）。

1. **注入不变量**（复用 align-inject 测试面）：wrap 后 `textContent` 字节恒等；DOM census 仅 `+span`；jsdom Selection 六向验证；重复注入幂等（repaint 双跑不双包）；`<a>` 链接全存活。
2. **嵌套/边界回归**：footnote-in-para 场景 `closest` 拒绝（无孤 '。' 幽灵 sid）；RESTRICTED_SPAN_PARENTS 内留裸片不崩；math/code/pre/ltx_note_mark 子树零 sid；support 块（bibitem/figure/table caption）拿 sid 但不进 bead 对位（噪声面断言无害）。
3. **切句器**：zhseg JS 移植对 zhseg.py 逐句 diff（golden 对拍）；en 扁平化 vs RAW 回归（`\n` 不切）；abbrev/dot guard 用例（`Fig. 3`、`3.14`）；join 不变量（拼接==原文）。
4. **对位器**：golden fixtures 断言指标阈值——chunk 全 1:1 率 ≥70%（实测 76.3%）、bead 1:1 占比 ≥85%、抽验正确率 ≥85%；mismatch fixture（zh 多拆）产出 m:n bead 不跨 chunk 渗血。
5. **交互**：委托三事件在四种 pane 组合（DomPane↔DomPane、HtmlPane↔DomPane、LivePane 进行中、DOM→PDF v1.5）下的 e2e——hover 双侧着色、点击跳+`navStacks` 回退成对、增量 paint 后新句即活、开关关闭零残留。
6. **性能闸**：注入 ≤1.5ms/chunk（实测 1.13）；session.mount 分片不阻塞（单 chunk 超时即让帧）；128k span 规模委托附加 ~0ms、hover 中位延迟不劣于现状（~59ms 含帧分发）。
7. **sanitize 回归**：`data-sid`/`data-bead`/`zhs`/`ens` 过 `sanitizeDomHtml` 存活。
8. **PDF（v2）**：dest 普查全 `tl.*` 为 XYZ；两相法则在 twocol fixture 全解；folio 吞锚 leading-gap 闸用例；无 dest 存量 PDF 整体降级不报错。

## 工作量与分期

| 期   | 内容                                              | 改动面                                                                                                                    | 估时              |
| ---- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| v1   | DOM↔DOM 句级悬停高亮 + 点击跳 + 开关              | `sentalign.ts` 新增 ~300 LOC；DomPane/HtmlPane/LivePane/markdown 各 1–3 行钩；ReaderView ~50 行；settings/i18n/CSS ~80 行 | 2–3 天含测试      |
| v1.5 | DOM→PDF 点击跳（PosMap 分位插值 + 合成 XYZ dest） | sentalign +~60 行，PdfPane 零改                                                                                           | 0.5–1 天          |
| v2   | PDF 句锚 + 文本层 quad+PDF→DOM 双向               | 后端 ~80 行（compile.py+placeholders.py）；前端 sentalignPdf ~150 行；存量任务重跑 splice 才生效                          | 3–4 天            |
| v3   | 译文携带句标（⟪S⟫ 槽位推广）+`sent_marks` sidecar | retry/batch/emit/types ~150 行 + prompt/协议改动；打破 ~93.4% 序位天花板                                                  | 2–3 天 + 重译成本 |

依赖：v1 无前置；v1.5 依赖 v1 的 bead 索引；v2 依赖 v1.5 跳转通道；v3 独立可插队（收益是替掉前端重切 + 提准）。

## 风险

1. **句数不等（7.53% chunk，zh>en 占 89.2%）**：对位器以 m:n bead 兜底，交互上永远是组高亮；|Δ|≥3 仅 0.19%。残余风险=用户预期 1:1——可用 hover 时 bead 内句数徽标提示（v1 后评）。
2. **对位漂移**：抽验 87.5%，误差全是 zh 句界滑移；eq-but-derailed 占 6.5%。bead 语义把损伤限制在组内。v3 句标是根治。
3. **多片段 sid（49%）**：任何 `querySelector` 单元素假设即 bug——契约测试钉死 `querySelectorAll`。
4. **Intl `\n` 乱切**：只对扁平化文本切句（en 侧）；回归用例钉 RAW/flat 差异。
5. **嵌套 `[data-chunk]` 吞并**：漏 `closest` 闸则 footnote 宿主句染 ghost sid——已列回归测试。
6. **RESTRICTED_SPAN_PARENTS 裸片**：表/列表内句无 span → 该处悬停无响应（可接受，文档化）；不可为包 span 破坏 phrasing 模型（A 方案 span>table 违规实证）。
7. **support 块噪声 sid**（bibitem/figure caption 内未译 en，43 块）：无害；可选按 kind 门控 hover 源侧。
8. **PDF 类级 pdfview=FitH 降级**：`\hypertarget` 在 pdftex/xelatex 双臂都丢 x → 只用裸原语，Code Review 闸。
9. **存量 PDF 无锚**：仅 31.5% 有 dest，v2 前必须保 chunk 级降级路径。
10. **zh PDF 文本抽取**：缺 cMapUrl/standardFontDataUrl 则 quad 派生失败——PdfPane 加载参数检查列验收。
11. **folio 吞锚**：末锚被页码行吃掉 → leading-gap 闸（>2× median）+ 双页 quad 用例（实测 7/499 跨页对）。
12. **大文档 mount 抖动**：jsdom 下 188KB 文档注入 ~104–131ms——必须走 `forEachSliced` 分片。
13. **fixture 真空**：repo 无真实 dual.json——测试基建第一步是快照合法化（体积 + 隐私：选小任务、脱 task id 亦可）。
14. **sanitize 回归面**：运行时注入不过 DOMPurify，但 v3 emit 直出时被剥光即静默失效——ADD_ATTR 声明 + 测试先行。
15. **zh 侧勿用裸 Intl**：Intl 与 zhseg 虽 97.7% 节点一致，但序位对位的 93.4% 天花板依赖与 `sentence_ends` 同款的 `{}` 深度/abbrev 不对称修正；混用会把 chunk-exact 打回 ~84%。

## v1.6 动效臂落地实录（2026-09-26，`f8a848bb`）

动效三件套已上线（方案 D 平滑滚动经评估否决——与 SyncEngine/navstack 抢滚动主权，负收益）：

- **A press 涟漪**：`anim.press(x,y)` 源点 fixed 扩散环 ~420ms 自清。
- **B land 连线 + 行擦入**：源点→首个视口内行左缘中的三次贝塞尔（pathLength=1 dash 描入渐隐 1.1s）+ 逐行 `.sa-wipe` scaleX 擦入（40ms stagger、≤8 行）；`from=null`（gotoPeer 等非点击跳）只擦不连。
- **C PDF 悬停对位**：pdf 窗格 pointermove → `seqAtPoint` → 对侧经 `pdfHover` 桥锚/带染色。

机制要点（32-agent review `wf_8fc4404c-65f` 加固后形态）：

- `from` 坐标 param 穿线（`animPress` 返回值沿 jumpSeq/jumpSidToPdf/pdfJumpFlash 一路透传给 `animLand`），取代 animFrom 字段+TTL——陈旧源点与异步单槽竞态按构造消除。
- hover 键侧限定 `${side}|${sid}|${bead}`——1:1 bead（87.6%）双侧键串全同，不限定则 en→zh 直迁在 en 侧留死色、zh 侧永不染。
- `peerGen` 代际闸：外源 clearHot（滚动清轨/DOM 悬停扫）把 pdf 侧已备 peer 扫掉后 `cur` 仍持械，须凭代际比对打破 sameSeq early-return 才可重备。
- PdfPane `saTintReq` + `textlayerrendered` 重染——懒渲页 materialize 即补 peer 色；`hoverSeq` 清场按 cls 限定（广播 `sa-peer` 清扫不踩在场 `sa-hot` 轨）。
- 滚动清轨：`{capture:true}` 挂 scroll（scroll 不冒泡，须捕获才捕得到内层 .pdfSlickContainer）；pointermove trailing-edge 节流（pend 存最新坐标、单 timer 窗尾重解 seq）。
- injectChunk 重注入（MO 感知）→ hover∩chunk 命中先 clearHot 再按记忆侧/seq 重备 DOM hover 或 pdf peer。
- `mountedPdf` 同体免重挂——重挂先 detach 会把在场悬停轨扫掉。
- `lineRects` 同行碎片并集（em/a 切开同 sid 的行幅取并）；`land` 内部只清 land 面（`clearLandFx`）不动涟漪——`cancelLand` 是视图销毁口径才全摘（涟漪截没回归即 playwright 验收实捕）。
- reduced-motion 全域降级；全部 fixed+transform/opacity 零重排。

验证：review 确认 20 条 findings——本批修 17、2 条 by-design 跳过（land ≤1.1s 冻结窗滚动取消会连杀着陆连线；PdfPane 组件测试基建缺位）、修复期间另自查捕获 2 条（peerGen 重备、land 截没在飞涟漪）；anim+sentalign 62/62 vitest、全套 931/931（69 文件）、tsc/eslint/vite build 绿、`scripts/sentalign_anim_verify.mjs` playwright 浏览器验收 10/10。

## v1.7 PDF 侧句级落地（2026-09-26）

v1.5 引入的 u 分位块内插值已把落点推进段内（探针实测 u_src=0.66→u_meas=0.49），但 `pdfFlashSeq` 整段 190 叶全闪使观感仍是「段落级」。本版不改后端、不依赖 `tl.*` 句锚即拿到 PDF 侧真句级：dst marked 字形叶文本经 `splitZh`/`splitEn` 重切句 → `u·concatLen` 选句（与 DOM 臂 `sents.find` 同语义）→ 句首叶 `{page,fraction,x}` 作落点 Pos、`pdfFlashEls` 句域叶集闪示（实测 deep click 闪 18 叶/51px≈一句 vs 旧 190 叶/整段）。

- 改动面：`PdfPane` 新增 `seqLeaves`（seqEls→leafEls 下钻）与 `flashEls`（任意叶集闪）两 handle；`sentalign` 新增 `pdfSentAt` 私方法与 `pdfSeqLeaves`/`pdfFlashEls` 两 dep，`pdfJumpFlash` 增 `sent` 参贯穿句级闪选链（预选叶集→跳后重选→行带→整段殿后）；`jumpSeq`/`jumpSidToPdf` 两臂同接——PDF↔PDF 与 DOM→PDF 两路都吃。
- 落点语义：`sent?.pos ?? interpDst ?? seqPos` 三阶梯——dst 页已渲染即句级直锚（无需 est_dst 钳制，文本成比例映射天然收敛于块内）；懒渲页先走旧插值落地、闪选链 160/550ms 双拍重试，命中即封代际（`flashGen` 每次起跳递增，挡窗内连点陈旧闪示）。
- marked 多出现（TOC 重放 + 正文真标同 seq 共存）按 `seqPos` 锚页择组、无锚取裹字最多组；跨页续段、数学长段（一句裹百叶）按选句自然兜底。
- 验证：vitest 54/54（新增 4 例——句级落点、叶缺席殿后、TOC 择组、DOM→PDF 句级）、tsc/eslint/build 绿、`scripts/sentalign_depth_probe.mjs` playwright 深度探针双向实证（en→zh 句闪 31% 覆盖、zh→en 数学长段一句全裹属正确）。

## v1.8 悬停/落定全面升句级 + 落定闪共轨（2026-09-26，`272bc14b`）

v1.7 只把「点击跳」的 dst 闪示升到句叶级——两条悬停轨（源侧 `sa-hot`、对侧 `sa-peer`）与 usages/镜像跳的落定闪仍是整锚染，观感回到段级。本版把三者全部收句：

- **源侧句级 hot**：新增 `pdfSentUnder(side,seq,t)`——指针下叶经 `seqLeafGroup`（v1.7 `pdfSentAt` 的 marked 多现择组逻辑抽出共用，`seqPos` 锚页组优先、无锚取裹字最多组）重切句，命中叶所在句的句域叶集返；`SentAlignDeps.pdfTintEls` 桥到 `PdfPane.tintEls→saTint` 逐叶 `sa-hot`。非叶上/切空/dep 缺席退整锚 `pdfHover` 旧路。`sameEls`（同长 + 同首末 + 首元素仍带 cls）dedup 兜 60ms 节流重算同句——先清再加是两帧闪帧。
- **对侧句级 peer 随手**：`armPdfPeer(side,seq,pos)` 按 pos→`fracInBlock` u 跟手——pdf dst 走 `pdfSentAt` 句叶 `sa-peer`（`pdfPeerSentEls` dedup）、DOM dst 按 `u·concatLen` 取句 `data-sid` 子集（无句料保全块）。**同 seq 每次 move 重算**——原 fresh 早退把 peer 冻在首算句；DOM 写由 dedup 兜住不重标。`pdfHoverPos` 记存位——DOM 对侧重注（injectChunk）后无新 pointermove 也按存位重补同句。
- **落定闪共轨修复**：`mirrorDest` 直调 `origGoTo` 不走 `goToDestination` 包装——`ReaderView.mirrorTo` 成功支补 `dh.flashDest(dest)`；包装支（cite 锚/usages 站跳）同接 `flashDest`。`landingFlash`：落点 Pos→`seqAtPoint` 多 x 采样（dest 常在块间白/栏缝/图区，单点易落空）→ seq 锚叶闪；无 seq 退 `bandElsAt` 行带；懒渲页两路皆空 200ms 步最多重试两拍。
- **`saFlashAt` 新度闸**：`saFlash` 记最近打闪时刻；`landingFlash` 见 400ms 内已有新闪整场免打 + `flashDest` 首拍延 180ms——修「usages/镜像跳的迟到整锚闪把 sentalign 句闪踩回段闪」实机回归（复现测得 54 叶/284px 全 seq 闪）。
- 验证：vitest sentalign 套更新 peer 随 pos 重算语义（dedup 在写层）、全量 961/961；playwright `tmp/inspect-verify/pw_seq_repro.mjs` **14/14**——悬停 hot=18/215 叶 + peer=21 叶、点击跳落定闪 21 叶/15.7px（对照 seq 块 358px）。
