# gateway-3003 翻译后端实测（en→zh 段落级）

日期：2026-09-14。探针脚本 `tmp/exp/gwbench/gateway_xlat_probe.py`，原始数据 `tmp/exp/gwbench/gateway_xlat_results.json`（含全部 src/zh 全文与 usage）。

## 结论

**能用，且占位符契约全绿：3 个可用模型 × 4 样例 = 12/12 validator PASS，占位符 0 丢失 0 幻觉。** 但首选不是任务指定的 swe-2-max——它契约守得完美、译文质量在线，却是 reasoning 模型，单 chunk 63–124s，是 sonnet 的 ~30 倍，串行翻一篇 146-chunk 论文要 ~3.7h。

- **推荐接入**：`POST http://127.0.0.1:3003/v1/chat/completions`，`Authorization: Bearer 240127`（一次通过，未试 x-api-key），`model=claude-sonnet-5-medium`，`temperature=0.2`，`max_tokens` ≥ 8192 富余（实测 out 170–277 tokens）。备选 `gemini-3-8-flash-medium`（质量相当、契约全绿，但带 thinking token 开销）。
- **swe-2-max 判定**：能用但不该当主力翻译后端。占位符/命令契约 4/4 全保（连 `\` 控制空格和 `\href{url}{}` 都逐字保住），学术译文准确流畅——代码模型的指令跟随确实强，验证了"契约反而守得好"的假设。唯一问题是推理开销：每 chunk 自带 580–1066 字符 reasoning，延迟 63–124s。适合当兜底或对照组，不适合批量管线。
- **OpenAI 全系不可用**（gpt-5-5-medium、gpt-5-4-medium 均 502 `devin stream ended without stop reason`）；`glm-5-3-medium` 400 `permission_denied`。横评实际只跑了 3 家（windsurf/anthropic/google）。

## 端点矩阵（实测）

| 端点                        | 状态                                                                                                          |
| --------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `GET /v1/models`            | 200，200+ 模型（anthropic/google/openai/zai/moonshot/xai/deepseek/nvidia/windsurf/machines + `MODEL_*` 别名） |
| `POST /v1/chat/completions` | 200，三族模型通用；reasoning 模型经 `message.reasoning_content` 返回思考                                      |
| `POST /v1/messages`         | 200（claude-sonnet-5-medium 实测），Anthropic 原生格式                                                        |
| `POST /v1/responses`        | 200（swe-2-max 实测），reasoning 走 encrypted_content                                                         |

成本注意：**网关会注入隐藏系统提示**——"Say OK"最小请求 prompt_tokens 高达 465（swe-2-max）/ 566（claude via /v1/messages），每请求固定 overhead 要计入成本模型。

## 样例与逐条结果

样例取自 `miniscanner.parse_file('bench/corpus/1706.03762/ms.tex', flatten=True)` 的 chunks + 1 个手写压力样例。system prompt 用简化版契约（占位符逐字保留/不新造/保 LaTeX 命令/只输出译文）。校验器：`tmp/exp/rule_validator.validate_pair`（注意不在 `bench/py/`，在 `tmp/exp/`）。

| 样例               | 来源     | len  | 占位符                    | swe-2-max   | sonnet-5-medium | gemini-3.8-flash-medium |
| ------------------ | -------- | ---- | ------------------------- | ----------- | --------------- | ----------------------- |
| A-intro-encdec     | chunk#15 | 490  | 6 (2 CITE+4 MATH)         | PASS 63.3s  | PASS 3.0s       | PASS 3.7s               |
| B-decoder-mask     | chunk#21 | 706  | 3 MATH                    | PASS 89.9s  | PASS⚠1warn 3.1s | PASS 7.9s               |
| C-conv-complexity  | chunk#58 | 770  | 8 (2 CITE+6 MATH)         | PASS 93.4s  | PASS 4.2s       | PASS 7.6s               |
| D-synthetic-stress | 手写     | ~330 | 5 (BIBITEM+2 MATH+2 CITE) | PASS 123.6s | PASS 3.2s       | PASS 3.2s               |

唯一 warn：sonnet 在 B 的 zh/src 长度比 0.30 压线（界 [0.3,2.5]）。中文本来就密，0.30 是正常值——**validator 下界建议放宽到 ~0.25**。

### D 样例（压力样例，全文）

src：`[[BIBITEM_1]] Vaswani et al.\ \href{https://arxiv.org/abs/1706.03762}{introduced the Transformer}, demonstrating that attention alone suffices when the hidden dimension satisfies [[MATH_3]]; earlier work by Bahdanau, Cho, and Bengio [[CITE_2]] and the survey of Luong and Manning [[CITE_5]] had already hinted at this, provided gradients stay below [[MATH_4]].`

- swe-2-max：`[[BIBITEM_1]] Vaswani et al.\ \href{https://arxiv.org/abs/1706.03762}{提出了 Transformer}，证明了当隐藏维度满足 [[MATH_3]] 时，仅靠注意力机制便已足够；…` — **全保**：BIBITEM 前缀占位符、`\`、`\href` URL 逐字、人名处理得体。
- sonnet：`[[BIBITEM_1]] Vaswani等人\href{…}{提出了Transformer}，…` — 占位符全保，但**删了 `\` 控制空格**（validator 不报：macro 规则只查 zh _新增_ 命令，不查丢失的非结构命令——校验盲区，重建时 `\` 丢失无害但说明契约覆盖不全）。
- gemini：`[[BIBITEM_1]] Vaswani 等人\ \href{…}{提出了 Transformer}，…` — 全保，含 `\`。

### 质量一句话点评

- **swe-2-max**：术语最稳（空洞卷积、逐点前馈层、层归一化）；C 样例混用半角逗号 `,` 与全角 `，`——排版小瑕疵。
- **claude-sonnet-5-medium**：同等学术腔，行文最干净（扩张卷积）；输出纯译文零包装。
- **gemini-3.8-flash-medium**：质量持平（膨胀卷积），偶有加词（"在此结构中"），占位符前后保留空格习惯好。

## 成本/延迟信号

| 模型                    | in tokens/chunk | out tokens/chunk | 延迟     | 备注                                      |
| ----------------------- | --------------- | ---------------- | -------- | ----------------------------------------- |
| swe-2-max               | 245–319         | 491–1034         | 63–124s  | out 含 reasoning_content（580–1066 字符） |
| claude-sonnet-5-medium  | 259–359         | 170–277          | 3.0–4.2s | 无 thinking，token 最省                   |
| gemini-3.8-flash-medium | 145–225         | 384–1259         | 3.2–7.9s | out 大头是 thinking                       |

按 146 chunks/篇估算：sonnet 输入 ~4.1 万 + 输出 ~3.2 万 tokens、串行 ~9 分钟；gemini 输出 ~13 万（thinking 占 3/4）；swe-2-max 输出 ~10 万但延迟是瓶颈。若网关有并发余量，吞吐问题可缓解，成本信号需按厂商计价另算（usage 字段完整返回，含 `prompt_tokens_details.cached_tokens`，未见计费字段）。

## 遗留

- 未测流式、`temperature` 以外参数（response_format/seed）、超长 chunk（>2k 字符）与并发限流。
- 占位符契约在本批 100% 存活，样本量 12 对——上线前建议拿 `bench/fixtures/` 陷阱集 + 整篇 1706.03762 做一次大样本回归。
- OpenAI/zai 上游故障若是网关侧长期问题，模型清单的"存在≠可用"要进运行手册。
