# qualbench — 译文质量 LLM-judge

- judge_model: `mock-judge`（mock=True）
- source: state · seed=42 · papers=8 · judged=48 chunks
- started: 2026-09-16T05:47:10.183391+00:00

## 总分（model × judge）

| model × judge | n | mean | median | 分布 5→1 |
| --- | --- | --- | --- | --- |
| swe-2-medium × judge=mock-judge | 48 | 4.31 | 5 | 5:25 4:14 3:8 2:1 1:0 |

## flag 频率（全体 judged chunk）

- `untranslated_spans`: 9

## per-kind

| kind | n | mean | median | 分布 5→1 | flags |
| --- | --- | --- | --- | --- | --- |
| caption | 13 | 4.31 | 5 | 5:7 4:3 3:3 2:0 1:0 | untranslated_spans×3 |
| para | 22 | 4.05 | 4 | 5:8 4:8 3:5 2:1 1:0 | untranslated_spans×6 |
| section_title | 13 | 4.77 | 5 | 5:10 4:3 3:0 2:0 1:0 | — |

## per-paper

| paper | model | n | mean | 分布 5→1 | flags |
| --- | --- | --- | --- | --- | --- |
| 0707.3950 | swe-2-medium | 6 | 4.50 | 5:4 4:1 3:1 2:0 1:0 | untranslated_spans×1 |
| 0905.2486 | swe-2-medium | 6 | 4.33 | 5:3 4:2 3:1 2:0 1:0 | untranslated_spans×1 |
| 1003.1383 | swe-2-medium | 6 | 5.00 | 5:6 4:0 3:0 2:0 1:0 | — |
| 1003.1464 | swe-2-medium | 6 | 4.67 | 5:4 4:2 3:0 2:0 1:0 | — |
| 2009.03685 | swe-2-medium | 6 | 4.00 | 5:2 4:2 3:2 2:0 1:0 | untranslated_spans×2 |
| 2105.03740 | swe-2-medium | 6 | 3.83 | 5:1 4:3 3:2 2:0 1:0 | untranslated_spans×2 |
| 2405.08810 | swe-2-medium | 6 | 3.67 | 5:2 4:1 3:2 2:1 1:0 | untranslated_spans×3 |
| 2410.17902 | swe-2-medium | 6 | 4.50 | 5:3 4:3 3:0 2:0 1:0 | — |

## 最差 chunk（score 升序前 30）

| paper | chunk | kind | score | flags | note |
| --- | --- | --- | --- | --- | --- |
| 2405.08810 | 1:3 | para | 2 | untranslated_spans | mock-judge |
| 2009.03685 | 0:57 | para | 3 | untranslated_spans | mock-judge |
| 2105.03740 | 0:21 | caption | 3 | untranslated_spans | mock-judge |
| 2405.08810 | 3:7 | caption | 3 | untranslated_spans | mock-judge |
| 0905.2486 | 0:6 | para | 3 | untranslated_spans | mock-judge |
| 0707.3950 | 0:3 | para | 3 | untranslated_spans | mock-judge |
| 2009.03685 | 0:37 | para | 3 | untranslated_spans | mock-judge |
| 2405.08810 | 8:11 | caption | 3 | untranslated_spans | mock-judge |
| 2105.03740 | 0:26 | para | 3 | untranslated_spans | mock-judge |
