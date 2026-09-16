# spec06 审计 —— docs/06-arxiv-source.md vs src/texlate/arxiv/

- 审计对象：`src/texlate/arxiv/`（cache/fetch/locate/ratelimit/sniff/_texutil/unpack）+ `tests/test_arxiv_*.py`；HEAD f461683。
- 方法：逐节抽取 spec 断言 → 对照实现与测试 → verdict。unpack 路径防护另做恶意 tar 实测（`tmp/audit-spec06/hostile_unpack.py`）。
- verdict 口径：**covered**=实现 + 测试齐；**impl-only**=实现对、无直接测试；**partial**=部分覆盖或有偏离；**missing**=无实现；**n/a-m0**=属后续里程碑面。

## §0 两个消费方共享语义

partial。在线路径走 `acquire_source`（fetch.py:588）全链复用 sniff→unpack→locate；批量建库 `bench/py/build_corpus_v3.py:960` 自带 `unpack_blob`——只查绝对路径+`..`，丢弃全部非 reg 成员（含 in-tree link），无容量上限/大小写折叠/stub/mtree。与「共享同一套解包/定位/钉版语义」不一致：corpus `extracted/` 是弱规范化产物，可能含产品路径会改名的 casefold 冲突。manifest 四元组 `(channel,item,member,blob_sha256)` 符合 §6.2。

## §1.1 端点表

partial。实现面只有 `/src`：`fetch.py:207` `_src_url` 拼 `https://{host}/src/{id}[vN]`；export 镜像作故障转移桶（fetch.py:52-54、`_across_hosts`:277-294，test_failover_to_export_host）。`/html`、`/abs`、`/pdf` GET、Atom `api/query`、OAI、RSS 均无实现——`ratelimit.path_class`（ratelimit.py:45-53）已为 api/oai 预留桶分类。

## §1.2 请求纪律

covered。UA `texlate/{ver} (+repo; mailto:)`（fetch.py:55-58）；每 host ≥3.05s 全局间隔跨 path-class 合并计时（ratelimit.py:207-216）+ `max_connections=1` 零并发（fetch.py:240）；HEAD 预检一次拿 resolved_version+kind_hint+content-length+etag（fetch.py:182-204，`_CD_VER_RE`:151）；>150MB 拒（DL_CAP fetch.py:60、`too_large`:203、body 复查 :366）；`If-None-Match`/`If-Modified-Since`→304（fetch.py:330-334、:359-360）。测试：head 解析/304/404/failover/e2e 命中均覆盖（test_arxiv_fetch.py）；`too_large` 路径无测试。

## §1.3 退避与 park

covered，两处实现超出 spec（更保守，注明）：

- 重试 3 次 +10s/+30s/+90s ±20% jitter：fetch.py:62、:259-275；`Retry-After` 取 `max(computed, ra)`（:212-218）——spec 写「从其值」，impl 在 ra<计算值时仍等计算值，更保守。
- 404 不重试：不在 TRANSIENT_STATUS（fetch.py:64-73）→ 直通 `_head_gate`/:346-354 记 `not_found`。
- 连续 2 次 → 按路径 park：BREAKER_STRIKES=2（ratelimit.py:38）、(host,path_class) 桶、park_base=1800s（:34，勘误已落实 15min→30min）、翻倍封顶 7200s（:36、:229-234）、checkpoint JSON 落盘可恢复（:129-171，test_state_persistence）。
- 日预算 180（ratelimit.py:32；spec 150–200 区间内）。
- 超出 spec：406 计入 breaker strike 且进重试集（ratelimit.py:225、fetch.py:66）；成功/404 复位 strike 与 park_step（ratelimit.py:235-242）。
- 测试覆盖足：pacing/跨类共享/breaker/翻倍/复位/预算/持久化/损坏状态全有（test_arxiv_ratelimit.py）；**406 路径无专项测试**。
- 含义「元数据队列与下载队列独立调度」成立：api vs content 分桶（ratelimit.py:45-53）。

## §1.4 版本语义

partial。

- 缓存键永远 resolved version：covered——HEAD cd 解析（fetch.py:186-188）→ `_head_phase`:455 → GET cd 漂移再钉（:613-615，test_get_newer_version_commits_resolved）。
- meta.json 存 requested_id+resolved_version：covered（fetch.py:556-559）。
- Atom resolved_version>缓存 → 标 stale：**missing**（依赖 §3，无 Atom 实现）。
- 钉不存在版本 → 404 报版本清单：partial——404→`not_found` 有（fetch.py:348-349）；版本清单（abs/OAI arXivRaw）无实现。

## §2.1 三态判别 + 第四态

covered。魔数优先（sniff.py:95-118）：`1f8b`→有上限 gunzip→offset257 `ustar`→TAR 否则 SINGLE；`%PDF`→PDF；其余 UNKNOWN；未压缩裸 tar 是 spec 外兼容分支（:113-117）。无 bsdtar 依赖（纯 tarfile getmembers 先列后解，unpack.py:189）。files.txt 由 write_manifest 产出（unpack.py:346-362）。第四态 pdf_wrapper：check_pdf_wrapper（sniff.py:171-188）= includepdf ∧ section==0 ∧ 正文<2KB，locate 接线（locate.py:342-349）；另加 `is_stub` 放宽档。测试：魔数/corpus139 对拍/损坏 gzip/wrapper 正负例全有（test_arxiv_sniff.py）；**inflated>512MB oversized 拒绝路径无测试**。

## §2.2 路径安全

covered，并经恶意 tar 实测（tmp/audit-spec06/hostile_unpack.py：13 种逃逸向量全部被拒或落树内，dest 外零文件）：

- 拒绝项：`..`/绝对路径/盘符（unpack.py:89-103 `_norm_member`）、包外 link——先查原始 linkname 再查归一化结果双保险（:254-264，注释解释了为何不能只查归一化）、device/fifo/socket 等非 reg（:241-243）、setuid/setgid（:229-231）。
- 规范化：`./` 剥离 + 空段折叠（:98）、重名 overwrite 告警（:209-210）、大小写折叠 `~cN` 改名 + 告警（:203-208、:135-145）。
- 上限：成员≤20k（:32、:190-192）、单文件≤100MB（:33、:217）、总量≤512MB（:34、:218-219，hardlink 物化再查 :295-297）、gunzip 流式 cap 512MB（sniff.py:70-86）。
- 落盘 raw.*+extracted/：fetch.py:538-544（spec 文本写 `raw/` 目录，实现为 `raw.*` 单文件——与 §4.1「`raw.*`」一致，记为 spec 自身措辞歧义）。
- mtree.txt：path+size+sha256+kind`[+link][+stub]`（unpack.py:353-360），spec 只要前三列，实现是超集。
- stub：<100B 或 `%auto-ignore`（unpack.py:36-37、:159-172）留盘标记不进 files 抽样语义（stub_files 单列）。
- 测试：dotdot/绝对/盘符/NUL 截断/symlink 逃逸与保留/hardlink 物化与 dangling/special/setuid/casefold/dup/stub/单文件 cap（monkeypatch 缩阈）/corpus139 全量 resolve 对拍——覆盖强；**缺 MAX_MEMBERS 与 MAX_TOTAL_BYTES 专项测试**（实现有，测试无）。
- 代码细节：file 覆盖同名 symlink 先摘链再写（unpack.py:154-156）防穿链改写，测试 test_file_over_symlink_replaces_link 覆盖。

## §2.3 主文件定位

covered，一处裁决序与 spec 字面有出入（语义可辩护，注明）：

- 候选扩展名大小写不敏感 `.tex/.ltx/.latex`（locate.py:33、:304）——勘误已落实。
- 先剥注释（`\%` 转义+verbatim+comment env 感知，_texutil.py:16-26 走 mask_tex）再匹配 `\documentclass|\documentstyle`（locate.py:40、:400）。
- 裁决序 _choose（:407-438）：begin{document} 过滤 → in_degree==0 独立根 → 文件名先验 `main|paper|ms|root|manuscript|thesis|{id}`（:34-36、:428-434）→ 顶层目录（min parts :435-436）→ include-degree 最大、路径序兜底（:438）。
- 偏离：spec 序为「先验→仍≥2 独立根→标 multi_doc」，impl 在文件名先验**之前**就按 indep≥2 置 `multi_doc`（:420）——即先验消歧到 1 个仍标 multi_doc。语义上「包内有多个独立文档」更忠实，但与 spec 字面序不同；corpus 测试期望与此实现一致（2201.07948/2201.05989 multi_doc=True）。
- 零候选→plain TeX `\bye`/ConTeXt `\starttext` 分类（:316-323、DocKind:82-89）→ 不硬猜；「进降级链」无下游实现（见 §5）。
- report 记录全部候选：candidates+independent_roots 落 meta.json locate 块（fetch.py:398-417）。
- 测试：corpus_v2 全量 139 全 latex+main、v1 陷阱 5 篇钉 main/multi_doc、注释 docclass 不入围——覆盖足。

## §2.4 \input 拓扑

covered。八形态 + 裸 `\input file`（locate.py:57-79 `_REF_RES`；控制词边界防 `\includegraphics` 误配——测试断言 zz 不 unresolved）；import/subimport 双参拼 dir/file（:63-78、:154-158）；基准序 CWD(main_dir)→项目根→including 目录（:216-222，勘误已落实，test_basis_order_cwd_first）；扩展名 `.tex→.sty→裸名`、`\include` 强制 .tex 优先（:193-200）；`\bibliography{x}`→x.bbl 逐逗号项解析+**`\jobname.bbl` 兜底**（:245-262、:356-383，勘误已落实，test_locate_1502_bare_input_and_bbl）；环检测 visiting 集断环 warning、菱形 seen 静默去重（:441-470、test_cycle_and_diamond）；深度闸 64（:37）。

## §3 元数据层

missing。src/texlate 内无 Atom id_list/OAI-PMH/DataCite 任何实现（grep 全空；path_class 仅为 /api、/oai 留了限流分类）。meta.json 是 acquire 级 schema（id/版本/etag/format/locate 摘要），**不含** §3.2 的 title/authors/abstract/primary_category/categories/published/updated/doi/journal_ref/comment/license/links。下游消费点因此全缺：`primary_category`→术语包、`comment`→chunk 预算、`authors`→不可翻名单、stale 检测（§1.4）。ratelimit 的 api 桶分类已备好，属未接线而非阻碍。

## §4 缓存设计

- §4.1 source tier：covered。键 `{id}v{resolved}`（cache.py:67-73，逃逸拒绝+glob 消毒 :27、:77-83）；产物 raw.*/extracted/files.txt/mtree.txt/meta.json/etag 齐（fetch.py:533-585、unpack.py:346-362）；staging→rename 原子换入+`.old-` 回滚（cache.py:106-133）。
- §4.1 product tier：partial。实现在 server/worker.py:204-220 `cache_key_for`=`sha256(id@ver|model|PIPELINE_VERSION|lang)`——**缺 spec 材料里的 `glossary_hash`**；glossary 实际参与段级缓存键 `cfg_hash`（worker.py SegmentCache 注释 :226-233），功能等价但键材料与 spec 不同。失效语义（pipeline_version 只失效 product 层）方向一致。
- §4.2 状态机：partial。AcquireStatus（fetch.py:87-99）覆盖取源段终态 not_found/pdf_only/unknown_format/unpack_error/too_large/parked/budget；`pending→…→done` 全链与 `degraded_html|degraded_pdf` 属 server 任务态（worker 11 态机），不在本层。`stub` 终态无对应——pdf_wrapper/stub 只进 warnings，acquire 仍返回 OK。

## §5 降级链

missing（本层）。无 L2 `/html` 探测、无 L3 PDF sidecar 翻译入口；`pdf_wrapper` 检出后仅 warning+meta 标记，acquire 照常 OK 返回，下游解析 wrapper .tex 大概率走到 compile_failed 而非 `degraded_*`。worker.py:746-755 把 PDF_ONLY/UNKNOWN_FORMAT 映射 `no_latex_source` 错误，无降级。spec 三态覆盖 ≈100% 的承诺当前只有 L1。

## §6 批量渠道

covered（bench 侧，`build_corpus_v3.py`）：IA arxiv-bulk+HF TIGER 双渠道、零 arxiv.org 请求、`.part`+Range 断点续传、zipsum 交叉核验 sha256（:624-654）、manifest 四元组、resolved_version=null（corpus_v3 meta.json 实证）。与 §0 共享语义声明的出入见 §0（unpack 双实现）。HF scholarweave/S3/GCP 行属裁决记录非实现项。

## §7 开放项

仍开放，与 spec 自述一致；park 取保守值已落实。

## 实现超出 spec 的加固（留档）

- `_valid_id` 拒非法 id 在发请求之前（fetch.py:168-174、test_bad_id_rejected_before_network）；entry_dir resolve 逃逸拒（cache.py:70-72）。
- GET 响应 cd/etag 刷新 HEAD（fetch.py:376-386）+ 版本漂移重钉（:613-615）。
- 缓存终态透传：pdf_only/unknown 命中不伪装 cache_hit（fetch.py:421-429，两个专项测试）。
- ratelimit 损坏状态文件干净起步不拦请求（ratelimit.py:145-147、test_load_corrupt_state_starts_clean）。
- `_hit_status`/404 复位断路器等防御性语义。

## 测试缺口汇总（建议补）

1. `too_large`：content-length>150MB 与 body>cap 两路（fetch.py:203、:366）。
2. inflated oversized>512MB → AcquireStatus.TOO_LARGE（sniff.py:99-108 → fetch.py:526-532）。
3. MAX_MEMBERS>20k 与 MAX_TOTAL_BYTES>512MB 拒绝（unpack.py:190-192、:218-219）——monkeypatch 缩阈即可，现有 test_file_size_cap 同款手法。
4. 406 作为 transient+strike 的行为钉死（目前只在 docstring 声明）。
5. `unpack_single` stem 消毒边界（注入字符/空名→main.tex，unpack.py:308-315）目前只测了正常名。

## 总评

§1–§2 在线取源 + 解包 + 定位核心面 **covered 且测试扎实**（unpack 安全语义经独立恶意 tar 复核为真）；§4.1 source tier covered。两处明确缺口：§3 元数据层整体 missing（连带 §1.4 stale、§4.1 消费点、§6 分层 frame 的 license 键只能靠 build 期补齐），§5 降级链 L2/L3 missing（wrapper/pdf_only 只标记不降级）。两处语义偏离需注意：bulk 管线 unpack 双实现（§0 承诺未兑现）、product 键材料缺 glossary_hash（段级缓存已兜住功能）。五处测试缺口均为「实现有、断言无」，非实现缺陷。
