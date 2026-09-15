# R11 · texlate 翻译层 prompt 套件与术语表设计规格

> 调研对象：`tmp/refs/LaTeXTrans`（prompts.py / translator_agent / parser_agent / parser / validator / terms/）、`tmp/refs/MathTranslate`（process_latex / translate / tencent / config）；辅助参考 `tmp/refs/ieeA`（translator/prompts.py / pipeline.py / rules/glossary.py / parser/structure.py）。
> 结论先行：**抄 LaTeXTrans 的「分类型 system prompt + 尾置占位符条款 + 三级术语表 + ph 恒等注入 + LLM 判 env + 三段式重翻」骨架；抄 ieeA 的「文档级术语表过滤 + 稳定前缀 + 编号批量 + state 断点」协议；MathTranslate 只借「占位符工程细节（垫空格/大写刷回/受限展开白名单）」。**

---

## 0. 一句话决策表

| 决策点            | 结论                                                                                                  | 出处                                                          |
| ----------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| prompt 组织       | 每种 chunk 类型一份 system prompt，共享公共条款块 + 类型专属条款                                      | LaTeXTrans `prompts.py`                                       |
| 占位符条款位置    | **放在条款列表尾部**（倒数第 1~2 条），利用近因效应                                                   | section prompt 第 10/11 条、env prompt 第 9/9 条              |
| 占位符硬约束      | prompt 条款是软约束，**真正硬约束 = 占位符 `ph→ph` 恒等映射灌进 glossary**（"glossary 是最高优先级"） | `translator_agent.py:add_placeholder()`                       |
| 术语表            | 三级：user CSV > arXiv category 匹配 > default.csv；两列无表头                                        | `build_term_dict()` + `terms/*.csv`                           |
| glossary 注入方式 | **文档级过滤后整表烤进 system prompt 尾部**（稳定前缀吃 provider 缓存），不要逐 chunk 拼装            | ieeA `pipeline.py`（修掉 LaTeXTrans 逐条拼 dict repr 的糙法） |
| env 可译性判定    | 规则黑名单先判，判不定的 env 交 LLM（temp=0、只答 True/False、few-shot、**失败默认 True**）           | `parser_agent.py` + `set_need_trans_for_envs_system_prompt`   |
| 段内"该不该翻"    | 不学 LaTeXTrans 问 LLM；用 MathTranslate 廉价规则（无拉丁字母跳过/全大写跳过），只对灰区上 LLM        | `translate.py:45` `process_text.py`                           |
| 带错重翻          | `[Original]/[Translation]/[Error]` 三段式 user prompt + 专用 corrector system prompt，≤3 轮           | `retrans_error_parts_system_prompt` + coordinator             |
| 批量              | <300 字符短块打包编号批量 `[1]…[2]…`（≤2000 字符/批），解析失败整批回退单翻                           | ieeA `pipeline.py`（docs/02 已预定此路线）                    |
| 并发              | Semaphore 10~50；**首发单飞暖前缀缓存，其余并发**；429 特判退避                                       | LaTeXTrans sem=10 / ieeA sem=50 + warmup                      |
| 断点              | state JSON 逐块落盘 `{version, meta, completed[], results[]}`；map 落盘格式学 LaTeXTrans 五表         | ieeA v2.1 schema / LaTeXTrans `*_map.json`                    |
| temperature       | 翻译 0.2~0.3（LaTeXTrans 用 0.7，对格式保真偏激进）；judge/提取一律 0                                 | `translator_agent.py`                                         |

---

## 1. LaTeXTrans 挖掘结果（证据）

### 1.1 prompts.py 全部 prompt 清单

`src/formats/latex/prompts.py` 共 15 个 system prompt，由 `init_prompts(source_lang, target_lang)` 填充语种（`en→English`、`ch→Chinese`）。按用途分四组：

| prompt                                                       | 用途                                                            | 条款数    | 占位符条款位置                       |
| ------------------------------------------------------------ | --------------------------------------------------------------- | --------- | ------------------------------------ |
| `caption_system_prompt`                                      | \caption/\title/\keywords 等短文本                              | 9         | 第 8 条                              |
| `section_system_prompt`                                      | 正文 section 长文                                               | 11        | **第 10 条**（人名条款第 11 条压轴） |
| `env_system_prompt`                                          | 可译 env 内容                                                   | 9         | 第 9 条（末条）                      |
| `caption/section/env_system_prompt_with_dict`                | 上述三者的术语表版（结构相同，靠调用方在尾部追加 `<Glossary>`） | 9/10/9    | 8/10/9                               |
| `section/caption/env_system_prompt_with_sum`                 | 带滚动摘要版（首段加 "authoritative summary" 指令）             | 10/9/9    | 10/8/9                               |
| `section_system_prompt_with_terms_sum`                       | 术语表 + 摘要双注入版                                           | 10        | 10                                   |
| `section_system_prompt_with_prev / _terms_prev`              | 带前段上下文版                                                  | 10/10     | 10                                   |
| `set_need_trans_for_envs_system_prompt`                      | **LLM 判 env 可译性**                                           | —         | —                                    |
| `retrans_error_parts_system_prompt`                          | 带错重翻 corrector                                              | 10 条规则 | 第 10 条                             |
| `extract_terminology_system_prompt`                          | 从 src→tgt 对齐句对抽双语术语                                   | —         | —                                    |
| `get_summary_system_prompt` / `refine_summary_system_prompt` | 滚动摘要（≤300 词）                                             | —         | —                                    |

**公共条款块逐条列出**（以 `section_system_prompt` 为基准，caption/env 是同构裁剪）：

1. `Only translate the natural language content while keeping all LaTeX commands, environments, references, mathematical expressions, and labels unchanged.`（只翻自然语言）
2. `Section headings ... must also be translated, but their LaTeX syntax must remain unchanged.`（仅 section 版有：标题要翻、语法不动）
3. `Do not translate or modify the following LaTeX elements:` 枚举三类的"不翻清单"——
    - `Control commands: \label{}, \cite{}, \ref{}, \textbf{}, \emph{}, etc.`
    - `Mathematical environments: $...$, \[…\], \begin{equation}...\end{equation}, etc.`
    - `Any parameter or argument that includes numerical values with LaTeX layout units such as: em, ex, in, pt, pc, cm, mm, dd, cc, nd, nc, bp, sp. Example: \vspace{-1.125cm} or [scale=0.58] → leave such expressions completely unchanged.`（尺寸单位枚举非常具体，值得抄）
4. `Do not change the writing of special characters, such as "\%", "\#", "\&", etc.`
5. `For highlighting commands or style-related LaTeX commands (such as \hl{...}, \ctext[RGB]{...}{...}, and other custom commands based on soul, xcolor, etc.) that are known to fail with {target_lang} characters, do not translate their arguments. Keep the original {source_lang} content inside these commands.`（已知与 CJK 冲突的宏，参数保原语——防编译炸）
6. `Please add appropriate spaces before and after special symbols ... "| special\_token| <reasoning\_process> | ..."`（特例条款：特殊符号两侧垫空格防编译后无法换行——这是中文排版真实痛点，hjfy 场景独有）
7. `The final output must be a valid and compilable LaTeX document.`
8. `Ensure that the translated text is accurate, coherent, and follows academic writing conventions ... consistent academic terminology ...`
9. `Directly output only the translated LaTeX code without any additional explanations, formatting markers, or comments such as "```latex".`
10. **占位符条款**（原文）：
    > `<PLACEHOLDER_CAP_...>,<PLACEHOLDER_ENV_...>,<PLACEHOLDER_..._begin> and <PLACEHOLDER_..._end> are placeholders for artificial environments or captions. Please do not let them affect your translation and keep these placeholders after translation.`
11. **人名条款**（仅 section 版，压轴第 11 条）：
    > `Name retention principle,always keep author names (e.g., "Daya Guo", "Dejian Yang") in their original {source_lang} form. Never translate, transliterate, or reorder names (e.g., "Daya Guo" → "Daya Guo", NOT "郭达雅" or "Guo Daya").`

**条款位置规律**：占位符条款在 section 版放第 10/11 条、env 版放第 9/9（末条）、caption 版第 8/9。**始终压在条款列表尾部**——与 docs/04 "放第 10 条效果最好"的笔记吻合：不是"必须第 10"，而是"必须在尾部、且全文唯一一次出现"（三个 prompt 里措辞一字不差）。

caption 版与 section 版差异：无"标题要翻"条款、无人名条款、任务描述换成 "concise LaTeX texts ... paper titles, figure titles, and table titles"。env 版同 section 但无标题条款/人名条款。

### 1.2 term_dict 三级体系

`translator_agent.py:build_term_dict()`：

```text
user_term (CLI --config user_term=xxx.csv)         → 独占加载，不走下面两级
└─ 否则 config["category"][arxiv_id] (abs 页爬的 subjects)
   ├─ 逐 category 试 terms/{category}.csv，命中即 update（多 category 并集，先命中先写）
   └─ 一个都没中 / 无 category → terms/default.csv
```

- **CSV 格式**：两列无表头 `English Term,Chinese Translation`，`pd.read_csv(header=None)`。
- **体量**：`default.csv` 404 行、`cs.LG` 357、`cs.RO` 354、`cs.ML` 305、`cs.AI` 212、`cs.CV` 158，合计 ~1790 行人工对。内容含"保原语"型条目（`AGI,AGI`、`Canny,Canny`）。
- **category 来源**：`utils.get_arxiv_category()` 爬 `arxiv.org/abs/{id}` 的 `div.subjects`，正则 `\(([a-z]+\.[A-Z]+)\)` 提取，得 `{arxiv_id: [cs.CV, cs.LG]}`。
- **注入方式**（糙但有效）：把整个 `term_dict` 的 **Python dict repr** 拼进 system prompt 尾部——
  `"...you must strictly use the following glossary for substitution. This is the highest priority rule to ensure the consistency of terms throughout the text.\n<Glossary>:\n{self.term_dict}\nNow, please translate the following new paragraph..."`，user 消息为 `[Current LaTeX Paragraph]:\n{text}`。
- **运行时增广**（trans_mode 2 + update_term）：每翻完一段，用 `extract_terminology_system_prompt` 从 src/tgt 对齐文本抽 `"en" - "zh"` 词对，并入 `term_dict`（已存在不覆盖），落盘 `term_dict.json`。注：代码有 bug（`update_term` 置 True 后立即置 False），等于该路径实际未启用——**可借鉴思路，不抄实现**。

### 1.3 add_placeholder() 恒等注入（全文最妙的一招）

`translator_agent.py:966-1003`：执行翻译前，读 `inputs_map.json`（取 `begin`/`end`）、`envs_map.json`、`captions_map.json`、`newcommands_map.json`（各取 `placeholder`），然后：

```python
for item in placeholder_list:
    self.term_dict[item] = item   # ph → ph 恒等映射
```

即 `<PLACEHOLDER_CAP_1> → <PLACEHOLDER_CAP_1>` 作为术语条目进 glossary。由于 prompt 宣称 "glossary 是最高优先级规则"，**占位符保护从"请你别动"的软约束升级为"术语替换表规定它映射到自身"的硬约束**。零额外 token 成本（占位符本来就少），直接抄。

### 1.4 need_trans LLM 判定

- 规则先判（`parser.py:_extract_envs`）：env 命中黑名单（equation/align/gather/verbatim/lstlisting/minted/figure/tikzpicture/tabular/longtable/algorithm/thebibliography 全族 ~30 个）或**体内含 CAP 占位符** → `need_trans=False`。env 正则本身排除 `document/center/proof/multicols`（proof 留在正文里随段翻）。
- LLM 复判（`parser_agent.py`）：所有 `need_trans=True` 且 env_name ∉ `{abstract, itemize}` 的 env，逐个问 LLM。参数：**temperature=0、max_tokens=50、回答 `true/false` 小写比对、解析不出或请求失败一律返回 True（fail-open 宁翻勿漏）**。
- prompt 原文要点（`set_need_trans_for_envs_system_prompt`）：判 **content 而非 env name**（"Environment names can be custom-defined ... should be ignored"）；True=含自然语言句子；False=纯 code/math/tikz/标记；5 个 few-shot（mybox 定义句→true、customcode for 循环→false、randomenv \draw→false、something 含 \caption→true、eqnarray 纯公式→false）。

### 1.5 分段粒度与落盘协议

- **粒度是"section 级"不是段落级**：`_split_to_sections` 按 `\section|\subsection|\subsubsection` 切，编号 `"1"/"1_2"/"1_2_3"`；`"-1"`=preamble（\begin{document} 前）、`"0"`=首个 \section 前的正文头，**这两段文本本身不送 LLM（trans_content=content），但段内的 caption/env 照常摘出送翻**——\title、abstract env 就是这样翻掉的；`_merge_short_sections(min_tokens=50)`（tiktoken gpt-4 编码）把碎段并掉。
- **占位符四类**：`<PLACEHOLDER_CAP_n>`（caption/subcaption/title/keywords/abstract/icmltitle 命令整体）、`<PLACEHOLDER_ENV_n>`（整个 env）、`<PLACEHOLDER_{file}_begin/end>`（\input 展平时的文件边界标记）、`<PLACEHOLDER_NEWCOMMAND_n>`（\newcommand/\def/\renewcommand/\newenvironment 定义整体，**不展开**，靠 LLM 自律 + validator 数命令兜底）。
- **抽取顺序技巧**：先 `_extract_captions` 后 `_extract_envs` → figure/table 的 caption 已被摘成 CAP，env 内含 CAP → need_trans=False → "图表环境不翻但 caption 单独翻"自动成立。
- **落盘五表**（每完成一个 section 整表重写）：`sections_map.json` `[{section, content, trans_content}]`、`captions_map.json` `[{placeholder, cap_type, content, trans_content}]`、`envs_map.json` `[{placeholder, env_name, content, trans_content, need_trans}]`、`inputs_map.json` `[{command, begin, end, path}]`、`newcommands_map.json` `[{placeholder, name, content}]`；外加 `errors_report.json`、`term_dict.json`。
- **并发**：`asyncio.Semaphore(10)` 裹 section 级任务；每个 section 内部先串行翻其 envs、再串行翻其 captions（嵌套依赖——env/caption 翻译挂在所属 section 任务里）。
- **重试/回环**：单次请求 3 试、间隔 5s、超时 100s；失败登记 `fail_{section_nums,caption_phs,env_phs}` 并回退原文；全部翻完后 `_val_fail_parts` 对失败件重翻 ≤3 轮。coordinator 层还有 Validator→`trans_mode=1` 带错重翻→再验 的外环（≤3 轮）。
- **Validator 三账**（`validator_agent.py`）：①命令多重集 diff（pylatexenc 数 `\macro`+`\begin/\end{env}` 次数，忽略 `\eg \ie` 和单字符非字母宏）②占位符集合差集（缺/多双向）③括号栈（原文只查 `{}` `[]`，译文加查 `()`）。错误格式化为文本喂回重翻。

---

## 2. MathTranslate 挖掘结果（证据）

### 2.1 受限展开白名单

`process_latex.py:process_newcommands`：对每条 `\newcommand/\def` 定义，**仅当定义体 `content_all` 命中白名单子串时才在使用点展开**：

```python
replace_newcommand_list = ['equation', 'array', 'displaymath', 'align',
                           'multiple', 'gather', 'theorem', 'textcolor'] \
                          + environment_list + command_list
# environment_list = ['abstract','acknowledgments','itemize','enumerate',
#                     'description','list','proof','quote','spacing']
# command_list     = ['section','subsection','subsubsection','caption',
#                     'subcaption','footnote','paragraph']
need_replace = any(special in content_all for special in replace_newcommand_list)
```

动机：`\be→\begin{equation}`、`\thm→\begin{theorem}` 这类别名宏不展开的话，保护/翻译规则套不上。命中后 `replace_newcommand` 做 `#i→ {text}` 参数代入（**代入文本两侧垫空格**），定义本体先用 `XMATHX_REPLACE{i}_NEWCOMMAND` 藏起防误伤，展开完再还原。\newtheorem 声明的定理环境名由 `get_theorems` 收集后并入可译 env 列表。

### 2.2 占位符工程细节

- **占位符形态**：`XMATHX_1_2_3`——`variable_code(count)` 把序号按位拆开用 `_` 连接（123→`XMATHX_1_2_3`）。还原正则 `XMATHX_(\d+(?:_\d+)*)*` 把数字串拼回整数索引——**即便 MT 引擎吃掉/插入部分分隔符也能恢复**，这是对"无纪律 MT 引擎"的鲁棒设计。
- **两侧垫空格**：`replaced_objs.append(f' {latex_obj} ')`、`pattern.sub(' ' + variable_code(count) + ' ', text, 1)`——占位符两侧强制空格，防 MT 把占位符和相邻单词粘连成不可还原形态。
- **译后归一**：`replace_with_uppercase(text, math_code)`（IGNORECASE 正则刷回全大写）——MT 可能把 `XMATHX` 改小写/变形。
- **腾讯 UntranslatedText API**：`tencent.py` 设 `request.UntranslatedText = config.math_code`——腾讯翻译 API 原生支持"不翻标记"，命中该子串的 token 原样透传。**有原生 support 的引擎优先用原生机制，prompt 层只是兜底**。
- **特殊字符编码**：`\% \# \& \\ \{ \}` 等 → `XMATHXPC XMATHXNB XMATHXAD XMATHXBS XMATHXLB XMATHXRB`（垫空格包围）；变音符号 `\"o` → `XMATHXDQo`。译后 `recover_special/recover_accent` 还原；`%` 最后统一 `\%` 兜底。
- **recover 循环**：`recover_latex_objects` 用 `pattern.subn` 循环替换直到 0 命中（对象内可嵌占位符），并统计 `n_bad/ntotal` 报"N/M latex object correctly translated"。
- **杂项启发式**：`\pm→$\pm$`（防裸命令）、`Eq.→equation`（防句号断句）、译后裸 `_→\_`、`\n` 合并规则（下一行非 `XMATHX` 开头则并入上行）、`\textbf/\textit/\emph` 直接脱壳保留内容。

### 2.3 分段粒度与 texlate 对比

| 维度             | MathTranslate                                           | LaTeXTrans                                                      | texlate（已定架构）                                 |
| ---------------- | ------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------- |
| 最小翻译单元     | 段落（`\n\n+` 切，`\item` 再切）                        | section 级                                                      | **段落级 chunk**（docs/02）                         |
| 占位符           | `XMATHX_d_d_d` 万物皆替（env/命令/花括号/数学全对象化） | `<PLACEHOLDER_{CAP,ENV,...}>` 只替 env/caption/input/newcommand | `[[TYPE_n]]` 选择性保护（math/cite/ref/env/author） |
| 正文内残余 LaTeX | 几乎没有（全对象化）                                    | 大量残留靠 LLM 自律                                             | 同 LaTeXTrans（inline 命令留给 LLM）                |
| 不翻判定         | 白名单 env/command 才翻内容，其余对象化                 | 黑名单 env 不翻 + LLM 判未知 env                                | 黑名单 + LLM judge                                  |
| 引擎             | 传统 MT（google/腾讯）                                  | LLM                                                             | LLM                                                 |

texlate 取中：粒度=MathTranslate 的段落级（不是 LaTeXTrans 的 section 级——section 级单请求 8k token 太粗、上下文稀释、断点粒度差）；占位符密度=LaTeXTrans 的选择性保护（不是 MathTranslate 的全对象化——LLM 有纪律，过多占位符反而稀释注意力）。

---

## 3. Spec A：texlate prompt 套件

### 3.1 套件结构：公共条款块 + 类型专属块

六种 chunk 类型 → 六份 system prompt。**公共条款块（C1–C8）逐字共享**（便于维护 + 前缀缓存），类型差异通过 (a) 任务首句、(b) 追加专属条款 实现。

```text
system_prompt(kind) = TASK_SENTENCE[kind]
                    + COMMON_CLAUSES (C1..C8, 逐字固定)
                    + KIND_CLAUSES[kind]      # 0~2 条
                    + PLACEHOLDER_CLAUSE      # 压轴, 见 3.2
                    + NAME_CLAUSE             # 仅 para/abstract
                    + GLOSSARY_BLOCK          # 见 §4, 追加在最末
```

**公共条款块草案**（英文，照 LaTeXTrans 条款改写；`{SRC}/{TGT}` 由 init 期填充）：

````text
You are a professional academic translator specializing in LaTeX-based scientific writing.
{TASK_SENTENCE}
Please strictly follow the following requirements when translating:
C1. Only translate the natural language content. Keep all LaTeX commands,
    environments, references, mathematical expressions, and labels unchanged.
C2. Do not translate or modify:
    - Control commands: \label{}, \cite{} and its variants (\citep, \citet,
      \citealp...), \ref, \eqref, \autoref, \cref, \pageref, \nameref, \url,
      \textbf, \emph, etc.
    - Math: $...$, \(...\), \[...\], \begin{...}...\end{...} math environments.
    - Any argument containing LaTeX layout units: em, ex, in, pt, pc, cm, mm,
      dd, cc, nd, nc, bp, sp (e.g. \vspace{-1.125cm}, [scale=0.58] → unchanged).
C3. Do not change escaped special characters: \%, \#, \&, \_, \{, \}, etc.
C4. For style commands known to break with {TGT} characters (\hl{...},
    \ctext[RGB]{...}{...}, soul/xcolor-based custom commands), do not translate
    their arguments; keep the original {SRC} inside.
C5. Add appropriate spaces around special symbols (e.g. "| special\_token |
    <reasoning\_process>") so the compiled {TGT} text can wrap correctly.
C6. The output must be valid, compilable LaTeX.
C7. Keep accurate, coherent academic {TGT} with consistent terminology and
    standard abbreviations.
C8. Output only the translated LaTeX — no explanations, no "```latex" fences,
    no comments.
````

**各类型专属条款**：

| kind                        | TASK_SENTENCE                                                                        | 专属条款                                                                                                                                              |
| --------------------------- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `para` 正文段               | "translate the following LaTeX paragraph(s) from {SRC} to {TGT}"                     | + K1: 人名保原语条款（见 3.3）                                                                                                                        |
| `caption`                   | "translate concise LaTeX texts such as figure/table captions and titles"             | 无（短文本，C 块已够）                                                                                                                                |
| `section_title`             | "translate the heading text inside \section/\subsection-style commands"              | + K2: `Translate only the text inside the braces of the heading command; keep the command, its optional argument [], and any \label unchanged.`       |
| `abstract`                  | "translate the abstract of an academic paper"                                        | + K1 人名条款；+ K3: `Keep it as one fluent paragraph; preserve \keywords structure if present.`                                                      |
| `table_text` 表格内文本     | "translate the natural-language cell text inside the following LaTeX table fragment" | + K4: `Never touch &, \\, \hline, \multicolumn, \cline and column specs ({l c r p{...}}); translate cell text only. Keep row/column count identical.` |
| `env_text` 判可译的未知 env | "translate the natural-language content inside the following LaTeX environment"      | + K5: `Keep \begin{...}/\end{...} and all structural commands inside unchanged; translate only human-readable sentences.`                             |

注：`table_text` 是新能力——LaTeXTrans/MathTranslate 都直接不翻 tabular。texlate 若做 M2+ 表格内文本翻译，必须用 K4 强约束 + validator 行/列数对账，否则 `&`/`\\` 必炸。**建议 v0 先不翻表格内文本，prompt 先备好。**

### 3.2 占位符契约条款——最终措辞

放每份 prompt 的**条款列表末位**（专属条款之后、glossary 块之前），全文档措辞逐字一致：

```text
C9. [[TYPE_n]] tokens (e.g. [[MATH_12]], [[CITE_3]], [[REF_7]], [[ENV_4]],
    [[AUTHOR_1]], [[SL]], [[PL]]) are placeholders for protected LaTeX
    fragments or structural markers. Do not translate, modify, reorder,
    split, merge, add, or remove any of them, and do not let them influence
    the surrounding translation. Every placeholder in the input must appear
    verbatim in your output.
```

措辞依据：①枚举真实 token 形态（比 LaTeXTrans 的 `<PLACEHOLDER_...>` 通配更具体——模型不需要猜模式）；②动词清单 `translate, modify, reorder, split, merge, add, remove` 覆盖 validator 会查的全部破坏方式（缺/多/移位/拆并）；③"must appear verbatim" 与 glossary 恒等映射互为表里。`[[SL]]/[[PL]]` 若采用 ieeA 换行编码则一并列入（见 §6 协议层决定——若换行不进 prompt 层则从枚举里删掉）。

### 3.3 人名保原语条款（para/abstract 末条）

```text
C10. Name retention: always keep person names (e.g., "Daya Guo") in their
     original {SRC} form. Never translate, transliterate, or reorder them.
```

### 3.4 带错重翻协议

System prompt（专用 corrector，不改共享块——重翻的语境不同）：

```text
You are a professional academic translator and LaTeX translation corrector.
You receive the original {SRC} LaTeX fragment, its current {TGT} translation,
and error information. Output only the corrected {TGT} LaTeX — preserve all
LaTeX syntax and all [[TYPE_n]] placeholders verbatim; fix only what the
[Error] section reports (plus obvious collateral issues it implies).
Input format:
[Original]
<original {SRC} LaTeX>
[Translation]
<current {TGT} LaTeX>
[Error]
<missing/extra placeholders, command mismatches, bracket errors, ...>
```

User 消息组装（照 `translator_agent.py:664`）：

```text
[Original]:
{content}
[Translation]:
{trans_content}
[Error]:
{command_error\nph_error\nbracket_error}   # validator 三类错误原文拼接
```

温度建议 0.2；重翻轮上限 3（coordinator 外环）；仍败→回退原文并记 `fault` 标记进 state。

### 3.5 批量请求的编号协议（短块打包）

照 ieeA：短 chunk（<300 字符）打包为编号批量，user 文本 `[1] xxx\n[2] yyy`，context 前置 `请翻译以下编号内容，保持相同的编号格式返回。`；响应以 `\[(\d+)\]\s*(.+?)(?=\[\d+\]|$)` 解析，**数量不符或序号越界→整批回退逐条单翻**。批量场景复用 `para` prompt + 批量指令（不要为批量再造一套条款）。

---

## 4. Spec B：术语表设计

### 4.1 三级来源与优先级

```text
① 用户表  ~/.texlate/glossary.yaml 或 --glossary user.csv    → 最高优先，独占式覆盖同名条
② arXiv category 表  terms/{primary_cat}.csv (+ 次 category 并集)
③ 内建默认表  terms/default.csv                              → 兜底
```

- 匹配键：arXiv abs 页 `div.subjects` 提取 category（照 `get_arxiv_category`），按声明顺序逐个映射 `terms/{cat}.csv`；多 category **并集合并、先命中先写**（一级 category 语义权重最高）。
- 文件格式：**CSV 两列无表头 `en,zh`**（与 LaTeXTrans 语料兼容，可直接搬 `terms/*.csv` 种子）；用户表额外允许 ieeA 风格 yaml（`term: target` 或 `{target, context, domain, priority, notes}` 结构体），内部统一成 `Dict[en, entry]`。
- 冲突解决：user > category > default；同层并集先写者胜（dict update 语义）。
- **"保原语"条目是一等公民**（`AGI,AGI`/`LLM,LLM`/`Canny,Canny`）——缩写和模型名靠它们防音译，种子表必须含。

### 4.2 占位符恒等注入

翻前准备阶段（glossary 物化时）：

```python
for ph in all_placeholders_in_doc:      # [[MATH_n]] [[CITE_n]] ... + [[SL]] [[PL]]
    glossary[ph] = ph                    # ph → ph 恒等映射, 优先级最低(不覆盖真术语)
```

注入后 glossary 尾部追加到 system prompt（见 4.3）。占位符集合随文档物化一次性固定——顺序按 `TYPE` 字典序再按 `n` 数值序（**稳定排序是前缀缓存命中前提**）。

### 4.3 注入方式：文档级过滤 + 整表烤进（修 LaTeXTrans 之糙）

不抄 LaTeXTrans 的两点：逐 chunk 把 `dict` repr 拼 prompt（格式丑、前缀不稳）；逐条请求现拼。改抄 ieeA：

1. **文档级过滤**：翻译启动时扫全部 chunk 源文本，用 `(?<!\w)term(?!\w)`（IGNORECASE|ASCII）筛出本文实际出现的术语 → `doc_glossary`。**整篇文档过滤一次**，而非逐 chunk——保证 system prompt 恒定。
2. **烤进 prompt**：`doc_glossary` 序列化为 `- en: zh` 行表（弃 dict repr），追加在 system prompt 末尾：

    ```text
    When translating, you must strictly use the following glossary. This is the
    highest-priority rule for terminology consistency.
    <Glossary>:
    - {en}: {zh}
    ...
    - [[MATH_3]]: [[MATH_3]]     ← 恒等注入的占位符混在表里
    ```

3. **前缀缓存友好**：system prompt 全文（公共条款 + 专属条款+glossary）在整篇文档翻译期间**逐字节不变**；Anthropic 走 `cache_control` 块标记，OpenAI/DeepSeek 靠自然前缀命中（ieeA 实证路径）。批量/单翻两个 prompt variant 各自物化并 warmup。

### 4.4 用户编辑界面

- CLI：`--glossary path.csv|yaml`（对应 LaTeXTrans `user_term`）；`texlate glossary show/edit` 子命令读写 `~/.texlate/glossary.yaml`。
- 论文级覆盖：`output/{paper}/glossary.local.yaml` 存在则并入（优先级介于 user 与 category 之间——用户针对单篇的修正不该污染全局）。
- 翻译产物附带 `term_dict.json` 落盘（用了哪些术语，可追溯）。
- 运行时术语自增（可选开关，修掉 LaTeXTrans 的 bug 版）：翻完每段用 `extract_terminology_system_prompt` 式抽取 `"en" - "zh"` 对，新词并入**本文档 glossary 副本**（不回写用户表）；落盘 `glossary.extracted.json` 供用户审后手动 promote。**默认关**——自动抽取词对质量参差，污染全局表得不偿失。

### 4.5 种子术语表

直接搬 LaTeXTrans `terms/` 六表作初始资产（default 404 + cs.LG 357 + cs.RO 354 + cs.ML 305 + cs.AI 212 + cs.CV 158）；覆盖缺口按 bench/corpus 的 category 分布补（hep-th、math.*、cond-mat、eess 等 LaTeXTrans 没有的领域后续众包扩）。category→文件映射表做成 `terms/index.yaml`（cat → [file, ...]），加领域不改代码。

---

## 5. Spec C：LLM-judge 设计

### 5.1 判定分工表

| 判定                   | 首选手段                                                                                        | LLM 出场时机                                                            |
| ---------------------- | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| env 可译性             | 黑名单（math/verbatim/figure/table/algorithm/bib 全族不翻；proof/itemize 等白名单直接翻）       | **黑白名单都不中的未知 env → LLM judge**（抄 LaTeXTrans）               |
| 段内是否含可译自然语言 | 规则：`.*[a-zA-Z].*` 无拉丁字母跳过；全大写跳过；纯占位符 chunk 跳过（`^\[\[[A-Z_]+_\d+\]\]$`） | 一般不需要——规则覆盖面已够，灰区（如夹杂公式的短句）默认翻（fail-open） |
| 宏是否透明（参数可译） | 宏表静态分析（体含 text 类命令→透明）                                                           | M2+ 可考虑，v0 不做                                                     |
| 术语抽取               | —                                                                                               | 可选开关（§4.4）                                                        |
| 编译修复               | 规则表先匹配                                                                                    | 未命中→LLM 修复器（docs/02 已定，不属本 spec）                          |

### 5.2 env 可译性 judge——prompt 与 few-shot

直接沿用 LaTeXTrans prompt（§1.4 已录要点），按 texlate 语境改写三处：语种参数化、`Input:` 改喂 env 全文（含 `\begin/\end`）、few-shot 增补 LaTeXTrans 没覆盖的灰区。**完整草案**：

```text
You are a LaTeX translation assistant.
Your task is to analyze the content inside a LaTeX environment and decide
whether it should be translated when translating an academic paper from {SRC}
to {TGT}. Ignore the environment name itself (it may be custom-defined);
judge only the content.

Return `True` if the content contains human-readable natural language that
contributes meaning (explanations, definitions, theorem statements,
descriptions). Return `False` if it contains only code, markup, math,
drawing instructions, or other non-linguistic content.

Output exactly `True` or `False`. No explanations.

Examples:

Input:
\begin{mybox}
A graph is connected if there is a path between every pair of vertices.
\end{mybox}
True

Input:
\begin{customcode}
for i in range(10):
    print(i)
\end{customcode}
False

Input:
\begin{randomenv}
\draw[->] (0,0) -- (1,1);
\end{randomenv}
False

Input:
\begin{something}
\caption{The architecture of our model.}
\includegraphics{fig1.png}
\end{something}
True

Input:
\begin{resultblock}
We observe a 12\% relative improvement over the strongest baseline.
\end{resultblock}
True

Input:
\begin{eqnarray}
\bm{x}_{regressor}=[\bm{h}_{\hat{y}};\bm{h}_x]
\end{eqnarray}
False
```

调用参数：**temperature=0、max_tokens=16**（LaTeXTrans 给 50，够用即可）、3 次重试；解析 `output.strip().lower()` ∈ {`true`,`false`}，**其余一律 True（fail-open 宁翻勿漏）**。判 False 的 env 整体对象化为 `[[ENV_n]]`（不走内容翻译），判 True 的按 `env_text` chunk 类型送翻。

---

## 6. Spec D：批量 / 并发 / 断点续翻协议

### 6.1 批量协议

```text
分桶：content < 300 字符 → short 桶; 否则 long 桶
打包：short 桶按累计 ≤2000 字符贪心装箱为 batch（编号 [1]..[n]）
发送：batch 走编号批量协议 (§3.5); long 逐条单翻
回退：batch 解析失败/数量不符 → 整批退化为逐条单翻 (复用并发额度)
跳过：纯占位符 chunk 不发请求，translation=source 直接落盘
```

### 6.2 并发与缓存暖机

- `asyncio.Semaphore(N)`，N 默认 10（LaTeXTrans 值；按 provider 限额可调 10~50）。
- **首发单飞**：第一个请求单独 await 完成后再并发其余——服务端前缀缓存建立后，后续请求白吃缓存（ieeA warmup 模式）。
- 退避：指数 `retry_delay * 2^attempt`（429/rate-limit 用 `3^attempt`、下限 5s；timeout 下限 10s）；单请求 3~5 试，失败→回退原文 + 记 `skipped`+`skip_reason`，不阻塞整批。
- temperature：翻译 0.2~0.3（LaTeXTrans 用 0.7——对"保 LaTeX 结构"任务偏激进；无实测依据前取保守值，模型横评再调）；judge/术语抽取 0。
- 字数上限：单请求输入 ≤2000 字符（MathTranslate char_limit；LLM 可放宽到 ~4000 但批量一致性好维护），超限 chunk 按句界二分（优先大写开头处切，照 `split_too_long_paragraphs`）。

### 6.3 断点续翻与落盘

**state 文件**（`output/{paper}/state.json`，每完成一块原子重写）：

```json
{
  "version": "1.0",
  "meta": {"model": "...", "pipeline_version": "...", "started_at": "...",
           "finished_at": "...", "total_chunks": 137},
  "completed": ["chunk_id", ...],
  "results": [{"chunk_id": "...", "source": "...", "translation": "...",
               "metadata": {"kind": "para", "batched": true, "batch_id": "batch_3",
                            "skipped": false, "glossary_hits": 4}}],
  "errors_report": [{"chunk_id": "...", "command_error": "...", "ph_error": "...",
                     "bracket_error": "..."}]
}
```

- 续翻：`completed` 集合命中即跳过；`results` 重建 results_map，按 chunk 序拼接输出。
- **中间产物五表**学 LaTeXTrans 命名（`sections_map` 概念换成我们的 chunks）：`chunks_map.json`（含 kind/content/translation/status）、`placeholders_map.json`（ph→原片段 + 类型）、`glossary.json`、`state.json`、`errors_report.json`——重建器只读 map 表，不依赖内存态。
- 缓存键粒度：chunk 级 `sha256(content + model + prompt_version)`（MathTranslate 段级 hash 思路），命中直接填 translation——同一论文换模型重翻/中断重跑都受益。
- 修复回环：validator 三账（命令多重集/占位符差集/括号栈，照 LaTeXTrans 清单 + docs/04 补 cite/ref key diff、math env 配对、长度比）→ errors_report → 三段式重翻 ≤3 轮 → 仍败回退原文 + `fault` 标记。

### 6.4 换行编码（待裁决项，建议采纳）

ieeA 把 `\n`/`\n\n` 编码为 `[[SL]]`/`[[PL]]` 再送翻——防止 LLM 自由增删换行破坏段落边界，且译后计数对账（source_sl/pl vs decoded_sl/pl）。texlate chunk 已按空行分段，段内单行 `\n` 在 LaTeX 语义上是空格——**建议采纳仅对 `[[SL]]`：段内换行编码保护，送翻前编码、回来解码；`[[PL]]` 不需要（分段边界在 chunk 层管理）**。若采纳，占位符条款枚举含 `[[SL]]`（§3.2 已预留）。

---

## 7. 风险与开放项

1. **glossary 体积**：default+category 并集 ~~500 条 ≈ 3~~4k token/请求。短块批量时 glossary 可能超过正文体积——接受（一次烤进吃缓存），但需留意超小 provider 上下文。
2. **占位符 vs 译文流畅度**：`[[MATH_n]]` 隔断句子时 LLM 可能出翻译腔。MathTranslate 的解法是垫空格；对 LLM 可在 user 文本中给占位符两侧保留天然空格（scanner 产出时保证）。
3. **prompt_version 入缓存键**：条款措辞任何改动必须 bump `prompt_version`——否则 chunk 缓存命中旧 prompt 产物，不可复现。
4. **table_text/section_title/abstract 的 validator 对账项**：表格要加 `&`/`\\` 计数、标题要加命令名 diff——随 chunk kind 配置对账表（validator spec 的事，这里登记需求）。
5. **update_term 自增**：LaTeXTrans 实现了但没启用（bug）；我们默认关、留接口（§4.4）。
