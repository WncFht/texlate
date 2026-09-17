#!/usr/bin/env python3
r"""dossier.py — per-id 跨阶段案卷：签名→证据→历史→规则链 一键出卷。

把 scout-*/工单派单的手工归因固化成读侧工具（still-manual-audit-2026-09-17
§2 schema）：records/*.jsonl 全量时间线 + cases.jsonl 案卷 + work/{id}/
产物树 + rules.yaml taxonomy 读侧复用（first_error→taxonomy_class，解
M1 聚合桶细分）。**只读**：不改任何 records/work。

数据源契约（stagerun.py docstring）：
  records/{ingest,parse,xlat,compile,fixloop}.jsonl  {id,stage,arm,upstream,status,dur_s,metrics,errors,sig}
  cases.jsonl                                      {corpus,cond,verdict,rounds,actions,installed,...}
  work/{safe_id}/  src/ zh/ parse.json xlat-{arm}.jsonl splice/ build-base/ _texmf/

用法:
  dossier.py 0707.0128                     # 自动选最新含该 id 的 run 目录
  dossier.py 0707.0128 --run DIR           # 钉 run
  dossier.py 0707.0128 --diff DIR          # 本 run → DIR 的 end-state 迁移（M5 波前后对账）
  dossier.py 0707.0128 --all-runs          # 附跨 run 出现史（prior_waves 全表）
  dossier.py 0707.0128 --json              # 机读 dossier dict
  dossier.py --selftest                    # 合成假 run 自检

读侧 import：``texlate.compile.fixloop``（taxonomy/ruleset）可用时启用
（``uv run python bench/py/dossier.py``），不可用时降级为 sig 级口径并在
报告标注——系统 python3 保底可跑。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import benchlib

BENCH = Path(__file__).resolve().parents[1]
RESULTS = BENCH / "results"
CORPUS_V3 = BENCH / "corpus_v3"
VENDORED_INV = RESULTS / "cbucket-vendored-inventory" / "inventory.jsonl"

try:  # 读侧 taxonomy 复用——uv run 下可用；系统 python 降级
    from texlate.compile.fixloop.engine import load_ruleset
    from texlate.compile.fixloop.logparse import parse_log, parse_text

    _TAX_OK = True
except Exception:  # noqa: BLE001 -- 任何 import 失败都走降级面
    _TAX_OK = False

try:  # triage.bucket_sig/classify/retired_names 复用（同目录，stdlib 级）
    import triage
except Exception:  # noqa: BLE001
    triage = None

STAGES = ("ingest", "parse", "xlat", "compile", "fixloop")
_FAIL_WORDS = {"fail", "error", "reject", "crash", "timeout"}
#: M1 待细分桶（audit §2 gap_flags.needs_subclass）
_SUBCLASS_SIGS = ("other", "syntax", "unfixable:other")
#: M6 wontfix 裁定面（audit §2）
_WONTFIX_CATS = {"early_eof", "capacity", "latex209", "inject"}
_BANG_TAIL = 3
_EXCERPT_HEAD = 600

_RULESET = None


def _ruleset():
    """rules.yaml 懒装（taxonomy + rules + warn_patterns）；不可用 → None。"""
    global _RULESET
    if not _TAX_OK:
        return None
    if _RULESET is None:
        try:
            _RULESET = load_ruleset()
        except Exception:  # noqa: BLE001 -- rules.yaml 缺/坏不拖读侧
            _RULESET = False
    return _RULESET or None


# ---------------------------------------------------------------- id 归一


def _id_candidates(pid: str) -> list[str]:
    """records id 形态候选：原样 + ``--``↔``/`` 互换。"""
    cands = [pid]
    if "--" in pid:
        cands.append(pid.replace("--", "/"))
    if "/" in pid:
        cands.append(pid.replace("/", "--"))
    return list(dict.fromkeys(cands))


def _workdir_names(pid: str) -> list[str]:
    return [benchlib.safe_id(c) for c in _id_candidates(pid)]


# ---------------------------------------------------------------- records 侧


def _runs_with_records(results: Path = RESULTS) -> list[Path]:
    return sorted(d.parent for d in results.glob("*/records")) if results.exists() else []


def load_stage_records(run_dir: Path, pid: str) -> dict[str, list[dict]]:
    """records/{stage}.jsonl → {stage: 该 id 全量行（append 序——波次可辨）}。"""
    cands = set(_id_candidates(pid))
    out: dict[str, list[dict]] = {}
    rec_dir = run_dir / "records"
    for f in sorted(rec_dir.glob("*.jsonl")) if rec_dir.is_dir() else []:
        hits = [
            r
            for r in benchlib.iter_jsonl(f)
            if isinstance(r, dict) and str(r.get("id")) in cands
        ]
        if hits:
            out[f.stem] = hits
    return out


def _latest(recs: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """每 stage 末条胜视图（(id,arm,upstream) 键）。"""
    return {
        st: list(benchlib.latest_by(rows, benchlib.rec_key).values())
        for st, rows in recs.items()
    }


def load_cases(run_dir: Path, pid: str) -> list[dict]:
    cands = set(_id_candidates(pid))
    f = run_dir / "cases.jsonl"
    if not f.exists():
        return []
    hits = [
        r
        for r in benchlib.iter_jsonl(f)
        if isinstance(r, dict) and str(r.get("corpus")) in cands
    ]
    return list(
        benchlib.latest_by(hits, lambda r: (r.get("corpus"), r.get("cond"))).values()
    )


def load_tickets(run_dir: Path, pid: str) -> list[str]:
    """tickets.jsonl 中 example_ids 含此 id 的工单 sig_id。"""
    cands = set(_id_candidates(pid))
    out = []
    for f in sorted(run_dir.glob("tickets*.jsonl")):
        for r in benchlib.iter_jsonl(f):
            if isinstance(r, dict) and cands & {
                str(x) for x in (r.get("example_ids") or [])
            }:
                out.append(str(r.get("sig_id") or r.get("signature") or "?"))
    return out


def _id_in_run(run_dir: Path, pid: str) -> bool:
    if load_stage_records(run_dir, pid) or load_cases(run_dir, pid):
        return True
    return any((run_dir / "work" / n).is_dir() for n in _workdir_names(pid))


def pick_run(pid: str, results: Path = RESULTS) -> Path | None:
    for run_dir in reversed(_runs_with_records(results)):
        if _id_in_run(run_dir, pid):
            return run_dir
    return None


# ---------------------------------------------------------------- work 树侧


def _tree_stats(d: Path) -> dict:
    n = 0
    size = 0
    for p in d.rglob("*"):
        if p.is_file():
            n += 1
            try:
                size += p.stat().st_size
            except OSError:
                pass
    return {"files": n, "bytes": size}


def _xlat_chunk_stats(f: Path) -> dict:
    stats: dict[str, int] = {}
    bad: list[dict] = []
    for r in benchlib.iter_jsonl(f):
        if not isinstance(r, dict):
            continue
        st = str(r.get("status") or "?")
        stats[st] = stats.get(st, 0) + 1
        if st != "ok" and len(bad) < 8:
            bad.append(
                {
                    "chunk_id": r.get("chunk_id"),
                    "status": st,
                    "error_kind": r.get("error_kind") or r.get("skip_reason") or "",
                }
            )
    return {"counts": stats, "bad": bad, "total": sum(stats.values())}


def _texmf_installed(texmf: Path) -> list[str]:
    home = texmf / "home"
    if not home.is_dir():
        return []
    return sorted(
        p.relative_to(home).as_posix()
        for p in home.rglob("*")
        if p.is_file()
        and p.suffix in (".sty", ".cls", ".def", ".clo", ".fd", ".cfg", ".tex")
    )


def _classify_log(log_path: Path | None, *, timed_out: bool = False) -> dict | None:
    """log 文件 → taxonomy (cat,pay) + n_bang——读侧复用 fixloop 分类器（M1）。"""
    rs = _ruleset()
    if rs is None or log_path is None or not log_path.is_file():
        return None
    try:
        rep = parse_log(log_path, warn_patterns=rs.warn_patterns)
        cat, pay = rs.taxonomy.classify(rep, timed_out=timed_out)
    except Exception:  # noqa: BLE001 -- 单 log 坏不拖案卷
        return None
    return {"category": cat, "payload": pay, "n_bang": rep.n_bang,
            "warnings": rep.warnings, "line_no": rep.line_no,
            "file_stack": rep.file_stack[-3:]}


def _classify_text(text: str) -> dict | None:
    """first_error 原文行 → taxonomy（无全 log 时的降级口径）。"""
    rs = _ruleset()
    if rs is None or not text:
        return None
    try:
        rep = parse_text(text, warn_patterns=rs.warn_patterns)
        cat, pay = rs.taxonomy.classify(rep)
    except Exception:  # noqa: BLE001
        return None
    return {"category": cat, "payload": pay}


def _rec_taxo(rec: dict | None, *path: str) -> dict | None:
    """records 物化 taxonomy（judge_dict 写侧口径 {cat,pay}）→ {category,payload}。

    ``path`` 如 ``("post", "taxonomy")`` 取 ``metrics.post.taxonomy``。
    cat 为 None 视为缺席（advisory 判不上时写侧落双 None）。
    """
    node = (rec or {}).get("metrics") or {}
    for k in path:
        node = node.get(k) if isinstance(node, dict) else None
        if node is None:
            return None
    if not isinstance(node, dict) or node.get("cat") is None:
        return None
    return {"category": node.get("cat"), "payload": node.get("pay")}


def work_inventory(wdir: Path) -> dict:
    inv: dict = {"path": str(wdir), "present": wdir.is_dir()}
    if not wdir.is_dir():
        return inv
    for sub in ("src", "zh", "splice", "build-base", "_texmf", "xlat-state"):
        d = wdir / sub
        if d.is_dir():
            inv[sub] = _tree_stats(d)
    pj = wdir / "parse.json"
    if pj.is_file():
        try:
            d = json.loads(pj.read_text(encoding="utf-8"))
            inv["parse"] = {
                "status": d.get("status"),
                "main_rel": d.get("main_rel"),
                "engine_resolved": d.get("engine_resolved"),
                "route_reject": (d.get("route") or {}).get("reject"),
                "totals": d.get("totals"),
                "parse_fail": d.get("parse_fail"),
            }
        except (OSError, json.JSONDecodeError):
            inv["parse"] = {"status": "unreadable"}
    arm_f = wdir / "zh" / ".xlat-arm.json"
    if arm_f.is_file():
        try:
            inv["xlat_arm"] = json.loads(arm_f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    inv["xlat_arms"] = {
        f.name: _xlat_chunk_stats(f) for f in sorted(wdir.glob("xlat-*.jsonl"))
    }
    for sub in ("splice", "build-base"):
        d = wdir / sub
        if not d.is_dir():
            continue
        logs = sorted(d.glob("*.log"))
        pdfs = sorted(d.glob("*.pdf"))
        entry: dict = {
            "pdf": [p.name for p in pdfs],
            "log_name": logs[-1].name if logs else None,
        }
        tax = _classify_log(logs[-1]) if logs else None
        if tax:
            entry["taxonomy"] = tax
        inv[f"{sub}_compile"] = entry
    inst = _texmf_installed(wdir / "_texmf")
    if inst:
        inv["texmf_installed"] = inst
    return inv


# ---------------------------------------------------------------- schema 面


def _err0(rec: dict) -> dict:
    errs = rec.get("errors") or []
    return errs[0] if errs else {}


def _is_fail(status: str) -> bool:
    return status in _FAIL_WORDS


def _latest_of(recs: dict[str, list[dict]], stage: str, arm: str | None = None) -> dict | None:
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


def _manifest_row(pid: str) -> dict | None:
    cands = set(_id_candidates(pid))
    for f in sorted(CORPUS_V3.glob("manifest*.jsonl")):
        for r in benchlib.iter_jsonl(f):
            if isinstance(r, dict) and str(r.get("id")) in cands:
                return r
    return None


def _identity(pid: str, recs: dict[str, list[dict]]) -> dict:
    m = _manifest_row(pid) or {}
    comp = _primary_compile(recs)
    par = _latest_of(recs, "parse")
    cm = (comp or {}).get("metrics") or {}
    return {
        "id": pid,
        "layer": m.get("layer"),
        "era": m.get("era"),
        "channel": m.get("channel"),
        "main_rel": cm.get("main_rel") or ((par or {}).get("metrics") or {}).get("main_rel"),
        "engine": cm.get("engine") or ((par or {}).get("metrics") or {}).get("engine_resolved"),
        "uncompressed_bytes": m.get("bytes"),
    }


def _signature(recs: dict[str, list[dict]]) -> dict:
    comp = _primary_compile(recs) or {}
    v = (comp.get("metrics") or {}).get("verdict") or {}
    sig_raw = str(comp.get("sig") or "")
    bucketed = None
    if triage is not None and sig_raw:
        try:
            bucketed = triage.bucket_sig(sig_raw, comp)
        except Exception:  # noqa: BLE001
            pass
    return {
        "sig_raw": sig_raw or None,
        "sig_bucketed": bucketed,
        "verdict": v or None,
        "fix_class_hint": _fix_class_hint(sig_raw, comp),
    }


def _fix_class_hint(sig: str, rec: dict) -> str | None:
    if triage is None or not sig:
        return None
    try:
        cls, note = triage.classify(sig, rec)
    except Exception:  # noqa: BLE001
        return None
    return f"{cls}: {note}"


def _evidence(run_dir: Path, pid: str, recs: dict[str, list[dict]],
              cases: list[dict], inv: dict) -> dict:
    comp = _primary_compile(recs) or {}
    cm = comp.get("metrics") or {}
    first_err = (cm.get("compile") or {}).get("first_error")
    fl = _latest_of(recs, "fixloop")
    post = ((fl or {}).get("metrics") or {}).get("post") or {}
    excerpt = (cases[-1].get("log_excerpt") if cases else None) or None
    # records 物化 taxonomy 优先（judge 判的那份 log），自算降级
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


def _history(pid: str, run_dir: Path, recs: dict[str, list[dict]]) -> dict:
    timeline = []
    for st in STAGES:
        for r in recs.get(st) or []:
            timeline.append(
                {
                    "stage": st,
                    "arm": r.get("arm"),
                    "upstream": r.get("upstream") or "",
                    "status": r.get("status"),
                    "dur_s": r.get("dur_s"),
                    "sig": r.get("sig") or "",
                    "code": r.get("code"),
                }
            )
    # csb 链：fixloop.compile_status_before vs compile 末条 status
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
    prior_waves = [r["run"] for r in _cross_run(pid)]
    prior_tickets = []
    for run_dir2 in _runs_with_records():
        prior_tickets.extend(load_tickets(run_dir2, pid))
    return {
        "timeline": timeline,
        "csb_chain": csb_chain,
        "stale_flag": stale,
        "prior_tickets": sorted(set(prior_tickets)),
        "prior_waves": prior_waves,
    }


def _candidate_rules(cat: str | None, payload: str | None) -> list[str]:
    """sig cat → rules.yaml 候选规则 id（when.category 命中 / always / any 子表）。"""
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
    if triage is not None and cat == "missing_file" and pay:
        try:
            retired = Path(str(pay)).name in triage.retired_names()
        except Exception:  # noqa: BLE001
            pass
    hits = []
    for c in cases:
        for a in c.get("actions") or []:
            hits.append(f"r{a.get('round')}:{a.get('rule')} → {a.get('result')}")
    # taxonomy_class：records 物化面优先（post.taxonomy=fixloop 后判残墙，
    # metrics.taxonomy=compile 判），退 splice 全 log 自算，再退 first_error 行
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
    unrunnable = st in {"reject", "skip", "error"} or (comp == {} and not recs.get("compile"))
    wontfix = cat in _WONTFIX_CATS or bucket in _WONTFIX_CATS
    return {
        "needs_subclass": bool(needs_subclass),
        "needs_probe": bool(needs_probe),
        "unrunnable": bool(unrunnable),
        "wontfix_candidate": bool(wontfix),
    }


def _vendored_lookup(payload: str) -> str | None:
    if not payload or not VENDORED_INV.is_file():
        return None
    for r in benchlib.iter_jsonl(VENDORED_INV):
        if isinstance(r, dict) and r.get("file") == payload:
            return f"{r.get('disposition')}（{r.get('license', '?')}）"
    return None


def _cross_run(pid: str) -> list[dict]:
    out = []
    for run_dir in _runs_with_records():
        recs = load_stage_records(run_dir, pid)
        if not recs and not any(
            (run_dir / "work" / n).is_dir() for n in _workdir_names(pid)
        ):
            continue
        out.append(
            {
                "run": run_dir.name,
                "stages": {
                    st: [f"{r.get('status')}/{r.get('arm','-')}" for r in rs]
                    for st, rs in _latest(recs).items()
                },
                "workdir": any(
                    (run_dir / "work" / n).is_dir() for n in _workdir_names(pid)
                ),
            }
        )
    return out


def _salient(stage: str, rec: dict) -> str:
    m = rec.get("metrics") or {}
    if stage == "ingest":
        return _err0(rec).get("payload") or ""
    if stage == "parse":
        route = m.get("route") or {}
        bits = [
            f"main={m.get('main_rel')}",
            f"eng={m.get('engine_resolved')}",
            f"chunks={(m.get('totals') or {}).get('chunks', m.get('chunks', '?'))}",
        ]
        if route.get("reject"):
            bits.append(f"reject={route['reject']}")
        wk = m.get("warn_kinds")
        if wk:
            bits.append(f"warn={wk}")
        return " ".join(str(b) for b in bits if b)
    if stage == "xlat":
        t = m.get("translate") or {}
        return (
            f"chunks={t.get('chunks')} ok={t.get('ok')} fault={t.get('fault')} "
            f"skipped={t.get('skipped')} ph={t.get('leftover_ph')}"
        )
    if stage == "compile":
        v = m.get("verdict") or {}
        c = m.get("compile") or {}
        inj = m.get("inject") or {}
        return (
            f"eng={m.get('engine')} inject={inj.get('status')}:{inj.get('mode')} "
            f"verdict={v.get('status')} cat={v.get('category')} pay={v.get('payload')} "
            f"cjk={v.get('cjk_chars')} pdf={c.get('pdf_bytes')}B"
        )
    if stage == "fixloop":
        return (
            f"verdict={m.get('fixloop_verdict')} rounds={m.get('rounds')} "
            f"actions={m.get('n_actions')} installed={m.get('installed')} "
            f"final_cat={m.get('final_cat')}"
        )
    return ""


def _attribution(recs: dict[str, list[dict]], inv: dict) -> list[str]:
    out: list[str] = []
    latest = _latest(recs)
    broken = None
    for st in STAGES:
        for r in latest.get(st, []):
            if _is_fail(str(r.get("status"))):
                broken = (st, r)
                break
        if broken:
            break
    gated = [
        (st, r)
        for st in STAGES
        for r in latest.get(st, [])
        if str(r.get("status")) == "skip" and _err0(r).get("code") == "upstream_gate"
    ]
    if broken:
        st, r = broken
        e = _err0(r)
        out.append(
            f"断点={st} status={r.get('status')} sig={r.get('sig') or '-'} "
            f"cat={e.get('cat') or '-'} payload={e.get('payload') or '-'}"
        )
    elif gated:
        st, r = gated[0]
        out.append(f"断点=上游门 {st} skip:{_err0(r).get('payload')}")
    elif latest:
        out.append("断点=无（链上无 fail 格）")
    else:
        out.append("断点=无 records")
    comp = {str(r.get("arm")): r for r in latest.get("compile", [])}
    zh, base = comp.get("zh"), comp.get("base")
    if zh and base:
        zs, bs = str(zh.get("status")), str(base.get("status"))
        if _is_fail(zs) and _is_fail(bs):
            out.append("归因=源级（base 臂同败——原文直编即挂，非翻译引入）")
        elif _is_fail(zs) and not _is_fail(bs):
            out.append("归因=管线引入（base 臂过而 zh 臂败——inject/normalize/译文侧）")
        else:
            out.append(f"归因=zh={zs} base={bs}")
    elif zh:
        out.append("归因=无 base 臂对照（zh 单臂）")
    if zh:
        v = (zh.get("metrics") or {}).get("verdict") or {}
        cat, pay = v.get("category"), v.get("payload")
        if cat:
            line = f"首错类={cat} payload={pay}"
            if cat == "missing_file" and pay:
                vend = _vendored_lookup(str(pay))
                line += f" → vendored 案={vend or 'inventory 外（新候选）'}"
            out.append(line)
    for r in latest.get("fixloop", []):
        m = r.get("metrics") or {}
        fv = m.get("fixloop_verdict")
        if fv:
            out.append(
                f"fixloop={fv} rounds={m.get('rounds')} installed={m.get('installed')}"
            )
    xa = inv.get("xlat_arm") or {}
    if zh and xa.get("arm"):
        upstream = str(zh.get("upstream") or zh.get("arm"))
        if str(xa.get("arm")) != upstream:
            out.append(
                f"⚠ provenance 分歧：zh/ 树是 xlat arm={xa['arm']} 产物，"
                f"compile 记录按 upstream={upstream} 记——陈树新编可能"
            )
    return out


# ---------------------------------------------------------------- diff（M5）


def _end_state(run_dir: Path, pid: str) -> dict:
    """单 run 的格终态面：{stage/arm: status} + verdict/fixloop 词 + pdf 在否。"""
    recs = load_stage_records(run_dir, pid)
    latest = _latest(recs)
    st: dict[str, str] = {}
    for stage, rows in latest.items():
        for r in rows:
            st[f"{stage}/{r.get('arm','-')}"] = str(r.get("status"))
    comp = _primary_compile(recs)
    fl = _latest_of(latest, "fixloop")
    v = ((comp or {}).get("metrics") or {}).get("verdict") or {}
    fv = ((fl or {}).get("metrics") or {}).get("fixloop_verdict")
    wdir = next(
        (
            run_dir / "work" / n
            for n in _workdir_names(pid)
            if (run_dir / "work" / n).is_dir()
        ),
        None,
    )
    pdf = bool(wdir and list((wdir / "splice").glob("*.pdf"))) if wdir else False
    return {
        "cells": st,
        "verdict": v.get("status"),
        "category": v.get("category"),
        "fixloop_verdict": fv,
        "splice_pdf": pdf,
    }


def _diff(a: dict, b: dict, name_a: str, name_b: str) -> list[str]:
    """end-state 对账行（M5：波前后迁移判读固化）。"""
    lines = []
    keys = sorted(set(a["cells"]) | set(b["cells"]))
    for k in keys:
        sa, sb = a["cells"].get(k, "—"), b["cells"].get(k, "—")
        mark = "  " if sa == sb else "→ "
        lines.append(f"{mark}{k}: {sa} → {sb}")
    for label in ("verdict", "category", "fixloop_verdict", "splice_pdf"):
        va, vb = a.get(label), b.get(label)
        if va != vb:
            lines.append(f"→ {label}: {va} → {vb}")
    if not any(l.startswith("→") for l in lines):
        lines.append(f"（{name_a} ≡ {name_b}：无迁移）")
    return lines


# ---------------------------------------------------------------- build/render


def build_dossier(
    pid: str,
    run_dir: Path,
    *,
    all_runs: bool = False,
    diff_dir: Path | None = None,
) -> dict:
    recs = load_stage_records(run_dir, pid)
    cases = load_cases(run_dir, pid)
    wdir = next(
        (
            run_dir / "work" / n
            for n in _workdir_names(pid)
            if (run_dir / "work" / n).is_dir()
        ),
        run_dir / "work" / _workdir_names(pid)[0],
    )
    inv = work_inventory(wdir)
    d = {
        "id": pid,
        "run": str(run_dir),
        "identity": _identity(pid, recs),
        "signature": _signature(recs),
        "evidence": _evidence(run_dir, pid, recs, cases, inv),
        "history": _history(pid, run_dir, recs),
        "rules": _rules_section(recs, cases, inv),
        "gap_flags": _gap_flags(recs, inv),
        "attribution": _attribution(recs, inv),
        "stages": _latest(recs),
        "cases": cases,
        "work": inv,
        "taxonomy_engine": "fixloop.ruleset" if _ruleset() else "unavailable",
    }
    if all_runs:
        d["all_runs"] = _cross_run(pid)
    if diff_dir is not None:
        d["diff"] = {
            "a": _end_state(run_dir, pid),
            "b": _end_state(diff_dir, pid),
            "a_name": run_dir.name,
            "b_name": diff_dir.name,
        }
    return d


def render_md(d: dict) -> str:
    L: list[str] = []
    idn = d["identity"]
    L.append(f"# dossier: {d['id']}")
    L.append("")
    L.append(
        f"- run: `{d['run']}` ｜ layer={idn.get('layer')} era={idn.get('era')} "
        f"channel={idn.get('channel')}"
    )
    L.append(
        f"- main={idn.get('main_rel')} engine={idn.get('engine')} "
        f"bytes={idn.get('uncompressed_bytes')}"
    )
    sig = d["signature"]
    v = sig.get("verdict") or {}
    L.append(
        f"- sig=`{sig.get('sig_raw')}` bucket=`{sig.get('sig_bucketed')}` "
        f"verdict={v.get('status')}/{v.get('category')}:{v.get('payload')} "
        f"errs={v.get('n_errors')} cjk={v.get('cjk_chars')} warn_hit={v.get('warnings_hit')}"
    )
    if sig.get("fix_class_hint"):
        L.append(f"- fix_class_hint: {sig['fix_class_hint']}")
    gf = d["gap_flags"]
    flags = [k for k, on in gf.items() if on]
    L.append(f"- gap_flags: {', '.join(flags) or '无'}")
    L.append(f"- taxonomy_engine: {d['taxonomy_engine']}")
    L.append("")
    # 证据
    ev = d["evidence"]
    L.append("## 证据")
    L.append("")
    if ev.get("first_error_line"):
        L.append(f"- first_error: `{ev['first_error_line']}`")
    if ev.get("first_error_taxonomy"):
        t = ev["first_error_taxonomy"]
        L.append(f"- first_error→taxonomy: `{t.get('category')}:{t.get('payload')}`")
    L.append(
        f"- repro: `{ev.get('repro_path')}` splice={'✓' if ev.get('splice_dir') else '—'} "
        f"_texmf={'✓' if ev.get('texmf_tree') else '—'}"
    )
    if ev.get("log_excerpt"):
        L.append(f"- log_excerpt: `{ev['log_excerpt']}`")
    L.append("")
    # 时间线
    L.append("## 阶段链时间线（append 序全量）")
    L.append("")
    L.append("| stage | arm | upstream | status | dur_s | sig |")
    L.append("|---|---|---|---|---|---|")
    for r in d["history"]["timeline"]:
        L.append(
            f"| {r['stage']} | {r.get('arm') or '-'} | {r.get('upstream') or '-'} "
            f"| **{r.get('status')}** | {r.get('dur_s')} | `{r.get('sig') or '-'}` |"
        )
    L.append("")
    for c in d["history"]["csb_chain"]:
        mark = " ⚠stale" if c["stale"] else ""
        L.append(f"- csb={c['csb']} vs compile_now={c['compile_now']}{mark}")
    if d["history"]["prior_tickets"]:
        L.append(f"- prior_tickets: {d['history']['prior_tickets']}")
    if d["history"]["prior_waves"]:
        L.append(f"- prior_waves: {d['history']['prior_waves']}")
    L.append("")
    # 规则面
    ru = d["rules"]
    L.append("## 规则面")
    L.append("")
    if ru.get("taxonomy_class"):
        t = ru["taxonomy_class"]
        L.append(
            f"- taxonomy_class: `{t.get('category')}:{t.get('payload')}`"
            f"（{t.get('source')}）"
        )
    elif d["taxonomy_engine"] == "unavailable":
        L.append("- taxonomy_class: —（texlate.* 不可达——`uv run` 重跑可得）")
    if ru.get("retired_name") is not None:
        L.append(f"- retired_name: {ru['retired_name']}")
    if ru.get("candidate_rules"):
        L.append(f"- candidate_rules: {ru['candidate_rules']}")
    for h in ru.get("rule_hit_history") or []:
        L.append(f"- hit: {h}")
    L.append("")
    # 归因
    L.append("## 归因")
    L.append("")
    for line in d["attribution"]:
        L.append(f"- {line}")
    L.append("")
    # fixloop 案卷
    if d["cases"]:
        L.append("## fixloop 案卷（cases.jsonl）")
        L.append("")
        for c in d["cases"]:
            L.append(
                f"- cond={c.get('cond')} verdict=**{c.get('verdict')}** "
                f"final_pdf={c.get('final_pdf')} started_fail={c.get('started_fail')}"
            )
            for rd in c.get("rounds") or []:
                L.append(
                    f"  - r{rd.get('round')}: cat={rd.get('cat')} pay={rd.get('pay')} "
                    f"pdf={rd.get('pdf')} errs={rd.get('n_errors')}"
                )
            for a in c.get("actions") or []:
                L.append(f"  - action[{a.get('rule')}]: {a.get('result')}")
            if c.get("installed"):
                L.append(f"  - installed: {c['installed']}")
            if c.get("advisories"):
                L.append(f"  - advisories: {c['advisories']}")
        L.append("")
    # 产物树
    inv = d["work"]
    L.append("## 产物树")
    L.append("")
    if not inv.get("present"):
        L.append("work/{id}/ 不在场。")
    else:
        for sub in ("src", "zh", "splice", "build-base", "_texmf", "xlat-state"):
            s = inv.get(sub)
            if s:
                L.append(f"- `{sub}/` {s['files']} 文件 {s['bytes']}B")
        pj = inv.get("parse")
        if pj:
            L.append(
                f"- parse.json: status={pj.get('status')} main={pj.get('main_rel')} "
                f"eng={pj.get('engine_resolved')} reject={pj.get('route_reject')} "
                f"totals={pj.get('totals')} parse_fail={pj.get('parse_fail')}"
            )
        xa = inv.get("xlat_arm")
        if xa:
            L.append(
                f"- zh/.xlat-arm.json: arm={xa.get('arm')} model={xa.get('model')} ts={xa.get('ts')}"
            )
        for name, xs in (inv.get("xlat_arms") or {}).items():
            L.append(f"- `{name}`: {xs['counts']}（共 {xs['total']} 块）")
            for b in xs["bad"]:
                L.append(f"  - ✗ {b['chunk_id']} {b['status']} {b['error_kind']}")
        for sub in ("splice", "build-base"):
            c = inv.get(f"{sub}_compile")
            if not c:
                continue
            L.append(f"- {sub} 编译面: pdf={c['pdf'] or '无'} log={c['log_name']}")
            t = c.get("taxonomy")
            if t:
                L.append(
                    f"  - taxonomy=`{t['category']}:{t['payload']}` bang×{t['n_bang']} "
                    f"line={t.get('line_no')} stack={t.get('file_stack')} warn={t.get('warnings')}"
                )
        if inv.get("texmf_installed"):
            L.append(f"- _texmf 装落: {inv['texmf_installed']}")
    L.append("")
    # diff
    if d.get("diff"):
        dd = d["diff"]
        L.append(f"## 波前后 diff（{dd['a_name']} → {dd['b_name']}）")
        L.append("")
        for ln in _diff(dd["a"], dd["b"], dd["a_name"], dd["b_name"]):
            L.append(f"- {ln}")
        L.append("")
    if d.get("all_runs"):
        L.append("## 跨 run 出现史")
        L.append("")
        L.append("| run | workdir | stages |")
        L.append("|---|---|---|")
        for r in d["all_runs"]:
            stages = " ".join(f"{k}={','.join(v)}" for k, v in r["stages"].items())
            L.append(f"| {r['run']} | {'✓' if r['workdir'] else '—'} | {stages or '—'} |")
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- selftest


def selftest() -> int:
    """合成假 run（records+work）→ dossier 全链自检。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        run = Path(td) / "stagerun-t-2099-01-01"
        (run / "records").mkdir(parents=True)
        wdir = run / "work" / "9999.0001"
        (wdir / "zh").mkdir(parents=True)
        (wdir / "splice").mkdir(parents=True)
        (wdir / "zh" / ".xlat-arm.json").write_text('{"arm":"mock"}', encoding="utf-8")
        (wdir / "parse.json").write_text(
            json.dumps(
                {
                    "id": "9999.0001",
                    "status": "ok",
                    "main_rel": "m.tex",
                    "engine_resolved": "xelatex",
                    "route": {},
                    "totals": {"chunks": 3},
                }
            ),
            encoding="utf-8",
        )
        (wdir / "splice" / "m.log").write_text(
            "x\n! LaTeX Error: File `foo.sty' not found.\ny\n", encoding="utf-8"
        )
        (wdir / "xlat-mock.jsonl").write_text(
            '{"chunk_id":"0:0","status":"ok"}\n'
            '{"chunk_id":"0:1","status":"fault","error_kind":"timeout"}\n',
            encoding="utf-8",
        )
        recs = {
            "ingest": [{"id": "9999.0001", "stage": "ingest", "arm": "-", "status": "ok", "dur_s": 0.1, "metrics": {}, "errors": [], "sig": ""}],
            "parse": [{"id": "9999.0001", "stage": "parse", "arm": "-", "status": "ok", "dur_s": 0.2, "metrics": {"main_rel": "m.tex", "engine_resolved": "xelatex", "route": {}, "totals": {"chunks": 3}}, "errors": [], "sig": ""}],
            "xlat": [{"id": "9999.0001", "stage": "xlat", "arm": "mock", "status": "ok", "dur_s": 1.0, "metrics": {"translate": {"chunks": 2, "ok": 1, "fault": 1}}, "errors": [], "sig": ""}],
            "compile": [{"id": "9999.0001", "stage": "compile", "arm": "zh", "status": "fail", "dur_s": 1.0, "metrics": {"engine": "xelatex", "verdict": {"status": "fail", "category": "missing_file", "payload": "foo.sty", "cjk_chars": -1}, "compile": {"pdf_bytes": 0, "first_error": "! LaTeX Error: File `foo.sty' not found."}, "inject": {"status": "injected", "mode": "ctex"}}, "errors": [{"code": "missing_file", "cat": "missing_file", "payload": "foo.sty"}], "sig": "missing_file:foo.sty"}],
            "fixloop": [{"id": "9999.0001", "stage": "fixloop", "arm": "fix", "status": "clean", "dur_s": 2.0, "metrics": {"compile_status_before": "fail", "fixloop_verdict": "clean", "rounds": 1}, "errors": [], "sig": "clean"}],
        }
        for st, rows in recs.items():
            (run / "records" / f"{st}.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
            )
        d = build_dossier("9999.0001", run)
        md = render_md(d)
        for needle in (
            "断点=compile",
            "missing_file:foo.sty",
            "0:1",
            "xelatex",
            "first_error",
            "csb=fail",
        ):
            assert needle in md, f"缺 {needle}\n{md}"
        assert d["gap_flags"]["needs_subclass"] is False
        assert d["signature"]["sig_raw"] == "missing_file:foo.sty"
        print("selftest ok")
        return 0


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("id", nargs="?", help="arxiv id（astro-ph/0111038 或 0707.0128）")
    p.add_argument("--run", type=Path, help="stagerun run 目录（缺省自动选最新含此 id 者）")
    p.add_argument("--diff", type=Path, metavar="DIR", help="与另一 run 做 end-state 对账（M5 波前后）")
    p.add_argument("--all-runs", action="store_true", help="附跨 run 出现史")
    p.add_argument("--json", action="store_true", help="机读 dossier dict 输出")
    p.add_argument("-o", "--out", type=Path, help="写文件（缺省 stdout）")
    p.add_argument("--selftest", action="store_true", help="合成假 run 自检")
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.id:
        p.error("id 必填（或 --selftest）")
    run_dir = args.run or pick_run(args.id)
    if run_dir is None:
        print(f"error: {args.id} 不在任何 {RESULTS}/*/records/ run 里", file=sys.stderr)
        return 2
    d = build_dossier(args.id, run_dir, all_runs=args.all_runs, diff_dir=args.diff)
    text = (
        json.dumps(d, ensure_ascii=False, indent=1, default=str)
        if args.json
        else render_md(d)
    )
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
