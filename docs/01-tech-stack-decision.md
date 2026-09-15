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

## 调研证据 (2026-09 实测，20 份报告见 `bench/results/`)

### LaTeX 解析：8 库实测全灭于宏展开，自研半解析器已实证

**Benchmark (39 项目/256 tex + 30 陷阱，`bench/results/00-grand-comparison.md`)**:

| 库                           | 语料       | 陷阱      | 泄漏率    | identity    | 结论                                                      |
| ---------------------------- | ---------- | --------- | --------- | ----------- | --------------------------------------------------------- |
| **miniscanner (自研 spike)** | 259/259    | **32/32** | **0.11%** | **259/259** | **主解析器路线实证**                                      |
| latex-utensils (TS)          | 89/90      | 24/2/0    | 低        | —           | 命令族表参考;错误位置不可信                               |
| unified-latex (TS)           | 90/90      | 19/4/3    | 中        | 差          | **CTAN 签名表 (404 宏 +128 环境)+受限展开参考**           |
| tree-sitter-latex (TS)       | 90/90 不崩 | —         | —         | —           | **译文校验器**(1.15ms,ERROR/MISSING+env 配对)             |
| TexSoup (PY)                 | 84→89/90   | 4 fails   | 中        | 62/89       | tokenizer 内核参考                                        |
| plasTeX (PY)                 | ~75/90     | —         | —         | —           | **展开层设计 oracle**;真.sty 加载=静默截断须屏蔽          |
| pylatexenc (PY)              | 假 90/90   | 静默截断  | —         | —           | **REJECTED**:组内`\begin`吞至 EOF/`%`吃`}`,99% 损失零报错 |
| ieeA (PY)                    | 93/93      | 16/3/7    | 10.24%    | 0/93        | 反面基线                                                  |

- **T01 (`\be→\begin{equation}`) 8/8 库全灭**;真实语料 12/39 篇存在结构性宏 —— 半解析器 + 宏表是唯一正确路线，已被 miniscanner 验证 (1176 行达 M1 级指标)。
- **"能 parse"≠"parse 对"**: pylatexenc 90/90 假象 (静默截断零报错);tree-sitter `\verb|a%b|` 静默错。**校验器必须独立于解析器。**
- **AST round-trip 不可行，区间 splice 唯一保真**: 严格解析器在真实脏语料必破 (语料含真·缺`$`文件);pieces 覆盖全文+identity 逐字节一致证明"宁粗勿断"。
- **piece 边界纪律**根治 ieeA 死 token: 块级结构必须独立 piece，边界 token 不得并入 chunk。
- **宏展开层=blocker**(macro-stats 39 篇实测): 95% 论文有宏 (median 47),51% 在正文内定义，49% 宏体藏可译文本。最小范围：六类定义语法 + 参数代入 + 不动点展开+`\input`展平+`\if`结构化;catcode/halign 可弃 (≤1/39)。

### 编译：自动修复循环实证 (fixloop spike)

- **救回率 16/16 = 100%**(94% clean),冷环境 TEXMF 沙箱实测 12 项目×3 条件。四招承担全部修复：`static_precheck`(kpsewhich 预检 + 批量 tlmgr)+`install_file`+`install_tfm`+`install_sysfont`。
- **tectonic 陷阱确认**: 静默降级，"出 PDF"≠成功 —— 判定须用 `'!'错误数≤3` 的 clean 阈值。
- **ctex 注入 0% 破坏**(compile-bench): hjfy 同款 `\usepackage[fontset=windows,UTF8]{ctex}` 实测安全。
- hjfy 人肉固化修复库 → 我们规则表 (yaml 可贡献)+ LLM 修复器 (log+ 源文件→最小 patch),白盒可复现。

### 覆盖率与降级链 (60 篇实测抽样)

- e-print 源码 **86.7%**;arXiv HTML 覆盖 **=源码覆盖**(LaTeXML 从源码生成，救不了 13.3% PDF 直投)。
- 84.6% 多文件 tar(中位 7 文件),38.5% 自带 .cls/.sty,**42.5% 有.bbl 无.bib → 编译直接消费 .bbl**。
- 降级链定案：`e-print → arXiv HTML → MinerU/BabelDOC PDF`。

### BabelDOC sidecar(冒烟实测可行)

- 0.6.4 独立 venv(702MB 无 Torch),Adam 15 页 60s,~$0.02–0.05/篇，峰值 1.1GB;质量高 (图内矢量文字也翻)。
- 两坑：网关拒绝 `temperature=0`→`--no-send-temperature`;**翻译失败静默 fallback 原文**→sidecar 须校验 token 数防假成功。
- subprocess CLI + FastAPI 封装 ~200 行，解决 AGPL+ 崩溃隔离。**禁止 import 进主进程**。

### 支撑生态

| 维度            | Python                                    | TypeScript                       |
| --------------- | ----------------------------------------- | -------------------------------- |
| LLM SDK         | 官方全                                    | 官方全 + Vercel AI SDK           |
| prompt 缓存控制 | Anthropic/百炼/火山 SDK 覆盖              | 火山 Context API 需手写 ~200 行  |
| 任务队列        | huey(SQLite)/arq/dramatiq                 | bunqueue/bullmq                  |
| EPUB/DOCX       | EbookLib/python-docx 最成熟               | epub-gen-memory/docx 够用        |
| PDF 深度处理    | pdfminer/PyMuPDF/**BabelDOC/MinerU 原生** | pdf-lib/pdfjs-dist, 指令级做不了 |
| arXiv           | arxiv.py 现成                             | 手写 ~50 行                      |

**关键点**: MinerU 官方自带 `mineru-api` HTTP 服务 + Python/Go/TS 三语 SDK; BabelDOC 只有 Python 库/CLI。PDF 指令级翻译无论主语言是什么都要走 sidecar —— 但若主语言是 Python, 它们是直接 import 的库。

### 部署分发与社区

- **TeX 依赖是最大分发障碍**, 解法已验证：**便携 tectonic 二进制** (10-23MB, MIT, 自动拉宏包; 实测 0.17.0 用 ctexart 编译中文 PDF 成功，Fandol 字体自动下载)。边界：pstricks 不可用、无 PK 字体、无 Windows ARM64、bundle 固定快照冷门包缺文件 (放文档同目录可绕)。
- `uv tool install` 是本领域 CLI 分发事实标准 (pdf2zh 官方首选)。
- **社区匹配**: pdf2zh(36.9k)/MinerU(79.9k)/BabelDOC/bbm/LaTeXTrans/texglot/ieeA/AiNiee/docutranslate **全部 Python**, 贡献者池 59-129 人级; TS 在该领域无第二个管线项目，hjfy 是作者前端背景的孤例。
- **TeXGlot** (Mengqi-Lei/texglot, 30★, Apache-2.0): 与目标形态几乎完全重合的活体先例 —— Python 管线 + TS 前端对照阅读器 + Electron 桌面 + 便携 tectonic 三平台分发。其 `app/compiler.py` 的引擎兼容手术 (XeTeX 兼容前导/OT1→TU 字体改写/剥 inputenc) 证明"源码归一化层"思路可行。

## 落选方案与理由

- **全 TS (hjfy 原路)**: 唯一优势是解析器可跑浏览器 —— 但本架构阅读器渲染 PDF 而非 LaTeX, 优势不成立; 且放弃全部 Python 参考生态和贡献者池。hjfy 作者选 TS 因其前端背景 (amis 作者)。
- **全 Python 含前端**: 前端仍躲不开 JS (pdfslick), 统一语言红利本就不存在。
- **Go/Rust**: LaTeX/文档生态为零, 全部自写，仅有单二进制分发优势 —— tectonic sidecar 已解决分发瓶颈，不划算。

## 具体选型

| 组件            | 选择                                                                        | 备注                                                                                                 |
| --------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 语言/运行时     | Python 3.12+, uv 管理                                                       | `uv tool install texlate`                                                                            |
| LaTeX 半解析器  | **自写 scanner + pieces 区间 splice**(miniscanner 已实证 1176 行达 M1 指标) | 单次正向逐字符扫描→pieces→占位符 + 不动点展开;参考 unified-latex CTAN 签名表 + latex-utensils 命令族 |
| 宏展开层        | 自写六类定义建表 + 参数代入 + 不动点受限展开                                | 含正文内定义 (51% 论文);plasTeX mouth/gullet 设计 + MathTranslate 受限展开规则                       |
| 校验            | 自写规则 + **tree-sitter-latex CST 校验**(独立解析器，防"能 parse 但错")    | ERROR/MISSING+env配对(~35行)+brace/cite key diff+ 占位符修复 (Levenshtein)                           |
| LLM 编排        | 自写 ~500 行：OpenAI 兼容 + Anthropic, asyncio+Semaphore                    | 参考 ieeA provider 缓存策略 (cache_control/Context API)                                              |
| 编译            | **xelatex/TeXLive 主 + tectonic 便携二进制降级** + ctex 注入                | fixloop 实测：判定用 clean 阈值非"出 pdf"                                                            |
| 编译修复        | **log 解析 → 规则表 (16 条已实证) → 修复执行 → 重试** + LLM 辅助修复        | fixloop spike 救回率 100%;hjfy 最大壁垒的开源解法                                                    |
| Web 后端        | FastAPI + SSE + SQLite 队列 (huey 或自写)                                   | 服务端可换 Redis                                                                                     |
| 前端            | Vite + TS + pdfslick 双栏对照 + marked/KaTeX                                | hjfy 同款阅读形态                                                                                    |
| 存储            | 本地：文件系统缓存; 服务端：S3 + Postgres                                   | arXiv ID → 译文缓存 (产品壁垒)                                                                       |
| PDF 路线 (后置) | MinerU HTTP API (过渡) → BabelDOC sidecar (旗舰)                            | AGPL 组件保持在进程边界外                                                                            |
| License         | **Apache-2.0** (本仓库代码)                                                 | AGPL 组件只经 CLI/HTTP 边界调用                                                                      |
