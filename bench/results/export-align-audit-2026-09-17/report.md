# export-align-audit — export/ + align.py 审计交付

> 2026-09-17 收口。落地 `2e2e15d`（export/{__init__,common,docx,epub,filters}.py + align.py + 三测试文件，+441/-41）。自验 `-k "export or align"` 95 绿、ruff 双净。探针 tmp/export-align-audit/。

## 修复清单（10 项）

1. **percent-encoded manifest href 找不到成员**（epub.py:296 `member_path()`）——`href.split("#")[0]` → `unquote` 优先、原样兜底，统一供 ncx_path/spine/extra manifest 三处。`href="ch%201.xhtml"` 指成员 `ch 1.xhtml` 原拼字面 `%20` 落空，整本被拒（InDesign/转换器产物普遍 percent-encoded）。
2. **成员级坏 CRC/加密/未知压缩穿透 ExportError 族**（epub.py:255）——`zf.read(info)` 包 `(OSError, RuntimeError, NotImplementedError, BadZipFile) → MalformedEpubError`；原裸 BadZipFile 绕过 CLI `except ExportError` 变 traceback。
3. **XML 非法字符三层净化**——filters.py `sanitize_xml_text`（\x00-\x08\x0b\x0c\x0e-\x1f、孤代理、FFFE/FFFF）；normalize_text 送模型文本先净化；插入侧 `insert_translation`/`insert_after` 净化译文；序列化侧 `_serialize_soup` 全篇 + NCX 同款。bs4 透传非法字符产非法 XHTML，lxml `w:t.text=` 带 \x0b 直接 ValueError——DOCX 侧一条脏译文炸整次导出。
4. **`<?xml encoding?>` PI 陈旧声明说谎**（epub.py:889 `_XML_DECL_ENCODING_RE`）——bs4 只改写 `<meta charset>`，`encoding="ISO-8859-1"` decl 原样透传给 utf-8 字节 → 严格 XML 阅读器按 latin-1 解 utf-8。
5. **sniff_format 未知压缩方法裸炸**（__init__.py:66）——except 补 `NotImplementedError`（method 99 等）→ 返回 None。
6. **缺 mimetype 输入产出非法 EPUB**（epub.py:949）——`save_epub` 无条件先写 `book.members.get("mimetype", b"application/epub+zip")` ZIP_STORED，守 OCF 硬约束。
7. **nav landmark 被克隆成两份**（epub.py:862）——受限容器条件补 `owner.name == "nav"`：`<nav epub:type="doc-toc">` 直挂文本走克隆路径曾把 epub:type 复制成第二个 landmark（EPUBCheck 违规）。
8. **target_lang 注入 OPF/run 属性**（common.py `safe_language` + epub `_restamp_opf`/`_stamp_translation` + docx `insert_after`/`core_properties.language`）——`[\w-]+` fullmatch 非 BCP47 → None 早退；`target_lang='zh<x="1">'` 曾让 OPF 变非法 XML（正则 splice 无转义层）。
9. **marker 哨兵 \x00 被新净化吃掉**（epub.py:574）——换 PUA 段 `{seq}`（EE8080/EE8081 实测），与新 sanitize 共生。
10. **align per-op 容错**（align.py:290）——`cm` 六参 float 化包 try（TypeError/ValueError→debug+跳）；`Do` arm 的 `args[0] not in resources` 移进 try——ArrayObject operand 的 `in` 抛 TypeError，原整页 regions 全丢现只丢该算子。

## 新测试（+13）

epub ×9（percent-encoded href、坏成员 Malformed、控制字符剥除 ×2、非 utf-8 decl 重打、缺 mimetype 兜底、nav 不双 landmark、target_lang 注入闸、未知压缩 method）、docx ×2（控制字符、hostile target_lang）、align ×2（畸形算子只丢自身、同位锚 `<=` 链回归钉）。

## 未修（理由）

- `_graphic_regions` 整页扫描崩只丢该页：`_match_figure_regions` 外层 try 已有，per-op 加固已到可行粒度。
- 畸形 XHTML 输入不拒翻：html.parser 宽容是既定口径，产出侧 `_serialize_soup` 净化兜底。
- 探针证伪不列修：python-docx `add_run` 自动折 `<w:br/>`；multi-run 锚定/空 units/无 body 正确；PdfReader 无 fd 泄漏；pypdf 容忍未知 op；docx sectPr/paraId 不连坐克隆。

## 外部路由（记录不动手）

- `common.py:163` `store.load()` 在 except-BaseException 半成品回放路径若 jsonl 自身损坏会二次抛盖原异常——StateStore.load 容错契约归 xlat scope（已审）。
- chunks.jsonl 缺失/乱序/超大边界——results 以 chunk_id 键控、缺块自然重翻；批量协议归 xlat scope。
- server 侧 export 调用面（worker/app）不在本 scope。
