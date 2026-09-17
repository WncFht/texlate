% texlate vendored stub — 原许可禁分发，最小兼容面
% imsart.cls S1 替身：VTEX/IMS 直发、许可核不到 → stub。IMS 期刊
% class 骨架=article + frontmatter 系 cs/env 面。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{imsart}[texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{imsart.cls is a compatibility shim}

\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass[10pt]{article}

% —— IMS frontmatter 面 ——
\newenvironment{frontmatter}{}{}
\providecommand{\affiliation}[1]{\gdef\@affiliation{#1}}
\providecommand{\address}[1]{\gdef\@address{#1}}
\providecommand{\email}[1]{\gdef\@email{#1}}
\providecommand{\keyword}[1]{\gdef\@keywords{#1}}
\providecommand{\keywords}[1]{\keyword{#1}}
\providecommand{\amsclass}[1]{\gdef\@amsclass{#1}}
\providecommand{\received}[1]{}
\providecommand{\revised}[1]{}
\providecommand{\accepted}[1]{}
\providecommand{\publishedonline}[1]{}
\providecommand{\corresp}[1]{}
\providecommand{\thankstext}[2]{}
\providecommand{\dedication}[1]{}
\providecommand{\runtitle}[1]{\gdef\@runtitle{#1}}
\providecommand{\runauthor}[1]{\gdef\@runauthor{#1}}
\def\@runtitle{}\def\@runauthor{}\def\@affiliation{}\def\@address{}\def\@email{}\def\@keywords{}\def\@amsclass{}
\newenvironment{aug}{}{}
\endinput
