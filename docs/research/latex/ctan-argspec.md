# CTAN argspec 签名表构建 + 语料覆盖率

> **结论**：`argspec.json` 已产出并入库为 `latex/data/argspec.json`（构建时 1820 条 = 1597 宏 + 223 环境，现行版本 1595 宏 + 263 环境）。对 256 个语料 .tex、30 万次命令调用的统计：按出现次数覆盖 78.6%、环境按出现次数覆盖 98.9%；未覆盖的 21% 几乎全是论文自定义宏与 TeX 原语/内部宏——正是「未知→保守保护」的设计目标区间。
> **状态**：现行（已落地为 `latex/data/argspec.json`；消费侧规范见 `spec/latex-pipeline.md`）
> **日期**：2026-09-15

## 1. 表结构

```json
"section": {
  "name": "section",
  "kind": "macro",                      // macro | env
  "package": "latex2e",                 // 来源包
  "signature": "s o m",                 // xparse argspec；"" = 零参或未知
  "arg_roles": ["skip","opt-text","text"],  // 与 signature token 对齐
  "policy": "chunk-arg",                // 兜底行为指令
  "named_arguments": ["starred","tocTitle","title"],
  "source": ["ctan:latex2e","manual"]   // "guessed-signature" 标记推断值
}
```

`arg_roles` 五值：`text`（可译正文→chunk）、`opt-text`（可选参中可译文本）、`key`（不透明标识符→保护：cite key/label/文件名/计数器/color/包名）、`verbatim`（逐字内容：url/code，内部不解析）、`skip`（结构参留模板：数字/尺寸/列格式/overlay/星号/定界参）。`policy` 兜底指令：`chunk-arg | transparent | key | verbatim | protect | boundary | literal`；env 另有 `body_role: text | verbatim | math | protect`（protect = 整段保护但内部挖 `\caption`）。

## 2. 六源合并方法

1. **unified-latex-ctan 主源（464 条带签名）**：从 18 个包的 ESM `index.js` 直接 `import` 出 `macros`/`environments`，取 `signature`/`namedArguments`/`pgfkeysArgs`/`inMathMode`/`escapeToken`[^unified-latex]。同名跨包冲突 18 个（`\bibitem/\label/\ref/\section/\newtheorem/\item` 等）按「保留 latex2e 定义、其余记 `also_in`」处理。
2. **扫描器命令族表**：cite/ref/label 族 → `key`；chunk-arg 族 → `m=text, o=opt-text`；transparent 族 → `m=text`；protect 族 → `key`；protect-block → `m` 全 `skip` 整段保护；boundary/inline-literal/字体开关 → literal。环境侧 math/verbatim/protect 三名单直接映射 `body_role`。
3. **latex-utensils 文法互证**：`command.label`（label/ref/eqref/autoref/cref）→ key；`command.url` → verbatim；`\href` = url+text 双参；verbatim/minted/lstlisting/comment 环境 → verbatim；`\text` → text[^latex-utensils]。
4. **手工标注 ~120 条**：按 signature 位置校准角色——`\section s o m → skip opt-text text`；`\cite o m → skip key`；`\href o m m → skip verbatim text`；`\caption o m → opt-text text`；`\footnote o m → skip text`（可选参是编号）；`\textcolor m m → key text`；`\newtheorem m m o → key text skip`（定理名可译）；`\includegraphics s o o m → skip×3 key`；`\newcommand s +m o +o +m → skip key skip×3`；beamer `d<>` overlay 一律 skip，但 `frame/block/alertblock/exampleblock` 的 `d{}` 定界参是标题文本 → `text`。
5. **猜测签名 84 条**（`source` 标 `guessed-signature`）：ctan 缺签名但族归属明确时按规则生成——cite 族猜 `o o m→[skip,skip,key]`（natbib 约定）、chunk-arg 猜 `o m→[opt-text,text]`、transparent 猜 `m→[text]`、protect 猜 `m→[key]`。原则：**猜 `o` 类参数无害**（不匹配则跳过），**绝不多猜 `m`**（会误吃后续 `{group}` 当参数）；boundary/literal 不猜参。
6. **批量 literal 族 ~1000 条**：语料证明未覆盖大头是数学符号——希腊字母/二元运算/箭头/定界符/算子/数学重音/数学字体/间距 ~600，text 符号族、单字母重音（`\c \d \b \u \v \H \k \r \t` + `\i \j \l \o`）、长度寄存器、`\the*`/`\and`/`\xspace`/`\hrule/\hfil` 族/版式开关；单字符非字母命令整组 literal；`\begin`/`\end` 以 `policy:boundary` 入表。

## 3. 覆盖率（256 文件 / 300911 次调用）

宏：种类 749/5094 = 14.7%、出现 236664/300911 = **78.6%**；环境：种类 101/155 = 65.2%、出现 10253/10372 = **98.9%**。

已覆盖 23.7 万次按 policy 分布：literal 155484（52%，语料数学密集）｜protect 25990｜boundary 22730｜key 21279｜chunk-arg 10606｜transparent 345｜verbatim 116。`chunk-arg` 与 `key` 两 policy 的参数角色标注是表的核心价值——它们是唯一「角色标错会漏译/错译」的命令面。

未覆盖 64247 次按类聚合（top）：未知长尾 55128 次/3682 种（论文自定义宏）；单字母用户宏 2405 次/25 种（`\C \R \E \B` 等数集缩写）；定义类 2325 次；`@` 内部宏 2096 次/364 种；TeX 原语/条件 987 次；ref 族 254 次（人工核对全是 `\nref` 类自定义名，误报）；自定义标题类 159 次。高频个案如 agda.sty 生成宏（单篇 ~10K 次）、`\cat/\scat`（范畴论缩写）、tikz/pstricks 绘图命令、bussproofs 证明树、bra-ket/单位宏——全部 protect 处理，不进表。

## 4. 对解析器的进表决策

1. **未知命令 → 保护 token 不吃参**：长尾是论文自定义宏无法预知参数个数；只保护控制序列本身、后续 `{group}` 照常解析——`\demph{可译文本}` 的参数仍进 chunk（白赚），错吃会把文本当 key 永久保护、错不吃最多多译一点，后者安全。
2. **单字符命令默认 literal；单字母命令默认 protect**（用户宏重灾区，表内仅枚举确认的重音）。
3. **未知环境默认 `body_role=text`**：未覆盖环境全是 theorem 类/自定义环境，正文仍可译——保护 `\begin/\end` 壳即可。
4. **不再为覆盖率扩表**：剩余未覆盖几乎无标准化命令，进表反而引入错误签名。
5. `@` 内部宏、`if` 系原语 → protect：出现在 preamble/.sty 内，永不该送译。
6. 全部「翻译敏感」命令（章节/caption/footnote/字体强调/href/textcolor/multirow/beamer 标题族）已手工校准完毕。

## 5. 已知局限

统计用正则剥离 verbatim/comment 非完整解析，嵌套同名 verbatim 极端情况边界可偏一两个字节（只影响计数）；84 条猜测签名中 cite 族统一猜 `o o m`，个别变体（`\citeN*`）实际签名可能不同——有 `guessed-signature` 标记可审计回滚；命令统计不分数学/文本模式（数学内未知宏在数学保护阶段已整段跳过，无影响）；`\verb|x|` 类命令的真实参数是定界符式，signature 的 `m` 只是角色标注载体，解析器须按 `policy:verbatim` 走定界符扫描。数据源 unified-latex-ctan 1.8.4 提供 422 宏 + 129 环境。

### 参考文献

[^unified-latex]: unified-latex. unified-latex-ctan — CTAN macro/environment signatures for unified-latex (1.8.4). GitHub. [github.com/siefkenj/unified-latex](https://github.com/siefkenj/unified-latex)

[^latex-utensils]: texlab & contributors. latex-utensils — LaTeX parsing utilities (latex.pegjs grammar). GitHub. [github.com/latex-lsp/latex-utensils](https://github.com/latex-lsp/latex-utensils)
