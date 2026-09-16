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

门控判官是 ``\ArrowBetweenLines``（mathtools ``s o`` 无必参）：未装包时
名字内联、装包后裸名 ``[[CMD]]``——唯一能把 argspec protect 与探针
``[[CMD]]``（罩 ``{..}`` 参）区分开的形状。
"""

import pytest

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import PieceKind, ScanResult
from texlate.latex.reconstruct import validate_result

ART = "\\documentclass{article}\n%s\\begin{document}\n%s\n\\end{document}\n"
BEAMER = "\\documentclass{beamer}\n\\begin{document}\n%s\n\\end{document}\n"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def scan(body: str, preamble: str = "", doc: str = ART) -> ScanResult:
    tex = doc % (preamble, body) if doc is ART else doc % body
    res = parse_tex(tex)
    assert reconstruct(res) == tex
    assert validate_result(res) == []
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
        " Second column text goes on here too.",
    ]


# --------------------------------------------------------------- protect


def test_protect_whole_call_multiline_args() -> None:
    r"""``\contentsline{chapter}{Intro}{1}``（latex2e ``m m m``）签名三参
    全消 → 整调用 ``[[CMD]]``，``Intro`` 不进任何 chunk。"""
    res = scan("Text \\contentsline{chapter}{Intro}{1} more words.")
    assert res.ph_map["[[CMD_1]]"] == "\\contentsline{chapter}{Intro}{1}"
    assert "Intro" not in res.protected_tex


def test_protect_gating_discriminator() -> None:
    r"""门控判官 ``\ArrowBetweenLines``（mathtools ``s o`` 无必参）：
    未装包 → 名字内联；装包 → 裸名 ``[[CMD]]``（探针无参可罩 vs policy
    罩名——同 ph 形状、不同成因）。"""
    ungated = scan("Text \\ArrowBetweenLines more words here.")
    [c] = ungated.chunks
    assert c.content == "Text \\ArrowBetweenLines more words here."
    assert not ungated.ph_map

    gated = scan(
        "Text \\ArrowBetweenLines more words here.", "\\usepackage{mathtools}\n"
    )
    assert gated.ph_map["[[CMD_1]]"] == "\\ArrowBetweenLines"


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


def test_verbatim_policy_pct_arg_degrades() -> None:
    r"""verbatim policy 走签名读参（非 ``\verb`` 式定界读法）：``%`` 进参
    → 注释吃行、组未闭 → 退化裸名 ``[[CMD]]`` + 余文注释。

    已知边角：真实 LaTeX 里 verbatim 角色参数 ``%`` 是字面——分段器在
    Mouth 之后已看不到原字节，无法回捞（详见报告）。"""
    res = scan(
        "Text \\hyperbaseurl{http://x%20y} more words.",
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
    未装 exam 时对照探针整调用。"""
    res = scan(
        "Text \\fillin[First Words][Second Words] end.",
        "\\usepackage{exam}\n",
    )
    fills = [c for c in res.chunks if c.context == "fillin"]
    assert [c.content for c in fills] == ["First Words", "Second Words"]

    ungated = scan("Text \\fillin[First Words][Second Words] end.")
    assert ungated.ph_map["[[CMD_1]]"] == "\\fillin[First Words][Second Words]"
    assert not [c for c in ungated.chunks if c.context == "fillin"]


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
