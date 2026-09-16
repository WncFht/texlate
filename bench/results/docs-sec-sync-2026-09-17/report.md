# docs-sec-sync — SEC-1..10 + 别名对账规格同步交付

> 2026-09-17 收口。落地 `e5bd205`（docs/ 3 文件 4 处，+5/-4）。只动 docs/，代码零碰。全部按各文档既有「勘误 2026-09-17」文风就地追加。

## 改动清单

1. **docs/06-arxiv-source.md §2.2** —「链接语义」bullet 后新增「别名落点对账」一条：经 kept symlink 祖先写穿的成员共享物理落点、后到写穿先到，`_reconcile_aliases` 以落点最末成员为赢家回填 size/sha256（涉 symlink 含 kind/link_target），字段实变者记 `dup_member_overwrite`。理由：`6fe2feb` 落地的新行为，§2.2 是 unpack 契约规范位。

2. **docs/05-reproduction-plan.md §5.7 BYOK 行（179）** — 追加勘误：server 形态（TEXLATE_MODE=server）无 X-Texlate-Key 时 resolve_auth 直出 `api_key=""`/`source=none`，key 不回落 settings.json/env，匿名桶永不携带部署方凭据；`validate_model` 加 `isprintable` 闸。理由：原行「header > settings.json > env」四级回落断言已被 SEC 修复推翻（server 形态例外）。

3. **docs/05-reproduction-plan.md §5.7 中间件行（180）** — 追加勘误：impl 为 `request_gate_mw` 单中间件两形态共用，写清语义域——local Host 剥端口须 ∈ {localhost,127.0.0.1,::1} 违则 403（全请求含读面）；mutating /api 按序 allowlist Origin 放行 → Sec-Fetch-Site:cross-site 403 → Origin scheme+netloc(含端口)≠请求 scheme+Host 403 → 皆无放行；server 匿名 mutation 401 auth_required（allowlist 不豁免）；非空 body 非 application/json 415；PUT settings/settings/test server 形态 403；settings/test 跨槽 base_url-only 400；upload 文件名落 `.`/`..` 400。理由：原行「TrustedHost(localhost) + 非 GET 校验 Origin/Sec-Fetch-Site」与新闸语义不符。

4. **docs/05 §5.1 解包行（125）+ docs/tools-runbook.md share unpack 行（16）** — 前者追加 mtree 多列 + 别名对账指引勘误（mtree path+sha256 三列断言早前已漂移，顺带收口指向 docs/06 §2.2）；后者补 share 解包上限（manifest ≤1MB、artifacts ≤64、声明合计 ≤300MB、size+1 有界读，违例 ShareError→share_invalid）。理由：两处是 in-scope 文档里仅有的 unpack/share 契约描述面。

## 核实依据（代码为准）

share.py:64/69/385-416（_ARTIFACT_MAX/_INFLATED_MAX/有界读）、settings.py:489-497（server 不回落）、settings.py:148（isprintable）、app.py:474-513（request_gate_mw 全序）、app.py:609-634（415 闸）、app.py:1485-1493（跨槽 400）、app.py:974-978（文件名 400）、app.py:1080-1085（ShareError→400 share_invalid）、unpack.py:202-235/302（_reconcile_aliases 收尾调用点）。

## 存疑未改的漂移

- docs/08 无「server/BYOK 节」——任务指针近似，实际 server 面规格在 docs/05 §5.7（其规范本体是冻结的 research/product/web-layer.md，按要求未动）；docs/08 §6 状态词表 needs_auth 行仍准确。
- research/product/web-layer.md 大概率仍写着已被推翻的旧断言（匿名继承 key/TrustedHost 等），但属冻结档案不动。
- HANDOFF-2026-09-15/16 为时点记录，未动。
