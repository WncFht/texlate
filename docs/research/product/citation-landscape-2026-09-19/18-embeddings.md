# Embedding 与图学习路线调研

论文相似度/推荐在工程上有两条互补路线：**内容派（CBF）**把论文文本编码成向量、用引用图当训练信号（SPECTER 一系）；**图派（GB）**直接用引用图结构本身学 embedding 或相似度（ProNE/node2vec/GNN）。产业实践表明两者互补——CBF 从摘要推断「作者的立场」，GB 从引用推断「学界的回应」，ensemble 效果最好[^multi-persp]。本 lane 把两条线的可用资产、生产系统机制、评测与选型成本逐一核实。

## SPECTER 一系：用引用图监督的文本 embedding

### SPECTER（ACL 2020，奠基）

Cohan 等人在 SciBERT 基础上继续预训练，监督信号是引用图本身：每个训练样本是三元组（query 论文 P_Q、正例 P⁺=被 P_Q 引用的论文、负例 P⁻=未被引用者），用 L2 距离的 triplet margin loss（margin=1）拉近被引对、推远非被引对[^specter]。负例分两档：随机未引用论文是 easy negative，被 P⁺引用但未被 P_Q 引用的二跳邻居是 hard negative[^specter-gh]。输入只有标题+摘要拼接，**推理时不需要任何引用信息**——这是它对新鲜无引论文也能出向量的关键[^specter]。产出 768 维向量，配套发布 SciDocs 评测基准（7 个文档级任务：直接引用预测、共被引预测、分类、推荐、co-view/co-read 等）[^specter]。HF 上有官方模型 `allenai/specter`；注意 errata：原实现是多层 scalar-mix + 平均池化，HF 版取末层 [CLS]，两者下游表现相当[^specter-gh]。官方同时提供两个推理渠道——HF 权重与 S2 线上预计算 embedding——并明确两套向量由不同版本模型产出、不可混用[^specter-gh]。

### SciNCL（EMNLP 2022，修正采样缺陷）

Ostendorff 等人指出 SPECTER 把「被引/未被引」当离散 0/1 相似度信号有两个硬伤：一篇引用了 Q 的论文却可能被采为负例（方向性导致正负样本碰撞），且引用本身含礼貌性引用等噪声[^scincl]。SciNCL 先在引用图上训练图 embedding（DeepWalk 系，无向化全图），再在图 embedding 空间里做受控 kNN 采样：正例取自近邻、负例取自受控间隔之外，得到连续相似度与不碰撞的难正负例[^scincl]。SciDocs 上 12 项指标赢 SPECTER 九项、均值更优；且只需 1% 训练三元组、甚至从通用域 LM 出发微调即可超过基线[^scincl]。HF 模型 `malteos/scincl`，代码 `malteos/scincl`，采样用 FAISS[^scincl-gh]。

### SPECTER2 + SciRepEval（EMNLP 2023，现役主力）

SciRepEval 论文（Singh 等）先建了 24 任务、4 任务格式（CLF 分类 / RGN 回归 / PRX 邻近检索 / SRCH 短文本搜索）的评测基准，内含 SciDocs 子集[^scirepeval]。他们发现 SPECTER/SciNCL 约 70% 预训练数据集中在 CS+BioMed 两个域，跨域泛化差（此前已有独立工作发现 BM25 在 CS/BioMed 之外的域上能打赢 SPECTER 系）[^scirepeval]。SPECTER2 的对策是两阶段：**基座从零预训练于 600 万引用三元组（比 SPECTER 多 10 倍）且横跨 23 个学科领域**；然后在 SciRepEval 训练任务上训练任务格式专用 adapter（分类/回归/邻近/搜索各一），adapter 是挂在每层 transformer 上的线性小模块，基座冻结[^scirepeval][^ai2-blog]。

HF 命名有坑（官方重命名过一次）：`allenai/specter2_base` 是基座，`allenai/specter2` 是 proximity adapter（论文↔论文检索，即 similar-papers 该用的那个），另有 `allenai/specter2_adhoc_query`（短查询编码）、`_classification`、`_regression`[^specter2-hf]。用法是 `AutoAdapterModel` 载基座再挂 adapter，输入 `title + [SEP] + abstract`，取末层 [CLS]，max_length=512[^specter2-hf]。模型同时发在 HuggingFace 和 AWS S3[^specter2-gh]。

成绩：SciRepEval 平均 71.1（SPECTER 67.5、SciNCL 68.8），out-of-train 泛化 74.1；MDCR（Multi-Domain Citation Recommendation）MAP 38.4 / Recall@5 33.0，显著超 BM25（33.7/28.5）[^specter2-gh]。**同篇论文另一个重要实测：通用文本检索模型（E5、MPNet、OpenAI ada-002、Instructor）在 SciRepEval 上全面不如领域专用模型**——直接用通用 embedding 服务论文相似度是有明显缺口的[^scirepeval][^ai2-blog]。

## 可直接消费的资产清单（实测为主）

### Semantic Scholar Datasets（2026-09-19 实测）

`GET https://api.semanticscholar.org/datasets/v1/release/latest` 无鉴权可列出全部数据集；但 `…/dataset/{name}` 取下载链接返回 `{"error":"A valid API key is required"}`——**清单免费、下载需 API key**（实测 2026-09-19）。release 2026-09-17 各数据集官方口径：

| 数据集 | 规模 | 体积 | 内容 |
| --- | --- | --- | --- |
| papers | 200M records | ~45GB（30 片×1.5GB） | 标题/作者/日期/externalIds 等核心元数据 |
| citations | **2.4B records** | ~255GB（30×8.5GB） | citingPaper→citedPaper 边，**带 influential 分类、intent 分类、引用上下文** |
| embeddings-specter_v1 | 120M records | ~840GB（30×28GB） | SPECTER v1 稠密向量 |
| embeddings-specter_v2 | 120M records | ~840GB（30×28GB） | **SPECTER2 产出的稠密向量** |
| abstracts | 100M records | ~54GB | 摘要文本 |
| paper-ids | 450M records | ~15GB | sha ID ↔ corpusId 映射 |
| authors | 75M records | ~3GB | 作者属性 |
| tldrs | 58M records | ~6GB | TLDR 一句话摘要 |
| s2orc_v2 | 16M records | ~180GB | OA PDF 全文解析（句段/文献条目级） |

license 为 ODC-BY（按 S2 一贯口径，本次未逐条复核）；数据集按 release 周期更新、支持 diffs 增量[^s2-datasets]。120M×768 维 fp32 理论 ~369GB，官方报 30×28GB≈840GB 说明存储为 JSONL 文本浮点（压缩前更大），实际下载体积以分片为准（未验证压缩率）。

### SPECTER2 训练资产

6M 引用三元组训练集随 SciRepEval 公开（HF `allenai/scirepeval` 与 AWS S3 双渠道），含 SciNCL 三元组子集；adapter 阶段另加 600K 采样三元组[^specter2-gh]。想自训「自己语料上的 SPECTER 式模型」，这是现成的冷启动燃料。

### 开源代码/权重

`allenai/specter`（代码+HF 权重）、`allenai/SPECTER2`（代码+HF/S3 权重）、`malteos/scincl`（代码+HF 权重）、`THUDM/ProNE`（单文件 Python 参考实现）均公开[^specter-gh][^specter2-gh][^scincl-gh][^prone-gh]。HF 侧 license 未逐卡核验（SPECTER 仓库为 Apache-2.0，HF 权重页未验证）。

## 生产系统机制核实

### OpenAlex related_works：不是引用图算法

一个需要纠正的常见假设：OpenAlex 的 `related_works` **不是**共被引/耦合——官方文档原文为「algorithm finds recent papers with the most concepts/topics in common」，即找**主题重叠最多的近期论文**[^openalex-docs]。OpenAlex Topics 本身是模型打的标签，因此 related_works 本质是「主题向量重合度 × 时间近因」的语义相似，偏新不重引。它适合补足「相似但无引用关系」的发现，不能当引用图谱推荐用。

### Semantic Scholar Recommendations API

公开面：`GET /recommendations/v1/papers/forpaper/{paper_id}`（接受 S2ID/ArXiv/DOI；`limit≤500`；`from` 选池 `recent`（默认，近期论文池）或 `all-cs`（全 CS 池））和 `POST /recommendations/v1/papers/`（正负例论文列表，给 Research Feeds 供电）[^s2-recs-blog][^s2-recs-docs]。实测 2026-09-19：`forpaper/ArXiv:1706.03762?from=all-cs` 未鉴权返回 5 条注意力/NMT 相关论文；同地址 `from=recent` 直接 429——**未鉴权极易限流，正式用必须申 key**。算法官方表述为「learned model of their topical interests」，S2 提供给学术界的 CBF embedding 就是 SPECTER（127M×768）；SciDocs 里的 CoView/CoRead 任务源自 S2 用户行为日志，说明其线上推荐历史上也吃过 co-usage 协同信号[^multi-persp][^s2-recs-blog]。

### CBF×GB 混合的量化论证（重点文献）

arXiv 2407.05836《Academic Article Recommendation Using Multiple Perspectives》是目前对两路线最系统的对比：用 S2 提供的 SPECTER（CBF，127M 摘要×768 维）与 ProNE 谱聚类 embedding（GB，119M 文档×280 维，跑在 200M 论文/20 亿引用边上）做推荐，ANN 检索，结论是 CBF 与 GB 九个维度互补（信号源/时间不变性/先验偏向/规模效应等），ensemble 显著有效[^multi-persp]。两个关键洞察：**CBF embedding 时间不变**（摘要不再变，新文当天即可推）；**GB 推荐偏被引多、偏旧**（引用需时间累积）——这正好解释了为什么生产系统多把 embedding 召回与图信号做级联。

## 图派方法

### 谱方法：ProNE（IJCAI 2019，工业级可跑）

清华 THUDM 的 ProNE 把网络 embedding 分两步：稀疏矩阵分解初始化 + 谱空间传播增强（高阶 Cheeger 不等式调制），单线程 29 小时可嵌 1 亿节点网络，比 20 线程的 LINE/DeepWalk/node2vec 快 10–400 倍[^prone]。谱传播步骤还能当通用增强器，给其他方法产出 +10% 相对提升[^prone]。正是上述 multi-perspectives 论文用来编码 2B 边引用图的方法——是目前已验证能单机组跑全规模学术引用图的图派方案，参考实现 `THUDM/ProNE`[^prone-gh]。

### 随机游走系与 GNN

DeepWalk/LINE/node2vec 是经典基线，但亿级规模训练要「周到月」级[^prone]；在论文推荐语境更多作 benchmark 而非生产选型。GNN 一系代表是 Hu 等人的 **HGT（Heterogeneous Graph Transformer，WWW 2020）**：在 Microsoft Academic Graph 这类异构图（paper-author-venue-field 多类型节点边）上设计类型感知注意力与相对时间编码，做论文-领域/会议/作者的链路预测与下游任务[^hgt]。GNN 的共同问题是 transductive——新节点进图要重训或额外设计 inductive 变体（GraphSAGE 系可缓解），生产上不如「文本 encoder + ANN」灵活；引用预测（citation prediction）本身常被拿来做预训练/评测任务（SciDocs、SciRepEval 都含）。

## 评测面

| 基准 | 内容 | 用途 |
| --- | --- | --- |
| SciDocs | 7 个文档级任务（cite-pred/co-cite/co-view/co-read/分类/推荐/用户活动预测），随 SPECTER 发布[^specter] | embedding 综合体检 |
| SciRepEval | 24 任务 × 4 格式（CLF/RGN/PRX/SRCH），含 SciDocs 子集，区分 in-train/out-of-train 泛化[^scirepeval] | 现役最全基准，HF `allenai/scirepeval` + `_test` 数据 |
| MDCR | 多域引用推荐基准[^specter2-gh] | 检验跨域泛化（SPECTER2 的卖点成绩） |

评测面给的 actionable 结论：①跨域性是 embedding 质量的最大坑（SPECTER v1 的 2 域偏科被 BM25 反杀）；②通用 MTEB 系模型在学术任务上打不过领域模型；③邻近检索（PRX）任务格式与 similar-papers 最对应，选型时优先看 PRX 成绩。

## 选型建议

给「数百万篇论文量级的 similar-papers 服务」三条路线的成本画像：

| 路线 | 资产 | 冷启动 | 量化成本 | 适用 |
| --- | --- | --- | --- | --- |
| A. 吃 S2 specter_v2 dump | 120M 现成向量（需 API key，ODC-BY） | 覆盖 S2 已收录论文 | 下载 ~30 分片；arXiv 子集 ~2.5M×768 fp16≈3.8GB，hnswlib 单机即可；全集 120M 走 IVF-PQ ≈12GB 或 int8 ≈92GB | 起步首选，当天能用 |
| B. 自跑 SPECTER2 proximity 推理 | HF/S3 模型（BERT-base 规模+adapter） | **任何新论文当天可编码**（不需引用） | 2.5M 篇 ≈ A100 数小时 / 消费级 GPU 约一天；max_length 512 截断摘要即可 | 补 S2 缺口与新鲜度 |
| C. 图派层（ProNE 类） | 自建引用图（S2 citations dump 2.4B 边或自抽） | 需引用累积，新文冷启动差 | 单线程 29h/亿节点[^prone]；产出 280d 小向量 | 召回补充/重排信号，补 CBF 的结构盲区 |

推荐组合：**A 打底 + B 补新 + C 做候选扩充与重排**，这正是 multi-perspectives 论文论证有效的 CBF×GB ensemble 形态[^multi-persp]。ANN 侧 arXiv 规模（百万级）hnswlib 单实例足够（召回&gt;95% 常规参数）；上到亿级再换 FAISS IVF+PQ。注意两个工程细节：①S2 下载现在要 API key 且未鉴权端点限流凶（实测 429）；②HF 在本机网络不可达（代理/直连均 SSL EOF，实测 2026-09-19），模型权重可改走 SPECTER2 官方 AWS S3 渠道或 archbox 干净环境。

另两个值得记的风险：SPECTER 两版本 embedding 不可混用（官方明示）[^specter-gh]；OpenAlex related_works 常被误当引用相似度用，实际是主题重叠×新度，不能替代引用图信号[^openalex-docs]。

## 探针产物

`tmp/citation-survey/embeddings/` 下：`s2_datasets_latest.json`（S2 数据集清单，release 2026-09-17）、`s2_spec_v2_files.json`/`s2_citations_files.json`（数据集下载端点 401 证据）、`rec_allcs.json`（S2 recommendations all-cs 池实测返回）、`rec_recent.json`（recent 池 429 限流证据）。

### 参考文献

[^specter]: Cohan, Feldman, Beltagy, Downey, Weld. SPECTER: Document-level Representation Learning using Citation-informed Transformers. ACL 2020. [arXiv:2004.07180](https://arxiv.org/pdf/2004.07180)
[^specter-gh]: AllenAI. SPECTER GitHub README（errata、训练文件格式、API 版本说明）. [github.com/allenai/specter](https://github.com/allenai/specter/blob/master/README.md)
[^scincl]: Ostendorff, Rethmeier, Augenstein, Gipp, Rehm. Neighborhood Contrastive Learning for Scientific Document Representations with Citation Embeddings. EMNLP 2022. [aclanthology.org/2022.emnlp-main.802](https://aclanthology.org/2022.emnlp-main.802/)
[^scincl-gh]: malteos. SciNCL 代码与模型卡. [github.com/malteos/scincl](https://github.com/malteos/scincl/)
[^scirepeval]: Singh, D'Arcy, Cohan, Downey, Feldman. SciRepEval: A Multi-Format Benchmark for Scientific Document Representations. EMNLP 2023. [aclanthology.org/2023.emnlp-main.338](https://aclanthology.org/2023.emnlp-main.338/)
[^ai2-blog]: AllenAI. SPECTER2: Adapting scientific document embeddings to multiple fields and task formats. [allenai.org blog](https://allenai.org/blog/specter2-adapting-scientific-document-embeddings-to-multiple-fields-and-task-formats-c95686c06567)
[^specter2-hf]: AllenAI. allenai/specter2_base / specter2 / specter2_adhoc_query model cards. [huggingface.co/allenai/specter2_base](https://huggingface.co/allenai/specter2_base)
[^specter2-gh]: AllenAI. SPECTER2 GitHub README（重命名表、MDCR 成绩、S3 渠道）. [github.com/allenai/SPECTER2](https://github.com/allenai/SPECTER2)
[^s2-datasets]: Semantic Scholar. Datasets API release 2026-09-17 清单与下载端点（实测）. [api.semanticscholar.org/datasets/v1](https://api.semanticscholar.org/datasets/v1/release/latest)
[^s2-recs-blog]: AI2. Semantic Scholar releases new Recommendations API. [medium.com/ai2-blog](https://medium.com/ai2-blog/semantic-scholar-releases-new-recommendations-api-ca01ef2d80d4)
[^s2-recs-docs]: Semantic Scholar API Guide. Recommendations API（pools/正负例/500 上限）. [semanticscholar-api-docs](https://mulatta.github.io/semanticscholar-api-docs/en/06-recommendations/)
[^openalex-docs]: OpenAlex. Work object documentation — related_works 定义. [openalex-docs](https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/work-object/README.md)
[^multi-persp]: Academic Article Recommendation Using Multiple Perspectives（CBF=SPECTER 127M×768 vs GB=ProNE 119M×280，ANN 服务，九维对比）. [arXiv:2407.05836](https://doi.org/10.48550/arxiv.2407.05836)
[^prone]: Zhang, Dong, Wang, Tang, Ding. ProNE: Fast and Scalable Network Representation Learning. IJCAI 2019. [ijcai.org/proceedings/2019/594](https://www.ijcai.org/proceedings/2019/0594.pdf)
[^prone-gh]: THUDM. ProNE 参考实现. [github.com/THUDM/ProNE](https://github.com/THUDM/ProNE/)
[^hgt]: Hu, Dong, Wang, Sun. Heterogeneous Graph Transformer. WWW 2020（MAG 异构图上的类型感知注意力与时间编码）.
