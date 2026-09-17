# scout-token-prep — n200 真臂网关/token 可行性盘点（只读）

> 2026-09-17 ~08:00 UTC 实测收口。**结论：GO。主链 `http://100.105.212.52:3003` + `swe-2-medium` 全绿，昨夜 realpostfix2 n100 刚实证跑通（4.03h、10706/10717 chunk ok、零 429）。** 兜底面有一处恶化：Prism 已余额耗尽。探针现场 `tmp/scout-token-prep/`（gitignored）。

## 各网关实测现状

### devin-2api 主网关（推荐路径，bench 默认）

- `http://100.105.212.52:3003` Bearer `240127`：healthz 200（v0.12.0，较 09-14 的 v0.9 已升级），214 模型，`swe-2-medium`/`swe-2-high`/`swe-2-max` 实测 chat 200（swe-2-medium ~5s "OK"，rsn~100 字符；swe-2-high 2.8s）。tailnet 直连，出向经 gwcap :3399 透明代理——swe-2-medium* 全局 sem=4，当前 inflight=0/queued=0 空闲。
- 本机第二路径 `http://127.0.0.1:3033`：archbox 自己的 devin-2api v0.12.0（独立 token 直发 server.codeium.com，max_rpm 80，**不受 gwcap 闸**），swe-2-medium 实测 200。上游账号是否与 fht-mba 同号未实证——若同号，分路径提吞吐不增配额。
- ssh 隧道 `127.0.0.1:3003` 当前未起（非常驻）；bench 不需要它，server 产品链也可走 tailnet http（validate_base_url 已白名单 100.64/10）。
- **坑（已踩实证）**：`temperature:0` → 502 `invalid_argument` 全模型灭；`0.2` 正常。产品 `TRANSLATE_TEMPERATURE=0.2` 安全，prompts.py:346 有记录——任何新探针/脚本别用 temp=0。
- promo 面：记录 swe-2 系免费至 **2026-10-16**（剩 29 天）；v0.12.0 已删 `/panel/api/models`，免费池无法内省，只能实测+按到期日。glm-5-2/swe-1-7 系 promo 09-16 已到期。

### 兜底池（按可靠性排序，均实测）

- **Prism `https://ai.prism.uno`：已死**——/v1/models 200（23 模型）但 chat 返回 `insufficient_user_quota`，余额 **-$0.28**。保险库付费面 80→0，需充值才复活。
- **llm7.io `https://api.llm7.io`**（免 key）：47 模型含 GLM-5.3-Flash；首发 30s 超时、重试 4.8s 通——不稳定依旧，且该模型是 reasoning 型（需留 max_tokens 余量）。机会型。
- **Pollinations `https://text.pollinations.ai`**（免 key）：openai-fast 实测 "OK" 0.87s，anonymous 共享预算。机会型。
- 同网关付费/计量链（非免费但活）：`claude-sonnet-5-medium`（chat + /v1/messages 实测 200，in 566/req）、`glm-5-3-low`（记录档 $1.4/$4.4 per M，未再烧）。

## n200 需求测算（证据：realpostfix2-2026-09-16 n=100 真臂）

- 规模：~107 chunks/篇 → n200 ≈ **21.4K chunks**；token/chunk ~450–700（in 250–500 含隐藏系统提示 + out ~134）→ **总量 ~10–15M tokens**。
- 墙钟：n100@conc2=4.03h → n200 **~8h@conc2，~4h@sem4**（gwcap 硬闸上限）；双路径分流理论上可再压，但受上游账号配额是否共享所限（未实证）。
- 成本：promo 窗口内 **$0**；窗口后需切计量链或注册的免费档（ModelScope/智谱等，见 free-tokens 文档待办清单）。

## 推荐网关序

1. **主力**：`100.105.212.52:3003` + `swe-2-medium`，`--sem 4`（stagerun 默认即此）。
2. 备选同池：`swe-2-high`（契约 99%，慢 70%）；修复器专座 `swe-2-max`。
3. 路径冗余：`127.0.0.1:3033`（fht-mba 挂/被占时顶上）。
4. 质量兜底（计费）：`claude-sonnet-5-medium` / `glm-5-3-low`。
5. 免费兜底（机会型，仅救急不进关键路径）：pollinations > llm7。

## 风险项

1. **promo 窗口**：swe-2 免费至 10-16——n200 必须在此之前落完；逾期无免费主力，需切计量链或让用户注册免费档（最高 ROI：ModelScope/智谱/百炼/SiliconFlow/OpenCode Zen）。
2. **Prism 死** → vault 兜底清零，剩余免费兜底全是机会型，撑不起 21K 请求。
3. fht-mba 实例 `active_requests=18`——其他会话/客户端在共用；gwcap 只闸本机 swe-2-medium。
4. `temperature:0` 502 地雷（前述）；免费池无内省口，跑前需 1 发探活确认 promo 未提前死。
