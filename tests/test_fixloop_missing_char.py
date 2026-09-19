"""F4 missing_character 分诊规则 —— 合成 log 驱动 + builtin 直测。

warn 段 ``missing_char`` (无 '!' 错时) → ``warn_missing_char`` 伪类别 →
missing_char_fix: CJK 码位在非 CJK 字体 → ``\\AtBeginDocument`` 绑定预热;
符号/拉丁码位 → 字面替换 (表驱动, params.char_table 可扩)。
"""

from pathlib import Path

from test_fixloop_loop import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop._builtins_misschar import macro_glyph_fix
from texlate.compile.fixloop.builtins import (
    _inject_after_docclass,
    _mc_parse_log,
    font_fallback,
    missing_char_fix,
    svjour_clo_stub,
)
from texlate.compile.fixloop.engine import LoopCtx

CTEX_MAIN = (
    "\\documentclass{elsart3}\n"
    "\\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}  % [texlate injected]\n"
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


def test_mc_parse_log_tfm_hex_codepoint() -> None:
    r"""tfm 字体 ``("XXXX)`` 十六进制码位分支 (③): ``("8FD9)`` = U+8FD9「这」。

    loop1 tfm_only 197 格缺字行全是此形——旧正则只认 ``(U+XXXX)`` spec
    格式 → missing_char_fix 未触发主因。
    """
    seen = _mc_parse_log('Missing character: There is no 这 ("8FD9) in font cmr10!\n')
    assert seen[0x8FD9] == ("这", "cmr10")


def test_builtin_tfm_cjk_no_warmup(tmp_path: Path) -> None:
    r"""tfm 字体 (cmr10 无 ``[``/``:``) 缺 CJK → cjk_glyph spec 门排除 → 不预热。

    数学内 CJK 缺字大头落在数学族 TFM 上，xeCJK interchartoks 是水平列
    机制不进数学——warmup 对此无效只能烧到 stuck；数学面已由 inject 侧
    ``\Umathcode`` 符号字体 (CJK_MATH_FALLBACK) 兜底 (④)。
    """
    (tmp_path / "main.tex").write_text(CTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(
        'Missing character: There is no 这 ("8FD9) in font cmr10!\n'
        'Missing character: There is no 是 ("662F) in font ec-lmr10!\n',
        encoding="utf-8",
    )
    ok, note = missing_char_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "unmatched" in note
    assert "AtBeginDocument" not in (tmp_path / "main.tex").read_text()


def test_builtin_mixed_spec_tfm_cjk_warms(tmp_path: Path) -> None:
    """spec+tfm 混合缺字：spec 字体那条仍触发预热 (tfm 条目不拖累)。"""
    (tmp_path / "main.tex").write_text(CTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(
        'Missing character: There is no 这 ("8FD9) in font cmr10!\n'
        "Missing character: There is no 欠 (U+6B20) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, note = missing_char_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    assert "warmup" in note
    assert "\\AtBeginDocument" in (tmp_path / "main.tex").read_text()


def test_inject_after_docclass_multi_seam(tmp_path: Path) -> None:
    r"""``\ifpdf A \else B \fi`` 双 docclass → snippet 两臂各落一份 (② 复用)。"""
    (tmp_path / "main.tex").write_text(
        "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    assert _inject_after_docclass(_ctx(tmp_path), "% probe") is True
    t = (tmp_path / "main.tex").read_text()
    assert t.count("% probe") == 2  # noqa: PLR2004 - 每缝一份


def test_inject_after_docclass_skips_commented(tmp_path: Path) -> None:
    r"""``%\documentclass`` 死行不产生缝——snippet 只落真缝后（2211.04482 记档）。

    attrib-2211 实证：注入物残留在被注释 docclass 行后（时序形态：
    注入时行尚活、后被注释），锚定本身须证伪——遮盖视图本就排除，
    此测试钉死该不变量防回归。
    """
    (tmp_path / "main.tex").write_text(
        "%\\documentclass[twocolumn,linenumbers]{aastex62}\n"
        "\\documentclass[twocolumn]{aastex62}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    assert _inject_after_docclass(_ctx(tmp_path), "% probe") is True
    lines = (tmp_path / "main.tex").read_text().splitlines()
    assert lines[0].startswith("%\\documentclass")
    assert lines[1] == "\\documentclass[twocolumn]{aastex62}"
    assert lines[2] == "% probe"  # 唯一缝 = 真 docclass 行后


def test_inject_after_docclass_only_commented_falls_back(tmp_path: Path) -> None:
    r"""全文只剩 ``%\documentclass`` → 无活缝退文件头注。"""
    (tmp_path / "main.tex").write_text(
        "%\\documentclass{foo}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    assert _inject_after_docclass(_ctx(tmp_path), "% probe") is True
    t = (tmp_path / "main.tex").read_text()
    assert t.startswith("% probe\n%\\documentclass")


def test_svjour_clo_stub_ignores_commented_opts(tmp_path: Path) -> None:
    r"""``%\documentclass[opts]`` 的选项不进 ``sv<opt>.clo`` stub 表（同族锚钉）。"""
    (tmp_path / "main.tex").write_text(
        "%\\documentclass[smallextended]{svjour}\n"
        "\\documentclass[referee]{svjour}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _note = svjour_clo_stub(_ctx(tmp_path), None, None, {})
    assert ok is True
    assert (tmp_path / "svreferee.clo").exists()
    assert not (tmp_path / "svsmallextended.clo").exists()


def test_font_fallback_cyrillic(tmp_path: Path) -> None:
    r"""西里尔缺字 (⑤): Ж U+0416 → ``\newunicodechar`` 逐字回退 Libertinus。

    snippet 必须含 newunicodechar 包行 + ``\txlatefallback`` 字体族 +
    逐字声明 ``\newunicodechar{Ж}{{\txlatefallback Ж}}``。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nЖ\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no Ж (U+0416) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok is True
    assert "Libertinus Serif" in note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{newunicodechar}" in t
    assert "\\newfontfamily\\txlatefallback{Libertinus Serif}" in t
    assert (
        "\\newunicodechar{Ж}{\\ifmmode\\mbox{\\txlatefallback Ж}"
        "\\else{\\txlatefallback Ж}\\fi}" in t
    )
    assert t.index("newunicodechar") > t.index("\\documentclass")


def test_font_fallback_combining_char(tmp_path: Path) -> None:
    """组合符带 U+0300-036F 同走回退 (⑤ 组合符面)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ̈ (U+0308) in font cmr10!\n",
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, _note = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok is True
    t = (tmp_path / "main.tex").read_text()
    assert (
        "\\newunicodechar{̈}{\\ifmmode\\mbox{\\txlatefallback ̈}"
        "\\else{\\txlatefallback ̈}\\fi}" in t
    )


def test_font_fallback_replace_entries_yield(tmp_path: Path) -> None:
    """char_table ``replace`` 已覆盖的码位 (ø U+00F8) 让位字面替换——
    同码位不再发 newunicodechar，仅 ø 缺字时 font_fallback 整体不动作。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nø\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ø (U+00F8) in font cmmi8!\n",
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok is False
    assert "no missing chars in fallback bands" in note


def test_font_fallback_outside_bands(tmp_path: Path) -> None:
    """带外码位 (CJK U+8FD9) 不归 font_fallback —— CJK 另有 warmup/数学兜底。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no 这 ("8FD9) in font cmr10!\n',
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok is False
    assert "no missing chars in fallback bands" in note


def test_font_fallback_pkg_unavailable(tmp_path: Path) -> None:
    """newunicodechar.sty 探测+安装双败 → 不谎报 applied。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nЖ\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no Ж (U+0416) in font cmr10!\n",
        encoding="utf-8",
    )
    ok, note = font_fallback(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok is False
    assert "newunicodechar.sty unavailable" in note
    assert "txlatefallback" not in (tmp_path / "main.tex").read_text()


def test_font_fallback_idempotent(tmp_path: Path) -> None:
    """同 snippet 已在源内 → 第二轮不重复注入 (``snippet in t`` 幂等门)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nЖ\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no Ж (U+0416) in font cmr10!\n",
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path)
    eng = MockEngine([], available={"newunicodechar.sty"})
    assert font_fallback(ctx, eng, None, {})[0] is True
    ok, note = font_fallback(ctx, eng, None, {})
    assert ok is False
    assert "already present" in note


# ════════════════════════════════════════════════════════════════
# misscharext (2026-09-19, utf8census rebucket ×5):
# char_table 扩列 (¡/™/ZWNJ-ZWJ-RLM/02F7/2329/232A/2010) + macro_glyph_fix
# ════════════════════════════════════════════════════════════════


def test_loop_latin1_tm_zwnj_char_table(tmp_path: Path) -> None:
    r"""¡/™/ZWNJ 字面缺字 → 实装 char_table 字面替换 (60-misschar.yaml 扩列)。

    1811.10109 实证 (™ in shipped .bbl, aer8 TFM ``("2122)``);
    2410.00026 实证 (ZWNJ U+200C bib→bbl, lmroman8);
    1206.0663 实证 (¡ in math ``n$¡$``, txr TFM ``("A1)`` —— ``!`` 连字产 ¡);
    2003.03387 实证 (U+2010 HYPHEN×2 bib-passthrough, revtex4+ae aer9)。
    """
    main = (
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\nn$¡$ Bitcoin™ off‌load co‐op\n\\end{document}\n"
    )
    log = (
        'Missing character: There is no ¡ ("A1) in font txr!\n'
        'Missing character: There is no ™ ("2122) in font aer8!\n'
        "Missing character: There is no ‌ (U+200C) in font "
        "[lmroman8-regular]:mapping=tex-text;!\n"
        'Missing character: There is no ‐ ("2010) in font aer9!\n'
        "Output written on main.pdf (1 page).\n"
    )
    eng = MockEngine([{"log": log, "pdf": True}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_missing_char"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "n$\\mbox{!`}$" in t
    assert "Bitcoin\\mbox{\\texttrademark}" in t
    assert "off{}load" in t  # ZWNJ 剥除
    assert "co\\mbox{-}op" in t  # U+2010 → 连字符


def test_font_fallback_latin1_boundary(tmp_path: Path) -> None:
    r"""¡ U+00A1 不归 font_fallback —— _FB_RANGES 起点 0x00C0 边界决策钉死。

    latin-1 标点全有 TeX 原生命令形 (char_table 语义替换 > 字体替换),
    扩带会让未补条目静默绑 Libertinus 而非以 unmatched 露面 → 带不扩。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nn$¡$\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no ¡ ("A1) in font txr!\n',
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok is False
    assert "no missing chars in fallback bands" in note


def test_builtin_macro_glyph_tildelow(tmp_path: Path) -> None:
    r"""``\texttildelow`` 产 U+02F7 缺字 (2308.04265 文本域站点) → 站点改写。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "rate of \\raisebox{0.5ex}{\\texttildelow}80\\% x\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ˷ (U+02F7) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    assert "1" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\raisebox{0.5ex}{\\ensuremath{\\sim}}80\\%" in t
    assert "\\texttildelow" not in t


def test_builtin_macro_glyph_textangle_newcommand(tmp_path: Path) -> None:
    r"""``\textlangle``/``\textrangle`` 产 U+2329/232A (2403.00011 宏体站点)。

    ``\qdist`` 宏体在文本域定义、数学域展开 —— 双模 ``\ensuremath`` 串
    两侧恒正 (定义点域判不准); ``Command \X invalid in math mode``
    warning 同灭。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\newcommand{\\qdist}[1]{\\textlangle#1\\textrangle}\n"
        "\\begin{document}\n$\\qdist{x}$ and $\\qdist{y}$\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "LaTeX Warning: Command \\textlangle invalid in math mode on input line 5.\n"
        'Missing character: There is no 〈 ("2329) in font zptmcmr!\n'
        'Missing character: There is no 〉 ("232A) in font zptmcmr!\n',
        encoding="utf-8",
    )
    ok, _note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert (
        "\\newcommand{\\qdist}[1]{\\ensuremath{\\langle}#1\\ensuremath{\\rangle}}" in t
    )


def test_builtin_macro_glyph_declines_without_cp(tmp_path: Path) -> None:
    """产出码位不在缺字表 → cs 站点不动 (字体真有字形的不误伤)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\textlangle x\\textrangle\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ≠ (U+2260) in font cmr7!\n",
        encoding="utf-8",
    )
    ok, note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "no macro-generated" in note
    assert "\\textlangle" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_builtin_macro_glyph_masked_protection(tmp_path: Path) -> None:
    r"""verbatim/注释内同名 cs 不改写 (遮盖面)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "% \\texttildelow dead\n"
        "\\begin{verbatim}\\texttildelow\\end{verbatim}\n"
        "\\texttildelow\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ˷ (U+02F7) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, _note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "% \\texttildelow dead" in t
    assert "\\begin{verbatim}\\texttildelow\\end{verbatim}" in t
    assert t.count("\\ensuremath{\\sim}") == 1


def test_builtin_macro_glyph_cs_sites_absent(tmp_path: Path) -> None:
    """码位在缺字表但源内无 cs 站点 → decline (字面量归 char_table 臂)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ˷ (U+02F7) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "no cs sites" in note
