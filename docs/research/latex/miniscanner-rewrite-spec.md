# miniscanner 扶正重写实施规格 — `texlate.latex`

> 输入：`bench/py/miniscanner.py`（1176 行 spike，259/259 语料 + 32/32 陷阱 + 0.11% 泄漏 + identity 100%）。
> 目标：按 `docs/02-architecture.md` §1 的既定设计（`byte_range + kind` 段流 + `[[TYPE_n]]` 占位符 + splice 重建）重写为 `src/texlate/latex/` 正式模块，**顺手修掉残留 25 处泄漏**。
> 本文只给命名、签名、关键算法伪代码与逐条修复映射，不给完整实现。

## 0. 结论速览

1. **整体可搬**：spike 的架构（单遍逐字符扫描 → pieces → 占位符模板 → 不动点重建）已被 259/259 + 32/32 证明，重写是"结构化 + 修 4 个缺陷"，不是换架构。
2. **25 处泄漏归为 4 个机制**（§7 逐条映射），修复全是局部规则，无架构改动：
    - **A（12 处）**：`_args` 的"单 token 参数"兜底（`miniscanner.py:537`）让未知命令 `[[CMD]]` 吞掉 `$` 及其后任意字符 → 全局 `$` 配对错位。**修法：未知命令禁用单 token 参数 + math-debt 修复兜底**。
    - **B（5 处）**：caption/footnote 参数内的注释行原样落进 chunk（注释含 `$`）。**修法：in_arg 上下文注释改发 `[[COMMENT_n]]`**。
    - **C（3 处）**：`\begin{multline*}…\end{multline}` 星号笔误 → `_find_env_end` 失败 → `\begin` 落 run；footnote 内未知 `code` 环境 begin/end 字面落进 chunk。**修法：env 名匹配去 `*` 归一 + in_arg 下未知环境整体 `[[ENV]]`**。
    - **D（4 处）**：`\ifAnonymous{a}{b}` 在 footnote arg 子扫描中被当边界字面 → 落进 chunk。**修法：in_arg 下边界/条件命令改发 `[[CMD_n]]`**。
    - **1 处不可修**（Pset1sol 源文件自身未配对 `$`）→ 记入 warnings，不计修复目标。
3. **预期泄漏**：25 → ≤3（0.11% → ~0.01%）。其余验收指标不得回退（§10）。
4. **主要结构升级**：pieces 由 `("lit"|"chunkph", str)` 二元组升级为带 `src_span` 的 `Piece`（docs/02 已定的 byte_range 模型）；共享可变状态收敛为一个 `ScanState`（"子扫描器必须引用共享"这条教训的正式化）；`_args` 改为 argspec 驱动。

---

## 1. 模块布局

按 `docs/02-architecture.md:92` 的既定目录（`src/texlate/latex/`：scanner, macro_table, placeholder, reconstruct）落位：

```
src/texlate/latex/
  __init__.py        # 公共 API re-export：parse_tex / parse_file / reconstruct / flatten_inputs / ScanResult
  tables.py          # 命令族常量表（纯数据，零逻辑）
  model.py           # Span/Piece/PieceKind/PhType/Chunk/MacroEntry/MacroKind/ArgSpec/ArgSpan/ScanResult/ScanWarning
  placeholder.py     # PH_RX、PlaceholderIssuer（共享计数器）、占位符命名空间
  macro_table.py     # 六类定义命令扫描 + MacroEntry 分类 + argspec 解析
  scanner.py         # Scanner 主循环 + _dispatch_cmd + env/macro/arg handlers + math-debt repair
  flatten.py         # flatten_inputs（\input/\include 展平）
  reconstruct.py     # splice 重建 + 递归展开 + validate
  api.py             # parse_tex / parse_file（preamble 判定、入口装配）
```

职责边界：

- `tables.py` ↔ spike `miniscanner.py:30-390` 的全部常量表，**直接搬**（含 discard 修正后的终值，不写 discard 过程）。
- `model.py`/`placeholder.py` 是被 scanner/macro_table/reconstruct 三方共享的纯数据层，不得反向依赖。
- `scanner.py` 只允许依赖 model/placeholder/macro_table/tables；`reconstruct.py` 只依赖 model/placeholder。
- `api.py` 装配 `flatten → parse`，是唯一允许碰文件系统的地方（`flatten.py` 除外，它读 `\input` 目标文件）。

## 2. 核心数据结构

全部 `@dataclass(slots=True)`。区间一律半开 `[start, end)`，相对**当前 scan 输入串**的偏移；子扫描器通过 `base` 参数把 span 换算回全局偏移（§4.6）。

```python
# model.py
@dataclass(slots=True)
class Span:
    start: int
    end: int

class PieceKind(Enum):
    LITERAL       # 逐字段：注释/preamble/边界命令/环境 tag/宏定义/兜底
    PROTECTED     # [[TYPE_n]]，本体在 ph_map
    CHUNK_REF     # [[CHUNK_n]]，本体在 chunks[i]

@dataclass(slots=True)
class Piece:
    kind: PieceKind
    span: Span          # 该 piece 覆盖的原文区间（pieces 无缝平铺 [0,n) —— 不变式）
    text: str           # protected_tex 中的渲染形：LITERAL=tex[span]，其余=占位符串
    env: str | None     # 所处最内层环境名（调试用，可为 None）

class PhType(Enum):     # [[TYPE_n]] 的 TYPE 全枚举
    MATH   VERB   ENV    CITE   REF    LABEL   URL
    GRAPHICS BIB  CMD    HREF   MACRO  KEY     AUTHOR
    COMMENT COND  ENVTAG                          # ← 新增 3 类（见 §7）
    # CHUNK 不在此列：CHUNK_n 走 chunks[] 而非 ph_map

@dataclass(slots=True)
class Chunk:
    id: int
    content: str              # 渲染形（可内嵌 [[TYPE_n]]）
    context: str              # "paragraph" | "item" | chunk-arg 命令名（section/caption/footnote/title/…）
    span: Span                # 原文区间（定位/调试）
    env: str | None           # 所在环境（如 figure 内 caption → "figure"）
    placeholders: list[str]   # content 内嵌的保护占位符（PH_RX 提取，供译者校验契约）

@dataclass(slots=True)
class ArgSpan:              # 替代 spike 的 (cs,ce,fs,fe) 匿名四元组（miniscanner.py:518）
    content: Span             # 内容区间（去括号）
    full: Span                # 含括号整段；单 token 参数时 content==full
    spec: "ArgSpec | None"

class MacroKind(Enum):
    ENV_BEGIN    # 体 ≡ \begin{X}
    ENV_END      # 体 ≡ \end{X}
    OPAQUE       # 体无自然文本 → 整调用 [[MACRO]]
    TRANSPARENT  # 体含自然文本 → 参数按位分流（protect_args）
    LITERAL      # \newif 注册的 \Xtrue/\Xfalse

@dataclass(slots=True)
class ArgSpec:              # xparse 参数签名项（§5.2）
    kind: str               # 'm'|'o'|'O'|'s'|'d'|'D'|'r'|'R'|'v'|'e'|'t'|'b'
    delim: str = ""         # d/D/r/R/t 的定界符，如 '<>'
    default: str | None = None

@dataclass(slots=True)
class MacroEntry:           # 替代 spike Macro（miniscanner.py:398）
    name: str
    spec: list[ArgSpec]     # 参数签名；classic \newcommand → [m]*n(+前导 'o')
    kind: MacroKind
    target_env: str = ""    # ENV_BEGIN/ENV_END 专用
    protect_args: tuple[bool, ...] = ()   # TRANSPARENT 专用：参数位 → [[KEY]]
    body: str = ""
    def_site: int = -1      # 定义点偏移（全局，调试/审计用）

@dataclass(slots=True)
class EnvEntry:             # \newenvironment 登记（spike 里 "env:" 前缀死代码的扶正，见 §12-W6）
    name: str
    nargs: int
    kind: str               # "protected" | "transparent"（启发式，spike _env_kind_of 同规则）

@dataclass(slots=True)
class ScanWarning:          # 新增：可观测性（泄漏类 bug 的第一手线索）
    kind: str               # "unclosed_env"|"unpaired_dollar"|"stray_end"|"debt_repair"|"def_parse_fail"
    pos: int
    detail: str

@dataclass(slots=True)
class ScanResult:
    protected_tex: str
    chunks: list[Chunk]
    ph_map: dict[str, str]            # "[[TYPE_n]]" → 原文段（可内嵌其他占位符）
    macros: "MacroTable"
    pieces: list[Piece]
    inputs: list[tuple[int, str]]     # (原文位置，文件名)
    warnings: list[ScanWarning]
```

```python
# macro_table.py
@dataclass(slots=True)
class MacroTable:
    cmds: dict[str, MacroEntry]  # 命令名 → 条目
    envs: dict[str, EnvEntry]  # 环境名 → 条目（spike "env:"+name 的显式化）
```

```python
# placeholder.py
PH_RX = re.compile(r"\[\[([A-Z_]+)_(\d+)\]\]")
CHUNK_RX = re.compile(r"\[\[CHUNK_(\d+)\]\]")


class PlaceholderIssuer:  # spike _ctr list-hack 的扶正（miniscanner.py:434）
    def __init__(self):
        self._n = 0

    def new(self, typ: PhType, body: str, ph_map: dict) -> str:
        ...
        # _n += 1; ph = f"[[{typ.name}_{self._n}]]"; ph_map[ph] = body; return ph
```

```python
# scanner.py —— 共享可变状态（"递归子扫描的一切可变状态必须引用共享"教训的容器化）
@dataclass(slots=True)
class ScanState:
    issuer: PlaceholderIssuer
    ph_map: dict[str, str]
    chunks: list[Chunk]
    macros: MacroTable
    inputs: list[tuple[int, str]]
    warnings: list[ScanWarning]
```

## 3. 扫描状态机

### 3.1 主循环分支顺序（`Scanner.scan`）

逐字符 `i` 单调递增、**绝不回退、绝不抛异常**（259/259 零崩溃之源，`miniscanner-report.md` §6）。分支顺序即语义，**不得调换**：

```
while i < n:
    c = tex[i]
    1. c == '\\' → name,j = read_cmd_name → dispatch_cmd()      # 命令先吃（\verb/\url/verbatim env 的 % 永远到不了分支2）
    2. c == '%'  → flush_run + 注释处理（§3.4）                  # 能到这里必是真注释（\% 已被单字符命令吃掉）
    3. c == '$'  → 数学配对（§3.3，含 math-debt repair）
    4. c == '\n' → 空行判定（\n + 空白* + \n）→ flush_run        # 段落边界
    5. 其余      → run.append(c)                                # 含 { } ~ 单字符逐字
flush_run()
```

> 说明：`\\` 与 `%` 互斥首字符，相对顺序无关；关键是 `\` 分支内部把 `\verb|..|`、`\url{..%..}`、verbatim 环境**整段消费**，`%` 判定永远看不到它们（修 ieeA `\url%` 截断 bug 的机制，§8）。

### 3.2 `dispatch_cmd` 分派顺序（名称解析后）

spike `miniscanner.py:944-1136` 的顺序原样保留，每格标注"进 run / 独立 piece / in_arg 变体"：

| #   | 命中                                                                                                 | 处理（顶层）                                                               | in_arg 变体（§3.4）                                                    |
| --- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| 1   | `verb` / `verb*`                                                                                     | `[[VERB]]` 进 run（按定界符吞，新增 EOL 上限，§12-W9）                     | 同左（ph 天然安全）                                                    |
| 2   | `newcommand/renewcommand/providecommand/def/NewDocumentCommand*/DeclareMathOperator*/newenvironment` | flush+ 整段 LITERAL + 登记宏表                                             | 同左（定义在 arg 内几乎不出现，出现则同样逐字）                        |
| 3   | `newif`                                                                                              | flush+LITERAL + 注册 `\Xtrue/\Xfalse` 为 LITERAL 宏                        | 同左                                                                   |
| 4   | `begin`                                                                                              | `_handle_env`（§3.5）                                                      | 同左但走 in_arg 规则                                                   |
| 5   | `end`                                                                                                | flush+LITERAL；`\end{document}` → 本体 + 余下全文 LITERAL，扫描结束        | `[[ENVTAG]]` 进 run（不 flush）                                        |
| 6   | cite 族（`CITE_NAMES` 或 `startswith("cite")`）                                                      | `_protect_call → [[CITE]]` 进 run                                          | 同左                                                                   |
| 7   | ref 族（`REF_NAMES` 或 `endswith("ref")` **排除** `href` 与 TRANSPARENT）                            | `[[REF]]` 进 run                                                           | 同左                                                                   |
| 8   | `PROTECT_NAMES`                                                                                      | 类型映射 `[[LABEL/URL/GRAPHICS/BIB/CMD]]`；`url/path` 用 verbatim 括号匹配 | 同左                                                                   |
| 9   | `href`                                                                                               | 第一参 verbatim 括号 → `\href[[HREF]]{`，第二参继续扫                      | 同左                                                                   |
| 10  | `input/include`                                                                                      | flush+LITERAL + 记 `inputs[]`                                              | `[[CMD]]`（arg 内不展平）                                              |
| 11  | `CHUNK_ARG_NAMES`                                                                                    | `_handle_chunk_arg`（§3.6）                                                | 嵌套 chunk-arg 内联化（spike `_arg_inline` 同语义）                    |
| 12  | `PROTECT_BLOCK_NAMES`                                                                                | flush+`[[AUTHOR]]` 独立 piece                                              | `[[AUTHOR]]` 进 run（不 flush）                                        |
| 13  | `TRANSPARENT_NAMES`                                                                                  | 命令名逐字进 run，参数随主流扫描                                           | 同左                                                                   |
| 14  | `BOUNDARY_NAMES`                                                                                     | flush+LITERAL；`item` 置 `force_chunk`                                     | `_protect_call → [[CMD]]` 进 run（连 `[opt]{arg}` 一起保护，不 flush） |
| 15  | `COND_RX` / LITERAL 类宏                                                                             | flush+LITERAL                                                              | `[[COND]]` 进 run（修泄漏 D）                                          |
| 16  | `\[ \( \] \)`                                                                                        | `\[`/`\(` 找配对 → `[[MATH]]` 进 run；`\]`/`\)` 逐字                       | 同左                                                                   |
| 17  | `INLINE_LITERAL_CMDS`/`FONT_SWITCHES`/单字符（重音/非字母）                                          | 逐字进 run                                                                 | 同左                                                                   |
| 18  | 宏表命中                                                                                             | `_handle_macro`（§3.7）                                                    | 同左                                                                   |
| 19  | 未知命令                                                                                             | **有 `{`/`[` 参数 → `_protect_call → [[CMD]]` 进 run**；否则逐字进 run     | 同左                                                                   |

### 3.3 数学配对 + math-debt repair（修泄漏 A 的第二层）

```
on '$':
    if '$$' 前缀: 找未转义 '$$'，区域内不含 \n\n → [[MATH]]；失败逐字一个 '$'
    else:        找下一未转义 '$'（\' 跳 2 字符；遇 \n\n 中止）→ [[MATH]]；失败逐字 '$' + 记 warning(unpaired_dollar)

debt 机制（新增）：
    state.math_debt: list[int]          # run 下标栈
    _ph_into_run(typ, body):            # 一切占位符进 run 的唯一入口
        ph = issuer.new(typ, body); run.append(ph)
        if 未转义'$'计数(body) 为奇: math_debt.append(len(run)-1)
    on '$' when math_debt 非空:          # 该 '$' 是占位符体内开出的数学的闭合
        idx = math_debt.pop()
        tail = ''.join(run[idx:]) + '$' # 占位符串+其后字面+闭合 $
        del run[idx:]; run.append(issuer.new(MATH, tail)); i += 1
    flush_run 时清空 math_debt（跨段不追）
```

正确性论证：`[[CMD]]` 体含奇数 `$` 意味着它在原文里开启了未闭合数学；其后第一个 `$` 必为闭合符。把它与占位符合并为 `[[MATH]]`（体 = `[[CMD_n]]…$`，内嵌占位符由展开层还原）→ identity 保持，泄漏归零。对 `$$` 同样只消费一个 `$` 作闭合、留另一个重判（罕见，写进 spec 即可）。

### 3.4 注释处理（修泄漏 B）

```
on '%'（能到这里即真注释）:
    k = tex.find('\n', i); 注释段 = tex[i:k or n]
    if in_arg:  run.append(issuer.new(COMMENT, 注释段))     # 进 ph_map → chunk 内只见占位符
    else:       flush_run; emit(LITERAL, 注释段)            # 顶层独立 piece（原行为）
    i = k or n（\n 本身不入注释，回流主循环）
```

identity 不受影响：`[[COMMENT_n]]` 在 ph_map 中逐字还原。顶层注释仍是 LITERAL piece（不进 chunk，无需占位）。

### 3.5 `_handle_env`（修泄漏 C）

```
env = {name}；j = env名 '}' 后一位
1. env ∈ VERBATIM_ENVS → flush；字面 find '\end{env}'（不做括号计数，与 TeX 一致）→ [[VERB]] 独立 piece；找不到 → \begin 行 LITERAL
2. env ∈ MATH_ENVS     → find_env_end（同名计数+宏端点+注释安全+*归一）
                         命中 → [[MATH]] 进 run；未命中 → \begin 行 LITERAL + warning(unclosed_env)   ← 原 run.append 改为 LITERAL（§7-C1）
3. env ∈ PROTECTED_ENVS → find_env_end → flush + _env_with_mined → [[ENV]] 独立 piece；未命中 → LITERAL+warning
4. 其余（透明：itemize/theorem/abstract/minipage/未知…）:
   ├─ 顶层：env_stack.push(env)；吞 [opt] 与 ENV_MANDATORY_ARG 的 {arg} → \begin 行(含参数) LITERAL piece
   ├─ in_arg：
   │    env ∈ ARG_TRANSPARENT_ENVS（itemize/enumerate/description/center/flush*/quote/abstract/minipage 等纯容器）
   │        → \begin行(含opt/mand参数) → [[ENVTAG]] 进 run；env_stack.push
   │    否则（未知/结构环境，如 lhs2TeX code）
   │        → find_env_end → flush-free：run.append(_env_with_mined(...)) = [[ENV]] 进 run（修泄漏 C2）
   └─ env ∈ macro_table.envs → 按 EnvEntry.kind 选 protected/transparent 路径（扶正 §12-W6）
```

`_find_env_end` 两处改动（`miniscanner.py:552-587` 为基准）：

- **星号归一**：比较 `sub.rstrip('*') == env.rstrip('*')`（begin/end 两侧、宏端点 `target_env` 同规则）——`\begin{multline*}…\end{multline}` 笔误场景命中。
- 未命中返回 `None` 时**调用方一律 LITERAL 化 `\begin` 行**（原来 MATH/PROTECTED 分支 `run.append(tex[i:j])` 是泄漏 C1 的根）。

### 3.6 `_handle_chunk_arg`（参数挖 chunk）

```
sig: _handle_chunk_arg(tex, i, j, name, run) -> int
1. 吞 '*' → [opt]（按 CHUNK_ARG_SPEC[name] 的 spec 决定跳几参、哪参可译，见 §5.3）
2. 可译参数 {arg} → 括号匹配取 inner；空 → 整段进 run
3. sub = spawn(mode=MINED_ONLY, in_arg=True, base=i 参数偏移)
   rendered = sub.scan(inner).protected_tex          # in_arg 规则生效：注释/条件/未知env 全占位符化
4. self.in_arg（父在 arg 内）→ run.append(前缀 + rendered + '}')   # 嵌套内联（footnote-in-caption）
   否则 → flush；emit(前缀 LITERAL)；pieces += CHUNK_REF(chunk(rendered, context=name))；emit('}')
```

不变式：chunk 三段（`\caption{` / `[[CHUNK_n]]` / `}`）各自独立 piece —— **块级结构必须独立 piece** 这条铁律的体现（`miniscanner-report.md` §6.1）。

### 3.7 `_handle_macro`（宏表命中）

```
ENV_BEGIN → find_env_end(target_env) → 按 §3.5 的 env 分类走 MATH/VERB/ENV(mined)/透明保护
ENV_END   → 逐字进 run（裸 \ee 无配对 begin 时的容错）
OPAQUE    → _args(spec) → [[MACRO]] 进 run
TRANSPARENT → _args(spec)；按 protect_args 分流：
    保护位 → [[KEY]]；文本位 → spawn(in_arg=True).scan → rendered 进 run
    括号/参数间空白逐字进 run（identity）
LITERAL   → 已在分派 15 拦下
```

### 3.8 flush_run（分块规则，`miniscanner.py:834-857` 原样）

```
s = ''.join(run)
s 全空白 → emit LITERAL
mode == MINED_ONLY → emit LITERAL
clean = s 去 [[..]]占位符 → 去 \命令 → 去非字母；|clean| < 20 且无 force_chunk → emit LITERAL
否则：lead/trail 空白 LITERAL；core → CHUNK_REF piece（context="paragraph" 或 "item"）
```

`force_chunk`（`\item` 后置位）消费一次即复位。chunk.span = run 起止（全局偏移）。

## 4. Scanner 对象模型

```python
class Scanner:
    def __init__(self, state: ScanState, *, mode=ScanMode.NORMAL,
                 in_arg=False, force_chunk=False, base=0):
        self.state = state            # 一切可变状态在此（issuer/ph_map/chunks/macros/inputs/warnings）
        self.mode = mode              # NORMAL | MINED_ONLY
        self.in_arg = in_arg          # 渲染结果将落入 chunk → 字面必须占位符化
        self.force_chunk = force_chunk
        self.base = base              # 子扫描切片的全局偏移（span 换算）
        self.pieces: list[Piece] = []
        self.env_stack: list[str] = []
        self.math_debt: list[int] = []

    def spawn(self, *, mode=None, in_arg=None, base=0) -> "Scanner":
        # 共享 self.state；env_stack 拷贝；其余按参数覆盖
```

- `spawn` 即 spike `_spawn`（`miniscanner.py:1305-1311`）的扶正：**共享只通过 `state` 一个引用**，杜绝 list-hack 漏拷。
- `_emit(s)` → `emit_literal(span)`：构造 `Piece(LITERAL, span, tex[span], env_stack[-1] or None)`。
- 顶层 `scan` 返回时 pieces 必须满足平铺不变式（`p0.start==0`、`end==n`、无缝）——单元测试断言。

## 5. 宏表 schema（六类定义）

`_scan_macro_def(tex, i, name) -> end`（`miniscanner.py:649-784` 重构），逐类登记：

| 定义命令                                                           | 语法                                       | 登记字段                                                                                                                       |
| ------------------------------------------------------------------ | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `\newcommand` `\renewcommand` `\providecommand`                    | `*?` `{\n}`或`\n` `[n]?` `[def]?` `{body}` | `spec=[m]*n + 前导'o'(有def)`；分类 §5.1                                                                                       |
| `\def`（+`\gdef/\edef/\xdef` 同语法，`macro-stats.md` 显示 ~7 例） | `\n`或`{\n}` `#1#2…` `{body}`              | `spec=[m]*#计数`；**局限**：delimited 参数（`\def\f(#1){}`）只数连续 `#n`，记 warning(def_parse_fail)                          |
| `\DeclareMathOperator`（新增，语料 115 次/8 篇）                   | `*?` `{\n}` `{text}`                       | `spec=[]`、`kind=OPAQUE`（数学算子不译）；`{text}` 不入表                                                                      |
| `\newenvironment` `\renewenvironment`                              | `{env}` `[n]?` `{begin-body}` `{end-body}` | `envs[env]=EnvEntry(nargs, kind)`；kind 启发式=体含 `caption/figure` → `"protected"` 否则 `"transparent"`（同 `_env_kind_of`） |
| `\NewDocumentCommand` 系（`Renew/Provide/Declare`）                | `{\n}`或`\n` `{argspec}` `{body}`          | `spec=parse_argspec(签名串)`                                                                                                   |
| `\newif`                                                           | `\ifX`                                     | `cmds[Xtrue]=cmds[Xfalse]=MacroEntry(LITERAL)`（现有逻辑保留）                                                                 |

副表（P2，先留 hook 不实现）：`\let\a\b`（15 例，别名拷贝）；`\newtheorem{thm}{Title}`（148 例，`envs[thm]=transparent` + 标题文本可登记待译）。

### 5.1 三分类判定（`miniscanner.py:604-620` 原样）

```
body.strip() fullmatch '\\begin{X}' → ENV_BEGIN(target_env=X)
           fullmatch '\\end{X}'   → ENV_END(target_env=X)
body_has_text == False            → OPAQUE       # \dR 型
else                              → TRANSPARENT + protect_args = _protected_param_positions(body)
```

`_body_has_text` / `_protected_param_positions`（`miniscanner.py:622-647`）**原样搬**——`\figref→figure~\ref{#1}` 半文本半引用宏的关键机制。

### 5.2 `parse_argspec(spec_str) -> list[ArgSpec]`

```
字符流解析：
  m          → ArgSpec('m')            强制 {}
  o          → ArgSpec('o')            可选 []
  O{def}     → ArgSpec('O', default)   可选带默认
  s          → ArgSpec('s')            星号测试
  d<>/D<>{d} → ArgSpec('d'/'D', '<>')  定界可选
  r<>/R<>{d} → ArgSpec('r'/'R', '<>')  定界强制
  v          → ArgSpec('v')            逐字
  e{..}/t<>  → ArgSpec('e'/'t')        修饰/测试（解析即跳过语义）
  b          → ArgSpec('b')            环境体（只出现在 \NewDocumentEnvironment）
  空白/未知  → skip + warning
```

### 5.3 `_args` 签名升级

```python
def _args(self, tex, i, spec: list[ArgSpec] | int,
          has_opt=False, *, allow_single_token=True) -> tuple[list[ArgSpan], int]
```

- `spec` 为 `list[ArgSpec]` 时逐项消费（m→`{}`、o/O→`[]`、s→`*`、d/D→定界符、r/R→定界强制、单 token 兜底仅当 `allow_single_token`）。
- `spec` 为 `int` 时等价 `[m]*n`（classic 宏路径）。
- **`allow_single_token=False` 是唯一调用点 = 未知命令保护**（分派 19）——修泄漏 A 的第一层（`miniscanner.py:537` 的单 token 分支只保留给已注册宏，那是 TeX 正确语义）。

### 5.4 `CHUNK_ARG_SPEC`（修 `\captionof` 顺带项）

```python
CHUNK_ARG_SPEC: dict[str, tuple[str, int]] = {
    # name → (argspec 串，可译参数下标)
    "captionof": ("mom", 2),     # \captionof{type}[lof]{text} —— spike 错把 {type} 当可译参
    "section":   ("om", 1), "subsection": ("om", 1), …  # 全部 chunk-arg 命令默认 ("om", last)
    "footnote":  ("om", 1), "footnotetext": ("om", 1),
    "title": ("m", 0), "thanks": ("m", 0), "caption": ("om", 1), "subcaption": ("om", 1),
}
```

默认规则：未登记名 → `[opt]?{arg}`（同 spike 行为）。

## 6. 占位符方案

- **格式**：`[[TYPE_n]]`，`PH_RX` 全局唯一正则；`n` 由单一 `PlaceholderIssuer` 单调递增（跨子扫描器共享——`miniscanner-report.md` §6.2 的编号冲突教训）。
- **两个命名空间**：`[[CHUNK_n]]`（可译，`chunks[]` 索引）与 `[[TYPE_n]]`（保护，`ph_map` 映射）。CHUNK 与保护 ph 共用同一方括号语法但不同表，reconstruct 统一展开。
- **嵌套规则**：
    - chunk.content 可含任意保护 ph（`A [[MATH_1]] b [[CITE_2]]`）。
    - `[[ENV_n]]` 体可含 `[[CHUNK_k]]`（保护环境内挖 caption）+ 保护 ph。
    - `[[MATH_n]]`（debt-repair 产物）体可含 `[[CMD_k]]`。
    - `[[COMMENT_n]]`/`[[COND_n]]`/`[[ENVTAG_n]]` 只出现在 chunk 内部（in_arg 产物）。
    - 嵌套深度不限；展开层递归解决（DAG，无环——ph 体要么原文切片要么含更高层渲染结果，构造上不可能成环；assert 兜底）。
- **碰撞**：`[[` 字面在 LaTeX 源出现概率≈0；保险起见 `emit` 时校验 `body` 内不产生 `[[X_n]]` 形新串（不校验，语料 259 篇无碰撞，留 assert）。

## 7. 25 处泄漏逐条 → 修复映射

机制字母 = §0-2 的分类。全部实证见 `bench/results/miniscanner-parse.json` 与 §附录排查记录。

| #           | 文件 / ctx                                                  | 泄漏内容                                                          | 机制                                               | 修复                                                                                |
| ----------- | ----------------------------------------------------------- | ----------------------------------------------------------------- | -------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 1           | 0807.3917/main.tex ¶                                        | `[[CMD_600]][[MATH_601]]\{h_i\}[[MATH_602]]I(W)$`                 | A：`[[CMD]]` 单 token 吞 `$(`                      | `_args(allow_single_token=False)` → `[[CMD]]` 止于 `\num{..}`；debt repair 兜底残余 |
| 2           | 1507.02284/sieve.tex caption                                | `%$Y_1$ is optimized…` 注释行入 chunk                             | B：arg 内注释字面                                  | in_arg → `[[COMMENT_n]]`                                                            |
| 3           | 1612.09375/cfnt.tex ¶                                       | `[[CMD_460]][[MATH_461]]S…F(S)[[MATH_464]]S$`                     | A：CMD 吞 `$\x` 前缀                               | 同 #1                                                                               |
| 4           | 1612.09375/intro.tex ¶                                      | `[[CMD_142]]om U \times V \to W…`                                 | A：CMD 吞 `$\fr` 留 `om`                           | 同 #1                                                                               |
| 5           | 1612.09375/sets.tex ¶                                       | `[[CMD_319]]ta\from \Set \to…\Delta$.`                            | A：CMD 吞 `$\De` 留 `ta`                           | 同 #1                                                                               |
| 6/7         | 1906.08237/exp.tex + neurips_2019.tex caption               | `% … $*$ means ensembles,` 注释行                                 | B                                                  | 同 #2                                                                               |
| 8/9         | 2003.08934/arxiv_submission + resultstable caption          | `% Baselines indicated with $\dagger$…`                           | B                                                  | 同 #2                                                                               |
| 10          | 2201.05989/paper.tex ¶                                      | `[[CMD_121]]7\%)$`（实证 CMD=`\num{53807} $(2.5`）                | A                                                  | 同 #1                                                                               |
| 11          | 2201.05989/paper.tex caption                                | `[[CMD_448]]es[[MATH_449]]…` （CMD=`\num{20000} $\tim`）          | A                                                  | 同 #1                                                                               |
| 12          | 2501.14787/Pset1sol.tex ¶                                   | `\begin{multline*}…\end{multline}` 笔误 → begin+ 全文进 chunk     | C1：`*` 不匹配 `_find_env_end` 失败 → `run.append` | env 名 `rstrip('*')` 归一匹配；未命中时 `\begin` LITERAL+warning                    |
| 13          | 2501.14787/Pset1sol.tex ¶                                   | 源文 `x^T dx).` 本身缺闭合 `$`                                    | **不可修**（源 typo）                              | warning(unpaired_dollar)；泄漏计数可豁免                                            |
| 14/16/18    | 2602.19229/arxiv + structure + ub-flew-calculus ¶           | `[[CMD_1089]] \in J)\n $}`                                        | A：`\AxiomC{…} $\x` 被单 token 吞                  | 同 #1                                                                               |
| 15/17/19    | 2602.19229 同组 ¶                                           | `an [[CMD_1576]]perA_0…`（实证 CMD=`\lrinhypersequent{}\n$\mHy`） | A                                                  | 同 #1                                                                               |
| 20/21/23/24 | 2609.08578/Paper-with-appendices + Paper.processed footnote | `\ifAnonymous{[name omitted]}{Oskar Eriksson}` 入 chunk           | D：条件命令 in_arg 字面                            | in_arg → `[[COND_n]]`                                                               |
| 22/25       | 2609.08578 同组 footnote                                    | `\begin{code}[hide]…\end{code}` 字面入 chunk                      | C2：arg 内未知环境透明 → begin/end 字面            | in_arg 未知 env → `_env_with_mined` → `[[ENV_n]]`                                   |

**汇总**：修复 A（`_args` 禁单 token + debt repair）覆盖 #1,3,4,5,10,11,14–19 共 12 条；B（`[[COMMENT]]`）5 条；C1（星号归一）1 条；C2（in_arg 未知 env 保护）2 条；D（`[[COND]]`）4 条；不可修 1 条。**目标 ≤3 处残留**（#13 + 潜在长尾），泄漏率 ~0.01%。

## 8. verbatim/comment 处理顺序（不变式）

ieeA bug：注释剥离跑在 verbatim 识别前 → `\url{a%20b}` 被截断。本架构的不变式：

> **凡内容可含 `%` 的构造，必须在 `%` 分支判定之前被整段消费。**

实现上是单遍扫描 + `\\` 分支内部自足：

- `\verb|…|`/`\verb*`：`\` 分支内按定界符吞（新增：搜索上限 = 下一 `\n`，TeX 里 verb 不跨行——`miniscanner.py:947` 的 `find(d)` 无界是隐患 §12-W9）。
- `\url/\path` 参数：`_match_brace(verbatim=True)`，`%` 不当注释（`miniscanner.py:463-483` 的 verbatim 参数原样保留）。
- `\href` 第一参：同上 verbatim 括号。
- `VERBATIM_ENVS`：字面 `find('\end{env}')`，内部 `%`/`\end` 注释均不解析（与 TeX 一致）。
- `\lstinline`：从 PROTECT_NAMES 移入 verb 同款定界符处理（spike 只覆盖 `{…}` 形，`|…|` 形漏 → §12-W10）。
- 宏定义体：`_match_brace`（非 verbatim）内 `%` 按注释跳过——与 TeX 语义一致（定义体内 `%` 确是注释）。

## 9. 未知命令策略 + 透明/不透明判定

- **未知命令（分派 19）**：`{`/`[` 参数存在 → `_args(spec=[m]*6, has_opt=True, allow_single_token=False)` → `[[CMD]]` 整段进 run；无参数 → 命令名逐字进 run。保守保护防 key 泄漏（`miniscanner-report.md` §6 已知边界：自定义文本宏 `\ours{方法名}` 不译——接受，配置开关留 P2）。
- **debt 兜底**：任何进入 run 的占位符体含奇数个未转义 `$` → 压栈，下一 `$` 触发合并修复（§3.3）。这使"保护段吞 `$`"从全局配对毒药降级为局部自愈合。
- **宏三分类**：ENV_BEGIN / ENV_END / OPAQUE / TRANSPARENT(+protect_args) / LITERAL（§5.1）。判定在**登记时**一次完成，调用点只查表。
- **透明命令（内置表白名单）**：命令名逐字进 run，参数随主流走（`\emph{重要}` → 文本进 chunk）。
- **cite/ref 词族**：`startswith("cite")` / `endswith("ref")` 前缀后缀匹配覆盖 natbib 全族 + 未收录派生（`\citeCWM`），**显式排除 `href`**（T22 踩过的坑，`miniscanner_test.py:52` 注释）。

## 10. splice 重建算法

```python
# reconstruct.py
def reconstruct(res: ScanResult, translations: dict[int, str] | None = None) -> str:
    """按 pieces.splice + 占位符递归展开（DAG，无 fixpoint 轮次）。"""
    trans = (
        {}
        if translations is None
        else {f"[[CHUNK_{k}]]": v for k, v in translations.items()}
    )

    memo: dict[str, str] = {}

    def expand(token: str) -> str:  # token 形如 [[X_n]]
        if token in memo:
            return memo[token]
        if token in trans:
            body = trans[token]  # 译文优先
        elif token in res.ph_map:
            body = res.ph_map[token]  # 保护本体
        else:
            body = chunk_content(token)  # CHUNK → 原文
        # 单遍替换该体内的所有占位符（体内占位符编号>父级必经子扫描器发出，无环）
        memo[token] = PH_RX.sub(lambda m: expand(m.group(0)), body)
        return memo[token]

    out = []
    for p in res.pieces:  # 平铺不变式保证无缝
        if p.kind is PieceKind.LITERAL:
            out.append(p.text)
        else:
            out.append(expand(p.text))
    return "".join(out)
```

- **identity**：translations=None → CHUNK 落 `chunk.content` → 递归展开全部内嵌 ph → 逐字节 = 原文（pieces 平铺 + ph 体逐字）。
- **相对 spike `str.replace` 不动点**（`miniscanner.py:1343-1350`）的升级：O(轮×文本) → O(总规模) + memo；语义等价（同一替换表迭代至不动点 ≡ DAG 递归展开）。
- **译文侧契约**：译文必须保留 chunk.placeholders 全列；`validate_translation(chunk, text)` 校验缺失/幻觉占位符（缺失 → 报错回退原文，由 translate 层消费——本模块只提供校验函数）。
- `validate_result(res)`：孤儿 chunk（`[[CHUNK_i]]` 不可达）、死 ph、pieces 非平铺 → `warnings`/`ScanWarning`，测试断言 0。

## 11. 测试计划

### 11.1 单元测试（`tests/latex/` 新增）

| 目标             | 用例                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------- |
| `match_brace`    | 嵌套/注释内 `{}` 不计/verbatim 模式/未闭→None                                                                 |
| `match_bracket`  | `[` 内嵌 `{..}` 与 `[..]`、注释安全                                                                           |
| `read_cmd_name`  | `\foo@bar`、`\%` 单字符、`\verb` 后跟定界符                                                                   |
| `find_env_end`   | 同名嵌套、宏端点 `\ee`、注释内 `\end` 不计、**`multline*→multline` 星号归一**、未闭→None                      |
| `_args`          | opt/mand 混合、**`allow_single_token=False` 时 `\num{53807} $(2.5` 只取 `{53807}`**、argspec `s/d<>` 消费     |
| `parse_argspec`  | `"mom"`、`"O{def}d<>s"`、非法字符容错                                                                         |
| math-debt        | `[[CMD]]` 含 `$(` → 后 `$` 合并为 `[[MATH]]`；双 debt 栈序                                                    |
| in_arg           | caption 内注释→`[[COMMENT]]`；`\ifX{a}{b}`→`[[COND]]`；未知 env→`[[ENV]]`；itemize→`[[ENVTAG]]`+item 文本可译 |
| 宏分类           | `\be→\begin{eq}` ENV_BEGIN；`\dR` OPAQUE；`\figref` TRANSPARENT+protect_args；`\newif` LITERAL                |
| chunk 化         | <20 字符弃、`\item` force、lead/trail 空白切分、mined_only 全字面                                             |
| 宏定义点         | 正文内 `\def`（post-`\begin{document}`，语料 51% 论文场景）                                                   |
| `flatten_inputs` | 嵌套相对主目录、注释内 `\input` 不展开、verbatim 内不展开、`_seen` 环                                         |
| `reconstruct`    | identity、三层嵌套（chunk→ENV→CHUNK）、假译文、孤儿检测                                                       |

### 11.2 回归复用

- `bench/py/miniscanner_test.py` 复制为 `tests/latex/test_bench_regression.py`：import 从 `miniscanner` 换 `texlate.latex`（兼容 shim：`parse_file/parse_tex/reconstruct/flatten_inputs/ScanResult.chunks/.ph_map/.pieces` 同签名）。
- 语料 `bench/corpus/`（gitignored 子目录——CI 侧需缓存或降级为 fixtures-only 回归）+ `bench/fixtures/` 三件套，断言矩阵逐条照搬（T01–T29 + 209×3 + multi×4）。

### 11.3 验收指标（≥ spike 基线）

| 指标                | 基线                  | 验收                                      |
| ------------------- | --------------------- | ----------------------------------------- |
| 解析成功            | 259/259               | ≥259/259，0 异常 0 超时（30s/文件）       |
| 陷阱断言            | 32/32                 | 32/32                                     |
| 泄漏                | 25/23427 (0.11%)      | **≤5 (≤0.03%)**，且 `\cite/\ref` 命中仍 0 |
| identity 重建       | 259/259               | 259/259                                   |
| 死占位符/孤儿 chunk | 0/0                   | 0/0                                       |
| 性能                | 中位 1.3ms，max 253ms | 中位 ≤5ms，max ≤500ms                     |

## 12. 搬迁清单：可搬 / 必改 / 结构性弱点

### 12.1 直接搬（近逐字）

- `tables.py` ← `miniscanner.py:30-390` 全部常量表（含 `MATH_ENVS|=star`、`discard` 终值）。
- `_ws`(:456)、`_match_brace`(:462)、`_match_bracket`(:485)、`_read_cmd_name`(:589)、`_env_name_at`(:544)。
- `flatten_inputs`(:1354-1454) 逻辑原样（注释/verbatim 感知、file_dir→root_dir 双查找）。
- `flush_run` 阈值/空白切分/force_chunk 逻辑（:834-857）。
- `_body_has_text`/`_protected_param_positions`（:622-647）。
- `parse_tex` 的 preamble 判定（:1316-1325）。

### 12.2 搬但必改

| 组件                                 | 改动                                                                      |
| ------------------------------------ | ------------------------------------------------------------------------- |
| `_args`(:512)                        | argspec 驱动 + `allow_single_token` 旗标；返回 `ArgSpan`                  |
| `_find_env_end`(:552)                | env 名 `rstrip('*')` 归一                                                 |
| `_scan_macro_def`(:649)              | +`\DeclareMathOperator`/`\gdef` 系 + argspec + `def_site` + `envs` 显式表 |
| `_dispatch_cmd`(:939)                | in_arg 分支（注释/边界/条件/未知 env/input/end）；`\lstinline` 定界符化   |
| `_protect_call`(:1138)               | 不变逻辑，但所有 `_ph` 调用改走 `_ph_into_run`（debt 记账）               |
| `_handle_chunk_arg`(:1167)           | `CHUNK_ARG_SPEC` 查表；spawn(in_arg=True, base=cs)                        |
| `_env_with_mined`(:1295)             | spawn(mode=MINED_ONLY, in_arg=False, base=j)；env_stack 播种              |
| `scan` 主循环 (:819)                 | `$` 分支接 debt repair；piece 发射带 span/env                             |
| `reconstruct`(:1328)                 | 递归 memo 展开（§10）+ validate                                           |
| `Scanner.__init__/_spawn`(:425/1305) | `ScanState` 容器化；`_ctr` list-hack 废止                                 |

### 12.3 必重写

- pieces 模型：二元组 → `Piece(kind, span, text, env)`（docs/02 既定 byte_range 契约）。
- `ScanResult`/`Chunk`：+span/env/placeholders/warnings 字段。
- `Macro`→`MacroEntry`：`nargs/has_opt` → `spec: list[ArgSpec]`。
- `MacroTable`：`env:` 前缀键 → `cmds`/`envs` 双表。

### 12.4 结构性弱点清单（重写必须处理或显式留档）

- **W1 `miniscanner.py:537`**：单 token 参数兜底吞任意字符 → 泄漏 A 根因。**已修（§5.3）**。
- **W2 `:553-587`**：env 名精确匹配不容 `*` 笔误 → 泄漏 C1。**已修（§3.5）**。
- **W3 `:863-867`**：arg 内注释字面落 chunk → 泄漏 B。**已修（§3.4）**。
- **W4 `:1085-1088`**：arg 内条件命令字面落 chunk → 泄漏 D。**已修（§3.2-15）**。
- **W5 `:1280-1293`**：arg 内未知 env 透明 → begin/end 字面落 chunk → 泄漏 C2。**已修（§3.5-4）**。
- **W6 `:677` `env:` 注册无读者**：`\newenvironment` 登记是死代码。重写接入 `_handle_env` 查 `envs` 表（§3.5-4）。
- **W7 `:1305-1311` `_spawn` 手工拷字段**：新增可变状态极易漏拷 → `ScanState` 容器化。
- **W8 `:518` 匿名四元组 `(cs,ce,fs,fe)`**：可读性差 → `ArgSpan`。
- **W9 `:950` `\verb` 定界符 find 无 EOL 上限**：跨行误吞 → 限 `eol`。
- **W10 `:1138-1165` `_protect_call` 不识别 `\lstinline|…|`**：定界形漏保护 → 走 verb 通道。
- **W11 `:1322` `re.search(r"\\begin\{document\}")`**：注释内/`\begin {document}`（空格）误判 → 改走 tokenize 顺手记录（或保留正则 + 留档，低频）。
- **W12 `:1434` `_seen` 环检测同时拦合法重复包含**：`\input` 两次在 TeX 语义下应展开两次；现行为跳过第二次（内容保留字面，identity 不破坏，但漏译一次）。留档为已知偏差，不打算修（防环优先级更高）。
- **W13 `CHUNK_ARG_NAMES` 无参数形状**：`\captionof{type}{text}` 误取 `{type}` → `CHUNK_ARG_SPEC`（§5.4）。
- **W14 `$` 配对 O(n²)**（`:887-905`）：44 万字符 253ms 可接受；如需优化，预计算未转义 `$` 位置表。留档。
- **W15 `_env_kind_of`(:787) `"caption" in body` 启发式粗糙**：维持现状，注释标注。
- **W16 译文占位符合法性**：translator 丢/改 `[[X_n]]` → 孤儿/死 token。reconstruct 提供 `validate_translation` hook（§10），接线属 translate 层。

## 附：排查记录（修复依据实证）

- `\num{53807} $(2.57\%)$` → `[[CMD_121]]='\num{53807} $(2.5'`（单 token 吃 `$`+`(`+`2`+`.`+`5` 共 5 参）——2201.05989 实测 ph_map。
- `\lrinhypersequent{}\n$\mHyperA_0…` → `[[CMD_1553]]='\lrinhypersequent{}\n$\mHy'`——2602.19229 实测。
- `\begin{multline*}…\end{multline}` 原文笔误——2501.14787/Pset1sol.tex 实测（`multline*` 开、`multline` 闭）。
- `\ifAnonymous{a}{b}` 为 `\newif` 自定义旗标的双参用法——2609.08578 实测。
- caption 内 `%% 注释行` 含 `$*$`/`$\dagger$`/`$Y_1$`——1906.08237/2003.08934/1507.02284 实测。
- 引用：`bench/py/miniscanner.py`（行号散见全文）、`bench/results/miniscanner-report.md` §4/§6、`bench/results/macro-stats.md` §1/§10、`bench/py/miniscanner_test.py:55-62`（LEAK_PATTERNS 口径）、`docs/02-architecture.md:14-41`、`:90-101`。
