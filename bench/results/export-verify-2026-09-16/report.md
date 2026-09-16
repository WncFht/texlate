# export-verify-2026-09-16 — EPUB/DOCX 真实文件验证

`src/texlate/export/` 双语插译包的真实文档全链验证。驱动 `verify_export.py`（本目录内，可复跑），翻译器 `MockTranslator`。在早前 `export-realbook-2026-09-16/`（2 本 PG 书）基础上扩展到 bbm test_books 与 arXiv 工作流真 DOCX，断言面加了 marker 泄漏、XHTML 良构、克隆段落戳、`sectPr` 连坐检查。

## 语料

EPUB 5 本：PG1080/pg1952（Ebookmaker EPUB3 + NCX + pagebreak）、Liber_Esther（bbm 测试书，拉丁语 OPF2 + `xsi:type` 属性 dc:language）、lemo（日语 ruby + 46 处 `<br>`）、animal_farm（20 篇 spine + sup + hidden + 22 外链）。DOCX 7 份：manuscript（2084 段/11 表/150 hyperlink/258 txbx/6 header）、PLM_figures_tables（5 表/5 drawing/oMath）、acl（脚注+尾注+footer+域代码+txbx）、docx_01（MinerU demo：39 oMath/55 instrText/sdt/全附属 part）、kr24（header/footer/footnote/endnote/txbx）、czxu-pub、Response_letter。

## 验证矩阵（12 文件全 PASS）

| 文件 | units | translated | unchanged | 特性命中 | 结果 |
|---|---|---|---|---|---|
| pg1080.epub | 105 | 105 | 0 | nav/NCX/pagebreak/multi-run 5 | PASS |
| pg1952.epub | 334 | 334 | 0 | nav/NCX/hidden/multi-run 2 | PASS |
| Liber_Esther.epub | 424 | 424 | 0 | OPF2/xsi:type/multi-run 15 | PASS（修后） |
| lemo.epub | 45 | 3 | 42 | ruby/br/marker 1 | PASS |
| animal_farm.epub | 409 | 409 | 0 | 20 篇/sup/hidden/marker 2/multi-run 18 | PASS |
| manuscript.docx | 881 | 658 | 223 | tbl/hyperlink/txbx 双份/header | PASS |
| Response_letter.docx | 18 | 18 | 0 | 极简件 | PASS |
| PLM_figures_tables.docx | 164 | 68 | 96 | tbl/drawing/oMath | PASS |
| acl.docx | 128 | 127 | 1 | footnote/endnote/footer/域代码/txbx | PASS |
| czxu-pub.docx | 1 | 1 | 0 | footnote/endnote part 在场 | PASS |
| docx_01.docx | 254 | 139 | 115 | oMath/instrText/fldSimple/sdt/全附属 part | PASS |
| kr24.docx | 173 | 153 | 20 | header/footer/footnote/endnote/txbx | PASS |

## 发现的 bug 与修复

1. **`_restamp_opf` 把 OPF 改残**（真书实锤）：`replace(m.group(2), language)` 字符串替换先命中 `language` 标签名里的 `la` → `<dc:zh-CNnguage>`，输出 OPF 非法 XML。改 match span 拼接。回归 `test_dc_language_with_attributes`。
2. **`insert_after` 克隆连坐 `w:sectPr`**（潜伏）：节尾段克隆复制出多余分节边界。克隆 pPr 后摘除 sectPr。回归 `test_sectpr_not_cloned`。
3. 验证侧三处计数口径修正（harness 内，非产品 bug）：`w:color` 元素名笔误、嵌套 txbx `w:p` 污染、NCX unchanged 单元计数。

## 补充单测（tests/test_export_*.py，+9 例）

EPUB：dc:language 带属性改写、字面 `[[IMG_1]]` 碰撞回避、`<img>` marker 往返、figcaption 受限容器内部追加、命名实体+裸 `&`+伪实体。DOCX：sectPr 不克隆、hyperlink 文本抽取、fldSimple/vanish 跳过、表格单元格、页眉 part。

## 残留风险

- 未跑 epubcheck / Word 实开（无 java 运行时）；结构化断言覆盖 mimetype/id/nav/OPF 良构面，epubcheck 全量对账为 spec 既定 v1 不做项。
- 复杂域跨段 TOC：`w:fldChar` 缓存结果 `w:t` 若无 TOC 样式会被翻译，译文段落域结果区内——Word 更新域即消失，无破坏但可能多余。
- 全量内存模型：本批最大 509KB EPUB/306KB DOCX 无压力，>50MB 未测。
- `text/html` manifest 形态与多 rootfile 未覆盖（罕见）。
