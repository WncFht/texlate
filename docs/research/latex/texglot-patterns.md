# texglot 深度阅读：可复用模式目录

> **结论**：TeXGlot 与 texlate 形态几乎全重合（Python/FastAPI 管线 + pdfjs 双栏对照阅读器 + 便携 tectonic 分发 + Electron 壳），最值得整体搬走四块——visible_tex 屏蔽视图驱动的源码归一化手术包、named-dest 锚点滚动同步、双层缓存键、tectonic 钉版分发与编译沙箱。
> **状态**：时点证据（2026-09-15 口径，对照 TeXGlot v1.1.0 源码；归一化层/锚点同步/段缓存等主项已落地，各节注记）
> **日期**：2026-09-15

调研对象为 TeXGlot[^texglot] v1.1.0 源码树；下文 `file:line` 均指该版本内路径，供复核与二次挖掘。一个先验校正：任务预想的「[Original]/[Translation]/[Error] 三段式带错重翻」在其代码中不存在——等价物是结构化 JSON 字段 `previous_validation_error` / `slot_validation_failures`（§7），比对话式错误描述更稳。

## 1. 搬运裁决（按性价比排序）

1. **源码归一化层**（`app/compiler.py::normalize_engine`）：把 pdfTeX 时代源码改写为 XeTeX/tectonic 可编译形态的完整手术包——剥 inputenc/fontenc、改 `\pdfoutput`、驱动选项 pdftex→xetex、OT1/T1 字体族→fontspec+TeXGyre、px→`\pdfpxdimen`、microtype 不支持选项降级、legacy CJK→xeCJK。全部在注释屏蔽视图 `visible_tex()` 上定位、在原文上做 span 替换——这是最值得抄的元方法（§2.0）。
   → 已落地为 `compile/normalize.py`（其 docstring 明示移植自 normalize_engine 系）；错误驱动的条件改写按分工铁律留给 `compile/fixloop/`（pdftex_prim_guard/px_to_bp/microtype_off 等，见 `fixloop-rules.md`）。
2. **滚动同步方案**：不做文本对齐，利用 hyperref named destinations 在重编译后保留同名锚点（section/figure/cite）——后端 pypdf 提取锚点页内坐标 + 最大权值单调链，前端在「归一化累计页高」坐标系里线性插值（`app/alignment.py` + `frontend/src/readerNavigation.ts`）。可行性实证见 `alignment-probe.md`。
   → 已落地为 `align.py` → `dual.json`（figure region 匹配同思路）。
3. **段级缓存键**：`Segment.key` = sha256(源文本 + role + 失效标签 + masked/protected 快照），文件级键 = sha256(prompt_version+base_url+model+lang+glossary+context)；改 prompt 只作废应作废的段（§4）。
   → 已落地为 server `translation_cache` 表 `{cfg_hash}:{seg_key}` + `xlat/state.py` 批级断点续翻（键组分按 texlate 契约改造）。
4. **tectonic 分发 + 编译沙箱**：五平台 sha256 钉死矩阵 + `--untrusted` + `openin_any=p` + macOS sandbox-exec 白名单 profile + 子进程环境洗密钥（§6、§2.6）。
   → 沙箱与能力面思想落地为 `compile/sandbox.py` 及 fixloop caps；tectonic 钉版分发属桌面分发形态，texlate 走已装引擎探测未采纳（Electron 壳 roadmap 已裁决不做）。

**反面**：单 job 全局串行、每段整文件重写缓存、api_key 明文落盘、无鉴权本地 HTTP、i18n 中间件改写 JSON 响应——见 §8。

## 2. 源码归一化层（`app/compiler.py` 引擎兼容手术）

### 2.0 方法论：visible_tex 屏蔽视图 + 原文 span 替换（最该抄的元模式）

所有正则定位都打在「注释/逐字环境被等长空格遮盖」的视图 `visible_tex()` 上（offset 保持），然后把 `(start,end,replacement)` 按逆序应用到原文。遮盖时 `\n` 保留、其余字符变空格——**行号不变**，诊断信息仍能对回源码（`app/sources.py:172-223`：先遮 verbatim/Verbatim/lstlisting/minted/filecontents/comment 环境，再遮 `\verb` 与行内 `%` 注释）。这是陷阱规避的基石——`%` 在 `\verb|%|` 里不是注释；归一化层必须坚持「定位视图 ≠ 改写目标」两分，编辑列表统一 `sorted(edits, reverse=True)` 回放（`app/compiler.py:241-243`）。texlate `compile/normalize.py` 与 `textutil/mask.py` 即此模式的落地形。

### 2.1 preamble 注入锚点与兼容前导块

`inject_preamble`（`compiler.py:51-55`）把所有兼容性前导块统一插在 `\begin{document}` 前（定位走 masked view）；字体系定义块例外，插在 `\documentclass{...}` **之后**（利用 `group_end` 找类名右括号，`:268-271`）。五个前导块：

- **PIXEL_COMPATIBILITY**（`:58-60`）：pdfTeX 的 `px` 单位在 XeTeX 不存在，补 `\ifdefined\pdfpxdimen\else\newdimen\pdfpxdimen\pdfpxdimen=65782sp\fi`。
- **XETEX_COMPATIBILITY**（`:63-85`）：① microtype 只开 TU/EU1/EU2 的 protrusion set（`package/microtype/after` hook）；② breakurl 载入前暂存 `\ifpdf` 强制 `\iftrue`、载入后恢复；③ `\PassOptionsToClass{nopdfoutputerror,allowfontchageintitle}{quantumarticle}`——该类假定非 pdfTeX 都出 DVI；④ pstricks hook：`\pst@object` 包一层 `\typeout{TeXGlot-PostScript-object: ...}`，编译后扫日志发现用过 PSTricks 就报错提示转 PDF（`:1559-1562`）。
- **TECTONIC_FONT_COMPATIBILITY**（`:88-97`）：tectonic 不能生成 PK 字体，把 bbm 的 `\mathbbm/\mathbbmss/\mathbbmtt` 经 `\AddToHook{package/bbm/after}` 重绑到向量字体 dsrom/dsss。
- **FLOAT_SIZING**（`:100-127`）：`\AtBeginDocument` 重定义 `\@endfloatbox`，超高 float 用 `\resizebox*` 缩到 `\textheight-\baselineskip` 并 `\typeout` 回读日志；只在存在 figure/table 时才注入。
- **TABLE_FITTING**（`:130-151`）：`TeXGlotFitTable` 环境 = `adjustbox{max width=\linewidth}`，hook 到 threeparttable；`fit_tables()` 给译文阶段超宽 table 套壳。

### 2.2 `normalize_engine()` 主编排（`:344-447`）

顺序：normalize_comment_terminators → normalize_float_positions →（tectonic/xelatex 时）normalize_pdftex_features → normalize_pixel_dimensions → 按需前插兼容块 → `\PassOptionsToPackage{no-math}{fontspec}` 前插 → 剥 inputenc/fontenc → 删 `\pdfinfo{}` → 删 `\pdfoutput=1` → 驱动选项 pdftex→xetex → times/mathptmx 字体替换 → normalize_legacy_cjk。

三个改写细节值得照抄：

- **剥 inputenc/fontenc**（`:377-389`）：不整行删，解析 `\usepackage[..]{a,b,c}` 名字列表只剔掉 `{inputenc,fontenc}`，其余包保留；剔空则换成 `\n`。
- **驱动选项 pdftex→xetex**（`:403-418`）：只改 hyperref/graphicx/graphics/color/xcolor 可选参数里的独立 `pdftex` token；注释明示定位用 masked view 但**绝不能把 masked view 拷回去**（会把注释行变空行、断跨行参数）。
- **times/mathptmx→TeX Gyre**（`:420-444`）：暂存 `\rmdefault` 等 → `\usepackage{fontspec}` → 默认族仍是 ptm/phv/pcr 才 `\setmainfont{texgyretermes-regular.otf}[...]`。

### 2.3 OT1/T1/LY1→TU 字体族改写（`prepare_legacy_latin_fonts`，`:176-274`）

映射表 `ptm→texgyretermes, phv→texgyreheros, pcr→texgyrecursor, ppl→texgyrepagella, pbk→texgyrebonum, pnc→texgyreschola, pag→texgyreadventor`。两条正则：`\usefont{OT1|T1|LY1}{ptm...}` → 编码改 TU、族名加 `texglot-` 前缀；`\fontfamily{ptm...}` → 族名加前缀 + 补 `\fontencoding{TU}`；**自定义 NFSS 族跳过**（先全项目收集 `\DeclareFontFamily{TU}{...}` 与 `NFSSFamily=`）。定义块插到 `\documentclass{}` 后：暂存默认族 → `\RequirePackage[no-math]{fontspec}` → 每个用到的族 `\newfontfamily\TeXGlotLatin{ptm}{texgyretermes-regular.otf}[NFSSFamily=texglot-ptm,BoldFont=...]` → 恢复默认族。**不改作者的默认字体，只给显式 Type1 选择提供 Unicode 等价物**——尺度拿捏值得抄。

### 2.4 pdfTeX 特性降级（`normalize_pdftex_features`，`:450-494`）

`PDFTEX_OUTPUT_SETTINGS` 整段删除：`\pdfcompresslevel/objcompresslevel/minorversion/majorversion/optionpdfminorversion/gentounicode` 赋值与 `\input glyphtounicode`。microtype 的 `expansion/spacing/kerning`（tectonic 再加 `tracking`）逐 option 解析 `key=value` 改写为 `xxx=false`，删除位补回换行——**所有删除保持行号稳定**，错误可回溯源文件行号。

### 2.5 其它归一化

- `normalize_comment_terminators`（`:296-304`）：`\end{comment}` 行尾空白剥掉——comment.sty 按整行比对，行尾 tab 会让它吞到 EOF。
- `normalize_float_positions`（`:277-293`）：float 位置参数里非法字符剥掉（如 `[!htbp^]`）。
- `normalize_pixel_dimensions`（`:307-341`）：只在尺寸参数语境（includegraphics 的 width/height、`\setlength/\hspace/\rule/\hskip` 等）把 `Npx` 改成 `N\pdfpxdimen`——语境受限替换，不是全局 sed。
- `normalize_legacy_cjk`（`:537-584`）：`\usepackage{CJK|CJKutf8}` 换 xeCJK+Fandol（lualatex 换 luatexja-fontspec）；`\begin{CJK}{..}{..}`/`\end{CJK}` 换成 `{`/`}` 保留分组去 8-bit 编码。
- `prepare_chinese`（`:792-844`）：目标语言非英文时注入 xeCJK + FandolSong/Hei/Fang 全套 + `AutoFallBack` + Noto CJK fallback（随包字体目录）+ `\emergencystretch=2em` + 中文名重定义 + `\hypersetup{colorlinks=false}`；**自带 Fandol/Noto 字体进工程目录**，不依赖系统字体。
- `use_bundled_bibliography`（`:766-789`）：`\bibliography{...}` 引用的 .bib 缺失时，若包内有现成 `.bbl` 就改成 `\input{xxx.bbl}`。
- `rebase_project_paths`（`:866-893`）：`\input/../foo.tex` 越界引用剥掉 `../` 后在包内找同路径文件改写成正确相对路径。
- `prepare_minted_cache`（`app/minted.py:9-48`）：老 minted 缓存定义 `\PYGdefault`、新的要 `\PYG`，在 .pygstyle 尾追加 `\let` 别名块。

### 2.6 编译执行与恢复

`choose_compiler`（`:847-858`）auto 顺序 tectonic→xelatex→lualatex。`_compile_document`（`:1351-1571`）：tectonic 命令行带 `--untrusted --bundle <url> --keep-logs --keep-intermediates --makefile-rules --outdir --hide <settings.json> --hide <connections.json>`——`--hide` 把含密钥配置对编译隐藏；经典引擎 `-no-shell-escape -interaction=nonstopmode -halt-on-error -file-line-error -recorder`；环境变量**过滤名字含 KEY/TOKEN/SECRET/PASSWORD 的变量**再加 `TECTONIC_UNTRUSTED_MODE=1 openin_any=p openout_any=p shell_escape=f`；macOS sandbox-exec profile = deny 家目录读 + deny 所有写，再按白名单放行工程/输出/缓存目录（`:928-975`）；超时 `asyncio.wait_for` + `terminate_process_tree`（POSIX `killpg` / Windows `taskkill /T /F`）；依赖记录用编译器自述产物——tectonic 读 `--makefile-rules`、经典引擎读 `.fls` 的 INPUT 行——**用真实依赖决定翻译哪些 .tex，而不是静态猜 `\input`**；失败时日志尾部 64KB 进 `CompilationError.tex_log`。

带诊断自动修复重试 `_compile_with_recovery`（`:1336-1348`，最多 3 次）：unicode-math 在老式数学宏上炸 → 模板 `\ifPDFTeX` 分支降级 fontspec；natbib author-year 不兼容 → `\PassOptionsToPackage{numbers}{natbib}`；`Option clash for package X` → 汇总已用选项前置。`recover_external_package`（`:1191-1260`）：bundle 内宏包踩 pdfTeX 原语 → `tectonic -X bundle cat --only-cached` 捞原文件本地打补丁，写 `xxx.sty.texglot-original` 备份 + SHA256 头注——**对上游包的修复留原文 + 指纹**。`embed_cjk_mappings`（`app/pdf.py:9-58`）：编译完给 Identity-H/Adobe-GB1 的无 ToUnicode 字体注入内置 cmap，让 tectonic 出的中文 PDF 可复制可搜索（texlate 对应物 = `compile/cjkmap.py` + `compile/cmaps/` GB1 资产）。EPS：`prepare_eps`（`app/graphics.py`）Ghostscript `-dSAFER -sDEVICE=pdfwrite -dEPSCrop` 转 pdf，依赖宏展开的用 xdv 预编译探真实引用。

## 3. BYOK provider 抽象（`app/providers.py`，全文件 44 行）

`provider_for_url()` 按 hostname 特化：`api.deepseek.com`→deepseek，dashscope 各域 + `*.maas.aliyuncs.com` 区域形态→qwen，其余→custom。配套 `PROVIDERS` 预设表（name/base_url/model/placeholder/docs 五元组）；文件 docstring 点明原则——**「Provider recognition is based on trusted API hosts, never the model name alone」**。消费点：`Translator.complete()` 按 provider 加私有字段（deepseek `thinking={type:disabled}`、qwen `enable_thinking=false`、两者支持 `response_format json_object`）；`load_settings()` 按 provider 读对应环境变量；`provider_options()` 按 provider 从 connections.json 找回该 host 上次存的 key。URL 校验：禁 query/fragment/userinfo（防 key 泄进 URL）、http 只允许 localhost、宽容剥 `/chat/completions` 后缀。

→ texlate 落地形不同：`xlat/client.py` 走 dialect（auto/openai/anthropic/responses）+ `server/providers/` 预设，BYOK 凭据只进内存 `Secrets` 不落盘——「按 host 不认 model」原则保留，host→provider 映射换成了显式 dialect 参数。

## 4. 缓存键与落盘

**文件级键**（`app/jobs.py:528-542`）：`cache-{sha256(json{version,base,model,language,glossary,paper_context,context_guidance})[:16]}.json`——`PROMPT_VERSION`（`llm.py:30`，形如 `texglot-optional-context-v5`）语义变就 bump，注释明示「mask 变化只作废受影响段」。每个产物 schema 各有版本常量（`SOURCE_PREPARATION_VERSION`/`TITLE_METADATA_VERSION`/`alignment.VERSION`）。

**段级键**（`Segment.key`，`app/latex.py:256-285`）：material = 源文本（非 paragraph 段前置 role）+ **按需失效标签**——源文含 accent 命令追加 `\0text-accents-v1`、含 text 声明追加 `\0text-declarations-v1`、protected 含数量/单位追加 `\0quantity-units-v1`、有字面宏值追加 `\0literal-macros-v1`+repr；最后必附 `\0source-map-v1\0` + masked/protected 快照 repr。**token 布局变了 key 就变，masking 规则升级时只有受影响段缓存作废**——细粒度失效的教科书写法。粒度：一个 Segment = 一个 cache entry，value 是模型原始输出（restore 前）。

**落盘容错**：`atomic_json`（`config.py:74-80`）tmp+rename+0600；缓存读入逐条再校验（类型/语言/restore，任一步炸了就弹掉重翻——缓存条目不盲信）；损坏文件 rename 成 `*-invalid-<rand>.json` 隔离不删；每段成功即整表重写（崩溃只丢当前段，但 O(n²) IO 见 §8）；arXiv 下载 `.part`→`replace`；`project_signature` 用 prepared source 全树 sha256 做编译产物可复用凭据。

## 5. 前端与滚动同步（核心可抄块）

**pdfjs 装配**：`getDocument` 三件套 `cMapUrl/standardFontDataUrl/wasmUrl` 指向 `/pdfjs/`；vite `closeBundle` 插件把 `node_modules/pdfjs-dist/{cmaps,standard_fonts,wasm}` 拷进 dist 并聚合 THIRD_PARTY_LICENSES；后端 StaticFiles 挂载（`PdfPane.tsx` + `vite.config.ts` + `main.py:321-327`）。渲染细节：先批量取 `getViewport({scale:1})` 高宽比排 placeholder 再虚拟化；`IntersectionObserver rootMargin:"700px 0px"` 近屏才渲染；`ratio = min(devicePixelRatio, 2, sqrt(5_000_000/(w*h)))` 限显存；新帧 canvas+textLayer 齐才 `replaceChildren`；URL 带 `?version=<sha256>`，重编译后不吃旧缓存且后端可对 stale version 回 409。

**后端锚点提取**（`app/alignment.py`）：hyperref 给 section/figure/cite/equation 生成 named destination，同源重编译名字不变 → 同名 dest 即天然对照锚点（`page.*`/`Doc-Start` 等页码锚刻意排除）；`destination_position` 取页号 + `/Top`/`/Left` 得页内纵坐标 fraction（处理 90/180/270 旋转）；`ordered_pairs` 对所有同名锚点跑**最大权值单调链 DP**（x、y 严格递增才入链）剔除乱序浮动锚点，权重 section 系 12 > 图表 10 > equation 4 > cite 2；`match_figure_regions`（`app/figure_alignment.py`）对 figure/subfigure 锚点页解析 content stream 的 `q/Q/cm/Do`，按签名匹配双侧同一插图得页内 `[start,end]` region——**图 float 漂移后滚动跟图不跟文**。产物 `{kind, heights, pairs, regions, documents: versions}`。

**前端位置映射**（`readerNavigation.ts`）：每页高宽比累加成「归一化全书纵轴」，锚点映成该轴坐标；position→二分找相邻 landmark→线性插值→映回对侧 (page,fraction)。退化防护三件：版本不符置 null、pairs 非严格单调降级同页同 fraction、figure region 命中按 region 内比例映射。阅读焦点线 = `scrollTop + viewportHeight*0.2`；`ignoreTop` 抑制程序化滚动回声；位置持久化 700ms debounce + `pagehide` keepalive 兜底。

→ 已落地：`align.py::build_alignment` 产 `dual.json`（同源同名 dest 配对 + 单调链 + 归一化插值 + regions），实证基础见 `alignment-probe.md`；前端 SolidJS+pdfslick 栈不同但映射模型照搬。

## 6. tectonic 分发（`scripts/install_compiler.py`，121 行）

版本钉死 `VERSION="0.17.0"`；五平台资产矩阵（win-x64 zip / darwin-arm64 / darwin-x64 / linux-x64-musl / linux-arm64-musl）各带 sha256；URL 形如 GitHub releases `tectonic@{VERSION}` tag 资产。`install()`：`urlopen(timeout=90)` 读 ≤150MB+1 → sha256 校验失败整体拒绝 → 归档里**只提 tectonic 单文件**（member basename 匹配且恰好一个）→ 写 `tectonic.download` → chmod 0o755 → `replace()` 原子落位。查找顺序 `find_compiler`（`compiler.py:27-48`）：PyInstaller `_MEIPASS/tools` → `shutil.which`（win 拒 .cmd/.bat）→ DATA/tools → mac 追加 texbin/homebrew。宏包 bundle 也钉版本默认 `tlextras-2022.0r0.tar`，env 可覆盖；桌面打包复用同一 `install()`（「never bundle an unknown PATH executable」）。**没做 PGP/sigstore 验签，sha256 是唯一信任锚**——照搬时留意。

## 7. Electron 打包（texlate 不采纳，留档参考）

进程模型：`requestSingleInstanceLock`；Chromium profile 与文档目录分离；`BrowserWindow` 全锁（nodeIntegration:false, contextIsolation:true, sandbox:true）；外链一律 `shell.openExternal` + `setWindowOpenHandler deny` + `will-navigate` 非同源拦截；权限请求全拒。`startService()`：端口扫描 preferred..+20 先打 `/api/health`，`matchingService` 要求 `ok && name=='TeXGlot' && data_dir` canonical 相等——同库已在跑就复用不 spawn；版本不符报 `different-service-version`；spawn `--engine-server --port N --parent-pipe`；就绪探测 150×200ms 轮询；关停阶梯 stdin EOF（后端 watchdog 收）→15s→taskkill/SIGKILL。本地服务模式同款思路在 `app/server.py`：`service.lock` flock 单 owner → 自己 `socket.bind` 再交 uvicorn（先占端口再加载 JobManager）；`TrustedHostMiddleware` 限 localhost 防 DNS rebinding；写请求校验 `Origin==host` 且 `sec-fetch-site!=cross-site`。

打包面：PyInstaller `--onedir --collect-submodules app,uvicorn --add-binary tectonic:tools` 产 engine-dist，electron-builder `extraResources` 进 `resources/engine`；CI matrix win+mac 先测前端/后端/桌面再 `smoke_platform.py` 冒烟冻结引擎，Windows 还真跑安装器冒烟。自更新只查不装：下载前校验 release `asset.digest`/SHA256SUMS，install 前再验一次；renderer 不能传 URL/路径（`event.senderFrame` origin 校验）。

## 8. 翻译回路（翻译→校验→带错重翻）

**段级重试阶梯**（`jobs.py:580-611`）：整段翻 ×2（`feedback` 携带上轮 ValueError 文本）→ `translate_slots` 兜底；`ProviderError`（服务不可用）抛出整 job 失败重跑，`ValueError`（结构校验）只记该段、三振后保留原文 + warning（任务 `partial` 状态）。并发 `asyncio.Semaphore(settings.concurrency)`，异常 cancel 全部。

**请求结构**（`llm.py:327-418`）：system prompt 讲清 `⟪P0000⟫` 是受保护 token 每个恰好出现一次；`value_tokens`（可动：数字/行内公式/引用/人名宏）可按目标语语法换序但语义角色不变，给了数字错位反例；文档视为不可信数据防注入。user content 是 JSON：`{paper_context?, paragraph(masked), surrounding_source?, value_tokens{token→原文≤350字符}, fixed_format_order, fixed_text_context, previous_validation_error}`——**反馈不是对话式「你错了」，而是校验异常字符串进字段**。`recover_copied_tokens`：模型把受保护原文抄回来而没用 token 时，原文在输出里唯一出现才替换回 token——只修 exact+unique。`validate_translation_language`：中文目标时散文段（≥8 拉丁词且 ≥2 虚词）译文 CJK 为 0 → 报错；英文词残留 >80% 且 CJK <15% → 报错。`normalize_language`：OpenCC 兜底简繁。

**结构校验**（`Segment.restore`，`latex.py:379-496`）：token 多重集相等；词粘连检查防「RoBERTa→RoBERTas」；fixed token 相对顺序不变；`\textbf{` 类命令与参数间不许插正文；scope/cell 区域签名比对（`{}/[]/&/\\/\begin` 嵌套帧序列两版一致）；空白边界对不许插字；译文长度 ≥10% 源文；只对生成散文做 LaTeX 转义（`\{}$&%#_^~` 映射 + Unicode 数学符号→`\ensuremath`）。`validate_source_map`：付费翻译前先自证 masked→protected→source 可逆；`target_probe` 把英文词换成译文样本做**免费预检编译**，确认字体兼容再花钱翻（texlate 对应物 = `compile/probe.py`）。

**兜底 slots 模式**（`translate_slots`，`llm.py:420-571`）：段落按受保护 token 切开，散文片段编号 `⟪S0000⟫`，要求 JSON `{slot_id: 译文}`（`response_format json_object`）；每 8 槽一批，失败槽只重问失败那批并附 `slot_validation_failures{slot:reason}`；槽校验拒空/非字符串/保护标记/LaTeX 围栏；已接受槽不再改。槽前还有 `translate_lines`→`repair_chunks` 一级：闭合 scope 边界按句号/伪代码关键字切段重翻，粒度介于整段与槽之间。→ texlate 落地为 `xlat/retry.py` 阶梯 + `validate/l0.py` 结构校验 + `[n]` 批协议 reconcile（`xlat/batch.py::parse_batch_response`），思想同源、字段化反馈保留。

**HTTP 层**（`Translator.complete`，`llm.py:239-325`）：401/403→认证错、402→余额、404→地址/模型错、408/409/425/429/5xx→重试 ≤2 次（`retry_delay` 读 Retry-After 数字或 HTTP-date，>60s 不等）、其余 4xx→拒绝；`finish_reason=="length"`→截断错；usage 可缺省不记账；TransportError/SSLError 指数退避；`redact()` 把 `settings.api_key` 与 `sk-*` 模式抹出错误信息。

## 9. 反面清单（别抄的地方）

| 位置                            | 问题                                                         | 评价                                                                                  |
| ------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| `jobs.py:56-57`、`config.py:18` | import 时 `mkdir`，import 副作用                             | texlate 延迟到服务启动                                                                |
| `jobs.py:139,263`               | `Semaphore(1)` 包住整条 pipeline                             | 全局一次只跑一个 job；texlate worker 用 `asyncio.Queue` 串行任务但不锁段级并发        |
| `jobs.py:597-598`               | 每翻完一段把整个 cache dict 重写一遍                         | O(n²) IO；texlate 用 SQLite `translation_cache` 表天然解决                            |
| `config.py:74-80`               | tmp 名固定 `.tmp`                                            | 同路径并发写会撞（靠 slot=1 掩盖）；tmp 名应带 uuid                                   |
| `jobs.py:109-111`               | `except(...): pass` 静默吞错                                 | 至少记 log                                                                            |
| `llm.py:221-224`                | `redact` 只抹 `sk-*` 和自己的 key                            | 别家 key 形态照样进日志；texlate `logredact.py` 做 provider 无关脱敏                  |
| `compiler.py:1431`              | env 过滤按子串 KEY/TOKEN/SECRET/PASSWORD                     | 误伤 `MONKEY`/`KEYSTONE` 等；正向做法是白名单 env                                     |
| `main.py:53-60`                 | 本地 API 无鉴权，只靠 Origin/Sec-Fetch-Site + TrustedHost    | 本机任意进程可 curl `/api/jobs`；texlate server 模式另有 401 鉴权（`server/auth.py`） |
| `main.py:69-93`                 | i18n 中间件对每个 `/api` JSON 响应读全 body 重序列化查表翻译 | 英文 UI 依赖后端中文原文不漂移——脆耦合；应返回 error code 由前端翻                    |
| `desktop/package.json`          | mac ad-hoc 签名 + `hardenedRuntime:false`                    | dmg 下载者要绕 Gatekeeper；公发必须正签 + 公证                                        |
| `llm.py:336-347`                | 每段请求都带 ~400 词 system prompt                           | 无 prompt caching 意识；texlate glossary/prompt 设计考虑了前缀缓存命中                |
| `jobs.py:528-541`               | cache 文件按 config hash 命名但永不清理                      | `cache-*.json` 无限累积；texlate 需 GC 策略（当前同样遗留）                           |
| `config.py:164`                 | api_key 明文存 settings.json（0600）                         | BYOK 常态取舍但要承认；texlate 选择 key 不落盘（内存 `Secrets`）                      |
| `figure_alignment.py:51-57`     | 图形签名用原始压缩字节                                       | 两次编译 flate 字节不保证一致；应对解码后内容或图像 hash                              |
| `PdfReader.tsx`（1200 行）      | 单组件巨石：阅读器 + 批注 + 同步 + 持久化                    | texlate 前端照 `readerNavigation.ts` 纯函数剥离方式写                                 |
| `jobs.py:302-304`               | `shutil.rmtree` 直接删目录无软删                             | 风险低但重试路径多；texlate 用哨兵文件做段级幂等                                      |

值得一提的「糙但有担当」：翻译失败的段保留原文并把任务标 `partial` 而非 `failed`，配合 cache 可断点续翻——方向对，texlate 继承此语义（`delivered` 口径）。

## 附：texlate 复用对照

| texlate 模块    | texglot 源                                                                   | 落地形                                                                                                                      |
| --------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| 源码归一化      | `compiler.py:344-447` + `sources.py:172-223` visible_tex + 五个前导块        | `compile/normalize.py` + `textutil/mask.py`；条件改写归 fixloop                                                             |
| BYOK provider   | `providers.py` + `llm.py:250-256` 方言点                                     | `xlat/client.py` dialect + `server/providers/`；key 不落盘                                                                  |
| 段缓存          | `latex.py:256-285` + `jobs.py:528-598` + `config.py:74-80`                   | `translation_cache` 表 + `xlat/state.py`                                                                                    |
| 对照阅读器      | `alignment.py` + `figure_alignment.py` + `readerNavigation.ts`               | `align.py` → `dual.json`；SolidJS 前端                                                                                      |
| tectonic 分发   | `install_compiler.py` + `compiler.py:27-48,1121-1128`                        | 未采纳（非桌面分发形态）                                                                                                    |
| 桌面壳          | `service.cjs` + `build_desktop.py` + electron-builder                        | 未采纳（roadmap 裁决不做 Electron）                                                                                         |
| 翻译回路        | `jobs.py:580-611` + `llm.py:378-408` + `latex.py:379-496` + `llm.py:420-571` | `xlat/retry.py` + `validate/l0.py` + `[n]` 批协议                                                                           |
| 编译沙箱        | `compiler.py:928-975` + `:1428-1440`                                         | `compile/sandbox.py` + fixloop caps                                                                                         |
| 防注入/路径安全 | `compiler.py:896-925` + `sources.py:48-73`                                   | `server/upload.py` 安全解包（底层引擎 `arxiv/unpack.py`）+ `textutil/osutil.py` `safe_resolve`/`safe_is_file`/`safe_is_dir` |

### 参考文献

[^texglot]: Mengqi Lei. TeXGlot v1.1.0 — local LaTeX translation pipeline (FastAPI + pdfjs + tectonic + Electron). GitHub. [github.com/Mengqi-Lei/texglot](https://github.com/Mengqi-Lei/texglot)
