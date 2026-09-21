# L2 HTML 降级路调研与分块规格：LaTeXML DOM → 占位符契约 → 双语呈现

> **结论**：arXiv 原生 HTML（LaTeXML 输出）可按「提取边界 = `article.ltx_document` + 叶选择器分块 + 原子占位符」规则产出与 LaTeX 路**同构的 chunks[]**——translate/validate 零改动；MathML 整子树直通不译；对齐锚用 DOM 序 1:1 精确锚（优于 PDF 路 named-dest 估算）；双语呈现定「交错注入（原上译下）为规范产物、双栏为派生视图」。
> **状态**：已落地（`arxiv/html.py` 的块枚举/占位符/`marked_html` 锚注入、`server/worker/html.py` 的 arxiv_html 链、web 端 `HtmlPane`）。规范面唯一事实源 = `spec/`；本文是 DOM 实测证据与设计动机——**§2/§5/§6/§7 为设计稿**，落地真相以 `spec/arxiv-source.md` §5.2 与下方落地差异注记为准；§1/§3/§4 的 DOM 取证仍然有效。
> **日期**：2026-09-14 取证（样本：arxiv.org/html 1706.03762/2203.02155/stub 1412.6980 + ar5iv 多篇），2026-09-20 重订入库

**落地差异注记（2026-09-21 补，vs `arxiv/html.py` + `server/worker/html.py`）**：

- `data-chunk` 锚用**元素 key**（元素 `id` 优先、缺失合成 `b{n}`）而非纯 seq——1:1 契约语义不变。
- §2 三组选择器伪码（ATOMIC/LEAF/SKIPTREE）从未成码：落地是 dispatch-table 分派（`_SKIP_TAGS`/`_SKIP_CLASS_PREFIX`/`_SKIP_BLOCK_CLS`/`_EQN_PREFIX`/`_MEDIA_TAGS`/`_SUPPORT_ANCESTOR`）。
- `ltx_tag` 由 `_SKIP_CLASS_PREFIX` 剥除、不保留在文本内（§2 表相反）；`span.ltx_ERROR` → `[[CMD_n]]` 原子占位符，不计入质量信号。
- bibitem/figure/listing/authors/dates/equation 落地为 **support 块**（枚举式、带 `data-chunk` 锚、不译，内部仍挖 caption/title）——非 §2 表的整树跳过；`div.ltx_para` 本身就是 para 块（`span.ltx_p` 未处理）。
- 落地 kind 枚举 = para/p/title/caption/footnote/keywords + support 族——无 cell/pubnote kind（`ltx_tabular` → `[[TABLE_n]]` 原子）；占位符族 = MATH/CITE/REF/NOTE/GRAPHICS/CMD/TABLE/URL，无 `[[IMG_n]]`。
- §5 多信号 stub 表未落地：实现只判「无 `article.ltx_document`」（pdf_wrapper 亚型仅存于 e-print sniff 侧）。
- §6 交错单 DOM 规范产物未实现：落地为成对 `en.html`/`zh.html` 共享 `data-chunk` 键 + 原位 zh 文本替换 + `dual.json` `alignment={"kind":"pages"}`；`data-chunk-role`/`texlate-zh`/`data-pending`/zh-克隆去 id 均未实现，`dual.json` 也无 `ltx_id↔seq` 深链表。

## 1. DOM 结构事实

- **engine**：arxiv.org `/html/` 与 ar5iv[^ar5iv] 同为 LaTeXML[^latexml]（0.7.5/0.7.6）——**同引擎同 DOM 方言，一套选择器通吃两源**；ar5iv 可作 L2 第二源（但同样救不了 PDF-only）。
- **页面骨架**：chrome（导航/TOC/页脚/modal/infobox）全剥，唯一提取边界 = `article.ltx_document`（无 id，class 定位）；article 内顶层序 = `div.ltx_para` 版权行 → `h1.ltx_title_document` → `div.ltx_authors` → `div.ltx_abstract` → `section.ltx_section`…→ `section.ltx_appendix`…→ `section.ltx_bibliography`。
- **资源引用**：`img.ltx_graphics[src]` 全相对路径，基准 = `https://arxiv.org/html/{id}v{resolved}/`——服务化时必须 absolutize 或走代理。
- **标题层级**：h1=document、h2=section/appendix/bibliography、h3=subsection、h4=subsubsection、h5=paragraph(runin)、h6=abstract/theorem；**chrome 里也有 h2/h5**，计数须限定 article 内。

### class 直方图（摘要）

实测三篇（1706/2203/math0404188）关键类的块语义：`ltx_para`=段落容器（非分块单位，可包公式表/列表）；`p.ltx_p`+`span.ltx_p`=**文本叶**（后者是表格单元内段，2203 中 479/662）；`ltx_equation*`=行间公式 **`<table>`**；`ltx_section*/appendix`=section 嵌套最深 3 层；`ltx_figure/table`=figure 浮动体（可嵌套子图面板）；`ltx_tabular/ltx_td`=数据表格（单元块是块数大头，表格密论文占 80%+）；`ltx_bibitem/bibblock`=参考文献条目；`ltx_cite`=cite 元素；`ltx_ref`=内部交叉引用锚；`ltx_note/note_content`=行内嵌套脚注（内容默认隐藏）；`ltx_theorem*`=定理块；`ltx_authors`=作者块（不译）；`ltx_ERROR`=LaTeXML 错误内嵌字面量；`ltx_picture/svg`=TikZ→内联 SVG；`ltx_Math`/`ltx_math_unparsed`=`<math>` 元素（unparsed=解析失败）；`ltx_align_*`/`ltx_font_*`/`ltx_text` 等纯表现层不影响抽取。

## 2. 分块模型（三层规则）

> ⚠️ 本节为设计稿伪码与跳过表——落地为 `html.py` dispatch-table 实现，差异见头部落地差异注记。

```python
ATOMIC   = 'math, cite.ltx_cite, a.ltx_ref, span.ltx_note, span.ltx_pubnote, img, svg,
            .ltx_personname, .ltx_contact, .ltx_role_affiliation'
LEAF     = 'p.ltx_p, span.ltx_p, figcaption.ltx_caption, .ltx_title, span.ltx_note_content'
SKIPTREE = 'table.ltx_equation, table.ltx_equationgroup, li.ltx_bibitem,
            .ltx_pagination, nav, script, style, pre, .ltx_verbatim, .ltx_listing'
```

叶发现按文档序；leaf-in-leaf 只发生在 note/pubnote（`p.ltx_p` 内嵌原子 `span.ltx_note` 再内 `ltx_note_content` 叶→父子两块都保留）；裸单元格补扫（td/th 无 LEAF 后代且有非原子文本 → cell 块）。实测块数：1706.03762=311、2203.02155=1857（cell 块为主）、math0404188=581、stub=1。**表格单元块极小（中位 <20 字符）→ 翻译层按编号批量打包**，seq 粒度 ≠ 请求粒度。

### 跳过清单（与 LaTeX 路黑名单对齐）

| 节点                                        | 处理                                              | 理由                                                                       |
| ------------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------- |
| `table.ltx_equation*`                       | 整树跳过（连编号 tag 都不进块）                   | 行间公式不可译                                                             |
| `li.ltx_bibitem`                            | 整树跳过                                          | 对齐 thebibliography 黑名单；**省 ~11% 字符量**（2203: 20K/182K）          |
| `div.ltx_authors` 内 personname/contact 等  | 原子级跳过                                        | 人名保原语；`ltx_note_content` 例外（致谢散文，译）                        |
| `ltx_tag`（"Figure 1:"/"•"）                | **保留在文本内**                                  | "图 1："该翻；项目符号本来就是符号                                         |
| `span.ltx_ERROR`                            | 文本原样进 chunk + 计数进质量信号                 | 它是可见文本（如 `\preprintnumber` 残留）                                  |
| `pre`/`.ltx_verbatim`/`.ltx_listing`        | 跳过子树                                          | 代码不译（样本未覆盖，防御性保留）                                         |

### 抽取与占位符契约

`src_text(leaf)` = 序列化：文本节点原样；ATOMIC 子树 → `[[TYPE_n]]`（math→`[[MATH_n]]`、cite→`[[CITE_n]]`、`a.ltx_ref`→`[[REF_n]]`、note/pubnote→`[[NOTE_n]]`、img/svg→`[[IMG_n]]`）——与主管线 `[[TYPE_n]]` 契约同构，validator 的占位符多重集校验零改动复用。**陷阱**：naive `get_text()` 会把 `<math><annotation>` 的 TeX 源码和 `ltx_note_content` 隐藏脚注文本串进正文（2203 实测多 ~850 字符噪音）——必须先原子替换再取文本。

## 3. 数学

全部样本 `<math>` 100% 携带 `alttext="{TeX源}"` **且** `<annotation encoding="application/x-tex">` 子元素（双份冗余）。决策：**MathML 子树原子直通**——翻译输入 `[[MATH_n]]`，zh DOM 原样克隆由浏览器原生渲染；alttext 不进占位符。`ltx_math_unparsed`（LaTeXML 解析失败，math0404188 有 59/2293）同样直通但计数进质量报告。

## 4. 锚点与对齐

- LaTeXML id 全是**位置式**（`S3.E1`/`bib.bib8`/`footnote1`/`abstract1`），`\label` 名不保留——HTML 路不存在与 PDF named-dest 的语义对应物，但双语 HTML 同源生成，不需要它。
- **主锚 = DOM 序 1:1**：每个可译叶按文档序编锚，与 chunks/SSE `chunk.items[].seq` 严格对应——PDF 路靠 named-destination 估算的对齐，HTML 路是天然精确 1:1。
- DOM 标记：原叶 `data-chunk="{key}" data-chunk-role="en"`；译文兄弟 `data-chunk="{key}" data-chunk-role="zh"`；LaTeXML id 保留在 en 节点（锚跳转目标），zh 克隆不复制 id（防 `href=#S1` 跳译文副本；如需 zh 侧锚用 `{orig}--zh`）。
- `a.ltx_ref[href^="#"]` 全部内部交叉引用在 zh DOM 克隆中原样可用；自建双语 TOC 直接读 `ltx_title_*` 元素生成。

## 5. stub / 失败检测

> ⚠️ 本节多信号表为设计稿——落地只判「无 `article.ltx_document`」，见头部落地差异注记。

DOM 内零额外请求信号：

| 信号                            | 正常       | stub (1412.6980)                      | 判定                                                                |
| ------------------------------- | ---------- | ------------------------------------- | ------------------------------------------------------------------- |
| `ltx_section`+`ltx_appendix` 数 | 8–87       | **0**                                 | ==0 ∧ 文本<2KB → `html_stub`                                        |
| article 文本长                  | ≥30K chars | 35 chars                              | 主判据                                                              |
| 文本模式                        | —          | `See pages 1-last of 0_adam_main.pdf` | `See pages? [\d\-last]+ of \S+\.pdf` → **pdf_wrapper 亚型**         |
| `span.ltx_ERROR`                | 0–2        | 0                                     | >0 → warning（未定义宏残留）                                        |
| `math.ltx_math_unparsed`        | 0–1        | —                                     | >5% of math → degraded 警告                                         |

路由：stub+pdf_wrapper → 「论文本体是扫描 PDF」跳 L3；stub 非 wrapper（LaTeXML 崩）→ 也跳 L3；**stub 不送翻译**。外部可选信号（懒加载）：arxiv.org 每页 footer 链 `./{id}v{N}/__stdout.txt`（构建日志）；ar5iv `/log/{id}` 机器可读转换报告（`Status:conversion:N` 0=ok/1=warn/2=error/3=fatal）。

## 6. 双语呈现方案

> ⚠️ 本节交错单 DOM 方案未实现——落地为成对 `en.html`/`zh.html` + `dual.json`，见头部落地差异注记。

**决定：DOM 内逐节点交错插入译文（原上译下）为规范产物**，理由：L2 是降级路工程预算有限，交错视图零同步机械（单滚动容器天然对齐）；SSE `chunk` 事件按锚到达即插，用户逐段看译文生长；沉浸式翻译已在同一 DOM 方言验证此 UX；**双栏不丢失**——规范 DOM 里 en/zh 节点都带 `data-chunk`+`data-chunk-role`，派生双栏 = 克隆 article 一侧删 zh 一侧删 en，scrollTop 按 `[data-chunk]` offsetTop 映射即可接入既有 SyncEngine。

zh 节点 = 克隆叶元素同名同类 + `texlate-zh`/`lang="zh-CN"`/`data-chunk-role`，紧随其后插入；表格单元 zh 内容插在原 `span.ltx_p` 后同 td 内；note 依赖槽用 `data-pending` 标记，note chunk 到达后填充。样式自带最小 ltx 样式表（不引 arXiv CDN CSS——跨域资产 + 主题耦合）；MathML 原生渲染，SVG/PNG 已 absolutize。

## 7. 与主管线的接口（translate 编排契约接入点）

> ⚠️ 本节 kind/占位符枚举与 `dual.json` 深链表为设计稿口径——落地见头部落地差异注记与 `spec/arxiv-source.md` §5.2。

`parse` 阶段替换 scanner——输入 HTML 字节，输出与 LaTeX 路完全同构的 `chunks[]`（锚/kind/src_text+ 占位符）；`translate/validate` 零改动；`compile` 换成「zh DOM 写回 + 剥壳 HTML 序列化」产出 `article.en.html`/`article.zh.html`/`dual.json`（含 `ltx_id↔seq` 映射表支持 `#S3.E1` 深链）。kind 枚举新值 `para/cell/caption/title_*/note/pubnote` 进同一列；占位符枚举同一族（ENV/AUTHOR 不需要——公式表整跳、authors 原子跳过）；断点续翻走 translation_cache 内容寻址（与 LaTeX 路 src_text 不同形，不串缓存）；stub/pdf_wrapper 路由 L3 不产 `degraded_html`。

## 8. 开放问题（重订时注）

`pre/ltx_verbatim/algorithm` 样本当时未覆盖（选择器防御性加入）；`ltx_keywords/ltx_dates` 低频；zh 内 `a.ltx_ref` href 是否重写指向 zh 锚（`#S3--zh`）是低风险增强项；单元格批量打包目标尺寸（建议 ~1500 字符/请求）在译器层验证；数学 `alttext` 空值边界未观测到反例（2729/2729 非空）；`Status:conversion` 枚举全集未穷尽（实测见 2，文档述 0–3）。

### 参考文献

[^latexml]: NIST / DLMF. LaTeXML — arxiv.org/html 与 ar5iv 共同的转换引擎（0.7.x DOM 方言，`ltx_*` class 体系）. [latexml](https://math.nist.gov/~BMiller/LaTeXML/)
[^ar5iv]: ar5iv — arXiv 论文的 LaTeXML HTML 独立镜像（`/log/{id}` 转换报告机器可读）. [ar5iv.labs.arxiv.org](https://ar5iv.labs.arxiv.org/)
