# 全仓重构侦察 2026-09-19

8 路只读子代理分域扫描（latex / compile+fixloop / server+顶层 / xlat+textutil / validate+arxiv / tests+bench / web / docs），本文件是汇总裁决。结论先行：**清偿顺序应从「同口径散落族」的 quick wins 开始，主菜是抽公共 pipeline core；v1 臂退役是最大的单笔政策决策**。整体结构债已是收尾期而非腐烂期——docs 在案的两轮审计+12-lane 修复波清掉了大拆分包级别的问题，剩下的是未完成的机械拆分、契约未收口和若干政策悬案。

## 一、结构性主菜

### 1. 公共 pipeline core（最高收益，最高成本）

同一条管线契约被接了 4 次：`cli.py → e2e.py` 私有函数（`e2e.py` ~15 个 `_private`，只有 `pipe_condition`/`base_condition` 半公开）、`server/worker/`（独立实现）、`bench/py/e2e_mock_bench.py:290-340` 与 `e2e_real_bench.py:143-190`（import `e2e._scan_tree/_delivered/_env_judge_pass` 并内联重写 `_translate_tree`）。e2e 与 worker 的双写点：`_run_fixloop`（e2e.py:452 ↔ worker/compile.py:509，各 ~90 行同款 flag/dropped/跨引擎逻辑）、`_l2_repair`（e2e.py:386 ↔ `_l2_repair_zh` compile.py:723）、`_delivered` ↔ `_PIPE_TO_DB`、`_baseline_snapshot` ↔ `ctx.base_dir`。一致性靠 docstring「同口径/同位/同款」（~15 处）维持，且已在 compile.py:487 漂移过一次。方向：抽 pipeline-core 模块（ReportSink + CompileRunner protocols），e2e/worker 各留薄适配器；bench 两臂改吃公共 API。前置依赖：worker seam 清理（见三.6）。

### 2. v1 臂退役裁决（最大单笔决策）

`scanner.py`（1799）+ `flatten.py` + `*_v1` 入口 + `model.py` 双臂字段（`ifflags`/`steps` v1-only、`pkgs` v2-only，model.py:221-228）+ ~16 个测试文件（含 `test_fuzz_v1arm`/`test_v1arm_audit`），合计 ~2.3k 产品行。v1/v2 用两种语言（字节偏移 vs token）重实现同一套 dispatch 语义：`_dispatch_cmd`↔`_dispatch`、`_handle_cond`/`_eval_if`↔`gullet/cond.py`、`_find_math_close`↔`_find_math_close_tok`、`_split_core`↔`_split_rendered`——每个语义修复都要写两遍。唯一保留理由=parsebench 对拍 oracle（文档在案 wave2 deferred#1，M3 前须决；scanner 覆盖率 47.5%）。路径：先给 oracle 找替身（v2 快照集或留档 expected），再把 v1 移到 `bench/` 或删除，`ScanState` 随之瘦身。

### 3. segmenter 三面镜像 dispatch 表

同一 §3.2 规则序投影三遍：`mainloop.py:84 _DISPATCH_FAMS`（流）、`pending.py:79 _GRP_SURFACE_FAMS`（组表面）、`pending.py:110 _PEND_SPEC_FAMS`（pending 槽），一致性只靠 `test_dispatch_mirror.py` 钉住；加一行规则要改 3 表 + 3 handler 集。单表 + per-context capability flags 可合并，但三个表面可用操作确实不同——可行、非平凡。附带收益：大量 `# noqa: C901, PLR0912` 随表化一起消掉。

## 二、「同口径」散落族——drift 是定时炸弹

| 复制簇 | 位置 | 现状 |
| --- | --- | --- |
| 日志行词法 ×4 | `l2.py:49-131` ↔ `texlog` ↔ `compile/loginfo` ↔ `fixloop/logparse` | 只靠注释同步；drift 静默翻转 clean/dirty 判定。抽共享 log-lexicon 模块（texlog 是天然家） |
| `glossary_hash` ×2 | `cli.py:1073`（裸 expanduser + ShareError）↔ `worker/share.py:381`（`_glossary_path` confine + fallback） | 语义已分叉——同一任务 CLI/server 打包可出不同 share key。**correctness，最小修复最大收益** |
| placeholder 语法 ×4 | `placeholder.py PH_RX` / `placeholders.py BARE_PH_RX` / `l0 PH_ANY_LIKE_RX` / `export/markers.py MARKER_RE` | 有意的超集关系但调用点无注记；另 `l0.py:92` 字节级复制 textutil 正则、`l0.py:1014` 手写 Counter diff 而非调 `ph_in_cs_net` |
| pipeline 拦截骨架 ×3 | `pipeline.py:362-439` `_intercept_*` + `_ledger_call` ×3（1174/1196/1337） | 已漂移：`"auth_gate.record"` vs `"auth_gate record"`；`_run_ledgers()` + 共享 passthrough-result builder |
| client 传输样板 ×3 | `client.py:910-1012` `list_models`/`panel_models`/`probe_model` | ~60 行同款 httpx→ChatError wrap；`_get_json`/`_post_json` |
| translator 构造 ×3 | `worker/translate.py:519` `_make_translator` / `:559` `_doc_translator` / `compile.py:614` `_llm_hook_pack` | env-force/api_key/model/retry_model 决策链三个变体；一个 `resolve_translator(ctx, kind)` |
| 工具发现 ×2 | `sandbox.find_tool`（sandbox.py:566）↔ `toolchain.resolve_tool`/`find_managed`（toolchain.py:192,201） | PATH→macOS-dirs→managed-dir 语义重叠；归并到 toolchain |
| ChunkResult 映射 ×3 | `pipeline.py:1004-1117` `_emit`/`_load_resumed`/`StateStore.record` 手抄 ~13 字段 | `ChunkRecord.from_result()`/`to_result()`/`as_dict` 单源 |
| Home.tsx 上传 ×2 | `web/src/pages/Home.tsx:178-209` vs `:236-273` | verbatim 重复；`uploadOne()` 抽取 ~60 行 |

## 三、已开始的拆分收尾（C2–C4 mid-flight）

1. `fixloop/builtins.py` facade 还住 ~700 行 graphics/EPS/SVG 实现（`pstricks_dvips_preflight`:213、`eps_to_pdf`:381、`graphic_case_link`:566、`graphic_repair`:664、`includepdf_missing_stub`:713、`svg_prepare`:889 + ~12 私helper）→ 抽 `_builtins_graphics.py` 完成 C3。
2. `_builtins_*` 叶间私名互借：`_builtins_bib.py:19`/`_builtins_shim.py:21` import `_fixloop_log`；`_builtins_shim.py:22` import `_FB_FONT`/`_MATH_SHIM_CS`/`_mc_*` → 归位 `_builtins_common`。
3. `fixloop/__init__` eager 链（顶层 `import fcntl`，POSIX-only）逼出 ~8 处 `# noqa: PLC0415` lazy import（engine×2/probe×2/loginfo×3/sandbox×1）→ PEP 562 `__getattr__` 或把 fcntl 收进函数。
4. `compile/engine.py`（1371）= Protocol + XelatexEngine(:301-865) + TectonicEngine(:880-1155) + routing(:1156-1332) + search-cache(:1333+) → `engine/` 包（fixloop 同款模式）；`LoopCtx` ~52 字段（:316）分 sub-dataclass；`fixloop()` 359 行状态机。
5. `sandbox.py`（944）两融关注点：subprocess runner（`_drain_bounded`/`_kill_tree`/`_RunawaySentry`）vs bwrap/sandbox-exec policy 各 ~470 行 → `proc.py` 分离。
6. `PipelineWorker` 9-mixin（`worker/__init__.py:119`）+ `__init__.py` ~40 个 re-export 纯测试 patch seam + 子模块 `import texlate.server.worker as _w` 运行期回查 → seam 收口到 `worker/seams.py` 或显式注入；是主菜 1 的前置。
7. `app.py` `create_app` 1570 行单函数（:630-2197，~25 端点 + auth/quota 闭包 + 2 middleware）→ routers per domain + AppDeps dataclass；`app.py:149-628` 的 multipart/auth helpers 已是天然 `server/http/` 层。
8. `store.py` Store 45 方法 × 8 聚合 → per-aggregate repos 共享 conn，Store 留组合 facade。
9. `settings.py` 四关切 + 字段知识在写径 `_normalize_updates`(:314) 与读径 `_load_*`(:348+) 双链重复 → 单字段 spec 表；auth/provider  probing 出模块。
10. `cli.py` 1661 全命令+thin-client+doctor → `cli/` 包按命令组拆。
11. `export/epub.py` 1370：sanitize 簇(:984-1140) 是自含 XHTML sanitizer；load/units/insert/serialize 四相 → `export/epub/` 包（`test_fuzz_export.py` 1.9k 行兜底）。
12. 杂项：`xlat/pipeline.py` 的 `MockTranslator`（:226-334 ~110 行）移 `xlat/mock.py`；`rules/90-shim-legacy.yaml` 2283 行占规则库 1/3（观察项）；`segmenter` god-class 按行数机械拆分（mainloop 触 67 个 `self._`），真解耦需显式 state 对象——收益低风险高，可只先归并 `_accent_cs`/`_inline_lit_cs` 两处 verbatim 重复到 `_common.py`。

## 四、层级与边界

- `arxiv/html.py:39-41` 向上 import `latex.placeholder.PH_RX`、`xlat.pipeline.ChunkIn`、`xlat.prompts.normalize_kind`——底层获取层够到解析层和翻译编排层（xlat 反过来消费 arxiv 输出，近环）。`ChunkIn`/`normalize_kind` 移共享 types 位，或 html 出本地 block 由上游转换。
- `TEXLATE_*` env 读取散落 ~15 文件、绕过 `textutil.env_flag/env_str/env_float` 单源，语义已分叉：`toolchain.py:83` 用 `is not None` 使 `TEXLATE_NO_DOWNLOAD=0` 反而开启；`engine.py:326/907/1336`、`settings.py` 6+ 处、`llm_hook.py:349-353`、`cli.py:911-940` 各写各的。合法例外：sandbox env 白名单（sandbox.py:101）、worker env 过滤（l1.py:303）。
- 私名跨界：`meta.py:34`→`fetch._valid_id`、`l2.py:31`→`texlog._ERR_FNAME`、`html.py`→`Fetcher._request`、`retry.py:32`→`batch._abbrev_cut`、bench→`e2e._*`。提 public 或收进共享私有模块。
- `TokenSource` Protocol 名存实亡（`_common.py:456` 声明 4 方法；消费侧 `isinstance(src, Gullet)` ×7 + 直触 `src._q`/`src.macros`，mainloop:483/env:589）。wave2 deferred#8。
- monkeypatch 驱动的环依赖：`segmenter/{group,pending,args}.py` `import texlate.latex.segmenter as _seg` 自我回环只为测试 patch `argspec_lookup`；worker 同款（三.6）。patch 规范家（`latex/tables.py`）或显式注入。
- 命名碰撞：`latex/tables.py` vs `segmenter/tables.py` vs `gullet/tables.py`（re-export shim）；`server/events.py`（SSE bus）vs `worker/events.py`（emitter mixin→建议 `emit.py`）；`share.py`/`worker/share.py`/cli share 命令三层散域；`e2e.py` 的 `mock_*` 命名是历史残留（现为生产 CLI 臂）。

## 五、测试与 bench（重构安全网自身的卫生）

- `_fuzzkit.py` 半迁移：只 ~10 文件用、~29 仍裸 `random.Random(`（含同引 kit 的文件）；findings-writer ×4。机械收尾。
- 事件考古式命名：~55 文件按捕获波命名（`test_server_fixes{,2}`、`test_wave3_lowfixes`、`test_worker_audit_fixes.py` 2543 行 39 个 monkeypatch）；按 concern 重组、拆巨人。
- 无 pytest mark 分层（`slow`/`integration`）；重构迭代期想要快环就加。
- `bench/py` 54 平铺脚本混维护中 harness 与一次性报告；compilebench v2/v3 文件名版本化；可分 harness/report/corpus 子目录。
- 测试套件本身是资产：独立 oracle 密度高（fuzz 文件自带 `_lex`/classifier），conftest 568 行共享 fake 层干净、73 文件复用——正是重构前想要的安全网，不要为「减行数」动它。

## 六、明确不建议动

`textutil/` leaf+facade 有原则且有文档；`xlat` lazy facade、`stores/tasks.ts`（dense 但正确、~5 个测试文件钉住）、`l0.py` 内聚、compile 层 normalize（无条件）vs fixloop（错误驱动）纪律一致、`web/api/` 层、`bench/results/` 划出链外是有意为之。

## 七、文档侧悬案（docs 在案，非新发现）

share 非事务发布窗（share.py:503 自述 rename 不可逆）、`skipped` 双轨改名 ticket（pipeline.py:115-124 status 串与 bool 反向命名）、`llm_hook` worker 侧生产接线待裁、bench 长尾（`triage._read_jsonl:65`/`gate_scorecard:319` 内联读径、e2e_real 标 legacy 未做）。docs 钉行号是持续损耗源——改钉 `file:symbol`。

## 建议顺序

1. **Quick wins（约一周）**：glossary_hash 单源 → env 收口 → log-lexicon → 三处 ×3 复制折叠（pipeline 拦截/client 传输/translator 构造）→ find_tool 归并。顺手消 correctness 风险，为后续热身。
2. **完成已开始的拆分**：builtins graphics 出叶、_builtins_common 归位、fixloop `__init__` lazy、engine/sandbox/store/settings/app/cli/epub 机械拆分——互相独立，可并行分包给多个代理。
3. **worker seam 收口 → 公共 pipeline core**：主菜，做完 e2e/worker/bench 四份契约变一份。
4. **v1 退役裁决**（政策决策可并行酝酿）：先定 parsebench oracle 替身再动手。
5. **segmenter 三镜像表合一**：在 pipeline core 之后做，借重构惯性。
