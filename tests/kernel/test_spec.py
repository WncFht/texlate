"""Tests for kernel/spec.py — the Spec v2 authoring surface, compile-time
checks, hashing, and load_spec.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from kernel import events
from kernel.spec import (
    Param,
    Spec,
    SpecError,
    Stage,
    cell_fp,
    code_sha,
    compile_checks,
    load_spec,
    spec_hash,
    topo_stages,
)


def _ok_class(extra=None):
    sc = {"ok": "terminal", "error": "retriable", "skip": "retriable",
          "fault": "terminal", "fail": "terminal"}
    sc.update(extra or {})
    return sc


def _stage(name, **kw):
    kw.setdefault("status_class", _ok_class())
    kw.setdefault("fn", lambda ctx: "ok")
    return Stage(name, **kw)


def _spec(**kw):
    kw.setdefault("kind", "soak")
    kw.setdefault("stages", [_stage("a")])
    kw.setdefault("items", [{"id": "2401.00001"}])
    return Spec(**kw)


# --- Param ----------------------------------------------------------------------------


def test_param_defaults_and_coerce():
    p = Param()
    assert p.type is str and p.required is False and p.choices is None
    assert p.coerce("x", "abc") == "abc"
    assert Param(int).coerce("n", "5") == 5
    assert Param(float).coerce("t", "0.5") == 0.5
    assert Param(bool).coerce("b", "true") is True
    assert Param(bool).coerce("b", "0") is False
    assert Param(choices=["a", "b"]).coerce("c", "a") == "a"
    with pytest.raises(SpecError):
        Param(int).coerce("n", "nope")
    with pytest.raises(SpecError):
        Param(choices=["a"]).coerce("c", "z")


def test_param_fp_selector_auto():
    assert Param().fp_effective("temp") is True
    assert Param().fp_effective("n") is False       # selector knob
    assert Param().fp_effective("seed") is False
    assert Param(fp=True).fp_effective("n") is True  # pinned — flagged by checks
    assert Param(fp=False).fp_effective("temp") is False


# --- Stage -----------------------------------------------------------------------------


def test_stage_needs_normalization():
    st = Stage("s", fn=lambda c: "ok",
               needs=["up1", ("up2", {"ok", "partial"}),
                      ("up3", {"accept": {"clean"}}),
                      {"stage": "up4", "accept": {"ok"}}])
    assert st.needs == [
        ("up1", frozenset({"ok"})),
        ("up2", frozenset({"ok", "partial"})),
        ("up3", frozenset({"clean"})),
        ("up4", frozenset({"ok"})),
    ]
    st2 = Stage("s2", fn=lambda c: "ok",
                needs=[("up", {"ok"})], on={"up": {"fail"}})
    assert st2.accept_for("up") == {"ok", "fail"}    # on widens accept


# --- compile_checks ----------------------------------------------------------------------


def test_compile_clean_spec_passes():
    spec = _spec(stages=[_stage("ingest"), _stage("xlat",
                                                 needs=[("ingest", {"ok"})])])
    assert compile_checks(spec) == []


def test_compile_duplicate_stage_names():
    spec = _spec(stages=[_stage("a"), _stage("a")])
    assert any("duplicate stage name" in p for p in compile_checks(spec))


def test_compile_needs_unknown_and_self():
    spec = _spec(stages=[_stage("a", needs=[("ghost", {"ok"})]),
                         _stage("b", needs=[("b", {"ok"})])])
    probs = compile_checks(spec)
    assert any("unknown stage 'ghost'" in p for p in probs)
    assert any("needs itself" in p for p in probs)


def test_compile_cycle_detected():
    spec = _spec(stages=[_stage("a", needs=[("b", {"ok"})]),
                         _stage("b", needs=[("a", {"ok"})])])
    assert topo_stages(spec) is None
    assert any("cycle" in p for p in compile_checks(spec))


def test_compile_status_class_defaults_to_canonical():
    st = Stage("a", fn=lambda c: "ok")          # no status_class declared
    spec = _spec(stages=[st])
    assert compile_checks(spec) == []           # omission is not an error
    # the canonical table: DONE -> terminal, RETRIABLE -> retriable
    assert st.status_class == {
        "ok": "terminal", "partial": "terminal", "clean": "terminal",
        "fail": "terminal", "reject": "terminal", "fault": "terminal",
        "dirty_pdf": "terminal", "skip": "retriable", "error": "retriable",
    }


def test_compile_status_class_bad_keys_and_values():
    st = _stage("a", status_class={"ok": "terminal", "dedup": "terminal",
                                   "weird": "upstream"})
    probs = compile_checks(_spec(stages=[st]))
    assert any("not instrument statuses" in p for p in probs)   # dedup banned


def test_compile_done_status_mapped_retriable_banned():
    st = _stage("a", status_class={"ok": "retriable"})
    probs = compile_checks(_spec(stages=[st]))
    assert any("DONE status 'ok' mapped to retriable" in p for p in probs)


def test_compile_status_class_must_cover_ok_and_downstream_accept():
    # downstream stage accepts 'partial' from 'a', but a never classifies it
    a = _stage("a", status_class={"ok": "terminal"})
    b = _stage("b", needs=[("a", {"partial"})],
               status_class={"ok": "terminal", "error": "retriable"})
    probs = compile_checks(_spec(stages=[a, b]))
    assert any("does not classify" in p and "'ok'" in p or "partial" in p
               for p in probs)


def test_compile_paid_stage_needs_dedup_key():
    st = _stage("x", paid=True)
    spec = _spec(stages=[st])
    assert any("dedup_key required" in p for p in compile_checks(spec))
    # declaring at spec level satisfies it
    spec2 = _spec(stages=[st], dedup_key=("idc", "arm", "variant"))
    assert not any("dedup_key required" in p for p in compile_checks(spec2))


def test_compile_duplicate_item_cells():
    spec = _spec(items=[{"id": "a"}, {"id": "a"}])
    assert any("duplicate item cell key" in p for p in compile_checks(spec))


def test_compile_param_violations():
    spec = _spec(params={
        "bad_type": Param(list),
        "req_default": Param(str, default="x", required=True),
        "bad_default": Param(int, default="s"),
        "n": Param(int, fp=True),               # selector knob fp=True
    })
    probs = compile_checks(spec)
    assert any("not in" in p and "bad_type" in p for p in probs)
    assert any("required=True but default" in p for p in probs)
    assert any("bad_default" in p for p in probs)
    assert any("selector knob" in p for p in probs)


def test_compile_layer_and_eval_gates():
    spec = _spec(items=[{"id": "a", "layer": "mars"}],
                 allowed_layers=["bench"])
    assert any("not in allowed_layers" in p for p in compile_checks(spec))
    spec2 = _spec(items=[{"id": "a", "layer": "holdout"}],
                  allowed_layers=["holdout"])
    assert any("requires spec.eval" in p for p in compile_checks(spec2))
    spec3 = _spec(items=[{"id": "a", "layer": "holdout"}],
                  allowed_layers=["holdout"], eval=True)
    assert not any("requires spec.eval" in p for p in compile_checks(spec3))


def test_compile_executor_and_mutates_vocab():
    spec = _spec(executor="banana")
    assert any("executor" in p for p in compile_checks(spec))
    st = _stage("a", mutates=["nope"])
    assert any("mutates kind" in p for p in compile_checks(_spec(stages=[st])))
    st2 = _stage("a", executor="process")
    assert not any("executor" in p for p in compile_checks(_spec(stages=[st2])))


def test_compile_needs_accept_vocab():
    st = _stage("a", needs=[("b", {"dedup"}), ("b", {"ok"})])
    spec = _spec(stages=[_stage("b"), st])
    assert any("non-instrument statuses" in p for p in compile_checks(spec))


def test_items_materialize_one_shot():
    calls = []

    def gen():
        calls.append(1)
        yield {"id": "a"}
        yield {"id": "b"}

    spec = _spec(items=gen)
    items = spec.iter_items()
    assert [i["id"] for i in items] == ["a", "b"]
    assert spec.iter_items() == items            # same contents
    assert spec.items is not gen                 # materialized into a list
    assert len(calls) == 1                       # generator ran exactly once


def test_item_tuple_and_bare_forms():
    spec = _spec(items=["2401.00001",
                        ("2401.00002", "zh"),
                        ("2401.00003", "zh", "u", "v", "a")])
    items = spec.iter_items()
    assert items[0] == {"id": "2401.00001", "arm": "-", "up": "-",
                        "variant": "-"}
    assert items[1]["arm"] == "zh"
    assert items[2] == {"id": "2401.00003", "arm": "zh", "up": "u",
                        "variant": "v", "stage": "a"}


# --- hashing ----------------------------------------------------------------------------


def test_spec_hash_deterministic_and_sensitive():
    s1 = _spec()
    s2 = _spec()
    s3 = _spec(items=[{"id": "different"}])
    assert spec_hash(s1) == spec_hash(s2)
    assert spec_hash(s1) != spec_hash(s3)
    assert code_sha(s1) == code_sha(s2)


def test_cell_fp_excludes_selector_params():
    spec = _spec(params={"temp": Param(float, default=0.1),
                         "n": Param(int, default=1)})
    base = {"id": "x", "idc": "x", "arm": "-", "up": "-", "variant": "-",
            "stage": "a", "fp_input": None,
            "run_params": {"temp": 0.1, "n": 1}, "params": {}}
    f1 = cell_fp(spec, base)
    # selector knob change -> fp UNCHANGED (§3.4)
    f2 = cell_fp(spec, dict(base, run_params={"temp": 0.1, "n": 99}))
    assert f1 == f2
    # fp-effective param change -> fp changes
    f3 = cell_fp(spec, dict(base, run_params={"temp": 0.9, "n": 1}))
    assert f1 != f3
    # input change -> fp changes
    f4 = cell_fp(spec, dict(base, fp_input="sha:abc"))
    assert f1 != f4
    assert f1 == cell_fp(spec, base)              # deterministic


# --- load_spec ----------------------------------------------------------------------------


def test_load_spec_roundtrip(tmp_path: Path):
    src = tmp_path / "mybench.py"
    src.write_text(textwrap.dedent("""\
        from kernel.spec import Param, Spec, Stage

        def go(ctx):
            return "ok"

        spec = Spec(
            kind="filebench",
            params={"n": Param(int, default=2)},
            stages=[Stage("only", fn=go,
                          status_class={"ok": "terminal"})],
            items=[{"id": "2401.00001"}],
        )
        """))
    spec = load_spec(src)
    assert spec.kind == "filebench"
    assert spec._path == str(src)
    # file-source code_sha is stable and path-sensitive
    assert code_sha(spec) == code_sha(spec, src)


def test_load_spec_compile_failure_raises(tmp_path: Path):
    src = tmp_path / "bad.py"
    src.write_text(textwrap.dedent("""\
        from kernel.spec import Spec, Stage
        spec = Spec(kind="bad", stages=[
            Stage("a", fn=None, status_class={"ok": "terminal"}),
        ], items=[])
        """))
    with pytest.raises(SpecError) as exc:
        load_spec(src)
    assert any("fn is not callable" in p for p in exc.value.problems)


def test_load_spec_missing_spec_object(tmp_path: Path):
    src = tmp_path / "empty.py"
    src.write_text("x = 1\n")
    with pytest.raises(SpecError):
        load_spec(src)
