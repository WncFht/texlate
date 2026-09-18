#!/usr/bin/env python3
r"""qualsample — 分层基线抽样：xlat state 池 → sample.jsonl + sample_meta.json。

qualbench ``--source manifest`` 的上游：把 stagerun/e2e_real 已落盘的
``state.json`` 池按冻结协议抽 ~1200 chunk（~350 篇 × 3-4 块/篇——簇多 CI 窄，
文档即 bootstrap 聚类单元），src/zh 全文落盘，judge 批不再回读 state。

池与优先级（``POOLS``）：
  rt1      ``bench/results/stagerun-rt1/work/{id}/xlat-state/real/state.json``
           ——finished rt1 批，arm=real，swe-2-medium，主池。
  e2ereal  ``bench/work_e2ereal/_xlat_state/{id}/state.json``
           ——e2e_real 批副池，arm=""。同 paper id → rt1 优先（arm=real 同质，
           副池整篇丢弃不混块）；e2e-only 篇排在候选序尾部只补缺。

分层（冻结协议 docs/research/xlat-quality-eval-2026-09-18）：
  para 按 src 长度三分层——切点取**池级**分布（rt1 全部可用 para 的 len(src)
  1/3、2/3 分位），配额均摊；caption/section_title 各保底 ``--caption`` /
  ``--section-title``（默认 150）；其余 kind（abstract/table_text/env_text…）
  有则收不保底（当前两池实测为零）。para 配额 = ``--chunks - caption - section``
  均分三档，余数给低 tertile。

选篇与取块：
  候选序 = shuffle(rt1 篇) + shuffle(e2e-only 篇)，rng=``--seed``。顺序放篇至
  ``--papers`` 篇；此后任一分层候选仍不足配额则继续放篇补缺（"同池放宽篇数补"——
  放篇序本身先 rt1 后 e2e，天然同池优先）。stratum 内按篇轮转（round-robin，
  每篇每轮出 1 块）取至配额——跨篇摊平，保证簇数。

行 schema：``{paper, chunk_id, kind, model, src, zh, arm, status, pool,
len_tertile}``——``len_tertile`` 仅 para 标 0/1/2，其他 kind 为 null。行序为
跨篇轮转序（qualbench collect_manifest_pairs 同款），--n 截前缀仍是多样本。

用法:
  uv run python bench/py/qualsample.py --dry-run          # 分层统计不写盘
  uv run python bench/py/qualsample.py --seed 20260918 --papers 350 \
      --out bench/results/qualbase-2026-09-18/
依赖: 纯 stdlib + benchlib/qualbench（``_state_files``/``Pair`` 复用）。
"""

from __future__ import annotations

import argparse
import collections
import json
import random
from datetime import UTC, datetime
from pathlib import Path

import benchlib
import qualbench

ROOT = Path(__file__).resolve().parents[2]

#: 池登记——(root, pool 标签, arm 语义)。序即优先级：rt1 主池先行。
POOLS = (
    ("rt1", ROOT / "bench/results/stagerun-rt1/work"),
    ("e2ereal", ROOT / "bench/work_e2ereal/_xlat_state"),
)

KEEP_STATUS = ("ok", "partial")


# ---------------------------------------------------------------- 池扫描（pass 1：轻量索引）
def scan_pools() -> tuple[dict, dict]:
    """两池 state.json → ({pool: {paper: light}}, {pool: census})。

    light = {path, arm, model, kinds:{kind:n}, para_lens:[len(src)...]}——
    不存 src/zh 本体（~9 万 para 全留内存不值；选中篇 pass 2 回读）。
    census = {files, papers, usable_chunks, kinds:{kind:n}} 供 meta/报告。
    """
    papers: dict[str, dict] = {}
    census: dict[str, dict] = {}
    for pool, root in POOLS:
        pool_papers: dict[str, dict] = {}
        c_kinds = collections.Counter()
        n_files = 0
        for path, paper, arm in qualbench._state_files([root]):
            n_files += 1
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            model = str((data.get("meta") or {}).get("model") or "?")
            last: dict[str, dict] = {}
            for r in data.get("results") or []:
                last[str(r.get("chunk_id"))] = r
            kinds = collections.Counter()
            para_lens: list[int] = []
            for r in last.values():
                status = str(r.get("status") or "")
                zh = str(r.get("translation") or "")
                src = str(r.get("source") or "")
                if status not in KEEP_STATUS or zh == src:
                    continue
                kind = str(r.get("kind") or "para")
                kinds[kind] += 1
                c_kinds[kind] += 1
                if kind == "para":
                    para_lens.append(len(src))
            if not kinds:
                continue
            pool_papers[paper] = {
                "path": path,
                "arm": arm,
                "model": model,
                "kinds": dict(kinds),
                "para_lens": para_lens,
            }
        papers[pool] = pool_papers
        census[pool] = {
            "root": str(root.relative_to(ROOT)),
            "files": n_files,
            "papers": len(pool_papers),
            "usable_chunks": sum(c_kinds.values()),
            "kinds": dict(c_kinds),
        }
    return papers, census


# ---------------------------------------------------------------- tertile
def tertile_cuts(lens: list[int]) -> tuple[int, int]:
    """池级 para len(src) → (q33, q66) 闭边界：len<=q33→t0, <=q66→t1, else t2。"""
    s = sorted(lens)
    if not s:
        return (0, 0)
    n = len(s)
    return (s[n // 3], s[(2 * n) // 3])


def tertile_of(n: int, q1: int, q2: int) -> int:
    return 0 if n <= q1 else (1 if n <= q2 else 2)


# ---------------------------------------------------------------- 选篇
def admit_papers(
    papers: dict[str, dict],
    cuts: tuple[int, int],
    targets: dict[tuple[str, int | None], int],
    n_papers: int,
    rng: random.Random,
) -> tuple[list[tuple[str, str]], list[dict]]:
    """候选序（rt1 shuffle → e2e-only shuffle）放篇至配额可达 → [(pool, paper)]。

    放够 ``n_papers`` 篇后逐层核候选量；任一分层不足配额则继续放篇补缺
    （序内先 rt1 后 e2e——"副池只补缺"）。返回放篇序 + gaps 记录。
    """
    rt1 = papers["rt1"]
    e2e_only = {p: v for p, v in papers["e2ereal"].items() if p not in rt1}
    # 两个独立 shuffle 保持池优先级（不是合并洗牌）——"副池只补缺"
    rt1_order = sorted(rt1)
    rng.shuffle(rt1_order)
    e2e_order = sorted(e2e_only)
    rng.shuffle(e2e_order)
    order = [("rt1", p) for p in rt1_order] + [("e2ereal", p) for p in e2e_order]

    def strata_of(pool: str, paper: str) -> dict[tuple[str, int | None], int]:
        info = papers[pool][paper]
        out: dict[tuple[str, int | None], int] = {}
        tc = collections.Counter(
            tertile_of(n, cuts[0], cuts[1]) for n in info["para_lens"]
        )
        for t in (0, 1, 2):
            out[("para", t)] = tc.get(t, 0)
        for kind, n in info["kinds"].items():
            if kind != "para":
                out[(kind, None)] = n
        return out

    have = collections.Counter()
    admitted: list[tuple[str, str]] = []
    gaps: list[dict] = []
    i = 0
    while i < len(order):
        pool, paper = order[i]
        i += 1
        if not papers[pool][paper]["kinds"]:
            continue
        admitted.append((pool, paper))
        for sk, n in strata_of(pool, paper).items():
            have[sk] += n
        if len(admitted) >= n_papers and all(
            have.get(sk, 0) >= t for sk, t in targets.items()
        ):
            break
    shortfalls = {
        sk: (have.get(sk, 0), t) for sk, t in targets.items() if have.get(sk, 0) < t
    }
    if len(admitted) > n_papers:
        gaps.append(
            {
                "action": "extended_papers",
                "papers": len(admitted),
                "reason": f"strata shortfall at n_papers={n_papers}",
            }
        )
    for (kind, t), (got, want) in sorted(shortfalls.items(), key=str):
        gaps.append(
            {
                "stratum": f"{kind}[{t}]" if t is not None else kind,
                "target": want,
                "available": got,
                "action": "shortfall_exhausted",
            }
        )
    n_e2e = sum(1 for pool, _ in admitted if pool == "e2ereal")
    if n_e2e:
        gaps.append({"action": "e2e_gapfill", "papers": n_e2e})
    return admitted, gaps


# ---------------------------------------------------------------- 取块（pass 2：选中篇回读）
def _nat_key(cid: str):
    """chunk_id 自然序键（``0:1`` < ``0:23`` < ``0:108``）。"""
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in cid.split(":"))


def load_chunks(path: Path) -> list[dict]:
    """state.json → 末行胜去重后的可用块（status∈ok/partial ∧ zh≠src）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    last: dict[str, dict] = {}
    for r in data.get("results") or []:
        last[str(r.get("chunk_id"))] = r
    out = []
    for r in last.values():
        status = str(r.get("status") or "")
        zh = str(r.get("translation") or "")
        src = str(r.get("source") or "")
        if status in KEEP_STATUS and zh != src:
            out.append(
                {
                    "chunk_id": str(r.get("chunk_id")),
                    "kind": str(r.get("kind") or "para"),
                    "src": src,
                    "zh": zh,
                    "status": status,
                }
            )
    return sorted(out, key=lambda c: _nat_key(c["chunk_id"]))


def pick_strata(
    admitted: list[tuple[str, str]],
    papers: dict[str, dict],
    cuts: tuple[int, int],
    targets: dict[tuple[str, int | None], int],
    rng: random.Random,
) -> list[dict]:
    """分层配额取块：stratum 内跨篇 round-robin（每篇每轮 1 块）→ 摊平簇。"""
    # 每篇 → {stratum_key: [chunk,...]（seed 洗牌）}
    per_paper: dict[str, dict[tuple[str, int | None], collections.deque]] = {}
    for pool, paper in admitted:
        info = papers[pool][paper]
        buckets: dict[tuple[str, int | None], list[dict]] = collections.defaultdict(
            list
        )
        for c in load_chunks(info["path"]):
            if c["kind"] == "para":
                buckets[("para", tertile_of(len(c["src"]), cuts[0], cuts[1]))].append(c)
            else:
                buckets[(c["kind"], None)].append(c)
        per_paper[paper] = {}
        for sk, lst in buckets.items():
            rng.shuffle(lst)
            per_paper[paper][sk] = collections.deque(lst)

    picks: list[tuple[str, str, dict, int | None]] = []  # (pool, paper, chunk, tertile)
    # 连续游标跨 stratum 轮转：每 stratum 不重头——游标在 admitted 环上持续推进，
    # 尾部篇不再每层都被跳过（固定起点会让末位 ~50 篇全层陪跑零产出）。
    n = len(admitted)
    cursor = 0
    for sk, target in sorted(targets.items(), key=str):
        got = 0
        while got < target:
            progressed = False
            for _ in range(n):  # 从 cursor 起满一圈
                if got >= target:
                    break
                pool, paper = admitted[cursor]
                cursor = (cursor + 1) % n
                q = per_paper[paper].get(sk)
                if q:
                    picks.append((pool, paper, q.popleft(), sk[1]))
                    got += 1
                    progressed = True
            if not progressed:
                break
    # 无配额 kind（abstract/table_text/env_text…）有则收：全量收进
    targeted_kinds = {k for k, _ in targets}
    for pool, paper in admitted:
        for (kind, _), q in per_paper[paper].items():
            if kind not in targeted_kinds:
                picks.extend((pool, paper, c, None) for c in q)
    return picks


# ---------------------------------------------------------------- 主流程
def build_sample(args) -> tuple[list[dict], dict]:
    rng = random.Random(args.seed)
    papers, census = scan_pools()

    rt1_para_lens = [n for info in papers["rt1"].values() for n in info["para_lens"]]
    cuts = tertile_cuts(rt1_para_lens)
    para_total = max(0, args.chunks - args.caption - args.section_title)
    base, rem = divmod(para_total, 3)
    targets: dict[tuple[str, int | None], int] = {
        ("para", 0): base + (1 if rem > 0 else 0),
        ("para", 1): base + (1 if rem > 1 else 0),
        ("para", 2): base,
        ("caption", None): args.caption,
        ("section_title", None): args.section_title,
    }

    admitted, gaps = admit_papers(papers, cuts, targets, args.papers, rng)
    picks = pick_strata(admitted, papers, cuts, targets, rng)

    # 行拼装 + 跨篇轮转序（qualbench 同款：任取 --n 前缀仍跨篇分散）
    by_paper: dict[str, list[dict]] = collections.defaultdict(list)
    for pool, paper, c, tert in picks:
        info = papers[pool][paper]
        by_paper[paper].append(
            {
                "paper": paper,
                "chunk_id": c["chunk_id"],
                "kind": c["kind"],
                "model": info["model"],
                "src": c["src"],
                "zh": c["zh"],
                "arm": info["arm"],
                "status": c["status"],
                "pool": pool,
                "len_tertile": tert,
            }
        )
    rows: list[dict] = []
    queues = {p: collections.deque(rs) for p, rs in sorted(by_paper.items())}
    while queues:
        for p in list(queues):
            q = queues[p]
            if q:
                rows.append(q.popleft())
            if not q:
                del queues[p]

    # meta.strata：para 记 tertile {n,lo,hi}（lo/hi = 该层 len 闭区间），
    # 其他 kind 记 {n}；quota 未达时 n 为实收并已由 gaps 留痕
    lens_sorted = sorted(rt1_para_lens)
    bounds = (
        (lens_sorted[0], cuts[0]),
        (cuts[0] + 1, cuts[1]),
        (cuts[1] + 1, lens_sorted[-1]),
    )
    got = collections.Counter((r["kind"], r["len_tertile"]) for r in rows)
    strata: dict[str, dict] = {"para": {"cuts": list(cuts)}}
    for t in (0, 1, 2):
        strata["para"][str(t)] = {
            "n": got.get(("para", t), 0),
            "lo": bounds[t][0],
            "hi": bounds[t][1],
        }
    for kind, _ in targets:
        if kind == "para":
            continue
        strata[kind] = {"n": got.get((kind, None), 0)}
    for (kind, _), n in sorted(got.items()):
        if kind not in strata and kind != "para":
            strata[kind] = {"n": n}
    other_kinds = [
        k
        for pool_c in census.values()
        for k in pool_c["kinds"]
        if k not in ("para", "caption", "section_title")
    ]
    if not other_kinds:
        gaps.append(
            {
                "note": "no abstract/table_text/env_text chunks in pools — "
                "collect-if-present strata empty"
            }
        )

    meta = {
        "seed": args.seed,
        "created_at": datetime.now(UTC).isoformat(),
        "pools": census,
        "params": {
            "chunks": args.chunks,
            "papers": args.papers,
            "caption": args.caption,
            "section_title": args.section_title,
            "tertile_rule": "len(src)<=cuts[0]->0, <=cuts[1]->1, else 2 "
            "(rt1 pool-level distribution)",
        },
        "strata": strata,
        "papers_n": len({r["paper"] for r in rows}),
        "chunks_n": len(rows),
        "gaps": gaps,
    }
    return rows, meta


def print_dry(rows: list[dict], meta: dict) -> None:
    print(f"seed={meta['seed']} papers={meta['papers_n']} chunks={meta['chunks_n']}")
    for pool, c in meta["pools"].items():
        print(
            f"  pool {pool}: files={c['files']} papers={c['papers']} "
            f"usable={c['usable_chunks']} kinds={c['kinds']}"
        )
    print("strata:")
    for kind, s in meta["strata"].items():
        print(f"  {kind}: {s}")
    print(f"gaps: {meta['gaps']}")
    by_pool = collections.Counter(r["pool"] for r in rows)
    by_kind = collections.Counter(r["kind"] for r in rows)
    per_paper = collections.Counter(r["paper"] for r in rows)
    dist = collections.Counter(per_paper.values())
    print(f"by_pool={dict(by_pool)} by_kind={dict(by_kind)}")
    print(f"chunks/paper dist (n_chunks->n_papers): {sorted(dist.items())}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=20260918)
    ap.add_argument(
        "--papers", type=int, default=350, help="目标篇数（配额不足自动放宽）"
    )
    ap.add_argument("--chunks", type=int, default=1200, help="目标总块数")
    ap.add_argument("--caption", type=int, default=150, help="caption 保底")
    ap.add_argument("--section-title", type=int, default=150, help="section_title 保底")
    ap.add_argument(
        "--out", default=None, help="产出目录（写 sample.jsonl + sample_meta.json）"
    )
    ap.add_argument("--dry-run", action="store_true", help="只打印分层统计不写文件")
    args = ap.parse_args()

    rows, meta = build_sample(args)
    if args.dry_run:
        print_dry(rows, meta)
        return
    out_dir = (
        Path(args.out)
        if args.out
        else ROOT / "bench/results" / f"qualbase-{datetime.now(UTC).date()}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    sample = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    benchlib.atomic_write_text(out_dir / "sample.jsonl", sample)
    benchlib.atomic_write_text(
        out_dir / "sample_meta.json",
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
    )
    print_dry(rows, meta)
    print(f"-> {out_dir}/sample.jsonl + sample_meta.json")


if __name__ == "__main__":
    main()
