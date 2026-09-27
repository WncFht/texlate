"""erafix 钉 —— erafam lane 七捆落地 (failmine7 桶 → lane-erafam census 2026-09-20)。

B1-B4: ``cs_targeted_fix`` params.cs_table 定点族 40 键
(95-targeted.yaml, 53 cells) —— era/209 刊面宏 polyfill/guard/cs_map。
B5: ``hani_font_fallback`` (60-misschar.yaml order 29, 11 cells) ——
汉字缺字落 Fandol 系主字体 (script=hani 真缺字形) 的二档回退臂:
``cjk_font_fallback`` font_not 含 fandol 把这群格留成无臂认领,
本臂 font_not 刻意不收 fandol 专收其漏口。
B6: ``_MACRO_GLYPH_CS`` 三键 (checkmark/blacktriangle/ss, 5 cells)。
B7: ``missing_char_fix`` params.char_table 四行
(figuredash/lcomma/ncomma/danda, 3 cells)。
"""

import re

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop._builtins_misschar import _MACRO_GLYPH_CS

_RS = load_ruleset()
_CS_PARAMS = next(r for r in _RS.rules if r.id == "cs_targeted_fix").action["params"]
_CSTABLE = _CS_PARAMS["cs_table"]
_HANI = next(r for r in _RS.rules if r.id == "hani_font_fallback")
_HANI_PARAMS = _HANI.action["params"]
_CHAR_TABLE = next(r for r in _RS.rules if r.id == "missing_char_fix").action["params"][
    "char_table"
]
_CHAR_IDS = {e["id"] for e in _CHAR_TABLE}


def test_ruleset_loads_with_hani_rule() -> None:
    """规则库载入且 hani_font_fallback 在册 (落地时 195→196; 共仓兄弟
    lane 并发加规则, 钉下界不钉绝对数)。"""
    assert len(_RS.rules) >= 196  # noqa: PLR2004 - 落地时 195+1, 只钉下界
    assert _HANI.order == 29  # noqa: PLR2004 - hangul(28) 后位次钉死
    assert _HANI.action["kind"] == "builtin_transform"
    assert _HANI.action["function"] == "font_fallback"


def test_hani_params_shape() -> None:
    """hani 臂参数面: 表意三段带表 + txlatehanifb cs + 家族名候选。"""
    assert _HANI_PARAMS["fallback_cs"] == "txlatehanifb"
    assert _HANI_PARAMS["fallback_ranges"] == [
        [0x4E00, 0x9FFF],
        [0x3400, 0x4DBF],
        [0xF900, 0xFAFF],
    ]
    assert "Noto Serif CJK SC" in _HANI_PARAMS["fallback_fonts"]


def test_hani_font_not_negative_fandol() -> None:
    """font_not 负向钉: FandolSong/FandolKai 字体 token 不命中 —— 本臂猎场。

    log 字体 token 形如 ``[FandolSong-Regular.otf]/OT:script=hani``;
    fandol 入 font_not 正是 cjk 臂漏管这 11 格的根因, 本臂必须不收。
    """
    pat = _HANI_PARAMS["font_not"]
    for tok in (
        "[FandolSong-Regular.otf]/OT:script=hani",
        "[FandolKai-Regular.otf]/OT:script=hani",
        "FandolSong-Regular",
    ):
        assert re.search(pat, tok, re.IGNORECASE) is None


def test_hani_font_not_positive_noto() -> None:
    """font_not 正向钉: 已具大字库 hani 覆盖的字体仍跳过 (防自回环)。"""
    pat = _HANI_PARAMS["font_not"]
    for tok in ("Noto Sans CJK SC", "Noto Serif CJK TC", "Source Han Serif SC"):
        assert re.search(pat, tok, re.IGNORECASE)


def test_cs_table_erafam_polyfill_keys() -> None:
    """B1/B4 polyfill 键在册: I/onecolumn/proof/no/@captype 形态各异。"""
    for key in ("I", "onecolumn", "proof", "no", "undefinedpagestyle", "Pacs"):
        assert key in _CSTABLE, key
    assert _CSTABLE["I"]["polyfill"].endswith("\\providecommand{\\I}{I}")
    # "no" 是 psfig 缺-bb 错误分支内部 cs —— noop polyfill;
    # yaml 裸 no 会解析成 False 键永不命中, 必须引号保活。
    assert False not in _CSTABLE
    assert _CSTABLE["no"]["polyfill"].endswith("\\providecommand\\no{}")


def test_cs_table_erafam_at_and_guard_keys() -> None:
    """B2 @-面与 guard 形键: csname-safe polyfill + dict/argspec guard。"""
    assert _CSTABLE["if@smallext"]["polyfill"].endswith(
        "\\expandafter\\newif\\csname if@smallext\\endcsname"
    )
    assert _CSTABLE["@captype"]["guard"] == {"args": "", "body": "figure"}
    assert _CSTABLE["KV@undefined"]["guard"] == "[2]"
    assert _CSTABLE["@verridelabel"]["guard"] == "[1]"
    assert "\\let\\csname collaboration@sw" in _CSTABLE["collaboration@sw"]["polyfill"]


def test_cs_table_erafam_usepackage_keys() -> None:
    """B3 pkg-load 键 + epsfile cs_map: usepackage 走 RequirePackage 臂。"""
    assert _CSTABLE["overset"] == {"usepackage": "amsmath"}
    assert _CSTABLE["setstretch"] == {"usepackage": "setspace"}
    assert _CSTABLE["onehalfspace"] == {"usepackage": "setspace"}
    assert _CSTABLE["mathscr"] == {"usepackage": "mathrsfs"}
    assert _CSTABLE["psfrag"] == {"usepackage": "psfrag"}
    assert _CSTABLE["epsfile"]["usepackage"] == "epsfig"
    assert _CSTABLE["epsfile"]["cs_map"] == {"epsfile": "epsfig"}


def test_macro_glyph_cs_erafam_entries() -> None:
    """B6 _MACRO_GLYPH_CS 三键: produced-cp → 站点重写串。"""
    assert _MACRO_GLYPH_CS["checkmark"] == (0x2713, "\\ensuremath{\\surd}")
    assert _MACRO_GLYPH_CS["blacktriangle"] == (
        0x25B4,
        "\\ensuremath{\\vartriangle}",
    )
    assert _MACRO_GLYPH_CS["ss"] == (0x1E9E, "ss")


def test_char_table_erafam_entries() -> None:
    """B7 char_table 四行: figuredash/lcomma/ncomma/danda 字面替换。"""
    assert {"figuredash", "lcomma", "ncomma", "danda"} <= _CHAR_IDS
    by_id = {e["id"]: e for e in _CHAR_TABLE}
    assert by_id["figuredash"]["cps"] == [0x2012]
    assert by_id["figuredash"]["replace"] == "--"
    assert by_id["lcomma"]["cps"] == [0x13C]
    assert by_id["lcomma"]["replace"] == "\\mbox{\\c{l}}"
    assert by_id["ncomma"]["cps"] == [0x146]
    assert by_id["danda"]["cps"] == [0x964]
    assert by_id["danda"]["replace"] == "{}"
