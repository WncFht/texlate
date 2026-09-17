r"""comment 族（``DEAD_ENVS``）行锚终结——``_env_stop`` dead 臂的 scan 视图对齐。

comment.sty 排除环境按**行**吞体：``\end{env}`` 须列 0 起、行内独占
（``}`` 后仅空格到行尾/EOF）才终结。mask 视图已按此判死；本文件钉住
三个 scan 视图同判——v2 segmenter（raw find + token 级 ``_find_env_end``/
``_skip_verbatim_env_toks``）、v1 scanner、``flatten_inputs``：

- 行中 ``x\end{comment}`` 不终结（列非 0）；
- ``\end {comment}``/``\end{ comment }`` 断序列不终结；
- ``\end{comment*}`` 不终结 ``\begin{comment}``（异名交叉不算）；
- ``\endcomment`` cs 与 env_end 宏端点不终结（comment.sty 只认字面行）；
- ``\begin{comment}`` 体内不嵌套——首个行锚 ``\end{comment}`` 即终。
"""

from pathlib import Path

import pytest
from conftest import DOC, blob

from texlate.latex import parse_tex, reconstruct
from texlate.latex.api import new_state
from texlate.latex.flatten import flatten_inputs
from texlate.latex.model import ScanResult
from texlate.latex.reconstruct import validate_result
from texlate.latex.scanner import Scanner
from texlate.textutil import dead_end_anchored, dead_env_end


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2 路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def scan_v2(body: str) -> ScanResult:
    tex = DOC % body
    res = parse_tex(tex)
    assert reconstruct(res) == tex
    assert validate_result(res) == []
    return res


def scan_v1(body: str) -> ScanResult:
    res = Scanner(new_state()).scan(DOC % body)
    assert reconstruct(res) == DOC % body
    return res


# ---------------------------------------------------------------- helper 单测


def test_dead_env_end_line_anchor() -> None:
    r"""``dead_env_end`` 行锚判定：列 0 + 行内独占才命中。"""
    assert dead_env_end("x\\end{comment}\n", "comment", 0) == -1  # 行中
    assert dead_env_end("x\n\\end{comment}\n", "comment", 0) == 2  # noqa: PLR2004
    assert dead_env_end("x\n\\end{comment}   \n", "comment", 0) == 2  # noqa: PLR2004 — 尾空格容许
    assert dead_env_end("x\n\\end{comment}", "comment", 0) == 2  # noqa: PLR2004 — EOF 界
    assert dead_env_end("x\n \\end{comment}\n", "comment", 0) == -1  # 行首空格
    assert dead_env_end("x\n\\end {comment}\n", "comment", 0) == -1  # 断序列
    assert dead_env_end("x\n\\end{ comment }\n", "comment", 0) == -1
    assert dead_env_end("x\n\\end{comment} y\n", "comment", 0) == -1  # 行内非独占
    assert dead_env_end("\\end{comment}\n", "comment", 0) == -1  # 文件头无前列换行
    assert dead_env_end("x\n\\end{comment*}\n", "comment", 0) == -1  # 异名不终结
    assert dead_env_end("x\n\\end{comment*}\n", "comment*", 0) == 2  # noqa: PLR2004


def test_dead_end_anchored_span_check() -> None:
    r"""``dead_end_anchored``：``[a,e)`` 逐字节 ``\\end{env}`` + 行锚两侧。"""
    text = "a\n\\end{comment} \nb"
    assert dead_end_anchored(text, "comment", 2, 15)
    assert not dead_end_anchored(text, "comment", 1, 14)  # 段偏移错位
    assert not dead_end_anchored(text, "comment*", 2, 15)  # 名不符
    text2 = "a\n\\end {comment}\nb"
    assert not dead_end_anchored(text2, "comment", 2, 16)  # 断序列字面段不等
    assert not dead_end_anchored("\\end{comment}\n", "comment", 0, 13)  # 文件头


# ---------------------------------------------------------------- v2 主路径


def test_v2_midline_end_does_not_terminate() -> None:
    r"""行中 ``x\end{comment}`` 不终结——mask 视图判死区不再泄译文。"""
    body = (
        "Alpha words here.\n"
        "\\begin{comment}\n"
        "dead line x\\end{comment} still dead words\n"
        "\\end{comment}\n"
        "Beta live words here."
    )
    res = scan_v2(body)
    chunked = blob(res)
    assert "Beta live words here." in chunked
    assert "still dead words" not in chunked
    assert "dead line" not in chunked
    verb = res.ph_map["[[VERB_1]]"]
    assert verb == (
        "\\begin{comment}\ndead line x\\end{comment} still dead words\n\\end{comment}"
    )


def test_v2_midline_end_only_unclosed() -> None:
    r"""全图无行锚 ``\end{comment}`` → ``unclosed_env`` + 体走漏网（salvage
    口径与 verbatim 未闭合同规——体不整体判死，防 typo 端点吞全文）。"""
    res = scan_v2("Alpha words.\n\\begin{comment}\ndead x\\end{comment} tail words.")
    assert any(w.kind == "unclosed_env" for w in res.warnings)


def test_v2_broken_sequence_end() -> None:
    r"""``\end {comment}``（断序列）不终结——``_env_name`` 容空白但行锚不认。"""
    body = (
        "Alpha words here.\n"
        "\\begin{comment}\n"
        "dead body\n"
        "\\end {comment}\n"
        "more dead words\n"
        "\\end{comment}\n"
        "Beta live words here."
    )
    res = scan_v2(body)
    chunked = blob(res)
    assert "Beta live words here." in chunked
    assert "more dead words" not in chunked


def test_v2_star_cross_end() -> None:
    r"""``\\end{comment*}`` 不终结 ``\\begin{comment}``——异名交叉不配对。"""
    body = (
        "Alpha words here.\n"
        "\\begin{comment}\n"
        "\\end{comment*}\n"
        "still dead words\n"
        "\\end{comment}\n"
        "Beta live words here."
    )
    res = scan_v2(body)
    chunked = blob(res)
    assert "Beta live words here." in chunked
    assert "still dead words" not in chunked


def test_v2_no_nesting_begin_inside() -> None:
    r"""``\\begin{comment}`` 体内 ``\\begin{comment}`` 不嵌套——首个行锚
    ``\\end{comment}`` 即终（comment.sty 逐行吞体无栈）。"""
    body = (
        "Alpha words here.\n"
        "\\begin{comment}\n"
        "\\begin{comment}\n"
        "dead words\n"
        "\\end{comment}\n"
        "Beta live words here."
    )
    res = scan_v2(body)
    chunked = blob(res)
    assert "Beta live words here." in chunked


def test_v1_midline_end_does_not_terminate() -> None:
    r"""v1 scanner 同判：行中 ``\\end{comment}`` 不终结。"""
    body = (
        "Alpha words here.\n"
        "\\begin{comment}\n"
        "dead line x\\end{comment} still dead words\n"
        "\\end{comment}\n"
        "Beta live words here."
    )
    res = scan_v1(body)
    chunked = blob(res)
    assert "Beta live words here." in chunked
    assert "still dead words" not in chunked


def test_v1_nested_dead_env_skip_anchored() -> None:
    r"""v1 ``_find_env_end`` 嵌套跳读：``\\begin{frame}`` 体内 ``\\begin{comment}``
    的死区只认行锚 ``\\end{comment}``——行中端点后 ``\\end{frame}`` 仍属死区。"""
    body = (
        "\\begin{frame}\n"
        "frame words\n"
        "\\begin{comment}\n"
        "dead x\\end{comment} still dead \\end{frame}\n"
        "\\end{comment}\n"
        "\\end{frame}\n"
        "Beta live words here."
    )
    res = scan_v1(body)
    chunked = blob(res)
    assert "Beta live words here." in chunked
    assert "still dead" not in chunked


# ---------------------------------------------------------------- flatten 面


def test_flatten_input_inside_dead_region(tmp_path: Path) -> None:
    r"""``\\input`` 落在 comment 死区（行中端点之后）不展开——与 mask 视图一致。"""
    (tmp_path / "sub.tex").write_text("SUBFILE CONTENT HERE", encoding="utf-8")
    tex = (
        "\\begin{comment}\n"
        "dead x\\end{comment} still dead\n"
        "\\input{sub}\n"
        "\\end{comment}\n"
        "\\input{sub}\n"
    )
    out = flatten_inputs(tex, str(tmp_path))
    # 死区内 \input 原样保留；锚定端点后的那次照常展开
    assert out.count("SUBFILE CONTENT HERE") == 1
    assert "\\input{sub}" in out


def test_flatten_unanchored_end_leaves_all_dead(tmp_path: Path) -> None:
    r"""全图无行锚端点：``\\input`` 在体任何位置都不展开（体判死到 EOF）。"""
    (tmp_path / "sub.tex").write_text("SUBFILE CONTENT HERE", encoding="utf-8")
    tex = "\\begin{comment}\ndead x\\end{comment} still dead\n\\input{sub}\n"
    out = flatten_inputs(tex, str(tmp_path))
    assert "SUBFILE CONTENT HERE" not in out
