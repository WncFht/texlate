# misc-pack 实现文档

杂项加固包，四个互不依赖的小特性，可独立分期落地：

| 编号 | 特性                                  | 实验          | 一句话                                                                                    |
| ---- | ------------------------------------- | ------------- | ----------------------------------------------------------------------------------------- |
| M1   | 缺 key 防护链                         | ms-keyless    | local 形态无 key 提交今天静默产全量假译文并以 done 交付，且毒化段缓存与任务级复用         |
| M2   | arXiv ID canon 扩展                   | ms-urlnorm    | `normalize_arxiv_id` 30 形态只过 19；升级为 canon() 单源，前端 `parseArxivId` 同步放宽    |
| M3   | lake 格位 pin + CAS GC 接线           | ms-pin        | evict 已认 `pinned` 字段但无 pin/unpin 动词、catalog 重建丢 pin、CAS `gc_sweep` 零调用方  |
| M4   | 参考文献 .bib 导出（+kept refs 选配） | ms-bib-export | src.tar .bib verbatim 覆盖 68.2% key，id 臂走远端 bibtex，meta 合成兜底；S2 恒 429 不进链 |

证据文件：`tmp/ux-research-20260922/exp/ms-{keyless,urlnorm,pin,bib-export}/`、canon 契约 `docs/spec/arxiv-id-canon.md`、设计稿 `kept-refs-design.md`（本目录）。

---

## 目标

### M1 缺 key 防护（P0，正确性/防毒）

实测链：`submit.ts:41` 无条件 `api.translate` → `options.ts:107` `byok()` 空 key 返回 `undefined` → 无 `X-Texlate-Key` 头 → local 中间件（`app.py:346`）只查回环/Host → `resolve_auth` 三级落空 → `AuthContext(api_key="", source="none")` → `create_and_enqueue`（`deps.py:329`）照常建行入队 → 202 跳 reader → worker `translate.py:650` 记一次 `mock_translator` warning 后 `MockTranslator()` 上场 → 4/4 chunks `status=ok`、zh 全是占位译文 → `done` 交付 + 6 件产物（含 zh.pdf）。

实测毒化面（`exp/ms-keyless/improvements.json` K1–K9 + 160 行中毒缓存实证）：

- mock 译文写入 `translation_cache`（实测 160 行「这是译文」入库），fresh+ 真 key 重交同论文仍 156/157 命中 mock、零 LLM 调用；
- `find_reusable` 命中 mock done 行 → 带 key 用户 200 reused 拿到垃圾任务；
- done 任务 warnings 永不渲染（`ResultBody` 只在非 done 终态面板挂 warn-list）；
- 小文档坏 key 不触发 `auth_fail_threshold=3` 熔断 → 落 `partial` 且 error.code 被 `compile` 顶替（应 `provider_auth`）；
- done ∉ `RETRYABLE_FROM`（实测 retry→409），mock-done 任务无重跑入口；`retranslate` 无 key 仍 202 重 mock。

目标：无 key 请求在建行点即落 `needs_auth`（复用既有内联 key + retry UX），mock 只对显式 opt-in（`TEXLATE_TRANSLATOR=mock`/测试桩）可达且绝不写共享缓存，存量 mock 任务可识别、可重跑、不可复用。

### M2 arXiv ID canon（P1，输入面）

现状 `arxiv/fetch.py:143-181`：30 形态表 baseline 只过 19。11 个缺口已定位：老 id 小写 class（`cond-mat.mes-hall`→REJECT）、`ar5iv.org` 独立域、alphaXiv abs/pdf、4 种 DOI 形态（doi.org URL、`doi:` 前缀、裸 `10.48550`、`dx.doi.org`）、LANL 镜像、老 id DOI 内嵌 slash（`10.48550/arXiv.hep-th/9901001`）、class 保留致分键（`math.GT/0309136` 收下不剥 → 与 `math/0309136` 双键双任务）。

目标：按 `arxiv-id-canon-spec.md` 落地 `canon()` 单源——剥离序管线化、旧形 class 剥壳 + archive 小写化 + `V`→`v` 归一、MM 校验 + strict_era 闸、`--`↔`/` safe_id 回流并进 canon 前置步；`normalize_arxiv_id`/`valid_id`/`req_base_ver` 全仓 8 个调用点变薄壳零签名变化。对抗面约束（44 探针实测）：extended 臂 6 个回归（裸 id 的 `.pdf` 尾与首尾 `/` 容忍丢了）与 8 个过收（`ftp://`/`javascript://` 任意 scheme、`lanl.gov`/`www.lanl.gov` 裸域、`:8080` 端口、`//` 双斜杠、alphaxiv 未实证动词 `/overview`）必须不回带——锚定前缀剥壳（不 urlparse 任意 host）天然堵死端口/双斜杠/怪 scheme。

### M3 lake pin + CAS GC（P2，bench 运维）

字节删除动词全景实测只有四个：`lake.evict`（catalog 三层）、`cli prune → runs.remove_cell_tree`（`work/{sid}`）、`lake.shrink_shell`（终态格瘦身）、`ledger.seal_gc`（raw 段水位闸）；`sweep()` 自身除封账 raw 段外不删字节。缺口：

- `cli lake` 只有 `status|evict|register|absorb`——**无 pin/unpin**；
- `T_LAKE_CELL` 事件只带 `{id,idc,state,source,bytes}`（`events.py:61/90`）——catalog 重建丢 `pinned`/`manifested`/`orphan`/`last_used_at`/`regen_cost` 五个字段（实测 `catalog_only_keys_lost_on_rebuild`）；
- pin 语义实测：`pinned` **字段**经得起 `mark_used` 与状态转移；`state=="pinned"` 会被下一次 `set()` 静默解 pin（`state_pin_silent_unpin:true`）——**pin 必须走字段不走状态**；pin 标记绝不许是格内文件（`shrink_shell` 实测吃掉 pin marker）；
- `cas.gc_sweep`（`cas.py:179`，nlink==1 + grace 闸）**零生产调用方**——CAS 对象无界泄漏；
- zh-store manifest（5481 行）无 pin 字段（预留面）。

目标：`lake pin/unpin` 动词 + pin 随 lake_cell 事件落账（重建不丢）+ `lake status` 出 pinned 面 + `cas.gc_sweep` 接进 `sweep()` 尾段。run 格 pin 不在本期（work 格已有 `vault_check` paid 闸，pin 需求未证实）。

### M4 .bib 导出（P1，引用面收口）

宇宙 494 key（bibitem ∪ cited ∪ cite-dest）：Lane A verbatim（src.tar `.bib` 原文）覆盖 337/494=68.2%（9 任务 5 带 .bib；2 key 因 hyperref 把 `cite.*` dest 小写化需大小写折叠兜底；33 条 entry 依赖 `@STRING` 宏——导出必须携带 defs 闭包否则 .bib 断裂）；Lane B 只有排版文本 157/494=31.8%，其中 80 条能抽 id（78 arXiv+2 DOI）走远端出版级 bibtex，77 条无 id 落 `@misc{note={text}}`。远端实测：DataCite `doi.org/10.48550/arXiv.<id>` Accept x-bibtex 7/8（重试→8/8，SSL 抖动要重试）；crosscite 真 DOI 2/3（bbl 里 DOI 百分号编码须 unquote，修复→3/3）；Crossref bibliographic 12 探 10 回包但 title-overlap≥0.5 门控只剩 5/12——**错配率高，不门控即毒导出**；S2 全程 429，导出链不得依赖 S2。远端延迟 p50 2177ms / max 20271ms——必须并发闸 + 总 deadline+ 降级兜底。

目标：`GET /api/task/{id}/refs.bib?keys=` 端点（Lane A verbatim + Lane B id→远端 + Lane C meta 合成三臂），Toolbar 下载清单出 `refs.bib` 项；Phase B 叠加 kept_refs 收藏（SQLite 表 + CiteCard ☆ 钮）让 keys 子集可挑。

---

## 交互规格

### M1 缺 key

- **提交时（Home）**：`settingsStore.settings()?.has_api_key === false` 且 `optKey` 空 → 提交钮下挂内联提示「未配置 API Key →」链 `#/settings`（P1 级预检，软提示不 disabled——服务端闸才是权威；多 keyless 场景[无 settings 键但有 env key]提示可误报，故不禁用按钮）。
- **建行即 needs_auth**：`auth.source=="none"` 且非显式 mock → `create_and_enqueue` 建行后直接落 `needs_auth` 终态（不回 202 进队列），返回行带 `reader_url`——前端照跳 reader，ResultBody 既有 needs_auth 面板（内联 key 输入 + retry，`retry` 端点 `tasks.py:306` 已对 needs_auth 行强制 `X-Texlate-Key`）即统一缺 key 落点。
- **同 cache_key 再撞 needs_auth 行**：`deps.py` IntegrityError 臂现状只认 active 行（needs_auth 行撞键会发无 task_id 的 409 死信）——扩臂：`find_active_by_cache_key` 之外再查终态 `needs_auth` 行，命中则 200 返回该行（`{reused:true}`），前端跳去补 key。
- **401 富错误**：`ApiError.code=="auth_required"` 时 Home/Upload 错误面渲染结构化块（文案 + `#/settings` 链接 + 内联 key 输入复用 ResultBody authKey 模式），替换今天的裸文本。
- **done 也见 warnings**：done 且 `task.warnings` 非空 → reader 出持久 banner（复用 `.warn-list` 样式），`mock_translator` 警告不再只在 ~0.2s translating 窗口露脸。
- **mock 任务重跑**：done 且 warnings 含 `mock_translator` → ResultBody 出 retry 钮（服务端对 `mock_run` 标记行放行 done→queued 并强制 fresh 口径——绕过段缓存与 find_reusable）。

### M2 canon

- Home 输入框接受：DOI 四形态、`arXiv:`/`oai:` 前缀、`ar5iv.org`/`alphaxiv.org` URL（限 `abs|pdf|html` 动词、http/https scheme）、`[cs.CL]` 尾注、`.pdf/.tar.gz` 扩展名尾、safe_id `--` 回流形、老 id class 任意形（剥壳收编）。
- 非法输入反馈不变（`home.invalidId` + aria-invalid）；`canon` 的 `CanonError.reason`（`bad_shape|bad_month|bad_era|bad_version|unsafe`）供服务端 400 detail 文案派生——前端不逐因渲染，统一定格式错。
- **不收**（对抗实测定案）：LANL 镜像域名、非 http(s) scheme、带端口、`//` 双斜杠、alphaxiv `/overview`（未实证动词）、ADS bibcode、`arXiv preprint` 散文形、`v0`/`v1234`、寄生域名、`..` 逃逸、unicode 数字。

### M3 pin

- CLI：`bench lake pin <idc>...` / `bench lake unpin <idc>...`（canon 归一 idc，同 `register` 臂的 `res.idc` 口径）；`bench lake status` 增 pinned 行数/字节面；`bench sweep` 尾段自动跑 `cas.gc_sweep`（24h grace）并 report `cas_swept`。
- pin 的格：`evict` 三层全跳（现状 `_pinned` 已认字段，保留 `state=="pinned"` 读兼容存量行）；`hydrate`/`mark_used`/状态转移不清 pin 位。
- zh-store manifest 行加可选 `pinned` 字段（append-only last-wins，importer 宽容透传）——本期只占位，无删除动词消费。

### M4 .bib 导出 + kept refs

- **导出入口**：Toolbar 下载清单追加 `refs.bib` 项（`kind` 走自定义 label，`url=/api/task/{id}/refs.bib?download=1`，`download` 属性直链）；无条件项——`CiteIndex.size>0` 或 kept>0 时才显，或恒显由服务端按可得 key 数定空稿。kept>0 时默认导 kept 子集，加 `?all=1` 出全量。
- **导出降级语义**：单 key 远端臂失败/超时 → 自动退 `@misc{key, note={text}}`；响应头 `X-Refs-Degraded: <n>` 报降级条数，文件头注释行列出降级 key——不 502 不打错。
- **kept refs（Phase B）**：CiteCard foot 加 ☆/★ 钮（与 jump/ext 链并列，`cite-card-foot` 既有挂点）；ReaderView mount 时 `GET /refs/kept` 一次取回；toggle=乐观写+PUT，失败回滚；任务删除 kept 行随 `ON DELETE CASCADE` 殉葬；BYOK 换租户后不可见（与任务同 blast radius）。
- DomPane 路补卡：`PaneSlot` 给 DomPane 补传 `citeMeta`+keep 回调；key=`bib.bibN` 序数 id，payload 由 `li.ltx_bibitem` clone 构造（text=clone.textContent、label=`.ltx_tag_bibitem`、ids=`extractRefIds(text)`）。

---

## 数据/管线改动

- **M1**：无 schema 迁移必需。`options_json` 内嵌 `mock_run:1` 内部审计键（先例：`reuse_hit` 等 `_SNAPSHOT_OPTS_DROP` 口径，snapshot 不透出）——`find_reusable`/`find_active_by_cache_key` 命中集按此键排除；retry 闸对 `mock_run` 行放行 done。
- **M2**：`arxiv_id` 落库值变为 canon base——`math.GT/0309136` 与 `math/0309136` 自此同 cache_key 同 task 键（**去重语义变化是特性**，但存量异键任务/缓存不迁移）。
- **M3**：`events.py` `OPTIONAL_KEYS[T_LAKE_CELL]` 扩 `{pinned, manifested, orphan, regen_cost, last_used_at}`；`lake._lake_event` 转发这些键——catalog 重放重建自此保住五个易失字段（今天只投影 `{source,bytes}`）。zh-store manifest 行 schema 加 `pinned`。
- **M4 Phase B**：`store/_common.py` DDL 串追加 `kept_refs` 表（`task_id REFERENCES tasks(id) ON DELETE CASCADE, ref_key, payload JSON≤64KB, created_at, updated_at, PK(task_id,ref_key)`）；新叶 `store/_kept.py`（list/put/delete）+ `__init__` 门面转发。**不走 sidecar 文件**——slim/retention 抹一切未登记路径（reading.json 同坑实证），用户数据必须进 DB。

---

## 前端改动（文件级）

### M1

- `web/src/pages/Home.tsx`：读 `settingsStore.settings()?.has_api_key`，提交钮下挂条件内联提示（新 i18n 键 `home.noKeyHint`）。
- `web/src/home/submit.ts`：catch 臂 `code=="auth_required"` → 结构化错误（链 #/settings）；409 臂不变。
- `web/src/pages/Reader.tsx`：`resultStatus` 之外加 `doneWarnings` memo（done && warnings.length）；downloads memo 追加 refs.bib 项（M4）。
- `web/src/reader/ResultBody.tsx`：done+mock warning 臂出 retry 钮（st 传 `"done"` 时 RESULT_TEXT 缺键——加 `done` 键或单列 banner 组件）；needs_auth 面板逻辑不变。
- `web/src/i18n/{zh,en}.ts`：`home.noKeyHint`、`reader.mockNotice`、`reader.resultDone`（如需）等 ~4 键。

### M2

- `web/src/home/search.ts`：`parseArxivId` 同步 canon 面——ARXIV_RE 老 id class 放宽 `\.[A-Za-z][A-Za-z-]*`；前缀剥壳加 DOI/oai/尾注/扩展名步；仍保持「比服务端窄」哲学（怪输入留服务端 400）。`extractRefIds`（`reader/citations.ts:53`）是 scan 口径不是 canon，**不动**。
- `web/src/test/parseArxivId.test.ts`：30 形态表移植 vitest。

### M4

- `web/src/stores/keptRefs.ts`（新，~80 行）：`kept=Signal<Record<key,payload>>`、`load(taskId)`、`toggle(key,payload)` 乐观写 + 回滚；随 ReaderView 实例局部 signal。
- `web/src/pages/Reader.tsx`：mount effect 并列 `citeIndex` effect（~L346）调 `keptRefs.load`；downloads memo 追加 refs.bib 条件项。
- `web/src/reader/CiteCard.tsx`：`CiteCardBody` props 加 `kept?: boolean`、`onToggleKeep?()`，foot 加 ☆/★ 钮。
- `web/src/reader/PdfPane.tsx`：开卡时组 payload（entry + `citeMeta(key)` 快照）回传 toggle。
- `web/src/reader/PaneSlot.tsx` + `DomPane.tsx`：补传 citeMeta/keep 回调（PaneSlot.tsx:92-104 现状不传 DomPane——缺口须补）。
- `web/src/api/rest.ts` + `api/types.ts`：`refsKept(taskId)`/`refsKeepPut(taskId,key,payload)` 客户端 + `KeptRef` 类型。
- `web/src/styles/cite.css`：`.cite-card-keep`（与 `.cite-card-jump` 同族）；`tasklist.css`/`Toolbar` 无改（DownloadItem 复用）。
- i18n：`cite.keep/cite.kept/cite.keepRemove/files.refsBib` 等 ~4 键。

### M3

无前端改动（bench kernel CLI 面）。

---

## 后端改动

### M1（`src/texlate/server/`）

1. `routers/deps.py::create_and_enqueue`（~L234 auth 解析后）：`auth.source=="none"` 且 `TEXLATE_TRANSLATOR!=mock` → 建行但**不入队**，直接 `transition(needs_auth)` 返回（202 + reader_url）；IntegrityError 臂补 needs_auth 行命中→200 返回。覆盖 translate/upload/shareImport 全部调用方（`tasks.py:103`、`upload.py:126` 同源）。
2. `worker/translate.py::_resolve_translator`（~L627）：无 key 臂改抛 `AuthError("未配置 API key")`——`core.py:182` 已把 `AuthError`→`provider_auth` fault；Mock 仅 `translator_factory`/`TEXLATE_TRANSLATOR=mock` 可达。显式 mock 跑：`_make_cache`（~L812）在 `ctx.secrets.api_key==""` 时返回 NullCache（不读不写），worker 收尾往 `options_json` 写 `mock_run:1`。
3. `store/_tasks.py::find_reusable`/`find_active_by_cache_key`：命中集排除 `options_json` 含 `mock_run` 的行（`json_extract` 或 LIKE 闸）。
4. `routers/tasks.py::task_retry`（~L302）：`RETRYABLE_FROM` 之外放行 `done ∧ mock_run` 行，retry 合并 options 时强制 `prefer=fresh` 语义（跳过段缓存读—— NullCache 只在无 key 时启用，故需显式 `no_seg_cache` 内部选项透传 worker）。
5. `worker/core.py::run()` 收尾：`auth_gate.all_failed`（`xlat/authgate.py:75` 已存在）为真 → error code 钉 `provider_auth`（fault/partial），不被 compile 码顶替（小文档 <3 块不触发 threshold=3 的实测坑）。
6. snapshot：`auth_source` 不透出（现状已是，保持）；needs_auth 建行行 `message` 写「未配置 API Key」。

### M2（`src/texlate/arxiv/fetch.py` + 调用点）

1. 新 `canon(raw, *, strict_era=True) -> CanonId` / `try_canon` / `CanonError(reason)`：剥离序管线按 spec §2（strip → `--`→`/` unfold → 前缀循环剥[arxiv.org 动词簇 + doi.org/dx.doi.org + `doi:` + `10.48550/arXiv.` + `oai:` + `arXiv:|.`] → `?#` 截断 → 尾 `/` → `[class]` 尾注 → 扩展名循环剥 → `vN` 钉版 → class 剥壳 → archive 小写 → 白名单校验）。**锚定正则前缀剥，不 urlparse**——端口/双斜杠/怪 scheme 结构性拒收；`ar5iv.org|alphaxiv.org` 作显式 host 白名单臂（动词限 `abs|pdf|html`，须带 scheme）；LANL 不收（spec 非目标）。
2. `normalize_arxiv_id`/`valid_id`/`req_base_ver` 变薄壳转发（8 个调用点零签名变化：`meta.py:40`、`tasks.py:59`、`refs.py:265`、`cli/thin.py:71`、`cli/share.py:114`、`worker/share.py:430`、`store/_tasks.py:221` 等）。
3. 校验：MM∈[01,12] 默认开；`strict_era` 新形 YYMM≥0704、老形 YYMM≤0703；seq 位数不做时代闸（远端跨时代互认 301 实证）；`v03`→`v3`、`v0` 拒。
4. `bench/py/benchlib.py::canon_id/safe_id` 归并薄壳（`safe_id = canon(x).safe()`）。

### M3（`bench/py/kernel/`）

1. `events.py`：`OPTIONAL_KEYS[T_LAKE_CELL] += {"pinned","manifested","orphan","regen_cost","last_used_at"}`。
2. `lake.py`：`_lake_event` 转发新键；`LakeCatalog.pin(idc)`/`unpin(idc)` = `set(idc, current_state, pinned=True/False)`（字段臂，state 原样）；`_pinned` 读口径不变。
3. `cli.py`：`lake` 子命令加 `pin`/`unpin`（参数=id 列表，canon 归一）；`status` 增 pinned 计数/字节、`cas.stat()` 面。
4. `sweep.py::sweep()` 尾段调 `cas.gc_sweep(grace_s=86400)`，report 增 `cas_swept`——nlink 引用计数本质安全，sweep 的 NB flock 与 `_cas_lock` EX 双锁序已备。
5. `doctor.py`：`lake_catalog` 检查补「pinned 行 dir 缺失→warn」分案（dirless pinned 比 dirless 普排严重）。

### M4（`src/texlate/server/routers/refs.py` 同 register 扩 + 新 `server/bibexport.py`）

1. `bibexport.py`（新叶）：`.bib` 解析器（`@TYPE{key,` 花括号配对切段、`@STRING` defs 表、entry 的 string 引用闭包）、key 归一 `re.sub(r"[^\w:.-]","_",key)`、src.tar/`upload_tex` blob 扫 `*.bib`（tarfile 流式）、case-fold 兜底键表。
2. Lane A：key → verbatim entry 原文 + 被引 `@STRING` defs 闭包置顶注释块。
3. Lane B（key 无 verbatim 且有 id）：arXiv→`https://doi.org/10.48550/arXiv.<id>`、DOI→`https://doi.org/<unquoted doi>`，`Accept: application/x-bibtex`，httpx loop 桶 client（refs.py 既有 `_client()` 复用），并发闸 4、单请求 15s、**总 deadline ~20s**；回包 bibtex key 改写成我方 key；Crossref `bibliographic` 仅作末臂且 `title-overlap≥0.5` 门控（不门控=毒导出，实测 5/12 通过率）。**S2 永不进导出链**（429 常态实证）。
4. Lane C：kept payload 的 RefMeta 快照 → `@misc{key, title/author(" and " 连)/year/journaltitle/doi/eprint+archivePrefix=arXiv}`；meta 空 → `note={text}`；text 也空 → `@misc{key}` 壳。
5. 端点：`GET /api/task/{id}/refs.bib?keys=a,b,c[&all=1]`（`deps.get_task` 租户闸；keys 缺省=kept 全集，无 kept 则全可解 key）；`text/x-bibtex; charset=utf-8` + `Content-Disposition: attachment`；`X-Refs-Degraded` 头 + 文件头降级注释。
6. Phase B：`store/_kept.py` 三函数 + `GET/PUT /api/task/{id}/refs/kept`（PUT 体 `{key,payload}`/`payload:null`=unkeep，key≤160 复用 `_MAX_KEY`，payload≤64KB 闸）。

---

## 测试计划

- **M2**：`canon()` pytest——30 形态表全绿 + 44 对抗探针（6 回归形必收、8 过收形必拒、3 spoof 必拒、`..`/unicode 数字/`v0` 必拒）；幂等性 `canon(canon_str(x))==canon(x)`；`normalize_arxiv_id` 壳语义不变式。前端 `parseArxivId.test.ts` 同步放宽断言。
- **M1**：pytest 建行闸——无 key submit→needs_auth 行 + reader_url；needs_auth 撞键→200 重用行；`find_reusable` 排除 mock_run；worker 单测 `_resolve_translator` 无 key 抛 AuthError、显式 mock 不写 cache；retry mock_run 行放行且带 fresh。vitest——`homeSubmit` auth_required 富错误、`ResultBody` done+warnings banner、needs_auth 内联 key 流。
- **M3**：kernel 测试——pin 字段跨 `mark_used`/状态转移存活（复现 durability 臂）；catalog 重建 replay 保 pinned/manifested/regen_cost；`evict` 三层全跳 pinned + orphan-pinned 存活 + unpin 后可逐；`sweep` 尾段 `cas_swept` 非空；`shrink_shell` 不认文件级 pin（文档化断言）。
- **M4**：`.bib` 解析单测（@STRING 闭包、大小写折叠键、缺 key 跳过）；三臂桩测——DataCite/crosscite/crossref 用 httpx MockTransport（unquote 修复回归、overlap<0.5 拒收、429→Lane C 兜底）；端点测——租户闸、keys 参数、degraded 头、`Content-Disposition`；Phase B 加 kept CRUD + cascade + 64KB 闸 + 跨租户 404。

## 工作量与分期

| 期  | 内容                                                                                | 估时     |
| --- | ----------------------------------------------------------------------------------- | -------- |
| S1  | M2 canon（服务端 + web 镜像 + 测试）                                                | 1.5–2 天 |
| S1  | M3 pin（event schema + catalog/CLI/sweep + 测试）                                   | 1.5 天   |
| S2  | M1 缺 key 防护（建行闸 + mock 围栅 + 缓存防毒 + 前端预检/banner/富 401 + retry 道） | 2–2.5 天 |
| S3  | M4 Phase A（bibexport 叶 + refs.bib 端点 + Toolbar 下载项 + 桩测）                  | 2 天     |
| S4  | M4 Phase B（kept_refs 表 + 端点 + keptRefs store + CiteCard ☆ + DomPane 补线）      | 2 天     |

合计 ~9 天。S1 两项零风险先行；M1 的 mock 防毒（K3）与建行闸（K2）须在同一个 PR 内落——只堵入口不清缓存会留存量毒。

## 风险

1. **needs_auth 建行 vs dedup**：needs_auth 行占 cache_key，同键再提交撞 `IntegrityError`——`deps.py:311` 臂必须同步扩（命中 needs_auth 行→200 返回），否则用户配完 key 重交收无 task_id 的 409 死信。
2. **存量 mock 毒缓存**：段缓存行无 mock 标记可溯，既往写入的占位译文无法批量识别清除——`no_seg_cache` 只防新毒；已知毒池限于 exp 库 160 行，prod 若有需按 `zh LIKE '这是译文%'` 一次性清。
3. **canon 收编改变 dedup 键**：`math.GT/0309136` 旧任务键与新 canon 键分仓——历史任务不复用是既定代价；strict_era 默认开会拒 `9912.00001`/`hep-th/0801001` 这类不可能 id（预期收益：省一轮远端 404）。
4. **refs.bib 远端延迟/抖动**：p50 2.2s、max 20s——总 deadline + 并发 4 + Lane C 兜底是硬需求；上游格式漂移（DataCite 非 `@` 开头回包）按 miss 降级不炸导出。
5. **Crossref 门控**：title-overlap 阈值 0.5 是实测拐点（12 探 5 过）——阈值进常量并随门控回归测试钉死；无门控接入=毒导出。
6. **dom 路 kept key 漂移**：`bib.bibN` 序数随 arXiv 版本重取可变——payload 快照自含 text/meta 使导出不受影响；卡面 keep 态可能标错条目（接受，与位置持久化同语义）。
7. **pin 持久化依赖事件 schema 扩展**：只写 catalog 行不进 `lake_cell` 事件的实现等于没做（重建即丢）——`_lake_event` 转发与 `OPTIONAL_KEYS` 白名单必须同 PR。
8. **sweep 接 cas.gc_sweep 的锁序**：sweep 持 `sweep.lock` NB + kernel_active_hold，`gc_sweep` 内再取 `_cas_lock` EX——须保证 sweep 内调用点不与既有 cas 操作序倒置（现 cas 无其他长持锁方，风险低但要断言 grace 内对象不删）。
