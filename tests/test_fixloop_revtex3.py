r"""revtex34-lane (2026-09-19): cond-mat/0408520 REVTeX-3 (``\documentstyle``) 面钉。

格面: ``\documentstyle[prb,aps]{revtex}`` 209 稿 (ISO-8859 编码)。
实测链 (stagerun-flipcheck2 记录 + 本车道全链 replay, xelatex 3 轮
clean 15 页 PDF):

- ``upgrade_209`` → ``\documentclass[prb,aps]{revtex4-2}`` + COMPAT_SHIM
  面包屑 (polyfill 锚定双条件之一);
- r1 ``undefined_cs:\twocolumn`` → ``revtex209_surface_polyfill``
  (``\frontmatter@init`` 早武装 + ``\twocolumn``/``\@makecol``/``\pacs``
  revtex4-2 删除面整块回填);
- r2 ``env_undefined:abstract`` → ``abstract_frontmatter_hoist``
  (稿面 maketitle→abstract 老版式前移, revtex4-2 的 abstract 环境仅
  frontmatter 期存活);
- ``\input BoxedEPS.tex`` → vendored stubs 落件: ``\ForceWidth`` 存值 +
  ``\BoxedEPSF``→``\includegraphics`` + ``\SetOzTeXEPSFSpecial``/
  ``\HideDisplacementBoxes`` 等 noop。

普查结论: 稿面实需面 = 以上四件, 无新增 shim 面 (``\address``/
``\narrowtext`` 是 revtex4-2 软警告非错误)。本文件钉住该链回归。
"""

from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop._builtins_vendored import (
    _vendor_root,
    _vendored_source,
    vendored_fetch,
)
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.latex209 import upgrade_209
from texlate.compile.logparse import ErrReport


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _ctx(tmp_path: Path, err_head: str = "") -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


class _Eng:
    """builtin_transform/regex_rewrite 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


#: 0408520 升级后形态 (upgrade_209 产物摘录): 面包屑 + live revtex4-2 docclass。
_UPGRADED_DOC = (
    "\\documentclass[prb,aps]{revtex4-2}\n"
    "% texlate: LaTeX 2.09 compatibility shim\n"
    "\\usepackage{latexsym}\n"
    "\\begin{document}\n"
    "\\twocolumn[\\hsize\\textwidth\\columnwidth\\hsize\n"
    "           \\csname @twocolumnfalse\\endcsname\n"
    "\\title{T}\\author{A}\\address{D}\n\\maketitle\n\\widetext\n"
    "\\begin{abstract}\nbody\n\\end{abstract}\n\\narrowtext\n]\n"
    "\\section{S}\nx\n\\end{document}\n"
)


def test_upgrade_209_converts_revtex_docstyle() -> None:
    """\\documentstyle[prb,aps]{revtex} → revtex4-2 + COMPAT_SHIM 面包屑。"""
    tex = "\\documentstyle[prb,aps]{revtex}\n\\begin{document}\nx\n\\end{document}\n"
    out, info = upgrade_209(tex)
    assert info["status"] == "converted"
    assert info["target"] == "revtex4-2"
    assert "\\documentclass[prb,aps]{revtex4-2}" in out
    assert "% texlate: LaTeX 2.09 compatibility shim" in out


def test_polyfill_rule_registered() -> None:
    rule = _rule("revtex209_surface_polyfill")
    assert rule.order == 145  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    cats = [w["category"] for w in rule.when["any"]]
    assert cats == ["undefined_cs", "other"]
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "revtex209_surface_polyfill"
    assert "compatibility shim" in rule.condition["source_contains"]


def test_polyfill_fires_on_upgraded_doc(tmp_path: Path) -> None:
    """面包屑 ∧ live revtex4-2 docclass → 整块删除面回填于 docclass 缝后。"""
    (tmp_path / "main.tex").write_text(_UPGRADED_DOC, encoding="utf-8")
    ok, note = actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule("revtex209_surface_polyfill"),
        _ctx(tmp_path),
        _Eng(),
        "twocolumn",
        ErrReport(),
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    # 注入位 = docclass 缝后, 先于 \begin{document} (序言 \author 要先见武装面)
    assert t.index("\\frontmatter@init") < t.index("\\begin{document}")
    assert "\\providecommand{\\twocolumn}[1][]{#1}" in t
    assert "\\@ifundefined{@makecol}" in t
    assert "\\def\\pacs#1" in t


def test_polyfill_declines_without_breadcrumb(tmp_path: Path) -> None:
    """直写 \\documentclass{revtex4-2} 的非 209 稿无面包屑 → 不锚。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{revtex4-2}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = actions._apply(  # noqa: SLF001
        _rule("revtex209_surface_polyfill"),
        _ctx(tmp_path),
        _Eng(),
        "twocolumn",
        ErrReport(),
    )
    assert not ok
    assert "breadcrumb" in note


def test_polyfill_declines_commented_docclass(tmp_path: Path) -> None:
    """面包屑在场但 docclass 全被注释 → masked live 复核拒锚。"""
    (tmp_path / "main.tex").write_text(
        "% \\documentclass[prb,aps]{revtex4-2}\n"
        "% texlate: LaTeX 2.09 compatibility shim\n"
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = actions._apply(  # noqa: SLF001
        _rule("revtex209_surface_polyfill"),
        _ctx(tmp_path),
        _Eng(),
        "twocolumn",
        ErrReport(),
    )
    assert not ok
    assert "revtex4-2" in note


def test_polyfill_idempotent(tmp_path: Path) -> None:
    """snippet 幂等: 二轮重入不重复注入。"""
    (tmp_path / "main.tex").write_text(_UPGRADED_DOC, encoding="utf-8")
    rule = _rule("revtex209_surface_polyfill")
    ok1, _ = actions._apply(rule, _ctx(tmp_path), _Eng(), "twocolumn", ErrReport())  # noqa: SLF001
    assert ok1
    ok2, note2 = actions._apply(  # noqa: SLF001
        rule, _ctx(tmp_path), _Eng(), "twocolumn", ErrReport()
    )
    assert not ok2
    assert "already present" in note2


def test_abstract_hoist_rule_registered() -> None:
    rule = _rule("abstract_frontmatter_hoist")
    assert rule.order == 168  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    cats = [w["category"] for w in rule.when["any"]]
    assert cats == ["env_undefined", "undefined_cs"]
    assert rule.action["kind"] == "regex_rewrite"


def test_abstract_hoist_paper_shape(tmp_path: Path) -> None:
    """0408520 实形 → abstract 块+间隔段前移 \\maketitle 前。"""
    doc = (
        "\\documentclass[prb,aps]{revtex4-2}\n"
        "% texlate: LaTeX 2.09 compatibility shim\n"
        "\\begin{document}\n"
        "\\twocolumn[\\hsize\\textwidth\\columnwidth\\hsize\n"
        "           \\csname @twocolumnfalse\\endcsname\n"
        "\\title{T}\n\\author{A}\n\\address{D}\n\n\\maketitle\n\\widetext\n\n\n"
        "\\begin{abstract}\nabstract body\n\\end{abstract}\n"
        "\\vspace{0.5cm}\n\\narrowtext\n]\n"
        "\\section{Intro}\nx\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ctx = _ctx(
        tmp_path,
        "! LaTeX Error: Environment abstract undefined.\nl.26 \\begin{abstract}",
    )
    ok, note = actions._apply(  # noqa: SLF001
        _rule("abstract_frontmatter_hoist"), ctx, _Eng(), "abstract", ErrReport()
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t.index("\\begin{abstract}") < t.index("\\maketitle")
    assert "abstract body" in t
    assert t.index("\\end{abstract}") < t.index("\\maketitle")


def test_boxedeps_vendored_stub_surface() -> None:
    """vendored BoxedEPS.tex 提供稿面实调宏面 (\\input 装入件)。"""
    src = _vendored_source(_vendor_root({}), "BoxedEPS.tex")
    assert src is not None, "BoxedEPS.tex not vendored"
    body = src.read_text(encoding="utf-8")
    # 0408520 实调面: \ForceWidth 存值 + \BoxedEPSF 退化 \includegraphics
    assert "\\def\\ForceWidth#1" in body
    assert "\\def\\BoxedEPSF#1" in body
    assert "\\includegraphics" in body
    # driver-special/位移框开关 noop (编译期 \special 由 graphicx 接管)
    for cs in ("\\SetOzTeXEPSFSpecial", "\\HideDisplacementBoxes"):
        assert f"\\def{cs}{{}}" in body


def test_boxedeps_vendored_fetch_installs(tmp_path: Path) -> None:
    """vendored_fetch 把 stub 平铺进 wdir —— \\input BoxedEPS.tex 命中件。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input BoxedEPS.tex\n", encoding="utf-8"
    )
    ok, note = vendored_fetch(_ctx(tmp_path), _Eng(), "BoxedEPS.tex", {})
    assert ok, note
    installed = tmp_path / "BoxedEPS.tex"
    assert installed.is_file()
    assert "\\def\\BoxedEPSF#1" in installed.read_text(encoding="utf-8")


def test_full_chain_upgraded_doc_converges(tmp_path: Path) -> None:
    """升级稿序贯过两规则 → polyfill 注入 + abstract 前移同落 (replay 序钉)。"""
    (tmp_path / "main.tex").write_text(_UPGRADED_DOC, encoding="utf-8")
    ctx = _ctx(tmp_path)
    ok1, _ = actions._apply(  # noqa: SLF001
        _rule("revtex209_surface_polyfill"), ctx, _Eng(), "twocolumn", ErrReport()
    )
    assert ok1
    ctx.err_head = (
        "! LaTeX Error: Environment abstract undefined.\nl.30 \\begin{abstract}"
    )
    ok2, _ = actions._apply(  # noqa: SLF001
        _rule("abstract_frontmatter_hoist"), ctx, _Eng(), "abstract", ErrReport()
    )
    assert ok2
    t = (tmp_path / "main.tex").read_text()
    assert "\\providecommand{\\twocolumn}[1][]{#1}" in t
    assert t.index("\\begin{abstract}") < t.index("\\maketitle")
