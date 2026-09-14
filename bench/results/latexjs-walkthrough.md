# LaTeX.js 源码走读报告

对象:`/tmp/latex-refs/LaTeX.js`(michael-brade/latex.js,v0.12.6,master @ bda76c3,LiveScript→TypeScript 迁移中)

## 0. TL;DR — 先纠正一个前提

LaTeX.js **不是** TeX 语义实现。它没有 mouth/gullet 分离、没有 token 流、没有
catcode 表、没有 `\def`/`\newcommand`/`#1` 参数替换——一行都没有。它是一台
**PEG(peggy)解析器直接驱动 DOM 生成的"解析即执行"机器**:文法规则一边匹配源码,
一边调用生成器产出 HTML 节点。作者在 `docs/limitations.md` 里明说:

> "for now there is no way of defining macros, only expanding macros is supported"
> "this parser does not implement TeX's distinction of expansion and execution.
> Right now, there is only one phase that takes a macro and returns an HTML fragment."

"JS 里最完整的 LaTeX 实现"的名号指的是**输出保真度和内置宏覆盖**(约 147 个
LaTeX 宏 + documentclass/package 体系 + 计数器/长度/标签/引用语义),不是 TeX
语言机制。对我们的受限宏展开层,它能给的是**宏签名驱动参数解析**的设计和组平衡
状态机,而 `#n` 替换展开机制要去 plasTeX 找。

另一个现状:master 正处于 LiveScript→TypeScript 重写中途。`src/*.ts` 是新实现
(尚未完工,`src/latex/latex.ltx.ts` 只有 28 行 stub,`macro-manager.ts` 里还有
`if (pkg = "latex.ltx")` 这种赋值当比较的 bug,当前 TS 路径大概率跑不通);
`src/*.ls` 是 0.12.x 发布的实际实现。两边架构相同,下文以 .ls(完整)+ .ts
(新结构)对照描述。

## 1. 整体架构:没有三段式,只有"文法→生成器"两级

```
LaTeX 源码字符串
   │
   ▼  peggy 生成的递归下降解析器(一次通过,无 token 中间层)
latex-parser.pegjs(1069 行文法,内嵌 JS action 代码)
   │  文法 action 里直接调用 g.createText / g.macro / m.beginArgs ...
   ▼
MacroManager(宏名 → JS 函数 + 参数签名表)── packages: latex.ltx / documentclasses / packages
   │
   ▼
Generator / HtmlGenerator(文档状态机 + DOM 工厂)
   │  counters(计数器)、groups(组/属性栈)、labels/refs、lengths、
   │  createText/createFragment/addAttributes、KaTeX 接管数学
   ▼
DocumentFragment(HTML DOM)
```

对应 TeX 三段式:

| TeX | LaTeX.js 对应物 | 文件 |
|---|---|---|
| mouth(字符→token,catcode) | **不存在**。字符直接被 PEG 终结符规则消费,每个 catcode 硬编码成一条文法规则 | `src/parser/latex-parser.pegjs` 底部 |
| gullet(展开,宏替换) | **不存在 token 级展开**。最接近的是 MacroManager:宏注册表 + 参数签名 + 调用分发 | `src/macro-manager.ts`(313 行) |
| stomach(执行,排版) | Generator 体系:DOM 生成 + 全局状态(组栈、计数器、长度、label/ref) | `src/generator/generator.ts`、`counters.ts`、`groups.ts`、`html/generator.ts`、`html/elements.ts` |
| 宏体(替换文本) | **JS 函数**,不是 token 列表。按 class 组织成 "package",装饰器 `@Macro(mode)` `@Args(...)` 声明元数据 | `src/latex/latex.ltx.ls`(1333 行,~147 个宏)、`src/latex/packages/*.ts`、`src/latex/documentclasses/*.ts` |

**token 流怎么走**:不走。源码字符流进 PEG 解析器,文法里的 action(`{ ... }`
块)在匹配成功的瞬间执行,直接产出 DOM 节点或副作用。例如 `macro` 规则
(pegjs:211-218):

```js
macro =
    name:identifier _ &{ if (m.hasMacro(name)) { m.beginArgs(name); return true; } }
    macro_args
    { var args = m.parsedArgs(); m.endArgs();
      return g.createFragment(g.macro(name, args)); }
```

识别宏名 → 查签名表 → 文法按签名逐参数解析(`macro_args` 循环)→ 调
`g.macro(name,args)` → JS 函数返回 `[Node|string]` → 包成 fragment 成为该规则
的返回值。**解析和执行完全融合**,没有"先展开成 token 串再排版"的余地。

`MacroManager` 的职责(新 TS 版从 generator 里拆出来的):
- `#packages: MacroPackage[]` 有序包列表,`#macroPkg` 倒序查找 → 后加载的包覆盖
  先加载的同名宏(相当于内建 `\renewcommand` 语义)。
- `macros: Map<name, {mode, args?}>` 元数据表,由 `@Macro`/`@Args` 装饰器在类加载
  时填充。
- `#curArgs: Stack<ParsedArgs>` **参数签名栈**:`beginArgs` 把该宏的 args 签名副本
  压栈,文法每消化一个参数就 `shift` 掉签名头部、`addParsedArg` 存结果,
  `endArgs` 弹栈校验全部消化完。嵌套宏(参数里的宏)靠栈自然支持。
- `selectArgsBranch` 处理"多签名分支"(签名可以是 `ArgType[][]` 备选列表,看下一
  个字符是 `[` 还是 `{` 决定走哪个分支)。

## 2. catcode:硬编码进文法,不可变

没有 catcode 表、没有 `\catcode`、没有 token 对象。每个 catcode 是一条文法规则,
注释里标了编号(pegjs:913-993):

```js
escape        = "\\"          // catcode 0
begin_group   = "{"           // catcode 1
end_group     = "}"           // catcode 2
math_shift    = "$"           // catcode 3
alignment_tab = "&"           // catcode 4
nl/sp/comment = ...           // catcode 5/10/14
nbsp          = "~"           // catcode 13(active,固定映射到 nbsp)
char          = [a-z]i        // catcode 11
punctuation等  = ...           // catcode 12
macro_parameter = "#"         // catcode 6 —— 存在但只作语法占位符,从不用于替换!
```

影响:
- `identifier = $char+` 宏名只允许字母。`\p@enumii`、`\@listdepth` 这类 `@`-宏
  **无法从源码输入**,只能被 JS 内部以 `g.macro("p@enumii")` 调用——效果上等价
  LaTeX 的 @-catcode 惯例,但不是实现了 catcode 切换。`\makeatletter`/
  `\makeatother` 是 no-op stub(latex.ltx.ls:1281-1285)。
- `#` 在文法里有规则但只在 `utf8_char` 的负向前瞻里被排除——正文里出现 `#`
  是语法错误(没法输出 `\#` 以外的用法…… 实际上 `\#` 走 `ctrl_sym`)。**宏参数
  记号完全没被用在"替换文本"语义上**。
- `^^x`/`^^FF`/`^^^^FFFF` 转义在 `charsym` 规则实现(真正的 TeX 特性,少见地
  保留了)。
- active 字符只有 `~` 一个,语义固定。

## 3. \def/\newcommand 展开机制:不存在,替代物是"声明式参数签名"

### 3.1 用户宏:没有 `\newcommand`,只有 JS `CustomMacros`

全仓搜索 `newcommand|renewcommand|providecommand|\\def`:定义处为零(只有
`counters.ts:41` 调用了一个不存在的 `this.newcommand` —— TS 移植中的死代码;
.ls 版对应位置是 `@_macros[\the + c] = -> [...]` 直接给 JS 宏表赋值)。
文档层也确认:fixtures 无一使用 `\newcommand`,`docs/extending.md` 教用户用
**JavaScript 类 + `args` 表**注入宏:

```js
args['bf'] = ['HV']                       // 模式 + 参数签名
prototype['bf'] = function() { this.g.setFontWeight('bf') };
```

也就是说 LaTeX.js 里"宏"= JS 函数,"展开"= 函数调用返回值。`#1-#9`、替换文本、
参数文本(parameter text)、递归展开、`##` 转义、`expandafter`/`noexpand`、
定界参数、undelimited 单 token 参数——**一概没有**,自然也没有展开深度控制
(不需要:JS 递归就是栈,爆栈即异常)。

### 3.2 参数机制(这是它唯一和"宏参数"沾边的东西,值得细看)

宏签名是字符串数组:`["H", "s", "o?", "g"]` = 水平模式 + 可选星 + 可选 `[...]` +
必选 `{...}`。全部类型见 `src/macros.ts` 的 `ArgType`(`g/hg/h/i/ie/k/csv/u/c*/
m/l/cl/n/f/v/is/X/s` + `o?`族可选参数)。

解析驱动方式(`macro_args`,pegjs:249-296):循环里逐个尝试
`m.nextArg("X")` 看签名头部是否匹配该类型,匹配则调对应的专用文法规则解析,
`addParsedArg` 收集。要点:

- **可选参数靠签名驱动**:只有签名写了 `o?`,文法才尝试 `[`;`opt_group` 内部
  允许嵌套 `[]` 靠组平衡解决(fixture 有专门测试 `[{t]}t]`)。
- **必选参数必须带 `{}`**(`arg_group` 以 `begin_group` 开头)——不支持 TeX 的
  undelimited 参数(`\textbf a` 里的 `a` 是合法单 token 参数,LaTeX.js 会报错)。
  **这是它比真 TeX 弱、而我们必须强的一点**:`\newcommand` 展开层必须支持
  "单 token 或 {} 组"两种必选参数形态。
- **星号** `s` → `_ s:"*"?` 返回 boolean。
- **参数前空白**:每个参数规则以 `_`(skip_space)开头,吃空格/换行/注释但不吃
  段落空行(`!break`)——近似 TeX 控制词后空白吞噬,fixture "mixed with space
  and comments" 专测。
- **`X` 参数类型 + `preExecMacro`**:签名中 `X` 位置触发 `g.macro(name,
  parsedArgs())` **当场先执行一次**(参数还没收齐),用于 `\textbf` 这类需要先
  改解析状态(进组+设字体)再解析参数体的宏;最终 `endArgs` 后再真正执行一次。
  即"一个宏可以执行两次:中途副作用 + 最终产出"。我们不需要,但它揭示了一个真
  实需求:宏调用要能在参数解析中途产生解析副作用。
- **组平衡状态机**(`groups.ts` / generator.ls):两条栈——`_stack` 每级存
  attrs/align/currentlabel/lengths(`enterGroup/exitGroup`),`_groups` 每层存
  花括号差值(`startBalanced/endBalanced/isBalanced`)。文档/环境内默认
  **unbalanced**(`}` 直接交给上层规则结束),参数内默认 **balanced**(`}` 才能
  被识别为参数结束)。`text` 规则里 `{` 进组、`}` 仅在 unbalanced 时退组——
  用"是否处于强制平衡区"区分"组括号"和"定界括号",小巧有效。
- **宏名表防原型污染**:`hasMacro` 黑名单
  `constructor/toString/valueOf/hasOwnProperty`(generator.ls:142)——我们的
  宏表也该防 `__proto__` 系键名。

### 3.3 数学与 verbatim:整体保护(直接可抄的思路)

文法里 `math` 规则把 `$...$`/`$$...$$`/`\(...\)`/`\[...\]` 的**内部全部当成原
始字符**:`math_primitive` 只匹配 `escape identifier`(宏名原样吞,不执行)、
分组、`^`/`_`、`&` 等,拼成字符串 `m` 交给 `g.parseMath(m, ...)` → KaTeX。
**数学里的宏从不展开**——这正是我们要的"公式宏整体保护":扫描时把 `$...$` 当
不透明区间跳过即可,LaTeX.js 证明这条路在工程上完全够用。`\verb` 同理,文法
逐字符读到分隔符为止。

## 4. 和 plasTeX 的设计差异:plasTeX 是真 TeX,LaTeX.js 是 CFG 解析器

| | LaTeX.js | plasTeX(参照,待另一 agent 详评) |
|---|---|---|
| 输入处理 | PEG 一次通过,字符→DOM | 字符→token(catcode 表)→ token 流 |
| 宏 | JS 函数,签名驱动参数解析 | 替换文本 + 参数文本,真 `#n` 替换 |
| `\def`/`\newcommand` | **不支持**(文档明说) | 支持,宏在运行时定义/重定义 |
| 展开/执行两阶段 | 明确不区分 | 区分(有 expansion 概念) |
| 用户宏的能力上限 | 零(要写 JS) | 接近真 TeX |
| 参数形态 | 仅 `{}`/`[]` 定界 | undelimited 单 token、定界参数文本 |
| 复杂度来源 | 文法规模(每种参数一条规则) | 展开循环 + 上下文敏感 |

作者自己在 limitations.md 引了 "TeX 无静态 parse tree" 的四个问题(动态作用域
定参数、宏作参数、词法宏系统、可改语法),然后**主动选择放弃**:只认标准
LaTeX 语法子集。结论:plasTeX 远比 LaTeX.js"真";LaTeX.js 的强项是用约 2.5k
行引擎把"标准 LaTeX 文档 → 保真 HTML"做通了,靠的是把语义问题全部改写成
JavaScript。

## 5. 对我们"受限宏展开层"的借鉴

目标重述:对体内含可译文本的 `\newcommand` 做 `#n` 参数替换展开;数学/不可译
宏整体保护。

**可直接简化抄走的:**

1. **宏签名表模型**:`Map<name, {nArgs, optDefault, body}>`——`\newcommand` 的
   `[n][dflt]` 天然是签名式(无定界参数文本),LaTeX.js 的 `args` 表 +
   `beginArgs` 栈结构几乎可直接映射:`\foo[2][x]{body}` → `{mandatory:2,
   opt:{default:'x'}, tokens:[...]}`。调用时先按需尝试 `[`,再依次取 n 个
   "单 token 或 {}组"参数。
2. **组平衡状态机简化版**:我们只需要一根花括号计数栈区分"`{`组括号 vs 参数定
   界括号",不需要 attrs/lengths 那套(那是 HTML 属性继承用的)。`groups.ts`
   的 `_groups` 栈 ~50 行逻辑足够参考。
3. **数学保护**:扫到 `$`/`$$`/`\(`/`\[`/`\begin{equation}` 等,跳到配对定界
   符,区间内不展开——对应 `math_primitive` 的"只吞不展开"。
4. **符号表先行**:`symbols.ts` 模式——`\alpha` 等在查宏表前先查 unicode 符号
   表,文字类宏可以零成本直译。
5. **宏表有序覆盖**:后定义覆盖先定义(`#macroPkg` 倒序查),`\renewcommand`
   语义免费获得;加 JS 关键字/原型键黑名单(防 `__proto__`)。
6. **参数前空白处理**:`skip_space` 规则——参数前吃 `sp/nl/comment` 但停于空
   行(段落边界),这是 `fixture/macros.tex` 反复测的行为,我们照做。
7. **`X`/preExecMacro 的教训**:若以后遇到"展开结果要改变后续解析"的宏(如
   字体声明影响可译性判定),需要中途执行钩子;一期可不做。

**不能抄、需自研或看 plasTeX 的:**

- **token 级替换**:LaTeX.js 完全没有。我们要的 `#1→arg` 替换、body 重扫、
  递归展开(宏体里再调宏)、深度上限(建议 50-200 可调,防 `\def\x{\x}`),
  得按 plasTeX 的 Expander/token 模型自己写。
- **undelimited 参数**:LaTeX.js 不支持;真 TeX 的必选参数是"单 token 或组",
  `\newcommand` 层必须实现(否则 `\textbf a` 类输入挂掉)。
- **`##`→`#`、嵌套定义、`\expandafter` 系**:都不在 LaTeX.js 视野内。受限层可
  明确拒绝(报错/保护)而非实现——这是"受限"二字的合理边界,LaTeX.js 的存在
  恰好证明"砍掉这些仍能覆盖大量真实文档"。

**一句话定位**:LaTeX.js 验证了"签名驱动参数解析 + 数学整体保护"这条路对标准
LaTeX 文档足够,而且只要 ~2.5k 行引擎;我们比它多做的唯一硬部分是 `#n` 替换展
开——这部分它给不了参考,主力参考是 plasTeX。

## 6. 体积与复杂度

| 部件 | 行数 | 备注 |
|---|---|---|
| `src/parser/latex-parser.pegjs` | 1069 | 全部"语法"。其中 ~300 行是 xcolor 颜色表达式、picture 坐标、tabular 列规格等 LaTeX 专项文法;核心文本/宏/组骨架 ~500-600 行 |
| `src/macro-manager.ts` | 313 | 包注册 + 宏查找 + 参数签名栈 |
| `src/macros.ts` | 152 | 类型 + 装饰器 |
| `src/generator/*` + `html/*` | ~1088 | DOM 生成、组栈、计数器、HTML 元素 |
| `src/types.ts` | 288 | Length(sp 内部表示!)/Vector |
| `src/latex/latex.ltx.ls` | 1333 | ~147 个宏的标准库(JS 实现) |
| packages + documentclasses | ~1200 | xcolor/graphicx/hyperref 等 14 个 |
| **合计(TS+LS+PEG,无 CSS)** | **~7.4k** | ls/ts 有约 2.7k 功能重复(迁移中) |

"引擎"净重 ≈ 文法 1069 + 宏管理 313 + 宏类型 152 + 生成器 ~800 ≈ **2.3k 行**
(不含宏库本身)。对照之下 plasTeX 的 token 机 + 展开器体量明显更大。

**我们的受限展开层估算**(不含翻译层):
- tokenizer(固定 catcode:escape/组/数学/参数记号/字母/其他/空白/注释):
  ~200-300 行
- `\newcommand`/`\renewcommand`/`\providecommand` 签名与 body 提取(含 `##`
  拒绝):~100-150 行
- 展开主循环(签名取参:`[]`可选 + n×"单token或组"、`#n` 替换、重扫、深度上
  限):~250-350 行
- 数学/verbatim/不可译宏保护 + 符号表:~100 行

合计 **~600-1000 行**即可覆盖 LaTeX.js 所证实的"标准文档子集"+ 我们独有的
`#n` 展开。这比预想小,关键原因是 `\newcommand` 没有定界参数文本——签名表方案
(抄 LaTeX.js)比 TeX 的 parameter-text 匹配省一大块。

## 附:关键文件索引

- `/tmp/latex-refs/LaTeX.js/src/parser/latex-parser.pegjs` — 文法(catcode 注释在 913-993;macro/macro_args 在 211-296;组平衡 arg_group 在 444-484;math 在 873-894)
- `/tmp/latex-refs/LaTeX.js/src/macro-manager.ts` — 包/宏表/参数签名栈(149-313)
- `/tmp/latex-refs/LaTeX.js/src/macros.ts` — ArgType/MacroMode 定义 + 装饰器
- `/tmp/latex-refs/LaTeX.js/src/generator.ls` — 旧版生成器(宏表、组栈、计数器、label/ref;152-217 是参数栈机制)
- `/tmp/latex-refs/LaTeX.js/src/generator/groups.ts` — 组平衡状态机(TS 版,99 行)
- `/tmp/latex-refs/LaTeX.js/src/generator/counters.ts` — 计数器 + `newcommand` 死代码(41 行)
- `/tmp/latex-refs/LaTeX.js/src/latex/latex.ltx.ls` — 标准宏库(~147 宏;`\textbf` 的 X-双阶段在 278-307)
- `/tmp/latex-refs/LaTeX.js/src/latex/packages/echo.ts` — 最小宏包样例(测试用)
- `/tmp/latex-refs/LaTeX.js/docs/limitations.md` — 作者自述:"no way of defining macros"、不区分 expansion/execution、TeX 不可静态解析的四个问题
- `/tmp/latex-refs/LaTeX.js/docs/extending.md` — CustomMacros 机制 + args 签名表文档
- `/tmp/latex-refs/LaTeX.js/test/fixtures/macros.tex` — 参数解析行为基准(空白/注释/嵌套括号)
