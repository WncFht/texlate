# ADR-001: 技术栈选型

**状态**: 已决定 (2026-09-14)
**背景**: 开源复现「幻觉翻译 hjfy.top」—— arXiv LaTeX 源码 → LLM 段落级翻译 → 注入 ctex 重编译中文 PDF → 双语对照阅读 + 译文缓存。

## 决策

**Python 3.12+ 核心引擎/CLI/服务端 + TypeScript Web 前端 + tectonic 便携二进制做编译层。**

```
┌─ Web 前端 (TS: Vite + pdfslick + KaTeX, 双语对照) ─┐
│                  JSON + SSE                        │
├─ texlate 核心 (Python) ────────────────────────────┤
│  LaTeX 半解析器 → 宏展开层 → 翻译编排 → 校验 →       │
│  重建 → tectonic/xelatex 编译 + 自动修复循环         │
├─ Sidecar (按需) ───────────────────────────────────┤
│  MinerU HTTP API (PDF→结构化) / BabelDOC CLI        │
└────────────────────────────────────────────────────┘
```

## 调研证据 (2026-09 实测)

### LaTeX 解析: 所有语言都必须自写

- 没有任何现成库完成「段落级提取 + 宏展开 + 保真回填」全链路。hjfy (~2万行TS)、ieeA (~15k行Python)、MathTranslate、LaTeXTrans、texlab、pandoc、LaTeXML 全部自写解析器。
- 现成最接近的三个:
  - **unified-latex** (TS, 127★, MIT, 39万下载/月): 36 包 AST 工具集, 明确不保 round-trip, 不做 \def 展开; **其 CTAN 宏签名表可移植复用**
  - **pylatexenc 3** (Python, 427★, MIT): 真实节点模型+宏签名表(natbib 有类别)+pos 信息; ieeA 曾用其 AST 后弃用 —— 严格按签名表挂参数遇到 spec 外宏会断, 翻译场景要"宁粗勿断"的容错分割
  - **TexSoup** (Python, 330★, BSD): 容错最强, README 自报 50/50 arXiv 论文全解析成功 (plasTeX 11/50, LaTeXML 29/50), 但语义浅
- 真做宏展开的只有渲染引擎 (plasTeX/LaTeX.js/LaTeXML/pandoc), 都不保源码
- **正确架构共识**: 任务本质是 segment-protect-reconstruct —— scanner 记录每个可译段的 byte range, 译文按区间 splice, 不做 AST 全量重建
- **tree-sitter-latex** (latex-lsp, 173★, MIT, 移植自 texlab): 错误容忍强, 四语言绑定齐全 —— 用作**辅助校验层**而非主解析器

### 支撑生态

| 维度 | Python | TypeScript |
|---|---|---|
| LLM SDK | 官方全 | 官方全 + Vercel AI SDK |
| prompt 缓存控制 | Anthropic/百炼/火山 SDK 覆盖 | 火山 Context API 需手写 ~200 行 |
| 任务队列 | huey(SQLite)/arq/dramatiq | bunqueue/bullmq |
| EPUB/DOCX | EbookLib/python-docx 最成熟 | epub-gen-memory/docx 够用 |
| PDF 深度处理 | pdfminer/PyMuPDF/**BabelDOC/MinerU 原生** | pdf-lib/pdfjs-dist, 指令级做不了 |
| arXiv | arxiv.py 现成 | 手写 ~50 行 |

**关键点**: MinerU 官方自带 `mineru-api` HTTP 服务 + Python/Go/TS 三语 SDK; BabelDOC 只有 Python 库/CLI。PDF 指令级翻译无论主语言是什么都要走 sidecar —— 但若主语言是 Python, 它们是直接 import 的库。

### 部署分发与社区

- **TeX 依赖是最大分发障碍**, 解法已验证: **便携 tectonic 二进制** (10-23MB, MIT, 自动拉宏包; 实测 0.17.0 用 ctexart 编译中文 PDF 成功, Fandol 字体自动下载)。边界: pstricks 不可用、无 PK 字体、无 Windows ARM64、bundle 固定快照冷门包缺文件(放文档同目录可绕)。
- `uv tool install` 是本领域 CLI 分发事实标准 (pdf2zh 官方首选)。
- **社区匹配**: pdf2zh(36.9k)/MinerU(79.9k)/BabelDOC/bbm/LaTeXTrans/texglot/ieeA/AiNiee/docutranslate **全部 Python**, 贡献者池 59-129 人级; TS 在该领域无第二个管线项目, hjfy 是作者前端背景的孤例。
- **TeXGlot** (Mengqi-Lei/texglot, 30★, Apache-2.0): 与目标形态几乎完全重合的活体先例 —— Python 管线 + TS 前端对照阅读器 + Electron 桌面 + 便携 tectonic 三平台分发。其 `app/compiler.py` 的引擎兼容手术(XeTeX 兼容前导/OT1→TU 字体改写/剥 inputenc)证明"源码归一化层"思路可行。

## 落选方案与理由

- **全 TS (hjfy 原路)**: 唯一优势是解析器可跑浏览器 —— 但本架构阅读器渲染 PDF 而非 LaTeX, 优势不成立; 且放弃全部 Python 参考生态和贡献者池。hjfy 作者选 TS 因其前端背景 (amis 作者)。
- **全 Python 含前端**: 前端仍躲不开 JS (pdfslick), 统一语言红利本就不存在。
- **Go/Rust**: LaTeX/文档生态为零, 全部自写, 仅有单二进制分发优势 —— tectonic sidecar 已解决分发瓶颈, 不划算。

## 具体选型

| 组件 | 选择 | 备注 |
|---|---|---|
| 语言/运行时 | Python 3.12+, uv 管理 | `uv tool install texlate` |
| LaTeX 半解析器 | **自写 scanner + 递归下降** (~3-5k行) | byte-range 区间替换模型; 参考 ieeA/TexSoup 容错思路 + unified-latex CTAN 签名表移植 |
| 宏展开层 | 自写 \newcommand/\def/\newenvironment 建表 + 受限展开 | 只对"含可翻译文本"的宏展开 (MathTranslate 思路) |
| 校验 | 自写规则 + **tree-sitter-latex 辅助 AST 校验** | brace token-diff/cite-ref key diff/环境配对/占位符修复(Levenshtein) |
| LLM 编排 | 自写 ~500行: OpenAI兼容 + Anthropic, asyncio+Semaphore | 参考 ieeA provider 缓存策略 (cache_control/Context API) |
| 编译 | **tectonic 便携二进制子进程** (校验和验证下载) + xelatex/TeXLive 可选 | texglot 已验证三平台; ctex 注入 |
| 编译修复 | **log 解析 → 规则表 → 修复执行 → 重试** 循环 + LLM 辅助修复 | hjfy 最大壁垒的开源解法 |
| Web 后端 | FastAPI + SSE + SQLite 队列 (huey 或自写) | 服务端可换 Redis |
| 前端 | Vite + TS + pdfslick 双栏对照 + marked/KaTeX | hjfy 同款阅读形态 |
| 存储 | 本地: 文件系统缓存; 服务端: S3 + Postgres | arXiv ID → 译文缓存 (产品壁垒) |
| PDF 路线 (后置) | MinerU HTTP API (过渡) → BabelDOC sidecar (旗舰) | AGPL 组件保持在进程边界外 |
| License | **Apache-2.0** (本仓库代码) | AGPL 组件只经 CLI/HTTP 边界调用 |
