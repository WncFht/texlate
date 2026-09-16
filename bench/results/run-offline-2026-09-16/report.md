# run-offline — `texlate run --offline` 全链源获取零网络

> 2026-09-16。scope：cli.py run 段 + test_cli.py。2 文件 +98/−3，cli*+arxiv_fetch 62 过、ruff 净。fetch-offline（`8af61c5`）残余收口。

## 改动清单

- `cli.py:206-213` — `run` 新增 `--offline` flag，help 注明「env TEXLATE_OFFLINE=1 等效；--server 模式不生效」（fetch 命令同款写法，`_env_flag` 复用既有 import）。
- `cli.py:251-253` — run docstring 补 offline 段：本地目录源无影响；arXiv id 源只查本地 src-cache，miss→`offline_no_cache` exit 1。
- `cli.py:293-295` — 调用点 `offline=offline or _env_flag("TEXLATE_OFFLINE", default=False)`（与 fetch.py:107 同款 env 解析位）。
- `cli.py:331-338` — `_resolve_source` 加 `*, offline: bool = False` kwarg 透传 `acquire_source(offline=)`；本地目录分流在 acquire 之前短路，dir 源天然不受影响。

## 测试（test_cli.py 新增 `_seed_cache` helper + 4 例）

- `test_offline_miss_exit_1` — 空缓存 → exit 1 + `detail=offline_no_cache:*`
- `test_offline_env_flag_miss` — `TEXLATE_OFFLINE=1`（monkeypatch）等效
- `test_offline_hit_full_pipeline` — SourceCache stage/commit 铺 `2001.00099v1` 含 `extracted/main.tex` → 全链跑通 exit 0，`status=cache_hit detail=offline`，fake_engine 确被驱动
- `test_offline_local_dir_unaffected` — 本地目录源 exit 0 clean

## offline 在 run 链的覆盖边界（残余联网点，如实记录）

`--offline` 只到源获取层。run 全链仍有联网点：

1. **tectonic 冷拉 bundle** — `engine.py:59` `TECTONIC_BUNDLE_PIN` 是 URL，首编冷拉留网；热缓存后不联网。xelatex 走本地 TeXLive 不联网。
2. `TEXLATE_ENV_JUDGE=1`（默认关）→ LLM 网关 env 判定。
3. `TEXLATE_FIXLOOP_LLM=1`（默认关）→ fixloop llm_hook 网关。
4. `--server` 模式整链 HTTP 瘦客户端 by design 联网；`--offline --server` flag 静默不生效（与 `--cache/--keep/--work-dir` 在 server 模式下既有语义一致，help 已注明）。

已核实不联网：MockTranslator/L0/validate 层无网关调用；e2e 链不查 arXiv meta；`acquire_source(offline=True)` HEAD/GET 都不发。

## 验证

`uv run pytest tests/test_cli*.py tests/test_arxiv_fetch.py -q`：62 passed 1 skipped；ruff format/check 两文件净；真机冒烟三路径（flag miss / env miss / seeded hit 全链）。

## 注意

跑测期间撞上一次瞬时 4-fail（含改动前已绿的 test_local_dir_clean）——当时别家在飞改 engine.py/inject.py/e2e.py，重跑全绿，定性多会话共仓读时刻抖动。`--offline --server` 未做互斥拒绝（与既有本地旗标语义一致）；若要严格互斥 exit 2 是小改，待 leader 定夺。
