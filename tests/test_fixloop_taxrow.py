r"""taxrow 56-行签面 —— taxcen 普查 (333 other|None → 224 实缺 → 79 簇 →
56 提案覆盖 223/224) 落 ``10-taxonomy.yaml`` 的逐行钉测。

行分两层: **37 全新类 id** (pkg/class 自报硬错、内核装载语义、数值/数学
引擎错) 与 **19 近失扩写** (既有行臂补/措辞并收——missing_tfm 无规格形、
runaway_scan ``_:`` cs 名、invalid_in_math 花括号参、undefined_color
model 变体、key_unknown pgfkeys/xkeyval 两措辞、missing_graphic noBB/
open-fail、missing_file 裸名兜底、pkg_version_skew need-version 族、
pkg_obsolete 选项级、fontspec 裸头兜底)。每行至少一钉, 签名一律取
``tmp/lane-taxcen/clusters_raw.json`` verbatim 实证头 (非模板改写)。

序约束钉三处: use_post missing_graphic (errhelp 出 ctx8 右缘) vs 同形
无证据 → missing_file 裸名臂; use_pre missing_file (``^No file X.fd``
探测行) vs 裸 NFSS → nfss_setup; key_unknown 臂 ``payload_group`` 拆除
后首非空组语义 (l3keys→组1 / pgfkeys→组2 / xkeyval→组3)。
"""

from functools import lru_cache
from typing import Any

import pytest

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.logparse import parse_text


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _warn() -> list[dict[str, Any]]:
    return _rs().warn_patterns


def classify(text: str) -> tuple[str | None, str | None]:
    return _rs().taxonomy.classify(parse_text(text, _warn()))


def classify_errs(text: str) -> list[tuple[str | None, str | None]]:
    return _rs().taxonomy.classify_errs(parse_text(text, _warn()))


def _log(head: str) -> str:
    """最小 ``! <head>`` 单错块 + ``l.N`` 回显行。"""
    return f"! {head}\nl.1 x\n"


# ── 全新类 id (44 行, clusters_raw verbatim heads) ──
_HEAD_PINS: list[tuple[str, str, str | None]] = [
    # (head, cat, payload) — 每行一条 verbatim 实证签
    (
        "Package natbib Error: Bibliography not compatible with author-year citations.",
        "bib_compat",
        "author-year",
    ),
    (
        "Package natbib Error: Bibliography not compatible with numbers citations.",
        "bib_compat",
        "numbers",
    ),
    (
        "LaTeX Error: Unknown option ` compress' for package `natbib'.",
        "unknown_option",
        "compress",
    ),
    (
        "LaTeX Error: Unknown option `classicReIm' for package `kpfonts-otf'.",
        "unknown_option",
        "classicReIm",
    ),
    (
        "LaTeX Error: Unknown option `keeplastbox' for package `flushend'.",
        "unknown_option",
        "keeplastbox",
    ),
    (
        # 包名无引号变体 (siunitx/datatool-base/xcolor 实证同形)
        "LaTeX Error: Unknown option 'load' for package siunitx.",
        "unknown_option",
        "load",
    ),
    (
        "LaTeX Error: Unknown option 'hiresbb' for package xcolor.",
        "unknown_option",
        "hiresbb",
    ),
    (
        "Package breakurl Error: The breakurl depends on hyperref package.",
        "pkg_requires",
        "hyperref",
    ),
    (
        "Package bxcjkjatype Error: The engine in use is not supported.",
        "pkg_engine",
        "bxcjkjatype",
    ),
    (
        "Package bmpsize Error: You need pdfTeX 1.30.0 or newer.",
        "pkg_engine",
        "bmpsize",
    ),
    (
        "Package graphics Error: Division by 0.",
        "graphics_div",
        "0",
    ),
    (
        (
            "Class acmart Error: An attempt to redefine \\baselinestretch "
            "detected. Please do not do this for ACM submissions!."
        ),
        "cls_redefine_guard",
        "\\baselinestretch",
    ),
    (
        "Class revtex4-2 Error: \\and is not supported.",
        "cls_unsupported",
        "\\and",
    ),
    (
        "Class acmart Error: No country present for an affiliation.",
        "cls_affil",
        None,
    ),
    (
        "Class scrartcl Error: undefined old font command `\\bf'.",
        "oldfont_cmd",
        "\\bf",
    ),
    (
        "Package calc Error: `\\let ' invalid at this point.",
        "calc_err",
        "\\let ",
    ),
    (
        "Package keyval Error: Zalta undefined.",
        "keyval_undef",
        "Zalta",
    ),
    (
        "Package keyval Error: rheight undefined.",
        "keyval_undef",
        "rheight",
    ),
    (
        # zh-leak 槽: keyval 槽名译文污染同签归桶
        "Package keyval Error: 这是译文 undefined.",
        "keyval_undef",
        "这是译文",
    ),
    (
        "Package etoolbox Error: Toggle '这是译文' undefined.",
        "etoolbox_toggle",
        "这是译文",
    ),
    (
        "Package pgf Error: No shape named `tau1' is known.",
        "pgf_shape",
        "tau1",
    ),
    (
        "Package newunicodechar Error: Invalid argument.",
        "newunicodechar_arg",
        None,
    ),
    (
        (
            "Package standalone Error: Shell escape needed to create graphic! "
            "Use the '-shell-escape' option.."
        ),
        "standalone_shell",
        None,
    ),
    (
        "\\@combinedblfloats could not be patched.",
        "patch_fail",
        "\\@combinedblfloats",
    ),
    (
        "Package biblatex Error: Patching \\MakeUppercase failed.",
        "patch_fail",
        "\\MakeUppercase",
    ),
    (
        # 裸形无 cs → payload None (首个非空组语义)
        "patch failed.",
        "patch_fail",
        None,
    ),
    (
        "Package microtype Error: Disabling ligatures of a font is only possible",
        "microtype_pdftex",
        None,
    ),
    (
        "Package microtype Error: The kerning feature only works with pdftex 1.40",
        "microtype_pdftex",
        None,
    ),
    (
        "Package microtype Error: Font expansion does not work with xetex.",
        "microtype_pdftex",
        None,
    ),
    (
        "Package siunitx Error: Invalid number '0.2 x 0.2 x 0.5'.",
        "siunitx_err",
        None,
    ),
    (
        "Package siunitx Error: Found prefix part with no unit.",
        "siunitx_err",
        None,
    ),
    (
        "Package siunitx Error: Package 'units' incompatible.",
        "siunitx_err",
        None,
    ),
    (
        "Package acro Error: You've requested acronym `这是译文' on line 445 but you",
        "acro_err",
        None,
    ),
    (
        (
            "Package pgfplots Error: \\pgfplotslistfront\\ from "
            "\\pgfplotstable@colnames\\ although list is EMPTY."
        ),
        "pgfplots_err",
        None,
    ),
    (
        (
            "Package pgfplots Error: Could not read table file 'bicycle_results.csv' "
            "in 'search path=.'. In case you intended to provide inline"
        ),
        "pgfplots_err",
        None,
    ),
    (
        "Package amsmath Error: Erroneous nesting of equation structures;",
        "amsmath_err",
        None,
    ),
    (
        "Package amsmath Error: Old form `\\cases' should be \\begin{cases}.",
        "amsmath_err",
        None,
    ),
    (
        "LaTeX hooks Error: Generic hooks cannot be added to '\\@begintheorem'.",
        "latex_hooks",
        None,
    ),
    (
        "LaTeX hooks Error: Sorting rule for 'begindocument' hook applied too late.",
        "latex_hooks",
        None,
    ),
    (
        "LaTeX Error: No counter 'theorem' defined.",
        "counter_undef",
        "theorem",
    ),
    (
        "LaTeX Error: No counter '这是译文' defined.",
        "counter_undef",
        "这是译文",
    ),
    (
        "LaTeX Error: The font size command \\normalsize is not defined:",
        "fontsize_undef",
        "\\normalsize",
    ),
    (
        "LaTeX Error: Too many symbol fonts declared.",
        "symbol_font",
        None,
    ),
    (
        "LaTeX Error: Symbol font `gns@font' not defined.",
        "symbol_font",
        "gns@font",
    ),
    (
        "LaTeX Error: Symbol font `gns@font' is not defined.",
        "symbol_font",
        "gns@font",
    ),
    (
        # 裸 NFSS 中止 (无 ``^No file X.fd`` 探测行 → use_pre 臂够不着)
        "LaTeX Error: This NFSS system isn't set up properly.",
        "nfss_setup",
        None,
    ),
    ("Corrupted NFSS tables.", "nfss_corrupt", None),
    (
        "LaTeX Error: Loading a class or package in a group.",
        "grouped_load",
        None,
    ),
    (
        "LaTeX Error: Can be used only in preamble.",
        "preamble_only",
        None,
    ),
    (
        "LaTeX Error: \\RequirePackage or \\LoadClass in Options Section.",
        "options_section",
        None,
    ),
    (
        "LaTeX Error: \\usepackage before \\documentclass.",
        "pkg_before_docclass",
        None,
    ),
    ("LaTeX Error: Too deeply nested.", "nested_depth", None),
    (
        "LaTeX Error: \\verb ended by end of line.",
        "cs_eol",
        "\\verb",
    ),
    (
        "Use of \\0 doesn't match its definition.",
        "cs_mismatch",
        "\\0",
    ),
    (
        "Use of \\@citex doesn't match its definition.",
        "cs_mismatch",
        "\\@citex",
    ),
    (
        "Use of \\b doesn't match its definition.",
        "cs_mismatch",
        "\\b",
    ),
    (
        # `\<space>` 空格 cs 双空格实证形 —— 提案 `\\\S` 漏此支, 补 `\\ `
        "Use of \\  doesn't match its definition.",
        "cs_mismatch",
        "\\ ",
    ),
    (
        "You can't use `\\spacefactor' in vertical mode.",
        "vmode_prim",
        "\\spacefactor",
    ),
    (
        "You can't use `\\unskip' in vertical mode.",
        "vmode_prim",
        "\\unskip",
    ),
    (
        "You can't use `\\eqno' in math mode.",
        "vmode_prim",
        "\\eqno",
    ),
    (
        "You can't use `\\halign' in math mode.",
        "vmode_prim",
        "\\halign",
    ),
    ("LaTeX Error: Not allowed in LR mode.", "lr_mode", None),
    (
        "! Incomplete \\iffalse; all text was ignored after line 275.",
        "incomplete_if",
        "\\iffalse",
    ),
    ("Too many }'s.", "extra_brace", None),
    ("Display math should end with $$.", "display_math_close", None),
    ("Dimension too large.", "dim_overflow", None),
    ("Arithmetic overflow.", "arith_overflow", None),
    (
        "Output loop---100 consecutive dead cycles.",
        "output_loop",
        None,
    ),
    (
        "Extended mathchar used as mathchar (67145689).",
        "mathchar_ext",
        None,
    ),
    (
        (
            "Xy-pic error: Forms @/.../, @(...), and @`{...}, only available "
            "when curve extension loaded."
        ),
        "xypic_err",
        None,
    ),
    ("A <box> was supposed to be here.", "xypic_err", None),
]


@pytest.mark.parametrize(
    ("head", "cat", "pay"),
    [pytest.param(h, c, p, id=f"{c}:{h[:36]}") for h, c, p in _HEAD_PINS],
)
def test_new_row_head(head: str, cat: str, pay: str | None) -> None:
    assert classify(_log(head)) == (cat, pay)


# ── 近失扩写: 既有行新措辞/新参形 ──


def test_missing_tfm_no_spec_arm() -> None:
    # `Font \cs=name not loadable` 无 `at Npt|scaled N` 规格段 → 新臂;
    # 规格臂在前先签, 本臂只见无规格残形
    assert classify(
        _log(
            "Font \\NOTEN=musix13 not loadable: Metric (TFM) file or "
            "installed font not found."
        )
    ) == ("missing_tfm", "musix13")


def test_missing_tfm_spec_arms_regression() -> None:
    # at-Npt 与 scaled-N 规格形仍走前臂 (评估序不被无规格臂截)
    assert classify("! Font \\X=cmr10 at 10pt not loadable.\nl.5 x\n") == (
        "missing_tfm",
        "cmr10",
    )
    assert classify("! Font \\NOTEN=musix13 scaled 1200 not loadable.\nl.5 x\n") == (
        "missing_tfm",
        "musix13",
    )


def test_runaway_scan_expl3_cs_underscore_colon() -> None:
    # expl3 `\__siunitx_quantity_parsed_aux:w` —— cs 名类补 `_:`
    assert classify(
        _log("File ended while scanning use of \\__siunitx_quantity_parsed_aux:w.")
    ) == ("runaway_scan", "\\__siunitx_quantity_parsed_aux:w")


def test_runaway_scan_at_cs_regression() -> None:
    assert classify(_log("File ended while scanning use of \\@foo.")) == (
        "runaway_scan",
        "\\@foo",
    )


def test_invalid_in_math_braced_arg() -> None:
    # `Command \end{lemma} invalid` —— 花括号参夹 cs 与 ` invalid` 之间
    assert classify(
        _log("LaTeX Error: Command \\end{lemma} invalid in math mode.")
    ) == ("invalid_in_math", "end")


def test_invalid_in_math_plain_regression() -> None:
    assert classify(_log("LaTeX Error: Command \\cite invalid in math mode.")) == (
        "invalid_in_math",
        "cite",
    )


def test_undefined_color_model_variant() -> None:
    assert classify(
        _log("Package xcolor Error: Undefined color model `这是译文'.")
    ) == ("undefined_color", "这是译文")


def test_undefined_color_plain_regression() -> None:
    assert classify(_log("LaTeX Error: Undefined color `blue'.")) == (
        "undefined_color",
        "blue",
    )


def test_key_unknown_l3keys_regression() -> None:
    # payload_group 拆除后组1 仍先签 (首非空组语义)
    assert classify(
        _log("The key 'acro/这是译文' is unknown and is being ignored.")
    ) == ("key_unknown", "acro/这是译文")


def test_key_unknown_pgfkeys_variant() -> None:
    # pgfkeys `I do not know the key 'X'` —— 键路径带空格 `[^']+` 全捕 (组2)
    assert classify(
        _log(
            "Package pgfkeys Error: I do not know the key '/msc/top head dist', "
            "to which you passed '0', and I am going to ignore it. Perhaps y"
        )
    ) == ("key_unknown", "/msc/top head dist")


def test_key_unknown_xkeyval_variant() -> None:
    # xkeyval `` `X' undefined in families `Y' `` (组3)
    assert classify(
        _log("Package xkeyval Error: `这是译文' undefined in families `Grot'.")
    ) == ("key_unknown", "这是译文")


def test_missing_graphic_nobb_variant() -> None:
    assert classify(
        _log(
            "LaTeX Error: Cannot determine size of graphic in "
            "graphbelow.jpg (no BoundingBox)."
        )
    ) == ("missing_graphic", "graphbelow.jpg")


def test_missing_graphic_open_fail_variant() -> None:
    assert classify(_log("Could not open file 86efield9.eps, ignoring it.")) == (
        "missing_graphic",
        "86efield9.eps",
    )


def test_pkg_version_skew_need_version() -> None:
    # caption.sty cooperation nag —— 前臂要 file-line+`too old` 双条件
    assert classify(
        _log(
            "Package caption Error: For a successful cooperation we need "
            "at least version"
        )
    ) == ("pkg_version_skew", "caption")


def test_pkg_obsolete_option_level() -> None:
    # 选项级废弃措辞 (区别于包级 `Package `X' is obsolete`)
    assert classify(
        _log(
            "Package glossaries Error: obsolete package option `smallcaps' "
            "has been removed. Rollback required or use a newer alternative."
        )
    ) == ("pkg_obsolete", "smallcaps")


def test_fontspec_bare_fallback() -> None:
    # 裸 `Package fontspec Error:` head 无 font-X-cannot-be-found 签 →
    # fontspec_missing|None 兜底 (排折行臂后, fix 层自行 decline)
    assert classify(_log("Package fontspec Error:")) == (
        "fontspec_missing",
        None,
    )


def test_fontspec_tu_nfss_routes_fontspec() -> None:
    # TU/ NFSS 伴随错归 fontspec_missing (taxcen 普查时点未中, 现已签)
    log = (
        "./main.tex:591: Font TU/fontawesomepro/solid/n/10="
        "FontAwesome5Pro-Solid:script=latn; at 10.0pt not loadable: "
        "Metric (TFM) file or installed font not found.\n"
    )
    assert classify(log) == ("fontspec_missing", "fontawesomepro")


# ── 序约束: use_post / use_pre / 裸名兜底 ──


def test_missing_file_extless_bare_stem() -> None:
    # 裸名 `File `stem' not found` 无 post 证据 → missing_file|stem 兜底
    # (排 use_post missing_graphic 臂后不抢既有路由)
    assert classify(_log("LaTeX Error: File `Fig1' not found.")) == (
        "missing_file",
        "Fig1",
    )


def test_missing_file_extless_with_graphic_errhelp_routes_graphic() -> None:
    # 同裸名头 + post 窗 errhelp `I could not locate the file with any of
    # these extensions:` → 仍归 missing_graphic (本臂排其后不抢路由)。
    # errhelp 恒居错误行 +8 (恰出 ctx8 右缘) → 需 ≥9 行垫出 post 窗。
    log = (
        "! LaTeX Error: File `Fig1' not found.\n"
        "\n"
        "See the LaTeX manual or LaTeX Companion for explanation.\n"
        "Type  H <return>  for immediate help.\n"
        " ...\n"
        "\n"
        "l.42 \\includegraphics{Fig1}\n"
        "\n"
        "I could not locate the file with any of these extensions:\n"
        ".png,.pdf,.jpg\n"
    )
    assert classify(log) == ("missing_graphic", "Fig1")


def test_missing_file_extless_poslogo_bare() -> None:
    # PoSlogo 实证形 —— l.N 回显 `\begin{document}` 无 graphic cs, post
    # 窗也无 errhelp → 保守落 missing_file|stem
    log = "! LaTeX Error: File `PoSlogo' not found.\n\nl.32 \\begin{document}\n"
    assert classify(log) == ("missing_file", "PoSlogo")


def test_nfss_setup_with_fd_probe_routes_missing_file() -> None:
    # `^No file X.fd.` 探测行 + NFSS 中止同窗 → use_pre missing_file 臂
    # 先签 (评估序), nfss_setup 兜底臂只见裸 NFSS。
    log = (
        "No file lgrcmr.fd.\n"
        "! LaTeX Error: This NFSS system isn't set up properly.\n"
        "l.5 \\selectfont\n"
    )
    assert classify(log) == ("missing_file", "lgrcmr.fd")


# ── 全错误面: classify_errs 多签去重 ──


def test_errs_multi_sig_dedup() -> None:
    # 2509.14454 同构: microtype + standalone + preamble_only + 2×裸名
    # File —— 首错遮蔽面逐错派发, (cat,pay) 去重保错误序。错误间垫 >ctx8
    # 行距防后续错头漏进本错 blob 抢签 (err ctx 无 pre/post 窗, 但 ctx8
    # 向右覆盖——新行全在 missing_file 后, 裸名头漏进前错 ctx 会被先签)。
    pad = "\n".join(f"ctx filler {i}" for i in range(9)) + "\n"
    log = (
        "! Package microtype Error: Font expansion does not work with xetex.\n"
        "l.10 x\n"
        + pad
        + "! Package standalone Error: Shell escape needed to create graphic! "
        "Use the '-shell-escape' option..\n"
        "l.11 x\n" + pad + "! LaTeX Error: Can be used only in preamble.\n"
        "l.12 x\n" + pad + "! LaTeX Error: File `Fig1' not found.\n"
        "l.13 x\n" + pad + "! LaTeX Error: File `Fig1' not found.\n"
        "l.14 x\n"
    )
    assert classify_errs(log) == [
        ("microtype_pdftex", None),
        ("standalone_shell", None),
        ("preamble_only", None),
        ("missing_file", "Fig1"),
    ]
