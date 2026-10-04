"""CJK_MATH_FALLBACK / CJK_FIRST_USE_WARMUP 回归测试（CJK 丢字兜底双机制）。

机理一（数学兜底）：xeCJK 的 ``\\XeTeXinterchartoks`` 只在水平列触发，**数学模式
不触发**——译文落进 ``$..$``/``\\beq``/下标/``\\boldmath`` 头标（loop1 misschar
实证标记：ec-lmss12、rm-lmr8、cmr10/7、ptmr8t 全是数学族 TFM）即在数学字体
里丢字形。本块把 CJK 码位 ``\\Umathcode`` 重映为 ordinary 符号，指向
FandolSong 直载的 ``texlatecjk`` 符号字体（normal+bold 双 math version）。

机理二（首用 warmup）：xeCJK 的 ``__xeCJK_select_font:`` 惰性启用（初值
``\\prg_do_nothing:``）；elsart frontmatter 用 ``\\vbox`` 捕获组先于启用点
排版 CJK → 整篇丢字（1003.5459 实测 5485 个）。``\\AtBeginDocument`` 排一个
即弃 CJK hbox 即完成机制级初始化。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.inject import (
    CJK_FIRST_USE_WARMUP,
    CJK_MATH_FALLBACK,
    FLOAT_SIZING,
    TIE_ACCENT_FIX,
    _float_sized,
    inject_cjk,
)

DOC = (
    "\\documentclass{article}\n"
    "\\usepackage{amsmath}\n"
    "\\begin{document}\n"
    "Text 这是译文 $x_这是译文^{这是译文}$.\n"
    "\\[y = 这是译文 + \\int_这是译文\\]\n"
    "{\\boldmath $这是译文$}\n"
    "\\end{document}\n"
)

#: 双模注入钉共用的最小文档壳。
_MINIMAL_DOC = "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"


@pytest.mark.parametrize("mode", ["ctex", "xecjk"])
def test_math_fallback_injected_both_modes(mode: str) -> None:
    """ctex 与 xecjk 两条注入路径都带数学兜底块。"""
    out, info = inject_cjk(_MINIMAL_DOC, mode=mode)
    assert info["status"] == "injected"
    assert "\\DeclareSymbolFont{texlatecjk}" in out
    assert "\\Umathcode" in out
    assert "FandolSong-Regular.otf" in out


def test_math_fallback_engine_guard() -> None:
    """兜底块整体包在 \\ifdefined\\Umathcode 内——pdftex 等无此原语的引擎整块跳过。"""
    body = CJK_MATH_FALLBACK
    assert "\\ifdefined\\Umathcode" in body
    assert body.index("\\ifdefined\\Umathcode") < body.index("\\DeclareSymbolFont")


def test_math_fallback_mathgroup_budget_guard() -> None:
    r"""``\DeclareSymbolFont`` 预算闸 ``\count18<15``（先 +1 后查 ``<16`` →
    剩 1 空位须拒申；``<16`` 旧闸放行反而触发 ``Too many symbol fonts``
    + ``texlatecjk`` 未定义级联——2203.00075 stix 后 count18=15 实证）。"""
    body = CJK_MATH_FALLBACK
    assert body.count(r"\ifnum\count18<15") == body.count("\\DeclareSymbolFont{texlate")
    assert r"\ifnum\count18<16" not in body


def test_math_fallback_skipped_when_cjk_present() -> None:
    """文档自带 CJK 支持 → status=already → 不注兜底块（不碰文档自有字体设定）。"""
    tex = "\\documentclass{ctexart}\n\\begin{document}\nx\\end{document}\n"
    out, info = inject_cjk(tex)
    assert info["status"] == "already"
    assert "texlatecjk" not in out
    assert CJK_FIRST_USE_WARMUP.strip() not in out


@pytest.mark.parametrize("mode", ["ctex", "xecjk"])
def test_first_use_warmup_injected_both_modes(mode: str) -> None:
    """两条注入路径都带首用 warmup，且注册点在 CJK 宏包加载之后（启用点序正确）。"""
    anchors = {
        "ctex": r"\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}",
        "xecjk": r"\setCJKmainfont",
    }
    out, info = inject_cjk(_MINIMAL_DOC, mode=mode)
    assert info["status"] == "injected"
    assert CJK_FIRST_USE_WARMUP.strip() in out
    assert "\\AtBeginDocument{\\setbox0=\\hbox{字}}" in out
    assert out.index(anchors[mode]) < out.index(CJK_FIRST_USE_WARMUP.strip())


def test_first_use_warmup_engine_guard() -> None:
    """warmup 仅 XeTeX 挂载——pdftex 下裸 CJK 字符需 CJK 环境，直排反受其害。"""
    assert "\\ifdefined\\XeTeXversion" in CJK_FIRST_USE_WARMUP
    assert CJK_FIRST_USE_WARMUP.index("\\ifdefined\\XeTeXversion") < (
        CJK_FIRST_USE_WARMUP.index("\\AtBeginDocument")
    )


def test_math_fallback_covers_unified_ranges() -> None:
    """兜底码位覆盖 CJK 统一表意文字主段 + ext-A + 部首补充 (2E80-2FDF)
    + 兼容/标点/假名/全角 + astral ext-B(20000-2A6DF) 与 ext-C..F 段
    (2A700-2EBEF)——``\\TeXlate@mathmap\\symtexlatecjk`` 九段全钉。"""
    for rng in (
        "4E00-9FFF",
        "3400-4DBF",
        "3000-303F",
        "FF00-FFEF",
        "3040-30FF",
        "F900-FAFF",
        "2E80-2FDF",
        "20000-2A6DF",
        "2A700-2EBEF",
    ):
        assert rng in CJK_MATH_FALLBACK


@pytest.mark.parametrize("mode", ["ctex", "xecjk"])
def test_tie_accent_fix_injected_both_modes(mode: str) -> None:
    r"""``\t`` TU 声明随两条注入路径落盘，包在 ``\UnicodeEncodingName`` 门内。"""
    assert "\\ifdefined\\UnicodeEncodingName" in TIE_ACCENT_FIX
    assert "\\DeclareUnicodeAccent{\\t}" in TIE_ACCENT_FIX
    out, info = inject_cjk(_MINIMAL_DOC, mode=mode)
    assert info["status"] == "injected"
    assert "\\DeclareUnicodeAccent{\\t}" in out


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_math_fallback_real_compile(tmp_path: Path) -> None:
    """真编译验证：注入产物里数学内 CJK 零缺字；剥掉兜底块的对照则缺字。

    对照臂证明缺字确由本块兜住，而非文档本身不缺。
    """
    out, info = inject_cjk(DOC, mode="ctex")
    assert info["status"] == "injected"
    xelatex = shutil.which("xelatex")
    assert xelatex is not None

    def _compile(name: str, tex: str) -> str:
        p = tmp_path / f"{name}.tex"
        p.write_text(tex, encoding="utf-8")
        subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
            [xelatex, "-interaction=nonstopmode", p.name],
            cwd=tmp_path,
            capture_output=True,
            timeout=120,
            check=False,
        )
        return (tmp_path / f"{name}.log").read_text(encoding="utf-8", errors="replace")

    log = _compile("with_fallback", out)
    n_missing = len(re.findall(r"Missing character", log))
    assert n_missing == 0, f"注入后仍有 {n_missing} 个缺字"

    ctl = out.replace(CJK_MATH_FALLBACK, "")
    assert "texlatecjk" not in ctl
    ctl_log = _compile("ctl_nofallback", ctl)
    assert len(re.findall(r"Missing character", ctl_log)) > 0


BD_DEF_DOC = (
    "\\documentclass[10pt]{article}\n"
    "\\let\\la=\\label \\let\\ci=\\cite\n"
    "\\def\\nn{\\nonumber} \\def\\bd{\\begin{document}} \\def\\ed{\\end{document}}\n"
    "\\def\\ds{\\documentstyle}\n"
    "\\begin{document}\n"
    "x $y_1$\n"
    "\\end{document}\n"
)

BD_NEWCOMMAND_DOC = (
    "\\documentclass{svjour2}\n"
    "\\newcommand {\\bd}{\\begin{document}}\n"
    "\\begin{document}\n"
    "x\n"
    "\\end{document}\n"
)


def test_bd_shorthand_def_not_split() -> None:
    r"""``\def\bd{\begin{document}}`` 简写形态：宏体内 bd 字样不是注入锚。

    hep-th/0307203、hep-th/9910011 实案——裸 finditer 把数学兜底块（含
    ``#1`` 参数定义）楔进 ``\def\bd{`` 与 ``\begin{document}}`` 之间，
    "Illegal parameter number in definition of \bd" 连级 ``undefined_cs``。
    """
    out, info = inject_cjk(BD_DEF_DOC, mode="ctex")
    assert info["status"] == "injected"
    needle = (
        "\\def\\nn{\\nonumber} \\def\\bd{\\begin{document}} \\def\\ed{\\end{document}}"
    )
    assert needle in out
    fb = out.index("\\DeclareSymbolFont{texlatecjk}")
    assert out.index(needle) < fb < out.index("\\begin{document}\nx")
    assert "multi-bd idempotent" not in out


def test_bd_shorthand_newcommand_not_split() -> None:
    r"""``\newcommand{\bd}{\begin{document}}`` 同构（0905.0876）：锚点仍只认 depth-0 bd。"""
    out, info = inject_cjk(BD_NEWCOMMAND_DOC, mode="ctex")
    assert info["status"] == "injected"
    needle = "\\newcommand {\\bd}{\\begin{document}}"
    assert needle in out
    fb = out.index("\\DeclareSymbolFont{texlatecjk}")
    assert out.index(needle) < fb < out.index("\\begin{document}\nx")
    assert "multi-bd idempotent" not in out


def test_float_table_fitting_skip_indef_bd() -> None:
    r"""FLOAT_SIZING：不楔进 ``\def`` 宏体，落真 bd 前（TABLE_FITTING 0930 拔除）。"""
    for block, inject in ((FLOAT_SIZING, _float_sized),):
        out = inject(BD_DEF_DOC)
        assert block.strip() in out
        needle = "\\def\\bd{\\begin{document}}"
        assert (
            out.index(needle)
            < out.index(block.strip())
            < out.index("\\begin{document}\nx")
        )
