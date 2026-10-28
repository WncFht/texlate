"""``PipelineConfig.warmup``：首项单飞暖前缀缓存可关。

轮转网关（每请求换供应商）下前缀缓存不跨请求命中，单飞只白白串行一个
推理调用；``warmup=False`` 时首项与其余项同批并发。
"""

import asyncio

from texlate.xlat import pipeline as pl

_LONG = "prose " + "x" * 400


def _peak_and_order(*, warmup: bool) -> tuple[int, list[str]]:
    """4 个 single 项、并发 4：返回 (最大在飞数, 事件序)。"""
    p = pl.XlatPipeline(
        pl.MockTranslator(),
        config=pl.PipelineConfig(concurrency=4, batch_max_items=1, warmup=warmup),
    )
    inflight = 0
    peak = 0
    events: list[str] = []

    async def fake_process(item: pl.WorkItem) -> list[pl.ChunkResult]:
        nonlocal inflight, peak
        (c,) = item.affected()
        inflight += 1
        peak = max(peak, inflight)
        events.append(f"start {c.chunk_id}")
        await asyncio.sleep(0.05)
        inflight -= 1
        events.append(f"end {c.chunk_id}")
        return [
            pl.ChunkResult(
                chunk_id=c.chunk_id,
                source=c.content,
                translation=c.content,
                kind="para",
                status="ok",
                attempts=1,
            )
        ]

    p._process = fake_process  # type: ignore[method-assign]  # noqa: SLF001
    chunks = [pl.ChunkIn(chunk_id=f"c{i}", content=_LONG) for i in range(4)]
    asyncio.run(asyncio.wait_for(p.run(chunks), timeout=15))
    return peak, events


def test_warmup_default_single_flights_first_item() -> None:
    peak, events = _peak_and_order(warmup=True)
    assert events[:2] == ["start c0", "end c0"]
    assert peak == 3  # noqa: PLR2004 -- 首项独跑后余 3 项并发


def test_warmup_off_runs_first_item_concurrently() -> None:
    peak, events = _peak_and_order(warmup=False)
    assert events[:4] == ["start c0", "start c1", "start c2", "start c3"]
    assert peak == 4  # noqa: PLR2004
