r"""中文支持注入：ctex `[fontset=fandol,UTF8]` 默认路径 + xeCJK 降级路径 + 数学兜底。

`CJK_MATH_FALLBACK`：xeCJK interchartoks 不进数学模式，译文落 `$..$`/
`\boldmath` 头标即在数学族字体丢字，`\Umathcode` 重映进 FandolSong
（CJK 九段）/ Libertinus Serif（西里尔·组合符·拉丁扩展）符号字体补齐。

docs/spec/compile.md 注入缝：
- 兼容块 → `\begin{document}` 前（``_seams._splice_before_document``，depth-0 锚）
- 字体系块 → `\documentclass{}` 后（``_seams.find_docclass_ends``：逐缝注入，
  `\ifpdf A \else B \fi` 分支选择形态每条臂各落一份幂等块）
- preamble 消费仿真定义 → 同 docclass 缝（normalize.XETEX_EARLY_DEFS 经
  ``_seams`` find_docclass_ends/_splice_after_seams 消费；无 bd/子档闸——
  bd 藏 ``\input`` 子件形态 main 零 bd，2609.19376 实案）
- `\documentstyle` → **禁止注入 + inject 层 reject**（ctex/xeCJK 与 2.09
  互不兼容；route_project 已降级为 latex209_suspect 试编标记——
  inject 是 2.09 的兜底拒绝点，账本记 `inject_reject:latex209`
  与 route reject 分流）

实证：compile-bench 72 次编译中 ctex 注入破坏率 0%（bench/results/compile-report.md）。

C4 拆分：本模块宿 CJK 注入编排（``inject_cjk``/``_input_hop_*``/
``prepare_chinese``）。缝原语（``_splice_*``/``find_docclass_ends``）
出叶 ``_seams``——inject/layout/normalize 三向单向消费；主文件发现+
``\input`` 闭包+filecontents 虚拟 FS 出叶 ``mainfile``，版式手术
（FLOAT_SIZING/TABLE_FITTING/wrapfloat 降级）出叶 ``layout``——两叶
消费名经本模块静态回引（钉点面守恒；layout 缝原语已转 ``_seams``
单向取用，旧 inject↔layout 顶层互引环断，``__getattr__`` 惰性转口退役）。
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

from texlate.textutil import (
    BEGIN_DOC_RX,
    DOCCLASS_RX,
    INPUT_BARE_RX,
    INPUT_BRACED_RX,
    _tar_disguised,
    clean_decl_name,
    decode_tex,
    iter_depth0,
    safe_resolve,
)

from ._seams import _splice_after_seams, _splice_before_document, find_docclass_ends
from .latex209 import upgrade_209
from .layout import (  # noqa: F401 — C4 出叶回引：layout 缝原语转 _seams 后环断，钉点名转静态回引
    FLOAT_SIZING,
    TABLE_FITTING,
    _demote_wrapfloats_text,
    _float_sized,
    demote_wrapfloats,
    inject_float_sizing,
    inject_table_fitting,
)
from .marks import inject_layout_marks  # noqa: F401 — 同 C4 转引面
from .mainfile import (  # noqa: F401 — C4 出叶回引：find_main_tex/_walk_inputs 等公共+私名钉点面守恒
    _MAIN_TEX_SUFFIXES,
    _resolve_input,
    _walk_inputs,
    classify_no_main,
    find_main_tex,
)
from .mask import visible_tex
from .transcode import _iter_files

if TYPE_CHECKING:
    from pathlib import Path

#: zihao=false 必须钉死：ctex 默认 scheme=chinese 在未收到显式字号选项时
#: 强启 zihao=5（ctex-scheme-chinese.def），把 \normalsize..\tiny 全体重映射到
#: 中文字号 bp 尺寸（10pt→10.53937pt +5.4%），版式几何全面膨胀。
CTEX_LINE = r"\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}"

#: acmart.cls 类载时快照 ``\ACM@origbaselinestretch``（:3627）并
#: ``\AtEndDocument`` 用 ``\ifx`` 比对 ``\baselinestretch``——ctex 默认
#: scheme=chinese 在未显式传 linespread 时自补 ``\linespread{1.3}``
#: （ctex-scheme-chinese.def → ctex.sty:711），恰构成「重定义」触发
#: Class Error（soak-2026-09-18 zh-only 49 格，base 臂 0）。守卫自靶向：
#: 快照 cs 名唯 acmart 系定义，命中即把 ``\baselinestretch`` 归位快照义
#: ——类意本即禁改 stretch，比对恒真；非 acmart 档 ``\ifcsname`` 假空转。
#: 紧随 usepackage 行后：ctex 的 \linespread 在包载时执行，快照必先存在。
ACM_BASELINESTRETCH_GUARD = (
    "\n% texlate: acmart \\baselinestretch guard (ctex scheme=chinese \\linespread{1.3})\n"
    r"\ifcsname ACM@origbaselinestretch\endcsname"
    r"\expandafter\let\expandafter\baselinestretch"
    r"\csname ACM@origbaselinestretch\endcsname\fi"
)

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

#: ``_input_hop_inject`` 一跳 ``\input`` 目标数上界——病态工程的巨量
#: 声明不拖死探测；正常 preamble 分拆远在此界内。
_INPUT_HOP_CAP = 64


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


def _sentinel_wrap(block: str, sentinel: str, *, what: str) -> str:
    r"""多缝/多锚幂等哨兵包裹：活臂执行立 ``\def\<sentinel>{1}`` 哨，余点整块跳过。

    ``\fi`` 配对安全前提：被包块内 ``\if`` 全成对（skip 计数平衡）。
    ``_seams._splice_before_document`` 的 multi-bd 包裹同构——本助手是
    docclass 多缝侧的对应件（layout ``_float_sized`` 同款手写点收编位）。
    """
    return (
        f"% texlate: {what} (multi-seam idempotent)\n"
        f"\\ifdefined\\{sentinel}\\else\n"
        f"\\def\\{sentinel}{{1}}%\n" + block + "\\fi\n"
    )


def inject_cjk(  # noqa: C901 — ctex/xecjk 双模锚点分派+幂等校验平铺
    tex: str,
    *,
    mode: str = "ctex",
    root: Path | None = None,
    _defer_math_fallback: bool = False,
) -> tuple[str, dict]:
    r"""在主文件文本上注入中文支持。返回 `(new_text, info)`。

    mode `"ctex"`：`\documentclass` 行后插 `\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}`
    （hjfy 同款、双引擎实测 0% 破坏、白拿节名汉化；`zihao=false` 钉住防
    scheme=chinese 默认强启 zihao=5 把全文版式撑大 5.4%）。
    mode `"xecjk"`：同缝插 xeCJK+Fandol 块（ctex 冲突签名→fixloop/探针切换用）。

    `\documentstyle` → 先经 latex209.upgrade_209 升级转换（209 兼容模式内核层
    禁 `\usepackage`，注入前必须升级；`root` 提供工程树做随源 .sty 检测）。
    不可转形态（ds@ 选项机类）才抛 InjectRejectError，reason 注明机制。

    ``_defer_math_fallback``：``_input_hop_inject`` 一跳注入子文件时置位——
    ``CJK_MATH_FALLBACK`` 的 preamble 尾锚须落在编排 main 的 bd 前（子件
    缝位在组合 preamble 里只是中段），由调用方负责回填，本函数两处
    符号字体块落点全跳过。
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
    block = (
        CTEX_LINE + "  % [texlate injected]" + ACM_BASELINESTRETCH_GUARD
        if mode == "ctex"
        else XECJK_BLOCK
    )
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
    if not bd_in_main and not _defer_math_fallback:
        block += CJK_MATH_FALLBACK
    if len(hits) > 1:
        # 幂等哨兵：分支选择形态（\ifpdf A \else B \fi）逐缝注入，活臂的块
        # 执行后立哨；万一第二缝也执行（顺序双 \documentclass 坏档）整块
        # 跳过。\fi 配对安全：块内 \if 全成对（skip 计数平衡）。
        block = _sentinel_wrap(block, "TeXlateCJKloaded", what="CJK support")
    out = _splice_after_seams(tex, hits, block)
    if bd_in_main and not _defer_math_fallback:
        out = _splice_before_document(out, CJK_MATH_FALLBACK, after=hits[0][0])
    info: dict = {"status": "injected", "mode": mode, "line": lineno}
    if conv is not None:
        info["upgrade209"] = conv
    if len(hits) > 1:
        info["seams"] = len(hits)
    return out, info


def _input_hop_targets(
    root: Path, decl_dir: Path, main_vis: str, *, before: int | None
) -> list[tuple[Path, str, int]]:
    r"""字面 ``\input`` 一跳目标收集：``(子件路径, 解码文本, \input 位)``。

    遮盖视图上按文档序扫 input 族命中（``_walk_inputs`` 同口径），逐条
    ``_resolve_input`` 一跳解析（声明目录→工程根、``.tex``/``.ltx`` 补全、
    越根/伪装件拒）。``before`` 截断位 = main 首个 bd——bd 后 ``\input``
    是 body 件，dc 落此非 preamble 缝，不收。
    """
    hops: list[tuple[Path, str, int]] = []
    for m in sorted(
        (*INPUT_BRACED_RX.finditer(main_vis), *INPUT_BARE_RX.finditer(main_vis)),
        key=lambda x: x.start(),
    ):
        if (m.groupdict().get("verb") or "input") != "input":
            continue  # \include/\InputIfFileExists 目标非 preamble 载体
        if before is not None and m.start() > before:
            break  # 命中点按文档序——bd 后 \input 一律 body 件
        name = clean_decl_name(m["arg"])
        if name is None:
            continue
        tgt = _resolve_input(root, decl_dir, name)
        if tgt is None:
            continue
        try:
            blob = tgt.read_bytes()
        except OSError:
            continue
        if _tar_disguised(blob):
            continue  # _walk_inputs 同闸——伪装件字节非注入面
        hops.append((tgt, decode_tex(blob), m.start()))
        if len(hops) >= _INPUT_HOP_CAP:
            break
    return hops


def _input_hop_inject(
    root: Path, main_path: Path, main_text: str, *, mode: str
) -> tuple[str, dict] | None:
    r"""``\documentclass`` 藏在一跳 ``\input`` 子文件形态的二探注入。

    main 本体无 dc 缝（``no-docline``）时按文档序逐条字面 ``\input``
    目标做一跳解析（``_input_hop_targets`` 收集），首个带 dc 缝的子
    文件跑 ``inject_cjk`` 并写回；返回 ``(new_main_text, info)``，info
    加 ``input_hop`` 记携带者包内相对路径。无携带者 → ``None``（调用方
    维持 ``no-docline`` 票面）。

    字面参 only——宏实参/条件臂不解析；``\include``/``\InputIfFileExists``
    目标非 preamble 载体不收。一跳面任一文件已带 CJK 支持则整树记
    ``already``——per-文件 already 判定盖不到兄弟件，先注入再撞兄弟
    ctex = option clash。main 有 bd 时 ``CJK_MATH_FALLBACK`` 不下进子件
    而挪到 main 的 bd 前：mathgroup 余号语义要求 preamble 尾锚，子件
    缝位在组合 preamble 里只是中段（W157-W161 机理）。
    """
    # 归一到绝对帧：``_resolve_input`` 产物是 safe_resolve 绝对路径，相对
    # root 喂进 ``is_relative_to`` 恒假→零跳静默维持 no-docline——豆腐路
    # 原位复发，不能靠调用方自觉传绝对路径。
    rroot = safe_resolve(root)
    mpath = safe_resolve(main_path)
    if rroot is None or mpath is None:
        return None
    root, main_path = rroot, mpath
    main_vis = visible_tex(main_text)
    bd_positions = [m.start() for m in iter_depth0(BEGIN_DOC_RX, main_vis)]
    first_bd = min(bd_positions) if bd_positions else None
    hops = _input_hop_targets(root, main_path.parent, main_vis, before=first_bd)
    if not hops:
        return None
    for tgt, sub, _ipos in hops:
        if CJK_PRESENT_RE.search(visible_tex(sub)):
            return main_text, {
                "status": "already",
                "input_hop": tgt.relative_to(root).as_posix(),
            }
    for tgt, sub, ipos in hops:
        defer = first_bd is not None
        new_sub, sinfo = inject_cjk(
            sub, mode=mode, root=root, _defer_math_fallback=defer
        )
        if sinfo.get("status") == "no-docline":
            continue
        sinfo["input_hop"] = tgt.relative_to(root).as_posix()
        if sinfo["status"] != "injected":  # 防御——already 预扫已挡
            return main_text, sinfo
        tgt.write_text(new_sub, encoding="utf-8")
        if defer:
            main_text = _splice_before_document(
                main_text, CJK_MATH_FALLBACK, after=ipos
            )
            sinfo["math_fallback"] = "main-bd"
        return main_text, sinfo
    return None


def _project_uses(root: Path, needle: str) -> bool:
    r"""工程树任一主后缀 tex 源遮盖视图含 ``needle`` → True（树级特性闸）。

    ``demote_wrapfloats``/``inject_float_sizing`` 同款 ``_iter_files`` 全树
    口径——threeparttable 等活在 ``\input`` 子件里的用法不该因子件不在
    main 文本面而漏钩子（软链/隐藏目录豁免随 walker 自带）。
    """
    for path in _iter_files(root, _MAIN_TEX_SUFFIXES):
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        if _tar_disguised(blob):
            continue
        if needle in visible_tex(decode_tex(blob)):
            return True
    return False


def _table_fitting(tex: str) -> str:
    r"""单文件 TABLE_FITTING 注入：``_float_sized`` 同构——bd 优先，无 bd 落 dc 缝。

    ``inject_table_fitting`` 只走 ``_splice_before_document``——bd 不在档
    （编排壳 main，bd 藏 ``\input`` 子件）时静默不落。本助手补 docclass
    缝 fallback：有 bd 走 bd 前锚（原 ``inject_table_fitting`` 口径），
    无 bd 有 dc 缝走缝后锚（多缝 ``_sentinel_wrap`` 幂等），两无原样返回。
    """
    vis = visible_tex(tex)
    if TABLE_FITTING.strip() in tex or not DOCCLASS_RX.search(vis):
        return tex
    if next(iter_depth0(BEGIN_DOC_RX, vis), None) is not None:
        return _splice_before_document(tex, TABLE_FITTING, sentinel="TeXlateTableFit")
    hits = find_docclass_ends(tex)
    if not hits:
        return tex
    block = TABLE_FITTING
    if len(hits) > 1:
        block = _sentinel_wrap(block, "TeXlateTableFit", what="table fitting")
    return _splice_after_seams(tex, hits, block)


def _fit_table_hook(root: Path, main_text: str, hop: str | None) -> str:
    r"""TABLE_FITTING 落点编排：main 先尝，main 无锚则落 ``input_hop`` 携带子件。

    编排壳形态（main 无 dc/bd，``inject_cjk`` 经一跳落在 hop 子件）下
    preamble 载体是子件——钩子的 ``\usepackage{adjustbox}``/``AddToHook``
    必须进组合 preamble，写 main 无效。返回（可能改写的）main 文本；
    子件命中时原地写回。hop 为 root 相对 posix（``info["input_hop"]``）。
    """
    new_text = _table_fitting(main_text)
    if new_text != main_text or TABLE_FITTING.strip() in main_text or hop is None:
        return new_text  # 已落 / 已在档 / 无携带者可落
    tgt = safe_resolve(root / hop)
    if tgt is None or not tgt.is_relative_to(root) or not tgt.is_file():
        return new_text
    try:
        blob = tgt.read_bytes()
    except OSError:
        return new_text
    if _tar_disguised(blob):
        return new_text
    sub = decode_tex(blob)
    new_sub = _table_fitting(sub)
    if new_sub != sub:
        # 子件不可写不阻断——钩子缺失只是溢宽不兜
        with contextlib.suppress(OSError):
            tgt.write_text(new_sub, encoding="utf-8")
    return new_text


def prepare_chinese(
    root: Path,
    main: Path | str,
    *,
    mode: str = "ctex",
    float_sizing: bool = True,
    demote_wrap: bool = True,
    layout_marks: bool = False,
) -> dict:
    r"""工程级中文注入编排：ctex/xeCJK 注入 + 浮体钩子 + wrapfloat 降级。

    主文件 ctex/xeCJK + 按需 FLOAT_SIZING/TABLE_FITTING；全树 wrapfloat
    降级为普通浮体（``demote_wrap=False`` 时跳过）。

    返回注入报告 dict（注入缝行号/模式/已存在标记/wrapfloats_demoted）。
    `\documentstyle` 工程抛 InjectRejectError——调用方应记
    ``inject_reject:<reason>`` 类 reject（与 route reject 分流），而非
    编译失败。
    """
    main_path = root / main if isinstance(main, str) else main
    blob = main_path.read_bytes()
    if _tar_disguised(blob):
        # 兜底闸：find_main_tex 已排除 tar 候选，本层挡绕开检出直传的
        # 伪装 main——latin-1 解出的成员文本可含 dc 缝，注入写回即腐蚀。
        raise InjectRejectError(reason="nontex")
    text = decode_tex(blob)
    new_text, info = inject_cjk(text, mode=mode, root=root)
    if info.get("status") == "no-docline":
        # \documentclass 藏一跳 \input 子件形态（soak-2026-09-18 两格实证：
        # 2609.19979 MK2.tex→preambule.tex、2609.20454 arxiv.tex→preamble.tex
        # ——本体零缝照出 0 中文字节豆腐 pdf）。
        hop = _input_hop_inject(root, main_path, text, mode=mode)
        if hop is not None:
            new_text, info = hop
    if _project_uses(root, "threeparttable"):
        # 已带 CJK 的工程（status=already）同样要 threeparttable 溢宽钩子；
        # 树级闸——用法在 \input 子件里的工程也兜；bd 藏 hop 子件时钩子
        # 经 _fit_table_hook 落携带者。
        new_text = _fit_table_hook(root, new_text, info.get("input_hop"))
    if new_text != text:
        main_path.write_text(new_text, encoding="utf-8")
    if demote_wrap:
        info["wrapfloats_demoted"] = demote_wrapfloats(root)
    if float_sizing:
        info["float_sizing"] = inject_float_sizing(root)
    if layout_marks:
        # 末位注入：marks 钩子面要在 FLOAT_SIZING 对 ``\@endfloatbox``
        # 的补丁就位之后再注册，读到的才是手术后尺寸。
        info["layout_marks"] = inject_layout_marks(root)
    return info
