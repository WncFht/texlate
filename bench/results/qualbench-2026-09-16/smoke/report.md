# qualbench — 译文质量 LLM-judge

- judge_model: `swe-2-medium`（mock=False）
- source: state · seed=42 · papers=8 · judged=3 chunks
- started: 2026-09-16T05:47:15.570871+00:00

## 总分（model × judge）

| model × judge | n | mean | median | 分布 5→1 |
| --- | --- | --- | --- | --- |
| swe-2-medium × judge=swe-2-medium | 3 | 4.67 | 5 | 5:2 4:1 3:0 2:0 1:0 |

## flag 频率（全体 judged chunk）

- （无 flag）

## per-kind

| kind | n | mean | median | 分布 5→1 | flags |
| --- | --- | --- | --- | --- | --- |
| caption | 2 | 5.00 | 5 | 5:2 4:0 3:0 2:0 1:0 | — |
| para | 1 | 4.00 | 4 | 5:0 4:1 3:0 2:0 1:0 | — |

## per-paper

| paper | model | n | mean | 分布 5→1 | flags |
| --- | --- | --- | --- | --- | --- |
| 0707.3950 | swe-2-medium | 1 | 4.00 | 5:0 4:1 3:0 2:0 1:0 | — |
| 0905.2486 | swe-2-medium | 1 | 5.00 | 5:1 4:0 3:0 2:0 1:0 | — |
| 1003.1383 | swe-2-medium | 1 | 5.00 | 5:1 4:0 3:0 2:0 1:0 | — |

## 最差 chunk（score 升序前 30）

| paper | chunk | kind | score | flags | note |
| --- | --- | --- | --- | --- | --- |
