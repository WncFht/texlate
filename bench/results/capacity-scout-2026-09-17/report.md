# capacity-scout — capacity fail 统一资源上限面审计（只读）

> 2026-09-17 收口。overseer 背景项：recut 55 格 fail 里 capacity×4，问有无统一资源上限配置面。**结论：无统一面，也不该为这 4 格建——它们全是 TeX 内部 input stack 爆栈（多半是拼接产物真无限递归），需要逐格根因修复而非调大上限。** 配额故障中完成，全 Read 核实，file:line 精确。

## (c) 4 格 capacity 实际耗尽项

recut2-join-2026-09-17 `unfixable:capacity`：1404.0037 / 1706.00076 / 1706.00335 / 2105.00111（全 zh 臂 xelatex）。日志实证（stagerun-loop1 records/compile.jsonl + modec）：每个实例都是 `TeX capacity exceeded, sorry [input stack size=10000]`——kpathsea `stack_size` cnf var，即 TeX 内部输入/宏展开栈，**不是**墙钟/OS 内存/fd。`capacity` 类只是 log 正则 `TeX capacity exceeded`（rules.yaml:312）；现无规则调任何上限响应它。诚实附注：stack_size=10000 爆栈通常是 `\input`/宏真递归——调大栈只救部分格，多数要根因修。

## (a) 上限旋钮清单

| 点位 | 类型 | 值 | 今日可调？ |
|---|---|---|---|
| compile/engine.py:50 `DEFAULT_TIMEOUT` | 模块常量 | 240s | 可——`Engine.compile(timeout=)` 参数 |
| compile/engine.py:55 `_TECTONIC_RETRY_TIMEOUT` | 常量 | 120s 重试上限 | 否 |
| compile/engine.py:1205 `per_pass` | 派生 | 240/2=120s/趟 | 经 timeout |
| fixloop rules.yaml `meta.loop.timeout_sec` ~:61 | yaml | 120s | 可——`fixloop(compile_timeout=)` > yaml > engine 默认（fixloop/engine.py:1237-1246） |
| cli.py:228 `run --timeout` | CLI flag | 240s | 可——流 compile + fixloop 重编 |
| bench/py/e2e_mock_bench.py:807 `--timeout` | flag | 240s | 可——同管（_Job.timeout，e2e.py:336） |
| bench/py/alignbench.py:889 `--timeout` | flag | 240s | 可 |
| bench/py/compilebench_v2.py `TIMEOUT` | 常量 | 字面量 | 仅改码 |
| **server worker.py:181 `COMPILE_TIMEOUT`** | 常量 | 240s | **断头路**——ctor 有 `compile_timeout` 参（:1139）但 create_app 从不传（app.py:432-441）；settings.json FIELDS 只有 quota_max_*；无 env 无 flag |
| worker 四处调用点（:2710/:2795/:2835/:3025） | 全 `self._compile_timeout` | 240s | 同上断头路 |
| sandbox.py:191-250 `run_process` | 参数 | timeout 必传 + out_cap=8MB | 逐调用 |
| sandbox rlimits（内存/CPU/nofile） | — | — | **不存在**——只有 killpg 墙钟 + 8MB stdout cap |
| TeX cnf `buf_size=8000000` | Xelatex._env setdefault engine.py:1009 | 8MB | 仅改码 |
| TeX cnf `max_print_line=10000` | _ENV_FORCED sandbox.py:62-68 | 10k | 仅改码 |
| 工具调用字面量 timeout 群 | 字面量 | — | 否（engine.py kpsewhich/tlmgr/updmap×8、normalize.py:1105、latex209.py:359、toolchain.py×3、judge.py:75、fixloop engine.py:547+:994 yaml、llm_hook.py:50、xlat/client.py:45-46） |
| 上传上限 settings.py:50-52 | 常量 | 80MB/300MB/4000 | 否 |

## (b) 判定：分散，但有一条潜伏缝

三层：(1) 墙钟 compile timeout —— 端到端参数化完善（`--timeout` → `_Job.timeout` → engine.compile + fixloop compile_timeout），bench/CLI 全局可调，server 侧钉死常量。(2) TeX 内部容量（cnf vars）—— 唯一硬编码注入点 buf_size(engine.py:1009) + _ENV_FORCED 的 max_print_line；ambient env **无法**注入 stack_size 等——child_env 白名单（sandbox.py:30-59）刻意剥光非 TEXMF*/TEXINPUTS 系（该白名单同时是 secret-washing 边界）。(3) OS rlimits —— 设计性缺席（sandbox 只做 fs/net 隔离）。

潜伏缝：`Engine.compile(env_extra=)` 在 protocol（engine.py:908）与两个 impl（xelatex :1159→_env、tectonic :1579→child_env）都在但**零生产调用者**——e2e/worker/fixloop/bench 全不传，fixloop 自己的 Engine protocol（fixloop/engine.py:112-121）甚至没声明它。第二条零代码通道：fixloop `engine_flags` → xelatex argv 原样透传 `-cnf-line=stack_size=500000`（_split_flags engine.py:1091-1116，只滤 output-rekey 系）；tectonic 丢进 flags_dropped → 现成 cross-engine 臂会交给 xelatex。今日无规则发它。

## (d) 建议

**别为 capacity 建"统一上限配置"**——4 格要逐格根因（input-stack 爆栈多半是递归；TL 的 10000 已慷慨，全局调大会改所有格的失败语义）。若仍要可调，最小面：扩 `Xelatex._env` setdefault 链（engine.py:1009）或 _ENV_FORCED 加 `TEXLATE_TEX_STACK_SIZE` 式 env 桥 + 把 env_extra 穿过 fixloop compile_kw（fixloop/engine.py:1244-1246）——共 ~3 处，顺带修 tectonic/xelatex 不对称。墙钟侧唯一值得收的口是 server 路径：`COMPILE_TIMEOUT` 裸常量——worker.py:181 读一个 `TEXLATE_COMPILE_TIMEOUT`（或 settings.json key）即三入口齐平。
