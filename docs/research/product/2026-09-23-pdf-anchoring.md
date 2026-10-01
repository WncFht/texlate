# PDF 窗格功能锚定可行性调研

> **结论**：给 PDF 做这些功能**难度不大**。选区/右键/浮条/键位四入口早已穿透 textLayer（PdfPane 是「半接线」不是盲区），唯一真缺口是「PDF 位置 → chunk seq」一条映射。三条路按 ROI 排：**C 模糊锚**（已在产线跑 copy-latex pdf 臂，升级 ~0.5-1 天，存量任务零重编全亮）→ **A SyncTeX**（~1 周，新编译任务确定性 chunk 级锚，两引擎 flag 通路现成）→ **B marked-content 编译期注锚**（3-5 天，唯一确定性句级方案，双引擎+pdf.js 已端到端实证）。**否决**：ActualText 零前端复制（pdf.js 6.3.289 抽取不消费，PR#20014 仍 open）、tagpdf 全标签（xelatex 不推荐 + 编译 2-7× 膨胀）、改产品形态做页内覆盖翻译（业界天花板实证 Moonlight 双 viewer 只有页级滚动同步，无段级协议可抄也不必抄）。
>
> **状态**：**已落地**——B 路 marked-content 注锚为主锚已实装（`823107dc`+`f95b47a6`，含 L2 归因闸修复），C 模糊锚升级随 UX 落地波已实装；A SyncTeX 未做（按原裁决优先级排后）。调研本体：13-agent 工作流 wf_55ea5568-3cf（3 内勘 + 5 外研 + 综合矩阵 + 4 条高风险论断对抗核验全数 confirmed）。实施细节见 `../../dev/projects/2026-09-23-pdf-seq-anchors-impl.md`
> **日期**：2026-09-23
> **原始产物**：`tmp/pdf-anchoring-20260923/full-result.json`（全量结构化输出）、scratch 实证件同目录

## 1. 问题框定

Wave A-D 落地的阅读器功能（Copy LaTeX、句级对齐、find-usages、选区浮条/右键）依赖「指到的元素有稳定身份」：`data-chunk`(seq)/`data-sid`/`alttext`/`data-key` 锚点只存在于 DOM 视图。`arxiv` 链任务只产双 PDF（`view:"pdf"`，`routers/reader.py:85`），DOM 功能全灭。

关键前提：**双 PDF 都是我们自己编译的，LaTeX 源在 `base/` 里，chunks 表有 `(src_file, byte_start, byte_end)`（decode_tex 后字符偏移）**——比所有无源竞品的锚定起点严格更强。

## 2. 内勘发现（texlate 现状）

### 2.1 编译链（i-compile-chain）

- 编译落点：`worker/compile.py:1146-1201` `_compile_zh`（copytree zh→build-zh → `eng.compile` → res.pdf→任务根 zh.pdf）；en 同款 `_compile_en` :486-516。
- **SyncTeX 通路今天已通**：xelatex `_split_flags` 直通（`_xelatex.py:310-340`，只拒 output/jobname 类重键）；tectonic `_TECTONIC_FLAG_MAP` 显式映射 `-synctex=1→--synctex`（`_tectonic.py:44-47`）。
- `.synctex.gz` 落 build-zh——**必须 harvest 到任务根并注册 files.kind**，否则 `/api/tasks/slim` 连 build-zh 一起清（tests/test_app_endpoints.py:1515 实证语义）。`_builtins_shim.py:770` 已把 .synctex.gz 列入瞬态件不挡 relocate。
- **spliced zh.tex 零 chunk 标记**（实测 t_d7c669e8b3c92149/zh/main.tex 仅 preamble 有 `% texlate:` 注释）——seq→zh 行区间侧车图须插桩 `reconstruct.py:372-391` 记账（pieces 无缝平铺，post-pass 只插空格/{}/偶发换行，偏移增量有界可追）。
- fixloop `regex_rewrite` 改 .tex 经 `_sync_fixed_sources` 回灌 zh/（compile.py:139-164）——行图须在其后生成或按文件标 stale 降级；en 侧 fixloop 不回灌 base（pristine 约定），被救回任务的 en 锚降级。

### 2.2 seq→行映射（i-seq-line-map）

四环中三环已就位：① seq→(file，字符区间) 已在 chunks 表且生产验证；② 字符偏移→行号是纯 `\n` 计数；④ (file,line)→seq 区间包含查询平凡。唯一缺口 ③ PDF 坐标→(file,line) 靠 synctex/注锚补。

实测 `.synctex.gz` 格式：Input 表 tag→绝对路径 + 逐页 `{p` 块内 (tag,line,x,y,w,h,d) 记录；`synctex edit -o page:x:y:pdf` 反查返回 Input+Line（y 原点 top-left、bp 单位，pdf.js convertToPdfPoint 出 bottom-left 需翻转）。本机 `/usr/bin/synctex` v1.5 可用；自写解析器 ~150-200 行。建议服务端一次性预解析成紧凑 JSON 产物（synctex.gz 体积≈PDF 乃至 2×，格式非公开契约——man 5 明言）。

### 2.3 PdfPane 现状（i-pdfpane-surface）

已有三层锚体系，**功能缺的不是入口是数据**：

- named-dest 层：idle 分片 `getAnnotations` 收 Link annot dest 进 destNames（PdfPane.tsx:286-314）；`goToDestination` 包装成唯一跳转漏斗（:672-706）；mirrorDest/posDest 双向桥（:435-508）。
- 悬浮卡委托：viewer.container 上 pointerover/click capture/focusin 收 cite.* 锚（:712-869）。
- 选区层：textLayerMode=ENABLE；hitctx bodies 已含 `.textLayer`（hitctx.ts:358）；**sel.copyTex 已在产线跑 difflib token 锚定把 PDF 选区文本映射到 dual.json seq（copylatex.ts:271-307）**——「PDF 选区→seq」不需几何已被证明。
- 死项：`cite.usages` pdf 臂是静默 no-op（ReaderView.tsx:214 附近），`getDestinations()`「批量恒 0」为过期观察（实测 zh.pdf 返回 103 dest）。

## 3. 外研发现（业界怎么做）

### 3.1 SyncTeX (e-synctex)

- 机制：引擎内嵌「排版盒→源位置」映射，把每页嵌套盒树（vbox/hbox/glue/kern/math）连同 (Input tag, 行号，列号)+sp 坐标写入 .synctex.gz。逆查=页坐标→最小包含盒→(file,line)；正查=(file,line)→盒矩形集。**列号恒 -1，实际粒度=源行**。
- 先例：Overleaf/TeX Live 壳 `synctex` CLI；JS 侧 LaTeX-Workshop synctexjs.ts、wasmtex/synctex（MIT，corca-ai 仓）。
- 易错点：同一源行多 chunk 不可分（需 textLayer 词命中消歧，LW textBeforeSelection 法）；align/多行公式环境整体塌到 `\end` 行（tex.sx#453517）；.bbl/.aux/TOC 的 Input tag 指向生成文件须白名单过滤；多源行塌同一显示行可借 glue/kern 子记录按 x 分。
- **对 texlate 恰好合身**：arXiv 源段落多为整段一行 → 一行即一 chunk；zh 侧须 splice 行图记账（唯一大件）。

### 3.2 无源 PDF 锚定三路线（e-reader-anchors）

- **quote 锚（hypothes.is 最成熟）**：TextQuoteSelector{exact+ 前后 32 字}+TextPositionSelector hint；逐页剥空白→Myers bitap 近似匹配→50/20/20/2 加权打分→NFKD 回映 textLayer Range。文档漂移场景孤儿率 22-27%（arXiv:1512.06195）；跨页选区直接不支持。
- **坐标锚**：Zotero {pageIndex,rects[]}+text 冗余，绑死同一文件。
- **结构/编译期锚**：ScholarPhi 用 TeX 注色双编译 + 像素 diff 才拿到段锚——**我们一行 `\special` 就有等价物**。
- 文本层失准面：连字 U+FB00 系（须 NFKD——我们 normSel 未做）、行尾断词、数学符号字体 glyph soup、双栏抽取序交错、ToUnicode 缺失件全灭。

### 3.3 双语 PDF 对照形态（e-bilingual-pdf）

- 原位派（BabelDOC/PDFMathTranslate/DeepL）：解析 content stream 逐字符收 Tj/TJ+CTM 建 IL，锚=编译期对象身份，dual 输出只做页级并置/交替，**无交互锚协议**。
- 重排双 viewer 派（Moonlight）：DocLayout-YOLO 检测→重排译文 PDF→第二 viewer **仅页级滚动同步**——与我们现有 landmarks sync 等价。「两份独立排版 PDF 之间段级对应」无人做也无需做：我们的 chunks 字节偏移严格强于检测框。

### 3.4 tagged PDF / marked content (e-tagged-pdf)

五条通道可行性排序：

| 通道                                                              | 判定                                                                                                                                                                                                     |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| marked-content 自定义 tag（`\special{pdf:code /TLXC42 BMC}…EMC`） | **主路线**——pdf.js `includeMarkedContent:true`（viewer 本来就开）透出 tag/id，TextLayer 自动包 `span.markedContent`（带 MCID 自动写 DOM id）。双引擎已实证：xelatex+tectonic（xdvipdfmx 血统）均原样落流 |
| named dest（`\hypertarget`/`pdf:dest`）                           | 点锚，适合跳转/滚同步，表达不了区间；dvipdfmx 回收未引用 dest 须 `dvipdfmx:config C 0x10` 保底（tectonic 靠 PR#953 才支持，裸 pdf:dest 路须实测）                                                        |
| 隐形 Link annot（`pdf:bann/eann`）                                | 天然跨行跨页拆分，跨页高亮兜底                                                                                                                                                                           |
| /ActualText                                                       | **死路**——pdf.js 不消费（已核验 vendored 6.3.289 源码：仅 getStructTree alt 回退 + 写回路径触及），「复制 PDF 文字直接得 LaTeX」零前端方案不存在                                                         |
| 完整 tagpdf 结构树                                                | **否决**——lualatex 才成熟、xelatex 不推荐、编译 2-7× 膨胀                                                                                                                                                |

- BMC/EMC 是 whatsit：只能落句/段边界（插词中断连字/kerning/抑制断词）；verbatim/数学/xobject 内部禁入；chunk 跨页续页成洞（页尾 BMC 未闭合 pdf.js 容忍丢弃）——句级注入把跨页率压到极低 + bann/eann 兜底。
- MCID 无 StructParents 是灰色用法（verapdf 会叫）；保守做法只读 `item.tag` 自建 seq 映射。

### 3.5 pdf.js API 面（e-pdfjs-api）

- 坐标桥：`Range→getClientRects→pageView.viewport.convertToPdfPoint→quadPoints`，autolinker.js 的 calculateLinkPosition/textPosition 是同构蓝本（~80+45 行可抄）；高亮走 CSS Custom Highlight（Baseline 2026-03）或 overlay div（~50 行）。
- 易错点：跨页选区需自拼；textLayer 懒渲染页无 textDivs（getTextContent 不等渲染可绕）；findController 高亮注入改写 textDiv DOM 使 Range 端点偏移须按 div.textContent 树走；页文本偏移口径 = items.str 拼接 + hasEOL 项插 `\n`（前后端须同口径）。
- 结论：前端「选中→page+quads+ 页内偏移」只差 ~300-400 行胶水；真正工作量在后端锚数据供给。

## 4. 功能×方案难度矩阵

| 功能              | 方案                  | 难度                                       | 判定                                                           |
| ----------------- | --------------------- | ------------------------------------------ | -------------------------------------------------------------- |
| copy-latex        | C textLayer 模糊锚    | 已在产线；升 hypothes.is 评分+NFKD ~0.5-1d | **v1 兜底 + 存量唯一通路**；glyph-soup/连字/跨页选区失准       |
| copy-latex        | A SyncTeX             | ~1 周                                      | **v1 主路**——确定性 chunk 级；en 侧近免费，zh 侧行图是唯一大件 |
| copy-latex        | B marked-content      | 3-5d                                       | **v1 最佳精度**——span 级锚，新管线推荐                         |
| copy-latex        | ActualText            | —                                          | **已证伪**                                                     |
| copy-latex        | D DOM 对照窗格        | ~1d                                        | 补充兜底，仅 arxiv_html 链                                     |
| sent-align        | C 双向模糊锚          | ~1 周                                      | 无重编路径，精度有顶（heading 并句漂移——data-chunk 可免）      |
| sent-align        | A SyncTeX             | 随骨干 + 数天                              | 给 chunk 级跳转/高亮；行粒度给不了句级                         |
| sent-align        | B 句级注锚            | B 基建 +1-2d                               | **二期唯一确定性句级**                                         |
| find-usages       | F 现有 dest+ 源侧索引 | 1-2d                                       | **v1 最快**——修死菜单项 + 拓 CITE_SEL 词表；59.6% 天花板       |
| find-usages       | A forward lookup      | 随骨干+~1d                                 | 补无 hyperref 文档覆盖                                         |
| find-usages       | B 注锚                | 搭 B 车 ~1d                                | 二期确定性                                                     |
| 划词菜单/FloatBar | 现状                  | 已穿透 textLayer                           | 菜单项随锚 lane 免费                                           |
| 全部              | E 页内覆盖翻译改形    | 周级 + 产品重做                            | **不值得**——无范式且劣于源侧信息                               |
| 全部              | A+B 组合              | ~1-1.5 周                                  | **目标态**：确定性锚 + C 兜底存量                              |

## 5. 推荐路径

1. **第一步（1-2 天，存量全亮）**：修 cite.usages pdf 死臂（ReaderView.tsx:214）、CITE_SEL 拓到 figure./equation./section.、pdfSeqsForText 升 hypothes.is 式评分（prefix/suffix+ 位置 hint+NFKD）、range→quads 几何桥。四功能 PDF 臂以 C 精度上线，**零重编覆盖全部存量任务**。
2. **第二步（~1 周，确定性骨干）**：双引擎 -synctex=1/--synctex + harvest 注册、reconstruct 插桩产 seq→行区间侧车图（fixloop 回灌后 anchor 校验+difflib 修复）、服务端预解析 synctex.gz→页索引 JSON、PdfPane 点→seq+seq→rects。
3. **第三步（+3-5 天，二期精度层）**：marked-content 注锚——chunk 界 `/TLXC<seq>`、句界 `⟪S<n>⟫` 作 BMC/BDC tag，复用第二步同一插桩点；前端读 `span.markedContent`。解锁真句级 sent-align 与 span 级 copy-latex/usages。**scratch 已双引擎+pdf.js 端到端实证**。
4. **补充（各 1-2 天）**：段级 dest 注入扩跳转覆盖；D dual.json DOM 对照窗格作为 arxiv 任务全功能兜底视图。

## 6. 已核验风险登记（4 条对抗核验全 confirmed）

- pdf.js 6.3.289 不消费 ActualText——`getTextContent` 的 beginMarkedContentProps 只出 {type,id,tag}，textLayer 复制只用字形 str；上游 PR#20014 仍 open。
- tectonic 0.15.0 `\special{pdf:code}` 实证：BMC/BDC+MCID 原样落内容流（xdvipdfmx 血统）；pdf:bann/eann 与 config special 其余项未逐项实测。
- xelatex synctex CJK 实证：ctex demo 6 次反查全中正确文件行、Column=-1；但行右三分区/行尾 glue 有误归因（synctex#20 已知盒边界漂移）——行粒度可用，真实 zh.pdf 命中率分布待回归。
- BMC/EMC 排版影响 **已量化（§7 Exp-B）**：段边界注入零漂移、段内注入该行 ≤2.3bp 水平微移（xeCJK 标点挤压被 whatsit 打断的同类效应）；跨页 BMC 不配平机制实存，须 annot 兜底。

其余记录在案的不确定项：zh 行图对 fixloop 回灌的修复成功率、CSS Custom Highlight 未在目标浏览器矩阵实证（overlay div 兜底需预留）、pdf.js 私有面依赖须收敛进单 adapter。zh.pdf textLayer 抽取质量与 synctex 保真度已量测（§7）；synctex.gz 实测 ≈PDF 体积 12%。

## 7. 实验实证（2026-09-23 下午，真任务实测）

三实验全部在真实任务 `t_d7c669e8b3c92149`（51 页 zh.pdf + en.pdf + dual.json 400 chunks）与 7 个存量任务（2947 chunks）上跑完。脚本与报告在 `tmp/pdf-anchoring-20260923/exp/`（`expPdfAnchor.test.ts` 在 `web/src/test/`）。

### Exp-C 模糊锚（路径 C 天花板量测）

- 产线 `pdfSeqsForText` 逐字串定位：仅 **33.6%** chunk 的 zh 文本在抽取文本中逐字可寻——失败主因不是抽取器而是 **dual.json 里的 LaTeX 残留**（`\textbf{`/`\emph`/`~`/`\%`/`\ref` 占位符）。
- 定位成功处匹配器精度 **~99.8%**——评分器本身没问题。
- 加 texStrip+token 级次定位器（最长连续 token 命中，cov≥0.5）：覆盖率 **33.6% → 64.9%**，命中率不降。剩余 ~35% 是数学/引用断口切碎段，需容忍断口的对齐（hypothes.is prefix+suffix 式），C 路可再压榨但存在硬顶。
- 副产品发现：命中区间用闭区间 min..max 会在标题页过度膨胀（span 最大 75）→ 需连通分量聚簇替代区间夹取。

### Exp-A SyncTeX（路径 A 保真度量测）

- `-synctex=1` xelatex 两遍编译零适配，synctex.gz = **398KB / PDF 3.3MB ≈ 12%**（调研期「≈PDF 体积」估计过悲观）。
- 正向（源行→页）40 探针 **80% 页级正确**，误差集中在跨页段。
- 反向（页内坐标→行）40 探针：**87.5% 落在 ±2 行内的 chunk 宿行**；5 个真 miss 全部落在参考文献/宏展开区——恰好都是非 chunk 区，业务上无损。
- **同行多 chunk 负载：45/326 宿行（13.8%）共享 ≥2 chunk，单行最多 6 个**——行粒度须配第二消歧器（行内 token 偏移）。
- 结论：A 路作「页 + 行邻域」粗锚可靠，chunk 级消歧须叠 C 的行内匹配。

### Exp-B marked-content 注锚（路径 B 端到端）

- `\special{pdf:code /TLXC<seq> BMC}…\special{pdf:code EMC}` 在真实 zh 文档两处注入（一处纯文本段 p8、一处含行间公式定理段 p20）：**编译零告警、PDF 体积不变、51 页逐词 bbox 对比仅注入行 12 处 xMin/xMax ≤2.3bp 水平微移**（whatsit 占位的已知效应），段边界注入零漂移——证伪了「BMC 排版影响未量化」的悲观预期。
- pdf.js `getTextContent({includeMarkedContent:true})` **直接吐出 `beginMarkedContent tag=TLXC885/TLXC1443` 边界项**，中间夹 57 个 text item 正好覆盖整段——item 索引→textDiv→quads 链路全通，不依赖 DOM span。
- 附带发现：文档本已含 640 个 `Table/NonStruct` MCID 标记（宏包产物），共存无冲突。
- 约束确认：whatsit 只能落句/段边界（段内注入造成该行水平微移）；跨页 BMC 不配平问题实存，须 annot 兜底。

### 实验后路径裁决

**B 路可提前**：端到端实证一次通过、零排版代价、唯一确定性 seq 级锚。建议修订原 C→A→B 顺序为 **C 快速铺存量（仍值得，1-2d）→ B 直接做主锚（跳过 A 的 synctex 解析基建）**：A 的行图插桩件与 B 共用同一注入点，但 B 不需要 synctex 解析器与 harvest 管线件，工程量更小且精度更高。A 降级为「不想要注锚 PDF 时的退路」。

## 附：方法与产物

- 工作流 `wf_55ea5568-3cf`（13 agent：3 内勘只读 + 5 外研 + 1 综合矩阵 + 4 对抗核验），~1.22M subagent tokens，~2.9h。
- 全量结构化输出：`tmp/pdf-anchoring-20260923/full-result.json`；scratch 实证件（synctex demo、marked-content 双引擎验证）在同目录。
- 关联调研：`2026-09-22-moonlight-reverse.md`（Moonlight 页内覆盖/双 viewer 实证）、`docs/dev/projects/ux-impl-2026-09-22/` 路线图 §8（DOM 侧已落地功能清单）。
