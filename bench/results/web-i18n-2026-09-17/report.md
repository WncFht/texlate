# web-i18n — 完整性审计 + 小修落盘

> 2026-09-17。scope：web/src/i18n + 组件文案接线。122 vitest 绿、tsc/eslint 净。

## 审计结论

**(a) 调用了但 zh.ts 缺键：0**。`t` 是普通嵌套 const（非函数），全部 `t.<sec>.<key>` 字面访问逐一核对——含三波新特性（shareBtn 10 键、usage 面板 stats* 7 键、BYOK optKey*）——零缺失。

**(b) zh.ts 死键：1**。`home.mock`（"Mock API"）全仓零引用，疑为已拆的 dev 开关残留——已删。Record 三段（status/kind/files）条目看似零调用实走 `t.status[x]` 括号访问，已逐词表核对：status 11 值 = server/store.py 非终态5+终态6 全覆盖；kind 6 值覆盖 TaskKind 联合+share；files 10 值 = FileKind 联合。

**(c) 硬编码字面量：5 处已接线**

- `Reader.tsx:579` `（可重试）` → 新键 `reader.retryable`
- `HtmlPane.tsx:80` `（无内容）` → 新键 `reader.chunkEmpty`
- `PdfPane.tsx:193` `aria-label="加载 PDF"` → 新键 `pane.pdfLoading`
- `PdfPane.tsx:196` `PDF 加载失败：` → 新键 `pane.pdfError`
- `Settings.tsx:179` `<option>auto</option>` 裸英文 → `t.home.engineAuto`（Home 同值已本地化"自动路由"，Settings 漏了；同页 optOn/optOff 跨段复用先例一致）

**(d) Record 访问回退不齐：2 处补齐**。宅例是 `?? 原值`（TaskList:108/116、Reader:574/822、taskFiles:50 均有），独缺 `TaskList.tsx:119` `t.status[task.stage??task.status]` 与 `Reader.tsx:779` `t.status[s]`——均已补 `??`（今天 TaskStage 闭集不会 miss，防服务端词表超前于前端类型时渲染空白）。

**(e) index.html `<title>` 硬编码** 与 appName/tagline 重复——`main.tsx` 加 `document.title` 接线，zh.ts 成唯一事实源。

## 机制档（非 bug，记档）

无 en.ts、无 fallback 链、无 locale 开关——zh-only 是 zh.ts 头注声明的 M3 设计（"结构留 i18n 余地"），英文 UI 属架构级 backlog。缺键运行期行为：`undefined` → JSX 渲染空白（Record 访问有 `??` 兜底）；静态访问靠 tsc 编译期兜。`index.html` `lang="zh-CN"` 与设计一致。

## 改动文件（8 + 1 新）

- `web/src/i18n/zh.ts` — 删 `home.mock`；+`reader.retryable`/`reader.chunkEmpty`/`pane.pdfLoading`/`pane.pdfError`
- `web/src/pages/Reader.tsx` — 2 处接线
- `web/src/pages/Settings.tsx` — auto → engineAuto
- `web/src/components/TaskList.tsx` — `??` 回退
- `web/src/reader/HtmlPane.tsx` — import t + chunkEmpty
- `web/src/reader/PdfPane.tsx` — import t + 2 处
- `web/src/main.tsx` — document.title
- `web/src/test/i18n.test.ts` — **新增**：Record 段词表覆盖契约测试（status 11/kind 6/files=DB_TO_URL_KIND 全集 + 无空白叶值），服务端词表扩张时先于 UI 空白报警

## 验证

`npx tsc --noEmit` 净；`npx eslint`（8 触碰文件）净；`npx vitest run` **18 文件 122 测试全过**（新增 4 断言在内）。
