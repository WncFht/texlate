# 语料规范 —— arXiv LaTeX 源码评测底材

> spec/ 层唯一事实源：与 `bench/` 磁盘现状对齐。评测器侧（用这些底材怎么测）见 `spec/benchmark.md`；取源渠道裁决与单次调研证据以 `research/` 档案为准，本文不复述实测细节。
> 写作时点注意：语料库正在从统一物理根 `bench/corpus/` 复拆为 `corpus_v3`/`corpus_m1k`/`corpus_v2` 分库（git 已暂存、磁盘迁移在飞）。各层 manifest 文件名与层语义是跨迁移稳定锚点；本文按目标布局写根名，迁移完成前 `bench/corpus/` 仍是实际载体。

## 1. 定位与设计原则

语料是整条管线（解析/翻译/编译/fixloop）的**评测与开发底材**：arXiv e-print 解压原样，入库后不改写——陷阱语义逐字节保留，`bench/fixtures/` 同理。六条设计原则[^v3plan]：

1. **零在线 API 为默认路径**：主体语料来自批量渠道（IA `arxiv-bulk` 月 chunk / HF `TIGER-Lab/arxiv-latex-5T` / HF scholarweave parquet / HF 元数据快照），不请求 arxiv.org → 可复现、无限流、可断点续跑；仅 hot/recent/daily 等"近期轴"层走产品取源路径 `acquire_source`（e-print 钉版，限速串行）。
2. **Measure-then-sample**：bulk tar 给出整月全集 → 先测全体成员真实特征（docclass/文件数/编码/`\input` 深度/包旗标），再按真实分布配额抽样，优于盲抽 id 赌分层命中。
3. **字节保真分级**：raw e-print blob 原样入库（编译段底材，图/.bst/.bbl 齐全才可编）+ `extracted/` 过滤树（解析段底材）；有损源（scholarweave 脱水文本树，无二进制图）只进 dev 层、不进评测/池化。
4. **评测/开发分轨**：核心均匀层回答"成功率多少"（无偏池化估计唯一来源），其余各层回答"这个坑处理了吗/训练调试用什么"——**报告分开，池化只用 core 层**；`holdout` 层为评测贞操层，dev 侧枚举摸不到（§6 治理）。
5. **钉版可复现**：成员级 `(channel, item, member, blob_sha256)` 四元组记 manifest；语料可凭入库脚本重生成。
6. **加层不删层**：新需求开新 manifest 层，旧层原样保留；版本冲突落选树存档 `_alt-versions/`（§9）。

## 2. 物理布局与标识

### 2.1 库根与入库边界

| 根目录 | 角色 | 口径 |
| --- | --- | --- |
| `bench/corpus_v3/` | **主库**——v3 层化语料（§3 表全部层 + v1/iclr 并入层 + 台账/审计件） | manifest/台账/提名/报告入库，`{id}/` 数据 gitignored |
| `bench/corpus_m1k/` | m1k 全流程评测语料（4 源抽样 997 篇） | `manifest_{recent,axhot,iclr,v3}.jsonl` + `MANIFEST.md` 入库，数据 gitignored |
| `bench/corpus_v2/` | v2 分层随机库（钉版本 e-print 渠道） | `manifest.jsonl` + `MANIFEST.md` + `build_corpus.py` 入库 |
| `bench/corpus_daily/` | 日更 soak 滚动窗口（每日增删，生命周期独立，不并入静态库） | `manifest_{公告日}.jsonl` 入库，数据 gitignored |
| `bench/corpus_iclr_pdf/` | ICLR PDF 产物库（OpenReview 官方 PDF，非 e-print 树——663 件时点） | 全量 gitignored |
| `bench/zh-store/` | real 臂 LLM 译文资产库（§8） | 全量 gitignored |
| `bench/frame/` | 抽样框与规划资产（§4） | 全部入库 |

历史口径：2026-09-20 曾"七库合一"——`corpus`/`corpus_v2`/`corpus_m1k`/`corpus_iclr` 四库 paper 树并入 `bench/corpus/` 统一物理根（947 搬移 + 251 去重 + 3 冲突双保留），四库文档折存 `MANIFEST_{v1,v2,m1k}.md`；同日复拆为上表分库布局。合并现场以统一根 MANIFEST 末节为准[^unified]。

### 2.2 单篇 cell 布局

```
{root}/{id}/
  meta.json                 # id/layer/stratum_cell/cluster_id/channel/license/features/渠道字段
  raw.{tar.gz,gz,pdf}       # 原始 e-print blob（字节级钉版，编译段底材）
  extracted/                # 安全解包过滤树（解析段底材）
```

- 新式 id（`YYMM.NNNNN`）平铺；旧式 id（`archive/YYMMNNN`，如 `hep-th/9901001`）按 `archive/name` 两级目录嵌套，与 arXiv 目录结构一致。
- `stub`/`pdf_only` 成员只留 raw 不解包（无 `extracted/`），记丢弃原因——v1 层为裸布局 `{id}/files/`（无 extracted/），属历史形态。
- manifest 行 schema（S4 钉版）：`{id, channel, item, member, blob_sha256, main_tex_sha256, features, stratum_cell, license_class}`；channel ∈ `ia` / `tiger` / `arxiv_eprint` / `hf_scholarweave` / `direct-fetch`（v2 历史标签）。

### 2.3 id 两形与 canon 归一

同一论文存在两种拼写：raw 形 `archive/name`（manifest/records 键）与 canon/安全形 `archive--name`（`work/` 单层目录名）。转换函数：`bench/py/benchlib.py::safe_id`（`/`→`--`）与 `bench/py/stagerun_lib.py::canon_id`（`--`→`/`，幂等归一）。**任何 id 匹配/查重工具必须双侧 canon 归一**——`--ids` 收 flat 拼写自动回规范形，撞名对（`math/0408287` vs `math--0408287`）归同一 records 键与 workdir；历史上双拼写并存造成过同 wid 并发互删事故[^mixed]。

## 3. 分层 manifest 体系

层 = 一个 `manifest_{layer}.jsonl` 清单 + 明确口径（抽样框/用途/治理）。层名由 `bench/py/benchlib.py::manifest_layers` 按 `manifest_*.jsonl` 文件名枚举——**manifest 文件名即层身份**。

### 3.1 v3 层化主库（bench/corpus_v3/ 或迁移期 bench/corpus/）

| 层 | manifest | 篇数 | 抽样框与渠道 | 用途/治理 |
| --- | --- | ---: | --- | --- |
| core | `manifest.jsonl` | 1,000 | 30 月簇（a–d 带 IA 月块 / e 带 TIGER），year_band 5 带 ×200 等分，簇内 cat_group 软配额、cell 内随机抽 | **池化估计唯一来源**；无偏成功率口径 |
| booster | `manifest_booster.jsonl` | 200 | 机制台账驱动 agent 策展（§5），B01–B07 地板配额 | 机制覆盖层，不进池化 |
| hot | `manifest_hot.jsonl` | 166 | OpenAlex 高引近期（hot-cite 124 按 cited_by_count 降序 / hot-recent 42 随机），`arxiv_eprint` 渠道 | 需求轴+时近轴补样，不进池化（frame 非均匀） |
| expand | `manifest_expand.jsonl` | 3,866 | cell 配额 = core 配比 × n100 失败率加权，bulk 扫描扩池 + eprint 定点补强 | 体量扩样层，不进池化 |
| holdout | `manifest_holdout.jsonl` | 3,020 | bulk 2,699（38 cell flat×2.7，`exclude_cluster_months` 剔除核心 30 簇月）+ eprint recent 321 | **EVAL_ONLY**（§6），评测/开发月间零泄漏 |
| dev_vol | `manifest_dev_vol.jsonl` | 2,000 | fbias 配额（flat × cell 历史失败率偏置 λ=1.0），不排除核心簇月 | 修复训练体量层 |
| dev_failmine | `manifest_dev_failmine.jsonl` | 1,500 | flags 配额：FLAG_RX 机制旗标定向挖旧时代（deadpkg/docstyle209/epsfig/pdftex_prim/pstricks/babel + fill 兜底） | 机制挖掘训练层 |
| dev_recent | `manifest_dev_recent.jsonl` | 1,514 | 2501+ 盲区双通道：scholarweave 脱水 1,065（`figures_stripped` 记账）+ eprint 449 | 近期 dev 层 |
| v1 | `manifest_v1.jsonl` | 39 | 手挑陷阱库（裸布局 `{id}/files/`） | 并入层，对拍基线 |
| v2（并入树） | `manifest_v2.jsonl` | 217 行（139 在场） | 分层随机钉版本 e-print；manifest 是 fetch-log 含失败项 | 渠道敏感性对拍 |
| iclr | `manifest_iclr.jsonl` | 25 | ICLR section-study 源语料（扫盘生成） | 专题研究底材 |

v3 八层（core/booster/hot/expand/holdout/dev_vol/dev_failmine/dev_recent）时点合计 **13,266 篇**；并入 v1/v2/iclr 树后物理规模约 14.2k extracted 树 / ~55GB[^unified]。`cluster_id` 前缀区分来源：核心 `Cnn`（30 簇）、`HO*` holdout、`DV*` dev_vol、`DF*` dev_failmine、`HOT` hot 层。

### 3.2 corpus_m1k 库

全流程最严测试语料（实到 997，3 篇 axhot 候选 pdf_only 缺口），`TEXLATE_CORPUS=bench/corpus_m1k` 供 stagerun 全链消费[^m1k]：

| 层 | n | 来源 |
| --- | ---: | --- |
| recent | 300 | `corpus_daily` 2026-09-18 公告日 `announce_type∈{new,cross}` 已物化池 |
| axhot | 247 | alphaXiv feed 四榜（Hot 30d/90d + Views/Likes All）最佳榜位排序 |
| iclr | 200 | `work_iclr/map.jsonl` 已映射 arXiv id，年份加权抽样（2024:80/2023:50/2022:35/2021:20/≤2020:15） |
| v3 | 250 | v3 主库 dev 层抽样子集（**排除 holdout**——评测贞操层不烧 QA 跑） |

### 3.3 corpus_v2 库

钉版本 e-print 分层随机库：`arxiv.org/src/{id}v{N}` content-disposition 解析版本号，`raw.*` 字节原样 + `extracted/` 过滤树；manifest 是 fetch-log（含失败项），在场 139 篇。角色 = 渠道敏感性对拍基线（与 v3 tar 成员渠道抽样框不同，池化时做渠道敏感性检查）[^v3plan]。

### 3.4 corpus_daily 库

日更 soak 滚动窗口：RSS 公告集（cs+math）→ `manifest_{公告日}.jsonl` 枚举 → `acquire_source` 物化 `announce_type∈{new,cross}` 条目。设计 ~1,200 篇/日，批次身份 = 频道 pubDate，已有当日 manifest 幂等跳过；滚动增删、不并入静态库[^daily]。

## 4. 抽样框（frame）

`bench/frame/` 是全部层抽样的宇宙：`frame.parquet`（3,164,528 行 × 14 列，HF 元数据快照远程列裁剪扫得）+ `frame_raw.parquet` + 簇/配额规划件（`cluster_pick.json`、`allocation-{core,booster}.csv`、`cluster-cat-mix.csv`、item/chunk 索引、license/era 分层表）。schema 关键列：`tar_yymm`（id 内嵌公布月，簇抽样主键）、`year_band`（a≤2006 … e 21-25 / f 2026+ 不进样）、`primary_cat`、`cat_group`（8 组归并）、`license_class`（7 类）、`n_versions`[^frame-alloc]。

实测坑（构建期必须绕）：id 月 ≠ v1 月（+1 月滚动 ~3.1%）→ 簇归属用 `tar_yymm` 不用 v1 月；yymm 字符串比较在 2000 年界断裂 → 转年序键再比；license 是记录级最新版本值；frame 不知成员形态（pdf_only 率由扫描实测，配额按 ~5% 折损预留）[^frame-alloc]。

## 5. 构建管线（bench/py/corpus/）

管线脚本与职责（均可重入断点续跑；状态落 `bench/work_*` gitignored 工作区）：

| 脚本 | 子命令/模式 | 职责 |
| --- | --- | --- |
| `build_corpus_v3.py` | plan→probe→fetch→zipsum→scan→frame-lookup→sample→extract / extract-booster | P2 主管线：30 簇下载（IA/TIGER chunk）→ 流式成员扫描（features + tex staging 全留 gzip）→ cell 内随机配额抽 core → booster 候选预筛 → 物化落盘 |
| `build_corpus_expand.py` | plan→scan→extract / fetch-ids / qc | expand 层增量扩：故障率加权配额、旧池复用 + 新池 Range-GET、`--ids-file` 定点补强（台账回收 orphan id 走 eprint 渠道） |
| `build_hot_layer.py` | candidates→fetch→report | hot 层：OpenAlex 候选生成（限流护栏日预算内 `--limit` 续跑）→ `acquire_source` 物化 → `pdf_only` 记 fetch_fail |
| `build_corpus_layers.py` | plan→scan→extract→qc / recent | holdout + dev_vol + dev_failmine bulk 臂（同三段式）+ 各层 eprint recent 臂（`acquire_source` 钉版） |
| `build_sw_layer.py` | footers→pool→assign→rehydrate | scholarweave 脱水通道：parquet footer 行组圈 2501+ → 列投影 range-GET → `==== FILE:` 拆包重打 raw.tar.gz → dev_recent 层 |
| `build_corpus_m1k.py` | select→materialize→emit / all | m1k 四源抽样（recent→axhot→iclr→v3 逐层去重）→ 本地 copytree 优先、缺则 `acquire_source` 补抓 → emit manifest |
| `daily_arxiv.py` | enum→fetch→report | 日更 soak：RSS 公告集枚举 → `acquire_source` 物化 → 报告；`--backfill-list` 补枚举缺口 |
| `corpus_v2/build_corpus.py` | （单跑批量取源） | v2 库构建：分层 id 清单 → e-print 钉版本下载 → 解包落盘 |
| `select_booster.py` | （corpus_v3/ 内） | P3 补强层选择器：nominations/ → booster_selection.jsonl + selection_report.md（B 地板 → W 机制覆盖 → 稀有度填满 ~200） |
| `iclr_map.py` / `iclr_fetch.py` | — | iclr 层辅助：ICLR accepted 标题 → OpenReview/OpenAlex/S2 三档映射 arXiv id → `acquire_source` 物化 |

跨管线共享纪律：bulk 臂磁盘峰值 ≈ 单 chunk（成员级 Range-GET 回取，不留整包）；eprint 臂全走产品 `acquire_source`（限速串行、日预算内分批续跑）；tex staging（成员 tex gzip 全留）是 hunter grep/curator 阅读底材，**不删**[^v3plan][^daily][^sw]。

### 5.1 机制台账与补强策展

`mechanisms.jsonl`（append-only，含 verdict 批注行）——每行一机制 `{mech_id, title, kind: known-trap|suspected|found-in-wild, detection, status: wanted|partial|covered|exhausted, examples[], evidence, notes}`。种子 = fixtures @Tnn + 规格增补 + parsebench 归因 + 野例 W 系[^v3plan]。

补强层产出靠两类 agent 角色：Curator（分带实际打开 tex 阅读，提名 `{id, mech_tags, justification}` + 新机制落账）与 Hunter（领 wanted/partial 台账定向狩猎，检出手段分层 L0 成员名索引 → L1 features flag → L2 staging zgrep → L3 开文件判读；找不到记 `exhausted` + 搜索证据——"还缺什么"本身是产出）。提名审计轨迹入库 `nominations/{agent}.jsonl` + `{agent}.mechs.jsonl`。B01–B07 地板配额：2.09 遗存 / 非 UTF-8 / 深多文件 / 低 TeX 密度类目 / 宏包机制 / 大字节 / 边缘形态[^v3plan]。

## 6. 评测治理

- **池化估计只用 core 层** + 事后分层权重（`w_cell = frame 宇宙 cell 数 / 样本 cell 数`，cell = year_band × cat_group）；其余层按 cell 报命中率，双口径（加权池化 + 宏平均）并列[^v3plan]。
- **EVAL_ONLY 治理**：`bench/py/benchlib.py::EVAL_ONLY_LAYERS = {"holdout"}`——`dev_layers()` 枚举自动排除，评测侧须显式 `--layers holdout`；`corpus_ids()` 仍含全层供跨层去重[^layers]。
- **语料根切换**：`TEXLATE_CORPUS` 环境变量换语料根（`stagerun_lib.CORPUS`，默认指向 v3 主库；soak 用 `corpus_daily`，m1k 用 `corpus_m1k`）。
- **QC 门禁**（各层收线同口径）：id 唯一 / 跨层零撞 / meta 齐 / extracted 非空；`%auto-ignore` 占位 stub 最小尺寸 + 正文含量门槛；QC 明细落 `bench/work_v3/{layer}/qc.md`[^layers]。
- **覆盖簿记**：`eval_coverage.json`（B04/B06 配额宇宙 × 语料实收覆盖，扫成员数与 cell 对账）。

## 7. 版本与冲突

- tar 成员名 `{YYMM}/{id}.gz|pdf` 无版本号 → 四元组钉版、`resolved_version=null`；eprint 臂 `acquire_source` 按当前版钉（v2 渠道存 content-disposition 版本号）。
- 去重键 = id；跨渠道不去重（渠道敏感性本身是测量对象）。
- 同名不同版冲突**双保留**：本根 `{id}/` 始终是 manifest 钉版树，落选副本移存 `_alt-versions/{id}/`（现 3 例）[^unified]。

## 8. zh-store —— 译文资产库

`bench/zh-store/` 是 real 臂付费 LLM 译文的归并资产库，**唯一不可再生资产**（重译烧 token，旧 promo 价买不回）[^zhstore]：

```
{canon_id}/
  zh/                # LLM 译文树（段落级中文 .tex + 结构件 + .xlat-arm.json 臂标记）
  splice/            # 中文成品树（<main>.pdf + .fixloop-entry.pdf 快照 + fixloop 修复现场 + log）
  provenance.json    # {id, source_run, arm, moved_at}
_alt/{canon_id}/{run}/   # 重复翻译落选副本（正主按 run 优先级选出）
```

时点规模 2,247 唯一 id + 30 重译副本 / 26.1G。消费约定：要中文译文文本 → `zh/`；要成品双语 PDF → `splice/<main>.pdf`；replay/修复播种 → 整 `{canon_id}/` 拷回 `work/{id}/` 续跑 compile+fixloop；语料原件 → v3 主库 `{canon_id}/`[^zhstore]。

## 9. 登记纪律

1. `MANIFEST.md` 是各库唯一人类可读口径：层构成/规模/渠道/勘误都在此收口；条目数以 jsonl 实文件为准。
2. 新增语料必须登记对应 manifest + MANIFEST 更新；语料数据树 gitignored（入库边界见各根 `.gitignore`：manifest/台账/提名/报告/脚本入库，`{id}/` 排除）。
3. 语料原样不改写；机制发现 → `mechanisms.jsonl` 落账 → `covered` 后 fixture 化（benchmark 侧生长环，见 `spec/benchmark.md` §B2）。
4. 语料渠道取数细节与法务/发布口径归 `research/arxiv/`、`research/corpus/` 档案，本文不展开[^bulk]。

### 参考文献

[^v3plan]: 仓内证据件 [v3-plan](../research/corpus/v3-plan.md)（分层计划定稿）与 [frame-and-allocation](../research/corpus/frame-and-allocation.md)（frame+30 簇配额）。
[^unified]: 仓内证据件 统一根 `MANIFEST.md` 末节"七库合一"（2026-09-20 合并/复拆口径）；时点规模以文件实数为准。
[^frame-alloc]: 仓内证据件 [frame-and-allocation](../research/corpus/frame-and-allocation.md) 与 [ia-pilot](../research/corpus/ia-pilot.md)（IA 管道实测）。
[^layers]: 仓内证据件 `bench/corpus/MANIFEST.md`"2026-09-19 评测/开发分轨扩层"节与 `bench/py/benchlib.py`。
[^m1k]: 仓内证据件 `corpus_m1k/MANIFEST.md`（迁移期 `bench/corpus/MANIFEST_m1k.md`）与 `bench/work_m1k/report.md`。
[^daily]: 仓内证据件 [daily-soak](../research/arxiv/2026-09-19-daily-soak.md) 与 `bench/py/corpus/daily_arxiv.py` 模块 docstring。
[^sw]: 仓内证据件 [bulk-channels](../research/arxiv/bulk-channels.md)（scholarweave 通道裁决）与 `build_sw_layer.py` docstring。
[^zhstore]: 仓内证据件 `bench/zh-store/README.md`（资产库结构与消费约定）。
[^mixed]: 仓内证据件 `bench/py/stagerun_lib.py::canon_id` docstring（loop1 双拼写并存事故归因）。
[^bulk]: 仓内证据件 [bulk-channels](../research/arxiv/bulk-channels.md)、[licensing](../research/arxiv/licensing.md)、[post2020-sourcing](../research/corpus/post2020-sourcing.md)。
