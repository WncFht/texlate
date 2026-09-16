# xlat-sweep — xlat/ + validate/ 残余审计

> 2026-09-16/17。scope：xlat/ 全部 + validate/（l0.py/pipeline.py 只读——1d 活面）。3 文件小修，scope 324 测试全绿、ruff 净。

## 处置清单（已落盘）

- `xlat/retry.py:326` — `_assemble_slots`：`elif kind == "ph"` 与 `else` 两分支体完全相同（均 `decode_newlines(payload)`），合并为 `translated[payload] if kind == "slot" else payload`；[[SL]]/[[PL]]/[[SP]] 解码注释保留。
- `validate/l1.py:219` — `ensure_deps` 的 `except (OSError, SubprocessError): return False` 静默吞错（npm i 失败→静默降级 L0 无线索）：补 `log.debug` 带 CalledProcessError.stderr 尾 300 字符；新增 module logger。
- `validate/__init__.py:3` — docstring「九规则」→「十规则」（`_check_ph_in_cs` 已由 1d 接入 `validate_pair`）。

## l0.py 只读观察（1d 在飞，审计时文件仍在变）

- 检查器清单（`validate_pair` :903-920，10 条）：placeholder/brace/env/key/math/length/macro/item_glue/**ph_in_cs（新）**/protocol_echo。
- `_check_ph_in_cs` :840-871：`_PH_IN_CS_RX` :81 双侧夹持（尾邻必需字母排 `\cs[[PH]]` 合法高频形 + `\\` 控制符号）；`_mask_comments` 净差 Counter → ERROR；已接 :918。盲区 docstring 自记 `\cs[[KEY_n]]` 尾邻。
- `_check_item_glue` :813-837：`_lex` cs 流（注释豁免）、`item*` 净差 → WARN（`\itemsep` 等合法 cs 靠净差豁免所以只敢 warn）。
- `_check_protocol_echo` :873-897：`_ECHO_SIGS` :158-170 逐枚净差 → ERROR；未遮盖 zh 裸 count（注释内回显也抓）。
- **staleness（已转 1d）**：docstring :10「九条规则」、:325「七条规则」、:904「九组检查」三处计数未随 ph_in_cs 更新；:81 `_PH_IN_CS_RX` 单行 ruff format 会改写。
- **双 mask 实现并存**：textutil `mask_comments`（:51 import，placeholder/env_tokens/key_multiset 用）与本地 `_mask_comments` :316（仅 ph_in_cs 用）——语义同口径，建议统一或注明刻意异构。

## pipeline.py 只读观察

- `_intercept_leftover_ph` :311-335 四调用点：:1000 `_collect`、:866 `_load_resumed`、:913 `_route_chunks`、:665 `retranslate_chunk`。**`_intercept_ph_in_cs` 副层在飞**（1d → 项目体验方式 lane）。
- `client.py:702`/`batch.py:83`（bug-B 上下文）：probe `.strip()` 验收口径；`_parse_numbered` 空段整批退单翻。
- **建议项（只记）**：`_route_chunks` :915 纯 PH 路径 `self._emit(r)` 未包 try——与 `_collect` :1002「emit 绝不外泄」护栏不一致，state/on_result 抛错会炸穿 run() 路由中段；`_prompts` 缓存键 (kind,batch) 跨 `run()` 不重置（`_materialize` 重建 `_doc_glossary` 后旧 prompt 残留）——现调用点全单 run 新实例，理论风险。

## vulture 裁决

误报确认有消费方（保留）：by_rule/save_maps/save_cache/summary/hard_failures/all_failed/retranslate_chunk/chat_stream/discover_free_models/all_kinds/chunk_to_in/as_dict/PROVIDER_KEY_ENV/LOCAL_GLOSSARY_NAME/available/ensure_deps/sign/validate/cached_tokens/finish_reason/promo_end/context_tokens/max_output_tokens/supports_thinking/stage。

无生产调用方但保留（记档不删）：

- `client.py:42 HIDDEN_PROMPT_TOKENS` — 探针实测成本参数（154-566 取 465），docstring 注明供成本估算。
- `placeholders.py:72 find_all` — 有测试无生产调用、未入 `__all__`；一行工具函数。
- `placeholders.py:248 PhValidator` — 死类但承载 L0 替换缝 docstring；其 `→PhDiff` 签名与现网 `validate_fn: Callable→str` 已不一致，真要留应改 `typing.Protocol` 对齐。
- `retry.py:47 SLOT_MAX_CHARS` — spec 参数（docs/08:113）但**槽位超长二分从未实装**——`_make_slots`/`_stage_slots` 均无其用。

## 错误路径抽查

均合格：retry.py:309（log.debug）、client.py:592 usage_sink（log.exception）、client.py:710 probe（错误入 probe_error+redact）、client.py:730 list_models（带注释降级）、pipeline 各处 except（log.debug/exception 或 _skip 带 reason）、state.py:115 缓存损坏隔离（log.warning+改名不删）、state.py:219 记录级容错（log.warning）。`_sse_events` 坏 JSON 行跳过属 SSE 噪声口径合理。

## 残余建议（优先级）

1. **1d**：l0.py 三处规则计数 staleness + 双 mask_comments 统一 + :81 format；pipeline `_intercept_ph_in_cs` 副层落盘后 `_route_chunks` emit 加 try 护栏。
2. `SLOT_MAX_CHARS` 槽位二分实装或删常量（spec docs/08:113 承诺超 1500 字符槽先句界二分）。
3. `PhValidator` → `typing.Protocol` 对齐真缝或删。
4. `HIDDEN_PROMPT_TOKENS`/`find_all` 去留 leader 定。
