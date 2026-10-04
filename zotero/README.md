# zotero-texlate

[TeXlate](https://hjfy.top) 的 Zotero 7 插件：右键 arXiv 条目 →「TeXlate：翻译为中文」→ texlate 服务器拉取论文 LaTeX 源码、段落级翻译、重编译中文 PDF；插件轮询任务到终态，把生成的 `zh.pdf` 挂为条目附件，并在 Extra 字段写入 `texlate: <taskId>` 幂等标记。已译条目出现第二个菜单项——「TeXlate：在阅读器打开」，打开 `{serverUrl}/#/reader/{taskId}` 双语对照阅读器。

插件是瘦客户端：取源、解析、翻译、编译全在服务端。Zotero 里不需要 LLM key、TeX 引擎、Python。

## 依赖

- **Zotero 7.0+**（`strict_min_version` 7.0，`strict_max_version` 10.*）
- **一个跑起来的 texlate 服务**，本地或远端均可——本地实例**插件可自助拉起**：`serverUrl` 指向 loopback 且服务不可达时，插件自动下载 uv 独立二进制（无 uv 时，钉版本+sha256 校验）并拉起 `uvx texlate web`，首次需数分钟安装依赖。也可以手动：

```bash
uvx texlate web          # → http://127.0.0.1:8765（本仓内：uv run texlate web）
```

翻译凭据归服务端管（web Settings 页 BYOK，或 `TEXLATE_*` 环境变量）——插件只发 `POST /api/arxiv/{id}/translate` 空体请求；模型、目标语言、key 全部来自服务端设置。首次自助拉起后若任务报 `needs_auth`，插件会自动打开 Settings 页配置 BYOK。

## 安装

- **一键安装**（需已装 [Add-on Market](https://github.com/syt2/zotero-addons)）：市场内搜「TeXlate」直装；或把下面的深链粘进浏览器地址栏，唤起 Zotero 确认安装：

  `zotero://zoteroaddoncollection/install?source=https%3A%2F%2Fgithub.com%2FWncFht%2Ftexlate%2Freleases%2Flatest%2Fdownload%2Ftexlate.xpi`

- **手动安装**：从 [Releases](https://github.com/WncFht/texlate/releases/latest) 下载 `texlate.xpi`，Zotero → **工具 → 插件 → 齿轮图标 → 从文件安装附加组件…** → 选该文件。

插件按 `update_url` 自动轮询更新，发新版无需手动重装。

自行构建：

```bash
npm ci
npx zotero-plugin build   # → .scaffold/build/texlate.xpi
```

隔离 profile 的开发回路（mock 服务 + fixture + RDP 验证编排）见 `dev/README.md`。

## 配置

Zotero → 设置 → **TeXlate**——偏好面板内联展示即改即存。全部偏好存在 `extensions.zotero.texlate` 前缀下（`addon/prefs.js`）：

| 偏好               | 默认值                  | 含义                                                                                  |
| ------------------ | ----------------------- | ------------------------------------------------------------------------------------- |
| `serverUrl`        | `http://127.0.0.1:8765` | texlate 服务 base URL                                                                 |
| `apiKey`           | _（空）_                | `X-Texlate-Key` 请求头——只有远端 `TEXLATE_MODE=server` 实例需要；本机 loopback 不用填 |
| `attachZhPdf`      | `true`                  | 完成后挂载 `zh.pdf`                                                                   |
| `attachEnPdf`      | `false`                 | 挂载 `en.pdf`                                                                         |
| `batchDelayMs`     | `1000`                  | 多选批处理条目间延迟                                                                  |
| `pollIntervalMs`   | `2000`                  | 任务状态轮询间隔                                                                      |
| `pollTimeoutMs`    | `10800000`              | 轮询放弃时限（3 小时）                                                                |
| `autoStart`        | `true`                  | loopback 服务不可达时自动拉起本地服务（无 uv 自动下载）                               |
| `bootstrapDataDir` | _（空）_                | 高级：拉起服务时传 `--data-dir` 覆盖数据目录（默认 `~/.texlate`）                     |

「检查连接」用面板当前值 ping `GET /api/health`；「启动本地服务」立即走一遍自助拉起链（下载 uv→拉起→等待就绪），状态写回同一行。

API key 以**明文**存在 Zotero 偏好里——和所有 Zotero 插件偏好一样。

## 行为说明

- **arXiv id 提取** — 四级回退 `DOI → url → archiveID → extra`（`src/modules/arxivId.ts`）。原始 id 原样透传——`v3` 版本后缀与旧格式 `hep-th/9901001` 都带；解析归服务端的 `normalize_arxiv_id`。没有 arXiv 痕迹的条目不可翻译。
- **菜单置灰** — `computeMenuState(items)`（`src/modules/menu.ts`）：≥1 个选中普通条目有可提取 arXiv id 且无 `texlate:` 标记时显示「翻译为中文」；≥1 个选中条目带标记时显示「在阅读器打开」；两者都不满足时整个子菜单隐藏。多选时逐条顺序翻译，间隔 `batchDelayMs`。
- **幂等标记** — Extra 里的 `texlate: t_xxx` 行是唯一事实源：已标记条目再翻译会短路为「已翻译」，菜单翻转成阅读器入口。只重写本插件的标记行；Extra 其他行逐字节保留。
- **附件** — 产物下载到纯 ASCII 临时文件，对照 `/api/files` 清单校验 sha256、查 `%PDF` 魔数，再以 `TeXlate {中文|英文原文} - {短标题}` 为名导入为存储附件。任务终态 `partial` 仍挂载已有产物并加警告行；`needs_auth` 打开 `{serverUrl}/#/settings` 做 BYOK 登录。
- **进度** — 插件沙箱没有 EventSource/ReadableStream，进度靠 `setTimeout` 轮询 `GET /api/task/{id}` 映射到 11 态机（queued → fetching → parsing → translating → compiling → done / partial / fault / cancelled / interrupted / needs_auth）。传输层失败最多连重试 5 次——服务端可能中途重启；HTTP 4xx 与未知状态立即失败。
- **去重收养** — 服务端对活跃任务按 cache_key 去重：重复翻译同一篇会拿到 `409 duplicate_active` 与现存 task_id。插件收养前先读该任务状态——若落在可重试终态（`fault`/`partial`/`cancelled`/`interrupted`/`needs_auth`，含占着去重槽位的 `interrupted`）先 `POST /api/task/{id}/retry` 复活再轮询，否则直接收养。
- **自助拉起** — `src/modules/bootstrap.ts`：health 传输层失败 + `serverUrl` 为 loopback + `autoStart` 开 → `ensureServer()`：managed `~/.texlate/bin/uv` → PATH `uvx`/`uv` → 无则下载钉版 uv（五平台 sha256 矩阵、系统 `tar` 解压）→ `sh -c 'nohup … &'` 脱离 Zotero 生命周期拉起（Windows 走 PowerShell `Start-Process`）→ 轮询 health 至就绪（上限 300s）。服务日志在 `~/.texlate/bootstrap-server.log`；`service.lock` 幂等——重复拉起无害。非 loopback 地址、开关关闭时原样报不可达。

## Dev API

挂在 `Zotero.texlate` 上供 `dev/` 验证工具链用（经 RDP eval 驱动——见 `dev/README.md`）：

```js
await Zotero.texlate.selftest(itemID); // 全链 → SelftestResult {ok, steps[], taskId}
await Zotero.texlate.selftestNonArxiv(itemID); // 负例路径：extract→null + mark→none
Zotero.texlate.api.computeMenuState(items); // 菜单可见性纯谓词 → {translate, reader}
Zotero.texlate.api.bootstrap.findUv(); // uv 探测 → {cmd,args} | null
Zotero.texlate.api.bootstrap.ensureServer(prefs); // 直跑拉起链（dev-verify 用）
```

`selftest` 走 resolve-item → prefs → health → extract → already-marked → create → poll → files → download+attach → mark → attachments-verify → reader-url，每步记录可归因证据；绝不抛异常——失败落 `steps[i].detail`，`error` 字段点名首个失败步骤。

## 开发

```bash
npm install     # 工具链
npm run build   # zotero-plugin build + tsc --noEmit → .scaffold/build/
npm start       # scaffold serve（需要 .env——见 .env.example）
npm test        # 真 Zotero 里跑 mocha
```

## 目录

- `addon/` — 静态资源：manifest（Zotero 7.0–10.\*）、bootstrap、偏好默认值、locale（en-US/zh-CN）、preferences.xhtml
- `src/` — `hooks.ts` 只做分发；逻辑全在 `src/modules/`（client / arxivId / poller / attach / prefs / menu / flow / selftest）；共享签名在 `src/contracts.ts`
- `typings/` — scaffold 生成的 d.ts
- `dev/` — 验证工具链 + research 笔记（`dev/README.md`）

## License

Apache-2.0。基于 [windingwind/zotero-plugin-template](https://github.com/windingwind/zotero-plugin-template) 脚手架。
