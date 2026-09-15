"""batch：装箱边界 / 编号协议解析 / @@ 兜底 / 整批退单翻信号 / 超大块切分。"""

from texlate.xlat import batch


class TestPackBatches:
    def test_empty(self) -> None:
        assert batch.pack_batches([]) == []

    def test_single_oversized_gets_own_batch(self) -> None:
        # 单块 ~2000 字符（含编号开销超限）独占一批；小块另批
        out = batch.pack_batches(["x" * 1995, "a", "b"])
        assert out == [[0], [1, 2]]

    def test_boundary_exact_fit(self) -> None:
        # 两块各 ~996：996+8=1004，两块 2008 > 2000 → 不合并
        out = batch.pack_batches(["x" * 996, "y" * 996])
        assert out == [[0], [1]]

    def test_greedy_fill(self) -> None:
        # 4×490 → 490+8=498 ×4 = 1992 ≤ 2000 → 同批；加第 5 块则溢出
        out = batch.pack_batches(["x" * 490] * 5)
        assert out == [[0, 1, 2, 3], [4]]

    def test_order_preserved(self) -> None:
        out = batch.pack_batches(["a" * 100, "b" * 1900, "c" * 100])
        assert out == [[0], [1], [2]]


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
