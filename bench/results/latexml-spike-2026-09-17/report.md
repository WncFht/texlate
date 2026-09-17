# G1 LaTeXML/HTML 降级链 spike（2026-09-17，0.5d 帽内）

派工口径：m3gap-scout G1 项——「LaTeXML 运行时获取与打包是大头，先评 0.5 天 spike」。
结论先行：**不需要 LaTeXML 运行时**。arXiv 原生 HTML（`arxiv.org/html/{id}`，服务端
LaTeXML 渲染产物直出）覆盖率与 DOM 契约都够，G1 应按 **arxiv-html-first** 形态立项。

## 结论：arxiv-html-first，LaTeXML 运行时完全不必引入

| 维度 | 实测 |
|---|---|
| 覆盖率 | **35/36 = 97.2%**（36 id 探针，跨 1997–2026 全年代；唯一 404 = cond-mat/0501286 撤稿论文） |
| 运行时成本 | **零**——arXiv 服务端已渲染，我们只抓 HTML（与 e-print 同一限流域） |
| DOM→chunk 契约 | 直接拟合：`div.ltx_para`（含稳定 id）、`<math alttext="{LaTeX}">`（公式源可回映占位符）、`h2–h6.ltx_title_*`、`ltx_figure/ltx_caption/ltx_bibitem`；MathML 浏览器原生渲染 |
| 工作量重估 | **~2–3 天**（原估 3–5 天，省掉整个 LaTeXML 获取/打包面） |

样本实证（`tmp/latexml-spike/arxiv-html-sample.html`，2.0MB 全文）：
`ltx_para`×209、`ltx_bibitem`×92、`ltx_caption`×58、`ltx_figure`×41、
`ltx_title_{section,subsection,subsubsection,paragraph,appendix}` 齐全、
`<math alttext>` 内嵌原始 LaTeX——占位符回映与现有 ph 契约同构。

## 覆盖率探针方法

`tmp/latexml-spike/coverage-probe.txt`：36 id（corpus_v3 manifest 跨年代采样 +
hep-ph/cond-mat/math 老 id 系）逐个 `GET arxiv.org/html/{id}`，记
HTTP code / size / `ltx_para` 计数 / "HTML not available" 命中。
35×200 且全部 `ltx_para>0`（段落 DOM 非空壳）；唯一 404 cond-mat/0501286
经核实为撤稿（withdrawn）——撤稿件无 HTML 属预期行为，不构成覆盖率缺陷。

## LaTeXML 获取路径全否（裁决依据）

- **AUR/cpan 源装**：Perl 依赖树深（~80+ cpan 模块），本机/CI 构建脆弱，不可复现。
- **Docker latexml 官方镜像**：2.33GB 拉取，为降级链兜底不值这个体量。
- **latexmls 服务化**：原生 socket 协议非 HTTP，得再写协议适配层——引入比收益贵的组件。

三条路全被否决后剩下的正是 arxiv 原生 HTML——而且它**本来就是我们抓的内容**
（同域同限流，无新外部依赖）。

## 建议形态（交 overseer 裁决）

1. **HTML 降级链 = fetch `/html/{id}` → DOM 分块（复用 export/ 的 lxml/bs4 模式）
   → XlatPipeline → HtmlPane 呈现**。段落粒度天然 = `ltx_para`，公式走
   `alttext`→占位符，bib/figure/caption 记 support。
2. e-print 拿不到时它是第二条命（F 桶呼应）；e-print 在时仍走 LaTeX 主链——
   HTML 是**降级兜底不是主通道**，覆盖率 97.2% 足够兜底语义。
3. 无 LaTeXML 依赖 ⇒ Dockerfile/uv tool 分发面零变化，docs/05 §5.x 的
   「LaTeXML DOM 分块」规格改写为「arXiv HTML DOM 分块」。

证据：`tmp/latexml-spike/`（coverage-probe.txt 台账 + probe-*.html ×36 +
arxiv-html-sample.html）。src/git 未动（本报告由 leader 代笔落盘）。
