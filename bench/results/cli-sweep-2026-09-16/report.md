# cli-sweep — 子命令离线冒烟矩阵（全离线，零网关）

> 2026-09-16。scope `src/texlate/cli.py`。68 测试全绿（test_cli* ×41 + test_share_cli ×27）。

## 冒烟矩阵

| 子命令 | 路径 | exit | 结果 |
| --- | --- | --- | --- |
| `--help` 全枚举 | 顶层 + version/fetch/parse/run/web/export/doctor/share/share pack/share unpack/tools/tools install-tectonic | 0 ×13 | 形状正常 |
| `version` | 实跑 | 0 | `texlate 0.1.0` |
| `parse` | bench/fixtures/tricky.tex（20 chunks/42 ph/0 warn）+ xlat-traps.tex `-o` | 0 | 符合契约 |
| `run` 本地目录 | /tmp tiny article mock 全链 | 0 | tectonic 实编 0.64s，verdict=partial(cjk_chars<20)，0=clean/partial 契约符合 |
| `run` 用法错 ×5 | bad engine / --model 脱离 --server / 本地目录喂 --server / -w 是文件 / -w 非空拒删 | 2 ×5 | 退出码契约全符合（含 reject_at→2 口径） |
| `export` epub/docx --mock | 缺省/显式 out | 0 | 插译 2/2，stderr 报告行正确 |
| `export` 错误 ×2 | 不存在文件 / 非 epub-docx zip | 1 ×2 | 「无法识别的导出格式」——test 钉死的设计口径 |
| `doctor` | 空 data-dir | 0 | 8 ok/1 n/a（网关不触网） |
| `tools install-tectonic` | TEXLATE_NO_DOWNLOAD=1 | 0 | 系统件检出正确 |
| `share pack` | 真任务 --data-dir | 0 | 七组分 key_parts JSON + 6.8MB 包 |
| `share unpack` | round-trip | 0 | manifest + 逐件 sha256 对账过 |
| `share` 错误 ×2 | pack 非目录非 id / unpack 非 bundle | 1 ×2 | 报错清晰 |

## 修复（已落，leader 入库）

`cli.py:543` web docstring `` ``texlate[server]`` `` → `` ``server`` ``：rich markup 把 `[server]` 当标签吞掉，help 实渲染丢 extra 名。

## 契约缺口（报告不修）

1. **`fetch` 无真离线路径**：HIT 也必先 HEAD 比 etag（fetch.py:451）——契约与实现一致；若要离线 HIT 需加开关（结构性，立项再议）。
2. **tools-runbook.md §1 表漂移**：缺 version/doctor/share pack|unpack 行——leader 已补（同 commit）。
3. `export` 不存在文件报「无法识别的导出格式」——exit 1 正确、test 钉死、文案略误导，非破窗。
