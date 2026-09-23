# copy-latex 实现文档

> 调研综合：9 组实验（cl-anno-census / cl-renderer-id / cl-seq-map / cl-span-extract / cl-dialect / cl-arb-sel / cl-macro / cl-fallback / cl-settings-spike）+ ss-dom-sel / ss-floatbar 交互探测 + 代码审计。产出物=「阅读器内一键复制原文 LaTeX 源」功能的可执行实现规格。

## 目标

在阅读器（Reader）内把「看到的内容」还原成「可粘贴的 LaTeX 源」：

1. **公式级**：点击渲染公式 → 弹出源码卡（LaTeX 本体 + 复制钮）。覆盖 dom 视图（arxiv_html 链 MathML）与 html/live 视图（KaTeX）。
2. **选区级**：拖选一段正文 → 浮动条「复制 LaTeX」→ 得到覆盖 chunk 的原始 `.tex` 切片（权威源=DB span→`decode_tex` 切片，含原始宏调用/注释/空白）。默认档 = sentclip（选区边界外扩到句界，平衡率 99.6–100%，中位多收 9–17 字符）。
3. **明确不做**（v1）：dom 视图正文复制（arxiv_html 链没有 .tex 源——`src/` 只有 `index.html`，`src_text` 是 DOM 派生文本+`[[TYPE_n]]` token，非 LaTeX）；pdf 视图公式点选（文本层是字形汤，无载体）；``with_defs`` 自含宏包（P3 候选）。

**分链能力矩阵**（实证基础见对应实验键）：

| 视图/链 | 公式复制 | 选区复制 |
|---|---|---|
| dom（arxiv_html，DomPane） | ✅ alttext 载体 100% 覆盖（修一行 sanitize 即解锁） | ❌ 无 LaTeX 源 |
| html（md_zip 降级，HtmlPane）+ live（LivePane） | ✅ KaTeX annotation（auto-render 现场生成） | ✅ seq→span→源切片 |
| pdf（eprint/upload_tex 终态，PdfPane） | ❌ P3 | 🟡 模糊锚定→整段档（P2） |

## 交互规格

### 公式源卡（dom + html/live，P0）

- **触发**：`click` 命中 `math`（dom）或 `.katex`（html/live）→ 弹出 `.latex-card` 悬浮卡（复用 `CiteCard` 定位骨架：fixed 定位、`GAP=6`、下方不足自动翻上、Esc/滚动/卡片外交付关闭、pointer 可移入）。触屏 tap=出卡。
- **内容**：`<pre>` 等宽滚动区显 LaTeX 源（**一律 textContent 注入，绝不 innerHTML**——载体内容源自 arXiv，虽 inert 但按不可信处理）；底部行：`[复制]` 钮 + 字符数 + 行内公式可选「带 `$…$` 界符」开关（默认关，复制纯体）。
- **快捷键**：`Alt+click` 跳过卡直接复制 + toast。
- **提取序**（cl-fallback 实证）：
  1. `math[alttext]`（dom 链，与 annotation 逐字节相同 8907/8907）；
  2. `.katex annotation[encoding="application/x-tex"]`（html/live 链，KaTeX 渲染产物自带；annotation 文本=phText 喂入体剥界符=原始数学体）；
  3. 皆无（外源 MathML/MathJax assistive-mml）→ 懒载 `mathml-to-latex`（165KB，0.134ms/式，ws-norm 62%/sim 0.877）兜底，卡上标 `approx`。
- `ltx_math_unparsed`（2.9%）与 TOC 内数学（0.18%）同样满载体，无需特判。

### 选区浮动条（html/live P1；pdf P2）

- **出现**：`selectionchange` + 拖选抑制（pointerdown→pointerup 期间不出条；指针失联经 `pointercancel`/`blur` 兜底复位——ss-floatbar 实测 stuck 窗存在）；松手后条浮于选区首 rect 上方，即时随滚动（实测跟随误差 <0.1px）、锚离屏即隐、回滚重现。
- **定位坑**（探针实测，必须落进实现）：条容器 `user-select:none`（拖进条内不扩选）；cross-pane 选区（en→zh 横穿）条锚在 anchor 侧 rect 而非 union（union 会悬在双栏缝上）；pane margin 变化不发 scroll 事件 → 条位置会 stale，重定位挂 `selectionchange`+`ResizeObserver(pane)`。
- **动作**：`[复制 LaTeX]`（默认档）+ 档位移出小菜单：`句界(sent)` / `整段(whole)`，localStorage `texlate-copylatex-mode` 记档（不进服务端 Settings——避免动白名单 schema）。
- **反馈**：成功 toast「已复制 N 段 · M 字符」；`approx` 时 toast 加「（近似重构）」；失败 toast 原文错误。
- **选区→seq**：
  - html/live：`el.closest('[data-chunk]')` 属性值=seq int（`HtmlPane.sectionHtml` / `LivePane` `el.dataset.chunk`），覆盖区间=seq 连续闭区间；
  - pdf：无 DOM 锚——`selection.toString()` 归一化后对 `dual.chunks[].en`（原侧）/`.zh`（译侧）做 difflib 序贯锚定取 seq 区间（anchor 臂 med 误差 0；只做段级命中不做偏移级），整段档返回；
  - 跨 pane：双侧各取各自 seq 集合并去重，head anchor 取 anchor 侧边界段、tail 取 focus 侧边界段。
- **zh 侧铁律**：译侧选区只能整段档——zh 文本在 en 源切片里无锚可定（语言不同），客户端对 zh 侧选区不下发 head/tail，服务端按 whole 处理。

## 数据/管线改动

**现有资产（零迁移）**：

- `chunks` 表每行自带 `(seq, chunk_id, src_file, byte_start, byte_end)`，`chunk_id=sha256(src_file:start:end)[:24]`（`server/worker/_common.py:399`）。span→`decode_tex` 切片即权威片段：10/10 可抽、重扫同 span、零中段切割、零括号失衡（cl-span-extract）。
- `sentence_ends`（`xlat/batch.py:327`）句界扫描器：depth==0 的 `.!?`+后随空白、`\\` 转义双跳、`{}` 深度跟踪、缩写豁免——直接复用做 sentclip 收边（raw tex 上无 `[[SL]]` token 但 `\n` 分支原生生效）。
- `decode_tex`（`textutil/encoding.py:771`） arXiv 编码净化。
- dom 链 `<math>` 双载体 100%（alttext=annotation 逐字节等）。

**改动清单**：

1. `web/src/reader/sanitize.ts` `DOM_PROFILE.ADD_ATTR` 追加 `"alttext"`（一行，实证可存活；`semantics`/`annotation` 维持禁——mXSS 向量，alttext 已够）。
2. **无 schema 迁移**：span 列已在；`dual.json` 投影不加列（dom 链不做文本复制，`chunk_id` 无需下发）。
3. （P3 可选）宏定义持久化：`ScanResult` 的 defs 表（cl-macro：分类 env_begin/math/opaque/transparent_inline/transparent_expand）在 parse 段随 `ph_map` 落 `base/` 旁 `defs.json`，供「复制含定义」模式拼接 `\newcommand` 前置块。
4. （P3 可选，pdf 精确档）splice 期对 zh.tex 注入 accsupp `ActualText=⟦Snnnn⟧` 包裹——spike 实证载体机制：宏回卷覆盖 98.1% chunk 界（moving-arg/tabular 上下文要跳），界符注入 +2.2% 字节但 arg 上下文对 PDF 不可见（纯锚点），roundtrip 剥离全净。属重选项，另行立项。

## 前端改动（文件级）

| 文件 | 改动 |
|---|---|
| `web/src/reader/sanitize.ts` | `DOM_PROFILE.ADD_ATTR` 加 `"alttext"`；头注补「alttext=copy-latex 载体」 |
| `web/src/reader/copylatex.ts`（新，纯逻辑可 vitest） | ①`mathTexFrom(el)`：alttext→katex annotation→mathml-to-latex 懒载三级提取；②`selChunks(bodyEl, lane)`：`Range.intersectsNode` 扫 `[data-chunk]`→seq 区间+头尾 anchor 文本（各 ≤400 字符，含选区边缘上下文）；③`pdfSeqsForText(dual, selText, side)`：归一化 difflib 段级锚定；④`copyText(s)`：`navigator.clipboard.writeText` + textarea execCommand 兜底 |
| `web/src/reader/LatexCard.tsx`（新） | 公式源卡组件：CiteCard 定位逻辑抽出/复刻（rect anchor、翻上、Esc、scroll-close），内文 `<pre>` textContent + 复制钮 + 界符开关 + approx 标 |
| `web/src/reader/SelBar.tsx`（新） | 选区浮动条：selectionchange 驱动、拖选抑制、pointercancel/blur 救援、随滚跟随、离屏隐、`user-select:none`、档位菜单、结果 toast（复用 `.pane-toast` 样式类） |
| `web/src/reader/DomPane.tsx` | `bodyEl` 委托 `click`：`closest('math')`→开 LatexCard（alttext 路径）；不挂选区条（无 LaTeX 源） |
| `web/src/reader/HtmlPane.tsx` / `LivePane.tsx` | 挂 `SelBar`（taskId prop 已有于 HtmlPane；LivePane 需透传）+ math click→LatexCard（`.katex` 路径）。`repaint`/增量补丁后无需重挂——委托在 bodyEl 上 |
| `web/src/reader/PdfPane.tsx`（P2） | textLayer 容器挂 SelBar；`chunks` prop 由 ReaderView 经 PaneSlot 补传（现只 html 视图消费） |
| `web/src/reader/PaneSlot.tsx` / `ReaderView.tsx` | taskId/dual chunks 透传补齐；无逻辑改动 |
| `web/src/api/types.ts` + `rest.ts` | `LatexSelRequest/LatexSelResponse` 类型 + `api.latexSelection(taskId, body)` |
| `web/src/i18n/{zh,en}.ts` | `reader.copyLatex*` 键组（卡标题/复制/已复制 N 段/档名/approx 标/失败），双语逐键对（i18n.test.ts 守护） |
| `web/src/styles/copylatex.css`（新） | `.latex-card`、`.sel-bar`、`.latex-approx` 徽标；复用 cite.css 的卡片外观变量 |

**委托 vs 逐元素监听**：全部交互走 pane 级 `bodyEl` 委托（DomPane 现有 `click`/`pointerover` 委托同款），KaTeX 重扫/chunk 重绘/增量补丁不破坏监听。

## 后端改动

**新端点**：`POST /api/task/{task_id}/latex`（新路由叶 `src/texlate/server/routers/srccut.py`，`routers/__init__.py` 注册位追加）。

```
请求体：{seqs: int[],              // 覆盖 chunk seq 集，≤300、非空、int
        head?: str, tail?: str,   // 首/尾边界段的 anchor 文本（≤400 字符）
        mode?: "sent"|"whole",    // 默认 sent；zh 侧选区客户端恒发 whole
        gaps?: bool}              // 默认 true：同文件相邻块间回收 gap 料
200：{latex: str, chunks: int, files: [src_file…],
     mode_used: "sent"|"whole", approx?: bool, truncated?: bool}
4xx：404 task（get_task 租户闸）、400 seqs 非法/超帽、
     422 kind=arxiv_html（无 tex 源）或源全不可得
```

**服务端流程**（纯逻辑落 `src/texlate/server/srccut.py`，文件 IO 走 `asyncio.to_thread`——reader.py 同款）：

1. `deps.get_task`（id 形态+存在+tenant 三检）；`kind=="arxiv_html"` 早拒 422。
2. `ChunkRepo.spans_by_seqs(task_id, seqs)`（新 repo 方法，列集 `seq,chunk_id,src_file,byte_start,byte_end,kind,src_text`——`_PREVIEW_COLS` 无 span 列故新方法不复用）。
3. 逐行取源切片，**三级回落链**：
   - `tasks/{id}/base/{src_file}` → `read_bytes`→`decode_tex`→`text[byte_start:byte_end]`（**字符偏移切 str，不是字节**——列名谎称，cl-seq-map 实测非 ASCII 文件 367/400 行 char≠byte）；
   - base 缺席（slim 清过）→ `src.tar` 同 relpath 成员切片 + **校验头**：切片归一化前缀须与 `src_text` 归一化头匹配（`main.tex` 被 normalize 注入 ~1.5KB 头致 span 漂移，不匹配即弃此臂）；
   - 皆败 → `dual.json` `chunks[seq].en` + `ph` 反掩码重构（实证 exact 7/8、norm-unique 8/8），置 `approx:true`。
4. `mode=sent` 且 anchor 在场：anchor 归一化（空白折叠+智能引号归一+`[[TYPE_n]]`↔ph 体展开对照面）后 difflib 在边界切片内定位（cl-arb-sel anchor 臂 med 误差 0）；切点外扩至 `sentence_ends` 最近界；锚定置信不足（最长匹配块 < anchor 归一化长 ×0.6）→ 该侧退 whole。**置信不足不报错**——降级档即正确行为。
5. `gaps`：同 `src_file` 相邻 chunk 间插入 `text[prev_end:next_start]` 原文（注释/`\section`/`\label` 料，占文件字节 15–37%），单 gap 截 2KB；跨 `src_file` 插 `% ── file: {src_file} ──` 注释界标（LaTeX 安全）。
6. 切片 `

` 连接；输出总量帽 256KB（超 → 截尾 + `truncated:true`）。
7. 审计：`files` 回包切片涉及的 src_file 列表——前端 toast/调试可溯源。

**并发/一致性**：只读端点，无写；DB 行+base 树在终态后冻结（chunk 重译不改 span/src_text），无需锁。在飞任务（translating 中）chunks 已建，可服务——LivePane 场景自然覆盖。

## 测试计划

**vitest（`web/src/test/`）**：

- `sanitize.test.ts`：补断言 `alttext` 存活、`semantics`/`annotation` 仍剥（现有 mathMl 用例旁加）。
- `copylatex.test.ts`（新）：math 提取三径（alttext 优先/annotation 次/全无→fallback mock）；`selChunks` 在含嵌套锚+无行锚（bibitem/figure）夹具上的 seq 区间正确（ss-dom-sel 普查形态）；anchor 抽取截帽；pdf 模糊锚定对 dual 夹具命中预期 seq 区间；剪贴板兜底路径。
- `selBar.test.ts`（新）：拖选抑制、pointercancel 救援、离屏隐藏、cross-pane 锚位。
- i18n parity 由既有 `i18n.test.ts` 自动覆盖。

**pytest（`tests/` 或 `src/texlate/server` 测试面）**：

- `spans_by_seqs` 行集/排序/空集；
- 端点：whole 档基线切片 == `decode_tex(base/file)[start:end]` 逐字节；sent 档对带句中切点的 anchor 外扩句界；anchor 失配退 whole；gaps 含块间注释；跨文件界标；arxiv_html 422；seqs 超帽 400；base 缺席走 tar/approx 臂（造无 base 有 tar 与全无两 fixture）；租户 404。
- `sentence_ends` 对 raw tex（无 token 编码）回归用例。

**e2e（`web/scripts/copylatex_verify.mjs`，cite_verify.mjs 同款 Playwright 骨架）**：真实任务双链——dom 视图点公式出卡+复制内容含 `\frac`/`\begin`；html 视图选段落→条→剪贴板含原始宏调用；zh 侧选区退整段档；Esc/滚动收卡；零 console 错。环境坑记注：`TMPDIR=~/.cache/pw-tmp` 防 /tmp tmpfs 撑爆 chromium（ADR-0021 实证）。

## 工作量与分期

| 期 | 内容 | 估时 | 依赖 |
|---|---|---|---|
| P0 | sanitize 一行 + 公式源卡（dom+html/live）+ i18n + vitest + e2e 公式面 | 2–3 天 | 零后端；mathml-to-latex 懒载打包条目录 package.json |
| P1 | 后端端点+repo 方法+srccut 纯件；html/live 选区条（whole+sentclip+gaps）；e2e 选区面 | 3–4 天 | P0 的 SelBar/clipboard 件可复用 |
| P2 | pdf 视图：chunks 透传+模糊锚定整段档；zh 侧选区接通；`with_defs`（若 defs.json 持久化同期落） | 2–3 天 | P1 端点；锚定质量需 20+ 真实选区样本复验 |
| P3（研究项，另行裁决） | pdf 精确档：splice 期 accsupp `ActualText` 宏包裹（spike：宏回卷覆盖 98.1%，roundtrip 净）→ pdf.js 文本层出 sentinel → 边界级映射；dom 链「复制块 HTML」旁路 | 不定 | spike 已证载体机制；需新评估编译兼容面 |

## 风险

1. **byte_start/byte_end 列名谎称**（cl-seq-map）：实为 Python str 字符偏移。切片必须 `decode_tex` 后对 str 切——对 bytes 切在非 ASCII 文件必错（实测 367/400 行分叉）。文档/代码注释要钉死，改名是 breaking 另议。
2. **坐标系=base/ 归一化树**：normalize 注入 ~1.5KB 头+改写 `\input`，`src.tar` 回退对被动过的文件 span 漂移——必须带校验头闸（§后端 3），main 文件为高危位。
3. **展开面 vs 原始面**（cl-macro）：`src_text`=L1 展开面，`[[EXPAND_n]]` 只活在 ph_map identity 轨；raw 切片保原始调用点（`\salve{}`）但**宏定义不在切片内**——粘到别处不编译。v1 接受（忠实复制语义）；P3 `with_defs` 补。
4. **KaTeX annotation ≠ 源切片级精确**（cl-dialect）：annotation 是 phText 喂入体剥界符形——`$$\begin…$$` 包裹被剥、语义等价但非逐字节；且源体本身 25% 逐公式 KaTeX 不可渲（74/83% 干净率）不影响复制（源照旧给）但**不要在卡里做「预览渲染」承诺**。
5. **选区条交互暗坑**（ss-floatbar 全谱）：拖选期泄漏定位、missed pointerup stuck、条自身被拖选、pane margin 移动无 scroll 事件 stale——§交互规格的对策（抑制/救援/user-select/RO 重定位）逐条对应实测坑，不可省。
6. **dom 链锚≠seq**（ss-dom-sel）：`[data-chunk]` 值是 block key（`S1.p4`/`b5`）且 163 锚仅 113 有 chunk 行（bibitem/figure/authors 无行），DOM 序≠seq 序——dom 链绝不走 seq 端点，只做公式卡（alttext 在元素自身，无锚依赖）。
7. **approx 臂语义**：ph 重构缺注释/原始空白——`approx` 旗标必须透出到 UI toast，防用户把重构体当源引用。
8. **base/ 被 slim**：`slim_task_dir` 对 done/partial 保留 zh/base 是现行约定但实证 2/10 任务 base 已清——回落链是硬需求不是可选项。
9. **安全面收敛**：alttext/切片内容一律 textContent 入 DOM；端点走 `get_task` 租户闸+`_read_body` 4MB 闸+seqs/output 双帽；无新外发请求面（mathml-to-latex 纯本地 wasm/js）。
10. **剪切板权限**：`navigator.clipboard.writeText` 需 secure context+focus——iframe/失焦退化到 execCommand 兜底；失败给「手动复制」卡内可选文本态而非静默。