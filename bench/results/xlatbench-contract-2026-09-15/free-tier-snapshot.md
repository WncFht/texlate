# 免费集 / promo 快照 — 2026-09-15 ~09:36 UTC+8

来源：`GET /panel/api/models`（191 条）∩ `GET /v1/models`（209 条），
原始响应落盘 `models_panel.json` / `models_v1.json`（同目录）。
字段口径：`cost_tier`（free/low/medium/high）+ `credit_multiplier` + `promo.{active,end_date}`。

## cost_tier == "free"（6 个 —— 与 E22 免费集同口径）

| uid | provider | credit_multiplier | promo.end_date (UTC) | 备注 |
|---|---|---|---|---|
| glm-5-2 | ZAI | 1.5 | **2026-09-16T07:59** | 明天到期 |
| swe-1-7 | WINDSURF | 9 | **2026-09-16T07:59** | 明天到期 |
| swe-1-7-medium | WINDSURF | 3 | **2026-09-16T07:59** | 明天到期 |
| swe-2-medium | WINDSURF | 6 | 2026-10-16T06:59 | E22 默认 |
| swe-2-high | WINDSURF | 9 | 2026-10-16T06:59 | |
| swe-2-max | WINDSURF | 12 | 2026-10-16T06:59 | |

## promo.active == true（非 free tier，16 个）

| uid | provider | tier | mult | promo.end_date (UTC) |
|---|---|---|---|---|
| glm-5-2-none | ZAI | low | 1 | **2026-09-16T07:59** |
| glm-5-2-none-1m | ZAI | low | 2 | **2026-09-16T07:59** |
| glm-5-2-1m | ZAI | low | 3 | **2026-09-16T07:59** |
| glm-5-2-max | ZAI | low | 3 | **2026-09-16T07:59** |
| glm-5-2-max-1m | ZAI | low | 6 | **2026-09-16T07:59** |
| swe-1-7-lightning | WINDSURF | medium | 18 | **2026-09-16T07:59** |
| swe-1-7-lightning-medium | WINDSURF | medium | 9 | **2026-09-16T07:59** |
| gpt-5-6-sol-none | OPENAI | high | 10 | 2026-10-03T07:00 |
| gpt-5-6-sol-low | OPENAI | high | 30 | 2026-10-03T07:00 |
| gpt-5-6-sol-medium | OPENAI | high | 50 | 2026-10-03T07:00 |
| gpt-5-6-sol-high | OPENAI | high | 90 | 2026-10-03T07:00 |
| gpt-5-6-sol-xhigh | OPENAI | high | 150 | 2026-10-03T07:00 |
| gpt-5-6-sol-max | OPENAI | high | 200 | 2026-10-03T07:00 |
| gemini-3-7-flash-low | GOOGLE | medium | 6 | 2027-01-01T08:00 |
| gemini-3-7-flash-medium | GOOGLE | medium | 8 | 2027-01-01T08:00 |
| gemini-3-7-flash-high | GOOGLE | medium | 10 | 2027-01-01T08:00 |

## 要点

- **2026-09-16T07:59Z 到期潮**：glm-5-2 全系 6 变体 + swe-1-7 系 4 个共 10 个 uid 同刻到期；免费集从 6 → 3（仅剩 swe-2-medium/high/max）。
- gpt-5-6-sol 系 promo 到 10-03，但 OpenAI 系实测全 502（E21）——promo 有效 ≠ 可用。
- 全部 promo 模型都在 `/v1/models` 清单内且 `disabled=false`。
- 运行期纪律不变：client 启动时拉 panel + v1 求交 + 探活，不硬编码免费集。
