# alignbench — B7 锚点保留基准

- date: 2026-09-16 21:26Z · wall 0.0s · 门槛 retention ≥ 0.95
- pairs: 5 (hyperref 3 · degraded 1 · low 1 · invalid 1 · error 0)
- retention: min 0.7142857142857143 · p50 1.0 · mean 0.9048
- chain w_ratio: min 0.8148 · p50 1.0
- **gates**: no_errors=✅ · retention≥0.95=❌ · degraded_ok=✅

## 逐对明细

| pair | kind | verdict | arm | zh_v | dests a→b | common | ret | Δp med | chain w |
|---|---|---|---|---|---|---|---|---|---|
| selftest/keep | selftest | ok | - | - | 7→7 | 7 | 1.000 | 0 | 1.000 |
| selftest/shift | selftest | ok | - | - | 7→7 | 7 | 1.000 | 1 | 1.000 |
| selftest/drop | selftest | low | - | - | 7→5 | 5 | 0.714 | 0 | 0.815 |
| selftest/degraded | selftest | degraded | - | - | 0→0 | 0 | n/a | None | None |
| selftest/corrupt | selftest | invalid(b) | - | - | - | - | - | - | - |

## 保留率不达标对（zh 编译完整性探针 + 编译 verdict 联判）

blame 分布: unknown×1

- `selftest/drop` ret=0.714 blame=unknown arm=None zh_v=None (pipe-xel=None pipe-fix=None) lost=['section.2', 'section.3']

## 丢锚点归因入口（→ fixtures B2 沉淀）

- `selftest/drop`: section.2, section.3

## 不可解析 PDF 对（编译段垃圾产物，B3/B5 已计 FAIL）

- `selftest/corrupt` side=b: PdfStreamError: Stream has ended unexpectedly

