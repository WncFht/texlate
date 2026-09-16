# test-flake-fix — smell 清单 low/info 项修复交付

> 2026-09-17 收口。落地 `431b857`（7 测试文件，+76/-54）。leader 复核 245 绿。探针 `tmp/test-flake-fix/`（gitignored）。五项全处置，零「不值得修」。

## 逐项

1. **test_cli.py test_copytree_failure_cleans_mkdtemp**（tempdir glob 竞态）：`monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))` 把 mkdtemp 钉进用例私有目录（实证 mkdtemp 吃 tempdir 全局），断言改 `not list(tmp_path.glob("texlate-run-*"))`——并行 pytest 会话并发增删完全免疫且仍真测清理（不 redirect 会退化成空过）。连带 `Path` 最后 runtime 用点消失被 ruff TC003 收进 TYPE_CHECKING。
2. **test_server_byok.py:135 + test_app_endpoints.py:1024**（bind-release 端口竞态）：探针实证 bind 未 listen 的 socket 持口防抢占（二次 bind EADDRINUSE）且入站 connect 必 ECONNREFUSED——改 `with socket.socket()` 持口贯穿请求，删即释窗。
3. **conftest.py wait_terminal**：`time.time()` → `time.monotonic()` 两处。
4. **test_fixloop_cases.py:14 + test_fixloop_logparse.py:14**（收集期 IO）：模块级 `RS = load_ruleset()` → `@lru_cache(maxsize=1) def _rs()` 惰性加载；logparse 加 `_warn()` 薄壳。坏 yaml 现在报 test fail 而非 collection error。**leader 扩单**：同款 `RS` 收集期 IO 另有 5 文件（test_fixloop_aux_eof/loop/spikereplay/rules/f1f2）已派回同型修。
5. **test_fixloop_llm_hook.py:230**（墙钟断言）：`_drive` 放弃语义是 daemon 线程丢跑——给 FakeTranslator 加 `done = threading.Event()` 哨兵，断言 `not tr.done.is_set()`（协程仍在 5s 睡=确证放弃而非等满），零墙钟且更严格；删 `_ABANDON_SLACK_S`/`import time`。

## 自验

改动文件 245 绿；改动用例 5 连跑 5/5；全量 --ignore 三件在飞 2857 绿 4 skip 2 xfail；ruff 净。唯一失败 test_fuzz_share.py::test_fuzz_unpack_mutated_bytes 为 fuzz-roundtrip 在飞件（zlib.error 面待其裁决）。

## 遗留

5 个 sibling 文件同款 `load_ruleset()` 收编中（leader 扩单）；其余清单项全处置毕。
