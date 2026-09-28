% texlate vendored stub — 原许可禁分发，最小兼容面
% appolb.cls 替身：Acta Physica Polonica B 类 (© Jagiellonian
% Univ.，不在 TL) → article + appolb frontmatter 面。自 shim_map
% appolb.cls 条迁移 (1312.0559 missing_cls_crash 实证; 真件签名
% 2410.17921 抄值): \eqsec 开 equation 按 section 编号 (真件
% verbatim 减 \eq@sec 内部 flag); \address/\PACS 即时打印块;
% \Tr = mathop{\operator@font Tr} → {\rm Tr} 兜底 (无 amsopn);
% \preprint/\runhead 存值件 noop。
% 本 stub 在场则 shim_map appolb.cls 条成死配置（vendored 预检
% 先于 missing_file 落件，同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{appolb}[2026/09/28 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{appolb.cls is a compatibility shim -> article + appolb polyfills}
\LoadClassWithOptions{article}
\providecommand{\eqsec}{\def\theequation{\thesection.\@arabic\c@equation}\@addtoreset{equation}{section}}
\providecommand{\address}[1]{\par\vspace*{6pt}\noindent{\small\rmfamily #1}\par}
\providecommand{\PACS}[1]{\par\noindent\strut\kern18pt{\footnotesize\rmfamily PACS numbers: #1}\par}
\providecommand{\Tr}{\mathop{\rm Tr}\nolimits}
\providecommand{\preprint}[1]{}
\providecommand{\runhead}[1]{}
\endinput
