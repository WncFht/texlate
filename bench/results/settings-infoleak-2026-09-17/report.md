# settings-infoleak — server 模式三端点信息泄漏裁剪

> 2026-09-17。scope：app.py + test_app_endpoints.py。204 app/api/settings/provider 测试绿、ruff 净。app-contracts 终审遗留 #3 收口。

## 前端消费面取证

| 字段 | 前端消费点 | 判定 |
|---|---|---|
| settings.base_url/model/target_lang/glossary/engine/concurrency/context_guidance/has_api_key | Settings.tsx 表单 prefill（L28-34）+ has_api_key 徽标/清键钮 | 留 |
| settings.glossary_dir | web/src 零命中 | 裁（宿主文件系统路径） |
| settings.cors_origins | web/src 零命中 | 裁（部署方跨域策略） |
| settings.quota_max_tasks/quota_max_bytes | 零命中但属租户自身配额策略，非拓扑 | 留（处方「别一刀切」） |
| health.ok/version/compilers | Home.tsx L342-353 徽标 | server 模式全裁；前端 `version ?? "?"` + compilersStat 空串天然降级 |
| health.data_dir | 零命中 | 裁 |
| providers.has_env_key | web/src 零命中（mock 本就恒 false） | 摘键（前端无消费，摘键与恒 false 等价取摘键） |
| providers.active/key_env | key_env 是静态预设元数据、active 可由已保留的 base_url 推导 | 留 |

## 改动文件

- `src/texlate/server/app.py`：新增 `_SERVER_SETTINGS_HIDDEN` 常量（cors_origins+glossary_dir，注明 quota 保留理由）；`health()` server 分支回 `{ok: True}` 最小集；`settings_get()` server 摘 2 键；`providers()` server 摘 `has_env_key`。判法沿用 `_settings_write_gate` 同款 `server_mode() == "server"`。
- `tests/test_app_endpoints.py`：TestServerModeSettingsGate 增 4 钉样——health 最小集精确等值、settings 缺省+保留面断言、providers 摘键（env 真设 DEEPSEEK_API_KEY 也不回）、local 三端点全量回归钉样；类 docstring 补裁剪契约。

## 未改

- `web/dev/mock-api.ts`：mock 固定 local 形态，当前全量出参即 local 响应，不演双模（记录差异）。
- `web/src/api/client.ts`：`Health.version/compilers/data_dir`、`Settings` 拓扑键、`Provider.has_env_key` 均 optional/catchall 已覆盖缺省形态，无类型改动。
- `settings_put` 响应不裁：server 模式 PUT 已 403 不可达（`_settings_write_gate`，08eb73a）。

## 验证

`uv run pytest tests/ -k "app or api or settings or provider"` → **204 passed**；`ruff check` + `ruff format --check` 双链净。

## leader 复核备注

- diff 与报告逐 hunk 对账一致；裁剪判法与 `_settings_write_gate` 同口径 `server_mode() == "server"`。
- quota_* 保留决策合理——多租户下租户须自查配额用量（agent 按处方执行）。
