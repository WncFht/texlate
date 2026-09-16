# fixloop:fail 逐格归因（56 格 · leader 版 · scout-fail59 复核待并入）

> 口径：fixloop.jsonl 末条 `fixloop_verdict` ∈ unfixable:*/max_rounds/
> no_errors_no_pdf/stuck。**当前 56 格**（overseer 底单 59 为更早快照，
> 期间定点 rerun 愈 3 格）。逐格证据 = post.compile.first_error +
> 冒犯行源码 + CJK 腐蚀指纹检测。

## 裁定汇总

| 裁定 | 格数 | 处置通道 |
|---|---|---|
| corrosion（译文腐蚀超簇） | 27 | fixer-slots + segmenter/L0 已落修复，**重翻即回收**；非规则面 |
| fixable-data（规则/shim body 数据缺口） | 18 | 数据提案 → rules.yaml owner（项目体验方式）评审 |
| upstream（稿/上游真伤） | 9 | wontfix 或 llm_hook 候选 |
| infra | 1 | fontmaps/tfm 装配层 |
| SIGSEGV | 1 | ticket-only（1803.00012，已立案） |

**clean 率杠杆**：corrosion 27 格随 realpostfix2 全量重翻自然回收；
fixable-data 18 格是真增量空间——若全落地，fail 池 56→~11。

## 逐格裁定表

| id | cat | 裁定 | 证据（冒犯行/机理） |
|---|---|---|---|
| 0707.0382 | syntax | upstream | `AMSbsy.sty:24` 内嵌 tar 头字节（`AMSfonts.sty 0000644…`）——稿自带 sty 实为 tar 归档 |
| 0707.4206 | illegal_unit | corrosion | `pstricks.tex:386` `\psunit 1这是译文`——bundled 包文件被翻（同 .rtx 文件面排除类问题） |
| 0905.0193 | early_eof | fixable-data | `svjour.cls:93` `\ClassError{No valid journal specified}`——`\documentclass[epj]{svjour}` 选项不认，类选项 shim 候选（单格量） |
| 1003.0476 | syntax | upstream | `ws-procs975x65.cls:619` Missing number——World Scientific 类自带 epsfsafe 探测代码在现代 LaTeX 下不稳健 |
| 1003.2165 | babel_opt | fixable-data | `Unknown option 'polutonikogreek'`——语言无 .ldf 档，需选项改写（→`greek`+polutoniko 属性或剥除），非安装 |
| 1012.1830 | syntax | corrosion | `Illegal parameter number` + 全文 `这是译文`——PH/参数腐蚀 |
| 1109.2144 | illegal_unit | corrosion | `10pt.rtx.tex:76` `-20这是译文`——.rtx 排除已落（`*.rtx.tex` glob），待重翻 |
| 1109.2205 | syntax | corrosion | 同 1012.1830，`Illegal parameter` + `这是译文` |
| 1109.2354 | syntax | fixable-data | `aipcheck.tex:82` Paragraph ended before `\next`——bundled 交互检查文件，wdir 覆写 stub 候选（同 hep-ph/0111248 提案） |
| 1109.5313 | illegal_unit | corrosion | `10pt.rtx.tex:76` 同 1109.2144 |
| 1206.0136 | early_eof | upstream | `session.tex:3 \input{Paper.tex}` file-ended scan——Paper.tex 内 `^^M` 缺字刷屏截断（补记7 已归因），真根在缺字/misschar 面 |
| 1206.0148 | syntax | upstream | `ws-mpla.cls:552` 同 1003.0476 WS 类族 |
| 1206.0565 | syntax | fixable-data | `aipcheck.tex:82` 同 1109.2354 |
| 1206.0701 | other | corrosion(plaus) | `Incomplete \iffalse` line 113——doc 内 `这是译文` 密布，`\fi` 被蚀概率高 |
| 1206.2111 | syntax | corrosion | `schulze.tex:36` 孤 `[12pt]`——`\documentclass[12pt]{…}` 行 cs+arg 被蚀只剩选项括号（PH-in-cs 同族） |
| 1306.0067 | syntax | fixable-data | `Extra \or` `m{1.25in}` 列型——原类定义 `m`/`C` 列型，shim→article 丢列型定义；shim body 补 `\usepackage{array}`+`\newcolumntype` |
| 1306.0281 | early_eof | fixable-data | `ntheorem: Theorem style plain already defined`——acmart-shim 载 amsthm 与 doc ntheorem 撞，drop-loads/选项剥除候选 |
| 1306.0364 | other | corrosion(plaus) | `Incomplete \iffalse` line 101（原发 expl3 backend 已愈）——同 1206.0701 |
| 1306.0516 | illegal_unit | corrosion | `\\[1.5这是译文]` |
| 1404.0037 | illegal_unit | corrosion | `\tableofcontents` 报 illegal unit——上 pass 蚀坏的 `\\[..这是译文]` 进 .toc，二次读取时爆在 toc 行 |
| 1404.0519 | early_eof | corrosion | `\c3这是译文2`——`\c{S}` 口音参数被译文改写（补记7） |
| 1608.06693 | early_eof | fixable-data | fontspec `\normalsize not defined`——svglov3.clo shim 缺字号引导，fontspec 先于 \normalsize 初始化；clo shim body 补尺寸命令或推迟 fontspec |
| 1608.06714 | syntax | corrosion | `\begin{deluxetable*}{这是译文}`——列格式参数被译文 |
| 1706.00016 | syntax | fixable-data | `Extra \or` `rCCCCCC`——原类自定义 `C` 列型，shim 丢失（同 1306.0067） |
| 1706.00076 | illegal_unit | corrosion | `{\Small \tableofcontents}`——toc 携带蚀坏长度（同 1404.0037） |
| 1706.00240 | early_eof | upstream | `draft.sty:141 \acsetup{single, short-format=\acsize}`——acro v3 改名键 vs doc v2 语法，上游 API 漂移 |
| 1706.00335 | capacity | fixable-data | `\end{restatable}` 处 capacity——complexity 类 restatable 支持随 shim 丢失，递归爆栈；shim body 补 thm-restate 兼容 |
| 1706.02464 | syntax | corrosion | `tcilcomm.tex:117` `\@temptokenb{这是译文}`——bufsize 修复（`26b760e`）后暴露的巨行腐蚀 |
| 1706.07911 | early_eof | fixable-data | fontspec `\liningnums already defined`——doc/包重定义撞 fontspec，already_def 类规则候选 |
| 1811.03624 | syntax | fixable-data | `Extra \or` `C{2.2cm}` 列型（同 1306.0067） |
| 1907.00027 | capacity | corrosion | `\caption{这是译文 \bh{s}…}` 后 capacity——蚀坏宏循环爆内存 |
| 1907.00131 | early_eof | corrosion | `\@citex doesn't match` + `这是译文` 上下文——cite 宏参数蚀坏 |
| 1907.10528 | illegal_unit | corrosion | `\\[1.10这是译文]` |
| 2009.11064 | undefined_cs | upstream | `ms.bbl:21 \sortlist[entry]{apa/global/}`——biblatex-apa 产 .bbl 配非 biblatex 引用体系，上游错配 |
| 2009.11130 | other | upstream | `\gdef\GetTitle` obeylines+catcode'015 脆弱宏 EOF 扫描——稿自带 catcode 戏法在 xelatex 下不稳健 |
| 2104.00116 | illegal_unit | corrosion | `\parindent=0这是译文` |
| 2105.00111 | capacity | fixable-data | `\end{restatable}` 同 1706.00335 |
| 2105.11398 | illegal_unit | corrosion | `\\[-.5这是译文]`（pst-all fanout 已通后前进到此） |
| 2203.00092 | syntax | corrosion | `\foreach\iin {这是译文}`——`\foreach\i in` 空格被吞融合 `\iin`（bug-B 同族） |
| 2211.12985 | missing_tfm | infra | `skak.sty:1774 Font LSB/ska…`——skak 包装进 _texmf 但 tfm 缺，fontmaps/mktex 装配层 |
| 2211.13028 | early_eof | fixable-data | `hypdvips: Wrong hyperref driver hxetex`——doc 强指 dvips 驱动，driver 剥除规则候选 |
| 2308.12593 | illegal_unit | corrosion | `\hspace{-1这是译文}` |
| 2308.12612 | early_eof | fixable-data | `hyperref: Wrong driver option pdftex`——doc 传 pdftex 驱动选项，同族剥除规则 |
| 2403.00139 | early_eof | upstream | `static-1.05.tex:441 NFSS system isn't set up properly` at `\begin{document}`——字体体制上游伤 |
| 2403.05454 | illegal_unit | corrosion | `\\[1这是译文]` |
| astro-ph/0104174 | capacity | fixable-data | `\begin{document}` 处 capacity——aastex shim 下递归（aastex cls 宏面缺口），与 0408531 同签名 |
| astro-ph/0408286 | undefined_cs | fixable-data | `\maketitle` undef——espcrc1 shim 替身丢 \maketitle 宏面，shim body 补 |
| astro-ph/0408531 | capacity | fixable-data | 同 astro-ph/0104174 |
| astro-ph/0605222 | undefined_cs | fixable-data | `\hb` undef——aastex 族 Hβ 宏，aastex shim body 补 `\def\hb{H$\beta$}` 类 |
| cond-mat/0501221 | undefined_cs | corrosion | `{\emFrenkel--这是译文}`——`\em`+Frenkel 融合（bug-B） |
| hep-lat/0111059 | undefined_cs | fixable-data | `cpcauth.cls:122 \eqntopsep 8\p@`——elsart shim 缺 `\eqntopsep` dimen（已在 ucs 族提案内） |
| hep-ph/0408067 | undefined_cs | corrosion | `\LARGEFun`——`\LARGE`+Fun 融合 |
| hep-ph/0501170 | illegal_unit | corrosion | `\vspace{2这是译文}` |
| hep-ph/0605134 | syntax | corrosion | `Illegal parameter` + `这是译文` |
| hep-ph/9910403 | undefined_cs | corrosion | `\LARGEOptimal`——`\LARGE`+Optimal 融合 |
| 1803.00012 | nenp | ticket | xelatex SIGSEGV（revtex4 shim 树 hyperref 初始化段），无规则面可修——ticket-only |

## fixable-data 提案明细（18 格 → 6 个数据动件）

1. **shim body 列型补齐**（3 格：1306.0067/1706.00016/1811.03624）——期刊类
   shim→article 时附带 `\RequirePackage{array}` + 常见 `C`/`m` 列型
   `\newcolumntype` 兜底。
2. **shim body 宏面补齐**（4 格）：elsart `\eqntopsep`（hep-lat/0111059）、
   espcrc1 `\maketitle`（astro-ph/0408286）、aastex `\hb` 等天文缩写宏
   （astro-ph/0605222）、aastex cls capacity 递归根因待查
   （astro-ph/0104174+0408531，可能同 `\maketitle`/宏面缺口衍生）。
3. **thm-restate 兼容**（2 格：1706.00335/2105.00111）——complexity/期刊类
   shim body 载 thm-restate 或定义 restatable env。
4. **驱动选项剥除**（2 格：2211.13028/2308.12612）——doc 传 pdftex/dvips
   驱动给 hyperref/hypdvips，xelatex 下剥除/改 hxetex。
5. **bundled 交互文件覆写**（2 格：1109.2354/1206.0565）——aipcheck.tex
   `\next`/`\read` 交互检查 → wdir stub 覆写（bundled_class_shadow 同机理
   扩 target 类）。
6. **杂项**（5 格）：1306.0281 ntheorem/amsthm 撞（drop-loads）、
   1608.06693 clo shim 字号引导、1706.07911 `\liningnums` 重定义、
   1003.2165 babel 选项改写、0905.0193 svjour 类选项。

以上均为**数据/规则逻辑提案**，按纪律不直写——报 owner（项目体验方式）
评审落 rules.yaml；其中 4/5 两项可能需要新 when 条件或 target 类型，
属逻辑动件需 texlate-1d 裁定。
