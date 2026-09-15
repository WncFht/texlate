# 架构设计

> 本文是**高层架构视图**。逐模块实现规格以 `docs/06–10` 为准（06 源获取 / 07 解析管线 / 08 翻译 + 编译 / 09–10 benchmark）；调研证据在 `docs/research/`。

## 管线总览 (arXiv LaTeX 路线，hjfy 同款)

```
arXiv ID ─→ ①下载源码tar ─→ ②展平(\input/include) ─→ ③宏表建立+半解析
        ─→ ④段落级翻译(LLM,占位符保护) ─→ ⑤校验+自动修复译文
        ─→ ⑥重建.tex ─→ ⑦注入ctex ─→ ⑧tectonic编译(+修复循环)
        ─→ ⑨产出: zh.pdf / 双语对照数据 / 译文源码tar
```

## 模块划分

### 1. `texlate.latex` — 核心解析器 (自写，本项目命脉)

**区间替换模型**: 不做 AST 全量重建。scanner 输出 token/segment 流，每段记录 `byte_range + kind`,可译段标记 `chunk_id`,保护段替换为 `[[TYPE_n]]` 占位符; 译文回来按 byte_range splice 回原文。

```
Scanner 单遍产出:
  ├─ macro_table:   \newcommand/\renewcommand/\def/\NewDocumentCommand/\newenvironment → 受限展开规则
  ├─ segments[]:    {kind: text|math_inline|math_env|command|comment|verbatim|env_head... , start, end, translatable}
  ├─ chunks[]:      段落级可译单元 (≥20字符, 空行分段, 结构行排除)
  └─ placeholders:  [[MATH_n]] [[CITE_n]] [[REF_n]] [[ENV_n]] [[AUTHOR_n]] ...
```

**保护清单** (ieeA 实测漏洞清单的全部修复):

- 数学：`$…$` `\(\)` `\[…\]` `$$…$$` + 全族数学环境 (equation/align/gather/multline/flalign/alignat/IEEEeqnarray/dmath/subequations/empheq/cases/split/…, 可配置扩展)
- 引用全族：`\cite \citep \citet \citealp \citeauthor \citeyear \cite*[…]{…}` + `\ref \eqref \autoref \cref \Cref \pageref \nameref \label`
- `\url \href{u}{t}(只翻t) \includegraphics \footnote(翻) \verb\x \verb|…|`
- 作者块 `\author[opt]{…}` 整段保护 (可选译 affiliation)
- verbatim/lstlisting/minted/comment 环境原样
- 结构命令 `\section[opt]{t} \subsection… \title \caption[\lof]{t}` — 可选参数保留，必译参数挖为 chunk
- `\if/\else/\fi` 条件块按结构保护 (内容仍走段落提取)
- 注释处理在 verbatim 识别**之后**逐字符做 (修 ieeA 的 \url 含 % 被截断 bug)

**宏展开层** (hjfy 双解析思路的落地):

- 前置扫描建立宏表; 体内含可翻译文本的宏 → 标记为"透明宏", 其调用点的参数参与分段
- 体内纯结构/公式的宏 (\be→\begin{equation}) → 展开为等价命令后按该命令规则保护
- 展开深度限制 + 递归检测，畸形定义降级为"不透明整体保护"

### 2. `texlate.xlat` — 翻译编排

- 分块：段落为最小单元; <300 字符短块打包为编号批量请求 (≤2000 字符/批); 批量解析失败整批回退单翻
- 上下文：每 chunk 携带前 N 段摘要/前后句; 可选先跑"术语提取"第一遍生成双语术语表
- 术语表：文档级过滤并集注入 system prompt (烤进 prompt 吃前缀缓存); 用户可编辑
- Provider: OpenAI 兼容网关 + Anthropic; 前缀缓存优化 (cache_control/火山 Context API); 指数退避重试; 失败降级保原文
- 断点续翻：state 文件逐块落盘
- 校验 (翻译后): 占位符还原 (Levenshtein≤2 修 typo, 幻觉占位符删除)、brace token-diff、cite/ref key 集合差集、math env 配对、长度比 sanity; 失败 → 重译该块 / 回退原文
- 辅助：tree-sitter-latex 解析译文做结构 sanity check

### 3. `texlate.compile` — 编译 + 修复循环 (hjfy 最大壁垒)

- 中文注入：`\documentclass` 后插 `\usepackage[fontset=fandol,UTF8]{ctex}` (服务端可切 fontset); 兼容手术：剥 `[utf8]{inputenc}`/`[T1]{fontenc}`、OT1→TU 字体声明改写、与 fontspec/polyglossia/babel 冲突检测表
- 引擎：tectonic 便携二进制 (校验和验证，texglot 方案) 默认; 服务端/CI 用 TeXLive xelatex+latexmk; 多趟+bibtex/biber; 无 .bib 有 .bbl 时 `\bibliography{x}` → `\input{x.bbl}` 改写
- **修复循环** (核心差异化):

    ```
    编译失败 → 解析 log (! 错误行 + 上下文+l.*提示) → 规则表匹配 (已知包冲突/命令缺失/环境错配)
      → 命中：应用固化修复 → 重编译
      → 未命中：LLM 修复器 (喂最小上下文：log 片段 + 源文件相关段) → 重编译 (限 N 轮)
      → 仍败：降级策略 (该文件回退原文/标记 fault, 提供源码包下载)
    ```

- 修复规则库是**可持续积累的资产**: 每次失败案例沉淀为 yaml 规则 (hjfy 的 5000 篇人肉经验 → 我们的社区众包规则库)

### 4. `texlate.arxiv` — 下载与缓存

- `arxiv.org/e-print/{id}` (tar.gz/单 tex/gz 兼容), 3s 限速 + 重试，tar 路径过滤
- 版本号语义：`2501.14787v2` 精确命中; 无版本 → 最新
- 缓存键：`arxiv_id@version + model + pipeline_version + target_lang` → {pdf, src.tar, meta}
- 批量预译：S3 requester-pays / OAI-PMH; 引用排序选种子集

### 5. `texlate.server` + `web/` — 产品层

- FastAPI: `POST /api/arxiv/{id}/translate` `GET /api/task/{id}`(SSE 逐段进度) `GET /api/files/{id}` `POST /api/upload` (PDF/DOCX/EPUB)
- 前端：Vite+TS, 双 pdfslick viewer 滚动同步 (original/translated/split 三模式) — 直接对标 hjfy 阅读体验
- 任务队列：SQLite (CLI/单机) → Redis (服务端)

### 6. 文档翻译 (后置)

- PDF: 过渡期 MinerU HTTP → markdown 译文对照阅读; 旗舰期 BabelDOC CLI sidecar 出同页双语 PDF (AGPL 边界：独立进程/可选安装)
- EPUB: zip+lxml 原文节点后插译文节点 (bilingual_book_maker 模式)
- DOCX: `word/document.xml` 段后插 `w:p` 复制样式; 或 LibreOffice→PDF 走统一管线

## 目录结构 (uv workspace 预留)

```
texlate/
  src/texlate/
    latex/        # scanner, macro_table, placeholder, reconstruct
    xlat/         # orchestrator, providers, prompts, glossary
    validate/     # rules, ts_latex(可选绑定)
    compile/      # tectonic wrapper, ctex inject, fixrules/, repair loop
    arxiv/        # download, cache, s3
    server/       # fastapi app
    cli.py
  web/            # TS 前端
  tests/          # 黄金语料集: tests/corpus/*.tex 真实arXiv样本
  docs/
```

## 测试策略 (差异化重点)

- **黄金语料集**: 收集 N 篇真实 arXiv 源码做回归 (解析→翻译 mock→重建→编译全链), 这是 hjfy 用 5000 篇人肉做的事的开源版
- 单元：占位符还原/宏展开/校验器/批量解析
- 端到端成功率看板：每环节成功率量化 (下载/解析/翻译/编译), 迭代有据
