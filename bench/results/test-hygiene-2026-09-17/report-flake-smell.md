# test-hygiene — 第三轮：blob_persisted flaky 修复 + tests/ smell 扫

> 2026-09-17 收口。落地 `2cb259a`（test_server_upload.py + test_compile_mask.py，+7/-12）。报告所列 test_compile_engine_judge.py PT018 拆分在 leader 复核时该文件已无残余 `assert a and b` 且干净——疑被并行 peer commit 先行收编，未入本 commit。scope tests/，未动 src/bench。（前两轮见同目录 report.md。）

## flaky 修复 — test_blob_persisted

根因实证：`_epub()` 的 `writestr` 用 `time.localtime()` 填 zip date_time，DOS 2s 粒度——两次调用跨边界字节不等（探针复现 diff 于 index 10 local header + central dir）。服务端 app.py:919 原样 write_bytes。修法：payload 只生成一次，`assert blobs[0].read_bytes() == payload`——仍逐字节等且更精确（对齐「落盘==上传字节」真契约）。5 连跑 5/5 绿。

## 顺手修（ruff 机械面）

- test_compile_mask.py:92/96 F811——`test_decode_tex_latin1_fallback` 逐字重复两份（前者永不收集），删一。
- test_compile_mask.py:111,127 PLC0415——`mask_comments`/`mask_tex` 函数内 import 挪顶层。

## smell 清单（file:line + 严重度，均未动）

| 严重度 | 位置 | 问题 |
|---|---|---|
| low | test_bench_regression.py:138 | `wall_ms` 字段 write-only——dedupe-pass 裁 KEEP（bench/py/fixture_assert.py:76,100 消费） |
| low | test_cli.py:244,248 | `tempfile.gettempdir()` glob `texlate-run-*` before/after 断言——并行 pytest 会话互踩 flake 面 |
| low | test_server_sidecar.py:71 | `elapsed < 4.5` 墙钟阈值——极端负载 CI flake 面 |
| low | test_server_byok.py:135 / test_app_endpoints.py:1024 | bind-release 占即释端口测 connection-refused——端口被抢误判（窗极小） |
| info | test_fixloop_llm_hook.py:230 | `elapsed < 2.0s` vs ~0.15s 预期——slack 13×，健康 |
| info | conftest.py:362 | `wait_terminal` 用 time.time() 非 monotonic |
| info | test_share_cli.py:155 | `TEXLATE_DATA_DIR` 依赖 autouse `_isolated_env`——隐式耦合 |
| info | test_fixloop_cases.py:14 | `RS = load_ruleset()` 收集期执行——ruleset 坏时 collection error 而非 test fail |

清白面：无真网络（live 全走 TEXLATE_LIVE 门，httpx 全 MockTransport）；随机全带种子；pytest.raises 全具名；无 bare-sleep 同步。

## peer 在飞记档

- test_texlog.py 收集 error（`looks_like_tex_file`→`looks_like_input_file` peer 改名未同步测试）——非本批引入。
- test_fuzz_unpack.py（fuzz-roundtrip #264 在飞）曾见 symlink-loop ELOOP + name_max 断言败，末次复跑 25 绿。symlink 环 oracle vs 产品缺口裁决已转 fuzz-roundtrip。

## 自验

pytest 三文件 103 绿；全量 --ignore test_texlog 2871 绿；ruff 改动文件净。
