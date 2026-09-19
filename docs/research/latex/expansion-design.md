# 宏展开层设计规格 — 扫描中即时展开（gullet 模式）

> 状态：设计定案稿（待评审）。参考实现：plasTeX 3.1（`tmp/refs/plastex/plasTeX/`，行号均指该副本）。
> 前置：`docs/04-selection-context.md` §2（六类定义范围定案）、`bench/results/macro-stats-report.md`（语料实测）、`bench/py/miniscanner.py`（现行骨架，行号指该文件）。

## 0. 结论速览

| 决策点          | 定案                                                                                                                                                                                                                            | 依据                                                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 展开架构        | **三段流**：Mouth(tokenize) → Gullet(回压式展开) → Segmenter(分段)。Gullet 拉取 Mouth 的原始 token，命中宏则读参代入、把展开结果**推回流前端**，分段器只见展开后 token                                                          | plasTeX `TeX.__iter__` TeX.py:281-340；tokenizer/展开器分离是唯一能同时满足"正文内定义 (51%)"+"`#{` 定界参数"+"\input 由宏产出"的形态 |
| 扫描时机        | **扫描中建表 + 调用点即时展开**（docs/04 已定），宏定义命令本身由 gullet 消费并登记                                                                                                                                             | macro-stats §1:268 个定义在 `\begin{document}` 后                                                                                     |
| 展开边界        | 只展开**用户宏 + 少数原语**（`\input \endinput \if族 \expandafter \csname \noexpand \makeatletter`）。LaTeX 内建命令（`\section \cite …`）不展开，原样交给分段器按 argspec 表处理                                               | plasTeX 同构：`macroName is not None` 才 invoke（TeX.py:312）                                                                         |
| `\def` 定界参数 | 移植 plasTeX `Definition.invoke`（`__init__.py:1170-1235`，约 65 行）+ `expandDef`（`__init__.py:1096-1127`），详见 §5.3                                                                                                        | 实测支持 `\def\ra[#1 #2 #3]`、`#{` 尾随组                                                                                             |
| 限制            | 三级防护：`gen` 代数上限 32（每 token 携带，展开产物 gen+1）+ 全局步数预算 100k/doc + 输入栈深度 8                                                                                                                              | plasTeX **没有**任何限制——`\def\x{\x}` 会死循环，是我们必须补的                                                                       |
| 展开失败降级    | 定义解析失败→不登记；调用点参数不匹配→回吐已读 token、调用整体按不透明保护；gen/预算耗尽→调用原样输出为 `[[MACRO_n]]`                                                                                                           | UnrecognizedMacro 兜底思路（`__init__.py:1046`），但落点是"保护段"非 DOM 节点                                                         |
| `\if` 处理      | **两档**：可求值者（常量/`\ifmmode`/`\newif` 旗标/`\ifnum`字面量/`\ifdefined`）→ 吃掉条件、推回选中分支（丢弃分支不进分段器）；不可求值者 → `\if/\else/\fi` 作结构界标 literal piece，两分支都扫（翻译端全收，编译端 TeX 自决） | plasTeX 全求值（`processIfContent` TeX.py:531-585），我们不照搬——求错值的代价是丢文本，双扫的代价只是多翻                             |
| `\input`        | **扫描中展平**：`\input` 原语在 gullet 里把新 Mouth 压入 inputs 栈（TeX.py:143-177 同构），pos 记 `(file_id, offset)`；注释/verbatim 内的 `\input` 天然不触发（Mouth 层吃掉）                                                   | miniscanner 现行是扫描前 `flatten_inputs`（miniscanner.py:1354-1454）；改成扫描中后宏产出的 `\input` 也能展平                         |
| `\makeatletter` | Mouth 的 catcode 表挂可变 `@` 项；`\makeatletter/\makeatother` 流经 gullet 时副作用翻转 + 原样吐给分段器                                                                                                                        | plasTeX `makeatletter` Base/LaTeX/**init**.py:61-63；拉取式 tokenize 才有效（先 tokenize 全文再翻 catcode 无效）                      |
| 宏作用域        | scope 链：`{`/`\bgroup`/`\begin{env}` 推、`}`/`\end` 弹；`\gdef/\xdef/\global` 写底帧，其余写顶帧；`\newcommand` 按 LaTeX 语义**也算局部**（与 plasTeX 一律 addGlobal 不同，见 §8）                                             | Context.py:787-831 addGlobal/addLocal                                                                                                 |
| oracle          | plasTeX 屏蔽 `.sty/.cls` 后 DOM `par` 节点可提取段落，实测 ms.tex 0.2s/158 段、ATLAS 0.9s/329 段；用 `SequenceMatcher` 对规范化文本流做 recall 对拍                                                                             | 见 §11 + `tmp/exp/oracle/oracle_probe.py` 实验记录                                                                                    |

---

## 1. 总体模型：mouth / gullet / segmenter

TeX 自身的三段式：mouth（字符→token）、gullet（token→展开后 token，宏展开唯一发生地）、stomach（排版执行）。plasTeX 逐层对应，texlate 借用前两段 + 用分段器替代 stomach：

```
文件字节流
   │  Mouth (每输入文件一个，栈式)
   │    · 字符→token；三态 N/M/S；注释整行吞掉不产 token
   │    · plasTeX: Tokenizer.__iter__  Tokenizer.py:333-483
   ▼
   Gullet (全局一个)
   │    · read() 拉原始 token（回压缓冲优先 → inputs 栈顶 Mouth）
   │    · cs token 命中宏表/原语 → 按 argspec 读参 → 代入 → 推回前端
   │    · plasTeX: TeX.itertokens + TeX.__iter__ + pushTokens
   │      TeX.py:249-279, 281-340, 441-467
   ▼
   Segmenter (分段器 = 现 miniscanner 主循环的演化)
        · 消费"展开后 token 流"，产出 pieces/chunks/placeholders
        · 一切输出物保留 byte_range（见 §2.3 虚拟 token 的 pos 规则）
```

与 plasTeX 的关键差异：plasTeX 的展开产物是 **DOM 节点**（`invoke` 返回 `None`→节点入流，TeX.py:323-329）；texlate 的产物是**带 byte_range 的 token**，因为最终要做区间 splice（`docs/02-architecture.md` §1 区间替换模型）。这决定了 §6 的"分类展开而非物化展开"策略。

## 2. Token 与 Mouth 规格

### 2.1 Token

```python
@dataclass(slots=True)
class Tok:
    kind: str  # 'cs' | 'lbrace' | 'rbrace' | 'mathshift' | 'param'
    # | 'space' | 'eol_par' | 'letter' | 'other' | 'active'
    text: str  # cs→名字 (不含\)，其余→字符本体
    pos: tuple  # (file_id, offset) —— 源 token 的字节位置；
    # 展开产物见 §2.3
    gen: int = 0  # 展开代数：源 token=0，宏展开产物=触发者 gen+1
```

- `eol_par`：连续 `\n\n`（及 `\par`）折叠为一个段落边界 token —— plasTeX 用 `EscapeSequence('par')`（Tokenizer.py:388-408），我们把 `par` 也归一为 `eol_par`，分段器靠它切 chunk。
- 不设 `catcode` 全量字段：kind 已是归并后的类别；需要的只有 `mathshift/param/lbrace/rbrace` 做结构与参数处理。active 字符（`~`）保留 `active` kind 单独派发（`~` → 不断行空格，分段器当字面量）。

### 2.2 Mouth（移植 Tokenizer.py:333-483）

```python
class Mouth:
    def __init__(self, text: str, file_id: int, cats: CatTable):
        self.buf = text
        self.i = 0
        self.state = S_N  # N=行首 M=行中 S=吸空白
        self.tokbuf: deque[Tok]  # 回压缓冲（pushTokens 落点）
        self.cats = cats  # catcode 表引用（@ 可变）

    def next(self) -> Tok | None: ...
```

逐条对应 plasTeX 行为：

| 行为         | plasTeX 源                                                                           | texlate 移植要点                                                                                        |
| ------------ | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| 回压优先     | `while mybuffer: yield mybuffer.pop(0)` Tokenizer.py:367-368                         | `tokbuf` 先空先出；`push_tokens` 逆序塞左端（Tokenizer.py:319-331）                                     |
| 空白折叠     | space → state S；行首/行内多空格合一 Tokenizer.py:381-387                            | 同                                                                                                      |
| 换行         | EOL：S 态跳过；M 态→Space；N 态→`par`（相邻 par 去重 prev 检查）Tokenizer.py:388-408 | N 态 `\n`→`eol_par`；`\n\n` 由"连续 par 去重"天然折叠                                                   |
| 注释         | `CC_COMMENT → readline()` 整行吞掉，**不产 token** Tokenizer.py:466-470              | **`\input`/`% \newcommand` 被注释即消失的直接保证**——注释在 Mouth 层终结，永不进 gullet                 |
| 转义序列     | `\`+字母串→cs；`\`+非字母→单字符 cs；`\`+EOL→Space Tokenizer.py:411-453              | cs 名后随空白按 state S 吸收（`\foo  x`→`\foo`+1 space）                                                |
| catcode 查询 | 逐字符 `context.whichCode(ch)` Tokenizer.py:253,272                                  | 每字符过 `cats.code(ch)`；`@` 的 letter/other 翻转即查即用（§9）                                        |
| `^^X` 序列   | iterchars Tokenizer.py:274-288                                                       | v1 可不做（语料 ~0），留接口                                                                            |
| `\let` 别名  | `context.get_let(token)` Tokenizer.py:456,474                                        | 不做 Mouth 层解析——`\let` 在 gullet 建别名表项，宏表查找时解引用（§8），等价且少一条 Mouth→Context 依赖 |

### 2.3 展开产物的 pos 规则（区间替换模型的硬约束）

展开产生的 token **没有源字节位置**。规则：

- 宏体 token 的 pos = **定义体区间** `(file_id, def_body_offset)`，并打 `gen>0` 标；
- 分段器对所有 `gen>0` token 遵守：**不以其 pos 做 splice**——只用来做类型判定（math env？cite？文本？）；
- 调用点 splice 一律用**调用 token 的 pos**（`\be` 自己的位置）：`\be...\ee` 整段保护时 `[[MATH_n]]` 包的是 `\be` 到 `\ee` 的**原始字节**，不是展开文本（§6.2）。

→ 推论：宏展开在 texlate 是**分类器/识别器**，不是文本物化器。这区别于 plasTeX（展开产物直接进 DOM 渲染）。

## 3. Gullet：回压式不动点展开

### 3.1 数据结构

```python
class Gullet:
    inputs: list[Mouth]  # 输入栈 = TeX.inputs (TeX.py:72)
    macros: MacroTable  # scope 链 (§8)
    ifflags: dict[str, bool]  # \newif 旗标
    math_depth: int  # $/\(/\[/math env 计数 → \ifmmode 求值
    steps: int = 0  # 已展开步数
    BUDGET = 100_000  # 每文档展开步数上限
    MAX_GEN = 32  # token 代数上限
    MAX_INPUTS = 8  # \input 嵌套深度（同 miniscanner.py:1366）
```

### 3.2 原始流 `read()`（对应 `itertokens` TeX.py:249-279 + `pushTokens` TeX.py:441-467）

```python
def read(self) -> Tok | None:
    while self.inputs:
        t = self.inputs[-1].next()  # 回压缓冲在 Mouth 内部优先
        if t is not None:
            return t
        self.inputs.pop()  # 输入耗尽弹栈 = endInput (TeX.py:165-177)
    return None


def unread(self, toks: list[Tok]):  # pushTokens (TeX.py:455-467)
    if toks:
        self.inputs[-1].push_tokens(toks)  # 压回当前 Mouth 的 tokbuf 前端
```

读参（`readArgument`）一律走 `read()`——**参数读的是未展开 token**，与 plasTeX 用 `itertokens` 读参一致（TeX.py:704-714, 786-841）。

### 3.3 展开主循环 `next_expanded()`（对应 `__iter__` TeX.py:281-340）

```python
def next_expanded(self) -> Tok | None:
    while True:
        t = self.read()
        if t is None:
            return None
        if t.kind != "cs" or t.name not in self.expandables():
            return t  # 普通 token/内建命令 → 直交分段器
        if t.gen >= self.MAX_GEN or self.steps >= self.BUDGET:
            return t  # 降级：未展开原样交出（gen>0 ⇒ 分段器按不透明宏调用保护）
        self.steps += 1
        try:
            result = self.expand(t)  # None | [] | [Tok...] | MARKER
        except ExpandError:
            return t  # 展开失败降级（§3.5）
        if result is None:
            return t  # 命令自身即输出（本设计基本不用）
        if isinstance(result, Tok):  # 副作用型原语（makeatletter 等）返回自身
            return result
        self.unread(result)  # 展开结果推回前端 → 不动点
        # 不 return —— 继续循环，新推入的 token 再判是否宏
```

`expandables()` = 宏表 ∪ 原语集 `{def,edef,gdef,xdef, let, newcommand,renewcommand,providecommand, DeclareRobustCommand, newenvironment,renewenvironment, DeclareMathOperator, NewDocumentCommand(+Renew/Provide/Declare), newtheorem, newif, input,endinput,include, if族(见§7), else,fi, expandafter,csname,endcsname, noexpand,long,outer, makeatletter,makeatother, catcode, newif-setter, ifundefined}`。

**关键性质**（逐条来自 plasTeX，移植后必须保持）：

1. **读参读原始 token**：`Definition.invoke`/`NewCommand.invoke` 里 `tex.readArgument` 走 `itertokens`（未展开流）——`\foo\bar` 把 `\bar` 原样作参（`__init__.py:1184,1154`）。
2. **展开结果回压到同一流**：`pushTokens` 压当前输入栈顶的 tokbuf，外层循环立刻重读（TeX.py:328 + Tokenizer.py:367）——`\be` 展开的 `\begin{equation}` 下一个循环即被分段器视角"看到"。
3. **选路分支不进流**：`processIfContent` 从 `itertokens` 收集分案例、只推回选中支（TeX.py:552-585）——被 `\iffalse` 跳过的 `\def` 永不执行，这是"结构化 \if"正确的唯一途径。
4. **副作用命令也在流内**：`\makeatletter` 是 token，流经时翻转 catcode——顺序语义天然正确。

### 3.4 限制与递归检测

plasTeX 无任何限制（`\def\x{\x}` 死循环——它靠外层 alarm 兜底，`plastex_nokpse.py` 用 `signal.alarm(60)`）。texlate 三层：

| 层         | 机制                                                                  | 触发后                                                                                        |
| ---------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| token 代数 | 宏展开产物的 `gen = 触发 token.gen + 1`；`gen > MAX_GEN(32)` 不再展开 | 该 cs 按不透明宏调用输出（保字节）                                                            |
| 全局步数   | `steps` 每 `expand()` 一次 +1；超 `BUDGET(100k)`                      | 后续所有 cs 不再展开；记 `expansion_overflow` 事件                                            |
| 输入栈     | `len(inputs) > MAX_INPUTS(8)` 时 `\input` 拒绝压栈                    | `\input` 调用本身 literal 输出；循环引用另用 `_seen` 绝对路径集去重（沿 miniscanner.py:1434） |

直接自指 `\x→\x` 会被 gen 机制在 32 步内掐停；`MAX_GEN` 取值依据：正常宏嵌套（`\be→\begin`、`\Figref→Figure~\ref`）≤4 代，32 已 8 倍余量。不做 plasTeX 式 invoke 递归——我们全程迭代，无 Python 栈风险。

### 3.5 展开失败降级表

| 失败                                                     | 处理                                                                                                                                                      |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 定义语法解析失败（如 `\def` 后非 cs、参数文本残缺）      | 不登记宏表；定义区段按 literal 原样发出；该名后续调用走"未知命令"路径（miniscanner 现行：带参→`[[CMD_n]]`，miniscanner.py:1128-1136）                     |
| 调用点参数不匹配（定界参数找不到 delimiter、流提前结束） | **回吐**：已读 token 全部 `unread` 回压，`\name` 本体按不透明宏 `[[MACRO_n]]` 输出；bytes 一个都不能丢（pos 区间拼接校验：调用起点→回吐末位连续覆盖原文） |
| 参数数读满前流尽                                         | 同上回吐降级                                                                                                                                              |
| gen/BUDGET 超限                                          | `\name`+已读参整体 `[[MACRO_n]]`                                                                                                                          |
| `\input` 文件不存在                                      | warning + `\input{..}` 原样 literal（plasTeX 同，Primitives.py:434-440）                                                                                  |
| 宏体本身畸形（如体含未配对 `}`）                         | 定义时 `_match_brace` 类校验失败 → 不登记                                                                                                                 |

原则：**任何降级都必须保证 splice 后字节级 identity**——降级输出永远是"原文某连续区间"，不是展开文本。

## 4. 六类定义的统一 argspec

### 4.1 ArgSpec 表示

```python
@dataclass
class Arg:  # 参数槽（调用点读取顺序即列表序）
    kind: str  # 'm'      强制：{..}或单 token（TeX undelimited）
    # 'o'      可选：[..]，缺席→default
    # 'star'   字面*，bool
    # 'eq'     可选=号（\let\a=\b）
    # 'delim'  定界参数：读到 delim_toks 为止（不含）
    # 'until_group'  #{ 型：读到 BGROUP 前，'{'回吐不消费
    delim: list[Tok] | None  # kind='delim' 的定界 token 序列（逐 token 相等比较）
    default: list[Tok] | None  # 'o' 的缺省值 token
    name: str = ""  # 诊断用


@dataclass
class MacroDef:
    name: str
    spec: list[Arg]  # 定界参数模板也在此
    body: list[Tok]  # 替换文本（含 #n Parameter token）
    kind: str  # env_begin|env_end|opaque|transparent|literal|math
    target_env: str = ""
    protect_args: tuple[bool, ...] = ()
    scope: str = "local"  # local|global（\gdef/\xdef/\global 前缀→global）
    src: tuple = ()  # (file_id, def_start, def_end) 登记位置
```

参数代入产出 `params: dict[int, list[Tok]]`（1 基，`#i → params[i]`）。

### 4.2 六类定义 → argspec 编译表

| 定义命令                                       | 解析语法                                                               | argspec                       | body                            | 备注                                                                                                                                                                                                                                |
| ---------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `\newcommand[*]{\n}[N][d]{B}`                  | `* name:cs [n:int] [d:nox] B:nox`（plasTeX `Definitions.py:17`）       | `[o(d)?] + m×(N-1或N)`        | B                               | `*` 只吃 token 不改变语义；N 含可选位（`\newcommand{\x}[2][a]`=#1 可选+#2 强制，plasTeX `nargs-1` `__init__.py:1145-1147`——**miniscanner 现行 `opt+N` 多读一个，是 bug**）                                                          |
| `\renewcommand`                                | 同上                                                                   | 同上                          | B                               | 覆盖写（表语义：`set`）                                                                                                                                                                                                             |
| `\providecommand`                              | 同上                                                                   | 同上                          | B                               | `setdefault`（已存在不覆盖）                                                                                                                                                                                                        |
| `\DeclareRobustCommand`                        | 同上                                                                   | 同上                          | B                               | = `\newcommand`（plasTeX `Definitions.py:32-33`）                                                                                                                                                                                   |
| `\def\N<参数文本>{B}` `\edef/\gdef/\xdef`      | `name:Tok args:Args B:nox`（plasTeX `Primitives.py:130`）              | 参数文本→Arg 序列（§5.2/5.3） | B                               | scope：`\gdef/\xdef`→global，其余 local；`\long` 前缀吃掉即可（`Primitives.py:482`）；**`\edef` 体不预先展开**（plasTeX 同样存未展开 `edef(DefCommand)` Primitives.py:173——调用点惰性展开等价，分歧仅在被定义体内再有定义时，罕见） |
| `\DeclareMathOperator[*]{\n}{B}`               | `* name:cs B:nox`（`amsmath.py:112`）                                  | `[]`（0 参）                  | `\operatorname[*]{B}`（包一层） | kind=math；`amsmath.py:111-123`                                                                                                                                                                                                     |
| `\newenvironment[*]{env}[N][d]{before}{after}` | `* name:str [N] [d] begin:nox end:nox`（`Definitions.py:44`）          | env 表项：`[o]+m×(N-1或N)`    | before                          | 登记 `env:envname`；`\end` 部分只作 env_end 配对不参与代入（`Context.py:1126-1129` 存 `end<name>`）                                                                                                                                 |
| `\NewDocumentCommand{\n}{spec}{B}`             | xparse spec 字母                                                       | spec→Arg 序列（§4.3）         | B                               | 0/39 语料；实现子集 + 降级                                                                                                                                                                                                          |
| `\let\a[ = ]\b`                                | `name:Tok eq:('=') value:Tok`（`Primitives.py:371`）                   | —                             | —                               | 别名表项：`\a`→当前 `\b` 的 MacroDef **快照引用**（\b 后改不影响 \a）；\b 为字符 token→literal 别名                                                                                                                                 |
| `\newif\iffoo`                                 | `name:cs`（`Registers.py:75-78`→`Context.newif` Context.py:1008-1041） | —                             | —                               | 三项登记：`\iffoo`→旗标 (False)，`\footrue/\foofalse`→setter                                                                                                                                                                        |
| `\newtheorem{n}[c]{cap}[w]`                    | `* name:str [c:str] cap [w:str]`（`Definitions.py:62`）                | env 表项                      | —                               | env:`n`→transparent env + caption 元数据（分段器：env 透明扫内容，`[title]` 可选参作 chunk；cap 是"Theorem"类 boilerplate→literal）                                                                                                 |

辅助：`\ifundefined`/\@ifundefined → 以宏表查名推回对应分支（`Base/LaTeX/__init__.py:36-45`）。

### 4.3 xparse spec 子集（`\NewDocumentCommand`）

按字母序解析 spec 串：

| 字母                            | 语义                      | Arg.kind                                      |
| ------------------------------- | ------------------------- | --------------------------------------------- |
| `m`                             | 强制 `{..}`/单 token      | `m`                                           |
| `o`                             | 可选 `[..]` 无默认        | `o`(default=None)                             |
| `O{d}`                          | 可选 `[..]` 默认 d        | `o`(default=d)                                |
| `s`                             | `*` 修饰                  | `star`                                        |
| `tX`                            | 可选 token X 出现否       | `star`(char=X)                                |
| `d<o><c>` / `D<o><c>{d}`        | 可选自定义定界            | `o`(open=o,close=c)                           |
| `r<o><c>` / `R<o><c>{d}`        | 必选自定义定界            | `delim`                                       |
| `u{X}`                          | 读到 X 止                 | `delim`                                       |
| `g`                             | 可选 `{..}` 组            | `o`(brace)                                    |
| `l`                             | 读到 BGROUP 前            | `until_group`                                 |
| `v` / `b` / `e{}` / `E{}` / `x` | 逐字/环境体/embellishment | v1 不实现：spec 含这些字母→整条定义降级不登记 |

## 5. 参数读取与代入实现要点

### 5.1 三种基础读参原语（对应 plasTeX `readArgument` 族 TeX.py:587-908）

```python
def read_undelimited(self) -> list[Tok] | None:  # readToken TeX.py:786-841
    """跳过前置空白后：BGROUP→平衡组 (不含括号) | 单 token。"""


def read_grouping(
    self, open_c, close_c
) -> list[Tok] | None:  # readGrouping TeX.py:863-908
    """[...] 类可选参：首 token 非 escape 且==open → 平衡读到 close。"""


def read_delimited(
    self, delim: list[Tok]
) -> list[Tok]:  # Definition.invoke __init__.py:1211-1219
    """逐 token 读原始流直到 token==delim[0] 且后续==delim[1:]；delim 消费不入参。"""
```

`#` 参数代入 `expandDef`（**直接移植 `__init__.py:1096-1127`**）：遍历 body token，`CC_PARAMETER` 后：再 `#`→字面 `#`；数字→`params[int]` 展开插入；`previous=='ifx'` 时参数外包 `BeginGroup/EndGroup`（`__init__.py:1116-1119` 的 ifx hack——`\ifx` 需要 token 形态参数，我们若无 `\ifx` 求值可省略，但保留无害）。

### 5.2 `\def` 参数文本 → argspec 编译

定义点：`\def` 命令的 `args:Args` 参数类型在 TeX.py:704-714——`Args` 读原始 token 直到首个 `BGROUP`（`{` 回吐留给 body:nox）。即**参数文本=`\def\name` 与 `{` 之间的全部 token**。

编译规则（参数文本逐 token）：

```
PT 中 token a:
  a 是 CC_PARAMETER('#'):
      取下一 token d:
        d ∈ '1'..'9'      → 新参数槽 pending
        d 是 '#'          → 跳过（## 序列）
        d 是 BGROUP('{')  → 前一参数是 `#{` 型: kind='until_group'
        其他               → 参数文本非法 → 整个 \def 不登记
  a 非 '#' 且 pending 参数槽存在:
      pending.kind = 'delim'; pending.delim += [a]   # a 是定界 token
      （连续非# token 构成多 token 定界序列）
  a 非 '#' 且无 pending:
      编译为 'literal_match' 槽: 调用点要求流中下一个 token==a，否则参数不匹配
  结尾仍有 pending:
      pending.kind = 'm'（undelimited，最后参数无显式定界）
```

> 与 plasTeX 的差异：plasTeX 不在定义时编译，而在 `Definition.invoke` 里**每次调用时**重走一遍参数文本（`__init__.py:1177` 起 `for a in argIter`）。我们把同样的判定逻辑前移到 `newdef` 时编译成 `spec`，调用点纯查表——语义等价，省掉每调用的参数文本解析。

**`\def\ra[#1 #2 #3]{...}`（任务用例）编译结果**：

```
spec = [ literal_match('['),
         delim(delim=[space])          # #1
         delim(delim=[space])          # #2
         delim(delim=[']']) ]          # #3
```

调用 `\ra[A B C]`：`[` 字面匹配；`A`（读到空格）；`B`（读到空格）；`C`（读到 `]`）。多 token 定界如 `\def\f(#1,#2){}`：`,` 是 #1 的 delim。

嵌套参数 `##`：`\def` 体里又含 `\def\x#1{..#1..}` 时内层 `#` 写作 `##`——`DefCommand.invoke` 的 nested 检测（`Primitives.py:135-160`）：参数文本/定义体中 `##` 折叠为 `#`。**移植**：定义登记时若体或参数文本出现连续 `##`→按 plasTeX 同款算法先折叠再编译。

### 5.3 `\def` 调用点求值（移植点 `__init__.py:1170-1235`）

```python
def invoke_def(m: MacroDef, tex: Gullet) -> list[Tok]:
    if not m.spec:
        return m.body  # 无参宏直还体 (__init__.py:1171)
    params = {0: None}
    pending = None  # 已见 #n 未读实参的槽
    for arg in m.spec:
        if arg.kind == "literal_match":  # __init__.py:1221-1227
            t = tex.read()
            if t != arg.delim[0]:
                raise ArgMismatch  # → 调用点降级 (§3.5)
            continue
        if pending is not None:  # 上一槽是 undelimited → 先补读
            params[len(params)] = tex.read_undelimited()
            pending = None
        if arg.kind == "m":
            params[len(params)] = tex.read_undelimited()  # __init__.py:1184-1185
        elif arg.kind == "delim":
            params[len(params)] = tex.read_delimited(arg.delim)  # __init__.py:1211-1219
        elif arg.kind == "until_group":  # `#{` __init__.py:1196-1205
            param = []
            for t in tex.read_stream():
                if t.kind == "lbrace":
                    tex.unread([t])
                    break  # '{' 回吐，留给 body 或后续
                param.append(t)
            params[len(params)] = param
    if pending is not None:  # 尾随 undelimited __init__.py:1229-1231
        params[len(params)] = tex.read_undelimited()
    return expandDef(m.body, params)  # __init__.py:1096-1127
```

**踩坑备忘**（来自源阅读，移植时逐条对）：

1. `read_delimited` 的定界 token **被消费但不入参**（`__init__.py:1215-1217` `if t == a: break`）——`\f(#1,#2)` 的 `,` 和 `)` 都吃掉。
2. `#{` 型：定界 `{` **回吐不消费**（`__init__.py:1199-1201`）——`\def\foo#1#{` 的 `{` 留在流里作为后续组的开始。
3. undelimited 参数读 `{..}` 组时**剥掉括号**（`readToken` 组内 token 不含 BGROUP/EGROUP，TeX.py:801-815）；单 token 参数就是单 token——`\foo x`→`[x]`。
4. `readArgument` 前导空白吸收（`stripLeadingWhitespace` TeX.py:599,645-646）；但**定界参数**的空格定界本身参与匹配（`#1 ␣` 的空格是 delim），不冲突——空格吸收只发生在参数槽开头。
5. `params` 1 基：`params=[None]` 起头（`__init__.py:1176`）。
6. plasTeX 在参数不匹配时只 `log.info` 然后 `break`（`__init__.py:1226`）继续流程——我们改为 `raise ArgMismatch`→回吐降级，因为"继续"会默默吞参数字节，对 splice 模型更危险。

### 5.4 `\newcommand` 族调用点（移植 `NewCommand.invoke __init__.py:1135-1163`）

```python
params = {0: None}
if has_opt:
    params[1] = tex.read_grouping("[", "]") or m.opt_default  # __init__.py:1148-1150
for i in range(mand_count):
    params[len(params) + 1] = tex.read_undelimited()  # __init__.py:1153-1155
return expandDef(m.body, params)
```

## 6. 透明 / 不透明宏判定与分段交互

### 6.1 定义时分类（扩展 miniscanner `_register_macro` miniscanner.py:604-620）

| kind          | 判定（按序）                                                                | 调用点行为                                                                                             |
| ------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `env_begin`   | body `strip` 后 `^\\begin\{env\}$` 全匹配（miniscanner.py:609-613）         | 展开 → 分段器见 `\begin{env}` token，按 env 规则处理；**splice 用调用点原文区间**（§2.3）              |
| `env_end`     | `^\\end\{env\}$`                                                            | 同上，供 `_find_env_end` 类配对                                                                        |
| `math`        | body 含 `$ \( \[ \ensuremath \frac \sum \mathbb ^ _` 等数学特征且无可译文本 | 调用点 + 参数整体 `[[MACRO_n]]`（`\dR`、`\wt`、`\Figref` 的 `\ref` 部分也在内——protect_args 标记细化） |
| `opaque`      | `_body_has_text` 否（去命令/参数后无 ≥2 连续字母，miniscanner.py:623-629）  | 调用整体 `[[MACRO_n]]`                                                                                 |
| `transparent` | 其余（体含可译文本）                                                        | 二选一（§6.2）：`inline`（参数承载文本）或 `expand`（体自带文本）                                      |
| `literal`     | `\newif` setter、`\let` 到字符的别名等                                      | 调用 token 原样输出                                                                                    |

`protect_args` 沿用 miniscanner.py:631-647：`#i` 出现在 `\ref/\cite/\label/\url` 参数位 → 该实参整体保护不进 chunk。

### 6.2 transparent 的两个子模式（**新增**，解决"宏体藏可译文本 49%"）

调用点拿到 `MacroDef` 后：

```
transparent-inline（体中可译文本全部经 #i 参数位进入，如 \todo{...} 只有 #1 是文本）：
    → 不物化展开。宏名 token 按 literal 吐给分段器，参数逐个交分段器内联扫
      （miniscanner.py:1230-1249 现行行为；protect_args 位→[[KEY]]）
    → splice 保留 \todo{译文} 结构

transparent-expand（体自带可译文本，如 \def\cmsMessage{Submitted to...}、\papertitle）：
    → gullet 正常展开+推回；分段器在展开 token 上跑常规分段
    → 但 chunk 的 splice 目标不是展开文本：把**调用点区间**登记为 chunk 的
      byte_range，chunk.content = 展开文本的表面（surface）
    → 译文回来时调用点 `\cmsMessage` 整体被译文替换；定义本体在 preamble 原样保留
    → 判据：body 去参数位后仍有可译文本（`_body_has_text(body 去掉 #i)`）
```

混合体（参数位和体都有文本）：取 `expand`——体文本是召回率大头，参数跟着展开流一起被分段。

### 6.3 判定时机

全部**定义时**完成（`newdef` 时打 kind），调用点零分析——`49% 宏体藏文本`的召回靠 `transparent-expand` 分支兜底，不再需要"猜"。

## 7. `\if` 族结构化处理

### 7.1 两档策略（与 plasTeX 全求值的刻意分歧）

plasTeX 对每个 `\if*` 都 `processIfContent(bool)`（`Primitives.py:182-367`），不可求值者硬编常量（`\ifhmode`→True、`\ifvmode`→False、`\ifeof`→False……）。对**翻译**而言，求错值 = 丢一支文本（另一支可能是要翻的内容）。因此：

| 档位         | 条件族                                                                                                                                                                                                                                                                                                                                                                                                                      | 处理                                                                                                                                                                                                                  |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **可求值**   | `\iftrue \iffalse`；`\newif` 旗标 `\iffoo`；`\ifmmode`（math_depth>0）；`\ifnum/\ifodd/\ifdim` 操作数全为字面量（复用 readNumber 简化版：符号 + 数字 + 单位，TeX.py:1433-1641 砍半实现）；`\ifdefined\cs`；`\if`（两 token 文本相等）；`\ifcat`；`\ifx`（两 token 同为 literal 时可比）；`\ifcsname..\endcsname`；`\ifeof \ifvoid \ifhbox \ifvbox \ifinner`→恒 False；`\ifhmode \ifvmode`→按当前模式常量（正文=True/False） | 读条件 → `process_if(bool)`：**case 收集只推回选中支**（§7.2），未选支 token 丢弃——其内 `\def` 不执行、文本不进 chunk，与 TeX 语义一致                                                                                |
| **不可求值** | `\ifnum` 等带寄存器/内部量、`\ifx` 对宏、其他一切                                                                                                                                                                                                                                                                                                                                                                           | 条件部分仍按各自语法读掉（避免 `\count0=1` 泄漏进 chunk），`\if/\else/\fi` 发为结构界标 literal piece（miniscanner `COND_RX` miniscanner.py:389,1084-1088 现行行为），**两分支都进分段器**——召回优先，编译端 TeX 自决 |

新增退化保护：`\ifmmode A\else B\fi` 型宏（1502.01589 一族，macro-stats §2）——在宏体展开流里 `\ifmmode` 由 math_depth 求值，正确支推回；math_depth 由分段器在 `$ \( \[ \begin{数学env}` 处 +1、配对处 -1 维护，回馈给 gullet（`isMathMode` 等价物，Context.py:294-300 的简化——我们只追深度不追节点）。

### 7.2 `process_if` 算法（移植 TeX.py:531-585）

```python
def process_if(self, which: bool | int):
    """收集未展开 token 到 \fi，按 \else/\or 分案例，推回选中案例。"""
    cases = [[]]
    nesting = 0
    for t in self.read_stream():  # 原始流 itertokens (TeX.py:552)
        name = t.name if t.kind == "cs" else ""
        if name == "newif":  # \newif\ifx 对要整对保留 (TeX.py:556-559)
            cases[-1] += [t, self.read()]
            continue
        if name.startswith("if"):  # 任何 if* 计数嵌套 (TeX.py:560-562)
            cases[-1].append(t)
            nesting += 1
        elif name == "fi":
            if not nesting:
                break  # 收尾 \fi 本身不推回 (TeX.py:563-568)
            cases[-1].append(t)
            nesting -= 1
        elif not nesting and name in ("else", "or"):
            cases.append([])  # 分新案例
        else:
            cases[-1].append(t)
    cases.append([])  # 无 else 支的默认 (TeX.py:582)
    self.unread(cases[which if isinstance(which, int) else (0 if which else 1)])
```

要点：`itertokens` 读原始流——被跳过支的宏**不展开**；`newif` 特例保证 `\ifx\newif\ify` 序列不被 `\ify` 误算嵌套。

`\ifcase N` → `which=N`（`Primitives.py:342-346`）。

## 8. 宏表作用域

```python
class MacroTable:
    scopes: list[dict[str, MacroDef|Alias|Flag|Literal]]
    def push_scope(self): ...      # lbrace/bgroup/\begin{env} 分段器回报
    def pop_scope(self): ...
    def lookup(self, name):        # 自顶向下
    def set(self, name, m, scope): # scope='global'→scopes[0], else 顶帧
```

| 操作                                          | 写入位置        | 依据                                                                                                                                                           |
| --------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `\def \edef \newcommand \newenvironment \let` | 顶帧（local）   | LaTeX `\newcommand` 内部是 `\def`→局部；**plasTeX 一律 `addGlobal`（Context.py:1080）是简化**——按局部实现更贴近 TeX，且局部泄漏的代价只是"组外多认了个宏"≈无害 |
| `\gdef \xdef \global\def`                     | 底帧            | `DefCommand.local=False`→`newdef(local=False)`→`addGlobal`（Primitives.py:176-180, Context.py:1162-1165）                                                      |
| 环境 begin 参数宏                             | env 的 scope 帧 | `\begin{env}` 推帧、`\end` 弹                                                                                                                                  |

scope 推弹由**分段器**驱动（它才知道 `{`/`}`/`\begin`/`\end` 的结构语义），经回调通知 gullet。保守退化：若分段器没报（例如参数内组被整块读走），scope 不推——组内 `\def` 会泄漏到外层。可接受（over-expansion ≪ miss），v2 再补 brace 深度回报。

`\let`：别名项存"当时的 MacroDef 引用"（快照）；目标为字符 token（`\let\a=%`）→literal 别名。`context.get_let` 等价物在 gullet 查表时解引用一层。

## 9. `\makeatletter` 区

- **机制**：catcode 表 `cats` 为 Mouth/Gullet 共享可变结构；`\makeatletter` token 流过时 `cats['@']=LETTER`，`\makeatother` 复位（Base/LaTeX/**init**.py:57-63 同构）；两命令同时作为 literal token 交给分段器（输出原样）。
- **必须拉取式 tokenize**：catcode 影响的是"之后字符的归类"，只有 Mouth 按需产 token 才能正确生效——这是"扫描前展平 + 预 tokenize"方案做不了的第二个理由（第一个是 \input）。
- `\documentclass/\usepackage` 期间 `@`=letter 的自动包裹（Packages.py:30-36,57-70）：我们**不加载真包**，故不需要；但 `\makeatletter` 区里定义的 `\foo@bar` 宏在区外被以 `@` 为 other 的状态调用时本来就不可达（TeX 语义），无需特判。
- 语料事实：`\makeatletter` 26% 论文出现（macro-stats §5），多在序言——`\csname`/`\expandafter` 3/39 顺带实现（`Primitives.py:413-424,495-512`，后者是"读两 token、展开后者一次、整体推回"，~15 行）。

## 10. `\input/\include` 展平

| 项             | 定案                                                                                                                                                           | 依据                                                                                                  |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| 时机           | **扫描中**：`\input` 是 gullet 原语，invoke 时把新 Mouth 压 `inputs` 栈；`\endinput` 提前弹栈（`Primitives.py:426-452`）                                       | 宏产出的 `\input`（`\def\main{\input{a}}\main`）也能展平；分段器 pos 体系 (file_id,offset) 天然分文件 |
| 文件查找       | `kpsewhich` 简化版：先 `\input` 所在文件目录、再主文件目录、再 basename±`.tex`（TeX.py:1322-1377 的 TEXINPUTS 拼目录思路 + miniscanner.py:1414-1433 现行顺序） | 无 TeX 安装也要工作                                                                                   |
| 循环           | `_seen` 绝对路径集 + `MAX_INPUTS` 深度                                                                                                                         | miniscanner.py:1434,1366                                                                              |
| 注释内         | `% \input{x}` 在 Mouth 层吞掉（Tokenizer.py:466-470），**天然不展开**                                                                                          | 任务硬要求                                                                                            |
| verbatim 内    | verbatim env 由分段器整块消费，其内 token 不经 gullet → `\input` 不触发                                                                                        | plasTeX 同（`VerbatimEnvironment.invoke` 在 gullet 之前截流，`__init__.py:968-1031`）                 |
| `\includeonly` | 忽略（全部包含；miniscanner 现行同）                                                                                                                           |                                                                                                       |
| 不再做         | miniscanner `flatten_inputs` 扫描前展平（miniscanner.py:1354-1454）**退役**，改由上述机制；保留其"先文件目录后主目录+basename 兜底"的查找顺序                  |                                                                                                       |

## 11. Oracle 对拍工具（`tmp/exp/oracle/`）

**实验结论**（2026-09-14，`oracle_probe.py` 实测）：

- kpsewhich 打桩为"只放行主目录 `.tex`、屏蔽 `.sty/.cls`"后，plasTeX 3.1 成功解析真实语料：`1706.03762/ms.tex` 0.2s → 158 个 ≥20 字符 `par` 段；`1207.7214/TheATLASJulyPaper.tex` 0.9s → 329 段。`par` 节点 = TeX 段落单元，正好对拍我们的 chunk。
- `par.textContent`：宏已展开（`\Figref`→"Figurefig:a"、`\be`→equation 节点、`\ifdraft`→选中支、`\ifmmode`→TEXTBRANCH）；**命令参数会泄进 textContent**（`\citep{key1,key2}`→"key1,key2"）——对拍前需规范化（§11.2 步骤 3）。
- `par.source`：展开后命令串化形式（`\citep {key1,key2}`），同样可用作第二口径。
- 陷阱：无真实 `.sty` 时 `iopart` 等自定义类走 `UnrecognizedMacro` 兜底——段落提取不受影响；但 `\input` 指向的真 `.tex` 必须放行（ms.tex 的 introduction/model_architecture 靠它）。

### 11.1 `oracle_extract.py`（已具雏形：`oracle_probe.py`）

```
输入: main.tex 路径
打桩: TeX.kpsewhich → 仅命中 主目录/*.tex（拒 .sty/.cls/.clo/.def）
      + sys.setrecursionlimit(30000) + SIGALRM 120s/文件
遍历: doc DOM → nodeName=='par' 且 textContent.strip()≥20 字符
输出: JSONL {file, paras:[{text, alpha}]}
      alpha = re.sub(r'[^a-zA-Z ]','', text).lower() 归一表面
```

### 11.2 `oracle_diff.py`

```
输入: oracle JSONL + texlate ScanResult(chunks)
步骤:
  1) oracle 侧: paras → concat → norm_str   (空白折叠、去非字母)
  2) texlate 侧: chunks → 剥 [[PH_n]] → 同规范化 → norm_str'
     (规范化函数两侧同一份代码, 含"命令参数泄入"的近似处理:
      oracle 端把 \citep 的参数误当文本 → 我们 chunks 里对应是 [[CITE_n]] →
      规范化时把 [[*_n]] 替换为 '*' 哨兵而非删除, 让 diff 报"缺失/多余哨兵"而非整段错位)
  3) difflib.SequenceMatcher(None, norm_str, norm_str') → opcodes
  4) 指标:
     recall  = matched_oracle_chars / oracle_chars    (oracle 有、我们漏 → 漏翻)
     noise   = inserted_chars / texlate_chars         (我们有、oracle 无 → 保护泄漏/过度分段)
     输出每文件 {ratio, recall, noise, top5 unmatched windows±80ch}
产物: tmp/exp/oracle/report.json + 差异窗口文本
```

边界对拍（更严格版，可选）：oracle `par` 顺序流 vs chunk 顺序流做 LCS——粒度到"段"而非字符，直接报"整段漏"vs"段内部分漏"。先跑字符级，再看是否需要。

## 12. 移植清单（file:line 速查）

| 组件                   | plasTeX 源                                                                                                                                                                                                                                                     | texlate 落点                                                                                                                     |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 输入栈                 | `TeX.inputs`/`input()`/`endInput` TeX.py:72,143-177                                                                                                                                                                                                            | `Gullet.inputs` + `Mouth`                                                                                                        |
| 回压                   | `pushToken/pushTokens` TeX.py:441-467；`Tokenizer._tokBuffer` Tokenizer.py:204,308-331,367-368                                                                                                                                                                 | `Mouth.tokbuf`                                                                                                                   |
| 展开主循环             | `TeX.__iter__` TeX.py:281-340                                                                                                                                                                                                                                  | `Gullet.next_expanded` §3.3                                                                                                      |
| 原始流                 | `TeX.itertokens` TeX.py:249-279                                                                                                                                                                                                                                | `Gullet.read`                                                                                                                    |
| mouth 三态机           | `Tokenizer.__iter__` Tokenizer.py:333-483（注释 466-470；cs 411-453；par 388-408）                                                                                                                                                                             | `Mouth.next` §2.2                                                                                                                |
| 参数 DSL               | `Macro.arguments` `__init__.py:586-674`（regex 606-608，groupings 610，`*`/`=` 618-630，`type:subtype` 642-666）                                                                                                                                               | 不照搬 DSL 字符串；用 §4.1 编译后 `Arg` 列表（DSL 是 plasTeX 给 Python 类写 argspec 的便利层，我们宏表是运行时数据，直接存结构） |
| 读参                   | `readArgumentAndSource` TeX.py:597-784（`Args` 704-714；`cs` 726-727）；`readToken` 786-841；`readCharacter` 843-861；`readGrouping` 863-908                                                                                                                   | `read_undelimited/read_grouping/read_delimited` §5.1                                                                             |
| `\def` 定界参数        | `Definition.invoke` `__init__.py:1170-1235`（literal 匹配 1221-1227；delim 1211-1219；`#{` 1196-1205；尾随 1229-1231）                                                                                                                                         | `invoke_def` §5.3（定义时预编译 spec，§5.2）                                                                                     |
| 参数代入               | `expandDef` `__init__.py:1096-1127`                                                                                                                                                                                                                            | 同名移植                                                                                                                         |
| `\newcommand` 调用     | `NewCommand.invoke` `__init__.py:1135-1163`                                                                                                                                                                                                                    | §5.4                                                                                                                             |
| 定义命令               | `DefCommand` Primitives.py:127-168（`##` 折叠 135-160）；`newcommand` Definitions.py:15-24；`newenvironment` 42-51；`newtheorem` 61-90；`DeclareMathOperator` amsmath.py:111-123；`let` Primitives.py:369-374；`newif` Registers.py:75-78→Context.py:1008-1041 | §4.2 编译表                                                                                                                      |
| `\if`                  | `if*` 族 Primitives.py:182-367；`processIfContent` TeX.py:531-585；`NewIf/IfTrue/IfFalse` `__init__.py:1063-1094`                                                                                                                                              | §7                                                                                                                               |
| `\input`               | `input` Primitives.py:426-448；`endinput` 450-452；`kpsewhich` TeX.py:1322-1377                                                                                                                                                                                | §10                                                                                                                              |
| `\makeatletter`        | Base/LaTeX/**init**.py:57-63；catcode Context.py:876-890                                                                                                                                                                                                       | §9                                                                                                                               |
| `\expandafter/\csname` | Primitives.py:495-512 / 413-424                                                                                                                                                                                                                                | 顺带实现                                                                                                                         |
| 兜底                   | `Context.__getitem__` Context.py:624-641 + `UnrecognizedMacro` `__init__.py:1046-1061`                                                                                                                                                                         | 未知 cs → miniscanner 现行规则（带参 `[[CMD]]`，否则 literal）                                                                   |
| 作用域                 | `Context.push/pop/addGlobal/addLocal` Context.py:643-728,744-785,787-831                                                                                                                                                                                       | `MacroTable` §8                                                                                                                  |

## 13. 实验记录（`tmp/exp/oracle/`）

- `oracle_probe.py`：屏蔽 `.sty/.cls`、放行本地 `.tex` 的 kpsewhich 打桩下，plasTeX 3.1 在 2 个真实语料上提取段落成功（ms.tex 158 段/0.2s，ATLAS 329 段/0.9s）。DOM `par` 节点可作 oracle；`textContent` 已展开宏但混有命令参数文本，对拍前需归一化。
- 合成样例验证：`\be` 宏展开→equation 节点、`\ifdraft` 按旗标选支、`\ifmmode` 在文本模式取 else 支、`\def\Figref{Figure~\ref{#1}}` 调用点正确代入——oracle 的展开语义与目标设计一致。

## 14. 明确不做（与 docs/04 §2 对齐）

- catcode 通用机制（除 `@` 特例）、active chars 自定义、`\halign`、完整求值器（寄存器算术/盒尺）、`\write/\read/\openout`、e-TeX 扩展、`\uppercase/\lowercase`、xparse `v/b/e/E/x` 参数型。
- plasTeX 的 DOM/stomach（`digest`、`level`、context 对象栈随节点绑）全部不移植——我们只要 mouth+gullet。
- plasTeX 已知不实现：`\edef` 体预展开（惰性等价）、`\let` 的 Mouth 层解析、`\chardef` 语义——我们同样跳过。
