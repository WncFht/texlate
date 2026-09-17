# normalize-fuzz — compile/normalize.py 对抗性 property tests

> 2026-09-17 收口。交付 `tests/test_fuzz_normalize.py`（~1200 行，commit `ce8e48f`）：**10 passed + 10 xfailed(strict)**，ruff check/format 双净。种子随机性质套件：随机工程树 × 字节载荷矩阵 + 性质不变量。kpsewhich 遮蔽臂在性质循环关停（host 依赖非确定），独立钉覆盖。

## 核心不变量（oracle）

- `normalize_engine`：返回 str、幂等、删除类编辑行数不减、xelatex/tectonic 源无 pdfTeX 输出控制/inputenc/fontenc/CJK 环境/非法驱动 token（遮盖区合法残留）。
- `normalize_project`：任意字节载荷不炸；写回件必 strict-UTF-8；二进制 allowlist/软链/DOS-EPS 魔数件逐字节不动；隐藏路径件非手术面不动。
- `.aux` 系：在场 ⇒ 空或 `\n` 收尾；缺席 ⇒ 落 `purged_intermediates`。
- `aipcheck.tex` 逐名 stub（区分大小写）；PS 臂行数不减、数据段逐字节保留、atend 占位头行改写末实值。
- stats 键全集台账；二跑幂等（rewritten==0、零改写台账、全树字节同）。

## 确认缺陷（strict-xfail 钉住，`--runxfail` 验证）

| # | 缺陷 | 位置 | 复现/影响 | 严重度 |
|---|------|------|-----------|--------|
| 1 | bbl-splice 跨 run 累加 | normalize.py:686-697 `use_bundled_bibliography` | 只替换首个 `\bibliography{}`——同文件两只缺库 + bundled `.bbl` 时每跑再换一只，终态 N 份 `\input{x.bbl}` = docstring 明令避免的重复排版 | 中（worker/e2e 重试会同树重跑 normalize） |
| 2 | `group_end` 递归爆栈 | mask.py:60，经 `\pdfinfo{`(467)/`\DisableLigatures{`(313)/`\documentclass{`(~604) 可达 | ~2000+ 嵌套 `{` → RecursionError 整单崩 | 低-中 |
| 3 | NUL 包名 → `ValueError: embedded null byte` | `_kpse_resolve` normalize.py:1108 catch `(OSError, SubprocessError)` 漏 ValueError | `\usepackage{a\x00b}`，kpsewhich 在场 + xelatex/lualatex 可达 | 低 |
| 4 | 只读输入 → PermissionError 半程崩 | write_text normalize.py:1272、purge unlink :1007 无 OSError 守卫（`_neutralize_junk_files`:806 同型写有守卫——不对称） | 0444 `.sty` / 0555 目录含可清 `.aux` → 留半归一化树 | 低-中 |
| 5 | 隐藏路径不对称 | `_transcode_support_files`:1056 豁免 `.` 前缀，但主环/junk/rebase/`source_path_violations`/legacy-latin 臂全不查 | `.git/evil.tex` 含 `\input{/etc/passwd}` → 转码改写 + violation 误报拦编译 | 中（arXiv tarball 带 VCS 残渣） |
| 6 | 手工 splice 丢内嵌换行破行数不变量 | `normalize_pixel_dimensions`:374-382（`5\npx`→`5\pdfpxdimen`）、`normalize_legacy_cjk`:657-665 | 未做 apply_edits `\n` 补偿 | 低 |

## 非钉观察项（未断言，值得复查）

- `.ltx` 仅 bbl 臂排除（:1267），其余 doc_source 臂仍收。
- PS 件 NUL 密集 `%` 注释行可解为 utf-16 → 注释翻代码（`_sanitize_ps_comments`）。
- `%%Begin*` 无 `%%End*` → 尾部注释全失净化。
- PS 注释内 mid-line `\r` → 输出行数增长。
- `encodings` 台账记录后被 purge 的中间件。
- 包名 glob 元字符（`a*b`）→ `_try_shadow` rglob 误命中。
- 含 `\begin{document}` 的 `.sty` 被注 doc 级兼容块。

## 会话插曲

交付前文件曾含 collection 杀手（`_LATIN1` em-dash 非 latin-1 可编码），leader 直修（`—`→`-`）解全员 pytest 收集阻断，已并入交付版。
