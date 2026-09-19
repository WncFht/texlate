# Zotero 插件调研：texlate × Zotero 集成（2026-09-19）

调研问题：做一个 Zotero 插件，让用户右键 arXiv 条目 → 调本地/远程 texlate 服务翻译 → 中文 PDF 挂回条目附件。texlate 侧 API 事实（已核实）：`POST /api/arxiv/{id}/translate` 建任务、`GET /api/task/{id}` 轮询、`GET /api/files/{id}/{kind}` 取产物、`GET /api/health` 探测、`POST /api/upload` 传源 zip；local 形态 127.0.0.1:8765 无鉴权，`TEXLATE_MODE=server` 走 `X-Texlate-Key`。

## 1. Zotero 插件开发技术栈现状（核验时点 2026-09）

### 版本线

Zotero 版本迭代很快：7（Firefox 115 ESR）→ 8（2026-01-22，Firefox 140 ESR）→ 9 → **10（2026-08-17，当前稳定版）**。8→9→10 同基 Firefox 140，破坏性逐版递减；每升一个大版本插件只需把 `manifest.json` 的 `applications.zotero.strict_max_version` 改到 `x.0.*`，甚至可以只在 update manifest 里改、不发新版[^z8dev][^z10dev][^changelog]。新插件应直接以 `strict_min_version: "7.0.*"` + `strict_max_version: "10.0.*"` 起跳，覆盖全部在役版本。

### 架构与脚手架

Zotero 7 起插件是 **bootstrapped WebExtension 式**：根目录 `manifest.json`（`manifest_version: 2` + `applications.zotero` 块）+ `bootstrap.js`（startup/shutdown/install/uninstall 生命周期钩子），不再有 XUL overlay；bootstrap 作用域自动注入 `Zotero`/`Services`/`Cc`/`Ci` 全局[^z7dev][^filestructure]。

事实标准脚手架是 **`windingwind/zotero-plugin-template`**（TypeScript + esbuild）：配套 `zotero-plugin-toolkit`（ztoolkit——菜单/对话框/progress window/reader 注入的封装）与 `zotero-plugin-scaffold`（热重载、占位符替换、xpi 打包、`zotero-plugin release` 一键 bump+构建+GitHub Release+update.json 发布的完整 CI 流）[^template][^scaffold-release]。官方样例 `zotero/make-it-red` 只教骨架，社区模板才是生产路径——本节列出的所有翻译类插件全部用它。

### 能力面（本用例所需全部存在）

- **右键菜单**：Zotero 8 起有官方 `Zotero.Menu` API（registerMenu/unregisterMenu，卸载自动清理）；更早版本用 toolkit 的 MenuManager 手工注入 item context menu[^z8dev]。
- **挂附件**：`Zotero.Attachments.importFromFile({file, libraryID, parentItemID, title})` 建 stored attachment——社区插件实测用法一致[^writeapi]。
- **HTTP 出网**：`Zotero.HTTP.request(method, url, {data, headers, responseType})` 是特权上下文全功能客户端，调 `127.0.0.1:8765` 或远程 https 均无 CORS/权限障碍——zotero-pdf2zh 就是这么调 localhost:8890 的，路径已被验证[^httpreq]。
- **长任务**：插件侧 JS 轮询 `GET /api/task/{id}` + `Zotero.ProgressWindow` 进度提示即可；pdf2zh v4.1.6 起也是"翻译改后台任务"同款[^pdf2zh]。
- **设置页**：模板自带 preferences pane（`addon/prefs.js` + Fluent locale），存 server URL/API key。

### 打包与分发

- `.xpi` = zip；**Zotero 插件无需签名**（不走 Mozilla AMO 签名链，bootstrap loader 不验签），手动安装路径 Tools → Add-ons → ⚙ → Install Add-On From File[^plugins-doc][^papersgpt]。
- **没有官方商店**：官方文档仍写 "An official plugin directory is planned"[^plugins-doc]。实际分发三通道：① GitHub Releases + `update_url`→`update.json` 自更新（scaffold 全自动）[^scaffold-release]；② 社区注册表 **`zotero-plugin-dev/zotero-plugin-registry`**——PR 一个 meta.json（id/name/update_json 地址/homepage/tags）即收录，是新版社区商店前端的数据源[^registry]；③ 应用内商店插件 **`syt2/zotero-addons`（Add-on Market）**消费该注册表，用户量最大的中文社区入口[^addons-market]。
- 条目元数据里 arXiv id 的三个来源：preprint 条目类型的 `archiveID` 字段、`extra` 字段的 `arXiv: xxxx` 行、DOI `10.48550/arXiv.xxxx`——hjfy 插件即从 DOI/URL/Extra 提取，够覆盖[^hjfy]。

## 2. 对照插件逐个拆

### guaguastandup/zotero-pdf2zh（6.6k★，赛道标杆）

**架构即 texlate 插件的直接模板**：插件本体是 windingwind 模板的薄客户端（右键菜单 + 设置页 + 轮询），翻译全在用户自己跑的 **Python server.zip**（`uv run server.py` 监听 127.0.0.1:8890，含 requirements.txt）——插件经设置页 "Python Server IP" HTTP 调用，有"检查连接"探测按钮[^pdf2zh][^rosetears]。texlate 连 server.zip 这层都不用——`texlate web` 天然就是那个常驻服务。

- 用户流：右键条目/附件（支持批量）→ 四项菜单（翻译/裁剪/双语对照双栏/单栏）→ 后台任务 → 生成 PDF 挂回条目。v4.1.x 把翻译改后台、远程/Docker 完成后优先 HTTP 挂附件[^pdf2zh]。
- 规模：627 commits，插件源码在 `plugin/`（TS 中等复杂度插件量级），`server/` 是 Python 件；AGPL-3.0。
- 要点：**它证明了"插件=本地 Python 服务的薄壳"是学术用户接受度最高的形态**，6.6k★ 全部是这么用的。

### ANGJustinl/zotero-plugin-hjfy（22★，最小对照）

hjfy.top 的第三方拉取插件：从 DOI/URL/Extra 提 arXiv id → GET `hjfy.top/api/arxivFiles/{id}`（取 zhCN 件）→ stored attachment 挂回，标题 "中文翻译 - 原标题"；支持多选批量[^hjfy]。单体 `src/modules/arxivTranslation.ts`，windingwind 模板，AGPL-3.0。**这就是 texlate 插件 MVP 的形态下界**——把它的 hjfy API 换成 localhost texlate API 即得。

### windingwind/zotero-pdf-translate（11.8k★，最大但不同生态位）

划词/注释/元数据翻译（不是全文出文件）：选中弹窗、注释 comment 写译文、标题摘要右键翻译、20+ 翻译服务注册表（密钥存 prefs、自定义 endpoint、QPS 配额管理）[^pdf-translate]。**借鉴价值在模式不在代码**：service 注册表、自动语言检测跳过、item pane section 注入。AGPL-3.0——接口设计可参考，代码不能抄。

### immersive-translate/zotero-immersivetranslate（~330★，官方 SaaS 插件）

沉浸式翻译官方插件，**Pro 会员专属**：官网领授权码 → 设置页粘贴 → 右键"使用沉浸式翻译" → PDF 发云端 BabelDOC 服务[^imt-plugin]。证明了"Zotero 插件+远程翻译服务"的产品形态被商业验证；texlate 的对应物是"本地服务/自建远程 + BYOK"，正好切免费/自部署生态位。

## 3. texlate 插件形态推演

### MVP 功能切片（按依赖排序，全部不需要后端改动）

1. **arXiv id 提取**：`preprint.archiveID` → `extra` 字段 `arXiv:` 行 → DOI `10.48550/arXiv.*` → URL `arxiv.org/abs/*` 四级回落；非 arXiv 条目菜单置灰（texlate 管线吃 LaTeX 源不吃 PDF）。
2. **服务探测**：`GET /api/health` 探 `127.0.0.1:8765`；不在则弹引导（"先 `uvx texlate web`，或设置里填远程实例"）——pdf2zh 的"检查连接"按钮同款。
3. **建任务**：`POST /api/arxiv/{id}/translate`（远程实例加 `X-Texlate-Key` 头）。
4. **轮询**：`GET /api/task/{id}` 间隔轮询 + ProgressWindow；失败弹错误+可点日志链接。
5. **挂附件**：`GET /api/files/{id}/zh.pdf` 存临时文件 → `Zotero.Attachments.importFromFile` 挂 stored attachment，标题 "中文翻译 - {短标题}"；可选同步挂双语对照件。
6. **跳转阅读器**：菜单加"在 texlate 阅读器打开" → `GET /api/task/{id}/reader` 拿 URL → `Zotero.launchURL`——**这是 pdf2zh/hjfy 都没有的差异化**：它们是静态 PDF 附件，texlate 有活的 SPA 双语阅读器。
7. **设置页**：server URL（默认 127.0.0.1:8765）、可选 API key、默认挂哪些产物、批量并发数。

MVP 工程量：提取+菜单+轮询+挂附件+设置页 ≈ **800–1500 行 TS**（对比 pdf2zh 插件端数千行——它多了裁剪/拼接 PDF 等本地活，texlate 不用）。一天出骨架，一周内测，无需后端新端点。

### 做不做的判断：做，且成本低到不该犹豫

- **触达价值**：Zotero 是中文学术用户的事实入口——pdf2zh 6.6k★、pdf-translate 11.8k★、沉浸式官方插件 ~330★ 三档数据说明这条触手真实有效；hjfy 22★ 的第三方插件说明有 API 就会有人做（官方做只是抢先收编这个生态位）。
- **差异化**：三家都是"静态 PDF 挂附件"，texlate 能挂 PDF **并且**直接跳 SPA 双语阅读器——竞品给不了的形态。
- **成本**：MVP ≈ 千行 TS + 脚手架开箱；不碰后端（API 已齐）；维护面只有 strict_max_version 逐版 bump。
- **时机**：放 PyPI 发版之后（用户得先有 `uvx texlate web` 可装），作为 M2 分发面的一部分与冻结二进制并行。

### License 与风险

- 插件选 **Apache-2.0** 与主仓一致：经 HTTP 调 texlate 服务不构成衍生作品；windingwind 模板本体 MIT 可兼容。**注意三个对照插件全是 AGPL-3.0——一行代码都不能抄**，只能抄模式。
- 风险点小：① Zotero 大版本 strict_max_version 年 bump（成本一行字）；② 本地服务形态下"插件装了但 texlate 没装"的引导体验要靠探测+文档兜住；③ 非 arXiv 条目的翻译需求（PDF 上传路径）等 MinerU M3 落地后插件加个 `/api/upload` 分支即可，不影响 MVP。

### 参考文献

[^z7dev]: Zotero Documentation. Zotero 7 for Developers. [zotero.org](https://www.zotero.org/support/dev/zotero_7_for_developers)
[^z8dev]: Zotero Documentation. Zotero 8 for Developers（新菜单 API、Firefox 140 ESM 化）. [zotero.org](https://www.zotero.org/support/dev/zotero_8_for_developers)
[^z10dev]: Zotero Documentation. Zotero 10 for Developers（本地 API 写支持 + 安全加固）. [zotero.org](https://www.zotero.org/support/dev/zotero_10_for_developers)
[^changelog]: Zotero Documentation. Version History（8.0=2026-01-22, 10.0=2026-08-17）. [zotero.org](https://www.zotero.org/support/changelog)
[^filestructure]: windingwind. Plugin File Structure — Dev Docs for Zotero Plugin. [windingwind.github.io](https://windingwind.github.io/doc-for-zotero-plugin-dev/main/plugin-file-structure)
[^template]: windingwind. zotero-plugin-template. GitHub. [github.com](https://github.com/windingwind/zotero-plugin-template/)
[^scaffold-release]: zotero-plugin.dev. Scaffold Release 文档. [zotero-plugin.dev](https://zotero-plugin.dev/zotero-plugin-scaffold/release.html)
[^httpreq]: windingwind. HTTP Request — Dev Docs for Zotero Plugin. [windingwind.github.io](https://windingwind.github.io/doc-for-zotero-plugin-dev/main/http-request)
[^writeapi]: akchan/dzackgarza. zotero write api plugin（importFromFile 用法实证）. GitHub. [github.com](https://github.com/dzackgarza/zotero-local-write-api)
[^plugins-doc]: Zotero Documentation. Plugins（官方目录 "planned"）. [zotero.org](https://www.zotero.org/support/plugins)
[^registry]: zotero-plugin-dev. zotero-plugin-registry（meta.json PR 收录）. GitHub. [github.com](https://github.com/zotero-plugin-dev/zotero-plugin-registry)
[^addons-market]: syt2. zotero-addons — Zotero 内应用商店插件. GitHub. [github.com](https://github.com/syt2/zotero-addons)
[^papersgpt]: PapersGPT. Zotero 10 Plugin Compatibility（无签名、Install Add-On From File）. 2026. [papersgpt.com](https://www.papersgpt.com/en/blogs/zotero-10-plugin-compatibility)
[^pdf2zh]: guaguastandup. zotero-pdf2zh README（插件+server.zip 架构、后台任务、HTTP 挂附件）. GitHub. [github.com](https://github.com/guaguastandup/zotero-pdf2zh)
[^rosetears]: Rosetears. Zotero-pdf2zh 部署教程（server.zip uv run 127.0.0.1:8890、菜单四项）. 2025. [rosetears.cn](https://rosetears.cn/en/posts/archives-62-62/)
[^hjfy]: ANGJustinl. zotero-plugin-hjfy（DOI/URL/Extra 提 id、hjfy API 拉 zhCN、stored attachment）. GitHub. [github.com](https://github.com/ANGJustinl/zotero-plugin-hjfy)
[^pdf-translate]: windingwind. zotero-pdf-translate（划词翻译、20+ 服务注册表）. GitHub. [github.com](https://github.com/windingwind/zotero-pdf-translate)
[^imt-plugin]: immersive-translate. zotero-immersivetranslate（Pro 授权码 + 云端 BabelDOC）. GitHub. [github.com](https://github.com/immersive-translate/zotero-immersivetranslate)
