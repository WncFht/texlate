# repro-1306 — 1306.0067 `Extra \or`（三臂 + base 全炸）

## 判决

**非管线 bug。** 既有 source×environment 缺陷：revtex4-1 4.1s × array v2.6n on TeX Live 2026（kernel LaTeX2e 2025-11-01）。疑似 segmenter/reconstruct 列 spec 破坏**不存在**。

## 证据

1. `bench/work_e2emock/corpus_v3/base-xel/1306.0067/main.tex` 与语料解压源**逐字节一致**（diff exit 0）。同一 tabular（line 150；pipe 臂 inject 后偏移到 225/227）同一 `Extra \or`。spec 行 md5 解压版-vs-pipe 一致（`region-diff.txt`）。
2. base-xel：30 errors → Emergency stop，但表格前已 ship page [1] → partial pdf 77KB → verdict partial。pipe 臂：0 页 ship → no_pdf → fail。**同一缺陷，shipout 运气不同**。
3. log 227 行（base）：`Class revtex4-1 Info: Unrecognized array package. Please update this document class! (Proceeding with fingers crossed.)` —— 实锤。
4. `\@testpach` 插桩 trace：chclass/chnum/lastchclass 序列 article-vs-revtex **完全一致**（`>`→9、decl 组→3、`m`→10/chnum3、`{1.25in}`→0）；revtex 恰在 `{1.25in}`→`\@classz` 执行时爆炸（`trace.txt`）。

## 机理链

- revtex4-1.cls `\document@inithook` → `\@ifpackageloaded{array}`（经 dcolumn 载入）→ `\switch@array` 拿 `\@mkpream`/`\@classx`/`\insert@column`/`\@arraycr` 等对照 circa-2018 array 快照校验。
- array v2.6n 校验 FAIL → "Unrecognized array package"——**但 `\let` 交换无条件执行**：`\@mkpream←\@mkpream@array@new`（旧协议：`\@startpbox`→\relax via `\@mkpream@relax`，无 `\do@row@strut`/`\ar@align@mcell` lets）、`\@classx←\@classx@array@new`、`\insert@column←\@insert@column@array@new`（无 `\@protected@firstofone`/tagging-socket 装甲）。
- 新版 array `\@classz` 随后在 `\xdef\@preamble`（`\@addtopreamble` = `\xdef`）内发出 `\@startpbox{\@nextchar}\insert@pcolumn\@endpbox` + `\insert@column`，装甲缺失 → `\ifcase\@chnum` 展开失衡 → 孤儿 `\or` → 30× `Extra \or` → `Incomplete \iffalse` → Emergency stop。

## 复现矩阵（本目录 RESULTS.txt）

- revtex4-1+dcolumn+`>{...}m{...}`：FAIL | article+array 同 spec：PASS | revtex+ccc：PASS | revtex+`>{...}c`：PASS | revtex+`m{}` 单独：FAIL（m/p/b 路径是触发点）| pdflatex：FAIL（引擎无关）| `array[=2020-02-10]` 回滚：FAIL（checksum 覆盖 `\insert@column` 等，回滚 array 也配不上快照）。

## 补丁 —— 已验证反补丁

- 最小修复 = revtex 交换后恢复 `\@mkpream`+`\insert@column`（仅 mkpream 会 HANG；classx/insert 单独仍 FAIL；mkpream+classx HANG；**mkpream+insert PASS**；三件套 PASS）。
- 前导安全形态（已证）：`\begin{document}` 前保存 `\@mkpream`/`\insert@column`（此刻仍是 array 原版——交换在 `\document@inithook` 内跑），经 `\AtBeginDocument` 恢复（在交换之后执行）。
- **真源 E2E**：`e2e/main.tex` = 未改 1306.0067 + guard → xelatex rc=0，**0 错误，7 页 PDF**（未补丁版 emergency stop）。
- fixloop 规则草案 `revtex4_array_swap_guard`（order 170，category syntax；gate：源有 revtex4 docclass + err ctx `Extra \or`；regex_rewrite 在 `\begin{document}` 前注入 guard）：`revtex4-array-guard.yaml`。array 缺席或 checksum 通过时保存/恢复同值 → 无操作安全。备选 `\def\switch@array{}` 中和也能过，但会丢 `\@array@sw` 初始化与 revtex 合法 array 胶——guard 更外科手术。

## 含义

- fixloop 的 unfixable:syntax 是**运气好才对**的判决；上规则把这一类转成可修。n=80 爆炸半径：仅 1306.0067（签名唯一）。
- bench 记账：base 同炸 → pipe-vs-base delta 门里这是**既有缺陷**非回归；绝对 zh-pdf 门下规则落地前仍记 fail。
- 上游式已知缺陷：revtex4-1 对现代内核无人维护；TeX Live ≥2024 任何 `m`/`p`/`b` 列用法的 revtex 文档都会踩。

## 证据包

`RESULTS.txt` / `trace.txt` / `region-diff.txt` / `repro-*.tex`+logs / `e2e/`（guard 注入真源 + 7 页 pdf）/ `revtex4-array-guard.yaml`。
