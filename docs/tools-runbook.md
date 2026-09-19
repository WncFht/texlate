# 工具与运维手册

> 2026-09-16 起维护。汇总本仓全部可复用工具：产品 CLI、`scripts/`、`bench/py/` 评测器、web 冒烟，以及从开发过程沉淀的运维手法。

## 1. 产品 CLI（`uv run texlate …`）

| 命令                                                        | 用途                                                                                                                                                                                       |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `texlate fetch <arxiv_id> [--offline]`                      | HEAD→GET→sniff→unpack→locate→钉版缓存（`~/.cache/texlate/src/{id}v{ver}/`）；`--offline` 零网络只查本地缓存（无缓存报 `offline_no_cache` 退出 1）                                          |
| `texlate parse <main.tex> [-o chunks.jsonl] [--no-flatten]` | v2 Gullet+Segmenter 半解析分块；`--no-flatten` 不展平 `\input`                                                                                                                             |
| `texlate run <id\|dir> [--keep -w DIR] [--offline]`         | mock 端到端（normalize→mock 翻译→ctex 注入→编译→judge）；stderr 实况（stage 行 + translate 进度条 + 修复帧），`-q` 关；`--offline`/`TEXLATE_OFFLINE=1` 取源零网络（本地目录源无影响，`--server` 不生效）；退出码 0 clean/partial、1 编译失败、2 路由拒绝 |
| `texlate run <id> --server URL`                             | 瘦客户端模式：提交到 FastAPI 任务队列，`--wait` 内先 SSE 实况（快照/stage/chunk/修复帧渲 stderr），非 SSE/断流自动回退轮询；`--model/--api-key/--base-url/--out`（BYOK 走 `x-texlate-*` 头）      |
| `texlate web [--host --port --data-dir]`                    | 起 FastAPI+SSE 服务（缺省 127.0.0.1:8765），SPA 需先 `scripts/build-web.sh`；日志落盘 `<data_dir>/logs/texlate.log`（4MB×3 轮转）                                                           |
| `texlate export <docx/epub>`                                | 双语插译导出                                                                                                                                                                               |
| `texlate share pack <task_id>`                              | 任务产物打社区共享包 `{share_key}.share.zip`（七组分键，见 shared-cache.md）                                                                                                               |
| `texlate share unpack <bundle>`                             | 共享包解包 + manifest/产物 sha256 全量回验（manifest ≤1MB、artifacts ≤64 条、声明合计 ≤300MB、成员按声明 size+1 有界读对账，违例 ShareError→`share_invalid`）                              |
| `texlate doctor`                                            | 环境自检：python/tectonic/xelatex/cjk 字体（ctex/fandol/sys-zh）/pdftotext/网关连通/data-dir/server-extra/babeldoc 逐项 ok/warn/fail/n/a                                                   |
| `texlate version`                                           | 打版本号                                                                                                                                                                                   |
| `texlate tools install-tectonic`                            | tectonic 便携引擎安装（sha256 钉版矩阵）                                                                                                                                                   |

BYOK 环境直配（免 settings.json）：`TEXLATE_BASE_URL` / `TEXLATE_API_KEY` / `TEXLATE_MODEL`。

离线总闸：`TEXLATE_OFFLINE=1` 等效 `fetch`/`run` 的 `--offline`——取源只查本地 src-cache（钉版精确查 `{id}v{ver}`、未钉版取已缓存最高版），无缓存报 `offline_no_cache` 退出 1，不静默降级联网。

日志与实况：`texlate` logger 挂 RichHandler 走 stderr（stdout 只留 JSON 契约面）。级别：`TEXLATE_LOG=debug\|info\|warning\|error\|off` > 旗标 > 缺省 WARNING；旗标 `-v`=INFO、`-vv`=DEBUG、`-q`=ERROR、`-qq`=CRITICAL——`-v`/`-q` 既可写子命令前（全局 callback 位）也可写 `run` 后（子命令位，覆盖全局）；`fetch -v` 是 `--version` 不是 verbose。日志文件：`TEXLATE_LOG_FILE=<path>` 指定、`=off` 关；server 入口（`web`/`python -m texlate.server`）缺省落 `<data_dir>/logs/texlate.log`（4MB×3 轮转、DEBUG 级、RedactFilter 脱敏）。

## 2. scripts/ — 运维脚本

| 脚本                                    | 用途                                                                                                                                                                                |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent-links.sh`                        | 重建 CLAUDE.md→AGENTS.md 与 .claude/skills 软链层（clone 后跑一次）                                                                                                                 |
| `build-web.sh [--no-install]`           | web SPA 构建并拷入 `src/texlate/server/static/`（gitignored 产物）                                                                                                                  |
| `crossnote-links.sh`                    | MPE 预览 .crossnote 链接层重建                                                                                                                                                      |
| `fmt-shell.sh`                          | gfs stdin→stdout formatter（zsh 透传，其余 shfmt -i 2）                                                                                                                             |
| `demo.sh [id] [--real]`                 | 端到端冒烟演示：fetch→parse→mock run→pdftotext 验 CJK（`--real` 追加网关真翻译）；默认样例 2105.11479                                                                               |
| `dev-smoke.sh [--keep]`                 | web e2e 一条龙：起 vite→日志解析实际端口（漂移安全）→mock 鉴别→`web/scripts/smoke.mjs`→只杀自己 PID                                                                                 |
| `server-smoke.sh [port] [dir]`          | texlate web 全链 curl 冒烟：起服→health→SPA→openapi→upload→SSE→artifact sha256→收尾                                                                                                 |
| `git-stash-export.sh [stash@{N}] [dir]` | stash 事故无损取证：tracked + `^3` untracked 两树导出 scratch（只读 stash，不动工作区/索引）                                                                                        |
| `loc.sh [--cloc]`                       | 代码量统计：ls-files 圈定 + 剔数据快照 + 分桶 + 未跟踪档（bench/results 有 170 万行生成 JSON，裸 cloc 会把数据当代码）                                                              |
| `pyspy-triage.sh <PID> [-n -i -o]`      | py-spy 钉栈 triage：N 次 dump 栈签名逐项比对 + utime/stime 增量——签名全同+CPU 前进=STUCK(疑似 ReDoS/死循环,exit 1)、全同+CPU 平=IDLE(exit 3)、变动=MOVING(exit 0)；`PYSPY_BIN` 覆盖 |

## 3. bench/py/ — 评测器与批跑（B1–B7 对应 docs/10）

| 脚本                                                                                                                                        | 对应   | 用途                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `parsebench.py`                                                                                                                             | B1     | 产品管线评测器：identity/leak/dead_ph/漏斗（corpus_v3 + corpus39）                                                               |
| `fixture_assert.py`                                                                                                                         | B2     | 陷阱断言跑分（fixtures/*.tex @Tnn）                                                                                              |
| `compilebench_v3.py`                                                                                                                        | B3     | corpus_v3 base 臂编译基线（分层抽样×双引擎）                                                                                     |
| `fixloop_bench.py`                                                                                                                          | B3     | fixloop 救回率 + 配方单源（TUNA_TLNET、TlpdbIndex、CaseSink）                                                                    |
| `xlatbench.py`                                                                                                                              | B4a    | 翻译硬契约回归（网关模型分层抽样，逐调用 L0 校验）                                                                               |
| `qualbench.py`                                                                                                                              | B4b    | LLM-judge 翻译质量臂（结构指标之外的质量维度）                                                                                   |
| `e2e_mock_bench.py`                                                                                                                         | B5-A   | mock 端到端基线（产品 API 全链）                                                                                                 |
| `e2e_real_bench.py`                                                                                                                         | B5-B/D | 真网关翻译 E2E：`--fixloop onfail`（救回臂）、`--base onfail`（归因臂）、`--layers hot`；自带 0 网络 preflight                   |
| `validbench.py`                                                                                                                             | B6     | 校验段破坏检出基准（L0/L1/L2）                                                                                                   |
| `alignbench.py`                                                                                                                             | B7     | named-dest 锚点保留率（en/zh PDF 对）                                                                                            |
| `stagerun.py`                                                                                                                               | —      | 分阶段批量驱动：`ingest/parse/xlat/compile/fixloop` 五子命令，append records jsonl，(id,arm,upstream) resume，`--sem` 网关信号量 |
| `triage.py`                                                                                                                                 | —      | records→tickets.jsonl 聚类 + metrics.jsonl 趋势 + report merge                                                                   |
| `wave.py` / `rundiff.py` / `report/dossier.py` / `gate_scorecard.py` / `report/mech_ids.py` / `report/defect_ledger.py`                     | —      | 修复波编排（选样/快照/scorecard/postmortem）+ records 迁移矩阵 + per-id 跨阶段失败链 + GATE 记分 + 机制/规则→id 反查 + 缺陷台账  |
| `status_panel.py` / `task_ping.py`                                                                                                          | —      | 批跑看板（`bench/results/status-panel/`）：任务态注册/心跳/聚合面板                                                              |
| `gwpilot.py`（+`gwpilot.md`）                                                                                                               | —      | 见缝插针批跑驱动：断点续跑队列 + 无分级网关场景的自适应并发闸兜底；`bench/queue/*.jsonl` 队列，`bench/work_gwpilot/` 状态        |
| `translators_bench.py`                                                                                                                      | —      | xlat 臂工厂：mock/sabotage-b/sabotage-c/perturb + ledger                                                                         |
| `preflight_batch.py`                                                                                                                        | —      | 批前一票闸（import walk+mock 链 + 磁盘+manifest+PATH+ 网关认证），`--no-net` 离线                                                |
| `runbook_loop.md`                                                                                                                           | —      | loop 批 12 步操作单（排序约束：zh/ 是臂间共享演化树）                                                                            |
| `corpus/build_corpus_v3.py` / `corpus/build_corpus_expand.py` / `corpus/build_hot_layer.py`                                                 | —      | 语料三层管线：core/booster→expand(+3800)→hot(OpenAlex 高引近期，日预算 85/轮）                                                   |
| `benchlib.py`                                                                                                                               | —      | 共享件：records jsonl/manifest/编译常量（纯 stdlib 零 IO）                                                                       |
| `report/v2_diff.py` / `gullet_bench.py` / `report/l2_attr_probe.py` / `report/export_realbook.py` / `macro_scan.py` / `rerun_xelatex.py` 等 | —      | 专项探针                                                                                                                         |
| `report/` / `corpus/` / `scratch/`                                                                                                          | —      | `report/`=一次性审计/横评/归因脚本、`corpus/`=语料管线（均含 `sys.path` shim 引顶层 lib）、`scratch/`=一次性探针（不复用承诺）   |

外部库横评（选型期已结案）：`report/bench_pylatexenc.py` `report/texsoup_bench.py` `report/plastex_bench.py` `report/ieeA_bench.py` + `bench/ts/`。

**执行纪律**：import `texlate.*` 的脚本必须 `uv run python bench/py/…`；纯 stdlib 工具系统 python3 即可。

## 4. web/ — 前端工具

- `web/dev/mock-api.ts`：vite dev 中间件 mock 后端（默认 ON，`VITE_MOCK_API=0` 关）；`/api/health` 回 `version:"mock"` 即 mock/真后端鉴别器；seed 任务 done/partial/fault/needs_auth 全档。
- `web/scripts/smoke.mjs`：playwright-core 21 断言 e2e 冒烟（home→提交→进度棋盘格→阅读器→下载菜单→响应式）；`WEB_BASE`/`PW_EXE` 覆盖；截图留 `scripts/shots/`。
- 三件套自检：`npx tsc --noEmit && npx eslint . && npx vitest run`。

## 5. 运维手册（会话沉淀的坑与手法）

### 5.1 网关接入

- **接法**：默认本地 `http://127.0.0.1:3003`（`TEXLATE_BASE_URL` / Settings 页覆盖任意 OpenAI 兼容端点）；bench/脚本/curl 一律走 env。
- **429 是瞬时限流**：先换端点/降并发再判死；批量烧配额前跑 `preflight_batch.py`。
- **arXiv 日预算 ~180 req**：取源 `--limit 85`/轮 + durable cron 续跑（CronCreate 默认 session-only，要 `durable:true`）。
- 网关探活最小集：`/healthz` 版本串、`/v1/models` 无 auth 401=活、带 auth 列模型、真 chat probe。

### 5.2 排障手法

- **挂死/慢文件三件套**：`timeout 25 uv run python -X faulthandler -` + `faulthandler.dump_traceback_later(20, exit=True)` 留现场；`cProfile` 内联 sort_stats("cumulative")；**monkeypatch 间谍**免插桩追踪内部面（包 `Scanner._flush_run`/`PlaceholderIssuer.new` + `traceback.extract_stack()`）。离奇死先查 OOM（dmesg）。
- **xelatex ~100 error 上限**：nonstopmode 不豁免——错误洪水 → mid-document abort → 截断 partial pdf（bibliography 在文末最先死，B7 归因实测）。锚点保留率异常先查这个。
- **ruff --fix 会删出 bug**：F841 autofix 把 `except Exception as e` 的 `as e` 删掉，payload repr 变错对象——autofix 后必须人工复核 diff。
- **`command grep` 反 alias**：本机 grep=ugrep 吃 .gitignore——查 gitignore'd 文件（bench/results 等）必须 `command grep`，否则静默漏报。
- **进程→会话归因**：ss -tnp→ps cmdline 指纹→/proc cwd→transcript mtime→grep 指纹→`This session is` fleet 名→SendMessage 处置。
- **nft 调试四件套**：nftrace（`meta nftrace set 1` + `nft monitor trace`）、counter 规则定位断包层、`nstat -az` 前后 diff、按 handle 删规则；`ss -K` 杀单条连接逼重握手；回滚=`nft delete table`。
- **ts-input 反欺骗**：tailscaled 的 `ip saddr 100.64.0.0/10 iifname != tailscale0 drop` 会杀 lo 上的 un-NAT 回包；tailscaled 重启重插 jump → bypass 规则要 systemd drop-in 兜底。
- **sqlite3 CLI 管道不可靠**：译文含 `|` 会把分列打歪——精确比对走 python sqlite3 API。
- **sed 吃反斜杠**：LaTeX 文本手术一律 python replace。
- **vite 端口漂移**：从 dev log 解析 `Local:` 行取真实口；`version:"mock"` 验明正身；杀进程按 ss 端口属主 + `ps -o lstart=` 启动时间，不 pkill。
- **SSE 累积 UI 断言**：隔 2s 数两次 DOM 量断言单调不回落（棋盘格回归手法）。

### 5.3 bench/批跑语义

- **`--layers` 默认只 core**：stagerun/e2e_real_bench 要全量必须显式 `--layers core,booster,hot`；`--sem 4`/`--concurrency 4` 对齐网关并发闸。
- **stagerun 五子命令序**：`ingest→parse→xlat --arm mock→compile --arm zh --xlat-arm mock→compile --arm base→fixloop --on nonclean`；同结果目录只许一个 stagerun 进程（records 单写者 append）；跨天续跑钉 `--dir`。records 速览：per-file `wc -l` + `command grep -c '"status": "ok"\|"clean"\|"partial"'`。
- **triage.py**：`--selftest` 合成自检；`all DIR` 三件套；无 records 旧目录自动降级 `tickets-legacy.jsonl`；**冒烟跑必带 `--no-global`**（metrics.jsonl 是 git 跟踪文件，会污染）。
- **zh/ 是臂间共享就地演化树**：compile zh(mock) 必先于 real/sabotage；sabotage 两臂放全批最后（污染 zh/）；续跑靠同 `--n/--seed/--layers` 确定性选样 + `--xlat-arm` 钉 provenance。
- **fixloop 只在 fail 上跑**：partial 已有 PDF，halt_on_error+ 树改写会弄丢它（实测回退 2/3）。（勘误 2026-09-17：floor 机制落地后 fixloop 亦收 misschar/error 类 partial——`_want_fix` 改判 fail+ 特定 partial，floor_snap 保入场 PDF 回退；见 docs/10 L120 勘误。）
- **records.jsonl append = 行在即 done**；results.json 整体重写崩一次全丢。SIGTERM 后同参重启即无损续跑（`_paper_done` 秒跳）；**但运行中改 bench 脚本本身**会新旧逻辑混用（进程持旧内存映像，resume 按新代码跑）。
- **tectonic 版本岔路**：0.15 裸 CLI 用 `--bundle`，0.17 `-X compile` 要 `--web-bundle`；`-vv` 放 `-X` 后 `compile` 前；bundle 不可达时**静默卡**——先 `curl -sI` 探活 + `XDG_CACHE_HOME` 隔离复现。
- **uv.lock churn**：UV_DEFAULT_INDEX 抖动让每个 commit 前都得 `git checkout uv.lock`——约 15 次/会话，入链前先看 diff 是不是纯 index churn。
- **frozen src 快照**：`TEXLATE_SRC` env（e2e_real_bench/stagerun 支持）或 `cp -al` hardlink farm——churn 期隔离 bench 与在飞改动；语料快照**必须 hardlink**（顶层 rglob 不跟 symlink 目录）。
- **冒烟残留会进 append manifest**：扩库 QC 按时间戳归因。
- **withdrawn stub**：`format:"stub"` 的 124B withdraw.txt 不是缺口。
- **签名可分辨度**：n≈3/p（看到发生率 p 的签名 ≥3 次）。

### 5.4 多会话协作纪律（三会话会战实测）

- **stash 并发事故定式**（2026-09-16 实录）：`git stash -u`+pop 撞并发提交未 drop → 全队在途 tracked 编辑被收走。恢复：**绝不整 pop**——`scripts/git-stash-export.sh` 无损导出两树 → 各 agent `git show "stash@{0}:f" > f` 逐文件自救；`git checkout stash@{0} -- paths` **会写索引**（曾把别人暂存 hunk 卷进自己 commit）；事后禁令升级为「禁止一切 git 状态命令」。
- **hunk 级选择性暂存**（非交互 `git add -p`）：`git diff > patch` → python 按 `@@` 切 hunk → `git apply --cached --check` 再 `--cached`——多人共用单文件时可脚本化拆 commit。
- staged 文件卡别人 commit（ruff-check 扫全 index）→ 即验即提、`git add` 只点路径。
- commit 撞车静默回滚 → `git commit` 后必 `git log -1` + `status --short` 验证。
- 共享 append-only 区（rules.yaml/builtins.py）先广播冻结再改。
- 等 teammate 落地用 `sleep N && grep 特征串` 轮询核实，不空等。
- subagent 写不了 `bench/results/**/SUMMARY.md`（harness 拦）→ 全文 SendMessage 给 leader 代落盘。
- SendMessage 协议帧：shutdown_request 必须发结构化对象 `{"type":"shutdown_request",...}`，塞 `message=` 文本会被拒。
- Agent 批量 spawn 有锁：一次十几个会撞 spawn 锁失败——按名重试即可。
- 隔离陈旧在途文件用**部分路径 stash**：`git stash push -m "<原因>" -- <paths>`（可逆，比删强）。
- 交付验收四步：diff-stat → ruff check+format → pytest -x -q → commit 确认。

## 6. 会话考古方法论

`uv run ~/.agents/skills/session-transcripts/scripts/session_transcript.py {ls|show|grep|get|ask|export}`——NDJSON transcript 不直读（单行 MB 级），按 清单→地图→定位→取证 成本升序挖；`ask` 让原会话自答最省；子代理在 `<sid>/subagents/`，`show` 自动附录。
