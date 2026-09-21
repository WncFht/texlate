# 全仓目标达成审计 — 2026-09-16（13 维度汇总）

> **结论**：13 维度全仓只读审计总索引：M0 达成、M1 实质达成、M2 字面未达（89.5%<90%）、M3 约半程；另出 P0 安全三件与编排断链清单。
> **状态**：时点证据（2026-09-16 口径）
> **日期**：2026-09-16（2026-09-20 迁入重编）

> HEAD `6a256b2`。本文是 13 个并行审计 agent 的汇总索引；各分报告同目录，
> 逐项 verdict + file:line 证据在分报告内。审计方法：spec 原文逐条抽规范性
> 断言 → 对照实现/测试/bench 实物 → DONE/PARTIAL/MISSING/UNVERIFIABLE。
>
> **时效注记（2026-09-16 午后）**：本文是午前时点快照。P0 安全三件、编排
> 断链（fixloop 接线/L2 回灌/target_probe/env_judge/recover_copied_tokens）、
> SPA 打包链（M3）、argspec 装载（M1 GAP）、B3 zh 臂/Mode B·C/B7 归因等
> 多项"缺口"已在同日午后修复或推进——**当前判定以 `docs/HANDOFF-2026-09-16.md`
> §3 追记与 §6 为准**（该文件未迁入本库；原文见 `git show d39a1b23^:docs/HANDOFF-2026-09-16.md`），本文留作证据档案。

## 1. 里程碑总判定（docs/05 §6 口径）

| 里程碑         | 判定                                         | 关键事实                                                                                                                                                                                                                                    |
| -------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M0 骨架 + 基线 | **达成**                                     | 4/4 验收 DONE：identity 1955/1955 双侧 strict、leak 0.046%、traps 34/34、arxiv 六子项 +264 测试、双注入双引擎+judge、corpus39 基线在库                                                                                                      |
| M1 展开 + 翻译 | **实质达成**（1 GAP + 2 PARTIAL + 保留项）   | 出口门 97.8%/89% 双口径 ≥85%；GAP=argspec.json 1820 条产品面零装载；PARTIAL=UBD 日志信号、ts-validator extra 缺位；保留=n100 证据跑在 v1 面                                                                                                 |
| M2 编译攻坚    | **字面未达成**（库层齐、编排断、门差一口气） | normalize/fixloop(31)/ctan_fetch/沙箱 DONE；出口门 89.5%<90%、n=172<200、**fixloop 未接产品链**（e2e/worker 单次 compile 即判）；target_probe、LLM 修复器 MISSING                                                                           |
| M3 产品化      | **约半程**                                   | server 3639 行实装（WAL/SSE/BYOK/11 态机）+ 前端 22 文件真代码；但 **SPA 送不出去**（server/static 不存在+pyproject 无 force-include）；fixloop 未接 worker；Dockerfile/tectonic 矩阵/瘦客户端/EPUB/DOCX 未实现；hjfy 对齐表 5 绿 3 半 2 红 |

## 2. spec 覆盖（docs/06–10）

- **06 arxiv**：取源/限速/解包安全/定位全落（恶意 tar 13 向量实测全拒）；
  §3 元数据层（Atom/OAI）、§5 降级链 MISSING；`build_corpus_v3.py:960`
  藏第二套弱化 unpack，违反 §0 共享语义。
- **07 latex**：唯一实质缺口 = §3.8 `INLINE_MAX=8000` 死常量零消费；
  其余全是 spec 滞后（v2 三件套未回写模块清单）。§12.2 验收数字与
  bench 实物逐项核对一致，247 测试绿。
- **08 translate+compile**：库层厚（prompts/batch/retry/state/glossary/
  L0-L2/normalize 12 手术/inject/engine/judge/sandbox/fixloop+cases）。
  **缺口集中在编排接线**：fixloop 未接 e2e/worker（spec §0 主链缺整段）、
  L2→逐块重译回灌环 missing、target_probe missing、embed_cjk_mappings
  missing、env-judge 与 recover_copied_tokens 成稿但零调用点、
  engine_flags 收集不生效。
- **09/10 语料+bench**：语料对盘一致（仅 corpus_v2 139 vs spec 137 漂移）。
  门：B1+B2 全绿、B6 满分、B4a 已建档；**B3 zh 臂从未跑、e2e Mode B/C
  未产品化/未跑、B7 当前 FAIL、B4b 距 85% 远**。

## 3. 横切面

- **e2e 实测**：真通。arXiv id→双语 PDF 全链（1706.03762→12p/1744 CJK；
  2501.14787→81p/18603 CJK）；错误路径结构化；web 起服正常（/ 404=
  SPA 未打包，与 M3 断链互为印证）。
- **测试质量**：零假绿（1090 pass/16 skip）；三缺口：e2e.py 产品编排层
  零覆盖（test_e2e_mock 测的是手工重接的影子链）、xlat/client.py ~350
  行无离线测试、validate 层 12 条静默失活（门控路径改名后永久 skip）。
- **证据对账**：HANDOFF-2026-09-16 全部数字 MATCH，零 MISMATCH。
- **文档漂移**：里程碑标签全面陈旧（仍写 M0 实施中）、索引漏 6 篇、
  fixloop「25 规则」→实 31、工具链缺 taplo、「无 ts」被 web/ 推翻。

## 4. 安全发现（codehealth，按严重度）

| 级别 | 位置                             | 问题                                                                       |
| ---- | -------------------------------- | -------------------------------------------------------------------------- |
| H1   | server/worker.py:840             | `options.main` 无 confinement → 绝对路径/`..` 逃逸任务目录，编译产物写树外 |
| H2   | settings.py:350 + client.py:161  | `RedactFilter` 从未挂载 + 远端响应体原文落 DB/日志 → key 回显泄漏通道      |
| H3   | fixloop/ctan.py `overlay="tree"` | 路径穿越只挡 `../` 前缀 + xz 解压无上限（latent，生产现只用 flat）         |
| M1   | app.py `_create_and_enqueue`     | `find_reusable` 无 tenant 过滤 → 跨租户存在性预言机                        |
| M2   | worker.py:1321 `_make_glossary`  | 任意文件读 → 内容进 LLM prompt 外泄通道                                    |

## 5. 优先级收口建议

- **P0 安全**：H1 路径逃逸、M2 glossary 任意读、H2 RedactFilter 挂载 +
  远端 body 脱敏——server 模式对外前必须修。
- **P0 接线**：fixloop→worker/e2e 产品链（M2 门 + spec08 §0 双料缺口，
  修一条解两处）。
- **P1**：argspec.json 装载（M1 GAP）；L2→重译回灌；target_probe；
  env-judge/recover_copied_tokens 调用点；e2e.py 测试；12 条死 skip
  复活；server/static 打包（M3 主功能断链）。
- **P2**：文档批（里程碑标签/索引/taplo/ts-validator extra）；
  INLINE_MAX 接线或删；build_corpus_v3 第二套 unpack 归并；
  B3/B7/Mode-B/C bench 臂补跑；corpus_v2 manifest 数字更正。

## 6. 分报告索引

| 报告                                   | 维度              | 头条结论                                                |
| -------------------------------------- | ----------------- | ------------------------------------------------------- |
| [m0.md](m0.md)                         | M0 验收           | 4/4 DONE                                                |
| [m1.md](m1.md)                         | M1 验收           | 5P/2PART/1GAP，出口门带保留过                           |
| [m2.md](m2.md)                         | M2 验收           | 库层齐；89.5%/n172 为时点值，「未接链」已反转——fixloop/target_probe/L2 回灌/LLM 修复器均实装，详见文首 SUPERSEDED 注记 |
| [m3.md](m3.md)                         | M3 验收           | 约半程；SPA 断链最刺眼                                  |
| [spec06.md](spec06.md)                 | arxiv spec        | §3/§5 missing；unpack 有两套                            |
| [spec07.md](spec07.md)                 | latex spec        | 仅 INLINE_MAX 死常量；余皆 spec 滞后                    |
| [spec08.md](spec08.md)                 | xlat+compile spec | 库厚、编排断：fixloop/L2 回灌/target_probe              |
| [spec0910.md](spec0910.md)             | 语料+bench spec   | B3/Mode-B/C 未跑、B7 FAIL                               |
| [e2e-func.md](e2e-func.md)             | 功能实测          | 端到端真通，出双语 PDF                                  |
| [tests.md](tests.md)                   | 测试质量          | 零假绿；e2e.py 零覆盖最要害                             |
| [codehealth.md](codehealth.md)         | 代码健康 + 安全   | ruff 净；5 个真实安全发现                               |
| [evidence.md](evidence.md)             | 数字对账          | HANDOFF 全部声明 MATCH                                  |
| [docs.md](docs.md)                     | 文档漂移          | 里程碑标签/索引/工具链三处最需更新                      |
| [wave2-findings.md](wave2-findings.md) | 波二 9-scout 台账 | 发现处置路由全录（fixed/fixer/routed/deferred/wontfix） |
