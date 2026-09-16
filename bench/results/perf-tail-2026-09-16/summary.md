# perf-tail wave-2: latex 慢文件归因 + 算法修复

2026-09-16。目标：corpus_v3 上 `parse_file`（v2 Gullet+Segmenter 默认路径，`flatten=True`）的 >500ms 长尾。

## 样本与方法

`sample.txt` = 前轮 parsebench `v2.wall_ms` top-40 + 固定种子 20260916 随机 160 篇 = 201 篇（有效 199）。`before.jsonl`/`after.jsonl` 同机逐文件 wall_ms。Identity = `perf_tail_identity.py` 对 `res.vtex + repr(chunks) + sorted(ph_map) + repr(warnings) + repr(inputs)` 的 sha256；old tree = HEAD 版 segmenter/gullet 拷入 `/tmp/texlate_old`。

## 结果

199/201 ok：total 51476 → 43385ms（84.3%），median 50.8 → 38.2ms，>500ms 20 → 18 篇，0 回退。Identity 201/201 全等；pytest 子集 338 passed。

## 修复与归因

1. `_collect_group` 未闭合开括号墓标（`_ListSource._unmatched_open`）：失败 drain O(tail) → O(1) 直答。证据 22607 调用/145 失败/18.59M 拉取（97.8%）。归因 2410.17998 2929→1071ms。
2. `live_srcs` `(pop,push)` 事件钟门（gullet 计数器）：省每 token dict 重建（pdotaph2 986K 次）。
3. `_cover_text` 融合：省逐 token `vt.slice` 反查（pdotaph2 815K 次）。#2+#3：pdotaph2 2258→1831、breview →1932、2009.11053 →531。
4. `_slice_items` bisect 窄化（bounds 前缀和提升）：O(items×parts)→O(items+parts·log)。zwanenburg 1390→833ms。

## 剩余长尾

13/18 篇 decode 主导（textutil `sniff_tex_encoding`/`is_cjk_cp` linear any()，建议 bisect ~10x，出 ownership）；scan 余量为线性 ~1µs/tok 管线。
