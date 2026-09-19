r"""decmathsym: ``_SITE_DEF_CMDS`` 数学声明族扩面 (resid209 census, 9901081)。

9901081 (2.09 升级稿 ``\ifnfsstwo`` live 臂): ``\DeclareMathSymbol{\upi/\umu/
\upartial}`` 三处非致命 already_def —— DeclareMath{Symbol,Delimiter,Accent,
Radical} 与 DeclareMathAlphabet 同走 ``\ifx\csname\@gobble\string#1\endcsname
\relax`` 自有守卫 (latex.ltx:13462/13511/13594/13696 产 ``Command `\X'
already defined``, 不经 ``\@ifdefinable``) → ``\let\X\@undefined`` 站点前置
有效; end* 名亦无 ``\@qend`` 拒径 (守卫不查 ``\@ifdefinable``) → 仍走
``\let`` 不换 rc@ 旁路。``\DeclareSymbolFontAlphabet`` 不入列: 守卫查的是
space-后缀伴生名 ``\X␣`` (latex.ltx:13753-13763), 清 ``\X`` 本体是徒劳。
"""

from pathlib import Path

from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

_MAIN_DOCCLASS = "\\documentclass{article}\n"


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _write_main(tmp_path: Path, body: str) -> None:
    (tmp_path / "main.tex").write_text(_MAIN_DOCCLASS + body)


def test_decmathsym_ifnfsstwo_arm_cluster(tmp_path: Path) -> None:
    r"""9901081 形: ``\ifnfsstwo`` 臂内 ``\DeclareMathSymbol`` 三连撞
    (``\ifnfsstwo`` 非 ``\iffalse`` —— 臂不遮盖, 站点可见, ``\let``
    前置落臂内随臂生死)。反引号签三撞名一轮全清。"""
    _write_main(
        tmp_path,
        "\\ifnfsstwo\n"
        '\\DeclareMathSymbol{\\upi}{\\mathalpha}{letters}{"60}\n'
        '\\DeclareMathSymbol{\\umu}{\\mathalpha}{letters}{"6D}\n'
        '\\DeclareMathSymbol{\\upartial}{\\mathord}{letters}{"40}\n'
        "\\else\n\\let\\upi\\relax\n\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:3: LaTeX Error: Command `\\upi' already defined.\n"
        "main.tex:4: LaTeX Error: Command `\\umu' already defined.\n"
        "main.tex:5: LaTeX Error: Command `\\upartial' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "upi", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for cs in ("upi", "umu", "upartial"):
        assert (
            f"\\makeatletter\\let\\{cs}\\@undefined\\makeatother\n"
            f"\\DeclareMathSymbol{{\\{cs}}}"
        ) in t, cs
    # 前置落在臂内 (\ifnfsstwo 与 \else 之间), 不泄出死臂语义
    assert (
        t.index("\\ifnfsstwo") < t.index("\\let\\upi\\@undefined") < t.index("\\else")
    )


def test_decmathsym_all_four_decl_sites(tmp_path: Path) -> None:
    r"""四件全收: 单撞名证据 + 同文件 DeclareMath{Symbol,Delimiter,Accent,
    Radical} 站点簇扩 → 一轮全清 (站点前置语义无操作覆盖未撞名)。"""
    _write_main(
        tmp_path,
        '\\DeclareMathSymbol{\\upi}{\\mathalpha}{letters}{"60}\n'
        '\\DeclareMathDelimiter{\\ulcorner}{\\mathopen}{letters}{"70}{letters}{"71}\n'
        '\\DeclareMathAccent{\\wtilde}{\\mathord}{letters}{"7E}\n'
        '\\DeclareMathRadical{\\sqrtsign}{symbols}{"70}{largesymbols}{"70}\n'
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Command `\\upi' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "upi", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    for cs, cmd in (
        ("upi", "DeclareMathSymbol"),
        ("ulcorner", "DeclareMathDelimiter"),
        ("wtilde", "DeclareMathAccent"),
        ("sqrtsign", "DeclareMathRadical"),
    ):
        assert (
            f"\\makeatletter\\let\\{cs}\\@undefined\\makeatother\n\\{cmd}{{\\{cs}}}"
        ) in t, cs


def test_decmathsym_unbraced_cs_site(tmp_path: Path) -> None:
    r"""裸 cs 形 ``\DeclareMathSymbol\upi{...}`` (无花括第一参) 同收。"""
    _write_main(
        tmp_path,
        '\\DeclareMathSymbol\\upi{\\mathalpha}{letters}{"60}\n'
        '\\DeclareMathSymbol\\umu{\\mathalpha}{letters}{"6D}\n'
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Command `\\upi' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "upi", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\makeatletter\\let\\upi\\@undefined\\makeatother\n\\DeclareMathSymbol\\upi"
    ) in t
    assert "\\let\\umu\\@undefined" in t


def test_decmathsym_endstar_name_keeps_let(tmp_path: Path) -> None:
    r"""end* 名 × ``\DeclareMathSymbol`` 站仍走 ``\let\X\@undefined``:
    csname-freeze 守卫无 ``\@qend`` 恒拒径 (非 ``\@ifdefinable``),
    与 ``\newcommand`` 站换 rc@ 旁路的分流正好相反 —— 不可入
    ``_IFN_ROUTED_CMDS``。"""
    _write_main(
        tmp_path,
        '\\DeclareMathSymbol{\\endbaz}{\\mathalpha}{letters}{"50}\n'
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Command \\endbaz already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](_ctx(tmp_path), None, "endbaz", {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\makeatletter\\let\\endbaz\\@undefined\\makeatother\n"
        "\\DeclareMathSymbol{\\endbaz}"
    ) in t
    assert "rc@ifdefinable" not in t


def test_decmathsym_sty_site_no_catcode_wrap(tmp_path: Path) -> None:
    r""".sty 内 ``\DeclareMathSymbol`` 站前置裸 ``\let`` —— @ 本是
    letter, ``\makeatother`` 尾注会烂掉其后 @-cs (同 .cls 钉)。"""
    _write_main(tmp_path, "\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "foo.sty").write_text(
        '\\DeclareMathSymbol{\\upi}{\\mathalpha}{letters}{"60}\n'
        '\\DeclareMathSymbol{\\umu}{\\mathalpha}{letters}{"6D}\n'
        "\\def\\define@key#1{#1}\n",
    )
    (tmp_path / "main.log").write_text(
        "foo.sty:1: LaTeX Error: Command `\\upi' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "upi", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "foo.sty").read_text()
    assert "\\let\\upi\\@undefined\n\\DeclareMathSymbol{\\upi}" in t
    assert "\\let\\umu\\@undefined\n\\DeclareMathSymbol{\\umu}" in t
    assert "makeatletter" not in t
    assert "makeatother" not in t


def test_decmathsym_unrelated_decls_untouched(tmp_path: Path) -> None:
    r"""负面钉: 同文件 ``\providecommand`` (非 end* 名撞名静默族) 与
    ``\DeclareSymbolFontAlphabet``/``\SetMathAlphabet`` (守卫查伴生名
    或非 already_def 签) 站点一律不动。"""
    _write_main(
        tmp_path,
        "\\providecommand{\\upi}{P}\n"
        "\\DeclareSymbolFontAlphabet{\\mymath}{operators}\n"
        "\\SetMathAlphabet\\foo{normal}{OT1}{cmr}{m}{n}\n"
        '\\DeclareMathSymbol{\\umu}{\\mathalpha}{letters}{"6D}\n'
        '\\DeclareMathSymbol{\\upartial}{\\mathord}{letters}{"40}\n'
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:5: LaTeX Error: Command `\\umu' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "umu", {"min_batch": 2}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\let\\umu\\@undefined" in t
    assert "\\let\\upi" not in t  # provide 站点非恒拒名 —— 不动
    assert "\\let\\mymath" not in t  # 守卫查 \mymath␣ 伴生名 —— 清本体徒劳
    assert "\\let\\foo" not in t  # \SetMathAlphabet 不产 already_def 签


def test_decmathsym_single_site_declines_min_batch(tmp_path: Path) -> None:
    """孤站单撞名格 (min_batch=2 门) 让位 renew(111) —— 同 newcommand 族。"""
    _write_main(
        tmp_path,
        '\\DeclareMathSymbol{\\upi}{\\mathalpha}{letters}{"60}\n'
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:2: LaTeX Error: Command `\\upi' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "upi", {"min_batch": 2}
    )
    assert not ok
    assert "<2" in note


def test_decmathsym_commented_site_not_counted(tmp_path: Path) -> None:
    r"""``% \DeclareMathSymbol{\upi}`` 注释内站点遮盖剔除 —— 不数不动,
    孤撞名仍按 min_batch 门 decline (docclass 块不扩站)。"""
    _write_main(
        tmp_path,
        '%\\DeclareMathSymbol{\\upi}{\\mathalpha}{letters}{"60}\n'
        "\\begin{document}\nx\n\\end{document}\n",
    )
    (tmp_path / "main.log").write_text(
        "main.tex:1: LaTeX Error: Command `\\upi' already defined.\n"
    )
    ok, note = TRANSFORM_FNS["undefine_for_redef"](
        _ctx(tmp_path), None, "upi", {"min_batch": 2}
    )
    assert not ok
    assert "<2" in note
    t = (tmp_path / "main.tex").read_text()
    assert "\\let\\upi\\@undefined" not in t
