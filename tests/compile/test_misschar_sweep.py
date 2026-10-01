r"""``missing_char`` C0 测量扫掠豁免（picinpar ``\computeilg`` 类）。

签名面：同一字体名下 ≥25 条严格升序 C0+DEL（U+0000–001F、U+007F）
``Missing character`` 消息 = 测量盒逐码位试排丢盒噪音（``\loop
\setbox\wbox=\hbox{\char\tcl}``，``\tcl`` 0→127）——非正文丢字，门控
豁免。散 C0/单码位重复/非 C0 升序/碎片升序（<25）均照常计入。

实证锚点：1003.0694（lmroman10-regular/italic 双字体各 33 成员升序链，
gate 132 → 0）；corpus loop3 全量 splice log 零误伤。
"""

from __future__ import annotations

from conftest import make_comp_res

from texlate.compile.judge import count_missing_chars, judge
from texlate.compile.loginfo import parse_log as eng_parse_log
from texlate.redlines import REDLINES_BY_ID
from texlate.texlog import misschar_sweep_hits

_FONT = "[lmroman10-regular]:mapping=tex-text;"
_C0_END = 0x20  # C0 上界——签名域 U+0000–001F + U+007F
_DEL = 0x7F
_LF = 0x0A  # 缺字本体是换行符 → 消息自身折行
_SWEEP_N = 33  # 单字体全扫掠成员数 = 32 C0 + DEL


def _mc(font: str = _FONT, ch: str = "中", ann: str = "(U+4E2D)") -> str:
    """规范缺字行（字面 + 码位标注 + 字体名）。"""
    return f"Missing character: There is no {ch} {ann} in font {font}!"


def _c0_name(cp: int) -> str:
    """C0 码位的 ``^^X`` 名记法字面（log 实测形态）。"""
    return f"^^{chr(cp + 64) if cp < _C0_END else '?'}"


def _sweep(font: str = _FONT, *, wrapped: bool = False) -> str:
    """picinpar 形全扫掠：U+0000–001F + U+007F 升序 33 条。

    ``wrapped`` 时 U+000A 条用实测自身折行形（缺字本体是换行符：
    ``There is no <\\n> (U+000A) in font`` 跨两行）。
    """
    lines = []
    for cp in (*range(_C0_END), _DEL):
        if wrapped and cp == _LF:
            lines.append(
                f"Missing character: There is no \n (U+{cp:04X}) in font {font}!"
            )
        else:
            lines.append(_mc(font, _c0_name(cp), f"(U+{cp:04X})"))
    return "\n".join(lines)


# ---------------------------------------------------------------- 扫掠豁免


def test_sweep_fully_excluded_gate_and_engine() -> None:
    """33 成员升序 C0+DEL 扫掠 → 门控零计数、engine 不发射 missing_chars。"""
    text = _sweep() + "\n"
    assert misschar_sweep_hits(text) == _SWEEP_N
    assert count_missing_chars(text) == 0
    assert "missing_chars" not in eng_parse_log(text).warnings_hit


def test_sweep_two_fonts_each_excluded() -> None:
    """双字体各自成链（1003.0694 形态）→ 两链全员豁免。"""
    text = _sweep("[lmroman10-regular]:mapping=tex-text;") + "\n"
    text += _sweep("[lmroman10-italic]:mapping=tex-text;") + "\n"
    assert misschar_sweep_hits(text) == 2 * _SWEEP_N
    assert count_missing_chars(text) == 0


def test_sweep_u000a_wrapped_member() -> None:
    """U+000A 消息自身折行（``no <\\n> (U+000A)``）仍归入扫掠——拼接后成链。"""
    text = _sweep(wrapped=True) + "\n"
    # 折行成员照常是 gate 命中（`Missing character:` 前缀在），扫掠须全覆盖。
    assert text.count("Missing character:") == _SWEEP_N
    assert misschar_sweep_hits(text) == _SWEEP_N
    assert count_missing_chars(text) == 0


def test_sweep_boundary_run_min() -> None:
    """升序链长 25 豁免、24 不豁免——阈值硬边界。"""
    font = _FONT
    for n, exp in ((25, 0), (24, 24)):
        lines = [_mc(font, _c0_name(cp), f"(U+{cp:04X})") for cp in range(n)]
        text = "\n".join(lines) + "\n"
        assert count_missing_chars(text) == exp, (n, text)


def test_judge_sweep_only_is_clean() -> None:
    """纯扫掠 log → judge clean + ``missing_character_sweep×N`` notes 观察项。"""
    text = _sweep() + "\n"
    v = judge(make_comp_res(log_text=text), expect_cjk=True, log_text=text)
    assert v.missing_chars == 0
    assert f"missing_character_sweep×{_SWEEP_N}" in v.notes
    assert not any(r.startswith("missing_character×") for r in v.reasons)
    assert not any(r.startswith("warn:missing") for r in v.reasons)
    assert v.status == "clean"


# ---------------------------------------------------------------- 不误豁免


def test_scattered_c0_still_counted() -> None:
    """散 C0（非升序/重复码位）照常计入——cond-mat/9910148 ^^B×8 形态。"""
    lines = [f"noise {i}\n" + _mc(_FONT, "^^B", "(U+0002)") for i in range(8)]
    text = "\n".join(lines) + "\n"
    assert misschar_sweep_hits(text) == 0
    assert count_missing_chars(text) == len(lines)
    assert "missing_chars" in eng_parse_log(text).warnings_hit


def test_repeated_single_cp_still_counted() -> None:
    """单码位重复 U+0000×30（1706.07495 错误恢复副产形态）非扫掠。"""
    lines = [_mc(_FONT, "^^@", "(U+0000)") for _ in range(30)]
    text = "\n".join(lines) + "\n"
    assert misschar_sweep_hits(text) == 0
    assert count_missing_chars(text) == len(lines)


def test_ascending_non_c0_still_counted() -> None:
    """非 C0 升序链（U+0041..U+0059 可印字符）不属豁免域——测量盒签名限 C0+DEL。"""
    lines = [_mc(_FONT, chr(cp), f"(U+{cp:04X})") for cp in range(0x41, 0x5A)]
    text = "\n".join(lines) + "\n"
    assert misschar_sweep_hits(text) == 0
    assert count_missing_chars(text) == len(lines)


def test_interleaved_two_fonts_below_min() -> None:
    """两字体各 16 成员交错——单链 <25 不豁免（字体名归序不拼跨字体链）。"""
    fa, fb = (
        "[lmroman10-regular]:mapping=tex-text;",
        "[lmroman12-regular]:mapping=tex-text;",
    )
    lines = []
    for cp in range(16):
        lines.append(_mc(fa, _c0_name(cp), f"(U+{cp:04X})"))
        lines.append(_mc(fb, _c0_name(cp), f"(U+{cp:04X})"))
    text = "\n".join(lines) + "\n"
    assert misschar_sweep_hits(text) == 0
    assert count_missing_chars(text) == len(lines)


def test_run_break_on_descent() -> None:
    """码位回降截断升序链——两段独立评估，碎片 <25 留计。"""
    cps = [*range(0x18), 0x05, *range(0x19, _C0_END), _DEL]
    lines = [_mc(_FONT, _c0_name(cp), f"(U+{cp:04X})") for cp in cps]
    text = "\n".join(lines) + "\n"
    assert misschar_sweep_hits(text) == 0
    assert count_missing_chars(text) == len(cps)


# ---------------------------------------------------------------- 混合保留


def test_mixed_sweep_plus_real_miss() -> None:
    """扫掠 + 真缺字并存：真缺字留计、扫掠豁免——reasons 只钉真部分。"""
    reals = [_mc(_FONT, "中", "(U+4E2D)"), _mc(_FONT, "£", '("A3)')]
    text = _sweep() + "\n" + "\n".join(reals) + "\n"
    assert misschar_sweep_hits(text) == _SWEEP_N
    assert count_missing_chars(text) == len(reals)
    info = eng_parse_log(text)
    assert "missing_chars" in info.warnings_hit
    v = judge(make_comp_res(log_text=text), expect_cjk=True, log_text=text)
    assert v.missing_chars == len(reals)
    assert f"missing_character×{len(reals)}" in v.reasons
    assert f"missing_character_sweep×{_SWEEP_N}" in v.notes


def test_sweep_after_nullfont_not_mixed() -> None:
    """nullfont 命中与扫掠并存：两豁免独立成立、各自进 notes。"""
    text = _mc("nullfont", ";", '("3B)') + "\n" + _sweep() + "\n"
    v = judge(make_comp_res(log_text=text), expect_cjk=True, log_text=text)
    assert v.missing_chars == 0
    assert "missing_character_nullfont×1" in v.notes
    assert f"missing_character_sweep×{_SWEEP_N}" in v.notes
    assert v.status == "clean"


def test_registry_row_shape() -> None:
    """``missing_char_sweep`` 注册行形冻结：judge 独生、pattern=None（算法判定）。

    行无检索切片——豁免在两路消费点内联调用 ``misschar_sweep_hits``；
    钉死 judge 词干名与 ``engine``/``rules``/``logattr`` 零泄漏（warn:* 镜像
    若泄漏会把扫掠噪音经 rules 派发白烧轮次）。
    """
    r = REDLINES_BY_ID["missing_char_sweep"]
    assert r.engine is None
    assert r.rules is None
    assert r.logattr is None
    assert r.logattr_redline is False
    assert r.judge is not None
    assert r.judge.name == "missing_character_sweep"
    assert r.judge.pattern is None
