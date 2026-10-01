"""xlat 编排性质 fuzz——fault 矩阵驱动 + 独立 oracle 重算。

不变量清单：

- ``encode_newlines``/``decode_newlines`` 对任意不含 sentinel 字面的输入
  round-trip（``\\r\\n``/``\\r`` 归一后逐字节还原）；``source_sl``/``source_pl``
  计数与逐 ``\\n``-run 重放的独立 oracle 一致；
- ``pack_batches`` 产出 ``range(n)`` 的保序划分；多成员批
  ``Σ(len+overhead) ≤ max_chars``，超限单件独占一批；
- ``encode_batch`` → ``parse_batch_response`` 对编码后非空成员无损往返；
  ``parse_batch_response`` 对任意垃圾输入只回 ``None`` 或恰 ``n`` 段非空串——
  绝不静默错位、绝不抛；
- ``split_long_chunk`` 片段按序覆盖原文（接缝只丢 ``\\n``），片段非空且
  ``≤ max_chars + 64``（``_safe_cut`` 探测窗上限）；
- ``XlatPipeline.run`` 在内容驱动的随机 fault 注入下：结果序 == 输入序、
  chunk 零丢失（run 末行 ``done_map[cid]`` 若缺即 KeyError——本套断言
  全字段对账）、``skipped ⇒ translation == source``、fault 分类
  auth/provider/crash/validate 各归其位——含**批内连坐语义**（非
  retryable ChatError 全批同罪 skip；retryable/裸崩整批降级单翻后
  按成员各自定罪）、同输入结果逐字段确定；
- state 续跑：已完成块零重发、未完成块必重发、重试结果按新一轮
  （done 集合过滤后的）编排与 oracle 一致；
- ``segment_key``/``file_cache_key``/``cache_key_for`` 与独立 sha256 重算
  一致且对每个成分敏感；``api_key`` 永不以明文进键；``ChatClient`` 错误
  文本不含明文 key（``redact`` 口径）；
- ``AuthGate`` 连续计数/熔断/``all_failed`` 与独立记账 oracle 逐条一致；
- ``StateStore``/``atomic_json``/``load_cache``：原子落盘 0600 无残留、
  record→load 逐字段往返、任意字节/结构变异 ``load`` 只回 ``(set, dict)``
  或在已钉缺陷族内断言复现逃逸。

回归钉（首轮 fuzz 钉住的 4 族缺陷已全部修复，以下转常设回归用例）：

- ``placeholders.diff`` 补上了 rules ``_check_placeholder`` 的 ``src_literal``
  净差豁免（src 自带 ``[RS80]``/``[a_1]`` 形 verbatim 字面不再计 ``extra``；
  此前缺省 validator 路径下逐字正确译文必判 invalid → 阶梯三振 →
  恒 fallback_orig）——``test_diff_src_literal_fuzzy_exempt``；
- ``encode_newlines``/``decode_newlines`` 转义链加深为四相
  （sentinel→sentinel2 最内层），sentinel 字面 ``[[__TEXLATE_*_LIT__]]``
  round-trip 恢复——``test_sentinel_literal_roundtrip``；
- ``StateStore.load``/``load_cache`` 损坏兜网并收 ``UnicodeDecodeError``——
  非 UTF-8 字节同样隔离改名回空——``test_state_load_non_utf8_quarantines``；
- ``StateStore.load`` 字段级类型脏纳入兜网（非可迭代/不可哈希/非 dict
  ``meta``/非数值 ``total_chunks`` → 隔离回 ``(set(), {})``）——
  ``test_state_load_malformed_fields_quarantine`` 8 参数族。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from _fuzzkit import (
    RecordingTranslator,
    fuzz_rng,
    soup_join,
    strip_feedback_reply,
)

from texlate.textutil import residual_en_net
from texlate.validate.rules import validate_pair
from texlate.xlat import batch as xb
from texlate.xlat import placeholders as ph
from texlate.xlat.client import AuthError, ChatClient, ChatError, redact
from texlate.xlat.pipeline import (
    AuthGate,
    AuthTrippedError,
    ChunkIn,
    ChunkResult,
    PipelineConfig,
    XlatPipeline,
)
from texlate.xlat.state import (
    StateStore,
    atomic_json,
    file_cache_key,
    load_cache,
    segment_key,
)

if TYPE_CHECKING:
    import random
    from pathlib import Path

# ---------------------------------------------------------------- 常量与 soup

#: fault 注入标记（\\x00 包裹——自然 chunk 不可能出现的形态）
_M_AUTH = "\x00AUTH\x00"
_M_E500 = "\x00E500\x00"  # non-retryable 5xx
_M_E5XX = "\x00E5XX\x00"  # retryable 5xx
_M_CRASH = "\x00CRASH\x00"  # 非 ChatError 裸崩
_M_BAD = "\x00BAD\x00"  # 校验永不放行的脏译文标记
_MARKERS = (_M_AUTH, _M_E500, _M_E5XX, _M_CRASH, _M_BAD)

#: 文本 soup——刻意避开 fuzzy 占位符形（``[X_n]``/``【..】``/``[[..]`` 缺括号，
#: 那些由 src_literal drift 钉单独覆盖；``[12]`` 纯数字不命中 PH_FUZZY_RX）
_TEXT_SOUP = [
    "Hello world. ",
    "The quick brown fox",
    " jumps over.\n",
    "lazy dog.\n\n",
    "[[MATH_1]]",
    "[[CITE_12]]",
    "[[ENV_3]]",
    "[[SL]]",
    "[[PL]]",
    "[[SL_RAW]]",
    "[[PL_RAW]]",
    "[[SP]]",
    "[[SP_RAW]]",
    "[[NBSP]]",
    "[[THINSP]]",
    "\\alpha",
    "\\cite{x}",
    "\\textbf{b}",
    "{",
    "}",
    "$x+y$",
    "~",
    "\\,",
    "\\ ",
    "\\;",
    "\\!",
    "\\:",
    "中文片段。",
    "% trailing comment\n",
    "@@",
    "[12]",
    "\t",
    "  ",
    "x" * 120,
]

#: 编解码 fuzz 专用 soup——含全部转义层字面 + \\r 系，但不含 sentinel 层
_CODEC_SOUP = [
    *_TEXT_SOUP,
    "\r\n",
    "\r",
    "[[NBSP_RAW]]",
    "[[THINSP_RAW]]",
    "[[MEDSP_RAW]]",
    "[[THICKSP_RAW]]",
    "[[NEGSP_RAW]]",
]

_SENTINELS = [
    "[[__TEXLATE_SL_LIT__]]",
    "[[__TEXLATE_PL_LIT__]]",
    "[[__TEXLATE_SP_LIT__]]",
    "[[__TEXLATE_NBSP_LIT__]]",
    "[[__TEXLATE_THINSP_LIT__]]",
    "[[__TEXLATE_MEDSP_LIT__]]",
    "[[__TEXLATE_THICKSP_LIT__]]",
    "[[__TEXLATE_NEGSP_LIT__]]",
]

#: 发生器概率（字面量提名喂 PLR2004）
_P_MARKER = 0.35
_P_PURE = 0.12
_P_BIB = 0.08
_P_LONG = 0.1
_FUZZ_ITERS = 3000
_FUZZ_ITERS_MED = 1500
_SAFE_CUT_WINDOW = 64  # _safe_cut 探测半径——片段上界 = limit + 窗口
_MODE_PRIVATE = 0o600
_P_ST_GARBAGE = 0.3
_P_ST_SCALAR = 0.5
_P_LC_GARBAGE = 0.4
_P_LC_SCALAR = 0.6

_KINDS = ("para", "caption", "section_title", "abstract", "table_text", "env_text")

_NL_RUN = re.compile(r"\n+")


# ---------------------------------------------------------------- 编解码 oracle


def _norm_nl(s: str) -> str:
    """``encode_newlines`` 的归一前置——oracle 独立转写。"""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _oracle_nl_counts(s: str) -> tuple[int, int]:
    """逐 ``\\n`` run 重放计数 → ``(sl, pl)``：k 连换行 = k//2 个 PL + k%2 个 SL。"""
    sl = pl = 0
    for m in _NL_RUN.finditer(s):
        k = len(m.group(0))
        pl += k // 2
        sl += k % 2
    return sl, pl


def test_fuzz_newline_codec_roundtrip() -> None:
    """任意 soup 文本 round-trip 逐字节还原（归一化后）。"""
    rng = fuzz_rng(20261001)
    for _ in range(_FUZZ_ITERS):
        s = soup_join(rng, _CODEC_SOUP, 0, 30)
        enc, _counts = ph.encode_newlines(s)
        assert ph.decode_newlines(enc) == _norm_nl(s), f"round-trip broke: {s!r}"


def test_fuzz_encode_counts_oracle() -> None:
    """``source_sl``/``source_pl`` 计数 == 独立 run 重放 oracle。"""
    rng = fuzz_rng(20261002)
    for _ in range(_FUZZ_ITERS):
        s = soup_join(rng, _CODEC_SOUP, 0, 30)
        _enc, counts = ph.encode_newlines(s)
        sl, pl = _oracle_nl_counts(_norm_nl(s))
        assert (counts["source_sl"], counts["source_pl"]) == (sl, pl)


def test_sentinel_literal_roundtrip() -> None:
    """回归钉：源含 sentinel 字面 → 三层转义后 ``decode(encode(s)) == s``。"""
    for s in _SENTINELS:
        enc, _ = ph.encode_newlines(f"a {s} b")
        assert ph.decode_newlines(enc) == f"a {s} b"


# ---------------------------------------------------------------- batch 协议


def test_fuzz_pack_batches_partition() -> None:
    """装箱 = ``range(n)`` 保序划分；多成员批受 ``max_chars`` 约束。"""
    rng = fuzz_rng(20261003)
    for _ in range(_FUZZ_ITERS_MED):
        contents = [
            "".join(rng.choice("ab{}$ ") for _ in range(rng.randint(0, 500)))
            for _ in range(rng.randint(0, 30))
        ]
        max_chars = rng.choice([1, 7, 50, 200, 2000])
        groups = xb.pack_batches(contents, max_chars=max_chars)
        flat = [i for g in groups for i in g]
        assert flat == list(range(len(contents)))
        for g in groups:
            total = sum(len(contents[i]) + xb.BATCH_ITEM_OVERHEAD for i in g)
            assert total <= max_chars or len(g) == 1


def test_fuzz_batch_encode_parse_roundtrip() -> None:
    """成员编码后非空的批载荷 → 解析逐字节还原（成员 ``.strip()`` 口径）。"""
    rng = fuzz_rng(20261004)
    for _ in range(_FUZZ_ITERS_MED):
        contents = [
            s
            for _ in range(rng.randint(1, 8))
            if (s := soup_join(rng, _CODEC_SOUP, 1, 8))
            # 独段 ``@@`` 成员上线即成残码行（剥除→段空→整批拒收），生成面排除
            and ph.encode_newlines(s)[0].strip() not in ("", "@@")
        ]
        if not contents:
            continue
        encs = [ph.encode_newlines(c)[0] for c in contents]
        # sanity: 编码面永不含裸换行（单行协议的前提）
        assert all("\n" not in e and "\r" not in e for e in encs)
        parts = xb.parse_batch_response(xb.encode_batch(contents), len(contents))
        assert parts == [e.strip() for e in encs]


def test_batch_whitespace_member_poisons_parse() -> None:
    """纯空白成员编码后 strip 成空 → 整批 ``None``（退化单翻，不丢不炸）。

    钉住现状语义：一个 ``is_placeholder_only`` 判 False 但编码后空白的成员
    会让 ``parse_batch_response`` 全军覆没——代价是多烧 N-1 次单翻调用。
    """
    enc = xb.encode_batch(["   ", "real text here"])
    assert xb.parse_batch_response(enc, 2) is None


def test_fuzz_parse_batch_never_misaligns() -> None:
    """垃圾/变异响应只许 ``None`` 或恰 ``n`` 段非空串——绝不部分错位。"""
    rng = fuzz_rng(20261005)
    junk = [
        "[1]",
        "[2]",
        "[12]",
        "@@",
        "\n",
        " ",
        "]",
        "[",
        "x",
        "[[MATH_1]]",
        "中文",
        "[1] a [2] b",
        "[0] z",
        "[-1] z",
        "[ 1 ] z",
        "@@x@@",
        "\x00",
    ]
    for _ in range(_FUZZ_ITERS):
        n = rng.randint(1, 6)
        text = "".join(rng.choice(junk) for _ in range(rng.randint(0, 15)))
        out = xb.parse_batch_response(text, n)
        if out is None:
            continue
        assert len(out) == n
        assert all(isinstance(p, str) and p for p in out)


def test_fuzz_split_partition_oracle() -> None:
    """切分片段按序覆盖原文：逐段前缀匹配，接缝只允许丢 ``\\n``。"""
    rng = fuzz_rng(20261006)
    for _ in range(_FUZZ_ITERS_MED):
        limit = rng.choice([1, 3, 40, 120, 500])
        text = soup_join(rng, _TEXT_SOUP, 1, 40)
        pieces = xb.split_long_chunk(text, max_chars=limit)
        assert pieces
        if len(text) <= limit:
            assert pieces == [text]
            continue
        rest = text
        for p in pieces:
            assert p, f"empty piece from {text!r}"
            assert len(p) <= limit + _SAFE_CUT_WINDOW
            assert rest.startswith(p), f"piece not a prefix of rest: {text!r}"
            rest = rest[len(p) :].lstrip("\n")
        assert rest == "", f"uncovered tail: {text!r}"


# ---------------------------------------------------------------- diff 对账


def test_fuzz_diff_identity_clean_pool() -> None:
    """干净池（无 fuzzy 形）逐字拷贝 → ``ok``；永不在脏输入上抛。"""
    rng = fuzz_rng(20261007)
    for _ in range(_FUZZ_ITERS):
        s = soup_join(rng, _TEXT_SOUP, 0, 25)
        d = ph.diff(s, s)
        assert d.ok, f"identity diff not ok: {s!r} -> {d.describe()}"
        # 脏 zh 侧不抛——diff 是不可信输入面
        zh = soup_join(rng, _TEXT_SOUP, 0, 25)
        ph.diff(s, zh)


def test_fuzz_diff_detects_drop_and_inject() -> None:
    """丢一个 ``[[X_n]]`` → missing/misspelled；多一个 src 外 token → extra。"""
    rng = fuzz_rng(20261008)
    for _ in range(_FUZZ_ITERS_MED):
        toks = rng.sample(
            ["[[MATH_1]]", "[[CITE_2]]", "[[ENV_3]]", "[[TABLE_4]]"],
            k=rng.randint(1, 4),
        )
        src = " ".join(["word", *toks, "tail"])
        drop = rng.choice(toks)
        zh_missing = " ".join(["word", *(t for t in toks if t != drop), "tail"])
        d = ph.diff(src, zh_missing)
        assert drop in d.missing or any(drop == g for _b, g in d.misspelled)
        d2 = ph.diff(src, f"{src} [[ZZZ_9]]")
        assert "[[ZZZ_9]]" in d2.extra


def test_diff_src_literal_fuzzy_exempt() -> None:
    """回归钉：``[Xn]`` 形字面 verbatim 复制判 ok（与 rules 豁免同口径）。"""
    src = "see [RS80] and [a_1] in the references"
    assert validate_pair(src, src).ok  # rules 有豁免——对照组必须过
    assert ph.diff(src, src).ok  # xlat diff 同口径净差豁免


def test_fuzz_is_placeholder_only_oracle() -> None:
    """``is_placeholder_only`` ⇒ 内容全由占位符 token + 空白覆盖（独立 oracle）。"""
    rng = fuzz_rng(20261009)
    pool = ["[[MATH_1]]", "[[CITE_2]]", "[[SL]]", "[[PL]]", " ", "\n", "\t", "x", "%"]
    for _ in range(_FUZZ_ITERS):
        s = "".join(rng.choice(pool) for _ in range(rng.randint(0, 8)))
        if ph.is_placeholder_only(s):
            residue = ph.ANY_PH_RX.sub("", s)
            assert not residue.strip()
            assert ph.ANY_PH_RX.search(s)


# ---------------------------------------------------------------- fault 驱动 pipeline


class ScriptedTranslator(RecordingTranslator):
    """内容驱动 fault 注入——行为只看 ``user`` 文本，与 asyncio 调度序无关。

    - marker → 对应异常（检查序 = AUTH→E500→E5XX→CRASH，批级连坐按此推）；
    - ``response_format`` 请求 → slots JSON 全空值（``_valid_slot_text`` 必拒
      → slots 阶段对 BAD 块必败走 fallback）；
    - 全 ``[n]`` 编号行 user → 逐字节回显（走真 ``parse_batch_response``）；
    - 否则回显 user（剥 ``[previous_validation_error]`` 反馈后缀）。
    """

    def __init__(self) -> None:
        super().__init__(
            record="user",
            markers=[
                (_M_AUTH, AuthError("denied", status=401)),
                (_M_E500, ChatError("boom500", status=500, retryable=False)),
                (_M_E5XX, ChatError("boom5xx", status=500, retryable=True)),
                (_M_CRASH, RuntimeError("scripted crash")),
            ],
            slots_fill="",
            batch_match="lines",
            single_fn=strip_feedback_reply,
        )


def _fuzz_validator(src: str, zh: str) -> str:
    """``_M_BAD`` 永不放行；其余走默认占位符对账。"""
    if _M_BAD in zh:
        return "bad marker in translation"
    return ph.diff(src, zh).describe()


def _gen_doc(rng: random.Random, base: int) -> list[ChunkIn]:
    """随机文档：纯占位符/短块/超 hard 块/fault 标记块混合（id 带迭代前缀防撞）。

    每个非纯块尾挂 ``\\x01T<base>_<i>\\x01`` 记账 tag——既验证「应请求的块
    确实进过载荷」，也把编码面钉成非空白（空白成员进批有独立钉住语义）。
    marker 只注短块——>hard_limit 的 split 路径保持干净。
    """
    chunks: list[ChunkIn] = []
    for i in range(rng.randint(1, 14)):
        cid = f"{base}_{i}"
        r = rng.random()
        if r < _P_PURE:
            content = " ".join(
                rng.choice(["[[MATH_1]]", "[[CITE_2]]", "[[SL]]"])
                for _ in range(rng.randint(1, 3))
            )
        elif r < _P_PURE + _P_BIB:
            content = f"[[BIB_{rng.randint(1, 9)}]] " + soup_join(rng, _TEXT_SOUP, 2, 8)
        elif r < _P_PURE + _P_BIB + _P_LONG:
            body = soup_join(rng, _TEXT_SOUP, 20, 60) + " tail."
            content = body * (600 // max(1, len(body)) + 1)
        else:
            content = soup_join(rng, _TEXT_SOUP, 1, 10)
            if rng.random() < _P_MARKER:
                content += rng.choice(_MARKERS)
        if not ph.is_placeholder_only(content.strip()):
            content += f"\x01T{cid}\x01"
        chunks.append(ChunkIn(cid, content, rng.choice(_KINDS)))
    return chunks


def _cfg(rng: random.Random, **kw: object) -> PipelineConfig:
    """小预算配置：hard 500 / batch 200 / min 100 → 批/独员 single/split 三臂都打得到。"""
    return PipelineConfig(
        concurrency=rng.choice([1, 2, 4]),
        batch_max_chars=200,
        batch_min_chars=100,
        hard_limit=500,
        auth_fail_threshold=0,
        **kw,  # type: ignore[arg-type]
    )


@dataclass
class _Exp:
    """一块的期望终态——``attempts``/``translation`` 为 None 表示不判。"""

    status: str
    error_kind: str = ""
    skipped: bool = False
    batched: bool = False
    translation: str | None = None
    attempts: int | None = None


def _marker_of(content: str) -> str:
    for m in _MARKERS:
        if m in content:
            return m
    return ""


def _exp_single(content: str) -> _Exp:
    """单块路径期望（long 单翻 / 批降级 / split 片段共用形态）。"""
    m = _marker_of(content)
    if m == _M_AUTH:
        return _Exp("skipped", "auth", skipped=True, translation=content, attempts=0)
    if m in (_M_E500, _M_E5XX):
        return _Exp(
            "skipped", "provider", skipped=True, translation=content, attempts=0
        )
    if m == _M_CRASH:
        return _Exp("skipped", "crash", skipped=True, translation=content, attempts=0)
    if m == _M_BAD:
        # 阶梯三振 fallback_orig——attempts 随 lines/slots 结构浮动不判
        return _Exp("fault", "validate", skipped=True, translation=content)
    enc = ph.encode_newlines(content)[0]
    zh = ph.decode_newlines(enc)
    if residual_en_net(content, zh):
        # 残英升格拦截——ok 出口被第四网降 fault + 回退原文
        return _Exp("fault", "validate", skipped=True, translation=content, attempts=1)
    return _Exp("ok", translation=zh, attempts=1)


def _simulate(  # noqa: C901, PLR0912 -- oracle 复刻编排路由，分支即语义面
    chunks: list[ChunkIn], cfg: PipelineConfig, *, done: set[str]
) -> dict[str, _Exp]:
    """路由 + 批内连坐语义的独立重放——只调公开契约（pack/split/codec）。

    ``done`` = 续跑已完成集合（ok/partial）：这些块不进 pending，期望由
    调用方按 run1 记录原样对账（本表不覆盖它们）。
    """
    exp: dict[str, _Exp] = {}
    pending: list[ChunkIn] = []
    for c in chunks:
        if c.chunk_id in done:
            continue
        if ph.is_placeholder_only(c.content.strip()):
            exp[c.chunk_id] = _Exp("ok", translation=c.content, attempts=0)
            continue
        if "[[BIB_" in c.content:
            exp[c.chunk_id] = _Exp("ok", translation=c.content, attempts=0)
            continue
        pieces = xb.split_long_chunk(c.content, max_chars=cfg.hard_limit)
        if len(pieces) > 1:
            # split 父块：逐片段单翻 + " " 合并；attempts 聚合各片段
            # （干净片段 echo 单翻恒 1 试 → len(pieces)）
            merged = " ".join(
                ph.decode_newlines(ph.encode_newlines(p)[0]) for p in pieces
            )
            if residual_en_net(c.content, merged):
                # 合并父块过 _collect 残英网 → fault + 回退原文
                exp[c.chunk_id] = _Exp(
                    "fault",
                    "validate",
                    skipped=True,
                    translation=c.content,
                    attempts=len(pieces),
                )
            else:
                exp[c.chunk_id] = _Exp("ok", translation=merged, attempts=len(pieces))
            continue
        pending.append(c)

    by_kind: dict[str, list[ChunkIn]] = {}
    for c in pending:
        by_kind.setdefault(c.kind, []).append(c)
    for grp in by_kind.values():
        contents = [c.content for c in grp]
        groups = xb.pack_batches(
            contents,
            max_chars=cfg.batch_max_chars,
            max_items=cfg.batch_max_items,
            min_chars=cfg.batch_min_chars,
            # v6 keep 前缀逐项实长——管线同口径，oracle 不复刻会假报批路由分歧
            overheads=[xb.batch_member_overhead(t) for t in contents],
            workers=cfg.concurrency,
        )
        for idxs in groups:
            members = [grp[j] for j in idxs]
            if len(members) == 1:
                # 独员组退化成 single 阶梯路径
                exp[members[0].chunk_id] = _exp_single(members[0].content)
                continue
            kinds = {_marker_of(m.content) for m in members}
            if _M_AUTH in kinds:
                # 非 retryable ChatError → 全批同罪 skip（连坐语义）
                for m in members:
                    exp[m.chunk_id] = _Exp(
                        "skipped",
                        "auth",
                        skipped=True,
                        translation=m.content,
                        attempts=0,
                    )
            elif _M_E500 in kinds:
                for m in members:
                    exp[m.chunk_id] = _Exp(
                        "skipped",
                        "provider",
                        skipped=True,
                        translation=m.content,
                        attempts=0,
                    )
            elif kinds & {_M_E5XX, _M_CRASH}:
                # retryable/裸崩 → 整批降级单翻，按成员各自定罪
                for m in members:
                    exp[m.chunk_id] = _exp_single(m.content)
            else:
                for m in members:
                    if _marker_of(m.content) == _M_BAD:
                        exp[m.chunk_id] = _Exp(
                            "fault", "validate", skipped=True, translation=m.content
                        )
                    else:
                        enc = ph.encode_newlines(m.content)[0]
                        zh = ph.decode_newlines(enc.strip())
                        if residual_en_net(m.content, zh):
                            # 批成员同样过 _collect 残英网——batched/batch_id 不动
                            exp[m.chunk_id] = _Exp(
                                "fault",
                                "validate",
                                skipped=True,
                                batched=True,
                                translation=m.content,
                                attempts=1,
                            )
                        else:
                            exp[m.chunk_id] = _Exp(
                                "ok",
                                batched=True,
                                translation=zh,
                                attempts=1,
                            )
    return exp


def _check_result(c: ChunkIn, r: ChunkResult, exp: _Exp) -> None:
    """逐块全字段对账。"""
    assert r.status == exp.status, (
        f"{c.chunk_id}: {r.status} != {exp.status} ({r.skip_reason})"
    )
    assert r.error_kind == exp.error_kind, f"{c.chunk_id}: {r.error_kind!r}"
    assert r.fell_back == exp.skipped, c.chunk_id
    assert r.batched == exp.batched, c.chunk_id
    if exp.attempts is not None:
        assert r.attempts == exp.attempts, f"{c.chunk_id}: attempts={r.attempts}"
    if exp.skipped:
        assert r.translation == r.source == c.content, c.chunk_id
    elif exp.translation is not None:
        assert r.translation == exp.translation, c.chunk_id
    if exp.batched:
        assert r.batch_id.startswith("batch_")


def test_fuzz_pipeline_no_lost_no_reorder() -> None:
    """随机 fault 文档：结果序==输入序、零丢失、逐块全字段对独立 oracle。"""
    rng = fuzz_rng(20261010)
    for it in range(200):
        chunks = _gen_doc(rng, it)
        t = ScriptedTranslator()
        cfg = _cfg(rng)
        exp = _simulate(chunks, cfg, done=set())
        results = asyncio.run(
            XlatPipeline(t, config=cfg, validator=_fuzz_validator).run(chunks)
        )
        assert [r.chunk_id for r in results] == [c.chunk_id for c in chunks]
        for c, r in zip(chunks, results, strict=True):
            _check_result(c, r, exp[c.chunk_id])
        # 每个非纯块的 tag 确实进过请求载荷（零静默丢失——含被连坐的；
        # [[BIB_ 直通块按设计零请求，豁免此钉）
        requested = "\n".join(t.calls)
        for c in chunks:
            if not ph.is_placeholder_only(c.content.strip()) and (
                "[[BIB_" not in c.content
            ):
                assert f"\x01T{c.chunk_id}\x01" in requested, c.chunk_id


def test_fuzz_pipeline_deterministic() -> None:
    """同输入同结果——attempts/batch_id/warnings 全字段逐字节等。"""
    rng = fuzz_rng(20261011)
    for it in range(60):
        chunks = _gen_doc(rng, 10000 + it)
        cfg = _cfg(rng)
        r1 = asyncio.run(
            XlatPipeline(
                ScriptedTranslator(), config=cfg, validator=_fuzz_validator
            ).run(chunks)
        )
        r2 = asyncio.run(
            XlatPipeline(
                ScriptedTranslator(), config=cfg, validator=_fuzz_validator
            ).run(chunks)
        )
        assert [
            (
                r.status,
                r.translation,
                r.fell_back,
                r.error_kind,
                r.batched,
                r.batch_id,
                r.attempts,
                r.warnings,
            )
            for r in r1
        ] == [
            (
                r.status,
                r.translation,
                r.fell_back,
                r.error_kind,
                r.batched,
                r.batch_id,
                r.attempts,
                r.warnings,
            )
            for r in r2
        ]


def test_fuzz_pipeline_resume_no_retranslate(tmp_path: Path) -> None:
    """续跑：run1 ok/partial 块零重发且结果同记录；skipped/fault 块必重发，
    且按新一轮（done 集合过滤后的）编排重出与 oracle 一致的结果。"""
    rng = fuzz_rng(20261012)
    for it in range(40):
        outdir = tmp_path / f"r{it}"
        chunks = _gen_doc(rng, 20000 + it)
        cfg = _cfg(rng)
        t1 = ScriptedTranslator()
        r1 = asyncio.run(
            XlatPipeline(
                t1,
                config=cfg,
                state=StateStore(outdir, save_every=10**9),
                validator=_fuzz_validator,
            ).run(chunks)
        )
        exp1 = _simulate(chunks, cfg, done=set())
        for c, r in zip(chunks, r1, strict=True):
            _check_result(c, r, exp1[c.chunk_id])

        t2 = ScriptedTranslator()
        r2 = asyncio.run(
            XlatPipeline(
                t2,
                config=cfg,
                state=StateStore(outdir, save_every=10**9),
                validator=_fuzz_validator,
            ).run(chunks)
        )
        done = {
            c.chunk_id
            for c, a in zip(chunks, r1, strict=True)
            if a.status in ("ok", "partial")
        }
        exp2 = _simulate(chunks, cfg, done=done)
        calls2 = "\n".join(t2.calls)
        for c, a, b in zip(chunks, r1, r2, strict=True):
            tag = f"\x01T{c.chunk_id}\x01"
            pure = ph.is_placeholder_only(c.content.strip())
            if a.status in ("ok", "partial"):
                # 已完成块：零重发 + 结果即 run1 落库记录
                assert tag not in calls2, f"{c.chunk_id} re-requested"
                assert (b.status, b.fell_back, b.translation, b.error_kind) == (
                    a.status,
                    a.fell_back,
                    a.translation,
                    a.error_kind,
                )
            else:
                if not pure:
                    assert tag in calls2, f"{c.chunk_id} not retried"
                _check_result(c, b, exp2[c.chunk_id])


def test_pipeline_all_auth_trips_gate() -> None:
    """全员 auth 失败 → ``AuthTrippedError``（凭证失效绝不静默 fallback 整篇）。"""
    cfg = PipelineConfig(
        concurrency=3,
        batch_max_chars=200,
        hard_limit=500,
        auth_fail_threshold=2,
    )
    chunks = [ChunkIn(f"c{i}", f"Text body {i} {_M_AUTH}") for i in range(6)]
    with pytest.raises(AuthTrippedError):
        asyncio.run(XlatPipeline(ScriptedTranslator(), config=cfg).run(chunks))


def test_pipeline_empty_run() -> None:
    """空输入 → 空结果，不发请求。"""
    t = ScriptedTranslator()
    assert asyncio.run(XlatPipeline(t).run([])) == []
    assert t.calls == []


def test_chat_error_never_leaks_api_key() -> None:
    """泄漏面 oracle：上游 401 body 明文回显 key → 异常文本必须脱敏。"""
    canary = "sk-canary-NEVERLEAK-01234567"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": f"invalid key {canary} provided"}}
        )

    async def _run() -> ChatError:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            client = ChatClient("http://localhost:3003", canary, http=http)
            with pytest.raises(AuthError) as ei:
                await client.chat("m", [{"role": "user", "content": "hi"}])
            return ei.value
        finally:
            await http.aclose()

    err = asyncio.run(_run())
    assert canary not in str(err)
    assert "***" in str(err)


def test_fuzz_redact_key_forms() -> None:
    """``redact``：显式 key 逐字替换。"""
    rng = fuzz_rng(20261018)
    for _ in range(500):
        key = f"sk-{rng.randbytes(8).hex()}"
        text = soup_join(rng, _TEXT_SOUP, 0, 6) + key + " tail"
        assert key not in redact(text, key)


# ---------------------------------------------------------------- 缓存键 oracle


def test_fuzz_segment_key_oracle() -> None:
    """``segment_key`` == 独立材料拼装的 sha256；逐成分敏感。"""
    rng = fuzz_rng(20261013)
    for _ in range(_FUZZ_ITERS_MED):
        src = soup_join(rng, _TEXT_SOUP, 0, 12)
        role = rng.choice(["", "para", "caption"])
        tags = [rng.choice(["accent", "decl", "ord"]) for _ in range(rng.randint(0, 3))]
        snap = rng.choice(["", "[]", "['MATH']"])
        material = src if not role else f"{role}\x00{src}"
        for tag in tags:
            material += f"\x00{tag}"
        if snap:
            material += f"\x00masked\x00{snap}"
        want = hashlib.sha256(material.encode()).hexdigest()
        assert (
            segment_key(src, role, invalidation_tags=tags, masked_snapshot=snap) == want
        )


def test_segment_key_sensitivity() -> None:
    """成分翻转 → 键必变（确定性不等，非概率断言）。"""
    base = segment_key("src", "para")
    assert segment_key("src2", "para") != base
    assert segment_key("src", "caption") != base
    assert segment_key("src", "para", invalidation_tags=["x"]) != base
    assert segment_key("src", "para", masked_snapshot="s") != base
    assert segment_key("src", "para") == segment_key("src", "para")


def test_file_cache_key_oracle() -> None:
    """``file_cache_key`` == sort_keys JSON 的 sha256[:16] 独立重算。"""
    payload = json.dumps(
        {
            "version": "pv",
            "base": "http://x",
            "model": "m",
            "language": "zh",
            "glossary": None,
            "context": "c",
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    want = hashlib.sha256(payload.encode()).hexdigest()[:16]
    got = file_cache_key(
        prompt_version="pv",
        base_url="http://x",
        model="m",
        lang="zh",
        glossary=None,
        context="c",
    )
    assert got == want


def test_cache_key_for_scope_and_secret() -> None:
    """``worker.cache_key_for``：成分敏感；shared scope 忽略 api_key。"""
    from texlate.server.worker import PIPELINE_VERSION, cache_key_for  # noqa: PLC0415

    kw = {"arxiv_id": "1706.03762", "version": 2, "model": "m", "target_lang": "zh"}
    material = f"1706.03762@v2|m|{PIPELINE_VERSION}|zh"
    assert cache_key_for(**kw) == hashlib.sha256(material.encode()).hexdigest()
    assert cache_key_for(**{**kw, "arxiv_id": "x"}) != cache_key_for(**kw)
    assert cache_key_for(**{**kw, "version": 3}) != cache_key_for(**kw)
    assert cache_key_for(**{**kw, "model": "n"}) != cache_key_for(**kw)
    assert cache_key_for(**{**kw, "target_lang": "en"}) != cache_key_for(**kw)
    # version=None/0 同键（ver 段 falsy 归一为空）
    assert cache_key_for(**{**kw, "version": None}) == cache_key_for(
        **{**kw, "version": 0}
    )
    # shared scope：api_key 不进键
    assert cache_key_for(**kw, api_key="sk-secret") == cache_key_for(**kw)


def test_cache_key_for_per_key_scope(clean_env: pytest.MonkeyPatch) -> None:
    """``TEXLATE_CACHE_SCOPE=per_key``：key 进材料但永不明文。"""
    from texlate.server.worker import cache_key_for  # noqa: PLC0415

    clean_env.setenv("TEXLATE_CACHE_SCOPE", "per_key")
    kw = {"arxiv_id": "a", "version": 1, "model": "m", "target_lang": "zh"}
    k1 = cache_key_for(**kw, api_key="sk-AAA")
    k2 = cache_key_for(**kw, api_key="sk-BBB")
    k3 = cache_key_for(**kw, api_key="sk-AAA")
    assert k1 != k2
    assert k1 == k3
    sha_len = 64
    assert "sk-AAA" not in k1
    assert len(k1) == sha_len


# ---------------------------------------------------------------- AuthGate oracle


def test_fuzz_authgate_oracle() -> None:
    """随机结果流 → consecutive/auth_failures/non_auth/tripped 逐条对账。"""
    rng = fuzz_rng(20261014)
    for _ in range(_FUZZ_ITERS_MED):
        thr = rng.choice([0, 1, 3, 5])
        gate = AuthGate(threshold=thr)
        exp_consec = exp_auth = exp_non = 0
        exp_trip = False
        for _ in range(rng.randint(1, 12)):
            kind = rng.choice(["auth", "provider", "crash", "validate", ""])
            attempts = rng.choice([0, 0, 1, 2])
            gate.record(
                ChunkResult(
                    chunk_id="x",
                    source="s",
                    translation="t",
                    kind="para",
                    attempts=attempts,
                    error_kind=kind,
                )
            )
            if kind == "auth":
                exp_consec += 1
                exp_auth += 1
                if 0 < thr <= exp_consec:
                    exp_trip = True
            elif attempts > 0 or kind:
                exp_consec = 0
                exp_non += 1
            assert gate.consecutive == exp_consec
            assert gate.auth_failures == exp_auth
            assert gate.non_auth == exp_non
            assert gate.tripped == exp_trip
            assert gate.all_failed == (exp_trip or (exp_auth > 0 and exp_non == 0))


# ---------------------------------------------------------------- state 落盘


def test_atomic_json_perms_and_residue(tmp_path: Path) -> None:
    """原子写：0600 + 无 tmp 残留 + 重写覆盖。"""
    p = tmp_path / "a.json"
    atomic_json(p, {"x": 1})
    assert stat.S_IMODE(p.stat().st_mode) == _MODE_PRIVATE
    assert [f.name for f in tmp_path.iterdir()] == ["a.json"]
    atomic_json(p, {"y": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"y": 2}
    assert [f.name for f in tmp_path.iterdir()] == ["a.json"]


def test_fuzz_state_record_load_roundtrip(tmp_path: Path) -> None:
    """随机 ChunkRecord 序列 → flush → load：completed 集合与字段逐条对账。"""
    rng = fuzz_rng(20261015)
    from texlate.xlat.state import ChunkRecord  # noqa: PLC0415

    for it in range(60):
        d = tmp_path / f"s{it}"
        st = StateStore(d, save_every=rng.randint(1, 5))
        st.start(0)
        recs: dict[str, dict[str, object]] = {}
        order: list[str] = []
        for i in range(rng.randint(1, 15)):
            cid = f"c{rng.randint(0, 8)}"  # 故意重 id——load 后者覆盖
            rec = ChunkRecord(
                chunk_id=cid,
                source=f"src{i}",
                translation=f"zh{i}",
                status=rng.choice(["ok", "skipped", "fault", "partial"]),
                attempts=rng.randint(0, 4),
                warnings=[f"w{i}"],
                error_kind=rng.choice(["", "auth", "provider", "crash"]),
            )
            st.record(rec)
            recs[cid] = {"source": f"src{i}", "status": rec.status}
            if cid not in order:
                order.append(cid)
        st.finish()
        completed, loaded = StateStore(d).load()
        assert completed == set(order)
        for cid, expect in recs.items():
            assert loaded[cid].source == expect["source"]
            assert loaded[cid].status == expect["status"]


def test_fuzz_state_load_never_raises(tmp_path: Path) -> None:
    """state.json 字节/结构级变异：``load`` 只回 ``(set, dict)`` 绝不抛——
    字段级类型脏（``test_state_load_malformed_fields_quarantine``）同样
    走隔离回空。"""
    rng = fuzz_rng(20261016)
    base = {
        "version": "1.0",
        "meta": {"total_chunks": 2},
        "completed": ["c0", "c9"],
        "results": [
            {
                "chunk_id": "c0",
                "source": "s",
                "translation": "t",
                "status": "ok",
            },
            {"chunk_id": "c9", "source": "s9"},
        ],
        "errors_report": [],
    }
    for i in range(300):
        d = tmp_path / f"c{i}"
        d.mkdir()
        p = d / "state.json"
        r = rng.random()
        if r < _P_ST_GARBAGE:
            # ASCII 垃圾必可解码——非 UTF-8 分支由 test_state_load_non_utf8_quarantines
            # 回归钉（load 漏 catch 已修，原 xfail 拆为普通断言）
            p.write_bytes(bytes(rng.randrange(128) for _ in range(rng.randint(0, 200))))
        elif r < _P_ST_SCALAR:
            p.write_text(json.dumps(rng.choice([[], "x", 42, None])))
        else:
            doc = json.loads(json.dumps(base))
            k = rng.choice(["completed", "results", "errors_report", "meta", "version"])
            doc[k] = rng.choice([None, [], {}, "x", 7, [None, {"x": 1}]])
            p.write_text(json.dumps(doc))
        completed, recs = StateStore(d).load()
        assert isinstance(completed, set)
        assert all(isinstance(v.chunk_id, str) for v in recs.values())


def test_state_load_non_utf8_quarantines(tmp_path: Path) -> None:
    """回归钉：非 UTF-8 state/cache 文件隔离回空而非抛。"""
    d1 = tmp_path / "state"
    d1.mkdir()
    (d1 / "state.json").write_bytes(b"\xff\xfe\x00garbage")
    assert StateStore(d1).load() == (set(), {})
    p2 = tmp_path / "cache-k.json"
    p2.write_bytes(b"\x80\x81not-utf8")
    assert load_cache(p2) == {}


@pytest.mark.parametrize(
    "doc",
    [
        {"meta": "x"},  # 真值非 dict → meta.get 崩（现隔离）
        {"meta": 7},
        {"meta": [1]},
        {"completed": 7},  # 真值非可迭代 → set() 崩（现隔离）
        {"completed": [{"x": 1}]},  # 成员不可哈希 → set() 崩（现隔离）
        {"results": 7},  # 真值非可迭代 → for 崩（现隔离）
        {"errors_report": 7},  # list() 崩（现隔离）
        {"meta": {"total_chunks": "x"}},  # int() 崩（现隔离）
    ],
)
def test_state_load_malformed_fields_quarantine(
    tmp_path: Path, doc: dict[str, Any]
) -> None:
    """回归钉：字段级类型脏隔离回 ``(set(), {})`` 而非抛。"""
    d = tmp_path / "s"
    d.mkdir()
    (d / "state.json").write_text(json.dumps(doc), encoding="utf-8")
    assert StateStore(d).load() == (set(), {})


def test_fuzz_load_cache_never_raises(tmp_path: Path) -> None:
    """cache-*.json 变异：坏 JSON → 隔离改名 + {}；非 dict JSON → {} 不隔离。"""
    rng = fuzz_rng(20261017)
    for i in range(300):
        d = tmp_path / f"c{i}"
        d.mkdir()
        p = d / "cache-k.json"
        r = rng.random()
        if r < _P_LC_GARBAGE:
            # ASCII 垃圾必可解码——非 UTF-8 由 test_state_load_non_utf8_* 钉
            p.write_bytes(bytes(rng.randrange(128) for _ in range(rng.randint(0, 120))))
        elif r < _P_LC_SCALAR:
            p.write_text(json.dumps(rng.choice([[], "x", 42, 3.5])))
        else:
            p.write_text(json.dumps({"a": rng.choice(["t", 1, None, []]), "b": "keep"}))
        out = load_cache(p)
        assert isinstance(out, dict)
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in out.items())
