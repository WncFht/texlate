# ADR-0009 批量语料渠道：IA/TIGER/scholarweave/e-print 四通道 + frame 抽样框

> **状态**：现行（S3 付费为未决项）
> **日期**：2026-09-15（05 §5.9 批量层初裁）| 更新 2026-09-19（规模化路线定案）

## 上下文

终目标是「所有 arXiv 论文干净翻译」——评测语料与未来的批量预译都需要规模化获取。e-print 直采有日 ~85–180 篇硬限，撑不起语料扩张；arXiv robots.txt 明令禁止程序化抓 `/src/`，S3 requester-pays 是官方认可的批量正道。需要回答：各年代段走哪个渠道、怎么枚举选样、近期段（2501+）无损含图源从哪来。

## 裁决

- **枚举层**：`frame.parquet` 全量抽样框（metadata snapshot + 渠道索引，约 316 万行、新式 id 完备率 99.9994%）为主资产；增量维护 = librarian-bots 日更 parquet 定期重拉 + OAI-PMH `ListIdentifiers` 日增量对账（含 `deleted` 墓碑 → withdrawn 标记）+ Kaggle 周快照字段级交叉校验。
- **批量物化 era 三分**：≤2020-10 走 IA `arxiv-bulk`（含图、免费、member 钉版已跑通）；2021–2024 走 TIGER-Lab `arxiv-latex-5T` 主力 + IA 末端补洞；scholarweave 月更通道判有损（73% 文件缺失、无二进制），限 dev 层。
- **指定小批量 ≤2k**：e-print 直采不变。
- **滚动增量层**：OAI-PMH/RSS 日增量 → e-print 取源 → `corpus_daily` 滚动语料（每日增删、独立生命周期，不并入评测层）。
- **S3 requester-pays 暂不决**：约 $80 近三年 / ~$150 十年窗 / 全量 ~2.9TB $260–400，是 2501+ 段「无损含图 + 规模」的唯一解；此前「不用 S3」是 bench 扩容语境下的裁决，对「非常广泛」目标值得翻盘——列为决策点，同区 EC2 免 egress 自跑 ETL 是备选。
- **存储纪律**：10 万篇 ≈ 350GB；raw 保留（钉版语义）、extracted 按需重建。
- **校准 oracle**：ar5iv 分层数据集（官方 LaTeXML 无错转换只有 ~75%）+ X-raying 分布（88.6% 有效 TeX / 9.3% pdf-only / 1.6% 主文件难定位）作判分基线[^xray-arxiv][^ar5iv]。

## 理由

- 「近期 + 保真含图 + 规模」三角只能选二：TIGER 止 2412、IA 冻 2020-10、scholarweave 有损、e-print 日 85 篇——2501+ 无损批量是规模化唯一硬约束。
- OAI-PMH 实测单日 2715 headers/4s、全量回填约 2h——增量通道便宜先做。
- 证据：调研档案 `research/arxiv/2026-09-19-scale-roadmap.md`、`research/arxiv/bulk-channels.md`、`research/arxiv/oai-pmh.md`；主仓 `docs/05` §5.9（S3 manifest 切块 + 引用排序 edges.jsonl → rank.txt，同 region EC2 免 egress）。

## 演变

- 2026-09-15：批量层定位 M4 远期（S3 + 引用排序预译语料）。
- 2026-09-19：规模化路线升级——「广泛 paper 测试」目标下，枚举增量、era 三分渠道、pdf_only 物化层、withdrawn 对账、oracle 校准五件先行；S3 付费重议为显式决策点。daily soak 管线已启动（RSS→export→corpus_daily→stagerun，约千篇/日量级滚动）。

## 现状

落地为 `bench/frame/frame.parquet` 抽样框 + `bench/py/corpus/` 管线（`build_corpus_{v2,v3,layers,expand,sw}` + `build_hot_layer` + `daily_arxiv`）+ `bench/corpus_daily/` 滚动语料库；S3 通道未启用（决策点挂账）。逐篇通道实现见 ADR-0008。

### 参考文献

[^xray-arxiv]: X-raying the arXiv——60 万篇 e-print 形态实测（88.6% 有效 TeX / 9.3% pdf-only / 1.6% 主文件难定位）. arXiv:2601.11385. [arxiv.org/abs/2601.11385](https://arxiv.org/abs/2601.11385)
[^ar5iv]: ar5iv 分层数据集——2.17M 篇 LaTeXML 转换严重度分档（no_problem/warning/error）. [sigmathling.kwarc.info/resources/ar5iv-dataset-2024](https://sigmathling.kwarc.info/resources/ar5iv-dataset-2024/)
