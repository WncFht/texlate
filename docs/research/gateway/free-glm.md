# gateway-3003 免费模型横评（en→zh LaTeX 段落翻译）

> **⚠️ SUPERSEDED 2026-09-17**：免费默认推荐已改判 `swe-2-medium`（唯一 100% 硬契约，promo 至 2026-10-16）。现状唯一事实源 = [`free-model-ranking.md`](free-model-ranking.md)；本文仅留 glm 族契约/延迟实测作历史参考，勿再据此派工。

日期：2026-09-14。探针 `tmp/exp/gwbench/gateway_xlat_glm.py`（串行、≥1s 间隔、timeout 180s、temp 0.2、max_tokens 8192），原始数据 `tmp/exp/gwbench/gateway_xlat_glm.json`（含全部译文全文/usage/reasoning 长度）。样例与前测逐字节一致（A/B/C = 1706.03762 chunk #15/#21/#58，D = 手写压力样例），评测方法同 `gateway-3003-xlat.md`。

## TL;DR

**免费档默认推荐 `glm-5-3-low`**：4/4 契约全保、无 reasoning 开销、平均 ~1.2s/chunk（sonnet-5-medium 的 1/3）、out 仅 108–170 tok（sonnet 的 ~60%），且保住了连 sonnet 都丢的 `\` 控制空格。备选 `glm-5-3-high`（同速，爱加英文括注）或 `glm-5-2-none`（1.2–2.4s，同样无推理）。

- **契约存活 39/39**（GLM 8 模型 ×4 样例 = 32/32；顺带探测 7 模型 ×D = 7/7），占位符 0 丢失 0 幻觉，HTTP 错误 0。唯一 warn：glm-5-2 在 B 的长度比 0.30 压线（与 sonnet 前测同一位置，已判误报）。
- **15/15 模型全部可用**——前测的 OpenAI 502 / `glm-5-3-medium` 400 未复现（清单里确实没有 glm-5-3-medium，本次未再试）。
- **延迟排序**（4 样例均值）：glm-5-3-low ≈ glm-5-3-high (~1.2s) < glm-5-2-none (1.6s) < glm-5-3-flash-low (2.4s) < glm-5-2 (3.9s) < glm-5-3-max (4.6s) < glm-5-3-flash-max (7.6s) < glm-5-2-max (9.5s)。reasoning 档位名不虚传：后缀 `-max`/无后缀的 5-2 都在思考，`-none`/`-low`/`flash-low`/`5-3-high` 基本不思考。
- **顺带探测**：kimi-k3-low (2.5s)、deepseek-v4-flash-high (2.7s)、nemotron-3-ultra-none (4.4s)、inkling-low (3.7s) 可用且 D 全保；kimi-k2-6 一条 D 思考了 9657 字符 / 41s，直接出局；grok-4-5-low 9.3s 偏慢但契约干净。

## GLM 全档矩阵（4 样例 × 8 模型）

| 模型              | A         | B           | C         | D          | validator | reasoning            | out tok 区间 | 延迟区间  |
| ----------------- | --------- | ----------- | --------- | ---------- | --------- | -------------------- | ------------ | --------- |
| glm-5-2           | PASS 5.9s | PASS⚠1 4.6s | PASS 2.0s | PASS 3.4s  | 4/4       | 全部 (290–2387 字符) | 333–934      | 2.0–5.9s  |
| glm-5-2-none      | PASS 1.2s | PASS 1.4s   | PASS 2.4s | PASS 1.6s  | 4/4       | 无                   | 109–169      | 1.2–2.4s  |
| glm-5-2-max       | PASS 7.6s | PASS 8.8s   | PASS 8.4s | PASS 13.3s | 4/4       | 全部 (3492–5398)     | 1266–2046    | 7.6–13.3s |
| glm-5-3-low       | PASS 1.0s | PASS 1.3s   | PASS 1.5s | PASS 1.0s  | 4/4       | 无                   | 108–170      | 1.0–1.5s  |
| glm-5-3-high      | PASS 1.1s | PASS 1.4s   | PASS 1.5s | PASS 1.0s  | 4/4       | 仅 D 有 63 字符      | 118–184      | 1.0–1.5s  |
| glm-5-3-max       | PASS 2.9s | PASS 3.1s   | PASS 7.5s | PASS 5.2s  | 4/4       | 全部 (1561–3897)     | 713–1522     | 2.9–7.5s  |
| glm-5-3-flash-low | PASS 1.6s | PASS 1.6s   | PASS 5.3s | PASS 1.2s  | 4/4       | 无                   | 107–173      | 1.2–5.3s  |
| glm-5-3-flash-max | PASS 6.2s | PASS 6.1s   | PASS 7.5s | PASS 10.5s | 4/4       | 全部 (1708–3755)     | 778–1320     | 6.1–10.5s |

唯一 warn = glm-5-2 / B：`length 长度比 0.30 超出 [0.3,2.5]`（zh=210/src=706，与 sonnet 前测同点位同数值——再次印证下界该放宽到 ~0.25）。

## 顺带探测矩阵（ping + D）

| 模型                     | ping "Say OK"                                           | D 样例              | validator | 备注                                   |
| ------------------------ | ------------------------------------------------------- | ------------------- | --------- | -------------------------------------- |
| kimi-k2-6                | 200 5.2s "OK"                                           | PASS 41.4s out=2828 | PASS      | reasoning 9657 字符，慢到不可用        |
| kimi-k3-low              | 200 1.2s "OK"                                           | PASS 2.5s out=126   | PASS      | reasoning 仅 46 字符，快且干净         |
| deepseek-v4-flash-high   | 200 1.0s "OK"                                           | PASS 2.7s out=369   | PASS      | reasoning 1308 字符                    |
| deepseek-v4-1-flash-high | 200 3.2s "OK"                                           | PASS 10.6s out=1339 | PASS      | reasoning 4087 字符                    |
| nemotron-3-ultra-none    | 200 0.8s "OK"                                           | PASS 4.4s out=128   | PASS      | 无 reasoning                           |
| inkling-low              | 200 4.5s "OK! How can I help you with your code today?" | PASS 3.7s out=591   | PASS      | 代码向模型口吻                         |
| grok-4-5-low             | 200 1.4s "OK"                                           | PASS 9.3s out=102   | PASS      | 保 "et al." 不译；有 cached_tokens=128 |

## 每模型一句话点评

- **glm-5-3-low**：速度/成本/契约三赢，译文干净无包装无括注，D 里 `\` 与 `\href` 全保——**免费档首选**。
- **glm-5-3-high**：同速，但爱加「空洞卷积（dilated convolutions）」式英文括注——对双语对照阅读可能是加分也可能是噪音，按需选。
- **glm-5-2-none**：5-2 系的无推理档，干净稳定，比 5-3-low 略慢一点点。
- **glm-5-3-flash-low**：low 档同档速度（C 样例偶发 5.3s 慢抖），质量持平。
- **glm-5-2**：带推理，质量无可见提升却多烧 3–9 倍 out token；D 里把 `\` 改成普通空格（validator 盲区，人工发现）。
- **glm-5-3-max**：推理开销中等（out 713–1522），译文与 low 档难分高下——翻译任务用不上推理。
- **glm-5-3-flash-max**：比 5-3-max 更慢更贵，无质量差。
- **glm-5-2-max**：最慢档（7.6–13.3s），reasoning 最长 5398 字符，纯浪费。
- **kimi-k3-low**：顺带探测里最有价值的——2.5s、契约全保（含 `\`），可作 GLM 之外的第二来源。
- **deepseek-v4-flash-high**：2.7s 可用，但译文排版紧凑（`Vaswani等人`、占位符前后不留空），双语对照渲染时空白处理要注意。
- **deepseek-v4-1-flash-high**：同上但 10.6s + 4k 字符推理，不如 v4-flash。
- **nemotron-3-ultra-none**：无推理 4.4s，丢了 `\`，行文略简（"即可"），可用但无优势。
- **inkling-low**：ping 自述是代码助手，3.7s 契约全保但丢 `\`，观察名单。
- **kimi-k2-6**：单条 D 思考 9657 字符 / 41s——批量管线直接出局。
- **grok-4-5-low**：9.3s 偏慢；有趣点是保 `\` 且留 "et al." 不译（更接近原文排印，见仁见智）。

## 与前测 sonnet-5-medium 对比

| 维度                      | glm-5-3-low（本次推荐） | claude-sonnet-5-medium（前测推荐）    |
| ------------------------- | ----------------------- | ------------------------------------- |
| validator                 | 4/4 PASS 0 warn         | 4/4 PASS（B 有同一 length 压线 warn） |
| 延迟                      | 1.0–1.5s                | 3.0–4.2s                              |
| out tokens                | 108–170                 | 170–277                               |
| in tokens（同 4 样例）    | 162–234                 | 259–359                               |
| reasoning                 | 无                      | 无                                    |
| `\` 控制空格（D，人工查） | **保住**                | 丢失                                  |
| 输出风格                  | 纯译文零包装            | 纯译文零包装                          |

glm-5-3-low 在延迟、token 成本、`\` 保留三项全面优于 sonnet-5-medium；译文质量目测同档（术语准确、"空洞卷积/逐位置前馈层" 译法规范）。**且免费**。sonnet 的唯一剩余优势是 anthropic 上游的行为可预期性。

按 146 chunks/篇估算：glm-5-3-low 串行 ~3 分钟/篇（sonnet ~9 分钟），in ~2.7 万 + out ~2 万 tokens——若按量计费也是最低档。

## 发现与坑

1. **档位后缀 = reasoning 开关**：`-none`/`-low`/`5-3-high`/`flash-low` 不思考或极短思考；无后缀与 `-max` 全量推理。glm-5-3-high 仅 D 有 63 字符 reasoning——high 档对短输入才偶尔思考。
2. **`\` 保留是 validator 盲区**（macro 规则只查 zh 新增命令）：本次人工核 D——保 `\`：glm-5-2-none/5-2-max/5-3 全系/flash 全系/kimi-k3-low/deepseek×2/grok；丢 `\`：glm-5-2/kimi-k2-6/nemotron/inkling（前测 sonnet 也丢）。要进契约得加专门规则。
3. **in-token 因上游而异**：同 4 样例 GLM 计 156–234、sonnet 前测 259–359、各 side 模型 ping 381–580——网关按 provider 注入不同量的隐藏提示，GLM 线路开销最小。
4. **本次 0 个 HTTP 错误**——前测 OpenAI 502、`glm-5-3-medium` 400 说明"清单存在≠可用"仍成立（glm-5-3-medium 不在清单里，本次未试）；glm-5-3-max 前测的 cached_tokens=320 本次未复现（GLM 全部 cached=0，仅 grok 有 128）。
5. max_tokens=8192 全程未触发 length 截断（最长 out 2828 = kimi-k2-6），无需重试。
