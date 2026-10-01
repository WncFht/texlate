# arXiv 层规模化路线（2026-09-19）：广泛 paper 测试的获取面设计

> **结论**：逐篇获取层与抽样框已是业界水准（钉版缓存/降级链/3.16M 行 frame/8 层语料治理），真正的硬缺口只有一条：**「2501+ 近期 + 无损含图 + 规模」三角无免费解**——IA 冻 2020-10、TIGER 止 2412、scholarweave 有损（73% 文件缺失 + 无二进制）、e-print 直采 ~85 篇/日。推荐 era 三分物化 + 增量枚举通道 + pdf_only 测试层 + oracle 校准；S3 付费（近三年 ~$80 / 十年窗 ~$150）是 2501+ 段唯一解、留作决策点。
> **状态**：规划文档（时点证据 2026-09-19 口径）。**缺口 2「无增量通道」曾由 [2026-09-19-daily-soak.md](2026-09-19-daily-soak.md) 落地、该链 2026-09-21 退役**（RSS 枚举+OAI 对账通道设计仍可复用）；pdf_only 物化层、版本漂移对账、S3 决策仍开放。
> **日期**：2026-09-19 定稿，2026-09-20 重订入库

触发：为「在非常广泛的 paper 上测试和修复 pipeline」评估 arXiv 获取层现状与缺口。三路调研：自家审计 + 外部渠道普查 + 工具链/文献调研。前置文档：[bulk-channels.md](bulk-channels.md)、[oai-pmh.md](oai-pmh.md)、[layer.md](layer.md)。

## 1. 现状盘点（已强，不推翻）

- **逐篇层业界水准**：`arxiv/` = fetch（HEAD+etag+ 退避+export 转移+WAF 免疫）/ meta（Atom+OAI-PMH GetRecord）/ locate（主 tex 裁决 + 8 形态 \input 拓扑——严格超集 latexpand 与 unarXive flatten）/ unpack+sniff / ratelimit（per-host 桶+path-class 断路器 + 日预算 ~180 发）/ cache（钉版）。降级链 e-print→HTML→PDF sidecar 已接线。
- **枚举已解**：`bench/frame/frame.parquet` = 3,164,528 行全量抽样框（metadata snapshot + 渠道索引），新式 id 完备率 99.9994%——「从全库分层选样」能力已在手。
- **语料治理完备**：13,266 篇 8 层（core/booster/expand/hot/dev_vol/dev_failmine/dev_recent/holdout），`(channel,item,member,sha256)` 钉版 + EVAL_ONLY 闸 + QC 台账（语料侧档案见 [../corpus/](../corpus/)）。
- **覆盖率基线已实测**：~87% 有 TeX 源、~9-13% pdf-only（年代敏感）、HTML↔源码集合等价、~50% 论文自带 .bbl。
- **批量四通道已跑通**：IA arxiv-bulk（≤2020-10 含图，免费）/ TIGER-Lab（→2412）/ scholarweave（月更但 73% 文件缺失 + 无二进制，判有损限 dev 层）/ e-print 直采（实时，~85 篇/日实测）。

## 2. 缺口清单（按重要性）

1. **2501+ 无损批量断档（唯一硬约束）**：「近期 + 保真含图 + 规模」三角只能选二。TIGER 止 2412、IA 冻 2020-10、scholarweave 有损、e-print 日 ~85 篇——近期评测语料无规模化免费无损路径。
2. **~~无增量通道~~（曾由 daily-soak 落地、2026-09-21 退役）**：frame 是时点快照；OAI-PMH ListIdentifiers/RSS/listing 日更枚举当时全未接线（OAI 实测单日 2715 headers/4s，全量回填 ~2000 页 ≈ 2h，deletedRecord=persistent 可感知撤稿）——后由 RSS 枚举 + OAI 对账补齐，见姊妹篇；该链退役后增量通道回到开放态。
3. **pdf_only 层未建**：~9-13% 宇宙的 L3 降级路径（html→pdf sidecar）零物化语料——目前只记 `*_fail.jsonl`。
4. **版本漂移/撤稿无对账**：sha256 钉版只在重取时暴露漂移；OAI `status="deleted"` 墓碑与 `<version>` 史未消费。
5. **存储/带宽策略**：10 万篇 ≈ 350GB（raw+extracted）；IA ~11MB/s 理论 ~1TB/日，可行但需「raw 保留 / extracted 按需重建」分层留存。

## 3. 外部调研关键事实

- **arXiv robots.txt 明令禁止程序化抓 `/src/`**：S3 requester-pays 是官方认可的批量正道（API 限度 bursts 4 req/s）；惯例 ~1req/3s 的逐篇直采属灰色但普遍[^arxiv-robots]。
- **S3 实测价**（官方 bulk-data 文档口径[^arxiv-bulk]）：近 3 年月 chunk ≈ **$80**；2015–2025 十年窗 1.6TB ≈ **$150**；全量 src ~2.9TB ≈ $260-400。**us-east-1 内 EC2 拉取免 egress**——开源 Rust ETL `arxivETL_sync`（scholarweave 同款上游）即此模式：区内免费消化 S3 再落自家盘[^arxiv-etl]。
- **X-raying the arXiv**（60 万篇实测研究[^xray]）：88.6% 有效 TeX / 9.3% pdf-only / 0.37% 撤稿 stub / **1.6% 主文件难定位**——是我们 L2/L3 降级链与 locate() 的负载基线；其 BaRDE 裁决器 = locate() 简化版（99.9%），可对照核算漏判率。另：~27% e-print 字节是冗余文件（图为主）。
- **ar5iv 分层数据集**（2.17M 篇，2024-04[^ar5iv]）：no_problem 366k / warning 1.3M / error 500k——官方 LaTeXML **无错转换只有 ~75%**，是我们管线成功率的校准 oracle；WithdrarXiv 是撤稿专集。
- **Kaggle/HF 元数据**：Kaggle 周更 JSONL（license/versions 全字段[^kaggle]）、librarian-bots 日更 parquet（CC0[^hf-meta]）、OAI 是 license+ 版本史唯一权威源——枚举底表三源交叉校验即可。
- latexpand 只处理 `\input/\include` 且有 verbatim 误展开 bug；arxiv_latex_cleaner 的注释剥离语义边界（`\iffalse\fi`/verbatim/comment 特例）值得对照我们的 strip_comments。

## 4. 建议路线

### A. 枚举/索引层（便宜先做）

frame.parquet 为主资产，加**增量维护管线**：librarian-bots 日更 snapshot 定期重拉合入 + OAI-PMH `ListIdentifiers&until=昨日` 日增量对账（含 deleted 墓碑 → withdrawn 标记）。Kaggle 周快照做字段级交叉校验。产出 = 持续更新的 universe index，任意维度（era/cat/license/size/version 数/withdrawn）分层选样。

### B. 批量物化（era 三分，S3 是决策点）

- **≤2020-10**：IA arxiv-bulk 继续（含图、member 钉版已跑通）。
- **2021-2024**：TIGER-Lab 主力 + IA 末端补洞（2011/2012 已知特例）。
- **2501+**：三选一——(a) **S3 付费**（推荐重议：~$80 近三年 / ~$150 十年窗，一次解锁无损含图源 + manifest first/last_item 精确二分定位指定 id；此前「不用 S3」是 bench 扩容语境下的裁决，对「非常广泛」目标该裁决应重新评估）；(b) **arxivETL_sync 自跑**（us-east-1 免费消化 S3，零 egress，代价是维护 ETL+EC2）；(c) scholarweave 维持 dev-only。
- **指定小批量 ≤2k**：直采不变（~2.6h 拐点账已算清，见 [bulk-channels.md](bulk-channels.md) §2）。

### C. 测试面补齐

- **pdf_only 层**：把 `*_fail.jsonl` 名单物化成层（raw.pdf 留存），专测 L3 降级链；按 ~9-13% 占比镜像真实负载。
- **滚动增量层**：OAI-PMH/RSS 日增量 → e-print → 「近期真实负载」滚动语料——**曾落地为 corpus_daily、2026-09-21 退役**，通道设计见 [2026-09-19-daily-soak.md](2026-09-19-daily-soak.md)。
- **withdrawn/版本对账**：OAI deletedRecord + 钉版 sha256 定期抽查重验证。
- **oracle 校准**：ar5iv 三档严重度 + X-raying 分布定判分基线——LaTeXML 无错 75% 是参考线，parsebench 目标应锚定高于它。

### D. 存储

10 万篇 ≈ 350GB；raw 保留（钉版语义）、extracted 按需重建；大实验按惯例可移远端容量节点。

## 5. 决策点

**S3 ~$80-150 要不要花**：它是 2501+ 段「无损含图 + 规模」的唯一解；不花则近期评测料只能靠 scholarweave 有损 + 日增量缓慢积累（~85 篇/日，万篇需 ~4 个月）。其余建议（增量通道/pdf_only 层/对账/oracle）零成本可先行。**重订时注：增量通道已落地；S3 决策点仍开放。**

### 参考文献

[^arxiv-robots]: arXiv. Robots 政策——/src/ 程序化抓取限制与批量正道指引。[arxiv.org/robots.txt](https://arxiv.org/robots.txt) / info.arxiv.org [help/robots](https://info.arxiv.org/help/robots.html)

[^arxiv-bulk]: arXiv. Bulk Data Access via S3——requester-pays 定价口径与 manifest 布局。info.arxiv.org. [help/bulk_data_s3](https://info.arxiv.org/help/bulk_data_s3.html)

[^arxiv-etl]: arthiondaena. arxivETL_sync——us-east-1 区内免费消化 S3 桶的开源 Rust ETL（scholarweave 同款上游）. GitHub. [arthiondaena/arxivETL_sync](https://github.com/arthiondaena/arxivETL_sync)

[^xray]: X-raying the arXiv——60 万篇 e-print 形态实测（88.6% TeX / 9.3% pdf-only / 主文件定位难 1.6% / BaRDE 裁决器）. arXiv:2601.11385. [arxiv.org/abs/2601.11385](https://arxiv.org/abs/2601.11385)

[^ar5iv]: ar5iv 分层数据集——2.17M 篇 LaTeXML 转换严重度分档（no_problem/warning/error）. [sigmathling.kwarc.info/resources/ar5iv-dataset-2024](https://sigmathling.kwarc.info/resources/ar5iv-dataset-2024/)

[^kaggle]: Cornell University. arXiv Dataset（元数据 JSONL 周更，license/versions 全字段）. Kaggle. [kaggle.com/datasets/Cornell-University/arxiv](https://www.kaggle.com/datasets/Cornell-University/arxiv)

[^hf-meta]: librarian-bots. arxiv-metadata-snapshot（CC0 元数据 parquet，日更）. HuggingFace. [datasets/librarian-bots/arxiv-metadata-snapshot](https://huggingface.co/datasets/librarian-bots/arxiv-metadata-snapshot)
