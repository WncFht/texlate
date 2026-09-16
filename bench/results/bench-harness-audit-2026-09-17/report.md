# bench-harness-audit — bench/py 评测 harness 交付

> 2026-09-17 收口。落地 `3cbf419`（15 个 bench/py 脚本 + tests/test_bench_harness.py 新建 9 例，+507/-152）；gate_scorecard.py 的 4 项修复已随 `932157a`（overseer arm-partition 提交）先行落地，本批内容在 HEAD 复核齐全。leader 复核 test_bench_harness+triage+rundiff+regression+engine_judge+align 219 绿 1 skip。stagerun.py/fixloop_bench.py 为 peer 飞区只读未动。探针 `tmp/bench-harness-audit/`（gitignored）。

范围：bench/py/ 评测 harness 脚本（语料数据不审）。方向：计数/归因、评分口径、数据完整性、边界、接口漂移。方法：通读 → 假数据探针实证崩溃 → 修在范围内缺陷 + 补测试。stagerun.py/fixloop_bench.py 飞区只读未动。

## 已修（探针实证崩溃的全部复现→修复→复绿）

**gate_scorecard.py**（随 932157a 落地）
- `total==0`/`n_norej==0` → ZeroDivisionError（实证）。加 `cells=0` 早退 + n_norej 守卫。
- need 公式 `int(total*GATE)-pdf+1` → `max(0, math.ceil(total*GATE-pdf-1e-9))`（实证 89/100 格误报 need+2，应为 +1：int() 截断 + 恒 +1 双 bug）。
- `r["status"]` → `.get("status") or "?"` 缺键容错。
- pick_final 增 upstream_mismatch：compile/fix 行 upstream 不一致 → 该 fix 作废（实证 u1 编译行 + u2 fix 行被计 fixloop:clean）。注意 peer 后来给 last_records 加了 upstream 过滤（默认 "mock"，防双臂波次串账），本检查在主流程已冗余，保留为直接调 pick_final 时的防御层。

**benchlib.py**
- `judge_dict` verdict 补 `warnings_hit` 字段（对齐 e2e._tail_dict 形状，verdict_sig 派生一致）。
- 新增 `atomic_write_text(path, text)`：同目录 .tmp + replace。

**e2e_mock_bench.py**
- 抽公共 `seed_results(rec_path, out_path)`：results.jsonl 存在但全坏行/空 → 回退 results.json 快照（原逻辑"账在=不回退"，快照永远丢）；json.loads 加 guard + isinstance dict。
- results.json 落盘改 atomic_write_text。
- run_project 包 try/except → 单篇崩记 `bench_error` 行（与 e2e_real 同口径），不再炸整批；合并时成功 rec 清掉陈旧 status/error 残键防 bench_error 粘滞。

**triage.py**
- SKIP_STATUS 补 `skipped_oversize`/`bench_error`（e2e_real 旧账词经 LEGACY_ARM_MAP 流入 triage）。
- pipeline_introduced 判据补 `zh not in OK|SKIP|{"error"}`：上游门/policy拒/harness崩 不再误报"管线引入"。

**compilebench_v3.py**
- report() cases.jsonl → `benchlib.read_jsonl`（实证截尾行 JSONDecodeError 崩）。
- resume done-set → iter_jsonl + `pid and eng` 双键守卫（单键缺失不再污染 done）。
- `n_papers==0` ZeroDivision 三处（实证）→ pdf_pct/clean_pct 条件变量。
- v2 对比 `if r2 and c3:` 防空行。

**compilebench_v2.py** — report() + resume done-set 同款 iter_jsonl 容错。

**xlatbench.py** — resume / rejudge / aggregate 三处裸 json.loads → iter_jsonl/read_jsonl。

**validbench.py** — replay 读 → read_jsonl。

**gullet_bench.py** — fp 重喂 `expand_all` 加 try → `row["fp"]=f"refeed_err:{e!r}"`（原文档一崩整跑挂且 resume 因无行写入死循环）。

**build_corpus_v3.py**
- fetch_one：final 存在但尺寸错且无 .part → 原逻辑拿错尺寸当 `have` 续传进 fresh .part → 永假 size mismatch/verify 失败死循环；改为 unlink final + have=0 重抓。
- save_chunks / manifest.jsonl / manifest_booster.jsonl → atomic_write_text。
- features / booster_selection / wanted-member / feats_by_cluster 四处读 → iter_jsonl/read_jsonl。
- booster `raw_name` dict → `.get(fmt, "raw.bin")`（B07 池设计含 format=error 成员，原 KeyError 可达）。
- load_frame_lookup TSV 截尾行 `len(parts)<6` guard。

**build_corpus_expand.py**
- 新增 `manifest_row_from_meta(dest)`：从 meta.json 合成 manifest 行（重算 main_tex_sha256）。
- cmd_extract：meta 在 manifest 缺 → 回补行（原永久缺口）；meta 坏/缺 → 落回重抓自愈。
- chunk_yield_by_band / scan_item done_members / select_members / offsets_for 四处 → iter_jsonl（实证：截尾行致每次 rescan 永崩同一 item）。
- RAW_NAME 补 `"error": "raw.bin"`；save_plan / select_stats → atomic；frame_filter TSV guard。

**build_hot_layer.py**
- cmd_fetch：extracted/ 在而 manifest 缺 → 解析 meta.json 回补 manifest 行（原永久跳过且残缺树被当完成）；meta 坏/缺 → 落回重抓。
- candidates / manifest / cmd_report 读 → read_jsonl/iter_jsonl。

**parsebench.py** — aggregate `recon` 缺 identity 键 guard。

**l2_attr_probe.py** — rows_out/cases_out 改 `with` + write_jsonl 逐行 flush（原中途崩丢全部缓冲）；`r["translation"]` → status==ok 且非 None 才进 trans。

**qualbench.py** — `payload["choices"][0]` 边界：非 list / 空 / 元素非 dict → 空内容降级不崩。

**alignbench.py** — pairs_from_manifest → iter_jsonl + `a`/`b` 缺键 guard。

## 新测试

`tests/test_bench_harness.py`（9 例，全过）：benchlib torn-line/atomic_write/judge_dict verdict 形状；gate_scorecard need 公式（89→need 1）+ upstream_mismatch + empty；e2e_mock seed_results 账坏回退快照 + bench_error 合并清残键；compilebench_v3 torn cases + need；fetch_one 坏尺寸 final 重抓；manifest_row_from_meta 合成。

## 自验

- `uv run pytest tests/test_bench_harness.py test_bench_triage.py test_bench_rundiff.py test_bench_regression.py test_compile_engine_judge.py test_align.py` → **219 passed, 1 skipped**
- `uv run ruff check bench/py/ tests/test_bench_harness.py` → clean（新测试补了公开名/常量/lambda 签名过 tests 严格档）
- py_compile × 全部触动文件 + import smoke → OK
- `triage.py --selftest` rc=0；`translators_bench.py` selfcheck ok；`alignbench.py --selftest` PASS（写 bench/results/alignbench-selftest-2026-09-16/）
- 探针现场保留 `tmp/bench-harness-audit/`（gitignored）：gate×4 + cbv3×3 均实证 崩→修→绿。

## 未修（report-only）

飞区只读（stagerun/fixloop owner 路由）：
- `fixloop_bench.py` unguarded json.loads ×4（406/436/452/814 行附近）——账截尾即崩，与本次修的同款缺陷。
- `stagerun.py`：compile resume 键 (id, arm, upstream-name) 不核树内容 → xlat --rerun 换树后 compile 旧 zh 记录仍判 done 跳过（归因错）；`_ON_PRED["all"]` 含 error 格；stage_parse `shutdown(wait=False)` race；make_sig status 形参未用；chunk_id `int()` ValueError 无 guard。

非飞区但定界为语义/边缘（改了会动口径，留给 owner 决策）：
- compilebench_v3：no_main_tex/no_source 论文零 case 行 → per-engine 分母不含它们，pdf% 分母(n_papers)与 case 分母不一致（口径注释级）；cells.json 增量写非原子（读侧 suppress 自愈，优先级低）。
- build_corpus_v3 verify_chunk 双重整文件 read_bytes（GB 级 RAM×2，流式 hashlib.file_digest 更好）；extract manifest 全量内存末写（幂等重跑自愈但慢）。
- build_corpus_expand fetch_blob Range 被服务端忽略时整 tar 进 RAM；largest_remainder rel>2 负 quota 边角。
- qualbench per-paper 报告行标 first-seen model——多模型同论文错标（语义级）。
- e2e_mock 无 resume-skip（全量重跑是设计，但注意 records.jsonl 单调膨胀）。
- triage 读 metrics.jsonl 与 records 时点不原子（staleness 窗口）；多 upstream 同案计数塌缩；fixloop clean 判定未核 clean-sig——三处均为口径注记，未改。

## 外部路由

- `src/texlate/e2e.py` `_tail_dict` verdict 缺 payload 键（产品侧）：benchlib.judge_dict 有 payload，verdict_sig 派生 cat 时 e2e 侧记录配错风险——产品代码 owner 决定（e2e.py 归 texlate-1d lane，已转告）。
- 飞区两项见上（fixloop_bench ×4 / stagerun ×5）——已归 peer 项目体验方式 lane。
