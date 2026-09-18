% texlate vendored stub — 原许可禁分发，最小兼容面
% mn.cls (MNRAS 1994-2002 老类) 语义替身：原件非 TL 收录、许可禁再分发
% → stub。等价面同 fixloop mn2e shim 先例：转接到 TL 收录的 mnras.cls
% (files/mnras.cls 随包兜底)。usegraphicx 选项剔除逻辑照 mn2e body —
% mnras.cls 的 \ds@usegraphicx 在 Options Section 内 \usepackage 必炸，
% 须从 \@classoptionslist 剔除、类装完再补装 graphicx。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{mn}[2026/09/18 texlate stub -> mnras; original not redistributable]
\PackageWarningNoLine{texlate-stub}{mn.cls is a compatibility shim -> mnras}
\newif\ifmn@graphicx
\DeclareOption*{}\ProcessOptions\relax
\def\mn@gx{usegraphicx}
\def\mn@clean{}
\@for\mn@o:=\@classoptionslist\do{%
  \ifx\mn@o\mn@gx \mn@graphicxtrue\else
    \ifx\mn@clean\@empty\edef\mn@clean{\mn@o}%
    \else\edef\mn@clean{\mn@clean,\mn@o}\fi
  \fi}
\let\@classoptionslist\mn@clean
\LoadClass{mnras}
\ifmn@graphicx\RequirePackage{graphicx}\fi
\endinput
