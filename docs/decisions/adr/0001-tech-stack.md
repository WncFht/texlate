# ADR-0001 技术栈：Python 核心 + TypeScript 前端 + 进程边界隔离 AGPL

> **状态**：现行
> **日期**：2026-09-14（初次裁决）| 更新 2026-09-15（引擎默认改判，归 ADR-0006）

## 上下文

复刻 hjfy 要一次性选定语言、运行时、编译层、前端栈、分发方式与许可证。调研期对 8 个 LaTeX 解析库、编译侧、支撑生态、部署分发做了大横评（主仓 `docs/05` 证据矩阵 E1–E22），结论是所有现成 LaTeX 解析库都在宏展开上全灭、TeX 依赖是最大分发障碍、同领域开源项目清一色 Python。

## 裁决

**Python 3.12+ 做核心引擎/CLI/服务端，TypeScript 只做 Web 前端，tectonic 便携二进制做编译层兜底，uv 管理分发，仓库代码 Apache-2.0，AGPL 组件一律进程边界外。**

- 语言/运行时：Python 3.12+、uv 管理，`uv tool install texlate` 分发（pdf2zh 同款事实标准）。
- 编译层：tectonic 便携二进制（10–23MB、MIT、自动拉宏包）+ TeXLive xelatex——引擎细节与路由见 ADR-0006。
- 前端：SolidJS + Vite + pdfslick（选型理由见 ADR-0016）。
- sidecar：BabelDOC（AGPL）等 copyleft 组件只经 CLI/HTTP 边界调用，禁止 import 进主进程（ADR-0017）；EbookLib 不碰、EPUB 用 stdlib 自拆（ADR-0018）。
- 参考实现：unified-latex（CTAN 签名表）、latex-utensils（命令族）、plasTeX（mouth/gullet 设计）、texglot（归一化/锚点同步/BYOK/分发矩阵六块照抄设计）、ieeA（GPL-3，只看模式不搬码）。

## 理由

- **Python 生态全覆盖**：LLM SDK（OpenAI/Anthropic）、arXiv 客户端、EPUB/DOCX 库、PDF 深度处理（BabelDOC/MinerU 原生 Python）、任务队列——每个环节都有成熟件；TypeScript 在该领域没有第二个管线项目，hjfy 选 TS 是作者前端背景的孤例。
- **社区匹配**：pdf2zh/MinerU/BabelDOC/bbm/LaTeXTrans/texglot/ieeA 全部 Python，贡献者池 59–129 人级。
- **TeX 分发已解**：tectonic 单二进制 + 自动拉宏包实测可用（0.17.0 编译中文 PDF 成功），「装 TeXLive」不再是分发前置。
- **落选方案**：全 TS（解析器跑浏览器的优势不成立——阅读器渲染的是 PDF 不是 LaTeX，且放弃全部 Python 生态）；全 Python 含前端（前端躲不开 JS，统一语言红利本就不存在）；Go/Rust（LaTeX/文档生态为零，唯一优势单二进制已被 tectonic sidecar 解决）。完整被否清单见 ADR-0019。
- 证据：主仓 `docs/05` 证据矩阵 E1（8 库横评）、E9（引擎矩阵）、E12（texglot 拆解）；调研档案 `research/product/2026-09-14-competitors.md`、`research/latex/texglot-patterns.md`。

## 演变

- 2026-09-14：初裁「xelatex/TeXLive 主 + tectonic 便携降级」。
- 2026-09-15:05 裁决 6 改判为「分发默认 tectonic 优先 + xelatex 兜底 + 静态预检路由；开发默认 xelatex」——引擎语义归 ADR-0006，本篇只管语言/边界/许可证层。
- 任务队列候选 huey 不实现：M0 定案自写 asyncio.Queue + SQLite（ADR-0015）。

## 现状

落地为 `src/texlate/` Python 包（uv 管理、`uv sync` 起 .venv、Python 3.12+）+ `web/` SolidJS+Vite 前端（独立 package.json）+ `server/babeldoc.py` spawn-CLI sidecar；许可证 Apache-2.0 + NOTICE（texglot/unified-latex 等借鉴声明）。
