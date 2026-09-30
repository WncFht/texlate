# 文献清单：语料、PDF 翻译与文档智能参照系

> **结论**：调研留存的 14 件文献档归并为 11 项参照——arXiv 语料集（unarXive ×2、arXMLiv、S2ORC）、PDF 侧保版翻译（PDFMathTranslate、BabelDOC）、文档智能模型与评测（Nougat、olmOCR）、一件内部生态调研快照，及两件无法判读意图的抓取残档。
> **状态**：现行
> **日期**：2026-09-20

## 留存件清点

| 留存文件              | 判定                                                      |
| --------------------- | --------------------------------------------------------- |
| unarxive2020.pdf      | unarXive 2020 论文（Scientometrics 2020）                 |
| unarxive2022a.pdf     | unarXive 2022 论文（arXiv 预印本，2023）                  |
| unarxive2022b.pdf     | 与 unarxive2022a.pdf 字节级相同的重复副本                 |
| kitopen_record.html   | KITopen 数据仓中 unarXive 2022 数据集的记录页             |
| arxmliv_stats.html    | 空文件（0 字节），抓取失败残档，意图应为 arXMLiv 统计页   |
| sig.html              | 19 字节「404 page not found」，原抓取意图无法判读         |
| nougat.pdf            | OpenReview 403 错误页 HTML，非论文本体                    |
| nougat2.pdf           | OpenReview 挑战验证 JSON 错误，非论文本体                 |
| nougat3.pdf           | 同上（同一附件的第二次失败抓取）                          |
| babeldoc.pdf          | BabelDOC 论文（ACL 2026 System Demonstrations）           |
| pdfmathtranslate.pdf  | PDFMathTranslate 论文（EMNLP 2025 System Demonstrations） |
| s2orc.pdf             | S2ORC 论文（ACL 2020）                                    |
| multiagent-survey.pdf | 内部生态调研快照（8 页），非外部出版物                    |
| olmocr_tests.py       | olmOCR 仓评测件源码快照                                   |

## arXiv 语料集

### unarXive（2020）

Saier & Färber 的 unarXive：把 arXiv LaTeX 源码大规模转换为结构化全文、标注文内引用并链接元数据的学术数据集[^unarxive20]。本项目从它拿了什么：arXiv 源码→结构化全文转换的可行性先例与规模参照；其「LaTeX 源比 PDF 携带更富结构」的论据是 texlate 选源码路线的直接支撑。

### unarXive 2022 (2023)

Saier、Krause & Färber 的 unarXive 2022：全量 arXiv 预处理的 NLP 语料，含结构化全文与引用网络[^unarxive22]；kitopen_record.html 是 KITopen 数据仓中该数据集的正式发布记录页[^kitopen]。本项目从它拿了什么：全量 arXiv 语料的构建口径（版本覆盖、全文结构标注、引用边抽取），以及语料层设计与评测规模的蓝本。（留存两件 PDF 字节级相同，实为同一份 arXiv 预印本。）

### arXMLiv

arxmliv_stats.html 为 0 字节空文件——抓取失败的残档，留存意图应为 arXMLiv 项目的构建统计页；arXMLiv 是 latexml 驱动的 arXiv→XML/HTML5+MathML 转换语料，LaTeX 结构化标记路线最长寿的先例[^arxmliv]。本项目从它拿了什么：LaTeX→标记语言的成熟工具链（latexml）对照与解析质量维度。

### S2ORC

Lo、Wang、Neumann、Kinney & Weld 的 S2ORC：8,100 万篇论文的元数据 + 全文规范化语料（ACL 2020）[^s2orc]。本项目从它拿了什么：学术文档跨源规范化与元数据链接的工业级先例；与 LaTeX 源路线互补的对照系。

### sig.html — 出处待核

19 字节残档，内容为「404 page not found」，原抓取目标与意图均无法判读，仅清点存目。

## PDF 侧保版翻译

### PDFMathTranslate（PDF2zh）

Ouyang、Chu、Xin & Ma 的 PDFMathTranslate：首个开源的保版式学术 PDF 翻译软件（EMNLP 2025 系统演示）[^pdf2zh]。本项目从它拿了什么：PDF 级保版翻译的直接先驱——版式检测→翻译→重渲染流水线、数学式保护与双语对照的产品形态蓝本；其 PDF 文本提取损耗同时反证了源码路线的必要性。

### BabelDOC

Qi、Ma、Wang、Wang & Wang 的 BabelDOC：PDFMathTranslate 同组的后继，以中间表示（IR）解耦版式与语义、经自适应排版回锚的 PDF 翻译框架（ACL 2026 系统演示）[^babeldoc]。本项目从它拿了什么：IR 驱动的版式保持方案、公式占位符化（formula placeholdering）与术语约束生成的文档级设计；也是 texlate PDF 臂的借鉴与互操作对象。

## 文档智能模型与评测

### Nougat

Blecher 等（Meta AI）的 Nougat：端到端视觉模型把学术 PDF 直接转成 markup（ICLR 2024）[^nougat]。留存三件（nougat.pdf、nougat2.pdf、nougat3.pdf）均为 OpenReview 403/挑战验证的抓取失败残档，非论文本体——条目按公开出处计。本项目从它拿了什么：「PDF→模型→标记」路线的代表，作为源码路线的对照——texlate 绕过其 OCR 不确定性，直接消费 LaTeX 真值。

### olmOCR 评测件

olmocr_tests.py 是 allenai/olmOCR 仓库评测件（tests.py）的源码快照[^olmocr]：用「可执行判据」评估 PDF→markdown 转换质量——baseline/present/absent/order/table/math/format/footnote 八类判据加模糊匹配阈值。本项目从它拿了什么：校验器判据分层与「判定即代码」的设计参照，启发了占位符契约校验器的硬/软判据划分。

## 内部调研件

### Subagents / Multi-Agent 生态调研

multiagent-survey.pdf 为一份内部生态调研的 PDF 快照（标注 2026-09-14，8 页），内容为主流编码代理的 subagent/多代理编排生态；非外部出版物，出处待核（疑为项目调研件导出）。留存价值：代理编排模式与工具面调研底稿。

### 参考文献

[^unarxive20]: Saier, T., & Färber, M. unarXive: a large scholarly data set with publications' full-text, annotated in-text citations, and links to metadata. Scientometrics 124, 2020. [arxiv.org](https://arxiv.org/abs/2003.04022)

[^unarxive22]: Saier, T., Krause, J., & Färber, M. unarXive 2022: All arXiv Publications Pre-Processed for NLP, Including Structured Full-Text and Citation Network. arXiv:2303.14957, 2023. [arxiv.org](https://arxiv.org/abs/2303.14957)

[^kitopen]: Saier, T., Krause, J., & Färber, M. unarXive 2022（数据集记录）. KITopen, DOI 10.5445/IR/1000174916, 2023. [doi.org](https://doi.org/10.5445/IR/1000174916)

[^arxmliv]: arXMLiv 项目（latexml 驱动的 arXiv→XML+MathML 语料）. [arxmliv.kwarc.info](https://arxmliv.kwarc.info/)

[^s2orc]: Lo, K., Wang, L. L., Neumann, M., Kinney, R., & Weld, D. S. S2ORC: The Semantic Scholar Open Research Corpus. ACL 2020. [arxiv.org](https://arxiv.org/abs/1911.02782)

[^pdf2zh]: Ouyang, R., Chu, C., Xin, Z., & Ma, X. PDFMathTranslate: Scientific Document Translation Preserving Layouts. EMNLP 2025 System Demonstrations. [aclanthology.org](https://aclanthology.org/2025.emnlp-demos.71/)

[^babeldoc]: Qi, Y., Ma, X., Wang, X., Wang, H., & Wang, R. BabelDOC: Better Layout-Preserving PDF Translation via Intermediate Representation. ACL 2026 System Demonstrations. [aclanthology.org](https://aclanthology.org/2026.acl-demo.25/)

[^nougat]: Blecher, L., Cucurull, G., Scialom, T., & Stojnic, R. Nougat: Neural Optical Understanding for Academic Documents. ICLR 2024. [arxiv.org](https://arxiv.org/abs/2308.13418)

[^olmocr]: Allen Institute for AI. olmOCR 工具包与评测件。[github.com/allenai/olmocr](https://github.com/allenai/olmocr)；olmOCR: Unlocking Trillions of Tokens in PDFs with Vision Language Models. [arxiv.org](https://arxiv.org/abs/2502.18443)
