# 翻译模型选型实证：占位符契约驱动的横评

> **结论**：在内部 OpenAI 兼容网关可路由的模型面中，`swe-2-medium` 以 100% 硬契约存活率、全场最低推理开销与可接受延迟成为翻译管线默认模型；排序由「占位符/脆弱命令契约存活」一票否决制驱动，而非译文主观质量或榜单跑分。
> **状态**：现行（数据口径 2026-09-14 – 2026-09-17；免费额度为促销制，供给面随时点变化，选型结论应周期性重测）
> **日期**：2026-09-20

## 1. 选型目标与负载特征

翻译管线的负载不是通用对话：每篇论文被半解析层切成 约 150–210 个文本块（chunk），块内数学式、引用、命令已替换为 `[[MATH_n]]` 等占位符；模型的任务是逐段英译中并逐字保留占位符，译文随后被 splice 回 LaTeX 重编译。因此一次契约失败不是「质量打折」，而是占位符对应内容静默消失、或脆弱命令与中文熔合成未定义控制序列直接编译爆炸——这决定了选型判据的优先级顺序。

硬约束（任一不满足即出局）：占位符零丢失、零新造；脆弱 LaTeX 命令（`\` 控制空格、`\,`、`~`）不丢失、不与中文字符熔合；输出为纯译文、无包装。软目标（排序用）：延迟（串行管线的单篇吞吐 ≈ 延迟 p50 × 块数）、输出 token 成本、行为方差（reasoning 长度失控的模型无法预算）。

## 2. 评测方法

### 2.1 契约校验器

规则校验器逐对比较源文与译文：占位符集合与多重集相等、无新造占位符、无新增控制序列、译文/源文长度比在界内；其上叠加三条增强判据——`ph_order`（占位符序列逐一相等）、`cs_dropped`（脆弱命令 src→zh 计数差）、`en_residue`（译文残留英文词计数，粗质量信号）。

### 2.2 样例集

两阶段推进：4 样例冒烟（3 个真实论文块 + 1 个手写压力样例，覆盖行首 BIBITEM 占位符、`\href`、`\` 控制空格、多 key 引用、verbatim `%`）→ 40 样例 ×2 轮主评测（6 篇横跨 article/IEEEtran/elsarticle/amsart 等文档类与不同学科的论文各取 6 块，外加 4 个合成压力样例；样例故意不均匀，含单段 19 个占位符的高密度段）。个别慢模型（swe-2-max、swe-1-7）减量到 14/28 样例 ×1 轮——样本量不对称，比较「率」时需注意。

### 2.3 指标优先级

- L1 硬契约率（一票否决）：无丢占位符 ∧ 无造占位符 ∧ 无丢脆弱命令 ∧ 校验器无 error。差 5% 就是合格线内外之别。
- L2 `ph_order` 软信号：严格序守恒对中译英过严——实测违例约 95% 是合法中文重构（`of X`→`X 的`、状语前置），降级为观察项；唯「结构性占位符脱离其文本位」（如 BIBITEM 掉到条目文本后）仍为真伤。
- L3 延迟 p50/p95 与 reasoning 开销：p50 决定吞吐，p95 暴露尾部风险；`reasoning_content` 长度是白烧 token 与延迟的直接来源。
- L4 token 经济：out_tok 中位数（reasoning 计入账单的直接代理）；in_tok 中位数反映网关按上游 lane 注入的固定提示开销。

### 2.4 请求协议

`POST /v1/chat/completions`（OpenAI 兼容面），`temperature=0.2`，`max_tokens=8192`（length 截断自动放大重试），串行、≥1s 间隔。原始调用记录（含全部 src/zh 与 usage）留存于开发机评测工作区，本文为摘要口径。

### 2.5 评测期沉淀的校验器修订

`ph_order` 从硬判据降为软信号；`cs_dropped` 升为硬判据（它是抓到全部 `\和` 熔合编译炸弹的唯一判据）；长度比下界 0.3→0.25（中文密度天然压线，`zh/src ≈ 0.30` 两次实测均为误报）；占位符跨段迁移（chunk 边界处结构占位符被挪出条目区）尚无专项检测；译文质量层（术语一致性、学术腔）仍需人工盲评兜底。

## 3. 模型横评结论

### 3.1 端点面与模型目录

内部网关对外暴露 OpenAI 兼容面：chat/completions 为主用协议，同一模型另经 OpenAI Responses 与 Anthropic Messages 两协议可用（thinking 分别以 `reasoning_content`、thinking block/加密思考块形式透出）。模型目录 200+ 个，按上游厂商分族（anthropic/openai/google/zai/moonshot/xai/deepseek/windsurf/nvidia/machines）。

**目录存在 ≠ 可调通**：实测清单内模型有 502（上游流异常终止）与 400 permission_denied（未授权）案例，错误模型名报 400 而非 model_not_found——候选模型必须先过小样实测再进管线。reasoning 模型的 `max_tokens` 预算含思考链，过小会得到 `content:""` + `finish_reason:"length"`。

### 3.2 主横评总表（40 样例 ×2 轮，免费档 6 模型）

| model            | n   | 硬契约        | ord 软信号 | ph_miss | cs_drop | 延迟 p50/p95 | rsn p50/p95 (字符) | out_tok 中位 |
| ---------------- | --- | ------------- | ---------- | ------- | ------- | ------------ | ------------------ | ------------ |
| **swe-2-medium** | 80  | **80 (100%)** | 19         | 0       | 0       | 5.9/14.6s    | **98/144**         | **134**      |
| swe-2-high       | 80  | 79 (99%)      | 17         | 0       | 0       | 10.1/19.5s   | 442/1118           | 416          |
| swe-1-7          | 28  | 27 (96%)      | 6          | 0       | 1       | 4.0/20.2s    | 2486/**22050**     | 806          |
| swe-1-7-medium   | 80  | 77 (96%)      | 16         | 0       | 2       | **2.9**/8.7s | 1811/6263          | 650          |
| swe-2-max        | 14  | 13 (93%)      | 2          | 0       | 1       | 10.4/29.7s   | 600/1574           | 561          |
| glm-5-2          | 80  | 73 (91%)      | 18         | **9**   | **6**   | 4.1/9.4s     | 1703/3596          | 710          |

（`ord` 列 = 硬契约通过但占位符换序的计数，以合法中文重构为主；HTTP 错误 0、空输出 0。）

### 3.3 失败模式归因

- **glm-5-2**：免费集垫底（91%）且失败模式最恶性——单点连吞 9 个 MATH 占位符与 `(i)/(ii)` 引用（译文出现「是 的一个特例」式空洞，属静默大段丢失）；压力样例两轮丢 `\` 控制空格。
- **swe-2-max**：把 `\` 控制空格与后随中文字符熔成 `\和`/`\道`（未定义控制序列，重编译必炸）——更深的思考产出更「中文」的句式，反而撞上更恶性的错误形态。
- **swe-1-7-medium / swe-1-6-fast**：各丢一次行首 `[[BIBITEM_1]]`——低思考变体在「占位符紧贴句首人名」场景的确定性翻车模式。
- **swe-1-7**：契约 96% 不算差，但 reasoning 方差失控（单点 120k 字符/125s，p95 22k 字符），批量管线无法预算。
- **swe-2-medium**：19 次 ord 软信号经抽查全为合法换序——失败集里没有一个真伤。

### 3.4 横向发现

1. **档位后缀 = reasoning 开关**：`-none`/`-low`/`flash-low`/`5-3-high` 不思考或极短思考；无后缀与 `-max` 全量推理。**模型名后缀是出厂固定的 effort 档，比运行时参数可靠**——swe-1-7 裸档 reasoning 长度在 12k–120k 字符间剧烈波动，其后缀变体则稳定。
2. **运行时推理参数大多静默透传**：`reasoning_effort`、`thinking:{type:disabled}`、`reasoning:{effort:*}` 等字段全部 HTTP 200 原样返回、无校验报错，是否生效只能靠效果反推；唯一稳定观测到效果的是 swe-1-7 上 `reasoning_effort:"none"`（压到约 3.5k 字符，仍不能全关）。想零思考直接用 `-none`/`-lightning` 后缀档。
3. **固定注入开销按上游 lane 分档**：同一最小请求在不同 provider 线路的 in_tok 从约 156 到约 570 不等——网关为上游代理框架注入的隐藏系统提示量不同，成本要按 lane 分开估。
4. **思考深度 ≠ 契约收益**：swe-2-max 的 rsn 中位 600 字符（medium 的约 6 倍）、延迟约 1.6 倍，没有换来任何可观测的契约或质量收益，反添 `\和` 熔合事故；思考投入流向句式重构而非占位符保护。
5. **「清单存在 ≠ 可用」是长期事实**：横评窗口内 OpenAI 系模型全部 502、个别 GLM 档位 400，次日又全部恢复——供给面按小时级波动，运行手册必须带探活与降级。

### 3.5 质量面印象（人工抽查，非判据）

硬契约全保的前提下，各候选译文质量同档：swe-2-medium 行文最贴付费对照组且行为方差最小；claude-sonnet-5-medium 输出最干净但会丢 `\` 控制空格（校验盲区，人工发现）；glm-5-3-low 保住了 sonnet 都丢的 `\`；glm-5-3-high 爱加英文括注（对双语对照可正可负）；deepseek 系译文排版偏紧凑、占位符前后不留空白；grok-4-5-low 保留 "et al." 原文。质量差异在契约全绿时不足以翻盘排序。

## 4. 延迟与成本模型

### 4.1 单请求成本结构

每请求 token = **固定注入开销**（上游代理框架系统提示，按 provider lane 约 160–570 in-tok）+ 业务 prompt + 输出。reasoning 模型的 out token 含思考链：swe-2-max 单段翻译 out 491–1034 tok（大头是 580–1066 字符 reasoning），swe-2-medium 恒定约 100 字符「思考地板」。**思考开销是延迟与账单的第一驱动**——延迟近似呈「固定开销 + out_tok × 系数」形态：同模型延迟随 out_tok 线性上升，输入长度变化对延迟几乎无影响（4 样例 in 差近 2 倍延迟不变，rsn 差 10 倍延迟差约 10 倍）。成本与延迟优化因此同构：砍思考。

### 4.2 分块统计与单篇 token（39 篇语料口径）

全语料 chunk 总数 17,268、源文 5.32M 字符，其中占位符字面量占 17.8%（MATH 占全部占位符约 70%）。典型期刊论文 p50 ≈ 210 chunk / 7.5 万字符（讲义/书级语料拉高均值，看 p50 不看 mean）。按批处理协议（<300 字符 chunk 顺序贪心入批、≤2000 字符/批，≥300 单发；每请求 400 tok 开销摊销模型）估算：**每篇 total token p50 ≈ 9.1 万**，与「幻觉翻译」约 10 万 token/篇的公开锚点基本重合[^hjfy]。

关键结构：开销摊销占输入 token 的 68%——≥300 字符的 chunk 只占 34%，却贡献 89% 的请求数，每发都背固定开销。**批阈值是成本的最大杠杆**：评测时按全量入批 ≤8000 字符/批估算可把每篇 total p50 再降约 40% 至 5.4 万、请求数降一个量级（6,632→685）——该杠杆已由产线落地（见下注记）。

> 注记（2026-09-21）：批协议已于 2026-09-18 重构（`73ffa4c`）——取消 short/long 分桶改全量入批，`BATCH_MAX_CHARS=12000` / `BATCH_MAX_ITEMS=32` / `BATCH_MIN_CHARS=2500`（`src/texlate/xlat/batch.py`，K 量化等大装箱）。本节「<300 字符 chunk 顺序贪心入批、≤2000 字符/批、≥300 单发」为评测期协议口径；§4.3/§4.4 的成本与延迟数系旧协议上界。

### 4.3 BYOK 单篇成本（2026-09 时点刊例价）

| 模型档      | 单价 in/out (per M tok) |   每篇 p50 | 每篇 mean | 万篇（按 mean） |
| ----------- | ----------------------- | ---------: | --------: | --------------: |
| qwen-turbo  | ¥0.3 / ¥0.6             | **¥0.036** |    ¥0.065 |        **¥653** |
| deepseek-v3 | ¥1.0 / ¥2.0             |     ¥0.121 |    ¥0.218 |          ¥2,177 |
| gpt-4o-mini | $0.15 / $0.6            |     ¥0.195 |    ¥0.355 |          ¥3,551 |

刊例价见各厂定价页[^pricing]。「幻觉翻译」3 亿 token/万篇 ≈ ¥140 的口径隐含约 3 万计费 token/篇，比上述任何方案低约 3 倍——最可能解释是 prompt 缓存命中（本模型里占输入 68% 的开销项在缓存命中后趋零）与跳译非正文内容；追平路径 = 缓存复用 + 激进批处理 + 跳译策略，而非解析质量改进。

### 4.4 延迟预算

串行口径：swe-2-medium（p50 5.9s）翻约 146 chunk 论文 ≈ 14 分钟/篇；glm-5-3-low（约 1.2s）≈ 3 分钟；sonnet-5-medium（约 3.2s）≈ 9 分钟；swe-2-max 冒烟期单段 63–124s，串行约 3.7 小时，不可用作批量主力（其延迟在后续减量横评中回落到 med 10.4s，属档位间方差，仍显著高于 medium）。并发余量可线性摊薄吞吐问题，但尾部延迟（p95）决定整篇完成时间。

## 5. 供给面与降级链（2026-09 时点）

### 5.1 促销制免费集

内部网关目录中标注免费档的模型为限时促销（promo）制，到期日各异。运行期纪律：**不硬编码免费集**——客户端启动时拉取网关模型目录与成本档元数据、按促销有效性动态筛选、与可调清单求交并探活；任一模型促销到期自动降级到备选链。

### 5.2 公共免费额度类型学

对 BYOK 用户与自建部署，2026-09 时点存在四类免费供给（均为公开政策，额度随时点波动，以各官方页为准）：

- **官方免费档**（需一次性注册）：国内多家平台提供每日限量或限期额度——魔搭社区推理日配额[^ms]、智谱永久免费小模型档[^glm]、SiliconFlow 免费小模型集（含 Hunyuan-MT-7B 专用翻译模型）[^sf]、阿里百炼/火山/腾讯等新人额度包[^bailian]；海外有 Gemini Flash 免费档[^gemini]、Groq[^groq]、OpenRouter `:free` 变体[^or]、Cloudflare Workers AI[^cf]、NVIDIA NIM 试用[^nim]、Mistral 实验档[^mistral] 等。
- **聚合/公益站**：第三方转发站随时关停、改规则、限速不稳，数据经第三方——只当机会型补充，不进关键路径。
- **CLI 订阅转 API 生态**：把各类 CLI 助手订阅额度转成本地 OpenAI 兼容端点的开源工具（CLIProxyAPI、AIClient-2-API 等）[^cli2api]，需对应账号 OAuth；上游政策收紧频繁，注意清理已死上游配置。
- **本地自托管**：12GB 级显存可跑 14B 级量化指令模型（ollama/llama.cpp），质量低于旗舰 API 但零成本零依赖，是全部促销到期时的永久兜底臂。
- **已死面**（2026-09 核实）：GitHub Models 已整体退休、若干厂商 OAuth 免费层与公益站已关停——**免费面保鲜期按月计，凭据池需周期性重测**（一次内部盘点实测 80 条收录端点仅 2 条仍活）。
- **数据条款**：部分免费档默认允许拿 prompt 训练——翻译公开 arXiv 文本风险可控，管线应保留发送范围开关。

### 5.3 机会型臂纪律

匿名档/共享预算档实测不稳定（同一日内出现连续空响应与「预算耗尽」内联文案），只配作机会型臂：串行加间隔、失败自动降级、不进关键路径；已验证契约的免费源按可靠性排序进降级链，排序随测活结果滚动更新。

## 6. 共享容量的 fg/bg 分级准入（配套设计）

翻译批跑（单批可达数万请求）与交互式流量共用同一网关容量池。客户端侧自我节流（按剩余配额 − 外部需求预测让速）已验证有效但有三个结构性上限：双边礼让在窗口边界撞车（被拒请求也计上游额度）、空闲尾槽无人敢填（分钟桶配额不用即废）、网关眼里请求无类别（交互等待与无人值守批跑 FIFO 同权）。把调度下沉进网关的概念设计如下：

- **key→class 映射**：分类打在认证层，`fg`（默认）/`bg` 两类；存量 key 与未标 class 的全部按 fg 处理，行为与现状完全一致，零回归面。
- **闸内分级准入**：fg 语义不变；bg 准入加「fg 预留量」约束——`bucketUsed + 1 ≤ quota − reserve`，其中 `reserve = fg 准入速率 EMA × 本桶剩余秒数 + fg 排队数 + margin`（margin 默认约 4，可配）。动态 reserve 的副产品正好是 work-conserving 尾槽填充：窗口尾部 fg 不用的槽自动放给 bg，不需要单独收尾逻辑，不留静态死配额。
- **排队优先级**：容量释放先喂 fg 等待队列；bg 等待预估要把 fg 排队计入。
- **bg 的持有与快败语义**：bg 是无人值守负载、等得起——闸内排队上限放宽（建议默认 120s）；因预留不足被快败时 `Retry-After` 给到下个窗口的秒数，批跑客户端直接睡到开桶。
- **响应头遥测**：每个响应 piggyback `X-Gate-*` 头（服务 lane、class、窗口用量/配额、重置秒数、闸内等待、429 原因分类），批跑客户端从轮询管理面降级为纯被动调度：quota 型 429 睡满 `Retry-After`，成功响应实时校准余量模型。
- **明确不做**：周配额配速（免费 promo 无周限额概念）、lane 偏好/steering、按模型分类（class 跟 key 不跟 model）、任何向后不兼容。

验收口径的核心：fg 间歇负载下其闸内等待分布与无 bg 时统计不可区分；网关完全空闲时 bg 能把桶吃到 `quota − margin` 附近；fg 占满某 lane 时 bg 在该 lane 饿死但不产生上游拒绝计数。

## 7. 结论

选型结论表（2026-09-17 口径，促销到期后按链自动降级）：

| 定位         | 模型                                    | 依据                                                                                    |
| ------------ | --------------------------------------- | --------------------------------------------------------------------------------------- |
| **默认**     | `swe-2-medium`                          | 唯一 100% 硬契约（80/80）、rsn p50 98 字符思考地板、out 中位 134、5.9s/段、行为方差最小 |
| 质量升级档   | `swe-2-high`                            | 契约 99%、延迟 +70%、思考开销中等                                                       |
| 促销窗口快选 | `glm-5-2`                               | 契约 91%、有灾难性吞占位符史——仅窗口期内当速度档且必须配重试阶梯                        |
| 修复器专座   | `swe-2-max`                             | reasoning 最深，留给编译修复回路的 LLM 修复器兜底                                       |
| 禁用         | `swe-1-7-medium`、`swe-1-7`             | BIBITEM 契约事故史 / reasoning 爆炸不可预算                                             |
| BYOK 对照    | `glm-5-3-low`、`claude-sonnet-5-medium` | 付费侧质量/速度基准，不进默认链                                                         |

方法论沉淀（可泛化到其他「输出必须被程序消费」的 LLM 选型）：契约存活率优先于质量跑分与延迟；reasoning 开销是成本与延迟的第一驱动，「思考地板」型号是金矿；模型名后缀比运行时 effort 参数可靠；模型目录不等于可用面，探针先行、测活常态化。

### 参考文献

[^hjfy]: 幻觉翻译 hjfy.top 公开成本说明（约 10 万 token/篇、3 亿 token/万篇 ≈ ¥140 口径）. [hjfy.top](https://hjfy.top/)

[^pricing]: 各厂刊例价：阿里云百炼模型服务定价 [help.aliyun.com](https://help.aliyun.com/zh/model-studio/billing-for-model-studio)；DeepSeek API 定价 [api-docs.deepseek.com](https://api-docs.deepseek.com/quick_start/pricing)；OpenAI API 定价 [openai.com](https://openai.com/api/pricing/)

[^ms]: ModelScope 魔搭免费推理额度说明。[modelscope.cn](https://modelscope.cn/docs)；限额响应头参考实现 [github.com](https://github.com/Morningstars666/ModelScopeApiBalanceCheck)

[^glm]: 智谱 bigmodel 模型概览与速率限制。[docs.bigmodel.cn](https://docs.bigmodel.cn/cn/guide/start/model-overview)

[^sf]: SiliconFlow 免费层说明。[getmodelkey.com](https://www.getmodelkey.com/zh/guides/siliconflow-api-free-tier-2026/)

[^bailian]: 阿里云百炼新人免费额度及用完即停说明。[help.aliyun.com](https://help.aliyun.com/zh/model-studio/new-free-quota)

[^gemini]: Google. Gemini API rate limits. [ai.google.dev](https://ai.google.dev/gemini-api/docs/rate-limits)

[^groq]: Groq. Rate limits. [console.groq.com](https://console.groq.com/docs/rate-limits)

[^or]: OpenRouter. API limits 与 free 变体。[openrouter.ai](https://openrouter.ai/docs/guides/routing/model-variants/free)

[^cf]: Cloudflare. Workers AI pricing. [developers.cloudflare.com](https://developers.cloudflare.com/workers-ai/platform/pricing/)

[^nim]: NVIDIA. NIM build integrations. [build.nvidia.com](https://build.nvidia.com/settings/integrations)

[^mistral]: Mistral AI. Rate limits help. [help.mistral.ai](https://help.mistral.ai/en/articles/698531)

[^cli2api]: CLIProxyAPI [github.com/router-for-me/CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)；AIClient-2-API [github.com/justlovemaki/AIClient-2-API](https://github.com/justlovemaki/AIClient-2-API)
