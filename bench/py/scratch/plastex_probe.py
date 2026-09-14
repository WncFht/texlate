"""Probe plasTeX behavior on individual tricky constructs."""
import sys, time
from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging
disableLogging()

CASES = {
 'natbib': r'''\documentclass{article}
usepackage{natbib}
\begin{document}See \citep{a} and \citet[see][chap.~2]{b}, \citealp{c}, \citeauthor{d}, \citeyear{e}, \ref{f}, \eqref{g}, \autoref{h}, \cref{i}, \pageref{j}, \nameref{k}, \label{l}.\end{document}''',
 'natbib2': r'''\documentclass{article}
\usepackage{natbib}
\begin{document}See \citep{a} and \citet[see][chap.~2]{b}, \citealp{c}, \citeauthor{d}, \citeyear{e}, \ref{f}, \eqref{g}, \autoref{h}, \cref{i}, \pageref{j}, \nameref{k}, \label{l}.\end{document}''',
 'url-verb': r'''\documentclass{article}
\usepackage{hyperref}
\begin{document}\url{http://example.com/a%20b.pdf} \verb|a%b| \href{https://x.com}{doc}\end{document}''',
 'verbatim': "\\documentclass{article}\n\\usepackage{listings}\n\\begin{document}\n\\begin{verbatim}100% real\\end{verbatim}\n\\begin{lstlisting}\ncode%with%percent\n\\end{lstlisting}\n\\end{document}",
 'algos': r'''\documentclass{article}
\usepackage{algorithm,algpseudocode,subcaption,graphicx,amsmath,amssymb,amsthm}
\begin{document}text\end{document}''',
 'xparse-only': r'''\documentclass{article}
\usepackage{xparse}
\begin{document}text\end{document}''',
 'xparse-def': r'''\documentclass{article}
\usepackage{xparse}
\NewDocumentCommand{\vect}{m}{\mathbf{#1}}
\begin{document}v $\vect{v}$\end{document}''',
 'newthm': r'''\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}\begin{theorem}[Main Result]
For all $n>0$, the statement holds.
\end{theorem}\end{document}''',
 'subeq': r'''\documentclass{article}
\usepackage{amsmath}
\begin{document}
\begin{subequations}
\begin{align}
a &= b + c \\
d &= e + f
\end{align}
\end{subequations}
\begin{flalign}
x &= y
\end{flalign}
\end{document}''',
 'be-full': r'''\documentclass{article}
\usepackage{amsmath,amssymb}
\newcommand{\be}{\begin{equation}}
\newcommand{\ee}{\end{equation}}
\def\wt{\widetilde}
\def\Tr{\mathop{\rm Tr}\nolimits}
\newcommand{\dR}{\mathbb{R}}
\begin{document}
The key result is
\be \wt{A} = \Tr(M^2) \ee
which uses \dR{} inside text too.
\end{document}''',
 'makeatletter': r'''\documentclass{article}
\makeatletter
\newcommand{\secretmacro}{\@ifnextchar[{\@with}{\@without}}
\makeatother
\begin{document}text\end{document}''',
 'ifdraft': r'''\documentclass{article}
\newif\ifdraft
\drafttrue
\begin{document}
\ifdraft
Draft mode paragraph that still contains translatable text.
\else
Final mode paragraph.
\fi
\end{document}''',
 'input-multi': None,  # handled separately
}

for name, src in CASES.items():
    if src is None:
        continue
    tex = TeX()
    tex.input(src)
    t0 = time.time()
    try:
        doc = tex.parse()
        eqs = doc.getElementsByTagName('equation')
        print('%-14s OK %.2fs equations=%d' % (name, time.time()-t0, len(eqs)))
    except Exception as e:
        print('%-14s FAIL %.2fs: %s %s' % (name, time.time()-t0, type(e).__name__, str(e)[:150]))
    sys.stdout.flush()
