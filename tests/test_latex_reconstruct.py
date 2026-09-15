r"""reconstruct DAG 展开 + validate 的单测（docs/07 §9）。"""

import re

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import Chunk, ScanResult
from texlate.latex.reconstruct import (
    cjk_glue_fix,
    unicode_math_fix,
    validate_result,
    validate_translation,
)

DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


def scan(body: str) -> ScanResult:
    return parse_tex(DOC % body)


def test_identity() -> None:
    body = (
        "Para \\cite{a} $x$ \\emph{em} text.\n\\begin{figure}\\caption{C}\\end{figure}"
    )
    res = scan(body)
    assert reconstruct(res) == DOC % body


def test_fake_translation() -> None:
    res = scan("Para one long text here \\cite{a}.")
    trans = {
        c.id: f"译文{i} {''.join(c.placeholders)}" for i, c in enumerate(res.chunks)
    }
    out = reconstruct(res, trans)
    assert "译文0" in out
    assert not re.search(r"\[\[[A-Z_]+_\d+\]\]", out)  # 无占位符残留


def test_dag_nested_ph() -> None:
    r"""三层嵌套：chunk 内含 ``[[ENV]]``，其体内含 ``[[CITE]]``——DAG 递归展开。"""
    body = "\\begin{figure}\\caption{Cap \\cite{x} text}\\end{figure}"
    res = scan(body)
    env_ph = [k for k, v in res.ph_map.items() if v.startswith("\\begin{figure}")]
    assert env_ph
    body_env = res.ph_map[env_ph[0]]
    assert "[[CHUNK_" in body_env or "\\caption" in body_env
    assert reconstruct(res) == DOC % body


def test_validate_translation_contract() -> None:
    res = scan("Text \\cite{a} long text here.")
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
    res = scan(body)
    assert validate_result(res) == []


def test_cjk_glue_only_with_translations() -> None:
    r"""``cjk_glue_fix`` 只在译文路径启用（identity 逐字节）。"""
    assert cjk_glue_fix("\\cmd这是") == "\\cmd 这是"
    res = scan("\\LaTeX 紧跟文字")
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
    res = scan("Para one long text here \\cite{a}.")
    ch = res.chunks[0]
    phs = "".join(ch.placeholders)
    out = reconstruct(res, {ch.id: f"β 粒子 {phs}"})
    assert "$\\beta$ 粒子" in out


def test_short_run_ph_survives() -> None:
    r"""短 run（<CHUNK_MIN）里的 ``[[CITE]]`` 不丢——LITERAL piece 带渲染文本。"""
    res = scan("See \\cite{a}.")
    assert "[[CITE_" in res.protected_tex
    assert reconstruct(res) == DOC % "See \\cite{a}."


def test_chunk_split_max() -> None:
    r"""超 ``CHUNK_MAX`` 的 chunk 二次切分：切点不在 ``[[X_n]]`` 中间。"""
    long_text = ("Sentence one with words. " * 200) + "\\cite{a} " + ("tail. " * 100)
    res = scan("\\section{" + long_text + "}")
    total = "".join(c.content for c in res.chunks)
    assert "\\cite{a}" not in total  # cite 应已占位符化
    for c in res.chunks:
        # 切分边界不断占位符：content 里每个 [[X_n]] 都完整匹配
        for m in re.finditer(r"\[\[", c.content):
            assert re.match(r"\[\[[A-Z_]+_\d+\]\]", c.content[m.start() :])
