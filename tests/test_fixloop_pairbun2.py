"""pairbun2 钉 —— failmine7 pair-bundle 四捆落地 (2026-09-20)。

B1 ``msym_tfm_rename`` (95-targeted.yaml order 19, 2 cells): missing_tfm
|msymN CTAN 死名 → 源内引用改 msbmN (amsfonts 槽位兼容, tftopl 对账);
臂先 install_tfm(20) 评估, 死名在装包面前完成改名。
B2 ``and:`` cs_table 键 + cs_targeted_fix when.any 扩 cls_unsupported
(95-targeted.yaml, 2 cells): revtex4-2 ``\\let\\and\\frontmatter@and``
类载抢占 → 守卫形全跳过 → 无条件 ``\\def\\and{\\par}`` 覆盖。
B3 ``mathbf_ot1_greek`` (60-misschar.yaml order 25.95, 1+1 cells):
``\\mathbf{\\Lambda}`` 族 OT1 槽位-in-TU 字体控字符缺字 →
``\\ensuremath{\\boldsymbol{...}}`` 站点改写; ams/bm 包装载门控。
B4 ``hanja_route_fallback`` (60-misschar.yaml order 29.5, 2+1 cells):
xetexko hanja→UnBatang 路由缺字 (逐字 newunicodechar 绑在 catcode
域全死) → ``\\setmainhanjafont`` 族级改绑 FandolSong, masked 面活
``\\begin{document}`` 锚 + ``\\def\\txlatehanjaroute{}`` 代码标记幂等。
"""

import re

import regex

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.ruleset import Rule

_RS = load_ruleset()
_MSYM = next(r for r in _RS.rules if r.id == "msym_tfm_rename")
_MATHBF = next(r for r in _RS.rules if r.id == "mathbf_ot1_greek")
_HANJA = next(r for r in _RS.rules if r.id == "hanja_route_fallback")
_CS = next(r for r in _RS.rules if r.id == "cs_targeted_fix")
_CSTABLE = _CS.action["params"]["cs_table"]


def _sub(rule: Rule, text: str) -> str | None:
    """经 _compile_rewrites/_masked_sub 真管线跑单条 rewrite。"""
    pat, repl, masked = actions._compile_rewrites(  # noqa: SLF001
        rule.action["params"]["rewrites"]
    )[0]
    if masked:
        return actions._masked_sub(pat, repl, text)  # noqa: SLF001
    return actions._bounded_sub(pat, repl, text)  # noqa: SLF001


def test_ruleset_loads_with_pairbun2_rules() -> None:
    """三新臂在册且位次钉死 (共仓兄弟车道并发加规则, 只钉下界)。"""
    assert len(_RS.rules) >= 200  # noqa: PLR2004 - 落地时 197+3
    assert _MSYM.order == 19  # noqa: PLR2004 - install_tfm(20) 前
    assert _MATHBF.order == 25.95  # noqa: PLR2004 - caret(25.9) 后 font_fallback(26) 前
    assert _HANJA.order == 29.5  # noqa: PLR2004 - hani(29) 后 fontspec_clone_sub(30.5) 前
    for r in (_MSYM, _MATHBF, _HANJA):
        assert r.action["kind"] == "regex_rewrite"


def test_msym_arm_gate() -> None:
    """B1 门: missing_tfm + payload_required + payload 精确 msym<N>。"""
    assert _MSYM.when == {"category": "missing_tfm", "payload_required": True}
    pat = _MSYM.condition["payload_pattern"]
    assert re.search(pat, "msym10")
    assert re.search(pat, "msym7")
    assert re.search(pat, "msym10x") is None
    assert re.search(pat, "cmsym10") is None


def test_msym_rewrite() -> None:
    """B1 改写: msym10→msbm10, cmsym/msym10x 不动。"""
    out = _sub(_MSYM, "\\font\\x=msym10 at 14pt \\font\\y=cmsym10")
    assert out == "\\font\\x=msbm10 at 14pt \\font\\y=cmsym10"
    assert _sub(_MSYM, "\\font\\z=msym10x") == "\\font\\z=msym10x"
    assert _MSYM.action["params"]["exts"] == [".tex", ".sty", ".cls"]


def test_cs_table_and_entry_and_when_widened() -> None:
    """B2: and 键 polyfill 为无条件 \\def (非 providecommand 守卫形) +
    when.any 收 cls_unsupported (payload=类拒 cs 名)。"""
    assert _CSTABLE["and"]["polyfill"] == "\n\\def\\and{\\par}"
    # 守卫形一律不许可 —— 类载 \\let\\and\\frontmatter@and 会骗过
    assert "\\providecommand" not in _CSTABLE["and"]["polyfill"]
    assert "\\ifdefined" not in _CSTABLE["and"]["polyfill"]
    cats = {w["category"] for w in _CS.when["any"]}
    assert "cls_unsupported" in cats
    assert "undefined_cs" in cats


def test_mathbf_arm_gate() -> None:
    """B3 门: warn_missing_char (misschar 派发族) + 行首 ams/bm 装载。"""
    cats = {w["category"] for w in _MATHBF.when["any"]}
    assert "warn_missing_char" in cats
    assert actions._is_misschar_rule(_MATHBF)  # noqa: SLF001
    pat = _MATHBF.condition["source_contains"]
    for src in (
        "\\usepackage{amsmath}\n",
        "  \\usepackage{mathtools}\n",
        "\\usepackage[utf8]{inputenc,bm}\n",
        "\\RequirePackage{amsbsy}\n",
    ):
        assert regex.search(pat, src), src
    for src in (
        "% \\usepackage{amsmath}\n",
        "\\usepackage{graphicx}\n",
        "x \\usepackage{amsmath}\n",  # 非行首
    ):
        assert regex.search(pat, src) is None, src


def test_mathbf_rewrite() -> None:
    """B3 改写: 花括形/松散形并收, 多 token 参与前缀 cs 不动。"""
    cases = {
        "$\\mathbf{\\Lambda} x$": "$\\ensuremath{\\boldsymbol{\\Lambda}} x$",
        "{\\mathbf \\Lambda}": "{\\ensuremath{\\boldsymbol{\\Lambda}}}",
        "\\mathbf{\\Sigma}+\\mathbf\\Pi": "\\ensuremath{\\boldsymbol{\\Sigma}}+\\ensuremath{\\boldsymbol{\\Pi}}",
        "\\mathbf{\\Lambda X}": "\\mathbf{\\Lambda X}",
        "\\mathbf{\\Lambdabar}": "\\mathbf{\\Lambdabar}",
    }
    for src, want in cases.items():
        assert _sub(_MATHBF, src) == want, src


def test_hanja_arm_gate() -> None:
    """B4 门: warn_missing_char 族 + 行首 kotex/xetexko 装载。"""
    assert actions._is_misschar_rule(_HANJA)  # noqa: SLF001
    pat = _HANJA.condition["source_contains"]
    assert regex.search(pat, "\\usepackage{kotex}\n")
    assert regex.search(pat, "\\usepackage[hangul]{xetexko}\n")
    assert regex.search(pat, "  \\RequirePackage{kotex}\n")
    assert regex.search(pat, "\\usepackage{amsmath}\n") is None
    assert regex.search(pat, "% \\usepackage{kotex}\n") is None


def test_hanja_inject_idempotent() -> None:
    """B4 注入: 活 \\begin{document} 前插入路由件; 注释锚不吃; 复火幂等。"""
    src = (
        "\\documentclass{article}\n"
        "\\usepackage{kotex}\n"
        "% \\begin{document}\n"
        "\\begin{document}\nx\n"
    )
    out = _sub(_HANJA, src)
    assert out.count("\\setmainhanjafont{FandolSong-Regular.otf}") == 1
    assert "\\ifdefined\\setmainhanjafont" in out
    assert "\\IfFontExistsTF{FandolSong-Regular.otf}" in out
    assert "\\def\\txlatehanjaroute{}\n\\begin{document}" in out
    # 注释行锚未动 —— 注入只在活锚前
    assert out.index("% \\begin{document}") < out.index("\\ifdefined\\setmainhanjafont")
    assert _sub(_HANJA, out) == out  # 代码标记幂等


def test_hanja_masked_surface_skips_verbatim() -> None:
    """B4 masked 面: verbatim 内 \\begin{document} 锚不可见不改写。"""
    src = (
        "\\documentclass{article}\n"
        "\\usepackage{kotex}\n"
        "\\begin{verbatim}\n\\begin{document}\n\\end{verbatim}\n"
        "\\begin{document}\nx\n"
    )
    out = _sub(_HANJA, src)
    assert out.count("\\ifdefined\\setmainhanjafont") == 1
    # verbatim 块内字面原样
    assert "\\begin{verbatim}\n\\begin{document}\n\\end{verbatim}" in out
