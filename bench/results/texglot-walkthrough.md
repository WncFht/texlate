# TeXGlot 代码走读报告

对象：`/tmp/latex-refs/texglot`（Mengqi-Lei/texglot v1.1.0，Apache-2.0）
形态：arXiv 链接/源码包 → 自研 TeX 分段器（**不是** pylatexenc walker）→ OpenAI 兼容 LLM 翻译 → tectonic/xelatex/lualatex 编译 → FastAPI 本地服务 + React/PDF.js 双语阅读器 + Electron+PyInstaller 桌面版。
代码量：后端 ~9.8k 行 Python，前端 ~6k 行 TS/TSX，桌面 ~600 行 CJS。

## 总体判断（先说结论）

- **最重要的纠偏**：README 说"pylatexenc 解析"，实际 pylatexenc 只用于两处边缘功能（uni2latex 字典、标题元数据渲染）。主解析是 `app/latex.py` 里 1900 行的**手写字符级 scanner**——不建 AST、不展开 TeX，直接在源码文本上按 span 切"散文段"（Segment），其余一切变成 `⟪P0000⟫` 占位符。这个设计哲学值得抄：**原文切片是唯一事实来源，模型永远拿不到生成 TeX 的机会**。
- 编译层（compiler.py 1571 行）是全仓库最有价值部分，"引擎兼容手术"做得非常细，大量规则可直接搬。
- 双语阅读器的"内容定位点同步"（named destinations + LIS 单调链 + 图像签名匹配）思路精巧，前端不复杂，值得借鉴而非照抄。
- 翻译层的"校验→反馈重试→降级修复"三级结构是核心资产；provider 抽象反而很薄（就一个 host 识别）。
- 整体工程质量偏高（防御性写法、注释解释 why、测试 30 个文件），糙点在文末列出。

---

## 1. 解析层

### 1.1 pylatexenc 的真实用法（很少）

- `app/latex.py:19-23` — `get_builtin_uni2latex_dict()` 建 `UNICODE_MATH` 表：非 ASCII 字符 → `\ensuremath{...}` 编码。**直接可抄**。
- `app/latex.py:27-37` — `render_text_symbol()`：把 Unicode 数学符号包成 `\ifdefined\cmd <编码>\else <原字符>\fi`，编译期优雅降级。**直接可抄**。
- `app/latex.py:1120-1170` — `_display_title_text()`：唯一用 `LatexWalker`/`LatexNodes2Text` 的地方，用于把 `\title{...}` 渲染成纯文本元数据。自定义 context：`add_context_category` 注入 `MacroSpec`（忽略 includegraphics/thanks/label/color/fontsize，href 取第二参数字符串，FONT_SWITCHES 全部 discard），`tolerant_parsing=False` 严格模式，未知命令直接抛错。**需改造**（作元数据提取可抄，作分段器别学）。
- **walker 配置/节点提取/宏展开：不存在。** 没有 chunk 节点树、没有宏展开——刻意为之（文件头 docstring："does not pretend to implement TeX's execution semantics"）。

### 1.2 真正的分段器 `segments()` — `app/latex.py:1479-1919`

字符级 scanner，产出 `Segment(start,end,source,masked,protected,role)`（`latex.py:228`）。masked 里散文原文、其余替换成 `⟪P%04d⟫`；`protected[]` 按序存原切片。要点：

- **遮蔽视图**：`visible_tex()`（`app/sources.py:172-223`）把注释、verbatim 类环境、`\verb`/`\lstinline` 内容替换为**等长空格**，保偏移量供正则定位；`without_comments()`（`sources.py:155-169`）同款只遮注释。**直接可抄**——所有"定位后改原文"的逻辑都建立在这个不变量上。
- **数学保护**：`$`/`$$`/`\(`/`\[`/数学环境 → `math_end()`（`latex.py:645-703`）按 token 配对，处理嵌套组、begingroup、环境别名。`collect_math_aliases()`（`latex.py:893-926`）识别 `\newcommand\x{\[...\]}` 类别名和 `\def\formula#1\stop{$#1$}` 定界参数宏（`DelimitedMath` 数据类）。**需改造但思路必抄**。
- **公式/引用保护粒度**：`MATH_ENV`/`OPAQUE_ENV`/`TEXT_COMMAND`/`OPAQUE_COMMAND`/`OPAQUE_ARGUMENTS`/`TEXT_AFTER_ARGS`/`ENVIRONMENT_ARGS`（`latex.py:184-225`）几张命令分类表是灵魂——知道 `\section{}` 的参数是散文、`\cite{}` 的参数不透明、`\multicolumn{2}` 先跳 N 个参数取第 N+1 个。**直接可抄（表内容按需要增删）**。
- **数字/标识符保护**：`put()`（`latex.py:1567-1592`）在散文内部再切出 `NAMED_IDENTIFIER`（`latex.py:62-68`，如 GPT-4、ResNet-50）和 `QUANTITY`（数字+thousand/KMBT/`5\%`），使模型无法误译数值。**直接可抄**。
- **重音单词**：`text_accents.py` 全文——把 `K\"oppen`、{\c c} 等 TeX 重音写法识别成 NFC Unicode 词，整词保护 + `accented_word_text()` 提供显示值。**需改造**（178 行自包含，可整文件搬）。
- **自定义宏推断**（可选做）：
  - `collect_text_macros`（`latex.py:859-890`）：1 参数、body 只含白名单格式命令 → 视为散文包装器。
  - `collect_literal_macros`（`latex.py:929-941`）：0 参数纯文本定义 → 值可直接给模型看（`\ie`→"i.e."）。
  - `collect_numeric_registers`/`collect_prose_arguments`（`latex.py:1173-1335`）：后者用 `TeXGlotProseParameterN` 探针 token 回灌分段器推断多参数宏哪个参数是散文。**仅参考**（非常聪明但 150 行复杂逻辑，第一期可不做）。
- **文件级决策**：`classify_source_contexts()`（`latex.py:1416-1476`）按 `\input` 边建图并传播"opaque 上下文"——被公式/tikz 环境 include 的文件及其后代不翻译；混用文件整个保留原文并告警。**直接可抄**。
- **分段出口**：`flush()`（`latex.py:1521-1565`）要求段内含 `[A-Za-z]{2,}` 或 CJK 才产出，空段丢弃；`max_chars=4500` 句末断点。**直接可抄**。

### 1.3 Segment.restore() 校验 — `app/latex.py:379-496`（翻译正确性核心）

译文返回后的多重校验，任一失败抛 ValueError 进修复流程：
- token 多重集合相等（`sorted(actual)==sorted(expected)`，`:383`）；
- **可移动性分类**（`movable_token` `latex.py:155-181`）：数字/引用/inline math/纯文本宏可以随语法重排；固定 token（结构、格式命令）必须保序（`:404-408`）；
- **scope 检查** `regions()`（`:420-455`）：`{}`/`&`/`\\`/display math 划界，可移动 token 不许跨单元格/分组/展示公式；
- `argument_boundaries()`/`whitespace_boundaries()`：格式命令与其 `{}` 之间、表格结构/空单元格里不许插入正文；
- `word_joins()`：防止模型给保护标识符拼数字尾巴；
- `escape()`（`:468-484`）：**对模型产出的散文做 LaTeX 转义**（`&%#_` 等）+ Unicode 数学符号走 `render_text_symbol`——模型被禁止输出任何 `\`（`validate_generated_prose` `latex.py:51-56`）；
- 译文长度 ≥ 原文散文 10% 的下限检查。
**整体直接可抄**——这是"翻译标记保护公式"的实现本体，比想象中严密得多。
- `validate_source_map()`（`:537-548`）编译前自检 masked↔source 互逆；`target_probe()`（`:550-572`）把译文槽位填"译文译文…"做字体兼容性预编译。**两者都直接可抄**。

---

## 2. 翻译层 — `app/llm.py`（650 行）+ `app/jobs.py`

### 2.1 Provider 抽象（薄）

- `app/providers.py:31-44` — `provider_for_url()` 按 **hostname** 识别 deepseek/qwen/custom（阿里云正则含区域域名）。不是插件架构，是"OpenAI 兼容端点 + 个别 provider 参数特化"。**直接可抄**。
- `llm.py:250-256` — 特化项：deepseek 关 thinking、qwen 关 enable_thinking、JSON 输出仅这两家支持 response_format。
- `llm.py:239-325` `complete()`：httpx AsyncClient，`/chat/completions`，3 次重试；`retry_delay()`（`llm.py:116-127`）解析 `Retry-After`（秒/HTTP-date 两种）与指数退避取 max；`finish_reason=="length"` 视为截断报错；401/402/404 立即失败、408/409/425/429/5xx 可重试；usage 缺失容错。**直接可抄**。

### 2.2 Prompt 结构 — `llm.py:336-408`

system 长 prompt（英文写、指令极细：token 语义、数字可重排但保语义角色、禁止输出 LaTeX/围栏）+ user JSON：
`{paper_context?, paragraph(masked), surrounding_source, value_tokens{token→原值}, fixed_format_order[token…], fixed_text_context{token→短格式串}, previous_validation_error?}`。
- 术语表：`Settings.glossary`（≤12000 字符）直接拼进 prompt（`llm.py:355-356`）。
- 标题段 role="title" 有专属追加 prompt（`llm.py:371-372`，连"all you need→即你所需"都写进去了）。
- `paper_context`：摘要提取见 `app/paper_context.py` 全文（沿 `\input` 图展开、上限 6000 字符、A&A 五段摘要特判）。**直接可抄**。

### 2.3 校验与三级修复 — `llm.py:420-633` + `jobs.py:580-611`

- `validate_translation_language()`（`llm.py:173-218`）：目标中文时检查 CJK 字数>0、残留英文 <80%——防模型照抄原文。**直接可抄**。
- `recover_copied_tokens()`（`llm.py:130-157`）：模型把 `$..$` 原样抄出而漏 token 时，唯一匹配则回填 token。**直接可抄**。
- 级联（`jobs.py:584-605`）：`translate()`（带 feedback 重试 ≤2 次）→ `translate_slots()`：
  - 先试 `translate_lines()`（`llm.py:573-633`）：`repair_chunks()`（`llm.py:34-109`）按句/伪代码步骤在 scope 闭合处切段，逐句重译（每句自身再有 2 次 feedback 重试 + slot 兜底）。
  - 再 `translate_slots`（`llm.py:420-571`）：散文切成 slot，模型只返回 `{"0":"译文"}` JSON 映射——**彻底不让模型碰 token 结构**；每批 8 个 slot、失败 slot 单独重问一次。
  - 全失败 → 该段保留原文 + warning（`jobs.py:605-610`）。
- `normalize_language()`：OpenCC t2s/s2t（`llm.py:160-170`）。
- `Segment.key`（`latex.py:256-285`）：sha256(source+role+masked+protected+若干版本哨兵)，prompt/mask 变更可精确失效。**直接可抄**。

### 2.4 并发与断点续传 — `app/jobs.py`

- 全局单流水线 `self.slot = asyncio.Semaphore(1)`（`jobs.py:139`）；段级 `asyncio.Semaphore(settings.concurrency)`（1–8，`jobs.py:577`）。
- 缓存：`cache-{config_hash[:16]}.json`，config_hash 含 PROMPT_VERSION+base_url+model+语言+glossary+paper_context（`jobs.py:528-541`）；每段成功即 `atomic_json` 落盘（`jobs.py:598`）；重启后校验缓存再复用（`jobs.py:560-575`）。`atomic_json`（`config.py:74-80`）tmp+rename+0600。
- 中断恢复：服务重启时 ACTIVE 任务标记 `interrupted`（`jobs.py:151-155`）；source-ready/prepared-source/original.pdf 各阶段有签名/哨兵文件跳过（`jobs.py:294-333,371-390`）。
- 预编译：`target_probe` 译文桩先跑一遍完整编译（`jobs.py:506-512`），在花钱翻译前暴露字体/模板问题。**思路直接可抄**。

---

## 3. 编译层 — `app/compiler.py`（1571 行，全文精读）

### 3.1 引擎选择与查找

- `choose_compiler()`（`compiler.py:847-858`）：`auto` 时固定顺序 **tectonic → xelatex → lualatex**，无智能探测（不论文档特征）。指定引擎缺失直接报错。**需改造**（顺序策略可议）。
- `find_compiler()`（`compiler.py:27-48`）：PyInstaller bundled → PATH（Windows 排除 .cmd/.bat）→ `DATA/tools/` → macOS `/Library/TeX/texbin`、homebrew。**直接可抄**。

### 3.2 "引擎兼容手术"清单 — `normalize_engine()`（`compiler.py:344-447`）

对每个 `.tex/.sty/.cls/...` 文件（`TEX_SOURCE_SUFFIXES`）做文本改写，仅在 tectonic/xelatex 分支：

| 手术 | 位置 | 做法 | 评价 |
|---|---|---|---|
| comment.sty 行尾 | `compiler.py:296-304` | `\end{comment}` 行尾空白/tab 清除（comment.sty 逐行比较会吃穿 EOF） | 直接可抄 |
| 浮动体位置 | `compiler.py:277-293` | `[0.5\columnwidth]` 等非法位置参数滤成合法 `htbpH!` 子集 | 直接可抄 |
| pdfTeX primitives | `compiler.py:450-494` `PDFTEX_OUTPUT_SETTINGS`+`normalize_pdftex_features` | 删 `\pdfcompresslevel/\pdfobjcompresslevel/\pdfminorversion/\pdfgentounicode/\input glyphtounicode`、`\DisableLigatures{...}`；microtype 的 `expansion/spacing/kerning`（tectonic 再+`tracking`）改写 `=false`；**替换时补换行保行号** | 直接可抄 |
| px 单位 | `compiler.py:58-60,307-341` | 仅在 dimension 参数语境把 `12px`→`12\pdfpxdimen`，文件头注 `\pdfpxdimen=65782sp`（pdfTeX 默认） | 直接可抄 |
| XeTeX 兼容块 | `compiler.py:63-85` `XETEX_COMPATIBILITY` | microtype TU `\DeclareMicrotypeSet`；breakurl 前后 hook 强 `\ifpdf`；`\PassOptionsToClass{nopdfoutputerror,allowfontchageintitle}{quantumarticle}`；pstricks 对象 `\typeout` 记录仪（编译后扫 log 报错转人工） | 直接可抄 |
| inputenc/fontenc 剥离 | `compiler.py:376-389` | `\usepackage[...,]{inputenc,fontenc,...}` 按逗号名单过滤，空则删整行（因导入时已统一转 UTF-8） | 直接可抄 |
| `\pdfinfo`/`\pdfoutput` | `compiler.py:390-401` | 删除 | 直接可抄 |
| driver 选项 | `compiler.py:403-418` | hyperref/graphicx/graphics/color/xcolor 的 `[pdftex]`→`xetex` | 直接可抄 |
| fontspec no-math | `compiler.py:369-373` | 首行前置 `\PassOptionsToPackage{no-math}{fontspec}` | 直接可抄 |
| times/mathptmx | `compiler.py:419-443` | 检测后 preamble 注 fontspec + texgyretermes/heros/cursor 的 `\ifx\rmdefault\TeXGlotLegacyTimes` 条件替换 | 直接可抄 |
| Type1 字体族 | `compiler.py:176-274` `LEGACY_LATIN_FAMILIES`+`prepare_legacy_latin_fonts` | `\usefont{OT1|T1|LY1}{ptm...}`→`{TU}{texglot-ptm}`、`\fontfamily{ptm}`→`\fontencoding{TU}\fontfamily{texglot-ptm}`；documentclass 后插 `\newfontfamily\TeXGlotLatin<name>{texgyre*-regular.otf}[NFSSFamily=texglot-<name>,BoldFont=…]` 定义块，先存再恢复 `\rmdefault` 等；跳过作者自定义 NFSSFamily | 直接可抄（ptm/phv/pcr/ppl/pbk/pnc/pag→texgyre 七族映射） |
| 遗留 CJK | `compiler.py:537-584` `normalize_legacy_cjk` | `\usepackage{CJK/CJKutf8}`→xeCJK（lualatex→luatexja-fontspec）+Fandol 四字体声明；`\begin{CJK}{UTF8}{gbsn}`→裸 `{`、`\end{CJK}`→`}` 保留分组 | 直接可抄 |
| bbm 双线体 | `compiler.py:88-97` `TECTONIC_FONT_COMPATIBILITY` | tectonic 无法生成 PK 字体：`\SetMathAlphabet{\mathbbm/mathbbmss/mathbbmtt}`→`U/dsrom/dsss`（仅 bbm 包 hook）——这就是任务里问的"字体兼容性表"本体，其实只管 bbm | 直接可抄 |
| aastex.cls 落地 | `compiler.py:497-511` `prepare_engine_sources` | tectonic 2022 bundle 的 aastex 是 1999 RC 别名：若文档 `\documentclass{aastex}` 且工程无同名 cls，把 `app/resources/tex/aastex.cls`（AASTeX 5.2 完整版）复制进工程 | 直接可抄（模式：pin 一份完整上游 cls 应对 bundle 过时别名） |
| minted 缓存 | `app/minted.py` 全文 | `.pygstyle` 旧式 `PYGdefault` 前缀 → `\let\PYG\PYGdefault` 等别名追加 | 需改造（用到 minted 缓存才需要） |
| 超高浮动体 | `compiler.py:100-127` `FLOAT_SIZING`+`prepare_float_sizing` | `\AtBeginDocument` 重定义 `\@endfloatbox`：figure/table(\*) 高度 >`\textheight` 时 `\resizebox*{!}{\textheight-\baselineskip}` 整体缩放并 `\typeout` 记录 | 直接可抄（中文论文译后变长刚需） |
| 超宽表格 | `compiler.py:130-151` `TABLE_FITTING`+`fit_tables`(587-630) | 自造 `TeXGlotFitTable` env=adjustbox `max width=\linewidth`，hook `threeparttable`；静态扫描把未手动 resizebox 的 tabular 包进去 | 直接可抄 |
| 长标识符断行 | `compiler.py:633-763` `break_long_code_identifiers` | `\texttt{aaa.bbb_ccc}` ≥24 字符时在 `.`/`_` 后插 `{\allowbreak}`，用完整 scanner 跳过定义/数学/代码环境 | 需改造 |
| 现成 .bbl | `compiler.py:766-789` `use_bundled_bibliography` | arXiv 附 .bbl 而缺 .bib → `\bibliography{...}` 换 `\input{x.bbl}` | 直接可抄 |
| 父目录错位 | `compiler.py:866-893` `rebase_project_paths` | `\input{../x.tex}` 若包内存在同名相对路径则重写 | 需改造 |
| 路径安全 | `compiler.py:896-925` `source_path_violations` | 编译前拒绝对路径/`..` 越界/`\openin|cmd` | 直接可抄 |

### 3.3 中文注入 — `prepare_chinese()`（`compiler.py:792-844`）

- 不是 ctex——**xeCJK + fontspec**（ctex 会改节名/日期/版式，docstring 明说"Font-only CJK support avoids changing template geometry"）。lualatex 走 `luatexja-fontspec`。
- 已有 `ctex*|xeCJK|luatexja*` 或已注入过 → 直接返回（`:796-805`）。
- 中文字体：**FandolSong-Regular.otf**（Bold=FandolSong-Bold、Italic=FandolKai）+ FandolHei + FandolFang——tectonic bundle 自带，零安装；日/韩用 macOS 系统字体名（Hiragino Mincho ProN / AppleMyungjo——**Win/Linux 会挂，糙点**）。
- fallback：`\xeCJKsetup{AutoFallBack=true}` + `\setCJKfallbackfamilyfont{...}[Path=texglot-fonts/]{NotoSerifCJKsc-Regular.otf}`，字体文件由 `jobs.py:410-414` 从 `app/resources/fonts/` 拷进工程 `texglot-fonts/`。
- 附加：`\emergencystretch=2em`、中文名表（摘要/参考文献/图/表/目录，简繁两表）、`\hypersetup{colorlinks=false}`。
- 注入点在 `\begin{document}` 前（`inject_preamble` `compiler.py:51-55`），不改作者 preamble。
**整体直接可抄**——这份注入块就是"如何给任意英文 arXiv 模板加中文"的最优答案。

### 3.4 编译执行 — `_compile_document()`（`compiler.py:1351-1571`）

- **tectonic 命令行**（`:1394-1416`）：`tectonic -X compile --untrusted --bundle <url> --keep-logs --keep-intermediates --outfmt pdf --makefile-rules <out>/dependencies.mk --outdir <out> --hide <settings.json> --hide <connections.json> <main.tex>`。bundle 固定 `tlextras-2022.0r0.tar`（`tectonic_bundle()` `:1121-1128`，env 可覆盖）。`--hide` 藏密钥文件、单次跑完（tectonic 自动多遍）。**直接可抄**。
- **xelatex/lualatex**（`:1417-1427`）：`-no-shell-escape -interaction=nonstopmode -halt-on-error -file-line-error -recorder -output-directory=<out>`，最多 **3 遍**；首遍后 aux 含 `\bibdata` 且有 bibtex 则中间插 bibtex（`BIBINPUTS/BSTINPUTS` 指向 cwd，`:1507-1538`）。
- **环境清洗**（`:1428-1440`）：剥 `*KEY/TOKEN/SECRET/PASSWORD*` env；`openin_any=p openout_any=p shell_escape=f`。
- **macOS 沙箱** `sandbox_command()`（`:928-975`）：sandbox-exec profile——deny `$HOME` 读、deny 全盘写，白名单 root/out/tectonic cache/tools/字体/tmp；DATA 内其他 job 目录不可读。**直接可抄（仅 darwin 生效）**。
- **进程管理**：`process_options()`/`terminate_process_tree()`（`app/platforms.py:23-30,76-108`）Win `taskkill /T /F` vs POSIX `killpg`。**直接可抄**。
- **log 处理**：stdout 截 8MB 循环读（`collect()` `:1454-1469`，顺带数 "note: downloading" 报进度）；全部写 `compile.log`；失败时筛 `error:|^!|not found|Emergency|Undefined control|Fatal` 末 5 行 + `.log` 尾 64KB 进 `CompilationError`；成功后扫最终遍 log 产出警告（Missing character/undefined references/Float too large/Float-Fit/PostScript-object→直接报错）。**直接可抄**。
- **依赖记录**：`compiled_dependencies()`（`:1041-1087`）tectonic 读 `dependencies.mk`（`makefile_inputs` 手写 Make 转义解析 + `tectonic_unescaped_inputs`）、其他引擎读 `.fls` 的 `INPUT ` 行——**用真实编译输入决定翻译哪些 .tex**，比静态 `\input` 扫描可靠（宏条件 include 也能中）。**直接可抄**。
- `probe_source_dependencies()`（`:1098-1110`）：先 `--outfmt xdv` 空跑一遍只为拿依赖表（发现 EPS 真实使用集）。贵但稳。**需改造**。
- **ToUnicode 修补** `app/pdf.py` 全文：编译后用 pypdf 给 Identity-H/V 编码、GB1 字体补 `Adobe-GB1-UCS2` ToUnicode 流——Fandol CJK 输出可搜索可复制。**直接可抄**（需带 cmap 资源文件）。

### 3.5 编译失败自动修复 — `_compile_with_recovery()`（`compiler.py:1336-1348`）

最多 3 次尝试，两条修复路径：

1. `recover_compile_configuration()`（`:1263-1333`）——主文档级：
   - log 含 `__um_group_begin:`/`Extended mathchar used as mathchar`（unicode-math 与老数学宏冲突）且模板是 `\ifPDFTeX...\else\usepackage{unicode-math}` 双引擎分支、全文无显式 unicode-math 用法 → 把分支里的 `{unicode-math}` 改 `{fontspec}`（保留传统数学 + Unicode 文本）。
   - `Bibliography not compatible with author-year` → `\PassOptionsToPackage{numbers}{natbib}`。
   - `Option clash for package X` → 从 error 位置文件里抓 X 已有选项合并 `\PassOptionsToPackage{旧+新}{X}` 前置到文档首行。
2. `recover_external_package()`（`:1191-1260`）——bundle 包级（tectonic 专属）：
   - 从 `error: xxx.sty:LINE: Undefined control sequence` + tex_log `l.LINE \pdfxxx` 精确定位 bundle 包里的 pdfTeX primitive；
   - 用隔离 `Tectonic.toml` 工程 + `tectonic -X bundle cat --only-cached <name>` 取出**该 bundle 内原始包文件**（`:1131-1188`）；
   - 删除 `PDFTEX_OUTPUT_SETTINGS` 匹配行（保行号），写备份 `<name>.texglot-original` + 附 SHA256 头的修改版进工程目录 shadow 掉 bundle 版。
   - 防呆：本地已有同名文件不覆盖、行号必须对上、>1MB 资源拒绝。
**两者都直接可抄**——"log 驱动定点修复"是它在真实 arXiv 语料上存活的关键。

### 3.6 EPS 处理 — `app/graphics.py`（521 行）

- 两路：有 XDV 依赖记录时按 `used_images` 精确集合转；否则静态分析（`graphics_context` 收集 `\graphicspath/\input@path/\DeclareGraphicsExtensions`+0 参数宏字典，作用域外/重定义/`let` 标记 ambiguous，解析不出就报错拒猜）。
- ghostscript `-dSAFER -dBATCH -sDEVICE=pdfwrite -dEPSCrop` 转 PDF（`find_ghostscript` `:71-85` 含 Windows ProgramFiles 搜索），逐张超时 120s、单页校验。
- **重定向黑科技** `redirect_compiled_eps()`（`:20-68`）：不改 `\includegraphics`，注入 expl3 代码 hook `\Gin@setfile`——按 eps 文件 **md5** 查 prop 表换成转换后 PDF。 parameterized 宏、同名文件全免疫。**直接可抄**。

---

## 4. Tectonic 分发 — `scripts/install_compiler.py`（121 行）

- 矩阵 `ASSETS`（`:18-39`）：**Win x64 / macOS arm64+x64 / Linux x64+arm64**（musl 静态版），VERSION=`0.17.0`，每平台硬编码 sha256。
- 流程（`:57-91`）：`urlopen`（90s 超时，150MB 上限读全量）→ sha256 校验（不符不装）→ zip/tar.gz 内找唯一 `tectonic[.exe]` 成员 → 写 `<dest>/tectonic.download` → chmod 755 → `replace` 原子改名 → `--version` 自检。
- `--if-missing` 先 `available_compilers()` 探测（`:100-106`）。
- **无 fallback**：单一下载源（GitHub releases），无重试、无镜像、无断点续传——校验和是亮点，网络韧性是糙点。
- `build_desktop.py:146-150` 打包时复用 `install()` 到 `tools/` 再 `--add-binary`。**整体直接可抄**。

---

## 5. 双语阅读器 — `frontend/src/`（React 19 + pdfjs-dist 6.3 + Vite）

**架构**：后端 `app/reader.py` 出 `ReaderData{documents{side:{version(sha256),pages}}, annotations, alignment, reading}`；前端两个 `PdfPane` 各自渲染一份 PDF，`readerNavigation.ts` 的 `createPositionMapper` 做位置换算。

- **PDF 渲染** `PdfPane.tsx`：
  - `pdfjs.getDocument({url, cMapUrl:"/pdfjs/cmaps/", cMapPacked:true, standardFontDataUrl, wasmUrl})`（`:356-362`），worker 用 `?url` 导入（`:10`）；vite.config 把 pdfjs-dist 的 cmaps/standard_fonts/wasm 拷进 `dist/pdfjs/` 由 FastAPI 挂静态目录（`main.py:327`）。
  - 开文档先批量取每页 `viewport.height/width` 比例（8 页/批，`:370-383`）→ 连续滚动容器里每页占位等高宽，`IntersectionObserver` rootMargin 700px 虚拟化挂载 `PageCanvas`（`:196-203`）。
  - canvas 渲染：backing store 比例 `min(dpr, 2, sqrt(5e6/(w*h)))` 限内存（`:102-106`）；`pdfjs.TextLayer` 提供可选文字层；**双缓冲换帧**——新页 pixels+textLayer 都好了才 `replaceChildren`，防旧页闪显（`:126-133`）。**直接可抄**。
- **对齐后端** `app/alignment.py`：
  - 两份 PDF 的 `named_destinations` 交集配对（hyperref 的 `section.*`/`figure.*`/`cite.*` 等 ID 翻译后不变）；`priority()` 权重 section=12 > figure/table=10 > equation=4 > cite=2，`page.*`/`Doc-Start`/footnote 排除（`:47-58`）。
  - `destination_position()`：`/Top`/`/Left` + `/Rotate` → `{page, fraction(页内纵向比例)}`（`:27-44`）。
  - `ordered_pairs()`（`:61-96`）：**最大权重单调链（加权 LIS）**，丢弃浮动/乱序锚点——同一链双向用，滚动不回退。**直接可抄**。
  - `figure_alignment.py`：对 `figure.*` 锚点所在页，遍历内容流 `q/Q/cm/Do` 计算 XObject 实际绘制区域；Form 用流 sha256、Image 用"排序 metadata+原始压缩字节"签名匹配同一图 → `regions` 对，让跨节浮动的图也能点对点同步（`:60-175`）。**仅参考**（精巧但重）。
- **前端映射** `readerNavigation.ts:17-141`：每侧 `heights[]` 前缀和 → 连续坐标轴；`pairs` 作折点分段线性插值；命中 `regions` 唯一匹配时按图内比例映射；无对齐齐退回页码+页内比例。`captureViewport` 取视口 20% 处为阅读线（`:173-187`）。**直接可抄**。
- **同步滚动**：`PdfReader.tsx:526-547`——用户滚一侧（rAF 节流 + `generation` 代次 + `ignoreTop` 1px 防回声环 `PdfPane.tsx:499-516`）→ `mapper` 算对侧位置 → `jump()`。模式切换/缩放变化先 `capturePositions` 再映射恢复（`:184-224`）。
- **批注**：textLayer TreeWalker 逐 text node 交 range → `getClientRects` 归一化 + `mergeRects` 合行（`readerGeometry.ts:35-90`）；存 `reader.json`（不写回 PDF），`document_version` 绑定防错位，revision 乐观锁（`app/reader.py:151-197`）。
- **阅读位置持久化**：`ReadingState{positions,mode,zoom,sync,left}` 700ms 防抖 PUT + `pagehide` keepalive 兜底（`PdfReader.tsx:326-363`）。

---

## 6. 桌面版 — `desktop/` + `scripts/build_desktop.py`

- **架构**：Electron 壳（main.cjs 140 行）spawn **PyInstaller onedir 冻结后端** `texglot-engine`（= app.server + CLI 双入口，`desktop/engine.py`）；浏览器 UI 与桌面共用同一 FastAPI 服务（127.0.0.1），前端 dist 打进引擎 `app/web`。
- **服务发现** `desktop/service.cjs:55-112`：8765 起扫 20 端口；先 health 探测 `{name=="TeXGlot", data_dir 匹配}` 且版本一致→**复用已有服务**（`owned:false`），否则 spawn `--engine-server --port N --parent-pipe`（stdin EOF 看门狗：父进程死→服务自杀，`app/server.py:31-42`）。150×200ms 健康轮询。**直接可抄**。
- **PyInstaller 参数**（`build_desktop.py:151-192`）：`--onedir --console --collect-submodules app,uvicorn --collect-data opencc,certifi --add-data frontend/dist:app/web --add-data app/resources --add-binary tectonic:tools --exclude-module tkinter,pytest,PIL`。**直接可抄**。
- **Electron 安全**（`main.cjs:30-48`）：sandbox+contextIsolation+无 nodeIntegration、`setWindowOpenHandler` deny+外链走系统浏览器、`will-navigate` 限 service origin、权限全拒。
- **打包矩阵**：electron-builder → mac dmg（arm64+x64）、win nsis x64（`perMachine:false, allowElevation:false`，无需管理员）。CI `desktop.yml`：windows-latest + macos-15-intel 两 runner，构建后 `smoke_platform.py`（本地 model stub 的端到端翻译验证，328 行）+ Windows 真安装包验证。Linux 桌面无（`build_desktop.py:124-125` 明示只 macOS/Windows）。
- **更新** `updates.cjs`：GitHub releases latest（API 超限退化 `releases/latest` HEAD 重定向解析）→ `SHA256SUMS.txt` 校验下载 → `shell.openPath` 让用户手动装（未签名无法自动更新）。**需改造**。
- **license 聚合** `build_desktop.py:42-110`：从校验过的 Electron zip 抽 LICENSES.chromium.html + importlib.metadata 收集 Python 依赖 license + Tectonic license → THIRD_PARTY_NOTICES.txt。**直接可抄**。

---

## 7. 代码质量评价与坑

**做得好的**：防御性注释解释了每个 why；"masked view 保偏移"一处抽象撑起所有改写；编译 recovery 只修诊断定位到的东西；密钥 env 清洗 + `--hide` + macOS 沙箱多层设防；缓存 key 版本哨兵（`text-accents-v1` 等）精细失效。

**糙点/隐患**：
1. `app/latex.py:533` `word_joins` 里 `assert run is not None`——`AssertionError` **不是** ValueError，`jobs.py:595` 的修复循环接不住，会直接打挂整个任务（尽管前面校验使触发概率低）。
2. `jobs.py:598` 每翻完一段就 `atomic_json` 全量写缓存 dict——段数 N 则 O(N²) IO，几千段的论文会明显抖动。
3. `prepare_chinese`（`compiler.py:806-808`）日/韩注入 macOS 专名 Hiragino Mincho ProN/AppleMyungjo，Windows/Linux 必编译失败（但 find_main 的 `language_rank` 又偏好拉丁字母文档，日韩目标语言实用性本来就低）。
4. `install_compiler.py` 下载无重试/无镜像；`urlopen` 读环境代理但没显式处理。
5. `fit_tables`（`compiler.py:591`）`\begin{table}.*?\end{table}` 非嵌套正则，table 环境嵌套会错切（罕见）。
6. `choose_compiler` auto 恒 tectonic 优先——装了完整 TeXLive 的用户反而走 bundle 下载路线；且 tectonic bundle 版本硬绑 2022。
7. `sandbox_command` 只在 macOS 生效；Windows/Linux 编译仅靠 `--untrusted`+env 白名单，保护明显弱。
8. `segments()` 主体在**原始 text**（含注释）上扫，靠每处判断注释——与它自己的 `visible_tex` 抽象并存，读代码时容易踩坑；注释会作为 protected token 原样回写（模型看不到注释内容）。
9. `restore()` 10% 长度下限对"纯公式标题"类段可能误伤，但配合 validate_source_map 预检风险可控。
10. 前端 `PdfPane` 每页 `getPage` 预热比例是串行批次，特大文档（>200页）打开偏慢；`ratios` 全量渲染 placeholder DOM 不虚拟化列表本身。
11. `recover_external_package` 往工程目录写 shadow 包——与 `prepare_engine_sources` 的 aastex 落地同款思路，但会把"非作者文件"混进导出 zip（可接受）。
12. `config.py:148` `merge_settings` 里 `Settings(base_url=...)` 只为过 validator 构造临时对象——能跑但可读性差。

**整体结论**：编译层（`compiler.py`+`graphics.py`+`pdf.py`）与分段/校验层（`latex.py` 的 Segment 体系）是可以大面积"直接可抄"的两块；翻译层抄结构与校验思路即可，prompt 自行迭代；阅读器抄 `alignment.py`+`readerNavigation.ts` 的映射模型；桌面架构（服务发现+parent-pipe+PyInstaller 参数）直接可抄。
