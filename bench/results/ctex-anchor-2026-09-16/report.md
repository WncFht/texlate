# ctex theorem 锚点改名修复报告（2410.17902 / B7 sub-gate 0.75 → 1.000）

2026-09-16 · 任务 #28 · 改动：`src/texlate/compile/inject.py` + `tests/test_inject_theorem_anchor.py`

## 结论先行

**根因不是 ctex**。共享计数器 theorem（`\newtheorem{lemma}[definition]{Lemma}` 形态）的 named-dest 命名在 LaTeX 内核 2026-06-01 发生了行为变化：2410.17902 的 en 臂在 Mac BasicTeX 2026（kernel 2026-06-01, hyperref 7.01r）上编译产出 `lemma.3.1` 等 env 名锚点，zh 臂在本机 Arch TL2026（kernel 2025-11-01, hyperref 7.01p）上产出 `definition.3.1` 等根计数器名锚点，两侧集合恰好不相交 → alignbench ret=0.75（13 个 theorem 锚全丢）。

修复是在 inject.py 的注入块里追加 `THEOREM_ANCHOR_SHIM`：在 `\@begintheorem`/`\@opargbegintheorem` 的 before 钩子上按「另一侧名字」补发一个孪生 dest——纯增量、不改名、不动 `\@currentHref` 持久值（.aux label 名不变）。三层验证全过：最小复现双侧 dest 齐发、`pytest` 新增回归用例含真 xelatex 编译、2410.17902 全量重编后 alignbench **ret 0.75 → 1.000**，且同工具链配对不退化（1.000）。

## 机理（实证链）

### 命名分叉点：`\newcounteralias`

kernel 2026-06-01 引入 `\newcounteralias{alias}{root}`（ltcounts.dtx v1.2c）：`\c@alias` `\let` 到 `\c@root` 寄存器，`theH<alias>` 转发 `theH<root>`，并记录 `\alias@ctr@<alias>`=root。同版内核的 `\@othm`（共享计数器 `\newtheorem` 的底层）改用 alias 计数器：env 步进**自己的别名计数器** → `\refstepcounter` 把 `\@currentcounter` 置为 env 名 → hyperref 的 `refstepcounter/target` socket 产出 `env.N` 锚点。firstaid v1.1t 的 `\@amsthm@reset@ynthm` 对 amsthm 的 `\@ynthm` 做了同样改写，并挂 `package/amsthm/after` 与 `class/amsart|amsbook|amsproc/after` 钩子（ams 类内嵌 amsthm 不走 usepackage，需要类钩子兜底）。

旧内核（本机 2025-11-01）没有这套机制：amsthm `\@ynthm` 只 `\xdef\the<env>` 转发 `\the<root>`，env 体调 `\@thm{style}{root}{title}` → `\refstepcounter{root}` → `\@currentcounter`=root → 锚点 `root.N`（cleveref 加载时 `\@thm` 被换成 `\@ifnextchar` 版本，`\refstepcounter[env]{root}` 的 optarg 只记录 cref 类型，步进的仍是 root——与 zh 臂 .aux 里 `l1@cref` 记 `[definition]` 类型互证）。

### 反证 ctex

本机用**同一份 en 源**（无 ctex）直接 xelatex 编译即得 `definition.*` 锚点——ctex 从头到尾无罪；分叉完全由 en/zh 两臂工具链差产生。en 臂日志头：`TeX Live 2026 (format=xelatex 2026.7.16)` + hyperref `2026-06-17 v7.01r` + `/usr/local/texlive/2026basic/`（BasicTeX, Mac）；zh 臂：`TeX Live 2026/Arch Linux (format 2026.5.31)` + kernel 2025-11-01 + hyperref `7.01p`。

### 为什么不选「改名对齐」

brief 原定方向是 zh 侧把 `definition.*` 改名回 `lemma.*`。否掉的理由：生产路径 `worker._compile_en` 与 zh 用**同一引擎**编译——同工具链对上锚点本来就一致（两边都是 `definition.*`），改名 shim 会把正常对掰坏。加性孪生 dest 对四种组合全对：旧en+旧zh（两边原生同名，shim 各补一个对方名）、新en+新zh（同理）、新en+旧zh（本案）、旧en+新zh（将来升级后）。孪生只是多一个 dest，不影响 zh 内部链接与 .aux。

## 实现

`src/texlate/compile/inject.py` 新增 `THEOREM_ANCHOR_SHIM`，`inject_cjk` 在 ctex/xecjk 两种模式下都追加（分叉本质是工具链差异，与 CJK 引擎选择无关）：

- 挂 `cmd/@begintheorem/before` + `cmd/@opargbegintheorem/before`（内核原生 theorem 的带 `[note]` 入口；amsthm 下 `\@opargbegintheorem` 是 `\relax`，cmd 钩子延迟到 `\begin{document}` patch，对 `\relax` 静默放弃——实测无警告）。
- 触发时 `\@currentcounter`/`\@currentHref` 已由 `\refstepcounter` 设好（原生锚点已发）。判定：`\@currenvir`==`\@currentcounter` 且 `alias@ctr@<env>` 存在 → 新内核 alias 情形，补 `root.\theH<ctr>`；不等且 `\the<env>` 有定义 → 旧内核共享计数器，补 `env.\theH<ctr>`。
- 发射走 `\MakeLinkTarget*{<name>}`（manual 星形形态，避开 counter 存在性检查——旧内核上 `c@lemma` 本就不存在，非星形会抛 "Counter 'lemma' ... not defined" 警告）；`\@currentHref` 发射前存、发射后 `\global` 恢复，后续 `\label` 仍写原生名。
- 守卫链：`MakeLinkTarget` → `\@currentcounter` → `theH<ctr>` → `alias@ctr@<env>`/`the<env>`，任何一环缺失即整体 no-op（无 hyperref、proof 类无号环境、自有计数器 env 均安全跳过）。不挂 `\@thm`/`\@ynthm`/`\@othm` patch → 与 cleveref 加载顺序零耦合。
- 泛化：shim 文本零硬编码 env 名，对一切 `\newtheorem{<env>}[<root>]` 声明生效（`test_shim_no_hardcoded_env_names` 用 `\b<name>\b` 断言 lemma/definition/theorem/corollary/proposition 均不出现）。

## 三层验证

### L1 最小复现（tmp/exp/b7-241017902-ctex/shim_test.tex）

amsart+amsthm+hyperref+cleveref，`definition[section]` 根 + `lemma/theorem` 共享 + `own` 自有计数器对照。本机 xelatex（kernel 2025-11）两轮编译后 dests：

`definition.1.1 … definition.1.4`（原生）+ `lemma.1.2` `lemma.1.3`（孪生，含 `[named]` 可选注路径）+ `theorem.1.4`（孪生）+ `own.1`（无孪生，正确）。.aux `\newlabel` 仍记 `definition.1.2` 等原生名——`\@currentHref` 恢复生效。

反向模拟（`shim_test_case1.tex`）：手工 `\let\c@lemma\c@definition` + 定义 `alias@ctr@lemma`=definition + `theHlemma`=`theHdefinition`，env 直接步进 `lemma`（模拟新内核行为）→ dests 出 `lemma.1.2`（原生）+ `definition.1.2`（孪生根名）——case1 分支验证。

### L2 pytest 回归（tests/test_inject_theorem_anchor.py）

3 用例全绿（本机实跑 2.3s）：双模式注入断言、无硬编码 env 名断言、真 xelatex 编译 + `extract_landmarks` 断言孪生 dest 齐发 + `own` 无孪生（`shutil.which("xelatex")` 缺失时 skip）。

### L3 全量重编 + alignbench

`bench/results/stagerun-loop1-2026-09-16/work/2410.17902/zh/exceptional.tex`（pre-injection 快照）→ `prepare_chinese`（真实产品路径：ctex + shim + float_sizing）→ xelatex 3 遍 → zh PDF 65 dests。

| 对子 | a | b | dests a→b | common | ret |
|---|---|---|---|---|---|
| 修复前（pairs.jsonl:479） | base-xel（Mac 新内核） | pipe-xel | 52→52 | 39 | **0.750** |
| 修复后 | base-xel | zh_rerun（本机 + shim） | 52→65 | 52 | **1.000** |
| 同工具链对照 | 本机 en（旧内核，definition.* 原生） | zh_rerun | 24→65 | 24 | **1.000** |

输出物：`pair/`（跨工具链）与 `pair-local/`（同工具链）两份 alignbench 产物。65-52=13 个 zh-only dest 即补发的 `definition.*` 原生名——en 侧 `lemma.*` 全数命中孪生。

## 文件与边界

- 改动：`src/texlate/compile/inject.py`（`THEOREM_ANCHOR_SHIM` 常量 + `inject_cjk` 追加一行 `block += THEOREM_ANCHOR_SHIM`）、`tests/test_inject_theorem_anchor.py`（新增）。
- `uv run ruff check` / `ruff format --check` 两文件全净；`pytest tests/test_inject_theorem_anchor.py tests/test_compile_inject.py` 17 绿（inject 相邻面 58 绿）。
- 残留风险：非 `\@begintheorem` 系的 theorem 实现（ntheorem 自建路径、thmtools 的 `\end` 后置等）钩不到——静默 no-op 不劣化；`\@opargbegintheorem` 在 exotic 包下若被定义为不可 patch 形态，ltcmdhooks 静默放弃，同样 no-op。
- 未做：zh 侧 PDF 内部 `\ref` 链接仍指 `definition.*`（原生名）——本就正确，无需处理；en 侧同名链接在双链 PDF 里经 align 解析照旧命中。

## 附：关键代码位置

- shim 常量：`src/texlate/compile/inject.py` `THEOREM_ANCHOR_SHIM`（docclass 缝注入，ctex/xecjk 双模式）
- 复现现场：`tmp/exp/b7-241017902-ctex/`（gitignored scratch；`shim_test.tex`/`shim_test_case1.tex`/`zh_rerun/`）
- 基准产物：`bench/results/ctex-anchor-2026-09-16/pair{,-local}/`
