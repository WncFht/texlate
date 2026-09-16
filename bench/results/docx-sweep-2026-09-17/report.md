# docx-sweep — export/docx.py 残余审计+小修

> 2026-09-17。scope：`src/texlate/export/docx.py` + `tests/test_export_docx.py`。66 测试绿、ruff 净。前置报告已覆盖项（`_part_root` XMLSyntaxError warning、epub 无 body 锚定）未重复。探针先行验证全部疑点后才动手。

## 处置清单（已落盘）

1. **无 `w:body` 畸形 document.xml** — `doc.element.body=None` 时 `body.iter` 崩裸 `AttributeError`；`_iter_surfaces` 入口 raise `UnsupportedFormatError`（worker/cli 统一 catch `ExportError`；docx 侧缺 body 是致命畸形，无 epub 式锚定落点）。
2. **隐藏 run rPr 污染译文（样式污染，实锤）** — `_first_rpr` 旧版取直系 `w:r` 首个 rPr：`w:vanish`/`w:specVanish` 隐藏 run 的 rPr 克隆进译文 run → **译文段在 Word 整段隐形**；`w:hyperlink`/`w:sdt`/`w:smartTag` 包裹段落则拿不到 rPr（findall 只查直系子）。改为 `w:t` 驱动——取首个可见文本 run 的 rPr，`_protected` 顺带排隐藏 run 与嵌套 `w:p`。
3. **`w:specVanish` 隐藏文本送模型** — `_protected` 只查 `w:vanish`；specVanish run 文本被拼进 unit（探针实测 `visiblespechidden`）。新增 `_HIDDEN_PROPS=(vanish,specVanish)`。
4. **`mc:Fallback` 双计（实锤）** — `mc:AlternateContent` Choice/Fallback 是同内容双份序列化（Word 文本框 VML 兜底），descendant iter 两侧各产 unit（探针实测同文本两 unit、digest 相同）→ 同一文本送模型两遍。`_in_mc_fallback` 祖先判据 + `_iter_paras` 统一过滤（body 与附属 part 同规则）。
5. **`w14:paraId`/`w14:textId` 克隆重复** — deepcopy 把逐段唯一锚点 id 复制给译文段（epub `_strip_duplicate_ids` 同类）；克隆后 pop 两属性。
6. **`w:noBreakHyphen` 丢字符** — 可见字符不在抽取映射，`non‑breaking` 被粘成 `nonbreaking` 错词；并入 `_LITERAL_NODE`（原 `_WS_NODE` 更名）→ `-`。
7. **`w:lang` 译文戳** — texlate-zh 在 docx 侧的语义等价物：译文 run rPr 补 `w:lang @w:val + @w:eastAsia = target_lang`（`OxmlElement` + `insert_element_before` 按 rPr schema 序落 `eastAsianLayout/specVanish/oMath` 前）；`insert_after` 增 `language` 参。
8. **`w:moveFrom`** — 修订移出侧补进 `_PROTECTED_ANCESTOR`（与 `w:del` 同族——移走文本不送模型）。

## 测试

新增 8 测试：no-body 拒翻、vanish rPr 不继承且继承可见 run rPr、hyperlink rPr 继承、paraId/textId 唯一、specVanish 跳过、noBreakHyphen 字符、mc:Fallback 去重、w:lang 戳。

`uv run pytest tests/ -k "docx or export"` → **66 passed**；`ruff format --check` + `ruff check` 双链净。

## 观察（未动，附理由）

- 复杂域（`w:fldChar` begin/end）缓存结果的 `w:t` 按可见文本抽取——读者所见即所翻；TOC 域整体已由 `_toc_styled` 拦，HYPERLINK/PAGEREF 缓存文本本就是可见内容。
- `w:webHidden` run 抽取正确（print 可见）；若源 run 带 webHidden 其 rPr 被克隆后译文也 web-hidden——边角形态。
- `w:sdt` `w:showingPlcHdr` 占位文本（"Click here to enter text"）会被翻译——无害小浪费。
- `mc:AlternateContent` 多个 `mc:Choice`（各含 `w:p`）仍会重复枚举——比 Fallback 罕见，同族残余。
- `w:altChunk`/`w:sym`/`w:softHyphen`/`w:ptab`/docProps 元数据/`glossary.xml` building blocks——按设计不枚举或无形符。
- docx `ExportReport.warnings` 恒空——epub warnings 是 marker 调和专属机制；docx 无对应物，跳面失败走 `log.warning`（export-sweep 已留痕）。
- `documents` 口径 = document.xml + 有 unit 的附属 part 数，与 epub「枚举文档数」语义一致。
