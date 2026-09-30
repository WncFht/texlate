"""kernel._vault_intact — 副本完好/产物在场代数 (kernel.vault 拆分叶).

A commit marker + intact declared bytes prove a copy EXISTS; they do NOT
prove the copy carries the product it is supposed to display. fixloop-dedup
and quick-terminal harvests seal pdf-less splice workspaces (fig*.pdf assets
only, or no pdf at all), and record-level verdicts then vouch them as
product (qc no_pdf 普查 ~97 格根因). ``_copy_product_ok`` is the single
source of truth; consumers gate/rank on it instead of trusting the verdict
alone.

四组判定：``_copy_intact``/``_kind_intact`` (声明件 size 精确全在),
``_copy_file_rels``/``_copy_product_*`` (zh=.tex 树，splice=编译成品 pdf),
``_pdf_intact``/``_product_pdf_rels``/``_corrupt_product_pdfs`` (收割封口
闸——pdf_corrupt 类的截断/异物字节永不入库), ``_safe_rel`` (meta 声明径
卫生——损 meta 不得把 verify/restore 引到叶外)。
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

from kernel import idnorm
from kernel._vault_cred import (
    KINDS,
    _check_idc,
    _comp,
    _kind_root,
    _norm_zone,
    dir_key,
)
from kernel._vault_io import _iter_files

#: Kinds with a product notion — zh's product is the translated .tex tree,
#: splice's is the compiled paper pdf. state/layoutqc leaves are payload dirs
#: (state.json/qc.json) with no further product concept.
_PRODUCT_KINDS = frozenset({"zh", "splice"})

#: Root-level pdf stems carrying these prefixes are figure assets, not the
#: compiled paper (the fig-only seal shape — e.g. a splice leaf holding
#: fig1..fig18.pdf and no product pdf counts as product-LESS).
_FIGISH_STEM_RE = re.compile(r"(?:fig|plot|pic)", re.IGNORECASE)


def _copy_file_rels(src, kind: str) -> list[str] | None:
    """posix-rel paths of one kind inside a copy — None when the kind is
    absent/unresolvable.

    ``src`` accepts either a vault meta dict (its ``files`` declaration is
    consulted — callers pair it with ``_copy_intact``/``bytes_ok`` for
    physicality) or a filesystem dir (vault leaf / restored work dir),
    scanned live. Read-only; no writes."""
    if isinstance(src, dict):
        files = src.get("files")
        flist = files.get(kind) if isinstance(files, dict) else None
        if not isinstance(flist, list) or not flist:
            return None
        return [
            e["path"]
            for e in flist
            if isinstance(e, dict) and isinstance(e.get("path"), str) and e["path"]
        ]
    d = Path(src)
    if not d.is_dir():
        return None
    return [rel for _p, rel in _iter_files(d)]


def _copy_product_ok(src, kind: str) -> tuple[bool, str]:
    """(ok, reason) — the copy's ``kind`` dir actually holds product bytes.

    splice  product = a compiled-paper pdf: a ``.pdf`` whose stem matches a
            declared ``.tex`` stem (the ``_splice_keep`` final-pdf rule —
            also rescues nested/fig-named pairs), else a ROOT-level ``.pdf``
            whose stem is not fig/plot/pic-prefixed (``.fixloop-entry.pdf``
            floor snapshots and meta-skew names like ``MQD_Manuscript.pdf``
            count here; ``fig*.pdf`` figure assets and ``figures/*.pdf``
            nested assets do not).
    zh      product = >=1 declared ``.tex`` (the translated source tree).
    others  no product notion — always (True, "na"); those copies can only
            ever be judged by intactness.
    """
    rels = _copy_file_rels(src, kind)
    if rels is None:
        return False, "kind_absent"
    if kind == "zh":
        if any(r.endswith(".tex") for r in rels):
            return True, "tex"
        return False, "no_tex"
    if kind == "splice":
        tex_stems = {
            r.rsplit("/", 1)[-1][: -len(".tex")] for r in rels if r.endswith(".tex")
        }
        root_pdf = False
        for r in rels:
            if not r.endswith(".pdf"):
                continue
            stem = r.rsplit("/", 1)[-1][: -len(".pdf")]
            if stem in tex_stems:
                return True, "stem_match"
            if "/" not in r and not _FIGISH_STEM_RE.match(stem):
                root_pdf = True
        return (True, "root_pdf") if root_pdf else (False, "no_product_pdf")
    return True, "na"


def _copy_product_bad(meta: dict) -> int:
    """Number of declared product-kinds that are product-less — the ranking
    penalty a copy pays for sealing a shell (0 = every declared product kind
    carries its product; a state-only leaf declares no product kinds at all
    and scores 0 — its payload IS its product)."""
    files = meta.get("files")
    if not isinstance(files, dict):
        return 0
    return sum(
        1 for k in files if k in _PRODUCT_KINDS and not _copy_product_ok(meta, k)[0]
    )


def _pdf_intact(path: Path) -> tuple[bool, str]:
    """(ok, reason) — tolerant structural check on a .pdf payload: ``%PDF-``
    magic at offset 0 plus ``startxref``/``%%EOF`` inside the last ~1 KiB.
    Not a parser — it only proves the bytes are a complete pdf rather than
    a truncated/torn write or foreign content (the pdf_corrupt class:
    killed compiles sealed half-written product pdfs)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if fh.read(5) != b"%PDF-":
                return False, "bad_header"
            fh.seek(max(0, size - 1024))
            tail = fh.read()
    except OSError:
        return False, "unreadable"
    if b"%%EOF" not in tail:
        return False, "no_eof"
    if b"startxref" not in tail:
        return False, "no_startxref"
    return True, "ok"


def _product_pdf_rels(kind: str, rels: list[str]) -> list[str]:
    """rels subset that is the kind's DELIVERABLE pdf — exactly the files
    ``_copy_product_ok`` would vouch as splice product (stem-matched to a
    declared .tex, else root-level non-figish). Only splice has a pdf
    product notion: zh's product is the .tex tree — its pdf payloads are
    source cargo (arXiv tarballs routinely ship stray author pdfs) and
    gating them would refuse paid bytes over dead cargo, looping regen on
    corrupt-at-source quirks."""
    if kind != "splice":
        return []
    tex_stems = {
        r.rsplit("/", 1)[-1][: -len(".tex")] for r in rels if r.endswith(".tex")
    }
    out = []
    for r in rels:
        if not r.endswith(".pdf"):
            continue
        stem = r.rsplit("/", 1)[-1][: -len(".pdf")]
        if stem in tex_stems or ("/" not in r and not _FIGISH_STEM_RE.match(stem)):
            out.append(r)
    return out


def _corrupt_product_pdfs(kind: str, files: list[tuple[Path, str]]) -> list[dict]:
    """[{path, reason}] for deliverable pdfs failing ``_pdf_intact`` — the
    seal-time acceptance gate."""
    by_rel = {rel: p for p, rel in files}
    out = []
    for rel in _product_pdf_rels(kind, [rel for _p, rel in files]):
        ok, why = _pdf_intact(by_rel[rel])
        if not ok:
            out.append({"path": rel, "reason": why})
    return out


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


def _kind_intact(meta: dict, kind: str) -> bool:
    """``_copy_intact`` 的单 kind 版——rekey 按 kind 子集搬，只看目标 kind
    的声明件是否全在且 size 精确。"""
    if kind in (meta.get("tombstoned_kinds") or ()):
        return False
    try:
        zone = _norm_zone(meta.get("zone", "pending"))
        idc = _check_idc(meta["idc"])
        arm = _comp(meta.get("arm"))
        variant = _comp(meta.get("variant"))
        altseq = str(meta.get("altseq", "0"))
        flist = meta["files"][kind]
    except (KeyError, TypeError, ValueError):
        return False
    if not isinstance(flist, list) or not flist:
        return False
    leaf = _kind_root(zone, kind) / idnorm.safe_id(idc) / dir_key(arm, variant, altseq)
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
        if not stat.S_ISREG(st.st_mode) or st.st_size != ent.get("size"):
            return False
        if st.st_size > 0:
            has_bytes = True
    return has_bytes
