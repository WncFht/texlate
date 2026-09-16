# triage report — stagerun-loop1-2026-09-16

- 生成: 2026-09-16 08:36 UTC · 数据源: records/
- date=2026-09-16 · wall_s=4410864.8

## stage 通过率

| stage | arm | ok | total | rate | skip |
| --- | --- | --- | --- | --- | --- |
| compile | zh | 2290 | 5108 | 44.8% | 543 |
| fixloop | fix | 1100 | 1310 | 84.0% | 0 |
| ingest | - | 5059 | 5072 | 99.7% | 13 |
| parse | - | 4980 | 5059 | 98.4% | 75 |
| xlat | mock | 4957 | 5059 | 98.0% | 79 |
| xlat | real | 48 | 50 | 96.0% | 2 |

## fixloop

- rescue_rate: 1100/1310 = 84.0%
- top_unfixable:
  - `no_errors_no_pdf` ×15
  - `unfixable:syntax` ×12
  - `unfixable:missing_file:pst-node` ×11
  - `unfixable:other` ×10
  - `unfixable:illegal_unit` ×9
  - `unfixable:missing_file:jheppub.sty` ×9
  - `unfixable:missing_file:citesort.sty` ×7
  - `unfixable:missing_file:diagrams.sty` ×7
  - `unfixable:pdftex_prim:pdfcompresslevel` ×6
  - `unfixable:missing_file:axodraw.sty` ×5

## tickets (top 20/455)

| sig_id | stage | signature | count | fix_class | examples |
| --- | --- | --- | --- | --- | --- |
| compile-001 | compile | `clean` | 1998 | rule | 0707.0559, 0707.0583, 0707.1163… |
| compile-002 | compile | `missing_character` | 457 | rule | 0707.0271, 0707.0793, 0707.1871… |
| fixloop-003 | fixloop | `acceptable_pdf` | 448 | rule | 0806.2219, 1003.0159, 1206.1954… |
| compile-004 | compile | `inject_reject:latex209` | 414 | wontfix | 0707.2570, 0707.3474, 0707.3972… |
| compile-005 | compile | `warn:invalid_utf8` | 354 | rule | 0707.4363, 0806.2434, 0806.3306… |
| compile-006 | compile | `illegal_unit` | 312 | rule | 0707.0005, 0707.0351, 0707.0143… |
| compile-007 | compile | `undefined_cs` | 284 | rule | 0707.0167, 0707.1781, 0707.3928… |
| compile-008 | compile | `syntax` | 166 | rule | 0707.0382, 0707.1511, 0707.2951… |
| compile-009 | compile | `errors>3` | 140 | rule | 0707.0476, 0707.1255, 0707.1588… |
| compile-010 | compile | `other` | 131 | rule | 0707.3761, 0707.3763, 0806.1481… |
| fixloop-011 | fixloop | `best_effort_pdf` | 95 | rule | 0806.3115, 1206.0607, 1306.0550… |
| compile-012 | compile | `missing_file:aastex.cls` | 82 | shim_table | 0707.0255, 0707.1345, 0707.1778… |
| parse-013 | parse | `no_main_tex` | 75 | rule | 0707.1206, 0707.2108, 0806.0433… |
| compile-014 | compile | `missing_file:iopart.cls` | 44 | shim_table | 0707.0128, 0707.2152, 0707.3484… |
| compile-015 | compile | `missing_file:mn2e.cls` | 42 | shim_table | 0707.4614, 0806.2538, 0806.2841… |
| compile-016 | compile | `missing_file:aa.cls` | 33 | shim_table | 0707.2016, 0806.2574, 0806.2990… |
| fixloop-017 | fixloop | `acceptable_pdf:epsf.sty` | 28 | rule | 0806.0650, 0806.3004, 0806.1415… |
| compile-018 | compile | `missing_file:elsart.cls` | 25 | shim_table | 0707.2284, 0707.3701, 0707.4206… |
| compile-019 | compile | `missing_file:tcilatex.tex` | 23 | shim_table | 0707.0063, 0806.0300, 0806.1203… |
| compile-020 | compile | `no_pdf` | 23 | rule | 0707.1325, 0806.2073, 0806.3016… |
