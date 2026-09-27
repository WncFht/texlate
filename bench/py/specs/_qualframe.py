"""_qualframe — qualbench frame bakers (the frozen selection layer).

A qualbench frame is a tracked jsonl under ``bench/nominations/`` — one
PAIR row per line; every row becomes one judge cell at plan time (see
``specs/qualbench.py`` for the row->item transform). Row schema — all
keys required::

    {"paper":      <canon id>,            # cell idc
     "chunk_id":   "fi:bi",               # variant component, never '|'
     "kind":       "para|caption|section_title|abstract|table_text|env_text",
     "model":      "<judged translator>", # cell arm
     "src":        "<en source chunk>",
     "zh":         "<produced translation>",
     "src_status": "ok|partial",          # the translation's own status
     "up":         "<provenance tag>",    # mock-corpus / vlt-… / sample file
     "judge":      "mock-judge|swe-2-max|swe-2-high"}

Bakers:

- ``bake_mock`` — lake corpus cells → blank-line chunks → deterministic
  ``_mock_translate`` (placeholders/control sequences preserved, prose
  runs → fixed zh). ``judge="mock-judge"`` gives the zero-gateway
  self-check arm; ``judge="swe-2-max"`` over the same deterministic
  pairs is the paid-lane smoke (real wire, deterministic content).
- ``bake_manifest`` — a frozen sample jsonl (qualsample-style rows with
  paper/chunk_id/kind/model/src|source/zh|translation) → frame rows
  verbatim; ``--judge`` assigns the judge column.
- ``bake_state`` — ``xlat-state/{arm}/state.json`` trees (stagerun
  ``work/{id}/`` layout and bare ``{id}/`` e2e_real layout both
  sniffed) → results[] last-row-wins → ok/partial ∧ zh≠src → rows with
  model=meta.model (fallback: arm), judge=routed at bake time. This is
  the live lane: ``--state-root`` pointing at replay/backup work trees
  bakes real-pipeline pairs today; once soak/e2e_real harvests vault
  ``state`` assets the same builder reads them via ``vault/state/``
  (pass the vault root — leaf dirs have the same ``{key}/state.json``
  tail shape).

Baking is deterministic under (inputs, seed): same roots + same knobs →
same rows → same cell keys. Re-baking a DIFFERENT set must land a NEW
frame file (bump the tag), never rewrite a frozen one.

    uv run python bench/py/specs/_qualframe.py mock \
        --papers 6 --per-paper 8 --judge mock-judge \
        --out bench/nominations/qualframe-mock-v1.jsonl
    uv run python bench/py/specs/_qualframe.py state \
        --state-root ~/.local/share/texlate-bench/backup/phase0-20260922 \
        --papers 3 --per-paper 8 --judge swe-2-max \
        --out bench/nominations/qualframe-live-v1.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "bench" / "py"))


def _row(
    paper: str,
    chunk_id: str,
    kind: str,
    model: str,
    src: str,
    zh: str,
    src_status: str,
    up: str,
    judge: str,
) -> dict:
    """Canonical frame row — the schema the spec's row->item transform
    consumes. ``sha`` is the row fingerprint input (fp_input)."""
    r = {
        "paper": str(paper),
        "chunk_id": str(chunk_id),
        "kind": str(kind),
        "model": str(model),
        "src": src,
        "zh": zh,
        "src_status": str(src_status),
        "up": str(up),
        "judge": str(judge),
    }
    r["sha"] = hashlib.sha256(
        json.dumps(r, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return r


# ---------------------------------------------------------------- mock corpus
_MOCK_ZH = "这是译文"
_MOCK_TOKEN_RX = re.compile(
    r"\[\[[A-Z_]+_\d+\]\]|\[\[[A-Z][A-Z_]*\]\]|\\[a-zA-Z@]+\*?|\\(?!\[\[).|[][(){}|~$&]"
)
_PROSE_RUN_RX = re.compile(r"[a-zA-Z][^\n]*[a-zA-Z]|[a-zA-Z]")
_SKIP_BLOCK_RX = re.compile(
    r"\\documentclass|\\usepackage|\\begin\{document\}|\\bibliography\{|"
    r"\\begin\{(?:verbatim|lstlisting|minted)"
)
_ASCII_WORDS_RX = re.compile(r"[A-Za-z]{2,}")


def _mock_translate(text: str) -> str:
    """Deterministic mock translation: placeholders/control sequences and
    brackets kept in place, prose runs -> the fixed zh string."""
    out: list[str] = []
    pos = 0
    for m in _MOCK_TOKEN_RX.finditer(text):
        out.append(_PROSE_RUN_RX.sub(_MOCK_ZH, text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_PROSE_RUN_RX.sub(_MOCK_ZH, text[pos:]))
    return "".join(out)


def _chunk_blocks(
    tex_root: Path, *, min_chars: int, max_chars: int, rng: random.Random
) -> list[tuple[str, str]]:
    """extracted/*.tex → [(fi:bi, block)] — verbatim old-driver rules:
    blank-line split, strip, chars window, ≥3 ASCII words, no preamble/
    bibliography/verbatim blocks."""
    blocks: list[tuple[str, str]] = []
    for fi, f in enumerate(sorted(tex_root.rglob("*.tex"))):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for bi, raw_blk in enumerate(re.split(r"\n\s*\n", text)):
            blk = raw_blk.strip()
            if not (min_chars <= len(blk) <= max_chars):
                continue
            if len(_ASCII_WORDS_RX.findall(blk)) < 3:
                continue
            if _SKIP_BLOCK_RX.search(blk):
                continue
            blocks.append((f"{fi}:{bi}", blk))
    rng.shuffle(blocks)
    return blocks


def bake_mock(
    *,
    papers: int,
    per_paper: int,
    seed: int,
    judge: str,
    min_chars: int,
    max_chars: int,
    lake_source: str = "arxiv",
) -> tuple[list[dict], dict]:
    """Lake corpus cells → mock-translated pair rows."""
    from kernel import lake

    rng = random.Random(seed)
    cat = lake.LakeCatalog.load()
    cands = sorted(
        idc for idc in cat.rows() if lake.is_complete(idc, source=lake_source)
    )
    rng.shuffle(cands)
    picked = cands[:papers] if papers else cands
    picked.sort()

    rows: list[dict] = []
    meta_papers: list[dict] = []
    for idc in picked:
        cell = lake.cell_dir(idc, source=lake_source)
        blocks = _chunk_blocks(
            cell / "extracted", min_chars=min_chars, max_chars=max_chars, rng=rng
        )
        take = blocks[:per_paper] if per_paper else blocks
        for cid, src in take:
            rows.append(
                _row(
                    idc,
                    cid,
                    "para",
                    "mock-translator",
                    src,
                    _mock_translate(src),
                    "ok",
                    "mock-corpus",
                    judge,
                )
            )
        meta_papers.append({"id": idc, "n_pairs": len(take), "n_blocks": len(blocks)})
    return rows, {"papers": meta_papers, "pool": len(cands)}


# ---------------------------------------------------------------- manifest
def bake_manifest(
    *, manifest: Path, judge: str, up: str | None = None
) -> tuple[list[dict], dict]:
    """Frozen sample jsonl → frame rows (qualsample field aliases)."""
    rows: list[dict] = []
    tag = up or manifest.stem
    n = 0
    for raw_ln in manifest.read_text(encoding="utf-8").splitlines():
        line = raw_ln.strip()
        if not line:
            continue
        r = json.loads(line)
        rows.append(
            _row(
                r["paper"],
                r["chunk_id"],
                r.get("kind") or "para",
                r.get("model") or "?",
                r.get("src") or r.get("source") or "",
                r.get("zh") or r.get("translation") or "",
                r.get("status") or "ok",
                tag,
                judge,
            )
        )
        n += 1
    return rows, {"manifest": str(manifest), "n_rows": n}


# ---------------------------------------------------------------- state pool
def _state_files(roots: list[Path]) -> list[tuple[Path, str, str]]:
    """``--state-root`` 下递归找 state.json → [(path, paper, arm)]。

    Two layouts (verbatim from the old driver): a path containing
    ``xlat-state/{arm}`` puts the paper one level above and the arm one
    level below; otherwise the state.json's parent dir IS the paper dir
    (e2e_real ``_xlat_state/{safe_id}/`` and vault ``state/{safe}/{key}/``
    leaf shapes — the leaf key carries arm[@variant]).
    """
    from kernel import idnorm

    out: list[tuple[Path, str, str]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("state.json")):
            try:
                parts = p.relative_to(root).parts
            except ValueError:
                parts = p.parts
            paper, arm = "", ""
            if "xlat-state" in parts:
                i = parts.index("xlat-state")
                paper = parts[i - 1] if i else p.parent.parent.name
                arm = parts[i + 1] if i + 1 < len(parts) - 1 else ""
            else:
                paper = (
                    p.parent.parent.name if p.parent.name == "state" else p.parent.name
                )
            res = idnorm.canon_id(paper)
            paper = res.idc if res.ok and res.idc else paper
            out.append((p, paper, arm))
    return out


def bake_state(
    *,
    roots: list[Path],
    papers: int,
    per_paper: int,
    seed: int,
    judge: str,
    min_chars: int,
    max_chars: int,
    kinds: set[str] | None = None,
    arms: set[str] | None = None,
    up: str = "state-pool",
) -> tuple[list[dict], dict]:
    """state.json trees → pair rows; judge routed per pair at bake time
    (route_judge semantics — the preferred judge may yield to the pool
    when banned by the pair's own model).

    ``arms`` filters the ``xlat-state/{arm}`` arm column *before* the
    papers cap — mock/real trees interleave under one state root, and
    judging mock translations with a real judge is wasted spend."""
    from specs.qualbench import Pair, route_judge

    rng = random.Random(seed)
    entries = _state_files(roots)
    if arms:
        entries = [e for e in entries if e[2] in arms]
    rng.shuffle(entries)
    entries = entries[:papers] if papers else entries
    entries.sort(key=lambda e: e[1])

    rows: list[dict] = []
    meta_papers: list[dict] = []
    n_no_judge = 0
    for path, paper, arm in entries:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        model = str((data.get("meta") or {}).get("model") or arm or "?")
        last: dict[str, dict] = {}
        for r in data.get("results") or []:
            last[str(r.get("chunk_id"))] = r  # 末行胜
        n_dead = 0
        cands: dict[str, list[dict]] = {}
        for r in last.values():
            zh = str(r.get("translation") or "")
            src = str(r.get("source") or "")
            status = str(r.get("status") or "")
            if status not in ("ok", "partial") or zh == src:
                n_dead += 1
                continue
            kind = str(r.get("kind") or "para")
            if kinds and kind not in kinds:
                continue
            if not (min_chars <= len(src) <= max_chars):
                continue
            cands.setdefault(kind, []).append(r)
        picked: list[dict] = []
        buckets = list(cands.values())
        for b in buckets:
            rng.shuffle(b)
        while sum(len(b) for b in buckets) and (
            not per_paper or len(picked) < per_paper
        ):
            progressed = False
            for b in buckets:
                if b and (not per_paper or len(picked) < per_paper):
                    picked.append(b.pop())
                    progressed = True
            if not progressed:
                break
        for r in picked:
            src = str(r.get("source") or "")
            zh = str(r.get("translation") or "")
            jm = route_judge(
                Pair(paper=paper, chunk_id="", kind="", model=model, src="", zh=""),
                judge,
            )
            if jm is None:
                n_no_judge += 1
                continue
            rows.append(
                _row(
                    paper,
                    str(r.get("chunk_id")),
                    str(r.get("kind") or "para"),
                    model,
                    src,
                    zh,
                    str(r.get("status") or "ok"),
                    up,
                    jm,
                )
            )
        meta_papers.append(
            {
                "id": paper,
                "model": model,
                "arm": arm,
                "n_pairs": len(picked),
                "n_unjudged": n_dead,
                "state": str(path),
            }
        )
    meta = {"papers": meta_papers}
    if n_no_judge:
        meta["n_no_eligible_judge"] = n_no_judge
    return rows, meta


# ---------------------------------------------------------------- bake CLI
def _write(rows: list[dict], meta: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    side = out.with_suffix(".meta.json")
    side.write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} rows -> {out} (meta -> {side})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _common(p, judge_default):
        p.add_argument("--papers", type=int, default=0)
        p.add_argument("--per-paper", type=int, default=12)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--judge", default=judge_default)
        p.add_argument("--min-chars", type=int, default=8)
        p.add_argument("--max-chars", type=int, default=20000)
        p.add_argument("--out", required=True)

    p_mock = sub.add_parser("mock", help="lake cells + deterministic mock zh")
    _common(p_mock, "mock-judge")
    p_mock.add_argument("--lake-source", default="arxiv")

    p_man = sub.add_parser("manifest", help="frozen sample jsonl -> rows")
    p_man.add_argument("--manifest", required=True)
    p_man.add_argument("--judge", default="swe-2-max")
    p_man.add_argument("--up", default=None)
    p_man.add_argument("--out", required=True)

    p_st = sub.add_parser("state", help="xlat state.json trees -> rows")
    _common(p_st, "swe-2-max")
    p_st.add_argument("--state-root", action="append", required=True)
    p_st.add_argument("--kinds", default=None)
    p_st.add_argument(
        "--arms", default=None, help="csv arm filter (e.g. real) — before --papers cap"
    )
    p_st.add_argument("--up", default="state-pool")

    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.cmd == "mock":
        rows, meta = bake_mock(
            papers=args.papers,
            per_paper=args.per_paper,
            seed=args.seed,
            judge=args.judge,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
            lake_source=args.lake_source,
        )
    elif args.cmd == "manifest":
        rows, meta = bake_manifest(
            manifest=Path(args.manifest), judge=args.judge, up=args.up
        )
    else:
        kinds = (
            {k.strip() for k in args.kinds.split(",") if k.strip()}
            if args.kinds
            else None
        )
        arms = (
            {a.strip() for a in args.arms.split(",") if a.strip()}
            if args.arms
            else None
        )
        rows, meta = bake_state(
            roots=[Path(r) for r in args.state_root],
            papers=args.papers,
            per_paper=args.per_paper,
            seed=args.seed,
            judge=args.judge,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
            kinds=kinds,
            arms=arms,
            up=args.up,
        )
    meta["cmd"] = args.cmd
    meta["judge"] = args.judge
    meta["seed"] = getattr(args, "seed", None)
    _write(rows, meta, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
