# sel-translate 选区翻译 — 实现文档

> **状态**：已砍，未实施（2026-09-23 落地波裁决——无 assist 端点，`sel.xlat`/`sel.explain` 未注册，无 selxlat.ts/routers/selxlat.py）。保留为设计档案：若未来重开此功能，端点契约/配额模型/实验结论仍有效，代码落点须按届时现状重对。

综合自 2026-09-22 UX 调研波次的全部 st-\* 实验（st-endpoint / st-dict-prompt / st-backcheck / st-modal / st-quota，全部 verdict=works）与同波 ss-\* 选区面兄弟道（ss-floatbar / ss-ctxmenu / ss-cmdreg / ss-hotkeys / ss-menu-content / ss-pdf-sel / ss-dom-sel / align-zh-sid），并对齐生产代码现状（`src/texlate/server/`、`web/src/`）。引用文件均为仓库相对路径，仓库根 = `/home/fanghaotian/src/texlate/`。

## 目标

在阅读器（DomPane / HtmlPane / PdfPane 三窗格）内对任意划选文本提供即时翻译，不打断阅读流、不经过编译管线：

1. **段/句翻译**：划选 ≤4096 字符的英文文本 → 同步端点 → 450px 锚定 modal 展示中文译文（markdown 渲染）。
2. **词典模式**：划选 ≤3 词 → 同端点 `mode="dict"` → 返回结构化 JSON 词条卡（lemma/pos/senses/best/gloss_zh）。
3. **BYOK 同源**：复用任务级凭证解析（header > settings > env），server 形态可选匿名池（默认关）。
4. **成本受控**：双闸门配额（req/day + est_tok/day）+ 缓存免费 + in_flight=1 + 实结计量。
5. **可选分期**：回检标注（zh 句 → en 回链高亮），依赖 zh 句切分与对齐数据。

非目标：不修改 worker/pipeline/编译链；不动 dual.json 既有 chunk 契约（回检分期除外）；不做解释/总结等其他 assist 能力（ctxmenu 占位即可）。

## 交互规格

### 触发面（三入口，全部 `when=hasSelection` 门控）

| 入口                   | 行为                                                                                                                       | 实证数据                                              |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| 浮动工具条 FloatBar    | mouseup/键盘 Shift+ 选择后 ~55ms 内出现于选区首行附近（below-first + flip + 视口钳位）；按钮「翻译 t」「词典 l」「复制 c」 | ss-floatbar 25/25 PASS，scroll-follow 误差 ≤0.1px     |
| 上下文菜单 ContextMenu | 右键弹自定义菜单，sel 组：翻译/词典/复制（解释占位禁用项）；mousedown 即快照 selection（右键点在选区外会先塌缩选区）       | ss-ctxmenu 27/27 jsdom + 17/17 real Chrome，open 71ms |
| 热键                   | `t`=翻译、`l`=词典、`c`=复制——仅 hasSelection 时激活；Escape 关闭顺序 editor > cite > find > menu > info > help > sel      | ss-hotkeys 冲突表 60/60                               |

选区采集：以 `selection→[data-chunk]` walk 法定位归属 chunk（24.7µs，远优于全文 scan 42.5ms）；选区文本 `range.toString()`，上下文取选区所在 chunk 文本前后各 ≤500 字符（服务端再截断兜底）。**Chromium 会塌缩跨 pane 选区**——UI 只处理单 pane 选区，pane 归属随 selection anchorNode 判定。

### Modal（选区翻译主容器，st-modal 移植）

- 几何：`MODAL_W=450`，视口 `MARGIN=8`，锚 `GAP=10`，`MAX_H=0.72×vh`。
- 锚定双策略：**chunk 优先**（`data-chunk` 盒内分数坐标 + chunkId，reflow 下误差 0px/整段、17.5–66.4px/部分）→ **frac 兜底**（bodyEl 内容盒分数坐标，reflow 误差 163–320px）。`buildAnchor`/`resolveAnchor` 原样移植 `tmp/ux-research-20260922/exp/st-modal/st-modal.mjs`。
- 落位：`placeModal` below-first → 下方不足翻上 → 双侧不足取空大侧 → 双向钳位（**modal 永不出屏**为兜底不变式）。
- 「回到选区」：锚滚出屏外时先 `scrollIntoView({block:'center'})` 再落位（adv4 实证缺此步会算出 top=−15748）。
- 拖拽：`.st-head` pointerdown → `setPointerCapture` → `transform3d` 位移（合成层不触发布局）→ pointerup 烘回 left/top；拖过后 `dirtyDrag` 禁止自动回锚；resize 时钳回屏内。
- 关闭：Esc（capture+stopPropagation，进层栈）/ ×按钮 / 点正文空白。不阻塞阅读，允许同时只开一个实例。
- DOM：`.st-modal > .st-head(title+grip+×) / .st-src(3 行 clamp 显示原文) / .st-out(.st-committed + .st-tail) / .st-foot(复制/回到选区/status)`。
- 流式渲染（M3，可选）：`createMdStream` block 策略——`commitBoundary` 取最后一个不在 ``` fence 且不在 open `$$` 内的 `\n\n`，已提交块只解析一次，尾块每拍重渲，KaTeX 只扫新落地段（17 feeds 7.3ms vs full 36.8ms）。swe-2-medium 为假流式（deltas 末尾 ~0.3s 爆发，TTFT≈总时延），v1 走同步 + 骨架屏即可，SSE 升级位预留。
- 复用 `web/src/reader/markdown.ts` 的 `loadMdLibs()` + `finishChunk()` 做渲染后处理（外链 blank/反查/KaTeX），与正文同库同版本。

### 词典模式

- 触发：选区 ≤3 词时 floatbar/菜单/热键 `l` 走 `mode="dict"`；modal 切 dict 视图（词条卡布局：lemma+pos 行、senses 列表、best 高亮、gloss_zh）。
- 响应 JSON schema（dict_spike.py 验证，Arm A 10/10 + json_object 3/3 + 对抗 4/4 全部可解析）：`{lemma, pos, senses[{pos, en, zh}], best, best_why_zh, gloss_zh}`。
- 成本实测：prompt ~319–329 tok、completion ~148 tok、median wall 3.37s。

### 状态与错误面

- 请求中：modal `.st-tail` 显示骨架/ spinner + status「翻译中…」。
- 429：`{scope:peer|pool, retry_after_s}` → status 显示「额度用尽，Ns 后重试」+ 倒计时禁用重发。
- 502 provider_error / 网络失败：status + 重试钮。
- 503（匿名池关闭）仅 server 匿名臂可达：status「匿名额度未开放」。
- 复制按钮：合并 `.st-committed`+`.st-tail` innerText → clipboard。

## 数据/管线改动

**不碰编译管线。** 选区翻译是请求路径旁路：前端 → 新 REST 端点 → ChatClient → 网关 → 响应。涉及的数据面改动全部在服务端的「配额/计量/缓存/设置」四件套，无 worker/emit/编译改动。

### 端点契约（st-quota endpoint_spec 验证稿，逐字采用）

```
POST /api/task/{task_id}/xlat/selection          # 同步，不进 TaskRunner，无 SSE
Request:  {text: str(1..4096c), context?: str(服务端截 ±500c),
           target_lang?: str(缺省=任务 target_lang), mode?: "translate"|"dict"}
200:      {zh | dict: {…}, usage{prompt_tokens, completion_tokens},
           cached: bool, quota{peer_req_left, peer_tok_left, pool_tok_left}}
400 bad_request | 404 task | 409 status∉{done,partial} |
429 {scope: peer|pool, retry_after_s} | 503 pool off | 502 provider_error
```

### 配额与计量

- **双闸门 per-peer**（st-quota 对抗模拟结论：chars-only 闸漏 2.28M tok/day、req-only 漏 74k、双闸封至 ~39.4k）：`deps.sel_quota = OrderedDict[(peer,day) → {req, est_tok}]`，LRU 4096 peers（同 `deps.ip_quota` 模式）。推荐值 **30 req/day + 40k est_tok/day**，settings 可调。
- **估算口径**（成本模型回归，rmse≈53–78 tok）：`ptok_est = 819.9 + 0.1972×en_chars`、`ctok_est = 88.7 + 0.1828×en_chars`；过闸按估算，**计量与池扣减按 settled usage 实结**（swe-2 为 reasoning model，估算与实结偏差大）。
- **in_flight=1/peer**：并发第二发直接 429 retryable。
- **缓存免费**：命中 translation_cache 不计 tok（req 计数照记，防刷探测）。
- **匿名池**（server 形态可选）：SQLite 持久化 `sel_meter(scope_key, day, req, ptok, ctok)`，`anon_xlat_pool_tokens_per_day` 默认 0=关→503。池规模参考：网关 ~550 out_tok/s 的 2/5/10% ≈ 8.4k/21k/42k 次 p50 选区/天。

### 缓存

复用 `translation_cache` 表，key 前缀 `sel:{sha256(model|target_lang|normalize(text))}` 独立命名空间（与 SegmentCache `{cfg_hash}:{seg_key}` 同思路但不共享桶——选区文本无 placeholder 掩码语义）。normalize = NFKC + 折叠空白。dict 模式 key 前缀 `seld:`，value 存 JSON 串。

### Prompt

- `mode="translate"`：v1 复用 `build_system_prompt(kind='para', …)`（~820 tok 地板，含 PLACEHOLDER_CLAUSE——选区内若含 `[[TYPE_n]]` 掩码须原样保留）。优化位：新增 `kind='sel'` 瘦身 prompt（~350 tok，p50 成本 −49%），质量需 A/B 后启用，做 settings 开关。
- `mode="dict"`：SYSTEM prompt 与 USER_TMPL 逐字取自 `exp/st-dict-prompt/dict_spike.py`（“You are a dictionary engine inside an academic-paper reader…” + `Span: «{span}»\nSentence: "{ctx}"`），`response_format={"type":"json_object"}`。
- user 消息 = text + context 拼接，context 服务端硬截 ±500c。

### ChatClient 接线

`Secrets.from_auth(auth, model=row["model"])` → `ChatClient(base_url, api_key, dialect)` → `chat()`（同步端点用非流式；`chat_stream` 留给 M3 SSE 升级）。`usage_sink` 回调 → UsageRecord → meter repo。**已知坑**：`_sse_events` 会静默丢弃网关 in-band error frame → `content==''` 且无异常——端点必须检测「空内容 + 无 err」重试 1 次，仍空 → 502 provider_error。

### 回检标注数据（M4 可选分期）

st-backcheck 产出 per-chunk 对齐图：`{seq, kind, en_sents[], zh_sents[], beads[], zh_ann[{en_ref[], bead, conf, flags[], drops[], adds[]}]}`，9 文档 1553 chunks 实测 99.8% zh 句 1:1 回链、conf high 87.1%、~5.7% zh 句带 flag（split/merged/drop/add/term?/untranslated-run）。落地路径二选一：a) emit 期写进 dual.json chunk 新字段 `sents`（chunk schema 加字段，FileKind 不动）；b) 独立 artifact（需 `types.ts` FileKind + `DB_TO_URL_KIND` 新增 kind）。zh 句侧定位用 align-zh-sid 裁决的 spike B：前端 TreeWalker 按 `[data-chunk]` 重切分（JS 移植 `zh_sentence_spans`，~105 LoC，~1100 spans/188KB doc，49% sid 跨多 text node → 契约是 sid→element-set）。parity 上限 93.4% chunk-exact；真解 `⟪S0000⟫` sentinel 协议留作远期。

## 前端改动（文件级）

新增文件：

- `web/src/reader/selxlat.ts` — 选区采集（selection→chunk 切片、context 抽取、normalize）、`buildAnchor`/`resolveAnchor`/`placeModal`/`commitBoundary`/`createMdStream` 移植（框架无关纯函数，直接抄 st-modal.mjs）。
- `web/src/reader/SelModal.tsx` — Solid 组件，`<Portal>` 挂 body，createSignal 驱动 open/anchor/status/dict 视图；拖拽/Esc/resize/回到选区逻辑移植 `createModal`。
- `web/src/reader/FloatBar.tsx` — 浮动条（ss-floatbar 移植：show ~55ms、scroll-follow、pane margin 变化重定位——adv 实证 margin 变无 scroll 事件会留 stale 位，需监听 resize+layout）。
- `web/src/reader/ContextMenu.tsx` + `web/src/reader/cmdreg.ts` — 菜单与命令注册表（ss-ctxmenu/ss-cmdreg 移植：when-grammar、ctx keys `hasSelection/onCite/onZhBlock/onChunk/inInput/paneSide`、`snapshotCtx`、mousedown 快照 selection、Esc/外侧点击/pane-scroll-capture 关闭）。
- `web/src/styles/selxlat.css` — modal/floatbar/menu 样式（沿用 cite.css 的卡片视觉语言）。

修改文件：

- `web/src/api/types.ts` — 加 `SelXlatRequest`、`SelXlatResponse`、`SelDictResult`、`SelQuota`；M4 时 `DualChunk` 加 `sents?` 或 FileKind 新增。
- `web/src/api/rest.ts` — `api` 对象加 `xlatSelection(taskId, body)`，**显式 `AbortSignal.timeout(30_000)`**（默认 `REQUEST_TIMEOUT_MS=15_000` 会剪掉 p99 16.23s）；429 透传 `retry_after_s`（`toApiError` detail 扩展或新 code）。
- `web/src/reader/DomPane.tsx` — bodyEl 加 `contextmenu` + `selectionchange`/mouseup 钩子 → 上报 `{text, rect, chunkId, side}` 给 ReaderView；不碰既有 CiteCard 监听组。
- `web/src/reader/HtmlPane.tsx` — 同 DomPane 钩子集（marked 渲染层同样挂 `[data-chunk]`）。
- `web/src/reader/PdfPane.tsx` — 钩子挂 `s.viewer.container`（textLayer `user-select:text` 原生可选）；注意拖过链接塌缩选区、findbar 开关清选区——触发前快照。
- `web/src/reader/PaneSlot.tsx` — 透传 `onSelection`/`onContextMenu` props。
- `web/src/reader/ReaderView.tsx` — keydown 表加 `t/l/c`（when hasSelection，cmdreg 判定）；Esc 层栈统一注册（与 CiteCard 的 document capture 排序——CiteCard 先注册会先吃 Esc，sel 层须进同一层栈管理器）；挂 `<SelModal>`/`<FloatBar>`/`<ContextMenu>`；供给 ctx（`selectionText/hasSelection/onChunk/paneSide`）。
- `web/src/stores/settings.ts` — `selXlatEnabled` 开关（默认开）。
- `web/src/i18n/en.ts` + `web/src/i18n/zh.ts` — 新增 `selXlat` 组：`translate/lookup/copy/copyAs/source/reanchor/copied/copyFailed/translating/quotaPeer/quotaPool/retryAfter/providerError/poolOff`。
- `web/src/styles/app.css` — `@import` 链尾追加 `selxlat.css`。
- `web/src/test/` — 新增 `selxlat.test.ts`、`selModal.test.ts`（沿用 domPane.test.ts 的 vitest+jsdom+solid render harness）。

## 后端改动

新增文件：

- `src/texlate/server/routers/selxlat.py` — 照 `refs.py` 叶模板 `register(app, deps)`。handler 阶梯：
    1. `_read_body`（4MB 闸+CT 415+ 坏 JSON 400 白拿）→ 字段校验 `text 1..4096c`、`context` 截 ±500c、`mode∈{translate,dict}`、`target_lang∈TARGET_LANGS`（缺省取任务行）；
    2. `deps.get_task` → 404；`status∈{done,partial}` else 409（tasks.py retranslate 同款先例）；
    3. `deps.auth(request)`：`source="none"`（server 匿名）→ 池臂：`pool_per_day>0` else 503，扣 pool；否则 `Secrets.from_auth` → 用户 key 臂；
    4. `in_flight` 检查 → peer 双闸（`deps.sel_quota`）→ 429 `{scope,retry_after_s}`；
    5. `store.cache_get(selkey)` → hit → 200 `cached:true`；
    6. `ChatClient.chat`（dict 模式 `response_format=json_object`）→ **空内容检测 +1 次重试** → 仍败 502 `provider_error`；429/timeout 上抛归一 502/429；
    7. `usage_sink` → meter repo 实结 + peer 桶 est→settled 修正 + pool 扣减；
    8. `cache_put` → 200 带 `quota{…}` 余量。
       dict 模式另加 JSON parse 失败重试 1 次。

修改文件：

- `src/texlate/server/routers/deps.py` — `AppDeps` 加 `sel_quota: OrderedDict`（4096 LRU）、`sel_inflight: set[str]`、meter repo 句柄。
- `src/texlate/server/routers/__init__.py` — `register_routers` 追加 `selxlat.register(app, deps)`。
- `src/texlate/server/app.py` — `request_gate_mw` server 匿名 401（~line 370）前加白名单：`_route_path` 匹配 `POST /api/task/*/xlat/selection` 放行（池臂在 handler 内自决）。
- `src/texlate/server/settings.py` — `_FieldSpec` 表加 `anon_xlat_pool_tokens_per_day`(int,0)、`sel_xlat_peer_req_per_day`(int,30)、`sel_xlat_peer_tok_per_day`(int,40000)、`sel_xlat_context_chars`(int,500)、`sel_xlat_slim_prompt`(bool,false)。
- `src/texlate/server/store/_common.py` — DDL 加 `sel_meter(scope_key TEXT, day TEXT, req INT, ptok INT, ctok INT, PRIMARY KEY(scope_key,day))`；新 repo 文件 `store/_selmeter.py` 照 `_usage.py` UsageRepo upsert 模板。
- `src/texlate/xlat/prompts.py` — M2+ 加 `kind='sel'` 瘦身 system（~350 tok），`build_system_prompt` kind union 扩展。
- `src/texlate/xlat/client.py` — 不改；端点按 `worker/translate.py:639` 同款构造。测试注入：`AppDeps` 或 `app.state` 挂 `selxlat_client_factory`（默认可调 `ChatClient`），pytest patch 之。

不改动：`worker/`、`translate.py`、emit、dual.json chunk 契约（M4 除外）、`TaskRunner`（选区请求永远同步直答，不进队列）。

## 测试计划

后端 pytest（`tests/server/test_app_endpoints.py` 模式，`TestClient(make_app(tmp_path))`，`client.portal.call` 触异步面）：

- 契约阶梯：200 正常 / 400（text 空、>4096c、mode 非法、lang 非法）/ 404 坏 task / 409 非 done|partial 任务。
- 配额：灌满 peer req 闸 → 429 `scope=peer`+`retry_after_s`；灌 tok 闸同理；跨日重置；in_flight 并发第二发 429。
- 匿名臂：server 形态无 `X-Texlate-Key` + `pool=0` → 503；`pool>0` → 200 且池计数递减；带 key → 走用户臂不动池。
- 闸白名单：server 形态匿名 POST 不被 `request_gate_mw` 401 截杀（对照组：任意别的 mutation 仍 401）。
- 缓存：同 text 二次 → `cached:true` 且 mock client 调用数不涨；normalize 后等值文本命中。
- 静默空流：mock 返 `content=''` → 断言重试一次 → 仍空 → 502 `provider_error`；dict 模式坏 JSON → 重试 → 502。
- 计量：`sel_meter` (scope,day) 行 req/ptok/ctok 聚合正确；cache hit 不计 tok 计 req。
- 429 透传：mock 网关 429（body 带 retry_after）→ 端点 502/429 且 retry_after 进响应体。

前端 vitest+jsdom（`web/src/test/` harness，`vi.stubGlobal('fetch')`）：

- `buildAnchor`/`resolveAnchor`：reflow 矩阵（chunk 锚 0px 断言、frac 误差上界断言）；chunk 缺失退化 frac。
- `placeModal`：below/above/空大侧/双向钳位/永不越屏矩阵。
- `commitBoundary`：``` fence、open `$$`、嵌套、末尾边界（st-modal fixtures 移植）。
- `SelModal`：openAt 落位、拖拽 transform→bake、Esc 层栈（先注册 CiteCard 再 Esc 只关 cite）、「回到选区」scrollIntoView 路径、resize 钳位。
- `FloatBar`/`ContextMenu`/cmdreg：hasSelection 门控、mousedown 快照、关闭路径。
- `rest.ts`：`xlatSelection` signal ≥30s；429 → ApiError 携带 retry_after。
- M4：`zhseg` JS 移植 parity 对拍（抽样 chunk，sid 集合与 Python 版 ≥93% 一致）、sid→element-set 高亮渲染。

e2e 手动清单：三 pane 划选（dom/html/pdf textLayer）、跨 pane 拖选塌缩不炸、pdf 链接拖选、窗口换宽后 modal 回锚、settings 开关 kill-switch、server 形态匿名池开/关两态。

## 工作量与分期

| 期                      | 内容                                                                                                                                                                                                        | 估算   |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| **M1 核心闭环**         | selxlat.py 端点（同步、双闸、缓存、计量、空流重试）+ deps/app/settings/store 接线；前端 selxlat.ts + SelModal（同步渲染 + 骨架屏）+ FloatBar + `t` 热键 + DomPane/HtmlPane 钩子 + rest.ts/types.ts/i18n/css | 2–3 天 |
| **M2 入口补全**         | ContextMenu+cmdreg 落地、PdfPane textLayer、Esc 层栈统一（含 CiteCard 收编）、settings 开关、匿名池                                                                                                         | 1–2 天 |
| **M3 体验增强**         | dict 模式（端点 mode+ 前端词条卡视图）；`kind='sel'` 瘦身 prompt + A/B；可选 SSE 流式 + block 渲染（swe-2 假流式下收益小，按上游模型定夺）                                                                  | 1 天   |
| **M4 回检标注（可选）** | backcheck 数据落地（dual.json `sents` 字段或独立 artifact + FileKind）、zhseg JS 移植、zh 句→en bead 高亮 UI                                                                                                | 2–3 天 |

M1 即可独立交付用户价值；M2/M3 可按反馈重排；M4 是独立增量，不阻塞主线。

## 风险

1. **网关 429 闩锁**：实测 ~6 req/min 突发即触发 ~60s 闩锁，429 body 携带 `retry_after` 35–885s。端点必须把 retry_after 透传前端；前端做倒计时禁用 + 提示。in_flight=1 天然削峰。
2. **静默空流**：`_sse_events` 丢弃 in-band error frame → `content==''` 不抛异常。端点不显式检测会把空串当译文写进缓存——**检测 + 重试 + 仍空 502 是硬要求**，且空结果绝不入缓存。
3. **假流式**：swe-2-medium deltas 末尾 ~0.3s 集中爆发（TTFT≈总时延）。M3 的 SSE+block 渲染对该模型收益≈0，仅为未来真流式上游预留；v1 同步即可。
4. **Prompt 地板成本**：para prompt ~820–921 tok 固定开销占 p50 选区（135c）成本的 ~85%。瘦身 prompt ~350 tok 可省 ~49% 但翻质量未验证——必须 A/B 后才默认启用，先留 settings 开关。
5. **对抗泄漏**：单 chars 闸可被「最小 text×高频」击穿（模拟 2.28M tok/day）；req-only 漏 74k。必须双闸且 tok 闸按估算口径先扣后修；池扣减必须按 settled 实结（reasoning model 估算漂移大）。
6. **锚漂移**：reflow 下 frac 锚误差 163–320px（部分选区）/272px（整段），chunk 锚 17.5–66px/0px。必须 chunk 优先+frac 兜底；`data-chunk` 缺失的 pane 区域退化为 frac 仍可接受。
7. **Esc 层栈竞态**：CiteCard 用 document capture+stopPropagation 且先注册先吃 Esc——sel modal/menu 若各自 capture 会互相抢。必须统一层栈管理器（顺序 editor>cite>find>menu>info>help>sel），M2 收编 CiteCard。
8. **跨 pane/链接塌缩**：Chromium 塌缩跨 pane 选区；pdf textLayer 拖过 `<a>` 塌缩、findbar 开关清选区。触发面必须 mousedown 快照 selection，UI 对塌缩静默容错（选区没了就收 floatbar）。
9. **客户端超时**：`rest.ts` 默认 15s 会剪掉 p99 16.23s——`xlatSelection` 显式 ≥30s，否则长尾必现 AbortError。
10. **zh 句切分 parity 上限**：JS 移植与 Python 版 ~93.4% chunk-exact（~6% 漂移），回检 en_ref 高亮精度受限；`⟪S0000⟫` sentinel 是真解但伤 dual.json 契约，M4 前不做。
11. **回检 FP 面**（M4）：单位改写（5.1–10B→51–100 亿）、CJK 数字、合法引文会误报 untranslated-run/drop——UI 标注需弱化呈现（虚线下划线而非错误色）。
12. **池账目重启漂移**：peer LRU 重启清零（可接受）；SQLite 池按 flush 粒度近似持久化，进程被杀账目停在上次落盘点——额度是软预算，不需要强一致。
13. **dict 解析面**：json_object 模式实测 13/13 可解析但仍需 parse 失败重试 + 降级到纯文本展示兜底。
