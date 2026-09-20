# 2026-09-16 大批量强化笔记（合并件）

> **结论**：当日三件事的核心产出——stagerun 分阶段批量架构（五阶段各自独立 records/resume/并发模型）、pipe-fix 救回臂 `onfail` 语义（只接 fail 不接 partial）、续翻语义三修（`_paper_done` 谓词、slots `[[SL]]` 解码、续跑 source 漂移防线）——均已落地：`bench/py/stagerun*.py`、`triage.py`、`e2e_real_bench.py --fixloop`、`xlat/retry.py`、`pipeline.py`。
> **状态**：时点证据（2026-09-16 口径；一次性作战件合并浓缩，stagerun/triage/修复均已实装）
> **日期**：2026-09-16

由原 `2026-09-16-batch-hardening-design.md`、`2026-09-16-e2e-pipefix-hotlayer.md`、`2026-09-16-xlat-resume-review.md` 三件合并浓缩；过程流水与工单排期从略，保留设计决策与已验证结论。

## 1. stagerun 分阶段批量架构

**问题**：n100 实测（64 篇完跑）暴露的不是跑不起来，而是论文级串行且全阶段耦合——无法按阶段提取共性、观测面有洞、失败→修复没工单化。first_error 一半是 missing_file（32/64）；fixloop 对 31 个 fail 救回 24。

**架构**：每个阶段是对选样全集的一次扫描，产出自己的 `records/{stage}.jsonl`（append 式、行在=done 即 resume 语义）：

```
manifest → ingest（IO 线程池，work/{id}/src/）
        → parse（ProcessPool，route+normalize+parse_file → work/{id}/parse.json）
        → xlat（asyncio+全局网关 sem；--arm mock|real|sabotage → work/{id}/zh/）
        → compile（ThreadPool subprocess；splice+inject+judge；--arm zh|base 对照归因）
        → fixloop（compile 非 clean 格 → cases.jsonl + repaired zh/）
        → triage（离线：records 签名聚类 → tickets.jsonl）
        → fix（subagent 复现→修→replay 三门验收 → leader 合并）
        → regress（同 seed 重跑受影响 stage + replay_all；metrics.jsonl 追加趋势）
```

关键性质：**每阶段独立可重跑、独立并发模型、独立故障签名集**；论文流过 DAG 靠 workdir 中间产物而非内存对象。臂是 stage 参数而非独立流水线：real 臂只跑子集（LLM 引入破坏由 real 暴露），compile/fixloop 对 mock 产物全集跑（结构故障全暴露），下游共用。base 对照臂做归因——「zh 非 clean ∧ base clean」集合即管线引入回归。

**规模 sizing 原则**：按「值得分辨的最稀有签名」定规模（发生率 p 的签名要见 ≥3 次需 n≈3/p）；parse/mock/sabotage 臂免费拉满全集，real 臂跑子集 250–300 篇，compile base 首轮全集建源健康基线后按需补跑。rescue 率这类头条指标在全集上过强，绑定约束是稀有签名。

**先修的观测洞**（否则批量数据有毒）：chunk_to_in 补传 ph_map（武装阶梯抄回臂）；auth 失败静默全败→连续 N 块 auth-fail 该论文 fault + 全局熔断；chunks.error_code 两写口径统一 + warnings 落库；usage/latency sink 接线（协议只回 str 时真实 token 无法记账）；records append 化 + CaseSink 加锁。

## 2. pipe-fix 救回臂与 `onfail` 语义

pipe-xel 非终态时把产物树 copy 到独立工作区跑 `fixloop()`（xelatex usermode + TUNA 钉 + tlpdb 离线索引），随后同判据复判。`--fixloop onfail|always|never`（默认 onfail），结果沉淀 `cases.jsonl`。

**语义校准（冒烟实证）**：`onfail` 只接 pipe-xel `fail`，**不接 partial、不接 reject**——partial 已产出 PDF、其判据是 warning 级（invalid_utf8/missing_chars，非编译错误，fixloop 规则无能为力），而 fixloop 的 halt_on_error 引擎 + 树改写（vendored sty 隔离、tlmgr 装包改变宏定义环境）**会把已有 PDF 弄丢**：冒烟中 partial→fail 回退 2/3。reject 不救（inject 拒绝=无 ctex）。always 模式保留全跑能力作幂等/回退率探针。

**联合冒烟（hot 层 9 篇）**：翻译 9/9 执行、splice 残留 0、管线引入回归 0；救回 3 篇（2410.08770 fail→clean 为纯 fixloop 功劳——base 亦 fail；另两篇 fail→partial）；union 口径 usable PDF 5/9→8/9。

**hot 语料层**（第三层，扩展不替换）：`hot-cite`（OpenAlex `from_publication_date≥2024-01-01` 按 cited_by_count 降序）+ `hot-recent`（2025-06+ 随机）——修正 corpus_v3 抽样框（IA ≤2020-10 + TIGER ≤2412 均匀层）与真实负载分布不匹配；首日入库 72 篇，CS 占比 51%（核心层仅 18%）。

## 3. 续翻语义三修

**`_paper_done()` 谓词（bench 层漏洞修复）**：三层记账面口径核查——chunk 层 `completed` 只认 ok/partial（正确）、server 任务层 partial 折叠进 ok（正确）、bench 论文层「status 非空即 cached」**是漏洞**——draining 窗口里传输级 skip 的论文被永久墓标。修复：`bench_error`、translate.skipped>0、translate.fault>0 任一 → 不算完成，续跑重进（chunk 级 state 只重翻失败块，成本有界）。fault（阶梯四段全败）在 pipeline 侧本就进重试集，bench 谓词同口径。

**`[[SL]]` "幻觉占位符"实为 slots 装配 bug**：全部 fault 的 warnings 含 `slots assembled but still invalid: 多余/未识别占位符：[[SL]]`——根因不是模型臆造：`_assemble_slots` 对 `("ph", payload)` 项原样回拼**不解码**，编码期产生的 `[[SL]]`/`[[PL]]` 字面残留进校验文本 → 任何含换行的 chunk 在 slots 段必败（既有测试全是单行源恰好绕过）。修复：ph 分支改 `decode_newlines(payload)`。

**`\` 脆弱间距防线（编码为占位符）**：E21/E22 硬判据 `\ ` 丢失（`resp.\ to`、`s.t.\ $x$`、`cf.\ \S` 高频形态）——模型把 `\ ` 当排版噪声丢弃，阶梯四段接不住是生成端真弱点非校验误报。防线：`encode_newlines` 把 `\ `→`[[SP]]`、`decode_newlines` 还原——模型侧看到的是受保护的占位符（echo 可靠性远高于裸 `\ `），校验侧 decode 后判据不动；`PROMPT_VERSION` bump 正确失效段级缓存。`\,`/`\;`/`\:`/`\!`/`~` 同族未编码——无实测失败信号，留扩展点。

**splice 残留防线（source 漂移核查）**：1524 例 leftover_ph 的根因——续跑按位置 chunk_id `{fidx}:{c.id}` 命中旧记录**不校验 source**，parse 漂移下同 id 指向不同内容，旧译文的 `[[X_n]]` 在新 ph_map 缺席 → splice 留字面残留。三处修复：`_route_chunks` 命中前比 `prev.source == c.content`（漂移即 warning + 重翻 + 丢出 done_map）；`reconstruct` 查无实体的 ph token 记 `dangling` 集合并 warning 而非静默留字面；bench summary 的 splice 残留行升级为 gate（PASS 或逐篇点名 FAIL）。
