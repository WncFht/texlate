r"""F4 missing_character 分诊规则 —— 合成 log 驱动 + builtin 直测。

warn 段 ``missing_char`` (无 '!' 错时) → ``warn_missing_char`` 伪类别 →
missing_char_fix: CJK 码位在非 CJK 字体 → ``\AtBeginDocument`` 绑定预热;
符号/拉丁码位 → 字面替换 (表驱动, params.char_table 可扩)。

现覆盖面: ``_mc_parse_log`` tfm ``("XXXX)`` 码位分支、cjk_glyph spec 门
(tfm 排除/spec 混合预热)、``_inject_after_docclass`` 多缝与注释缝锚定、
``svjour_clo_stub`` 注释选项免疫、``font_fallback`` 西里尔/组合符
newunicodechar 逐字回退 (带界/幂等/包缺位), char_table 三批扩列
(misscharext ¡/™/ZWNJ/U+2010 族、misscharcen162 TFM+bbl 17-cell、
misschars4 ~21-cell), ``macro_glyph_fix`` cs 站点改写
(texttildelow/textlangle/textendash/gravedbl-acutedbl/``\char<dec>``
OT1 槽位臂), ``caret_utf8_fix`` .bbl ``^^XX`` UTF-8 字节解码 (C1 指纹门)。
hangul 路由 (kotexfix #196) 已拆 ``test_fixloop_kotex.py``。
"""

from pathlib import Path

from test_fixloop_loop import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop._builtins_misschar import (
    caret_utf8_fix,
    macro_glyph_fix,
)
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
    assert "\\RequirePackage{newunicodechar}" in t
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
    assert (
        "macro glyph sites rewritten: 1" in note
    )  # 钉单站点改写 ("in 1 file(s)" 不算数)
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


# ════════════════════════════════════════════════════════════════
# misscharcen #162 (2026-09-19, loop3 残余普查 misscharcen 车道):
# char_table 补 14 条 (·²´¼½º≤⋅∼ℤ thinsp ʼ ╨ PUA —— 17 cells/35 lines)
# + _MACRO_GLYPH_CS 扩 \\textendash/\\textgravedbl/\\textacutedbl
# ════════════════════════════════════════════════════════════════


def test_loop_misscharcen162_tfm_replaces(tmp_path: Path) -> None:
    r"""TFM 无槽字面 → ``\ensuremath``/TFM 自有槽系替换 (17-cell 普查签名)。

    缺字体全是 cmr*/zptmcm7t/cmmi7 TFM —— ``\textXxx`` 在 TU 下产出同
    码位会再缺, 一律走数学族/TFM 连字形:
    ``´``→``'`` (1003.1105 ``k'\tau´`` 数学内伪 prime),
    ``¼½``→``\frac{1}{4|2}`` (physics/0408068 数学系数),
    ``≤``→``\leq`` (1811.10179 ``≤\leq`` 并列), ``²``→``^2``
    (1306.0373 ``X²``/2608.25702), ``·``→``\cdot`` (0707.2570/
    physics--0408068/2410.00043), ``º``→``\textordmasculine``
    (0905.1202 ``K_º`` cmmi7 数学下标 —— \mbox 落文本字体 lmroman 有槽)。
    """
    main = (
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\n"
        "$k'\\tau´$ $½+¼$ $≤\\leq\\delta$ $X²$ $K_º$ mid·dot ² tail\n"
        "\\end{document}\n"
    )
    log = (
        'Missing character: There is no ´ ("B4) in font cmr10!\n'
        'Missing character: There is no ½ ("BD) in font cmr12!\n'
        'Missing character: There is no ¼ ("BC) in font cmr12!\n'
        'Missing character: There is no ≤ ("2264) in font cmr12!\n'
        'Missing character: There is no ² ("B2) in font cmr8!\n'
        'Missing character: There is no º ("BA) in font cmmi7!\n'
        'Missing character: There is no · ("B7) in font cmr12!\n'
        'Missing character: There is no · ("B7) in font zptmcm7t!\n'
        "Output written on main.pdf (1 page).\n"
    )
    eng = MockEngine([{"log": log, "pdf": True}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_missing_char"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\tau\\ensuremath{'}" in t
    assert "\\ensuremath{\\frac{1}{2}}+\\ensuremath{\\frac{1}{4}}" in t
    assert "\\ensuremath{\\leq}\\leq" in t
    assert "X\\ensuremath{^2}" in t
    assert "K_\\mbox{\\textordmasculine}" in t
    assert "mid\\ensuremath{\\cdot}dot" in t
    assert " \\ensuremath{^2} tail" in t


def test_loop_misscharcen162_bbl_lmroman(tmp_path: Path) -> None:
    r"""spec 字体 (lmroman*) 缺字 + shipped .bbl 字面 → 替换/剥除。

    ``∼``→``\sim`` (1803.00056 .bbl ``Gaussian∼09`` lmromancaps10),
    ``ℤ``→``\mathbb{Z}`` (1803.03082 .bbl lmroman10-italic, 格载 amssymb),
    ``ʼ``→``'`` (1404.0261 .bbl ``kasteleynʼs``),
    thinsp→``\,`` (1608.02573/1803.00030/2505.13884),
    ``╨``→``-`` (1404.0389 .bbl ``silicone╨based`` CP437-era 连字符
    mojibake —— 还原连字符非剥除), PUA U+F07A→``{}`` (0905.1031)。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\nx \\input{main.bbl}\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.bbl").write_text(
        "Gaussian∼09 kasteleynʼs 50 km silicone╨based ℤ-set pua\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ∼ (U+223C) in font "
        "[lmromancaps10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ʼ (U+02BC) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no   (U+2009) in font "
        "[lmroman9-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ╨ (U+2568) in font "
        "[lmroman12-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ℤ (U+2124) in font "
        "[lmroman10-italic]:mapping=tex-text;!\n"
        "Missing character: There is no  (U+F07A) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, note = missing_char_fix(_ctx(tmp_path), None, None, _missing_char_fix_params())
    assert ok is True, note
    t = (tmp_path / "main.bbl").read_text(encoding="utf-8")
    assert "Gaussian\\ensuremath{\\sim}09" in t
    assert "kasteleyn\\mbox{'}s" in t
    assert "50\\,km" in t
    assert "silicone-based" in t
    assert "\\ensuremath{\\mathbb{Z}}-set" in t
    assert "pua{}" in t


def _missing_char_fix_params() -> dict:
    """落地 ruleset 里 ``missing_char_fix`` 的真 params (测 yaml 条目本身)。"""
    from texlate.compile.fixloop.ruleset import (  # noqa: PLC0415 - 延迟 import
        load_ruleset,
    )

    for r in load_ruleset().phase("loop"):
        if r.id == "missing_char_fix":
            return r.action.get("params") or {}
    msg = "missing_char_fix rule not found"
    raise AssertionError(msg)


def test_builtin_macro_glyph_textendash_math(tmp_path: Path) -> None:
    r"""``\textendash`` 数学态 ket 记号内产 U+2013 → ``\mbox{--}``。

    0806.2407 签名 (``$i_{13/2}\textendash\frac{3}{2}$``, cmr10 ×40):
    ``--`` TFM 连字产 en-dash, \mbox 双模安全 —— 与 char_table endash
    字面臂同形。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "$0.784|6i_{13/2}\\textendash\\frac{3}{2}\\rangle$\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        'Missing character: There is no – ("2013) in font cmr10!\n',
        encoding="utf-8",
    )
    ok, _note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "|6i_{13/2}\\mbox{--}\\frac{3}{2}\\rangle" in t
    assert "\\textendash" not in t


def test_builtin_macro_glyph_dblquote_pair(tmp_path: Path) -> None:
    r"""``\textgravedbl X\textacutedbl`` „...˝ 引号对 → „...\" 成对归一。

    hep-ph/0605319 签名 (tuenc: gravedbl→U+02F5 缺 ×12, acutedbl→
    U+02DD 有槽不缺)。acutedbl 键伴生 02F5 —— gravedbl 触发时整对
    改写 ``\quotedblbase``+``''``, 免留 „...˝ 混搭。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\textgravedbl quoted\\textacutedbl done\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ˵ (U+02F5) in font "
        "[lmroman12-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, _note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\mbox{\\quotedblbase} quoted\\mbox{''} done" in t
    assert "\\textgravedbl" not in t
    assert "\\textacutedbl" not in t


def test_builtin_macro_glyph_acutedbl_own_cp_not_keyed(tmp_path: Path) -> None:
    r"""acutedbl 自产 U+02DD 缺字不触发 ``''`` —— 音标域语义不误伤。

    键位是伴生 02F5 引号对触发而非自产码位: 只有 02DD 缺字 (无
    02F5) 时 ``\textacutedbl`` 站点原样保留, 交下轮/字体回退。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "phon \\textacutedbl mark\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ˝ (U+02DD) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, _note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "\\textacutedbl" in (tmp_path / "main.tex").read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# misscharcen #169 (2026-09-19, misschar 批二): macro_glyph_fix
# +``\char<dec>`` OT1 槽位臂 (1404.0578) + caret_utf8_fix 新臂
# (2104.00026 .bbl ``^^XX`` UTF-8 字节记法)
# ════════════════════════════════════════════════════════════════


def test_builtin_macro_glyph_char_slot_textsc_ligature(tmp_path: Path) -> None:
    r"""``\textsc{\char13}`` OT1/cmcsc 槽位 13=fl 连字 → 字母串改写。

    1404.0578 签名 (lmromancaps10 ``^^M`` U+000D ×41): Unicode 字体下
    ``\char13`` 产码位 13 本身而非槽位字形 —— 槽位表还原连字本意;
    写字母 ``fl`` 在 \textsc 上下文自动取小型大写形 (cmcsc 槽位原义)。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "x \\textsc{\\char13} y \\char11 z \\char15 w\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ^^M (U+000D) in font "
        "[lmromancaps10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ^^K (U+000B) in font "
        "[lmromancaps10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ^^O (U+000F) in font "
        "[lmromancaps10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    assert "char" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\textsc{fl}" in t
    assert "y ff z ffl w" in t
    assert "\\char" not in t


def test_builtin_macro_glyph_char_slot_radices_and_greek(tmp_path: Path) -> None:
    r"""八/十六进制实参同臂 (``\char'15``/``\char"D``) + 希腊槽位
    (``\char1``→``\ensuremath{\Delta}``)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "a \\char'15 b \\char\"D c \\char1 d\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ^^M (U+000D) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ^^A (U+0001) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, _note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "a fl b fl c \\ensuremath{\\Delta} d" in t


def test_builtin_macro_glyph_char_slot_gate_bounds(tmp_path: Path) -> None:
    r"""槽表内 dec∉seen → 站点不动 (``\char12`` 产 U+000C 未缺字);
    表外 dec (≥32 ASCII 面) 本就不收。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "a \\char99 b \\char12 c\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ^^M (U+000D) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, note = macro_glyph_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "no cs sites" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\char99" in t
    assert "\\char12" in t


def test_loop_char_slot_end_to_end(tmp_path: Path) -> None:
    r"""实装 ruleset 端到端: ``\textsc{\char13}`` → ``\textsc{fl}``
    (1404.0578 单签 U+000D → 25.8 macro_glyph_fix 槽位臂)。"""
    main = (
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\n这是译文\\textsc{\\char13}这是译文\n\\end{document}\n"
    )
    log = (
        "Missing character: There is no ^^M (U+000D) in font "
        "[lmromancaps10-regular]:mapping=tex-text;!\n"
        "Output written on main.pdf (1 page).\n"
    )
    eng = MockEngine([{"log": log, "pdf": True}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_missing_char"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\textsc{fl}" in t
    assert "\\char" not in t


def test_builtin_caret_utf8_bbl_decode(tmp_path: Path) -> None:
    r""".bbl ``^^XX`` UTF-8 字节记法 → 解码还原字面量 (2104.00026 签名)。

    ``f^^c3^^bcr`` = UTF-8 C3 BC = ``für``; ``^^e2^^80^^93`` = E2 80 93
    = en-dash。C1 字节 (^^80/^^93) 是缺字指纹; ``^^c3^^bc`` 字节都落
    Latin-1 有槽面产零缺字静默 mojibake —— 段级解码一并还原。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx \\input{main.bbl}\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.bbl").write_text(
        "Zeitschrift f^^c3^^bcr Physik "
        "Knizhnik^^e2^^80^^93Zamolodchikov 121^^e2^^80^^93187\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ^^80 (U+0080) in font "
        "[lmroman9-italic]:mapping=tex-text;!\n"
        "Missing character: There is no ^^93 (U+0093) in font "
        "[lmroman9-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, note = caret_utf8_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    assert "decoded" in note
    t = (tmp_path / "main.bbl").read_text(encoding="utf-8")
    assert "für Physik" in t
    assert "Knizhnik–Zamolodchikov" in t
    assert "121–187" in t
    assert "^^" not in t


def test_builtin_caret_utf8_bad_seq_and_singles_preserved(tmp_path: Path) -> None:
    r"""单 token / 非 UTF-8 合法序列原样保留 —— 合法 TeX 记法与坏
    mojibake 不误伤; 同段混入的合法序列照解。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "keep ^^41 ^^0d bad ^^e2^^41^^80 surr ^^ed^^a0^^80 good ^^c3^^bc\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ^^80 (U+0080) in font "
        "[lmroman9-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    ok, _note = caret_utf8_fix(_ctx(tmp_path), None, None, {})
    assert ok is True
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "^^41" in t  # 单 token 合法记法不动
    assert "^^0d" in t
    assert "^^e2^^41^^80" in t  # E2 需 2 续字节 (41 非续) → 全回吐
    assert "^^ed^^a0^^80" in t  # ED A0 80 = 代理区 → 严格校验回吐
    assert "good ü" in t


def test_builtin_caret_utf8_gate_requires_c1(tmp_path: Path) -> None:
    r"""无 C1 缺字 → 指纹门不过 → 不动 (纯 ü 类零缺字 mojibake 不属
    证据修复面, known_gap)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "Zeitschrift f^^c3^^bcr\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no ≠ (U+2260) in font cmr7!\n",
        encoding="utf-8",
    )
    ok, note = caret_utf8_fix(_ctx(tmp_path), None, None, {})
    assert ok is False
    assert "fingerprint" in note
    assert "f^^c3^^bcr" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_loop_caret_utf8_end_to_end(tmp_path: Path) -> None:
    r"""实装 ruleset 端到端: C1 缺字 → 25.9 caret_utf8_fix 解码 .bbl
    → clean (2104.00026 签名复刻)。"""
    proj = make_proj(
        tmp_path,
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\nx \\input{main.bbl}\n\\end{document}\n",
    )
    (proj / "main.bbl").write_text(
        "Zeitschrift f^^c3^^bcr Physik 121^^e2^^80^^93187\n",
        encoding="utf-8",
    )
    log = (
        "Missing character: There is no ^^80 (U+0080) in font "
        "[lmroman9-italic]:mapping=tex-text;!\n"
        "Missing character: There is no ^^93 (U+0093) in font "
        "[lmroman9-regular]:mapping=tex-text;!\n"
        "Output written on main.pdf (1 page).\n"
    )
    eng = MockEngine([{"log": log, "pdf": True}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(proj, eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_missing_char"
    t = (proj / "main.bbl").read_text(encoding="utf-8")
    assert "für Physik" in t
    assert "121–187" in t


# ════════════════════════════════════════════════════════════════
# misschars4 #190 (2026-09-19, loop3 残余普查 misschar3 车道):
# char_table 补 21 条 (tab ‰ € ✓ ¯ ├ ǎ ﬁ ˆ ₁₂ ∀∃∈∘∧∨∪ ⟨⟩ ˵)
# ════════════════════════════════════════════════════════════════


def test_loop_misschars4_char_table(tmp_path: Path) -> None:
    r"""~20-cell 普查字面 → 替换/剥除 (misschars4 #190 签名批)。

    文本族 (lmroman 有槽): ‰→``\textperthousand`` €→``\texteuro``
    ˵→``''``; accent 机制形 (任意字体可排, 免再缺同码位):
    ¯→``\={}`` ǎ→``\v{a}`` ˆ→``\^{}``; 数学族: ✓→``\surd``
    (kernel 字形免 amssymb) ₁₂→``_1/_2`` ∀∃∈∘∧∨∪⟨⟩→同名 math cs;
    ├ boxdraw→``{}`` 剥除; ﬁ→``fi`` religate; tab→空格
    (1907.00144 lmroman10-italic ×2 实证)。
    """
    main = (
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\n"
        "a\tb ‰pct €eur ✓ok ¯m ├x čǎ ﬁle ˆh ˵d "
        "$x₁ y₂ ∀∃∈∘∧∨∪⟨φ⟩$\n"
        "\\end{document}\n"
    )
    log = (
        "Missing character: There is no ^^I (U+0009) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ‰ (U+2030) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no € (U+20AC) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ✓ (U+2713) in font cmr10!\n"
        "Missing character: There is no ¯ (U+00AF) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        'Missing character: There is no ├ ("251C) in font cmr12!\n'
        "Missing character: There is no ǎ (U+01CE) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ﬁ (U+FB01) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ˆ (U+02C6) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ˵ (U+02F5) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no ₁ (U+2081) in font cmr10!\n"
        "Missing character: There is no ₂ (U+2082) in font cmr10!\n"
        "Missing character: There is no ∀ (U+2200) in font cmr10!\n"
        "Missing character: There is no ∃ (U+2203) in font cmr10!\n"
        "Missing character: There is no ∈ (U+2208) in font cmr10!\n"
        "Missing character: There is no ∘ (U+2218) in font cmr10!\n"
        "Missing character: There is no ∧ (U+2227) in font cmr10!\n"
        "Missing character: There is no ∨ (U+2228) in font cmr10!\n"
        "Missing character: There is no ∪ (U+222A) in font cmr10!\n"
        "Missing character: There is no ⟨ (U+27E8) in font cmr10!\n"
        "Missing character: There is no ⟩ (U+27E9) in font cmr10!\n"
        "Output written on main.pdf (1 page).\n"
    )
    eng = MockEngine([{"log": log, "pdf": True}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "warn_missing_char"
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "a b \\mbox{\\textperthousand}pct" in t
    assert "\\mbox{\\texteuro}eur" in t
    assert "\\ensuremath{\\surd}ok" in t
    assert "\\mbox{\\={}}m {}x" in t
    assert "č\\mbox{\\v{a}}" in t
    assert "file \\mbox{\\^{}}h" in t
    assert "\\mbox{''}d" in t
    assert "x\\ensuremath{_1}" in t
    assert "y\\ensuremath{_2}" in t
    assert (
        "\\ensuremath{\\forall}\\ensuremath{\\exists}\\ensuremath{\\in}"
        "\\ensuremath{\\circ}\\ensuremath{\\wedge}\\ensuremath{\\vee}"
        "\\ensuremath{\\cup}" in t
    )
    assert "\\ensuremath{\\langle}φ\\ensuremath{\\rangle}" in t
