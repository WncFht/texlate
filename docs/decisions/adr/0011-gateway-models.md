# ADR-0011 模型网关策略：BYOK 预设表 + 内部网关默认 + 免费集动态筛

> **状态**：现行
> **日期**：2026-09-15（05 裁决 11）| 更新 2026-09-19（网关事故应对、promo 死线排产）

## 上下文

texlate 走 BYOK——用户自带任意 OpenAI 兼容端点；但开发期/bench 需要一个默认后端。模型选择判据不是通用榜单：占位符契约存活率是一票否决项（契约失败 = 内容静默消失或 `\`+中文熔成未定义控制序列编译爆炸），其次才是延迟、token 成本、reasoning 开销方差。内部 OpenAI 兼容网关聚合 200+ 模型，但目录存在 ≠ 可调通（502/permission_denied 并存）。

## 裁决

- **BYOK 抽象**：`base_url + api_key + model` 三要素 + provider 预设表（hostname 识别端点特化）；OpenAI 兼容端点统一走 `openai` SDK，Anthropic 走 `anthropic` SDK；**不引 litellm**（多一层参数透传坑，babeldoc 实测 `temperature=0` 被网关 400）。协议方言 auto/openai/anthropic/responses 可选。
- **本地默认后端**：内部 OpenAI 兼容网关 + `swe-2-medium`（temp 0.2、max_tokens 留足）——免费档中大样本硬契约率 100%（80/80）、reasoning p50=98 字符全场地板、5.9s/chunk；备选 `swe-2-high`（99%）；`swe-2-max` 留 LLM 修复器位；`swe-1-7`/`swe-1-7-medium` 进 denylist（丢命令/BIBITEM 史 + reasoning 爆炸）。
- **免费集运行时动态筛**：promo 会到期、清单≠可用——启动拉网关面板模型表按 `cost_tier==free ∧ promo.active` 与 `/v1/models` 求交 + 探活白名单；preference 序 + denylist 双表驱动选模。
- **前缀缓存**：system prompt + 术语表 + 占位符契约放前缀并稳定排序（Anthropic `cache_control` 手动断点、OpenAI/DeepSeek 自动前缀缓存零代码、火山 Context API 预留）。
- **网关特性硬约束**：每请求 ~160–566 隐藏 prompt token 开销（网关注入系统提示，按型号分档、批内摊不掉——成本模型的请求摊销要上调）；reasoning 档的 effort 旋钮是模型名后缀而非参数，且 `reasoning_content` 吃 max_tokens 须给足。

## 理由

- E21 网关实测：三协议可用（chat/completions + responses + messages）、占位符契约 12/12 全绿（含 BIBITEM 前缀/`\href`/`\␣` 压力样例）。
- E22 大样本横评（338 调用）：硬契约率 swe-2-medium 100% > swe-2-high 99% > swe-1-7 系 96% > swe-2-max 93% > glm-5-2 91%；失败现场含 glm-5-2 连吞 9 个 MATH、swe-2-max `\`+中文熔合。
- 证据：调研档案 `research/model-selection.md`（横评方法论与排序管线）；主仓 `docs/05` E20/E21/E22。

## 演变

- 2026-09-14→15：默认模型从 `claude-sonnet-5-medium`（E21 小样本首选）改判 `swe-2-medium`（E22 大样本免费档 100% 契约）；sonnet 转付费对照位（同 glm-5-3-low）。
- `swe-2-medium` promo 2026-10-16 到期——免费额度内 real 臂吞吐 ~40–72 格/h；裁决为滚动探针排产（每波分层 200–300 格优先打 hot/expand 缺口）而非全量回归（real≈mock 已实证，mock 全量 + real 探针即可）。
- 2026-09-19：网关非流式 POST 一度全模型 502（stream 正常）——管线走流式桥接应对，probe 探活也须在桥内做；教训是「网关面即单点」，免费集动态筛与备胎模型的价值实锤。

## 现状

实现落在 `xlat/client.py`：`DEFAULT_MODEL_PREFERENCE = (swe-2-medium, swe-2-high, swe-2-max, glm-5-2)`、`DEFAULT_MODEL_DENYLIST = {swe-1-7, swe-1-7-medium}`、面板表 `/v1/models` 求交 + 探活白名单、`API_DIALECTS` 四方言；`server/providers.py` 持 BYOK 预设目录（deepseek/openai/anthropic/dashscope/custom）与 `/v1/models` 探活。默认 base_url 预置内部网关地址——对外发布形态的中性默认值是已登记待办（见 roadmap 决策点）。
