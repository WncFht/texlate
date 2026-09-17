"""server store/events 性质 fuzz——状态机矩阵 + 并发纪律 + 事件流不变量。

不变量清单：

- ``transition`` 非 force 合法迁移 iff ``(to=="cancelled" ∧ cur∈ACTIVE) ∨
  (to=="queued" ∧ cur∈RETRYABLE_FROM)``——其余一律 ``TransitionError`` 且
  携带 ``(task_id, current, target)``，行原状不动；缺失任务 ``StoreError``；
- 迁移副作用：``to∈STAGES`` → ``stage=to`` + 首次 ``started_at``；
  ``to∈TERMINAL`` → ``finished_at`` + ``stage=None``（显式 ``stage=`` 参数
  也被终态覆写）；``to=="queued"`` → 清
  ``worker_id``/``stage``/``error_json``/``finished_at``、留 ``started_at``；
- ``valid_task_id``：``t_``+16hex 放行，错长/错前缀/非 hex 拒；
- ``append_event`` seq 逐任务从 1 连续单调；``events_since(k)`` 精确回放
  ``k+1..``；``EVENT_CAP`` 滚动截断后窗内仍连续；
- ``insert_chunks``/``flush_chunk_batch`` 显式事务——中途失败全回滚，
  不留半成品（``has_chunks``/计数器/段缓存零污染）；
- ``translation_cache`` REPLACE 保 ``hit_count``（COALESCE 读旧行）；
- ``delete_task`` FK CASCADE 清 chunks/files/events/usage，二次删 False；
- ``recover_startup`` 遗留 ACTIVE → interrupted/needs_auth（header 分流），
  queued 残留 worker_id 清场、终态行不碰，幂等——二次跑全零；
- 多连接（每线程自持 Store）并发写同库不死锁、seq 各自连续；
  ``check_same_thread`` 缺省开——越线程直调当场 ``ProgrammingError``；
- ``claim`` 无 CAS——顺序双认领 last-writer-wins（DB 层不防竞，真护栏是
  单写者纪律，钉住以显化）；
- ``snapshot.counters`` 与 ``chunk_counts``/任务列一致；
- ``EventBus``：publish 扇出保序保 seq；订阅队列溢出 → ``_RESYNC`` 哨兵
  + 摘除；``stream`` 重放→实时→done/终态行/行删三种终结，finally 摘除
  订阅；``close_all`` 唤醒 parked 生成器。
"""

from __future__ import annotations

import asyncio
import random
import sqlite3
import threading
from typing import TYPE_CHECKING, Any

import pytest

from texlate.server.events import _RESYNC, _SUB_QUEUE_MAX, EventBus, sse_frame
from texlate.server.store import (
    ACTIVE_STATUSES,
    EVENT_CAP,
    RETRYABLE_FROM,
    TERMINAL_STATUSES,
    Store,
    StoreError,
    TransitionError,
    new_task_id,
    valid_task_id,
)

if TYPE_CHECKING:
    from pathlib import Path

_ALL_STATUSES = sorted(ACTIVE_STATUSES | TERMINAL_STATUSES)
_WALK_ITERS = 1500
_ID_ITERS = 300
_SEQ_EVENTS = 400
_N_TASKS = 4
_N_SUBS = 4
_N_EVENTS = 30
_OVERFLOW_EXTRA = 40
_N_THREADS = 6
_OPS_PER_THREAD = 15
_RECOVER_TASKS = 40
_CAP_EXTRA = 50
_EXPECTED_HITS = 2
_USAGE_CALLS = 2
_SNAP_TOTAL = 6
_SNAP_DONE = 4
_SNAP_CACHED = 1
_SNAP_FAILED = 2
_SNAP_TOKENS = 99
_SNAP_PROGRESS = 66
_CLAIMED_P = 0.3
_FORCE_P = 0.5
_PARK_MS = 0.05
_WAKE_TIMEOUT_S = 1.0


def _store(tmp_path: Path, name: str = "x.db") -> Store:
    """开好连接的 Store（DDL 已落）。"""
    s = Store(tmp_path / name)
    s.open()
    return s


def _mk_task(
    s: Store,
    *,
    auth_source: str = "settings",
    tenant: str = "local",
    cache_key: str | None = None,
) -> str:
    """建行（默认 settings 源）→ task_id。"""
    tid = new_task_id()
    s.create_task(
        task_id=tid,
        kind="arxiv",
        target_lang="zh",
        model="m",
        auth_source=auth_source,
        tenant=tenant,
        cache_key=cache_key,
    )
    return tid


def _install(s: Store, tid: str, status: str) -> None:
    """force 通道把任务钉进任意状态（含非法值——测守卫对脏现状的拒绝）。"""
    s.transition(tid, status, force=True)


def _chunk_row(seq: int, chunk_id: str | None = None) -> dict[str, Any]:
    return {
        "seq": seq,
        "chunk_id": chunk_id or f"c{seq}",
        "src_file": "main.tex",
        "byte_start": seq * 10,
        "byte_end": seq * 10 + 9,
        "kind": "text",
        "src_text": f"text {seq}",
    }


def _legal(cur: str, to: str) -> bool:
    """非 force 合法迁移 oracle（§3.3 守卫式）。"""
    return (to == "cancelled" and cur in ACTIVE_STATUSES) or (
        to == "queued" and cur in RETRYABLE_FROM
    )


# ---------------------------------------------------------------- 状态机


def test_fuzz_transition_matrix(tmp_path: Path) -> None:
    """全 cur×to 矩阵：合法 iff ACTIVE→cancelled / RETRYABLE→queued。"""
    s = _store(tmp_path)
    targets = [*_ALL_STATUSES, "bogus", "", "CANCELLED", "Done"]
    for cur in [*_ALL_STATUSES, "bogus", ""]:
        tid = _mk_task(s)
        _install(s, tid, cur)
        for to in targets:
            if _legal(cur, to):
                assert s.transition(tid, to)["status"] == to
                _install(s, tid, cur)  # 复位再测下一目标
            else:
                with pytest.raises(TransitionError) as ei:
                    s.transition(tid, to)
                e = ei.value
                assert (e.task_id, e.current, e.target) == (tid, cur, to)
                assert s.get(tid)["status"] == cur  # 拒迁行原状
    with pytest.raises(StoreError, match="task not found"):
        s.transition("t_" + "0" * 16, "cancelled")
    s.close()


def test_fuzz_transition_walk(tmp_path: Path) -> None:
    """随机游走 + oracle 逐步对账（含 force 钉脏态再拒非 force 出）。"""
    rng = random.Random(20261102)  # noqa: S311 -- 确定性种子
    s = _store(tmp_path)
    tids = [_mk_task(s) for _ in range(_N_TASKS)]
    state = dict.fromkeys(tids, "queued")
    for _ in range(_WALK_ITERS):
        tid = rng.choice(tids)
        to = rng.choice([*_ALL_STATUSES, "bogus", ""])
        force = rng.random() < _FORCE_P
        cur = state[tid]
        if force or _legal(cur, to):
            s.transition(tid, to, force=force)
            state[tid] = to
        else:
            with pytest.raises(TransitionError):
                s.transition(tid, to)
        assert s.get(tid)["status"] == state[tid]
    s.close()


def test_transition_field_effects(tmp_path: Path) -> None:
    """副作用表：stage/started_at/finished_at/queued 清场逐条钉。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    s.transition(tid, "fetching", force=True)
    r1 = s.get(tid)
    assert r1 is not None
    assert r1["stage"] == "fetching"
    assert r1["started_at"] is not None
    t0 = r1["started_at"]
    s.transition(tid, "parsing", force=True)
    r2 = s.get(tid)
    assert r2 is not None
    assert r2["stage"] == "parsing"
    assert r2["started_at"] == t0  # 首个 stage 戳不被覆写
    # 显式 stage= 参数在终态下也被覆写为 None
    s.transition(tid, "done", force=True, stage="weird")
    r3 = s.get(tid)
    assert r3 is not None
    assert r3["finished_at"] is not None
    assert r3["stage"] is None
    # queued 复活清场
    s.claim(tid, "w1")
    s.transition(tid, "fault", force=True, error={"code": "provider_error"})
    r4 = s.get(tid)
    assert r4 is not None
    assert r4["worker_id"] == "w1"
    assert r4["error_json"] is not None
    s.transition(tid, "queued")  # fault ∈ RETRYABLE → API 合法路径
    r5 = s.get(tid)
    assert r5 is not None
    assert (
        r5["worker_id"],
        r5["stage"],
        r5["error_json"],
        r5["finished_at"],
    ) == (None, None, None, None)
    assert r5["started_at"] == t0  # retry 计时基准保留
    s.close()


# ---------------------------------------------------------------- task_id 形态


def test_fuzz_task_id_oracle() -> None:
    """规范形放行；错长/错前缀/非 hex/空全拒。"""
    rng = random.Random(20261103)  # noqa: S311 -- 确定性种子
    for _ in range(_ID_ITERS):
        tid = new_task_id()
        assert valid_task_id(tid)
        body = tid[2:]
        for bad in (
            tid[:-1],  # 短
            tid + "0",  # 长
            "x_" + body,  # 坏前缀
            "t_" + body[:-1] + "g",  # 非 hex 字符
            body,  # 无前缀
            "",
        ):
            assert not valid_task_id(bad), bad
        # 扰动位再验——大小写 hex 过闸是 int(,16) 宽容，单独钉
        mutated = list(tid)
        mutated[rng.randrange(2, len(tid))] = "z"
        assert not valid_task_id("".join(mutated))


def test_task_id_leniency_pinned() -> None:
    """int(,16) 宽容度钉住：大写 hex / 空白填充的非规范形同样过闸。

    白名单只管「不进 SQL 拼接」——非规范 id 查无此行即 404，不构成注入；
    但放行面比表面正则宽，钉住防未来收紧时意外破契约。
    """
    base = new_task_id()
    assert valid_task_id("t_" + base[2:].upper())
    assert valid_task_id("t_  " + base[4:])  # int() strip 空白 → 过闸
    assert not valid_task_id(base.upper())  # T_ 前缀大小写敏感


# ---------------------------------------------------------------- 事件落盘


def test_fuzz_events_seq(tmp_path: Path) -> None:
    """逐任务 seq 从 1 连续单调；events_since(k) 精确回放 k+1..。"""
    rng = random.Random(20261104)  # noqa: S311 -- 确定性种子
    s = _store(tmp_path)
    tids = [_mk_task(s) for _ in range(_N_TASKS)]
    expected = dict.fromkeys(tids, 0)
    for _ in range(_SEQ_EVENTS):
        tid = rng.choice(tids)
        seq = s.append_event(
            tid, rng.choice(["progress", "warning", "chunk"]), {"i": expected[tid]}
        )
        expected[tid] += 1
        assert seq == expected[tid]
    for tid in tids:
        n = expected[tid]
        evs = s.events_since(tid, 0)
        assert [e["seq"] for e in evs] == list(range(1, n + 1))
        assert s.last_seq(tid) == n
        if n:
            k = rng.randrange(n)
            tail = s.events_since(tid, k)
            assert [e["seq"] for e in tail] == list(range(k + 1, n + 1))
    s.close()


def test_events_cap_rolling_window(tmp_path: Path) -> None:
    """EVENT_CAP 滚动截断：窗内 seq 仍连续，旧段出局。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    for i in range(EVENT_CAP + _CAP_EXTRA):
        assert s.append_event(tid, "progress", {"i": i}) == i + 1
    evs = s.events_since(tid, 0)
    assert len(evs) == EVENT_CAP
    assert evs[0]["seq"] == _CAP_EXTRA + 1  # seq 1.._CAP_EXTRA 被裁
    assert [e["seq"] for e in evs] == list(
        range(_CAP_EXTRA + 1, EVENT_CAP + _CAP_EXTRA + 1)
    )
    assert evs[0]["data"] == {"i": _CAP_EXTRA}
    s.close()


# ---------------------------------------------------------------- 事务原子性


def test_insert_chunks_atomic(tmp_path: Path) -> None:
    """executemany 中段撞约束 → 全回滚，has_chunks 不假阳。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    rows = [_chunk_row(i) for i in range(5)]
    rows[3] = _chunk_row(1, chunk_id="cx")  # (task_id,seq) UNIQUE 冲突在中段
    with pytest.raises(sqlite3.IntegrityError):
        s.insert_chunks(tid, rows)
    assert not s.has_chunks(tid)
    assert s.all_chunks(tid) == []
    rows2 = [_chunk_row(i) for i in range(5)]
    rows2[4] = _chunk_row(9, chunk_id="c0")  # PK (task_id,chunk_id) 冲突
    with pytest.raises(sqlite3.IntegrityError):
        s.insert_chunks(tid, rows2)
    assert not s.has_chunks(tid)
    s.insert_chunks(tid, [_chunk_row(i) for i in range(3)])
    assert s.has_chunks(tid)
    assert [c["seq"] for c in s.all_chunks(tid)] == [0, 1, 2]
    s.close()


def test_flush_chunk_batch_atomic(tmp_path: Path) -> None:
    """updates/cache_puts/counters 一笔事务：中途炸全回滚。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    s.insert_chunks(tid, [_chunk_row(i) for i in range(3)])
    good = [("c0", {"status": "ok", "translation": "译0"})]
    bad = [("c1", {"status": "ok", "no_such_col": "x"})]  # 列名脏 → 中途炸
    with pytest.raises(sqlite3.OperationalError):
        s.flush_chunk_batch(
            tid, [*good, *bad], [("k1", "译", "m", "zh")], {"total": 3, "done": 1}
        )
    assert all(c["status"] == "pending" for c in s.all_chunks(tid))
    assert s.cache_get("k1") is None
    row = s.get(tid)
    assert row is not None
    assert (row["total_chunks"], row["done_chunks"], row["progress"]) == (0, 0, 0)
    s.flush_chunk_batch(
        tid, good, [("k1", "译", "m", "zh")], {"total": 3, "done": 1, "progress": 33}
    )
    assert s.cache_get("k1") == "译"
    row = s.get(tid)
    assert row is not None
    assert row["done_chunks"] == 1
    s.close()


def test_cache_hit_count_preserved(tmp_path: Path) -> None:
    """REPLACE 不清 hit_count（COALESCE 读旧行）；translation 取新值。

    命中记账是聚合落盘——随 ``flush_chunk_batch`` 事务顺带写。
    """
    s = _store(tmp_path)
    tid = _mk_task(s)
    s.insert_chunks(tid, [_chunk_row(0)])
    s.flush_chunk_batch(tid, [("c0", {"status": "ok"})], [("k", "v1", "m", "zh")], {})
    assert s.cache_get("k") == "v1"  # hit → 1（随下方批事务落）
    s.flush_chunk_batch(tid, [], [("k", "v2", "m", "zh")], {})
    assert s.cache_get("k") == "v2"  # hit → 2，新值在位
    s.flush_chunk_batch(tid, [], [], {})  # 空批也顺带落挂起记账
    hit = s.conn.execute(
        "SELECT hit_count FROM translation_cache WHERE key = ?", ("k",)
    ).fetchone()["hit_count"]
    assert hit == _EXPECTED_HITS
    s.close()


def test_flush_counters_missing_keys_zeroed(tmp_path: Path) -> None:
    """counters 缺键 → .get(k,0) 清零列——钉住「调用方全键」契约（观察项）。

    worker 恒传六键；若有第二调用方传缺省 dict，total/done/progress 会被
    静默归零——当前行为，非 defect，钉住以显化口径。
    """
    s = _store(tmp_path)
    tid = _mk_task(s)
    s.insert_chunks(tid, [_chunk_row(0)])
    s.flush_chunk_batch(
        tid,
        [("c0", {"status": "ok"})],
        [],
        {"total": 1, "done": 1, "progress": 50},
    )
    s.flush_chunk_batch(tid, [], [], {})
    row = s.get(tid)
    assert row is not None
    assert (row["total_chunks"], row["done_chunks"], row["progress"]) == (0, 0, 0)
    s.close()


# ---------------------------------------------------------------- 删除/恢复


def test_delete_task_cascade_idempotent(tmp_path: Path) -> None:
    """FK CASCADE 全清 + 幂等回执 False。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    s.insert_chunks(tid, [_chunk_row(i) for i in range(3)])
    s.put_file(tid, "pdf", "out/main.pdf", size=10, sha256="x")
    s.append_event(tid, "progress", {})
    s.record_usage(
        tid, model="m", calls=1, prompt_tokens=2, completion_tokens=3, latency_s=0.5
    )
    s.record_usage(
        tid, model="m", calls=1, prompt_tokens=1, completion_tokens=1, latency_s=0.1
    )
    usage = s.usage_for(tid)
    assert usage is not None
    assert usage["calls"] == _USAGE_CALLS  # upsert 累加
    assert s.delete_task(tid)
    assert s.get(tid) is None
    assert s.all_chunks(tid) == []
    assert s.files(tid) == {}
    assert s.events_since(tid, 0) == []
    assert s.usage_for(tid) is None
    assert not s.delete_task(tid)
    s.close()


def test_fuzz_recover_startup(tmp_path: Path) -> None:
    """混合脏状态恢复：ACTIVE-queued → interrupted/needs_auth(header)；
    queued+header → needs_auth；queued 清 worker_id；终态不碰；二次幂等。"""
    rng = random.Random(20261105)  # noqa: S311 -- 确定性种子
    s = _store(tmp_path)
    exp_status: dict[str, str] = {}
    claimed: set[str] = set()
    touched: set[str] = set()  # recover 实际改写的行 → worker_id 必清
    want = {"interrupted": 0, "needs_auth": 0}
    for _ in range(_RECOVER_TASKS):
        auth = rng.choice(["settings", "header"])
        st = rng.choice(_ALL_STATUSES)
        tid = _mk_task(s, auth_source=auth)
        _install(s, tid, st)
        if rng.random() < _CLAIMED_P:
            s.claim(tid, "w")
            claimed.add(tid)
        if st in (ACTIVE_STATUSES - {"queued"}):
            exp = "needs_auth" if auth == "header" else "interrupted"
            want[exp] += 1
            touched.add(tid)
        elif st == "queued" and auth == "header":
            exp = "needs_auth"
            want["needs_auth"] += 1
            touched.add(tid)
        elif st == "queued":
            exp = st
            touched.add(tid)  # queued 行残留 worker_id 清场
        else:
            exp = st  # 终态行 recover 不碰（认领标记也保留）
        exp_status[tid] = exp
    assert s.recover_startup() == want
    for tid, exp in exp_status.items():
        row = s.get(tid)
        assert row is not None
        assert row["status"] == exp
        if tid in touched:
            assert row["worker_id"] is None
        elif tid in claimed:
            assert row["worker_id"] == "w"
    assert s.recover_startup() == {"interrupted": 0, "needs_auth": 0}
    s.close()


# ---------------------------------------------------------------- 并发纪律


def test_concurrent_writers_serialize(tmp_path: Path) -> None:
    """每线程自持连接并发写同库：不死锁、不丢行、seq 各自连续。"""
    path = tmp_path / "c.db"
    s0 = Store(path)
    s0.open()
    tids = [_mk_task(s0) for _ in range(_N_THREADS)]
    s0.close()
    errors: list[str] = []

    def _worker(idx: int) -> None:
        try:
            s = Store(path)
            s.open()
            for j in range(_OPS_PER_THREAD):
                s.append_event(tids[idx], "progress", {"w": idx, "j": j})
                s.heartbeat(tids[idx])
            s.close()
        except Exception as exc:  # noqa: BLE001 -- 线程内全收，集中断言
            errors.append(f"w{idx}: {exc!r}")

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(_N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert all(not t.is_alive() for t in threads)
    assert errors == []
    s = Store(path)
    s.open()
    for tid in tids:
        evs = s.events_since(tid, 0)
        assert [e["seq"] for e in evs] == list(range(1, _OPS_PER_THREAD + 1))
    s.close()


def test_cross_thread_rejected_loudly(tmp_path: Path) -> None:
    """check_same_thread 缺省开：越线程直调当场 ProgrammingError（非静默竞写）。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    errors: list[str] = []

    def _probe() -> None:
        try:
            s.get(tid)
        except sqlite3.ProgrammingError:
            errors.append("ProgrammingError")
        except Exception as exc:  # noqa: BLE001 -- 线程内全收，集中断言
            errors.append(repr(exc))

    t = threading.Thread(target=_probe)
    t.start()
    t.join(timeout=5)
    assert errors == ["ProgrammingError"]
    s.close()


def test_claim_no_cas_last_writer_wins(tmp_path: Path) -> None:
    """claim 是无条件 UPDATE（无 CAS）——双连接顺序认领后到者赢。

    DB 层不防竞；真护栏是单写者纪律（dispatch 串行 + 越线程炸）。
    钉住以显化「认领不保证唯一」。
    """
    path = tmp_path / "claim.db"
    s1, s2 = Store(path), Store(path)
    s1.open()
    s2.open()
    tid = _mk_task(s1)
    s1.claim(tid, "w1")
    s2.claim(tid, "w2")
    row = s1.get(tid)
    assert row is not None
    assert row["worker_id"] == "w2"
    s1.close()
    s2.close()


# ---------------------------------------------------------------- snapshot/杂项查询


def test_snapshot_counters_consistency(tmp_path: Path) -> None:
    """snapshot.counters 与 chunk_counts/任务列对账；last_seq/warnings 同形。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    s.insert_chunks(tid, [_chunk_row(i) for i in range(_SNAP_TOTAL)])
    s.flush_chunk_batch(
        tid,
        [
            ("c0", {"status": "ok"}),
            ("c1", {"status": "ok"}),
            ("c2", {"status": "fallback_orig"}),
            ("c3", {"status": "failed"}),
        ],
        [],
        {
            "total": _SNAP_TOTAL,
            "done": _SNAP_DONE,
            "cached": _SNAP_CACHED,
            "failed": _SNAP_FAILED,
            "tokens": _SNAP_TOKENS,
            "progress": _SNAP_PROGRESS,
        },
    )
    snap = s.snapshot(tid, artifacts={"pdf": "x"})
    cc = s.chunk_counts(tid)
    assert snap["counters"]["total"] == cc["total"] == _SNAP_TOTAL
    assert snap["counters"]["done"] == cc["done"] == _SNAP_DONE
    assert snap["counters"]["failed"] == cc["failed"] == _SNAP_FAILED
    assert snap["counters"]["cached"] == _SNAP_CACHED  # 任务列——chunks 表推不出
    assert snap["counters"]["tokens"] == _SNAP_TOKENS
    assert snap["progress"] == _SNAP_PROGRESS
    seq = s.append_event(tid, "warning", {"code": "w", "message": "m"})
    s.append_event(tid, "warning", {"plain": "nonmsg"})
    snap2 = s.snapshot(tid, artifacts={})
    assert snap2["last_seq"] == seq + 1
    assert snap2["warnings"] == ["[w] m", "{'plain': 'nonmsg'}"]
    s.close()


def test_task_queries(tmp_path: Path) -> None:
    """_list_tasks_all 租户隔离 + 过滤；find_active_by_cache_key；tenant_usage；
    delete_file 幂等回执。"""
    s = _store(tmp_path)
    ta = _mk_task(s, tenant="a", cache_key="k1")
    tb = _mk_task(s, tenant="a")
    tc = _mk_task(s, tenant="b")
    _install(s, ta, "translating")
    _install(s, tb, "done")
    assert {r["id"] for r in s._list_tasks_all("a")} == {ta, tb}  # noqa: SLF001 -- 测试专用私有方法
    assert [r["id"] for r in s._list_tasks_all("a", status="done")] == [tb]  # noqa: SLF001
    active = s.find_active_by_cache_key("k1")
    assert active is not None
    assert active["id"] == ta
    _install(s, ta, "done")
    assert s.find_active_by_cache_key("k1") is None  # 终态出局
    s.put_file(ta, "pdf", "a.pdf", size=7)
    s.put_file(ta, "pdf", "a2.pdf", size=11)  # upsert 同 kind 覆写
    s.put_file(tc, "pdf", "c.pdf", size=100)
    assert s.tenant_usage("a") == {"tasks": 2, "bytes": 11}
    assert s.delete_file(ta, "pdf") == "a2.pdf"
    assert s.delete_file(ta, "pdf") is None
    s.close()


# ---------------------------------------------------------------- EventBus


def test_bus_fanout_order(tmp_path: Path) -> None:
    """N 订阅者各自收全序保 seq；他任务隔离。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    other = _mk_task(s)

    async def _go() -> None:
        bus = EventBus(s)
        qs = [bus.subscribe(tid) for _ in range(_N_SUBS)]
        q_other = bus.subscribe(other)
        for i in range(_N_EVENTS):
            bus.publish(tid, "progress", {"i": i})
        bus.publish(other, "progress", {"i": -1})
        for q in qs:
            seqs = []
            while not q.empty():
                seqs.append(q.get_nowait()["seq"])
            assert seqs == list(range(1, _N_EVENTS + 1))
        assert q_other.qsize() == 1
        assert q_other.get_nowait()["seq"] == 1  # 各自任务独立计数

    asyncio.run(_go())
    s.close()


def test_bus_overflow_resync(tmp_path: Path) -> None:
    """停滞消费者溢出 → 队列压 _RESYNC 哨兵 + 摘除；落盘面无损可重放。"""
    s = _store(tmp_path)
    tid = _mk_task(s)

    async def _go() -> None:
        bus = EventBus(s)
        q = bus.subscribe(tid)
        for i in range(_SUB_QUEUE_MAX + _OVERFLOW_EXTRA):
            bus.publish(tid, "progress", {"i": i})
        assert q.get_nowait() is _RESYNC
        assert q.empty()
        bus.publish(tid, "progress", {"i": -1})  # 已摘除——不再进 q
        assert q.empty()
        assert s.last_seq(tid) == _SUB_QUEUE_MAX + _OVERFLOW_EXTRA + 1

    asyncio.run(_go())
    s.close()


def test_stream_replay_live_done(tmp_path: Path) -> None:
    """stream：重放 last_event_id 之后 → 实时续流 → done 终结 + 退订实效。"""
    s = _store(tmp_path)
    tid = _mk_task(s)

    async def _go() -> None:
        bus = EventBus(s)
        bus.publish(tid, "progress", {"i": 1})
        s2 = bus.publish(tid, "progress", {"i": 2})
        gen = bus.stream(tid, last_event_id=s2 - 1)
        ev = await gen.__anext__()
        assert (ev["seq"], ev["type"]) == (s2, "progress")
        s3 = bus.publish(tid, "progress", {"i": 3})  # 实时段
        ev = await gen.__anext__()
        assert ev["seq"] == s3
        bus.publish(tid, "done", {})
        ev = await gen.__anext__()
        assert ev["type"] == "done"
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    asyncio.run(_go())
    s.close()


def test_stream_unsubscribes_on_done(tmp_path: Path) -> None:
    """流终结 finally→unsubscribe：被摘队列不再收扇出（disconnect cleanup）。"""
    s = _store(tmp_path)
    tid = _mk_task(s)

    async def _go() -> None:
        bus = EventBus(s)
        seen: list[asyncio.Queue[dict[str, Any]]] = []
        orig = bus.unsubscribe

        def _spy(task_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
            seen.append(q)
            orig(task_id, q)

        bus.unsubscribe = _spy
        _install(s, tid, "done")  # done 帧只对真终态任务终结重放
        bus.publish(tid, "done", {})
        got = [ev async for ev in bus.stream(tid)]
        assert [e["type"] for e in got] == ["done"]  # 重放见 done 即终
        assert len(seen) == 1
        bus.publish(tid, "progress", {"i": 1})
        assert seen[0].empty()

    asyncio.run(_go())
    s.close()


def test_stream_terminal_row_short_circuit(tmp_path: Path) -> None:
    """终态行（无 done 事件）与已删行：重放照发 → 判终即返，不空等。"""
    s = _store(tmp_path)
    tid = _mk_task(s)
    s.append_event(tid, "progress", {"i": 1})
    _install(s, tid, "done")  # recover/直改路径：终态无 done 事件

    async def _go() -> None:
        bus = EventBus(s)
        got = [ev async for ev in bus.stream(tid)]
        assert [e["seq"] for e in got] == [1]
        gone = _mk_task(s)
        s.delete_task(gone)
        got2 = [ev async for ev in bus.stream(gone)]
        assert got2 == []

    asyncio.run(_go())
    s.close()


def test_close_all_wakes_parked_stream(tmp_path: Path) -> None:
    """close_all 压哨兵唤醒 parked 生成器——不停 loop 死等。"""
    s = _store(tmp_path)
    tid = _mk_task(s)

    async def _go() -> None:
        bus = EventBus(s)
        gen = bus.stream(tid)
        parked = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(_PARK_MS)  # 让它走到 q.get()
        bus.close_all()
        done = False
        try:
            await asyncio.wait_for(parked, _WAKE_TIMEOUT_S)
        except StopAsyncIteration:
            done = True
        assert done

    asyncio.run(_go())
    s.close()


def test_sse_frame_shape() -> None:
    """sse_frame 字段映射 + ensure_ascii=False 序列化。"""
    ev = {"seq": 3, "type": "progress", "data": {"k": "中"}}
    assert sse_frame(ev) == {
        "id": "3",
        "event": "progress",
        "data": '{"k": "中"}',
    }
