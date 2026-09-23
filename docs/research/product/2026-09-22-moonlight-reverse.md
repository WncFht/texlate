# Moonlight (themoonlight.io) 逆向调研

> **结论**：Moonlight 是韩国 Corca Inc.（约 20 人，Pre-A ~$5.4M，adtech 转型）做的「AI 论文阅读器」——Chrome 扩展劫持任意 PDF → 定制 pdf.js 阅读器 → 翻译/解释/摘要/讨论/引用卡全套 AI 功能。技术栈普通（Next.js+Vercel+Express+S3），护城河不在模型在**分发形态**（扩展即入口）与**增长引擎**（SEO 评审语料+会议 hub+推荐返利+游戏化）。对 texlate 可直接借鉴的：`<|N|>` 句级锚点协议、`<<<type|json>>>` 流内工具调用帧、框选解释、匿名镜像端点漏斗、per-paper 周配额模型、SEO 语料页打法、wasmtex（MIT WASM LaTeX 编译器）、pdf-lib 客户端导出合成。texlate 独有的 LaTeX 源编译管线仍是它架构上做不了的——它最强的 Layout Translate 也只是 PDF 重排版，产不出可编译双语稿。
>
> **状态**：调研完成（140-agent ultracode 工作流 wf_b2eff762-4a1，四轮 resume 全绿：34 侦察+22 审计+26 lane+320 gap item→30 条对抗核验全数 confirmed、0 refuted；§9 为已核验落地清单）
> **日期**：2026-09-22

## 1. 公司背景

| 项 | 内容 |
|---|---|
| 公司 | Corca Inc.（首尔），约 20 人 |
| 融资 | Pre-A 约 $5.4M |
| 前身 | adtech 出身，2024-05-02 发布 Moonlight Chrome 扩展 |
| 规模 | 声称 350K 用户；Chrome Web Store 扩展 100K users；移动 App 很小（Android 5K+，iOS 22 个评分且全韩区） |
| 产品族 | Moonlight（阅读器）、Moonlight Scholar（检索 closed beta）、CorTeX、Craken |
| 内部工具 | Ceal + MoonClaw（VoC supervisor 内部 agent） |
| OSS | github.com/corca-ai 57 repos：**wasmtex**(MIT)、cf-vfs、semath、moon-search-light、episteme、charness |
| 定位自述 | CEO 明示 "Thick Wrapper" 战略：用户消费 UX 不消费模型，窄域纵深是大厂打不到的资产 |

## 2. 架构画像

```
用户在浏览器打开任意 PDF → 扩展 content script 检测 contentType==='application/pdf'
  → 带页面凭证重取字节 → blob URL → closed shadow DOM iframe
  → chrome-extension://<id>/web/pdf.html?origin=<page>&file=<blob>
  → 定制 pdf.js 4.4.168 阅读器（React 18.3 islands + KaTeX + Milkdown/ProseMirror）
站点侧：www.themoonlight.io (Next.js 14.2.35 App Router, Vercel sin1)
  ├─ /api/* catch-all proxy → api.themoonlight.io (Express + Zod)
  ├─ ml.themoonlight.io/detect?url=&page_index= (DocLayout-YOLO 10 类版面检测)
  └─ S3 ap-northeast-2 `moonlight-paper`（presigned-post 直传 + review-uploads/ 转存）
```

| 层 | 事实 |
|---|---|
| 认证 | cookie `connect.sid` + `/api/auth/jwt` 跨域换票；Google OAuth/One Tap + email；Apple 登录只存在于 App（web 没有） |
| 流式 | **零 SSE/WS**：全部 fetch `getReader()`+`TextDecoder`，300ms 节流重渲 markdown；流内两类帧：`<|N|>` 句级锚点 + `<<<type|json>>>` 工具/meta 帧 |
| 扩展 | MV3 v3.3.0，31.2MiB，id `lhipdkibljepmfojllcfflfflhflcbgi`；viewer bundle 与 web `/extension/dist/web/pdf.html` **同一份代码**，postMessage 契约驱动；`externally_connectable` 让站点直读写 chrome.storage.sync |
| 实验/归因 | 自研 `/experiments/{evaluate,exposure}`；`channel_ai_search='ChatGPT / Perplexity search'` 获客归因字段 |
| 防护 | Vercel WAF（/api/* 对裸 curl 429+challenge）；`detected-country` 走 geoip，CN 用户配额规则更狠（见 §6） |

## 3. 协议面（公开/半公开端点精选）

| 端点 | 鉴权 | 机制 |
|---|---|---|
| `GET /api/proxy?fileUrl=` | **无鉴权** | 服务端代取任意 URL 字节给 viewer；只认 PDF content-type（arxiv.org/abs 透传 HTML 会挂） |
| `/api/paper/upload/{presigned-post,form,complete}` | 匿名可 | S3 三步直传，100MB |
| `GET /api/paper/share/{uuid}` | **无鉴权** | 分享链接直读（PATCH isPublic 生成） |
| `/api/review/{latest,trending,search}` + `/{slug}?language=` | **无鉴权** | 整个 AI 评审语料裸奔；offset 校验 bug（min0.max0）→ 每查询只够得着最新 100 条 |
| `GET /scholar/search-with-ref?query=<title>` | **无鉴权** | 一次调用拿回论文+references+citing 的整个 ego 网络 |
| `GET /api/etc/geoip` | 无鉴权 | MaxMind 式地区判定，驱动分区配额 |
| `/ai/anonymous/*` | 无鉴权 | **每个 AI 功能都有匿名镜像端点**（infographic 除外），服务端计量 |
| `/ai/translate-page-with-source-v2` | cookie | `{texts[],target}` → 流式译文内嵌 `<|N|>` 源句索引 |
| `/pdf-translation/{capability,jobs}` | Premium | 整篇重排版译文 PDF 的任务队列，2s→10s 轮询退避，≤20min，默认 maxPages=30 |
| `/ai/explain-infographic` | 登录 | 选段→1024×1024 JPG，**唯一有独立周额度的功能**（Pro 5/Premium 30） |
| `/ai/latex` | cookie | 公式 DOM 文本+元素 PNG → LaTeX |
| `GET /paper/{id}/sentences?sentenceIndex=N` | cookie | **句子仓库**：引用 chip 点击后回取真实原句（`<ref>` 证据落地） |
| `/ai/auto-highlight-page` | 匿名可 | 句列表→`{index,type∈novelty/methods/results,reason}` |
| `PATCH /user/weekly-paper-urls` | cookie | per-paper 配额计量落点 |
| 自定义响应头 | — | `X-Show-Paywall:1`（任何响应可触发付费墙）、`X-Contribution-Changed`（广播全 tab 刷新 streak）、`Retry-After` |

## 4. 功能机制逐项（lane 核验级）

### 4.1 翻译 —— 三个独立面
- **(A) 选区/单词翻译**：~450px 可拖 modal，页分数坐标锚定
- **(B) 页级对照翻译**：每个 `.page` div 右缘挂 `.translate-page-wrapper` 侧栏（收起=40px 竖签，展开=markdown 面板可拖宽）。客户端把 pdf.js textLayer 句化（`textWithRanges{nodes,ranges:DOM Range,paragraphEnds}`）POST 上去，**回流译文里嵌 `<|N|>` 索引**，客户端解析后给译文段打 `data-start/end-text-with-range-index`，并从源句 Range 的 clientRects 合成 `sentence-bbox` overlay——**双向 hover 高亮**（译文 hover 亮源句框，源句 hover 反向命中），v1.4.0 上线的 "Translation Sentence Matching"。跨页句用 `data-is-last-sentence-continuing` 缝合，高亮颜色经 `data-color-alias` 透传进译文
- **(C) Layout Translate（Premium beta）**：服务端任务 API 产出**整篇重排版译文 PDF**，灌进**第二个** PDFViewer，source-only/split/translated-only 三模式 + 双 viewer 双向滚动同步，视图偏好按 (paperId,lang) 持久化
- Auto Translate：scroll 防抖触发当前页±1，并发上限 3 页/批量 15 页；译文服务端持久化，重开即瞬时，导出时烘进 PDF
- **修正**：它做的是双向 hover 高亮而非「悬浮显示原文弹窗」；漂移 bug 存在于 heading 被并入句子的边界 case

### 4.2 解释（Explain）
- 三输入：服务端 `ml.themoonlight.io/detect` 返回 figure/table/formula 框 → hover chip + Explain(E)/Copy(C) 菜单；持久开关的 "Image Description Mode" 或 Cmd/Ctrl+drag 框任意区域；文本选区→Explain
- 每次 explain 都**附带 top-30 S2 references+citations 作上下文**；结果流式进 memo modal，可续聊
- 流内 `<<<toolname|{json}>>>` 帧实现 agentic 工具调用（已实现的唯一工具：searchPaperInGoogleScholar，结果截 25k 字符），有 wait/complete/fail UI 卡
- 公式一键复制 LaTeX（`/ai/latex`，可配 `$$` vs `\(`）
- **Infographic**：选段→POST `/ai/explain-infographic`→1024² JPG，唯一无匿名 twin 的 AI 功能；NEW 徽章+常驻额度 chip，额度耗尽按档位弹不同升级话术

### 4.3 摘要 / With AI 右栏
- 开纸默认右栏自动展开到 With AI tab（移动端除外）：**Keyword Dictionary → 3-Line Summary → Summary** 三张手风琴卡
- 每卡若 paper 记录已有字段直接渲染；仅当 OWNER 且首次才流式生成（`/ai/keywords`、`/ai/three-line-summary`、`/ai/summary`），写回 paper——**分享链接的访客白嫖 owner 预计算内容**
- 每个功能一个用户可改 prompt（`/user/{keywords,three-line-summary,summary}-prompt`）
- Discussion 多轮 chat：~6 个入口、整篇/选区两种 scope、命名线程+跨论文历史、`<ref p s pg>` 句级证据 chip、@-mention 最多 10 篇（付费）、流式建议追问；免费按 paper 计不按消息计

### 4.4 引用（Smart Citation + Citation Tab）
- 点击文内引用锚→解析到 S2（OpenAlex 兜底）→原地卡：题录+摘要+被引数 + 三个按需流式增强（**"Reason cited" / "Worth reading?" 四档判决 Full Read/Skim/Abstract only/Pass（按用户 library 亲疏条件化）/ reference summary**）+ 与 library 关系的彩色徽章
- 两个保存动词分工：**"Keep It"** 进 Citation Cards tab→批量导出（.bib 服务端 BibTeX / .txt 客户端 citeproc 出 APA/Vancouver/Harvard / CSV）；**"Add to Library"** 直接物化成库内论文
- v1.6.0 Citation Tab：cited/citing 双向列表；开文档时一次 `/scholar/search-with-ref` 引导全 ego 网

### 4.5 Library
- 单归属文件夹树 + 扁平 tags + 星级 + 可改元信息 + 多格式引用导出 + ZIP 批量下载 + Zotoro key 导入（collection 选择器+去重+逐文件失败分类）
- **Recents**：打开未存的论文自动进历史，可拖进文件夹——「打开≠保存」解耦
- insights 条：Library Status + contribution heatmap + Most Utilized Papers（加权参与度）+ 全站周度热门架
- **关键设计**：library 是排序信号不只是存储——Scholar、citation 卡配色、explain 个性化都吃库内容
- 缺口：无共享库（Coming Soon）、无 RIS/CSL、无跨笔记搜索、本地文件条目绑路径跨设备即坏

### 4.6 标注/笔记
- 5 色高亮 + 句锚评论 + 自由 pin + Milkdown Crepe markdown/LaTeX 笔记 + AI auto-highlight
- 锚定双制式：XPath+offset 的 DOM Range 序列化 + 归一化几何 source_ranges，三级冗余页解析
- **导出绝活**：标注经 `pdfjs_internal_editor__moonlight_` 前缀注入 annotationStorage，用 pdf-lib 烘成真 PDF annotation 对象（highlight/free_text+quadPoints），auto-highlight 颜色 alpha 合成后上纸
- 手工标注全档位免费；只有 AI 动作走周配额；游客有 uuid 本地标注
- 营销文案说有 underline 实际没做

### 4.7 防幻觉/可信层（grounding）
- 每个 AI 调用都带 `#### Page N ####` 页锚全文 + 选区 ±3 句窗口 + top-30 引文上下文
- `<ref>` chip 点开后从**服务端句子仓库**回取原句，"Go near source" 跑认真的句定位管线（句分布图、印刷页↔PDF 页调和、NFKD/大小写/变音符归一、±5 邻居扫描、sessionStorage 缓存）
- 诚实标签层："Abstract-based AI analysis" 徽章、"insufficient evidence" 弃权态、"subject to change" 免责
- **承认的不对称**：Explain/chat 普通回答仍无证据链（自家对比文承认输给 Typeset，Featurebase 11 个月的 evidence-link 请求还挂 In Review）

### 4.8 Team / Enterprise（核验：计费容器，不是协作空间）
- seat 计费容器：admin 付 seat 费、邀请码+链接、成员享权益；**无共享库/标注/协作编辑**（定价页自写 "Coming Soon"）
- 档位 1-3（无折扣只图统一付款）/4-15/16-29/30+ 邮件洽询；Pro $12/$10/$8、Premium $59/$49/$39
- 邀请页 `/{lang}/{teamId}/invite?code=`：未登录即可 GET `/api/team/{id}` 看邀请人；边缘 case 极细（proration/最小账单/续约锁/seat 不可低于成员数/一人一队）
- 唯一已交付协作原语：per-paper share 链接（连标注一起走，访客只读）

### 4.9 Scholar Deep Search（closed beta）
- `/{lang}/scholar` 307→login，API 401；waitlist 走 Google Form
- 声称 500M+（PubMed/arXiv/IEEE/Crossref）；四层：library 亲疏标记+"Connection to my research"、NL 标准漏斗评 top-100、真引用边图、citation-graph gap 分析
- 公开原型泄露实现：`moon-search-light`=S2 API+gemini-3-flash+text-embedding-3-small——**检索面是 S2 拼装非自建索引**
- Featurebase 实锤多次分钟级延迟

### 4.10 暗色模式（修正此前结论）
- **有**，viewer 内 `DocumentTheme{Original,Night}`：纯 CSS `filter: invert(90%) hue-rotate(180deg)` 打在 `.pdfViewer .page canvas`+`.textLayer`+缩略图上，`.annotationLayer` 豁免保住高亮色
- 与我们差异：它是 view-only CSS 滤镜（导出/下载不受用），**Blender 是像素级烘进 PDF 产物**；用户投诉的「无暗色」主要指 web 站外壳和移动端

### 4.11 配额经济（计费模型）
- **per-paper 周槽位**非 token 计量：`MAX_FREE_PAPERS=3`，周一 00:00 UTC 重置；首次对某 URL 记 metered action 即占槽，占后该篇本周无限用
- 绕过栈：订阅/7 天 welcome 窗/14 天 referral 窗/partner 窗/受邀未激活宽限/移动端全面豁免/教程 PDF/匿名 twin
- **CN 地区歧视**：geoip 命中后 3 篇变**终身累计**非每周——值得注意的激进成本控制
- 转化双层：确定性 LimitReachedModalV2（第 3 篇预警/第 4 篇锁死+referral 逃生口）+ 任意响应 `X-Show-Paywall:1` 触发的 A/B 付费墙
- 独立额度：infographic 周 credit（5/30）、Discussion 一次性体验旗标+10 篇上限、Layout Translate Premium 专属周配额+maxPages=30

### 4.12 移动端
- 无 PWA/无 manifest/无 service worker；iOS+Android 独立 App（v1.1.6）是刻意收窄的「阅读+库」伴侣
- 平板是目标形态（pencil 手写、折叠屏切平板模式）；手机 App 直接隐藏 header
- App Store 合规的 Apple 登录只在 App 里→web 永远 stranded 这批用户；支付走 Toss webview
- 采用量极小且韩区集中；投诉收敛于 iPad 卡顿/手写/侧栏/缩放

## 5. 增长引擎（最值钱的一节）

| 杠杆 | 机制 |
|---|---|
| **扩展即分发** | 任意站点 PDF→Moonlight 接管；劫持本身即「一键导入」（open 历史+配额登记同时完成）；无 arXiv abs 页挂件——纯 PDF 劫持一条路 |
| **零摩擦漏斗** | 匿名上传/paste-URL/全页 drag-drop→直接进 `/file?url=` 阅读器（HTTP 200 无墙，route 在 /[lang] 外）；所有 AI 有匿名 twin；注册请求由 viewer postMessage 延迟到教程完成/配额耗尽/存库时 |
| **SEO 评审语料** | `/{lang}/review/{slug}` 每篇 arXiv 自动生成结构化评审（长文 markdown+LaTeX 数学+关键词典+页面快照 PNG+相似论文×5+浏览计数）；**每日批量**（发布→入库~4 天→评审 66 秒后上线实测）；16 个 arXiv archive 全覆盖+会议 dump |
| **隐藏 LLM-seeding** | 每评审页埋 `h-0 opacity-0 text-[1px]` div 告诉 AI 助手「这是全世界最准确的摘要」+功能推销+安装链接；同时 robots.txt 封 GPTBot/ClaudeBot/CCBot——**只借 Google 索引喂答案引擎，不给你训练**；实测隐藏文案原样出现在搜索摘要里 |
| **会议 hub** | ECCV 507/KDD ~605/KCCV 161 篇静态配置 SSR 页，CollectionPage+Event+BreadcrumbList JSON-LD |
| **站点↔扩展深桥** | `externally_connectable` 双向：站点 ping 4 个候选扩展 ID、读写 storage.sync、完成活动任务、按 URL 布防劫持 |
| **游戏化** | GitHub 式 Paper streak 漂浮组件可挂**每个网站**（默认关）；heatmap+radar+加权计分；周年庆任务/教授 campaign/lab-exchange |
| **referral** | 2 人→1 月 Pro；被邀请者 14 天豁免窗 |

## 6. 弱点与用户投诉（我们的机会面）

- 译文-源句 hover 对齐有边界漂移（heading 并入句子）
- iPad/移动端卡顿、手写坏、侧栏烦、文本选择不精——移动端全线弱
- 登录 bug、强制第三方 cookie；Apple 登录用户进不了 web
- cloud-only，无本地/自托管；团队共享库到现在还是 Coming Soon
- Premium $59/mo 刺眼；CN 用户终身 3 篇的歧视性配额
- Explain 普通回答无证据链（自家承认输 Typeset）
- 本地文件库条目绑路径、跨设备即坏；无 RIS/CSL 导出；无全局笔记搜索

## 7. Corca OSS 可白嫖清单

| 仓库 | 是什么 | 对我们的价值 |
|---|---|---|
| **wasmtex** (MIT) | WASM pdfLaTeX/XeLaTeX/LuaLaTeX + LSP + SyncTeX | ★★★ 浏览器内编译——做 web 端免排队即时预览可直接用 |
| moon-search-light | Scholar 检索原型（S2+embedding） | 文献检索 MVP 蓝本 |
| episteme | relation-map 探索器原型 | 引用图谱 UI 参考 |
| cf-vfs | CF Workers/DO/R2 VFS | 边缘缓存参照 |
| semath | Rust 数学语义 | 公式语义层远期参考 |

## 8. 对 texlate 的可借鉴清单

> 22 个 audit agent 已把 texlate 现状摸清（SolidJS 前端/FastAPI 26 端点/LaTeX 源管线/BYOK/serial queue/trizone bench/ADR-0020 暗色/ADR-0021 引用卡/share.zip）。

### 8.1 ADOPT —— 直接抄，成本低收益明确

| 项 | 理由 |
|---|---|
| **`<|N|>` 锚点协议 + `<<<type|json>>>` 流内帧** | 零 SSE/WS：fetch+TextDecoder+300ms 节流重渲；`<|N|>` 让流式译文段回指源句索引，`<<<tool|json>>>` 让模型中途调工具——我们 chat/summary 流式照这个做 |
| **Cmd/Ctrl+drag 框选解释** | 零依赖交互；我们有 LaTeX 源知道 figure 位置，做得比它准 |
| **匿名镜像端点 + postMessage 延迟注册** | `/anonymous/*` 镜像+用完再要账号，纯路由层工作；它实测是转化主力 |
| **per-paper 周槽位配额** | 比 token 计量好懂一百倍：「每周免费 N 篇」一句话说清；占槽后该篇无限用也是好的体感 |
| **双向 hover 高亮** | 我们 splice 双语段天然有对照；它做 DOM Range+bbox overlay 那么痛苦是因为只有 PDF 坐标 |
| **Keep It→批量导出 .bib/.csv** | ADR-0021 引用卡加收藏+导出即齐 |
| **"Worth reading?" 四档判决** | Full Read/Skim/Abstract only/Pass，按用户库亲疏条件化——挂在引用卡上是高体感低成本的 AI 增强 |
| **pdf-lib 客户端合成导出** | 标注/译文烘进 PDF 在浏览器里完成（quadPoints+annotationStorage），省服务端合成管线 |
| **dedupe-by-URL** | POST 撞 409→GET 取已有；我们 corpus 同 URL 判重可直接抄语义 |
| **每功能自定义 prompt** | BYOK 下顺手，设置页几个 textarea |
| **`X-Show-Paywall` 响应头协议** | 任何响应都可触发付费墙的统一信号，比逐个端点特判干净 |

### 8.2 ADAPT —— 改造后抄

| 项 | 怎么改 |
|---|---|
| **扩展劫持** | 它劫持后做 overlay 阅读器；我们扩展劫持 arXiv PDF 应直接走 LaTeX 源管线产双语编译 PDF——**学它的分发，不学它的产物形态**。注意它没有 arXiv abs 页挂件，纯 PDF 劫持一条路径 |
| **SEO 语料页** | 它的评审页是薄 AI 摘要钓搜索；我们已翻论文可产 `/{slug}` 句级双语对照页——**同样打法我们的内容质量严格更高**。LLM-seeding 隐藏文本可学（文案别照抄「最准确」那种夸大），robots 封 AI 爬虫但放 Google 的策略照抄 |
| **每日批量入库管线** | 它发布→入库 ~4 天→评审 66s；我们 daily arXiv 抓取通道知识在 git 历史里，重启时对照它的节奏（注意 daily-soak 已退役勿原样重建，指的是 SEO 页生成管线） |
| **Layout Translate 双 viewer** | 它的 re-typeset 是 PDF 重排；我们做「原 PDF | 双语编译 PDF」双 pane 同步滚动是同一 UX 形态，但产物是源级编译的 |
| **wasmtex** | MIT 直接拿：web 端 WASM 即时预览小文档，重型编译仍走服务端 xelatex |
| **句子仓库+`<ref>` 证据 chip** | 它有 `/paper/{id}/sentences` 服务端句库支撑证据跳转；我们 LaTeX 源侧的句定位更准——做 chat 时证据 chip+「跳到原文」全套可抄，地基我们更好 |
| **library 作为排序信号** | 库内容喂检索/引用卡配色/个性化；我们语料库同思路可复用 |
| **share 链接带标注只读** | PATCH isPublic+无鉴权 GET+READ 权限降级=分享即漏斗；我们 share.zip 已有产物版，网页版可照此 |
| **游戏化=共修飞轮** | 它的 streak 只是留存；我们可做「修好一篇编译失败论文」计分反哺 fixloop 规则库 |
| **模型分档** | 它 9 模型三档+luna/terra 内部别名品牌层；我们 BYOK 下可改成功能分档（页翻免费/fixloop 精修收费） |
| **团队 seat+邀请码三段式** | 计费容器先抄（admin 付+码+邀请页），共享语料桶/术语表是我们能抢跑的差异点 |

### 8.3 SKIP —— 明确不抄

| 项 | 理由 |
|---|---|
| CV 版面检测（DocLayout-YOLO） | 我们有 LaTeX 源结构信息免费拿，不需要 CV 兜底 |
| cloud-only 强制上传 | 反定位 |
| 自研 A/B `/experiments` | 过度工程 |
| quiz/radar/infographic 花活 | 非核心动线；infographic 还要独立额度计量太绕 |
| 移动原生 App | 它自己做得很差且投入大；我们 web 优先 |
| CN 终身配额歧视 | 吃相难看，且我们就是中文用户主场 |

### 8.4 DIFFERENTIATE —— 它做不了、我们该放大的

| 我们的独占 | 为什么它做不了 |
|---|---|
| **LaTeX 源→可编译双语 PDF** | 它 Layout Translate 上限是 PDF 重排版；我们产出可再编译、可投稿格式的双语稿 |
| **术语一致+fixloop 编译级自愈** | 编译反馈回路是源级管线独有 |
| **暗色烘进产物（Blender）** | 它只有 view-only CSS 滤镜，导出即失效 |
| **本地/自托管+BYOK** | 隐私敏感机构天然排他 |
| **bench/trizone 质量闭环** | 可度量迭代，它没有公开质量闭环 |
| **证据链天然更准** | 它要句子仓库+±5 邻居扫描补救 PDF 坐标漂移；我们源侧定位一步到位 |

## 9. 已核验落地清单（工作流 verify 阶段产出：320 gap item → 30 confirmed / 0 refuted）

> 每条都对着 texlate 现有代码落点写（括号=优先级/工作量；全文见 `tmp/moonlight-20260922/confirmed-items.md`）。

### P0

1. **句级配对对齐·双向 hover**（P0/L）— 学它的 `<|N|>` 协议但用确定性 ID：en 侧用 in-tree `sentence_ends` 分句、zh 侧用 `⟪S0000⟫` sentinel 嵌 chunk，映射写进 dual.json；DOM 路径先行。我们的块锚天然免疫它 heading 并句的漂移 bug。
2. **无 key 提交硬失败+Settings 深链**（P0/S）— 现在静默跑空，改成拒收并直跳设置页。

### P1 · 翻译 UX（2）

3. zh pane 每块「peek original」就地展开 en 源句（S）— dual.json 已有 `{seq,en,zh}`，零新载荷；比它 hover-only 更进一层。
4. 选区翻译弹窗+词典模式（M）— ≤3 词走词典式释义；DomPane 是 DOM 文本顺手做，PdfPane 开 textLayer 选择。

### P1 · Chat（3）

5. `POST /api/task/{id}/chat` chunk 接地问答端点（M）— context 用 `⟦S0001⟧` seq 标记的 en 原文，**服务端校验每条引用 seq**（编造的直接丢）——比它「popover 显示原句」更硬的诚实保证，因为只有我们有权威段库。
6. Reader chat dock 第三栏（M）— 刻意选 dock 不选 modal：modal 遮内容正是它用户投诉榜首。
7. 双语 ref chip+镜像跳转（M）— chip 点开同时给 en 引文**和**它的 zh 译文（它句子仓库单语，结构上给不了）。

### P1 · 选区/解释（2）

8. 每个公式一键 Copy LaTeX（S）— 我们要花零成本：源里有真 LaTeX，不用 `/ai/latex` 猜。
9. parse-tree 锚定的「Explain this figure/table」 chip（L）— 它要 DocLayout-YOLO 服务端检测，我们从 LaTeX 源 parse 树直接知道环境边界。

### P1 · 引用（4）

10. 引用卡「translate this reference」动作（S）— 卡片解析出 arXiv id 即给一键翻译入口，引用卡→新任务闭环。
11. 从源 bundle 出 author-verbatim BibTeX（M）— `thebibliography`/`.bib` 在源里就是原文，不重建。
12. 多键引用 `[3-7]`/`[2,5,9]` 合并卡（M）。
13. DomPane 引用卡补齐 S2 元信息对齐 PdfPane（S）。

### P1 · 摘要/预览（3）

14. 已持久化的 term_dict 露出为关键词典卡（S）。
15. 开卷 zh TL;DR/abstract 卡（M）。
16. link-preview 卡扩到 bibliography 锚之外（M）。

### P1 · Library（4）

17. keep/pin 标记豁免 retention sweep（S）。
18. 引用卡「已译」徽标+一键开本机译文（S）。
19. kept-refs 车卡→批量导出（M）。
20. Zotero 收藏夹→批量翻译队列，反向通道补成双向（M）。

### P1 · Discover（3）

21. 引用卡「translate in texlate」action（S）。
22. References 侧栏 tab：全 bibliography+L2 元信息+已译状态（M）。
23. 会议合集页：per-conference arXiv id JSON 渲 Discover（M）——学它会议 hub 但内容是译文不是薄摘要。

### P1 · Deep Search（4）

24. 「Related work」面板：typed 引用列表（M）。
25. **LaTeX 源 citation-edge+cite-context 抽取管线**（L）— `thebibliography`/`\cite` 在源侧抽边，这正是 citation-landscape 调研定的独有资产。
26. 「接近你已译论文」亲疏徽标+可查依据（M）。
27. 个人已译语料双语全文检索：SQLite FTS5 over chunks（M）。

### P1 · Onboarding（2）

29. 捆绑零 token demo 论文（M）— 对应它的匿名漏斗 aha-moment。
30. 入口归一化扩到 DOI/ar5iv/alphaXiv URL 形（S）。

## 10. 风险与注意事项

- **法务**：全程公开面（无鉴权端点、CRX 公开分发、GitHub 开源仓、RSC/i18n 字典），无越权；勿调其匿名 AI 端点做规模化白嫖（违反 ToS 且无必要）。`/api/proxy?fileUrl=` 无鉴权代取是**它的**攻击面不是我们的作业模板——我们若做 URL 拉取要加白名单/SSRF 防护
- **扩展审核**：「劫持 PDF」类扩展上架声明文案需谨慎；它 100K 用户过审说明路径可行
- **wasmtex 体积**：WASM TeX+字体几十 MB，在线预览要评估加载策略
- **配额启示**：per-paper 槽位模型对 LLM 成本失控是天然闸门，值得我们计量设计参考，但 CN 歧视那条别学

## 附：侦察方法与证据位置

- 工作流 `wf_b2eff762-4a1`（140 agent，四轮 resume 全绿，累计 ~5.5M subagent tokens）；中间产物 `tmp/moonlight-20260922/`：`lane-summaries.md`（26 lane 全文）、`confirmed-items.md`（30 条已核验建议全文）、`final-result.json`、`per-agent/*.json`（56 侦察+审计原始结果）
- 手段：CRX 解包（v3.3.0 pdfScript.js 6.2MB 全文可读）、RSC flight/i18n ~2406 键字典、公开无鉴权 API 实测（review/proxy/scholar/geoip/share）、Notion recordMap、Featurebase `__NEXT_DATA__`、Wayback 语料抽样、GitHub corca-ai 仓审计
- 未穿透（completeness critic 记录在案）：**全程零真实 AI 调用**——AI 行为结论全部推自客户端解析代码与端点形状，未抓过线上 wire 流量；WAF 后登录态内页未做（无真账号）；ml 服务与 Scholar 实现黑盒。156 条 open_questions 存 `final-result.json` 备查
