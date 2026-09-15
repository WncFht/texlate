# arxiv-to-prompt 解剖报告

> 对象：`arxiv-to-prompt` 0.14.1（PyPI，作者 Takashi Ishida，MIT，repo github.com/takashiishida/arxiv-to-prompt）。
> 源码快照：`tmp/exp/atp-src/`（HEAD `3078dda`，2026-08-24）。试运行输出：`tmp/exp/atp-runs/`。
> 体量：`core.py` 1207 行 + `cli.py` 203 行 + `tests/test_core.py` 2073 行（118 用例）。依赖仅 requests/filelock/pyperclip（+可选 tiktoken）。零解析库——**全部用正则 + 括号计数手撸**。
> 定位：arXiv 源码 → 展平成单文件 prompt 喂 LLM。与我们的「保护/分块/splice 重建」不是同一件事，但抓取层、主文件定位、展平、裁剪四块直接同构，可对照。

## 1. 抓取层（`download_arxiv_source` / `check_source_available`）

- **端点**：`GET https://arxiv.org/e-print/{id}`，**永远拉最新版**——`extract_arxiv_id` 的正则 `(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?` 把 URL 里的 `vN` 直接剥掉，无钉版本能力。旧式 id（`math/0306374`）不匹配正则、原样透传（碰巧 URL 可用）。
- **预检**：下载前先 `GET /format/{id}` 抓 HTML 搜 `'Download source'` 字符串判源码可用性——多一次 HTTP 且脆（页面文案变即坏），我们「直接打 e-print、按魔数分流」的设计更省更稳。
- **UA/限速**：`User-Agent: Mozilla/5.0` 伪装；**无任何限速/重试**（仅 availability 检查的 session 挂了 max_retries=3）。
- **缓存**：`~/.cache/arxiv-to-prompt/{id}/`（`/`→`_`），XDG/LOCALAPPDATA 感知。设计亮点：
    - `.arxiv_cache_complete` 完成标记 + rglob 有 .tex 才算有效缓存；
    - `.locks/{sha256(id)}.lock` FileLock 串行化同 id 并发下载（`--lock-timeout` 默认 120s）；
    - `.staging/` 临时目录构建 → `os.replace` 原子发布；旧目录先改名 `.old.{uuid}` 备份，发布失败回滚、成功后清理；
    - 不完整缓存自动重建（`stale_cache_repair`）。
- **解包安全**：逐成员拒 `..`/绝对路径/symlink/hardlink；py≥3.12 用 `filter="data"`。tar 失败回落 plain-gzip：gunzip 后嗅 `\documentclass|\documentstyle|\bye|\end` 才写成 `main.tex`（否则报错）。
- **对照我们**：我们的 §3 魔数三态判别（ustar 嗅探）比它「tar 异常→试 gzip」的异常驱动更干净；它有锁/原子发布/回滚（我们设计里未写锁，可补）；它有版本语义缺失（我们 resolved_version 设计完备）。

## 2. 主文件定位（`find_main_tex`，三遍扫描）

1. 全树找 `main.tex|paper.tex|index.tex` 且行内含 `\documentclass|\documentstyle` → 命中即返回（walk 序）；
2. 否则取**行数最长**的含 `\documentclass|\documentstyle` 的 .tex（启发：会议模板/附带短文更短）；
3. 否则取最长的含 plain-TeX 终结符的文件：正则 `\\(?:bye|end)(?![a-zA-Z{])`（`\end` 后不接字母/`{`，故 `\end{document}` 不算，harvmac 裸 `\end` 算）。

**实测证实致命缺陷**：`'\documentclass' in line` 是**裸行子串匹配、不剥注释**。1502.01589 中 `Planck.tex`（201 行宏文件，`\documentclass` 只出现在 `%` 注释里）打败真正的主文件 `planck_parameters_2015.tex`（83 行）→ 整个输出是宏文件垃圾。我们的 §4 算法（剥注释候选 + `\begin{document}` + include 图根 + `multi_doc` 标记）全面超越。

## 3. 展平（`flatten_tex`）

- 仅识别 `\\(?:input|include){([^}]+)}`——**花括号形独占**。`\input filename`（无括号 TeX 原生语法）直接漏展平（实测证实）。无 `\import/\subfile/\InputIfFileExists/\includestandalone/\CatchFileBetweenTags`；`\bibliography{x}` 不映射 `x.bbl`（paper.bbl 有 52 条 bibitem，输出里 `\bibliography{egbib}` 原样残留）。
- 扩展名补全：`x.tex` → `x`（与 LaTeX `\input` 语义一致，注释里还引了 latexref）。0.9.0 修了带点路径（`3.5_dataset`）——做法是「不以 .tex 结尾才补」，而非按段补。
- 路径解析：**只相对根目录**（`os.path.join(directory, name)`），不相对 including 文件目录——子目录文件里 `\input{sibling}` 会漏。我们「including 目录 → 根目录」双查找更对。
- 注释内 `\input` 不展开：行前缀扫未转义 `%`（奇偶反斜杠计数判 `\%`/`\\%`，实现正确）。
- 环/重复：单 `processed_files` 集合，二次包含返回 `""`——与 spike W12 同款偏差（防环优先于重复展开语义）。
- 编码：`errors='replace'`——latin-1 文件不崩但吃进 mojibake `�`。

## 4. 裁剪

### 4.1 `--no-comments`（`remove_comments_from_lines`）

1. 先 `re.sub(r'\\iffalse\b.*?\\fi\b', '', DOTALL)` 抠掉 iff alse 块（注释大段的习惯写法）；
2. 整行 `%` 开头 → 删行；
3. 行内逐字符：`in_command` 标记（前一字符是 `\`）→ `\%` 保留、`\\%` 正确判注释。

**实测证实缺陷**：verbatim 盲——`\verb|100%|` → `\verb|100`，`\url{http://x.com/a%20b}` → `\url{http://x.com/a`（合成 fixture 实测）。即 ieeA 同款 bug。`\iffalse` 正则也无嵌套/verbatim 感知。我们「`\` 分支先消费 verb/url/verbatim env，`%` 分支永远看不到它们」的单遍不变式根治此类。

### 4.2 `--no-appendix` / `--abstract`

- `re.search(r'\\appendix\b')` 首个命中截断。管线顺序 = 剥注释 → 宏展开 → appendix → figure-paths：与 `--no-comments` 联用时注释里的 `\appendix` 不误伤（顺序对）；但单用 `--no-appendix` 时注释内 `\appendix`、verbatim 内 `\appendix` 仍触发截断。不识别 `\begin{appendix}` env / 无 `\appendix` 的附录节。
- `--abstract`：`\\begin\{abstract\}(.*?)\\end\{abstract\}` DOTALL。强制先剥注释（防抽到被注释的 abstract）——细节用心了。

### 4.3 `--list-sections` / `--section`（section 树）

- 命令表仅 `section|subsection|subsubsection` 三级（无 part/chapter/paragraph）；支持 `\*`；**不支持 `[short]` 可选参**——`\section[Short]{Long}` 整节从树中消失（合成 fixture 实测）。标题用括号匹配取，嵌套 `{` 安全（0.11.1 修的）。
- 建树：扁平扫描 → `end_pos` = 下一个 level≤自己的节点起点 → 栈式父子装配。`extract_section` = `[start_pos, end_pos)` 原文切片（含节头行 + 全部子孙节）。
- UX 亮点：`--section "A > B"` 路径语法；裸名多义时 stderr 列全部候选路径提示消歧（`find_all_by_name`）。这部分交互设计值得原样借鉴（如果我们做「只译某节」）。

## 5. `--expand-macros`

- 覆盖：`\newcommand/\renewcommand/\providecommand`（±`*`）、`\DeclareMathOperator`（±`*`，体改写为 `\operatorname{...}`）、`\def` **仅零参**。`[n]` 参 + `[default]` 首参可选、`#1..#9` 位置替换、≤10 轮不动点嵌套展开。
- **定义段直接从文本删除**（regions_to_remove 合并后剔除）——对 prompt 合理，对 identity 重建是破坏性的（我们宏表是登记制、不删原文）。
- 不支持：`\let`、`\newenvironment`、条件式、带参 `\def`、`##` 嵌套定义（`replace('#1')` 会把 `##1` 错伤）、定义点之前的同名调用（全文本无差别展开）。
- 括号/方括号匹配手写 depth 计数，`\{`/`\[` 转义感知——与我们 `_match_brace` 同思路但无注释感知。

## 6. `--figure-paths` / `--token-count`

- figure-paths：取**最后一个** `\graphicspath` 声明（与 LaTeX 后定义覆盖语义一致）+ 源码根目录兜底；`\includegraphics` 正则（可带 `[opt]`）；扩展名按 `.pdf/.png/.jpg/.jpeg/.eps/.svg` 序补；只返回**盘上实存**绝对路径、去重、跳过 `://` URL。管线位置在裁剪之后——`--no-comments --no-appendix` 可排除被注释/附录图（配套语义自洽）。
- token-count：tiktoken `o200k_base`，`disallowed_special=()` 防 `<|endofprompt|>` 字面崩溃（GPT-4 论文实测坑，changelog 有案）。

## 7. 本地实测汇总（全部 `--local-folder`，uvx 0.14.1）

| 语料           | 难点                                                    | 结果                                                                    | 质量                                                                                        |
| -------------- | ------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 1706.03762     | 基线                                                    | ✅ list-sections/section/abstract/expand-macros/token-count(13352) 全通 | 节树完整正确                                                                                |
| 2201.05989     | camera.tex+paper.tex 双 documentclass                   | ✅ 展平 167KB                                                           | 「最长文件」启发恰好蒙对（paper.tex 1025>149 行）；不标 multi_doc，纯运气                   |
| 1502.01589     | 103 文件、`\input X` 无括号、documentclass 陷注释       | ❌ **完全失败**                                                         | 选中 Planck.tex 宏文件当主文件，输出 202 行宏定义垃圾；即使选对，无括号 `\input` 也全不展开 |
| hep-th/9901001 | `\documentstyle` LaTeX 2.09                             | ✅                                                                      | 27KB 干净全文，`\bye\|\end` 兜底逻辑覆盖更老 plain TeX                                      |
| 2602.09511     | 法语 babel                                              | ✅                                                                      | 252KB 正常；list-sections 有少量空名子节（`\subsection{}` 类）                              |
| synth fixture  | `\section[opt]`、`\input` 无括号、`\verb\|%`、`\url{%}` | ❌ 三连证实                                                             | opt-arg 节消失；无括号 input 不展开；verb/url 内 `%` 被当注释截断                           |

## 8. 可借鉴 / 不适用

### 值得抄

1. **Section 树交互**：`A > B` 路径消歧 + stderr 列候选——若做「按节翻译」直接借用此 UX。
2. **缓存发布机制**：staging 构建 → marker 完成位 → `os.replace` 原子换 + `.old` 备份回滚 + per-id FileLock。我们 arxiv-layer 缓存设计没写锁与原子发布，可补这一段。
3. **plain-TeX 终结符兜底**：`\bye|\end(?![a-zA-Z{])` 正则判 harvmac 类无 documentclass 论文——我们 §4「零候选→降级链」更保守，但作为「再挣扎一下」的最后一档便宜好用。
4. **`\iffalse…\fi` 当注释块**的认知（我们不剥注释，但判别「真注释 vs 条件编译」时可参考）。
5. **`\graphicspath` 取最后声明**、figure-paths 跑在裁剪后的管线序——资源收集器顺序语义。
6. **测试资产**：`tests/test_core.py` 118 例里有现成的边缘用例构造（带点 input 路径、尾部空白 `\input{appendix }`、嵌套括号节题、tar 安全成员），可吸收进我们的 fixture 集。

### 不适用 / 我们已超越

1. **它本质是「flatten + 正则过滤器」**，无占位符/分块/splice/校验——不同物种。我们 chunk/PH/identity/validate 体系它完全没有。
2. **主文件定位**：裸子串不剥注释 → 实测翻车；我们五级裁决 + multi_doc。
3. **展平命令覆盖**：只有花括号 `\input/\include`，无括号形、`\import` 系、`\bibliography→.bbl`、相对 including 目录解析全缺。
4. **注释剥离 verbatim 盲**（实测截断 `\verb`/`\url`）——我们单遍扫描不变式根治。
5. **节命令表过窄 + 无 `[opt]` 支持**（实测 `\section[Short]` 消失）；不感知 env/数学/条件。
6. **宏处理是破坏性字符串重写**（删定义、无差别展开、仅零参 `\def`）；我们宏表登记制 + argspec + 分类保护。
7. **无版本语义**（永远最新版）、无限速、`/format` HTML 预检脆、编码 errors=replace 出 mojibake——我们各有对应设计。
8. **`--expand-macros` 对翻译管线有害**：展开把宏体注入每个调用点，译文里出现大段重复 tex——我们「宏不展开、TRANSPARENT 宏参数按位分流」才是正路。它这功能是给「把论文喂给不懂该文件宏的 LLM」场景用的。
