# audit 次要观察三条处置（2026-09-15，scanner.py，未 commit）

均实证为真 bug 并修复；corpus 250 文件对拍 56 篇有 diff，抽样全数归入
三类意图内改动，无意外面。

## 1. `\\]` 早关 `\[..\]`（+ `\%` 杀闭符搜索）

`_find_math_close` 逐字符 `startswith("\\]")`：`\\]`（换行+括号）的第二
个 `\` 被复检成闭符 → 数学段早收、余文漏出。顺带 `\%` 的 `%` 被当注释
吞行 → 闭符永远找不到，整段 `\[...\]` 退化成裸文本 chunk。

修：`\` 处非闭符即成对消费 `\<x>`（`\`+`\n` 例外只进一步，段界判定
不吃亏）。探针：`\[ a \\] b \]` 现整段 MATH；`\[\\\]` 真闭符仍命中。

注：`_find_env_end` 无此病——它走 `read_cmd_name`，`\\` 早被当单命令
整体消费。

## 2. `\cite{a}{b}` 多参吞

`_protect_call` 无条件连吃至多 3 个 `{...}` 组。cite/ref/protect 族全是
单 key 签名 → `{b}` 被吞进占位符永不见光。corpus 实证：
`2105.03923` 的 `\citep{r2d2} {\colorred when LSTM is used.}`——
整句正文被吞进 CITE；`2211.13021` 的 `\bibitem{KS} {Kagan,…}`——
作者串被吞进 BIB。

修：`_protect_call` 加 `mand` 上限；cite/ref/protect 三族传 1，
`inputminted{lang}{file}` 双参传 2，其余调用点保持 3 兜底。

## 3. BOUNDARY 命令 `{arg}` 落正文

`\cline{1-2}`/`\vspace*{2em}`/`\setcounter{a}{b}` 等结构参落进 run →
成 chunk 被翻译（corpus 实证：`\vspace{0.2cm}` 的 `{0.2cm}` 单独成
chunk 送译）。

修：`_BOUNDARY_TAIL` per-name argspec 表（复用 `_args`/`ArgSpec`：
cline m、cmidrule o+d()+m、vspace/hspace s+m、counter/length mm、
pagestyle/pagenumbering m、pagebreak/linebreak/nopagebreak/twocolumn o、
usepackage/documentclass 族 om），tail 命中即并进 LITERAL span。
**有意不收**：`\item[o]` label、`\newtheorem` 标题、`{text}` 跟随的
`\par`/`appendix` 等——那些是可译文本。

## 验证

- 12 探针全覆盖（含 `\\\]` 真闭符、`\citet[o][o]{k}`、inputminted 双参、
  item[label] 不变式）。
- pytest：latex 侧全绿；唯一红 = leader 在飞 `test_latex_expansion.py`
  17 件（stash 验证与我无关）+ fixloop rules-v2 4 件（同上）。
- ruff check/format 净。
