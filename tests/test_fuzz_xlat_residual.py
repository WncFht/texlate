"""xlat 编排残余面 fuzz——split 臂簿记 / 解码序锻造洞 / 批成员缓存旁路 / dup-id。

与 ``test_fuzz_xlat.py``（广撒网不变量 + fault 矩阵 oracle）、
``test_fuzz_xlat_batch.py``（批协议标记归属 + 槽位臂）、
``test_fuzz_xlat_retry.py``（退避/阶梯机械）的分工：本文件收编排层残余——
``_process`` split 臂聚合、``decode_newlines`` 先于校验/拦截的锻造面、
批路径段级缓存旁路、``retranslate_chunk`` 结果形、``run()`` 入口 dup-id。

CONFIRMED（xfail-strict，D# 与 ``tmp/fuzz-xlat-batch/findings.*`` 台账同号）：

- D1 ``_process`` split 臂不聚合 ``attempts``——父块恒 ``attempts=0``，
  ``AuthGate.record`` 按 ``attempts==0 and not error_kind`` 判「没发请求不置证」
  → 真发过 N 次请求的全成功 split 父块不清零 ``consecutive``、不计
  ``non_auth``、``all_failed`` 假阳。跨论文熔断调用方据此误累计。
- D2 split 任一 piece fault/skipped → 父块 ``skipped=True`` 但
  ``translation=" ".join(pieces)`` 混入原文片段 ≠ ``source``——违反
  ``_skip``/fallback_orig 一路钉住的 ``skipped ⇒ translation == source``
  簿记不变量（``test_fuzz_xlat`` oracle 明列）。splice 按 status 闸不吃它，
  但 state.json/DB chunks 行以 fallback 语义持久化了半译半成品。
- D3 裸 token 锻造洞——``decode_newlines`` 先于 ``diff``/三张拦截网：
  模型应答里凭空铸 ``[[SL]]``/``[[PL]]``/``[[SP]]``/``[[NBSP]]``/
  ``[[THINSP]]``/``[[MEDSP]]``/``[[THICKSP]]``/``[[NEGSP]]`` 全部静默解码成
  ``\\n``/``\\n\\n``/``\\ ``/``~``/``\\,``/``\\:``/``\\;``/``\\!``——
  对账看不见（src 侧本就是真字符非 token，``diff`` 只数 ``[[..]]`` 多重集），
  ``bare_cs_net`` 不收控制符号，``\\:``/``\\;``/``\\!`` 是数学模式专属命令，
  落进文本域即编译炸弹，一路 ``status=ok`` 交付 splice。对照组：铸
  ``[[MATH_9]]`` 被 ``_intercept_leftover_ph`` 拦降 fault。同洞反向：
  模型丢 ``[[SL]]`` 同样无信号（``source_sl``/``source_pl`` 计数产出后
  无任何消费方）。
- D4 批成员不查段级缓存——``_one_batch`` 直发 ``encode_batch`` 全员，
  缓存命中的 short 块仍烧进批载荷且新应答静默覆盖原缓存条目
  （``_cache_store``）；single/split 路径经 ``_one_chunk`` 正常查命中。
  旁证：批不可重试错误时 ``_skip`` 连坐也跳过逐成员缓存命中。

PLAUSIBLE（只进 findings，不钉 xfail）：

- P1 ``run()`` 不查 ``chunk_id`` 唯一——dup id 两块全路由全处理，
  ``done_map[cid]`` 后写盖前写，返回表同位同对象：首位块领到次位的
  source+translation（静默错配）。产品侧 ``e2e`` ``{fidx}:{cid}`` 命名
  保证唯一——属垃圾进，但 pipeline 不拒也不查。
- P2 空/纯空白块（``is_placeholder_only`` 判 False）走批→批毒→退单翻→
  空 user 直发模型→任意应答以 ``ok`` 交付；``_delivered`` 只看译文非空。

OBSERVED 钉（现行行为留档，定性待裁）：

- ``retranslate_chunk`` fault 形 ``skipped=False``（ladder fallback_orig
  同语义置 True）——下游 ``chunk_error_code`` 殊途同归 ``validate``，
  簿记形不一致而已。
- worker BaseException（KI 模拟）→ ``fatal`` 收账→排空→``run`` 重抛不挂死。
- ``GatewayTranslator`` length 放大臂：``max_tokens<32768`` 时内联放大重试
  一次即升 32768；已顶格则不再放大；``max_tries`` 内每轮各带一次放大尝试。
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import (
    Finding,
    fuzz_rng,
    soup_join,
    soup_pick,
    write_findings,
    xfail_confirmed,
)

from texlate.xlat import pipeline as xp
from texlate.xlat import placeholders as ph
from texlate.xlat.batch import split_long_chunk
from texlate.xlat.client import AuthError, ChatError, LengthTruncatedError
from texlate.xlat.retry import RetryPolicy
from texlate.xlat.state import ChunkRecord, StateStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from texlate.xlat.client import ChatOptions

# ---------------------------------------------------------------- 标记与底料

#: 内容驱动 fault 注入标记（``\x00`` 包裹——自然 chunk 不可能的形态）
_M_AUTH = "\x00AUTH\x00"
_M_E5XX = "\x00E5XX\x00"
_M_BAD = "\x00BAD\x00"  # 校验永不放行（marker 在 src 侧即判死）
_M_KI = "\x00KI\x00"  # KeyboardInterrupt 注入

#: 裸 token → 解码字面（D3 锻造洞武器表：换行系 + ``_SPACE_FAM`` 空白系）
_FORGE_TOKENS: list[tuple[str, str]] = [
    ("[[SL]]", "\n"),
    ("[[PL]]", "\n\n"),
    ("[[SP]]", "\\ "),
    ("[[NBSP]]", "~"),
    ("[[THINSP]]", "\\,"),
    ("[[MEDSP]]", "\\:"),
    ("[[THICKSP]]", "\\;"),
    ("[[NEGSP]]", "\\!"),
]

_FUZZ_ITERS = 400
_SENT_BLOCK = "sentence body number nine. "  # 铺 split/长度控制的底料
_HARD = 120  # 与 _cfg 的 hard_limit 同源——oracle 复算切点用


class _T:
    """录制型 marker translator——行为只看 ``user`` 内容，与调度序无关。

    - ``_M_AUTH`` → AuthError(401)；``_M_E5XX`` → retryable ChatError；
      ``_M_KI`` → KeyboardInterrupt；
    - ``response_format`` 请求（slots 臂）→ 每槽回 ``"槽译"``；
    - 全 ``[n]`` 行批请求 → ``batch_fn``（缺省逐行回显正文，走真解析）；
    - 其余 → ``single_fn``（缺省 ``"zh:"+user`` 回显）。
    """

    def __init__(
        self,
        batch_fn: Callable[[str], str] | None = None,
        single_fn: Callable[[str], str] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.batch_fn = batch_fn
        self.single_fn = single_fn or (lambda u: f"zh:{u}")

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """按内容路由应答/异常。"""
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "rf": response_format,
            }
        )
        if _M_AUTH in user:
            msg = "denied"
            raise AuthError(msg, status=401)
        if _M_E5XX in user:
            msg = "boom5xx"
            raise ChatError(msg, status=500, retryable=True)
        if _M_KI in user:
            msg = "simulated"
            raise KeyboardInterrupt(msg)
        if response_format is not None:
            payload = json.loads(user)
            slots = payload.get("slots") or {}
            return json.dumps(dict.fromkeys(slots, "槽译"), ensure_ascii=False)
        if user.startswith("[1]"):
            if self.batch_fn is not None:
                return self.batch_fn(user)
            return "\n".join(
                f"{m.group(1)} zh:{m.group(2)}"
                if (m := re.match(r"^(\[\d+\])\s?(.*)$", ln, re.DOTALL))
                else ln
                for ln in user.split("\n")
            )
        return self.single_fn(user)


def _cfg(**kw: object) -> xp.PipelineConfig:
    """串行小预算：short 80 / batch 2000 / hard 120——split 臂伸手可及。"""
    args: dict[str, object] = {
        "concurrency": 1,
        "short_limit": 80,
        "batch_max_chars": 2000,
        "hard_limit": _HARD,
    }
    args.update(kw)
    return xp.PipelineConfig(**args)  # type: ignore[arg-type]


def _bad_validator(src: str, zh: str) -> str:
    """``_M_BAD`` 在 **src** 侧即判死（钉阶梯全阶段）；余走默认对账。"""
    if _M_BAD in src:
        return "bad marker in source"
    return ph.diff(src, zh).describe()


def _run(
    chunks: list[xp.ChunkIn],
    t: _T,
    *,
    validator: Callable[[str, str], str] | None = None,
    cfg: xp.PipelineConfig | None = None,
) -> list[xp.ChunkResult]:
    p = xp.XlatPipeline(t, config=cfg or _cfg(), validator=validator or _bad_validator)
    return asyncio.run(p.run(chunks))


def _split_doc(n_rep: int = 40) -> str:
    """超 hard_limit 的长块底料（>120B ⇒ split 路由）。"""
    return _SENT_BLOCK * n_rep


# ---------------------------------------------------------------- D1: split 臂 attempts 不聚合 → auth 闸盲


class TestSplitAttemptsAccounting:
    """D1：split 父块恒 ``attempts=0``——真发过请求的块在 auth 闸里「没发请求」。"""

    @xfail_confirmed(
        "D1: split 父块 attempts 不聚合——恒 0（pipeline.py `_process` split 臂"
        " 建 ChunkResult 不带 attempts）；真实多请求成功块对 auth 闸不可见"
    )
    def test_split_parent_attempts_aggregated(self) -> None:
        """契约：split 父块 ``attempts`` = 各 piece 阶梯尝试之和。"""
        t = _T()
        res = _run(
            [xp.ChunkIn("big", _split_doc(), "para")],
            t,
            validator=lambda _s, _z: "",
        )
        assert res[0].status == "ok"
        n_req = len(t.calls)
        assert n_req >= 2  # noqa: PLR2004 -- >120B 硬限下 ≥2 piece 各至少一请求
        assert res[0].attempts == n_req

    @xfail_confirmed(
        "D1: 全成功 split 不提供 non_auth 证据——all_failed 假阳"
        "（auth_failures>0 且 non_auth==0，尽管 split 真发过请求且成功）"
    )
    def test_split_success_counts_as_non_auth_evidence(self) -> None:
        """契约：发过请求且成功的 split 父块应计 ``non_auth``（清 consecutive）。"""
        p = xp.XlatPipeline(
            _T(), config=_cfg(auth_fail_threshold=0), validator=_bad_validator
        )
        chunks = [
            xp.ChunkIn("a1", f"auth fail {_M_AUTH}", "para"),
            xp.ChunkIn("big", _split_doc(), "para"),
        ]
        res = asyncio.run(p.run(chunks))
        assert res[0].error_kind == "auth"
        assert res[1].status == "ok"
        gate = p.auth_gate
        assert gate.non_auth >= 1
        assert not gate.all_failed

    def test_gate_evidence_matrix_observed(self) -> None:
        """observed 对照：single ok 计 non_auth、cache-hit 不计——split 独盲。"""
        # single 成功块 → non_auth=1（对照组，证明闸本身工作）
        p = xp.XlatPipeline(_T(), config=_cfg(), validator=_bad_validator)
        asyncio.run(p.run([xp.ChunkIn("s", "x" * 100, "para")]))
        assert p.auth_gate.non_auth == 1
        # cache-hit → attempts=0 不计（符合「没发请求不置证」本意）
        p2 = xp.XlatPipeline(_T(), config=_cfg(), validator=_bad_validator, cache={})
        c = xp.ChunkIn("c", "y" * 100, "para")
        assert p2.cache is not None
        p2.cache[p2._seg_key(c)] = "缓存译文"  # noqa: SLF001
        asyncio.run(p2.run([c]))
        assert p2.auth_gate.non_auth == 0


# ---------------------------------------------------------------- D2: split fault → skipped 但译文非原文


class TestSplitFaultShape:
    """D2：split piece 失败 → 父块 ``skipped=True`` + 混合译文 ≠ 原文。"""

    @xfail_confirmed(
        "D2: skipped ⇒ translation==source 不变量在 split 臂破——"
        "piece 失败时父块 skipped=True 但 translation=merged（半译半成品）"
    )
    def test_split_fault_skipped_translation_not_source(self) -> None:
        """契约：``skipped=True`` 的块 ``translation`` 必须是原文回填。"""
        content = _SENT_BLOCK * 6 + f"bad {_M_AUTH} part " + _SENT_BLOCK * 6
        # 构造守卫：marker 须完整落在某 piece 内（切点漂移时此断言先于语义断言失败）
        assert any(
            _M_AUTH in piece for piece in split_long_chunk(content, max_chars=_HARD)
        )
        res = _run([xp.ChunkIn("big", content, "para")], _T())
        r = res[0]
        assert r.status == "fault"
        assert not (r.skipped and r.translation != r.source)

    def test_split_fault_merged_shape_observed(self) -> None:
        """observed：merged = 成功 piece 译文 + 失败 piece 原文，``" "`` 拼接。"""
        content = _SENT_BLOCK * 6 + f"bad {_M_AUTH} part " + _SENT_BLOCK * 6
        assert any(
            _M_AUTH in piece for piece in split_long_chunk(content, max_chars=_HARD)
        )
        res = _run([xp.ChunkIn("big", content, "para")], _T())
        r = res[0]
        assert r.status == "fault"
        assert r.skipped
        assert r.skip_reason == "split piece(s) failed"
        assert _M_AUTH in r.translation  # 失败 piece 原文混入 merged
        assert "zh:" in r.translation  # 成功 piece 译文同锅
        assert r.error_kind == "auth"
        assert r.batch_id == ""

    def test_fuzz_split_worst_status_oracle(self) -> None:
        """随机 piece 成败混合——``split_long_chunk`` 复算 piece 集做自证 oracle。

        marker 完整落进某 piece ⇒ 该 piece 失败（translation=piece 原文）、
        父块 worst=fault/skipped、error_kind 按 marker 族；marker 被切散 ⇒
        全 ok。merged 逐 piece 可预测：``ok piece → "zh:"+piece``、
        ``fail piece → piece 原文``。
        """
        rng = fuzz_rng(20261211)
        want_kind = {_M_BAD: "validate", _M_AUTH: "auth", _M_E5XX: "provider"}
        for i in range(60):
            body = _SENT_BLOCK * rng.randint(4, 12)
            inject = rng.choice(["", _M_BAD, _M_AUTH, _M_E5XX])
            content = body + inject + body
            pieces = split_long_chunk(content, max_chars=_HARD)
            assert len(pieces) > 1  # 构造保证走 split 臂（min ~223B）
            hit = bool(inject) and any(inject in piece for piece in pieces)
            expected_merged = " ".join(
                piece if inject and inject in piece else f"zh:{piece}"
                for piece in pieces
            )
            res = _run([xp.ChunkIn(f"b{i}", content, "para")], _T())
            r = res[0]
            assert r.translation == expected_merged, (i, inject)
            if not hit:
                assert r.status == "ok", (i, r.status, r.skip_reason)
                assert not r.skipped
                assert r.error_kind == ""
            else:
                assert r.status == "fault", (i, r.status)
                assert r.skipped
                assert r.error_kind == want_kind[inject]

    def test_split_error_kind_priority(self) -> None:
        """observed：``auth`` 优先于首个非空 kind（piece 序）。"""
        content = (
            _SENT_BLOCK * 5 + _M_AUTH + _SENT_BLOCK * 5 + _M_E5XX + _SENT_BLOCK * 5
        )
        pieces = split_long_chunk(content, max_chars=_HARD)
        has_auth = any(_M_AUTH in piece for piece in pieces)
        has_e5 = any(_M_E5XX in piece for piece in pieces)
        res = _run([xp.ChunkIn("big", content, "para")], _T())
        r = res[0]
        if has_auth:
            assert r.error_kind == "auth"
        elif has_e5:
            assert r.error_kind == "provider"
        else:
            assert r.error_kind == ""
        assert (r.status == "fault") == (has_auth or has_e5)


# ---------------------------------------------------------------- D3: 裸 token 锻造洞（decode 先于校验）


class TestDecodeForgeHole:
    """D3：src 外裸 token 在应答里凭空铸出 → decode 成字面 → 全链路无信号交付。"""

    @xfail_confirmed(
        "D3: 锻造裸 token 静默解码交付——src 集合外的 [[NEGSP]] 等八族 token"
        " 经 decode_newlines 变 \\!/\\n\\n/~ 进 ok 译文；diff/拦截网全部看不见"
        "（对照：[[MATH_9]] 型带号 token 被 leftover 网拦降 fault）"
    )
    @pytest.mark.parametrize(("tok", "lit"), _FORGE_TOKENS)
    def test_forged_bare_token_silently_delivered(self, tok: str, lit: str) -> None:
        """契约：src 外的裸 token 应答不得静默解码成字面进交付译文。"""
        t = _T(single_fn=lambda _u, _t=tok: f"译文 {_t} 尾部")
        # 100B ∈ [short_limit, hard_limit)——单发路径（>120 会走 split 臂）
        res = _run([xp.ChunkIn("c", "x" * 100, "para")], t)
        r = res[0]
        # 修复形态不拘——拒收/降 fault/剥除皆可；唯独不许字面进 ok 译文
        assert lit not in r.translation or r.status != "ok"

    @xfail_confirmed(
        "D3: 批路径同洞——成员段内锻造的 [[NEGSP]] → \\! 进 batched ok 译文"
    )
    def test_forged_token_in_batch_member(self) -> None:
        """契约同上单发面——批解析后 ``decode_newlines(part)`` 同样无闸。"""
        t = _T(batch_fn=lambda _u: "[1] 译文 [[NEGSP]] 尾\n[2] 二号译文")
        res = _run(
            [
                xp.ChunkIn("m1", "member one", "para"),
                xp.ChunkIn("m2", "member two", "para"),
            ],
            t,
        )
        assert "\\!" not in res[0].translation or res[0].status != "ok"
        assert res[1].status == "ok"  # 干净成员不受连坐

    def test_typed_token_forged_caught_control(self) -> None:
        """对照组：validator 放行时 ``[[MATH_9]]`` 型带号 token 锻造仍被
        leftover 网拦降 fault——洞只在裸 token 族（decode 抹平后无迹可寻）。"""
        t = _T(single_fn=lambda _u: "译文 [[MATH_9]] 尾")
        # 100B ∈ [short_limit, hard_limit)——单发路径钉 leftover 网本体
        res = _run(
            [xp.ChunkIn("c", "x" * 100, "para")],
            t,
            validator=lambda _s, _z: "",
        )
        r = res[0]
        assert r.status == "fault"
        assert r.skipped
        assert r.translation == r.source
        assert r.error_kind == "validate"
        assert any("leftover_ph" in w for w in r.warnings)

    def test_dropped_sl_token_also_invisible(self) -> None:
        r"""observed 同洞反向：src 真 ``\n`` 编码成 ``[[SL]]`` 被模型丢弃 →
        zh 丢换行无任何信号（``source_sl``/``source_pl`` 计数产出后无消费方）。"""
        t = _T(single_fn=lambda _u: "译文无换行标记")
        res = _run([xp.ChunkIn("c", "line1\nline2 " + "x" * 200, "para")], t)
        r = res[0]
        assert r.status == "ok"  # 丢失静默交付（现行行为钉）
        assert "\n" not in r.translation

    def test_fuzz_forge_soup_all_tokens(self) -> None:
        """随机锻造汤：八族 token × 随机重复注进应答——现行行为下全部静默
        解码交付（本用例钉现行面；D3 修复落地后此钉翻转方向即回归守卫）。"""
        rng = fuzz_rng(20261212)
        for _ in range(_FUZZ_ITERS):
            tok, lit = soup_pick(rng, _FORGE_TOKENS)
            n_forge = rng.randint(1, 4)
            t = _T(single_fn=lambda _u, _t=tok, _k=n_forge: "译文" + _t * _k + "尾")
            res = _run(
                [xp.ChunkIn("c", "prose " + "x" * rng.randint(100, 400), "para")],
                t,
            )
            r = res[0]
            assert lit in r.translation  # 现行：锻造字面静默交付
            assert r.status == "ok"


# ---------------------------------------------------------------- D4: 批成员不查段级缓存


class TestBatchCacheBypass:
    """D4：``_one_batch`` 直发全员——缓存命中的 short 块仍烧进批载荷。"""

    @xfail_confirmed(
        "D4: 批成员不查段级缓存——缓存命中的 short 块仍入批烧 token，"
        "且新应答经 _cache_store 静默覆盖原缓存条目（single/long 路径正常命中）"
    )
    def test_cached_short_member_still_sent_in_batch(self) -> None:
        """契约：段级缓存命中的成员不进批载荷、直接回缓存译文零请求。"""
        p = xp.XlatPipeline(_T(), config=_cfg(), validator=_bad_validator, cache={})
        c_cached = xp.ChunkIn("cached", "already translated text", "para")
        assert p.cache is not None
        p.cache[p._seg_key(c_cached)] = "缓存译文"  # noqa: SLF001
        res = asyncio.run(
            p.run([c_cached, xp.ChunkIn("fresh", "brand new text", "para")])
        )
        assert res[0].translation == "缓存译文"
        assert res[0].attempts == 0  # 零请求

    def test_single_path_cache_hit_control(self) -> None:
        """对照组：long/single 路径缓存命中零请求直回（≤120B 防走 split——
        split 块按 piece 粒度查缓存，父键永不命中）。"""
        p = xp.XlatPipeline(_T(), config=_cfg(), validator=_bad_validator, cache={})
        c = xp.ChunkIn("c", "y" * 100, "para")
        assert p.cache is not None
        p.cache[p._seg_key(c)] = "缓存译文"  # noqa: SLF001
        res = asyncio.run(p.run([c, xp.ChunkIn("f", "z" * 100, "para")]))
        assert res[0].translation == "缓存译文"
        assert res[0].attempts == 0

    def test_nonretryable_batch_error_skips_cached_member(self) -> None:
        """observed（D4 旁证）：批 401 连坐 skip 也跳过逐成员缓存命中——
        有缓存条目照 skipped，等下轮续跑自愈。"""

        async def die(**_kw: object) -> str:
            msg = "denied"
            raise AuthError(msg, status=401)

        p = xp.XlatPipeline(
            type("DeadT", (), {"translate": staticmethod(die)})(),
            config=_cfg(auth_fail_threshold=0),
            validator=_bad_validator,
            cache={},
        )
        c_cached = xp.ChunkIn("cached", "already translated text", "para")
        assert p.cache is not None
        p.cache[p._seg_key(c_cached)] = "缓存译文"  # noqa: SLF001
        res = asyncio.run(
            p.run([c_cached, xp.ChunkIn("fresh", "brand new text", "para")])
        )
        # 现行：两块同罪 skipped（缓存命中成员也被连坐）
        assert [r.status for r in res] == ["skipped", "skipped"]


# ---------------------------------------------------------------- P1: dup chunk_id 塌缩（observed 钉 + findings）


class TestDupChunkId:
    """P1(PLAUSIBLE)：``run()`` 不查 id 唯一——dup id 静默错配。"""

    def test_dup_id_collapses_to_last_observed(self) -> None:
        """observed：两块同 id → 同位返回同一 ChunkResult 对象（后者盖前者）。"""
        res = _run(
            [
                xp.ChunkIn("dup", "first body here", "para"),
                xp.ChunkIn("dup", "second body here", "para"),
            ],
            _T(),
        )
        assert res[0] is res[1]  # done_map 单键——同对象两处回填
        assert res[0].source == "second body here"  # 首位领到次位源
        assert res[0].translation == "zh:second body here"

    def test_dup_id_ph_only_vs_prose(self) -> None:
        """observed：ph-only 先落 done_map、prose 后处理盖掉——位置序无关。"""
        res = _run(
            [
                xp.ChunkIn("dup", "[[MATH_1]]", "para"),
                xp.ChunkIn("dup", "real prose body", "para"),
            ],
            _T(),
        )
        assert res[0] is res[1]
        assert res[0].translation == "zh:real prose body"


class TestEmptyChunk:
    """P2(PLAUSIBLE)：空块不拒——退单翻把空 user 直发模型，任意应答交付。"""

    def test_empty_chunk_gets_arbitrary_ok(self) -> None:
        """observed：``""`` 块 → 批毒退单翻 → 空 user → ``"zh:"`` 以 ok 交付。"""
        t = _T(batch_fn=lambda _u: "garbage unparseable")
        res = _run(
            [
                xp.ChunkIn("e", "", "para"),
                xp.ChunkIn("ok", "real body", "para"),
            ],
            t,
        )
        # 空块没走 ph-only 短路（"" 不是占位符），批毒后退单翻拿到 "zh:"+"" 应答
        assert res[0].status == "ok"
        assert res[0].translation == "zh:"
        assert res[1].status == "ok"
        assert any(call["user"] == "" for call in t.calls)  # 空 user 真发了请求

    def test_resumed_poisoned_record_self_heals(self) -> None:
        """observed：state 里 status=ok 但含源外 token 的毒记录 → 装载时被
        leftover 网降 fault、滤出 completed → 本轮重翻自愈（不落 splice）。"""
        d = Path(tempfile.mkdtemp(dir="tmp/fuzz-xlat-batch"))
        st = StateStore(d)
        st.start(1)
        st.record(
            ChunkRecord(
                chunk_id="c0",
                source="plain text body here",
                translation="译文 [[MATH_9]]",
                status="ok",
                attempts=0,
            )
        )
        st.finish()
        p = xp.XlatPipeline(
            _T(),
            config=_cfg(),
            validator=_bad_validator,
            state=StateStore(d),
        )
        res = asyncio.run(p.run([xp.ChunkIn("c0", "plain text body here", "para")]))
        r = res[0]
        assert r.status == "ok"
        assert r.translation == "zh:plain text body here"
        assert r.attempts > 0  # 真重翻了——不是吃毒记录


# ---------------------------------------------------------------- retranslate_chunk 结果形（observed）


class TestRetranslateShape:
    """``retranslate_chunk`` L2 回灌面——observed 钉 + 拦截网沿用。"""

    def test_transport_crash_returns_none(self) -> None:
        """observed：传输层异常 → ``None``（保留原译，不算有效修复发）。"""

        async def boom(**_kw: object) -> str:
            msg = "dead"
            raise ConnectionError(msg)

        p = xp.XlatPipeline(
            type("DeadT", (), {"translate": staticmethod(boom)})(),
            config=_cfg(),
        )
        out = asyncio.run(
            p.retranslate_chunk(xp.ChunkIn("c", "src text", "para"), "err")
        )
        assert out is None

    def test_still_invalid_fault_shape(self) -> None:
        """observed：L0 仍败 → fault + translation=source + error_kind=validate，
        但 ``skipped=False``（与 ladder fallback_orig 的 ``skipped=True`` 异形——
        下游 ``chunk_error_code`` 殊途同归 ``validate``，簿记形不一致留档）。"""
        p = xp.XlatPipeline(
            _T(single_fn=lambda _u: "译文丢了占位符"),
            config=_cfg(),
            validator=_bad_validator,
        )
        r = asyncio.run(
            p.retranslate_chunk(
                xp.ChunkIn("c", "src [[MATH_1]] text", "para"), "compile err"
            )
        )
        assert r is not None
        assert r.status == "fault"
        assert r.translation == r.source
        assert r.error_kind == "validate"
        assert r.skipped is False  # 异形钉：fallback_orig 同语义置 True
        assert r.attempts == 1

    def test_intercepts_apply_on_ok(self) -> None:
        """observed：回灌 ok 结果同受 leftover 网——铸 ``[[MATH_9]]`` 降 fault。"""
        p = xp.XlatPipeline(
            _T(single_fn=lambda _u: "译文 [[MATH_9]] 尾"),
            config=_cfg(),
            validator=lambda _s, _z: "",
        )
        r = asyncio.run(
            p.retranslate_chunk(xp.ChunkIn("c", "plain src text", "para"), "err")
        )
        assert r is not None
        assert r.status == "fault"
        assert r.skipped
        assert r.error_kind == "validate"

    def test_decode_hole_shared(self) -> None:
        """observed（D3 同洞）：回灌路径 ``decode_newlines`` 同样先于校验。"""
        p = xp.XlatPipeline(
            _T(single_fn=lambda _u: "译文 [[NEGSP]] 尾"),
            config=_cfg(),
            validator=lambda _s, _z: "",
        )
        r = asyncio.run(
            p.retranslate_chunk(xp.ChunkIn("c", "plain src text", "para"), "err")
        )
        assert r is not None
        assert r.status == "ok"
        assert "\\!" in r.translation  # 现行：锻造字面静默交付


# ---------------------------------------------------------------- 编排残余观察钉


class TestOrchestraResidual:
    """worker BaseException / GatewayTranslator 放大臂 / 结果序幂等观察钉。"""

    def test_worker_keyboardinterrupt_reraises_no_hang(self) -> None:
        """observed(E3)：item 内 BaseException → fatal 收账排空 → run 重抛。"""
        p = xp.XlatPipeline(_T(), config=_cfg(), validator=_bad_validator)
        chunks = [
            xp.ChunkIn("k", f"body {_M_KI} text", "para"),
            xp.ChunkIn("n", "normal body text", "para"),
        ]
        with pytest.raises(KeyboardInterrupt):
            asyncio.run(p.run(chunks))

    def test_gateway_length_amplify_once_then_respect_policy(self) -> None:
        """observed：``max_tokens<32768`` 的 length 截断内联放大一次；
        ``call_with_backoff`` 每轮各带一次放大尝试（2 轮 ⇒ 至多 4 chat）。"""

        class _Cli:
            def __init__(self, fails: int) -> None:
                self.fails = fails
                self.seen: list[int] = []

            async def chat(
                self, _m: str, _msgs: list[dict[str, str]], *, options: ChatOptions
            ) -> SimpleNamespace:
                self.seen.append(options.max_tokens or 0)
                if len(self.seen) <= self.fails:
                    msg = "len"
                    raise LengthTruncatedError(msg)
                return SimpleNamespace(content="ok")

        async def go() -> tuple[list[int], list[int]]:
            c1 = _Cli(1)
            gt = xp.GatewayTranslator(
                c1,  # type: ignore[arg-type]
                "m",
                policy=RetryPolicy(max_tries=1, base_delay=0),
            )
            await gt.translate(system="s", user="u", temperature=0.1, max_tokens=100)
            c2 = _Cli(99)
            gt2 = xp.GatewayTranslator(
                c2,  # type: ignore[arg-type]
                "m",
                policy=RetryPolicy(max_tries=2, base_delay=0),
            )
            with pytest.raises(LengthTruncatedError):
                await gt2.translate(
                    system="s", user="u", temperature=0.1, max_tokens=100
                )
            return c1.seen, c2.seen

        seen1, seen2 = asyncio.run(go())
        assert seen1 == [100, 32768]
        assert seen2 == [100, 32768, 100, 32768]

    def test_gateway_at_cap_no_amplify(self) -> None:
        """observed：``max_tokens`` 已顶格 → 不放大，错误直穿。"""

        class _Cli:
            def __init__(self) -> None:
                self.seen: list[int] = []

            async def chat(
                self, _m: str, _msgs: list[dict[str, str]], *, options: ChatOptions
            ) -> SimpleNamespace:
                self.seen.append(options.max_tokens or 0)
                msg = "len"
                raise LengthTruncatedError(msg)

        async def go() -> list[int]:
            c = _Cli()
            gt = xp.GatewayTranslator(
                c,  # type: ignore[arg-type]
                "m",
                policy=RetryPolicy(max_tries=1, base_delay=0),
            )
            with pytest.raises(LengthTruncatedError):
                await gt.translate(
                    system="s",
                    user="u",
                    temperature=0.1,
                    max_tokens=xp.LENGTH_RETRY_MAX_TOKENS,
                )
            return c.seen

        assert asyncio.run(go()) == [32768]

    def test_run_result_order_and_source_echo(self) -> None:
        """observed：结果序 == 输入序，``source`` 逐块归位不错配。"""
        rng = fuzz_rng(20261213)
        soup = ["alpha ", "beta ", "[[MATH_1]]", "gamma ", "delta"]
        chunks = [
            xp.ChunkIn(
                f"c{i}",
                soup_join(rng, soup, 1, 10) + f" tag{i}",
                rng.choice(["para", "caption"]),
            )
            for i in range(10)
        ]
        res = _run(chunks, _T())
        assert [r.chunk_id for r in res] == [c.chunk_id for c in chunks]
        for c, r in zip(chunks, res, strict=True):
            assert r.source == c.content


# ---------------------------------------------------------------- findings 台账落盘


def test_write_findings_ledger() -> None:
    """台账写出——``tmp/fuzz-xlat-batch/findings.txt``（jsonl/md 由报告侧产出）。"""
    write_findings(
        Path("tmp/fuzz-xlat-batch/findings.txt"),
        title="xlat-residual-fuzz — B11 残余面台账",
        scope=(
            "pipeline split 臂簿记 / decode_newlines 先于校验的裸 token 锻造面 / "
            "批成员段级缓存旁路 / dup chunk_id / retranslate_chunk 结果形 / "
            "GatewayTranslator 放大臂 / worker BaseException"
        ),
        test_file="tests/test_fuzz_xlat_residual.py",
        status="4 CONFIRMED xfail-strict / 2 PLAUSIBLE / 观察钉一簇",
        confirmed=[
            Finding(
                "D1",
                "split 父块 attempts 不聚合 → AuthGate 盲（consecutive 不清/"
                "non_auth 不计/all_failed 假阳）",
                (
                    "site: src/texlate/xlat/pipeline.py `_process` split 臂 "
                    "(merged ChunkResult 无 attempts 字段)\n"
                    "repro: test_split_parent_attempts_aggregated + "
                    "test_split_success_counts_as_non_auth_evidence\n"
                    "probe: tmp/fuzz-xlat-batch/probe.py P1——2×auth + 1×全成功 "
                    "split(≥2 piece 真请求) → non_auth=0, all_failed=True\n"
                    "修法: split 臂聚合 attempts=sum(piece.attempts)；或 "
                    "AuthGate.record 增认 split 完成证据"
                ),
            ),
            Finding(
                "D2",
                "split fault → skipped=True 但 translation=merged≠source",
                (
                    "site: src/texlate/xlat/pipeline.py `_process` split 臂 "
                    "(skipped=(status=='fault') + translation=' '.join)\n"
                    "破 `skipped ⇒ translation==source` 不变量（test_fuzz_xlat "
                    "oracle 明列 + _skip/fallback_orig 一路同构）\n"
                    "blast radius: splice 按 status 闸不吃 merged；state.json/"
                    "DB chunks 行以 fallback 语义持久化半译文\n"
                    "修法: fault 父块 translation 回填 parent.source（或 "
                    "skipped 不置——两头都须保不变量）"
                ),
            ),
            Finding(
                "D3",
                "裸 token 锻造洞——decode_newlines 先于 diff/三拦截网，"
                "src 外 [[SL]]/[[PL]]/空间族 token 静默解码成交付字符",
                (
                    "sites: xlat/retry.py `_stage_whole`/`_stage_lines`/"
                    "`_assemble_slots`（decode→repair→validate 序）+ "
                    "xlat/pipeline.py `_one_batch`/`retranslate_chunk` 同款\n"
                    "八族 token 解码字面: SL→\\n PL→\\n\\n SP→`\\ ` NBSP→~ "
                    "THINSP→\\, MEDSP→\\: THICKSP→\\; NEGSP→\\!\n"
                    "\\:/\\;/\\! 是数学模式专属——文本域出现即编译炸弹；"
                    "bare_cs_net 不收控制符号、diff 只数 [[..]] 多重集、"
                    "leftover 网查 post-decode 文本\n"
                    "反向同洞：模型丢 [[SL]] 也无信号（source_sl/pl 计数无消费方）\n"
                    "对照: [[MATH_9]] 型被 leftover 网拦降 fault（对照钉在案）\n"
                    "修法: 校验前置到 decode 前按 token 多重集对账；或对 "
                    "decode 产物增字符级网（\\!\\:\\; 文本域检出）"
                ),
            ),
            Finding(
                "D4",
                "批成员不查段级缓存——缓存命中 short 块仍入批烧 token 且被覆盖",
                (
                    "site: src/texlate/xlat/pipeline.py `_one_batch`——直发 "
                    "encode_batch 全员，_cache_hit 只在 _one_chunk 内\n"
                    "repro: test_cached_short_member_still_sent_in_batch——"
                    "payload '[1] already translated text\\n[2] brand new text' "
                    "含已缓存成员；成功应答 _cache_store 覆盖原条目\n"
                    "旁证: 批 401 连坐 skip 也跳过逐成员缓存命中\n"
                    "修法: _build_work_items/_one_batch 前置逐成员 _cache_hit "
                    "短路（命中成员直接 _collect ok，不进批）"
                ),
            ),
        ],
        observed=[
            (
                "P1 dup chunk_id 塌缩：run() 不查唯一——同位返回同一 ChunkResult "
                "对象（source+translation 皆是后者），静默错配；e2e {fidx}:{cid} "
                "命名保证唯一，pipeline 不拒（PLAUSIBLE）"
            ),
            (
                "P2 空/纯空白块非 ph-only → 批毒退单翻 → 空 user 直发 → 任意应答 "
                "ok 交付（_delivered 只看译文非空）（PLAUSIBLE）"
            ),
            (
                "retranslate_chunk fault 形 skipped=False（fallback_orig 置 True "
                "异形）——chunk_error_code 殊途同归 validate"
            ),
            "worker BaseException→fatal 收账→排空→run 重抛不挂死（E3 钉）",
            (
                "GatewayTranslator length 放大：<32768 内联放大一次；顶格直穿；"
                "max_tries 轮各带一次放大（钉 seq [100,32768]*k）"
            ),
            "auth 熔断连坐 skip 不记 batch_id（_skip 默认 ''）",
        ],
        notes=[
            (
                "D3 修复方向若走「decode 前 token 多重集对账」：src_encoded 与 "
                "zh_raw 的八族 token 多重集须相等——哨兵族（[[__TEXLATE_*_LIT*__]]）"
                "已在 BARE_PH_RX 盲区外对称不可见，不计。"
            )
        ],
        scratch="tmp/fuzz-xlat-batch/probe*.py",
    )
