# docs/ 写作与维护约定

文档 hygiene 三条约定：SUPERSEDED 标记、research/ 索引登记、勘误引用粒度。问题清单与动机见 `docs/research/roadmap-2026-09-17/inputs/docs-health.md`。

## SUPERSEDED 标记

文档被后续裁决或实装取代时，不删文件、不改写历史正文；在标题下加一条 blockquote 横幅，标日期、一句过期范围、继任者路径：

> **⚠️ SUPERSEDED YYYY-MM-DD**：<什么判定已过期>。现状唯一事实源 = `<继任者路径>`；本文仅留<取证过程等>作历史参考，勿再据此派工。

范例：`docs/research/audit-2026-09-16/m3.md`（M3 现状判定被 `bench/results/m3gap-scout-2026-09-17/report.md` 改判后挂横幅）。时效性结论（免费额度、默认模型、配额数字）过期等同被改判，同样处理。

## research/ 索引登记

- 新报告或新目录入库时，在 `docs/research/README.md` 登记一行：主题件进对应主题表（arxiv/latex/corpus/gateway/product），审计/保全/评审/排期类日期化快照目录进「日期化快照目录」表，跨主题单件进「根目录散件」表。
- 规范文档与勘误引用的裁决证据必须落在 `docs/research/` 或已入库的 `bench/results/` 路径；untracked 区文件不作引用源（有丢失与断链双重风险）。
- 日期化快照目录自带 README 的，其内部分报告表由产出方同步维护。

## 勘误引用粒度

- 行号锚点（`file.py:NNNN`）只是时点快照，拆包即失效——仅用于「当时取证」语境。
- 规范勘误与长期引用写「模块+符号」粒度（如 `worker/compile.py::_probe_target`），不写裸行号。
