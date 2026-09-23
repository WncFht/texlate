# Lane 19：中文学术生态与 OAG 数据集

> **结论**：OAG 是目前唯一「国内 OSS 直链免鉴权、含完整引用边、ODC-BY 许可」且仍在更新的 10⁸ 级学术图（OpenAlex 快照同为免鉴权 bulk 全量边、CC0 更宽松，但走 S3；MAG Zenodo 化石同为 ODC-BY 免鉴权但停更于 2021-09）——v3.3（2026-09）1.71 亿论文、17 个分卷合计 ~117.6GB，`references`/`n_citation` 字段内嵌；短板是年更无 diff、无 arXiv ID 字段、v3 起失去 MAG 半边。中文生态「发现」产品整体偏弱：X-MOL/文献鸟走订阅推送路线，仅文献鸟 citenet 与引用图谱沾边——中文侧没有 Connected Papers 级产品，空档明显。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## AMiner（智谱旗下，清华 KEG 系）

前身 2006 年 ArnetMiner（唐杰团队，SIGKDD 2020 Test-of-Time）[^arnetminer][^wsdm16]；现归 Z.ai，2025-09 大版本升级接入 GLM 旗舰模型，定位 AI-powered academic research assistant。官方口径：3.3 亿 paper records、6000 万学者画像、**28 亿条 citation relationships**、1.8 亿专利[^aminer-about]。知识图谱是叙事核心——论文引用、学者合作、学者-机构隶属、学科演化显式建模为百亿级三元组[^aminer-upgrade]。

**开放平台 API（付费面）**：Bearer token 计费，与本调研直接相关的 `/api/paper/relation`（论文引用关系）**¥0.10/次**、citation/by/keywords ¥0.10/次；检索类便宜——`/api/paper/search` 免费、search/pro ¥0.01、qa/searchPro ¥0.30[^aminer-openapi][^aminer-pricing]。即 AMiner 把**引用边当增值数据卖、检索当引流**——官方定位是数据 vendor 而非发现层产品，图谱能力都进了自家搜索/画像。

开放数据平台的数据集列表接口无鉴权可访问（2026-09-19 实测）：45 个数据集中与引用图直接相关的两个——**OAG**（152,525,231 papers / 1,935,422,474 relationships）与经典 **AMiner Citation 集**（22,428,114 papers / 249,160,839 边，DBLP+ACM 抽取研究用）[^aminer-skill]。

## OAG —— 本 lane 最重要的资产

OAG 由清华 KEG 与微软研究院合作构建：LinKG 框架把 MAG 与 AMiner 两张十亿级图做实体对齐（KDD'19：91,137,597 对链接、精度 99.10%）[^kdd19]。**MAG 2021-12-31 停服后 OAG v3 起改为只发 AMiner 单源图**，linking pairs 停发[^oag-group]。版本谱系：v2.1（2020-11）是最后含 MAG 半边的版本；v3.2（2025-02）152.5M papers、Pub-Pub[Reference] 边 **1,269,112,709**；**v3.3（2026-09）Publication 170,897,622**、Person 34.4M、Venue 95,811、Affiliation 331,779[^oag21][^oag32][^oag33]。

**v3.3 数据模式与下载**（2026-09-19 实测）：Publication schema 字段 `id, title, authors[].{name,org,org_id,id}, venue_id, venue, year, keywords[], references[], n_citation, doi, abstract`——**`references` 即引用边列表（内部 paper id）、`n_citation` 即被引数**。四类实体各自成 zip，官方下载页给阿里云 OSS 直链、**免鉴权支持 Range**：`v6_oag_publication_1..17.zip` 合计 **117,573,819,986 B ≈ 117.6GB**，author 1.2GB、org/venue 数 MB[^oag33]。JSONL 格式，许可证 **ODC-BY**。历史版本的 Azure blob 直链（Wayback 取证）当前可达性未验证；SourceForge 仅托管 v2 作者名 CSV——**拿 OAG 走 opendata.aminer.cn 的 OSS 直链即可**。

**OAG vs OpenAlex/S2（自建图视角）**：体量同级（OAG 1.71 亿篇（v3.3）/12.7 亿边（v3.2 口径） vs OpenAlex ~2.5 亿 works、S2 ~2.1 亿）；许可 ODC-BY 够用但不如 OpenAlex CC0 干净；**年更无 diff**（每次全量重下 117GB，新论文场景滞后明显，OpenAlex 月更+API 日级、S2 周更 diffs）；**无 arXiv id 字段**（接 arXiv 要走 doi/标题自匹配——比 OpenAlex/S2 麻烦的关键点）；独有价值在作者画像/机构实体质量高（中文作者消歧是祖传强项），PubAuthor-Org/Person 边在 OpenAlex 无直接等价物。

## X-MOL 与文献鸟

**X-MOL**（北京衮雪科技）：「期刊关注+关键词/作者关注」追更推送——上万种英文期刊日更与官网同天，按关注集预筛推送[^xmol-help][^xmol-qq]。本质是 RSS+关键词过滤的产品化，无任何引用图机制；证明中文科研用户对定制化追更的强需求。

**文献鸟 Stork**：斯坦福科研人员个人运营的付费工具，核心免费件是关键词文献推送邮件；高级功能按件收费 **¥800/年/功能（学术价）**，会员全套餐 ¥17,996/年[^stork-about][^stork-membership][^stork-pro]。与本调研直接相关的是付费件**「文献引用网络」**：输入关键词→检索相关文献→构建可交互引用网络图，**x 轴=发表时间、节点大小=「影响分数」（多数情况=该文献在关键词命中集内的被引次数——领域内被引而非全局被引，新文以期刊影响因子兜底）**；Keep Top N% 过滤、Top 1000 文献表可导 CSV、支持 PMID/DOI 单篇顺藤摸瓜[^stork-citenet][^stork-citenet-page]。数据源原为 PubMed，2026-05 起内测全学科检索。评价：**中文学界唯一产品化的引用网络发现件**——领域内被引归一化+时间轴布局+Top N% 过滤是朴素而有效的取舍，且转向全学科说明引用网发现需求已溢出生物医学。

## 中文引文库与镜像生态（简评）

知网 CNKI/万方/维普：中文学位期刊引文索引，割裂、机构订阅制、无公开 bulk，对 arXiv/英文文献基本不覆盖——对本项目价值≈0。百度学术：检索+被引数+相关文献，引用数据疑来自 Crossref 等公开源，无开放 API。谷歌学术镜像/导航站是灰产型可用性工具非数据资产。**中文用户习惯：追更靠订阅推送、发现靠关键词检索+被引排序，引用图谱可视化类几乎空白**——「引用图谱做发现」对中文用户反而是新鲜卖点，不被既有习惯绑架。

## MAG 遗档可获取性

MAG 停服后由 OpenAlex 继承（专利除外）[^mag-openalex]；原始快照仍在：**Zenodo `10.5281/zenodo.6511057` 托管 2021-09-13 快照**（zstd，ODC-BY）——`Papers.txt.zst` 19.8GB→72GB、**`PaperReferences.txt.zst` 7.9GB→40.5GB（全量引用边单表）**、共 12 文件 ~52.5GB；完整 ~160GB 因上传限额未全放[^zenodo-mag]。MAG id 仍被 OpenAlex `ids.mag` 与 OAG v2.x linking pairs 引用，作 ID 桥与历史回填仍有价值。

## 结论

OAG v3.3 是今天就能开始下载的第三数据源（与 OpenAlex/S2 同级体量），但年更无 diff、无 arXiv id、失 MAG 半边三个短板要认账；AMiner 按次卖引用关系说明其定位是 vendor；中文生态发现产品仅文献鸟 citenet 一例且是付费小件——中文侧没有 Connected Papers 级产品，对中文用户做引用图谱发现是未被既有习惯绑架的空档；MAG Zenodo 化石值得顺手收做校验与回填。

### 参考文献

[^arnetminer]: Tang et al. ArnetMiner: Extraction and Mining of Academic Social Networks. KDD 2008. [dl.acm.org](https://dl.acm.org/doi/10.1145/1401890.1402008)

[^wsdm16]: Tang. AMiner: Toward Understanding Big Scholar Data. WSDM 2016. [keg.cs.tsinghua.edu.cn](https://keg.cs.tsinghua.edu.cn/persons/jietang/publications/WSDM16-Tang-AMiner.pdf)

[^kdd19]: Zhang et al. OAG: Toward Linking Large-scale Heterogeneous Entity Graphs. KDD 2019. [dl.acm.org](https://dl.acm.org/doi/10.1145/3292500.3330785)

[^aminer-about]: AMiner. About AMiner. 2026. [aminer.cn](https://www.aminer.cn/aboutus/en-US/about)

[^aminer-upgrade]: AMiner. AMiner 全面升级. 2026. [aminer.cn](https://www.aminer.cn/aboutus/zh-CN/articles/68d0e8cf0bdaf175736bca8e)

[^aminer-openapi]: AMiner. AMiner 开放平台. 2023. [aminer.cn](https://www.aminer.cn/aboutus/zh-CN/articles/655733362ab17a07228377c5)

[^aminer-pricing]: AMiner. 开放平台 API 文档. [open.aminer.cn](https://open.aminer.cn/open/docs)

[^aminer-skill]: AMiner Open Platform API Complete Reference（社区整理）. [github.com](https://github.com/AI-SOIL-Lab/AIRA-Skill/blob/master/skills/aminer-data-search/references/api-catalog.md)

[^oag-group]: Open Academic Graph Google Group. [groups.google.com](https://groups.google.com/g/open-academic-graph)

[^oag21]: AMiner. OAG 2.1 下载页. [old.aminer.cn](https://old.aminer.cn/oag-2-1/oag-2-1)

[^oag32]: AMiner. OAG 3.2 article（实测 2026-09-19）. [open.aminer.cn](https://open.aminer.cn/open/article?id=67aaf63af4cbd12984b6a5f0)

[^oag33]: AMiner. OAG 3.3 发布页（含 v6 下载直链，实测 2026-09-19）. [aminer.cn](https://www.aminer.cn/aboutus/zh-CN/articles/6aa27e4e675c8612fa63599e)

[^zenodo-mag]: Microsoft Academic Graph 2021-09-13 snapshot. Zenodo. [doi.org/10.5281/zenodo.6511057](https://doi.org/10.5281/zenodo.6511057)

[^mag-openalex]: Scheidsteger et al. Comparison of metadata between MAG and OpenAlex. 2022. [arxiv.org/pdf/2206.14168](https://arxiv.org/pdf/2206.14168)

[^xmol-help]: X-MOL. 怎样设置关键词/作者关注. [x-mol.com](https://www.x-mol.com/article/help/q2016)

[^xmol-qq]: 免费追踪文献的平台，比肩谷歌学术. 腾讯新闻 2021. [news.qq.com](https://news.qq.com/rain/a/20211130A0D1HR00)

[^stork-about]: 文献鸟. 关于文献鸟 Stork. [storkapp.cn](https://www.storkapp.cn/about.php)

[^stork-membership]: 文献鸟. 会员价格页. [storkapp.me](https://www.storkapp.me/marketing/templates/Stork1/membership.php)

[^stork-pro]: 文献鸟. Pro 功能页. [storkapp.cn](https://www.storkapp.cn/marketing/templates/Stork1/pro.php)

[^stork-citenet]: 文献鸟. 文献引用网络功能页. [storkapp.cn](https://www.storkapp.cn/marketing/templates/Stork1/citenet.php)

[^stork-citenet-page]: 文献鸟. 文献引用网络入口页（实测 2026-09-19）. [storkapp.cn](https://www.storkapp.cn/citenet/)
