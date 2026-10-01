# layoutqc v2 —— 版面质检全面升级（内部审计 × 外部调研 × 状态条件保留）

日期：2026-09-23。本文档由三路输入综合而成：(a) verification-surface fork 的全链路审计；(b) splice 机制 fork（reflow + 未消费信号）；(c) 5-lane 外部调研 workflow（BabelDOC / MinerU·olmOCR·Marker·Docling / 度量准则 OmniDocBench / render-diff / 仪表化编译）。取代 v1 的 L1/L2/L3 草案，是重建 bench 前检验升级的准绳。

## 0. 一句话

现在的验证只证明「pdf 存在 + 错误少 + 有中文」——版面几何零覆盖；而外部**没有一家**在推理期做渲染几何 QC（BabelDOC 干脆没有出货后检查），所以我们的目标不是抄谁，而是把我们独有的优势（手里握着源 .tex 真值 + en 基线 PDF + 双臂都重编）换成一套分层检测电池：T0 每篇必跑（bbox 几何 + 日志信号 + 退化兜底），T1 bench 跑批时加 raster + BIoU，T2 上 `\pdfsavepos` 发射侧真值（已实证）+ LLM 评审。

## 1. 现状：每道门的 status 实际证明什么（fork 审计确认）

| stage   | status 证明                                                                                                                | 盲区                                           |
| ------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| xlat    | 网关调用完成、译文非空（`e2e_real/xlat.py::_xlat`，delivered 谓词在 `pipecore/state.py`）                                  | 译文质量（qualbench 另管）                     |
| compile | judge.py:96-122 四件套：pdf 存在 ∧ `!`≤3 且首错非 DIRTY_FIRST ∧ 红线 warning 零命中 ∧ CJK≥20 字符 + pdf_bytes≥50% baseline | **全部版面几何**：overfull、浮体漂移、表格重合 |
| fixloop | 救火尝试，终态继承 compile 判定                                                                                            | 修后版面零测量                                 |
| base    | en 基线对照编译                                                                                                            | —                                              |

- 账本实证：492k records 中 31% 带 sig，sig 族**无一版面几何类**；`acceptable_pdf` 6274 + `best_effort_pdf` 4340 只记"出了 pdf 但降级"。
- 刻意失明：texlog.py:112 注释明说 overfull 尺寸转储被滤出词法；`_RUNAWAY_VBOX_RX`（logparse.py:68）只用于超时归类，不进 verdict；redlines 无任何 overfull 条目。
- mechanisms.jsonl 263 条机制中 layout 类仅 ~15 条，全是 caption/路径 DSL 级，**无一条验证渲染产物**。
- e2e_real-2 实证：zh 臂终态 30/37 clean（81%）反超 en 基线 25/38（66%）——fixloop 手术有效，但这 30 篇里有多少版面缺陷没人知道。

## 2. splice 机制决定的五类盲区（splice fork 确认）

splice = **reflow 重编译**（译文写回 .tex 整树重编，`pipecore/translate.py::translate_tree_run`），非 BabelDOC 式 overlay。zh 树注入两件版面手术（compile/layout.py）：FLOAT_SIZING（超高浮体 \resizebox*，并发 `TeXlate-Float-Fit` typeout——**发射了没人消费**）、demote_wrapfloats（wrapfig→普通浮体，嵌套/条件内的逃过）；TABLE_FITTING 0930 拔除（成对钩 ended-by 毁编 ~1200 事件，钳宽归 fixloop `tabular_fit` 源级跨度包）。

| 缺陷类   | 机制                                                  | 现状                         |
| -------- | ----------------------------------------------------- | ---------------------------- |
| 表格重合 | 绝对定位元素（tikz overlay/textpos）内容变长→物理重叠 | **零覆盖**                   |
| 图片乱飞 | zh 段落长度变化→float 重锚异页（reflow 固有）         | 只预防不检测                 |
| 表宽溢出 | 裸 tabular + 定宽列 + zh 文 → overfull 单元格互压     | **零覆盖**                   |
| 宽度溢出 | FLOAT_SIZING 只管超页高，includegraphics 超宽不缩     | **零覆盖**                   |
| 丢图     | graphicspath/复制缺失                                 | 已检（missing_graphic 红线） |

## 3. 外部调研：别人怎么做（5 lane 全回）

### 3.1 最重要的发现：渲染几何 QC 是无人区

四个生产级 parser（olmOCR / MinerU / Marker / Docling）+ BabelDOC，**没有一家在推理期对渲染产物做 overlap/overflow/float-drift 检查**——所有 QC 都是「parse 结构 vs GT」。BabelDOC（9.6k star，overlay 路线）出货后零自动检查，issue #615 自认「静默丢旋转字形数月无人发现」。olmOCR-2 的 30,381 条单测 reward 也只测文本在场性。**我们的场景（GT=源 .tex，产出=重编 PDF）本身没被任何现成方案覆盖——这正是可以做出独有资产的地方。**

### 3.2 BabelDOC lane（overlay 阵营的教训）

- 它的 fit 策略值得借：scale 阶梯 −0.05/−0.10（floor 0.1，<0.7 尝试向自由空间扩 box——`get_max_bottom/right_space` 扫所有邻块），rtree 碰撞清扫。
- 出货 QC 只有论文里的评测 harness：**BIoU**（同源 parser 抽 en/zh 两侧元素 box → 按阅读序 + 空间邻近匹配 → IoU）、**UTB**（未翻译文本块计数/页）、Gemini judge 四维度 rubric（LF/TP/VA/TC）。
- 教训：**never-silent 规则**——每个被丢/溢出的元素必须 log+count；**no-op roundtrip 门**（`--only-parse-generate-pdf`：不改一字重编，分离 splice 引入缺陷 vs 源文件固有缺陷）。
- 我们的 overlap-pair 回归计数法直接抄 #615：重叠文本块对数（>5% 小盒面积），zh vs en 基线对比。

### 3.3 parser 四件套 lane（可偷清单，按可落地度排序）

1. **olmOCR BaselineTest**——纯正则退化检测（重复 n-gram≤5、禁用字符、空页字符下限）：零依赖，直接落在 zh pdftotext 上。
2. **Docling ConfidenceReport 形状**——component 分 + mean/low-percentile 评级，页级 + 文档级：直接当我们的 QC 报告 schema。
3. **olmOCR absent/order 测试**——「源行未翻译残留」（absence）+「章节序保持」（order），不需要 GT，源就在手里。
4. **MinerU drop-and-count**——bbox-fallback/dropped 计数器：映射成注入块丢弃记账。
5. Marker escalation（低置信段→重译）、olmOCR test-mining（从源 .tex 自动生成每篇检查清单）——中期项。

### 3.4 度量准则 lane（OmniDocBench 家谱 → 配对场景适配）

| 准则     | 抓什么               | 我们的适配                                                                                                                            |
| -------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| NED      | 文本丢失/乱序/tofu   | **YES 核心**：zh-PDF pdftotext vs zh-src 分段逐段比（比准则原版更强——我们有精确期望串）；en-PDF vs en-src 定抽取噪声底                |
| TEDS     | 表格 cell 合并/塌列  | **源侧 YES**：`latex/tables/` 已解析 tabular → TEDS(src-tree, zh-tree) 查 LLM/fixloop 是否改了表结构；渲染侧不建 parser，用 bbox 代理 |
| IoU/mIoU | 版面漂移/越界/丢浮体 | **YES 核心**：`pdftotext -bbox`/`pdftohtml -xml`（poppler 子进程，既定边界）——zh bbox vs 页框 + vs en bbox                            |
| ARD      | 阅读序/浮体位移      | 元素清单序 vs zh-PDF 抽取序；reflow 后浮体合法漂移 → warn 级不进门                                                                    |
| CDM/BLEU | 公式渲染/n-gram      | **SKIP**：math placeholder 已做字节级 identity（L0 multiset），比 CDM 强；精确串使 BLEU 严格弱于 NED                                  |

**最强偷法——SyncTeX = 我们的 page-program**：WeVisDoc 的 DOM 双编译（render + targets），我们手里有更好的 DOM——.tex 树本身。zh 编译加 `-synctex`（tectonic 支持）→ 每个 PDF glyph/box 映射回 zh 源行 → 映射到 segment → **元素↔bbox 真值表，零 OCR**。此后「渲染对了没」全是查表：presence（NED）、position（IoU vs en 侧 bbox）、order（ARD）、extent（bbox 在页框内）。OmniDocBench 值得再偷：component 分制 + per-page/per-attribute 拆分 + per-stage timeout。

### 3.5 render-diff lane（页对齐栈 + 成本实测）

- en↔zh 像素 diff 无意义（所有字形合法不同）；配对渲染买的是**几何对等**——margin、栏、图位、墨量、页数。
- **页对齐栈（有序）**：① `pdfimages` hash 锚点（实测 127 rasters/34pp 命中，免费）；② symbol-skeleton LCS（数字/引用/arXiv id/URL 翻不过去——pdftotext 抽取后 Needleman-Wunsch 对齐页序）；③ 仪表化 marker（`texlate://mark/n` link annot，零版面扰动，作 ①② 的验证真值）。
- 成本实测：pdftotext-bbox ≈6ms/页；pdftoppm gray PPM ≈0.12s/页@100dpi（流式 PPM 不落盘）；全语料双臂 ≈12 CPU·h ≈ 1h wall @12 核。依赖只有 poppler（judge.py 已在用）+ pillow/numpy bench extra。

### 3.6 instrument lane（发射侧真值——已端到端实证）

比 SyncTeX 更强的一手方案，已在 xelatex 上验证跑通（tmp/savepos-probe）：**让 LaTeX 自己吐出位置**。注入 `\pdfsavepos` whatsit + 专用 `\write` 流 → shipout 时落 `<stem>.txlm`（`MARK <uid> x=… y=… p=…` 行）→ 检测变成**解析文件**，不是猜像素。

- **钩子注入零改源**：`\AddToHook{env/<name>/begin|end}`——begin mark 落外层流=浮体锚点，end mark 乘 `\@currbox`=实发位置；figure*/table*/tabular*/longtable/equation*/align*/minipage/textblock 全覆盖（含 algorithm/lstlisting 自定义浮体）。
- **UID 必须冻结**：deferred `\write` 在 shipout 才展开——`\thefigure` 读到的是发排值，须 `\edef`+`\expandafter` 冻结（探针实证）。
- **BOX dims**：`\AddToHook{cmd/@endfloatbox/after}{\immediate\write…}` 取 `wd/ht+dp \@currbox` → 每个浮体真值矩形；`GEOM` 行给页框/textblock。
- **免费信号**：source 有 env 但无 MARK 落盘 = `lost_element`（measure-then-discard 试排盒天然无 mark，零误报）。
- 落点：clone `inject_float_sizing` 写法（layout.py:89-118 的 file-walk+sentinel 缝），`LAYOUT_MARKS` 块接 `prepare_chinese`(inject.py:670-714) 与 `base_condition`(e2e.py:289-301) → 双臂真值；`.txlm` 落在 compile cwd=main dir（`engine/_xelatex/main.py`）；开销 <1%。
- 风险已列：`\def` 伪 env 无 hook（覆盖率审计本身是信号）；`\@endfloatbox` 被 class 重定义→`\ifdefined` 守卫；moving-arg 内禁放 mark；tectonic 下 `.txlm` 落 out dir 需验路径。

## 4. 升级后检测栈：三层电池

### T0 —— 每篇必跑（~free，pdftotext-bbox + 日志 + 正则）

| 检查           | 方法                                                                   | sig                 |
| -------------- | ---------------------------------------------------------------------- | ------------------- |
| overfull 升级  | log 扫描 Overfull \hbox/\vbox 计数 + 最大 pt（阈值化 >50pt 或 >10 处） | `layout:overfull`   |
| Float-Fit 回读 | `TeXlate-Float-Fit` typeout 清单                                       | `layout:float_fit`  |
| 浮体丢失       | `Float too large`/undefined 引用 warning                               | `layout:float_lost` |
| 越界           | word bbox 出 textblock+4pt                                             | `geo_margin_breach` |
| 文本重叠       | word IoU>0.3 跨行（BabelDOC #615 法）                                  | `geo_text_overlap`  |
| 浮体挤页       | ≥2 连续有墨无词页                                                      | `geo_float_jam`     |
| 页数漂移       | zh/en 页数比 ∉[0.6,1.6]                                                | `align_page_count`  |
| 丢图           | image-hash 锚点缺失                                                    | `align_figure_lost` |
| 序断裂         | skeleton-LCS 非单调                                                    | `align_order_break` |
| 公式漂移       | 对齐窗口内 eq-line 比                                                  | `align_math_drift`  |
| 页眉丢失       | running head 缺席                                                      | `geo_header_lost`   |
| 退化兜底       | olmOCR BaselineTest（重复 n-gram/禁字符/空页下限）                     | `vis_degenerate`    |
| UTB 类比       | 残留英文块计数                                                         | `xlat_residual_en`  |
| 块丢弃记账     | 注入块/overflow 元素 count+sig（never-silent）                         | `layout:dropped_*`  |

### T1 —— bench 跑批层（zh+en raster @100dpi + BIoU）

| 检查      | 方法                                              | sig                   |
| --------- | ------------------------------------------------- | --------------------- |
| 空白页    | ink<0.1%                                          | `vis_blank_page`      |
| 墨团      | dark CC>40% 页                                    | `vis_ink_blob`        |
| 页中空洞  | 最大空 rect>30% textblock                         | `vis_void`            |
| tofu 群   | 空心矩形 CC 簇 / U+FFFD                           | `vis_tofu_box`        |
| 栏塌陷    | gutter 剖面 ≠ en 栏数                             | `geo_column_collapse` |
| BIoU 类比 | 同 extractor 抽两侧元素 box → 序 + 邻近匹配 → IoU | `geo_biou_low`        |
| 同臂 SSIM | 跨版本回归（同语言唯一合法像素 diff）             | `regress_ink_profile` |

### T2 —— 仪表化真值层（.txlm marks，已实证）

instrument lane 给的 sig 表（marks 存在时精确，缺席时降级到 T0/T1）：

| sig                      | 触发规则                                                    |
| ------------------------ | ----------------------------------------------------------- |
| `layout:float_drift`     | \|Δabspage\| zh−en ≥2（同 uid 跨臂比）                      |
| `layout:overlap`         | 同页 rect 交 >150pt² ∧ >5% 小盒（同 wrapfloat.py:66-67 阈） |
| `layout:offpage`         | rect 出页框 >2pt                                            |
| `layout:margin_break`    | 非浮体 rect 横向出 textblock >2pt                           |
| `layout:lost_element`    | 源有 env、无 shipped MARK                                   |
| `layout:order_inversion` | 同族元素序 vs base 成对逆序                                 |
| `layout:page_delta`      | 末页差 + 低文本页计数                                       |
| `layout:marks_absent`    | .txlm 缺失/空 → 降级 L2 poppler                             |

配套：新 `compile/marks.py` 解析器；LLM judge（BabelDOC rubric：LF/TP/VA/TC+UTB）页图对评审作 catch-all；**no-op roundtrip 门**（en 源不改一字走 splice 重编）分离 splice 引入 vs 源固有缺陷，兼作 T0/T1 误报率标定基线。

marks 的定位：**bench 默认开**（开销 <1%，双臂注入已设计好）——它不是抽样奢侈品而是 T0 的精确校准尺 + 本身即检出器；SyncTeX 降为备选（需要 element↔行级映射时才上）。

### 报告 schema（Docling 式）

per-doc QC 记录 = {component scores: text/geo/float/structure, mean_grade, low_grade(5th pct 页), per-page 表} → 落 records + triage 票。

## 5. 挂载设计

- 新 stage `layoutqc`：`e2e_real/__init__.py` stage 表注册（compile/fixloop 之后、mutates 收割之前），实现在 `e2e_real/layoutqc.py::_layoutqc`；`mutates=[]` 只读，读 workdir splice pdf + log + en base pdf。
- 记账：verdict 作 sig 挂终态格（`verbs/gate.py::pick_final` 的 compile/fixloop 末格）→ triage 自动聚类出票。
- 备选形态：独立后验 spec 走 vault.restore 读回（wrapfloat corpus 族已是此形态）——适合对存量 ~284 splice 篇回填检测出基线率。
- 检测器本体已存在：wrapfloat.py 的 `pdftohtml -xml` bbox 碰撞链（wrapfig fixture 实证检出能力）——泛化到全浮体/表格；bbox 阈值须按 zh 文本密度校准（行/块级而非词级，裸词级误报高）；marks 在位时 L2 退为兜底。
- marks 注入挂在 `prepare_chinese`/`base_condition`（双臂）；`.txlm` 随 workdir 收割进 vault（加进 mutates 白名单或直接读 workdir）。
- 顺手修：fixloop `upstream:no DONE compile row; upstream still in flight` sig 文案误导（实为上游未产出非竞态），e2e_real-2 六个终态 error 都是它。

## 6. 检验反过来定「成功即删」政策（磁盘×质量同一张表）

> **本节为计划版；定稿门定义与保留表在 §11。**

「成功」重定义为 `compile clean ∧ layoutqc clean`（T0 全过，T1 视跑批层级）。保留政策按终态分档：

| 终态           | 保留                                                                              | 稳态 MB/篇 |
| -------------- | --------------------------------------------------------------------------------- | ---------- |
| clean∧clean    | raw + zh tex + final.pdf + metrics + QC 报告；extracted/workdir/splice 中间件全删 | **~7-8**   |
| layout fail    | + splice 全档（复现/调参素材）                                                    | ~17        |
| compile fail   | + extracted + workdir 诊断面                                                      | ~20+       |
| fetch/前置失败 | 仅 catalog 行                                                                     | ~0         |

含义：现行「全 clean 也全留」(~26MB/篇) → 条件保留后 clean 篇 ~8MB，**且版面缺陷篇自动获得完整诊断料**——这正是 rebuild-plan-v4 §2.3 P3 政策能成立的前提（13k≈104G 贴顶需此项）。

副作用坦白：上 layoutqc 后 clean 率会**下降**（e2e_real-2 的 30 clean 里会翻出 layout sig）——缺陷一直在，现在才开始量。这是目的不是回归。

## 7. 执行序

1. **T0 日志侧**（~半天）：overfull/float-fit/float-lost 三信号进 verdict（纯 scan 代码）+ fixloop sig 文案修正。
2. **marks 注入**（~1d，先行——它是校准尺）：`LAYOUT_MARKS` preamble 块 + `compile/marks.py` 解析 + .txlm 收割；单篇 probe 已证可行，补 tectonic 路径验证。
3. **T0 几何侧**（1-2d）：`layoutqc` stage + wrapfloat 检测器泛化 + pdfimages 锚点 + skeleton-LCS + BaselineTest + UTB + dropped 记账；marks 在位的检查直接查表。
4. **存量回填**：后验 spec 对 vault ~284 splice 篇扫 T0（+双臂 marks 重编子集），出 layout 缺陷基线率（决定 T1 强度）+ no-op roundtrip 误报基线。
5. **T1**（1d）：raster 电池 + BIoU 类比；pillow/numpy 进 bench extra。
6. **T2**：LLM judge 抽样；校准集 ~50 篇（marks 真值可半自动产出标注）。
7. 保留政策随 layoutqc 落地生效：clean 篇瘦身、fail 篇留诊断 → rebuild Step 0 的磁盘手术至此闭环。

## 8. 未决

- bbox 碰撞阈值校准集：~50 篇标注（下标/上标/并排表格天然 bbox 相交）；marks 真值可半自动产出标注。
- T1 抽样率：待 T0 回填基线率出来再定。
- tikz overlay 类文档的表格重合 T0 可能仍漏——那类归 T1 BIoU/T2 judge。
- tectonic 下 `.txlm` 落 out dir（xelatex 落 main dir 已证）——marks 落地前验路径；`\@endfloatbox` 被 class 重定义时 BOX dims 缺失需 `\ifdefined` 守卫。

## 9. 调研来源

- OmniDocBench（opendatalab）：end2end.yaml / cal_metric.py / MGAM v1.6；paper arXiv 2412.07626
- BabelDOC（funstory-ai）：Typesetting.md、issue #615 缺陷目录、ACL 2026 demo（BIoU/UTB/Likert rubric）
- olmOCR-2：`bench/tests.py` 8 TestType + 30,381 单测 RLVR
- MinerU / Marker / Docling：middle.json confidence、`--use_llm` 栈、ConfidenceReport
- MonkeyOCR v1.5（arXiv 2511.10390）render-and-compare；WeVisDoc page-programs
- LayoutReader（arXiv 2108.11591）ARD

## 10. As-built 校准实录（2026-09-23 实跑标定）

§4 表是**计划**；本节是**落地真相**。全部语义经 e2e_real-2 三十一篇双臂实跑 + vault 284 胞单臂回填 + 逐页 PNG 人工核验标定。落地代码：`src/texlate/compile/marks.py`（发射侧）、`bench/py/specs/_layoutqc/__init__.py`+`_raster_child.py`（检测侧）、`tests/compile/test_layoutqc.py`（27 例）。

### 10.1 单位与坐标陷阱

- **TeX pt ≠ PDF bp**：GEOM 行按 TeX pt（1/72.27in），poppler 按 bp（1/72in）。letter=614.295pt=612bp。`PT2BP=72/72.27`——geom↔页面框比较前必乘；否则 `paper_mismatch` 全量误报（31/31 实证）。
- **savepos 报变换前坐标**：tikz 旋转节点 / rotatebox / sidewaystable 内的内层 env（tabular/minipage/textblock）mark 坐标在布局系而非渲染系，天然出页框 → `layout:offpage` **只吃浮体 + 展示数学**，内层出框由 poppler 词级 breach 兜（渲染后真值）。2402.07927 p10 实证 13 个旋转 tikz 树内嵌 tabular 全为误报。

### 10.2 逐信号落地语义（与 §4 计划有差异者加粗）

| sig                                            | 落地语义                                                                                                                                                                                                                                 | 标定依据                                                                                                                                               |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `layout:overfull`                              | log 扫 Overfull \hbox/\vbox，计数 + 最大 pt                                                                                                                                                                                              | 3 findings/3 papers——真实溢出，保留                                                                                                                    |
| `layout:float_fit`                             | `TeXlate-Float-Fit` typeout 回读                                                                                                                                                                                                         | 信息信号（自家手术记账）                                                                                                                               |
| `layout:float_lost`                            | `Float too large` 等 warning                                                                                                                                                                                                             | 2408.03794 n=12——截断编译实证                                                                                                                          |
| `geo_margin_breach`                            | 词心限正文带（`t-2≤cy≤b+20`，页眉页脚豁免）+ CJK 全角标点 bbox 边缘每侧扣 0.6h + **≥4 词 x 序连续 ASCII 段越界豁免**（verbatim 附录/列表溢出=en 原文同形；CJK 词断跑故双栏免疫）+ 数学符号 token 不计；base 侧不豁免（全量计供跨臂抑制） | 2608.25736 8 findings 全 furniture/标点误报→修后 13 findings/9 papers 为真（超宽表出栏）；e2e_real-3 178 findings 多 verbatim 附录→ASCII 跑豁免        |
| `geo_text_overlap`                             | 词 IoU>0.3 跨行对（≤2 字符纯符号 token 剔除——√∼±→ 堆叠 bbox 伪影），**跨臂抑制**：zh≤max(base×1.5, base+3) 不升级                                                                                                                        | 2609.20519 1805 对全在矢量图内、两臂同构→43→17；e2e_real-3 111 findings 多 stackrel/√ 字形伪影→符号 token 剔除                                         |
| ~~`geo_float_jam`~~ → **`geo_text_as_curves`** | 原「有墨无词且 images>0」语义颠倒——图版页全合法。改为：ink>0.5% ∧ 词<3 ∧ 无位图对象 → 文字渲成曲线（不可复制检索真缺陷）                                                                                                                 | 1706.02386 p27-28 图+caption 页实证原语义只抓合法面                                                                                                    |
| `align_page_count`                             | zh/base 页数比 ∉[0.6,1.6]                                                                                                                                                                                                                | 2408.03794 截断编译实证（9p vs 全档）                                                                                                                  |
| `align_figure_lost`                            | pdfimages 计数 zh<base                                                                                                                                                                                                                   | 与 marks `lost_element` 互补                                                                                                                           |
| `align_order_break`                            | skeleton-LCS 覆盖 <0.6                                                                                                                                                                                                                   | 数值表/双栏抽取序噪声面已知；2607.04366 cov=0.452 实证为抽取序效应                                                                                     |
| `align_math_drift`                             | marks 数学 env e-mark 数对拍                                                                                                                                                                                                             | 仅 marks 在位时                                                                                                                                        |
| `geo_header_lost`                              | base 页眉覆盖≥50% 且 zh<20%                                                                                                                                                                                                              | running-head 与 breach 解耦                                                                                                                            |
| `vis_degenerate`                               | FFFD>0 ∨ 词级 n-gram 超 cap（`max(3·npages,20)`，**纯符号 token 剔除**）∨ 空页>2                                                                                                                                                         | 散点 marker ●/○ 连珠剔除（1706.02386 298×●）；refs 先截断                                                                                              |
| `xlat_residual_en` / `xlat_residual_en_heavy`  | refs 截断后词级英文行（**正文域复现 ≥4 次的 running-head/furniture 行剔除**）：**≥25 行 ∧ ≥2%** 或 **≥60 行**；frac≥15% 升 `xlat_residual_en_heavy`（真半译出货档）                                                                      | 阈值前 22 papers 报警含 frontmatter/语料例句/图内 caption 合法英文；e2e_real-3 frac≥0.15≈8 篇全真半译（fault→src 回退出货），低 frac 多为合法 verbatim |
| `layout:paper_mismatch`                        | geom pw×PT2BP vs mediabox 差>2bp                                                                                                                                                                                                         | 2503.10867 letter 几何出 A4 页=真实配置异常                                                                                                            |
| `vis_void`                                     | **内部白色连通块**（不贴测量区任一边）>30% 且非末页                                                                                                                                                                                      | 矩形法把目录收尾/末页留白当洞；CC 语义后 23→0 全为贴边合法留白                                                                                         |
| `geo_column_collapse`                          | **横带众数栏数** zh_mode≠base_mode                                                                                                                                                                                                       | 整页投影被通栏图填沟误 1 栏（2502.15152）；横带化后 19→0                                                                                               |
| `layout:float_drift`                           | **Theil-Sen 趋势残差**≥2 页（≥3 对）；<3 对用页数比期望                                                                                                                                                                                  | 2512.01407 渐变 dp −2→−14 中位模型两头误报→趋势面后 18→0；2505.16322 wrapfig 降格漂 23 页=真信号                                                       |
| `layout:order_inversion`                       | **跨页倒置对**才报（Kendall-tau 对拍 (p,-y) 序）                                                                                                                                                                                         | 同页倒置=双栏行主序伪影（2601.02468/2607.06115 实证）；12→7 findings 全真重排事件                                                                      |
| `layout:lost_element`                          | base 发排 e-mark 而 zh 无                                                                                                                                                                                                                | 声明序对拍                                                                                                                                             |
| `layout:float_seq_mismatch`                    | 声明序浮体数不等                                                                                                                                                                                                                         | 声明序对拍                                                                                                                                             |
| `layout:dropped_env`                           | splice env 计数 < src（demote 改名归并）                                                                                                                                                                                                 | wrapfigure→figure 改名不报警                                                                                                                           |
| `layout:marks_coverage`                        | 受钩 env 有 \\begin 无 mark                                                                                                                                                                                                              | 2408.03794 figure*:7 截断实证；单臂信号不进 CROSS_ARM                                                                                                  |
| `layout:marks_absent`                          | .txlm 缺失/零 mark；**base 侧两分**：`base_txlm=None`（未建对照臂）静默记账——臂编不编是参数选择（base=onfail clean 不建臂）；臂已建而 txlm 缺席/零 mark 照报（注入链断）                                                                 | 存量 282/284 无 marks=预期；新编译双臂注入；e2e_real-3 base=onfail 下 121 条结构性噪音→静默                                                            |
| `regress_ink_profile`                          | zh 页墨量 < base ±2 页窗峰值×0.35 ∧ **< 非空 zh 页墨量中位数×0.25**（自身文档内离群低点才算掉内容）∧ base 邻窗>8%；末页/空页豁免                                                                                                         | e2e_real-3 41 findings 全为 zh_img==base_img 的重排错位假阳→加自离群闸；空页不计入中位数防半空白文档闸死                                               |

### 10.3 声明序匹配（demote 免疫）

跨臂元素匹配**不按 uid 名**：`demote_wrapfloats` 把 wrapfigure→figure 且注入 minipage，uid 面全乱。主键 = `env_sequence(root)` 源扫 `<env>-<per-env序>` 声明序——与编译行为无关恒真，浮体孤页丢 b-mark（page builder 不触发）也不受影响。env 改名如实记进 finding（`base_env`/`zh_env`）。

### 10.4 实跑验证矩阵

| 验证                                       | 规模                                                | 结果                                                   |
| ------------------------------------------ | --------------------------------------------------- | ------------------------------------------------------ |
| `pytest tests/compile/test_layoutqc.py`    | 27 例                                               | 全过（含 e2e 实编 marks 注入→.txlm）                   |
| run_exp 双臂重编                           | 31 篇（e2e_real-2 39 id 中有 vault splice 者）      | inject→compile→txlm→compare 全链路通                   |
| **no-op roundtrip 门**（zh=base=src 自比） | 31 篇                                               | **31/31 PASS**——跨臂信号自比全零，比对器自反无系统偏置 |
| reqc 双臂复判（终版代码）                  | 31 篇                                               | 见 §10.5                                               |
| backfill 单臂存量                          | 284 vault 胞（0444-fused → copy_mutating 可写副本） | 见 §10.5                                               |
| 逐页 PNG 人工核验                          | 8 页                                                | 逐类误报归因见 §10.2 标定依据列                        |

### 10.5 终版实跑 AGG（reqc4 + backfill5，校准后代码）

**reqc4（e2e_real-2 三十一篇双臂复判，findings 计数/篇数）**：

| sig                                                                                    | findings | papers | 判读                                                          |
| -------------------------------------------------------------------------------------- | -------- | ------ | ------------------------------------------------------------- |
| `xlat_residual_en`                                                                     | 10       | 10     | 全真（25–470 行残留英文）                                     |
| `geo_margin_breach`                                                                    | 13       | 9      | 真（超宽表出栏/URL 贴边）                                     |
| `geo_text_overlap`                                                                     | 17       | 8      | 矢量图内 bbox 伪影为主（已知类）                              |
| `layout:order_inversion`                                                               | 7        | 7      | 真重排事件（多良性，供分诊）                                  |
| `layout:float_drift`                                                                   | 6        | 4      | 真离群（wrapfig 降格漂 22 页等）                              |
| `align_order_break`                                                                    | 4        | 4      | 粗信号，抽取序噪声面已知                                      |
| `layout:overfull`                                                                      | 3        | 3      | 真溢出                                                        |
| `layout:float_fit`                                                                     | 3        | 3      | 自家手术记账                                                  |
| `vis_degenerate`                                                                       | 4→1      | 4→1    | 3 篇为符号 token 伪影（后验已清），余 2408.03794 fffd=3695 真 |
| `layout:marks_absent`/`marks_coverage`/`float_lost`/`paper_mismatch`                   | 3/2/1/1  | —      | 全实证真（截断编译/配置异常）                                 |
| `layout:offpage`/`vis_void`/`geo_column_collapse`/`geo_text_as_curves`/`geo_float_jam` | **0**    | 0      | 校准目标达成：无非零残留                                      |

**backfill5（vault 284 胞单臂存量，papers_with/282 done）**：

- `marks_absent` 282（预期：存量无注入）、`no_pdf` 1、`no_main` 2；
- `overfull` 58、`float_lost` 22、`float_fit` 26——真实版面债底数；
- `margin_breach` 221 findings/26 篇、`text_overlap` 493/136（单臂裸口径，含图内，双臂抑制需 base）；
- `residual_en` 93 篇（新阈值从 176 压到 93，仍为最大单 sig——存量翻译残留率 ~33%）；
- `vis_degenerate` 22→**11 真**（后验清 10 符号/数字伪影）——其中 **2609.19965/2609.20732 抓出"这是译文这是译文…"占位符退化输出数百连**——存量语料里真混着 mock/占位译文，此前验证全放行了。这是本电池最硬的一次实证。

**roundtrip 门**：31/31 PASS（gate3 在 reqc4 后自动跑，CROSS_ARM 跨臂信号自比全零）。

**rescan6（284 vault 胞单臂重扫，tier 门 + 新探测器 + 标记页收割，2026-09-23 晚）**：

- **tier 分布**（282 scored + 2 no_main）：clean 34 / warn 89 / **hard 159**——hard 占比 56% 主因是周期性占位检测把 2609.* mock 译文集群整批翻出。
- **sig 总计**：`geo_text_overlap` 493（单臂裸口径含图内伪影）、`marks_absent` 282（存量预期）、`geo_margin_breach` 222/26 篇、`vis_degenerate` **143**、`xlat_residual_en` 93 篇、`overfull` 59、`float_fit` 26、`vis_void` 22、`float_lost` 21、`vis_blank_page` 9、`pdf_corrupt` 1、`no_pdf` 1。
- **`vis_degenerate` 精度实证**：143 发全部落在 2609.* 占位译文集群（`degen_periodic_lines` 289–1613 行/篇，top_ngram 全部低于旧阈）——真实论文零命中，新检测器 FP≈0 召回=整批。
- **新签实证**：`layout:pdf_corrupt` 2404.14219（newmain.pdf 坏 xref，poppler 全工具链拒读）；`xlat_broken_refs` 2505.21476（正文 646 ?? 字符，\cite/\ref 全断链）；`regress_ink_profile`/`geo_table_lost`/`vis_tofu_box` 在双臂子集活跃。
- **reqc5（40 胞双臂重打分）**：hard 27 / warn 12 / clean 1——marks 跨臂面 `lost_element`/`float_drift`/`order_inversion`/`marks_coverage` 全类活跃；鲜度判（pdf.mtime>tex.mtime）识别 2505.21476 vault 存量 pdf 冒充重编产物（重编 100 错 abort），改按单臂语义计。
- **收割面**：tier≥warn 胞格 flagged_pages PNG 落 `out*/<cell>/flagged/`（110dpi 收割专道）；176p 长文档收割 27/35 页实证 keep 模式只渲标记页。

**run4 扩容波（胞 41–120 双臂 marks 重编，2026-09-23 深夜）**：

- **鲜度闸连合 bug（已修）**：首波 run3 把 `pdf.mtime>tex.mtime` 当「本波已编」——copytree 承 vault mtime 下存量 pdf 恒新于 tex，80/80 zh 漏注入漏编、marks_absent 满发、跨臂面全哑。修为「`TeXlateMark` 哨兵在 tex + pdf 更新」才算 fresh（recompile zh/base 两路同闸，reqc marks_era 判据同改）。
- **end 钩子 `\@currenvir` 毒化（已修 marks.py）**：`env/<name>/end` 触发点上 `\@currenvir` 可能已恢复成外层 env——2609.20793 `\maketitle` 内 authblk tabular 的 end 钩子读出 `center` → `\the\relax` 报错 + `center-0-e` 毒化 mark + 编译 rc=1 双收。修为 end 钩子注册期烙名 `\txlm@e{<env>}`（begin 仍 `\@currenvir` 自取，实证恒对），加未分配计数器守卫。authblk repro 全 uid 成对。
- **`_compile` 成败判（已修）**：`rc==0` 闸过严——nonstopmode 可恢复错误照常出 pdf 但 rc=1，7 格 zh_compile_fail 中 5 格实有新鲜产物。修为「编译后 pdf 新于 tex」判成功。
- **run4 分布**（80 胞）：clean 5 / warn 18 / hard 50 / error 7——marks 面全类实弹：`float_drift`（单格 15 位点）、`order_inversion`、`marks_coverage`、`align_page_count`、`align_order_break`；`marks_absent` 清零。
- **error 格归宿**：5/7 是 rc 闸误杀（reqc 免编译重打分自动拾回）；2404.14219 真编译死（pdf_corrupt 本源）；1610.02136 早前波次已编。

**reqc6 + rescan7（终版代码统一重打分，2026-09-23 深夜）**：

- **reqc6（120 胞双臂）**：clean 8 / warn 32 / hard 80 / **0 error**——marks 真值面全量在位：`float_drift` 123 位点、`order_inversion` 36、`lost_element` 12、`marks_coverage` 9、`align_page_count` 15、`align_order_break` 17、`offpage` 1；`marks_absent` 仅 9（118/120 鲜度闸过、2 格 stale vault pdf + 编译死格按单臂 INFO 计）。新签 `xlat_broken_refs` 9 胞、`geo_table_lost` 1、`align_figure_lost` 2、`align_math_drift` 2、`geo_column_collapse` 2。
- **rescan7（284 vault 胞单臂）**：clean 33 / warn 90 / hard 159 / error 2（皆 no_main）——与 rescan6 分布稳定（clean 34→33 边缘抖动）；新签 `xlat_broken_refs` **15 胞**、`pdf_corrupt` 1、`no_pdf` 1。
- **双臂 vs 单臂对照**：同一批 2609.\* 占位集群在双臂下 marks 面额外供出 drift/inversion/coverage 三类真值——单臂只能看 marks_absent+degen，双臂才可证「浮体级丢件/乱序」；证实双臂 marks 是检测面的独占深度层。

**run7 全量波（214 胞双臂 marks 重编，2026-09-23 晚，float_score 全量 eligible）**：

- **规模**：vault/splice ∩ lake-tex eligible 215 选 214——存量 121 work tree 走鲜度闸 fresh-skip 只重打分（吃 natbib `(?)`/`[?]` 断引正则），~94 新格编译+QC。
- **分布**：clean 13 / warn 45 / hard 153 / error 3（2× zh_compile_fail + 2609.20756 zh_no_main——该格 splice 只有 root.pdf 无 tex 源，退化胞格记档）。对照 reqc6（120 胞）clean 率 6.7%→6.1% 持平、hard 66.7%→71.5%——新覆盖的 float_score 尾部并不比头部干净，版面缺陷是全面性的不是头部密集格的专利。
- **信号总计（前八）**：`geo_margin_breach` 245、`float_drift` 234、`geo_text_overlap` 208、`vis_degenerate` 143、`offpage` 114、`xlat_residual_en` 74、`regress_ink_profile`/`order_inversion` 各 54；`xlat_broken_refs` 9 胞（natbib 扩面后新检出）。
- **口径注记**：存量 121 树的 txlm 是 marks end-hook 烙名修复（`\@currenvir` 外层还原误读）前的产物——偶发错名 -e 标记属已知噪音，未重编；新格全部吃修复后代码。

**qc_replay（260 帧探针批 vault 胞全量重放，校准后探测器，2026-09-24，`tools/qc_replay.py`）**：

241 胞可判（19 胞 vault 无 splice 封件）。tier 分布 clean 56 / warn 161 / hard 24。逐 sig 新码 vs 旧码对照（findings 计数）：

| sig                      | 旧  | 新  | 变动归因                                                             |
| ------------------------ | --- | --- | -------------------------------------------------------------------- |
| `layout:marks_absent`    | 241 | 39  | `base_txlm=None`（base=onfail 未建对照臂）静默——噪音面消退           |
| `geo_margin_breach`      | 309 | 213 | ≥4 词连续 ASCII 段越界豁免（verbatim 附录/列表=en 原文同形）         |
| `geo_text_overlap`       | 287 | 144 | ≤2 字符纯符号 token 剔除（stackrel/√ 字形堆叠 bbox 伪影）            |
| `xlat_residual_en`       | 62  | 42  | running-head/furniture 行（正文域复现 ≥4 次）剔除                    |
| `regress_ink_profile`    | 41  | 0   | 自离群闸（<自身非空页墨量中位数×0.25）——重排错位假阳清零             |
| `align_order_break`      | 6   | 0   | 同上波次随抽序面复评消散                                             |
| `xlat_residual_en_heavy` | —   | 16  | 新签：frac≥15% 真半译出货档（fault→src 回退出货），自 residual 析出  |
| `layout:overfull`        | 43  | 43  | 不变——43 findings/23 篇全真出血，现为 fixloop `warn_overfull` 驱动面 |

**两个结构性遮蔽数**（真实缺口，非噪音）：

- **txlm 源分布**：splice 98 / layoutqc_vault 105 / **missing 38**——38 胞 zh 臂在全 vault 无一枚 .txlm（marks 注入链从未触达；多为 slim 后 tex 源已焚、或编译从未带注入跑过），marks 面对这 38 胞结构性失明，只剩 log/raster 层兜底。
- **env_masked 143**：143 胞 splice 封件为 artifact-only（slim 只留 pdf/log/txlm 无 .tex）——`layout:dropped_env` 的 env_inventory(splice) 恒空被遮蔽不计，env 面对 slimmed 胞格整体失明。这是 §6「成功即删」政策的检测面代价，留档知情。

### 10.6 已知 FP/盲区清单（留档不堵）

- **矢量图内 bbox 伪影**：pgfplots/tikz 图内密集 tick 标签在 poppler 词级天然交叠；跨臂抑制吃大头，figure 区域分割（MinerU 式 layout parser）是根治但超范围。
- **深色位图页 ink_blob FP**：星系格/照片类深色位图天然产出巨大 dark CC（0812.1022 银河格 43% 实证）——已按 text_as_curves 同族豁免：含嵌入位图页不报 ink_blob，非位图页的矢量病态/字体炸弹仍受检。
- **行内周期占位检测**（degen 第三分支）：CJK mock 译文「这是译文这是译文…」整行无空格，词级 n-gram 受 running-head 放阈连坐放走（2609.19244 top_rep=46<195 但满页占位符，行内连珠 706 行实证）；`degen_periodic_lines≥3` 新签，单两行修辞重复/无词字符单元（……/====）不过阈。
- **vis_void 浮体密页存疑**：subfigure 密排页浮体间白条可成内部白连通块（2609.19244 18 页连发，看图多为合法浮体间距）——阈值/浮体页折扣待 rescan AGG 分布裁决，记观察项。
- **refs 页 breach**：URL/DOI 不可断行天然贴边——跨臂抑制后残余为可接受底噪。
- **合法英文类**：frontmatter 作者块/affiliation、语料例句（方言研究 2605.06276）、图内 caption、pseudocode——residual_en 阈值已压至 ≥25∧2% 仍可能含少量此类，人工分诊语义。
- **旋转容器内 marks**：offpage 已对内层 env 豁免，但浮体级 mark 在 sidewaystable 内仍会坐标异常（罕见，表* 在旋转体内时）；如需根治走 BOX dims 或 SyncTeX。
- **抽取序 LCS 噪声**：数字密集表在 2 栏重排下 skeleton 序乱——align_order_break 是粗信号，45% cov 级事件需人工看页。
- **BIoU/SSIM 要素未落地**：`vis_tofu_box`/`geo_table_lost`（规则行代理）/`regress_ink_profile`（逐页墨量回归抓矢量图掉图，pdfimages 盲区补位）已落地；`geo_biou_low`/SSIM 仍在计划面；LLM judge(T2) 未建。
- **raster 超时静默缺口（已修）**：`_run` 60s 帽对长文档 raster 全灭——load~38 下 15p 实测 42s、176p 必然 `raster_error=empty` 静默丢全 raster 层（2505.21476 实证）。修为度量遍 RASTER_TIMEOUT=420s + 收割专道（keep 模式只渲标记页 -f/-l 段批，不再二遍全扫）。
- **void_frac 直方图栈 bug（已修）**：最大白矩形实现存索引栈、弹出高度不回传左界，有墨页也虚报 1.0（2403.05234 全页 void_frac=1.0 实证）——findings 走 `void_int` 未受灾，口径修复后备路径不再说谎。
- **存量树鲜度判连合（已修）**：一切「pdf.mtime>tex.mtime ⇒ 本波产物」判据都被 vault copytree 承 mtime 骗过——run3 80/80 zh 漏注入实证。凡鲜度判必须「`TeXlateMark` 哨兵在 tex」与「pdf 新于 tex」双条件。
- **env end 钩子环境名（已修 marks.py）**：`env/<name>/end` 钩子里 `\@currenvir` 非契约可靠（\maketitle 内 env 嵌套读出外层名），end 钩子一律注册期烙名；begin 钩子 `\@currenvir` 自取实证可靠。
- **`layout:no_pdf`**：zh PDF 缺席兜底 sig。
- **fullpage XObject 幻影词层（已修 2026-09-26）**：splice 矢量保真复用把整页源文嵌作 `fullpage` Form XObject 再按图 bbox clip——poppler `pdftotext -bbox` 无视 XObject clip，报出 clip 区外幻影 en 词与可见 zh 行互撞（2609.05962 p11：pdftotext 460 词 vs mupdf 82 词；texttrace/OCG/Tr 排查排除隐墨面）；mupdf `get_text('words')` clip-aware 只报可见墨——`_bbox_pages` 换 pymupdf 优先（AGPL 可选依赖，缺席退 pdftotext）。W1 普查口径 1413→749 词对。
- **en×en 图内源侧碰撞（已修 CJK 闸 2026-09-26）**：嵌入图 PDF 内的 en 标签互撞（matplotlib tick×轴题挤压）是源侧几何非 splice 产物——splice 只产 zh 墨，凡 splice 致撞必含 CJK——`_word_overlap_pairs` 加 CJK 参与闸（en×en 跳过，残留 en 行互撞归 xlat_residual_en 管）。W1 普查词对 749→133、findings 188→35/格 93→25（-81%）；抽核实撞真阳：cond-mat/9901106 p3 zh 题字压图轴刻度（18 对）、1404.0417 p6 zh×残留 en 引文（6 对）；2202.13013 zh 行内 math token 微撞为边界真信号非噪音。

### 10.7 检查面完备性自问（vs §3 外部调研）

| 缺陷类           | 覆盖                                                                                                         | 备注                        |
| ---------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------- |
| 丢图/丢浮体      | marks `lost_element` + `float_seq_mismatch` + `align_figure_lost` + `float_lost`(log)                        | 四层冗余                    |
| 浮体漂移/乱序    | `float_drift`(Theil-Sen) + `order_inversion`(跨页) + `offpage`                                               | 声明序主键免疫 demote       |
| 溢出/越界        | `overfull`(log) + `margin_breach`(词级) + `offpage`(元素级)                                                  | 三视角                      |
| 文本重叠         | `text_overlap`(IoU 词对 + 跨臂抑制)                                                                          | figure 内残余 FP 已知       |
| 版面几何         | `paper_mismatch` + `column_collapse` + `header_lost` + `vis_void` + `text_as_curves`                         |                             |
| 页数/序完整性    | `page_count` + `order_break` + `math_drift`                                                                  |                             |
| 内容退化         | `vis_degenerate`(fffd/ngram/空页) + `residual_en`                                                            |                             |
| 编译截断         | `marks_coverage` + `marks_absent` + `no_pdf`                                                                 | 2408.03794 实证             |
| 表格 cell 级崩坏 | **半盲区**——`geo_table_lost` 规则行代理覆盖「网格线消失」类；cell 内错位/列错位仍只有 overfull/breach 间接面 | MinerU 式 parser 才够       |
| 公式渲染错       | math placeholder 字节 identity（L0）+ `math_drift` 计数                                                      | 渲染层面未验（CDM 已 SKIP） |
| 阅读序           | marks (p,-y) 对拍                                                                                            | 双栏行主序伪影已修          |

结论：T0+T1 现行电池对**版面几何/浮体完整性/内容退化/编译完整性**四类是足的；真盲区只剩**表格 cell 级结构**与**渲染后公式**两处，均属 T2 parser/judge 范畴——按 §7 序收在此处是正确边界。

## 11. 终版检验方案与工件保留政策（定稿 2026-09-23）

§4–§6 是计划面；本节是**执行契约**——门定义、信号分档、删除政策全部按 §10 校准后代码（31 个已发射 sig）定稿。

### 11.1 门定义：信号三档

`qc_paper` 产出的 sig 按「是否挡 done」分三档。**clean = 零非 INFO findings**。

| 档                                 | 判定                                            | sig                                                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **HARD**（fail，留全档）           | 元素丢失 / 编译截断 / 结构性版面崩坏 / 内容退化 | `layout:no_pdf` `layout:pdf_corrupt` `layout:marks_coverage` `layout:lost_element` `layout:float_seq_mismatch` `layout:dropped_env` `layout:offpage` `layout:paper_mismatch` `layout:float_lost` `align_page_count` `align_figure_lost` `align_math_drift` `vis_degenerate` `vis_blank_page` `vis_ink_blob` `vis_void` `vis_tofu_box` `geo_table_lost` `geo_column_collapse` `geo_text_as_curves` |
| **WARN**（进 QC score，不挡 done） | 真实但非阻断的版面/翻译质量扣分                 | `xlat_residual_en` `xlat_residual_en_heavy` `xlat_broken_refs` `geo_margin_breach` `geo_text_overlap` `layout:float_drift` `layout:order_inversion` `layout:overfull` `geo_header_lost` `align_order_break` `regress_ink_profile`                                                                                                                                                                 |
| **INFO**（纯记账）                 | 机制回执 / 预期缺席                             | `layout:float_fit`（FLOAT_SIZING 手术回执——splice fork 发现的「发射了没人消费」信号，现由本档闭环消费）；`layout:marks_absent`（存量无注入期胞格恒发；**新双臂编译语境下升级为 WARN**——注入缺席=仪表链断）                                                                                                                                                                                        |

分档理由：

- **HARD 全是「产出不可用或元素级丢失」**——§10.5 每条背后都有实证：截断编译（marks_coverage/float_lost）、letter 稿出 A4（paper_mismatch）、占位符 mock 译文（vis_degenerate）、掉图窟窿（vis_void）。
- **WARN 是「读者能看见但读得完」**——residual_en 存量基线 ~33% 挡门会淹没分诊、text_overlap 含已知 figure 内伪影、drift/inversion 多为合法 reflow 事件。进 score 供人工分诊与质量统计，不挡。
- `align_order_break` 是粗信号（LCS 抽取序噪声面已知，§10.6）——只作看页提示。
- 已落地：`vis_tofu_box`（.notdef 空心框簇 ≥4/页，四边墨率判据挡 O/0 伪影）→ HARD；`geo_table_lost`（规则行数跨臂对拍，zh<base×0.6 且 base≥3）→ HARD；`regress_ink_profile`（逐页墨量回归，矢量图掉图补位）→ WARN；`layout:pdf_corrupt`（poppler 渲染级失败，坏 xref/断 stream）→ HARD；`xlat_broken_refs`（`?{2,}` run≥8 位点，断链 cite/ref）→ WARN。未建：`geo_biou_low`/SSIM（→ WARN 预期）。

### 11.2 QC 报告契约（保留扫描器的输入）

qc_paper 结果落 records 时须带三键，供删除政策消费：

```json
{
    "qc_tier": "clean|warn|hard",
    "flagged_pages": [3, 7],
    "sig_counts": { "geo_margin_breach": 2 }
}
```

- `qc_tier` = findings 里最高的非 INFO 档；无 findings → `clean`。
- `flagged_pages` = findings 各 `page` 字段去重排序——**tier≥warn 的胞格把这些页渲成 PNG 收进 vault**。raster 子进程本来就把全页过一遍，收标记页 PNG 是边际零成本（~200KB/页，通常 ≤5 页/篇）。

### 11.3 工件保留政策（成功即删·定稿）

| 终态            | 定义                 | 保留                                                                              | 估算/篇  |
| --------------- | -------------------- | --------------------------------------------------------------------------------- | -------- |
| `clean`         | 零非 INFO findings   | raw + zh tex + final.pdf + QC 报告 + metrics；extracted/workdir/splice 中间件全删 | ~8MB     |
| `warn`          | 仅 WARN/INFO         | 同上 + flagged_pages PNG + splice 内 tex（翻修素材）                              | ~10MB    |
| `hard`          | ≥1 HARD              | splice 全档 + workdir 诊断面 + flagged PNG                                        | ~17-20MB |
| `upstream fail` | no_pdf/no_main/fetch | catalog 行 + QC 报告                                                              | ~0       |

与 §6 计划版的两处修订：

1. **warn 档新增 flagged_pages PNG**——QC 报告必须自含分诊素材，否则「成功即删」把唯一可目检的证据也删了。
2. **warn 档保留 splice tex 而非全档**——tex 是翻修/复译素材（小），pdf/aux/图片中间件才是体积大头（可删）。

存量适用性：284 vault 胞全部 `marks_absent`（INFO）→ 其 clean 判定只看单臂可检面；backfill5 的 11 真 degen、22 float_lost、1 paper_mismatch 按本表全落 `hard` 留全档——**存量重扫一次即可按本表出删留清单**（P3 磁盘手术的执行依据）。
