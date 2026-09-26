# spec08 审计 —— docs/08-translate-compile.md vs src/texlate/{xlat,validate,compile} + e2e/cli/server 编排

> **结论**：spec08 逐节审计：xlat/validate/compile/fixloop 库层 covered；编排面 fixloop、L2 回灌、target_probe 三处 missing 是最大缺口。
> **状态**：时点证据（2026-09-16 口径）
> **日期**：2026-09-16（2026-09-20 迁入重编）
>
> **⚠️ SUPERSEDED 2026-09-21**：头条 verdict「编排面 fixloop、L2 回灌、target_probe 三处 missing 是最大缺口」已被后续实装反转——**fixloop 已接编排**（`pipecore.fixloop_job`，`e2e.py` `pipe_condition` 调用；worker 链 `server/worker/compile.py` `_run_fixloop`/`fixloop_round`，`run_fixloop` seam 声明于 `server/worker/core.py`）、**target_probe 已实装**（`compile/probe.py`，经 `pipecore.probe_report` 供 e2e/worker 两侧调用）、**L2 回灌已落地**（`repair_l2.py` + `pipecore.l2_repair_job`，e2e 与 worker 均已接线）、**LLM 修复器已实装**（`compile/fixloop/llm_hook.py` `LlmFixer`/`make_llm_hook`，worker 侧已接线）。测量类/覆盖面 verdict 仍为时点事实、未宣称反转。现状唯一事实源 = `docs/spec/`（尤其 `architecture.md` §2.6）；本文仅留逐节取证过程作历史参考，勿再据此派工。

- 审计对象：`src/texlate/xlat/`（client/pipeline/batch/retry/state/glossary/prompts/placeholders）、`src/texlate/validate/`（l0/l1/l2/report）、`src/texlate/compile/`（engine/inject/mask/normalize/judge/sandbox + fixloop/ 全部）、`src/texlate/e2e.py`、`cli.py`、`server/worker.py` 编排面；HEAD f461683（v2 切换后）。
- 方法：逐节抽规范断言 → 对照实现与测试 → verdict。只读审计，未跑网关/编译实测；编排链路以 grep + 通读为准。
- verdict 口径：**covered**=实现 + 测试齐；**impl-only**=实现对、无直接测试；**partial**=部分覆盖或有偏离；**missing**=无实现；**changed**=有意偏离 spec（代码内有记录）；**opt-absent**=spec 标可选、未实现（合规但不享受功能）。

## §0 总览链

partial。spec 链 `chunks → 术语物化 → prompt → 批量/重试 → L0 → (L1) → splice → normalize → 注入 → 沙箱编译 → fixloop → clean判定 → zh.pdf`。

- 真实链（server/worker.py）：`acquire_source → route_project → normalize_project → parse_file → XlatPipeline(L0 validate_pair) → reconstruct → prepare_chinese → engine.compile → judge`（worker.py:1149、:1162-1168 `_compile_zh`）。**fixloop 整段缺席**，编译一次即判。
- mock 链（e2e.py:118 `pipe_condition` / :141 `mock_pipeline_run`）：`normalize → mock 翻译 → prepare_chinese → compile → judge`，同样无 fixloop。
- 顺序差异：spec 示意 normalize 在 splice 后，实现两条链都是 normalize 在翻译**前**（对 normalized 源做翻译——语义可辩护，仅注明）。
- 「出 PDF ≠ 成功」铁律：judge.py 的 warnings_hit/expect_cjk 检查 + L0 独立于编译成立（见 §4.3）。

## §1.1 六种 kind + prompt 套件

covered。`xlat/prompts.py`：

- `_KINDS` 六种（para/caption/section_title/abstract/table_text/env_text）+ `KIND_ALIASES` 把 segmenter `Chunk.context`（para/item/节题命令名/env 名等）归一到 kind——v2 切换后 `chunk_to_in`（pipeline.py `ChunkIn`）是唯一适配点，`Chunk.context` 字段仍在（latex/model.py:82-84），接口兼容 spec。
- 组装序 = 头 + TASK + C1–C8 逐字公共块 + `_FUSION_CLAUSE`(C8a) + kind 条款 + (批量时 B1) + C9 PLACEHOLDER_CLAUSE 压轴 + C10 NAME_CLAUSE（仅 para/abstract）+ glossary 尾块——与 spec 公式一致。
- C9 逐字落实（含 `[[SL]]/[[PL]]`），实现额外列 `[[SP]]`（软空格占位符，placeholders.py 实有）——超集，注明。
- `PROMPT_VERSION = "xlat-prompt-v3"` 单源，进 file_cache_key（state.py）满足「prompt 改动必须 bump」契约。
- 测试：test_xlat_prompts.py 覆盖 kind 分派/条款序/glossary 块。

## §1.2 带错重翻（corrector）

covered。`_CORRECTOR_SYSTEM` 专用 prompt（不动共享块）+ `corrector_user_prompt` 三段式 `[Original]/[Translation]/[Error]`（prompts.py）。字段化反馈落实：`previous_validation_error`/`slot_validation_failures` 进 JSON 字段（pipeline.py `_one_chunk` 组请求体处）。阶梯位置：整段第 2 试走 corrector_fn（retry.py `translate_with_ladder` `_stage_whole`）。温度 0.2 沿用 TRANSLATE_TEMPERATURE；「上限 3 轮仍败→fallback+fault」由阶梯三振语义覆盖（fallback_orig → status=skipped/partial，字段名与 spec 字面 `fault` 有出入：ChunkResult 四态 ok/skipped/fault/partial，ladder 耗尽落 `skipped`+`skip_reason`，语义等价）。

## §1.3 批量协议

covered。`xlat/batch.py`：`SHORT_CHAR_LIMIT=300`、`BATCH_MAX_CHARS=2000`、`BATCH_ITEM_OVERHEAD=8`、`CHUNK_HARD_LIMIT=6000`；`pack_batches` 贪心装箱；`encode_batch` `[n]` 编号 + `encode_newlines`；`parse_batch_response` 三级解析（锚定 `\[(\d+)\]` → 非锚定 → `@@` 行兜底）；数量不符/越界/解析失败 → `_one_batch` 整批退化逐条（复用并发额度，pipeline.py）；超大原子 chunk `split_long_chunk` 先切（闭合 scope 句界 + `_safe_cut` 原子 span 避让）。纯占位符 chunk 不发请求、translation=source 直落（pipeline.py:666 `is_placeholder_only` → `status=ok`）。`[[SL]]`/`[[PL]]` 编解码 round-trip（placeholders.py，k≥3 换行保真）。测试：test_xlat_batch.py、test_xlat_placeholders.py、test_xlat_pipeline.py 覆盖。

## §1.4 术语表（三级 + 恒等 + 文档级烤进）

covered，一处接线缺口。

- 五层装载 `Glossary.load`（glossary.py）：user(`$HOME/.texlate/glossary.yaml`/`USER_GLOSSARY_PATH`) → local(`glossary.local.yaml`，优先级介于 user 与 category 之间，合 spec) → category(`terms/index.yaml` → `terms/{cat}.csv`) → default(`terms/default.csv` 404 行，与 spec「default 404」一致) → placeholder 恒等（`setdefault` 最低优先不覆盖真术语，合「ph→ph 恒等注入」）。
- 文档级过滤：`doc_filter` 用 `(?<!\w)term(?!\w)` IGNORECASE|ASCII 扫全部 chunk 源（pipeline.py `_materialize` 对**全部** chunk 含已完成项跑——保证续跑时 prompt 逐字节不变，满足前缀缓存不变式）；排序「实术语按 en.lower()、ph 按 sort_key(TYPE 字典序+n 数值)」稳定（glossary.py `sort_key`）。
- 渲染 `- en: zh` 行表（`render_glossary_block`）追加 system 末尾 ✓。
- CSV 两列无表头、「保原语」一等公民（单列行 = 恒等条目，`load_csv`）✓；yaml 三形态 `flatten_terms`，list 形态拒绝 ✓。
- 产物 `term_dict.json`：`StateStore.GLOSSARY_FILE`（state.py）定义且 `save_maps` 实现；**但 worker 产品链用 `DBStateBridge`（worker.py:307-375）——只实现 load/record/start/finish 鸭子型，不落 term_dict.json**，五表中间产物仅文件版 StateStore 产出。
- 缺口：`Glossary.load(local_path=…)` 参数存在，worker `_make_glossary` 只接 user_path/default——**glossary.local.yaml 论文级覆盖未接线**。
- 运行时术语自增：spec 标「可选默认关」→ 未实现，**opt-absent**。
- 测试：test_xlat_glossary.py 覆盖层序/过滤/CSV/yaml 形态。

## §1.5 判定分工与 LLM-judge

partial。

- env 可译性：黑/白名单在 latex 层（tables.py `PROTECTED_ENVS`/`ARG_TRANSPARENT_ENVS`）；未知 env 处理 = top-level 时 begin 行 literal + 体挖 chunk（fail-open），in_arg 时整段 `[[ENV_n]]` opaque。**`_ENV_JUDGE_SYSTEM` + `parse_env_judge_answer` + `ENV_JUDGE_TEMPERATURE=0.0`/`MAX_TOKENS=16`/3 重试/非 true 一律 fail-open True/6 few-shot 全部成稿**（prompts.py:278-350）——但 grep 全仓**无任何调用点**，「未知 env → judge」链路 missing：False 方向（纯代码 env 不翻）永远不会被触发。
- 段内可译自然语言「无拉丁字母跳过/全大写跳过」：**missing**——只实现了纯占位符跳过（pipeline.py:666）；chunk 发射侧（segmenter.py `_new_chunk`:467）也无此过滤。灰区 fail-open 语义自然成立（没有 judge 兜底，全靠静态表）。
- 宏透明性：latex 层宏表静态分析（MacroKind OPAQUE/TRANSPARENT/LITERAL，model.py:99-107）✓，spec 允许 v0 不做 LLM 判定。
- 编译修复「未命中→LLM 修复器」：fixloop `llm_hook` 机制完整（fixloop/engine.py:328、:668-700 `escalate_llm` fallback 分发、:816/:846 接线点）；**但 fixloop 本身未进编排**（§5 详述），且无生产 llm_hook provider。

## §1.6 并发 / 重试 / 断点 / 缓存键

partial（主体 covered，一处 spec 组件未接线）。

- `asyncio.Semaphore` 并发：`DEFAULT_CONCURRENCY=10`（pipeline.py:55），可配 ✓。
- 首发单飞暖前缀缓存：`_drain` warmup 单飞 → N workers ✓（pipeline.py:1-8 文档串 + `_drain`）。
- 退避：`call_with_backoff` 指数 `base·2^attempt`（retry.py `RetryPolicy` base_delay=1.0）；429 用 `3^attempt` 下限 5s（`rate_limit_floor=5.0`）；timeout 下限 10s（`timeout_floor=10.0`）；`Retry-After` 解析序 **body `error.retry_after`→header→默认**（client.py `_body_retry_after`，≤60s——落实 2026-09-15 B4a 勘误）；`max_tries=5` 合「3~5 试」；失败回退原文 + `skipped`+`skip_reason` 不阻塞整批 ✓。
- 温度：翻译 0.2（pipeline.py:49）；judge 0.0（prompts.py:345）✓。
- 重试阶梯：整段×2（第 2 试 corrector_fn/字段化反馈）→ 行级 `_stage_lines`（`_split_lines_scoped` 闭合 scope 句号切）→ slots JSON（`⟪S0000⟫`、`SLOTS_PER_BATCH=8`、`SLOTS_MAX_ROUNDS=2`、**只重问失败批**、`response_format json_object` + `_strip_json_fence`）→ 三振 `fallback_orig` + warning → `partial` 终态（retry.py 全链）✓。
- **`recover_copied_tokens`：定义 + 单测齐（placeholders.py、test_xlat_placeholders.py:133-158），exact+unique 最长片段优先——但无任何生产调用点**，阶梯各 stage 均未消费 → missing 接线。
- HTTP 状态码分类表：`classify_status`（client.py）401/403→AuthError、402→BillingError、404→EndpointNotFoundError、408/409/425/429/5xx→RetryableHTTPError、余 4xx→ClientRejectedError；`LengthTruncatedError`(finish_reason=length)+`EmptyContentError`；`redact()` provider 无关脱敏 ✓。长度截断触发 `LENGTH_RETRY_MAX_TOKENS=32768` 重试（pipeline.py）——spec 未写数值，实现合理。
- 断点：`StateStore`（state.py）`state.json` + 五表（STATE_FILE/CHUNKS_MAP/PLACEHOLDERS_MAP/GLOSSARY_FILE=term_dict.json/ERRORS_FILE）；`atomic_json` tmp+rename+0600；`load_cache` 损坏隔离不删；`segment_key` = sha256(role\x00source+tags+masked ph-type 快照)——合「source+role+ 失效标签+masked 快照」公式；`file_cache_key` = `sha256[prompt_version+base_url+model+lang+glossary+context](:16)` ✓。`_load_resumed` completed 只收 ok/partial（skipped/fault 续跑重试，pipeline.py:610-613）。
- 产品链断点：worker `DBStateBridge`（worker.py:307-375）以 DB chunks 表承载同一契约（load→(completed,recs)、record 缓冲、worker `_flush_translate` 批量事务落盘）——语义对齐，仅五表中间产物不落文件（见 §1.4）。
- stale-source 自愈：parse 漂移下同 id 陈旧记录按未命中重翻（pipeline.py:655-664，n100 实测 1524 例教训）——spec 未写此条，实现超集。
- 测试：test_xlat_state.py、test_xlat_retry.py、test_xlat_client.py、test_xlat_pipeline.py 覆盖。

## §1.7 本地默认后端

covered。`settings.py:36-37` `DEFAULT_BASE_URL=http://127.0.0.1:<内部网关端口>` + `DEFAULT_MODEL=swe-2-medium`；worker 默认 `GatewayTranslator(client, model or "swe-2-medium")`（worker.py:1316-1318）。`pick_model` 偏好序 `("swe-2-medium","swe-2-high","swe-2-max")` + `DENYLIST={swe-1-7,swe-1-7-medium}`（client.py）——合 spec「备选 swe-2-high、swe-2-max 留修复器、禁 swe-1-7*」序。免费集动态筛：`discover_free_models` = `/panel/api/models`（cost_tier==free ∧ promo.active ∧ ¬disabled）∩ `/v1/models` ∩ probe_model 探活，Semaphore(4)（client.py）。`HIDDEN_PROMPT_TOKENS=465` 记账（spec 给 ~160–566 区间，取值居中）。BYOK：`provider_for_url` host→provider 预设 + `PROVIDER_KEY_ENV` + anthropic/openai 方言（`_PROVIDER_DIALECT`）+ `normalize_base_url` + `validate_base_url`（拒 userinfo/query、非 localhost 强制 https，settings.py:76-96）。测试：test_xlat_client.py + test_xlat_gateway_smoke.py（env 守卫）。

## §2.1 L0 规则层

covered。`validate/l0.py` 七规则全落：placeholder（multiset diff + `PH_FUZZY_RX` 同口径模糊候选 lev≤2 + 修复建议）、brace（`\{\}` 转义/`%` 注释豁免/前缀深度）、env（begin/end 栈 + env 名 multiset）、key（cite/ref/label/bibitem/bibliography multiset + 逗号拆分 + `[..]` 豁免）、math（`$` 计数 + `\(\)\[\]` 成对）、length（比 [0.25,2.50] warn + CJK<30% warn）、macro（zh−src cs 集合 + src 脆弱间距 cs 多重集⊆zh 反向检查 + 31 结构族硬判据）。大样本再修两条已落：占位符严格序守恒降为 warn（E21）、`cs_dropped` 脆弱命令差升 error + 非 ASCII 熔合 cs error（E22）。`validate_pair` → `L0Report.feedback()` 供 corrector 字段化反馈；接线在 worker.py:949（lambda 注入）与 e2e.py:51。测试：test_validate_l0.py。

## §2.2 L1 tree-sitter 层（可选组件）

covered-as-optional。`validate/l1.py`：`TsValidator` JSONL 批处理常驻进程（`--repl`）+ `TsBaseline`/`ok_relative` **强制相对模式**（合「绝对判定不可用」实测结论）+ `ensure_deps` npm i + `available()` 无 node 优雅降级 L0。检查面 ERROR/MISSING/env 配对/unclosed_math/brace_balance/placeholder diff。spec 标可选组件——**未接入 XlatPipeline validator（产品链只有 L0）**，属 opt-absent 的合规缺口：组件本身完整、链上未用。测试：test_validate_l1.py（node 守卫）。

## §2.3 L2 编译 log 回灌

partial→missing（关键环节）。

- log 解析双格式 `^!`+`file:line:`、`l.N`、ctx 8 行、tail 30、`(` 文件栈：三处实现——`validate/l2.py`（L2Verdict + warning 分类 + 红线 + `cjk_missing` + `log_missing=True` tectonic 兜底）、`compile/engine.py parse_log`（`_NONERR_FILELINE_RE` 排除 + WARNING_RED_LINES + `_ERROR_RULES` ~18 类）、`compile/fixloop/logparse.py`（head/tail/warnings 三 scope Taxonomy）。texlog.py 单源文件栈原语收敛三方。解析面 covered。
- **「不过 → 重译该块（错误描述进反馈字段）→ 再不过 → fallback 原文」：missing**。全仓无 L2Verdict→xlat 回灌：`_compile_zh`（worker.py:1162-1168）= compile→judge 终了；e2e 同。L2 产物只在 `validate/report.py` 聚合层与 bench 消费——编译错与具体 chunk 的映射、错误描述进 `previous_validation_error` 字段的回路均未建。

## §3.1 visible_tex 遮蔽 + 逆序回放

covered。`compile/mask.py` `visible_tex`→`textutil.mask_tex`（verbatim/verb/`%` 注释等长空格遮盖、`\n` 保留行号/offset 不变）；`apply_edits` 逆序应用 + 删除补 `\n` 保行号稳定；`group_end` 括号定位。「定位视图≠改写目标」纪律由 API 形态强制（编辑打在原文 span）。测试：test_compile_mask.py、test_textutil_encoding.py。

## §3.2 无条件手术清单（12 项）

covered，一处注入缝偏离（见下）。`normalize.py` 十二项全落、顺序 ≈ spec 1→10：`normalize_comment_terminators`/`normalize_float_positions`/`normalize_pdftex_features`（`\pdf*` 赋值整段删 + `\DisableLigatures` + microtype expansion/spacing/kerning→false、tectonic 再+tracking）/`normalize_pixel_dimensions`（语境受限 `Npx→N\pdfpxdimen`）/三兼容块/`PassOptionsToPackage{no-math}{fontspec}`/`strip_input_encodings`（名字列表只剔 {inputenc,fontenc}）/`normalize_pdf_primitives`（`\pdfinfo` 删、`\pdfoutput=1` 删、pdftex→xetex 只限 hyperref/graphicx/graphics/color/xcolor 可选参独立 token）/`prepare_legacy_latin_fonts`（OT1/T1/LY1→TU `texlate-*` 族映射 + `\usefont/\fontfamily` 改写 + 定义块插 `\documentclass` 后 + 自定义 NFSS 跳过）/`normalize_legacy_cjk`（CJK/CJKutf8→xeCJK+Fandol；lualatex→luatexja）/`use_bundled_bibliography`/`rebase_project_paths`（+`source_path_violations` 检测）。文件级 `normalize_project` + `_transcode_aux_bib`（.bib/.bbl/.bst 转码）+ `stats["encodings"]` 台账。

**偏离**：spec 第 5 条「兼容前导块注入点 = `\begin{document}` 前」；实现把三块直接**前插文件顶**（normalize.py:582/585/591 `PIXEL_COMPATIBILITY + text` 等）——即 `\documentclass` 之前。polyfill 内容均为 `\ifdefined` 守护的原语定义，语义上可用，但与 spec 注入缝约定不一致。

**分工铁律**（无条件手术在 normalize、条件手术在 fixloop）：成立——normalize 无 cond 分支，fixloop rules 全部 error/cond 触发；同名包/同原语两侧无重复改写（microtype 在 normalize 是选项→false、在 fixloop 是 `xetexglyph_tfm` 触发的 `[protrusion=false,expansion=false]` 强制——对象不同维度，注明非冲突）。

测试：test_compile_normalize.py。

## §3.3 中文注入

covered + 一处 changed。

- `CTEX_LINE = \usepackage[fontset=fandol,UTF8]{ctex}` 默认路径；`XECJK_BLOCK` 降级路径；`CJK_PRESENT_RE` 检测既有 CJK 配置（无尾边界，ctexart 等也命中）；`find_docclass_end` 注释感知括号匹配定位注入缝；`inject_cjk` orchestrate；`find_main_tex` latin-dominant language_rank + name/depth/size 排序；`FLOAT_SIZING`（`\resizebox*` + typeout，figure/table 门控）+ `TABLE_FITTING`（threeparttable adjustbox）；`prepare_chinese` 总编排（inject.py）。
- **changed**：spec §4.2「`\documentstyle` → 无条件 reject」；实现降级为 `route_project` 置 `latex209_suspect` 试编标记（engine.py:905/:918-944），注入层 `InjectRejectError`（inject.py:98-107）+ fixloop `latex209_reject` gate（rules.yaml:280-295）作双兜底。代码注释载明动机（TL2026 上 ~23% 误报：现代模板注释/字符串内出现 documentstyle 字样）。功能等效（真 2.09 仍被 inject+gate 拦），判定面从「路由即拒」变「试编后拒」——审计记为有意偏离。
- 测试：test_compile_inject.py。

## §3.4 target_probe 与 compiled_dependencies

partial（一半 missing）。

- `compiled_dependencies`（engine.py:333）：`.fls` INPUT 行 + `dependencies.mk` makefile 双解析、root 有界、main 必填——实现 covered；填 `CompRes.deps`。**消费缺口**：没有任何编排拿它当权威翻译文件集（mock 遍历全部 *.tex；worker 按行集 parse）——产物在、用途未接。
- `target_probe`（spec：翻译前以译文桩编译一遍探字体/模板，探针失败直接进 fixloop）：**missing**。机制零件在 e2e.py（`mock_translate_tree`+`pipe_condition` 恰是桩编译链），但它是 dev harness/`texlate run` 的整链，**未作为 pre-flight 阶段接入 worker 产品链**，且「探针失败→fixloop」因 fixloop 缺席无从谈起。
- `embed_cjk_mappings`（spec §3.3 尾：编译后给 Identity-H/Adobe-GB1 无 ToUnicode 字体注 `Adobe-GB1-UCS2` cmap）：**missing**，仅 judge.py:18 注释引用其名。

## §4.1 Engine 协议

covered。`Engine` Protocol（engine.py:381-441）：`caps` frozenset + `detect`/`compile`（签名即 spec 面，:393/:502/:799 三处 noqa 注释自证）/`probe_file`/`install_file`/`rebuild_fontmaps`/`filemap` + `parse_log`。

- xelatex：flags `-no-shell-escape -interaction=nonstopmode -file-line-error -recorder` + `-halt-on-error`（best_effort 时豁免——spec 写死 halt-on-error，实现给 fixloop salvage 留了非 halt 档，注明）、passes=2、timeout=240、TEXMFHOME usertree、caps={kpsewhich,tlmgr,updmap,recorder}；`install_file` = probe→`_filemap_index`（TlpdbIndex 离线优先 → `tlmgr search --global --file` 兜底 + 磁盘缓存）→`tlmgr --usermode install`→复核；`_install_lock` flock + init-usertree；`TEXLATE_TLNET` 仓 pin（合「historic tlnet/pin cache」条款）。
- tectonic：`-X compile --untrusted --keep-logs --keep-intermediates --makefile-rules --outdir` + `-Z continue-on-errors` + `--web-bundle/--bundle` + `--hide`；`TECTONIC_BUNDLE_PIN=tlextras-2022.0r0` 钉版 ✓；`_TECTONIC_ATTEMPTS=2`；无 .log 时 stderr 兜底（engine.py:850 注释同 spec「tectonic 有时不写 .log」）；caps={bundle}；`install_file` 走注入的 `ctan_fetch`+`filemap_index`。
- 测试：test_compile_engine_judge.py（engine 侧多 mock/条件守卫）。

## §4.2 路由与兜底

covered（documentstyle 条见 §3.3 changed）。`route_project`（engine.py:918）：`*.eps`/`\usepackage{pstricks}`/`pspicture` → xelatex-first（跳过 tectonic 硬墙）✓；frozencache+minted → tectonic 优先 ✓；位图字体包（bbm/dsfont 类）→ flag 标注（失败后换引擎由编排/bench 层消费——worker 单引擎跑一次，「失败后换 xelatex」交叉兜底只在 bench fixloop 臂体现，产品链 partial）；non_utf8 → flag + normalize `_transcode_aux_bib`/decode_tex 转码已前置（spec「iconv 转码预处理」语义达成）。`engine_for` 工厂 + prefer 参数；「M0 开发默认 xelatex / 分发默认 tectonic 优先」由 prefer 默认值与 CLI `--engine auto` 承接。测试：test_compile_engine_judge.py 路由用例。

## §4.3 clean 判定三件套

covered。`judge.py`：`judge` = timeout→fail；killed-signal→dirty；no_pdf→fail；有 pdf 后三件套——① `errors ≤ CLEAN_ERR_MAX=3`；② 首错类别 ∈ `DIRTY_FIRST_CATEGORIES`（missing_file/tfm/pfb/graphic、fontspec_missing、undefined_cs、eps_image、latex209）→ dirty；③ WARNING_RED_LINES（invalid_utf8/fffd_glyph/missing_chars/missing_graphic/degraded_file 即 tectonic File..not found 降级行）命中 → dirty。**中文实际渲染检查**：`count_missing_chars` + `pdf_cjk_chars`（pdftotext，`CJK_MIN_CHARS=20`；expect_cjk 时 missing_chars>0 或 cjk_chars==0/<20 分级记 reason；pdftotext 缺席降级到 Missing-character 计数——恰覆盖 hep-th「8 页 PDF 0 中文字节」场景）。`partial` = 有 pdf 但 dirty ✓。测试：test_compile_engine_judge.py。

## §4.4 编译沙箱

covered。`sandbox.py`：`child_env` **白名单**（`_ENV_PASS_EXACT` + `TEXMF*/TEXINPUTS/…` 前缀 + `_ENV_FORCED`：TECTONIC_UNTRUSTED_MODE=1、openin_any=p、openout_any=p、shell_escape=f、max_print_line=10000）；`--untrusted`/`-no-shell-escape` 已进引擎 flags（§4.1）；`sandbox_wrap` macOS SBPL profile（deny $HOME 读 + deny 全写 + literal/subpath 白名单放行 + file-read-metadata 允许——settings/浏览器 profile/SSH key 编译期不可读语义达成，Linux 侧不生效属平台限制）；`run_process` stdin=DEVNULL + `start_new_session` + `killpg` SIGKILL 进程树超时杀 + 8MB tail cap；`find_tool` which+macOS 路径。

## §5.1–5.4 fixloop 两层 YAML + 主循环

库层 covered / 编排 missing（最大缺口）。

- 两层 YAML：rules.yaml `taxonomy`（~20 类：missing_file/missing_tfm/xetexglyph_tfm/missing_pfb/ps_image/fontspec_missing/illegal_unit/option_clash/already_def/soul_err/hyphenation/minted_froz/inputenc_unicode/latex209/undefined_cs(+subclassify→pdftex_prim、`l.N` cs payload)/capacity/emergency/env_mismatch/syntax(+Extra }/endgroup/fi 族)/other 兜底 + tail-scope latex209 + warnings-scope warn_utf8）+ `rules` 31 条。
- spec 16 条全在（id 逐一对拍 ✓）；§5.2 九条全在：`pstricks_dvips_fallback` 更名 `pstricks_dvips_preflight`（gate/order 0，rules.yaml:308-329，注释自引 docs/08:273）、`ctan_fetch` 版本前置落实为顶层 `version_guard`（rules.yaml:89）+ `check_version_compat`（ctan.py）；扩展条：pstricks_route(precheck/-10)、legacy_pkg_shim(12)、eps_to_pdf(15)、inputenc_strip(94)、aastex_bundle_shadow(155)、journal_cs_polyfill(160)、cs_targeted_fix(165)。
- phase gate/precheck/loop + order 升序 + 每轮一条归因 + `{rule_id}:{pay}` dedup + stuck sig×3 + escalate_llm order 900 兜底：`_match_apply`/`_gate_eval`/fixloop 主循环（engine.py:808+）全落；顺序不变量（gate 先、install 先 rewrite、900 恒末）由 order 编排承载。
- 动作原语 7 种 `_ACTION_KINDS` 全集（engine.py:164-172）；命名函数注册表 spec 写「仅 3 个」——实现 `TRANSFORM_FNS`/`REWRITE_FNS` 已扩到 ~15 个（builtins.py：option_clash_merge/pdftex_prim_polyfill/vendored_shadow_isolate/non_utf8_recode/bbl_stub_rewrite/font_sub_shim/pstricks_dvips_preflight/eps_to_pdf/legacy_pkg_shim/strip_inputenc/cs_targeted_fix/journal_cs_polyfill/bundled_class_shadow/px_to_bp/keep_latin_tokens），spec 表述过时、实现超集。
- `_when_ok`/`_cond_ok` 原语集（tool_available/cap_available/engine_in/main_head_contains/source_contains/ctx_suggests/fileset/cache_dir_glob/vendored_shadow/package_version_ge/prim_read_form/shim_known；未知 cond fail-closed）；per-rule provenance/stats/engines modes + Ruleset 加载校验（version=1/必填键）。
- tectonic 降级：`_wire_engine` 注入 `ctan_fetch`+version_guard epoch（engine.py fixloop 侧）；`CtanFetcher`/`TlpdbIndex`（from_tlpdb/load/save/ensure/query/suggest + `peek_index` lazy）+ `fetch_tlpdb`/`fetch_package`（ctan.py）——「file→tlpdb 离线索引→tlnet 拉取→cwd 平铺遮蔽→查不到 advisory」链完整。
- 主循环：precheck → find_main_tex(strict→loose fallback) → rounds(compile→`_report_of`(log or stdout_tail)→classify→clean check honoring warn_cats→gate→stuck×3→match/apply→unfixable:/dirty_pdf) → salvage best_effort pass → final verdict（acceptable_pdf ≤clean_err_max）→ `_record_case`。
- **缺失面**：
    - **编排**：`fixloop(` 调用点只有 cases.py:151（replay）、bench/py/fixloop_bench.py:293、tests——`e2e.py`/`worker.py` 产品链零引用。**spec §0 主链 fixloop 段未接**。
    - `engine_flags`：规则 params 收集进 `ctx.engine_flags`（engine.py:325/:655-658）并进 cell（:1003），但 `Engine.compile` 签名不收 flags——minted_frozencache 的 `-shell-escape` 等**只记录不生效**。
    - `llm_hook` provider：机制在（escalate_llm 分发 :668-700），生产 provider 无（随 fixloop 未接一并缺席）。
    - shadow 模式（proposed 试运行只记录）：spec 标可选 → opt-absent。
- 测试：test_fixloop_rules/yamlish/logparse/loop/cases/ctan/spikereplay 七件，覆盖厚。

## §5.5 沉淀机制

covered（库层）。`cases.py`：`CaseSink`→cases.jsonl（corpus/cond/engine/rounds[cat/pay/rule/result]/verdict/log_excerpt 全字段）；`triage`（unfixable:/stuck/dirty_pdf/max_rounds/no_errors_no_pdf）；`replay_case` 门①本格重跑、`replay_all` 门②全语料 no-regression、`stats_backfill` 门③ fires/rescued_cells 回填 + proposed→active 建议（非自动——合 spec 语义）。测试：test_fixloop_cases.py。

## v2 切换后 xlat↔segmenter 接口核对

兼容。`Chunk` 仍暴露 `.id/.content/.context/.env/.placeholders`（model.py:76-88）；`context` 值域（para/item/chunk-arg 命令名/env 语境）经 `KIND_ALIASES`→6 kind；`chunk_to_in` 是唯一适配缝；`PH_RX`（`[[A-Z_]+_\d+]`，placeholder.py:18）为 segmenter 签发与 xlat 校验共用单源；`placeholders` 列表由 `_new_chunk` 自动 findall（segmenter.py:467-476）。spec §1.1「按 kind 选 prompt」契约不因 v2 破裂。

## 缺口汇总（按严重度）

| 缺口                                                                     | 层面 | verdict                   |
| ------------------------------------------------------------------------ | ---- | ------------------------- |
| fixloop 未接入 e2e/worker 编排（spec §0 主链缺整段）                     | 编排 | missing                   |
| L2→逐块重译回灌环（§2.3 尾条）                                           | 编排 | missing                   |
| target_probe 翻译前桩编译 pre-flight（§3.4）                             | 编排 | missing                   |
| embed_cjk_mappings ToUnicode cmap 注入（§3.3 尾）                        | 功能 | missing                   |
| env LLM judge 无调用点（§1.5，prompt 全备）                              | 接线 | missing                   |
| recover_copied_tokens 无调用点（§1.6，函数 + 测试齐）                    | 接线 | missing                   |
| 无拉丁字母/全大写跳过规则（§1.5 表行）                                   | 规则 | missing                   |
| engine_flags 收集不生效（fixloop→Engine.compile 断口）                   | 接线 | partial                   |
| compiled_dependencies 产物无权威消费方（§3.4）                           | 接线 | partial                   |
| glossary.local.yaml 层未接 worker；term_dict.json 仅文件版 StateStore 落 | 接线 | partial                   |
| 引擎交叉兜底（tectonic 失败→xelatex）仅 bench 臂，产品链单引擎单次       | 编排 | partial                   |
| documentstyle：spec 无条件 reject → 实现 suspect 标记+inject/gate 双兜底 | 语义 | changed（有意，代码载因） |
| 兼容前导块注入点：spec「`\begin{document}` 前」→ 实现文件顶              | 偏离 | partial                   |
| L1 validator 未接入 pipeline（spec 可选）                                | 可选 | opt-absent                |
| shadow 模式 / 运行时术语自增（spec 可选默认关）                          | 可选 | opt-absent                |
