# E2E 功能实测审计（2026-09-16，HEAD f461683）

> **结论**：端到端功能实测：真 arXiv id 与本地语料均走全链产出真实 CJK PDF；错误路径全结构化；web 可起可探可关。
> **状态**：时点证据（2026-09-16 口径）
> **日期**：2026-09-16（2026-09-20 迁入重编）

把产品当用户用一遍：CLI 面 → mock 端到端真实语料 → 错误路径 → web 服务。产物均在 `tmp/audit-e2e/`（gitignored）。

## 环境

- xelatex：TeX Live 2026/Arch（`/usr/bin/xelatex`）可用；tectonic 0.15.0 可用；pdffonts/pdfinfo/pdftotext 可用。
- 缺包记录（不修）：本机 TeX Live 无 `revtex4.cls`。

## 1. CLI 面

`uv run texlate --help`：version / fetch / parse / run / web 五个子命令，help 完整。

- `texlate version` → `texlate 0.1.0`
- `fetch {arxiv_id}`：取 e-print，支持钉版 `-v` / `--cache`
- `parse {path}`：半解析，`--out` 落 chunks.jsonl，`--flatten/--no-flatten`
- `run {source}`：mock 端到端（arXiv id 或本地目录），`-e auto|xelatex|tectonic`，`-w` 工作目录，`--keep`。文档退出码：0 clean/partial，1 编译失败，2 路由拒绝
- `web`：`--host/--port/--data-dir`

## 2. Mock 端到端（真实语料）

### 2.1 `texlate run bench/corpus/1706.03762 -w tmp/audit-e2e/run-1706.03762 --keep`

- 链路：route → normalize(11 files, 1 rewritten) → translate(10 files, 155 chunks, 0 fault, leftover_ph=0) → inject(ctex, line 33) → compile(tectonic, 1.52s, rc=0) → verdict
- 产物：`tmp/audit-e2e/run-1706.03762/_tect_out/ms.pdf`，1,283,141 B，12 页 letter
- pdffonts：FandolSong-Regular/Bold（CID Type 0C, Identity-H, embedded）在列——真中文字体
- pdftotext 抽 CJK：1744 字，译文为 mock 串「这是译文」；`\citep{}`/`$h_t$`/`\url{}` 原位保留
- verdict：`partial`，reasons=[warn:missing_chars, missing_character×2]，category=clean。退出码 0
- 「双语」定位澄清：mock 路径 PDF 为纯译文（散文整段替换），双语对照是 web reader 的对齐功能（`/api/task/{id}/reader`），非 PDF 内嵌

### 2.2 `texlate run bench/corpus/2501.14787 -w tmp/audit-e2e/run-2501.14787 --keep`

- 链路：normalize(22/6) → translate(20 files, 757 chunks, 0 fault) → inject → compile(tectonic, 13.85s, rc=0)
- 产物：`_tect_out/main.pdf`，909,158 B，81 页 letter；FandolSong+FandolHei 嵌入；CJK 抽取 18,603 字（含「目录」）
- verdict：`partial`，reasons=[errors>3 (14), first_error=undefined_cs, warn:invalid_utf8, missing_character×61]——有 14 个 undefined_cs 但仍出 PDF。退出码 0

### 2.3 `texlate run bench/corpus/1412.6980 -w tmp/audit-e2e/run-1412.6980 --keep`

- chunks=0、files=0：根因是语料本身——`arxiv.tex` 全文 13 行，正文只有 `\includepdf{0_adam_main.pdf}`（Adam 论文以整 PDF 分发），无散文可翻。`texlate parse` 同样 chunks=0/pieces=3，行为正确非 bug
- 产物：`_tect_out/arxiv.pdf` 15 页 A4 编译成功（原文重排），pdffonts 无 CJK 字体、抽取 0 字，verdict `partial` + `cjk_chars=0` 如实上报。退出码 0

### 2.4 `texlate run bench/corpus/0906.1291 -w tmp/audit-e2e/run-0906.1291 --keep`

- 链路全走到 compile：normalize(1/1) → translate(53 chunks) → inject(ctex line 56) → xelatex 编译失败 `File 'revtex4.cls' not found`（本机 TeX Live 缺包，非产品缺陷）
- verdict：`fail`/no_pdf/category=missing_file，first_error 正确抓取。退出码 1

### 2.5 真·用户流：arXiv id 直跑

- `texlate fetch 1706.03762 --cache tmp/audit-e2e/cache` → `{"status":"ok","resolved_version":7,"main_tex":"ms.tex"}`（在线，v7 钉版落缓存）
- `texlate run 1706.03762 --cache tmp/audit-e2e/cache -w tmp/audit-e2e/run-arxiv-1706 --keep` → 命中缓存复跑全链，结果与 2.1 完全一致（155 chunks / 1.28MB PDF / 1744 CJK）

## 3. 错误路径（无裸 traceback）

| 命令                                               | 结果                                                                    | 退出码 |
| -------------------------------------------------- | ----------------------------------------------------------------------- | ------ |
| `fetch 9999.99999`                                 | `{"status":"not_found"}` JSON                                           | 1      |
| `run /nonexistent/dir`                             | `{"status":"error","detail":"bad_id:..."}`（目录不存在→按 id 路由拒绝） | 1      |
| `run tmp/audit-e2e/pdfonly`（只放 PDF 的目录）     | `status:reject, reasons:["no main tex"]`                                | 2      |
| `parse /nonexistent.tex`                           | typer「File does not exist」                                            | 2      |
| `parse tmp/audit-e2e/bad.tex`（`\broken{` 不闭合） | 容忍半解析 chunks=0/pieces=4                                            | 0      |

退出码语义与 `cli.py:167` 文档一致：source 解析失败=1、pipeline reject=2、编译失败=1、clean/partial=0。

## 4. Web 服务

`uv run texlate web --port 8877 --data-dir tmp/audit-e2e/webdata`：

- `GET /api/health` → `{"ok":true,"version":"0.1.0","compilers":{"tectonic":true,"xelatex":true,"babeldoc":false}}`——编译器探测真实
- `GET /api/tasks` → `{"tasks":[]}`；openapi 列 14 条路由（translate/upload/task/cancel/retry/reader/settings/providers 等）
- `GET /` → 404（无前端 SPA bundle——当时记为 M3 占位符合预期；同批 m3 审计改判其为 SPA 交付断链：`server/static/` 缺失 + 打包未 force-include。该缺陷已于 2026-09-17 闭合：现 `static/` 经 `scripts/build-web.sh` + pyproject artifacts 随包分发，`mount_spa` 已在 `server/staticfiles.py`/`app.py` 接线）
- SIGTERM 干净关闭

## 5. 结论

端到端真通：真实 arXiv id 与本地语料目录均能走完「取源→normalize→mock 翻译→ctex 注入→编译→判定」全链产出含真实 CJK 的 PDF；错误路径全部结构化 JSON/干净报错；web 可起可探可关。唯一环境缺口：本机 TeX Live 缺 `revtex4.cls`（影响 revtex 类语料编译，已记录）。
