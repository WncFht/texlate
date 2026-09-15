# arXiv 许可证体系与译文再分发法务边界

日期：2026-09-14 · 依据：`info.arxiv.org` 官方文档（license / OAI-PMH / API ToU / robots / reuse FAQ）+ Wayback 存档的 `arxiv.org` 页面（许可文本、abs 页 HTML、2013 版 license 页）+ HuggingFace 镜像的 Cornell arXiv metadata snapshot（3.16M 条全量 license 统计）+ OpenAlex 抽样交叉验证 + `docs/research/product/hjfy-site.md` 侦察结论。**非法律意见；面向产品决策的风险定性。**

## 0. 结论速览

1. **第三方再分发 arXiv 论文没有默认法律基础。**「arXiv perpetual non-exclusive license」全文只有一句授予——投稿人把分发权授给 **arXiv.org 一家**，不含读者/第三方任何权利、不含转授权、不含衍生权。arXiv 官方 reuse FAQ 与 API ToU 说得很直白：_"The overwhelming majority of e-prints are submitted using the arXiv perpetual non-exclusive license, **which does not grant further reuse permissions directly**. In these cases you will need to contact the author directly."_ 以及 _"The redistribution of e-prints requires permission from the copyright holder."_「挂到网上=可镜像」是社区惯例容忍，不是授权。
2. **分布实测（自建，见 §2）**：全量 3.16M 条中 non-exclusive 占 **60.3%**，CC 系合计 ~25%，null（主要 pre-2004 assumed-license）14.3%。**近窗（update_date≥2023）non-exclusive 降至 46.6%，CC-BY 升至 39.8%，CC-BY-NC-ND 6.2%**——hjfy 主攻的新论文语料里「可公开托管衍生译文」的约 43–47%，另一半必须降级为私有。
3. **机器可读入口**：Atom 搜索 API **不返回 license**（官方 reuse FAQ 明言 _"the license for the full text is not a part of the current search API schema"_）；OAI-PMH `arXiv`/`arXivRaw` 两格式都有顶层 `<license>` 元素（schema 实锤）；abs 页 HTML 有 `<div class="abs-license"><a href="{许可URI}">`（Wayback 三实例验证），但无 `rel=license`/`citation_license` meta。
4. **CC-BY-NC-ND 论文翻译并公开托管 = 直接违约**（ND 禁止分发 Adapted Material，CC 法律文本明确将翻译列入改编）。ND 选项 2020-11 才上线，目前占近窗投稿 ~6%。non-exclusive 论文连逐字再分发原文都无权——hjfy 连 `{id}.pdf` 原文都公开托管，敞口比「只托管译文」更大。
5. **产品结论**：meta.json 必须存 `license` 字段（一个字段的成本，两种形态都用得上）。本地 BYOK 形态法务实质安全（下载 + 私人翻译落在 ToU 明示的 "personal use / research purposes" 内）。公开服务端形态必须做 license gate：CC0/BY/BY-SA（非商业下 +NC-SA）→ 公开；non-exclusive/assumed/null/ND → 只翻不托管或登录私有访问；原文 PDF 一律直链 arxiv.org 不落地。

## 1. arXiv 许可证体系

### 1.1 当前六个选项（`info.arxiv.org/help/license`，2026-09-14 实测）

| 选项                                          | 许可要点（官方表述）                                                                                       | 对「翻译衍生 + 再分发」的含义                     |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| **CC BY 4.0**                                 | 署名即可 "distribute, remix, adapt, and build upon"，商用允许                                              | 可翻译可托管，须署名 + 标改动                     |
| **CC BY-SA 4.0**                              | 同 BY，且改编物须同许可发布                                                                                | 译文须以 CC-BY-SA 发布                            |
| **CC BY-NC-SA 4.0**                           | 同 SA，且仅非商业                                                                                          | 免费服务可托管；付费/订阅有 NC 风险               |
| **CC BY-NC-ND 4.0**                           | 仅可 "copy and distribute in unadapted form"，非商业，署名                                                 | **译文是改编物→禁止分发**；原文逐字分发也限非商业 |
| **arXiv perpetual non-exclusive license 1.0** | "gives limited rights to arXiv to distribute the article, and also limits re-use of any type"（by others） | 第三方无任何权利；只能个人使用                    |
| **CC Zero (CC0)**                             | 公有领域捐献，无条件                                                                                       | 完全自由                                          |

补充事实（同页）：

- **许可按版本（version）授予且不可撤销**："different versions of the work can have different licenses"、"the license chosen for each version is irrevocable"。
- 除 CC0 外作者保留版权；**arXiv 元数据本身是 CC0**（我们存 license 字段无版权负担）。
- "All articles on arXiv.org can be viewed and downloaded freely by anyone"——查看下载自由，不等于再分发授权。
- 投稿人若想用列表外许可，官方姿势是「选 arXiv license + 在论文首页注明实际许可」→ **存在 license 字段与论文内声明不一致的边角**。
- 帮助页**未声明默认选项**；2020-11 官方博客说选项列表按「最自由→最受限」排序（CC0 例外）。经验分布（§2）显示 non-exclusive 一直是多数。

### 1.2 历史沿革（影响存量分布）

- 1991–2003：无许可选择环节，论文挂 `assumed-1991-2003` 许可，官方 reuse FAQ 定性 **"functionally equivalent to the arXiv non-exclusive license"**。元数据里 license 字段为 null（§2 的 14.3% null 主体即此）。
- 2013 版选项：non-exclusive + CC BY 3.0 + CC BY-NC-SA 3.0 + PD 认证（故存量里见 `by/3.0`、`by-nc-sa/3.0` URI）。
- 2020-11-09：新增 **CC BY-NC-ND 4.0**（为兼容部分期刊政策），选项重排为自由度降序。**2020-11 之前的投稿不可能有 ND**。
- 现今 CC 选项均为 4.0。

### 1.3 non-exclusive license 全文（Wayback `arxiv.org/licenses/nonexclusive-distrib/1.0/`）

> "I grant arXiv.org a perpetual, non-exclusive license to distribute this article. I certify that I have the right to grant this license. I understand that submissions cannot be completely removed once accepted. I understand that arXiv.org reserves the right to reclassify or reject any submission."

通篇只有给 arXiv.org 的分发授权 + 权利能力确认 + 不可删除告知 + 审核权告知。**没有给读者、镜像方、下游用户的任何条款，也没有给 arXiv 转授权/再许可的权利**——所以 arXiv 自己也无权替我们豁免，ToU 只能如实说「去找版权人」。

## 2. 许可证分布统计（自算）

### 2.1 数据源与方法

arXiv 官方**没有发布过公开的 license 占比统计**（翻遍 blog 存档与帮助站无果；官方只在 ToU/FAQ 里给定性描述 "overwhelming majority … non-exclusive"）。可复现的自算路径：

- **首选**：Cornell 官方 Kaggle `arxiv-metadata-oai-snapshot`（每日刷新；每行含 `license` 字段，URI 形式）。本次用其 HuggingFace 镜像 `librarian-bots/arxiv-metadata-snapshot`（更新至当日，3,164,528 行），经 datasets-server `/statistics`+`/filter` 端点直接计数，无需下载全量。
- **权威慢路**：OAI-PMH `oaipmh.arxiv.org/oai` 全量收割 `arXiv`/`arXivRaw` 格式（ToU：3s/req；~2.4M 条需数周，适合一次性建库后增量同步）。
- **OpenAlex 不可用作 arXiv 许可分布源**：实测其 arXiv location 的 license 覆盖严重不全（pre-2015 抽样 400/400 全 null，2024 年也约半数 null），null 无法区分「non-exclusive」与「无数据」。只能当 CC 下界代理。

### 2.2 全量分布（snapshot 2026-09，n=3,164,528）

| license URI                                    |      条数 |      占比 |
| ---------------------------------------------- | --------: | --------: |
| `arxiv.org/licenses/nonexclusive-distrib/1.0/` | 1,909,582 | **60.3%** |
| `creativecommons.org/licenses/by/4.0/`         |   578,816 |     18.3% |
| `…/by-nc-nd/4.0/`                              |    89,035 |      2.8% |
| `…/by-nc-sa/4.0/`                              |    65,822 |      2.1% |
| `…/by-sa/4.0/`                                 |    30,433 |      1.0% |
| `…/publicdomain/zero/1.0/` (CC0)               |    21,789 |      0.7% |
| `…/by/3.0/`                                    |     7,912 |     0.25% |
| `…/by-nc-sa/3.0/`                              |     5,870 |     0.19% |
| `…/publicdomain/`                              |     2,474 |     0.08% |
| null（pre-2004 assumed 为主）                  |   452,795 |     14.3% |

### 2.3 近窗分布（update_date ≥ 2023-01-01，n=1,114,915；注意 update_date 含老论文修订）

| license                  |    条数 |      占比 |
| ------------------------ | ------: | --------: |
| non-exclusive            | 519,928 | **46.6%** |
| CC BY 4.0                | 443,955 | **39.8%** |
| CC BY-NC-ND 4.0          |  68,522 |      6.2% |
| CC BY-NC-SA 4.0          |  45,157 |      4.1% |
| CC BY-SA 4.0             |  21,802 |      2.0% |
| CC0                      |  13,315 |      1.2% |
| 其余（3.0/PD/null 残差） |  ~2,236 |     ~0.2% |

趋势延续到 **2025+（update_date ≥ 2025-01-01，n=659,983）**：non-exclusive 45.8%（302,207）/ CC-BY 41.0%（270,341）/ NC-ND 6.0%（39,477）/ NC-SA 4.0%（26,346）/ 残差 ~3.3%（SA+CC0 为主）。

**读法**：CC 采用率随年代显著上升（全量 25% → 2023+ ~53%，CC-BY 单项仍在涨）。对 hjfy 那种「以近一两年 CS/ML 论文为主」的服务形态：~47% 可合规公开托管译文（BY 39.8% + SA 2.0% + CC0 1.2% + NC-SA 4.1% 若非商业），~47% 连原文都无权再分发（non-exclusive），~6% 禁止衍生托管（ND）。**ND 占比虽小但绝对量大（近窗 6.9 万篇），不能忽略。**

## 3. 机器可读入口（文档面）

| 入口                                                                                    | 有无 license                                                                                                                                                                                                                        | 证据                                                                                                 |
| --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Atom API**（`export.arxiv.org/api/query`）                                            | **无**。entry 字段表（user-manual §5.2/§3.3.2）只有 title/id/published/updated/summary/author/link/category + `arxiv:` 扩展（primary_category/comment/affiliation/journal_ref/doi）                                                 | 官方 reuse FAQ 明言 _"the license for the full text is not a part of the current search API schema"_ |
| **OAI-PMH**（`oaipmh.arxiv.org/oai`，2025-03 重写后基址；`export.arxiv.org/oai2` 已弃） | **有**。`arXiv` 与 `arXivRaw` 两格式均含顶层 `<license>` 元素（anyURI 值）；`oai_dc` 无。注意 schema 中 license 是**记录级单元素**——「逐版本不同许可」在元数据里只见最新值                                                          | `arXiv.xsd`/`arXivRaw.xsd`（2008/2014 加入）；仅暴露各文最新版本                                     |
| **abs 页 HTML**                                                                         | **有**，`<div class="abs-license"><a href="{许可URI}" title="Rights to this article">…`。CC 许可时加 `class="has_license"` 与图标 `<img src="…/icons/licenses/by-nc-nd-4.0.png">`。**无 `rel=license`、无 `citation_license` meta** | Wayback 三个实例：1706.03762→nonexclusive URI；2308.09224→`by/4.0`；2407.11091→`by-nc-nd/4.0`        |
| _\*citation__meta（Google Scholar 惯例）__                                              | Scholar 收录规范只有 `citation_title/author/publication_date/pdf_url/…`，**规范本身没有 license 标签**；arXiv abs 页实发 `citation_title/author/date/online_date/pdf_url/arxiv_id/abstract`                                         | scholar.google.com/intl/en/scholar/inclusion.html + 同上 abs 快照                                    |
| **Kaggle/HF 元数据快照**                                                                | 有 `license` 字段（URI 字符串或 null）                                                                                                                                                                                              | §2                                                                                                   |
| e-print 源码包 / PDF                                                                    | 无结构化 license 文件；CC 论文 PDF 内文可能有作者自注许可（不可靠），勿依赖                                                                                                                                                         | —                                                                                                    |

**工程含义**：license 获取要么走 OAI-PMH（批量建库），要么解析 abs 页 `abs-license`（单篇随取——与下载 e-print 同域同限速，顺路拿）。Atom 拿不到。

## 4. 法律分析

### 4.1 逐许可对「翻译衍生 + 译文 PDF 托管 + 修改源码 tgz 托管」

| 许可                                 | 制作译文（衍生）  | 公开托管译文 PDF | 公开托管 zh_CN.tgz | 条件                                              |
| ------------------------------------ | ----------------- | ---------------- | ------------------ | ------------------------------------------------- |
| CC0 / PD                             | ✅                | ✅               | ✅                 | 无义务                                            |
| CC BY 4.0/3.0                        | ✅                | ✅               | ✅                 | 署名：作者 + 标题 + 原许可 URI+ 改动说明          |
| CC BY-SA 4.0                         | ✅                | ✅（须标 SA）    | ✅（须标 SA）      | BY 义务 + 译作同许可                              |
| CC BY-NC-SA 4.0                      | ✅                | ✅ 仅限非商业    | ✅ 仅限非商业      | BY+SA 义务 + 不得商用                             |
| **CC BY-NC-ND 4.0**                  | ⚠️ 私用可、分享禁 | ❌ **直接违约**  | ❌ **直接违约**    | ND：只许逐字、非商业分发；翻译属 Adapted Material |
| **non-exclusive（含 assumed/null）** | ⚠️ 私用灰色       | ❌ 无授权        | ❌ 无授权          | 第三方零权利；须逐篇找版权人                      |

要点展开：

- **翻译在 CC 定义下就是改编**（Adapted Material 涵盖 translated/adapted）。所以 ND 的红线不是「改没改」，而是「分发改编物」本身——公开托管 zh_CN.pdf/zh_CN.tgz 即违反，与是否收费无关。CC 官方口径允许为个人使用私下改编——本地工具翻译自读落在安全侧。
- **NC 的边界**：CC 对 NonCommercial 的定义（"not primarily intended for or directed towards commercial advantage or monetary compensation"）在付费墙/订阅场景下偏不利；免费 + 无广告的公开服务通常在安全侧，但一旦有 /pay 页对 NC 论文收费即踩线。保守策略：NC 论文永不进计费链路。
- **SA 传染性**：BY-SA/BY-NC-SA 论文的译文 PDF 与 tgz 本身就是「以同许可发布」的对象——产品要在产物里嵌许可页并对外声明 SA，否则违约。做得到，但要显式做。
- **源码 tgz 与 PDF 同一作品同一许可**，且 zh_CN.tgz 是在源 LaTeX 上改写而来，衍生性比译文 PDF 更直接；规则相同，不因其是「源码」而豁免。
- **逐版本许可**：同一 arXiv id 的 v1/v2 许可可不同（不可撤销）。托管产物要绑定「所译版本的许可」，取 license 时带版本语义（OAI 只给最新版记录级值；abs 页显示当前默认版本）。

### 4.2 non-exclusive 论文：「惯例容忍」与真实风险

- 法律地位：第三方**连逐字镜像原文 PDF 都无授权**，遑论衍生译文。唯一的成文依据是 arXiv API ToU 给的「个人使用/研究目的可 retrieve/store/use」——**到「自己机器上自己看」为止**；ToU 同页禁止 "Store and serve arXiv e-prints (PDFs, source files, or other content) from your servers"（无许可或无授权时）。
- 生态现实：大量第三方（semantic scholar、arxiv-sanity 类镜像、各种 PDF 阅读器/笔记工具、GitHub 上的源码镜像）灰色共存，靠的是**无人逐案追究 + takedown 后删除**，不是权利基础。出版商侧有成规模维权先例（Elsevier v. Sci-Hub/LibGen、对 ResearchGate 的撤稿施压），学术预印本的容忍度高于期刊正式版但无保证。
- 管辖提示：hjfy 是京 ICP 备案境内主体，适用中国著作权法——「个人学习/研究」合理使用同样止于「再公开传播」；翻译权、信息网络传播权都在作者手里。

### 4.3 hjfy.top 实际做法定性（对照 `hjfy-site.md` 侦察）

- 产物三件套 `{id}.pdf`（**原文**）/`{id}_zh_CN.pdf`/`{id}_zh_CN.tgz`，阿里云 OSS 签名 URL，**匿名即可访问已译论文**、无 license 过滤、UI 无许可展示。
- 定性：对占其语料约一半的 non-exclusive 论文是**无授权逐字再分发 + 无授权衍生分发**；对 ND 论文另加 ND 违约；对已埋点未启用的付费通道，将来对 NC 论文构成商用风险。属「全量敞口」姿势——以社区容忍为事实基础，可运转但结构上不可辩护；**我们复刻时应把它当反例而非规格**。

### 4.4 自动化访问条款（文档面）

- `help/robots`：_"Indiscriminate automated downloads from this site are not permitted."_ 机器人走 OAI-PMH / API / RSS / bulk(S3)；监控限流，403 后继续猛打视为攻击「without hesitation or warning」。
- API ToU：旧式 API（OAI-PMH/RSS/arXiv API）**≤1 req/3s、单连接、跨机器合计**，禁绕过限速与冒用凭据。
- 允许："Retrieve, store, transform, and share **descriptive metadata**"（CC0）；"Retrieve, store, and use the **content** of arXiv e-prints for your own **personal use, or for research purposes**"；鼓励建工具但内容回链 abs 页。
- 结论：**下载 + 翻译 + 自用**全程合规；**再托管**越线（除非该篇许可允许）；镜像/聚合形态与 ToU 明确冲突。

## 5. 产品建议

### 5.1 两形态通用：meta.json 必须存 license

```json
"license": {
  "uri": "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
  "short": "arxiv-nonexclusive | cc-by | cc-by-sa | cc-by-nc-sa | cc-by-nc-nd | cc0 | assumed | null",
  "version": "v3",            // 许可对应的论文版本（逐版本许可）
  "source": "abs-license | oai-pmh | snapshot | pdf-none",
  "fetched_at": "…"
}
```

成本一个字段，收益：server 形态的分桶闸、UI 署名 badge、将来批量统计、法务留痕。取数链：单篇走 abs `abs-license` href（与 e-print 同域顺路）；批量建库走 OAI-PMH `arXiv` 格式 `<license>`。

### 5.2 本地 BYOK 工具

- 法务定性：e-print 下载 + 私人翻译 = ToU 明示的 personal/research use；衍生译文不出本机，敞口 ≈ 0。**无需 license gate**。
- 仍建议存 license（5.1）并在 UI 显示：对 non-CC/ND 论文附一句「原文许可仅授权 arXiv 分发，译文请勿二次分发」——把责任边界显式交给用户。
- 不提供「一键发布译文」类出口。

### 5.3 公开服务端（hjfy 形态）

- **license gate 为硬前置**：先取 license 再定服务级。
    - `cc0 | cc-by | cc-by-sa` → 公开托管译文 PDF + tgz；产物内嵌署名页（原标题/作者/arXiv 链接/原许可 URI/「机器翻译衍生作品」声明）；SA 系声明译文以同许可发布。
    - `cc-by-nc-sa` → 公开但**永不接入计费/广告**；若产品将来全面收费，降级为私有。
    - `cc-by-nc-nd | arxiv-nonexclusive | assumed | null` → **只翻不公开**：产物仅对任务创建者可见（登录态 + 短时效签名 URL），不进公开列表/SEO/CDN 公开缓存；或直接拒翻 ND 并在 UI 说明原因（更保守）。
    - 原文 PDF **一律不落地**，阅读器直链 `arxiv.org/pdf/{id}`（ToU 明禁 store-and-serve）。
- 必备配套：takedown/联系邮箱、署名与许可展示（可复刻 arXiv 自己的 `abs-license` 样式）、服务条款里把「用户请求触发的翻译」与「公开分发」分开表述。
- 按 §2.3 近窗数字估：合规公开面 ~43–47%，~53% 需私有降级——这决定了「公开双语库」永远只能是半个库，产品叙事要提前接受。

## 6. 留给实测 agent 的接口

- 枚举 abs-license `href` 的实际值域全集（3.0 URI、assumed URI、CC0/PD 变体的真实字符串形态）。
- Atom API 逐字段实测复核 license 缺席（文档已声明）。
- OAI `arXivRaw` 记录级 license 与「逐版本许可」的关系（schema 只有单 license 元素，疑为最新版值）。
- Kaggle null 构成：pre-2004 assumed 占比 vs 其他缺口。

## 附：本次取证来源

- `info.arxiv.org/help/license/index.html`（六选项、逐版本不可撤销、元数据 CC0）
- `info.arxiv.org/help/oa/index.html`（OAI-PMH 基址/格式/收割策略）
- `info.arxiv.org/help/api/tou.html`（再分发需版权人许可、personal/research use、3s 限速、metadata CC0）
- `info.arxiv.org/help/license/reuse.html`（reuse FAQ：overwhelming majority non-exclusive、abs 页许可位置、search API 无 license）
- Wayback：`arxiv.org/licenses/nonexclusive-distrib/1.0/`（许可全文）、`help/robots.html`（禁爬）、`help/license` 2013 版（历史选项）、abs 页三实例（abs-license 标记）、`OAI/arXiv.xsd`+`arXivRaw.xsd`（license 元素）
- blog.arxiv.org 2020-11-09 存档（CC-BY-NC-ND 上线、选项排序）
- HuggingFace `librarian-bots/arxiv-metadata-snapshot` datasets-server `/statistics`+`/filter`（§2 全部数字）；OpenAlex `works?filter=locations.source.id:S4306400194` 抽样（覆盖缺陷证据）
- `scholar.google.com/intl/en/scholar/inclusion.html`（citation_* 规范，无 license 标签）
