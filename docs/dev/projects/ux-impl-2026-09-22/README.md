# texlate 阅读器 UX 七功能总实现路线图

> 证据底座：57 recon + 24 arch + 56 experiment（works 47 / partial 8 / fails 1）+ 56 对抗核验（confirmed 50 / uncertain 3 / refuted 3）+ 16 design。全部产物在 `tmp/ux-research-20260922/`（exp/\* 实验件、verify-* 核验件、`synth-master-inputs.json` 全量结构化结果）。本路线图对应 7 个 lane：sel-system（选区/右键/快捷键体系）、find-usages（反向引用）、copy-latex（复制 LaTeX 源）、sent-align（句级双语对齐）、sel-translate（划词翻译）、cite-translate（引用卡→翻译闭环）、misc-pack（杂项加固包）。

## 一、七功能结论速览

| Lane           | 推荐形态（design 裁决）                                                            | 最小工作量                                  | 完整工作量                        | 可行性                                             |
| -------------- | ---------------------------------------------------------------------------------- | ------------------------------------------- | --------------------------------- | -------------------------------------------------- |
| sel-system     | 单注册表 + 数据 when+ 三薄适配器（cmdreg）→ FloatBar+ContextMenu+ 键位分发         | 2–2.5d（无 cmdreg）/ P0+P1 ≈5d（含 cmdreg） | 9–12d（+游标模态+palette+assist） | 全绿：三件套 spike 42/22/26/66 测试全过            |
| find-usages    | 统一 UsageIndex（DOM 锚/PDF dest 反查/ph token 三 provider）+ 卡片/面板双形态      | ≈2d（dom 链 MVP）                           | 6–8d 三视图                       | 全绿：锚普查/语境句/跳链全 confirmed               |
| copy-latex     | alttext/annotation 公式级 + seq→span 选区级 verbatim                               | 1.5–2d                                      | B 档 3–4d（C 档 1–2w 可选）       | 全绿：100% 载体覆盖、span 映射已在 DB              |
| sent-align     | 前端 bead 对齐 + CSS Custom Highlight（A），二期 dual.json sents+PDF \pdfdest（C） | ≈2d（client-bead-link）                     | A 5–7d + C 7–9d                   | 全绿，对齐正确率 87.5% 为固有上限                  |
| sel-translate  | 泡钮→锚定卡 + 新同步端点 POST /xlat/selection + 词典/翻译双模                      | 1.5–2d                                      | MVP ≈4d；+流式/回查/持久化 ≈11.5d | 可行但须新建端点（现无自由文本通道）+ 网关限速适配 |
| cite-translate | 卡内单译钮 + 文献抽屉批译 + toast/徽标观测面；服务端零新端点                       | ≈1d（钮+toast）                             | 5–6.5d                            | 可行；硬前置=M1 keyless 修复（mock 毒化）          |
| misc-pack      | 四件打包：M1 keyless 诚实面 / M2 URL canon / M3 pin 耐久 / M4 refs.bib             | 3–4.5d                                      | 8–9d                              | 全绿：四件各独立可 ship                            |

## 二、依赖关系（前置地基）

### 2.1 两个跨功能前置件（必须先落）

1. **command registry（cmdreg + HitCtx + 单分发壳）** —— sel-system P0 同时就是它。
    - 形态：`web/src/reader/cmd/{cmdreg,hitctx,commands}.ts + entries/{keymap,menu,floatbar}.ts`；`Command={id,title(i18n),when,enableWhen,keys,sec,bar,run(ctx)}`，when 是 VS Code 风字符串谓词（编译期爆坏语法、`whenKeys⊆ctxKeys` 可静态审计）；HitCtx=事件瞬间同步快照（sel/cite/math/chunk/caps 五 facet 非互斥）。
    - 谁依赖它：sel-system 三入口（浮条/右键/键位）；之后 copy-latex 的菜单项（math.copyTex/chunk.copySrc）、sel-translate 的泡钮/菜单项（sel.xlat/sel.explain）、find-usages 的 cite.jump/usages、sent-align 的开关与游标模态键面，全部以「注册表加一行」方式接入。不建注册表的替代（入口自治）已被实测否定：现状三路监听已有 2 格失败 +1 格双发。
    - 工作量：≈3–4d（spike 产物 253/422/305 行净移植 + HitCtx 三视图解析器 + 21 项命令表 + 分发壳 + 审计测试）。

2. **taskStatus 扩展（taskStore 窄面开放）** —— cite-translate 卡片 chip/徽标/批译面板的前提。
    - 形态：不新建 store/传输层。tasks.ts 加 `track(taskId,{arxivId?})`（非 pin 登记）、`intents` Map（arxivId→taskId 竞态桥，TTL 60s）、`taskByArxiv()` 派生选择器；taskTransport 唯一改动=`pollListWanted` 从「只归并 wanted ids」改「整表归并」（新非终态行自动 wanted(pin:false)、消失行 unwant）——badge/Tasks 页零改自动吃红利。
    - 纪律：pin 槽（MAX_SSE_TASKS=3）是 reader 聚焦专属，任何卡/badge 不得 `watch()`；queue_position 只在 SSE snapshot 帧下发，槽外只显「排队中」。
    - 工作量：1.5–2d（含 vitest）。

### 2.2 微插桩（行级改动，先落先解锁）

| 插桩                   | 位置                                                                                               | 解锁面                                                                                       |
| ---------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `ADD_ATTR:['alttext']` | `web/src/reader/sanitize.ts` DOM_PROFILE（1 行）                                                   | DomPane 公式 LaTeX 载体 0→100%（annotation/semantics 维持禁放=mXSS 防线）                    |
| `chunk_id` 投影        | `worker/html.py:101 _dual_chunk_row` + `routers/tasks.py` chunks 端点 + `types.ts`（≈3 处各 1 行） | dom 视图 data-chunk key→seq 映射（chunk.retx、copyPair、usages seq 定位）                    |
| `unmaskLatex` 插桩     | `web/src/reader/markdown.ts`：MATH 替换外包 `span[data-ph]`、CITE→`a.cite-ref[data-key]`（≈15 行） | html 视图 math.copyTex 0→2485 hits、cite.* 0→128 可解                                        |
| PDF dest 预解析集      | PdfPane MO/加载期 `getAnnotations` 分片扫 → dest 名 Set                                            | `cite.targetExists` 同步谓词（getDestinations() 批量 API 在真实文件返回 0，必须逐名/按页扫） |

### 2.3 横向依赖链

- `toastStore+ToastHost`（≈0.5d，spike 已验）→ cite-translate 回执、sel-translate 错误面、copy-latex 拷贝反馈。
- `sentalign` 句切+bead 对齐器 → sent-align 本体 + sel-translate P2 的 zh→en 回查（st-backcheck 同算法）+ find-usages zh 侧语境句。
- misc-pack **M1（keyless 修复）是 cite-translate 的硬前置**：无 key 派任务会产 MockTranslator 假译文并毒化段级缓存桶（首跑毒化后续所有同桶任务），cite 卡放行 POST 前必须有 key 闸。
- misc-pack **M2（canon 单源）是 cite 批译判重的前提**：preflight 分桶依赖双侧 canon 归一（mixed-id-forms 坑：raw `cat/id` vs canon `cat--id` 并存）。
- 服务端 `GET /api/task/{id}/source?seqs=`（copy-latex P1）依赖 chunks 表已有 (src_file,byte_start,byte_end)——零新仪表，纯投影放出。
- sent-align C（PDF 句锚）动编译链，须在 `latex/reconstruct.py` splice 内注入 `\pdfdest`（禁 `\hypertarget`——FitH 丢 x 已实测），依赖 fixloop/resplice 幂等窗口。
- kept-refs 表（misc P2）→ refs.bib 导出与卡面 keep 钮；DDL 追加式自动迁移。

## 三、推荐批次

### B0 · 止血与微插桩（≈2d，串行最先）

**原因：两个静默数据腐化 bug 在飞，且微插桩是后续一切的前提。**

- M1 keyless 诚实面：server 侧 `deps.create_and_enqueue` 在 `source=='none'` 时走 needs_auth 臂（豁免显式 mock 工厂）；web 侧 Home 预检 has_api_key 引导条 + Reader done 警告细条。0.5–1d。
- M3 pin 耐久化：pin 真相落 cell 侧 PINNED 标记文件，三把清扫器（lake.evict/shrink_shell/remove_cell_tree）+ catalog rebuild 全认标记（实证三连全漏）。~1d。
- 微插桩四件套（见 2.2）：alttext、chunk_id、unmaskLatex span/a、PDF dest 预扫描骨架。
- toastStore + ToastHost 落仓（spike 平移 ≈200 行）。

### B1 · 选区内核（≈5–7d）

- P0：cmdreg.ts + hitctx.ts + selection.ts + escstack.ts；ReaderView.tsx:167-242 硬编码 onKey 整块换成单分发器（顺带修 legacy：findbar checkbox Esc 失灵、pdf.js editor 态 Backspace 双发、help modal 穿透）。带齐 42+66 测试与 `whenKeys⊆ctxKeys`/chord 冲突表审计。
- P1：FloatBar（release 压制 +40ms debounce+scroll capture 跟随+ResizeObserver/MutationObserver 防陈旧）+ ContextMenu（Portal、placeMenu/placeSubmenu、Esc capture+sIP、菜单/浮条互斥、Shift+ 右键放行原生）挂三 pane 委托；menu-spec 21 项按 caps 裁剪；settings 加 floatbar 开关。
- 出口判据：jsdom 命中矩阵绿 + placeMenu/placeBar fuzz 0 违例 + 手测三视图。

### B2 · 任务观测面（≈2d，可与 B1 并行）

- tasks.ts `track()/intents/taskByArxiv/taskStatusOf` + taskTransport `mergeList` 整表归并；Toolbar 挂 activeCount badge（复用 .nav-badge，reader 内落点）；visibilitychange→visible 补一拍 ensureFresh(0)。

### B3 · 引用翻译闭环（≈3–4d，依赖 B0-M1/M2 + B2）

- CiteCardBody foot「翻译此文」钮（显隐复用 `meta()?.arxivId ?? e()?.arxivId` 门）→ citeTranslate.ts 七态分派（preflight done/active → POST → 200/202/409/401 → toast）。
- RefTaskChip 状态机（idle→queued→running→done/failed，**必须含 terminal→running 回边**——retry 同 task_id 续写同一事件流）。
- RefsPanel 抽屉批译：`GET /api/tasks` 一拍 preflight 三桶分桶（canon 归一）→ 仅 new 臂串行 POST + Idempotency-Key；K>30 出确认文案（N=60 批译 p50≈47min）。
- `extractRefIds` 加裸 DOI 兜底（36.3%→43.3% 覆盖）；GuidePane citations 加小钮。

### B4 · 三乘浪（可并行，合计 ≈8–10d）

- **sel-translate MVP（≈4d）**：server `routers/selxlat.py`（POST /api/task/{id}/xlat/selection，text≤4096、deps.get_task 闸、per-IP 30req/40k tok 日滚双桶、translation_cache `sel:` 前缀臂、record_usage 真账、SEL_PROMPT_VERSION 独立、超时≥30s 因 p99=16.2s）；前端泡钮 + 锚定卡（chunk 锚，换宽误差 0px vs 页分数 272.6px），词典/翻译双模，卡内排除 `.cite-card,.sel-bubble` 防自触发。客户端节流 ≤4/min + retry-on-empty + SSE error 帧映射（`_sse_events` 补 error→异常，治网关 200+ 空流静默）。
- **copy-latex（≈2–4d）**：`copyLatex.ts` 三级提取（raw 序索引/alttext+KaTeX annotation/ph token）+ 选区 seq 区间 unmask 拼接；server `GET /api/task/{id}/source?seqs=` 按 **decode_tex 后字符偏移**切 `base/`（绝不切 src.tar——normalize 注入 prologue 致 62% 静默错切）；sentclip 默认档（brace-balanced 99.6-100%）；菜单项只在有可提取物时 preventDefault。
- **find-usages（≈3–5d）**：`usages.ts` 移植泛化（figure/bibitem/table/equation/section/theorem 分类 + nav/TOC chrome 剔除 + 自指丢弃）；UsagesCard 复用 CiteCard 壳；DomPane 三触发（点击/contextmenu/:focus-visible）；PDF 侧 idle 分片扫 dest 反查表按 doc.version 缓存（29% 文档零 dest、3% 匿名 hex 名→诚实空态）；跳转全走现成 jumpToEl/onDestJump/navstack。**移植必须带 suppressUntilExit/600ms scrollGrace**（第三 reopen 向量实证）。

### B5 · 句级对齐（≈2d MVP / 5–7d 完整 A）

- MVP（client-bead-link ≈2d）：`sentalign.ts`（splitEn 移植 sentence_ends / splitZh 用 ws-normalize+「。！？!?+闭引号」正则臂——Intl.Segmenter zh 对 Latin 缩写系统性过切勿用）→ alignBeads（ρ 自适应贪心、锚元素硬约束、MAXG=4）→ wrapChunk DOM 后注入（绕开 marked code-block 死区）→ linkSentAlign 委托 hover 双侧点亮。零后端零迁移。
- 完整 A（5–7d）：CSS Custom Highlight 主路+span 兜底、点击定位 gotoSent 走 navstack 镜像、单栏 Peek 卡（CiteCard 壳）、LivePane 逐段 collect、Toolbar 'a' 开关。
- sel-translate P2 回查与 find-usages zh 语境句乘此 bead 对齐器便车。

### B6 · 深水区/可选天花板（≈2–4w，按价值排期）

- sent-align C：dual.json v2 `chunks[].sents`（新 `src/texlate/sentalign.py`）+ zh 侧 splice 内 `\pdfdest` 锚 + PdfPane overlay（7–9d）；注意 ~3.5k snt 锚进 `_monotonic_chain` O(n²) 需两段式拆解。
- sel-system P2/P3：游标模态（v 进/jk 句/[] 块/Enter 落 Selection/t 取对侧句——修 87.4% 句键盘不可达；哨兵 id 须带 pane 后缀防撞车）+ CommandPalette（Ctrl+K）+ 后端 assist 端点。
- copy-latex P3：`\texlatemark` PDF 锚、accsupp `\ActualText`、zh_spans 旁车（1–2w）。
- cite-translate Phase 3 打磨 + misc-pack P2 kept-refs 全量（3–4d）与 M4 refs.bib（1–1.5d，Lane A verbatim+@STRING 闭包+ci 折叠，Crossref 臂必须 title-overlap≥0.5 门控、S2 全程 429 不可入链）。

## 四、总工作量

| 口径                                                 | 人日    |
| ---------------------------------------------------- | ------- |
| 七功能全 minimal + 共享地基（B0–B5 中 MVP 档）       | ≈20–24d |
| 推荐 rollout（B0–B5 含 sent-align A、cite 批译面板） | ≈30–35d |
| 全 ideal（含 B6 深水区，不含 copy-latex P3 上限档）  | ≈50–60d |

## 五、风险登记册（按严重度排）

| #   | 风险                                                                                                                                                                                                                              | 等级    | 所在 lane                | 缓解                                                                                                                                                |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | **Mock 毒化**：无 key local 提交静默产假译文并永久污染段缓存桶（reuse_hit 克隆+translation_cache 指纹缺 key/translator 身份），prefer=fresh 重跑仍 67% mock                                                                       | 高      | misc/cite-translate      | B0-M1 最先落；cite 卡 has_api_key 硬闸；显式 mock 走 TEXLATE_TRANSLATOR 白名单                                                                      |
| R2  | **Esc/键位层栈**：ss-ctxmenu 核验出 3 缺陷（子菜单 roving 键未 sIP、与 CiteCard:62 同节点更早注册的 capture Esc 一次塌两层、开着的子菜单不关）；现状已有 2 fail+1 cofire                                                          | 高      | sel-system               | 唯一解=中央层栈 registry（topmost 语义）+ 12 行层栈测试；FindBar Esc 移交层栈；editor 层只记账不消费                                                |
| R3  | **zh 侧结构性丢失**：id 幸存 92%（bare inline id 随 clear() 丢 69 个）；nested-block kill 是内容丢失级 bug——嵌套 data-chunk 块被整棵 clear，§3.2.3 三个 item 译文缺席且 page↔page 同步 ~70% 文档错位                              | 高      | fu/sent-align            | emit 侧修：含后代 [data-chunk] 的块禁整棵 clear（提升为兄弟节点或保护 token）；zh pane 索引自建不依赖 en id                                         |
| R4  | **PDF dest 面**：29.1% 编译产物零 named dest；3.2% 匿名 hex 名（疑似 fixloop/重烘焙改写非 ASCII anchor）；getDestinations() 批量恒 0                                                                                              | 高      | fu/sent-align            | 逐名 getDestination/按页 getAnnotations 分片懒扫+version 缓存；hex-degenerate 文档诚实空态；查 fixloop anchor 改写                                  |
| R5  | **对齐正确率天花板**：单调对齐 spotcheck 87.5%，失败清一色 zh 边界滑移级联；6.14% chunk 句数不等（zh>en 9.7:1 不对称）                                                                                                            | 中      | sent-align/sel-translate | 诚实设计=n:m bead 整组亮、禁伪造 1:1；后端 beads 仅在双侧句数核验通过才采信；错亮不毁 chunk 级 sync                                                 |
| R6  | **字符串注入死区**：zh 续行 `\n`+缩进被 marked 判 code block，`<span>` 变字面文本静默全灭（0.49% chunk）；fu-popover 第三 reopen 向量（卡卸载后指针下 figure 重触发）                                                             | 中      | sent-align/fu            | 只做 DOM 后注入（TreeWalker text node），永不做字符串注入；移植带 suppressUntilExit                                                                 |
| R7  | **坐标系陷阱**：chunks.byte_start/end 是 decode_tex str 的**字符**偏移（非字节），坐标系是 normalize 后 base/ 非 src.tar（tar 回退腿 62% 静默错切须删）；EXPAND 组 chunk 调用点原文双侧不可重建，span 切片是唯一真源              | 中      | copy-latex               | 端点只切 base/；API 面建议改名 char_start/end；base 缺失任务重扫或拒绝不兜底                                                                        |
| R8  | **网关传输面**：隐式 ~6req/min + 60s 闩；上游限流回 200+SSE error 帧被静默吞成空流；swe-2 假流式（delta 挤末段）；固定 prompt 地板 ~470 tok（7-token ping 计 474）；REQUEST_TIMEOUT_MS=15s < p99 16.2s                            | 中      | sel-translate            | 端点超时≥30s；客户端 ≤4/min 节流+retry-on-empty；`_sse_events` 补 error 帧→异常映射；按真账 usage 计费不按 chars                                    |
| R9  | **SSE 槽纪律与 store bug**：demotion→sseDead 误伤（降级任务永不再升回、槽位整会话空转）；`resetLive` merge 语义不清 done（陈旧终态泄进 retry 轮，Reader 拿旧 artifacts）；retry 撞 cache_key 裸 IntegrityError 500                | 中      | cite-translate           | track() 非 pin 登记；closeChannel 前摘 wanted；修 resetLive 显式清 done；retry 撞槽归一 409                                                         |
| R10 | **覆盖率天花板要诚实**：56.7% \\bibitem 无任何 id（per-doc p50=19%、155 篇零覆盖）；eq 目标 id 覆盖仅 ~21-47%；sec inlinks 70% 是 TOC chrome                                                                                      | 中      | cite/fu                  | 面板头部「N 条·K 条可译」计数 + 灰态原因行；DOI 兜底臂 +7pp；eq 类 v1 不做触发面；chrome 锚剔除                                                     |
| R11 | **选区面暗坑**：linkAnnotation rect 上无法起拖（pdf.js 原生）；splitPct 拖条/流式插 DOM 不发 scroll/resize→浮条陈旧；合成 pointerup 丢失卡死 release 压制；28% 文本在 seq=null 锚（bibitem/figure/authors）；卡内文本再划词自触发 | 中      | sel-system               | ResizeObserver+MutationObserver/refresh()；pointercancel+window blur 兜底；chunk facet 容忍 null、copyPair 按 counterpartAvail 门；closest 排除卡体 |
| R12 | **sanitize/泄漏面**：alttext 恢复后泄漏尾文本节点是版本脆弱提取面（DOMPurify 升级可静默消失）；rewrap=md 全文正则腐蚀未掩码 `$..$`；`\newenvironment{xlatseg}`+`\providecommand{\xlatseg}` 名撞致 seq 泄漏进 PDF                  | 低 - 中 | copy-latex               | raw 序索引为主、泄漏文本仅兜底 + 回归测试；rewrap 必须与掩码感知同层；env/macro 用非撞名                                                            |
| R13 | **新 schema/DDL 面**：`kept_refs` 走 DB（躲开 `slim_task_dir` 抹 sidecar——`reading.json` 已被实证会丢）；dual.json sents 须为「DB 行 + 可重扫源」纯函数（retranslate 重跑 `_build_dual`）；`OPTIONAL_KEYS` 扩键旧 kernel 拒读     | 低      | misc/sent-align          | DDL 追加式迁移；payload 快照自愈序数漂移；kernel 单仓无跨版本面≈0                                                                                   |

## 六、明确砍掉/不做清单（各 lane 设计裁决汇总）

- sel-system minimal 砍：cursor 模态、命令面板、子菜单、触屏长按、LivePane 接入、sel.find@dom/html。
- sent-align 砍：pdf-dest 一期（挪 C 档）、emit 期字符串注入（死区实证）、设置开关。
- copy-latex 砍：PdfPane 文本层取源（无载体）、mathml-to-latex/OCR 兜底链（无源面=自家 sanitize 造的，1 行 ADD_ATTR 治本）、DomPane 正文复制（html 链无 prose LaTeX）。
- sel-translate 砍：zh→en 反向 v1、复用 retranslate 端点（串行队列+resplice+ 全量重编，形态错配）、卡内嵌 key 输入写 localStorage。
- cite-translate 砍：服务端批译端点（客户端 preflight+ 串行 POST 已够）、watch() pin 槽（反模式）。
- find-usages 砍：literal/deictic 提及补扫 v1（仅 +4% recall，phase4 再议）、html 视图无锚时的假装降级。

## 七、产物索引

- lane 实现文档（本目录内）：
    - `sel-system 实现文档：选区→命令→菜单_浮条_键位_句游标.md` — 选区内核（cmdreg/HitCtx/Esc 栈/FloatBar/ContextMenu/句游标）
    - `find-usages（目标→全部引用处）实现文档.md` — find-usages
    - `copy-latex 实现文档（调研综合）.md` — copy-latex
    - `sent-align：阅读器句级双语对位高亮_跳转 实施文档.md` — sent-align
    - `cite-translate 实现文档：引用文献一键_批量翻译.md` — cite-translate
    - `misc-pack 实现文档：缺 key 防护 + arXiv ID canon + lake pin + .bib 导出.md` — misc-pack 四件
    - `⌘-inspect 修饰键检视层 实现文档.md` — ⌘-Inspect（2026-09-26 增补）
    - `sel-translate 选区翻译 — 实现文档.md` — **已砍未实施**（2026-09-23 落地波裁决）
    - `kept-refs-design.md` — misc-pack M4 设计稿：kept_refs 表 + refs.bib 双级组装（2026-09-29 自 tmp/ 归档）
    - `fu-id-conv LaTeXML id 词表普查.md` — find-usages 证据附件：LaTeXML id 词表普查（2026-09-29 自 tmp/ 归档）
    - `ct-card-states 状态机实证.md` — cite-translate 证据附件：卡片状态机实证（2026-09-29 自 tmp/ 归档）
- 汇总输入：`tmp/ux-research-20260922/synth-master-inputs.json`（209 份 agent 结构化输出全集）
- 可直接移植的 spike 代码：`exp/ss-ctxmenu/`（ContextMenu.tsx 422+ctxmenu.css 104+594 行测试）、`exp/ss-floatbar/floatbar.mjs`（305 行）、`exp/ss-cmdreg/`（253 行 +42 测试）、`exp/ss-hotkeys/keymap.js`（66 cell 全绿）、`exp/ct-toast/`（toastStore.ts+ToastHost.tsx）、`exp/fu-popover-spike/figIndex.ts`、`exp/st-modal/`（锚定 + 拖拽 26/26）、`exp/ms-urlnorm/norm_spike.py`（30 形态表 +44 对抗探针）、`exp/cl-settings-spike/`（变换矩阵 64 输出 roundtrip 全对）
- 语料真相：真实 dual.json 在 `~/.texlate/tasks/`（repo 内无 populated 样例，align-sample 已实证）；zh-store/bench 供回测

## 八、实施状态（2026-09-23 全量落地）

> 四轮 workflow 实施完毕（wave A 地基 6 lane → wave B 选区内核 3 段 → wave C 功能 5 lane → wave D 整合 + 修复 + 验证 3 段），终态：**tsc 0 错 / vitest 868/868（65 文件）/ eslint 0 警 / pytest tests/ 9998+32skip / tests/kernel/ 583+2skip / ruff server+kernel 清零**。sel-translate 已按裁决砍掉，menu-spec 中 sel.xlat/sel.explain 未注册（无 assist 端点）。

### 落地清单

> 本表是全包**权威落地清单**：各 lane 实现文档记的是该 lane 的设计与当时计划，与本表冲突以本表为准（代码为最终事实源）。

| 功能           | 代码落点                                                                                                                                                                                                                                                                                                                                                                 | 验证                                                   |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------ |
| toast 地基     | `web/src/stores/toastStore.ts` + `components/ToastHost.tsx`（挂 App.tsx）+ `styles/toast.css`                                                                                                                                                                                                                                                                            | 8 vitest                                               |
| M1 缺 key 闸   | `routers/deps.py`（建行即 needs_auth+ 撞键收编 200）+ `store/_tasks.py`（mock_run 审计键、find_needs_auth_by_cache_key）+ `worker/translate.py` + `http.py` `_RESERVED_OPTION_KEYS` 摘 mock_run/no_seg_cache；前端 Home 提示+ResultBody banner/mock retry                                                                                                                | tests/server/test_server_keyless_gate.py 9 项          |
| M2 canon       | `arxiv/fetch.py` canon/try_canon/CanonError + `home/search.ts` parseArxivId 扩面                                                                                                                                                                                                                                                                                         | test_arxiv_canon.py + parseArxivId.test.ts（102 断言） |
| M3 lake pin    | `bench/py/kernel/` lake pin/unpin/status + PINNED 标记三清扫器全认 + sweep 尾段 gc_sweep + events 五键重放 + importer pinned 透传                                                                                                                                                                                                                                        | test_lake_pin.py 20 项                                 |
| M4 kept+.bib   | `store/_kept.py`+kept_refs DDL+`bibexport.py`（verbatim→@misc 降级+X-Refs-Degraded）+refs.py 三端点；前端 `stores/keptRefs.ts`+CiteCard ☆+Reader 下载项                                                                                                                                                                                                                  | test_server_refs_kept.py 44 项                         |
| B2 taskStatus  | `tasks.ts` track/intents/taskByArxiv/taskStatusOf + `taskTransport` 整表归并 + Toolbar「任务 N」chip + notifyDone 双写点                                                                                                                                                                                                                                                 | taskObserve.test.ts                                    |
| 微插桩         | sanitize ADD_ATTR（alttext+data-sid+data-bead+data-ph+data-key+data-bib-key）、chunks 投影 chunk_id、markdown.ts unmask 产 span[data-ph]/a.cite-ref/span.bib-anchor、PdfPane dests() 预扫                                                                                                                                                                                | —                                                      |
| sel-system     | `reader/cmd/{cmdreg,hitctx,commands}.ts`（18 命令+when DSL+CTX_KEYS 审计）、`reader/sel/{selection,coveredChunks,escstack,sentseg,cursor}.ts`、`keymap.ts` 单分发器、`FloatBar.tsx`+`ContextMenu.tsx`、ReaderView 接线、`styles/selsys.css`、settings floatbar 开关                                                                                                      | sel 七件套 194 + 组件 25 vitest                        |
| copy-latex     | `server/srccut.py`+`routers/srccut.py`（POST /api/task/{id}/latex，三级回落+sent 锚定+gaps 回收）+`_chunks.py` spans_by_seqs；前端 `copylatex.ts`+`LatexCard.tsx`+`features/copylatex.ts` 三命令（math/chunk/sel.copyTex）+mathml-to-latex 懒载兜底                                                                                                                      | 17 pytest + 20 vitest                                  |
| find-usages    | `usages.ts`（DOM 锚扫+ph token+pdf dest 三层，TOC 剔除/自指丢弃/子图归并）+`uscontext.ts` 语境句+`UsagesCard.tsx`（suppressFocusOpenFor 已带）+`features/findusages.ts`（cite.usages+attachUsages）+DomPane/PaneSlot 委托+CiteCard「N 处引用→」                                                                                                                          | 36 vitest + usages_verify.mjs 27/27 实跑               |
| sent-align     | `sentalign.ts`（splitEn/splitZh 正则臂/alignBeads MAXG=4/注入绕 marked 死区/.sa-hot/.sa-peer/点击跳+navstack+DOM→PDF fraction→/XYZ dest）+Settings 开关（texlate-sent-align 默认开）                                                                                                                                                                                     | 32 vitest                                              |
| cite-translate | `citeTranslate.ts` 七态机（含 terminal→running 回边 + 零帧行兜底+band 插值）+`RefTaskChip.tsx`+`RefsPanel.tsx` 批译抽屉（preflight 三桶+warn_big+ 串行 POST 独立 idem key）+Toolbar「文献」钮+CiteCard foot 翻译 chip+citations.ts 裸 DOI 臂                                                                                                                             | 71 vitest                                              |
| sentalign 动效 | `anim.ts`（涟漪/连线 + 行擦入/clearLandFx 单轨）+ sentalign `from` 穿线·`peerGen` 代际·侧限定键·节流 + 滚动清轨·injectChunk 重备 + PdfPane `saTintReq` 重染 + `mountedPdf` 免重挂（v1.6，`f8a848bb`，2026-09-26）                                                                                                                                                        | anim+sentalign 62 vitest + playwright 10/10            |
| sentalign 句级 | `sentalign.ts` `pdfSentAt`/`pdfSentUnder`/`seqLeafGroup`（marked 叶重切句+u 选句）+ `pdfTintEls` dep + `armPdfPeer` u-跟手/`pdfHoverPos` 存位重补 + PdfPane `seqLeaves`/`flashEls`/`tintEls`/`flashDest`/`landingFlash`/`saFlashAt` 新度闸（v1.7 `39b93bed` 点击落点句级 + v1.8 `272bc14b` 悬停/落定全句级，2026-09-26）                                                 | 54+ vitest + pw 14/14                                  |
| ⌘-Inspect      | `features/inspect.ts`（armed/hoverEval/`hotEls[]`/Esc 栈）+ PdfPane `inspectAt`/`inspectDestAt`/`destHotAt` 分面命中（文字 0.02/浮动体 0.045/空白 0.09+ 栏闸 0.45）+ `scanDests` 螺旋序+`resolveDestPoints` 并行 + `destPoint`/`destRowLabel`/`bandElsNear` + DomPane/HtmlPane armed 揭示 + `styles/inspect.css`（v1 `3b60a33d` + 命中/揭示加固 `272bc14b`，2026-09-26） | inspect vitest + pw 12/12                              |

### 已记 deferral / 已知边界

- DomPane 引用卡暂无「翻译此文」chip（PaneSlot 未透传到 dom 臂）；ReaderView 级 menuCard（右键/c 键）的 CiteCardBody 已接 onTranslate+refTask，同功能入口覆盖——dom 臂补接留作小事。
- pdf 侧 usages/copyTex 均为机会型（named dest 覆盖天花板 59.6%，hex-degenerate 文档诚实空态）；live-pane 与 ReaderView 互斥故其接线是防御性死支。
- sent-align：DOM↔DOM bead 级 + PDF 侧悬停/点击/落定闪句叶级均已落地（v1.7/v1.8——marked 叶文本重切句 + u 分位选句，无 `\pdfdest` 句锚即得）；v2 `\pdfdest` 句锚/v3 sentinel 句标仍未做（管线改动，按 B6 排期）。
- e2e：usages_verify 27/27 实跑绿；copylatex/selsys/citetranslate verify.mjs 已 authored，须活服+fixture 才跑。
- `?seq=N` 深链已通（App 路由参→caps.linkScheme→chunk.copyLink 产 `#/reader/{id}?seq=N`），同任务内点击不重跳（keyed Match 取舍）。
- tests/ 与 tests/kernel/ 混跑有 conftest 模块名碰撞怪癖（既有）；kernel test_s07 并发用例偶发抖动（既有）。
- 旧断言面已随语义更新：~30 处 keyless→needs_auth 预期、canon 归一形、mock warning 反转——全部为有意语义变更，非回退。
