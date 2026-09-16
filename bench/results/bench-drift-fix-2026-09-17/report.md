# bench-drift-fix — e2e_mock_bench 漂移修复交付

> 2026-09-17 收口。落地 `d240b43`（bench/py/e2e_mock_bench.py，+38/-24）。leader 复核 diff 与报告逐条吻合。探针 `tmp/bench-drift-fix/`（gitignored）。

## 改动（对照 src/texlate/e2e.py 原件逐门核对）

1. `translate_tree` — 扫描段改为直接调 `e2e_mod._scan_tree(root)` 原件（dotfile/.rtx.tex 静默跳、.code.tex/无散文记 support_files、is_file、suffix.lower() 四门单源化，不再镜像副本）；翻译段镜像 `_translate_tree`：补 `glossary=Glossary.load(placeholders=collect_doc_placeholders(...))` + `cache={}`，stats 补齐 `partial_chunks`/`support_files`/`support_skipped` 三键（与产品 stats 同形）。相应删 `parse_file`/`ChunkIn`/`chunk_to_in` 导入，加 `Glossary`/`collect_doc_placeholders`。选复用 `_scan_tree` 而非独立副本——本文件已深度依赖 e2e_mod._* 私有面，复用消漂移面且 docstring 已注明镜像源。
2. `pipe_mode_condition` — `expect_cjk` 提升为变量（= `stats.get("chunks") != 0`，同 pipe_condition:929）；`_run_fixloop` 调用补 `timeout=job.timeout` + `expect_cjk=expect_cjk`，返回值 `_last` 改回 `res`；并补上缺失的 ToUnicode 尾段（`res.has_pdf → rec["tounicode_fonts"] = e2e_mod._embed_tounicode(res.pdf)`）——审计两条目外发现的第三处小漂移，按同构目标一并修。

## 自验

- 探针 tmp/bench-drift-fix/probe_gates.py：合成树实证 UPPER.TEX 进 scan、.hidden/.rtx.tex 静默跳、tikz.code.tex+纯宏 macros.tex 进 support_files、名为 dir.tex 的目录被 is_file 跳过（旧径会记 fault）、chmod000→fault_files；glossary/cache 实接（cache 有条目证明缓存路活着）。
- 探针 probe_fixloop_args.py（monkeypatch 编译三缝）：捕获 `_run_fixloop` 实收 timeout=240.0(=job.timeout)、expect_cjk True（有散文）/False（0-chunk 空文档）；fixloop_on=False 路径完好。
- pytest tests/test_e2e{,_wiring,_mock}.py + test_bench_harness.py：47 全过。
- 真机冒烟 `--limit 1 --conditions pipeB-xel,pipeC-xel`（0807.3917）：两臂全链跑通→partial，fixloop verdict=best_effort_pdf、tounicode_fonts=3、新 stats 键齐。冒烟产物已自清。

## 外路由注记

报告时 flag 的「pipe_condition e2e.py:949 仍不传 timeout」经 leader 复核已由 1d `aaf6b28` 落地（:953-958 `timeout=job.timeout`+`expect_cjk` 均在）——staleness 回声，无遗留。
