# integration-verify — 全链集成终审

> 2026-09-17 收口。只读验证任务，无代码改动。产出 `bench/results/intverify-2026-09-16/`（mock e2e 结果目录）+ `tmp/integration-verify/` 探针与日志。

## 1. 全量 pytest —— 终审 2832 passed / 4 skipped / 0 failed（82.9s）

首跑（~05:14）有 2 失败，定性均为**在飞工作区瞬态**，非落地回归，终审已自愈：
- `test_fixloop_rules.py::test_every_rule_has_provenance` — rules.yaml 新规则 `graphic_ext_relax`（order 14，wave-4 批）缺 `source_ref` 键（只写了 `provenance:`）。05:20:50 被补上（`source_ref: "wave-4 规则批; c6f1511 落地…"`），现过。
- `test_server_sidecar.py::test_index_no_cache` — `GET /` 缺 `Cache-Control: no-cache`；staticfiles.py 当时正被 server-sidecar-audit 编辑（05:16:50、05:20:13 两次 mtime），整文件复跑 14/14 绿。

注：两跑之间 passed 数 2817→2832（在飞代理持续加测试，全绿）。

## 2. mock e2e 烟测 —— 整链无断裂

`uv run python bench/py/e2e_mock_bench.py --limit 2 --conditions base-xel,pipe-xel,pipe-tec,pipeB-xel`：
- 0906.1291 四臂全 **clean**；0807.3917 四臂全 **partial**（non-UTF8 cp1252 + pstricks/eps，base 臂原文即 partial，pipe 臂同档——非管线引入）。
- 管线信号干净：fault_chunks=0、leftover_ph=0；pipeB（~30% Mode B 破坏）verdict 与 pipe 一致 → 校验+fixloop 链完整兜住。fixloop 实证点火（vendored_sty_shadow 隔离旧版 .cls/.sty）。
- 产出 `bench/results/intverify-2026-09-16/`（UTC 日期命名）。

## 3. CLI 烟测 —— 正常

`--help` 8 子命令面齐（version/fetch/parse/run/web/export/doctor/share/tools）；`version`=0.1.0；`doctor` 9/9 ok（xelatex/tectonic/cjk-fonts/gateway 200·214 models/babeldoc 全在）。

## 4. 跨模块接口抽查 —— 三条缝，无集成缺陷

**(a) parse_log 三口径**（`compile/engine.py:290`、`validate/l2.py:413`、`compile/fixloop/logparse.py:76`）：文件栈已收敛到 `texlog.py` 单源原语。探针跑 `bench/work_e2emock` 下 **1070 份真实 .log**，三家 n_errors / first_error / file_stack / popped_files **零分歧**。合成边角两处 l2 偏严（eng/fl 计错、l2 不计）：① 无扩展名 `name:N:` file:line 行（l2 `_FILE_LINE_RX` 要求 `.ext`，l2.py:48-50）；② 消息中段才出现 `Package X Warning` 的 file:line 行（l2 `_NONERR_FILELINE_RX` 在 group3 上非锚定 search，l2.py:56-58；eng/fl 要求 Warning 类名紧跟 `file:line: ` 前缀）。真实语料均未触发，属低风险口径差——l2 是观测面偏保守，eng/fl 是计数门偏宽，方向合理；是否拉齐留档待裁。

**(b) worker↔store files 生命周期**：`store.delete_file`（store.py:772）仅 2 调用点——app.py:1254（换 main retry 清派生产物，跳过 src_tar）与 worker.py:2116（`_invalidate_splice` 摘哨兵后清 `_SPLICE_STALE_KINDS`=zh_pdf/zh_src_zip/dual_json/compile_log/md_zip）。两处都是 `resolve()+is_relative_to(task_root)` confinement + `suppress(OSError)` 删磁盘件，行/盘两层分工一致，无裸删路径。

**(c) export sanitize 链**：`sanitize_xml_text` 单源（export/filters.py:24，XML 1.0 Char 补集），写回点全覆盖——epub.py:850（译文）/900（整篇序列化）/1017（ncx）、docx.py:322；`member_path`（epub.py:296）按 zip 成员字典命中、不触文件系统，traversal 形态天然免疫；`save_epub` mimetype STORED 首位 + 原 infolist 序。

## 结论

集成态健康：终审 pytest 全绿、mock 整链通、CLI 正常、三条跨模块缝一致。无需修复的集成层缺陷；唯一留档项是 parse_log 上述两处低风险口径差。探针与日志在 `tmp/integration-verify/`（probe_parselog.py、pytest-full.log、pytest-final.log、e2emock.log）。
