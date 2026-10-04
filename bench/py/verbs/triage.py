r"""triage — run records 聚类分诊 → tickets.jsonl + report.md。

数据源从旧 bench/results/{run}/records/*.jsonl 迁到 ledger index:
records ∪ eval_records WHERE run=? 按 (id,arm,up,variant,stage) seq
末条胜。产物落 RUNDIR/derived/（kernel run 的派生面——run 根 report.md
是 cells/cases 官方件，不覆盖）。

  bench triage RUN                # tickets.jsonl + report.md → derived/
  bench triage RUN --trend        # 同 kind 跨 run stage_rates（runs 表 run_seq 序，
                                  #   替代旧 bench/results/metrics.jsonl 追加行）
  bench triage RUN --table eval_records   # 只看评测表（缺省 both 并集）
  bench triage RUN --json         # 机读 payload（line+tickets+落盘文件）

RUN 解析：kind/date/slug、run 目录、或任意 records.run 值（导入账）。
旧 harness 降级与 --selftest 已随 results/ 目录面一起退役——index 是唯一
records 面。状态词汇单源 verbs._vocab（benchlib 原样移植）。
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from verbs import _vocab

BENCH = Path(__file__).resolve().parents[2]
REPO = BENCH.parent
RULES_DIR = REPO / "src/texlate/compile/fixloop/rules"

OK_STATUS = _vocab.OK_STATUS
SKIP_STATUS = _vocab.SKIP_STATUS
RESCUED_STATUS = _vocab.RESCUED_STATUS
TERMINAL_WORDS = _vocab.TERMINAL_WORDS
STATUS_RANK = _vocab.STATUS_RANK

MAX_EXAMPLES = 5
MAX_REG_IDS = 50
TOP_UNFIXABLE = 10
TOP_TICKETS_MD = 20

# 退役/改名包常识集 (F1 的 elsart.cls 这类——还没进 shim_map 的也算 shim_table 候选)。
KNOWN_RETIRED = {"elsart.cls", "aastex.cls", "aastex63.cls", "revtex.cls", "psfig.sty"}

_TABLES = {
    "records": ("records",),
    "eval_records": ("eval_records",),
    "both": ("records", "eval_records"),
}

_COLS = "seq,id,idc,arm,up,variant,stage,status,cat,sig,code,fp,dur_s,metrics,errors,ts"


# ---------- 读 records ----------


def _jcol(text):
    """TEXT JSON 列 → obj；null/腐化 → None（下游 _metrics/_err0 各自收窄）。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _blob_dir(rundir):
    """run dir → derived/blobs/（$blob 标记回读面）；无 dir/无 blobs → None。"""
    if rundir is None:
        return None
    d = Path(rundir) / "derived" / "blobs"
    return d if d.is_dir() else None


def load_records(index, run, blob_dir=None, table="both"):
    """index records ∪ eval_records → [rec dict]；同键末条胜（ORDER BY seq 覆盖写）。

    键 = (id, arm, up, variant, stage)——比旧 stagerun (id,arm,up) 文件内键
    多 stage（单查询跨段）与 variant（变体即不同测量格）。有意用裸 ``id``
    而非 ``idc``：triage 是审计面，``math--X``/``math/X`` 双拼写同存的账
    本身就是要捞的病灶，canon 归一会把两形静默并键遮住分裂信号。
    """
    from kernel import events

    best = {}
    for t in _TABLES[table]:
        cur = index.conn.execute(
            f"SELECT {_COLS} FROM {t} WHERE run=? ORDER BY seq",  # noqa: S608 — t 取自 _TABLES 闭集
            (run,),
        )
        for row in cur:
            rec = {
                "id": row["id"],
                "idc": row["idc"],
                "arm": row["arm"],
                "upstream": row["up"],
                "variant": row["variant"],
                "stage": row["stage"],
                "status": row["status"],
                "cat": row["cat"],
                "sig": row["sig"],
                "code": row["code"],
                "fp": row["fp"],
                "dur_s": row["dur_s"],
                "metrics": events.unblob(_jcol(row["metrics"]), blob_dir),
                "errors": events.unblob(_jcol(row["errors"]), blob_dir),
                "ts": row["ts"],
                "src": t,
            }
            key = (
                str(row["id"]),
                str(row["arm"] or "-"),
                str(row["up"] or ""),
                str(row["variant"] or ""),
                str(row["stage"] or "?"),
            )
            best[key] = rec
    return list(best.values())


# ---------- sig 解析与归类 ----------


# 归桶规则：stagerun 的 sig payload 常带逐实例细节（fault 计数/member 名/
# repr/路径），直接聚类会把同一缺陷类碎成 N 张 singleton 票——ticket 按
# 缺陷类算，不按实例算。
_STAGE_CATS = {
    "xlat",
    "ingest",
    "inject",
    "route",
    "parse",
    "compile",
    "upstream",
}
# payload 是实例细节、无缺陷类信息量的 cat（_missing_rec 系 member 名/
# no_extracted 路径/sabotage 台账 id 列表/missing_character xN 计数）。
_SIG_DROP_PAY = {
    "stub_format",
    "pdf_format",
    "error_format",
    "eprint_fetch_unwired",
    "no_item",
    "no_extracted",
    "sabotage_escaped",
    "missing_character",
}
_RE_KV_NUM = re.compile(r"(\w+=)\d+")


def _err0(rec):
    """errors 头元素 dict 化：errors 非 list/空表/头非 dict → None（类型混淆按无 errors 计）。"""
    errs = rec.get("errors")
    if not isinstance(errs, list) or not errs:
        return None
    e0 = errs[0]
    return e0 if isinstance(e0, dict) else None


def bucket_sig(sig, rec):
    """聚类 sig 归一化：code 比 stage-bucket cat 更细时换 code；实例细节归桶。

    - errors[0].cat 与 sig cat 一致且 code 是另一个缺陷类词 → 按 code 聚类
      （xlat:leftover_ph/chunks_bad、parse:no_main_tex、inject:inject_reject 等）；
      e0.cat 不一致（legacy harness 行 cat=None）或 code 含 ':'（fv 组合词）
      不换，防误并。
    - harness 系 code='harness:ExcType' 已含类名，repr payload 碎裂 → 留 code。
    - kv 计数 fault=1 skipped=0 → fault=N skipped=N；code 换名后残留的纯
      数字 payload（leftover_ph '3'）是计数 → 丢。
    """
    prefix = ""
    s = sig
    for pre in ("unfixable:", "reject:", "nosig:"):
        if s.startswith(pre):
            prefix, s = pre, s[len(pre) :]
            break
    if ":" in s:
        cat, pay = s.split(":", 1)
    else:
        cat, pay = s, ""
    e0 = _err0(rec) or {}
    code = str(e0.get("code") or "").strip()
    if cat == "harness" and code.startswith("harness:"):
        return f"{prefix}{code}"
    swapped = bool(
        code
        and ":" not in code
        and code != cat
        and cat in _STAGE_CATS
        and str(e0.get("cat") or "") == cat
    )
    if swapped:
        cat, pay = code, str(e0.get("payload") or pay)
    if cat in _SIG_DROP_PAY or (swapped and pay.isdigit()):
        pay = ""
    pay = _RE_KV_NUM.sub(r"\1N", pay)
    return f"{prefix}{cat}:{pay}".rstrip(":")


def record_sig(rec):
    """record → 归一化 sig: 优先 rec['sig']; 否则 errors[0] 合成 cat:pay;
    兜底 nosig:status。"""
    sig = str(rec.get("sig") or "").strip()
    if not sig:
        e0 = _err0(rec)
        if e0 is not None:
            cat = e0.get("cat") or e0.get("code") or "error"
            pay = e0.get("payload")
            sig = f"{cat}:{pay}" if pay not in (None, "") else str(cat)
        else:
            sig = f"nosig:{rec.get('status') or 'unknown'}"
    return bucket_sig(sig, rec)


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
    """rules/ 分片 legacy_pkg_shim.shim_map 键 ∪ 常识集; yaml 不可用时退回常识集。"""
    names = set(KNOWN_RETIRED)
    try:
        import yaml

        rules: list[dict] = []
        for part in sorted(RULES_DIR.glob("*.yaml")):
            rules.extend((yaml.safe_load(part.read_text()) or {}).get("rules") or [])
        for rule in rules:
            if rule.get("id") == "legacy_pkg_shim":
                names |= set(
                    ((rule.get("action") or {}).get("params") or {}).get("shim_map")
                    or {}
                )
    except Exception as e:  # shim 表只是归类提示，读不到不致命
        print(f"  warn: rules/ shim_map 读取失败 ({e}); 用内置退役表", file=sys.stderr)
    return names


def classify(sig, rep):
    """(sig, 代表 record) → (fix_class, note)。

    顺序：具体 cat 先判 (unfixable:missing_file:elsart.cls 也是 shim_table 单 — F1),
    终态词兜底 core; 其余 rule 留人工。
    """
    cat, pay = parse_sig(sig)
    if not pay:
        e0 = _err0(rep)
        if e0 is not None:
            pay = str(e0.get("payload") or "")
    base = Path(pay).name if pay else ""

    # unfixable 零触发分流：fixloop 全程无规则动作 = 规则库覆盖缺口
    # （与触发但修不动的规则力不足分桶——wontfix 裁定面据此自动拆出）。
    # n_actions 缺席（旧记录）视为不可判，走既有 cat 分支。
    if (
        sig.startswith("unfixable:")
        and (rep.get("metrics") or {}).get("n_actions") == 0
    ):
        return (
            "ruleset_gap",
            "n_actions=0——fixloop 全程零规则触发 = 覆盖缺口, wontfix 候选",
        )
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
            "undefined_cs 逐标记归因 (F2): 缺包→filemap.overrides/cs_targeted_fix; 笔误→llm_hook",
        )
    if cat == "missing_character":
        return "rule", "CJK 缺字类规则可扩性 (F4)"
    if cat == "leftover_ph":
        return "core", "占位符字面泄漏进文档——splice/translate 层缺陷, 非规则可修"
    if cat == "latex209" or pay == "latex209":
        # sig 形如 inject_reject:latex209 / inject:latex209 —— cat 是阶段桶，
        # 209 判定落在 payload 位
        return (
            "wontfix",
            "LaTeX2.09 路由层拒绝 (F3: verdict 语义 reject→partial, 非缺陷)",
        )
    # 终态词判在剥过 verdict 前缀的 cat 上——nosig:stuck / reject:max_rounds
    # 这类带前缀 sig 的 raw 头词是前缀本身，直切 sig 会漏判成 rule。
    if sig.startswith("unfixable:") or cat in TERMINAL_WORDS:
        return "core", "fixloop 终态 → 规则面外的引擎/taxonomy 缺口"
    return "rule", "待人工归因"


# ---------- records → tickets ----------


def _upstream_gated(rec):
    """上游门记录：errors[0].cat=='upstream' 或 sig 'upstream:*'。

    上游阶段未过/未跑的派生格——归宿在上游工单，本阶段不重复出票
    （upstream_gate/no_src/not_translated/arm_mismatch/no_parse_tree/
    no_splice 全系 cat=upstream）。ingest stub_format 等真失败型
    reject cat≠upstream，不在此豁免。
    """
    e0 = _err0(rec) or {}
    if str(e0.get("cat") or "") == "upstream":
        return True
    return str(rec.get("sig") or "").startswith("upstream:")


def build_tickets(recs, rundir):
    """(stage, sig) 聚类非 ok/skip 记录 (显式 sig 的 ok 记录也留票——warning 级)。

    rundir 为 None（index-only 账）时 repro_path 恒 None。返回按 count
    降序的 ticket dict 列表。
    """
    from kernel import idnorm

    clusters = {}
    for rec in recs:
        st = str(rec.get("status") or "")
        has_sig = bool(str(rec.get("sig") or "").strip())
        has_err = bool(rec.get("errors"))
        if st in OK_STATUS | SKIP_STATUS and not (has_sig or has_err):
            continue
        if st in SKIP_STATUS and _upstream_gated(rec):
            continue
        key = (str(rec.get("stage") or "?"), record_sig(rec))
        clusters.setdefault(key, []).append(rec)

    tickets = []
    for (stage, sig), rs in clusters.items():
        ids = []
        seen = set()
        for r in rs:
            rid = str(r.get("id") or "?")
            rv = str(r.get("variant") or "")
            label = f"{rid}@{rv}" if rv not in ("", "-") else rid
            if label not in seen:
                seen.add(label)
                ids.append(label)
        repro = None
        if rundir is not None:
            for r in rs:
                cands = []
                idc = str(r.get("idc") or "")
                if idc:
                    cands.append(idnorm.safe_id(idc))
                rid = str(r.get("id") or "")
                if rid and rid not in cands:
                    cands.append(rid)
                for w in cands:
                    if w and (Path(rundir) / "work" / w).is_dir():
                        repro = f"work/{w}/"
                        break
                if repro:
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


# ---------- metrics ----------


def _metrics(rec):
    """rec['metrics'] dict 化——真值非 dict 按 {} 计（类型混淆不崩）。"""
    m = rec.get("metrics")
    return m if isinstance(m, dict) else {}


def stage_rates(recs):
    """records → {stage: {arm: {ok,total,rate,n_skip,by_status}}}."""
    rates = {}
    for r in recs:
        stage = str(r.get("stage") or "?")
        arm = str(r.get("arm") or "default")
        variant = str(r.get("variant") or "")
        if variant not in ("", "-"):
            # variant 即测量格（e2e_mock 条件臂/xlatbench rep）——并进率表
            # 轴，否则同 stage+arm 的多变体格静默合并。
            arm = f"{arm}@{variant}" if arm not in ("", "-") else variant
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
    return {
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


def _wall_s(index, info, recs):
    """finished 事件 wall_s 优先；缺事件 → dur_s 求和兜底（非有限值不计）。"""
    from kernel import events
    from kernel import report as _report

    fin = _report._last_typed(index, info, events.T_FINISHED)
    ws = (fin or {}).get("wall_s")
    if isinstance(ws, (int, float)) and not isinstance(ws, bool):
        try:
            f = float(ws)
        except (ValueError, TypeError):
            f = float("nan")
        if math.isfinite(f):
            return round(f, 1)
    total = 0.0
    for r in recs:
        try:
            d = float(r.get("dur_s") or 0)
        except (ValueError, TypeError):
            continue
        if math.isfinite(d):
            total += d
    return round(total, 1) if math.isfinite(total) else 0.0


def _run_date(info):
    """run 的 YYYY-MM-DD：runs.date 列 → run 名内嵌日期 → 今日兜底。"""
    d = info.get("date")
    if d:
        return str(d)[:10]
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(info.get("run") or ""))
    if m:
        return m.group(0)
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _is_unfixable(rec):
    st = str(rec.get("status") or "")
    sig = str(rec.get("sig") or "")
    return (
        st.startswith("unfixable")
        or st in TERMINAL_WORDS | {"fail"}
        or sig.startswith("unfixable:")
        or sig.split(":", 1)[0] in TERMINAL_WORDS
    )


def compute_metrics(recs, run_id, date, wall_s, prev_line):
    """records → 汇总行 {run_id,date,stage_rates,fixloop,regressions,wall_s}。

    prev_line = 同 kind 前一 run 的同类行（rate_drop 基线；None 则跳过）。
    """
    rates = stage_rates(recs)

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

    # 回归：(a) compile zh 非 clean ∧ base clean = 管线引入; (b) 对上一行的 rate 跌
    regs = []
    by_id = {}
    for r in recs:
        if r.get("stage") == "compile":
            by_id.setdefault(str(r.get("id")), {})[str(r.get("arm") or "default")] = (
                str(r.get("status") or "")
            )
    # zh 侧 skip/reject（上游门/政策拒）与 error（harness 崩）不算管线引入缺陷
    pipe = sorted(
        i
        for i, a in by_id.items()
        if a.get("zh")
        and a["zh"] not in OK_STATUS | SKIP_STATUS | {"error"}
        and a.get("base") in OK_STATUS
    )
    regs += [
        {"kind": "pipeline_introduced", "stage": "compile", "id": i}
        for i in pipe[:MAX_REG_IDS]
    ]
    if len(pipe) > MAX_REG_IDS:
        regs.append({"kind": "pipeline_introduced_truncated", "total": len(pipe)})
    # 跨段退化：fixloop 终态低于入口态 (loop1 实证 17 格，本探测器盲区补网)。
    # 注意基建杀伤会混入——真退化判定需直编复验
    # (见 docs/log/audit-2026-09-16/wave2-findings.md loop1 节)。
    # 只巡 attempted：skip 记录没真跑 fixloop，STATUS_RANK 表外 -1 会假阳退化。
    degraded = sorted(
        (
            str(r.get("id")),
            str(_metrics(r).get("compile_status_before") or ""),
            str(r.get("status") or ""),
        )
        for r in attempted
        if STATUS_RANK.get(str(r.get("status") or ""), -1)
        < STATUS_RANK.get(str(_metrics(r).get("compile_status_before") or ""), -1)
    )
    regs += [
        {"kind": "fixloop_degraded", "id": i, "before": b, "after": a}
        for i, b, a in degraded[:MAX_REG_IDS]
    ]
    if len(degraded) > MAX_REG_IDS:
        regs.append({"kind": "fixloop_degraded_truncated", "total": len(degraded)})
    prev_rates = (prev_line or {}).get("stage_rates") or {}
    for stage, arms in rates.items():
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

    return {
        "run_id": run_id,
        "date": date,
        "stage_rates": rates,
        "fixloop": fixloop,
        "regressions": regs,
        "wall_s": wall_s,
    }


def prev_line(index, info, table="both"):
    """同 kind 上一 run（runs.run_seq 序）→ {run_id, stage_rates}；无 → None。"""
    from kernel import report as _report

    kind = info.get("kind")
    seq = (info.get("row") or {}).get("run_seq")
    if not kind or seq is None:
        return None
    row = index.conn.execute(
        "SELECT run FROM runs WHERE kind=? AND run_seq<? ORDER BY run_seq DESC LIMIT 1",
        (kind, seq),
    ).fetchone()
    if row is None:
        return None
    pinfo = _report._resolve(index, row["run"])
    recs = load_records(index, pinfo["run"], _blob_dir(pinfo["rundir"]), table)
    return {"run_id": pinfo["run"], "stage_rates": stage_rates(recs)}


def trend_lines(index, kind, table="both"):
    """同 kind 全部 run 按 run_seq 序 → [metrics 行]（行间即 rate_drop 链）。"""
    from kernel import report as _report

    cur = index.conn.execute(
        "SELECT run FROM runs WHERE kind=? ORDER BY run_seq", (kind,)
    )
    lines, prev = [], None
    for row in cur:
        info = _report._resolve(index, row["run"])
        recs = load_records(index, info["run"], _blob_dir(info["rundir"]), table)
        line = compute_metrics(
            recs,
            info["run"],
            _run_date(info),
            _wall_s(index, info, recs),
            prev,
        )
        lines.append(line)
        prev = line
    return lines


# ---------- report ----------


def render_report(line, tickets, source_note):
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
        degs = [r for r in regs if r["kind"] == "fixloop_degraded"]
        lines.append(
            f"- 回归: rate_drop×{len(drops)} · pipeline_introduced×{len(pipes)}"
            f" · fixloop_degraded×{len(degs)}"
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


def render_trend(kind, lines):
    """[metrics 行] → 跨 run rate 透视表（run × stage:arm 格子率）。"""
    cols = sorted(
        {
            f"{s}:{a}"
            for ln in lines
            for s, arms in ln["stage_rates"].items()
            for a in arms
        }
    )
    out = [
        f"# trend — {kind} ({len(lines)} runs)",
        "",
        "| run | date | " + " | ".join(cols) + " | regs |",
        "| --- | --- |" + " --- |" * (len(cols) + 1),
    ]
    for ln in lines:
        cells = []
        for c in cols:
            s, a = c.split(":", 1)
            cell = (ln["stage_rates"].get(s) or {}).get(a)
            cells.append(
                "-"
                if not cell or cell["rate"] is None
                else f"{cell['rate'] * 100:.0f}%({cell['ok']}/{cell['total']})"
            )
        out.append(
            f"| {ln['run_id']} | {ln['date']} | "
            + " | ".join(cells)
            + f" | {len(ln.get('regressions') or [])} |"
        )
    return "\n".join(out) + "\n"


# ---------- verb ----------


def add_args(sp):
    sp.add_argument(
        "run",
        help="run 引用: kind/date/slug、run 目录、或任意 records.run 值（含导入账）",
    )
    sp.add_argument(
        "--table",
        choices=sorted(_TABLES),
        default="both",
        help="records 面选择（缺省 both = records ∪ eval_records）",
    )
    sp.add_argument(
        "--trend",
        action="store_true",
        help="同 kind 全 run 重算 stage_rates（runs 表 run_seq 序，只打不落盘）",
    )
    sp.add_argument("--json", action="store_true", dest="as_json", help="机读输出")
    sp.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="tickets/report 落点覆盖（缺省 RUNDIR/derived/）",
    )


def main(args):
    from kernel import cli as _cli
    from kernel import report as _report

    index = _cli._open_index()
    try:
        info = _report._resolve(index, args.run)

        if args.trend:
            if not info.get("kind"):
                print(
                    f"triage: {args.run!r} 无法定 kind（runs 表无行）——trend 需 kind",
                    file=sys.stderr,
                )
                return 2
            lines = trend_lines(index, info["kind"], table=args.table)
            if args.as_json:
                _cli._print_json({"kind": info["kind"], "runs": lines})
            else:
                print(render_trend(info["kind"], lines), end="")
            return 0

        recs = load_records(index, info["run"], _blob_dir(info["rundir"]), args.table)
        if not recs:
            print(
                f"triage: {info['run']!r} 无 {args.table} 行",
                file=sys.stderr,
            )
            return 1
        prev = prev_line(index, info, table=args.table)
        line = compute_metrics(
            recs,
            info["run"],
            _run_date(info),
            _wall_s(index, info, recs),
            prev,
        )
        tickets = build_tickets(recs, info["rundir"])
        src = f"index {args.table} ({len(recs)} cells)"
        md = render_report(line, tickets, src)

        out_dir = args.out_dir
        if out_dir is None and info["rundir"] is not None:
            out_dir = Path(info["rundir"]) / "derived"
        files = []
        if out_dir is not None:
            _cli._pre_write()
            out_dir.mkdir(parents=True, exist_ok=True)
            tp = out_dir / "tickets.jsonl"
            tp.write_text(
                "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tickets),
                encoding="utf-8",
            )
            files.append(tp)
            rp = out_dir / "report.md"
            rp.write_text(md, encoding="utf-8")
            files.append(rp)

        if args.as_json:
            _cli._print_json(
                {
                    "run": info["run"],
                    "line": line,
                    "tickets": tickets,
                    "files": [str(f) for f in files],
                }
            )
        elif not files:
            print(md, end="")  # index-only 账无落点 → stdout 给全文
        else:
            by_class = Counter(t["fix_class"] for t in tickets)
            print(
                f"triage {info['run']}: {len(recs)} cells → {len(tickets)} tickets"
                f" {dict(by_class)}; regressions={len(line['regressions'])}"
            )
            for f in files:
                print(f"  → {f}")
        return 0
    finally:
        index.close()
