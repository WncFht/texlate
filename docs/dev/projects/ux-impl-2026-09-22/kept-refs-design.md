# kept-refs（引用卡收藏 + .bib 导出）考古与设计

> **结论**：SQLite `kept_refs` 表（`PK(task_id, ref_key)` + payload 快照即真相）+ 服务端 `refs.bib` 组装端点——sidecar 文件方案因 slim 清扫面出局。
>
> **状态**：已落地（misc-pack M4，2026-09-23 落地波；落地差异见文末注记）
> **日期**：2026-09-22

2026-09-22 · 结论：**现状无任何「收藏/keep」持久化**。CiteCard 脚部只有 `跳到文献表` + `arXiv ↗` + `DOI ↗` 三个动作（CiteCard.tsx L169-201）。本稿给出存储选型与 .bib 组装点设计。

## 0. 考古事实（决定设计的硬约束）

### 0.1 三条卡路的数据可用面不对称

| 卡路                     | 宿主                | key                                                                                                                                   | text                        | meta                                                               |
| ------------------------ | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------ |
| pdf（eprint/upload_tex） | PdfPane.tsx:192-237 | `cite.<key>` dest → `citeIndex.lookup`（dual.json `ph` 的 `\bibitem{key}` 反查）；lazy 兜底 `key = dest.slice(5)`，`order=0 label=""` | `BibEntry.text`（掩码已解） | `props.citeMeta(key)`（ReaderView.tsx:348）                        |
| dom（arxiv_html）        | DomPane.tsx:182-201 | **只有 DOM id `bib.bibN`**（positional，非 bibkey；`data-chunk` 同值）                                                                | `li.ltx_bibitem` clone      | **未接线**——PaneSlot.tsx:92-104 不给 DomPane 传 citeMeta/citeIndex |
| html（md_zip 降级）      | HtmlPane            | 无卡                                                                                                                                  | —                           | —                                                                  |

- dual.json `ph` 里 `[[BIB_n]]` 只含 `\bibitem{key}`（可选 `[label]`），条目正文=该 token 到下一 BIB token 的 en 子串——**结构化 BibTeX 字段已丢失**，只剩格式化文本（实测 dual.json 样例，ux-research 现场 seq52）。
- bibtex 源论文（`\bibliography{x}`）bibitem 根本不进 chunks——citeIndex.size=0，pdf 卡全靠 lazy dest；此时 bibkey 仍真（hyperref cite.\<key\> 锚），但无 label/order/text 除非 dest 抽取成功。
- dom 路 `bib.bibN` 是 LaTeXML 序数 id——同一文档版本内稳定，重取新版 arXiv 后序数可漂移（见 §3 风险）。

### 0.2 服务端持久化既有模式

- **SQLite** `texlate.db`（store/_common.py DDL）：tasks/chunks/files/translation_cache/task_events/task_usage 六表；新表=DDL 串追加 `CREATE TABLE IF NOT EXISTS` 即自动迁移（task_usage/T4 先例，_common.py:111-121）。租户隔离走 `deps.get_task`（tenant=sha256(api_key) 比对，deps.py:88-93）——挂 task_id FK 即免租户列。
- **任务目录 sidecar**：`reading.json`（reader.py:97-141）——`atomic_json`（xlat/state.py:39）+ 字段级合并 PUT + `document_version`(zh_pdf sha256) 409 闸。
- **⚠ slim 清扫面**（store/_common.py:273-332 + server/_common.py:44-61）：`POST /tasks/slim` 与 retention loop 删 task_dir 内**一切未登记进 files 表的路径**（done/partial 仅 keep_dirs `zh`/`base` 整树豁免）。**reading.json 现已会被 slim 抹掉**（既有缺陷，位置持久化不抗瘦身）；kept-refs 若走 sidecar 同被抹——用户标的数据被清扫器静默丢，比丢滚动位置严重。⇒ **sidecar 方案出局**（除非登记 files 行污染产物面）。
- 任务删除 `DELETE /task/{id}` → `drop_task_dir` rmtree + 行删（tasks.py:464）；FK `ON DELETE CASCADE` 可让 kept 行随任务殉葬——语义正确（论文删了收藏无意义）。
- `src.tar` 是登记产物（survive slim）：eprint=tar.gz 含原始 .tex/.bbl/.bib；upload_tex=上传 blob。`src/` 展开树会被 slim 删。
- localStorage 现状只放外观偏好（texlate-paper-theme/texlate-lang）；用户产出态（阅读位置）一律服务端——kept-refs 属后者，localStorage 不符本仓分层惯例且 server 模式下无租户故事。

### 0.3 卡片生命周期

滚动/scalechanging/pagesdestroy 即关（annotationLayer LRU 逐出死锚）；开卡 dwell 150ms、关宽限 350ms；卡 DOM 序远离锚，Tab 重导已做。keep 钮进 `cite-card-foot`（cite.css:81）与 jump/ext 链并列即可，不新开挂点。

## 1. 存储设计：**SQLite `kept_refs` 表**（推荐 v1）

```sql
CREATE TABLE IF NOT EXISTS kept_refs (
  task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  ref_key    TEXT NOT NULL,             -- bibkey 或 dom 路 bib.bibN
  payload    TEXT NOT NULL,             -- JSON: {label,text,arxivId,doi,meta}
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (task_id, ref_key)
);
```

- DDL 串追加即可（IF NOT EXISTS 自带迁移）；访问层放新叶 `store/_kept.py`（list/put/delete 三函数）+ `__init__` 门面转发，与既有叶同构。
- `payload` 存**快照即真相**：text=用户当时看到的条目文本，meta=当时的 L2 RefMeta 快照。重译/重排版后 key 即使漂移，导出内容仍是用户标的那份（自愈合，见 §3）。
- 无 tenant 列——task_id 经 `get_task` 已做租户检；跨租户探测不到 task_id 就碰不到 kept 行。

### 端点（挂进 `routers/refs.py` 同一 register）

| 端点                                     | 体/参                                    | 行为                                                                           |
| ---------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------ |
| `GET /api/task/{id}/refs/kept`           | —                                        | `{kept: {key: payload}}`（读者打开时一次取，挂 ReaderView mount）              |
| `PUT /api/task/{id}/refs/kept`           | `{key, payload}` / `{key, payload:null}` | upsert / unkeep；key 长 ≤160 复用 `_MAX_KEY`；payload ≤64KB 闸                 |
| `GET /api/task/{id}/refs.bib?keys=a,b,c` | keys 缺省=全部 kept                      | 组装 .bib → `text/x-bibtex; charset=utf-8` + `Content-Disposition: attachment` |

三端点全走 `deps.get_task` 租户闸；refs.bib 不需 document_version（payload 自含内容）。

## 2. .bib 组装点：服务端 refs.py，两级供给

```
keys → for each:
  ① src.tar/源树 verbatim：tarfile 开 src.tar 扫 *.bib，
     @\w+\s*{\s*key\s*, 花括号配对切原始 BibTeX 段——bibtex 源论文
     给真字段（作者/刊名/pages 全保真）。upload_tex blob 同理。
     .bbl 的 \bibitem 段不取（LaTeX 原样塞 note= 太丑）。
  ② 快照合成（兜底，arxiv_html/lazy dest 唯一路）：
     @misc{key, title/author( " and " 连)/year/journaltitle(venue)/
     doi/eprint+archivePrefix=arXiv 来自 meta_json；
     meta 缺 → @misc{key, note={text}} }
```

- 选服务端而非前端组装：verbatim 臂必须读 src.tar（在服务端盘上）；前端组装只能做②——拿不到真 BibTeX 是本特性的主要价值损失。
- 导出 UI：Toolbar `downloads: DownloadItem[]`（Toolbar.tsx:289+；ReaderView 装配清单处）追加条件项 `kept-refs.bib`（kept.size>0 才显），或卡内/侧栏加「导出 .bib」钮。URL 即 `refs.bib` 端点——`download` 属性直链，与现有产物下载同径。

## 3. 前端接线（改动面）

- `stores/keptRefs.ts`（新，~80 行）：`kept=Signal<Record<key,payload>>`，`load(taskId)` 挂 ReaderView mount effect（与 citeIndex effect 并列，ReaderView.tsx:346-367 区）；`toggle(key,payload)`=乐观写+PUT，失败回滚。按 taskId 分桶（模块态 Map<taskId,signal> 或随 ReaderView 实例局部 signal——后者更简单，reader 页单实例）。
- `CiteCardBody`：props 加 `kept?: boolean`、`onToggleKeep?()`——foot 加 ☆/★ 钮（i18n `cite.keep`/`cite.kept`/`cite.keepRemove`）。
- PdfPane：卡开时 `entry` 即 payload 源（key/order/label/text/ids + `props.citeMeta(key)` 快照）；toggle 回传经新 prop。
- **DomPane 缺口须补**：PaneSlot 给 DomPane 补传 citeMeta（可选）+ keep 回调；key=`id`（`bib.bibN`），payload 由 clone 构造——`text=clone.textContent`、label 取 `.ltx_tag_bibitem` 文本、ids 走 `extractRefIds(text)`。
- i18n zh/en 各加 3-4 键；cite.css 加 `.cite-card-keep` 样式（与 `.cite-card-jump` 同族）。

## 4. 被否方案

- **localStorage `texlate-kept:{taskId}`**：与 reading.json 服务端先例相悖；清浏览器数据即丢；server 模式无租户概念（同 origin 共用）。仅适做离线兜底缓存层，不做主存。
- **task_dir sidecar `kept-refs.json`**：slim 白名单抹除（reading.json 同款坑，且 kept 是用户数据不可接受）；除非登记 files 行——污染产物面且 files 行语义=可服务 artifact，不合适。
- **tasks 表加列 / options_json 内嵌**：per-key 行集合塞 JSON 列，并发 toggle 要整列读改写——竞态面差，不如行表。

## 5. 风险

1. **dom 路 key 漂移**：`bib.bibN` 是序数——重取新 arXiv 版本序数可换。缓解：payload 快照自含 text/meta（导出不受影响）；卡面 keep 态可能标到错条目上（接受：kept 标的是「这个位置」，与位置持久化同语义）。
2. **bibtex 源论文 citeIndex=0**：lazy dest 抽取 text 才有 payload；verbatim 臂靠 src.tar .bib 兜底——若 eprint 既无 .bib 又抽取失败，kept payload 只剩 key，导出成 `@misc{key}` 空壳（仍可接受=占位）。
3. **BYOK 换 key→tenant 换**：kept 行随任务行一起对新租户不可见——与任务本体同 blast radius，一致行为。
4. **payload 体积**：meta.tldr+text ≈ KB 级/条，400 条上限内 DB 行无虞；PUT 加 64KB 闸即可。
5. **并发 toggle**：同 taskId 双窗格同条目同时 toggle——upsert 幂等，后写赢，语义可接受（标志位非计数器）。

## 6. 落地差异注记（2026-09-23 落地波回写）

- **`.bib` 组装两级 → 三臂**：misc-pack M4 在 ① verbatim 与 ② 快照合成之间加了 Lane B 远端 bibtex 臂——无 verbatim 但有 arxiv/doi 线索时走 crosscite（DOI→`doi.org/<unquoted>`、arXiv→`doi.org/10.48550/arXiv.<id>` DataCite）+ Crossref `query.bibliographic` 末臂（`title-overlap>=0.5` 门控，S2 因 429 常态不进链）；远端臂失败/超时/低重叠一律降级 Lane C 绝不 502。实现落点 `server/bibexport.py`。
- **`refs.bib` 端点扩参**：除 `keys=` 外增 `all=1`（无 kept 时默认全可解 key、有 kept 时默认只导 kept 子集，`all=1` 出全量）与 `download=1`（仅此时下发 `Content-Disposition: attachment`）；新增响应头 `X-Refs-Degraded`（降级 key 数 + 文件头注释双层报告）与 `X-Refs-Truncated`（`_MAX_REFS` 截断信号）。
- **kept 端点增 DELETE 臂**：`DELETE /api/task/{id}/refs/kept/{key:path}`（`:path` 容纳 key 内 `/`，未命中 404）——与 `PUT payload:null` unkeep 两形并存。
- **DomPane 缺口已补**（§3 计划项落地）：PaneSlot 现给 DomPane 传 `citeMeta` + `onToggleKeep`；`stores/keptRefs.ts` 落地为**模块单例**（reader 页单任务单例，深层 pane 经 PaneSlot 直读——设计稿「Map 分桶 vs 局部 signal」两案实际取第三形态），toggle 带乐观写+回滚+全局写链串行+keySeq 代次闸。
- **风险 2 退化已实证**：eprint 无 .bib 且抽取失败时导出 `@misc{key}` 空壳——`bibexport.py` 代码注释具名回指本稿（"kept-refs-design 风险 2 已知退化"）。
