# test-hygiene — tests/ 套件卫生审计（只读取证）

> 2026-09-17。2447 收集 1.5s 无错。按严重度排序；High 3 项已转修复。

## High

1. **test_share_postpack.py:99-107 env 依赖（必红面）**：`test_done_packs_and_indexes` 断言 `key_parts.glossary_hash==""` 走真 `worker._share_glossary_hash` → 读真实 `~/.texlate/glossary.yaml`（worker.py:3189），文件没钉 `worker.USER_GLOSSARY_PATH`（test_share_wire.py:83 有示范钉法）——宿主有术语表即红，方向反了的"脏宿主才红"违例。修法：conftest 级 `make_app`/`client` 工厂统一钉（`_make_glossary` 对每 live-pipeline 测试都读真文件，test_server_worker/l2/babeldoc/app_endpoints 全裸奔靠 MockTranslator 不敏感撑着）。
2. **test_xlat_gateway_smoke.py:16 密钥硬编码**：`GATEWAY_KEY = env.get("TEXLATE_GATEWAY_KEY", "240127")`——真网关 key 默认值入库。修法：默认 `""`，`_LIVE` 且 key 空 → skip。
3. **conftest.py:29-44 env 白名单缺口（系统性）**：`clean_env._ENV_KEYS` 只盖凭证/路由，漏行为旗标 `TEXLATE_NO_BWRAP`/`TEXLATE_OFFLINE`/`TEXLATE_NO_EXPAND`/`TEXLATE_NO_L2`/`TEXLATE_ENV_JUDGE`/`TEXLATE_NO_DOWNLOAD`/`TEXLATE_TS_NODE_PATH`/`TEXLATE_BABELDOC_TIMEOUT`——宿主 export 任一即无关测试翻转。修法：按 `TEXLATE_` 前缀扫描 delenv，新旗标自动免疫。

## Medium

4. `install_log_scrub` 全局 filter 泄漏——app.py:410 lifespan 每起 app 往 root+`_LOG_NAMES`+全部现有 handler（含 pytest capture）挂 `RedactFilter` 从不卸；caplog 断言 `sk-*`/`api_key=`/`Bearer` 文本的用例会序依赖炸。修法：autouse fixture 快照/还原 filters，或配 uninstall 由 teardown 调。
5. test_bench_rundiff.py:18 + test_bench_triage.py:22 收集期 `sys.path.insert(0, bench/py)` 永不摘——改 pytest.ini `pythonpath` 或 conftest fixture。
6. test_validate_l1.py:16 收集期 `v.available()` → subprocess 探 node——挪 module fixture 或 `shutil.which` 收集期判定。
7. test_compile_engine_judge.py:431-437 `os.environ` 手设手删不经 monkeypatch——断言炸则泄漏。

## Low / flake 面

8. test_server_byok.py:137 / test_app_endpoints.py:981 bind(0)→close→ECONNREFUSED 端口被抢窗口（极低概率）。
9. test_server_babeldoc.py:215 假 sidecar `sleep(60)`——kill 路径坏会留孤儿进程。
10. test_fixloop_llm_hook.py:222 时序断言（delay=5 vs timeout=0.05+slack）极端负载 flake 面。
11. test_share_cli.py:159 `os.environ` 直读靠 autouse setenv 撑。
12. test_fixloop_cases.py:14/test_fixloop_logparse.py:14 模块级 `load_ruleset()` 收集期 IO。
13. worker `_loop`/`_loop_tid` 私有属性注入伪造 loop 线程（test_share_hook.py:88 等）——能用但深耦。

## 审过净

tmp/磁盘泄漏（全在 tmp_path）；断言质量（`pytest.raises` 全带具体类型，无永真/吞断言）；async 标记；外依赖守卫（xelatex/tectonic/node/bwrap/corpus/TEXLATE_LIVE/fastapi importorskip 全就位）；lru_cache 污染路径；随机种子/时钟；线程 join。

## 路由

High 3 项返 test-hygiene 自修（conftest 前缀扫描 + USER_GLOSSARY_PATH 钉 + GATEWAY_KEY 去默认）；Medium 按 ROI 顺手带。

---

# 第二轮：修复落地（High 三项 + Medium 全清）

> `uv run pytest tests/ -q` → **2515 passed, 4 skipped, 0 failed**（58.6s，4 skip 全为既有 env-guard）；ruff format/check 对全部改动文件净。pipeline.py 在飞未造成任何红。

## 逐项落地

**High-1 USER_GLOSSARY_PATH 统一钉** — conftest 新 autouse `_no_user_glossary`：钉 `xlat.glossary.USER_GLOSSARY_PATH` + 条件钉 `worker.USER_GLOSSARY_PATH`（sys.modules 在册才钉，不强拉 worker；后 import 的 worker 会 from-bind 到已钉值）。test_share_wire（pair fixture + test_zero_match）、test_share_hook（test_no_layer_empty）、test_share_cli（_isolated_env）的重复钉已删。
- **中途自伤已修**：首版用 monkeypatch——autouse 消费它会把共享 monkeypatch 提前实例化，teardown 排到 test_compile_sandbox `_clear_probe_caches` 之后撞上未还原 lambda（4 个 teardown AttributeError）。已改写手写 save/set/restore（conftest.py:72-104 注释记档）。**规训：此后任何 autouse fixture 都别吃 monkeypatch。**

**High-2 gateway_smoke key 默认值** — `GATEWAY_KEY` 默认 `"240127"`→`""`；skipif 改 `not (_LIVE and GATEWAY_KEY)`。真实密钥不再内嵌默认值。

**High-3 install_log_scrub 泄漏** — conftest 新 autouse `_restore_log_filters`：用例后从 root + 全部已注册 logger + 各自 handler 摘除 `RedactFilter`（settings.py:540 挂而不卸，曾污染后续 caplog 断言）。

**Medium-1 clean_env 前缀扫描** — `TEXLATE_*` 全前缀 delenv（`tuple(os.environ)` 先物化再删）；`_ENV_KEYS` 收敛为 5 个非前缀键。新行为旗标（含 TEXLATE_SHARE_DIR）自动免疫。

**Medium-2 sys.path.insert 收口** — pyproject `[tool.pytest.ini_options]` 加 `pythonpath = ["bench/py"]`；test_bench_triage/test_bench_rundiff 模块级 sys.path.insert+BENCH_PY 删除，import 归位 isort 序；`Path` 移入 TYPE_CHECKING。

**Medium-3 validate_l1 收集期探测** — 模块级 `TsValidator()`+`available()` 删除；skipif 收窄为 `shutil.which("node")`+tree-sitter 目录纯路径闸；真可用性终判挪模块级 `v` fixture（pytest.skip 兜底），3 个消费用例改收 `v` 参。

**Medium-4 engine_judge 手动 env** — `os.environ` set/del → `monkeypatch.setenv`；`import os` 移除。

## 文件清单（全在 tests/+pyproject）

conftest.py、test_share_wire.py、test_share_hook.py、test_share_cli.py、test_xlat_gateway_smoke.py、test_bench_triage.py、test_bench_rundiff.py、test_validate_l1.py、test_compile_engine_judge.py、pyproject.toml

## 备注

- 验证中段曾见 test_worker_audit_fixes pty-fd 用例红——是 server-residual #164 在飞（babeldoc.py 当时刚改），其修复落地后末次全量已绿，非本单问题。
- 未碰 test_fixloop_yamlish.py 与 Low #13 worker 私有属性注入面（留档）。
- diff 逐 hunk 自查：无夹带、无 src/ 改动。
