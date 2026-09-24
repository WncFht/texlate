"""P3 retention verbs — CAS projection (cas_link_tree / cas_link_leaves),
splice slim (_splice_keep / slim_splice), and the prune shrink gate
(_cell_shrinkable + shrink-on-blocked wiring)."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from kernel import cas, cli, events, paths, runs, vault

IDC = "cond-mat/9601002"
SID = "cond-mat--9601002"
IDC2 = "2401.00002"
SID2 = "2401.00002"

BIG = vault.CAS_LINK_FLOOR + 4096


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def _blob(n: int, seed: bytes) -> bytes:
    return (seed * (n // len(seed) + 1))[:n]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_rows() -> list[dict]:
    return [r for _ln, r, _raw in events.iter_jsonl(paths.vault_manifest_path())
            if isinstance(r, dict)]


def _meta(idc=IDC, arm="real", variant="-", altseq="0") -> dict:
    return json.loads(
        vault.meta_path(idc, arm, variant, altseq).read_text(encoding="utf-8"))


def _splice_src(tmp_path: Path, name: str = "sp") -> Path:
    """Real-shaped splice leaf: stem-matched final pdf + arm + log kept;
    dup pdf, root figs, tex source, figs/ and anc/ all doomed."""
    return _tree(tmp_path / name, {
        "Manuscript.tex": b"\\bye",
        "Manuscript.pdf": _blob(5000, b"final-pdf"),
        ".fixloop-entry.pdf": _blob(5000, b"dup-pdf"),
        "fig1.pdf": _blob(3000, b"figpdf"),
        "figs/f.pdf": b"nested-fig",
        "anc/a.txt": b"anc",
        "Manuscript.log": b"log-bytes",
        ".xlat-arm.json": b"{}",
    })


# --- cas_link_tree ------------------------------------------------------------------


def test_cas_link_tree_links_big_skips_small(broot, tmp_path):
    payload = _blob(BIG, b"big")
    tree = _tree(tmp_path / "t", {"big.bin": payload, "small.bin": b"tiny"})
    stats = vault.cas_link_tree(tree)
    assert stats == {"linked": 1, "bytes": BIG}
    obj = cas.object_path(_sha(payload), "file")
    assert obj.exists()
    assert os.stat(tree / "big.bin").st_ino == os.stat(obj).st_ino
    # under the floor the file keeps its private inode — no object stored
    assert not cas.has(_sha(b"tiny"), kind="file")


def test_cas_link_tree_dedup_hit_shares_one_inode(broot, tmp_path):
    payload = _blob(BIG, b"shared")
    t1 = _tree(tmp_path / "a", {"f.bin": payload})
    t2 = _tree(tmp_path / "b", {"f.bin": payload})
    vault.cas_link_tree(t1)
    vault.cas_link_tree(t2)
    obj = cas.object_path(_sha(payload), "file")
    assert os.stat(t1 / "f.bin").st_ino == os.stat(obj).st_ino
    assert os.stat(t2 / "f.bin").st_ino == os.stat(obj).st_ino
    assert os.stat(obj).st_nlink == 3  # object + two leaf projections


def test_cas_link_tree_sha_map_hit_skips_store(broot, tmp_path, monkeypatch):
    payload = _blob(BIG, b"m")
    sha = cas.store_bytes(payload, kind="file")  # object already live
    tree = _tree(tmp_path / "t", {"f.bin": payload})

    def boom(*_a, **_k):
        raise AssertionError("store_file must not run on a sha_map hit")

    monkeypatch.setattr(cas, "store_file", boom)
    stats = vault.cas_link_tree(tree, {"f.bin": sha})
    assert stats["linked"] == 1
    assert os.stat(tree / "f.bin").st_ino == \
        os.stat(cas.object_path(sha, "file")).st_ino


# --- cas_link_leaves (retroverb) ------------------------------------------------------


def test_iter_committed_leaves_shared_root_yields_once(broot):
    # pending/primary/alt share vault/{kind} physically — a leaf must be
    # yielded exactly once, labeled by its physical root
    _tree(paths.vault_dir() / "zh" / SID / "real", {"f": b"x"})
    zones = [z for z, *_ in vault._iter_committed_leaves("zh")]
    assert zones == ["main"]


def test_cas_link_leaves_links_fused_leaf_and_refuses(broot):
    # pre-hook leaf: hand-built committed dir, already read-only fused
    leaf = _tree(paths.vault_dir() / "splice" / SID / "real", {
        "big.pdf": _blob(BIG, b"pdf"),
        "note.txt": b"small",
    })
    vault._chmod_readonly_tree(leaf, include_root=True)

    dry = vault.cas_link_leaves(kind="splice", dry=True)
    assert dry == [{
        "zone": "main", "kind": "splice", "sid": SID, "key": "real",
        "candidates": 1, "bytes": BIG, "linked": 0,
    }]
    # dry is pure — private inode, nothing stored
    assert not cas.has(_sha(_blob(BIG, b"pdf")), kind="file")

    rows = vault.cas_link_leaves(kind="splice")
    assert len(rows) == 1
    assert rows[0]["linked"] == 1 and rows[0]["bytes"] == BIG
    f = leaf / "big.pdf"
    obj = cas.object_path(_sha(_blob(BIG, b"pdf")), "file")
    assert os.stat(f).st_ino == os.stat(obj).st_ino
    # fuse re-applied over the whole leaf
    for p in (leaf, f, leaf / "note.txt"):
        assert stat.S_IMODE(p.stat().st_mode) & 0o222 == 0


def test_cas_link_leaves_idc_filter(broot):
    for sid in (SID, SID2):
        _tree(paths.vault_dir() / "zh" / sid / "real",
              {"b.bin": _blob(BIG, sid.encode())})
    rows = vault.cas_link_leaves(kind="zh", idc=IDC2)
    assert [r["sid"] for r in rows] == [SID2]


# --- _splice_keep ----------------------------------------------------------------------


def test_splice_keep_stem_match(broot, tmp_path):
    leaf = _splice_src(tmp_path)
    keep = vault._splice_keep(leaf)
    assert {p.name for p in keep} == {
        "Manuscript.pdf", ".xlat-arm.json", "Manuscript.log"}


def test_splice_keep_largest_pdf_fallback(broot, tmp_path):
    leaf = _tree(tmp_path / "leaf", {
        "src.tex": b"t",           # stem 'src' matches no pdf
        "a.pdf": _blob(100, b"a"),
        "b.pdf": _blob(9000, b"b"),
    })
    keep = vault._splice_keep(leaf)
    assert {p.name for p in keep} == {"b.pdf"}


# --- slim_splice ------------------------------------------------------------------------


def test_slim_splice_dry_then_real(broot, tmp_path):
    vault.harvest(IDC, "real", "-", {"splice": _splice_src(tmp_path)})
    leaf = paths.vault_dir() / "splice" / SID / "real"
    pre_bytes = _meta()["bytes"]

    dry = vault.slim_splice(dry=True)
    assert len(dry) == 1
    d = dry[0]
    assert d["meta"] is True and d["zone"] == "main"
    assert d["kept"] == [".xlat-arm.json", "Manuscript.log", "Manuscript.pdf"]
    assert d["dropped_bytes"] > 0
    # dry is pure — every doomed node still on disk
    for rel in ("Manuscript.tex", ".fixloop-entry.pdf", "fig1.pdf",
                "figs/f.pdf", "anc/a.txt"):
        assert (leaf / rel).exists(), rel

    rows = vault.slim_splice()
    assert len(rows) == 1
    r = rows[0]
    assert r["zone"] == "pending"  # logical zone comes from meta
    assert {p.name for p in leaf.iterdir()} == {
        ".xlat-arm.json", "Manuscript.log", "Manuscript.pdf"}
    meta = _meta()
    assert [row["path"] for row in meta["files"]["splice"]] == r["kept"]
    assert meta["bytes"] == pre_bytes - r["dropped_bytes"]
    assert meta["slimmed"]["kept"] == r["kept"]
    assert meta["slimmed"]["dropped_bytes"] == r["dropped_bytes"]
    last = _manifest_rows()[-1]
    assert last["op"] == "slim" and last["idc"] == IDC
    assert last["zone"] == "pending"
    assert last["dropped_bytes"] == r["dropped_bytes"]

    # idempotent — a leaf already at surface is skipped
    assert vault.slim_splice() == []


def test_slim_splice_idc_filter(broot, tmp_path):
    vault.harvest(IDC, "real", "-", {"splice": _splice_src(tmp_path, "a")})
    vault.harvest(IDC2, "real", "-", {"splice": _splice_src(tmp_path, "b")})
    rows = vault.slim_splice(idc=IDC2)
    assert [r["sid"] for r in rows] == [SID2]
    leaf1 = paths.vault_dir() / "splice" / SID / "real"
    assert (leaf1 / "Manuscript.tex").exists()  # untouched


def test_slim_splice_quar_leaf_reports_meta_zone(broot, tmp_path):
    vault.harvest(IDC, "real", "-", {"splice": _splice_src(tmp_path)})
    vault.promote(IDC, "real", "-", "0", "quar", "quar")
    leaf = paths.vault_dir() / "quar" / "splice" / SID / "real"
    assert leaf.is_dir()
    rows = vault.slim_splice()
    assert len(rows) == 1 and rows[0]["zone"] == "quar"
    assert not (leaf / "Manuscript.tex").exists()
    assert _manifest_rows()[-1]["zone"] == "quar"


def test_slim_splice_metaless_leaf_still_slims(broot, tmp_path):
    # squatter bytes without a meta — slims physically, manifest row gets
    # bytes=None and the physical zone label
    leaf = _splice_src(paths.vault_dir() / "splice" / SID)
    # _splice_src builds under tmp_path-shaped root; re-point into vault
    rows = vault.slim_splice(dry=True)
    assert len(rows) == 1 and rows[0]["meta"] is False
    vault.slim_splice()
    assert {p.name for p in leaf.iterdir()} == {
        ".xlat-arm.json", "Manuscript.log", "Manuscript.pdf"}
    last = _manifest_rows()[-1]
    assert last["op"] == "slim" and last["bytes"] is None


# --- prune shrink-on-blocked ----------------------------------------------------------


def test_cell_shrinkable_gate(broot):
    cell = broot / "c1"
    (cell / "xlat-state.real").mkdir(parents=True)
    (cell / "xlat-state.real" / "seg-1.json").write_bytes(b"ckpt")
    assert cli._cell_shrinkable(cell)
    # the real cell-side checkpoint spelling is state.{arm}[@{variant}]
    (cell / "state.real@v1").mkdir()
    (cell / "state.real@v1" / "state.json").write_bytes(b"ckpt2")
    assert cli._cell_shrinkable(cell)
    (cell / "xlat-state@rep2").mkdir()
    (cell / "xlat-state@rep2" / "seg.json").write_bytes(b"ckpt3")
    assert cli._cell_shrinkable(cell)
    # empty paid-named dirs carry no files — still shrinkable
    (cell / "zh.real").mkdir()
    assert cli._cell_shrinkable(cell)
    # a real paid product tree forbids the shrink
    (cell / "zh.real" / "out.md").write_bytes(b"paid")
    assert not cli._cell_shrinkable(cell)


def test_prune_shrinks_checkpoint_only_blocked_cell(broot):
    rd = runs.create_run("soak", date="2026-09-24",
                         spec_dict={"kind": "soak"})
    cell = rd.work("9901.00009")
    (cell / "state.real@v1").mkdir(parents=True)
    (cell / "state.real@v1" / "state.json").write_bytes(b"paid-ckpt")
    (cell / "state.real@v1" / "xlat-detail.jsonl").write_bytes(b"log")
    (cell / "receipt.json").write_bytes(b"{}")
    (cell / "build-base").mkdir()
    (cell / "build-base" / "junk.bin").write_bytes(b"rebuildable")
    (cell / ".xlat-stage").mkdir()
    (cell / ".xlat-stage" / "main.tex").write_bytes(b"staging")

    rc = cli.main(["prune", "--run", rd.run, "--keep", "events"])
    assert rc == cli.EXIT_FAIL          # still blocked — paid shape present
    assert cell.exists()                # cell root survives
    # checkpoint + shell kept, rebuildable bulk gone
    assert (cell / "state.real@v1" / "state.json").exists()
    assert (cell / "state.real@v1" / "xlat-detail.jsonl").exists()
    assert (cell / "receipt.json").exists()
    assert not (cell / "build-base").exists()
    assert not (cell / ".xlat-stage").exists()


def test_prune_paid_product_cell_stays_whole(broot):
    rd = runs.create_run("soak", date="2026-09-24",
                         spec_dict={"kind": "soak"})
    cell = rd.work("9901.00010")
    (cell / "splice.real").mkdir(parents=True)
    (cell / "splice.real" / "M.pdf").write_bytes(b"paid")
    (cell / "build.x").mkdir()
    (cell / "build.x" / "junk.bin").write_bytes(b"rebuildable")

    rc = cli.main(["prune", "--run", rd.run, "--keep", "events"])
    assert rc == cli.EXIT_FAIL
    # not checkpoint-only → no shrink; the whole cell waits for harvest
    assert (cell / "splice.real" / "M.pdf").exists()
    assert (cell / "build.x" / "junk.bin").exists()


# --- corpus_v3 TARS prune -------------------------------------------------------------


def test_prune_tar_deletes_tar_and_part(broot, tmp_path, monkeypatch):
    from specs import corpus_v3

    tars = tmp_path / "tars"
    tars.mkdir()
    (tars / "2501_001.tar").write_bytes(b"TAR")
    (tars / "2501_001.tar.part").write_bytes(b"PART")
    (tars / "2501_002.tar").write_bytes(b"OTHER")
    monkeypatch.setattr(corpus_v3, "TARS", tars)

    freed = corpus_v3._prune_tar({"item": "2501_001"})
    assert freed == len(b"TAR") + len(b"PART")
    assert not (tars / "2501_001.tar").exists()
    assert not (tars / "2501_001.tar.part").exists()
    assert (tars / "2501_002.tar").exists()      # only the named chunk dies
    # already-gone tar is a no-op, not an error
    assert corpus_v3._prune_tar({"item": "2501_001"}) == 0
