# repro-0806-2026-09-16：0806.3472 唯一 pipe<base 退化归因

> modec-v3 随机 50 篇里唯一「pipeline 引入」的退化（`run-before/matrix.md`：base-xel clean / pipe-xel partial）。归因结论：**不是单点 bug，是 segmenter 展开组 surface 三缺陷叠加**——全部以 20 行最小复现钉死，补丁经属主 texlate-3f 采纳落地（`90aa823`，语义等价逐 hunk 核对过），回归 `tests/test_segmenter_unpaired_0806.py` 7/7 绿。

## 最小复现（`repro.tex`，20 行）

`\phantomsubsection` 宏同时踩中三个缺陷：体内 `{\bf #1.}` 展开组、`\vspace{2mm}` 结构尾参、文末 `$$...$$` display-math + picture 环境内嵌 `$x$/$y$`。

## 三缺陷机制链

### A — 展开组 detokenize 空格缺失（`\bfKostant` 融合）

`{\bf X}` 经宏展开后控制词 token 与字母 token 之间**无 gap 字节可恢复**（token `pos` 全指宏调用点，`_gap_surface` 只救 gen=0）。不补空格则 surface 渲染成 `\bfKostant`——未定义控制词；更糟的是 mock/真翻译把融合词当 `\cs` 整保留 → "Kostant" 这个词**逃逸翻译**。identity 重建照常（字节不丢），surface 层已坏。

修法（HEAD `_cat_surf`，segmenter.py:803 ≡ 补丁 `_SurfCat`）：`\`-引导且字母结尾的元素（控制词渲染）后随字母开头元素时自动插 `" "`——TeX 控制词吞空格的 detokenize 对价；ph 串 `[[X_n]]` 非字母开头恒不触发。

### B — 组内 BOUNDARY_TAIL 缺失（`\vspace{2这是译文}`）

顶层 `_handle_boundary` 用 `BOUNDARY_TAIL` argspec 把 `\vspace{2mm}` 结构参消费进 LITERAL；`_group_surface` 无对应分支 → `{2mm}` 逐字符落 chunk surface → 翻译 `mm` → `\vspace{2这是译文}` → 编译 `Illegal unit of measure`（0806.3472 主错因）。

修法（HEAD `_group_surface` 内 `BOUNDARY_NAMES` 分支 ~:1242 ≡ 补丁 hunk-4）：`BOUNDARY_TAIL` spec 数 m-参 → `_grp_call_end` 整调用保护进 `[[CMD]]` ph。已知局限：`_grp_call_end` 只识 `*→[o]→{m}` 固定序，`newcounter{m,o}`/`\cmidrule` 的 `d()` 尾参会漏——组内场景稀有，接受。

### C — 未配对 `$$` EOF 级联（`$\omega$` 静默蒸发）

`_on_math` unpaired 分支丢 `nxt`（`$$` 第二枚 `$` 已 read 出流）→ surface 剩单 `$`（`Missing $`/`Display math should end with $$`）；且 `$$` 体 raw-read 扫描耗尽 Mouth 弹栈后，`unread` 只能建 file_id<0 合成源——主循环 pop-栈尾扫抢先整盖 `[cons,EOF)`，回放 token 全零宽 vspan → `$\omega$` 等 ph 体空串**静默丢弃**（surface 数学蒸发）。

修法（HEAD `_on_math` 非配对路 ~:1650-1675 ≡ 补丁 C1+C2）：disp 时 `vspan` 盖到 `nxt.pos[2]`、surface 并入 `nxt.text`；中止分流——源仍存活走 `unread` 回放，EOF 耗尽（源已弹栈）余段直接 `_flush_run`+`_cover_to(fid,len)`+`_emit` LITERAL 保字节（含 `\end{document}`——宁可不翻译不可丢内容）+ `unpaired_dollar` ScanWarning 留痕。

## e2e 实证（HEAD 直跑，无 shadow）

`e2e_mock_bench --ids 0806.3472 --corpus bench/corpus_v3 --conditions base-xel,pipe-xel` → `bench/results/repro-0806-head-2026-09-16/`：

- base-xel clean；pipe-xel **n_errors 66→0、first_error None、L2 hits 0**（基线 modec-v3/tailfix 均 `errors>3 (66)`；未修树同口径误跑过一发是 45）。
- verdict 仍 partial——**唯一剩因 `missing_character×16`，与两条基线逐字节同数**，非 A/B/C 面（见「残留」）。
- `run-before/`、`run-after-frozen-src/` 两轮是 frozen-src 口径（`e2e_mock_bench.py:56` 的 `sys.path.insert(0, TEXLATE_SRC||ROOT/src)` 压 PYTHONPATH）——不含修复，红是预期；`repro-0806-head-2026-09-16/` 才是 HEAD 权威发。

## 残留（新发现，另立票跟进——非本三 bug 面）

1. **`\text{}` 内层 `$` 误配**：`_on_math` 的 `$` 配对不懂 `\text{...}` 参数边界：`$\left\{...\text{for all oriented cup diagrams $c \mu$}\right\}$` 在 `\text` 内层 `$` 处截断（实证 `[[MATH_942]]` body 止于 `...diagrams $`），残余 `c \mu$}\right\}$` 裸落 surface → mock 把 `c` 译成 `这是译文` 落进数学 → cmr10/8/6 缺字 ×16。修法方向：`_on_math` 加 `\text/\mbox/\intertext` 族括号深度跳扫；真 LLM 下此面表现需单独评。→ 任务挂号跟进。
2. **C2 门语义差**：补丁版是 `x is None and isinstance(src, Gullet)`；HEAD 是裸 `x is None`（segmenter.py:1664）。若 `_on_math` 可被 `_ListSource`（in_arg 子扫）触达，EOF 时会误把 `[cons,EOF)` 整段 LITERAL 盖掉抢走主扫字节——今天大概不可达（参数内数学不走该路径），值得补一行守卫。

## 交付物

- `tests/test_segmenter_unpaired_0806.py`（随 `90aa823` 入库）：7 tests 全绿——无 `\bfKostant` 融合、`\vspace{2mm}`→`[[CMD]]`（块内无裸 `{2mm}`）、`$\omega$` 不蒸发、无孤 `$`、两 fixture `reconstruct==tex` 恒等。
- 回归：`pytest tests/ -k "segmenter or expand or parse"` 142/142（HEAD）。
- 现场：`repro.tex`、`segmenter-fix-draft.diff`/`segmenter-fix.patch`（设计评审存档——对当前 HEAD 3/5 hunks 已不适用，因为修复本身在文件里）、`run-before/`、`run-after-frozen-src/`、`../repro-0806-head-2026-09-16/`。
