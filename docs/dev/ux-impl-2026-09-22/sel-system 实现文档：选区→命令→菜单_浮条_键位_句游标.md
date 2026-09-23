# sel-system 实现文档

> 调研基线：tmp/ux-research-20260922/ 下 9 条 sel-system 实验道（ss-dom-sel / ss-pdf-sel / ss-ctxmenu / ss-floatbar / ss-cmdreg / ss-hotkeys / ss-shadow / ss-menu-content / ss-a11y），全部 `works + confirmed`。本文档把结论折成可落地的实现规格。所有 spike 源码可直接移植，路径随文标注。

## 目标

给阅读器加一套以「选区/光标语境」为中心的交互系统，四个入口共用一份命令注册表：

1. **浮动工具条（FloatBar）**——划词松手后在选区上方出条（复制/翻译/解释等 3-5 个高频动作）。
2. **自定义右键菜单（ContextMenu）**——按右键落点语境（选区/引用锚/公式/chunk 块/pane）出 21 项规格的语境菜单，替代浏览器默认菜单。
3. **统一键位分发器（keymap）+ Esc 层栈**——单 document keydown 取代 ReaderView.tsx:168 的硬编码 if 链与散落各组件的 Esc 监听；顺带修掉实测的 8+3 个现网缺陷（findbar checkbox 上 Esc 死键、edSel+Backspace 双发等）。
4. **句游标模态（a11y）**——`v` 进模态，j/k 逐句、[/] 逐块移动，Enter 选句、t 取对侧译文、c 复制、Esc 退出。把目前 87.2% 键盘不可达的句子变成可达（全文 Tab 模型 p50≈79 击 vs 游标块跳 p50=100/平扫 220，而现状 380/436 句根本到不了）。

非目标：pdf.js 批注编辑器、跨页拖选（上游不支持，见风险）、服务端协同批注。

## 交互规格

### 选区语义（三 pane 统一）

- **DOM 双栏（DomPane=ar5iv HTML，HtmlPane=chunk 流）与 PdfPane（pdf.js textLayer）全部走原生 Selection**——结构面零障碍：全仓 0 个 shadow DOM、0 个 iframe（ss-shadow 静态+运行时普查），`.textLayer` 链上 user-select 全为 auto/text，app 23 个 CSS 无一命中 textLayer 选择属性；PDF 侧**零改动**即可拖选/双击选词/Ctrl+A/copy 事件（ss-pdf-sel 真机 harness 全绿）。
- 选区→chunk 解析用 **coveredChunks**（`exp/ss-dom-sel/coveredChunks.mjs` 移植）：`sel.getRangeAt(0)` 规范化后按锚点区间切片 `[data-chunk]`，O(命中锚数) 而非全扫——163 锚文档 Chrome 2.2µs / Firefox 6µs / jsdom 25µs（全扫对拍 550+800+1000 组 fuzz 零失配）。返回 `data-chunk` 键数组（文档序）。
- **边界规则**：选区终点恰在下一锚首 offset0 时该锚算相交（复制文案用 `trim().length>0` 滤白字）；端点落在无锚区（license 行/页眉残渣，实测 322 字符）向文档序收拢到最近锚；跨 pane 选区对两侧 bodyEl 各跑一遍（单 document，`commonAncestor` 可能是 body）；反向拖拽用 `compareDocumentPosition` 判 anchorAfterFocus（双引擎一致，`sel.direction` 字符串也可用）。
- **键到 seq 的映射**：DomPane 的 `data-chunk` = emit 块 key（`S1.p4`/`b5`/`footnote1` 字符串），HtmlPane 的 `data-chunk` = 整数 seq（HtmlPane.tsx:118 `data-chunk="${seq}"`）。约 31% 的 DOM 锚（bibitem/figure/authors，实测 50/163）没有 chunks 行 → `intSeq` 为 null，重译类命令隐藏、复制类照常。
- **复制文本源**：用 `range.toString()`/`cloneContents().textContent`（1234 字符），不用 `sel.toString()`（1230——折叠换行，丢结构）。
- **PDF 侧已知上限**（全是上游 pdf.js 行为，见风险节）：从链接批注上起拖=0 字符、textLayer 下方死区起拖=0、跨页拖选不延申、findbar 重新查询会塌掉选区（DOM 重建 76→0）。

### FloatBar（划词浮条）

管线（`exp/ss-floatbar/floatbar.mjs` 移植，`createFloatBar`）：`selectionchange` → 拖拽期压制只记 pending（release 模式）/ 非拖拽 40ms 静默 debounce → `pointerup` 或 debounce 到点后 `rAF` 合帧 → **一次** `range.getBoundingClientRect()` → `placeBar` 纯函数 → `translate()` 落位。

- 落点规则：默认选区并集 rect 上方居中（gap 8px）；上放不下翻下；两侧都不够贴空大侧；水平钳 `[8, vw-w-8]`。
- 滚动跟随：document capture 阶段 scroll 监听（pane 内滚动容器不冒泡），每帧重算锚 rect 重放 place——平滑滚动 163 采样 max/mean/p95 误差均 0.08px；锚滚出视口即藏、滚回即显（curRange 留存）；resize 同理重估。
- 条上 `pointerdown`/`mousedown` preventDefault——点钮不收选区。
- 成本：单次评估 0.1–1.8ms（85KB 全选级选区也仅 1.3ms），release 路径松手后 3.4–13ms 出条；26/26 验证断言、80 万 fuzz 零违例。
- 按钮集 = 注册表 `sel.*` 组启用项前 N 个（复制/复制双语/查找/解释）。

### ContextMenu（右键菜单）

组件（`exp/ss-ctxmenu/ContextMenu.tsx` + `useContextMenu` 移植，437 行）：`contextmenu` → `preventDefault` → 开单快照 `{x, y, selection, target}` → `Portal→body` fixed 菜单（pane 内 transform/overflow 不咬 fixed）→ 首帧估宽 220×估高 28px/项防出屏、`onMount` 实测重放同一 place 函数。

- `placeMenu`：光标右下展开，右/下溢出翻到另一侧，仍出界硬钳视口（margin 4px）；`placeSubmenu`：贴父项右缘 -2px 重叠消缝，右溢出翻左侧，顶对齐 -4px。两函数各 2 万 fuzz 零视口违例。
- 子菜单：150ms hover-intent 开 / 300ms 斜移宽限关；DOM 嵌在父 `li` 内（pointerleave 语义白捡——进子孙不算 leave，免三角算法）；ArrowRight 进/ArrowLeft 出，递归三级已验证。
- 关单路径：Esc（**capture + stopImmediatePropagation**，抢先于同节点已注册 bubble 监听）、外部 pointerdown、滚动（capture）、Tab 顺走；关单回焦开单前焦点元素。开单期 document 监听=3 个，关后=0。
- **两个已修缺陷必须随移植保留**：(a) 已处理导航键全部 `stopPropagation`——Solid 委托事件沿祖先链上冒，子菜单内 ArrowDown 否则被根级 onKey 二次处理抢焦点；(b) 垂直换轨（↑↓/Home/End）时 `setSubIdx(-1)`——防 stale-open + aria-expanded 残影。
- **平台级约束**（记录在案）：右键点选区外会在 mousedown 先塌掉选区（原生 Chrome 语义），快照为空 → 依赖 sel 的项禁用——菜单项谓词要同时挂 chunk 语境，不能只挂 `sel`；Esc 早注册的 capture 监听（CiteCard.tsx:62 模式）仍会先跑——**必须先落统一 Esc 层栈再上菜单**（见分期）。
- 菜单皮肤复用 12 个现有 token（--panel/--ink/--shadow-pop 等），暗色 11/12 直接过、只补 1 条；bundle 增量约 21KB（含 solid runtime 摊薄后实际更小）。

### 菜单内容（menu-spec，21 项 / 5 段）

`exp/ss-menu-content/menu-spec.json` 为唯一事实源。每语境菜单非空率 100%（min 2 / max 10 项）：

| 段 | 项 | 谓词要点 |
|---|---|---|
| sel | `sel.copy` 复制 / `sel.copyPair` 复制双语对照 / `sel.find` 文档内查找 / `sel.explain` 解释选段 | `sel.text` 非空；copyPair 要 `sel.inChunk && chunk.counterpartAvail`；explain 需 `caps.assist`（新后端端点） |
| cite | `cite.card` 查看引用条目 / `cite.jump` 跳至目标（动态文案按 targetKind：bib=文献条目 figure=图表 section=小节）/ `cite.copy` 复制条目 / `cite.arxiv` / `cite.doi` / `cite.alphaxiv` | `cite.targetKind=='bib'` + entryText/arxivId/doi 存在性；alphaxiv 走既有 `api.discoverOverview`，未收录回包 `{available:false}` 按 toast 降级 |
| math | `math.copyTex` 复制 TeX / `math.copyMathml` | `math.tex` 取 `alttext` 或 `annotation[encoding=application/x-tex]`（latexml 真标记，dom 语料 142 个 math 100% 有 alttext） |
| chunk | `chunk.copySrc` 复制原文（含 hasNontext 兜底：1/163 空 textContent 容器块）/ `chunk.copyZh` 复制译文 / `chunk.copyPair` 复制双语段 / `chunk.retx` 重译此段 / `chunk.copyTex` 复制 LaTeX 源 / `chunk.copyLink` 复制段链接 | retx：`seq∈pending` 时 **disabled 不 hidden**，且需 `intSeq`（DomPane 需 chunk_id→seq 映射，见管线节）；copyLink 需路由 `seq` 参数（见后端节） |
| pane | `pane.find` 窗格内查找 / `pane.navBack` 跳回 / `pane.navFwd` 前进 | caps.findInPane（现仅 PdfPane 有 openFind）；navBack/navFwd 按跳回栈非空 |

语料普查支撑的覆盖率：dom 侧 cite 锚→bib 解析率 81.7%、死锚 0、math alttext 100%；pdf 侧 40 个 cite dest 全可解析。注意 cite.* 项在今日 html 语料未实际 fire（en.html 的 cite 锚结构走的是 dom pane）——以 dom/pdf 侧为准。

### 键位分发器 + Esc 层栈（ss-hotkeys proposed 形态）

单 `document keydown` 分发器（`exp/ss-hotkeys/keymap.js` 的 `installProposed` 移植），处理顺序每格都是策略点：

1. `Ctrl/Cmd+F` → 活动 pane openFind（先于 inInput——findbar 里再按也要能重聚焦）；
2. findbar 内任意控件上 Esc → 关 findbar + `stopImmediatePropagation`（修 checkbox 聚焦 Esc 死键；连带挡住 window 级 pdf.js unselect 误杀高亮）；
3. `e.isComposing` → 放过（IME 兜底）；
4. inInput（INPUT/TEXTAREA/SELECT/contenteditable）→ 放过；
5. **Esc 层栈一次恰好塌一层**：`editor(pdf.js 选中高亮) > cite > find > menu > info > help > sel`——editor 层只记账不消费（事件穿透给 window 级 pdf.js UIManager 自己做 unselectAll，真单塌一层）；其余层消费时 sIP 截停，window 级监听收不到，一次 Esc 不双塌；
6. help modal 开时除 `?` 外全灭 + sIP（modal 独占管道）；
7. Alt+←→ → navBack/navFwd（pdf.js 不绑 alt 变体）；
8. 其余修饰键全放（不 preventDefault 浏览器键）；
9. `e.repeat` 只放行 `[` `]`（翻页连发），动作键去重；
10. pdf.js 编辑器选中态占有 Backspace/Delete——让位给 window 监听删高亮（修 nav:back+删高亮双发）；
11. 键表：`t`=译选段 `l`=查选段 `c`=复制选区|cite 开卡（谓词链）`s`=同步 `1-4`=模式 `[`/`]`=翻页 `Backspace`=跳回 `?`=help。

实测：66/66 cells + 12/12 层栈剧本全过、单键分发 p95=0.1ms；对照 legacy 抓出 8+3 个现网缺陷（全部变成回归测试），57 行冲突表落盘 `exp/ss-hotkeys/conflict-table.json`。新键位 v/j/k/Enter/t/c 与 21 个焦点上下文零冲突。

### 句游标模态（a11y）

- **哨兵分句（sentseg，`exp/ss-a11y/sentseg.js` 移植）**：在 `[data-chunk]` 块内钉零宽 `<i class="sb" tabindex="-1" role="mark" id="sb-{side}-{seq}-{k}">`——句界可跨内联 `<a>/<math>/<b>`，包元素方案在跨界句上折断，哨兵+Range(marker_i→marker_{i+1}|块尾) 是唯一不毁 DOM 的路。id 必须带侧名（双 pane 克隆下裸 id 双侧撞车，aria-activedescendant 会指到对侧）。句读规则 = `sentence_ends`（xlat/batch.py:327）语义的 DOM 移植：en 用 `.!?`+缩写豁免（尾词含 `.` 或 ≤3 字母不切），zh 用 `。！？；`+后随空白闸；SKIP_TAGS 整树跳过 MATH/SCRIPT/SVG 等。分句质量实测 missed_cuts=0、chunkIdx 单调。
- **游标（cursor，`exp/ss-a11y/cursor.js` 移植）**：pane 聚焦按 `v` 进模态（现键面不占 v）；j/↓ k/↑ 逐句、`]`/l `[`/h 逐块首句（预建 chunkIdx→首句表，空句块如 figure 须扫最近有句块——163 块里实测有无句块）、Home/End 首末句（端点停住报「首/末句已达」，不环绕）；Enter 在 cursor↔selected 翻转——**真 Selection 落在句 Range 上**，视觉=原生高亮零样式债；`t` 取对侧同 sid 句（管线逐句对齐保证 sid 双侧面一致，实测 en/zh 各 436 句）；`c`/`y`/Ctrl+C 复制（无显式选择时游标句即隐含 payload）；Esc 出模态回焦 pane；Tab 不拦截自然出模态（无键盘陷阱，WCAG 2.1.2）；二次进模态记位。
- 两形态均 14/14 e2e 过：**选 roving tabindex**（真焦点漫游，SR 读句语境、focus-scroll 原生）；aria-activedescendant 备选但需给 pane 套复合 role（role=log 属设计债，记录在案不采用）。每动作配 aria-live 宣读；哨兵全 tabindex=-1 → **零新增 tab 停点**。

## 数据/管线改动

**几乎为零——选区系统吃的是既有产物**：

- `data-chunk` 锚 en/zh 双侧已由 `marked_html`（arxiv/html.py:535）同一份标记 DOM 派生，与 chunks 行 `chunk_id` 严格 1:1——不动。
- `⟪S0000⟫` sentinel、`sentence_ends`、splice 全部不动。`chunk.copyTex` v1 = 直抄 chunks 行 `en`（含 sentinel 的近似源，非逐字——菜单 note 已声明「en 文本+ph 反代近似重建」）；v2 若要还原可再暴露 ph 映射。
- **唯一需要新增的映射**：DomPane 的 `data-chunk`（块 key 字符串）→ 整数 `seq`。两条路任选：(a) chunks 端点序列化加 `chunk_id` 字段（store `_PREVIEW_COLS` 已含该列，`tasks.py:180` 加一行即可，**推荐**——零 emit 变更，前端 chunk_id→seq Map 一次建成）；(b) `marked_html` emit 时补 `data-seq`（枚举序要复算 doc_chunks 的 TRANSLATE_CTX 过滤，不如 (a) 干净）。
- zh 侧锚比 en 少 3 个（160 vs 163）——emit 偏斜，语境谓词按本侧 `closest` 取值，天然免疫；不需对齐。
- 句游标的哨兵**纯前端注入**（不污染产物、不重跑 emit、对既有缓存产物即装即用）；zh 侧 sid 对齐依赖管线既有的逐句翻译对应关系，已在 436/436 句产物上实证。

## 前端改动（文件级）

移植源全部在 `tmp/ux-research-20260922/exp/ss-*/`，均已真浏览器+jsdom 双侧验证。

**新增 `web/src/reader/sel/` 子目录**（与 reader 机制同层内聚）：

| 文件 | 来源 | 说明 |
|---|---|---|
| `cmdreg.ts` | ss-cmdreg/cmdreg.ts（253 行） | when 子句 DSL（`key`/`!`/`&&`/`\|\|`/括号/`=='lit'`，编译缓存+`whenKeys` 静态审计防拼写漂移）+ `Registry`（register 即编译，坏 when 启动期爆；`enabled()` 0.6µs、`byKey()` 1.0µs） |
| `context.ts` | ss-cmdreg/context.ts（90 行扩写） | `snapshotCtx(target, sel)` 一次快照产全部谓词键——扩到 menu-spec 全集：`sel{text,inChunk}`、`cite{targetKind,targetExists,entryText,cardFillable,arxivId,doi}`、`math{tex,mathml}`、`chunk{hasEn,hasZh,hasNontext,zhUntranslated,counterpartAvail,intSeq,hasPh}`、`view`、`caps{assist,retx,findInPane,linkScheme,discover,navBack,navFwd}`、`inInput`、`paneSide`；谓词键 ⊆ 产出键由 whenKeys 审计保证 |
| `commands.ts` | ss-cmdreg/commands.ts + menu-spec.json | 21 项命令表：title 换 i18n key、run 接真身（clipboard/navBack/gotoAnchor/api.retranslateChunk/api.discoverOverview/FindBar/assist） |
| `entries.ts` | ss-cmdreg/entries/*.ts | 三入口同构消费：`menuItemsFor`（enabled→CtxItem[]+组间 sep）、`chordOf`+`byKey`、`paletteItems`（commandScore 模糊排序——vendored `command-score.ts` 副本已在 exp 根） |
| `coveredChunks.ts` | ss-dom-sel/coveredChunks.mjs（78 行） | `makeChunkResolver(bodyEl)` 工厂，契约与边界规则见交互规格 |
| `ContextMenu.tsx` | ss-ctxmenu/ContextMenu.tsx（437 行，含两处已修缺陷补丁） | 默认导出组件 + `useContextMenu(build)` 钩子；`placeMenu`/`placeSubmenu` 导出供 fuzz 测试 |
| `FloatBar.tsx` + `floatbar.ts` | ss-floatbar/floatbar.mjs（305 行） | `placeBar` 纯函数 + Solid 化控制器（Portal→body 固定壳、组件根作 bar 元素传入）；**补三处对抗坑**：ResizeObserver/重渲染后 refresh、pointercancel 解 stuck suppression、live 模式可关 |
| `keymap.ts` | ss-hotkeys/keymap.js proposed 支 | `attachReaderKeys(hooks)` 单分发器 + `ESC_ORDER` 层栈注册面（各浮层 register/unregister 替代自有 Esc 监听） |
| `sentseg.ts` | ss-a11y/sentseg.js（161 行） | `segmentDoc(root, side)` → sents[]；注入时机=DomPane 分片 innerHTML 后 / HtmlPane render 后 |
| `cursor.ts` | ss-a11y/cursor.js（246 行，roving 形态） | `makeCursor({pane, body, sents, otherSents, live})`；接入 keymap 层栈（cursor 模态层在 help 之下、sel 之上） |
| `web/src/styles/sel.css` | ss-ctxmenu/ctxmenu.css + 新写 | `.ctx-menu/.ctx-item/.ctx-sep/.ctx-sub`（token 复用）、`.floatbar`、`.sb` 哨兵（零宽但可被 .cur/.sel 高亮——outline/marker 伪元素）、`.pane.cursor-on` 态 |
| 测试文件×6 | 各 exp 测试移植 | 见测试计划 |

**修改既有文件**：

- `web/src/reader/ReaderView.tsx`：删 :167-242 的 `onKey` if 链 → `attachReaderKeys`；组件层挂 `useContextMenu`（挂点是 panes 容器 `on:contextmenu`——`e.target` 进 snapshotCtx 分语境）；挂载 `<FloatBar>`；help 浮层加 v/j/k/t/c 条目；`caps` 由 props/任务态装配传入 commands。
- `web/src/reader/DomPane.tsx`：handle 暴露 `bodyEl()` + `chunkSeqOf(dataChunk)`（用 chunks 端点 chunk_id 建 Map）；分片 innerHTML 落地后调 sentseg 注入（懒注入：v 首按时才 segmentDoc 亦可，436 句成本可忽略）；可选补 `openFind`（chunk pane 目前无 FindBar——`pane.find`/`sel.find` 在 dom 侧要达需先给 ChunkPaneHandle 加 find 能力，否则 caps.findInPane=false 自然隐藏，**P3 再做**）。
- `web/src/reader/HtmlPane.tsx`：同上（`data-chunk` 本就是 seq，Map 退化为恒等）。
- `web/src/reader/PdfPane.tsx`：viewer 容器挂 `on:contextmenu`；pdf.js 编辑器态接 Esc 层栈 `editor` 层（`slick.eventBus` 的 `editingstateschanged` → `hasSelectedEditor` + `store.annotationEditorMode`）；**textLayer 选择零改动**（已实证）。
- `web/src/reader/CiteCard.tsx`：删 :55-64 自有 capture Esc → 注册进层栈 `cite` 层（否则新菜单的 capture Esc 与它谁先谁后不可控，双塌）。
- `web/src/reader/FindBar.tsx`：:94-96 输入框 Esc 逻辑收编进层栈 `find` 层（修 checkbox Esc 死键；保留 Enter 重查）。
- `web/src/components/menuNav.ts`：`bindMenuDismiss` 的 Esc 分支改走层栈 `menu`/`info` 层注册（签名兼容：内部改实现，调用点不动）。
- `web/src/reader/DocInfo.tsx`：同上（info 层）。
- `web/src/App.tsx`：`parseHash` 支持 `#/reader/:id?seq=N`（或 `#/reader/:id/chunk/N`），Reader 消费 → 滚动到 chunk 并闪高亮——`chunk.copyLink` 落地参数。
- `web/src/api/types.ts` + `rest.ts`：`Chunk` 加 `chunk_id?: string`；P3 加 `api.assist(taskId, text)`。
- `web/src/i18n/zh.ts` + `en.ts`：新增 `menu.*`（21 项×2 语）+ `cursor.*` 宣读串 + help 条目；两文件 key-for-key 镜像（既有 parity 测试会守）。
- `web/src/pages/Reader.tsx`：装配 caps（retx 权限、assist 可用性、navBack/navFwd 栈态）+ 注入命令 run 依赖（taskId、handles）。
- `web/src/reader/citations.ts`/`CiteCard.tsx`：cite 语境字段（entryText/cardFillable/arxivId/doi）经 RefMeta/citeIndex 既有面供给 snapshotCtx。

## 后端改动

最小化，两处：

1. `src/texlate/server/routers/tasks.py:180` chunks 端点序列化加 `"chunk_id": r["chunk_id"]`——一行进 `_PREVIEW_COLS` 已选字段的暴露，DomPane 的 key→seq 映射数据源。
2. **P3**：`POST /api/task/{task_id}/assist`（body `{text, ctx?: {seq?, side?}}` → `{text}` 解释结果）——`sel.explain`/`math.explainFormula` 的后端臂；走既有 BYOK tenant（sha256(api_key)）+ LLM 网关串行域，复用 retranslate 的入队/配额模式（worker/retranslate.py 为模板）。未上线时 `caps.assist=false`，菜单项谓词自然隐藏，前端零分叉。

其余不变：emit（data-chunk 双侧已在）、splice、fixloop、`/api/task/{id}/chunk/{seq}/retranslate`（retx 直接用）、`/api/refs/lookup`、`/api/discover/overview`（alphaxiv 项直接用）、路由（hash 路由纯前端）。

## 测试计划

**单测（vitest + jsdom，移植既有套件）**：

- `sel.cmdreg.test.ts`：60 例（42 主 + 18 对抗）——when 编译/求值/审计、三入口同构、谓词叠加非互斥、坏 when 注册期爆。
- `sel.ctxmenu.test.tsx`：27 例——placeMenu/placeSubmenu 不变式（各 2 万 fuzz 移植或抽样 5 千）、esc/外点/滚动关单、子菜单节拍、roving-bubble 与 stale-sub-on-rove 两个回归锁定。
- `sel.coveredChunks.test.ts`：800 组 fuzz 对拍 `intersectsNode` 全扫 oracle + 7 个 directed（跨 3 块/反向/嵌套 footnote/无锚区端点/offset0 白字尾）。
- `sel.keymap.test.ts`：66-cell 上下文×键位矩阵 + 12 层栈剧本 + 17 对抗场景（legacy 8+3 缺陷转回归：fbCheck Esc、stale findbar、edSel+Backspace、help 下穿透、跨子系统双塌等）。
- `sel.floatbar.test.ts`：placeBar fuzz（抽样）+ 状态机（拖拽压制/塌缩/出屏/回显）。
- `sel.sentseg.test.ts`：分句质量（missed_cuts=0、空句、chunkIdx 单调、zh CJK 句读、id 带侧名不撞车）。
- `sel.cursor.test.ts`：14 个 e2e 剧本的 jsdom 版（复制文本与 Range 精确相等、t 换侧、Esc/Tab 出模态、重入记位、零新 tab 停点）。

**真浏览器（Playwright，Chromium + Firefox；WebKit 未测——缺系统依赖，记录为缺口）**：

- 真鼠标拖选→coveredChunks→seq 断言（fixture en.html：跨 3 段 = seqs [9,10,11,12]；反向拖拽）；dblclick/tripleclick；select-all 命中 163/160 锚。
- FloatBar 26 项 verify 清单移植（滚动跟随逐帧误差、翻转、钳位、release 出条时延 <50ms）。
- ContextMenu 17 项真 Chrome 检查移植（71ms 开单延迟、子菜单 -2px 贴边、暗色 token swap 零补规则）。
- PDF 侧零改动回归审计（zeroDiffAudit：computed user-select/PE 全链 + app CSS 命中规则=0）防未来样式回归。
- IME 组合期不抢键（isComposing 早退）、`caretRangeFromPoint`/`caretPositionFromPoint` 路径只走真浏览器（jsdom 没有这两个 API——测试分流）。

**集成**：retx 菜单项 → `POST /api/task/{id}/chunk/{seq}/retranslate` → SSE 回刷 chunk 状态（pending 期项 disabled）；cite.card → CiteCard 既有面；chunk.copyLink → hash 落地 → 重开定位闪高亮；assist 端点 BYOK 往返。

**a11y 回归**：Tab 全走查停点数不变（哨兵全 -1）、aria-live 每动作宣读、axe 静态面、WCAG 2.1.2 无键盘陷阱。

## 工作量与分期

移植为主、新写为辅——源码合计约 2000 行可直接搬，测试约 1300 行：

| 期 | 内容 | 估时 |
|---|---|---|
| **P0 基座** | cmdreg + context + commands 骨架 + **统一 keymap/Esc 层栈**（CiteCard/FindBar/menuNav/DocInfo 四处 Esc 收编）+ 8 个 legacy 缺陷修复 | 2–3 天 |
| **P1 主面** | coveredChunks + sel.copy/copyPair + ContextMenu + FloatBar + menu-spec 中不依赖新后端的 18 项 + i18n + 样式 | 3–4 天 |
| **P2 游标** | sentseg + cursor（roving）+ aria-live + help 文档化 | 2 天 |
| **P3 长尾** | assist 端点 + sel.explain/math.explainFormula + `?seq=` 路由 + chunk.copyLink + chunk pane 的 openFind（caps.findInPane 补全）+ palette 入口（ctrl+k，注册表已备） | 2–3 天 |

合计约 9–12 个工作日。**顺序约束**：Esc 层栈（P0）必须先于 ContextMenu 落地——否则 ctxmenu 已记录的「早注册 capture Esc 双塌」约束会成真缺陷。

## 风险

1. **FloatBar 非滚动布局漂移**（对抗实测）：pane 分栏拖动 margin 变化、DomPane 渐进渲染在锚点上方插入 chunk，都不发 scroll 事件 → 条滞留旧位（实测漂移 200/480px）。对策：ResizeObserver 监听 pane/body + chunk 渲染完成后 `refresh()`；`pointercancel` 解 stuck suppression（实测窗口期内条假可见）。
2. **Esc 双塌/抢塌**：现状 CiteCard capture Esc + FindBar sIP + ReaderView bubble + bindMenuDismiss 四家并存——必须原子迁移到层栈，半迁移态比现状更坏。迁移后 pdf.js window 级 unselect 语义要靠「editor 层只记账不消费」保住。
3. **PDF 上游限制（不修，只记录）**：链接批注上起拖=0 字符（annotationLayer section 吃 pointerdown）；跨页拖选不延申（textLayer 按页）；findbar 重查塌选区（上游 DOM 重建）；页缘死区起拖=0。均属 pdf.js 契约，文档化为 known limitation；`chunk.copyLink` 在 pdf pane 右键落点上不提供 seq 精度。
4. **右键塌选区**：原生行为——选区外右键先 collapse 再 contextmenu，快照为空。菜单项谓词必须同时挂 chunk/cite/math 语境（menu-spec 已按此设计），不能 sel-only。
5. **Solid 委托事件**：菜单内导航键必须全部 stopPropagation（cancelBubble 截断委托上冒）——已修缺陷模式在移植时逐字保留，加注释防回退。
6. **zh 锚缺失/emit 偏斜**（163 vs 160）：双侧语境各自自足，但任何「假定双侧锚一一对应」的代码（如对侧同 sid 句取 Range）要有 miss 兜底（cursor 的 translate 已报「no aligned sentence」）。
7. **chunk.retx 的 seq 依赖**：DomPane `data-chunk` 是块 key 非 seq——chunks 端点 `chunk_id` 字段未落地前该项在 dom 侧恒 hidden（谓词 `intSeq` 天然兜底，不会错触发）；约 31% 锚本就无 chunk 行。
8. **sentseg 与 sanitize 序**：哨兵必须在 DOMPurify/innerHTML 落地之后注入，且若产物 HTML 重渲染需重钉（挂 DomPane 分片回调）；哨兵不进选择文本（零宽元素）但会进 `cloneContents`——copyPair 等用 `range.toString()` 不受影响，导出类路径要确认。
9. **jsdom 盲区**：`caretRangeFromPoint`/`caretPositionFromPoint`/`elementFromPoint` jsdom 没有——命中测试类逻辑（右键点→元素）在 jsdom 只能用 e.target 直给，真机路径靠 Playwright 覆盖。
10. **assist 端点成本**：sel.explain 走 LLM——须尊重 BYOK/配额语义，P3 前菜单项谓词隐藏，不留半吊子入口。
11. **WebKit 未验**：全链路（coveredChunks/floatbar/ctxmenu）只用标准 Selection/Range/CSSOM API，预期可工作，但实测缺口记录在案，发布说明标注 Chrome/Firefox 保证面。
