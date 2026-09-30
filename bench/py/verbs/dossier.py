"""dossier — per-id 跨阶段案卷：签名→证据→历史→规则链 一键出卷（index 版）。

``bench dossier ID [--run RUN] [--diff RUN] [--all-runs] [--json] [-o OUT]``

数据源映射（旧 report/dossier.py → index）:
  results/*/records/{stage}.jsonl → records 表 ``WHERE idc IN (变体)`` 全量
    append 史（(run_seq, seq) 序——波次可辨）;
  cases.jsonl                    → cases 表 payload 列;
  tickets*.jsonl                 → RUNDIR/derived/tickets*.jsonl（triage 动
    词产物，缺席容忍——动词单向依赖，不在线重算）;
  work/{safe_id}/                → RUNDIR/work/{safe_id(idc)}/，被 prune 收
    档时降级 vault.query(idc) 列副本（「现场已收档」语义）;
  run_meta.json                  → runs 表行 + RUNDIR/invocations.jsonl
    （flags 是整 run 级 spec params——无 per-stage argv）;
  RESULTS glob                   → runs 表 run_seq 序。

id 归一经 ``idnorm.canon_id`` 单源：canon 不可解（invalid/ambig）直接报错
exit 2——不猜；查无此人（canon ok 但无账）另行报 exit 2。
VENDORED_INV 面按 dossier 决议丢弃（老物随 results/ 死，新 run 无 vendored
概念）。只读：不改任何 index/vault。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

from kernel import idnorm, paths, vault
from kernel import index as index_mod

from verbs._common import (
    _STAGE_SUFFIXES,
    _all_runs,
    _iter_jsonl,
    _stem_group,
    _stem_of,
)

BENCH = Path(__file__).resolve().parents[2]
REPO = BENCH.parent
CORPUS = BENCH / "corpus"

try:  # taxonomy 需 texlate 系依赖——bare python3 下由 main() 里
    # _maybe_reexec_venv 切仓内 .venv 重入；仍不可用时降级 sig 级
    from texlate.compile.fixloop.engine import load_ruleset
    from texlate.compile.logparse import parse_log, parse_text

    _TAX_OK = True
except Exception:
    _TAX_OK = False

try:  # triage 动词产物复用（bucket_sig/classify/retired_names——缺席降级）
    from verbs import triage as _triage_mod
except Exception:
    _triage_mod = None


def _triage_fn(name: str):
    fn = getattr(_triage_mod, name, None) if _triage_mod is not None else None
    return fn if callable(fn) else None


STAGES = _STAGE_SUFFIXES  # 阶段词表单源在 verbs/_common.py（原同内容双 tuple）
_FAIL_WORDS = {"fail", "error", "reject", "crash", "timeout"}
_SUBCLASS_SIGS = ("other", "syntax", "unfixable:other")
_WONTFIX_CATS = {"early_eof", "capacity", "latex209", "inject"}
_EXCERPT_HEAD = 600

_RULESET: list = [None]  # 懒装格：[None]=未装 [False]=装败（免 global）


def _ruleset():
    if not _TAX_OK:
        return None
    if _RULESET[0] is None:
        try:
            _RULESET[0] = load_ruleset()
        except Exception:
            _RULESET[0] = False
    return _RULESET[0] or None


def _maybe_reexec_venv() -> None:
    """bare python3 缺 httpx/regex → texlate.compile 面全灭；仓内 .venv 在
    且当前非其解释器时，execve 重入整个 bench 进程（env 闸防环）。

    纯 python 包可借 addsitedir 混用，但 regex 是 C 扩展且 .venv=py3.12
    vs 系统 py3.14 副版本错位——只有整进程切解释器一条路。
    """
    if _TAX_OK or os.environ.get("TEXLATE_BENCH_REEXEC"):
        return
    venv_py = REPO / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        return
    with contextlib.suppress(OSError):
        if Path(sys.executable).resolve() == venv_py.resolve():
            return
    shim = BENCH / "py" / "bench"
    env = dict(os.environ, TEXLATE_BENCH_REEXEC="1")
    os.execve(  # noqa: S606 — 解释器重入非 shell 起进程
        str(venv_py), [str(venv_py), str(shim), *sys.argv[1:]], env
    )


def _open_index() -> index_mod.Index:
    return index_mod.open_index()


def _load_registry():
    try:
        return idnorm.PapersRegistry.load()
    except Exception:
        return None


# ---------------------------------------------------------------- run 解析


def _resolve_run_group(idx, run_arg: str):
    """run 名 → 账组 runs 行（import 拆账的 *_records_<stage> 兄弟并组）。

    精确 → 前缀唯一 → stem 并组；跨 stem 即歧义 (None, err)。
    """
    rows = _all_runs(idx)
    seeds = [r for r in rows if r.get("run") == run_arg]
    if not seeds:
        seeds = [r for r in rows if str(r.get("run")).startswith(run_arg)]
    if not seeds:
        return None, f"run not found: {run_arg!r}"
    return _stem_group(rows, seeds, run_arg)


def _rundir(run_row: dict | None) -> Path | None:
    if not run_row:
        return None
    k, d, s = run_row.get("kind"), run_row.get("date"), run_row.get("slug")
    if not all(isinstance(x, str) for x in (k, d, s)):
        return None
    p = paths.run_dir(k, d, s)
    return p if p.is_dir() else None


# ---------------------------------------------------------------- records/cases 读取


def _unblob(val, blob_dir: Path | None):
    """{"$blob":sha} 标记 → run derived/blobs 真值（读侧镜像 ctx._unblob）。"""
    if not (isinstance(val, dict) and isinstance(val.get("$blob"), str)):
        return val
    if blob_dir is None:
        return val
    try:
        return json.loads(
            (blob_dir / f"{val['$blob']}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return val


def _row_to_rec(d: dict) -> dict:
    """index 行 → 旧 records 形（``up``→``upstream``，id 取 idc 正形）。"""
    blob_dir = None
    k, dt, s = d.get("kind"), d.get("date"), d.get("slug")
    if all(isinstance(x, str) for x in (k, dt, s)):
        blob_dir = paths.run_dir(k, dt, s) / "derived" / "blobs"
    for col in ("metrics", "errors"):
        v = d.get(col)
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                v = None
        d[col] = _unblob(v, blob_dir)
    d["upstream"] = d.get("up")
    d["id"] = d.get("idc") or d.get("id")
    return d


def _fetch_records(idx, cands: list[str], runs: list[str] | None = None):
    """该 id 全部账（跨 run append 序 (run_seq, seq)）→ rec 行 list。"""
    ph = ",".join("?" for _ in cands)
    sql = (
        "SELECT r.*, ru.run_seq, ru.kind, ru.date, ru.slug"  # noqa: S608 — 值全走占位符参数化
        " FROM records r LEFT JOIN runs ru ON ru.run = r.run"
        f" WHERE (r.idc IN ({ph}) OR r.id IN ({ph}))"
    )
    args = list(cands) + list(cands)
    if runs:
        rph = ",".join("?" for _ in runs)
        sql += f" AND r.run IN ({rph})"
        args += list(runs)
    sql += " ORDER BY COALESCE(ru.run_seq, 9223372036854775807), r.seq"
    return [_row_to_rec(dict(r)) for r in idx.conn.execute(sql, args)]


def _fetch_cases(idx, cands: list[str], runs: list[str] | None = None):
    """cases 表 payload → 旧 cases.jsonl 形 dict 序列（append 序）。

    T_CELL_QUEUED 行 payload 是整个事件（无 corpus/cond/verdict 面）——
    滤到案卷形 dict（旧 cases.jsonl 语义只含 CaseSink 案卷）。
    """
    ph = ",".join("?" for _ in cands)
    sql = (
        "SELECT c.run, c.seq, c.payload, c.ts, ru.run_seq"  # noqa: S608 — 值全走占位符参数化
        " FROM cases c LEFT JOIN runs ru ON ru.run = c.run"
        f" WHERE (c.idc IN ({ph}) OR c.id IN ({ph}))"
    )
    args = list(cands) + list(cands)
    if runs:
        rph = ",".join("?" for _ in runs)
        sql += f" AND c.run IN ({rph})"
        args += list(runs)
    sql += " ORDER BY COALESCE(ru.run_seq, 9223372036854775807), c.seq"
    out = []
    for row in idx.conn.execute(sql, args):
        try:
            p = json.loads(row["payload"]) if row["payload"] else None
        except ValueError:
            continue
        if isinstance(p, dict) and ("corpus" in p or "cond" in p or "verdict" in p):
            out.append(p)
    # 旧 load_cases 语义：(corpus,cond) 键末条胜
    latest = {}
    for p in out:
        latest[(p.get("corpus"), p.get("cond"))] = p
    return list(latest.values())


def _group_stages(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(str(r.get("stage") or "?"), []).append(r)
    return out


def _rec_key(rec: dict) -> tuple[str, str, str]:
    return (
        str(rec.get("id")),
        str(rec.get("arm") or "-"),
        str(rec.get("upstream") or ""),
    )


def _latest(recs: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """每 stage 末条胜视图（(id,arm,upstream) 键，append 序后者胜）。"""
    out = {}
    for st, rows in recs.items():
        d = {}
        for r in rows:
            d[_rec_key(r)] = r
        out[st] = list(d.values())
    return out


def load_tickets(pid_cands: set[str], rundirs: list[Path]) -> list[str]:
    """derived/tickets*.jsonl 中 example_ids 含此 id 的工单 sig_id（缺席容忍）。"""
    out = []
    for rd in rundirs:
        d = rd / "derived"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("tickets*.jsonl")):
            out.extend(
                str(r.get("sig_id") or r.get("signature") or "?")
                for r in _iter_jsonl(f)
                if isinstance(r, dict)
                and pid_cands & {str(x) for x in (r.get("example_ids") or [])}
            )
    return out


def _invocations(rundir: Path | None) -> list[dict]:
    if rundir is None:
        return []
    return [r for r in _iter_jsonl(rundir / "invocations.jsonl") if isinstance(r, dict)]


# ---------------------------------------------------------------- work 树侧


def _tree_stats(d: Path) -> dict:
    n = 0
    size = 0
    for p in d.rglob("*"):
        if p.is_file():
            n += 1
            with contextlib.suppress(OSError):
                size += p.stat().st_size
    return {"files": n, "bytes": size}


def _xlat_chunk_stats(f: Path) -> dict:
    stats: dict[str, int] = {}
    bad: list[dict] = []
    for r in _iter_jsonl(f):
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
    rs = _ruleset()
    if rs is None or log_path is None or not log_path.is_file():
        return None
    try:
        rep = parse_log(log_path, warn_patterns=rs.warn_patterns)
        cat, pay = rs.taxonomy.classify(rep, timed_out=timed_out)
    except Exception:
        return None
    return {
        "category": cat,
        "payload": pay,
        "n_bang": rep.n_bang,
        "warnings": rep.warnings,
        "line_no": rep.line_no,
        "file_stack": rep.file_stack[-3:],
    }


def _classify_text(text: str) -> dict | None:
    rs = _ruleset()
    if rs is None or not text:
        return None
    try:
        rep = parse_text(text, warn_patterns=rs.warn_patterns)
        cat, pay = rs.taxonomy.classify(rep)
    except Exception:
        return None
    return {"category": cat, "payload": pay}


def _rec_taxo(rec: dict | None, *path: str) -> dict | None:
    """records 物化 taxonomy（{cat,pay}）→ {category,payload}。"""
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
        with contextlib.suppress(OSError, json.JSONDecodeError):
            inv["xlat_arm"] = json.loads(arm_f.read_text(encoding="utf-8"))
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


def _cross_run(
    rows: list[dict], group_rundirs: dict[str, Path | None], safe: str
) -> list[dict]:
    by_run: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_run.setdefault(str(r.get("run")), {})[_rec_key(r)] = r
    out = []
    for run, keyed in by_run.items():
        stages: dict[str, list[str]] = {}
        for r in keyed.values():
            st = str(r.get("stage"))
            stages.setdefault(st, []).append(f"{r.get('status')}/{r.get('arm', '-')}")
        rd = group_rundirs.get(run) or _rundir_for_name(run)
        out.append(
            {
                "run": run,
                "stages": stages,
                "workdir": bool(rd and (rd / "work" / safe).is_dir()),
            }
        )
    return out


def _rundir_for_name(run: str) -> Path | None:
    """run 名 → rundir（import-* 平名与 kind/date/slug 两形都兜）。"""
    base = paths.runs_dir()
    for cand in base.glob(f"*/*/{run.rpartition('/')[2] or run}"):
        if cand.is_dir():
            return cand
    parts = run.split("/")
    if len(parts) == 3:
        p = paths.run_dir(parts[0], parts[1], parts[2])
        if p.is_dir():
            return p
    return None


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
            out.append(f"首错类={cat} payload={pay}")
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


# ---------------------------------------------------------------- diff


def _end_state(recs: dict[str, list[dict]], wdir: Path | None) -> dict:
    """单账组的格终态面：{stage/arm: status} + verdict/fixloop 词 + pdf 在否。"""
    latest = _latest(recs)
    st: dict[str, str] = {}
    for stage, rows in latest.items():
        for r in rows:
            st[f"{stage}/{r.get('arm', '-')}"] = str(r.get("status"))
    comp = _primary_compile(recs)
    fl = _latest_of(recs, "fixloop")
    v = ((comp or {}).get("metrics") or {}).get("verdict") or {}
    fv = ((fl or {}).get("metrics") or {}).get("fixloop_verdict")
    pdf = bool(wdir and list((wdir / "splice").glob("*.pdf"))) if wdir else False
    return {
        "cells": st,
        "verdict": v.get("status"),
        "category": v.get("category"),
        "fixloop_verdict": fv,
        "splice_pdf": pdf,
    }


def _diff(a: dict, b: dict, name_a: str, name_b: str) -> list[str]:
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
    if not any(ln.startswith("→") for ln in lines):
        lines.append(f"（{name_a} ≡ {name_b}：无迁移）")
    return lines


# ---------------------------------------------------------------- build/render


def build_dossier(
    pid: str,
    cands: set[str],
    recs: dict[str, list[dict]],
    cases: list[dict],
    wdir: Path,
    inv: dict,
    *,
    run_label: str,
    run_info: dict | None = None,
    invocations: list[dict] | None = None,
    vault_copies: list[dict] | None = None,
    prior_waves: list[str] | None = None,
    prior_tickets: list[str] | None = None,
    all_runs: list[dict] | None = None,
    diff: dict | None = None,
) -> dict:
    d = {
        "id": pid,
        "run": run_label,
        "run_info": run_info,
        "invocations": invocations or [],
        "identity": _identity(pid, cands, recs),
        "signature": _signature(recs),
        "evidence": _evidence(recs, cases, inv),
        "history": _history(recs, prior_waves or [], prior_tickets or []),
        "rules": _rules_section(recs, cases, inv),
        "gap_flags": _gap_flags(recs, inv),
        "attribution": _attribution(recs, inv),
        "stages": _latest(recs),
        "cases": cases,
        "work": inv,
        "vault_copies": vault_copies or [],
        "taxonomy_engine": "fixloop.ruleset" if _ruleset() else "unavailable",
    }
    if all_runs is not None:
        d["all_runs"] = all_runs
    if diff is not None:
        d["diff"] = diff
    return d


def render_md(d: dict) -> str:
    lines: list[str] = []
    idn = d["identity"]
    lines.append(f"# dossier: {d['id']}")
    lines.append("")
    lines.append(
        f"- run: `{d['run']}` ｜ layer={idn.get('layer')} era={idn.get('era')} "
        f"channel={idn.get('channel')}"
    )
    ri = d.get("run_info") or {}
    if ri:
        lines.append(
            f"- run_info: kind={ri.get('kind')} date={ri.get('date')} "
            f"spec_hash={str(ri.get('spec_hash') or '')[:12]} "
            f"invocations={len(d.get('invocations') or [])}"
        )
    lines.append(
        f"- main={idn.get('main_rel')} engine={idn.get('engine')} "
        f"bytes={idn.get('uncompressed_bytes')}"
    )
    sig = d["signature"]
    v = sig.get("verdict") or {}
    lines.append(
        f"- sig=`{sig.get('sig_raw')}` bucket=`{sig.get('sig_bucketed')}` "
        f"verdict={v.get('status')}/{v.get('category')}:{v.get('payload')} "
        f"errs={v.get('n_errors')} cjk={v.get('cjk_chars')} warn_hit={v.get('warnings_hit')}"
    )
    if sig.get("fix_class_hint"):
        lines.append(f"- fix_class_hint: {sig['fix_class_hint']}")
    gf = d["gap_flags"]
    flags = [k for k, on in gf.items() if on]
    lines.append(f"- gap_flags: {', '.join(flags) or '无'}")
    lines.append(f"- taxonomy_engine: {d['taxonomy_engine']}")
    lines.append("")
    # 证据
    ev = d["evidence"]
    lines.append("## 证据")
    lines.append("")
    if ev.get("first_error_line"):
        lines.append(f"- first_error: `{ev['first_error_line']}`")
    if ev.get("first_error_taxonomy"):
        t = ev["first_error_taxonomy"]
        lines.append(
            f"- first_error→taxonomy: `{t.get('category')}:{t.get('payload')}`"
        )
    lines.append(
        f"- repro: `{ev.get('repro_path')}` splice={'✓' if ev.get('splice_dir') else '—'} "
        f"_texmf={'✓' if ev.get('texmf_tree') else '—'}"
    )
    if ev.get("log_excerpt"):
        lines.append(f"- log_excerpt: `{ev['log_excerpt']}`")
    lines.append("")
    # 时间线
    lines.append("## 阶段链时间线（append 序全量）")
    lines.append("")
    lines.append("| run | stage | arm | upstream | status | dur_s | sig |")
    lines.append("|---|---|---|---|---|---|---|")
    lines.extend(
        f"| {r.get('run') or '-'} | {r['stage']} | {r.get('arm') or '-'} "
        f"| {r.get('upstream') or '-'} "
        f"| **{r.get('status')}** | {r.get('dur_s')} | `{r.get('sig') or '-'}` |"
        for r in d["history"]["timeline"]
    )
    lines.append("")
    for c in d["history"]["csb_chain"]:
        mark = " ⚠stale" if c["stale"] else ""
        lines.append(f"- csb={c['csb']} vs compile_now={c['compile_now']}{mark}")
    if d["history"]["prior_tickets"]:
        lines.append(f"- prior_tickets: {d['history']['prior_tickets']}")
    if d["history"]["prior_waves"]:
        lines.append(f"- prior_waves: {d['history']['prior_waves']}")
    lines.append("")
    # 规则面
    ru = d["rules"]
    lines.append("## 规则面")
    lines.append("")
    if ru.get("taxonomy_class"):
        t = ru["taxonomy_class"]
        lines.append(
            f"- taxonomy_class: `{t.get('category')}:{t.get('payload')}`"
            f"（{t.get('source')}）"
        )
    elif d["taxonomy_engine"] == "unavailable":
        lines.append("- taxonomy_class: —（texlate.* 不可达——`uv run` 重跑可得）")
    if ru.get("retired_name") is not None:
        lines.append(f"- retired_name: {ru['retired_name']}")
    if ru.get("candidate_rules"):
        lines.append(f"- candidate_rules: {ru['candidate_rules']}")
    lines.extend(f"- hit: {h}" for h in ru.get("rule_hit_history") or [])
    lines.append("")
    # 归因
    lines.append("## 归因")
    lines.append("")
    lines.extend(f"- {line}" for line in d["attribution"])
    lines.append("")
    # fixloop 案卷
    if d["cases"]:
        lines.append("## fixloop 案卷（cases）")
        lines.append("")
        for c in d["cases"]:
            lines.append(
                f"- cond={c.get('cond')} verdict=**{c.get('verdict')}** "
                f"final_pdf={c.get('final_pdf')} started_fail={c.get('started_fail')}"
            )
            lines.extend(
                f"  - r{rd.get('round')}: cat={rd.get('cat')} pay={rd.get('pay')} "
                f"pdf={rd.get('pdf')} errs={rd.get('n_errors')}"
                for rd in c.get("rounds") or []
            )
            lines.extend(
                f"  - action[{a.get('rule')}]: {a.get('result')}"
                for a in c.get("actions") or []
            )
            if c.get("installed"):
                lines.append(f"  - installed: {c['installed']}")
            if c.get("advisories"):
                lines.append(f"  - advisories: {c['advisories']}")
        lines.append("")
    # 产物树
    inv = d["work"]
    lines.append("## 产物树")
    lines.append("")
    if not inv.get("present"):
        vc = d.get("vault_copies") or []
        if vc:
            lines.append(
                f"work/{{id}}/ 不在场——现场已收档，vault 在册副本 {len(vc)} 份:"
            )
            lines.extend(
                f"- arm={c.get('arm')} variant={c.get('variant')} "
                f"altseq={c.get('altseq')} verdict={c.get('verdict')} "
                f"bytes_ok={c.get('bytes_ok')} sha={str(c.get('sha') or '')[:12]}"
                for c in vc[:12]
            )
            lines.append("（`bench vault restore` 可取回工作树）")
        else:
            lines.append("work/{id}/ 不在场。")
    else:
        for sub in ("src", "zh", "splice", "build-base", "_texmf", "xlat-state"):
            s = inv.get(sub)
            if s:
                lines.append(f"- `{sub}/` {s['files']} 文件 {s['bytes']}B")
        pj = inv.get("parse")
        if pj:
            lines.append(
                f"- parse.json: status={pj.get('status')} main={pj.get('main_rel')} "
                f"eng={pj.get('engine_resolved')} reject={pj.get('route_reject')} "
                f"totals={pj.get('totals')} parse_fail={pj.get('parse_fail')}"
            )
        xa = inv.get("xlat_arm")
        if xa:
            lines.append(
                f"- zh/.xlat-arm.json: arm={xa.get('arm')} model={xa.get('model')} ts={xa.get('ts')}"
            )
        for name, xs in (inv.get("xlat_arms") or {}).items():
            lines.append(f"- `{name}`: {xs['counts']}（共 {xs['total']} 块）")
            lines.extend(
                f"  - ✗ {b['chunk_id']} {b['status']} {b['error_kind']}"
                for b in xs["bad"]
            )
        for sub in ("splice", "build-base"):
            c = inv.get(f"{sub}_compile")
            if not c:
                continue
            lines.append(f"- {sub} 编译面: pdf={c['pdf'] or '无'} log={c['log_name']}")
            t = c.get("taxonomy")
            if t:
                lines.append(
                    f"  - taxonomy=`{t['category']}:{t['payload']}` bang×{t['n_bang']} "
                    f"line={t.get('line_no')} stack={t.get('file_stack')} warn={t.get('warnings')}"
                )
        if inv.get("texmf_installed"):
            lines.append(f"- _texmf 装落: {inv['texmf_installed']}")
    lines.append("")
    # diff
    if d.get("diff"):
        dd = d["diff"]
        lines.append(f"## 波前后 diff（{dd['a_name']} → {dd['b_name']}）")
        lines.append("")
        lines.extend(
            f"- {ln}" for ln in _diff(dd["a"], dd["b"], dd["a_name"], dd["b_name"])
        )
        lines.append("")
    if d.get("all_runs"):
        lines.append("## 跨 run 出现史")
        lines.append("")
        lines.append("| run | workdir | stages |")
        lines.append("|---|---|---|")
        for r in d["all_runs"]:
            stages = " ".join(f"{k}={','.join(v)}" for k, v in r["stages"].items())
            lines.append(
                f"| {r['run']} | {'✓' if r['workdir'] else '—'} | {stages or '—'} |"
            )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- cli


def add_args(sp) -> None:
    sp.add_argument(
        "id", nargs="?", help="arxiv id（cat/YYMMNNN、YYMM.NNNNN 或 safe 形）"
    )
    sp.add_argument(
        "--run",
        default=None,
        help="钉 run（精确名/唯一前缀/stem——import 兄弟组自动并组；"
        "缺省选含此 id 的最新 run_seq 账组）",
    )
    sp.add_argument(
        "--diff",
        default=None,
        metavar="RUN",
        help="与另一 run 做 end-state 对账（波前后迁移）",
    )
    sp.add_argument("--all-runs", action="store_true", help="附跨 run 出现史")
    sp.add_argument(
        "--json", action="store_true", dest="as_json", help="机读 dossier dict 输出"
    )
    sp.add_argument(
        "-o", "--out", type=Path, default=None, help="写文件（缺省 stdout）"
    )


def main(args) -> int:
    _maybe_reexec_venv()
    if not args.id:
        print("dossier: id 必填", file=sys.stderr)
        return 2

    res = idnorm.canon_id(args.id, registry=_load_registry())
    if not res.ok:
        cands = f" candidates={res.candidates}" if res.candidates else ""
        print(
            f"dossier: canon 不可解 {args.id!r}: {res.reason}{cands}", file=sys.stderr
        )
        return 2
    idc = res.idc
    safe = idnorm.safe_id(idc)
    cands = list(dict.fromkeys([args.id, idc, safe]))
    cand_set = set(cands)

    idx = _open_index()

    group = None
    if args.run:
        group, err = _resolve_run_group(idx, args.run)
        if err is not None:
            print(f"dossier: {err}", file=sys.stderr)
            return 2
        run_names = [str(r["run"]) for r in group]
        rows = _fetch_records(idx, cands, run_names)
        if not rows:
            print(f"dossier: {idc} 不在 {args.run!r} 账组里", file=sys.stderr)
            return 2
    else:
        rows = _fetch_records(idx, cands)
        if not rows:
            cases_probe = _fetch_cases(idx, cands)
            if not cases_probe:
                # workdir 兜底：run_seq 倒序找 work/{safe}
                run_rows = [
                    dict(r)
                    for r in idx.conn.execute(
                        "SELECT run, run_seq, kind, date, slug FROM runs"
                        " ORDER BY run_seq DESC"
                    ).fetchall()
                ]
                hit = None
                for rr in run_rows:
                    rd = _rundir(rr)
                    if rd and (rd / "work" / safe).is_dir():
                        hit = rr
                        break
                if hit is None:
                    print(
                        f"dossier: {idc} 查无此人（records/cases/work 三路全空）",
                        file=sys.stderr,
                    )
                    return 2
                group = [hit]
                run_names = [str(hit["run"])]
            else:
                seen = {}
                for rr in idx.conn.execute(
                    "SELECT run, run_seq, kind, date, slug FROM runs"
                ):
                    seen[rr["run"]] = dict(rr)
                # cases 的 run 归属取最新出现者
                ph = ",".join("?" for _ in cands)
                crows = idx.conn.execute(
                    "SELECT DISTINCT run FROM cases"  # noqa: S608 — 值全走占位符参数化
                    f" WHERE idc IN ({ph}) OR id IN ({ph})",
                    list(cands) + list(cands),
                ).fetchall()
                best = max(
                    (seen.get(cr["run"]) for cr in crows),
                    key=lambda r: (r or {}).get("run_seq") or -1,
                    default=None,
                )
                group = [best] if best else []
                run_names = [str(best["run"])] if best else []
        else:
            latest_run = max((r for r in rows), key=lambda r: r.get("run_seq") or -1)[
                "run"
            ]
            group, _ = _resolve_run_group(idx, latest_run)
            run_names = [str(r["run"]) for r in (group or [])]
            if group and len(group) > 1:
                rows = _fetch_records(idx, cands, run_names)

    run_names = [str(r["run"]) for r in (group or [])] if group else run_names
    recs = _group_stages(rows)
    cases = _fetch_cases(idx, cands, run_names or None)
    stem = _stem_of(run_names[-1]) if run_names else idc
    run_label = stem if len(run_names) > 1 else (run_names[-1] if run_names else "-")

    # workdir：组内 run_seq 倒序找第一个有 work/{safe} 的 rundir
    primary = (group or [])[-1] if group else None
    wdir = None
    for rr in reversed(group or []):
        rd = _rundir(rr)
        if rd and (rd / "work" / safe).is_dir():
            wdir = rd / "work" / safe
            break
    if wdir is None and primary is not None:
        rd = _rundir(primary)
        wdir = (rd / "work" / safe) if rd else Path(f"<no-rundir>/{safe}")
    if wdir is None:
        wdir = Path(f"<no-run>/{safe}")
    inv = work_inventory(wdir)

    vault_copies = []
    if not inv.get("present"):
        with contextlib.suppress(Exception):
            vault_copies = vault.query(idc)

    # tickets：本组 rundirs + 全 rundir 面（prior 票史）
    group_rds = [rd for rd in (_rundir(r) for r in (group or [])) if rd]
    all_rds = [p for p in sorted(paths.runs_dir().glob("*/*/*")) if p.is_dir()]
    prior_tickets = load_tickets(cand_set, all_rds or group_rds)

    prior_waves = sorted({str(r.get("run")) for r in rows})
    primary_rd = _rundir(primary)
    run_info = primary
    invocs = _invocations(primary_rd)

    all_runs = None
    if args.all_runs:
        group_rundirs = {str(r["run"]): _rundir(r) for r in (group or [])}
        all_runs = _cross_run(rows, group_rundirs, safe)

    diff = None
    if args.diff:
        dgroup, derr = _resolve_run_group(idx, args.diff)
        if derr is not None:
            print(f"dossier: --diff {derr}", file=sys.stderr)
            return 2
        dnames = [str(r["run"]) for r in dgroup]
        drows = _fetch_records(idx, cands, dnames)
        dwdir = None
        for rr in reversed(dgroup or []):
            rd = _rundir(rr)
            if rd and (rd / "work" / safe).is_dir():
                dwdir = rd / "work" / safe
                break
        diff = {
            "a": _end_state(recs, wdir if inv.get("present") else None),
            "b": _end_state(_group_stages(drows), dwdir),
            "a_name": run_label,
            "b_name": args.diff,
        }

    d = build_dossier(
        args.id,
        cand_set,
        recs,
        cases,
        wdir,
        inv,
        run_label=run_label,
        run_info=run_info,
        invocations=invocs,
        vault_copies=vault_copies,
        prior_waves=prior_waves,
        prior_tickets=prior_tickets,
        all_runs=all_runs,
        diff=diff,
    )
    text = (
        json.dumps(d, ensure_ascii=False, indent=1, default=str)
        if args.as_json
        else render_md(d)
    )
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(text)
    return 0
