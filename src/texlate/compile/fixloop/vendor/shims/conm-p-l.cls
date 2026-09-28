% texlate vendored stub — 原许可禁分发，最小兼容面
% conm-p-l.cls 替身：ACM 90s 会议 preprint 版式 (© ACM，不在 TL)
% → acmart 官方继任类。自 shim_map conm-p-l.cls 条迁移：
% 1003.0067 实证 acmart→unicode-math 装载后 \Psi 类希腊字母变
% \mitPsi chardef —— 稿内 \section{...$\pdo$...} 在 hyperref
% \pdfstringdef (bookmark) 展开时 `` `\mitPsi `` 炸 "Improper
% alphabetic constant" + intcalc 级联 → \pdfstringdefDisableCommands
% 域内把 \pdo 降级成纯文本。
% 本 stub 在场则 shim_map conm-p-l.cls 条成死配置（vendored 预检
% 先于 missing_file 落件，同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{conm-p-l}[2026/09/28 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{conm-p-l.cls is a compatibility shim -> acmart}
\LoadClassWithOptions{acmart}
\AtBeginDocument{\@ifundefined{pdfstringdefDisableCommands}{}{%
  \pdfstringdefDisableCommands{\def\pdo{PsiDO}}}}
\endinput
