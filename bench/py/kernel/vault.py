"""vault — the paid-bytes zone (design §3.5, §3.10.4, §3.10.6; risks R4/R5).

Layout (paths.py owns the roots; this module owns everything beneath them)::

    vault/
    ├── .vault-sentinel            # mount proof — writes refuse when missing
    ├── .lock                      # the single global vault write lock (immortal)
    ├── .staging/{tag}/{kind}/     # harvest staging — same volume as vault
    ├── {zh,splice,state}/{safe_id}/{arm}[@{variant}][.{altseq}]/
    │                              # pending/primary/alt copies (zone = metadata)
    ├── quar/{kind}/{safe_id}/{arm}[@{variant}][.{altseq}]/
    │                              # quarantine keeps a physical separate root
    │                              # (§3.10.4 "仅 quar 保留物理分根", mirroring the
    │                              #  kind-first shape: vault/quar/<kind>/...)
    ├── meta/{esc(sid)}.{esc(arm)}[@{esc(variant)}][.{altseq}].json
    │                              # per-copy commit marker — written LAST
    └── manifest.jsonl             # append-only credential ledger rows (in-lock)

Two-phase commit order (§3.5 — the direction is nailed down):

    work bytes -> hardlink into .staging/{tag}/{kind}/ (os.link zero-copy;
    EXDEV -> copyfile) -> .files.jsonl manifest -> chmod -R a-w (fuse) ->
    fsync -> rename() each kind dir into place (same volume, atomic per dir)
    -> meta/*.json written LAST via atomic_write (the commit marker) ->
    manifest.jsonl appended -> lock released -> asset events emitted.

A kill between rename and meta leaves "bytes visible, no meta": directory
existence NEVER counts — the dedup criterion (``bytes_ok``) requires a
parseable meta AND every declared asset present non-empty on disk, so
uncommitted bytes can never satisfy dedup (R4). A catchable failure after
renames (e.g. meta write error) unfuses and deletes the dirs it just moved —
the kernel only ever deletes files it created itself.

Link + fuse semantics: staged files share the *source work tree's* inode,
so ``chmod -R a-w`` makes the work-side file read-only too. That is the
intended fuse direction (harvest fires after the last mutating stage —
the work copy IS the vault copy, immutable everywhere). Consumers that
must write get ``restore(mode='copy')``; ``mode='link'`` hands back the
shared 0444 inode — mutating it fails EACCES loudly, which the design
prefers over a silently poisoned vault (§3.10.4).

Credential = (idc, arm, variant, altseq, zone) — five dimensions, one meta
file per physical copy. ``.{altseq}`` disambiguates multiple copies of one
(idc,arm,variant) in the same namespace; meta filenames and leaf dir names
escape every component via idnorm (injective round-trip: '.'->%2E,
'@'->%40, '%'->%25 first; altseq is charset-restricted, never escaped).
Parse eats the .json suffix then the .altseq suffix, then splits.

Verdicts (§3.8): ``bytes_ok`` is the PHYSICAL criterion — meta parseable
and declared bytes intact (pending included: the bytes are really there).
``dedup_hit`` is the policy criterion — intact AND verdict in
{primary,alt,quar,adopted,verified}; pending/tombstone excluded. The paid
gate composes them with the in-lock claim recheck upstream.

Locks: every vault write serializes through ``vault/.lock`` — EX for
harvest/promote/adopt/tombstone/heal, SH for verify/find_meta_less_dirs/
restore. Meta reads are lock-free (atomic_write means readers only ever
see complete files). Ledger events are emitted AFTER the lock is dropped
so the vault critical section never blocks on the ledger's own lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import stat
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from kernel import events, fsutil, idnorm, ledger, locks, paths

__all__ = [
    "DEDUP_VERDICTS",
    "KINDS",
    "VERDICTS",
    "ZONES",
    "AmbiguousDonor",
    "DestOccupied",
    "MetaMissing",
    "VaultError",
    "adopt",
    "bytes_ok",
    "dedup_hit",
    "dir_key",
    "find_meta_less_dirs",
    "harvest",
    "heal",
    "leaf_dir",
    "manifest_rows",
    "meta_key",
    "meta_path",
    "parse_dir_key",
    "parse_meta_key",
    "pending_metas",
    "promote",
    "query",
    "restore",
    "tombstone",
    "verify",
]

# Asset kinds the vault physically stores (§3.10.1: xlat-state is the third;
# layoutqc is the fourth——qc.json+txlm 质检包随末段 mutates 格收割).
KINDS = frozenset({"zh", "splice", "state", "layoutqc"})

# Zone vocabulary: pending/primary/alt live in the kind roots; quar keeps a
# physical separate root under vault/quar/<kind>/.
ZONES = frozenset({"pending", "primary", "alt", "quar"})
_ZONE_ALIASES = {"quarantine": "quar"}

# Verdicts whose intact copies satisfy the §3.8 dedup oracle. pending is
# "视同无字节" for dedup (the lock-recheck blocks double burn elsewhere);
# tombstone is a regen_gate hard stop owned by the paid gate, not a hit.
DEDUP_VERDICTS = frozenset(
    {"primary", "alt", "quar", "quarantine", "adopted", "verified"}
)
VERDICTS = DEDUP_VERDICTS | {"pending", "tombstone"}

_ALTSEQ_RE = re.compile(r"[A-Za-z0-9-]+")
_META_SUFFIX = ".json"
_FILES_MANIFEST = ".files.jsonl"
_HEAL_TMP_SUFFIX = ".heal-tmp"

# zone -> vault-relative root tag (which physical namespace a copy lives in).
_ZONE_TAG = {
    "pending": "primary",
    "primary": "primary",
    "alt": "primary",
    "quar": "quar",
}

# restore() preference when several copies of a cell exist.
_ZONE_RANK = {"primary": 0, "alt": 1, "quar": 2, "pending": 3}


class VaultError(Exception):
    """Base failure for vault operations."""


class DestOccupied(VaultError):
    """A commit destination is already occupied — never silently nest."""


class MetaMissing(VaultError):
    """The commit marker a verb needs is absent or unparseable."""


class AmbiguousDonor(VaultError):
    """heal found >1 distinct good inode for one sha — refusing to pick
    (sha-binding ambiguity must refuse, §3.10.4)."""


# --- naming (credential components — injective escaping, §3.10.4) ---------------


def _comp(v, default: str = "-") -> str:
    return default if v is None or v == "" else str(v)


def _check_idc(idc) -> str:
    """Resolve any accepted spelling to canon idc and prove its safe_id is a
    clean single path segment. canon_id(registry=None) is stateless: safe
    forms decode, vN strips per §3.10.7, deny-listed/bare tails refuse."""
    res = idnorm.canon_id(str(idc))
    if not res.ok or not res.idc:
        msg = f"bad vault id {idc!r}: {res.reason}"
        raise ValueError(msg)
    sid = idnorm.safe_id(res.idc)
    if not sid or sid.startswith(".") or "/" in sid or "\\" in sid:
        msg = f"bad vault id {idc!r}: unusable safe_id {sid!r}"
        raise ValueError(msg)
    return res.idc


def _check_altseq(altseq) -> str:
    a = str(altseq)
    if not _ALTSEQ_RE.fullmatch(a):
        msg = f"bad altseq {altseq!r}: restricted to [A-Za-z0-9-]"
        raise ValueError(msg)
    return a


def _norm_zone(zone) -> str:
    z = _ZONE_ALIASES.get(zone, zone)
    if z not in ZONES:
        msg = f"bad vault zone {zone!r} (allowed: {sorted(ZONES)})"
        raise ValueError(msg)
    return z


def _norm_verdict(verdict) -> str:
    v = _ZONE_ALIASES.get(verdict, verdict)
    if v not in VERDICTS:
        msg = f"bad vault verdict {verdict!r} (allowed: {sorted(VERDICTS)})"
        raise ValueError(msg)
    return v


def dir_key(arm, variant: str = "-", altseq: str = "0") -> str:
    """Leaf directory name ``{arm}[@{variant}][.{altseq}]`` — every component
    percent-escaped so the name round-trips injectively (§3.10.4). The null
    spellings '-' (variant) and '0' (altseq) leave no suffix."""
    name = idnorm.escape_component(_comp(arm))
    variant = _comp(variant)
    if variant != "-":
        name += "@" + idnorm.escape_component(variant)
    altseq = _comp(altseq, "0")
    if altseq != "0":
        name += "." + _check_altseq(altseq)
    return name


def parse_dir_key(name) -> tuple[str, str, str]:
    """Inverse of dir_key -> (arm, variant, altseq)."""
    parts = str(name).split(".")
    if len(parts) == 1:
        armvar, altseq = parts[0], "0"
    elif len(parts) == 2:
        armvar, altseq = parts
        _check_altseq(altseq)
    else:
        msg = f"unparseable vault dir key {name!r}"
        raise ValueError(msg)
    av = armvar.split("@")
    if len(av) > 2 or not av[0]:
        msg = f"unparseable vault dir key {name!r}"
        raise ValueError(msg)
    arm = idnorm.unescape_component(av[0])
    variant = idnorm.unescape_component(av[1]) if len(av) == 2 else "-"
    return arm, variant, altseq


def meta_key(idc, arm, variant: str = "-", altseq: str = "0") -> str:
    """Meta filename ``{esc(sid)}.{dir_key}.json`` — the 5-dim credential's
    canonical name (zone lives in the content, not the name)."""
    idc = _check_idc(idc)
    esc_sid = idnorm.escape_component(idnorm.safe_id(idc))
    return f"{esc_sid}.{dir_key(arm, variant, altseq)}{_META_SUFFIX}"


def parse_meta_key(name) -> tuple[str, str, str, str]:
    """Inverse of meta_key -> (idc, arm, variant, altseq). Eats the .json
    suffix, then splits escaped components (§3.10.4 parse order)."""
    stem = Path(name).name
    if not stem.endswith(_META_SUFFIX):
        msg = f"not a vault meta name {name!r}"
        raise ValueError(msg)
    stem = stem[: -len(_META_SUFFIX)]
    parts = stem.split(".")
    if len(parts) not in (2, 3):
        msg = f"unparseable vault meta name {name!r}"
        raise ValueError(msg)
    idc = idnorm.idc_from_safe(idnorm.unescape_component(parts[0]))
    arm, variant, altseq = parse_dir_key(".".join(parts[1:]))
    return idc, arm, variant, altseq


def meta_path(idc, arm, variant: str = "-", altseq: str = "0") -> Path:
    return paths.vault_meta_dir() / meta_key(idc, arm, variant, altseq)


def _zone_tag(zone: str) -> str:
    """Physical namespace for a zone: quar is the only separate root."""
    return _ZONE_TAG[zone]


def _kind_root(zone: str, kind: str) -> Path:
    if zone == "quar":
        return paths.vault_dir() / "quar" / kind
    return paths.vault_dir() / kind


def leaf_dir(zone, kind, idc, arm, variant: str = "-", altseq: str = "0") -> Path:
    """Absolute path of one committed kind dir for the credential."""
    return (
        _kind_root(_norm_zone(zone), kind)
        / idnorm.safe_id(_check_idc(idc))
        / dir_key(arm, variant, altseq)
    )


def _rel_leaf(zone: str, kind: str, sid: str, key: str) -> str:
    """Vault-relative leaf path used in manifest rows and asset events."""
    if zone == "quar":
        return f"quar/{kind}/{sid}/{key}"
    return f"{kind}/{sid}/{key}"


def _work_dirname(kind: str, arm: str, variant: str) -> str:
    """restore() destination subdir — work-tree convention
    ``{kind}.{arm}[@{variant}]`` (components escaped like vault dir keys)."""
    name = f"{kind}.{idnorm.escape_component(arm)}"
    if variant != "-":
        name += f"@{idnorm.escape_component(variant)}"
    return name


# --- small IO helpers --------------------------------------------------------------


def _require_sentinel() -> None:
    """R5: refuse vault writes when the mount proof is absent — an empty
    mount point must never silently swallow paid bytes."""
    if not paths.vault_sentinel_path().exists():
        msg = (
            f"vault sentinel {paths.vault_sentinel_path()} missing — "
            "refusing to write into a possibly-unmounted vault dir"
        )
        raise VaultError(msg)


def _fsync_file(p: Path) -> None:
    fd = os.open(p, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_tree(root: Path) -> None:
    """fsync every file and dir under root, then root itself."""
    for p, kind in fsutil._iter_tree(root):
        if kind == "file":
            _fsync_file(p)
        elif kind == "dir":
            fsutil.fsync_dir(p)
    fsutil.fsync_dir(root)


def _fsync_ancestors(leaf_parent: Path) -> None:
    """fsync a dir and every ancestor up to and including the vault root —
    dirent durability for the whole sid/kind/quar chain a rename may have
    just created."""
    p = Path(leaf_parent)
    vault = paths.vault_dir()
    while True:
        fsutil.fsync_dir(p)
        if p in (vault, p.parent):
            break
        p = p.parent


def _chmod_readonly_tree(root: Path, include_root: bool = True) -> dict:
    """``chmod -R a-w`` — the vault fuse. Files share the work source's
    inode, so this deliberately makes the work-side copy read-only too.

    ``include_root=False`` leaves the tree root writable: rename(2) must
    rewrite the moved dir's ``..`` entry and refuses a read-only source dir,
    so the top dir is fused only AFTER it lands in place (nested dirs' ``..``
    does not change — they stay fused throughout).

    Returns ``{posix-rel: orig_mode}`` for every node whose write bits were
    actually cleared — the rollback map an aborted commit uses to restore
    the shared source inodes. Already-fused nodes are skipped, so a
    re-harvest of an earlier commit's fused source stays fused (idempotent)."""
    root = Path(root)
    changed: dict[str, int] = {}
    for p, kind in fsutil._iter_tree(root):
        if kind == "link":
            continue
        st = p.stat(follow_symlinks=False)
        mode = stat.S_IMODE(st.st_mode)
        if mode & 0o222:
            os.chmod(p, mode & ~0o222)
            changed[p.relative_to(root).as_posix()] = mode
    if include_root:
        st = root.stat()
        mode = stat.S_IMODE(st.st_mode)
        if mode & 0o222:
            os.chmod(root, mode & ~0o222)
            changed["."] = mode
    return changed


def _unfuse_dirs(root: Path) -> None:
    """Lift the a-w fuse on root and every dir under it — used only for
    aborting a commit this process created (rollback cleanup), never for
    mutating committed bytes."""
    root = Path(root)
    for p, kind in fsutil._iter_tree(root):
        if kind == "dir":
            st = p.stat(follow_symlinks=False)
            os.chmod(p, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
    if root.exists():
        st = root.stat()
        os.chmod(root, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)


def _iter_files(root: Path) -> list[tuple[Path, str]]:
    """(abspath, posix-rel) for every regular file under root, sorted."""
    out = []
    for p, kind in fsutil._iter_tree(Path(root)):
        if kind == "file":
            out.append((p, p.relative_to(root).as_posix()))
    return sorted(out, key=lambda t: t[1])


def _non_regular(root: Path) -> list[Path]:
    """Entries that are neither regular file nor dir — symlinks and special
    files are refused loudly (vault holds regular bytes only)."""
    return [p for p, kind in fsutil._iter_tree(Path(root)) if kind in ("link", "other")]


def _safe_rel(rel) -> str | None:
    """Declared-path sanity: relative, non-empty, no '.'/'..' segments — a
    corrupt meta must never steer verify/restore outside its leaf dir."""
    if not isinstance(rel, str) or not rel:
        return None
    if rel.startswith(("/", "\\")):
        return None
    if any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    return rel


def _read_meta(path: Path) -> dict | None:
    """Tolerant meta read — None on missing/unparseable/wrong shape.
    atomic_write means readers never see a torn meta anyway; None marks
    corruption, never a partial write."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_meta(path: Path, meta: dict) -> None:
    payload = (
        json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    fsutil.atomic_write(path, payload)


def _append_manifest_locked(row: dict) -> None:
    """Append one manifest row inside vault/.lock. Reuses the ledger's
    append primitive — same torn-tail heal + single-write + fsync contract."""
    line = (
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    ledger._append_payload_locked(paths.vault_manifest_path(), line)


def _iter_metas():
    """Yield (meta_path, key_tuple|None, content|None) over meta/*.json.
    key is the filename-parsed credential (authoritative); content is the
    parsed JSON (None when unparseable)."""
    d = paths.vault_meta_dir()
    if not d.is_dir():
        return
    for mp in sorted(d.glob(f"*{_META_SUFFIX}")):
        try:
            key = parse_meta_key(mp.name)
        except ValueError:
            key = None
        yield mp, key, _read_meta(mp)


def manifest_rows() -> list[dict]:
    """All parseable manifest.jsonl rows in append order (tolerant read)."""
    return [
        r
        for _ln, r, _raw in events.iter_jsonl(paths.vault_manifest_path())
        if isinstance(r, dict)
    ]


# --- commit path -----------------------------------------------------------------


def _slot_taken(idc: str, arm: str, variant: str, altseq: str) -> bool:
    """Credential occupancy: meta exists OR any kind dir exists in EITHER
    physical namespace (primary roots and quar roots). A meta-less squatter
    dir also blocks the slot — occupied is occupied."""
    if meta_path(idc, arm, variant, altseq).exists():
        return True
    sid = idnorm.safe_id(idc)
    key = dir_key(arm, variant, altseq)
    for zone in ("primary", "quar"):
        for kind in KINDS:
            if (_kind_root(zone, kind) / sid / key).exists():
                return True
    return False


def _choose_altseq(
    idc: str,
    arm: str,
    variant: str,
    altseq,
) -> str:
    """altseq=None -> first free slot '0','1','2',... (the ``.{altseq}``
    disambiguation of §3.10.4); explicit altseq -> use it or refuse."""
    if altseq is not None:
        a = _check_altseq(altseq)
        if _slot_taken(idc, arm, variant, a):
            msg = (
                f"vault copy ({idc},{arm},{variant},{a}) already occupied — "
                "refusing to nest into an existing destination"
            )
            raise DestOccupied(msg)
        return a
    for i in range(10000):
        a = str(i)
        if not _slot_taken(idc, arm, variant, a):
            return a
    msg = f"no free altseq slot for ({idc},{arm},{variant})"
    raise VaultError(msg)


def _group_files(rows: list[dict]) -> dict:
    """[{kind,path,size,sha256}] -> {kind: [{path,size,sha256}]} for meta."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["kind"], []).append(
            {"path": r["path"], "size": r["size"], "sha256": r["sha256"]}
        )
    return out


def harvest(
    idc,
    arm,
    variant,
    assets: dict,
    source_run: str = "adhoc",
    altseq=None,
    verdict: str = "pending",
    zone=None,
    model=None,
    id=None,
    seq=None,
    staged: bool = False,
    sink=None,  # noqa: A002 -- id=/seq= 是事件行键名，调用方以 kwarg 传入
    run_dir=None,
    _op: str = "harvest",
) -> Path:
    """THE commit path — stage, fuse, rename, meta-last, manifest, emit.

    assets = {kind: src_dir} for kind in {zh,splice,state}. The whole write
    serializes through vault/.lock; asset events emit AFTER the lock drops.
    Returns the meta path (the commit marker).

    Refusals (all loud, nothing partially committed by a handled error):
    missing/non-dir source, non-regular files inside (links/fifos — the
    vault holds regular bytes only), all-empty asset trees, occupied
    destination (explicit altseq), missing sentinel, cross-device staging.
    """
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    verdict = _norm_verdict(verdict)
    zone = (
        _norm_zone(zone)
        if zone is not None
        else ("quar" if verdict == "quar" else "pending")
    )
    _require_sentinel()
    paths.assert_vault_same_volume()
    if not isinstance(assets, dict) or not assets:
        msg = "harvest needs a non-empty {kind: src_dir} dict"
        raise ValueError(msg)
    kinds = sorted(assets)
    unknown = set(kinds) - KINDS
    if unknown:
        msg = f"unknown asset kinds {sorted(unknown)} (allowed: {sorted(KINDS)})"
        raise ValueError(msg)
    srcs: dict[str, Path] = {}
    for k in kinds:
        src = Path(assets[k])
        if not src.is_dir():
            msg = f"asset {k} source is not a directory: {src}"
            raise VaultError(msg)
        offenders = _non_regular(src)
        if offenders:
            msg = (
                f"asset {k} holds non-regular files (vault stores regular "
                f"bytes only): {[str(o) for o in offenders[:5]]}"
            )
            raise VaultError(msg)
        files = _iter_files(src)
        if not files or all(p.stat().st_size == 0 for p, _ in files):
            msg = f"asset {k} carries no non-empty bytes: {src}"
            raise VaultError(msg)
        srcs[k] = src
    sid = idnorm.safe_id(idc)
    with locks.flock(paths.vault_lock_path(), exclusive=True):
        chosen = _choose_altseq(idc, arm, variant, altseq)
        key = dir_key(arm, variant, chosen)
        dests = {k: _kind_root(zone, k) / sid / key for k in kinds}
        paths.vault_staging_dir().mkdir(parents=True, exist_ok=True)
        tag = Path(
            tempfile.mkdtemp(
                prefix=f"hv-{sid[:32]}-", dir=str(paths.vault_staging_dir())
            )
        )
        mpath = meta_path(idc, arm, variant, chosen)
        moved: list[str] = []
        fused: dict[str, dict] = {}
        kind_bytes: dict[str, int] = {}
        try:
            rows: list[dict] = []
            for k in kinds:
                fsutil.hardlink_farm(srcs[k], tag / k)
                total = 0
                for p, rel in _iter_files(tag / k):
                    st = p.stat()
                    rows.append(
                        {
                            "kind": k,
                            "path": rel,
                            "size": st.st_size,
                            "sha256": fsutil._sha256_file(p),
                        }
                    )
                    total += st.st_size
                kind_bytes[k] = total
            rows.sort(key=lambda r: (r["kind"], r["path"]))
            blob = "".join(
                json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
                for r in rows
            ).encode("utf-8")
            asset_sha = hashlib.sha256(blob).hexdigest()
            fman = tag / _FILES_MANIFEST
            fman.write_bytes(blob)
            _fsync_file(fman)
            for k in kinds:
                fused[k] = _chmod_readonly_tree(tag / k, include_root=False)
                _fsync_tree(tag / k)
            fsutil.fsync_dir(tag)
            # rename() each kind dir into place — same volume, so each move
            # is atomic; a crash here leaves meta-less bytes (R4, sweep's).
            for k in kinds:
                dst = dests[k]
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.rename(tag / k, dst)
                # deferred root fuse — a 0555 source dir makes rename() fail
                # (the kernel rewrites its '..' entry on the move).
                st = dst.stat()
                os.chmod(dst, stat.S_IMODE(st.st_mode) & ~0o222)
                fsutil.fsync_dir(dst)
                _fsync_ancestors(dst.parent)
                moved.append(k)
            # meta is the commit marker — it lands LAST, durably.
            meta = {
                "v": 1,
                "idc": idc,
                "arm": arm,
                "variant": variant,
                "altseq": chosen,
                "zone": zone,
                "verdict": verdict,
                "asset_sha": asset_sha,
                "files": _group_files(rows),
                "kinds": kinds,
                "bytes": sum(kind_bytes.values()),
                "source_run": source_run,
                "staged": True,
                "ts": round(time.time(), 3),
            }
            if model is not None:
                meta["model"] = model
            _write_meta(mpath, meta)
            row = {
                "op": _op,
                "idc": idc,
                "arm": arm,
                "variant": variant,
                "altseq": chosen,
                "zone": zone,
                "verdict": verdict,
                "path": f"{sid}/{key}",
                "dirs": {k: _rel_leaf(zone, k, sid, key) for k in kinds},
                "kinds": kinds,
                "bytes": sum(kind_bytes.values()),
                "bytes_ok": True,
                "sha": asset_sha,
                "source_run": source_run,
                "ts": round(time.time(), 3),
            }
            if model is not None:
                row["model"] = model
            _append_manifest_locked(row)
            fsutil.fsync_dir(paths.vault_dir())
        except BaseException:
            # Best-effort rollback of the kinds we already moved — these are
            # files this harvest created seconds ago inside its own critical
            # section, so removing them is the self-cleaning direction. The
            # committed trees are already fused, so lift the fuse on dirs
            # first (rename-back of a 0555 dir fails on the '..' rewrite).
            for k in moved:
                _unfuse_dirs(dests[k])
                shutil.rmtree(dests[k], ignore_errors=True)
                # prune the {sid} parent iff this aborted commit left it empty
                with suppress(OSError):
                    dests[k].parent.rmdir()
            # Un-fuse the work-source inodes this commit fused — the tag
            # tree dies with staging, but the source-side aliases share the
            # inodes and would stay 0444 forever otherwise. Only nodes this
            # pass actually fused are restored, and only regular files: the
            # tag-side dirs were fresh inodes (the source's own dirs were
            # never touched) and a swapped-in symlink must not chmod a
            # foreign target.
            for k, changed in fused.items():
                for rel, mode in changed.items():
                    with suppress(OSError):
                        p = srcs[k] / rel
                        if stat.S_ISREG(os.lstat(p).st_mode):
                            os.chmod(p, mode)
            shutil.rmtree(tag, ignore_errors=True)
            raise
        shutil.rmtree(tag, ignore_errors=True)

    # Lock released — asset events never block the vault critical section on
    # the ledger lock. state: 'adopted' for quar-born copies, 'staged' for
    # secure-then-evict pre-staging, else 'pending'. seq may be a callable
    # (per-kind mint — a shared int would stamp duplicate (run_seq,seq)
    # keys and the index would drop every kind after the first).
    state = "adopted" if zone == "quar" else ("staged" if staged else "pending")
    seq_fn = seq if callable(seq) else (lambda: seq)
    for k in kinds:
        ev = events.make_event(
            events.T_ASSET,
            run=source_run,
            seq=seq_fn(),
            id=id or idc,
            idc=idc,
            arm=arm,
            variant=variant,
            kind=k,
            path=_rel_leaf(zone, k, sid, key),
            sha=asset_sha,
            bytes=kind_bytes[k],
            state=state,
            verdict=verdict,
            zone=zone,
            altseq=chosen,
        )
        ledger.emit(ev, run_dir=run_dir, sink=sink)
    return mpath


# --- promote (zone/verdict bookkeeping; quar moves bytes) ---------------------------


def promote(
    idc,
    arm,
    variant,
    altseq,
    zone,
    verdict,
    source_run: str = "reconcile",
    sink=None,
    run_dir=None,
) -> None:
    """pending -> primary|quar|alt (and quar -> primary|alt back).

    primary/alt are pure metadata zones — promote is a meta rewrite plus a
    manifest append row (zero byte I/O, last-row-wins per altseq). quar is
    the exception with a physical root, so crossing the quar boundary
    rename()s each declared kind dir between namespaces. Emits per-kind
    asset events (state='verified') afterwards so the index vault_meta
    projection learns the new verdict.
    """
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    altseq = _check_altseq(altseq)
    zone = _norm_zone(zone)
    verdict = _norm_verdict(verdict)
    _require_sentinel()
    sid = idnorm.safe_id(idc)
    key = dir_key(arm, variant, altseq)
    with locks.flock(paths.vault_lock_path(), exclusive=True):
        mpath = meta_path(idc, arm, variant, altseq)
        meta = _read_meta(mpath)
        if meta is None:
            msg = f"no parseable meta at {mpath} — nothing to promote"
            raise MetaMissing(msg)
        old_zone = _norm_zone(meta.get("zone", "pending"))
        moved: list[str] = []
        missing: list[str] = []
        try:
            if _zone_tag(old_zone) != _zone_tag(zone):
                for k in meta.get("files", {}):
                    src = _kind_root(old_zone, k) / sid / key
                    dst = _kind_root(zone, k) / sid / key
                    if not src.exists():
                        missing.append(k)
                        continue
                    if dst.exists():
                        msg = f"promote destination occupied: {dst}"
                        raise DestOccupied(msg)  # noqa: TRY301 -- raise 必须留在 try 内：except 回滚已搬动的 moved 集
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    # lift the root fuse so rename() may rewrite '..'
                    # (committed leaf dirs are 0555); re-fuse after landing.
                    st = src.stat()
                    os.chmod(src, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
                    os.rename(src, dst)
                    st = dst.stat()
                    os.chmod(dst, stat.S_IMODE(st.st_mode) & ~0o222)
                    fsutil.fsync_dir(dst)
                    _fsync_ancestors(dst.parent)
                    _fsync_ancestors(src.parent)
                    moved.append(k)
                if missing and not moved:
                    msg = (
                        f"promote {idc}/{arm}/{variant}/{altseq}: every "
                        f"declared kind missing under {old_zone} "
                        f"({missing}) — nothing to move"
                    )
                    raise VaultError(msg)  # noqa: TRY301 -- 同上：触发回滚的中止点
        except BaseException:
            for k in moved:
                dst = _kind_root(zone, k) / sid / key
                src = _kind_root(old_zone, k) / sid / key
                with suppress(OSError):
                    st = dst.stat()
                    os.chmod(dst, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
                    os.rename(dst, src)
                    st = src.stat()
                    os.chmod(src, stat.S_IMODE(st.st_mode) & ~0o222)
            raise
        meta["zone"] = zone
        meta["verdict"] = verdict
        meta["prev_zone"] = old_zone
        meta["ts"] = round(time.time(), 3)
        _write_meta(mpath, meta)
        _append_manifest_locked(
            {
                "op": "promote",
                "idc": idc,
                "arm": arm,
                "variant": variant,
                "altseq": altseq,
                "zone": zone,
                "verdict": verdict,
                "from_zone": old_zone,
                "path": f"{sid}/{key}",
                "moved": moved,
                "missing": missing,
                "bytes_ok": _copy_intact(meta),
                "source_run": source_run,
                "ts": round(time.time(), 3),
            }
        )
    for k in meta.get("files", {}):
        ev = events.make_event(
            events.T_ASSET,
            run=source_run,
            seq=None,
            id=idc,
            idc=idc,
            arm=arm,
            variant=variant,
            kind=k,
            path=_rel_leaf(zone, k, sid, key),
            sha=meta.get("asset_sha"),
            state="verified",
            verdict=verdict,
            zone=zone,
            altseq=altseq,
        )
        ledger.emit(ev, run_dir=run_dir, sink=sink)


# --- dedup criterion ---------------------------------------------------------------


def _copy_intact(meta: dict) -> bool:
    """Physical intactness of one copy: meta's declared kinds each resolve
    to a dir under the meta's zone root, every declared file is present,
    regular, and size-exact, and each kind holds >0 bytes of content."""
    try:
        zone = _norm_zone(meta.get("zone", "pending"))
        files = meta["files"]
        idc = _check_idc(meta["idc"])
        arm = _comp(meta.get("arm"))
        variant = _comp(meta.get("variant"))
        altseq = str(meta.get("altseq", "0"))
        sid = idnorm.safe_id(idc)
        key = dir_key(arm, variant, altseq)
    except (KeyError, TypeError, ValueError):
        return False
    if not isinstance(files, dict) or not files:
        return False
    for kind, flist in files.items():
        if kind not in KINDS or not isinstance(flist, list) or not flist:
            return False
        leaf = _kind_root(zone, kind) / sid / key
        if not leaf.is_dir():
            return False
        has_bytes = False
        for ent in flist:
            rel = _safe_rel(ent.get("path") if isinstance(ent, dict) else None)
            if rel is None:
                return False
            try:
                st = (leaf / rel).stat()
            except OSError:
                return False
            if not stat.S_ISREG(st.st_mode):
                return False
            if st.st_size != ent.get("size"):
                return False
            if st.st_size > 0:
                has_bytes = True
        if not has_bytes:
            return False
    return True


def bytes_ok(idc, arm, variant, altseq=None) -> bool:
    """THE physical dedup criterion: some matching copy has a parseable meta
    AND every asset it declares present non-empty on disk. Directory
    existence NEVER counts. Verdict policy is NOT applied here — see
    dedup_hit() for the §3.8 composition."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    for _mp, key, meta in _iter_metas():
        if key is None or meta is None:
            continue
        if key[:3] != (idc, arm, variant):
            continue
        if altseq is not None and key[3] != str(altseq):
            continue
        if _copy_intact(meta):
            return True
    return False


def dedup_hit(idc, arm, variant) -> bool:
    """§3.8 dedup oracle: an intact copy whose verdict dedups
    (primary|alt|quar|adopted|verified). pending and tombstone copies do
    not count — the claim lock-recheck and regen gate own those states."""
    for row in query(idc, arm, variant):
        if row.get("_parse_error") or row.get("verdict") not in DEDUP_VERDICTS:
            continue
        if row["bytes_ok"]:
            return True
    return False


def query(idc, arm: str = "*", variant: str = "*") -> list[dict]:
    """All copies (metas) for a cell — '*' wildcards on arm/variant.
    Rows are the meta content plus filename-authoritative idc/arm/variant/
    altseq, meta_path, bytes_ok (physical intactness), and _parse_error on
    corrupt metas. Sorted by (altseq, name)."""
    idc = _check_idc(idc)
    rows = []
    for mp, key, meta in _iter_metas():
        if key is None:
            continue
        kidc, karm, kvar, kalt = key
        if kidc != idc:
            continue
        if arm not in ("*", karm):
            continue
        if variant not in ("*", kvar):
            continue
        row = dict(meta) if meta is not None else {}
        row.update(
            {
                "idc": kidc,
                "arm": karm,
                "variant": kvar,
                "altseq": kalt,
                "meta_path": str(mp),
            }
        )
        if meta is None:
            row["_parse_error"] = True
            row["bytes_ok"] = False
        else:
            row["bytes_ok"] = _copy_intact(meta)
        rows.append(row)
    rows.sort(key=lambda r: (r["altseq"], r["meta_path"]))
    return rows


def pending_metas() -> list[dict]:
    """Metas still in zone='pending' — the sweep's promote queue."""
    out = []
    for mp, key, meta in _iter_metas():
        if key is None or meta is None:
            continue
        if meta.get("zone") == "pending":
            row = dict(meta)
            row.update(
                {
                    "idc": key[0],
                    "arm": key[1],
                    "variant": key[2],
                    "altseq": key[3],
                    "meta_path": str(mp),
                }
            )
            out.append(row)
    return out


# --- verify / heal ------------------------------------------------------------------


def verify(level: str = "stat", sample_frac: float = 0.05, seed=None) -> dict:
    """Three-tier vault check (§3.10.4), under a shared vault lock.

    stat   — meta parseable + declared files exist + sizes match
    sample — stat + sha256 rehash of a sample_frac fraction of inodes
    full   — stat + sha256 rehash of every inode

    Inode-aggregated: files sharing an inode are checked once and a single
    bad inode marks every alias (shared inode corrupts all aliases — the
    "位腐连坐" reversal is deliberate). Returns {level, metas, checked,
    inodes, bad:[{paths,reason,sha,inode}], meta_missing:[dirs with no
    covering meta], meta_bad:[unparseable/credential-mismatched metas],
    extra:[unmanifested files inside covered dirs]}."""
    if level not in ("stat", "sample", "full"):
        msg = f"bad verify level {level!r}"
        raise ValueError(msg)
    rng = random.Random(seed)
    with locks.flock(paths.vault_lock_path(), exclusive=False):
        return _verify_scan(level, sample_frac, rng)


def _verify_scan(level: str, sample_frac: float, rng) -> dict:
    report = {
        "level": level,
        "metas": 0,
        "checked": 0,
        "inodes": 0,
        "bad": [],
        "meta_missing": [],
        "meta_bad": [],
        "extra": [],
    }
    inode_map: dict[tuple, list] = {}
    covered_leaves: list[tuple[Path, set]] = []
    for mp, key, meta in _iter_metas():
        report["metas"] += 1
        if key is None or meta is None:
            report["meta_bad"].append(str(mp))
            continue
        kidc, karm, kvar, kalt = key
        # the filename is the credential — content must agree with it
        if (
            meta.get("idc") != kidc
            or _comp(meta.get("arm")) != karm
            or _comp(meta.get("variant")) != kvar
            or str(meta.get("altseq", "0")) != kalt
        ):
            report["meta_bad"].append(str(mp))
            continue
        try:
            zone = _norm_zone(meta.get("zone", "pending"))
        except ValueError:
            report["meta_bad"].append(str(mp))
            continue
        files = meta.get("files")
        if not isinstance(files, dict):
            report["meta_bad"].append(str(mp))
            continue
        sid = idnorm.safe_id(kidc)
        k = dir_key(karm, kvar, kalt)
        for kind, flist in files.items():
            if kind not in KINDS or not isinstance(flist, list):
                report["meta_bad"].append(str(mp))
                continue
            leaf = _kind_root(zone, kind) / sid / k
            declared: set = set()
            for ent in flist:
                if not isinstance(ent, dict):
                    continue
                report["checked"] += 1
                rel = _safe_rel(ent.get("path"))
                if rel is None:
                    report["bad"].append(
                        {
                            "paths": [str(leaf / str(ent.get("path")))],
                            "reason": "unsafe_declared_path",
                            "sha": [ent.get("sha256")],
                            "inode": None,
                        }
                    )
                    continue
                declared.add(rel)
                fp = leaf / rel
                try:
                    st = fp.stat()
                except OSError:
                    report["bad"].append(
                        {
                            "paths": [str(fp)],
                            "reason": "missing",
                            "sha": [ent.get("sha256")],
                            "inode": None,
                        }
                    )
                    continue
                if not stat.S_ISREG(st.st_mode):
                    report["bad"].append(
                        {
                            "paths": [str(fp)],
                            "reason": "non_regular",
                            "sha": [ent.get("sha256")],
                            "inode": None,
                        }
                    )
                    continue
                inode_map.setdefault((st.st_dev, st.st_ino), []).append((fp, ent))
            covered_leaves.append((leaf, declared))
    # one check per inode; a bad inode damns every alias at once
    for (dev, ino), aliases in sorted(inode_map.items()):
        report["inodes"] += 1
        st = aliases[0][0].stat()
        expected = {ent.get("sha256") for _p, ent in aliases}
        size_bad = any(st.st_size != ent.get("size") for _p, ent in aliases)
        sha_bad = False
        if (
            not size_bad
            and level != "stat"
            and (level == "full" or rng.random() < sample_frac)
        ):
            sha_bad = fsutil._sha256_file(aliases[0][0]) not in expected
        if size_bad or sha_bad:
            report["bad"].append(
                {
                    "paths": [str(p) for p, _e in aliases],
                    "reason": "size_mismatch" if size_bad else "sha_mismatch",
                    "sha": sorted(s for s in expected if s),
                    "inode": [dev, ino],
                }
            )
    for leaf, declared in covered_leaves:
        if not leaf.is_dir():
            continue
        for p, rel in _iter_files(leaf):
            if rel not in declared:
                report["extra"].append(str(p))
    report["meta_missing"] = [str(p) for p in _scan_meta_less_dirs()]
    return report


def heal(verify_report: dict | None = None) -> int:
    """Re-link vault paths that verify() marked bad to a good donor inode
    carrying the declared sha (§3.10.4 single-file self-heal).

    All vault aliases of a bad inode are re-linked together — a single-path
    rename-replace on a shared inode would leave sibling aliases corrupt.
    Exactly one distinct good donor inode may carry the sha: zero -> skip
    (unhealable), >1 -> AmbiguousDonor (sha-binding ambiguity must refuse).
    Returns the number of paths re-linked."""
    _require_sentinel()
    if verify_report is None:
        verify_report = verify("full")
    with locks.flock(paths.vault_lock_path(), exclusive=True):
        donors = _donor_map()
        touched: set = set()
        healed = 0
        for bad in verify_report.get("bad", []):
            if bad.get("reason") not in ("sha_mismatch", "size_mismatch", "missing"):
                continue
            shas = [s for s in (bad.get("sha") or []) if s]
            if len(set(shas)) != 1:
                continue  # nothing or ambiguous expected — not relink-healable
            want = shas[0]
            bad_ino = tuple(bad["inode"]) if bad.get("inode") else None
            cands = {
                ino: p for ino, p in donors.get(want, {}).items() if ino != bad_ino
            }
            if len(cands) > 1:
                msg = (
                    f"multiple good inodes carry sha {want[:16]}… — refusing "
                    "to pick (§3.10.4 sha-binding ambiguity)"
                )
                raise AmbiguousDonor(msg)
            if not cands:
                continue
            donor_path = next(iter(cands.values()))
            for path_str in bad["paths"]:
                target = Path(path_str)
                _lift_fuse(target.parent, touched)
                tmp = target.parent / (target.name + _HEAL_TMP_SUFFIX)
                with suppress(FileNotFoundError):
                    tmp.unlink()
                os.link(donor_path, tmp)
                os.replace(tmp, target)
                healed += 1
        for d in touched:
            st = d.stat()
            os.chmod(d, stat.S_IMODE(st.st_mode) & ~0o222)
            fsutil.fsync_dir(d)
        return healed


def _lift_fuse(d: Path, touched: set) -> None:
    """Make dir ``d`` (creating any missing ancestors) writable for dirent
    surgery; record dirs that must be (re-)fused afterwards — a previously
    fused existing dir that we lifted, or the surgery dir itself when it had
    to be recreated (it is a committed leaf). Intermediate namespace dirs
    ({kind}, {sid}) recreated along the way stay at the default 0755 — fusing
    them would block future commits into that subtree."""
    missing = []
    cur = d
    while not cur.exists():
        missing.append(cur)
        cur = cur.parent
    st = cur.stat()
    if not st.st_mode & stat.S_IWUSR:
        os.chmod(cur, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
        touched.add(cur)
    for sub in reversed(missing):
        sub.mkdir()
    if missing:
        touched.add(missing[0])  # missing[0] == d: the recreated leaf dir


def _donor_map() -> dict:
    """actual_sha -> {(dev,ino): path} over declared vault files that pass
    their own check — the only bytes trustworthy enough to heal with."""
    out: dict[str, dict] = {}
    seen: dict[tuple, str] = {}
    for _mp, key, meta in _iter_metas():
        if key is None or meta is None:
            continue
        try:
            zone = _norm_zone(meta.get("zone", "pending"))
        except ValueError:
            continue
        files = meta.get("files")
        if not isinstance(files, dict):
            continue
        sid = idnorm.safe_id(key[0])
        k = dir_key(key[1], key[2], key[3])
        for kind, flist in files.items():
            if kind not in KINDS or not isinstance(flist, list):
                continue
            leaf = _kind_root(zone, kind) / sid / k
            for ent in flist:
                rel = _safe_rel(ent.get("path") if isinstance(ent, dict) else None)
                if rel is None:
                    continue
                fp = leaf / rel
                try:
                    st = fp.stat()
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                ino = (st.st_dev, st.st_ino)
                if ino not in seen:
                    seen[ino] = fsutil._sha256_file(fp)
                actual = seen[ino]
                if actual != ent.get("sha256"):
                    continue  # donor must be GOOD against its own declaration
                out.setdefault(actual, {})[ino] = fp
    return out


# --- adopt / restore / tombstone / orphan scan ---------------------------------------


def adopt(
    src_dir,
    idc,
    arm: str = "-",
    variant: str = "-",
    reason: str = "orphan",
    kind: str = "zh",
    id=None,  # noqa: A002 -- 事件行键名
    sink=None,
    run_dir=None,
) -> Path:
    """Orphan bytes -> quarantine. The whole tree becomes one quar-zone copy
    via the normal two-phase commit (verdict='quar', state='adopted'), then
    a note event records the adoption. Refuses non-regular files — a stray
    fifo or symlink never enters the vault."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    if kind not in KINDS:
        msg = f"adopt kind must be one of {sorted(KINDS)}, got {kind!r}"
        raise ValueError(msg)
    src = Path(src_dir)
    if not src.is_dir():
        msg = f"adopt source is not a directory: {src}"
        raise VaultError(msg)
    offenders = _non_regular(src)
    if offenders:
        msg = f"adopt refuses non-regular files: {[str(o) for o in offenders[:5]]}"
        raise VaultError(msg)
    mpath = harvest(
        idc,
        arm,
        variant,
        {kind: src},
        source_run="adopt",
        verdict="quar",
        zone="quar",
        id=id,
        sink=sink,
        run_dir=run_dir,
        _op="adopt",
    )
    meta = _read_meta(mpath) or {}
    ev = events.make_event(
        events.T_NOTE,
        run="adopt",
        seq=None,
        id=id or idc,
        idc=idc,
        text=(
            f"adopted orphan bytes {src} -> vault quar "
            f"({idc},{arm},{variant},{meta.get('altseq', '0')}) "
            f"reason={reason}"
        ),
        level="warn",
    )
    ledger.emit(ev, run_dir=run_dir, sink=sink)
    return leaf_dir("quar", kind, idc, arm, variant, meta.get("altseq", "0"))


def restore(idc, arm, variant, dest, altseq=None, mode: str = "copy") -> int:
    """vault -> work materialization of the best intact copy.

    Picks the first intact copy by zone preference (primary > alt > quar >
    pending), then materializes each declared kind under
    ``dest/{kind}.{arm}[@{variant}]/``:

    - mode='copy' (default): fsutil.copy_mutating — fresh owner-writable
      bytes; the safe choice for mutating consumers (fixloop/replay would
      otherwise hit the 0444 fuse as EACCES).
    - mode='link': fsutil.hardlink_farm — zero-copy sharing of the vault
      inodes, which stay read-only. CALLER CONTRACT: read-only consumers
      only; a mutating consumer gets a loud EACCES, never silent poisoning.

    Raises VaultError when no intact copy exists — damaged credentials are
    restored only by explicit operator handling, never silently."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    if mode not in ("copy", "link"):
        msg = f"restore mode must be 'copy'|'link', got {mode!r}"
        raise ValueError(msg)
    _require_sentinel()
    dest = Path(dest)
    with locks.flock(paths.vault_lock_path(), exclusive=False):
        meta = _select_copy(idc, arm, variant, altseq)
        if meta is None:
            msg = f"no intact committed copy for ({idc},{arm},{variant},{altseq})"
            raise VaultError(msg)
        zone = _norm_zone(meta.get("zone", "pending"))
        sid = idnorm.safe_id(idc)
        key = dir_key(arm, variant, meta.get("altseq", "0"))
        made = 0
        for kind in meta.get("files", {}):
            src = _kind_root(zone, kind) / sid / key
            d = dest / _work_dirname(kind, arm, variant)
            if mode == "link":
                fsutil.hardlink_farm(src, d)
            else:
                fsutil.copy_mutating(src, d)
            made += len(_iter_files(d))
        return made


def _select_copy(idc: str, arm: str, variant: str, altseq) -> dict | None:
    """Best intact copy for restore: exact altseq when given, else by zone
    preference then lowest altseq."""
    cands = []
    for _mp, key, meta in _iter_metas():
        if key is None or meta is None or key[:3] != (idc, arm, variant):
            continue
        if altseq is not None and key[3] != str(altseq):
            continue
        try:
            z = _norm_zone(meta.get("zone", "pending"))
        except ValueError:
            continue
        if not _copy_intact(meta):
            continue
        cands.append((_ZONE_RANK.get(z, 4), key[3], meta))
    if not cands:
        return None
    cands.sort(key=lambda t: (t[0], t[1]))
    return cands[0][2]


def tombstone(
    idc,
    arm,
    variant,
    kind,
    reason,
    lost_run: str = "",
    id=None,
    sink=None,
    run_dir=None,
) -> None:  # noqa: A002 -- 事件行键名
    """Register lost bytes: a manifest tombstone row inside the vault lock,
    then a first-class tombstone event in the ledger (§3.1 — tombstones are
    events, not separate files). The regen gate reads these rows upstream."""
    idc = _check_idc(idc)
    arm = _comp(arm)
    variant = _comp(variant)
    _require_sentinel()
    ts = round(time.time(), 3)
    with locks.flock(paths.vault_lock_path(), exclusive=True):
        _append_manifest_locked(
            {
                "op": "tombstone",
                "idc": idc,
                "arm": arm,
                "variant": variant,
                "kind": kind,
                "reason": reason,
                "lost_run": lost_run,
                "zone": "tombstone",
                "ts": ts,
            }
        )
    ev = events.make_event(
        events.T_TOMBSTONE,
        id=id or idc,
        idc=idc,
        arm=arm,
        variant=variant,
        kind=kind,
        reason=reason,
        lost_run=lost_run,
        ts=ts,
    )
    ledger.emit(ev, run_dir=run_dir, sink=sink)


def find_meta_less_dirs() -> list[Path]:
    """Orphan detector: leaf dirs under the kind roots (primary AND quar
    namespaces) with no covering meta — the R4 crash window made visible.

    REPORT ONLY — deletion is deliberately not here. The hardened delete
    predicate (sibling metas + manifest alt rows + age + dedup-domain check)
    belongs to the sweep; this just enumerates candidates under a shared
    vault lock."""
    with locks.flock(paths.vault_lock_path(), exclusive=False):
        return _scan_meta_less_dirs()


def _scan_meta_less_dirs() -> list[Path]:
    covered = set()
    for _mp, key, meta in _iter_metas():
        if key is None or meta is None:
            continue
        try:
            zone = _norm_zone(meta.get("zone", "pending"))
        except ValueError:
            continue
        files = meta.get("files")
        if not isinstance(files, dict):
            continue
        sid = idnorm.safe_id(key[0])
        k = dir_key(key[1], key[2], key[3])
        for kind in files:
            covered.add((_zone_tag(zone), kind, sid, k))
    out = []
    for tag in ("primary", "quar"):
        for kind in sorted(KINDS):
            root = _kind_root("quar" if tag == "quar" else "primary", kind)
            if not root.is_dir():
                continue
            for sid_d in sorted(root.iterdir()):
                if not sid_d.is_dir():
                    continue
                for leaf in sorted(sid_d.iterdir()):
                    if not leaf.is_dir():
                        continue
                    if (tag, kind, sid_d.name, leaf.name) not in covered:
                        out.append(leaf)
    return out
