# 分发形态调研：二进制 / client / app（2026-09-19）

问题：texlate 适不适合做成二进制分发？更进一步做成 client/app 选什么技术栈？分题调研见同目录：[`python-binary.md`](python-binary.md)（Python→二进制方案与渠道）、[`app-shell.md`](app-shell.md)（桌面壳技术栈）、[`competitors-and-latex.md`](competitors-and-latex.md)（竞品形态 + LaTeX 捆绑事实）、[`routes.md`](routes.md)（语言选型 + 各路线实施细节）、[`zotero-plugin.md`](zotero-plugin.md)（Zotero 插件生态面）、[`zotero-design.md`](zotero-design.md)（**插件设计方案——实施按此执行**）、[`pdf2zh-read.md`](pdf2zh-read.md)（6.6k★ 标杆源码深读）、[`pdf-translate-read.md`](pdf-translate-read.md)（11.8k★ 工程模式深读）、[`zotero-dev-prompt.md`](zotero-dev-prompt.md)（插件开发工单 prompt：verifier 先行 + 三性质验收 + skeleton 留档）。`tmp/refs/` 下有 zotero-pdf2zh/zotero-plugin-hjfy/zotero-pdf-translate/zotero-plugin-template 四个 clone（全 AGPL/MIT，只抄模式）。

## 仓库侧既有事实

- `compile/toolchain.py` 已实现 tectonic 五平台 sha256 钉死 + 自动下载 `~/.texlate/tools`——LaTeX 依赖这个最大分发障碍已经解决，且与业界做法同构（GlyphX/Scribe 把 tectonic 当 sidecar 随安装器分发，Quarto `quarto install tinytex` 同款托管下载模式）。
- `texlate web` 起 FastAPI 伺服已构建 SPA（hatch `artifacts` 强制入 wheel），`run --server` 已有瘦客户端模式——client/server 分离在架构上已存在。
- `docs/research/latex/texglot-patterns.md` 已拆解过活体先例 texglot 的 PyInstaller onedir + Electron + tectonic sidecar 打包手术；`docs/03-roadmap.md:48` 把「BYOK 桌面版」挂 M4+；2026-09-18 裁决 Electron M1 不做。

## 核心结论

**适合做，分层推进，别跳级。** 竞品调研给出赛道定形：hjfy.top 与沉浸式翻译 BabelDOC 是纯 SaaS，PDFMathTranslate-next 是唯一自部署壳——「本地起 web 服务 + 自动开浏览器」就是本赛道既定的 app 形态，没有一家拿原生桌面 app 当主形态。texlate 的 BYOK+本地跑相对 hjfy SaaS 本来就是差异化，本地分发形态强化它。

### 推荐路径（按投入递增）

| 档 | 形态 | 覆盖用户 | 成本 |
| --- | --- | --- | --- |
| 0 | PyPI + `uvx texlate web` / `uv tool install` | 肯敲一条命令的人；pdf2zh 在 macOS 就走这条 | ≈0（发版即得） |
| 1 | 冻结二进制 + `web` 自开浏览器（pdf2zh.exe 同形态） | Windows 双击用户（学术用户主力） | 中：CI 三平台矩阵 |
| 2 | 同一二进制 + pywebview 窗口 | 要「像个 app」的 Win/mac 用户；Linux 退浏览器 | 低-中：无第二工具链 |
| 3 | Tauri 2 sidecar 套壳 | 要安装器/updater/tray/单实例/移动端时 | 高：Rust+Node 双工具链 + 签名照付 |
| 4 | 移动阅读器：PWA → Capacitor | 只读已译结果 | 按需 |

第 1 档技术选型：**PyStand 目录打包**（pdf2zh 实测路线，embeddable runtime + site-packages 拷贝，无 bootloader 故几乎无 AV 误报）与 **PyApp/box**（几 MB stub 首跑自举，与 texlate 托管下载哲学同构，hatch `hatch build --target app` 原生集成）二选一；PyInstaller onedir 保底（onefile 有启动罚与误报，自编 bootloader 可大幅降误报）。Nuitka 对 LLM-bound 负载无收益；PyOxidizer 实质停维勿入。

第 3 档注意（如果走到）：Tauri ~14MB vs Electron ~190MB 安装包、内存 ~1/3，texglot 的 Electron 答案不必抄——Tauri sidecar 能以 1/10 体积拿同样结果，与昨日「Electron 不做」裁决方向一致。坑：PyInstaller onefile 产物有双层进程杀不干净（用 onedir 或自己实现关停协议）；pdfslick 在 Linux WebKitGTK 的渲染需真机先验；签名税费一项不少。

### LaTeX 捆绑结论

不构成障碍。tectonic 首跑按需逐文件拉 bundle（非整包 2.8GB），`--only-cached` + 预热缓存可半离线；翻译流程本身要联网调 LLM，首跑联网可接受。**唯一真坑是 biber**：tectonic 不内置，biblatex↔biber 版本错配是慢病（texlate 已踩过 3.17↔2.22）——上游 PR #1166 已让 tectonic 优先调用名为 `tectonic-biber` 的组件，**钉版 biber 改名 `tectonic-biber` 随包分发即可根治**，二进制分发时应直接采纳，顺手消掉现有 bug。

### 签名税费（绕不开，可延后）

Windows：SignPath Foundation 给合格 OSS 免费签名流水线，或 Azure Artifact Signing $9.99/月；macOS：.app 分发需 Apple Developer $99/年签名+公证，CLI 渠道未签名代价可承受（quarantine xattr 只管浏览器下载）。未签名 SmartScreen 警告随信誉积累消退，pdf2zh 长期未签名照常发。

### 顺路洞察

- Zotero 插件是本赛道标准触手（hjfy/BabelDOC/PDFMT 三家都有官方或第三方），texlate 开放 API 后值得做，成本极低。
- `run --server` 瘦客户端 + BYOK 意味着「托管实例 + 瘦客户端」商业模式天然可行（用户自建 server 给团队用），无需为 client 单独开发。
- Astral 未收编 PyOxidizer 但接管 python-build-standalone，方向是「uv 管解释器」而非静态打包——PyApp 路线押注方向与上游一致，将来 uv 官方化类似能力时不吃亏。
