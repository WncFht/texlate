#!/usr/bin/env python3
r"""
triage.py — stagerun records → tickets.jsonl 聚类 + metrics.jsonl 趋势 + report merge。

实现 docs/research/product/2026-09-16-batch-hardening-design.md §6 文件协议 / §9 E3+E4:

  records/{stage}.jsonl   每行 {id,stage,arm,status,dur_s,metrics{..},errors[{code,cat,payload}],sig}
  tickets.jsonl           {sig_id,stage,signature,count,example_ids[],repro_path,fix_class,notes}
  metrics.jsonl           跨 run 追加 {run_id,date,stage_rates{},fixloop{..},regressions[],wall_s}
                          （全局文件 git 跟踪；冒烟/实验跑用 --no-global 只写 run 内 metrics.json）

用法:
  triage.py records DIR            # records/*.jsonl → DIR/tickets.jsonl (按 count 降序)
  triage.py metrics DIR            # 算本 run 汇总, 追加 bench/results/metrics.jsonl (= DIR 父目录)
  triage.py report DIR             # records + tickets → DIR/report.md
  triage.py all DIR                # 三连
  triage.py --selftest             # 合成假 records/ 全链自检

旧 harness 目录 (无 records/) 自动降级: 从 results.json verdict + cases.jsonl
推 pseudo-records, records 子命令产出 tickets-legacy.jsonl (不污染新管线命名)。
纯 stdlib + 可选 pyyaml (读 rules.yaml shim_map); 系统 python3 可跑。
"""

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
REPO = BENCH.parent
RULES_YAML = REPO / "src/texlate/compile/fixloop/rules.yaml"

# 记录状态词汇: ok 系不出票; skip 系(上游断/policy 拒)不计入 attempted。
OK_STATUS = {"ok", "clean", "done"}
SKIP_STATUS = {"skip", "skipped", "reject", "rejected", "upstream_fail"}
# fixloop 救援成功的终态 (含带伤出 pdf)。
RESCUED_STATUS = {
    "ok",
    "clean",
    "acceptable_pdf",
    "best_effort_pdf",
    "dirty_pdf",
    "partial",
}
# fixloop 终态词 → core 单 (规则面之外的引擎缺口)。
TERMINAL_WORDS = {"stuck", "max_rounds"}

MAX_EXAMPLES = 5
MAX_REG_IDS = 50
TOP_UNFIXABLE = 10
TOP_TICKETS_MD = 20

# 退役/改名包常识集 (F1 的 elsart.cls 这类——还没进 shim_map 的也算 shim_table 候选)。
KNOWN_RETIRED = {"elsart.cls", "aastex.cls", "aastex63.cls", "revtex.cls", "psfig.sty"}


# ---------- 读 records ----------


def _read_jsonl(path):
    bad = 0
    for ln in path.read_text(errors="replace").splitlines():
        line = ln.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            bad += 1
    if bad:
        print(f"  warn: {path.name} 跳过 {bad} 行坏 json", file=sys.stderr)


def load_records(results_dir):
    """records/{stage}.jsonl → list[dict]; stage 缺省取文件名。"""
    recs = []
    rdir = results_dir / "records"
    if not rdir.is_dir():
        return recs
    for fp in sorted(rdir.glob("*.jsonl")):
        stage = fp.stem
        for rec in _read_jsonl(fp):
            if isinstance(rec, dict):
                rec.setdefault("stage", stage)
                recs.append(rec)
    return recs


# ---------- sig 解析与归类 ----------


def record_sig(rec):
    """record → sig: 优先 rec['sig']; 否则 errors[0] 合成 cat:pay; 兜底 nosig:status。"""
    sig = str(rec.get("sig") or "").strip()
    if sig:
        return sig
    errs = rec.get("errors") or []
    if errs and isinstance(errs[0], dict):
        cat = errs[0].get("cat") or errs[0].get("code") or "error"
        pay = errs[0].get("payload")
        return f"{cat}:{pay}" if pay not in (None, "") else str(cat)
    return f"nosig:{rec.get('status') or 'unknown'}"


def parse_sig(sig):
    """剥 verdict 前缀后取 (cat, pay): 'unfixable:missing_file:x.cls' → ('missing_file','x.cls')。"""
    s = sig
    for pre in ("unfixable:", "reject:", "nosig:"):
        if s.startswith(pre):
            s = s[len(pre) :]
            break
    if ":" in s:
        cat, pay = s.split(":", 1)
    else:
        cat, pay = s, ""
    return cat.strip(), pay.strip()


def retired_names():
    """rules.yaml legacy_pkg_shim.shim_map 键 ∪ 常识集; yaml 不可用时退回常识集。"""
    names = set(KNOWN_RETIRED)
    try:
        import yaml

        doc = yaml.safe_load(RULES_YAML.read_text()) or {}
        for rule in doc.get("rules") or []:
            if rule.get("id") == "legacy_pkg_shim":
                names |= set(
                    ((rule.get("action") or {}).get("params") or {}).get("shim_map")
                    or {}
                )
    except Exception as e:  # shim 表只是归类提示, 读不到不致命
        print(
            f"  warn: rules.yaml shim_map 读取失败 ({e}); 用内置退役表", file=sys.stderr
        )
    return names


def classify(sig, rep):
    """(sig, 代表 record) → (fix_class, note)。

    顺序: 具体 cat 先判 (unfixable:missing_file:elsart.cls 也是 shim_table 单 — F1),
    终态词兜底 core; 其余 rule 留人工。
    """
    cat, pay = parse_sig(sig)
    if not pay:
        errs = rep.get("errors") or []
        if errs and isinstance(errs[0], dict):
            pay = str(errs[0].get("payload") or "")
    base = Path(pay).name if pay else ""

    if cat == "missing_file" and base and base in retired_names():
        return "shim_table", f"{base} 退役/改名包 → legacy_pkg_shim shim_map 扩列 (F1)"
    if cat == "missing_file":
        return (
            "rule",
            f"{base or pay or '?'} 非退役名 → install_file 应覆盖; 查 filemap.overrides/为何装不上",
        )
    if cat == "undefined_cs":
        return (
            "rule",
            "undefined_cs 逐签名归因 (F2): 缺包→filemap.overrides/cs_targeted_fix; 笔误→llm_hook",
        )
    if cat == "missing_character":
        return "rule", "CJK 缺字类规则可扩性 (F4)"
    if cat == "latex209":
        return (
            "wontfix",
            "LaTeX2.09 路由层拒绝 (F3: verdict 语义 reject→partial, 非缺陷)",
        )
    if sig.startswith("unfixable:") or sig in TERMINAL_WORDS:
        return "core", "fixloop 终态 → 规则面外的引擎/taxonomy 缺口"
    return "rule", "待人工归因"


# ---------- records → tickets ----------


def build_tickets(recs, results_dir):
    """(stage, sig) 聚类非 ok/skip 记录 (显式 sig 的 ok 记录也留票——warning 级)。

    返回按 count 降序的 ticket dict 列表。
    """
    clusters = {}
    for rec in recs:
        st = str(rec.get("status") or "")
        has_sig = bool(str(rec.get("sig") or "").strip())
        has_err = bool(rec.get("errors"))
        if st in OK_STATUS | SKIP_STATUS and not (has_sig or has_err):
            continue
        key = (str(rec.get("stage") or "?"), record_sig(rec))
        clusters.setdefault(key, []).append(rec)

    tickets = []
    for (stage, sig), rs in clusters.items():
        ids = []
        for r in rs:
            rid = str(r.get("id") or "?")
            if rid not in ids:
                ids.append(rid)
        repro = None
        for rid in ids:
            if (results_dir / "work" / rid).is_dir():
                repro = f"work/{rid}/"
                break
        rep = rs[0]
        fix_class, note = classify(sig, rep)
        sts = Counter(str(r.get("status") or "?") for r in rs)
        if set(sts) <= OK_STATUS:
            note += "; 全部落在 ok 记录上 (warning 级)"
        elif len(sts) > 1:
            note += f"; 状态分布 {dict(sts)}"
        tickets.append(
            {
                "sig_id": None,  # 排序后回填
                "stage": stage,
                "signature": sig,
                "count": len(rs),
                "example_ids": ids[:MAX_EXAMPLES],
                "repro_path": repro,
                "fix_class": fix_class,
                "notes": note,
            }
        )
    tickets.sort(key=lambda t: (-t["count"], t["stage"], t["signature"]))
    for i, t in enumerate(tickets, 1):
        t["sig_id"] = f"{t['stage']}-{i:03d}"
    return tickets


# ---------- 旧 harness 降级 (results.json / cases.jsonl → pseudo-records) ----------

# arm key → (stage, arm)。e2e_real 三格: pipe-xel=编中(base 对照), base-xel, pipe-fix。
LEGACY_ARM_MAP = {"pipe-xel": ("compile", "zh"), "base-xel": ("compile", "base")}

RE_MISSING_FILE = re.compile(r"File `([^']+)' not found")
RE_MISSING_CHAR = re.compile(r"missing_character[×x](\d+)")


def _legacy_sig(verdict, first_error):
    """verdict 块 → sig: cat 为主, cat 模糊 (clean/other/None) 时退回 reasons 头。"""
    vstatus = verdict.get("status")
    if vstatus in ("clean", None):
        return ""
    cat = verdict.get("category")
    reasons = [str(r).strip() for r in (verdict.get("reasons") or []) if str(r).strip()]
    if cat in (None, "clean", "other"):
        if any(r.startswith("missing_character") for r in reasons):
            cat = "missing_character"
        elif cat in (None, "clean") and reasons:
            head = reasons[0]
            cat = (
                head.split("=", 1)[1].split(":")[0]
                if head.startswith("first_error=")
                else head.split()[0]
            )
    pay = ""
    if cat == "missing_file":
        m = RE_MISSING_FILE.search(first_error or "")
        if m:
            pay = m.group(1)
    elif cat == "missing_character":
        m = RE_MISSING_CHAR.search(" ".join(reasons))
        if m:
            pay = f"x{m.group(1)}"
    if not cat:
        return f"verdict:{vstatus}"
    return f"{cat}:{pay}".rstrip(":")


def legacy_records(results_dir):
    """旧 results.json → record 形状列表。fixloop 细节取 pipe-fix.fixloop / cases.jsonl。"""
    rp = results_dir / "results.json"
    if not rp.exists():
        return []
    data = json.loads(rp.read_text())
    recs = []
    for key, rec in data.items():
        if not isinstance(rec, dict):
            continue
        rid = str(rec.get("id") or key)
        for arm_key, (stage, arm) in LEGACY_ARM_MAP.items():
            cell = rec.get(arm_key)
            if not isinstance(cell, dict):
                continue
            verdict = cell.get("verdict") or {}
            vstatus = verdict.get("status") or cell.get("status") or "?"
            sig = _legacy_sig(verdict, (cell.get("compile") or {}).get("first_error"))
            cat, pay = parse_sig(sig) if sig else ("", "")
            recs.append(
                {
                    "id": rid,
                    "stage": stage,
                    "arm": arm,
                    "status": {"clean": "ok", "reject": "reject"}.get(vstatus, vstatus),
                    "dur_s": (cell.get("compile") or {}).get("seconds"),
                    "metrics": {
                        "translate": cell.get("translate") or {},
                        "verdict": verdict,
                    },
                    "errors": [{"code": cat, "cat": cat, "payload": pay}]
                    if sig
                    else [],
                    "sig": sig,
                }
            )
        # pipe-fix → fixloop stage: 内部 verdict 即签名主体
        fix = rec.get("pipe-fix") or {}
        fl = fix.get("fixloop") if isinstance(fix, dict) else None
        if isinstance(fl, dict) and fl.get("verdict"):
            rounds = fl.get("rounds") or []
            last = (rounds[-1] or {}) if rounds else {}
            fcat = fl.get("final_cat") or last.get("category") or last.get("cat")
            fpay = ""  # 取最末一个非空 pay (末轮常为 null)
            for rd in reversed(rounds):
                if rd and (rd.get("pay") or rd.get("payload")):
                    fpay = rd.get("pay") or rd.get("payload")
                    break
            fv = str(fl["verdict"])
            sig = fv
            if fv.startswith("unfixable:") and fcat and f"{fcat}" not in fv:
                sig = f"{fv}:{fcat}"
            if fpay:
                sig = f"{sig}:{fpay}"
            status = (
                "ok"
                if fv in RESCUED_STATUS and fl.get("final_pdf")
                else ("partial" if fv == "dirty_pdf" else "fail")
            )
            recs.append(
                {
                    "id": rid,
                    "stage": "fixloop",
                    "arm": "fix",
                    "status": status,
                    "dur_s": None,
                    "metrics": {
                        "fixloop_verdict": fv,
                        "final_errors": fl.get("final_errors"),
                    },
                    "errors": [{"code": fv, "cat": fcat, "payload": fpay}]
                    if status != "ok"
                    else [],
                    "sig": sig if status != "ok" else "",
                }
            )
        elif isinstance(fix, dict) and fix.get("status"):
            # 有 pipe-fix 格但无 fixloop 细节
            vstatus = fix.get("status")
            recs.append(
                {
                    "id": rid,
                    "stage": "fixloop",
                    "arm": "fix",
                    "status": {"clean": "ok"}.get(vstatus, vstatus),
                    "dur_s": None,
                    "metrics": {},
                    "errors": [],
                    "sig": "" if vstatus == "clean" else f"verdict:{vstatus}",
                }
            )
        # 整格崩 (无 arm 细胞) → harness 票, 不静默吞
        if not any(isinstance(rec.get(k), dict) for k in (*LEGACY_ARM_MAP, "pipe-fix")):
            st = rec.get("status") or "?"
            recs.append(
                {
                    "id": rid,
                    "stage": "harness",
                    "arm": "-",
                    "status": st,
                    "dur_s": rec.get("seconds"),
                    "metrics": {},
                    "errors": [{"code": st, "cat": None, "payload": rec.get("error")}],
                    "sig": f"harness:{st}",
                }
            )
    return recs


# ---------- metrics ----------


def _run_meta(results_dir):
    mp = results_dir / "run_meta.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _iso(s):
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def _wall_s(results_dir, recs, meta):
    t0, t1 = (
        _iso(meta.get("started_at")),
        _iso(
            meta.get("finished_at") or meta.get("ended_at") or meta.get("completed_at")
        ),
    )
    if t0 and t1 and t1 > t0:
        return round((t1 - t0).total_seconds(), 1)
    return round(sum(float(r.get("dur_s") or 0) for r in recs), 1)


def _is_unfixable(rec):
    st = str(rec.get("status") or "")
    sig = str(rec.get("sig") or "")
    return (
        st.startswith("unfixable")
        or st in TERMINAL_WORDS | {"fail"}
        or sig.startswith("unfixable:")
        or sig in TERMINAL_WORDS
    )


def compute_metrics(results_dir, recs, prev_line):
    """records → metrics.jsonl 一行 (schema 见 spec §6)。"""
    rates = {}
    for r in recs:
        stage = str(r.get("stage") or "?")
        arm = str(r.get("arm") or "default")
        cell = rates.setdefault(stage, {}).setdefault(arm, Counter())
        st = str(r.get("status") or "?")
        cell["total"] += 1
        cell[f"st:{st}"] += 1
        # fixloop 的"成功"= rescued 终态集（partial/acceptable_pdf 等带伤出 pdf
        # 也算），与 fixloop.rescue_rate 同口径；其余阶段用 OK_STATUS。
        ok_set = RESCUED_STATUS if stage == "fixloop" else OK_STATUS
        if st in ok_set:
            cell["ok"] += 1
        if st in SKIP_STATUS:
            cell["skip"] += 1
    stage_rates = {
        stage: {
            arm: {
                "ok": c["ok"],
                "total": c["total"],
                "rate": round(c["ok"] / c["total"], 4) if c["total"] else None,
                "n_skip": c["skip"],
                "by_status": {k[3:]: v for k, v in c.items() if k.startswith("st:")},
            }
            for arm, c in arms.items()
        }
        for stage, arms in rates.items()
    }

    fl = [r for r in recs if r.get("stage") == "fixloop"]
    attempted = [r for r in fl if str(r.get("status") or "") not in SKIP_STATUS]
    rescued = [r for r in attempted if str(r.get("status") or "") in RESCUED_STATUS]
    unfix = Counter(record_sig(r) for r in attempted if _is_unfixable(r))
    fixloop = {
        "attempted": len(attempted),
        "rescued": len(rescued),
        "rescue_rate": round(len(rescued) / len(attempted), 4) if attempted else None,
        "top_unfixable": [
            {"sig": s, "count": c} for s, c in unfix.most_common(TOP_UNFIXABLE)
        ],
    }

    # 回归: (a) compile zh 非 clean ∧ base clean = 管线引入; (b) 对上一行 metrics 的 rate 跌
    regs = []
    by_id = {}
    for r in recs:
        if r.get("stage") == "compile":
            by_id.setdefault(str(r.get("id")), {})[str(r.get("arm") or "default")] = (
                str(r.get("status") or "")
            )
    pipe = sorted(
        i
        for i, a in by_id.items()
        if a.get("zh") and a["zh"] not in OK_STATUS and a.get("base") in OK_STATUS
    )
    regs += [
        {"kind": "pipeline_introduced", "stage": "compile", "id": i}
        for i in pipe[:MAX_REG_IDS]
    ]
    if len(pipe) > MAX_REG_IDS:
        regs.append({"kind": "pipeline_introduced_truncated", "total": len(pipe)})
    prev_rates = (prev_line or {}).get("stage_rates") or {}
    for stage, arms in stage_rates.items():
        for arm, cell in arms.items():
            pr = (prev_rates.get(stage) or {}).get(arm) or {}
            if (
                pr.get("rate") is not None
                and cell["rate"] is not None
                and cell["rate"] < pr["rate"] - 1e-9
            ):
                regs.append(
                    {
                        "kind": "rate_drop",
                        "stage": stage,
                        "arm": arm,
                        "prev": pr["rate"],
                        "cur": cell["rate"],
                        "prev_run": (prev_line or {}).get("run_id"),
                    }
                )

    meta = _run_meta(results_dir)
    run_id = results_dir.name
    date = (
        str(meta.get("started_at") or "")[:10]
        or (run_id[-10:] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", run_id[-10:]) else "")
        or datetime.now(UTC).strftime("%Y-%m-%d")
    )
    return {
        "run_id": run_id,
        "date": date,
        "stage_rates": stage_rates,
        "fixloop": fixloop,
        "regressions": regs,
        "wall_s": _wall_s(results_dir, recs, meta),
    }


def _last_metrics_line(metrics_file, exclude_run=None):
    """metrics.jsonl 最末一行; exclude_run 跳过同 run_id (重算本 run 不自比)。"""
    if not metrics_file.exists():
        return None
    last = None
    for line in metrics_file.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if exclude_run is not None and row.get("run_id") == exclude_run:
            continue
        last = row
    return last


# ---------- report ----------


def render_report(results_dir, line, tickets, source_note):
    """metrics 行 + tickets → markdown 文本。"""
    lines = [f"# triage report — {line['run_id']}", ""]
    lines.append(
        f"- 生成: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · 数据源: {source_note}"
    )
    lines.append(f"- date={line['date']} · wall_s={line['wall_s']}")
    regs = line.get("regressions") or []
    if regs:
        drops = [r for r in regs if r["kind"] == "rate_drop"]
        pipes = [r for r in regs if r["kind"] == "pipeline_introduced"]
        lines.append(
            f"- 回归: rate_drop×{len(drops)} · pipeline_introduced×{len(pipes)}"
            + (f" ({', '.join(r['id'] for r in pipes[:5])}…)" if len(pipes) > 5 else "")
        )
    lines += [
        "",
        "## stage 通过率",
        "",
        "| stage | arm | ok | total | rate | skip |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for stage in sorted(line["stage_rates"]):
        for arm, c in sorted(line["stage_rates"][stage].items()):
            rate = f"{c['rate'] * 100:.1f}%" if c["rate"] is not None else "-"
            lines.append(
                f"| {stage} | {arm} | {c['ok']} | {c['total']} | {rate} | {c['n_skip']} |"
            )
    fl = line.get("fixloop") or {}
    if fl.get("attempted"):
        lines += [
            "",
            "## fixloop",
            "",
            f"- rescue_rate: {fl['rescued']}/{fl['attempted']} = "
            + (
                f"{fl['rescue_rate'] * 100:.1f}%"
                if fl["rescue_rate"] is not None
                else "-"
            ),
        ]
        if fl.get("top_unfixable"):
            lines.append("- top_unfixable:")
            lines += [f"  - `{u['sig']}` ×{u['count']}" for u in fl["top_unfixable"]]
    if tickets:
        lines += [
            "",
            f"## tickets (top {min(len(tickets), TOP_TICKETS_MD)}/{len(tickets)})",
            "",
            "| sig_id | stage | signature | count | fix_class | examples |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for t in tickets[:TOP_TICKETS_MD]:
            ex = ", ".join(t["example_ids"][:3]) + (
                "…" if len(t["example_ids"]) > 3 else ""
            )
            lines.append(
                f"| {t['sig_id']} | {t['stage']} | `{t['signature']}` | {t['count']} | {t['fix_class']} | {ex} |"
            )
    elif tickets is not None:
        lines += ["", "## tickets", "", "无 (全部 ok 或无 sig)。"]
    return "\n".join(lines) + "\n"


# ---------- 子命令 ----------


def _records_or_legacy(results_dir):
    """→ (recs, is_legacy)。records/ 为空时降级 results.json。"""
    recs = load_records(results_dir)
    if recs:
        return recs, False
    return legacy_records(results_dir), True


def cmd_records(results_dir, out=None):
    recs, legacy = _records_or_legacy(results_dir)
    if not recs:
        print(
            f"{results_dir}: 无 records/*.jsonl 且无可降级 results.json",
            file=sys.stderr,
        )
        return 1
    tickets = build_tickets(recs, results_dir)
    out = out or results_dir / ("tickets-legacy.jsonl" if legacy else "tickets.jsonl")
    with out.open("w") as f:
        for t in tickets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    src = "legacy(results.json/cases.jsonl)" if legacy else f"records/ ({len(recs)} 行)"
    print(f"tickets: {len(tickets)} 条 ← {src} → {out}")
    by_class = Counter(t["fix_class"] for t in tickets)
    print("  fix_class:", dict(by_class))
    return 0


def cmd_metrics(results_dir, metrics_file=None, *, global_append=True):
    recs, legacy = _records_or_legacy(results_dir)
    if not recs:
        print(f"{results_dir}: 无记录可算 metrics", file=sys.stderr)
        return 1
    metrics_file = metrics_file or results_dir.parent / "metrics.jsonl"
    prev = _last_metrics_line(metrics_file, exclude_run=results_dir.name)
    line = compute_metrics(results_dir, recs, prev)
    if global_append:
        # 全局趋势行追加进 git 跟踪的 bench/results/metrics.jsonl——
        # 冒烟/实验跑用 --no-global 只留 run 内 metrics.json 不污染趋势。
        metrics_file.parent.mkdir(parents=True, exist_ok=True)
        with metrics_file.open("a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    # 本 run 汇总 (spec §6 metrics.json) — stagerun 已写则不覆盖
    mp = results_dir / "metrics.json"
    if not mp.exists():
        mp.write_text(json.dumps(line, ensure_ascii=False, indent=1) + "\n")
    tag = " [legacy]" if legacy else ""
    dest = str(metrics_file) if global_append else "(run-local only)"
    print(
        f"metrics{tag}: {results_dir.name} → {dest} "
        f"(stages={list(line['stage_rates'])}, regressions={len(line['regressions'])})"
    )
    return 0


def cmd_report(results_dir, out=None):
    recs, legacy = _records_or_legacy(results_dir)
    line = None
    if recs:
        prev = _last_metrics_line(
            results_dir.parent / "metrics.jsonl", exclude_run=results_dir.name
        )
        line = compute_metrics(results_dir, recs, prev)
    elif (results_dir / "metrics.json").exists():
        line = json.loads((results_dir / "metrics.json").read_text())
    if line is None:
        print(f"{results_dir}: 无 records 且无 metrics.json", file=sys.stderr)
        return 1
    tickets = None
    for name in ("tickets.jsonl", "tickets-legacy.jsonl"):
        tp = results_dir / name
        if tp.exists():
            tickets = list(_read_jsonl(tp))
            break
    src = "legacy results.json" if legacy else "records/"
    md = render_report(results_dir, line, tickets, src)
    out = out or results_dir / "report.md"
    out.write_text(md)
    print(f"report → {out}")
    return 0


# ---------- selftest ----------


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="triage-selftest-"))
    rdir = tmp / "fake-run-2099-01-01"
    (rdir / "records").mkdir(parents=True)
    (rdir / "work" / "aaa").mkdir(parents=True)
    (rdir / "work" / "bbb").mkdir(parents=True)
    (rdir / "run_meta.json").write_text(
        json.dumps(
            {
                "seed": 1,
                "started_at": "2099-01-01T00:00:00+00:00",
                "finished_at": "2099-01-01T00:10:00+00:00",
            }
        )
    )

    def rec(i, stage, arm, status, sig="", dur=1.0, errs=None):
        return {
            "id": i,
            "stage": stage,
            "arm": arm,
            "status": status,
            "dur_s": dur,
            "metrics": {},
            "errors": errs or [],
            "sig": sig,
        }

    compile_recs = [
        rec("aaa", "compile", "zh", "ok"),
        rec("bbb", "compile", "zh", "fail", "missing_file:elsart.cls"),
        rec("ccc", "compile", "zh", "fail", "missing_file:elsart.cls"),
        rec("ddd", "compile", "zh", "fail", "missing_file:elsart.cls"),
        rec("eee", "compile", "zh", "fail", "undefined_cs:\\foo"),
        rec("fff", "compile", "zh", "fail", "undefined_cs:\\foo"),
        rec("ggg", "compile", "zh", "fail", "syntax:brace"),
        rec("aaa", "compile", "base", "ok"),
        rec("bbb", "compile", "base", "ok"),  # pipeline_introduced 回归
        rec("ccc", "compile", "base", "ok"),
        rec("ddd", "compile", "base", "fail", "missing_file:elsart.cls"),
        rec("eee", "compile", "base", "ok"),
        rec("fff", "compile", "base", "ok"),
        rec("ggg", "compile", "base", "fail", "syntax:brace"),  # 源生语法错, 非回归
    ]
    fixloop_recs = [
        rec("bbb", "fixloop", "fix", "fail", "unfixable:missing_file:elsart.cls"),
        rec("ccc", "fixloop", "fix", "fail", "unfixable:missing_file:elsart.cls"),
        rec("ddd", "fixloop", "fix", "ok"),
        rec("eee", "fixloop", "fix", "fail", "stuck"),
        rec("hhh", "fixloop", "fix", "skip"),
    ]
    xlat_recs = [
        rec("aaa", "xlat", "mock", "ok"),
        rec("bbb", "xlat", "mock", "ok"),
        rec(
            "nosig",
            "xlat",
            "mock",
            "fail",
            "",
            errs=[{"code": "auth", "cat": "auth", "payload": "401"}],
        ),
    ]
    for stage, rows in (
        ("compile", compile_recs),
        ("fixloop", fixloop_recs),
        ("xlat", xlat_recs),
    ):
        with (rdir / "records" / f"{stage}.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    print(f"== selftest dir: {rdir}")
    assert cmd_records(rdir) == 0
    assert cmd_metrics(rdir) == 0
    assert cmd_report(rdir) == 0

    tickets = [json.loads(x) for x in (rdir / "tickets.jsonl").read_text().splitlines()]
    counts = [t["count"] for t in tickets]
    assert counts == sorted(counts, reverse=True), "tickets 未按 count 降序"
    assert all(len(t["example_ids"]) <= MAX_EXAMPLES for t in tickets)
    top = tickets[0]
    assert top["signature"] == "missing_file:elsart.cls"
    assert top["count"] == 4  # zh×3 + base×1
    assert top["fix_class"] == "shim_table", top
    assert top["repro_path"] == "work/bbb/", top
    by_sig = {t["signature"]: t for t in tickets}
    assert by_sig["undefined_cs:\\foo"]["fix_class"] == "rule"
    assert by_sig["unfixable:missing_file:elsart.cls"]["fix_class"] == "shim_table"
    assert by_sig["stuck"]["fix_class"] == "core"
    assert by_sig["auth:401"]["fix_class"] == "rule"  # errors[] 合成 sig
    # metrics append 两次 → 两行, 第二行带 rate_drop? (同 rate → 无 drop)
    mfile = tmp / "metrics.jsonl"
    assert mfile.exists(), "metrics.jsonl 未写到 results_dir 父目录"
    mlines = mfile.read_text().splitlines()
    assert len(mlines) == 1
    line = json.loads(mlines[0])
    assert line["run_id"] == rdir.name
    assert line["wall_s"] == 600.0
    assert line["stage_rates"]["compile"]["zh"]["ok"] == 1
    assert line["stage_rates"]["compile"]["zh"]["total"] == 7
    assert line["fixloop"]["attempted"] == 4  # skip 不计
    assert line["fixloop"]["rescued"] == 1
    pipes = [r for r in line["regressions"] if r["kind"] == "pipeline_introduced"]
    assert {r["id"] for r in pipes} == {"bbb", "ccc", "eee", "fff"}, pipes
    # 追加第二遍验证 append 语义
    assert cmd_metrics(rdir) == 0
    assert len(mfile.read_text().splitlines()) == 2
    # report 产出
    rpt = (rdir / "report.md").read_text()
    assert "missing_file:elsart.cls" in rpt
    assert "compile" in rpt
    print("== selftest PASS ==")
    print(rpt)
    return 0


# ---------- main ----------


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--selftest", action="store_true", help="合成假 records/ 全链自检")
    sub = p.add_subparsers(dest="cmd")
    for name in ("records", "metrics", "report", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("dir", type=Path, help="results 目录 bench/results/{run}/")
        if name in ("records", "report"):
            sp.add_argument("--out", type=Path, default=None)
        if name in ("metrics", "all"):
            sp.add_argument("--metrics-file", type=Path, default=None)
            sp.add_argument(
                "--no-global",
                action="store_true",
                help="不追加全局 metrics.jsonl（冒烟/实验跑用，防污染趋势文件）",
            )
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.cmd == "records":
        return cmd_records(args.dir, args.out)
    if args.cmd == "metrics":
        return cmd_metrics(
            args.dir, args.metrics_file, global_append=not args.no_global
        )
    if args.cmd == "report":
        return cmd_report(args.dir, args.out)
    if args.cmd == "all":
        rc = cmd_records(args.dir)
        rc |= cmd_metrics(args.dir, args.metrics_file, global_append=not args.no_global)
        rc |= cmd_report(args.dir)
        return rc
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
