"""gate_scorecard A4 硬化面 L0 钉——csb 加深/波次窗/冻结窗/scope+--json 完整。

不变量清单：

- ``pick_final`` 新 drop_reason 封闭：``post_inconsistent``（f.status 与
  metrics.post.status 相悖=拼账/腐记录）、``csb_contradicts_fp``（指纹
  匹配证明 fix 吃的就是当前 compile 而 csb 字段相悖）、``window_stale``
  （legacy-csb 过门但 compile(zh,同上游) 覆盖波晚于 fixloop 覆盖波）。
  三档均不污染既有真值表（over_noncompiled/no_csb/stale/fp_mismatch/
  upstream_mismatch 原样）。
- ``csb_check`` 桶三分：fingerprint/legacy_status/none——无 fp 无 csb
  的 fix 落 none，不再误记 legacy_status。
- ``window_suspects``：--ids 显式集/--xlat-arm 匹配口径；compile 侧取
  最新覆盖波、fixloop 侧取 max(--rerun 波, 最早覆盖波)；非 --rerun
  fixloop 波不刷新 done 格→不抬 fix 写时估计；meta 缺席 → 空集。
- ``check_freeze``：in_flight_invocation/recent_write/tail_truncated/
  torn_read 四路 → partial；干净窗 → frozen；meta 缺席不崩。
- ``main --require-frozen``：partial → exit 3 且只出 freeze 块；
  frozen → 正常记分 exit 0。
- ``--json``：schema v3 + generated_at/scope/population/freeze/
  freshness_window 在场；end_state.reject 与 excl_reject 互补自洽；
  union scope 钉阶段并集语义（非 zh+base 臂并集）。
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import gate_scorecard

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_NOW = time.time()
_OLD = _NOW - 86400 * 3  # 三天前——稳超 write-window


def _rec(pid: str, stage: str, status: object, **over: object) -> dict:
    r = {
        "id": pid,
        "stage": stage,
        "arm": "zh" if stage == "compile" else "fix",
        "upstream": "mock",
        "status": status,
        "metrics": {},
        "errors": [],
        "sig": "",
    }
    r.update(over)
    return r


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False))
            f.write("\n")


def _mk_run(tmp_path: Path, comp_rows: list, fix_rows: list, meta: dict | None) -> Path:
    """run/records 两层结构 + 可选 run_meta.json → records_dir。"""
    recdir = tmp_path / "run" / "records"
    _write_jsonl(recdir / "compile.jsonl", comp_rows)
    _write_jsonl(recdir / "fixloop.jsonl", fix_rows)
    if meta is not None:
        (tmp_path / "run" / "run_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
    return recdir


def _age(path: Path, ts: float = _OLD) -> None:
    """mtime 回拨——fresh tmp 文件默认落 write-window 内，测 frozen 必须老化。"""
    os.utime(path, (ts, ts))


def _inv(ts: str, stage: str, *argv: str) -> dict:
    return {"ts": ts, "stage": stage, "argv": list(argv)}


# ================================================================ pick_final 加深
def test_pick_final_post_inconsistent() -> None:
    """f.status 与 metrics.post.status 相悖 → post_inconsistent；缺失/非 str 不判。"""
    c = _rec("p", "compile", "fail")
    bad = {
        "id": "p",
        "status": "clean",
        "metrics": {
            "compile_status_before": "fail",
            "post": {"status": "fail"},
        },
    }
    assert gate_scorecard.pick_final(c, bad) == ("compile", c, "post_inconsistent")
    # post.status 缺席/非 str/一致 → 不判，正常接管
    for post in ({}, {"status": "clean"}, {"status": 5}, {"status": None}, "x", 5):
        f = {
            "id": "p",
            "status": "clean",
            "metrics": {"compile_status_before": "fail", "post": post},
        }
        assert gate_scorecard.pick_final(c, f) == ("fixloop", f, None), post


def test_pick_final_csb_contradicts_fp() -> None:
    """fp 匹配 + csb 相悖 → csb_contradicts_fp（拼账记录）；csb 相符/缺席 → 接管。"""
    c = _rec("p", "compile", "fail", sig="syntax:x", code="abc")
    fp = gate_scorecard.compile_fp(c)
    contra = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_fp": fp, "compile_status_before": "partial"},
    }
    stage, _r, drop = gate_scorecard.pick_final(c, contra)
    assert (stage, drop) == ("compile", "csb_contradicts_fp")
    ok = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_fp": fp, "compile_status_before": "fail"},
    }
    assert gate_scorecard.pick_final(c, ok) == ("fixloop", ok, None)
    no_csb = {"id": "p", "status": "clean", "metrics": {"compile_fp": fp}}
    assert gate_scorecard.pick_final(c, no_csb) == ("fixloop", no_csb, None)
    # fp 失配仍优先报 fp_mismatch（指纹是更强判据）
    bad = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_fp": "f" * 16, "compile_status_before": "fail"},
    }
    assert gate_scorecard.pick_final(c, bad)[2] == "fp_mismatch"


def test_pick_final_window_stale() -> None:
    """legacy-csb 过门 + window_suspect → window_stale；指纹档不受窗判。"""
    c = _rec("p", "compile", "fail")
    legacy = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_status_before": "fail"},
    }
    assert gate_scorecard.pick_final(c, legacy, window_suspect=True) == (
        "compile",
        c,
        "window_stale",
    )
    assert gate_scorecard.pick_final(c, legacy, window_suspect=False) == (
        "fixloop",
        legacy,
        None,
    )
    # 指纹档：fp 匹配即新鲜，窗判无权拦（per-record 证据强于波次估计）
    fpfix = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_fp": gate_scorecard.compile_fp(c)},
    }
    assert gate_scorecard.pick_final(c, fpfix, window_suspect=True) == (
        "fixloop",
        fpfix,
        None,
    )
    # csb 未过门仍 stale——窗判只在过门后生效
    stale = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_status_before": "partial"},
    }
    assert gate_scorecard.pick_final(c, stale, window_suspect=True)[2] == "stale"


# ================================================================ csb_check 三分桶
def test_csb_check_three_buckets(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """fingerprint/legacy_status/none 各归其桶——两无记录不再误记 legacy。"""
    c_fail = _rec("a", "compile", "fail")
    comp = [
        c_fail,
        _rec("b", "compile", "fail"),
        _rec("c", "compile", "fail"),
        _rec("d", "compile", "fail"),
    ]
    fix = [
        {
            "id": "a",
            "status": "clean",
            "upstream": "mock",
            "metrics": {"compile_fp": gate_scorecard.compile_fp(c_fail)},
        },
        {
            "id": "b",
            "status": "clean",
            "upstream": "mock",
            "metrics": {"compile_status_before": "fail"},
        },
        {"id": "c", "status": "clean", "upstream": "mock", "metrics": {}},
        {"id": "d", "status": "clean", "upstream": "mock"},  # 无 metrics 键
    ]
    recdir = _mk_run(tmp_path, comp, fix, None)
    assert gate_scorecard.main([str(recdir), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["csb_check"] == {
        "fingerprint": 1,
        "legacy_status": 1,
        "none": 2,
    }
    # c/d 两无 → no_csb 丢（与桶计数互证）
    assert d["dropped_fix"]["no_csb"] == 2  # noqa: PLR2004 -- 钉计数即断言对象


# ================================================================ window_suspects
def test_window_suspects_basic_and_scope() -> None:
    """compile 覆盖波晚于 fixloop 覆盖波 → suspect；--ids/--xlat-arm 限定口径。"""
    meta = {
        "finished_at": "2026-09-18T00:00:00+00:00",
        "invocations": [
            _inv("2026-09-17T01:00:00+00:00", "fixloop", "--on", "fail"),
            _inv(
                "2026-09-17T02:00:00+00:00",
                "compile",
                "--arm",
                "zh",
                "--xlat-arm",
                "mock",
            ),
        ],
    }
    assert gate_scorecard.window_suspects(meta, {"a", "b"}) == {"a", "b"}
    # fixloop --rerun 波晚于 compile 波 → fix 可能已重写 → 不 suspect
    meta2 = {
        "finished_at": "2026-09-18T00:00:00+00:00",
        "invocations": [
            _inv("2026-09-17T01:00:00+00:00", "fixloop", "--on", "fail"),
            _inv("2026-09-17T02:00:00+00:00", "compile", "--arm", "zh"),
            _inv(
                "2026-09-17T03:00:00+00:00",
                "fixloop",
                "--on",
                "fail",
                "--rerun",
            ),
        ],
    }
    assert gate_scorecard.window_suspects(meta2, {"a"}) == set()
    # --ids 限定：compile 波只覆盖 a,b → c 不 suspect
    meta3 = {
        "finished_at": "2026-09-18T00:00:00+00:00",
        "invocations": [
            _inv("2026-09-17T01:00:00+00:00", "fixloop"),
            _inv(
                "2026-09-17T02:00:00+00:00",
                "compile",
                "--arm",
                "zh",
                "--ids",
                "a,b",
            ),
        ],
    }
    assert gate_scorecard.window_suspects(meta3, {"a", "b", "c"}) == {"a", "b"}
    # base 臂 compile 波不入 zh 口径；real 上游 fixloop 波不盖 mock 账
    meta4 = {
        "finished_at": "2026-09-18T00:00:00+00:00",
        "invocations": [
            _inv("2026-09-17T01:00:00+00:00", "fixloop"),
            _inv("2026-09-17T02:00:00+00:00", "compile", "--arm", "base"),
            _inv(
                "2026-09-17T03:00:00+00:00",
                "fixloop",
                "--xlat-arm",
                "real",
                "--rerun",
            ),
        ],
    }
    assert gate_scorecard.window_suspects(meta4, {"a"}) == set()


def test_window_suspects_nonrerun_no_refresh() -> None:
    """非 --rerun 的 fixloop 波不抬 fix 写时估计——done 格不重写。

    fixloop 早波写过记录，compile 中波重写，fixloop 晚波（非 rerun，格已
    done 不重写）扫过不改账——仍 suspect（记录可能参照被覆盖的 compile）。
    """
    meta = {
        "finished_at": "2026-09-18T00:00:00+00:00",
        "invocations": [
            _inv("2026-09-17T01:00:00+00:00", "fixloop"),
            _inv("2026-09-17T02:00:00+00:00", "compile", "--arm", "zh"),
            _inv("2026-09-17T03:00:00+00:00", "fixloop"),  # 非 rerun——不抬估计
        ],
    }
    assert gate_scorecard.window_suspects(meta, {"a"}) == {"a"}


def test_window_suspects_meta_absent_or_dirty() -> None:
    assert gate_scorecard.window_suspects(None, {"a"}) == set()
    assert gate_scorecard.window_suspects({}, {"a"}) == set()
    dirty = {"invocations": [{"ts": "junk", "stage": "compile"}, "x", 5]}
    assert gate_scorecard.window_suspects(dirty, {"a"}) == set()


# ================================================================ check_freeze
def _quiet_files() -> dict:
    return {
        "compile.jsonl": {
            "exists": True,
            "torn": False,
            "tail_truncated": False,
            "bad_lines": 0,
            "age_s": 9999.0,
        },
        "fixloop.jsonl": {
            "exists": True,
            "torn": False,
            "tail_truncated": False,
            "bad_lines": 0,
            "age_s": 9999.0,
        },
    }


def test_freeze_clean_window(tmp_path: Path) -> None:
    meta = {
        "finished_at": "2026-09-17T12:00:00+00:00",
        "invocations": [_inv("2026-09-17T01:00:00+00:00", "compile")],
    }
    fz = gate_scorecard.check_freeze(tmp_path, _quiet_files(), meta)
    assert fz["status"] == "frozen"
    assert fz["partial"] is False
    assert fz["signals"]["run_meta"] == "present"


def test_freeze_inflight_invocation(tmp_path: Path) -> None:
    """invocation.ts > finished_at → 在飞/被硬杀波次 → partial。"""
    meta = {
        "finished_at": "2026-09-17T01:30:00+00:00",
        "invocations": [
            _inv("2026-09-17T01:00:00+00:00", "compile"),
            _inv("2026-09-17T02:00:00+00:00", "fixloop", "--on", "fail"),
        ],
    }
    fz = gate_scorecard.check_freeze(tmp_path, _quiet_files(), meta)
    assert fz["status"] == "partial"
    assert "in_flight_invocation" in fz["reasons"]
    assert fz["signals"]["in_flight_invocations"][0]["stage"] == "fixloop"
    # finished_at 缺席 = 有 invocation 从未收尾 → 同样在飞
    meta2 = {"invocations": [_inv("2026-09-17T01:00:00+00:00", "compile")]}
    fz2 = gate_scorecard.check_freeze(tmp_path, _quiet_files(), meta2)
    assert fz2["status"] == "partial"


def test_freeze_file_signals(tmp_path: Path) -> None:
    files = _quiet_files()
    files["compile.jsonl"]["age_s"] = 5.0  # 窗口内写
    fz = gate_scorecard.check_freeze(tmp_path, files, None, write_window=120.0)
    assert fz["status"] == "partial"
    assert "recent_write:compile.jsonl" in fz["reasons"]
    files = _quiet_files()
    files["fixloop.jsonl"]["tail_truncated"] = True
    fz = gate_scorecard.check_freeze(tmp_path, files, None)
    assert "tail_truncated:fixloop.jsonl" in fz["reasons"]
    files = _quiet_files()
    files["compile.jsonl"]["torn"] = True
    fz = gate_scorecard.check_freeze(tmp_path, files, None)
    assert "torn_read:compile.jsonl" in fz["reasons"]
    # meta 缺席 → run_meta 信号 absent 但文件面独立生效
    assert fz["signals"]["run_meta"] == "absent"


def test_tail_truncated_real_file(tmp_path: Path) -> None:
    p = tmp_path / "compile.jsonl"
    p.write_text('{"id":"a","status":"clean"}\n{"id":"b","sta', encoding="utf-8")
    assert gate_scorecard._tail_truncated(p) is True  # noqa: SLF001 -- 白盒钉截尾探测
    p.write_text('{"id":"a"}\n{"id":"b","status":"x"}\n', encoding="utf-8")
    assert gate_scorecard._tail_truncated(p) is False  # noqa: SLF001 -- 同上
    p.write_text("", encoding="utf-8")
    assert gate_scorecard._tail_truncated(p) is False  # noqa: SLF001 -- 同上
    assert gate_scorecard._tail_truncated(tmp_path / "missing.jsonl") is False  # noqa: SLF001 -- 同上


def test_scan_file_torn_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """读前后 stat 双采样不一致 → torn=True（读到混合截面）。"""
    p = tmp_path / "compile.jsonl"
    _write_jsonl(p, [{"id": "a", "arm": "zh", "status": "clean"}])
    seq = iter([(10, 1), (99, 2)])  # pre/post sig 不同 → 读中被改写
    monkeypatch.setattr(gate_scorecard, "_stat_sig", lambda _p: next(seq, (99, 2)))
    _recs, _st, info = gate_scorecard._scan_file(  # noqa: SLF001 -- 白盒钉双采样
        p, "zh", "mock", datetime.now(UTC)
    )
    assert info["torn"] is True


# ================================================================ main 集成面
def test_main_require_frozen_blocks_partial(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """fresh-mtime records（tmp 刚写→recent_write）→ partial → exit 3。"""
    recdir = _mk_run(
        tmp_path,
        [{"id": "a", "arm": "zh", "upstream": "mock", "status": "clean"}],
        [],
        None,
    )
    assert gate_scorecard.main([str(recdir), "--require-frozen"]) == 3  # noqa: PLR2004 -- exit 码即断言对象
    assert "PARTIAL" in capsys.readouterr().out
    # json 模式：只出 freeze 块 + error 标记
    assert gate_scorecard.main([str(recdir), "--require-frozen", "--json"]) == 3  # noqa: PLR2004 -- 同上
    d = json.loads(capsys.readouterr().out)
    assert d["error"] == "records_not_frozen"
    assert d["freeze"]["partial"] is True
    assert "recent_write:compile.jsonl" in d["freeze"]["reasons"]


def test_main_require_frozen_passes_frozen(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """老 mtime + 收尾 meta → frozen → 正常记分。"""
    meta = {
        "finished_at": "2026-09-17T12:00:00+00:00",
        "invocations": [_inv("2026-09-17T01:00:00+00:00", "compile")],
    }
    recdir = _mk_run(
        tmp_path,
        [{"id": "a", "arm": "zh", "upstream": "mock", "status": "clean"}],
        [],
        meta,
    )
    _age(recdir / "compile.jsonl")
    _age(recdir / "fixloop.jsonl")
    assert gate_scorecard.main([str(recdir), "--require-frozen", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["freeze"]["status"] == "frozen"
    assert d["cells"] == 1


def test_main_json_scope_population(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """--json 全字段面：scope 语义钉/population 过滤账/reject 互补。"""
    comp = [
        {"id": "a", "arm": "zh", "upstream": "mock", "status": "clean"},
        {"id": "b", "arm": "zh", "upstream": "mock", "status": "reject"},
        {"id": "c", "arm": "base", "upstream": "mock", "status": "clean"},  # arm 滤
        {"id": "d", "arm": "zh", "upstream": "real", "status": "clean"},  # 上游滤
        {"id": "a", "arm": "zh", "upstream": "mock", "status": "fail"},  # 末条胜
    ]
    recdir = _mk_run(tmp_path, comp, [], None)
    assert gate_scorecard.main([str(recdir), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["schema"] == "gate_scorecard/v3"
    assert d["generated_at"]
    sc = d["scope"]
    assert sc["arm"] == "zh"
    assert sc["upstream"] == "mock"
    assert "best-of" in sc["union"]
    assert "zh+base" in sc["union_not"]  # 非臂并集显式标注
    pop = d["population"]["compile"]
    assert pop["rows"] == 5  # noqa: PLR2004 -- 钉行数即断言对象
    assert pop["arm_filtered"] == 1
    assert pop["upstream_filtered"] == 1
    assert pop["accepted"] == 3  # noqa: PLR2004 -- 同上
    assert pop["unique"] == 2  # noqa: PLR2004 -- 同上
    assert pop["superseded"] == 1
    assert d["cells"] == 2  # noqa: PLR2004 -- 同上
    # reject 互补口径：cells=reject+n_norej
    assert d["end_state"]["reject"] == 1
    assert d["end_state"]["excl_reject"]["n"] == 1
    assert d["freshness_window"]["run_meta"] == "absent"
    assert d["freeze"]["status"] in {"frozen", "partial"}


def test_main_window_stale_drops(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """端到端：compile 波晚于 fixloop 波 → legacy fix 按 window_stale 丢。"""
    meta = {
        "finished_at": "2026-09-18T00:00:00+00:00",
        "invocations": [
            _inv("2026-09-17T01:00:00+00:00", "fixloop", "--on", "fail"),
            _inv(
                "2026-09-17T02:00:00+00:00",
                "compile",
                "--arm",
                "zh",
                "--xlat-arm",
                "mock",
            ),
        ],
    }
    comp = [{"id": "a", "arm": "zh", "upstream": "mock", "status": "fail"}]
    fix = [
        {
            "id": "a",
            "status": "clean",
            "upstream": "mock",
            "metrics": {"compile_status_before": "fail"},
        }
    ]
    recdir = _mk_run(tmp_path, comp, fix, meta)
    _age(recdir / "compile.jsonl")
    _age(recdir / "fixloop.jsonl")
    assert gate_scorecard.main([str(recdir), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["dropped_fix"] == {"window_stale": 1}
    assert d["freshness_window"]["suspect_cells"] == 1
    assert d["freshness_window"]["window_stale_dropped"] == 1
    # fix 被窗判丢 → end-state 回 compile:fail（假绿堵住）
    assert d["end_state"]["dist"] == {"compile:fail": 1}
    # 对照：无 meta → 同数据正常接管
    recdir2 = _mk_run(tmp_path / "m2", comp, fix, None)
    _age(recdir2 / "compile.jsonl")
    _age(recdir2 / "fixloop.jsonl")
    assert gate_scorecard.main([str(recdir2), "--json"]) == 0
    d2 = json.loads(capsys.readouterr().out)
    assert d2["end_state"]["dist"] == {"fixloop:clean": 1}


def test_main_partial_annotation(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """不加 --require-frozen 时 partial 仍记分但显式标注（文本+json 同源）。"""
    meta = {
        "finished_at": "2026-09-17T01:30:00+00:00",
        "invocations": [
            _inv("2026-09-17T01:00:00+00:00", "compile"),
            _inv("2026-09-17T02:00:00+00:00", "fixloop", "--on", "fail"),
        ],
    }
    recdir = _mk_run(
        tmp_path,
        [{"id": "a", "arm": "zh", "upstream": "mock", "status": "clean"}],
        [],
        meta,
    )
    _age(recdir / "compile.jsonl")
    _age(recdir / "fixloop.jsonl")
    assert gate_scorecard.main([str(recdir)]) == 0
    out = capsys.readouterr().out
    assert "freeze: PARTIAL" in out
    assert "in_flight_invocation" in out
    assert gate_scorecard.main([str(recdir), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["freeze"]["status"] == "partial"
    assert d["cells"] == 1  # 仍记分——partial 是标注非拒


def test_scan_records_population_conservation(tmp_path: Path) -> None:
    """行级去向守恒：accepted=Σ存活行；superseded=accepted-unique；各滤桶互斥。"""
    rows = [
        {"id": "a", "arm": "zh", "status": "fail"},
        {"id": "a", "arm": "zh", "status": "clean"},  # supersede
        {"id": "b", "arm": "base", "status": "fail"},  # arm_filtered
        {"id": "c", "arm": "zh", "status": "fail", "upstream": "real"},  # 上游滤
        {"id": 5, "arm": "zh", "status": "fail"},  # bad_id
        "{broken",
        "5",  # non_dict
        "",
        {"id": "d", "arm": "zh", "status": "fail", "errors": [{"code": "arm_mismatch"}]},
    ]
    p = tmp_path / "compile.jsonl"
    _write_jsonl(p, rows)
    latest, st = gate_scorecard.scan_records(p, arm="zh", upstream="mock")
    assert sorted(latest) == ["a"]  # c 被 upstream 滤——(upstream or mock) 口径
    assert st["rows"] == 7  # noqa: PLR2004 -- 钉行数即断言对象
    assert st["bad_lines"] == 1
    assert st["non_dict"] == 1
    assert st["arm_filtered"] == 1
    assert st["upstream_filtered"] == 1
    assert st["arm_mismatch"] == 1
    assert st["bad_id"] == 1
    assert st["accepted"] == 2  # noqa: PLR2004 -- 同上
    assert st["unique"] == 1
    assert st["superseded"] == 1
    # upstream=None 时 c(real) 也收——superseded 语义不变
    latest2, st2 = gate_scorecard.scan_records(p, arm="zh", upstream=None)
    assert sorted(latest2) == ["a", "c"]
    assert st2["accepted"] == 3  # noqa: PLR2004 -- 同上
    assert st2["unique"] == 2  # noqa: PLR2004 -- 同上
    assert st2["superseded"] == 1
