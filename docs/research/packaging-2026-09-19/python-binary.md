# Python 应用二进制分发调研（2026-09-19）

调研范围：把 uv 管理的 Python 3.12 CLI/web 应用（texlate）分发给非 Python 用户的可行路径。事实核验时点 2026-09；同类调研见同目录姊妹篇。

## 结论速览

零打包渠道（`uvx` / `uv tool install` + PyPI）已是 2026 年 Python CLI 的一等分发方式，应做基线；单文件二进制里 **PyApp/box**（运行时自举）最贴合本项目「托管下载」哲学，**PyInstaller** 仍是生态默认但 Windows 杀软误报与 onefile 启动惩罚是真实代价；**Nuitka** 误报更少但构建重、对 LLM-bound 工作负载无性能收益；**PyOxidizer** 实质停维，勿入；要出 .msi/.dmg 原生安装器时 **Briefcase** 是活跃选项。签名税费绕不开：Windows 侧 OSS 可走 SignPath Foundation 免费或 Azure Artifact Signing $9.99/月，macOS 侧 Apple Developer $99/年。

## 1. 单文件/安装器打包方案

### PyInstaller

生态默认，v6.22.2（2026-08-17），迭代节奏约每月一版[^pyi-changelog]。打包而非编译：字节码 + 解释器进 bundle，bootloader 运行期解压。Windows 杀软误报仍是结构性问题——bootloader 二进制签名被 AV 指纹化（与海量恶意样本同源），UPX 压缩与 onefile 的临时目录解压行为各加一分嫌疑；实测把 bootloader 从源码自编后 VirusTotal 从 4–19/71 降到 1/71[^synvan]。onefile 每次启动需解压到临时目录，体积大时启动慢 3–10s；onedir 无此罚但交付物是一目录[^mitmproxy-install]。三平台产物不可交叉编译，须各平台 CI runner 分别构建[^codegym]。

- 体积：CLI 级应用 onefile 约 15–30 MB（纯 Python 依赖），重依赖项目可到数百 MB[^devto-nuitka]。
- 成熟度：最高，hooks 生态最全；uv 项目无特殊兼容问题（它只认 import 图）。
- 坑：AV 误报、onefile 启动罚、Apple Silicon 需至少 adhoc 签名、要 matrix CI。

### Nuitka

真编译路线：Python → C → 机器码，standalone/onefile 均可。主流对比报告称 AV 误报「显著更少」且 CPU 密集代码快 10–30%[^devto-nuitka][^beatsync]；但也有实测显示 Nuitka onefile 在 VirusTotal 反而更高（19/71 vs PyInstaller 4/71）——onefile 模式的解压行为同样触启发式，onedir 则干净[^synvan]。构建慢（中型项目 5–15min+）、需各平台 C 工具链；对 `exec`/动态特性有边角。结论：误报优势在 onedir 形态成立，onefile 形态未必比自编 bootloader 的 PyInstaller 强。

- 体积：单文件 25–50 MB 起[^devto-nuitka]。
- 成熟度：高，商业支持存在；生产用户群真实。
- 坑：构建时间、C 工具链矩阵、动态 import 边角、onefile 并未豁免 AV。

### PyApp（+ box）

Ofek Lev（Hatch 作者）的 Rust 启动器：编译出几 MB 的 stub 二进制，首跑时抓 python-build-standalone 解释器 + 用 uv/pip 装项目到用户缓存目录，后续秒启；可选把解释器与项目全嵌进二进制换免网首启；自带 `self update/self remove` 管理子命令[^pyapp][^pydevtools-ship]。Hatch 有 `hatch build --target app` 插件直接产物[^hatch-binary]。`box`（box-packager）是更薄的封装，`uvx --from box-packager box package` 一条命令出产物[^guybrush]。已有实战先例：Montelimar 项目用 box 打包 FastAPI 服务作 Tauri sidecar[^guybrush]。仓库 ~2k stars，2026-03 仍有提交，活跃。

- 体积：默认几 MB（运行时拉取），全嵌模式与 PyInstaller onefile 同级。
- 成熟度：中——个人项目但设计干净、有 Hatch 官方集成与真实生产用例。
- 坑：默认模式首跑要网（texlate 反正首跑也要下 tectonic，同构）；Rust 工具链入 CI；名气小意味着边角自己扛。

### BeeWare Briefcase

打包成**原生安装器**而非单文件：Windows MSI/ZIP（WiX）、macOS DMG/.app/PKG、Linux system package/AppImage/Flatpak，另有 iOS/Android/Web 目标[^briefcase-faq]。项目非常活跃：2025-11 加了 MSI 安装目录定制与 pre-uninstall 选项，2026-04 已支持 Windows ARM64 原生构建[^beeware-nov][^beeware-apr]。Windows 侧用官方 embeddable Python 包（注意缺 tkinter 等模块）[^briefcase-win]。

- 体积：安装器含完整 Python 运行时，几十 MB 级。
- 成熟度：高，基金会化运营、月度 status update。
- 坑：心智模型是「GUI app 安装包」，CLI+本地 web 服务用它产出的东西形态略别扭（装完还是得开终端或给你包个壳）；Apache/MIT 项目无授权问题。

### PyOxidizer（实质停维，勿入）

末版 0.24.0（2022-12），主仓最后提交 2024-12；社区 fork（ntamas）卡在 musl/PyO3 版本错配无发布，PyO3 组织讨论过收留未落地[^pyoxidizer-751]。Astral 2024-12 起接管的是其底层 **python-build-standalone** 发行版（供 uv/PyApp 等用），明确不接管 PyOxidizer 本体[^astral-pbs]。理念最好（真静态单文件、不解压），但无维护 = 不评估。

### cx_Freeze / shiv / pex

cx_Freeze：bundle 路线的老选项，仍在维护但社区与文档都薄，仅在 PyInstaller hooks 失灵时作备胎。shiv/pex：zipapp/pex 文件**不是免 Python 方案**——目标机仍须有解释器；pex 活跃（v2.100.4，2026-08）[^pex]但定位是部署件不是终端用户分发件，shiv 更新慢。对「非 Python 用户」场景直接出局。

## 2. 不打二进制的渠道

### uv tool install / uvx（基线渠道）

`uvx texlate web` 即跑：临时 venv 装包、跑完缓存复用；`uv tool install` 落 PATH 持久化[^uv-tools]。uv 自身是单静态二进制，curl/brew/pip/winget 均可装，且**自带 Python 版本管理**（`uvx --python 3.12` 没有解释器也拉得到）[^linuxize-uv]。2025-2026 业界共识：对能跑一条命令的用户，`uvx` 就是正当的一等分发渠道而非「开发者捷径」[^pydevtools-ship]。texlate 已是 uv 原生项目，此渠道边际成本≈发 PyPI。

### pipx

仍在维护、仍是 Debian/Ubuntu 系绕 `externally-managed-environment` 的正经路径；功能面被 uv 基本覆盖（uvx 更快、自带解释器管理），仅余 `pipx inject`/`--global` 等少量独门特性[^pydevtools-uvx]。值得在 README 并列给出，不值得单独工程化。

### Homebrew

两条路：**自 tap** 零门槛（一个放 formula 的 git repo，`brew install owner/tap/texlate`），随时可做；**homebrew-core** 有硬性 notability 门槛——30 forks/30 watchers/75 stars，仓库 owner 自提则 90/90/225，仓库须 >30 天，formula 必须从源码构建（Python 应用走 virtualenv DSL 合规），自更新行为必须可禁用[^brew-policy]。注意：texlate 的运行时 tectonic 托管下载在 formula 语义下属于「运行时拉取二进制」，homebrew-core 对运行时安装专有软件有禁令风险，自 tap 无此问题；亦可走 cask（binary-only 软件归 cask）。

### Scoop / winget（Windows）

winget 社区仓 `microsoft/winget-pkgs` 免费提交 manifest（`wingetcreate` 工具链），需要稳定的 release asset URL；是 Windows 上唯一「官方感」渠道。Scoop 侧自建 bucket 就是一个 git repo + JSON manifest，零门槛，先自桶后求收录 extras/main 均可。两者都只包你发布的二进制/zip，不负责帮你构建。

### Linux：AUR / Flatpak / Snap / AppImage

AUR 打 PKGBUILD 装 pip 包即可（Arch 用户自己动手成本低）；AppImage 一条路径是把 python-build-standalone + venv 塞目录压 AppImage（Briefcase 有现成 Flatpak/AppImage 目标[^briefcase-faq]）；Snap/Flathub 商店流程重、沙箱内跑 LaTeX 编译子进程有额外适配成本，优先级最低。

## 3. 同类工具实操

- **yt-dlp**：CI 每平台 PyInstaller 构建（Windows x64/x86/ARM64、macOS universal2——自融合 universal2 wheel 的重工程、Linux 走 manylinux2014 docker + musllinux 双变体），同时发 zipimport 跨平台 Unix 单文件、PyPI、homebrew-core、自有 `-U` 自更新[^ytdlp-build][^ytdlp-install]。教科书级「全渠道」但工程量也大。
- **mitmproxy**：PyInstaller standalone spec（Win/Linux 单文件 zip）+ onedir spec 供 macOS .app 与 Windows InstallBuilder 安装器；brew cask 收录；文档明说 onefile 版「启动显著更慢」推荐安装器[^mitmproxy-install][^mitmproxy-build]。
- **Astral（ruff/uv）**：Rust 单静态二进制，standalone installer 脚本 + brew + pipx + winget 全渠道——证明「单文件 + 多渠道」路线在 Python 工具圈的天花板[^linuxize-uv]。
- **datasette/llm（simonw 系）**：纯 PyPI + `uvx`/`pipx` 指南，不做二进制；cli 工具受众为开发者时这就是完整答案。

## 4. 签名与平台税费

### Windows

Azure Artifact Signing（原 Trusted Signing）：Basic $9.99/月 5000 次签名，Premium $99.99/月 10 万次；个人开发者目前仅美国/加拿大可开，组织限美加英欧[^ms-codesign][^azure-pricing]。证书 3 天短效、CI 集成成熟（`azure/trusted-signing-action`），**必须时间戳**否则签名随证书一起过期[^hanselman]。**开源免费路**：SignPath Foundation 给合格 OSS 项目提供 OV 级签名流水线[^ms-codesign]。无论签不签，SmartScreen 信誉都要时间累积——签名给基础信誉但首版仍可能弹警告[^ms-codesign][^hanselman]。

### macOS

未签名 .app 触发 Gatekeeper「unidentified developer」拦截，需右键打开或用户手动放行的时代仍在；分发需 Apple Developer $99/年做签名+notarization（公证 2024 后流程已自动化程度高）。纯 CLI 二进制经 curl/包管理器下载不落 quarantine xattr，浏览器下载的未签名 arm64 原生二进制则会被拦——所以「不签名」对 CLI 渠道是可承受的，对 .app 渠道不可承受。

## 5. 展望：Astral 原生方案

社区多次提议 uv 官方做 `uv bundle`/`uv build --release`（issue #5802）、`uv layout` 离线发行目录（#11746）、「uv 改名即工具」自举模式（#10465）；Astral 明确说不拥有 PyOxidizer、这些提议截至 2026-09 均为开放 issue 未落地[^uv-5802][^uv-10465]。押注方向是「uv 解决解释器与依赖」而非「静态打包」，与 PyApp 哲学一致——意味着 PyApp/box 路线就算 uv 日后入场也不亏（届时大概率是同一思路的官方化）。

## 6. 对 texlate 的适用性点评

texlate 的特殊性：运行时本来就有一张「托管下载」网（tectonic 五平台 sha256 钉死自动装、可选 node 子进程），所以「二进制不完全自足」不是减分项而是既定架构。分三档看：第一档 `uv tool install texlate[server]` + PyPI，今天就能做，覆盖所有愿意敲一条命令的用户，是必做基线；第二档单文件二进制，**PyApp/box 与项目哲学最同构**（stub 小、首跑拉解释器与依赖、self update 现成、Hatch 原生集成 `hatch build --target app`），PyInstaller 作为生态保底但要有处理 AV 误报与 onefile 启动罚的心理准备；第三档原生安装器（Briefcase MSI/DMG 或 InstallBuilder）只有在做 GUI 壳时才值得，纯 CLI+本地 web 形态下安装器相对单文件没有净收益。签名预算：起步期 Windows 走 SignPath Foundation 免费申请、macOS 先不发 .app 就不交 $99——CLI 渠道两平台的「未签名」代价都可承受。

### 参考文献

[^pyi-changelog]: PyInstaller Changelog. pyinstaller.org, 2026. [CHANGES](https://pyinstaller.org/en/stable/CHANGES.html)
[^synvan]: Synvan. Python ➝ Exe with Minimal False Positives. synvan.com, 2025. [link](https://synvan.com/posts/python-to-exe/)
[^beatsync]: RendereelStudio. Nuitka vs PyInstaller: Complete Comparison 2026. [link](https://beatsyncpro.ai/blog/nuitka-vs-pyinstaller.html)
[^devto-nuitka]: weisshufer. From PyInstaller to Nuitka: Convert Python to EXE Without False Positives. dev.to, 2025. [link](https://dev.to/weisshufer/from-pyinstaller-to-nuitka-convert-python-to-exe-without-false-positives-19jf)
[^codegym]: CodeGym. Turn a Python Script Into an .exe: PyInstaller, Nuitka, BeeWare, PyOxidizer, and the Antivirus Reality. [link](https://codegym.cc/groups/posts/python-script-to-exe)
[^pyapp]: ofek. pyapp — Runtime installer for Python applications. GitHub. [link](https://github.com/ofek/pyapp)
[^pydevtools-ship]: pydevtools. How do I ship a Python application to end users? [link](https://pydevtools.com/handbook/explanation/how-do-i-ship-a-python-application-to-end-users/)
[^hatch-binary]: Hatch. Binary builder (PyApp). hatch.pypa.io. [link](https://hatch.pypa.io/dev/plugins/builder/binary/)
[^guybrush]: guybrush.ink. Bundling Python apps with box/PyApp, incl. Tauri sidecar precedent. 2025-05. [link](https://guybrush.ink/writings/2025-05-18-bundling-python)
[^briefcase-faq]: BeeWare. Briefcase FAQ — supported platforms. [link](https://briefcase.beeware.org/en/stable/about/faq/)
[^beeware-nov]: BeeWare. November 2025 Status Update. [link](https://beeware.org/cs/news/buzz/2025/november-2025-status-update/)
[^beeware-apr]: BeeWare. April 2026 Status Update. [link](https://beeware.org/news/buzz/2026/april-2026-status-update/)
[^briefcase-win]: BeeWare. Briefcase Windows platform reference. [link](https://briefcase.beeware.org/en/latest/reference/platforms/windows/)
[^pyoxidizer-751]: jaraco et al. Maintenance support (offer) — PyOxidizer issue #751. GitHub, 2024-2026. [link](https://github.com/indygreg/PyOxidizer/issues/751)
[^astral-pbs]: Astral. A new home for python-build-standalone. astral.sh blog, 2024-12. [link](https://astral.sh/blog/python-build-standalone)
[^pex]: SkillFed. pex package index entry (v2.100.4, 2026-08). [link](https://skillfed.io/packages/pex)
[^uv-tools]: Astral. uv docs — Tools. docs.astral.sh. [link](https://docs.astral.sh/uv/concepts/tools/)
[^pydevtools-uvx]: pydevtools. uvx: Run Python CLI Tools in Isolated Environments. [link](https://pydevtools.com/handbook/reference/uvx/)
[^linuxize-uv]: Linuxize. How to Install and Use uv. [link](https://linuxize.com/post/how-to-install-and-use-uv/)
[^brew-policy]: Homebrew. Package Acceptance Policy (notability thresholds). docs.brew.sh. [link](https://docs.brew.sh/Package-Acceptance-Policy)
[^ytdlp-build]: yt-dlp. .github/workflows/build.yml. GitHub. [link](https://github.com/yt-dlp/yt-dlp/blob/HEAD/.github/workflows/build.yml)
[^ytdlp-install]: yt-dlp wiki. Installation.md. GitHub. [link](https://github.com/yt-dlp/yt-dlp-wiki/blob/master/Installation.md)
[^mitmproxy-install]: mitmproxy docs. Installation. docs.mitmproxy.org. [link](https://docs.mitmproxy.org/stable/overview/installation/)
[^mitmproxy-build]: mitmproxy. release/build.py + DeepWiki packaging notes. [link](https://deepwiki.com/mitmproxy/mitmproxy/6.2-packaging-and-distribution)
[^ms-codesign]: Microsoft Learn. Code signing options for Windows app developers. [link](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)
[^azure-pricing]: Microsoft Azure. Artifact Signing pricing. [link](https://azure.microsoft.com/en-us/pricing/details/trusted-signing/)
[^hanselman]: Hanselman. Automatically Signing a Windows EXE with Azure Trusted Signing. 2025. [link](https://www.hanselman.com/blog/automatically-signing-a-windows-exe-with-azure-trusted-signing-dotnet-sign-and-github-actions)
[^uv-5802]: astral-sh/uv issue #5802 — `uv bundle` suggestion. GitHub. [link](https://github.com/astral-sh/uv/issues/5802)
[^uv-10465]: astral-sh/uv issue #10465 — uv as self-contained tool wrapper. GitHub. [link](https://github.com/astral-sh/uv/issues/10465)
