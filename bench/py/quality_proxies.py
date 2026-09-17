#!/usr/bin/env python3
r"""quality_proxies.py — S5 质量面代理指标后算器（verdict-proxy-spec-2026-09-17 §1 三件套）。

对既有 stagerun run 目录纯后算，零改码零重跑：

- ``leak_*``（xlat 记录）：送译 chunk ``source`` 命中六族展开残留正则的比率
  ——单源复用 ``parsebench.LEAK_PATTERNS``（corpus_v3 0.040% 官方口径同套）。
  输入 ``work/{id}/xlat-state/{arm}/state.json`` 的 ``results[]``，按
  ``chunk_id`` 末条胜去重（重试行 source 相同，去重幂等）。两臂同义——
  leak 是上游 parse/gullet 质量面，mock/real 都有效。
- ``term_*``（仅 real 臂）：术语表一致率。术语集重建口径 = manifest
  ``cat_group`` → ``terms/index.yaml`` category csv + ``default.csv`` +
  ``Glossary.doc_filter``（只留文档出现的词）——与 server 路径
  ``Glossary.load(categories=arxiv_categories)`` 同层；stagerun 的
  ``XlatPipeline`` 从未传 glossary（观测对象是「若按 server 口径注入
  应一致」的代理，不是「实际注入的一致」）。mock/sabotage 臂译文是
  echo/扰动占位，``term_*`` 恒 null。
- ``landmark``（compile 记录）：zh/base pdf named-dest 按
  ``align._category`` 分桶 ÷ 编译树结构期望数（``\section`` 系 +
  float env + 编号公式 env + ``\bibitem``，剥注释后正则计数）。
  无 hyperref 稿恒低是已知口径面（spec §4.2），先观测不定阈。

产出 sidecar ``<run>/quality-metrics.jsonl``——**不放 records/ 内**：
triage ``load_records`` 按 ``records/*.jsonl`` glob 收账（triage.py:87），
sidecar 入内会被当 stage=quality 记进聚类。行形状 =
``{id, stage, arm, upstream, metrics: {<subtree>: {...}}}``——子树名与
records 落点同名（xlat→``translate``、compile→``landmark``），将来回填
= ``rec["metrics"].setdefault(subtree, {}).update(keys)`` 一步合并。

用法::

  uv run python bench/py/quality_proxies.py bench/results/stagerun-loop1-2026-09-16 \
      [--jobs 8] [--limit N] [--ids id1,id2] [--manifest PATH ...] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import benchlib
import stagerun_lib as sl  # sys.path 设置 + canon_id/load_latest/workdir
from parsebench import LEAK_PATTERNS  # 六族正则单源——勿复制防口径漂移

from texlate.align import _category, extract_landmarks
from texlate.xlat.glossary import _TERM_BOUNDARY, LOCAL_GLOSSARY_NAME, Glossary

ROOT = Path(__file__).resolve().parents[2]

#: 术语指标只对真 LLM 臂有意义（mock/sabotage/perturb 译文是 echo/扰动占位）。
TERM_ARMS = frozenset({"real"})

#: 术语重建时禁用用户层——机器相关的 ~/.texlate/glossary.yaml 会让跨机
#: 后算口径漂移；local 层（论文自带 glossary.local.yaml）保留，它是语料属性。
_NO_USER_GLOSSARY = Path("/__texlate_bench_no_user_glossary__.yaml")

# ---------------------------------------------------------------- 结构期望计数
# 剥注释后对编译树 *.tex(+*.bbl) 计数。编号公式 env 不带 *（* 形无编号不产生
# dest）；float env 含 * 形（figure* 仍出 hyperref 锚）。section 系含 \appendix
# 以外的全体节令（\appendix 无标题参，不产 dest）。
_COMMENT_RX = re.compile(r"(?<!\\)%.*")
_EXPECTED_TEX_RX = {
    "section": re.compile(
        r"\\(?:section|subsection|subsubsection|paragraph|subparagraph|chapter|part)"
        r"\*?\s*[\[{]"
    ),
    "figtable": re.compile(
        r"\\begin\s*\{\s*(?:figure|table|figtable|sidewaysfigure|sidewaystable"
        r"|wrapfigure|wraptable)\*?\s*\}"
    ),
    "equation": re.compile(
        r"\\begin\s*\{\s*(?:equation|align|gather|multline|eqnarray|flalign"
        r"|alignat|dmath)\s*\}"
    ),
    "footnote": re.compile(r"\\footnote\s*[\[{]"),
}
_BIBITEM_RX = re.compile(r"\\bibitem\b")
#: hyperref/书签类包在场判定——n_dests==0 时区分「从未产锚」与「锚全丢」。
_HYPERREF_RX = re.compile(
    r"\\(?:usepackage|RequirePackage)(?:\s*\[[^\]]*\])?\s*\{[^}]*"
    r"(?:hyperref|bookmark|hypcap)[^}]*\}"
)


def _strip_comments(text: str) -> str:
    return "\n".join(_COMMENT_RX.sub("", line) for line in text.splitlines())


def expected_landmarks(tex_root: Path) -> dict | None:
    """编译树结构期望计数 + hyperref 在场标记；root 缺席/零文件 → None。"""
    if not tex_root.is_dir():
        return None
    counts = dict.fromkeys(_EXPECTED_TEX_RX, 0)
    counts["cite"] = 0
    n_files = 0
    hyperref = False
    for fp in sorted(tex_root.rglob("*")):
        if fp.suffix.lower() not in (".tex", ".bbl") or not fp.is_file():
            continue
        try:
            text = _strip_comments(fp.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        n_files += 1
        hyperref = hyperref or bool(_HYPERREF_RX.search(text))
        for cat, rx in _EXPECTED_TEX_RX.items():
            counts[cat] += len(rx.findall(text))
        counts["cite"] += len(_BIBITEM_RX.findall(text))
    if not n_files:
        return None
    return {"counts": counts, "hyperref": hyperref, "n_files": n_files}


def landmark_metrics(pdf: Path, tex_root: Path | None) -> dict:
    """pdf 锚点分桶计数 + 期望数 + 各类存活比（期望 0 → None，不捏造 1.0）。

    ``coverage`` = 已插桩类别（section/figtable/equation/cite/footnote）的
    dests 合计 ÷ 期望合计——``other`` 桶（theorem./item./自定义名）不进
    分子，防止非标准 dest 名把存活率顶高（1907.03768 实测 43 个 other
    dest 会把全锚丢失掩盖成 0.70）。
    """
    lm = extract_landmarks(pdf)
    dests: dict[str, int] = {}
    for name in lm["dests"]:
        cat = _category(name)
        dests[cat] = dests.get(cat, 0) + 1
    exp_doc = expected_landmarks(tex_root) if tex_root else None
    expected = exp_doc["counts"] if exp_doc else None
    density: dict[str, float | None] = {}
    for cat in sorted(set(dests) | set(expected or {})):
        exp = (expected or {}).get(cat, 0)
        density[cat] = round(dests.get(cat, 0) / exp, 4) if exp else None
    n_expected = sum(expected.values()) if expected else 0
    n_dests = sum(dests.values())
    matched = sum(dests.get(c, 0) for c in _EXPECTED_TEX_RX) + dests.get("cite", 0)
    return {
        "pdf": pdf.name,
        "npages": lm["npages"],
        "n_dests": n_dests,
        "dests": dict(sorted(dests.items())),
        "expected": expected,
        "n_expected": n_expected,
        "hyperref": exp_doc["hyperref"] if exp_doc else None,
        "density": dict(sorted(density.items())),
        "coverage": round(matched / n_expected, 4) if n_expected else None,
        "density_all": round(n_dests / n_expected, 4) if n_expected else None,
    }


# ---------------------------------------------------------------- leak / term
def scan_leak(pairs: list[tuple[str, str]]) -> dict:
    """``(chunk_id, source)`` → parsebench 同口径六族泄漏扫描。"""
    hits = dict.fromkeys(LEAK_PATTERNS, 0)
    leaked = 0
    examples = []
    for cid, src in pairs:
        found = [name for name, rx in LEAK_PATTERNS.items() if rx.search(src)]
        if not found:
            continue
        leaked += 1
        for f in found:
            hits[f] += 1
        if len(examples) < 5:
            examples.append({"chunk_id": cid, "leaks": found})
    n = len(pairs)
    return {
        "leak_n": leaked,
        "leak_total": n,
        "leak_rate": round(leaked / n, 4) if n else None,
        "leak_hits": hits,
        "leak_examples": examples,
    }


def rebuild_term_dict(
    cat_group: str | None, sources: list[str], local_path: Path | None
) -> dict[str, str]:
    """重建 server 口径注入术语集（doc_filter 后），缺席层自动跳过。"""
    g = Glossary.load(
        user_path=_NO_USER_GLOSSARY,
        local_path=local_path,
        categories=[cat_group] if cat_group else (),
    )
    return g.doc_filter(sources)


def score_terms(pairs: list[tuple[str, str, str]], term_dict: dict[str, str]) -> dict:
    """``(chunk_id, source, translation)`` → 逐 chunk 术语命中核算。

    applicable = 已交付 chunk 的 source 命中术语 en 的 (chunk,term) 对数；
    hit = 对应 translation 含 zh。``term_misses`` 截 10 条供归因。
    """
    compiled = [
        (
            en,
            zh,
            re.compile(_TERM_BOUNDARY.format(re.escape(en)), re.IGNORECASE | re.ASCII),
        )
        for en, zh in term_dict.items()
    ]
    applicable = hit = 0
    misses = []
    for cid, src, zh_out in pairs:
        for en, zh, rx in compiled:
            if not rx.search(src):
                continue
            applicable += 1
            if zh in zh_out:
                hit += 1
            elif len(misses) < 10:
                misses.append({"en": en, "zh": zh, "chunk_id": cid})
    return {
        "term_applicable": applicable,
        "term_hit": hit,
        "term_hit_rate": round(hit / applicable, 4) if applicable else None,
        "term_misses": misses,
        "term_dict_size": len(term_dict),
    }


# ---------------------------------------------------------------- state 读取
def _state_pairs(state_path: Path) -> list[tuple[str, dict]]:
    """state.json ``results[]`` → ``(chunk_id, row)`` 末条胜（续跑重试幂等）。"""
    doc = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
    rows = doc.get("results") or []
    keyed = [r for r in rows if isinstance(r, dict) and r.get("chunk_id")]
    return list(benchlib.latest_by(keyed, lambda r: str(r.get("chunk_id"))).items())


def _xlat_metrics(
    wid: Path, arm: str, cat_group: str | None
) -> tuple[dict | None, str | None]:
    """返回 (translate 子树 patch, 缺失原因)。"""
    state_path = wid / "xlat-state" / arm / "state.json"
    if not state_path.is_file():
        return None, "state_missing"
    try:
        dedup = _state_pairs(state_path)
    except (json.JSONDecodeError, OSError) as e:
        return None, f"state_bad:{type(e).__name__}"
    pairs = [(cid, str(r.get("source") or "")) for cid, r in dedup]
    patch = scan_leak(pairs)
    if arm in TERM_ARMS:
        delivered = [
            (cid, str(r.get("source") or ""), str(r.get("translation") or ""))
            for cid, r in dedup
            if r.get("status") in ("ok", "partial") and r.get("translation")
        ]
        try:
            td = rebuild_term_dict(
                cat_group,
                [s for _c, s, _t in delivered],
                wid / "src" / LOCAL_GLOSSARY_NAME,
            )
            patch.update(score_terms(delivered, td))
        except Exception as e:
            patch.update(
                {
                    "term_applicable": None,
                    "term_hit": None,
                    "term_hit_rate": None,
                    "term_misses": [],
                    "term_dict_size": None,
                    "term_note": f"rebuild_failed:{type(e).__name__}",
                }
            )
    else:
        patch.update(
            {
                "term_applicable": None,
                "term_hit": None,
                "term_hit_rate": None,
                "term_misses": [],
                "term_dict_size": None,
            }
        )
    return {"translate": patch}, None


def _compile_metrics(
    wid: Path, arm: str, main_rel: str | None
) -> tuple[dict | None, str | None]:
    """zh→splice、base→build-base；fixloop post 重算属二期（spec §2）。"""
    sub = {"zh": "splice", "base": "build-base"}.get(arm)
    if sub is None:
        return None, "arm_unmapped"
    build_dir = wid / sub
    if not build_dir.is_dir():
        return None, f"{sub}_missing"
    pdf = None
    if main_rel:
        cand = build_dir / (Path(main_rel).stem + ".pdf")
        if cand.is_file():
            pdf = cand
    if pdf is None:
        pdfs = [p for p in build_dir.glob("*.pdf") if p.is_file()]
        if pdfs:
            pdf = max(pdfs, key=lambda p: p.stat().st_mtime)
    if pdf is None:
        return None, "no_pdf"
    try:
        return {"landmark": landmark_metrics(pdf, build_dir)}, None
    except Exception as e:
        return None, f"landmark_bad:{type(e).__name__}"


# ---------------------------------------------------------------- 驱动
def _load_cat_groups(manifest_paths: list[Path]) -> dict[str, str]:
    """manifest*.jsonl → {canon_id: cat_group}。"""
    out: dict[str, str] = {}
    for mp in manifest_paths:
        if not mp.is_file():
            continue
        for row in benchlib.iter_jsonl(mp, errors="replace"):
            if isinstance(row, dict) and row.get("id"):
                cg = row.get("cat_group")
                out[sl.canon_id(str(row["id"]))] = str(cg) if cg else ""
    return out


def _main_rel(rec: dict, wid: Path) -> str | None:
    m = (rec.get("metrics") or {}).get("main_rel")
    if isinstance(m, str) and m:
        return m
    pj = wid / "parse.json"
    if pj.is_file():
        try:
            doc = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
            m2 = doc.get("main_rel")
            return str(m2) if m2 else None
        except (json.JSONDecodeError, OSError):
            return None
    return None


def process_run(
    run_dir: Path,
    cat_groups: dict[str, str],
    *,
    jobs: int = 8,
    limit: int = 0,
    only_ids: set[str] | None = None,
) -> tuple[list[dict], dict]:
    """扫 run records → sidecar 行 + 汇总账。"""
    tasks: list[tuple[dict, str]] = []  # (rec, kind)
    for stage in ("xlat", "compile"):
        if limit and len(tasks) >= limit:
            break
        latest = sl.load_latest(run_dir / "records" / f"{stage}.jsonl")
        for (pid, arm, _up), rec in sorted(latest.items()):
            if limit and len(tasks) >= limit:
                break
            if only_ids is not None and pid not in only_ids:
                continue
            if stage == "xlat":
                if rec.get("status") not in ("ok", "partial", "fail"):
                    continue
                tasks.append((rec, "xlat"))
            elif arm in ("zh", "base") and rec.get("status") in ("clean", "partial"):
                tasks.append((rec, "compile"))

    missing: dict[str, int] = {}
    rows: list[dict] = []

    def work(item: tuple[dict, str]) -> tuple[dict, dict | None, str | None]:
        rec, kind = item
        pid = sl.canon_id(str(rec["id"]))
        wid = sl.workdir(run_dir, pid)
        if kind == "xlat":
            return rec, *_xlat_metrics(
                wid, str(rec.get("arm") or ""), cat_groups.get(pid) or None
            )
        return rec, *_compile_metrics(
            wid, str(rec.get("arm") or ""), _main_rel(rec, wid)
        )

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for rec, patch, miss in ex.map(work, tasks):
            if patch is None:
                missing[miss or "?"] = missing.get(miss or "?", 0) + 1
                continue
            rows.append(
                {
                    "id": sl.canon_id(str(rec["id"])),
                    "stage": rec.get("stage"),
                    "arm": rec.get("arm"),
                    "upstream": rec.get("upstream") or "",
                    "metrics": patch,
                }
            )

    leak_rates = [
        r["metrics"]["translate"]["leak_rate"]
        for r in rows
        if r["stage"] == "xlat"
        and r["metrics"]["translate"].get("leak_rate") is not None
    ]
    term_rates = [
        r["metrics"]["translate"]["term_hit_rate"]
        for r in rows
        if r["metrics"].get("translate", {}).get("term_hit_rate") is not None
    ]
    dens = [
        r["metrics"]["landmark"]["coverage"]
        for r in rows
        if r["stage"] == "compile"
        and r["metrics"]["landmark"].get("coverage") is not None
    ]
    summary = {
        "rows": len(rows),
        "xlat_rows": sum(1 for r in rows if r["stage"] == "xlat"),
        "compile_rows": sum(1 for r in rows if r["stage"] == "compile"),
        "missing": dict(sorted(missing.items())),
        "leak_rate_p50": statistics.median(leak_rates) if leak_rates else None,
        "leak_rate_max": max(leak_rates) if leak_rates else None,
        "term_hit_rate_p50": statistics.median(term_rates) if term_rates else None,
        "landmark_coverage_p50": statistics.median(dens) if dens else None,
        "landmark_coverage_max": max(dens) if dens else None,
    }
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path, help="stagerun 结果目录（含 records/ work/）")
    ap.add_argument(
        "--manifest",
        type=Path,
        action="append",
        default=None,
        help="manifest jsonl（可多次）；缺省 glob bench/corpus_v3/manifest*.jsonl",
    )
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="最多处理格数（冒烟用）")
    ap.add_argument("--ids", default="", help="逗号分隔 id 子集")
    ap.add_argument(
        "--out", type=Path, default=None, help="缺省 <run>/quality-metrics.jsonl"
    )
    args = ap.parse_args(argv)

    run_dir = args.run_dir.resolve()
    manifests = args.manifest or sorted(
        (ROOT / "bench/corpus_v3").glob("manifest*.jsonl")
    )
    cat_groups = _load_cat_groups(manifests)
    only = {sl.canon_id(i) for i in args.ids.split(",") if i.strip()} or None

    t0 = time.monotonic()
    rows, summary = process_run(
        run_dir, cat_groups, jobs=args.jobs, limit=args.limit, only_ids=only
    )
    out = args.out or (run_dir / "quality-metrics.jsonl")
    benchlib.atomic_write_text(
        out, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    )
    summary["seconds"] = round(time.monotonic() - t0, 1)
    summary["out"] = str(out)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
