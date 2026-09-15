# texglot 深度阅读：可复用模式目录

> 阅读对象：`tmp/refs/texglot/`（TeXGlot v1.1.0，下文所有 `file:line` 均相对该目录）。
> 与 texlate 形态几乎完全重合：Python(FastAPI) 管线 + React/pdfjs 双栏对照阅读器 + PyInstaller 冻结后端 + Electron 壳 + 便携 tectonic 分发。

## 结论先行

**最值得整体搬走的四块**（按性价比排序）：

1. **`app/compiler.py` 的"源码归一化层"** — `normalize_engine()` 是把 pdfTeX 时代源码改写为 XeTeX/tectonic 可编译形态的完整手术包：剥 inputenc/fontenc、改 `\pdfoutput`、pdftex→xetex 驱动选项、OT1/T1 字体族 → fontspec+TeXGyre、px→`\pdfpxdimen`、microtype 不支持选项降级、legacy CJK→xeCJK。**全部在注释屏蔽视图 `visible_tex()` 上定位、在原文上做 span 替换**，这是它最值得抄的方法论（见 §1.0）。
2. **滚动同步方案** — 不做文本对齐，而是利用 **hyperref named destinations 在重编译后天然保留同名锚点**（section/figure/cite），后端 pypdf 提取锚点页内坐标 + 最大权值单调链，前端在"归一化累计页高"坐标系里线性插值。优雅且可测试（`app/alignment.py` + `frontend/src/readerNavigation.ts`）。
3. **段级缓存键设计** — `Segment.key` = sha256(源文本 + role + 失效标签 + masked/protected 快照），文件级键 = sha256(prompt_version+base_url+model+lang+glossary+context)。双层结构使得改 prompt 只作废应作废的部分（§3）。
4. **tectonic 分发 + 编译沙箱** — 5 平台 sha256 钉死矩阵 + `--untrusted` + `openin_any=p` + macOS sandbox-exec 白名单 profile + 子进程环境变量洗密钥（§5、§1.7）。

**翻译回路注意**：任务里提到的 "[Original]/[Translation]/[Error] 三段式"在 texglot 中**不存在**。它的带错重翻是把上一轮 `ValueError` 文本塞进请求 JSON 的 `previous_validation_error` / `slot_validation_failures` 字段（§7），比我们预想的更结构化。

**反面**：单 job 全局串行、每段整文件重写缓存、api_key 明文落盘、无鉴权本地 HTTP、i18n 中间件整体改写成 JSON 响应——见 §8。

---

## 1. `app/compiler.py` 引擎兼容手术（源码归一化层）

### 1.0 方法论：visible_tex 屏蔽视图 + 原文 span 替换（最该抄的元模式）

- **做什么**：所有正则定位都打在"注释/逐字环境被等长空格遮盖"的视图 `visible_tex()` 上（offset 保持），然后把 `(start,end,replacement)` 按逆序应用到原文。遮盖时 `\n` 保留、其余字符变空格 → **行号不变**，诊断信息仍能对回源码。
- **file**：`app/sources.py:172-223`（visible_tex：先遮 verbatim/Verbatim/lstlisting/minted/filecontents/comment 环境，再遮 `\verb` 和行内 `%` 注释）；`app/sources.py:155-169`（without_comments 简化版）。
- **texlate 用法**：这是陷阱规避的基石——`%` 在 `\verb|%|` 里不是注释。我们的归一化层也应坚持"定位视图 ≠ 改写目标"两分，编辑列表统一 `sorted(edits, reverse=True)` 回放（`app/compiler.py:241-243`）。

### 1.1 preamble 注入锚点

- **file**：`app/compiler.py:51-55`

```python
def inject_preamble(text: str, block: str) -> str:
    marker = re.search(r"\\begin\s*\{document\}", visible_tex(text))
    if not marker:
        return text
    return text[: marker.start()] + block + text[marker.start() :]
```

- **texlate 用法**：所有兼容性前导块统一走这一个注入点（`\begin{document}` 前），不要往 `\documentclass` 前塞——但注意 §1.4 的字体系定义块反而是插在 `\documentclass{...}` **之后**（利用 `group_end` 找类名右括号，`app/compiler.py:268-271`）。

### 1.2 XeTeX/tectonic 兼容前导块（原文摘录）

- **PIXEL_COMPATIBILITY**（`app/compiler.py:58-60`）——pdfTeX 的 `px` 单位在 XeTeX 不存在，补一个固定 dimen：

```tex
% texglot: pdfTeX pixel dimensions for XeTeX
\ifdefined\pdfpxdimen\else\newdimen\pdfpxdimen\pdfpxdimen=65782sp\fi
```

- **XETEX_COMPATIBILITY**（`app/compiler.py:63-85`）——四件事：① microtype 只开 TU/EU1/EU2 的 protrusion set（`\AddToHook{package/microtype/after}`）；② breakurl 载入前暂存 `\ifpdf` 并强制 `\iftrue`，载入后恢复（`package/breakurl/before|after` hook）；③ `\PassOptionsToClass{nopdfoutputerror,allowfontchageintitle}{quantumarticle}`——quantumarticle 假定非 pdfTeX 都出 DVI；④ pstricks hook：把 `\pst@object` 包一层 `\typeout{TeXGlot-PostScript-object: ...}`，编译后扫日志发现用过 PSTricks 就报错提示转 PDF（`app/compiler.py:1559-1562`）。
- **TECTONIC_FONT_COMPATIBILITY**（`app/compiler.py:88-97`）——tectonic 不能生成 PK 字体，把 `bbm` 包的 `\mathbbm/\mathbbmss/\mathbbmtt` 重绑到向量字体 `dsrom/dsss`：

```tex
\AddToHook{package/bbm/after}{%
\SetMathAlphabet{\mathbbm}{normal}{U}{dsrom}{m}{n}%
...}
```

- **FLOAT_SIZING**（`app/compiler.py:100-127`）：`\AtBeginDocument` 重定义 `\@endfloatbox`，超高 float 用 `\resizebox*` 缩到 `\textheight-\baselineskip`，并 `\typeout{TeXGlot-Float-Fit:...}` 供日志回读。**只在存在 figure/table 环境时才注入**（`prepare_float_sizing`, `app/compiler.py:154-173`）。
- **TABLE_FITTING**（`app/compiler.py:130-151`）：定义 `TeXGlotFitTable` 环境 = `adjustbox{max width=\linewidth}`，hook 到 `threeparttable`；`fit_tables()`（`app/compiler.py:587-630`）给译文阶段超宽 table 内的 tabular 套壳。

### 1.3 `normalize_engine()` 主编排（`app/compiler.py:344-447`）

顺序：`normalize_comment_terminators` → `normalize_float_positions` →（tectonic/xelatex 时）`normalize_pdftex_features` → `normalize_pixel_dimensions` → 按需前插 PIXEL/XETEX/TECTONIC_FONT 兼容块 → `\PassOptionsToPackage{no-math}{fontspec}` 前插 → **剥 inputenc/fontenc** → 删 `\pdfinfo{}` → 删 `\pdfoutput=1` → 驱动选项 pdftex→xetex → times/mathptmx 字体替换 → `normalize_legacy_cjk`。

关键改写原文：

**剥 inputenc/fontenc**（`app/compiler.py:377-389`）——不整行删，而是解析 `\usepackage[..]{a,b,c}` 的名字列表，只剔掉 `{inputenc,fontenc}`，其余保留：

```python
for match in re.finditer(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}", visible
):
    names = [v.strip() for v in match[1].split(",")]
    kept = [v for v in names if v not in {"inputenc", "fontenc"}]
    if kept != names:
        value = (
            text[match.start() : match.start(1)] + ",".join(kept) + "}"
            if kept
            else "\n"
        )
        removals.append((match.start(), match.end(), value))
```

**删 `\pdfinfo{...}` 和 `\pdfoutput=1`**（`app/compiler.py:393-401`）：

```python
for match in re.finditer(r"\\pdfinfo\s*\{", visible):
    removals.append((match.start(), group_end(visible, match.end() - 1), "\n"))
...
for match in reversed(
    list(re.finditer(r"\\pdfoutput\s*=?\s*1\b", visible_tex(text)))
):
    text = text[: match.start()] + " " + text[match.end() :]
```

**驱动选项 pdftex→xetex**（`app/compiler.py:403-418`）——只改 hyperref/graphicx/graphics/color/xcolor 的可选参数里的独立 `pdftex` token；注释特别说明：定位用 masked view，但**绝不能把 masked view 拷回去**（会把注释行变空行、断跨行参数）。

**times/mathptmx → TeX Gyre**（`app/compiler.py:420-444`）：检测到 `\usepackage{times|mathptmx}` 时注入一段：暂存 `\rmdefault` 等 → `\usepackage{fontspec}` → 若默认族还是 ptm/phv/pcr 就 `\setmainfont{texgyretermes-regular.otf}[...]` 等。

### 1.4 OT1/T1/LY1 → TU 字体族改写（`prepare_legacy_latin_fonts`，`app/compiler.py:176-274`）

- 映射表（`app/compiler.py:176-184`）：`ptm→texgyretermes, phv→texgyreheros, pcr→texgyrecursor, ppl→texgyrepagella, pbk→texgyrebonum, pnc→texgyreschola, pag→texgyreadventor`。
- 两条正则（`app/compiler.py:216-217`）：
    - `\usefont{OT1|T1|LY1}{ptm...}` → 编码改 `TU`、族名加 `texglot-` 前缀（两处 span 编辑）；
    - `\fontfamily{ptm...}` → 族名加前缀 + 前面补 `\fontencoding{TU}`；**自定义 NFSS 族跳过**（先全项目收集 `\DeclareFontFamily{TU}{...}` 和 `NFSSFamily=`，`app/compiler.py:212-214`）。
- 然后生成定义块插到 `\documentclass{}` 后（`app/compiler.py:246-265`）：暂存 `\rmdefault/\sfdefault/\ttdefault` → `\RequirePackage[no-math]{fontspec}` → 每个用到的族 `\newfontfamily\TeXGlotLatin{ptm}{texgyretermes-regular.otf}[NFSSFamily=texglot-ptm,BoldFont=...,ItalicFont=...,BoldItalicFont=...,SlantedFont=...,BoldSlantedFont=...]` → 恢复默认族。**它不改作者的默认字体，只给显式 Type1 选择提供 Unicode 等价物**——尺度拿捏值得抄。

### 1.5 pdfTeX 特性降级（`normalize_pdftex_features`，`app/compiler.py:450-494`）

- `PDFTEX_OUTPUT_SETTINGS`（`app/compiler.py:450-453`）整段删除：

```python
re.compile(
    r"(?:\\global\s*)?\\(?P<control>pdf(?:compresslevel|objcompresslevel|minorversion|majorversion|optionpdfminorversion|gentounicode))\s*=?\s*\d+\b"
    r"|\\input\s*(?:\{glyphtounicode(?:\.tex)?\}|glyphtounicode(?:\.tex)?\b)"
)
```

- microtype 的 `expansion/spacing/kerning`（tectonic 再加 `tracking`）选项改写成 `xxx=false`，逐 option 解析 `key=value`，保留行数不变（`app/compiler.py:473-493`：`replacement += "\n" * (...)` 补回换行数——**所有删除都保持行号稳定**，方便错误回溯源文件行号）。

### 1.6 其它归一化

- `normalize_comment_terminators`（`app/compiler.py:296-304`）：`\end{comment}` 行尾空白剥掉——comment.sty 按整行比对，行尾 tab 会让它吞到 EOF。
- `normalize_float_positions`（`app/compiler.py:277-293`）：float 位置参数里非法字符剥掉（如 `[!htbp^]`）。
- `normalize_pixel_dimensions`（`app/compiler.py:307-341`）：只在尺寸参数语境（includegraphics 的 width/height、`\setlength/\hspace/\rule/\hskip...`）把 `Npx` 改成 `N\pdfpxdimen`——**语境受限替换**，不是全局 sed。
- `normalize_legacy_cjk`（`app/compiler.py:537-584`）：`\usepackage{CJK|CJKutf8}` 换成 `xeCJK`+Fandol 字体（lualatex 换 luatexja-fontspec）；`\begin{CJK}{..}{..}`/`\end{CJK}` 换成 `{`/`}` 保留分组去掉 8-bit 编码。
- `prepare_chinese`（`app/compiler.py:792-844`）：目标语言非英文时往主文件 preamble 注入 xeCJK + FandolSong/Hei/Fang 全套 + `AutoFallBack` + Noto CJK fallback（随包字体目录 `texglot-fonts/`）+ `\emergencystretch=2em` + `\AtBeginDocument` 重定义 `\abstractname/\refname/\figurename...` 中文名 + `\hypersetup{colorlinks=false}`。**自带 Fandol/Noto 字体进工程目录**（`app/jobs.py:409-413`），不依赖系统字体。
- `use_bundled_bibliography`（`app/compiler.py:766-789`）：`\bibliography{...}` 引用的 .bib 缺失时，若 arXiv 附了现成 `.bbl` 就改成 `\input{xxx.bbl}`。
- `rebase_project_paths`（`app/compiler.py:866-893`）：`\input/../foo.tex` 越界引用，剥掉 `../` 后在包内找同路径文件则改写成正确相对路径。
- `prepare_minted_cache`（`app/minted.py:9-48`）：老 minted 缓存定义 `\PYGdefault`、新的要 `\PYG`，在 .pygstyle 尾追加 `\let\PYG...\PYGdefault...` 别名块。

### 1.7 编译执行与恢复

- `choose_compiler`（`app/compiler.py:847-858`）：auto 顺序 tectonic→xelatex→lualatex。
- `_compile_document`（`app/compiler.py:1351-1571`）：
    - tectonic 命令行（`app/compiler.py:1396-1416`）：`-X compile --untrusted --bundle <url> --keep-logs --keep-intermediates --outfmt pdf --makefile-rules <out>/dependencies.mk --outdir <out> --hide <settings.json> --hide <connections.json> <main>`——`--hide` 把含密钥的配置文件对编译隐藏；
    - 经典引擎：`-no-shell-escape -interaction=nonstopmode -halt-on-error -file-line-error -recorder`；
    - 环境变量（`app/compiler.py:1428-1440`）：**过滤掉名字含 KEY/TOKEN/SECRET/PASSWORD 的变量**，再加 `TECTONIC_UNTRUSTED_MODE=1 openin_any=p openout_any=p shell_escape=f`；
    - macOS 沙箱（`sandbox_command`, `app/compiler.py:928-975`）：sandbox-exec profile = deny `$HOME` 读 + deny 所有写，再按白名单放行工程目录/输出目录/tectonic 缓存/字体；**settings.json、浏览器 profile、SSH key 编译期不可读**；
    - 超时 `asyncio.wait_for` + `terminate_process_tree`（`app/platforms.py:76-108`，POSIX `killpg` / Windows `taskkill /T /F`）；
    - 依赖记录：tectonic 读 `--makefile-rules` 产物（`makefile_inputs`/`tectonic_unescaped_inputs` 解析 Make 转义，`app/compiler.py:978-1038`），经典引擎读 `.fls` 的 `INPUT` 行（`compiled_dependencies`, `app/compiler.py:1041-1087`）——**用编译器自述的真实依赖决定翻译哪些 .tex**，而不是静态猜 `\input`；
    - 失败时从日志提取 hints（`app/compiler.py:1484-1492`），tex_log 尾部 64KB 进 `CompilationError.tex_log`。
- **带诊断的自动修复重试**（`_compile_with_recovery`, `app/compiler.py:1336-1348`，最多 3 次）：
    - `recover_compile_configuration`（`app/compiler.py:1263-1333`）：unicode-math 在老式数学宏上炸 → 把模板的 `\ifPDFTeX...\else\usepackage{unicode-math}` 分支降级成 fontspec（仅限无显式 unicode math 时）；natbib author-year 不兼容 → `\PassOptionsToPackage{numbers}{natbib}`；`Option clash for package X` → 汇总该包已用选项 `\PassOptionsToPackage` 前置；
    - `recover_external_package`（`app/compiler.py:1191-1260`）：bundle 内宏包踩了 pdfTeX 原语 → 用 `tectonic -X bundle cat --only-cached <file>` 把原文件捞出来，本地打补丁（同 PDFTEX_OUTPUT_SETTINGS 策略），写 `xxx.sty.texglot-original` 备份 + SHA256 头注。**对上游包的修复留原文 + 指纹**，很讲究。
- `embed_cjk_mappings`（`app/pdf.py:9-58`）：编译完给 Identity-H 编码、Adobe-GB1 的无 ToUnicode 字体注入内置 `Adobe-GB1-UCS2` cmap——**让 tectonic 出的中文 PDF 可复制可搜索**。
- EPS：`prepare_eps`（`app/graphics.py:393-470`+）用 Ghostscript `-dSAFER -dBATCH -sDEVICE=pdfwrite -dEPSCrop` 转 .eps→.pdf，依赖宏展开的用 xdv 预编译探真实引用（`probe_source_dependencies`, `app/compiler.py:1098-1110`）。

---

## 2. `provider_for_url()` — hostname→provider 特化

- **file**：`app/providers.py:31-44`（全文 44 行，整文件即 BYOK 抽象）：

```python
def provider_for_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host == "api.deepseek.com":
        return "deepseek"
    if host in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    } or re.fullmatch(
        r"[a-z0-9-]+\.(?:cn-beijing|ap-southeast-1|ap-northeast-1|eu-central-1|cn-hongkong)\.maas\.aliyuncs\.com",
        host,
    ):
        return "qwen"
    return "custom"
```

- 配套：`PROVIDERS` 预设表（`app/providers.py:6-28`，name/base_url/model/placeholder/docs 五元组）；文件 docstring 点明原则——**"Provider recognition is based on trusted API hosts, never the model name alone"**（`app/providers.py:1`）。
- 消费点：`Translator.complete()` 按 provider 加私有字段（`app/llm.py:250-256`：deepseek `thinking={type:disabled}`，qwen 系 `enable_thinking=false`，两者支持 `response_format json_object`）；`load_settings()` 按 provider 读对应环境变量（`app/config.py:86-91`：`DEEPSEEK_API_KEY`/`DASHSCOPE_API_KEY`）；`provider_options()` 按 provider 从 `connections.json` 找回该 host 上次存的 key（`app/config.py:106-129`）。
- URL 校验（`app/config.py:34-50`）：禁 query/fragment/用户名密码（防止把 key 泄进 URL）、http 只允许 localhost、`removesuffix("/chat/completions")` 宽容。
- **texlate 用法**：BYOK 抽象直接照这个形状抄——`hostname → provider_id → {请求体方言, env key 名, 文档链接}` 三级。texlate 大概率要加 OpenAI/Anthropic/Gemini/兼容网关，注意它"按 host 不认 model"的原则。

---

## 3. 缓存键与落盘

### 3.1 缓存文件键（config 级）

- **file**：`app/jobs.py:528-542`

```python
config_hash = hashlib.sha256(
    json.dumps(
        {
            "version": PROMPT_VERSION,
            "base": settings.base_url,
            "model": settings.model,
            "language": settings.target_language,
            "glossary": settings.glossary,
            "paper_context": context,
            "context_guidance": settings.context_guidance,
        },
        sort_keys=True,
    ).encode()
).hexdigest()
cache_path = folder / f"cache-{config_hash[:16]}.json"
```

- `PROMPT_VERSION`（`app/llm.py:30`）：`"texglot-optional-context-v5"`——prompt 语义变了就 bump，注释里明确说"mask 变化只作废受影响段，恢复改进只对新/未缓存工作生效"。配套版本常量：`SOURCE_PREPARATION_VERSION`（`app/jobs.py:59`）、`TITLE_METADATA_VERSION`（`app/jobs.py:60`）、`alignment.VERSION`（`app/alignment.py:16`）——**每个产物的 schema/语义都有自己的版本号**。

### 3.2 段级缓存键（`Segment.key`，`app/latex.py:256-285`）

```python
material = (
    self.source if self.role == "paragraph" else self.role + "\0" + self.source
)
if re.search(r"\\[\"'`^~=.]", self.source):
    material += "\0text-accents-v1"
if any(re.search(r"\\" + name + r"\s*\{", self.source) for name in TEXT_DECLARATIONS):
    material += "\0text-declarations-v1"
if any(re.fullmatch(NUMBER + MAGNITUDE, v) or re.fullmatch(NUMBER, v) and "," in v
       for v in self.protected):
    material += "\0quantity-units-v1"
used = [(v, self.literal_value(v)) for v in self.protected
        if self.literal_value(v) is not None]
if used:
    material += "\0literal-macros-v1" + repr(used)
material += "\0source-map-v1\0" + repr((self.masked, self.protected))
return hashlib.sha256(material.encode()).hexdigest()
```

- **要点**：key 不只是源文本——含 role、masked/protected 快照（token 布局变了 key 就变），再加**按需失效标签**（该段含 accent/声明/数量级时追加对应 tag）——masking 规则升级时只有受影响段的缓存作废，没影响的全保留。这是"细粒度失效"的教科书写法。
- 粒度：**一个 Segment = 一个 cache entry**，value 是模型原始输出（restore 前），见 `app/jobs.py:596-598`。

### 3.3 落盘与容错

- `atomic_json`（`app/config.py:74-80`）——tmp+rename+0600 标准件：

```python
def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(temp, path)
```

- 缓存读入时**逐条再校验**（`app/jobs.py:560-573`）：`isinstance str` → `normalize_language` → `validate_translation_language` → `item.restore()`，任何一步炸了就 `cache.pop(key)` 重翻——缓存条目不盲信。
- 损坏文件隔离不删（`app/jobs.py:544-558`）：JSON 解析失败 → rename 成 `cache-xxx-invalid-<rand>.json` 保留诊断。
- 每段成功即 `atomic_json(cache_path, cache)`（`app/jobs.py:597-598`）——崩溃只丢当前段（但实现粗糙，见 §8）。
- job.json 同样 atomic_json（`app/jobs.py:165-167`）；arXiv 下载 `.part`→`replace`（`app/sources.py:287,319`）；工程签名 `project_signature`（`app/jobs.py:120-132`）把"prepared source 全文件树 sha256"作为编译产物可复用的凭据（`app/jobs.py:371-391`）。
- **texlate 用法**：三层全抄——config 级 hash 文件名 + 段级 key 内含 masked/protected 快照和失效 tag + atomic_json(tmp,0600,replace)。改进点：缓存写放大（§8）。

---

## 4. 前端（pdfjs / 对照 / 同步 / 本地服务）

### 4.1 pdfjs 装配

- **worker + getDocument**（`frontend/src/PdfPane.tsx:10,26,356-362`）：

```ts
import workerURL from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjs.GlobalWorkerOptions.workerSrc = workerURL;
...
const loader = pdfjs.getDocument({
  url,
  cMapUrl: "/pdfjs/cmaps/",
  cMapPacked: true,
  standardFontDataUrl: "/pdfjs/standard_fonts/",
  wasmUrl: "/pdfjs/wasm/",
});
```

- **资产拷 dist**：`vite.config.ts:7-21` 自定义插件 `local-pdf-resources` 在 `closeBundle` 里 `cpSync node_modules/pdfjs-dist/{cmaps,standard_fonts,wasm} → dist/pdfjs/`；顺手把 5 个依赖的 LICENSE 聚成 `dist/THIRD_PARTY_LICENSES.txt`。后端 mount：`app/main.py:321-327`（`/assets`、`/pdfjs` 挂 StaticFiles；找不到 dist 就回退 `app/web` 即 PyInstaller 包内路径）。
- pdfjs-dist `^6.3.289`（`frontend/package.json:14`）；API 是新版：`new pdfjs.TextLayer({textContentSource, container, viewport})`（`PdfPane.tsx:119-124`）。
- **texlate 用法**：三件套（cMapUrl/standardFontDataUrl/wasmUrl）+ closeBundle 拷资产 + FastAPI 静态挂载，直接照搬。

### 4.2 渲染管线细节（PdfPane.tsx）

- 先批量取每页 `getViewport({scale:1})` 高宽比（8 页一批，`PdfPane.tsx:368-384`），全文档先排 placeholder 再虚拟化渲染；
- `IntersectionObserver rootMargin:"700px 0px"`（`PdfPane.tsx:196-203`）——近屏才渲染 PageCanvas；
- DPR/显存上限：`ratio = min(devicePixelRatio, 2, sqrt(5_000_000/(w*h)))`（`PdfPane.tsx:102-107`）；
- 帧切换原子化：新帧 canvas+textLayer 都好了才 `replaceChildren`（`PdfPane.tsx:127-133`），渲染中 doc/page 变了直接丢弃（`current()` 守卫，`PdfPane.tsx:87-93`）；
- URL 带 `?version=<sha256>`（`PdfPane.tsx:353`）——PDF 重编译后浏览器不吃旧缓存，后端还能对 stale version 回 409（`app/main.py:275-280`）。

### 4.3 双栏对照与滚动同步（核心）

**后端锚点提取**（`app/alignment.py`）：

- 原理：LaTeX/hyperref 给 section/figure/cite/equation 生成 named destination，**同一源码重编译后名字不变** → 同名 dest 即天然对照锚点。`page.*`、`Doc-Start` 等页码锚点刻意排除（`app/alignment.py:1-5,47-58`）。
- `destination_position`（`app/alignment.py:27-44`）：取 dest 页号 + `/Top`/`/Left` → 页内纵坐标 fraction（处理了 90/180/270 旋转）。
- `ordered_pairs`（`app/alignment.py:61-96`）：把所有同名锚点按"原文页序 + 权重+id"排序后跑**最大权值单调链 DP**（x、y 都严格递增才入链）——剔除跨章乱序的浮动锚点，得到保序 landmark 序列。权重：section 系 12 > 图表 10 > equation 4 > cite 2。
- `match_figure_regions`（`app/figure_alignment.py:125-175`）：对 `figure.*/subfigure.*` 锚点页，解析 content stream 的 `q/Q/cm/Do`，按签名（Form stream 数据 / Image 元数据 + 流字节 sha256）匹配双侧同一插图 → 得到页内 `[start,end]` region。**图 float 漂移后滚动跟图不跟文**。
- 产物 `{"kind": "landmarks"|"pages", "heights", "pairs", "regions", "documents": versions}`（`app/alignment.py:99-128`）；`cached_alignment` lru_cache。

**前端位置映射**（`frontend/src/readerNavigation.ts`）：

- `createPositionMapper`（`readerNavigation.ts:17-141`）：把每页高宽比累加成"归一化全书纵轴"（`starts`），锚点映射成该轴坐标；position→坐标→二分找相邻 landmark→线性插值→映回对侧 (page,fraction)。三种退化都做了防护：版本不符置 null（`readerNavigation.ts:22-28`）、pairs 非严格单调则降级为同页同 fraction（`readerNavigation.ts:84-90,118-123`）、figure region 命中时按 region 内比例映射（`readerNavigation.ts:95-117`）。
- `captureViewport`（`readerNavigation.ts:173-187`）：阅读焦点线 = `scrollTop + viewportHeight*0.2`，位置三元组 `{page, fraction, viewport}`。
- 联动：`onPosition`（`PdfReader.tsx:526-547`）用户滚一侧 → `mapper()` 算对侧位置 → `pane(target).jump()`；`ignoreTop` 抑制程序化滚动引起的回声（`PdfPane.tsx:499-516`）。
- 位置持久化：700ms debounce + `pagehide` 时 `keepalive` 兜底（`PdfReader.tsx:326-363`）；`reader.py` 存 `reader.json`，写入前校验 `document_version`（`app/reader.py:198-212`）。
- **texlate 用法**：这套"named destination 锚点 + 单调链 + 高度归一化插值"是全文最精妙的设计，直接照抄；工作量集中在 pypdf 侧 ~200 行 + TS 侧 ~200 行，且各有独立测试（`tests/test_alignment.py`、`frontend/tests/readerNavigation.test.cjs`）。

### 4.4 本地服务模式

- `app/server.py:15-43`：`service_lock(DATA/service.lock)` flock/msvcrt 单 owner（`app/platforms.py:33-73`）→ 自己 `socket.bind(("127.0.0.1", port))` 再把 socket 交给 `uvicorn.Server(sockets=[sock])`——**先占端口再加载 JobManager**，防并发双启改任务状态；`--parent-pipe` 起 watchdog 线程读 stdin，Electron 爹死 stdin EOF → `server.should_exit`。
- `app/main.py:47-66`：`TrustedHostMiddleware(allowed_hosts=["localhost","127.0.0.1","[::1]"])` 防 DNS rebinding；写请求校验 `Origin==host` 且 `sec-fetch-site!=cross-site`；`X-Content-Type-Options:nosniff`、`/api` `Cache-Control:no-store`。

---

## 5. tectonic 分发

- **file**：`scripts/install_compiler.py`（121 行，完整实现）。
- 版本 `VERSION = "0.17.0"`（`:17`）；三平台矩阵 + sha256（`:18-39`）：

```python
ASSETS = {
    ("Windows", "x86_64"): ("x86_64-pc-windows-msvc.zip",
        "f61ce51f0b0ade1015b7de7ef368541c5424e9756ecbd0d7af97d6d48030845f"),
    ("Darwin", "arm64"): ("aarch64-apple-darwin.tar.gz",
        "a3f1cac7c5678f01661a92212f58480ae3b0634115d880dbc59e2953ded45667"),
    ("Darwin", "x86_64"): ("x86_64-apple-darwin.tar.gz",
        "7c90ef5b6ddb1eb1937e4337add5237b79338e4b9676459fa91187d24d6cdf80"),
    ("Linux", "x86_64"): ("x86_64-unknown-linux-musl.tar.gz",
        "8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7"),
    ("Linux", "arm64"): ("aarch64-unknown-linux-musl.tar.gz",
        "b10954a95404f3ab2328d2fa59a5ebab8e657f893fab096f98be8db7c0c979b8"),
}
```

- URL：`https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40{VERSION}/tectonic-{VERSION}-{suffix}`（`:50-53`）。
- `install()`（`:57-91`）：`urlopen(timeout=90)` 读 ≤150MB+1 → sha256 校验失败即整体拒绝 → zip/tar.gz 里**只提 tectonic 单文件**（member 名 basename 匹配且恰好一个）→ 写 `<dest>/tectonic.download` → `chmod 0o755` → `replace()` 原子落位。落点 `DATA/tools/`（`TEXGLOT_DATA_DIR` 或仓库 `data/`）。
- 查找顺序 `find_compiler`（`app/compiler.py:27-48`）：PyInstaller `_MEIPASS/tools` → `shutil.which`（win 拒绝 .cmd/.bat）→ `DATA/tools` → mac 追加 `/Library/TeX/texbin`、homebrew 两前缀。
- 宏包 bundle 也钉版本：`tectonic_bundle()`（`app/compiler.py:1121-1128`）默认 `https://data1b.fullyjustified.net/tlextras-2022.0r0.tar`，env 可覆盖。
- 桌面打包时同一 `install()` 复用（`scripts/build_desktop.py:146-150`："never bundle an unknown PATH executable"）→ `--add-binary tectonic→tools`（`build_desktop.py:183-184`）。
- **texlate 用法**：照抄（矩阵 + 校验 + 单文件提取 + 原子落位+bundle pin）。注意它**没做** PGP/sigstore 验签，sha256 是唯一信任锚。

---

## 6. Electron 打包

### 6.1 进程模型

- `desktop/main.cjs`：`requestSingleInstanceLock`（`:13`）；`userData` 指向 `~/.texglot/desktop-profile`（`:10-12`，Chromium profile 与文档分开放）；`BrowserWindow` 全锁（`:30-35`：`nodeIntegration:false, contextIsolation:true, sandbox:true`）；外链一律 `shell.openExternal` + `setWindowOpenHandler deny` + `will-navigate` 非同源拦截（`:42-45`）；权限请求全拒（`:46-47`）。
- `desktop/service.cjs:55-112` `startService()`：
    - 端口扫描 `preferred..+20`（`:61-69`）：先打 `/api/health`，`matchingService`（`:41-44`）要求 `ok && name=='TeXGlot' && data_dir` canonical 相等 → **同库已在跑就复用不 spawn**；版本不符报 `different-service-version`（mac app 升级后旧服务还占着数据目录的场景）；
    - spawn：`texglot-engine --engine-server --port N --parent-pipe`，`cwd=dataDir`，`stdio:['pipe', logfd, logfd]`（`:73-78`）；
    - 就绪探测 150×200ms 轮询 health（`:99-109`）；
    - 关闭阶梯（`:84-97`）：`child.stdin.end()` EOF 请求优雅退出（后端 watchdog 收）→ 15s → win `taskkill /T /F` / POSIX `SIGKILL` → 再等 2s。
- 后端入口切换：`desktop/engine.py`（frozen 时 `--engine-server` 转 `app.server.main`，否则走 CLI）；`app/runtime.py:16-25` 生成命令行（frozen `[sys.executable, --engine-server]` vs 源码 `-m app.server`）；`child_environment()`（`runtime.py:28-38`）修复 PyInstaller 子进程 `LD_LIBRARY_PATH`（恢复 `*_ORIG`）。
- 退出拦截（`main.cjs:119-140`）：quit 前查 `/api/jobs`，有活动任务弹确认框。

### 6.2 构建配置

- `desktop/package.json:20-111`：electron-builder 26.x + electron 44；`extraResources` 把 `engine-dist/texglot-engine`（PyInstaller onedir 产物）放进 `resources/engine`；mac `dmg`（`identity:"-"` ad-hoc 签名，`hardenedRuntime:false`——糙，见 §8）、win `nsis`（`oneClick:false, allowToChangeInstallationDirectory:true, installerLanguages:[en_US,zh_CN]`）；`afterPack: after-pack.cjs`（`desktop/after-pack.cjs`：签名前 `xattr -rd com.apple.FinderInfo/ResourceFork` 清 Finder 元数据）。
- `scripts/build_desktop.py`：PIL 生成 icon.icns/ico/png（`:24-39`）；`@electron/get` 拉校验过的 Electron zip 抽 LICENSE 聚合 `THIRD_PARTY_NOTICES.txt`（`:51-110`）；PyInstaller 参数（`:151-192`）：`--onedir --collect-submodules app,uvicorn --collect-data opencc,certifi --add-data frontend/dist:app/web --add-data app/resources --add-binary tectonic:tools`；**在 tmpdir 里跑 electron-builder 再拷产物**（`:204-215`，躲云同步目录的 Finder 元数据污染签名）。
- CI（`.github/workflows/desktop.yml`）：matrix `windows-latest` + `macos-15-intel`；先 `frontend npm ci/test/build` → `uv sync --group desktop` + pytest → `desktop npm ci/test` → `build_desktop.py` → **`smoke_platform.py` 冒烟冻结引擎** → Windows 还真跑 `Setup.exe /S /D=` 装一遍再冒烟（`:48-56`）。
- 自更新（`desktop/updates.cjs`）：不自动装——只查 GitHub releases，下载前校验 `asset.digest`（`sha256:` 前缀）或 `SHA256SUMS.txt` 条目（`:126-134`），下载用专用 session partition + URL 一次性标记防串扰（`:247-287`），install 前再验一次 sha256（`:228-233`）；renderer 不能传 URL/路径（`main.cjs:81-92` 校验 `event.senderFrame` origin）。
- **texlate 用法**：spawn/health/版本握手/stdin-EOF 关停阶梯这套直接抄；打包侧 PyInstaller onedir + extraResources + afterPack 清 xattr 也可照搬。

---

## 7. 翻译回路（翻译→校验→带错重翻）

**注意**：代码里没有 `[Original]/[Translation]/[Error]` 三段式 prompt；它的等价物是**结构化 JSON 字段 `previous_validation_error` / `slot_validation_failures`**。

### 7.1 段级重试阶梯（`app/jobs.py:580-611`）

```python
async def one(key, item):
    if key in translated:
        return
    async with semaphore:
        feedback = ""
        for attempt in range(3):
            try:
                output = await (
                    client.translate_slots(item, context, feedback)
                    if attempt == 2
                    else client.translate(item, context, feedback)
                )
                validate_translation_language(item, output, settings.target_language)
                restored = item.restore(output)
                translated[key] = restored
                cache[key] = output
                atomic_json(cache_path, cache)
                break
            except ProviderError:
                raise
            except ValueError as exc:
                feedback = str(exc)
                if attempt == 2:
                    failed.append(key)
                    ...log "保留原文 [segment key · rel:line]"
```

- 阶梯：**整段翻 ×2（带反馈）→ translate_slots 兜底**；`ProviderError`（服务不可用）直接抛出让整个 job 失败重跑，`ValueError`（结构校验）只记该段、三振后保留原文 + warning（`partial` 状态，`app/jobs.py:635-638,663-667`）。
- 并发：`asyncio.Semaphore(settings.concurrency)`，全部 task 先 create 再 gather，异常时 cancel 全部（`app/jobs.py:619-626`）。

### 7.2 请求结构（`app/llm.py:327-418`）

- system prompt（`llm.py:336-347`）讲清规则：`⟪P0000⟫` 是受保护 LaTeX/公式/引用 token，每个恰好出现一次；`value_tokens`（可动：数字/行内公式/引用/人名宏）可按目标语语法换序但语义角色不变，还给了"decreases from A to B after C steps"的反例防数字错位；文档视为不可信数据防注入。
- user content 是一个 JSON（`llm.py:378-408`）：`{paper_context?, paragraph( masked), surrounding_source?, value_tokens{token→原文值≤350字符}, fixed_format_order[固定 token 序], fixed_text_context{token→短原文}, previous_validation_error}`。**反馈不是对话式"你错了"，而是把校验异常字符串塞进下一次请求的字段**。
- `recover_copied_tokens`（`llm.py:130-157`）：模型把受保护 LaTeX 原文抄回来而没用 token 时，若该原文在输出里**唯一出现**就替换回 token——只修"exact+unique"的，不瞎猜。
- `validate_translation_language`（`llm.py:173-218`）：中文目标时，散文段（≥8 个拉丁词且含 ≥2 个虚词）译文 CJK 字数为 0 → 报错；英文词残留 >80% 且 CJK <15% → 报错。
- `normalize_language`（`llm.py:160-170`）：OpenCC t2s/s2t 兜底简繁。

### 7.3 结构校验（`Segment.restore`，`app/latex.py:379-496`）

- token 多重集相等（`:381-384`）；词粘连检查防 "RoBERTa→RoBERTas" 式拼坏（`word_joins`, `:385-402`）；**fixed token 相对顺序不变**（`:403-409`）；`\textbf{` 类命令与参数间不许插正文（`argument_boundaries`, `:410-418`）；scope/cell 区域签名比对——`{}/[]/&/\\/\begin` 构成的嵌套帧序列在两版 token 序里必须一致（`regions()`, `:420-455`）；空白边界对不许插字（`whitespace_boundaries`, `:456-461`）；译文长度 ≥10% 源文（`:464-465`）；最后**只对生成散文做 LaTeX 转义**（`escape()`, `:468-496`，`\{}$&%#_^~` 映射表 + `render_text_symbol` Unicode 数学符号 → `\ensuremath` 包裹）。
- `validate_source_map`（`latex.py:537-548`）：付费翻译前先自证 masked→protected→source 可逆；`target_probe`（`latex.py:550-`）把英文词换成"译文/譯文"样本做**免费预检编译**——jobs.py:506-512 先用 probe 输出编译一遍确认字体兼容再花钱翻。

### 7.4 兜底：slots 模式（`translate_slots`，`app/llm.py:420-571`）

- 把段落按受保护 token 切开，含文字的散文片段编号 `⟪S0000⟫`，要求模型返回 JSON `{slot_id: 译文}`（`response_format json_object`）；每 8 槽一批，失败槽**只重问失败那批**并附 `slot_validation_failures{slot:reason}`；校验每槽：非空、非字符串拒、含保护标记拒、含 LaTeX/围栏拒（`validate_generated_prose`）；已接受的槽不再改。槽前还有一级 `translate_lines`→`repair_chunks`（`llm.py:34-109`）：在闭合 scope 边界按句号/算法伪代码关键字切段重翻，粒度介于整段和槽之间。
- **texlate 用法**：阶梯"整段带反馈×2 → 行级修复 → slot JSON"可直接搬；字段化反馈比三段式 prompt 更稳（模型不需要解析对话历史里的错误描述）。

### 7.5 HTTP 层（`Translator.complete`，`app/llm.py:239-325`）

- 状态码分类：401/403→认证错、402→余额、404→地址/模型错、408/409/425/429/5xx→重试（≤2 次，`retry_delay` 读 Retry-After 数字或 HTTP-date，`llm.py:116-127`，>60s 不等直接报错）、其余 4xx→拒绝；`finish_reason=="length"`→截断错；`choices[0].message.content` 逐层 isinstance 校验；usage 可缺省不记账；`httpx.TransportError/ssl.SSLError` 指数退避。
- `redact()`（`llm.py:221-224`）：错误信息里抹 `settings.api_key` 和 `sk-*` 模式再写进 job.error/log。

---

## 8. 反面清单（别抄的地方）

| 位置                                    | 问题                                                                       | 评价                                                                                                                                                       |
| --------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/jobs.py:56-57`、`app/config.py:18` | import 时 `JOBS.mkdir()/DATA.mkdir()`，import 副作用                       | texlate 应延迟到服务启动                                                                                                                                   |
| `app/jobs.py:139,263`                   | `self.slot = asyncio.Semaphore(1)` 包住整条 pipeline                       | **全局一次只跑一个 job**——单用户桌面工具说得过去，texlate 若做服务端直接去掉                                                                               |
| `app/jobs.py:597-598`                   | 每翻完一段把**整个 cache dict** atomic_json 重写一遍                       | O(n²) IO；大论文数百段就是几百次全量写。可接受但糙；可改 append-only jsonl + 定期压实                                                                      |
| `app/config.py:74-80`                   | `temp = path.with_suffix(".tmp")` 固定名                                   | 同路径并发写会撞（靠 slot=1 掩盖）；tmp 名应带 uuid                                                                                                        |
| `app/jobs.py:109-111,156-158`           | `refresh_title_metadata` 等 `except(...): pass` 静默吞错                   | 迁移失败无痕；至少记 log                                                                                                                                   |
| `app/llm.py:221-224`                    | `redact` 只抹 `sk-*` 和自己的 key                                          | 别家 key 形态（sk-ant-, sk-or-, AIza 等）照样进日志；texlate 应做 provider 无关的脱敏或干脆不记请求体                                                      |
| `app/compiler.py:1431`                  | env 过滤按子串 `KEY/TOKEN/SECRET/PASSWORD`                                 | 误伤 `MONKEY`、`KEYSTONE` 等无辜变量（无害但糙）；正向做法是白名单 env                                                                                     |
| `app/main.py:53-60`                     | 本地 API 无鉴权，只靠 Origin/Sec-Fetch-Site + TrustedHost                  | 本机任意进程可 curl `/api/jobs` 读论文/投任务；桌面单机可接受，**写成 texlate 安全边界时要点名**                                                           |
| `app/main.py:69-93`                     | i18n 中间件对每个 `/api` JSON 响应读全 body 重序列化、按中文字符串查表翻译 | 英文 UI 下错误消息依赖后端中文原文不漂移——脆耦合；texlate 应直接返回 error code 由前端翻                                                                   |
| `desktop/package.json:64-65`            | mac `"identity": "-"` ad-hoc 签名 + `hardenedRuntime:false`                | dmg 下载者要绕 Gatekeeper；texlate 若要公发必须正签 + 公证，别抄这个                                                                                       |
| `app/llm.py:336-347`                    | 每段请求都带一遍 ~400 词 system prompt                                     | 无 prompt caching 意识；texlate 选 Anthropic 时应上 cache_control 或合并进 user                                                                            |
| `app/jobs.py:528-541`                   | cache 文件按 config hash 命名但**永不清理**                                | `cache-*.json` 无限累积；texlate 需要 GC 策略                                                                                                              |
| `app/config.py:164`                     | `api_key` 明文存 `settings.json`（0600）                                   | BYOK 常态取舍，但要在文档里承认；texlate 可考虑 keychain/DPAPI                                                                                             |
| `app/figure_alignment.py:51-57`         | 图形签名用 `StreamObject.get_data` 原始压缩字节                            | 两次编译 flate 字节不保证一致，签名偶发失配（有 fallback 兜底所以无害）；若 texlate 也做图匹配，应对解码后内容或图像 hash                                  |
| `frontend/src/PdfReader.tsx`（1200 行） | 单组件巨石：阅读器 + 批注 + 同步 + 持久化全揉一起                          | 功能全但难拆；texlate 前端应照 `readerNavigation.ts`/`readerGeometry.ts` 这种纯函数剥离方式写                                                              |
| `app/jobs.py:302-304`                   | `shutil.rmtree(source)` 直接删目录无软删                                   | 用户任务目录是程序自管的，风险低；但重试路径多，状态文件用 sentinel（`source-ready` touchfile）而不是事务——崩在 rmtree 与 touch 之间会重解压，属可接受粗糙 |

**值得一提的"糙但有担当"**：`jobs.py` 里翻译失败的段保留原文并把任务标 `partial` 而非 `failed`，配合 cache 可断点续翻——方向对，但失败原因只进 log 不进结构化字段，前端只能显示文本警告。

---

## 附：texlate 复用速查

| texlate 模块       | 抄 texglot 哪里                                                                                                     |
| ------------------ | ------------------------------------------------------------------------------------------------------------------- |
| 源码归一化层       | `compiler.py:344-447` 编排 + `sources.py:172-223` visible_tex + `compiler.py:58-151` 五个前导块                     |
| BYOK provider 抽象 | `providers.py` 全文 44 行 + `llm.py:250-256` 方言点                                                                 |
| 段缓存             | `latex.py:256-285` key 构成 + `jobs.py:528-598` 文件布局 + `config.py:74-80` atomic_json                            |
| 对照阅读器         | `alignment.py` + `figure_alignment.py` + `readerNavigation.ts` + `PdfPane.tsx:356-362,196-203`                      |
| tectonic 分发      | `install_compiler.py` 全文 + `compiler.py:27-48,1121-1128`                                                          |
| 桌面壳             | `service.cjs` spawn/health/关停 + `build_desktop.py:151-215` + `package.json` electron-builder 段                   |
| 翻译回路           | `jobs.py:580-611` 阶梯 + `llm.py:378-408` 请求 JSON + `latex.py:379-496` restore 校验 + `llm.py:420-571` slots 兜底 |
| 编译沙箱           | `compiler.py:928-975` sandbox-exec + `compiler.py:1428-1440` env 清洗                                               |
| 防注入/路径安全    | `compiler.py:896-925` source_path_violations + `sources.py:48-73` safe_path                                         |
