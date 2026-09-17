# gated-retire — NEED_LOGS gated 用例收编进 manifest fixtures 交付

> 2026-09-17 收口。仅动 `tests/test_validate_l2.py` + `tests/test_fixloop_spikereplay.py` 两文件。自验（配额故障前完成）：`pytest` 三文件 39 绿、ruff 净；探针证据 `tmp/gated-retire/`。

## test_validate_l2.py

删除 5 个 NEED_LOGS gated 块（断言全部被 fixtures/logs/manifest.json 行或常跑 fixture 测试收编）：

- test_real_log_clean → xelatex-clean-warnings.log 即同源件（work_compile/1512.03385/.../residual_v1_arxiv_release.log）：ok=true、n_errors=0、first_error=null
- test_real_log_warnings_classified → tectonic-citation-warn.log 行：by_class_min citation≥5/reference≥1/generic≥1；total>0 另由 test_verdict_serialization 覆盖
- test_real_log_cjk_missing_glyph_redline → xelatex-cjk-missing-glyph.log 行断言逐字等价
- test_real_log_invalid_utf8_redline → xelatex-utf8-redline-project.log + xelatex-inputenc-fffd.log（invalid_utf8/fffd_glyph 双红线）
- test_real_log_first_error_ctx_and_stack → ctx≤8（missing-file fixture 测）+ l.N-in-ctx（fileline fixture l.24）+ stack_suffix（manifest 全行）

保留 1 个 gated 块、门收窄 NEED_LOGS(五件合取) → NEED_ERR_LOG(单件) + 缺口注释：

- test_real_log_bang_count —— `^!` 格式错 tex_line 走 ctx `l.N` 兜底（_tex_line_from_ctx）的唯一断言面。已核实 manifest 无覆盖：全部 first_error.tex_line 出自 `file:line:` 格式，`^!` 首错一律 null。同步移除闲置 _WARN_LOG/_CLEAN_LOG/_CJK_LOG/_UTF8_LOG/_REAL_LOGS 常量，模块 docstring 已更新。

## test_fixloop_spikereplay.py

_FIXTURE_CATS 改 Path 键：13 行由 tests/fixtures/logs/manifest.json fixloop{n_bang,category,payload} 模块级派生 + 2 件顶级 legacy fixture 保持手写（在 logs/ 外）。test_fixture_logs_classify 覆盖 2→15 个 log；docstring 更新。模块级 json.loads 与 test_l2_real_fixtures.py 同例（manifest 入库常在）。

## 自验

`uv run pytest tests/test_validate_l2.py tests/test_fixloop_spikereplay.py tests/test_l2_real_fixtures.py -x -q` → 39 passed（前 44=23+3+18；后 39=18+3+18，classify 内覆盖 2→15）。本机 bench/work_compile 在场，保留的 gated 用例实跑非 skip。ruff check + format --check 净。
