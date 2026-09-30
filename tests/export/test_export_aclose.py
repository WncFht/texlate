"""``export`` 网关臂 client 回收契约：``drive_pipeline`` in-loop ``aclose``。

网关 ``ChatClient`` 自持 httpx 池绑在管线 ephemeral loop 上——池必须在该
loop 存活时于其内 ``aclose()``；cli ``finally`` 的 ``asyncio.run`` 新 loop
关池是「foreign loop」坑（连接绑死 loop）。本文件钉死两节契约：

- ``_export_translator`` 网关臂产的 translator 暴露 ``aclose`` 且委托
  ``client.aclose``（``drive_pipeline`` 经 ``getattr`` 探到它才走 in-loop
  回收——此前网关臂无此件，只 mock/stub translator 有测试覆盖）；
- ``drive_pipeline`` 真在管线 loop 内 await ``aclose``（loop 事后被
  ``asyncio.run`` 收掉的证据 = ``is_closed()``）。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import texlate.cli as _cli
from texlate.export.common import ApplyCounts, drive_pipeline
from texlate.xlat.pipeline import GatewayTranslator
from texlate.xlat.state import StateStore

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_gateway_arm_translator_exposes_aclose(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """网关臂 translator 暴露 ``aclose`` 且委托自持 client——缺了则
    ``drive_pipeline`` in-loop finally 探不到、httpx 池漏到外 loop 关。"""
    clean_env.setenv("TEXLATE_API_KEY", "k-test")
    t = _cli._export_translator(None, mock=False)  # noqa: SLF001 -- 钉点缝
    assert isinstance(t, GatewayTranslator)
    aclose = getattr(t, "aclose", None)
    assert callable(aclose)
    seen: list[asyncio.AbstractEventLoop] = []

    async def _spy() -> None:
        seen.append(asyncio.get_running_loop())

    clean_env.setattr(t.client, "aclose", _spy)
    asyncio.run(aclose())
    assert len(seen) == 1  # aclose 真委托到 client.aclose


def test_drive_pipeline_awaits_aclose_inside_pipeline_loop(tmp_path: Path) -> None:
    """``aclose`` 在管线 ephemeral loop 内被 await——返回时 loop 已关
    （``asyncio.run`` 收摊痕迹），证明不是事后新 loop 上的 foreign close。"""
    seen: dict[str, asyncio.AbstractEventLoop] = {}

    class _T:
        async def translate(self, **_kw: object) -> str:
            return "x"

        async def aclose(self) -> None:
            seen["loop"] = asyncio.get_running_loop()

    results, _counts = drive_pipeline(
        [],
        translator=_T(),
        store=StateStore(tmp_path / "s", model="m", pipeline_version="v"),
        glossary=None,
        on_result=None,
        apply_fn=lambda r: ApplyCounts(translated=len(r)),
        save_fn=lambda _n: None,
    )
    assert results == {}
    assert seen["loop"].is_closed()
