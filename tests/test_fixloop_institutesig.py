r"""institutesig wave-7 (#253): para_longize 表外残面收编钉。

117 cells/31 cs 普查 → 19 表外格/15 cs。逐条上游实档核签后收编:
``\abstract`` (aa.cls ``\let\abstract=\aaabstract`` 别名 —— 无
``\def\abstract`` 定义点, def-site 臂结构性够不到, astro-ph/0103289
实证), revtex 系 ``\@affil@match``/``\add@AUCO@grp``/``\@sect@ltx``/
``\ltx@def@footproc`` (ltxutil.sty/revtex4-*.cls 实档), microtype
``\MT@is@char`` (``\CHAR"``/``\relax`` 定界), pictex ``\put``
(``#1#2 at #3 #4 `` 字面 `` at ``+空格定界, 现行档已 \long 老档非),
mn2e ``\@titleone``, verbatim ``\verbatim@start``, float ``\@float@HH``,
textpos ``\TP@textblock``, pgffor ``\pgffor@var@add``,
caption ``\caption@prepareanchor`` (starred \newcommand)。``\abrace@next``
是 abraces.sty ``\let``-派发暂存 → 拒收面。``\Refff`` 是稿内自定义宏
走 def-site 臂 (fileset 内有 ``\def``), 不入表。
"""

import subprocess
from pathlib import Path

from _fixloopkit import XELATEX, EngStub, mk_ctx, requires_xelatex, write_file

from texlate.compile.fixloop._builtins_paralong import (
    _WRAP_TABLE,
    _wrap_block,
    para_longize,
)


def _xelatex(wdir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — 固定 argv, 测试面实弹编译
        [XELATEX, "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        cwd=wdir,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_wrap_table_institutesig_wave7() -> None:
    """表钉: 13 新行签名与上游实档逐字一致 (改 sig 须先重核定义点)。"""
    expected = {
        "abstract": ("#1", "{#1}"),
        "@titleone": ("#1", "{#1}"),
        "@affil@match": ("#1#2#3#4#5", "{#1}{#2}{#3}{#4}{#5}"),
        "add@AUCO@grp": ("#1#2#3#4", "{#1}{#2}{#3}{#4}"),
        "@sect@ltx": ("#1#2#3#4#5#6[#7]#8", "{#1}{#2}{#3}{#4}{#5}{#6}[#7]{#8}"),
        "MT@is@char": ('#1\\CHAR"#2#3#4\\relax', '#1\\CHAR"{#2}{#3}#4\\relax'),
        "verbatim@start": ("#1", "{#1}"),
        "ltx@def@footproc": ("#1[#2]", "{#1}[#2]"),
        "@float@HH": ("#1[H]", "{#1}[H]"),
        "TP@textblock": ("[#1,#2](#3,#4)", "[#1,#2](#3,#4)"),
        "pgffor@var@add": ("#1#2\\pgffor@stop", "{#1}#2\\pgffor@stop"),
        "caption@prepareanchor": ("#1#2", "{#1}{#2}"),
        "put": ("#1#2 at #3 #4 ", "{#1}#2 at #3 #4 "),
    }
    for name, spec in expected.items():
        assert _WRAP_TABLE.get(name) == spec, name


def test_abstract_alias_wrap(tmp_path: Path) -> None:
    r"""aa.cls 别名机制钉: ``\def\abstract`` 不存在 → def-site 零命中,
    wrap 兜底; ``\abstract`` 在 begindoc 前被调 → preamble 调用点缝。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\abstract{a\n\nb}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:2: Paragraph ended before \\abstract was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    assert "wrap" in note
    t = main.read_text()
    assert t.index("% fixloop: para_longize") < t.index("\\abstract{a")
    assert "\\let\\TL@pl@abstract\\abstract" in t
    assert "\\long\\def\\abstract#1{\\TL@pl@strip{#1}" in t


def test_abrace_next_denied(tmp_path: Path) -> None:
    r"""``\abrace@next`` 是 abraces.sty ``\let``-派发暂存 → 拒收 (2105.00115)。"""
    main = write_file(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:3: Paragraph ended before \\abrace@next was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert not ok
    assert "denied" in note
    assert "TL@pl@" not in main.read_text()


def test_put_pictex_delimited_block() -> None:
    r"""pictex ``\put`` 定界签名钉: 字面 `` at `` + 空格定界 #3/#4 + 尾空格
    #4 定界 —— 定界参裸转发 (顶层 `` at ``/空格不可能在已捕值内), 无界 #1 补括号。"""
    block, done = _wrap_block(["put"], _WRAP_TABLE, "")
    assert done == ["put"]
    assert "\\long\\def\\put#1#2 at #3 #4 {\\TL@pl@strip{#1}" in block
    assert (
        "\\long\\def\\TL@pl@put@siv#1#2#3#4{\\TL@pl@put{#1}#2 at #3 #4 }\\fi" in block
    )


def test_sect_ltx_eight_arg_block() -> None:
    r"""revtex ``\@sect@ltx`` 8 参链 —— stage 罗马级到 sviii, ``[#7]`` 定界参
    裸转发 (alias ``TL@pl@@sect@ltx``)。"""
    block, done = _wrap_block(["@sect@ltx"], _WRAP_TABLE, "")
    assert done == ["@sect@ltx"]
    assert "\\long\\def\\@sect@ltx#1#2#3#4#5#6[#7]#8{\\TL@pl@strip{#1}" in block
    assert (
        "\\long\\def\\TL@pl@@sect@ltx@sviii#1#2#3#4#5#6#7#8"
        "{\\TL@pl@@sect@ltx{#1}{#2}{#3}{#4}{#5}{#6}[#7]{#8}}\\fi" in block
    )


def test_mt_is_char_delimited_block() -> None:
    r"""microtype ``\MT@is@char`` —— ``\CHAR"``/``\relax`` 定界参裸转发,
    无界 #2/#3 补括号。"""
    block, done = _wrap_block(["MT@is@char"], _WRAP_TABLE, "")
    assert done == ["MT@is@char"]
    assert '\\long\\def\\MT@is@char#1\\CHAR"#2#3#4\\relax{\\TL@pl@strip{#1}' in block
    assert (
        "\\long\\def\\TL@pl@MT@is@char@siv#1#2#3#4"
        '{\\TL@pl@MT@is@char#1\\CHAR"{#2}{#3}#4\\relax}\\fi' in block
    )


@requires_xelatex
def test_xelatex_abstract_alias_e2e(tmp_path: Path) -> None:
    r"""真 xelatex aa.cls 机制: ``\let\abstract\aaabstract`` 别名 + preamble
    调用 —— def-site 收不到, wrap 快照别名实义剥 \par 后忠实转发。"""
    src = (
        "\\documentclass{article}\n"
        "\\def\\aaabstract#1{\\gdef\\absstore{#1}}\n"
        "\\let\\abstract\\aaabstract\n"
        "\\abstract{first para\n\nsecond para}\n"
        "\\begin{document}\\typeout{ABS:\\absstore}x\\end{document}\n"
    )
    write_file(tmp_path, "main.tex", src)
    _xelatex(tmp_path)
    log = (tmp_path / "main.log").read_text(errors="replace")
    assert "Paragraph ended before \\abstract" in log
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:4: Paragraph ended before \\abstract was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    r2 = _xelatex(tmp_path)
    log2 = (tmp_path / "main.log").read_text(errors="replace")
    assert r2.returncode == 0
    assert "Paragraph ended" not in log2
    assert "ABS:first para" in log2


@requires_xelatex
def test_xelatex_put_pictex_e2e(tmp_path: Path) -> None:
    r"""真 xelatex pictex 形非 \long ``\put#1#2 at #3 #4 ``: 参内空行炸
    para_ended; wrap 后 `` at ``/空格定界链剥 \par 忠实转发 (1404.0443)。"""
    src = (
        "\\documentclass{article}\n"
        "\\def\\put#1#2 at #3 #4 {\\typeout{PUT:#1|#2|#3|#4}}\n"
        "\\begin{document}\n\\put{obj} at 1 2\n\\put{o\n\nbj} at 3 4\n"
        "\\end{document}\n"
    )
    write_file(tmp_path, "main.tex", src)
    _xelatex(tmp_path)
    log = (tmp_path / "main.log").read_text(errors="replace")
    assert "Paragraph ended before \\put" in log
    ctx = mk_ctx(
        tmp_path, err_head="main.tex:5: Paragraph ended before \\put was complete."
    )
    ok, note = para_longize(ctx, EngStub(), None, {})
    assert ok, note
    r2 = _xelatex(tmp_path)
    log2 = (tmp_path / "main.log").read_text(errors="replace")
    assert r2.returncode == 0
    assert "Paragraph ended" not in log2
    assert "PUT:obj||1|2" in log2  # 无参调用忠实转发
    assert "PUT:o bj||3|4" in log2
