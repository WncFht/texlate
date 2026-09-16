# share CLI 接线验收报告

2026-09-16 · 工单：`src/texlate/share.py` 库层 → `texlate share` 子命令接线。实现落 `src/texlate/cli.py`（新增 share 段 + 5 个内部 helper），测试 `tests/test_share_cli.py`（26 例全绿）。

## 命令面

```
texlate share pack <task_dir_or_id> [-o OUT] [--data-dir DIR] [--contributor S]
texlate share unpack <bundle.share.zip> [-o DIR]
```

- `pack` 参数分流：已存在目录直接用；`t_*` 形按任务 id 到 `tasks/` 下找（`--data-dir` > `TEXLATE_DATA_DIR` > `~/.texlate`）。
- `pack -o` 形态判定：已存在目录或无后缀路径 → 目录（其下落 `{share_key}.share.zip`）；带后缀路径 → 按给定名落盘；缺省 cwd。
- `unpack -o` 缺省 `cwd/{包名去 .share.zip 后缀}`。
- 退出码：0 成功；1 操作失败（定位不到库/任务行缺失/状态非 done|partial/ShareError 校验失败）；2 typer 参数错。

## key_parts 七组分来源表

| 组分 | 来源 | 备注 |
| --- | --- | --- |
| `arxiv_id` | 任务行 `arxiv_id` 列经 `normalize_arxiv_id` 拆 base | worker fetch 后落钉版形 `{id}v{N}` |
| `version` | 同上拆出的 resolved ver → `"v{N}"`；无 v → `""` | spec 即「进键的是 resolved 版本」 |
| `model` | 任务行 `model` 列 | 空 → 报错 |
| `prompt_ver` | `xlat.prompts.PROMPT_VERSION` | 本装常量 |
| `target_lang` | 任务行 `target_lang` 列 | 空 → 报错 |
| `glossary_hash` | 自定义术语表层文件 sha256 复合；无层 → `""` | 层 = 配置的 `glossary` 路径（缺省 `~/.texlate/glossary.yaml` 若存在）+ `base/glossary.local.yaml`；配置路径已死 → ShareError（不错标 `""` 串桶） |
| `pipeline_ver` | `server.worker.PIPELINE_VERSION` | 经 cache_key 交叉验证（见下） |

任务行读取：`sqlite3` `mode=ro` 只读直连 `texlate.db`——不走 `Store.open()`（带 DDL/迁移写副作用），`_share_data_root` 也不 mkdir（只读定位）。

## cache_key 交叉验证（pipeline_ver 诚实性）

`tasks.cache_key = sha256(arxiv_id@ver|model|PIPELINE_VERSION|lang)`——材料含 pipeline_ver 本身。pack 时对 `{ver ∈ {resolved_ver, None（latest 请求形态）}}` 两候选重算，命中 stored 即证明产物出自当前 PIPELINE_VERSION；不符 → **拒绝**（产物出自不同版本管线，打包会错标 share key）。`TEXLATE_CACHE_SCOPE=per_key` 时材料含凭证指纹无法重算 → 降级 stderr 告警放行。live-smoke 真任务实测：stored `890e97…` 与 `version=None` 重算完全一致。

## 验证证据

- `uv run pytest tests/test_share_cli.py -x -q`：**26 passed**。覆盖：round-trip（pack→unpack manifest/key_parts 一致）、目录/任务 id/--data-dir/env 四种定位、`-o` 两形、contributor 透传、钉版/latest 双形态 cache_key、partial 放行、全部报错路径（无库/无行/坏状态/无 arxiv_id/cache_key 不符/缺产物/glossary 配置死链）、unpack 篡改/非 zip/缺 manifest 拒绝、per_key 降级告警、三级 --help。
- `uv run ruff check src/texlate/cli.py tests/test_share_cli.py`：clean；`ruff format` 已收。
- 回归：`tests/test_share.py + test_cli*.py` 73 例全绿。
- 真实任务端到端：`share pack tmp/live-smoke-data/tasks/t_6cc3d2948f12bb38` → key `fd419dcb…`；`share unpack` 三产物 sha256 与 files 表登记逐字节一致（`ba5fbb…`/`41e13…`/`039ff8…`）。

## 实跑 `--help`

```
Usage: texlate share [OPTIONS] COMMAND [ARGS]...

 社区共享译文缓存包（设计 docs/research/product/shared-cache.md）。

╭─ Commands ─────────────────────────────────────────────╮
│ pack    本地任务产物 → {share_key}.share.zip。          │
│ unpack  .share.zip → 校验解包 + 打印 manifest 摘要。    │
╰─────────────────────────────────────────────────────────╯
```

## 已知边界（留 v2/服务端立项）

- `pipeline_ver`/`prompt_ver` 只能记账为**当前**安装版本——`per_key` 分桶下无 cache_key 可校验时，跨版本旧任务会错标（已告警）；要根治需任务行持久化 pipeline_ver（worker 立项改动）。
- `glossary_hash` 是 pack 时刻文件内容指纹——任务翻译完成后用户改了术语表文件会错标；内置/分类层不进指纹（随 pipeline_ver 走）。
- upload/文档类任务（arxiv_id NULL）不参与共享寻址——显式报错。
