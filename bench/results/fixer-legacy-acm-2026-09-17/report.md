# fixer-legacy-acm — 1306.0281 acm_proc_article-sp 作者块 shim gap

2026-09-17 · 任务 #35 · 状态: **已合并**（rules.yaml `legacy_pkg_shim` shim_map，byte-equal 校验过）

## 结论

`unfixable:early_eof → acceptable_pdf`：fixloop halt 臂 r1 `missing_file` 触发 legacy_pkg_shim 注入新 cls body，r2 出 PDF（67,914 B）；judge 非 halt 双 pass 产出 17 页 / 147,782 B / cjk 5344，judge status `partial`（残面 35 errs 全部落在下述已路由残面，非 shim 覆盖域）。`\titlenote` 引爆的 maketitle 风暴（`\@xfootnotemark` 定界参失配 + `Missing \endcsname`，~100 连）清零。

## 交付物（本目录）

- `rules-fragment.yaml` — shim_map 替换件（已并入 src/texlate/compile/fixloop/rules.yaml）
- `findings.txt` — 完整根因/设计/残面记录
- `build_scratch.py` + `scratch-rules.yaml` + `replay.py` — 复现链
- `replay-cell.json` / `judge.json` / `cases.jsonl` / `work/1306.0281/` — 实证件（注入后 cls 与 fragment 逐字节一致）

## 根因

acmart 原生 `\def\titlenote` 向 `\@title` 追加 `\footnotemark`；稿把整作者块包在单个 `\author{...}` 参内，manuscript 格式下 `\@mkauthors@i` 走 `\MakeUppercase`→`\__text_expand` 展开 `\titlenote`→`\footnotemark`→`\@xfootnotemark` 定界参失配→百连级联。必须**覆盖**（非 provide）：`\protected\def\titlenote#1{\thanks{#1}}`。

## shim 设计（cls body，装载期 @=letter）

- `\titlenote` → `\protected` 桥 `\thanks`（无条件覆盖；text_expand/pdfstring 原样穿透，typeset 时落 `\thankses` 注脚条）
- `\alignauthor` → `\par`（列起始命令，零参复刻"新作者列"断行）
- `\affaddr`/`\affinst` → `\emph{#1}`（`\author{}` 参内顶层；acmart `\affiliation` 会污 `\addresses`）
- `\additionalauthors` → `\author{#1}`；`\numberofauthors` → noop；`\subtitle` → ifdefined 守卫
- abstract 序桥：`\renewenvironment{abstract}` 按 `\@ACM@maketitle@typeset` 分路——pre-maketitle 走原生 `\Collect@Body\@saveabstract`，post-maketitle 就地排无号块（**late path 不走 Collect@Body**：environ 体扫描 `\let` 劫持 `\abstract`，不容 typeset 回调——v2 版在此炸 `Too many }'s`，v3 修正）
- 2.09 字族：只补 `\cal`/`\mit`（amsart.cls:437-443 `DeclareOldFontCommand` 已继承 `\rm\sf\tt\bf\it\sl\sc`，有意略去 cal/mit；稿内 `\cA→{\cal A}` 族 ~100 undefined_cs）

## 降级面（best_effort 可接受）

五作者并单条 acmart author 条目（`\alignauthor` 列流无法无损重建 per-author 结构），机构 emph 行内保文，titlenote 注文进 thanks 条，pdfauthor 元数据脏串（cosmetic）。

## 残面（不在 class-shim 覆盖，已报 leader 路由）

1. **`\@begintheorem` "Paragraph ended" ×6 + missing `\item` ×6**（prelims/extlwe 全部 theorem 点）——`[#3]` 定界扫描吞 `\end{env}` 吃到 `\par`；amsthm `\@oparg` 防护被绕过，首嫌 texlate `THEOREM_ANCHOR_SHIM` 的 `cmd/@begintheorem/before` 钩（inject.py:101）或 splice 方括号重构。需最小 repro。
2. **tikz ~19 errs**（shortsecret.tex:31+）——稿主注释掉 `\usepackage{tikz}`（main.tex:135）但 tikzpicture 实调；cls 无条件预载有 option-clash 回归面，不桥。
3. 末端 `\baselinestretch` redefine ClassError + definition env 未闭合（残面 1 级联）。
4. `missing_character` ×5（字覆盖面，与 shim 无关）。

## replay 坑

重放前必须 `rm work/*/splice/acm_proc_article-sp.cls`——旧 stub 在场压住 `missing_file` 触发，新 body 永不落盘。
