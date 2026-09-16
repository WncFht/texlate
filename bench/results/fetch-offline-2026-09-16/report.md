# fetch-offline — `fetch --offline` / `TEXLATE_OFFLINE=1` 离线缓存通道

> 2026-09-16。scope：arxiv/fetch.py + cli.py fetch 段 + test_arxiv_fetch.py。3 文件 +132/−4，36 测试过、ruff 净。

## 设计形态

旗标 + env 双通道：`texlate fetch --offline` 或 `TEXLATE_OFFLINE=1`（or 语义，显式旗标优先）。选型照仓内惯例「typer Option + env 兜底」（`--data-dir`/`TEXLATE_DATA_DIR`、`TEXLATE_MODEL` 同款）；env 复用 `e2e._env_flag`，cli.py 照 worker.py 先例跨模块 import 私有 helper。库层 `acquire_source(..., offline=False)` kwarg——默认 False 向后兼容，server/worker.py:1458 调用点零影响。

## 改动点

- `src/texlate/arxiv/fetch.py`：新增 `_offline_phase()`（:600 附近）+ `acquire_source` 加 `offline` kwarg。离线臂在 `_head_phase` 之前短路，fetcher 完全不触碰：钉版走 `cache.get(base, ver)`、未钉版走 `cache.get_latest(base)`（现成接口，docstring 本就写「仅离线兜底」）。命中沿用 `_hit_status` 终态透传（pdf_only/unknown 不伪装 hit），`detail="offline"` 标记来源。
- `src/texlate/cli.py`：fetch 加 `--offline` flag + `TEXLATE_OFFLINE` env，import `_env_flag`。
- `tests/test_arxiv_fetch.py`：+3 例。

## 行为矩阵

| | 在线 | 离线 |
| --- | --- | --- |
| HIT | etag 命中 → cache_hit（不变） | 钉版精确命中 / 未钉版取最高缓存版 → cache_hit + detail="offline"，**零请求** |
| miss | HEAD→GET→落盘（不变） | 空缓存/钉错版 → error + `offline_no_cache:{id}[v{N}]`，exit 1，不静默换版不上网 |

pdf_only/unknown 条目离线命中透传终态（exit 1，同在线语义，下游不会对着不存在的 extracted/ 跑）。`bad_id` 校验在离线分支之前，非法 id 照样拒且零请求。

## 验证

- `uv run pytest tests/test_arxiv_fetch.py tests/test_arxiv_locate.py -q`：30 passed 1 skipped（live gate）。
- `uv run ruff check` + `format --check` 全绿。
- CLI 冒烟：miss→exit 1 JSON `{"status":"error","detail":"offline_no_cache:2001.00099"}`；手工铺 `{id}v3/` 缓存 → cache_hit exit 0；`TEXLATE_OFFLINE=1` env 等效触发。

## 残余

离线 hit 不做 etag 重验证（断网本来就打不了 HEAD）——拿到的是落盘时版本，正是语义本体。`run` 命令的 `_resolve_source`（cli.py:300）没接 offline，全链离线模式是后续活儿。
