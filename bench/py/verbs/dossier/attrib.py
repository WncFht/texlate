"""verbs.dossier 归因/横切叶 —— 跨 run 出现史 + 断点归因 + 单格醒目行 +
end-state 面与波前后 diff（dossier.py 拆分叶）。

门面回引名单见 ``verbs.dossier._LEAF_EXPORTS``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kernel import paths

from verbs.dossier.env import STAGES
from verbs.dossier.fetch import _latest, _rec_key
from verbs.dossier.sections import (
    _err0,
    _is_fail,
    _latest_of,
    _primary_compile,
)

if TYPE_CHECKING:
    from pathlib import Path


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
    """裸 run 名 → rundir（import-* 平名 glob 先、kind/date/slug 三切后）。

    run→rundir 解析族的 name 形——族谱/勿再长新件见 ``_common._rundir``
    上方注释块；本形只在 _cross_run 拿不到 JOIN 行时兜底。"""
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
