r"""segmenter 面包 fuzz——「绝不抛异常」铁规 + identity + validate 零告警。

不变量清单（Gullet+Segmenter 产品路径，``scan_tex``/``parse_tex``/
``parse_tex``/``parse_file``/``reconstruct``/``validate_result``）：

- 铁规：任意 ``str`` 入参 ``parse_tex``/``scan_tex`` 绝不抛异常——含
  敌意 soup 拼装、突变文档、嵌套/未闭 group/env、展开炸弹
  （``MAX_GEN=32``/``BUDGET`` 兜死）、``\input`` 无根解析。
- identity：``reconstruct(res) == tex`` 逐字节还原（展开组以调用点
  vtex 切片保面）。
- ``validate_result(res) == []`` 零告警（pieces 无缝平铺 +
  ph/chunk 无悬空——``check_invariants`` 公共口径）。
- 确定性：同输入连跑 ``res`` 逐字节同（vtex/chunks/pieces 全等）。
- 入口边角：空 ``Gullet`` → 空 ``ScanResult``；``parse_tex(None)``
  → 空结果（容忍）；非 str → ``TypeError``（观察钉，非缺陷）。

缺陷台账（``tmp/segmenter-fuzz/`` 实证，2026-09-17，xfail-strict 钉——
修复后 XPASS 即拆钉信号）：

- [FIXED] S1：``\@`` + ASCII 字母 → reconstruct 注入伪空格 →
  identity 破。根因：``_common.py`` ``_LETTER_TAIL_RX`` 把孤 ``\@``
  尾当「字母结尾 csname」匹配（``@`` 在字符类里）→ ``core.py``
  ``_rappend`` 的 prev-ends-``\<letters>`` + next-starts-letter 判定
  触发，插入 ``" "``。``\@foo``→``\@ foo``、``\alpha\@beta``→
  ``\alpha\@ beta``。修法落地：``\\[a-zA-Z@]*[a-zA-Z]\Z``（尾字符
  必须真字母，``@`` 只许中位）——``_common.py``/``scanner.py``
  （``letters_cut`` 同源）/``reconstruct.py _CS_TAIL_RX``（译文接缝
  同族）三处同改。``\@`` 是控制符号不吞后继空格；``\ds@list`` 族
  中位 ``@`` 不受影响。
- [FIXED] S2（minor）：``ph_collision`` 声明字面量 →
  ``validate_result`` 误报 ``dangling_ph``。修法落地：``ScanResult``
  增 ``ph_reserved`` 字段（``scan_tex``/``Segmenter.scan`` 双源透传），
  ``validate_result`` 对 ``res.ph_reserved`` 内 token 豁免
  ``dangling_ph`` 与 ``dangling_chunk_ref``（oob ``[[CHUNK_n]]`` 字面
  同族——可 resolve 的 ``[[CHUNK_0]]`` 仍按真 ref 走，钉保留）；
  ``reconstruct`` 的 ``dangling`` 日志集同规豁免。

观察钉（pin observed——当前行为即取舍，定性留裁决）：

- ``parse_tex(None)`` → 空 ``ScanResult``（None 被当空源容忍，
  与其它非-str 的 TypeError 不对称）。
- ``reconstruct`` 敌意 ``translations``：str 键/oob/负 id 静默忽略；
  非 str 值 → ``TypeError``（双层包装 ``TypeError(TypeError(...))``）；
  ``[[CHUNK_0]]``/NUL 值原样穿透进输出。
- ``[[CHUNK_0]]`` 字面源不误报 ``dangling_ph``（解析成真 chunk ref
  ——与 S2 的 ``[[MATH_1]]`` 族不对称：同类字面，一类告警一类不）。
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
from conftest import DOC, check_invariants, scan_doc

from texlate.latex import parse_tex, reconstruct
from texlate.latex.gullet import Gullet
from texlate.latex.reconstruct import validate_result
from texlate.latex.segmenter import parse_tex as _seg_parse_tex
from texlate.latex.segmenter import scan_tex

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult

# ---------------------------------------------------------------- 常量与 soup

_FUZZ_ITERS = 600
_FUZZ_ITERS_MED = 300
_SEED_SOUP = 2026091706
_SEED_MUTATE = 2026091707
_SEED_GROUP = 2026091708

#: 敌意 token 汤——控制序列/环境/组/数学/注释/展开族/CJK/边缘字符。
#: ``\@``+字母与 ``[[X_n]]`` 字面曾由 S1/S2 钉表隔离、不入汤；修复后
#: sweep 对全汤面断言 identity+validate（``\@gobble`` 等汤料自带触形）。
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
    "\\newcommand{\\v}[1]{#1}",
    "\\v{y}",
    "\\def\\self{\\self}",
    "\\self",
    "\\input{a}",
    "\\include{b}",
    "\\usepackage{c}",
    "\\verb|x|",
    "\\verb",
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
    "\\label{l}",
    "\\ref{l}",
    "\\cite{c}",
    "\\footnote{f}",
    "\x00",
    "\x01",
    "\x7f",
    "\\catcode",
    "\\expandafter",
    "\\noexpand",
    "\\par",
    "\\leavevmode",
    "\\hbox{",
    "\\ifx",
    "\\else",
    "\\fi",
]

#: S1 钉表——``\@``+ASCII 字母全形态（正文/group/env arg/宏参/makeatother 后）。
_S1_CASES = [
    "\\@foo",
    "\\@namedef{x}{y}",
    "\\alpha\\@beta",
    "{\\@x}",
    "\\textbf{\\@x}",
    "a \\@b c",
    "\\@z",
    "\\section{\\@x}",
    "text \\@A more",
    "\\makeatletter\n\\@ok\n\\makeatother\n\\@bar",
]

#: S1 排除面——这些形态 identity 必须继续成立（修 S1 不许误伤）。
_S1_SAFE = [
    "\\@-foo",  # 非字母跟随
    "\\@1",  # 数字跟随
    "\\@@foo",  # 双 @
    "\\@ foo",  # 已带空格
    "a\\@",  # 行尾
    "\\@",  # 孤立
    "\\alpha\\@",  # csname 尾
    "\\@中文",  # CJK 跟随
    "\\@_x",  # 下划线跟随
    "\\makeatletter\n\\@foo\n\\makeatother",  # @ 作字母期
    "\\def\\m{\\@x}\\m",  # \def 体内（ph 本体不拆）
    "$\\@x$",  # 数学区
    "\\-foo",  # 其它控制符号对照
    "\\_x",
    "\\;x",
    "\\!x",
    "\\,x",
]

#: S2 ph_collision 字面量——声明保留却被 ``validate_result`` 报 dangling_ph。
#: ``[[CHUNK_99]]`` 是 oob chunk 字面形：dangling_chunk_ref 同族豁免面。
_S2_CASES = [
    "text [[MATH_1]] more words here to fill",
    "\\def\\m{[[X_1]]}\\m",
    "[[EQ_2]] at start of a sentence with words",
    "see [[ENV_3]] literal and [[MATH_2]] words",
    "see [[CHUNK_99]] literal words words words here",
]


# ---------------------------------------------------------------- 小件


def _vtex_pieces(res: ScanResult) -> str:
    """全部 piece 覆盖的 vtex 切片拼接——identity 的 piece 级口径。"""
    return "".join(res.vtex[p.span.start : p.span.end] for p in res.pieces)


def _assert_never_raises(tex: str) -> ScanResult:
    """铁规断言件：``parse_tex`` 不抛即返回 res（抛则测试自然红）。"""
    return parse_tex(tex)


# ---------------------------------------------------------------- S1 钉表


class TestAtLetterSpace:
    r"""S1（已修）：``\@``+ASCII 字母 → ``_rappend`` 伪空格 → identity 破。"""

    @pytest.mark.parametrize("body", _S1_CASES)
    def test_at_letter_identity(self, body: str) -> None:
        tex = DOC % body
        res = parse_tex(tex)
        assert reconstruct(res) == tex

    @pytest.mark.parametrize("body", _S1_SAFE)
    def test_at_boundary_identity(self, body: str) -> None:
        """排除面钉：非字母跟随/双@/makeatletter 内/def 体/数学区恒不破。"""
        tex = DOC % body
        res = parse_tex(tex)
        check_invariants(res, tex)

    def test_at_letter_space_signature(self) -> None:
        """修复签名钉：``\\@foo`` 逐字节还原，且不再出现 ``\\@ `` 伪空格。"""
        tex = DOC % "\\@foo"
        res = parse_tex(tex)
        out = reconstruct(res)
        assert out == tex
        assert "\\@ foo" not in out

    def test_control_symbols_other_than_at_safe(self) -> None:
        """对照组：``@`` 以外全部控制符号 + 字母跟随——identity 不破。"""
        for cs in (
            "\\-",
            "\\_",
            "\\;",
            "\\!",
            "\\,",
            "\\:",
            "\\%",
            "\\&",
            "\\#",
            "\\~",
            "\\^",
        ):
            body = f"{cs}foo"
            tex = DOC % body
            res = parse_tex(tex)
            assert reconstruct(res) == tex, short(body)


# ---------------------------------------------------------------- S2 钉表


class TestPhReservedDangling:
    """S2（已修）：``ph_reserved`` 声明字面量 → ``validate_result`` 不误报。"""

    @pytest.mark.parametrize("body", _S2_CASES)
    def test_reserved_literal_no_dangling(self, body: str) -> None:
        res = scan_doc(body)
        assert validate_result(res) == []

    @pytest.mark.parametrize("body", _S2_CASES)
    def test_reserved_literal_identity_holds(self, body: str) -> None:
        """S2 不误伤 identity：字面量逐字节还原 + ph_collision 告警在。"""
        res = scan_doc(body)
        assert reconstruct(res) == DOC % body
        assert any(w.kind == "ph_collision" for w in res.warnings)

    def test_chunk_ref_literal_exempt(self) -> None:
        """观察钉：``[[CHUNK_0]]`` 字面不告警——解析成真 chunk ref。"""
        res = scan_doc("see [[CHUNK_0]] inline words words words here")
        assert reconstruct(res) == DOC % "see [[CHUNK_0]] inline words words words here"
        assert not [w for w in validate_result(res) if w.kind == "dangling_ph"]

    def test_reserved_token_avoids_issued_ph(self) -> None:
        """保留集真生效：源含 ``[[MATH_1]]`` 时签发避开同号——无顶替。"""
        body = "[[MATH_1]] and $x+y$ math words words words words"
        res = scan_doc(body)
        assert reconstruct(res) == DOC % body
        # $x+y$ 的 MATH 占位符签到了别的号（保留集避让），字面号不进 ph_map
        assert "[[MATH_1]]" not in res.ph_map
        assert any(v == "$x+y$" for v in res.ph_map.values())


# ---------------------------------------------------------------- 铁规 fuzz


def test_fuzz_soup_never_raises() -> None:
    """铁规：soup 随机拼装（DOC 包裹）——``parse_tex`` 绝不抛。"""
    rng = fuzz_rng(_SEED_SOUP)
    for _ in range(_FUZZ_ITERS):
        body = soup_join(rng, _TEX_SOUP, 1, 24)
        res = _assert_never_raises(DOC % body)
        # vtex 切片无缝（pieces 平铺的头号不变式与抛异常同级——不许静默丢片）
        assert _vtex_pieces(res) == res.vtex, short(body)


def test_fuzz_soup_identity_and_validate() -> None:
    r"""identity+validate sweep：S1/S2 修复后全汤面断言（``\@``+字母与
    ``[[X_n]]`` 字面不再跳过——回归即红）。"""
    rng = fuzz_rng(_SEED_SOUP + 1)
    for _ in range(_FUZZ_ITERS):
        body = soup_join(rng, _TEX_SOUP, 2, 30)
        tex = DOC % body
        res = parse_tex(tex)
        assert reconstruct(res) == tex, short(body)
        assert validate_result(res) == [], short(body)
        check_invariants(res, tex)


def test_fuzz_mutated_doc_never_raises() -> None:
    """突变 fuzz：合法 DOC 上插/删/换/复制 soup 片段——绝不抛 + identity。"""
    rng = fuzz_rng(_SEED_MUTATE)
    base_bodies = [
        "Para words here with \\textbf{bold} and $e=mc^2$ math.\n\nSecond para.",
        "\\section{A}\nText \\cite{k} words \\footnote{fn} tail.\n\\begin{itemize}\n\\item one\n\\end{itemize}",
        "\\newcommand{\\v}[1]{\\mathbf{#1}}\nUse $\\v{x}$ here.",
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
        res = _assert_never_raises(tex)
        assert reconstruct(res) == tex, short(body)
        assert validate_result(res) == [], short(body)


def test_fuzz_nesting_never_raises() -> None:
    """结构汤：未闭/交叉嵌套 group/env/数学——绝不抛 + 界外 identity。"""
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
    ]
    for _ in range(_FUZZ_ITERS_MED):
        body = soup_join(rng, nest_soup, 1, 40)
        tex = DOC % body
        res = _assert_never_raises(tex)
        assert reconstruct(res) == tex, short(body)


def test_fuzz_expansion_bombs_bounded() -> None:
    """展开炸弹：自递归/互递归/深链——Gullet 预算兜死，绝不抛。"""
    rng = fuzz_rng(_SEED_GROUP + 1)
    bombs = [
        "\\def\\a{\\a}\\a",
        "\\def\\a{\\b}\\def\\b{\\a}\\a",
        "\\def\\a{\\a\\a}\\a",
        "\\def\\a{x\\a}\\a",
        "\\def\\a{\\b}\\def\\b{\\c}\\def\\c{\\a}\\a",
        "\\csname\\endcsname",
        "\\expandafter\\expandafter\\expandafter",
    ]
    for _ in range(_FUZZ_ITERS_MED):
        body = soup_pick(rng, bombs) + soup_join(rng, _TEX_SOUP, 0, 6)
        tex = DOC % body
        res = _assert_never_raises(tex)
        assert reconstruct(res) == tex, short(body)


def _det_key(res: ScanResult) -> tuple:
    """确定性投影——ScanResult 无 eq 语义，取可比较面（vtex/chunks/pieces/重建）。"""
    return (res.vtex, len(res.chunks), len(res.pieces), reconstruct(res))


def test_fuzz_deterministic() -> None:
    """确定性：同 soup 产物连跑两次 parse_tex——投影全等。"""
    rng = fuzz_rng(_SEED_SOUP + 2)
    for _ in range(_FUZZ_ITERS_MED):
        body = soup_join(rng, _TEX_SOUP, 2, 16)
        tex = DOC % body
        assert_deterministic(lambda: parse_tex(tex), key=_det_key)  # noqa: B023 -- 闭包只吃 tex 无循环依赖


# ---------------------------------------------------------------- 入口边角钉


class TestEntryEdges:
    """入口边角观察钉——pin 当前契约（非缺陷，定性留裁决）。"""

    def test_parse_tex_none_tolerated(self) -> None:
        """``None`` → 空结果（容忍）；其它非-str 是 TypeError（下钉）。"""
        res = parse_tex(None)  # type: ignore[arg-type]
        assert res.pieces == []
        assert res.chunks == []

    @pytest.mark.parametrize("bad", [42, b"x", ["a"], 3.5])
    def test_parse_tex_non_str_typeerror(self, bad: object) -> None:
        """非-str 入参 → ``TypeError`` 裸逃（调用方契约，钉住防误读）。"""
        with pytest.raises(TypeError):
            parse_tex(bad)  # type: ignore[arg-type]

    def test_scan_tex_empty_gullet(self) -> None:
        """空 Gullet 三形态 → 空 ``ScanResult``。"""
        for g in (Gullet(), Gullet(""), self._push_empty()):
            res = scan_tex(g)
            assert res.pieces == []
            assert res.vtex == ""

    @staticmethod
    def _push_empty() -> Gullet:
        g = Gullet()
        g.push_source("")
        return g

    def test_parse_tex_entry_same(self) -> None:
        """``segmenter.parse_tex``/``api.parse_tex`` 同路径（NO_EXPAND 缺席时）。"""
        tex = DOC % "same entry path words here"
        assert reconstruct(_seg_parse_tex(tex)) == reconstruct(parse_tex(tex))


class TestReconstructTranslations:
    """``reconstruct(res, translations)`` 敌意参观察钉。"""

    @pytest.fixture
    def res(self) -> ScanResult:
        return scan_doc("Para words here for chunk formation to happen properly.")

    @pytest.mark.parametrize(
        "tr",
        [{"0": "译文"}, {9999: "x"}, {-1: "x"}, {0: "[[CHUNK_0]]"}, {0: "a\x00b"}],
        ids=["str_key", "oob_id", "neg_id", "selfref", "nul_val"],
    )
    def test_hostile_translations_tolerated(self, res: ScanResult, tr: dict) -> None:
        """str 键/越界/负 id/自引/NUL 值——不抛，原样穿透或静默忽略。"""
        out = reconstruct(res, tr)  # type: ignore[arg-type]
        assert isinstance(out, str)

    @pytest.mark.parametrize("bad", [5, None, ["x"]], ids=["int", "none", "list"])
    def test_non_str_translation_typeerror(self, res: ScanResult, bad: object) -> None:
        """非-str 译文值 → ``TypeError``（双层包装签名见台账）。"""
        with pytest.raises(TypeError):
            reconstruct(res, {0: bad})
