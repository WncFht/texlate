# gtrap-scout — xeCJK protect-edef 毒盒爆炸半径评估

> 2026-09-16。源自 realarm-repro bug 类 G（cond-mat/0307508：elsart3 `\proc@elem` 测盒 + `\no@harm` `\def\protect{\noexpand\protect\noexpand}` → xeCJK CJK→font 绑定全局毒化，0 err/4379 miss 全 lmroman10）。证据文件：`docclass_census.json`、`corpus_cls_idiom.json`、`dyn_extent_carriers.json`、`tier_a_papers.txt`、`ecosystem_carriers.txt`。

## (a) 语料爆炸半径 —— Tier-A（elsart 血统：`\no@harm` + `\proc@elem` 测量盒）

触发条件：真载体 .cls 随 e-print Shipped。非 ship 的 elsart 声明走 legacy_pkg_shim→elsarticle（安全）。

- corpus（39）：0 篇（elsarticle ×2——2008 重写版无 `\no@harm`，干净）
- corpus_v2（139）：2 篇 trap-live——0812.4521、hep-ex/0406065（都 ship elsart.cls）
- corpus_v3（3997）：**17 篇 trap-live** / 43 Tier-A 声明：
  - elsart shipper：0806.1988、0806.3151、0905.0612、0905.1299、0905.1619、1003.5459（loop1 见 5485 ec-lm* miss）、astro-ph/9901365、astro-ph/0605133、nlin/0408017、physics/0408075
  - elsart3/3-1 shipper：cond-mat/0307508（已观察受害者）、1907.00254
  - **autart shipper（新载体——Automatica class，`\proc@elem` 逐字节相同）**：1306.5836、1706.02495、2003.03498、2308.04287
  - personal.cls shipper（elsart 克隆）：0707.0793
  - 24 个非 ship elsart/elsart1p 声明 → shim→elsarticle，安全。2 个 `\documentstyle{elsart}` → latex209 reject。
- 所有被译论文都把 CJK 放进 `\title`/`\author` → trap-live 篇触发率 ≈100%。

## (b) 生态携带者（texmf-dist + ~/texmf + 3340 份语料 ship cls/sty，md5 去重）

- **确认带毒形态**：elsart.cls/.sty/elsart1/ELSART.*、elsart3*/elsart1p（壳）、autart.cls/AUTART.CLS、personal.cls。
- **有惯用法但安全**（edef/write/fnmark/thanks 累加器，或内核标准 `\@outputpage` 配 `\set@typeset@protect` 在 vbox 内）：aa.cls、aastex.cls、svjour*/llncs/svproc、iopart/jpconf、amsart/amsbook/amsproc（`\markleft`→`\mark` 而已）、natbib、aipproc*、seg、ws-* 系、ar-1col、acmsmall*、tMOP2e、newlfm、pecha、flowfram、pgfpages、preview、latexrelease（内核）、subfig、blkarray、cases、program、picinpar、dinbrief、lettre、aps.sty、memoir/mem.cls。
- **未验证孤本**（1 份）：soul-ori.sty、nath.sty、sebase.cls、edbk.cls/kapproc.cls。
- 大户全部干净：amsart（473 篇）、revtex*（809）、IEEEtran（234）、acmart（61）、elsarticle（96）。

## (c) fixloop 签名 + 补丁草案

**反应式签名（高精度）**：missing_char 大量（≥~50）全落 lmroman*/ec-lm* 字体 AND 零 `!` 错 AND（docclass ∈ {elsart, elsart1, elsart3, elsart1p, elsart3p, elsart5p, elsart3-1, autart, personal, elsevier} OR 工程 .cls/.sty 命中载体 regex）。首个 missing 是标题/frontmatter CJK 加强判据。注意：cjk_warmup 已对 warn_missing_char 触发——warmup 后 miss 仍在即本类升级标志（若每个新 (fam,ser,sh,size) 元组被重复毒化或毒化在 family 级，warmup 救不了）。

**主动文件签名（确定性，normalize/prep 期跑）**：扫工程树 *.cls/*.sty 找含 `\def\protect{\noexpand\protect\noexpand}` 的 sanitizer 宏（regex `\\def\\[A-Za-z@]*harm[^}]*\\def\\protect\{\\noexpand` 抓 `\no@harm`/protect-sanitizer 变体）PLUS `\begingroup` 界内调用该 sanitizer 且含 `\setbox\s*\\?[A-Za-z@]*\s*\\hbox` 的宏。通用抓未知 ship class（1850 个唯一 ship 文件，名单白名单不够）。

**补丁草案（伪码）**：

```text
for f in project_tree.glob("*.cls","*.sty"):
    if carrier_signature(f):
        # 方案 A（elsart 实测 0-miss）：\proc@elem 等价宏内删
        #   `\setbox\@tempboxa\hbox{#2}` 行——丢弃用测量盒，
        #   \no@harm/\xdef 语义保留。
        # 方案 B（arximspdf 先例）：该组内 \setbox 前插 `\let\protect\relax`。
        # 兜底：整体覆写 f 为 legacy-shim stub
        #   \ProvidesClass{stem}[fixloop shim -> elsarticle]\LoadClassWithOptions{elsarticle}
        recompile
```

elsart3/elsart3-1 声明会自然扫到其载入的 elsart.cls（壳本身无惯用法）。另建议把 elsart3/elsart3-1/elsart1/autart/personal 加进 legacy_pkg_shim 名表覆盖非 ship 情形（当前这些名未覆盖——不同失败模态 class-not-found）。

## (d) 置信度 / 限制

- 高：载体分类逐宏读过（非仅 grep）。elsart/autart/personal 共享同一 `\proc@elem` 代码。所有「安全」携带者的惯用法只裹 `\xdef`/`\write`/`\mark` 或内核 `\@outputpage`（vbox 内 `\set@typeset@protect` 恢复 protect）。
- **开放实证问题**：现有 `CJK_FIRST_USE_WARMUP`（`\AtBeginDocument{\setbox0=\hbox{字}}`，inject.py:354）是否已治愈本类——0307508 的基线 Rio.tex 无此块（早于该特性）。若绑定复用成立则 warmup 全修；若每次毒排版都重毒 family 绑定，则只有 class 补丁有效。real-postfix 复扫（#80）会给出答案。
- `\let\protect\noexpand` 形态毒化未测（repro 只证 `\def` 自指形）。若同杀，Tier-B 输出例程携带者需复查——但 vbox 内 `\set@typeset@protect` 大概率仍兜底。
- 组跟踪扫描近似动态域；经额外间接层调 sanitizer 的异类载体可能漏——由反应式日志签名兜底。
- 语料声明计数扫论文树全部 .tex；少数命中或非主模板文件（Tier-A 清单已目检——声明都在真主文件里）。
