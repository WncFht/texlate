# docs/ 一致性审计 — 2026-09-16（工作树）

只读审计：docs/ 四层文档体系 vs 仓库现状。基线 = 审计时点工作树。
**注意**：审计窗口内 `docs/README.md`、`docs/research/README.md`、`AGENTS.md`（=CLAUDE.md 目标）、`docs/HANDOFF-2026-09-16.md` 被并行会话实时更新——任务书预期的多处"缺失索引"在审计过程中已被修掉，下表逐项标注 [审计中已修]。

## 缺失索引项

| # | 位置 | 内容 | 现状 |
|---|------|------|------|
| 1 | `docs/README.md` 索引表 L6–21 | 顶层 14 个 .md 全部在列（含 HANDOFF-2026-09-16）；research 计数已改 "73 篇"（实际：research/ 下 75 个 .md − 2 个 README = 73，口径自洽 ✓） | **完整**[审计中已修：原为 "58 篇"] |
| 2 | `docs/research/README.md` product/ 表 L85–88 | `2026-09-16-batch-hardening-design.md`/`2026-09-16-e2e-pipefix-hotlayer.md`/`2026-09-16-signature-mining.md`/`shared-cache.md` 四篇已补登；arxiv/corpus/gateway/latex 各子目录文件全数在列 | **完整**[审计中已修] |
| 3 | `docs/research/audit-2026-09-16/README.md` §6 L69–85 | 13 分报告（m0–m3 + spec06/07/08/0910 + e2e-func/tests/codehealth/evidence/docs）全列，与目录文件一一对应 | **完整** |
| 4 | `bench/corpus_v3/MANIFEST.md` L4 | 入库清单枚举漏 `manifest_hot.jsonl`（72 行）、`manifest_expand.jsonl`（3800 行）及管线 `build_hot_layer.py`/`build_corpus_expand.py`——正文 L1018/1033 有 booster/hot 层叙述但头部清单未追记 | **仍缺** |
| 5 | `docs/10-benchmark-suite.md` §0 L10–18 | 总览表仍写"七个 benchmark"：`stagerun.py`（五阶段批量驱动）、`qualbench.py`（LLM-judge 质量臂 ≈B4b 部分面）、`triage.py`（失败分诊）三个新评测器无任何条目——stagerun 设计在 `research/product/2026-09-16-batch-hardening-design.md` 有记但 10 未引 | **仍缺** |
| 6 | `bench/PROTOCOL.md` L10–17 | fixtures 清单已补齐 8 件（tricky-w/w73/wenc/xlat-traps/escape-outside 在列）✓；唯 L10 "26 个陷阱构造" vs 实测 27 个唯一 `@Tnn`（28 行出现）计数差 1 | 基本完整，计数小误 |
| 7 | `AGENTS.md`（CLAUDE.md）L4/L8/L13/L18/L22 | 现版已覆盖 `export/`、`share.py`、`server/` babeldoc sidecar+cmaps、`bench/py` stagerun/triage/qualbench/build_corpus_*、corpus_v3 四层 5072 篇——任务书引用的旧版缺漏全部修复 | **完整**[审计中已修]。残余小项：server/ 未枚举 `settings.py`/`events.py`/`staticfiles.py`/`__main__.py`；cli 命令列缺 `version` |

## 过时描述

| # | 位置 | 声明 | 现状证据 |
|---|------|------|----------|
| 1 | `docs/09-benchmark-corpus.md` L2 表头 + L159 | "~1,200 篇"、"raw ~3.7MB×1,200 ≈ 4-5GB" | manifest 四件合计 **5072** 篇（1000+200+3800+72），expand 层（`manifest_expand.jsonl` 3800 行 + `build_corpus_expand.py`）在 §6 布局图 L146–157 与全文均无提及——hot 层有 L123 增补注记，expand 层没有对应注记 |
| 2 | `docs/08-translate-compile.md` L239–240 勘误 | "rules 段 31 条（v3 整改）" | `src/texlate/compile/fixloop/rules.yaml` rules 段实测 **33 条**（taxonomy 28 条未变） |
| 3 | `docs/08` L185/L217/L246 + `docs/05` L72/L79 | `\documentstyle` → "无条件 reject" | 实装已改 `latex209_suspect` 降级试编 + inject 兜底拒真 2.09（`38cc0a7`，HANDOFF-0916 §4 有决策记录）；按 docs/README 修改纪律，推翻 05 §3 裁决 13 应在 05 加注记——未加 |
| 4 | `docs/08` §3.4 L189–192 | target_probe 作为管线步骤 | `src/texlate/compile/probe.py` 已落（`54e1c4b`）但**零调用点**——worker.py/e2e.py/cli.py 全无引用，属"库落未接线"，spec 无状态注记 |
| 5 | `docs/10` L22 现状列注记 | "Mode B 未产品化、Mode C 未跑"、"B3 zh 条件臂从未跑"、"B7 当前门 FAIL（2 ERROR + 0.026 离群对）" | Mode B/C 已实装 `bench/py/e2e_mock_bench.py` pipeB-xel/pipeC-xel（`f4d9ec8`/`c187025`，`bench/results/mock-sabotage-v3-2026-09-16/`）；B3 zh 臂已跑（`bench/results/compilebench-v3-zh-2026-09-16/` + `fixloop-zh-cbv3-2026-09-16/`）；B7 已归因（`b7-attribution-2026-09-16` + `5b37831`：xelatex ~100 错截断 cite.* 必死）+ pipe-fix 复测 mean 0.9918（`27d2096`，HANDOFF §6.1） |
| 6 | `docs/10` L77 B3 状态 | "base×双引擎臂由 compilebench-v3（corpus_v3 抽样）在跑" | v4+fixloop 臂已跑完（`61a9e16`，联合 pdf 154/172=89.5%）+ `base-v3-full-2026-09-16` 全量基线在盘 |
| 7 | `docs/07` §12.2 L520 + §12.3 L529 | 性能注记 "85 文件 >500ms、max 8.4s" | `0278602`/`55db9bc` 两波 perf 后长尾 -48%（51476→26723ms）、>500ms 文件 20→11（HANDOFF §6.1）——切换时点数字未回写；§12.3 `res.macros` union 遗留**仍开**（`model.py:208` 仍是 `MacroTable \| GulletMacroTable`） |
| 8 | `docs/HANDOFF-2026-09-16.md` L11 §0 | "HEAD `f461683`（master）。1090 passed/16 skipped" | §6 已续记 ~15 个后续 commit（至 `0454e57`），§0 头部快照未更；tests/ 现 81 个测试文件（审计时点为 49） |
| 9 | `docs/HANDOFF-2026-09-15.md` L3 | "状态：M0 实施中" | 当日快照头部，M0 已验收——dated 文档可不改，但与 README "随里程碑更新" 定位略冲突 |
| 10 | `README.md`（根）L19–20 表 | "SPA 打包待接"、"fixloop 31 规则" | `server/static/` 已建 + `pyproject.toml` L43 `artifacts=` 打包钩 + `scripts/build-web.sh` + `Dockerfile` 均在（审计时 audit M3 报的断链已接）；rules 实测 33 |
| 11 | `docs/research/latex/2026-09-16-aux-cjk-truncation.md` | "机理（推断，待复现确认）"、fixloop 切入点"建议" | 修复已落：`normalize.py:638–662 _transcode_aux_bib`（docstring 自引本文"立项臂二"）+ `tests/test_normalize_aux_trunc.py`——文档未加"已修"注记 |
| 12 | `docs/audit-2026-09-16/README.md` 整体 | 时点审计（HEAD `6a256b2`）| 其 P0/编排缺口多数已在同日午后修复（见下表）；作证据档案可不改，但 CLAUDE.md/HANDOFF 以它为"当前判定"入口，顶部无"部分结论已过期"指针 |
| 13 | `docs/06-arxiv-source.md` 全文 | 无任何落地记录节（规范原文态） | §3 元数据层已全落（`arxiv/meta.py`：Atom 主源 + OAI-PMH 兜底 + `PaperMeta` schema + `resolve_version`/`degrade`，`d7b3c0a` + `test_arxiv_meta.py`）；§5 降级链 `degrade()` 裁决层已落（L2 html/L3 pdf sidecar 判空逻辑），babeldoc sidecar 落地 `server/babeldoc.py`——均无注记 |
| 14 | `docs/08` §3.2 L165–178 手术清单 | 12 条无条件手术 | `normalize.py` 新增 `_transcode_aux_bib` 编码层（aux/bib/bst 非 UTF-8 转码 + 8192B 截尾整形，`4a8d5ce`/`b6ba25a` 系）未进清单 |
| 15 | `docs/08` §4.2 L217 路由表 / §4.4 沙箱 / §5 | 路由表无沙箱落地记 | `compile/sandbox.py` + `tests/test_compile_sandbox.py`（bwrap，`b260378`）已落；F3 verdict 语义改判（`daf6a2a`：reject→partial+`reject_at`∈{fixloop,inject,route}）使 §4.3/§5.4 verdict 词汇表偏旧 |

## 已完成但标待办

审计 P0 三件（`audit-2026-09-16/README.md` §4 + HANDOFF-0916 §3 引言 L109–114 仍以"待修"口径引用）——**三件全部已修**：

| # | 审计条目 | 修复证据 |
|---|----------|----------|
| 1 | H1 `worker.py:840` options.main 路径逃逸 | `worker.py:1333–1345`：resolve 后 `is_relative_to(base)` 拒绝绝对路径/`..` 逃逸，`main_rel` 只取 base 内相对路径 |
| 2 | M2 `worker.py:1321 _make_glossary` 任意文件读 | `worker.py:2511–2534 _glossary_path`：绝对路径/`..` 形态即拒 + resolve 后须 `is_relative_to` 允许根（base + settings `glossary_dir` 受信根）+ `glossary_rejected` warning 事件 |
| 3 | H2 RedactFilter 未挂载 + 远端 body 落盘 | `settings.py:490–549 RedactFilter`/`install_log_scrub` 实装并挂载于 `app.py:231`（root logger + uvicorn 系 handler 全覆盖 + 幂等换装）；`client.py:702` 等错误路径过 `redact()`；`tests/test_server_security.py:415–439` 回归用例 |
| 4 | （附带）H3 ctan.py overlay 路径穿越 + xz 无上限 | `ctan.py:160–172 _norm_member_name` 任意位 `..`/绝对路径/盘符全拒 + `_decompress_xz` cap（`max_inflated`）——已修 |
| 5 | （附带）M1 `find_reusable` 无 tenant 过滤 | `worker.py:390–409 cache_key_for` docstring 记为**设计决策**（跨租户 reuse=hjfy 对等缓存既定特性）+ `cache_scope()=="per_key"` 模式按 `sha256(api_key)[:16]` 分桶消 oracle——已按设计收口，默认共享桶下 oracle 仍存在属有意取舍 |

HANDOFF-0916 §3 其余"待做"实为已落：

| # | 位置 | 条目 | 落地证据 |
|---|------|------|----------|
| 6 | L137–139 | "aux/bib 8192B 截断→invalid UTF-8 立项（未做）" | `_transcode_aux_bib`（normalize.py:651）+ `test_normalize_aux_trunc.py` |
| 7 | L139 | "cs→包表长尾接 llm_hook（目前 cs_targeted_fix 只覆盖静态表）" | `fixloop/llm_hook.py` + `engine.py:696–729`（escalate_llm action + `fallback: escalate_llm` 挂钩，rules.yaml L1009 已引用）——残余真缺口：worker 调 fixloop 未传 `llm_hook` 参数 |
| 8 | L141 | "babeldoc `_run_pdf` 对照实验：决策=暂缓" | babeldoc sidecar 已进 worker 产品链（`8d50c38`：`server/babeldoc.py` + `_run_pdf`/`_babeldoc_job`/`_finish_pdf`）——§6.1 已记但 §3.2 原文未划销 |
| 9 | L110–112 | "编排断链（fixloop 未接 e2e/worker、L2→重译回灌、target_probe、env-judge/recover_copied_tokens 零调用点）" | fixloop：`e2e.py:33` + `worker.py:50/1837` 双接；L2 回灌：`worker.py` `_l2_localize`/`_retranslate_hits`；env_judge：`worker.py:1677`；recover_copied_tokens：`pipeline.py:477`。**唯一仍断：target_probe 零调用点**（见过时表 #4） |
| 10 | L112–113 | "未跑的门：B3 zh 臂、e2e Mode B/C、B7 当前 FAIL" | 见过时表 #5——三者均已有实质推进/归因 |
| 11 | L113–114 | "测试缺口：e2e.py 零覆盖、xlat/client 无离线用例、12 条静默死 skip" | `tests/test_e2e.py` + `test_e2e_wiring.py`、`test_xlat_client.py` + `test_xlat_client_wire.py` 均在；现存 skipif 全部环境/语料门（合法），另有 `test_l0_holes.py`/`test_compile_sandbox.py`/`test_server_polish.py` 等新增 |
| 12 | L123–126 | "性能尾 85 文件 >500ms、max 8.4s" | perf 两波已落（-48% 长尾），残余 11 文件 ——条目未划销 |
| 13 | （审计 P1）argspec.json 1820 条产品面零装载 | M1 GAP | `tables.py:535–578 argspec_tables/argspec_lookup` 装载并接入 `segmenter.py:3052/1615` 分派热路径——已修 |
| 14 | （审计 M3）SPA 送不出去 / Dockerfile 缺位 | `server/static/` 构建产物在盘 + pyproject `artifacts` + `scripts/build-web.sh` + `Dockerfile` ——已修 |
| 15 | （审计 P2 未消项）INLINE_MAX=8000 死常量 | `tables.py:23` 仍零消费——**仍开** |
| 16 | （审计 P2 未消项）`build_corpus_v3.py:962` 第二套 unpack | 仍在（`unpack_blob`/`safe_name` 自实现，未归并产品层）——**仍开** |

## 建议的新文档

| # | 主题 | 现状 | 建议 |
|---|------|------|------|
| 1 | corpus_v3 **expand 层**（3800 篇，`build_corpus_expand.py`/`manifest_expand.jsonl`，总 5072） | 仅 HANDOFF §6.1 + batch-hardening-design 提及；无渠道/frame/配额/去重口径立档，09 与 MANIFEST 均无 | `docs/research/corpus/2026-09-16-expand-layer.md`（数据面 + QC：`bench/results/corpus-expand-qc-2026-09-16/`）|
| 2 | **qualbench**（B4b LLM-judge 质量臂，`c81d695`） | 仅 HANDOFF 一笔；10 §B4b 仍写旧方案 | 短注记进 10 §B4b + `research/gateway/` 或 `product/` 留档评分协议 |
| 3 | **安全 P0 三件修复对账** | audit 报告留问题、代码已修，无修复记录文 | 在 `research/product/` 留一篇 fix-note（confinement 规则/RedactFilter 挂载面/残留 M1 设计取舍）|
| 4 | **F3 verdict 语义改判**（reject→partial+reject_at，`daf6a2a`） | HANDOFF §6.1 有记；08 spec verdict 词汇未同步 | 08 加勘误段即可，不必新档 |
| 5 | **stagerun 批跑 + loop1 结果** | 设计文在 batch-hardening-design.md；`runbook_loop.md` 在 bench/py | loop1 跑完后落 `bench/results/stagerun-loop1-*/` 报告 + 09/10 各加一行口径注记 |
| 6 | **babeldoc sidecar / export 产品面** | pdf-path.md/doc-formats.md 是"暂居 research/"的后置规范，实装证据散在 `export-realbook`/`export-verify` results | 落地注记加进两 spec 文头即可 |
