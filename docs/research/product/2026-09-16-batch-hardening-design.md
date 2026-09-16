# 大批量强化管线设计——分阶段批量执行 + triage→fix→regress 循环

日期：2026-09-16（v2：按用户意见改为分阶段批量架构 + 数据集入库）。依据：六个子代理对 worker/store/xlat/compile/fixloop/bench/corpus 的全量精读 + `bench/results/e2e-real-n100-postcutover-2026-09-16/` 实跑数据。本文是执行规格——所有改造点均落到具体文件。

## 0. 现状判断

n100 实测（64 篇完跑，swe-2-medium）：翻译契约 5540/5542 ok、splice 残留 0；pipe-xel 18 clean/14 partial/32 fail；**first_error 一半是 missing_file（32/64）**；fixloop 对 31 个 fail 救回 24（clean 17 + acceptable 3 + best_effort 4）。base-xel 对照臂证明绝大多数 fail 是**源侧**问题，管线引入的回归只有 7 篇。

瓶颈不在跑不起来，在：**论文级串行且全阶段耦合（无法按阶段提取共性）、观测面有洞（数据不可信）、失败→修复没工单化**。v2 改为**分阶段批量执行**：每个阶段是对选样全集的一次扫描，产出自己的 records 文件——每个阶段的故障面天然是干净数据集，executor 按该阶段资源类型单独选型。

## 1. 总体形态

```
manifest (1272 行；channel=ia + item + member 自带 IA bulk 坐标)
   │
   ▼ stagerun ingest  —— 数据集批量物化 → work/{id}/src/
   ▼ stagerun parse   —— route+normalize+parse_file → records/parse.jsonl + work/{id}/parse.json
   ▼ stagerun xlat    —— XlatPipeline(arm: mock|real|sabotage) → records/xlat.jsonl + work/{id}/zh/
   ▼ stagerun compile —— splice+inject+compile+judge(arm: zh|base) → records/compile.jsonl
   ▼ stagerun fixloop —— 对 compile 非 clean 格 → cases.jsonl + work/{id}/zh/(repaired)
   │
   ▼ triage（离线脚本）—— 各 stage records 签名聚类 → tickets.jsonl
   ▼ fix（subagent，leader 委派+收口）—— replay_case 三门验收 → leader 合并
   ▼ regress —— 同 seed 重跑受影响 stage + replay_all；metrics.jsonl 追加趋势
```

关键性质：**每阶段独立可重跑、独立并发模型、独立故障签名集**；论文流过 DAG 靠 workdir 中间产物而非内存对象。subagent 只做"复现→修→回放"三段式。

## 2. 入库层（数据集物化，不走 arXiv API）

- 语料主体已在盘上：corpus_v3 manifest 1272 行（core 1000 + booster 200 + hot 72），已物化 1047 个工程目录（`{id}/extracted/`），**缺 ~225 篇未落盘**。
- manifest 每行自带 IA bulk 坐标（`channel=ia`、`item=arXiv_src_YYMM_NNN`、`member=YYMM/<name>.gz`、`blob_sha256`）——补缺与扩层**按 item 分组整包拉取抽成员**，一个 item tar 解出数十篇，零逐篇 API。
- `stagerun ingest` 定义：已物化 → copytree 进 `work/{id}/src/`；未物化 → 按 `item` 聚组拉 IA tar、抽 member 落 `corpus_v3/{id}/extracted/` 补库后 copytree。record：`{id, n_files, main_tex_guess, sha256_ok, source(cache|ia)}`。
- arXiv 逐篇 API（~85 篇/日）仅留作单篇即兴旁路，不是入库主路；未来要更大规模走 IA bulk 同一通道扩 manifest。

## 3. 执行层——stagerun 阶段矩阵

新驱动 `bench/py/stagerun.py`：每阶段一子命令，`--ids/--layers/--n/--seed` 选样、`--jobs` 本阶段并发、`--arm` 臂。**resume = records/{stage}.jsonl 已有该 id 即跳过**。

| stage   | 函数边界（现成代码出处）                                                                                           | 产出 artifact                                                 | executor                               |
| ------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- | -------------------------------------- |
| ingest  | manifest→copytree / IA 抽成员（build_corpus_v3/build_hot_layer 同款）                                              | `work/{id}/src/`                                              | ThreadPool 8（IO）                     |
| parse   | `route_project`+`normalize_project`+`parse_file`（e2e_real `pipe_xel_condition` 前半；worker `_stage_parse` 同构） | `work/{id}/parse.json`（main_rel/chunks/warnings/unresolved） | ProcessPool 4-8（CPU，expander 纯 py） |
| xlat    | `translate_tree`（e2e_real:164）；mock/sabotage 臂用 e2e_mock 的 Translator 类                                     | `work/{id}/zh/` + chunk 明细                                  | asyncio + **全局** gateway sem         |
| compile | splice+inject+`_compile_judge`（e2e_real:274）+`base_xel_condition`（:310）                                        | `work/{id}/splice/`、`build-*/`                               | ThreadPool 4-8（subprocess）           |
| fixloop | `pipe_fix_condition`（e2e_real:334）→ `fixloop()`+CaseSink                                                         | cases.jsonl + repaired `zh/`                                  | 同 compile                             |

臂是 stage 参数而非独立流水线：`xlat --arm mock|real|sabotage`、`compile --arm zh|base`（base 直编 `src/` 做归因）。**real 臂只跑子集**（records 按 arm 分记），compile/fixloop 对 mock 产物全集跑——LLM 引入破坏（断括号/造命令）由 real 子集暴露，结构故障由 mock 全集暴露，下游共用。

跨阶段契约：`parse.json` 是 xlat 输入清单；`zh/` 树是 compile 输入；上游 record 非 ok 下游自动 skip（`--upstream partial` 放行部分产物测降级路径）。

**必改**（否则批量数据不可信或与产品分叉）：

1. `chunk_to_in` 补传 `ph_map`（e2e_real 当前不传 → 阶梯抄回臂没武装，比产品弱；产品 e2e.py:193 传了）——最高优先。
2. `MAX_TOTAL_CHARS` 死代码接上或删（:89）。
3. L2 回灌作为 `xlat --post l2` 可选步对齐产品 `pipe_condition`（e2e.py:751-758）。
4. records 一律 **append 式 jsonl**（parsebench 全内存末尾写盘：崩一次全丢）。
5. CaseSink 加 `threading.Lock` 或 per-shard `cases-{wid}.jsonl` 后合并（裸 append 并行会交错截断）。

## 4. 错误检测面（每层有什么、缺什么）

| stage   | 已有检测                                                                | 缺口（工单）                                                                  |
| ------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| parse   | `res.warnings` kind、unresolved_inputs、parsebench leak/identity        | bench 只收 warn_kinds 计数，丢 warning 详情（pos/detail）——records 要带全量   |
| xlat    | L0 `validate_pair` 7 规则 inline、chunk status、leftover_ph 硬门        | **error_code 两写不一致**；**warnings 不落库**；**partial→ok 抹掉 recovered** |
| compile | judge verdict{status,category,payload,n_errors,missing_chars,cjk_chars} | judge 只看末次 log——fixloop per-round category 要并进 compile record          |
| fixloop | taxonomy 22 类 + per-round rule trace                                   | `unfixable:*`/`stuck`/`max_rounds` 即工单来源                                 |
| 归因    | `compile --arm base` 对照                                               | 已有                                                                          |

**横切洞（先于大批量修）**：

- **auth 失败静默全败**：401 逐 chunk 吞成 skipped→全块 fallback_orig、任务显示"完成"。凭证失效=整批假数据。修：xlat stage 内连续 N 块 auth 失败→该论文 fault + **全局熔断**（连续 3 篇全 auth-fail 停跑报警）。
- **usage/latency 在 Translator 边界丢弃**（协议只回 str）：真实 token/延迟无法记账。修：ChatClient→GatewayTranslator 挂可选 usage sink 回调。
- `EmptyContentError` non-retryable→reasoning 模型空响应直接穿透 skipped。修：归 retryable 一次。
- worker 侧同源洞（对产品链直接受益）：`_compile_zh` 无 zh.pdf 哨兵恒重编；`.splice-done` 先于 `_zip_zh` 写盘（worker.py:1404-1405）；interrupted 不发 done 事件；`inject_reject` 不在 `store.ERROR_CODES`；`ctx.row` 快照致 `_fail` stage 陈旧。

## 5. 验证层

- **工单验收三门**（cases.py 现成）：`replay_case` 本格 fail→pdf；`replay_all` 无 regressed；`stats_backfill` 回填 stats + `status_suggested=active` 人工转正。
- **sabotage 臂**：escaped==0 硬门（e2e_mock Mode B/C 台账迁为 `xlat --arm sabotage`）。
- **阶段回归**：同 seed 重跑受影响 stage，逐 stage 成功率不得跌；`compile(zh) 非clean ∧ compile(base) clean` 回归集合必须为空或收敛。
- fixloop 单测：`tests/test_fixloop_loop.py` MockEngine/mini_rs 验机械流转；真编译验证走 replay。

## 6. 日志与指标传递（文件协议）

```
bench/results/{run}-{tag}-{date}/
  records/{stage}.jsonl   # 每篇一行 append；行在=done（resume 语义）
  work/{id}/              # 中间产物树（src/ parse.json zh/ splice/ build-*/）——replay 物证
  cases.jsonl             # fixloop 修复现场
  tickets.jsonl           # triage 产出
  fixes.jsonl             # 修复台账（sig→rule/commit/验证结果）
  metrics.json            # 本 run 汇总
  run_meta.json           # seed/layers/arms/版本/git rev
```

- record schema 统一：`{id, stage, arm, status, dur_s, metrics{...}, errors[{code,cat,payload}], sig}`——triage 按 `sig` 聚类。
- ticket schema：`{sig_id, stage, signature, count, example_ids[], repro_path, fix_class(rule|builtin|core|shim_table|wontfix), notes}`。
- `metrics.jsonl`（跨 run 追加）：`{run_id, date, stage_rates{}, fixloop{rescue_rate, top_unfixable[]}, regressions[], wall_s}`。
- 不依赖 server DB（Store 单连接单线程）；worker 侧 SSE/log 链是产品面，bench 以 records 为准。

## 7. 规模与并发参数

**分层跑法**（每阶段独立放量——分阶段架构的直接红利）：

- ingest/parse/compile/mock-xlat/fixloop：**可全集 1272**（零 LLM）
- xlat real：**子集 200-300**（64s/篇中位，墙钟大头）
- smoke n=10-20 全 stage 通跑；loop 批 n=150-250 分层抽；gate 批 500+/全集

**每阶段 executor**（资源类型不同，不再一刀切）：

| stage           | bound      | 并发                      | 备注                                                                    |
| --------------- | ---------- | ------------------------- | ----------------------------------------------------------------------- |
| ingest          | IO         | 8 线程                    | IA tar 整包拉取可再高                                                   |
| parse           | CPU（py）  | 4-8 进程                  | ProcessPool；pickle 边界=路径 + 配置                                    |
| xlat（real）    | 网关 IO    | asyncio，全局 sem         | **swe-2-medium 硬闸 4**（archbox gwcap 代理接管本机出向 :3003，见下）   |
| compile/fixloop | subprocess | 4-8 线程（archbox 12-16） | 每 job 独立 workdir（compile 删同 outdir stale 产物）；tlmgr flock 安全 |

**网关并发硬约束（2026-09-16 起）**：archbox 上全部出向 tcp/3003 被 nftables `inet gwcap` REDIRECT 到本机 `gw-cap-proxy`（127.0.0.1:3399），对 `model` 以 `swe-2-medium` 开头的请求过**全局信号量 4**——任何会话、任何隧道共享此额度。故 xlat real 臂全局 sem = **4**（其他模型另查网关限流）；观测 `curl 127.0.0.1:3399/__gwcap/healthz` 看 inflight/queued。

**成本估算**：mock 臂全集 1272 篇 compile+fixloop 段 8 并行 ≈ 4-6h；real xlat 300 篇 @并发 4 ≈ 1.5-2.5h（64s/篇 × 300 ÷ 4 ≈ 80min 起步，含抖动按上限估）。Linux 无 FS 沙箱——批量跑第三方 tex 加 `-no-shell-escape` + env 白名单兜底。

## 8. subagent 工作模式

**leader（本 session）直接委派 + 删除，无编排框架**：

1. leader 跑批 → triage 出 tickets.jsonl → 按签名量排序取 top-N
2. 每工单 spawn 一个 fixer（`Agent` 工具），prompt 即工单：repro 路径、修复面（rules.yaml 段/builtins.py 函数/core 文件范围）、验收三门。纪律：**不跑 git 状态命令、不改工单外文件、产出=补丁落盘+replay 证据 + 一行 report**
3. leader 验证据 → 相邻 case 回归 → commit → **关 agent**（roster 不留僵尸；同名可再 spawn）
4. 文件归属：`rules.yaml`/`builtins.py` 共享热点——并发 fixer ≤3 且只 append；core 文件（worker/pipeline/engine）串行或 leader 自修
5. `llm_hook` stub（undefined_cs_guess 等）攒批签名后一次实现接 3003 网关——"LLM 修编译错误"统一出口（走 gwcap 额度，注意并发≤4）

## 9. 首批工单（按序）

观测/正确性（先于大批量，否则数据有毒）：

- T1 xlat 补传 ph_map（武装阶梯抄回臂）
- T2 auth 静默全败闸 + 全局熔断
- T3 chunks.error_code 两写口径统一 + warnings 落库
- T4 usage/latency sink 接线
- T5 records jsonl append 化 + CaseSink 锁
- T6 .splice-done/_zip_zh 顺序；_compile_zh zh.pdf 哨兵；interrupted 补 done
- T7 EmptyContentError 归 retryable；inject_reject 入 ERROR_CODES

stagerun 工程：

- E1 `stagerun.py` 骨架：manifest 共享读取 + 5 stage 子命令 + records/append + resume-skip
- E2 xlat stage 全局 semaphore（默认 4，对 gwcap）
- E3 triage 脚本（各 stage records → tickets.jsonl 聚类）
- E4 metrics.jsonl 趋势 + report merge
- E5 重复件收敛（manifest 读 ×4、_judge_dict ×3、safe_id ×2、IGNORE ×2、TUNA ×3）

fixloop 规则面（n100 签名直接转化）：

- F1 退役包 shim 表扩列：elsart.cls→elsarticle
- F2 `undefined_cs`×6 逐签名归因：缺包→filemap.overrides/cs_targeted_fix 扩表，笔误→llm_hook
- F3 latex209 verdict 语义：reject→partial 而非 fail
- F4 missing_character CJK 缺字类规则可扩性

## 10. 实施顺序

1. T1-T7（leader 或 1-2 fixer，一天内）——观测面先正
2. E1 stagerun 骨架 + E2 → n=20 全 stage smoke 验 records/resume/并发
3. ingest 补齐 ~225 缺篇（IA 批量）→ loop 批：mock 臂 n≈250 全 stage + real xlat n=50 → 首版 tickets
4. F1-F4 fixer 循环；每轮 merge 后 replay_all + 同 seed 重跑受影响 stage
5. gate 批：mock 全集 1272 + real 子集 300 → 各 stage 硬化结论入 metrics.jsonl

## 附：与产品线的关系

stagerun 各阶段直接 import `texlate.*` 产品 API（不走 HTTP）。worker 侧修复（T2/T3/T4/T6）对产品链同步生效。fixloop→worker 接线已完成（`_compile_zh`→`_run_fixloop`，`CaseSink(data_dir/fixloop-cases.jsonl)`，`fixloop` SSE 事件，`fixloop_exhausted` 终态码）——**bench 沉淀的每条 case 都是产品 fixloop 的回归样本**。
