r"""argspec.json 表 + 分段器接线：包门控 / policy 分派 / env 体路由 / v1 导出。

数据资产 ``src/texlate/latex/data/argspec.json``（CTAN 签名合成，
``tmp/exp/ctan/build_argspec.py`` 生成）。装载走
``tables.argspec_tables()``（``importlib.resources`` + ``@cache``）；
查表 ``argspec_lookup``/``argspec_lookup_env`` 以
``package ∈ pkgs ∪ ARGSPEC_ALWAYS_PKGS`` 或 ``also_in`` 交集门控。
分段器挂点：``_handle_unknown_cs``（宏表未命中的未知 cs → policy
分派）与 ``_handle_env_begin``（族表不知的 env → body_role 路由）。
"""

from texlate.latex import parse_tex, parse_tex_v1, reconstruct
from texlate.latex.gullet import IfSetter, MacroDef, ScopeMacroTable
from texlate.latex.model import ScanResult
from texlate.latex.tables import (
    ARGSPEC_ALWAYS_PKGS,
    argspec_lookup,
    argspec_lookup_env,
    argspec_tables,
)

ART = "\\documentclass{article}\n%s\\begin{document}\n%s\n\\end{document}\n"
BEAMER = "\\documentclass{beamer}\n\\begin{document}\n%s\n\\end{document}\n"


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


def test_lookup_gating() -> None:
    r"""真实包名须 ``pkgs`` 命中；``ALWAYS`` 族（latex2e 等）无条件激活。"""
    assert argspec_lookup("frametitle", set()) is None
    assert argspec_lookup("frametitle", {"beamer"}) is not None
    assert argspec_lookup("section", set()) is not None  # latex2e 恒激活
    assert argspec_lookup_env("dcases", set()) is None
    assert argspec_lookup_env("dcases", {"mathtools"}) is not None
    # also_in：主包未装、also_in 包已装 → 命中
    assert argspec_lookup("pageref", set()) is None
    assert argspec_lookup("pageref", {"hyperref"}) is not None
    for pkg in ARGSPEC_ALWAYS_PKGS:
        assert not argspec_lookup("frametitle", {pkg})  # 恒激活族不冒充 beamer


def test_gated_cmd_falls_to_probe() -> None:
    r"""包未加载 → 探针档：``\frametitle{T}`` 整调用 ``[[CMD]]`` 无 chunk。"""
    res = scan("Text \\frametitle{My Frame Title} more text here.")
    assert "\\frametitle{My Frame Title}" in res.ph_map.values()
    assert all(c.context != "frametitle" for c in res.chunks)


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
    r"""``dcases``（mathtools）：未装→体当文本流；已装→``[[MATH]]``。"""
    body = "Text\n\\begin{dcases}x = 1\\end{dcases}\nmore text here."
    gated = scan(body)
    assert "\\begin{dcases}" in gated.protected_tex  # 未知 env 透明尾
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


def test_v1_result_macros_converged() -> None:
    r"""``ScanResult.macros`` 单型：v1 平表经 ``export_flat_macros`` 导出。

    ``\\newcommand`` → ``MacroDef``；``\\newif`` 派生 ``\\dbgtrue`` →
    ``IfSetter``（LITERAL 旗标同态）。
    """
    res = parse_tex_v1(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\newcommand{\\xx}[1]{#1!}\n\\newif\\ifdbg\nText \\xx{a}.\n"
        "\\end{document}\n"
    )
    assert isinstance(res.macros, ScopeMacroTable)
    assert isinstance(res.macros.resolve(res.macros.lookup("xx")), MacroDef)
    setter = res.macros.resolve(res.macros.lookup("dbgtrue"))
    assert isinstance(setter, IfSetter)
    assert setter.value is True


def test_argspec_identity_battery() -> None:
    r"""恒等抽查：argspec 命中/门控两态 + env 三体，reconstruct 逐字节还原。"""
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
