# ADR-0002 LaTeX 半解析：自研 scanner + pieces 区间 splice

> **状态**：现行
> **日期**：2026-09-15（05 裁决 1）

## 上下文

LaTeX 是图灵完备的宏语言——`\def`/条件/catcode 让「正确解析」等价于实现 TeX 求值器，hjfy 同样走自研半解析。调研期对 8 个现成库 + 自研 spike（miniscanner，1176 行纯 Python）做了 39 项目/256 tex + 30 陷阱的大横评：**全部现成库在宏展开上全灭**（`\be→\begin{equation}` 类结构性宏真实语料 12/39 篇存在），且「能 parse」≠「parse 对」——pylatexenc 交出 90/90 的假成功率（组内 `\begin` 吞至 EOF、`%` 吃 `}`，99% 损失零报错）。

## 裁决

自研半解析器，**不做 AST 全量重建**：单次正向逐字符扫描产出 token/segment 流，每段记 `byte_range + kind`，可译段标 `chunk_id`，不可译段替换为 `[[TYPE_n]]` 占位符；译文回来按 byte_range **区间 splice 回原文**——identity 逐字节一致是硬验收。

机制要点：

- **piece 边界纪律**：块级结构必须独立 piece，边界 token 不并入 chunk（根治 ieeA 死 token）。
- **保护清单**：数学全族（`$…$`/`\(\)`/`\[\]`/`$$…$$`+equation/align 等环境族）、引用全族（`\cite*`/`\ref`/`\eqref`/`\label` 等）、`\url`/`\href`（只翻显示文本）/`\verb`/verbatim/comment 环境原样、作者块整段保护、结构命令 `\section[opt]{t}` 可选参数保留必译参数挖 chunk、`\if/\else/\fi` 条件块结构保护。
- **分段器硬要求**：`\input`/`\include`/`\label`/`\bibitem` 必须留占位符侧、绝不进可译 chunk（连续 `\input` 被当单 chunk 吞会连锅端掉锚点与正文，E18 实证 258 锚丢失）。
- **未知命令/env 降级**：未知命令保护 token 不吃参、未知 env 按 `body_role=text` 处理、畸形宏定义降级为不透明整体保护。
- 宏展开层的设计单独成 ADR-0003；校验链见 ADR-0004。

## 理由

- E1：miniscanner spike 259/259 文件、32/32 陷阱、0.11% 泄漏、identity 100%、1.3ms——半解析 + 区间 splice 路线被实证。
- E2：25 处残留泄漏归因为 4 机制（单 token 误吃参 / in-arg 注释 / env `*` / in-arg 条件式），全部有修法——按重写规格落地为产品代码。
- AST round-trip 不可行：严格解析器在真实脏语料必破（语料含真·缺 `$` 文件）；pieces 覆盖全文 + identity 逐字节一致证明「宁粗勿断」。
- 未知命令如果按 argspec 吃参，自定义宏（横评未覆盖 ≈22% 出现）会把正文吞进参数；宁可漏译不可错译。
- 证据：主仓 `docs/05` E1/E2/E3（argspec 覆盖 78.6%/98.9%）；调研档案 `research/latex/miniscanner-rewrite-spec.md`、`research/corpus/parsebench-v1.md`。

## 演变

- 2026-09-15：v1 九文件落地（tables/model/placeholder/macro_table/scanner/flatten/reconstruct/api）。
- 2026-09-16：v2 重写为 `gullet/`+`segmenter/` 独立包并 cutover（splice 残留占位符 1524→0 清零），v2 成为唯一解析路径；E10 补丁上游化（`_args` 不跨 `\` 语科级 bug、bare `\input` 文件名、DIM/DELIM boundary、cjk_glue_fix）。
- 后续持续修泄漏：leak 0.11%→0.046%→**0.040%**（corpus 约 3900 文件口径，57 条残留清一色 `dollar` 族——`$` 跨 chunk 边界失配单类债）。

## 现状

实现落在 `latex/` 包：`mouth.py`+`flatten.py`（输入展平）→ `gullet/`（宏展开，ADR-0003）→ `segmenter/`（pieces+chunks+占位符）→ `reconstruct.py`（DAG memoized 展开回写）+ `tables.py`/`model.py`/`placeholder.py`/`macro_table.py`/`api.py`/`prose.py`；签名表 `latex/data/argspec.json`（1820 条，装载零 GAP）。parsebench 口径：identity 100%、leak 0.040%。
