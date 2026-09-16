# export-sweep — export/ + align + probe + normalize + textutil 残余审计

> 2026-09-16。scope：`src/texlate/export/`、`align.py`、`compile/probe.py`、`compile/normalize.py`、`textutil.py` + 对应测试。5 文件 +16/−23，scope 测试 154 全绿、ruff select=ALL 净、vulture 复扫描仅误报。

## 处置清单（已落盘）

1. `compile/probe.py` — 删 `consume_deps`（零调用方薄包装，worker 直接用 `deps_diff`；未进 `compile/__init__.py` 再导出面）+ `__all__` 项 + `CompRes` TYPE_CHECKING import（其唯一使用点）。
2. `export/epub.py` — 删 `Unit.doc_path`/`Unit.doc_index` 死字段（构造后全仓零读；job_id 已内嵌 `epub:{doc_index}:{path}:…`，溯源不丢）+ 两处构造点 kwargs。
3. `export/docx.py` — `_part_root` XMLSyntaxError 静默丢 part → `log.warning`（footnotes/comments 坏 XML 此前无痕迹不翻）；新增 module logger。
4. `export/epub.py` — `_restamp_opf` UnicodeDecodeError 静默 return → `log.warning`（dc:language 静默过期）。
5. `compile/normalize.py` — `_kpse_resolve` OSError/SubprocessError → `log.debug`；`_try_shadow` read_bytes OSError → `log.debug`（遮蔽缺失→invalid_utf8 此前无迹可溯）；新增 module logger。
6. `align.py` — `_dest_page` 异常 → `log.debug`；`_match_figure_regions` 单页 content-stream 崩溃 → `log.debug`。

## 审计记录（未动，附理由）

- TODO/FIXME/XXX/HACK：scope 内零命中。
- vulture 误报排除：`inject_preamble`/`source_path_violations`/`normalize_project`（compile/__init__ + e2e/worker/tests 在用）；`prefer_engine`/`declared_in`/`DepsDiff.unseen,extra,saw`（worker._probe_target + tests 消费）；`ExportReport.skipped`（cli.py:634/worker.py:3331 读）；`docx _blob`/`val`（python-docx 外部对象属性写入）；`DocxUnit.part_name`（docx.py:318 读）。
- 其余 except 均为有意降级且已留痕或文档化：`__init__.py` sniff→UnsupportedFormatError 上浮；`common.py` partial save 有 `log.exception`；`epub.py` NCX 有 `log.warning`；`rights.py` 判反即 drm；`probe.py` 索引失败→`index_available=False`+notes 上报；`textutil.py` 解码兜底链是设计语义；`align.py` pypdf 缺席/单侧坏→pages 降级已有 `log.debug`；`normalize.py` NUL 闸/PS 早退均有内联文档。

## 规格对账

- `research/latex/doc-formats.md` §2.5 Unit 契约 `{job_id,text,markers,context_group}`：实现无 `context_group`（spec 自注「分组建议直接 token 预算」——XlatPipeline 全局批量即此路径）；删死字段后 Unit 内部面与 spec 精神一致。§2（DRM 预检/fixed-layout 拒翻/marker 协议/mimetype ZIP_STORED/NCX 原文-译文/nav translation_host/dc:identifier 不动/bs4 html.parser）与 §3 逐条对上。
- `research/product/web-layer.md` §5.4：`{kind,heights,pairs,regions}` build_alignment 输出逐项一致。
- `docs/08` §3.2：十二项清单逐条对应（1–8/10 在 normalize_engine；9/11/12/13 工程级在 normalize_project）；`_transcode_support_files` 是 spec `_transcode_aux_bib` 超集（+PS 注释净化+catch-all），spec 落地注记已覆盖。§3.4 target_probe 差异 spec 落地注记已自记。
- §3.2 项 5「注入缝 = `\begin{document}` 前」：实现把兼容前导块放文件顶——`\PassOptionsToClass` 必须先于 `\documentclass`，文件顶是必需位置，行为正确仅措辞松。

## 残余建议（结构性，未动）

1. `epub.py`：无 `<body>` 的畸形 xhtml 下 owner 退到 document 根，`_insert_clone_translation` 可能对根 `insert_after` 抛错——罕见畸形输入上会崩（可闻错误非静默），仅记录。
2. `normalize_engine` 对 `\documentstyle`（latex209）文档也前置 `\AddToHook`——2.09 无此命令会编译错；inject gate + fixloop `latex209_reject` 已兜底拒，belt-and-suspenders 不单独修。
3. `export_epub`/`export_docx` 两个转调包装目前仅 `export_document` 内部用——公共 API 面预留，非死代码。
4. `DepsDiff.seen` 仅测试消费——诊断 API 面，保留。
