# App 壳技术栈调研：Python 后端 + 现成 SPA 怎么包成桌面/移动应用

调研时点 2026-09-19。场景设定：texlate 已是「本地 FastAPI+SSE+SQLite 服务 + 构建好的 SolidJS SPA」形态，`texlate web` 一键起服务、CLI `run --server` 已有瘦客户端模式；tectonic 引擎已实现五平台托管下载。问题只剩一个——怎么把这个本地 web 应用包成「双击即用」的东西。Electron 已于 2026-09-18 裁决不做（M1 范围外，M2/M3+ 可再议），本文重点在非 Electron 选项，Electron 只作对照基线。

## 结论先行

对 texlate 这种「SPA 已经写好、后端是 Python 本地服务」的形态，壳层只有三个真实选项，按投入排序：

1. **不套壳**：冻结二进制 + 启动后自动开浏览器（pdf2zh 同款形态，Windows 用户体验天花板就在此）；
2. **pywebview 壳**：冻结二进制里内嵌一个系统 webview 窗口，Windows/macOS 体验完整，Linux 退化为浏览器（WebKitGTK 依赖 PyGObject 系统包，PyInstaller 无法打进包——这是硬伤不是配置问题）；
3. **Tauri 2 sidecar 壳**：Rust 壳 + 同一个 PyInstaller 产物做 sidecar，换来真安装器/updater/tray/单实例/移动端通道，代价是要写少量 Rust、引入 Node+Cargo 双工具链，且**签名问题一个都不帮你解决**。

Flet/PySide6/Neutralino/Wails 对 texlate 都不成立：前两者要求重写 UI，后两者生态薄、且同样得 spawn Python（见下文）。

## 方案逐个过

### Tauri 2.x + Python sidecar

官方 sidecar 机制是成熟做法：`tauri.conf.json` 的 `bundle.externalBin` 声明二进制，文件名必须带 `-<target-triple>` 后缀，Rust 侧经 `tauri_plugin_shell` 的 `shell().sidecar(name)` spawn，权限在 `capabilities/*.json` 里逐条声明[^tauri-sidecar]。现成样板不少：`example-tauri-v2-python-server-sidecar`（Next.js + FastAPI + PyInstaller，开箱即用）[^tauri-template]、voicebox（React + FastAPI + PyInstaller，生产中的两阶段构建：先 `pyinstaller --onefile` 出 server 二进制，拷进 `src-tauri/binaries/`，再 `tauri build` 出 DMG/MSI/AppImage）[^voicebox]。

体积/内存对比（2025-26 多个来源互证）：Tauri v2 真实应用安装包 3–15MB、常驻内存 30–65MB、冷启动 0.3–1s；Electron 对应 80–150MB+、150–300MB、1–3s[^woyable][^openreplay]。同一应用双实现的对照实验：Electron 138MB→Tauri 14MB，内存 210MB→65MB[^regaya]。

坑（实测记录，非理论）：

- **杀不掉 sidecar**：one-file PyInstaller exe 有 bootloader 双层进程，Tauri 只拿到 bootloader 的 pid，`process.kill()` 杀不到真子进程——必须自己实现关停协议（stdin 命令或 HTTP `/shutdown` 端点）[^tauri-template]。孤儿后端占住端口是该模式的第一大故障面[^amicoscript]。
- **webview 不一致**：WebView2(Win)/WKWebView(macOS)/WebKitGTK(Linux) 三家渲染有差异，WebKitGTK 落后数月——`:has()`、container queries、view transitions 在新 CSS 上会踩；Linux 的 WebKitGTK inspector 难用[^regaya][^openreplay]。texlate 的 pdfslick 阅读器渲染复杂度高，这一点要在真机上验证，不能假设。
- **签名不解决**：`.dmg`/`.msi` 安装器和钩子都在，但证书是独立的付费线——未签名 dmg 照样被 Gatekeeper 拦，sidecar 里的 PyInstaller 二进制也一样要 notarize[^amicoscript]。
- **Linux 依赖**：`.deb` 可以声明 `libwebkit2gtk-4.1` 让 apt 解决，反而比 pywebview 干净[^amicoscript]。

小结：体积 极小（壳 ~8–12MB + Python sidecar 体积）｜成熟度 桌面高、移动端中｜适合度 **最终形态候选**——当需要 updater/tray/安装器/移动端时上，之前不用。

### Tauri 2 移动端

v2（2024-10 稳定）起支持 iOS/Android，同一套 Rust+前端代码五平台编译；移动端 Rust 编为库（`libapp.a`/`.so`）嵌入 Xcode/Gradle 工程，经 `cargo-mobile2` 编排[^deepwiki-mobile]。2026 中现状：表单/阅读器/工具类可用，插件生态从 2025-01 的 ~47 个涨到 2026-04 的 120+；但插件覆盖、签名、webview 怪癖的坑比桌面多，「移动即产品」仍推荐 RN/Flutter，「桌面为主+移动赠品」选 Tauri 合理[^mayhemcode][^codercops]。

### pywebview

2025-08 发 6.0、2026-01 到 6.2.1，月下载 ~110 万，维护活跃[^pywebview6][^pyrank]。用法即「uvicorn 跑 daemon 线程 + `webview.create_window` 占主线程」（macOS 强制 GUI loop 在主线程），等端口就绪再开窗否则白屏；JS↔Python 有 `js_api` 桥可弹原生文件对话框（WebView2 不支持普通下载时必需）[^qso]。后端：Windows 用 EdgeChromium/WebView2（Win10/11 自带零依赖），macOS 用 WKWebView（经 pyobjc，PyInstaller 需 `--hidden-import objc,Foundation,AppKit,WebKit` + `--collect-all webview`），Linux 用 WebKitGTK[^amicoscript][^qso]。

**致命伤在 Linux**：WebKitGTK 经 PyGObject 来自系统包，PyInstaller 搬不进 bundle——Linux 构建只能退回浏览器 tab。AmicoScript 项目的实战文档明确记了两阶段路线：Phase 1 pywebview 过渡、Phase 2 Tauri sidecar 补 Linux 窗口 + 安装器 + updater[^amicoscript]。这条路线几乎可以直接照抄到 texlate。

缺什么：没有安装器/updater/tray/单实例/深链——打包签名全靠自己（PyInstaller + NSIS/hdiutil），菜单能力弱（6.0 起有窗口级菜单）。比 Tauri 省的是：零 Rust、零第二工具链、后端不用拆进程（uvicorn 就活在自己进程里，没有 sidecar 孤儿问题）。

小结：体积 = PyInstaller 产物本身（~15–30MB 级）｜成熟度 中高（6.x 活跃）｜适合度 **第一壳**——最小投入把「黑框终端+浏览器」升级成「一个窗口」。

### Flet（Flutter for Python）

2026-09-15 刚发 1.0（重写后的首个稳定版）：`flet build` 出六平台安装包，内嵌 CPython 3.12/3.13/3.14，桌面/移动/网页通吃；`flet pack` 是 PyInstaller 快捷路径[^flet-pub][^flet-1.0]。**对 texlate 不成立**：Flet 用 Flutter 渲染自己的控件树，不是 webview 壳——采用它等于把 SolidJS 前端推倒用 Python 重写。另注意 1.0 极新（发布仅数日），社区反馈稳定性仍在追，Android 冷启动有 10–13s 的实测报告（pre-1.0 数据）[^flet-1.0]。

### PySide6 / Qt for Python

正经原生桌面栈，但同样要重写 UI（或塞 QWebEngineView 当壳——等于自带 Chromium，体积比 Electron 好不了多少）。LGPL 对开源可用但动态链接/安装器合规要留意，商业授权另算；PyInstaller 打包 +40–80MB 级。对「已有 SPA 想套壳」的目标是绕路。

### Neutralino / Wails / Lorca

Neutralino 活跃但生态小，模式仍是「壳 + 自己 spawn 后端」，工具链/updater 不如 Tauri；Wails 是 Go 后端框架，不重写后端就退化成一个更重的 pywebview；Lorca 依赖本机 Chrome + CDP，基本停更。三者对 texlate 都没有比 pywebview/Tauri 多任何东西。

### 不套壳：local web app 形态（品类现状）

同品类（PDF 论文翻译）的真实分发现状，PDFMathTranslate-next（BabelDOC 官方参考实现）：**Windows 推 .exe zip 包、Linux 推 Docker、macOS 推 `uv tool install`**；其「GUI」是 Gradio WebUI——双击 exe 弹一个常驻终端，半分钟后自动开浏览器到 `localhost:7860`[^pdf2zh]。assets 分 with-assets/without-assets 两档发行版（字体模型预打包 vs 运行时下载），与 texlate 的 tectonic 托管下载思路一致。

更大参照系：Datasette Desktop 是 Electron + python-build-standalone + 首启建 venv `pip install`（为插件系统保留完整 Python；texlate 无插件需求，冻结二进制即可，不必学它背整个解释器）[^datasette]；JupyterLab Desktop 是 Electron + 内嵌 conda 环境[^jlab]。这俩说明「Electron 壳 + Python 环境」是上一代主流答案，代价就是 100MB+ 起步。

不套壳的真实体验缺陷：终端窗口常驻（普通用户看不懂也不敢关）、端口冲突时无引导、没有 dock icon/独立窗口、关浏览器 tab ≠ 停服务、tab 淹没在浏览器里。pdf2zh 能这么发是因为用户群容忍度高。

### 移动/平板「阅读器」形态

如果未来要的只是「读已翻译好的双语 PDF」而非本地跑整条管线：PWA 先行（manifest + service worker，Android/桌面可装，iOS 半残）[^ourcodeworld]；要进商店再上 Capacitor 套壳（Ionic 维护，web 代码复用 ~90%，iOS 过审需加原生增值功能——Apple 4.2 拒纯 webview 壳）[^reepa][^edana]。Tauri mobile 是「桌面已用 Tauri 则顺手」的选项，不值得为移动端单独引入。

## 对 texlate 的推荐路径

1. **现在（M1 分发面）**：`uv tool install texlate` / `uvx texlate web` 作为主渠道（pdf2zh 在 macOS 也是这条路），tectonic 托管下载已就位，零新工程。
2. **双击用户（可紧随）**：PyInstaller/pyapp 冻结 `texlate`（CLI + `web` 自动开浏览器），出 Windows zip / macOS dmg / Linux 单文件——与 pdf2zh.exe 同形态，前端零改动。
3. **想要「像 app」（M2 候选）**：同一个冻结二进制里加 pywebview 窗口模式（Win/macOS 原生窗口，Linux 自动退浏览器）；AmicoScript 的 desktop-shell.md 是可照抄的工程文档。
4. **需要真 app 体验（M3+ 再议）**：Tauri 2 sidecar 套同一个 PyInstaller 产物，拿安装器/updater/tray/单实例/移动端通道；SPA 原样复用。届时先验 pdfslick 在 WebKitGTK 的渲染。
5. **移动阅读器**：PWA → Capacitor/Tauri mobile，按需再说。

Electron 维持 2026-09-18 裁决不做——Tauri/pywebview 能以 1/10 体积拿到同样的「SPA 套壳」结果，Electron 对这个项目没有增量价值。

## 参考文献

[^tauri-sidecar]: Tauri 官方文档. Embedding External Binaries (sidecar). [v2.tauri.app](https://v2.tauri.app/develop/sidecar/)
[^tauri-template]: dieharders/goofyrao. example-tauri-v2-python-server-sidecar / template-tauri-v2-python. [github.com](https://github.com/goofyrao/template-tauri-v2-python)
[^voicebox]: jamiepine/voicebox. docs/developer/building.mdx — PyInstaller FastAPI sidecar + Tauri 两阶段构建. [github.com](https://github.com/jamiepine/voicebox/blob/main/docs/content/docs/developer/building.mdx)
[^woyable]: Woyable. Tauri vs Electron 2026: Size, RAM, Security Compared. [woyable.com](https://woyable.com/en/posts/tauri-vs-electron-2026)
[^openreplay]: OpenReplay. Comparing Electron and Tauri for Desktop Applications. [blog.openreplay.com](https://blog.openreplay.com/comparing-electron-tauri-desktop-applications/)
[^regaya]: Alan Regaya. Tauri vs Electron: What I Learned Shipping a Desktop App in Both. [alanregaya.dev](https://alanregaya.dev/blog/tauri-vs-electron-lessons)
[^amicoscript]: AmicoScript. docs/desktop-shell.md — pywebview 现状 + Tauri sidecar 规划、Linux WebKitGTK 不可打包、签名独立付费线. [github.com](https://github.com/sim186/AmicoScript/blob/main/docs/desktop-shell.md)
[^deepwiki-mobile]: DeepWiki. Mobile Platform Support — tauri-apps/tauri. [deepwiki.com](https://deepwiki.com/tauri-apps/tauri/8-mobile-platform-support)
[^mayhemcode]: MayhemCode. Build Mobile and Desktop Apps From One Codebase | Tauri 2 (2026-07). [mayhemcode.com](https://www.mayhemcode.com/2026/07/build-mobile-and-desktop-apps-from-one.html)
[^codercops]: CODERCOPS. Tauri 2.0: Desktop and Mobile Without the Bloat. [blog.codercops.com](https://blog.codercops.com/blog/tauri-2-desktop-mobile-apps-rust-web-2026)
[^pywebview6]: r0x0r/pywebview. 6.0 release notes + blog. [github.com](https://github.com/r0x0r/pywebview/releases/tag/6.0)
[^pyrank]: PyRank. pywebview 包数据（下载量/发版节奏）. [pyrank.org](https://pyrank.org/package/pywebview/)
[^qso]: QSOCapture. launcher.py — uvicorn daemon 线程 + pywebview edgechromium 窗口 + PyInstaller 冻结实战. [github.com](https://github.com/sq3rx/QSOCapture/blob/refs/heads/main/launcher.py)
[^flet-pub]: Flet 官方文档. Publishing a Flet app. [flet.dev](https://flet.dev/docs/publish/)
[^flet-1.0]: RuntimeWire. Flet 1.0 ships Python apps across six platforms after a ground-up rewrite (2026-09-17). [runtimewire.com](https://runtimewire.com/article/flet-1-0-python-cross-platform-apps-feodor-fitsner)
[^pdf2zh]: PDFMathTranslate-next. README + Windows 安装文档 + v2.6.0 release notes. [github.com](https://github.com/PDFMathTranslate/PDFMathTranslate-next)
[^datasette]: Simon Willison. Datasette Desktop—a macOS desktop application for Datasette (2021). [simonwillison.net](https://simonwillison.net/2021/Sep/8/datasette-desktop/)
[^jlab]: jupyterlab/jupyterlab-desktop. [github.com](https://github.com/jupyterlab/jupyterlab-desktop)
[^ourcodeworld]: Our Code World. PWA vs Capacitor vs Native: Choosing an App Architecture in 2026. [ourcodeworld.com](https://ourcodeworld.com/articles/read/3646/pwa-vs-capacitor-vs-native-2026)
[^reepa]: Reepa Solutions. Progressive Web Apps vs Native — When a PWA Is Enough and When It Isn't 2026. [reepasolutions.de](https://reepasolutions.de/en/software-development/progressive-web-apps-vs-native)
[^edana]: Edana. Should You Still Choose Capacitor Today? (2025-07). [edana.ch](https://edana.ch/en/2025/07/31/should-you-still-choose-capacitor-today-for-which-types-of-mobile-projects-does-it-remain-relevant/)
