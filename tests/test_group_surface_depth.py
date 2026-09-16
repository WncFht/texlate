r"""``_close_group`` 展开组 eol_par 尾段「全或无」发射回归（Option D）。

缺陷（hep-ph/9910403 + hep-ph/0408067 + hep-ph/0501170 同签名——
``\@iiiparbox`` runaway triplet）：``_close_group`` 对 ``_group_surface``
在 ``eol_par`` 切出的 ``segs[1:]`` 逐段 ``_flush_run``——尾段挂空 ident
零宽 span 入下一 run，literal 冲刷（surface 全 ws / ``clean < CHUNK_MIN``）
只渲 ident——``}``/``\end{env}`` 等结构字节整段蒸发：

- ``\renewcommand{\abstract}[1]{...\parbox{\absize}{#1...\par}...}`` 的
  ``\par`` 把 ``}``+``\end{center}`` 切成尾段 → 译文面丢 ``}`` →
  ``\parbox{`` 未闭 → ``File ended while scanning use of \@iiiparbox``。
- ``\newcommand{\wrap}[1]{\begin{center}H\par #1\end{center}}`` →
  ``\end{center}`` 孤儿化丢失。

修复：``segs[1:]`` 不再逐段冲刷——以 ``\n\n`` 前缀 ``_rappend`` 挂进
**同一 run** 一次 flush（``\n\n`` ≈ ``\par`` 语义等价）。免疫面不依赖
结构枚举：任何包住 eol_par 的构造（括号/环境/verbatim/数学界/条件式）
都走同一条「整组同沉浮」路径：

- 合体 < CHUNK_MIN → literal → ``[[EXPAND]]``→调用切片原样（可编译不译），
  空 ident 尾段丢弃面由 ``expand_tail_dropped`` ScanWarning 留痕；
- ≥MIN → chunk 化（必要时 ``_split_bounds`` 切 part，每 part 全量落盘）。
"""

import pytest

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import ScanResult
from texlate.latex.reconstruct import validate_result

ART = "\\documentclass{article}\n%s\\begin{document}\n%s\n\\end{document}\n"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def check_invariants(res: ScanResult, tex: str) -> None:
    """公共断言：恒等重建 + 校验零告警 + pieces 无缝平铺 vtex。"""
    assert reconstruct(res) == tex
    assert validate_result(res) == []
    pos = 0
    for p in res.pieces:
        assert p.span.start == pos
        pos = p.span.end
    assert pos == len(res.vtex)


def translated(res: ScanResult) -> str:
    """透传译文面（chunk content 原样）——暴露 surface 丢字节。"""
    return reconstruct(res, {i: c.content for i, c in enumerate(res.chunks)})


# ------------------------------------------------------------- 结构内 \par


def test_parbox_par_keeps_closing_brace_and_env_end() -> None:
    r"""9910403 形：``\parbox`` 参内 ``\par`` 不再切断 ``}``+``\end{center}``。"""
    tex = ART % (
        (
            "\\renewcommand{\\abstract}[1]{\\begin{center}\\parbox{\\absize}"
            "{#1\\setlength{\\baselineskip}{2.5ex}\\par}\\end{center}}\n"
        ),
        "\\abstract{Alpha beta gamma delta epsilon zeta eta theta.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    envtags = [v for k, v in res.ph_map.items() if k.startswith("[[ENVTAG")]
    assert "\\begin{center}" in envtags
    assert "\\end{center}" in envtags  # 修复前：\end{center} 尾段蒸发
    out = translated(res)
    assert "\\parbox{\\absize}{" in out
    assert "}\\end{center}" in out.replace("\n", "")  # 闭括 + 环境尾齐在


def test_wrap_macro_env_end_not_orphaned() -> None:
    r"""``\wrap`` 形：``\begin{center}…\par…\end{center}`` 环境端点同段。"""
    tex = ART % (
        "\\newcommand{\\wrap}[1]{\\begin{center}H\\par #1\\end{center}}\n",
        "\\wrap{Some wrapped text here.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    envtags = [v for k, v in res.ph_map.items() if k.startswith("[[ENVTAG")]
    assert "\\begin{center}" in envtags
    assert "\\end{center}" in envtags
    [c] = res.chunks  # \begin/\end 与正文同 surface 段——没有孤儿尾段
    assert "H" in c.content
    assert "wrapped" in c.content
    out = translated(res)
    assert "\\begin{center}" in out
    assert "\\end{center}" in out


def test_inbrace_par_survives_as_blankline() -> None:
    r"""``\parbox{a}{x\par y}`` 形：结构内 ``\par`` → ``\n\n`` 段内分隔存活。"""
    tex = ART % (
        "\\def\\pb#1{\\parbox{3cm}{#1\\par tail words}}\n",
        "\\pb{Head words here.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    [c] = res.chunks
    assert "\n\n" in c.content  # eol_par → 段内空行分隔
    assert "{" in c.content  # 花括号成对留段内
    assert "}" in c.content
    out = translated(res)
    assert "\\parbox{3cm}{" in out


def test_bgroup_egroup_par_not_split() -> None:
    r"""``\bgroup…\par…\egroup``：cs 形组原语内 eol_par 同样不丢尾。"""
    tex = ART % (
        "\\def\\bg#1{\\bgroup\\bf B#1\\par\\egroup rest}\n",
        "\\bg{Bold text inside bgroup here.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    [c] = res.chunks
    assert "\\egroup" in c.content  # 修复前：\par 切断 → \egroup 尾段险
    out = translated(res)
    assert "\\bgroup" in out
    assert "\\egroup" in out


def test_unclosed_env_tail_not_dropped() -> None:
    r"""组内 ``\begin`` 无配对 ``\end``：全组合体一段——尾部文字不蒸发。"""
    tex = ART % (
        "\\def\\op#1{\\begin{center}H#1\\par more words\\par even more}\n",
        "\\op{Centered body text here.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    [c] = res.chunks
    assert "more words" in c.content
    assert "even more" in c.content


# ------------------------------------------------------------- 合段语义


def test_depth0_par_merges_same_run() -> None:
    r"""Option D：深度 0 的 ``eol_par`` 也不再分段——整组同一 run 一次冲刷。

    修复前沿 ``\par`` 切开两段（尾段 sub-MIN 有丢字节险）；现在段界变
    ``\n\n`` 段内分隔，前后两半同 chunk。
    """
    tex = ART % (
        "\\def\\two#1{#1\\par Second part with enough words to form a chunk.}\n",
        "\\two{First part words here for the test case.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    [c] = res.chunks  # 同一 run 一次 flush → 单 chunk 含双侧
    assert "First part" in c.content
    assert "Second part" in c.content
    assert "\n\n" in c.content


def test_balanced_brace_then_par_still_merges() -> None:
    r"""``{x}\par y``：``}`` 闭组后 ``\par`` 同样合段（Option D 不看深度）。"""
    tex = ART % (
        "\\def\\bb#1{H{#1}\\par Tail part with enough words to chunk.}\n",
        "\\bb{Inner text body here.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    [c] = res.chunks
    assert "Tail part" in c.content
    assert "{" in c.content


# ------------------------------------------------------------- 告警留痕


def test_expand_tail_dropped_warning_fires() -> None:
    r"""整组合体仍 sub-CHUNK_MIN 时 literal 冲刷丢 surface——必须留痕。"""
    tex = ART % (
        # 组 surface 全 ph/结构字符（clean 剥 ph 后 < CHUNK_MIN）→ literal
        "\\newcommand{\\mt}{\\begin{center}\\par\\end{center}}\n",
        "\\mt\nAfter text.",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert any(w.kind == "expand_tail_dropped" for w in res.warnings)


def test_no_warning_when_tail_survives() -> None:
    r"""正常面：合体 ≥CHUNK_MIN 成 chunk——零 ``expand_tail_dropped``。"""
    tex = ART % (
        "\\def\\pb#1{\\parbox{3cm}{#1\\par tail words}}\n",
        "\\pb{Head words here.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert not any(w.kind == "expand_tail_dropped" for w in res.warnings)
