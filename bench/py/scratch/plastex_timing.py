"""Time plasTeX on a few representative corpus files."""

import sys, time, signal

sys.setrecursionlimit(10000)
from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging

disableLogging()

FILES = [
    "corpus/1706.03762/background.tex",  # 无 documentclass 的章节文件
    "corpus/1706.03762/ms.tex",  # NIPS 主文件
    "corpus/2305.14335/main.tex",  # IEEEtran
    "corpus/hep-th/9901001/imamura2.tex",  # LaTeX 2.09
    "corpus/2501.14787/lectures/01-Overview.tex",
    "corpus/1810.04805/abstract.tex",
]
import os

ROOT = "/Users/fanghaotian/src/texlate/bench"


class TO(Exception):
    pass


def h(s, f):
    raise TO()


signal.signal(signal.SIGALRM, h)

for f in FILES:
    path = os.path.join(ROOT, f)
    tex = TeX()
    t0 = time.time()
    signal.alarm(30)
    try:
        tex.input(open(path, encoding="utf-8", errors="replace"))
        doc = tex.parse()
        dt = time.time() - t0
        n = (
            len(doc.getElementsByTagName("*"))
            if hasattr(doc, "getElementsByTagName")
            else -1
        )
        print("%-52s OK %6.2fs nodes~%d" % (f, dt, n))
    except TO:
        print("%-52s TIMEOUT(30s)" % f)
    except Exception as e:
        print(
            "%-52s FAIL %5.2fs %s %s"
            % (f, time.time() - t0, type(e).__name__, str(e)[:90])
        )
    finally:
        signal.alarm(0)
    sys.stdout.flush()
