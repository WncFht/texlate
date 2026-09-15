# Gateway 3003 探测报告

探测时间：2026-09-14 ~22:24-22:35 本地时间。目标 `http://127.0.0.1:3003`，key `240127`。

## TL;DR

**`swe-2-max` 存在且可调通。** 走 OpenAI Chat 协议：

```
POST http://127.0.0.1:3003/v1/chat/completions
Authorization: Bearer 240127
{"model":"swe-2-max","messages":[{"role":"user","content":"..."}],"max_tokens":N}
```

它是 reasoning 模型：响应里 `message.reasoning_content` 是思考链、`message.content` 是正文，`max_tokens` 要留够（reasoning 也吃 max_tokens，16 token 会全部耗在思考上导致 content 为空 + `finish_reason:"length"`）。`/v1/responses`（OpenAI Responses）和 `/v1/messages`（Anthropic）两种协议对 swe-2-max 同样可用。流式/非流式都支持。

## 进程身份

- `lsof -nP -i :3003`：进程 `devin-2ap`（PID 28962，user fanghaotian）监听 `*:3003`，有 20+ 条 ESTABLISHED 连接（在被别的客户端用着）。
- `GET /healthz` 返回：`{"active_requests":22,"debug_logging":true,"draining":false,"pid":28962,"status":"ok","uptime_seconds":1902,"version":"v0.9.0-13-gcc28e95"}`
- 上游是 **Devin**：未知模型报错原文 `devin stream ended without stop reason`、`permission_denied ... (trace ID: ...)`。
- Go 写的服务（404 是 `404 page not found` + `X-Content-Type-Options: nosniff`，gorilla/mux 风格）。

## 认证

| 方式                           | 结果                                                                   |
| ------------------------------ | ---------------------------------------------------------------------- |
| 无 auth                        | 401 `{"error":{"message":"Missing API key","type":"unauthenticated"}}` |
| `Authorization: Bearer 240127` | **200**                                                                |
| `x-api-key: 240127`            | **200**                                                                |
| `api-key: 240127`              | 401 Missing API key                                                    |

结论：Bearer 或 `x-api-key` 都行（query param 未试，header 已够）。报告全程用 Bearer。

## 端点面

| 端点                                                                                                                    | 状态           | 说明                                                               |
| ----------------------------------------------------------------------------------------------------------------------- | -------------- | ------------------------------------------------------------------ |
| `GET /healthz`                                                                                                          | 200            | 无需 auth；JSON 健康信息（见上）                                   |
| `GET /v1/models`                                                                                                        | 200（需 auth） | 209 个模型                                                         |
| `GET /v1/models/{id}`                                                                                                   | 200（需 auth） | 单模型详情，如 `/v1/models/swe-2-max`                              |
| `POST /v1/chat/completions`                                                                                             | **200**        | OpenAI Chat 协议，stream + 非 stream 均可                          |
| `POST /v1/responses`                                                                                                    | **200**        | OpenAI Responses API 协议                                          |
| `POST /v1/messages`                                                                                                     | **200**        | Anthropic Messages 协议（返回 thinking block + `sealed.v1.` 签名） |
| `POST /v1/completions`                                                                                                  | 404            | legacy completions 不存在                                          |
| `POST /chat/completions`、`POST /messages`（无 /v1）                                                                    | 404            |                                                                    |
| `GET /`、`/health`、`/models`、`/docs`、`/openapi.json`、`/v1`、`/status`、`/metrics`、`/v1/embeddings`、`/v1/usage` 等 | 404            | 无自带文档                                                         |

## 模型清单（209 个，按 owned_by 分组，原样 id）

**windsurf (9)**：`swe-1-6`, `swe-1-6-fast`, `swe-1-7`, `swe-1-7-medium`, `swe-1-7-lightning`, `swe-1-7-lightning-medium`, `swe-2-medium`, `swe-2-high`, `swe-2-max`

**anthropic (53)**：`claude-opus-4-6`, `claude-opus-4-6-1m`, `claude-opus-4-6-thinking`, `claude-opus-4-6-thinking-1m`, `claude-opus-4-7-{low,medium,high,xhigh,max}`, `claude-opus-4-8-{low,medium,high,xhigh,max}` + `-fast` 各档，`claude-opus-5-{low,medium,high,xhigh,max}` + `-fast` 各档，`claude-5-fable-{low,medium,high,xhigh,max}`, `claude-fable-5-1-{low,medium,high,xhigh,max}`, `claude-sonnet-4-6`, `claude-sonnet-4-6-1m`, `claude-sonnet-4-6-thinking(-1m)`, `claude-sonnet-5-{low,medium,high,xhigh,max}`, `MODEL_CLAUDE_4_5_OPUS`, `MODEL_CLAUDE_4_5_OPUS_THINKING`, `MODEL_PRIVATE_{2,3,11}`

**openai (88)**：`gpt-5-4-{none,low,medium,high,xhigh}` + `-priority` 各档，`gpt-5-4-mini-{low,medium,high,xhigh}`, `gpt-5-5-{none,low,medium,high,xhigh}` + `-priority`, `gpt-5-6-sol-{none,low,medium,high,xhigh,max}` + `-priority`, `gpt-5-6-terra-{none,low,medium,high,xhigh,max}` + `-priority`, `gpt-5-6-luna-{none,low,medium,high,xhigh,max}` + `-priority`, `gpt-6-astra-{low,medium,high,xhigh,max}` + `-priority`（无 none）, `gpt-5-3-codex-{low,medium,high,xhigh}` + `-priority`, `MODEL_GPT_5_2_{NONE,LOW,MEDIUM,HIGH,XHIGH}`, `MODEL_CHAT_GPT_4_1_2025_04_14`, `MODEL_PRIVATE_{12,13,14,15}`

**google (20)**：`gemini-3-1-pro-{low,high}`, `gemini-3-5-flash-{minimal,low,medium,high}`, `gemini-3-6-flash-{minimal,low,medium,high}`, `gemini-3-7-flash-{low,medium,high}`, `gemini-3-8-flash-{low,medium,high}`, `MODEL_GOOGLE_GEMINI_3_0_FLASH_{MINIMAL,LOW,MEDIUM,HIGH}`

**zai (12)**：`glm-5-2`, `glm-5-2-max`, `glm-5-2-1m`, `glm-5-2-max-1m`, `glm-5-2-none`, `glm-5-2-none-1m`, `glm-5-3-{low,high,max}`, `glm-5-3-flash-{low,high,max}`

**moonshot (5)**：`kimi-k2-6`, `kimi-k2-7`, `kimi-k3-{low,high,max}`

**xai (7)**：`grok-4-5-{low,medium,high}`, `grok-4-6-{low,medium,high,xhigh}`

**deepseek (6)**：`deepseek-v4-flash-{high,max}`, `deepseek-v4-1-flash-{high,max}`, `deepseek-v4-pro-{high,max}`

**machines (6)**：`inkling-{none,low,medium,high,xhigh,max}`

**nvidia (3)**：`nemotron-3-ultra-{none,medium,high}`

`swe-2-max` 详情：`{"context_tokens":262000,"max_output_tokens":128000,"owned_by":"windsurf","supports_thinking":true,"preserve_thinking":true,"supports_tool_calls":true,"supports_parallel_tool_calls":true,"supports_images":true,"is_model_router":false}`

## 端点 × 模型矩阵（`POST /v1/chat/completions`，"Say OK"，max_tokens=64）

| 模型                     | 结果    | 延迟    | 备注                                                                                                                                                                                       |
| ------------------------ | ------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `swe-2-max`              | 200     | ~12-15s | reasoning 模型，`reasoning_content` + `content`                                                                                                                                            |
| `swe-2-high`             | 200     | 12.2s   | 同上                                                                                                                                                                                       |
| `claude-sonnet-5-medium` | 200     | 1.9s    | 无 reasoning_content 字段                                                                                                                                                                  |
| `gpt-6-astra-medium`     | **502** | 1.6s    | `{"error":{"message":"devin stream ended without stop reason","stage":"response_event","type":"server_error","debug_ref":"20260914-223630"}}`                                              |
| `deepseek-v4-pro-max`    | 200     | 1.6s    | 有 reasoning_content                                                                                                                                                                       |
| `glm-5-3-max`            | 200     | 0.5s    | 最快；`cached_tokens:320`                                                                                                                                                                  |
| `kimi-k3-high`           | 200     | 1.0s    | 有 reasoning_content                                                                                                                                                                       |
| `nonexistent-model`      | **400** | 0.4s    | `{"error":{"message":"permission_denied: an internal error occurred (trace ID: ...)","type":"invalid_request_error","upstream_trace_id":"..."}}` —— 模型清单是静态目录，未授权模型被上游拒 |

响应结构：标准 OpenAI chat.completion（`choices[0].message.{content,reasoning_content?}`、`usage.{prompt_tokens,completion_tokens,prompt_tokens_details.cached_tokens}`）。流式为 SSE `chat.completion.chunk`，`reasoning_content` 与 `content` 分 delta 下发，结尾 `data: [DONE]`。

## swe-2-max 实测样例

请求（非流式）：

```json
POST /v1/chat/completions
{"model":"swe-2-max","messages":[{"role":"user","content":"Translate to Chinese: The quick brown fox jumps over the lazy dog."}],"max_tokens":200}
```

响应（HTTP 200，14.3s）：

```json
{
    "choices": [
        {
            "finish_reason": "stop",
            "index": 0,
            "message": {
                "content": "敏捷的棕色狐狸跳过了懒惰的狗。",
                "reasoning_content": "I need to translate the English pangram \"The quick brown fox jumps over the lazy dog\" into Chinese. A direct translation would be 敏捷的棕色狐狸跳过了懒惰的狗，but a more natural phrasing in Chinese is 那只敏捷的棕色狐狸跳过了那只懒惰的狗。I'll provide this translation.",
                "role": "assistant"
            }
        }
    ],
    "model": "swe-2-max",
    "object": "chat.completion",
    "usage": {
        "completion_tokens": 97,
        "prompt_tokens": 477,
        "prompt_tokens_details": {
            "cache_write_tokens": 0,
            "cached_tokens": 0
        },
        "total_tokens": 574
    }
}
```

`/v1/messages` 同一模型返回 Anthropic 格式：`content[0]` 是 `{"type":"thinking","thinking":"...","signature":"sealed.v1...."}`，`content[1]` 是 `{"type":"text","text":"OK"}`，`stop_reason:"end_turn"`。`/v1/responses` 返回 `output[]` 里 `type:"reasoning"`（含 `encrypted_content:"sealed.v1...."` + `summary`）和 `type:"message"` 两项。

## 注意事项 / 坑

1. **每请求 ~465-477 prompt token 固定开销**：一句 "Say OK" 计 prompt_tokens≈465+，网关注入了上游 agent harness 系统提示。翻译流水线按量计费/限速时要算进成本；不是白送的上下文。
2. **reasoning 模型的 max_tokens**：swe-2-* / deepseek / kimi-k3 / inkling 这类会先把预算花在思考上，`max_tokens` 太小（如 16）会得到 `content:""` + `finish_reason:"length"`。翻译段落建议给充足输出预算或按段落长度放大。
3. **延迟**：swe-2-max 单句翻译 ~14s，明显慢于 glm-5-3-max（0.5s）等；大批量段落翻译要并发或换快模型。
4. **错误模型名报 400 `permission_denied`**（而非 model_not_found），`gpt-6-astra-medium` 这类在清单里的模型也会 502——清单 ≠ 全可用，用前按矩阵实测。
5. 网关是 Devin 系工具（`devin-2ap` v0.9.0-13），三种协议是适配层，upstream 只有一套；`sealed.v1.` 加密思考块在 Responses/Messages 里原样透出。
