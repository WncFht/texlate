"""L2 归因准确率探针——真实编译 FAIL 案例上的 `_l2_localize` 分布级验证。

数据源（全部只读）：

- `bench/results/e2e-real-n100-postcutover-2026-09-16/results.json` —— pipe-xel
  非 clean 案例清单（fail/partial）。
- `bench/work_e2ereal/pipe-xel/<id>/` —— splice 后的工作树 + 真实 xelatex
  `*.log`（pipe 条件无 fixloop 改盘，文件即编译时所见）。
- `bench/work_e2ereal/_xlat_state/<id>/state.json` —— 真实译文账
  （`{"fidx:cid": {source, translation, status}}`）。
- `bench/corpus_v3/<id>/extracted/` —— 原始英文源（喂 `parse_file` 复现
  ScanResult 的 chunks/ph_map）。

方法：对每条 log 错误复跑**真** `_l2_localize` 路径（`_L2Attr` +
`_resolve_fidx` + `_chunk_spans`，原样 import src/texlate/repair.py 内部件，
不重实现），逐错误记归因结果与距离/命中形态；再按规则粗分
归对/归错/不可归因三档，window 命中落明细供人工复核。

先决校验：state 里每条 `source` 必须等于 `scans[fidx].chunks[cid].content`
（snapshot 期 segmenter/normalize 漂移侦测）；漂移超阈值的案例标
`drift` 不进准确率统计。

跑法：`uv run python bench/py/l2_attr_probe.py`
产出：`bench/results/l2-attr-probe-2026-09-16/{probe.jsonl,cases.jsonl,summary.md}`
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import benchlib

from texlate import repair
from texlate.compile.engine import CompRes
from texlate.latex.api import parse_file

if TYPE_CHECKING:
    from texlate.validate import l2 as l2_mod

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "bench/work_e2ereal/pipe-xel"
STATE = ROOT / "bench/work_e2ereal/_xlat_state"
SRC = ROOT / "bench/corpus_v3"
RESULTS_JSON = ROOT / "bench/results/e2e-real-n100-postcutover-2026-09-16/results.json"
OUT = ROOT / "bench/results/l2-attr-probe-2026-09-16"

#: chunk-source 对齐容忍度（低于此比例的案例判 drift 不进准确率统计）
ALIGN_MIN = 0.9

_CJK_RX = re.compile(r"[一-鿿]")


def _build_run(aid: str, work: Path) -> tuple[repair._TreeRun | None, dict]:
    """建 _TreeRun：scans=(work路径, 源树parse结果)，trans=state ok 译文。"""
    st_path = STATE / aid / "state.json"
    if not st_path.exists():
        return None, {"drop": "no_state"}
    state = json.loads(st_path.read_text(encoding="utf-8"))

    work_texs = sorted(work.rglob("*.tex"))
    scans: list[tuple[Path, object]] = []
    skipped: list[str] = []
    for wf in work_texs:
        rel = wf.relative_to(work)
        sf = SRC / aid / "extracted" / rel
        if not sf.exists():
            skipped.append(str(rel))
            continue
        try:
            res = parse_file(sf, flatten=False)
        except Exception as e:
            skipped.append(f"{rel} (parse: {type(e).__name__})")
            continue
        scans.append((wf, res))

    # fidx 对齐校验：state 的 "fidx:cid" 以 driver 枚举序为准——
    # skipped 非空意味着枚举错位，整条目记 drift（宁缺勿错）。
    # results 是 append 账：resume 会对同一 chunk_id 记多条（前条的 source
    # 还带着原文换行，后条已折叠）——按 chunk_id 去重、last-wins。
    results = state.get("results") or []
    latest: dict[str, dict] = {}
    n_records = len(results)
    for r in results:
        cid_key = r.get("chunk_id")
        if cid_key:
            latest[cid_key] = r
    total = 0
    matched = 0
    drift_examples: list[str] = []
    trans: dict[int, dict[int, str]] = {}
    for r in latest.values():
        total += 1
        fidx_s, _, cid_s = (r.get("chunk_id") or "").partition(":")
        try:
            fidx, cid = int(fidx_s), int(cid_s)
            chunk = scans[fidx][1].chunks[cid]
        except (ValueError, IndexError):
            drift_examples.append(r.get("chunk_id") or "?")
            continue
        if chunk.content == r.get("source"):
            matched += 1
            if r.get("status") == "ok" and r.get("translation") is not None:
                trans.setdefault(fidx, {})[cid] = r["translation"]
        else:
            drift_examples.append(r.get("chunk_id") or "?")

    info = {
        "records_total": n_records,
        "chunks_reported": total,
        "chunks_aligned": matched,
        "align_ratio": (matched / total) if total else 0.0,
        "skipped_files": skipped,
        "drift_examples": drift_examples[:5],
    }
    run = repair._TreeRun(scans=scans, trans=trans, chunk_ins={}, pipe=None)
    return run, info


def _classify_error(st: repair._L2Attr, err: l2_mod.LogError, work: Path) -> dict:
    """单条错误的归因明细：outcome + 距离 + 行内容证据。"""
    row: dict = {
        "head": err.head[:200],
        "tex_file": err.tex_file,
        "tex_line": err.tex_line,
        "stack_depth": len(err.file_stack),
        "stack_inner": err.file_stack[-1] if err.file_stack else None,
    }
    src_tok = err.tex_file or (err.file_stack[-1] if err.file_stack else None)
    if src_tok is None:
        row["outcome"] = "no_loc"
        return row
    fidx = repair._resolve_fidx(src_tok, st.run, work)
    if fidx is None:
        row["outcome"] = "unresolved_file"
        row["src_tok"] = src_tok
        return row
    row["fidx"] = fidx
    row["file"] = st.run.scans[fidx][0].relative_to(work).as_posix()
    st.file_state(fidx)
    sres = st.run.scans[fidx][1]
    row["file_chunks"] = len(sres.chunks)
    row["spans_none"] = sum(1 for v in st.spans[fidx].values() if v is None)

    if err.tex_line is None:
        row["outcome"] = (
            "file_level"
            if len(sres.chunks) <= repair.L2_MAX_CHUNKS
            else "no_line_big_file"
        )
        return row

    offs = st.line_off[fidx]
    if not (1 <= err.tex_line <= len(offs) - 1):
        row["outcome"] = "line_oob"
        return row
    off = offs[err.tex_line - 1]
    lines = st.texts[fidx].splitlines()
    line_txt = lines[err.tex_line - 1] if err.tex_line <= len(lines) else ""
    row["line_text"] = line_txt[:200]
    row["line_cjk"] = bool(_CJK_RX.search(line_txt))

    best_cid, best_gap, in_span = None, repair._L2_ATTR_WINDOW + 1, False
    for cid, sp in st.spans[fidx].items():
        if sp is None:
            continue
        s, e = sp
        if s <= off < e:
            best_cid, best_gap, in_span = cid, 0, True
            break
        gap = max(s - off, off - e, 0)
        if gap < best_gap:
            best_cid, best_gap = cid, gap
    if in_span:
        row["outcome"] = "in_span"
        row["cid"] = best_cid
    elif best_cid is not None and best_gap <= repair._L2_ATTR_WINDOW:
        row["outcome"] = "window"
        row["cid"] = best_cid
        row["gap"] = best_gap
    else:
        row["outcome"] = "beyond_window"
        row["gap"] = best_gap if best_cid is not None else None
    if row.get("cid") is not None:
        c = sres.chunks[row["cid"]]
        row["chunk_kind"] = c.context
        row["chunk_env"] = c.env
        row["chunk_translated"] = row["cid"] in (st.run.trans.get(fidx) or {})
    return row


def main() -> int:
    results = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    cases = []
    for aid, v in results.items():
        pv = (v.get("pipe-xel") or {}).get("verdict") or {}
        if pv.get("status") not in ("fail", "partial"):
            continue
        cases.append((aid, pv.get("status"), v.get("main") or "main.tex"))

    OUT.mkdir(parents=True, exist_ok=True)
    oc = Counter()
    per_case = []

    with (
        (OUT / "probe.jsonl").open("w", encoding="utf-8") as rows_out,
        (OUT / "cases.jsonl").open("w", encoding="utf-8") as cases_out,
    ):
        for aid, status, main in cases:
            work = WORK / aid
            log = work / (Path(main).stem + ".log")
            case = {"id": aid, "status": status, "main": main}
            if not log.exists():
                case["drop"] = "no_log"
                per_case.append(case)
                benchlib.write_jsonl(cases_out, case)
                continue
            run, info = _build_run(aid, work)
            case.update(info)
            if run is None or info["align_ratio"] < ALIGN_MIN:
                case["drop"] = "drift" if run is not None else info.get("drop")
                per_case.append(case)
                benchlib.write_jsonl(cases_out, case)
                continue

            res_c = CompRes(engine="xelatex", ok=False, log_path=log)
            verdict = repair._l2_parse(res_c)
            case["n_errors"] = verdict.n_errors
            st = repair._L2Attr(run, work)
            n_hits = 0
            for err in verdict.errors[: repair._L2_MAX_ERRORS]:
                row = _classify_error(st, err, work)
                row["case"] = aid
                row["verdict"] = status
                benchlib.write_jsonl(rows_out, row)
                oc[row["outcome"]] += 1
                if row["outcome"] in ("in_span", "window", "file_level"):
                    n_hits += 1
            case["attributed"] = n_hits
            case["dropped_spans"] = sum(
                sum(1 for v in st.spans[i].values() if v is None) for i in st.spans
            )
            per_case.append(case)
            benchlib.write_jsonl(cases_out, case)

    summary = {
        "cases_total": len(cases),
        "cases_scored": sum(1 for c in per_case if "drop" not in c),
        "cases_dropped": [c["id"] for c in per_case if "drop" in c],
        "outcome_counts": dict(oc),
        "errors_total": sum(oc.values()),
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
