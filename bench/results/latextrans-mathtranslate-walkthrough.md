# 代码走读：LaTeXTrans vs MathTranslate — LaTeX 源码翻译两条路线

走读对象（本地副本）：
- **LaTeXTrans**（NiuTrans，MIT）：`/tmp/latex-refs/LaTeXTrans`，论文 arXiv:2508.18791。多 agent + LLM 翻译管线。
- **MathTranslate**（SUSYUSTC，Apache-2.0，~1.4k★）：`/tmp/latex-refs/MathTranslate`，v3.1.2。regex + 受限宏展开 + 传统机器翻译引擎（Google/Tencent）。

一句话结论：**两家共用同一套底层正则骨架**（`regex` 库递归子模式匹配嵌套花括号 + 占位符替换/回填），LaTeXTrans 的 `process_newcommands`/`get_pattern_brace` 明显是从 MathTranslate 演化来的；但占位符的**粒度**和**翻译回路**完全不同——MathTranslate 把"几乎所有 LaTeX 对象"都换成占位符让 MT 引擎只看到自然语言，LaTeXTrans 只藏"不可翻/高危"结构，把含 LaTeX 命令的正文直接交给 LLM，靠 Validator 对账。

---

## 1. 两家架构图

### LaTeXTrans（`CoordinatorAgent` 顺序编排，asyncio）

```
main.py / src/runtime.py
  │  --arxiv → 下载 e-print tar.gz + 解包 + 抓 arXiv category
  │  --project → 本地目录 / zip / tar 解压
  ▼
CoordinatorAgent.workflow_latextrans()        src/agents/coordinator_agent.py
  │
  ├─ 1. ParserAgent.execute()                 tool_agents/parser_agent.py
  │     └─ LatexParser (src/formats/latex/parser.py)  自写 regex parser
  │        产出 5 个 map：inputs_map / newcommands_map / sections_map /
  │                     captions_map / envs_map （全部落到 output_dir 的 JSON）
  │     └─ LLM judge：对每个未知 env 判 need_trans True/False (temp=0, ≤50tok)
  │
  ├─ 2. TranslatorAgent.execute()             tool_agents/translator_agent.py
  │     aiohttp + Semaphore(10) 并发翻 section/env/caption
  │     每次完成即回写 JSON（断点可恢复）；失败部件记 fail_* 名单重试 ≤3 次
  │
  ├─ 3. ValidatorAgent.execute()              tool_agents/validator_agent.py
  │     规则校验（不调 LLM）→ errors_report.json
  │
  ├─ 4. while errors_report and retry<3:
  │        translator.trans_mode=1 → 只重翻出错部件（[Original]/[Translation]/[Error] 三段式）
  │        validator.execute(errors_report) 复检
  │
  └─ 5. GeneratorAgent.execute()              tool_agents/generator_agent.py
        ├─ LatexConstructor (reconstruct.py)：拼 sections → 回填 env/caption/
        │   newcommand 占位符 → input begin/end 配对、拆回独立 .tex 文件 →
        │   补 \usepackage[UTF8]{ctex} → 写回主文件
        └─ LaTexCompiler (compile.py)：latexmk -pdflatex → 失败 fallback -xelatex
           （日语走 compile_ja → lualatex）→ 产出 ch_<name>.pdf
```

README 宣称"六 agent：Parser, Translator, Validator, Summarizer, Terminology Extractor, Generator"。**实际代码里只有 4 个 tool agent + 1 个 coordinator**；Summarizer 和 TerminologyExtractor 只是 prompts.py 里的模板 + TranslatorAgent 里的未接线方法（见 §4）。这是"论文架构 vs 发布实现"的差距，值得注意。

### MathTranslate（单类流水线，线程池并发段落）

```
translate_tex.py (单文件) / translate_arxiv.py (整项目)
  │
  ▼
LatexTranslator.translate_full_latex()        mathtranslate/translate.py
  │
  ├─ 预处理：remove_tex_comments → \mathbf→\boldsymbol → remove_bibnote
  │          → process_newcommands  ★受限宏展开（核心差异点）
  │          → replace_accent / replace_special（\"o、\% → XMATHX 编码）
  │
  ├─ is_complete? → 拆 preamble/body/postamble，preamble 插 xeCJK+amsmath
  │                 （不完整则 connect_paragraphs + 可选包默认模板）
  │
  ├─ split_latex_to_paragraphs：全文 replace_latex_objects → \n\n 切段 → 逐段回填
  │
  ├─ ThreadPoolExecutor.map(worker, paragraphs)   ← 唯一并发点
  │     worker → translate_paragraph_latex：
  │       a) 删 textbf/emph 格式命令 → 对象→XMATHX 占位符 → 拼句 → 调 MT 引擎
  │          → 强制占位符大写 → recover_latex_objects 回填（递归，容忍错位）
  │       b) process_leading_level_brace 递归翻顶层 {} 组
  │       c) translate_latex_all_objects：白名单 env/command/mularg 的
  │          *参数内部* 再过一遍同一翻译函数（caption/section/theorem…）
  │
  ├─ 翻 \title → 逃逸裸 % → recover_special/accent
  └─ 输出 .tex → --compile 时 os.system('xelatex')；arxiv 流程打 zip 提示传 Overleaf
```

MathTranslate 没有"agent"概念：一个 `LatexTranslator` 类 + 两个引擎适配器（`TextTranslator` 包 google/tencent）。所谓并发只是段落级 ThreadPoolExecutor。

---

## 2. 共同的底层正则骨架（同源证据）

两家都用 PyPI `regex` 库（不是 stdlib `re`）的**递归子模式**匹配嵌套花括号：

```python
# MathTranslate process_latex.py:15 / LaTeXTrans utils.py:24 — 一字不差
get_pattern_brace = lambda index: rf"\{{((?:[^{{}}]++|(?{index}))*+)\}}"
```

机制：`\{` + 捕获组 `((?:[^{}]++|(?N))*+)` + `\}`。
- `[^{}]++`：非花括号字符，**占有量词**防回溯爆炸；
- `(?N)`：递归调用第 N 号捕获组自身的 pattern（要求 N 组包住整个 `{...}`，即"花括号串"是可递归自指的文法）；
- 由此支持任意深度嵌套 `{a{b{c}}}`，无需手写栈式扫描。

在此之上的积木（两家几乎相同）：

| 函数 | 作用 |
|---|---|
| `get_pattern_command_full(name, n)` | 拼 `\name[opt]{arg1}..{argn}` 的 regex；n=None 时带 options 组 + 1 个花括号参；n=0 时加 `(?=[^a-zA-Z])` 防吞掉后续命令名字母 |
| `get_pattern_env(name)` | `\begin{name}[opt]...\end{\1}`，用反向引用 `\1` 配环境名 |
| `get_pattern_newcommand` | `\newcommand\|renewcommand\|def[...][n]{body}`，捕获名字(花括号或裸两种写法)、参数个数、宏体 |

**已知局限（两家相同）**：
- env 用 `(.*?)` 非贪婪 + `\end{\1}` 配 → **同名环境嵌套会失配**（在第一个 `\end{same}` 处截断）；异名嵌套没问题。
- 花括号计数不区分 `\{` `\}` 转义，也不处理 verbatim 内字面花括号——MathTranslate 用 `replace_special` 先把 `\{`→`XMATHXLB` 缓解；LaTeXTrans 靠先跑 `remove_comments` + 黑名单 env 兜底。

LaTeXTrans 的 `get_env_pattern` 加了一个排除环：`\\begin{spaces}\{(?!document\b|center\b|proof\b|multicols\b)(.*?)\}`——document/center/proof/multicols 不抽为占位符，直接在正文里翻。

---

## 3. MathTranslate 深读

文件：`mathtranslate/process_latex.py`（496 行，全部核心）、`translate.py`（驱动）、`process_file.py`（\input 合并）、`process_text.py`（断句/分段）。

### 3.1 占位符体系（XMATHX）

`math_code = 'XMATHX'`（config.py:26）。所有被摘出的 LaTeX 对象变成 ` XMATHX_1_2_3 ` 形式：
- 编号十进制拆位加下划线（`variable_code(123)` → `XMATHX_1_2_3`），回填时 `int(''.join(digits))` 还原序号。下划线分隔是为了让 MT 引擎把这串当成普通 token 不乱动；
- 两侧各垫一个空格，防止引擎把占位符和邻词粘连；
- 翻译后 `replace_with_uppercase(text, 'XMATHX')` 把引擎可能改的小写/变形统一刷回大写再匹配。

`replace_latex_objects`（process_latex.py:110）按**固定优先级**逐类替换（顺序就是优先级）：
1. `$$...$$`、`$...$`、`\[...\]`、`\(...\)` —— 数学先行
2. `pattern_env` 任意 `\begin..\end` 环境（整体变不透明对象）
3. `pattern_set1/set2`：`\setlength\xxx{...}` 类赋值命令
4. `mularg_command_list` 里定义的多参命令（默认只 `('textcolor', 2, (1,))`，用户可用 `-commands` 文件追加 `additional_commands`）
5. `pattern_command_full`：任意 `\cmd[opt]{arg}`
6. `pattern_brace`：裸 `{...}`
7. `pattern_command_simple`：裸 `\cmd`

关键性质：**替换是分层累积的**——先摘 `$..$`，env 摘出时其内部的 `XMATHX` 码已封进对象文本。因此 `recover_latex_objects` 必须循环 `subn` 直到零替换，外层先还原、内层码再露头再还原。错位容忍：`XMATHX_i` 的 i 超出 objs 范围 → 回填 `'???'`；统计 `n_bad`（丢/多的对象数），只打印报告不阻断。

`modify_text` 是个精巧工具：按占位符把文本切段，只对非占位符段施加函数——`modify_before`（`\pm`→`$\pm$`、`Eq.`→`equation`）、`modify_after`（裸 `_`→`\_`）都不会碰到占位符内部。

### 3.2 process_newcommands —— 受限宏展开（重点）

`process_latex.py:455`：

```python
def process_newcommands(latex):
    pattern = regex.compile(pattern_newcommand, regex.DOTALL)
    matches_all = list(regex.finditer(pattern, latex))
    for match in matches_all:
        need_replace = False
        content_all = match.group(0)            # 整个 \newcommand 定义原文
        for special in replace_newcommand_list:
            if special in content_all:          # 子串匹配定义体！
                need_replace = True
        if not need_replace:
            continue
        ...
        latex = latex.replace(match.group(), f'{math_code}_REPLACE{count}_NEWCOMMAND')
        full_newcommands.append(match.group(0))
        latex = replace_newcommand((name, n_arguments, content), latex)
        count += 1
    for i in range(count):
        latex = latex.replace(f'{math_code}_REPLACE{i}_NEWCOMMAND', full_newcommands[i])
```

**策略规则**：
1. **只匹配 `\newcommand` 和 `\def`**（不支持 renewcommand/newenvironment——LaTeXTrans 版的 pattern 更全但不用在主管线）；
2. **展开条件 = 定义体子串命中白名单** `replace_newcommand_list = ['equation','array','displaymath','align','multiple','gather','theorem','textcolor'] + environment_list + command_list`（process_latex.py:75）。即：宏体里只要**含有**这些字符串之一就展开该宏的全部使用点。直觉：这些是"影响翻译对象识别的结构性命令"——若宏包住了 equation/caption/section，占位符层会把它当普通过 `\cmd` 整吞，导致数学/标题不被保护或正文不被翻；
   - 例（test_latex/input_be.tex）：`\newcommand{\be}{\begin{equation}}` → `\be` 在使用点展开成 `\begin{equation}`，方程体正确成为不透明对象；
   - 例（input_mularg.tex）：`\newcommand{\green}[1]{\textcolor{green}{#1}}` → 命中 `textcolor` → `\green{This is green.}` 展开为 `\textcolor{green}{This is green.}`，后者再经 mularg 规则只翻第 2 参；
   - 普通缩写宏（如 `\newcommand{\R}{\mathbb{R}}`）不命中 → 原样留下，被 `pattern_command_simple` 整吞成不透明占位符，不翻也不坏。
3. **展开方式**：先把定义本体替换成 `XMATHX_REPLACE{i}_NEWCOMMAND` 哨兵（让定义文本在展开期间隐身），再对全文 `pattern.sub` 展开使用点，最后把定义原文贴回去。效果：**使用点展开、定义保留**——ref_be.tex 输出里 `\newcommand{\be}` 仍在。
4. **参数替换**（replace_newcommand，:439）：宏体里 `#i` → ` {argi} `（两侧加空格，防止与宏体其他 token 粘连）；用 `get_pattern_command_full(name, n)` 匹配使用点，n=0 时靠 `(?=[^a-zA-Z])` 阻断误匹配前缀（`\be` 不会吃掉 `\begin`）。
5. **不做的事**：无递归展开防护需求（定义被藏起来了，但使用点展开只跑一遍——若宏 A 展开后产生宏 B 的调用，B 的展开已在其自身轮次做过，顺序由 matches_all 的 finditer 顺序决定，**存在展开顺序敏感**）；不支持 `[9]` 以上参数（`\[(\d)\]` 只一位）；不支持可选参数默认值 `[1][default]`；不展开 `\newenvironment`、`\DeclareRobustCommand`、`\def` 的非 `\xxx` 形参（`\def\a#1{}` 形参语法也不支持——pattern 要求 `\name` 后跟 `[n]` + `{body}`）。

注意一个顺序细节：`matches_all` 在替换前一次性取好，循环里用 `latex.replace(match.group(), 哨兵)`——如果两个定义文本完全相同，replace 会命中第一个出现位置，轻微错位的风险存在但无害。

### 3.3 翻译与回填

- `split_latex_to_paragraphs`：全文先 `replace_latex_objects`（此时 env 都是占位符），按 `\n\n+` 切段，逐段 `recover_latex_objects`——段落边界不会切进 env 内部。
- `_translate_text_in_paragraph_latex`：先 `delete_specific_format` 把 `\textbf/\textit/\emph{x}` 剥成 `x`（**格式直接丢弃**换可译性）；对象→码；`combine_split_to_sentences` 把单个 `\n` 折行合并回句子（下一行以 XMATHX 开头除外）；超长段 `split_too_long_paragraphs` 按 `.` 断句找大写开头的切点；不完整文档再 `split_titles`。
- `translate_paragraph_text`：按行聚合到 `char_limit=2000` 批量发引擎；**全大写文本跳过不译**（保住 ABSTRACT 这类标题词）；单行长于 2000 直接 assert 崩。
- `translate_latex_all_objects`：对白名单 env（`environment_list` + `\newtheorem` 抓出来的 theorem 名 + 各自 `*` 变体）用 `process_specific_env` 翻**内部**；对白名单命令（`command_list`：section/subsection/subsubsection/caption/subcaption/footnote/paragraph）用 `process_specific_command` 翻**花括号参数**；mularg 命令只翻指定参数位。figure/table/equation 不在白名单 → 整env 不透明，但 `\caption` 是命令级处理，regex 能看穿 env 边界，**图环境里的 caption 照样被翻到**（ref_caption.tex 证实）。
- `process_leading_level_brace`：先把对象摘掉，对剩下的顶层 `{...}` 递归调用翻译函数——处理 `\title{...}` 之外散落的 brace 文本。
- 收尾：`%` → `\%` 全部转义（因为注释已删，剩下的 % 都是引擎引入的），再 recover_special/accent。

### 3.4 特殊字符/accent 编码

`replace_special`：`\\`→`XMATHXBS`、`\%`→`XMATHXPC`、`\&`→`XMATHXAD`、`\#`→`XMATHXNB`、`\$`→`XMATHXDL`、`\{`/`\}`→`XMATHXLB/RB`、`\ `→`XMATHXSP`（两侧加空格）；`replace_accent`：`\`{o}`/`\"o` → `XMATHXBQo`/`XMATHXDQo`（不加空格，保单词完整性）。回填时 accent 统一为 `\`{o}` 花括号形式。

### 3.5 引擎、并发、缓存、编译

- 引擎：`google` → `mtranslate` 包（免费 API 封装；仓库里还留着 Selenium+Xvfb 驱动 Google Translate 网页的 `google.py` 备用实现和 `ParallelTranslator` 每线程一浏览器，已注释掉）；`tencent` → 官方 TMT SDK，`UntranslatedText=config.math_code` **直接利用腾讯 API 的"不译标记"参数保护占位符**——这是最省事的一条保护通道。
  - ⚠️ 发现疑似 bug：`translate.py:30` google 分支 `self.try_translate = lambda text: self.translator.translate(...)`，但 `self.translator` 在 google 分支从未赋值（只有 tencent 分支赋值）——调用即 AttributeError。可能依赖调用方打补丁或 3.1.2 之后已修。
- 重试：`translate()` while True，有 `is_error_request_frequency`（腾讯 RequestLimitExceeded）睡 0.5s 重试，其他异常直接抛——**无上限死循环**。
- 并发：`ThreadPoolExecutor(max_workers=threads)`，`threads=0`→None（默认 min(32, cpu+4)）；腾讯强制 1 线程；worker 是段落级 `translate_paragraph_latex`。
- 缓存：`sha256(全文+版本+引擎+语言对+mularg配置)` 为文档级目录，段落再 hash 为文件，逐段命中免翻；最多 5 个文档缓存 LRU 淘汰（`cache.py`）。
- `\input` 合并：`process_file.merge_complete` 只处理 `\input{}`（不支持 `\include`），**就地覆盖原 tex 文件**——译完的项目文件结构被摊平进主文件，剩下的 .tex 全删（translate_dir 里 `os.remove`）。
- `.bib` 处理：无 .bib 但有 .bbl 时 `add_bbl` 把 `\bibliography{}` 就地换成 .bbl 内容。
- 编译：单文件 `--compile` → `os.system('xelatex out.tex')` 一把过；arxiv 模式打 zip 由用户传 Overleaf 自动编译（`upload_overleaf.py` 是硬编码账号的 selenium 草稿，等于没接）。中文支持靠 preamble 插 `\usepackage{xeCJK}` + `\documentclass[UTF8]`（不完整文档用 default_begin 模板）——所以**绑死 xelatex**。
- 编码：`charset_normalizer` 逐文件探测，`<0.9` 置信度告警；`--force-utf8` 可强制。

---

## 4. LaTeXTrans 深读

### 4.1 Parser —— 自写 regex 切分器（不是 AST）

`src/formats/latex/parser.py` + `utils.py`。流程（`LatexParser.parse`）：

1. `find_main_tex_file`：先查 arXiv 解压带的 `00README.json` 里 `usage=toplevel`，否则扫所有 .tex 找 `\documentclass`。
2. `remove_comments`：删 `comment` 环境 + 非转义 `%` 行/行尾。
3. `_merge_inputs`：循环内联 `\input`/`\include`，**每段裹 `<PLACEHOLDER_{relpath}_begin>/<PLACEHOLDER_{relpath}_end>`**——既摊平翻译又保留文件边界供重建。
4. `_extract_newcommands`：`\newcommand/\renewcommand/\def/\newenvironment/\renewenvironment` 的**定义**换成 `<PLACEHOLDER_NEWCOMMAND_i>`。**不展开使用点**——定义藏起来让 LLM 改不到，重建时原文贴回；使用点留在正文里由 LLM "别动命令" 规则约束 + Validator 兜底。
5. `compress_newlines`：≥3 连续换行压成 2 个——注释明说"防止大模型漏掉占位符"。
6. `_split_to_sections`：preamble→`"-1"`（不翻）、`\begin{document}`到首个 `\section`→`"0"`（不翻），正文按 section/subsection/subsubsection 切成 `"2"`/`"2_1"`/`"2_1_3"` 编号段。**不支持 \chapter**。
7. `_merge_short_sections(min_tokens=50)`：tiktoken(gpt-4) 计量，过短的段与后段合并（id 用 `+` 连）——省 API 调用。
8. 每段内：`_extract_captions` 先把 `\caption/\subcaption/\title/\keywords/\abstract/\icmltitle` 摘成 `<PLACEHOLDER_CAP_i>`；再 `_extract_envs` 把任意 `\begin{env}..\end{env}`（除 document/center/proof/multicols）摘成 `<PLACEHOLDER_ENV_i>`。
   - **顺序很关键**：caption 先摘 → 含 CAP 占位符的 env 直接 `need_trans=False` → 图/表环境整坨不翻，caption 单独走 caption prompt 翻。
   - `no_translate_envs` 黑名单 ~40 项：数学族（equation/align/gather/multline/cases/subequations…）、图表族（figure*/table*/tabular*/longtable/sidewaystable）、代码族（verbatim/lstlisting/minted）、tikzpicture、algorithm*/algorithmic*、tcolorbox、thebibliography、CJK、scope。
9. **LLM judge**（parser_agent.py:35-57）：剩余 `need_trans=True` 且不在 `['abstract','itemize']`（这俩免判直接翻）的 env，逐个问 LLM（`set_need_trans_for_envs_system_prompt`，temp=0、max_tokens=50、只许答 True/False）——"只看内容不看环境名：含自然语言→True，纯代码/公式/TikZ→False"，带 5 个 few-shot。判不出来的 env 类型就靠这一招泛化。

产出物全是 JSON map（`placeholder → 原文 → trans_content → need_trans`），中间态完全落盘、可检查、可续跑——这是它比 MathTranslate 工程化强的地方。

### 4.2 Translator —— 并发 + 术语 + 错误回路

`translator_agent.py`（1006 行，全系统最肥）。

- **并发**：`aiohttp` + `Semaphore(10)`，逐 section `as_completed`；每个 section 翻完顺带翻它引用的 env（顺出 env 里嵌的 CAP）和 caption；**每完成一个就重写三个 map JSON**（断点保护 + 方便观测）。
- **三种 trans_mode**：
  - `0` 普通翻译（默认）：section/caption/env 各用专属 system prompt。
  - `1` 错误重翻：Validator 报错的部件才走这，`retrans_error_parts_system_prompt`，user prompt 三段式 `[Original] / [Translation] / [Error]`。
  - `2` 术语模式（config `mode=2`）：`term_dict` 非空则用 `*_with_dict` prompt + system 尾部硬塞 `<Glossary>`。
- **term_dict 三个来源**（`build_term_dict`）：`user_term` CSV > arXiv category 匹配的 `terms/{cs.AI,cs.CV,...}.csv` > `terms/default.csv`（~400-1800 行人工术语对）。category 是 main.py 里 BeautifulSoup 抓 arXiv abs 页 subjects 得到的。
- **`add_placeholder()`（:966）很妙**：把所有占位符（input begin/end、CAP、ENV、NEWCOMMAND）以 `ph→ph` 恒等映射灌进 term_dict—— glossary 注入时顺带把"占位符必须原样保留"变成术语替换的硬约束，尽管 mode 0 的 prompt 并不带 glossary（该注入只在 mode 1/2 生效）。
- **失败处理**：`_request_llm_for_trans` 3 次超时/异常后记 `fail_section_nums/fail_caption_phs/fail_env_phs` 并**返回原文兜底**；`_val_fail_parts` 循环重翻失败部件 ≤3 轮。
- **死的"第5、6 agent"**：`_request_llm_for_summary`、`_request_llm_for_refine_summary`、`_merge_with_prev_sections`、prompts 里的 `get_summary/refine_summary/*_with_sum/*_with_prev/*_with_terms_sum` **全部无人调用**；`update_term` 开关还有 bug（`self.update_term = True` 紧跟 `= False`，:33-35，恒为 False），所以"逐段抽取 `"en"-"zh"` 术语对回灌词典"的 TerminologyExtractor 通路接好了代码但被 bug 钉死。Summarizer 同样只剩 prompt。README 的六 agent 是论文口径。

### 4.3 Validator —— 纯规则三项对账

`validator_agent.py`，对"已翻部件"（全部 section、全部 caption、`need_trans` 的 env）逐一检查：

1. `_validate_command`：**pylatexenc `LatexWalker` 解析原文与译文**，递归数 `LatexMacroNode` 名 + `\begin/\end{env}` 的多重集；忽略 `\eg/\ie` 和单字符非字母宏。源多译少 → 报 "expected N, found M"。（用真 parser 做计数，比 regex 数 `\begin` 靠谱——这是项目里唯一用 AST 的地方。）
2. `_validate_placeholder`：原文/译文的占位符集合求差，missing / extra 都报。
3. `_validate_closed_brackets`：栈式括号匹配；译文查 `()[]{}` 三类，原文只查 `[]{}`——避免原文本就有的单边 `)`（笑脸、枚举）误报。

汇总成 `errors_report.json` → coordinator 最多 3 轮"重翻出错部件 → 复检"。**注意它不做编译检查**——编译失败不会回流给 LLM。

小 bug 记录：`_extract_parts_need_validate` 用 `sec["section"] != 0`（int）比 `"0"`（str）→ 永真，等于全量校验；`_val_fail_parts` 里 `if fail_retry_count == Maxtry` 在循环条件下不可达。均无害。

### 4.4 Generator —— 重建 + 编译

- `LatexConstructor.construct`：sections 按序拼接 `trans_content` → 字符串级 `replace` 回填 ENV/CAP/NEWCOMMAND 占位符 → `_revert_inputs`：栈式匹配 `<PLACEHOLDER_path_begin/end>`，把**翻译后的内文写回各自的 .tex 文件**，主文件里恢复 `\input{path}`——**保留原项目文件结构**，和 MathTranslate 的摊平覆盖相反。残留 `<PLACEHOLDER_*>` 打警告后删除。
- 中文：`\documentclass` 后插 `\usepackage[UTF8]{ctex}`；日语（注释掉的代码路径）：注释掉 inputenc/fontenc/times/mathptmx/`\pdfoutput`，documentclass 加 `lualatex` 选项 + `luatexja`。
- `LaTexCompiler.compile`：`latexmk -pdflatex -interaction=nonstopmode -file-line-error -synctex=1 -f -outdir=build_pdflatex`（cwd=主文件目录，`-f` 强制出 PDF）→ 无 PDF 则换 `-xelatex` → 再失败打 log 路径返回 None。成功写 `success.txt`（eval 脚本据此统计编译率）。**不区分 MiKTeX/TeXLive**——直接调 latexmk，装了就能跑；没有"引擎探测"逻辑。
- GUI：`src/gui/streamlit_app.py` 走 `src/runtime.py` 的同一条管线（event_callback 报进度）。

### 4.5 Prompt 设计精华（prompts.py）

三套基线 prompt（section/caption/env）条款高度重合，值得抄的条款：

- **只翻自然语言**：label/cite/ref/textbf/emph、数学环境、`$..$`、带单位的尺寸参数（`em,ex,in,pt,pc,cm,mm,dd,cc,nd,nc,bp,sp`，举例 `\vspace{-1.125cm}`、`[scale=0.58]`）一律不动；
- **特殊字符保形**：`\% \# \&` 不许改写法；
- **CJK 不兼容命令保原文**：`\hl{}`、`\ctext[RGB]{}{}` 等 soul/xcolor 系命令**参数不许翻**（中文进去会编译挂）——这是踩过坑的经验条款；
- **排版防爆**："在特殊符号前后加空格"条款，给了 `|special\_token|` 例子，防中文无空格长串撑破右边界；
- **人名保原语**（仅 section prompt）："Daya Guo" 不翻不转写不换序；
- 占位符条款统一第 10 条：`<PLACEHOLDER_CAP_…>`、`<PLACEHOLDER_ENV_…>`、`<PLACEHOLDER_…_begin/end>` 是人工占位符，不许受影响、必须保留；
- 禁止输出 ```latex 包裹。

结构化 prompt 还有两个：
- `set_need_trans_for_envs`（§4.1 的 judge）："忽略环境名只看内容" + 5 few-shot，只许输出 True/False；
- `retrans_error_parts`：[Original]/[Translation]/[Error] 三段输入协议 + 同一套 LaTeX 守则 + "只输出修订译文"；
- `extract_terminology`：给 src+tgt 抽 `"en" - "zh"` 对齐术语对（few-shot 两个），供 update_term 回路（已被 bug 关闭）。

### 4.6 评估脚本

`evaluation/scripts/exp_fc_score.py`：读 `build_*/​*.log` 数 Error/Warning 行，`score = 100 - 10*E - 2*W (+20 if 编译成功)`，跑 50 篇取均值——一个粗糙的"格式保持分"。`exp_cometkiwi_llmscore.py` 做语义质量分。

---

## 5. 宏展开策略正面对比

| 维度 | MathTranslate | LaTeXTrans |
|---|---|---|
| 主管线是否展开 | **受限展开**：定义体命中白名单子串才展开使用点 | **不展开**：定义藏进 `<PLACEHOLDER_NEWCOMMAND_i>`，使用点靠 LLM 自律 + Validator 数命令 |
| 匹配哪些定义 | `\newcommand`、`\def`（无 renewcommand/newenvironment） | 五个：newcommand/renewcommand/def/newenvironment/renewenvironment |
| 参数 | `[n]` 0-9 一位，`#i` 文本替换，两侧加空格 | （管线不展开；eval 用的 utils.process_newcommands 同款机制但**无条件全展开**） |
| 定义本体 | 藏哨兵→展开使用点→**贴回原文** | 占位符→重建时贴回 |
| 白名单 | equation/array/displaymath/align/multiple/gather/theorem/textcolor + environment_list + command_list | — |
| 动机 | 防止宏吞掉结构命令（\be 里的 equation 要不透明、\green 里的 textcolor 参数要翻） | 防 LLM 篡改定义；使用点是否被翻译由命令计数校验兜底 |
| 定理环境 | `\newtheorem{xxx}` 抓名 → env 白名单补入 | 交给 LLM judge 判 need_trans |

LaTeXTrans 仓库里其实**也有**一份 `process_newcommands`（utils.py:303，MathTranslate 同款但无白名单、全展开）——只服务 `extract_pure_text` 评估通路（把论文摊成纯文本算分），不进翻译管线。

---

## 6. 对我们的借鉴清单

**直接可抄（MathTranslate）：**
1. `get_pattern_brace` 递归子模式 + `get_pattern_command_full(name,n)` 动态拼 N 参命令——轻量、覆盖 `\cmd[opt]{a}{b}{c}` 全家桶，比我们手写栈扫描省代码；注意占有量词 `++` 防回溯。
2. **受限宏展开的判定规则**："定义体命中结构命令白名单才展开使用点、定义保留"——在"完全不展开"（使用点变不透明块、内容不翻）和"全展开"（易炸）之间是很聪明的折中，且规则可解释、可测（他们有 test_latex/ 的 input/ref 对照测试）。
3. 占位符工程细节：数字拆位加下划线、两侧垫空格、译后强制大写刷回、`modify_text` 只对非占位符段施加变换、recover 循环 subn 直到零替换 + 越界回填 `'???'` + n_bad 计数上报。
4. 腾讯 `UntranslatedText` 参数传占位符头——如果接腾讯/其他支持"不译标记"的引擎，白嫖保护。
5. 段落级 `ThreadPoolExecutor.map` + 逐段 sha256 缓存 + LRU 文档缓存——便宜的加速与断点续翻。
6. `charset_normalizer` 逐文件探测编码（arXiv 老论文大量 latin-1/gbk）。
7. 收尾 `裸 % → \%`、accent 统一花括号形式——译后修补小动作。
8. test_latex 的 input_*/ref_* 结对测试方式：一个 tex 输入 + 期望输出做 golden。

**直接可抄（LaTeXTrans）：**
9. **`\input` 双向 placeholder**：begin/end 包裹内联内容，重建时栈式配对写回独立文件——保住了项目文件结构（比 MathTranslate 摊平删除高明）；同时 `\include` 也支持。
10. **caption 先摘 → 含 CAP 的 env 判不翻**：一个顺序技巧同时解决"图环境不翻"和"图 caption 要翻"。
11. **黑名单 + LLM judge 双层 env 分类**：~40 个确定的 no_translate_envs 直接 False，未知 env 用 temp=0/50token/True-False 的便宜 judge——比我们纯规则表的泛化能力强，成本极低。
12. **Validator 三项对账**：pylatexenc 命令多重集比对（忽略 \eg/\ie/单字符非字母宏）+ 占位符集合差 + 栈式括号匹配（原文少查一类括号防误报）→ errors_report → **只重翻出错部件**（三段式 [Original]/[Translation]/[Error]）→ 复检，≤3 轮。这是 LLM 路线性价比最高的正确性装置。
13. **占位符恒等映射灌术语表**：`ph→ph` 塞 glossary，把"保留占位符"变成最高优先级术语约束——一个免费的双保险。
14. **按 arXiv category 选术语 CSV**（抓 abs 页 subjects）+ user_term 覆盖 + default 兜底——低成本术语对齐。
15. prompt 里的实战条款：CJK 不兼容命令参数不翻（\hl/\ctext）、尺寸参数不翻、特殊符号两侧加空格防撑行、人名保原语、禁止 ```latex 围栏。
16. `_merge_short_sections(min_tokens=50)` 合并碎段省调用；每完成一件即落盘 JSON 的断点续跑。
17. 编译 fallback 链 pdflatex→xelatex（ja→lualatex）+ `success.txt` 标记 + 从 log 数 Error/Warning 算格式分的评估法。

**两边的坑（要避开）：**
- env 正则在**同名环境嵌套**时截断（`\begin{proof}...\begin{proof}...\end{proof}...\end{proof}`）——递归子模式能解花括号但解决不了 begin/end 配对，必要时换 pylatexenc 或自写平衡扫描。
- LaTeXTrans 的 `sys.stderr = open(os.devnull,'w')` 到处开关 streamlit 进度条，工程味道很重；我们不用学。
- MathTranslate 的 translate() 是**无限重试死循环**；google 分支 `self.translator` 未赋值的疑似 bug。
- LaTeXTrans README 的"六 agent"与实际实现不符（Summarizer/TerminologyExtractor 是死代码，update_term 被 bug 钉死）——借鉴概念可以，别指望开箱即用。
- LaTeXTrans 不支持 `\chapter`（book 类论文会切不断）。
- MathTranslate 删 textbf/emph 换可译性——**格式真丢了**；LaTeXTrans 让 LLM 保命令的方式更稳但费 token。
- 两家都把"编译是否成功"挡在校验回路外（LaTeXTrans 有编译 fallback 但不回喂 LLM；MathTranslate 干脆让用户自己传 Overleaf）。如果我们做编译错误→LLM 修复闭环，就是差异化改进点。

---

## 7. 关键文件索引

LaTeXTrans（`/tmp/latex-refs/LaTeXTrans/`）：
- 管线编排：`src/agents/coordinator_agent.py:49-98`
- Parser：`src/formats/latex/parser.py`（LatexParser 全类）；agent 壳 + LLM judge：`src/agents/tool_agents/parser_agent.py:27-127`
- 正则积木 + 杂项：`src/formats/latex/utils.py:22-24`（brace）、`:466-524`（env/command/newcommand patterns）、`:288-334`（eval 用 process_newcommands）、`:573-602`（find_main_tex_file）、`:604-634`（merge inputs）
- Translator：`src/agents/tool_agents/translator_agent.py`（并发 :83-130；mode 分支 :383-558；term_dict :933-1003；死代码 summary/prev :750-931）
- Validator：`src/agents/tool_agents/validator_agent.py`（三项校验 :81-157；pylatexenc 计数 :173-210）
- 重建：`src/formats/latex/reconstruct.py`（回填 :48-76；inputs 栈式回写 :78-144；ctex/ja :133-188）
- 编译：`src/formats/latex/compile.py`（pdflatex→xelatex :11-42；ja lualatex :45-67）
- Prompts：`src/formats/latex/prompts.py`（全部；judge :161-225；retrans :227-273；术语抽取 :275-320；summary :322-353）
- 术语表：`terms/*.csv`（default 404 行等）

MathTranslate（`/tmp/latex-refs/MathTranslate/`）：
- 核心全部：`mathtranslate/process_latex.py`（patterns :8-48；replace/recover :110-180；env/command 处理 :215-292；special/accent :373-415；**process_newcommands :439-483**）
- 驱动：`mathtranslate/translate.py`（LatexTranslator 全类；translate_full_latex :217-278）
- 文件合并/bbl：`mathtranslate/process_file.py`
- 断句/超长段：`mathtranslate/process_text.py`
- arXiv 项目流：`mathtranslate/translate_arxiv.py`（translate_dir :58-92 删非主 tex、合 bbl）
- 缓存：`mathtranslate/cache.py`；编码：`mathtranslate/encoding.py`
- 引擎：`mathtranslate/tencent.py`（UntranslatedText :19）、`mathtranslate/google.py`（selenium 备用）
- golden 测试：`test_latex/input_*.tex` ↔ `ref_*.tex`
