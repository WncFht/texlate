r"""v1 字节 scanner 臂（``parse_tex_v1``/``parse_file_v1``）性质 fuzz。

并存期基准对照臂（``TEXLATE_NO_EXPAND=1`` 分派目标）此前只有
``test_v1arm_audit`` 单点回归钉——本文件补状态机性质面。直调 v1 入口
（不走 env 分派）保测试稳定；分派面由 ``TestDispatch`` 单独钉。

不变量清单（``Scanner.scan`` 铁律：单遍逐字符、绝不回退、绝不抛异常）：

- 铁规：任意 ``str`` 入参 ``parse_tex_v1`` 绝不抛异常——含敌意 soup 拼装、
  突变文档、未闭/交叉嵌套 group/env、展开炸弹（``BUDGET``/``MAX_GEN``
  回压兜死）、无 DOC 壳裸串（preamble 判定缺席面）。
- pieces 平铺：``res.pieces`` 无缝覆盖 ``[0, len(tex))``——v1 坐标系即
  输入 tex 本身（``res.vtex`` 恒空；虚拟展开文本面是 v2 专有字段）。
- identity：``reconstruct(res) == tex`` 逐字节还原（corpus_v3 1955/1955
  strict 同口径，fuzz 面上零违约实证 2026-09-18）。
- ``validate_result(res) == []``：无 dangling_ph/orphan_chunk/pieces_gap。
- ``protected_tex == "".join(p.text for p in pieces)``——构造级一致性钉。
- ``chunk.id == chunks 下标``——``[[CHUNK_id]]`` 寻址对齐约束。
- warning/input 位置界内：``w.pos``/``inputs`` 偏移 ∈ ``[0, len(tex)]``。
- 确定性：同输入连跑投影恒等（protected_tex/chunk contents/ph_map）。
- 重入：``parse_tex_v1(res.protected_tex)`` 仍 identity——``[[X_n]]`` 字面
  走 ``ph_reserved`` 豁免面不破重建。

观察钉（pin 当前契约，非缺陷声明）：

- ``parse_tex_v1(非 str)`` → ``TypeError``（``PH_RX.findall`` 先触）——与
  v2 ``parse_tex(None)`` 容忍空结果不对称：env 分派后两臂入参契约分歧。
- ``parse_file_v1`` 不存在路径 → ``OSError(ENXIO)``（api.py 明文契约）；
  ``\\input{miss}``/自环 → ``missing_input`` warning 不抛。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from _fuzzkit import (
    assert_deterministic,
    fuzz_rng,
    short,
    soup_join,
    soup_pick,
)
from conftest import DOC

from texlate.latex import parse_tex, parse_tex_v1, reconstruct
from texlate.latex.api import parse_file_v1
from texlate.latex.reconstruct import validate_result

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.latex.model import ScanResult

# ---------------------------------------------------------------- 常量与 soup

_FUZZ_ITERS = 600
_FUZZ_ITERS_MED = 300
_SEED_SOUP = 2026091801
_SEED_MUTATE = 2026091802
_SEED_GROUP = 2026091803

#: 敌意 token 汤——与 ``test_fuzz_segmenter`` 同面（两臂共享敌意面），另加
#: v1 分派表触形：``\newif``/``\if*`` 两档、``\endinput``、verbatim/filecontents
#: 环境、PROTECT_BLOCK（``\author``）、verbatim 括号参（``\url``/``\path``）、
#: ``\href`` 双参、``\bibliography``、定界参 ``\def``。
_TEX_SOUP = [
    "a",
    "Z",
    " ",
    "  ",
    "\n",
    "\n\n",
    "\t",
    "~",
    "^",
    "_x",
    "&",
    "#1",
    "%",
    "% trailing comment\n",
    "{",
    "}",
    "{a}",
    "{{}}",
    "$x$",
    "$",
    "$$y$$",
    "\\",
    "\\alpha",
    "\\textbf{a}",
    "\\textbf",
    "\\emph",
    "\\begin{eq}",
    "\\end{eq}",
    "\\begin{itemize}",
    "\\end{itemize}",
    "\\item ",
    "\\[",
    "\\]",
    "\\(",
    "\\)",
    "\\def\\m{x}",
    "\\m",
    "\\def\\a#1{#1}",
    "\\a{z}",
    "\\def\\d<#1>{d#1}",
    "\\newcommand{\\v}[1]{#1}",
    "\\v{y}",
    "\\def\\self{\\self}",
    "\\self",
    "\\input{a}",
    "\\include{b}",
    "\\usepackage{c}",
    "\\verb|x|",
    "\\verb",
    "\\verb*x",
    "\\lstinline|x|",
    "\\lstinline[language=C]{x}",
    "\\@gobble{x}",
    "\\csname a\\endcsname",
    "\\makeatletter",
    "\\makeatother",
    "0",
    "9",
    "中",
    "文",
    "é",
    "\\'e",
    "--",
    "---",
    "``",
    "''",
    "[",
    "]",
    "<",
    ">",
    "|",
    "\\|",
    "\\ ",
    "\\,",
    "\\;",
    "\\!",
    "\\-",
    "\\_",
    "\\%",
    "\\&",
    "\\#",
    "\\hline",
    "\\\\",
    "=",
    "+",
    "*",
    "/",
    "\\section{T}",
    "\\section*{T}",
    "\\section[opt]{T}",
    "\\label{l}",
    "\\ref{l}",
    "\\cite{c}",
    "\\cite[p.1]{c}",
    "\\footnote{f}",
    "\\author{au}",
    "\\title{ti}",
    "\\url{u}",
    "\\url|u|",
    "\\path{p}",
    "\\href{u}{t}",
    "\\includegraphics{g}",
    "\\bibliography{b}",
    "\\begin{verbatim}",
    "\\end{verbatim}",
    "\\begin{comment}",
    "\\end{comment}",
    "\\begin{filecontents}{f}",
    "\\end{filecontents}",
    "\\newif\\ifx",
    "\\xtrue",
    "\\xfalse",
    "\\ifx",
    "\\ifnum 1<2",
    "\\ifcase 0",
    "\\or",
    "\\else",
    "\\fi",
    "\\iffalse",
    "\\iftrue",
    "\\endinput",
    "\x00",
    "\x01",
    "\x7f",
    "\\catcode",
    "\\expandafter",
    "\\noexpand",
    "\\par",
    "\\leavevmode",
    "\\hbox{",
]

#: 展开炸弹汤——自递归/互递归/深嵌套 if 链，BUDGET/MAX_GEN 回压面。
_BOMB_SOUP = [
    "\\def\\a{\\a}\\a",
    "\\def\\a{\\b}\\def\\b{\\a}\\a",
    "\\def\\a{\\a\\a}\\a",
    "\\def\\a{x\\a}\\a",
    "\\def\\a{\\b}\\def\\b{\\c}\\def\\c{\\a}\\a",
    "\\newif\\ifx\\ifx A \\ifx B \\fi \\fi",
    "\\iftrue A \\iftrue B \\else C \\fi D \\fi",
    "\\ifnum 1<2 yes \\else no \\fi",
    "\\ifcase 2 a \\or b \\or c \\else d \\fi",
    "\\ifx\\a\\b xx \\fi",
    "\\iffalse DEAD \\fi",
    "\\csname\\endcsname",
    "\\expandafter\\expandafter\\expandafter",
]

#: 边角输入——空/单字符/残缺 preamble（preamble 判定双正则缺席/半在场）。
_EDGE_INPUTS = [
    "",
    "\n",
    " ",
    "%",
    "\\",
    "{",
    "}",
    "$",
    "\x00",
    "abc",
    "\\end{document}",
    "\\begin{document}",
    "\\documentclass{article}",
    "\\documentclass{article}\n\\begin{document}",
    "no docclass but \\begin{document} here\n\nprose words words words words",
    "\\begin{document} alone\n\nprose words words words words words words",
    "\\documentclass{article} docclass only\n\nprose words words words words",
]


# ---------------------------------------------------------------- 断言件


def _v1_invariants(res: ScanResult, tex: str) -> None:
    """v1 全不变量束——各 fuzz 用例共享的断言件（违约即红）。"""
    # v1 坐标系即输入 tex：虚拟文本面恒空（v2 专有字段）
    assert res.vtex == "", short(tex)
    # protected_tex 构造级一致：pieces 文本拼接
    assert res.protected_tex == "".join(p.text for p in res.pieces), short(tex)
    # pieces 无缝平铺 [0, len(tex))——头号不变式
    pos = 0
    for p in res.pieces:
        assert p.span.start == pos, short(tex)
        assert 0 <= p.span.start <= p.span.end <= len(tex), short(tex)
        pos = p.span.end
    assert pos == len(tex), short(tex)
    # identity 铁律 + 结构校验零告警
    assert reconstruct(res) == tex, short(tex)
    assert validate_result(res) == [], short(tex)
    # [[CHUNK_id]] 寻址对齐
    for k, c in enumerate(res.chunks):
        assert c.id == k, short(tex)
    # 可观测性位置界内
    for w in res.warnings:
        assert 0 <= w.pos <= len(tex), short(tex)
    for ipos, _name in res.inputs:
        assert 0 <= ipos <= len(tex), short(tex)


# ---------------------------------------------------------------- 铁规 fuzz


def test_fuzz_soup_never_raises() -> None:
    """铁规：soup 随机拼装（DOC 包裹）——``parse_tex_v1`` 绝不抛 + 全不变量。"""
    rng = fuzz_rng(_SEED_SOUP)
    for _ in range(_FUZZ_ITERS):
        tex = DOC % soup_join(rng, _TEX_SOUP, 1, 24)
        _v1_invariants(parse_tex_v1(tex), tex)


def test_fuzz_soup_raw_no_wrapper() -> None:
    """裸串（无 DOC 壳）：preamble 判定缺席面——绝不抛 + 全不变量。"""
    rng = fuzz_rng(_SEED_SOUP + 1)
    for _ in range(_FUZZ_ITERS_MED):
        tex = soup_join(rng, _TEX_SOUP, 1, 24)
        _v1_invariants(parse_tex_v1(tex), tex)


def test_fuzz_mutated_doc() -> None:
    """突变 fuzz：合法 body 上插/删/换/复制 soup 片段——全不变量。"""
    rng = fuzz_rng(_SEED_MUTATE)
    base_bodies = [
        "Para words here with \\textbf{bold} and $e=mc^2$ math.\n\nSecond para.",
        "\\section{A}\nText \\cite{k} words \\footnote{fn} tail.\n\\begin{itemize}\n\\item one\n\\end{itemize}",
        "\\newcommand{\\v}[1]{\\mathbf{#1}}\nUse $\\v{x}$ here.",
        "\\newif\\ifdraft\\drafttrue\n\\ifdraft DRAFT-WORDS \\else FINAL \\fi tail.",
    ]
    for _ in range(_FUZZ_ITERS):
        body = soup_pick(rng, base_bodies)
        for _ in range(rng.randint(1, 6)):
            op = rng.randrange(4)
            pos = rng.randrange(len(body) + 1)
            piece = soup_pick(rng, _TEX_SOUP)
            if op == 0:
                body = body[:pos] + piece + body[pos:]
            elif op == 1 and body:
                end = min(len(body), pos + rng.randint(1, 8))
                body = body[:pos] + body[end:]
            elif op == 2:  # noqa: PLR2004 -- op 枚举值即 soup 概率档
                body = (
                    body[:pos] + piece + body[pos + 1 :]
                    if pos < len(body)
                    else body + piece
                )
            else:
                body = body + body[max(0, pos - 12) : pos]
        tex = DOC % body
        _v1_invariants(parse_tex_v1(tex), tex)


def test_fuzz_nesting_never_raises() -> None:
    """结构汤：未闭/交叉嵌套 group/env/数学——绝不抛 + 全不变量。"""
    rng = fuzz_rng(_SEED_GROUP)
    nest_soup = [
        "{",
        "}",
        "\\begin{a}",
        "\\end{b}",
        "\\begin{a",
        "$",
        "$$",
        "[",
        "]",
        "\\hbox{",
        "\\begingroup",
        "\\endgroup",
        "\\iftrue",
        "\\fi",
    ]
    for _ in range(_FUZZ_ITERS_MED):
        tex = DOC % soup_join(rng, nest_soup, 1, 40)
        _v1_invariants(parse_tex_v1(tex), tex)


def test_fuzz_expansion_bombs_bounded() -> None:
    """展开炸弹：自递归/互递归/深 if 链——BUDGET/MAX_GEN 兜死，绝不抛。"""
    rng = fuzz_rng(_SEED_GROUP + 1)
    for _ in range(_FUZZ_ITERS_MED):
        tex = DOC % (soup_pick(rng, _BOMB_SOUP) + soup_join(rng, _TEX_SOUP, 0, 6))
        _v1_invariants(parse_tex_v1(tex), tex)


def _det_key(res: ScanResult) -> tuple:
    """确定性投影——ScanResult 无 eq 语义，取可比较面。"""
    return (
        res.protected_tex,
        tuple(c.content for c in res.chunks),
        tuple(sorted(res.ph_map.items())),
        reconstruct(res),
    )


def test_fuzz_deterministic() -> None:
    """确定性：同 soup 产物连跑两次 ``parse_tex_v1``——投影全等。"""
    rng = fuzz_rng(_SEED_SOUP + 2)
    for _ in range(_FUZZ_ITERS_MED):
        tex = DOC % soup_join(rng, _TEX_SOUP, 2, 16)
        assert_deterministic(lambda: parse_tex_v1(tex), key=_det_key)  # noqa: B023 -- 闭包只吃 tex 无循环依赖


def test_fuzz_reentry_protected_tex() -> None:
    """重入：``protected_tex``（含 ``[[X_n]]`` 字面）再喂 v1——仍 identity。"""
    rng = fuzz_rng(_SEED_SOUP + 3)
    for _ in range(_FUZZ_ITERS_MED):
        tex = DOC % soup_join(rng, _TEX_SOUP, 1, 20)
        ptex = parse_tex_v1(tex).protected_tex
        res2 = parse_tex_v1(ptex)
        assert reconstruct(res2) == ptex, short(ptex)


# ---------------------------------------------------------------- 入口边角钉


class TestEntryEdges:
    """入口边角观察钉——pin 当前契约（非缺陷，定性留裁决）。"""

    @pytest.mark.parametrize("tex", _EDGE_INPUTS)
    def test_edge_inputs_invariants(self, tex: str) -> None:
        """空/单字符/残缺 preamble——全不变量束照常成立。"""
        _v1_invariants(parse_tex_v1(tex), tex)

    @pytest.mark.parametrize(
        "bad",
        [None, 42, b"x", ["a"], 3.5],
        ids=["none", "int", "bytes", "list", "float"],
    )
    def test_non_str_typeerror(self, bad: object) -> None:
        """非-str 入参 → ``TypeError``（v1 不容忍 None——与 v2 不对称观察钉）。"""
        with pytest.raises(TypeError):
            parse_tex_v1(bad)  # type: ignore[arg-type]


class TestDispatch:
    """``TEXLATE_NO_EXPAND`` 分派面钉——env 走 monkeypatch 不污染邻测试。"""

    def test_no_expand_routes_to_v1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``TEXLATE_NO_EXPAND=1`` → ``parse_tex`` 与 ``parse_tex_v1`` 投影全等。"""
        tex = DOC % "Dispatch probe words enough to form a chunk here. $x$ \\cite{k}"
        monkeypatch.setenv("TEXLATE_NO_EXPAND", "1")
        via_env = parse_tex(tex)
        direct = parse_tex_v1(tex)
        assert via_env.protected_tex == direct.protected_tex
        assert [c.content for c in via_env.chunks] == [c.content for c in direct.chunks]
        assert via_env.ph_map == direct.ph_map

    def test_default_routes_to_v2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺省走 v2：``vtex`` 非空面 vs v1 恒空——两臂输出契约可分。"""
        monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)
        tex = DOC % "plain dispatch words"
        assert parse_tex(tex).vtex == tex
        assert parse_tex_v1(tex).vtex == ""


class TestParseFileV1:
    """``parse_file_v1`` flatten 面钉——读盘 + ``\\input`` 族解析。"""

    def test_missing_input_warns_not_raises(self, tmp_path: Path) -> None:
        """``\\input{miss}``/自环 → ``missing_input`` warning，不抛。"""
        main = tmp_path / "main.tex"
        main.write_text(
            "\\input{nonexistent}\n\\input{main}\n\n"
            "prose words words words words words here",
            encoding="utf-8",
        )
        res = parse_file_v1(main)
        assert any(w.kind == "missing_input" for w in res.warnings)
        assert res.inputs  # 漏网 input 记名可审计

    def test_input_inlines_and_scans(self, tmp_path: Path) -> None:
        """真 ``\\input{a}`` 照常内联进扫描面。"""
        (tmp_path / "a.tex").write_text(
            "FILE-A-CONTENT enough words to be prose here", encoding="utf-8"
        )
        main = tmp_path / "main.tex"
        main.write_text("\\input{a}\n", encoding="utf-8")
        res = parse_file_v1(main)
        assert "FILE-A-CONTENT" in res.protected_tex or any(
            "FILE-A-CONTENT" in c.content for c in res.chunks
        )

    def test_missing_file_oserror(self, tmp_path: Path) -> None:
        """不存在路径 → ``OSError(ENXIO)``（api.py 明文契约，非静默空结果）。"""
        import errno  # noqa: PLC0415 -- 测试内局部导入按仓例

        with pytest.raises(OSError, match="not a regular file") as ei:
            parse_file_v1(tmp_path / "nope.tex")
        assert ei.value.errno == errno.ENXIO

    def test_flatten_false_leaves_input_literal(self, tmp_path: Path) -> None:
        """``flatten=False``：``\\input`` 不解析——记名 + 原文保留。"""
        main = tmp_path / "main.tex"
        src = "\\input{a}\n\nprose words words words words words"
        main.write_text(src, encoding="utf-8")
        res = parse_file_v1(main, flatten=False)
        assert res.inputs == [(0, "a")]
        assert "\\input{a}" in res.protected_tex or any(
            "\\input{a}" in c.content for c in res.chunks
        )
