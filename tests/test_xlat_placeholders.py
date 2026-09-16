"""placeholders：换行编码 round-trip / 占位符对账 / 恒等排序 / recover_copied_tokens。"""

from texlate.xlat import placeholders as ph


class TestNewlineCodec:
    def test_round_trip_simple(self) -> None:
        src = "line one\nline two\nline three"
        enc, counts = ph.encode_newlines(src)
        assert enc == "line one[[SL]]line two[[SL]]line three"
        assert counts == {"source_sl": 2, "source_pl": 0}
        assert ph.decode_newlines(enc) == src

    def test_para_breaks(self) -> None:
        src = "para one\n\n\npara two"
        enc, counts = ph.encode_newlines(src)
        assert "[[PL]]" in enc
        assert counts["source_pl"] == 1
        assert ph.decode_newlines(enc) == src

    def test_crlf_normalized(self) -> None:
        src = "a\r\nb\rc"
        enc, _ = ph.encode_newlines(src)
        assert enc == "a[[SL]]b[[SL]]c"

    def test_literal_sl_collision(self) -> None:
        """源文本自带字面 [[SL]] 时不与编码 token 碰撞（两级转义）。"""
        src = "literal [[SL]] here\nreal break"
        enc, _ = ph.encode_newlines(src)
        # 字面 [[SL]] → [[SL_RAW]]，真换行 → [[SL]]
        assert enc == "literal [[SL_RAW]] here[[SL]]real break"
        assert ph.decode_newlines(enc) == src

    def test_literal_sl_raw_collision(self) -> None:
        """源文本自带 [[SL_RAW]] 也不能被还原错。"""
        src = "has [[SL_RAW]] literal"
        enc, _ = ph.encode_newlines(src)
        assert "[[SL_RAW]]" not in enc or "LIT" in enc
        assert ph.decode_newlines(enc) == src

    def test_decode_unknown_markers_pass_through(self) -> None:
        assert ph.decode_newlines("a[[MATH_1]]b") == "a[[MATH_1]]b"

    def test_fragile_space_masked(self) -> None:
        r"""`\ ` 脆弱间距 → ``[[SP]]`` 占位符（吃 C9 保护契约），decode 还原。"""
        src = "cf.\\ [[MATH_1]] holds,\ni.e.\\ too"
        enc, _ = ph.encode_newlines(src)
        assert enc == "cf.[[SP]][[MATH_1]] holds,[[SL]]i.e.[[SP]]too"
        assert ph.decode_newlines(enc) == src

    def test_literal_sp_collision(self) -> None:
        """源文本自带字面 ``[[SP]]``/``[[SP_RAW]]`` 走两级转义不碰撞。"""
        src = "literal [[SP]] and [[SP_RAW]] plus\\ real"
        enc, _ = ph.encode_newlines(src)
        assert "\\ " not in enc.replace("[[SP_RAW]]", "")
        assert ph.decode_newlines(enc) == src

    def test_double_backslash_space(self) -> None:
        r"""``\\ ``（换行命令+空格）内的 ``\ `` 子串——编码后仍无损 round-trip。"""
        src = "line\\\\ broken\nnext"
        enc, _ = ph.encode_newlines(src)
        assert ph.decode_newlines(enc) == src

    def test_space_family_encoded(self) -> None:
        r"""空白族扩列 (realpostfix2 E22 实证): ``~``/``\,``/``\:``/``\;``/``\!`` 各占一 token。"""
        src = "Fig.~1, thin\\, med\\: thick\\; neg\\! end"
        enc, _ = ph.encode_newlines(src)
        assert enc == (
            "Fig.[[NBSP]]1, thin[[THINSP]] med[[MEDSP]] "
            "thick[[THICKSP]] neg[[NEGSP]] end"
        )
        assert ph.decode_newlines(enc) == src

    def test_space_family_literal_collision(self) -> None:
        """源文本自带字面 ``[[NBSP]]``/``[[THINSP_RAW]]`` 走两级转义不碰撞。"""
        src = "literal [[NBSP]] and [[THINSP_RAW]] plus~x\\,y"
        enc, _ = ph.encode_newlines(src)
        assert "[[NBSP_RAW]]" in enc
        assert ph.decode_newlines(enc) == src

    def test_space_family_double_backslash(self) -> None:
        r"""``\\,`` 内的 ``\,`` 子串——编码后仍无损 round-trip（``\``+``\,`` 字节级重合）。"""
        src = "line\\\\, cont\\\\; next"
        enc, _ = ph.encode_newlines(src)
        assert ph.decode_newlines(enc) == src

    def test_space_family_diff_counts_missing(self) -> None:
        """模型丢 ``[[NBSP]]`` 计 missing——E22 丢号正是本族要拦的形态。"""
        d = ph.diff("Fig.[[NBSP]]1", "图[[MATH_0]]1")
        assert d.missing == ["[[NBSP]]"]


class TestFindAllAndSort:
    def test_typed_and_bare(self) -> None:
        text = "a [[MATH_2]] b [[CITE_1]] c [[SL]] d"
        assert ph.find_all(text) == ["[[MATH_2]]", "[[CITE_1]]", "[[SL]]"]

    def test_sort_key_order(self) -> None:
        phs = ["[[MATH_12]]", "[[CITE_3]]", "[[MATH_2]]", "[[SL]]", "[[AUTHOR_1]]"]
        assert sorted(phs, key=ph.sort_key) == [
            "[[AUTHOR_1]]",
            "[[CITE_3]]",
            "[[MATH_2]]",
            "[[MATH_12]]",
            "[[SL]]",
        ]

    def test_is_placeholder_only(self) -> None:
        assert ph.is_placeholder_only("[[MATH_1]]")
        assert ph.is_placeholder_only("  [[ENV_3]] [[MATH_1]]  ")
        assert not ph.is_placeholder_only("text [[MATH_1]]")
        assert not ph.is_placeholder_only("")


class TestDiff:
    def test_clean(self) -> None:
        src = "a [[MATH_1]] b [[CITE_2]]"
        zh = "甲 [[MATH_1]] 乙 [[CITE_2]]"
        d = ph.diff(src, zh)
        assert d.ok

    def test_missing(self) -> None:
        d = ph.diff("a [[MATH_1]]", "甲")
        assert d.missing == ["[[MATH_1]]"]
        assert "missing placeholder: [[MATH_1]]" in d.describe()

    def test_extra(self) -> None:
        d = ph.diff("a", "甲 [[MATH_9]]")
        assert d.extra == ["[[MATH_9]]"]

    def test_misspelled_lev2(self) -> None:
        """[[MATH_1]] → [MATH_1] 单层括号化是 lev=2 模糊候选，进 misspelled。"""
        d = ph.diff("x [[MATH_1]] y", "x [MATH_1] y")
        assert not d.missing
        assert d.misspelled == [("[MATH_1]", "[[MATH_1]]")]

    def test_cjk_bracket_variant_is_extra(self) -> None:
        """【MATH_1】 全角化 lev=4 超阈值——不报拼错，报多余（L0 同口径）。"""
        d = ph.diff("x [[MATH_1]] y", "x 【MATH_1】 y")
        assert d.missing == ["[[MATH_1]]"]
        assert d.extra == ["【MATH_1】"]

    def test_multiplicity(self) -> None:
        d = ph.diff("[[MATH_1]] [[MATH_1]]", "[[MATH_1]]")
        assert d.missing == ["[[MATH_1]]"]

    def test_bare_marker_diff(self) -> None:
        d = ph.diff("a[[SL]]b", "ab")
        assert d.missing == ["[[SL]]"]

    def test_comment_masked(self) -> None:
        """zh 注释里的占位符不计入（与 L0 豁免口径一致）。"""
        d = ph.diff("a [[MATH_1]]", "a % [[MATH_1]] in comment")
        assert d.missing == ["[[MATH_1]]"]


class TestRecoverCopiedTokens:
    def test_exact_unique_replaced(self) -> None:
        ph_map = {"[[MATH_1]]": "$x+y$", "[[CITE_2]]": "\\cite{foo}"}
        zh = "当 $x+y$ 成立时见 \\cite{foo}"
        out, recovered = ph.recover_copied_tokens(zh, ph_map)
        assert out == "当 [[MATH_1]] 成立时见 [[CITE_2]]"
        assert sorted(recovered) == ["[[CITE_2]]", "[[MATH_1]]"]

    def test_not_unique_not_touched(self) -> None:
        ph_map = {"[[MATH_1]]": "$x$"}
        zh = "$x$ and $x$ both"  # 出现两次——不瞎猜
        out, recovered = ph.recover_copied_tokens(zh, ph_map)
        assert out == zh
        assert recovered == []

    def test_present_ph_skipped(self) -> None:
        ph_map = {"[[MATH_1]]": "$x$"}
        zh = "[[MATH_1]] plus $x$"
        out, recovered = ph.recover_copied_tokens(zh, ph_map)
        assert out == zh
        assert recovered == []

    def test_substring_fragment_shadows_longer(self) -> None:
        """`$x$` 是 `$$x$$` 子串——长 fragment 必须先认领，否则短者把

        长者的副本啃成 `$[[MATH_1]]$`，display 公式永远失配。
        """
        ph_map = {"[[MATH_1]]": "$x$", "[[MATH_2]]": "$$x$$"}
        zh = "译文里公式 $$x$$ 保留原样"
        out, recovered = ph.recover_copied_tokens(zh, ph_map)
        assert out == "译文里公式 [[MATH_2]] 保留原样"
        assert recovered == ["[[MATH_2]]"]


def test_collect_doc_placeholders_stable_order() -> None:
    docs = ["b [[MATH_10]] [[SL]]", "a [[CITE_1]] [[MATH_2]]"]
    out = ph.collect_doc_placeholders(docs)
    assert out == ["[[CITE_1]]", "[[MATH_2]]", "[[MATH_10]]", "[[SL]]"]
