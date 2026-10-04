"""scout-misschar-coverage 2026-09-17 三项修复的审计测试。

- accent_mark_fix: accent cs 生成的组合符 (U+0300-036F) 非输入字符，
  newunicodechar 拦不到 → 源级 ``\\<cs>{x}`` 站点改写预组字/剥 accent.
- math_font_chars: font_fallback ``\\ifmmode`` 模板 + 文本字母 cs 数学域 shim.
- nullfont_noise: missing_char 标记排除 ``in font nullfont`` 测量盒噪音。
"""

from collections.abc import Callable
from pathlib import Path

from _fixloopkit import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.builtins import (
    _inject_after_docclass,
    _mc_parse_log,
    accent_mark_fix,
    font_fallback,
)
from texlate.compile.fixloop.engine import LoopCtx, Ruleset
from texlate.compile.logparse import parse_text


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _write_main(tmp_path: Path, body: str) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n",
        encoding="utf-8",
    )


def _mc_log(*lines: str) -> str:
    return "".join(lines) + "Output written on main.pdf (1 page).\n"


def _drive_rule(
    tmp_path: Path,
    rule_fn: Callable[..., tuple[bool, str]],
    body: str | None,
    *log_lines: str,
    eng: MockEngine | None = None,
    params: dict[str, object] | None = None,
) -> tuple[bool, str]:
    """规则直驱三件套：``body`` 非 None 重写 main.tex、写 main.log、调 rule_fn。

    ``body=None`` 跳过 main.tex 重写——复点火用例靠它保住首轮注入的声明。
    """
    if body is not None:
        _write_main(tmp_path, body)
    (tmp_path / "main.log").write_text(_mc_log(*log_lines), encoding="utf-8")
    return rule_fn(_ctx(tmp_path), eng or MockEngine([]), None, params or {})


# ---------------------------------------------------------------- accent_mark_fix
def test_accent_sites_rewritten_and_fallback_self_injected(tmp_path: Path) -> None:
    r"""``Gu\c{t}\u{a}`` → ``Guţă``: 预组字面量 + 自注 newunicodechar 回退行.

    0327/0306 组合符由 accent 机制生成非输入字符 —— 自注行是必要的
    (applied-key 一次性, font_fallback 同格不再触火).
    """
    ok, note = _drive_rule(
        tmp_path,
        accent_mark_fix,
        r"M. Gu\c{t}\u{a} done",
        "Missing character: There is no ̧ (U+0327) in font [lmroman9-regular]:mapping=tex-text;!\n",
        "Missing character: There is no ̆ (U+0306) in font [lmroman9-regular]:mapping=tex-text;!\n",
        eng=MockEngine([], available={"newunicodechar.sty"}),
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert r"Guţă" in t
    assert r"\c{t}" not in t
    assert r"\u{a}" not in t
    assert "\\RequirePackage{newunicodechar}" in t
    assert (
        "\\newunicodechar{ţ}{\\ifmmode\\mbox{\\txlatefallback ţ}"
        "\\else{\\txlatefallback ţ}\\fi}" in t
    )


def test_accent_no_precomposed_strips_mark(tmp_path: Path) -> None:
    r"""``\c{q}`` 无预组字 → 剥 accent 留 base ``q``."""
    ok, note = _drive_rule(
        tmp_path,
        accent_mark_fix,
        r"li\c{q}ge",
        "Missing character: There is no ̧ (U+0327) in font cmr10!\n",
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert r"liqge" in t
    # 无预组产出 → 不引 newunicodechar
    assert "newunicodechar" not in t


def test_accent_multichar_arg_composes_first_char(tmp_path: Path) -> None:
    r"""``\c{ts}`` 多字符实参对首字试组 → ``ţs`` (比剥净保真)."""
    ok, _ = _drive_rule(
        tmp_path,
        accent_mark_fix,
        r"o\c{ts}y",
        "Missing character: There is no ̧ (U+0327) in font cmr10!\n",
    )
    assert ok
    assert r"oţsy" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_accent_math_sites_untouched(tmp_path: Path) -> None:
    r"""``\'{e}`` 在 ``$..$``/``equation`` 内是 \acute 真义 → 不改写; 文本域同 cs 照改."""
    ok, _ = _drive_rule(
        tmp_path,
        accent_mark_fix,
        "caf\\'{e} and $\\'{e}$ and\n\\begin{equation}\\'{e}\\end{equation}\n",
        "Missing character: There is no ́ (U+0301) in font cmr10!\n",
    )
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "café" in t
    assert "$\\'{e}$" in t  # inline 数学域站点原样
    assert "\\begin{equation}\\'{e}\\end{equation}" in t


def test_accent_verbatim_and_comment_untouched(tmp_path: Path) -> None:
    r"""verbatim 环境体与 ``%`` 注释内的 ``\c{x}`` 不改写 (遮盖视图守卫)."""
    ok, _ = _drive_rule(
        tmp_path,
        accent_mark_fix,
        "real \\c{t} site\n"
        "\\begin{verbatim}\n\\c{x}\n\\end{verbatim}\n"
        "% \\c{y} comment\n",
        "Missing character: There is no ̧ (U+0327) in font cmr10!\n",
    )
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "real ţ site" in t
    assert "\\c{x}" in t
    assert "% \\c{y} comment" in t


def test_accent_symbol_cs_bare_letter_arg(tmp_path: Path) -> None:
    r"""符号 cs 裸字母实参 ``\~n`` → ``ñ`` (字母 cs 裸参不收 —— ``\ca`` 与长名不可分)."""
    ok, _ = _drive_rule(
        tmp_path,
        accent_mark_fix,
        "Espa\\~n a \\c x end",
        "Missing character: There is no ̃ (U+0303) in font cmr10!\n"
        "Missing character: There is no ̧ (U+0327) in font cmr10!\n",
    )
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "Españ a" in t
    assert r"\c x" in t  # 字母 cs 裸参不改写 (spec 保守面)


def test_accent_bbl_and_cls_rewritten(tmp_path: Path) -> None:
    r"""``.bbl``/``.cls`` 内 accent 站点同改 (1206.1954 ``\bibitem`` 人名场景)."""
    (tmp_path / "main.bbl").write_text(
        "\\bibitem{g} M. Gu\\c{t}\\u{a}\n", encoding="utf-8"
    )
    (tmp_path / "main.cls").write_text(
        "\\ProvidesClass{main}\n\\newcommand{\\who}{Gu\\c{t}\\u{a}}\n",
        encoding="utf-8",
    )
    ok, _ = _drive_rule(
        tmp_path,
        accent_mark_fix,
        "body",
        "Missing character: There is no ̧ (U+0327) in font [lmroman9]:mapping=tex-text;!\n"
        "Missing character: There is no ̆ (U+0306) in font [lmroman9]:mapping=tex-text;!\n",
    )
    assert ok
    assert "Guţă" in (tmp_path / "main.bbl").read_text(encoding="utf-8")
    assert "Guţă" in (tmp_path / "main.cls").read_text(encoding="utf-8")


def test_accent_no_mark_cps_noop(tmp_path: Path) -> None:
    """log 无组合符缺字 → False (其余缺字不归本规则)."""
    ok, note = _drive_rule(
        tmp_path,
        accent_mark_fix,
        "x",
        "Missing character: There is no ≠ (U+2260) in font cmr7!\n",
    )
    assert ok is False
    assert "no combining-mark" in note


# ---------------------------------------------------------------- math_font_chars
def test_font_fallback_template_is_mode_aware(tmp_path: Path) -> None:
    r"""``\newunicodechar`` 替换体 ``\ifmmode`` 双模: 数学内逃 ``\mbox``."""
    ok, _ = _drive_rule(
        tmp_path,
        font_fallback,
        "Ж",
        "Missing character: There is no Ж (U+0416) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        eng=MockEngine([], available={"newunicodechar.sty"}),
    )
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert (
        "\\newunicodechar{Ж}{\\ifmmode\\mbox{\\txlatefallback Ж}"
        "\\else{\\txlatefallback Ж}\\fi}" in t
    )


def test_math_cs_shim_injected(tmp_path: Path) -> None:
    r"""``Y$\i$lmaz`` + 数学内 ``$\L^{\phi,p}$`` → ``\i``/``\L`` shim 注入."""
    ok, note = _drive_rule(
        tmp_path,
        font_fallback,
        "Y$\\i$lmaz and $\\L^{\\phi,p}$",
        "Missing character: There is no ı (U+0131) in font cmmi10!\n"
        "Missing character: There is no Ł (U+0141) in font cmmi10!\n",
        eng=MockEngine([], available={"newunicodechar.sty"}),
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert r"\ifdefined\txlateoldi\else\let\txlateoldi\i\fi" in t
    assert r"\protected\def\i{\ifmmode\mbox{\txlateoldi}\else\txlateoldi\fi}" in t
    assert r"\protected\def\L{\ifmmode\mbox{\txlateoldL}\else\txlateoldL\fi}" in t
    assert "math cs shim" in note


def test_math_cs_shim_text_only_cs_skipped(tmp_path: Path) -> None:
    r"""``\i`` 只在文本域出现 → 不 shim (文本域缺字是 ambient 字体真缺, 不归此修)."""
    ok, note = _drive_rule(
        tmp_path,
        font_fallback,
        "Y\\i lmaz",
        "Missing character: There is no ı (U+0131) in font cmmi10!\n",
        eng=MockEngine([], available={"newunicodechar.sty"}),
    )
    assert ok  # 字面 ı 仍走 newunicodechar 兜底 (0x131 在带内)
    assert "math cs shim" not in note
    assert "txlateoldi" not in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_math_cs_shim_outofband_cp(tmp_path: Path) -> None:
    r"""``$\S$`` 产 §(0xA7) 不在回退带 → shim 仍成立 (shim 不吃带门)."""
    ok, note = _drive_rule(
        tmp_path,
        font_fallback,
        "see $\\S$",
        "Missing character: There is no § (U+00A7) in font cmmi10!\n",
    )
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
    assert t.count("\\newunicodechar{ţ}") == 1  # 逐字去重：不重复声明
    assert "\\ifdefined\\txlatefallback" in t


def test_fallback_cs_second_family_coexists(tmp_path: Path) -> None:
    r"""``fallback_cs`` 第二实例 (``txlatecjkfb``+FandolSong) 与首实例共存不撞名."""
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, _ = _drive_rule(
        tmp_path,
        font_fallback,
        "Ж 这",
        "Missing character: There is no Ж (U+0416) in font cmr10!\n",
        eng=eng,
    )
    assert ok
    ok, note = _drive_rule(
        tmp_path,
        font_fallback,
        None,  # 复点火不重写 main.tex——保住首轮注入的声明
        "Missing character: There is no 这 (U+8FD9) in font cmr10!\n",
        eng=eng,
        params={
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
    ok, _ = _drive_rule(
        tmp_path,
        font_fallback,
        "Ж 这",
        "Missing character: There is no Ж (U+0416) in font cmr10!\n"
        "Missing character: There is no 这 (U+8FD9) in font [FandolSong-Regular.otf]!\n",
        eng=MockEngine([], available={"newunicodechar.sty"}),
        params={
            "font_not": "Fandol|Noto.*CJK",
            "fallback_ranges": [[0x0410, 0x04FF], [0x4E00, 0x9FFF]],
        },
    )
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\newunicodechar{Ж}" in t
    assert "\\newunicodechar{这}" not in t  # fandol 落字被 font_not 排


def test_font_fallback_repeat_fire_idempotent(tmp_path: Path) -> None:
    r"""二轮新 cp 再点火: 第二块 ``\ifdefined`` 守卫 ``\newfontfamily`` 不 already_def."""
    eng = MockEngine([], available={"newunicodechar.sty"})
    assert _drive_rule(
        tmp_path,
        font_fallback,
        "Ж л",
        "Missing character: There is no Ж (U+0416) in font cmr10!\n",
        eng=eng,
    )[0]
    ok, _ = _drive_rule(
        tmp_path,
        font_fallback,
        None,  # 复点火不重写 main.tex
        "Missing character: There is no Ж (U+0416) in font cmr10!\n"
        "Missing character: There is no л (U+043B) in font cmr10!\n",
        eng=eng,
    )
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
    r"""纯 nullfont 缺字行 → 标记不举 → 首轮 clean (测量盒噪音不再进修复环)."""
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
    """真字体缺字行仍举标记 —— nullfont 排除不误伤正常行."""
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
    """整 log 只有 nullfont 缺字 (含一条 wrap 续行) → 标记不举."""
    text = (
        'Missing character: There is no ; ("3B) in font nullfont!\n'
        "pad Missing character: There is no 8\n"
        '("38) in font nullfont!\n'
        "Output written on main.pdf (1 page).\n"
    )
    rep = parse_text(text, Ruleset.load().warn_patterns)
    assert rep.warnings == []


def test_mc_parse_log_skips_nullfont() -> None:
    """``_mc_parse_log`` 层兜底：nullfont 码位不进 seen (wrap 漏网双保险)."""
    seen = _mc_parse_log(
        'Missing character: There is no ; ("3B) in font nullfont!\n'
        "Missing character: There is no ≠ (U+2260) in font cmr7!\n"
    )
    assert 0x3B not in seen  # noqa: PLR2004 - 字面码位即语义
    assert seen[0x2260][1] == "cmr7"


# ---------------------------------------------------------------- misschars4 #190
def test_math_cs_shim_wrapped_atbegindocument(tmp_path: Path) -> None:
    r"""shim let+def 走 ``\AtBeginDocument`` 迟延注册 —— hyperref 在
    ``begindocument/before`` 预钩段重声明文本命令族, 导言区即时 ``\def``
    会被复回 kernel 原义 (1404.0332 ``\i`` shim 在场仍缺字实证;
    probe t4/t9 即时形失效 vs t7/t8 hook 迟延存活)。"""
    ok, note = _drive_rule(
        tmp_path,
        font_fallback,
        "Y$\\i$lmaz",
        "Missing character: There is no ı (U+0131) in font cmmi10!\n",
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert (
        r"\AtBeginDocument{\ifdefined\txlateoldi\else\let\txlateoldi\i\fi"
        r"\protected\def\i{\ifmmode\mbox{\txlateoldi}\else\txlateoldi\fi}}" in t
    )


def test_math_cs_shim_th_thorn(tmp_path: Path) -> None:
    r"""``$M_{\th}$`` 数学域产 þ(0xFE) → ``\th`` 无参 shim
    (#190 ``_MATH_SHIM_CS`` produced_by 注册 ``\th``/``\TH``)。"""
    ok, note = _drive_rule(
        tmp_path,
        font_fallback,
        "ordinals $M_{\\th}$ tail",
        "Missing character: There is no þ (U+00FE) in font cmmi10!\n",
    )
    assert ok, note
    assert "math cs shim" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert (
        r"\AtBeginDocument{\ifdefined\txlateoldth\else\let\txlateoldth\th\fi"
        r"\protected\def\th{\ifmmode\mbox{\txlateoldth}\else\txlateoldth\fi}}" in t
    )


def test_math_cs_shim_arg_cs_ring(tmp_path: Path) -> None:
    r"""带参 accent cs ``$\r{A}$`` 产 Å(0xC5) → ``\r#1`` 实参重花括透传
    shim (0806.3530 ``$\r{A}$`` Å-in-cmmi9 实证; ``_MATH_SHIM_ARG_CS``
    触发门 = 全预组面 C5/E5/16E/16F)。"""
    ok, note = _drive_rule(
        tmp_path,
        font_fallback,
        "radius $\\r{A}$ ngstrom",
        "Missing character: There is no Å (U+00C5) in font cmmi9!\n",
    )
    assert ok, note
    assert "math cs shim" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert (
        r"\AtBeginDocument{\ifdefined\txlateoldr\else\let\txlateoldr\r\fi"
        r"\protected\def\r#1{\ifmmode\mbox{\txlateoldr{#1}}"
        r"\else\txlateoldr{#1}\fi}}" in t
    )


def test_math_cs_shim_arg_cs_text_only_skipped(tmp_path: Path) -> None:
    r"""``\r{A}`` 只在文本域 → 不 shim (同无参臂双信号门: 站点须在数学 span)。"""
    ok, note = _drive_rule(
        tmp_path,
        font_fallback,
        "radius \\r{A}ngstrom",
        "Missing character: There is no Å (U+00C5) in font cmmi9!\n",
        eng=MockEngine([], available={"newunicodechar.sty"}),
    )
    assert ok, note  # 带内码位仍走 newunicodechar 兜底; 只断言不 shim
    assert "math cs shim" not in note
    assert "txlateoldr" not in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_producer_map_th_thorn_registered() -> None:
    r"""``_MATH_SHIM_CS`` ``\th``/``\TH`` → 0xFE/0xDE 同入 cs_rebind
    ``_producer_map`` 产出表 —— produced_by 注册点 (共享表反转喂双臂)。"""
    from texlate.compile.fixloop.builtins.csbind import (  # noqa: PLC0415
        _producer_map,
    )

    producers = _producer_map({})
    assert producers[0xFE] == "th"
    assert producers[0xDE] == "TH"
