"""verbs.dossier 装配/渲染叶 —— build_dossier 组卷 + render_md 出文
（dossier.py 拆分叶）。

门面回引名单见 ``verbs.dossier._LEAF_EXPORTS``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from verbs._dossier_attrib import _attribution, _diff
from verbs._dossier_env import _ruleset
from verbs._dossier_fetch import _latest
from verbs._dossier_sections import (
    _evidence,
    _gap_flags,
    _history,
    _identity,
    _rules_section,
    _signature,
)

if TYPE_CHECKING:
    from pathlib import Path

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
