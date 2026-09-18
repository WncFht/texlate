% texlate vendored stub — 原许可禁分发，最小兼容面
% revtex.cls 替身：REVTeX 3.x 老类名（© APS，不在 TL——TL 只存 revtex4-2）
% → 桥 revtex4-2 + 2.09 残面 polyfill。自 shim_map revtex.cls 条迁移（13 格
% 实证簇残面：\twocolumn/\@makecol 被 revtex4-2 \let\@undefined 故回排式
% polyfill；\pacs 后置 \maketitle 炸 ClassError 故 begin-doc 起直印——
% shim 原件 \AtBeginDocument{\def\pacs##1} 的 ## 在新 hook token-list 存储
% 不塌缩、\begin{document} 期炸参数序，此处改 class 级宏 + \let 绑同款语义）。
% \documentstyle{revtex} 的 2.09 稿由 normalize/latex209 改写层直转
% revtex4-2，不吃本条；本 stub 管直写 \documentclass{revtex} 存量稿。
% 本 stub 在场则 shim_map revtex.cls 条成死配置（vendored 预检先于 missing_file 落件，
% 同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{revtex}[texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{revtex.cls is a compatibility shim -> revtex4-2}
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
\def\revtex@pacsflat#1{\par\noindent\textbf{PACS:} #1\par}
\AtBeginDocument{\let\pacs\revtex@pacsflat}
\endinput
