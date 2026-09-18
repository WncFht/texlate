"""``latex.api`` env 分派实臂钉——``TEXLATE_NO_EXPAND=1`` 下 v1 臂真跑。

``test_latex_env_dispatch.py`` 用 spy 钉分派方向（哪个臂被调、返回值透传）；
本文件钉实臂投影：env 置真时 ``parse_tex``/``parse_file`` 的实跑输出须与
直调 ``parse_tex_v1``/``parse_file_v1`` 逐字段一致，且带 v1 指纹
（``vtex == ""``——v2 单文件恒 ``vtex == 入参``，见 model.py ScanResult）。

spy 钉不住「分派对了但 v1 臂自身断链」——v1 臂是纯包内代码无额外依赖，
干净 clone 直跑即可，无需 skipif。
"""

from pathlib import Path

import pytest
from conftest import DOC

from texlate.latex import api
from texlate.latex.model import ScanResult

_TEX = DOC % "Hello \\emph{world} and $x^2$ math here."


def _proj(res: ScanResult) -> tuple[object, ...]:
    """稳定投影：``macros``（ScopeMacroTable 无 eq 口径）外全部可观测字段。

    pieces/chunks/warnings 元素皆是 dataclass（含 Span），``==`` 逐字段
    递归比较；list/dict 成员直接进元组参与等值。
    """
    return (
        res.protected_tex,
        res.vtex,
        res.ph_map,
        res.ph_reserved,
        res.pieces,
        res.chunks,
        res.warnings,
        res.inputs,
    )


@pytest.mark.parametrize("val", ["1", "true", "TRUE", " yes ", "on"])
def test_no_expand_truthy_runs_real_v1(clean_env: pytest.MonkeyPatch, val: str) -> None:
    """真值表全词（strip+lower 归一）→ 实 v1 臂，投影 == 直调 ``parse_tex_v1``。"""
    clean_env.setenv("TEXLATE_NO_EXPAND", val)
    got = api.parse_tex(_TEX)
    assert got.vtex == ""  # v1 指纹：若 parse_tex_v1 被改道 v2，此处先爆
    assert _proj(got) == _proj(api.parse_tex_v1(_TEX))


@pytest.mark.parametrize("val", [None, "0", "false", "off", "2"])
def test_default_and_falsy_run_real_v2(
    clean_env: pytest.MonkeyPatch, val: str | None
) -> None:
    """缺席/假值/非白名单词（``2`` 这类「非空即真」陷阱）→ 实 v2 臂。"""
    if val is None:
        clean_env.delenv("TEXLATE_NO_EXPAND", raising=False)
    else:
        clean_env.setenv("TEXLATE_NO_EXPAND", val)
    got = api.parse_tex(_TEX)
    assert got.vtex == _TEX  # v2 指纹：单文件叙事序虚拟文本 == 入参
    assert _proj(got) == _proj(api.parse_tex_v2(_TEX))


def test_parse_file_no_expand_runs_v1_flatten(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """文件臂：env=1 → v1 ``flatten_inputs`` 路径真跑（``\\input`` 内联为证）。"""
    clean_env.setenv("TEXLATE_NO_EXPAND", "1")
    (tmp_path / "sub.tex").write_text(
        "Sub prose body text lives here.\n", encoding="utf-8"
    )
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{sub}\n\\end{document}\n",
        encoding="utf-8",
    )
    got = api.parse_file(main)
    assert got.vtex == ""
    # flatten 实跑证据：子文件散文内联后进 chunk 面（v1 不记 inputs）
    assert any("Sub prose body text" in c.content for c in got.chunks)
    assert _proj(got) == _proj(api.parse_file_v1(main))


def test_parse_file_default_runs_v2_gullet_flatten(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """对照：默认臂走 gullet 内联——``vtex`` 含子文件文本且 ``inputs`` 记账。"""
    clean_env.delenv("TEXLATE_NO_EXPAND", raising=False)
    (tmp_path / "sub.tex").write_text(
        "Sub prose body text lives here.\n", encoding="utf-8"
    )
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{sub}\n\\end{document}\n",
        encoding="utf-8",
    )
    got = api.parse_file(main)
    assert "Sub prose body text" in got.vtex
    assert got.inputs  # gullet 臂 (vpos, abspath) 记账
