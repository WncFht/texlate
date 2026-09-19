# zotero-pdf-translate 源码深读（2026-09-19）

仓库 `tmp/refs/zotero-pdf-translate`（v2.4.7，11.8k★，AGPL-3.0——只看模式不抄码）。它是划词/注释/元数据翻译插件，与 texlate「整篇翻译出 PDF」生态位不同；本文只萃取**插件工程模式**：服务注册表、设置页、UI 注入点、任务队列、发布链。

## 1. 结构与构建链

windingwind 模板标准布局：`src/`（TS，80 文件 ≈11k 行）+ `addon/`（manifest/prefs/locale/xhtml/静态资源）+ `typings/`（scaffold 生成）+ `zotero-plugin.config.ts`（scaffold 配置单源）。

- `zotero-plugin.config.ts:5-64`：`source:["src","addon"]`、esbuild 双入口（`src/index.ts`→`__addonRef__.js`、`src/extras/*` 平铺）、`target:"firefox115"`、`define` 占位符映射（`__addonID__`/`__buildVersion__`/`__updateURL__` 等注入 manifest.json 与 bootstrap.js 的占位符）、`updateURL` 指向 GitHub release 的 `update.json`。
- `package.json` scripts：`start`=`zotero-plugin serve`（热重载 dev）、`build`=`tsc --noEmit && zotero-plugin build`、`release`=`zotero-plugin release`（bump+构建+GitHub Release+update.json 一条龙）。
- `addon/manifest.json`：`manifest_version:2` + `applications.zotero` 块，`strict_min_version:"7.9.9"`/`strict_max_version:"10.9.9"`——一版跨 Zotero 7–10。
- `addon/prefs.js`（132 行）：`pref("__prefsPrefix__.key", default)` 逐行声明全部默认值；scaffold 据此生成 `typings/prefs.d.ts` 的 `PluginPrefsMap`，`getPref` 因此类型安全（`src/utils/prefs.ts:24-38`）。
- `addon/bootstrap.js`：官方 make-it-red 骨架，`startup` 里 `registerChrome` + `loadSubScript(scripts/__addonRef__.js, ctx)`，main window load/unload 转发到 `Zotero.__addonInstance__.hooks`。
- `src/index.ts:5-21`：幂等入口——`Zotero[addonInstance]` 不存在才 new Addon() 挂全局，防双载。

## 2. 服务注册表（最值钱的一块）

`src/modules/services/base.ts:7-63` 的 `TranslateService` 接口：

```ts
{ id, type:"word"|"sentence", name?, helpUrl?,
  defaultSecret?, secretValidator?(secret)=>{secret,status,info},
  translate(data)=>void,            // 写 data.result，出错 throw
  config?(settings:AllowedSettingsMethods)=>void,  // 声明式设置 UI
  requireExternalConfig? }           // true → 名字加 📍 后缀
```

- 注册即 `index.ts:53-100` 一个对象数组；`TranslationServices`（index.ts:102-463）提供：按"免费无配置→需配置→custom 兜底"排序（:114-151）、`getServiceNameByID` 给需密钥服务加 🗝️、需外部配置加 📍（:165-180）、`getUnconfiguredServiceIds` 从 `secretObj` pref 算未配置集（:199-235）、`runTranslationTask` 统一跑任务含语言禁用检查/缓存命中/candidateServices 失败回退链（:237-370）。
- **"自建服务器"范本是 `mtranserver.ts`（69 行全文）**：`getPref("mtranserver.endpoint")` 取 URL、`data.secret` 塞 authorization 头、`config(settings)` 加 endpoint 文本框+checkbox、`requireExternalConfig:true`——texlate 插件的 "server URL + X-Texlate-Key" 就是这个形状的等价物。
- 自定义服务槽位模式：`gpt.ts` 用 `createGPTService(id)` 工厂产出 `chatgpt/customgpt1/2/3/azuregpt` 五个同构服务（:486-495），各带独立 pref 前缀的 endpoint/model/prompt/customParams——**texlate 将来"多个 server 实例"可借这个多槽位思路**，但 MVP 一个 URL 就够，别先建抽象。
- 注意：**不是**"服务配置即 JSON"——每个服务是编译进 bundle 的 TS 对象；用户自定义面只有 customgpt/deeplcustom 的 endpoint 文本框。texlate 没有 49 个后端要适配，这层复杂度与我们无关。

## 3. 设置页（两层）

**主 pane**：`Zotero.PreferencePanes.register` 挂 `preferences.xhtml`（preferenceWindow.ts:13-20）；xhtml 里放 `-placeholder` 元素，`buildPrefsPane` 用 `ztoolkit.UI.replaceElement` 动态生成 menulist（枚举服务填 menuitem，:33-132），然后 **200+ 行逐个 querySelector 挂 listener**（:160-262）——直白但啰嗦，我们设置面小不需要学这层。

**每服务设置弹窗（推荐偷）**：`createServiceSettingsDialog`（settingsDialog.ts:231-263）调 `service.config(dialog)`，`AllowedSettingsMethods`（:103-116）提供声明式 API：`addTextSetting/addPasswordSetting/addNumberSetting/addCheckboxSetting/addSelectSetting/addTextAreaSetting/addCustomParamsSetting/addButton/addStaticRow/onSave(validator)`，收口自动 `addAutoSaveButton`。texlate 的"server URL + key + 挂哪些产物"用一个这种 dialog 就齐了，**零 xhtml**。

**Secret 存储**：所有 key 集中在一个 pref `secretObj`（JSON map `{serviceId: secret}`，secret.ts:18-27）；`defaultPrefs.ts:20-26` 启动时给每个服务种 `defaultSecret` 占位；`manageKeysDialog` 就是一个 textarea 编辑整份 JSON（manageKeys.ts:4-58）。`crypto.ts` 是 HMAC 签名工具（腾讯/阿里 API 用），**不是加密**——secret 在 Zotero.Prefs 里明文。`secretValidator`（_template.ts:83-97）返回 `{secret,status,info}` 做格式校验+用户提示。

## 4. UI 注入点全清单

| 注入点 | API | 位置 |
| --- | --- | --- |
| item 右键菜单 | `Zotero.MenuManager.registerMenu` target `"main/library/item"`，`onShowing` 里 `context.setVisible` 控制 | menu.ts:12-66 |
| reader 划词弹窗 | `Zotero.Reader.registerEventListener("renderTextSelectionPopup")` | reader.ts:8-16 |
| reader 注释侧栏按钮 | `registerEventListener("renderSidebarAnnotationHeader")` + `append()` | reader.ts:18-59 |
| item pane section | `Zotero.ItemPaneManager.registerSection`（header/sidenav/bodyXHTML 自定义元素 + sectionButtons） | tabpanel.ts:11-50 |
| item pane info row | `Zotero.ItemPaneManager.registerInfoRow`（ExtraField 读写，editable） | infoBox.ts:6-36 |
| itemTree 附加列 | `Zotero.ItemTreeManager.registerColumn`（dataProvider 读 ExtraField） | itemTree.ts:6-19 |
| notifier | `Zotero.Notifier.registerObserver(cb,["item"])` → hooks.onNotify 派发 | notify.ts:1-16, hooks.ts:129-160 |
| 快捷键 | `ztoolkit.Keyboard.register`（accel+T / concat 修饰键） | shortcuts.ts |

值得注意的实战 trick：reader.ts:27-58 在 >1000 注释时用 `img error` 事件 + `requestIdleCallback` 延迟创建按钮防阻塞主线程。自定义元素 `customElements.js` 在 mainWindow load 时经 `Services.scriptloader.loadSubScript` 注入（hooks.ts:88-95）。

texlate 需要的面：**item context menu（必须）+ item pane section 显示任务状态/阅读器链接（可选）+ notifier 做"同步来的新 arXiv 条目自动翻"（可选，同款 enableAnnotationFromSyncTranslation 模式）**。reader 注入与 texlate 无关——翻译产物不是它 reader 里的东西。

## 5. 任务与进度

- `TranslateTask`（task.ts:8-93）：raw/result/service/candidateServices/status(waiting|processing|success|fail)/extraTasks；queue 挂 `addon.data.translate.queue` 上限 100 截断（cleanTasks :358-370）。
- 缓存即 queue 内 `findLast` 同 raw+service+lang（index.ts:290-313）——**进程级、不落盘**。
- 批量 = `for` 顺序 await + `batchTaskDelay` 1000ms（hooks.ts:226-230）——无并发。texlate 插件批量翻多条目时值得照搬"顺序+间隔"，别把 server/网关打爆。
- 错误呈现：异常→`task.result=错误文本`+`status:"fail"`（task.ts:164-180），UI 层统一展示；`sanitizeTaskForLog` 打日志前给 secret 打码（task.ts:101-127）——好习惯，抄。
- `TranslateTaskRunner.run`（task.ts:135-173）：注入 `data.secret = getServiceSecret(service)` → processor → success/fail。

## 6. i18n

Fluent：`addon/locale/{en-US,zh-CN,it-IT}/{addon,mainWindow,panel,preferences,standalone}.ftl`；`getString(id,{args})`；主窗用 `MozXULElement.insertFTLIfNeeded` 挂 ftl（hooks.ts:93-95）；服务显示名 = `service-${id}` key + `renameServices` pref 用户改名（index.ts:166-167）。zh-CN/en-US 双语手维护。

## 7. update/发布

tag `v**` 推 GitHub → `.github/workflows/release.yml`：npm install → build → `npm run release`（scaffold 发 xpi 到版本 release + 推 `update.json` 到固定 `release` tag 下，config.ts:11-15）；`apexskier/github-release-commenter` 自动回帖已修复 issue。beta 版走 `update-beta.json` 分流（version 含 `-` 判定）。

## 8. 规模与复杂度

`src/` 80 文件 ≈11k 行，其中 `services/` 49 文件 ≈4.5k 行——**一半代码是 49 个翻译后端的适配**。复杂度集中：settingsDialog 676 + preferenceWindow 551 + gpt 496 + task 488 + services/index 463 + panel 元素 447 + popup 414。剥掉 texlate 用不上的（services 适配层、reader popup/panel、KaTeX），我们需要的面（菜单+HTTP+轮询+附件+设置）证实 <1.5k 行可行。

## 9. 值得抄 vs 不要抄

**值得抄（模式复刻，不是代码）**：

1. `AllowedSettingsMethods` 声明式设置弹窗（settingsDialog.ts:118-263）——texlate 的 server URL/API key/产物勾选用它一个 dialog 齐活。
2. `mtranserver.ts` 全文件 = "自建服务 endpoint+secret 头"最小范本。
3. 🗝️/📍 后缀表达服务配置状态（index.ts:165-180）；`getUnconfiguredServiceIds` 做"未配置隐藏"可用在菜单置灰逻辑。
4. `secretObj` 单 pref JSON map（多实例 key 一处存）+ `sanitizeTaskForLog` 打码（task.ts:101-127）。
5. candidateServices 失败回退链（index.ts:360-364）——将来多 server 实例/本地不在退远程时有原型。
6. scaffold 生成 `prefs.d.ts` → `getPref` 类型化；`update.json` 固定 release tag 的自更新渠道。
7. hooks 只做派发的纪律（hooks.ts:259-260 注释自带警告）。

**不要抄**：

1. `buildPrefsPane` 200+ 行手写 listener 接线——设置面小走 dialog 模式。
2. 自造 task queue/cache——texlate 任务在 server 侧，插件只要 `{itemKey: taskId}` 状态 map + ExtraField 写 `texlateTaskId` 做幂等（防重复翻）。
3. ExtraField 存译文文本的模式——我们产物是附件不是字段。
4. 明文 secret 可接受（Zotero.Prefs 无加密存储），但 README 写明 X-Texlate-Key 本地明文。
5. AGPL——以上全部只复刻模式，零代码搬运。
