# export-fuzz — EPUB/DOCX 双语插译对抗性 property tests

> 2026-09-17 收口。交付 `tests/test_fuzz_export.py`（~1870 行，commit `58a94c1`）：**16 passed + 13 xfailed(strict)**，ruff check/format 双净。纯离线（MockTranslator + _ChaosTranslator 12 变体/_EmptyTranslator/_AuthFailTranslator），seeded 确定性。

## 覆盖矩阵

- **L1 纯函数 oracle**：`reconcile_markers`（签发 token 恰一次/sent 内未签发字面保留/臆造形剥净/一致回复逐字节/None 不炸）；`split_on_markers` 拼接还原；`normalize_text`/`sanitize_xml_text` 幂等+无 XML 非法字符+无零宽；`safe_language` 非 None 恒 `[\w-]+` fullmatch；`Ordinals.allocate` 不重发占用+`marker_name` `[A-Z_]+`+`find_markers` 全中；`is_special/apparatus/wordless/placeholder_only` 对抗串返 bool；`coerce_glossary` 缺席路径→ExportError。
- **L2 单元级直喂**：`iter_units` 80-iter hostile body 不抛+unit.text 归一化非空非 special+job_id 全本唯一+签发 token 恰一次；`insert_translation` 50-iter 臆造/丢弃/重复 marker+markup/控制字符译文不抛+插后 strict XML+签发 token 零残留+NCX 逐字节 oracle；`insert_after`（docx）克隆紧跟源段+子元素只剩 w:pPr/w:r+剥 w14:paraId/textId/sectPr+555555 戳+w:lang。
- **L3 e2e**：`translate_epub` 60-iter×Chaos——sniff==epub、testzip 过、mimetype 首条 STORED、成员集==输入∪{mimetype}、全成员 strict XML、decl encoding=utf-8、dc:language==safe_language、NCX text 二值、translated==.texlate-zh+NCX 改写、五计数==iter_units 重算、签发 token 零残留、unit 非 marker 片段⊂输出可见文本、on_result 每单元恰一次、{dst}.state 清理。`translate_docx` 40-iter——全 part well-formed、源段保序非译文子序列、译文段紧跟、译文段数==translated、w:lang/core 对账。半成品：AuthTrippedError 后 dst 仍合法出包+state 保留。`export_document` 嗅探分派；`sniff_format` 100-iter。

## 钉住的确认缺陷（8 族/9 测试函数/13 xfail case，strict）

| # | 缺陷 | 位置 | 影响 |
|---|------|------|------|
| 1 | `_serialize_soup` 直通面 | epub.py:894-903 | html.parser 宽容解析逐字节回写——`<script>a<b&&c</script>`/`<style>a>b</style>` raw-text、注释 `--`、doctype 内部子集截断、PI 含 `<`、`<p<div>` 错位 tag：合法输入产出非法 XHTML 成员（6 case） |
| 2 | `member_path` 不 normalize | epub.py:296-308 | posixpath.join 无 normpath：合法书 `href="../ch1.xhtml"` → MalformedEpubError |
| 3 | PUA 哨兵碰撞 | epub.py `_runs_for_owner` ~563/574 | `{seq}` 与源文逐字同形 → `text.replace` 先中字面位→真哨兵残留进 sent 送模型并漏进出包 |
| 4 | fragment 双根 | epub.py `insert_translation` ~860-877 | root_owner 判定只盖 html/文档根，fragment 顶层 `<p>` 走克隆→双根非法 XML |
| 5 | 空译文插出且计数 | epub `_apply` ~1030 + docx `insert_after`:314-353 | echo 判据只比 zh==src，空译文非等价原文→空 .texlate-zh 节点插入且计 translated |
| 6 | `<pre>` 内 `<br>` 词粘连 | epub.py `_separate_brs`:470-478/`_owner_events`:502-504 | pre 内 br 不切 run 不插分隔→`alpha<br>beta` 归并 `alphabeta` 错词送模型 |
| 7 | mimetype 直通 | epub.py `save_epub`:946-954 | 输入 mimetype 成员内容照抄→垃圾进出包，sniff_format 不可识别 |
| 8 | 超深嵌套 RecursionError | epub.py `iter_units`:589 `body.descendants`+`soup.encode` 递归 | ~2000 层行内嵌套裸逃 RecursionError，不属 ExportError 族 |

## 未钉观察项

- NCX 单元只查 `is_placeholder_only`，不查 wordless/special——与 body 单元口径不对称。
- `_separate_brs` 就地改源 DOM（book.soups 被 mutate），迭代后再 load 才见原文——语义可辩。
- `on_result` 回调异常在 pipeline.py 翻译循环被吞——与 xlat 主链同策。
- 源文自有 `[[X_n]]` 字面 token 跨 unit 各自保留合法（literal 判定 per-sent）。
- docx 克隆剥 w14:paraId/textId 实证无残留；畸形 `word/footnotes.xml` → "该面跳过翻译" 优雅降级（容错正确）。
- unit.text 排除 Comment/PI/CData——`_owner_events`:522 exact-type 过滤，oracle 已对齐。
