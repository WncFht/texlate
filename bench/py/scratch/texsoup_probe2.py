"""Find which node kind carries the %% comment text in iclr2016."""

import TexSoup
from TexSoup.utils import TC
from TexSoup.data import TexText, TexExpr

src = open(
    "/Users/fanghaotian/src/texlate/bench/corpus/1511.06432/iclr2016_conference.tex"
).read()
soup = TexSoup.TexSoup(src)

# walk expr tree manually; find expr whose str contains 'Preliminary Observation'
found = []


def walk(e, path):
    s = None
    for c in getattr(e, "contents", []) or []:
        if isinstance(c, TexExpr):
            walk(c, path + [type(e).__name__ + ":" + str(getattr(e, "name", ""))])
    for a in getattr(e, "args", []) or []:
        for c in getattr(a, "contents", []) or []:
            if isinstance(c, TexExpr):
                walk(
                    c,
                    path
                    + [type(e).__name__ + ":" + str(getattr(e, "name", "")) + "/arg"],
                )
    try:
        s = str(e)
    except Exception:
        return
    if "Preliminary Observation" in s and len(s) < 400:
        toks = getattr(e, "_contents", None)
        cat = getattr(toks[0], "category", None) if toks else None
        found.append((type(e).__name__, cat, " > ".join(path[-4:]), s[:120]))


for c in soup.expr.contents:
    if isinstance(c, TexExpr):
        walk(c, [])

for f in found[:10]:
    print(f)
print("total", len(found))

# Also: what does the node stream look like near a comment?
i = src.find("%% \\subsubsection{Preliminary")
print("src ctx:", repr(src[i - 60 : i + 200]))
