r"""``_group_surface`` 组内分派三族修复的行为钉（签名面裁决见
``test_dispatch_mirror._SIG_DIFFS``——这里钉的是译文面行为）：

- **chunk-arg**：``\section[opt]{t}`` 组内名+头参进 ``[[CMD]]``、``{t}``
  组 token 留 surface——修复前行缺，``\section{`` 名连括号漏进译文面。
- **protect-block**：``\author[opt]{..}{key=..}`` 组内整调用 →
  ``[[AUTHOR]]``——修复前行缺，名+参裸落 surface 散文。
- **单 token 禁食 + inline-literal**：argspec text 位 ``\emph p`` 不再把
  首字母 ``p`` 吸进 ``[[CMD]]``（``ost``/``zzw`` 尾段裸露腐蚀类）；
  ``\5``/``\_`` 无参字面不再被 argspec 假条目/探针吃掉随行参。
"""

import pytest
from conftest import ART, check_invariants

from texlate.latex import parse_tex
from texlate.latex.model import ScanResult

# 组 surface 须过 CHUNK_MIN 才成 chunk——统一垫词，别让样本落 literal 路
PAD = "pad words here to push past the minimum limit"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def ph_body(res: ScanResult, typ: str) -> list[str]:
    """``ph_map`` 里 ``[[{typ}_n]]`` 全体 body。"""
    return [v for k, v in res.ph_map.items() if k.startswith(f"[[{typ}")]


def blob(res: ScanResult) -> str:
    """全部 chunk content 拼接——可见面断言口径。"""
    return "\n".join(c.content for c in res.chunks)


# ------------------------------------------------------------ chunk-arg 族


def test_chunk_arg_name_into_cmd_arg_stays_surface() -> None:
    r"""``\section{t}``：名进 ``[[CMD]]``，``{t}`` 组整体留 surface 可见。"""
    tex = ART % (
        "\\def\\s{\\section{Intro Words Here} " + PAD + "}\n",
        "\\s",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "CMD") == ["\\section"]
    assert "{Intro Words Here}" in blob(res)  # 花括号随组留 surface
    assert "\\section" not in blob(res)  # 修复前名+{ 裸漏译文面


def test_chunk_arg_opt_head_into_cmd() -> None:
    r"""``\section[Sh]{t}``：``[opt]`` 头参随名进 ``[[CMD]]``。"""
    tex = ART % (
        "\\def\\s{\\section[Sh]{Long Title Words} " + PAD + "}\n",
        "\\s",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "CMD") == ["\\section[Sh]"]
    assert "{Long Title Words}" in blob(res)


def test_chunk_arg_star_form() -> None:
    r"""``\section*{t}``：``*`` 随名进 ``[[CMD]]``。"""
    tex = ART % (
        "\\def\\s{\\section*{Starred Title Words} " + PAD + "}\n",
        "\\s",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "CMD") == ["\\section*"]
    assert "{Starred Title Words}" in blob(res)


def test_chunk_arg_bail_without_group() -> None:
    r"""``\section zzq``：可译槽非 ``{..}`` 组 → 名逐字回落留 surface。"""
    tex = ART % (
        "\\def\\s{\\section zzq " + PAD + "}\n",
        "\\s",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "CMD") == []
    assert "\\section zzq" in blob(res)


def test_chunk_arg_empty_group_literal() -> None:
    r"""``\section{}``：空参 → 整调用逐字（主流空参同规）。"""
    tex = ART % (
        "\\def\\s{\\section{} " + PAD + "}\n",
        "\\s",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "CMD") == []
    assert "\\section{}" in blob(res)


def test_chunk_arg_captionof_type_head() -> None:
    r"""``\captionof{figure}{t}``（``mom``,2）：``{figure}`` 头参进 ``[[CMD]]``。"""
    tex = ART % (
        "\\def\\c{\\captionof{figure}{Cap Words Here} " + PAD + "}\n",
        "\\c",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "CMD") == ["\\captionof{figure}"]
    assert "{Cap Words Here}" in blob(res)


# ---------------------------------------------------------- protect-block 族


def test_protect_block_whole_call() -> None:
    r"""``\author{John Doe}``：整调用 → ``[[AUTHOR]]``，参不裸进散文。"""
    tex = ART % (
        "\\def\\a{\\author{John Doe} " + PAD + "}\n",
        "\\a",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "AUTHOR") == ["\\author{John Doe}"]
    assert "John Doe" not in blob(res)
    assert "\\author" not in blob(res)


def test_protect_block_opt_arg() -> None:
    r"""``\author[JD]{n}``：``[opt]``+``{m}`` 同进 ``[[AUTHOR]]``。"""
    tex = ART % (
        "\\def\\a{\\author[JD]{John Doe} " + PAD + "}\n",
        "\\a",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "AUTHOR") == ["\\author[JD]{John Doe}"]


def test_protect_block_abort_covers_cs_only() -> None:
    r"""``\author`` 无 ``{`` 跟随 → abort 只护 cs 本体，随行散文可见。"""
    tex = ART % (
        "\\def\\a{\\author " + PAD + "}\n",
        "\\a",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "AUTHOR") == ["\\author"]
    assert PAD in blob(res)


def test_protect_block_keyval_tail() -> None:
    r"""``\author{Doe}{affil=MIT}``：keyval 形续组同护（aipproc 二参同规）。"""
    tex = ART % (
        "\\def\\a{\\author{Doe}{affil=MIT} " + PAD + "}\n",
        "\\a",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "AUTHOR") == ["\\author{Doe}{affil=MIT}"]


def test_protect_block_nonkeyval_tail_stays() -> None:
    r"""``\author{Doe}{plain}``：非 keyval 续组不吃——``{plain}`` 留 surface。"""
    tex = ART % (
        "\\def\\a{\\author{Doe}{plain words} " + PAD + "}\n",
        "\\a",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "AUTHOR") == ["\\author{Doe}"]
    assert "{plain words}" in blob(res)


# ------------------------------------------- 单 token 禁食（text 位/thead 路）


def test_emph_bare_word_not_stolen() -> None:
    r"""``\emph post``：text 位不吃裸 token——``post`` 整词留 surface。

    修复前 ``m`` 位单 token 臂吃掉首字母 ``p`` 进 ``[[CMD]]``，``ost``
    尾段裸落 surface——签名面看不见的散字母偷吃（腐蚀类）。
    """
    tex = ART % (
        "\\def\\v{pre \\emph post " + PAD + "}\n",
        "\\v",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\emph post" in blob(res)
    assert ph_body(res, "CMD") == []


def test_emph_bare_following_word_intact() -> None:
    r"""``\emph pzzw`` 探针：吃首字母则 ``pzzw`` 解体为 ``zzw``——钉整词。"""
    tex = ART % (
        "\\def\\v{pre \\emph pzzw " + PAD + "}\n",
        "\\v",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "pzzw" in blob(res)  # 修复前 p 入 [[CMD]]、surface 只剩 zzw
    assert ph_body(res, "CMD") == []


def test_textcolor_bare_color_not_stolen() -> None:
    r"""``\textcolor red``：thead 路 ``allow_single_token=False``——``red`` 是散文。"""
    tex = ART % (
        "\\def\\v{xx \\textcolor red " + PAD + "}\n",
        "\\v",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\textcolor red" in blob(res)
    assert ph_body(res, "CMD") == []


def test_textcolor_braced_head_still_eaten() -> None:
    r"""``\textcolor{red}{t}``：花括号头参照常进 ``[[CMD]]``，``{t}`` 留 surface。"""
    tex = ART % (
        "\\def\\v{xx \\textcolor{red}{yes words} " + PAD + "}\n",
        "\\v",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ph_body(res, "CMD") == ["\\textcolor{red}"]
    assert "{yes words}" in blob(res)


# ------------------------------------------------------------- inline-literal


def test_inline_literal_digit_keeps_arg() -> None:
    r"""``\5{zz}``：单字符非字母命令无参字面——``{zz}`` 不被探针吸走。"""
    tex = ART % (
        "\\def\\v{aa \\5{zz} bb " + PAD + "}\n",
        "\\v",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\5{zz}" in blob(res)
    assert ph_body(res, "CMD") == []


def test_inline_literal_underscore_keeps_arg() -> None:
    r"""``\_{zz}``：argspec 假条目（``m`` protect）被 inline-literal 行截停。"""
    tex = ART % (
        "\\def\\v{aa \\_{zz} bb " + PAD + "}\n",
        "\\v",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\_{zz}" in blob(res)
    assert ph_body(res, "CMD") == []


def test_inline_literal_font_switch() -> None:
    r"""``\bf`` 字体开关：零参字面，随行词不吸。"""
    tex = ART % (
        "\\def\\v{aa \\bf bb " + PAD + "}\n",
        "\\v",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\bf bb" in blob(res)
    assert ph_body(res, "CMD") == []
