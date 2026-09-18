r"""四条泄漏机制的回归测试（rewrite-spec 泄漏表 + docs/07 §11）。

A ``_args`` 单 token 兜底吞 ``$``/``\\``；
B in-arg 注释；C1 env 名 ``*`` 归一；C2 in-arg 未知 env；D in-arg 条件式。
"""

import re

from conftest import DOC, blob, scan_doc

from texlate.latex import parse_tex, reconstruct

LEAK_DOLLAR = re.compile(r"\$")
LEAK_COND = re.compile(r"\\(?:if[a-zA-Z]+|else|fi)(?![a-zA-Z])")
LEAK_BEGIN = re.compile(r"\\begin\{")


# ---------------------------------------------------------------- 机制 A


def test_leak_a_single_token_does_not_eat_dollar() -> None:
    r"""``\num{53807} $(2.5`` 场景：未知/带参命令的单 token 兜底不得吞 ``$``。"""
    res = scan_doc("Values \\num{53807} $(2.5, 3)$ here.")
    # $(2.5, 3)$ 必须成 [[MATH]]，而不是被当 \num 的第二参数吞掉
    assert not LEAK_DOLLAR.search(blob(res))
    assert any(v == "$(2.5, 3)$" for v in res.ph_map.values())


def test_leak_a_single_token_stops_at_backslash() -> None:
    r"""单 token 参数读到 ``\\`` 必须停——``\cmd \letters`` 不切命令名。"""
    res = scan_doc("Text \\foo \\barbaz continues.")
    # \foo 未知无参 → 逐字；\barbaz 完整保留不被切断
    assert reconstruct(res) == DOC % "Text \\foo \\barbaz continues."
    assert not any(w.kind == "letters_cut" for w in res.warnings)


def test_leak_a_empty_spec_no_ws_swallow() -> None:
    r"""空 argspec 的 OPAQUE 宏不吞命令后空白——``\CX\ngate`` 不误报不切断。"""
    body = (
        "\\newcommand{\\CX}{\\ensuremath{\\wedge {\\sf X}}\\xspace}\n"
        "the \\CX\ngate by conjugating"
    )
    res = scan_doc(body)
    assert not any(w.kind == "letters_cut" for w in res.warnings)
    assert reconstruct(res) == DOC % body
    assert any(v == "\\CX" for v in res.ph_map.values())


# ---------------------------------------------------------------- 机制 B


def test_leak_b_comment_in_arg() -> None:
    r"""``\caption{a % comment\n b}``：参数内注释 → ``[[COMMENT]]`` 不留裸 ``%``。"""
    res = scan_doc("\\caption{Cap text % trailing comment\n continues}")
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
    res = scan_doc(body)
    assert "\\begin{multline*}x=1\\end{multline}" in res.ph_map.values()
    assert not any(
        w.kind == "unclosed_env" and "multline" in w.detail for w in res.warnings
    )


def test_leak_c2_unknown_env_in_arg() -> None:
    r"""in_arg 未知 env → ``[[ENV]]`` 进 run——``\\begin{`` 不进 chunk。"""
    res = scan_doc("\\section{Title \\begin{strangeenv}x\\end{strangeenv} end}")
    assert not LEAK_BEGIN.search(blob(res))
    assert any(
        v == "\\begin{strangeenv}x\\end{strangeenv}" for v in res.ph_map.values()
    )


def test_arg_transparent_env_in_arg() -> None:
    r"""in_arg 容器白名单（itemize 等）→ ``[[ENVTAG]]`` + 内部照挖。"""
    res = scan_doc("\\section{T \\begin{itemize}\\item inner text here\\end{itemize}}")
    types = {k.split("_")[0].strip("[]") for k in res.ph_map}
    assert "ENVTAG" in types
    assert "inner text here" in blob(res)


# ---------------------------------------------------------------- 机制 D


def test_leak_d_cond_in_arg() -> None:
    r"""in_arg ``\ifAnonymous{a}{b}`` → ``[[COND]]`` 整调用，不泄 ``\\if``。"""
    res = scan_doc("\\footnote{Text \\ifAnonymous{alice}{bob} end}")
    b = blob(res)
    assert not LEAK_COND.search(b)
    assert any(t.startswith("[[COND") for t in res.ph_map)


def test_if_macro_toplevel_protects_whole_call() -> None:
    r"""非原语 ``if*`` 宏（``\newcommand{\ifX}[2]``）→ 整调用 ``[[CMD]]``。"""
    body = "\\newcommand{\\ifAnon}[2]{#1}\nText \\ifAnon{a}{b} tail"
    res = scan_doc(body)
    assert "\\ifAnon{a}{b}" in res.ph_map.values()
    assert not LEAK_COND.search(
        res.protected_tex.replace("\\newcommand{\\ifAnon}[2]{#1}", "")
    )
    assert not LEAK_COND.search(blob(res))


# ---------------------------------------------------------------- 综合


def test_known_unclosable_dollar_degrades() -> None:
    r"""真不配对 ``$``（corpus 作者笔误）→ literal + ``unpaired_dollar``，不吞后文。"""
    body = "the scalar $dx^T x = x^T dx).\n\nNext paragraph text here."
    res = scan_doc(body)
    assert any(w.kind == "unpaired_dollar" for w in res.warnings)
    assert reconstruct(res) == DOC % body


# ---------------------------------------------------------------- 展开组内再生段（_group_surface）


def test_group_verb_protected() -> None:
    r"""展开组内 ``\verb|raw$|`` → ``[[VERB]]``——逐字内容不泄可译 surface。

    ``_group_surface`` 曾缺 verb 行：``\verb`` 落默认支，``|raw$|`` 逐字
    进 surface（``$`` 还扰 math 判定）。
    """
    body = "\\newcommand{\\vv}{pre \\verb|raw$| post}\nText \\vv tail words here."
    res = scan_doc(body)
    assert any(v == "\\verb|raw$|" for v in res.ph_map.values())
    assert "raw$" not in blob(res)
    assert "pre" in blob(res)
    assert "post" in blob(res)
    assert reconstruct(res) == DOC % body


def test_group_verb_unpaired_falls_literal() -> None:
    r"""组内 ``\verb|x`` 无闭符（EOL 上限）→ 逐字回落，同主流档。"""
    body = "\\newcommand{\\vv}{pre \\verb|raw\npost}\nText \\vv tail words here."
    res = scan_doc(body)
    assert "raw" in blob(res)  # 逐字回落后内容照常进可译面
    assert reconstruct(res) == DOC % body


def test_group_hyperref_text_arg_kept() -> None:
    r"""展开组内 ``\hyperref[l]{text}``：``[label]`` 随命令保护，``{text}``
    留可译 surface——``*ref`` 后缀规则曾把整调用吞进 ``[[REF]]`` 丢 text。"""
    body = (
        "\\newcommand{\\hh}{\\hyperref[sec:x]{translatable link text}}\n"
        "See \\hh now ok."
    )
    res = scan_doc(body)
    assert "translatable link text" in blob(res)
    assert "sec:x" not in blob(res)
    assert reconstruct(res) == DOC % body


def test_group_hyperref_brace_key_form() -> None:
    r"""``\\hyperref{key}{text}`` 双参形：首参（key）保护、次参留 surface。"""
    body = (
        "\\newcommand{\\hh}{\\hyperref{sec:y}{brace key text here}}\nSee \\hh now ok."
    )
    res = scan_doc(body)
    assert "brace key text here" in blob(res)
    assert "sec:y" not in blob(res)
    assert reconstruct(res) == DOC % body


def test_group_href_url_protected() -> None:
    r"""展开组内 ``\href{url}{text}``：``{url}`` → ``[[HREF]]``，``{text}``
    留可译 surface（主版 ``_handle_href`` 同形）。"""
    body = "\\newcommand{\\hh}{\\href{http://x.y/z}{click me link}}\nSee \\hh ok."
    res = scan_doc(body)
    assert any(
        k.startswith("[[HREF_") and v == "{http://x.y/z}" for k, v in res.ph_map.items()
    )
    assert "http://x.y/z" not in blob(res)
    assert "click me link" in blob(res)
    assert reconstruct(res) == DOC % body


def test_group_url_delim_form() -> None:
    r"""展开组内 ``\url|http://..|`` 定界形 → ``[[URL]]``（主版 verbatim 支对价）。"""
    body = "\\newcommand{\\uu}{\\url|http://x.y/|}\nSee \\uu tail text here."
    res = scan_doc(body)
    assert any(
        k.startswith("[[URL_") and v == "\\url|http://x.y/|"
        for k, v in res.ph_map.items()
    )
    assert "http://x.y/" not in blob(res)
    assert reconstruct(res) == DOC % body


# ---------------------------------------------------------------- 间隙剖分
# ``_cover_gap``：``\cs`` 后被吞空格/``%`` 注释这类非 token 字节先剖成
# 字面 run 项，不并入右侧 ph 体——否则 in_arg/mined 子扫的 ident 轨渲染
# 丢空格（``A\foo \cite{x}`` 曾渲成 ``A\foo[[CITE_1]]``，v1 有空格）。


def test_gap_before_cite_in_arg() -> None:
    r"""``\foo \cite`` 的被吞空格：chunk 面 ``\foo [[CITE]]`` 且 ph 体不带前隙。"""
    body = r"\section{A\foo \cite{x} tail}"
    res = scan_doc(body)
    assert "A\\foo [[CITE_1]] tail" in blob(res)
    assert res.ph_map["[[CITE_1]]"] == "\\cite{x}"
    assert reconstruct(res) == DOC % body


def test_gap_comment_before_ph_in_arg() -> None:
    r"""``A%note\n \cite{x}``：注释剖出为 ``[[COMMENT]]``，空格留在渲染面。"""
    body = "\\section{A%note\n \\cite{x} tail}"
    res = scan_doc(body)
    text = blob(res)
    assert "[[COMMENT_" in text
    assert "\n [[CITE_" in text
    assert res.ph_map["[[CITE_1]]"] == "\\cite{x}"
    assert any(v == "%note" for v in res.ph_map.values())
    assert reconstruct(res) == DOC % body


def test_gap_before_envtag_in_arg() -> None:
    r"""``\begin``/``\end`` 前间隙同样剖分——ENVTAG/ENV 体头即 ``\\``。"""
    body = "\\section{A\\foo \\begin{itemize}\\item x\\end{itemize} tail}"
    res = scan_doc(body)
    assert "A\\foo [[ENVTAG_1]][[CMD_2]] x[[ENVTAG_3]] tail" in blob(res)
    assert res.ph_map["[[ENVTAG_1]]"] == "\\begin{itemize}"
    assert res.ph_map["[[ENVTAG_3]]"] == "\\end{itemize}"
    assert reconstruct(res) == DOC % body


def test_gap_before_math_and_verb_in_arg() -> None:
    r"""``$``/``\\(``/``\\verb`` 前被吞空格不丢——渲染面 ``\\foo [[X]]``。"""
    for pat, ph, body in (
        (r"\section{A\foo $x$ tail}", "[[MATH_1]]", "$x$"),
        (r"\section{A\foo \(x\) tail}", "[[MATH_1]]", "\\(x\\)"),
        (r"\section{A\foo \verb|v| tail}", "[[VERB_1]]", "\\verb|v|"),
    ):
        res = scan_doc(pat)
        assert f"A\\foo {ph} tail" in blob(res), pat
        assert res.ph_map[ph] == body
        assert reconstruct(res) == DOC % pat


def test_gap_before_opaque_macro_in_arg() -> None:
    r"""``\mm`` 类宏调用前间隙剖分——MACRO 体 = ``\\mm`` 本体。"""
    body = "\\newcommand{\\mm}{X}\n\\section{A\\foo \\mm tail}"
    res = scan_doc(body)
    assert "A\\foo [[MACRO_1]] tail" in blob(res)
    assert res.ph_map["[[MACRO_1]]"] == "\\mm"
    assert reconstruct(res) == DOC % body


def test_gap_toplevel_ph_body_clean() -> None:
    r"""顶层保护段同样剖分：ph 体首字节 = 构造首字节（``\\``/``$``）。"""
    res = scan_doc("Para \\foo \\cite{x} and \\begin{equation}y\\end{equation} z.")
    assert res.ph_map["[[CITE_1]]"] == "\\cite{x}"
    assert all(not v.startswith((" ", "\n", "%")) for v in res.ph_map.values())
    assert (
        reconstruct(res)
        == DOC % "Para \\foo \\cite{x} and \\begin{equation}y\\end{equation} z."
    )


# ---------------------------------------------------------------- 宏展开洞
# modec-misschar-2026-09-16 归因：数学内容以散文身份到翻译器。


def test_alias_newcommand_env_endpoints_protect_math() -> None:
    r"""``\nc`` 别名定义链：``\be…\en`` → ``[[MATH]]``（0905.0795 miss×100）。

    ``\newcommand{\nc}{\newcommand}`` 体=裸 cs 曾判 opaque → 定义永不
    执行 → ``\be`` 未注册 → equation 环境体整段进 chunk 被译。
    """
    body = (
        "\\newcommand{\\nc}{\\newcommand}\n"
        "\\nc{\\be}{\\begin{equation}}\n"
        "\\nc{\\en}{\\end{equation}}\n"
        "Lead prose sentence with enough letters here.\n\n"
        "\\be \\tau(x)=\\sum_{\\alpha\\in A} \\tau_\\alpha(x) regionword \\en\n\n"
        "Tail prose sentence with enough letters here."
    )
    res = scan_doc(body)
    assert any(t.startswith("[[MATH_") and "\\tau" in v for t, v in res.ph_map.items())
    assert not any(
        "\\tau" in c.content or "regionword" in c.content for c in res.chunks
    )
    assert reconstruct(res) == DOC % body


def test_user_env_math_role_eqnarray_tail() -> None:
    r"""``\newenvironment{subeqnarray}`` before 尾 ``\eqnarray`` → 体成 ``[[MATH]]``。

    1003.0112 miss×180：MATH_ENVS 无名、``_do_newenv`` 一律 transparent
    → 体按散文进 chunk。字面 ``\begin``/宏端点 ``\sba`` 两形都钉。
    """
    body = (
        "\\newenvironment{subeqnarray}\n"
        "  {\\arraycolsep1pt\n"
        "    \\def\\@eqnnum\\stepcounter##1{\\stepcounter{subequation}{\\reset@font\\rm\n"
        "      (\\theequation\\alph{subequation})}}\\eqnarray}\n"
        "  {\\endeqnarray\\stepcounter{equation}}\n"
        "\\newcommand{\\sba}{\\begin{subeqnarray}}\n"
        "\\newcommand{\\sea}{\\end{subeqnarray}}\n"
        "Lead prose sentence with enough letters here.\n\n"
        "\\begin{subeqnarray}\n"
        "\\varphi^U_\\Omega = \\int d\\omega region_{\\Omega, omega} \\varphi_{region}^{U}\n"
        "\\end{subeqnarray}\n\n"
        "\\sba\na^2+b^2=c^2 regionword\n\\sea\n\n"
        "Tail prose sentence with enough letters here."
    )
    res = scan_doc(body)
    env = res.macros.lookup_env("subeqnarray")
    assert env is not None
    assert env.body_role == "math"
    maths = [v for k, v in res.ph_map.items() if k.startswith("[[MATH_")]
    assert any("\\varphi^U_\\Omega" in v for v in maths)
    assert any("\\sba" in v for v in maths)
    assert not any(
        "regionword" in c.content or "\\varphi" in c.content for c in res.chunks
    )
    assert reconstruct(res) == DOC % body


def test_user_env_math_role_in_arg() -> None:
    r"""in_arg 路：用户 math env 嵌 ``\section`` 参数里也整段 ``[[MATH]]``。"""
    body = (
        "\\newenvironment{subeqnarray}{\\eqnarray}{\\endeqnarray}\n"
        "\\section{Lead \\begin{subeqnarray}x_{region}=1\\end{subeqnarray} tail words here}"
    )
    res = scan_doc(body)
    assert any(
        k.startswith("[[MATH_")
        and "\\begin{subeqnarray}" in v
        and "\\end{subeqnarray}" in v
        for k, v in res.ph_map.items()
    )
    assert reconstruct(res) == DOC % body


# ---------------------------------------------------------------- 机制 E：@-cs 展开泄漏


def test_at_cs_body_macro_stays_opaque() -> None:
    r"""``\makeatletter`` 域内 ``\def`` 的替换体含 @-csname → opaque 不展开。

    0707.3950 实证：``\def\section{\@startsection...}`` 展开后 ``\@startsection``
    序列化进正文（@=other），``\@`` 重解析为 ``\spacefactor`` → 不可编译。
    opaque 保调用点原文，编译期由保留的 def 自己展开。
    """
    tex = (
        "\\documentclass{article}\n"
        "\\makeatletter\n"
        "\\def\\section{\\@startsection{section}{1}{\\z@}{-3.5ex plus -1ex minus\n"
        "-.2ex}{2.3ex plus .2ex}{\\large\\bf}}\n"
        "\\makeatother\n"
        "\\begin{document}\n"
        "\\section{Introduction to the topic}\n"
        "Body text with enough words here.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    entry = res.macros.resolve(res.macros.lookup("section"))
    assert getattr(entry, "kind", "") == "opaque"
    # 调用点不展开：@ -cs 不进 chunk、不进 ph 体（preamble def 区段本身合法）
    assert not any(
        "\\@startsection" in c.content or "\\z@" in c.content for c in res.chunks
    )
    assert not any("\\@startsection" in v or "\\z@" in v for v in res.ph_map.values())
    zh = reconstruct(res, {c.id: "引言译文" for c in res.chunks})
    post = zh.split("\\begin{document}", 1)[1]
    assert "\\@startsection" not in post
    assert "\\z@" not in post
    assert "\\section{引言译文}" in post  # 调用点保留 + 标题照常可翻


def test_at_cs_alias_body_stays_opaque() -> None:
    r"""裸 ``\\@foo`` 别名体同判 opaque——``_bare_cs`` 通道不得放行展开。"""
    body = (
        "\\makeatletter\n"
        "\\def\\nc{\\@startsection}\n"
        "\\makeatother\n"
        "Text \\nc{arg} more words in this sentence."
    )
    res = scan_doc(body)
    entry = res.macros.resolve(res.macros.lookup("nc"))
    assert getattr(entry, "kind", "") == "opaque"


def test_non_at_macro_still_expands() -> None:
    r"""对照组：无 @-cs 的含文本宏照常 transparent_expand（防过度 opaque）。"""
    res = scan_doc("\\def\\foo{EXPANDED phrase words}\\foo fills the sentence here.")
    assert any("EXPANDED phrase words" in c.content for c in res.chunks)


def test_at_csname_synth_body_stays_opaque() -> None:
    r"""``\csname a@b\endcsname`` 体：@ 是字符 token、@-cs 展开期才合成——
    第二路径同判 opaque（体扫描看不到 ``\@`` 形 cs token）。"""
    body = (
        "\\makeatletter\n"
        "\\def\\foo{\\csname @startsection\\endcsname}\n"
        "\\makeatother\n"
        "Text \\foo more words in this sentence."
    )
    res = scan_doc(body)
    entry = res.macros.resolve(res.macros.lookup("foo"))
    assert getattr(entry, "kind", "") == "opaque"
    out = reconstruct(res, {c.id: "译文" for c in res.chunks})
    post = out.split("\\begin{document}", 1)[1]
    assert "\\@" not in post


# ---------------------------------------------------------------- 机制 F：in_arg 裸 ``\input`` 文件名


def test_input_bare_name_in_arg_protected() -> None:
    r"""``\caption{see \input foo_bar.tex end}``：裸文件名并入 ``[[CMD]]``——
    zhfile 普查实漏：文件名曾留 arg 文本被译，splice 出 ``\input 这是译文``
    炸 ``I can't find file``。"""
    body = "\\caption{see \\input foo_bar.tex end}"
    res = scan_doc(body)
    assert "see [[CMD_1]] end" in blob(res)
    assert res.ph_map["[[CMD_1]]"] == "\\input foo_bar.tex"
    zh = reconstruct(res, {c.id: c.content.replace("end", "尾") for c in res.chunks})
    assert "\\input foo_bar.tex" in zh
    assert reconstruct(res) == DOC % body


def test_input_bare_name_in_arg_path_charset() -> None:
    r"""FILENAME_CHARS 全谱：``/``、``-``、``_``、``.``、数字连吃到名尾。"""
    res = scan_doc("\\caption{see \\input path/to-file_2.v3.tex end}")
    assert res.ph_map["[[CMD_1]]"] == "\\input path/to-file_2.v3.tex"
    assert "to-file" not in blob(res)


def test_input_braced_in_arg_unchanged() -> None:
    r"""``\input{file}`` in_arg 本就安全：整调用单 CMD，行为不动。"""
    res = scan_doc("\\caption{see \\input{foo_bar.tex} end}")
    assert res.ph_map["[[CMD_1]]"] == "\\input{foo_bar.tex}"
    assert "see [[CMD_1]] end" in blob(res)


def test_input_bare_name_arg_end() -> None:
    r"""文件名在参数尾：``\input f.tex`` 收到组尾，无越界消费。"""
    res = scan_doc("\\caption{see \\input foo_bar.tex}")
    assert res.ph_map["[[CMD_1]]"] == "\\input foo_bar.tex"
    assert "foo_bar" not in blob(res)


def test_input_bare_name_stops_at_group() -> None:
    r"""``\input foo{rest}``：文件名收到 ``{`` 前——组参留 surface 续扫。"""
    res = scan_doc("\\caption{see \\input foo{rest} end}")
    assert res.ph_map["[[CMD_1]]"] == "\\input foo"
    assert "rest" in blob(res)


def test_input_bare_name_stops_at_cs() -> None:
    r"""``\input \myfile`` 动态名：``\\`` 非文件名字符——只吃 ``\input``。"""
    res = scan_doc("\\caption{see \\input \\myfile end}")
    assert res.ph_map["[[CMD_1]]"] == "\\input"


def test_input_bare_name_par_boundary() -> None:
    r"""``\input\n\nfoo``：``eol_par`` 边界停——``foo`` 是段后正文非文件名。"""
    res = scan_doc("\\caption{see \\input\n\nfoo end}")
    assert res.ph_map["[[CMD_1]]"] == "\\input"
    assert "foo end" in blob(res)


def test_input_alone_in_arg() -> None:
    r"""裸 ``\input`` 参数尾零跟随：只护 cs 本体，不过度消费。"""
    res = scan_doc("\\caption{see \\input}")
    assert res.ph_map["[[CMD_1]]"] == "\\input"
    assert "see [[CMD_1]]" in blob(res)


def test_input_bare_name_family_wide() -> None:
    r"""``\include``/``\subfile`` 同族裸名形一并收（INPUT_SCAN_CMDS 全谱）。"""
    res = scan_doc("\\caption{a \\include foo_bar b \\subfile baz-qux c}")
    bodies = list(res.ph_map.values())
    assert "\\include foo_bar" in bodies
    assert "\\subfile baz-qux" in bodies
    assert "foo_bar" not in blob(res)
    assert "baz-qux" not in blob(res)
