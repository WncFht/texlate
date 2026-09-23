# find-usages（目标 → 全部引用处）实现文档

调研综合自 `tmp/ux-research-20260922/exp/` 下 10 个 fu-* 实验（全部已验证落地），覆盖 dom/html/pdf 三视图。本文档给出文件级实现方案。

**实验 → 结论映射**

| 实验 | 证明的事 |
|---|---|
| fu-anchor-census | en.html 正文锚面：1713 个 `a[href^="#"]`、0 dangling；bib 目标 100% 有入链（992 全在 `.ltx_cite`）、table 86%、fig 58%、eq 21%、sec 正文口径仅 28%（70% 入链来自 TOC nav chrome）、footnote 2%、algo 0 |
| fu-id-conv | LaTeXML id 词表（28 文档 70157 id 零重复）：`S/SS/SSS/Px`=节、`F`=图、`T`=表（`figure.ltx_table`）、`E/Ex/EGx`=公式、`Thm<env>`=定理、`bib.bib<N>`=文献、`algorithm<N>/alg<N>`=算法、`footnote<N>`=脚注；浮动体 100% 带 id、bibitem 0/1439 缺、eq 行 58% 无 id 但外层 `table.ltx_equation` 恒有 |
| fu-context | 源文语境句管线：masked chunk `[[CITE_n]]` 位 → `sentence_ends` 扩句界 → unmask；594 锚 → 442 唯一句（82 句天然服务多锚），严格干净 82.4%、可用口径 88.7%，p50=200 字符；缺陷全枚举（displaymath 邻接 29 为最大类） |
| fu-pdf-scan | PDF 链路注释 → named dest → 页：zh 产物 2185/2185 全解析、en 150/151；`doc.getDestinations()` 全文件返回 `{}`（dest 在 /Names→/Dests 名称树，必须按 annot 逐个解）；整本扫 1.4–1478ms |
| fu-dest-vocab | 282 篇编译产物 322 个 dest 前缀词表：`cite`=bibkey verbatim（16849 链、命中 99.6%）、`section*` 含星号节、`figure/equation/theorem/table` 同族；**29% 文档零 dest、cite dest 仅 59.6% 文档有**、9 篇匿名 hex dest 不可分类 |
| fu-zh-ids | zh 侧 id 存活 92%（S1 echo 完美翻译下）：73 丢失=69 bare inline（`ltx_text` 随 `target.clear()` 整段被译文换掉）+3 嵌套 data-chunk 块（itemize 内 para，译文真丢）+1 protected-token；但 en 侧 93 个锚目标在 zh 全部幸存、holder_mismatch=0、反向零新增 |
| fu-nonref | \ref 族之外的提及召回界：fig/tab 仅 4.0%（literal 3.2%+deictic 0.85%）、全 floats 6.75%；43% 浮动体从未被 \ref；unref'd 但字面提及仅 2%（下限） |
| fu-popover-spike | FigPopover/FigPane/figIndex 全栈参考实现：26/26 vitest + 真实浏览器 e2e；踩出并修复两个真缺陷（Esc 复开、巨 figure 锚 rect 出屏）；索引冷建 86ms/温建 13ms |
| fu-jump | 跳转力学全绿（22/22+13/13）：bibkey→{seq,charOff,enLen} Map 查找 0.4µs（vs querySelector 5.5ms）；Pos.fraction=charOff/enLen 落点最坏 49px（顶落点 1672px、68% 高块落点出屏）；NavStack 往返精确、zh 镜像同 seq 40/40；现状 html 视图可点引用元素=0（76 裸括号文本） |
| fu-bib-reverse | 反向索引充分性终审：composite route 对 10/10 真实文档成立——777/777 CITE token en+zh 双存活、474 个被引 key 全有 ≥1 句、zh 配对 100%、`cite.<key>` 命名空间=bibkey  verbatim、条目文本 474/474 经 chunk\|pdf\|src 三路并集；**但存量 ph 键归属有编号漂移型错绑**（2 档 rederive 0%、1 档原生 ph 前移一位），归属必须锚点/序数对源码核对 |

## 目标

给阅读器加 IDE 式「查找引用处」：对**文献条目 / 图 / 表 / 公式 / 节 / 定理**六类可引用目标，一处唤起其全部正文引用点列表——每条引用点显示语境句（en+zh 配对），点击即跳转到该引用处（闪记+跳回栈+split 对侧镜像）。本质是 ADR-0021「引用锚 → 目标」正向跳转的逆向补全：同一份锚面数据反向建索引。

- **v1（本期）**：dom 视图（en.html/zh.html pane）浮动体+文献的 usages 悬浮卡；html 视图（chunks）cite-ref 标记化 + usages。
- **v2**：pdf 视图 usages（named-dest 反向索引）、emit 侧 zh id 存活修复、服务端语境句预计算 sidecar。
- **不做**：非 \ref 字面/指示词提及召回（召回界仅 ~4%，见风险）、algorithm 浮动体（语料 0 实例）、footnote（1/56 有入链）、跨论文被引（属 citation-landscape 方向）。

## 交互规格

**唤起面**（dom 视图为准，html/pdf 同构映射）：

| 目标 | 唤起手势 | 卡片锚 |
|---|---|---|
| figure/table 浮动体（含无 caption 者——id 覆盖 100%） | hover dwell 150ms / 触屏 tap / 键盘 `:focus-visible`（mount 侧注 `tabindex=0`） | `figcaption` rect 优先，无则 figure 顶缘；**rect 夹入视口**（1900px 浮动体包围盒出屏会渲出 0 可见像素——spike 实测修复项） |
| 文献条目（`li.ltx_bibitem`/`[data-bib-key]`） | ①文献表内 hover/tap 直接出卡；②正文 CiteCard 脚部「N 处引用 →」钮切到 usages 视图；③右键「查找引用」 | bibitem 元素 rect |
| eq/sec/thm | 右键/contextmenu「查找引用」（入链面稀——eq 21%/sec 28%，hover 强入口不值） | 目标元素 rect |
| 正文引用锚 `.ltx_cite`/`.cite-ref` | 右键「该文献的全部引用处」 | 锚 rect |

**卡片**（`role=dialog`，复用 ADR-0021 时序：OPEN_DELAY=150 / CLOSE_DELAY=350 / scrollGrace=600ms / Esc capture 关 / 指针可移入 / 下方不足翻上 / 横向夹视口）：
- head：目标标签（`Figure 1:`/`Table 3:`/`[12]`/`Section 2`）+「N 处引用」计数。
- 句列 `<ol>`：每行 `序号 + 语境句`（截断 ~280 字符——fu-context p90=408/max=1620），en 句主行 + zh 配对句次行（zh_pair 实证 100%）。同句多锚合并一条。
- foot：「跳到目标本身」钮（bib 卡=跳到文献表，float 卡=跳到浮动体）。
- 空态：「正文中没有找到引用句」——43% 浮动体零 \ref 是常态，空态必须是一等设计而非异常。

**句项点击 → 跳转**：scrollTop 写位（dom：`gotoAnchor` 锚元素直跳 / html：`Pos{page:seq, fraction:charOff/enLen}`——packed 块最坏 49px 恒在视口内）→ `cite-flash` 1400ms 闪记 → `navStacks` 压栈（pair 号）→ split 下对侧镜像（dom 臂同 id `gotoAnchor`，zh 落空退同 `data-chunk` seq；html 臂同 seq+fraction）。↩/↪/Backspace/Alt+←→ 全部沿用现机制。

**键盘/a11y**：figure `tabindex=0` 使 Tab 可达（spike 实测首 figure 距文首 35 次 Tab）；触发元素上 Tab 直送卡内首句项；Esc 关卡通路**必须带 `suppressFocusOpenFor` 一次性旗标**——Esc 还焦点给 figure 时浏览器把程序 `focus()` 判为键盘模态→`:focus-visible` 命中→focusin 立刻复开卡片（Chromium+Firefox 双引擎实测复现，spike 缺陷 1）。`focus({preventScroll:true})` 防还焦点滚动复活 hover 路径（缺陷 2 通路）。

## 数据/管线改动

**总原则：v1 零管线改动可用。** 三层数据源全部已就位：

1. **DOM 锚**（dom 视图主源）：`a[href^="#id"]` 扫 pane DOM——census 口径 0 dangling。**必须滤 TOC/nav chrome**：`a.closest("nav, .ltx_toclist, .ltx_NAV, [role='navigation'], .ltx_tabs")` 外的锚才算正文引用（sec 类 70% 入链在 TOC，不滤则计数虚高 3.4 倍）。子图锚（`#S3.F2.sf1` 指向 figure 内 panel）`closest("figure")` 归并宿主；锚自身落在 figure 内（caption 自指）丢弃。目标分类按 fu-id-conv 词表走宿主元素 class（`ltx_figure`/`ltx_table`/`ltx_bibitem`/`ltx_equation`/`ltx_theorem`/`ltx_section` 系），eq 行级无 id 时取最近 `table.ltx_equation` 祖先。
2. **dual.json ph token**（html 视图唯一源 + 全视图的 seq/语境归位键）：`[[CITE_n]]` 在 masked `en` 中的 (seq, charOff) 即引用点，ph 体 `\cite{a,b}` 逗号拆 key（多键拆分实证正确）；`[[BIB_n]]` → bibkey→{seq,charOff,enLen}（bibitem 在语料中恒独占 chunk：122/122 单 bib/chunk、seq 零缺口、zh token 100% 存活）。**存量产物告警**：3/14 任务目实测 ph 键归属错位（编号漂移/前移），客户端构造时须做一致性自检（en 文本 token 序 vs ph 编号序），异常档降级为「有句无键」或按锚点法重导；无 ph 旧档（如 quarantine 179-chunk 档）自动退化纯 DOM 锚路。
3. **PDF named dests**（pdf 视图源，v2）：逐页 `getAnnotations` → Link annot `dest` → `getDestination(name)`+`getPageIndex` 解页，`cite.<bibkey>` 名空间与 bibkey verbatim 全等——反查表天然就是 key→[page,rect] 列表。**`getDestinations()` 批量枚举不可用**（/Names→/Dests 名称树不返）。覆盖天花板：cite dest 59.6% 文档、29% 零 dest——pdf 臂恒为机会型。性能：典型 <100ms，最坏 1478ms（14MB/51页）须 `requestIdleCallback`/分片后台建并缓存。

**语境句两条供给路（均已验证，按视图选用）**：
- DOM 路（dom 视图）：块元素（`p,li,td,th,figcaption,.ltx_p,.ltx_note`）干净文本（剥 `annotation,script,style`）上句界扫描——西文 `.!?` 须跟空白（挡 `3.5`/`Fig.2`）、CJK `。！？` 无空白亦界、`.` 边界回看缩写护栏表（Fig/Figs/Eq/Sec/Table/No/Vol/pp/cf/vs/e.g/i.e/et al/Dr/St/月份/单字母）、标点吞噬尾随闭括号；同块同句多锚合 anchors。
- 源文路（html 视图 + 可选服务端预算）：fu-context 管线——`parse_file`→masked chunk 内 `[[CITE_n]]` 位→`sentence_ends`（生产单源 `xlat/batch.py:327`，缩写豁免同源）左右扩至句界/chunk 硬界→`phText`+`RESIDUE_RULES` 移植版 unmask。严格干净 82.4%/可用 88.7%——UI 截断兜底，过伸最大类是 displaymath 邻接（masked 面 `[[MATH_n]]` 后无终止符，根治须在 masker 期补界标，v2 再议）。

**zh 配对**：双侧同 token 位（777/777）——en 句按 (seq,charOff) 抽取后，zh 句从同 seq chunk 的 zh 文本同 token 位抽（zh 文本 token 在位即句界对称）；dom 侧 zh 句取 zh pane 同 href 锚的句（zh 侧 89 锚同侧全解析）。

## 前端改动（文件级）

**新增**
- `web/src/reader/usages.ts`（~300 行，`figIndex.ts` 泛化移植）：
  - `classifyTarget(el): {kind:"bib"|"fig"|"table"|"eq"|"sec"|"thm", el, id, label}`——id 前缀表 + class 表双判（id 前缀快路，bare `.N` 终段/无 id 元素走 `closest` 宿主）。
  - `buildUsageIndex(root)`：`a[href^="#"]`→解析→滤 chrome→归并宿主→`sentenceAround`→`Map<key, UsageSite[]>`；`UsageSite={text, zhText?, anchors[], block, order, seq?}`。
  - `buildKeySeqMap(dual)` / `buildCiteUsageMap(dual)`：ph `[[BIB_n]]`/`[[CITE_n]]` 扫描（fu-jump/click.mjs 逐字路径）；CITE 体 `\cite{a,b}` 逗号拆、去 `(?:\[.*?\])?` 可选参；产物 `key→{seq,charOff,enLen}` 与 `key→Occurrence[]`。
  - `cardPlacement()` 纯函数直接搬（CARD_W=380、GAP=6、边距 8，与 CiteCard 同口径）。
- `web/src/reader/UsageCard.tsx`（~150 行，`FigPopover.tsx` 移植）：head（label+计数）+ `<ol>` 句项 button（idx+en 句+zh 句 muted 次行）+ foot「跳到目标」+ Esc capture/`onCardEnter/Leave`。
- `web/src/styles/usages.css` 或并入 `cite.css`：`.usage-card*`（FIG_CARD_CSS 移植）+ `.cite-ref`（dotted underline 指示可点）+ `.bib-anchor` + 复用 `.cite-flash`。

**修改**
- `web/src/reader/markdown.ts`：`unmaskLatex` 加 marks 模式（或新导出 `unmaskLatexMarked`）——`CITE`→`<span class="cite-ref" data-cite-keys="a,b">`、 `BIB`→`<span class="bib-anchor" data-bib-key>`（fu-jump `unmaskWithCiteMarks` 已验证：42 ref spans + 40 bib anchors 双侧渲染、13/13 click checks）。**现状 html 视图可点引用元素为 0**——这是 html 臂一切交互的前提改动。
- `web/src/reader/DomPane.tsx`：
  - `load()` 落地完成后 `buildUsageIndex(bodyEl)`（86ms 冷建可同步；大文档可走 `forEachSliced`）+ 全部 `figure`/`table.ltx_float_algorithm` 注 `tabindex=0`。
  - 事件委托扩面：现 `onOver/onClick/onFocusIn` 只进 bibitem 锚 → 新增「锚目标为 float/eq/sec/thm」与「浮动体本体 hover/focus/contextmenu」两条进卡路径，出 UsageCard；bibitem 锚的 CiteCard 脚部加「N 处引用 →」切换态。
  - 移植 spike 三修复：`suppressFocusOpenFor` 旗标、`anchorRect` figcaption+视口夹取、`scrollGraceUntil`。
  - 句项 `onJump` → 现有 `jumpToEl`+`onDestJump` 通路（压栈/镜像/flash 全复用）；zh 侧锚落空回退在 ReaderView 镜像层做（见下）。
- `web/src/reader/HtmlPane.tsx`：unmask 切 marks 模式；委托 `.cite-ref`（hover→CiteCard 走 `citeIndex.lookup` / click→跳 bib seq `Pos{page,fraction}` 压栈）；`[data-bib-key]`/contextmenu→UsageCard（句源=buildCiteUsageMap+chunkSideText 句抽，zh 句同 token 位）。
- `web/src/reader/CiteCard.tsx`：`CiteCardBody` 脚部加可选 `onShowUsages`/`usagesCount` 槽（「N 处引用 →」）。
- `web/src/reader/ReaderView.tsx`：usages 句跳复用 `onDestJump`/`navStacks`/`pair`/`mirrorTo`；`mirrorTo` 的 dest 载荷扩展为 `{anchor?:string, seq?:number}` 复合——dst `gotoAnchor` 失败且有 seq 时退 `jump({page:seq, fraction:0})`（zh `data-chunk` 集与 en 1:1；fu-zh-ids 的 desync 是元素序层面，chunk 序不受影响）。usages 卡状态各 pane 自治，不进 ReaderView。
- `web/src/reader/PdfPane.tsx`（v2）：idle 分片逐页 `getAnnotations` 建 `dest→[{page,rect}]` 反查（缓存随 doc 生命周期）；bib 区 `linkAnnotation` contextmenu / CiteCard「N 处引用」→ 列引用页项，点击走 `origGoTo` 同款 `navChain` 落定+压栈。
- `web/src/reader/PaneSlot.tsx`：无新 props（卡 pane 内自治）。
- `web/src/i18n/{zh,en}.ts`：`usages.title/count/empty/jumpTo/citeThis` + `cite.usagesBtn`。

## 后端改动

**v1 零强制改动**（dom/html 数据面齐备）。建议两项：
1. **`server/worker/html.py::_emit_html_dom` id 存活修复**（独立价值，可插队）：`target.clear()` 前收集后代 `[id]`/`[data-chunk]`——①bare inline id 元素在 `reinsert` 产物中无对应件时，以空壳 `<span id>` 锚补挂（或译文含对应 token 时由 reinsert 保骨架）；②嵌套 `data-chunk` 块（itemize 内 para 实证 3 块）改为「先内后外」回插或跳过内层独立回插——**这 3 块译文当前是真丢**（missed_blocks=3），修复同时救内容又救锚面，zh 镜像命中率 92%→~100%。
2. **可选 usages sidecar/端点**（v2）：emit 期跑 fu-context 管线产 `usages.json`（`{targetKey:[{seq,charOff,sent_en,sent_zh}]}`）经 `files.py` manifest 直出；或 `routers/reader.py` 加 `GET /task/{id}/usages` 懒算。收益：三视图同一句库、大文档免客户端重建、ph 归属可在服务端对 src.tar 做锚点核对（haystack 折空白+左窗 ~30 字符定位最近 `\cite`，实证 19/19 救回）。
3. ph 归属核对若在服务端做：注意 `src` 配对必须按 `src_file` 逐文件序对（全局序配对实测 pos_mismatch=103）；`\citealp{a}; \citealp[opt]\n{b}` 畸形 mega-key 边例要容错。

## 测试计划

- **vitest 单测**（`web/`）：`usages.ts`——句界（缩写表/闭括号吞噬/CJK 无空白/`3.5`/`e.g.` 双点）、同句多锚合并、TOC 滤除、子图归并、`classifyTarget` 前缀表（含 bare `.N`、eq 行→祖先回退）、`cardPlacement` 翻转/夹取；`buildCiteUsageMap` 多键拆分/畸形 key/`[[SL]]` 边界。以真实 `arxiv_html_1706.html` fixture 对拍 spike 已知值（9 figure/14 锚/14 句）。spike 26/26 套件整体移植为基线。
- **spike 回归固化**：fu-jump 22/22 + click 13/13 checks 固化为 `web/scripts/usages_verify.mjs`（playwright，TMPDIR 坑注记见 ADR-0021）；断言 Map 定位 40/40、fraction 落点 ≤49px、NavStack 往返、zh 同 seq 镜像。
- **e2e**：hover figure 出卡→句项点击→落点+闪记+栈深→↩ 回位→zh 镜像同位；Esc 关卡**不复开**（hover+键盘两路×Chromium/Firefox）；触屏 tap 出卡不跳；CiteCard→usages 视图流转；空态渲染；contextmenu 面。
- **语料回归**：索引构建跑 128 dual.json + 10 篇 en.html——断言 0 dangling、bib 覆盖 100%/table≥85%/fig≥55% 区间带、zh 锚目标存活 ≥92%（emit 修复后 ≥99%）。
- **存量兼容**：ph 漂移三档（t_32fce/t_4000988/t_42a5）+无 ph quarantine 档——句列有、键降级或重导、不炸、不产错绑卡。

## 工作量与分期

| 期 | 内容 | 估 |
|---|---|---|
| P0 | dom 视图 usages（fig/table/bib/eq/sec/thm 全类） | ~2.5d：usages.ts 0.5（spike 移植）+ UsageCard 0.5 + DomPane 委托/三修复 1 + i18n/css/测试 0.5 |
| P1 | html 视图 cite-ref marks + usages + fraction 跳 | ~2d：markdown.ts 0.5 + HtmlPane 委托 1 + 测试 0.5 |
| P2 | emit id 存活修复（含嵌套块译文丢失） | ~1d，独立价值可插队 |
| P3 | pdf 视图反查索引 + usages | ~2d：idle 反查 + 卡 + navChain 落定 |
| P4（可选） | usages.json sidecar 或懒算端点 | ~1d |
| P5（可选/倾向裁） | literal/deictic 提及召回 | ~1.5d+精度评估——收益上限 4%，先不做 |

## 风险

1. **zh 侧 id 存活 92%**（fu-zh-ids）：8% 镜像落空面 → seq 兜底为 v1 必修；73 个丢失中 69 是 bare inline（en 侧 93/93 锚目标实证幸存，落空面主要是行内锚）、3 个嵌套 data-chunk 是**真内容丢失**（独立 bug，P2 修）。
2. **存量 ph 键归属漂移**（fu-bib-reverse）：2/14 档 rederive 0% fidelity、1 档原生 ph 整体前移——只信 token 位+ph 键会张冠李戴；须一致性自检+降级/重导，服务端核对臂用锚点法（折空白后 19/19）。
3. **eq/sec/footnote 入链面稀**（census）：eq 21%、sec 正文 28%、footnote 2%——「usages 空」是常态；TOC 锚不滤则 sec 计数虚高 3.4 倍，滤除是硬要求。
4. **PDF 臂覆盖天花板**（dest-vocab）：29% 编译产物零 dest、cite dest 仅 59.6% 文档、9 篇匿名 hex dest 不可分类——pdf usages 恒为机会型入口，UI 不承诺全覆盖；zh 产物侧反查 100% 已实证。
5. **非 \ref 提及召回界**（fu-nonref）：fig/tab 仅 4.0% 提及在 \ref 外、43% 浮动体从未被 \ref——空态高频；literal 扫描上限 +2% 且有外部工作误报面（"Fig. 3 in [12]" 需排），建议 P5 裁掉。
6. **语境句过伸 ~11%**（fu-context）：displaymath 邻接最大类（masked 面不可见）——UI 截断 ~280 字符兜底，88.7% 可用口径为验收线；根治要 masker 期补界标，列入 v2。
7. **弹层时序三坑（spike 已踩出，须逐字移植）**：Esc 还焦点 →`:focus-visible` 复开（suppressFocusOpenFor 旗标）；巨 figure 锚 rect 出屏 → 卡 0 可见像素（figcaption+视口夹取）；开卡后浏览器 focus-scroll → scroll 杀卡（600ms scrollGrace）。
8. **性能**：索引冷建 ~86ms/170-chunk 可同步建，更大文档走 `forEachSliced`；Map 查找 0.4µs vs `querySelector` 5.5ms——禁每 hover 重扫 DOM；PDF 逐页扫最坏 1478ms 须 idle 分片+缓存，pdf.js `getDestinations()` 批量口不可用（返 {}），逐 annot 解。
9. **stub/退化文档**：3/25 arxiv 抓取是转换失败 stub（仅 8 id）、4/286 编译件 InvalidPDF、无 ph 旧档——索引对它们返空是正确行为，空态覆盖；`data-chunk` 合成键 `b{n}` 与真 id 共存，跳转按 data-chunk 序而非 id。
10. **en.html 上游可得性**：arxiv html 406 率（3/13 采样失败）决定 dom 视图可见面——与 usages 无关但影响曝光口径，dom 链本就有降级路径。