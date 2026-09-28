% texlate vendored stub — 原许可禁分发，最小兼容面
% aastex63.cls 替身：AAS TeX v6.3 (© AAS，不在 TL) → emulateapj +
% 6x 宏面 polyfill。自 shim_map aastex63.cls 条迁移 (aastex6x_body
% verbatim; 2208.00022 missing_cls 实证, \facilities/\software/
% track-changes 调用面)。emulateapj.cls 缺位由通用 missing_file
% →install_file(order 10) ctan_fetch 补 —— 与 yaml needs 同链。
% 不链 vendored aastex62 真件：其底 revtex4-1/4-2 在本机内核
% preamble \author 即炸 \collaboration@sw Undefined (smoke 实证),
% emulateapj 链是 yaml 侧既有实证活路。
% 本 stub 在场则 shim_map aastex63.cls 条成死配置（vendored 预检
% 先于 missing_file 落件，同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{aastex63}[2026/09/28 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{aastex63.cls is a compatibility shim -> emulateapj + 6x polyfills}
% emulateapj5 自指递归保险 —— ver@/opt@ 预注册 (85-shim aastex
% bundle-shadow 条同款)
\expandafter\def\csname ver@emulateapj5.sty\endcsname{2026/09/17}
\expandafter\def\csname opt@emulateapj5.sty\endcsname{twocolumn,onecolumn}
\LoadClassWithOptions{emulateapj}
\providecommand{\received}[1]{}
\providecommand{\revised}[1]{}
\providecommand{\accepted}[1]{}
\providecommand{\published}[1]{}
\providecommand{\submitjournal}[1]{}
\providecommand{\correspondingauthor}[1]{}
% emulateapj 实测无 \email —— provide+renew 双写 = 无条件占位;
% \collaboration 原生实现依赖 revtex 内部件 (未武装会炸) ——
% 同样覆盖成确定性版式
\providecommand{\email}[1]{}
\renewcommand{\email}[1]{}
\providecommand{\collaboration}[2]{#2}
\renewcommand{\collaboration}[2]{#2}
% \keywords 在 emulateapj 受 showkeys 选项门控 —— 覆盖成确定性版式
\providecommand{\keywords}[1]{}
\renewcommand{\keywords}[1]{\par\noindent\textbf{Keywords:} #1\par}
% emulateapj \url→\anchor 原样排印参数 —— footnote 等已冻结参数内
% catcode-8 `_`/`^`/`&` 炸 Missing $ (2105.03750 实证)。轻量等价:
% \detokenize 回收成 catcode-12 文本再 \texttt 排印。签名兼容
% emulateapj \@dblarg 形: \url{X} 与 \url[anchor]{X} 都排 X
\renewcommand{\url}[2][]{\texttt{\detokenize{#2}}}
% \nolinkurl 同面 (2104.00028): hyperref-only cs, shim 语境恒无
% hyperref → 委托 shim \url 继承 detokenize 保护; provide 形让位
% 稿后装真 hyperref
\providecommand{\nolinkurl}[1]{\url{#1}}
\providecommand{\nocollaboration}[1]{}
\providecommand{\facilities}[1]{\par\noindent\textbf{Facilities:} #1\par}
\providecommand{\software}[1]{\par\noindent\textbf{Software:} #1\par}
% aastex6x \startlongtable 把 deluxetable 拉成长表; emulateapj 的
% deluxetable 本就是 longtable 实现 —— no-op 语义一致
\providecommand{\startlongtable}{}
\@ifundefined{endlongtable}{\@namedef{endlongtable}{}}{}
\providecommand{\watermark}[1]{}
% --- aastex63x/AASTeX62 实侧补面 (真件 aastex631.cls 抄签名) ---
% \altaffiliation 在 emulateapj 有原生 revtex 定义 → provide 让位
\providecommand{\altaffiliation}[2][]{}
\providecommand{\allauthors}{}
\providecommand{\setwatermarkfontsize}[1]{}
% track-changes 族 (真件 \@ifnextchar 可选参形): \added[why]{new}
% 印新, \deleted[why]{old} 吞旧, \replaced[why]{old}{new} 印新;
% \listofchanges 无参; \AuthorCollaborationLimit 是 \newcount
% 寄存器 (稿侧 \AuthorCollaborationLimit=N 赋值)
\providecommand{\added}[2][]{#2}
\providecommand{\deleted}[2][]{}
\providecommand{\replaced}[3][]{#3}
\providecommand{\listofchanges}{}
\@ifundefined{AuthorCollaborationLimit}{\newcount\AuthorCollaborationLimit\AuthorCollaborationLimit=10000\relax}{}
% \lesssim/\gtrsim: emulateapj 传递装 amssymb → provide 平时让位;
% 无 amssymb 路径兜底画符 (rlap <∽ 叠加)
\providecommand{\lesssim}{\mathrel{\hbox{\rlap{\raisebox{-.4ex}{$<$}}\raisebox{.4ex}{$\sim$}}}}
\providecommand{\gtrsim}{\mathrel{\hbox{\rlap{\raisebox{-.4ex}{$>$}}\raisebox{.4ex}{$\sim$}}}}
% env 三件: widetext 跨栏块 → 横线包围段; ruledtabular → tabular
% 直通; contribution → 无号小节。全 \@ifundefined 守卫
\@ifundefined{widetext}{\newenvironment{widetext}{\par\hrule\nobreak}{\par\nobreak\hrule\par}}{}
\@ifundefined{ruledtabular}{\newenvironment{ruledtabular}{\tabular}{\endtabular}}{}
\@ifundefined{contribution}{\newenvironment{contribution}{\par\noindent\textbf{Author contributions:}\space}{\par}}{}
\providecommand{\rotate}{}
\endinput
