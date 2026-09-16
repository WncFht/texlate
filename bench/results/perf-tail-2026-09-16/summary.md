# perf-tail wave-2: latex 慢文件归因 + 算法修复

2026-09-16。目标：corpus_v3 上 `parse_file`（v2 Gullet+Segmenter 默认路径，`flatten=True`）的 >500ms 长尾。textutil.py 归属经 leader 授权扩入。

## 样本与方法

`sample.txt` = 前轮 parsebench `v2.wall_ms` top-40 + 固定种子 20260916 随机 160 篇 = 201 篇（有效 199）。`before.jsonl`/`after.jsonl` 同机逐文件 wall_ms（after 含全部 5 项修复）。Identity = `perf_tail_identity.py` 对 `res.vtex + repr(chunks) + sorted(ph_map) + repr(warnings) + repr(inputs)` 的 sha256；old tree = HEAD 版 segmenter/gullet/textutil 拷入 `/tmp/texlate_old`。

## 结果

199/201 ok：**total 51476 → 26723ms（51.9%），median 50.8 → 39.4ms，>500ms 20 → 11 篇，0 回退（>+20ms）**。Identity 201/201 digest 全等；`pytest -k 'latex or segmenter or argspec or textutil or encoding'` 359 passed；ruff check/format 净。

## 修复与归因

### 1. `_collect_group` 未闭合开括号墓标（`_ListSource._unmatched_open`）— segmenter.py

失败扫描原是 O(stream-tail)：每个未匹配 open 触发到底部的 drain 再全量 unread。2410.17998 上 22607 次调用中 145 次失败，贡献 **18.59M / 19.0M 次 _ListSource token 拉取（97.8%）**，`_collect_group` cumtime 11.15s / 总 14.0s（cProfile）。修复：EOF 失败把 opens 栈记入 `_unmatched_open`（键 `(pos, gen)`），命中即 `unread([open_t]); return None`——与 drain+全量回吐可观测等价。`_ListSource` token 列构造时固定（unread 只回放已见、skip_past 只删），未闭合判定单调永久；Gullet 流侧不可墓标（合成 rbrace、push_source 拼接、catcode 重切均可令 position-keyed 判定失真）且实测失败为 0，只挂 `_ListSource`。

归因：**2410.17998 2929 → ~1100ms**；失败重扫拉取 18.59M → 1.05M。

### 2. `live_srcs` 快照门：per-token dict 重建 → `(pop,push)` 事件钟 — gullet.py + segmenter.py

`scan()` 原对每 token 重建 `live_srcs` dict 再 diff（pdotaph2：986K 次重建）。Gullet 维护 `_pop_seq`/`_push_seq` 单调计数器（`read()` 弹栈、`\endinput` 弹栈、`push_source`、`unread` 合成源各 +1），scan 每 token 只比二元组。

### 3. `_cover_text`：`cover` + 所盖文本一步返回 — segmenter.py

`_rappend_tok`/`eol_par` 原 cover 后再 `vt.slice` 反查同段（bisect+join 逐 token，pdotaph2 815K 次）。`_cover_text(fid,end) -> (Span,str)` 直接取 `file_texts[fid][a:end]`；`end<=a` 返回零宽 Span+""（回放/乱序语义同前）。其余 ~20 处低频 ph 体站点（~24K 次）不动。

归因（#2+#3 合计）：pdotaph2 2258 → ~1850ms、breview → ~1050ms、2009.11053 698 → ~575ms。

### 4. `_slice_items`：bisect 窄化 + 前缀和提升 — segmenter.py

`_flush_run` 超大 run 切分后每段从 `acc=0` 全列重扫 → O(items × parts)。zwanenburg：281 次调用 8.9M 次 `len(it.surface)`。`_flush_run` 建一次 surface 前缀和 `bounds`（同时喂 `_split_bounds`），`_slice_items` 以 `min(bisect_right(bounds,lo)-1, bisect_left(bounds,lo))` / `bisect_left/right(bounds,hi)` 定窗——窗是命中项充要条件的严格超集，逐项条件原样；末段 `hi==end` 时上界取 `bisect_right` 收 `acc==hi==end` 零宽项。

归因：**zwanenburg 1390 → ~840ms**（本步 ~1129 → 833）。

### 5. 码点分类 bisect 化 — textutil.py（leader 授权扩归属）

非 UTF-8 blob 的 `sniff_tex_encoding` 对 ~10 个候选解码各跑一次全文 `_score_text`，逐字 `_char_class` 线性 `any()` 扫 9 个类区间 + `is_cjk_cp` 再扫 5 个 CJK 区间（breview：`_char_class` 976K 次调用、5.9M 次 `any()`，cProfile tottime ~3.5s）。修复：`_merge_ranges`/`_in_ranges`/`_class_lookup_table` 三个 helper——布尔表排序合并（相邻并入），命名表按 `_CLASS_RANGES` 先名 carve 成排序不相交 (lo,hi,name) 面，重叠子段归先名（首中语义对任意输入逐点等价）；`is_cjk_cp`/`_char_class`/`_cjk_decode_score` 的 kana 检查全改 bisect。19,913 码点边界+随机抽样与朴素实现零分歧；`tests/test_textutil_encoding.py` 新增 `test_is_cjk_cp_boundaries`/`test_char_class_boundaries` 钉全边界（含 0x3007 双覆盖、0x3400 接界、相邻类区接界）。

归因：**全部 decode 主导文件 -60~-77%**——2403.15096 4583→1330、doctor04 3107→1233、SDrel 2310→696、ArticleSarahLemler 2238→511、1206.2072 2127→624、khiTxenon 1892→545、NS_1loop 1471→395、breviewTBLG 1460→459、0806.1079 1295→365、text_to_arxiv 877→254、0707.0005 774→231。

## 剩余长尾

11 篇 >500ms：pdotaph2 1849、2403.15096 1330、doctor04 1233、2410.17998 1100、breview 1049、zwanenburg 841、SDrel 696、1206.2072 624、2009.11053 575、khiTxenon 545、ArticleSarahLemler 511。pdotaph2/2410.17998/breview/2009.11053 为线性 ~1µs/tok 的逐 token cover/dispatch 管线（mouth.next/_rappend_tok/cover/_cover_text 平铺）；SDrel/ArticleSarahLemler 等余量在 `_decode_mixed`/多候选 decode+评分本身（每候选一次全量 `blob.decode`+`_score_text`，语义上不可跳）。

## 产物

- `sample.txt`、`before.jsonl`、`after.jsonl`、`identity-old.jsonl`、`identity-new.jsonl`、`prof-*.txt` ×5（修复前 top-5 cProfile）
- 探针：`bench/py/scratch/perf_tail.py`（sample/run/profile）、`perf_tail_identity.py`（A/B digest）
