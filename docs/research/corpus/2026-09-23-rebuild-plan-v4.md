# Corpus 重建终案 v4 —— 规模裁决 + 管线缺口 + 执行序列

日期：2026-09-23。调研方式：5 路并行 agent 盘点（specs/hydration/selection 三路代码审计 + constraints 实测 + stats sizing）。本文件取代此前口头的 ~7.3k / ~12.8k 两版估算，为重建的准绳。

## 0. 一句话答案

- **管线写了没有**：骨架完整可跑——`frame_build`/`corpus_v3`/`corpus_expand`/`corpus_layers`/`corpus_hot`/`corpus_sw` 六个 spec + `_corpus_common` 全部机械（下载/扫描/feature/materialize/largest_remainder）+ `lake register/absorb/pin/evict/doctor` CLI 齐活；旧 `bench/py/corpus/build_*.py` 已于 17fed90a 删除，逻辑逐字迁入 specs，无损失。**缺的是一个 40-cell allocator 和配套 driver spec**（详见 §3）。
- **13k 够不够**：统计上 core 5k 已过 knee（pooled MDE 2.46pp，spec 要求 5pp，余量 2 倍）；继续加到 20k 只买 +0.17pp pooled CI——不值。真正的边际收益在 scale 层的失败签名发现（+1k 篇 ≈ +173 instance sigs）。
- **真实上限**：不是 API，是**磁盘**——物理盘余量 ~109G，全量 zh 每篇实测 ~18.8MB（corpus 4.4 + vault 4.8 + splice 9.6）。13k 必须 zh 分层 + splice 修剪；20k 需 zh-partial 或存储手术。

## 1. 统计 sizing（实测账本：492k records / 15,829 papers / 2,238 distinct sigs）

### 1.1 每格精度（Wilson 95% 半宽）

| n/格                 | p=0.5  | p=0.8  |
| -------------------- | ------ | ------ |
| 100                  | ±9.6pp | ±7.8pp |
| 125（core 5k/40 格） | ±8.6pp | ±7.0pp |
| 200                  | ±6.9pp | ±5.5pp |
| 325（13k/40）        | ±5.4pp | ±4.3pp |
| 500（20k/40）        | ±4.4pp | ±3.5pp |

### 1.2 回归检出（two-proportion, α=.05, power=80%, 基线 0.75）

- 格级 5pp 跌落需 n=1251/格/run——**永远达不到**，格级只做健康描述不做门。
- pooled（后分层加权）run-vs-run MDE：5k → **2.46pp**；13k → 1.52pp；20k → 1.22pp。spec 的 5pp 回归门在 5k 已 >99% 功效。

### 1.3 签名发现曲线（真实账本）

- 原始 sig：2,238 distinct，singleton 率 75.6%，Chao1 估计总量 ~10,560 → 当前只观测到 ~21%。
- 边际产出 @n≈10k：**+173 新 sig/每 +1k 篇**，仍在近线性段。
- 但机制族级（sig 前缀）：90 distinct，Chao1 114 → **79% 已覆盖，+2.4/1k 已饱和**。尾巴是实例参数化 sig（喂聚类，不喂规则编写）。

### 1.4 结论

core 5k 是 knee；超出的规模只能通过 scale 层的签名发现来辩护。20k vs 13k 的统计收益微不足道（+0.17pp CI），签名收益 +1.2k instance sigs（Chao1 覆盖 21%→~32%）——可做但属加餐。

## 2. 磁盘规划（实测值，2026-09-23）

### 2.1 实测单价（推翻旧估算）

| 对象                 | 实测                                                                 | 旧估算 | 备注                                                                       |
| -------------------- | -------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------- |
| corpus cell hydrated | **mean ~11.9MB**（raw 5.4 + extracted 6.5，n=100>2M）；全群均 ~8.7MB | 4.4MB  | era 加权投影 ~11.1MB（e 带 17.6MB 主导）；e/f 带现存 cell 偏大可再压       |
| vault/zh             | mean 4.7MB，其中 binary 图档 **4.5MB**、texish 0.22MB                | —      | 图档与 corpus cell 同字节但未挂 CAS → 可硬链去重                           |
| vault/splice         | mean 9.4MB                                                           | —      | final.pdf 1.5MB + .fixloop-entry.pdf 2.8MB（重复）+ 全部图 pdf/中间件 ~5MB |
| TARS 暂存            | **每 chunk ~0.5GB 永不清理**（corpus_v3.py:92 无 prune）             | —      | 13k ~430 chunks ≈ 215G 瞬时——必须先修                                      |

每篇全量 zh 稳态 = raw 5 + ext 6.5 + zh 4.7 + splice 9.4 ≈ **26MB**（现状政策）；修剪后 ≈ **8MB**。

### 2.2 预算盘

- 物理余量 109G（917G 盘 88%）；lake+vault 现占 26.5G
- 可回收：`~/tmp-quarantine-20260922/` 14G + bench `backup/` 6.5G + 旧 hydrated 但落选新 manifest 的 cell ~22G + repo `tmp/` 部分 ~5G → **合计可用 ~130-140G**

### 2.3 保留政策档位（每篇稳态）

| 政策    | 内容                                    | MB/篇  | 13k 总量    |
| ------- | --------------------------------------- | ------ | ----------- |
| P0 现状 | 全留                                    | ~26    | 338G ✗      |
| P1      | evict extracted（lake 原生 LRU 档）     | ~19.5  | 254G ✗      |
| P2      | P1 + splice 只留 final.pdf+arm.json+log | ~11.6  | 151G ✗      |
| P3      | P2 + zh 图档硬链 CAS（≈去重）           | **~8** | **~104G ✓** |

**P3 = 13k 的准入政策**：raw 常驻（5MB，档案资产）、extracted 用完即 evict（lake `evict()` 原生支持，`raw_only` 档设计如此）、zh cell 图档走 CAS 硬链（~省 4.5MB/篇）、splice 只留 final.pdf+metrics（~省 8MB/篇）。

**P3+（状态条件版，依赖 layoutqc 落地）**：clean∧layout-clean 篇 → 上表 ~8MB；layout fail 篇留 splice 全档（~17MB）作复现料；compile fail 篇留 extracted+workdir 诊断面。详见 docs/dev/layoutqc-plan.md §5——磁盘政策与质量体系同一张表。

### 2.4 运行期峰值

- fetch 阶段 TARS：按 item 用完即删（新增 prune 钩子）→ 峰值 ~10-20G 而非 215G
- extracted 工作集：只在跑批窗口存在，batch 级 evict → ~2k×6.5 ≈ 13G 峰值
- workdir：~1.5MB/篇 瞬时，runs/ 定期清

### 2.5 磁盘配方结论

| 规模 | corpus raw | eval extracted | zh(链CAS) | splice(final only) | 稳态合计  | 判定                        |
| ---- | ---------- | -------------- | --------- | ------------------ | --------- | --------------------------- |
| 10k  | 50G        | 工作集 ~13G    | ~8G       | ~15G               | **~86G**  | 宽限 ✓                      |
| 13k  | 65G        | ~13G           | ~10G      | ~19G               | **~107G** | 贴顶 ✓（需回收 quarantine） |
| 20k  | 100G       | —              | —         | —                  | >150G     | ✗ 需迁盘/压缩 zh            |

zh 时间面（不变）：j10 ≈ 55 papers/h、yield 0.77 → 全 zh 10k ≈ 9.8d、13k ≈ 12.8d，promo 23d 内都够。**瓶颈从始至终是磁盘，不是 API、不是天数。**

## 3. 管线现状与缺口

### 3.1 已有（可直接复用）

- `frame_build` spec（bench/py/specs/frame_build.py）：snapshot→derive→indexes→allocate→stamp；frame.parquet 3.17M 行今日新鲜；strata-era-cat.csv 即 40-cell 宇宙。
- `_corpus_common`（1,311 行）：download_item（.part+Range 断点+sha1/oid16 校验）、scan_item/scan_batch、fetch_blob Range-GET、frame_lookup、blob_features+eval_signatures、materialize_into_stage、manifest_row_from_meta、largest_remainder。
- 五件套 spec：corpus_v3（整 tar+stream scan 全链）、corpus_expand（quota 增量+eprint 尾道）、corpus_layers（flat/fbias/flags 三模式）、corpus_hot（OpenAlex）、corpus_sw（scholarweave 行段投影）。
- lake：`register`/`absorb`/`pin`/`evict`/`doctor` CLI 齐；`lake.hydrate()` 库函数被 spec fetch_fn 调用（无 CLI verb 是设计如此）。
- 选择侧：select_booster.py + mechanisms.jsonl（263 行：B×11/T×34/W×213/q×5）+ nominations/（~558 提名 + ~99 机制提案）全部存活。

### 3.2 缺口（要新写的，约 1-2 天）

1. **band×cat allocator**：现有 `cmd_allocate` 只产 30 个月度 cluster；40-cell（5 band × 8 cat_group）配额须新写——cell floor 125 + 按比例 top-up 到 core 5k，再映射回 cluster/成员。
2. **per-cell floor**：`largest_remainder` 无 floor 参数，需扩展或包一层。
3. **license 条件过采**：license_class 全程记录但从未作选择谓词——cc-release 层需要。
4. **legacy 冻结**：manifest 每次 run 重建，需一次性快照拷 manifest_legacy.jsonl。
5. **mech_tags 全字段**：`manifest_row_from_meta` 缺 mech_tags（只 booster 行有），schema 严格化要补。
6. **driver spec**：v3 写死 ~1000-core/30-cluster 形态；13k cell-keyed 重建需要新 spec（建议 `corpus_v4.py`）或 allocate 新模式 + 复用 v3 的 fetch/scan/extract 阶段。

### 3.3 设计偏差提醒（不影响开跑）

- 设计的 `view_archive` 成员级端点未实现（用 zipsum+offset Range-GET 等价实现）；wanted≥12 密度分发不是显式开关（v3 恒整 tar）；TIGER 散装成员探测层未实现。都可后补。

### 3.4 重构裁决（fork 深审 + git 史）

**之前做过吗：没有。** git log 显示 corpus_v3.py/_corpus_common.py 只有三次提交——Wave-E 逐字迁移（81210a49, 4c1f2fb3）与 Wave-F repoint（cf054070）；无独立审计；且 `~/.local/state/texlate/corpus-build/v3/` 不存在——**迁移后从未端到端跑过**（v3-smoke* 三个 run 全部 dedup-skip 空跑）。代码完备，实战未证。

**裁决：参数化+扩展，不重写。** 全部 `_corpus_common`、lake.hydrate、fetch/zipsum/frame_lookup/sample/extract 阶段、qc 断言可复用。必须修的：

| 项                                             | 严重度          | 位置                                                                     | 修法                                                              |
| ---------------------------------------------- | --------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| TARS 永不清理                                  | **launch 阻断** | corpus_v3.py:92 TARS=WORK/"tars" 无 prune                                | 新增 post-extract prune 阶段（extract 后即可删对应 item 的 .tar） |
| quota 无法表达格级 floor                       | 高              | _sample :1337-1367 shares 制 + deficit backfill :1397 静默违反 cell 下限 | 换读 allocation-core-v4.csv（cluster×cat×target）                 |
| pick_chunk_ids 写死 2 chunks/月                | 高              | :188-195                                                                 | 按 quota 扩（池须 ≥5× cell 需求）                                 |
| _scan 串行 ~30-60s/chunk                       | 中              | :1132-1159                                                               | chunk 独立，并行化 → 4-7h 压到 ~1h                                |
| _extract_members 串行+每 member 全 header 重扫 | 中              | :1704-1789, getmembers :1662                                             | 按 tag 并行；offset 索引复用                                      |
| manifest 每次 run 全量重建                     | 低              | _rebuild_manifest :1790+                                                 | legacy 冻结用显式快照拷贝                                         |
| zh/splice vault 不挂 CAS                       | 中（磁盘）      | vault 写入处                                                             | 未变 binary 文件硬链 objects/ → zh 省 4.5MB/篇、splice 省 ~5MB/篇 |
| qc 文案写死 "目标 1000"                        | 低              | :2067                                                                    | 参数化                                                            |

密度分发 verdict：core 层 dense（wanted≥12/item）整 tar 正确；稀疏层靠 `fetch_blob` 成员级 Range-GET 已存在，仅 id-keyed 补足时需要开关——**不是重建前置项**。

## 3.5 风险增量（审计新增）

- v3 spec 零端到端实证 → 开跑前必须一次 1-cluster 全链路彩排（plan→qc 全绿才算管线就绪）。
- 430-chunk fetch 的 .part 断点续传在整 tar 模式下已是实现好的；TARS prune 须等该 item 全部 member extract 完才可删（gc 顺序 = extract→prune，同 stage 内）。

## 4. 最终方案 —— ~13k，分层 zh

| 层         | 篇数        | zh                                   | 职责                             |
| ---------- | ----------- | ------------------------------------ | -------------------------------- |
| core       | 5,000       | 全                                   | 40-cell 加权推断主资产（125/格） |
| holdout    | 2,000       | 全                                   | 回归门（pooled MDE 2.5pp）       |
| dev        | 500         | 全                                   | 日常迭代                         |
| booster    | 500         | 全                                   | 机制覆盖（263 机制账本）         |
| cc-release | 1,000       | 全                                   | 可发布子集（e-band CC 过采）     |
| hot        | 300         | 全                                   | OpenAlex 热文                    |
| legacy     | ~500        | 全                                   | 冻结旧资产                       |
| scale      | 3,000       | **en-compile 优先，promo 余量补 zh** | 签名发现引擎                     |
| **合计**   | **~12,800** | 9,800 全 zh + 3k 弹性                |                                  |

- zh 工作量：9.8k ÷ 0.77 yield ≈ 12.7k 次尝试 ≈ **9.6 天 @j10** —— promo 内余量充足，scale 层 zh 可吃到 ~13k 全 zh（12.8d）仍有余。
- 磁盘：P3 政策下 13k ≈ **107G**，须先回收 quarantine 14G + backups 6.5G 才宽松；安全阀 = scale 降到 2k。
- 想 20k：先做存储手术（zh 工件 zstd / lake 迁盘），否则物理装不下。scale 层扩容走 `corpus_expand` 增量路径，接口已支持——**现在把 allocator 写成可增量就是为 20k 留门**。

## 5. 执行序列

- **Step 0（今天）**：磁盘手术——(a) 回收 quarantine 14G + bench backups 6.5G（需用户点头）；(b) 定 P3 保留政策：splice 只留 final.pdf+arm.json+log、zh 图档挂 CAS、extracted 用完即 evict；(c) `TEXLATE_LAKE_CAP_GB` 调到 ~120。
- **Step 1（1-2d 代码）**：(a) `corpus_v4.py` driver spec + 40-cell allocator（cell floor + top-up + license 谓词 + legacy 快照，quota-CSV 喂 _sample）；(b) **TARS post-extract prune**（launch 阻断项）；(c) pick_chunk_ids 按 quota 扩；(d) scan/extract 并行化；(e) `manifest_row_from_meta` 补 mech_tags；(f) vault zh/splice 落 CAS 硬链。
- **Step 1.5**：**1-cluster 全链路彩排**（v3 迁移后零实证）——plan→fetch→scan→sample→extract→qc 全绿 + TARS prune 验证，才算管线就绪。
- **Step 2**：`bench run frame_build`（allocate 新模式）→ manifests → `lake register` skeletons。
- **Step 3**：fetch/hydrate —— ~142GB/10h 网络面，detached 跑（setsid+nohup，按 detached-long-batches 纪律）。
- **Step 4**：zh 按优先级 tier 跑 @j8-10：core→holdout→dev→booster→cc→hot→legacy→scale。
- **Step 5**：promo 余量 → scale zh 补齐 / scale 扩到磁盘极限。
- **Go/no-go 门**：Step1 后 dry-run allocator 出 40-cell 配额表审阅；彩排全绿才放行 Step2；Step3 后 `doctor`+catalog 对账；Step4 每 tier 跑完 `gate` 过 90% 才进下一 tier。

## 6. 风险登记

- splice mean 9.4MB 是磁盘刺客（.fixloop-entry.pdf 单文件均 2.8MB×250，全量中间件图 pdf 占大头）——P3 保留政策必须先定。
- **TARS 暂存 215G**：不加 post-extract prune，fetch 阶段 alone 就爆盘——已在 Step1 列为阻断项。
- 迁移后 spec 从未端到端跑过（v3-smoke* 全 dedup-skip 空跑）——彩排是硬门。
- TIGER 3.7MB/s 主导 fetch 时间；IA 段快。era 混合 40/60 已计入。
- promo 到期后 scale 层 zh 成本真实化——en-compile 签名不依赖 zh，是天然降级路径。
- e2e_real-2 在飞（pid 3226531）——fetch/hydrate 开跑前确认网关负载不互踩。
- vault zh 图档未挂 CAS（nlink=4 但对象库无 inode——vault 内部互链，corpus↔vault 不去重），修好前 zh 每层多花 ~4.5MB/篇。
