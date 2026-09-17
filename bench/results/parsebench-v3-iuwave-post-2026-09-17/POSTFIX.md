# parsebench-v3-iuwave-post — POST-FIX gate for illegal_unit wave

Captured with the illegal_unit wave fix in the working tree (segmenter tail-scan
coverage: comma decimals, unbounded unit keywords, newline/comment gaps, count
registers, `\relax` terminator; tables.py count family + hoffset/voffset;
pending.py group-internal spec args; argspec.json multirow/adjustwidth*/hangparas/
genfrac) plus the api.py envflag fix.

## diff vs parsebench-v3-iuwave-base-2026-09-17

- parse ok: 1955/1955 (unchanged), errors 0
- identity: strict 1955 (unchanged — zero flips)
- leak: 57/136052 = 0.04%, hits={'dollar': 57} (unchanged — illegal_unit is a
  stagerun signature, not a parsebench cell metric; dollar pool untouched)
- warnings/funnel/flatten metrics: identical to baseline (diff of metric lines
  empty)

wall 890.6s vs base 452.7s — slowdown is CPU contention (C-bucket rerun wave +
full pytest in flight), not a code regression.

Verdict: **zero regression** — safe to commit.
