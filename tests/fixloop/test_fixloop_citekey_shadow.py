r"""批二 (apj-bib-scout §S2/S3/S4): vendored_sty_shadow 两缺口 + citekey_sanitize。

- ``_provides_date`` 宏间址兜底：``\ProvidesPackage{x}[\abx@date ...]`` 形
  回读同文件 ``\def\abx@date{YYYY/MM/DD}``（biblatex v3.12 实证面）。
- ``find_vendored_shadows`` cwd 毒化防御：kpsewhich 命中落 wdir 内 → 非遮蔽。
- ``vendored_shadow_isolate`` cohort_map：确证更旧的包同包伴船整组隔离
  （1907.00257 半栈 biblatex / 2003.10727 全栈——只隔 .sty 留 .def/.bbx
  继续遮蔽 = 新混栈）。
- ``citekey_sanitize``：旧 .bbl cite-key 裸 ``&``/``_`` 双侧一致重写
  （\bibitem 定义点 + \cite 引用点 + .aux 残留）。
"""

from pathlib import Path

from _fixloopkit import ShadowEng, mk_ctx

from texlate.compile.fixloop.builtins import (
    _provides_date,
    citekey_sanitize,
    find_vendored_shadows,
    vendored_shadow_isolate,
)

OLD_BIBLATEX = (
    "\\def\\abx@date{2018/11/02}\n\\def\\abx@version{3.12}\n"
    "\\ProvidesPackage{biblatex}[\\abx@date\\space v\\abx@version\\space programmable]\n"
)
NEW_BIBLATEX = "\\ProvidesPackage{biblatex}[2025/01/01 v3.21 programmable]\n"


def test_provides_date_literal() -> None:
    assert _provides_date(NEW_BIBLATEX) == (2025, 1, 1)


def test_provides_date_macro_indirect() -> None:
    """``[\\abx@date ...]`` 间址 → 同文件 ``\\def\\abx@date`` 取回字面日期。"""
    assert _provides_date(OLD_BIBLATEX) == (2018, 11, 2)


def test_provides_date_no_face() -> None:
    assert _provides_date("\\ProvidesPackage{noprov}\n") is None
    # bracket 存但非 cs 引导（版本字面量）→ None
    assert _provides_date("\\ProvidesPackage{x}[v1.0 notes]\n") is None


def test_vendored_shadow_cohort_isolation(tmp_path: Path) -> None:
    """1907.00257 形：vendored biblatex 半栈确证更旧 → sty+ 伴船整组隔离。"""
    wdir = tmp_path / "proj"
    wdir.mkdir()
    texmf = tmp_path / "texmf"  # 系统面必须在 wdir 外（否则正中 cwd 毒化闸）
    texmf.mkdir()
    (texmf / "biblatex.sty").write_text(NEW_BIBLATEX, encoding="utf-8")
    for name in (
        "biblatex.sty",
        "biblatex.def",
        "biblatex.cfg",
        "blx-compat.def",
        "standard.bbx",
        "numeric.cbx",
        "english.lbx",
    ):
        (wdir / name).write_text(OLD_BIBLATEX, encoding="utf-8")
    (wdir / "myown.bbx").write_text("% author bbx\n", encoding="utf-8")
    (wdir / "other.sty").write_text("% unrelated\n", encoding="utf-8")
    params = {
        "exts": (".sty", ".cls"),
        "suffix": ".fixloop-iso",
        "cohort_map": {
            "biblatex.sty": [
                "biblatex.def",
                "biblatex.cfg",
                "blx-*.def",
                "*.bbx",
                "*.cbx",
                "*.lbx",
                "*.dbx",
            ]
        },
    }
    ok, note = vendored_shadow_isolate(mk_ctx(wdir), ShadowEng(texmf), None, params)
    assert ok, note
    assert (wdir / "biblatex.sty.fixloop-iso").is_file()
    for name in (
        "biblatex.def",
        "biblatex.cfg",
        "blx-compat.def",
        "standard.bbx",
        "numeric.cbx",
        "english.lbx",
        "myown.bbx",
    ):
        assert (wdir / f"{name}.fixloop-iso").is_file(), name
    assert (wdir / "other.sty").is_file()  # 非伴船不动


def test_vendored_probe_hit_inside_wdir_not_shadow(tmp_path: Path) -> None:
    """kpsewhich cwd 毒化：命中落 wdir 内（非系统件）→ 不算遮蔽证据。"""
    wdir = tmp_path / "proj"
    wdir.mkdir()
    sub = wdir / "chaps"
    sub.mkdir()
    (sub / "biblatex.sty").write_text(OLD_BIBLATEX, encoding="utf-8")
    (wdir / "biblatex.sty").write_text(OLD_BIBLATEX, encoding="utf-8")
    eng = ShadowEng(tmp_path / "texmf", extra={"biblatex.sty": sub / "biblatex.sty"})
    assert find_vendored_shadows(mk_ctx(wdir), eng, (".sty",)) == []


def test_citekey_sanitize_dual_side(tmp_path: Path) -> None:
    """.bbl \\bibitem 定义点 + .tex \\cite 引用点同图重写；aux 残留同步。"""
    (tmp_path / "ms.bbl").write_text(
        "\\bibitem{Allen_90} Allen 1990\n\\bibitem[LAB]{2005A&A...429..161T} A&A\n"
        "\\bibitem{plain} Plain\n",
        encoding="utf-8",
    )
    (tmp_path / "main.tex").write_text(
        "see \\cite{Allen_90} and \\citep[fig.~2]{2005A&A...429..161T,plain}\n"
        "% \\cite{commented_key}\n",
        encoding="utf-8",
    )
    (tmp_path / "ms.aux").write_text(
        "\\citation{Allen_90,plain}\n\\bibcite{Allen_90}{{1}{1}{}{}{}}\n",
        encoding="utf-8",
    )
    ok, note = citekey_sanitize(mk_ctx(tmp_path), None, None, {})
    assert ok, note
    bbl = (tmp_path / "ms.bbl").read_text(encoding="utf-8")
    tex = (tmp_path / "main.tex").read_text(encoding="utf-8")
    aux = (tmp_path / "ms.aux").read_text(encoding="utf-8")
    assert "\\bibitem{Allen-90}" in bbl
    assert "\\bibitem[LAB]{2005AAA...429..161T}" in bbl
    assert "\\cite{Allen-90}" in tex
    assert "\\citep[fig.~2]{2005AAA...429..161T,plain}" in tex
    assert "\\cite{commented_key}" in tex  # 注释内不改（展示面非查找面）
    assert "\\citation{Allen-90,plain}" in aux
    assert "\\bibcite{Allen-90}" in aux


def test_citekey_sanitize_idempotent(tmp_path: Path) -> None:
    """无裸 &/_ 键 → (False, …) 自幂不点火。"""
    (tmp_path / "ms.bbl").write_text("\\bibitem{allen90} x\n", encoding="utf-8")
    (tmp_path / "main.tex").write_text("\\cite{allen90}\n", encoding="utf-8")
    ok, note = citekey_sanitize(mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no unsafe" in note
