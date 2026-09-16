# triage report — stagerun-smoke-2026-09-16

- 生成: 2026-09-16 05:29 UTC · 数据源: records/
- date=2026-09-16 · wall_s=13.2
- 回归: rate_drop×1 · pipeline_introduced×2

## stage 通过率

| stage | arm | ok | total | rate | skip |
| --- | --- | --- | --- | --- | --- |
| compile | base | 3 | 3 | 100.0% | 0 |
| compile | zh | 1 | 3 | 33.3% | 0 |
| fixloop | fix | 0 | 2 | 0.0% | 0 |
| ingest | - | 3 | 3 | 100.0% | 0 |
| parse | - | 3 | 3 | 100.0% | 0 |
| xlat | mock | 3 | 3 | 100.0% | 0 |

## fixloop

- rescue_rate: 2/2 = 100.0%

## tickets (top 4/4)

| sig_id | stage | signature | count | fix_class | examples |
| --- | --- | --- | --- | --- | --- |
| compile-001 | compile | `clean` | 4 | rule | 1003.4522, 0707.3950, 2203.13039 |
| compile-002 | compile | `missing_character` | 2 | rule | 0707.3950, 2203.13039 |
| fixloop-003 | fixloop | `acceptable_pdf` | 1 | rule | 2203.13039 |
| fixloop-004 | fixloop | `best_effort_pdf` | 1 | rule | 0707.3950 |
