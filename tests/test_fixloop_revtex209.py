r"""revtex209_surface_polyfill 内建 —— 209 升级稿踩 revtex4-2 删除面整块补。

实证簇 (corpus_v3 残面 13 格): ``upgrade_209`` 把 ``\documentstyle{revtex}``
改写成 ``\documentclass{revtex4-2}`` + COMPAT_SHIM——改写稿不经 revtex.cls
stub (90-shim-legacy ``legacy_pkg_shim`` 只答 ``missing_file``), 却踩
revtex4-2 刻意删除的 2.09 宏面: ``\twocolumn``/``\@makecol`` 被
``\let\@undefined``、frontmatter 机 begin-doc 才武装而序言 ``\author``
先炸、``\pacs`` 在 ``\maketitle`` 后 ClassError。锚定 = COMPAT_SHIM
面包屑 (∧) live ``\documentclass{revtex4-2}``。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins, load_ruleset
from texlate.compile.fixloop.builtins import revtex209_surface_polyfill
from texlate.compile.fixloop.engine import LoopCtx

_DOCCLASS = "\\documentclass[aps,prb]{revtex4-2}"
_SHIM = "% texlate: LaTeX 2.09 compatibility shim"
_PREAMBLE_AND_BODY = (
    "\\author{Some One}\n"
    "\\begin{document}\n"
    "\\maketitle\n"
    "\\pacs{12.34.Ab}\n"
    "\\end{document}\n"
)


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=None
    )


def _main(tmp_path: Path, text: str) -> None:
    (tmp_path / "main.tex").write_text(text, encoding="utf-8")


def _upgraded(tmp_path: Path) -> None:
    """仿真 upgrade_209 产物: live revtex4-2 docclass + COMPAT_SHIM 面包屑。"""
    _main(
        tmp_path,
        _DOCCLASS + "\n" + _SHIM + "\n\\usepackage{latexsym}\n" + _PREAMBLE_AND_BODY,
    )


def test_hit_injects_after_docclass(tmp_path: Path) -> None:
    r"""锚定双全 → docclass 缝后即注 (序言 ``\author`` 之前) 整块面。"""
    _upgraded(tmp_path)
    ok, note = revtex209_surface_polyfill(_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    mark = "% fixloop: revtex 2.09 surface polyfill"
    assert mark in t
    # 注入位: docclass 行之后、\author 之前 (frontmatter 机须先于序言调用武装)
    assert t.index(_DOCCLASS) < t.index(mark) < t.index("\\author")
    assert "\\frontmatter@init" in t
    assert "\\providecommand{\\twocolumn}[1][]{#1}" in t
    assert "\\@ifundefined{@makecol}" in t
    # hook 内 \long\def 单 ``#``——``##`` 会字面留下炸参数号 (guardsmoke 实证);
    # \long 容忍空行/\and 实参 (revpacs 残案)
    assert "\\AtBeginDocument{\\long\\def\\pacs#1{" in t
    injected = t.split(mark, 1)[1].split("\\makeatother", 1)[0]
    assert "##" not in injected
    assert "\\makeatletter" in t
    assert "\\makeatother" in t


def test_reject_no_breadcrumb(tmp_path: Path) -> None:
    r"""直写 ``\documentclass{revtex4-2}`` 的非 209 稿不动 (无面包屑)。"""
    _main(tmp_path, _DOCCLASS + "\n" + _PREAMBLE_AND_BODY)
    before = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok, note = revtex209_surface_polyfill(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "breadcrumb" in note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == before


def test_reject_wrong_class(tmp_path: Path) -> None:
    r"""面包屑在但 live docclass 非 revtex4-2 (article) → 不锚。"""
    _main(tmp_path, "\\documentclass{article}\n" + _SHIM + "\n" + _PREAMBLE_AND_BODY)
    ok, note = revtex209_surface_polyfill(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "revtex4-2" in note
    assert "polyfill" not in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_reject_neighbor_class_names(tmp_path: Path) -> None:
    r"""邻名 ``{revtex4}``/``{revtex4-1}`` 不算锚 (``{revtex4-2}`` 精确匹配)。"""
    for cls in ("revtex4", "revtex4-1"):
        wdir = tmp_path / cls
        wdir.mkdir()
        _main(wdir, f"\\documentclass{{{cls}}}\n" + _SHIM + "\n" + _PREAMBLE_AND_BODY)
        ok, _note = revtex209_surface_polyfill(_ctx(wdir), None, None, {})
        assert not ok, cls


def test_reject_commented_docclass_deadzone(tmp_path: Path) -> None:
    r"""注释掉的 ``\documentclass{revtex4-2}`` 死区不锚 (遮盖视图复核)。"""
    _main(
        tmp_path,
        _SHIM
        + "\n% \\documentclass{revtex4-2}\n\\documentclass{article}\n"
        + _PREAMBLE_AND_BODY,
    )
    ok, note = revtex209_surface_polyfill(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "revtex4-2" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "surface polyfill" not in t


def test_idempotent_second_call(tmp_path: Path) -> None:
    """二入幂等: 首注 True, 再调 False 且文本不变。"""
    _upgraded(tmp_path)
    ctx = _ctx(tmp_path)
    ok, _note = revtex209_surface_polyfill(ctx, None, None, {})
    assert ok
    after = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok2, note2 = revtex209_surface_polyfill(ctx, None, None, {})
    assert not ok2
    assert "already present" in note2
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == after


def test_registration_and_rule() -> None:
    """注册钉: TRANSFORM_FNS 直连 + rules/ 装载含同名规则且接线一致。"""
    assert (
        builtins.TRANSFORM_FNS["revtex209_surface_polyfill"]
        is revtex209_surface_polyfill
    )
    rules = {r.id: r for r in load_ruleset().rules}
    rule = rules["revtex209_surface_polyfill"]
    assert rule.phase == "loop"
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "revtex209_surface_polyfill"
    cats = {c.get("category") for c in rule.when["any"]}
    assert cats == {"undefined_cs", "other"}
