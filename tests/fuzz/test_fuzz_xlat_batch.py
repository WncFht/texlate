"""xlat batch 路径对抗性契约测试——batch.py 协议 + retry.py 槽位批臂 + pipeline 批量编排。

与 ``test_fuzz_xlat.py`` 的分工：那边是广撒网不变量（装箱划分 / 编解码往返 /
垃圾输入只回 ``None`` / 编排对账 / 续跑）；本文件逐条钉「标记归属」语义——
``[n]`` 行首锚定 vs ``@@`` 兜底的优先级与泄漏面、槽位过滤
``_valid_slot_text`` 逃逸形态、批内部分失败→单块回炉的请求形态与记账字段。
每条断言注释都注明观测语义（observed semantics）。

已修复的缺陷级语义（断言已翻转为修复后行为，留档备查）：

- 单行非锚定退路错配（was CONFIRMED wrong-attribution，``batch.py:36`` +
  ``batch.py:102``）：模型把整批挤在一行且正文 ``[n]`` 引用号恰好凑齐
  ``{1..n}`` 多重集时，``_NUM_RX`` 无法区分协议编号与引用号 → 静默错配。
  修复：非锚定编号解析整体撤除——单行/行内 ``[k]`` 与引用号在 token 层
  不可区分，任何含 ``[k]`` 的非锚定响应都按歧义整批拒收退单翻；
- ``@@`` 兜底原样泄漏（was ``batch.py:106-110``）：编号解析失败后 ``@@``
  段不剥 ``[n]`` 序号字面，标记原文进译文；``@@`` 行本身在编号路径里也按
  字面保留在段内。修复：``@@`` 段内非嵌套 ``[k]``（1≤k≤n）判协议残码
  → 整批拒收；编号段内 ``@@`` 独占行按协议残码剥除；
- ``[[n]]`` 字面腐蚀（was ``batch.py:36``）：行首锚定不吃 ``[[``，非锚定
  却匹配内层 ``[n]`` → 产出 ``]`` 残渣段。修复：随非锚定路径一并消失，
  ``[[k]]`` 属占位符族字面按内容放行；
- ``_valid_slot_text`` 非规范槽形逃逸（was ``retry.py:44``/``retry.py:214``）：
  ``⟪S1⟫``（<4 位）/``⟪s0000⟫``（小写）/``⟪S0000``（未闭合）全部放行。
  修复：``⟪⟫[[ ]]`` 括号字符任一出现即拒，罩住全部非规范残码形。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable

import pytest
from _fuzzkit import RecordingTranslator, fuzz_rng

from texlate.xlat import batch as xb
from texlate.xlat import pipeline as xp
from texlate.xlat import placeholders as ph
from texlate.xlat import retry as rt
from texlate.xlat.client import AuthError, ChatError, RetryableHTTPError
from texlate.xlat.mock import MockTranslator

# ---------------------------------------------------------------- 私有面薄封装

_vst = rt._valid_slot_text  # noqa: SLF001 -- 私有契约正是被测面
_make_slots = rt._make_slots  # noqa: SLF001
_assemble = rt._assemble_slots  # noqa: SLF001
_slots_round = rt._slots_round  # noqa: SLF001
_stub_rx = ph.STUB_ONLY_RX

_FUZZ_MED = 1500

_SlotsFn = Callable[[dict[str, str], str], Awaitable[dict[str, str]]]


class _SlotCtx:
    """``_slots_round`` 的最小伪 ctx——该方法只触 ``attempts``/``slots_fn``。"""

    def __init__(self, slots_fn: _SlotsFn) -> None:
        self.attempts = 0
        self.slots_fn = slots_fn


def _group_recorder(sink: list[list[str]]) -> _SlotsFn:
    """录下每次调用的组键序并全答 ``zh`` 的 slots_fn。"""

    async def fn(group: dict[str, str], _fb: str) -> dict[str, str]:
        sink.append(list(group))
        return dict.fromkeys(group, "zh")

    return fn


class _T(RecordingTranslator):
    """录制型 translator：``batch_fn`` 处理 ``[1]`` 起头的批请求，其余走 ``single_fn``。

    所有入参入账供断言（system 区分 batch 变体、rf 区分 slots 请求）；``batch_fn``
    抛异常时原样穿透（错误注入用）。``response_format`` 请求无 slots 短路——
    与正文同走批/独员路由（本臂语义即无 rf 特判）。
    """

    def __init__(
        self,
        batch_fn: Callable[[str], str],
        single_fn: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(slots_fill=None, batch_fn=batch_fn, single_fn=single_fn)


def _cfg(**kw: object) -> xp.PipelineConfig:
    """批路径全命中配置：batch 2000 / 串行（workers=1 关掉 min_chars 并行放大）。"""
    args: dict[str, object] = {
        "concurrency": 1,
        "batch_max_chars": 2000,
    }
    args.update(kw)
    return xp.PipelineConfig(**args)  # type: ignore[arg-type]


def _run(
    chunks: list[xp.ChunkIn],
    t: _T,
    validator: Callable[[str, str], str] | None = None,
) -> list[xp.ChunkResult]:
    return asyncio.run(
        xp.XlatPipeline(t, config=_cfg(), validator=validator).run(chunks)
    )


# ---------------------------------------------------------------- encode_batch 请求构造


class TestEncodeBatch:
    def test_one_based_numbering_and_order(self) -> None:
        # observed: 1 基序号、成员序==行序、行间单 \n、不产 [0]
        out = xb.encode_batch(["alpha", "beta", "gamma"])
        assert out == "[1] alpha\n[2] beta\n[3] gamma"
        assert "[0]" not in out

    def test_per_member_newline_codec(self) -> None:
        # observed: 每成员独立过 encode_newlines——\n→[[SL]]、\n\n→[[PL]]、~→[[NBSP]]；
        # ph 成员序号行内嵌 ``keep:`` 名单点名保真集（v6 批协议）
        out = xb.encode_batch(["a\nb", "c\n\nd", "x~y"])
        assert out == (
            "[1] keep: [[SL]] | a[[SL]]b\n"
            "[2] keep: [[PL]] | c[[PL]]d\n"
            "[3] keep: [[NBSP]] | x[[NBSP]]y"
        )

    def test_member_literal_ph_escaped(self) -> None:
        # observed: 成员字面 [[SL]] 升级 [[SL_RAW]]——编码面不产裸换行也不碰撞
        # token；[[SL_RAW]] 匹配类型化占位符形 → keep 名单照点
        out = xb.encode_batch(["lit [[SL]] here"])
        assert out == "[1] keep: [[SL_RAW]] | lit [[SL_RAW]] here"

    def test_empty_member_emits_marker_only_line(self) -> None:
        # observed: 空成员 → ``[k] `` 裸行（响应侧 strip 成空段 → 整批解析失败）
        assert xb.encode_batch(["", "x"]) == "[1] \n[2] x"

    def test_member_starting_with_marker_stays_inline(self) -> None:
        # observed: 成员内容自带 ``[n]`` 只作行内文本——行首仍是真序号 ``[k]``
        out = xb.encode_batch(["[2] starts with marker", "normal"])
        assert out == "[1] [2] starts with marker\n[2] normal"

    def test_empty_input(self) -> None:
        assert xb.encode_batch([]) == ""


# ---------------------------------------------------------------- pack_batches 边界


class TestPackBatches:
    def test_exact_fit_boundary(self) -> None:
        # observed: cur_len+need == max_chars 不溢出（判定是 > 不是 >=）
        out = xb.pack_batches(["x" * 992], max_chars=1000, item_overhead=8)
        assert out == [[0]]
        out2 = xb.pack_batches(["x" * 492, "y" * 492], max_chars=1000, item_overhead=8)
        assert out2 == [[0, 1]]

    def test_zero_max_chars_one_per_batch(self) -> None:
        # observed: max_chars=0 时每成员独占一批（need>0 恒溢出，cur 空仍 append）
        assert xb.pack_batches(["a", "b", "c"], max_chars=0) == [[0], [1], [2]]

    def test_zero_overhead(self) -> None:
        # observed: item_overhead=0 → need=len(text)，边界按裸长度算
        out = xb.pack_batches(["x" * 5, "y" * 5], max_chars=10, item_overhead=0)
        assert out == [[0, 1]]

    def test_fuzz_overhead_partition_oracle(self) -> None:
        """随机 (max_chars, overhead)：保序划分 + 硬帽不超（等大填充由单元钉）。"""
        rng = fuzz_rng(20261201)
        for _ in range(_FUZZ_MED):
            contents = ["x" * rng.randint(0, 300) for _ in range(rng.randint(0, 20))]
            max_chars = rng.choice([1, 8, 50, 300, 2000])
            ov = rng.choice([0, 1, 8, 40])
            groups = xb.pack_batches(contents, max_chars=max_chars, item_overhead=ov)
            assert [i for g in groups for i in g] == list(range(len(contents)))
            for g in groups:
                assert len(g) <= xb.BATCH_MAX_ITEMS
                total = sum(len(contents[i]) + ov for i in g)
                # 多成员组不得超字符帽（独员组允许独超）
                assert total <= max_chars or len(g) == 1


# ---------------------------------------------------------------- parse 行首锚定路径


class TestParseAnchored:
    def test_reorder_remaps_to_member_position(self) -> None:
        # observed: 乱序序号按文本位置切段、按编号归位——成员归属正确
        out = xb.parse_batch_response("[2] second\n[1] first\n[3] third", 3)
        assert out == ["first", "second", "third"]

    def test_preamble_silently_dropped(self) -> None:
        # observed: 首个标记前的文本整体丢弃——不报错不拼接
        assert xb.parse_batch_response("junk preamble\n[1] a\n[2] b", 2) == ["a", "b"]

    def test_trailing_junk_glued_to_last_member(self) -> None:
        # observed: 末标记之后的无标文本并入最后一段——成员 n 多出一截
        out = xb.parse_batch_response("[1] a\n[2] b\ntrailing junk", 2)
        assert out == ["a", "b\ntrailing junk"]

    def test_section_raw_newlines_kept(self) -> None:
        # observed: 段内裸换行原样保留（模型不经 [[SL]] 的多行输出按字面收）
        out = xb.parse_batch_response("[1] line1\ncontinued\n[2] x", 2)
        assert out == ["line1\ncontinued", "x"]

    def test_atat_line_inside_numbered_section_stripped(self) -> None:
        # observed: ``@@`` 独占行在编号段内按协议残码剥除——它是兜底分隔符
        # 不是译文内容，保留即字面泄漏进 PDF
        out = xb.parse_batch_response("[1] a\n@@\n[2] b", 2)
        assert out == ["a", "b"]
        # 剥除后段空 → 整批拒收（成员实质空译，歧义不可救）
        assert xb.parse_batch_response("[1] @@\n[2] b", 2) is None

    def test_indented_and_tabbed_markers_consumed(self) -> None:
        # observed: ``^\s*`` 吃行首空白——缩进/Tab/空行前置的 [n] 仍是标记
        assert xb.parse_batch_response("[1] a\n   [2] b", 2) == ["a", "b"]
        assert xb.parse_batch_response("[1] a\n\t[2] b", 2) == ["a", "b"]
        assert xb.parse_batch_response("[1] a\n\n\n[2] b", 2) == ["a", "b"]

    def test_crlf_tolerated(self) -> None:
        # observed: \r\n 行尾落进前段被 strip 清掉，标记照常锚定
        assert xb.parse_batch_response("[1] a\r\n[2] b", 2) == ["a", "b"]

    def test_u2028_normalized_to_anchored(self) -> None:
        # observed: \u2028/\u2029/\r 等行界先归一成 \n——标记走行首锚定路径
        out = xb.parse_batch_response("[1] a [2] b", 2)
        assert out == ["a", "b"]

    def test_unclosed_bracket_glues(self) -> None:
        # observed: 无 ``]`` 闭合的 ``[``/``[3`` 不是标记——并入前段字面
        assert xb.parse_batch_response("[1] a\n[2] b [", 2) == ["a", "b ["]
        assert xb.parse_batch_response("[1] a\n[2] b\n[3", 2) == ["a", "b\n[3"]

    def test_marker_like_forms_stay_content(self) -> None:
        # observed: ``[1a]``/``[-1]`` 不命中 ``\[\d+\]``——留作段内字面
        out = xb.parse_batch_response("[1] a\n[1a] x\n[2] b", 2)
        assert out == ["a\n[1a] x", "b"]
        out2 = xb.parse_batch_response("[1] a\n[-1] x\n[2] b", 2)
        assert out2 == ["a\n[-1] x", "b"]


# ---------------------------------------------------------------- parse 严格多重集


class TestParseMultiset:
    """序号多重集须恰为 {1..n}——任何不齐都整批 None，绝不部分回收。"""

    def test_duplicate_marker_fails_whole(self) -> None:
        # observed: 重复序号 → 多重集 ≠ → None（不去重不取先）
        assert xb.parse_batch_response("[1] a\n[1] dup\n[2] b", 2) is None

    def test_zero_marker_fails_whole(self) -> None:
        # observed: [0] 越界 → None（[0] 在场其他合法段也不回收）
        assert xb.parse_batch_response("[0] z\n[1] a\n[2] b", 2) is None

    def test_marker_beyond_range_fails_whole(self) -> None:
        # observed: 多出 [3] → None——即使 [1][2] 两段完好
        assert xb.parse_batch_response("[1] a\n[2] b\n[3] c", 2) is None

    def test_missing_marker_fails_whole(self) -> None:
        # observed: 缺 [2] → None——不救 [1]/[3]
        assert xb.parse_batch_response("[1] a\n[3] c", 3) is None

    def test_citation_at_line_start_kills_batch(self) -> None:
        # observed: 段内行首 ``[12]`` 被当标记 → 多重集炸 → 整批退单翻。
        # 行首引用号是真实译文形态——一个引用行烧掉整批（安全方向但成本高）
        assert xb.parse_batch_response("[1] a\n[12] cite\n[2] b", 2) is None
        assert xb.parse_batch_response("[1] a\n[12] cite\n[2] b", 12) is None

    def test_empty_section_fails_whole(self) -> None:
        # observed: 任一空段（含纯空白）→ all() 假 → 整批 None
        assert xb.parse_batch_response("[1] a\n[2]\n[3] c", 3) is None
        assert xb.parse_batch_response("[1] a\n[2]   \n[3] c", 3) is None

    def test_spaced_markers_not_markers(self) -> None:
        # observed: ``[2 ]``/``[ 2]`` 不命中两种编号正则 → 多重集缺 → None
        assert xb.parse_batch_response("[1] a\n[2 ] b", 2) is None
        assert xb.parse_batch_response("[1] a\n[ 2] b", 2) is None

    def test_leading_zero_accepted(self) -> None:
        # observed: ``[01]`` int→1 按合法序号收
        assert xb.parse_batch_response("[01] a\n[2] b", 2) == ["a", "b"]

    def test_unicode_digits_accepted(self) -> None:
        # observed: ``\d``+``int()`` 通吃 Unicode 十进制——全角数字也是标记
        assert xb.parse_batch_response("[１] a\n[２] b", 2) == ["a", "b"]

    def test_huge_marker_no_crash(self) -> None:
        # observed: 60 位巨号 int() 正常、多重集炸 → None
        assert xb.parse_batch_response("[1] a\n[" + "9" * 60 + "] b", 2) is None

    def test_empty_and_nonpositive_n(self) -> None:
        # observed: 空文本/空白文本/n≤0 → None
        assert xb.parse_batch_response("", 1) is None
        assert xb.parse_batch_response("   \n  ", 2) is None
        assert xb.parse_batch_response("[1] a", 0) is None
        assert xb.parse_batch_response("[1] a", -1) is None


# ---------------------------------------------------------------- 行内 [n]（歧义拒收面）


class TestParseNonAnchored:
    """非锚定编号解析已撤除——行内 ``[k]`` 与正文引用号 token 层不可区分。

    任何含 ``[k]`` 的非锚定响应一律整批 ``None`` 退单翻：宁可烧调用也不
    可静默错配/截断进 PDF。
    """

    def test_single_line_squeezed_rejected(self) -> None:
        # observed: 单行 ``[1] a [2] b`` 不再按编号切——``[2]`` 可能是引用号
        # 也可能是挤行分隔符，结构不可区分 → 歧义拒收
        assert xb.parse_batch_response("[1] first [2] second", 2) is None

    def test_single_line_citation_misattribution(self) -> None:
        """was CONFIRMED wrong-attribution——修复后整批 None。

        模型单行输出、成员 2 实际缺失、成员 1 译文自带 ``[2]`` 引用号凑齐
        多重集 → 旧码把引用残段配给成员 2。修复后行内 ``[n]`` 不解析，
        响应经 ``@@`` 兜底仍含 ``[k]``(k∈{1..n}) 判协议泄漏 → 整批拒收。
        """
        assert xb.parse_batch_response("[1] 结果如文献 [2] 所示成立", 2) is None
        # n=3 同款：一条译文两个引用号凑齐 {1,2,3}
        assert xb.parse_batch_response("[1] ref [2] and [3] here", 3) is None

    def test_inline_marker_with_head_rejected(self) -> None:
        # observed: n=1 行内 ``[1]``——头文本是序言还是成员内容/``[1]`` 是
        # 序号还是引用号不可区分 → 歧义拒收（退单翻重译即得正确译文）
        assert xb.parse_batch_response("x [1] y", 1) is None
        assert xb.parse_batch_response("参见文献 [1] 可知成立", 1) is None

    def test_double_bracket_no_corruption(self) -> None:
        # observed(was PLAUSIBLE 缺陷): ``[[n]]`` 行首锚定不吃，非锚定曾吃
        # 内层 ``[n]`` 产 ``]`` 残渣——非锚定撤除后腐蚀面消失
        assert xb.parse_batch_response("[[1]] a\n[[2]] b", 2) is None
        # ``[[1]]`` 非序号形态（占位符族字面）：n=1 无协议歧义 → 原文收下
        assert xb.parse_batch_response("x [[1]] y", 1) == ["x [[1]] y"]

    def test_atat_guard_rejects_leaked_markers(self) -> None:
        # observed: ``@@`` 段内非嵌套 ``[k]``(k∈{1..n}) = 协议残码/引用号
        # 歧义 → 整批拒收（was: 非锚定先行切走、``@@`` 行字面落段）
        assert xb.parse_batch_response("x [1] p [2] q\n@@\nz", 2) is None


# ---------------------------------------------------------------- parse keep 回显剥除


class TestParseKeepEcho:
    """``keep:`` 名单回显按协议残码剥除——名单是元数据不是译文。

    实测回显率≈0（keep-roster-and-values-truncation-2026-09-29），剥除是
    防 ``diff`` 同集漏检的保险：名单与成员 ph 天然同集，残留 ``keep:``
    行可能多重集相等静默放行。
    """

    def test_keep_echo_own_line_stripped(self) -> None:
        # observed: 名单镜像回段首独占行——剥除后取正文
        out = xb.parse_batch_response(
            "[1] keep: [[MATH_1]] [[CITE_2]]\n译文 [[MATH_1]] [[CITE_2]]\n[2] 乙",
            2,
        )
        assert out == ["译文 [[MATH_1]] [[CITE_2]]", "乙"]

    def test_keep_echo_inline_pipe_stripped(self) -> None:
        # observed: `keep: ids |` 内联镜像（与请求同形）——名单+分隔符剥除
        out = xb.parse_batch_response("[1] keep: [[NBSP]] | 译文正文~尾\n[2] 乙", 2)
        assert out == ["译文正文~尾", "乙"]

    def test_keep_echo_inline_no_pipe_stripped(self) -> None:
        # observed: 名单回显不带 ``|`` 也剥——模型丢分隔符不挡名单剥除
        out = xb.parse_batch_response("[1] keep: [[MATH_1]] 译文甲\n[2] 乙", 2)
        assert out == ["译文甲", "乙"]

    def test_keep_echo_only_member_kills_batch(self) -> None:
        # observed: 名单独占段（回显后零译文）→ 整批 None 退单翻——
        # 名单 ph 多重集与成员同集，留下非空会骗过 diff 漏成译文
        assert xb.parse_batch_response("[1] keep: [[MATH_1]]\n[2] 乙", 2) is None
        assert xb.parse_batch_response("[1] keep: [[MATH_1]] |\n[2] 乙", 2) is None

    def test_keep_echo_in_atat_sections(self) -> None:
        # observed: ``@@`` 兜底段首同款剥除
        out = xb.parse_batch_response("keep: [[MATH_1]]\n译文甲\n@@\n乙", 2)
        assert out == ["译文甲", "乙"]
        # 独占段 → 段数不足 → None
        assert xb.parse_batch_response("keep: [[MATH_1]]\n@@\n乙", 2) is None

    def test_member_content_leading_keep_text_kept(self) -> None:
        # observed: 段首 ``keep:`` 后无 ph token 列不是名单——按内容收
        out = xb.parse_batch_response("[1] keep: the result\n[2] 乙", 2)
        assert out == ["keep: the result", "乙"]

    def test_mock_translator_swallows_keep_roster(self) -> None:
        # observed: mock 应答不回显名单——真实线发请求形态下批往返仍过
        user = xb.encode_batch(["see [[MATH_1]] now", "plain text"])
        assert "keep:" in user  # 前提：真实请求面含名单前缀
        out = asyncio.run(
            MockTranslator().translate(
                system="", user=user, temperature=0.0, max_tokens=8192
            )
        )
        assert "keep:" not in out
        parts = xb.parse_batch_response(out, 2)
        assert parts is not None
        assert "[[MATH_1]]" in parts[0]


# ---------------------------------------------------------------- bare_token_audit NBSP 宽容


class TestBareTokenAudit:
    """八族 token 多重集对账 + ``_BENIGN_MISS_TOKENS`` 丢失向宽容。"""

    def test_missing_nbsp_forgiven(self) -> None:
        # observed: [[NBSP]] 丢失（in>out）赦免——decode 后只少 ``~``
        # 是良性排版伤；夜跑唯一存活失败类、对一切 keep 变体免疫
        assert rt.bare_token_audit("a[[NBSP]]b", "译文") == ""
        assert rt.bare_token_audit("a[[NBSP]]b[[NBSP]]c", "译[[NBSP]]文") == ""

    def test_extra_nbsp_hard_fail(self) -> None:
        # observed: 凭空铸 [[NBSP]]（in<out）仍硬败——锻造是幻觉标记
        err = rt.bare_token_audit("ab", "译[[NBSP]]文")
        assert "structural token multiset mismatch" in err
        assert "NBSP" in err

    def test_other_families_missing_hard_fail(self) -> None:
        # observed: 宽容只给 NBSP——[[SL]]/[[PL]] 同向丢失仍硬败
        assert "[[SL]]" in rt.bare_token_audit("a[[SL]]b", "译文")
        assert "[[PL]]" in rt.bare_token_audit("a[[PL]]b", "译文")


# ---------------------------------------------------------------- per-member 开销记账


class TestMemberOverhead:
    def test_batch_member_overhead_counts_keep(self) -> None:
        # observed: ph-free 恒 BATCH_ITEM_OVERHEAD；ph 成员加 keep 前缀实长
        assert xb.batch_member_overhead("plain text") == xb.BATCH_ITEM_OVERHEAD
        text = "a~b"
        enc = ph.encode_newlines(text)[0]
        keep = f"keep: {' '.join(ph.find_all(enc))} | "
        assert xb.batch_member_overhead(text) == xb.BATCH_ITEM_OVERHEAD + len(keep)

    def test_overheads_per_item_replaces_default(self) -> None:
        # observed: overheads 逐项顶替 item_overhead——keep 头长计入容量
        assert xb.pack_batches(["x" * 5, "y" * 5], max_chars=20, overheads=[9, 9]) == [
            [0],
            [1],
        ]
        assert xb.pack_batches(["x" * 5, "y" * 5], max_chars=20, overheads=[4, 4]) == [
            [0, 1]
        ]
        with pytest.raises(ValueError, match="overheads len"):
            xb.pack_batches(["a"], overheads=[1, 2])


# ---------------------------------------------------------------- parse @@ 兜底


class TestParseAtAt:
    def test_n1_markerless_text_accepted(self) -> None:
        # observed: n=1 无标记非空文本经 ``@@`` 单段兜底原样收
        assert xb.parse_batch_response("just some text", 1) == ["just some text"]

    def test_atat_verbatim_marker_leak(self) -> None:
        """was ``@@`` 段不剥 ``[n]`` 字面标记原文进译文——修复后判泄漏拒收。"""
        # observed: 段内非嵌套 ``[k]``(k∈{1..n}) → 歧义整批 None
        assert xb.parse_batch_response("x [1] y [2] z", 1) is None
        assert xb.parse_batch_response("x [1] y\n@@\nz", 2) is None
        # k>n/[0]/[[k]] 非序号形态按内容放行——真引用号不受影响
        assert xb.parse_batch_response("x [5] y", 1) == ["x [5] y"]
        assert xb.parse_batch_response("见 [3] 文献\n@@\n乙", 2) == [
            "见 [3] 文献",
            "乙",
        ]
        assert xb.parse_batch_response("x [[1]] y", 1) == ["x [[1]] y"]

    def test_anchored_first_bracket_eats_rest(self) -> None:
        # observed: ``[1][2][3]`` 行首锚定吃首个 ``[1]``——余下字面并入该段
        # （``@@`` 独占行按协议残码剥除）
        out = xb.parse_batch_response("[1][2][3]\n@@\nreal", 1)
        assert out == ["[2][3]\nreal"]

    def test_atat_stub_drop_then_count(self) -> None:
        # observed: 裸 ``[n]`` 桩段先丢再数段——幸存段恰 n 仍收
        assert xb.parse_batch_response("[2]\n@@\nreal", 1) == ["real"]
        assert xb.parse_batch_response("[1]\n@@\n[2]", 2) is None
        assert xb.parse_batch_response("译文甲\n@@\n[2]", 2) is None

    def test_stub_rx_multi_stub(self) -> None:
        # observed: ``[1][2][3]``/``[1] [2]`` 连桩也按空槽丢
        assert _stub_rx.fullmatch("[1][2][3]")
        assert _stub_rx.fullmatch("[1] [2]")
        assert _stub_rx.fullmatch("  [2]  ")
        assert not _stub_rx.fullmatch("[1] x")
        assert not _stub_rx.fullmatch("[1a]")
        assert not _stub_rx.fullmatch("[]")

    def test_atat_section_count_mismatch(self) -> None:
        # observed: ``@@`` 段数 ≠ n → None（不部分回收）
        assert xb.parse_batch_response("a\n@@\nb\n@@\nc", 2) is None

    def test_atat_only_line_form(self) -> None:
        # observed: ``@@`` 判定要 ``^\s*@@\s*$`` 独占行——``a @@ b``/``@@ x``/
        # ``x@@`` 不切，原样留在段内
        assert xb.parse_batch_response("a @@ b", 1) == ["a @@ b"]
        out = xb.parse_batch_response("a\n@@ x\n@@\nb", 2)
        assert out == ["a\n@@ x", "b"]


# ---------------------------------------------------------------- 槽位臂 _valid_slot_text / _make_slots / _assemble


class TestValidSlotText:
    def test_contract_matrix(self) -> None:
        # observed: 非空 str + 无槽 token + 无占位符 token 才放行
        assert _vst("译文")
        assert _vst("trailing ok ")
        assert not _vst("")
        assert not _vst("   ")
        assert not _vst("\n")
        for bad in [None, 5, ["x"], {"k": "v"}]:
            assert not _vst(bad)

    def test_slot_token_forms_rejected(self) -> None:
        # observed: 规范 ``⟪S\d{4,}⟫`` 任何位置出现都拒
        assert not _vst("有 ⟪S0000⟫ 槽")
        assert not _vst("⟪S0001⟫")
        assert not _vst("⟪S12345⟫")
        assert not _vst("prefix⟪S9999⟫suffix")

    def test_ph_tokens_rejected(self) -> None:
        # observed: ANY_PH_RX 全形态（带号+裸标记）都拒
        assert not _vst("有 [[MATH_1]]")
        assert not _vst("[[SL]]")
        assert not _vst("[[MATH]]")

    def test_noncanonical_forms_rejected(self) -> None:
        """was PLAUSIBLE 缺陷：非规范槽形逃过滤——修复后括号字符出现即拒。"""
        # observed: <4 位数字/小写 s/未闭合/缺半边/小写占位符全拒
        # （``⟪⟫[[ ]]`` 任一出现 → 畸形 token 不放行进装配译文）
        assert not _vst("⟪S1⟫")
        assert not _vst("⟪S123⟫")
        assert not _vst("⟪s0000⟫")
        assert not _vst("⟪S0000")
        assert not _vst("S0000⟫")
        assert not _vst("[[math_1]]")
        assert not _vst("[[1]]")
        assert not _vst("x [[ y")
        assert not _vst("x ]] y")


class TestMakeSlots:
    def test_empty_and_pure_inputs(self) -> None:
        # observed: 空串 → 空槽空序；纯空白 → raw 项；纯占位符 → ph 项零槽
        assert _make_slots("") == ({}, [])
        assert _make_slots("   ") == ({}, [("raw", "   ")])
        assert _make_slots("[[MATH_1]]") == ({}, [("ph", "[[MATH_1]]")])

    def test_whitespace_in_slot_values(self) -> None:
        # observed: 槽散文保留边界空白；纯空白间隔降 raw 项
        slots, seq = _make_slots("a  [[MATH_1]]  b")
        assert slots == {"⟪S0000⟫": "a  ", "⟪S0001⟫": "  b"}
        assert [k for k, _p in seq] == ["slot", "ph", "slot"]
        _slots2, seq2 = _make_slots("a [[MATH_1]]  [[CITE_2]] b")
        assert ("raw", "  ") in seq2

    def test_sequential_ids(self) -> None:
        # observed: 槽号按产出序 ``⟪S%04d⟫`` 连续编号
        enc = " [[MATH_1]] ".join(f"prose{i}" for i in range(12))
        slots, _seq = _make_slots(enc)
        assert sorted(slots) == [f"⟪S{i:04d}⟫" for i in range(len(slots))]
        assert len(slots) == 12  # noqa: PLR2004 -- 12 段散文 12 槽


class TestAssembleSlots:
    def test_identity_oracle(self) -> None:
        # observed: 槽位按原文回填 → assemble(seq, identity) == decode(enc)
        for enc in [
            "alpha [[MATH_1]] beta [[CITE_2]] gamma",
            "a  [[MATH_1]]   b",
            "lead [[MATH_1]]",
            "[[MATH_1]] tail",
        ]:
            slots, seq = _make_slots(enc)
            assert _assemble(seq, dict(slots)) == ph.decode_newlines(enc)

    def test_fuzz_identity_oracle(self) -> None:
        """随机编码文本走 _make_slots→identity 装配 == decode_newlines。"""
        rng = fuzz_rng(20261202)
        soup = ["word ", "[[MATH_1]]", "[[CITE_2]]", "[[SL]]", " ", "x", " tail"]
        for _ in range(_FUZZ_MED):
            raw = "".join(rng.choice(soup) for _ in range(rng.randint(0, 15)))
            enc = ph.encode_newlines(raw)[0]
            slots, seq = _make_slots(enc)
            assert _assemble(seq, dict(slots)) == ph.decode_newlines(enc)

    def test_extra_keys_ignored(self) -> None:
        # observed: translated 里 seq 外的键不影响装配
        slots, seq = _make_slots("a [[MATH_1]]")
        out = _assemble(seq, {**slots, "⟪S9999⟫": "ghost"})
        assert out == ph.decode_newlines("a [[MATH_1]]")


# ---------------------------------------------------------------- 槽位批臂 _slots_round


class TestSlotsRound:
    def test_groups_of_eight_in_pending_order(self) -> None:
        # observed: pending 按插入序切 ≤8 组；attempts 按组计
        seen: list[list[str]] = []
        ctx = _SlotCtx(_group_recorder(seen))
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(20)}
        want = list(pending)
        translated: dict[str, str] = {}
        asyncio.run(_slots_round(ctx, pending, translated, {}))
        assert [len(g) for g in seen] == [8, 8, 4]
        assert ctx.attempts == 3  # noqa: PLR2004 -- 3 组 3 次
        # 拼接序 == pending 插入序——sorted() 会抹掉被测的次序语义
        assert [k for g in seen for k in g] == want
        assert sorted(translated) == want
        assert not pending

    def test_fuzz_group_partition_order(self) -> None:
        """随机 pending 规模：组大小 ≤8、连续切分、拼接序 == pending 插入序。"""
        rng = fuzz_rng(20261203)
        for _ in range(300):
            n = rng.randint(0, 30)
            groups: list[list[str]] = []
            ctx = _SlotCtx(_group_recorder(groups))
            pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(n)}
            want = list(pending)
            asyncio.run(_slots_round(ctx, pending, {}, {}))
            flat = [k for g in groups for k in g]
            assert flat == want  # 保序切组——拼接即原序
            assert all(len(g) <= 8 for g in groups)  # noqa: PLR2004 -- 8 槽/批
            tail = [n % 8] if n % 8 else []
            assert [len(g) for g in groups] == [8] * (n // 8) + tail

    def test_feedback_pipelines_within_round(self) -> None:
        # observed: 同轮内后组的 feedback 已含前组失败槽——失败 JSON 边问边攒
        calls: list[str] = []

        async def fn(group: dict[str, str], fb: str) -> dict[str, str]:
            calls.append(fb)
            return {k: ("bad [[MATH_1]]" if k == "⟪S0003⟫" else "zh") for k in group}

        ctx = _SlotCtx(fn)
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(10)}
        translated: dict[str, str] = {}
        asyncio.run(_slots_round(ctx, pending, translated, {}))
        assert calls[0] == ""  # 首组无 feedback
        assert json.loads(calls[1]) == {
            "⟪S0003⟫": "empty / non-string / contains slot or placeholder token"
        }
        assert sorted(pending) == ["⟪S0003⟫"]
        assert "⟪S0003⟫" not in translated

    def test_invalid_and_missing_answers(self) -> None:
        # observed: 非 dict 返回 → 全槽「empty/non-string」失败形态
        ctx = _SlotCtx(lambda _g, _f: asyncio.sleep(0, result=["not", "dict"]))
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(3)}
        failures: dict[str, str] = {}
        asyncio.run(_slots_round(ctx, pending, {}, failures))
        assert set(failures) == set(pending)
        assert all("empty" in v for v in failures.values())

    def test_exception_marks_no_answer(self) -> None:
        # observed: 非 ChatError 异常 → 整组「no answer」留 pending（下轮重问）

        async def boom(_g: dict[str, str], _f: str) -> dict[str, str]:
            msg = "kaboom"
            raise ValueError(msg)

        ctx = _SlotCtx(boom)
        pending = {f"⟪S{i:04d}⟫": f"p{i}" for i in range(3)}
        failures: dict[str, str] = {}
        asyncio.run(_slots_round(ctx, pending, {}, failures))
        assert set(failures) == set(pending)
        assert set(failures.values()) == {"no answer"}

    def test_chaterror_propagates(self) -> None:
        # observed: ChatError（认证等）不被槽位臂吞——直接穿透

        async def auth(_g: dict[str, str], _f: str) -> dict[str, str]:
            msg = "401"
            raise AuthError(msg, status=401)

        ctx = _SlotCtx(auth)
        pending = {"⟪S0000⟫": "p"}
        with pytest.raises(AuthError):
            asyncio.run(_slots_round(ctx, pending, {}, {}))


# ---------------------------------------------------------------- 阶梯槽位阶段


class TestStageSlots:
    async def _never(self, _t: str, _f: str) -> str:
        return "no placeholders here"

    def test_exhaustion_falls_back_orig(self) -> None:
        # observed: 失败槽两轮不补 → warning + fallback_orig（translation=原文）

        async def stubborn(slots: dict[str, str], _fb: str) -> dict[str, str]:
            return {k: ("" if k.endswith("0001⟫") else "槽译") for k in slots}

        res = asyncio.run(
            rt.translate_with_ladder(
                "Alpha text [[MATH_1]] omega text",
                translate_fn=self._never,
                slots_fn=stubborn,
            )
        )
        assert res.status == "fallback_orig"
        assert res.stage == "fallback"
        assert res.translation == "Alpha text [[MATH_1]] omega text"
        assert any("slots unanswered" in w for w in res.warnings)
        assert res.attempts == 4  # noqa: PLR2004 -- whole×2 + slots 两轮各 1 组

    def test_round_two_reasks_only_failed(self) -> None:
        # observed: 第二轮只重问 pending 槽、feedback 带失败 JSON
        seen: list[tuple[list[str], str]] = []

        async def flaky(slots: dict[str, str], fb: str) -> dict[str, str]:
            seen.append((sorted(slots), fb))
            if len(seen) == 1:
                return {k: ("" if k == "⟪S0001⟫" else "槽译") for k in slots}
            return dict.fromkeys(slots, "槽译")

        res = asyncio.run(
            rt.translate_with_ladder(
                "Alpha text [[MATH_1]] omega text",
                translate_fn=self._never,
                slots_fn=flaky,
            )
        )
        assert res.status == "recovered"
        assert res.stage == "slots"
        assert seen[1][0] == ["⟪S0001⟫"]  # 第二轮只含失败槽
        assert "⟪S0001⟫" in seen[1][1]

    def test_no_prose_slots_returns_none(self) -> None:
        # observed: 无散文可切（全占位符源）→ slots 阶段直接弃 → fallback_orig
        res = asyncio.run(
            rt.translate_with_ladder(
                "[[MATH_1]]",
                translate_fn=self._never,
                slots_fn=self._never,  # type: ignore[arg-type] -- 永不被调
            )
        )
        assert res.status == "fallback_orig"
        assert res.translation == "[[MATH_1]]"


# ---------------------------------------------------------------- pipeline 批量编排


class TestBuildWorkItems:
    def test_kind_grouped_batches_and_ordering(self) -> None:
        # observed: 全量装箱——批按 kind 分组不混装；独员组退化成 single
        # 与批按装箱序交错（不再批先单后）；seq 跨 kind 全局递增；
        # kind 组序 = pending 首见序
        p = xp.XlatPipeline(_T(lambda u: u), config=_cfg(batch_max_chars=60))
        pending = [
            xp.ChunkIn("s1", "a" * 50, "para"),  # 58>60 → 独占组 → single
            xp.ChunkIn("b1", "short1", "para"),
            xp.ChunkIn("b2", "cap1", "caption"),
            xp.ChunkIn("b3", "short2", "para"),
            xp.ChunkIn("b4", "cap2", "caption"),
        ]
        items = p._build_work_items(pending, [])  # noqa: SLF001
        kinds = [it[0] for it in items]
        assert kinds == ["single", "batch", "batch"]
        assert items[0][1].chunk_id == "s1"
        b0, b1 = items[1][1], items[2][1]
        assert b0[0] == 0
        assert [c.chunk_id for c in b0[1]] == ["b1", "b3"]
        assert b1[0] == 1
        assert [c.chunk_id for c in b1[1]] == ["b2", "b4"]

    def test_fuzz_kind_homogeneity(self) -> None:
        """随机 pending：批内 kind 恒同质、批 ≥2 成员、seq 连续、全体划分。"""
        rng = fuzz_rng(20261204)
        p = xp.XlatPipeline(_T(lambda u: u), config=_cfg(batch_max_chars=40))
        for _ in range(300):
            pending = [
                xp.ChunkIn(
                    f"c{i}",
                    "x" * rng.randint(1, 60),
                    rng.choice(["para", "caption", "abstract"]),
                )
                for i in range(rng.randint(1, 15))
            ]
            items = p._build_work_items(pending, [])  # noqa: SLF001
            seqs: list[int] = []
            covered: list[str] = []
            for k, payload in items:
                if k == "batch":
                    members = payload[1]
                    assert len(members) >= 2  # noqa: PLR2004 -- 独员组退化成 single 不落 batch
                    assert len({c.kind for c in members}) == 1
                    seqs.append(payload[0])
                    covered += [c.chunk_id for c in members]
                else:
                    assert k == "single"
                    covered.append(payload.chunk_id)
            assert seqs == list(range(len(seqs)))  # seq 全局连续
            assert sorted(covered) == sorted(c.chunk_id for c in pending)  # 全划分


class TestPipelineBatch:
    def test_request_payload_and_prompt_variant(self) -> None:
        # observed: user = encode_batch 原文；批请求不带 response_format
        # （对照 slots 请求的 json_object）
        t = _T(lambda u: u)
        chunks = [
            xp.ChunkIn("a", "first text", "para"),
            xp.ChunkIn("b", "second\nline", "para"),
        ]
        _run(chunks, t)
        assert t.calls[0]["user"] == (
            "[1] first text\n[2] keep: [[SL]] | second[[SL]]line"
        )
        assert t.calls[0]["rf"] is None

    def test_pure_ph_chunks_never_requested(self) -> None:
        # observed: is_placeholder_only 块零请求直落 ok + translation=原文逐字
        t = _T(lambda u: u)
        res = _run(
            [
                xp.ChunkIn("pure", "[[MATH_1]] [[CITE_2]]", "para"),
                xp.ChunkIn("purews", "  [[MATH_3]]  ", "para"),
                xp.ChunkIn("real", "some real text", "para"),
                xp.ChunkIn("real2", "more real text", "para"),
            ],
            t,
        )
        assert res[0].status == "ok"
        assert res[0].translation == "[[MATH_1]] [[CITE_2]]"
        assert res[0].attempts == 0
        assert not res[0].fell_back
        assert res[0].batch_id == ""
        assert not res[0].batched
        assert res[1].translation == "  [[MATH_3]]  "  # strip 判定、原文落盘
        assert [c["user"] for c in t.calls] == [
            "[1] some real text\n[2] more real text"
        ]

    def test_whitespace_member_poisons_batch_pipeline(self) -> None:
        # observed: 空白成员（非 ph-only）编码成 ``[k] `` 空段 → 整批解析失败
        # → 全员退单翻各烧一次调用（批 1 发 + N 单发）
        t = _T(lambda u: u, lambda u: f"zh {u}")
        res = _run(
            [
                xp.ChunkIn("m1", "   ", "para"),
                xp.ChunkIn("m2", "real member", "para"),
            ],
            t,
        )
        assert [r.batched for r in res] == [False, False]
        assert t.calls[0]["user"].startswith("[1]")
        assert sorted(c["user"] for c in t.calls[1:]) == ["   ", "real member"]

    def test_newline_only_member_batches_fine(self) -> None:
        # observed: 纯换行成员不是 ph-only、编码成 [[PL]] 正常进批往返
        t = _T(lambda u: u)
        res = _run(
            [
                xp.ChunkIn("nl", "\n\n", "para"),
                xp.ChunkIn("tail", "tail member", "para"),
            ],
            t,
        )
        assert res[0].status == "ok"
        assert res[0].batched
        assert res[0].translation == "\n\n"

    def test_parse_failure_degrades_all_to_singles(self) -> None:
        # observed: 解析失败 → 全员各自走单翻（无 [n] 包裹、非批 system），
        # batch_id 仍记 batch_0000、batched=False、attempts 只记单翻阶梯
        t = _T(lambda _u: "garbage no markers", lambda u: f"zh {u}")
        res = _run(
            [
                xp.ChunkIn("a", "ma", "para"),
                xp.ChunkIn("b", "mb", "para"),
                xp.ChunkIn("c", "mc", "para"),
            ],
            t,
        )
        assert [r.status for r in res] == ["ok"] * 3
        assert all(not r.batched for r in res)
        assert {r.batch_id for r in res} == {"batch_0000"}
        assert all(r.attempts == 1 for r in res)
        users = [c["user"] for c in t.calls]
        assert users[0].startswith("[1]")
        assert sorted(users[1:]) == ["ma", "mb", "mc"]

    def test_partial_validation_failure_reasks_only_failed(self) -> None:
        """批成功但该块校验败 → 只回炉失败成员，形态=裸编码单翻。"""

        # observed: member2 译文丢 [[CITE_2]] → 独走阶梯（user=原文无编号、
        # system 非批变体）；member1 保 batched=True/attempts=1
        def batch_reply(_u: str) -> str:
            return "[1] 译文一 [[MATH_1]]\n[2] 译文二丢了占位符"

        t = _T(batch_reply)
        res = _run(
            [
                xp.ChunkIn("a", "first text [[MATH_1]]", "para"),
                xp.ChunkIn("b", "second text [[CITE_2]]", "para"),
            ],
            t,
        )
        assert res[0].batched
        assert res[0].attempts == 1
        assert res[0].translation == "译文一 [[MATH_1]]"
        assert not res[1].batched
        assert res[1].batch_id == "batch_0000"
        assert len(t.calls) == 2  # noqa: PLR2004 -- 批 1 + 回炉 1
        assert t.calls[1]["user"] == "second text [[CITE_2]]"
        assert t.calls[1]["system"] != t.calls[0]["system"]  # 批/单 system 分体

    def test_retryable_error_degrades_all(self) -> None:
        # observed: retryable ChatError/裸崩 → 全员单翻；
        # non-retryable → 全 skip 连坐不再重发
        for exc, want_status, want_kind, extra_calls in [
            (RetryableHTTPError("b", status=500, retryable=True), "ok", "", 2),
            (ChatError("noauth", status=401, retryable=False), "skipped", "auth", 0),
            (RuntimeError("bare"), "ok", "", 2),
        ]:

            def boom(_u: str, _e: BaseException = exc) -> str:
                raise _e

            t = _T(boom)
            res = _run(
                [
                    xp.ChunkIn("m1", "member one", "para"),
                    xp.ChunkIn("m2", "member two", "para"),
                ],
                t,
            )
            assert [r.status for r in res] == [want_status] * 2
            assert all(r.error_kind == want_kind for r in res)
            assert len(t.calls) == 1 + extra_calls

    def test_strict_all_or_nothing_no_partial_salvage(self) -> None:
        # observed: 响应少一个标记 → 已有段不救，全员回炉
        t = _T(lambda _u: "[1] 一\n[2] 二", lambda u: f"zh {u}")
        res = _run(
            [xp.ChunkIn(c, f"m{c}", "para") for c in "abc"],
            t,
        )
        assert all(r.batched is False for r in res)
        assert len(t.calls) == 4  # noqa: PLR2004 -- 批 1 + 单 3

    def test_batch_marker_decode_applied(self) -> None:
        # observed: 段内 [[SL]] token 经 decode_newlines → 译文含真换行
        # （源带真换行使应答的 [[SL]] 成合法 echo——bare_token_audit 要求
        #   八族 token 多重集相等，无源 token 的 [[SL]] 属锻造必拒）
        t = _T(lambda _u: "[1] a[[SL]]b\n[2] c")
        res = _run(
            [xp.ChunkIn("a", "m\na", "para"), xp.ChunkIn("b", "mb", "para")],
            t,
        )
        assert res[0].translation == "a\nb"

    def test_single_line_misattribution_e2e(self) -> None:
        """was CONFIRMED wrong-attribution e2e——修复后整批退单翻。"""
        # observed: 单行 ``[1] .. [2] ..`` 响应判歧义 → 全员各自走单翻
        # （批 1 发 + 单 N 发），batched=False、batch_id 仍记批号
        t = _T(lambda _u: "[1] 结果如文献 [2] 所示成立", lambda u: f"zh {u}")
        res = _run(
            [
                xp.ChunkIn("m1", "First member text here", "para"),
                xp.ChunkIn("m2", "Second member text here", "para"),
            ],
            t,
        )
        assert [r.status for r in res] == ["ok", "ok"]
        assert all(not r.batched for r in res)
        assert {r.batch_id for r in res} == {"batch_0000"}
        assert res[0].translation == "zh First member text here"
        assert res[1].translation == "zh Second member text here"
        assert len(t.calls) == 3  # noqa: PLR2004 -- 批 1 + 单翻 2

    def test_degraded_member_consults_cache(self) -> None:
        # observed: 批解析失败 → 回炉先查段级缓存，命中即免重发
        chunks = [xp.ChunkIn("a", "ma", "para"), xp.ChunkIn("b", "mb", "para")]
        p = xp.XlatPipeline(_T(lambda _u: "garbage"), config=_cfg(), cache={})
        key = p._seg_key(chunks[0])  # noqa: SLF001
        assert p.cache is not None
        p.cache[key] = "cached zh"
        res = asyncio.run(p.run(chunks))
        assert res[0].translation == "cached zh"
        assert res[0].attempts == 0  # 缓存命中没发请求

    def test_leftover_ph_intercept_on_batch_member(self) -> None:
        # observed: 批成员译文带 src 外 token → 松 validator 放行也被
        # _collect 升格拦截 → fault + skipped + 回退原文 + error_kind=validate
        def batch_reply(_u: str) -> str:
            return "[1] 译文 [[MATH_9]]\n[2] 译文二"

        t = _T(batch_reply)
        res = _run(
            [
                xp.ChunkIn("a", "first text", "para"),
                xp.ChunkIn("b", "second text", "para"),
            ],
            t,
            validator=lambda _s, _z: "",  # 松 validator——拦截网是唯一闸
        )
        assert res[0].status == "fault"
        assert res[0].fell_back
        assert res[0].translation == res[0].source
        assert res[0].error_kind == "validate"
        assert any("leftover_ph" in w for w in res[0].warnings)
        assert res[1].status == "ok"


# ---------------------------------------------------------------- parse 不变量 fuzz


class TestParseFuzz:
    def test_fuzz_anchored_attribution_never_misaligns(self) -> None:
        """良构响应（行首 [k] + 任意乱序）永不错配——独立 oracle 逐段对账。"""
        rng = fuzz_rng(20261205)
        words = ["alpha", "beta", "gamma", "[x]", "[a]", "中文", "@@", "}", "$"]
        for _ in range(_FUZZ_MED):
            n = rng.randint(1, 8)
            secs = [
                " ".join(rng.choice(words) for _ in range(rng.randint(1, 6)))
                for _ in range(n)
            ]
            # 良构前提：段内不出现行首 [digit] 形态、无 ``@@`` 独占段
            # （``@@`` 独占行按协议残码剥除——剥后段空视同空段整批拒收，
            # ``a @@ b`` 行内形按内容字面收不受影响）；生成器能产出
            # ``@@`` 独字段，违例轮跳过而非 assert
            if any(
                re.search(r"(?m)^\s*\[\d", s) or re.fullmatch(r"\s*@@\s*", s)
                for s in secs
            ):
                continue
            order = list(range(n))
            rng.shuffle(order)
            body = "\n".join(f"[{i + 1}] {secs[i]}" for i in order)
            out = xb.parse_batch_response(body, n)
            assert out == secs

    def test_fuzz_garbage_none_or_n_nonempty(self) -> None:
        """标记系垃圾汤：只许 None 或恰 n 段非空——绝不部分错位。"""
        rng = fuzz_rng(20261206)
        junk = [
            "[1]",
            "[2]",
            "[12]",
            "[[1]]",
            "@@",
            "[0]",
            "[ 2]",
            "[2 ]",
            "[1a]",
            "[-1]",
            "[２]",
            "\n",
            " ",
            "x",
            "[[MATH_1]]",
            "中文",
            "[1] a [2] b",
            "a@@b",
        ]
        for _ in range(_FUZZ_MED):
            n = rng.randint(1, 6)
            text = "".join(rng.choice(junk) for _ in range(rng.randint(0, 15)))
            out = xb.parse_batch_response(text, n)
            if out is None:
                continue
            assert len(out) == n
            assert all(isinstance(p, str) and p for p in out)
