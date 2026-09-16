# scout-spliceguard — PH-in-cs 防线精确插入点（交付 1d 的 ready-to-apply 规格）

> 2026-09-16。只读侦察 + `tmp/scout-spliceguard/rx_probe.py` 实证（14/14 证据格命中）。未碰入库文件。

## 结论一行

双落点：① `validate/l0.py` 新增第 10 条规则 `_check_ph_in_cs`（Severity.ERROR，retry/回退由既有阶梯全免送达）；② `xlat/pipeline.py` 加 `_intercept_ph_in_cs` 同款 sibling 升格拦截（盖续跑/缓存旁路）。正则须双侧夹持 `\\[a-zA-Z@]+\[\[..\]\][a-zA-Z@]`——初稿 `\\[a-zA-Z]*\[\[PH` 实测 FP ~5% 合法尾邻。

## 管线流与最早拦截点

zh chunk 流：`translate` → `decode_newlines` → `repair` → **`validator(src, zh)`** → ChunkResult → `_collect` → `done_map` → `by_file`/`trans` → `reconstruct(res, trans)` splice。splice 爆炸点 `reconstruct.py:175` `expand()` 内 `PH_RX.sub`——`\fo[[MATH_1]]o` → `\fo$…$o`。

**最早可拦截点 = validator**（译文进 splice 前最后一道程序闸，且带重试配额）。`validate_pair` 唯一注入实现，四处同构：`e2e.py:215`、`worker.py:1859`、`worker.py:2686`（L2 回灌臂）、`bench/py/e2e_mock_bench.py:311`（bench 臂）；share 消费 `worker.py:806` 直调。validator 调用面（挂上即全覆盖）：`retry.py:252,261,280,284,357`、`pipeline.py:710,643`。

## 既有机制接入

validator err → 阶梯自动重试（corrector 三段式 / `[previous_validation_error]` 尾拼）→ 耗尽 → `fallback_orig`（retry.py:408-416）→ `ChunkResult{status="fault", skipped=True, translation=source, error_kind="validate"}`（pipeline.py:586-609 现成）。splice 闸 `_delivered`/`_PIPE_TO_DB` fault 不进 trans → `expand` 走 `chunks[idx].content` 原文回填（reconstruct.py:168-171）。不进 fixloop ✓。

**副层必要性**：`pipeline.py:515-523` 缓存命中直接返回未校验 zh——续跑 state/段级缓存旁路 validator。`_intercept_leftover_ph`（:311-335）在 `_collect:1000`、`_load_resumed:866`、`retranslate_chunk:665`、`_route_chunks:913` 四点调用是拦 stale 脏译的唯一闸；本缺陷同形 → sibling `_intercept_ph_in_cs` 挂同四点（fault+skipped+source+`ph_in_cs:N` warning+error_kind=validate）。

## 正则实证（关键修正）

```python
_PH_IN_CS_RX = re.compile(r"\\[a-zA-Z@]+\[\[[^\[\]\n]{1,48}?\]\][a-zA-Z@]")
# net-diff：Counter(rx.findall(mask_comments(zh))) - Counter(rx.findall(mask_comments(src)))
```

- **双侧字母夹持必需**：corpus_v3 抽 87 文件 5413 src chunks，合法尾邻 `\cs[[PH]]` 271 处（~5%）——`\protect[[REF_n]]`、`\em[[CMD_n]]`、`\S[[REF_n]]`——裸 `\\[a-zA-Z]*\[\[PH` 全标即灾难级 FP；`*` 还误吃 `\[[PH]]`（`\[` display-math + PH 合法），须 `+`。
- **净差口径必需**：src 存在合法同形态 2/5413（`\lq[[CMD_206]]angular-momentum`——CMD 体 `\` 头不融合），忠实回显须豁免；Counter 净差即 L0 house style。
- zh 侧判定正确：真 LLM 与 harness 挪位产出同一字符串签名；抓「后果签名」非「挪位行为」不错杀合法换序。
- 内层 `[^\[\]\n]{1,48}?` 与 `PH_FUZZY_RX` 同口径，连 `[[math_1]]` 小写变体/臆造 `[[FOO]]` 一起抓；`[[SL]]/[[PL]]/[[SP]]` 校验前已 decode 不在视野。
- `@` 与 `_lex`/`_CS_OR_SYM_RX`（l0.py:91,295）同口径；`\\fo[[PH]]o` 会被抓（word-split 非 cs-bomb 但同为挪位缺陷，retry 修正无害）——要严格限可加 `(?<!\\)`，建议不加。
- **残余盲区（记档不盖）**：尾邻 `\cs[[KEY_n]]`/`\cs[[AUTHOR_n]]`——KEY=裸 key（`smith2020`）、AUTHOR=人名，载荷恒字母头 → `\foo[[KEY_1]]`→`\foosmith` 融合弹；validator 签名 (src,zh) 拿不到 ph_map 判不了载荷首字符。v2 可按类型白名单补 `\cite[[KEY_1]]` 形态（KEY/AUTHOR 在 src 恒居括号内，zh 尾邻必为挪位）。本次 14 格证据全 mid-name，不在盲区。

## 插入点（给 1d）

**主层 `validate/l0.py`**：常量区 ~:135 加 `_PH_IN_CS_RX`；新 `_check_ph_in_cs`（`_check_item_glue` :797 隔壁同款 Counter 净差骨架）；`validate_pair` :868-869 挂线（item_glue 后、protocol_echo 前）；Severity **必须 ERROR**（`rep.ok` 只看 error :222-224，warn 不 gate）；docstring「九条规则」→ 十。

**副层 `xlat/pipeline.py`**：`_intercept_ph_in_cs(r)` 邻 `_intercept_leftover_ph`（:311），调用点 :866/:913/:1000/:665 各加一行；计数 helper 放 `textutil.py`（两层共用，语义逐字节一致）。

## 测试计划

- `test_validate_l0.py` 9 例：a. `\fo[[MATH_1]]o`→error；b. `\foo[[MATH_1]]` 尾邻→pass（关键 FP 对照）；c. `\item[[MATH_1]]x`→error；d. src `\lq[[CMD_1]]angular`+zh 忠实同形→pass（净差豁免实格）；e. 注释区→pass；f. `\cite{[[KEY_1]]}`→pass；g. `\\[[MATH_1]]`/`\[[[MATH_1]]`→pass；h. `\fo[[FOO]]o` 臆造→error；i. `\fo[[math_1]]o`→error。
- pipeline 副层：仿 `test_leftover_ph.py` 骨架新开 `test_ph_in_cs.py`——三件套+`ph_in_cs:N` warning+毒化 cache-hit 拦截+resume stale ok+splice 终端实证无 `\fo<payload>`。
- 验收口径：modec-core pipeC 8 格 mid-cs undefined_cs + postfix 6+1 格应消；bench 臂同 `validate_pair` 零改动自动生效。

## item_glue 守卫现状

已存在建制内：`l0.py:797-821` `_check_item_glue`——`_lex` cs 流（注释豁免、非裸正则）、净差计数 zh 多出 `item*` cs 名、**Severity.WARN** 纯遥测。fixloop 侧 `cs_targeted_fix._SPLIT_HEADS`（builtins.py:889-901 含 "item"）。「纵深防御非根修」定性准确——新规则是它缺的 ERROR 级姊妹。
