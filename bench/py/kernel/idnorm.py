"""arXiv id normalization — single-resolution rule (design §3.7, §3.10.7).

canon = the spelling arXiv minted:

    old-style  ``archive/YYMMNNN``   (renamed archives keep their ORIGINAL
        spelling — ``q-alg/9703043`` is canon; the official rename map
        q-alg→math.QA exists for matching, never for rewriting)
    new-style  ``YYMM.NNNNN``        (5-digit suffix today; the 4-digit
        suffixes arXiv minted 2007-2014 are also canon and accepted)

``cat--id`` (double dash) is ONLY the fs encoding (safe_id) — never a valid
id spelling inside a field. canon_id decodes it first, then re-validates,
so ``cond-mat--9601002`` resolves to ``cond-mat/9601002``.

Bare 7-digit tails (``YYMMNNN``) are never guessed: only the PapersRegistry
may resolve them — |cats|=0 → invalid, |cats|≥2 → ambig, |cats|=1 → ok only
when the tail is backed by a tracked source (corpus manifest / idresolve /
human override). A local single cat is not proof of global uniqueness —
a wrong cat means translating the wrong paper on paid quota.

Read side intentionally does NOT normalize (§3.7): triage's non-canon
matches are an audit signal — wave-5's 253 missed cells were caught by it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .events import iter_jsonl

OK = "ok"
AMBIG = "ambig"
INVALID = "invalid"

# Repo checkout root (…/bench/py/kernel/idnorm.py -> parents[3]). Used as the
# default manifest source for PapersRegistry.load().
REPO_ROOT = Path(__file__).resolve().parents[3]

# Renamed arXiv archives: OLD minted spelling -> official NEW name.
# (§3.10.7 pins q-alg→math.QA, correcting §3.1's "q-alg→quant-ph" wording.)
ARCHIVE_RENAMED: dict[str, str] = {
    "q-alg": "math.QA",
    "alg-geom": "math.AG",
    "dg-ga": "math.DG",
    "funct-an": "math.FA",
    "chao-dyn": "nlin.CD",
    "cmp-lg": "cs.CL",
    "adap-org": "nlin.AO",
    "comp-gas": "nlin.CG",
    "patt-sol": "nlin.PS",
    "solv-int": "nlin.SI",
    "chem-ph": "physics.chem-ph",
    "atom-ph": "physics.atom-ph",
    "acc-phys": "physics.acc-ph",
    "ao-sci": "physics.ao-ph",
    "bayes-an": "physics.data-an",
    "mtrl-th": "cond-mat.mtrl-sci",
    "plasm-ph": "physics.plasm-ph",
    "supr-con": "cond-mat.supr-con",
}
_NEW_TO_OLD = {new: old for old, new in ARCHIVE_RENAMED.items()}

# Shape validators. [0-9] not \d — unicode digits must not leak into canon.
_CAT_RE = re.compile(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*")
_NUM_OLD_RE = re.compile(r"[0-9]{7,9}")  # YYMM(4) + NNN(3..5)
_NEW_RE = re.compile(r"[0-9]{4}\.[0-9]{4,5}")  # YYMM.NNNNN (4-digit legacy ok)
_BARE_RE = re.compile(r"[0-9]{7}")  # YYMMNNN tail — registry only
_VER_RE = re.compile(r"v[0-9]+$")

# Fixture/scratch namespaces that shape-validate but are not arXiv archives
# (e.g. "fixture/0101001"). Leading-dot forms like ".bak-mock/…" already fail
# the charset; these need an explicit deny.
_DENY_CATS = frozenset(
    {
        "fixture",
        "fixtures",
        "mock",
        "mocks",
        "test",
        "tests",
        "dummy",
        "example",
        "examples",
        "sample",
        "samples",
        "debug",
        "tmp",
        "meta",
    }
)
_DENY_SUFFIXES = ("-mock", "-fixture", "-test")

# Sources that prove a bare tail's cat is arXiv-real — required for the
# |cats|=1 -> ok gate. Ledger/vault/manual rows are untrusted breadth only.
TRACKED_SRC = frozenset({"manifest", "idresolve", "override"})


@dataclass(frozen=True)
class CanonResult:
    """Outcome of canon_id. state: 'ok' | 'ambig' | 'invalid'.

    idc        canon id when state == 'ok', else None
    candidates possible canon spellings when state == 'ambig'
    reason     short machine-stable explanation tag
    ver        stripped vN suffix (with 'v') when the input carried one
    """

    state: str
    idc: str | None = None
    candidates: list = field(default_factory=list)
    reason: str = ""
    ver: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == OK


def strip_ver(s: str) -> tuple[str, str | None]:
    """Peel a trailing vN version suffix -> (base, 'vN' | None)."""
    m = _VER_RE.search(s)
    if not m:
        return s, None
    return s[: m.start()], m.group(0)


def safe_id(idc: str) -> str:
    """fs encoding of a canon id: '/' -> '--'."""
    return idc.replace("/", "--")


def idc_from_safe(sid: str) -> str:
    """Decode a safe_id: the LAST '--' becomes '/' (the separator is the
    final double dash; single dashes inside the cat stay)."""
    head, sep, tail = sid.rpartition("--")
    if not sep:
        return sid
    return f"{head}/{tail}"


def escape_component(s: str) -> str:
    """Escape one component (arm/variant/altseq) for vault meta filenames:
    '%' -> %25 first, then '.' -> %2E, '@' -> %40."""
    return s.replace("%", "%25").replace(".", "%2E").replace("@", "%40")


def unescape_component(s: str) -> str:
    """Inverse of escape_component. %2E/%40 must decode BEFORE %25 so a
    literal '%40' in the source (stored as %2540) cannot double-decode."""
    return s.replace("%2E", ".").replace("%40", "@").replace("%25", "%")


def _mm_ok(yymm: str) -> bool:
    """YYMM month sanity: chars 3-4 must be 01..12."""
    mm = int(yymm[2:4])
    return 1 <= mm <= 12


def _cat_ok(cat: str) -> bool:
    if not _CAT_RE.fullmatch(cat):
        return False
    c = cat.lower()
    return not (c in _DENY_CATS or c.endswith(_DENY_SUFFIXES))


def _form_of(t: str) -> tuple | None:
    """Shape validation of a normalized token.

    -> ('old', cat, num) | ('new',) | None
    """
    if "/" in t:
        cat, _, num = t.partition("/")
        if not _NUM_OLD_RE.fullmatch(num) or not _mm_ok(num[:4]):
            return None
        if not _cat_ok(cat):
            return None
        return ("old", cat, num)
    if _NEW_RE.fullmatch(t) and _mm_ok(t[:4]):
        return ("new",)
    return None


def _normalize_token(tok: str) -> tuple[str, str | None, bool]:
    """backslash->slash, decode cat--id safe form, peel trailing vN.

    -> (normalized_text, ver | None, was_safe_form)
    """
    t = tok.replace("\\", "/")
    was_safe = False
    if "--" in t:
        t = idc_from_safe(t)
        was_safe = True
    t, ver = strip_ver(t)
    return t, ver, was_safe


_IA_EXT = r"(?:\.([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*))?$"
_IA_NEW = re.compile(r"([0-9]{4}\.[0-9]{4,5})(?:v([0-9]+))?" + _IA_EXT)
_IA_OLD = re.compile(r"([A-Za-z][A-Za-z0-9.-]*?)([0-9]{7,9})(?:v([0-9]+))?" + _IA_EXT)


def parse_ia_member(name: str) -> tuple[str, str | None, str | None] | None:
    """Parse an IA tar member name -> (idc, ver, ext), or None if it is not
    a per-paper member.

        'arXiv-cond-mat9601002v1.gz' -> ('cond-mat/9601002', 'v1', 'gz')
        'arXiv-2101.12345v3.pdf'    -> ('2101.12345', 'v3', 'pdf')
        '0103/hep-th0103100.gz'     -> ('hep-th/0103100', None, 'gz')
        'arXiv_pdf_0101_001.tar'    -> None   (item archive, not a member)
    """
    if not name:
        return None
    base = name.rsplit("/", 1)[-1].strip()
    base = base.removeprefix("arXiv-")
    m = _IA_NEW.match(base)
    if m:
        yymm_nn, ver, ext = m.groups()
        if not _mm_ok(yymm_nn[:4]):
            return None
        return yymm_nn, (f"v{ver}" if ver else None), ext
    m = _IA_OLD.match(base)
    if m:
        cat, num, ver, ext = m.groups()
        if _form_of(f"{cat}/{num}") is None:
            return None
        return f"{cat}/{num}", (f"v{ver}" if ver else None), ext
    return None


class PapersRegistry:
    """Known-paper registry backing bare-tail resolution (§3.10.7).

    Sources, with the tag recorded per tail in ``tail_src``:

        manifest   bench/corpus/manifest*.jsonl 'id' fields  (tracked)
        idresolve  lake/durable/idresolve.jsonl  (tracked, arXiv-verified)
        override   bench/corpus/id_overrides.jsonl (tracked, human)
        ledger     ledger/events.jsonl idc/id fields        (untracked)
        vault      vault/manifest.jsonl idc/id fields       (untracked)
        manual     add()                                    (untracked)

    ``resolutions`` holds explicit tail7 -> idc adjudications (id_overrides /
    idresolve rows) — the human/API answer that breaks an ambiguous tail.
    """

    def __init__(self):
        self.tails: dict[str, set[str]] = {}  # tail7 -> {cat}
        self.known: set[str] = set()  # full canon idc strings
        self.tail_src: dict[str, set[str]] = {}  # tail7 -> {source tag}
        self.resolutions: dict[str, str] = {}  # tail7 -> idc (adjudicated)

    # -- mutation --------------------------------------------------------------

    def add(self, idc: str, src: str = "manual") -> bool:
        """Register one id. The spelling is normalized first (safe form
        decoded, vN peeled); non-canon input is ignored. Returns True when
        the id was accepted."""
        if not isinstance(idc, str):
            return False
        norm, _ver, _sf = _normalize_token(idc.strip())
        form = _form_of(norm)
        if form is None:
            return False
        self.known.add(norm)
        if form[0] == "old":
            cat, num = form[1], form[2]
            self.tails.setdefault(num, set()).add(cat)
            self.tail_src.setdefault(num, set()).add(src)
        return True

    def resolve_tail(self, tail: str, idc: str, src: str = "override") -> bool:
        """Record an explicit tail7 -> idc adjudication. The target must be a
        valid old-style idc whose numeric part IS the tail — a mismatched
        resolution row is rejected (fail-closed)."""
        if not isinstance(tail, str) or not _BARE_RE.fullmatch(tail):
            return False
        if not isinstance(idc, str):
            return False
        norm, _ver, _sf = _normalize_token(idc.strip())
        form = _form_of(norm)
        if form is None or form[0] != "old" or form[2] != tail:
            return False
        self.resolutions[tail] = norm
        self.add(norm, src=src)
        return True

    # -- queries -----------------------------------------------------------------

    def has(self, idc: str) -> bool:
        """Membership check, tolerant of safe-form/versioned spellings."""
        if not isinstance(idc, str):
            return False
        norm, _ver, _sf = _normalize_token(idc.strip())
        return norm in self.known

    def cats_for_tail(self, tail7: str) -> set[str]:
        return set(self.tails.get(tail7, ()))

    def tail_tracked(self, tail7: str) -> bool:
        """Whether this tail has a tracked source (manifest/idresolve/override)
        — the |cats|=1 bare-tail ok gate."""
        return bool(self.tail_src.get(tail7, set()) & TRACKED_SRC)

    def rev(self) -> str:
        """Content sha256 of the resolver state — for resolver_rev pinning
        into plan.json / spec_env (§3.10.7)."""
        payload = {
            "known": sorted(self.known),
            "res": sorted(self.resolutions.items()),
            "src": {t: sorted(s) for t, s in sorted(self.tail_src.items())},
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # -- loading -------------------------------------------------------------------

    @classmethod
    def load(cls, roots=None) -> PapersRegistry:
        """Build a registry from on-disk sources. All files are optional —
        missing pieces are tolerated.

        roots: repo checkout(s) containing bench/corpus/ — defaults to this
        repo. Zone files (lake durable idresolve, ledger events, vault
        manifest) come from paths.* so TEXLATE_*_ROOT overrides apply.
        """
        reg = cls()
        if roots is None:
            roots = [REPO_ROOT]
        elif isinstance(roots, (str, Path)):
            roots = [roots]
        roots = [Path(r) for r in roots]

        # Tracked sources first.
        for root in roots:
            corpus = root / "bench" / "corpus"
            for mf in sorted(corpus.glob("manifest*.jsonl")):
                reg._feed_file(mf, src="manifest")
        # arXiv-verified API resolutions (lake durable).
        reg._feed_file(paths.lake_durable_dir() / "idresolve.jsonl", src="idresolve")
        # Human adjudications — written after idresolve so overrides win.
        for root in roots:
            reg._feed_file(
                root / "bench" / "corpus" / "id_overrides.jsonl", src="override"
            )
        # Untrusted breadth — never enough to mint a bare tail on its own.
        reg._feed_file(paths.events_path(), src="ledger")
        reg._feed_file(paths.vault_manifest_path(), src="vault")
        return reg

    def _feed_file(self, path: Path, src: str) -> None:
        try:
            if not path.is_file():
                return
        except OSError:
            return
        try:
            for _ln, row, _raw in iter_jsonl(path):
                if isinstance(row, dict):
                    self._feed_row(row, src)
        except OSError:
            return

    def _feed_row(self, row: dict, src: str) -> None:
        idc = (
            row.get("idc") or row.get("id") or row.get("resolved") or row.get("resolve")
        )
        tail = row.get("tail7") or row.get("tail")
        if isinstance(tail, str):
            # Row is a tail adjudication. Unresolved seeds contribute nothing —
            # an "ambig"/"pending" candidate must not leak into `known` and
            # accidentally mark the tail tracked.
            status = str(row.get("status", "")).lower()
            if status in {"pending", "ambig", "ambiguous", "invalid"}:
                return
            if isinstance(idc, str) and self.resolve_tail(tail, idc, src=src):
                return
            # Alternative resolution shape: {"tail7": "…", "cat": "…"}
            cat = row.get("cat") or row.get("archive")
            if isinstance(cat, str):
                self.resolve_tail(tail, f"{cat}/{tail}", src=src)
            # A tail row whose resolution target failed validation is dropped
            # wholesale (fail-closed) — never reinterpret it as a plain id.
            return
        if isinstance(idc, str):
            self.add(idc, src=src)


def canon_id(raw: str, registry: PapersRegistry | None = None) -> CanonResult:
    """Resolve any accepted spelling to its canon idc.

    Total, pure, idempotent — same input always yields the same CanonResult
    given the same registry, and canon_id(canon_id(x).idc).idc == idc.

        'cond-mat/9601002'   -> ok('cond-mat/9601002')
        'cond-mat--9601002'  -> ok('cond-mat/9601002')   (safe form decoded)
        '2101.12345v3'       -> ok('2101.12345', ver='v3')
        '9601002'            -> registry-gated (never guessed)
        'math.QA/9703043'    -> ok('q-alg/9703043') if registry knows the
                              minted spelling, else ok('math.QA/9703043')
        'a b' / 'blah' / '.bak-mock/0101001' -> invalid
    """
    if not isinstance(raw, str) or not raw.strip():
        return CanonResult(INVALID, reason="invalid:empty")
    toks = raw.split()
    if len(toks) > 1:
        return CanonResult(INVALID, reason="invalid:multi-token")
    t, ver, was_safe = _normalize_token(toks[0])

    form = _form_of(t)
    if form is not None:
        if form[0] == "new":
            return CanonResult(
                OK, idc=t, reason="ok:safe-id" if was_safe else "ok", ver=ver
            )
        cat, num = form[1], form[2]
        old = _NEW_TO_OLD.get(cat)
        if old is not None:
            old_idc = f"{old}/{num}"
            if registry is not None and registry.has(old_idc):
                return CanonResult(OK, idc=old_idc, reason="ok:registry-alias", ver=ver)
            return CanonResult(
                OK, idc=f"{cat}/{num}", reason="ok:new-name-kept", ver=ver
            )
        return CanonResult(
            OK, idc=f"{cat}/{num}", reason="ok:safe-id" if was_safe else "ok", ver=ver
        )

    if _BARE_RE.fullmatch(t):
        if not _mm_ok(t[:4]):
            return CanonResult(INVALID, reason="invalid:bad-tail-shape", ver=ver)
        if registry is None:
            return CanonResult(INVALID, reason="invalid:bare-tail-no-registry", ver=ver)
        res = registry.resolutions.get(t)
        if res is not None:
            return CanonResult(OK, idc=res, reason="ok:override", ver=ver)
        cats = registry.cats_for_tail(t)
        if not cats:
            return CanonResult(INVALID, reason="invalid:bare-tail-unknown", ver=ver)
        cands = sorted(f"{c}/{t}" for c in cats)
        if len(cats) > 1:
            return CanonResult(
                AMBIG, candidates=cands, reason="ambig:multi-cat", ver=ver
            )
        if not registry.tail_tracked(t):
            return CanonResult(
                AMBIG, candidates=cands, reason="ambig:untracked-cat", ver=ver
            )
        return CanonResult(OK, idc=cands[0], reason="ok:bare-tail", ver=ver)

    return CanonResult(INVALID, reason="invalid:shape", ver=ver)


__all__ = [
    "AMBIG",
    "ARCHIVE_RENAMED",
    "INVALID",
    "OK",
    "REPO_ROOT",
    "TRACKED_SRC",
    "CanonResult",
    "PapersRegistry",
    "canon_id",
    "escape_component",
    "idc_from_safe",
    "parse_ia_member",
    "safe_id",
    "strip_ver",
    "unescape_component",
]
