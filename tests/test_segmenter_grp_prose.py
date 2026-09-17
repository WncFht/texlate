r"""组内探针臂散文参挖掘钉版 —— ``_group_surface`` probe 行逐参散文门控。

背景：宏展开组内（gen>0 同 origin token 列）未知 cs 走 ``_grp_probe_end``
（``[o]``? + ``{m}``×6），命中即整调用折进单个 ``[[CMD_n]]``——与主流
``_handle_unknown_cs`` 修复前同型的散文蒸发（第三现场；前两现场 =
opaque 宏臂 4bca3a1 + 主流探针臂 22df2e5）。

修法（本文件钉住的语义，与 ``_handle_unknown_cs`` 挖掘臂同形）：

- 探针消费形内逐 ``{..}`` 组过 scout 散文判据的 token 级对价
  （``_grp_arg_prose``：cs token 剔为空白后 ≥4 连词、非全大写）——命中
  组内容经 ``_grp_scan`` 递归子扫渲进 run surface，嵌套 cs 照常分派保护；
  宏名/非散文参/散文参两侧花括号所在结构段仍 ``[[CMD]]`` 原文。
- ``[o]`` 组非散文槽位不挖；``_SWALLOW_ARG_NAMES`` 名闸同口径（W50）；
  子扫代数 ``depth >= MAX_GEN`` 回压：参维持 opaque + ``gen_overflow``；
  子扫整组 bail（参内保护族 env 无配对 ``\end``）→ 该参不挖。

每条用例过公共不变式：``reconstruct(res) == tex`` + ``validate_result``
零告警 + pieces 无缝平铺。
"""

import re

import pytest
from conftest import ART, blob, check_invariants

from texlate.latex import parse_tex
from texlate.latex.model import ScanResult

PROSE = "We consider a two form antisymmetric tensor field theory in detail"
PROSE2 = "Another independent sentence of English prose sits right here"
KEY = "dalianis2020"
#: 组 surface 须过 CHUNK_MIN 才成 chunk——统一垫词，别让样本落 literal 路
PAD = "pad words here to push the surface past the minimum chunk limit"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def scan_grp(call: str, defs: str = "") -> ScanResult:
    r"""``\\def\\w{<call> PAD}`` + ``\\w``——call 落展开组 token 列过组内分派。"""
    tex = ART % (f"{defs}\\def\\w{{{call} {PAD}}}\n", "\\w")
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


def cmd_bodies(res: ScanResult) -> list[str]:
    """全部 ``[[CMD_n]]`` ph 体（组内为 token 级重建文本）。"""
    return [
        body for ph, body in res.ph_map.items() if re.fullmatch(r"\[\[CMD_\d+\]\]", ph)
    ]


def test_grp_probe_prose_arg_surfaces() -> None:
    r"""``\unknowncmd{prose}`` 组内：散文参进 surface，``\unknowncmd{``/``}`` 留 CMD ph。"""
    res = scan_grp(f"\\unknowncmd{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\unknowncmd{" in bodies
    assert "}" in bodies
    assert all(PROSE not in b for b in bodies)


def test_grp_probe_key_arg_stays_opaque() -> None:
    r"""``\unknowncmd{cite-key}`` 组内非散文参：整调用单 CMD ph，参不外流。"""
    res = scan_grp(f"\\unknowncmd{{{KEY}}}")
    bodies = cmd_bodies(res)
    assert f"\\unknowncmd{{{KEY}}}" in bodies
    assert KEY not in blob(res)


def test_grp_probe_opt_arg_not_lifted() -> None:
    r"""``[o]`` 组非散文槽位不挖——形似散文的可选参仍随调用 opaque。"""
    res = scan_grp(f"\\unknowncmd[optional words with several terms here]{{{KEY}}}")
    bodies = cmd_bodies(res)
    whole = f"\\unknowncmd[optional words with several terms here]{{{KEY}}}"
    assert whole in bodies
    assert "optional" not in blob(res)


def test_grp_probe_opt_only_call_stays_cmd() -> None:
    r"""``\\foo[opt]`` 仅可选参命中探针：无 ``{..}`` 散文槽位——整调用单 CMD。"""
    res = scan_grp("\\unknowncmd[o1]")
    assert "\\unknowncmd[o1]" in cmd_bodies(res)


def test_grp_probe_second_arg_prose_first_key() -> None:
    r"""``\unknowncmd{key}{prose}`` 逐参判定：key 参留 CMD，散文参出 surface。"""
    res = scan_grp(f"\\unknowncmd{{{KEY}}}{{{PROSE}.}}")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert any(f"\\unknowncmd{{{KEY}}}" in b and PROSE not in b for b in bodies)
    assert KEY not in blob(res)


def test_grp_probe_two_prose_args_split() -> None:
    r"""``{prose}{prose}`` 双散文参：各自抠出，中段 ``}{`` 归 CMD 结构段。"""
    res = scan_grp(f"\\unknowncmd{{{PROSE}.}}{{{PROSE2}.}}")
    text = blob(res)
    assert PROSE in text
    assert PROSE2 in text
    bodies = cmd_bodies(res)
    assert "\\unknowncmd{" in bodies
    assert "}{" in bodies


def test_grp_probe_nested_cs_in_prose_arg() -> None:
    r"""散文参内嵌未知调用：``_grp_scan`` 子扫把 ``\\innercs{key}`` 折成 CMD。"""
    res = scan_grp(f"\\unknowncmd{{{PROSE} \\innercs{{{KEY}}} inside.}}")
    text = blob(res)
    assert PROSE in text
    assert "inside" in text
    assert KEY not in text
    assert f"\\innercs{{{KEY}}}" in cmd_bodies(res)


def test_grp_probe_swallow_name_stays_opaque() -> None:
    r"""组内 ``\comment{prose}``：吞块名闸命中——散文参不挖，整调用 CMD（W50 面）。"""
    res = scan_grp(f"\\comment{{{PROSE}.}}")
    bodies = cmd_bodies(res)
    assert f"\\comment{{{PROSE}.}}" in bodies
    assert PROSE not in blob(res)


def test_grp_probe_all_caps_rejected() -> None:
    r"""全大写缩写列（``NASA ESA SOHO MISSION LIST``）不算散文——维持 opaque。"""
    res = scan_grp("\\unknowncmd{NASA ESA SOHO MISSION LIST}")
    assert any("NASA" in b for b in cmd_bodies(res))
    assert "NASA" not in blob(res)


def test_grp_probe_commented_prose_not_lifted() -> None:
    r"""参内散文全在注释里：token 流本无注释 token——残文无 ≥4 连词 → opaque。"""
    res = scan_grp(
        "\\unknowncmd{%``A commented out paper title goes here''\n"
        "S.~Passaglia and M.~Sasaki}"
    )
    assert any("Passaglia" in b for b in cmd_bodies(res))
    assert "Passaglia" not in blob(res)


def test_grp_probe_no_args_literal() -> None:
    r"""零消费照旧逐字：``\\foo`` 后无组参 → 名进 surface，不收尾参。"""
    res = scan_grp("\\unknowncmd rest of the paragraph")
    text = blob(res)
    assert "rest of the paragraph" in text
    assert "\\unknowncmd" in text  # 探针全缺席回落逐字（主流同规）


def test_grp_probe_depth_backpressure() -> None:
    r"""嵌套散文参递归子扫到 ``MAX_GEN``：深层 ``\\f{prose}`` 不挖维持
    opaque + ``gen_overflow`` 告警；浅层散文照常出 surface。"""
    depth = 40
    inner = f"{PROSE} deep."
    call = f"\\f{{{inner}}}"
    for _ in range(depth):
        call = f"\\f{{Outer prose words wrap around {call} tail.}}"
    res = scan_grp(call)
    kinds = [w.kind for w in res.warnings]
    assert "gen_overflow" in kinds
    text = blob(res)
    assert "Outer prose words" in text  # 浅层（depth<MAX_GEN）照常挖掘
    assert f"{PROSE} deep." not in text  # 最深层（触底）维持 opaque


def test_grp_probe_in_param_macro() -> None:
    r"""带参宏 ``\\def\\w#1{pre #1 \\unknown{prose} post}`` 调用形——
    ``#1`` 代入与组内探针挖掘并存（``\\def\\wrapper#1{..\\unknown{prose}..}`` 合成现场）。"""
    tex = ART % (
        f"\\def\\w#1{{pre #1 \\unknowncmd{{{PROSE}.}} {PAD}}}\n",
        "\\w{zzk}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\unknowncmd{" in bodies
    assert all(PROSE not in b for b in bodies)
