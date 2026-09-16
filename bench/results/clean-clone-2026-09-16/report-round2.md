# clean-clone 收口复验（round 2，2026-09-16 晚）

> fresh clone `/tmp/texlate-verify-175123` @ `18ff106`（距首轮 4b52ef0 共 36 commit）。首轮留档 verify-round2.txt（/tmp，易失）。

## pytest：1538 passed / 48 skipped / 1 failed

首轮 13F 全清——11 条 corpus-guard 由 `6e2659a` 修好正常 skip，2 条 compile_timeout 由 `3c5aae2` 落盘自愈。

**新红 1 条 = committed test/rules desync**（真 breakage，非在飞）：
`test_engine_fp.py::test_tail_aastex_banner_not_latex209` 期望 `early_eof` 实得 `missing_file`。根因：rules.yaml cls-plea tail 规则（missing_file，pattern 匹 "…to include revtex4-1.cls"，guard "No pages of output"）有意排在 early_eof 之前，证据正是这条 aastex61 横幅尾；规则随 `18ff106` 落地但断言没跟着改。
**已修**：`97b1b4c`——断言改 `missing_file` + docstring 记 plea 路由优先口径。

## ruff

- src/：check + format 全净（75 文件）。
- 全仓 check：12 errors 全集中 `scripts/tcp-relay.py`（首轮时 ?? 未跟踪，`8314efd` 入库后 select=ALL 全咬：ANN201×3/D103×3/ANN001×4/T201/PLR2004）。**已修**：`27fa32d`——补标注/docstring/stderr/命名常量。
- 首轮 2 个（build_corpus RUF100、test_xlat_prompts PLR2004）已被 guard-fix 批清掉。
- 在链 format = 净（docs/*.md 8 文件属链外，hook types:[python]）。

## 结论

`18ff106` 经 `97b1b4c`+`27fa32d` 两补丁后回到「干净 clone 全绿」口径。首轮报告项全部解决。
