# texlate × Zotero 插件设计方案（2026-09-19）

基于三份深读（[zotero-plugin.md](zotero-plugin.md) 生态面、[pdf2zh-read.md](pdf2zh-read.md) 赛道标杆源码、[pdf-translate-read.md](pdf-translate-read.md) 工程模式）+ `tmp/refs/` 三个 clone 实测。本文定插件的产品形态与 MVP 设计，供实施按此执行。

## 一、产品形态

**薄客户端**：插件只做「入口 + 取回」，重活全在 texlate server（本地 `uvx texlate web` 或远程实例）。这个形态是赛道验证过的——zotero-pdf2zh 6.6k★ 全靠「插件=本地 Python 服务薄壳」；我们比它少一层部署摩擦（它要用户 server.zip+venv bootstrap，260 个 issue 的摩擦源头；texlate 一条 `uvx texlate web` 免疫）。

用户流两条：

1. 右键条目 → **「TeXlate：翻译为中文」**→ 后台任务（Zotero 不阻塞）→ 完成通知 → zh.pdf 自动挂为条目附件。
2. 右键条目 → **「TeXlate：在阅读器打开」**→ `Zotero.launchURL("{server}/#/reader/{taskId}")`——活的 SPA 双语阅读器。**这是三家竞品插件都给不了的差异化**：它们只能挂静态 PDF。

条目上记 `Extra: texlate: {taskId}` 做幂等标记——已译条目的菜单项自动从「翻译」变「打开阅读器」，重复翻译零成本（server 侧 `prefer:reuse` 的 cache_key dedup 也兜住同 id 重复建任务）。

## 二、MVP 功能切片（v0.1，~1.2k 行 TS，零后端改动）

| 切片 | 做法 | 依据 |
| --- | --- | --- |
| arXiv id 提取 | DOI → URL → archiveID → extra 四级回落；原始串（含 `hep-th/` 老格式、版本号 v2）直接传 server `normalize_arxiv_id` 解析——hjfy 插件正则只吃 `\d+\.\d+` 漏老论文，我们全量交给服务端 | hjfy arxivTranslation.ts:122-164 |
| 服务探测 | 设置页「检查连接」→ `GET /api/health`；菜单触发时探测失败 → 引导文案（`uvx texlate web` 或设置远程 URL） | pdf2zh 三级排障文案 :838-933 |
| 建任务 | `POST /api/arxiv/{id}/translate`，body `{}` 全默认（model/target_lang 吃 server settings，BYOK 也在 server）——**插件不碰 LLM 配置** | app.py:1171 |
| 进度轮询 | `setTimeout` 2s 轮询 `GET /api/task/{id}` 单点端点。**插件沙箱无 EventSource/ReadableStream**（pdf2zh 代码注释实证），SSE 用不了——轮询是唯一通道 | pdf2zh pdf2zhHelper.ts:549-597 |
| 状态映射 | 11 态机：5 个 active 态映射阶段文案（排队→取源→解析→翻译→编译），terminal 分流——done/partial 挂附件、fault 弹错误、needs_auth 打开 `{server}/#/settings` 配 key、cancelled/interrupted 提示 | store.py:152-158 |
| 附件回挂 | 临时文件（**ASCII 名**——pdf2zh 踩过 Windows `NS_ERROR_FILE_UNRECOGNIZED_PATH`）→ `Zotero.Attachments.importFromFile({file, parentItemID, libraryID})` stored attachment；标题「TeXlate 中文 - {短标题}」；`Zotero.File.getValidFileName` 清洗 | pdf2zh :790-802, :955-1016 |
| 产物清单 | `GET /api/files/{id}` 看 `artifacts` 里有哪些 kind 再挂：zh.pdf 默认；`prefer:reuse` 下历史任务可能只有部分产物 | app.py:1297 |
| 竞态宽限 | 任务终态 → files 404 时重试 ~20s 窗（pdf2zh `COMPLETED_FILE_GRACE_MS` 实证：完成信号与产物落盘有间隙） | pdf2zhHelper.ts:25 |
| 幂等 | `Extra` 字段写 `texlate: {taskId}`（Zotero 的 extra 是官方溢出字段）；批内 Set 去重 | pdf-translate ExtraField 模式 |
| 批量 | 多选顺序 await + 1s 间隔（pdf-translate `batchTaskDelay` 模式）——别把网关/server 打爆，并发交给 server 队列 | hooks.ts:226-230 |
| 设置页 | 声明式 dialog（pdf-translate `AllowedSettingsMethods` 模式，零 xhtml）：server URL（默认 `http://127.0.0.1:8765`）、API key（`secretObj` 单 pref JSON，明文、README 写明）、附件开关（zh.pdf 必挂；en.pdf/dual 可选挂）、批间隔 | settingsDialog.ts:118-263 |
| 菜单置灰 | 无 arXiv id 的条目 menuitem `setVisible(false)`（pdf-translate `onShowing` 模式）——pdf2zh 不置灰、使用时才报错是差评点 | menu.ts:12-66 |

## 三、架构

windingwind 模板（TS + esbuild + scaffold，热重载/打包/release 一条龙）：

```
src/
  index.ts        幂等入口（Zotero.texlate ??= new Addon()）
  hooks.ts        只做派发（pdf-translate 的纪律，不堆逻辑）
  modules/
    menu.ts       右键菜单两项 + onShowing 置灰
    client.ts     fetch 封装：base URL + X-Texlate-Key 注入 + 错误归一（mtranserver.ts 69 行形状）
    poller.ts     任务轮询：interval/超时(3h)/状态→文案/files 宽限
    attach.ts     下载→临时文件→importFromFile→ExtraField 标记
    prefs.ts      声明式设置 dialog + secretObj
    arxivId.ts    四级提取 + 传给 server normalize
addon/            manifest(min 7.0.* / max 10.*) + bootstrap + prefs.js + locale(en-US/zh-CN ftl)
```

**仓内位置 `zotero/` 子目录**（pdf2zh 也是插件+server 同仓）：server API 演进同 commit 改两侧；CI 加 `zotero` job 跑 `tsc --noEmit` + scaffold build。License Apache-2.0 与主仓一致（HTTP 调用不构成衍生作品；三家对照全 AGPL——**只抄模式零代码搬运**）。

## 四、明确不做（MVP 范围外）

- **LLM/模型/术语表配置**：pdf2zh 为此烧了 ~1100 行 LLM 表格（插件 3146 行的 1/3）——texlate BYOK 在 server settings，插件只传 `{}`。
- **多 server 槽位**：pdf-translate `createGPTService` 多槽位模式留作 extension point；MVP 单 URL 够（本地 or 一个远程）。
- **非 arXiv 条目**：菜单置灰；`/api/upload` 路（MinerU/PDF 上传）等 M3 落地后 v0.3 加。
- **task queue/cache 自造**：任务状态和缓存在 server 侧天然完备（cache_key dedup + 任务列表），插件不复制。
- **reader 注入/划词**：texlate 产物不在 Zotero reader 里读（在自家 SPA），不挂 reader popup。

## 五、路线图

- **v0.1（MVP）**：上表全切片；GitHub releases + `update.json` 自更新（scaffold 自带）。
- **v0.2**：item pane section（`ItemPaneManager.registerSection` 显示任务状态+「打开阅读器」链接）；partial 态产物选择（无 zh_pdf 时挂 md_zip/zh_html 并提示）；双语对照件作为第二附件选项。
- **v0.3**：notifier 监听 sync 新条目自动翻译（pdf-translate `enableAnnotationFromSyncTranslation` 同款）；`/api/upload` 非 arXiv 路。
- **v1.0**：`zotero-plugin-registry` PR + `zotero-addons`（Add-on Market）收录——中文学术用户最大入口；README 中英。

**时机**：PyPI 发版之后（用户得先有 `uvx texlate web` 可装）。与 Windows 冻结二进制并行——两者共同构成「不会敲命令的学术用户」的完整路径：装 Zotero 插件 → 插件引导装 texlate → 右键即用。

## 六、验证方案（本机可全链跑通）

本机已装 Zotero 140.10.0esr（Zotero 10 线）+ `xvfb-run`（无 DISPLAY）+ `yay`。分三层：

### L0 单测（vitest，Zotero API 打 stub）

纯逻辑件：四级 arXiv id 提取、11 态→文案映射、ExtraField `texlate:` 幂等解析、轮询退避、错误归一。模板自带 `zotero-plugin test`（mocha 跑在**真 Zotero 进程内**——hjfy 的 `test/startup.test.ts` 就是 `assert.isNotEmpty(Zotero[addonInstance])`），装载冒烟顺手 cover。

### L1 server 侧 e2e（插件协议层的靶子先立住）

`TEXLATE_TRANSLATOR=mock uv run texlate web`——`xlat/mock.py` 确定性假翻译，不触 LLM、零 token，但 fetch/parse/tectonic 编译全真，产出真 zh.pdf。curl 走一遍 `POST /api/arxiv/{id}/translate` → 轮询 → `GET /api/files/{id}` → 下 zh.pdf，插件协议层的靶子就有了。另有不配 key 不设 mock → `needs_auth` 态正好验插件引导分支。

### L2 插件在真 Zotero 里跑通（核心验证）

- **隔离**：`zotero --profile tmp/zotero-dev/profile` 专用 dev profile（`-P` 是 profile 名、`--profile` 才接路径）——本机 Zotero 是用户的真实库，绝不污染；夹具用魔法棒「Add Item(s) by Identifier」输 arXiv id，零 PDF 纯元数据条目。
- **装载**：`xvfb-run npx zotero-plugin serve`（scaffold 自带：建 dev profile + 热重载装载 + 重建自动刷新）。
- **脚本化驱动**（不真点右键）：`zotero --start-debugger-server 6100` 起 Firefox RDP devtools server → 脚本连接在 main window context evaluate JS——`ZoteroPane` 选条目、直接调插件的翻译函数、断言 `item.getAttachments()` 增量与 Extra 标记。插件里埋 `Zotero.texlate.selftest(itemId)` 调试入口跑「探测→建任务→轮询→挂附件→读标记」全链返回结果对象，e2e 断言全在返回值里。
- **断言面**：health 探测关→开、非 arXiv 条目菜单置灰、done 后附件落位 + 标题格式、Extra 幂等标记、重复触发不重挂、`#/reader/{taskId}` URL 拼接正确、needs_auth 引导分支、partial 态产物选择。

### L3 常态化

L2 的 selftest 断言写成 mocha 测试文件，`xvfb-run npm run test`（`zotero-plugin test`）进 CI——Zotero GUI 测试全生态都这么干（三家对照均无真 e2e，我们做到这层已经超前）。

## 七、实证坑清单（三家踩过的，别再踩）

1. 插件沙箱无 EventSource/AbortController/ReadableStream → 只能轮询（pdf2zh 注释实证）。
2. Windows 临时文件名必须 ASCII（pdf2zh :790-802）。
3. `importFromFile` 的 `parentItemID` 与 `collections` 互斥只给一个。
4. server 终态 ≠ 产物可见——files 404 重试窗 ~20s。
5. `strict_max_version` 每 Zotero 大版本 bump 是固定维护税（pdf2zh issue 里 "适配 zotero9" ×2）。
6. 状态字段单一事实源——pdf2zh 服务端中英状态混排逼出 50 行兼容，texlate API 已是单任务+英文状态机，保持住。
7. 明文 secret 可接受（Zotero.Prefs 无加密层），README 写明即可。
