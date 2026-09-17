r"""未知 cs 探针臂散文参挖掘钉版 —— ``_handle_unknown_cs`` 逐参散文门控。

背景：宏表/argspec 表双未中的未知命令走投机探针（``[o]{m}``×6、禁单
token 参），任一参消费即整调用折进单个 ``[[CMD_n]]``——花括号参里的
散文整块蒸发不进 chunk（1803.00127 ``\@maketitle{\begin{figure}…
\caption{…}`` 标题块 555B 全灭；corpus_v3 扫描另见 ``\acks``/
``\titlerunning``/``\texorpdfstring``/``\shortstack`` 同型）。

修法（本文件钉住的语义，与 ``_handle_opaque_macro`` 散文挖掘同形）：

- 探针消费参逐参过 scout 散文判据（剔注释+cs 后 ≥4 连词、非全大写）——
  命中即抠出 ``[[CMD]]`` 覆盖、内容子扫渲进 run surface；命令名段与
  非散文参、散文参两侧花括号所在结构段仍 opaque 原文。
- 非 ``{``-open 参（``[o]``/单 token——探针本不收后者）、跨 fid 组、
  未消费占位不挖；``gen >= MAX_GEN`` 回压维持整调用 opaque +
  ``gen_overflow`` 告警。
- 零消费照旧回吐逐字（``\foo x`` 的 ``x`` 是正文不是参——泄漏机制 A）。

每条用例过公共不变式：``reconstruct(res) == tex`` + ``validate_result``
零告警 + pieces 无缝平铺。
"""

import re

import pytest
from conftest import ART, blob, check_invariants

from texlate.latex import parse_tex
from texlate.latex.model import ScanResult

PROSE = "We consider a two form antisymmetric tensor field theory in detail"
KEY = "dalianis2020"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def scan(body: str, defs: str = "") -> ScanResult:
    tex = ART % (defs, body)
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


def cmd_bodies(res: ScanResult) -> list[str]:
    """全部 ``[[CMD_n]]`` ph 体（覆盖区间原文）。"""
    return [
        body for ph, body in res.ph_map.items() if re.fullmatch(r"\[\[CMD_\d+\]\]", ph)
    ]


def test_probe_prose_arg_surfaces() -> None:
    r"""``\unknowncmd{prose}``：散文参进 chunk surface，``\unknowncmd{``/``}`` 留 CMD ph。"""
    res = scan(f"\\unknowncmd{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\unknowncmd{" in bodies
    assert "}" in bodies
    assert all(PROSE not in b for b in bodies)


def test_probe_key_arg_stays_opaque() -> None:
    r"""``\unknowncmd{cite-key}`` 非散文参：整调用单 CMD ph，参不外流。"""
    res = scan(f"\\unknowncmd{{{KEY}}} Tail prose words keep flowing here.")
    bodies = cmd_bodies(res)
    assert f"\\unknowncmd{{{KEY}}}" in bodies
    assert KEY not in blob(res)


def test_probe_opt_arg_not_lifted() -> None:
    r"""``[o]`` 参即使形似散文也不挖（``[``-open 非散文槽位）——整调用 opaque。"""
    res = scan(
        "\\unknowncmd[optional words with several terms here]"
        f"{{{KEY}}} Tail prose keeps flowing."
    )
    bodies = cmd_bodies(res)
    whole = f"\\unknowncmd[optional words with several terms here]{{{KEY}}}"
    assert whole in bodies
    assert "optional" not in blob(res)


def test_probe_second_arg_prose_first_key() -> None:
    r"""``\unknowncmd{key}{prose}`` 逐参判定：key 参留 CMD，散文参出 surface。"""
    res = scan(f"\\unknowncmd{{{KEY}}}{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert any(f"\\unknowncmd{{{KEY}}}" in b and PROSE not in b for b in bodies)
    assert KEY not in blob(res)


def test_probe_nested_cs_in_prose_arg() -> None:
    r"""散文参内嵌未知调用：子扫探针臂照常把 ``\\inner{key}`` 折成 CMD，散文出 surface。"""
    res = scan(f"\\unknowncmd{{{PROSE} \\innercs{{{KEY}}} inside.}}")
    text = blob(res)
    assert PROSE in text
    assert "inside" in text
    assert KEY not in text
    assert f"\\innercs{{{KEY}}}" in cmd_bodies(res)


def test_probe_at_cs_after_makeatletter() -> None:
    r"""``\\makeatletter`` 区段内 ``\\@maketitle{prose}``——1803.00127 同型现场。"""
    defs = ""
    body = f"\\makeatletter\n\\@maketitle{{{PROSE}.}}\n\\makeatother\n"
    res = scan(body, defs)
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\@maketitle{" in bodies
    assert all(PROSE not in b for b in bodies)


def test_probe_unclosed_arg_bails() -> None:
    r"""未配对 ``{`` 参：``_collect_group`` EOF 回吐——探针零消费，
    组回主流重扫散文照常进 surface。"""
    res = scan("\\unknowncmd{unclosed prose group words here\n")
    assert "unclosed prose group words" in blob(res)


def test_probe_no_args_literal() -> None:
    r"""零消费照旧逐字：``\\foo`` 后无组参 → 名进 run，不收尾参。"""
    res = scan("\\unknowncmd rest of the paragraph text flows on here.")
    assert "rest of the paragraph text" in blob(res)


def test_probe_all_caps_rejected() -> None:
    r"""全大写缩写列（``NASA ESA SOHO MISSION LIST``）不算散文——维持 opaque。"""
    res = scan("\\unknowncmd{NASA ESA SOHO MISSION LIST}")
    assert any("NASA" in b for b in cmd_bodies(res))
    assert "NASA" not in blob(res)


def test_probe_commented_prose_not_lifted() -> None:
    r"""参内散文全在注释里 → 判据剔注释后无 ≥4 连词 → 维持 opaque。"""
    res = scan(
        "\\unknowncmd{%``A commented out paper title goes here''\n"
        "S.~Passaglia and M.~Sasaki}"
    )
    assert any("Passaglia" in b for b in cmd_bodies(res))
    assert "Passaglia" not in blob(res)


def test_probe_swallow_name_stays_opaque() -> None:
    r"""未定义 ``\comment{prose}``：吞块名闸命中——散文参不挖，整调用 CMD（W50 面）。"""
    res = scan(f"\\comment{{{PROSE}.}} Tail prose keeps flowing here.")
    bodies = cmd_bodies(res)
    assert f"\\comment{{{PROSE}.}}" in bodies
    assert PROSE not in blob(res)


def test_opaque_swallow_name_stays_opaque() -> None:
    r"""已定义 ``\def\comment#1{}`` + ``\comment{prose}``：opaque 臂同款闸——
    散文参不挖，整调用 MACRO（双臂一致）。"""
    res = scan(
        f"\\comment{{{PROSE}.}} Tail prose keeps flowing here.",
        "\\def\\comment#1{}\n",
    )
    assert PROSE not in blob(res)
    macro_bodies = [
        body
        for ph, body in res.ph_map.items()
        if re.fullmatch(r"\[\[MACRO_\d+\]\]", ph)
    ]
    assert f"\\comment{{{PROSE}.}}" in macro_bodies


def test_probe_gen_backpressure() -> None:
    r"""嵌套散文参递归子扫到 ``MAX_GEN``：内层 ``\\f{prose}`` 不挖，
    整调用 opaque + ``gen_overflow`` 告警；外层散文照常出 surface。"""
    depth = 40
    inner = f"{PROSE} deep."
    body = f"\\f{{{inner}}}"
    for _ in range(depth):
        body = f"\\f{{Outer prose words wrap around {body} tail.}}"
    res = scan(body)
    kinds = [w.kind for w in res.warnings]
    assert "gen_overflow" in kinds
    text = blob(res)
    assert "Outer prose words" in text  # 外层（gen<MAX_GEN）照常挖掘
    assert f"{PROSE} deep." not in text  # 最内层（gen 触底）维持 opaque
