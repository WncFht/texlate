# 语料规范 —— arXiv LaTeX 源码评测底材

> spec/ 层唯一事实源：与 `bench/` 磁盘现状对齐。评测器侧（用这些底材怎么测）见 `spec/benchmark.md`；取源渠道裁决与单次调研证据以 `research/` 档案为准。
> **trizone 口径（2026-09-23 起）**：清单/数据分离——`bench/corpus/` 只存 tracked manifest 与台账（数据树 gitignored），物化载荷统一在 `$TEXLATE_BENCH_ROOT/lake/corpus/`（可重建湖，设计 `spec/bench-trizone.md`）；付费产物归 vault（§8）。旧 `corpus_v2/corpus_m1k/corpus_daily/zh-store` 分库根已随 Wave-F 清点退役，manifest 全折进 `bench/corpus/` 单根。

## 1. 定位与设计原则

语料是整条管线（解析/翻译/编译/fixloop）的**评测与开发底材**：arXiv e-print 解压原样，入库后不改写——陷阱语义逐字节保留，`bench/fixtures/` 同理。六条设计原则[^v3plan]：

1. **零在线 API 为默认路径**：主体语料来自批量渠道（IA `arxiv-bulk` 月 chunk / HF `TIGER-Lab/arxiv-latex-5T` / HF scholarweave parquet / HF 元数据快照），不请求 arxiv.org → 可复现、无限流、可断点续跑；仅 hot/recent 等"近期轴"层走产品取源路径 `acquire_source`（e-print 钉版，限速串行）。
2. **Measure-then-sample**：bulk tar 给出整月全集 → 先测全体成员真实特征（docclass/文件数/编码/`\input` 深度/包旗标），再按真实分布配额抽样，优于盲抽 id 赌分层命中。
3. **字节保真分级**：raw e-print blob 原样入库（编译段底材，图/.bst/.bbl 齐全才可编）+ `extracted/` 过滤树（解析段底材）；有损源（scholarweave 脱水文本树，无二进制图）只进 dev 层、不进评测/池化。
4. **评测/开发分轨**：核心均匀层回答"成功率多少"（无偏池化估计唯一来源），其余各层回答"这个坑处理了吗/训练调试用什么"——**报告分开，池化只用 core 层**；`holdout` 层为评测贞操层，dev 侧枚举摸不到（§6 治理）。
5. **钉版可复现**：成员级 `(channel, item, member, blob_sha256)` 四元组记 manifest；语料可凭入库脚本重生成。
6. **加层不删层**：新需求开新 manifest 层，旧层原样保留；版本冲突落选树存档 `_alt-versions/`（§7）。

## 2. 物理布局与标识

### 2.1 库根与入库边界

| 根目录                              | 角色                                                                      | 口径                                                                                        |
| ----------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `bench/corpus/`                     | **清单根**——全部层的 manifest/台账/提名/审计件（tracked）                 | `manifest{,_*}.jsonl` + `MANIFEST*.md` + `mechanisms.jsonl` + `nominations/` 入库，无数据树 |
| `$TEXLATE_BENCH_ROOT/lake/corpus/`  | **载荷根**——全部物化语料 cell（可重建湖）                                 | 全量 gitignored（在仓库外）；`corpus/{source}/{sid}/` cell + `catalog.jsonl` 状态机         |
| `$TEXLATE_BENCH_ROOT/lake/objects/` | CAS 内容寻址存储（raw blob 与 vault 大叶文件的共享底）                    | 全量 gitignored                                                                             |
| `$TEXLATE_BENCH_ROOT/vault/`        | 付费/不可再生产物保险库（zh 译文/splice 成品/state 检查点/layoutqc 报告） | 全量 gitignored（§8）                                                                       |
| `bench/frame/`                      | 抽样框与规划资产（§4）                                                    | 全部入库                                                                                    |
| `bench/fixtures/`                   | 手造陷阱断言底材（`spec/benchmark.md` §B2）                               | 全部入库，逐字节即语义                                                                      |

历史口径：2026-09-20"七库合一"把 `corpus`/`corpus_v2`/`corpus_m1k`/`corpus_iclr` 四库并入统一根；2026-09-21~23 Wave-F 清点进一步把物理载荷迁入 trizone lake、清单统一收 `bench/corpus/`（m1k 四层折为 `manifest_m1k-*.jsonl`）、`corpus_daily` 随日更 soak 链退役删除、zh-store 资产归 vault。各层 manifest 文件名与层语义是跨迁移稳定锚点[^unified]。

### 2.2 单篇 cell 布局（lake）

```
lake/corpus/{source}/{sid}/
  meta.json                 # id/layer/stratum_cell/cluster_id/channel/license/features/渠道字段
  raw/                      # 原始 e-print blob 层（字节级钉版，编译段底材）
  extracted/                # 安全解包过滤树（解析段底材）
```

- `sid` = 安全形 id（`kernel/idnorm.py::safe_id`，`/`→`--`）；`source` ∈ `arxiv`/`sw` 等渠道标签。
- `catalog.jsonl` 是 cell 状态机账本（absent/skeleton/hydrated/raw_only/evicted），`lake.is_complete` 是读谓词（meta 可解析 ∧ extracted 件数与 `n_files` 一致）；skeleton/raw_only 态不满足读谓词，`ctx.src_path()` 按需触发 hydrate（raw 重投影零网络 / fetch_fn 联网双检查锁）。
- `stub`/`pdf_only` 成员只留 raw 不解包（无 `extracted/`），记丢弃原因。
- manifest 行 schema（S4 钉版）：`{id, channel, item, member, blob_sha256, main_tex_sha256, features, stratum_cell, license_class}`；channel ∈ `ia` / `tiger` / `arxiv_eprint` / `hf_scholarweave` / `direct-fetch`（v2 历史标签）。

### 2.3 id 两形与 canon 归一

同一论文存在两种拼写：raw 形 `archive/name`（manifest/records 键）与 canon/安全形 `archive--name`（湖格单层目录名）。转换函数：`kernel/idnorm.py::safe_id`（`/`→`--`）与 `kernel/idnorm.py::canon_id`（幂等归一，附 registry 校验）。**任何 id 匹配/查重工具必须双侧 canon 归一**——`ids=` 参数收 flat 拼写自动回规范形，撞名对（`math/0408287` vs `math--0408287`）归同一 records 键与工作目录；历史上双拼写并存造成过同 wid 并发互删事故[^mixed]。

## 3. 分层 manifest 体系

层 = 一个 `manifest_{layer}.jsonl` 清单 + 明确口径（抽样框/用途/治理）。层枚举由 `specs/_corpus_common/__init__.py::manifest_layers` 按 `bench/corpus/manifest_*.jsonl` 文件名发现——**manifest 文件名即层身份**。

### 3.1 主库层（bench/corpus/）

| 层           | manifest                      |               篇数 | 抽样框与渠道                                                                                                  | 用途/治理                                     |
| ------------ | ----------------------------- | -----------------: | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| core         | `manifest.jsonl`              |              1,000 | 30 月簇（a–d 带 IA 月块 / e 带 TIGER），year_band 5 带 ×200 等分，簇内 cat_group 软配额、cell 内随机抽        | **池化估计唯一来源**；无偏成功率口径          |
| booster      | `manifest_booster.jsonl`      |                200 | 机制台账驱动 agent 策展（§5.1），B01–B07 地板配额                                                             | 机制覆盖层，不进池化                          |
| hot          | `manifest_hot.jsonl`          |                166 | OpenAlex 高引近期（hot-cite 124 按 cited_by_count 降序 / hot-recent 42 随机），`arxiv_eprint` 渠道            | 需求轴 + 时近轴补样，不进池化（frame 非均匀） |
| expand       | `manifest_expand.jsonl`       |              3,866 | cell 配额 = core 配比 × n100 失败率加权，bulk 扫描扩池 + eprint 定点补强                                      | 体量扩样层，不进池化                          |
| holdout      | `manifest_holdout.jsonl`      |              3,020 | bulk 2,699（38 cell flat×2.7，`exclude_cluster_months` 剔除核心 30 簇月）+ eprint recent 321                  | **EVAL_ONLY**（§6），评测/开发月间零泄漏      |
| dev_vol      | `manifest_dev_vol.jsonl`      |              2,000 | fbias 配额（flat × cell 历史失败率偏置 λ=1.0），不排除核心簇月                                                | 修复训练体量层                                |
| dev_failmine | `manifest_dev_failmine.jsonl` |              1,500 | flags 配额：FLAG_RX 机制旗标定向挖旧时代（deadpkg/docstyle209/epsfig/pdftex_prim/pstricks/babel + fill 兜底） | 机制挖掘训练层                                |
| dev_recent   | `manifest_dev_recent.jsonl`   |              1,514 | 2501+ 盲区双通道：scholarweave 脱水 1,065（`figures_stripped` 记账）+ eprint 449                              | 近期 dev 层                                   |
| v1           | `manifest_v1.jsonl`           |                 39 | 手挑陷阱库（裸布局历史形态）                                                                                  | 并入层，对拍基线                              |
| v2           | `manifest_v2.jsonl`           | 217 行（139 在场） | 分层随机钉版本 e-print；manifest 是 fetch-log 含失败项                                                        | 渠道敏感性对拍                                |
| iclr         | `manifest_iclr.jsonl`         |                 25 | ICLR section-study 源语料（扫盘生成）                                                                         | 专题研究底材                                  |

八层（core/booster/hot/expand/holdout/dev_vol/dev_failmine/dev_recent）时点合计 **13,266 篇**；并入 v1/v2/iclr 树后湖内实有 15,126 个物化 cell（`lake/corpus/` 目录计数，含 m1k 各层物化，按 id 去重后的并集口径）。`cluster_id` 前缀区分来源：核心 `Cnn`（30 簇）、`HO*` holdout、`DV*` dev_vol、`DF*` dev_failmine、`HOT` hot 层[^unified]。

### 3.2 m1k 层（并入 bench/corpus/）

m1k 全流程最严测试集折为四个 `manifest_m1k-*.jsonl` 层（实到 997，3 篇 axhot 候选 pdf_only 缺口）[^m1k]：

| 层         |   n | 来源                                                                                            |
| ---------- | --: | ----------------------------------------------------------------------------------------------- |
| m1k-recent | 300 | `corpus_daily` 2026-09-18 公告日 `announce_type∈{new,cross}` 已物化池（daily 链已退役，层冻结） |
| m1k-axhot  | 247 | alphaXiv feed 四榜（Hot 30d/90d + Views/Likes All）最佳榜位排序                                 |
| m1k-iclr   | 200 | `iclr_map` 已映射 arXiv id，年份加权抽样（2024:80/2023:50/2022:35/2021:20/≤2020:15）            |
| m1k-v3     | 250 | v3 主库 dev 层抽样子集（**排除 holdout**——评测贞操层不烧 QA 跑）                                |

### 3.3 corpus_v2 口径

钉版本 e-print 分层随机库：`arxiv.org/src/{id}v{N}` content-disposition 解析版本号，`raw` 字节原样 + `extracted/` 过滤树；`manifest_v2.jsonl` 是 fetch-log（含失败项），在场 139 篇。角色 = 渠道敏感性对拍基线（与 tar 成员渠道抽样框不同，池化时做渠道敏感性检查）[^v3plan]。

### 3.4 corpus_daily（已退役）

日更 soak 滚动窗口（RSS 公告集 → `acquire_source` 物化）随 stagerun 管线于 2026-09-21 整体退役（`f7a2f32c`），`lake/daily/` 残留为历史面，勿重建[^daily]。

## 4. 抽样框（frame）

`bench/frame/` 是全部层抽样的宇宙：`frame.parquet`（3,164,528 行 × 14 列，HF 元数据快照远程列裁剪扫得）+ `frame_raw.parquet` + 簇/配额规划件（`cluster_pick.json`、`allocation-{core,booster}.csv`、`cluster-cat-mix.csv`、item/chunk 索引、license/era 分层表）。schema 关键列：`tar_yymm`（id 内嵌公布月，簇抽样主键）、`year_band`（a≤2006 … e 21-25 / f 2026+ 不进样）、`primary_cat`、`cat_group`（8 组归并）、`license_class`（7 类）、`n_versions`[^frame-alloc]。

实测坑（构建期必须绕）：id 月 ≠ v1 月（+1 月滚动 ~3.1%）→ 簇归属用 `tar_yymm` 不用 v1 月；yymm 字符串比较在 2000 年界断裂 → 转年序键再比；license 是记录级最新版本值；frame 不知成员形态（pdf_only 率由扫描实测，配额按 ~5% 折损预留）[^frame-alloc]。再生路径 = `bench run frame_build`（`--param snapshot_sha=<rev>` 钉 HF revision，是全部 corpus_* spec 的 ord-0 前置）。

## 5. 构建管线（`bench/py/specs/corpus_*.py`）

旧 `bench/py/corpus/build_*.py` 驱动已随 Wave-F 全数改写为 kernel spec（逐件映射 `dev/tools-runbook.md` §3.5）；成员级断点语义不变（状态落湖工作区文件态，可重入续跑）：

| spec            | stage 链                               | 职责                                                                                                                                              |
| --------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frame_build`   | 单件串行                               | `bench/frame/` 13 件抽样框资产再生（payload gitignored，唯一再生路径；全部 corpus builder 前置）                                                  |
| `corpus`        | 簇下载→成员扫描→配额抽样→湖化物化→自检 | P2 主管线：30 簇下载（IA/TIGER chunk，成员级 Range-GET 回取不留整包）→ 流式成员扫描 → cell 内随机配额抽 core → booster 预筛 → `lake.hydrate` 物化 |
| `corpus_expand` | plan→scan→extract                      | expand 层增量扩：stratum_cell 分布 × 故障率偏置 → largest_remainder 配额 → `manifest_expand.jsonl` tracked append                                 |
| `corpus_hot`    | candidates→fetch→report                | hot 层：OpenAlex 候选生成（限流护栏日预算内 `--limit` 续跑）→ `acquire_source` 物化 → 湖/清单双写                                                 |
| `corpus_layers` | plan→scan→extract→qc + recent 臂       | holdout + dev_vol + dev_failmine bulk 臂 + 各层 eprint recent 臂（`acquire_source` 钉版）                                                         |
| `corpus_sw`     | footers→pool→assign→rehydrate          | scholarweave 脱水通道：parquet footer 行组圈 2501+ → 列投影 range-GET → `==== FILE:` 拆包重打 raw.tar.gz → dev_recent 层                          |

辅助件：`bench/py/iclr_*.py` 六件（OpenReview 标题→arXiv id 三档映射、e-print/PDF 取源、双臂章节词数、汇总校准——ICLR 章节长度研究专用）；booster 层选择走分析动词 `bench booster-select`（nominations 池 → booster_selection.jsonl 确定性变换）。

跨管线纪律：bulk 臂磁盘峰值 ≈ 单 chunk；eprint 臂全走产品 `acquire_source`（限速串行、日预算内分批续跑）；成员 tex staging 是 hunter grep/curator 阅读底材[^v3plan][^sw]。

### 5.1 机制台账与补强策展

`bench/corpus/mechanisms.jsonl`（append-only，含 verdict 批注行）——每行一机制 `{mech_id, title, kind: known-trap|suspected|found-in-wild, detection, status: wanted|partial|covered|exhausted, examples[], evidence, notes}`。种子 = fixtures @Tnn + 规格增补 + parsebench 归因 + 野例 W 系[^v3plan]。

补强层产出靠两类 agent 角色：Curator（分带实际打开 tex 阅读，提名 `{id, mech_tags, justification}` + 新机制落账）与 Hunter（领 wanted/partial 台账定向狩猎，检出手段分层 L0 成员名索引 → L1 features flag → L2 staging zgrep → L3 开文件判读；找不到记 `exhausted` + 搜索证据）。提名审计轨迹入库 `bench/corpus/nominations/{agent}.jsonl` + `{agent}.mechs.jsonl`；`bench/nominations/` 另有评测向提名帧（e2e_real_frame、qualframe、wrapfloat_ids）。B01–B07 地板配额：2.09 遗存 / 非 UTF-8 / 深多文件 / 低 TeX 密度类目 / 宏包机制 / 大字节 / 边缘形态[^v3plan]。

## 6. 评测治理

- **池化估计只用 core 层** + 事后分层权重（`w_cell = frame 宇宙 cell 数 / 样本 cell 数`，cell = year_band × cat_group）；其余层按 cell 报命中率，双口径（加权池化 + 宏平均）并列[^v3plan]。
- **EVAL_ONLY 治理**：`kernel/spec.py::EVAL_LAYERS = {"holdout", "eval_only"}`——这些层的 item 只在 spec 声明 `eval=True` 时进帧；dev 侧 spec 枚举自动排除[^layers]。
- **清单根切换**：`TEXLATE_CORPUS` 环境变量换 manifest 根（默认 `bench/corpus`；`specs/_corpus_common/__init__.py::CORPUS` 与 parsebench 等 spec 均走此口径）。
- **QC 门禁**（各层收线同口径）：id 唯一 / 跨层零撞 / meta 齐 / extracted 非空；`%auto-ignore` 占位 stub 最小尺寸 + 正文含量门槛[^layers]。
- **覆盖簿记**：`bench/corpus/eval_coverage.json`（B04/B06 配额宇宙 × 语料实收覆盖，扫成员数与 cell 对账）。

## 7. 版本与冲突

- tar 成员名 `{YYMM}/{id}.gz|pdf` 无版本号 → 四元组钉版、`resolved_version=null`；eprint 臂 `acquire_source` 按当前版钉（v2 渠道存 content-disposition 版本号）。
- 去重键 = id；跨渠道不去重（渠道敏感性本身是测量对象）。
- 同名不同版冲突**双保留**：湖格 `{sid}/` 始终是 manifest 钉版树，落选副本移存 `_alt-versions/{id}/`[^unified]。

## 8. vault —— 付费产物保险库

`$TEXLATE_BENCH_ROOT/vault/` 是付费 LLM 译文与不可再生产物的唯一归并处（继任旧 `bench/zh-store/`）[^zhstore]：

```
vault/{kind}/{sid}/{arm,variant,altseq}/   # 物理叶：kind ∈ zh/splice/state/layoutqc
vault/meta/{esc(sid)}.{key}.json           # 叶描述：files 逐 kind 清单 + bytes + verdict
vault/manifest.jsonl                       # append-only 收编/迁移/slim 台账
vault/quar/{kind}/…                        # 隔离区（验坏/判毒叶）
```

消费约定：要中文译文文本 → `zh` 叶；要成品双语 PDF → `splice` 叶主干同名 pdf（P3 slim 后只留 pdf+arm+log）；续跑播种 → `bench vault restore` 把叶拷回 workdir；验账 → `bench vault verify`（字节级复核）。≥256KiB 叶文件经 `cas-link` 折进 `lake/objects/` 共享 inode——vault 叶是 CAS 投影，恢复/迁移走 vault 动词勿手拷[^retention]。

## 9. 登记纪律

1. `MANIFEST.md` 是清单根唯一人类可读口径：层构成/规模/渠道/勘误都在此收口；条目数以 jsonl 实文件为准。
2. 新增语料必须登记对应 manifest + MANIFEST 更新；数据载荷全量 gitignored（lake 侧重建），仓库内不入 `{id}/` 树。
3. 语料原样不改写；机制发现 → `mechanisms.jsonl` 落账 → `covered` 后 fixture 化（benchmark 侧生长环，见 `spec/benchmark.md` §B2）。
4. 语料渠道取数细节与法务/发布口径归 `research/arxiv/`、`research/corpus/` 档案[^bulk]。

### 参考文献

[^v3plan]: 仓内证据件 [v3-plan](../research/corpus/v3-plan.md)（分层计划定稿）与 [frame-and-allocation](../research/corpus/frame-and-allocation.md)（frame+30 簇配额）。

[^unified]: 仓内证据件 `bench/corpus/MANIFEST.md`（"七库合一"末节 + Wave-F 清单归并口径）；湖内 cell 数以 `lake/corpus/` 目录实数为准。

[^frame-alloc]: 仓内证据件 [frame-and-allocation](../research/corpus/frame-and-allocation.md) 与 [ia-pilot](../research/corpus/ia-pilot.md)（IA 管道实测）；再生 spec `bench/py/specs/frame_build.py` docstring。

[^layers]: 仓内证据件 `bench/py/kernel/spec.py::EVAL_LAYERS` 与 `bench/py/specs/_corpus_common/__init__.py`（manifest 消费面）。

[^m1k]: 仓内证据件 `bench/corpus/MANIFEST_m1k.md`（四层构成与来源口径）。

[^daily]: 仓内证据件 [daily-soak](../research/arxiv/2026-09-19-daily-soak.md)；退役提交 `f7a2f32c`（2026-09-21）。

[^sw]: 仓内证据件 [bulk-channels](../research/arxiv/bulk-channels.md)（scholarweave 通道裁决）与 `bench/py/specs/corpus_sw/__init__.py` docstring。

[^zhstore]: vault 布局/操作契约 `bench/py/kernel/vault/` 包 docstring 与 [bench-redesign-v2-trizone](../spec/bench-trizone.md) §3.10；旧 `bench/zh-store/README.md` 仅存 git 历史。

[^mixed]: 仓内证据件 `bench/py/kernel/idnorm.py::canon_id` docstring（loop1 双拼写并存事故归因）。

[^retention]: 仓内证据件 [2026-09-24 磁盘策略落地](../log/2026-09-24-磁盘策略落地与探针批指标.md) §1（slim/cas-link/prune 收壳实测数字）。

[^bulk]: 仓内证据件 [bulk-channels](../research/arxiv/bulk-channels.md)、[licensing](../research/arxiv/licensing.md)、[post2020-sourcing](../research/corpus/post2020-sourcing.md)。
