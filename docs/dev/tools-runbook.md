# 工具与运维手册

汇总本仓全部可复用工具：产品 CLI、`scripts/` 运维脚本、`bench/py/` 评测器与批跑件、`bench/ts/` 与 `web/` 冒烟工具，以及从开发过程沉淀的通用运维手法。路径均为仓内相对路径；逐件以文件头注释核实过用途。

## 1. 产品 CLI（`uv run texlate …`）

下表只列命令面，完整用法、旗标与环境变量见 `guide/cli.md`。

| 命令 | 用途 |
| --- | --- |
| `texlate fetch <id>` | arXiv 取源：HEAD→GET→sniff→解包→主文件定位→钉版缓存；`--offline` 零网络只查本地缓存 |
| `texlate parse <tex>` | v2 Gullet+Segmenter 半解析分块；`--no-flatten` 不展平 `\input` |
| `texlate run <id\|dir>` | mock 端到端（normalize→mock 翻译→ctex 注入→编译→判定）；`--server` 瘦客户端提交 web 任务队列 |
| `texlate web` | 起 FastAPI+SSE 服务与 SPA 阅读器（SPA 需先 `scripts/build-web.sh`） |
| `texlate export` | 双语插译导出 EPUB/DOCX |
| `texlate share pack/unpack` | 任务产物社区共享包打包/解包（解包带 manifest 与 sha256 回验） |
| `texlate doctor` | 环境自检：python/引擎/CJK 字体/pdftotext/网关连通逐项判定 |
| `texlate version` | 打版本号 |
| `texlate tools install-tectonic` | tectonic 便携引擎安装（sha256 钉版矩阵） |

通用约定：BYOK 环境变量 `TEXLATE_BASE_URL` / `TEXLATE_API_KEY` / `TEXLATE_MODEL`（网关统一为 OpenAI 兼容端点）；离线总闸 `TEXLATE_OFFLINE=1` 等效各命令 `--offline`；日志级别 `TEXLATE_LOG` 与 `-v`/`-q` 旗标，落盘文件 `TEXLATE_LOG_FILE`。

## 2. `scripts/` — 运维脚本

| 脚本 | 用途 |
| --- | --- |
| `agent-links.sh` | 重建 agent 入口软链层（`CLAUDE.md`→`AGENTS.md`、`.claude/skills/`→`.agents/skills/`），clone 后跑一次；目标是实体文件时拒绝覆盖 |
| `build-web.sh` | web SPA 构建并拷入 `src/texlate/server/static/`（gitignored 产物）；`--no-install` 跳过 `npm ci` |
| `crossnote-links.sh` | MPE 预览 `.crossnote` 链接层重建（软链 + 硬链混合，编辑器原子保存换 inode 后需重跑） |
| `demo.sh [id] [--real]` | 端到端冒烟演示：fetch→parse→mock run→pdftotext 验 CJK；`--real` 追加真翻译段 |
| `dev-smoke.sh [--keep]` | web 前端 e2e 一条龙：起 vite→从 dev 日志解析实际端口（漂移安全）→mock 鉴别→playwright 冒烟→只杀自己进程 |
| `errsweep.sh` | 错误清扫 agent 启动器：隔离 worktree 上按 runbook 蒸馏修复，flock 单实例；见 `dev/automation.md` |
| `find-gateway-hog.sh` | 「谁在打网关」归因链：连接→进程→会话指纹逐级定位 |
| `fmt-shell.sh` | git-format-staged 的 stdin→stdout formatter：zsh shebang 原样透传，其余按 `shfmt -i 2` |
| `git-stash-export.sh` | stash 事故无损取证：tracked + untracked 两树导出 scratch，只读 stash 不动工作区/索引 |
| `gw-health.sh` | 网关多路健康探测聚合单行报告，任一失败 exit 1（URL/超时均可 env 覆盖） |
| `gw-tunnel.sh` | 网关 SSH 隧道常驻管理（`start/stop/status/logs`）：重连循环 + setsid 脱管，产品链要求 localhost 端点时把远端服务映射回本地 |
| `loc.sh [--cloc]` | 代码量统计：git 跟踪文件分桶 + 剔数据快照后缀 + 未跟踪档单列（`bench/results/` 有百万行级生成 JSON，裸 cloc 会把数据当代码） |
| `pyspy-triage.sh <PID>` | py-spy 钉栈 triage：N 次 dump 栈签名逐项比对 + CPU 增量——全同+CPU 前进=疑似死循环/ReDoS、全同+CPU 平=阻塞待机、变动=健康推进 |
| `server-smoke.sh [port] [dir]` | `texlate web` 全链 curl 冒烟：起服→health→SPA→openapi→upload→SSE→产物 sha256→收尾只杀自己 PID |
| `tcp-relay.py <lport> <rhost> <rport>` | 微型 asyncio TCP 转发（纯 stdlib），让只认 localhost 的组件吃到远端服务 |

两个子目录：`scripts/systemd/` 是 errsweep 的 systemd --user service/timer 样例（`ExecStart` 指向 `scripts/errsweep.sh`，部署时按本机路径调整）；`scripts/gwcap/` 是本机网关并发闸组件（nftables REDIRECT + 信号量代理 + bypass 规则维护），属单机部署载荷、已退役留档。

## 3. `bench/py/` — 评测器与批跑件

执行纪律：import `texlate.*` 产品代码的脚本必须 `uv run python bench/py/…`（venv 才有 httpx/typer 等依赖）；纯 stdlib 工具（triage、rundiff、benchlib、status_panel 等）系统 python3 可跑，各文件头有注明。

### 3.1 B1–B7 评测器（对应评测规格，分层见 `dev/bench-harness.md`）

| 脚本 | 对应 | 用途 |
| --- | --- | --- |
| `parsebench.py` | B1 | 产品解析管线评测器：identity/leak/dead_ph/漏斗 + 分层加权池化统计 |
| `fixture_assert.py` | B2 | 陷阱断言跑分（`bench/fixtures/*.tex` 的 @Tnn/@Wnn/@Xn） |
| `compilebench_v3.py` | B3 | corpus base 臂编译基线：分层抽样 × 原文直编 × 双引擎 |
| `fixloop_bench.py` | B3 | fixloop 救回率 + 配方单源（tlnet 索引、CaseSink 沉淀） |
| `xlatbench.py` | B4a | 翻译硬契约回归：网关模型分层抽样，逐调用过 L0 校验 |
| `qualbench.py` | B4b | LLM-judge 翻译质量臂（ESA 协议错误标注 + 0–100 分） |
| `e2e_mock_bench.py` | B5-A | mock 端到端基线（产品 API 全链 + 破坏臂 pipeB/pipeC） |
| `e2e_real_bench.py` | B5-B/D | 真网关翻译 E2E：`--fixloop onfail` 救回臂、`--base onfail` 归因臂；自带零网络 preflight |
| `validbench.py` | B6 | 校验器破坏检出基准（L0/L1 逐 case 计时 + 对抗探针） |
| `alignbench.py` | B7 | named-dest 锚点保留率（en/zh PDF 对配对） |

另有两件专项 bench：`gullet_bench.py`（展开机 corpus 实测：耗时/token 数/warning 分类 + 不动点重喂）与 `wrapfloat_bench.py`（wrapfig 绕排碰撞检出 + 降级修复验证，poppler 信号）。

### 3.2 stagerun 分阶段批跑族

| 件 | 用途 |
| --- | --- |
| `stagerun.py` | 分阶段批量驱动：`ingest/parse/xlat/compile/fixloop` 五子命令，append 式 records jsonl，按 `(id, arm, upstream)` resume，`--sem` 网关信号量 |
| `stagerun_lib.py` | stagerun 内核：records 账/resume 谓词/run_meta/选样；不引 `texlate.*`，`TEXLATE_SRC` 快照接线也在这里 |
| `stage_{ingest,parse,xlat,compile,fixloop}.py` | 五个 stage 各自的 executor（`work/{id}/` 产物树契约见 stagerun 模块 docstring） |
| `translators_bench.py` | `xlat --arm` 的 translator 工厂：mock/sabotage-b/sabotage-c/perturb + 破坏台账面 |
| `preflight_batch.py` | 批前一票闸：import walk + mock 链 + 磁盘 + manifest + 工具链 + 网关认证，`--no-net` 离线 |
| `runbook_loop.md` | 整批操作单：前置检查→五 stage 序列→triage→波次，含估时表与排序约束 |

### 3.3 归因、编排与观测

| 件 | 用途 |
| --- | --- |
| `triage.py` | records→`tickets.jsonl` 签名聚类 + `metrics.jsonl` 趋势 + report 生成；`--selftest` 合成自检；冒烟跑必带 `--no-global`（全局 metrics 是跟踪文件） |
| `rundiff.py` | 两个 stagerun 结果目录逐格迁移矩阵（A→B 改善/退化/单侧，`--deep` 同态 churn 清单） |
| `wave.py` | 修复波编排壳：`run`（id 集/机制标签/规则反查开波）+ `postmortem`（rundiff+ 案卷 join）+ `scorecard`，只编排不重实现 |
| `gate_scorecard.py` | 出口门记分卡：compile/fixloop 末条 records 按 end-state 与 union 两口径并列 |
| `status_panel.py` | 只读本机状态面板：单页自刷新 HTML，采集器各自故障隔离，脱管常驻 |
| `task_ping.py` | 任务看板写入端：原子写 `tasks.d/*.json`，任何 agent/脚本可报进度 |
| `gwpilot.py`（+`gwpilot.md`） | 见缝插针批跑驱动：断点续跑队列 + 无分级网关场景的自适应并发闸代理兜底 |
| `quality_proxies.py` | 质量面代理指标后算：leak 残留率/术语一致率/named-dest 存活率，对既有 run 目录纯后算 |

### 3.4 ICLR 章节长度研究件

`iclr_map.py`（OpenReview 标题→arXiv id 三档映射）→ `iclr_fetch.py`（e-print 取源物化）/ `iclr_pdf.py`（无 arXiv 映射的 OpenReview PDF 兜底）→ `iclr_sections.py`（LaTeX 臂章节词数）/ `iclr_pdf_sections.py`（PDF 臂同口径）→ `iclr_stats.py`（双臂汇总 + 重叠论文校准 PDF 臂偏差）。

### 3.5 共享件与子目录

- `benchlib.py` — records jsonl 读写/manifest/编译常量，纯 stdlib 零 IO，系统 python3 与 uv 皆可载。
- `corpus/` — 语料管线：`build_corpus_v2.py`（分层随机层）、`build_corpus_v3.py`（簇下载→成员扫描→配额抽样 core/booster）、`build_corpus_expand.py`（扩库增量）、`build_corpus_layers.py`（holdout/dev_vol/dev_failmine 层）、`build_corpus_m1k.py`（m1k 四源评测集）、`build_hot_layer.py`（OpenAlex 高引近期 hot 层）、`build_sw_layer.py`（scholarweave 脱水通道 dev_recent）。日更链 2026-09-21 退役，`daily_arxiv.py` 已删（见 `dev/automation.md`）。
- `report/` — 一次性审计/横评/归因脚本（19 件，均含 `sys.path` shim 引顶层 lib）：外部库选型横评（`bench_pylatexenc`/`texsoup_bench`/`texsoup_diverge`/`plastex_bench`/`ieeA_bench`，选型期已结案）、质量评测工具链（`qualanchor`/`qualdrift`/`qualfreeze`/`qualsample`/`qualstats`）、台账与反查（`defect_ledger`/`dossier`/`mech_ids`/`mech_backfill`）、专项探针（`export_realbook`/`extract_l2_fixture`/`l2_attr_probe`/`layout_bench`/`v2_diff`）。

### 3.6 trizone-ledger 内核（`kernel/`）

`kernel/` 是新 bench 内核（设计 `dev/bench-redesign-v2-trizone.md`，架构图 `dev/assets/trizone-arch.svg`），单一 CLI 入口 `PYTHONPATH=bench/py python -m kernel <verb>`（prog 名 `bench`），操作 `$TEXLATE_BENCH_ROOT` 下四区。子命令族：`init / run / plan / status / export / derive / sweep / prune / backup / doctor / fsck / spec`，`vault {verify,restore,adopt,tombstone}`，`ledger {import,ingest,rebuild-index,tail-ingest}`，`lake {status,evict,register}`，`triage/gate/dossier` 是未迁移桩（exit 2）。契约：写命令先跑轻档 sweep；`run`/`plan` 在 `$ROOT/PAUSE` 存在时拒跑；`--detach` 经 `locks.detach_with_lock` 重 exec、付费 spec 强制 `--max-cost`。旧世界 stagerun 族（§3.2）仍是现役评测面，内核接管前两者并存。

## 4. `bench/ts/` — JS 侧解析库横评

独立 `package.json`（在 `bench/ts/` 里 `npm ci`），CommonJS，与根 toolchain 无关。三件外部库选型期 bench：`bench-lu.js`（latex-utensils）、`bench-tsl.js`（tree-sitter-latex 原生绑定，ERROR/MISSING node 计量 + 增量重解析演示）、`ul_*.js` 四件（unified-latex：corpus 解析经 worker 线程隔离、tricky 断言、共享 helper）。

## 5. `web/` — 前端工具

- `web/dev/mock-api.ts` — vite dev 中间件 mock 后端（默认 ON，`VITE_MOCK_API=0` 关）；`/api/health` 回 `version:"mock"` 即 mock/真后端鉴别器；seed 任务覆盖各终态档。
- `web/scripts/smoke.mjs` — playwright-core e2e 冒烟（首页→提交→进度→阅读器→下载→响应式），自带 `package.json`；`WEB_BASE`/`PW_EXE` 覆盖，截图留 `scripts/shots/`。`guide_probe.mjs`/`guide_shot.mjs` 是一次性截图探针。
- `web/scripts/cite_verify.mjs` — 引用 UX 行为级实测（hover 卡/Esc/click 跳+split 镜像/nav chip ↩↪/Backspace/触屏 tap/L2 meta/零 console 错，16 断言），打活服 `127.0.0.1:8765` + 真实任务 `t_d7c669e8b3c92149`（`TASK` 可换）。**环境坑**：本机 `/tmp` tmpfs 近满时 chromium `--disable-dev-shm-usage` 共享内存落盘即渲染进程 SIGTRAP（随机 Target crashed）——脚本内置 `TMPDIR=~/.cache/pw-tmp` 根治，新 playwright 脚本照抄此两行；另 `evaluate("string",arg)` 字符串函数不收 arg（静默 undefined），传参必须写真函数。`blender_verify.mjs`/`paper_theme_verify.mjs` 是 PDF 暗色管线的同款实测。
- 三件套自检：`npx tsc --noEmit && npx eslint . && npx vitest run`。

## 6. 运维手法沉淀（通用）

### 6.1 批跑与长任务

- **records append 即账目**：`records/{stage}.jsonl` 行在盘上 = done，同参重启即无损续跑；同一结果目录同时只许一个 stagerun 进程（单写者 append，双开会重复跑且行交错）。`results.json` 式整体重写文件崩一次全丢，新批一律走 append 账。
- **后台长批脱管**：超过半小时的批量一律 `setsid nohup` 脱离会话 + 日志直写文件 + 靠产物文件面监控进度，不挂在交互会话里等。
- **`--layers` 默认只 core**：stagerun/e2e_real_bench 要全量必须显式 `--layers core,booster,hot`（实际层名以 manifest 为准）。
- **`zh/` 是臂间共享就地演化树**：compile zh(mock) 必先于 real/sabotage；sabotage 两臂放全批最后（污染 zh/）；续跑靠同 `--n/--seed/--layers` 确定性选样 + `--xlat-arm` 钉 provenance。
- **fixloop 收格口径**：floor 机制落地后收 fail + 特定 partial（floor_snap 保入场 PDF 回退），inject reject 不救。
- **快照隔离**：churn 期 `TEXLATE_SRC` 指 frozen src 快照（或 `cp -al` hardlink farm——语料快照必须 hardlink，顶层遍历不跟 symlink 目录），隔离 bench 与在飞改动。
- **批前闸**：大批量前跑 `preflight_batch.py`（import walk + mock 链 + 磁盘 + manifest + 网关认证），429 先判瞬时限流再判死。
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
