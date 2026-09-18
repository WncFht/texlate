"""``_collect``/序章 BaseException 注入钉。

契约（``xlat/pipeline.py`` ``_ledger_call`` 双档网 + ``_drain``/``run``
序章尾两处收敛重抛）：

- ``_collect`` 五个账本调用点（三条 interceptor + ``auth_gate.record`` +
  ``_emit``）任一点抛 ``KeyboardInterrupt``/``SystemExit`` → 收 ``fatal``
  账本，同结果内剩余调用点与后续结果照常入账，绝不外泄；
- worker 不死：``fatal`` 已挂后剩余 item 排空 ``task_done``（不再发翻译
  请求）→ ``queue.join()`` 不锁；
- ``_drain`` join 后 ``raise fatal[0]`` → ``run()`` 向外抛原异常实例；
- 序章（``_load_resumed`` 三点 + ``_route_chunks`` 散文豁免臂五点）同款
  收账——``run()`` 在 ``state.start()``/队列编前排 ``raise fatal[0]``，
  翻译请求零发出。

注入点选择说明：三条 ``_intercept_*`` 在 ``_one_chunk`` 内的调用由
worker 级 ``except BaseException`` 覆盖，序章两臂已并同款账本（见
``TestPrologueFatalLedger``）；``_collect`` 面 run 级注入走
``AuthGate.record`` 与 ``on_result``（``_emit`` 槽位）——散文块路径下
这两处仅在 ``_collect`` 内触达；interceptor 覆盖面由单元钉（直调
``_collect``/``_route_chunks``/``_load_resumed``）承担。
"""

import asyncio

import pytest

from texlate.xlat import pipeline as pl

#: ≥ ``SHORT_CHAR_LIMIT``(300) → ``_build_work_items`` 落 ``("single", c)``
#: 工作单元——不装箱进 batch，注入点火位计数才确定。
_LONG = "prose " + "x" * 400

#: run 级死锁判定时限——join 收敛正常 <1s，给足余量；超时即「worker 死了
#: sentinel 没人吃」的判别信号（TimeoutError 而非挂死套件）。
_DEADLOCK_S = 15.0


def _chunk(cid: str) -> pl.ChunkIn:
    return pl.ChunkIn(chunk_id=cid, content=_LONG)


def _result(cid: str) -> pl.ChunkResult:
    return pl.ChunkResult(
        chunk_id=cid,
        source=f"src {cid}",
        translation=f"zh {cid}",
        kind="para",
        status="ok",
        attempts=1,
    )


def _run(p: pl.XlatPipeline, chunks: list[pl.ChunkIn]) -> list[pl.ChunkResult]:
    """``asyncio.run`` + ``wait_for``——join 死锁降级成 TimeoutError 判负。"""
    return asyncio.run(asyncio.wait_for(p.run(chunks), timeout=_DEADLOCK_S))


class TestCollectLedgerUnit:
    """单元面：直调 ``_collect``，三条 interceptor 逐点注入。"""

    @pytest.mark.parametrize("exc_cls", [KeyboardInterrupt, SystemExit])
    def test_base_exception_ledgered_and_loop_continues(
        self, monkeypatch: pytest.MonkeyPatch, exc_cls: type[BaseException]
    ) -> None:
        """首点（leftover_ph）抛致命 → 收 fatal；同 r 剩余点与次 r 照常跑完。"""
        emitted: list[str] = []
        p = pl.XlatPipeline(
            pl.MockTranslator(), on_result=lambda r: emitted.append(r.chunk_id)
        )
        boom = exc_cls("injected at leftover_ph")
        calls: list[tuple[str, str]] = []

        def _boom(r: pl.ChunkResult) -> None:
            calls.append(("leftover_ph", r.chunk_id))
            raise boom

        def _rec(tag: str) -> object:
            def _f(r: pl.ChunkResult) -> None:
                calls.append((tag, r.chunk_id))

            return _f

        monkeypatch.setattr(pl, "_intercept_leftover_ph", _boom)
        monkeypatch.setattr(pl, "_intercept_ph_in_cs", _rec("ph_in_cs"))
        monkeypatch.setattr(pl, "_intercept_bare_cs", _rec("bare_cs"))

        fatal: list[BaseException] = []
        done_map: dict[str, pl.ChunkResult] = {}
        # 契约：不抛——致命异常收账本而非外泄杀 worker
        p._collect([_result("a"), _result("b")], done_map, fatal)  # noqa: SLF001

        assert fatal == [boom, boom]  # 逐调用点独立收账：两 r 各记一笔
        assert set(done_map) == {"a", "b"}  # 结果入账先于账本调用，两 r 都在
        assert calls == [  # 调用点序与 r 循环双双不中断
            ("leftover_ph", "a"),
            ("ph_in_cs", "a"),
            ("bare_cs", "a"),
            ("leftover_ph", "b"),
            ("ph_in_cs", "b"),
            ("bare_cs", "b"),
        ]
        assert emitted == ["a", "b"]  # _emit 槽位（末点）也照常触达


class TestRunFatalLedger:
    """集成面：``run()`` 全程——fatal 收账 → 排空 → join 收敛 → 重抛原异常。

    ``fire_at`` 是 ``record``/``on_result`` 第几次调用时点火：1 = warmup
    臂（``_drain`` 首项直跑 ``_collect``），2 = worker 臂（fork 后首个
    item）——后者是判别位：worker 若被致命异常带走，队列余项与它的
    sentinel 无人消费，``join()`` 死等 → ``wait_for`` 超时判负。
    """

    @pytest.mark.parametrize("exc_cls", [KeyboardInterrupt, SystemExit])
    @pytest.mark.parametrize("fire_at", [1, 2])
    def test_auth_gate_record_fatal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        exc_cls: type[BaseException],
        fire_at: int,
    ) -> None:
        t = pl.MockTranslator()
        p = pl.XlatPipeline(t, config=pl.PipelineConfig(concurrency=1))
        boom = exc_cls("injected at auth_gate.record")
        seen = 0
        orig = pl.AuthGate.record

        def _gated(self: pl.AuthGate, r: pl.ChunkResult) -> None:
            nonlocal seen
            seen += 1
            if seen == fire_at:
                raise boom
            orig(self, r)

        monkeypatch.setattr(pl.AuthGate, "record", _gated)

        chunks = [_chunk(f"c{i}") for i in range(4)]
        with pytest.raises(exc_cls) as ei:
            _run(p, chunks)
        assert ei.value is boom  # 重抛的是注入实例本身
        # fatal 挂后不再发翻译请求（worker 排空不发工）——调用数钉死在火位
        assert len(t.calls) <= fire_at

    @pytest.mark.parametrize("fire_at", [1, 2])
    def test_emit_on_result_fatal(self, fire_at: int) -> None:
        """``_emit`` 槽位（state/on_result 落盘点）同契约——经 ctor 注入。"""
        boom = KeyboardInterrupt("injected at on_result")
        seen = 0

        def _gated_emit(_r: pl.ChunkResult) -> None:
            nonlocal seen
            seen += 1
            if seen == fire_at:
                raise boom

        t = pl.MockTranslator()
        p = pl.XlatPipeline(
            t,
            config=pl.PipelineConfig(concurrency=1),
            on_result=_gated_emit,
        )
        chunks = [_chunk(f"c{i}") for i in range(4)]
        with pytest.raises(KeyboardInterrupt) as ei:
            _run(p, chunks)
        assert ei.value is boom
        assert len(t.calls) <= fire_at


class TestPrologueFatalLedger:
    """序章面：``_load_resumed``/``_route_chunks`` 与 ``_collect`` 同款收账。

    ``run()`` 在 ``state.start()``/队列编排之前摆统一账本——``_route_chunks``
    散文豁免臂五点（3 interceptor + ``auth_gate.record`` + ``_emit``）与
    ``_load_resumed`` 逐记录三点任一处抛 ``BaseException`` → 收 ``fatal``，
    序章尾 ``raise fatal[0]``——先于 ``_drain``，故翻译请求零发出。
    """

    @pytest.mark.parametrize("exc_cls", [KeyboardInterrupt, SystemExit])
    def test_route_placeholder_intercept_fatal(
        self, monkeypatch: pytest.MonkeyPatch, exc_cls: type[BaseException]
    ) -> None:
        """placeholder-only 块走豁免臂——interceptor 点火 → 序章尾重抛原实例。"""
        t = pl.MockTranslator()
        p = pl.XlatPipeline(t, config=pl.PipelineConfig(concurrency=1))
        boom = exc_cls("injected at bare_cs prologue")

        def _boom(_r: pl.ChunkResult) -> None:
            raise boom

        monkeypatch.setattr(pl, "_intercept_bare_cs", _boom)
        with pytest.raises(exc_cls) as ei:
            _run(p, [pl.ChunkIn("p1", "[[X_1]]", "para")])
        assert ei.value is boom
        assert not t.calls  # 重抛先于 _drain——一个翻译请求都没发

    @pytest.mark.parametrize("exc_cls", [KeyboardInterrupt, SystemExit])
    def test_route_placeholder_auth_gate_fatal(
        self, monkeypatch: pytest.MonkeyPatch, exc_cls: type[BaseException]
    ) -> None:
        """豁免臂 ``auth_gate.record`` 槽位同契约。"""
        t = pl.MockTranslator()
        p = pl.XlatPipeline(t, config=pl.PipelineConfig(concurrency=1))
        boom = exc_cls("injected at auth_gate.record prologue")

        def _gated(_self: pl.AuthGate, _r: pl.ChunkResult) -> None:
            raise boom

        monkeypatch.setattr(pl.AuthGate, "record", _gated)
        with pytest.raises(exc_cls) as ei:
            _run(p, [pl.ChunkIn("p1", "[[X_1]]", "para")])
        assert ei.value is boom
        assert not t.calls

    def test_route_placeholder_emit_fatal(self) -> None:
        """豁免臂 ``_emit`` 槽位经 ``on_result`` 注入——同契约。"""
        boom = KeyboardInterrupt("injected at on_result prologue")

        def _gated_emit(_r: pl.ChunkResult) -> None:
            raise boom

        t = pl.MockTranslator()
        p = pl.XlatPipeline(
            t,
            config=pl.PipelineConfig(concurrency=1),
            on_result=_gated_emit,
        )
        with pytest.raises(KeyboardInterrupt) as ei:
            _run(p, [pl.ChunkIn("p1", "[[X_1]]", "para")])
        assert ei.value is boom
        assert not t.calls

    def test_route_placeholder_exception_still_logged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``Exception`` 档维持原语义：记账日志、不外抛、流程走完。"""
        t = pl.MockTranslator()
        p = pl.XlatPipeline(t, config=pl.PipelineConfig(concurrency=1))

        def _boom(_r: pl.ChunkResult) -> None:
            msg = "plain failure"
            raise ValueError(msg)

        monkeypatch.setattr(pl, "_intercept_bare_cs", _boom)
        out = _run(p, [pl.ChunkIn("p1", "[[X_1]]", "para")])
        assert [r.translation for r in out] == ["[[X_1]]"]  # 直落盘透传

    def test_route_chunks_unit_ledger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """单元面：豁免臂首点收账后余四点照常触达，done_map 入账不丢。"""
        emitted: list[str] = []
        p = pl.XlatPipeline(
            pl.MockTranslator(), on_result=lambda r: emitted.append(r.chunk_id)
        )
        p.auth_gate = pl.AuthGate(5)  # run() 才建——直调先补位
        boom = KeyboardInterrupt("injected at leftover_ph prologue")
        calls: list[tuple[str, str]] = []

        def _boom(r: pl.ChunkResult) -> None:
            calls.append(("leftover_ph", r.chunk_id))
            raise boom

        def _rec(tag: str) -> object:
            def _f(r: pl.ChunkResult) -> None:
                calls.append((tag, r.chunk_id))

            return _f

        monkeypatch.setattr(pl, "_intercept_leftover_ph", _boom)
        monkeypatch.setattr(pl, "_intercept_ph_in_cs", _rec("ph_in_cs"))
        monkeypatch.setattr(pl, "_intercept_bare_cs", _rec("bare_cs"))

        fatal: list[BaseException] = []
        done_map: dict[str, pl.ChunkResult] = {}
        pending, split_items = p._route_chunks(  # noqa: SLF001
            [pl.ChunkIn("p1", "[[X_1]]", "para")], set(), done_map, fatal
        )
        assert fatal == [boom]
        assert set(done_map) == {"p1"}
        assert not pending
        assert not split_items
        assert calls == [
            ("leftover_ph", "p1"),
            ("ph_in_cs", "p1"),
            ("bare_cs", "p1"),
        ]
        assert emitted == ["p1"]  # auth_gate.record(真件) + _emit 末点照常

    def test_load_resumed_unit_ledger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """单元面：``_load_resumed`` 逐记录三点收账——KI 记账不外泄。"""
        recs = {
            cid: pl.ChunkRecord(
                chunk_id=cid, source=f"src {cid}", translation=f"zh {cid}"
            )
            for cid in ("a", "b")
        }

        class _StubState:
            def load(self) -> tuple[set[str], dict[str, pl.ChunkRecord]]:
                return set(), recs

        p = pl.XlatPipeline(pl.MockTranslator(), state=_StubState())
        boom = KeyboardInterrupt("injected at load_resumed")
        calls: list[str] = []

        def _boom(r: pl.ChunkResult) -> None:
            calls.append(r.chunk_id)
            raise boom

        monkeypatch.setattr(pl, "_intercept_ph_in_cs", _boom)
        fatal: list[BaseException] = []
        _completed, done_map = p._load_resumed(fatal)  # noqa: SLF001
        assert fatal == [boom, boom]  # 两记录各记一笔，循环不中断
        assert set(done_map) == {"a", "b"}
        assert sorted(calls) == ["a", "b"]

    @pytest.mark.parametrize("exc_cls", [KeyboardInterrupt, SystemExit])
    def test_load_resumed_run_level_fatal(
        self, monkeypatch: pytest.MonkeyPatch, exc_cls: type[BaseException]
    ) -> None:
        """run 级：续跑装载臂收账 → 序章尾重抛先于 state.start()/_drain。"""
        recs = {
            "c0": pl.ChunkRecord(chunk_id="c0", source="src c0", translation="zh c0")
        }

        class _StubState:
            def __init__(self) -> None:
                self.started = False

            def load(self) -> tuple[set[str], dict[str, pl.ChunkRecord]]:
                return set(), recs

            def start(self, _n: int) -> None:
                self.started = True

        stub = _StubState()
        t = pl.MockTranslator()
        p = pl.XlatPipeline(t, state=stub)
        boom = exc_cls("injected at load_resumed run")

        def _boom(_r: pl.ChunkResult) -> None:
            raise boom

        monkeypatch.setattr(pl, "_intercept_leftover_ph", _boom)
        with pytest.raises(exc_cls) as ei:
            _run(p, [_chunk("c0")])
        assert ei.value is boom
        assert not stub.started  # 重抛先于 state.start()
        assert not t.calls
