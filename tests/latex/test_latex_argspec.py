r"""argspec.json 表 + 分段器接线：签名分派 / env 体路由。

数据资产 ``src/texlate/latex/data/argspec.json``（CTAN 签名合成，
生成脚本已退役）。装载走
``tables.argspec_tables()``（``importlib.resources`` + ``@cache``）；
查表 ``argspec_lookup``/``argspec_lookup_env`` 均不门控——名出现
本身即工程级加载证据（per-file pkgs 会漏跨文件导言包），用户
``\newcommand``/``\newenvironment`` 撞名由调用方 reg 先短路。
分段器挂点：``_handle_unknown_cs``（宏表未命中的未知 cs → policy
分派）与 ``_handle_env_begin``（族表不知的 env → body_role 路由）。
"""

from conftest import ART, BEAMER

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import ScanResult
from texlate.latex.tables import (
    argspec_lookup,
    argspec_lookup_env,
    argspec_tables,
)


def scan(body: str, preamble: str = "", doc: str = ART) -> ScanResult:
    return parse_tex(doc % (preamble, body) if doc is ART else doc % body)


def test_loader_tables() -> None:
    r"""``argspec_tables`` 装载 JSON → ``(macros, envs)`` 条目字段齐全。"""
    macros, envs = argspec_tables()
    assert len(macros) > 1000  # noqa: PLR2004 — 全表规模冒烟线
    assert len(envs) > 200  # noqa: PLR2004
    frametitle = macros["frametitle"]
    assert frametitle.package == "beamer"
    assert frametitle.policy == "chunk-arg"
    assert frametitle.signature == "d<> o m"
    assert frametitle.arg_roles == ("skip", "opt-text", "text")
    frame = envs["frame"]
    assert frame.body_role == "text"
    assert frame.arg_roles[-2:] == ("text", "text")


def test_lookup_ungated() -> None:
    r"""宏侧与环境侧查表均不门控：名出现即工程级加载证据。

    per-file ``pkgs`` 查不到跨文件导言包——体文件 ``\\crefrange`` 在
    门控下必假阴。用户 ``\\newcommand``/``\\newenvironment`` 撞名由
    调用方 reg 先短路（主流 ``_handle_unknown_cs`` 仅 ``m is None``
    查表、``_argspec_env`` 先查 ``reg``），到不了表签名。
    """
    assert argspec_lookup("frametitle", set()) is not None
    assert argspec_lookup("frametitle", {"beamer"}) is not None
    assert argspec_lookup("section", set()) is not None
    assert argspec_lookup_env("dcases", set()) is not None
    assert argspec_lookup_env("dcases", {"mathtools"}) is not None
    assert argspec_lookup("pageref", set()) is not None
    assert argspec_lookup("pageref", {"hyperref"}) is not None


def test_ungated_cmd_uses_signature() -> None:
    r"""无 ``\\documentclass{beamer}`` 声明的 ``\\frametitle`` 也按签名分派：

    chunk-arg ``d<> o m`` → ``{text}`` 角色参出 chunk（per-file pkgs
    空 ≠ 包未加载——``\\input`` 拆开的体文件同形）。
    """
    res = scan("Text \\frametitle{My Frame Title} more text here.")
    assert any(
        c.context == "frametitle" and c.content == "My Frame Title" for c in res.chunks
    )


def test_documentclass_activates() -> None:
    r"""``\documentclass{beamer}`` 登记包名 → ``frametitle`` 出 chunk。"""
    res = scan("Text \\frametitle{My Frame Title} more text here.", doc=BEAMER)
    assert any(
        c.context == "frametitle" and c.content == "My Frame Title" for c in res.chunks
    )


def test_usepackage_activates() -> None:
    r"""``\usepackage``（含逗号名单与 ``\\RequirePackage``）同样登记。"""
    body = "See \\texorpdfstring{Plain Words Here}{$x^2$} done."
    res = scan(body, "\\usepackage{hyperref}\n")
    assert any(c.content == "Plain Words Here" for c in res.chunks)
    res2 = scan(
        "Text\n\\begin{dcases}x = 1\\end{dcases}\nmore text here.",
        "\\usepackage{amsmath,mathtools}\n",
    )
    assert any(v == "\\begin{dcases}x = 1\\end{dcases}" for v in res2.ph_map.values())


def test_chunk_arg_opt_text() -> None:
    r"""``opt-text`` 位出 chunk、``skip`` 位随字面段——``s o m`` 位序。"""
    res = scan("Text \\frametitle<1->[Short Cap]{Long Title Here} end.", doc=BEAMER)
    contents = {c.content for c in res.chunks if c.context == "frametitle"}
    assert "Long Title Here" in contents
    assert "Short Cap" in contents  # opt-text 也译（\\section[lof] 同款）
    assert (
        reconstruct(res)
        == BEAMER % "Text \\frametitle<1->[Short Cap]{Long Title Here} end."
    )


def test_chunk_arg_latex2e_always() -> None:
    r"""``multicolumn``（latex2e 恒激活）：``skip,key,text`` 位序 → 末参出 chunk。"""
    res = scan(
        "\\begin{tabular}{ll}\\multicolumn{2}{c}{Span Head Text}\\\\\\end{tabular}"
    )
    assert any(
        c.context == "multicolumn" and c.content == "Span Head Text" for c in res.chunks
    )


def test_key_policy_whole_call() -> None:
    r"""``key`` policy：整调用 ``[[CMD]]``（``addbibresource`` manual 恒激活）。"""
    res = scan("Refs \\addbibresource{main.bib} done text here.")
    assert "\\addbibresource{main.bib}" in res.ph_map.values()
    assert all("main.bib" not in c.content for c in res.chunks)


def test_verbatim_policy_whole_call() -> None:
    r"""``verbatim`` policy（hyperref 门控）：``\\nolinkurl{..}`` 整体进 ph。"""
    res = scan("A \\nolinkurl{http://x/path} b text here.", "\\usepackage{hyperref}\n")
    assert "\\nolinkurl{http://x/path}" in res.ph_map.values()


def test_protect_zero_arg() -> None:
    r"""零参 protect：``\\printbibliography`` 本体 ``[[CMD]]``，后文照译。"""
    res = scan("Text \\printbibliography more text here.")
    assert "\\printbibliography" in res.ph_map.values()
    assert any("more text here." in c.content for c in res.chunks)


def test_env_math_body_gated() -> None:
    r"""``dcases``（mathtools math 体）：装不装 ``\\usepackage`` 行都 ``[[MATH]]``——

    ``pkgs`` 是 per-file 视图，体文件查不到导言区包名仍须按签名路由，
    否则数学体漏成散文被译。
    """
    body = "Text\n\\begin{dcases}x = 1\\end{dcases}\nmore text here."
    bare = scan(body)
    assert bare.ph_map.get("[[MATH_1]]") == "\\begin{dcases}x = 1\\end{dcases}"
    loaded = scan(body, "\\usepackage{mathtools}\n")
    assert loaded.ph_map.get("[[MATH_1]]") == "\\begin{dcases}x = 1\\end{dcases}"


def test_env_text_body_args() -> None:
    r"""``frame``（beamer text 体）：``d<>``/``[t]`` 吃进 begin 行字面，
    ``d{}`` 标题回吐主流进 chunk。"""
    res = scan(
        "\\begin{frame}<+->[t]{My Title Words}\nBody text here.\\end{frame}",
        doc=BEAMER,
    )
    assert "\\begin{frame}<+->[t]" in res.protected_tex
    assert any("{My Title Words}" in c.content for c in res.chunks)


def test_env_restatable_header_args_never_translate() -> None:
    r"""``restatable``（thmtools）：env-name/key 参永不进可译 chunk——

    2105.00111 实证：``\\begin{restatable}{theorem}{main}`` 在体文件
    （无 ``\\usepackage`` 行、per-file pkgs 空）两参曾漏成散文译成
    ``{这是译文}{这是译文}`` → cleveref ``\\cref@resetstack`` 递归炸栈。
    env-name/key 位永不译；装不装声明行行为一致。
    """
    body = (
        "Lead sentence goes here.\n\n"
        "\\begin{restatable}{theorem}{main}\n"
        "\\label{thm:main}Restated body text here.\n"
        "\\end{restatable}\n\n"
        "Tail sentence goes here.\n"
    )
    for preamble in ("", "\\usepackage{thmtools}\n"):
        res = scan(body, preamble)
        joined = "\n".join(c.content for c in res.chunks)
        assert "{theorem}" not in joined
        assert "{main}" not in joined
        assert "\\begin{restatable}{theorem}{main}" in res.vtex
        assert any("Restated body text" in c.content for c in res.chunks)
        tex = ART % (preamble, body)
        assert reconstruct(res) == tex


def test_env_opt_text_title_preserved() -> None:
    r"""F6 语义保持：``theorem[Name]`` 标题非版式 → 回吐进 chunk。"""
    res = scan("\\begin{theorem}[Fermat]Statement words here.\\end{theorem}")
    assert any("[Fermat]" in c.content for c in res.chunks)


def test_env_bibliography_stays_transparent() -> None:
    r"""族表已知 env 不交 argspec：``thebibliography``（数据 body=protect
    但已在 ``ENV_MANDATORY_ARG``）维持透明体——``\\bibitem`` 段照出 chunk
    （@X1-bibitem-lead trap 钉死的产品口径）。"""
    body = (
        "\\begin{thebibliography}{9}"
        "\\bibitem{a} A. Author. Title words here."
        "\\end{thebibliography}"
    )
    res = scan(body)
    assert "\\begin{thebibliography}{9}" in res.protected_tex
    assert any("Title words here." in c.content for c in res.chunks)


def test_unknown_cs_still_probe() -> None:
    r"""表外未知命令维持探针档：``\\foo{a}{b}`` → ``[[CMD]]``。"""
    res = scan("Text \\foo{a}{b} more.")
    assert any(v.startswith("\\foo{a}{b}") for v in res.ph_map.values())


def test_argspec_identity_suite() -> None:
    r"""恒等抽查：argspec 命中 + env 三体，reconstruct 逐字节还原。"""
    cases = [
        ART % ("", "Text \\foo{a}{b} \\printbibliography tail."),
        ART
        % (
            "\\usepackage{hyperref}\n",
            "See \\texorpdfstring{Words}{$x$} \\nolinkurl{http://y} end.",
        ),
        ART
        % (
            "\\usepackage{mathtools}\n",
            (
                "T\n\\begin{dcases}x\\end{dcases}\n"
                "\\begin{theorem}[Tt]Words here.\\end{theorem}\n"
                "\\begin{thebibliography}{9}\\bibitem{a}A\\end{thebibliography}"
            ),
        ),
        BEAMER % "\\begin{frame}<+->[t]{Title W}\\frametitle{T2}b\\end{frame}",
    ]
    for tex in cases:
        res = parse_tex(tex)
        assert reconstruct(res) == tex


def test_body_file_key_args_never_translate() -> None:
    r"""多参 ref 宏的 key 参永不进可译 chunk（宏侧 ``restatable`` 同型）：

    ``\\crefrange{a}{b}``（cleveref ``s m m``，``REF_NAMES`` 内唯一包
    门控多参名）在体文件（per-file pkgs 空、无 ``\\usepackage`` 行）
    门控下 ``_cite_ref_mand`` 只得 1——尾参 ``{b}`` 漏成散文被译 →
    cleveref ``\\cref@resetstack`` 递归炸栈（2105.00111）。``\\joref``
    （``m×5``，manual 恒激活族）同路钉大参目。key 位永不译；装不装
    声明行行为一致。
    """
    body = "See \\crefrange{eq:a}{eq:b} and \\joref{Aauth}{Jour}{Vol}{Pag}{Year} done."
    for preamble in ("", "\\usepackage{cleveref}\n"):
        res = scan(body, preamble)
        joined = "\n".join(c.content for c in res.chunks)
        for key in ("eq:b", "Jour", "Vol", "Pag", "Year"):
            assert key not in joined
        assert "\\crefrange{eq:a}{eq:b}" in res.ph_map.values()
        assert "\\joref{Aauth}{Jour}{Vol}{Pag}{Year}" in res.ph_map.values()
        assert reconstruct(res) == ART % (preamble, body)


def test_user_newcommand_shadow_wins() -> None:
    r"""用户 ``\\newcommand`` 撞名优先于表签名——reg 短路实证钉。

    ``\\frametitle``（beamer chunk-arg ``d<> o m``）：opaque 用户宏
    → ``_handle_opaque_macro`` 按用户 spec 整调用 ``[[MACRO]]``，
    ``{text}`` 角色签名不得抠出 chunk。``\\nolinkurl``（verbatim
    policy）：可展开用户宏 gullet 先行展开——surface 见用户体文本，
    verbatim 签名不得整调用逐字。
    """
    res = scan(
        "Text \\frametitle{Hi There} more words here.",
        "\\newcommand{\\frametitle}[1]{\\textbf{#1}}\n",
    )
    assert all(c.context != "frametitle" for c in res.chunks)
    assert "\\frametitle{Hi There}" in res.ph_map.values()
    res2 = scan(
        "A \\nolinkurl{http://x} b words here.",
        "\\newcommand{\\nolinkurl}[1]{URL:#1}\n",
    )
    assert any("URL:http://x" in c.content for c in res2.chunks)
