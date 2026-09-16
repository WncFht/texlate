# export-verify — EPUB/DOCX 真实输出结构级验证（38/38 PASS + 2 探针，零缺陷）

> 2026-09-17 收口。验证型零代码改动。`tmp/export-verify/` 造输入（3 章 EPUB 含 code/img/figcaption/实体/字面[[IMG_1]]/li、python-docx DOCX 含 paraId/noBreakHyphen/vanish/hyperlink/表格/sectPr/注入 footnotes、无 body 畸形 EPUB、30 章 big.epub、glossary.csv）全走 `uv run texlate export --mock` CLI 真路径。

## 验证矩阵（全 PASS）

**EPUB**：mimetype 首条 ZIP_STORED；OCF 骨架齐；全部 xhtml/opf well-formed；原文保留+texlate-zh 插译交替（zh span 均有前行源段）；源 id 不连坐；`dc:language→zh-CN`；NCX `原文 / 译文`；`<code>` marker 往返 2x；figcaption 内部追加；img 成对（源/译 2=3）；字面 `[[IMG_1]]` 保留/`[[IMG_2]]` marker 不漏；li 插译；`.texlate-zh{color:#555}` 注入 head。
**EPUB 边界**：nobody.epub 锚定插译成功+单 `<html>`+warnings 留痕（`no <body>; owner=html`）；big.epub 30 章 150 单元全插译；`{dst}.state/` 成功即清理。
**DOCX**：`[Content_Types].xml`/document/styles/footnotes.xml 齐；document.xml well-formed；**w14:paraId/textId 克隆剥除（1x）**；**w:sectPr 不连坐（2x）**；**noBreakHyphen→`-`**；脚注插译；python-docx 重开正常、译文段全奇数位严格交替；译文 run eastAsia=SimSun+color=555555+w:lang zh-CN；**vanish 不遗传/bold 继承**；pStyle ListNumber 继承；表格单元格+hyperlink 段插译。
**glossary**：`--glossary csv` CLI 接受+探针确认 `transformer: 变压器` 注入 system prompt 尾块。

## 结论

docx-sweep 8 修（`d600c44`）+ epub-nobody（`ce7d982`）在真产物上全部体现——**零缺陷**。epubcheck 本机未装 SKIP 记档（结构断言已覆盖 OCF 硬约束）。产物 `tmp/export-verify/` 可重跑（make_inputs.py/verify.py/glossary_probe.py）。
