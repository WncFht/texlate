"""hangul 缺字专臂 —— hangul_font_fallback (60-misschar.yaml order 28)。

谚文码位 (U+AC00-D7A3 音节 + jamo 四段) 落无 hangul 块字体 →
``font_fallback`` builtin 经 ``params.fallback_fonts`` 有序候选探测
(文件形 kpathsea / 家族名 fc-list) 绑首个可解析 ko 字体;
cjk_font_fallback 带表已剔出谚文段 (FandolSong 无 hangul 块,
绑回 = 错字体谎报), 全候选灭 → decline 不谎报。
"""

from pathlib import Path

from _fixloopkit import MockEngine

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.builtins import font_fallback
from texlate.compile.fixloop.engine import LoopCtx, RunFn

#: 与 60-misschar.yaml hangul_font_fallback.params 同形 (直测参数面)。
KO_PARAMS = {
    "fallback_ranges": [
        [0x1100, 0x11FF],
        [0x3130, 0x318F],
        [0xA960, 0xA97C],
        [0xAC00, 0xD7A3],
        [0xD7B0, 0xD7FB],
    ],
    "fallback_fonts": [
        {"name": "UnDotum.ttf", "install": True},
        "Noto Sans CJK KR",
        "IBM Plex Sans KR",
        "Nanum Gothic",
        "Malgun Gothic",
    ],
    "fallback_cs": "txlatekofb",
    "font_not": (
        "noto.*(cjk|kr|korean)|source.?han|sarasa|hanazono|nanum|malgun|kopub|"
        "plex.*kr|apple|batang|dotum|gulim|gungsuh|myeongjo|dinaru|"
        "un(batang|dotum|graphic|pilgi|gungseo|dinaru|shinmun|yetgul|pen|taza|"
        "vada|park|jamo|bom|yeti|sora)|hcr|hamchorom|jamo|baekmuk|"
        "droid.*fallback|wqy|lxgw"
    ),
}

MAIN = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"


def _ctx(tmp_path: Path, runner: RunFn | None = None) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=runner
    )


def _proj(tmp_path: Path, log: str) -> None:
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    (tmp_path / "main.log").write_text(log, encoding="utf-8")


def _fc_none(argv: list, timeout: int, wdir: Path) -> tuple:
    """fc-list 全 miss 桩 (rc=0 空输出 = 查无此族)。"""
    del argv, timeout, wdir
    return 0, "", 0.0, False


def test_hangul_syllable_in_lmroman_binds_undotum(tmp_path: Path) -> None:
    """谚文音节缺字落 lmroman (2410.18001 签名) → 绑 TL unfonts UnDotum。

    文件形候选 ``UnDotum.ttf`` probe 命中即胜, 不经 fc-list。
    """
    _proj(
        tmp_path,
        "Missing character: There is no 박 (U+BC15) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n",
    )
    eng = MockEngine([], available={"newunicodechar.sty", "UnDotum.ttf"})
    ok, note = font_fallback(_ctx(tmp_path, runner=_fc_none), eng, None, KO_PARAMS)
    assert ok is True
    assert "UnDotum.ttf" in note
    t = (tmp_path / "main.tex").read_text()
    assert "\\newfontfamily\\txlatekofb{UnDotum.ttf}" in t
    assert (
        "\\newunicodechar{박}{\\ifmmode\\mbox{\\txlatekofb 박}"
        "\\else{\\txlatekofb 박}\\fi}" in t
    )


def test_hangul_in_fandol_still_selected(tmp_path: Path) -> None:
    """谚文落 FandolSong (2403.00013 签名) —— font_not 刻意不收 fandol。

    Fandol 系无 hangul 块正是病灶; 旧 cjk 臂 font_not 含 fandol 只挡
    自己那臂, 本臂必须照样选上。
    """
    _proj(
        tmp_path,
        "Missing character: There is no 학 (U+D559) in font "
        "[FandolSong-Regular.otf]/OT:script=hani;language=dflt;!\n",
    )
    eng = MockEngine([], available={"newunicodechar.sty", "UnDotum.ttf"})
    ok, _note = font_fallback(_ctx(tmp_path, runner=_fc_none), eng, None, KO_PARAMS)
    assert ok is True
    assert "\\newunicodechar{학}" in (tmp_path / "main.tex").read_text()


def test_hangul_in_ko_capable_font_declines(tmp_path: Path) -> None:
    """谚文落本已覆盖 hangul 的字体 (NotoSansCJKkr) → 真缺字形 → 不动。"""
    _proj(
        tmp_path,
        "Missing character: There is no ퟋ (U+D7CB) in font "
        "[NotoSansCJKkr-Regular.otf]/OT:script=kore;!\n",
    )
    eng = MockEngine([], available={"newunicodechar.sty", "UnDotum.ttf"})
    ok, note = font_fallback(_ctx(tmp_path, runner=_fc_none), eng, None, KO_PARAMS)
    assert ok is False
    assert "no missing chars in fallback bands" in note
    assert "txlatekofb" not in (tmp_path / "main.tex").read_text()


def test_hangul_in_ipa_japanese_font_still_selected(tmp_path: Path) -> None:
    """谚文落 uming (IPA 日系, 无 hangul 块) —— font_not 不收 uming/ukai。

    IPA 日文字体只盖假名/汉字, 谚文照缺 → 本臂必须认领绑 ko 字体。
    """
    _proj(
        tmp_path,
        "Missing character: There is no 박 (U+BC15) in font "
        "[uming.ttc]/OT:script=kana;!\n",
    )
    eng = MockEngine([], available={"newunicodechar.sty", "UnDotum.ttf"})
    ok, _note = font_fallback(_ctx(tmp_path, runner=_fc_none), eng, None, KO_PARAMS)
    assert ok is True
    assert "\\newunicodechar{박}" in (tmp_path / "main.tex").read_text()


def test_jamo_bands_covered(tmp_path: Path) -> None:
    """jamo 四段边样 (U+1100/U+3131/U+A960/U+D7B0) 均在带表内。"""
    _proj(
        tmp_path,
        "Missing character: There is no ᄀ (U+1100) in font cmr10!\n"
        "Missing character: There is no ㄱ (U+3131) in font cmr10!\n"
        "Missing character: There is no ꥠ (U+A960) in font cmr10!\n"
        "Missing character: There is no ힰ (U+D7B0) in font cmr10!\n",
    )
    eng = MockEngine([], available={"newunicodechar.sty", "UnDotum.ttf"})
    ok, _note = font_fallback(_ctx(tmp_path, runner=_fc_none), eng, None, KO_PARAMS)
    assert ok is True
    t = (tmp_path / "main.tex").read_text()
    for ch in "ᄀㄱꥠힰ":
        assert f"\\newunicodechar{{{ch}}}" in t


def test_fc_candidate_when_file_font_absent(tmp_path: Path) -> None:
    """UnDotum probe+install 双败 → fc-list 命中家族名候选接管。"""
    _proj(
        tmp_path,
        "Missing character: There is no 박 (U+BC15) in font cmr10!\n",
    )

    def _fc_plex(argv: list, timeout: int, wdir: Path) -> tuple:
        del timeout, wdir
        if argv[0] == "fc-list" and argv[1] == "IBM Plex Sans KR":
            return 0, "IBM Plex Sans KR\n", 0.0, False
        return 0, "", 0.0, False

    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path, runner=_fc_plex), eng, None, KO_PARAMS)
    assert ok is True
    assert "IBM Plex Sans KR" in note
    t = (tmp_path / "main.tex").read_text()
    assert "\\newfontfamily\\txlatekofb{IBM Plex Sans KR}" in t
    assert eng.install_calls == ["UnDotum.ttf"]  # install:true 候选试过补装


def test_install_path_recovers_file_font(tmp_path: Path) -> None:
    """UnDotum probe miss → install:true 补装成功 → 复核命中绑定。"""
    _proj(
        tmp_path,
        "Missing character: There is no 박 (U+BC15) in font cmr10!\n",
    )
    eng = MockEngine(
        [],
        available={"newunicodechar.sty"},
        installable={"UnDotum.ttf"},
    )
    ok, _note = font_fallback(_ctx(tmp_path, runner=_fc_none), eng, None, KO_PARAMS)
    assert ok is True
    assert (
        "\\newfontfamily\\txlatekofb{UnDotum.ttf}"
        in (tmp_path / "main.tex").read_text()
    )


def test_all_candidates_dead_declines(tmp_path: Path) -> None:
    """全候选不可解析 → decline 不谎报 (诚实 unfixable, 非错字体声明)。"""
    _proj(
        tmp_path,
        "Missing character: There is no 박 (U+BC15) in font cmr10!\n",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path, runner=_fc_none), eng, None, KO_PARAMS)
    assert ok is False
    assert "no fallback font resolvable" in note
    assert "txlatekofb" not in (tmp_path / "main.tex").read_text()


def test_non_hangul_cjk_untouched_by_ko_arm(tmp_path: Path) -> None:
    """CJK 码位 (U+8FD9) 不在谚文带 → 本臂不选, 仍归 cjk 臂。"""
    _proj(
        tmp_path,
        'Missing character: There is no 这 ("8FD9) in font futr8t!\n',
    )
    eng = MockEngine([], available={"newunicodechar.sty", "UnDotum.ttf"})
    ok, note = font_fallback(_ctx(tmp_path, runner=_fc_none), eng, None, KO_PARAMS)
    assert ok is False
    assert "no missing chars in fallback bands" in note


def test_cjk_arm_ranges_no_longer_claim_hangul(tmp_path: Path) -> None:
    """cjk_font_fallback 带表剔出谚文段 —— 同 log 下不再绑 FandolSong。

    钉死带表收窄: 谚文若仍被 cjk 臂认领 = FandolSong 错绑回潮。
    """
    _proj(
        tmp_path,
        "Missing character: There is no 박 (U+BC15) in font futr8t!\n",
    )
    rule = next(r for r in load_ruleset().phase("loop") if r.id == "cjk_font_fallback")
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(_ctx(tmp_path), eng, None, dict(rule.action["params"]))
    assert ok is False
    assert "no missing chars in fallback bands" in note


def test_shipped_rule_params_bind_ko_font(tmp_path: Path) -> None:
    """实装规则参数面直放: 库内 hangul_font_fallback 参数 → UnDotum 绑定。"""
    _proj(
        tmp_path,
        "Missing character: There is no 박 (U+BC15) in font cmr10!\n",
    )
    rule = next(
        r for r in load_ruleset().phase("loop") if r.id == "hangul_font_fallback"
    )
    assert rule.order == 28  # noqa: PLR2004 - cjk(27) 后位次钉死
    eng = MockEngine([], available={"newunicodechar.sty", "UnDotum.ttf"})
    ok, _note = font_fallback(
        _ctx(tmp_path, runner=_fc_none), eng, None, dict(rule.action["params"])
    )
    assert ok is True
    t = (tmp_path / "main.tex").read_text()
    assert "\\newfontfamily\\txlatekofb{UnDotum.ttf}" in t
    assert "\\newunicodechar{박}" in t


def test_hangul_and_cjk_chars_split_across_arms(tmp_path: Path) -> None:
    """混合缺字格: CJK 归 txlatecjkfb/FandolSong, 谚文归 txlatekofb/ ko 字体。

    两臂顺序直放 (loop 跨轮各发一次): 注入块互不吞字, cs 并存。
    """
    _proj(
        tmp_path,
        'Missing character: There is no 这 ("8FD9) in font futr8t!\n'
        "Missing character: There is no 박 (U+BC15) in font futr8t!\n",
    )
    rs = load_ruleset()
    cjk = next(r for r in rs.phase("loop") if r.id == "cjk_font_fallback")
    ko = next(r for r in rs.phase("loop") if r.id == "hangul_font_fallback")
    ctx = _ctx(tmp_path, runner=_fc_none)
    eng = MockEngine([], available={"newunicodechar.sty", "UnDotum.ttf"})
    ok1, _ = font_fallback(ctx, eng, None, dict(cjk.action["params"]))
    ok2, _ = font_fallback(ctx, eng, None, dict(ko.action["params"]))
    assert ok1
    assert ok2
    t = (tmp_path / "main.tex").read_text()
    assert "\\newfontfamily\\txlatecjkfb{FandolSong-Regular.otf}" in t
    assert "\\newfontfamily\\txlatekofb{UnDotum.ttf}" in t
    assert "\\newunicodechar{这}" in t
    assert "\\newunicodechar{박}" in t


def test_legacy_single_font_path_untouched(tmp_path: Path) -> None:
    """旧 ``fallback_font`` 单值路不探测 —— 字体缺席也照绑 (行为钉死)。"""
    _proj(
        tmp_path,
        "Missing character: There is no Ж (U+0416) in font cmr10!\n",
    )
    eng = MockEngine([], available={"newunicodechar.sty"})
    ok, note = font_fallback(
        _ctx(tmp_path),
        eng,
        None,
        {"fallback_ranges": [[0x400, 0x4FF]], "fallback_font": "NoSuchFont"},
    )
    assert ok is True
    assert "NoSuchFont" in note


def test_fixloop_e2e_dispatches_both_arms(tmp_path: Path) -> None:
    """真环路派发钉: 混合缺字格 cjk(27) 先吃汉字, 谚文臂(28) 次轮认领谚文。

    序位非认领依据 —— 两臂带表已互不重叠, 各轮第一命中臂独享。文中
    ``\\newfontfamily`` 注入块不触发 ``_CJK_MECH_RE`` 误判
    (``newfontfamily`` ≠ ``newCJKfontfamily``)。
    """
    from _fixloopkit import CLEAN_LOG, make_proj  # noqa: PLC0415

    from texlate.compile.fixloop import fixloop  # noqa: PLC0415

    make_proj(tmp_path)
    log1 = (
        "Missing character: There is no 가 (U+AC00) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        'Missing character: There is no 这 ("8FD9) in font cmr10!\n'
        "Output written on main.pdf (1 page).\n"
    )
    log2 = (
        "Missing character: There is no 가 (U+AC00) in font "
        "[lmroman10-regular]:mapping=tex-text;!\n"
        "Output written on main.pdf (1 page).\n"
    )
    eng = MockEngine(
        [
            {"log": log1, "pdf": True},
            {"log": log2, "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        available={"newunicodechar.sty", "UnDotum.ttf"},
    )
    cell = fixloop(tmp_path, eng)
    assert cell["verdict"] == "clean"
    rules = [
        a["rule"]
        for a in cell["actions"]
        if a["rule"] in {"cjk_font_fallback", "hangul_font_fallback"}
    ]
    assert rules == ["cjk_font_fallback", "hangul_font_fallback"]
    t = (tmp_path / "main.tex").read_text()
    assert "\\newfontfamily\\txlatecjkfb{FandolSong-Regular.otf}" in t
    assert "\\newfontfamily\\txlatekofb{UnDotum.ttf}" in t
    assert "\\newunicodechar{这}{\\ifmmode\\mbox{\\txlatecjkfb 这}" in t
    assert "\\newunicodechar{가}{\\ifmmode\\mbox{\\txlatekofb 가}" in t
