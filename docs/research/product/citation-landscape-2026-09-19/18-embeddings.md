# Lane 18：Embedding 与图学习路线（SPECTER 系 / ProNE / CBF×GB 混合）

> **结论**：内容派（SPECTER→SciNCL→SPECTER2，引用图当监督信号产出文本向量）与图派（ProNE 谱方法，单机可跑亿级引用图）互补——CBF 从摘要推断「作者的立场」、GB 从引用推断「学界的回应」，ensemble 效果最好；工程选型 = S2 specter_v2 dump 打底 + SPECTER2 自跑补新鲜度 + ProNE 图向量做候选扩充与重排。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## SPECTER 一系：用引用图监督的文本 embedding

**SPECTER**（ACL 2020，奠基）：SciBERT 上继续预训练，监督信号是引用图本身——三元组（query 论文、正例=被引论文、负例=未被引者）L2 triplet margin loss；负例分两档（随机 easy negative + 被正例引用但未被 query 引用的二跳 hard negative）。输入只有标题+摘要，**推理时不需要任何引用信息**——新鲜无引论文当天可出向量，768 维[^specter]。配套 SciDocs 基准（7 个文档级任务）。官方明示两套产出渠道（HF 权重与 S2 线上预计算 embedding）由不同版本模型产出、**不可混用**[^specter-gh]。

**SciNCL**（EMNLP 2022，修正采样缺陷）：指出 SPECTER 把「被引/未被引」当离散 0/1 信号的硬伤——引用了 query 的论文可能被采为负例、引用本身含礼貌性噪声。对策：先在引用图上训图 embedding（DeepWalk 系），再在图 embedding 空间做受控 kNN 采样得到连续相似度与不碰撞的难正负例。SciDocs 12 项指标赢 SPECTER 九项，且只需 1% 训练三元组[^scincl][^scincl-gh]。

**SPECTER2 + SciRepEval**（EMNLP 2023，现役主力）：SciRepEval 基准 24 任务×4 格式（CLF/RGN/PRX/SRCH）；发现 SPECTER/SciNCL 约 70% 预训练数据集中在 CS+BioMed 两域、跨域泛化差（BM25 在其他域能反杀 SPECTER 系）。SPECTER2 对策两阶段：**基座从零预训练于 600 万引用三元组、横跨 23 个学科**；再训任务格式专用 adapter（基座冻结）[^scirepeval][^ai2-blog]。HF 命名有坑：`allenai/specter2_base` 是基座、**`allenai/specter2` 是 proximity adapter（similar-papers 该用的那个）**、另有 `_adhoc_query`/`_classification`/`_regression`；用法 `AutoAdapterModel` 载基座挂 adapter，输入 `title + [SEP] + abstract`，max_length=512[^specter2-hf]。成绩：SciRepEval 平均 71.1（SPECTER 67.5、SciNCL 68.8），MDCR MAP 38.4 显著超 BM25 33.7[^specter2-gh]。同篇论文另一关键实测：**通用文本检索模型（E5/MPNet/ada-002/Instructor）在 SciRepEval 全面不如领域专用模型**——拿通用 embedding 服务论文相似度有明显缺口[^scirepeval]。

## 可直接消费的资产

**S2 Datasets**（release 2026-09-17 实测）：清单端点无鉴权可列、**下载需 API key**。关键数据集：citations **2.4B 边 ~255GB**（带 influential/intent/context 属性）、embeddings-specter_v2 120M×768 ~840GB（30 片可按 ID 过滤流式抽取）、papers 200M ~45GB、abstracts 100M ~54GB、paper-ids 450M 映射、s2orc_v2 16M 全文解析；ODC-BY，按 release 周期更新支持 diffs[^s2-datasets]。

**SPECTER2 训练资产**：6M 引用三元组训练集随 SciRepEval 公开（HF+AWS S3 双渠道）——自训「自己语料上的 SPECTER 式模型」的现成冷启动燃料[^specter2-gh]。开源件：`allenai/specter`、`allenai/SPECTER2`、`malteos/scincl`、`THUDM/ProNE`[^specter-gh][^specter2-gh][^scincl-gh][^prone-gh]。

## 生产系统机制核实

- **OpenAlex related_works 不是引用图算法**：官方原文「finds recent papers with the most concepts/topics in common」——主题向量重合度×时间近因的语义相似，偏新不重引；适合补「相似但无引用关系」的发现，不能当引用图推荐用[^openalex-docs]。
- **S2 Recommendations**：`forpaper/{id}` 的 `from` 参数选池 `recent`（默认）或 `all-cs`；`POST /papers` 正负例给 Research Feeds 供电；未鉴权极易 429，正式用必须申 key[^s2-recs-blog][^s2-recs-docs]。SciDocs 的 CoView/CoRead 任务源自 S2 用户行为日志——其线上推荐历史上也吃过 co-usage 协同信号。
- **CBF×GB 混合量化论证**（arXiv 2407.05836，目前最系统对比）：SPECTER（CBF，127M×768）+ ProNE（GB，119M×280，跑在 200M 论文/20 亿边上）做 ANN 推荐，九维互补、ensemble 显著有效。两个关键洞察：**CBF embedding 时间不变**（摘要不再变，新文当天可推）；**GB 推荐偏被引多、偏旧**（引用需时间累积）——这正是生产系统把 embedding 召回与图信号级联的原因[^multi-persp]。

## 图派方法

**ProNE**（IJCAI 2019，工业级可跑）：清华 THUDM，稀疏矩阵分解初始化+谱空间传播增强（高阶 Cheeger 不等式调制），**单线程 29 小时嵌 1 亿节点**，比 20 线程 LINE/DeepWalk/node2vec 快 10–400 倍；谱传播还能当通用增强器给其他方法 +10% 相对提升——是目前已验证能单机跑全规模学术引用图的图派方案[^prone][^prone-gh]。

随机游走系亿级训练要「周到月」级，更多作 benchmark；GNN 代表 HGT（WWW 2020，MAG 异构图类型感知注意力+相对时间编码），但 transductive——新节点进图要重训或额外设计 inductive 变体，生产上不如「文本 encoder+ANN」灵活[^hgt]。

## 选型路线（数百万篇量级 similar-papers 服务）

| 路线 | 资产 | 冷启动 | 量化成本 | 适用 |
| --- | --- | --- | --- | --- |
| A. 吃 S2 specter_v2 dump | 120M 现成向量（需 key，ODC-BY） | 覆盖 S2 已收录 | arXiv 子集 ~2.5M×768 fp16≈3.8GB，hnswlib 单机即可 | 起步首选，当天能用 |
| B. 自跑 SPECTER2 proximity | HF/S3 模型（BERT-base+adapter） | **任何新论文当天可编码** | 2.5M 篇≈A100 数小时/消费级 GPU 约一天 | 补 S2 缺口与新鲜度 |
| C. 图派层（ProNE 类） | 自建引用图 | 需引用累积，新文冷启动差 | 单线程 29h/亿节点；产出 280d 小向量 | 召回补充/重排，补 CBF 结构盲区 |

推荐组合 **A 打底 + B 补新 + C 做候选扩充与重排**——即 multi-perspectives 论文论证有效的 CBF×GB ensemble 形态。ANN 侧 arXiv 规模 hnswlib 单实例足够，亿级换 FAISS IVF+PQ。两个风险要记住：SPECTER 两版本向量不可混用；S2 下载需 API key 且未鉴权端点限流凶。模型权重除 HF 外另发在 SPECTER2 官方 AWS S3 渠道[^specter2-gh]。

## 结论

embedding 侧「引用图当监督信号」是最经济的融合——向量天然含引用信息且对新文 day-0 可用；图派向量补 CBF 看不到的「学界回应」维度；通用 embedding 模型在学术任务上打不过领域模型，选型只看 SciRepEval PRX（邻近检索）成绩。

### 参考文献

[^specter]: Cohan, Feldman, Beltagy, Downey, Weld. SPECTER: Document-level Representation Learning using Citation-informed Transformers. ACL 2020. [arXiv:2004.07180](https://arxiv.org/pdf/2004.07180)
[^specter-gh]: AllenAI. SPECTER GitHub README（errata、API 版本说明）. [github.com/allenai/specter](https://github.com/allenai/specter/blob/master/README.md)
[^scincl]: Ostendorff, Rethmeier, Augenstein, Gipp, Rehm. Neighborhood Contrastive Learning for Scientific Document Representations. EMNLP 2022. [aclanthology.org/2022.emnlp-main.802](https://aclanthology.org/2022.emnlp-main.802/)
[^scincl-gh]: malteos. SciNCL 代码与模型卡. [github.com/malteos/scincl](https://github.com/malteos/scincl/)
[^scirepeval]: Singh, D'Arcy, Cohan, Downey, Feldman. SciRepEval. EMNLP 2023. [aclanthology.org/2023.emnlp-main.338](https://aclanthology.org/2023.emnlp-main.338/)
[^ai2-blog]: AllenAI. SPECTER2: Adapting scientific document embeddings to multiple fields and task formats. [allenai.org blog](https://allenai.org/blog/specter2-adapting-scientific-document-embeddings-to-multiple-fields-and-task-formats-c95686c06567)
[^specter2-hf]: AllenAI. allenai/specter2_base / specter2 model cards. [huggingface.co/allenai/specter2_base](https://huggingface.co/allenai/specter2_base)
[^specter2-gh]: AllenAI. SPECTER2 GitHub README（重命名表、MDCR 成绩、S3 渠道）. [github.com/allenai/SPECTER2](https://github.com/allenai/SPECTER2)
[^s2-datasets]: Semantic Scholar. Datasets API release 2026-09-17 清单（2026-09-19 实测）. [api.semanticscholar.org/datasets/v1](https://api.semanticscholar.org/datasets/v1/release/latest)
[^s2-recs-blog]: AI2. Semantic Scholar releases new Recommendations API. [medium.com/ai2-blog](https://medium.com/ai2-blog/semantic-scholar-releases-new-recommendations-api-ca01ef2d80d4)
[^s2-recs-docs]: Semantic Scholar API Guide. Recommendations API. [semanticscholar-api-docs](https://mulatta.github.io/semanticscholar-api-docs/en/06-recommendations/)
[^openalex-docs]: OpenAlex. Work object documentation — related_works 定义. [openalex-docs](https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/work-object/README.md)
[^multi-persp]: Academic Article Recommendation Using Multiple Perspectives. [arXiv:2407.05836](https://doi.org/10.48550/arxiv.2407.05836)
[^prone]: Zhang, Dong, Wang, Tang, Ding. ProNE: Fast and Scalable Network Representation Learning. IJCAI 2019. [ijcai.org/proceedings/2019/594](https://www.ijcai.org/proceedings/2019/0594.pdf)
[^prone-gh]: THUDM. ProNE 参考实现. [github.com/THUDM/ProNE](https://github.com/THUDM/ProNE/)
[^hgt]: Hu, Dong, Wang, Sun. Heterogeneous Graph Transformer. WWW 2020.
