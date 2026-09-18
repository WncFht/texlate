#!/usr/bin/env python3
r"""qualfreeze — qualbench 基线的钉集抽取 + 复跑分布漂移门禁。

两个子命令：

  freeze  从基线 records.jsonl（esa2 协议）抽 N chunk 回归钉集 →
          frozen300.jsonl。manifest 形态
          ``{paper, chunk_id, kind, model, zh, src}``——**不含分数**
          （分数属基线 records，钉集只钉 chunk 身份与文本）。
          分层口径：``stated100 < LOW_BAND``（默认 55，即 contest 阈）
          的低分格**全收**——回归集必须压住坏样本信号；剩余预算按
          kind×分位带（0-54/55-74/75-89/90-100）largest-remainder
          比例分配；``--min-kind kind:N``（默认 caption:40 +
          section_title:40）保底小类不被分层挤没。seed 固定
          → 选取确定可复现。文本字段优先级：record 自带
          ``src``/``zh`` > ``--sample`` manifest 补全（按
          model|paper|chunk 或 paper|chunk 回填）>
          ``src_excerpt``/``zh_excerpt`` 兜底（截断文本复跑 judge
          保真度打折，stderr 明示计数）。副产物
          ``<out>.meta.json`` 记 seed/输入/分层计数/文本来源账。

  check   对「同一 frozen 集的复跑 records」做**分布漂移**门禁——
          不逐 chunk 比对（judge 有噪声），只比分布层。两侧各按
          ``stated100`` 数值存在性过滤（excluded 数进报告）、按
          ``model|paper|chunk_id`` 末行胜去重。四个信号：

            stated100_ks   分布漂移：two-sample KS（有 scipy 走
                           scipy.stats.ks_2samp，否则手写 D 统计 +
                           Marsaglia–Tsang–Wang 渐近 p）；p < ks_alpha → drift
            flag_rates     逐 flag kind 率漂移：pooled 二比例 z-test，
                           p < flag_alpha → drift（不做多重校正——各 flag
                           独立信号，报告全量 p 供人工裁）
            kind_means     per-kind stated100 均值 |Δ| > kind_delta → drift
            contested_rate contested 率 |Δ| > contested_delta → drift
                           （附 z-test p 供参考，门禁看绝对差）

          ``--frozen`` 可选：给 frozen300 manifest 时两侧先过滤到
          钉集再比（baseline 传全量 records 时必需；传已过滤的
          frozen-records 则为无害 no-op）。门禁阈值是用户裁决项：
          CLI 默认 ``None`` → 代码内 ``DEFAULTS`` 兜底（当前全
          None，leader 填）；某阈值为 None 的信号记 disabled 不
          参与裁决；**全部 disabled → verdict=unarmed、exit 2**
          （没武装的门禁不算过）。

          产物：``--out`` gate_report.json（verdict/阈值/逐信号
          明细/键覆盖诊断）+ stdout 摘要。
          exit：0=pass · 3=drift detected · 2=usage error
          （文件缺/无 armed 信号/参数错——argparse 自报亦 2）。

与 stats lane 分工：本工具只做 gate/分布检验（KS、z-test、|Δ| 阈）；
bootstrap CI（paper 簇 block bootstrap、pairacc）归
``qualstats.py ci|pairacc|report``——CI 回答「指标多准」，本门禁
回答「两次跑分布漂没漂」。

用法:
  uv run python bench/py/qualfreeze.py freeze \
      --records bench/results/qualbase-2026-09-18/records.jsonl \
      --out bench/results/qualbase-2026-09-18/frozen300.jsonl \
      --sample bench/results/qualbase-2026-09-18/sample.jsonl
  uv run python bench/py/qualfreeze.py check \
      --baseline bench/results/qualbase-2026-09-18/records.jsonl \
      --new bench/results/qualrerun-XXXX/records.jsonl \
      --frozen bench/results/qualbase-2026-09-18/frozen300.jsonl \
      --out gate_report.json --ks-alpha 0.05 --kind-delta 5
依赖: 纯 stdlib + benchlib（scipy 可选，缺失走手写渐近 KS）。
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

import benchlib

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------- 常量

#: 低分格阈值——stated < LOW_BAND 的 chunk 全收（= contest 阈 STATED_CONTEST）
LOW_BAND = 55
#: 钉集默认规模
DEFAULT_N = 300
#: 默认 kind 保底（小类不被分层挤没；``kind:N`` 语法）
DEFAULT_MIN_KINDS = ("caption:40", "section_title:40")

#: flag 词表（与 qualstats.KNOWN_FLAGS 同源——门禁列全集，观测外 flag 并入）
KNOWN_FLAGS = (
    "untranslated_spans",
    "hallucinated_content",
    "mistranslation",
    "term_inconsistency",
    "over_translation",
    "placeholder_broken",
    "grammar",
    "fluency_register",
)

#: 门禁阈值——用户裁决④（2026-09-18）写死；None = 该信号 disabled 不参与裁决
DEFAULTS: dict[str, float | None] = {
    "ks_alpha": 0.05,
    "flag_alpha": 0.01,
    "kind_delta": 5.0,
    "contested_delta": 0.10,
}

EXIT_PASS = 0
EXIT_DRIFT = 3
EXIT_USAGE = 2


# ---------------------------------------------------------------- 通用件
def _num(x: object) -> bool:
    """数值分谓词（qualstats 同口径：int/float 非 bool）。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _unit_key(rec: dict) -> tuple[str, str, str]:
    """分布分析的单位键：``(model, paper, chunk_id)``——一 chunk-model 一分。"""
    return (
        str(rec.get("model") or ""),
        str(rec.get("paper") or "?"),
        str(rec.get("chunk_id") or "?"),
    )


def load_side(path: Path) -> tuple[list[dict], dict]:
    """records.jsonl → (judged 去重记录, 计数账)。

    去重两层：先按 record ``key`` 末行胜（resume 追加语义），再按
    ``model|paper|chunk_id`` 末行胜（同 chunk 多 judge/重测行只留
    最新一条——分布单位是一 chunk-model 一分）。随后按
    ``stated100`` 数值存在性分 judged / excluded。
    """
    recs = benchlib.read_jsonl(path)
    by_key = benchlib.latest_by(
        (r for r in recs if isinstance(r, dict)),
        lambda r: str(r.get("key") or "|".join(_unit_key(r))),
    )
    by_unit = benchlib.latest_by(by_key.values(), _unit_key)
    judged: list[dict] = []
    n_excluded = 0
    for r in by_unit.values():
        if _num(r.get("stated100")):
            judged.append(r)
        else:
            n_excluded += 1
    counts = {
        "n_raw": len(recs),
        "n_units": len(by_unit),
        "n_judged": len(judged),
        "n_excluded": n_excluded,
    }
    return judged, counts


def _band(score: float, low: float = LOW_BAND) -> str:
    """stated100 → 分位带标签（沿用 qualbench _SCORE_BANDS 口径，低分带沿 ``low``）。"""
    if score >= 90:
        return "90-100"
    if score >= 75:
        return "75-89"
    if score >= low:
        return f"{int(low)}-74"
    return f"0-{int(low) - 1}"


def _frozen_keys(manifest: Path) -> tuple[set, set]:
    """frozen manifest → (三元组键集, paper|chunk 键集)——check 过滤两侧用。"""
    triples: set[tuple[str, str, str]] = set()
    pairs: set[tuple[str, str]] = set()
    for r in benchlib.read_jsonl(manifest):
        if not isinstance(r, dict):
            continue
        paper = str(r.get("paper") or "?")
        chunk = str(r.get("chunk_id") or "?")
        model = str(r.get("model") or "")
        pairs.add((paper, chunk))
        if model:
            triples.add((model, paper, chunk))
    return triples, pairs


# ---------------------------------------------------------------- freeze
def _parse_min_kinds(specs: list[str] | None) -> dict[str, int]:
    """``kind:N`` 规格列 → {kind: N}；坏格式 argparse 层已挡，这里容错跳。"""
    out: dict[str, int] = {}
    for s in specs or DEFAULT_MIN_KINDS:
        if not s:
            continue
        kind, _, n = s.partition(":")
        try:
            out[kind.strip()] = int(n)
        except ValueError:
            print(f"warn: --min-kind 规格 {s!r} 不可解，跳过", file=sys.stderr)
    return out


def _text_of(
    rec: dict,
    sample_idx: dict[tuple[str, str, str], dict],
    sample_pc: dict[tuple[str, str], dict],
) -> tuple[str, str, str]:
    """record → (src, zh, text_source)。优先级见模块 docstring。"""
    src = rec.get("src")
    zh = rec.get("zh")
    if src and zh:
        return str(src), str(zh), "record"
    model, paper, chunk = _unit_key(rec)
    srow = sample_idx.get((model, paper, chunk)) or sample_pc.get((paper, chunk))
    if srow:
        s = srow.get("src") or srow.get("source")
        z = srow.get("zh") or srow.get("translation")
        if s and z:
            return str(s), str(z), "sample"
    return (
        str(rec.get("src_excerpt") or ""),
        str(rec.get("zh_excerpt") or ""),
        "excerpt",
    )


def cmd_freeze(args: argparse.Namespace) -> int:
    """分层抽 N chunk → frozen manifest + meta sidecar。"""
    rec_path = Path(args.records)
    if not rec_path.is_file():
        print(f"error: records 不存在 {rec_path}", file=sys.stderr)
        return EXIT_USAGE
    judged, counts = load_side(rec_path)
    if not judged:
        print("error: records 无 judged 行（stated100 全空）", file=sys.stderr)
        return EXIT_USAGE

    rng = random.Random(args.seed)
    min_kinds = _parse_min_kinds(args.min_kind)
    low = float(args.low_band)
    if not 0 < low <= 75:
        print(
            f"error: --low-band {low} 越界（须在 (0,75]——低分带之上"
            "还得有 55-74/75-89/90-100 三带可分层）",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # 分层桶：kind × band → records（确定性序）
    strata: dict[tuple[str, str], list[dict]] = {}
    for r in sorted(judged, key=_unit_key):
        cell = (str(r.get("kind") or "?"), _band(float(r["stated100"]), low))
        strata.setdefault(cell, []).append(r)

    # 低分带（stated < low）全收——回归集压住坏样本信号
    selected: dict[tuple[str, str, str], dict] = {}
    n_low = 0
    for rows in strata.values():
        for r in rows:
            if float(r["stated100"]) < low:
                selected[_unit_key(r)] = r
                n_low += 1

    # kind 保底：不足 N 从同 kind 剩余池 seed 补齐（跨带均匀）
    for kind, floor in min_kinds.items():
        have = sum(1 for k in selected.values() if str(k.get("kind")) == kind)
        if have >= floor:
            continue
        pool = [
            r
            for (k2, _), rows in strata.items()
            if k2 == kind
            for r in rows
            if _unit_key(r) not in selected
        ]
        take = min(floor - have, len(pool))
        if take < floor - have:
            print(
                f"warn: kind={kind} 全量 {have + len(pool)} < 保底 {floor}",
                file=sys.stderr,
            )
        for r in rng.sample(pool, take):
            selected[_unit_key(r)] = r

    # 剩余预算：kind×band largest-remainder 比例分配
    budget = max(0, args.n - len(selected))
    cells = {
        c: [r for r in rows if _unit_key(r) not in selected]
        for c, rows in strata.items()
    }
    cells = {c: rs for c, rs in cells.items() if rs}
    total_rem = sum(len(rs) for rs in cells.values())
    if budget and total_rem:
        quotas = {c: budget * len(rs) / total_rem for c, rs in cells.items()}
        alloc = {c: min(int(q), len(cells[c])) for c, q in quotas.items()}
        leftover = min(budget - sum(alloc.values()), total_rem - sum(alloc.values()))
        # 小数部分大者优先补 1（确定性 tie-break：cell 名序）
        for c in sorted(quotas, key=lambda c: (-(quotas[c] % 1), c)):
            if leftover <= 0:
                break
            if alloc[c] < len(cells[c]):
                alloc[c] += 1
                leftover -= 1
        # 极端：配额发完还有剩（池子比预算小已由 min 截住），顺序补满
        if leftover > 0:
            for c in sorted(cells):
                if leftover <= 0:
                    break
                room = len(cells[c]) - alloc[c]
                bump = min(room, leftover)
                alloc[c] += bump
                leftover -= bump
        for c, k in alloc.items():
            for r in rng.sample(sorted(cells[c], key=_unit_key), k):
                selected[_unit_key(r)] = r
    elif len(selected) > args.n:
        print(
            f"warn: 低分+保底已占 {len(selected)} > --n {args.n}，钉集超编",
            file=sys.stderr,
        )

    picked = sorted(selected.values(), key=_unit_key)
    if len(picked) < args.n:
        print(
            f"warn: 可抽 judged 仅 {len(judged)}，钉集 {len(picked)} < --n {args.n}",
            file=sys.stderr,
        )

    # sample manifest 全文索引（可选）
    sample_idx: dict[tuple[str, str, str], dict] = {}
    sample_pc: dict[tuple[str, str], dict] = {}
    if args.sample:
        for s in benchlib.read_jsonl(Path(args.sample)):
            if not isinstance(s, dict):
                continue
            paper = str(s.get("paper") or "?")
            chunk = str(s.get("chunk_id") or "?")
            model = str(s.get("model") or "")
            sample_pc[(paper, chunk)] = s
            if model:
                sample_idx[(model, paper, chunk)] = s

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text_src_tally: dict[str, int] = {}
    with out_path.open("w", encoding="utf-8") as fh:
        for r in picked:
            src, zh, via = _text_of(r, sample_idx, sample_pc)
            text_src_tally[via] = text_src_tally.get(via, 0) + 1
            benchlib.write_jsonl(
                fh,
                {
                    "paper": r.get("paper"),
                    "chunk_id": r.get("chunk_id"),
                    "kind": r.get("kind"),
                    "model": r.get("model"),
                    "zh": zh,
                    "src": src,
                },
            )
    if text_src_tally.get("excerpt"):
        print(
            f"warn: {text_src_tally['excerpt']}/{len(picked)} 行只有 "
            "excerpt 截断文本（record 无 src/zh 且未命中 --sample）——"
            "复跑 judge 保真度打折",
            file=sys.stderr,
        )

    # 分层账：kind × band → 选中数/池数
    strata_report = {}
    for (kind, band), rows in sorted(strata.items()):
        n_sel = sum(
            1
            for r in picked
            if str(r.get("kind")) == kind and _band(float(r["stated100"]), low) == band
        )
        strata_report[f"{kind}|{band}"] = {"pool": len(rows), "picked": n_sel}
    meta = {
        "records": str(rec_path),
        "out": str(out_path),
        "seed": args.seed,
        "n_target": args.n,
        "n_picked": len(picked),
        "n_low_band_all_in": n_low,
        "min_kinds": min_kinds,
        "low_band": low,
        "sample": args.sample,
        "text_source_tally": text_src_tally,
        "input_counts": counts,
        "strata": strata_report,
        "created_at": datetime.now(UTC).isoformat(),
    }
    meta_path = out_path.with_name(f"{out_path.stem}.meta.json")
    benchlib.atomic_write_text(
        meta_path, json.dumps(meta, ensure_ascii=False, indent=1) + "\n"
    )
    print(
        f"frozen -> {out_path} ({len(picked)}/{args.n} · "
        f"low_all_in={n_low} · text={text_src_tally}) · meta -> {meta_path}"
    )
    return EXIT_PASS


# ---------------------------------------------------------------- check：检验件
def _kolmogorov_sf(lam: float) -> float:
    """Kolmogorov 极限分布 SF：Q(λ) = 2·Σ_{j≥1} (-1)^{j-1} e^{-2j²λ²}。

    scipy ``kolmogorov.sf`` 的渐近口径手抄：λ 小区域交替级数慢收敛且
    真值→1（D 本来就小，门禁必过），<0.4 直接归 1；≥0.4 级数项
    e^{-2j²λ²} 快速衰减，截到 1e-10 / j=200 封顶，值域钳 [0,1]。
    """
    if lam < 0.4:
        return 1.0
    s = 0.0
    for j in range(1, 201):
        t = math.exp(-2.0 * j * j * lam * lam)
        s += t if j % 2 else -t
        if t < 1e-10:
            break
    return max(0.0, min(1.0, 2.0 * s))


def ks_2samp(a: list[float], b: list[float]) -> tuple[float, float, str]:
    """two-sample KS → (D, p, method)。有 scipy 用 scipy，否则手写渐近。"""
    try:
        from scipy.stats import ks_2samp as _scipy_ks

        res = _scipy_ks(a, b, method="asymp")
        return float(res.statistic), float(res.pvalue), "scipy.asymp"
    except ImportError:
        pass
    xs, ys = sorted(a), sorted(b)
    n1, n2 = len(xs), len(ys)
    i = j = 0
    d = 0.0
    while i < n1 and j < n2:
        v = min(xs[i], ys[j])
        while i < n1 and xs[i] <= v:
            i += 1
        while j < n2 and ys[j] <= v:
            j += 1
        d = max(d, abs(i / n1 - j / n2))
    # 一侧扫尽后，ECDF 差在末端固定为 |i/n1 - j/n2|
    d = max(d, abs(i / n1 - j / n2))
    en = n1 * n2 / (n1 + n2)
    lam = (math.sqrt(en) + 0.12 + 0.11 / math.sqrt(en)) * d
    return d, _kolmogorov_sf(lam), "manual.asymp"


def prop_z(k1: int, n1: int, k2: int, n2: int) -> dict:
    """pooled 二比例 z-test → {p1, p2, diff, z, p}；分母 0 → z=0,p=1。"""
    p1 = k1 / n1 if n1 else 0.0
    p2 = k2 / n2 if n2 else 0.0
    p_pool = (k1 + k2) / (n1 + n2) if (n1 + n2) else 0.0
    denom = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if n1 and n2 else 0.0
    if denom == 0.0:
        return {
            "p1": p1,
            "p2": p2,
            "diff": p2 - p1,
            "z": 0.0,
            "p": 1.0,
        }
    z = (p2 - p1) / denom
    return {
        "p1": p1,
        "p2": p2,
        "diff": p2 - p1,
        "z": z,
        "p": math.erfc(abs(z) / math.sqrt(2.0)),
    }


def _resolve(args: argparse.Namespace) -> dict[str, float | None]:
    """CLI > DEFAULTS 阈值归一；全 None → 无 armed 信号。"""
    return {
        name: (
            getattr(args, name) if getattr(args, name) is not None else DEFAULTS[name]
        )
        for name in DEFAULTS
    }


def cmd_check(args: argparse.Namespace) -> int:
    """两侧 records → 分布漂移门禁 → gate_report.json + exit code。"""
    base_p, new_p = Path(args.baseline), Path(args.new)
    in_paths = [base_p, new_p] + ([Path(args.frozen)] if args.frozen else [])
    for p in in_paths:
        if not p.is_file():
            print(f"error: 输入不存在 {p}", file=sys.stderr)
            return EXIT_USAGE

    base, c_base = load_side(base_p)
    new, c_new = load_side(new_p)

    # --frozen：两侧过滤到钉集（baseline 全量 records 时必需）。
    # manifest 带 model（常态）→ 只按三元组匹配——(paper,chunk) 双轨会把
    # 同 chunk 异 model 的记录也放进门；manifest 无 model 才退 pairs。
    frozen_info = None
    if args.frozen:
        triples, pairs = _frozen_keys(Path(args.frozen))

        def _in_frozen(r: dict) -> bool:
            uk = _unit_key(r)
            if triples:
                return uk in triples
            return (uk[1], uk[2]) in pairs

        base = [r for r in base if _in_frozen(r)]
        new = [r for r in new if _in_frozen(r)]
        frozen_info = {
            "path": str(args.frozen),
            "n_manifest": len(pairs),
            "n_base_covered": len(base),
            "n_new_covered": len(new),
        }

    thr = _resolve(args)
    if not base or not new:
        # 空侧不能当 vacuous pass——门禁没数据可裁就是 usage 错
        report = {
            "verdict": "empty_side",
            "generated_at": datetime.now(UTC).isoformat(),
            "inputs": {
                "baseline": str(base_p),
                "new": str(new_p),
                "frozen": args.frozen,
            },
            "counts": {
                "baseline": c_base,
                "new": c_new,
                "frozen": frozen_info,
                "n_base_used": len(base),
                "n_new_used": len(new),
            },
            "thresholds": thr,
        }
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        benchlib.atomic_write_text(
            out_p, json.dumps(report, ensure_ascii=False, indent=1) + "\n"
        )
        print(
            f"error: 过滤后一侧为空（base={len(base)} new={len(new)}）——门禁没数据可裁",
            file=sys.stderr,
        )
        print(f"report -> {out_p}")
        return EXIT_USAGE

    drift_signals: list[str] = []
    checks: dict[str, dict] = {}

    # ---- 1) stated100 KS ------------------------------------------------
    a_scores = [float(r["stated100"]) for r in base]
    b_scores = [float(r["stated100"]) for r in new]
    if thr["ks_alpha"] is not None and a_scores and b_scores:
        d, p, method = ks_2samp(a_scores, b_scores)
        hit = p < thr["ks_alpha"]
        checks["stated100_ks"] = {
            "enabled": True,
            "D": round(d, 6),
            "p_value": p,
            "method": method,
            "alpha": thr["ks_alpha"],
            "drift": hit,
        }
        if hit:
            drift_signals.append(f"stated100_ks p={p:.4g}<{thr['ks_alpha']}")
    else:
        checks["stated100_ks"] = {
            "enabled": False,
            "reason": "threshold unset" if thr["ks_alpha"] is None else "empty side",
        }

    # ---- 2) 逐 flag 率 z-test -------------------------------------------
    flags_seen = sorted(
        set(KNOWN_FLAGS) | {f for r in base + new for f in (r.get("flags") or [])}
    )
    flag_rows: dict[str, dict] = {}
    n_flag_drift = 0
    for f in flags_seen:
        k1 = sum(1 for r in base if f in (r.get("flags") or []))
        k2 = sum(1 for r in new if f in (r.get("flags") or []))
        zr = prop_z(k1, len(base), k2, len(new))
        hit = thr["flag_alpha"] is not None and zr["p"] < thr["flag_alpha"]
        flag_rows[f] = {
            "k_base": k1,
            "k_new": k2,
            "rate_base": round(zr["p1"], 6),
            "rate_new": round(zr["p2"], 6),
            "diff": round(zr["diff"], 6),
            "z": round(zr["z"], 4),
            "p_value": zr["p"],
            "drift": bool(hit),
        }
        if hit:
            n_flag_drift += 1
            drift_signals.append(
                f"flag/{f} {zr['p1']:.3f}→{zr['p2']:.3f} p={zr['p']:.4g}"
            )
    checks["flag_rates"] = {
        "enabled": thr["flag_alpha"] is not None,
        "alpha": thr["flag_alpha"],
        "n_flags_drifted": n_flag_drift,
        "per_flag": flag_rows,
        "note": "逐 flag 独立检验，未做多重校正",
    }

    # ---- 3) per-kind 均值 |Δ| --------------------------------------------
    kinds = sorted(
        {str(r.get("kind") or "?") for r in base}
        | {str(r.get("kind") or "?") for r in new}
    )
    kind_rows: dict[str, dict] = {}
    n_kind_drift = 0
    for k in kinds:
        xs = [float(r["stated100"]) for r in base if str(r.get("kind") or "?") == k]
        ys = [float(r["stated100"]) for r in new if str(r.get("kind") or "?") == k]
        m1 = statistics.mean(xs) if xs else None
        m2 = statistics.mean(ys) if ys else None
        delta = (m2 - m1) if (m1 is not None and m2 is not None) else None
        hit = (
            thr["kind_delta"] is not None
            and delta is not None
            and abs(delta) > thr["kind_delta"]
        )
        kind_rows[k] = {
            "n_base": len(xs),
            "n_new": len(ys),
            "mean_base": round(m1, 4) if m1 is not None else None,
            "mean_new": round(m2, 4) if m2 is not None else None,
            "delta": round(delta, 4) if delta is not None else None,
            "drift": bool(hit),
        }
        if hit:
            n_kind_drift += 1
            drift_signals.append(f"kind/{k} mean Δ={delta:+.1f}")
    checks["kind_means"] = {
        "enabled": thr["kind_delta"] is not None,
        "delta": thr["kind_delta"],
        "n_kinds_drifted": n_kind_drift,
        "per_kind": kind_rows,
    }

    # ---- 4) contested 率 -------------------------------------------------
    k1 = sum(1 for r in base if r.get("contested"))
    k2 = sum(1 for r in new if r.get("contested"))
    zr = prop_z(k1, len(base), k2, len(new))
    hit = (
        thr["contested_delta"] is not None
        and len(base)
        and len(new)
        and abs(zr["diff"]) > thr["contested_delta"]
    )
    checks["contested_rate"] = {
        "enabled": thr["contested_delta"] is not None,
        "delta": thr["contested_delta"],
        "rate_base": round(zr["p1"], 6),
        "rate_new": round(zr["p2"], 6),
        "diff": round(zr["diff"], 6),
        "z": round(zr["z"], 4),
        "p_value": zr["p"],
        "drift": bool(hit),
    }
    if hit:
        drift_signals.append(f"contested {zr['p1']:.3f}→{zr['p2']:.3f}")

    # ---- verdict ----------------------------------------------------------
    armed = [n for n in DEFAULTS if checks.get(_CHECK_MAP[n], {}).get("enabled")]
    if not armed:
        verdict = "unarmed"
        code = EXIT_USAGE
    elif drift_signals:
        verdict = "drift"
        code = EXIT_DRIFT
    else:
        verdict = "pass"
        code = EXIT_PASS

    report = {
        "verdict": verdict,
        "generated_at": datetime.now(UTC).isoformat(),
        "inputs": {
            "baseline": str(base_p),
            "new": str(new_p),
            "frozen": args.frozen,
        },
        "counts": {
            "baseline": c_base,
            "new": c_new,
            "frozen": frozen_info,
            "n_base_used": len(base),
            "n_new_used": len(new),
            "n_common_units": len(
                {_unit_key(r) for r in base} & {_unit_key(r) for r in new}
            ),
        },
        "thresholds": thr,
        "armed_signals": armed,
        "checks": checks,
        "drift_signals": drift_signals,
    }
    out_p = Path(args.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    benchlib.atomic_write_text(
        out_p, json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    )

    print(
        f"# qualfreeze check — verdict={verdict} "
        f"(base n={len(base)} excl={c_base['n_excluded']} · "
        f"new n={len(new)} excl={c_new['n_excluded']})"
    )
    for name, c in checks.items():
        if not c.get("enabled"):
            print(f"  {name:16} disabled ({c.get('reason', 'threshold unset')})")
        elif name == "stated100_ks":
            print(
                f"  {name:16} D={c['D']:.4f} p={c['p_value']:.4g} "
                f"({'DRIFT' if c['drift'] else 'ok'} · {c['method']})"
            )
        elif name == "flag_rates":
            print(f"  {name:16} {c['n_flags_drifted']} flag(s) drifted")
        elif name == "kind_means":
            print(f"  {name:16} {c['n_kinds_drifted']} kind(s) drifted")
        elif name == "contested_rate":
            print(
                f"  {name:16} {c['rate_base']:.3f}→{c['rate_new']:.3f} "
                f"({'DRIFT' if c['drift'] else 'ok'})"
            )
    for s in drift_signals:
        print(f"  ! {s}")
    print(f"report -> {out_p}")
    if verdict == "unarmed":
        print(
            "error: 无 armed 信号——门禁阈值全 None（传 --ks-alpha 等或填 DEFAULTS）",
            file=sys.stderr,
        )
    return code


#: DEFAULTS 键 → checks 块名（armed 判定映射）
_CHECK_MAP = {
    "ks_alpha": "stated100_ks",
    "flag_alpha": "flag_rates",
    "kind_delta": "kind_means",
    "contested_delta": "contested_rate",
}


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_fz = sub.add_parser("freeze", help="基线 records → 分层钉集 manifest")
    p_fz.add_argument("--records", required=True, help="基线 records.jsonl")
    p_fz.add_argument("--out", required=True, help="产出 frozen300.jsonl")
    p_fz.add_argument(
        "--sample",
        default=None,
        help="qualsample sample.jsonl——record 无全文时按此回填 src/zh",
    )
    p_fz.add_argument("--n", type=int, default=DEFAULT_N)
    p_fz.add_argument("--seed", type=int, default=20260918)
    p_fz.add_argument(
        "--low-band",
        type=float,
        default=LOW_BAND,
        help="stated 低于此值全收（默认 55=contest 阈）",
    )
    p_fz.add_argument(
        "--min-kind",
        action="append",
        default=None,
        metavar="kind:N",
        help="kind 保底数（可多次，指定后整体替换默认 caption:40 + section_title:40）",
    )
    p_fz.set_defaults(fn=cmd_freeze)

    p_ck = sub.add_parser("check", help="复跑 records → 分布漂移门禁")
    p_ck.add_argument("--baseline", required=True, help="基线 records.jsonl")
    p_ck.add_argument("--new", required=True, help="复跑 records.jsonl")
    p_ck.add_argument(
        "--frozen",
        default=None,
        help="frozen300.jsonl——给定时两侧先过滤到钉集",
    )
    p_ck.add_argument("--out", required=True, help="gate_report.json")
    p_ck.add_argument("--ks-alpha", type=float, default=None)
    p_ck.add_argument("--flag-alpha", type=float, default=None)
    p_ck.add_argument("--kind-delta", type=float, default=None)
    p_ck.add_argument("--contested-delta", type=float, default=None)
    p_ck.set_defaults(fn=cmd_check)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
