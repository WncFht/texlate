# parsebench-v3-iuwave-base — PRE-FIX baseline for illegal_unit wave

Captured before the illegal_unit wave fix (segmenter/tables.py + _common.py
coverage fixes, ~126 cells) lands, so the post-fix run can be diffed against it.

## invocation

```
uv run python bench/py/parsebench.py --corpus bench/corpus_v3 \
  --out bench/results/parsebench-v3-iuwave-base-2026-09-17/ \
  > bench/results/parsebench-v3-iuwave-base-2026-09-17.run.log 2>&1
```

Same command shape as `parsebench-v3-nkind-2026-09-17/` (full corpus_v3
manifest, 1000 papers / 1955 files, default flags, no --v2 arm).

## environment

- git HEAD: `1209a364083af9876969c2dbb1210b0ebd337d33` (master, dirty tree —
  concurrent wave work in flight; baseline reflects working-tree state)
- date: 2026-09-17
- runner: `uv run` (.venv, product `texlate.latex` default path = v2
  Gullet+Segmenter)

## results

- wall: **452.7s** (nkind reference: 415.5s)
- parse ok: **1955/1955** (100.0%), errors 0, measure_errors 0
- identity: strict **1955** / normalized 0 / diverged 0 — no flips
- leak: **57/136052** chunks = 0.04%, hits={'dollar': 57}
- fake-translation: dead CHUNK ph 0 / dead protect ph 0 / orphan chunks 0 /
  bug1 ph-tail 0
- scan/validate warnings: unclosed_env 79, stray_end 69, def_parse_fail 295,
  missing_input 159, unpaired_dollar 172, debt_repair 4, env_mismatch 1
- flatten coverage: 1838 reached / 107 orphan tex / 10 rootless (94.5%)

Numbers are identical to `parsebench-v3-nkind-2026-09-17/` (same HEAD-era
code), confirming reproducibility of the 57-leak / 100%-strict baseline.

## pytest gate

```
uv run pytest tests/test_machinery_audit.py tests/test_argspec_dispatch.py -x -q
→ 50 passed, 2 warnings in 0.19s
```

## artifacts

- `files.jsonl` — per-file records (1955 rows)
- `papers.json` — per-paper records (1000 papers)
- `summary.md` — aggregate report with funnel/gates/statistics
- `../parsebench-v3-iuwave-base-2026-09-17.run.log` — stdout log
