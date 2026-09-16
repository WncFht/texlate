# scout-coreleak — 「CJK 域泄漏」实为三机理 + jpsj3 盲改归因（交付 1d）

> 2026-09-16。只读侦察 + `tmp/scout-coreleak/`（t_tie.tex/t_tie2.tex/t_show.tex/jpsj/）。未碰入库文件。结论：modec-core 报的「CJK 域泄漏缺字」拆开是**两个不同机理**，加 jpsj3 共三处独立修复点。

## 1a — 2003.10723：`{\t …}` TS1 重音路径绕过 xeCJK 域（非页眉假设）

**机理（证据）**
- `pipe-xel/2003.10723/SS_October.log:456` `Missing character: There is no 这 (U+8FD9) in font [lmroman12-regular]`，夹 shipout [18]/[19] 间；pdftotext p19 = 参考文献页 `\bibitem{Spruch_26} 这是译文, {\t 这是译文.}`——唯一缺字 = 唯一一处 `\t`+CJK。页边界纯属 bibitem 恰好落页首（article pagestyle=plain 无走字头，排除页眉假设）。
- `\meaning\t` = `\TS1-cmd \t \TS1\t`（实测）：`\t` 不在 tuenc.def:299-313 的 15 个 `\DeclareUnicodeAccent` → 落 TS1 fallback（ts1enc.def:66 `\DeclareTextAccent{\t}{TS1}{26}`）→ `\accent` 原语把 accentee 直接排当前字体（lmroman12），**不经 xeCJK interchartoks 字域切换** → CJK 落 Latin 域。
- 复现：`{\t 这}`/`{\t{这}}`/`{\t{这是译文}}` 全丢于 lmroman12；TU 原生 `\'这` 完好。缺口面 = 全部未 TU 化 TS1 重音：`\t`（实证）、`\capitaltie`/`\newtie`/`\capitalnewtie`、`\capital*` 11 件（ts1enc.def:55-69）。fixloop `cjk_warmup` 救不了（只解绑定顺序不解域绕过）。

**修复点**：`inject.py` 注入块追加 TS1→TU 重音提升（CJK_MATH_FALLBACK 同缝 :111-160 区）：

```latex
% texlate: promote TS1-fallback accents to TU so CJK accentees stay in CJK domain
\ifdefined\UnicodeEncodingName
\DeclareUnicodeAccent{\t}{"0361}
\fi
```

其余 tie/capital 族同式可选，码位逐个核（`\t`→U+0361 已实证）。**测试**：test_compile_inject.py 断言注入产物含 `\DeclareUnicodeAccent{\t}`；live-fire `tmp/scout-coreleak/t_tie.tex`（修前 mc=1 → 修后 0）。

## 1b — 2410.17992：quantumarticle `\selectfont` 陷阱，**选项名拼错未绕过**

**机理（证据）**
- `main.log:1297-1360`：`\@titelsaveboxHuge=\box97` → `Class quantumarticle Error: ...not supposed to use \textbf{}...inside \title{}` → 缺 `这是译文`×4 lmsans17；box98×4、box99 error+×8。类在标题测量盒设 `\selectfont` 陷阱：cls:1038-1046 `\@titleatfontsize` 内 `\iftoggle{@allowfontchangeintitle}{}{\def\selectfont{\ClassError…}}`；测量盒 cls:1048-1062。
- xeCJK.sty:3603-3604 `\fontfamily{#2}\selectfont`——CJK 切字体走 `\selectfont` → 撞陷阱：error 抛出 + 字体从未选中 → CJK 滞留 lmsans17。**类 error ×3 与缺字 ×20 同一发子弹**；FandolHei 绑定正常（非 sans 族绑定缺口）。
- 类自带逃生门 cls:209 `\DeclareOptionX{allowfontchangeintitle}`，而 `normalize.py` XETEX_COMPATIBILITY 传的是 **`allowfontchageintitle`（chage，缺 n）** → xkeyval 视为未知选项 → toggle 恒 false → 陷阱生效。

**修复**：`normalize.py:183` 一个字母 `allowfontchageintitle`→`allowfontchangeintitle`——**已由 leader 落盘**（本仓 normalize.py 属 1e lane），含拼写守卫测试。class error ×3 + 缺字 ×20 应同灭。

附注：main.log:1706+ `;` in nullfont ×4——hyperref pdfstring 书签域，另一族，勿并案。

## 2 — cond-mat/0111097：jpsj→jpsj3 无目标类校验，partial→fail 劣化

**机理（证据）**
- `latex209.py:144` `"jpsj": _ClassSpec("jpsj3")` + upgrade_209 `target = spec.target if spec is not None else cls`（:385-386）——**映射后无目标存在性校验**。
- 产物 `\documentclass[seceq,twocolumn]{jpsj3}`（epsfig 已正确剥入 pkg_opts）→ `File 'jpsj3.cls' not found` → 三臂 missing_file fail。kpsewhich 空；fixloop ctan_fetch 也抓不到（jpsj3 仅期刊站分发非 CTAN）。
- base 臂 compat 实证原物可用：`Compatibility mode: loading jpsj.sty rather than jpsj.cls` 载随包 → partial。

**修复点**：`latex209.py:385-389`，spec 改名（`spec.target != cls`）时先做目标类可解析性检查，失败返回 `{"status":"reject","reason":"latex209_no_target","target":target}` → inject 经 :465-466 抛 `inject_reject:latex209_no_target`（同 ds@ reject API 形态）。校验两级：随包 `root.rglob(f"{target}.cls")`（仿 `_ships_style` :310-314）+ 系统 `kpsewhich`（normalize.py:928 `_kpse_resolve` 现成模式；**kpsewhich 缺席 fail-open**——mapped 目标 revtex4-2/mnras/elsarticle 全在系统 texmf，fail-closed 会误杀全部合法映射）。只对改名场景查——未映射类按设计交 fixloop missing_file→ctan_fetch（:11-12 既有契约）。

**排除项（都实测过）**：保留原名 `\documentclass{jpsj}`——compat 仅由 `\documentstyle` 触发，死路；`\documentclass{article}`+`\usepackage{jpsj}`——main-style 型 `\newcounter{section}` 撞 article + 209 内件 → 结构性破损；zh 臂无 compat 可退（documentstyle 禁 `\usepackage`）→ reject 是诚实 verdict，不再花编译费打 missing_file。

**测试**（test_latex209.py 同风格）：① `\documentstyle{jpsj}` + 无 jpsj3.cls + kpsewhich 空 → `reject/latex209_no_target`；② tmp_path 放假 jpsj3.cls → `converted`（rglob 臂）；③ `\documentstyle{mn}` 系统有 mnras.cls → 仍 `converted`（kpsewhich 臂，无则 skipif）；④ `\documentstyle{article}` std 类不受影响。

## 给 1d 的优先级

normalize.py 拼写（1 字母，签名 5 全灭，**已落**）→ latex209.py 校验（防劣化族）→ inject.py `\t` 提升（低频但机理钉死）。三处独立可分三 commit。
