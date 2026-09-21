r"""argspec policy 分派黑盒测试——每条 policy 取真实宏端到端钉语义。

配合 ``test_latex_argspec.py``（表装载/门控/冒烟），本文件按 policy 逐条
断言分派行为与族表遮蔽关系：

- ``literal``（``\alpha``/``\Pr``）：名字+参数全内联，不出 ``[[CMD]]``
- ``transparent``：argspec 侧**死路径**——全条目被 TRANSPARENT_NAMES
  族表先截获（``\sout`` 内联仍按族语义断言）
- ``boundary``：argspec 侧**死路径**——全条目被 BOUNDARY_NAMES/
  ``\begin``/``\end`` 先截获（``\columnbreak`` 无包仍按族语义切段）
- ``protect``/``key``/``verbatim``：整调用 ``[[CMD]]``，签名定消费范围
- ``chunk-arg``：text/opt-text 位出独立 chunk，key/skip 位留字面
- env 侧 ``body_role``：verbatim/math/protect/text 四态 + 标题参回吐

签名不吃包门（``argspec_lookup``/``argspec_lookup_env`` 均不门控——名
出现即工程级加载证据，per-file pkgs 查不到跨文件导言包）；``s o``
无必参名的 ``\ArrowBetweenLines`` 装不装包恒裸名 ``[[CMD]]``——policy
罩名与探针 ``[[CMD]]``（罩 ``{..}`` 参）同 ph 形状、不同成因。
"""

import pytest
from conftest import ART, BEAMER, check_invariants

import texlate.latex.tables as tables_mod
from texlate.latex import parse_tex
from texlate.latex.model import ArgspecEntry, PieceKind, ScanResult
from texlate.latex.tables import (
    ACCENT_CHARS,
    BOUNDARY_NAMES,
    CHUNK_ARG_NAMES,
    CITE_NAMES,
    COND_RX,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    INPUT_SCAN_CMDS,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    REF_NAMES,
    TRANSPARENT_NAMES,
    argspec_tables,
)


def scan(body: str, preamble: str = "", doc: str = ART) -> ScanResult:
    tex = doc % (preamble, body) if doc is ART else doc % body
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


# ---------------------------------------------------------------- literal


def test_literal_policy_flows_inline() -> None:
    r"""``literal``（``\alpha`` latex2e / ``\Pr`` latex2e）：名字与 ``{x}``
    参数全内联进 chunk content，ph_map 零签发。"""
    res = scan("Text \\alpha\\Pr{x} more words here.")
    [c] = res.chunks
    assert c.content == "Text \\alpha\\Pr{x} more words here."
    assert not res.ph_map


def test_literal_contrast_unknown_cs_probe() -> None:
    r"""对照：表外 ``\foo{x}`` → 探针档 ``[[CMD]]``——literal 名单的意义
    恰是**不**罩占位。"""
    res = scan("Text \\foo{x} more words here.")
    assert res.ph_map["[[CMD_1]]"] == "\\foo{x}"


# ------------------------------------------------------------ transparent


def test_transparent_policy_shadowed_by_family() -> None:
    r"""argspec ``transparent`` 全 6 条（hbox/hl/noindent/sout/uline/uwave）
    ∈ TRANSPARENT_NAMES——族表先行：名字内联、``{..}`` 参数回吐 run。"""
    res = scan("Text \\sout{struck words} more here.")
    [c] = res.chunks
    assert c.content == "Text \\sout{struck words} more here."
    assert not res.ph_map


def test_transparent_noindent_inline() -> None:
    r"""``\noindent`` 同款：cs 名内联进 chunk 首，无占位。"""
    res = scan("\\noindent Text after noindent more words here.")
    [c] = res.chunks
    assert c.content == "\\noindent Text after noindent more words here."


# -------------------------------------------------------------- boundary


def test_boundary_columnbreak_via_family() -> None:
    r"""``\columnbreak``（argspec boundary/multicol）∈ BOUNDARY_NAMES——
    无包也切段：冲 run + 自身 LITERAL piece + 后段新 chunk。"""
    res = scan(
        "First column text goes on here with enough words."
        "\\columnbreak Second column text goes on here too."
    )
    [lit] = [p for p in res.pieces if p.text == "\\columnbreak"]
    assert lit.kind is PieceKind.LITERAL
    assert [c.content for c in res.chunks] == [
        "First column text goes on here with enough words.",
        "Second column text goes on here too.",
    ]


# --------------------------------------------------------------- protect


def test_protect_whole_call_multiline_args() -> None:
    r"""``\contentsline{chapter}{Intro}{1}``（latex2e ``m m m``）签名三参
    全消 → 整调用 ``[[CMD]]``，``Intro`` 不进任何 chunk。"""
    res = scan("Text \\contentsline{chapter}{Intro}{1} more words.")
    assert res.ph_map["[[CMD_1]]"] == "\\contentsline{chapter}{Intro}{1}"
    assert "Intro" not in res.protected_tex


def test_protect_signature_ignores_pkgs() -> None:
    r"""``\ArrowBetweenLines``（mathtools ``s o`` 无必参）：签名不吃包门——
    装不装 ``\usepackage`` 裸名恒 ``[[CMD]]``（policy 罩名 vs 探针罩
    ``{..}`` 参——同 ph 形状、不同成因；per-file pkgs 门控下必假阴）。"""
    for preamble in ("", "\\usepackage{mathtools}\n"):
        res = scan("Text \\ArrowBetweenLines more words here.", preamble)
        assert res.ph_map["[[CMD_1]]"] == "\\ArrowBetweenLines"


def test_protect_signature_consumes_star_opt() -> None:
    r"""``s o`` 签名实消费：``\ArrowBetweenLines*[x]`` → ``[[CMD]]`` 罩到
    ``[x]`` 止。"""
    res = scan(
        "Text \\ArrowBetweenLines*[x] more words here.",
        "\\usepackage{mathtools}\n",
    )
    assert res.ph_map["[[CMD_1]]"] == "\\ArrowBetweenLines*[x]"


def test_protect_t_spec_tokens() -> None:
    r"""``t`` 签名项：``\onslide+<2->{hidden}``（beamer ``t+ t* d<> d{}``）
    四段全消 → 整调用 ``[[CMD]]``。"""
    res = scan("Text \\onslide+<2->{hidden words} more.", doc=BEAMER)
    assert res.ph_map["[[CMD_1]]"] == "\\onslide+<2->{hidden words}"


# ------------------------------------------------------------------- key


def test_key_policy_latex2e() -> None:
    r"""``\Alph{page}``（latex2e ``m`` key）：整调用 ``[[CMD]]``——形状同
    protect，区分在 arg_roles。"""
    res = scan("Text \\Alph{page} more words here.")
    assert res.ph_map["[[CMD_1]]"] == "\\Alph{page}"


def test_key_policy_gated_delim_specs() -> None:
    r"""``\againframe[opt]{label}``（beamer ``d<> o o m`` key）：delim/opt/
    mand 全消 → 整调用 ``[[CMD]]``。"""
    res = scan("Text \\againframe[opt]{label} more.", doc=BEAMER)
    assert res.ph_map["[[CMD_1]]"] == "\\againframe[opt]{label}"


# --------------------------------------------------------------- verbatim


def test_verbatim_policy_whole_call() -> None:
    r"""``\hyperbaseurl{http://x}``（hyperref ``m`` verbatim）：整调用
    ``[[CMD]]``——URL 不进 chunk。"""
    res = scan(
        "Text \\hyperbaseurl{http://x} more words here.",
        "\\usepackage{hyperref}\n",
    )
    [c] = res.chunks
    assert c.placeholders == ["[[CMD_1]]"]
    assert res.ph_map["[[CMD_1]]"] == "\\hyperbaseurl{http://x}"
    assert "http" not in c.content


def test_verbatim_policy_pct_arg_preserved() -> None:
    r"""verbatim policy 走逐字读参（``\url``/``\path`` 同款字节级配对）：
    ``%`` 在参数里是字面——整调用 ``[[CMD]]`` 含 ``%20``，不截不断。

    修复前退化形态：``%`` 被 Mouth 当注释吃掉 → 组未闭 → 裸名
    ``[[CMD]]`` + ``http://x`` 泄漏进 chunk。"""
    res = scan(
        "Text \\hyperbaseurl{http://x%20y} more words here.",
        "\\usepackage{hyperref}\n",
    )
    [c] = res.chunks
    assert c.placeholders == ["[[CMD_1]]"]
    assert res.ph_map["[[CMD_1]]"] == "\\hyperbaseurl{http://x%20y}"
    assert c.content == "Text [[CMD_1]] more words here."


def test_verbatim_policy_delim_form() -> None:
    r"""verbatim policy 认 ``\cmd|x|`` 定界形（``_protect_cs(verbatim=True)``
    首 token 定界符规则——ctan-argspec 的 policy 语义即定界扫描）。"""
    res = scan(
        "Text \\nolinkurl|a%20b| more words here.",
        "\\usepackage{hyperref}\n",
    )
    assert res.ph_map["[[CMD_1]]"] == "\\nolinkurl|a%20b|"


def test_verbatim_policy_in_arg() -> None:
    r"""in_arg 内 verbatim policy：``\section{.. \hyperbaseurl{u/x} ..}``
    → ``[[CMD]]`` 嵌进 chunk content。"""
    res = scan(
        "Text \\section{See \\hyperbaseurl{u/x} rest of title} tail.",
        "\\usepackage{hyperref}\n",
    )
    [c] = res.chunks
    assert c.content == "See [[CMD_1]] rest of title"
    assert res.ph_map["[[CMD_1]]"] == "\\hyperbaseurl{u/x}"


def test_verbatim_policy_pct_inside_unclosed_group() -> None:
    r"""``%`` 吞掉外层组闭括号时（``\section{..\hyperbaseurl{u%20}..}``——
    token 层 ``%`` 按 TeX 规则本就是注释）：verbatim 字节级配对仍罩住
    整调用 ``[[CMD]]`` 含 ``%``，被吞字节经 gap 覆盖回吐字面。"""
    res = scan(
        "Text \\section{See \\hyperbaseurl{u%20} rest of title} tail.",
        "\\usepackage{hyperref}\n",
    )
    assert res.ph_map["[[CMD_1]]"] == "\\hyperbaseurl{u%20}"
    assert "rest of title" in res.protected_tex


def test_verbatim_policy_unclosed_falls_back() -> None:
    r"""verbatim 参未闭（组不配）→ 裸名 ``[[CMD]]``，后续字节主流重扫。"""
    res = scan(
        "Text \\hyperbaseurl{http://x more words.",
        "\\usepackage{hyperref}\n",
    )
    assert res.ph_map["[[CMD_1]]"] == "\\hyperbaseurl"


# -------------------------------------------------------------- chunk-arg


def test_chunk_arg_text_role() -> None:
    r"""``text`` 位出独立 chunk：``\alert{..}``（manual 恒激活 ``m``）。"""
    res = scan("Text \\alert{Alert words here} end.")
    [c] = [c for c in res.chunks if c.context == "alert"]
    assert c.content == "Alert words here"


def test_chunk_arg_opt_text_role() -> None:
    r"""``opt-text`` 位出 chunk、方括号留字面：``\CorrectChoice[..]``
    （manual ``o ``）。"""
    res = scan("Text \\CorrectChoice[Opt Words Here] end.")
    [c] = [c for c in res.chunks if c.context == "CorrectChoice"]
    assert c.content == "Opt Words Here"
    assert "\\CorrectChoice[" in res.protected_tex


def test_chunk_arg_multiple_opt_text() -> None:
    r"""``\fillin[a][b]``（exam ``o o`` opt-text×2）→ 两独立 chunk；
    装不装 ``\usepackage{exam}`` 行为一致（签名不吃包门）。"""
    for preamble in ("", "\\usepackage{exam}\n"):
        res = scan("Text \\fillin[First Words][Second Words] end.", preamble)
        fills = [c for c in res.chunks if c.context == "fillin"]
        assert [c.content for c in fills] == ["First Words", "Second Words"]


def test_chunk_arg_key_stays_literal() -> None:
    r"""``\hyperlink{sec:k}{text}``（hyperref ``m m`` key+text）：key 位
    留 protected_tex 字面，text 位独立成段。"""
    res = scan(
        "Text \\hyperlink{sec:intro}{Jump to section} end.",
        "\\usepackage{hyperref}\n",
    )
    [c] = [c for c in res.chunks if c.context == "hyperlink"]
    assert c.content == "Jump to section"
    assert "\\hyperlink{sec:intro}{" in res.protected_tex


def test_chunk_arg_hyperref_bracket_label() -> None:
    r"""``\hyperref[label]{text}``（hyperref ``m m`` key+text）：``m`` 位
    兼收 ``[`` 组——文档形 key 留字面、text 出 chunk；路19 前须在分派
    row7 把 ``hyperref`` 从 ``*ref`` 后缀规则放出（mand=1 会吞 text）。"""
    res = scan(
        "Text \\hyperref[sec:x]{Ref Words Here} end.",
        "\\usepackage{hyperref}\n",
    )
    [c] = [c for c in res.chunks if c.context == "hyperref"]
    assert c.content == "Ref Words Here"
    assert "\\hyperref[sec:x]{[[CHUNK_0]]}" in res.protected_tex


def test_chunk_arg_beamer_subtitle() -> None:
    r"""``\framesubtitle{..}``（beamer ``d<> m``）：``m`` 位出 chunk。"""
    res = scan("Text \\framesubtitle{Sub Words Here} end.", doc=BEAMER)
    [c] = [c for c in res.chunks if c.context == "framesubtitle"]
    assert c.content == "Sub Words Here"


# ------------------------------------------------------------- env 侧路由


def test_env_body_role_verbatim() -> None:
    r"""env ``body_role=verbatim``（``verbatimcode`` ALWAYS pkg）：整环境
    独立 PROTECTED piece；体内 ``%``/伪 ``\end{document}`` 不解释。"""
    res = scan(
        "Text\n\\begin{verbatimcode}a % b \\end{document}\n"
        "\\end{verbatimcode}\nmore words here."
    )
    assert res.ph_map["[[VERB_1]]"] == (
        "\\begin{verbatimcode}a % b \\end{document}\n\\end{verbatimcode}"
    )
    assert PieceKind.PROTECTED in [p.kind for p in res.pieces]


def test_env_body_role_math() -> None:
    r"""``mathpar``（ALWAYS math env）→ ``[[MATH]]`` 罩整环境进 run。"""
    res = scan("Text\n\\begin{mathpar}x = 1\\end{mathpar}\nmore words here.")
    assert res.ph_map["[[MATH_1]]"] == "\\begin{mathpar}x = 1\\end{mathpar}"


def test_env_body_role_protect_mines_caption() -> None:
    r"""``prooftree``（ALWAYS protect env）→ ``[[ENV]]`` 整段；体内
    ``\infer`` 出 ``[[CMD]]``、``\caption`` 参数挖成 chunk env=prooftree
    ——保护环境内的 mined subscan。"""
    res = scan(
        "Text\n\\begin{prooftree}\\infer{B}{A}\\caption{Cap words here}"
        "\\end{prooftree}\nend."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\infer{B}{A}"
    assert res.ph_map["[[ENV_2]]"] == (
        "\\begin{prooftree}[[CMD_1]]\\caption{[[CHUNK_0]]}\\end{prooftree}"
    )
    [cap] = res.chunks
    assert cap.context == "caption"
    assert cap.env == "prooftree"
    assert cap.content == "Cap words here"


def test_env_body_role_text_title_args() -> None:
    r"""``block``/``alertblock``（beamer text env）：``d<>`` 版式参吞进
    begin 行字面、``d{}`` 标题回吐与体同进 chunk env=block。"""
    res = scan(
        "Text\n\\begin{block}{Block Title Words}Body text here.\\end{block}\nend.",
        doc=BEAMER,
    )
    [c] = [c for c in res.chunks if c.env == "block"]
    assert c.content == "{Block Title Words}Body text here."

    res2 = scan(
        "Text\n\\begin{alertblock}<+->{Alert Title Words}Body text here."
        "\\end{alertblock}\nend.",
        doc=BEAMER,
    )
    assert "\\begin{alertblock}<+->" in res2.protected_tex
    [c2] = [c for c in res2.chunks if c.env == "alertblock"]
    assert c2.content == "{Alert Title Words}Body text here."


def test_env_theorem_opt_title_preserved() -> None:
    r"""``theorem[Fermat]``（mathtools text env ``o``）：装包后走 argspec
    路由——``[Name]`` 非版式参回吐进 chunk，env 字段记 theorem。"""
    res = scan(
        "Text\n\\begin{theorem}[Fermat]Statement words here.\\end{theorem}\nend.",
        "\\usepackage{mathtools}\n",
    )
    [c] = [c for c in res.chunks if c.env == "theorem"]
    assert c.content == "[Fermat]Statement words here."


# ------------------------------------------------- 死路径（shadow invariant）


def test_transparent_boundary_all_family_shadowed() -> None:
    r"""遮蔽不变式：argspec ``transparent``/``boundary`` 的每条 macro 必须
    被 ``_dispatch`` 前段行（verb/begin/end/cite/ref/protect/href/input/
    chunk-arg/protect-block/transparent/boundary/cond/literal）截获——
    否则 ``_handle_argspec_cs`` 里"语义正确但未经族表校验"的分支会活过来。

    今天 6/6 transparent ∈ TRANSPARENT_NAMES、45/45 boundary ∈
    BOUNDARY_NAMES（或 begin/end）；表或族漂移引入未遮蔽条目时此测试响。"""
    macros, _envs = argspec_tables()
    row_sets = (
        TRANSPARENT_NAMES
        | BOUNDARY_NAMES
        | PROTECT_NAMES
        | CHUNK_ARG_NAMES
        | PROTECT_BLOCK_NAMES
        | CITE_NAMES
        | REF_NAMES
        | INPUT_SCAN_CMDS
        | INLINE_LITERAL_CMDS
        | FONT_SWITCHES
        | {"verb", "verb*", "lstinline", "begin", "end", "href", "endinput"}
    )
    offenders = [
        (name, e.package, e.policy)
        for name, e in sorted(macros.items())
        if e.policy in ("transparent", "boundary")
        and name not in row_sets
        and not name.startswith("cite")
        and not name.endswith("ref")
        and not COND_RX.match(name)
        and not (len(name) == 1 and (name in ACCENT_CHARS or not name.isalpha()))
    ]
    assert not offenders


def test_argspec_dead_path_reach_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""``transparent``/``boundary`` 分支今日不可达；一旦漂移使其可达，
    记 ``argspec_shadowed`` 告警且语义照旧——用假条目强制走通验证。"""
    real = tables_mod.argspec_lookup

    def fake_lookup(name: str, pkgs: set[str]) -> ArgspecEntry | None:
        if name == "zztrans":
            return ArgspecEntry(
                name="zztrans",
                package="zzz",
                signature="m",
                arg_roles=("key",),
                policy="transparent",
            )
        if name == "zzbreak":
            return ArgspecEntry(name="zzbreak", package="zzz", policy="boundary")
        return real(name, pkgs)

    monkeypatch.setattr(tables_mod, "argspec_lookup", fake_lookup)

    res = scan("Text \\zztrans{kk} more words here.")
    assert any(
        w.kind == "argspec_shadowed" and w.detail == "zztrans" for w in res.warnings
    )
    [c] = res.chunks
    assert c.content == "Text \\zztrans{kk} more words here."

    res2 = scan(
        "First column text goes on here with enough words."
        "\\zzbreak Second column text goes on here too."
    )
    assert any(
        w.kind == "argspec_shadowed" and w.detail == "zzbreak" for w in res2.warnings
    )
    [lit] = [p for p in res2.pieces if p.text == "\\zzbreak"]
    assert lit.kind is PieceKind.LITERAL
    assert [c.content for c in res2.chunks] == [
        "First column text goes on here with enough words.",
        "Second column text goes on here too.",
    ]
