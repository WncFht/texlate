# 保留契约 —— bench 产物的寿命、删除谓词与活生成器

> 对照 `TIERS.md`（验证分层）、`py/runbook_loop.md`（L3 操作单，含 `work/{id}/` 目录布局）、`stagerun.py` 模块 docstring（DAG 契约）、`py/harvest.py`（zh-store 收割器）。那几份定义**目录里有什么**，本文定义**每样东西活多久、按什么谓词删**。

> **2026-09-20 终态 —— results 归零重启 + 兼容壳拆除 + zh-store 三分区**：旧 run 全部 458 项已删（账本在 `archive-2026-09-20/`）；real 臂 LLM 资产提取至 **`bench/zh-store/`**，收割器 `bench/py/harvest.py`：终判 compile-clean → primary `{id}/`，已译非 clean → `_quarantine/{id}/`（付费字节保留、选池永不重译、可日后免费重编译捞回），落选副本 → `_alt/{id}/{run}/`，覆盖索引 `manifest.jsonl`；语料唯一物理根 `corpus` 54.9G，四源库 symlink 兼容壳同日拆除（原 MANIFEST 折存 `corpus/MANIFEST_{v1,v2,m1k}.md`，版本冲突落选树存 `corpus/_alt-versions/`）；nightwatch 快照循环已停删。**收割后 run 的 `work/` 是纯脚手架可整删，results/ 保持纯账本形态。**

## results/ 结构分类（2026-09-19 时点，387 项）

| 类 | 数量 | 体量 | 内容 |
|---|---|---|---|
| `stagerun-*` / `replay-*` / `soak-*` | 42 | ~44.6G | DAG 格式 run：`records/` + `work/{id}/` + `cases.jsonl` + `run_meta.json` |
| 评测器三件套目录（parsebench/compilebench/validbench/e2e/alignbench/probe 等） | ~300 | <0.5G | `files\|cases.jsonl` + `summary.md` + `papers\|cells.json`（docs/spec/benchmark.md 产出契约） |
| 顶层 `*.md` | 75 | 小 | 一次性报告 / 横评 / walkthrough |
| `nightwatch/` | 1 | 8M 且增 | cron 每 10min 快照 `.md` |

`records-only` 子类（31 个，如 `stagerun-loop1-2026-09-16`、`base-v3-full-2026-09-16`）：有 `records/` 或 `cases.jsonl` 无 `work/`——账本留存，现场已逝或本就不落树。

## work/{id}/ 价值分层（按重建代价）

| 子目录 | 内容 | 重建代价 | 删除口径 |
|---|---|---|---|
| `zh/`（real 臂） | 付费 LLM 译文树 | **不可再生**——重译烧 token，swe-2 promo 2026-10-16 到期后同价买不回 | 收割前不删；`harvest.py` 移入 zh-store 后随 work/ 可删 |
| `splice/` | 中文 PDF + `.fixloop-entry.pdf` + fixloop 修复树 + log | CPU 可重建，但 inject/fixloop 代码漂移使重建字节≠当时字节 | 收割前不删（时间点保真 + replay 播种源）；入 zh-store 后随 work/ 可删 |
| `zh/`（mock 臂） | 确定性译文树 | 免费重建，代价=逐篇 parse+normalize CPU | 默认留；空间告急时 loop2/loop3/flipcheck 系可删（确定性可复现，失当时字节） |
| `xlat-state/` | xlat resume 检查点 | 已完成 run 无意义 | 可删（~0.8G，收益小默认留） |
| `src/` | corpus extracted 原样副本 | 谓词可删：该 id 在任一 corpus 根仍有原件 | **A 档已删**（17.15G，2026-09-19） |
| `build-base/` | base 臂原文直编现场 | 同 src/（corpus 有原件即可重建） | **A 档已删** |
| `_texmf/` | tlmgr usermode 装包落点 | 零成本重下 | **A 档已删** |
| `parse.json` / `xlat-*.jsonl` / `.xlat-arm.json` | 元数据 | 小 | 留 |
| `work/{id}/{zh,splice}/src/` | **论文自身源码子目录** | 是 zh/splice 树的一部分 | 勿当 staging 删 |

## 删除谓词（A 档先例，`tmp/cleanup-a/clean_a.py`）

1. **corpus 覆盖**：`{id}` 经 canon 归一（`--`↔`/` 双拼写都试）在 `corpus`/`corpus_v2`/`corpus`/`corpus_daily`/`corpus_m1k`/`corpus_iclr` 任一根下有目录，才准删 `src/`、`build-base/`；否则保留（它可能是唯一副本）。
2. **在飞跳过**：进程活着的 run 整目录跳过（pgrep stagerun；当时 m1k 在跑即被跳过）；`work/{id}` 顶层 mtime <1h 也跳。
3. **dry-run 先行**：脚本默认 dry-run，`--apply` 才执行；protected/fresh-skip 名单要过一眼再动手。

## 活生成器（删前必查，2026-09-19 时点）

- `texlate-daily-soak.timer`：每日 02:30 UTC 新增 `corpus_daily/` 论文 + `soak-<date>/` run（语料日增 ~1G 级）
- `texlate-errsweep.timer`：每日 18:23 蒸馏（在 errsweep worktree，不写 results）
- 并行会话：replay/重烘焙波随时从既有 run 拷 work 树播种新目录（`replay-mutex-window` 教训：mutex 在飞禁派波）；`tmp/lane-*` 是它们的活现场（<2h 有写入即视为在飞，勿动）
- 收割闸：run 收尾跑 `python3 bench/py/harvest.py --dir <run>`（move 语义）——漏跑则译文随 work/ 删除而丢失；`_quarantine/` 内 id 已在 manifest 标记，选池永不重译

## 下游依赖（为何不能一刀切删 work/）

- 跨阶段续跑：`compile` 读 `zh/`，`fixloop` 就地改 `splice/`——run 目录不是快照是可续跑的现场
- replay 播种：`replay-b3a-2026-09-18` 实证 replay run 只跑 compile+fixloop 两阶段，work 树从 donor 全量拷贝（硬链数=1）
- `triage.py` 工单 `repro_path` 直指 `work/{rid}/`——删树即工单复现路径死链
- `cases.jsonl` 只记判定/动作不记字节——`splice/` 是产物唯一字节面
