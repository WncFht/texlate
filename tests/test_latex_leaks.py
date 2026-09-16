r"""四条泄漏机制的回归测试（rewrite-spec 泄漏表 + docs/07 §11）。

A ``_args`` 单 token 兜底吞 ``$``/``\\``；
B in-arg 注释；C1 env 名 ``*`` 归一；C2 in-arg 未知 env；D in-arg 条件式。
"""

import re

from texlate.latex import parse_tex, reconstruct
from texlate.latex.api import new_state
from texlate.latex.model import PhType, ScanResult
from texlate.latex.scanner import Scanner

DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"
LEAK_DOLLAR = re.compile(r"\$")
LEAK_COND = re.compile(r"\\(?:if[a-zA-Z]+|else|fi)(?![a-zA-Z])")
LEAK_BEGIN = re.compile(r"\\begin\{")


def scan(body: str) -> ScanResult:
    return parse_tex(DOC % body)


def blob(res: ScanResult) -> str:
    return "\n".join(c.content for c in res.chunks)


# ---------------------------------------------------------------- 机制 A


def test_leak_a_single_token_does_not_eat_dollar() -> None:
    r"""``\num{53807} $(2.5`` 场景：未知/带参命令的单 token 兜底不得吞 ``$``。"""
    res = scan("Values \\num{53807} $(2.5, 3)$ here.")
    # $(2.5, 3)$ 必须成 [[MATH]]，而不是被当 \num 的第二参数吞掉
    assert not LEAK_DOLLAR.search(blob(res))
    assert any(v == "$(2.5, 3)$" for v in res.ph_map.values())


def test_leak_a_single_token_stops_at_backslash() -> None:
    r"""单 token 参数读到 ``\\`` 必须停——``\cmd \letters`` 不切命令名。"""
    res = scan("Text \\foo \\barbaz continues.")
    # \foo 未知无参 → 逐字；\barbaz 完整保留不被切断
    assert reconstruct(res) == DOC % "Text \\foo \\barbaz continues."
    assert not any(w.kind == "letters_cut" for w in res.warnings)


def test_leak_a_letters_cut_detection() -> None:
    r"""BUG1 断言本体：ph 体以 ``\\letters`` 结尾且后继是字母 → ``letters_cut``。"""
    state = new_state()
    sc = Scanner(state)
    sc._tex = "\\abcdef"  # noqa: SLF001 — 断言机制单测
    sc._ph(PhType.CMD, "\\ab", cut_end=3)  # noqa: SLF001 — 体尾 \ab 后继 'd' 字母
    assert any(w.kind == "letters_cut" for w in state.warnings)


def test_leak_a_empty_spec_no_ws_swallow() -> None:
    r"""空 argspec 的 OPAQUE 宏不吞命令后空白——``\CX\ngate`` 不误报不切断。"""
    body = (
        "\\newcommand{\\CX}{\\ensuremath{\\wedge {\\sf X}}\\xspace}\n"
        "the \\CX\ngate by conjugating"
    )
    res = scan(body)
    assert not any(w.kind == "letters_cut" for w in res.warnings)
    assert reconstruct(res) == DOC % body
    assert any(v == "\\CX" for v in res.ph_map.values())


# ---------------------------------------------------------------- 机制 B


def test_leak_b_comment_in_arg() -> None:
    r"""``\caption{a % comment\n b}``：参数内注释 → ``[[COMMENT]]`` 不留裸 ``%``。"""
    res = scan("\\caption{Cap text % trailing comment\n continues}")
    b = blob(res)
    assert "%" not in re.sub(r"\[\[COMMENT_\d+\]\]", "", b)
    assert any(t.startswith("[[COMMENT") for t in res.ph_map)
    assert (
        reconstruct(res) == DOC % "\\caption{Cap text % trailing comment\n continues}"
    )


# ---------------------------------------------------------------- 机制 C


def test_leak_c1_env_star_normalized() -> None:
    r"""``\begin{multline*}…\end{multline}`` 笔误：双侧 ``rstrip('*')`` 仍配对。"""
    body = "Text\n\\begin{multline*}x=1\\end{multline}\nmore"
    res = scan(body)
    assert "\\begin{multline*}x=1\\end{multline}" in res.ph_map.values()
    assert not any(
        w.kind == "unclosed_env" and "multline" in w.detail for w in res.warnings
    )


def test_leak_c2_unknown_env_in_arg() -> None:
    r"""in_arg 未知 env → ``[[ENV]]`` 进 run——``\\begin{`` 不进 chunk。"""
    res = scan("\\section{Title \\begin{strangeenv}x\\end{strangeenv} end}")
    assert not LEAK_BEGIN.search(blob(res))
    assert any(
        v == "\\begin{strangeenv}x\\end{strangeenv}" for v in res.ph_map.values()
    )


def test_arg_transparent_env_in_arg() -> None:
    r"""in_arg 容器白名单（itemize 等）→ ``[[ENVTAG]]`` + 内部照挖。"""
    res = scan("\\section{T \\begin{itemize}\\item inner text here\\end{itemize}}")
    types = {k.split("_")[0].strip("[]") for k in res.ph_map}
    assert "ENVTAG" in types
    assert "inner text here" in blob(res)


# ---------------------------------------------------------------- 机制 D


def test_leak_d_cond_in_arg() -> None:
    r"""in_arg ``\ifAnonymous{a}{b}`` → ``[[COND]]`` 整调用，不泄 ``\\if``。"""
    res = scan("\\footnote{Text \\ifAnonymous{alice}{bob} end}")
    b = blob(res)
    assert not LEAK_COND.search(b)
    assert any(t.startswith("[[COND") for t in res.ph_map)


def test_if_macro_toplevel_protects_whole_call() -> None:
    r"""非原语 ``if*`` 宏（``\newcommand{\ifX}[2]``）→ 整调用 ``[[CMD]]``。"""
    body = "\\newcommand{\\ifAnon}[2]{#1}\nText \\ifAnon{a}{b} tail"
    res = scan(body)
    assert "\\ifAnon{a}{b}" in res.ph_map.values()
    assert not LEAK_COND.search(
        res.protected_tex.replace("\\newcommand{\\ifAnon}[2]{#1}", "")
    )
    assert not LEAK_COND.search(blob(res))


# ---------------------------------------------------------------- 综合


def test_known_unclosable_dollar_degrades() -> None:
    r"""真不配对 ``$``（corpus 作者笔误）→ literal + ``unpaired_dollar``，不吞后文。"""
    body = "the scalar $dx^T x = x^T dx).\n\nNext paragraph text here."
    res = scan(body)
    assert any(w.kind == "unpaired_dollar" for w in res.warnings)
    assert reconstruct(res) == DOC % body


# ---------------------------------------------------------------- 展开组内再生段（_group_surface）


def test_group_verb_protected() -> None:
    r"""展开组内 ``\verb|raw$|`` → ``[[VERB]]``——逐字内容不泄可译 surface。

    ``_group_surface`` 曾缺 verb 行：``\verb`` 落默认支，``|raw$|`` 逐字
    进 surface（``$`` 还扰 math 判定）。
    """
    body = "\\newcommand{\\vv}{pre \\verb|raw$| post}\nText \\vv tail words here."
    res = scan(body)
    assert any(v == "\\verb|raw$|" for v in res.ph_map.values())
    assert "raw$" not in blob(res)
    assert "pre" in blob(res)
    assert "post" in blob(res)
    assert reconstruct(res) == DOC % body


def test_group_verb_unpaired_falls_literal() -> None:
    r"""组内 ``\verb|x`` 无闭符（EOL 上限）→ 逐字回落，同主流档。"""
    body = "\\newcommand{\\vv}{pre \\verb|raw\npost}\nText \\vv tail words here."
    res = scan(body)
    assert "raw" in blob(res)  # 逐字回落后内容照常进可译面
    assert reconstruct(res) == DOC % body


def test_group_hyperref_text_arg_kept() -> None:
    r"""展开组内 ``\hyperref[l]{text}``：``[label]`` 随命令保护，``{text}``
    留可译 surface——``*ref`` 后缀规则曾把整调用吞进 ``[[REF]]`` 丢 text。"""
    body = (
        "\\newcommand{\\hh}{\\hyperref[sec:x]{translatable link text}}\n"
        "See \\hh now ok."
    )
    res = scan(body)
    assert "translatable link text" in blob(res)
    assert "sec:x" not in blob(res)
    assert reconstruct(res) == DOC % body


def test_group_hyperref_brace_key_form() -> None:
    r"""``\\hyperref{key}{text}`` 双参形：首参（key）保护、次参留 surface。"""
    body = (
        "\\newcommand{\\hh}{\\hyperref{sec:y}{brace key text here}}\nSee \\hh now ok."
    )
    res = scan(body)
    assert "brace key text here" in blob(res)
    assert "sec:y" not in blob(res)
    assert reconstruct(res) == DOC % body


def test_group_href_url_protected() -> None:
    r"""展开组内 ``\href{url}{text}``：``{url}`` → ``[[HREF]]``，``{text}``
    留可译 surface（主版 ``_handle_href`` 同形）。"""
    body = "\\newcommand{\\hh}{\\href{http://x.y/z}{click me link}}\nSee \\hh ok."
    res = scan(body)
    assert any(
        k.startswith("[[HREF_") and v == "{http://x.y/z}" for k, v in res.ph_map.items()
    )
    assert "http://x.y/z" not in blob(res)
    assert "click me link" in blob(res)
    assert reconstruct(res) == DOC % body


def test_group_url_delim_form() -> None:
    r"""展开组内 ``\url|http://..|`` 定界形 → ``[[URL]]``（主版 verbatim 支对价）。"""
    body = "\\newcommand{\\uu}{\\url|http://x.y/|}\nSee \\uu tail text here."
    res = scan(body)
    assert any(
        k.startswith("[[URL_") and v == "\\url|http://x.y/|"
        for k, v in res.ph_map.items()
    )
    assert "http://x.y/" not in blob(res)
    assert reconstruct(res) == DOC % body
