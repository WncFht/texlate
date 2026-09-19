# 技术栈评估与分发路线实施细节（2026-09-19）

姊妹篇：[README](README.md)（结论）、[python-binary.md](python-binary.md)、[app-shell.md](app-shell.md)、[competitors-and-latex.md](competitors-and-latex.md)、[zotero-plugin.md](zotero-plugin.md)。本文回答两个问题：技术栈该不该留在 Python；每条路线具体怎么做。

## 一、要不要换语言

**结论：核心留 Python，不为"单二进制"重写；壳层和热路径按需用 Rust/TS，这本来就是现状（SPA 是 TS、Tauri 壳是 Rust）。**

### Python 不是实际瓶颈

逐条对号 Python 的"经典罪状"：

- **性能**：工作负载是 I/O 密集型——LLM 请求（实测 2.9s 固定 + 13.3ms/out_tok）、tectonic 编译子进程（秒到分钟级）、arXiv 下载。Python 解释器开销占总时延 <1%；CPU 段（segmenter/fixloop）是单文档毫秒-秒级短任务。换 Rust 加速一个不占时延的环节没有收益。
- **并发/GIL**：`texlate web` 是单用户本地实例，uvicorn+asyncio 足够；多租户场景 TEXLATE_MODE=server 也是 I/O 型。
- **打包/分发**：冻结二进制 + tectonic sidecar 已把分发问题解决在语言层之下——而且运行时本来就要下载 tectonic/biber/字体，**永远不是纯自足单文件**，Rust/Go 的单二进制优势被这层"托管下载"架构抵消。
- **类型/重构安全**：`ruff select=ALL` 严格集 + 类型标注已在扛，bench 断言矩阵护住语义。

### 重写的真实代价

- 领域知识沉淀在代码里：gullet/segmenter 半解析+展开机（corpus_v3 identity 100%/leak 0.040% 是几百篇语料喂出来的断言）、fixloop 规则库（数百条逐案攒的修复规则）、cjkmap/GB1 cmap 资产、validate 三层。这不是"翻译一遍代码"，是把 M0–M3 的实证过程重跑一遍。
- 生态面：arXiv API/robots 礼节、PDF 检查（pypdf）、EPUB/DOCX（python-docx）、tree-sitter node 校验件——Rust/Go 在这些领域生态明显薄。docs/01 当时就裁决过 Go/Rust："LaTeX/文档生态为零，tectonic sidecar 已解决分发瓶颈，不划算"——结论今天仍成立，且论据更强了。
- 时机：M2/M3 演进期规则库和修复回路在快速生长，迭代速度比运行时效率值钱。同类项目（BabelDOC/PDFMT、texglot、hjfy）全部是 Python，不是巧合。

### 什么时候重新评估

出现以下任一信号再说：要做纯 WASM/边缘部署形态；segmenter 成实测热点且 Cython/Rust extension 不够；要进 App Store 做真正原生移动应用。届时也是"热路径换件"而非整体重写。

## 二、Route 0 — PyPI + uvx（基线，先做）

`uvx --from 'texlate[server]' texlate web` 今天就该能用，它是所有上层形态的地基（Zotero 插件引导用户装 texlate 也是这条路）。

1. **发布面**：`uv build` 出 wheel+sdist（hatch artifacts 已把 SPA 强制入 wheel）；GitHub release workflow 走 PyPI trusted publishing（OIDC，免 token）；tag 即发布。
2. **README 安装段**：`uv tool install 'texlate[server]'`（持久）与 `uvx --from 'texlate[server]' texlate web`（一次性）两条并列；附 pipx 等价命令。
3. **补一个 UX 缺口**：`cli.py` 的 `web` 目前只在"实例已运行"时 `webbrowser.open`（cli.py:811），首次启动不自动开浏览器——加 `--open/--no-open`（local 形态默认开），这是 Route 1 双击体验的前置。
4. **`texlate doctor` 核验项**：确认覆盖 tectonic 可达性、网关连通、数据目录可写——冻结包用户排障全靠它。
5. **渠道铺面**：homebrew 自 tap（一个 git repo + formula，零门槛）；Scoop 自桶；AUR 留社区。homebrew-core 先不急（notability 门槛 + 运行时拉二进制的政策风险）。
6. **API 文档**：`POST /api/arxiv/{id}/translate`、`GET /api/task/{id}`、`GET /api/files/{id}/{kind}`、`POST /api/upload`、`GET /api/health`、server 模式 `X-Texlate-Key`——写一页 `docs/api.md`，Zotero 插件和瘦客户端生态都吃它。

## 三、Route 1 — 冻结二进制（Windows 双击党）

目标形态：zip 解压 → 双击 `texlate.exe` → 起服务 + 自动开浏览器，pdf2zh.exe 同款。只做 Windows（macOS/Linux 由 Route 0 覆盖，pdf2zh 也是这个分工）。

三条技术路，推荐顺序：

### 方案 A：PyStand 目录打包（pdf2zh 实测路线，推荐先试）

照 `PDFMathTranslate-next/.github/workflows/exe-build.yml` 的方子：

```
build/
  runtime/          ← python-3.13.x-embed-amd64.zip 解压
  site-packages/    ← uv pip install 'texlate[server]' 的产出
  texlate.exe       ← PyStand.exe 改名
  texlate.int       ← 入口：import texlate.cli; app() 或直起 web
  tools/            ← 预置 tectonic + tectonic-biber（可选）
```

优点：无 bootloader → AV 误报面最小；文件即所见，排障直接；CI 全是 shell 操作无新工具链。缺点：交付物是目录（zip 分发可接受）；无自更新（加一个查 PyPI JSON API 的 `--check-update` 提示即可）。

### 方案 B：PyApp / box（理念最同构）

几 MB Rust stub，首跑自举 python-build-standalone + 项目依赖到用户缓存；自带 `self update/self remove`；Hatch 原生 `hatch build --target app`。与 texlate 的"tectonic 托管下载"是同一哲学：二进制不必自足，缺什么首跑拉。已有作 Tauri sidecar 的实战先例（Montelimar）。缺点：CI 引入 Rust；首跑要网（反正也要拉 tectonic）；项目小名气边角自扛。

### 方案 C：PyInstaller onedir（生态保底）

texglot 模式照搬：`--onedir --collect-submodules uvicorn --collect-data certifi --add-data static:static --add-binary tectonic:tools`。**只出 onedir**：onefile 有 3–10s 解压启动罚、bootloader 双层进程让外层杀不到子进程、误报最高。误报还想降就从源码自编 bootloader（实测 VirusTotal 4–19/71 → 1/71）。

### 共同要件（不论选哪条）

- `tectonic-biber` 钉版同捆：tectonic ≥PR#1166 优先调 `tectonic-biber`，把匹配 bundle 代际的 biber 改名塞进 `tools/`——顺带根治现有 biblatex 错配坑。
- 单实例已有（service.lock flock）；数据目录 `~/.texlate` 不变，zip 删了重来零残留。
- 先不签名：SmartScreen 警告随下载量消退；要做时走 SignPath Foundation OSS 免费通道。
- CI：windows-latest runner 跑打包脚本 + 冒烟（起 web → `/api/health` 200 → 关）。
- `texlate web --open` 让双击即见浏览器（依赖 Route 0 第 3 条）。

## 四、Route 2 — pywebview 窗口（"像个 app"的最小投入）

在 Route 1 同一个二进制里加 `--app` 模式，不新增打包线：

```
uvicorn 起 daemon 线程 → 轮询 /api/health 200 → webview.create_window(url)
窗口关闭 → 调关停钩 → 退出
```

- Windows 用 EdgeChromium/WebView2（Win10/11 自带）；macOS 走 pyobjc/WKWebView（PyInstaller 需 `--hidden-import objc,Foundation,AppKit,WebKit --collect-all webview`）。
- **Linux 硬伤**：WebKitGTK 依赖 PyGObject 系统包，PyInstaller/PyStand 打不进包——检测到无 WebKitGTK 时自动退 `webbrowser.open`，行为与 Route 1 一致。
- 工程量 ~200–400 行 + `pywebview` optional extra；换来"一个独立窗口、一个 dock 图标、关窗即停"——这就是普通用户感知的"app 与否"分界线。
- 明确不做：托盘、菜单、安装器、自更新——那些是 Route 3 的存在意义，这里做了反而高不成低不就。

## 五、Route 3 — Tauri 2 sidecar（真 app 形态，M3+ 再议）

需要安装器/updater/托盘/单实例/深链时上。两阶段构建：PyInstaller/pyapp 出 `texlate-server-<target-triple>` → 拷入 `src-tauri/binaries/` → `tauri build` 出 dmg/msi/AppImage。

关键手术（texglot Electron 手术单的 Tauri 版）：

- `bundle.externalBin` 声明 + 文件命名 `-<triple>` 后缀；spawn 走 `tauri_plugin_shell`，`capabilities/*.json` 逐条授权。
- **关停协议**：外层只能拿到 launcher pid，杀不到真服务——给 server 加 `POST /api/shutdown`（仅回环可达 + Host 闸复用现有防 DNS rebinding）或抄 texglot 的 stdin-EOF watchdog。孤儿进程占端口是该模式第一大故障面，先做它。
- SPA 零改动：webview 直接 `window.url = http://127.0.0.1:<port>`（不起自定义协议），SSE/fetch/下载全走原生 web 语义；端口 bind 0 取空口传入壳。
- updater 是 ed25519 密钥对体系，与代码签名独立；单实例/托盘有官方 plugin。
- **验证先行**：pdfslick 在 WKWebView(macOS)/WebKitGTK(Linux) 的渲染、pdf worker、下载导出——WebKitGTK CSS 落后数月，这条不过 Route 3 不启动。
- 签名照付：macOS $99/年（壳+sidecar 同签）+ Windows 证书线；Tauri 不省这笔钱。

体积对比账：壳 ~8–12MB + Python sidecar ~50–100MB（PyStand/onedir 形态）——vs texglot Electron 路线 ~190MB+。同结果 1/3–1/2 体积。

## 六、Route 4 — 阅读器/移动（远期）

- 最省路径：SPA 已是阅读器 → 加 PWA manifest + service worker（缓存已下载任务产物），桌面/Android 浏览器即得"可安装 app"；iOS PWA 半残（推送/存储配额受限）。
- 要进商店再 Capacitor 套壳连远程实例（Ionic 维护，web 代码 ~90% 复用；iOS 过审需原生增值功能，纯 webview 壳会被 4.2 拒）。
- 前提都已在：`TEXLATE_MODE=server` + `X-Texlate-Key` 鉴权就位 → "用户自建实例 + 手机阅读"零新后端开发。
- Tauri mobile 不值得为它单独引入——桌面用了 Tauri 才顺手。

## 七、旁路：托管实例 + 瘦客户端（已存在，别漏）

`run --server` 瘦客户端 + server 模式鉴权已就位，意味着"团队/实验室自建 texlate 实例"今天零新开发就成立：leader 机器跑 `TEXLATE_MODE=server texlate web --host 0.0.0.0`，成员 `texlate run --server http://host:8765`。这条与所有本地分发形态正交，README 里值得专门一节。公共托管（hjfy 对标）是产品决策——要配额/计费/队列隔离，不在技术栈讨论范围。
