"""Shared spec helpers — cross-spec machinery that is not kernel.

``devin_factory()`` is the standard paid gateway bundle (G5): a spec that
burns through the devin-2api gateway carries
``gateway_factory=devin_factory()`` so `bench run <spec>` needs no caller
injection. Client construction stays lazy inside GatewayFactory — the
first session.request() builds it, and construction IS the paid
assertion.

The wire client is ``GatewayChat``: a SYNC facade over the async
``texlate.xlat.client.ChatClient``, because ``PaidSession.request()`` is
a synchronous call path. The facade owns one daemon event loop and runs
every coroutine through it — safe from both bare worker threads and
async-owned cells (which should call ``session.request`` via
``asyncio.to_thread`` so the paid-slot blocking never freezes their
loop).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from kernel import events, vault
from kernel import paid as paidmod

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_PRICES",
    "GatewayChat",
    "PaidEscape",
    "SessionClient",
    "SessionTranslator",
    "TimedTranslator",
    "devin_factory",
]

# The one and only paid endpoint — texlate is hard-pinned to the local
# devin-2api gateway + swe-2-medium (see project memory: all shims fold
# into 127.0.0.1:3033; llm7/pollinations/prism were deleted, never re-add).
DEFAULT_BASE_URL = "http://127.0.0.1:3033"
DEFAULT_MODEL = "swe-2-medium"

# Nominal per-token price surface. swe-2-medium rides a promo that bills
# $0 until 2026-10-16, but the meter still needs non-empty prices or the
# kernel refuses the run — and a nominal table keeps --max-cost a REAL
# fuse the day the promo lapses (order-of-magnitude stand-in, not a
# tariff sheet; specs needing exact accounting pass ``prices``).
DEFAULT_PRICES = {
    "swe-2-medium": {"in_per_mtok": 2.0, "out_per_mtok": 8.0},
    "*": {"in_per_mtok": 2.0, "out_per_mtok": 8.0},
}


class _Pump:
    """One daemon event loop on its own thread.

    ``run(coro)`` blocks the CALLER until the coroutine finishes — safe
    from any thread, including threads already running a loop (never call
    this from inside the pump's own loop; nothing here does).
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._t = threading.Thread(
            target=self._loop.run_forever, name="gw-pump", daemon=True
        )
        self._t.start()

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()


class GatewayChat:
    """Sync facade over texlate ``ChatClient`` for PaidSession.request.

    One instance = one pump + one lazily-built ChatClient living on the
    pump's loop (connection reuse across requests; httpx clients are
    loop-bound so the client must be built AND used on the same loop).

    ``chat(model=..., messages=..., **opts) -> dict`` mirrors the old
    stage_xlat call shape: returns ``{"text", "reasoning", "model",
    "finish_reason", "latency_s", "usage": {in_tok, out_tok}}`` — the
    usage dict feeds ``paid._usage_of`` straight into the meter.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        *,
        stream_fallback=None,
        timeout=None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self._stream_fallback = stream_fallback
        self._timeout = timeout
        self._pump = _Pump()
        self._client = None

    def _cli(self):
        if self._client is None:

            async def _make():
                from texlate.xlat.client import ChatClient

                return ChatClient(
                    self.base_url,
                    self.api_key,
                    timeout=self._timeout,
                    stream_fallback=self._stream_fallback,
                )

            self._client = self._pump.run(_make())
        return self._client

    def chat(self, model=None, messages=None, *, options=None, **kw):
        """One chat round-trip. ``options`` is a ChatOptions; remaining
        kwargs (temperature/max_tokens/response_format/extra) are folded
        into one when options is absent."""
        cli = self._cli()
        if options is None and kw:
            from texlate.xlat._dialects import ChatOptions

            options = ChatOptions(**kw)

        async def _go():
            return await cli.chat(model or self.model, messages or [], options=options)

        res = self._pump.run(_go())
        return {
            "text": res.content,
            "reasoning": res.reasoning,
            "model": res.model,
            "finish_reason": res.finish_reason,
            "latency_s": res.latency_s,
            "usage": {
                "in_tok": res.usage.prompt_tokens,
                "out_tok": res.usage.completion_tokens,
            },
        }


def devin_factory(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    prices=None,
    nslots: int = 4,
) -> paidmod.GatewayFactory:
    """The standard bench paid factory: devin-2api + swe-2-medium.

    ``api_key``/``base_url`` default to the env credentials chain
    (TEXLATE_API_KEY -> TEXLATE_GATEWAY_KEY -> ""; TEXLATE_BASE_URL ->
    loopback gateway). ``prices`` overrides the nominal table.
    """
    from texlate.xlat.client import env_key_for_url

    url = base_url or DEFAULT_BASE_URL
    key = api_key if api_key is not None else env_key_for_url(url)
    mdl = model or DEFAULT_MODEL

    def build(_ctx=None):
        return GatewayChat(url, key, mdl)

    return paidmod.GatewayFactory(
        build, prices=dict(prices or DEFAULT_PRICES), nslots=nslots
    )


# ---------------------------------------------------------------- paid bridge
#
# The consuming side of the paid lane: adapters that let texlate's async
# machinery (GatewayTranslator / XlatPipeline / fixloop llm_hook) ride a
# kernel PaidSession, so every wire call stays inside claim / paid_slot /
# meter / PAUSE / AUTH_DEAD / abort / budget enforcement.

_PAID_ESCAPE = (
    paidmod.PaidPause,
    paidmod.PaidAbortRun,
    paidmod.PaidAbortCell,
    paidmod.BudgetExceeded,
)


class PaidEscape(BaseException):
    """Escape pod for kernel paid exceptions raised inside a pipeline.

    ``XlatPipeline``'s per-chunk ``except Exception`` nets (worker/batch/
    warmup paths) would otherwise swallow ``PaidPause``/``PaidAbortRun``/
    ``PaidAbortCell``/``BudgetExceeded`` into skipped chunks — a TERMINAL
    fail that never retries, which breaks the PAUSE contract (cells
    burned mid-pause must land ``error``/``cat=pause`` so a later run
    picks them up) and silently drops PaidAbortRun's run-abort and
    BudgetExceeded's reject semantics. As a ``BaseException`` the pod
    rides the pipeline's fatal lane (``except BaseException`` → fatal
    ledger → ``_drain`` re-raise) out through ``asyncio.run``; the stage
    fn then unwraps with ``except PaidEscape as e: raise e.orig`` and
    the kernel's paid exception map sees the original.

    ``BaseException`` is load-bearing: anything less gets eaten by the
    very nets this exists to escape.
    """

    def __init__(self, orig: BaseException) -> None:
        super().__init__(f"{type(orig).__name__}: {orig}")
        self.orig = orig


def _respot_paid(exc: BaseException, *, feed_gate: bool) -> BaseException:
    """Re-pot a kernel paid exception for its journey through texlate.

    ``feed_gate=True`` (the XlatPipeline lane): ``paid.AuthError``
    converts to texlate ``xlat._errors.AuthError`` — a ChatError, so
    ``_kind_of`` files it "auth" and the designed AuthGate threshold →
    AuthTrippedError lane survives the bridge (unconverted it would
    classify "crash" and the circuit never trips on bridged 401s).
    ``feed_gate=False`` (fixloop llm_hook — no gate downstream): AuthError
    escapes with the rest of the family so dead credentials kill the
    cell (kernel error+auth_dead) instead of degrading rounds silently.
    """
    if feed_gate and isinstance(exc, paidmod.AuthError):
        from texlate.xlat._errors import AuthError as XlatAuth

        return XlatAuth(str(exc), status=int(getattr(exc, "status", 0) or 401))
    if isinstance(exc, (*_PAID_ESCAPE, paidmod.AuthError)):
        return PaidEscape(exc)
    return exc


class SessionClient:
    """ChatClient-shaped async shim over a PaidSession (GatewayTranslator side).

    ``chat()`` runs ``session.request`` via ``asyncio.to_thread`` so the
    paid-slot wait never freezes the caller's loop — ``chat_s`` therefore
    includes queueing time (consuming specs note the req_timing skew).
    ``chat_calls``/``chat_s`` are the wire-level counters.
    """

    def __init__(self, session) -> None:
        self._s = session
        self.chat_s = 0.0
        self.chat_calls = 0

    async def chat(self, model, messages, *, options=None):
        t0 = time.monotonic()
        try:
            res = await asyncio.to_thread(
                self._s.request, "chat", model, messages, options=options
            )
        except Exception as e:
            respotted = _respot_paid(e, feed_gate=True)
            if respotted is e:
                raise
            raise respotted from e
        finally:
            self.chat_s += time.monotonic() - t0
            self.chat_calls += 1
        return SimpleNamespace(
            content=res["text"],
            reasoning=res.get("reasoning") or "",
            finish_reason=res.get("finish_reason") or "",
            model=res.get("model") or model,
            latency_s=res.get("latency_s") or 0.0,
        )


class TimedTranslator:
    """``translate()`` outer span/call counter — pass-through attrs via
    ``__getattr__`` (``StateStore(model=translator.model)`` keeps working)."""

    def __init__(self, inner) -> None:
        self._i = inner
        self.calls = 0
        self.span_s = 0.0

    def __getattr__(self, k: str):
        if k == "_i":
            raise AttributeError(k)
        return getattr(self._i, k)

    async def translate(self, **kw):
        t0 = time.monotonic()
        try:
            return await self._i.translate(**kw)
        finally:
            self.span_s += time.monotonic() - t0
            self.calls += 1


class SessionTranslator:
    """Translator-protocol shim over a PaidSession (fixloop llm_hook side).

    A bare ChatClient here would bypass meter/claim/slot enforcement —
    every paid call must ride the session. Whole paid family escapes
    (AuthError included): the hook lane has no auth gate to feed.
    """

    def __init__(self, session, model: str) -> None:
        self._s = session
        self.model = model

    async def translate(
        self, *, system, user, temperature, max_tokens, response_format=None
    ) -> str:
        from texlate.xlat._dialects import ChatOptions

        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            res = await asyncio.to_thread(
                self._s.request,
                "chat",
                self.model,
                msgs,
                options=ChatOptions(
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                ),
            )
        except Exception as e:
            respotted = _respot_paid(e, feed_gate=False)
            if respotted is e:
                raise
            raise respotted from e
        return res["text"]


# ------------------------------------------------------------ records 末条账
#
# 「末条账·跨全 run」投影是 spec 层公共判读件：ctx.upstream_rec 是
# run∪foreign_runs 域，run2 里 run1 的账出域（本 run 那行是 dedup 非
# DONE）——on 谓词/want_fix/expect_cjk/质检补票这些「上游账」判读必须读
# 全域，否则跨 run 续跑全部看成 None 走歪。soak/e2e_real/quality 曾各
# 藏一份同构副本，统一收此处。

_DONE_STS = tuple(sorted(events.STATUS_DONE))

#: IN 位串只插占位符个数（模块级常量）——值仍全参数化。
_LAST_DONE_SQL = (
    "SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"  # noqa: S608
    "fp,dur_s,metrics,errors,ts FROM records "
    "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=? "
    f"AND status IN ({','.join('?' * len(_DONE_STS))}) "
    "ORDER BY rowid DESC LIMIT 1"
)

_LAST_ANY_SQL = (
    "SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
    "fp,dur_s,metrics,errors,ts FROM records "
    "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=? "
    "ORDER BY rowid DESC LIMIT 1"
)

_LAST_STS_SQL = (
    "SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
    "fp,dur_s,metrics,errors,ts FROM records "
    "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=? "
    "AND status=? ORDER BY rowid DESC LIMIT 1"
)


def _last_row(
    ctx,
    stage: str,
    *,
    done_only: bool = False,
    status: str | None = None,
    variant: str | None = None,
) -> dict | None:
    """末条账（任意 status；done_only=True 时同 _last_done 旧口径）。

    ``status`` 等值过滤钉到指定账——declined 闸行也占 DONE 位会遮蔽
    早先真账，质检补票须钉 ok。``variant`` 覆盖 ctx.variant——quality
    的 ctx.variant 带 @EPOCH 后缀查不了源账，须显式传源 variant。
    """
    idx = ctx.index
    if idx is None:
        return None
    var = ctx.variant if variant is None else variant
    if status is not None:
        row = idx.conn.execute(
            _LAST_STS_SQL, (ctx.idc, ctx.arm, ctx.up, var, stage, status)
        ).fetchone()
    elif done_only:
        row = idx.conn.execute(
            _LAST_DONE_SQL, (ctx.idc, ctx.arm, ctx.up, var, stage, *_DONE_STS)
        ).fetchone()
    else:
        row = idx.conn.execute(
            _LAST_ANY_SQL, (ctx.idc, ctx.arm, ctx.up, var, stage)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for col in ("metrics", "errors"):
        v = d.get(col)
        if isinstance(v, str):
            with contextlib.suppress(ValueError):
                d[col] = json.loads(v)
        d[col] = ctx._unblob(d[col])
    return d


def _last_done(ctx, stage: str, variant: str | None = None) -> dict | None:
    """末条 DONE 账·跨全 run——``_needs_eval`` 的 dedup-look-through 同域。"""
    return _last_row(ctx, stage, done_only=True, variant=variant)


# ------------------------------------------------------------ spec 管线小件
#
# soak→e2e_real 逐字复用簇（_gate/_swap_in/_ensure_kind/_xlat_marker/
# _compile_judge）+ CaseSink→emit_case 桥——原散于 soak.py/e2e_real.py/
# fixloop_bench.py 的同形副本收此（soak 改一处 e2e_real 不跟的漂移面）。
# 函数级惰性 import（engine_for/CaseSink/benchlib）保本模块顶层无
# texlate/specs 依赖——qualbench/xlatbench 不 _bootstrap.ensure() 也照载。


def _gate(
    status: str, code: str, cat: str, payload, metrics: dict | None = None
) -> dict:
    """旧 stagerun gate_rec 的 return-dict 版：status + 单条 errors +
    可选 metrics；sig 由内核 errors[0] cat:pay 自动合成。"""
    out = {
        "status": status,
        "code": code,
        "errors": [{"code": code, "cat": cat, "payload": payload}],
    }
    if metrics:
        out["metrics"] = metrics
    return out


def _swap_in(stage_dir: Path, dst: Path) -> None:
    """暂存树 → dst 的 rename 接力（旧 stagerun_lib.swap_in 同式）。"""
    old = stage_dir.with_name(f"{stage_dir.name}-old")
    if dst.exists():
        if old.exists():
            shutil.rmtree(old)
        os.rename(dst, old)
    os.rename(stage_dir, dst)
    if old.exists():
        shutil.rmtree(old)


def _ensure_kind(ctx, kind: str) -> Path | None:
    """本 run 的 mutates-kind 读径：同 run 上游产物优先，缺席则 vault
    restore(mode="copy") 物化全部已封 kind（0444 融合树的 可写副本
    口径——消费方可能要改）。无完好 vault 副本 → None。"""
    d = ctx.upstream_asset_dir(kind)
    if d is not None:
        return d
    with contextlib.suppress(vault.VaultError):
        vault.restore(ctx.idc, ctx.arm, ctx.variant, ctx.paper_dir(), mode="copy")
    return ctx.upstream_asset_dir(kind)


def _xlat_marker(zh: Path) -> dict | None:
    """``zh.-/.xlat-arm.json`` → dict；zh/ marker 缺席 → None。"""
    p = zh / ".xlat-arm.json"
    if not zh.is_dir() or not p.exists():
        return None
    try:
        doc = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


def _compile_judge(
    work: Path,
    main_rel: str,
    eng_name: str,
    timeout: float,
    *,
    expect_cjk: bool,
) -> dict:
    """best-effort 编译 + judge → {compile, verdict, status}。"""
    from specs import _benchlite as benchlib
    from texlate.compile.engine import engine_for

    kw = {"halt_on_error": False} if eng_name == "xelatex" else {}
    res = engine_for(eng_name, **kw).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    return benchlib.judge_dict(res, expect_cjk=expect_cjk)


def case_bridge(ctx):
    """CaseSink → ctx.emit_case 桥实例（soak/e2e_real/fixloop_bench 同款）：
    record 行形状逐字进 cases 账道；文件落点 /dev/null（ledger+cases.jsonl
    由内核原子写，双重落盘只会留两份漂移面——旧 _dedup_cases 末行胜去重
    由账道末行胜天然覆盖）。fixloop_bench 的具名 kwargs
    (corpus_id/cond/engine) 由 ``**kw`` 直通承载。惰性 CaseSink 载入：
    本模块顶层不依赖 texlate。"""
    from texlate.compile.fixloop import CaseSink

    class _CaseBridge(CaseSink):
        def __init__(self, ctx) -> None:
            super().__init__(os.devnull)
            self._ctx = ctx

        def record(self, cell, **kw):
            rec = super().record(cell, **kw)
            self._ctx.emit_case(rec)
            return rec

    return _CaseBridge(ctx)
