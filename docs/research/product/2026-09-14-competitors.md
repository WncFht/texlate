# 竞品侦察：arXiv 阅读/翻译生态

> **结论**：「LaTeX 源码 → 中译 → 保排版全文产物」生态位上 hjfy 是唯一者；最接近的是豆包/元宝的 PDF 双语对照与沉浸式翻译 + BabelDOC 组合。ar5iv 与 arxiv.org/html 同引擎同覆盖，可作 HTML 降级链第二源。
> **状态**：时点证据（2026-09-14 口径）
> **日期**：2026-09-14

方法：各站实测 + GitHub 源码逆向（hjfy 生态）。hjfy 本体详规见 `2026-09-14-hjfy-site.md`，本文聚焦竞品与 ar5iv 降级源结论。图例：✅=有 / ⚠️=有但弱或需登录付费 / ❌=无。

## 1. 竞品矩阵

| 服务                                  | 形态                                                  | 双语对照                                 | 全文翻译                                                  | 免费？                                      | 与 hjfy 的核心差异                                                          |
| ------------------------------------- | ----------------------------------------------------- | ---------------------------------------- | --------------------------------------------------------- | ------------------------------------------- | --------------------------------------------------------------------------- |
| **幻觉翻译 hjfy.top**（被复刻对象）   | SPA：双 pdfslick 并排 PDF（可同步滚动）               | ✅ 左右分屏 PDF                          | ✅ LaTeX 源码级 zh 重编译 PDF + .tgz 源码                 | 内测免费；100 篇/天；登录建任务             | —                                                                           |
| **alphaXiv**                          | arXiv 增强层：AI Overview + 问答 + 讨论社区           | ❌                                       | ⚠️ `/zh/abs/{id}` 只译标题/摘要/AI 概览，正文仍是英文 PDF | 免费为主；Assistant 有 "Smart" 分层（登录） | **HTML 理解层，不做全文中译 PDF**；卖点是 grounded Q&A/社区而非翻译         |
| **沉浸式翻译 (immersivetranslate)**   | 浏览器扩展；arXiv 专属 adapter 自动加载 ar5iv/HTML 版 | ✅ 段落上下对照（原上译下）              | ✅ 全文 HTML 双语                                         | 基础免费；Pro 解锁高阶引擎                  | 运行时注入双语，不产生新产物；**正是 ar5iv 最大下游消费者**                 |
| **BabelDOC**（沉浸式翻译系 PDF 管线） | PDF→PDF 重排版翻译（开源）                            | ✅ 双语 PDF                              | ✅                                                        | 开源免费 + 付费云版                         | 不走 LaTeX 源码、走 PDF 版面解析；与我们的 LaTeX 路线互补/竞品              |
| **papers.cool**（苏剑林 bojone）      | arXiv/会议论文 feed + tantivy 搜索                    | ⚠️ 摘要中英切换（Desc Language）         | ❌（正文靠 Kimi 摘要或浏览器翻译）                        | 免费                                        | 发现层：每天新论文列表 + `[Kimi]` 跳转 kimi.ai 总结；不做全文翻译           |
| **SciSpace**                          | Chat-with-PDF + Copilot 划词解释 + 文献库             | ❌                                       | ⚠️ 上传 PDF 问答/摘要，非对照翻译                         | 免费额度；Plus ~$12–20/月                   | 通用 PDF 助手，无 arXiv 源码级翻译                                          |
| **HF Papers**                         | 每日论文榜 + 社区评论/投票                            | ❌                                       | ❌                                                        | 免费                                        | 纯发现 + 讨论层                                                             |
| **ReadPaper**                         | 国产：翻译 + 阅读 + 搜索 + 管理一体                   | ⚠️ 划词/段落翻译                         | ⚠️ 上传 PDF 翻译（收费定位）                              | 部分免费，翻译是卖点功能                    | PDF 上传路线，非 arXiv 源码重编译                                           |
| **豆包（浏览器插件/网页）**           | 通用助手：arXiv 直链/PDF 上传                         | ✅ 一键翻译后「原版 + 译版并排」中英对照 | ✅ PDF 翻译保格式                                         | 免费                                        | **功能上最接近 hjfy 的大众产品**，但走 PDF 版面路线非 LaTeX 源码            |
| **腾讯元宝**                          | 长文精读：论文/财报场景                               | ⚠️ 网页端公式渲染好的中译阅读            | ✅ PDF 直译                                               | 免费（需登录）                              | 下载版公式退化为 LaTeX 代码；主打精读总结非双语产物                         |
| **Kimi**                              | 对话式读论文（URL/PDF）；papers.cool 内嵌入口         | ❌                                       | ❌（问答/摘要）                                           | 免费                                        | `kimi --print` CLI 可 agentic 地下载 arXiv 源码翻译——概念同构但无产品化产物 |
| **有道 arxiv 翻译**                   | 网页：喂 ar5iv/abs URL 翻译                           | ✅ 网页双语                              | ✅ HTML 页翻译                                            | 免费                                        | 通用网页翻译，用户手动喂 ar5iv 链接                                         |

**生态位结论**：与 hjfy **正面撞车**（LaTeX 源码→中译→保排版全文产物）的只有 hjfy 自己；最接近的是豆包/元宝的「PDF 双语对照阅读」（PDF 版面路线，非源码级）与沉浸式翻译+BabelDOC（HTML 注入/PDF 重排）。alphaXiv 撞的是「arXiv 增强阅读」心智但不撞全文翻译。

## 2. alphaXiv 详查（直接竞品候选）

> 本节为 2026-09-14 注册墙外侦察口径；alphaXiv 现状的唯一事实源是 [2026-09-19-alphaxiv-reverse.md](2026-09-19-alphaxiv-reverse.md)（免鉴权 REST 面 + SDK 端点枚举的完整逆向），本节内容被其全面取代。

- **注册墙外可见**：Explore feed、搜索（含中文查询）、`/abs/{id}` 页 = AI Overview（博客式导读，嵌图/公式）、Audio、Discussion 评论楼、Similar papers、Cite、作者/机构页、GitHub 链接。`/zh/abs/{id}` 路由存在：标题 + 摘要+Overview 中译，**正文不译**（仅 "View Paper" 跳原 PDF）。
- **功能**：AI Overview、Assistant（grounded Q&A，"Smart" 档）、行内评论/讨论、AI detection（Pangram）、MCP server（`/docs/mcp`）、Autoresearch（openresearch.sh）、Chrome 扩展（"understand-research"）[^alphaxiv]。
- **模型线索**：第三方实测称默认 **Gemini Flash** 系（中英问答皆可，2026-09-14 口径）；官方未公开。已被本仓更新逆向取代：[2026-09-19-alphaxiv-reverse.md](2026-09-19-alphaxiv-reverse.md) 的「内容管线」节（Assistant 实为 Fast/Smart/Pro 三档 13 模型菜单，无单一默认；podcast=Claude 4.1 Opus、retrieval=Qwen3-8B 微调）与「看不到的部分与补全手段」节（翻译延迟指向 flash/mini 档）。
- **定价**：无公开 pricing 页；Assistant 分层 + 登录留存（"Sign in to save"）。
- **形态差异**：alphaXiv = HTML 理解层（导读 + 问答 + 社区），hjfy = 产物层（可下载的 zh 重编译 PDF + LaTeX 源码）。两者可共存：典型中文用户流是 alphaXiv 发现 → ar5iv+ 沉浸式翻译 细读（知乎实测贴证实）。

## 3. ar5iv.labs.arxiv.org 探测（降级链第二源评估）

实测 4+2 发（间隔 ≥3.05s），结论：

| 论文                            | 结果                         | 说明                                                                                                                                                                           |
| ------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `1706.03762`                    | 200，167KB，完整正文         | 951 个 `ltx_*` 元素                                                                                                                                                            |
| `hep-th/9901001`（1999 老论文） | 200，165KB，完整正文         | 595 个 `ltx_*`，MathML 带 `alttext`+`intent`                                                                                                                                   |
| `1412.6980`（Adam）             | 200，8KB **stub**            | 论文本身是 `\pdfpages` 包裹 PDF 的壳源码 → HTML 只有 "See pages 1-last of 0_adam_main.pdf"；`/log/{id}` 转换报告 severity-error（2 个 math-mode error，`Status:conversion:2`） |
| `1602.03837`（PDF-only 无源码） | **307 → arxiv.org/abs/{id}** | ar5iv 对无源码论文直接跳 abs 页，不给 HTML                                                                                                                                     |

- **引擎**：`<!--Generated by LaTeXML oxide (version 0.7.5)-->`，日志内含 `latexml-oxide`/`latexml_engine/src/*.rs` 路径（Deyan Ginev 的 Rust 重写版 Cortex）[^latexml]。**与 arxiv.org/html 同引擎同族**——DOM 皆是 `ltx_document/ltx_section/ltx_para/ltx_p` + MathML，下游同一套抽取器可通吃两源。
- **覆盖结论**：ar5iv ≈ arxiv.org/html 同源同覆盖（有 LaTeX 源码→全转；无源码→重定向 abs；壳源码→stub+ 转换报告）。**可作降级链第二源**：同一解析器、按需生成、独立部署；但它救不了 PDF-only 论文（那条路只能走 PDF 管线）。`Status:conversion` 等级与 `/log/{id}` 报告可作质量信号。
- 副产品：`/feeling_lucky`、明暗主题、`ar5iv-nav-button` 分页导航。

## 4. 第三方 hjfy 生态（API 消费方式 → 对我们 API 同构的约束）

GitHub 实存消费端（`gh search` 实测）：

| 项目                                             | Stars | 消费方式                                                                                                  |
| ------------------------------------------------ | ----- | --------------------------------------------------------------------------------------------------------- |
| `Infinity4B/zotero-hjfy-split-reader`            | 46    | 完整客户端：`hjfyClient.ts` 封装三端点 + 轮询[^zotero-split]                                              |
| `ANGJustinl/zotero-plugin-hjfy`                  | 22    | 同上端点，DOI/URL/Extra 多路提取 arXiv ID[^zotero-hjfy]                                                   |
| `yuchenwu73/ArXiv-Hjfy-Switcher`                 | 2     | 油猴/扩展：在 abs 页注入 `hjfy.top/arxiv/{id}` 链接（保留 `v\d+` 版本号、兼容 `cond-mat/0501001` 老格式） |
| `guantongpeng/arxiv-hjfy-extension`              | 5     | 扩展跳转                                                                                                  |
| greasyfork `463525`（arXiv 论文一键翻译，xx025） | —     | 不消费 hjfy；把 `ar5iv.labs.arxiv.org/html/{id}` 喂给有道——**ar5iv→翻译站工作流实证**                     |

**hjfy API 形态（第三方客户端逆向，与 `2026-09-14-hjfy-site.md` 互证）**：

- `GET /arxiv/{id}` — 阅读器页；**访问即创建/prime 任务**（未登录 → `/login` 重定向）。任务无独立 POST 端点。
- `GET /api/arxivStatus/{id}` — `{status, info}`；状态机 `start / finished / failed / error / fault`（客户端把 start/finished 都当中间态；finished 且无 zhCN 文件时会再 prime 一次——疑似「取源完成→翻译需二次触发」）。
- `GET /api/arxivFiles/{id}` — `{status, msg, data:{id, title, origin, zhCN, zhCNTar, isDeepSeek}}`：`status:0`+`data.zhCN` 非空 = 译好；`status:101` 或中文「请登录」= 需登录；`msg` 文案驱动 not-ready/pending 判定（未找到/正在处理中…）。
- 轮询范式：先查 files（`zhCN` 落地即成功），再查 status 判死；`10s × 72 ≈ 12min` 上限。版本号精确匹配（`assertExactReference`），客户端自带 vN→裸 ID 回退。
- **设计约束**：`/arxiv/{id}` 深链是生态互操作点（所有扩展只认这个 URL），复刻时应保留同构路由；files JSON 的 `origin/zhCN/zhCNTar` 三产物命名已成事实标准。

## 5. 对 TeXlate 的启示

1. **差异化成立**：没有人做「LaTeX 源码级 zh 重编译 PDF + 源码开放下载」；hjfy 是该生态位唯一者，复刻有存在价值。豆包/元宝证明「双语对照阅读」需求真实且大众。
2. **HTML 降级链**：arxiv.org/html（主）→ ar5iv（同源备援，同 ltx DOM 零成本接入）→ PDF 管线（无源码论文兜底，可借 BabelDOC/自研）。
3. **互操作面**：保持 `/arxiv/{id}` 深链 + `api/{arxivStatus,arxivFiles}/{id}` 轮询形态，hjfy 生态插件可零改对接我们——冷启动分发捷径。
4. **竞品护城河参考**：alphaXiv 的 Overview/Q&A 是「理解层」增值，可作为二期方向；沉浸式翻译证明 ar5iv HTML 双语是已验证 UX。

### 参考文献

[^alphaxiv]: alphaXiv. 产品文档与 MCP server 说明. 2026. [alphaxiv.org](https://www.alphaxiv.org)

[^latexml]: Ginev 等. LaTeXML — LaTeX 到 XML/MathML/HTML5 转换器（ar5iv 与 arxiv.org/html 共用引擎）. [latexml / ar5iv](https://ar5iv.labs.arxiv.org)

[^zotero-hjfy]: ANGJustinl. zotero-plugin-hjfy. GitHub 2026. [github.com/ANGJustinl/zotero-plugin-hjfy](https://github.com/ANGJustinl/zotero-plugin-hjfy)

[^zotero-split]: Infinity4B. zotero-hjfy-split-reader. GitHub 2026. [github.com/Infinity4B/zotero-hjfy-split-reader](https://github.com/Infinity4B/zotero-hjfy-split-reader)
