# worker-followup — #74 二次 dedup + #78 L2 EOF 归因 + llm_hook BYOK 落地

> 2026-09-16。入库 `7cce5f9`：worker.py(+260/-25 区段内)、texlog.py、validate/l2.py、e2e.py、test_server_l2.py、test_worker_audit_fixes.py(+325)。52/52 自属测试绿；全量 2163 pass + 4 failed（fixloop 在飞外部破坏）+ 4 skipped。

## Item A — #74 latest-alias 二次 dedup

- `worker.py:392` TaskCtx + `reuse_hit`；`:1492` `_post_resolve_reuse`：fetch resolve 出 pinned 版后 `cache_key_for(arxiv_id, resolved_version, model, target_lang, api_key=secrets.api_key)`（自动带 per_key 租户后缀）重算 → `find_reusable` 命中置 `ctx.reuse_hit`；未命中且无 active twin 时 `update_fields(cache_key=resolved_key)` 重钉键（`sqlite3.IntegrityError` 兜底）。双向覆盖：alias 单复用 pinned 产物 + alias 完成后被 pinned 请求复用。`prefer=="fresh"`/非 arxiv kind 跳过。
- `:1428` `_stage_fetch` reuse 臂：终态守卫 → `_materialize_reuse`（to_thread 拷贝+`_register`，路径穿越/缺 src 均 skip）→ `_finish_reuse`（二次终态守卫、非 done→partial+error_json 回放、publish 带 `_artifact_urls`+`_stats`）。**不写 `.fetch-done` 哨兵**——崩溃 resume 走正常重取+重 dedup（幂等）。
- `:1413` `_run_tex` reuse_hit 早退。

## Item B — #78 L2 runaway 归因洞（越 worker.py 授权落 texlog/l2/e2e）

- `texlog.py:72` `update_file_stack` 加 `popped` out-param：`)` 弹栈按序记录（含 None 占位）。
- `l2.py:122` `_EOF_ERR_RX`+`_EOF_POP_WINDOW=16`；`:153` `LogError.eof_file`+to_dict；`:290` `_eof_culprit`（head 命中 "File ended while scanning" 且 16 行内有真实文件弹出才回填——宁可 None 归父也不错怪）；`:312` parse 循环维护 last_pop。
- `e2e.py:477` `attr_error` 首支 eof_file→`_resolve_fidx` 肇事文件级归因（≤L2_MAX_CHUNKS 全块否则末块）；`:450` forward-exclusion：`s >= line_end` 块跳过（repro-2501 的 preamble `l.88` 错归修复）。

## Item C — llm_hook BYOK + share 硬闸

- `worker.py:698` `_PerCallTranslator`：每 translate 新建 `ChatClient(usage_sink=sink)`+finally aclose——`_drive` 每调用 `asyncio.run` 新 loop，共享 client httpx 池跨 loop 炸+绕计费红线。
- `:2524` `_llm_hook_pack` gate 序：share→None → `options.llm_hook` false→None → `TEXLATE_FIXLOOP_LLM=0`→None → `_translator_factory`（meter+close）→ 无 key/mock→None → 真 BYOK per-call hook+`_new_usage_meter`。
- `:2562` `_teardown_llm_hook` finally `_persist_usage`+关 clients；`:2430` `_run_fixloop` 接线。
- share 三闸：`_l2_enabled:2509`/`_env_judge_enabled:2198`/`_llm_hook_pack:2524` 首行 `kind=="share"`→off；`_l2_attempt:2771` 禁用原因 `share_zero_token`。

## 共享面变更（leader 已知情）

- `_persist_usage:3265` `=`→`+=`：旁路 meter（env_judge/L2/doc/llm_hook）只数本臂，原赋值覆盖主链总量——加性对既有臂严格更正确。
- `test_server_l2.py` `_attr_err_log` 写死 `l.5`→运行时扫 `这是译文` 行号：ctex 注入后移行号，#78 forward-exclusion 正确拒归后旧 fixture 落空变 no-op——钉真目标行。
- `_post_resolve_reuse` 重钉 cache_key 超字面 spec：pinned 请求也能复用 alias 产物；双闸兜住。

## 测试

`test_worker_audit_fixes.py` 新增 12 用例：`TestPostResolveDedup`×4、`TestL2EofAttribution`×3、`TestLlmHookShareGates`×5。`test_worker_audit_fixes+test_server_l2+test_share_apply` 52/52 绿。

## 风险留痕

- reuse 物化在 `_stage_fetch` to_thread，`_finish_reuse` 经 `_on_loop` 回 loop——cancel 竞态已测。
- re-key 窗口：fetch→re-key 间同 key 完成已先 `find_reusable` 查过；双写由 partial unique index+except 兜。
- `_PerCallTranslator` 每调用一 client——escalate 罕见路径，连接开销可接受。
- eof_file 归因靠 `)` 与错误行距 ≤16——超窗回 None 走原 tex_file 路径，不劣于修复前。

## 外部红（非本批）

`test_fixloop_missing_char.py::test_cjk_missing_drives_warmup_round`——`builtins.py` 在飞（fixloop 车道），verdict `acceptable_pdf` vs `clean` 分类漂移。
