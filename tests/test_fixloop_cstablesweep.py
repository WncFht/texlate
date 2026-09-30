"""cstablesweep 批 (task #227) —— 19 firedunfixed undefined_cs singles 直改单测。

95-targeted.yaml cs_targeted_fix(165) 的 ``params.cs_table`` 新增 15 行 +
``epstopdfDeclareGraphicsRule`` 扩行; ``pdfinclusioncopyfonts`` 进
PDFTEX_PRIMS + _PRIM_COUNTISH 双表; diagrams 双子 stub 补 Onto/Into
垂直对角 16 箭头。``\\@nil`` (1706.00225, vendored aa.cls 选项机件内部件)
判 stub-fidelity 道主, 本表拒收 —— 裸 ``\\def\\@nil{}`` 会腐 list 哨兵。

钉死的机制要点:

- ``endproof`` 必走 ``\\ifdefined\\X\\else\\def\\X{..}\\fi`` 守卫形:
  ``\\@ifdefinable`` 恒拒 ``end*`` 名 (``\\@carcube`` 首 3 字符=end),
  ``\\providecommand{\\endproof}`` 产 already_def r1→r2 死循环 (W151 实证)。
- ``Z`` 行 cs_map ``Zö→Z`` (xelatex 下 ö 是 letter, ``\\Zö`` 是整 cs) +
  ``\\AtBeginDocument`` 延迟 provide —— docclass 缝直注会把稿自
  ``\\newcommand{\\Z}`` 站点顶成 already_def。
- ``Bbb`` cs_map 词边界下 ``\\Bbbk`` 不误伤。
- ``epstopdf``/``transparent`` 真包在 xelatex 加载即 abort →
  usepackage 臂独力不治, polyfill 兜底才是真修。
"""

from pathlib import Path

from _fixloopkit import DOC, EngStub, mk_ctx, rule

import texlate.compile.fixloop as _fixloop_mod
from texlate.compile.fixloop._builtins_common import PDFTEX_PRIMS
from texlate.compile.fixloop._builtins_shim import _PRIM_COUNTISH
from texlate.compile.fixloop.builtins import TRANSFORM_FNS

_TARGETED = TRANSFORM_FNS["cs_targeted_fix"]
_PARAMS = rule("cs_targeted_fix").action["params"]
_CSTABLE = _PARAMS["cs_table"]

_STUB_DIR = Path(_fixloop_mod.__file__).parent / "vendor" / "stubs"


class _EngStub(EngStub):
    """probe 恒命中 / install 恒成 —— usepackage 臂走通支路（kit EngStub 恒 miss 的反语义）。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        return f"/texmf/{fname}"

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return True


def _proj(tmp_path: Path, tex: str) -> None:
    (tmp_path / "main.tex").write_text(tex, encoding="utf-8")


def _fix(tmp_path: Path, cs: str) -> tuple[bool, str]:
    return _TARGETED(mk_ctx(tmp_path), _EngStub(), cs, _PARAMS)


#: 本批落表的 cs → 期望 spec 键 (epstopdf 为扩行, 非新行)。
_EXPECTED_SPECS = {
    "endproof": {"polyfill"},
    "tikzset": {"usepackage", "polyfill"},
    "PACS": {"polyfill"},
    "decimalcolnumbers": {"polyfill"},
    "restartappendixnumbering": {"polyfill"},
    "gridline": {"usepackage", "polyfill"},
    "upperandlowercase": {"polyfill"},
    "tfrac": {"usepackage", "polyfill"},
    "Z": {"usepackage", "cs_map", "polyfill"},
    "msg": {"cs_map"},
    "transparent": {"polyfill"},
    "hangcaption": {"polyfill"},
    "htmladdnormallink": {"polyfill"},
    "Line": {"usepackage"},
    "Bbb": {"usepackage", "cs_map"},
    "epstopdfDeclareGraphicsRule": {"usepackage", "polyfill"},
}


def test_shipped_table_entries_present() -> None:
    """16 cs 全在 yaml cs_table, spec 键形与判决一致。"""
    for cs, keys in _EXPECTED_SPECS.items():
        assert cs in _CSTABLE, cs
        assert keys <= set(_CSTABLE[cs]), (cs, _CSTABLE[cs])


def test_atnil_not_tabled() -> None:
    """``\\@nil`` 延期 (aa.cls 内部件) —— 盲 polyfill 腐哨兵, 表内拒收。"""
    assert "@nil" not in _CSTABLE


def test_polyfill_bodies_carry_nl_prefix() -> None:
    """全 polyfill 带 ``\\n`` 前缀 —— 逃 docclass 行尾 % 吞缝 (1404.0346)。"""
    for cs, keys in _EXPECTED_SPECS.items():
        body = _CSTABLE[cs].get("polyfill")
        if "polyfill" in keys:
            assert body, cs
            assert body.startswith("\n"), cs


def test_endproof_guard_form_not_providecommand(tmp_path: Path) -> None:
    """W151: ``end*`` 名走 ``\\ifdefined..\\else\\def`` 守卫, 非 providecommand。"""
    _proj(tmp_path, DOC)
    ok, note = _fix(tmp_path, "endproof")
    assert ok, note
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\endproof\\else\\def\\endproof" in text
    assert "\\providecommand{\\endproof}" not in text


def test_z_csmap_typo_plus_deferred_provide(tmp_path: Path) -> None:
    """``\\Zö`` 拆笔误; ``\\Z`` provide 延 AtBeginDocument 不顶稿自义。"""
    tex = (
        "\\documentclass{article}\n"
        "\\newcommand{\\Z}{\\mathbb{Z}}\n"
        "\\begin{document}\n$\\Zö$\n\\end{document}\n"
    )
    _proj(tmp_path, tex)
    ok, _ = _fix(tmp_path, "Z")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\Zö" not in text
    assert "$\\Z$" in text
    assert "\\RequirePackage{amssymb}" in text
    assert "\\AtBeginDocument{\\providecommand{\\Z}" in text
    # 稿自 \newcommand{\Z} 原样存活 (provide 延迟, 站点不 already_def)。
    assert "\\newcommand{\\Z}{\\mathbb{Z}}" in text


def test_msg_expl3_csmap(tmp_path: Path) -> None:
    """``\\msg_term:n`` → ``\\iow_term:n``: ``:n`` 属 cs 名, 词界在 m 后。"""
    tex = DOC.replace("x", "\\ExplSyntaxOn\n\\msg_term:n{hi}\n\\ExplSyntaxOff")
    _proj(tmp_path, tex)
    ok, _ = _fix(tmp_path, "msg")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\iow_term:n{hi}" in text
    assert "\\msg_term" not in text


def test_bbb_csmap_spares_bbbk(tmp_path: Path) -> None:
    """``\\Bbb{R}`` → ``\\mathbb{R}``; 词界定 ``\\Bbbk`` 不误伤。"""
    tex = DOC.replace("x", "$\\Bbb{R}$ and $\\Bbbk$")
    _proj(tmp_path, tex)
    ok, _ = _fix(tmp_path, "Bbb")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "$\\mathbb{R}$" in text
    assert "$\\Bbbk$" in text
    assert "\\RequirePackage{amssymb}" in text


def test_line_usepackage_pict2e(tmp_path: Path) -> None:
    """axodraw ``\\Line`` → pict2e 原生同签名宏, 装真包臂。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "Line")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\RequirePackage{pict2e}" in text
    assert text.index("\\RequirePackage{pict2e}") > text.index("\\documentclass")


def test_epstopdf_extended_arm(tmp_path: Path) -> None:
    """epstopdf xelatex abort → usepackage + 3-cs polyfill 双臂。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "epstopdfDeclareGraphicsRule")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\RequirePackage{epstopdf}" in text
    assert "\\providecommand{\\epstopdfDeclareGraphicsRule}[4]{}" in text
    assert "\\providecommand{\\AppendGraphicsExtensions}[1]{}" in text
    assert "\\providecommand{\\PrependGraphicsExtensions}[1]{}" in text


def test_transparent_gobble(tmp_path: Path) -> None:
    """transparent xelatex abort → 吞参 noop (装包臂不可达)。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "transparent")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand{\\transparent}[1]{}" in text
    assert "\\usepackage{transparent}" not in text


def test_tfrac_dual_arm(tmp_path: Path) -> None:
    """amsmath 装包为主 + ``\\textstyle\\frac`` provide 兜底。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "tfrac")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\RequirePackage{amsmath}" in text
    assert "\\providecommand{\\tfrac}[2]" in text


def test_hangcaption_dual_form(tmp_path: Path) -> None:
    """``\\hangcaption[short]{long}`` 可选首参双形。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "hangcaption")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand{\\hangcaption}[2][]" in text


def test_htmladdnormallink_href_or_text(tmp_path: Path) -> None:
    """latex2html 宏 → ``\\href`` 在场真链, 缺席落锚文本。"""
    _proj(tmp_path, DOC)
    ok, _ = _fix(tmp_path, "htmladdnormallink")
    assert ok
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\providecommand{\\htmladdnormallink}[2]" in text
    assert "\\ifdefined\\href" in text


def test_refire_idempotent(tmp_path: Path) -> None:
    """二轮重火: usepackage 判重 + polyfill snippet 判重 → 文件幂等;
    臂 probe 注记保 done 非空 → 返回 True 不落 guess (pgffix 升级后
    ``tikzset`` 挂 ``usepackage: tikz`` 臂, 与 letltxmacro 同语义)。"""
    _proj(tmp_path, DOC)
    ok1, _ = _fix(tmp_path, "tikzset")
    assert ok1
    ok2, _ = _fix(tmp_path, "tikzset")
    assert ok2
    text = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert text.count("\\usetikzlibrary{arrows,positioning,shapes}") == 1
    assert text.count("% fixloop: cs-fix") == 1


def test_pdfinclusioncopyfonts_both_tables() -> None:
    """2403.15085 ``\\prim=1`` 写形+读形 → 原语表与 countish 表双收。"""
    assert "pdfinclusioncopyfonts" in PDFTEX_PRIMS
    assert "pdfinclusioncopyfonts" in _PRIM_COUNTISH


def test_diagrams_stub_twins_onto_into_family() -> None:
    """Onto/Into 垂直+对角 16 cs 双子点镜像 (math/9901064)。"""
    names = [
        f"{d}{k}"
        for d in ("u", "d", "v", "ru", "rd", "lu", "ld")
        for k in ("Onto", "Into")
    ] + ["hOnto", "hInto"]
    for stem in ("diagrams.sty", "diagrams.tex"):
        text = (_STUB_DIR / stem).read_text(encoding="utf-8")
        for cs in names:
            assert f"\\providecommand{{\\{cs}}}" in text, (stem, cs)
