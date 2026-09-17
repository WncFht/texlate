r"""跨层一致性 fuzz —— ``texlog.update_file_stack`` → ``engine.parse_log`` /
``l2.parse_log_text`` / ``fixloop.logparse.parse_text`` → ``judge`` 门控。

四层各自独立实现同一套 log 语义，本文件只测**跨层协议不变量**：

- misschar 划分：``_MISSCHAR_GATE_RX``（判入）+ ``_MISSCHAR_NULLFONT_RX``
  （良性观察）应恰好覆盖全部 ``Missing character`` 出现位——两支正则只在
  lookahead 正负号上不同，划分须逐点成立；rules.yaml ``missing_char`` 与
  engine ``WARNING_RED_LINES[missing_chars]`` 是同源第三/第四副本。
- 折行/交错对抗：nullfont 行的 ``in font nullfont`` 落续行仍豁免；真字体
  行紧邻 nullfont 行不被误豁免（tempered 窗限界到下一条 misschar）。
- l2 ``by_class`` 缺字四分类（missing_glyph / missing_glyph_cjk /
  fffd_glyph / missing_glyph_nullfont）与逐行 census 一致；
  ``sys_hits`` 只允许 ``invalid_utf8@`` 形态（设计内唯一降级类）。
- 错误计数三层一致：``n_errors``(engine) == ``n_errors``(l2) ==
  ``n_bang``(fixloop)，首错文本与出错文件栈同口径。
- judge 面：``warnings_hit`` → ``warn:*`` reasons；``warnings_sys`` 只进
  ``sys_warn:`` notes；nullfont 命中只进 notes 不进 reasons。

历史钉账（均已拆钉——保留作修复史脚注）：

- ``engine._ERR_FILELINE_RE`` 文件名面曾过宽（``^\S+?`` 收无扩展名/带冒号/
  带括号文件名）——已收紧为 ``_ERR_FNAME`` 严侧（``name.ext`` 必带扩展名、
  禁 ``()``/空白/``:``），fixloop logparse 经借用同轨三层合。
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from texlate.compile.engine import CompRes
from texlate.compile.engine import parse_log as eng_parse_log
from texlate.compile.fixloop._yamlish import load_yaml
from texlate.compile.fixloop.engine import RULES_PATH
from texlate.compile.fixloop.logparse import parse_text as fx_parse_text
from texlate.compile.judge import (
    _MISSCHAR_GATE_RX,
    _MISSCHAR_NULLFONT_RX,
    count_missing_chars,
    judge,
)
from texlate.texlog import update_file_stack
from texlate.validate.l2 import _REDLINE_CLASSES, parse_log_text

# ---------------------------------------------------------------- 常量与构造

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "logs"
_BENCH_ROOT = Path(__file__).resolve().parent.parent / "bench"

_WARN_PATTERNS: list[dict] = load_yaml(RULES_PATH)["warnings"]


def _mc(font: str = "cmr10", ch: str = "中", ann: str = "(U+4E2D)") -> str:
    """规范缺字行（字面 + 码位标注 + 字体名）。"""
    return f"Missing character: There is no {ch} {ann} in font {font}!"


def _real_logs() -> list[Path]:
    """fixture 全量 + bench 语料确定性抽样（gitignored 重产物缺席即跳）。"""
    files = sorted(_FIXTURE_DIR.glob("*.log"))
    if _BENCH_ROOT.is_dir():
        pool = sorted(
            p
            for p in _BENCH_ROOT.rglob("*.log")
            if p.stat().st_size < 3_000_000 and "results" not in p.parts  # noqa: PLR2004
        )
        step = max(1, len(pool) // 400)
        files += pool[::step]
    return files


_REAL_LOGS = _real_logs()


def _three(text: str) -> tuple[int, int, int]:
    """(engine n_errors, l2 n_errors, fixloop n_bang)。"""
    return (
        eng_parse_log(text).n_errors,
        parse_log_text(text).n_errors,
        fx_parse_text(text).n_bang,
    )


# ---------------------------------------------------------------- misschar 划分


def test_misschar_gate_nullfont_exact_partition() -> None:
    """gate+nullfont 恰划分所有 ``Missing character`` 字面出现位。"""
    rng = random.Random(20260917)  # noqa: S311 -- 确定性种子复现
    fonts = ["nullfont", "cmr10", "[lmroman12-regular]:mapping=tex-text;"]
    chars = ["中", ";", ")", "(", "", "1"]
    anns = ["(U+4E2D)", '("4E2D)', '("FFFD)', ""]
    for _ in range(3000):
        lines = [
            _mc(rng.choice(fonts), rng.choice(chars), rng.choice(anns))
            if rng.random() < 0.6  # noqa: PLR2004
            else rng.choice(["noise", "(./a.tex", ")", "l.5 \\foo"])
            for _ in range(rng.randint(0, 12))
        ]
        # 随机把一条 misschar 行的 "in font" 之前折行（续行形态）
        if lines and rng.random() < 0.4:  # noqa: PLR2004
            i = rng.randrange(len(lines))
            lines[i] = lines[i].replace(" in font ", "\nin font ", 1)
        text = "\n".join(lines)
        gate = count_missing_chars(text)
        nf = len(_MISSCHAR_NULLFONT_RX.findall(text))
        total = text.count("Missing character:")
        assert gate + nf == total, f"partition broke: {gate}+{nf} != {total}\n{text!r}"
        assert gate == len(_MISSCHAR_GATE_RX.findall(text))


def test_misschar_nullfont_continuation_still_excluded() -> None:
    """``in font nullfont`` 落续行（折行形态）仍豁免——tempered 窗跨 ``\\n``。"""
    cases = [
        _mc("nullfont").replace(" in font ", "\nin font ", 1),
        _mc("nullfont").replace(" in font ", "\n   in font ", 1),
        'Missing character: There is no ; ("3B)\nin font nullfont!',
    ]
    for t in cases:
        assert count_missing_chars(t) == 0, t
        assert len(_MISSCHAR_NULLFONT_RX.findall(t)) == 1


def test_misschar_no_cross_contamination() -> None:
    """真字体行紧邻 nullfont 行不被误豁免——窗不越过下一条 misschar 起点。"""
    cases = [
        # nullfont 先、真字体后
        _mc("nullfont", ";", '("3B)') + "\n" + _mc("cmmi10", "̧", "(U+0327)"),
        # 真字体先、nullfont 后（tempered 界先行拦住对第二条 misschar 的穿透）
        _mc("cmmi10", "̧", "(U+0327)") + "\n" + _mc("nullfont", ";", '("3B)'),
    ]
    for t in cases:
        assert count_missing_chars(t) == 1, t
    # 混合日志: judge 与 l2 同口径
    mixed = _mc("nullfont") + "\n" + _mc("cmmi10", "̧", "(U+0327)")
    bc = parse_log_text(mixed).warnings.by_class
    assert bc.get("missing_glyph_nullfont") == 1
    assert bc.get("missing_glyph") == 1


def test_misschar_window_bound_at_90() -> None:
    """90 字限界是硬边界：中间字符数 ≤90 即豁免、>90 不豁免。"""
    for pad in (88, 89, 90, 91, 120):
        t = "Missing character:" + "x" * pad + "in font nullfont"
        gate = count_missing_chars(t)
        assert gate == (0 if pad <= 90 else 1), (pad, gate)  # noqa: PLR2004


# ---------------------------------------------------------------- l2 census 一致


def _gen_log(rng: random.Random) -> tuple[str, dict[str, int]]:
    """生成 log + 期望统计：errors/misschar 分类全为规范形态。"""
    lines = ["This is XeTeX, Version 3.141592653"]
    exp = {"n_errors": 0, "nf": 0, "real": 0, "fffd": 0, "cjk": 0}
    pieces = [
        "noise text",
        "(./main.tex",
        "(./sub/chap1.tex",
        ")",
        "(./main.tex)",
        "Overfull \\hbox (12.5pt too wide)",
        "LaTeX Warning: Reference `x' undefined on input line 5.",
        "LaTeX Warning: Citation `y' on page 2 undefined.",
    ]
    for _ in range(rng.randint(2, 30)):
        r = rng.random()
        if r < 0.15:  # noqa: PLR2004
            if rng.random() < 0.5:  # noqa: PLR2004
                lines.append("! Undefined control sequence.")
            else:
                lines.append(f"./main.tex:{rng.randint(1, 999)}: LaTeX Error: boom.")
            exp["n_errors"] += 1
        elif r < 0.4:  # noqa: PLR2004
            kind = rng.random()
            if kind < 0.4:  # noqa: PLR2004
                lines.append(_mc("nullfont", rng.choice(";,12="), '("3B)'))
                exp["nf"] += 1
            elif kind < 0.6:  # noqa: PLR2004
                lines.append(_mc("ec-lmr10", "\N{REPLACEMENT CHARACTER}", '("FFFD)'))
                exp["fffd"] += 1
            elif kind < 0.8:  # noqa: PLR2004
                cp = rng.randint(0x4E00, 0x9FFF)
                lines.append(_mc("cmr10", chr(cp), f"(U+{cp:04X})"))
                exp["cjk"] += 1
            else:
                lines.append(_mc("cmr10", "£", '("A3)'))
                exp["real"] += 1
        else:
            lines.append(rng.choice(pieces))
    lines.append("Output written on ./main.pdf (1 page).")
    return "\n".join(lines) + "\n", exp


def test_fuzz_l2_misschar_census_agrees() -> None:
    """l2 by_class 缺字四类 == 逐行 census；judge 门控数 == 非 nullfont 行数。"""
    rng = random.Random(20260918)  # noqa: S311 -- 确定性种子
    for _ in range(2500):
        text, exp = _gen_log(rng)
        v = parse_log_text(text)
        bc = v.warnings.by_class
        assert bc.get("missing_glyph_nullfont", 0) == exp["nf"], text
        assert bc.get("fffd_glyph", 0) == exp["fffd"], text
        assert bc.get("missing_glyph_cjk", 0) == exp["cjk"], text
        assert bc.get("missing_glyph", 0) == exp["real"], text
        # judge 门控 = 全部非 nullfont 缺字行
        assert count_missing_chars(text) == exp["real"] + exp["fffd"] + exp["cjk"]
        # engine 红线同口径
        info = eng_parse_log(text)
        nonnull = exp["real"] + exp["fffd"] + exp["cjk"]
        assert ("missing_chars" in info.warnings_hit) == (nonnull > 0)
        assert ("fffd_glyph" in info.warnings_hit) == (exp["fffd"] > 0)
        # fixloop warnings 面同口径（rules.yaml missing_char 与 gate 同源）
        rep = fx_parse_text(text, _WARN_PATTERNS)
        assert ("missing_char" in rep.warnings) == (nonnull > 0)


def test_fuzz_sys_hits_only_invalid_utf8() -> None:
    """``sys_hits`` 仅 ``invalid_utf8@`` 形态——设计内唯一降级类。"""
    rng = random.Random(20260919)  # noqa: S311 -- 确定性种子
    warn_pool = [
        "Invalid UTF-8 byte C3 in input.",
        "Missing character: There is no 中 (U+4E2D) in font cmr10!",
        "File `fig.png' not found.",
        "Overfull \\hbox (1.0pt too wide)",
    ]
    for _ in range(1500):
        lines = []
        for _ in range(rng.randint(1, 10)):
            r = rng.random()
            if r < 0.3:  # noqa: PLR2004
                lines.append("(/usr/share/texmf-dist/tex/latex/base/x.sty")
            elif r < 0.5:  # noqa: PLR2004
                lines.append(")")
            else:
                lines.append(rng.choice(warn_pool))
        v = parse_log_text("\n".join(lines))
        for hit in v.warnings.sys_hits:
            assert hit.startswith("invalid_utf8@"), hit
        for red in v.warnings.redlines:
            assert red.split(":", 1)[0] in _REDLINE_CLASSES, red


# ---------------------------------------------------------------- 三层错误计数一致


def test_real_logs_three_layer_error_count() -> None:
    """真实 log 三层 n_errors/n_bang 一致 + 首错文本一致。"""
    assert _REAL_LOGS, "no logs found"
    for p in _REAL_LOGS:
        text = p.read_text(errors="replace")
        e = eng_parse_log(text)
        v = parse_log_text(text)
        f = fx_parse_text(text)
        assert e.n_errors == v.n_errors == f.n_bang, (
            f"{p}: eng={e.n_errors} l2={v.n_errors} fx={f.n_bang}"
        )
        heads = {e.first_error, v.first_error.head if v.first_error else None, f.first}
        if e.first_error is not None:
            assert len(heads) == 1, f"{p}: first_error drift {heads}"


def test_fuzz_canonical_log_three_layer_agree() -> None:
    """合成规范 log：计数/首错/首错栈三层一致。"""
    rng = random.Random(20260920)  # noqa: S311 -- 确定性种子
    for _ in range(1500):
        text, exp = _gen_log(rng)
        assert _three(text) == (exp["n_errors"],) * 3, text
        e = eng_parse_log(text)
        v = parse_log_text(text)
        f = fx_parse_text(text)
        if exp["n_errors"]:
            assert e.first_error == v.first_error.head == f.first
            assert e.file_stack == list(v.first_error.file_stack) == f.file_stack


def test_fuzz_mutated_real_log_agreement() -> None:
    """真实 log 注入 `!`/fileline 伪错 → 三层同步 +1；抽掉首行 → engine=None。"""
    rng = random.Random(20260921)  # noqa: S311 -- 确定性种子
    for p in _REAL_LOGS:
        lines = p.read_text(errors="replace").splitlines()
        base = _three("\n".join(lines) + "\n")
        pos = rng.randrange(len(lines) + 1)
        fake = rng.choice(["! Fake injected error.", "./ghost.tex:9: Fake err."])
        mut = [*lines[:pos], fake, *lines[pos:]]
        got = _three("\n".join(mut) + "\n")
        assert got == tuple(b + 1 for b in base), f"{p} @{pos}: {base}->{got}"
        if (
            lines
            and lines[0].startswith("This is ")
            and not lines[1].startswith("This is ")
        ):
            assert parse_log_text("\n".join(lines[1:])).engine is None


# ---------------------------------------------------------------- l2 结构不变量


def test_fuzz_l2_structural_invariants() -> None:
    """``first_error==errors[0]``、errors≤200、ctx≤8、tail=末30、栈全具名。"""
    rng = random.Random(20260922)  # noqa: S311 -- 确定性种子
    for _ in range(1200):
        text, _ = _gen_log(rng)
        v = parse_log_text(text)
        assert v.ok == (v.n_errors == 0)
        assert len(v.errors) == min(v.n_errors, 200)
        if v.errors:
            assert v.first_error is v.errors[0]
            assert [e.line_no for e in v.errors] == sorted(e.line_no for e in v.errors)
            for e in v.errors:
                assert len(e.ctx) <= 8  # noqa: PLR2004 -- _CTX_LINES 契约
                assert all(isinstance(s, str) for s in e.file_stack)
        assert v.tail == tuple(text.splitlines()[-30:])
        assert v.engine == "XeTeX"


def test_l2_error_cap_boundary() -> None:
    """``_MAX_STORED_ERRORS=200``：n_errors 精确计数、存储截断。"""
    text = "".join(f"! err{i}\n" for i in range(250))
    v = parse_log_text(text)
    assert v.n_errors == 250  # noqa: PLR2004 -- 钉存储上限语义
    assert len(v.errors) == 200  # noqa: PLR2004
    assert eng_parse_log(text).n_errors == 250  # noqa: PLR2004


def test_fuzz_update_file_stack_parens() -> None:
    """增量栈与裸括弧记账 oracle 一致；misschar 字形括弧豁免。"""
    rng = random.Random(20260923)  # noqa: S311 -- 确定性种子
    soup = [
        "(",
        ")",
        "(./a.tex",
        "(x.sty",
        "(52.0pt",
        _mc("nullfont", ")", '("0029)'),
        "text ",
        _mc("cmr10", "(", "(U+0028)"),
    ]
    for _ in range(2000):
        lines = [
            "".join(rng.choice(soup) for _ in range(rng.randint(1, 8)))
            for _ in range(rng.randint(1, 6))
        ]
        stack: list[str | None] = []
        popped: list[str | None] = []
        for ln in lines:
            update_file_stack(ln, stack, popped)
            assert all(s is None or isinstance(s, str) for s in stack)
        depth = 0
        for ln in lines:
            skip = (
                {
                    m.start(1)
                    for m in re.finditer(
                        r"Missing character: There is no ([()])(?=[ (]|$)", ln
                    )
                }
                if "Missing character" in ln
                else set()
            )
            for j, c in enumerate(ln):
                if j in skip:
                    continue
                depth += c == "("
                depth -= c == ")" and depth > 0
        assert len(stack) == depth, lines


# ---------------------------------------------------------------- judge 面


def _res(text: str) -> CompRes:
    """有 pdf 的 CompRes——log 由 engine 真管线解析。"""
    return CompRes(
        engine="xelatex",
        ok=True,
        pdf=Path("/nonexistent.pdf"),
        pdf_bytes=1024,
        log=eng_parse_log(text),
    )


def test_judge_nullfont_only_is_clean() -> None:
    """纯 nullfont 缺字 → clean：门控零计数 + nullfont 进 notes 观察项。"""
    text = _mc("nullfont", ";", '("3B)') + "\n" + _mc("nullfont", "1", '("31)') + "\n"
    v = judge(_res(text), expect_cjk=True, log_text=text)
    assert v.missing_chars == 0
    assert "missing_character_nullfont×2" in v.notes
    assert not any(r.startswith("missing_character") for r in v.reasons)
    assert not any(r.startswith("warn:missing") for r in v.reasons)
    # pdftotext 对不存在 pdf 返回 -1 → cjk_unverified 仅 notes
    assert v.status == "clean"


def test_judge_warn_hit_propagation() -> None:
    """warnings_hit→``warn:*`` reasons；warnings_sys→``sys_warn:*`` notes 只读。"""
    res = _res("noise\n")
    res.log.warnings_hit = ["missing_chars", "fffd_glyph"]
    res.log.warnings_sys = ["invalid_utf8@old.sty"]
    v = judge(res, log_text="noise\n")
    assert "warn:missing_chars" in v.reasons
    assert "warn:fffd_glyph" in v.reasons
    assert "sys_warn:invalid_utf8@old.sty" in v.notes
    assert not any("old.sty" in r for r in v.reasons)


# ================================================================ 钉账区
# 本节含已核销回归钉（docstring 留「原 strict-xfail」注脚）与当前唯一活钉
# test_xfail_error_line_filename_width——拆一枚清一枚。


def test_fffd_nullfont_benign() -> None:
    """repro: ``Missing character: There is no ("FFFD) in font nullfont!``。
    原 strict-xfail（fffd_glyph 缺 nullfont 豁免）——engine.py 豁免已落。"""

    text = 'Missing character: There is no ("FFFD) in font nullfont!\n'
    info = eng_parse_log(text)
    assert "fffd_glyph" not in info.warnings_hit  # 现状: 命中 → warn:fffd_glyph
    v = judge(_res(text), log_text=text)
    assert "warn:fffd_glyph" not in v.reasons
    assert v.status == "clean"


def test_misschar_window_no_swallow_real() -> None:
    """真 misschar + 后行 'in font nullfont' 字样 → 窗被本消息 in font 终止符
    截断，不误豁免（原 strict-xfail——redlines 窗口已收进消息体域）。"""
    text = _mc("cmr10") + "\nsome trailing text in font nullfont"
    assert count_missing_chars(text) == 1
    assert "missing_chars" in eng_parse_log(text).warnings_hit


#: 三层错误行口径一致集——l2._FILE_LINE_RX 消息面与 Warning 排除锚定已
#: 对齐 texlog._ERR_FILELINE_RE/_NONERR_FILELINE_RE（严侧）；
#: 真实语料 1504 log 零分歧——分叉全是畸形形。
_ERRLINES_AGREED = [
    "./main.tex:5:",  # 空消息——三层均不收
    "./main.tex:5:!boom",  # 冒号后无空格
    "./main.tex:5:\tboom",  # tab 分隔
    "./f.tex:5: See LaTeX Warning: x",  # Warning 字样在 msg 中段→真错
    "./f.tex:5: ! LaTeX Warning: x",  # msg 带 ! 前缀→Warning 排除不命中
    "./f.tex:5: ! ==> Fatal error occurred",  # ==> 不在 msg 起点→真错
]


@pytest.mark.parametrize("line", _ERRLINES_AGREED)
def test_error_line_three_layer_agree(line: str) -> None:
    text = line + "\nrest\n"
    e, lv, f = _three(text)
    assert e == lv == f, f"{line!r}: eng={e} l2={lv} fx={f}"


#: 文件名面三层已对齐严侧（原 strict-xfail——engine `_ERR_FNAME` 单源化后
#: 无扩展名/含冒号/含开括弧名齐拒，fixloop 经借用同轨）。
_ERRLINES_BAD_FNAME = [
    "Makefile:5: boom",  # 无扩展名
    "C:\\foo.tex:5: boom",  # 文件名含冒号
    "(x.tex:5: boom",  # 文件名带开括弧
]


@pytest.mark.parametrize("line", _ERRLINES_BAD_FNAME)
def test_error_line_filename_width(line: str) -> None:
    text = line + "\nrest\n"
    e, lv, f = _three(text)
    assert e == lv == f, f"{line!r}: eng={e} l2={lv} fx={f}"


def test_misschar_requires_colon() -> None:
    """裸 ``Missing character`` 无冒号前缀非消息形态——三闸均不计（原
    strict-xfail——redlines gate/probe 已加冒号）。"""
    text = "Missing characters will be silently dropped by this package.\n"
    assert count_missing_chars(text) == 0
    assert "missing_chars" not in eng_parse_log(text).warnings_hit


@pytest.mark.parametrize(
    "line",
    [
        "invalid utf-8 byte C3 in input.",
        "LaTeX Warning: Char replaced by U+FFFD on input line 5.",
    ],
)
def test_utf8_variant_cross_layer(line: str) -> None:
    """invalid_utf8 变体跨层同命中——loginfo._UTF8_WARN_RE 已对齐 l2
    （IGNORECASE + ``replaced by U+FFFD``，原 strict-xfail）。"""
    text = "(./main.tex\n" + line + "\n)\n"
    v = parse_log_text(text)
    assert v.warnings.by_class.get("invalid_utf8") == 1  # l2 已认
    assert "invalid_utf8" in eng_parse_log(text).warnings_hit  # engine 漏


def test_graphic_frame_parity() -> None:
    text = "(./main.tex\n(fig,1.eps\n! Undefined control sequence.\nl.5 \\foo\n"
    e = eng_parse_log(text)
    v = parse_log_text(text)
    f = fx_parse_text(text)
    assert e.file_stack == list(v.first_error.file_stack) == f.file_stack
