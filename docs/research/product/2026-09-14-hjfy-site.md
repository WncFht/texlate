# hjfy.top 线上产品侦察报告

> **结论**：hjfy.top 是「arXiv LaTeX 源码 → LLM 翻译 → ctex 重编译」生态位的唯一现存产品；API 面极薄（GET status 即创建任务），产物三件套 + 五态+fault 状态机 + DeepSeek 重翻通道构成复刻 checklist 的核心。
> **状态**：时点证据（2026-09-14 口径）
> **日期**：2026-09-14

方法：站点是纯 SPA（所有路由返回同一 `index.html`），因此主要证据来自前端 JS bundle 逆向 + 匿名 API 实测 + GitHub 第三方客户端源码[^zotero-hjfy][^zotero-split]。下文标注 `[实测]`=直接调通、`[代码]`=bundle 证据、`[猜]`=推断。

## 0. TL;DR

- **产品形态**：单页应用，三大功能 = arXiv 论文翻译（主）、本地 PDF 上传翻译（辅）、文件管理。**已译论文匿名随便看；创建新任务才要登录**。
- **阅读器不是"段落交错对照"**，而是**两个 pdfslick（pdf.js 封装）实例并排**：左原右译（可切换左右），三模式视图 `原文/翻译/分屏`，滚动同步按 delta 等值联动（非比例），跳页 >500px 时弹出"回跳"按钮而非跟随。PDF 上传的阅读器是**左原 PDF + 右 Markdown 渲染 HTML**（marked + KaTeX），固定分屏。
- **API 极薄**：`/api/{arxiv,file}Status/{id}` 轮询任务、`/api/{arxiv,file}Files/{id}` 取签名 OSS URL 列表。任务创建无独立端点——**GET status 即创建/触发**（未登录返回 `status:101`）。
- **产物三件套**（阿里云 OSS 杭州，签名 URL 1h）：`{id}.pdf` 原文、`{id}_zh_CN.pdf` 译文、`{id}_zh_CN.tgz` 译文 LaTeX 源码。
- **限制**：每天新建翻译 100 篇/人、PDF 上传 10 篇/天且 ≤10MB；内测免费；有 `/pay` 页和微信支付二维码接口（已埋点未启用定价）。
- **复刻核心差异点**：状态机五态+fault（start/processing/finished/failed/error + fault=编译失败仍可下载源码）、失败任务定期重修、DeepSeek 重翻反馈通道、LaTeX 源码 .tgz 公开下载。

## 1. 功能清单（复刻 checklist）

### 首页 `/` `[代码]`

- [ ] arXiv 输入框：接受 `https://arxiv.org/abs/{id}` 或裸 `{id}`（含 `v\d+` 版本号、旧式 `subject_id` 如 `math_0309113`），正则 `[0-9]{4}\.[0-9]{4,}(v\d+)?|subject_id`；非法时提示"请输入正确的 arXiv 地址或 ID"
- [ ] 3 个示例论文链接（1706.03762 / 2501.14787 / 2503.06072 / 2412.05265 中陈列）
- [ ] 输入时调 `arxivInfo` 检查 `hasSrc`，无源码提示"这篇论文未提供 Latex 源码，请使用本地文档功能"
- [ ] "近期访问的 arXiv 论文"列表（默认 10 条 + "加载全部"）——`[实测]` 匿名返回空，登录态服务端记录
- [ ] PDF 拖拽/点击上传区：≤10MB、`accept=.pdf`，文案"此功能还在测试中，效果不如 arXiv 翻译，不支持扫描文件"
- [ ] 顶栏：logo「幻觉翻译」、首页/关于、登录按钮（登录后头像菜单：我的文件/退出登录）
- [ ] 页脚：京 ICP 备 2025111180 号、小红书账号链接、联系邮箱 `public@cyberwalnut.top`
- [ ] 登录弹窗双 Tab：**微信扫码**（WxLogin，appid `wx9657b7da3b068829`；微信内浏览器走服务号 oauth2 `/api/login/callback/fuwuhao`）/ **手机号 +4 位验证码**（阿里云无痕验证码 `initAliyunCaptcha` SceneId `1vljhm6u` 保护 sendCode）
- [ ] 错误反馈入口（登录可见）："翻译有问题？"弹窗

### arXiv 阅读器 `/arxiv/{id}` `[代码+实测]`

- [ ] 任务状态轮询页（TaskLoading）：spinner + 阶段文案 + "返回首页"；`document.title` 换成"翻译中…"/论文标题
- [ ] 双语阅读器：双 pdfslick 实例 + 左侧栏（页面缩略图/文档大纲/附件 三 tab）+ 顶栏工具条
- [ ] 视图三模式、左右互换、滚动同步（详见 §2）
- [ ] 下载菜单：原文 PDF / 译文 PDF / 译文 LaTeX（.tgz）
- [ ] 失败兜底：版本号回退（`v\d+` 剥掉再查一遍）+ "或者点击这里查看不带版本号的论文"链接；fault 状态仍给源码下载
- [ ] 反馈弹窗（登录）：错误类型下拉（少量文本未翻译/大量文本未翻译/文献版本较老/**翻译可读性差→换 DeepSeek 重翻**（isDeepSeek 译文隐藏此项）/其他 + 文本框）

### 文档阅读器 `/file/{key}`（上传 PDF）`[代码]`

- [ ] 左栏 pdfslick 显示原 PDF；右栏 `<div class=markdown>` 渲染**译文 Markdown**（marked + 自定义 inlineKatex `$…$`/blockKatex `$$…$$`）
- [ ] Markdown 内相对资源经 `/api/getFile/{key}/…` 代理
- [ ] 工具条：下载译文 markdown；固定分屏，无模式切换、无滚动同步代码
- [ ] 需登录（未登录显示"需要登录才能访问"）

### 其它页面 `[代码]`

- [ ] `/myfiles`：上传文件表格（文件名等列 + 删除按钮 → `DELETE /api/deleteFile/{key}`），空态"未上传文件"，需登录
- [ ] `/about`：主要功能（LaTeX 源码翻译保排版 / 大模型翻译可读性高）+ FAQ 手风琴 6 条
- [ ] `/desktop`：桌面版介绍页——**目前是 Lorem ipsum 占位 stub**（"A better workflow"），桌面版未上线
- [ ] `/pay`：仅一个微信支付二维码（`createTransaction` 返回 `code_url` 画 canvas QR），无价格选择 UI

## 2. 阅读器 UX 规格（arXiv 双语）

**布局**：`pdfSlick` 容器全屏 flex；左侧窄 icon 栏（缩略图/大纲/附件切换）→ 可拖拽分隔条（`hover:cursor-col-resize`）→ 两个 `flex-1` PDF 面板。左上悬浮"返回"按钮（`absolute top-5 left-5`）。

**视图模式** `[代码]`：

```js
items: [
    { label: "原文", value: "original" },
    { label: "翻译", value: "translated" },
    { label: "分屏", value: "split" },
];
// 默认值：window.innerWidth > 1080 ? "split" : "translated"
```

**左右互换**：`localStorage.translatePosition`（默认 `"left"`；代码 `translatePosition==="left"?[U,B]:[B,U]`，U=译文面板）；tooltip 文案"左侧显示原文/左侧显示翻译"。

**滚动同步** `[代码]`：仅 split 模式挂载双向 scroll 监听；译文容器滚动时 `origin.scrollTop += delta`（**等值 delta 联动，非比例/非页对齐**）；反向亦然。增量 |Δ|>500px（大纲/缩略图跳页）不联动，改为浮出按钮（点击把对侧 scrollTop 拉到本侧位置）。

**工具条**（pdfslick 自带 + 自定义）：按页滚动、缩放菜单（自动/实际大小/页面适应/页面宽度/50%–200%）、放大缩小、页码指示（`pagechanging` 事件）、顺时针旋转、跳转首页/末页、全屏、打印、文档信息（标题/文件名/文件大小/PDF 版本/PDF 生产者）、查找（pdf.js findbar）、**批注编辑：高亮（多色）+ 自由文本**（`annotationEditorMode` HIGHLIGHT/FREETEXT）、亮/暗切换（`localStorage.theme`）。

**状态文案** `[代码]`：

| status     | 文案                                                                                |
| ---------- | ----------------------------------------------------------------------------------- |
| start      | "开始翻译，通常需要 1-10 分钟。"                                                    |
| processing | "翻译中"（info 附带当前文件名，如"正在翻译 04-alignment.tex"）                      |
| finished   | 进阅读器                                                                            |
| failed     | "翻译失败，对于 arXiv 论文，我们会定期检查失败任务并修复，请等待或联系我们加速处理" |
| error      | "翻译出错，可能这篇论文没有源码。"                                                  |
| fault      | "编译失败，请下载源码浏览"                                                          |

## 3. 可见 API 面

全部同源 `https://hjfy.top`，JSON 信封 `{status, data?, msg?}`：`status:0`=OK，`101`=需登录，`400/500`=错误。**无独立"创建任务"端点——GET Status 即触发/登记任务**（第三方客户端 Zotero 插件还会 GET `/arxiv/{id}` 页面来 prime，`[代码+三方证据]`[^zotero-hjfy]）。

| 端点                                           | 方法/载荷                                                                              | 响应（实测）                                                                                                                                                                                                   |
| ---------------------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/api/arxivStatus/{id}`                        | GET                                                                                    | `{status:0,data:{status:"finished",info:"正在翻译 01-Overview.tex"}}`；未译论文匿名→`{status:101,"required login"}`；不存在 id→`{status:"error",info:"正在下载论文源码"}`                                      |
| `/api/arxivFiles/{id}`                         | GET                                                                                    | `[实测]` `{id,title,origin,zhCN,zhCNTar,isDeepSeek}`，三个阿里云 OSS 签名 URL（`hjfy-files.oss-accelerate.aliyuncs.com/arxiv/{id}/`，`x-oss-expires=3600`）；命名 `{id}.pdf`/`{id}_zh_CN.pdf`/`{id}_zh_CN.tgz` |
| `/api/arxivInfo/{id}`                          | GET                                                                                    | 返回 `data.hasSrc` `[代码]`；`[实测]` 当前持续 500 "socket connection closed"（疑似线上故障）                                                                                                                  |
| `/api/arxivViewHistory?limit={n}`              | GET                                                                                    | `[实测]` 匿名 `{status:0,data:[]}`                                                                                                                                                                             |
| `/api/fileStatus/{key}` `/api/fileFiles/{key}` | GET                                                                                    | 同 arxiv 结构（type=file）；`[实测]` 乱 key 触发函数计算崩溃错误 → 后端**函数计算**实锤（呼应作者"SaaS 版本会莫名其妙退出"的说法）                                                                             |
| `/api/getFile/{key}/{path}`                    | GET                                                                                    | 文件资源代理；`[实测]` 坏 key→`{"msg":"Not found"}`                                                                                                                                                            |
| `/api/uploadFiles`                             | POST `multipart`（file,fileName）                                                      | `{status:0,data:{fileKey}}`→跳 `/file/{key}`；`status:302`→跳 `/arxiv/{arxivId}`（**上传命中已译论文直接复用**）；匿名 `[实测]` `required login`                                                               |
| `/api/myFiles` `/api/deleteFile/{key}`         | GET / POST(delete)                                                                     | 需登录（`required login`）                                                                                                                                                                                     |
| `/api/sendCode`                                | POST `{captchaVerifyParam,phone}`                                                      | 阿里云验证码校验先行；`[实测]` 假参数→`人机识别失败`                                                                                                                                                           |
| `/api/phoneLogin`                              | POST `{phone,code}`                                                                    | →`{data:{session}}`→`/api/callbackSession?session=…&path=…`                                                                                                                                                    |
| 微信登录                                       | WxLogin QR → `/api/login/callback/wechat?path=…`；微信内→`/api/login/callback/fuwuhao` |                                                                                                                                                                                                                |
| `/api/logout`                                  | POST                                                                                   |                                                                                                                                                                                                                |
| `/api/userinfo`                                | GET                                                                                    | `[实测]` `{login:false}`；登录后 `{login,nickname,head_img_url}`                                                                                                                                               |
| `/api/errorFeedback`                           | POST `{id:url, errorType, errorContent}`                                               | 登录可用                                                                                                                                                                                                       |
| `/api/pay/wechat/createTransaction`            | GET                                                                                    | →`{data:{code_url}}`，前端 canvas 画 QR                                                                                                                                                                        |

**前端栈**：SolidJS（编译模板 `w('<div>')`）+ Vite + Tailwind + pdfslick + marked + KaTeX + qrcode；静态资源走独立 CDN 域，百度统计，CSRFTOKEN 模板占位。

## 4. 定价与限制 `[About FAQ 代码原文]`

- "arXiv 已翻译的论文可随意浏览，但需登录才能创建新的翻译任务，**限制每人每天创建 100 篇**；PDF 文档翻译限制**每天上传 10 篇**，目前内测期间暂不收费。"
- PDF 上传 ≤10MB、不接受扫描件。
- `/pay` + 微信支付通道已建好但无定价 UI——付费设计方向大概率是按次/按量（作者文章痛批过月费 20 篇和按字数两种模式）。
- 联系：public@cyberwalnut.top；有小红书官号。

## 5. 原文之外的实现细节增量

1. **任务模型五态+fault 细分**：编译失败（fault）与翻译失败（failed）分开，fault 仍交付 .tgz 源码——复刻时 `status` 枚举直接抄。
2. **进度可见到文件名**：`info` 字段暴露"正在翻译 xx.tex"——后端按文件粒度推进并上报。
3. **isDeepSeek 双轨制**：默认译文用便宜模型（作者文章：qwen-turbo/doubao-lite），用户可反馈"换 DeepSeek 重翻"，`isDeepSeek` 标记进 files 响应——**分级模型 + 按需升级的产品化闭环**。
4. **失败任务定期重修**：failed 文案承诺"定期检查失败任务并修复"，呼应作者"手动修复固化进代码"的说法。
5. **版本号归一**：`v\d+` 可省略，失败后自动回退无版本号 ID；任务存储按无版本 ID（第三方插件 `VersionedArxivReference` 证实[^zotero-hjfy]）。
6. **PDF 译文交付物是 Markdown 而非重排版 PDF**：上传 PDF 走 marker→md→LLM，阅读器右侧 marked+KaTeX 渲染，图片走 `/api/getFile` 代理——作者自评"效果很差"，新方案（PDF 指令直译）在研。
7. **上传去重**：uploadFiles 返回 302+arxivId 说明后端对上传 PDF 做 arXiv 匹配/去重。
8. **生态**：多个第三方客户端直接消费上述 API[^zotero-hjfy][^zotero-split]，还有 ieeA（TeXlate 仓的参考实现）——API 即公开接口，复刻值得保持同构。
9. **桌面版占位**：`/desktop` 是模板 stub，与作者"之后做桌面版"一致——未做。
10. **后端线索**：函数计算（fileStatus 崩溃报文）、阿里云 OSS 杭州、阿里云验证码、微信双登录（扫码 + 服务号）、微信支付。

## 6. 未侦察到/存疑

- 付费价格点：createTransaction 无参数，金额服务端定死，匿名不创建交易故未取到 `[猜]`。
- `/api/arxivInfo` 现故障 500（可能确实坏了，FAQ 也说 arXiv 网络不稳）。
- "近期访问"匿名恒空，疑似登录态功能或已下线。
- Word/Epub：meta description 里宣传"Word 翻译，Epub 翻译"但前端无入口 `[猜:规划中]`。
- 翻译产物命名约定 `{id}_zh_CN` 暗示多语言预留，但 UI 无语言选择（`[猜]`）。

### 参考文献

[^zotero-hjfy]: ANGJustinl. zotero-plugin-hjfy（Zotero 插件，hjfy API 客户端，`src/modules/arxivTranslation.ts`）. GitHub 2026. [github.com/ANGJustinl/zotero-plugin-hjfy](https://github.com/ANGJustinl/zotero-plugin-hjfy)

[^zotero-split]: Infinity4B. zotero-hjfy-split-reader（分屏阅读器插件，`src/modules/hjfyClient.ts` + 状态分类器 hjfyState.ts）. GitHub 2026. [github.com/Infinity4B/zotero-hjfy-split-reader](https://github.com/Infinity4B/zotero-hjfy-split-reader)
