# mock-parity — `web/dev/mock-api.ts` vs `src/texlate/server/app.py` 端面对账

> 2026-09-17。scope：web/dev/mock-api.ts（唯一改动文件，~200 行净增）。tsc/eslint/vitest 122 全绿 + vite dev curl 冒烟 30+ 断言过。

## 结论

端点覆盖：server 19 个路由 mock 全有（无缺失端点、无死 mock）。但**响应形态漂移 9 处**，其中 retry/cancel/delete 是确定性假绿——前端 `api.retry()` 读 `res.task_id`，mock 返 `{ok:true}` → `task_id=undefined` → nav `#/reader/undefined`。

## (b) 形态漂移（已修）

| 端点 | 原 mock | server 真值 | 修复 |
|---|---|---|---|
| POST /task/{id}/retry | 200 `{ok:true}` 无守卫 | **202** `{task_id,status,events_url,reader_url?,cache:"retry"}`；非 RETRYABLE_FROM→409 `invalid_transition`；needs_auth 无 key→401 `auth_required`；body 白名单 {main,options}→400 `invalid_request` | 全阶梯实装 |
| POST /task/{id}/cancel | 200 `{ok:true}` 任意态可销 | 200 `{task_id,status:"cancelled"}`；终态→409 `invalid_transition` | 守卫+形状 |
| DELETE /task/{id} | **204** 空体；409 无 code | **200** `{task_id,status:"deleted"}`；ACTIVE→409 `{detail,code:"invalid_transition"}`；删前补发 done{status:"deleted"} SSE 帧 | 全修 |
| GET /task/{id} snapshot | 进行中无 `artifacts` 键 | server 恒带 artifacts（进行中 src_tar 已登记） | `registeredArtifacts()` 按态给 |
| GET /tasks | 发 snapshot 形（带 warnings/last_seq/usage） | 列表行固定 16 键含 `source_name`，无 warnings/usage；`?status=` 过滤 | 行形重写+过滤 |
| GET /files/{id}/{kind} | 白名单内任意 kind 都发文件 | 按 files 表登记判 404（doc 任务 dual.json 应 404）；`?version=`→409 `version_mismatch`；`?download=`→Content-Disposition；HEAD 同 GET | 全修 |
| GET /task/{id}/reader | html 任务仍发 `translated` 文档；`reading:null` | 无 zh.pdf 侧缺省；`reading` 恒 dict（`{}`） | 全修 |
| PUT reader/position | 任何 task_id 都 200 | 404 + `document_version` 不符→409 `version_mismatch` | 全修 |
| GET/PUT /api/settings | 5 字段；PUT 吞未知键 | public() 全量 12 字段（glossary_dir/concurrency/engine/context_guidance/cors_origins/quota_*）；未知键→400 `settings 未知字段` | 全修 |
| GET /providers | 2 预设无 active/has_env_key | 6 预设 + `active`（按 base_url 匹配）+ `has_env_key` | 全修 |

## (a) server 有 mock 无（已补）

- translate **dedup/reuse 全链**：400 非法 id（normalize_arxiv_id 同口径含 `hep-th/NNNNNNN` 旧式+`:path` 斜杠）、`?status`/lang/prefer 校验、409 `duplicate_active`（带 task_id，前端 409→直接跳转路径）、200 `{reused:true}`（done/partial 命中）、prefer=fresh 旁路。dedup 键 `{id}|{ver}|{model}|{lang}` 对齐 cache_key 组分。
- share/import dedup：首导跑管线、重导 200 reused（用独立 id 2501.99999 避开 seed 恒命中）。
- settings/test：base_url 校验 400（http 仅 localhost/tailnet 放行）、`api_key:"bad"`→`{ok:false,detail}` 演示失败臂。
- DELETE 后 idem key 释放（对齐行删 key 可复用）。

## (c) mock 有 server 无

无。`pdfjsAssetsMiddleware` 是 dev 静态资源不属于 API 面。

## 不修/备注

- CSRF（local_only_mw sec-fetch-site/origin 403）mock 未实装——dev 中间件同源语境，跳过。
- 429 quota、reuse_hit→share_pack 422、upload 413/501 魔数路由：mock 无对应概念，记录不修。
- server `?download=abc`→400（int 解析失败），mock 按 falsy 放过——非数字输入前端不发，记录。
- a02 html seed 产物集补真实化：+src_tar/en_pdf/zh_src_zip（对齐 _stage_compile 无 zh.pdf 臂），documents 只留 original。
