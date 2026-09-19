r"""键值/名槽尾参挖掘钉版 —— ``_keyval_tail_end`` ``[kv]``/``=[kv]`` 扩展 +
``_handle_cond`` ``if*`` 名槽吸收（kvdig 车道）。

三簇实格泄漏（mock-CJK 落机器槽 → 编译炸）：

- tikzstyle 裸键起头 ``[``/``{`` 列：``\tikzstyle{block} = [rectangle,draw,
  text width=8em,..]``——``\tikzstyle``（argspec ``"m"`` protect）只吃
  ``{block}``，``=[kv]`` 尾列裸落 surface 被译（2009.03715 zh:2038、
  2403.14735 zh:443）。
- l3keys/printbibliography 尾随 ``[kv]``：``\author[1,2]{n}[orcid=,email=]``
  （2410.17963、2403.01255——``_handle_protect_block`` 吃 ``[o]{m}`` 后
  ``[kv]`` 逃逸）、``\printbibliography[title={References},segment=1]``
  （2403.09125——签名 ``""`` 零参路径 ``[`` 无归属）。
- etoolbox/boolexpr ``if*`` 名槽：``\iftoggle{proofs}`` → ``\iftoggle{这是
  译文}``（1306.0026、1511.02547——COND_RX 界标路径只盖 ``\if`` 本体，
  ``{name}`` 组裸落）。

机制：``_kv_list_shaped``（任一项 ``key=`` 或全项裸键 token——``[see
Fig.~1]`` 散文不过门）判形；``_keyval_tail_end`` 吃调用后 ``{kv}``/``[kv]``
（``=`` 起头可选）并入覆盖，非键值组全量回放主流重扫；``_COND_GROUP_ARGS``
白名单在 ``_handle_cond`` 界标端点内吸收前 N 个 ``{..}`` 名/表达式槽——
``{T}{F}`` 支不在吸收数内，留 surface 照常进 chunk；``\newif`` 旗标
（``\ifdraft`` 等，``{`` 是分支内容不是参）不入表。

负例：``[see Fig.~1]`` 散文选参照常可挖、``[draft]`` 裸键吸收不动译文面。
每条过公共不变式（``reconstruct == tex`` + 零告警 + 无缝平铺）。
"""

import re

from conftest import ART, blob, check_invariants

from texlate.latex import parse_tex
from texlate.latex.model import ScanResult


def scan(body: str, defs: str = "") -> ScanResult:
    tex = ART % (defs, body)
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


def ph_bodies(res: ScanResult, kind: str = "CMD") -> list[str]:
    """全部 ``[[KIND_n]]`` ph 覆盖原文。"""
    return [
        body
        for ph, body in res.ph_map.items()
        if re.fullmatch(rf"\[\[{kind}_\d+\]\]", ph)
    ]


# ----------------------------------------------------------- cluster 1: tikzstyle ``=[kv]`` 尾列


def test_tikzstyle_eq_bracket_kv_absorbed() -> None:
    r"""``\tikzstyle{block} = [k=v,..]`` 整调用进 ``[[CMD]]``——``=`` 起头可选。"""
    res = scan(
        "Prose words before the call to keep the paragraph alive here.\n"
        "\\tikzstyle{block} = [rectangle, draw, text width=8em, "
        "text centered, rounded corners, minimum height=4em]\n"
        "More prose after to keep the run alive."
    )
    assert "rectangle" not in blob(res)
    assert "text width" not in blob(res)
    assert any(
        "\\tikzstyle{block} = [rectangle, draw, text width=8em" in b
        for b in ph_bodies(res)
    )


def test_tikzstyle_bare_key_list_absorbed() -> None:
    r"""``\tikzstyle{line} = [draw, -latex]`` 全裸键列同收（``-latex`` 键形）。"""
    res = scan(
        "Prose words before the call to keep the paragraph alive here.\n"
        "\\tikzstyle{line} = [draw, -latex]\n"
        "More prose after to keep the run alive."
    )
    assert "-latex" not in blob(res)
    assert any("\\tikzstyle{line} = [draw, -latex]" in b for b in ph_bodies(res))


def test_tikzstyle_bang_token_list() -> None:
    r"""``[black!10]``——``!`` 在键 token 字符集内，单项裸键列吸收。"""
    res = scan(
        "Prose words before the call to keep the paragraph alive here.\n"
        "\\tikzstyle{fill}=[black!10]\n"
        "More prose after to keep the run alive."
    )
    assert "black!10" not in blob(res)


# ----------------------------------------------------------- cluster 2: 调用后 ``[kv]`` 尾参


def test_author_trailing_bracket_kv() -> None:
    r"""``\author[1,2]{n}[email=..]``——``[kv]`` 尾组并入 ``[[AUTHOR]]``。"""
    res = scan(
        "\\author[1,2]{Horacio Thompson}[%\nemail=someone@example.edu,\n]\n"
        "Body prose after the author block keeps flowing here."
    )
    assert "email=" not in blob(res)
    assert any("email=someone@example.edu" in b for b in ph_bodies(res, "AUTHOR"))


def test_author_trailing_bracket_kv_own_line() -> None:
    r"""``{n}\\n[orcid=..]``——单换行不阻断（``_peek_nonspace`` 过 ws 不过 eol_par）。"""
    res = scan(
        "\\author[1]{Hamza K}\n[orcid=0000-0002-9532-2453]\n"
        "\\ead{hk@example.edu}\n"
        "Body prose after the author block keeps flowing here."
    )
    assert "orcid" not in blob(res)
    assert any("orcid=0000-0002-9532-2453" in b for b in ph_bodies(res, "AUTHOR"))


def test_printbibliography_bracket_kv() -> None:
    r"""签名 ``""`` 零参 protect：``\\printbibliography[kv]`` 尾组并入 ``[[CMD]]``。"""
    res = scan(
        "Body text before to give the run some prose content to translate.\n"
        "\\printbibliography[title={References}, segment=1, "
        "heading=subbibliography]\n"
        "Trailing prose."
    )
    assert "segment=1" not in blob(res)
    assert any(
        "\\printbibliography[title={References}, segment=1" in b for b in ph_bodies(res)
    )


# ----------------------------------------------------------- cluster 3: ``if*`` 名槽


def test_iftoggle_name_slot_protected() -> None:
    r"""``\\iftoggle{name}`` 名槽进界标覆盖；``{T}{F}`` 支留 surface 照译。"""
    res = scan(
        "\\newtoggle{qqtog}\n"
        "The full set of rules is in~"
        "\\iftoggle{qqtog}{the extended figure appendix}"
        "{\\cite{somekey}} and more text follows here."
    )
    assert "\\iftoggle{qqtog}" in res.protected_tex
    assert "qqtog" not in blob(res)
    assert "the extended figure appendix" in blob(res)


def test_ifthenelse_expr_slot_protected() -> None:
    r"""``\\ifthenelse{expr}`` 首参表达式槽吸收；分支照常。"""
    res = scan(
        "Lead-in prose keeps the run alive before the conditional here.\n"
        "\\ifthenelse{\\equal{alpha}{beta}}{the true branch words}"
        "{the false branch words} tail prose keeps going."
    )
    assert "\\ifthenelse{\\equal{alpha}{beta}}" in res.protected_tex
    assert "the true branch words" in blob(res)
    assert "the false branch words" in blob(res)


def test_ifstrequal_two_slots() -> None:
    r"""``\\ifstrequal{a}{b}`` 双名槽同收——吸收数按表白名单。"""
    res = scan(
        "Lead-in prose keeps the run alive before the conditional here.\n"
        "\\ifstrequal{keya}{keyb}{the true branch words}"
        "{\\cite{kb}} tail prose keeps going."
    )
    assert "\\ifstrequal{keya}{keyb}" in res.protected_tex
    assert "keya" not in blob(res)
    assert "the true branch words" in blob(res)


# ----------------------------------------------------------- 负例


def test_bracket_prose_after_call_stays_diggable() -> None:
    r"""``\\author{n} [see Fig.~1 ..]``——非键值组回放，散文选参照常进 chunk。"""
    res = scan(
        "\\author{Some Name} [see Fig.~1 for the details of this "
        "construction here] trailing prose keeps the paragraph alive."
    )
    assert "see Fig.~1 for the details" in blob(res)


def test_draft_bare_key_absorbed() -> None:
    r"""``\\printbibliography[draft]``——裸键形选参并入覆盖，不进译文面。"""
    res = scan(
        "Body text before to give the run some prose content to translate.\n"
        "\\printbibliography[draft]\n"
        "Trailing prose."
    )
    assert "draft" not in blob(res)
    assert any("\\printbibliography[draft]" in b for b in ph_bodies(res))


def test_unknown_if_flag_brace_not_absorbed() -> None:
    r"""非白名单 ``\\ifX{..}``——``{`` 是分支内容不是名槽，组照常进 chunk。"""
    res = scan(
        "Lead-in prose keeps the run alive before the conditional here.\n"
        "\\ifsomeflag{the grouped prose words stay diggable} "
        "tail prose keeps going."
    )
    assert "the grouped prose words stay diggable" in blob(res)


def test_kv_tail_stops_at_eol_par() -> None:
    r"""空行段界不跨——``\\printbibliography\\n\\n[kv]`` 的 ``[kv]`` 不收。"""
    res = scan(
        "Body text before to give the run some prose content to translate.\n"
        "\\printbibliography\n\n[title={References}, segment=1]\n"
        "Trailing prose."
    )
    # ``[title={References}`` 整组回放后落 surface——``References`` 可挖；
    # 界标只吃 ``\printbibliography`` 本体。
    assert any(b.rstrip() == "\\printbibliography" for b in ph_bodies(res))
