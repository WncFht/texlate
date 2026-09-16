# arxiv-stale — docs/06 §1.4 stale-version hint 落地报告

日期：2026-09-17。scope：`src/texlate/arxiv/` + `tests/test_arxiv_*.py`。

## Atom 可用字段结论

- Atom feed **不含版本史**：版本列表只在 OAI-PMH arXivRaw `<version>` 元素里。
- 裸 id 查询（`id_list={base}`）时 entry `<id>` = `http://arxiv.org/abs/{base}v{latest}` → `PaperMeta.resolved_version` 即 feed 宣告的最新版（`latest_version` property 同源）。
- 钉版查询（`id_list={base}vN`）entry 只描述该版——resolved_version=钉版号，拿不到真 latest（meta.py `PaperMeta` docstring 已注明「已见最新而非真 latest」）。
- 因此 stale 判定复用现成公共 API `resolve_version(base, fetcher=...)`（裸 id → Atom→OAI 链 → latest `int|None`，一切失败归一 None），与 spec「Atom resolved_version > 缓存 → 标 stale」语义对齐且白赚 OAI 兜底。

## stale 信号形态

`AcquireResult.warnings` 追加 `"stale:v{N} available"`。warnings 通道最零侵入：cli `_echo_acquire` 的 `warnings` 字段（cli.py:127）与 worker `fetch warn:` 日志（worker.py:1540）自然透出——**cli.py 零改动**。只注入缓存命中两臂：`_head_phase` etag-hit 与 `_get_phase` 304-hit，共用 `_hit_result`。语义：提示不升级、不挡命中；`latest <= hit_ver` 或探测失败 → 无 warning。

## 改动 file:line

- `src/texlate/arxiv/fetch.py:444` `_stale_warnings`——`hasattr(fetcher,"get_url")` 鸭子门（测试 fake 无 feed 臂静默跳过）+ 函数内延迟导入 `resolve_version` 破 meta→fetch 循环依赖（`# noqa: PLC0415`，仓内既有惯例）。
- `src/texlate/arxiv/fetch.py:462` `_hit_result`——`_hit_status` 终态透传 + stale warnings 组装。
- `src/texlate/arxiv/fetch.py:509` etag-hit 接入（`_head_phase`）。
- `src/texlate/arxiv/fetch.py:541` 304-hit 接入（`_get_phase`）。
- `tests/test_arxiv_fetch.py`：`_ATOM_LATEST_V2` fixture + 4 用例。
- meta.py/cache.py/cli.py：零改动。

## 测试

- `uv run pytest tests/test_arxiv_*.py -q` → **221 passed, 1 skipped**（live gate 正常跳过）。
- `uv run pytest tests/test_server_worker.py tests/test_e2e_mock.py tests/test_cli.py -q` → 38 passed（FakeFetcher 鸭子型路径回归）。
- `uv run ruff format --check` / `ruff check`（src/** select=ALL）→ 净。

新用例：

- `test_hit_stale_hint_when_feed_newer`：钉 v1 命中 + feed v2 → HIT + `["stale:v2 available"]`；同测把 HEAD etag 换新版走 304-hit 臂，同样报 stale——两臂一次覆盖。
- `test_hit_no_stale_when_pinned_is_latest`：钉 v2 + feed v2 → HIT 无 warnings（不误报）。
- `test_hit_stale_unpinned_feed_ahead`：未钉版、HEAD 解到已缓存 v1（src CDN 滞后于 feed 的形态）+ feed v2 → HIT + stale。
- `test_hit_stale_check_survives_meta_outage`：Atom/OAI 全 ConnectError → HIT + warnings `[]`（best-effort 不挡命中）。

## 边界确认

- 离线臂零网络：`_offline_phase` 不触 fetcher，stale 探测只在在线命中臂——`test_offline_hit_zero_network` 的 `not calls` 断言仍绿。
- HEAD 失败路径行为不变（探测在命中短路之后才发生）。
- 鸭子型 fetcher 无 `get_url` → 探测跳过，`conftest.FakeFetcher` 不炸。
- Atom/OAI 全挂 → `resolve_version` 归一 None → 静默无 warning。

## 残余

- 代价：每次缓存命中 +1 Atom 请求（Atom 挂时 +1 OAI），全过 limiter pacing——spec 明确以 Atom 为源，成本即此；批量重取场景请求数翻倍是 spec 内代价。
- 未钉版正常流（HEAD 解到真 latest → miss → GET 新版落盘）不产 stale——用户已拿新版，无需提示。
- 钉版 miss → GET 旧版成功（status OK）不报 stale——任务 scope 限定命中臂；「OK 路径也提示有新版」是另一个产品决策。
- FakeFetcher 若日后补 `get_url` mock，worker 测试可覆盖 stale 透出（`fetch warn:` 日志行）。
