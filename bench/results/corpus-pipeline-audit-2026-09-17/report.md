# corpus-pipeline-audit — bench 语料管线 + ts harness 审计交付

> 2026-09-17 收口。31 项确认修复，落地两笔：`fc4949c`（py 语料管线 5 文件 +268/-130）、`7b3e5b5`（bench/ts harness 4 文件 +77/-33）。探针 `tmp/corpus-pipeline-audit/`（gitignored）。benchlib/stagerun 按约定只读未动。

## build_corpus_v3.py

- `fetch_one` 坏文件永久失败循环修复：verify 失败时 unlink 坏 final/part + `c.pop("error")`——原逻辑坏文件落盘后反复命中同一路径永久失败。
- `verify_chunk` 双 `read_bytes` → 单遍双 hash（4MB 块流式，sha256+sha1 同算）。
- `stream_download` 补 try/finally 保证 response close。
- `cmd_probe` Range 读 capped 65536 + `with` 管 response。
- `cmd_zipsum` 补 URLError/OSError 容忍 + 仅 404 钉 dead。
- `cmd_extract` `.get(fmt, "raw.bin")` 防未知 fmt KeyError。
- `cmd_extract_booster` skipped 计数修正。
- `cmd_qc` 盘↔manifest 孤儿对账（双向 diff 报告）。
- `write_manifest_md` 已有 curated `## 补强层`/`## 热层` 段时跳过重写（保手工策展）。
- 4 处 csv fd 泄漏 → `with` 托管。

## build_corpus_expand.py

- `_verify_content` 单遍 sha256+sha1 贯通全部 3 条返回路径——原 size-only fast-path 让错内容混过校验。
- torn meta cache 恢复（半成品 meta.json 不毒化后续 run）。
- short-read 检查 + 远端读设上界。
- None-offset skip 防护。
- 5 处 csv fd 泄漏修复。

## build_hot_layer.py

- `_oa_get` 参数走 urlencode + 3 次重试。
- `cmd_candidates` 逐页 flush（中断不丢已抓页）+ 空结果不覆盖既有输出。
- `cmd_fetch` copytree 前 rmtree 陈旧目标。

## select_booster.py / corpus_v2/build_corpus.py

- select_booster：evidence 字段 `str()` 强转（非 str 输入炸 sort key）。
- corpus_v2 build：macOS ROOT 硬编码路径 → repo 相对。

## bench/ts（4 harness）

- **bench-tsl.js**：fetch 30s timeout；null-row 守卫；递归 walk 改迭代（深树不爆栈）；computed Point 修正；UTF-16 声明诚实化。
- **bench-lu.js**：`TimeoutError` 判定加 `constructor.name` 回落；`stripComments` 偶数反斜杠边界修复（`\\%` 后误判注释）；死代码删除。
- **ul_corpus.js**：空 split 产 phantom FAIL 修复。
- **ul_tricky.js**：行收集改 flatMap。

## 自验

- `ruff check` 全净；`ruff format` leader 侧补格式化 2 文件后净。
- `node --check` 4 文件全过；prettier --check 净。
- 探针 A–D + stripComments 8-case 全绿（agent 侧实证）。

## 存疑待裁（报 leader 裁，未动）

- `n100_rates` 在空输入时 ZeroDivisionError——需裁决：空集应报 0 还是报错。
- `largest_remainder` 负权重输入未防护——需裁决：契约是否承诺非负权重。
- bench-tsl partial-tree timeout 形态——记录在案。
