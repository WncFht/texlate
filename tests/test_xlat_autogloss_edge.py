"""autogloss 边界回归钉：``_pick_corpus`` 首元素超 cap 仍进料（整篇不丢）。

配合 ``test_xlat_autogloss.py`` 的 stride/打包钉——本件只钉
first-element-over-cap 回归面（旧 ``acc + len(t) > cap`` 先判把首块也挡掉，
全篇静默返回 ``{}``；修复后与 ``_pack_batches`` 的 oversized-singleton
合同一致：首条等距候选恒进料）。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from texlate.xlat import autogloss as ag
from texlate.xlat import client as cl

_BASE = "http://mock.local:3033"


def _ok(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "swe-2-medium",
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def _mock(plan: list[httpx.Response]) -> tuple[cl.ChatClient, list[httpx.Request]]:
    """按请求序回放 plan（同 test_xlat_autogloss 的 MockTransport 模式）。"""
    reqs: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        reqs.append(r)
        return plan[min(len(reqs), len(plan)) - 1]

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return cl.ChatClient(_BASE, "k", http=http), reqs


class TestPickCorpusEdge:
    def test_first_over_cap_still_picked(self) -> None:
        """首块即超 cap → 仍返回它（旧码 ``picked`` 空即 ``break`` → 全篇丢）。"""
        srcs = ["a" * 5000, "b" * 100, "c" * 100]
        assert ag._pick_corpus(srcs, 4800) == [srcs[0]]  # noqa: SLF001

    def test_oversize_first_still_extracts(self) -> None:
        """e2e：全篇唯一候选超 cap 时仍发出一次抽取调用，不再静默 ``{}``。"""
        client, reqs = _mock([_ok(json.dumps([{"src": "x", "tgt": "译"}]))])
        got = asyncio.run(
            ag.extract_terms(["a" * 5000], client, batch_chars=2400, max_batches=1)
        )
        assert len(reqs) >= 1
        assert got == {"x": "译"}
