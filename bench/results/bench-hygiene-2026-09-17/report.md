# bench-hygiene — bench/py 残余审计报告

> 2026-09-17。Scope：bench/py 全量 .py 除 stagerun.py / gate_scorecard.py / e2e_real_bench.py（在飞只读）与 scratch/。另含 bench/corpus_v3/select_booster.py。

## 改动清单（12 文件，全为小修）

**死代码删除（4 处，AST 全量扫 + 交叉 grep 零调用实证）**

- `bench/py/benchlib.py` — 删 `done_keys`（全仓零调用；续跑谓词已被 stagerun 的 (id,arm,upstream) 复合键 + load_records/末条胜取代）
- `bench/py/plastex_bench.py` — 删 `is_math`（提取走 is_protected_ancestor 内联 MATH_TAGS，函数从未接线）
- `bench/py/texsoup_bench.py` — 删 `text_of_arg`（零调用）
- `bench/py/validbench.py` — 删 `_live_positions`（零调用；`_live_insert_positions` 是活变体）

**路径漂移修复**

- `bench/py/ieeA_bench.py` — `BENCH = Path("/Users/fanghaotian/src/texlate/bench")` 硬编码 macOS 路径 → `Path(__file__).resolve().parents[1]`；report `lib_path` 同款硬编码 → `Path(ieeA.__file__).parent.parent` 实取；`"date": "2026-09-14"` 硬编码 → `time.strftime`
- `bench/py/export_realbook.py` — `OUTDIR = Path("bench/results/...")` CWD 相对 → 锚定 repo root（`parents[2]`），与其他脚本一致

**python3 vs uv run 标注修正（实测依赖链核实：texlate.arxiv.__init__→fetch/meta→httpx；texlate.compile.engine→toolchain→httpx；texlate.xlat.pipeline→client→httpx）**

- `bench/py/e2e_mock_bench.py` — 用法 `python3` → `uv run python`（模块级 texlate.e2e→xlat.client→httpx；CLAUDE.md 明列本脚本须 uv run）
- `bench/py/translators_bench.py` — 自检 `python` → `uv run python` + httpx 原因注记（模块级 texlat.xlat.pipeline）
- `bench/py/build_corpus_expand.py` — "纯 stdlib/系统 python3" 声明补 extract 例外：materialize 走 b3.unpack_blob → texlate.arxiv（无 src shim + httpx），须 `uv run`
- `bench/py/compilebench_v3.py` — "Deps: stdlib only" 修正：--gen-sample/--report 仍 stdlib-only；跑样本路径 lazy-import engine→toolchain→httpx，推荐 `uv run`

**docstring 漂移补登（真子命令/模式未列）**

- `bench/py/build_corpus_v3.py` — 用法补 `extract-booster`（cmd_extract_booster 实接线）
- `bench/py/bench_pylatexenc.py` — Usage 补 `damage` 模式（run_damage 实接线）

## 验证

- `python3 -m py_compile` 全 12 文件过；`uv run ruff format --check` + `ruff check` 动的文件全绿（残余 2 errors/2 未格式化全在 gate_scorecard/stagerun 在飞面，未碰）
- 冒烟：`uv run python bench/py/translators_bench.py` 自检 PASS（sabotage-b ledger n_events=63/escaped=0 + perturb spliced=5）；`triage.py --selftest` PASS（验证 done_keys 删除无回归）；e2e_mock/expand/cbv3/validbench `--help` 全过

## 审计确认无问题面

- **CLI 参数**：AST 全量扫，零未接线参数
- **静默吞错**：38 处 except 全过手——全部是记录进结果 dict（bench 语义）或有文档化 fallback；triage `_read_jsonl` 坏行带 stderr warn
- **records schema**：stagerun 写 `{id,stage,arm,upstream,status,dur_s,metrics,errors,sig}` 与 triage/rundiff 读端逐字段对齐；`metrics.compile_status_before`（fixloop_degraded 探测依赖）实证存在于 loop1 fixloop.jsonl；`floor_restored` 在写
- **benchlib 单源**：copytree_ignore（4 处）/TUNA_TLNET（2 处）/jsonl 原语均正确复用；triage 自有 `load_records` 是不同签名（results_dir→list），非重复实现
- **sys.path shim**：TEXLATE_SRC 惯例一致（stagerun/e2e_mock/e2e_real/preflight/alignbench 同款）
- **私有 API 漂移**：l2_attr_probe 的 e2e 内部件（_TreeRun/_L2Attr/_l2_parse/_resolve_fidx/常数）全在；gullet_bench 探针点（_invoke/_eval_if/process_if）签名兼容
- **runbook_loop.md** 命令行与现行一致

## 留观未修（确认非本 scope 或有因）

- `qualbench/xlatbench/stagerun --api-key 240127` 默认值——内部网关既定惯例（多处已入库），非新泄
- `l2_attr_probe` 钉死单一 run 目录（e2e-real-n100-postcutover）——docstring 明示一次性探针
- `~/.cache/texlate/src` 字面量在 cli.py `_DEFAULT_CACHE` 与 build_hot_layer `CACHE` 双写——单源化需动 src/ 产品侧（只读面），量小不值当
- `texsoup_diverge.py` 一次性 spike 分析脚本——保留原样
