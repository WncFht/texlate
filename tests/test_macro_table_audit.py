r"""macro_table.py 审计修复回归（latex-audit-core C2/C3/C5 + latex-audit F9a）。

C5 ``protected_param_positions`` 保护位跨 ``}`` 泄漏；F9a
``register_macros_in`` 不跳 verbatim 污染宏表；C2/C3 ``[n][d]`` 的
n 含可选位在 v1 spec 解析里差一（v2 ``_do_newcmd``/``_do_newenv``
本已正确——本文件只钉 v1 臂与共享函数行为）。
"""

from texlate.latex import parse_tex, parse_tex_v1
from texlate.latex.api import new_state
from texlate.latex.macro_table import (
    protected_param_positions,
    register_macros_in,
    scan_macro_def,
)
from texlate.latex.model import ScanResult

DOC = "\\documentclass{article}\n%s\n\\begin{document}\n%s\n\\end{document}\n"


def scan_v1(body: str, preamble: str = "") -> ScanResult:
    return parse_tex_v1(DOC % (preamble, body))


# ---------------------------------------------------------------- C5 保护位组界


def test_c5_protect_stops_at_group_close() -> None:
    r"""``\cite{#1} and #2``：``#2`` 在 ``\cite`` 参组外 → 不保护。"""
    assert protected_param_positions(r"See \cite{#1} and #2", 2) == (True, False)


def test_c5_protect_per_group() -> None:
    r"""保护随 ``{`` 进组、随 ``}`` 出组；非同层组不继承。"""
    assert protected_param_positions(r"\emph{#1}\cite{#2}", 2) == (False, True)
    assert protected_param_positions(r"\cite{#1}\emph{#2}", 2) == (True, False)
    assert protected_param_positions(r"\cite{#1}{#2}", 2) == (True, False)
    assert protected_param_positions(r"#1 \cite{#2}", 2) == (False, True)


def test_c5_protect_nested_and_opt() -> None:
    r"""嵌套保护组罩住内层；``[..]`` 可选参同为参数位且不吃 armed。"""
    assert protected_param_positions(r"\cite{\ref{#1}}", 1) == (True,)
    assert protected_param_positions(r"\emph{\cite{#1}}#2", 2) == (True, False)
    assert protected_param_positions(r"\includegraphics[#1]{#2}", 2) == (True, True)
    assert protected_param_positions(r"\cite[#1]{#2}#3", 3) == (True, True, False)


def test_c5_protect_single_token_arg() -> None:
    r"""裸 token 参（``\cite#1``）消费一枚即止——``#2`` 不保护。"""
    assert protected_param_positions(r"\cite#1 #2", 2) == (True, False)


def test_c5_protect_v1_callsite() -> None:
    r"""v1 公共路径：``#2`` 纯文本位 → 替换参数进 chunk 而非 ``[[KEY]]``。"""
    res = scan_v1(
        "\\x{sec:k}{SOME TEXT that is long enough to chunk on its own}",
        "\\newcommand{\\x}[2]{See \\cite{#1} and #2}",
    )
    assert any(k.startswith("[[KEY_") and "sec:k" in v for k, v in res.ph_map.items())
    assert any("SOME TEXT" in c.content for c in res.chunks)


def test_c5_protect_v2_callsite() -> None:
    r"""v2 默认路径同形：``#2`` 展开回正文 chunk，``#1`` 落保护占位。"""
    res = parse_tex(
        DOC
        % (
            "\\newcommand{\\x}[2]{See \\cite{#1} and #2}",
            "\\x{sec:k}{SOME TEXT that is long enough to chunk on its own}",
        )
    )
    assert any("SOME TEXT" in c.content for c in res.chunks)
    assert all("sec:k" not in c.content for c in res.chunks)


# ---------------------------------------------------------------- F9a verbatim 屏蔽


def test_f9a_register_skips_verbatim() -> None:
    r"""verbatim/lstlisting/``\verb``/``\lstinline``/comment/注释内假定义不登记。"""
    st = new_state()
    register_macros_in(
        "\\begin{verbatim}\n\\def\\fake{PWNED}\n\\end{verbatim}\n"
        "\\begin{lstlisting}\n\\newcommand{\\lf}{X}\n\\end{lstlisting}\n"
        "\\verb|\\def\\vb{BAD}|\n"
        "\\lstinline|\\def\\li{BAD}|\n"
        "\\begin{comment}\n\\def\\cd{BAD}\n\\end{comment}\n"
        "% \\def\\cm{BAD}\n"
        "\\newif\\iffy\n"
        "\\newcommand{\\real}{YES}\n",
        st,
    )
    assert set(st.macros.cmds) == {"real", "fytrue", "fyfalse"}
    assert "fy" in st.ifflags


def test_f9a_verbatim_def_v1_callsite() -> None:
    r"""v1 公共路径：verbatim 内 ``\\def\\fake`` 不注册 → 调用点走未知命令。"""
    res = scan_v1(
        "Body \\fake after verbatim env.",
        "\\begin{verbatim}\n\\def\\fake{PWNED}\n\\end{verbatim}\n"
        "\\newcommand{\\real}{YES}",
    )
    assert res.macros.lookup("fake") is None
    assert res.macros.lookup("real") is not None


def test_f9a_def_body_byte_faithful() -> None:
    r"""遮盖视图仅供定位——命中定义的体仍在原串解析，字节不丢。"""
    st = new_state()
    register_macros_in("\\newcommand{\\real}{Body \\emph{#1} tail}\n", st)
    assert st.macros.cmds["real"].body == "Body \\emph{#1} tail"


# ---------------------------------------------------------------- C2/C3 [n][d] 差一


def test_c2_newcommand_spec_counts_opt() -> None:
    r"""``\\newcommand{\\foo}[2][d]``：n 含可选位 → spec ``[o,m]`` 且录默认值。"""
    st = new_state()
    scan_macro_def(r"\newcommand{\foo}[2][d]{#1/#2}", 0, "newcommand", st)
    spec = st.macros.cmds["foo"].spec
    assert [s.kind for s in spec] == ["o", "m"]
    assert spec[0].default == "d"


def test_c2_newcommand_spec_variants() -> None:
    r"""无 ``[d]`` 时 n 全为强制位；``[1][d]`` → 纯 ``[o]``。"""
    st = new_state()
    scan_macro_def(r"\newcommand{\a}[2]{#1#2}", 0, "newcommand", st)
    scan_macro_def(r"\newcommand{\b}[1][d]{#1}", 0, "newcommand", st)
    scan_macro_def(r"\newcommand{\c}{x}", 0, "newcommand", st)
    assert [s.kind for s in st.macros.cmds["a"].spec] == ["m", "m"]
    assert [s.kind for s in st.macros.cmds["b"].spec] == ["o"]
    assert st.macros.cmds["c"].spec == []


def test_c2_newcommand_v1_callsite() -> None:
    r"""v1 公共路径：幻影第 3 参不再吞正文 token 进 ``[[MACRO]]``。"""
    res = scan_v1(
        "\\foo{a} TAIL words here for chunk coverage.",
        "\\newcommand{\\foo}[2][d]{#1/#2}",
    )
    macros = {k: v for k, v in res.ph_map.items() if k.startswith("[[MACRO_")}
    assert macros
    assert all(v == "\\foo{a}" for v in macros.values())
    assert any("TAIL words" in c.content for c in res.chunks)


def test_c3_newenvironment_nargs_counts_opt() -> None:
    r"""``\\newenvironment{ee}[2][d]`` → 强制位 1；无 ``[d]`` 时 n 全强制。"""
    st = new_state()
    scan_macro_def(r"\newenvironment{ee}[2][d]{B}{A}", 0, "newenvironment", st)
    scan_macro_def(r"\newenvironment{ff}[2]{B}{A}", 0, "newenvironment", st)
    assert st.macros.envs["ee"].nargs == 1
    # ff 无 ``[d]`` → n 全强制：恰比 ee 多一位
    assert st.macros.envs["ff"].nargs == st.macros.envs["ee"].nargs + 1


def test_c3_newenvironment_v1_callsite() -> None:
    r"""v1 公共路径：``\\begin{ee}{a}{b}`` 只取 ``{a}``——``{b}`` 回落正文。"""
    res = scan_v1(
        "\\begin{ee}{a}{b} TEXT body here with plenty of words. \\end{ee}",
        "\\newenvironment{ee}[2][d]{B}{A}",
    )
    assert any("{b} TEXT body" in c.content for c in res.chunks)
