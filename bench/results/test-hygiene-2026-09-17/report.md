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
