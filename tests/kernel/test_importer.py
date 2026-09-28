"""tests/kernel/test_importer.py — Phase 1 import pipeline contract.

Covers: redact() secret surface (gateway key substring, tailscale IPs,
auth-ish keys — and the false-positive shapes pdf_bytes=86753093 /
seconds=100.6 stay intact), import_benchdb on a tiny synthetic sqlite
fixture (dedupe, canon->quarantine, secrets redaction, started_at run
ordering, conservative paid/free resolution, idempotent re-import,
dry-run), import_jsonl_file, import_zhstore (verified vs tombstone vs
orphan census), and import_all aggregation.

All fixtures are synthetic — the real 457MB bench.db is never touched.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from kernel import cas, events, lake, paths, vault
from kernel.idnorm import PapersRegistry
from kernel.importer import (
    absorb_corpus,
    import_all,
    import_benchdb,
    import_jsonl_file,
    import_zhstore,
    redact,
    register_lake_manifests,
    seed_vault_zhstore,
)
from kernel.index import Index

if TYPE_CHECKING:
    from pathlib import Path

# 每个测试都要隔离 BENCH_ROOT——broot 只要副作用，全模块钉版不再逐个形参声明
pytestmark = pytest.mark.usefixtures("broot")

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
        "'/nonexistent/alpha','2026-09-19T01:00:00+00:00',NULL)"
    )
    db.execute(
        "INSERT INTO runs VALUES (2,'beta-early','live','stagerun',"
        "'/nonexistent/beta','2026-09-18T01:00:00+00:00',NULL)"
    )
    db.execute(
        "INSERT INTO runs VALUES (3,'gamma-nodate','live','stagerun',"
        "'/nonexistent/gamma',NULL,NULL)"
    )

    rec = (
        "INSERT INTO records"
        "(run_id,stage,id,id_canon,arm,upstream,code,status,dur_s,sig,"
        " queue_wait_s,seq,metrics,errors)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    rows = [
        # run 1 — plain row, then an exact duplicate (pre-dedupe)
        (
            1,
            "compile",
            "2112.00059",
            "2112.00059",
            "zh",
            "mock",
            "c1",
            "ok",
            1.0,
            None,
            None,
            1,
            '{"xlat_ts":"2026-09-19T01:00:01+00:00"}',
            None,
        ),
        (
            1,
            "compile",
            "2112.00059",
            "2112.00059",
            "zh",
            "mock",
            "c1",
            "ok",
            1.0,
            None,
            None,
            1,
            '{"xlat_ts":"2026-09-19T01:00:01+00:00"}',
            None,
        ),
        # run 1 — paid arm, order-sensitive: ok then error -> ok must win
        (
            1,
            "xlat",
            "cond-mat/9601002",
            "cond-mat/9601002",
            "real",
            "mock",
            "c1",
            "ok",
            5.0,
            None,
            None,
            2,
            "{}",
            "[]",
        ),
        (
            1,
            "xlat",
            "cond-mat/9601002",
            "cond-mat/9601002",
            "real",
            "mock",
            "c1",
            "error",
            0.5,
            None,
            None,
            3,
            "{}",
            "[]",
        ),
        # run 1 — free arm, order-sensitive: clean then skip -> skip wins
        (
            1,
            "compile",
            "0707.0006",
            "0707.0006",
            "zh",
            "mock",
            "c",
            "clean",
            1.0,
            None,
            None,
            6,
            "{}",
            "[]",
        ),
        (
            1,
            "compile",
            "0707.0006",
            "0707.0006",
            "zh",
            "mock",
            "c",
            "skip",
            0.1,
            None,
            None,
            7,
            "{}",
            "[]",
        ),
        # run 1 — secret-bearing metrics (key substring + tailscale IP +
        # auth-ish field)
        (
            1,
            "xlat",
            "2101.12345",
            "2101.12345",
            "real",
            "mock",
            "c1",
            "ok",
            9.9,
            None,
            None,
            4,
            (
                '{"api_key":"8675309-supersecret","pdf_bytes":86753093,'
                '"jump":"100.64.1.5","seconds":100.6}'
            ),
            "[]",
        ),
        # run 1 — ambiguous bare tail (registry holds two cats)
        (
            1,
            "xlat",
            "9601002",
            "9601002",
            "real",
            "mock",
            "c1",
            "ok",
            1.0,
            None,
            None,
            5,
            "{}",
            "[]",
        ),
        # run 2
        (
            2,
            "parse",
            "0906.1291",
            "0906.1291",
            "-",
            "-",
            "c",
            "clean",
            0.2,
            None,
            None,
            1,
            "{}",
            "[]",
        ),
        # run 3
        (
            3,
            "compile",
            "0707.0005",
            "0707.0005",
            "zh",
            "mock",
            "c",
            "fail",
            1.0,
            None,
            None,
            1,
            "{}",
            "[]",
        ),
    ]
    db.executemany(rec, rows)
    db.execute(
        "INSERT INTO eval_records VALUES (1,2,1,'2112.00060','ok',"
        'NULL,1.5,\'{"id":"2112.00060","status":"ok","seconds":1.5}\')'
    )
    db.execute(
        "INSERT INTO cases VALUES (1,2,1,'2112.00061','fixloop','xelatex',"
        '\'clean\',1,0,\'{"corpus":"2112.00061","verdict":"clean"}\')'
    )
    db.execute(
        "INSERT INTO cells VALUES (1,3,1,'2112.00062','{\"id\":\"2112.00062\"}')"
    )
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
    return [line for line in p.read_text(encoding="utf-8").splitlines() if line]


def _ledger_text() -> str:
    return "\n".join(_ledger_lines())


def _cell_payloads(index: Index) -> list[dict]:
    return [
        json.loads(r["payload"])
        for r in index.conn.execute(
            "SELECT payload FROM events WHERE type='cell' ORDER BY line_no"
        )
    ]


# -- redact -------------------------------------------------------------------


def test_redact_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_REDACT_SUBSTR", "8675309")
    obj = {
        "api_key": "8675309-deadbeef",
        "Authorization": "Bearer whatever",
        "nested": {"token": "tok", "safe": "x"},
        "jump_host": "ssh 100.64.1.5 and 100.200.1.1",
        "pdf_bytes": 86753093,  # contains '8675309' substring -> redacted
        "seconds": 100.6,  # float, NOT a tailscale IP -> kept
        "tokens": 12345,  # 'tokens' is not an auth key -> kept
        "file_cache_key": "abc",  # not auth-ish -> kept
        "ok": True,
    }
    out, n = redact(obj)
    # 下行断言字面量：api_key/Authorization/token/jump_host/pdf_bytes 五件
    assert n == 5  # noqa: PLR2004
    assert "$redact" in out["api_key"]
    assert "$redact" in out["Authorization"]
    assert "$redact" in out["nested"]["token"]
    assert "$redact" in out["jump_host"]
    assert "$redact" in out["pdf_bytes"]
    assert out["seconds"] == 100.6  # noqa: PLR2004 -- 断言字面量：fixture 原值核对
    assert out["tokens"] == 12345  # noqa: PLR2004 -- 断言字面量：fixture 原值核对
    assert out["file_cache_key"] == "abc"
    assert out["nested"]["safe"] == "x"
    assert out["ok"] is True
    # sha256 of the original string is preserved for verification
    assert (
        out["jump_host"]["$redact"]
        == hashlib.sha256(b"ssh 100.64.1.5 and 100.200.1.1").hexdigest()
    )
    # original is untouched (copy semantics)
    assert obj["api_key"] == "8675309-deadbeef"


def test_redact_list_and_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_REDACT_SUBSTR", "8675309")
    out, n = redact(["key=8675309x", "plain", {"a": "100.64.0.1"}])
    assert n == 2  # noqa: PLR2004 -- 断言字面量：脱敏计数
    assert out[0]["$redact"]
    assert out[1] == "plain"
    assert out[2]["a"]["$redact"]


# -- import_benchdb -----------------------------------------------------------


def test_import_benchdb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_REDACT_SUBSTR", "8675309")
    db_path = _mk_benchdb(tmp_path / "bench.db")
    index = Index()
    stats = import_benchdb(db_path, index, registry=_registry())

    assert stats["rows"] == 13  # noqa: PLR2004 -- 断言字面量：fixture 总行数
    assert stats["quarantined"] == 1  # the bare '9601002' row
    assert stats["dup_skipped"] == 1  # the exact duplicate row
    assert stats["order_sensitive"] == 2  # noqa: PLR2004 -- 断言字面量：paid + free 冲突键
    assert stats["redacted"] == 3  # noqa: PLR2004 -- 断言字面量：api_key/pdf_bytes/jump
    assert stats["emitted"] == stats["applied"] > 0
    assert stats["runs"] == 6  # noqa: PLR2004 -- 断言字面量：3 rec + eval + cases + cells
    assert stats["runs_minted"] == 6  # noqa: PLR2004 -- 断言字面量

    # ledger got the events; run_registered minted per import run
    text = _ledger_text()
    assert "8675309-supersecret" not in text  # secret never reaches ledger
    assert "100.64.1.5" not in text
    assert "$redact" in text

    # cells projection: conservative resolution
    paid = index.last_cell("cond-mat/9601002", "real", "mock", "-", "xlat")
    assert paid["status"] == "ok"  # paid -> done-ish wins
    free = index.last_cell("0707.0006", "zh", "mock", "-", "compile")
    assert free["status"] == "skip"  # free -> retriable wins
    assert index.last_cell("2112.00059", "zh", "mock", "-", "compile")["status"] == "ok"
    assert index.last_cell("0906.1291", "-", "-", "-", "parse")["status"] == "clean"
    # raw-table rows land under their table-name stage
    assert (
        index.last_cell("2112.00060", "-", "-", "-", "eval_records")["status"] == "ok"
    )
    assert index.last_cell("2112.00061", "-", "-", "-", "cases")["status"] == "ok"
    assert index.last_cell("2112.00062", "-", "-", "-", "cells")["status"] == "ok"

    # ordering: beta (09-18) minted before alpha (09-19)
    seqs = {
        r["run"]: r["run_seq"]
        for r in index.conn.execute("SELECT run,run_seq FROM runs")
    }
    assert (
        seqs["import-eval_records-r2-beta-early"] < seqs["import-records-r1-alpha-late"]
    )
    assert seqs["import-records-r2-beta-early"] < seqs["import-records-r1-alpha-late"]

    # quarantine: the Ambig id row + two order-sensitive reports
    qrows = [
        json.loads(line)
        for line in paths.quarantine_path().read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(
        r.get("type") == "import_quarantine"
        and r.get("id") == "9601002"
        and r.get("canon_state") == "ambig"
        for r in qrows
    )
    assert sum(r.get("type") == "import_order_sensitive" for r in qrows) == 2  # noqa: PLR2004 -- 断言字面量

    # redacted metrics inside the applied cell event
    payloads = _cell_payloads(index)
    sec = next(p for p in payloads if p["id"] == "2101.12345")
    assert "$redact" in sec["metrics"]["api_key"]
    assert "$redact" in sec["metrics"]["pdf_bytes"]
    assert "$redact" in sec["metrics"]["jump"]
    assert sec["metrics"]["seconds"] == 100.6  # noqa: PLR2004 -- 断言字面量：fixture 原值核对
    assert "8675309-supersecret" not in events.dumps(sec)


def test_import_benchdb_idempotent_and_dry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_REDACT_SUBSTR", "8675309")
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
    assert dry["rows"] == 13  # noqa: PLR2004 -- 断言字面量：fixture 总行数
    assert dry["emitted"] == 0
    assert dry["applied"] == 0
    assert len(_ledger_lines()) == n_lines


# -- import_jsonl_file ---------------------------------------------------------


def test_import_jsonl_file(tmp_path: Path) -> None:
    wdir = tmp_path / "wtrun-2026-09-17"
    wdir.mkdir()
    (wdir / "run_meta.json").write_text(
        json.dumps({"started_at": "2026-09-17T00:00:00+00:00"})
    )
    lines = [
        {
            "id": "2101.00001",
            "stage": "xlat",
            "arm": "real",
            "upstream": "-",
            "status": "ok",
            "dur_s": 2.0,
            "metrics": {},
        },
        {
            "id": "2101.00001",
            "stage": "xlat",
            "arm": "real",
            "upstream": "-",
            "status": "ok",
            "dur_s": 2.0,
            "metrics": {},
        },
        {"id": "garbage id", "stage": "xlat", "status": "ok"},
        {"corpus": "2101.00002", "cond": "fixloop", "verdict": "clean"},
    ]
    f = wdir / "records.jsonl"
    f.write_text("\n".join(json.dumps(line) for line in lines) + "\nnot json\n")
    index = Index()
    stats = import_jsonl_file(f, run="import-wtrun", index=index, registry=_registry())
    assert stats["rows"] == 5  # noqa: PLR2004 -- 断言字面量：4 json + 1 bad line
    assert stats["bad_lines"] == 1
    assert stats["dup_skipped"] == 1  # exact dup line
    assert stats["quarantined"] == 2  # noqa: PLR2004 -- 断言字面量：bad id + bad line
    assert index.last_cell("2101.00001", "real", "-", "-", "xlat")["status"] == "ok"
    assert index.last_cell("2101.00002", "-", "-", "-", "cases")["status"] == "ok"


# -- import_zhstore ------------------------------------------------------------


def test_import_zhstore(tmp_path: Path) -> None:
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
    (zh / "_quarantine" / "0712.0033" / "splice" / "s.pdf").write_bytes(b"%PDF-3")
    # orphan dir with no manifest row
    (zh / "0909.9999").mkdir()
    (zh / "0909.9999" / "x.pdf").write_bytes(b"%PDF-4")

    rows = [
        {
            "id": "0712.0031",
            "arm": "real",
            "model": "m1",
            "source_run": "run-a",
            "has_zh": True,
            "has_splice": True,
            "zone": "primary",
            "moved_at": "2026-09-20T10:00:00+00:00",
        },
        {
            "id": "0712.0032",
            "arm": "real",
            "model": "",
            "source_run": "run-b",
            "has_zh": True,
            "has_splice": False,
            "zone": "primary",
            "moved_at": "2026-09-20T10:01:00+00:00",
        },
        {
            "id": "0712.0033",
            "arm": "real",
            "model": "",
            "source_run": "run-c",
            "has_zh": False,
            "has_splice": True,
            "zone": "_quarantine",
            "moved_at": "2026-09-20T10:02:00+00:00",
        },
        {
            "id": "bad id",
            "arm": "real",
            "has_zh": True,
            "has_splice": False,
            "zone": "primary",
        },
    ]
    manifest = zh / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    index = Index()
    stats = import_zhstore(manifest, zh, index, registry=_registry())
    assert stats["rows"] == 4  # noqa: PLR2004 -- 断言字面量：manifest 行数
    assert stats["quarantined"] == 1  # 'bad id'
    assert stats["orphans"] == 1
    assert stats["orphan_dirs"] == ["0909.9999"]
    assert stats["emitted"] == stats["applied"] == 5  # noqa: PLR2004 -- 断言字面量：3 assets+1 tomb+1 note

    assert ("0712.0031", "real", "-") in index.vault_bytes_ok()
    assert ("0712.0033", "real", "-") in index.vault_bytes_ok()
    assert ("0712.0032", "real", "-") not in index.vault_bytes_ok()
    # tombstone verdict projected into vault_meta
    vm = index.conn.execute(
        "SELECT verdict FROM vault_meta WHERE idc='0712.0032'"
    ).fetchone()
    assert vm["verdict"] == "tombstone"
    quar_vm = index.conn.execute(
        "SELECT verdict FROM vault_meta WHERE idc='0712.0033'"
    ).fetchone()
    assert quar_vm["verdict"] == "quarantine"

    # re-import is a no-op
    n_lines = len(_ledger_lines())
    again = import_zhstore(manifest, zh, index, registry=_registry())
    assert again["emitted"] == 0
    assert again["applied"] == 0
    assert len(_ledger_lines()) == n_lines


# -- seed_vault_zhstore (Phase 2 census) ---------------------------------------


def _mk_zhstore(tmp_path: Path) -> tuple[Path, Path]:
    """Synthetic zh-store: 2 primary rows with bytes, 1 quar row whose
    bytes sit under _quarantine/, 1 primary-row-whose-bytes-are-in-quar,
    1 byte-less row, 1 canon-fail row with bytes, 1 unclaimed orphan dir,
    1 noncanon orphan dir."""
    zh = tmp_path / "zh-store"
    zh.mkdir()

    def put(rel: str, payload: bytes = b"%PDF") -> None:
        p = zh / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload)

    put("0712.0031/zh/main.pdf", b"%PDF-zh")
    put("0712.0031/splice/m.pdf", b"%PDF-sp")
    (zh / "0712.0031" / "provenance.json").write_text(
        json.dumps(
            {"arm": "real", "source_run": "run-a", "api_key": "sk-8675309-secret"}
        )
    )
    put("_quarantine/0712.0033/splice/s.pdf", b"%PDF-q")
    put("_quarantine/0712.0034/zh/m.pdf", b"%PDF-pq")
    put("bad id/zh/m.pdf", b"%PDF-bad")
    put("0909.9999/zh/m.pdf", b"%PDF-orphan")
    put("0712.0099.bak-mock/zh/m.pdf", b"%PDF-mock")

    rows = [
        {
            "id": "0712.0031",
            "arm": "real",
            "model": "m1",
            "source_run": "run-a",
            "has_zh": True,
            "has_splice": True,
            "zone": "primary",
            "moved_at": "2026-09-20T10:00:00+00:00",
        },
        {
            "id": "0712.0032",
            "arm": "real",
            "model": "",
            "source_run": "run-b",
            "has_zh": True,
            "has_splice": False,
            "zone": "primary",
        },
        {
            "id": "0712.0033",
            "arm": "real",
            "model": "",
            "source_run": "run-c",
            "has_zh": False,
            "has_splice": True,
            "zone": "_quarantine",
        },
        {
            "id": "0712.0034",
            "arm": "real",
            "model": "",
            "source_run": "run-d",
            "has_zh": True,
            "has_splice": False,
            "zone": "primary",
        },
        {
            "id": "bad id",
            "arm": "real",
            "has_zh": True,
            "has_splice": False,
            "zone": "primary",
        },
    ]
    manifest = zh / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return zh, manifest


def test_seed_vault_zhstore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_REDACT_SUBSTR", "8675309")
    zh, manifest = _mk_zhstore(tmp_path)
    index = Index()
    stats = seed_vault_zhstore(manifest, zh, index, registry=_registry())

    assert stats["rows"] == 5  # noqa: PLR2004 -- 断言字面量：manifest 行数
    # harvested: 0712.0031 (zh+splice), 0712.0033 quar, 0712.0034
    # quar-by-location, orphan 0909.9999 -> 4 copies / 5 kinds
    assert stats["harvested"] == 4  # noqa: PLR2004 -- 断言字面量：收割拷贝数
    assert stats["kinds_harvested"] == 5  # noqa: PLR2004 -- 断言字面量：收割 kind 数
    assert stats["still_missing"] == 1  # 0712.0032
    assert sorted(stats["orphan_dirs"]) == ["0712.0099.bak-mock", "0909.9999"]
    assert stats["noncanon_dirs"] == ["0712.0099.bak-mock", "bad id"] or sorted(
        stats["noncanon_dirs"]
    ) == ["0712.0099.bak-mock", "bad id"]
    assert stats["bytes"] > 0
    assert not stats["conflicts"]

    # primary copy: verdict verified, provenance merged + redacted
    rows = vault.query("0712.0031", "real", "-")
    assert len(rows) == 1
    assert rows[0]["bytes_ok"]
    assert rows[0]["zone"] == "primary"
    assert rows[0]["verdict"] == "verified"
    assert set(rows[0]["files"]) == {"zh", "splice"}
    prov = rows[0]["provenance"]
    assert prov["arm"] == "real"
    assert prov["api_key"] != "sk-8675309-secret"  # redacted on the way in
    # migration marker: doctor's paid reconciliation exempts seeded bytes
    assert rows[0]["import_src"] == "import-zhstore-vault-seed"

    # quar-by-container beats the manifest's claimed primary zone
    q34 = vault.query("0712.0034", "real", "-")
    assert len(q34) == 1
    assert q34[0]["zone"] == "quar"
    q33 = vault.query("0712.0033", "real", "-")
    assert len(q33) == 1
    assert q33[0]["zone"] == "quar"

    # orphan adopted into quar with adopted_from marker
    orph = vault.query("0909.9999", "-", "-")
    assert len(orph) == 1
    assert orph[0]["zone"] == "quar"
    assert orph[0]["verdict"] == "quar"
    assert orph[0]["adopted_from"].endswith("0909.9999")

    # noncanon bytes stayed out of the vault entirely (the query layer
    # itself canon-gates, so absence is proven via the index projection)
    assert (
        index.conn.execute(
            "SELECT COUNT(*) c FROM vault_meta WHERE idc LIKE '%bak-mock%' "
            "OR idc LIKE '%bad%'"
        ).fetchone()["c"]
        == 0
    )

    # physical payload is in the vault tree, fused read-only
    leaf = paths.vault_dir() / "zh" / "0712.0031" / "real" / "main.pdf"
    assert leaf.is_file()
    assert leaf.read_bytes() == b"%PDF-zh"
    assert not (leaf.stat().st_mode & 0o222)

    # dedup oracle now covers the seeded cells
    assert vault.dedup_hit("0712.0031", "real", "-")
    assert vault.dedup_hit("0712.0033", "real", "-")
    assert vault.dedup_hit("0909.9999", "-", "-")
    assert not vault.dedup_hit("0712.0032", "real", "-")

    rep = vault.verify("full")
    assert rep["bad"] == []
    assert rep["meta_bad"] == []
    assert rep["meta_missing"] == []

    # idempotent: a second census harvests nothing new — no events, no note
    _assert_seed_quiet_rerun(manifest, zh, index)


def _assert_seed_quiet_rerun(manifest: Path, zh: Path, index: Index) -> None:
    n_lines = len(_ledger_lines())
    again = seed_vault_zhstore(manifest, zh, index, registry=_registry())
    assert again["harvested"] == 0
    assert again["already"] == 4  # noqa: PLR2004 -- 断言字面量：已收割数
    assert len(_ledger_lines()) == n_lines


def test_seed_vault_zhstore_dry(tmp_path: Path) -> None:
    zh, manifest = _mk_zhstore(tmp_path)
    index = Index()
    stats = seed_vault_zhstore(manifest, zh, index, registry=_registry(), dry=True)
    assert stats["harvested"] == 4  # noqa: PLR2004 -- 断言字面量：收割拷贝数
    for kind in ("zh", "splice", "state", "quar"):
        d = paths.vault_dir() / kind
        assert not d.exists() or not list(d.rglob("*"))


# -- import_all ----------------------------------------------------------------


def test_import_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_REDACT_SUBSTR", "8675309")
    db_path = _mk_benchdb(tmp_path / "bench.db")
    zh = tmp_path / "zh-store"
    zh.mkdir()
    (zh / "0712.0031" / "zh").mkdir(parents=True)
    (zh / "0712.0031" / "zh" / "m.pdf").write_bytes(b"%PDF")
    manifest = zh / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "0712.0031",
                "arm": "real",
                "has_zh": True,
                "has_splice": False,
                "zone": "primary",
                "moved_at": "2026-09-20T10:00:00+00:00",
            }
        )
        + "\n"
    )

    scan = tmp_path / "work"
    (scan / "runx").mkdir(parents=True)
    (scan / "runx" / "records.xlat.jsonl").write_text(
        json.dumps({"id": "2101.00003", "stage": "xlat", "arm": "real", "status": "ok"})
        + "\n"
    )
    # stagerun stage ledgers: records/{stage}.jsonl — stage comes from
    # the file stem when the row itself doesn't carry one.
    (scan / "runx" / "records").mkdir()
    (scan / "runx" / "records" / "compile.jsonl").write_text(
        json.dumps({"id": "2101.00006", "arm": "mock", "status": "ok"}) + "\n"
    )
    # recovered eval/cells ledgers: stage by file family, default ok.
    (scan / "runx" / "eval-records-recovered.jsonl").write_text(
        json.dumps(
            {"id": "2101.00007", "route": {"engines": ["xelatex"]}, "status": "ok"}
        )
        + "\n"
    )
    (scan / "runx" / "cells-recovered.jsonl").write_text(
        json.dumps(
            {
                "id": "2101.00008",
                "band": "b",
                "route": {"engines": ["xelatex"]},
                "status": "ok",
            }
        )
        + "\n"
    )

    index = Index()
    total = import_all(
        {
            "benchdb": db_path,
            "scan_root": scan,
            "zhstore": {"manifest": manifest, "bytes_root": zh},
        },
        index,
        registry=_registry(),
    )
    assert "benchdb" in total["per_source"]
    assert "zhstore" in total["per_source"]
    assert "jsonl" in total["per_source"]
    assert total["rows"] == 18  # noqa: PLR2004 -- 断言字面量：db 13 + zh 1 + scan 4
    assert index.last_cell("2101.00003", "real", "-", "-", "xlat")["status"] == "ok"
    assert index.last_cell("2101.00006", "mock", "-", "-", "compile")["status"] == "ok"
    assert (
        index.last_cell("2101.00007", "-", "-", "-", "eval_records")["status"] == "ok"
    )
    assert index.last_cell("2101.00008", "-", "-", "-", "cells")["status"] == "ok"
    assert ("0712.0031", "real", "-") in index.vault_bytes_ok()


# -- blob offload (>4KB metrics/errors -> derived/blobs) ------------------------


def test_blob_offload(tmp_path: Path) -> None:
    big = "x" * 6000
    f = tmp_path / "records.jsonl"
    f.write_text(
        json.dumps(
            {
                "id": "2101.00009",
                "stage": "xlat",
                "arm": "real",
                "status": "ok",
                "metrics": {"blob": big},
            }
        )
        + "\n"
    )
    index = Index()
    stats = import_jsonl_file(f, run="import-blob", index=index)
    assert stats["emitted"] == 1
    payloads = _cell_payloads(index)
    assert len(payloads) == 1
    met = payloads[0]["metrics"]
    assert "$blob" in met
    assert met["$bytes"] > 4096  # noqa: PLR2004 -- 断言字面量：>4KB offload 阈
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


# -- lake register + absorb (Phase 3) ------------------------------------------


def _mk_manifests(tmp_path: Path) -> Path:
    """Two manifest files exercising: plain skeleton, failed seeds (bad
    status, stub format), mixed history (bad+ok -> skeleton), layer/channel
    union across files, canon-fail quarantine."""
    d = tmp_path / "manifests"
    d.mkdir()
    (d / "manifest_a.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {
                    "id": "0707.0978",
                    "layer": "v1",
                    "channel": "ia",
                    "format": "tar",
                    "n_files": 11,
                },
                {
                    "id": "astro-ph/0605048",
                    "layer": "booster",
                    "channel": "ia",
                    "format": "stub",
                    "status": None,
                },
                {
                    "id": "0806.1413",
                    "layer": "v1",
                    "channel": "ia",
                    "format": "gz",
                    "status": "fetch_error:406",
                },
                {
                    "id": "1003.1513",
                    "layer": "v1",
                    "channel": "ia",
                    "format": "tar",
                    "status": "fetch_error:406",
                },
                {"id": "bad id", "layer": "v1"},
            ]
        )
        + "\n"
    )
    (d / "manifest_b.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {
                    "id": "0707.0978",
                    "layer": "hot",
                    "channel": "arxiv_eprint",
                    "format": "tar",
                },
                {
                    "id": "1003.1513",
                    "layer": "v2",
                    "channel": "ia",
                    "format": "tar",
                    "status": "ok",
                },
            ]
        )
        + "\n"
    )
    return d


def test_register_lake_manifests(tmp_path: Path) -> None:
    mdir = _mk_manifests(tmp_path)
    index = Index()
    stats = register_lake_manifests([mdir], index, registry=_registry())

    assert stats["rows"] == 7  # noqa: PLR2004 -- 断言字面量：两 manifest 行数和
    assert stats["quarantined"] == 1  # 'bad id'
    assert stats["seeded_skeleton"] == 2  # noqa: PLR2004 -- 断言字面量：0707.0978/1003.1513
    assert stats["seeded_failed"] == 2  # noqa: PLR2004 -- 断言字面量：astro-ph stub/0806 406

    cat = lake.LakeCatalog.load()
    assert cat.state("0707.0978") == "skeleton"
    row = cat.rows()["0707.0978"]
    assert row["manifested"] is True
    assert sorted(row["layers"]) == ["hot", "v1"]  # union across files
    assert sorted(row["channels"]) == ["arxiv_eprint", "ia"]
    assert cat.state("astro-ph/0605048") == "failed"
    assert cat.rows()["astro-ph/0605048"]["regen_cost"] == "network"
    # mixed history (one bad row + one ok row) -> skeleton, not failed
    assert cat.state("1003.1513") == "skeleton"

    # skeleton dirs anchored, failed seeds are catalog-only
    assert lake.cell_dir("0707.0978").is_dir()
    assert not lake.cell_dir("astro-ph/0605048").exists()

    # idempotent: a re-run appends nothing
    n_lines = len(_ledger_lines())
    n_cat = len(paths.lake_catalog_path().read_text().splitlines())
    again = register_lake_manifests([mdir], index, registry=_registry())
    assert again["seeded_skeleton"] == 0
    assert again["seeded_failed"] == 0
    assert again["skipped_present"] == 4  # noqa: PLR2004 -- 断言字面量：已在册数
    assert len(_ledger_lines()) == n_lines
    assert len(paths.lake_catalog_path().read_text().splitlines()) == n_cat


def test_register_lake_manifests_never_downgrades(tmp_path: Path) -> None:
    mdir = _mk_manifests(tmp_path)
    index = Index()
    # pre-hydrate 0707.0978, then register — hydrated must survive
    lake.register_skeleton("0707.0978")
    lake.LakeCatalog.load().set("0707.0978", "hydrated", n_files=3)
    stats = register_lake_manifests([mdir], index, registry=_registry())
    cat = lake.LakeCatalog.load()
    assert cat.state("0707.0978") == "hydrated"
    # but its new memberships still merged in
    assert sorted(cat.rows()["0707.0978"]["layers"]) == ["hot", "v1"]
    assert stats["meta_merged"] == 1


def _mk_legacy_cell(
    root: Path,
    name: str,
    *,
    raw: bool = True,
    extracted: int = 2,
    meta: dict | None = None,
) -> Path:
    d = root / name
    (d / "extracted" / "sub").mkdir(parents=True)
    if raw:
        (d / "raw.tar.gz").write_bytes(b"%RAW-" + name.encode())
    for i in range(extracted):
        (d / "extracted" / f"f{i}.tex").write_bytes(b"tex-%d" % i)
    (d / "extracted" / "sub" / "s.sty").write_bytes(b"sty")
    (d / "meta.json").write_text(
        json.dumps(
            meta
            or {
                "arxiv_id": name,
                "format": "tar",
                "n_files": extracted + 1,
                "raw_file": "raw.tar.gz",
            }
        )
    )
    (d / "files.txt").write_text("f0.tex\n")
    return d


def _mk_corpus(tmp_path: Path) -> Path:
    """Legacy corpus tree: 2 full cells (new-style + safe-form spellings),
    a raw-only cell, a noncanon junk dir and a canon-but-payload-less dir."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _mk_legacy_cell(corpus, "0707.0978")  # new-style spelling
    _mk_legacy_cell(corpus, "astro-ph--0605048")  # safe-form spelling
    rawonly = corpus / "1003.1513"
    rawonly.mkdir()
    (rawonly / "raw.gz").write_bytes(b"%RAWGZ")
    (rawonly / "meta.json").write_text("{}")
    (corpus / "nominations").mkdir()  # noncanon junk dir
    (corpus / "empty-cell").mkdir()  # canon? no payload
    return corpus


def test_absorb_corpus(tmp_path: Path) -> None:
    corpus = _mk_corpus(tmp_path)
    mdir = _mk_manifests(tmp_path)

    index = Index()
    stats = absorb_corpus(corpus, index, registry=_registry(), manifests=[mdir])
    assert stats["absorbed"] == 3  # noqa: PLR2004 -- 断言字面量：吸收 cell 数
    assert stats["raw_only"] == 1
    assert "nominations" in stats["noncanon_dirs"]
    # 'empty-cell' canon-fails too (bare name is not an arxiv id) — it
    # lands in noncanon before the payload check
    assert "empty-cell" in stats["noncanon_dirs"]

    # cells are complete + read-only projections of CAS objects
    assert lake.is_complete("0707.0978")
    assert lake.is_complete("astro-ph/0605048")
    dest = lake.cell_dir("0707.0978")
    meta = json.loads((dest / "meta.json").read_text())
    assert meta["absorb"] is True
    assert meta["idc"] == "0707.0978"
    assert meta["n_files"] == 3  # noqa: PLR2004 -- 断言字面量：2 tex + 1 sty
    leaf = dest / "extracted" / "f0.tex"
    assert leaf.read_bytes() == b"tex-0"
    assert leaf.stat().st_mode & 0o222 == 0  # 0444 projection
    raw_leaf = dest / "raw" / "raw.tar.gz"
    assert raw_leaf.read_bytes() == b"%RAW-0707.0978"
    # CAS holds the bytes; the projection hardlinks the same inode
    sha = meta["raw_sha256"]
    assert cas.object_path(sha, "blob").stat().st_ino == raw_leaf.stat().st_ino
    # bookkeeping carried across
    assert (dest / "files.txt").is_file()

    cat = lake.LakeCatalog.load()
    assert cat.state("0707.0978") == "hydrated"
    assert cat.state("1003.1513") == "raw_only"
    assert cat.rows()["0707.0978"]["manifested"] is True
    # 1003.1513 is in the manifests -> manifested even though raw_only
    assert cat.rows()["1003.1513"]["manifested"] is True
    # source tree untouched + still writable
    assert (corpus / "0707.0978" / "raw.tar.gz").exists()
    assert (corpus / "0707.0978" / "extracted" / "f0.tex").stat().st_mode & 0o222

    # idempotent re-run: zero absorbs, zero new catalog rows
    n_cat = len(paths.lake_catalog_path().read_text().splitlines())
    again = absorb_corpus(corpus, index, registry=_registry(), manifests=[mdir])
    assert again["absorbed"] == 0
    assert again["already"] == 3  # noqa: PLR2004 -- 断言字面量：已吸收数
    assert len(paths.lake_catalog_path().read_text().splitlines()) == n_cat

    # crash-heal: wipe the catalog row, re-run re-seeds without re-absorb
    rows = [
        json.loads(line)
        for line in paths.lake_catalog_path().read_text().splitlines()
        if line
    ]
    rows = [r for r in rows if r.get("idc") != "0707.0978"]
    paths.lake_catalog_path().write_text("".join(json.dumps(r) + "\n" for r in rows))
    heal = absorb_corpus(corpus, index, registry=_registry(), manifests=[mdir])
    assert heal["absorbed"] == 0
    assert lake.LakeCatalog.load().state("0707.0978") == "hydrated"


def test_absorb_corpus_dry(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _mk_legacy_cell(corpus, "0707.0978")
    stats = absorb_corpus(corpus, Index(), dry=True)
    assert stats["absorbed"] == 1
    assert not lake.cell_dir("0707.0978").exists()
    assert not paths.lake_catalog_path().exists()
