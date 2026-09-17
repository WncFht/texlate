# cli-fuzz — adversarial CLI property tests

> 2026-09-17 收口。交付 `tests/test_fuzz_cli.py`（~1470 行，235 items，commit `2460fe7`）：**205 passed + 30 xfailed(strict)**，ruff check/format 双净。全离线——CliRunner + tripwire Fetcher/MockTransport/pipeline_stub，零网络零真引擎。oracle：`result.exception is None/SystemExit` + 输出无 Traceback。

## 确认缺陷（strict-xfail 钉住，修复即翻红）

| # | 缺陷 | 位置 | 复现/影响 | 修法 |
|---|------|------|-----------|------|
| D1 | NUL×14 Path 参数 traceback | typer `models.py:711` `PathInfo.convert` `os.stat` 只捕 OSError 不捕 ValueError | `parse/export/share unpack\|pack -o\|pack --data-dir/run --work-dir\|--cache/-o/fetch --cache/web --data-dir` 任一塞 `\x00` → `ValueError: stat: embedded null character`；对照组 str 参数干净 exit 1 | 上游 typer 补 ValueError 捕获，或 cli 侧 Path 参数预检 |
| D2 | `export <epub> -o <已存在文件>/x.epub --mock` | `cli.py:762` 只捕 ExportError | NotADirectoryError traceback | 捕 OSError 族 |
| D3 | `doctor` + `TEXLATE_BASE_URL='::::'` | `cli.py:1431` `_doc_gateway` | `except httpx.HTTPError` 漏 InvalidURL（继承 Exception 非 HTTPError），有/无 API_KEY 都触发 | except 元组补 InvalidURL |
| D4 | 瘦客户端不校验 arxiv id | `cli.py:423` `normalize_arxiv_id` 垃圾返回原样 + `cli.py:486` POST | `run 'x/../../y' --server http://s` 借 httpx dot-segment 规范化落到 `POST /api/y/translate`——**逃出 `/api/arxiv/` 命名空间**；`2001.00001/extra`、`a b`、`%2e%2e/x`、`x/../y`、`not-an-id` 同样原样进 path | 瘦客户端路径段校验（白名单 id 形态）后再拼 URL |
| D5 | `TEXLATE_TRANSLATOR=gatewy`（拼错值）静默忽略 | `cli.py:792-807` | auto/Mock 回落，与 `gateway` 缺 key 的 exit-2 显式拒不一致 | 非法值显式报错 |
| D6 | ENAMETOOLONG/EACCES OSError 穿透 `is_dir`/glob | `cli.py:385` `_resolve_source`、`:417` 瘦客户端预检、`:844` `_share_task_dir`、cache glob | traceback；`run <300 字符 source>` 同根因（注释记录，未重复钉） | 探测点补 OSError 宽捕 |

## 已修复项回归钉（commit `2307b40` 验证）

`--server '::::'`→2；`--timeout/--wait nan|inf`→2；空/纯空白 source→2；`share pack 't_x/../../victim'`→exit 1（jail 生效）；`'t_x/../t_x'`→exit 0（仓内归一合法）。

## 非缺陷说明

`--server ""` 在 MockTransport 下 `ValueError: unknown url type` 是 harness 假象——真实 transport 发包前即 `UnsupportedProtocol`→干净 exit 2（未打补丁实证）。测试在 mock handler 内补等价 scheme/host 闸。

## 覆盖面

arXiv id 46 具名形态×fetch+run；250 迭代种子随机汤（`--` 分隔）；`--version` 边界；NUL Path×14+对照×3；ENAMETOOLONG×5+EACCES；run 校验闸全谱（非有限/空源/引擎白名单/server-only/work-dir 形态）；瘦客户端 9 场景（409 attach、sha256 不符跳过、traversal 产物名、wait=0 立即超时）；parse/export/share/web/tools/doctor/env 旗标；`--help` 全 13 命令面。

## 遗留跟进

- **NUL-byte typer 回调扫描**：D1 根因在 typer 上游——产品侧是否统一 Path 参数预检待裁（leader lane，已记档）。
- D4 属安全面（URL 命名空间逃逸）——优先级最高。
