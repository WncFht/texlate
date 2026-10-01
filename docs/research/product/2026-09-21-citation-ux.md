# 引用跳转/跳回与文献悬浮卡片生态调研

> **状态**：**已落地 v1 + review 加固（2026-09-21）**——同锚双语义 + 跳回栈 + 三路兜底+S2 代理全实现，裁决见 ADR-0021；56-agent 对抗 review 确认项已全修（navChain 串行/死链预检/samePos 幻影栈/FitH 型 dest/焦点三段路/pendingMirror 重试等，明细在 ADR 现状节）；验证 `web/scripts/cite_verify.mjs` 16/16 PASS。M3 refs.json 产物未做（懒 dest 抽取同覆盖）。
> **方法**：126 subagent workflow（52 产品侦察 + 40 机制深挖 + 30 实现车道 + 4 综合），原始结构化产出存 `citation-ux-2026-09-21/raw.json`（1.2MB，survey/deep/mech 三分桶全量）。
> **日期**：2026-09-21

## 0. 结论速览（设计裁决建议）

两个需求（跳转 + 跳回、引用悬浮卡）**同锚双语义**一次解决——抄 Zotero：同一 `[n]` 锚点上 **hover=预览卡、click=真跳文献表**，跳前自动压栈，浮动「↩」钮或 Backspace/Alt+← 回跳。悬浮卡本身消灭了大部分跳转需求（Distill/arXiv Vanity 哲学：不跳即无需跳回），跳回栈只兜真跳的场景。

分层落地：

| 层           | 内容                                                                                                                   | 成本       |
| ------------ | ---------------------------------------------------------------------------------------------------------------------- | ---------- |
| M1 跳回栈    | 包 `linkService.goToDestination` 单点劫持 + 复用 `capturePos/jumpTo`（sync.ts:62-105）；每 pane 一栈；仅跳转类动作入栈 | 小，纯前端 |
| M2 L0 悬浮卡 | 本地 bib 串出卡：eprint 链扫 dual.json `ph` 的 `[[BIB_n]]`→`\bibitem`；html 链克隆 `li.ltx_bibitem`；0ms/0 网络        | 中，纯前端 |
| M3 refs.json | worker `_build_dual` 旁从 `.bbl`/thebibliography 抽 key→条目表，登记为任务产物（补 ph 缺位）                           | 中，server |
| L2 远端增强  | S2 `/paper/batch` 批量解析 title/authors/tldr/citationCount，走自家代理+TTL+负缓存，卡字段缺位静默隐藏                 | 大，可后做 |

**三条铁律**：①跳回栈绝不接 pdf.js `PDFHistory`（写真 window.history + `#nameddest` hash → `App.tsx:48` hash 路由兜底跳 home，活 bug；pdf.js 官方 `isViewerEmbedded` 与 Zotero 均主动禁用）；②拦跳转唯一拦截点是 patch `goToDestination`——`preventDefault/stopPropagation` 拦不住 onclick 属性处理器；③浏览器绝不按 hover 直连 S2/OpenAlex——免 key 池 429 是常态，必须服务端代理 + 负缓存。

## 1. 跳转语义三派（产品面分类）

- **原位浮卡派（零位移）**：IEEE Xplore 对 `ref-type="bibr"` 永不滚动就地弹卡；Apple Books 靠 `epub:type="noteref"` 语义决定 popover 还是 jump；Distill.pub / arXiv Vanity(ar5iv) 刻意消灭「跳到文献表」——`<d-cite>` 的 `.citation-number` 明确 `cursor:default` 无 click handler。
- **双语义派**：Zotero 同一 overlay hover=预览卡 click=跳文献表；Semantic Scholar 全端 click=锚定卡；sioyek 左键=跳、右键=overview、中键=smart jump。
- **纯跳转派**：pdf.js 原生 `goToDestination→scrollPageIntoView`，Skim/Okular/Zathura 同构。

## 2. 跳回机制四模式

- **自研位置栈（主流）**：包 `goToDestination` 单点，跳前 push `capturePos{page,fraction}`（zoom 无关），返回钮 pop。alphaXiv 实证：jotai `scrollHistory`+`showBackButton`+`backButtonDirection('up'/'down')`（返回钮带方向提示，值得抄）。
- **寄生 window.history**：pdf.js `PDFHistory` 用 pushState `{fingerprint,uid,dest}`+popstate 恢复——SPA 毒药（见铁律①）；Research Rabbit 更极端把步迹编进 URL `/search/:sid/:step` 可深链。
- **不跳即无需跳回**：浮卡派的最优解。
- **与既有跳回钮去重**：texlate 现有「跳回对照位置」是双侧 mapper 偏差>500px 的漂移校正钮（`updateDrift`/JUMPBACK_PX=500），**不是导航历史**——引用跳后两钮会同框，须去重（导航栈优先，程序跳转时抑 drift）。

## 3. 悬浮卡片

### 3.1 内容分档（按成本）

- **L0 本地 bib 串**（0ms/0 网络，texlate 天然适配）：eprint 链 dual.json `ph` 的 `[[BIB_n]]`→`\bibitem` 原文，`braceGroups()`/`phText()` 现成（markdown.ts:143-181）；html 链克隆 `li.ltx_bibitem` 节点（PLOS/ACM 同款，零解析格式全保真）。BIB 域 zh=src passthrough → 卡只出英文条目，别指望中文。
- **L1 +行动链接**：条目内正则提 arXiv ID/DOI（year∈91..今年 + month∈01..12 硬约束防 `\d{4}.\d{4}` 误报），给「在 texlate 打开」/Scholar lookup。
- **L2 远端增强**：文档打开即 `POST /paper/batch`（≤500 ids）批拉 title/authors/year/venue/citationCount/tldr 建 bibkey→元数据表（S2 scholarphi 同款「打开即批拉、hover 零等待」）。TLDR 仅 `/paper` 与 `/batch` 有，`/references` 子资源无此字段。

### 3.2 交互语义（工业常量）

- **时序（Wikipedia）**：150ms dwell 才开卡、300–500ms 宽限才关；同锚复悬复用 token 不重新取数；开卡后 ~200ms 再绑卡上事件防指针抖动。
- **可达性（WCAG 1.4.13 硬约束）**：Esc 可关、指针可从锚移入卡（容器整体 mouseleave 或安全多边形）、**禁止自动超时关**；`focusin` 开卡是键盘合规必需；pdf.js `.linkAnnotation>a` 是无文本空元素——须注入 `aria-label` 否则读屏只报「link」。
- **定位**：floating-ui；跨行引用链接是单 section+clip-path，须遍历 `getClientRects` 取最近边而非 bbox。
- **触屏**：tap=出卡（Kindle/Apple Books/S2 统一）；tap 时 mouseover 先于 click 且不可 preventDefault——hover 预览必须按 `pointerType`/dwell 门控。

### 3.3 生命周期陷阱（实测）

- pdf.js `PDFPageViewBuffer` LRU cap=10，逐出页销毁 annotationLayer → 开着的卡变死锚：`updateviewarea` tick 查 `anchor.isConnected`，`pagesdestroy`/`scalechanging` 直接收卡。
- 译文 pane innerHTML 分片重渲拔锚 → rev-token 在 fetch/渲染前后双校。
- `.textLayer.selecting` 下链接 `pointer-events:none`——选中态天然不触发 hover，无冲突。

## 4. 数据供给（卡片内容从哪来）

**本地三路兜底**（缺一即降级为「只有跳转没有卡」）：

1. **dual.json ph 扫描**（eprint 链主路）：`chunks[].ph` 里 `[[BIB_n]]`→`\bibitem[label]{key}`，条目正文=同 chunk `en` 中该 token 至下一 BIB token 子串；`[[CITE_n]]`→`\cite{keys}`；BIB 出现序=[N] 编号。易错点：`\bibliography{x}` 也产 `[[BIB_n]]` 但是占位调用，按 ph 值 `\bibitem` 前缀过滤。
2. **服务端 .bbl/.tex 抽取臂**（补 ph 缺位）：v1 dual 有 token 无 ph、`\bibliography{}`+.bbl 链 bibitem 不进 surface、arxiv_html 链结构上永无 ph（`_build_dual_html` 不挂）。`textutil/cite.py` 的 `BIBITEM_KEY_RE`/`CITE_FAMILY_RE` 现成；产物 `refs.json` 登记三连（KIND_URL/_MEDIA/`_register`）。`src/` 在非 done 终态被 slim——**必须管线内抽取落产物，不能请求时回扫**。
3. **DOM 兜底**（html 链）：克隆 `li#bib.bibN.ltx_bibitem`；dup-id 场景 en/zh 同文档时 document 级查找恒命中 en pane，clone 须剥 id。

**免 key API 实况**（2026-09-21 实测）：

- **OpenAlex**：已转积分计费——单实体 GET `$0` 无限（select 字段随意），匿名预算按出口 IP $0.10/天，共享出口整天 429；ids 无 arxiv 键。
- **S2 graph/v1**：无 key 池 429 常态；`GET /paper/{id}/references?fields=...,contexts&limit=1000` 一次解整表 + 引用语境句；`POST /paper/batch` ≤500 ids。
- **Crossref**：公共池 5req/s，mailto 进 polite 池；`query.bibliographic` 引文串→候选 DOI；arXiv DOI（10.48550/_）属 DataCite 走不通，10.5555/_ 伪 DOI 无解。
- **arXiv API**：`fetch_metadata_batch` 现成（≤200 ids/批）。
- **Unpaywall/OA**：唯 arxiv.org CORS `*` 可嵌 pdf.js；其余只能外链。

## 5. texlate 落地面（本仓侦察结论）

- **劫持点**：`slick.linkService.goToDestination` 包装——所有内链（cite 锚/大纲/named dest）唯一漏斗；capture 必须在首个 await 前同步做。更广漏斗 wrap `viewer.scrollPageIntoView` 可含 goToPage/缩略图。DOM 备选：`viewer.container` capture-phase click 过滤 `closest('.linkAnnotation')`，先于 pdf.js onclick 触发——与悬浮卡共用同一委托。
- **引用识别**：named-dest 前缀法精度≈100%（hyperref `cite.<bibkey>`，bench/corpus/2505.10468 实证 466 个）；无 hyperref 论文走 `textlayerrendered` 扫 `[n]` 正则注入推断链接（勿抄 Autolinker `_convertMatches` 索引空间 bug——join("\n") 匹配 index 喂给 join("") 转换器）。
- **缩放重置**：pdfslick `ignoreDestinationZoom:false` 写死 → FitH/FitR 型 dest 强改 page-width（cite 锚全为 XYZ-null 不受影响，section 锚中招）；镜像路径临时置 `ls._ignoreDestinationZoom=true`。
- **双栏镜像**：`cite.*` dest 在两侧同名 → `engine.navMute()`（新增）先于一切 jump 抑回声；dst 三级回退 `getDestination`→`pairsIndex.get(name)`→插值。建议「任何命名 dest 跳转都镜像对栏」。
- **DomPane/HTML 视图**：`a[href^="#"]` 必须 preventDefault（hash 路由活 bug）+ `CSS.escape`（`bib.bib1`/`S3.E1` 含点）；`[data-chunk]` 可二通道走 `handle.gotoPage`。
- **server 侧**：`refs.json` 产物 + `routers/refs.py` 代理叶（`GET /api/refs/arxiv/{id}`、`/doi/{doi}`）；httpx AsyncClient 必须照抄 discover.py 的 loop 键 `_clients` 表+`_aclose_clients` lifespan 钩（跨 loop 复用炸 "attached to a different loop"）。
- **引用语境句**（scite 式，可选增强）：两遍法 buildCitationIndex——pass1 扫 `[[BIB_n]]` 建 bibMap、pass2 扫 `[[CITE_n]]` 建 mentions[]+sentRange；盲区 CHUNK_MIN=20 短句不进 chunks、`\nocite` 须按命令名剔除。

## 6. 值得逐字抄的对象（深挖档案要点）

- **sioyek**：portal=持久引用锚（{srcPos,dstPos,dstDocVersion} 存 sqlite 按 checksum）；索引三层（行首 `[n]` 目标索引/行首 generic 正则/equation+ 前字距）；`[124,253,432]` 逗号分段状态机；history 的「回跳瞬间把当前活态回写 index+1」语义精确到回跳那刻；`[预览 i/n]` 候选循环是召回误检的低成本兜底——**抄这个 UX 比调正则划算**。缺陷勿抄：reference_indices 是 map 同号覆盖（改 multimap）、`[3-9]` dash 区间未解析。
- **Semantic Scholar Reader**：三代实现全逆向（scholarphi 开源可抄 + 生产 bundle）；`api/1/paper/{id}` 内部端点匿名可调；文档打开即批拉全文献表成 map。
- **Wikipedia PagePreviews**：Redux store+thunk；document 级委托 mouseover→linkDwell；150/300ms 常量；`isUserDwelling` token；Cite 的 referencePreviews 以插件复用同一状态机——悬浮卡框架化先例。
- **Zotero PDF reader**：hover=卡 click=跳双语义一锚两吃；9.0 启发式管线/master SDT 投影两代全量。
- **Distill.pub**：`<d-cite>`+`<d-hover-box>` shadow DOM；v1 全局单例 liveBoxes 互斥；bibtex script 标签内嵌文献表——消灭跳转的极端样本。
- **alphaXiv**：jotai scrollHistory+ 方向提示返回钮；`GET /paper/{id}/references` 服务端解析（自建索引非 OpenAlex/S2）。
- **Google Scholar PDF Reader 扩展**：三层 postMessage 架构 + 客户端多语言文档分析器，解析所读 PDF 参考文献条目→匹配 Scholar 库。
- **IEEE Xplore**：bibr 永不滚动就地弹卡 + 引用抽屉面板 + 上下文回链——「浮卡 vs 侧栏」双形态先例。
- **NotebookLM**：citation chips 跳源段落（TailwindDoc 文档模型+inlineObjectLocations 锚点）。
- **BabelDOC/PDFMathTranslate**：引用功能为零且管线主动破坏链接——直接竞品在此维度空白，是我们的差异点。

## 7. 产品矩阵（52 车道，relevance 0-3）

| rel | 产品                                                                                                                            | 跳/回/卡 | 数据源要点                             |
| --- | ------------------------------------------------------------------------------------------------------------------------------- | -------- | -------------------------------------- |
| 3   | Distill.pub                                                                                                                     | —/—/卡   | 文章自带 bibtex script 标签            |
| 3   | arXiv Vanity                                                                                                                    | 跳/—/卡  | 文档 DOM bibitem 克隆                  |
| 3   | Logseq                                                                                                                          | 跳/回/卡 | 本地 db-hooks page-preview-source      |
| 3   | Semantic Scholar Reader                                                                                                         | 跳/—/卡  | S2 自建图谱 + 内部 api/1               |
| 3   | Google Scholar PDF Reader                                                                                                       | 跳/回/卡 | 自建索引，客户端解析 PDF 文献表        |
| 3   | Wikipedia PagePreviews                                                                                                          | 跳/回/卡 | RESTBase /page/summary + 本地 ref 文本 |
| 3   | Nature.com                                                                                                                      | 跳/回/—  | 页内 DOM li.c-article-reference        |
| 3   | sioyek                                                                                                                          | 跳/回/卡 | 纯本地 MuPDF 三索引+fatcat 检索        |
| 3   | Obsidian                                                                                                                        | 跳/回/卡 | 本地 vault+metadata cache              |
| 3   | ReadCube Papers                                                                                                                 | 跳/—/卡  | 出版商直供引用元数据                   |
| 3   | PubMed Central                                                                                                                  | 跳/回/卡 | JATS li#CRn SSR                        |
| 3   | SpringerLink                                                                                                                    | 跳/—/卡  | SSR 内嵌文献表                         |
| 3   | Firefox pdf.js                                                                                                                  | 跳/回/卡 | annotation 字典+PDFHistory             |
| 3   | VS Code                                                                                                                         | 跳/回/卡 | LSP hover 聚合 + 三栈导航              |
| 3   | GNOME Papers/Evince                                                                                                             | 跳/回/卡 | 本地文档裁剪渲染                       |
| 3   | Apple Books/Margin                                                                                                              | 跳/回/卡 | EPUB aside/PDF link annot              |
| 3   | Skim                                                                                                                            | 跳/回/卡 | PDFKit 离屏渲染目标页区域              |
| 3   | alphaXiv                                                                                                                        | 跳/回/卡 | 自建索引 GET /paper/{id}/references    |
| 3   | Zotero PDF reader                                                                                                               | 跳/回/卡 | 本地 PDF 文本层 worker 解析            |
| 2   | Research Rabbit                                                                                                                 | —/回/卡  | S2+Crossref 融合，URL 步迹栈           |
| 2   | NotebookLM                                                                                                                      | 跳/—/卡  | 用户上传源 inlineObjectLocations       |
| 2   | ar5iv/arXiv HTML                                                                                                                | 跳/—/卡  | 纯 DOM li.ltx_bibitem                  |
| 2   | BabelDOC/PDFMathTranslate                                                                                                       | —/—/—    | 无引用数据层（竞品空白）               |
| 2   | Kindle X-Ray                                                                                                                    | 跳/回/—  | 预处理 .asc SQLite 实体索引随书捆绑    |
| 2   | Inciteful                                                                                                                       | —/回/卡  | 自建索引 api.getPaper                  |
| 2   | Notion                                                                                                                          | 跳/回/卡 | workspace block 树+recordMap           |
| 2   | hjfy.top                                                                                                                        | —/回/—   | 无卡功能                               |
| 2   | scite.ai                                                                                                                        | 跳/—/卡  | Smart Citations 自建索引               |
| 2   | Zathura                                                                                                                         | 跳/回/—  | poppler link annotation                |
| 2   | Scholarcy                                                                                                                       | 跳/—/卡  | 自建管线 + 远端拼装                    |
| 2   | Hypothesis                                                                                                                      | 跳/—/—   | h API 云端批注                         |
| 2   | MarginNote                                                                                                                      | 跳/回/卡 | 本地摘录卡片 + 脑图词典                |
| 2   | Roam Research                                                                                                                   | 跳/回/卡 | Datascript 图库 Live Preview           |
| 2   | Citation Gecko                                                                                                                  | —/—/卡   | Crossref 实时拉取                      |
| 2   | Okular                                                                                                                          | 跳/回/卡 | 本地裁剪 pixmap 异步渲染               |
| 2   | IEEE Xplore                                                                                                                     | 跳/—/卡  | IEEE 服务端解析文献表                  |
| 2   | LiquidText                                                                                                                      | 跳/回/—  | 本地摘录切片+lt:// 深链                |
| 2   | ACM DL                                                                                                                          | 跳/回/卡 | 页内 li#BibPLXBIBnn                    |
| 2   | SciSpace                                                                                                                        | 跳/回/卡 | /api/citation-management 自建          |
| 2   | ScienceDirect                                                                                                                   | 跳/回/—  | 页内 DOM .reference                    |
| 1.5 | Paperpile                                                                                                                       | 跳/回/卡 | 自建库（Crossref/PubMed 补全）         |
| 1   | Elicit / Connected Papers / Humata / papers.cool / Litmaps / OpenReview / Kami / Unpaywall / ChatPDF / Mendeley / EndNote Click | 各异     | 图谱/RAG/批注类，迁移度低              |

52 车道交付 40 条带深挖、12 条 survey-only；全部 52 条原始回答在 raw.json。

## 8. 完备性批判与未定问题

**漏查**：Acrobat「上一视图」桌面跳回基线未查；eLife Lens 侧栏引用面板——「浮卡 vs 侧栏」缺直接对照；Wiley/HighWire、CNKI（zh 预期基准）未查；GROBID 兜底被低估（无 ph/.bib 链/无 hyperref 三洞场景）；钉住卡/嵌套卡/`[3-7]` 多键卡未立车道。

**高估**：图谱发现类（Connected Papers/Litmaps）的历史是搜索会话态，对文档内锚跳几不可迁移；X-Ray/LiquidText/NotebookLM 偏猎奇。

**未定（待设计裁决）**：

1. zh 侧点 cite → en 侧跟不跟：split 跟（同名 dest 零成本），但卡满足需求则跳转低频——建议先卡后跟。
2. click 语义：荐 Zotero 分工（hover=卡/click=跳 + 压栈）；触屏 tap=卡、卡内置「跳到文献表」钮。
3. 远端源：S2 成形快但 429 池——必须代理+TTL+ 负缓存，本地表先行。
4. 无 hyperref/no-ph 兜底范围：v1 可只保 hyperref 链出卡，其余降级只有跳转。
5. 跳回 UI：复用 drift 钮还是悬浮 chip——荐悬浮 chip+ 栈按 pane 独立；栈条目含 {paneSide,page,Pos,scale}。

## 9. 原始数据

- 全量结构化产出：`docs/research/product/citation-ux-2026-09-21/raw.json`（survey 52 / deep 40 / mech 30，含每条 evidence 与 file:line 引用）。
- workflow journal：`~/.claude/projects/-home-fanghaotian-src-texlate/.../workflows/wf_07d2a7a7-e4b/journal.jsonl`。
