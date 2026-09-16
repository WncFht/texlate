# live-smoke2 真网关活烟报告 — 整链通（partial），抓到 2 个 bug（1 个是今日回归）

论文 cond-mat/0408438（corpus_v3 双臂 clean 的小篇，8 页 SWP 源）。真实 server + 真网关 swe-2-medium + 真 arXiv 取源。现场 `bench/results/live-smoke2-2026-09-16/`（server.log、sse.log/sse2.log、poll.log/poll2.log、artifacts/ 六件），任务树 `tmp/live-smoke2-data/tasks/t_*` 全保留。

## 三次任务

**Run1 `t_ce8d74acf57aa208` → fault@fetch**：旧式 id `cond-mat/0408438` 在全新 data dir 下 `SourceCache.commit` ENOENT——`entry_dir` 让 `root/cond-mat/0408438v1` 嵌套一层但 commit 不 mkdir 父目录（cache.py:120-126）。新 cache + 带斜杠 id 必炸；新式 id 从没暴露过。**存量 bug，非本次回归面**（已修 98d7bd1）。手工 `mkdir src-cache/cond-mat` 绕过。

**Run2 `t_bfb5a4b9179da52b` → fault@compile（`fixloop_exhausted: no pdf`）**：compile.log 仅一行 `bwrap: Can't find source path tmp/.../build-zh`。根因已 /tmp 最小复现坐实：`_bwrap_wrap`（engine.py:683）`--bind str(root)` 传相对路径，bwrap 绑源按**子进程 cwd** 解析，而 `run_process` 的 cwd 恰是 build 目录本身 → 必 ENOENT。en/zh 两发全灭（`_tect_out` 全空），且无 .log → judge 0 errors → `no_errors_no_pdf` 假相，fixloop 无从归因。**这是今天 bwrap 沙箱落地的回归**（engine.py mtime 14:44，晚于 13:57 上一场 smoke；base-v3-full REPORT 自注"快照早于 bwrap"）。触发面：`TEXLATE_DATA_DIR`/`--work-dir` 相对路径（`data_dir()` 不 resolve）；默认 `~/.texlate` 绝对 → 产品默认形态安全。修法：`_bwrap_wrap` 入口对 `root`/`out`/`extra_rw` 做 `.resolve()`，一行级（已转 项目体验方式）。

**Run3 `t_aea8a22c2e5469d4`（绝对 TEXLATE_DATA_DIR 重跑）→ partial，验收面全过**：

- 时间线 60.1s：fetch 0.9s（src-cache 命中）→ parse 0.1s → translate 43.3s → compile ~16s
- 60 chunks 全部 `ok`，**翻译臂 failed=0**；其中 21 块命中共享缓存（run2 同文产物——shared cache_scope 生产实证）
- tectonic 在 **bwrap 沙箱内真跑**（绝对路径下绑源正常）：`_tect_out` 有 pdf/log/aux/dependencies.mk，compile.log 是完整 TeX 日志
- **probe 接线实证**：en/zh 双侧 `deps=8/9 tl_pkg missing=0`、`probe diff: seen=2 unread=0 undeclared=0`
- **L2 实证**：zh 首编 `! Undefined control sequence` @:86 → 归因 chunk 0:1 → 重译仍破 → `fallback_src` 回源 → 重编 clean → 终态 partial（语义正确；done.stats `chunks_failed=1` 即此计数）
- inject ctex line 35 ✓；tounicode 3 个 GB1 cmap ✓；verdict clean errs=0 ✓
- 产物：en.pdf 8 页 / zh.pdf 6 页（390KB），pdftotext 抽出**流畅真中文**（标题/摘要/引言/正文全译，署名地址与文献表按惯例留英文）；dual.json pages 对齐 8↔6
- server.log 全程 INFO 无 traceback、无 warning，key 未泄
- 路由说明：该文只有 `.ps` 图非 `.eps`，按 route_project 规则 tectonic 优先属正确行为

## 结论与未覆盖

整链无回归：probe-wire、L2、fixloop、inject、tounicode、shared-cache、瘦客户端轮询+sha256 下载全部实证工作。但**相对路径场景下 bwrap 编译必死且报错隐形**——修法为 `_bwrap_wrap` 入口 `.resolve()`（已转 项目体验方式）。未覆盖面：THEOREM_ANCHOR_SHIM（此篇无 shared-counter 定理，B7 复跑 #49 覆盖）、l0 注释区占位符（未触发）。

清理：server 已停（8793 释放）、SSE curl 已杀、网关 inflight 已还。Run1 残留的 `artifacts/md`（16:02）是 fault 任务遗产，其余产物均 run3 的（16:12）。
