"""verbs.dossier work 树侧叶 —— work/{safe_id}/ 现场盘点 + texmf 落装面 +
编译日志/文本 taxonomy 归类（dossier.py 拆分叶）。

``parse_log``/``parse_text`` 借 ``dossier.env`` 的 texlate 桥（缺席绑
None，``_ruleset()`` 先闸——调用面不可达）。
门面回引名单见 ``verbs.dossier._LEAF_EXPORTS``。
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

from verbs._common import _iter_jsonl
from verbs.dossier.env import _ruleset, parse_log, parse_text

if TYPE_CHECKING:
    from pathlib import Path

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
