r"""kotexfix #196 (2026-09-19): ``missing_char_fix`` hangul 路由预分诊。

kotex/xetexko 工程谚文缺字走路由件 (xeCJK AutoFallBack +
``\setmainhangulfont`` 族), 不走 newunicodechar (catcode-12 死件) /
cjk_warmup (HG 类无效)。标记源: 2410.18001 (lmroman ×544) /
2403.00013 (FandolSong script=hani ×1355)。
"""

from pathlib import Path

from _fixloopkit import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.builtins import missing_char_fix
from texlate.compile.fixloop.engine import LoopCtx, RunFn

KOTEX_MAIN = (
    "\\documentclass{article}\n"
    "\\usepackage{ctex}\n"
    "\\usepackage{kotex}\n"
    "\\begin{document}\n박사 학위\n\\end{document}\n"
)

HANGUL_LM_LOG = (
    "Missing character: There is no 박 (U+BC15) in font "
    "[lmroman10-regular]:mapping=tex-text;!\n"
    "Missing character: There is no 학 (U+D559) in font "
    "[lmroman10-regular]:mapping=tex-text;!\n"
)


def _fc_none(argv: list, timeout: int, wdir: Path) -> tuple:
    """fc-list 全 miss 桩 (rc=0 空输出 = 查无此族)。"""
    del argv, timeout, wdir
    return 0, "", 0.0, False


def _ko_ctx(tmp_path: Path, runner: RunFn | None = None) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel="main.tex",
        runner=runner or _fc_none,
    )


def test_builtin_hangul_route_kotex_lmroman(tmp_path: Path) -> None:
    r"""2410.18001 标记: ctex+kotex 工程谚文落 lmroman → 路由件注入。

    两臂并射 ``\ifdefined`` 守: xeCJK AutoFallBack +
    ``\setCJKfallbackfamilyfont`` (rm/sf/tt) 治 CJK 类谚文,
    ``\setmainhangulfont`` 族治 HG 类谚文。注入点在 ``\begin{document}``
    行首 —— 晚于包装载的 catcode/charclass 重置, 早于 AtBeginDocument
    钩内排版。
    """
    (tmp_path / "main.tex").write_text(KOTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(HANGUL_LM_LOG, encoding="utf-8")
    eng = MockEngine([], available={"UnDotum.ttf"})
    ok, note = missing_char_fix(_ko_ctx(tmp_path), eng, None, {})
    assert ok is True
    assert "hangul route: 2 cp(s)" in note
    assert "UnDotum.ttf" in note
    t = (tmp_path / "main.tex").read_text()
    assert "\\xeCJKsetup{AutoFallBack}" in t
    assert "\\setCJKfallbackfamilyfont{\\CJKrmdefault}{UnDotum.ttf}" in t
    assert "\\setCJKfallbackfamilyfont{\\CJKsfdefault}{UnDotum.ttf}" in t
    assert "\\setCJKfallbackfamilyfont{\\CJKttdefault}{UnDotum.ttf}" in t
    assert "\\setmainhangulfont{UnDotum.ttf}" in t
    assert "\\setsanshangulfont{UnDotum.ttf}" in t
    assert "\\setmonohangulfont{UnDotum.ttf}" in t
    assert t.index("\\usepackage{kotex}") < t.index("AutoFallBack")
    assert t.index("AutoFallBack") < t.index("\\begin{document}")
    # 谚文出表 —— 暖盒不误触 (cjk_glyph 不再见谚文码位)
    assert "\\setbox0=\\hbox" not in t


def test_builtin_hangul_route_fandol_cls_mech(tmp_path: Path) -> None:
    r"""2403.00013 标记: 谚文落 FandolSong script=hani + 机制来自 shipped .cls。

    mech 探针吃 ``source_blob`` —— .cls 内 ``\RequirePackage{kotex}`` 命中
    ``_KO_MECH_RE`` (kaist-ucs.cls 内载 kotex/dhucs 实态); FandolSong 刻意
    不在 ``_KO_FONT_NOT`` (无 hangul 块正是病灶, 与 hangul_font_fallback
    font_not 同策)。
    """
    (tmp_path / "kaist-ucs.cls").write_text(
        "\\ProvidesClass{kaist-ucs}\n\\RequirePackage{kotex}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{kaist-ucs}\n\\begin{document}\n학위\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(
        "Missing character: There is no 학 (U+D559) in font "
        "[FandolSong-Regular.otf]/OT:script=hani;language=dflt;!\n",
        encoding="utf-8",
    )
    eng = MockEngine([], available={"UnDotum.ttf"})
    ok, note = missing_char_fix(_ko_ctx(tmp_path), eng, None, {})
    assert ok is True
    assert "hangul route" in note
    t = (tmp_path / "main.tex").read_text()
    assert "\\setCJKfallbackfamilyfont{\\CJKrmdefault}{UnDotum.ttf}" in t


def test_builtin_hangul_route_no_mech_declines(tmp_path: Path) -> None:
    """无 xeCJK/kotex 机制 → 路由臂不占先，谚文留表走 status-quo 链。

    无 kotex 的工程里 ``\\newunicodechar`` 逐字回退本来就是活路
    (hangul_font_fallback 末位臂接管), 路由臂 decline 不谎报。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n박\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(HANGUL_LM_LOG, encoding="utf-8")
    eng = MockEngine([], available={"UnDotum.ttf"})
    ok, note = missing_char_fix(_ko_ctx(tmp_path), eng, None, {})
    assert ok is False
    assert "no xeCJK/kotex mechanism" in note
    assert "AutoFallBack" not in (tmp_path / "main.tex").read_text()


def test_builtin_hangul_route_ko_font_not_claimed(tmp_path: Path) -> None:
    """ko-capable 字体上的谚文缺字不认领 —— 真缺字形面，留表交 unmatched。

    ``_KO_FONT_NOT`` 命中 → 码位不进 ``cps``: 同 log 里 lmroman 那条照
    认领 (``1 cp(s)``), NotoSansCJKkr 那条出路由臂视野。
    """
    (tmp_path / "main.tex").write_text(KOTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(
        "Missing character: There is no 박 (U+BC15) in font "
        "[NotoSansCJKkr-Regular.otf]/OT:script=kore;!\n"
        "Missing character: There is no 학 (U+D559) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    eng = MockEngine([], available={"UnDotum.ttf"})
    ok, note = missing_char_fix(_ko_ctx(tmp_path), eng, None, {})
    assert ok is True
    assert "hangul route: 1 cp(s)" in note


def test_builtin_hangul_route_fonts_dead_declines(tmp_path: Path) -> None:
    """ko 候选全灭 → decline 诚实交回 —— 路由件不注，末位臂照常。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{kotex}\n"
        "\\begin{document}\n박\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(HANGUL_LM_LOG, encoding="utf-8")
    eng = MockEngine([])  # probe/install/fc-list 全灭
    ok, note = missing_char_fix(_ko_ctx(tmp_path), eng, None, {})
    assert ok is False
    assert "no fallback font resolvable" in note
    assert "AutoFallBack" not in (tmp_path / "main.tex").read_text()


def test_builtin_hangul_route_idempotent(tmp_path: Path) -> None:
    """次轮同标记 → snippet 在场 → 码位仍认领出表 (暖盒不假阳性空烧)。

    自注 snippet 的 ``\\xeCJKsetup``/``\\setCJK*font`` 字样会让
    ``_CJK_MECH_RE`` 自我命中 —— 谚文留表会让暖盒误注一轮 (kotex-only
    工程本无 xeCJK 可暖), 认领出表钉死该回环。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{kotex}\n"
        "\\begin{document}\n박\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(HANGUL_LM_LOG, encoding="utf-8")
    ctx = _ko_ctx(tmp_path)
    eng = MockEngine([], available={"UnDotum.ttf"})
    assert missing_char_fix(ctx, eng, None, {})[0] is True
    ok, note = missing_char_fix(ctx, eng, None, {})
    assert ok is False
    assert "already present" in note
    t = (tmp_path / "main.tex").read_text()
    assert t.count("AutoFallBack") == 1
    assert "\\setbox0=\\hbox" not in t


def test_builtin_hangul_route_commented_begindoc_skipped(tmp_path: Path) -> None:
    r"""``%\begin{document}`` 死锚不落 —— 首个活锚行首注入 (遮盖面钉死)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{kotex}\n"
        "%\\begin{document} dead\n"
        "\\begin{document}\n박\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.log").write_text(HANGUL_LM_LOG, encoding="utf-8")
    eng = MockEngine([], available={"UnDotum.ttf"})
    ok, _note = missing_char_fix(_ko_ctx(tmp_path), eng, None, {})
    assert ok is True
    t = (tmp_path / "main.tex").read_text()
    dead = t.index("%\\begin{document} dead")
    live = t.index("\\begin{document}\n박")
    assert dead < t.index("AutoFallBack") < live


def test_builtin_hangul_route_fc_family_fallback(tmp_path: Path) -> None:
    """UnDotum probe+install 双败 → fc-list 家族名候选接管绑定。"""
    (tmp_path / "main.tex").write_text(KOTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(HANGUL_LM_LOG, encoding="utf-8")

    def _fc_noto(argv: list, timeout: int, wdir: Path) -> tuple:
        del timeout, wdir
        if argv[0] == "fc-list" and argv[1] == "Noto Sans CJK KR":
            return 0, "Noto Sans CJK KR\n", 0.0, False
        return 0, "", 0.0, False

    eng = MockEngine([])
    ok, note = missing_char_fix(_ko_ctx(tmp_path, runner=_fc_noto), eng, None, {})
    assert ok is True
    assert "Noto Sans CJK KR" in note
    t = (tmp_path / "main.tex").read_text()
    assert "\\setmainhangulfont{Noto Sans CJK KR}" in t
    assert eng.install_calls == ["UnDotum.ttf"]


def test_builtin_hangul_route_ko_fonts_param_override(tmp_path: Path) -> None:
    """``params.ko_fonts`` 覆盖候选表 —— yaml 参数面直放钉死。"""
    (tmp_path / "main.tex").write_text(KOTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(HANGUL_LM_LOG, encoding="utf-8")
    eng = MockEngine([], available={"MyKo.otf"})
    ok, _note = missing_char_fix(
        _ko_ctx(tmp_path), eng, None, {"ko_fonts": ["MyKo.otf"]}
    )
    assert ok is True
    assert "\\setmainhangulfont{MyKo.otf}" in (tmp_path / "main.tex").read_text()


def test_builtin_hangul_route_claims_only_hangul(tmp_path: Path) -> None:
    """混合缺字：谚文归路由臂，非谚文 CJK 仍走 cjk_warmup —— 认领外科手术。"""
    (tmp_path / "main.tex").write_text(KOTEX_MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(
        "Missing character: There is no 박 (U+BC15) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Missing character: There is no 欠 (U+6B20) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
        encoding="utf-8",
    )
    eng = MockEngine([], available={"UnDotum.ttf"})
    ok, note = missing_char_fix(_ko_ctx(tmp_path), eng, None, {})
    assert ok is True
    assert "hangul route: 1 cp(s)" in note
    assert "warmup" in note
    t = (tmp_path / "main.tex").read_text()
    assert "AutoFallBack" in t
    assert "\\setbox0=\\hbox" in t


def test_loop_hangul_route_e2e(tmp_path: Path) -> None:
    r"""实装 ruleset 端到端: kotex 工程谚文缺字 → missing_char_fix(25)
    路由件认领 → hangul_font_fallback(28) 不发 (码位已出表)。"""
    eng = MockEngine(
        [
            {
                "log": HANGUL_LM_LOG + "Output written on main.pdf (1 page).\n",
                "pdf": True,
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        available={"UnDotum.ttf"},
    )
    cell = fixloop(make_proj(tmp_path, KOTEX_MAIN), eng)
    assert cell["verdict"] == "clean"
    rules = [a["rule"] for a in cell["actions"]]
    assert "missing_char_fix" in rules
    assert "hangul_font_fallback" not in rules
    t = (tmp_path / "main.tex").read_text()
    assert "AutoFallBack" in t
    assert "xeCJK bind warmup" not in t
