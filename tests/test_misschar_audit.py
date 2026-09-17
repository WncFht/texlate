"""scout-misschar-coverage 2026-09-17 三项修复的审计测试.

- accent_mark_fix: accent cs 生成的组合符 (U+0300-036F) 非输入字符,
  newunicodechar 拦不到 → 源级 ``\\<cs>{x}`` 站点改写预组字/剥 accent.
- math_font_chars: font_fallback ``\\ifmmode`` 模板 + 文本字母 cs 数学域 shim.
- nullfont_noise: missing_char 签名排除 ``in font nullfont`` 测量盒噪音.
"""

from pathlib import Path

from test_fixloop_loop import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.builtins import (
    _inject_after_docclass,
    _mc_parse_log,
    accent_mark_fix,
    font_fallback,
)
from texlate.compile.fixloop.engine import LoopCtx, Ruleset
from texlate.compile.fixloop.logparse import parse_text


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _write_main(tmp_path: Path, body: str) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n",
        encoding="utf-8",
    )


def _mc_log(*lines: str) -> str:
    return "".join(lines) + "Output written on main.pdf (1 page).\n"


# ---------------------------------------------------------------- accent_mark_fix
def test_accent_sites_rewritten_and_fallback_self_injected(tmp_path: Path) -> None:
    r"""``Gu\c{t}\u{a}`` → ``Guţă``: 预组字面量 + 自注 newunicodechar 回退行.

    0327/0306 组合符由 accent 机制生成非输入字符 —— 自注行是必要的
    (applied-key 一次性, font_fallback 同格不再触火).
    """
    _write_main(tmp_path, r"M. Gu\c{t}\u{a} done")
    (tmp_path / "main.log").write_text(
        _mc_log(
            "Missing character: There is no ̧ (U+0327) in font [lmroman9-regular]:mapping=tex-text;!\n",
            "Missing character: There is no ̆ (U+0306) in font [lmroman9-regular]:mapping=tex-text;!\n",
        ),
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = accent_mark_fix(_ctx(tmp_path), eng, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert r"Guţă" in t
    assert r"\c{t}" not in t
    assert r"\u{a}" not in t
    assert "\\usepackage{newunicodechar}" in t
    assert (
        "\\newunicodechar{ţ}{\\ifmmode\\mbox{\\txlatefallback ţ}"
        "\\else{\\txlatefallback ţ}\\fi}" in t
    )


def test_accent_no_precomposed_strips_mark(tmp_path: Path) -> None:
    r"""``\c{q}`` 无预组字 → 剥 accent 留 base ``q``."""
    _write_main(tmp_path, r"li\c{q}ge")
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no ̧ (U+0327) in font cmr10!\n"),
        encoding="utf-8",
    )
    ok, note = accent_mark_fix(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert r"liqge" in t
    # 无预组产出 → 不引 newunicodechar
    assert "newunicodechar" not in t


def test_accent_multichar_arg_composes_first_char(tmp_path: Path) -> None:
    r"""``\c{ts}`` 多字符实参对首字试组 → ``ţs`` (比剥净保真)."""
    _write_main(tmp_path, r"o\c{ts}y")
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no ̧ (U+0327) in font cmr10!\n"),
        encoding="utf-8",
    )
    ok, _ = accent_mark_fix(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok
    assert r"oţsy" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_accent_math_sites_untouched(tmp_path: Path) -> None:
    r"""``\'{e}`` 在 ``$..$``/``equation`` 内是 \acute 真义 → 不改写; 文本域同 cs 照改."""
    _write_main(
        tmp_path,
        "caf\\'{e} and $\\'{e}$ and\n\\begin{equation}\\'{e}\\end{equation}\n",
    )
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no ́ (U+0301) in font cmr10!\n"),
        encoding="utf-8",
    )
    ok, _ = accent_mark_fix(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "café" in t
    assert "$\\'{e}$" in t  # inline 数学域站点原样
    assert "\\begin{equation}\\'{e}\\end{equation}" in t


def test_accent_verbatim_and_comment_untouched(tmp_path: Path) -> None:
    r"""verbatim 环境体与 ``%`` 注释内的 ``\c{x}`` 不改写 (遮盖视图守卫)."""
    _write_main(
        tmp_path,
        "real \\c{t} site\n"
        "\\begin{verbatim}\n\\c{x}\n\\end{verbatim}\n"
        "% \\c{y} comment\n",
    )
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no ̧ (U+0327) in font cmr10!\n"),
        encoding="utf-8",
    )
    ok, _ = accent_mark_fix(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "real ţ site" in t
    assert "\\c{x}" in t
    assert "% \\c{y} comment" in t


def test_accent_symbol_cs_bare_letter_arg(tmp_path: Path) -> None:
    r"""符号 cs 裸字母实参 ``\~n`` → ``ñ`` (字母 cs 裸参不收 —— ``\ca`` 与长名不可分)."""
    _write_main(tmp_path, "Espa\\~n a \\c x end")
    (tmp_path / "main.log").write_text(
        _mc_log(
            "Missing character: There is no ̃ (U+0303) in font cmr10!\n"
            "Missing character: There is no ̧ (U+0327) in font cmr10!\n"
        ),
        encoding="utf-8",
    )
    ok, _ = accent_mark_fix(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "Españ a" in t
    assert r"\c x" in t  # 字母 cs 裸参不改写 (spec 保守面)


def test_accent_bbl_and_cls_rewritten(tmp_path: Path) -> None:
    r"""``.bbl``/``.cls`` 内 accent 站点同改 (1206.1954 ``\bibitem`` 人名场景)."""
    _write_main(tmp_path, "body")
    (tmp_path / "main.bbl").write_text(
        "\\bibitem{g} M. Gu\\c{t}\\u{a}\n", encoding="utf-8"
    )
    (tmp_path / "main.log").write_text(
        _mc_log(
            "Missing character: There is no ̧ (U+0327) in font [lmroman9]:mapping=tex-text;!\n"
            "Missing character: There is no ̆ (U+0306) in font [lmroman9]:mapping=tex-text;!\n"
        ),
        encoding="utf-8",
    )
    ok, _ = accent_mark_fix(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok
    assert "Guţă" in (tmp_path / "main.bbl").read_text(encoding="utf-8")


def test_accent_no_mark_cps_noop(tmp_path: Path) -> None:
    """log 无组合符缺字 → False (其余缺字不归本规则)."""
    _write_main(tmp_path, "x")
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no ≠ (U+2260) in font cmr7!\n"),
        encoding="utf-8",
    )
    ok, note = accent_mark_fix(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok is False
    assert "no combining-mark" in note


# ---------------------------------------------------------------- math_font_chars
def test_font_fallback_template_is_mode_aware(tmp_path: Path) -> None:
    r"""``\newunicodechar`` 替换体 ``\ifmmode`` 双模: 数学内逃 ``\mbox``."""
    _write_main(tmp_path, "Ж")
    (tmp_path / "main.log").write_text(
        _mc_log(
            "Missing character: There is no Ж (U+0416) in font "
            "[lmroman10-regular]:mapping=tex-text;!\n"
        ),
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, _ = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert (
        "\\newunicodechar{Ж}{\\ifmmode\\mbox{\\txlatefallback Ж}"
        "\\else{\\txlatefallback Ж}\\fi}" in t
    )


def test_math_cs_shim_injected(tmp_path: Path) -> None:
    r"""``Y$\i$lmaz`` + 数学内 ``$\L^{\phi,p}$`` → ``\i``/``\L`` shim 注入."""
    _write_main(tmp_path, "Y$\\i$lmaz and $\\L^{\\phi,p}$")
    (tmp_path / "main.log").write_text(
        _mc_log(
            "Missing character: There is no ı (U+0131) in font cmmi10!\n"
            "Missing character: There is no Ł (U+0141) in font cmmi10!\n"
        ),
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert r"\ifdefined\txlateoldi\else\let\txlateoldi\i\fi" in t
    assert r"\protected\def\i{\ifmmode\mbox{\txlateoldi}\else\txlateoldi\fi}" in t
    assert r"\protected\def\L{\ifmmode\mbox{\txlateoldL}\else\txlateoldL\fi}" in t
    assert "math cs shim" in note


def test_math_cs_shim_text_only_cs_skipped(tmp_path: Path) -> None:
    r"""``\i`` 只在文本域出现 → 不 shim (文本域缺字是 ambient 字体真缺, 不归此修)."""
    _write_main(tmp_path, "Y\\i lmaz")
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no ı (U+0131) in font cmmi10!\n"),
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok  # 字面 ı 仍走 newunicodechar 兜底 (0x131 在带内)
    assert "math cs shim" not in note
    assert "txlateoldi" not in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_math_cs_shim_outofband_cp(tmp_path: Path) -> None:
    r"""``$\S$`` 产 §(0xA7) 不在回退带 → shim 仍成立 (shim 不吃带门)."""
    _write_main(tmp_path, "see $\\S$")
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no § (U+00A7) in font cmmi10!\n"),
        encoding="utf-8",
    )
    ok, note = font_fallback(_ctx(tmp_path), MockEngine([]), None, {})
    assert ok, note
    assert "math cs shim" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert r"\protected\def\S{\ifmmode\mbox{\txlateoldS}\else\txlateoldS\fi}" in t


def test_font_fallback_double_inject_no_clash(tmp_path: Path) -> None:
    r"""两规则各注一份回退块不炸: ``\ifdefined\txlatefallback`` 守卫 + 逐字去重."""
    make_proj(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\nGu\\c{t} and Ж\n\\end{document}\n",
    )
    log1 = _mc_log(
        "Missing character: There is no ̧ (U+0327) in font [lmroman9]:mapping=tex-text;!\n",
        "Missing character: There is no Ж (U+0416) in font [lmroman10-regular]:mapping=tex-text;!\n",
    )
    log2 = _mc_log(
        "Missing character: There is no Ж (U+0416) in font [lmroman10-regular]:mapping=tex-text;!\n"
    )
    eng = MockEngine(
        [
            {"log": log1, "pdf": True},
            {"log": log2, "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        available={"newunicodechar.sty"},
    )
    cell = fixloop(tmp_path, eng)
    assert cell["verdict"] == "clean"
    rules = [a["rule"] for a in cell["actions"]]
    assert rules.index("accent_mark_fix") < rules.index("font_fallback")
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t.count("\\newunicodechar{ţ}") == 1  # 逐字去重: 不重复声明
    assert "\\ifdefined\\txlatefallback" in t


def test_fallback_cs_second_family_coexists(tmp_path: Path) -> None:
    r"""``fallback_cs`` 第二实例 (``txlatecjkfb``+FandolSong) 与首实例共存不撞名."""
    _write_main(tmp_path, "Ж 这")
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no Ж (U+0416) in font cmr10!\n"),
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, _ = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no 这 (U+8FD9) in font cmr10!\n"),
        encoding="utf-8",
    )
    ok, note = font_fallback(
        _ctx(tmp_path),
        eng,
        None,
        {
            "fallback_cs": "txlatecjkfb",
            "fallback_font": "FandolSong-Regular.otf",
            "fallback_ranges": [[0x4E00, 0x9FFF]],
        },
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\txlatefallback\\else\\newfontfamily\\txlatefallback" in t
    assert "\\newfontfamily\\txlatecjkfb{FandolSong-Regular.otf}" in t
    assert t.count("\\newfontfamily\\txlatecjkfb") == 1
    assert "\\newunicodechar{这}{\\ifmmode\\mbox{\\txlatecjkfb 这}" in t


def test_font_not_skips_cjk_font_drops(tmp_path: Path) -> None:
    r"""``font_not`` 正则命中缺字字体名 → 该 cp 跳过 (CJK 字体真缺字形不重绑)."""
    _write_main(tmp_path, "Ж 这")
    (tmp_path / "main.log").write_text(
        _mc_log(
            "Missing character: There is no Ж (U+0416) in font cmr10!\n"
            "Missing character: There is no 这 (U+8FD9) in font [FandolSong-Regular.otf]!\n"
        ),
        encoding="utf-8",
    )
    params = {
        "font_not": "Fandol|Noto.*CJK",
        "fallback_ranges": [[0x0410, 0x04FF], [0x4E00, 0x9FFF]],
    }
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, _ = font_fallback(_ctx(tmp_path), eng, None, params)
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\newunicodechar{Ж}" in t
    assert "\\newunicodechar{这}" not in t  # fandol 落字被 font_not 排


def test_font_fallback_repeat_fire_idempotent(tmp_path: Path) -> None:
    r"""二轮新 cp 再点火: 第二块 ``\ifdefined`` 守卫 ``\newfontfamily`` 不 already_def."""
    _write_main(tmp_path, "Ж л")
    (tmp_path / "main.log").write_text(
        _mc_log("Missing character: There is no Ж (U+0416) in font cmr10!\n"),
        encoding="utf-8",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    assert font_fallback(_ctx(tmp_path), eng, None, {})[0]
    (tmp_path / "main.log").write_text(
        _mc_log(
            "Missing character: There is no Ж (U+0416) in font cmr10!\n"
            "Missing character: There is no л (U+043B) in font cmr10!\n"
        ),
        encoding="utf-8",
    )
    ok, _ = font_fallback(_ctx(tmp_path), eng, None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t.count("\\ifdefined\\txlatefallback") == 2  # noqa: PLR2004 - 双块各守
    assert t.count("\\newunicodechar{Ж}") == 1  # 已声明字符不重注
    assert t.count("\\newunicodechar{л}") == 1


# ---------------------------------------------------------- 注入缝
def test_inject_after_docclass_trailing_comment(tmp_path: Path) -> None:
    r"""docclass 行尾 ``%!TEX`` pragma → snippet 落注释外下一行 (1404.0346)."""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article} %!TEX program = xelatex\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    assert _inject_after_docclass(_ctx(tmp_path), "% probe") is True
    lines = (tmp_path / "main.tex").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "\\documentclass{article} %!TEX program = xelatex"
    assert lines[1] == "% probe"  # 落新行 —— 不被行尾注释吞


# ---------------------------------------------------------------- nullfont_noise
def test_warn_missing_char_ignores_nullfont(tmp_path: Path) -> None:
    r"""纯 nullfont 缺字行 → 签名不举 → 首轮 clean (测量盒噪音不再进修复环)."""
    eng = MockEngine(
        [
            {
                "log": 'Missing character: There is no ; ("3B) in font nullfont!\n'
                'Missing character: There is no 8 ("38) in font nullfont!\n'
                "Output written on main.pdf (1 page).\n",
                "pdf": True,
            }
        ]
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "clean"
    assert "missing_char" not in cell["rounds"][0]["warnings"]


def test_warn_missing_char_still_fires_on_real_font(tmp_path: Path) -> None:
    """真字体缺字行仍举签名 —— nullfont 排除不误伤正常行."""
    eng = MockEngine(
        [
            {
                "log": "Missing character: There is no ≠ (U+2260) in font cmr7!\n"
                'Missing character: There is no ; ("3B) in font nullfont!\n'
                "Output written on main.pdf (1 page).\n",
                "pdf": True,
            },
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["rounds"][0]["category"] == "warn_missing_char"


def test_warn_signature_wrapped_nullfont_line() -> None:
    r"""wrap 续行形态: 消息跨行折行时 lookahead 窗口仍认出 nullfont."""
    text = (
        "some prefix padding Missing character: There is no ;\n"
        '("3B) in font nullfont!\n'
        "Missing character: There is no ≠ (U+2260) in font cmr7!\n"
    )
    rep = parse_text(text, Ruleset.load().warn_patterns)
    assert rep.warnings == ["missing_char"]  # 真字体行仍举 (wrap 噪音被排)


def test_warn_signature_all_nullfont_silent() -> None:
    """整 log 只有 nullfont 缺字 (含一条 wrap 续行) → 签名不举."""
    text = (
        'Missing character: There is no ; ("3B) in font nullfont!\n'
        "pad Missing character: There is no 8\n"
        '("38) in font nullfont!\n'
        "Output written on main.pdf (1 page).\n"
    )
    rep = parse_text(text, Ruleset.load().warn_patterns)
    assert rep.warnings == []


def test_mc_parse_log_skips_nullfont() -> None:
    """``_mc_parse_log`` 层兜底: nullfont 码位不进 seen (wrap 漏网双保险)."""
    seen = _mc_parse_log(
        'Missing character: There is no ; ("3B) in font nullfont!\n'
        "Missing character: There is no ≠ (U+2260) in font cmr7!\n"
    )
    assert 0x3B not in seen  # noqa: PLR2004 - 字面码位即语义
    assert seen[0x2260][1] == "cmr7"
