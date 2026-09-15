# alignbench — B7 锚点保留基准

- date: 2026-09-15 12:25Z · wall 0.1s · 门槛 retention ≥ 0.95
- pairs: 7 (hyperref 3 · degraded 3 · low 0 · error 1)
- retention: min 1.0 · p50 1.0 · mean 1.0
- chain w_ratio: min 0.967 · p50 1.0
- **gates**: no_errors=❌ · retention≥0.95=✅ · degraded_ok=✅

## 逐对明细

| pair | kind | verdict | dests a→b | common | ret | Δp med | chain w |
|---|---|---|---|---|---|---|---|
| 0707.3950 | e2ereal-r2 | degraded | 0→0 | 0 | n/a | None | None |
| 0707.4363 | e2ereal-r2 | degraded | 0→0 | 0 | n/a | None | None |
| 1003.1464 | e2ereal-r2 | degraded | 0→0 | 0 | n/a | None | None |
| 1907.10324 | e2ereal-r2 | ok | 12→12 | 12 | 1.000 | -1 | 1.000 |
| 2211.13013 | e2ereal-r2 | ERROR | - | - | - | - | - |
| 2403.15096 | e2ereal-r2 | ok | 231→231 | 231 | 1.000 | 6 | 1.000 |
| 2410.06025 | e2ereal-r2 | ok | 181→181 | 181 | 1.000 | 0 | 0.967 |

## 异常对

- `2211.13013`: PdfStreamError: Stream has ended unexpectedly

