# 工具与运维手册

汇总本仓全部可复用工具：产品 CLI、`scripts/` 运维脚本、`bench/py/` 评测器与批跑件、`bench/ts/` 与 `web/` 冒烟工具，以及从开发过程沉淀的通用运维手法。路径均为仓内相对路径；逐件以文件头注释核实过用途。

## 1. 产品 CLI（`uv run texlate …`）

下表只列命令面，完整用法、旗标与环境变量见 `guide/cli.md`。

| 命令                             | 用途                                                                                         |
| -------------------------------- | -------------------------------------------------------------------------------------------- |
| `texlate fetch <id>`             | arXiv 取源：HEAD→GET→sniff→解包→主文件定位→钉版缓存；`--offline` 零网络只查本地缓存          |
| `texlate parse <tex>`            | Gullet+Segmenter 半解析分块；`--no-flatten` 不展平 `\input`                                  |
| `texlate run <id\|dir>`          | mock 端到端（normalize→mock 翻译→ctex 注入→编译→判定）；`--server` 瘦客户端提交 web 任务队列 |
| `texlate web`                    | 起 FastAPI+SSE 服务与 SPA 阅读器（SPA 需先 `scripts/build-web.sh`）                          |
| `texlate export`                 | 双语插译导出 EPUB/DOCX                                                                       |
| `texlate share pack/unpack`      | 任务产物社区共享包打包/解包（解包带 manifest 与 sha256 回验）                                |
| `texlate doctor`                 | 环境自检：python/引擎/CJK 字体/pdftotext/网关连通逐项判定                                    |
| `texlate version`                | 打版本号                                                                                     |
| `texlate tools install-tectonic` | tectonic 便携引擎安装（sha256 钉版矩阵）                                                     |

通用约定：BYOK 环境变量 `TEXLATE_BASE_URL` / `TEXLATE_API_KEY` / `TEXLATE_MODEL`（网关统一为 OpenAI 兼容端点）；离线总闸 `TEXLATE_OFFLINE=1` 等效各命令 `--offline`；日志级别 `TEXLATE_LOG` 与 `-v`/`-q` 旗标，落盘文件 `TEXLATE_LOG_FILE`。

## 2. `scripts/` — 运维脚本

| 脚本                    | 用途                                                                                                                                                                                                        |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent-links.sh`        | 重建 agent 入口软链层（`CLAUDE.md`→`AGENTS.md`、`.claude/skills/`→`.agents/skills/`），clone 后跑一次；目标是实体文件时拒绝覆盖                                                                             |
| `bench-backup.sh`       | trizone bench 根日备：`python3 -m kernel backup`（ledger + vault meta/manifest + lake durable/catalog + run keep-tier；vault 载荷字节归 restic 不管）+ tar 轮转保最新 3 份；`scripts/systemd/` 有配套 timer |
| `build-web.sh`          | web SPA 构建并拷入 `src/texlate/server/static/`（gitignored 产物）；`--no-install` 跳过 `npm ci`                                                                                                            |
| `crossnote-links.sh`    | MPE 预览 `.crossnote` 链接层重建（软链 + 硬链混合，编辑器原子保存换 inode 后需重跑）                                                                                                                        |
| `demo.sh [id] [--real]` | 端到端冒烟演示：fetch→parse→mock run→pdftotext 验 CJK；`--real` 追加真翻译段                                                                                                                                |
| `dev-smoke.sh [--keep]` | web 前端 e2e 一条龙：起 vite→从 dev 日志解析实际端口（漂移安全）→mock 鉴别→playwright 冒烟→只杀自己进程                                                                                                     |

| `fmt-shell.sh` | git-format-staged 的 stdin→stdout formatter：zsh shebang 原样透传，其余按 `shfmt -i 2` |
| `git-stash-export.sh` | stash 事故无损取证：tracked + untracked 两树导出 scratch，只读 stash 不动工作区/索引 |
| `loc.sh [--cloc]` | 代码量统计：git 跟踪文件分桶 + 剔数据快照后缀 + 未跟踪档单列 |
| `pyspy-triage.sh <PID>` | py-spy 钉栈 triage：N 次 dump 栈签名逐项比对 + CPU 增量——全同+CPU 前进=疑似死循环/ReDoS、全同+CPU 平=阻塞待机、变动=健康推进 |
| `server-smoke.sh [port] [dir]` | `texlate web` 全链 curl 冒烟：起服→health→SPA→openapi→upload→SSE→产物 sha256→收尾只杀自己 PID |

子目录 `scripts/systemd/` 收 systemd --user unit 件——`texlate-bench-backup` service/timer（`texlate-errsweep` 已于 2026-09-29 随链路退役拆除）（`ExecStart` 写死部署机路径，迁移时按目标机调整）。旧 `scripts/gwcap/` 网关并发闸组件已删，取证走 git 历史。

## 3. `bench/py/` — spec 套、分析动词与内核

执行纪律：统一入口 `uv run python bench/py/bench …`——跑批 `bench run <spec> [k=v …]`（参数为位置序 `k=v`，各 spec 的合法键见文件头 docstring），分析 `bench <verb>`。spec 经 `specs/_shared.py` 接线引 `texlate.*`，必须走 uv venv；不引产品代码的 verbs/kernel 面系统 python3 可跑（个别 verb 内置 venv 自重 exec 兜底）。

### 3.1 spec 套（`bench/py/specs/`，`bench run <名>` 起批）

B1–B7 评测规格对应（分层契约见 `dev/bench-harness.md`）：

| spec             | 对应   | 用途                                                                                                       |
| ---------------- | ------ | ---------------------------------------------------------------------------------------------------------- |
| `parsebench`     | B1     | 产品解析管线评测：identity/leak/dead_ph/漏斗 + 分层加权池化；`n/seed/ids/layers/only`（layers 默认 core）  |
| `fixture_assert` | B2     | 陷阱断言跑分（`bench/fixtures/*.tex` 的 @Tnn/@Wnn/@Xn）                                                    |
| `compilebench`   | B3     | corpus base 臂编译基线：分层抽样 × 原文直编 × 双引擎                                                       |
| `fixloop_bench`  | B3     | fixloop 救回率 + 配方单源（tlnet 索引、CaseSink 沉淀）                                                     |
| `xlatbench`      | B4a    | 翻译硬契约回归：网关模型分层抽样，逐调用过 rules 校验（付费）                                              |
| `qualbench`      | B4b    | LLM-judge 翻译质量臂（ESA 协议错误标注 + 0–100 分）（付费）                                                |
| `e2e_mock`       | B5-A   | mock 端到端基线（产品 API 全链 + 破坏臂 pipeB/pipeC）                                                      |
| `e2e_real`       | B5-B/D | 真网关翻译 E2E：`fixloop`/`base` 臂位 + `ids/only/model/concurrency/timeout/oversize_cap/no_probe`（付费） |
| `validbench`     | B6     | 校验器破坏检出基准（rules/cst 逐 case 计时 + 对抗探针）                                                    |
| `alignbench`     | B7     | named-dest 锚点保留率（en/zh PDF 对配对）                                                                  |
| `gullet`         | —      | 展开机 corpus 实测：耗时/token 数/warning 分类 + 不动点重喂                                                |
| `wrapfloat`      | —      | wrapfig 绕排碰撞检出 + 降级修复验证（poppler 信号）                                                        |

管线与内核自检 spec：

| spec      | 用途                                                                        |
| --------- | --------------------------------------------------------------------------- |
| `soak`    | 生产主线五段链单 run 串行：ingest→parse→xlat→compile→fixloop（付费臂在内）  |
| `smoke`   | 检出自检 spec：三免费 stage 跑合成件，证明 checkout 可用                    |
| `census`  | 湖审计 spec：全部 manifested cell 走一遍，零付费                            |
| `quality` | 质量面代理指标 rescore：对既有 run 的账重算 leak/term/landmark 三族，纯本地 |

| `paid_stub` | 付费门全链 spec：可注入网关工厂，零真实花费验证 paid gate |

语料构建谱系（旧 `bench/py/corpus/build_*.py` 的 spec 重写）：

| spec            | 用途                                                        |
| --------------- | ----------------------------------------------------------- |
| `frame_build`   | `bench/frame/` 抽样框资产再生（corpus_* 的 ord-0 前置）     |
| `corpus`        | P2 主管线：簇下载→成员扫描→配额抽样→湖化物化→自检           |
| `corpus_layers` | 扩库层构建：holdout / dev_vol / dev_failmine / dev_recent   |
| `corpus_expand` | 扩库增量管线（→ 总 ~5000 篇）                               |
| `corpus_hot`    | OpenAlex 高引近期 hot 层：免费渠道抽样→钉版取源→湖/清单双写 |
| `corpus_sw`     | scholarweave/arxiv-latex (HF) 通道适配器 + dev_recent 层    |

### 3.2 分析动词（`bench/py/verbs/`，`bench <verb>` 调用）

| verb                   | 用途                                          |
| ---------------------- | --------------------------------------------- |
| `bench triage`         | records 聚类分诊 → triage 票 + index events   |
| `bench rundiff`        | 两 run 逐格终态迁移对比                       |
| `bench gate`           | pick_final 跨 run 终判 + scorecard（出口门）  |
| `bench dossier`        | run 档案汇编（pick_run 按 run_seq）           |
| `bench xlat-report`    | xlatbench eval_records → 模型榜               |
| `bench xlat-rejudge`   | 存 src/zh 本地重判（免网关）                  |
| `bench qual-report`    | qualbench 评判汇总                            |
| `bench booster-select` | nominations 池 → booster 选择集（确定性变换） |

### 3.3 观测与共享件

| 件                      | 用途                                                                                                                                                                                                           |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ops/status_panel/`     | 只读本机状态面板：单页自刷新 HTML，采集器各自故障隔离，脱管常驻；账本面已改指 kernel runs/index                                                                                                                |
| `ops/task_ping.py`      | 任务看板写入端：原子写 `tasks.d/*.json`，任何 agent/脚本可报进度                                                                                                                                               |
| `tests/_translators.py` | translator 工厂：mock/sabotage-b/sabotage-c/perturb + 破坏台账面——被 `specs/_sabotage.py` 与 `e2e_mock` 引用                                                                                                   |
| `specs/_*.py`           | spec 共享叶：`_shared`（base_url/接线）、`_benchlite`（records/编译常量，旧 benchlib 吸收面）、`_corpus_common`、`_sabotage`、`_fixloop`、`_fixture_matrix`、`_leak`、`_qmetrics`、`_qualframe`、`_xlat_async` |

### 3.4 ICLR 章节长度研究件

`iclr/map.py`（OpenReview 标题→arXiv id 三档映射）→ `iclr/fetch.py`（e-print 取源物化）/ `iclr/pdf.py`（无 arXiv 映射的 OpenReview PDF 兜底）→ `iclr/sections.py`（LaTeX 臂章节词数）/ `iclr/pdf_sections.py`（PDF 臂同口径）→ `iclr/stats.py`（双臂汇总 + 重叠论文校准 PDF 臂偏差）。

### 3.5 已删面（Wave-F 2026-09-23）

旧 harness 全部件已删、功能由 §3.1–§3.2 继任：`stagerun*.py`/`stage_*.py`/`wave.py`/`harvest.py`/`preflight_batch.py`/`gwpilot.*`（批跑 → `bench run` spec 套）；`triage.py`/`rundiff.py`/`gate_scorecard.py`/`quality_proxies.py`（→ 同名 verb / quality spec）；`parsebench.py`/`compilebench_v3.py`/`xlatbench.py`/`qualbench.py`/`validbench.py`/`alignbench.py`/`fixloop_bench.py`/`fixture_assert.py`/`gullet_bench.py`/`wrapfloat_bench.py`/`e2e_mock_bench.py`/`e2e_real_bench.py`（→ 同名 spec）；`benchlib.py`（→ `specs/_benchlite.py`）；`corpus/build_*.py` ×7（→ `corpus_*`/`frame_build` spec）；`report/` 19 件一次性横评/审计脚本（选型期已结案）；`runbook_loop.md`（→ `bench plan` + 各 spec docstring）。批前闸职责改由 `bench doctor`（环境/工具链/网关）与 `bench plan`（格数/估时预报）分担。

### 3.6 trizone-ledger 内核（`kernel/`）

`kernel/` 是 bench 内核（设计 `spec/bench-trizone.md`——绿地口径不设历史兼容面，架构图 `spec/assets/trizone-arch.svg`），单一 CLI 入口 `uv run python bench/py/bench <verb>`（等价 `PYTHONPATH=bench/py python -m kernel`），操作 `$TEXLATE_BENCH_ROOT` 下四区。子命令族：`init / run / plan / status / derive / sweep / prune / backup / doctor / fsck / spec`，`vault {verify,restore,adopt,tombstone,seed}`，`ledger {import,ingest,rebuild-index,tail-ingest}`，`lake {status,evict,register,absorb,pin,unpin}`，`cache {status,evict,rebuild}`，外加 §3.2 分析动词（verbs/ 惰性加载）。契约：写命令先跑轻档 sweep；`run`/`plan` 在 `$ROOT/PAUSE` 存在时拒跑；`--detach` 经 `locks.detach_with_lock` 重 exec、付费 spec 强制 `--max-cost`。

## 4. `bench/ts/` — JS 侧解析库横评

独立 `package.json`（在 `bench/ts/` 里 `npm ci`），CommonJS，与根 toolchain 无关。三件外部库选型期 bench：`bench-lu.js`（latex-utensils）、`bench-tsl.js`（tree-sitter-latex 原生绑定，ERROR/MISSING node 计量 + 增量重解析演示）、`ul_*.js` 四件（unified-latex：corpus 解析经 worker 线程隔离、tricky 断言、共享 helper）。

## 5. `web/` — 前端工具

- `web/dev/mock-api.ts` — vite dev 中间件 mock 后端（默认 ON，`VITE_MOCK_API=0` 关）；`/api/health` 回 `version:"mock"` 即 mock/真后端鉴别器；seed 任务覆盖各终态档。
- `web/scripts/smoke.mjs` — playwright-core e2e 冒烟（首页→提交→进度→阅读器→下载→响应式），自带 `package.json`；`WEB_BASE`/`PW_EXE` 覆盖，截图留 `scripts/shots/`。`guide_probe.mjs`/`guide_shot.mjs` 是一次性截图探针。
- `web/scripts/*_verify.mjs` 一族 — playwright 行为级实测族（引用/翻译卡/锚点/usages/sentalign/selsys/主题等），范式件是 `cite_verify.mjs`（hover 卡/Esc/click 跳+split 镜像/nav chip ↩↪/Backspace/触屏 tap/远端 meta/零 console 错，16 断言），打活服 `127.0.0.1:8765` + 真实任务 `t_d7c669e8b3c92149`（`TASK` 可换）。**环境坑**：本机 `/tmp` tmpfs 近满时 chromium `--disable-dev-shm-usage` 共享内存落盘即渲染进程 SIGTRAP（随机 Target crashed）——公共 bootstrap `web/scripts/lib/pwkit.mjs` 已收 chromium 探测（`PW_EXE` 覆盖）+ `PW_TMP`=`~/.cache/pw-tmp` 挪 TMPDIR 出 tmpfs 的根治 + `SHOTS`/`check`/`results` 计数，新 playwright 脚本 `import` 它而非照抄 preamble；另 `evaluate("string",arg)` 字符串函数不收 arg（静默 undefined），传参必须写真函数。
- 三件套自检：`npx tsc --noEmit && npx eslint . && npx vitest run`。

## 6. 运维手法沉淀（通用）

### 6.1 批跑与长任务

- **落账即 done**：`records/<stage>.jsonl` 行在盘上 = done，同 spec 同参重启按 `(idc,arm,variant)` dedup 无损续跑；同一 run 目录同时只许一个写者进程（kernel lock 强制）。`results.json` 式整体重写文件崩一次全丢，批一律走 append 账。
- **后台长批脱管**：超过半小时的批量一律 `setsid nohup` 脱离会话 + 日志直写文件 + 靠产物文件面监控进度，不挂在交互会话里等（或 `bench run --detach` 走 kernel 脱管）。
- **子集与层参数**：选样类 spec 默认只跑 core 层——要全量显式 `layers=core,booster,hot`（层名以 manifest 为准）；定点子集 `ids=<csv>`，抽样 `n=<N> seed=<S>`。
- **fixloop 收格口径**：floor 机制落地后收 fail + 特定 partial（floor_snap 保入场 PDF 回退），inject reject 不救。
- **快照隔离**：churn 期用 `cp -al` hardlink farm 钉语料/src 快照（顶层遍历不跟 symlink 目录，快照必须 hardlink），隔离 bench 与在飞改动。
- **批前闸**：大批量前跑 `bench doctor`（环境/工具链/网关逐项判定）+ `bench plan <spec>`（格数/dedup 桶/估时预报），429 先判瞬时限流再判死。
- **签名可分辨度**：发生率 p 的签名要看 ≥3 次需 n≈3/p 的样本量。

### 6.2 排障

- **挂死/慢文件三件套**：`python -X faulthandler` + `faulthandler.dump_traceback_later` 留现场；`cProfile` 按 cumulative 排序；monkeypatch 间谍免插桩追踪内部面。离奇死先查 OOM。
- **钉栈 triage**：疑似死循环/ReDoS 用 `scripts/pyspy-triage.sh`——栈签名零位移叠加 CPU 增量才定罪（sleep/阻塞读栈也纹丝不动）。
- **xelatex ~100 error 上限**：nonstopmode 不豁免——错误洪水会 mid-document abort 产截断 partial PDF（文末内容最先死，bibliography/锚点保留率异常先查这个）。
- **文本手术**：LaTeX 源码手术一律 python replace（sed 吃反斜杠）；含 `|` 的译文比对走 python sqlite3 API 而非 CLI 分列管道。
- **vite 端口漂移**：从 dev 日志 `Local:` 行解析实际端口；`/api/health` 的 `version:"mock"` 验明 mock 正身；杀进程按端口属主 + 进程启动时间，不 pkill 广播。
- **autofix 复核**：`ruff --fix` 类自动修复可能删出 bug（如把 `except Exception as e` 的 `as e` 删掉），autofix 后必须人工复核 diff。

### 6.3 多会话共仓纪律

- **stash 并发事故定式**：并发 `git stash -u`+pop 会把全队在途编辑收走。恢复绝不整 pop——`scripts/git-stash-export.sh` 无损导出两树，再 `git show "stash@{N}:<file>"` 逐文件自救（`git checkout stash@{N} -- paths` 会写索引，可能卷入别人暂存内容）。
- **hunk 级选择性暂存**：`git diff > patch` → 按 `@@` 切 hunk → `git apply --cached`——多人共用单文件时可脚本化拆 commit。
- **即验即提**：staged 文件会卡别人 commit（check 类 hook 扫全 index），`git add` 只点路径，commit 后 `git log -1` 验证（撞车会静默回滚）。
- **共享 append-only 区**（规则库分片/builtins）先广播冻结再改；交付验收四步：diff-stat → lint → pytest -x → commit 确认。
