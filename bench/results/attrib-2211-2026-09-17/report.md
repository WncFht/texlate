# attrib-2211: 2211.04482 missing_number 归因裁决

2026-09-17, texlate-1d (leader)。41 路由题：post-A5 新 first_error `missing_number` at `splice/sne_table.tex:1`——判 tree-damage(serializer) 还是 fixloop 面。

## Verdict

**fixloop 面——陈旧 workdir 中毒，非 serializer、非新语法族。** 双臂最小 repro 逐签名校验：

- **干净臂**（aastex62.cls + `\usepackage{adjustbox}` + sne_table，无注入）：仅 `adjustbox.sty:1901 LaTeX Error: Command \splitbox already defined`（良性——`\newcommand` 不重定义，aastex62 的 `\newbox\splitbox`=box80 存活），deluxetable 全程无阻，`sne_table.tex:1` 无 missing_number。
- **中毒臂**（同树 + `\makeatletter\let\splitbox\@undefined\makeatother` 于 documentclass 后）：**逐字节复现**新 run 签名——`:1 Missing number <to be read again> \begingroup` + `A <box> was supposed to be here`，`:25 \enddata` 处 `\@splitbox #1#2->\ifstorebox \storebox \splittedbox \collectedbox \usestorebox` 五连 undefined + Missing number ×2。

## 机理链

1. aastex62.cls:4868 `\newbox\splitbox`（盒寄存器，deluxetable 分表机制 `\setbox\splitbox=\vtop`/`\unvbox\splitbox` 全套使用，cls 内 9 处均为寄存器用法）。
2. inject.py TABLE_FITTING（:316-331）注入 `\usepackage{adjustbox}`；adjustbox.sty:1898 `\newcommand\splitbox[2]` → already_def。
3. **A5 护栏有效**：`_allocated_cs_names(mask_tex(source_blob()))` 对当前 splice 树实测 `splitbox ∈ names`（direct 调用验证），新 run 中 already_def 未再触发注入——新 log 零 already-defined 错误行。
4. 但 `splice/main.tex:32` 与 `:34` 残留**两条** `\let\splitbox\@undefined`（mtime 08:16，早于 10:26 的 compile）——pre-A5 `already_def_undefine` 旧轮次注入物，fixloop 变异在复用 workdir 中跨 wave 存活。`:34`（真 documentclass 后）把盒 undefine → adjustbox `\newcommand` 静默成功 → `\splitbox` 变宏 → `\setbox\splitbox` 数字扫描展开宏遇 `\begingroup` → Missing number。
5. 新 run 2 actions 均为旁路规则（already_def 根本没出现，护栏无从介入），verdict `unfixable:syntax` 是对**自残态**的误分类。

## 附带发现

- **注入器锚点缝**：`splice/main.tex:32` 的注入落在**被注释的** `%\documentclass`（:31）之后——`_inject_after_docclass` 锚正则不排除 `%` 引导行（A5 记档的 eol+1 缝同族）。该针位空转但暴露了锚定 bug。
- `\ifstorebox` 等 undefined 根因：adjustbox.sty:1897 `%%\RequirePackage{storebox}` 被注释——`\@splitbox` 依赖的 storebox 原语本就缺载，但 `\@splitbox` 仅在 `\splitbox` 宏/`split=`key 路径被调，正常 load 下不炸；本案是被 `\unvbox<宏>` 数字扫描强行展开才踩进死路。

## 建议路由

1. **本 cell 立解**：重生 splice（或剥 main.tex:32/34 两行）重跑 → 预期 already_def benign + PDF 出。无新代码需求。
2. **harness 面**（e2e/stagerun 属主裁决）：`fixloop --rerun` 复用脏 workdir → 陈旧变异跨 wave 泄漏。rerun 应从 zh/ 重建 splice 或回滚 fixloop diff——**这可能是 recut2 其他 regression cell 的隐性污染源**，建议 41 评估是否加 rerun= clean-splice 语义。
3. **锚点加固**（peer1 面，小件）：`_inject_after_docclass`/同类锚正则跳过注释行。
4. already_def abstain 后的 sig 语义：良性 already_def（类盒胜、编译续行）目前仍计 unfixable——41 斟酌 verdict 映射。

## 证据

- repro 树：`tmp/attrib-2211/`（main.tex 干净臂 / main2.tex 中毒臂 + run1.out / run2.out）
- 现场：`bench/results/stagerun-loop1-2026-09-16/work/2211.04482/splice/{main.tex:32-34,main.log:339,848,1096-1208}`
- 护栏源码：`src/texlate/compile/fixloop/builtins.py:1043-1110`、rules.yaml 规则 provenance :3064
