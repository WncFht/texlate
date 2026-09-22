"""tests/kernel/test_importer.py — Phase 1 import pipeline contract.

Covers: redact() secret surface (gateway key substring, tailscale IPs,
auth-ish keys — and the false-positive shapes pdf_bytes=2401273 /
seconds=100.6 stay intact), import_benchdb on a tiny synthetic sqlite
fixture (dedupe, canon->quarantine, secrets redaction, started_at run
ordering, conservative paid/free resolution, idempotent re-import,
dry-run), import_jsonl_file, import_zhstore (verified vs tombstone vs
orphan census), and import_all aggregation.

All fixtures are synthetic — the real 457MB bench.db is never touched.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from kernel import events, paths
from kernel.idnorm import PapersRegistry
from kernel.index import Index
from kernel.importer import (
    import_all,
    import_benchdb,
    import_jsonl_file,
    import_zhstore,
    redact,
)


# -- fixture helpers ---------------------------------------------------------


def _mk_benchdb(path: Path) -> Path:
    """Tiny bench.db: 3 runs, records/eval_records/cases/cells rows."""
    db = sqlite3.connect(str(path))
    db.executescript(
        """
        CREATE TABLE runs (
            run_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            source TEXT NOT NULL, kind TEXT NOT NULL,
            path TEXT NOT NULL, created_at TEXT, git_rev TEXT);
        CREATE TABLE records (
            rec_id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
            stage TEXT NOT NULL, id TEXT NOT NULL, id_canon TEXT NOT NULL,
            arm TEXT NOT NULL DEFAULT '', upstream TEXT NOT NULL DEFAULT '',
            code TEXT NOT NULL DEFAULT '', status TEXT, dur_s REAL,
            sig TEXT, queue_wait_s REAL, seq INTEGER NOT NULL,
            metrics TEXT, errors TEXT);
        CREATE TABLE eval_records (
            rec_id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
            seq INTEGER NOT NULL, paper TEXT, status TEXT, score REAL,
            seconds REAL, raw TEXT NOT NULL);
        CREATE TABLE cases (
            rec_id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
            seq INTEGER NOT NULL, corpus TEXT, cond TEXT, engine TEXT,
            verdict TEXT, final_pdf INTEGER, final_errors INTEGER,
            raw TEXT NOT NULL);
        CREATE TABLE cells (
            rec_id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
            seq INTEGER NOT NULL, paper TEXT, raw TEXT NOT NULL);
        """
    )
    # beta sorts BEFORE alpha by created_at despite the larger run_id.
    db.execute(
        "INSERT INTO runs VALUES (1,'alpha-late','live','stagerun',"
        "'/nonexistent/alpha','2026-09-19T01:00:00+00:00',NULL)")
    db.execute(
        "INSERT INTO runs VALUES (2,'beta-early','live','stagerun',"
        "'/nonexistent/beta','2026-09-18T01:00:00+00:00',NULL)")
    db.execute(
        "INSERT INTO runs VALUES (3,'gamma-nodate','live','stagerun',"
        "'/nonexistent/gamma',NULL,NULL)")

    rec = (
        "INSERT INTO records"
        "(run_id,stage,id,id_canon,arm,upstream,code,status,dur_s,sig,"
        " queue_wait_s,seq,metrics,errors)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    rows = [
        # run 1 — plain row, then an exact duplicate (pre-dedupe)
        (1, "compile", "2112.00059", "2112.00059", "zh", "mock", "c1",
         "ok", 1.0, None, None, 1,
         '{"xlat_ts":"2026-09-19T01:00:01+00:00"}', None),
        (1, "compile", "2112.00059", "2112.00059", "zh", "mock", "c1",
         "ok", 1.0, None, None, 1,
         '{"xlat_ts":"2026-09-19T01:00:01+00:00"}', None),
        # run 1 — paid arm, order-sensitive: ok then error -> ok must win
        (1, "xlat", "cond-mat/9601002", "cond-mat/9601002", "real", "mock",
         "c1", "ok", 5.0, None, None, 2, "{}", "[]"),
        (1, "xlat", "cond-mat/9601002", "cond-mat/9601002", "real", "mock",
         "c1", "error", 0.5, None, None, 3, "{}", "[]"),
        # run 1 — free arm, order-sensitive: clean then skip -> skip wins
        (1, "compile", "0707.0006", "0707.0006", "zh", "mock", "c",
         "clean", 1.0, None, None, 6, "{}", "[]"),
        (1, "compile", "0707.0006", "0707.0006", "zh", "mock", "c",
         "skip", 0.1, None, None, 7, "{}", "[]"),
        # run 1 — secret-bearing metrics (key substring + tailscale IP +
        # auth-ish field)
        (1, "xlat", "2101.12345", "2101.12345", "real", "mock", "c1",
         "ok", 9.9, None, None, 4,
         '{"api_key":"240127-supersecret","pdf_bytes":2401273,'
         '"jump":"100.64.1.5","seconds":100.6}', "[]"),
        # run 1 — ambiguous bare tail (registry holds two cats)
        (1, "xlat", "9601002", "9601002", "real", "mock", "c1", "ok",
         1.0, None, None, 5, "{}", "[]"),
        # run 2
        (2, "parse", "0906.1291", "0906.1291", "-", "-", "c", "clean",
         0.2, None, None, 1, "{}", "[]"),
        # run 3
        (3, "compile", "0707.0005", "0707.0005", "zh", "mock", "c",
         "fail", 1.0, None, None, 1, "{}", "[]"),
    ]
    db.executemany(rec, rows)
    db.execute(
        "INSERT INTO eval_records VALUES (1,2,1,'2112.00060','ok',"
        "NULL,1.5,'{\"id\":\"2112.00060\",\"status\":\"ok\",\"seconds\":1.5}')")
    db.execute(
        "INSERT INTO cases VALUES (1,2,1,'2112.00061','fixloop','xelatex',"
        "'clean',1,0,'{\"corpus\":\"2112.00061\",\"verdict\":\"clean\"}')")
    db.execute(
        "INSERT INTO cells VALUES (1,3,1,'2112.00062','{\"id\":\"2112.00062\"}')")
    db.commit()
    db.close()
    return path


def _registry() -> PapersRegistry:
    reg = PapersRegistry()
    # two cats for the 9601002 tail -> bare tail is Ambig, never guessed
    reg.add("astro-ph/9601002")
    reg.add("hep-th/9601002")
    return reg


def _ledger_lines() -> list[str]:
    p = paths.events_path()
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l]


def _ledger_text() -> str:
    return "\n".join(_ledger_lines())


def _cell_payloads(index: Index) -> list[dict]:
    return [
        json.loads(r["payload"])
        for r in index.conn.execute(
            "SELECT payload FROM events WHERE type='cell' ORDER BY line_no")
    ]


# -- redact -------------------------------------------------------------------


def test_redact_surface():
    obj = {
        "api_key": "240127-deadbeef",
        "Authorization": "Bearer whatever",
        "nested": {"token": "tok", "safe": "x"},
        "jump_host": "ssh 100.64.1.5 and 100.200.1.1",
        "pdf_bytes": 2401273,      # contains '240127' substring -> redacted
        "seconds": 100.6,          # float, NOT a tailscale IP -> kept
        "tokens": 12345,           # 'tokens' is not an auth key -> kept
        "file_cache_key": "abc",   # not auth-ish -> kept
        "ok": True,
    }
    out, n = redact(obj)
    assert n == 5  # api_key, Authorization, token, jump_host, pdf_bytes
    assert "$redact" in out["api_key"]
    assert "$redact" in out["Authorization"]
    assert "$redact" in out["nested"]["token"]
    assert "$redact" in out["jump_host"]
    assert "$redact" in out["pdf_bytes"]
    assert out["seconds"] == 100.6
    assert out["tokens"] == 12345
    assert out["file_cache_key"] == "abc"
    assert out["nested"]["safe"] == "x"
    assert out["ok"] is True
    # sha256 of the original string is preserved for verification
    import hashlib
    assert out["jump_host"]["$redact"] == hashlib.sha256(
        b"ssh 100.64.1.5 and 100.200.1.1").hexdigest()
    # original is untouched (copy semantics)
    assert obj["api_key"] == "240127-deadbeef"


def test_redact_list_and_str():
    out, n = redact(["key=240127x", "plain", {"a": "100.64.0.1"}])
    assert n == 2
    assert out[0]["$redact"]
    assert out[1] == "plain"
    assert out[2]["a"]["$redact"]


# -- import_benchdb -----------------------------------------------------------


def test_import_benchdb(broot, tmp_path):
    db_path = _mk_benchdb(tmp_path / "bench.db")
    index = Index()
    stats = import_benchdb(db_path, index, registry=_registry())

    assert stats["rows"] == 13
    assert stats["quarantined"] == 1          # the bare '9601002' row
    assert stats["dup_skipped"] == 1          # the exact duplicate row
    assert stats["order_sensitive"] == 2      # paid + free conflict keys
    assert stats["redacted"] == 3             # api_key, pdf_bytes, jump
    assert stats["emitted"] == stats["applied"] > 0
    assert stats["runs"] == 6                 # 3 rec + eval + cases + cells
    assert stats["runs_minted"] == 6

    # ledger got the events; run_registered minted per import run
    text = _ledger_text()
    assert "240127-supersecret" not in text   # secret never reaches ledger
    assert "100.64.1.5" not in text
    assert "$redact" in text

    # cells projection: conservative resolution
    paid = index.last_cell("cond-mat/9601002", "real", "mock", "-", "xlat")
    assert paid["status"] == "ok"             # paid -> done-ish wins
    free = index.last_cell("0707.0006", "zh", "mock", "-", "compile")
    assert free["status"] == "skip"           # free -> retriable wins
    assert index.last_cell("2112.00059", "zh", "mock", "-",
                           "compile")["status"] == "ok"
    assert index.last_cell("0906.1291", "-", "-", "-",
                           "parse")["status"] == "clean"
    # raw-table rows land under their table-name stage
    assert index.last_cell("2112.00060", "-", "-", "-",
                           "eval_records")["status"] == "ok"
    assert index.last_cell("2112.00061", "-", "-", "-",
                           "cases")["status"] == "ok"
    assert index.last_cell("2112.00062", "-", "-", "-",
                           "cells")["status"] == "ok"

    # ordering: beta (09-18) minted before alpha (09-19)
    seqs = {
        r["run"]: r["run_seq"]
        for r in index.conn.execute("SELECT run,run_seq FROM runs")
    }
    assert seqs["import-eval_records-r2-beta-early"] < \
        seqs["import-records-r1-alpha-late"]
    assert seqs["import-records-r2-beta-early"] < \
        seqs["import-records-r1-alpha-late"]

    # quarantine: the Ambig id row + two order-sensitive reports
    qrows = [
        json.loads(l) for l in
        paths.quarantine_path().read_text(encoding="utf-8").splitlines()
        if l
    ]
    assert any(r.get("type") == "import_quarantine" and
               r.get("id") == "9601002" and
               r.get("canon_state") == "ambig" for r in qrows)
    assert sum(r.get("type") == "import_order_sensitive"
               for r in qrows) == 2

    # redacted metrics inside the applied cell event
    payloads = _cell_payloads(index)
    sec = [p for p in payloads if p["id"] == "2101.12345"][0]
    assert "$redact" in sec["metrics"]["api_key"]
    assert "$redact" in sec["metrics"]["pdf_bytes"]
    assert "$redact" in sec["metrics"]["jump"]
    assert sec["metrics"]["seconds"] == 100.6
    assert "240127-supersecret" not in events.dumps(sec)


def test_import_benchdb_idempotent_and_dry(broot, tmp_path):
    db_path = _mk_benchdb(tmp_path / "bench.db")
    index = Index()
    reg = _registry()
    first = import_benchdb(db_path, index, registry=reg)
    assert first["emitted"] > 0
    n_lines = len(_ledger_lines())
    quar_size = paths.quarantine_path().stat().st_size

    second = import_benchdb(db_path, index, registry=reg)
    assert second["emitted"] == 0
    assert second["applied"] == 0
    assert len(_ledger_lines()) == n_lines
    # quarantine rows deduped too — no double-spam
    assert paths.quarantine_path().stat().st_size == quar_size

    # dry run: counts only, zero writes anywhere
    dry = import_benchdb(db_path, index, registry=reg, dry=True)
    assert dry["rows"] == 13
    assert dry["emitted"] == 0 and dry["applied"] == 0
    assert len(_ledger_lines()) == n_lines


# -- import_jsonl_file ---------------------------------------------------------


def test_import_jsonl_file(broot, tmp_path):
    wdir = tmp_path / "wtrun-2026-09-17"
    wdir.mkdir()
    (wdir / "run_meta.json").write_text(json.dumps(
        {"started_at": "2026-09-17T00:00:00+00:00"}))
    lines = [
        {"id": "2101.00001", "stage": "xlat", "arm": "real",
         "upstream": "-", "status": "ok", "dur_s": 2.0, "metrics": {}},
        {"id": "2101.00001", "stage": "xlat", "arm": "real",
         "upstream": "-", "status": "ok", "dur_s": 2.0, "metrics": {}},
        {"id": "garbage id", "stage": "xlat", "status": "ok"},
        {"corpus": "2101.00002", "cond": "fixloop", "verdict": "clean"},
    ]
    f = wdir / "records.jsonl"
    f.write_text(
        "\n".join(json.dumps(l) for l in lines) + "\nnot json\n")
    index = Index()
    stats = import_jsonl_file(f, run="import-wtrun", index=index,
                              registry=_registry())
    assert stats["rows"] == 5                  # 4 json + 1 bad line
    assert stats["bad_lines"] == 1
    assert stats["dup_skipped"] == 1           # exact dup line
    assert stats["quarantined"] == 2           # bad id + bad line
    assert index.last_cell("2101.00001", "real", "-", "-",
                           "xlat")["status"] == "ok"
    assert index.last_cell("2101.00002", "-", "-", "-",
                           "cases")["status"] == "ok"


# -- import_zhstore ------------------------------------------------------------


def test_import_zhstore(broot, tmp_path):
    zh = tmp_path / "zh-store"
    zh.mkdir()
    # A: declared zh+splice, bytes present -> 2 verified assets
    (zh / "0712.0031" / "zh").mkdir(parents=True)
    (zh / "0712.0031" / "splice").mkdir(parents=True)
    (zh / "0712.0031" / "zh" / "main.pdf").write_bytes(b"%PDF-1")
    (zh / "0712.0031" / "splice" / "m.pdf").write_bytes(b"%PDF-2")
    # B: declared zh, no bytes -> tombstone
    # C: _quarantine zone, splice bytes under _quarantine/ -> verified
    (zh / "_quarantine" / "0712.0033" / "splice").mkdir(parents=True)
    (zh / "_quarantine" / "0712.0033" / "splice" / "s.pdf").write_bytes(
        b"%PDF-3")
    # orphan dir with no manifest row
    (zh / "0909.9999").mkdir()
    (zh / "0909.9999" / "x.pdf").write_bytes(b"%PDF-4")

    rows = [
        {"id": "0712.0031", "arm": "real", "model": "m1",
         "source_run": "run-a", "has_zh": True, "has_splice": True,
         "zone": "primary", "moved_at": "2026-09-20T10:00:00+00:00"},
        {"id": "0712.0032", "arm": "real", "model": "",
         "source_run": "run-b", "has_zh": True, "has_splice": False,
         "zone": "primary", "moved_at": "2026-09-20T10:01:00+00:00"},
        {"id": "0712.0033", "arm": "real", "model": "",
         "source_run": "run-c", "has_zh": False, "has_splice": True,
         "zone": "_quarantine", "moved_at": "2026-09-20T10:02:00+00:00"},
        {"id": "bad id", "arm": "real", "has_zh": True,
         "has_splice": False, "zone": "primary"},
    ]
    manifest = zh / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    index = Index()
    stats = import_zhstore(manifest, zh, index, registry=_registry())
    assert stats["rows"] == 4
    assert stats["quarantined"] == 1            # 'bad id'
    assert stats["orphans"] == 1
    assert stats["orphan_dirs"] == ["0909.9999"]
    assert stats["emitted"] == stats["applied"] == 5  # 3 assets+1 tomb+1 note

    assert ("0712.0031", "real", "-") in index.vault_bytes_ok()
    assert ("0712.0033", "real", "-") in index.vault_bytes_ok()
    assert ("0712.0032", "real", "-") not in index.vault_bytes_ok()
    # tombstone verdict projected into vault_meta
    vm = index.conn.execute(
        "SELECT verdict FROM vault_meta WHERE idc='0712.0032'").fetchone()
    assert vm["verdict"] == "tombstone"
    quar_vm = index.conn.execute(
        "SELECT verdict FROM vault_meta WHERE idc='0712.0033'").fetchone()
    assert quar_vm["verdict"] == "quarantine"

    # re-import is a no-op
    n_lines = len(_ledger_lines())
    again = import_zhstore(manifest, zh, index, registry=_registry())
    assert again["emitted"] == 0 and again["applied"] == 0
    assert len(_ledger_lines()) == n_lines


# -- import_all ----------------------------------------------------------------


def test_import_all(broot, tmp_path):
    db_path = _mk_benchdb(tmp_path / "bench.db")
    zh = tmp_path / "zh-store"
    zh.mkdir()
    (zh / "0712.0031" / "zh").mkdir(parents=True)
    (zh / "0712.0031" / "zh" / "m.pdf").write_bytes(b"%PDF")
    manifest = zh / "manifest.jsonl"
    manifest.write_text(json.dumps(
        {"id": "0712.0031", "arm": "real", "has_zh": True,
         "has_splice": False, "zone": "primary",
         "moved_at": "2026-09-20T10:00:00+00:00"}) + "\n")

    scan = tmp_path / "work"
    (scan / "runx").mkdir(parents=True)
    (scan / "runx" / "records.xlat.jsonl").write_text(json.dumps(
        {"id": "2101.00003", "stage": "xlat", "arm": "real",
         "status": "ok"}) + "\n")
    # stagerun stage ledgers: records/{stage}.jsonl — stage comes from
    # the file stem when the row itself doesn't carry one.
    (scan / "runx" / "records").mkdir()
    (scan / "runx" / "records" / "compile.jsonl").write_text(json.dumps(
        {"id": "2101.00006", "arm": "mock", "status": "ok"}) + "\n")
    # recovered eval/cells ledgers: stage by file family, default ok.
    (scan / "runx" / "eval-records-recovered.jsonl").write_text(
        json.dumps({"id": "2101.00007", "route": {"engines": ["xelatex"]},
                    "status": "ok"}) + "\n")
    (scan / "runx" / "cells-recovered.jsonl").write_text(
        json.dumps({"id": "2101.00008", "band": "b",
                    "route": {"engines": ["xelatex"]},
                    "status": "ok"}) + "\n")

    index = Index()
    total = import_all(
        {"benchdb": db_path,
         "scan_root": scan,
         "zhstore": {"manifest": manifest, "bytes_root": zh}},
        index, registry=_registry())
    assert "benchdb" in total["per_source"]
    assert "zhstore" in total["per_source"]
    assert "jsonl" in total["per_source"]
    assert total["rows"] == 18               # db 13 + zh 1 + scan 4
    assert index.last_cell("2101.00003", "real", "-", "-",
                           "xlat")["status"] == "ok"
    assert index.last_cell("2101.00006", "mock", "-", "-",
                           "compile")["status"] == "ok"
    assert index.last_cell("2101.00007", "-", "-", "-",
                           "eval_records")["status"] == "ok"
    assert index.last_cell("2101.00008", "-", "-", "-",
                           "cells")["status"] == "ok"
    assert ("0712.0031", "real", "-") in index.vault_bytes_ok()


# -- blob offload (>4KB metrics/errors -> derived/blobs) ------------------------


def test_blob_offload(broot, tmp_path):
    big = "x" * 6000
    f = tmp_path / "records.jsonl"
    f.write_text(json.dumps(
        {"id": "2101.00009", "stage": "xlat", "arm": "real",
         "status": "ok", "metrics": {"blob": big}}) + "\n")
    index = Index()
    stats = import_jsonl_file(f, run="import-blob", index=index)
    assert stats["emitted"] == 1
    payloads = _cell_payloads(index)
    assert len(payloads) == 1
    met = payloads[0]["metrics"]
    assert "$blob" in met and met["$bytes"] > 4096
    # blob landed under the run's derived/blobs and round-trips
    blob_dir = paths.runs_dir() / "import"
    found = list(blob_dir.rglob(f"{met['$blob']}.json"))
    assert len(found) == 1
    assert json.loads(found[0].read_text())["blob"] == big
    # re-import sees the offloaded sha in dedupe -> zero new lines
    n_lines = len(_ledger_lines())
    again = import_jsonl_file(f, run="import-blob", index=index)
    assert again["emitted"] == 0
    assert len(_ledger_lines()) == n_lines
