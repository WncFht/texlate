"""sentinel 梯级转义链对抗性质测试——escape/unescape 闭链。

族层 ``_escape_family``/``_unescape_family`` 与编解码层
``encode_newlines``/``decode_newlines`` 的双向性质：任意深哨兵字面、
非规范哨兵形（``LIT0``/``LIT1``/前导零/超位长）、跨族隔离、升降序依赖、
``decode`` 对裸 token 的吞吃语义，以及两条已修缺陷回归钉
（``LIT{9×5000}`` int 位限炸链 / ``LIT99999999`` 密区间空转 DoS）。
"""

import random
import re
import string

import pytest
from _fuzzkit import fuzz_rng

from texlate.xlat import placeholders as ph

_TAGS = ("SL", "PL", "SP", "NBSP", "THINSP", "MEDSP", "THICKSP", "NEGSP")
_FAM = {tag: (tok, raw) for tag, tok, raw, _lit in ph._ALL_FAM}  # noqa: SLF001 -- 白盒钉族表


def _s(tag: str, level: int) -> str:
    return ph._sentinel(tag, level)  # noqa: SLF001 -- 白盒钉哨兵命名


def _sd(tag: str, d: str) -> str:
    return f"[[__TEXLATE_{tag}_LIT{d}__]]"


def _norm(s: str) -> str:
    """``encode_newlines`` 的 CRLF 归一等价式——round-trip 期望按此对齐。"""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _esc(text: str, tag: str) -> str:
    tok, raw = _FAM[tag]
    return ph._escape_family(text, tag, tok, raw)  # noqa: SLF001 -- 白盒钉单族链


def _une(text: str, tag: str) -> str:
    tok, raw = _FAM[tag]
    return ph._unescape_family(text, tag, tok, raw)  # noqa: SLF001 -- 同上


def _ds(text: str, tag: str) -> list[str]:
    return ph._sentinel_ds(text, tag)  # noqa: SLF001 -- 白盒钉在册级序


class TestSentinelNaming:
    """`_sentinel`/`_sent_d`/`_sentinel_ds` 命名与级序契约。"""

    def test_sentinel_names(self) -> None:
        assert _s("SL", 2) == "[[__TEXLATE_SL_LIT__]]"
        assert _s("SL", 3) == "[[__TEXLATE_SL_LIT2__]]"
        assert _s("SL", 8) == "[[__TEXLATE_SL_LIT7__]]"

    def test_sent_d_parity(self) -> None:
        """后缀直取与级数命名同物：``""``↔2、``"2"``↔3。"""
        assert _sd("SP", "") == _s("SP", 2)
        assert _sd("SP", "2") == _s("SP", 3)
        assert _sd("SP", "11") == _s("SP", 12)

    def test_rx_captures_suffix(self) -> None:
        rx = ph._SENT_RX["SL"]  # noqa: SLF001 -- 白盒钉扫描器
        assert rx.findall("a[[__TEXLATE_SL_LIT__]]b") == [""]
        assert rx.findall("[[__TEXLATE_SL_LIT12__]]") == ["12"]

    def test_ds_order_and_canonical_filter(self) -> None:
        """在册级按 (len, 字典序) 数值升序、``""`` 排首；非规范形剔除。"""
        text = "".join(
            [
                _sd("SL", "10"),  # level 11
                _sd("SL", ""),  # level 2
                _sd("SL", "2"),  # level 3
                _sd("SL", "007"),  # 非规范——剔除
                _sd("SL", "0"),
                _sd("SL", "1"),
            ]
        )
        assert _ds(text, "SL") == ["", "2", "10"]

    def test_ds_dedupes(self) -> None:
        assert _ds(_sd("SL", "2") * 3, "SL") == ["2"]

    def test_dec_succ_pred_inverse(self) -> None:
        for d in ("2", "3", "9", "10", "19", "99", "100", "999", "10" * 20):
            succ = ph._dec_succ(d)  # noqa: SLF001 -- 白盒钉进位
            assert ph._dec_pred(succ) == d  # noqa: SLF001
            assert int(succ) == int(d) + 1
        assert ph._dec_succ("999") == "1000"  # noqa: SLF001
        assert ph._dec_pred("2") == ""  # noqa: SLF001 -- level 3→2 衔接空后缀


#: 族层对抗输入集——每族通用同一批（tag 无关形态 + tag 相关形态在测试内拼）。
def _adversarial_inputs(tag: str) -> list[str]:
    tok, raw = _FAM[tag]
    s2, s3, s8 = _s(tag, 2), _s(tag, 3), _s(tag, 8)
    return [
        "",
        "plain text only",
        tok,
        raw,
        s2,
        s3,
        s8,
        f"{tok}{raw}{s2}{s3}",  # 全链邻接
        f"a{tok}b{raw}c{s2}d{s3}e{s8}f",  # 全链散布
        f"{tok}{tok}{tok}",  # token 连排
        f"{s3}{s2}{s8}{s2}{s3}",  # 乱序多级
        f"{s8}suffix",  # 哨兵作前缀
        f"prefix{s8}",  # 哨兵作后缀
        f"x{s2}y{_s(tag, 4)}z",  # 多级夹文本
        f"{tok}_RAW]]",  # token+RAW 尾拼合边界
        f"[{tok}]",  # 括号外溢
        f"{tok[:-1]}",  # 残形 `[[SL]`——非 token 原样透传
        _sd(tag, "0"),  # 非规范 LIT0
        _sd(tag, "1"),  # 非规范 LIT1（level 2 的非规范形）
        _sd(tag, "007"),  # 前导零
        _sd(tag, "99999999"),  # 超高位——稀疏迭代不吃（旧码 ~1e8 空转）
        f"[[__TEXLATE_XX_LIT__]]{s2}",  # 异 tag 哨兵 + 本 tag 哨兵
        f"{s2}[[__TEXLATE_SL_LIT_]]",  # 单下划线尾——非哨兵
        f"{s2}[[__TEXLATE_SL_LIT]]",  # 缺 __——非哨兵
        f"{s2}[[_TEXLATE_SL_LIT__]]",  # 单下划线头——非哨兵
    ]


class TestFamilyRoundTrip:
    """``_unescape_family(_escape_family(s)) == s``——单族闭链恒等。"""

    @pytest.mark.parametrize("tag", _TAGS)
    def test_adversarial_round_trip(self, tag: str) -> None:
        for s in _adversarial_inputs(tag):
            assert _une(_esc(s, tag), tag) == s, (tag, s, _esc(s, tag))

    @pytest.mark.parametrize("tag", _TAGS)
    @pytest.mark.parametrize("level", [2, 3, 4, 5, 6, 7, 8, 20])
    def test_each_level_round_trip(self, tag: str, level: int) -> None:
        s = f"pre{_s(tag, level)}mid{_s(tag, level)}post"
        assert _une(_esc(s, tag), tag) == s

    @pytest.mark.parametrize("tag", _TAGS)
    def test_double_escape_round_trip(self, tag: str) -> None:
        """``unescape∘escape`` 对任意输入（含已编码形）皆恒等——
        ``unescape²∘escape²`` 随之成立。"""
        for s in _adversarial_inputs(tag):
            once = _esc(s, tag)
            assert _une(_esc(once, tag), tag) == once
            assert _une(_une(_esc(once, tag), tag), tag) == s

    @pytest.mark.parametrize("tag", _TAGS)
    def test_involution_invariant(self, tag: str) -> None:
        """``unescape∘escape∘unescape∘escape == unescape∘escape``——
        round-trip 恒等的直接推论，钉死防回退。"""
        for s in _adversarial_inputs(tag):
            ue = _une(_esc(s, tag), tag)
            assert _une(_esc(ue, tag), tag) == ue


class TestLevelMonotonicity:
    """级单调性：在册 k 级字面 escape 后恰升到 k+1，unescape 降回。"""

    @pytest.mark.parametrize("tag", _TAGS)
    @pytest.mark.parametrize("level", [2, 3, 5, 8])
    def test_single_sentinel_bumps_one(self, tag: str, level: int) -> None:
        s = f"x{_s(tag, level)}y"
        assert _esc(s, tag) == f"x{_s(tag, level + 1)}y"
        assert _une(_s(tag, level + 1), tag) == _s(tag, level)

    @pytest.mark.parametrize("tag", _TAGS)
    def test_max_level_shifts_by_one(self, tag: str) -> None:
        """混合在册集的各级恰各升一档（后缀 = level-1:3/5/8 级 → "2"/"4"/"7"）。"""
        text = f"{_s(tag, 2)}{_s(tag, 4)}{_s(tag, 7)}"
        out = _esc(text, tag)
        assert _ds(out, tag) == ["2", "4", "7"]

    def test_tok_raw_chain_positions(self) -> None:
        """token→RAW、RAW→sent(2)——链底两级各升一档（SL 族钉值）。"""
        tok, raw = _FAM["SL"]
        out = _esc(f"{tok}{raw}", "SL")
        assert out == f"{raw}{_s('SL', 2)}"
        assert _une(out, "SL") == f"{tok}{raw}"

    def test_raw_alone_becomes_sent2(self) -> None:
        _, raw = _FAM["PL"]
        assert _esc(f"a{raw}b", "PL") == f"a{_s('PL', 2)}b"

    def test_tok_alone_becomes_raw(self) -> None:
        tok, raw = _FAM["SP"]
        assert _esc(f"a{tok}b", "SP") == f"a{raw}b"


class TestOrderingPins:
    """升降序依赖——钉死 naive 序的双吃缺陷面。"""

    def test_escape_bumps_high_first(self) -> None:
        """sent(2)+sent(3) 共存须各升一档得 sent(3)+sent(4)；
        低位先升会把新产出 sent(3) 二次吃掉（得 LIT3+LIT3）。"""
        s = f"x{_s('SL', 2)}y{_s('SL', 3)}z"
        assert _esc(s, "SL") == f"x{_s('SL', 3)}y{_s('SL', 4)}z"

    def test_unescape_lowers_low_first(self) -> None:
        """sent(3)+sent(4) 共存须各降一档得 sent(2)+sent(3)；
        高位先降会把产出 sent(3) 二次降（得 LIT+LIT）。"""
        s = f"x{_s('SL', 3)}y{_s('SL', 4)}z"
        assert _une(s, "SL") == f"x{_s('SL', 2)}y{_s('SL', 3)}z"

    def test_escape_tail_raw_before_tok(self) -> None:
        """RAW→sent(2) 先于 token→RAW——反序会把新产出 RAW 二吃。"""
        tok, raw = _FAM["SL"]
        assert _esc(f"{raw}A{tok}", "SL") == f"{_s('SL', 2)}A{raw}"

    def test_unescape_head_tok_before_sent2(self) -> None:
        """RAW→token 先于 sent(2)→RAW——反序会把新产出 RAW 降成 token。"""
        tok, raw = _FAM["SL"]
        assert _une(f"{raw}A{_s('SL', 2)}", "SL") == f"{tok}A{raw}"

    def test_dense_ladder_all_levels(self) -> None:
        """2..8 级全在册——每级恰移一档（序列平移不重叠）。"""
        levels = [2, 3, 4, 5, 6, 7, 8]
        s = "|".join(_s("SL", lv) for lv in levels)
        assert _esc(s, "SL") == "|".join(_s("SL", lv + 1) for lv in levels)
        assert _une(_esc(s, "SL"), "SL") == s


class TestCrossFamilyIsolation:
    """跨族零污染——族 A 的升降链不触族 B 任何形态。"""

    @pytest.mark.parametrize(
        ("src_tag", "other_tag"),
        [(a, b) for a in _TAGS for b in _TAGS if a != b],
    )
    def test_family_blind_to_others(self, src_tag: str, other_tag: str) -> None:
        otok, oraw = _FAM[other_tag]
        foreign = f"{otok}{oraw}{_s(other_tag, 2)}{_s(other_tag, 5)}"
        s = f"pre{foreign}post"
        assert _esc(s, src_tag) == s
        assert _une(s, src_tag) == s

    def test_sentinel_names_never_substring(self) -> None:
        """八族 token/RAW/sentinel 名两两不为子串——升降链互盲的根基。"""
        names: list[str] = []
        for tag, tok, raw, _lit in ph._ALL_FAM:  # noqa: SLF001 -- 白盒钉族表
            names += [tok, raw, _s(tag, 2), _s(tag, 3), _s(tag, 9)]
        for i, a in enumerate(names):
            for j, b in enumerate(names):
                if i != j:
                    assert a not in b, (a, b)

    def test_mixed_family_codec_round_trip(self) -> None:
        """编解码层全族混合源——字面/token/脆弱间距/真换行同现。"""
        src = (
            "[[SL]][[SL_RAW]][[__TEXLATE_SL_LIT__]][[__TEXLATE_SL_LIT5__]]"
            "[[SP]][[SP_RAW]][[__TEXLATE_SP_LIT3__]]"
            "[[NBSP]][[THINSP_RAW]]~\\ \\,\\:\\;\\!\n\n\n"
        )
        enc, _ = ph.encode_newlines(src)
        assert ph.decode_newlines(enc) == src


class TestCodecRoundTrip:
    """``decode_newlines(encode_newlines(x))`` 公开 API 闭链。"""

    @pytest.mark.parametrize(
        "src",
        [
            "",
            "plain",
            "\n",
            "\n\n",
            "\n\n\n\n\n\n\n",  # 7 连
            "a\nb\n\nc\n\n\nd",
            "a\r\nb\rc",
            "a\r\n\r\nb",  # CRLF 对 → PL
            "[[SL]]",
            "[[SL]]\n",
            "\n[[SL]]",
            "[[SL]][[SL]]",
            "[[SL]][[SL_RAW]][[__TEXLATE_SL_LIT__]][[__TEXLATE_SL_LIT2__]]",
            "[[SL]]_RAW]]",  # 拼合边界——只吃到 `[[SL]]`
            "[[[SL]]]",  # 括号外溢——内层 `[[SL]]` 是 token
            "[[SL",  # 残形
            "[[PL]]\n\n[[PL_RAW]]",
            "~",
            "\\ ",
            "\\,",
            "\\:",
            "\\;",
            "\\!",
            "~\\ \\,\\:\\;\\!",
            "[[SP]]\\ ",
            "\\ [[SP]]",  # 字面 token + 真 lit 邻接
            "[[SP_RAW]][[__TEXLATE_SP_LIT__]]~",
            "[[NBSP]]x[[THINSP]]y[[NEGSP_RAW]]",
            "[[ENV_3]] [RS80] [[MATH_1]]",  # 带号占位符不涉本链
            "中文 [[SL]] 混排\n换行",
            "% comment [[SL]]\nbody",  # 注释区字面同样转义（mask 是 diff 侧事）
        ],
    )
    def test_round_trip(self, src: str) -> None:
        enc, _ = ph.encode_newlines(src)
        assert ph.decode_newlines(enc) == _norm(src)

    @pytest.mark.parametrize("k", range(1, 8))
    def test_newline_run_exact_form(self, k: int) -> None:
        """k 连换行 = ``[[PL]]``×(k//2)+``[[SL]]``×(k%2)——逐 k 钉编码形。"""
        enc, counts = ph.encode_newlines("a" + "\n" * k + "b")
        want = f"a{ph.PARA_NEWLINE * (k // 2)}{ph.SOFT_NEWLINE * (k % 2)}b"
        assert enc == want
        assert counts == {"source_sl": k % 2, "source_pl": k // 2}

    def test_encoded_output_has_no_newline(self) -> None:
        enc, _ = ph.encode_newlines("a\nb\n\nc\rd\r\ne")
        assert "\n" not in enc
        assert "\r" not in enc

    def test_counts_ignore_escaped_literals(self) -> None:
        """字面 ``[[SL]]``/``[[PL]]`` 不进 source_sl/pl——只计真换行。"""
        _, counts = ph.encode_newlines("[[SL]][[PL]]x\n")
        assert counts == {"source_sl": 1, "source_pl": 0}

    def test_literal_chain_encodes_to_sentinel(self) -> None:
        """字面 ``[[SL_RAW]]`` 编码成哨兵上链——wire 上是 LIT 形不是 RAW。"""
        enc, _ = ph.encode_newlines("a[[SL_RAW]]b")
        assert enc == "a[[__TEXLATE_SL_LIT__]]b"
        assert ph.decode_newlines(enc) == "a[[SL_RAW]]b"

    def test_double_codec_round_trip(self) -> None:
        """``decode²∘encode²`` 恒等——对已编码文本再编码再两降不丢。"""
        src = "x[[SL]]\n[[SP_RAW]]\\ y[[__TEXLATE_SL_LIT4__]]"
        enc1, _ = ph.encode_newlines(src)
        enc2, _ = ph.encode_newlines(enc1)
        assert ph.decode_newlines(ph.decode_newlines(enc2)) == src

    def test_decode_eats_bare_tokens(self) -> None:
        """decode 对未编码文本裸 token 是吞吃的——转义存在的理由，钉语义。"""
        assert ph.decode_newlines("a[[SL]]b") == "a\nb"
        assert ph.decode_newlines("a[[PL]]b") == "a\n\nb"
        assert ph.decode_newlines("a[[SP]]b") == "a\\ b"
        assert ph.decode_newlines("a[[NBSP]]b") == "a~b"

    def test_decode_raw_lowers_to_tok(self) -> None:
        """decode 对裸 RAW 形降一档成 token（未编码文本的链底语义）。"""
        assert ph.decode_newlines("a[[SL_RAW]]b") == "a[[SL]]b"
        assert ph.decode_newlines("a[[SP_RAW]]b") == "a[[SP]]b"

    def test_wire_sentinels_invisible_to_ph(self) -> None:
        """哨兵名不匹配 ``ANY_PH_RX``——wire 上 ``[[__TEXLATE_*_LITn__]]``
        对占位符对账不可见（既有 wire 形态语义，钉死防回退）。"""
        enc, _ = ph.encode_newlines("a[[SL_RAW]]b")
        assert enc == "a[[__TEXLATE_SL_LIT__]]b"
        assert ph.find_all(enc) == []

    def test_wire_raw_forms_are_bare_ph(self) -> None:
        """RAW 形 ``[[SL_RAW]]`` 命中 ``BARE_PH_RX``——字面 token 编码后
        在对账面仍按裸标记计。"""
        enc, _ = ph.encode_newlines("a[[SL]]b")
        assert enc == "a[[SL_RAW]]b"
        assert ph.find_all(enc) == ["[[SL_RAW]]"]


class TestNonCanonicalPassThrough:
    """非规范哨兵形——``_SENT_RX`` 命中但升降链不吃，双向原样透传。"""

    @pytest.mark.parametrize(
        "d",
        [
            "0",  # level 界下
            "1",  # level 2 的非规范形
            "00",
            "007",
            "00000001",
        ],
    )
    @pytest.mark.parametrize("tag", ["SL", "SP"])
    def test_noncanonical_round_trip(self, tag: str, d: str) -> None:
        s = f"x{_sd(tag, d)}y"
        assert _esc(s, tag) == s
        assert _une(s, tag) == s
        enc, _ = ph.encode_newlines(s)
        assert ph.decode_newlines(enc) == s

    def test_mixed_canonical_and_noncanonical(self) -> None:
        """规范/非规范同现——规范升降、非规范透传互不串。"""
        s = f"{_sd('SL', '007')}{_s('SL', 2)}{_sd('SL', '0')}"
        assert _une(_esc(s, "SL"), "SL") == s

    def test_wrong_tag_sentinel_passes(self) -> None:
        """``_SENT_RX`` 不命中的似哨兵形——所有族都原样透传。"""
        s = "a[[__TEXLATE_XX_LIT__]]b[[__TEXLATE_SL_LITX__]]c"
        enc, _ = ph.encode_newlines(s)
        assert ph.decode_newlines(enc) == s


class TestDefectRegressions:
    """两条已修缺陷的回归钉——重现体保留在测试体内。"""

    def test_huge_suffix_no_int_overflow(self) -> None:
        """D1：``LIT{9×5000}`` 曾 ``int(d)`` 触 4300 位限 ValueError 炸链；
        稀疏 d 串迭代无 int——任意长后缀字面无损 round-trip。"""
        s = "x" + _sd("SL", "9" * 5000) + "y"
        enc, _ = ph.encode_newlines(s)
        assert ph.decode_newlines(enc) == s
        assert _esc(s, "SL") == s.replace("LIT" + "9" * 5000, "LIT1" + "0" * 5000)

    def test_high_level_sparse_iteration(self) -> None:
        """D2：``LIT99999999``（level 1e8）曾撑开 ~1e8 次空转 replace
        （40B 输入 ~26s）；在册级迭代只吃命中级——升一档得 LIT100000000。"""
        s = f"a{_sd('SL', '99999999')}b"
        out = _esc(s, "SL")
        assert out == f"a{_sd('SL', '100000000')}b"
        assert _une(out, "SL") == s
        assert _ds(s, "SL") == ["99999999"]


#: fuzz 原子表——哨兵各级/token/RAW/非规范形/脆弱字面/换行/括号碎片/正文噪声。
_FUZZ_ATOMS = (
    "word",
    "TEXT",
    "x y",
    "中文段落",
    "\\cite{a}",
    "$e=mc^2$",
    "%cmt\n",
    "[[ENV_3]]",
    "[RS80]",
    "[[MATH_1]]",
    "\\textbf{b}",
    "[[SL]]",
    "[[SL_RAW]]",
    "[[PL]]",
    "[[PL_RAW]]",
    "[[SP]]",
    "[[SP_RAW]]",
    "[[NBSP]]",
    "[[NBSP_RAW]]",
    "[[THINSP]]",
    "[[MEDSP]]",
    "[[THICKSP]]",
    "[[NEGSP]]",
    "[[NEGSP_RAW]]",
    "~",
    "\\ ",
    "\\,",
    "\\:",
    "\\;",
    "\\!",
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
    "[[SL",
    "SL]]",
    "[[",
    "]]",
    "[[[SL]]]",
    "[[SL]]_RAW]]",
    "[[__TEXLATE_SL_LIT__]]",
    "[[__TEXLATE_SL_LIT2__]]",
    "[[__TEXLATE_SL_LIT5__]]",
    "[[__TEXLATE_PL_LIT3__]]",
    "[[__TEXLATE_SP_LIT__]]",
    "[[__TEXLATE_SP_LIT9__]]",
    "[[__TEXLATE_NBSP_LIT2__]]",
    "[[__TEXLATE_NEGSP_LIT7__]]",
    "[[__TEXLATE_SL_LIT0__]]",
    "[[__TEXLATE_SL_LIT1__]]",
    "[[__TEXLATE_SL_LIT007__]]",
    "[[__TEXLATE_XX_LIT__]]",
    "[[__TEXLATE_SL_LIT_]]",
    "[[__TEXLATE_SL_LIT]]",
)


class TestFuzzRoundTrip:
    """种子化 fuzz——哨兵原子/token/脆弱间距/换行/噪声随机拼接 round-trip。"""

    def _soup(self, rng: random.Random, n: int) -> str:
        return "".join(rng.choice(_FUZZ_ATOMS) for _ in range(n))

    def test_codec_round_trip_300(self) -> None:
        rng = fuzz_rng(20260917)
        for i in range(300):
            s = self._soup(rng, rng.randint(0, 25))
            enc, _ = ph.encode_newlines(s)
            dec = ph.decode_newlines(enc)
            assert dec == _norm(s), (i, s, enc, dec)

    def test_family_round_trip_300(self) -> None:
        rng = fuzz_rng(20260918)
        for i in range(300):
            s = self._soup(rng, rng.randint(0, 20))
            for tag in _TAGS:
                out = _une(_esc(s, tag), tag)
                assert out == s, (i, tag, s, _esc(s, tag), out)

    def test_double_encode_fuzz(self) -> None:
        rng = fuzz_rng(20260919)
        for i in range(200):
            s = self._soup(rng, rng.randint(0, 20))
            enc1, _ = ph.encode_newlines(s)
            enc2, _ = ph.encode_newlines(enc1)
            dec = ph.decode_newlines(ph.decode_newlines(enc2))
            assert dec == _norm(s), (i, s, enc1, enc2, dec)

    def test_encode_output_charset_fuzz(self) -> None:
        """编码产物无裸 ``\\n``/``\\r``、无 ``\\ `` 等脆弱字面残留。"""
        rng = fuzz_rng(20260920)
        fragile = ("\\ ", "~", "\\,", "\\:", "\\;", "\\!")
        for _ in range(200):
            s = self._soup(rng, rng.randint(0, 20))
            enc, _ = ph.encode_newlines(s)
            assert "\n" not in enc
            assert "\r" not in enc
            for lit in fragile:
                assert lit not in enc, (lit, s, enc)

    def test_ascii_noise_fuzz(self) -> None:
        """纯 ASCII 噪声串（含 ``[]_LIT`` 高集字符）——闭链恒等。"""
        rng = fuzz_rng(20260921)
        alpha = string.ascii_letters + string.digits + "[]_ \n\t\\~,;:!" + "TEXLATISP"
        for i in range(200):
            s = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 80)))
            enc, _ = ph.encode_newlines(s)
            assert ph.decode_newlines(enc) == _norm(s), (i, s, enc)
            for tag in ("SL", "SP", "NEGSP"):
                assert _une(_esc(s, tag), tag) == s, (i, tag, s)

    def test_bracket_soup_fuzz(self) -> None:
        """括号汤——``[``/``]``/合法 token 碎片高密拼接。"""
        rng = fuzz_rng(20260922)
        atoms = [
            "[",
            "]",
            "[[",
            "]]",
            "SL",
            "RAW",
            "LIT",
            "_",
            "TEXLATE",
            "0",
            "9",
            "[[SL]]",
            "[[SL_RAW]]",
            "[[__TEXLATE_SL_LIT__]]",
            "[[__TEXLATE_SL_LIT3__]]",
        ]
        for i in range(200):
            s = "".join(rng.choice(atoms) for _ in range(rng.randint(0, 30)))
            enc, _ = ph.encode_newlines(s)
            assert ph.decode_newlines(enc) == s, (i, s, enc)
            for tag in _TAGS:
                assert _une(_esc(s, tag), tag) == s, (i, tag, s)

    def test_sentinel_run_fuzz(self) -> None:
        """纯哨兵梯——多族多级规范哨兵连排 + 乱序穿插。"""
        rng = fuzz_rng(20260923)
        for i in range(200):
            parts = []
            for _ in range(rng.randint(1, 12)):
                tag = rng.choice(_TAGS)
                tok, raw = _FAM[tag]
                choices = [
                    tok,
                    raw,
                    _s(tag, rng.randint(2, 9)),
                    _sd(tag, rng.choice(["0", "1", "007"])),
                ]
                parts.append(rng.choice(choices))
            s = "|".join(parts)
            enc, _ = ph.encode_newlines(s)
            assert ph.decode_newlines(enc) == s, (i, s, enc)
            for tag in _TAGS:
                assert _une(_esc(s, tag), tag) == s, (i, tag, s)


class TestRegexBoundary:
    """``_SENT_RX`` 边界——钉 regex 命中/不命中的分界，防扫描面漂移。"""

    @pytest.mark.parametrize(
        "s",
        [
            "[[__TEXLATE_SL_LIT__]]",
            "[[__TEXLATE_SL_LIT0__]]",
            "[[__TEXLATE_SL_LIT99999__]]",
            "[[__TEXLATE_NEGSP_LIT42__]]",
        ],
    )
    def test_rx_matches(self, s: str) -> None:
        assert ph._SENT_RX[re.match(r"\[\[__TEXLATE_([A-Z]+)_", s).group(1)].search(s)  # noqa: SLF001

    @pytest.mark.parametrize(
        ("tag", "s"),
        [
            ("SL", "[[__TEXLATE_SL_LIT_]]"),  # 单下划线尾
            ("SL", "[[__TEXLATE_SL_LIT]]"),  # 缺尾 __
            ("SL", "[[_TEXLATE_SL_LIT__]]"),  # 单下划线头
            ("SL", "[[__TEXLATE_SL_LITX__]]"),  # 非数字后缀
            ("SL", "[[__TEXLATE_SL_LIT1_5__]]"),  # 内嵌下划线
            ("SL", "[[__TEXLATE_PL_LIT__]]"),  # 异 tag
            ("SL", "[[__TEXLATE_SL_LIT__]"),  # 缺尾 ]
            ("SL", "[__TEXLATE_SL_LIT__]]"),  # 缺头 [
        ],
    )
    def test_rx_rejects(self, tag: str, s: str) -> None:
        assert not ph._SENT_RX[tag].search(s)  # noqa: SLF001 -- 白盒钉扫描器
