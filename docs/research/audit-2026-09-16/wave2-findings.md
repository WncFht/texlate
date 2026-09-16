# 审计波二（2026-09-16 午后）— 9-scout 发现台账与路由

> 触发：leader（texlate-1d）派 9 只读 scout 全仓复扫，配合「优化改进重构整理」目标。
> 本台账记每条发现的处置：**fixed**=已落 commit、**fixer**=修复 agent 在飞、
> **routed**=按文件归属转 peer、**deferred**=收敛决策项、**wontfix**=判定不动。
> 归属约定：latex/e2e/fixloop/bench/tests/横切=1d；compile/engine.py、
> xlat/pipeline.py、fixloop/rules.yaml=项目体验方式；server/worker/probe/web=1e。

## scout 交付总览

| scout | 范围 | 条数 | 处置分布 |
| --- | --- | --- | --- |
| audit-latex-core | segmenter/gullet/mouth | 12+琐 | fixer-latex |
| audit-latex-periph | scanner v1/macro_table/flatten/api/model/tables/init | 9+退役清单 | fixer-latex + deferred(v1 退役) |
| audit-compile | compile 七件 | 10+附记 | routed 项目体验方式（engine.py），judge 小项 fixed |
| audit-fixloop | fixloop 全件+接线 | 12 | fixer-fixloop + routed(rules.yaml) |
| audit-xlat | xlat/*+接线面 | 11 | routed 1e(worker)/项目体验方式(pipeline)，client 项 fixer-e2e-misc |
| audit-server-e2e | server/e2e/cli/align/export | 12 | routed 1e ×9，leader 侧 fixer-e2e-misc ×3 |
| audit-tests-2 | tests/ 92 文件 | 10 | fixer-tests ×5 + routed 1e(staticfiles) |
| audit-bench | bench/py 全件 | 10 | fixed(misschar P0) + fixer-triage + fixer-bench-hygiene |
| audit-crosscut | TODO/docs/命名/依赖 | 7 | fixed 5583176（三件 doc 漂移+超集注释）+ deferred ×3 |

## P0 / 实证缺陷（已修）

- **`stagerun --on misschar` 恒选 0**：`_on_misschar` 读顶层 `crec["verdict"]`，compile rec 实际嵌 `metrics.verdict` → `2d2a412`（实证：修后 663 格 partial / 154906 缺字入闸）。peer 确认 misschar 轮未跑、直接吃活代码。
- **`_group_surface` 复刻 `_dispatch` 漂移**（segmenter.py:979 vs 1270）：组内 REF 判定漏 `"hyperref"` 排除 → 展开组内 `\hyperref[o]{text}` 可译参被 REF 整吞；缺 verb 行 → 组内 `\verb` 泄进 surface。→ fixer-latex P0。
- **triage `leftover_ph→core` 不可达**：xlat 错误写 `cat="xlat",code="leftover_ph"`，classify 按 cat 路由 → 全归 rule 且 `xlat:fault=N` 按计数碎 sig。→ fixer-triage。

## 修复在飞（6 fixer）

- **fixer-triage**（triage/stagerun/benchlib）：末行胜去重（compile.jsonl 已有 79 重复行）、run_meta `started_at/finished_at` 字段、skip 豁免失效+`stub_format:{member}` 碎票、sig 合成单源化（`_verdict_sig` vs `_legacy_sig` 漂移、`_judge_tail` vs `judge_dict` 差 payload）。
- **fixer-bench-hygiene**：死 spike 簇 ~2900 行验证删除（fixloop.py/fixloop_report/compile_bench/compile_report/rerun_xelatex/macro_scan）、`fixloop_bench` 模块级 RS IO 惰性化、`unpack_blob` 归并产品 `arxiv.unpack`。
- **fixer-tests**：pyproject `testpaths`/`norecursedirs`（裸 pytest INTERNALERROR）、`_HAS_RUN_DOC` 遗迹门、SSE `_FEED_DELAY` flake、`_StageError` code 覆盖、file:line 重复钉评估。
- **fixer-latex**：上列 P0 + `math_debt`/`math_depth` 死机制 + 切点链/input marker/env→PhType 三分收敛 + `FILENAME_CHARS` 单源 + `__init__` 24 死 re-export + `parse_file_v1` top_dir 转发 + `_cov_origin` 复现验证。
- **fixer-e2e-misc**：e2e mock 臂 partial 译文准入对齐、cli `_thin_submit` KeyError+退出码表、align 错误路径 `heights` 缺席、export epub/docx 双驱同构评估、client 死公共 API 标注。
- **fixer-fixloop**：`_when_ok` fail-open→对称 fail-closed+键白名单、`regex_rewrite` 0 命中落 flags、`_gate_eval` dedup 前置、`CtanFetcher.index` 共享索引 mutate、`pdftex_prim` subclassify 误路由、`missing_char_fix` verbatim 防护、`timeout_sec` 消费+timeout 透传链、`stats_backfill` project/corpus 口径、llm_hook 我侧四调用点 opt-in 接线。

## 已路由 peer

**项目体验方式**（compile/engine.py + pipeline.py + rules.yaml）：

- pipeline：LengthTruncatedError 双重放大（已裁 `max_tries=2`，落 `f22c0fe`）、`_route_chunks` 纯占位符绕拦截面（已堵）、`_one_chunk` 缓存丢 batch_id（已补）、skipped 双轨（缓行另立 ticket）、leftover_ph 集合差保持（注释留证）。
- engine.py：`_ERROR_RULES` vs rules.yaml taxonomy 双轨漂移（缺 8 id+3 变体组）、env 降级模式 `-shell-escape` 无兜底（安全）、tectonic `-Z` 直通后门、latex209 head 松版残留、`sandbox_wrap` extra_rw 不转发、`run_process` OSError 无捕获、`parse_log` vs `logparse` 口径差（ctx 9v8/l.N 锚位/warnings 词表）、路由信号双表（与 1e 的 probe.py 跨边界）、`include_eps` 死参、TMPDIR 沙箱内空挂、`_TECTONIC_ATTEMPTS` 真超时翻倍。
- rules.yaml：死配置面（capabilities/denylist_*/oracle/cache/params 若干净）、注释反转（epsf/binhex 通路描述、头注 25→36）、`vendored_sty_shadow` tectonic `mode:same` 撒谎（probe 无 cwd 恒 None）。

**texlate-1e**（worker/store/app/probe/web）：

- worker：`ph_fragments` 主路径不武装（recover_copied_tokens 生产死臂）、cancel `run_task` 孤儿化、env_judge/L2 旁路丢 glossary+usage_sink 且污染共享缓存、`_run_fixloop` 不吃 `reject:*`/`engine_flags`（reject_at 缺 fixloop 档+跨引擎臂缺席）、`_build_dual` loop 线程跑 pypdf、cancel TOCTOU force 覆写、`unpack_zip` 单层 parent 检查、`_run_doc` fallback client 泄漏、`_iter_pdf_fonts` IndirectObject、两次 `asyncio.run` 跨 loop 开关 client。
- store/app：`recover_startup` 僵尸 queued、`upload()` 孤儿目录、`chunk_counts["cached"]`/`warnings` 死字段、`staticfiles.py` 孤儿模块+SPA 挂载零测试。

## deferred / 决策项（leader 收敛）

1. **v1 退役**：periph 给了完整切线清单（api/scanner/macro_table/model/tables/gullet/init + ~5 测试文件 + parsebench v1 臂 + TEXLATE_NO_EXPAND 语义）。`flatten_inputs` 与 model 字节原语 bench 承重必留。**判定输入**：v2 已默认且 corpus_v3 3937 全绿——退役收益=删 ~1653 行 scanner+~430 行专属机械+消双臂字段并集；成本=失回退臂。倾向：本轮先不退役（pipeline 仍在演化，回退臂保险费低），清单存档待 M3 前再决。
2. **e2e_real_bench↔stagerun real 臂双轨**：判分同义（同 judge+flb 配方），差异仅记录形状。倾向：e2e_real 退 lib、main 标 legacy；e2e_mock 保留（tectonic 臂+L2 回灌+Mode B/C 唯一事实源）；compilebench_v3 残值=分层抽样+tectonic base。
3. **L2 编排环 e2e↔worker 双份**（`_l2_repair`↔`_l2_repair_zh`、`_env_judge_pass`↔`_env_judge_filter`）：底层原语已共享，编排环漂移中。抽注入 compile_fn/writeback_fn 的驱动函数——跨 1d/1e 边界，需与 1e 协商落点。
4. **status 词表四套混用**（verdict clean/partial/fail+reject、段 ok/fault/skipped、inject already/no-docline/injected、job pending/…）：至少 docs/08 补一节词表映射。
5. **`skipped` 语义双轨**（status vs bool 反向命名）：peer1 缓行裁决，另立 rename ticket。
6. **taxonomy 单源化方向**（engine↔rules.yaml）：peer1 裁决中，实现重活在他们侧。
7. **L2 真 log/spikereplay 干净 clone 永跳**：裁 1-2 条小真 log 入库 tests/fixtures/（M，下轮）。
8. **`TokenSource` Protocol 名存实亡**（声明 4 方法实触 8+ 成员 + isinstance 特判×4）：M 重构，列入 backlog。
9. **llm_hook 生产接线**：我侧 bench/e2e opt-in 已在飞；worker 侧等 1e 按 options 开关裁决。

## wontfix / 已核健康

- `_merge_ranges`/`_in_ranges` 公共化：唯一消费面 12 区间线性扫，收益边际——只落超集注释（5583176）。
- `json.loads(read_text)` ×5：单行重复，不动。
- stagerun TODO×2：活标记，保留。
- SSE 500ms 性能门：刻意 spec 门，观察项。
- 依赖表/web package.json/默认引擎序/PH_RX 形状/TEXLATE_LIVE 门/平台门/conftest helper：核实健康。
- fixloop 程序化交叉验证：36 规则 category 全由 taxonomy 产出、17 builtin+2 rewrite 全命中注册表、无 order 冲突/重复 id；8 taxonomy 无规则承接=刻意留白。
- server 哨兵顺序/done 事件配对/单写者纪律/share 对账/dispatcher 死锁修复/L2 cache 跨线程接线：核实干净。
