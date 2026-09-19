# 竞品分发形态与 LaTeX 捆绑调研（2026-09-19）

调研问题：(A) 同类 arXiv/PDF 翻译产品实际怎么分发；(B) LaTeX 工具链随 app 捆绑的技术事实。所有事实均经 2026-09-19 联网核实。

## A. 同类/相邻产品分发形态

### BabelDOC（funstory-ai，沉浸式翻译团队）

纯 Python 库定位——README 明确写 "Mainly designed to be embedded into other programs"。分发只有两条：`uv tool install --python 3.12 BabelDOC`（官方推荐）与源码 `uv run`[^babeldoc]。**官方不提供任何 GUI/exe**；CLI 自述 "mainly for debugging purposes"，官方把终端用户导向自家在线服务（Immersive Translate - BabelDOC，免费档 1000 页/月）和自部署壳 PDFMathTranslate 2.0[^babeldoc]。

### PDFMathTranslate-next（PDFMT 2.0，BabelDOC 官壳）

这是与 texlate 定位最接近的对照组：**同一生态位里活得最好的自部署产品**。分发矩阵[^pdfmt]：

- **Windows EXE**（官方推荐 Windows 用户用这个）：**不是 PyInstaller**，而是 **PyStand**（skywind3000 的轻量 Python 启动器）+ python.org embeddable runtime + 整个 `site-packages` 目录拷贝的文件夹式打包。CI 工作流 `exe-build.yml`：下载 `python-3.13.3-embed-amd64.zip` 解到 `build/runtime`，`uv pip install .` 后把 `venv/Lib/site-packages` 拷到 `build/site-packages`，PyStand.exe 改名 `pdf2zh.exe`，再跑 `babeldoc --generate-offline-assets ./build` 预置资产[^exebuild]。
- 两档 zip：裸版 ~380–430MB，**with-assets 版 ~590–650MB**（含字体+模型离线资产包，推荐首次/离线用户）；v2.9.0 每档下载量约 1k–4.5k 次[^pdfmt-releases]。
- **Docker**（推荐 Linux）、**uv tool**（推荐 macOS）。
- 前端形态：CLI + **Gradio WebUI**（本地起服务开浏览器）+ API；另有第三方 **Zotero 插件** `guaguastandup/zotero-pdf2zh`[^pdfmt]。
- 细节：Windows 版 release note 常年带 "打不开请先装 VC++ Redistributable" 提示——**未签名产物**的真实用户摩擦写照[^pdfmt-releases]。

### hjfy.top（幻觉翻译，texlate 复刻对象）

**纯 SaaS 网站，无任何客户端**。免注册浏览已翻译论文；新建任务需登录，限额 100 篇 arXiv/天 + 10 篇 PDF/天；内测期免费，京 ICP 备案个人主体[^hjfy]。生态上已长出第三方 **Zotero 插件** `ANGJustinl/zotero-plugin-hjfy`（AGPL，直连 `hjfy.top/api/arxivFiles/{id}` 拉 zhCN PDF 附件）[^hjfy-zotero]。

### 沉浸式翻译（Immersive Translate）

浏览器扩展 + 会员 SaaS，无独立桌面 app。其 PDF 翻译功能分 PDF Pro 与 BabelDOC 两路，**BabelDOC 明确是"后端翻译架构"——翻译全部跑在服务器侧**，免费用户单任务 166 页上限 + GLM-4-Flash，Pro 用户 5000 页 + 批量 100 任务 + 更多模型[^imt]。Zotero 插件 `zotero-immersivetranslate` 仅 Pro 可用。

### 其它桌面翻译工具（一句话生态位）

CopyTranslator（17.5k stars）= **Electron + Vue + Element**，GPL-2.0，剪贴板监听式划词翻译[^ct]；沙拉查词 = 纯浏览器扩展；Zotero 翻译插件生态是这类工具触达学术用户的主要通道。

### SaaS vs 本地：业界选择

算力/体积权衡下**主流是远程服务**：hjfy.top 与沉浸式翻译的 BabelDOC 都把翻译+排版重活放云端（服务端跑模型与排版引擎，前端只是提交+展示）。本地自部署形态存在（PDFMT 2.0），但定位是"给自部署用户的备份选项"，官方引流仍指向在线服务[^babeldoc]。**没有一家把 LaTeX/PDF 编译重链塞进桌面 app 当主形态**——PDFMT 的 exe 是"免环境解压即用"的本地 web 服务壳，不是原生桌面应用。

### A 部分启示

1. **"本地起 web 服务 + 浏览器打开" 就是这个赛道的既定 app 形态**——PDFMT 的 Gradio WebUI、texlate 自己的 `texlate web` 是同一物种。用户心智里"翻译论文工具 = 网页 UI"，套原生壳的边际收益低。
2. **Windows 免安装包是真需求**：PDFMT 推荐 Windows 用户走 exe 而非 uv/docker，说明目标用户（学术用户为主）里 Windows + 无 Python 环境占比高。PyStand 目录打包（而非 PyInstaller 单文件）是它的实际选择，值得复用评估。
3. **Zotero 插件是这个生态的标准触手**——hjfy、BabelDOC、PDFMT 三家都有（官方或第三方），成本极低（读 API 拉 PDF 挂附件），texlate 开放 API 后大概率会有人做或值得自己做一个。
4. hjfy 选 SaaS 的合理推断：LLM key 与算力成本集中管理、排队限额、免分发——与 texlate 的 BYOK 本地模型正好是互补定位，**本地 app 反而是 texlate 的差异化**（隐私、自带 key、离线可用）。

## B. LaTeX 捆绑技术事实

### tectonic 单二进制可嵌入性（已验证的成熟模式）

- 单文件静态二进制 ~10–20MB/平台（0.16.0：linux-musl 9.4MB、windows-msvc zip 19.1MB、mac 19.6MB）[^tectonic-rel]。
- **被捆绑进桌面 app 是成熟做法**：GlyphX/GlyphTeX 两个 Tauri LaTeX 编辑器在 CI 里按 target triple 下载 tectonic 塞进 `src-tauri/binaries` 当 sidecar 随安装器分发[^glyphx]；Overleaf 替代品 Scribe 同样 "bundled tectonic, no TeX distribution required"[^scribe]。texlate 现有的"五平台 sha256 钉死 + 自动下载"方案与之同构甚至更稳（hash 钉死）。
- **首跑联网拉 bundle 是按需逐文件的**，不是整包下载：引擎拦截 TeX I/O，缺哪个文件从预建 bundle（indexed tar）拉哪个，落本地缓存；整包 ~2.8GB 但永远不会整包拉[^tectonic-bundle]。
- **离线可行**：`--only-cached` 用已缓存文件编译；缓存目录可预置/拷贝（`TECTONIC_CACHE_DIR`），社区已验证"干净缓存跑一遍→拷走缓存→离线机用"的流程[^tectonic-offline]。完整离线需 `-b` 指本地 bundle 文件（数 GB，不现实）；现实路径是**预置按文档需求热好的缓存子集**或首次运行联网。
- 官方默认 bundle 仍是 **TeX Live 2022 代**（`tlextras-2022.0r0.tar`，0.16.8 时点）；2024/2025 的 `.ttb` 新格式 bundle 只有社区构建、需 master 分支[^tectonic-tl2024]。可用 `TECTONIC_BUNDLE_PREFIX`/`TECTONIC_BUNDLE_LOCKED` 构建期改默认源，`--web-bundle` 运行期覆盖[^tectonic-bundle]。
- V1 CLI vs `-X` V2：texlate 已用 `-X compile` 路径，符合现状。

### biber/biblatex：tectonic 的已知短板（与 texlate 现有坑一致）

- tectonic **不内置 biber**：biblatex 任务 shell out 到外部 `biber` 可执行文件；官方长期 issue（#35/#893/#1010）承认这是设计妥协[^biber]。
- **biblatex↔biber 版本错配是慢性病**：bundle 钉 TL2022 的 biblatex 3.x 与用户系统 biber 版本脱节就会炸（#1267：biber 2.20 ↔ biblatex 3.17 不兼容）[^biber-issue]。这正是 texlate 已记录的坑（tectonic biblatex 3.17 ↔ 系统 biber 2.22 错配）。
- **出路已在上游出现**：PR #1166（2025-07 合入）让 tectonic **优先用名为 `tectonic-biber` 的可执行文件**（CWD 或 PATH 中），`tectonic -X biber` 亦走它[^biber-pr]。→ **捆绑方案可以带一个钉版 biber 改名 `tectonic-biber` 一并分发**，从根上消掉错配——这是 texlate 做二进制分发时应直接采纳的模式。

### TinyTeX：另一档选择

- 体积档（安装包）：TinyTeX-0 ~1–24MB（仅 infra+tlmgr）、**TinyTeX-1 ~50–74MB**（够编译多数 R Markdown）、TinyTeX ~150–210MB、TinyTeX-2 = scheme-full ~1.7–1.9GB[^tinytex]。
- **Quarto 的 `quarto install tinytex` 就是"按需下载托管发行版"模式**——不在安装器里带 TeX，首次需要时拉月度 release[^tinytex-arm]。texlate 的 ensure_tectonic 已经是这个模式。
- TinyTeX 的优势是有完整 tlmgr（任意 CTAN 包装到用户目录），xelatex+biber 全家桶齐；劣势是目录树而非单文件，且与 tectonic 比体积大一个量级。

### TeX Live 全量：没人随 app 捆绑

scheme-full ~1.7–1.9GB 压缩（安装后 7GB+），没有任何桌面产品这么干；业界共识是"基础包+按需安装"（TinyTeX/MiKTeX/tectonic 三条路线都是这个思想）[^tinytex]。

### WASM 引擎：可选项但不解决真问题

SwiftLaTeX（PdfTeX+XeTeX WASM，AGPL-3.0，引擎停留在 TL2020 代）证明了浏览器内编译可行[^swiftlatex]；后继者 TeXlyre/busytex 2026 年已把 WASM 引擎升级到 TeX Live 2025/2026（pdftex/xetex/luatex）[^texlyre]。但对 texlate 而言 WASM 只替换"引擎二进制"这一块——fixloop/validate/expand 整条 Python 链仍在，消灭不了最大的分发件（Python 本体），且 SwiftLaTeX 是 AGPL。不值得。

## B 部分结论：LaTeX 捆绑不构成分发障碍

1. **tectonic 托管下载（texlate 已实现）已经是最优解**：10–20MB 单文件 + 首跑按需拉文件，与 GlyphX/Scribe/Quarto 的业界实践同构。做二进制/app 时直接把 `ensure_tectonic` 的产物打进包或保留首跑下载皆可，两路都有先例。
2. **biber 是唯一的真坑**，且上游已给出解：钉版 biber 改名 `tectonic-biber` 随包分发（~几 MB Perl 打包产物）可根治版本错配；不做则 biblatex 论文在"干净机器"上必然踩 #1267。
3. 完全离线编译不现实（bundle 数 GB），但"首跑联网拉文件 + 之后 `--only-cached` 可复现"对目标用户足够——翻译流程本身就要联网调 LLM。
4. WASM/TeX Live 全量/TinyTeX 三路线都逊于现状，不建议更换引擎策略。

### 参考文献

[^babeldoc]: funstory-ai. BabelDOC README. GitHub. [github.com/funstory-ai/BabelDOC](https://github.com/funstory-ai/BabelDOC)
[^pdfmt]: PDFMathTranslate. PDFMathTranslate-next README. GitHub. [github.com/PDFMathTranslate/PDFMathTranslate-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next)
[^exebuild]: PDFMathTranslate. exe-build.yml workflow. GitHub. [github.com/PDFMathTranslate-next/PDFMathTranslate-next/blob/a3efffec/.github/workflows/exe-build.yml](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/blob/a3efffec/.github/workflows/exe-build.yml)
[^pdfmt-releases]: PDFMathTranslate. Releases v2.8.1/v2.9.0. GitHub. [github.com/PDFMathTranslate-next/PDFMathTranslate-next/releases](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/releases/tag/v2.9.0)
[^hjfy]: 代码号/AI工具导航站. 幻觉翻译产品介绍. 2025. [ebingou.cn/gongju/21873.html](https://www.ebingou.cn/gongju/21873.html)
[^hjfy-zotero]: ANGJustinl. zotero-plugin-hjfy. GitHub. [github.com/ANGJustinl/zotero-plugin-hjfy](https://github.com/ANGJustinl/zotero-plugin-hjfy)
[^imt]: 沉浸式翻译. BabelDOC 翻译器文档. 2026. [immersivetranslate.com/zh-Hans/document/babel-doc-translator/](https://immersivetranslate.com/zh-Hans/document/babel-doc-translator/)
[^ct]: CopyTranslator. README/致谢. GitHub. [github.com/CopyTranslator/CopyTranslator](https://github.com/copytranslator/CopyTranslator)
[^tectonic-rel]: tectonic-typesetting. tectonic 0.16.0 release assets. GitHub. [github.com/tectonic-typesetting/tectonic/releases/tag/tectonic%400.16.0](https://github.com/tectonic-typesetting/tectonic/releases/tag/tectonic%400.16.0)
[^glyphx]: ssxraa. glyphx release-desktop.yml（tectonic 作 Tauri sidecar 按 triple 下载）. GitHub. [github.com/ssxraa/glyphx/blob/main/.github/workflows/release-desktop.yml](https://github.com/ssxraa/glyphx/blob/main/.github/workflows/release-desktop.yml)
[^scribe]: sunnyallana. Scribe README（"LaTeX engine in the installer: tectonic bundled"）. GitHub. [github.com/sunnyallana/Scribe](https://github.com/sunnyallana/Scribe/blob/master/README.md)
[^tectonic-bundle]: tectonic-typesetting. bundles/README + PR #1131 + issue #898. GitHub. [github.com/tectonic-typesetting/tectonic/blob/master/bundles/README.md](https://github.com/tectonic-typesetting/tectonic/blob/master/bundles/README.md)
[^tectonic-offline]: tectonic-typesetting. Issue #977 "avoid network dependencies altogether". GitHub. [github.com/tectonic-typesetting/tectonic/issues/977](https://github.com/tectonic-typesetting/tectonic/issues/977)
[^tectonic-tl2024]: tectonic-typesetting. Issue #1269 "Bundles for TeX Live >= 2024". GitHub. [github.com/tectonic-typesetting/tectonic/issues/1269](https://github.com/tectonic-typesetting/tectonic/issues/1269)
[^biber]: tectonic-typesetting. Issue #35 "Full biblatex support". GitHub. [github.com/tectonic-typesetting/tectonic/issues/35](https://github.com/tectonic-typesetting/tectonic/issues/35)
[^biber-issue]: tectonic-typesetting. Issue #1267 "biber 2.20 and biblatex 3.17 incompatible". GitHub. [github.com/tectonic-typesetting/tectonic/issues/1267](https://github.com/tectonic-typesetting/tectonic/issues/1267)
[^biber-pr]: tectonic-typesetting. PR #1166 "prefer tectonic-biber as the biber executable". GitHub. [github.com/tectonic-typesetting/tectonic/pull/1166](https://github.com/tectonic-typesetting/tectonic/pull/1166)
[^tinytex]: rstudio. tinytex-releases README（各档体积表）. GitHub. [github.com/rstudio/tinytex-releases](https://github.com/rstudio/tinytex-releases)
[^tinytex-arm]: Yihui Xie. TinyTeX arm64/musl binaries 公告（quarto install tinytex 走月度 release）. 2026-03. [yihui.org/en/2026/03/tinytex-arm64/](https://yihui.org/en/2026/03/tinytex-arm64/)
[^swiftlatex]: SwiftLaTeX. README（PdfTeX/XeTeX WASM，AGPL）. GitHub. [github.com/SwiftLaTeX/SwiftLaTeX](https://github.com/SwiftLaTeX/SwiftLaTeX)
[^texlyre]: TeXlyre. Discussion #83 / Issue #13（WASM 引擎升级 TL2025/2026）. GitHub. [github.com/TeXlyre/texlyre/discussions/83](https://github.com/TeXlyre/texlyre/discussions/83)
