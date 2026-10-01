"""kernel.vault._verify — 三档校验 + 单文件自愈 (kernel.vault 拆分叶).

``verify``: stat (meta 可解析 + 声明件在+size 合) / sample (+抽样 sha256
复算) / full (全 inode 复算), SH 锁下进行。inode 聚合判定——共享 inode
只查一次，一个坏 inode 连坐全部别名 (位腐连坐是有意反向)。

``heal``: 坏别名重链到携带声明 sha 的唯一好 donor inode (§3.10.4 单文件
自愈)——同 inode 的全部别名一起重链 (单径 rename-replace 会把兄弟别名
留腐); 恰好一个好 donor 才动手，0→skip, >1→AmbiguousDonor。
"""

from __future__ import annotations

import os
import random
import stat
from contextlib import suppress
from pathlib import Path

from kernel import fsutil, idnorm, locks, paths
from kernel.vault.cred import (
    KINDS,
    AmbiguousDonor,
    _comp,
    _kind_root,
    _norm_zone,
    dir_key,
)
from kernel.vault.intact import _safe_rel
from kernel.vault.io import (
    _iter_files,
    _iter_metas,
    _require_sentinel,
)
from kernel.vault.retention import _scan_meta_less_dirs

_HEAL_TMP_SUFFIX = ".heal-tmp"


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
