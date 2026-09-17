
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{acm_proc_article-sp}[2026/09/17 fixloop legacy shim -> acmart + author-block kit]
\LoadClassWithOptions{acmart}
% --- acm_proc_article-sp author-block family under acmart (1306.0281) ---
% \alignauthor is a column-starter (no arg, name runs to \\) — \par mirrors
% the old "new author column" break inside the single acmart \author{} arg.
\ifdefined\alignauthor\else\protected\def\alignauthor{\par}\fi
% \affaddr/\affinst{inst} sit loose inside \author{} — acmart \affiliation
% would corrupt \addresses there; inline emph keeps the text.
\ifdefined\affaddr\else\protected\def\affaddr#1{\emph{#1}}\fi
\ifdefined\affinst\else\protected\def\affinst#1{\emph{#1}}\fi
% \titlenote inside \author{} executes inside \MakeUppercase: acmart's
% native def appends \footnotemark to \@title -> \@xfootnotemark mismatch
% + Missing \endcsname storm (100 errs). Override is mandatory — \protected
% bridge to \thanks survives text_expand and lands in the \thankses strip.
\protected\def\titlenote#1{\thanks{#1}}
% \additionalauthors{names} top-level -> register as another acmart author.
\ifdefined\additionalauthors\else\protected\long\def\additionalauthors#1{\author{#1}}\fi
% \numberofauthors{N} — acmart auto-counts (cs_table polyfill also covers).
\ifdefined\numberofauthors\else\protected\def\numberofauthors#1{}\fi
% acmart has native \subtitle — guard only for exotic load paths.
\ifdefined\subtitle\else\protected\def\subtitle#1{}\fi
% Old acm_proc order puts abstract AFTER \maketitle; acmart \@saveabstract
% ClassErrors once \@ACM@maketitle@typeset. Conditional bridge: pre-maketitle
% keeps the native Collect@Body stash; post-maketitle typesets the body as a
% plain labelled block — NO Collect@Body on the late path (its body-scan
% hijacks \abstract and cannot tolerate a typesetting callback).
\renewenvironment{abstract}{\if@ACM@maketitle@typeset\par\medskip\noindent{\bfseries\abstractname.}\space\ignorespaces\else\Collect@Body\@saveabstract\fi}{\if@ACM@maketitle@typeset\par\medskip\fi}
% 2.09 font switches: acmart inherits \rm\sf\tt\bf\it\sl\sc from
% amsart (its \DeclareOldFontCommand block); only \cal/\mit are missing
% (amsart deliberately omits them) — doc \cA->{\cal A} family needs them.
\ifdefined\cal\else\DeclareOldFontCommand{\cal}{\normalfont\itshape}{\mathcal}\fi
\ifdefined\mit\else\DeclareOldFontCommand{\mit}{\normalfont\itshape}{\mathnormal}\fi
\endinput
