# cli-smoke — cli.py 离线冒烟矩阵（全 PASS，零修复）

> 2026-09-17 收口。scope：`src/texlate/cli.py` 全子命令离线面。**未发现崩溃/回归，零代码改动。** `pytest tests/test_cli*.py` 45 passed，ruff 双链净。

## 矩阵（全 PASS）

| 面 | 覆盖 |
|---|---|
| help/version | 顶层+9 子命令 --help 全渲染；`version`→`texlate 0.1.0`；裸调用/未知命令/缺参→exit 2 |
| fetch --offline | miss→`offline_no_cache`+1；未钉版取最高缓存版→`cache_hit`+0；`-v` 钉版/错版/0；URL id；`TEXLATE_OFFLINE=1` 等效 |
| parse | flatten/--no-flatten 同结果（tricky.tex 20 chunks）；`-o` jsonl 9 行；目录/不存在→2 |
| run 本地目录 | e2e mock 全链→`partial`+0；`--keep`；`--work-dir` 新建/已存在空/非空/文件边界全对 |
| run arxiv --offline | 无缓存→`offline_no_cache`+1；非 id→`bad_id`+1 |
| run 用法错 | bad engine/`--model`/`--wait` 脱 --server/本地目录喂 --server → 全 2 |
| run --server 瘦客户端 | 不可达→2；submit→poll→`--wait` 超时→1；done+6 产物 sha256 校验→0；409 attach→0；lost→1；needs_auth→2；fault→1；submit 422→2（假 server 逐路径构造） |
| web | 锁持→"已在运行"+0（webbrowser.open 无浏览器静默退化）；新 data-dir 真起 uvicorn→/api/health 200+根 200 |
| export | epub/docx `--mock`→0；裸 zip/缺失→`无法识别`+1；`--glossary` csv→0/死路径→1 |
| doctor | 本机 9/9 ok→0（含真网关探活 200/214 models） |
| share pack/unpack | 真任务行打包→0（七组 key_parts 齐）；`-o` 目录/显式→0；round-trip→0；敌意名 `..share.zip` 消毒→`share-unpacked`；非 zip→1 |
| tools install-tectonic | 系统件在场→0；缺件+TEXLATE_NO_DOWNLOAD→1 |

## 观察（非 bug，记档）

1. `run` tiny 文档 verdict=`partial`（mock 译文 cjk_chars=4<20）——判定语义正常。
2. `_thin_wait` 返 `lost` 后仍调一次 `_thin_download`（清单 404→空 artifacts 无害，cli.py:403）。
3. `export` 无 --mock 且无 key → 文档化回落 MockTranslator；`TEXLATE_TRANSLATOR=gateway` 无 key → 空 key GatewayTranslator 分段 fault 非崩溃（cli.py:664-675，预期）。
4. `xlat/pipeline.py` 在飞面未触——MockTranslator 路径无异常。

外部问题清单：空。
