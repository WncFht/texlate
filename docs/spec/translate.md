# spec · 翻译编排与校验链

> 范围：`xlat/`（翻译编排）+ `validate/`（rules/cst/logattr 三层校验）+ `repair/`（logfix 回灌修复）+ `compile/normalize/`（译文后源码归一化）。编译引擎、注入与 fixloop 见 `compile.md`；chunk 产出与占位符上游见 `latex-pipeline.md`。
> 口径：现行实现描述，符号引用为「模块 + `::符号`」粒度；实测证据见 `research/` 档案。

## 0. 总览

```
chunks[] ──► 术语表物化（四层 + doc 级过滤）+ ph 名单行
        ──► 按 kind 装配 system prompt（编号锚名规则 + kind 槽 + glossary 尾块）
        ──► 全量入批 / 拆分长块 ──► 语义重试阶梯 ──► rules 规则校验（每块即时）
        ──► （可选 cst）──► splice 回写
        ──► normalize 归一化手术 ──► 注入（见 compile.md）──► 编译
        ──► logfix log 归因重译 ──► fixloop（见 compile.md）
```

铁律：**出 PDF ≠ 成功**——校验必须独立于编译存在：实测占位符大面积丢失可产生零编译错误而静默删内容，亦有出 8 页 PDF 但零中文字节的案例[^texglot]。

## 1. 翻译编排（`xlat/`）

### 1.1 入口与管线骨架

`pipecore/translate.py::translate_tree_run` 是 e2e / server worker / bench 三臂共享入口：`latex.api.scan_tex_tree` 做文件级四级分流（parsed 翻译集 / fault / support 不译），chunk_id 形如 `{file_idx}:{chunk.id}`；随后装配 `XlatPipeline`（translator、validator、`Glossary.load()`、cache dict）并 `asyncio.run(pipe.run)`，收尾 `reconstruct` splice 回写。占位符点名册不进 `Glossary`——`_materialize` 里 `render_placeholder_manifest(collect_doc_placeholders(...))` 单独成串。

`pipeline/orch.py::XlatPipeline.run` 内部阶段：`_load_resumed` 载入断点（仅 ok/partial 计入已完成；source 漂移触发重译）→ `_route_chunks` 分流 → `_materialize`（doc glossary 过滤 + paper_ctx：取首个 abstract chunk 截 `PAPER_CTX_MAX_CHARS=6000`）→ `_build_work_items`（kind 分组 → `pack_batches` → batch/single/split 三类 work item）→ `_drain` 消费。

`_route_chunks` 三条短路径：`placeholder_only` 整块纯占位符不发请求、`[[BIB_` 前缀 chunk 原文直通并记 `bib_passthrough` warning、超 `CHUNK_HARD_LIMIT=6000` 的长块经 `split_long_chunk` 按句界二分（`_ATOMIC_CUT_RX`/`abbrev_cut`/`_safe_cut`）拆成 `(parent, subs)`。

### 1.2 chunk 类型与 system prompt 套件

六种 chunk kind：`para` / `caption` / `section_title` / `abstract` / `table_text` / `env_text`，各配 `_TASK_SENTENCE[kind]`。装配公式（`prompts.py::build_system_prompt`，逐字固定；规则扁平编号、一规则一物理行、`**Anchor.**` 锚名做 spec/测试句柄）：

```
_HEADER + TASK_SENTENCE[kind] + [paper-context 子句]
+ 规则块（`1. **Scope.** … N. **Batch protocol.**`，编号仅序位语义）
+ GLOSSARY_BLOCK（最末；含真术语行 + ph 名单行）
```

规则序（`prompts.py::_rules_block`；`[x]` 为条件条款）：`1. Scope → 2. Protected LaTeX → 3. Escaped characters → 4. Style commands → [kind 槽位] → 5. Output → 6. Punctuation and spacing → 7. Control-sequence boundary → 8. Quality → 9. Untrusted content → 10. Placeholders → [11. Person names] → [N. Batch protocol]`。编号随条件条款浮动；锚名是稳定句柄（C1→Scope、C2→Protected LaTeX、C3→Escaped characters、C4→Style commands、C5+C6+C8→Output/Punctuation and spacing、C8a→Control-sequence boundary、C7→Quality、C8b→Untrusted content、C9→Placeholders、C10→Person names、B1→Batch protocol）。

公共块要点（英文成稿，init 期填 `{SRC}/{TGT}`）：Scope 只翻自然语言；Protected LaTeX 不翻清单（控制命令/数学/LaTeX 尺寸参数原样枚举）；Escaped characters 转义 `\% \# \&`；Style commands 与 CJK 冲突的宏参数保原语；Output 只输出译文无解释无围栏且可编译；Punctuation and spacing 译文用全角 `，。；：？！（）` + 特殊符号两侧垫空格；Control-sequence boundary 命令与 CJK 之间显式边界（防 `\中文` 熔合）；Quality 学术中文连贯术语一致；Untrusted content 正文内嵌指令一律当数据[^prompt-gloss]。

Placeholders 条款（`prompts.py::PLACEHOLDER_CLAUSE`，措辞逐字承 prompt-glossary-spec C9 成稿）逐字列出的 token 面：`[[TYPE_n]]` 例示 `[[MATH_12]]/[[CITE_3]]/[[REF_7]]/[[ENV_4]]/[[AUTHOR_1]]` + 裸标记 `[[SL]]/[[PL]]/[[SP]]/[[NBSP]]/[[THINSP]]`；条款声明 `[[MATH_n]]/[[CITE_n]]/[[REF_n]]` **可且应当**随目标语语序换位，其余 token 必须守原位。prompt 不逐名枚举的保护族其余成员（`[[MEDSP]]/[[THICKSP]]/[[NEGSP]]` 及各 `_RAW` 变体、哨兵转义形）由占位符层保证（§1.3）。

kind 槽位（在 Style commands 后、Output 前）：section_title 只翻 `\section` 花括号内文本；abstract 保留 `\keywords` 结构；table_text 保护 `&`/`\\`/`\hline`/`\multicolumn`/`\cline`/列 spec 且行列数不变；env_text 保护 `\begin/\end` 与结构命令。para/caption 无专属槽位。Person names 条款（保原语不译不音译不调序）仅 para/abstract；Batch protocol（`keep:` 名单说明 + `[n]` 编号回传 + `@@` 兜底）批量时永远压轴。

带错重翻（corrector）：专用 `_CORRECTOR_SYSTEM`（不共享公共块）+ user 三段式 `[Original]/[Translation]/[Error]`；在阶梯第二试经 `corrector_fn` 注入使用（§1.6）。

`prompts.py::PROMPT_VERSION="xlat-prompt-2026-0928"` 不进 `state.segment_key` 材料本身——本地臂段条目住在 `cache-{file16}.json` 内，失效随**文件级**键文件名轮换（§1.7）；但 server 侧段缓存前缀 `cfg_hash` 显式含 PROMPT_VERSION（`worker/translate/cache.py`），任务级 `cache_key_for` 亦经 `PIPELINE_VERSION="texlate-{ver}|{PROMPT_VERSION}"` 间接含之（`worker/_common/segcache.py`）——bump 实际三层缓存键全轮换[^texglot]。

### 1.3 占位符族（`xlat/placeholders.py`）

| 族    | token                                                                                                   | 保护对象                                                                                    |
| ----- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| typed | `[[MATH_n]]/[[CITE_n]]/[[REF_n]]/[[ENV_n]]/[[AUTHOR_n]]` 等                                             | 数学/引用/参照/环境/人名等受保护 LaTeX 片段（上游 `latex.placeholder` 产出，`TYPED_PH_RX`） |
| 换行  | `[[SL]]`（单换行）、`[[PL]]`（`\n\n+` 空段保底）                                                        | 段内换行编码，送翻/回译对称                                                                 |
| 空格  | `[[SP]]`=`\`、`[[NBSP]]`=`~`、`[[THINSP]]`=`\,`、`[[MEDSP]]`=`\:`、`[[THICKSP]]`=`\;`、`[[NEGSP]]`=`\!` | 脆弱间距命令防熔合丢失，各带 `_RAW` 变体                                                    |
| 哨兵  | `[[__TEXLATE_{tag}_LIT{n}__]]`                                                                          | 源文本字面含占位符形串时的转义链，支持任意深度嵌套（level≥2），对 `ANY_PH_RX` 不可见        |

`encode_newlines`：`\n`→SL，k≥2 连换行→`PL×(k//2)+SL×(k%2)`；`EOL_RX` 归一 `\r\n|\r|\x0b|\x0c|\x85|U+2028|U+2029`。`diff()` 做 masked 多重集差 + lev≤2 模糊配对；`_BENIGN_EXTRA_TYPES={NBSP}` 容忍模型自发加入；注释区多余项单独计数。`recover_copied_tokens`：模型把受保护原文抄回译文时，仅**边界精确 + 全库唯一出现**才换回 token，不猜。

### 1.4 批量协议（`xlat/batch.py`）

- **无短/长分流**：所有 chunk 一律进批。`pack_batches` 常量：`BATCH_MAX_CHARS=12000`、`BATCH_MAX_ITEMS=32`、`BATCH_MIN_CHARS=2500`、`BATCH_ITEM_OVERHEAD=8`；`n_req=max(ceil(total/max_chars), min(workers, total//min_chars))`，超出 worker 数时向上取整到 worker 倍数做 K 量化等长分包。装箱容量按 `overheads` 逐项实记：管线喂 `batch_member_overhead`（`[n]` 编号 + `keep:` 前缀实长——ph 密集成员名单可达数百字符，平摊 8c 会低估实发 payload 悄悄超硬顶击穿 `max_tokens`）。
- 请求编码 `[1]…[n]` 行首编号；含占位符的成员序号行内嵌 `keep: <ids> |` 名单前缀（`[i] keep: [[MATH_1]] [[SL]] | <enc>`——点名该成员须保真的占位符集合，`|` 分隔名单与正文；ph-free 成员保持 `[i] <enc>` 无前缀）。名单取 `find_all` 首见序去重、裸族 token（`[[SL]]`/`[[NBSP]]` 等）与类型化 `[[X_n]]` 同列——keep 名单机制即对症夜跑归因的 ph 密集成员梯级重试风暴[^keep-roster]。
- 解析 `parse_batch_response`：先归一全部 Unicode 行界，再只认**行首锚定** `^\s*\[(\d+)\]`（MULTILINE）；序号多重集须恰为 {1..n}（乱序归位）且段段非空。行内 `[k]` 不可用作分隔——与正文引用号在 token 层不可区分，命中即整批拒收。段首 `keep: <ids>` 回显（`|`/换行可有可无）按协议残码剥除；名单独占段判空——名单与成员 ph 多重集天然同集，留非空会骗过 `diff` 漏成译文。
- `@@` 路径：段数恰 n 才收；段内出现 `[k]`（1≤k≤n）判序号泄漏拒收（`[0]`/`[k]` k>n/`[[k]]` 按字面放行）；裸 `[n]` 桩段（`_STUB_ONLY_RX`）按空槽丢弃；编号段内 `@@` 独占行按协议残码剥除；`keep:` 回显同剥。
- 退化：数量不符/越界/歧义 → 整批退回逐条单翻（复用并发额度）。

### 1.5 并发、退避与熔断

并发是 **worker 池**：`_drain` 首发一件 solo 暖前缀缓存，随后 `asyncio.Queue` + `DEFAULT_CONCURRENCY=10`（`PipelineConfig.concurrency` 可调）个 worker 协程消费、哨兵收尾；semaphore 只出现在模型探活（并发 4）。

`retry.py::RetryPolicy`：`max_tries=5`、`base_delay=1.0`；退避 `base·2^attempt`；429 用 `base·3^attempt` 且下限 `rate_limit_floor=5s`；timeout 下限 `timeout_floor=10s`；`Retry-After` 兑现（body `error.retry_after` 秒值优先于 HTTP header，上限 `MAX_RETRY_AFTER_S=60`）——本网关 429 的 retry_after 在 body 不在 header[^texglot]。`e.max_tries` 逐错型封顶。

`xlat/authgate.py::AuthGate`（自 pipeline 出叶；threshold 由 `PipelineConfig.auth_fail_threshold=3` 供）熔断：连续 3 次认证错闩锁 `tripped`——`_drain` 剩余项按 auth 失败记账不再发请求（避免 50+ 块重复烧 quota），`run()` 收尾抛 `AuthTrippedError` 判论文 fault。

### 1.6 语义重试阶梯（`xlat/retry.py::translate_with_ladder`）

四段阶梯，逐段收窄：

| 级  | 语义                | 要点                                                                                                                                       |
| --- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | 整段 ×2             | 第二试优先 `corrector_fn`（专用 corrector prompt），否则带字段化 `previous_validation_error` 反馈重试                                      |
| 2   | `_stage_lines` 行级 | `_split_lines_scoped` 闭合 scope 边界逐行译 + 审计重试；坏行回填 `src_l`                                                                   |
| 3   | `_stage_slots` 槽位 | `⟪S%04d⟫` 槽位 JSON（`response_format=json_object`）、`SLOTS_PER_BATCH=8`、`SLOT_MAX_CHARS=1500`、`SLOTS_MAX_ROUNDS=2`；失败槽只重问失败批 |
| 4   | `fallback_orig`     | 回退原文                                                                                                                                   |

`_valid_slot_text` 按**字符出现**拒收槽译文：`⟪`/`⟫`/`[[`/`]]` 任一出现即非法，覆盖非规范/未闭合/小写残码与半边 token——畸形 token 放行会把原文带进译文。`bare_token_audit(shown_src, zh_raw)` 在解码前对 8 个解码族裸令牌做多重集比对；`_BENIGN_MISS_TOKENS={NBSP}` 只赦**丢失**向（`in>out`——`[[NBSP]]` 丢了 decode 后只少个 `~`，是夜跑唯一存活失败类、对 prompt 侧一切变体免疫，审计侧赦免得解[^keep-roster]）；`in<out`（凭空铸 token）一切族维持硬败。

结果映射：`LadderResult.status ∈ {ok, recovered, fallback_orig}`；pipeline 把 `recovered`→chunk `partial`、`fallback_orig`→`fault` + `error_kind="validate"`。`ChunkResult.status ∈ {ok, skipped, fault, partial}`，`fell_back` 属性；`error_kind ∈ {"", auth, provider, crash, validate}`。

### 1.7 拦截网与缓存口径

`_INTERCEPT_NETS`（`xlat/intercept.py` 唯一枚举面——自 pipeline 出叶，`pipeline/` 回引）注册五张升格拦截网：`leftover_ph`、`ph_in_cs`、`bare_cs`、`residual_en`、`dangerous_cs`——与 `rules/main.py::CACHE_VETO_RULES` 同集合镜像。三处消费同迭代本表（intercept.py docstring 口径）：`_interceptable` bool 形——`_cache_hit`/`_cache_store` veto 毒化缓存条目（缓存命中与续跑旁路同样过网，命中旧毒条目清除重翻）；`pipeline._ledger_intercepts` 账本形——译文产出时经 `_net_apply_fn` 晚绑定取件，命中即 fault + 回退原文（`_load_resumed`/`_ledger_outcome` 共用）；`pipeline.retranslate_chunk` 裸形——logfix 回灌重译判定直迭代注册表。

缓存三层口径[^texglot]：

| 层     | 键构成                                                                                                                                          | 落点                                                                                                   |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 段级   | `state.segment_key` = `sha256(role␀source␀失效tag…␀masked␀快照)`；`masked_snapshot` 是占位符布局摘要（`repr(ph_types)`），token 布局变则 key 变 | `xlat` 本地：`cache-{file16}.json` 内条目；server：`translation_cache` 表，键 = `{cfg_hash}:{seg_key}` |
| 文件级 | `state.file_cache_key` = `sha256(prompt_version\|base_url\|model\|lang\|glossary\|context)[:16]`                                                | `cache-{16hex}.json` 文件名                                                                            |
| 任务级 | `worker/_common/segcache.py::cache_key_for` = `sha256(arxiv_id@ver\|model\|PIPELINE_VERSION\|lang[\|src:channel][\|fm:集][\|k:key指纹])`        | `tasks.cache_key` 活跃态部分唯一索引（dedup/attach）                                                   |

server 侧段缓存前缀 `cfg_hash` = `sha256(model|PROMPT_VERSION|target_lang|base_url|u:user_glossary_sig|l:local_sig|c:categories|ag:auto_glossary)[:16]`——base_url 进指纹防跨 provider 混桶中毒，categories/auto_glossary 开关进指纹同理；文档级 placeholders 不进（会把缓存锁成单文档桶）。`TEXLATE_CACHE_SCOPE=per_key` 时任务级与段级键均拼入 `sha256(api_key)[:16]` 指纹按凭证分桶，消除跨租户缓存存在性 oracle；默认 `shared`（公开论文确定性函数跨租户复用是既定特性）。`SegmentCache` 读面 = `_pending ∪ _written ∪ _pre`（prewarm 批量预载，`drain` 随 chunk flush 事务落盘）。

### 1.8 断点续跑（`xlat/state.py`）

`state.json` 逐块原子落盘（tmp+rename+0600）：`{version, meta{model, pipeline_version, total_chunks}, completed[], results[], errors_report[]}`；中间产物五表 `chunks_map/placeholders_map/glossary/state/errors_report`——重建器只读 map 表。续跑仅 ok/partial 计入完成；source 漂移块自动重译。段级缓存读入逐条再校验（只留 str→str），损坏文件改名隔离不删（`load_cache`）。

### 1.9 术语表（`xlat/glossary.py` + `xlat/terms/`）

四层 `setdefault` 先占先得（高层独占覆盖）：

```
① 用户表  家目录 `.texlate/glossary.yaml` | --glossary csv
② 论文级  output/{paper}/glossary.local.yaml
③ category 表  terms/{cat}.csv（index.yaml 映射，resolve-jail 防逃逸）
④ 内建默认  terms/default.csv
```

- 格式：CSV 两列无表头 `en,zh`、`#` 注释、utf-8-sig；单列行 → zh=en（保原语一等公民）。YAML 接受平铺 map / `{target:}` / `{"terms":{}}` 三形，list 拒绝，null→en。
- **ph 名单行（替代恒等注入）**：旧式 `glossary[ph]=ph` 逐条恒等注入是 O(doc_ph)×O(calls) 的重发成本（实测占新输入 ~85%），现改为 `placeholders.render_placeholder_manifest(collect_doc_placeholders(...))` 渲单行点名册压 `<Glossary>` 块末行——同 head 连号压缩 `[[MATH_1]]..[[MATH_3]]`（≥2 连号才压）、裸 token 原样枚举；清单超 `_PH_MANIFEST_MAX_CHARS=4000` 退化为**无括号** `TYPE×n` 计数形（带括号残形会命中 `BARE_PH_RX`/`PH_FUZZY_RX` 被判多余占位符触发成员重翻）。规模 O(类型 + 连续段) 而非 O(占位符)——2026-09-28 网关实测：2609.19506 stress 批输入 token 119802→4408（−96%），152/152 占位符全保留、0 成员重翻。
- **文档级过滤 + 整表烤进**：启动时扫全部 chunk 源文本，`(?<!\w)term(?!\w)`（IGNORECASE|ASCII；term 内空白/`~`→`[~\s]+`）筛出本文实际出现词条 → 序列化为 `- en: zh` 行表追加 system prompt 末尾——整篇翻译期间 system prompt 逐字节不变，供前缀缓存命中。真实词条按 `en.lower()` 排（ph 形 en 是普通词条无特判），字节稳定是缓存命中前提。
- `terms/index.yaml` 类目映射：`stat.ML`→`cs.ML.csv`、`eess.AS`→`cs.AI.csv`、`cond-mat.*`→`cond-mat.csv`、`quant-ph`→`quant-ph.csv`，未列→`default.csv`。资产行数：default 404 / cond-mat 756 / cs.LG 357 / cs.ML 305 / cs.RO 354 / quant-ph 311 / cs.AI 212 / cs.CV 158。种子表来自 LaTeXTrans[^latextrans]。
- 产物落盘 `term_dict.json`；运行时逐篇抽取臂 `autogloss.py` 的缺省分面：`TEXLATE_AUTO_GLOSSARY` env 仅闸本地 `run`/e2e（mock 占位管线）与 bench——该路径缺省关（`PipelineConfig.auto_glossary_fn`）；server/web 任务走逐任务选项 `auto_glossary` 且缺省已开（`server/http.py::_clean_task_options` 注入 `True`），此 env 在真实翻译路径无效。抽取细节：masked chunk 文列 → LLM JSON `[{src,tgt}]` → 归一键多数表决；`EXTRACT_BATCH_CHARS=2400`、`EXTRACT_MAX_BATCHES=6`、`EXTRACT_TEMPERATURE=0.1`、单批失败跳过。

### 1.10 网关客户端（`xlat/client.py`）

默认对接**内部 OpenAI 兼容网关**（`DEFAULT_BASE_URL` 指向本机回环端点；`TEXLATE_BASE_URL`/`TEXLATE_API_KEY`/`TEXLATE_MODEL`/`TEXLATE_DIALECT` env 逃生舱，`env_credentials` 读取；dialect ∈ `auto|openai|anthropic|responses` 四方言）。`chat()` 是生产主路径（非流式）；`chat_stream` 已接线生产——`chat` 的流式兜底臂（`stream_fallback`/`TEXLATE_STREAM_FALLBACK` opt-in，默认关），对 `_stream_rescuable` 判定的「非流式路由死亡」形错误（传输族/5xx，2026-09-19 网关非流式全模型 502、stream 独活实证）原地补发；其余消费方仅 tests/smoke。错误谱/方言编解码/免费集发现链/SSE 流式面已出叶 `_errors|_dialects|_discovery|stream.py`，`client.py` 经 `from leaf import` 回引保持 `texlate.xlat.client.X` 钉点面不变（ChatClient 留薄委托）。

- 模型面：`DEFAULT_MODEL="swe-2-medium"`；`DEFAULT_MODEL_PREFERENCE=("swe-2-medium","swe-2-high","swe-2-max","glm-5-2")`；`DEFAULT_MODEL_DENYLIST={"swe-1-7","swe-1-7-medium"}`（精确两枚，非通配）；`FALLBACK_MAX_CANDIDATES=3`。
- 免费集动态发现 `discover_free_models`：网关面板 `cost_tier=="free"∧promo.active∧!disabled` ∩ `/v1/models` ∩ 探活（Semaphore 4、`max_probe=12`）+ memoize——**仅 `is_free_gateway_url`**（回环 ∪ CGNAT 段 ∪ tailnet 域名）启用；`fallback_candidates`/`_FallbackTranslator`（worker `retry_model`）消费。
- 超时：`DEFAULT_TIMEOUT=httpx.Timeout(180, connect=10, read=300)`；`PROBE_TIMEOUT=60s`、`PROBE_MAX_TOKENS=8192`（= `REASONING_MIN_MAX_TOKENS`，reasoning 思考链同吃预算、小探针会假阴；server 端点探针同口径）。
- 错误型谱：`AuthError`(401/403) / `BillingError`(402) / `EndpointNotFoundError`(404) / `RetryableHTTPError`(429/408/409/425/5xx) / `ClientRejectedError` / `ContentFilterError`(max_tries=1) / `LengthTruncatedError`(status=200 伪装，max_tries=2，带 partial_content) / `EmptyContentError`·`MalformedResponseError`(max_tries=2)。
- `redact()` provider 无关脱敏（Bearer/sk-_/sk-ant-_/AIza*/key=:token= + 显式 api_key）；`provider_for_url` host→provider 预设表（anthropic/deepseek/dashscope/azure|openai/其余 custom），`PROVIDER_KEY_ENV` 映射各家 key env——BYOK 通道。

### 1.11 mock 臂与 translator 决议

`mock.py::MockTranslator`：确定性无网络；`_MOCK_TOKEN_RX` 保占位符/cs/花括号/`~$&|`；散文片段→`MOCK_ZH` 按 `max(1,len//8)` 重复；回显 `[n]` 批号、剥 `[placeholder_values]` 尾、`json_object` 时回 `{sid: mock_zh}`；记 `self.calls`。worker 侧 `server/worker/translate/xlator.py::_resolve_translator` 决议序：注入 `translator_factory` → `TEXLATE_TRANSLATOR=mock` → 网关臂（`force=="gateway"` 或有 api_key）→ 无 key 记 `mock_translator` warning 后抛 `AuthError`（静默假译文是事故面，mock 只对显式 opt-in 可达）；`sink` 在场给 `_PerCallTranslator` 惰性 ChatClient（ephemeral loop 消费面）。主链网关臂的备选链 `_FallbackTranslator` 序：`retry_model` 同 client 换模臂 → `endpoints.json` 端点档案臂（`_endpoint_arms`），合计封顶 `FALLBACK_ARM_MAX=4`。档案臂三闸——`secrets.source=="header"`（单发 key 绝不扇向第二端点）、非 local 形态、档案缺席——任一命中即空链，行为与无档案逐字节同构。profile `models` 条目形 `{model, redirect_model}`：`model` 是档案内本地名（展示与探针报告键），`redirect_model` 非空时上游收到的是它（别名重定向）；线名 = `wire_model(entry)`（`redirect_model || model`）——臂名、`exclude` 去重、激活写回 `settings.model` 一律走线名。建档两遍：先活动 profile 余模（同 client 同凭据零成本换模），再按档案序各 enabled 异端点 profile 首模各带自家 client（disabled 不参与——`active_id` 是定位不是参与）。异端点臂 key 走 `credential_for` 四级阶梯，`ctx.secrets.api_key` 绝不发向异 base_url；无凭据远程端点跳过（必 AuthError 白烧一跳），回环端点无 key 合法。切臂按目标 base_url 按任务去重发 `endpoint_fallback` warning；`retry=False` 旁路臂（llm_hook）不接任何备选。单块重译（`worker/retranslate.py`）无 api_key 时直接跳过——不以 mock 覆盖真译文。

## 2. 校验链（`validate/`）

三层分工 rules 规则 / cst tree-sitter CST / logattr 编译 log 归因，**全部 src↔zh 相对判定**（译文不得比原文更坏——src 自带不平衡继承容忍，只报新增损伤）。编排侧消费点：`CACHE_VETO_RULES={placeholder, ph_in_cs, bare_cs, residual_en, dangerous_cs}` 缓存写入/命中否决面（与 §1.7 `_INTERCEPT_NETS` 镜像）、`report.py::pair_feedback` 字段化反馈文本（`previous_validation_error`/`slot_validation_failures` 阶梯注入面）、`LogVerdict` 修复链触发。完整规则表、cst baseline 协议、logfix 归因豁免与聚合口径见 `spec/validate.md`（rules 实测见[^rules-lab]，cst 实测见[^cst-ts]）。

## 3. 修复与归一化

修复链序（precheck → logfix 回灌 → fixloop）、logfix 归因 - 重译簇、env judge 与 `repair/mech.py` 共享低层件的完整规范见 `spec/validate.md` §6–§7。编排侧须知两点：链序理由 = fixloop 的 regex_rewrite 会被 logfix resplice 冲掉；回退后补一次裸编、回落态即交付树。env 开关 `TEXLATE_NO_LOGFIX`/`TEXLATE_ENV_JUDGE`/`TEXLATE_NO_FIXLOOP`/`TEXLATE_FIXLOOP_LLM` 同节登记。

### 3.1 归一化层（`compile/normalize/`）

译文 splice 回写后、注入前的**无条件手术**层（条件性手术归 fixloop，两边不得重复改同一处）。

方法论——遮蔽视图 + 逆序回放：所有正则定位打在 `compile/mask.py::visible_tex` 等长遮盖视图上（verbatim/Verbatim/lstlisting/minted/filecontents/comment 环境 + `\verb` + 行内 `%` 注释遮盖为等长空格，`\n` 保留→行号/offset 不变）；编辑列表 `(start,end,replacement)` 经 `apply_edits` **逆序**应用到原文；视图永不回写；删除类编辑以补回换行保持行号稳定。

`normalize_engine(text, engine, *, doc_source=True, prologue=True)` 严格序：

1. `normalize_comment_terminators`——`\end{comment}` 行尾空白剥掉。
2. `normalize_float_positions`——float 位置参数非法字符剥掉。
3. `normalize_manual_hyphens`——手插连字符形态归一。
4. `normalize_pdftex_features`（tectonic/xelatex 限定）——`\pdf*` 输出系赋值整段删 + `\input glyphtounicode` 删；microtype `expansion/spacing/kerning`（tectonic 加 `tracking`）选项→`=false`。
5. `normalize_pixel_dimensions`（doc_source 限定）——尺寸语境 `Npx`→`N\pdfpxdimen`、`Nbp` 多值键（语境受限非全局 sed）。
6. `PIXEL_COMPATIBILITY` 前置（prologue 限定）——`\pdfpxdimen` polyfill 块。
7. `preamble_ok`（has_document ∧ ¬standalone/subfiles 子文档）才 prepend `XETEX_COMPATIBILITY`（microtype TU 限定 + breakurl `\ifpdf` 暂存 + quantumarticle PassOptions + pstricks 探针）+ `TECTONIC_FONT_COMPATIBILITY`（bbm→dsrom/dsss 向量字体 shim，tectonic 限定）+ `\PassOptionsToPackage{no-math}{fontspec}`——兼容块插**文件顶**（`\PassOptionsToClass` 语义所迫）。
8. `_splice_early_defs`（prologue 块内 + doc_source 限定；刻意不挂 preamble_ok/bd 闸——bd 藏 `\input` 子件时仍须注入；`SUBDOC_CHILD_RX` standalone/subfiles 子档跳过）——preamble 消费的仿真定义 `XETEX_EARLY_DEFS`（含 `\DeclareUnicodeCharacter` 仿真）逐缝插 `\documentclass` 之后（`\documentstyle` 缝滤除，全部用户 preamble 之前），幂等闸为块字面包含 + `\providecommand` 多缝重放安全。
9. `strip_input_encodings`——`\usepackage` 名单只剔 `{inputenc,fontenc}`，其余保留。
10. `normalize_pdf_primitives`——删 `\pdfinfo{...}`、删 `\pdfoutput=1`；驱动选项 `pdftex→xetex`（只改 hyperref/graphicx/graphics/color/xcolor 可选参内独立 token）。
11. `normalize_legacy_cjk`（lualatex 追加）——`CJK/CJKutf8`→xeCJK+Fandol，lualatex→luatexja。

树级手术（`normalize_project` 链序：junk → tex 件逐件 → transcode → legacy latin → rebase → shadow）：

- `_neutralize_junk_files`——`JUNK_FILE_STUBS`+标记闸命中件置 stub（隐藏路径/符号链豁免）。
- `_normalize_tex_files` 逐件：`_strip_lead_junk`（4096 窗剥文件头垃圾字节）→ `decode_tex_with` 分档解码 + `_record_verdict` → `normalize_engine`（doc_source=`.tex/.ltx` 后缀；prologue=doc_source ∨ `_prologue_ok` 严格 UTF-8 无 NUL）→ bbl 复用 → 写回。
- `use_bundled_bibliography`——`.bib` 缺失但声明词干的 `.bbl` 存在且含 `\begin{thebibliography}` → `\bibliography{x}`→`\input{<词干>.bbl}`（相对编译 cwd 的 posix 路径，relpath 不越 `..`；多只 `\bibliography` 只换首个缺库者；visible 已含 `\input{<target>}` 即不改——工程级幂等防逐跑累加）。
- `transcode.py::_transcode_support_files`——`.bib/.bbl/.bst` + `.aux` 系可再生中间产物非 UTF-8→UTF-8 转码写回；中间产物另加截尾整形（`_trim_intermediate_tail` 砍回最后一个完整行界：XeTeX 8192B 写缓冲在边界劈断多字节字符比非法字节更致命）[^aux-cjk]。另含 PS 图形件（`.eps/.epsf/.epsi/.mps/.ps`）`%` 注释行逐行净化 + `%%BoundingBox: (atend)` 头行 trailer 实值回填 + DOS-EPS 魔数整件豁免（台账 `sanitized_ps_comments`/`resolved_atend_bbox`/`dos_eps_skipped`），与全树非手术面/非 `BINARY_SUFFIXES` 件 strict-UTF-8 catch-all 转码（`transcoded_data`，含 NUL 字节且非 UTF-16 形态兜底不动）；中间产物截尾整形外另有「无完整行界即 unlink」purge 臂（台账 `trimmed_intermediates`/`purged_intermediates`）。
- `prepare_legacy_latin_fonts`——OT1/T1/LY1→TU：`ptm→texgyretermes` 等映射 + `\usefont/\fontfamily` 改写 + `\newfontfamily` 定义块插 `\documentclass{}` 后（自定义 NFSS 族跳过）。
- `rebase_project_paths`——`\input/../foo.tex` 越界引用重写为包内正确相对路径；`source_path_violations` 审计迭代器。
- `shadow.py::_shadow_broken_system_packages`——xelatex/lualatex 下 kpse 批量 resolve，坏字节系统包遮影进 main_dir（`_SHADOW_MAX_ROUNDS=8` 传递闭包）。

统一豁免：树级手术/审计面凡任一路径段以 `.` 前缀即整体跳过（`_hidden_path`）；单件读写 OSError 不中断整树，跳过保持原样、debug 落日志。

## 4. 状态词表（翻译侧）

| 域       | 字段                     | 取值                                                                                                                               | 产出                     |
| -------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| 块态     | `ChunkResult.status`     | `ok` / `partial`（阶梯 recovered）/ `fault`（翻译或校验错；fallback_orig 亦落 fault + `fell_back`）/ `skipped`（门控跳过）         | `xlat/pipeline/types.py` |
| 阶梯态   | `LadderResult.status`    | `ok` / `recovered` / `fallback_orig`                                                                                               | `xlat/retry.py`          |
| 错误型   | `ChunkResult.error_kind` | `""` / `auth` / `provider` / `crash` / `validate`                                                                                  | `xlat/pipeline/types.py` |
| logattr  | `LogVerdict.ok`          | `n_errors==0`；`log_missing` 单列                                                                                                  | `validate/logattr.py`    |
| 编译判决 | `Verdict.status`         | `clean` / `partial` / `fail`（无 reject——拒绝统一 partial + `reject_at` 审计字段，见 compile.md）                                  | `compile/judge.py`       |
| 任务态   | job `status`             | 活跃 `queued`/`fetching`/`parsing`/`translating`/`compiling`；终态 `done`/`partial`/`fault`/`cancelled`/`interrupted`/`needs_auth` | `server/store/`          |

### 参考文献

[^texglot]: TeXlate 调研档案：texglot 模式实录——归一化层/缓存键/重试阶梯/沙箱与网关实测。[research/latex/texglot-patterns.md](../research/latex/texglot-patterns.md)

[^prompt-gloss]: TeXlate 调研档案：prompt 套件与术语表工程规格。[research/latex/prompt-glossary-spec.md](../research/latex/prompt-glossary-spec.md)

[^rules-lab]: TeXlate 调研档案：L0 校验规则设计与对抗实测。[research/latex/validator-rules.md](../research/latex/validator-rules.md)

[^cst-ts]: TeXlate 调研档案：tree-sitter 校验层与 baseline 相对判定。[research/latex/validator-ts.md](../research/latex/validator-ts.md)

[^aux-cjk]: TeXlate 调研档案：aux 中间产物 CJK 截断归因。[research/latex/2026-09-16-aux-cjk-truncation.md](../research/latex/2026-09-16-aux-cjk-truncation.md)

[^latextrans]: NiuTrans. LaTeXTrans（术语表种子来源，MIT；arXiv 2508.18791）. [github.com/NiuTrans/LaTeXTrans](https://github.com/NiuTrans/LaTeXTrans)
