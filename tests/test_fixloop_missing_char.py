"""F4 missing_character 分诊规则 —— 合成 log 驱动 + builtin 直测。

warn 段 ``missing_char`` (无 '!' 错时) → ``warn_missing_char`` 伪类别 →
missing_char_fix: CJK 码位在非 CJK 字体 → ``\\AtBeginDocument`` 绑定预热;
符号/拉丁码位 → 字面替换 (表驱动, params.char_table 可扩)。
"""

from pathlib import Path

from test_fixloop_loop import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.builtins import missing_char_fix
from texlate.compile.fixloop.engine import LoopCtx

CTEX_MAIN = (
    "\\documentclass{elsart3}\n"
    "\\usepackage[fontset=fandol,UTF8]{ctex}  % [texlate injected]\n"
    "\\begin{document}\n"
    "\\begin{frontmatter}\n\\title{欠掺杂铜氧化物}\n\\end{frontmatter}\n"
    "在过去的几年中。\n"
    "\\end{document}\n"
)

CJK_MC_LOG = (
    "Missing character: There is no 欠 (U+6B20) in font [lmroman10-regular]:mapping=tex-text;!\n"
    "Missing character: There is no 在 (U+5728) in font [lmroman10-regular]:mapping=tex-text;!\n"
    "Missing character: There is no ， (U+FF0C) in font [lmroman10-regular]:mapping=tex-text;!\n"
    "Output written on main.pdf (1 page).\n"
)


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def test_cjk_missing_drives_warmup_round(tmp_path: Path) -> None:
    """elsart3+ctex 工程 CJK 落 lmroman → warn_missing_char → 预热注入 → 复编 clean。"""
    eng = MockEngine(
        [
            {"log": CJK_MC_LOG, "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path, CTEX_MAIN), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_missing_char"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\AtBeginDocument{\\setbox0=\\hbox{" in t
    assert "\\normalsize 中" in t
    # 注入在 documentclass 行后、begin{document} 前
    assert t.index("\\AtBeginDocument") < t.index("\\begin{document}")


def test_symbol_missing_char_replaced(tmp_path: Path) -> None:
    """≠ U+2260 落 cmr7 → 字面替换 \\ensuremath{\\neq} (n100 0806.1079 签名)。"""
    main = (
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\na ≠ b 且 a − b\n\\end{document}\n"
    )
    log = (
        "Missing character: There is no ≠ (U+2260) in font cmr7!\n"
        "Missing character: There is no − (U+2212) in font cmr10!\n"
        "Output written on main.pdf (1 page).\n"
    )
    eng = MockEngine([{"log": log, "pdf": True}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_missing_char"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "a \\ensuremath{\\neq} b 且 a \\ensuremath{-} b" in t


def test_builtin_no_cjk_mech_skips_warmup(tmp_path: Path) -> None:
    """无 ctex/xeCJK 的源 → CJK 缺字不可预热 → 不谎报 applied。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(CJK_MC_LOG, encoding="utf-8")
    ok, note = missing_char_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "warmup skipped" in note
    assert "AtBeginDocument" not in (tmp_path / "main.tex").read_text()


def test_builtin_cjk_glyph_in_cjk_font_unmatched(tmp_path: Path) -> None:
    """CJK 码位落在真 CJK 字体 = 字体真缺字形 → font_not 排除 → 不动作。"""
    (tmp_path / "main.tex").write_text(CTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(
        "Missing character: There is no 𠀀 (U+20000) in font [FandolSong-Regular.otf]!\n",
        encoding="utf-8",
    )
    ok, note = missing_char_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "unmatched" in note


def test_builtin_char_table_extensible(tmp_path: Path) -> None:
    """params.char_table 扩列: 自定义码位 → replace 生效 (数据驱动验证)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nℵx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ℵ (U+2135) in font cmr10!\n",
        encoding="utf-8",
    )
    ok, note = missing_char_fix(
        _ctx(tmp_path),
        None,
        None,
        {
            "char_table": [
                {"id": "aleph", "cps": [0x2135], "replace": "\\ensuremath{\\aleph}"}
            ]
        },
    )
    assert ok is True
    assert "replaced" in note
    assert "\\ensuremath{\\aleph}x" in (tmp_path / "main.tex").read_text()


def test_builtin_pdftex_caret_hex(tmp_path: Path) -> None:
    """pdftex ``^^e8`` 记法 → U+00E8 → egrave 替换。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\ncafè\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ^^e8 in font cmr10!\n",
        encoding="utf-8",
    )
    ok, _ = missing_char_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    assert "caf\\mbox{\\`{e}}" in (tmp_path / "main.tex").read_text()


def test_builtin_no_missing_char_log(tmp_path: Path) -> None:
    """log 无缺字行 → False (规则评估侧 skip, 不算应用)。"""
    (tmp_path / "main.tex").write_text(CTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(CLEAN_LOG, encoding="utf-8")
    ok, note = missing_char_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "no compile log" in note
