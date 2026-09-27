"""xlat-report / xlat-rejudge — xlatbench eval_records → 模型榜 + 免费重判。

旧 ``bench/py/xlatbench.py`` 的 cmd_report/cmd_rejudge 移植（samples 不
移——``bench plan`` 的格枚举已是等价面）。读面 = eval_records 末条胜
集（(idc,arm,up,variant) 键 seq 大者胜，重试格覆盖旧账）。

字段映射（旧 results.jsonl 行 → eval_records 行）：
  model→arm 列 · sample→idc 列 · run→metrics.rep（variant 'r{N}@v1'
  前缀同源互证）· judge.*→metrics 平铺键（hard_ok/validator_ok/
  validator_issues/ph_missing/ph_invented/ph_order_ok/cs_dropped/
  fragile_src/fragile_zh/en_residue_words/zh_len）· tok_*→metrics
  同名 · seconds→metrics.seconds · http→metrics.http ·
  content→metrics.zh · src→metrics.src · error→metrics.error ·
  retry_429/retried_32k/via_stream/unmetered→metrics 同名。
metrics/errors >4KB 走 $blob 卸载（run derived/blobs/）——读侧一律
kernel.report._unblob。rejudge 是纯本地重判（specs.xlatbench._judge
单源——verb 不复制判定口径）——永不触网关；缺 src/zh 的格 skip+计
数，是覆盖缺口而非可补数据。
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HELP = "xlatbench eval_records → 模型榜 / 本地重判"

_JUDGE_KEYS = (
    "hard_ok",
    "validator_ok",
    "validator_issues",
    "ph_missing",
    "ph_invented",
    "ph_order_ok",
    "cs_dropped",
    "fragile_src",
    "fragile_zh",
    "en_residue_words",
    "zh_len",
)


def _err(msg: str) -> None:
    print(f"xlat: {msg}", file=sys.stderr)


def _open_index():
    """Index + tail_ingest（cli._open_index 同式）。"""
    from kernel import index as index_mod

    idx = index_mod.Index()
    try:
        idx.tail_ingest()
    except Exception as exc:
        _err(f"note: tail_ingest failed ({exc}) — index may be stale")
    return idx


def _run_ref(ref: str):
    """run 引用 → (run_name, rundir)。kind/date/slug 或 runs/ 下目录。"""
    from kernel import paths

    p = Path(ref)
    if p.is_dir():
        try:
            rel = p.resolve().relative_to(paths.runs_dir().resolve())
        except ValueError:
            rel = None
        if rel is not None and len(rel.parts) >= 3:
            return "/".join(rel.parts[:3]), p
        _err(f"run dir outside runs/: {ref}")
        return None, None
    parts = ref.split("/")
    if len(parts) == 3:
        d = paths.run_dir(*parts)
        if d.is_dir():
            return ref, d
    _err(f"run not found: {ref!r} (need kind/date/slug or a runs/ dir)")
    return None, None


def _run_kind(idx, run_name: str) -> str | None:
    r = idx.conn.execute("SELECT kind FROM runs WHERE run=?", (run_name,)).fetchone()
    return r["kind"] if r else None


def _unblob(val, rundir: Path | None):
    from kernel import report as report_mod

    blob_dir = None
    if rundir is not None and (rundir / "derived" / "blobs").is_dir():
        blob_dir = rundir / "derived" / "blobs"
    return report_mod._unblob(val, blob_dir)


def _payload(raw, rundir: Path | None):
    """json 列 → 值 → $blob 解引用（blob 文件读不出则 marker 原样）。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return _unblob(raw, rundir)


def _eval_rows(idx, run_name: str) -> list[dict]:
    """末条胜集：(idc,arm,up,variant) 键 seq 大者胜。"""
    wins: dict[tuple, dict] = {}
    for r in idx.conn.execute(
        "SELECT seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
        "dur_s,metrics,errors,ts FROM eval_records WHERE run=? ORDER BY seq",
        (run_name,),
    ):
        wins[(r["idc"], r["arm"], r["up"], r["variant"])] = dict(r)
    return list(wins.values())


def _rec_of(row: dict, rundir: Path | None) -> dict:
    """eval_records 行 → 旧 results.jsonl 行形（aggregate 逐字复用）。"""
    m = _payload(row.get("metrics"), rundir)
    m = m if isinstance(m, dict) else {}
    variant = str(row.get("variant") or "")
    rep = variant.split("@", 1)[0].lstrip("r")
    return {
        "model": row.get("arm"),
        "sample": row.get("idc"),
        "run": m.get("rep", rep),
        "http": m.get("http"),
        "error": m.get("error"),
        "content": m.get("zh"),
        "seconds": m.get("seconds", row.get("dur_s") or 0),
        "reasoning_len": m.get("reasoning_len", 0),
        "tok_in": m.get("tok_in"),
        "tok_out": m.get("tok_out"),
        "tok_cached": m.get("tok_cached"),
        "retried_32k": m.get("retried_32k"),
        "retry_429": m.get("retry_429"),
        "src": m.get("src"),
        "judge": {k: m.get(k) for k in _JUDGE_KEYS if k in m},
    }


# ---------------------------------------------------------------- report
def _med(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * 0.95))]


def aggregate(recs: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """recs（旧行形）→ (逐模型聚合, 失败清单)——旧 aggregate 逐字。"""
    rows: dict[str, dict] = {}
    fails: list[dict] = []
    for r in recs:
        m = r["model"]
        st = rows.setdefault(
            m,
            {
                "n": 0,
                "hard_ok": 0,
                "http_err": 0,
                "empty": 0,
                "ph_miss": 0,
                "ph_inv": 0,
                "ord_bad": 0,
                "cs_drop": 0,
                "v_err": 0,
                "v_warn": 0,
                "retried": 0,
                "lat": [],
                "rsn": [],
                "tin": [],
                "tout": [],
                "tck": [],
            },
        )
        st["n"] += 1
        if r.get("retried_32k"):
            st["retried"] += 1
        if r.get("http") != 200:
            st["http_err"] += 1
            fails.append(
                {
                    "model": m,
                    "sample": r["sample"],
                    "run": r["run"],
                    "why": f"http {r.get('http')} {str(r.get('error'))[:80]}",
                }
            )
            continue
        if not r.get("content"):
            st["empty"] += 1
            fails.append(
                {
                    "model": m,
                    "sample": r["sample"],
                    "run": r["run"],
                    "why": "empty content"
                    + (f" ({str(r.get('error'))[:60]})" if r.get("error") else ""),
                }
            )
            continue
        j = r.get("judge") or {}
        st["lat"].append(r.get("seconds", 0))
        st["rsn"].append(r.get("reasoning_len", 0))
        st["tin"].append(r.get("tok_in") or 0)
        st["tout"].append(r.get("tok_out") or 0)
        st["tck"].append(r.get("tok_cached") or 0)
        for i in j.get("validator_issues") or []:
            if i.startswith("error:"):
                st["v_err"] += 1
            else:
                st["v_warn"] += 1
        if j.get("hard_ok"):
            st["hard_ok"] += 1
        else:
            why = []
            if j.get("ph_missing"):
                st["ph_miss"] += len(j["ph_missing"])
                why.append("miss:" + ",".join(j["ph_missing"]))
            if j.get("ph_invented"):
                st["ph_inv"] += len(j["ph_invented"])
                why.append("inv:" + ",".join(j["ph_invented"]))
            if j.get("cs_dropped"):
                st["cs_drop"] += 1
                why.append(f"cs {j.get('fragile_src')}→{j.get('fragile_zh')}")
            errs = [
                i for i in (j.get("validator_issues") or []) if i.startswith("error:")
            ]
            for e in errs:
                # issue 形 "error:rule:message"——message 自身可含 ':',
                # 旧 split(':',2)[-1] 会丢 message 首段; 取 rule + 完整前缀。
                parts = e.split(":", 2)
                why.append(
                    parts[1] + ":" + parts[2][:60] if len(parts) == 3 else e[:80]
                )
            fails.append(
                {
                    "model": m,
                    "sample": r["sample"],
                    "run": r["run"],
                    "why": "; ".join(why) or "?",
                    "src": r.get("src"),
                    "zh": r.get("content"),
                }
            )
        if j.get("ph_order_ok") is False:
            st["ord_bad"] += 1
    return rows, fails


def _cmd_report(args) -> int:
    idx = _open_index()
    recs: list[dict] = []
    names: list[str] = []
    first_rundir: Path | None = None
    for ref in args.runs:
        name, rdir = _run_ref(ref)
        if name is None:
            return 2
        kind = _run_kind(idx, name)
        if kind != "xlatbench":
            _err(f"{name}: kind={kind!r} skipped (xlat-report reads xlatbench runs)")
            continue
        names.append(name)
        if first_rundir is None:
            first_rundir = rdir
        recs.extend(_rec_of(row, rdir) for row in _eval_rows(idx, name))
    rows, fails = aggregate(recs)
    lines = [
        (
            "| model | n | hard_ok | ph_miss | ph_inv | cs_drop | ord_soft | "
            "http_err | lat p50/p95 | rsn p50/p95 | in_tok med | out_tok med | "
            "cached med |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    agg = {}
    for m, s in sorted(
        rows.items(), key=lambda kv: -kv[1]["hard_ok"] / max(kv[1]["n"], 1)
    ):
        pct = f"{s['hard_ok'] / s['n'] * 100:.0f}%" if s["n"] else "–"
        lines.append(
            f"| {m} | {s['n']} | {s['hard_ok']} ({pct}) | {s['ph_miss']} | "
            f"{s['ph_inv']} | {s['cs_drop']} | {s['ord_bad']} | "
            f"{s['http_err']} | {_med(s['lat']):.1f}/{_p95(s['lat']):.1f}s | "
            f"{_med(s['rsn']):.0f}/{_p95(s['rsn']):.0f}ch | "
            f"{_med(s['tin']):.0f} | {_med(s['tout']):.0f} | "
            f"{_med(s['tck']):.0f} |"
        )
        agg[m] = {
            k: (
                v
                if not isinstance(v, list)
                else {
                    "p50": _med(v),
                    "p95": _p95(v),
                    "min": min(v) if v else 0,
                    "max": max(v) if v else 0,
                }
            )
            for k, v in s.items()
        }
        agg[m]["hard_rate"] = s["hard_ok"] / s["n"] if s["n"] else None
    table = "\n".join(lines)
    print(table)
    print("\n## 失败现场\n")
    for f in fails:
        print(f"- {f['model']} {f['sample']} r{f['run']}: {f['why']}")
    if not recs:
        print("\n(no eval_records rows — run may be empty or kind filtered)")
        return 0
    out_obj = {
        # 判据 vintage 可辨：source=eval_records + runs 清单
        "source": "eval_records",
        "runs": names,
        "models": agg,
        "fails": fails,
    }
    if args.json_out:
        out_p = Path(args.json_out)
    elif first_rundir is not None:
        out_p = first_rundir / "derived" / "xlat-models.json"
    else:
        out_p = None
    if out_p is not None:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(
            json.dumps(out_obj, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {out_p} (source: eval_records)")
    if args.md:
        Path(args.md).write_text(table + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------------- rejudge
def _cmd_rejudge(args) -> int:
    """存量 metrics.src/zh 按现口径重判——validator/judge 升级后新旧
    hard_ok 对拍。纯本地，零网关。"""
    try:
        from specs.xlatbench import _judge  # 单源判定——verb 不复制口径
    except ImportError as exc:
        # spec 面是 venv-only（httpx/texlate.*）——裸 python3 下拒绝要干净
        _err(f"rejudge needs the repo venv: {exc}")
        return 2

    idx = _open_index()
    rc = 0
    for ref in args.runs:
        name, rdir = _run_ref(ref)
        if name is None:
            rc = 2
            continue
        kind = _run_kind(idx, name)
        if kind != "xlatbench":
            _err(f"{name}: kind={kind!r} skipped (xlat-rejudge reads xlatbench runs)")
            continue
        per_model: dict[str, list[int]] = {}
        flips: list[str] = []
        out_rows: list[dict] = []
        n_skip = 0
        for row in _eval_rows(idx, name):
            rec = _rec_of(row, rdir)
            if not (rec["http"] == 200 and rec["content"] and rec["src"]):
                n_skip += 1
                continue
            j_old = rec["judge"] or {}
            # 现口径 hard_ok; E22 时代硬判字段名是 ok
            old = j_old.get("hard_ok", j_old.get("ok"))
            new = _judge(rec["src"], rec["content"])
            st = per_model.setdefault(rec["model"], [0, 0, 0])
            st[0] += 1
            st[1] += int(bool(old))
            st[2] += int(new["hard_ok"])
            flip = old is not None and bool(old) != new["hard_ok"]
            if flip:
                flips.append(
                    f"{rec['model']} {rec['sample']} r{rec['run']}: "
                    f"{old}->{new['hard_ok']}"
                )
            out_rows.append(
                {
                    "id": row["id"],
                    "idc": row["idc"],
                    "arm": row["arm"],
                    "up": row["up"],
                    "variant": row["variant"],
                    "judge_old": j_old or None,
                    "judge_new": new,
                    "flip": flip,
                }
            )
        if args.out and len(args.runs) == 1:
            out_p = Path(args.out)
        else:
            out_p = rdir / "derived" / "rejudged.jsonl"
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as fp:
            for r in out_rows:
                fp.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"== {name}")
        for m, (n, old_ok, new_ok) in sorted(per_model.items()):
            print(
                f"  {m:22} hard_ok {old_ok}/{n} -> {new_ok}/{n} ({new_ok - old_ok:+d})"
            )
        for f_ in flips[:20]:
            print(f"  flip {f_}")
        if len(flips) > 20:
            print(f"  ... +{len(flips) - 20} more flips")
        if n_skip:
            print(
                f"  coverage gap: {n_skip} cells lack http200/src/zh — "
                "skipped (never fetched)"
            )
        print(f"  wrote {out_p} ({len(out_rows)} rejudgeable cells)")
    return rc


# ---------------------------------------------------------------- glue
def add_args(sp) -> None:
    verb = sp.prog.rsplit(" ", 1)[-1]
    sp.add_argument("runs", nargs="+", help="run 名 kind/date/slug 或 runs/ 下目录")
    if verb == "xlat-report":
        sp.add_argument("--md", default=None, help="聚合表落盘路径")
        sp.add_argument(
            "--json-out",
            default=None,
            help="models.json 落盘路径（默认首 run derived/xlat-models.json）",
        )
    else:  # xlat-rejudge
        sp.add_argument(
            "--out",
            default=None,
            help="重判投影（默认各 run derived/rejudged.jsonl）",
        )


def main(args) -> int:
    if args.cmd == "xlat-rejudge":
        return _cmd_rejudge(args)
    return _cmd_report(args)
