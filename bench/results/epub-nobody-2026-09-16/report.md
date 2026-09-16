# epub-nobody — 无 `<body>` 畸形 xhtml 防崩（export-sweep 残余 #1）

> 2026-09-16/17。scope：export/epub.py + test_export_epub.py。35 测试过、ruff 净。

## 机理

`iter_units`（epub.py:566）owner fallback：`body = soup.find("body") or soup`，`owner = _nearest_block(node) or body`。无 `<body>` 时 body 退成文档根；根级裸文本/inline 节点 `_nearest_block` 返回 None → **owner = soup 根**。

克隆路径 `_insert_clone_translation` 调 `owner.insert_after(new_p)`——bs4 4.15 的 `BeautifulSoup.insert_after` 是显式 override：`raise NotImplementedError`，单 unit 炸掉整条 `translate_epub`。

触发形态实测：纯文本文档、`<?xml?><p>x</p>stray text`、`<?xml?><a>text</a>` 根级 inline。同族次生缺陷：`<?xml?><html>text</html>` → owner=`<html>` → `html.insert_after` **造出第二个顶层 `<html>`**（不崩但静默污染）。

## 修法：锚定回退

`_insert_anchored_translation` 锚定 `run_nodes[-1]` 行内根——`tail.insert_after` 走 PageElement 版只要求 `tail.parent` 非空（根级节点 parent=soup，落得住）；译文照样交付，比 skipped 丢译文更贴产品语义。

document 级 owner（`owner.name == "html"` 或 `isinstance(owner, BeautifulSoup)`）并入既有 `is_multi_run or owner.name == "body"` 锚定分支——`<html>`/文档根与 `<body>` 同属不可克隆层。该分支记 `report.warnings`（`{job_id}: no <body>; owner={name} — translation anchored after run`），可闻但任务不死；warning 只挂 html/soup owner，multi_run 常规 block 不误报。`BLE001` 严格集内 anchored 覆盖全形态，不需 try/except 兜底。

## 改动

- `export/epub.py:822-840`（`insert_translation`）：`root_owner` 判定 + elif 扩条件 + warning 合并。
- `tests/test_export_epub.py`：`_epub_raw` helper + `test_no_body_doc_anchored_not_clone` 参数化四格（bare-text/stray-root-text/html-stray-text/html-only-text）——断言 fault==0、translated==units、warnings 含 `no <body>`、输出有 .texlate-zh 且 `find_all("html") <= 1`。

## 验证

`pytest test_export_epub/test_export_docx/test_cli_export` → 35 passed；`pytest -k "export or epub"` → 56 passed；ruff 双链净。探针：bare-text → `text<br/><span class="texlate-zh">zh</span>` 落文档根；html-direct → 无第二 html；`<a>`-root → anchored 克隆保留 href。

## 残余

- `translated` 仍 +1（译文确实落盘，warning 记路径异常非失败）。
- `<frameset>` 等更畸形结构未单测，同走 soup-root 锚定机理一致。
- 输出仍非合法 EPUB content doc（输入即畸形）——管线保证不崩+译文可达；epubcheck 合规不在 v1 边界。
