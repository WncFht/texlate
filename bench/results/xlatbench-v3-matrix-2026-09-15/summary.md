# xlatbench corpus_v3 放大矩阵 — 2026-09-15

`--docs 60 --per-kind 8 --runs 2`，37 样例/轮（33 real + S1–S4），4 免费模型。

| model | hard_ok | ph_miss | ph_inv | cs_drop | ord_soft | lat p50/p95 |
|---|---|---|---|---|---|---|
| swe-2-high | 74/74 100% | 0 | 0 | 0 | 20 | 10.3/20.5s |
| swe-2-medium | 72/74 97% | 0 | 0 | 2 | 17 | 6.1/12.3s |
| glm-5-2 | 71/74 96% | 0 | 0 | 2 | 19 | 4.7/8.4s |
| swe-1-7-medium | 71/74 96% | 0 | 0 | 3 | 14 | 3.5/13.0s |

## 读法

- **296 调用 ph 零丢零造**——占位符契约全模型守住；区分度全在 cs_dropped。
- S1-bibitem-lead 双轮连抓 glm-5-2 / swe-1-7-medium：`et al.\ ` 的 `\ ` 控制空格
  被译文吞掉（cs_dropped）。fixture 化压力样例按设计命中；swe-2 系全过。
- glm-5-2 另贡献一例 `\em自发`——`\`+中文熔成未定义 cs，validator macro 规则抓到。
- swe-1-7-medium reasoning p95 10937ch 远超同侪——花最多 reasoning 仍掉 cs。
- 排名与 E22 重判口径一致（swe-2-high 顶、glm 底），corpus_v3 抽样下绝对值更高。
