"""tests/bench_kernel/test_adversarial_fixes.py — D 批裁决回归.

Each test pins one ids-import-review finding that was adjudicated REAL and
fixed. Assertions encode the post-fix contract, not observed behavior.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest
from kernel import events, idnorm, importer, kernel, ledger, report
from kernel.index import Index
from kernel.spec import Spec, Stage

if TYPE_CHECKING:
    from pathlib import Path

# -- events.validate: universal extra-key + type gates ------------------------


def _ev(etype: str, **kw: object) -> dict:
    return events.make_event(etype, **kw)


def test_validate_rejects_registry_vocab_smuggling() -> None:
    """tail7/cat/resolved on ANY event type must die — they feed
    PapersRegistry._feed_row on replay."""
    base = {
        "run": "r",
        "seq": 1,
        "id": "x",
        "idc": "2101.12345",
        "arm": "a",
        "up": "-",
        "variant": "-",
        "stage": "s",
    }
    with pytest.raises(events.EventError):
        events.validate({**_ev(events.T_CELL, **base, status="ok"), "tail7": "9601002"})
    with pytest.raises(events.EventError):
        events.validate(
            {
                **_ev(events.T_NOTE, run="r", seq=1, text="t", level="info"),
                "resolved": "cond-mat/9601002",
            }
        )
    with pytest.raises(events.EventError):
        events.validate(
            {
                **_ev(events.T_CELL, **base, status="ok"),
                "cat": "claimed",
                "archive": "hep-th",
            }
        )


def test_validate_rejects_extra_keys_on_all_types() -> None:
    with pytest.raises(events.EventError):
        events.validate(
            {
                **_ev(
                    events.T_RUN_REGISTERED,
                    run="r",
                    run_seq=1,
                    kind="k",
                    date="2026-01-01",
                    slug="s",
                    spec_hash="h",
                    ts_start=1.0,
                ),
                "verdict": "x",
            }
        )
    with pytest.raises(events.EventError):
        events.validate(
            {**_ev(events.T_FINISHED, run="r", seq=1, wall_s=1.0, counts={}), "eval": 1}
        )
    with pytest.raises(events.EventError):
        events.validate(
            {
                **_ev(
                    events.T_CELL_QUEUED,
                    run="r",
                    seq=1,
                    id="x",
                    idc="2101.12345",
                    arm="a",
                    up="-",
                    variant="-",
                    stage="s",
                ),
                "metrics": {},
            }
        )


def test_validate_version_and_field_types() -> None:
    base = {
        "run": "r",
        "seq": 1,
        "id": "x",
        "idc": "2101.12345",
        "arm": "a",
        "up": "-",
        "variant": "-",
        "stage": "s",
        "status": "ok",
    }
    good = _ev(events.T_CELL, **base)
    events.validate(good)
    bad_ver = dict(good, v=events.SCHEMA_V + 99)
    with pytest.raises(events.EventError):
        events.validate(bad_ver)
    with pytest.raises(events.EventError):
        events.validate({**good, "seq": "1"})
    with pytest.raises(events.EventError):
        events.validate({**good, "dur_s": True})
    with pytest.raises(events.EventError):
        events.validate({**good, "metrics": "x"})
    with pytest.raises(events.EventError):
        events.validate({**good, "errors": "x"})
    with pytest.raises(events.EventError):
        events.validate({**good, "cat": "bogus-cat"})
    with pytest.raises(events.EventError):
        events.validate({**good, "eval": "yes"})
    # legit values still pass
    events.validate({**good, "eval": True})
    events.validate({**good, "eval": 1, "cat": "paid_pool"})


# -- idnorm: escape '/', case-fold, 9-digit reject ------------------------------


def test_escape_component_roundtrips_slash() -> None:
    assert "/" not in idnorm.escape_component("a/b")
    assert idnorm.unescape_component(idnorm.escape_component("a/b")) == "a/b"
    assert idnorm.unescape_component(idnorm.escape_component("a%b")) == "a%b"


def test_canon_id_case_folds_cat() -> None:
    assert idnorm.canon_id("Hep-Th/0101001").idc == "hep-th/0101001"
    r = idnorm.canon_id("MATH.QA/9703043")
    # no registry -> the official new-name spelling stands
    assert r.ok
    assert r.idc == "math.QA/9703043"
    reg = idnorm.PapersRegistry()
    reg.add("q-alg/9703043", src="manifest")
    assert idnorm.canon_id("math.qa/9703043", reg).idc == "q-alg/9703043"


def test_canon_id_rejects_9digit_old_suffix() -> None:
    assert not idnorm.canon_id("hep-th/970304312").ok  # 9-digit: never minted
    assert idnorm.canon_id("hep-th/97030431").ok  # 8-digit serial ok
    assert idnorm.canon_id("hep-th/9703043").ok  # 7-digit still fine


# -- PapersRegistry._feed_row: denylist + tracked-source gate -------------------


def test_feed_row_untracked_src_cannot_mint_resolution() -> None:
    reg = idnorm.PapersRegistry()
    # A ledger/vault/manual row carrying tail7+idc is breadth-only —
    # it must NOT write resolutions (else a note event poisons adjudication).
    for src in ("ledger", "vault", "manual"):
        reg._feed_row(  # noqa: SLF001 -- 钉私有喂行面（裁决路径正是被测面）
            {"tail7": "9601002", "idc": "cond-mat/9601002"}, src=src
        )
    assert reg.resolutions.get("9601002") is None
    # …but the idc still lands in known/tails (breadth)
    assert reg.has("cond-mat/9601002")
    assert reg.cats_for_tail("9601002") == {"cond-mat"}
    # A TRACKED source may adjudicate.
    reg._feed_row(  # noqa: SLF001 -- 钉私有喂行面
        {"tail7": "9601002", "idc": "cond-mat/9601002"}, src="manifest"
    )
    assert reg.resolutions["9601002"] == "cond-mat/9601002"


def test_feed_row_status_denylist_drops_everything() -> None:
    reg = idnorm.PapersRegistry()
    for status in ("pending", "ambig", "failed", "unresolved"):
        reg._feed_row(  # noqa: SLF001 -- 钉私有喂行面
            {"idc": "cond-mat/9601002", "status": status}, src="manifest"
        )
    assert not reg.known
    assert not reg.tails


# -- importer: redact surface ----------------------------------------------------


def test_redact_authish_key_name_survives_value_dies() -> None:
    out, n = importer.redact({"auth_token": "8675309-x", "ok": 1})
    assert "auth_token" in out  # key NAME is vocabulary, kept readable
    assert out["auth_token"]["$redact"]
    assert out["ok"] == 1
    assert n == 1


def test_redact_secret_inside_key_renamed() -> None:
    out, n = importer.redact({"node100.64.1.5": "x", "plain": "y"})
    assert n == 1
    key = next(iter(out))
    assert key.startswith("$redact:")
    assert "100.64" not in key
    assert out[key]["$redact"]
    assert out["plain"] == "y"


def test_redact_tailscale_without_word_boundary() -> None:
    # 'node100.64.1.5' — the \b-anchored pattern missed host-prefixed IPs.
    out, n = importer.redact({"jump": "node100.64.1.5"})
    assert n == 1
    assert out["jump"]["$redact"] == hashlib.sha256(b"node100.64.1.5").hexdigest()


def test_redact_new_auth_keys() -> None:
    for k in ("api_secret", "session_token", "bearer_token", "app_key"):
        out, n = importer.redact({k: "s3cr3t"})
        assert n == 1, k
        assert out[k]["$redact"], k


def test_redact_nonjson_scalars() -> None:
    out, n = importer.redact({"blob": b"\x00\x01", "s": {1, 2}, "k": "v"})
    assert out["blob"]["$nonjson"] == "bytes"
    assert out["s"]["$nonjson"] == "set"
    assert out["k"] == "v"
    assert n == 2  # noqa: PLR2004 -- 断言字面量（nonjson 脱敏计数）


# -- importer: status map / canon hint / non-dict rows ----------------------------


def test_status_of_kernel_statuses_fail_loud() -> None:
    for s in ("dedup", "claimed", "lost", "unpaid_gate"):
        status, orig = importer._status_of(  # noqa: SLF001 -- 钉私有状态映射面
            s, default="ok"
        )
        assert status == "fault"
        assert orig == s


def test_norm_db_record_uses_id_canon() -> None:
    rec = importer._norm_db_record(  # noqa: SLF001 -- 钉私有规整面
        {
            "id": "9601002",
            "id_canon": "cond-mat/9601002",
            "stage": "xlat",
            "arm": "real",
            "upstream": "mock",
            "status": "ok",
            "seq": 1,
            "metrics": None,
            "errors": None,
        },
        0.0,
    )
    assert rec["canon_hint"] == "cond-mat/9601002"


@pytest.mark.usefixtures("broot")
def test_import_jsonl_non_dict_rows_quarantine(tmp_path: Path) -> None:
    f = tmp_path / "records.jsonl"
    f.write_text(
        json.dumps(
            {
                "type": "cell",
                "run": "r",
                "seq": 1,
                "id": "2101.12345",
                "idc": "2101.12345",
                "arm": "a",
                "up": "-",
                "variant": "-",
                "stage": "s",
                "status": "ok",
            }
        )
        + "\n"
        + '"just a string"\n'
        + "[1,2,3]\n",
        encoding="utf-8",
    )
    idx = Index()
    stats = importer.import_jsonl_file(f, run="import-nondict", index=idx)
    assert stats["quarantined"] == 2  # noqa: PLR2004 -- 断言字面量（隔离行数）
    assert stats["events"] == 1


@pytest.mark.usefixtures("broot")
def test_import_zhstore_unknown_zone_quarantines(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "cond-mat/9601002",
                "arm": "zh",
                "kinds": ["zh"],
                "zone": "bogus-zone",
                "ts": "2026-01-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    bytes_root = tmp_path / "bytes"
    (bytes_root / "cond-mat--9601002" / "zh").mkdir(parents=True)
    (bytes_root / "cond-mat--9601002" / "zh" / "a.tex").write_text("x")
    idx = Index()
    stats = importer.import_zhstore(manifest, bytes_root, idx)
    # was fail-open to 'primary' — now the row is quarantined instead
    assert stats["quarantined"] >= 1


# -- report: $blob offload-marker resolution --------------------------------------


def test_unblob_rejects_non_sha_marker(tmp_path: Path) -> None:
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    val = {"$blob": "../../../etc/passwd"}
    assert report._unblob(val, blobs) is val  # noqa: SLF001 -- 钉私有解标记面
    ok = {"$blob": "a" * 64}
    # missing file -> marker kept
    assert report._unblob(ok, blobs) is ok  # noqa: SLF001 -- 钉私有解标记面


# -- eval lane: spec -> terminal stamp -> eval_records ----------------------------


def test_stage_eval_flag_and_to_dict() -> None:
    st = Stage("judge", lambda _ctx: "ok", eval=True)
    assert st.eval is True
    assert st.to_dict()["eval"] is True
    st2 = Stage("plain", lambda _ctx: "ok")
    assert st2.eval is False


def _fake_env(spec: Spec) -> dict:
    class _RD:
        run = "r1"
        path = None

    return {"rd": _RD(), "spec": spec}


@pytest.mark.usefixtures("broot")
def test_terminal_ev_stamps_eval() -> None:
    spec = Spec(
        "k",
        stages=[
            Stage("judge", lambda _ctx: "ok", eval=True),
            Stage("plain", lambda _ctx: "ok"),
        ],
    )
    env = _fake_env(spec)
    cell = {
        "id": "x",
        "idc": "2101.12345",
        "arm": "a",
        "up": "-",
        "variant": "-",
        "stage": "judge",
    }
    ev = kernel._terminal_ev(env, cell, "ok", seq=1)  # noqa: SLF001 -- 钉私有终态戳面
    assert ev["eval"] is True
    events.validate(ev)  # 'eval' is whitelisted on cells
    cell2 = {**cell, "stage": "plain"}
    ev2 = kernel._terminal_ev(env, cell2, "ok", seq=2)  # noqa: SLF001 -- 钉私有终态戳面
    assert "eval" not in ev2
    # spec.eval=True marks the whole run
    env3 = _fake_env(Spec("k", eval=True, stages=[Stage("plain", lambda _ctx: "ok")]))
    ev3 = kernel._terminal_ev(env3, cell2, "ok", seq=3)  # noqa: SLF001 -- 钉私有终态戳面
    assert ev3["eval"] is True


@pytest.mark.usefixtures("broot")
def test_eval_event_routes_to_eval_records() -> None:
    idx = Index()
    ev = events.make_event(
        events.T_CELL,
        run="r",
        seq=1,
        id="x",
        idc="2101.12345",
        arm="a",
        up="-",
        variant="-",
        stage="judge",
        status="ok",
    )
    ev["eval"] = 1
    idx.apply_event(ev)
    n_eval = idx.conn.execute("SELECT COUNT(*) FROM eval_records").fetchone()[0]
    n_main = idx.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    assert n_eval == 1  # copy lane: lands in both
    assert n_main == 1


# -- importer: vocab scalar redaction keeps grouping ------------------------------


@pytest.mark.usefixtures("broot")
def test_rec_to_event_redacts_vocab_but_keeps_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEXLATE_REDACT_SUBSTR", "8675309")
    rec = {
        "ts": 1.0,
        "id": "2101.12345",
        "canon_hint": None,
        "arm": "real-8675309abc",
        "up": "mock",
        "variant": "-",
        "stage": "xlat",
        "status": "ok",
        "dur_s": 1.0,
        "default_status": "ok",
        "metrics": {},
        "errors": [],
        "sig": "",
        "code": "",
        "dedup_sig": "s",
        "eval": False,
        "queue_wait_s": None,
    }
    quar: list = []
    stats = {"redacted": 0, "quarantined": 0}
    ev = importer._rec_to_event(  # noqa: SLF001 -- 钉私有行→事件转换面
        rec,
        src="jsonl",
        run_name="r1",
        run_seq=1,
        registry=None,
        quar=quar,
        stats=stats,
    )
    assert ev is not None  # redacted, not quarantined
    assert ev["arm"].startswith("$redact-")
    assert stats["redacted"] >= 1


# -- round-2: report shard gating + mint shard binding ------------------------------


def _cell_ev(
    run: str, seq: int, stage: str = "s", status: str = "ok", **kw: object
) -> dict:
    return events.make_event(
        events.T_CELL,
        run=run,
        seq=seq,
        id=kw.pop("id", "2101.12345"),
        idc=kw.pop("idc", "2101.12345"),
        arm=kw.pop("arm", "a"),
        up=kw.pop("up", "-"),
        variant=kw.pop("variant", "-"),
        stage=stage,
        status=status,
        **kw,
    )


def test_unblob_strict_marker_shape(tmp_path: Path) -> None:
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    sha = "a" * 64
    (blobs / f"{sha}.json").write_text('{"injected": true}')
    # a dict merely CONTAINING "$blob" is payload, not a marker
    payload = {"$blob": sha, "victim": True}
    assert report._unblob(payload, blobs) is payload  # noqa: SLF001 -- 钉私有解标记面
    # the well-formed marker resolves
    marker = {"$blob": sha, "$bytes": 17}
    assert report._unblob(marker, blobs) == {"injected": True}  # noqa: SLF001 -- 钉私有解标记面


def test_iter_shard_events_drops_invalid_lines(tmp_path: Path) -> None:
    rdir = tmp_path / "rd"
    rdir.mkdir()
    good = _cell_ev("r1", 1)
    (rdir / "events.jsonl").write_text(
        events.dumps(good)
        + "\n"
        + '{"type":"cell","status":"ok","arm":"a"}\n'  # missing keys
        + '{"type":"cell","run":"r1","seq":2,"id":"x","idc":"x",'
        '"arm":"a","up":"-","variant":"-","stage":"s",'
        '"status":"bogus-status"}\n'
    )  # bad status
    got = list(
        report._iter_shard_events(rdir, events.T_CELL)  # noqa: SLF001 -- 钉私有分片读面
    )
    assert [e["seq"] for e in got] == [1]


@pytest.mark.usefixtures("broot")
def test_mint_run_seq_refuses_shared_triple() -> None:
    ledger.mint_run_seq("r-one", "soak", "2026-01-01", "s", "h")
    with pytest.raises(events.EventError):
        ledger.mint_run_seq("r-two", "soak", "2026-01-01", "s", "h")


def test_iso_extreme_ts_returns_none() -> None:
    assert report._iso(1e20) is None  # noqa: SLF001 -- 钉私有时间戳面
    assert report._iso(float("inf")) is None  # noqa: SLF001 -- 钉私有时间戳面
    assert report._iso(float("nan")) is None  # noqa: SLF001 -- 钉私有时间戳面
    assert report._iso(0) is not None  # noqa: SLF001 -- 钉私有时间戳面
