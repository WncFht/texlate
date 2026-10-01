"""kernel.vault.cred — 凭证代数 (kernel.vault 拆分叶).

Credential = (idc, arm, variant, altseq, zone) — five dimensions, one meta
file per physical copy. 本叶是无盘状态层：词汇常量 (KINDS/ZONES/VERDICTS/
zone↔物理根映射)、四异常、五维命名与解析 (注入式转义 round-trip,
§3.10.4)、leaf/meta 绝对径定位。一切 lookup 只算名字不触盘。
"""

from __future__ import annotations

import re
from pathlib import Path

from kernel import events, idnorm, paths

# Asset kinds the vault physically stores (§3.10.1: xlat-state is the third;
# layoutqc is the fourth——qc.json+txlm 质检包随末段 mutates 格收割).
KINDS = events.VAULT_KINDS

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
