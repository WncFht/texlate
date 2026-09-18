r"""cs 对界 DSL 块钉（W29 pinlabel ``\labellist…\endlabellist``）。

``PAIR_BLOCK_CMDS`` 登记的 cs 对 → ``[[ENV]]`` 保护块 + mined 子扫：
``\pinlabel {tex}`` 标签文照产 chunk、``at x y`` 坐标脚手架与
开/闭 cs 名一律不裸进可译面。未闭合/孤闭 cs 走保守路径。
"""

from __future__ import annotations

import pytest
from conftest import DOC

from texlate.latex import parse_tex


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


_LABELLIST_DOC = DOC % (
    "\\labellist\n"
    "\\pinlabel {$s = $} [ ] at -10 10\n"
    "\\pinlabel {hidden label text} at 20 30\n"
    "\\endlabellist\n"
    "Normal prose paragraph that should be fully translated now."
)


def test_labellist_scaffolding_not_in_chunks() -> None:
    """开/闭 cs 名与 ``at x y`` 坐标均不出现在任何 chunk surface（W29 主钉）。"""
    res = parse_tex(_LABELLIST_DOC)
    all_chunks = "\n".join(c.content for c in res.chunks)
    assert "labellist" not in all_chunks
    assert "at -10 10" not in all_chunks
    assert "at 20 30" not in all_chunks
    assert "Normal prose paragraph" in all_chunks


def test_labellist_pinlabel_args_mined() -> None:
    """``\\pinlabel {tex}`` 的可译参照挖成独立 chunk（含数学形经 MATH ph）。"""
    res = parse_tex(_LABELLIST_DOC)
    contents = [c.content for c in res.chunks]
    assert any("hidden label text" in c for c in contents)
    # ``{$s = $}`` 标签：math 参在 chunk-arg 子扫内 ph 化
    assert any("[[MATH_" in c for c in contents)


def test_labellist_env_body_carries_scaffolding() -> None:
    """整段在 ``[[ENV]]`` ph 体内——identity 字节全留、脚手架随体保护。"""
    res = parse_tex(_LABELLIST_DOC)
    envs = {k: v for k, v in res.ph_map.items() if k.startswith("[[ENV_")}
    assert len(envs) == 1
    body = next(iter(envs.values()))
    assert "\\labellist" in body
    assert "\\endlabellist" in body
    assert "at -10 10" in body


def test_labellist_env_form_begin_end() -> None:
    """``\\begin{labellist}`` env 形同样整块保护（PROTECTED_ENVS 登记）。"""
    res = parse_tex(
        DOC % (
            "\\begin{labellist}\n"
            "\\pinlabel {env form label} at 1 2\n"
            "\\end{labellist}\n"
            "Prose paragraph after the env form label block."
        )
    )
    all_chunks = "\n".join(c.content for c in res.chunks)
    assert "at 1 2" not in all_chunks
    assert "Prose paragraph after the env form" in all_chunks


def test_labellist_mixed_close() -> None:
    """``\\labellist…\\end{labellist}`` 混搭闭形（``\\end{X}``→``\\endX`` 对价）。"""
    res = parse_tex(
        DOC % (
            "\\labellist\n"
            "\\pinlabel {mixed close label} at 3 4\n"
            "\\end{labellist}\n"
            "Trailing prose that must remain translatable."
        )
    )
    all_chunks = "\n".join(c.content for c in res.chunks)
    assert "at 3 4" not in all_chunks
    assert "Trailing prose" in all_chunks


def test_labellist_unclosed_falls_back() -> None:
    """无 ``\\endlabellist``：``unclosed_env`` 告警 + unknown-cs 保守路径。"""
    res = parse_tex(
        DOC % (
            "\\labellist\n"
            "\\pinlabel {dangling} at 5 6\n"
            "Paragraph continues without a block closer here."
        )
    )
    assert any(w.kind == "unclosed_env" for w in res.warnings)


def test_endlabellist_stray_is_cmd() -> None:
    """孤 ``\\endlabellist`` → ``[[CMD]]`` 进 run，不裸进可译面。"""
    res = parse_tex(
        DOC % (
            "Prose before the stray closer. \\endlabellist "
            "More prose after it continues the same run here."
        )
    )
    all_chunks = "\n".join(c.content for c in res.chunks)
    assert "endlabellist" not in all_chunks


def test_labellist_inside_group() -> None:
    """组内 ``\\labellist…\\endlabellist`` → 整段 ENV ph（B 臂对价）。"""
    res = parse_tex(
        DOC % (
            "\\newcommand{\\vv}{\\labellist \\pinlabel {x} at 1 1 \\endlabellist}\n"
            "A long enough prose paragraph to carry the expansion chunk "
            "well past the threshold for sure \\vv and trailing words."
        )
    )
    all_chunks = "\n".join(c.content for c in res.chunks)
    assert "at 1 1" not in all_chunks


def test_tablenotetext_note_mined() -> None:
    """``\\tablenotetext{a}{note}``：mark 参保护、note 文可译（W86 挖掘面）。"""
    res = parse_tex(
        DOC % (
            "\\begin{deluxetable}{lcc}\n"
            "\\tablecaption{Cap text}\n"
            "\\tablenotetext{a}{Measured with interferometry methods.}\n"
            "\\end{deluxetable}\n"
            "Prose after the table."
        )
    )
    contents = [c.content for c in res.chunks]
    assert any("Measured with interferometry methods." in c for c in contents)


def test_tablecomments_mined() -> None:
    """``\\tablecomments{text}`` 表尾注可译参挖掘。"""
    res = parse_tex(
        DOC % (
            "\\tablecomments{All magnitudes are on the AB system here.}\n"
            "Following prose stays in the translation flow."
        )
    )
    contents = [c.content for c in res.chunks]
    assert any("AB system" in c for c in contents)
