"""batch：装箱边界 / 编号协议解析 / @@ 兜底 / 整批退单翻信号 / 超大块切分。"""

from texlate.xlat import batch


class TestPackBatches:
    def test_empty(self) -> None:
        assert batch.pack_batches([]) == []

    def test_single_oversized_gets_own_batch(self) -> None:
        # 单块 ~2000 字符（含编号开销超 cap）独占一批；小块另批
        out = batch.pack_batches(["x" * 1995, "a", "b"], max_chars=2000)
        assert out == [[0], [1, 2]]

    def test_boundary_exact_fit(self) -> None:
        # 两块各 ~1004（含开销）：合计 2008 > cap → 不合并
        out = batch.pack_batches(["x" * 996, "y" * 996], max_chars=2000)
        assert out == [[0], [1]]

    def test_equal_sized_fill(self) -> None:
        # total=2490 → n_req=2、target=1245：[0,1] 封批，末批吞余量
        out = batch.pack_batches(["x" * 490] * 5, max_chars=2000)
        assert out == [[0, 1], [2, 3, 4]]

    def test_hard_cap_overrides_target(self) -> None:
        # 末批也不得超 cap：1908+108>2000 → [1] 单独封批
        out = batch.pack_batches(["a" * 100, "b" * 1900, "c" * 100], max_chars=2000)
        assert out == [[0], [1], [2]]

    def test_max_items_cap(self) -> None:
        out = batch.pack_batches(["x" * 10] * 5, max_chars=10**9, max_items=2)
        assert out == [[0, 1], [2, 3], [4]]

    def test_workers_inflates_request_count(self) -> None:
        # total≈8×1000：workers=10 → 并行填充拆到 ~min_chars/批 的多批
        out = batch.pack_batches(
            ["x" * 1000] * 8, max_chars=20000, min_chars=2000, workers=10
        )
        assert len(out) == 4  # noqa: PLR2004 -- total 8064//2000=4 批、每批 ~2 块
        assert all(len(g) == 2 for g in out)  # noqa: PLR2004 -- 每批 2 块即断言义

    def test_workers_k_quantized(self) -> None:
        # n_req>workers 时向上取 workers 倍数：40×3758 total≈150K、cap→13 批、
        # K=10 → 取 20 批等大（每批 2 块），不留 10+3 半空波次
        out = batch.pack_batches(
            ["x" * 3750] * 40, max_chars=12000, min_chars=2500, workers=10
        )
        assert len(out) == 20  # noqa: PLR2004 -- K=10 取 20 批等大即断言义
        assert all(len(g) == 2 for g in out)  # noqa: PLR2004 -- 每批 2 块即断言义

    def test_tiny_group_stays_one_batch(self) -> None:
        # total<min_chars 不硬凑 workers——一个小批胜过 N 个微型请求
        out = batch.pack_batches(
            ["a", "b", "c"], max_chars=12000, min_chars=2500, workers=10
        )
        assert out == [[0, 1, 2]]


class TestEncodeParse:
    def test_encode_numbered(self) -> None:
        text = batch.encode_batch(["hello world", "second\nline"])
        assert text == "[1] hello world\n[2] second[[SL]]line"

    def test_parse_numbered(self) -> None:
        raw = "[1] 你好\n[2] 世界 [[MATH_1]]"
        out = batch.parse_batch_response(raw, 2)
        assert out == ["你好", "世界 [[MATH_1]]"]

    def test_parse_out_of_order(self) -> None:
        raw = "[2] second piece\n[1] first piece"
        out = batch.parse_batch_response(raw, 2)
        assert out == ["first piece", "second piece"]

    def test_parse_wrong_count_falls_to_atat(self) -> None:
        raw = "译文甲\n@@\n译文乙\n@@\n译文丙"
        out = batch.parse_batch_response(raw, 3)
        assert out == ["译文甲", "译文乙", "译文丙"]

    def test_parse_failure_returns_none(self) -> None:
        assert batch.parse_batch_response("[1] only one", 2) is None
        assert batch.parse_batch_response("no markers at all", 3) is None
        assert batch.parse_batch_response("", 1) is None

    def test_parse_missing_index_none(self) -> None:
        # [1] [3] 缺 [2] —— 序号集不齐 → 退
        assert batch.parse_batch_response("[1] a\n[3] c", 3) is None

    def test_parse_out_of_range_none(self) -> None:
        # 序号越界 [9] → 退
        assert batch.parse_batch_response("[1] a\n[9] x", 2) is None

    def test_parse_index_reuse_none(self) -> None:
        # [1] [1] [2] 重复 → 序号集 != {1,2} → 退
        assert batch.parse_batch_response("[1] a\n[1] dup\n[2] b", 2) is None

    def test_empty_section_fails(self) -> None:
        assert batch.parse_batch_response("[1] a\n[2] \n[3] c", 3) is None

    def test_parse_ignores_inline_citation_brackets(self) -> None:
        """译文正文里的 ``[12]`` 引用号不得被当成员分隔符（行首锚定优先）。"""
        raw = "[1] 参见 [12] 的研究\n[2] 结果表明 [3,4] 一致"
        out = batch.parse_batch_response(raw, 2)
        assert out == ["参见 [12] 的研究", "结果表明 [3,4] 一致"]

    def test_parse_single_line_squeezed_rejected(self) -> None:
        """单行全挤（``[1] a [2] b``）与引用陷阱 token 层不可分——整批拒收。"""
        raw = "[1] 第一段 [2] 第二段 [3] 第三段"
        out = batch.parse_batch_response(raw, 3)
        assert out is None

    def test_atat_fallback_drops_bare_ordinal_stub(self) -> None:
        """``@@`` 兜底把裸 ``[n]`` 序号桩当空槽——``[1]`` 回显不得漏成译文。"""
        # n=1 整块批的退化回显：编号路径段空 → @@ 兜底不得收下裸桩
        assert batch.parse_batch_response("[1]", 1) is None
        # 全桩 / 半桩都按空槽计 → 段数不足 → 整批 None 退单翻
        assert batch.parse_batch_response("[1]\n@@\n[2]", 2) is None
        assert batch.parse_batch_response("译文甲\n@@\n[2]", 2) is None

    def test_atat_fallback_stub_salvage(self) -> None:
        """桩段是碎片不是槽位：丢弃后幸存段恰 ``n`` 个仍收下。"""
        assert batch.parse_batch_response("[2]\n@@\n译文", 1) == ["译文"]

    def test_atat_fallback_citation_brackets_kept(self) -> None:
        """译文正文含 ``[12]`` 引用号不是桩——``fullmatch`` 只罩纯桩段。"""
        raw = "参见 [12] 研究\n@@\n译文乙"
        assert batch.parse_batch_response(raw, 2) == ["参见 [12] 研究", "译文乙"]


class TestSplitLongChunk:
    def test_short_passthrough(self) -> None:
        assert batch.split_long_chunk("short text") == ["short text"]

    def test_splits_at_sentence_boundary(self) -> None:
        limit = 400
        src = ("Sentence one here. " * 100).strip()  # ~1900 chars
        parts = batch.split_long_chunk(src, max_chars=limit)
        assert len(parts) >= len(src) // limit
        assert all(len(p) <= limit for p in parts)
        assert "".join(parts) == src
        # 每片以句号结尾（除末片）
        for p in parts[:-1]:
            assert p.rstrip().endswith(".")

    def test_abbrev_guard_keeps_fig_2(self) -> None:
        """``Fig.`` 缩写尾点不切（E24 sentence-split-abbrev）——碎头/半截句进批。"""
        src = "aaaa Fig. 2 bbbb. cccc " * 40
        parts = batch.split_long_chunk(src, max_chars=100)
        assert "".join(parts) == src
        for p in parts:
            assert not p.rstrip().endswith("Fig.")
            if "Fig." in p:
                assert "Fig. 2" in p

    def test_abbrev_guard_eg_al(self) -> None:
        """``e.g.``/``et al.`` 含点尾词同款不切；真句尾照常断。"""
        src = "results e.g. these hold. " * 30 + "et al. found results. " * 10
        parts = batch.split_long_chunk(src, max_chars=80)
        assert "".join(parts) == src
        for p in parts[:-1]:
            tail = p.rstrip()
            assert not tail.endswith("e.g.")
            assert not tail.endswith("al.")

    def test_no_split_inside_braces(self) -> None:
        # 句号在 {} 内不切
        src = "\\cmd{Period. inside braces} " + "Tail sentence. " * 50
        parts = batch.split_long_chunk(src, max_chars=300)
        assert all(
            "\\cmd{Period. inside braces}" in p or "{Period." not in p for p in parts
        )
        assert len(parts) > 1

    def test_hard_fallback(self) -> None:
        limit = 1000
        src = "x" * (limit * 5)  # 无句号无空格 → 硬切
        parts = batch.split_long_chunk(src, max_chars=limit)
        assert len(parts) == len(src) // limit
        assert "".join(parts) == src

    def test_never_cuts_inside_placeholder(self) -> None:
        """硬切点落在 ``[[MATH_1]]`` 内部 → 退到 token 头（两半都过不了对账）。"""
        src = "a" * 95 + "[[MATH_1]]" + "b" * 50  # token 跨 95..105, 硬切 100
        parts = batch.split_long_chunk(src, max_chars=100)
        assert "".join(parts) == src
        assert parts[0] == "a" * 95
        assert parts[1].startswith("[[MATH_1]]")

    def test_never_cuts_inside_control_word(self) -> None:
        r"""硬切点落在 ``\foo`` 内部 → 退到 ``\`` 前（防 ``\``+CJK 熔合成新 cs）。"""
        src = "a" * 97 + "\\foo" + "b" * 50  # \foo 跨 97..101, 硬切 100
        parts = batch.split_long_chunk(src, max_chars=100)
        assert "".join(parts) == src
        assert parts[0] == "a" * 97
        assert parts[1].startswith("\\foo")

    def test_zero_or_negative_limit_returns_unsplit(self) -> None:
        """max_chars<1 曾死循环（_best_split 切出 cut=0 → rest 不变）——原样返回胜过挂死。"""
        src = "abcdef" * 100
        assert batch.split_long_chunk(src, max_chars=0) == [src]
        assert batch.split_long_chunk(src, max_chars=-5) == [src]
