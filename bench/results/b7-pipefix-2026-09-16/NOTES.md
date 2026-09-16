# B7 pipe-fix 口径复跑 — 补充笔记

脚本产出见 `summary.md` / `attribution.jsonl` / `coverage.jsonl` / `rescue.jsonl`。本文件记录两条不能从表内读出的实证。

## 2410.17902 ret=0.750 — ctex 注入致共享计数器锚点改名（复现实锤）

- 现象：en 52 dests ↔ zh 52 dests、common 39；丢的 13 个全部是 theorem 族（`lemma.3.1..3.10`/`theorem.1.1`/`theorem.3.11`/`corollary.3.2`/`conjecture.4.1`），zh 侧多出 13 个 `definition.*`。
- 根因：`exceptional.tex` 导言 `\newtheorem{lemma}[definition]{Lemma}` —— 全 theorem 族共享 `definition` 计数器。无 ctex 时（amsart+hyperref，TeX Live 2026 内核计数器别名机制）锚点按环境名出 `lemma.3.x`；**仅注入 `\usepackage[fontset=fandol,UTF8]{ctex}` 一行**（连翻译都不做），锚点即退化为父计数器名 `definition.3.x`。
- 复现：`tmp/exp/b7-241017902-ctex/` — 原 en 源 +ctex 行 → 产出 `definition.1.1, definition.3.1..3.11, definition.4.1`，与 zh 产物 new_b 13 条逐名一致。`\RequirePackage{xkeyval,ifpdf}` 行已二分排除（无关）。
- 判定：zh PDF 内部 `\ref`/`cleveref` 完全自洽（52 dests 全在、可点），损失的是 **en↔zh 同名锚点对拍**——对 B7 口径是真阳性，但不是 shell/翻译丢锚点，是 ctex 与内核 `\theH<env>` 别名机制的包交互。仅 1/35 可测对命中，因为共享计数器导言写法占比低。
- 处置选项：(a) 产品侧在 ctex 注入后补 per-env `\theH<env>` 别名定义（恢复 en 侧锚名口径）；(b) B7 口径侧对 `other` 类锚点放宽到数字后缀匹配（会弱化同名同步语义，不推荐）；(c) 接受为已知包差异、门槛对 `other` 类豁免——需 leader 决策。

## en 侧救援（base-rescue 臂）

- 31 个 base-xel 缺 main.pdf 的 id（legacy 包：revtex4/4-1/4-2、IEEEtran、pstricks、stmaryrd、shuffle、extarrows、aps4-2.rtx），用各 id 的 fixloop usertree（`work_e2ereal/_texmf/{sid}`）补编。
- 结果 29/31 出 PDF（clean 19 / partial 10），仍 fail 2：`0905.1767`、`1511.06879`。
- 坑（已修）：TEXMFHOME 传相对路径会被 xelatex 按工作目录解析 → usertree 失效全部 `File not found`。`rescue_en_baselines` 已 `.resolve()`；勿回退。

## §4 可行性盘点（B3-zh / B4b / Mode C）

- **B3 zh 臂：实际已跑完主体，文档「从未跑」已过时。** `compilebench-v3-zh-2026-09-16`（n=180，xelatex clean 27.4% / tectonic 35.4%）+ `fixloop-zh-cbv3-2026-09-16`（n=175，zh+ctex+fixloop：union pdf 120→151/175=86.3%，clean 层 150/175=85.7%）。距 M2 门「200 篇 ≥90%」差 25 篇 + 3.7pp；杠杆=missing_file shim（xelatex FAIL 108 格里 106 格是 missing_file，88 出 pdf/84 clean 已救，剩 unfixable 多为 revtex/aastex 类 legacy 件）+ eps_image tectonic 臂。
- **B4b：** 输入=corpus_v3 ~100 篇真实翻译——e2e-real-n100-postcutover 已产出 100 id 真译文树（pipe-xel/pipe-fix verdict：clean 51/partial 28/fail 13/reject 8，union pdf 79% vs 门 85%）。缺口：(1) qualbench 在 `_xlat_state`（111 篇/13345 chunk 对）上的实跑——脚本就绪（`bench/py/qualbench.py`，state 模式直读 StateStore），只差 LLM-judge 调用成本（~13k 对 × judge 模型，或 `--n` 抽样控量）；(2) 「译文进 B3 网格」已由 pipe-xel/pipe-fix verdict 等价覆盖，无需重跑。
- **Mode C：** `pipeC-xel`/`pipeC-tec` 已实装（e2e_mock_bench.py），corpus39 冒烟已跑（`e2e-modes-2026-09-16`，n=16：pipeC clean 3/16、pdf 14/14、4948 扰动、Mode B escaped=0）。上 corpus_v3 的阻塞：`e2e_mock_bench.py:54` `CORPUS = ROOT/"bench/corpus"` 硬编码，需加 `--corpus` 参数（~10 行）。成本：corpus39 全量 39 篇 × ~2min/篇 ÷ jobs ≈ 20min；v3 抽 50 篇 ≈ 1h。
