"""fixloop/L2 实况帧 + snapshot.queue_position + dual.json chunk status 验收。

- 引擎层 ``fixloop(on_round=…``)：每轮 ``cell["rounds"]`` 落新 entry 即
  同步回调（含 salvage 兜底轮），entry 与 cell 内同对象；
- worker 层 ``_run_fixloop``：``on_round`` 经 ``bus.publish`` 发
  ``{"phase": "round", "round": entry}`` 实况帧，收尾发
  ``{"phase": "done", "cell": <完整 cell>}``（崩溃发 crashed done）；
- worker 层 ``_l2_attempt``：start/progress/done 阶段帧——done 平铺
  统计键（enabled/errors/retranslated/fallback）+ ``report`` 全量；
- ``Store.snapshot``：``status == "queued"`` 时 ``queue_position`` =
  ``queued_rows`` 序内 1 基位次，其余状态/header 凭证行字段缺席；
- ``_build_dual``：chunks 每段带 ``status``，非 ok 段前端标「未翻译」。
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from _fixloopkit import MockEngine
from _workerkit import _insert_chunk, mk_ctx
from conftest import (
    MINI_TEX,
    RecordingEngine,
    live_app,
    task_events,
    upload_tex,
    wait_terminal,
)
from starlette.testclient import TestClient
from test_server_l2 import L2FlakyEngine

from texlate.compile.engine import CompRes, LogInfo
from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.engine import fixloop
from texlate.server.store import Store, new_task_id
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO（同 test_fixloop_aux_eof 口径）。"""
    return load_ruleset()


_EOF_LOG = (
    "This is XeTeX\n(./main.aux\n! File ended while scanning use of \\@newl@bel.\n"
    "<inserted text>\n                \\par\nl.5 \\begin{document}\n"
)
_CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"
MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n"


class TestEngineOnRound:
    """``fixloop(on_round=…``：每轮 entry 落 ``cell["rounds"]`` 即同步回调。"""

    def test_fires_per_round_same_object(self, tmp_path: Path) -> None:
        """aux_scan_eof→purge→clean 两轮剧本：回调序=cell 内同对象。"""
        (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
        (tmp_path / "main.aux").write_bytes(
            b"\\newlabel{a}{{1}{1}{\xe4\xb8}}\n\\newlabel{b}{{2}{2}{ok}}\n"
        )
        eng = MockEngine(
            [{"log": _EOF_LOG, "pdf": False}, {"log": _CLEAN_LOG, "pdf": True}]
        )
        fired: list[dict] = []
        cell = fixloop(tmp_path, eng, ruleset=_rs(), on_round=fired.append)
        assert cell["verdict"] == "clean"
        assert len(fired) == len(cell["rounds"]) == 2  # noqa: PLR2004 -- 两轮剧本
        assert [e["round"] for e in fired] == [1, 2]
        assert all(a is b for a, b in zip(cell["rounds"], fired, strict=True))

    def test_fires_for_salvage(self, tmp_path: Path) -> None:
        """salvage 兜底轮也过回调——rounds 末位 salvage entry 实况可见。"""
        (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
        # 健康 aux：签名命中但无可清件 → 规则 applied=False → 耗尽 → salvage
        (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{ok}}\n")
        eng = MockEngine([{"log": _EOF_LOG, "pdf": False}] * 8)
        fired: list[dict] = []
        cell = fixloop(tmp_path, eng, ruleset=_rs(), on_round=fired.append)
        assert cell["verdict"] != "clean"
        assert len(fired) == len(cell["rounds"])
        assert fired[-1].get("salvage") is True
        assert all(a is b for a, b in zip(cell["rounds"], fired, strict=True))

    def test_no_callback_unchanged(self, tmp_path: Path) -> None:
        """``on_round=None``（默认）零开销——e2e/bench 直调臂行为不变。"""
        (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
        eng = MockEngine([{"log": _CLEAN_LOG, "pdf": True}])
        cell = fixloop(tmp_path, eng, ruleset=_rs())
        assert cell["verdict"] == "clean"
        assert len(cell["rounds"]) == 1


class TestWorkerFixloopFrames:
    """``_run_fixloop``：``on_round`` → ``fixloop`` 事件 phase=round/done。"""

    def test_round_then_done_frames(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """stub fixloop 点火两轮 → 事件序 [round, round, done]；done 载完整 cell。"""
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.main_rel = "main.tex"
        work = ctx.root / "build-zh"
        work.mkdir(parents=True)
        ctx.zh_dir.mkdir(parents=True)
        (work / "main.tex").write_text(MINI_TEX, encoding="utf-8")
        (ctx.zh_dir / "main.tex").write_text(MINI_TEX, encoding="utf-8")

        def fake_fixloop(
            _work: Path,
            _eng: object,
            **kw: Any,  # noqa: ANN401 -- fixloop 开关面透传同 repair.run_fixloop
        ) -> dict[str, Any]:
            cell: dict[str, Any] = {
                "verdict": "clean",
                "rounds": [],
                "actions": [],
                "log": [],
            }
            on_round: Callable[[dict], None] | None = kw.get("on_round")
            for i in (1, 2):
                entry = {
                    "round": i,
                    "pdf": i == 2,  # noqa: PLR2004 -- 第 2 轮出 pdf
                    "n_errors": 1,
                    "category": "misc",
                    "sec": 0.1,
                }
                cell["rounds"].append(entry)
                if on_round is not None:
                    on_round(entry)
            return cell

        monkeypatch.setattr("texlate.repair.fixloop", fake_fixloop)
        first = CompRes(engine="tectonic", ok=True, pdf=None, log=LogInfo(n_errors=2))
        worker._run_fixloop(ctx, work, RecordingEngine("tectonic"), first)  # noqa: SLF001
        fix_evs = [
            e["data"]
            for e in store.events_since(ctx.task_id, 0)
            if e["type"] == "fixloop"
        ]
        assert [e["phase"] for e in fix_evs] == ["round", "round", "done"]
        assert [e["round"]["round"] for e in fix_evs[:2]] == [1, 2]
        cell = fix_evs[-1]["cell"]
        assert cell["verdict"] == "clean"
        assert len(cell["rounds"]) == 2  # noqa: PLR2004 -- 两轮剧本

    def test_crash_emits_done_frame(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """fixloop 抛错 → crashed done 帧收尾（前端卡片不挂）+ 原 CompRes 回传。"""
        ctx, worker, store = mk_ctx(tmp_path)
        work = ctx.root / "build-zh"
        work.mkdir(parents=True)
        ctx.zh_dir.mkdir(parents=True)

        def boom(*_a: object, **_kw: object) -> dict[str, Any]:
            msg = "fixloop exploded"
            raise RuntimeError(msg)

        monkeypatch.setattr("texlate.repair.fixloop", boom)
        first = CompRes(engine="tectonic", ok=True, pdf=None, log=LogInfo(n_errors=2))
        res = worker._run_fixloop(  # noqa: SLF001
            ctx, work, RecordingEngine("tectonic"), first
        )
        assert res is first
        fix_evs = [
            e["data"]
            for e in store.events_since(ctx.task_id, 0)
            if e["type"] == "fixloop"
        ]
        assert fix_evs == [
            {
                "phase": "done",
                "cond": "zh",
                "crashed": True,
                "message": "RuntimeError: fixloop exploded",
            }
        ]


class TestL2LiveFrames:
    """``_l2_attempt``：start → progress → done 帧 + done 平铺统计键。"""

    def test_l2_phase_frames(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """n_fail=1 → L2 修好即终：帧序 start/progress/done，done 带计数+report。"""
        eng = L2FlakyEngine(n_fail=1)
        translator = MockTranslator()
        app = live_app(
            tmp_path,
            lambda _ctx: translator,
            engine_factory=lambda _name: eng,
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done", snap
            evs = task_events(c, tid)
        l2 = [e["data"] for e in evs if e["type"] == "l2"]
        assert [e["phase"] for e in l2] == ["start", "progress", "progress", "done"]
        done = l2[-1]
        assert done["enabled"] is True
        assert done["errors"] >= 1
        assert done["retranslated"] >= 1
        assert done["fallback"] == 0
        assert done["report"]["recompiled"] == "clean"


class TestQueuePosition:
    """``snapshot.queue_position``：queued 行 = ``queued_rows`` 序内 1 基位次。"""

    def test_queued_position_ordering(self, tmp_path: Path) -> None:
        """三行 queued（created_at 钉序）→ 位次 1/3。"""
        store = Store(tmp_path / "t.db")
        store.open()
        tids = [new_task_id() for _ in range(3)]
        for i, tid in enumerate(tids):
            store.create_task(
                task_id=tid, kind="upload_tex", target_lang="zh-CN", model="m"
            )
            # created_at 钉死序——同秒落库只剩 id 字典序兜底，不可控
            store.conn.execute(
                "UPDATE tasks SET created_at=? WHERE id=?", (1000.0 + i, tid)
            )
        store.conn.commit()
        assert store.snapshot(tids[0], artifacts={})["queue_position"] == 1
        assert (
            store.snapshot(tids[2], artifacts={})["queue_position"] == 3  # noqa: PLR2004 -- 三行末位
        )

    def test_absent_when_not_queued(self, tmp_path: Path) -> None:
        """非 queued 状态字段缺席（不落 null）。"""
        store = Store(tmp_path / "t.db")
        store.open()
        tid = new_task_id()
        store.create_task(
            task_id=tid, kind="upload_tex", target_lang="zh-CN", model="m"
        )
        store.conn.execute("UPDATE tasks SET status='translating' WHERE id=?", (tid,))
        store.conn.commit()
        assert "queue_position" not in store.snapshot(tid, artifacts={})

    def test_absent_for_header_auth(self, tmp_path: Path) -> None:
        """header 凭证行不进 replay 队列（``queued_rows`` 排除口径）——位次缺席。"""
        store = Store(tmp_path / "t.db")
        store.open()
        tid = new_task_id()
        store.create_task(
            task_id=tid,
            kind="upload_tex",
            target_lang="zh-CN",
            model="m",
            auth_source="header",
        )
        assert "queue_position" not in store.snapshot(tid, artifacts={})


class TestDualChunkStatus:
    """``_build_dual`` chunks 带 ``status``——非 ok 段前端标「未翻译」。"""

    def test_chunk_status_per_segment(self, tmp_path: Path) -> None:
        """ok/fallback_orig 两段 → dual.json status 逐段落 + fallback zh 空。"""
        ctx, worker, store = mk_ctx(tmp_path)
        ctx.root.mkdir(parents=True, exist_ok=True)
        _insert_chunk(store, ctx.task_id, chunk_id="c1", seq=0, status="ok")
        _insert_chunk(store, ctx.task_id, chunk_id="c2", seq=1, status="fallback_orig")
        store.update_chunk(ctx.task_id, "c1", {"translation": "译文"})
        store.conn.commit()
        worker._build_dual(ctx)  # noqa: SLF001
        doc = json.loads((ctx.root / "dual.json").read_text(encoding="utf-8"))
        assert [c["status"] for c in doc["chunks"]] == ["ok", "fallback_orig"]
        assert doc["chunks"][0]["zh"] == "译文"
        assert doc["chunks"][1]["zh"] == ""
