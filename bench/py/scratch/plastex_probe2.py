"""Probe plasTeX part 2: find the recursion culprit in tricky.tex."""
import sys, time
from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging
disableLogging()

CASES = {
 'title-author': r'''\documentclass{article}
\title{A Tricky Test \thanks{supported by nobody}}
\author[1]{Alice Smith\thanks{alice@x.org} \and Bob Jones}
\date{\today}
\begin{document}\maketitle text\end{document}''',
 'figure-cap': r'''\documentclass{article}
\usepackage{graphicx}
\begin{document}
\begin{figure}[ht]
\centering
\includegraphics[width=0.5\textwidth]{figs/plot.pdf}
\caption{A figure with \emph{emphasis} and math $x^2$.}
\label{fig:x}
\end{figure}
\end{document}''',
 'table-foot': r'''\documentclass{article}
\begin{document}
\begin{table}[h]
\caption{Results table\footnote{computed by hand}}
\begin{tabular}{|l|r|}
\hline
name & value \\ \hline
alpha & 0.1 \\
\end{tabular}
\end{table}
\end{document}''',
 'lists': r'''\documentclass{article}
\begin{document}
\begin{itemize}
\item First item with $x$ math.
\item Second item.
\end{itemize}
\begin{description}
\item[Term] Its definition here.
\end{description}
\end{document}''',
 'abstract': r'''\documentclass{article}
\newcommand{\dR}{\mathbb{R}}
\begin{document}
\begin{abstract}
We study tricky \LaTeX{} constructs. Results hold for $x \in \dR$.
\end{abstract}
\end{document}''',
 'comments': r'''\documentclass{article}
\begin{document}
Real text. % a comment with { unbalanced brace and $x^2$ math
Escaped \% percent stays. Line break \\% followed by real comment
\end{document}''',
 'accents': r'''\documentclass{article}
\begin{document}
Andr\'e, M\"uller, \~n, caf\'e — names should not break parsing.
$ f(x) = 0 \quad \text{if and only if} \quad x = 0 $
A claim.\footnote{This footnote text should be translated.}
\bibliographystyle{plainnat}
\bibliography{refs}
\end{document}''',
 'display-math': r'''\documentclass{article}
\begin{document}
The identity
\[ \int_0^1 f(x)\,\mathrm{d}x = F(1) - F(0) \]
and inline \( e^{i\pi} = -1 \) both protected.
\end{document}''',
 'algorithm': r'''\documentclass{article}
\usepackage{algorithm}
\begin{document}text\end{document}''',
 'algpseudocode': r'''\documentclass{article}
\usepackage{algpseudocode}
\begin{document}text\end{document}''',
 'subcaption': r'''\documentclass{article}
\usepackage{subcaption}
\begin{document}text\end{document}''',
 'graphicx': r'''\documentclass{article}
\usepackage{graphicx}
\begin{document}text\end{document}''',
 'hyperref': r'''\documentclass{article}
\usepackage{hyperref}
\begin{document}text\end{document}''',
 'listings': "\\documentclass{article}\n\\usepackage{listings}\n\\begin{document}text\\end{document}",
 'amssymb': r'''\documentclass{article}
\usepackage{amssymb}
\begin{document}text\end{document}''',
}

for name, src in CASES.items():
    tex = TeX()
    tex.input(src)
    t0 = time.time()
    try:
        doc = tex.parse()
        print('%-14s OK %.2fs' % (name, time.time()-t0))
    except Exception as e:
        print('%-14s FAIL %.2fs: %s %s' % (name, time.time()-t0, type(e).__name__, str(e)[:120]))
    sys.stdout.flush()
