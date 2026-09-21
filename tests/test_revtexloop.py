"""revtex4-2/ltxgrid ``\\topskip`` 毒根——``upgrade_209`` 消毒单测。

gr-qc/0104075 实证：209 preamble 的 ``\\topskip 0mm`` 随升级进入 revtex4-2，
ltxgrid 输出例程页盒丈量失同步——``\\end{document}`` ``\\clearpage`` 死循环
（7 万页 SIGKILL）；``\\topskip <正值>`` 不循环但整页被吞。升级产物中深度 0、
语句首位的活 ``\\topskip`` 赋值一律剥除；读用位（``\\ifdim``/``=`` 右值）与
花括号内局部赋值不动。
"""

import pytest
from _latex209kit import target_always_resolvable  # noqa: F401

from texlate.compile.latex209 import upgrade_209


def test_topskip_dropped_on_revtex_upgrade() -> None:
    """gr-qc/0104075 几何块形：只剥 topskip，其余 209 版面行原样保留。"""
    tex = (
        "\\documentstyle[aps,epsfig]{revtex}\n"
        "\\topskip 0mm\n"
        "\\headheight 0mm\n"
        "\\textheight 238mm\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    out, info = upgrade_209(tex)
    assert info["status"] == "converted"
    assert info["target"] == "revtex4-2"
    assert info["topskip_dropped"] == 1
    assert "\\topskip" not in out
    assert "\\headheight 0mm" in out
    assert "\\textheight 238mm" in out


@pytest.mark.parametrize(
    "assign", ["\\topskip 0mm", "\\topskip=0mm", "\\topskip .5pt", "\\topskip -2pt"]
)
def test_topskip_assign_forms_dropped(assign: str) -> None:
    """裸赋值各形（空白/等号/小数/负值）全剥。"""
    out, info = upgrade_209(f"\\documentstyle{{revtex}}\n{assign}\nx\n")
    assert "\\topskip" not in out
    assert info["topskip_dropped"] == 1


def test_topskip_kept_for_non_ltxgrid_target() -> None:
    """article 等标准输出例程容忍 topskip——不剥，保作者语义。"""
    tex = "\\documentstyle{article}\n\\topskip 0mm\nx\n"
    out, info = upgrade_209(tex)
    assert "\\topskip 0mm" in out
    assert info["topskip_dropped"] == 0


def test_topskip_read_positions_kept() -> None:
    """读用位不剥：``\\ifdim`` 条件、``=`` 右值、花括号内局部赋值。"""
    tex = (
        "\\documentstyle{revtex}\n"
        "\\dimen0=\\topskip\n"
        "\\ifdim\\topskip=0mm \\fi\n"
        "{\\topskip 0mm}\n"
        "x\n"
    )
    out, info = upgrade_209(tex)
    assert out.count("\\topskip") == 3  # noqa: PLR2004
    assert info["topskip_dropped"] == 0


def test_topskip_multiple_dropped() -> None:
    """多处活赋值逐命中倒序剥除。"""
    tex = "\\documentstyle{revtex}\n\\topskip 0mm\ny\n\\topskip 1pt\nx\n"
    out, info = upgrade_209(tex)
    assert "\\topskip" not in out
    assert info["topskip_dropped"] == 2  # noqa: PLR2004


def test_topskip_commented_not_counted() -> None:
    """注释内的 topskip 字样经遮盖视图豁免。"""
    tex = "\\documentstyle{revtex}\n% \\topskip 0mm\nx\n"
    out, info = upgrade_209(tex)
    assert info["topskip_dropped"] == 0
    assert "% \\topskip 0mm" in out
