% texlate vendored stub — 原许可禁分发，最小兼容面
% mn2e.cls 替身：MNRAS 老类名（© RAS，不在 TL——真身只在
% doc/latex/mnras/LEGACY/，2015 改名 mnras）→ 桥 mnras.cls。自 shim_map
% mn2e.cls 条迁移（1109.6007/1206.5620 双引擎 4 格实证），与
% vendor/stubs/mn.cls 同体例。usegraphicx 选项剔除：mnras.cls 的
% \ds@usegraphicx 在 Options Section 内 \usepackage 必炸，须从
% \@classoptionslist 剔除、类装完再补装 graphicx。
% 本 stub 在场则 shim_map mn2e.cls 条成死配置（vendored 预检先于 missing_file 落件，
% 同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{mn2e}[texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{mn2e.cls is a compatibility shim -> mnras}
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
