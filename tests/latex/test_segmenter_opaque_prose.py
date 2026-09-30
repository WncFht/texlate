r"""Opaque 宏散文参挖掘钉版 —— ``_handle_opaque_macro`` 逐参散文门控。

背景：opaque 宏（gullet 判体无文本不展开——``\def`` 体含 ``@``-cs 或
无文本槽位的调用点保护档）历史上把整调用+参折进单个 ``[[MACRO_n]]``，
花括号参里的散文（abstract/caption/bibitem 条目/``\sortbibitem`` 第二参）
整块蒸发不进 chunk。cat9 @-cs 面实测 11/5135 doc 全量摘要/题注/书目消失。

修法（本文件钉住的语义）：

- ``{..}`` 组参逐参过 scout 散文判据（剔注释+cs 后 ≥4 连词、非全大写）——
  命中即抠出 ``[[MACRO]]`` 覆盖、内容子扫渲进 run surface（``_subscan_render``，
  嵌套 cs/注释照常保护成 ph）；宏名段与非散文参、散文参两侧花括号所在结构段
  仍 opaque 原文（``[[MACRO]]`` 体含 ``{``/``}``）。
- 非 ``{``-open 参（``[``/``e``/定界/单 token）、跨 fid 组、未消费占位不挖；
  ``gen >= MAX_GEN`` 回压维持整调用 opaque + ``gen_overflow`` 告警。
- ``\sortbibitem{KEY}{prose}`` 双参独立判定：key 参（非散文）留 ``[[MACRO]]``
  内——引文链不被译断。

每条用例过公共不变式：``reconstruct(res) == tex`` + ``validate_result`` 零告警
+ pieces 无缝平铺。
"""

from conftest import KEY, PROSE, blob, ph_bodies, scan_art

from texlate.latex.model import ScanResult

#: 体含 ``@``-cs → opaque 档（``_classify`` 的 ``_has_at_cs`` 早退）。
#: ``\makeatletter`` 区段内 ``\def`` 让 ``\@x`` 成单枚 cs token。
DEFS = (
    "\\makeatletter\n"
    "\\def\\myabs#1{\\@internal{#1}}\n"
    "\\def\\pair#1#2{\\@join{#1}{#2}}\n"
    "\\def\\keyonly#1{\\@store{#1}}\n"
    "\\makeatother\n"
)


def scan(body: str, defs: str = DEFS) -> ScanResult:
    """ART 模板 + DEFS 导言位的 ``scan_art`` 外包——缺省导言是本文件的 opaque 档。"""
    return scan_art(body, defs)


def macro_bodies(res: ScanResult) -> list[str]:
    """全部 ``[[MACRO_n]]`` ph 体（覆盖区间原文）。"""
    return ph_bodies(res, "MACRO")


def test_prose_arg_surfaces() -> None:
    r"""``\myabs{prose}``：散文参进 chunk surface，``\myabs{``/``}`` 留 MACRO ph。"""
    res = scan(f"\\myabs{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = macro_bodies(res)
    assert "\\myabs{" in bodies
    assert "}" in bodies
    # 散文本体不在任何 MACRO ph 体里
    assert all(PROSE not in b for b in bodies)


def test_key_arg_stays_opaque() -> None:
    r"""``\keyonly{cite-key}`` 非散文参：整调用单 MACRO ph，参不外流。"""
    res = scan(f"\\keyonly{{{KEY}}} Tail prose words keep flowing here.")
    bodies = macro_bodies(res)
    assert f"\\keyonly{{{KEY}}}" in bodies
    assert KEY not in blob(res)


def test_second_arg_prose_key_kept() -> None:
    r"""``\pair{KEY}{prose}``：key 参留 MACRO ph 内，散文参出 surface。"""
    res = scan(f"\\pair{{{KEY}}}{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = macro_bodies(res)
    assert any(f"\\pair{{{KEY}}}" in b and PROSE not in b for b in bodies)
    assert KEY not in blob(res)


def test_first_arg_prose_second_key() -> None:
    r"""``\pair{prose}{KEY}``：反向交错同样逐参判定。"""
    res = scan(f"\\pair{{{PROSE}.}}{{{KEY}}}")
    assert PROSE in blob(res)
    bodies = macro_bodies(res)
    assert any(b.endswith("}") and KEY in b and PROSE not in b for b in bodies)
    assert KEY not in blob(res)


def test_both_args_prose() -> None:
    r"""双散文参：两段散文都进 surface，宏名+双花括号段拆成 MACRO ph。"""
    p2 = "Another independent paragraph of prose follows here"
    res = scan(f"\\pair{{{PROSE}.}}{{{p2}.}}")
    text = blob(res)
    assert PROSE in text
    assert p2 in text
    # 宏名 cs 不裸落 surface——只能裹在 [[MACRO_n]] ph 体里
    assert "\\pair" not in text
    assert any("\\pair{" in b for b in macro_bodies(res))


def test_nested_cs_in_prose_arg() -> None:
    r"""散文参内嵌 opaque 调用：子扫照常保护成 ``[[MACRO]]``，散文出 surface。"""
    res = scan(f"\\myabs{{{PROSE} \\keyonly{{{KEY}}} inside.}}")
    text = blob(res)
    assert PROSE in text
    assert "inside" in text
    assert KEY not in text
    assert f"\\keyonly{{{KEY}}}" in macro_bodies(res)


def test_commented_title_not_lifted() -> None:
    r"""参内散文全在注释里 → 判据剔注释后无 ≥4 连词 → 维持 opaque（2403.15126 实态）。"""
    res = scan(
        "\\keyonly{%``A commented out paper title goes here''\n"
        "S.~Passaglia and M.~Sasaki}"
    )
    assert any("Passaglia" in b for b in macro_bodies(res))  # 参整体留 MACRO ph
    assert "Passaglia" not in blob(res)


def test_short_arg_not_prose() -> None:
    r"""<4 连词短参（``{Phys. Rev. D}`` 类刊名）不挖——opaque 保持。"""
    res = scan("\\keyonly{Phys. Rev. D} Tail prose words keep flowing here.")
    assert any("\\keyonly{Phys. Rev. D}" in b for b in macro_bodies(res))
    assert "Rev" not in blob(res)


def test_unclosed_arg_bails() -> None:
    r"""未配对 ``{`` 参：``_collect_group`` EOF 回吐——主流重扫，不挖不炸。"""
    res = scan("\\myabs{dalianis2020}{unclosed prose group words here\n")
    assert isinstance(res, ScanResult)


def test_prose_arg_all_caps_rejected() -> None:
    r"""全大写缩写列（``NASA ESA SOHO MISSION LIST``）不算散文——维持 opaque。"""
    res = scan("\\keyonly{NASA ESA SOHO MISSION LIST}")
    assert any("NASA" in b for b in macro_bodies(res))
    assert "NASA" not in blob(res)


# --------------------------------------------------------- 定界参消费（u/g）


def test_delim_cs_arg_consumed() -> None:
    r"""``\def\formula#1\stop{..}`` 调 ``\formula x^2 \stop``：``u`` 定界参
    滑窗命中 ``\stop``——delim 消费、整调用进 ``[[MACRO]]``，``x^2 \stop``
    不裸落 chunk（delim-param-args 修复前的泄漏形）。"""
    res = scan(
        "Before \\formula x^2+y^2 \\stop after words here.",
        "\\def\\formula#1\\stop{$#1$}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\formula x^2+y^2 \\stop"
    assert "x^2" not in blob(res)
    assert "\\stop" not in blob(res)


def test_delim_comma_args_all_consumed() -> None:
    r"""``\def\bbra#1,#2,#3{..}`` + ``\bbra a,b,c``（corpus 实形）：
    三枚逗号界定界参逐参消费，整调用 ``[[MACRO]]``。"""
    res = scan(
        "Before \\bbra a,b,c after words here.",
        "\\def\\bbra#1,#2,#3{\\left(#1,#2,#3\\right)}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\bbra a,b,c"
    assert "a,b,c" not in blob(res)


def test_delim_paren_and_cs_seq() -> None:
    r"""``\def\fl#1(#2)#3\\{..}``（0707.2151 ``\FetchLabel@`` 同形）：
    括号界 + cs 界混合序列逐参消费。"""
    res = scan(
        "Before \\fl foo(bar)baz\\\\ after words here.",
        "\\def\\fl#1(#2)#3\\\\{}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\fl foo(bar)baz\\\\"
    assert "baz" not in blob(res)


def test_delim_empty_arg_adjacent() -> None:
    r"""delim 紧邻（``\formula\stop`` 空参）：delim 序列立即命中——
    inner 空、内容位零宽，调用照常整收。"""
    res = scan(
        "Before \\formula\\stop after words here.",
        "\\def\\formula#1\\stop{$#1$}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\formula\\stop"


def test_delim_missing_delim_abandons() -> None:
    r"""delim 缺席（``\formula x^2`` 无 ``\stop``）→ 放弃：``\formula``
    单独 ``[[MACRO]]``，已拉 token 全量回放——余文主流重扫描不被吞。"""
    res = scan(
        "Before \\formula x^2+y^2 after words keep flowing.",
        "\\def\\formula#1\\stop{$#1$}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\formula"
    assert "x^2+y^2 after words" in blob(res)


def test_delim_eol_par_boundary_abandons() -> None:
    r"""delim 不跨 ``\n\n`` 段界：``\stop`` 在段界后出现 → runaway 放弃
    （``_find_math_close_tok``/``d/r`` closer-miss 同款防护），参数文回流。"""
    res = scan(
        "Before \\formula x^2+y^2\n\nafter \\stop words keep flowing here.",
        "\\def\\formula#1\\stop{$#1$}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\formula"
    assert "x^2+y^2" in res.protected_tex  # 已拉 token 回放主流——不吞文
    assert "\\stop" in blob(res)  # 放弃后 \stop 按未知 cs 主流处理


def test_delim_brace_group_shields_inner_delim() -> None:
    r"""``\formula {x \stop y} more \stop``：``{`` 起平衡组整收——组内
    ``\stop`` 不当 delim（gullet ``_read_delimited`` 同款屏蔽），外位
    ``\stop`` 才终结参数。"""
    res = scan(
        "Before \\formula {x \\stop y} more \\stop after words here.",
        "\\def\\formula#1\\stop{$#1$}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\formula {x \\stop y} more \\stop"


def test_until_group_arg_lbrace_pushed_back() -> None:
    r"""``\def\g#1#{..}``（``until_group``→``g``）：``#1`` 读到 ``{`` 止——
    ``{`` 回吐不消费、不计入 inner，尾随 ``{def}`` 组留主流照常进 chunk。"""
    res = scan(
        "Before \\g abc{def group words inside} after words here.",
        "\\def\\g#1#{\\textbf{#1}}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\g abc"
    assert "def group words inside" in blob(res)


def test_until_group_empty_arg_immediate_lbrace() -> None:
    r"""``\g{def}``：``{`` 立即回吐——``#1`` 空参，``{def}`` 组整体留主流。"""
    res = scan(
        "Before \\g{def group words inside} after words here.",
        "\\def\\g#1#{\\textbf{#1}}\n",
    )
    assert res.ph_map["[[MACRO_1]]"] == "\\g"
    assert "def group words inside" in blob(res)
