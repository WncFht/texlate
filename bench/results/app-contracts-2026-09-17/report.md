# app-contracts — app.py 端点契约一致性终审

> 2026-09-17。scope：app.py 端点契约 + 三测试文件。478 app/api/server/share 测试绿、ruff 净。

## 端点 × 守卫阶梯矩阵（18 路由）

约定：`_get_task` = valid_task_id → exists → tenant（3 查合一 404）；`TransitionError` → 409 invalid_transition；`StoreError` → 500 internal；`RequestValidationError` → 400 invalid_request。

| 端点 | 404 task | 4xx 输入 | 409 | 422 | 429 | 500 | auth |
|---|---|---|---|---|---|---|---|
| POST /api/arxiv/{id}/translate | — | 400 invalid_request（options 闸：engine∉词表/concurrency 非整数/非法 JSON）| 409 duplicate_active | — | 429 quota_exceeded | ✓ | BYOK resolve_auth |
| GET /api/task/{id}（SSE 同端点）| ✓ | — | — | — | — | ✓ | tenant via _get_task |
| GET /api/files/{id} | ✓ | — | — | — | — | ✓ | tenant |
| GET /api/files/{id}/{kind} | ✓ | 400 kind 白名单 | 409 version_mismatch 先于磁盘 404（防御序，可辩护）| — | — | ✓ | tenant |
| POST /api/upload | — | 400 invalid_request（multipart/options 闸）/413 upload_too_large/415 unsupported_format | 409 duplicate_active | — | 429 | ✓ | BYOK |
| POST /api/share/import | — | 400 share_invalid（包级校验全家）+ options 闸 | 409 duplicate_active | — | 429 | ✓（孤儿目录已收——upload-hardening 落地版）| BYOK |
| POST /api/task/{id}/share/pack | ✓ | — | 409 invalid_state（非终态）| 422 share_pack_rejected（kind=share/reuse_hit/无 arxiv_id）→ share_pack_artifacts（缺产物）| — | 500 share_pack_failed | tenant |
| GET /api/health | — | — | — | — | — | — | 公开（探活语义）|
| GET /api/tasks | — | — | — | — | — | ✓ | tenant 过滤 |
| POST /api/task/{id}/cancel | ✓ | — | 409 invalid_transition | — | — | ✓ | tenant |
| POST /api/task/{id}/retry | ✓ | 400 invalid_request（options 闸）| 409 invalid_transition | — | — | ✓ | tenant |
| DELETE /api/task/{id} | ✓ | — | 409 invalid_transition（非终态拒删）| — | — | ✓ | tenant |
| GET /api/task/{id}/reader | ✓ | — | — | — | — | ✓ | tenant |
| PUT /api/task/{id}/reader/position | ✓ | 400（body 校验）| — | — | — | ✓ | tenant |
| GET /api/settings | — | — | — | — | — | — | 公开读（见越权面③）|
| PUT /api/settings | — | 400 invalid_request | — | — | — | — | **新增：server 模式 403 闸** |
| POST /api/settings/test | — | 400 invalid_request | — | — | — | ✓ | **新增：server 模式 403 闸** |
| GET /api/providers | — | — | — | — | — | — | 公开读（见越权面③）|

阶梯一致性结论：share/pack 永久拒（422）先于瞬时拒（409）的排序正确——终态判定先跑是因为 kind/reuse_hit 是永久属性，非终态是瞬时属性；cancel/retry/delete 三个 409 经不同机制产出同形 body，契约一致。

## 错误码词表（14 码，全 snake_case）

`upload_too_large`(413) `unsupported_format`(415) `share_invalid`(400) `invalid_request`(400) `duplicate_active`(409) `invalid_transition`(409) `invalid_state`(409) `version_mismatch`(409) `quota_exceeded`(429) `share_pack_rejected`(422) `share_pack_artifacts`(422) `share_pack_failed`(500) `internal`(500) `auth_required`(401)。

- `invalid_state` vs `invalid_transition` 同义双码：**不改名**——web/dev/mock-api.ts:1272 与 sharePack.test.ts:190 钉死 invalid_state；前端按 status===409 分支不按 code。已在 test_share_postpack.py 钉码 + 注释防漂移。
- 无 code 的裸 400 是既定约定：code 只在客户端分支处发（duplicate_active 带 taskId、share_pack_*、invalid_state）。

## 越权面清单

**已修（本次落盘）：**

1. **HIGH — PUT /api/settings + POST /api/settings/test server 模式无闸**：任何可及 HTTP 的租户可改 base_url（跨租户 key 经第三方网关回传=窃钥）+ settings/test 是 SSRF 探测 oracle。依 web-layer.md §4.1（PUT settings 是本地单机默认形态，server 模式由部署方 settings.json/env 管理）新增 `_settings_write_gate()` → server 模式一律 403。
2. **MED — options_json 注入面**：无 schema 直流入库。修三类：(a) `concurrency:"abc"` → int() 崩 → 500（真契约 bug）；(b) `engine:"pdflatex"` 不校验 → 延迟到编译期才炸 → 现 intake 400；(c) 系统键 `reuse_hit/arxiv_categories/engine_resolved/route_engines/share` 用户可伪造（reuse_hit 注入→share_pack 拒收方向安全但污染审计）→ `_clean_task_options` 四处 intake 摘除 + engine 词表校验 + concurrency clamp 1–16。

**报告不改（超scope/需产品决策）：**

3. GET /api/settings（glossary_dir/base_url/quota）、/api/health（data_dir 绝对路径）、/api/providers（has_env_key）在 server 模式是信息泄漏面——响应形状是产品决策，建议 server 模式裁字段。
4. worker.py:3122 `int(options.get("qps"))` 同 (2a) 崩溃类——share-wire 在飞，只读参照未动。
5. `_auth` 每 translate 请求调 3 次（settings.json 重读 ×3）——perf nit。
6. retry mutation-before-final-transition 竞态窗——B3 已接受设计。

## 改动文件

- `src/texlate/server/app.py`：+`_RESERVED_OPTION_KEYS`/`_ENGINE_NAMES` 常量 + `_settings_write_gate()` + `_clean_task_options()`；接线 4 处 intake（translate :683、_upload_fields :840、share_import :949、retry :1218）+ 2 处 settings 闸（:1342/:1357）
- `tests/test_app_endpoints.py`：+TestOptionsGate(7) +TestServerModeSettingsGate(4)
- `tests/test_share_apply.py`：+test_import_options_gate + partial import
- `tests/test_share_postpack.py`：invalid_state 码钉版 + 注释

## 验证

`uv run pytest tests/ -k "app or api or server or share"` → **478 passed**；`ruff check` + `ruff format --check` 四文件全净。未动 _parse_multipart/share_import 体（upload-hardening 落地版）、worker/store/events。

## leader 复核备注

- diff 与报告逐 hunk 对账一致；share_import 内 `_clean_task_options` 插位在服务端 `options["share"]` 审计载荷强制覆盖**之前**——用户伪造 share 键先摘、服务端再权威覆写，顺序正确。
- retry 路径 `_clean_task_options` 只清入参 body——既有任务行上的合法 `share`/`reuse_hit` 标记不受影响。
