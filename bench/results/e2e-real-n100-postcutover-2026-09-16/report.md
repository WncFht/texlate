# triage report — e2e-real-n100-postcutover-2026-09-16

- 生成: 2026-09-16 04:17 UTC · 数据源: legacy results.json
- date=2026-09-16 · wall_s=156.9
- 回归: rate_drop×0 · pipeline_introduced×8 (0707.3950, 0905.4907, 1012.1321, 1206.1808, 1511.02908…)

## stage 通过率

| stage | arm | ok | total | rate | skip |
| --- | --- | --- | --- | --- | --- |
| compile | base | 8 | 56 | 14.3% | 0 |
| compile | zh | 26 | 82 | 31.7% | 1 |
| fixloop | fix | 27 | 37 | 73.0% | 0 |

## fixloop

- rescue_rate: 27/37 = 73.0%
- top_unfixable:
  - `unfixable:latex209` ×3
  - `unfixable:missing_file:elsart.cls` ×1
  - `unfixable:missing_file:aa.cls` ×1
  - `unfixable:missing_file:aipcheck.tex` ×1
  - `unfixable:missing_file:iopart12.clo` ×1
  - `unfixable:missing_file:aastex63.cls` ×1
  - `unfixable:missing_file:binhex.tex` ×1
  - `unfixable:other` ×1

## tickets (top 20/36)

| sig_id | stage | signature | count | fix_class | examples |
| --- | --- | --- | --- | --- | --- |
| compile-001 | compile | `missing_file:revtex4.cls` | 34 | rule | 0707.4363, 0707.4577, 0806.0982… |
| compile-002 | compile | `missing_file:epsf.sty` | 8 | rule | 1706.07924, 1803.08927, 1803.09046… |
| compile-003 | compile | `undefined_cs` | 8 | rule | 1012.1321, 1206.1808, 1511.02908… |
| compile-004 | compile | `warn:invalid_utf8` | 7 | rule | 0806.1079, 1608.06769, 2009.11013… |
| compile-005 | compile | `missing_file:revtex4-1.cls` | 4 | rule | 1404.5720, 1404.6133 |
| compile-006 | compile | `other` | 3 | rule | 1206.5628, 2403.15119 |
| compile-007 | compile | `syntax` | 3 | rule | 0905.4907, 1012.5842, 2403.15096 |
| fixloop-008 | fixloop | `unfixable:latex209` | 3 | wontfix | 1803.08927, 1803.09046, 2203.04385 |
| compile-009 | compile | `missing_character:x1` | 2 | rule | 1003.1464, 1608.02516 |
| compile-010 | compile | `missing_file` | 2 | rule | 2308.12712 |
| compile-011 | compile | `missing_file:IEEEtran.cls` | 2 | rule | 2410.17967 |
| compile-012 | compile | `missing_file:SIunits.sty` | 2 | rule | 2105.11495 |
| compile-013 | compile | `missing_file:aa.cls` | 2 | rule | 0905.4439 |
| compile-014 | compile | `missing_file:aastex63.cls` | 2 | shim_table | 2105.03750 |
| compile-015 | compile | `missing_file:aipcheck.tex` | 2 | rule | 1306.2177 |
| compile-016 | compile | `missing_file:aps4-2.rtx` | 2 | rule | 2308.12597 |
| compile-017 | compile | `missing_file:elsart.cls` | 2 | shim_table | 0707.4465 |
| compile-018 | compile | `missing_file:extarrows.sty` | 2 | rule | 1404.5834 |
| compile-019 | compile | `missing_file:iopart12.clo` | 2 | rule | 1306.5813 |
| compile-020 | compile | `missing_file:mnras.cls` | 2 | rule | 2211.04574 |
