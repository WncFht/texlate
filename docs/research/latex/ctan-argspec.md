# CTAN argspec 签名表导出 + 语料覆盖率实验

**结论先行**: argspec.json 已产出 1820 条签名条目（1597 宏 + 223 环境）。对 256 个语料
.tex、300911 次命令调用统计：**按出现次数覆盖 78.6%**(236664/300911),按种类
14.7%(749/5094);**环境按出现次数覆盖 98.9%**(10253/10372)。未覆盖的 21% 出现次数
几乎全部是「论文自定义宏 + TeX 原语/内部宏」——正是"未知→保守保护"的设计目标区间。
可译文本相关的命令参数角色 (text/key/verbatim/opt-text/skip) 已按语义标注完毕，
对常用命令手工校准、长尾用族规则推断、ctan 缺签名处生成"猜测签名"并显式标记。

## 交付物

| 文件                            | 内容                                                                                                                         |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `tmp/exp/ctan/export.mjs`       | 从 unified-latex-ctan 18 个包的 ESM `index.js` 直接 `import` 出 `macros`/`environments` → `ctan_raw.json`(422 宏 + 129 环境) |
| `tmp/exp/ctan/ctan_raw.json`    | 原始签名 + namedArguments + renderInfo 标志                                                                                  |
| `tmp/exp/ctan/build_argspec.py` | 三源合并 + arg_roles 标注 + 猜测签名 → `argspec.json`                                                                        |
| `tmp/exp/ctan/argspec.json`     | **M0 数据资产本体**(1820 条)                                                                                                 |
| `tmp/exp/ctan/coverage.py`      | 语料控制序列扫描 + 覆盖率 + 未覆盖分类建议 → `coverage.json`                                                                 |
| `tmp/exp/ctan/coverage.json`    | 实验数据 (top100 未覆盖清单、建议类聚合)                                                                                     |

## schema

```json
"section": {
  "name": "section",          // 命令/环境名，不含反斜杠; 单字符命令即字符本身
  "kind": "macro",            // macro | env
  "package": "latex2e",       // 来源; miniscanner/latex-utensils/manual/math-literal/...
  "signature": "s o m",       // xparse argspec 原样; "" = 零参或未知
  "arg_roles": ["skip","opt-text","text"],  // 与 signature token 对齐
  "policy": "chunk-arg",      // 兜底行为指令
  "named_arguments": ["starred","tocTitle","title"],  // ctan 提供时保留
  "source": ["ctan:latex2e","manual"],     // 出处; "guessed-signature" 标记猜测
}
```

- `arg_roles` 取值：`text`(可译正文→chunk)、`opt-text`(可选参中的可译文本)、
  `key`(不透明标识符→保护:cite key/label/文件名/计数器/color/包名)、
  `verbatim`(逐字内容:url/code，内部不解析)、`skip`(结构参留模板：
  数字/尺寸/列格式/overlay/星号/定界参)。
- `policy`(signature 缺省或兜底时解析器行为): `chunk-arg | transparent | key |
verbatim | protect | boundary | literal`。
- env 额外有 `body_role`: `text | verbatim | math | protect`(protect = 整段保护
  但内部挖 \caption，同 miniscanner 语义)。
- `source` 含 `guessed-signature` 时 signature/arg_roles 是推断值 (84 条，见下)。

## 三源合并方法

1. **ctan(主源，464 条带签名)**: `export.mjs` 对每个 `package/*/index.js` 做
   `import()`(包是 `"type": "module"`,node 26 直接跑),取 `signature` /
   `renderInfo.namedArguments` / `pgfkeysArgs` / `inMathMode` / `escapeToken`。
   同名跨包冲突 18 个 (bibitem/label/ref/section/newtheorem/item/part 等),
   规则：保留 latex2e 定义，其余记 `also_in` 字段。
2. **miniscanner.py 命令族表**: 直接 `import miniscanner`(无副作用),
   8 个族 → policy/role 规则:CITE_NAMES/REF_NAMES/label→m=`key`;
   CHUNK_ARG_NAMES→m=`text`,o=`opt-text`;TRANSPARENT_NAMES→m=`text`;
   PROTECT_NAMES→m=`key`;PROTECT_BLOCK_NAMES→`m`全`skip`整体保护;
   BOUNDARY/INLINE_LITERAL/FONT_SWITCHES→literal。
   环境侧:MATH_ENVS→`math`,VERBATIM_ENVS→`verbatim`,PROTECTED_ENVS→`protect`。
3. **latex-utensils(latex.pegjs 文法)**: 特判族与 miniscanner 互证：
   `command.label`(label/ref/eqref/autoref/cref)→key;`command.url`→verbatim;
   `command.href` url+text 双参;`verb`→verbatim;verbatim/minted/lstlisting/
   comment 环境→verbatim;两套 math env 名单并入 ENV_BODY_MATH;`\text`→text。
4. **手工标注 MANUAL(~120 条)**: 按 ctan signature 位置标 role。重点：
   `\section s o m → skip opt-text text`;`\cite o m → skip key`;
   `\href o m m → skip verbatim text`;`\caption o m → opt-text text`;
   `\footnote o m → skip text`(可选参是编号);
   `\textcolor m m → key text`;`\newtheorem m m o → key text skip`(定理名可译);
   `\includegraphics s o o m → skip×3 key`;`\newcommand s +m o +o +m →
skip key skip skip skip`;beamer `d<>` overlay 一律 skip。
   beamer `frame`/`block`/`alertblock`/`exampleblock` 环境的 **`d{}` 定界参是
   标题文本 → text**(env 参数手工表)。
5. **猜测签名**(84 条，`source` 含 `guessed-signature`): ctan 缺签名但族归属
   明确时按规则生成——cite/ref/label 族猜 `o o m`→`[skip,skip,key]`(natbib
   约定);chunk-arg 族猜 `o m`→`[opt-text,text]`;transparent 猜 `m`→`[text]`;
   protect 猜 `m`→`[key]`;MANUAL 条目按已知 m_roles 猜 `m×n`(multirow→
   `m m m` `[skip,skip,text]`)。**猜 o 类参数无害**(不匹配则跳过),**绝不
   多猜 m**(会误吃后续 `{group}` 当参数)。boundary/literal 不猜参 (空串)。
6. **批量 literal 族 (三个名单，~1000 条)**: 语料证明未覆盖命令大头是数学
   符号——`MATH_LITERAL_NAMES`(希腊字母/二元运算/箭头/定界符/算子/数学重音/
   数学字体/间距 ~600)、`TEXT_SYMBOL_NAMES`(text*符号族)、
   `ACCENT_LETTER_CMDS`(单字母重音 \c \d \b \u \v \H \k \r \t + \i \j \l \o)、
   `LENGTH_NAMES`(长度寄存器)、`MISC_LITERAL_NAMES`(\the* 计数器/\and/
   \xspace/\hrule/\hfil 族/版式开关)。单字符非字母命令整组 literal;
   `\begin`/`\end` 以 `policy:boundary` 入表 (解析器原语)。

## 覆盖率数据 (证据)

```
$ python3 tmp/exp/ctan/coverage.py
files=256
宏:   种类 749/5094 = 14.7%;  出现 236664/300911 = 78.6%
环境: 种类 101/155 = 65.2%;   出现 10253/10372   = 98.9%
```

覆盖的 236664 次按 policy 分布：

```
literal 155484 | protect 25990 | boundary 22730 | key 21279
| chunk-arg 10606 | transparent 345 | verbatim 116
```

解读：literal(数学符号/间距/单字符) 占总量 52%——语料是数学密集型;
真正送译相关的 `chunk-arg` 有 10606 次、`key` 21279 次，这两个 policy 的
参数角色标注是表的核心价值。

未覆盖 64247 次按建议类聚合 (top):

```
55128 occ / 3682 kinds  未知 → 保守保护 (论文自定义宏长尾)
 2405 occ /   25 kinds  单字母命令 → 用户宏 (\C \R \E \B \A \Z \Q \D \h)
 2325 occ /   31 kinds  定义类 → 保护 (\def \newif ...)
 2096 occ /  364 kinds  内部宏 (@) → 保护 (.sty/preamble 内部宏)
  987 occ /   31 kinds  TeX 原语/条件 (\if \or \else \fi)
  254 occ /   21 kinds  ref 族 (误报多: \nref 等是自定义)
  159 occ /   21 kinds  标题类 (自定义 section 别名)
  其余每类 <150 occ
```

## top 未覆盖命令 + 分类建议 (节选)

| 次数                                | 名字                                                                                          | 判定                                                               |
| ----------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| 3462/2079/1159/427/336/250…         | `AgdaSpace` `AgdaSymbol` `AgdaBound` `AgdaFunction` `AgdaOperator` `AgdaInductiveConstructor` | **不进表**: 单篇 agda.sty 生成宏 (~10K 次出自一两篇),protect       |
| 1613                                | `\def`                                                                                        | TeX 原语 → protect                                                 |
| 1468/555                            | `\cat` `\scat`                                                                                | 自定义范畴论缩写 → protect                                         |
| 925/884/612                         | `\config` `\AAA` `\of`                                                                        | 论文自定义 → protect                                               |
| 448/268/248/234/216/174/162/143/239 | `\C` `\R` `\E` `\B` `\A` `\Z` `\Q` `\D` `\h`                                                  | 单字母用户宏 (数集/缩写)→ protect;单字母重音 (\c \d \u \v…) 已在表 |
| 425/355/347/329/164                 | `\node` `\draw` `\rput` `\psline` `\pscircle`                                                 | tikz/pstricks 绘图命令 → protect(环境体已整段保护)                 |
| 435/189/128                         | `\Planck` `\planck` `\planckTT`                                                               | 论文物理宏 → protect                                               |
| 281/198                             | `\ket` `\GeV`                                                                                 | bra-ket/单位宏 → protect                                           |
| 283/263/251                         | `\UnaryInfC` `\RightLabel` `\AxiomC`                                                          | bussproofs 证明树 → protect                                        |
| 202                                 | `\demph`                                                                                      | 自定义强调 → protect(参数组会照常解析为文本，见下)                 |
| 140                                 | `\nref`                                                                                       | 自定义 ref 宏 → protect(不建议进表：非标准)                        |
| 114                                 | `\multirow`                                                                                   | **已进表**(guessed `m m m`→`[skip,skip,text]`)                     |
| 151                                 | `\neg`                                                                                        | **已进表** math-literal                                            |
| 258                                 | `\xspace`                                                                                     | **已进表** literal                                                 |
| 458×2                               | `\textquotedblleft/right`                                                                     | **已进表** literal                                                 |
| 128                                 | `\hfil`                                                                                       | **已进表** literal                                                 |

未覆盖环境已降到个位数频次：`Theorem` `Lemma`(自定义大写变体)、`problem`
`setprop` `iquestion` `acks` `ruledtabular` `deluxetable*` `longrotatetable`
`AgdaMultiCode` 等——全部按"未知环境"处理。

## 进表建议 (对解析器/M0 决策)

1. **未知命令 → "保护 token，不吃参"**: 本次实验证明长尾 (~3682 种/55K 次)
   是论文自定义宏，无法预知参数个数。建议解析器对未知 `\foo` 只保护控制序列
   本身、后续 `{group}` 照常解析——`\demph{可译文本}` 的参数仍进 chunk(白赚),
   `\cat{x}` 的参数当文本翻译 (噪声可接受)。这比"猜吃一参"安全：错吃会把
   文本当 key 永久保护，错不吃最多多译一点。
2. **单字符命令默认 literal**;**单字母命令默认 protect**(用户宏重灾区，
   表内仅枚举确认的重音)。
3. **未知环境默认 `body_role=text`**: 未覆盖环境全是 theorem 类/自定义环境，
   正文仍是可译文本——保护 `\begin/\end` 壳即可，与 miniscanner 行为一致。
4. **不需要再为覆盖率扩表**: 剩余未覆盖几乎无标准化命令;`ref 族/标题类`
   建议桶经人工核对全是自定义名 (\nref),进表反而引入错误签名。
5. **`@`-内部宏、`if` 系原语 → protect**: 出现在 preamble/.sty 内，永不该送译。
6. 表已覆盖全部"翻译敏感"命令 (chunk-arg/transparent 类): 章节、caption、
   footnote、字体强调、href/textcolor、multirow、beamer 标题族——这些
   是唯一"参数角色错了会漏译/错译"的命令，均已手工校准。

## 已知局限

- 扫描用正则剥离 verbatim/comment 后统计，非完整解析;`\begin{X}` 嵌套同名
  verbatim 极端情况下边界可能偏一两个字节——只影响计数，不影响表。
- `guessed-signature` 84 条中 cite 族统一猜 `o o m`,个别变体 (如 `\citeN*`)
  实际签名可能不同——有 `guessed-signature` 标记可审计回滚。
- 命令统计不区分数学/文本模式：`$..$` 内的 `\foo` 与正文 `\foo` 同计。
  数学内未知宏 (如 `\cat`) 会被翻译管线在数学保护阶段整段跳过，不进表无影响。
- `verbatim`/`lstinline` 类命令的真实参数是定界符式 (`\verb|x|`),signature
  里的 `m` 只是角色标注载体，解析器须按 `policy:verbatim` 走定界符扫描而非
  `{...}` 组解析。
- ctan 版本 1.8.4 提供 422 宏 + 129 环境 (比任务描述的 404+128 略多，以实跑为准)。
