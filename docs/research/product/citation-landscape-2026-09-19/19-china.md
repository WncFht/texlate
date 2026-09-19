# 中文学术生态与 OAG 数据集调研

本 lane 覆盖：AMiner/OAG 数据集（重点）、X-MOL、文献鸟 Stork、中文引文库（知网/万方/维普/百度学术）、MAG 遗档可获取性。核心结论先行：**OAG 是目前唯一「免鉴权直链下载、含完整引用边、ODC-BY 许可」的 10⁸ 级学术图**，v3.3 于 2026-09 刚发布（1.71 亿论文、17 个 publication 分卷实测合计 ~117.6GB 压缩），v3.2 官方口径含 12.7 亿条论文-论文引用边；AMiner 开放平台同时提供按次计费的引用关系 API（¥0.10/次）。中文生态的「发现」产品整体偏弱：X-MOL/文献鸟走「期刊订阅+关键词推送」路线，仅文献鸟的「文献引用网络」付费件与引用图谱沾边。

## AMiner（智谱旗下，清华 KEG 系）

### 公司与产品背景

AMiner 前身是 2006 年上线的 ArnetMiner（唐杰团队，清华计算机系 KEG 实验室），ArnetMiner 论文获 ACM SIGKDD 2020 Test-of-Time Award[^arnetminer][^wsdm16]。目前归属 **Z.ai（智谱）**，2025-09 完成大版本升级，检索/问答/速读接入 GLM 旗舰模型，定位「AI-powered academic research assistant」[^aminer-about]。官方口径：覆盖 220 个国家/地区、千万级用户，为 400+ 期刊提供推送服务；数据规模自称 **3.3 亿 paper records、6000 万学者画像、28 亿条 citation relationships、1.8 亿专利、11 万期刊会议、879 万知识实体**，数据源自述为「arXiv、PubMed 等权威公开文献库」[^aminer-about]。

产品面：学术搜索（自然语言改写+多智能体调度）、AI 速读/AI 文献库对话、Deep Research、学者画像（教育/任职/荣誉/论文/专利/项目多维）、机构画像、期刊画像、趋势分析、AI 2000 学者榜、开放平台（数据 API + 开源数据集）[^aminer-upgrade]。知识图谱能力是其叙事核心——「论文间引用、学者间合作、学者与机构隶属、学科主题演化」显式建模为百亿级三元组[^aminer-upgrade]。

### AMiner 开放平台 API（付费面）

开放平台 2023-10 上线，API base `https://datacenter.aminer.cn/gateway/open_platform`，Bearer token（控制台生成）+ `X-Platform` 头[^aminer-openapi][^aminer-skill]。28 个端点按次计费，与本调研直接相关的：**`/api/paper/relation`（论文引用关系）¥0.10/次**、`/api/paper/list/citation/by/keywords` ¥0.10/次；检索类便宜得多——`/api/paper/search` 免费、`search/pro` ¥0.01、`qa/search` ¥0.05、`qa/searchPro` ¥0.30[^aminer-pricing]。即：AMiner 把**引用边当增值数据卖**，检索当引流。社区已有成型的 API catalog 文档（含参数级说明）[^aminer-skill]。

另实测发现开放数据平台的**数据集列表接口裸奔无鉴权**（2026-09-19，经代理直连）：

- `GET https://open.aminer.cn/hub/dataset/tags` → 200，标签树
- `POST https://open.aminer.cn/hub/dataset/infos`（body `{"offset":0,"size":100}`）→ 200，返回全部 **45 个数据集**条目（name/node/edge/link/article_id）
- `GET https://open.aminer.cn/hub/dataset/article?article_id=&lt;id&gt;` → 数据集详情 JSON，`blocks[].content` 为含下载直链的 HTML

清单中与引用图直接相关的两个：

| 数据集 | 节点 | 边 | 页面 |
| --- | --- | --- | --- |
| Open Academic Graph | 152,525,231 papers（AMiner） | 1,935,422,474 relationships | aminer.cn/open-academic-graph |
| Citation | 22,428,114 papers | 249,160,839 citation relationships | aminer.cn/citation |

第二个是经典 AMiner citation 数据集（DBLP+ACM 抽取，论文-引用对，研究用）。其余多为画像/消歧/知识图谱/推荐评测集（WhoIsWho、Scholar Profiling、Entity Tagging、Paper Click 等）。

## OAG（Open Academic Graph）——本 lane 最重要的资产

### 版本谱系（全部经官方 article JSON 取证）

OAG 由清华 KEG 与微软研究院合作构建：LinKG 框架把 MAG 与 AMiner 两张十亿级图做实体对齐（论文 LSH+CNN、venue LSTM、作者异质 GAT），KDD'19 论文报告论文链接对 91,137,597 对、精度 99.10%[^kdd19]。**MAG 于 2021-12-31 停服后，OAG v3 起改为只发布 AMiner 单源图**，linking pairs 也随之停发（官方 Google Group 答复：「Since MAG shut down its service in 2021, OAG v3.1 didn't provide new linking relations」）[^oag-group]。

| 版本 | 发布 | 规模 | 备注 |
| --- | --- | --- | --- |
| v1 | 2017-07 | MAG 166,192,182 + AMiner 154,771,162 papers；64,639,608 linking pairs | 仅 papers+links |
| v2 | 2019-01 | MAG 208,915,369（2018-11 快照）+ AMiner 172,209,563（2019-01）；91.1M paper links、29,841 venue links、1.72M author links | 增加 authors/venues |
| v2.1 | 2020-11 | 同代更新 | **最后一个含 MAG 半边的版本**，下载页 `old.aminer.cn/oag-2-1`[^oag21] |
| v3.0 | 2023-11 | AMiner 单源 | 起换格式 |
| v3.1 | 2024-02 | AMiner 单源 | 无 linking pairs |
| v3.2 | 2025-02 | **152,525,231 papers（2000–2025）、34,891,863 person、156,657 org、77,002 venue**；边：Pub-Pub[Reference] **1,269,112,709**、PubAuthor-Org 223.5M、PubAuthor-Person 378.2M、Pub-Venue 64.6M | 去重解析系统+关系映射改进[^oag32] |
| **v3.3** | **2026-09（本月）** | **Publication 170,897,622**、Person 34,443,192、Venue 95,811、Affiliation 331,779 | 最新，下载直链实测可用[^oag33] |

### OAG v3.3 数据模式与下载（实测 2026-09-19）

Publication schema 字段：`id, title, authors[].{name, org, org_id, id}, venue_id, venue, year, keywords[], references[], n_citation, doi, abstract` —— **`references` 即引用边列表（本图内部 paper id），`n_citation` 即被引数**。四类实体各自成 zip，官方下载页给出阿里云 OSS 直链，**免鉴权、支持 Range**：

| 文件 | 实测大小（Content-Range） |
| --- | --- |
| `v6_oag_publication_1..17.zip` | **合计 117,573,819,986 B ≈ 117.6 GB**（单卷 6.74–6.99 GB × 17） |
| `v6_oag_author.zip` | 1,199,442,530 B（~1.2 GB） |
| `v6_oag_org.zip` | 5,320,265 B |
| `v6_oag_venue.zip` | 1,868,858 B |

格式为 JSONL（沿袭 OAG 历史格式，v3.3 未逐字节验证内部结构——标未验证）。许可证官方原文「OAG is released under **ODC-BY** license」，并要求引用 KDD'19 / TKDE'22 / KDD'08 三篇论文[^oag33]。

历史版本的 Azure blob 直链（`academicgraphv2.blob.core.windows.net/oag/` 与 `/oag-v1/`，Wayback 取证）在本机经代理 TLS EOF、直连超时——**本机不可达，全球可达性未验证**；SourceForge 仅托管 v2 作者名 CSV（116MB，非全量）。**结论：要拿 OAG 走 opendata.aminer.cn 的 OSS 直链即可，不需要 Azure**。

### OAG vs OpenAlex / S2（自建图视角）

- **体量同级**：OAG v3.3 1.71 亿论文、v3.2 12.7 亿引用边；OpenAlex ~2.5 亿 works、S2 ~2.1 亿（后两者数据见各自 lane）。OAG 引用边密度略低但量级可用。
- **许可**：OAG=ODC-BY（署名+相同方式共享义务需逐条核——ODC-BY 允许商用但要求署名并标注改动）；OpenAlex=CC0 最宽松；S2 datasets=ODC-BY 同族。OAG 许可够用于自建服务，但不如 CC0 干净。
- **时效**：OAG 年更节奏（v3.0 2023-11 → v3.1 2024-02 → v3.2 2025-02 → v3.3 2026-09），**没有增量 diff 机制**——每次全量重下 117GB；OpenAlex 月更快照+API 日级，S2 周更 diffs。做「新论文」场景 OAG 滞后明显。
- **ID 互操作**：OAG v3.x 只含 AMiner 内部 id + doi + n_citation，**没有 arXiv id 字段**（v2 时代的 MAG 半边有 MAG id 可接 OpenAlex 的 ids.mag）；要把 OAG 边接到 arXiv 论文上必须自己走 doi/标题匹配——这是它比 OpenAlex/S2 麻烦的关键点（未验证 v3.3 abstract 记录里是否偶现 arXiv id，需抽样核对）。
- **独有价值**：作者画像/机构实体质量高（中文语境作者消歧是 AMiner 祖传强项），PubAuthor-Org/Person 边在 OpenAlex 里没有直接等价物；做「学者-机构-论文」联合发现时 OAG 是现成补充。

## X-MOL（北京衮雪科技）

模式与引用图谱无关但值得对照：**「期刊关注 + 关键词/作者关注」的追更推送**——收录上万种英文期刊（SCIE/ESCI/SSCI/AHCI/EI 几乎全覆盖），日更基本与期刊官网同天；用户关注期刊或设关键词/作者（建议同义词一起输），系统按关注集预筛每日新文献推送；免登录可浏览，微信快捷登录[^xmol-help][^xmol-qq]。本质是「RSS 订阅器+关键词过滤」的产品化，无任何引用图机制；其价值在于证明中文科研用户对「定制化追更」的强需求。

## 文献鸟 Stork（storkapp.cn / storkapp.me）

斯坦福科研人员崔旭（Xu Cui）个人/小团队运营的付费工具，中文界面面向国内科研用户[^stork-about]。核心免费件是**关键词文献推送邮件**（PubMed/期刊源，免费版每关键词每次最多 10 篇、可日/周频）。高级功能按件收费，**每功能 ¥800/年（学术价）/ ¥1600（非学术）**，会员全套餐 ¥17,996/年[^stork-membership]；Pro 加影响因子/中科院分区过滤、限定期刊、每关键词上限提到 200[^stork-pro]。

与本调研直接相关的是付费件**「文献引用网络」**[^stork-citenet]：

- 输入关键词 → 实时检索相关文献（示例 154/209/6371 篇不等）→ 构建可交互引用网络图；**x 轴=发表时间，节点大小=「影响分数」**——多数情况下=该文献在「本关键词命中集内」的被引次数（领域内被引而非全局被引），新发表文献以期刊影响因子兜底；
- 交互：拖拽/缩放/拖单点，点节点看作者年份，再点看标题摘要；「该文献引用情况」给被引次数+具体引用/被引清单；
- 过滤：Keep Top N% 只留高影响节点；下方文献表（最多 Top 1000）含作者/年/刊/PMID/影响分数/被引数，可导 CSV；
- 也可输入 PMID/DOI 分析单篇文献的引用-被引关系（「顺藤摸瓜」式扩展）；
- 数据源原为 PubMed（生物医学生态），**2026-05 更新支持全学科检索（内测）**——底层疑似切换到全学科引用源（OpenAlex 类，未验证）；实测其 citenet 页挂出「PubMed 官方服务器接口问题，暂时无法获取被引数据」公告[^stork-citenet-page]。

评价：这是中文学界里**唯一产品化的引用网络发现件**，设计取向「5 分钟看懂一个领域的经典文献」——领域内被引归一化 + 时间轴布局 + Top N% 过滤，都是值得借鉴的朴素而有效的取舍；其 2026-05 转向全学科说明引用网发现需求已溢出生物医学。

## 中文引文库与镜像生态（简评）

- **知网 CNKI 中国引文数据库、万方、维普**：中文学位/期刊引文索引，彼此割裂、机构订阅制、无公开 bulk；对 arXiv/英文国际文献基本不覆盖——对本项目价值≈0（细节未验证）。
- **百度学术**：检索+被引数+「相关文献」推荐，引用数据疑来自 Crossref 等公开源（未验证）；无开放 API。
- **谷歌学术镜像/导航站**（X-MOL 旗下亦有镜像件、文献鸟「流畅谷歌学术」付费件）：灰产型可用性工具，非数据资产。
- 中文用户习惯差异：追更靠「订阅推送」（X-MOL/文献鸟/公众号），发现靠「关键词检索+被引排序」，引用图谱可视化类产品在中文世界几乎空白（文献鸟 citenet 是孤例）——**「引用图谱做发现」对中文用户反而是新鲜卖点，不被既有习惯绑架**。

## MAG（Microsoft Academic Graph）遗档可获取性

MAG 停服后由 OurResearch 继承进 OpenAlex（官方迁移路径，专利数据除外）[^mag-openalex]。原始 MAG 快照仍可得：**Zenodo `10.5281/zenodo.6511057` 托管 2021-09-13 快照**（zstd 压缩，ODC-BY）——`Papers.txt.zst` 19.8GB→72GB、`PaperReferences.txt.zst` 7.9GB→40.5GB（**全量引用边单表**）、`PaperAuthorAffiliations` 13.4GB 等 12 文件共 ~52.5GB；完整 ~160GB 压缩因上传限额未全放，维护者可按需索取[^zenodo-mag]。MAG id 仍被 OpenAlex 的 `ids.mag` 与 OAG v2.x linking pairs 引用，作 ID 桥仍有价值。

## 数据源对比结论

1. **OAG v3.3 是可以今天就开始下载的完整学术图**：117.6GB 压缩、1.71 亿论文、`references` 引用边内嵌、ODC-BY、免鉴权 OSS 直链——自建引用图的第三数据源，与 OpenAlex/S2 同级体量。
2. OAG 三个短板要认账：**年更无 diff**（新论文滞后数月）、**无 arXiv id 字段**（接 arXiv 要 doi/标题自匹配）、v3.x 起**失去 MAG 半边的跨源校核**（v2.1 linking pairs 还能当历史桥）。
3. AMiner 把引用关系按次卖（¥0.10/call），说明其官方定位是「数据 vendor」而非「发现层产品」——AMiner 的图谱能力都进了自家搜索/画像，没有独立的引用发现产品线。
4. 中文生态对「发现」的主流解法是订阅推送（X-MOL）与关键词提醒（文献鸟），引用图谱发现仅文献鸟 citenet 一例且是付费小件——**中文侧没有 Connected Papers 级产品，空档明显**。
5. MAG 遗档（Zenodo 52.5GB 核心集）值得顺手收：`PaperReferences` 边表 40.5GB 文本是 2021 年前的全量引用图化石，可做数据校验与历史回填。

### 参考文献

[^arnetminer]: Tang et al. ArnetMiner: Extraction and Mining of Academic Social Networks. KDD 2008. [doi.org](https://dl.acm.org/doi/10.1145/1401890.1402008)
[^wsdm16]: Tang. AMiner: Toward Understanding Big Scholar Data. WSDM 2016. [keg.cs.tsinghua.edu.cn](https://keg.cs.tsinghua.edu.cn/persons/jietang/publications/WSDM16-Tang-AMiner.pdf)
[^kdd19]: Zhang et al. OAG: Toward Linking Large-scale Heterogeneous Entity Graphs. KDD 2019. [dl.acm.org](https://dl.acm.org/doi/10.1145/3292500.3330785)、[PDF](https://keg.cs.tsinghua.edu.cn/jietang/publications/KDD19-Zhang-et-al-Open_Academic_Graph.pdf)
[^aminer-about]: AMiner. About AMiner. 2026. [aminer.cn](https://www.aminer.cn/aboutus/en-US/about)
[^aminer-upgrade]: AMiner. “搜、读、写”一站搞定，AMiner全面升级. 2026. [aminer.cn](https://www.aminer.cn/aboutus/zh-CN/articles/68d0e8cf0bdaf175736bca8e)
[^aminer-openapi]: AMiner. AMiner开放平台｜集中、高效且易于访问的数据资源. 2023. [aminer.cn](https://www.aminer.cn/aboutus/zh-CN/articles/655733362ab17a07228377c5)
[^aminer-pricing]: AMiner. 开放平台 API 文档. [open.aminer.cn](https://open.aminer.cn/open/docs)
[^aminer-skill]: AMiner Open Platform API Complete Reference（社区整理）. [github.com](https://github.com/AI-SOIL-Lab/AIRA-Skill/blob/master/skills/aminer-data-search/references/api-catalog.md)
[^oag-group]: Open Academic Graph Google Group. [groups.google.com](https://groups.google.com/g/open-academic-graph)
[^oag21]: AMiner. OAG 2.1 下载页. [old.aminer.cn](https://old.aminer.cn/oag-2-1/oag-2-1)
[^oag32]: AMiner. OAG 3.2 article（open.aminer.cn/hub/dataset/article?article_id=67aaf63af4cbd12984b6a5f0，实测 2026-09-19）. [open.aminer.cn](https://open.aminer.cn/open/article?id=67aaf63af4cbd12984b6a5f0)
[^oag33]: AMiner. OAG 3.3 发布页（含 v6 下载直链，实测 2026-09-19）. [aminer.cn](https://www.aminer.cn/aboutus/zh-CN/articles/6aa27e4e675c8612fa63599e)
[^zenodo-mag]: Microsoft Academic Graph 2021-09-13 snapshot. Zenodo. [doi.org](https://doi.org/10.5281/zenodo.6511057)
[^mag-openalex]: Scheidsteger et al. Comparison of metadata with relevance for bibliometrics between MAG and OpenAlex. 2022. [arxiv.org](https://arxiv.org/pdf/2206.14168)
[^xmol-help]: X-MOL. 怎样设置关键词/作者关注. [x-mol.com](https://www.x-mol.com/article/help/q2016)
[^xmol-qq]: 免费追踪文献的平台，比肩谷歌学术. 腾讯新闻 2021. [news.qq.com](https://news.qq.com/rain/a/20211130A0D1HR00)
[^stork-about]: 文献鸟. 关于文献鸟 Stork. [storkapp.cn](https://www.storkapp.cn/about.php)
[^stork-membership]: 文献鸟. 文献鸟会员价格页. [storkapp.me](https://www.storkapp.me/marketing/templates/Stork1/membership.php)
[^stork-pro]: 文献鸟. Pro 功能页（IF/分区过滤与定价）. [storkapp.cn](https://www.storkapp.cn/marketing/templates/Stork1/pro.php)
[^stork-citenet]: 文献鸟. 文献引用网络功能页. [storkapp.cn](https://www.storkapp.cn/marketing/templates/Stork1/citenet.php)
[^stork-citenet-page]: 文献鸟. 文献引用网络入口页（PubMed 故障公告，实测 2026-09-19）. [storkapp.cn](https://www.storkapp.cn/citenet/)

## 探针产物

`tmp/citation-survey/china/`：`FINDINGS.txt`（全部实测数字与结论）、`infos.json`/`tags.json`（AMiner 开放数据 API 原始返回）、`oag_article.json`/`oag32.json`（OAG v3.3/v3.2 官方 article 含 schema 与直链）、`oag_v33_sizes.txt`（17 个 publication zip 实测字节数）、`umi_open.js`（开放平台上层 bundle，API 路由取证）、`oag_wayback.html`（Azure blob 历史直链取证）、`gg.html`/`thudm_page.html`/`oag21.html`/`oag31.html`/`stork_cit.html`。
