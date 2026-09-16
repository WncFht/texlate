# clean-clone-2026-09-16：干净 clone 全绿验证

clone=`/tmp/texlate-clean-165302` @ `4b52ef0`（committed HEAD），留档 `/tmp/texlate-clean-165302/verify.txt`。

**`pytest tests/ -q`：1513 passed / 36 skipped / 13 failed**

## [A] 真 breakage（committed 自带守卫缺陷，确定性失败）— 11 条

根因：`.gitignore` 忽略 `bench/corpus/*/`、`bench/corpus_v2/*/` 数据但 MANIFEST.md(+build_corpus.py/manifest.jsonl) 入库 → 目录在干净 clone 上**存在**；守卫写的是 `skipif(not CORPUS.exists())` → 守卫失效、跑空数据 → `assert []`。

- `test_arxiv_locate.py`：test_locate_corpus_v2_all、test_locate_traps×5、test_locate_1502_bare_input_and_bbl、test_locate_wrapper_flag（8）
- `test_arxiv_sniff.py`：test_sniff_corpus_all（1）
- 另两条**完全没守卫**直接 FileNotFoundError：test_pdf_wrapper_detect（corpus_v1/1412.6980）、test_pdf_wrapper_negative（corpus_v2/2210.15358）（2）

注意：这是 standing defect（648212c 把 MANIFEST 入库起守卫即失效），非今日回归。修法=守卫判数据存在（如 `any(rglob("meta.json"))`）而非判目录。→ 任务 #73，guard-fix 在修。

## [B] 需要在飞修复落盘 — 2 条

committed `src/texlate/e2e.py:708` 调 `fixloop(..., compile_timeout=timeout)`，但 committed `fixloop()`（engine.py:869）无此 kwarg → TypeError。`compile_timeout` 是 0fe05c1 加在**调用侧**；形参只存在于工作树在飞版 engine.py:973（项目体验方式 fixloop 批）。

- test_e2e.py::test_pipeline_run_repair_chain_fail
- test_e2e_wiring.py::test_fixloop_runs_on_fail_and_recovers

## [C] 环境依赖：0 条

## ruff（committed HEAD）

- 任务口径 `src/`：`ruff check` 全过；`ruff format --check` 75 文件全 formatted。
- 全仓附加：`ruff check .` 2 errors，均 committed 状态且文件不在飞——`bench/corpus_v2/build_corpus.py:449` RUF100 陈旧 noqa；`tests/test_xlat_prompts.py:107` PLR2004 `== 0.01`（随 #73 同批修）。`ruff format --check .` 9 文件：8 个 docs/*.md 在链外（md 归 prettier/autocorrect，不算缺口）；1 个真在链 miss=tests/test_app_endpoints.py，app-polish 在飞版已重排并随 `9368872` 落盘。

## 结论

committed HEAD 未兑现「干净 clone 全绿」——13 红中 11 是 committed 守卫缺陷（standing），2 在等在飞 engine.py 参数落盘；src/ lint/format 干净，全仓另有 2 个 committed lint error（已派修）。
