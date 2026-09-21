"""Tests for kernel.vault — two-phase commit, dedup criterion, verify/heal."""
from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest
from kernel import events, paths, vault

IDC = "cond-mat/9601002"
SID = "cond-mat--9601002"
IDC2 = "2401.00002"
SID2 = "2401.00002"


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    """Materialize a small tree of regular files under ``root``."""
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def _manifest_rows() -> list[dict]:
    return [r for _ln, r, _raw in events.iter_jsonl(paths.vault_manifest_path())
            if isinstance(r, dict)]


def _events_of(etype: str) -> list[dict]:
    return [e for _ln, e, _raw in events.iter_jsonl(paths.events_path())
            if isinstance(e, dict) and e.get("type") == etype]


def _meta(idc=IDC, arm="r", variant="-", altseq="0") -> dict:
    return json.loads(
        vault.meta_path(idc, arm, variant, altseq).read_text(encoding="utf-8"))


# --- naming ----------------------------------------------------------------------

def test_meta_key_roundtrip_and_escaping(broot):
    cases = [
        ("cond-mat/9601002", "zh", "-", "0"),
        ("math.QA/9703043", "a.b@c", "v.1@x", "7"),
        ("2101.12345", "r", "rep3", "soak-2026-09-21"),
    ]
    for idc, arm, variant, altseq in cases:
        name = vault.meta_key(idc, arm, variant, altseq)
        assert name.endswith(".json")
        assert "/" not in name
        assert vault.parse_meta_key(name) == (idc, arm, variant, altseq)


def test_meta_key_normalizes_safe_form_input(broot):
    assert vault.meta_key("cond-mat/9601002", "zh") == \
        vault.meta_key("cond-mat--9601002", "zh")


def test_dir_key_roundtrip(broot):
    assert vault.dir_key("zh") == "zh"
    assert vault.dir_key("zh", "rep2") == "zh@rep2"
    assert vault.dir_key("a.b", "-", "3") == "a%2Eb.3"
    assert vault.parse_dir_key("a%2Eb.3") == ("a.b", "-", "3")
    assert vault.parse_dir_key("a%40b@c") == ("a@b", "c", "0")


def test_bad_altseq_rejected(broot):
    # altseq is charset-restricted and never escaped — separator chars refuse;
    # "" is not bad input: like '-'/'0' it spells the null/default component
    for bad in ("a.b", "x@y", "a/b", "a b"):
        with pytest.raises(ValueError):
            vault.dir_key("r", "-", bad)
    assert vault.dir_key("r", "-", "") == "r"


# --- harvest: the commit path -----------------------------------------------------

def test_harvest_commits_bytes_meta_manifest_in_order(broot, tmp_path):
    src = tmp_path / "work"
    zh = _tree(src / "zh.real", {"main.md": b"# zh", "figs/f.pdf": b"%PDF-x"})
    sp = _tree(src / "splice.real", {"s.tex": b"tex"})
    mpath = vault.harvest(IDC, "real", "-",
                          {"zh": zh, "splice": sp}, source_run="r1")
    assert mpath.parent == paths.vault_meta_dir()
    meta = json.loads(mpath.read_text(encoding="utf-8"))
    assert meta["idc"] == IDC and meta["arm"] == "real"
    assert meta["zone"] == "pending" and meta["verdict"] == "pending"
    assert meta["altseq"] == "0" and meta["staged"] is True
    assert set(meta["files"]) == {"zh", "splice"}
    assert meta["source_run"] == "r1"
    # committed bytes at the kind roots, read-only fused
    zd = paths.vault_dir() / "zh" / SID / "real"
    sd = paths.vault_dir() / "splice" / SID / "real"
    assert (zd / "main.md").read_bytes() == b"# zh"
    assert (zd / "figs" / "f.pdf").read_bytes() == b"%PDF-x"
    for f in (zd / "main.md", zd / "figs" / "f.pdf", sd / "s.tex", zd, sd):
        assert stat.S_IMODE(f.stat().st_mode) & 0o222 == 0
    # zero-copy: the vault file IS the work file's inode; the a-w fuse
    # therefore propagates to the work tree (intended, see module docstring)
    assert os.stat(zd / "main.md").st_ino == os.stat(zh / "main.md").st_ino
    assert stat.S_IMODE((zh / "main.md").stat().st_mode) & 0o222 == 0
    # commit order: the meta marker is the last thing written
    assert mpath.stat().st_mtime >= zd.stat().st_mtime
    # manifest row recorded inside the lock
    row = _manifest_rows()[-1]
    assert row["op"] == "harvest" and row["idc"] == IDC
    assert row["zone"] == "pending" and row["altseq"] == "0"
    assert row["bytes_ok"] is True and row["path"] == f"{SID}/real"
    # per-kind asset events emitted after lock release
    evs = _events_of("asset")
    assert {(e["kind"], e["state"]) for e in evs} == {
        ("zh", "pending"), ("splice", "pending")}
    assert all(e["verdict"] == "pending" and e["altseq"] == "0" for e in evs)
    assert all(e["path"].endswith(f"{SID}/real") for e in evs)
    # physical criterion satisfied; policy criterion not (pending dedups not)
    assert vault.bytes_ok(IDC, "real", "-")
    assert not vault.dedup_hit(IDC, "real", "-")


def test_harvest_dest_occupied_and_altseq_autopick(broot, tmp_path):
    s1 = _tree(tmp_path / "a/zh.r", {"f": b"one"})
    s2 = _tree(tmp_path / "b/zh.r", {"f": b"two"})
    vault.harvest(IDC, "r", "-", {"zh": s1}, altseq="0")
    with pytest.raises(vault.DestOccupied):
        vault.harvest(IDC, "r", "-", {"zh": s2}, altseq="0")
    # auto assignment lands the second physical copy on altseq '1'
    vault.harvest(IDC, "r", "-", {"zh": s2})
    assert _meta()["altseq"] == "0"
    assert _meta(altseq="1")["altseq"] == "1"
    assert (paths.vault_dir() / "zh" / SID / "r" / "f").read_bytes() == b"one"
    assert (paths.vault_dir() / "zh" / SID / "r.1" / "f").read_bytes() == b"two"
    assert len(vault.query(IDC)) == 2


def test_harvest_refuses_preexisting_metaless_dest(broot, tmp_path):
    # uncommitted bytes squatting at the destination must not be nested
    squat = paths.vault_dir() / "zh" / SID / "r"
    _tree(squat, {"x": b"squat"})
    s = _tree(tmp_path / "s/zh.r", {"f": b"v"})
    with pytest.raises(vault.DestOccupied):
        vault.harvest(IDC, "r", "-", {"zh": s}, altseq="0")
    vault.harvest(IDC, "r", "-", {"zh": s})          # auto -> '1'
    assert (squat / "x").exists()                   # squatter untouched
    assert _meta(altseq="1")["altseq"] == "1"


def test_meta_write_failure_rolls_back_renames(broot, tmp_path, monkeypatch):
    s = _tree(tmp_path / "w/zh.r", {"f": b"x"})

    def boom(*_a, **_k):
        raise RuntimeError("crash at meta write")

    monkeypatch.setattr(vault.fsutil, "atomic_write", boom)
    with pytest.raises(RuntimeError):
        vault.harvest(IDC, "r", "-", {"zh": s})
    # rollback: no committed leaf, no empty sid parent, nothing meta-less
    assert not (paths.vault_dir() / "zh" / SID / "r").exists()
    assert not (paths.vault_dir() / "zh" / SID).exists()
    assert vault.find_meta_less_dirs() == []
    assert _manifest_rows() == []
    assert not vault.bytes_ok(IDC, "r", "-")


def test_meta_less_bytes_never_dedup(broot):
    # forensic state of a kill between rename and meta write
    zd = paths.vault_dir() / "zh" / SID / "r"
    _tree(zd, {"main.md": b"paid bytes"})
    assert not vault.bytes_ok(IDC, "r", "-")
    assert not vault.dedup_hit(IDC, "r", "-")
    assert zd in vault.find_meta_less_dirs()
    rep = vault.verify()
    assert str(zd) in rep["meta_missing"]


def test_bytes_ok_negative_cases(broot, tmp_path):
    s = _tree(tmp_path / "w/zh.r", {"a": b"1", "b": b"22"})
    vault.harvest(IDC, "r", "-", {"zh": s})
    assert vault.bytes_ok(IDC, "r", "-")
    zd = paths.vault_dir() / "zh" / SID / "r"
    bf = zd / "b"
    os.chmod(bf, 0o600)                     # lift fuse for surgery (owner may)
    bf.write_bytes(b"2")                    # size drift
    assert not vault.bytes_ok(IDC, "r", "-")
    os.chmod(zd, 0o755)                     # dir fuse blocks unlink, lift it
    bf.unlink()                             # missing file
    assert not vault.bytes_ok(IDC, "r", "-")
    vault.meta_path(IDC, "r", "-", "0").unlink()   # commit marker gone
    assert not vault.bytes_ok(IDC, "r", "-")


def test_harvest_refuses_bad_assets(broot, tmp_path):
    empty = _tree(tmp_path / "w/zh.r", {"zero": b""})
    with pytest.raises(vault.VaultError):
        vault.harvest(IDC, "r", "-", {"zh": empty})
    with pytest.raises(vault.VaultError):
        vault.harvest(IDC, "r", "-", {"zh": tmp_path / "missing"})
    with pytest.raises(ValueError):
        vault.harvest(IDC, "r", "-", {"pdf": tmp_path / "x"})
    linked = _tree(tmp_path / "w2/zh.r", {"f": b"x"})
    os.symlink("f", linked / "link")
    with pytest.raises(vault.VaultError):
        vault.harvest(IDC, "r", "-", {"zh": linked})


# --- promote -------------------------------------------------------------------------

def test_promote_zero_io_and_quar_relocation(broot, tmp_path):
    s = _tree(tmp_path / "w/zh.r", {"f": b"paid"})
    vault.harvest(IDC, "r", "-", {"zh": s})
    zd = paths.vault_dir() / "zh" / SID / "r"
    ino = os.stat(zd / "f").st_ino
    vault.promote(IDC, "r", "-", "0", "primary", "primary")
    meta = _meta()
    assert meta["zone"] == "primary" and meta["verdict"] == "primary"
    assert meta["prev_zone"] == "pending"
    # zero byte I/O — same dir, same inode
    assert zd.exists() and os.stat(zd / "f").st_ino == ino
    assert _manifest_rows()[-1]["op"] == "promote"
    assert vault.dedup_hit(IDC, "r", "-")
    # promote to quar physically relocates the copy (quar keeps a real root)
    vault.promote(IDC, "r", "-", "0", "quar", "quar")
    qd = paths.vault_dir() / "quar" / "zh" / SID / "r"
    assert not zd.exists() and (qd / "f").exists()
    assert os.stat(qd / "f").st_ino == ino
    assert _meta()["zone"] == "quar"
    assert vault.bytes_ok(IDC, "r", "-")
    assert vault.dedup_hit(IDC, "r", "-")      # quar dedups per §3.8
    # and back out of quarantine
    vault.promote(IDC, "r", "-", "0", "primary", "primary")
    assert (zd / "f").exists() and not qd.exists()


def test_promote_missing_meta_raises(broot):
    with pytest.raises(vault.MetaMissing):
        vault.promote(IDC, "r", "-", "0", "primary", "primary")


def test_pending_metas_listing(broot, tmp_path):
    s = _tree(tmp_path / "w/zh.r", {"f": b"x"})
    vault.harvest(IDC, "r", "-", {"zh": s})
    pend = vault.pending_metas()
    assert len(pend) == 1 and pend[0]["idc"] == IDC
    vault.promote(IDC, "r", "-", "0", "primary", "primary")
    assert vault.pending_metas() == []


# --- adopt -----------------------------------------------------------------------------

def test_adopt_lands_in_quar_with_note(broot, tmp_path):
    orphan = _tree(tmp_path / "found", {"zh": b"orphan bytes", "d/x": b"y"})
    dest = vault.adopt(orphan, IDC, "r", "-", reason="test-orphan")
    assert dest == paths.vault_dir() / "quar" / "zh" / SID / "r"
    assert (dest / "zh").read_bytes() == b"orphan bytes"
    meta = _meta()
    assert meta["zone"] == "quar" and meta["verdict"] == "quar"
    notes = _events_of("note")
    assert any("adopted" in n["text"] and n["level"] == "warn" for n in notes)
    assert any(a["state"] == "adopted" for a in _events_of("asset"))
    assert vault.dedup_hit(IDC, "r", "-")
    assert _manifest_rows()[-1]["op"] == "adopt"


def test_adopt_refuses_non_regular(broot, tmp_path):
    bad = _tree(tmp_path / "bad", {"f": b"x"})
    os.mkfifo(bad / "pipe")
    with pytest.raises(vault.VaultError):
        vault.adopt(bad, IDC)


# --- restore ------------------------------------------------------------------------------

def test_restore_copy_and_link_modes(broot, tmp_path):
    s = _tree(tmp_path / "w/zh.r", {"main.md": b"body", "fig/f": b"img"})
    vault.harvest(IDC, "r", "-", {"zh": s})
    zf = paths.vault_dir() / "zh" / SID / "r" / "main.md"
    n = vault.restore(IDC, "r", "-", tmp_path / "out1", mode="copy")
    assert n == 2
    rf = tmp_path / "out1" / "zh.r" / "main.md"
    assert rf.read_bytes() == b"body"
    assert stat.S_IMODE(rf.stat().st_mode) & stat.S_IWUSR     # writable copy
    assert os.stat(rf).st_ino != os.stat(zf).st_ino           # independent
    vault.restore(IDC, "r", "-", tmp_path / "out2", mode="link")
    lf = tmp_path / "out2" / "zh.r" / "main.md"
    assert os.stat(lf).st_ino == os.stat(zf).st_ino           # shared inode
    assert stat.S_IMODE(lf.stat().st_mode) & 0o222 == 0       # fuse kept


def test_restore_refuses_when_no_intact_copy(broot, tmp_path):
    s = _tree(tmp_path / "w/zh.r", {"f": b"good"})
    vault.harvest(IDC, "r", "-", {"zh": s})
    zf = paths.vault_dir() / "zh" / SID / "r" / "f"
    os.chmod(zf, 0o600)
    zf.write_bytes(b"!!!longer")
    with pytest.raises(vault.VaultError):
        vault.restore(IDC, "r", "-", tmp_path / "out")


# --- verify / heal ---------------------------------------------------------------------------

def test_verify_full_aggregates_shared_inodes(broot, tmp_path):
    # zh and splice staged from the SAME inode -> vault aliases share it
    zh = tmp_path / "w/zh.r"
    sp = tmp_path / "w/splice.r"
    zh.mkdir(parents=True)
    sp.mkdir(parents=True)
    (zh / "f").write_bytes(b"same-content")
    os.link(zh / "f", sp / "f")
    vault.harvest(IDC, "r", "-", {"zh": zh, "splice": sp})
    zf = paths.vault_dir() / "zh" / SID / "r" / "f"
    sf = paths.vault_dir() / "splice" / SID / "r" / "f"
    assert os.stat(zf).st_ino == os.stat(sf).st_ino
    assert vault.verify("full")["bad"] == []
    # corrupt through the shared inode at the same length — stat stays clean
    os.chmod(zf, 0o600)
    zf.write_bytes(b"XXXX-content")
    assert vault.verify("stat")["bad"] == []           # size unchanged
    rep = vault.verify("full")
    assert len(rep["bad"]) == 1
    entry = rep["bad"][0]
    assert entry["reason"] == "sha_mismatch"
    assert set(entry["paths"]) == {str(zf), str(sf)}   # one bad inode, all aliases


def test_verify_stat_catches_size_drift(broot, tmp_path):
    s = _tree(tmp_path / "w/zh.r", {"f": b"12345"})
    vault.harvest(IDC, "r", "-", {"zh": s})
    zf = paths.vault_dir() / "zh" / SID / "r" / "f"
    os.chmod(zf, 0o600)
    zf.write_bytes(b"1234567")
    rep = vault.verify("stat")
    assert len(rep["bad"]) == 1
    assert rep["bad"][0]["reason"] == "size_mismatch"


def test_heal_relinks_all_aliases(broot, tmp_path):
    # cell A: zh/f and splice/f share inode I1
    zh = tmp_path / "wa/zh.r"
    sp = tmp_path / "wa/splice.r"
    zh.mkdir(parents=True)
    sp.mkdir(parents=True)
    (zh / "f").write_bytes(b"cell-bytes")
    os.link(zh / "f", sp / "f")
    vault.harvest(IDC, "r", "-", {"zh": zh, "splice": sp})
    # cell B: independent copy of the same bytes -> unique donor inode I2
    zhb = _tree(tmp_path / "wb/zh.r", {"f": b"cell-bytes"})
    vault.harvest(IDC2, "r", "-", {"zh": zhb})
    azf = paths.vault_dir() / "zh" / SID / "r" / "f"
    asf = paths.vault_dir() / "splice" / SID / "r" / "f"
    donor = paths.vault_dir() / "zh" / SID2 / "r" / "f"
    os.chmod(azf, 0o600)
    azf.write_bytes(b"CORRUPTED!!!")
    rep = vault.verify("full")
    assert len(rep["bad"]) == 1
    assert vault.heal(rep) == 2                        # BOTH aliases re-linked
    assert os.stat(azf).st_ino == os.stat(donor).st_ino
    assert os.stat(asf).st_ino == os.stat(donor).st_ino
    assert vault.verify("full")["bad"] == []


def test_heal_refuses_ambiguous_donor(broot, tmp_path):
    # three independent inodes carry the same bytes; corrupt one -> two good
    # donors remain -> sha-binding ambiguity must refuse, never pick
    for i, idc in enumerate((IDC, "2101.00003", "2101.00004")):
        src = _tree(tmp_path / f"w{i}/zh.r", {"f": b"dup-bytes"})
        vault.harvest(idc, "r", "-", {"zh": src})
    azf = paths.vault_dir() / "zh" / SID / "r" / "f"
    os.chmod(azf, 0o600)
    azf.write_bytes(b"bad")
    rep = vault.verify("full")
    assert len(rep["bad"]) == 1
    with pytest.raises(vault.AmbiguousDonor):
        vault.heal(rep)


# --- tombstone / concurrency ------------------------------------------------------------------

def test_tombstone_event_and_manifest_row(broot):
    vault.tombstone(IDC, "r", "-", "zh",
                    reason="bytes lost in wipe", lost_run="r0")
    tombs = _events_of("tombstone")
    assert len(tombs) == 1
    t = tombs[0]
    assert t["idc"] == IDC and t["kind"] == "zh" and t["lost_run"] == "r0"
    row = _manifest_rows()[-1]
    assert row["op"] == "tombstone" and row["reason"] == "bytes lost in wipe"


def test_concurrent_harvests_serialize(broot, tmp_path):
    errs = []

    def work(i):
        try:
            src = _tree(tmp_path / f"w{i}/zh.r",
                        {"f": f"bytes-{i}".encode()})
            vault.harvest(f"2101.000{i:02d}", "r", "-", {"zh": src})
        except Exception as e:  # noqa: BLE001 — collected for assertion
            errs.append(e)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    rows = _manifest_rows()
    assert len([r for r in rows if r.get("op") == "harvest"]) == 6
    for i in range(6):
        assert vault.bytes_ok(f"2101.000{i:02d}", "r", "-")
