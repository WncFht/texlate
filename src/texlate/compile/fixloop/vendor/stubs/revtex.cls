% texlate vendored stub — 原许可禁分发，最小兼容面
% revtex.cls 替身：REVTeX 3.x 老类名（© APS，不在 TL——TL 只存 revtex4-2）。
% 自 shim_map revtex.cls 条迁移（13 格实证簇残面：\twocolumn/\@makecol 被
% revtex4-2 \let\@undefined 故回排式 polyfill；\pacs 后置 \maketitle 炸
% ClassError 故 begin-doc 起直印）。
% 两态分派（loop2 167 格 base 臂 missing_file revtex.cls 全量实证）：
% - \documentstyle{revtex} compat 调用：revtex4-2 硬拒 compat mode
%   (cls 内 \@compatibility 检查 ! You cannot run revtex4-2 in
%   compatability mode) → 桥 article + 2.09 revtex 残面；documentstyle
%   选项经 latex209 \@documentclasshook 按 \@unusedoptionlist 逐名
%   \RequirePackage，revtex 随件 style 名 (aps/prl/preprint/floats/
%   tighten/onecolumn/multicol2) 无对应 .sty 必炸 missing_file → 剔除；
%   真 TL 名 (epsfig/epsf/multicol/amssymb/tabularx/manuscript...) 与
%   vendored 名 (eqsecnum/psfig) 放行正常解析。
% - \documentclass{revtex} 2e 直调：桥 revtex4-2（zh 臂 2.09 稿由
%   normalize/latex209 改写层直转 revtex4-2，不吃本 stub）。
% 本 stub 在场则 shim_map revtex.cls 条成死配置（vendored 预检先于
% missing_file 落件，同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{revtex}[2026/09/19 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{revtex.cls is a compatibility shim}
\if@compatibility
  \DeclareOption*{}\ProcessOptions\relax
  \LoadClassWithOptions{article}
  % 剔除 revtex 2.09 随件 style 名——latex209 hook 会把未消费选项当
  % .sty 逐名 \RequirePackage，这些名无对应文件（prd.sty 实证炸点）
  \def\revtex@drop{,aps,prl,prb,prd,pra,prc,pre,prx,rmp,preprint,tighten,floats,onecolumn,multicol2,}
  \def\revtex@keep{}
  \@for\revtex@o:=\@unusedoptionlist\do{%
    \@expandtwoargs\in@{,\revtex@o,}{\revtex@drop}%
    \ifin@\else
      \ifx\revtex@keep\@empty\edef\revtex@keep{\revtex@o}%
      \else\edef\revtex@keep{\revtex@keep,\revtex@o}\fi
    \fi}
  \let\@unusedoptionlist\revtex@keep
  % 2.09 revtex 残面（167 稿面扫实证）：\address×155 \pacs×104 \draft×97
  % \narrowtext×38 \widetext×19 \preprint×28 \tightenlines×19 \tighten×17
  \providecommand{\address}[1]{\par{\itshape#1\par}}
  \providecommand{\andaddress}[1]{\par{\itshape#1\par}}
  \providecommand{\pacs}[1]{\par\noindent\textbf{PACS:} #1\par}
  \providecommand{\preprint}[1]{}
  \providecommand{\draft}{}
  \providecommand{\tighten}{}
  \providecommand{\tightenlines}{}
  \providecommand{\widetext}{}
  \providecommand{\narrowtext}{}
  \providecommand{\submit}[1]{}
\else
  \LoadClassWithOptions{revtex4-2}
  % frontmatter 机器提前武装 (同 prl/apl/revtex4 先例)
  \frontmatter@init
  \let\frontmatter@init\relax
  % revtex4-2 故意 \let\twocolumn\@undefined; 2.09 稿
  % \twocolumn[frontmatter块] 需回排式 polyfill —— 直接吐内容
  % (noop 吞参会丢整页 frontmatter)
  \providecommand{\twocolumn}[1][]{#1}
  % \@makecol 同被删 (revtex3 output routine 内件); 回退
  % 最简内核语义 (box 回写, 丢 float/footnote 处理但保编译)
  \@ifundefined{@makecol}{\def\@makecol{\setbox\@outputbox\vbox{\unvbox\@cclv}}}{}
  % \pacs 全期容忍: revtex4-2 版在 \maketitle 后调 → ClassError
  % (revtex_pacs 5 格实证)。begin-doc 起改直印 —— 前置调用失去
  % frontmatter 注册但文本可见且不炸 (2.09 老稿多后置)。
  % \long: 老稿 \pacs 实参可含空行/\and 分段 (真 revtex 收段落级
  % 内容), 非 \long 遇 \par 炸 "Paragraph ended before \pacs"。
  \long\def\revtex@pacsflat#1{\par\noindent\textbf{PACS:} #1\par}
  \AtBeginDocument{\let\pacs\revtex@pacsflat}
\fi
\endinput
