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
import threading

from kernel import paid as paidmod

__all__ = ["DEFAULT_BASE_URL", "DEFAULT_MODEL", "DEFAULT_PRICES",
           "GatewayChat", "devin_factory"]

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
            target=self._loop.run_forever, name="gw-pump", daemon=True)
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

    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str = "",
                 model: str = DEFAULT_MODEL, *, stream_fallback=None,
                 timeout=None) -> None:
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
                    self.base_url, self.api_key,
                    timeout=self._timeout,
                    stream_fallback=self._stream_fallback)
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
            return await cli.chat(model or self.model, messages or [],
                                  options=options)

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


def devin_factory(*, base_url: str | None = None, api_key: str | None = None,
                  model: str | None = None, prices=None,
                  nslots: int = 4) -> paidmod.GatewayFactory:
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
        build, prices=dict(prices or DEFAULT_PRICES), nslots=nslots)
