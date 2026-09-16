# share-residual — index_lookup 坏行容错（3 新测试，132 绿）

> 2026-09-17 收口。消化 share-e2e 发现 #1：单行 malformed JSON 毒死全索引。

## 修法

`index_lookup` 行级 ShareError 改为容错跳过：malformed 行（JSON 解析失败/解析出非 object）收集行号后继续扫，循环结束 `bad_lines` 非空记一条 `log.warning`（行号全留）。last-wins 不变——坏行不参与覆盖，合法行照常命中。文件级失败语义不动：`FileNotFoundError`→`None`、整文件非 UTF-8 仍抛 `UnicodeDecodeError`（worker.py:2130/app.py:1082 既有 catch 面继续兜）。与 `benchlib.iter_jsonl` 容错账读同口径。

## 留痕取舍

扫完一条 warning 带全部坏行号（非逐行）——lookup 是每任务热路径，索引重度腐坏时逐行刷日志是噪音。

## 写入侧

`index_append` 无改动——POSIX O_APPEND 单行小写原子已够（NFS caveat 已记档）。

## 文件：行

- `src/texlate/share.py:434-464` — index_lookup 重写（bad_lines 收集 + 尾部单条 warning）
- `tests/test_share.py:489-515` — 删 `test_index_malformed_line_raises`（旧 raise 语义），新增 `test_index_malformed_lines_skipped`/`test_index_malformed_preserves_last_wins`/`test_index_all_malformed_misses`

## 验证

`pytest -k share` 132 passed；ruff check/format 净。

## 外部路由

- `app.py:1082`/`worker.py:2130` 的 `except ShareError` 对 index_lookup 现为空集——保留无害且向前兼容，清理归对应 owner。
- index_lookup 每次全量 read_text（append-only 无界增长后的性能点）——非本任务面。

## docs errata（已落 docs/08 §7 由 leader）

malformed 行跳过不计、扫完记一条 warning 带行号；单行坏数据不毒死全索引；文件整体非 UTF-8 仍按不可读由调用方降级 miss；last-wins 不变。
