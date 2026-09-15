"""rules.yaml 规则库装载校验 + when/condition 原语 + phase 序单测。"""

from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, RulesetError, load_ruleset
from texlate.compile.fixloop.engine import (
    LoopCtx,
    Rule,
    _cond_ok,
    _substitute,
    _when_ok,
)

RS = load_ruleset()


class _Eng:
    """cond 评估的最小引擎替身 (caps + probe)。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap"})

    def __init__(self, probe_map: dict[str, str] | None = None) -> None:
        self.probe_map = probe_map or {}

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd  # mock 不区分 cwd
        return self.probe_map.get(fname)

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def ctx_for(tmp_path: Path, engine_name: str = "xelatex") -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name=engine_name)


# ---------------------------------------------------------------- 结构校验
def test_phase_ordering() -> None:
    assert [r.id for r in RS.phase("gate")] == [
        "pstricks_dvips_preflight",
        "latex209_reject",
    ]
    assert [r.id for r in RS.phase("precheck")] == ["eps_route", "static_precheck"]
    loop = [r.id for r in RS.phase("loop")]
    assert loop[0] == "install_file"
    assert loop[-1] == "undefined_cs_guess"
    orders = [r.order for r in RS.phase("loop")]
    assert orders == sorted(orders)


def test_every_rule_has_provenance() -> None:
    for r in RS.rules:
        assert r.raw.get("source_ref"), r.id
        assert r.raw.get("provenance"), r.id
        assert isinstance(r.raw.get("stats"), dict), r.id


def test_version_guard_policy_present() -> None:
    # 对账第 25 条: 非 rules 条目, 是 filemap 段的 ctan_fetch 前置检查策略
    vg = RS.filemap_cfg["version_guard"]
    assert vg["enabled"] is True
    assert vg["texlive_format_epoch"] == "2022-07-14"


def test_engine_spec_default_and_degrade() -> None:
    by_id = {r.id: r for r in RS.rules}
    assert by_id["latex209_reject"].engine_spec("nonsense") == {"mode": "native"}
    spec = by_id["install_file"].engine_spec("tectonic")
    assert spec["mode"] == "degrade"
    assert spec["degrade"] == "ctan_fetch"
    assert by_id["eps_route"].engine_spec("xelatex")["mode"] == "skip"


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 2, "rules": []},
        {
            "version": 1,
            "rules": [{"phase": "loop", "when": {}, "action": {"kind": "run_tool"}}],
        },  # 缺 id
        {
            "version": 1,
            "rules": [
                {
                    "id": "x",
                    "phase": "weird",
                    "when": {},
                    "action": {"kind": "run_tool"},
                }
            ],
        },
        {
            "version": 1,
            "rules": [
                {"id": "x", "phase": "loop", "when": {}, "action": {"kind": "nope"}}
            ],
        },
        {
            "version": 1,
            "rules": [
                {
                    "id": "x",
                    "phase": "loop",
                    "when": {},
                    "action": {"kind": "builtin_transform", "function": "no_such_fn"},
                }
            ],
        },
        {
            "version": 1,
            "rules": [
                {
                    "id": "x",
                    "phase": "loop",
                    "when": {},
                    "action": {
                        "kind": "regex_rewrite",
                        "params": {
                            "rewrites": [{"pattern": "a", "function": "nope_fn"}]
                        },
                    },
                }
            ],
        },
        {
            "version": 1,
            "rules": [
                {
                    "id": "x",
                    "phase": "loop",
                    "when": {},
                    "action": {"kind": "run_tool"},
                    "engines": {"xelatex": {"mode": "bogus"}},
                }
            ],
        },
    ],
)
def test_ruleset_validation_errors(bad: dict) -> None:
    with pytest.raises(RulesetError):
        Ruleset(bad)


def test_warn_driven_fixes_toggle() -> None:
    data = {
        "version": 1,
        "meta": {"loop": {"warn_driven_fixes": False}},
        "taxonomy": [
            {"id": "warn_utf8", "scope": "warnings", "warn_id": "invalid_utf8"}
        ],
        "rules": [],
    }
    rs = Ruleset(data)
    assert rs.taxonomy.warn == []
    assert rs.taxonomy.warn_cats == set()


# ---------------------------------------------------------------- when
def test_when_always() -> None:
    assert _when_ok({"always": True}, None, None, ctx_for(Path.cwd()))


def test_when_category_and_payload_required() -> None:
    ctx = ctx_for(Path.cwd())
    w = {"category": "missing_file", "payload_required": True}
    assert _when_ok(w, "missing_file", "a.sty", ctx)
    assert not _when_ok(w, "missing_file", None, ctx)
    assert not _when_ok(w, "missing_tfm", "a.tfm", ctx)


def test_when_any_with_main_head(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\documentstyle{article}\n")
    ctx = ctx_for(tmp_path)
    ctx.main_rel = "main.tex"
    w = {
        "any": [
            {"category": "latex209"},
            {"category": "missing_file", "main_head_contains": "\\documentstyle"},
        ]
    }
    assert _when_ok(w, "missing_file", "x.sty", ctx)
    assert not _when_ok(w, "other", None, ctx)


def test_when_empty_never_matches(tmp_path: Path) -> None:
    assert not _when_ok({}, "missing_file", "x", ctx_for(tmp_path))


# ---------------------------------------------------------------- substitute
def test_substitute_payload_nested() -> None:
    out = _substitute({"f": "{payload}.tfm", "l": ["{payload}", 1]}, "phvb")
    assert out == {"f": "phvb.tfm", "l": ["phvb", 1]}


# ---------------------------------------------------------------- condition
def test_cond_tool_and_cap(tmp_path: Path) -> None:
    ctx, eng = ctx_for(tmp_path), _Eng()
    ok, _ = _cond_ok({"tool_available": "sh"}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, why = _cond_ok(
        {"tool_available": "no_such_tool_xyz"}, Rule({"id": "r"}), ctx, eng, None
    )
    assert not ok
    assert "unavailable" in why
    ok, _ = _cond_ok({"cap_available": "tlmgr"}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, _ = _cond_ok({"cap_available": "bundle"}, Rule({"id": "r"}), ctx, eng, None)
    assert not ok


def test_cond_engine_in_and_unknown_key(tmp_path: Path) -> None:
    ctx, eng = ctx_for(tmp_path), _Eng()
    ok, _ = _cond_ok({"engine_in": ["xelatex"]}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, _ = _cond_ok({"engine_in": ["tectonic"]}, Rule({"id": "r"}), ctx, eng, None)
    assert not ok
    ok, why = _cond_ok({"bogus_key": 1}, Rule({"id": "r"}), ctx, eng, None)
    assert not ok
    assert "unknown condition" in why  # fail-closed


def test_cond_source_ctx_fileset(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text("\\usepackage{minted}\n\\pdfoutput=1\n")
    (tmp_path / "x.bbl").write_text("bbl")
    ctx, eng = ctx_for(tmp_path), _Eng()
    ctx.main_rel = "main.tex"
    ok, _ = _cond_ok(
        {"source_contains": "\\\\usepackage"}, Rule({"id": "r"}), ctx, eng, None
    )
    assert ok
    ok, _ = _cond_ok(
        {"fileset": {"has_ext": [".bbl"], "lacks_ext": [".bib"]}},
        Rule({"id": "r"}),
        ctx,
        eng,
        None,
    )
    assert ok
    ok, _ = _cond_ok(
        {"fileset": {"has_ext": [".bib"]}}, Rule({"id": "r"}), ctx, eng, None
    )
    assert not ok
    ctx.err_head = "see \\hyphenation{中}"
    ok, _ = _cond_ok(
        {"ctx_suggests": "\\\\hyphenation"}, Rule({"id": "r"}), ctx, eng, None
    )
    assert ok


def test_cond_cache_dir_glob_and_prim_read_form(tmp_path: Path) -> None:
    (tmp_path / "_minted-main").mkdir()
    (tmp_path / "main.tex").write_text("\\ifnum\\pdfoutput>0 yes\\fi\n")
    ctx, eng = ctx_for(tmp_path), _Eng()
    ok, _ = _cond_ok({"cache_dir_glob": "_minted-*"}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, _ = _cond_ok({"prim_read_form": "pdfoutput"}, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    ok, _ = _cond_ok({"prim_read_form": "pdfinfo"}, Rule({"id": "r"}), ctx, eng, None)
    assert not ok


def test_cond_package_version_ge(tmp_path: Path) -> None:
    sty = tmp_path / "minted.sty"
    sty.write_text("\\ProvidesPackage{minted}[2025/01/01 v3.0 minted]\n")
    ctx, eng = ctx_for(tmp_path), _Eng({"minted.sty": str(sty)})
    cond = {"package_version_ge": {"file": "minted.sty", "version": 3}}
    ok, _ = _cond_ok(cond, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    cond = {"package_version_ge": {"file": "minted.sty", "version": 4}}
    ok, _ = _cond_ok(cond, Rule({"id": "r"}), ctx, eng, None)
    assert not ok


def test_cond_any_or() -> None:
    ctx, eng = ctx_for(Path.cwd()), _Eng()
    cond = {"any": [{"cap_available": "bundle"}, {"cap_available": "tlmgr"}]}
    ok, _ = _cond_ok(cond, Rule({"id": "r"}), ctx, eng, None)
    assert ok
    cond = {"any": [{"cap_available": "bundle"}, {"cap_available": "none"}]}
    ok, _ = _cond_ok(cond, Rule({"id": "r"}), ctx, eng, None)
    assert not ok
