"""Inspect plasTeX DOM structure on real + fixture docs."""
import sys, time
sys.setrecursionlimit(10000)
from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging
from plasTeX.DOM import Node
disableLogging()

def count_nodes(doc):
    n = [0]
    def w(x):
        for c in x.childNodes:
            n[0] += 1
            w(c)
    w(doc)
    return n[0]

def tag_counts(doc):
    from collections import Counter
    c = Counter()
    def w(x):
        for ch in x.childNodes:
            c[getattr(ch, 'nodeName', getattr(ch, 'tagName', type(ch).__name__))] += 1
            w(ch)
    w(doc)
    return c

src = r'''\documentclass{article}
\usepackage{amsmath,amssymb}
\newcommand{\be}{\begin{equation}}
\newcommand{\ee}{\end{equation}}
\def\wt{\widetilde}
\newcommand{\dR}{\mathbb{R}}
\begin{document}
\section[Short]{Long Title Here}
Text with \citep{key1} and \emph{emphasized} and \dR{} in text.
\be \wt{A} = \Tr(M^2) \ee
Inline $x \in \dR$ math and \[ y = 2 \] display.
\ifnum 1 < 2 YES\else NO\fi
\end{document}'''

tex = TeX()
tex.input(src)
t0 = time.time()
doc = tex.parse()
print('parsed %.2fs, total nodes=%d' % (time.time()-t0, count_nodes(doc)))
c = tag_counts(doc)
print('top tags:', c.most_common(15))
eqs = doc.getElementsByTagName('equation')
print('equations:', len(eqs))
if eqs:
    print('  eq source:', repr(eqs[0].source[:80]))
    print('  eq textContent:', repr(eqs[0].textContent[:80]))
# is \wt expanded inside equation?
print('widetilde nodes:', len(doc.getElementsByTagName('widetilde')))
print('mathbb nodes:', len(doc.getElementsByTagName('mathbb')))
print('citep nodes:', len(doc.getElementsByTagName('citep')))
print('document textContent:', repr(doc.textContent[:400]))
