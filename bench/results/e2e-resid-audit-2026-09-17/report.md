# e2e-resid-audit — e2e.py 只读残件审计

> 2026-09-17 收口。只读任务，零代码改动（e2e.py 归 texlate-1d lane，发现全部外路由）。探针 `tmp/e2e-resid-audit/`（gitignored）。

## 确认缺陷（已转 1d lane）

### F1 `_l2_parse` 存在但空的 .log 直返 0 错、永不退 `stdout_tail` —— 中
`src/texlate/e2e.py:395-401`：`res.log_path.exists()` → `l2_mod.parse_log` → 空文本进 `parse_log_text("")` → `log_missing=False, n_errors=0`。`_l2_localize` 随即 `return {}, 0` → `_l2_repair` 报 "no chunk-level attribution"，**整个 L2 臂静默空转**。OSError 子情形同理（`parse_log` 内部返 log_missing，stdout_tail 兜底分支够不到）。

实证（tmp 探针）：空 `main.log` + `stdout_tail` 含 `! Undefined control sequence.\nl.5` → `_l2_parse` 返 `log_missing=False n_errors=0`；`log_path=None` 的对照臂正确消费 stdout_tail。

引擎层 HEAD 已修同款：`engine.py:1421`/`1673` 都是 `parse_log(text or res.stdout_tail)`。修法：`_l2_parse` 自己 `read_text` 后 `text or res.stdout_tail` → `parse_log_text`，双空才 `log_missing`。注意 `_l2_localize`/`_l2_parse` 是 worker 共享函数（worker.py:80 import）——**e2e 修一处，worker L2 归因同愈**。

### F2 `judge()` 全程不传 `log_text` —— 中低
`e2e.py:379`（`_compile_judge`）与 `:834`（`_run_fixloop` 终判）都是裸 `judge(res, expect_cjk=…)`；worker 每个判定点都传 `log_text=self._log_text_of(res)`（worker.py:2715，.log 缺席退 stdout_tail）。

实证：CompRes(pdf 非空, log_path 存在但空, stdout_tail 含 2 行 Missing character) → e2e 口径 `missing_chars=0 reasons=['warn:missing_chars']`；worker 口径 `missing_chars=2 reasons=['warn:missing_chars','missing_character×2','cjk_unverified+missing_chars']`。`res.log` 引擎层已兜底所以 `warn:missing_chars` 红线仍命中、status 不翻——但 `missing_chars` 计数、`missing_character×N` reason、`cjk_unverified+missing_chars` 升级信号全丢；非 "There is no" 形制的 missing-char 行（红线 pattern 比 `count_missing_chars` 窄）会真翻 status。修法：e2e 加 `_log_text(res)`（存在→读，空/缺席/读失败→`stdout_tail`）并两处 `judge(…, log_text=…)`。附带：worker `_log_text_of` 有 exists-but-empty 同洞（读到 "" 直返，judge 复读同一空文件，stdout_tail 仍摸不到）——共享 helper 或 worker 侧顺带 `or res.stdout_tail`。

## 口径漂移（已转 1d 裁决）

### F3 `_run_fixloop` 不透传 `job.timeout` —— 中
`e2e.py:929-931` 调用无 `timeout=` → None → rules.yaml `meta.loop.timeout_sec=120`；而 `job.timeout`（bench `--timeout`/CLI 默认 240，=worker `COMPILE_TIMEOUT`）管其它所有编译。worker 侧 `compile_timeout=self._compile_timeout`（worker.py:2767）。后果：121–240s 才能编完的文档，首编过、fixloop 内重编超时 → verdict 反而劣化。修法：调用点加 `timeout=job.timeout`；`bench/py/e2e_mock_bench.py:518` 的 `pipe_mode_condition` 同款漏传。

### F4 fixloop 引擎 `halt_on_error` 两侧相反 —— 需裁决
e2e.py:814 `engine_for(job.eng_name)` 新造 → xelatex `halt_on_error=True`（docstring 声称 "fixloop 首错分类语义"）；worker `_run_fixloop` 复用 `_engine(ctx)` → xelatex `halt_on_error=False`（nonstop best-effort，worker.py:2601）。fixloop 每轮重编看到的错误面不同（首错即止 vs 全程错误集），分类输入不同。哪侧是权威语义需裁决——e2e 的 docstring 像有意，worker 像顺手复用。

### F5 `pipe_condition` 裸调 `_l2_repair` —— 低中
`e2e.py:916` 无 try/except；worker `_l2_attempt` 包了（worker.py:3121-3125，崩→记 log→继续 fixloop）。L2 崩（`file_state` 读盘、`asyncio.run` 等）会把整条 rec 炸掉——bench `run_project`（e2e_mock_bench.py:859）case 级 catch 兜底但该 cond 记录全失，连已拿到的首编 verdict 都丢。同文件 `_run_fixloop` 内部却包了 except（e2e.py:815-824）——两臂不对称。修法：仿 worker 包一层 → `rec["l2"]={"enabled":True,"error":...}`，以修复前 `res` 继续 fixloop。

### F6 首编缺 `target_probe` flags —— 低中
worker `_compile_zh`/`_compile_en` 首编前 `target_probe` 并传 `flags=rep.flags`（minted → `-shell-escape`，probe.py:267）；e2e `_compile_judge` 无 probe 段。minted+xelatex：worker 首编即过，e2e 首编败 → 白烧 L2+fixloop，verdict 路径分叉。若属有意 bench 简化请在 docstring 记一句；否则 `pipe_condition` 首编前接 `target_probe`。

## Cosmetic（转 1d）

- `_scan_tree` `fault_files`/`support_files` 记 `f.name`（basename，e2e.py:217/222/225）；worker 记 `rel`（worker.py:1835/1845）、stagerun parse_fail 记 `relative_to`。同名不同目碰撞歧义。建议 `f.relative_to(root).as_posix()`。
- `mock_pipeline_run` route-reject/no-main 两路（e2e.py:979-991）不落 `verdict` 键，inject-reject 路却落（:905）——消费端 `.get` 兜住没炸，报告形状不齐。
- l2/fixloop 关闭时 `reason` 记的是 env 名串（"TEXLATE_NO_L2"），worker 记描述性值（"share_zero_token"/"options.l2"）——微观漂移。

## 已核实非缺陷（线索复核结论）

- `_scan_tree` 四门：dotfile/`.rtx.tex`/`.code.tex`→support/`file_has_prose`→support + `is_file` + `suffix.lower()==".tex"` 全在（e2e.py:209-226），与 worker `_parse_all` 同构。
- `_env_judge_pass`：`parse_env_judge_answer` 已在重试域内（:154），fail-open `return True`；`asyncio.run` 在 HEAD 安全——全部调用点是 sync（cli.py:336 typer、run_condition、worker `_env_judge_filter` 在 `asyncio.to_thread` 线程）。
- `_slim_cell`：salvage 轮（`"salvage" if r.get("salvage")`）+ setup（round 0/-1）已拆（:746-787），与 worker `_fixloop_summary` 同构。
- `_l2_repair` 硬编码 `expect_cjk=True`（:692）**是 vacuous 非缺陷**：hits 非空 ⟹ chunks>0 ⟹ `pipe_condition` 的 expect_cjk 本就是 True；0-chunk 文档没有任何可归因块，走不到重编行。（但 bench `pipe_mode_condition` 调 `_run_fixloop` 漏传 `expect_cjk` → 默认 True 会污染 0-chunk Mode B/C 终判 tail——`_run_fixloop` 的 tail judge 无条件跑，与 hits 无关。bench 侧小坑。）
- `_expand_tokens`/`_chunk_spans` 与 `reconstruct.expand` parity：short_arg 折叠只对已译非 para/item 块（reconstruct.py:193-196 同则）、`glue_latin` splice 路恒真、ph_map→content 优先级与 dangling 字面保留一致；`Chunk.id`==位置下标（segmenter.py:685 `cid=len(chunks)`）。
- `retranslate_chunk` 只产 ok/fault/None（pipeline.py:702-759），`_retranslate_hits` 采纳域正确；传输异常→`kept_transport_err` 优雅降级。
- httpx.AsyncClient 跨 `asyncio.run` 复用实证无害（keep-alive 池自动重连）——L2 复用 `run.pipe.translator` 不炸。
- fixloop `cond`/`corpus_id`/`case_sink` 只进 cell 记账，e2e 不传无语义差。

## bench 侧附带（bench-harness 后续 agent 收编）

- `e2e_mock_bench.translate_tree`（:296）是 `_scan_tree` 的漂移副本：`rglob("*.tex")` 大小写敏感（漏 `.TEX`）、无 `is_file`、无 dotfile/`.rtx.tex`/`.code.tex`/`file_has_prose` 门、pipeline 缺 `Glossary.load(placeholders=…)` 与 `cache={}`——Mode B/C 臂量的管道与 `pipe_condition` 不完全同构。
- `stagerun.py:644-656` 同款 `rglob("*.tex")` + `f.name.endswith(".rtx.tex")` 未 lower——`.RTX.TEX` 会漏进翻译集（e2e/worker 都 lower()）——peer1 飞区，已转告。
