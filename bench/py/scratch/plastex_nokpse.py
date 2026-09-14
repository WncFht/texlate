"""Test: block real .sty/.cls loading entirely via kpsewhich monkeypatch."""

import sys, time, signal

sys.setrecursionlimit(20000)
from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging

disableLogging()


# 阻断一切真实文件查找 → \usepackage/\documentclass 走 Python 包或 UnrecognizedMacro
def no_kpse(self, name):
    raise FileNotFoundError("blocked: %s" % name)


TeX.kpsewhich = no_kpse

FILES = [
    "corpus/2203.02155/neurips_2021.tex",
    "corpus/1706.03762/ms.tex",
    "corpus/2305.14335/main.tex",
    "corpus/1810.04805/main.tex",
    "corpus/1511.06432/iclr2016_conference.tex",
    "corpus/1906.08237/neurips_2019.tex",
    "corpus/1906.08237/custom.tex",
    "corpus/2106.09685/iclr2022_conference.tex",
    "corpus/1512.03385/residual_v1_arxiv_release.tex",
    "corpus/2501.14787/main.tex",
    "corpus/2501.14787/lectures/10-CalculusofVariations.tex",
    "corpus/hep-th/9901001/imamura2.tex",
    "fixtures/tricky.tex",
]
ROOT = "/Users/fanghaotian/src/texlate/bench"
import os


class TO(Exception):
    pass


def h(s, f):
    raise TO()


signal.signal(signal.SIGALRM, h)

for f in FILES:
    path = os.path.join(ROOT, f)
    tex = TeX()
    t0 = time.time()
    signal.alarm(60)
    try:
        tex.input(open(path, encoding="utf-8", errors="replace"))
        doc = tex.parse()
        n = [0]

        def w(x):
            for c in getattr(x, "childNodes", []) or []:
                n[0] += 1
                w(c)

        w(doc)
        print(
            "%-50s OK %6.1fs nodes=%d text=%d"
            % (f, time.time() - t0, n[0], len(doc.textContent or ""))
        )
    except TO:
        print("%-50s TIMEOUT 60s" % f)
    except Exception as e:
        print(
            "%-50s FAIL %5.1fs %s %s"
            % (f, time.time() - t0, type(e).__name__, str(e)[:90])
        )
    finally:
        signal.alarm(0)
    sys.stdout.flush()
