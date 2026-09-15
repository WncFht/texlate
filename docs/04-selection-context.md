# 技术选型上下文 — 库与 API 候选全景

> 用途：M0 开工前最后一轮"选库/选 API"决策的输入文档。
> 状态：解析/编译/覆盖三大路线**已实证定案**；本文档列出每个组件的候选、实测证据、推荐与待决点。
> 证据索引：`bench/results/00-grand-comparison.md`（总结论）+ 19 份单项报告 + `bench/corpus/MANIFEST.md`(39 项目/256 tex 语料）。

---

## 0. 已定架构（不再翻案）

```
arXiv ID / 上传文件
  → 获取层: e-print(87%) → arXiv HTML(同覆盖降级) → PDF(13%, sidecar)
  → texlate.latex: 自研半解析器(单次正向扫描→pieces→占位符→宏表→区间splice)
  → texlate.translate: LLM 编排(BYOK) → 校验(独立 tree-sitter CST+规则diff) → 重译
  → texlate.compile: xelatex 主 / tectonic 便携降级 + fixloop 规则修复循环 + ctex 注入
  → 输出: zh PDF + dual 对照阅读器 + 译文缓存
Python 3.12 核心/CLI/服务端 · TS 仅 Web 前端 · AGPL 组件一律进程边界外
```

---

## 1. LaTeX 解析器 — 已定：自写，需选"参考源"

**实证**:miniscanner spike(1176 行，纯 Python 零依赖）259/259 + 32/32 陷阱 + 0.11% 泄漏 + identity 100% + 1.3ms。8 个现成库在宏展开上全灭，无可选项。**剩下的选择题只是"从谁身上抄什么"。**

| 参考源             | 抄什么                                                                                                                                                | 位置                                                                      |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **unified-latex**  | CTAN 签名表（404 宏 +128 环境 argspec `m o s d<>` xparse 风格）、受限展开 + 重解析路径、interval 重建思路                                             | `bench/ts/node_modules/@unified-latex/unified-latex-ctan/package/*/libs/` |
| **latex-utensils** | 命令族分类（专用节点表：`command.href/url/verb/label` 形状）、Peggy 文法里的命令白名单                                                                | `bench/ts/node_modules/latex-utensils/`                                   |
| **plasTeX**        | 展开层设计：mouth/gullet 分离、参数 DSL(`args='* name:cs [nargs][opt:nox] definition:nox'`)、UnrecognizedMacro 兜底、**教训：绝不加载真实 .sty/.cls** | `bench/py/.venv/lib/python3.12/site-packages/plasTeX/`                    |
| **TexSoup**        | 逐字符 tokenizer 容错顺序（转义→注释→数学→命令→文本）、position 全程可靠                                                                              | `bench/py/.venv/lib/python3.12/site-packages/TexSoup/`                    |
| **MathTranslate**  | 受限展开白名单（宏体命中 `equation/align/theorem/…` 子串才展开）、占位符两侧垫空格、腾讯 UntranslatedText API 思路                                    | `/tmp/latex-refs/MathTranslate/`                                          |
| **miniscanner**    | 全部机制：命令族表 150 行、piece 边界纪律、verbatim 先吃、宏表 env_begin/env_end 类属、`_args` 通用参数读取、子扫描器共享计数器、不动点重建           | `bench/py/miniscanner.py`                                                 |

**待决**:miniscanner 是否直接扶正为 `texlate.latex` 骨架（推荐：是，重写时顺便修 25 处残留泄漏：`$` 配对需计入保护段内 `$`、`\begin/\if` 字面残留后验重扫）。

## 2. 宏展开层 — 已定范围，待选实现策略

macro-stats 实测（39 篇）:95% 有宏（median 47)、12/39 结构性宏、**51% 在正文内定义宏**（只扫 preamble 必漏）、49% 宏体藏可译文本。

**范围定案**：六类定义（`\newcommand/\renewcommand/\def/\DeclareMathOperator/\newenvironment/\NewDocumentCommand`)+ 参数代入 + 不动点迭代 + `\input` 展平 + `\if/\else/\fi` 结构化（ifmmode/`\newif` 旗标）。**不做**:catcode/halign/active chars（损失 ≤1/39)、完整 TeX 求值器。

**待决**：展开时机——扫描中建表 + 调用点即时展开（miniscanner 现路线，推荐）vs 先建全表再二遍展开（unified-latex 路线，干净但多一遍）。前者实测已够，后者利于"定义在使用之后"的角落 case。

## 3. 译文校验器 — 已定：tree-sitter-latex + 规则 diff

- **tree-sitter-latex** `@pfoerster/tree-sitter-latex` 0.6.0(texlab 同款文法）:90/90 永不崩、1.15ms、ERROR/MISSING 节点+~35 行 CST env 配对即检出结构破坏。
- **接入方式待决**:①`tree-sitter` Python binding + 自行编译 grammar(bench 里 Python 绑定 build 失败过，TS 侧 web-tree-sitter 已验证）;②主进程内嵌 node 子进程跑校验（TS 侧已验证可行，~50 行）;③纯自写 brace/env/token diff（不依赖 CST，最简但覆盖面小）。**推荐 ②短期、③兜底**；别让一个 native 依赖卡住 uv 分发。
- **自写规则必查项**:placeholder 集合 diff（缺失/多余）、brace 平衡、`\begin/\end` env 名配对、cite/ref key 集合 diff、`$` 配对计数、译文 CJK 占比 sanity。

## 4. LLM 编排层 — 待选面最大

### 4.1 Provider 抽象（抄 texglot + ieeA)

- **texglot `provider_for_url()`**:hostname 识别 deepseek/qwen/custom + OpenAI 兼容端点参数特化，~44 行，直接可抄。BYOK 形态 = base_url + api_key + model。
- **SDK 选择**:OpenAI 兼容端点统一走 `openai` Python SDK（覆盖 DeepSeek/Qwen/火山 ark/Gemini-compat/本地网关）;Anthropic 走 `anthropic` SDK（需 cache_control 手动断点）。不要引 litellm——多一层参数透传坑（babeldoc 实测 `temperature=0` 被网关 400)。
- **本机环境**:`127.0.0.1:3003/v1` OpenAI 兼容网关存在（209 模型，babeldoc 冒烟用过 `gemini-3-5-flash-minimal`；本次查询 /models 返回空，可能需 auth header——M0 联调时确认）。

### 4.2 Prompt 缓存（成本关键，逐 provider 实测过）

| Provider        | 机制                                                          | 接入                |
| --------------- | ------------------------------------------------------------- | ------------------- |
| Anthropic       | `cache_control: {type:"ephemeral"}` 手动断点（4 个）,5min TTL | anthropic SDK       |
| OpenAI/DeepSeek | 自动前缀缓存 >1024 token                                      | 零代码              |
| 火山 Doubao     | Context API 显式建 context（省 80%）                          | 需手写 ~200 行 REST |
| 阿里百炼        | 隐式缓存                                                      | 零代码              |

**架构要求**:system prompt+ 术语表 + 占位符契约放前缀并稳定排序；ieeA 有现成 provider 缓存策略可参考

### 4.3 翻译回路（抄 LaTeXTrans，取其精华）

- **三级结构**（texglot 验证核心资产）：翻译 → 校验 → 带错误反馈重翻（`[Original]/[Translation]/[Error]` 三段式 user prompt)→ 降级。
- **Prompt 条款可抄**(LaTeXTrans prompts.py)：占位符必须原样保留放第 10 条；人名保原语；caption/section/env 各用专属 system prompt。
- **术语表**:`term_dict` 三级（user CSV > arXiv category 匹配 > default ~400-1800 行人工对）+ **`add_placeholder()` 妙技**：把全部占位符以 `ph→ph` 恒等映射灌进 glossary，占位符保护变术语硬约束。
- **LLM judge**:need_trans 判不定的 env 问 LLM(temp=0、只答 True/False、5 few-shot）泛化未知环境——我们 miniscanner 的 unknown env 可用同款。
- **并发**:`aiohttp/asyncio + Semaphore(10)` 段落级；每段完成即重写 map JSON 落盘（断点续跑 + 可观测）。

### 4.4 缓存键（抄 texglot)

`cache_key = hash(PROMPT_VERSION + base_url + model + lang + glossary_hash + paper_context_hash)`；段落级 atomic_json(tmp+rename+0600）落盘；重启校验后复用。**产品壁垒 = arXiv ID+version 命中的共享译文缓存层**。

## 5. 编译层 — 已定，细节待固化

- **主引擎 xelatex**:`-interaction=nonstopmode`，≤2 pass;**判定用 clean 阈值**(pdf 且 `'!'` 错误 ≤3),tectonic 静默降级教训——"出 PDF"≠成功。
- **tectonic 便携降级**：单二进制 10–23MB、MIT、自动拉宏包；已知边界 pstricks/PK 字体/无 Win-ARM64/bundle 快照缺文件（放文档同目录可绕）。下载要做 checksum 校验（texglot 已验证三平台分发）。
- **ctex 注入**:hjfy 实测同款 `\usepackage[fontset=windows,UTF8]{ctex}` 第 2 行注入，compile-bench 12 项目 **0% 破坏**；跨平台可换 `fontset=fandol`。
- **fixloop 规则表**(16 条已实证，yaml 化待做）:`static_precheck`(kpsewhich 预检 + 批量 tlmgr)/`install_file`/`install_tfm`/`install_sysfont`/`pdftex_prim_guard`/`px_to_bp`/`microtype_off`/`hyphenation_sane`/`soul_cjk_mbox`/`thm_sibling_strip`/`option_clash_merge`/`times_to_newtx`/`missing_pfb_updmap`/`minted_frozencache`/`latex209_reject`(→latex+dvips 路由）/`undefined_cs_guess`(→LLM 修复器兜底）。
- **`.bbl` 直消费**:42.5% 语料有 .bbl 无 .bib——编译时保留 .bbl 文件、不跑 bibtex。
- **LaTeX 2.09 路由**:`\documentstyle` → 拒绝 xelatex，走 latex+dvips 或放弃。

## 6. arXiv 接入 — 实测参数

- **e-print**:`https://arxiv.org/e-print/{id}` → 84.6% tar.gz（中位 7 文件，max 80)、15.4% 单 tex.gz。**限速 3–6s/次**、UA 必须带；list/API 页更易触发 "Rate exceeded"（封了等 60–90s)。
- **macOS bsdtar 坑**：单文件 gzipped tex 被误识为 mtree → 用 `gunzip` 不用 tar。
- **元数据**:`export.arxiv.org/api/query?id_list={id}`(Atom);category 可喂术语表匹配（LaTeXTrans 是 BeautifulSoup 抓 abs 页）。
- **HTML 降级**:`arxiv.org/html/{id}`（最新版）/ `/html/{id}v{n}`——LaTeXML 产物，覆盖率=源码，作"怪宏解析失败"时的异构降级，不省 PDF 通路。
- **批量预译**（远期）:S3 `arxiv-dataset` requester-pays；高引排序可用 citation 数据源。

## 7. 服务层 — 待选

| 组件       | 候选                                                                                                                        | 推荐与理由                                  |
| ---------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| HTTP       | **FastAPI** + uvicorn                                                                                                       | 生态/文档/SSE 成熟；texglot/hjfy 同构       |
| SSE        | sse-starlette 或裸 `StreamingResponse`                                                                                      | 逐段翻译进度；babeldoc sidecar 进度行也可用 |
| 任务队列   | ①自写 asyncio.Queue+SQLite 持久化（本地单用户够） ②**huey**(SQLite broker，无需 Redis) ③dramatiq/arq（需 Redis/服务端再引） | **M0 用 ①**，服务端化再升 ②                 |
| DB         | **SQLite**(stdlib/sqlmodel)                                                                                                 | 任务表 + 译文缓存 + 修复案例库              |
| 服务端存储 | S3 兼容（译文 PDF 共享缓存）                                                                                                | 产品壁垒所在，后置                          |

## 8. 前端 — 待选框架，形态已定

- **pdfslick**(pdfjs-dist 封装）:`@pdfslick/solid`(hjfy 同款）/ `@pdfslick/react`。**待决框架**：跟 hjfy 选 SolidJS+Zustand（轻、pdfslick 原生）vs React（生态大）。双 viewer 滚动同步需自写（scroll 事件 + 页锚映射，~100 行）。
- **三模式**:split（左右）/original/translated —— hjfy 实测形态。
- **KaTeX**:HTML 降级路线渲染数学；`marked` 渲染 MinerU markdown 对照。
- **Vite + TS + vitest**:texglot 同款工具链。
- **texglot 可抄细节**:`pdfjs.getDocument` cMapUrl/standardFontDataUrl/wasmUrl 配置、pdfjs 资产拷 dist、127.0.0.1 本地服务模式。

## 9. PDF 通路 — BabelDOC sidecar（已冒烟可行）

- **封装**:FastAPI sidecar `POST /translate`(multipart+lang+pages+dual/mono)→ tmpdir → `subprocess` 调 CLI → 回传。**150–250 行 + Dockerfile**,1–2 天。容器 2GB 内存、资产预热进镜像（`--generate-offline-assets`)、healthcheck=`--warmup`。
- **CLI 接口面**（实测）:`--files/--output/--pages/--qps/-c TOML/--no-dual/--no-mono/--watermark-output-mode no_watermark/--max-pages-per-part/--enable-process-pool/--rpc-doclayout*`;**无 stdin/stdout**；进度=stderr 行解析或按 stage 报。
- **两坑必须处理**:①`--no-send-temperature`（聚合网关兼容）;②**翻译失败静默 fallback 原文**——封装层校验 `Total tokens: 0` 或监控 `Fallback/BadRequestError` 日志。
- **可借鉴工程点**：自动术语提取（每篇先跑 term extraction)、翻译缓存、`--max-pages-per-part` 分块。
- **AGPL**:babeldoc+pdf2zh-next+PyMuPDF 全链 copyleft,**禁止 import 主进程**；输出 PDF 无 license 义务。
- **MinerU**（过渡/备选）:`mineru-api` 自带 HTTP 服务 + 三语 SDK；输出 content_list.json 带 bbox 正好喂对照阅读器；Apache-2.0+ 署名条款（需 NOTICE)。**与 babeldoc 的分工待决**:MinerU→md 轻对照 vs babeldoc→同页双语 PDF，前者便宜后者效果好。

## 10. EPUB/DOCX/分发

| 项           | 候选                                                                                                                           | 注意                                     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------- |
| EPUB         | **EbookLib 是 AGPL**(import 即污染）→ 用 stdlib `zipfile`+`lxml`/BeautifulSoup 自拆 OPF/HTML,~200 行；或 EbookLib 也走 sidecar | 翻译模式=DOM 内插译（对照式）            |
| DOCX         | **python-docx**(MIT)                                                                                                           | 段落级插译成熟                           |
| CLI 分发     | **`uv tool install texlate`**                                                                                                  | pdf2zh 同款事实标准；entry_points 单命令 |
| 桌面（远期） | **Electron+PyInstaller**(texglot 矩阵已验证：mac dmg arm64+x64 / win nsis)                                                     | 引擎=冻结后端+spawn,UI 与 web 同源       |
| Docker       | 主镜像（Python+TeXLive 或 tectonic)+ babeldoc sidecar 镜像分离                                                                 | AGPL 不混镜像                            |

## 11. License 边界表（红线）

| 可 import(MIT/Apache/BSD)                                                                                                                                                                                               | 只能进程边界外（AGPL/Copyleft)                                                   |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| fastapi/uvicorn/pydantic/openai/anthropic/aiohttp/tree-sitter/texsoup/plasTeX(LGPL?核实→用其设计不抄码）/unified-latex(MIT)/latex-utensils(MIT)/python-docx/tectonic(MIT 二进制）/pdfslick/KaTeX/lxml/bs4/sqlmodel/huey | **BabelDOC / pdf2zh / PyMuPDF / DocLayout-YOLO / EbookLib** → sidecar 或自写替代 |

> 注：plasTeX 是 **LPPL**（非 LGPL)——可以 import 但建议只抄设计；ieeA 是 GPL-3 → 只看不搬。

## 12. 下一轮待决清单（按优先级）

1. **LLM 默认模型矩阵**:M0 用哪个当 default(deepseek/qwen/gemini-flash 性价比横评：翻译质量×成本×速率，本机网关 209 模型可选）——**需要一个小 benchmark**:3 段语料×4 模型盲评。
2. **miniscanner 扶正**：直接演进 vs 按 lessons 重写（推荐后者，修 25 残留泄漏）。
3. **校验器接入**:node 子进程（短期）vs 纯自写 diff（长期）。
4. **任务队列**：自写 asyncio 起步 vs 直接 huey。
5. **前端框架**:SolidJS(pdfslick 原生+hjfy 验证）vs React。
6. **tectonic vs TeXLive 默认引擎**:M0 开发用本机 TeXLive(xelatex 已验证），分发默认 tectonic——确认 fixloop 规则在 tectonic 下的适配（tectonic 无 tlmgr,`install_*` 规则失效→降级为报错建议）。
7. **术语表 v0**：抄 LaTeXTrans `terms/*.csv` 人工对 + arXiv category 匹配，还是直接 LLM extract(BabelDOC 式 term extraction)。
8. **MinerU vs BabelDOC 分工**：过渡期 MinerU(md 对照）值不值得做，还是一步到位 babeldoc。
9. **共享译文缓存后端**：本地文件缓存先行，服务端 S3+Postgres 设计待定（含 BYOK 用户的隐私边界）。
10. **LLM 修复器**:fixloop `undefined_cs_guess` 兜底规则是接 LLM 的第一处——prompt 设计（log+ 源文件上下文→最小 patch JSON)。
