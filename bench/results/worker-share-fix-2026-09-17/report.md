# worker-share-fix — worker.py share/flush/log 四面修复交付

> 2026-09-17 收口。落地 `b356b3b`（worker.py + test_worker_audit_fixes.py + test_share_apply.py，+323/-40）。leader 复核 worker/share/dual 子集 267 绿。**双归因**：同 commit 含 dedupe-pass 在飞 hunk——`_zip_unique` 删除改 `from texlate.arxiv.unpack import _unique_rename`（:53 import 区 + :907 调用点），供应名 7b17107 已入库自洽；`CJK_RX` import（:122）属本代理缺陷 1 修配。探针 `tmp/worker-share-fix/probe.py`（修前 1/4 → 修后 4/4）。

## 缺陷 1 — share 对账 zh 位污染以 ok 落库

`_share_apply` 读包内 dual.json → `_share_pool` 建 `(src_file,en)→deque[zh]` → `_share_row` 弹 zh 跑 `validate_pair`。源任务 `fallback_orig`/`failed` 行 dual.json zh 位装的是 src_text 回写/空串，而 `validate_pair` CJK 占比仅 WARN——英文 src 配 zh=en/zh="" 都判 ok → matched 造假、英文「译文」ok 落库续传、绕过 matched==0 零命中拒绝。修法（worker.py:842-863 收闸）：zh 非 str/空白 → 不进池；`zh==en` 且无 CJK（`CJK_RX`）→ 不进池；`zh==en` 含 CJK 放行（原文即中文段的合法恒等译文）。选消费端池过滤而非改 `_build_dual` 打包面：dual.json 同喂 reader 端点——zh=en 忠实镜像 zh.pdf 实际块内容，改空串会让 reader 译文窗格空白与 PDF 不一致；且消费端守卫顺带覆盖已发布存量坏包。

## 缺陷 2 — `_share_lookup` 冗余 ShareError

worker.py:2290 `except (ShareError, OSError, UnicodeDecodeError)` → `(OSError, UnicodeDecodeError)`。`index_lookup`（share.py:472-502）真实异常面只有这两者；下方 `unpack_share` 的 `(ShareError, OSError)` 保留（真源）。

## 缺陷 3 — `_log_text_of` 空 .log 洞

原逻辑 .log 存在即读、读到 "" 直返，`stdout_tail` 兜底不可达 → missing-char 等只存在于 stdout 的升级信号静默丢（judge missing_chars=0）。改与 `engine.parse_log`（engine.py:1416/1668 `text or res.stdout_tail`）同口径：缺席/读失败/空文件一律 `text or res.stdout_tail or ""`。

## 缺陷 4 — `suppress(CancelledError)` 裹 `_flush_translate` 脆弱面

`_flush_translate` async→sync，两调用点（poll :1963、teardown :2025）去 await/suppress。选同步化而非注释/try：cancel 只投递在悬置点，同步体原子跑完——结构性消除「未来加 await→cancel 截断写盘再被吞」隐患。docstring 记不变量；`_teardown_translate` 后续真 await `_aclose_clients` 不受影响。

## 测试

- test_worker_audit_fixes.py +4 类 10 条：TestSharePoolZhGuard（zh==en 无 CJK→missed+share_miss；空白/非str/缺键→missed；含 CJK→ok；真 zh→ok）、TestLogTextOfFallback（空 log/缺文件/目录/非空胜出/无 log/全空）、TestFlushTranslateSync（sync 契约钉 + pending-cancel 下缓冲块仍落库）、TestShareLookupExceptSurface（目录→OSError 吞为 miss；monkeypatch 抛 ShareError→传播钉死面）。
- test_share_apply.py +test_import_polluted_zh_counts_as_miss：真管线产包→`_repack_dual` 污染 chunks[1].zh=en/chunks[2].zh=""→导入→partial+failed==2+`error.share{matched:1,missed:2}`+逐块 share_miss。

## 未修项

`zh != en` 但纯英文无占位符 zh 仍能过 `validate_pair`（CJK WARN）——L0 判定强度问题，超 routed 范围，记档未动。F4（`_run_fixloop` halt_on_error=True）leader 复核时发现未见落盘，已回问（截至报告时待答）。
