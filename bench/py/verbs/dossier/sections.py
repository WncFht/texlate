"""verbs.dossier schema 面叶 —— 案卷节构建：identity/signature/evidence/
history/rules/gap_flags 及共助（_err0/_is_fail/_latest_of/_primary_compile/
_manifest_row/_fix_class_hint/_candidate_rules）（dossier.py 拆分叶）。

门面回引名单见 ``verbs.dossier._LEAF_EXPORTS``。
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from verbs._common import _iter_jsonl
from verbs.dossier.env import (
    _EXCERPT_HEAD,
    _FAIL_WORDS,
    _SUBCLASS_SIGS,
    _WONTFIX_CATS,
    CORPUS,
    STAGES,
    _ruleset,
    _triage_fn,
)
from verbs.dossier.fetch import _latest
from verbs.dossier.work import _classify_text, _rec_taxo

# ---------------------------------------------------------------- schema 面


def _err0(rec: dict) -> dict:
    errs = rec.get("errors") or []
    return errs[0] if errs else {}


def _is_fail(status: str) -> bool:
    return status in _FAIL_WORDS


def _latest_of(
    recs: dict[str, list[dict]], stage: str, arm: str | None = None
) -> dict | None:
    rows = _latest(recs).get(stage) or []
    if arm is not None:
        rows = [r for r in rows if str(r.get("arm")) == arm]
    return rows[-1] if rows else None


def _primary_compile(recs: dict[str, list[dict]]) -> dict | None:
    """主 compile 格：zh 臂优先、append 序**末条 attempted**（skip=上游门
    格不算——rerun 波末位常是 skip，签名/verdict 要取真跑过的那条）。"""
    rows = _latest(recs).get("compile") or []
    for r in reversed(rows):
        if str(r.get("arm")) == "zh" and str(r.get("status")) != "skip":
            return r
    for r in reversed(rows):
        if str(r.get("status")) != "skip":
            return r
    return rows[-1] if rows else None


def _manifest_row(cands: set[str]) -> dict | None:
    for f in sorted(CORPUS.glob("manifest*.jsonl")):
        for r in _iter_jsonl(f):
            if isinstance(r, dict) and str(r.get("id")) in cands:
                return r
    return None


def _identity(pid: str, cands: set[str], recs: dict[str, list[dict]]) -> dict:
    m = _manifest_row(cands) or {}
    comp = _primary_compile(recs)
    par = _latest_of(recs, "parse")
    cm = (comp or {}).get("metrics") or {}
    return {
        "id": pid,
        "layer": m.get("layer"),
        "era": m.get("era"),
        "channel": m.get("channel"),
        "main_rel": cm.get("main_rel")
        or ((par or {}).get("metrics") or {}).get("main_rel"),
        "engine": cm.get("engine")
        or ((par or {}).get("metrics") or {}).get("engine_resolved"),
        "uncompressed_bytes": m.get("bytes"),
    }


def _signature(recs: dict[str, list[dict]]) -> dict:
    comp = _primary_compile(recs) or {}
    v = (comp.get("metrics") or {}).get("verdict") or {}
    sig_raw = str(comp.get("sig") or "")
    bucketed = None
    bucket_sig = _triage_fn("bucket_sig")
    if bucket_sig is not None and sig_raw:
        with contextlib.suppress(Exception):
            bucketed = bucket_sig(sig_raw, comp)
    return {
        "sig_raw": sig_raw or None,
        "sig_bucketed": bucketed,
        "verdict": v or None,
        "fix_class_hint": _fix_class_hint(sig_raw, comp),
    }


def _fix_class_hint(sig: str, rec: dict) -> str | None:
    classify = _triage_fn("classify")
    if classify is None or not sig:
        return None
    try:
        cls, note = classify(sig, rec)
    except Exception:
        return None
    return f"{cls}: {note}"


def _evidence(recs: dict[str, list[dict]], cases: list[dict], inv: dict) -> dict:
    comp = _primary_compile(recs) or {}
    cm = comp.get("metrics") or {}
    first_err = (cm.get("compile") or {}).get("first_error")
    fl = _latest_of(recs, "fixloop")
    post = ((fl or {}).get("metrics") or {}).get("post") or {}
    excerpt = (cases[-1].get("log_excerpt") if cases else None) or None
    fe_tax = _rec_taxo(comp, "taxonomy")
    if fe_tax is None:
        fe_tax = _classify_text(first_err or "")
    return {
        "first_error_line": first_err or (post.get("compile") or {}).get("first_error"),
        "first_error_taxonomy": fe_tax,
        "log_excerpt": excerpt[:_EXCERPT_HEAD] if excerpt else None,
        "repro_path": inv.get("path") if inv.get("present") else None,
        "splice_dir": bool(inv.get("splice")),
        "texmf_tree": bool(inv.get("_texmf")),
    }


def _history(
    recs: dict[str, list[dict]], prior_waves: list[str], prior_tickets: list[str]
) -> dict:
    order = [s for s in STAGES if s in recs] + sorted(
        s for s in recs if s not in STAGES
    )
    timeline = [
        {
            "stage": st,
            "arm": r.get("arm"),
            "upstream": r.get("upstream") or "",
            "status": r.get("status"),
            "dur_s": r.get("dur_s"),
            "sig": r.get("sig") or "",
            "code": r.get("code"),
            "run": r.get("run"),
        }
        for st in order
        for r in recs.get(st) or []
    ]
    comp = _primary_compile(recs)
    comp_status = (comp or {}).get("status")
    csb_chain = []
    for r in recs.get("fixloop") or []:
        csb = (r.get("metrics") or {}).get("compile_status_before")
        csb_chain.append(
            {
                "csb": csb,
                "compile_now": comp_status,
                "stale": bool(csb and comp_status and csb != comp_status),
                "status": r.get("status"),
            }
        )
    stale = any(c["stale"] for c in csb_chain)
    return {
        "timeline": timeline,
        "csb_chain": csb_chain,
        "stale_flag": stale,
        "prior_tickets": sorted(set(prior_tickets)),
        "prior_waves": prior_waves,
    }


def _candidate_rules(cat: str | None, payload: str | None) -> list[str]:
    rs = _ruleset()
    if rs is None or not cat:
        return []
    out = []
    for rule in rs.rules:
        w = rule.when
        hit = w.get("category") == cat or w.get("always") is True
        if not hit:
            for c in w.get("any") or []:
                if isinstance(c, dict) and c.get("category") == cat:
                    hit = True
                    break
        if hit:
            pay_note = ""
            if w.get("payload_required") and not payload:
                pay_note = "（payload_required 无 payload）"
            out.append(f"{rule.id}[{rule.phase}]{pay_note}")
    return out


def _rules_section(recs: dict[str, list[dict]], cases: list[dict], inv: dict) -> dict:
    comp = _primary_compile(recs) or {}
    v = (comp.get("metrics") or {}).get("verdict") or {}
    cat, pay = v.get("category"), v.get("payload")
    retired = None
    retired_names = _triage_fn("retired_names")
    if retired_names is not None and cat == "missing_file" and pay:
        with contextlib.suppress(Exception):
            retired = Path(str(pay)).name in retired_names()
    hits = [
        f"r{a.get('round')}:{a.get('rule')} → {a.get('result')}"
        for c in cases
        for a in c.get("actions") or []
    ]
    fl = _latest_of(recs, "fixloop")
    tax = None
    t0 = _rec_taxo(fl, "post", "taxonomy")
    if t0:
        tax = {**t0, "source": "records.post"}
    else:
        t0 = _rec_taxo(comp, "taxonomy")
        if t0:
            tax = {**t0, "source": "records.compile"}
    if tax is None:
        sc = inv.get("splice_compile") or {}
        if sc.get("taxonomy"):
            tax = {**sc["taxonomy"], "source": "splice_log"}
        else:
            fe = ((comp.get("metrics") or {}).get("compile") or {}).get("first_error")
            t2 = _classify_text(fe or "")
            if t2:
                tax = {**t2, "source": "first_error_line"}
    return {
        "taxonomy_class": tax,
        "candidate_rules": _candidate_rules(cat, pay),
        "rule_hit_history": hits,
        "retired_name": retired,
    }


def _gap_flags(recs: dict[str, list[dict]], inv: dict) -> dict:
    comp = _primary_compile(recs) or {}
    v = (comp.get("metrics") or {}).get("verdict") or {}
    sig = str(comp.get("sig") or "")
    bucket = sig.split(":", 1)[0] if sig else ""
    cat = v.get("category")
    st = str(comp.get("status") or "")
    needs_subclass = bucket in _SUBCLASS_SIGS or cat in _SUBCLASS_SIGS
    needs_probe = st == "clean" and bool(v.get("warnings_hit") or sig)
    unrunnable = st in {"reject", "skip", "error"} or (
        comp == {} and not recs.get("compile")
    )
    wontfix = cat in _WONTFIX_CATS or bucket in _WONTFIX_CATS
    return {
        "needs_subclass": bool(needs_subclass),
        "needs_probe": bool(needs_probe),
        "unrunnable": bool(unrunnable),
        "wontfix_candidate": bool(wontfix),
    }
