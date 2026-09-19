r"""中文支持注入：ctex `[fontset=fandol,UTF8]` 默认路径 + xeCJK 降级路径 + 数学兜底。

`CJK_MATH_FALLBACK`：xeCJK interchartoks 不进数学模式，译文落 `$..$`/
`\boldmath` 头标即在数学族字体丢字，`\Umathcode` 重映进 FandolSong
（CJK 九段）/ Libertinus Serif（西里尔·组合符·拉丁扩展）符号字体补齐。

docs/08 §3.3 注入缝：
- 兼容块 → `\begin{document}` 前（本模块 _splice_before_document，depth-0 锚）
- 字体系块 → `\documentclass{}` 后（本模块 find_docclass_ends：逐缝注入，
  `\ifpdf A \else B \fi` 分支选择形态每条臂各落一份幂等块）
- `\documentstyle` → **禁止注入 + inject 层 reject**（ctex/xeCJK 与 2.09
  互不兼容；route_project 已降级为 latex209_suspect 试编标记——
  inject 是 2.09 的兜底拒绝点，账本记 `inject_reject:latex209`
  与 route reject 分流）

实证：compile-bench 72 次编译中 ctex 注入破坏率 0%（bench/results/compile-report.md）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from texlate.textutil import (
    BEGIN_DOC_RX,
    DEAD_ENVS,
    DOCCLASS_DECL_RX,
    DOCCLASS_ONLY_RX,
    DOCCLASS_RX,
    DOCSTYLE_RX,
    INPUT_BARE_RX,
    INPUT_BRACED_RX,
    VERBATIM_ENVS,
    _tar_disguised,
    clean_decl_name,
    decode_tex,
    iter_depth0,
    mask_tex,
    safe_is_file,
    safe_resolve,
)

from .latex209 import upgrade_209
from .mask import group_end, visible_tex
from .normalize import (
    inject_preamble,  # noqa: F401 -- re-export 经 compile/__init__ 外发
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

#: zihao=false 必须钉死：ctex 默认 scheme=chinese 在未收到显式字号选项时
#: 强启 zihao=5（ctex-scheme-chinese.def），把 \normalsize..\tiny 全体重映射到
#: 中文字号 bp 尺寸（10pt→10.53937pt +5.4%），版式几何全面膨胀。
CTEX_LINE = r"\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}"

#: xeCJK 降级块：ctex 与模板冲突时（fixloop/探针编译切换）换这条路径。
XECJK_BLOCK = r"""
% texlate: CJK via xeCJK fallback path
\usepackage{xeCJK}
\setCJKmainfont{FandolSong-Regular.otf}[BoldFont=FandolSong-Bold.otf,ItalicFont=FandolKai-Regular.otf]
\setCJKsansfont{FandolHei-Regular.otf}[BoldFont=FandolHei-Bold.otf]
\setCJKmonofont{FandolFang-Regular.otf}
"""

#: 已有 CJK 支持 → 不重复注入。判定收紧到**包/类调用语境**
#: （`\usepackage`/`\RequirePackage`/`\LoadClass`/`\documentclass` 花括号
#: 参数内的族名）+ xeCJK/CJK 专属命令探测——裸子串会被
#: `\def\CTeXPreproc{...ctex v0.2.12...}` 宏体字面量、`\ctext` 宏名、
#: `mactex` 类包名假阳（loop1 A 桶实证：误判 already → 整跳注入 →
#: 整篇中文静默缺失）。花括号内 `ctex\w*`——`ctexart`/`ctexbook`/
#: `ctexrep`/`ctexbeamer`/`ctexsize` 类名与 `CJKutf8`/`CJKfontspec`
#: 包名全命中。词表是 ``textutil.LOADER_CMDS`` 真子集 + ``documentclass``：
#: ``PassOptionsToPackage``/``PassOptionsToClass`` 首个 ``{}`` 实参是选项表，
#: ``{ctex*}`` 落选项位会把「传选项未载包」误判成已有 CJK 跳注入。
CJK_PRESENT_RE = re.compile(
    r"\\(?:usepackage|RequirePackage|LoadClass|documentclass)"
    r"[^\n%{]*\{[^}\n%]*\b(?:ctex\w*|xeCJK\w*|CJK\w*|luatexja\w*)\b"
    r"|\\setCJK\w*font\b"
    r"|\\newCJKfontfamily\b"
    r"|\\xeCJKsetup\b"
    r"|\\begin\s*\{CJK\*?\}"
)

#: 共享计数器 theorem 的双 named-dest 补丁（B7 锚点对齐）。
#: `\newtheorem{lemma}[definition]` 类声明在不同内核上 dest 命名分叉：
#: 旧内核（<2026-06，无 \newcounteralias）env 步进根计数器 → 锚点是
#: `definition.N`；新内核 alias 计数器 → env 步进自己的别名 → 锚点
#: `lemma.N`。en/zh 两臂只要工具链不一致就丢一半锚点（2410.17902
#: en 臂在 BasicTeX 2026 新内核上编出 `lemma.*`，zh 臂本地旧内核
#: 出 `definition.*`）。本补丁在 `\@begintheorem`/`\@opargbegintheorem`
#: before 钩子上补发「另一侧名字」的孪生锚点——纯增量不改名，
#: `\@currentHref` 发完即恢复，.aux label 名不受影响：
#: - `\@currenvir`==`\@currentcounter` 且 `alias@ctr@<env>` 存在
#:   → 新内核 alias 情形，补根名 `root.\theH<ctr>`；
#: - 不等且 `\the<env>` 有定义 → 旧内核共享计数器，补 env 名
#:   `env.\theH<ctr>`（`\the<env>` 守卫顺带挡掉 proof 等无号环境）。
#: `\@opargbegintheorem` 在 amsthm 下是 \relax（patch 静默跳过），
#: 在内核原生 theorem 路径上是带 [note] 的入口，两边都挂。
THEOREM_ANCHOR_SHIM = r"""
% texlate: twin named-dest for shared-counter theorems
\makeatletter
\def\TeXlate@thmtwin{%
  \@ifundefined{MakeLinkTarget}{}{%
  \@ifundefined{@currentcounter}{}{%
  \@ifundefined{theH\@currentcounter}{}{%
    \ifx\@currenvir\@currentcounter
      \@ifundefined{alias@ctr@\@currenvir}{}{%
        \edef\TeXlate@twin{\csname alias@ctr@\@currenvir\endcsname}%
        \TeXlate@emit}%
    \else
      \@ifundefined{the\@currenvir}{}{%
        \let\TeXlate@twin\@currenvir
        \TeXlate@emit}%
    \fi}}}%
}%
\def\TeXlate@emit{%
  \begingroup
  \let\TeXlate@save\@currentHref
  \edef\TeXlate@name{\TeXlate@twin.\csname theH\@currentcounter\endcsname}%
  \MakeLinkTarget*{\TeXlate@name}%
  \global\let\@currentHref\TeXlate@save
  \endgroup}%
\AddToHook{cmd/@begintheorem/before}{\TeXlate@thmtwin}%
\AddToHook{cmd/@opargbegintheorem/before}{\TeXlate@thmtwin}%
\makeatother
"""

#: 数学模式缺字兜底：xeCJK 的 interchartoks 是水平列机制，**数学内不触发**——
#: 译文落进 ``$..$``/``\beq``/下标/``\boldmath`` 头标（loop1 misschar 实证：
#: ec-lmss12、rm-lmr8、cmr10/7、ptmr8t 全是数学族 TFM）即丢字形。
#: 本块把缺字码位 ``\Umathcode`` 重映为 ordinary 符号、指向专用符号字体：
#: CJK 九段 → ``texlatecjk``（FandolSong 文件直载，与 fontset=fandol/xecjk
#: 块同字体）；西里尔/组合符/拉丁扩展 → ``texlatefb``（Libertinus Serif，
#: ``\IfFontExistsTF`` 门——otf 缺席不挂）。normal+bold 两个 math version
#: 都挂。纯追加：无数学内缺字时零行为变化；非 XeTeX/LuaTeX 引擎
#: （无 ``\Umathcode``）整块跳过。
#:
#: ``"`` 仅 catcode-12 是合法 hex 前缀——bd 锚在用户宏包之后，读到本块时
#: ``"`` 可能已被改写：quotes.sty ``\global\catcode`\"\active``（1012.1303
#: spidersweb:208，``<to be read again> \let``——active ``"`` 在数字扫描中
#: 展开）、fundus-cyr 链置 catcode-11（1206.1631 gamma_d:186-194，
#: ``<to be read again> "``）——``\count@="4E00`` 全体 Missing number +
#: Missing \begin{document}（dimcen A3，22 hits/2 cells）。守护区间：
#: ``\TeXlate@dqcat`` 存值 + ``\catcode`\"=12``，区间内 ``\def`` 体、
#: 调用点实参与字体名引号全按 12 读入，尾端精确还原原 catcode。
CJK_MATH_FALLBACK = r"""
% texlate: math fallback via dedicated symbol fonts
\ifdefined\Umathcode
\makeatletter
% texlate: " is a valid hex prefix only at catcode 12 (quotes->active, cyr->11)
\chardef\TeXlate@dqcat=\the\catcode`\"\catcode`\"=12
\DeclareFontFamily{TU}{texlatecjk}{\hyphenchar\font\m@ne}
\DeclareFontShape{TU}{texlatecjk}{m}{n}{<->"[FandolSong-Regular.otf]"}{}
\DeclareFontShape{TU}{texlatecjk}{b}{n}{<->"[FandolSong-Bold.otf]"}{}
\DeclareFontShape{TU}{texlatecjk}{bx}{n}{<->ssub*texlatecjk/b/n}{}
\DeclareFontShape{TU}{texlatecjk}{m}{it}{<->ssub*texlatecjk/m/n}{}
\DeclareFontShape{TU}{texlatecjk}{m}{sl}{<->ssub*texlatecjk/m/n}{}
\DeclareFontShape{TU}{texlatecjk}{b}{it}{<->ssub*texlatecjk/b/n}{}
\DeclareFontShape{TU}{texlatecjk}{bx}{it}{<->ssub*texlatecjk/b/n}{}
\DeclareFontShape{TU}{texlatecjk}{bx}{sl}{<->ssub*texlatecjk/b/n}{}
\def\TeXlate@mathmap#1#2-#3;{\count@="#2\relax
  \@whilenum\count@<"#3 \do{\Umathcode\count@="0 #1 \count@\advance\count@\@ne}}
% \count18 = LaTeX2e 内核 mathgroup 分配计数器（实证：每 \DeclareSymbolFont
% 先 +1 后查 ``<16`` ——count18=15 时分配失败炸 "Too many symbol fonts
% declared"）——剩 1 空位须拒申（``<15``，不是 ``<16``；2203.00075 stix
% 后 count18=15 实证，旧闸放行反而触发 + ``texlatecjk`` 未定义级联）。
% 宁可缺 fb/cjk 兜底, 不让整条注入把文档编译炸掉（b2 归因：txfonts
% 14 族文档只剩 1 空位）。
\ifnum\count18<15\relax
\DeclareSymbolFont{texlatecjk}{TU}{texlatecjk}{m}{n}
\SetSymbolFont{texlatecjk}{bold}{TU}{texlatecjk}{b}{n}
\TeXlate@mathmap\symtexlatecjk 4E00-9FFF;
\TeXlate@mathmap\symtexlatecjk 3400-4DBF;
\TeXlate@mathmap\symtexlatecjk 3000-303F;
\TeXlate@mathmap\symtexlatecjk FF00-FFEF;
\TeXlate@mathmap\symtexlatecjk 3040-30FF;
\TeXlate@mathmap\symtexlatecjk F900-FAFF;
\TeXlate@mathmap\symtexlatecjk 2E80-2FDF;
\TeXlate@mathmap\symtexlatecjk 20000-2A6DF;
\TeXlate@mathmap\symtexlatecjk 2A700-2EBEF;
\fi
% 非 CJK 带（西里尔人名 Ш/Д/Л、组合符、拉丁扩展）走 Libertinus Serif;
% otf 缺席则整段不挂, 免把缺字升级成字体加载错误。
% \IfFileExists 是死门: \openin 走 TEXINPUTS(texmf/tex/), 字体住
% texmf/fonts/ 恒查不到; fontspec \IfFontExistsTF 走 kpathsea 字体树。
% fontspec 由 ctex/xeCJK 块携带加载, \ifdefined 兜底裸贴场景=缺席同义。
% 门本体必须是原语 \if——\IfFontExistsTF{..}{体}{} 的实参在读取时即完成
% tokenize, 体里 \makeatletter/\catcode 守护来不及生效; 故先把判定
% 收进 flag。flag 用 \chardef+\ifnum 而非 \let..\iftrue——被跳过的
% 分支文本里出现裸 \iftrue/\iffalse token 会被条件扫描误计成开臂,
% \fi 配对全崩 (Incomplete \ifdefined 实证)。
% 00D7 ×/00F7 ÷ 是 binop 语义, 普通 ordinary 化会改距, 故带内挖掉。
\ifdefined\IfFontExistsTF
\IfFontExistsTF{LibertinusSerif-Regular.otf}{%
  \chardef\TeXlateFBok=1\relax}{\chardef\TeXlateFBok=0\relax}%
\else
\chardef\TeXlateFBok=0\relax
\fi
\ifnum\TeXlateFBok=1\relax
\DeclareFontFamily{TU}{texlatefb}{\hyphenchar\font\m@ne}
\DeclareFontShape{TU}{texlatefb}{m}{n}{<->"[LibertinusSerif-Regular.otf]"}{}
\DeclareFontShape{TU}{texlatefb}{b}{n}{<->"[LibertinusSerif-Bold.otf]"}{}
\DeclareFontShape{TU}{texlatefb}{bx}{n}{<->ssub*texlatefb/b/n}{}
\DeclareFontShape{TU}{texlatefb}{m}{it}{<->ssub*texlatefb/m/n}{}
\DeclareFontShape{TU}{texlatefb}{m}{sl}{<->ssub*texlatefb/m/n}{}
\DeclareFontShape{TU}{texlatefb}{b}{it}{<->ssub*texlatefb/b/n}{}
\DeclareFontShape{TU}{texlatefb}{bx}{it}{<->ssub*texlatefb/b/n}{}
\DeclareFontShape{TU}{texlatefb}{bx}{sl}{<->ssub*texlatefb/b/n}{}
\ifnum\count18<15\relax
\DeclareSymbolFont{texlatefb}{TU}{texlatefb}{m}{n}
\SetSymbolFont{texlatefb}{bold}{TU}{texlatefb}{b}{n}
\TeXlate@mathmap\symtexlatefb 0400-04FF;
\TeXlate@mathmap\symtexlatefb 0300-036F;
\TeXlate@mathmap\symtexlatefb 00C0-00D6;
\TeXlate@mathmap\symtexlatefb 00D8-00F6;
\TeXlate@mathmap\symtexlatefb 00F8-017F;
\fi
\fi
\catcode`\"=\TeXlate@dqcat
\makeatother
\fi
"""

#: 段落级溢出缓解：CJK 散文里夹长 inline math/不可断串（hash、URL）时,
#: 前两遍断行失败 → emergencystretch 给第三遍虚拟伸缩量换断点。只救本来
#: 就要炸的段，不动能排好的段（实证 16 重灾篇 overfull −24%）。
#: \AtBeginDocument 包裹——类若在 begin-document 钩子里自设此值, 我们后到赢。
OVERFLOW_MITIGATION = r"""
% texlate: emergencystretch for unbreakable zh+math paragraphs
\AtBeginDocument{\emergencystretch=1.5em\relax}%
"""

#: elsart 类「首用即弃」症状的兜底：xeCJK 的 `__xeCJK_select_font:` 初值是
#: `\prg_do_nothing:`，待宏包自身的 end-preamble/begindvi 钩子才换成真身；
#: 若首个 CJK 排版落在 elsart frontmatter 的 `\vbox` 捕获组（`\no@harm`
#: 上下文，loop1 实证 1003.5459 全文 5485 个 ec-lm* 丢字）内，字体选择
#: 机制永久未激活 → 整篇丢字。在 `\begin{document}` 排一个即弃的 CJK
#: hbox 可永久修复（机制级初始化，单字即可）。仅 XeTeX 挂载——pdflatex
#: 下裸 CJK 字符需 CJK 环境，反受其害。
CJK_FIRST_USE_WARMUP = r"""
% texlate: xeCJK first-use warmup (frontmatter \vbox poison)
\ifdefined\XeTeXversion
\AtBeginDocument{\setbox0=\hbox{字}}%
\fi
"""

#: ``\t``（tie 音符 U+0361）缺席 tuenc.def 的 15 个 DeclareUnicodeAccent——
#: TU 下该 cs 回落 TS1 ``\accent`` 原语，绕开 xeCJK interchartoks → 被饰
#: CJK 字符落进拉丁字体丢字（2003.10723 实证）。补一条 TU 声明即回到
#: 普通文本命令路径；非 TU 引擎（无 ``\UnicodeEncodingName``）整块跳过。
#: 码位实参写十进制 ``865``——``"``-hex 仅在 catcode-12 合法（dimcen A3
#: 机理，见 CJK_MATH_FALLBACK 守护），``\add@unicode@accent`` 下游就是
#: ``\char`` 数字扫描，十进制语义恒等且对 ``"`` 改写免疫。
TIE_ACCENT_FIX = r"""
% texlate: \t absent from tuenc.def -> TS1 \accent bypasses xeCJK
\ifdefined\UnicodeEncodingName
\DeclareUnicodeAccent{\t}{865}
\fi
"""

#: lmroman 8-bit 覆盖缺口 (A6, ~49 格): 西里尔/希腊/拉丁扩展字符落进
#: ec-lmr/aer10/futr8t 族 8-bit TFM 文本字体 → 整族丢字, font_fallback
#: 逐字 ``\newunicodechar`` 只盖 in-band。本块给这些码位单开
#: ``\XeTeXintercharclass`` → CMU Serif (cm-unicode otf, 全谱覆盖),
#: ``\XeTeXinterchartoks`` 进出边沿换族。全带并入同一 class——带内相邻
#: 字符不触发过渡, 字体稳持; 不碰 CJK 码位 (xeCJK 的 class 分配不受影响,
#: 且本块不接 ucharclasses——它给 CJKUnified 也派 class, 会盖掉 xeCJK)。
#: 0..31 类对全接线: xeCJK 类 → CMU 类相邻 (人名汉字混排) 也要换族。
#: ``\TeXlate@clsmap`` 的 ``"``-hex 与 CJK_MATH_FALLBACK 同机理——缝位在
#: ``\documentclass`` 后（正常 ``"``=12），类文件若自身投毒 ``"`` 仍中招；
#: 同款守护: ``\TeXlate@dqcat`` 存值 → ``\catcode`\"=12`` → 尾端还原。
TEXT_8BIT_FALLBACK = r"""
% texlate: CMU Serif fallback for 8-bit TFM coverage gaps (xetex only)
\ifdefined\XeTeXversion
% 字体门: \IfFileExists 走 \openin/TEXINPUTS(texmf/tex/) 恒假死门——otf 住
% texmf/fonts/; fontspec \IfFontExistsTF 走 kpathsea 字体树才查得到。
% fontspec 由 ctex/xeCJK 块携带加载, \ifdefined 兜底裸贴场景=缺席同义。
% 判定先收进 flag 再用原语 \if 门本体——宏实参会在读取时完成 tokenize,
% 体内 \makeatletter/\catcode`\" 守护来不及生效(同 fb 臂)。flag 用
% \chardef+\ifnum: 被跳过分支里的裸 \iftrue/\iffalse token 会被条件
% 扫描误计成开臂, \fi 配对全崩。
\ifdefined\IfFontExistsTF
\IfFontExistsTF{cmunrm.otf}{\chardef\TeXlateCMUok=1\relax}{\chardef\TeXlateCMUok=0\relax}%
\else
\chardef\TeXlateCMUok=0\relax
\fi
\ifnum\TeXlateCMUok=1\relax
\makeatletter
% texlate: " is a valid hex prefix only at catcode 12 (same guard as mathmap)
\chardef\TeXlate@dqcat=\the\catcode`\"\catcode`\"=12
\DeclareFontFamily{TU}{texlatecmu}{\hyphenchar\font\m@ne}
\DeclareFontShape{TU}{texlatecmu}{m}{n}{<->"[cmunrm.otf]"}{}
\DeclareFontShape{TU}{texlatecmu}{b}{n}{<->"[cmunbx.otf]"}{}
\DeclareFontShape{TU}{texlatecmu}{bx}{n}{<->ssub*texlatecmu/b/n}{}
\DeclareFontShape{TU}{texlatecmu}{m}{it}{<->"[cmunti.otf]"}{}
\DeclareFontShape{TU}{texlatecmu}{m}{sl}{<->ssub*texlatecmu/m/it}{}
\DeclareFontShape{TU}{texlatecmu}{b}{it}{<->"[cmunbi.otf]"}{}
\DeclareFontShape{TU}{texlatecmu}{bx}{it}{<->ssub*texlatecmu/b/it}{}
\DeclareFontShape{TU}{texlatecmu}{b}{sl}{<->ssub*texlatecmu/b/it}{}
\DeclareFontShape{TU}{texlatecmu}{bx}{sl}{<->ssub*texlatecmu/bx/it}{}
\edef\TeXlate@cmuprev{\familydefault}
\def\TeXlate@cmuOn{\edef\TeXlate@cmuprev{\f@family}%
  \fontfamily{texlatecmu}\selectfont}
\def\TeXlate@cmuOff{\fontfamily{\TeXlate@cmuprev}\selectfont}
\ifdefined\newXeTeXintercharclass
  \newXeTeXintercharclass\TeXlateCMUclass
\else
  \chardef\TeXlateCMUclass=200
\fi
\def\TeXlate@clsmap#1-#2;{\count@="#1\relax
  \@whilenum\count@<"#2 \do{\XeTeXcharclass\count@=\TeXlateCMUclass
  \advance\count@\@ne}}
% Cyrillic + supplements
\TeXlate@clsmap 0400-0530;
\TeXlate@clsmap 1C80-1C90;
\TeXlate@clsmap 2DE0-2E00;
\TeXlate@clsmap A640-A6A0;
\TeXlate@clsmap 1E030-1E090;
% Greek and Coptic + Greek Extended + Coptic
\TeXlate@clsmap 0370-0400;
\TeXlate@clsmap 1F00-2000;
\TeXlate@clsmap 2C80-2D00;
% Latin Extended-A/B + Additional + C-G + IPA/phonetics
\TeXlate@clsmap 0100-0250;
\TeXlate@clsmap 1E00-1F00;
\TeXlate@clsmap 2C60-2C80;
\TeXlate@clsmap A720-A800;
\TeXlate@clsmap AB30-AB70;
\TeXlate@clsmap 1DF00-1E000;
\TeXlate@clsmap 10780-107C0;
\TeXlate@clsmap 0250-0300;
\TeXlate@clsmap 1D00-1DC0;
% Combining diacritical marks (all four blocks)
\TeXlate@clsmap 0300-0370;
\TeXlate@clsmap 1AB0-1B00;
\TeXlate@clsmap 1DC0-1E00;
\TeXlate@clsmap 20D0-2100;
% Latin ligatures (ff/fi/fl …) in 8-bit slots
\TeXlate@clsmap FB00-FB50;
% 进出双向接线: 类 0..31 (xeCJK 占用带在内) + 边界 255 (+4095 新界)。
% CMUclass 自身也落在 0..31——循环把 (自类→自类) 配成 Off, 同类相邻
% 字符每对都复位字体, 一串西里尔只剩首字换族; 接线后清掉这对自环。
\count@=\z@
\@whilenum\count@<32 \do{%
  \XeTeXinterchartoks\count@\TeXlateCMUclass={\TeXlate@cmuOn}%
  \XeTeXinterchartoks\TeXlateCMUclass\count@={\TeXlate@cmuOff}%
  \advance\count@\@ne}
\XeTeXinterchartoks\TeXlateCMUclass\TeXlateCMUclass={}
\XeTeXinterchartoks 255 \TeXlateCMUclass={\TeXlate@cmuOn}
\XeTeXinterchartoks\TeXlateCMUclass 255 ={\TeXlate@cmuOff}
\ifdefined\XeTeXinterwordspaceshaping
\XeTeXinterchartoks 4095 \TeXlateCMUclass={\TeXlate@cmuOn}
\XeTeXinterchartoks\TeXlateCMUclass 4095 ={\TeXlate@cmuOff}
\fi
\XeTeXinterchartokenstate=\@ne
\catcode`\"=\TeXlate@dqcat
\makeatother
\fi
\fi
"""

#: ``\begin{逐字/失活环境}`` opener——遮盖视图把 opener 本身也抹成空白，
#: 判断 docclass 行尾是否藏吞行环境必须查原文 tail（fuzz I4）。
_ENV_OPEN_RE = re.compile(
    r"\\begin\s*\{(?:"
    + "|".join(re.escape(e) for e in sorted(VERBATIM_ENVS | DEAD_ENVS))
    + r")\}"
)

#: 可作主入口的 TeX 源后缀（mask.py TEX_SOURCE_SUFFIXES 的子集——
#: .sty/.cls 等是被装载件不作 main 候选；.ltx 是合法主档形态）。
#: tuple 保序：``_resolve_input`` 无扩展名补全按 kpathsea 序先 .tex 后 .ltx。
_MAIN_TEX_SUFFIXES = (".tex", ".ltx")

#: \documentclass 调用参数扫描上限（防御畸形输入死循环）。
_DOCCLASS_SCAN_LIMIT = 4000

#: ``_body_mass`` BFS 文件数上界——分数只是排序键，够分胜负即可，
#: 病态工程（数千 .tex）不拖死选取。
_MASS_FILE_CAP = 1024

#: ``filecontents`` 环境成员抽取：``\begin{filecontents[*]}{name}`` 写的文件
#: 物理不在包内，但编译时 TeX 会把它落到工作目录再 ``\input``——自解包形态
#: （1502.06414 index_preprint.tex：50+ 成员包真 doc，外层尾行 ``\input{index}``）。
#: 遮盖视图把环境连 begin 行整体抹平，抽取必须在 ``keep_verbatim`` 视图做：
#: 注释内的伪 ``\begin{filecontents}`` 已被抹掉，成员体原样保留。
_FILECONTENTS_BEGIN_RX = re.compile(
    r"\\begin\s*\{(filecontents[^}\s]*)\}\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}"
)

#: 虚拟成员表上界——自解包包体可含数十成员（sty/cls/def），tex 族成员
#: 才有闭包意义；超界即病态输入，成员表截断。
_VIRTUAL_MEMBER_CAP = 256


def _norm_virtual_key(name: str) -> str | None:
    r"""``filecontents`` 名 → 规范包内相对路径；逃逸/绝对/噪声 → ``None``。"""
    name = name.strip().strip('"').strip()
    if not name or name.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _filecontents_bodies(kept: str) -> dict[str, str]:
    r"""``keep_verbatim`` 视图上的 filecontents 成员表：名 → 体文本。

    ``kept`` 是 ``mask_tex(raw, keep_verbatim=True)`` 产物——注释已抹、
    逐字族环境（含 filecontents 体）原样。重复写同名成员先写者胜
    （filecontents 不覆盖已存在文件，TeX 语义同款）。
    """
    out: dict[str, str] = {}
    for m in _FILECONTENTS_BEGIN_RX.finditer(kept):
        end = re.compile(r"\\end\{" + re.escape(m.group(1)) + r"\}").search(
            kept, m.end()
        )
        key = _norm_virtual_key(m.group(2))
        if key is not None and key not in out:
            out[key] = kept[m.end() : end.start() if end else len(kept)]
        if len(out) >= _VIRTUAL_MEMBER_CAP:
            break
    return out


def _resolve_virtual(
    root: Path, decl_dir: Path, name: str, virtual: Mapping[str, str]
) -> tuple[Path, str] | None:
    r"""``\input`` 目标 → filecontents 虚拟成员 ``(pseudo_path, body)``。

    磁盘解析缺席后的二探（``_resolve_input`` 同口径：无扩展名补 ``.tex``
    /``.ltx``，声明目录→工程根两跳）。pseudo_path 是该文件编译时会被
    filecontents 落盘的合成位（root 下成员名）——``seen`` 键与嵌套
    ``\input`` 基准目录沿用真路径语义，不落盘。
    """
    names = [name] if Path(name).suffix else [name + ext for ext in _MAIN_TEX_SUFFIXES]
    try:
        decl_rel = decl_dir.relative_to(root).as_posix()
    except ValueError:
        decl_rel = ""
    if decl_rel == ".":
        decl_rel = ""
    for fname in names:
        if Path(fname).suffix.lower() not in _MAIN_TEX_SUFFIXES:
            continue
        for base in (decl_rel, ""):
            key = f"{base}/{fname}" if base else fname
            body = virtual.get(key)
            if body is not None:
                return root / key, body
    return None


#: FLOAT_SIZING 仅在有 figure/table 时注入（docs/08 §3.3）。
FLOAT_SIZING = r"""% texlate: fit complete oversized float boxes v1
\usepackage{graphicx}
\begingroup
\makeatletter
\AtBeginDocument{%
\let\texlate@endfloatbox\@endfloatbox
\def\@endfloatbox{%
\texlate@endfloatbox
\def\texlate@figure{figure}%
\def\texlate@figurestar{figure*}%
\def\texlate@table{table}%
\def\texlate@tablestar{table*}%
\let\texlate@floatscope\@empty
\ifx\@currenvir\texlate@figure\def\texlate@floatscope{1}\fi
\ifx\@currenvir\texlate@figurestar\def\texlate@floatscope{1}\fi
\ifx\@currenvir\texlate@table\def\texlate@floatscope{1}\fi
\ifx\@currenvir\texlate@tablestar\def\texlate@floatscope{1}\fi
\ifx\texlate@floatscope\@empty\else
\ifdim\dimexpr\ht\@currbox+\dp\@currbox\relax>\textheight
\edef\texlate@floatwidth{\the\wd\@currbox}%
\edef\texlate@floatheight{\the\dimexpr\textheight-\baselineskip\relax}%
\ifdim\texlate@floatheight>0pt
\typeout{TeXlate-Float-Fit: \@captype\space \csname the\@captype\endcsname; height \the\dimexpr\ht\@currbox+\dp\@currbox\relax; limit \texlate@floatheight}%
\global\setbox\@currbox=\vbox{\hbox to\texlate@floatwidth{\hfil\resizebox*{!}{\texlate@floatheight}{\box\@currbox}\hfil}}%
\fi\fi\fi}%
}
\endgroup
"""

#: TABLE_FITTING hook threeparttable（adjustbox max width）。
TABLE_FITTING = r"""% texlate: fit complete measured table containers v1
\usepackage{adjustbox}
\begingroup
\makeatletter
\AtBeginDocument{%
\newif\iftexlate@tablefit
\newenvironment{TeXlateFitTable}{%
\iftexlate@tablefit
\let\texlate@endtablefit\relax
\else
\texlate@tablefittrue
\def\texlate@endtablefit{\end{adjustbox}}%
\begin{adjustbox}{max width=\linewidth}%
\fi\ignorespaces
}{\texlate@endtablefit}%
\AddToHook{env/threeparttable/before}{\begin{TeXlateFitTable}}%
\AddToHook{env/threeparttable/after}{\end{TeXlateFitTable}}%
}
\endgroup
"""


class InjectRejectError(ValueError):
    r"""`\documentstyle` 等不可注入形态——走降级链，不进编译。

    与 ``route_project`` 的 reject 分流：route 对 documentstyle 只打
    ``latex209_suspect``（先试编），inject 拒的是「注入后必死」——
    消费侧记 ``inject_reject:<reason>`` 类。
    """

    def __init__(self, reason: str = "latex209") -> None:
        """记录拒绝原因（默认 latex209 documentstyle）。"""
        self.reason = reason
        super().__init__("inject_reject:" + reason)


def _resolve_input(root: Path, decl_dir: Path, name: str) -> Path | None:
    r"""``\input``/``\include`` 目标 → 本地 .tex（声明目录→工程根两跳，kpathsea 序）。

    无扩展名补 ``.tex``；解析到非 .tex（``.bbl``/``.sty`` 等）或越出
    工程根的目标不计入 body 量（probe.py ``_find_local`` 同口径）。
    """
    names = [name] if Path(name).suffix else [name + ext for ext in _MAIN_TEX_SUFFIXES]
    for fname in names:
        if Path(fname).suffix.lower() not in _MAIN_TEX_SUFFIXES:
            continue
        for base in (decl_dir, root):
            # ``\input`` 参数是文档可控面——巨名 ENAMETOOLONG、symlink loop
            # RuntimeError、NUL ValueError 按不可解析处理（consistency-audit）。
            cand = safe_resolve(base / fname)
            if cand is not None and safe_is_file(cand) and cand.is_relative_to(root):
                return cand
    return None


def _walk_inputs(
    root: Path,
    seeds: list[tuple[Path, str]],
    virtual: Mapping[str, str] | None = None,
) -> Iterator[tuple[Path, str]]:
    r"""``\input``/``\include`` 传递闭包遍历：产出 ``(resolved_path, visible_text)``。

    从 ``(decl_file, visible_text)`` 种子出发，在遮盖视图上扫描 input 族
    目标（注释/verbatim 内的 ``\input`` 不参与），逐文件解析可存在的本地
    .tex（``_resolve_input`` 口径：声明目录→工程根两跳、越出工程根不计）。
    ``virtual`` 非空时磁盘缺席再探 filecontents 虚拟成员（自解包形态）。
    环引由 visited 集收，规模上界 ``_MASS_FILE_CAP``。
    """
    vmap: Mapping[str, str] = virtual if virtual is not None else {}
    seen = {src for src, _vis in seeds}
    queue = list(seeds)
    while queue and len(seen) <= _MASS_FILE_CAP:
        src, vis = queue.pop()
        for match in (
            *INPUT_BRACED_RX.finditer(vis),
            *INPUT_BARE_RX.finditer(vis),
        ):
            name = clean_decl_name(match["arg"])
            if name is None:
                continue
            tgt = _resolve_input(root, src.parent, name)
            if tgt is None and vmap:
                hit = _resolve_virtual(root, src.parent, name, vmap)
                if hit is not None and hit[0] not in seen:
                    tgt, body = hit
                    seen.add(tgt)
                    sub = visible_tex(body)
                    queue.append((tgt, sub))
                    yield tgt, sub
                    continue
            if tgt is None or tgt in seen:
                continue
            seen.add(tgt)
            try:
                blob = tgt.read_bytes()
            except OSError:
                continue
            if _tar_disguised(blob):
                continue  # tar 伪装件——成员字节不是闭包面（normalize._tex_sources 同闸）
            sub = visible_tex(decode_tex(blob))
            queue.append((tgt, sub))
            yield tgt, sub


def _closure_has_document(
    root: Path,
    main: Path,
    text: str,
    virtual: Mapping[str, str] | None = None,
) -> bool:
    r"""``\begin{document}`` 在本体或 ``\input`` 传递闭包任一文件中可见。

    编排壳 main（``\documentclass`` + ``\input{body}``，bd 落在被拉入的
    子文件——cs/0408015 ``main.tex→body.tex``、2105.00092
    ``main.tex→begin.tex`` 形态）按本谓词收为候选；闭包文件与本体同在
    遮盖视图判定，注释掉的 bd/``\input`` 不计。``virtual`` 提供
    filecontents 虚拟成员表（自解包形态）时磁盘缺席再探虚拟文件。
    """
    if BEGIN_DOC_RX.search(text):
        return True
    return any(
        BEGIN_DOC_RX.search(sub)
        for _tgt, sub in _walk_inputs(root, [(main, text)], virtual)
    )


def _closure_has_docclass(
    root: Path,
    main: Path,
    text: str,
    virtual: Mapping[str, str] | None = None,
) -> bool:
    r"""``\documentclass``/``\documentstyle`` 在本体或 ``\input`` 闭包可见。

    W99 形态：docclass 写在被 ``\input`` 拉入的 helper 里（0905.2435
    ``body.tex`` ``\input seki-deckblatt-3`` → helper 内
    ``\documentclass[twoside,12pt]{\whatSEKIDOCUMENTCLASS}`` 宏参类名），
    主文件本体零声明但 TeX 编译照常——候选识别与 bd 同口径走闭包。
    """
    if DOCCLASS_RX.search(text):
        return True
    return any(
        DOCCLASS_RX.search(sub)
        for _tgt, sub in _walk_inputs(root, [(main, text)], virtual)
    )


def _body_mass(
    root: Path,
    main: Path,
    body: str,
    virtual: Mapping[str, str] | None = None,
) -> int:
    r"""``\begin{document}`` 后实质 body 量：可见非空白字符数 + ``\input`` 闭包。

    standalone 图档也能凑齐 ``document`` 环境但 body 与正文章节脱节——
    裸 body 长度分不出「1K 的 ``\include`` 编排壳」与「1.5K 的 tikz 图」，
    故按「这篇 document 实际拉进多少 .tex 内容」计：本体 body 可见非空白
    字符 + body 内 ``\input``/``\include`` 可解析目标的传递闭包逐文件
    同口径计数（1803.02985 E 桶：thesis.tex 本体 ~0.7K/闭包 ~400K，
    standalone 图 body ~1.5K/闭包 0）。环引由 visited 集收，规模上界
    ``_MASS_FILE_CAP``。
    """
    mass = len(re.sub(r"\s", "", body))
    for _tgt, sub in _walk_inputs(root, [(main, body)], virtual):
        mass += len(re.sub(r"\s", "", sub))
    return mass


def find_main_tex(root: Path) -> Path | None:  # noqa: C901, PLR0912 — 候选过滤+排序启发式平铺即算法本体
    r"""定位主 .tex：最浅、最像正文的 `\documentclass`+`\begin{document}` 文件。

    候选门槛：`\documentclass`/`\documentstyle` 必须在文件本体（遮盖视图），
    `\begin{document}` 允许落在本体的 `\input`/`\include` 传递闭包内——
    编排壳 main 只拉子文件、bd 在下游（cs/0408015、2105.00092 形态）。

    排序：英文正文优先（多语种版本不靠 UTF-8 字节数排序——多字节文字
    系统性吃亏）→ main/paper/ms 名 → 模板参档后置（``\documentclass``
    的 ``[...]`` 里含控制序列 = 类文档模板算选项，如 aipguide
    ``[\optionlist]{aipproc}``；真论文写字面选项——1206.0565 类发行
    捆绑包中 guide/check 档 body 量比正主还大，需在深度/量级前挡下）
    → 目录深度 → 实质 body 量级
    （`\begin{document}` 后可见字符 + `\input` 闭包的十进制位数——
    standalone 图档/document 薄壳与真 main 分野，1803.02985 E 桶修法；
    只仲裁量级差，近等值回退文件大小，避免 `ver1/`、`old/`、diff 档
    这类版本目录副本被几个百分点翻盘）→ 文件大小。
    """
    resolved = root.resolve()
    scanned: list[tuple[Path, str, str]] = []
    kept_views: list[str] = []
    for p in sorted(
        p for p in root.rglob("*") if p.suffix.lower() in _MAIN_TEX_SUFFIXES
    ):
        try:
            blob = p.read_bytes()
        except OSError:
            continue
        if _tar_disguised(blob):
            continue  # tar 伪装件——成员文本可含 bd/dc 假信号且改写即腐蚀 blob
        raw = decode_tex(blob)
        scanned.append((p.resolve(), p.relative_to(root).as_posix(), visible_tex(raw)))
        if "filecontents" in raw:
            kept_views.append(mask_tex(raw, keep_verbatim=True))
    virtual: dict[str, str] = {}
    for kept in kept_views:
        for key, body in _filecontents_bodies(kept).items():
            virtual.setdefault(key, body)

    candidates = []
    bodies = {}
    tpl: dict[str, bool] = {}

    def _admit(rel: str, text: str) -> None:
        candidates.append(rel)
        # 与 _closure_has_document 的 ``\\begin\s*\{document\}`` 同口径——
        # ``\begin {document}``（空白合法）字面 split 切不到，body 量被
        # 前导区虚抬。
        bodies[rel] = BEGIN_DOC_RX.split(text, maxsplit=1)[-1]
        dc = DOCCLASS_DECL_RX.search(text)
        tpl[rel] = bool(dc and dc.group(2) and "\\" in dc.group(2))

    for p, rel, text in scanned:
        if not DOCCLASS_RX.search(text):
            continue
        if not _closure_has_document(resolved, p, text):
            continue
        _admit(rel, text)
    if not candidates:
        # W99 二遍（纯增量——只把 ``<none>`` 翻成 main，不搅动已有池序）：
        # docclass 可经 ``\input`` 闭包供给（helper 文件/W99 宏参类名，
        # 或 filecontents 虚拟成员）——本体无声明但 bd+dc 双闭包齐者入池。
        for p, rel, text in scanned:
            if not (
                BEGIN_DOC_RX.search(text)
                or INPUT_BRACED_RX.search(text)
                or INPUT_BARE_RX.search(text)
            ):
                continue  # 无 bd 也无 input 边 → 闭包双判定必空
            if not _closure_has_document(resolved, p, text, virtual):
                continue
            if not _closure_has_docclass(resolved, p, text, virtual):
                continue
            _admit(rel, text)
    if not candidates:
        return None

    def language_rank(path: str) -> bool:
        body = bodies[path]
        letters = sum(c.isalpha() for c in body)
        latin = len(re.findall(r"[A-Za-z]", body))
        return letters > 0 and latin < letters / 2

    masses = {
        rel: _body_mass(resolved, (resolved / rel).resolve(), bodies[rel])
        for rel in candidates
    }

    candidates.sort(
        key=lambda p: (
            language_rank(p),
            Path(p).name not in ("main.tex", "paper.tex", "ms.tex"),
            tpl[p],
            len(Path(p).parts),
            -len(str(masses[p])),
            -(root / p).stat().st_size,
        )
    )
    return root / candidates[0]


#: ``classify_no_main`` 的 plain-TeX/AMS-TeX 指纹：``\magnification``/``\magstep``
#: /``\bye``/``\font\<cs>`` 装载原语、裸 ``\end``（负向断言挡 ``\end{env}``）、
#: ``\input`` 的 209 前宏包名（attr 报告 §1.2 实测集 + gr-qc/9901068 补）。
#: 只在无 dc/ds 的空池上判定——LaTeX 工程到不了这层，指纹误伤面天然有界。
_PLAIN_TEX_RE = re.compile(
    r"\\magnification\b|\\magstep\b|\\bye\b|\\font\\|\\end\b(?!\s*\{)"
    r"|\\input\s*\{?\s*(?:harvmac|phyzzx|amstex|amsppt|epsf|jytex|mn|texinfo)\b"
)


def classify_no_main(root: Path) -> str | None:
    r"""``find_main_tex`` 空池归因：确认不可修的上游形态 → 子码；存疑 → ``None``。

    P-D 细分（bench/results/no-main-tex-attr-2026-09-17/report.md §3）——
    全树 ``*.tex`` 遮盖视图（注释/verbatim 内命中不算）上归桶：

    - ``"latex209"``：无 ``\documentclass`` 但有 ``\documentstyle``——209 时代
      池（amsppt 顶物 ``\endtopmatter \document`` 形态；与 route 的
      ``latex209_suspect`` 同族，upgrade_209 是旁路）。
    - ``"plain_tex"``：dc/ds/bd 三无但有 plain-TeX/AMS-TeX 指纹
      （``_PLAIN_TEX_RE``：装载原语 + 209 前 ``\input`` 宏包名）——
      xelatex/tectonic 路由下本不可编，拒绝正确。
    - ``"garbage"``：无任何可判 TeX/LaTeX 结构——HTML/DVI 伪装 .tex、撤稿
      stub、无 driver 残片断、零 ``.tex`` 树。
    - ``None``：可见 ``\documentclass`` 或 ``\begin{document}`` 但链路未闭——
      可能是检测缺口或真散件，票面留 ``no_main_tex`` 不归上游。

    消费方记 ``no_main_tex:<sub>``（stagerun errors payload、fixloop verdict
    后缀、worker/e2e reason 后缀）；``None`` 时票面不变。
    """
    has_ds = has_bd = plain = False
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in _MAIN_TEX_SUFFIXES:
            continue
        try:
            blob = p.read_bytes()
        except OSError:
            continue
        if _tar_disguised(blob):
            continue  # tar 伪装件——成员文本不供 dc/ds/bd/指纹判据
        vis = visible_tex(decode_tex(blob))
        if DOCCLASS_ONLY_RX.search(vis):
            return None
        has_ds |= DOCSTYLE_RX.search(vis) is not None
        has_bd |= BEGIN_DOC_RX.search(vis) is not None
        plain |= _PLAIN_TEX_RE.search(vis) is not None
    if has_ds:
        return "latex209"
    if has_bd:
        return None
    if plain:
        return "plain_tex"
    return "garbage"


def _docclass_close(vis: str, start: int) -> int:
    r"""从 `\documentclass` 命令名之后扫描 `[opt]{cls}` 配对，返回 `}` 后 offset。

    在 visible_tex 遮盖视图上扫——`%` 注释/verbatim 已等长抹成空格，
    注释内括号不参与配对。命令名与首括号之间只允许空白（含被抹平的
    注释残位）：`\documentclass\cls` 宏实参/裸声明形态下首个非空白
    token 不是 `[`/`{`，扫到则收口返回 start（调用方退化行尾缝）——
    无界前扫曾把远处 `\begin{document}` 的花括号吞成类名实参，缝落
    enddoc 行死注（I2）。
    """
    j, n = start, len(vis)
    db = dc = 0
    seen_brace = False
    while j < n:
        c = vis[j]
        if not seen_brace and db == 0 and c not in "[{ \t\n\r":
            return start
        if c == "\\":
            j += 2
            continue
        if c == "[":
            db += 1
        elif c == "]":
            db -= 1
        elif c == "{":
            dc += 1
            seen_brace = True
        elif c == "}":
            dc -= 1
            if seen_brace and dc == 0 and db <= 0:
                return j + 1
        if j - start > _DOCCLASS_SCAN_LIMIT:
            break
        j += 1
    return j


def find_docclass_ends(tex: str) -> list[tuple[int, int, str]]:
    r"""全部可用的 `\documentclass`/`\documentstyle` 注入缝 `(pos, lineno, cmd)`。

    在 visible_tex 等长遮盖视图上扫（注释/verbatim 命中天然消失，offset
    与原文对齐）。brace depth>0 的命中——`\newcommand{\ds}{\documentstyle}`
    类宏体（1706.07796）、`\ifmain{...}` 型实参——不是真声明点，跳过。

    条件分支内命中**不判死活**（`\ifpdf A \else B \fi` 双 docclass 是
    sigma/jhep 系标准形态；`\ifemulate`/`\ifdefined` 同理）——调用方逐缝
    注入，哪条臂执行哪条臂生效（loop1 A 桶：旧版取首个命中，落死分支
    则注入物整段进死代码 → 中文静默缺失）。
    """
    vis = visible_tex(tex)
    hits: list[tuple[int, int, str]] = []
    seen_pos: set[int] = set()
    for m in iter_depth0(DOCCLASS_RX, vis):
        close = _docclass_close(vis, m.end())
        if close > 0 and vis[close - 1] == "}":
            eol = tex.find("\n", close)
            lineno = tex.count("\n", 0, close) + 1
            # ``}`` 后同行纯空白/注释 → 行尾缝（吞注释安全位）；同行有活
            # 代码（单行文档的 bd/enddoc）或行尾开逐字/失活环境（opener 自身
            # 在 vis 上被抹平，须查原文 tail）则 ``}`` 后即插——插到其前不
            # 劈断、不落死文本/环境体（I1/I3/I4）。
            tail = vis[close : eol if eol >= 0 else len(vis)]
            raw_tail = tex[close : eol if eol >= 0 else len(tex)]
            insert = (
                eol
                if eol >= 0 and not tail.strip() and not _ENV_OPEN_RE.search(raw_tail)
                else close
            )
        else:
            # 无 {..} 的裸 \documentclass：退化为行尾注入。
            eol = tex.find("\n", m.end())
            lineno = tex.count("\n", 0, m.start()) + 1
            insert = len(tex) if eol < 0 else eol
        if insert not in seen_pos:  # 单行 `\if..\else..\fi` 双命中同缝
            seen_pos.add(insert)
            hits.append((insert, lineno, m.group(1)))
    if not hits:
        hits = _macro_proxy_seams(tex, vis)
    return hits


def _macro_proxy_seams(tex: str, vis: str) -> list[tuple[int, int, str]]:
    r"""宏包声明形态的回退缝。

    ``\def\doc{...\documentclass{cls}...}`` + 顶层 ``\doc`` 调用 —— 真声明
    藏在宏体内（depth>0 被 ``find_docclass_ends`` 主循环跳过），可编译
    文档会静默零注入（I9）。

    收集 ``\newcommand/\renewcommand/\def/\gdef`` 体内含声明命令的宏名，
    顶层（depth 0）调用行行尾即缝——注入物在执行序上位于真声明之后。
    """
    proxy: dict[str, str] = {}
    def_sites: set[int] = set()
    for m in re.finditer(
        r"\\(?:(?:new|renew|provide)command|DeclareRobustCommand|def|gdef|edef|xdef)"
        r"\*?\s*\{?\\([a-zA-Z@]+)\}?",
        vis,
    ):
        brace = vis.find("{", m.end())
        if brace < 0:
            continue
        body_end = group_end(vis, brace)
        dm = DOCCLASS_RX.search(vis, brace, body_end)
        if dm is not None:
            proxy[m.group(1)] = dm.group(1)
            def_sites.add(m.start(1) - 1)  # 定义位的 \name token 不算调用
    if not proxy:
        return []
    names = "|".join(sorted(proxy))
    invoke_re = re.compile(rf"\\(?:{names})(?![a-zA-Z@])")
    hits: list[tuple[int, int, str]] = []
    for m in iter_depth0(invoke_re, vis):
        if m.start() in def_sites:
            continue
        eol = tex.find("\n", m.end())
        insert = len(tex) if eol < 0 else eol
        lineno = tex.count("\n", 0, m.start()) + 1
        hits.append((insert, lineno, proxy.get(m.group(0)[1:], "documentclass")))
    return hits


def find_docclass_end(tex: str) -> tuple[int, int, str] | None:
    r"""首个可用 `\documentclass` 缝（``find_docclass_ends`` 的首元素）。"""
    hits = find_docclass_ends(tex)
    return hits[0] if hits else None


def _splice_after_seams(tex: str, hits: list[tuple[int, int, str]], block: str) -> str:
    r"""逐缝 ``\n``+block 回填——pos 为原 tex 绝对 offset，顺序累加 delta。"""
    out = tex
    delta = 0
    for pos, _ln, _c in hits:
        out = out[: pos + delta] + "\n" + block + out[pos + delta :]
        delta += len(block) + 1
    return out


def _splice_before_document(
    tex: str, block: str, *, after: int = 0, sentinel: str = "TeXlateMathFB"
) -> str:
    r"""``\begin{document}`` 前逐点 ``\n``+block 回填——preamble 尾锚。

    多 bd 形态（条件双 bd/坏档）逐点注入 + 幂等哨兵（与 docclass 多缝
    同款：活臂执行立哨，余点整块跳过）；右向左回填免 offset 簿记。
    只认 ``after``（首个 docclass 缝位）之后的 bd——先于缝位的 bd 不是
    preamble 尾，锚在那里会把声明放到 ``\documentclass`` 行之前。
    bd 命中取 ``iter_depth0``：``\def\bd{\begin{document}}``/``\newcommand``
    宏体内的 bd 字样不是真文档起点——裸 finditer 把注入块楔进 ``\def\bd{``
    与 ``\begin{document}}`` 之间，宏体吞含 ``#1`` 的定义即 "Illegal
    parameter number in definition of \bd"（hep-th/0307203、
    hep-th/9910011、0905.0876 实案）；depth>0 一律不算锚点。
    无合格 bd 则原样返回（调用方负责退化路径）。
    """
    positions = sorted(
        {
            m.start()
            for m in iter_depth0(BEGIN_DOC_RX, visible_tex(tex))
            if m.start() > after
        }
    )
    if not positions:
        return tex
    if len(positions) > 1:
        block = (
            f"% texlate: {sentinel} (multi-bd idempotent)\n"
            f"\\ifdefined\\{sentinel}\\else\n"
            f"\\def\\{sentinel}{{1}}%\n" + block + "\\fi\n"
        )
    for pos in reversed(positions):
        tex = tex[:pos] + "\n" + block + tex[pos:]
    return tex


def inject_cjk(  # noqa: C901 — ctex/xecjk 双模锚点分派+幂等校验平铺
    tex: str, *, mode: str = "ctex", root: Path | None = None
) -> tuple[str, dict]:
    r"""在主文件文本上注入中文支持。返回 `(new_text, info)`。

    mode `"ctex"`：`\documentclass` 行后插 `\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}`
    （hjfy 同款、双引擎实测 0% 破坏、白拿节名汉化；`zihao=false` 钉住防
    scheme=chinese 默认强启 zihao=5 把全文版式撑大 5.4%）。
    mode `"xecjk"`：同缝插 xeCJK+Fandol 块（ctex 冲突签名→fixloop/探针切换用）。

    `\documentstyle` → 先经 latex209.upgrade_209 升级转换（209 兼容模式内核层
    禁 `\usepackage`，注入前必须升级；`root` 提供工程树做随源 .sty 检测）。
    不可转形态（ds@ 选项机类）才抛 InjectRejectError，reason 注明机制。
    """
    if CJK_PRESENT_RE.search(visible_tex(tex)):
        return tex, {"status": "already"}
    hits = find_docclass_ends(tex)
    if not hits:
        return tex, {"status": "no-docline"}
    _pos, lineno, cmd = hits[0]
    conv: dict | None = None
    if cmd == "documentstyle":
        tex, conv = upgrade_209(tex, root=root)
        if conv["status"] != "converted":
            raise InjectRejectError(str(conv.get("reason") or "latex209"))
        hits = find_docclass_ends(tex)
        if not hits:  # 转换产物必含 \documentclass——防御性兜底
            raise InjectRejectError
        lineno = hits[0][1]
    block = CTEX_LINE + "  % [texlate injected]" if mode == "ctex" else XECJK_BLOCK
    block += THEOREM_ANCHOR_SHIM
    block += CJK_FIRST_USE_WARMUP
    block += TIE_ACCENT_FIX
    block += TEXT_8BIT_FALLBACK
    block += OVERFLOW_MITIGATION
    # 符号字体声明下沉 preamble 尾（b2 界外需求 W157-W161）：
    # \DeclareSymbolFont 占 mathgroup 全局序号——docclass 缝位在用户字体包
    # 之前抢号会把文档族号全体后移（1706.00183 硬编码 \mathchar 位移 ×271）
    # 或打满 16 上限（2308.04246 txfonts 溢出）。bd 在档时挪到 bd 前——
    # 用户字体包先行声明，注入字体取余号；bd 不在档（编排壳）维持缝位。
    # 合格锚 = 首个缝位之后的 bd；bd 全在缝位之前视同无 bd（回落缝位）。
    bd_in_main = any(
        m.start() > hits[0][0] for m in iter_depth0(BEGIN_DOC_RX, visible_tex(tex))
    )
    if not bd_in_main:
        block += CJK_MATH_FALLBACK
    if len(hits) > 1:
        # 幂等哨兵：分支选择形态（\ifpdf A \else B \fi）逐缝注入，活臂的块
        # 执行后立哨；万一第二缝也执行（顺序双 \documentclass 坏档）整块
        # 跳过。\fi 配对安全：块内 \if 全成对（skip 计数平衡）。
        block = (
            "% texlate: CJK support (multi-seam idempotent)\n"
            "\\ifdefined\\TeXlateCJKloaded\\else\n"
            "\\def\\TeXlateCJKloaded{1}%\n" + block + "\\fi\n"
        )
    out = _splice_after_seams(tex, hits, block)
    if bd_in_main:
        out = _splice_before_document(out, CJK_MATH_FALLBACK, after=hits[0][0])
    info: dict = {"status": "injected", "mode": mode, "line": lineno}
    if conv is not None:
        info["upgrade209"] = conv
    if len(hits) > 1:
        info["seams"] = len(hits)
    return out, info


def inject_float_sizing(root: Path) -> int:
    r"""FLOAT_SIZING 前导块：仅在工程确实含 figure/table 环境时注入主文件。

    超高 float 用 `\resizebox*` 缩进页高 + `\typeout{TeXlate-Float-Fit:}`
    供日志回读。返回注入文件数（0/1）。
    """
    sources = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _MAIN_TEX_SUFFIXES:
            try:
                blob = path.read_bytes()
            except OSError:
                continue  # chmod-0 等不可读档跳过（consistency-audit）
            if _tar_disguised(blob):
                continue  # tar 伪装件——成员字节非手术面，写回即腐蚀 blob
            sources[path] = decode_tex(blob)
    if not any(
        re.search(r"\\begin\s*\{(?:figure|table)\*?\}", visible_tex(text))
        for text in sources.values()
    ):
        return 0
    n = 0
    for path, text in sources.items():
        new_text = _float_sized(text)
        if new_text != text:
            try:
                path.write_text(new_text, encoding="utf-8")
            except OSError:
                continue  # 不可写档不计入
            n += 1
    return n


def _float_sized(text: str) -> str:
    r"""单文件 FLOAT_SIZING 注入：dc 在档即收，返回改写后文本（未变=不注）。

    ``\AtBeginDocument`` 钩子只要求前导区位置——bd 在 ``\input`` 子文件的
    编排壳 main（cs/0408015 形态）同权；有 bd 走 ``_splice_before_document``
    depth-0 锚（宏体内 bd 字样不算——``\def\bd{\begin{document}}`` 简写形态），
    无 bd 落 docclass 缝后（多臂声明逐缝注入 + 哨兵兜双执行——
    ``\let\texlate@endfloatbox\@endfloatbox`` 二次捕获已补丁版本会自递归）。
    """
    vis = visible_tex(text)
    if FLOAT_SIZING.strip() in text or not DOCCLASS_RX.search(vis):
        return text
    if next(iter_depth0(BEGIN_DOC_RX, vis), None) is not None:
        return _splice_before_document(text, FLOAT_SIZING, sentinel="TeXlateFloatFit")
    hits = find_docclass_ends(text)
    if not hits:
        return text
    block = FLOAT_SIZING
    if len(hits) > 1:
        block = (
            "% texlate: float sizing (multi-seam idempotent)\n"
            "\\ifdefined\\TeXlateFloatFit\\else\n"
            "\\def\\TeXlateFloatFit{1}%\n" + FLOAT_SIZING + "\\fi\n"
        )
    return _splice_after_seams(text, hits, block)


def inject_table_fitting(tex: str) -> str:
    """TABLE_FITTING 前导块：工程含 threeparttable 时注入（调用方负责判据）。"""
    if TABLE_FITTING.strip() in tex:
        return tex
    return _splice_before_document(tex, TABLE_FITTING, sentinel="TeXlateTableFit")


def prepare_chinese(
    root: Path, main: Path | str, *, mode: str = "ctex", float_sizing: bool = True
) -> dict:
    r"""工程级中文注入编排：主文件 ctex/xeCJK + 按需 FLOAT_SIZING/TABLE_FITTING。

    返回注入报告 dict（注入缝行号/模式/已存在标记）。`\documentstyle` 工程
    抛 InjectRejectError——调用方应记 ``inject_reject:<reason>`` 类 reject
    （与 route reject 分流），而非编译失败。
    """
    main_path = root / main if isinstance(main, str) else main
    blob = main_path.read_bytes()
    if _tar_disguised(blob):
        # 兜底闸：find_main_tex 已排除 tar 候选，本层挡绕开检出直传的
        # 伪装 main——latin-1 解出的成员文本可含 dc 缝，注入写回即腐蚀。
        raise InjectRejectError(reason="nontex")
    text = decode_tex(blob)
    new_text, info = inject_cjk(text, mode=mode, root=root)
    if "threeparttable" in visible_tex(new_text):
        # 已带 CJK 的工程（status=already）同样要 threeparttable 溢宽钩子。
        new_text = inject_table_fitting(new_text)
    if new_text != text:
        main_path.write_text(new_text, encoding="utf-8")
    if float_sizing:
        info["float_sizing"] = inject_float_sizing(root)
    return info
