# export-realbook-2026-09-16 — 真书 EPUB 双语插译回归

`src/texlate/export/` 的真实文档补验（此前测试全为手工最小构造）。驱动脚本 `bench/py/export_realbook.py`，语料为 Project Gutenberg 公版 EPUB（`tmp/realbook/`，gitignored 不入库），翻译器为 `MockTranslator`（`这是译文` 固定串，占位符契约天然成立）。

## 语料

| 文件 | 书 | 体量 | 成员 | spine 文档 |
|---|---|---|---|---|
| pg1080.epub | A Modest Proposal (Swift) | 258 KB | 13 | 5 |
| pg1952.epub | The Yellow Wallpaper (Gilman) | 224 KB | 12 | 4 |

两本均为 Ebookmaker 产出的 EPUB3（带 EPUB2 兼容 NCX、pgheader boilerplate、页码 pagebreak 标记）。`check_epub` 判 `ok`（无 DRM）。

## 结果

全链 `translate_epub` 成功，断言全过（明细 `report.json`）：

| 书 | units | 插译节点 | NCX 双串 | multi-run | marker | fault | 重复 id | EbookLib |
|---|---|---|---|---|---|---|---|---|
| pg1080 | 105 | 101 | 4 | 5 | 0 | 0 | 0 | 开 |
| pg1952 | 334 | 331 | 3 | 2 | 0 | 0 | 0 | 开 |

断言覆盖：出包 `mimetype` 首条且 `ZIP_STORED`；zip 成员数与源一致；每个 spine xhtml 可解析、`.texlate-zh` 节点数恰等于非 NCX unit 数（101/331 逐一对账）；全部文档无重复 `id`（RSC-005）；`nav li` 无嵌套塌缩；NCX `navLabel` 全部呈 `原文 / 译文` 双串；`warnings` 为空（439 unit 无一触发 marker 调和——真书 PG 文本无短保护行内元素命中 marker 路径，该路径由 `test_export_epub.py::test_marker_roundtrip` 单测兜底）。

## 观察

- multi-run owner 真实出现（7 例：如 `<div>` 直持文本又嵌 `<p>`），锚定插译路径被真书踩到。
- pg1952 的 boilerplate `header.pgheader` 含大量 Gutenberg 许可样板文本——正常计入插译（它不是 NON_CONTENT，阅读器确实渲染）。
- EbookLib（AGPL，仅作 reader 级验证工具、非依赖）两本均正常打开枚举 items。
- 未跑 epubcheck（无 java 运行时）；结构化断言已覆盖其最常挂的 mimetype/id/容器面。

复现：`uv run --with ebooklib python bench/py/export_realbook.py <epub...>`
