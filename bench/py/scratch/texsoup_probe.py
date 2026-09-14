"""Minimal repro probes for TexSoup findings."""

import TexSoup
from TexSoup.utils import TC
from TexSoup.data import TexText

cases = {
    "verb-oneline-%": "\\begin{verbatim}100% real\\end{verbatim}",
    "verb-multiline-%": "\\begin{verbatim}\n100% real\n\\end{verbatim}",
    "lst-oneline-%": "\\begin{lstlisting}x%y\\end{lstlisting}",
    "comment-%": "text %% commented \\section{X} more%\nnext line",
    "comment-brace": "text % { unbalanced\nreal",
    "url-%": "\\url{http://x/a%20b}",
}

for name, src in cases.items():
    try:
        soup = TexSoup.TexSoup(src)
        print("%-18s OK   -> %r" % (name, str(soup)[:90]))
        for n in soup.descendants:
            toks = getattr(n.expr, "_contents", None)
            cat = getattr(toks[0], "category", None) if toks else None
            print(
                "     node %-30r kind=%s cat=%s"
                % (str(n)[:40], type(n.expr).__name__, cat)
            )
    except Exception as e:
        print("%-18s FAIL -> %s: %s" % (name, type(e).__name__, str(e)[:110]))

# tolerance=1 on failing cases
for name, src in cases.items():
    try:
        soup = TexSoup.TexSoup(src, tolerance=1)
        print("t1 %-15s OK -> %r" % (name, str(soup)[:90]))
    except Exception as e:
        print("t1 %-15s FAIL %s" % (name, str(e)[:80]))
