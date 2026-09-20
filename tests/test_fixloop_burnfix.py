r"""burnfix 道三修钉 —— dedup 键烧穿/自投毒两族。

fix 1 ``\RequirePackage`` 化: ``_inject_after_docclass`` 在 docclass 藏进
``\IfFileExists``/宏体等 depth>0 形态时 ``find_docclass_ends`` 零命中 →
snippet 头注文件首行 (0812.0615 lang10.tex 实证) —— ``\usepackage`` 落
``\documentclass`` 前 = Missing ``\begin{document}`` 级联烧光轮次。
``\RequirePackage`` docclass 前后皆合法, 五个可达头注臂全换; 锚在 live
装载点行前的 stem_provs 臂 (``_builtins_csfix`` premature 前半) 天生在
docclass 后, 保留 ``\usepackage``。

fix 2 ``para_longize`` cap 8→64: dedup ``{rule}:None`` 全族共位,
>cap 截断使尾宏同签永不再派 (return-False-after-writes 在引擎语义下是
终局结算 —— no-apply 轮直接 break 出 verdict, 不可作续尾信号)。
截断仍发生时 notes 记 ``cap xN`` 残量, yaml known_gap 留痕。

fix 3 ``bbl_stub_rewrite`` count=0: multibib 双 ``\bibliography`` 档
首处改写后 dedup 键已烧, 尾处永滞留 —— TeX 语义本就逐 ``\bibliography``
各印一份 thebibliography, 全量改写是正确形。
"""

from pathlib import Path

from test_fixloop_loop import MockEngine

from texlate.compile.fixloop._builtins_bib import bbl_stub_rewrite
from texlate.compile.fixloop._builtins_common import _inject_after_docclass
from texlate.compile.fixloop._builtins_csfix import (
    _ensure_usepackage,
    premature_cs_guard,
)
from texlate.compile.fixloop._builtins_misschar import (
    _fb_snippet_lines,
    font_fallback,
)
from texlate.compile.fixloop._builtins_paralong import para_longize
from texlate.compile.fixloop._builtins_shim import cs_rebind
from texlate.compile.fixloop.engine import LoopCtx


def _ctx(tmp_path: Path, err_head: str = "") -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


#: docclass 藏进 ``\IfFileExists`` 两臂 —— ``find_docclass_ends`` 只收
#: depth-0 命中, 本形零缝 → ``_inject_after_docclass`` 走头注路径
#: (0812.0615 lang10.tex 同构)。
_HIDDEN_DOCCLASS = (
    "\\IfFileExists{mycls.cls}{\\documentclass{mycls}}{\\documentclass{article}}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)


# ═══════════ fix 1: 头注可达臂一律 \RequirePackage ═══════════


def test_fb_snippet_head_uses_requirepackage() -> None:
    """``_fb_snippet_lines`` 头行 ``\\RequirePackage`` —— 无 ``\\usepackage``。"""
    head = _fb_snippet_lines([0x0416], "Noto Serif")[:4]
    assert "\\RequirePackage{newunicodechar}" in head
    assert "\\ifdefined\\newfontfamily\\else\\RequirePackage{fontspec}\\fi" in head
    assert not any("\\usepackage" in ln for ln in head)


def test_hidden_docclass_head_prepend_safe(tmp_path: Path) -> None:
    """docclass 藏 ``\\IfFileExists`` 内 → 头注块落行首仍是 ``\\RequirePackage``
    (docclass 前 ``\\usepackage`` 即自投毒 —— 本钉防回归)。"""
    _write(tmp_path, "main.tex", _HIDDEN_DOCCLASS)
    _write(
        tmp_path,
        "main.log",
        "Missing character: There is no Ж (U+0416) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t.startswith("% fixloop: per-char font fallback")
    head = t.split("\\IfFileExists", 1)[0]
    assert "\\RequirePackage{newunicodechar}" in head
    assert "\\usepackage" not in head


def test_ensure_usepackage_head_prepend(tmp_path: Path) -> None:
    """``_ensure_usepackage`` 无 docclass 档头注 —— ``\\RequirePackage`` 行首合法。"""
    _write(tmp_path, "main.tex", _HIDDEN_DOCCLASS)
    eng = MockEngine([], available={"url.sty"})
    out = _ensure_usepackage(_ctx(tmp_path), eng, "url")
    assert any("url" in s for s in out)
    t = (tmp_path / "main.tex").read_text()
    assert t.split("\n", 1)[0] == "\\RequirePackage{url} % fixloop: cs-fix"


def test_cs_rebind_emits_requirepackage(tmp_path: Path) -> None:
    """cs_rebind 块 (无 docclass → 头注) ``\\RequirePackage{fontspec}``。"""
    _write(
        tmp_path,
        "main.tex",
        "\\begin{document}\nSee \\S 7 and \\S 9.\n\\end{document}\n",
    )
    _write(
        tmp_path, "main.log", 'Missing character: There is no § ("A7) in font cmr10!\n'
    )
    ok, note = cs_rebind(_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\RequirePackage{fontspec}" in t
    assert "\\usepackage" not in t


def test_premature_seam_emits_requirepackage(tmp_path: Path) -> None:
    """premature_cs_guard docclass 缝臂 emit ``\\RequirePackage{p}``。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\numberwithin{equation}{section}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    _write(
        tmp_path,
        "main.log",
        "./main.tex:2: LaTeX Error: Missing \\begin{document}.\nl.2 \\numberwithin{e\n",
    )
    ok, note = premature_cs_guard(
        _ctx(tmp_path), MockEngine([], available={"amsmath.sty"}), None, {}
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\RequirePackage{amsmath} % fixloop: premature provider" in t


def test_inject_after_docclass_head_prepend_path(tmp_path: Path) -> None:
    """机制钉: 零 docclass 缝时 ``_inject_after_docclass`` 确走头注。"""
    _write(tmp_path, "main.tex", _HIDDEN_DOCCLASS)
    ctx = _ctx(tmp_path)
    assert _inject_after_docclass(ctx, "SNIP")
    t = (tmp_path / "main.tex").read_text()
    assert t.startswith("SNIP\n\\IfFileExists")


# ═══════════ fix 2: para_longize cap 64 + 截断注记 ═══════════


def _para_proj(tmp_path: Path, names: list[str]) -> Path:
    defs = "\n".join(f"\\def\\{n}#1{{#1}}" for n in names)
    return _write(
        tmp_path,
        "main.tex",
        f"\\documentclass{{article}}\n{defs}\n\\begin{{document}}\nx\n\\end{{document}}\n",
    )


def _para_head(names: list[str]) -> str:
    return "\n".join(
        f"main.tex:{i + 2}: Paragraph ended before \\{n} was complete."
        for i, n in enumerate(names)
    )


def test_para_longize_cap_covers_ten(tmp_path: Path) -> None:
    """10 肇事宏 (旧 cap 8 截断面) —— cap 64 下全收 ``\\long``。"""
    names = [f"mac{chr(97 + i)}" for i in range(10)]  # maca..macj
    main = _para_proj(tmp_path, names)
    ctx = _ctx(tmp_path, _para_head(names))
    ok, note = para_longize(ctx, None, None, {})
    assert ok, note
    t = main.read_text()
    for n in names:
        assert f"\\long \\def\\{n}" in t


def test_para_longize_truncation_noted(tmp_path: Path) -> None:
    """70 肇事宏 > cap 64 —— 前 64 收 ``\\long``, notes 记截断残量
    (dedup 键已烧, 滞留宏靠已知残面留痕, 非静默)。"""
    names = [f"mac{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(70)]
    main = _para_proj(tmp_path, names)
    ctx = _ctx(tmp_path, _para_head(names))
    ok, note = para_longize(ctx, None, None, {})
    assert ok, note
    t = main.read_text()
    assert t.count("\\long \\def") == 64  # noqa: PLR2004 - params.max_macros 默认值断言
    assert "cap x64" in note
    assert "truncated" in note


# ═══════════ fix 3: bbl_stub_rewrite 全量改写 ═══════════


def test_bbl_stub_rewrite_all_bibliographies(tmp_path: Path) -> None:
    """multibib 双 ``\\bibliography`` —— 两处全改写 ``\\input`` (逐 call-site
    各印 thebibliography 是 TeX 本义); 旧 count=1 尾处同签永滞留。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{refsA}\ny\n\\bibliography{refsB}\n\\end{document}\n",
    )
    _write(
        tmp_path,
        "main.bbl",
        "\\begin{thebibliography}{9}\\end{thebibliography}\n",
    )
    ok, note = bbl_stub_rewrite(_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t.count("\\input{main.bbl}") == 2  # noqa: PLR2004
    assert "\\bibliography" not in t
