# docs-sync — tools-runbook/web-layer/shared-cache 对齐落地特性

> 2026-09-17。scope：docs/tools-runbook.md + docs/research/product/web-layer.md + docs/research/product/shared-cache.md。文档-only，未 commit。

## tools-runbook.md（§1 命令表）

- `fetch` 行：补 `--offline`（help 原文「离线模式：只用本地 src-cache、零网络请求」），无缓存 `offline_no_cache` 退出 1。
- `run` 行：`<id>` → `<id|dir>`（签名 source 接受本地工程目录），补 `[--offline]` + `TEXLATE_OFFLINE=1` 等效 + `--server` 不生效（cli.py:206-213）。
- `run --server` 行：补 `--model/--api-key/--base-url/--out`（BYOK 走 `x-texlate-*` 头，cli.py:377-382）。
- `doctor` 行：`ctex` 已扩为 `cjk-fonts`（kpsewhich ctex.sty/fandol + fc-list :lang=zh），补 `gateway`/`data-dir`；状态集 ok/n/a → ok/warn/fail/n/a。
- 新增「离线总闸」段：`TEXLATE_OFFLINE=1` 等效 `--offline`，钉版精确查 `{id}v{ver}`、未钉版取已缓存最高版（cli.py:96-100 docstring）。
- 未改：parse/web/export/share pack/unpack/version/tools install-tectonic 与实现一致；export 的 --mock/--glossary/-o 属帮助级细节不收。

## web-layer.md

- §2.2 schema：kind enum 补 "share"；properties 补 `usage`（task_usage 聚合行 model/calls/prompt_tokens/completion_tokens/latency_s，无记录键缺席，store.py:818-820）。
- §2.5 补三端点：`DELETE /api/task/{id}`（终态删除，ACTIVE 409，删前补 done{status:"deleted"}）、`POST /api/share/import`（机械校验+key_parts 白名单→kind="share"，manifest 自描述寻址）、`POST /api/task/{id}/share/pack`（{share_key,url,bytes}，幂等；守卫：kind=share/reuse_hit→422 share_pack_rejected、非终态→409 invalid_state、缺产物→422 share_pack_artifacts、打包失败→422 share_pack_failed）（app.py:828/921/1151）。
- §2.5 settings 行补 `clear_api_key` 伪字段（app.py:1259）。
- §5.2 新增「终态与 BYOK 面（已落地）」段：stat-strip 七格（mergeResultStats=done.stats 优先+counters/usage 兜底）、「分享本译文」三挂载点（done share-banner / 非干净终态 result-banner 操作行 / doc 任务 result-panel；canShare=done|partial+kind≠share+有 arxiv_id）、needs_auth 内联 key 随 retry 透传、Home 临时 API Key 三路径（translate/upload/shareImport，.share.zip 自动路由后者）、Settings 清 key。BYOK per-request/usage 面板/清 key 三者 §5 此前均无载，已补齐；§4 BYOK 层级设计无 drift 未动。

## shared-cache.md

- §0 opt-in 行：标注完成钩+端点+按钮+CLI 四面已落地。
- §6 新增「落地现状（2026-09-17）」段：按钮三挂载点+canShare 门控→POST pack（幂等/409/422 阶梯）；Home share_pack 配置项→_maybe_share_pack；CLI 同口径（share_pack_manifest 单一派生面）。
- §8 接线现状：补 POST pack 端点 + 消费侧显式导入 POST /api/share/import→_run_share（fetch→parse→_stage_share_apply (src_file,en) 对账→compile，零 token）。**勘正**：原文「任务创建 fetch 后→share_key lookup→命中走 §5 通道」措辞像已接线——grep 确认 translate 路径无 index_lookup/share_key，隐式命中仍未接线，已改写为「挂点已就位（dedup 7cce5f9 同点位）、接线未做」。
- §5 未改：步骤与 _run_share/_share_apply 逐条对上。注：§5 步骤 4「L0/L1 validate」——worker 只跑 validate_pair（L0），L1 对任何 kind 都不进 worker 管线；属规格层措辞未改，仅此处备案。

## 遗留

- 隐式 share 命中（translate 自动查 index.jsonl）未接线，§8 已如实标注。
- Idempotency-Key（web-idem 在飞）等后续变动需下轮对账。
