# qualbench — 译文质量 LLM-judge

- judge_model: `mock-judge`（mock=True）
- source: corpus · seed=42 · papers=3 · judged=12 chunks
- started: 2026-09-16T05:47:10.509969+00:00

## 总分（model × judge）

| model × judge | n | mean | median | 分布 5→1 |
| --- | --- | --- | --- | --- |
| mock-translator × judge=mock-judge | 12 | 4.58 | 5 | 5:7 4:5 3:0 2:0 1:0 |

## flag 频率（全体 judged chunk）

- （无 flag）

## per-kind

| kind | n | mean | median | 分布 5→1 | flags |
| --- | --- | --- | --- | --- | --- |
| para | 12 | 4.58 | 5 | 5:7 4:5 3:0 2:0 1:0 | — |

## per-paper

| paper | model | n | mean | 分布 5→1 | flags |
| --- | --- | --- | --- | --- | --- |
| 0905.0902 | mock-translator | 4 | 4.25 | 5:1 4:3 3:0 2:0 1:0 | — |
| 1306.0141 | mock-translator | 4 | 5.00 | 5:4 4:0 3:0 2:0 1:0 | — |
| 2308.00073 | mock-translator | 4 | 4.50 | 5:2 4:2 3:0 2:0 1:0 | — |

## 最差 chunk（score 升序前 30）

| paper | chunk | kind | score | flags | note |
| --- | --- | --- | --- | --- | --- |
