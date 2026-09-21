# arXiv 许可证体系与译文再分发法务边界

> **结论**：「arXiv perpetual non-exclusive license」只把分发权授给 arXiv 一家，**第三方再分发没有默认法律基础**——官方 reuse FAQ 与 API ToU 明言 redistribution 需版权人许可[^arxiv-reuse][^arxiv-tou]。全量分布：non-exclusive 60.3% / CC 系 ~25% / null(pre-2004 assumed) 14.3%；近窗（≥2023）non-exclusive 降至 46.6%、CC-BY 升至 39.8%——「可公开托管衍生译文」的约 43–47%。license 机读入口 = OAI-PMH `<license>`、RSS `dc:rights` 或 abs 页 `div.abs-license a[href]`；**Atom API 不返回 license**。CC-BY-NC-ND 论文翻译并公开托管 = 直接违约。
> **状态**：现行（法务事实面长期有效；统计为 2026-09 口径时点数据）。`license` 字段已实装进 `PaperMeta`（OAI 源）。server 为本地 BYOK 形态，公开托管 license gate 属前瞻设计未建。
> **日期**：2026-09-14 取证，2026-09-20 重订入库。**非法律意见；面向产品决策的风险定性。**

## 1. arXiv 许可证体系

### 1.1 当前六个选项[^arxiv-license]

| 选项                                          | 许可要点（官方表述）                                                                                       | 对「翻译衍生 + 再分发」的含义                     |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| **CC BY 4.0**                                 | 署名即可 "distribute, remix, adapt, and build upon"，商用允许                                              | 可翻译可托管，须署名 + 标改动                     |
| **CC BY-SA 4.0**                              | 同 BY，且改编物须同许可发布                                                                                | 译文须以 CC-BY-SA 发布                            |
| **CC BY-NC-SA 4.0**                           | 同 SA，且仅非商业                                                                                          | 免费服务可托管；付费/订阅有 NC 风险               |
| **CC BY-NC-ND 4.0**                           | 仅可 "copy and distribute in unadapted form"，非商业，署名                                                 | **译文是改编物→禁止分发**；原文逐字分发也限非商业 |
| **arXiv perpetual non-exclusive license 1.0** | "gives limited rights to arXiv to distribute the article, and also limits re-use of any type"（by others） | 第三方无任何权利；只能个人使用                    |
| **CC Zero (CC0)**                             | 公有领域捐献，无条件                                                                                       | 完全自由                                          |

补充事实：**许可按版本授予且不可撤销**（"different versions of the work can have different licenses"）；除 CC0 外作者保留版权；**arXiv 元数据本身是 CC0**（存 license 字段无版权负担）；"All articles can be viewed and downloaded freely" = 查看下载自由，不等于再分发授权；投稿人想用列表外许可的官方姿势是「选 arXiv license + 论文首页注明实际许可」→ 存在 license 字段与论文内声明不一致的边角。

### 1.2 历史沿革（影响存量分布）

- 1991–2003：无许可选择环节，挂 `assumed-1991-2003`，官方定性 **"functionally equivalent to the arXiv non-exclusive license"**[^arxiv-reuse]；元数据 license 为 null（§2 的 14.3% null 主体即此）。
- 2013 版选项：non-exclusive + CC BY 3.0 + CC BY-NC-SA 3.0 + PD 认证（故存量见 `by/3.0`、`by-nc-sa/3.0` URI）。
- 2020-11-09：新增 **CC BY-NC-ND 4.0**（兼容部分期刊政策），选项重排为自由度降序[^arxiv-blog-nd]——**2020-11 之前的投稿不可能有 ND**。现今 CC 选项均为 4.0。

### 1.3 non-exclusive license 全文（存档取证）

> "I grant arXiv.org a perpetual, non-exclusive license to distribute this article. I certify that I have the right to grant this license. I understand that submissions cannot be completely removed once accepted. I understand that arXiv.org reserves the right to reclassify or reject any submission."

通篇只有给 arXiv.org 的分发授权 + 权利能力确认 + 不可删除告知 + 审核权告知。**没有给读者、镜像方、下游用户的任何条款，也没有给 arXiv 转授权的权利**——所以 arXiv 自己也无权替第三方豁免，ToU 只能如实说「去找版权人」。

## 2. 许可证分布统计（自算，2026-09 快照）

arXiv 官方未发布过公开的 license 占比统计（只在 ToU/FAQ 给定性描述 "overwhelming majority … non-exclusive"[^arxiv-reuse]）。可复现自算路径：HF 镜像 `librarian-bots/arxiv-metadata-snapshot`（日更，每行含 `license` URI 字段）经 datasets-server `/statistics`+`/filter` 直接计数[^hf-meta]；权威慢路是 OAI-PMH 全量收割。**OpenAlex 不可用作 arXiv 许可分布源**——其 arXiv location 的 license 覆盖严重不全（pre-2015 抽样 400/400 全 null），null 无法区分「non-exclusive」与「无数据」。

### 2.1 全量分布（n=3,164,528）

| license URI                                    |      条数 |      占比 |
| ---------------------------------------------- | --------: | --------: |
| `arxiv.org/licenses/nonexclusive-distrib/1.0/` | 1,909,582 | **60.3%** |
| `creativecommons.org/licenses/by/4.0/`         |   578,816 |     18.3% |
| `…/by-nc-nd/4.0/`                              |    89,035 |      2.8% |
| `…/by-nc-sa/4.0/`                              |    65,822 |      2.1% |
| `…/by-sa/4.0/`                                 |    30,433 |      1.0% |
| `…/publicdomain/zero/1.0/` (CC0)               |    21,789 |      0.7% |
| `…/by/3.0/` + `…/by-nc-sa/3.0/` + `…/publicdomain/` |   16,256 |     0.5% |
| null（pre-2004 assumed 为主）                  |   452,795 |     14.3% |

### 2.2 近窗分布（update_date ≥ 2023-01-01，n=1,114,915）

| license           | 条数    | 占比      |
| ----------------- | ------: | --------: |
| non-exclusive     | 519,928 | **46.6%** |
| CC BY 4.0         | 443,955 | **39.8%** |
| CC BY-NC-ND 4.0   |  68,522 |      6.2% |
| CC BY-NC-SA 4.0   |  45,157 |      4.1% |
| CC BY-SA 4.0      |  21,802 |      2.0% |
| CC0               |  13,315 |      1.2% |
| null + 旧版 URI   |   2,236 |      0.2% |

残差 2,236 行（0.2%）= update_date≥2023 的老论文仍挂原许可——pre-2004 篇 license=null 与 pre-2013 时代 3.0/PD URI 落同一桶，两成分占比未分拆。2025+ 延续同趋势：non-exclusive 45.8% / CC-BY 41.0% / NC-ND 6.0%。**读法**：CC 采用率随年代显著上升；对「以近一两年 CS/ML 论文为主」的服务形态：~47% 可合规公开托管译文（BY+SA+CC0+非商业下 NC-SA），~47% 连原文都无权再分发，~6% 禁止衍生托管——ND 占比虽小但绝对量大（近窗 6.9 万篇）不能忽略。

## 3. 机器可读入口

| 入口                | 有无 license                                                                                                              | 证据/说明                                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **Atom API**        | **无**——官方 reuse FAQ 明言 license 不在 search API schema[^arxiv-reuse]                                                  | entry 字段只有 title/id/published/updated/summary/author/link/category + arxiv: 扩展                   |
| **OAI-PMH**         | **有**——`arXiv`/`arXivRaw`/`arXivOld` 均含顶层 `<license>`（anyURI）；`oai_dc` 无；记录级单元素（逐版本许可只见最新值）   | XSD schema 实锤 + [oai-pmh.md](oai-pmh.md) §2 字段矩阵                                                 |
| **RSS**             | **有**——每条 item 的 `dc:rights` 即许可 URI，与 abs/OAI 同一 URL 词表                                                     | [probes.md](probes.md) §A.4/A.7 + [daily-soak.md](2026-09-19-daily-soak.md)；日更增量、仅覆盖公告日    |
| **abs 页 HTML**     | **有**——`div.abs-license > a[href]` 的 href 即许可 URI；CC 许可附 `class="has_license"`+图标；无 `rel=license`/`citation_license` meta | [probes.md](probes.md) §A.4 三实例验证                                                                 |
| **Kaggle/HF 快照**  | 有 `license` 字段（URI 或 null）                                                                                          | §2                                                                                                     |
| e-print 源码包/PDF  | 无结构化 license；CC 论文 PDF 内文可能有作者自注（不可靠），勿依赖                                                          | —                                                                                                      |

工程含义：license 要么走 OAI-PMH（批量建库回溯），要么走 RSS `dc:rights`（日更增量——daily-soak 现走此道），要么解析 abs 页 `abs-license`（单篇随取——与下载 e-print 同域同限速顺路拿）；Atom 拿不到。

## 4. 法律分析

### 4.1 逐许可对「翻译衍生 + 译文 PDF 托管 + 修改源码 tgz 托管」

| 许可                                 | 制作译文（衍生）  | 公开托管译文 PDF | 公开托管 zh.tgz | 条件                                              |
| ------------------------------------ | ----------------- | ---------------- | --------------- | ------------------------------------------------- |
| CC0 / PD                             | ✅                | ✅               | ✅              | 无义务                                            |
| CC BY 4.0/3.0                        | ✅                | ✅               | ✅              | 署名：作者+标题+原许可 URI+改动说明               |
| CC BY-SA 4.0                         | ✅                | ✅（须标 SA）    | ✅（须标 SA）   | BY 义务 + 译作同许可                              |
| CC BY-NC-SA 4.0                      | ✅                | ✅ 仅限非商业    | ✅ 仅限非商业   | BY+SA 义务 + 不得商用                             |
| **CC BY-NC-ND 4.0**                  | ⚠️ 私用可、分享禁 | ❌ **直接违约**  | ❌ **直接违约** | ND：只许逐字、非商业分发；翻译属 Adapted Material |
| **non-exclusive（含 assumed/null）** | ⚠️ 私用灰色       | ❌ 无授权        | ❌ 无授权       | 第三方零权利；须逐篇找版权人                      |

要点：**翻译在 CC 定义下就是改编**——ND 的红线不是「改没改」而是「分发改编物」本身，与是否收费无关；NC 边界在付费墙/订阅场景偏不利，保守策略是 NC 论文永不进计费链路；SA 传染性要求产物内嵌许可页并声明同许可发布；源码 tgz 与 PDF 同一作品同一许可，zh.tgz 衍生性更直接不豁免；**逐版本许可**——托管产物要绑定「所译版本的许可」。

### 4.2 non-exclusive 论文：「惯例容忍」与真实风险

法律地位：第三方**连逐字镜像原文 PDF 都无授权**。唯一成文依据是 API ToU 的「personal use / research purposes 可 retrieve/store/use」[^arxiv-tou]——**到「自己机器上自己看」为止**；ToU 同页禁止在无授权时 "store and serve arXiv e-prints from your servers"。生态现实：大量第三方镜像/工具灰色共存靠的是无人逐案追究 + takedown 后删除，不是权利基础；出版商侧有成规模维权先例（Elsevier v. Sci-Hub/LibGen、对 ResearchGate 施压）。管辖提示：境内主体适用中国著作权法，「个人学习/研究」合理使用同样止于「再公开传播」。

### 4.3 hjfy.top 实际做法定性（对照侦察档案 [../product/hjfy-site.md](../product/hjfy-site.md)）

hjfy 产物三件套 `{id}.pdf`（**原文**）/`{id}_zh_CN.pdf`/`{id}_zh_CN.tgz`，签名 URL 匿名即可访问、无 license 过滤、UI 无许可展示。定性：对约一半 non-exclusive 论文是**无授权逐字再分发 + 无授权衍生分发**，对 ND 论文另加 ND 违约——属「全量敞口」姿势，以社区容忍为事实基础、可运转但结构上不可辩护。**复刻时应把它当反例而非规格。**

### 4.4 自动化访问条款

`help/robots`：_"Indiscriminate automated downloads from this site are not permitted."_ 机器人走 OAI-PMH/API/RSS/bulk(S3)；监控限流，403 后继续猛打视为攻击[^arxiv-robots]。API ToU：≤1 req/3s、单连接、跨机器合计；允许 "retrieve, store, transform, and share descriptive metadata"（CC0）与 "retrieve, store, and use content for personal use or research purposes"[^arxiv-tou]。**结论：下载+翻译+自用全程合规；再托管越线（除非该篇许可允许）；镜像/聚合形态与 ToU 明确冲突。**

## 5. 产品建议

### 5.1 meta 必存 license（两形态通用）

```json
"license": {
  "uri": "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
  "short": "arxiv-nonexclusive | cc-by | cc-by-sa | cc-by-nc-sa | cc-by-nc-nd | cc0-pd | assumed | null",
  "version": "v3",
  "source": "abs-license | oai-pmh | snapshot | pdf-none",
  "fetched_at": "…"
}
```

取数链：单篇走 abs `abs-license` href（与 e-print 同域顺路）；批量建库走 OAI-PMH `<license>`；日更增量走 RSS `dc:rights`。`short` 词表对齐既有 `license_class` 口径（[../corpus/frame-and-allocation.md](../corpus/frame-and-allocation.md) §3 / strata-license.csv 七类）且**版本无关**——旧版 `by/3.0`、`by-nc-sa/3.0` 分别并入 `cc-by`、`cc-by-nc-sa`，版本号由 `version`/`uri` 承载；`publicdomain/` 与 `publicdomain/zero/1.0/` 同归 `cc0-pd`（[../corpus/labels.md](../corpus/labels.md) 实测 2,474 条 PD 认证记录）。`assumed|null` 在 frame 口径中合并记作 `missing`。

### 5.2 本地 BYOK 工具（当前形态）

e-print 下载 + 私人翻译 = ToU 明示的 personal/research use，衍生译文不出本机，敞口 ≈0——**无需 license gate**。仍建议存 license 并在 UI 显示，对 non-CC/ND 论文附「原文许可仅授权 arXiv 分发，译文请勿二次分发」提示；不提供「一键发布译文」出口。

### 5.3 公开服务端（前瞻形态）

**license gate 为硬前置**：`cc0|cc-by|cc-by-sa` → 公开托管（产物内嵌署名页；SA 系声明译文同许可）；`cc-by-nc-sa` → 公开但永不接计费/广告；`cc-by-nc-nd|nonexclusive|assumed|null` → **只翻不公开**（产物仅任务创建者可见、不进公开列表/SEO/CDN 缓存，或直接拒翻 ND 并说明）。原文 PDF 一律不落地、阅读器直链 `arxiv.org/pdf/{id}`。必备配套：takedown/联系邮箱、署名与许可展示、服务条款把「用户请求触发的翻译」与「公开分发」分开表述。按近窗数字估：合规公开面 ~43–47%，~53% 需私有降级——**「公开双语库」永远只能是半个库**，产品叙事要提前接受。

### 参考文献

[^arxiv-license]: arXiv. License 选项说明（六选项、逐版本不可撤销、元数据 CC0）. info.arxiv.org. [help/license](https://info.arxiv.org/help/license/index.html)
[^arxiv-reuse]: arXiv. Reuse FAQ——non-exclusive 不授予 further reuse、redistribution 需版权人许可、search API 无 license 字段. info.arxiv.org. [help/license/reuse](https://info.arxiv.org/help/license/reuse.html)
[^arxiv-tou]: arXiv. API Terms of Use——personal/research use、禁 store-and-serve、3s/单连接限速. info.arxiv.org. [help/api/tou](https://info.arxiv.org/help/api/tou.html)
[^arxiv-robots]: arXiv. Robots 政策——禁无差别自动下载、403 后继续打视为攻击. info.arxiv.org. [help/robots](https://info.arxiv.org/help/robots.html)
[^arxiv-blog-nd]: arXiv blog. 2020-11-09 CC BY-NC-ND 上线公告与选项排序. [blog.arxiv.org](https://blog.arxiv.org/2020/11/09/new-license-option-cc-by-nc-nd-4-0/)
[^hf-meta]: librarian-bots. arxiv-metadata-snapshot（arXiv 元数据镜像，CC0 日更，含 license 字段）. HuggingFace. [datasets/librarian-bots/arxiv-metadata-snapshot](https://huggingface.co/datasets/librarian-bots/arxiv-metadata-snapshot)
