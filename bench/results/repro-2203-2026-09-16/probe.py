"""repro-2203.00092 pgffor 扫描错归因探针（只读 bench/src，不落盘改动）。

跑法：``uv run python bench/results/repro-2203-2026-09-16/probe.py``

机理链：
  1. gullet 把 ``\\makecommand{sf}{\\mathsf}{{CE,Ch,...}}`` 展开成
     ``\\foreach \\i in {CE,...} {\\xdef…}`` token 流（\\xdef 被 gullet
     执行成 consumed marker ``xdef:sf\\i``——surface 只剩 ``{}``）。
  2. segmenter 组内 surface 渲染把 cs ``\\i`` 与后续 letter ``i``/``n``
     直接拼接 → ``\\iin``（缺 cs→letter 空格守卫；同族先例见
     gullet._surface 的 ``\\text foo`` 注释）。修复在途：``_cat_surf``
     已把同款守卫铺满 _group_surface 全部 bare-append 位。
  3. chunk.content 携 ``\\foreach\\iin {…} {}`` 骨架 → 译文保骨架、
     list → 这是译文 → zh 文件 ``\\foreach\\iin {这是译文} {}`` →
     pgffor ``\\pgffor@var@add`` 扫 ``in`` 关键字 → 撞到空行/EOF →
     "File ended while scanning use of \\pgffor@var@add"（行中报在
     preprint.cls:163 = ``\\input{lib/commands.tex}``，即 characters.tex
     EOF 后父文件续行位——file:line 归因被导去父文件，L2 因此只回退了
     行中两处 blob、漏掉末行这颗）。
"""

from texlate.latex.api import parse_file
from texlate.latex.gullet import Gullet, _surface
from texlate.latex.reconstruct import reconstruct

PAPER = "bench/work_e2emock/corpus_v3/base-xel/2203.00092"
CHARS = f"{PAPER}/lib/characters.tex"


def main() -> None:
    src = open(CHARS).read()
    res = parse_file(CHARS, flatten=False)
    print("== chunk dump ==")
    for c in res.chunks:
        print(f"span=({c.span.start},{c.span.end}) ctx={c.context}")
        print("  content:", repr(c.content)[:200])
        print("  src    :", repr(src[c.span.start : c.span.end])[:200])
    print("identity:", reconstruct(res) == src)

    g = Gullet()
    g.push_source(src, "characters.tex")
    toks = []
    while (t := g.next_expanded()) is not None:
        toks.append(t)
    i = max(k for k, t in enumerate(toks) if t.kind == "cs" and t.text == "foreach")
    seg = toks[i : i + 9]
    print("== expansion head of last \\makecommand call ==")
    for t in seg:
        print(" ", t.kind, repr(t.text), "gen", t.gen)
    j = max(
        k for k, t in enumerate(toks) if t.kind == "consumed" and t.text.startswith("xdef")
    )
    print("consumed marker:", repr(toks[j].text))
    print("gullet._surface:", repr(_surface(seg)))
    print(
        "naive join      :",
        repr("".join("\\" + t.text if t.kind == "cs" else t.text for t in seg)),
    )


if __name__ == "__main__":
    main()
