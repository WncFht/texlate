"""Contract tests for kernel.idnorm — arXiv id normalization (§3.7, §3.10.7)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from kernel import paths
from kernel.idnorm import (
    AMBIG,
    INVALID,
    OK,
    PapersRegistry,
    canon_id,
    escape_component,
    idc_from_safe,
    parse_ia_member,
    safe_id,
    strip_ver,
    unescape_component,
)


def _ok_idc(raw: str, reg: PapersRegistry | None = None) -> str:
    r = canon_id(raw, reg)
    assert r.state == OK, f"{raw!r} -> {r}"
    assert r.idc is not None
    return r.idc


# --- valid forms --------------------------------------------------------------


def test_old_style_canon() -> None:
    assert _ok_idc("cond-mat/9601002") == "cond-mat/9601002"
    assert _ok_idc("hep-th/0103100") == "hep-th/0103100"
    # renamed archives are canon VERBATIM — never rewritten to the new name
    assert _ok_idc("q-alg/9703043") == "q-alg/9703043"
    assert _ok_idc("solv-int/9608004") == "solv-int/9608004"
    assert _ok_idc("mtrl-th/9601001") == "mtrl-th/9601001"
    # cats may contain '-' and '.'
    assert _ok_idc("math.QA/0308123") == "math.QA/0308123"
    assert _ok_idc("physics.chem-ph/9801001") == "physics.chem-ph/9801001"
    assert _ok_idc("cond-mat/0601561") == "cond-mat/0601561"


def test_new_style_canon() -> None:
    assert _ok_idc("2101.12345") == "2101.12345"
    assert _ok_idc("9911.12345") == "9911.12345"
    # arXiv minted 4-digit suffixes 2007–2014 (e.g. 0707.0063 in our corpus)
    assert _ok_idc("0704.0001") == "0704.0001"
    assert _ok_idc("0707.0063") == "0707.0063"


def test_version_suffix_peeled_and_recorded() -> None:
    r = canon_id("2101.12345v3")
    assert (r.state, r.idc, r.ver) == (OK, "2101.12345", "v3")
    r = canon_id("cond-mat/9601002v10")
    assert (r.state, r.idc, r.ver) == (OK, "cond-mat/9601002", "v10")
    r = canon_id("hep-th/0103100")
    assert r.ver is None


def test_safe_form_decoded_then_validated() -> None:
    assert _ok_idc("cond-mat--9601002") == "cond-mat/9601002"
    r = canon_id("hep-th--0103100v2")
    assert (r.state, r.idc, r.ver) == (OK, "hep-th/0103100", "v2")
    assert _ok_idc("q-alg--9703043") == "q-alg/9703043"


def test_outer_whitespace_and_backslash() -> None:
    assert _ok_idc("  hep-th/0103100  ") == "hep-th/0103100"
    assert _ok_idc("\t2101.12345\n") == "2101.12345"
    assert _ok_idc("hep-th\\0103100") == "hep-th/0103100"


# --- invalid -------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "blah",
        "_meta",
        "1506.022.1477",
        "hep-th/0103",  # num too short
        "hep-th/0103100000",  # num too long (>9)
        "hep-th/0113100",  # MM=13
        "hep-th/0100100",  # MM=00
        "hep-th/0103100/extra",  # compound path
        "1512.03385/c26/ph/clean",  # case-level id, not a paper id
        "a/b/c",
        "2101.123",  # suffix too short
        "2101.123456",  # suffix too long
        "2113.12345",  # new-style MM=13
        ".bak-mock/0101001",  # leading-dot garbage cat
        "fixture/0101001",  # fixture namespace
        "mock/9901001",
        "test/9901001",
        "foo-mock/9901001",
        "9601002",  # bare tail without registry
        "96010021",  # bare 8-digit — never a tail
        "9613002",  # bare tail MM=13
        "hep-th--0103100/extra",
        "cond-mat--9601002--x",  # residual '--' after last-dash decode
        "arXiv-cond-mat9601002v1.gz",  # IA member name is not an id spelling
        "cond-mat/9601002V1",  # uppercase V is not a version
    ],
)
def test_invalid(bad: str) -> None:
    r = canon_id(bad)
    assert r.state == INVALID, f"{bad!r} -> {r}"
    assert r.idc is None


def test_multi_token_invalid() -> None:
    r = canon_id("0806.2690 1206.0272 1404.0364")
    assert r.state == INVALID
    assert r.reason == "invalid:multi-token"
    assert canon_id("hep-th /0103100").state == INVALID
    assert canon_id("hep-th/ 0103100").state == INVALID


def test_non_string_input_invalid() -> None:
    assert canon_id(None).state == INVALID
    assert canon_id(9601002).state == INVALID


# --- bare tails via registry ------------------------------------------------------


def test_bare_tail_single_tracked_cat() -> None:
    reg = PapersRegistry()
    assert reg.add("cond-mat/9601002", src="manifest") is True
    r = canon_id("9601002", reg)
    assert (r.state, r.idc, r.reason) == (OK, "cond-mat/9601002", "ok:bare-tail")
    # versioned bare tail resolves through the same gate, ver preserved
    r = canon_id("9601002v2", reg)
    assert (r.state, r.idc, r.ver) == (OK, "cond-mat/9601002", "v2")


def test_bare_tail_single_untracked_cat_is_ambig() -> None:
    """|cats|=1 with only untrusted (ledger/vault/manual) source -> Ambig.

    A local single cat is not proof of global uniqueness (§3.10.7).
    """
    for src in ("vault", "ledger", "manual"):
        reg = PapersRegistry()
        reg.add("cond-mat/9601002", src=src)
        r = canon_id("9601002", reg)
        assert r.state == AMBIG, src
        assert r.candidates == ["cond-mat/9601002"]
        assert r.idc is None


def test_bare_tail_multi_cat_ambig_never_guesses() -> None:
    reg = PapersRegistry()
    reg.add("cond-mat/9601002", src="manifest")
    reg.add("hep-th/9601002", src="manifest")
    r = canon_id("9601002", reg)
    assert r.state == AMBIG
    assert r.candidates == ["cond-mat/9601002", "hep-th/9601002"]
    assert r.idc is None


def test_bare_tail_unknown_invalid() -> None:
    reg = PapersRegistry()
    reg.add("hep-th/0103100", src="manifest")
    r = canon_id("9601002", reg)
    assert r.state == INVALID
    assert r.reason == "invalid:bare-tail-unknown"


def test_bare_tail_override_resolution_beats_ambiguity() -> None:
    reg = PapersRegistry()
    reg.add("cond-mat/9601002", src="manifest")
    reg.add("hep-th/9601002", src="manifest")
    assert reg.resolve_tail("9601002", "cond-mat/9601002", src="override")
    r = canon_id("9601002", reg)
    assert (r.state, r.idc, r.reason) == (OK, "cond-mat/9601002", "ok:override")


def test_resolve_tail_rejects_mismatch() -> None:
    reg = PapersRegistry()
    assert reg.resolve_tail("9601002", "hep-th/0103100") is False  # num != tail
    assert reg.resolve_tail("abcdefg", "hep-th/0103100") is False  # bad tail
    assert reg.resolve_tail("9601002", "2101.12345") is False  # not old-form
    assert reg.resolve_tail("9601002", "garbage") is False
    assert "9601002" not in reg.resolutions


# --- renamed-archive alias --------------------------------------------------------


def test_alias_new_name_resolves_to_minted_spelling() -> None:
    reg = PapersRegistry()
    reg.add("q-alg/9703043", src="manifest")
    r = canon_id("math.QA/9703043", reg)
    assert (r.state, r.idc, r.reason) == (OK, "q-alg/9703043", "ok:registry-alias")
    reg.add("chao-dyn/9508001", src="manifest")
    assert canon_id("nlin.CD/9508001", reg).idc == "chao-dyn/9508001"
    # safe form of a new-name input resolves the same way
    assert canon_id("math.QA--9703043", reg).idc == "q-alg/9703043"


def test_alias_new_name_without_registry_keeps_input() -> None:
    r = canon_id("math.QA/9703043")
    assert (r.state, r.idc) == (OK, "math.QA/9703043")
    r = canon_id("cs.CL/9901001")
    assert r.idc == "cs.CL/9901001"


def test_alias_old_name_never_rewritten() -> None:
    reg = PapersRegistry()
    reg.add("math.QA/9703043", src="manifest")  # registry knows only NEW spelling
    r = canon_id("q-alg/9703043", reg)
    assert r.idc == "q-alg/9703043"  # minted spelling stands


# --- idempotence ---------------------------------------------------------------------


def test_canon_id_idempotent() -> None:
    reg = PapersRegistry()
    reg.add("q-alg/9703043", src="manifest")
    reg.add("cond-mat/9601002", src="manifest")
    for raw in (
        "cond-mat/9601002",
        "cond-mat--9601002",
        "2101.12345v2",
        "math.QA/9703043",
        "q-alg/9703043",
        "9601002",
        "hep-th/0103100v1",
    ):
        r1 = canon_id(raw, reg)
        assert r1.state == OK, raw
        r2 = canon_id(r1.idc, reg)
        assert r2.state == OK
        assert r2.idc == r1.idc


# --- safe_id / idc_from_safe -----------------------------------------------------------


def test_safe_id_encoding_and_roundtrip() -> None:
    assert safe_id("cond-mat/9601002") == "cond-mat--9601002"
    assert safe_id("2101.12345") == "2101.12345"
    assert idc_from_safe("cond-mat--9601002") == "cond-mat/9601002"
    assert idc_from_safe("a--b--c") == "a--b/c"  # LAST '--' splits
    assert idc_from_safe("2101.12345") == "2101.12345"
    for idc in (
        "cond-mat/9601002",
        "q-alg/9703043",
        "2101.12345",
        "physics.chem-ph/9801001",
        "math/0307078",
    ):
        assert idc_from_safe(safe_id(idc)) == idc


# --- strip_ver --------------------------------------------------------------------------


def test_strip_ver() -> None:
    assert strip_ver("2101.12345v3") == ("2101.12345", "v3")
    assert strip_ver("cond-mat/9601002") == ("cond-mat/9601002", None)
    assert strip_ver("x") == ("x", None)
    assert strip_ver("solv-int/9608004") == ("solv-int/9608004", None)  # 'v' in cat
    assert strip_ver("9608004v12") == ("9608004", "v12")
    assert strip_ver("fooV3") == ("fooV3", None)  # uppercase V untouched


# --- escape / unescape ---------------------------------------------------------------------


def test_escape_component() -> None:
    assert escape_component("a.b@c") == "a%2Eb%40c"
    assert escape_component("a%b") == "a%25b"
    assert escape_component("plain") == "plain"


def test_escape_unescape_roundtrip() -> None:
    for s in (
        "a.b@c",
        "a%b",
        "100%.done@x",
        "%2E",
        "..@@%%",
        "plain",
        "a%40b%2Ec",
        "x.y@z%w",
        "",
    ):
        assert unescape_component(escape_component(s)) == s


def test_unescape_no_double_decode() -> None:
    # literal '%2E' in the source survives as text — never decodes twice
    assert escape_component("%2E") == "%252E"
    assert unescape_component("%252E") == "%2E"
    assert unescape_component(escape_component("%40")) == "%40"


# --- parse_ia_member --------------------------------------------------------------------------


def test_parse_ia_member_old_style() -> None:
    assert parse_ia_member("arXiv-cond-mat9601002v1.gz") == (
        "cond-mat/9601002",
        "v1",
        "gz",
    )
    assert parse_ia_member("arXiv-q-alg9703043v2.gz") == ("q-alg/9703043", "v2", "gz")
    assert parse_ia_member("0103/hep-th0103100.gz") == ("hep-th/0103100", None, "gz")
    assert parse_ia_member("hep-th0103100.gz") == ("hep-th/0103100", None, "gz")
    assert parse_ia_member("arXiv-cond-mat9601002") == ("cond-mat/9601002", None, None)


def test_parse_ia_member_new_style() -> None:
    assert parse_ia_member("arXiv-2101.12345v3.pdf") == ("2101.12345", "v3", "pdf")
    assert parse_ia_member("arXiv-0704.0001v1.gz") == ("0704.0001", "v1", "gz")
    assert parse_ia_member("arXiv-2101.12345") == ("2101.12345", None, None)


def test_parse_ia_member_garbage() -> None:
    for bad in (
        "",
        "garbage",
        "arXiv-foo-bar.gz",
        "arXiv_pdf_0101_001.tar",
        "0103/readme.txt",
        "arXiv-cond-mat9613002v1.gz",
    ):  # MM=13 rejected
        assert parse_ia_member(bad) is None, bad


# --- registry ----------------------------------------------------------------------------


def test_registry_add_normalizes() -> None:
    reg = PapersRegistry()
    assert reg.add("cond-mat--9601002v1", src="manifest")  # safe+ver normalized
    assert reg.has("cond-mat/9601002")
    assert reg.has("cond-mat--9601002")  # tolerant lookup
    assert reg.cats_for_tail("9601002") == {"cond-mat"}
    assert reg.add("garbage") is False
    assert reg.add("2101.12345")
    assert reg.has("2101.12345v9")  # version-insensitive
    assert reg.cats_for_tail("1234567") == set()


def test_registry_rev_deterministic_and_sensitive() -> None:
    a, b = PapersRegistry(), PapersRegistry()
    a.add("cond-mat/9601002", src="manifest")
    a.add("hep-th/0103100", src="ledger")
    b.add("hep-th/0103100", src="ledger")
    b.add("cond-mat/9601002", src="manifest")
    assert a.rev() == b.rev()  # order-independent
    b.add("q-alg/9703043", src="manifest")
    assert a.rev() != b.rev()  # content-sensitive


def test_load_synthetic_root(tmp_path: Path, broot: Path) -> None:
    corpus = tmp_path / "bench" / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "manifest_a.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "cond-mat/9601002"}),
                json.dumps({"id": "astro-ph--0104007"}),  # safe form in id field
                json.dumps({"id": "hep-th/0103100v2"}),  # versioned id
                json.dumps({"id": "garbage"}),  # skipped
                json.dumps({"id": "fixture/0101001"}),  # denied namespace, skipped
                "not json at all",
            ]
        )
        + "\n"
    )
    (corpus / "id_overrides.jsonl").write_text(
        json.dumps({"tail7": "9601002", "idc": "cond-mat/9601002"})
        + "\n"
        + json.dumps({"tail7": "9999999", "status": "ambig"})
        + "\n"  # seed row ignored
    )
    # zone files resolve inside the isolated broot root
    assert paths.lake_durable_dir().is_relative_to(broot)
    (paths.lake_durable_dir() / "idresolve.jsonl").write_text(
        json.dumps({"tail7": "9508001", "idc": "solv-int/9508001"}) + "\n"
    )
    paths.events_path().write_text(
        json.dumps({"type": "cell", "idc": "nlin/0104012"}) + "\n"
    )
    paths.vault_manifest_path().write_text(
        json.dumps({"idc": "physics/9901057"}) + "\n"
    )
    reg = PapersRegistry.load(roots=[tmp_path])
    assert reg.has("cond-mat/9601002")
    assert reg.has("astro-ph/0104007")
    assert reg.has("hep-th/0103100")
    assert not reg.has("garbage")
    assert not reg.has("fixture/0101001")  # denied namespace never enters
    assert reg.has("nlin/0104012")  # ledger source
    assert reg.has("physics/9901057")  # vault source
    assert reg.resolutions["9601002"] == "cond-mat/9601002"
    assert reg.resolutions["9508001"] == "solv-int/9508001"
    assert "9999999" not in reg.resolutions
    # tracked-source gate bookkeeping
    assert reg.tail_tracked("9601002")
    assert reg.tail_tracked("9508001")
    assert not reg.tail_tracked("0104012")  # ledger-only -> untracked
    assert not reg.tail_tracked("9901057")  # vault-only -> untracked
    # end-to-end through canon_id
    assert canon_id("9601002", reg).idc == "cond-mat/9601002"
    assert canon_id("9508001", reg).idc == "solv-int/9508001"
    assert canon_id("0104012", reg).state == AMBIG  # ledger-only stays ambig


def test_load_missing_files_tolerated(tmp_path: Path, broot: Path) -> None:
    assert paths.events_path().is_relative_to(broot)  # zone reads stay isolated
    reg = PapersRegistry.load(roots=[tmp_path])  # no bench/corpus at all
    assert reg.known == set()
    assert reg.cats_for_tail("9601002") == set()
    assert reg.rev() == PapersRegistry().rev()


def test_load_default_repo_root(broot: Path) -> None:
    """Smoke: default load() reads this repo's tracked manifests."""
    assert paths.lake_durable_dir().is_relative_to(broot)
    reg = PapersRegistry.load()
    assert reg.has("hep-th/0103100")  # manifest_dev_failmine
    assert reg.has("astro-ph/0111264")  # manifest_booster
    assert reg.rev() != PapersRegistry().rev()
