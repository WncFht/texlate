# dedupe-pass — 重复实现单源化 + write-only 字段清扫交付

> 2026-09-17 收口。落地 `7b17107`（9 文件，+31/-62）。leader 复核：ruff 净，pytest 全量 2830 绿 4 skip（test_texlog.py peer 在飞收集失败划出；test_fuzz_{unpack,texlog}.py 为 fuzz-roundtrip 未入库在飞件划出——前者跑出 1 个 symlink-loop RuntimeError，已转 fuzz-roundtrip 裁决）。同主题 hunk 分三处落地：app.py 侧（`_NEW_ID_RE`/`_OLD_ID_RE`/`_LOCAL_HOSTS`/`_is_valid_arxiv` → `fetch._valid_id`+`client._LOOPBACK_HOSTS`）已随 `1d1ad8d` 双归因落地；textutil.py `BEGIN_DOC_RX` 导出已随 `07633b4` 双归因落地；worker.py `_zip_unique`→`unpack._unique_rename` 与 import 两 hunk 留在工作区，将随 worker-share-fix 交付同 commit 双归因。

## Group 1 — arXiv id 校验正则（app.py 侧已落 1d1ad8d）

`server/app.py` 删 `_NEW_ID_RE`/`_OLD_ID_RE`/`_is_valid_arxiv`，直引 `arxiv/fetch.py:154 _valid_id` + `:172 normalize_arxiv_id`。meta.py 评估为宿主被否——`fetch._stale_warnings` lazy-import meta 会形成环；fetch 是 id 语义的 producer 侧，持 canonical 正确。

## Group 2+3 — loopback/tailnet 主机集（三处重复 → xlat/client）

`_LOCAL_HOSTS`（app.py）+ `_LOCAL_HOSTS`（settings.py）+ `_LOOPBACK_HOSTS`（client.py:356）三份同源；`_TAILNET_V4`（settings↔client 双份）。统一收编 `xlat/client.py`（网络语义 producer 侧）：settings.py 改 import（`_LOOPBACK_HOSTS`+`_TAILNET_V4`，tailnet 加密 rationale 挪进 docstring），app.py 侧已随 1d1ad8d 切。

## Group 4 — `_TEX_EXT` → `arxiv/_texutil.py TEX_EXT`

unpack.py:44 与 locate.py:33 双份 `(".tex", ".ltx", ".latex")`。宿主选 `_texutil.py`（arxiv 层共享工具件，不引新依赖方向）。

## Group 5 — `\begin{document}` 正则 → `textutil.BEGIN_DOC_RX`

三处同 regex：sniff.py:142、inject.py:203、locate.py:41（共 6 个调用点 search/split 两用）。收编 textutil（跨层共享文本工具，三消费方都已 import 它），导出 hunk 随 07633b4 落。RUF022 `__all__` 排序顺手归位。

## Group 6 — `_zip_unique`/`_unique_rename` → `arxiv/unpack._unique_rename`

worker.py:896 与 unpack.py:161 逐字同体。worker 删本地版改 import 私有名（两 hunk 在工作区，随 worker-share-fix 交付落）。

## Write-only 字段裁决（crosscut-sweep 路由）

- `xlat/client.py` `HIDDEN_PROMPT_TOKENS`（:42，零引用）→ **删**。
- `FreeModel.max_output_tokens`（:304 字段 + :890 fill，零读点无序列化路径）→ **删**。
- `meta.py` `VersionInfo.source_type`（:82 字段 + :214 OAI fill，meta.json 手搭 dict 不含 versions → 字段到不了产物）→ **删**。
- `l1.py` `TsValidator.ensure_deps`（:211，公开 bootstrap API 但 src/tests/bench 零调用）→ **删** + docstring 同步；未来首装归 `tools` 命令面而非 doctor。
- `tests/test_bench_regression.py:138` `wall_ms` → **KEEP**：断言对象其实被 `bench/py/fixture_assert.py:76,100` 消费，原判「测试未用变量」有误。

## 旁证/边界

- peer `a91a474` 已先做 `_JSON_FENCE_RX`→`textutil.JSON_FENCE_RX` + `DEFAULT_BASE_URL`/`DEFAULT_MODEL`→client（settings.py 侧 swap 由 leader 在本 commit 内补刀落地）。
- 自验（agent 侧）：pytest 子集 731 绿 1 skip（--ignore test_texlog.py 规避 peer 在飞改名），ruff 净，无 import 环。
