"""server 面残余 fuzz——worker TaskCtx/options/store/settings/app 边界补面。

``test_fuzz_store.py`` 已钉状态机矩阵/事件流/并发纪律，``test_fuzz_sidecar.py``
已钉 settings 校验语料与 babeldoc 旁路，``test_fuzz_app_boundary.py`` 已钉
HTTP 闸后解析面。本文件打**跨层接缝**：store↔API 契约错位、worker↔settings
布尔语义分叉、force 通道的越枚举面。

已修 CONFIRMED（原 xfail-strict 钉，修复后转断言钉留档）：

- D1 ``task_retry`` 合并臂绕 ``_OPTIONS_JSON_CAP``——存量+增量合并后
  重跑帽闸（与 share 导入臂 post-merge 校验同口径），超帽 400。
- D2 ``/api/task/{id}/chunks`` ``limit`` 上限对齐 ``CHUNKS_PAGE_MAX``——
  超帽值 Query 校验拒（此前声明 1000 vs 钳 500 静默丢尾页）。
- D3 ``_parse_origin`` 剥 scheme 默认端口（``http://h:80``→``http://h``）——
  浏览器 Origin 恒省略默认端口，保留即 cors 精确匹配死配。

已修 OBSERVED（断言钉随修复翻向新契约）：

- D6 ``env_model()`` 出口过 ``validate_model``——env 臂与 header 臂同闸，
  控制字符不再原样进任务行/日志。
- D7 ``context_guidance`` load 走 ``_load_bool`` falsy 集——手写
  ``"false"``/``"0"`` 正确读 False（save 侧闸死非 bool，两臂对称）。
- D8 ``list_tasks_page`` ``ORDER BY created_at DESC, id DESC`` 显式
  tiebreak——并列时间戳分页不再依赖索引隐式 rowid 序，与
  ``queued_rows`` 同口径。

OBSERVED（断言钉当前行为/爆炸半径，非缺陷判词）：

- ``transition(force=True)`` 接受任意状态串——越枚举行不落任何状态集
  （``queued_rows``/``recover_startup``/列表过滤全不可见），``finished_at``
  缺位；钉爆炸半径防误读。
- ``opt_bool`` 与 ``_share_pack_opt_in`` 对 ``""`` 的判定分叉
  （``True``/``False``）——同文件族两套布尔归一化无共享 spec。
- ``_clean_task_options`` engine 只校验不回写（``engine=0`` 按 auto
  过闸但原值落库），与 ``source`` 规范化回写不对称。

正向不变量（绿）：snapshot options 摘内部审计键 + glossary 回显；
publish 已删任务返 0 不扇出；snapshot.warnings 回放 cap+序；
``queued_rows`` 排除 header 源；``chunks_page`` 双侧钳位；
``opt_bool`` env 回落；``_clean_task_options`` 白名单/钳位矩阵。
"""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from _fuzzkit import fuzz_rng, short
from conftest import mk_api_task

from texlate.server import settings as srv_settings
from texlate.server.app import (
    _OPTIONS_JSON_CAP,
    _ApiError,
    _clean_task_options,
)
from texlate.server.events import EventBus
from texlate.server.store import (
    ACTIVE_STATUSES,
    RETRYABLE_FROM,
    STAGES,
    TERMINAL_STATUSES,
    Store,
    new_task_id,
)
from texlate.server.worker import Secrets, TaskCtx
from texlate.server.worker._common import opt_bool
from texlate.server.worker.share import _Share

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient

ARXIV = "2401.00042"

#: ``_OPTIONS_JSON_CAP`` 下沿的合法面——两侧各带近帽量，合并即越帽。
_FAT = 60000
#: snapshot.warnings 回放帽（store._WARNINGS_CAP 口径）。
_WARN_N = 200
#: ``chunks_page`` 越帽探测的块量。
_CHUNK_N = 700
#: 钳位探测的小块量与页宽。
_CHUNK_EDGE = 30
_PAGE_EDGE = 10
#: 合法分页宽度（``_CHUNKS_PAGE_MAX`` 内）。
_PAGE_OK = 200
#: append_event seq 单调性探测的事件量。
_EVENT_N = 60

_parse_origin = srv_settings._parse_origin  # noqa: SLF001 -- 白盒钉私有归一化件


def _store(tmp_path: Path, name: str = "x.db") -> Store:
    s = Store(tmp_path / name)
    s.open()
    return s


def _mk(
    s: Store,
    *,
    tenant: str = "local",
    auth_source: str = "settings",
    **kw: Any,  # noqa: ANN401 -- create_task 键参透传
) -> str:
    tid = new_task_id()
    s.create_task(
        task_id=tid,
        kind="arxiv",
        target_lang="zh-CN",
        model="m",
        tenant=tenant,
        auth_source=auth_source,
        **kw,
    )
    return tid


def _ctx(store: Store, options: dict[str, Any]) -> TaskCtx:
    return TaskCtx(
        store=store,
        bus=None,  # type: ignore[arg-type] -- options() 只读 row
        task_id="t_ctx",
        row={"options_json": json.dumps(options)},
        secrets=Secrets(),
        root=store.path.parent,
    )


def _force(client: TestClient, tid: str, status: str) -> None:
    client.portal.call(
        partial(client.app.state.store.transition, tid, status, force=True)
    )


def _insert_chunks(store: Store, tid: str, n: int) -> None:
    store.insert_chunks(
        tid,
        [
            {
                "seq": i,
                "chunk_id": f"c{i}",
                "src_file": "main.tex",
                "byte_start": i * 10,
                "byte_end": i * 10 + 9,
                "kind": "para",
                "src_text": f"text {i}",
            }
            for i in range(n)
        ],
    )


# ---------------------------------------------------------------- CONFIRMED


class TestRetryMergedOptionsCap:
    """D1：retry 合并臂绕 ``_OPTIONS_JSON_CAP``——合并结果无闸。"""

    def test_merge_over_cap_rejected(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV, options={"note_a": "x" * _FAT})
        _force(client, tid, "fault")
        r = client.post(
            f"/api/task/{tid}/retry",
            json={"options": {"note_b": "y" * _FAT}},
        )
        # 期望：合并后仍超帽 → 400（与 share 导入注入后重闸同口径）
        assert r.status_code == HTTPStatus.BAD_REQUEST, r.text

    def test_merge_under_cap_ok(self, client: TestClient) -> None:
        """合并后仍在帽内 → 202，且存量键保留（对照组——本臂绿）。"""
        tid = mk_api_task(client, ARXIV, options={"note_a": "x"})
        _force(client, tid, "fault")
        r = client.post(f"/api/task/{tid}/retry", json={"options": {"note_b": "y"}})
        assert r.status_code == HTTPStatus.ACCEPTED, r.text
        row = client.portal.call(partial(client.app.state.store.get, tid))
        opts = json.loads(row["options_json"])
        assert opts == {"note_a": "x", "note_b": "y", "source": "eprint"}

    def test_create_side_cap_enforced(self, client: TestClient) -> None:
        """创建侧闸在位（对照——帽只对增量/直输生效，正是 D1 的不对称）。"""
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"options": {"note": "x" * (_OPTIONS_JSON_CAP + 1)}},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST


class TestChunksLimitContract:
    """D2：API ``le=1000`` vs store 钳 500——大 limit 静默丢块。"""

    def test_limit_over_clamp_returns_all(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        client.portal.call(
            partial(_insert_chunks, client.app.state.store, tid, _CHUNK_N)
        )
        r = client.get(f"/api/task/{tid}/chunks?limit=1000")
        # 期望契约：要么 API 拒超帽值（422），要么按 limit 全量返回——
        # 不得 200 截断（分页方按 total 翻页会静默丢尾部 200 块）
        assert r.status_code == HTTPStatus.BAD_REQUEST or (
            r.status_code == HTTPStatus.OK and len(r.json()["chunks"]) == _CHUNK_N
        ), f"limit=1000 → {r.status_code} + {len(r.json()['chunks'])} rows"

    def test_limit_boundaries(self, client: TestClient) -> None:
        """声明界内返回正常；界外（0/1001）被 Query 校验拒。"""
        tid = mk_api_task(client, ARXIV)
        client.portal.call(
            partial(_insert_chunks, client.app.state.store, tid, _CHUNK_N)
        )
        r = client.get(f"/api/task/{tid}/chunks?limit={_PAGE_OK}")
        assert r.status_code == HTTPStatus.OK
        assert len(r.json()["chunks"]) == _PAGE_OK
        for bad in (0, 1001, -5):
            r = client.get(f"/api/task/{tid}/chunks?limit={bad}")
            # RequestValidationError 归一化 400（app._validation_400）
            assert r.status_code == HTTPStatus.BAD_REQUEST, bad

    def test_store_clamps_direct(self, tmp_path: Path) -> None:
        """store 层钳位本身是把守的（负值/超帽按边界收）——缺口只在 API 口径。"""
        s = _store(tmp_path)
        tid = _mk(s)
        _insert_chunks(s, tid, _CHUNK_EDGE)
        rows, total = s.chunks_page(tid, offset=0, limit=-1)
        assert rows == []
        assert total == _CHUNK_EDGE
        rows, total = s.chunks_page(tid, offset=-5, limit=_PAGE_EDGE)
        assert len(rows) == _PAGE_EDGE
        assert rows[0]["seq"] == 0
        rows, _ = s.chunks_page(tid, offset=0, limit=10**9)
        assert len(rows) == _CHUNK_EDGE


class TestParseOrigin:
    """D3：默认端口保留 → cors_origins 死配。"""

    def test_default_port_elided(self) -> None:
        assert _parse_origin("http://a.com:80") == "http://a.com"
        assert _parse_origin("https://a.com:443") == "https://a.com"

    def test_non_default_port_kept(self) -> None:
        """非默认端口是真配置面，必须保留（对照组——本臂绿）。"""
        assert _parse_origin("http://a.com:8080") == "http://a.com:8080"
        # 错 scheme 的端口不属「默认端口」——``https://a.com:80`` 须原样
        assert _parse_origin("https://a.com:80") == "https://a.com:80"

    def test_canonical_forms(self) -> None:
        """无端口/大小写/尾斜杠的归一化契约（与 sidecar 拒绝语料互补）。"""
        for raw, want in (
            ("HTTP://A.COM", "http://a.com"),
            ("https://B.com/", "https://b.com"),
            ("  http://c.com  ", "http://c.com"),
            ("http://[::1]:3000", "http://[::1]:3000"),
        ):
            assert _parse_origin(raw) == want, raw


# ---------------------------------------------------------------- OBSERVED 钉


class TestForceTransitionBlastRadius:
    """force 通道无枚举闸——越界状态行的可见面全钉（OBSERVED）。"""

    def test_garbage_status_invisible(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        tid = _mk(s)
        out = s.transition(tid, "bogus_state", force=True)
        assert out["status"] == "bogus_state"
        # 不落任何状态集：finished_at 缺位、stage 保留（非 STAGES 非 TERMINAL）
        assert out["finished_at"] is None
        # 队列/恢复面看不见它——recover_startup 也不碰
        assert all(r["id"] != tid for r in s.queued_rows())
        assert s.recover_startup() == {"interrupted": 0, "needs_auth": 0}
        assert s.get(tid)["status"] == "bogus_state"
        # 但无过滤的列表页原样透出——前端拿到未知 status 枚举
        page, total = s.list_tasks_page("local")
        assert [r["id"] for r in page] == [tid]
        assert total == 1

    def test_force_to_terminal_clears_stage(self, tmp_path: Path) -> None:
        """对照组：合法终态的字段表正常（finished_at+stage 清场）。"""
        s = _store(tmp_path)
        tid = _mk(s)
        s.transition(tid, "translating", force=True)
        out = s.transition(tid, "done", force=True)
        assert out["finished_at"] is not None
        assert out["stage"] is None


class TestBoolCoercionDivergence:
    """``opt_bool`` vs ``_share_pack_opt_in`` 的 ``""`` 分叉（OBSERVED）。"""

    def test_empty_string_divergence(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        ctx = _ctx(s, {"share_pack": ""})
        # 同族两个布尔归一化件对 "" 判定相反：opt_bool 认开、share 件认关
        assert opt_bool({"k": ""}, "k", lambda: False) is True
        assert _Share()._share_pack_opt_in(ctx) is False  # noqa: SLF001 -- 白盒钉私有归一化件

    def test_opt_bool_matrix(self) -> None:
        """opt_bool 全值域钉：bool 直读、false 系字符串、非 bool 兜底真值。"""
        assert opt_bool({"k": True}, "k", lambda: False) is True
        assert opt_bool({"k": False}, "k", lambda: True) is False
        for v in ("0", "false", "no", "off", " OFF ", 0):
            assert opt_bool({"k": v}, "k", lambda: True) is False, short(v)
        for truthy in ("1", "true", "yes", [], {}, "0.0"):
            assert opt_bool({"k": truthy}, "k", lambda: False) is True, short(truthy)
        # 键缺席 → env_on 回落
        assert opt_bool({}, "k", lambda: True) is True
        assert opt_bool({}, "k", lambda: False) is False
        assert opt_bool({"k": None}, "k", lambda: False) is False


class TestEnvModelValidated:
    """``env_model()`` 出口过 ``validate_model``——env 臂与 header 臂同闸。"""

    def test_env_model_validated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODEL", "evil\nmodel\tinject")
        with pytest.raises(ValueError, match="invalid model"):
            srv_settings.resolve_auth(
                srv_settings.SettingsStore(tmp_path / "cfg").load()
            )

    def test_header_model_validated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODEL", "env-ok")
        with pytest.raises(ValueError, match="invalid model"):
            srv_settings.resolve_auth(
                srv_settings.SettingsStore(tmp_path / "cfg").load(),
                header_model="evil\nmodel",
            )


class TestContextGuidanceCoercion:
    """``context_guidance`` load 走 ``_load_bool``——str 值按 falsy 集解析。"""

    def test_string_false_reads_false(self, tmp_path: Path) -> None:
        d = tmp_path / "cfg"
        d.mkdir()
        p = srv_settings.SettingsStore(d)
        p.path.write_text(json.dumps({"context_guidance": "false"}), encoding="utf-8")
        # 手写 "false" 按 falsy 集读 False——与 save 侧非 bool 闸对称
        assert p.load()["context_guidance"] is False

    def test_coercion_table(self, tmp_path: Path) -> None:
        for i, (raw, want) in enumerate(
            (
                (False, False),
                (0, False),
                ("false", False),
                ("0", False),
                ("off", False),
                (1, True),
                ("yes", True),
            )
        ):
            d = tmp_path / f"cfg{i}"
            d.mkdir()
            p = srv_settings.SettingsStore(d)
            p.path.write_text(json.dumps({"context_guidance": raw}), encoding="utf-8")
            assert p.load()["context_guidance"] is want, raw


class TestListTasksPageTie:
    """``list_tasks_page`` ``, id DESC`` 显式 tiebreak——并列时间戳分页稳定。"""

    def test_equal_created_at_pagination(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        ids = [_mk(s) for _ in range(7)]
        for tid in ids:
            s.update_fields(tid, created_at=1000.0)
        seen: list[str] = []
        for off in range(0, len(ids) + 1, 2):
            rows, total = s.list_tasks_page("local", limit=2, offset=off)
            assert total == len(ids)
            seen.extend(str(r["id"]) for r in rows)
        # 钉住「并列 created_at 翻页不重不漏」——显式 tiebreak 保证，
        # 不再依赖索引隐式 rowid 序
        assert sorted(seen) == sorted(ids)

    def test_tiebreak_order_is_id_desc(self, tmp_path: Path) -> None:
        """并列 created_at 时按 id DESC 收序——与 DESC 语义一致。"""
        s = _store(tmp_path)
        ids = [_mk(s) for _ in range(4)]
        for tid in ids:
            s.update_fields(tid, created_at=1000.0)
        rows, _ = s.list_tasks_page("local", limit=10)
        assert [r["id"] for r in rows] == sorted(ids, reverse=True)


# ---------------------------------------------------------------- 正向不变量


class TestSnapshotEcho:
    """snapshot options/glossary 回显的摘键契约（正向钉）。"""

    def test_internal_keys_dropped(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        tid = _mk(
            s,
            options={
                "main": "main.tex",
                "note": "user-data",
                # worker 写入面 + 一次性入参——snapshot 不回显
                "share": {"share_key": "k"},
                "reuse_hit": "share:abc",
                "idempotency_key": "idem-1",
                "engine_resolved": "tectonic",
                "route_engines": ["xelatex"],
                "arxiv_categories": ["cs.CL"],
            },
            config={"glossary": "g.yaml"},
        )
        snap = s.snapshot(tid, artifacts={})
        assert snap["options"] == {"main": "main.tex", "note": "user-data"}
        assert snap["glossary"] == "g.yaml"

    def test_no_user_fields_absent(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        tid = _mk(s)
        snap = s.snapshot(tid, artifacts={})
        assert "options" not in snap
        assert "glossary" not in snap

    def test_corrupt_options_json_tolerated(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        tid = _mk(s)
        s.update_fields(tid, options_json="{corrupt")
        snap = s.snapshot(tid, artifacts={})
        assert "options" not in snap


class TestEventBusEdge:
    """publish 哨兵与 warnings 回放（正向钉）。"""

    def test_publish_missing_task_zero(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        bus = EventBus(s)
        assert bus.publish("t_ghost", "log", {"message": "x"}) == 0
        assert s.events_since("t_ghost", 0) == []

    def test_warnings_cap_and_order(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        tid = _mk(s)
        for i in range(_WARN_N + 30):
            s.append_event(tid, "warning", {"code": "w", "message": f"m{i}"})
        snap = s.snapshot(tid, artifacts={})
        warns = snap["warnings"]
        assert len(warns) == _WARN_N
        # 最近 200 条按时间序回放（DESC 取尾再反序）
        assert warns[0] == f"[w] m{30}"
        assert warns[-1] == f"[w] m{_WARN_N + 29}"


class TestQueuedRowsHeaderExclusion:
    """``queued_rows`` 排除 header 源（正向钉——凭证随进程死亡的语义面）。"""

    def test_header_source_excluded(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        kept = _mk(s, auth_source="settings")
        _mk(s, auth_source="header")
        _mk(s, auth_source="env")
        got = {str(r["id"]) for r in s.queued_rows()}
        assert kept in got
        assert len(got) == 2  # noqa: PLR2004 -- settings+env 两源入队钉


class TestCleanTaskOptions:
    """``_clean_task_options`` 白名单/钳位矩阵 + engine 非回写 OBSERVED。"""

    def test_reserved_keys_stripped(self) -> None:
        out = _clean_task_options(
            {
                "reuse_hit": "x",
                "share": {"k": "v"},
                "arxiv_categories": ["cs"],
                "engine_resolved": "x",
                "route_engines": ["x"],
                "keep": 1,
            }
        )
        assert out == {"keep": 1, "source": "eprint"}

    def test_engine_whitelist(self) -> None:
        for eng in ("auto", "xelatex", "tectonic"):
            _clean_task_options({"engine": eng})
        for bad in ("weasyprint", "pdflatex", {"e": 1}, ["x"]):
            with pytest.raises(_ApiError, match="engine"):
                _clean_task_options({"engine": bad})

    def test_engine_falsy_not_written_back(self) -> None:
        """OBSERVED：``engine=0``/``""`` 按 auto 过闸但**原值落库**——
        校验面 ``str(v or "auto")`` 与存储面不回写不对称（source 回写）。"""
        out = _clean_task_options({"engine": 0})
        assert out["engine"] == 0  # 原样保留——worker 侧 falsy 兜回 auto

    def test_concurrency_clamp(self) -> None:
        out = _clean_task_options({"concurrency": 99})
        assert out["concurrency"] == 16  # noqa: PLR2004 -- 钳位上限钉
        out = _clean_task_options({"concurrency": -3})
        assert out["concurrency"] == 1
        for bad in ("abc", {"x": 1}, [1]):
            with pytest.raises(_ApiError, match="concurrency"):
                _clean_task_options({"concurrency": bad})

    def test_merge_arm_no_default_inject(self) -> None:
        """``inject_defaults=False`` 不注 source（retry 合并语义钉）。"""
        out = _clean_task_options({"concurrency": 2}, inject_defaults=False)
        assert "source" not in out

    def test_fuzz_reserved_never_survive(self) -> None:
        """随机 options 键汤：保留键必摘、合法键原样过。"""
        rng = fuzz_rng(20260918)
        reserved = [
            "reuse_hit",
            "share",
            "arxiv_categories",
            "engine_resolved",
            "route_engines",
        ]
        for _ in range(200):
            keys = rng.sample(
                [*reserved, "main", "note", "prefer", "glossary", "pages"],
                k=rng.randrange(1, 6),
            )
            opts = {k: rng.choice([0, 1, "x", True, [1]]) for k in keys}
            out = _clean_task_options(dict(opts))
            for k in reserved:
                assert k not in out, short(opts)


class TestStoreQueriesEdge:
    """store 查询面残余边角（正向钉）。"""

    def test_status_filter_and_total(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        a = _mk(s)
        b = _mk(s)
        s.transition(a, "translating", force=True)
        s.transition(b, "done", force=True)
        rows, total = s.list_tasks_page("local", status="done")
        assert [str(r["id"]) for r in rows] == [b]
        assert total == 1
        rows, total = s.list_tasks_page("local", status="queued")
        assert rows == []
        assert total == 0

    def test_find_active_includes_interrupted(self, tmp_path: Path) -> None:
        """interrupted 占 dedup 槽（部分唯一索引覆盖集语义钉）。"""
        s = _store(tmp_path)
        tid = _mk(s, cache_key="ck1")
        s.transition(tid, "interrupted", force=True)
        hit = s.find_active_by_cache_key("ck1")
        assert hit is not None
        assert hit["id"] == tid

    def test_append_event_seq_monotone_after_cap(self, tmp_path: Path) -> None:
        """EVENT_CAP 滚动后 seq 不回绕——重放凭据单调。"""
        s = _store(tmp_path)
        tid = _mk(s)
        last = 0
        for i in range(_EVENT_N):
            last = s.append_event(tid, "log", {"i": i})
            assert last == i + 1
        assert s.last_seq(tid) == _EVENT_N


class TestTaskCtxOptions:
    """TaskCtx.options/update_options/set_option 的 JSON 回写契约（正向钉）。"""

    def test_options_roundtrip(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        ctx = _ctx(s, {"a": 1})
        assert ctx.options() == {"a": 1}
        out = ctx.update_options(lambda o: o.update({"b": 2}))
        assert json.loads(out) == {"a": 1, "b": 2}
        assert ctx.options() == {"a": 1, "b": 2}
        out = ctx.set_option("c", 3)
        assert json.loads(out)["c"] == 3  # noqa: PLR2004 -- set_option 回显值钉

    def test_corrupt_options_empty(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        ctx = TaskCtx(
            store=s,
            bus=None,  # type: ignore[arg-type]
            task_id="t",
            row={"options_json": "{bad json"},
            secrets=Secrets(),
            root=tmp_path,
        )
        assert ctx.options() == {}


class TestTransitionFieldMatrix:
    """force 迁移字段表的残余面（与 fuzz_store 矩阵互补——钉 row 级副作用）。"""

    def test_queued_clears_terminal_fields(self, tmp_path: Path) -> None:
        s = _store(tmp_path)
        tid = _mk(s)
        s.transition(tid, "fault", force=True, error={"code": "x"})
        out = s.transition(tid, "queued", force=True)
        assert out["finished_at"] is None
        assert out["stage"] is None
        assert out["error_json"] is None

    def test_status_enum_coverage(self) -> None:
        """状态集枚举正交性——ACTIVE∩TERMINAL 空、RETRYABLE⊆TERMINAL。"""
        assert not (ACTIVE_STATUSES & TERMINAL_STATUSES)
        assert RETRYABLE_FROM <= TERMINAL_STATUSES
        assert set(STAGES) <= ACTIVE_STATUSES
