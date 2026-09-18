"""换行编解码端到端对抗性质测试——encode_newlines/decode_newlines 混合面。

test_sentinel_ladder.py 钉族层梯级机制（_escape_family/_unescape_family 升降序、
级序迭代、级限回归）；本文件补端到端 codec 面：八族字面 token 汤（token/RAW/
sentinel/非规范形全混 + 邻接 + 字符串边缘位）、换行游程 0..10 与 CRLF/CR 归一、
脆弱空白字面与 token/换行互邻、CJK/emoji 混排，外加三条契约钉——编码产物
charset（无裸换行/脆弱字面）、encode 非幂等 iff（wire 形态在则再编码必变）、
PLACEHOLDER_CLAUSE 命名一致性（docs/08 勘误：实列 5/8 裸标记，
MEDSP/THICKSP/NEGSP 按设计不进 prompt 措辞）。
"""

import random
import re

import pytest
from _fuzzkit import fuzz_rng

from texlate.xlat import placeholders as ph
from texlate.xlat import prompts

#: 脆弱空白六族字面——SL/PL 的 lit 位是空串（换行游程不由 lit 编码），不列。
_SPACE_LITS: tuple[tuple[str, str], ...] = (
    ("[[SP]]", "\\ "),
    ("[[NBSP]]", "~"),
    ("[[THINSP]]", "\\,"),
    ("[[MEDSP]]", "\\:"),
    ("[[THICKSP]]", "\\;"),
    ("[[NEGSP]]", "\\!"),
)


def _sent(tag: str, d: str) -> str:
    """哨兵名直取（``""``=level 2、``"2"``=level 3）——与 _sent_d 同形。"""
    return f"[[__TEXLATE_{tag}_LIT{d}__]]"


def _norm(s: str) -> str:
    """``encode_newlines`` 的 CRLF 归一等价式——round-trip 期望按此对齐。"""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _enc(s: str) -> str:
    return ph.encode_newlines(s)[0]


def _rt(s: str) -> str:
    """``decode(encode(s))``——round-trip 目标值是 ``_norm(s)``。"""
    return ph.decode_newlines(_enc(s))


class TestLiteralTokenSoup:
    """字面 token 汤——八族全形态混合、邻接、边缘位、非规范哨兵。"""

    def test_all_family_forms_mega_soup(self) -> None:
        """八族 × {token, RAW, sent2, sent3, sent8, LIT0/LIT1/LIT007} 全混一锅。"""
        parts: list[str] = []
        for tag, tok, raw, _lit in ph._ALL_FAM:  # noqa: SLF001 -- 白盒钉族表
            parts += [
                tok,
                raw,
                _sent(tag, ""),
                _sent(tag, "2"),
                _sent(tag, "7"),
                _sent(tag, "0"),
                _sent(tag, "1"),
                _sent(tag, "007"),
            ]
        s = "x".join(parts)
        assert _rt(s) == s

    def test_all_tokens_adjacent(self) -> None:
        """八族 token 连排 + 倒序——邻接无分隔。"""
        toks = [tok for _tag, tok, _raw, _lit in ph._ALL_FAM]  # noqa: SLF001
        assert _rt("".join(toks)) == "".join(toks)
        assert _rt("".join(reversed(toks))) == "".join(reversed(toks))

    @pytest.mark.parametrize(
        "src",
        [
            "[[SL]]x",
            "x[[SL]]",
            "[[SP]]x",
            "x[[NEGSP]]",
            "[[SL]][[SL]]",
            "[[NBSP]][[NBSP_RAW]]",
            "[[SL_RAW]]x",
            "x[[SL_RAW]]",
            "[[__TEXLATE_SL_LIT__]]x",
            "x[[__TEXLATE_SL_LIT__]]",
            "[[__TEXLATE_NEGSP_LIT5__]]",
            "[[SL]][[SL_RAW]]",
            "[[SL_RAW]][[SL]]",
            "[[SL]][[__TEXLATE_SL_LIT__]]",
            "[[__TEXLATE_SL_LIT__]][[SL]]",
            "[[SL_RAW]][[__TEXLATE_SL_LIT__]]",
            "[[__TEXLATE_SL_LIT__]][[SL_RAW]]",
        ],
    )
    def test_tokens_at_edges(self, src: str) -> None:
        """字面 token/RAW/哨兵贴字符串首尾、异级互邻。"""
        assert _rt(src) == src

    @pytest.mark.parametrize(
        "d",
        ["0", "1", "00", "007", "01", "00000001"],
    )
    @pytest.mark.parametrize("tag", ["SL", "SP", "NEGSP"])
    def test_noncanonical_in_mixture(self, tag: str, d: str) -> None:
        """非规范哨兵混在真 token/换行/脆弱字面之间——双向透传不串。"""
        s = f"a{_sent(tag, d)}[[SL]]\\ b\n{_sent(tag, d)}"
        assert _rt(s) == _norm(s)

    def test_wrong_tag_and_malformed_sentinels(self) -> None:
        """异 tag/残形哨兵混排——所有族升降链均不命中，原样透传。"""
        s = (
            "a[[__TEXLATE_XX_LIT__]]b[[__TEXLATE_SL_LIT_]]c"
            "[[__TEXLATE_SL_LIT]]d[[_TEXLATE_SL_LIT__]]e\n"
        )
        assert _rt(s) == _norm(s)

    def test_typed_and_foreign_bare_tokens_untouched(self) -> None:
        """带号占位符与族外裸标记不参与本链——与族内形态混排亦透传。"""
        s = "[[MATH_1]][[ENV_3]][[X]][[SL_1]][[SL_RAWX]][[AUTHOR_7]]"
        assert _rt(s) == s


class TestNewlineRuns:
    """换行游程 0..10——含 PL+SL 奇数切分、边缘位、字面 token 邻接、CR 归一。"""

    @pytest.mark.parametrize("k", range(11))
    def test_run_between_text(self, k: int) -> None:
        s = "a" + "\n" * k + "b"
        assert _rt(s) == s

    @pytest.mark.parametrize("k", range(6))
    def test_run_at_edges(self, k: int) -> None:
        run = "\n" * k
        assert _rt(run + "x") == run + "x"
        assert _rt("x" + run) == "x" + run
        assert _rt(run) == run

    @pytest.mark.parametrize("k", range(5))
    def test_run_adjacent_literal_tokens(self, k: int) -> None:
        """字面 token 与真换行互邻——wire 上 RAW/SL 形可区分，不歧。"""
        run = "\n" * k
        assert _rt(f"[[SL]]{run}[[PL]]") == f"[[SL]]{run}[[PL]]"
        assert _rt(f"{run}[[SL]]") == f"{run}[[SL]]"
        assert _rt(f"[[SP]]{run}\\ ") == _norm(f"[[SP]]{run}\\ ")

    def test_odd_run_splits_pl_then_sl(self) -> None:
        """奇数游程 = ``[[PL]]``×k//2 + ``[[SL]]``——PL 在前钉死编码形。"""
        assert _enc("\n\n\n") == "[[PL]][[SL]]"
        assert _enc("\n\n\n\n\n") == "[[PL]][[PL]][[SL]]"
        assert _enc("\n\n\n\n") == "[[PL]][[PL]]"

    @pytest.mark.parametrize(
        ("src", "want"),
        [
            ("a\rb", "a\nb"),
            ("a\r\nb", "a\nb"),
            ("\r", "\n"),
            ("\r\n", "\n"),
            ("\r\r\n", "\n\n"),
            ("\n\r\n", "\n\n"),
            ("\r\n\n", "\n\n"),
            ("\n\r", "\n\n"),
            ("\r\n\r\n", "\n\n"),
            ("a\n\rb", "a\n\nb"),
            ("\r\n\r\r\n", "\n\n\n"),
        ],
    )
    def test_cr_crlf_normalize_then_round_trip(self, src: str, want: str) -> None:
        """CR/CRLF 先归一后编码——round-trip 终态是归一形，非原串。"""
        enc, _ = ph.encode_newlines(src)
        assert ph.decode_newlines(enc) == want == _norm(src)

    @pytest.mark.parametrize(
        ("src", "sl", "pl"),
        [
            ("[[SL]]\n[[PL]]", 1, 0),
            ("\n\n\n[[SL]]", 1, 1),
            ("[[PL_RAW]]\n\n\n\n", 0, 2),
            ("[[__TEXLATE_SL_LIT__]]", 0, 0),
            ("~\\ \n", 1, 0),
            ("[[SL]]", 0, 0),
        ],
    )
    def test_counts_only_real_newlines(self, src: str, sl: int, pl: int) -> None:
        """``source_sl/pl`` 只计真换行游程——字面 token/哨兵不计。"""
        _, counts = ph.encode_newlines(src)
        assert counts == {"source_sl": sl, "source_pl": pl}


class TestFragileSpaceAdjacency:
    """脆弱空白字面与 token/RAW/哨兵/换行/彼此互邻，及 chunk 边缘位。"""

    @pytest.mark.parametrize(("tok", "lit"), _SPACE_LITS)
    @pytest.mark.parametrize(
        "pattern",
        ["{lit}{tok}", "{tok}{lit}", "{lit}{raw}", "{raw}{lit}", "{lit}{sent}"],
    )
    def test_lit_adjacent_own_family(self, tok: str, lit: str, pattern: str) -> None:
        """字面贴本族 token/RAW/哨兵——encode 输出与 decode 归位各就各位。"""
        raw = tok[:-2] + "_RAW]]"
        sent = f"[[__TEXLATE_{tok[2:-2]}_LIT__]]"
        s = pattern.format(lit=lit, tok=tok, raw=raw, sent=sent)
        assert _rt(s) == s

    @pytest.mark.parametrize(
        "src",
        [
            "\\ [[NBSP]]",
            "~[[SP]]",
            "\\,[[NEGSP]]",
            "~[[SL]]",
            "\\ [[PL]]",
            "\\!~",
            "~\\!",
            "\\,\\:",
            "\\:\\;",
            "\\;\\!",
            "\\ \\,\\:\\;\\!~",
            "~\\ \\,\\:\\;\\!",
        ],
    )
    def test_lits_adjacent_each_other(self, src: str) -> None:
        """脆弱字面互邻——``\\ ``/``~``/``\\,`` 链式拼接不互相吞吃。"""
        assert _rt(src) == src

    @pytest.mark.parametrize(
        "src",
        [
            "\\ a",
            "a\\ ",
            "\\ ",
            "\\ \\ ",
            "~a",
            "a~",
            "~",
            "~~",
            "~~~",
            "~ ~",
            "\\,a",
            "a\\!",
            "\\:\\;",
            "a\\:b",
        ],
    )
    def test_lit_at_chunk_edges(self, src: str) -> None:
        """脆弱字面贴 chunk 首尾/独占/连排。"""
        assert _rt(src) == src

    @pytest.mark.parametrize(
        ("src", "want"),
        [
            ("a\\", "a\\"),  # 孤反斜杠——非脆弱字面，原样透传
            ("\\", "\\"),
            ("\\a", "\\a"),
            ("\\\\a", "\\\\a"),
            ("a\\\\", "a\\\\"),
            ("\\\\ ", "\\[[SP]]"),  # `\\` + `\ `——第二根反斜杠起 lit
            ("\\\\\\ ", "\\\\[[SP]]"),  # `\\` + `\ `同上
            ("\\\\,", "\\[[THINSP]]"),
            ("\\%\\ ", "\\%[[SP]]"),  # `%\ ` 之后真 `\ ` 仍是 lit
        ],
    )
    def test_backslash_edges(self, src: str, want: str) -> None:
        """反斜杠边界——lit 是 ``\\``+特定字符，孤 ``\\`` 与 ``\\\\`` 不吃。"""
        assert _enc(src) == want
        assert ph.decode_newlines(want) == src

    @pytest.mark.parametrize(
        "src",
        [
            "\\ \n",
            "\n\\ ",
            "~\n\n~",
            "\\,\n\\!",
            "\\ \n\n\n~",
            "\n~",
            "\n\n\\ ",
        ],
    )
    def test_lit_adjacent_newlines(self, src: str) -> None:
        """脆弱字面与换行游程互邻——lit→token 与 \\n→SL/PL 各编码各的。"""
        assert _rt(src) == src

    @pytest.mark.parametrize(
        "src",
        [
            "[[\\ ]]",  # 括号内脆弱字面——token 形被啃仍 round-trip
            "[[~]]",
            "[[\\,]]",
            "[[MATH\\ 1]]",
            "[[SL\\ ]]",
            "[[NBSP~]]",
        ],
    )
    def test_grammar_broken_literals(self, src: str) -> None:
        """括号汤内嵌脆弱字面——编码是纯文本替换，破语法形亦无损。"""
        assert _rt(src) == src


class TestUnicodeMix:
    """CJK/emoji/混排文本与 token/换行/脆弱字面同现。"""

    @pytest.mark.parametrize(
        "src",
        [
            "中文[[SL]]混排\n第二行",
            "日文テスト~間隔\\ ",
            "emoji🎉\n🎉",
            "🎉[[NBSP]]",
            "café\nnaïve\\,",
            "混排 [[PL]] 换行\n\n段落",
            "Кириллица\\ текст",
            "第\\ 一~行\\,末\n尾",
            "% 注释 [[SL]]\\ \n正文",
            "数式 $x_1$~と\\,~文",
        ],
    )
    def test_unicode_round_trip(self, src: str) -> None:
        assert _rt(src) == _norm(src)


#: 规范哨兵后缀 = ``""``(level 2) 或无前导零且 ≠"1" 的十进制（``"2"``=level 3）。
#: wire 上判"在册形态"用——非规范形（LIT0/LIT1/LIT007/前导零）双向透传不算。
_WIRE_RX = re.compile(
    r"\[\[(?:SL|PL|SP|NBSP|THINSP|MEDSP|THICKSP|NEGSP)(?:_RAW)?\]\]"
    r"|\[\[__TEXLATE_(?:SL|PL|SP|NBSP|THINSP|MEDSP|THICKSP|NEGSP)_LIT"
    r"(?:|[2-9]\d*|1\d+)__\]\]"
)


class TestCodecContracts:
    """编码产物契约——charset、计数 oracle、非幂等 iff、CR 有损、decode 合流。"""

    @pytest.mark.parametrize(
        "src",
        [
            "a\nb\n\nc\rd\r\ne",
            "\n\n\n~\\ \\,\\:\\;\\!",
            "[[SL]]\n[[SP_RAW]]~",
            "\r\n\r\n\r\n",
        ],
    )
    def test_encoded_output_charset(self, src: str) -> None:
        """编码产物无裸 ``\\n``/``\\r``、无六族脆弱字面残留（docstring 契约）。"""
        enc = _enc(src)
        assert "\n" not in enc
        assert "\r" not in enc
        for _tok, lit in _SPACE_LITS:
            assert lit not in enc

    @pytest.mark.parametrize(
        "src",
        [
            "a\\ b\\ c",
            "x~y~z~",
            "\\,\\:\\;\\!",
            "[[SP]]\\ [[SP]]",  # 字面 token 升 RAW 后，wire [[SP]] 只来自 lit
            "\\ \\ \\",
        ],
    )
    def test_wire_token_count_equals_lit_count(self, src: str) -> None:
        """wire 上族 token 计数恰等于源中对应脆弱字面数——转义链不漏不增。"""
        enc = _enc(src)
        for tok, lit in _SPACE_LITS:
            assert enc.count(tok) == _norm(src).count(lit), (tok, lit, src, enc)

    def test_wire_sl_pl_counts_match_dict(self) -> None:
        """wire 上 ``[[SL]]/[[PL]]`` 计数恰等于 counts 字典——两口径同源。"""
        enc, counts = ph.encode_newlines("a\nb\n\nc\n\n\nd")
        assert enc.count(ph.SOFT_NEWLINE) == counts["source_sl"]
        assert enc.count(ph.PARA_NEWLINE) == counts["source_pl"]

    def test_encode_bumps_tokens_one_level(self) -> None:
        """encode 非幂等——wire 上裸 token/RAW 再编码各升一级（定向三级链）。"""
        assert _enc("a\nb") == "a[[SL]]b"
        assert _enc("a[[SL]]b") == "a[[SL_RAW]]b"
        assert _enc("a[[SL_RAW]]b") == "a[[__TEXLATE_SL_LIT__]]b"
        assert _enc("a[[__TEXLATE_SL_LIT__]]b") == "a[[__TEXLATE_SL_LIT2__]]b"

    @pytest.mark.parametrize(
        "src",
        [
            "plain text",
            "",
            "[[X]]",  # 族外裸标记——非 wire 形态，再编码不动
            "[[MATH_1]]",  # 带号占位符不涉本链
            "a\\b",  # 孤反斜杠非 lit
            "x[[__TEXLATE_SL_LIT0__]]y",  # 非规范哨兵透传
            "x[[__TEXLATE_SL_LIT007__]]y",
            "a\nb",  # 产 [[SL]]——wire 形态在则再编码必变
            "a~b",
            "a\\ b",
            "[[SL]]",  # 字面 token——encode 产出 RAW 即 wire 形态
            "[[SL_RAW]]",
            "[[__TEXLATE_SL_LIT__]]",  # 规范哨兵再升一级
            "[[__TEXLATE_SL_LIT10__]]",
        ],
    )
    def test_encode_idempotent_iff_no_wire_forms(self, src: str) -> None:
        """``encode²(x) == encode(x)`` iff 编码产物不含任何 wire 形态
        （族 token/RAW/规范哨兵）——非幂等的精确语义。"""
        enc = _enc(src)
        enc2 = _enc(enc)
        assert (enc2 != enc) == bool(_WIRE_RX.search(enc))
        # 无论幂等与否，decode 对应降层总能归位
        assert ph.decode_newlines(enc) == _norm(src)

    def test_cr_normalization_is_lossy(self) -> None:
        """``\\r``→``\\n`` 归一写进 round-trip——CR 信息不可恢复是契约。"""
        assert _rt("a\rb") == "a\nb"
        assert _rt("a\rb") != "a\rb"
        assert _rt("a\r\nb") == "a\nb"

    def test_decode_merges_pl_sl_orderings(self) -> None:
        """decode 对裸 wire 非单射——``[[PL]][[SL]]`` 与 ``[[SL]][[PL]]``
        同归 ``\\n\\n\\n``（encode 只产 PL 在前的规范形，故不歧）。"""
        assert ph.decode_newlines("[[PL]][[SL]]") == "\n\n\n"
        assert ph.decode_newlines("[[SL]][[PL]]") == "\n\n\n"


class TestPlaceholderClauseConsistency:
    """C9 条款命名一致性——docs/08 §1.1 勘误钉住的 5/8 划分。"""

    def test_named_bare_tokens_are_module_constants(self) -> None:
        """条款点名的每个裸 token 都是 placeholders 模块实存常量。"""
        all_tokens = {tok for _tag, tok, _raw, _lit in ph._ALL_FAM}  # noqa: SLF001
        for tok in ph.BARE_PH_RX.findall(prompts.PLACEHOLDER_CLAUSE):
            assert tok in all_tokens, f"clause names {tok} not in _ALL_FAM"

    def test_named_set_is_exactly_five_of_eight(self) -> None:
        """条款实列恰 {SL,PL,SP,NBSP,THINSP}——docs/08:48 勘误：
        MEDSP/THICKSP/NEGSP 三族按设计不进 prompt 措辞，此划分漂移须显见。"""
        named = set(ph.BARE_PH_RX.findall(prompts.PLACEHOLDER_CLAUSE))
        expected = {"[[SL]]", "[[PL]]", "[[SP]]", "[[NBSP]]", "[[THINSP]]"}
        assert named == expected
        unnamed = {tok for _tag, tok, _r, _l in ph._ALL_FAM} - named  # noqa: SLF001
        assert unnamed == {"[[MEDSP]]", "[[THICKSP]]", "[[NEGSP]]"}

    def test_typed_examples_match_ph_grammar(self) -> None:
        """条款 typed 样例全部命中 ``[[TYPE_n]]`` 语法（``TYPE`` 全大写+数字）。"""
        typed = ph.TYPED_PH_RX.findall(prompts.PLACEHOLDER_CLAUSE)
        assert typed == [
            "[[MATH_12]]",
            "[[CITE_3]]",
            "[[REF_7]]",
            "[[ENV_4]]",
            "[[AUTHOR_1]]",
        ]


def _fuzz_atoms() -> list[str]:
    """fuzz 原子表——八族全形态 + 非规范哨兵 + 边缘碎片 + 噪声，随族表自增。"""
    atoms = [
        "word",
        "TEXT",
        "x y",
        "中文段落",
        "日文テスト",
        "🎉",
        "café",
        "\\cite{a}",
        "$e=mc^2$",
        "%cmt\n",
        "[[MATH_1]]",
        "[RS80]",
        "\\textbf{b}",
        "\\",
        " ",
        ",",
        ";",
        "!",
        "\n",
        "\n\n",
        "\n\n\n",
        "\r\n",
        "\r",
        "\t",
        "[[",
        "]]",
        "[[SL",
        "SL]]",
        "[[[SL]]]",
        "[[SL]]_RAW]]",
        "[[X]]",
        "[[SL_1]]",
        "[[SL_RAWX]]",
        "[[__TEXLATE_XX_LIT__]]",
        "[[__TEXLATE_SL_LIT_]]",
        "[[__TEXLATE_SL_LIT]]",
        "[[_TEXLATE_SL_LIT__]]",
        "[[\\ ]]",
        "[[~]]",
    ]
    for tag, tok, raw, lit in ph._ALL_FAM:  # noqa: SLF001 -- 白盒钉族表
        atoms += [
            tok,
            raw,
            _sent(tag, ""),
            _sent(tag, "2"),
            _sent(tag, "9"),
            _sent(tag, "0"),
            _sent(tag, "1"),
            _sent(tag, "007"),
            lit,
        ]
    return atoms


_ATOMS = _fuzz_atoms()


class TestSeededFuzz:
    """种子化 fuzz——端到端混合面 round-trip + 契约 oracle 同断言。"""

    def _soup(self, rng: random.Random, n: int) -> str:
        return "".join(rng.choice(_ATOMS) for _ in range(n))

    def test_round_trip_fuzz_400(self) -> None:
        rng = fuzz_rng(20260917)
        for i in range(400):
            s = self._soup(rng, rng.randint(0, 20))
            enc, _ = ph.encode_newlines(s)
            dec = ph.decode_newlines(enc)
            assert dec == _norm(s), (i, s, enc, dec)

    def test_oracles_fuzz(self) -> None:
        """逐样本同钉三 oracle：charset、族计数、非幂等 iff。"""
        rng = fuzz_rng(20260918)
        for i in range(250):
            s = self._soup(rng, rng.randint(0, 20))
            ns = _norm(s)
            enc, counts = ph.encode_newlines(s)
            assert "\n" not in enc, (i, s, enc)
            assert "\r" not in enc, (i, s, enc)
            for tok, lit in _SPACE_LITS:
                assert lit not in enc, (i, lit, s, enc)
                assert enc.count(tok) == ns.count(lit), (i, tok, s, enc)
            assert enc.count(ph.SOFT_NEWLINE) == counts["source_sl"], (i, s, enc)
            assert enc.count(ph.PARA_NEWLINE) == counts["source_pl"], (i, s, enc)
            enc2, _ = ph.encode_newlines(enc)
            assert (enc2 != enc) == bool(_WIRE_RX.search(enc)), (i, s, enc, enc2)
            assert ph.decode_newlines(ph.decode_newlines(enc2)) == ns, (i, s, enc2)

    def test_edge_heavy_fuzz(self) -> None:
        """边缘重采样——首尾强制 token/lit/换行原子，中段随机。"""
        rng = fuzz_rng(20260919)
        edge_atoms = [a for a in _ATOMS if a.startswith("[[") or a in _SPACE_LITS]
        edge_atoms += [lit for _tok, lit in _SPACE_LITS] + ["\n", "\n\n", "\r\n"]
        for i in range(250):
            s = (
                rng.choice(edge_atoms)
                + self._soup(rng, rng.randint(0, 12))
                + rng.choice(edge_atoms)
            )
            enc, _ = ph.encode_newlines(s)
            assert ph.decode_newlines(enc) == _norm(s), (i, s, enc)

    def test_newline_run_fuzz(self) -> None:
        """换行游程特化——随机游程（0..10）与随机原子交错。"""
        rng = fuzz_rng(20260920)
        for i in range(250):
            parts = []
            for _ in range(rng.randint(1, 8)):
                parts.append(rng.choice(_ATOMS))
                parts.append("\n" * rng.randint(0, 10))
            s = "".join(parts)
            enc, _ = ph.encode_newlines(s)
            assert ph.decode_newlines(enc) == _norm(s), (i, s, enc)
