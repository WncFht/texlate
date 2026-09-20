# ADR-0018 导出格式：EPUB/DOCX 双语插译——stdlib zipfile + python-docx，绕开 AGPL 库

> **状态**：现行
> **日期**：2026-09-15（05 E16 证据 + 导出裁决）

## 上下文

双语对照不只在阅读器里看：EPUB（阅读器/手机带走）与 DOCX（可编辑交付）是两个高价值导出形态。E16 对生成链做了选型实测：EPUB 生态里最顺手的 EbookLib 是 AGPL——与主仓 Apache-2.0 冲突；DOCX 的 python-docx 是 MIT 可用。插译结构（逐段 en 段紧跟 zh 段）比「前英后中两册拼接」阅读体验好得多。

## 裁决

- **EPUB 手搓**：stdlib `zipfile` + `bs4` 直写 OPF/NCX/XHTML——EPUB 就是 zip + 几个 xml，EbookLib 省下的代码量不抵 AGPL 传染风险；**不引 EbookLib**。
- **DOCX 用 python-docx**：`deepcopy(w:p)` + `addnext` 在段落级插译——保留原文档样式/图/表的容器结构，译文段克隆源段样式落位。
- **共享契约**：两格式共用 `translate/translate_list` 接口与双语段对数据结构（dual 语义）——导出是 dual.json 的下游消费者，不各自重发明译文摘取。
- **许可红线复查**：任何新导出格式先查依赖许可再动手（EPUB 教训已沉淀为规则：「生成库先看 LICENSE」）。

## 理由

- E16：EbookLib AGPL 排除 + python-docx 段落级可操作性实测可行；EPUB 手写量 ~百行级，可控。
- 双语插译（en 段 + zh 段交替）是对照阅读的格式层等价物——与阅读器双 pane 同语义、不同载体。
- 证据：主仓 `docs/05` E16；调研档案 `research/latex/doc-formats.md`。

## 演变

- 无改判。导出能力随 server 产物面暴露（files 表登记 + CLI `texlate export` 子命令同口径）。

## 现状

实现落在 `export/` 包（EPUB/DOCX 两叶 + 共享 dual 消费契约）+ `cli/` `export` 子命令。插译保真面（样式克隆、目录、图片容器）以测试套件与 doc-formats 调研记录为准。
