# 测试质量与覆盖审计（2026-09-16）

> **结论**：测试面审计：1090 绿、断言全为真行为断言零假绿；e2e.py 零覆盖、client 线路层离线零覆盖、12 条静默失活为主要缺口。
> **状态**：时点证据（2026-09-16 口径）
> **日期**：2026-09-16（2026-09-20 迁入重编）

范围：`tests/` 全集 + `src/texlate/` 模块映射 + `bench/fixtures/` 陷阱消费。基线：`uv run pytest tests/` = **1106 collected / 1090 passed / 16 skipped / 0 failed**（27s）。方法：逐文件 import 映射 + skip 条件归因 + AST 扫描零断言函数 + 核心文件断言抽查 + fixture 标记对账。

## 一、模块 × 覆盖矩阵

| src 模块                      |     行数 | 直接测试文件                           |       用例数 | 覆盖判定                                                                                                                                                                                                    |
| ----------------------------- | -------: | -------------------------------------- | -----------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `align.py`                    |      159 | test_align                             |            7 | 足（landmark/build_alignment 全路径）                                                                                                                                                                       |
| `arxiv/cache.py`              |        — | test_arxiv_fetch、test_server_worker   |            — | 间接足（经 fetch/worker 命中）                                                                                                                                                                              |
| `arxiv/fetch.py`              |      616 | test_arxiv_fetch                       |           14 | 足（httpx.MockTransport 全 fake 线路）                                                                                                                                                                      |
| `arxiv/locate.py`             |      470 | test_arxiv_locate                      |            9 | 足（3 条 corpus_v1 门控在本机已解开）                                                                                                                                                                       |
| `arxiv/ratelimit.py`          |        — | test_arxiv_ratelimit                   |           12 | 足（假钟全状态机）                                                                                                                                                                                          |
| `arxiv/sniff.py`              |        — | test_arxiv_sniff                       |            8 | 足                                                                                                                                                                                                          |
| `arxiv/_texutil.py`           |       26 | —                                      |            0 | 间接足（strip_comments 经 locate/sniff 用例）                                                                                                                                                               |
| `arxiv/unpack.py`             |      362 | test_arxiv_unpack                      |           14 | 足                                                                                                                                                                                                          |
| `cli.py`                      |      253 | test_cli                               |            1 | **薄**：只测 `version`；`run`/`web`/fetch 子命令零断言                                                                                                                                                      |
| `compile/engine.py`           |     1019 | test_compile_engine_judge              |           44 | 足（引擎实跑显式留 bench，注释声明）                                                                                                                                                                        |
| `compile/inject.py`           |        — | test_compile_inject                    |           14 | 足（语料实证陷阱：注释 docclass、revtex 多行）                                                                                                                                                              |
| `compile/judge.py`            |        — | test_compile_engine_judge              |            — | 足                                                                                                                                                                                                          |
| `compile/mask.py`             |        — | test_compile_mask                      |           11 | 足                                                                                                                                                                                                          |
| `compile/normalize.py`        |      672 | test_compile_normalize                 |           32 | 足                                                                                                                                                                                                          |
| `compile/sandbox.py`          |      236 | test_compile_engine_judge              |            2 | 薄但合理：env 白名单+passthrough 已测；sandbox-exec profile 仅 macOS（本机正确 skip）                                                                                                                       |
| `compile/fixloop/builtins.py` |        — | test_fixloop_rules                     |           23 | 足（phase 序/provenance/engine_spec 逐条钉）                                                                                                                                                                |
| `compile/fixloop/cases.py`    |        — | test_fixloop_cases                     |            9 | 足                                                                                                                                                                                                          |
| `compile/fixloop/ctan.py`     |        — | test_fixloop_ctan                      |           15 | 足                                                                                                                                                                                                          |
| `compile/fixloop/engine.py`   |        — | test_fixloop_loop + rules              |        28+23 | 足                                                                                                                                                                                                          |
| `compile/fixloop/logparse.py` |        — | test_fixloop_logparse + spikereplay    |         21+2 | logparse 本体足；spike 重放 2 条 skip（陈旧路径）                                                                                                                                                           |
| `compile/fixloop/_yamlish.py` |        — | test_fixloop_yamlish                   |            4 | 足                                                                                                                                                                                                          |
| **`e2e.py`**                  |      170 | **无**                                 |        **0** | **零覆盖**：`mock_pipeline_run`/`mock_translate_tree` 无 pytest 触达；仅 bench harness + `cli run` 用                                                                                                       |
| `latex/api.py`                |        — | 经所有 latex 用例                      |            — | 足（v2 默认路径全链压力）                                                                                                                                                                                   |
| `latex/flatten.py`            |        — | test_latex_flatten + e2e/audit         |           21 | 足                                                                                                                                                                                                          |
| `latex/gullet.py`             |     2487 | test_latex_expansion + cond + dispatch |        76+18 | 足（展开语义/界标/嵌套组密集断言）                                                                                                                                                                          |
| `latex/macro_table.py`        |      466 | test_latex_model + audit               |           10 | 足                                                                                                                                                                                                          |
| `latex/model.py`              |      427 | test_latex_model                       |           10 | 足                                                                                                                                                                                                          |
| `latex/mouth.py`              |      337 | test_latex_expansion                   |            — | 足                                                                                                                                                                                                          |
| `latex/placeholder.py`        |        — | bench_regression + dispatch            |            — | 足                                                                                                                                                                                                          |
| `latex/reconstruct.py`        |        — | test_latex_reconstruct + 全链          |           12 | 足（identity 逐字节断言遍布）                                                                                                                                                                               |
| `latex/scanner.py`            |     1652 | audit/leaks/weakness + parse_tex_v1 钉 |            — | 足（v1 腿有 dispatch 守卫用例）                                                                                                                                                                             |
| `latex/segmenter.py`          | **2974** | **无专属文件**                         |            — | 间接足但无单元级：全靠 api 层用例（cond 18、audit 52、bench_regression 18、dispatch 34）覆盖；缺 segmenter 内部态直接断言                                                                                   |
| `latex/tables.py`             |      510 | audit + weakness                       |            — | 足                                                                                                                                                                                                          |
| `server/app.py`               |      862 | test_server_api                        |           40 | 足                                                                                                                                                                                                          |
| `server/events.py`            |        — | test_server_sse                        |            7 | 足                                                                                                                                                                                                          |
| `server/settings.py`          |      441 | test_server_byok                       |           14 | 足                                                                                                                                                                                                          |
| `server/store.py`             |      705 | test_server_store + sse                |           21 | 足（状态机迁移/并发约束/assert-free 全为 pytest.raises）                                                                                                                                                    |
| `server/worker.py`            |     1474 | test_server_worker                     |           11 | 集成足（upload/arxiv/fault/cancel/resume 五链路）；单元薄——1270 行内部 helper 无单测                                                                                                                        |
| `server/__main__.py`          |        — | 无                                     |            0 | 可接受（argparse→uvicorn 薄壳）                                                                                                                                                                             |
| `texlog.py`                   |       98 | **无直接测试**                         |            0 | 间接足：`file_stack_at` 经 logparse 精确断言、`update_file_stack` 经 l2/engine                                                                                                                              |
| `textutil.py`                 |      713 | test_textutil_encoding + mask          |           16 | 足                                                                                                                                                                                                          |
| `validate/l0.py`              |      696 | test_validate_l0                       |           38 | 足                                                                                                                                                                                                          |
| `validate/l1.py`              |      389 | test_validate_l1                       |  6（4 skip） | **薄**：CST 校验主路径全灭于 node 依赖缺失——可解开未解                                                                                                                                                      |
| `validate/l2.py`              |      334 | test_validate_l2                       | 12（6 skip） | 合成半足；真实 log 半全灭于陈旧路径                                                                                                                                                                         |
| `validate/report.py`          |        — | test_validate_report                   |            5 | 足                                                                                                                                                                                                          |
| `xlat/batch.py`               |        — | test_xlat_batch                        |           22 | 足                                                                                                                                                                                                          |
| `xlat/client.py`              |      723 | test_xlat_client                       |           16 | **半薄**：异常分类/retry-after/provider 路由/key 解析等纯函数全钉；**`ChatClient.chat`/`chat_stream`/`_openai_body`/`_parse_openai`（~350 行线路层）离线零覆盖**——无 MockTransport，仅 live 门控 smoke 触达 |
| `xlat/glossary.py`            |        — | test_xlat_glossary                     |           20 | 足                                                                                                                                                                                                          |
| `xlat/pipeline.py`            |      806 | test_xlat_pipeline + e2e_mock + worker |           11 | 足（阶梯/续跑/退化全行为断言）                                                                                                                                                                              |
| `xlat/placeholders.py`        |        — | test_xlat_placeholders                 |           25 | 足                                                                                                                                                                                                          |
| `xlat/prompts.py`             |      357 | test_xlat_prompts                      |           15 | 足                                                                                                                                                                                                          |
| `xlat/retry.py`               |      392 | test_xlat_retry                        |           15 | 足                                                                                                                                                                                                          |
| `xlat/state.py`               |        — | test_xlat_state                        |           13 | 足（原子写/schema/隔离全钉）                                                                                                                                                                                |

## 二、16 skipped 逐条归因

| 用例                                         | 门控                                       | 本机可解开？                                                                                                                                        |
| -------------------------------------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| test_arxiv_fetch live ×1                     | `TEXLATE_LIVE=1`                           | 可解（需真网）——设计内网络门                                                                                                                        |
| test_xlat_gateway_smoke ×2                   | `TEXLATE_LIVE=1`                           | 可解（需网关）——设计内网络门                                                                                                                        |
| test_compile_engine_judge sandbox profile ×1 | `sys.platform == darwin` + sandbox-exec    | **不可解**（平台正确门控；Linux 侧 passthrough 已测）                                                                                               |
| test_validate_l1 ×4                          | `bench/ts/node_modules/tree-sitter` 存在性 | **可解未解**：node v24 在场、`bench/ts/package.json`+lock 入库，`npm ci` 即恢复                                                                     |
| test_validate_l2 ×6                          | `bench/work_compile/<paper>` 5 篇钉死      | **陈旧门**：目录已改名 `work_compile_v4` 且 v4 抽样换了语料（5 篇钉死论文全不在）；需重跑旧 compilebench 采样或把断言重钉到 v4 现存 log             |
| test_fixloop_spikereplay ×2                  | `bench/work_fixloop` 目录存在性            | **陈旧门**：现存 `work_fixloop_cbv4/v2/v3/v3_ds`（479 log）；重放断言是 spike 时代口径（22 格/soul_err 残错），直接指过去大概率断言不过，需核对重钉 |

可归一化结论：16 条里 3 条是设计内 live 门、1 条平台门、**12 条是本机环境/陈旧路径造成的静默失活**（L1×4 一条 `npm ci` 全恢复；L2×6 + spikereplay×2 需重跑 bench 或重钉断言）。

## 三、断言质量抽查（10 处核心）

抽查结论：**全为真行为断言，无 smoke/print 式**。

- `test_bench_regression::assert_tricky`（T01–T29 共 26 条）：逐条泄漏正则 + 双向断言（保护物不在 chunk ∧ 原文在 recon），如 T03 同时钉 `\def` 不进 chunk 且 recon 保真。
- `test_bench_regression` corpus/e2e 用例：`reconstruct(res) == res.vtex` 逐字节 identity + `validate_result` 结构警告清零 + 占位符签发集合零泄漏。
- `test_latex_audit`（52 条）：F1–F12 陷阱逐条、fuzz 不抛异常 + pieces 平铺 property（corpus_v3 抽样 60 篇，本机已跑通）、`\if` 界标覆盖断言。
- `test_latex_cond`（18 条）：可求值/不可求值 `\if` 族的界标语义精确断言（literal piece + 双分支召回）。
- `test_fixloop_rules`（23 条）：rules.yaml phase 序逐 id 钉、每条规则 source_ref/provenance/stats 三件套、engine_spec degrade 路径。
- `test_fixloop_loop`（28 条）：含 `test_file_line_error_log_e2e`、`test_pdftex_prim_guard_e2e` 等真循环行为用例。
- `test_xlat_pipeline`（11 条）：坏批量退单翻、AuthError 整批 skip、fault→splice 原文回退，全状态断言。
- `test_compile_inject`（14 条）：语料实证锚点（注释掉的 `\documentclass` 不作锚点、revtex4-2 多行收尾行号钉死）。
- `test_e2e_mock`（5 条）：合成 + corpus 五型论文全链，四层断言（全 ok / L0 复核 / 占位符契约 / splice 泄漏）。
- `test_server_worker`（11 条）：upload/arxiv 双链路终态、fault/cancel/resume 行为级断言（`wait_terminal` 真轮询）。

## 四、陷阱 fixture 消费对账

`bench/fixtures/` 8 个条目全部有测试消费，标记↔断言全对上：

| fixture              | 标记                                     | 消费方                                            | 断言数                                 |
| -------------------- | ---------------------------------------- | ------------------------------------------------- | -------------------------------------- |
| `tricky.tex`         | @T01–T29（T14 在 multi、T15/T28 不存在） | test_bench_regression                             | 26                                     |
| `tricky-209.tex`     | 无 @Tnn（2.09 旧式件）                   | assert_209                                        | 3（beq_eeq/documentstyle/def）         |
| `tricky-multi/`      | @T14 ×4                                  | assert_multi                                      | 4                                      |
| `tricky-w.tex`       | @W11/15/50/67/75/82/83/84/90/91/92       | assert_w                                          | 11（与 mechanisms.jsonl 台账一一对应） |
| `tricky-w73/`        | @W73 ×2                                  | assert_w73                                        | 2（纸内/根外逃逸）                     |
| `tricky-wenc.tex`    | W72                                      | assert_wenc                                       | 1                                      |
| `xlat-traps.tex`     | @X1–X4                                   | assert_xlat                                       | 4                                      |
| `escape-outside.tex` | —（w73 的 `\input{../../}` 逃逸目标件）  | 经 w73 解析消费 + test_compile_normalize 同名用例 | —                                      |

登记了没测的：**无**。`tricky-multi/main.latexml.log` 是 latexml 参照产物非测试输入。

## 五、假绿清单

**零检出**。

- `assert True`/`assert 1`：0 处。
- `except: pass` 吞错：0 处（仅 test_bench_regression:155 `except ParseTimeoutError` 与 test_latex_audit:389 `except OSError` 两处合法容错路径，均有后续断言）。
- 注释掉的断言：0 处。
- AST 扫描零断言测试函数 16 个：全部为 `pytest.raises` 形态（BudgetExhaustedError/YamlishError/StoreError/RetryableHTTPError 等），合法。

## 六、缺口清单（按严重度）

1. **`e2e.py` 零覆盖**（170 行产品编排层）：`mock_pipeline_run` 是 `texlate run` 与 e2e_mock_bench 的共同驱动，pytest 完全不经它——test_e2e_mock.py 手工重接了同一条链（parse→pipeline→reconstruct），等于测了"影子实现"；e2e.py 与下游（inject/engine/judge）签名漂移只有 bench 能抓。
2. **`xlat/client.py` 线路层离线零覆盖**（~350 行）：`ChatClient.chat/chat_stream/_openai_body/_parse_openai` 无 MockTransport 用例（test_arxiv_fetch 已立此范式）；请求构造/SSE 解析/usage 抽取错误只能等 live smoke。
3. **validate 层 12 条静默失活**：L1×4 一条 `npm ci`（bench/ts）即恢复；L2×6 与 spikereplay×2 的门控路径已改名（work_compile→work_compile_v4、work_fixloop→work_fixloop_*），断言钉死的语料论文不在新采样里——要么重钉要么补跑旧 harness，当前形态等于永久 skip 且无人察觉。
4. `cli.py` 薄（1 用例只测 version）：`run`/`web` 子命令面零断言——与缺口 1 同源，补 e2e 用例可一并带起 `cli run` smoke。
5. `latex/segmenter.py`（2974 行，全仓最大）无专属单测文件：现靠 api 层 170+ 用例间接覆盖（本机 corpus_v3 property 已实证有效），但 segmenter 内部态（piece 序列形态、EXPAND 组边界、墓标序号）无直接断言——回归定位要靠集成报错倒推。
