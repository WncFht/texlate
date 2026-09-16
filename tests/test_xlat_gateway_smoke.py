"""真网关冒烟：http://127.0.0.1:3003 一次 swe-2-medium 往返验证硬契约。

默认 skip——`TEXLATE_LIVE=1` + `TEXLATE_GATEWAY_KEY` 俱备才跑（网络测试，CI 默认不触网）：

    TEXLATE_LIVE=1 TEXLATE_GATEWAY_KEY=… .venv/bin/python -m pytest tests/test_xlat_gateway_smoke.py -v
"""

import os

import pytest

from texlate.xlat import placeholders
from texlate.xlat.client import ChatClient, ChatOptions

GATEWAY_URL = os.environ.get("TEXLATE_GATEWAY_URL", "http://127.0.0.1:3003")
GATEWAY_KEY = os.environ.get("TEXLATE_GATEWAY_KEY", "")

_LIVE = os.environ.get("TEXLATE_LIVE") == "1"
pytestmark = pytest.mark.skipif(
    not (_LIVE and GATEWAY_KEY),
    reason="network test — set TEXLATE_LIVE=1 + TEXLATE_GATEWAY_KEY to run",
)


@pytest.mark.asyncio
async def test_free_set_discovery_live() -> None:
    """panel 免费集字段齐全、∩ /v1/models、探活至少一个可用。"""
    async with ChatClient(GATEWAY_URL, GATEWAY_KEY) as c:
        free = await c.discover_free_models()
    assert free, "panel 免费集为空——promo 全过期？"
    alive = [m for m in free if m.probe_ok]
    assert alive, f"免费集探活全灭：{[(m.uid, m.probe_error) for m in free]}"
    for m in alive:
        assert m.promo_end, f"{m.uid} promo_end 缺失"


@pytest.mark.asyncio
async def test_swe2_medium_placeholder_contract() -> None:
    """swe-2-medium 真实往返：译文保留全部占位符（C9 硬契约）。"""
    src = (
        "We propose a method [[MATH_1]] following prior work [[CITE_2]] "
        "and evaluate it on [[REF_3]]."
    )
    async with ChatClient(GATEWAY_URL, GATEWAY_KEY) as c:
        r = await c.chat(
            "swe-2-medium",
            [
                {
                    "role": "system",
                    "content": (
                        "Translate from English to Chinese. Keep all "
                        "[[TYPE_n]] placeholder tokens verbatim."
                    ),
                },
                {"role": "user", "content": src},
            ],
            options=ChatOptions(temperature=0.2, max_tokens=8192),
        )
    assert r.content.strip()
    # 硬契约：占位符一个不缺
    d = placeholders.diff(src, r.content)
    assert d.ok, f"占位符契约违约：{d.describe()}"
    # 计费/隐藏 prompt token 量级观测（不断言具体值——网关注入会飘）
    assert r.usage.prompt_tokens > 0
