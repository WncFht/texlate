r"""reconstruct DAG 展开 + validate 的单测（docs/07 §9）。"""

import re

from conftest import DOC, scan_doc

from texlate.latex import reconstruct
from texlate.latex.model import Chunk
from texlate.latex.reconstruct import (
    cjk_glue_fix,
    unicode_math_fix,
    validate_result,
    validate_translation,
)


def test_identity() -> None:
    body = (
        "Para \\cite{a} $x$ \\emph{em} text.\n\\begin{figure}\\caption{C}\\end{figure}"
    )
    res = scan_doc(body)
    assert reconstruct(res) == DOC % body


def test_fake_translation() -> None:
    res = scan_doc("Para one long text here \\cite{a}.")
    trans = {
        c.id: f"译文{i} {''.join(c.placeholders)}" for i, c in enumerate(res.chunks)
    }
    out = reconstruct(res, trans)
    assert "译文0" in out
    assert not re.search(r"\[\[[A-Z_]+_\d+\]\]", out)  # 无占位符残留


def test_dag_nested_ph() -> None:
    r"""三层嵌套：chunk 内含 ``[[ENV]]``，其体内含 ``[[CITE]]``——DAG 递归展开。"""
    body = "\\begin{figure}\\caption{Cap \\cite{x} text}\\end{figure}"
    res = scan_doc(body)
    env_ph = [k for k, v in res.ph_map.items() if v.startswith("\\begin{figure}")]
    assert env_ph
    body_env = res.ph_map[env_ph[0]]
    assert "[[CHUNK_" in body_env or "\\caption" in body_env
    assert reconstruct(res) == DOC % body


def test_validate_translation_contract() -> None:
    res = scan_doc("Text \\cite{a} long text here.")
    ch = next(c for c in res.chunks if c.placeholders)
    keep = "".join(ch.placeholders)
    ok = validate_translation(ch, "译文 " + keep)
    assert ok.ok
    missing = validate_translation(ch, "译文没有占位符")
    assert not missing.ok
    assert missing.missing
    extra = validate_translation(ch, "译文 [[CITE_99]] " + keep)
    assert not extra.ok
    assert extra.extra


def test_validate_translation_multiset() -> None:
    """同一占位符 ×2 掉到 ×1 必须算 missing（Counter 口径，非 list-membership）。"""
    ch = Chunk(id=0, content="x", placeholders=["[[CITE_1]]", "[[CITE_1]]"])
    verdict = validate_translation(ch, "译文 [[CITE_1]]")  # 只留一个
    assert not verdict.ok
    assert verdict.missing == ["[[CITE_1]]"]


def test_validate_result_clean() -> None:
    body = "Para \\cite{a}.\n\\begin{figure}\\caption{C cap}\\end{figure}"
    res = scan_doc(body)
    assert validate_result(res) == []


def test_cjk_glue_only_with_translations() -> None:
    r"""``cjk_glue_fix`` 只在译文路径启用（identity 逐字节）。"""
    assert cjk_glue_fix("\\cmd这是") == "\\cmd 这是"
    res = scan_doc("\\LaTeX 紧跟文字")
    assert reconstruct(res) == DOC % "\\LaTeX 紧跟文字"  # identity 不动


def test_cjk_glue_verbatim_comment_immune() -> None:
    r"""verbatim/comment 体内的 ``\cmd中`` 是字面内容，不插空格。"""
    src = "\\begin{verbatim}\\cmd中\\end{verbatim}\n% \\cmd也\n\\cmd外"
    out = cjk_glue_fix(src)
    assert "\\cmd中" in out  # verbatim 不动
    assert "% \\cmd也" in out  # 注释不动
    assert "\\cmd 外" in out  # 正文修了


def test_unicode_math_fix() -> None:
    r"""译文游离的 ``β``/``∂`` → ``$\beta$``/``$\partial$``（文本字体无字形）。

    e2e-real 实证（1907.10324）：模型把 ``$\beta$`` 改写成字面 ``β`` 落进
    正文，Fandol/lmroman 无此字形 → missing_character 判 partial。
    """
    assert unicode_math_fix("β 衰变与 ∂ 求导") == "$\\beta$ 衰变与 $\\partial$ 求导"
    # 占位符 token 体内是原文回放——绝不动
    assert unicode_math_fix("见 [[MATH_1]] 的 β") == "见 [[MATH_1]] 的 $\\beta$"
    # 已写 \beta / $..$ 的不重复包裹
    assert unicode_math_fix("$x$ 与 \\beta") == "$x$ 与 \\beta"


def test_unicode_math_fix_in_reconstruct() -> None:
    """端到端：translation 值进 reconstruct 前先过 unicode_math_fix。"""
    res = scan_doc("Para one long text here \\cite{a}.")
    ch = res.chunks[0]
    phs = "".join(ch.placeholders)
    out = reconstruct(res, {ch.id: f"β 粒子 {phs}"})
    assert "$\\beta$ 粒子" in out


def test_short_run_ph_survives() -> None:
    r"""短 run（<CHUNK_MIN）里的 ``[[CITE]]`` 不丢——LITERAL piece 带渲染文本。"""
    res = scan_doc("See \\cite{a}.")
    assert "[[CITE_" in res.protected_tex
    assert reconstruct(res) == DOC % "See \\cite{a}."


def test_chunk_split_max() -> None:
    r"""超 ``CHUNK_MAX`` 的 chunk 二次切分：切点不在 ``[[X_n]]`` 中间。"""
    long_text = ("Sentence one with words. " * 200) + "\\cite{a} " + ("tail. " * 100)
    res = scan_doc("\\section{" + long_text + "}")
    total = "".join(c.content for c in res.chunks)
    assert "\\cite{a}" not in total  # cite 应已占位符化
    for c in res.chunks:
        # 切分边界不断占位符：content 里每个 [[X_n]] 都完整匹配
        for m in re.finditer(r"\[\[", c.content):
            assert re.match(r"\[\[[A-Z_]+_\d+\]\]", c.content[m.start() :])


def test_short_arg_par_collapse() -> None:
    r"""短参（caption）译文内的 ``\n\n`` 压单 ``\n``——``\par`` 进非 ``\long``
    移动参（nameref ``\NR@gettitle`` 等）即 runaway（1109.5963 实证）。"""
    res = scan_doc(
        "\\begin{figure}\\caption{The allowed region by $K$ mixing here.}\\end{figure}"
    )
    cap = next(c for c in res.chunks if c.context == "caption")
    out = reconstruct(res, {cap.id: "由\n\n  $K$ 混合允许的区域。"})
    m = re.search(r"\\caption\{([^}]*)\}", out)
    assert m is not None
    assert "\n\n" not in m.group(1)
    assert "由\n  $K$ 混合" in m.group(1)


def test_short_arg_par_collapse_ph_boundary() -> None:
    r"""译文尾 ``\n`` 叠 ph 体前导 ``\n  `` 在参数内合成 ``\n\n`` —— 边界合并
    形态同压（1109.5963 实际机理：``由\n`` + ``[[MATH]]``=``\n  $K..$``）。"""
    res = scan_doc(
        "\\begin{figure}\\caption{The allowed region by $K$ mixing here.}\\end{figure}"
    )
    cap = next(c for c in res.chunks if c.context == "caption")
    math_tok = next(t for t in cap.placeholders if t.startswith("[[MATH_"))
    res.ph_map[math_tok] = "\n  " + res.ph_map[math_tok]  # 复刻当次 ph 前导换行
    out = reconstruct(res, {cap.id: f"由\n{math_tok} 混合允许的区域。"})
    m = re.search(r"\\caption\{([^}]*)\}", out)
    assert m is not None
    assert "\n\n" not in m.group(1)
    assert "由\n  $K$" in m.group(1)


def test_short_arg_fold_preserves_ph_internal_pars() -> None:
    r"""短参折叠不穿透嵌套 ph 体——ph 展开体内部 ``\n\n``（受保环境的真
    段落界）原样保留；只有字面段与字面↔ph 接缝进折叠域（S3）。"""
    res = scan_doc(
        "\\begin{figure}\\caption{The allowed region by $K$ mixing here.}\\end{figure}"
    )
    cap = next(c for c in res.chunks if c.context == "caption")
    math_tok = next(t for t in cap.placeholders if t.startswith("[[MATH_"))
    res.ph_map[math_tok] = "$K$\n\ninner par"  # ph 体内真段落界
    out = reconstruct(res, {cap.id: f"由 {math_tok} 混合。"})
    assert "$K$\n\ninner par" in out


def test_para_chunk_keeps_par_break() -> None:
    r"""正文段（``para``）译文的 ``\n\n`` 是合法段落断——不折叠。"""
    res = scan_doc("Body paragraph with enough words to form a chunk here.")
    para = next(c for c in res.chunks if c.context == "para")
    out = reconstruct(res, {para.id: "第一段文字。\n\n第二段文字。"})
    assert "第一段文字。\n\n第二段文字。" in out


def test_short_arg_untranslated_identity() -> None:
    r"""未译短参保持原文逐字（identity 面不受折叠影响）。"""
    body = (
        "\\begin{figure}\\caption{The allowed region by $K$ mixing here.}\\end{figure}"
    )
    res = scan_doc(body)
    assert reconstruct(res) == DOC % body


# ------------------------------------------------------- bug-B 接缝守卫（_seg_join）


def test_latin_glue_ph_joint() -> None:
    r"""``[[CMD]]→\hline`` 展开尾 + 译文 ``Cd`` 字母头 → 接缝插空格
    （``\hlineCd`` 实形，1003.4522 换行栅栏变体）。"""
    res = scan_doc("Text \\section{See \\hline below} more words here.")
    ch = res.chunks[0]
    out = reconstruct(res, {ch.id: "See [[CMD_1]]Cd words"})
    assert "\\hline Cd" in out
    assert "\\hlineCd" not in out


def test_latin_glue_item_translation_internal() -> None:
    r"""译文体内 ``\itemFSU`` 保险丝：``\\item(?=[A-Z])`` 专款——模型把
    ``\item`` 回显黏大写时拆开（realarm bug-B spec 原样）。"""
    res = scan_doc("Para words here enough text and more.")
    ch = res.chunks[0]
    out = reconstruct(res, {ch.id: "lead \\itemFSU tail words."})
    assert "\\item FSU" in out


def test_latin_glue_no_fp_prefix_macros() -> None:
    r"""保守面：``\itemsep``/``\parindent``/``\par`` 族前缀撞名不动——
    平铺 ``\\item(?=[A-Za-z])`` 会误伤它们，接缝守卫只在段边界生效。"""
    res = scan_doc(
        "\\newcommand{\\fooBar}{x}\nText \\parindent=3pt \\fooBar \\itemsep2pt end."
    )
    out = reconstruct(res, {c.id: "译文" for c in res.chunks})
    assert "\\parindent" in out
    assert "\\itemsep" in out


def test_latin_glue_identity_untouched() -> None:
    r"""identity 路径逐字节——接缝守卫只在有译文时启用。"""
    res = scan_doc("Text \\parindent=3pt \\itemsep2pt end.")
    assert reconstruct(res) == DOC % "Text \\parindent=3pt \\itemsep2pt end."


# ------------------------------------------------- 行首 \cs 归位（_restore_linestarts）

#: ``\obeylines``+``\gdef`` 定界参数样板（2009.11130 ``\GetTitle`` 同构）。
_OBEYLINES_BODY = (
    "\\newbox\\TheTitle{\\obeylines\\gdef\\GetTitle #1\n"
    " \\ShortTitle  #2\n"
    " \\Author      #3\n"
    " \\EndTitle\n"
    " {\\setbox\\TheTitle=\\vbox{x}}\\def\\Title{\\obeylines\\GetTitle}\n"
    "\n"
    " \\Title\n"
    "A Long Enough English Title Line To Chunk Here\n"
    " \\ShortTitle\n"
    "WtF\n"
    " \\Author\n"
    " Firstname Lastname\n"
    " \\EndTitle\n"
)


def test_linestart_cs_restored_obeylines() -> None:
    r"""``\obeylines`` 定界参数族：段切把 `` \Title\n<t>\n \ShortTitle\n<t>``
    折成单行 chunk，译文面把行首 ``\X`` 定界符归位（``\n``≡空格恒等改写，
    ``\obeylines`` 下才兑现结构）——2009.11130 ``\GetTitle`` runaway。"""
    res = scan_doc(_OBEYLINES_BODY)
    assert reconstruct(res) == DOC % _OBEYLINES_BODY  # identity 逐字节
    para = next(c for c in res.chunks if "ShortTitle" in c.content)
    assert "\n" not in para.content  # 段切确实折成单行（机制前提）
    trans = {c.id: "译文" for c in res.chunks}
    trans[para.id] = (
        para.content.replace(
            "A Long Enough English Title Line To Chunk Here", "长标题译文"
        )
        .replace("WtF", "短题")
        .replace("Firstname Lastname", "作者名")
    )
    out = reconstruct(res, trans)
    for cs in ("ShortTitle", "Author", "EndTitle"):
        assert re.search(rf"(?m)^\\{cs}\b", out)  # 定界 cs 回行首 → ^^M\X 复原
    assert "长标题译文\n\\ShortTitle 短题\n\\Author 作者名\n\\EndTitle" in out
    # ``\gdef`` 参数区是字面段——逐字节不动（行首空格保留）
    assert (
        "\\gdef\\GetTitle #1\n \\ShortTitle  #2\n \\Author      #3\n \\EndTitle\n"
        in out
    )


def test_linestart_cs_already_linestart_and_foreign_untouched() -> None:
    r"""保守面：译文里已在行首的 ``\X`` 不再插 ``\n``（空行=``\par`` 语义变）；
    源 span 内非行首的 ``\X`` 不动。"""
    res = scan_doc(_OBEYLINES_BODY)
    para = next(c for c in res.chunks if "ShortTitle" in c.content)
    trans = {c.id: "译文" for c in res.chunks}
    trans[para.id] = (
        para.content.replace(
            "A Long Enough English Title Line To Chunk Here", "长标题译文"
        )
        .replace("  \\ShortTitle", "\n\\ShortTitle")  # 已在行首 → 不得再添 \n
        .replace("WtF", "短题")
        .replace("Firstname Lastname", "作者名 \\vbox 尾")  # \vbox 非行首 → 不动
    )
    out = reconstruct(res, trans)
    assert "\n\n\\ShortTitle" not in out
    assert re.search(r"(?m)^\\ShortTitle\b", out)
    assert "作者名 \\vbox 尾" in out  # 行中 ``\vbox`` 保持行中


def test_linestart_indented_cs_no_orphan_space_line() -> None:
    r"""2507.14695 实案回归: ``\institute`` 内缩进行首 ``\and`` (9 空格
    缩进) 译文原样保留 → 旧 ``(?<=.)`` 从空白串中段起步, ``\n   \and``
    被拆成 ``\n ␣\n\and``——孤儿空格行即空行即 ``\par`` →
    ``Paragraph ended before \institute`` 104 err。``(?<=\S)`` 要求
    空白串前置非空白字符: 行首缩进串逐位置皆 ``\n``/空白在前, 不命中;
    行中 ``text \and`` 仍归位 ``\n\and``。"""
    body = (
        "\\title{Some Title}\n"
        "\\institute{Inst One\n"
        "         \\and\n"
        "         Inst Two}\n"
        "Body paragraph text here long enough to matter."
    )
    res = scan_doc(body)
    assert reconstruct(res) == DOC % body  # identity 不受影响
    para = next(c for c in res.chunks if "\\and" in c.content)
    trans = {c.id: "译文" for c in res.chunks}
    trans[para.id] = (
        "\\institute{Inst One\n"
        "         \\and\n"  # 空格缩进行首 —— 原样保留
        "\t\t\\and\n"  # tab 缩进行首 —— 原样保留
        "         Inst Two   \\and tail\n"  # 行中 \and —— 归位 \n\and
        "}\n正文段落译文。"
    )
    out = reconstruct(res, trans)
    assert "\n \n\\and" not in out  # 孤儿空格行 —— 旧闸产出物
    assert "\n\t\n\\and" not in out  # 孤儿 tab 行同族
    assert "\n         \\and\n" in out  # 空格缩进行首原样
    assert "\n\t\t\\and\n" in out  # tab 缩进行首原样
    assert "Inst Two\n\\and tail" in out  # 行中 \and 仍归位
