# zotero-pdf2zh 源码深读报告（2026-09-19）

对象：`guaguastandup/zotero-pdf2zh` v4.1.7（6.6k★，AGPL-3.0），clone 于 `tmp/refs/zotero-pdf2zh`。**只看模式不抄码**——AGPL 一行不能搬。本文回答：这个 6.6k★ 插件实际怎么工作，texlate 插件该抄哪些模式、避哪些坑。

## 1. 仓库结构与构建

- 插件本体在 `plugin/`：标准 windingwind/zotero-plugin-template 布局（`src/index.ts` 入口、`src/hooks.ts` 生命周期、`src/modules/`、`src/addon/content/preferences.xhtml` 设置页、`typings/`）。构建链：`zotero-plugin-scaffold`（`zotero-plugin serve/build/release`）+ `zotero-plugin-toolkit` v5，`package.json:scripts` 全套模板原样。
- `server/` 是同仓 Flask 服务端（`server.py` 1440 行 + `manage_packages.py`/`update_packages.py` 运行时环境管理 + `index.html` 监控页 + `bo.mp3` 完成提示音）；仓根直接提交 `server.zip`（就是 `server/` 目录的 zip，还带着 `__MACOSX` 垃圾文件）和编译好的 `.xpi`——**产物入库**，糙但直接。
- 双仓三件套：插件 xpi + server.zip + docs（vitepress 站）。

## 2. 启动流

`src/index.ts:6-16` 模板标准：BasicTool 拿全局 → new Addon → 挂 `Zotero.pdf2zh`。`src/hooks.ts:8-19` `onStartup` 等 `initializationPromise + unlockPromise + uiReadyPromise` 三 promise → `initLocale` → `registerPrefs` → 对每个 main window `onMainWindowLoad`（建 ztoolkit、注册右键菜单 `pdf2zh.ts:16-54`、初始化设置页表格）。无 notifier 订阅——纯命令式插件，不监听库变化。

## 3. 菜单系统

单个 submenu `PDF2zh` 挂在 item context menu（`ztoolkit.Menu.register("item", ...)`，`pdf2zh.ts:40-53`），4 个 menuitem：translate / crop / compare / crop-compare——**菜单项 = 服务端点字符串**，`commandListener` 走 `hooks.onDialogEvents` → `processWorker(endpoint)`。无"区分条目类型"逻辑：选中什么都能点，PDF 校验在使用时才报错（`pdf2zhHelper.ts:699-708`：取 best attachment → 必须 `.pdf` 结尾且文件存在）。批量 = `getSelectedItems()` 全选循环。

## 4. 插件↔服务协议（核心情报）

### 提交

`pdf2zhHelper.ts:296-394`：`POST {serverUrl}/{endpoint}`（translate/crop/crop-compare/compare 四个裸路径，不在 /api 下），JSON body = `{fileName, fileContent: base64, ...30 余个 config 字段, asyncJob: true, llm_api: {service,model,apiKey,apiUrl,extraData}}`——**PDF 整文件 base64 内联上传 + LLM key 由插件侧持有随请求下发**（texlate 是 server 侧 BYOK，插件不用传 key，更简单）。自定义头 `X-PDF2zh-Protocol: accepted`、`X-PDF2zh-Plugin-Version` 做协议握手。提交**不重试**（注释明确：防重复翻译同一篇）。

### 轮询（重要约束）

`pdf2zhHelper.ts:549-597`：**Zotero 插件沙箱没有 AbortController/ReadableStream/EventSource——SSE/WebSocket/流式全部不可用**（代码注释原文），只能 `setTimeout` 轮询。它每 1s 拉 **`GET /api/tasks` 全量列表**找自己的 taskId，找不到再 fallback `GET /api/history`——服务端没有单任务查询端点，插件被迫全表扫描。状态字段混乱实证：server 返回里混着中文 `"完成"/"失败"` 和英文 `success/failed/error`、`finished: true`、嵌套 `result.fileList/filePaths/outputDir`——`completedTaskPayload`（:436-487）写了 50 行兼容逻辑去归一。**教训：texlate API 的单任务端点 `GET /api/task/{id}` 设计已经比它对——保持单一任务查询 + 稳定英文状态机**。

进度：任务对象带 `progress`(0-100) + `message`，插件映射成阶段文案（submitting→accepted→running→importing→file-done/failed，`formatJobProgressText` :108-166）。超时上限 3h。另有一个 `COMPLETED_FILE_GRACE_MS = 20s`（:25）：server 报完成但文件还没落盘的容忍窗——异步任务"完成信号 vs 产物可见"的竞态是真实问题。

### 取回

`handleResponse` :599-666：完成后遍历 `fileList`，每个文件 `GET {base}/translatedFile/{fileName}`（`downloadTranslatedFile` :753-769，带 PDF magic 校验）→ 写临时文件 → `importFromFile`；HTTP 失败降级本地路径直读（`filePaths[i]`/`outputDir`——server 同机时的抄近路，:927-949）。下载重试 3 次。

## 5. 附件回挂

`addAttachment` :955-1016：`Zotero.Attachments.importFromFile({file, parentItemID, libraryID, collections, fileBaseName, title})` 建 **stored attachment**。细节讲究：临时文件名强制 ASCII（Windows `NS_ERROR_FILE_UNRECOGNIZED_PATH` 坑，:790-802）；存储叶名过 `Zotero.File.getValidFileName` 清跨平台非法字符；`parentItemID` 与 `collections` 互斥只能给一个；附件选中右键时回溯 `parentItemID` 挂到父条目。标题 = `{shortTitle}-{service}-{type}`（rename pref 开）或原始文件名。去重只有**批内** `attachKeys` set（:980-984）——**不查条目已有附件**，重复翻译会重复挂。`{type}-open` pref 开了就 `Zotero.Reader.open(id)` 直接弹内置阅读器。

## 6. 设置页

`preferences.xhtml` ~40 个 pref：`new_serverip`、engine、service/next_service、sourceLang/targetLang、threadNum/qps/poolSize、skipLastPages、六种产物开关 + 各 `-open`、rename、showProgress + 一串 pdf2zh_next 引擎专属开关（ocr/noDual/fontFamily/dualMode/术语表等，texlate 不需要）+ **LLM API 表格**（preferenceScript.ts 934 行的大头：VirtualizedTable + 对话框编辑器，service/model/apiKey/apiUrl/extraData 多配置管理——texlate BYOK 在 server 侧，插件完全不需要这块）。「测试连接」按钮 = axios `GET /health` 10s 超时，验 `status==="ok" || version`，失败弹三级排障文案（:838-933）。

## 7. UX 细节

- `JobProgressPopup`（:1154-1373）：共享单例 ProgressWindow，每文件一行 + 汇总行，phase 驱动文案/图标/进度，全部批次结束后 8s 自关；`showProgress` pref 可关。
- 完成提示音 `bo.mp3` 由 server 提供（给 index.html 用，插件没用）。
- 失败文案分级：逐文件 alert + 进度行变红。
- 无"已翻译"条目状态标记——不记历史、不查重（批内除外），重译代价用户自担。

## 8. 值得抄的模式 vs 坑

**抄**：单 submenu 菜单、processWorker 单入口分发、accepted→轮询协议、ProgressWindow 逐文件行、importFromFile 全参数用法（parentItemID/collections 互斥、ASCII 临时名、getValidFileName）、attachKeys 批内去重、健康检查按钮的三级排障文案、server 报完成 vs 文件可见的 20s 宽限。

**坑（issue 260 个实证）**：① server.zip 部署是摩擦源头——用户要先装 uv/conda 再 `uv run --with-requirements` 起服，`manage_packages.py` 运行时建/更新 venv 还交互式问 Y/N，issue 里 "自动生成pdf2zh_next虚拟环境失败"/"无法翻译"/"环境可以查找到但是无法翻译" 反复出现；texlate `uvx texlate web` 一条命令天然免疫——**这是它的部署形态税，我们没有**。② "翻译成功但是不会写入zotero"、"为什么翻译的pdf无法同步"——附件回挂与同步链路脆弱。③ "什么时候支持Zotero 9/适配zotero9" ×2——大版本 strict_max_version 年 bump 是固定维护税。④ 插件状态字段要兼容中英混排——协议字段没有单一事实源的下场。⑤ 菜单不置灰无 PDF 条目，校验全在使用时报错。

## 9. 规模实测

插件核心 TS **3146 行**：hooks 114 + pdf2zh(菜单) 55 + helper(协议+附件+进度) 1373 + preferenceScript(LLM 表格+健康检查) 934 + fileProcessor(批量) 71 + types 78 + utils ~220 + attachmentUtils 82 + llmApiManager 157。其中 LLM 配置管理（~1100 行）texlate 不需要——**texlate 插件 MVP 真实复杂度对标 helper+菜单+hooks ≈ 1500 行内，砍掉 LLM 表格和裁剪/对比三端点后还能再瘦**。

## 10. 对 texlate 插件的直接映射

| pdf2zh | texlate 插件 |
| --- | --- |
| POST /translate + base64 文件 | `POST /api/arxiv/{id}/translate`（不用传文件！arXiv id 即输入；PDF 上传走 `/api/upload` 备选） |
| body 带 llm_api key | 零——server 侧 BYOK 已配好 |
| 轮询全量 /api/tasks 找 taskId | `GET /api/task/{id}` 单点查询，1s→2s 间隔 |
| 状态中英混排 50 行兼容 | 单一英文状态机，零兼容负担 |
| GET /translatedFile/{name} | `GET /api/files/{id}/zh.pdf` |
| SSE 不可用只能轮询 | 同约束——texlate SSE 给 SPA 用，插件走轮询 |
| importFromFile 挂 zh.pdf | 同 API，可选加挂双语件 + "在阅读器打开"菜单项（`GET /api/task/{id}/reader` → `Zotero.launchURL`）——**差异化独有项** |
| server.zip + venv bootstrap 摩擦 | `uvx texlate web` 单命令；插件健康检查指向 `/api/health`，不在则引导安装 |
