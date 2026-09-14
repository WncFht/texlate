"""Minimal round-trip repros for TexSoup."""

import TexSoup

cases = [
    r"{\tt [CLS]}",
    r"{\tt x}",
    r"a, 2016.",
    r"{\em arXiv}, 2016.",
    "\\newblock {\\em arXiv preprint arXiv:1607.06450}, 2016.",
    "\\texttt{aidan@cs.toronto.edu}\n  \\And",
    "{\\small\n\\begin{tabular}{c}x\\end{tabular}}",
    "{\\bf \\large{\n    Appendix}}",
    "\\resizebox{1.0}{\n\\begin{tabular}{c}x\\end{tabular}}",
    "min({step\\_num}^{-0.5},\n    {step\\_num})",
    "\\begin{figure*}[h]\n{\\includegraphics{x}}",
]

for src in cases:
    try:
        soup = TexSoup.TexSoup(src)
        out = str(soup)
        mark = "SAME" if out == src else "DIFF"
        print("%-4s %r -> %r" % (mark, src[:60], out[:60]))
    except Exception as e:
        print("FAIL %r: %s" % (src[:50], str(e)[:80]))
