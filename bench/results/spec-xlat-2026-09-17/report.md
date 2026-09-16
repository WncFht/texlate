# spec-xlat — docs/08 §1–2（+ docs/06/07 xlat 面）vs `src/texlate/xlat/` 规格对账（只读）

> 2026-09-17。只读对账，零代码改动。范围：docs/08 全规格中 xlat 段（§1 翻译编排、§2.3 L2 的 xlat 侧、§6 块态）、docs/07 §9 译文契约、docs/06 §术语/产物行；实现对 `src/texlate/xlat/` 九文件 + 消费方 worker.py/e2e.py/cli.py/export/common.py。

总评：**核心语义件全部实装且参数合规格**（prompt 套件/批量协议/阶梯/术语表/退避/断点/HTTP 分类）；drift 集中在「实装但未接线」与「规格文本滞后」两类。

## 一、对账表

| 规格条目 | 位置 | 实现状态 | 裁断 |
|---|---|---|---|
| 六 kind prompt 套件 C1–C8 逐字共享 + 组式 | docs/08 §1.1 | `xlat/prompts.py:75-244` 全件；装配序 header→task→C1-8→C8a→kind→C9→C10→glossary | ✅（C8a 反熔合为 B4a 实证扩条，已注记；`PROMPT_VERSION=xlat-prompt-v3` 失效纪律在） |
| C9 占位符条款逐字、末位 | §1.1 | `prompts.py:176-182` 末位 ✓ | ⚠️ 勘误级：列举多 `[[SP]]`（E21/E22 后加 token），spec 成稿未追记 |
| C10 人名条款仅 para/abstract | §1.1 | `prompts.py:185-188,240-241` | ✅ |
| corrector 三段式 + 温 0.2 | §1.2 | `prompts.py:249-273` + `pipeline.py:538-546` | ⚠️ 偏离：spec「上限 3 轮」未按文实现——corrector 只在阶梯 stage-1 调一次，三振语义由阶梯兜底（§1.6 与 §1.2 自相张力，impl 取 §1.6） |
| 分桶 <300 / 装箱 ≤2000 / `[n]`+`@@` / 退单翻 / 超大切分 | §1.3 | `batch.py:22-28,34-107` 全合；行首锚定 regex 优先是合理强化 | ✅ |
| 纯占位符 chunk 直落盘 | §1.3 | `placeholders.py:38-40,90-92` + `pipeline.py:904` | ✅（PURE_PH_RX 容许多 ph 空白分隔，超集语义） |
| `\n`→`[[SL]]` 编码 | §1.3 | `placeholders.py:99-149` | ⚠️ spec 称 `[[PL]]` 不需要；impl 用作 `\n\n+` 防御编码 + `[[SP]]` 保护 `\ `（皆注记） |
| 三级+ph 恒等+doc 过滤+整表烤进 | §1.4 | `glossary.py:64-131` 五层 setdefault 先写胜；`_TERM_BOUNDARY` IGNORECASE\|ASCII ✓；稳定排序 real(en.lower)+ph(sort_key) ✓ | ✅ worker 全接线（`worker.py:1884-1887,3713-3744`）；**e2e/export 路径见未落地清单** |
| `glossary.local.yaml` 论文级 | §1.4 | `worker.py:3696-3704` | ⚠️ 路径偏离：spec `output/{paper}/` → impl `<task>/base/`（随源树走，注释自认刻意） |
| `term_dict.json` 产物落盘 | §1.4 | `state.py:160,295-308` 有机制 | ❌ **未接线**：`save_maps` 全仓仅 tests 调用 |
| 运行时术语自增（可选默认关） | §1.4 | 无此功能 | ✅ spec 可选项，缺席合规 |
| 种子六表 + index.yaml | §1.4 | `xlat/terms/` 6 文件，default=404 行 ✓ | ✅ |
| env 黑白名单 + 未知→judge | §1.5 | 名单在 `latex/tables.py`（MATH/VERBATIM/PROTECTED/ARG_TRANSPARENT）；judge `prompts.py:278-353` + `e2e.py:130-183` + `worker.py:2439-2502` | ⚠️ 偏离：judge **默认关**（`TEXLATE_ENV_JUDGE`/options.env_judge opt-in），spec 写成未知 env 标准机制；且判 False 语义为「摘除译文回原文」非字面 `[[ENV_n]]`（等价降级） |
| judge 参数 0 温/16tok/3 试/小写 false/余 True/判 content/6 few-shot | §1.5 | `prompts.py:336-353` + `e2e.py:137-149` | ✅（温度 0.01 非 0——网关 502 实测注记） |
| 段内可译规则：无拉丁跳过/全大写跳过/纯 ph 跳过 | §1.5 | 仅纯 ph 跳过（`pipeline.py:904`） | ❌ 三缺二，前两条无任何实现 |
| 宏透明性 v0 不做 | §1.5 | — | ✅ |
| Semaphore(10) 并发 + 首发单飞暖缓存 | §1.6 | `pipeline.py:64,1007-1040` worker-pool 等价形态 + warmup 单飞 | ⚠️ `PipelineConfig` 默认 10 合 spec；**worker 生产默认 `options.concurrency or 3`**（`worker.py:1881`，网关硬闸 4 刻意值），spec 未追记 |
| 退避 `2^att`/429 `3^att` 底 5s/timeout 底 10s/Retry-After/body retry_after 勘误 | §1.6 | `retry.py:57-128` + `client.py:162-205` 解析序 body→header | ✅ 全合含 B4a 勘误落地 |
| 3~5 试、失败回退原文+skipped+reason | §1.6 | `RetryPolicy.max_tries=5`；`pipeline.py:740-755` | ✅ |
| 阶梯：整段×2→行级→slots(⟪S0000⟫/json_object/8 槽/失败重问)→fallback_orig+warn | §1.6 | `retry.py:42-50,256-420` 四段全件 | ✅ |
| `recover_copied_tokens` exact+unique | §1.6 | `placeholders.py:229-245` + 长 fragment 先认领强化 | ✅ |
| HTTP 状态码表 + `finish_reason=length` + `redact()` | §1.6 | `client.py:180-205,334-350,448-467` | ⚠️ spec「408/409/425/429/5xx 重试 ≤2」vs impl 该族吃满 policy=5（spec 同条内又写 3~5 试，自相矛盾；仅 EmptyContent/LengthTruncated cap=2） |
| state.json 逐块原子 `{version,meta,completed,results,errors_report}` | §1.6 | `state.py:237-291` | ✅（server 路径走 `DBStateBridge` chunks 表同语义，`worker.py:615-660`） |
| 中间产物五表（chunks_map/placeholders_map/glossary/state/errors_report），重建器只读 map | §1.6 | 机制在 `state.py:295-308` | ❌ **三表全死**：`save_maps` 无生产/bench 调用方；重建器读内存 scans/DB，不读 map 文件 |
| 段级键 `sha256(source+role+失效tag+masked快照)` | §1.6 | `state.py:62-80` + `pipeline.py:476-482` | ⚠️ `invalidation_tags` 形参存在但**无调用方传值**——accent/声明/数量级检测器不存在，该臂未接线 |
| 文件级键 `sha256(prompt_ver+base_url+model+lang+glossary+context)`→`cache-{16h}.json` | §1.6 | `state.py:83-106` 仅 tests 调用 | ⚠️ 生产用 `SegmentCache` 前缀 `sha256(model\|prompt_ver\|lang\|glossary\|l:local_sig\|c:cats)`（`worker.py:3765-3773`）——**无 base_url**（换网关不失效缓存）、无 context，但扩了 local_sig/cats |
| `atomic_json` tmp+rename+0600；缓存逐条再校验+损坏隔离 | §1.6 | `state.py:38-52,109-123` | ✅ |
| 默认后端 127.0.0.1:3003 + swe-2-medium；备选 high；max 留修复器；禁 swe-1-7* | §1.7 | `settings.py:40-41` `100.105.212.52:3003`+swe-2-medium；`client.py:51-53` | ⚠️ 多处偏离见清单 |
| 免费集运行时动态筛（panel free∩v1∩探活） | §1.7 | `client.py:718-786` 全件 | ❌ **无生产调用方**（docstring 自认）——生产走静态配置模型 |
| BYOK `provider_for_url` host→provider | §1.7 | `client.py:282-303` + `PROVIDER_KEY_ENV` | ✅ |
| 前缀缓存 Anthropic `cache_control` | §1.4 括注 | `_anthropic_body` 无 cache_control 字段（`client.py:477-499`） | ⚠️ anthropic 方言丢该优化（默认链路 OpenAI 方言不受影响） |
| L2 回灌：不过→带错误描述重译→再不过→fallback 原文 | §2.3 | `pipeline.py:611-666`（`[compile_error]` 反馈字段）+ `e2e.py:560-596` + `worker.py:2866-2931` | ✅ 链完整 |
| §6 块态 ok/fault/skipped | §6 | `pipeline.py:105` 实际四值 +`partial`（ladder recovered） | ⚠️ spec 表滞后；且 §1.6「fallback_orig→partial 终态」impl 块级落 `fault`+`skipped`，partial 只出现在论文级 |

## 二、未落地清单（按严重度）

1. **五表中的三表全死**（高）：`StateStore.save_maps` 全仓唯一调用方是 `tests/test_xlat_state.py:88`——`chunks_map.json`/`placeholders_map.json`/`term_dict.json` 永不落盘，§1.4 term_dict.json 产物与 §1.6「重建器只读 map 表」链路在生产和 bench 都不存在。要么接线（worker/e2e 物化期写三表），要么 spec 删这条承诺。
2. **免费集动态发现链无生产接线**（高）：`discover_free_models`/`probe_model`/`pick_model`（`client.py:679-786`）仅 bench/test 消费；§1.7 把动态筛写成选路机制，生产实为静态 `ctx.secrets.model or "swe-2-medium"` + `options.retry_model` 的 `_FallbackTranslator`（`worker.py:664-718`）。模型自动降级臂不存在。
3. **env_text kind 全链死路**（中）：v1/v2 scanner 均不发 `context="env_text"`（只发 para/item/chunk-arg 名），§1.5「判 True→env_text chunk 送翻」的增译路径不存在；judge 只做 revert。`table_text` 同死但 spec 自认「v0 不翻表格」合规。
4. **env_judge 默认关**（中）：spec §1.5 写成未知 env 标准判定机制；impl opt-in（`TEXLATE_ENV_JUDGE` 默认关 + `options.env_judge`），默认语义=未知顶层 env 一律翻（fail-open 全开而非先判）。
5. **`invalidation_tags` 缓存失效臂未接线**（中）：`segment_key` 支持但 `pipeline.py:476-482` 不传——spec 要求的 accent/声明/数量级失效检测不存在。
6. **段内可译规则三缺二**（低-中）：无拉丁字母跳过、全大写跳过未实现（仅纯 ph 跳过）。
7. **file_cache_key spec 公式生产不用**（低）：worker 前缀缺 `base_url` 成分——换 gateway endpoint 不失效段缓存（同 model 名不同上游可能产不同译文）。
8. **fixloop 修复器模型与 spec 不符**（低）：`fixloop/llm_hook.py:48` DEFAULT_MODEL=`swe-2-medium`，spec 定案 `swe-2-max` 留修复器；且 `DEFAULT_MODEL_PREFERENCE` 第 3 位是 swe-2-max——medium/high 全挂时修复器专机会被拿去跑翻译。
9. **Anthropic `cache_control` 未设**（低）：§1.4 前缀缓存机制在 anthropic 方言缺字段，BYOK-anthropic 丢缓存命中。
10. **e2e `_translate_tree` 裸 pipeline**（低）：`e2e.py:215-218` 不挂 glossary/state/cache——文件模式链无 ph 恒等注入、无断点、无段缓存；export 路径 `common.py:135-140` 有 glossary 但 `placeholders=` 恒空（ph 恒等注入缺席，export 侧 ph 域不同、影响待估）。

## 三、勘误级（规格文本本身滞后）

- §1.1 C9 成稿列举缺 `[[SP]]`（post-spec 新 token，`placeholders.py:62`）；§1.3「`[[PL]]` 不需要」与 impl 防御编码事实不符。
- §1.7 默认后端 `127.0.0.1:3003` → 现网 tailscale `100.105.212.52:3003`（`settings.py:40`、`cli.py:672` 同款）。
- §1.7 `swe-1-7*` 通配 → impl 精确两枚 `{"swe-1-7","swe-1-7-medium"}`（`client.py:53`，新 swe-1-7-* 变体可逃逸）；付费对照 `glm-5-3-low` vs 偏好表 `glm-5-2`。
- §6 块态枚举缺 `partial`；「fallback_orig→partial 终态」措辞与 impl 块级 `fault` 不符（论文级才对）。
- docs/06:148 产物清单 `chunks.jsonl`/`glossary.json` 与 §1.4/§1.6 `term_dict.json`/五表命名不一（跨文档，顺带提）。

## 四、合规确认（抽查无 drift）

prompt C1–C8 逐字/组装公式/C10 位置；批量 300/2000/`[n]`/`@@`/退单翻/6000 硬切；阶梯四段+⟪S0000⟫+8 槽+失败重问+`response_format`；退避全参数+B4a body retry_after 勘误；术语五层 setdefault+doc_filter 正则+稳定排序；state.json schema+0600 atomic+缓存隔离；HTTP 分类表+redact+length 截断；BYOK provider 表；L0 七规则（含 cs_dropped 升硬判据）；L2 重译→fallback 链；首发单飞暖缓存；recover_copied_tokens exact+unique；`validate_pair` 经 `validator` 缝全量接入主链（`worker.py:1889`）。

## leader 备注

pipeline.py 归 项目体验方式、e2e.py 归 1d——对账清单已按归属转发。建议优先级：#1 五表死链与 #2 免费集未接线是两条「规格承诺存在但物证为零」的项（同 SLOT_MAX_CHARS 先例同类）；#3-#5 为半接线项；其余文档追记即可。
