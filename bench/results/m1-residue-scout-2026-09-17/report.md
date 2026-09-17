# M1 harvest scout — zh/ 产出字面残留侦察

日期 2026-09-17，侦查窗口 30min（41 队令：产出受影响 id 集 + 收成估；>~50 则报回发 harvest 波）。

## 扫描面

- 主面：`stagerun-loop1-2026-09-16/work/*/zh/` —— 5059 篇 / 10926 tex（mock 译 `这是译文` 标记面，字面残留逐字存活可检）
- 小面：`work_fixloop`/`work_compile`/live-smoke 系 ~235 文件（同法扫过，量小不改结论）

## 方法

逐行以 `这是译文` marker 切 cell，剥 `%` 注释 / `\begin{env}[opt]` / `\\[opt]` / `\cmd[opt]{arg}×3` / `$..$`（含未闭合尾）后，对 cell 残文匹配四类残留签名：graphicx kv 键（`origin=`/`width=`/`trim=`…）、括片 dimen/乘数（`[3cm]`/`{n}{*}`/`{*}`）、孤立位置括号（`[tcb]`/`[TBLRH]`）、裸 dimen/glue 原子（`1em plus 0.5em`）。

关键坑已滤：zh 产出保留全部 LaTeX 结构——`\hskip N plus M\relax`、`\begin{env}[opt]`、xymatrix `\ar@{-}[r]`、natbib `\bibinfo{}{}` 内部组、数学 `$[..]$`/`^{*}` 残片全是合法存活，非残留。判别锚点是**与 cell marker 物理粘连**或 cell 内容纯残片。

## 发现

### A. 确证簇——寄存器赋值尾参粘连译文（~116 行 / 27 篇）

`[a-z]+=N[unit]?这是译文` 形：`hangafter=1这是译文`（74 行，宏展开把 `\def\bib{..\hangindent=1 true cm\hangafter=1}` 体接进散文）、`looseness=-1`（18）、`parindent=Npt`（8）、`baselineskip=N`（5）、`tolerance=800`、`vsize=10in`、`interdisplaylinepenalty=10000`。

**归属**：这是 scout-triage「散文区寄存器尾参」簇——illegal_unit 正式波（126 格口径）本就盖它，M1 波不必重收。id 集 `m1_assign_ids.txt`（27 篇）。

### B. M1 本征候选池——in_arg 字面段残片（721 行 / 185 篇，FP 掺）

剥壳后 cell 内仍见 `{4.5cm}` 列型片、`=10mm`/`=0pt` 赋值等号片、`{n}{*}` 中切 multirow、`*` 孤儿、`[r]`/`[d]` 残位参、`width = 0.1` kv 边例。真阳例（人工复核过上下文）：`{p{4.5cm}}{` 列参断片、`= 0.1} &` 表位断片、`\[` 后 `[row sep=..]` tikzcd opt 孤悬（begin 已剥但 opt 残在 cell 面——命令跨行斩切的实例）。

**置信**：池内混 FP（bibtex `\bibfield` 组、数学残 `^{*}` 已滤但仍有余）——估计真阳率 30-60%，即 ~60-110 篇实受影响、每篇 1-3 格。id 集 `m1_cand_ids.txt`（185 篇）。

### 合并

候选并集 ~195 篇（A∪B），**超 ~50 发波阈**。收成口径：每命中行 ≈1-3 受损格，估计 400-800 格受损译文可经重跑修复。

## 建议

按 41 原令发 parse→xlat→compile→fixloop harvest 波，作用域 = `m1_cand_ids.txt ∪ m1_assign_ids.txt`（~195 id）。A 簇与 illegal_unit 波重叠——若两波都发，A 集合可在 illegal_unit 波内一并重跑，M1 波可缩到 B 的 185 篇。侦察 30min 盒到点，per-id 精度未再压——harvest 波重跑天然兜底（重产出 diff 即真值）。

## 产物

- `m1_assign_ids.txt`（27 篇，A 簇确证）
- `m1_cand_ids.txt`（185 篇，B 簇候选）
- `m1_residue_scan.py`（扫描脚本，可复跑/收紧）
- `m1_residue_hits3.jsonl`（全量 1010 命中行底账，含弱信号）
