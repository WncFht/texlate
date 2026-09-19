# 07 · LaTeX 管线规格：半解析 / 展开 / 分段 / 重建

> 最终技术方案 · `src/texlate/latex/` 模块全规格。
> 证据基础：`docs/research/latex/miniscanner-rewrite-spec.md`（9 文件重写规格）、`expansion-design.md`（Mouth/Gullet/Segmenter）、`expansion-timing.md`（单遍展开语料证据）、`bench/py/miniscanner.py`（spike 原型，259/259 + 32/32 + 0.11% 泄漏 + identity 100%；**已退役**，断言矩阵移植 `tests/test_bench_regression.py`，docs/10 §B2）。
> 实现按本文执行；研究文档只作证据出处。

## 0. 设计哲学与不变式

**区间替换模型**：不做 AST 全量重建。扫描器产出 `Piece(kind, span, text, env)` 流——`pieces` **无缝平铺 `[0, n)`** 是头号不变式；可译段抽成 `chunks[]`、保护段替换为 `[[TYPE_n]]` 占位符；译文回来按占位符 DAG 递归展开 splice 回原文。

五条铁律：

1. **单遍逐字符扫描，绝不回退、绝不抛异常**（259/259 零崩溃之源）。
2. **分支顺序即语义，不得调换**（§3.1/§3.2）。
3. **凡内容可含 `%` 的构造必须在 `%` 分支判定前被整段消费**（`\verb|\url|verbatim env` 在 `\` 分支内自足——根治 ieeA `\url{a%20b}` 截断 bug）。
4. **splice 永远用调用点/原文的字节区间**；展开产物（`gen>0`）只做分类器输入，永不进 splice。
5. **一切降级必须 splice-safe**：失败输出永远是"原文某连续区间"，不是展开文本。

## 1. 模块布局

```
src/texlate/latex/
  __init__.py        # 公共 API re-export
  tables.py          # 命令族常量表（纯数据，零逻辑；含 argspec.json 装载）
  model.py           # Span/Piece/PieceKind/PhType/Chunk/ArgSpan/MacroEntry/
                     #   MacroKind/ArgSpec/EnvEntry/ScanResult/ScanWarning
  placeholder.py     # PH_RX、CHUNK_RX、PlaceholderIssuer（共享计数器）
  macro_table.py     # 六类定义命令扫描 + MacroEntry 分类 + argspec 编译
  scanner.py         # Scanner 主循环 + dispatch_cmd + env/macro/arg handlers
                     #   + math-debt repair
  flatten.py         # \input/\include 展平（Mouth 栈；见 §7）
  reconstruct.py     # splice 重建 + DAG 递归展开 + validate
  api.py             # parse_tex / parse_file（preamble 判定、入口装配）
```

（勘误 2026-09-17：v2 落地后布局实为 13 件——另 `mouth.py`（字符→token 三态折叠）、`gullet.py`（回压式展开 + \input 展平原语）、`segmenter.py`（token 流→pieces/chunks/占位符）、`prose.py`（`file_has_prose` 散文闸——support 件判据，e2e/worker/builtins 三处消费）；v2 为默认产品路径，`TEXLATE_NO_EXPAND=1` 回退 v1。勘误同日：`TEXLATE_NO_EXPAND` 曾为非空即真直读（`=0`/`=false` 也触发回退），已收敛 `textutil.env_flag` 标准真值集（`textutil/__init__.py:env_flag`）。锚点更新 2026-09-18：`gullet.py`/`segmenter.py` 已拆包——`gullet/`（args/classify/cond/core/decls/defcmd/entries/expand/input/tables/tokutil 十一叶）、`segmenter/`（args/\_common/core/env/group/mainloop/pending/tables 八叶——tables 系 B6 单源化收编的 scanner↔segmenter 七常量表）。勘误 2026-09-19：v1 臂退役——`scanner.py` 删除、`TEXLATE_NO_EXPAND` 回退开关移除（v2 为唯一解析路径，`parse_tex`/`parse_file` 直走 `parse_tex_v2`）；`macro_table.py` 瘦身为共享 helper 叶（`parse_argspec`→segmenter/tables、`body_has_text`/`classify_body`/`protected_param_positions`→gullet/classify）；`MacroTable` 平表删除、`ScanState` 瘦至 8 字段。上文 v1 布局清单与 `scanner.py` 锚点仅作历史参照。）

依赖方向：`model/placeholder` 为纯数据层不反向依赖；`scanner` 只依赖 model/placeholder/macro_table/tables；`reconstruct` 只依赖 model/placeholder；`api`/`flatten` 是唯一可碰文件系统处。

## 2. 核心数据结构

全部 `@dataclass(slots=True)`；区间为半开 `[start,end)`、相对当前 scan 输入串；子扫描经 `base` 换算全局偏移。

```python
class PieceKind(Enum):  LITERAL | PROTECTED | CHUNK_REF

class Piece:
    kind: PieceKind
    span: Span            # pieces 无缝平铺 [0,n) —— 不变式
    text: str             # LITERAL=tex[span]；其余=占位符串
    env: str | None

class PhType(Enum):       # [[TYPE_n]] 全枚举
    MATH VERB ENV CITE REF LABEL URL GRAPHICS BIB CMD
    HREF MACRO KEY AUTHOR COMMENT COND ENVTAG
    # CHUNK 不在此列：[[CHUNK_n]] 走 chunks[] 不走 ph_map
    # （勘误 2026-09-17：impl 另含 EXPAND——展开组 identity 面，
    #  segmenter 体=调用点 vtex 切片，model.py:PhType.EXPAND）

class Chunk:
    id: int
    content: str          # 渲染形（可内嵌 [[TYPE_n]]）
    context: str          # "para" | "item" | chunk-arg 命令名（勘误 2026-09-17：
                          # impl 默认 `"para"`——`"paragraph"` 专指 \paragraph 节题语境）
    span: Span
    env: str | None
    placeholders: list[str]

class ArgSpan:
    content: Span         # 去括号内容区间
    full: Span            # 含括号整段（单 token 参数时 content==full）
    spec: ArgSpec | None

class MacroKind(Enum):
    ENV_BEGIN | ENV_END | OPAQUE | TRANSPARENT | LITERAL

class ArgSpec:            # xparse 参数签名项
    kind: str             # 'm'|'o'|'O'|'s'|'d'|'D'|'r'|'R'|'v'|'e'|'t'|'b'
    delim: str = ""
    default: str | None = None

class MacroEntry:
    name: str
    spec: list[ArgSpec]
    kind: MacroKind
    target_env: str = ""            # ENV_BEGIN/END 专用
    protect_args: tuple[bool,...] = ()   # TRANSPARENT：参数位→[[KEY]]
    body: str = ""
    def_site: int = -1

class EnvEntry:           # \newenvironment 登记
    name: str; nargs: int
    kind: str             # "protected" | "transparent"（启发式）

class ScanWarning:
    kind: str             # unclosed_env|unpaired_dollar|stray_end|
                          #   debt_repair|def_parse_fail
                          # （勘误 2026-09-17：impl 共 20 种——再加 letters_cut|
                          #   expansion_overflow|if_unterminated|missing_input|
                          #   gen_overflow|ph_collision|env_mismatch|argspec_shadowed|
                          #   dangling_chunk_ref|dangling_ph|dead_ph|keyarg_unbound|
                          #   orphan_chunk|pieces_gap|verb_resync_failed）
    pos: int; detail: str

class ScanResult:
    protected_tex: str
    chunks: list[Chunk]
    ph_map: dict[str,str]           # "[[TYPE_n]]" → 原文段（可内嵌占位符）
    macros: ScopeMacroTable         # scope 链（v1 平表经 export_flat_macros 转换收敛）
    pieces: list[Piece]
    inputs: list[tuple[int,str]]
    warnings: list[ScanWarning]
    # （勘误 2026-09-17：impl 另含 vtex: str——叙事序虚拟文本，
    #  pieces/chunk.span 的坐标系；v1 字节 scanner 下留空）
```

（勘误 2026-09-17：`ArgspecEntry`（model.py:ArgspecEntry）整类未记档——`data/argspec.json` 一行：CTAN 宏/环境包归属 + xparse `signature` + `arg_roles`（text/opt-text 可译，key/verbatim/skip 保护）+ `policy` 兜底（chunk-arg|transparent|key|verbatim|protect|boundary|literal；env 侧 `body_role`: text|verbatim|math|protect）+ `guessed`（族规则推断签名，可审计回滚）+ `also_in` 跨包重名登记。）

```python
PH_RX = re.compile(
    r"\[\[[A-Z_]+_\d+\]\]"
)  # 勘误 2026-09-17：无捕获组——findall 直接出整 token
CHUNK_RX = re.compile(r"\[\[CHUNK_(\d+)\]\]")


class PlaceholderIssuer:  # 单一单调计数器，跨子扫描器共享（编号冲突教训的扶正）
    def new(typ, body, ph_map) -> str: ...


class ScanState:  # 一切可变状态的共享容器（spawn 只共享这一个引用）
    issuer
    ph_map
    chunks
    macros
    inputs
    warnings
```

## 3. 扫描状态机

### 3.1 主循环分支顺序（`Scanner.scan`）

```
while i < n:
    c = tex[i]
    1. '\\' → name,j = read_cmd_name → dispatch_cmd()   # \verb/\url/verbatim env
                                                       #   的 % 永远到不了分支 2
    2. '%'  → flush_run + 注释处理（§3.4）              # 能到这里必是真注释
    3. '$'  → 数学配对（§3.3，含 math-debt repair）
    4. '\n' → 空行判定（\n + 空白* + \n）→ flush_run     # 段落边界
    5. 其余 → run.append(c)
flush_run()
```

### 3.2 `dispatch_cmd` 分派表（19 行，顺序原样；勘误 2026-09-17：impl 名 `_dispatch_cmd`，`scanner.py:_dispatch_cmd`）

| #   | 命中                                                                                                 | 顶层处理                                                            | in_arg 变体                      |
| --- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------- |
| 1   | `verb`/`verb*`（+`\lstinline` 定界形）                                                               | 按定界符吞（EOL 上限）→ `[[VERB]]` 进 run                           | 同左                             |
| 2   | `newcommand/renewcommand/providecommand/def/NewDocumentCommand*/DeclareMathOperator*/newenvironment` | flush+ 整段 LITERAL + 登记宏表                                      | 同左                             |
| 3   | `newif`                                                                                              | flush+LITERAL + 注册 `\Xtrue/\Xfalse` 为 LITERAL 宏                 | 同左                             |
| 4   | `begin`                                                                                              | `_handle_env`（§3.5）                                               | 同左但走 in_arg 规则             |
| 5   | `end`                                                                                                | flush+LITERAL；`\end{document}` → 本体 + 余下全文 LITERAL，扫描结束 | `[[ENVTAG]]` 进 run（不 flush）  |
| 6   | cite 族（`CITE_NAMES` ∨ `startswith("cite")`）                                                       | `[[CITE]]` 进 run                                                   | 同左                             |
| 7   | ref 族（`REF_NAMES` ∨ `endswith("ref")`，**排除 `href` 与 TRANSPARENT**）                            | `[[REF]]` 进 run                                                    | 同左                             |
| 8   | `PROTECT_NAMES`                                                                                      | 类型映射 `[[LABEL/URL/GRAPHICS/BIB/CMD]]`；`url/path` verbatim 括号 | 同左                             |
| 9   | `href`                                                                                               | 第一参 verbatim 括号 → `\href[[HREF]]{`，第二参继续扫               | 同左                             |
| 10  | `input/include`                                                                                      | flush+LITERAL + 记 `inputs[]`                                       | `[[CMD]]`（arg 内不展平）        |
| 11  | `CHUNK_ARG_NAMES`                                                                                    | `_handle_chunk_arg`（§3.6）                                         | 嵌套 chunk-arg 内联化            |
| 12  | `PROTECT_BLOCK_NAMES`                                                                                | flush+`[[AUTHOR]]` 独立 piece                                       | `[[AUTHOR]]` 进 run（不 flush）  |
| 13  | `TRANSPARENT_NAMES`                                                                                  | 命令名逐字进 run，参数随主流                                        | 同左                             |
| 14  | `BOUNDARY_NAMES`                                                                                     | flush+LITERAL；`item` 置 `force_chunk`                              | `_protect_call → [[CMD]]` 进 run |
| 15  | `COND_RX` / LITERAL 类宏                                                                             | flush+LITERAL                                                       | `[[COND]]` 进 run                |
| 16  | `\[ \( \] \)`                                                                                        | `\[`/`\(` 找配对 → `[[MATH]]`；`\]`/`\)` 逐字                       | 同左                             |
| 17  | `INLINE_LITERAL_CMDS`/`FONT_SWITCHES`/单字符（重音/非字母）                                          | 逐字进 run                                                          | 同左                             |
| 18  | 宏表命中                                                                                             | `_handle_macro`（§3.7）                                             | 同左                             |
| 19  | 未知命令                                                                                             | 有 `{`/`[` 参数 → `_protect_call → [[CMD]]`；否则逐字               | 同左                             |

### 3.3 数学配对 + math-debt repair

```
on '$':
    '$$' 前缀 → 找未转义 '$$'（区域内不含 \n\n）→ [[MATH]]；失败逐字一个 '$'
    否则      → 找下一未转义 '$'（\' 跳 2 字符；遇 \n\n 中止）→ [[MATH]]；
                失败逐字 '$' + warning(unpaired_dollar)

debt 机制：
    _ph_into_run(typ, body) 是一切占位符进 run 的唯一入口；
    body 内未转义 '$' 计数为奇 → math_debt.append(run 下标)
    on '$' 且 math_debt 非空 → 该 '$' 是占位符体内开出数学的闭合符：
        占位符串 + 其后字面 + '$' 合并为 [[MATH]]；pop 栈
    flush_run 时清空（跨段不追）
```

正确性：`[[CMD]]` 体含奇数 `$` ⇒ 原文中开启了未闭合数学，其后第一个 `$` 必为闭合符；合并后 identity 保持、泄漏归零。这使"保护段吞 `$`"从全局配对毒药降级为局部自愈合（修泄漏机制 A 的第二层）。

### 3.4 注释处理（in_arg 变体，修泄漏 B）

```
on '%'（能到这里即真注释）:
    注释段 = tex[i : 下一 '\n' 或 n]
    in_arg → run.append(issuer.new(COMMENT, 注释段))   # chunk 内只见占位符
    顶层   → flush_run; emit(LITERAL, 注释段)
    '\n' 本身不入注释，回流主循环
```

### 3.5 `_handle_env`（修泄漏 C：星号归一 + in_arg 未知 env）

```
env = {name}
1. VERBATIM_ENVS  → flush；字面 find '\end{env}'（无括号计数，与 TeX 一致）
                    → [[VERB]] 独立 piece；找不到 → \begin 行 LITERAL
2. MATH_ENVS      → find_env_end（同名计数+宏端点+注释安全+*归一）
                    命中 → [[MATH]] 进 run；未命中 → \begin 行 LITERAL + warning
3. PROTECTED_ENVS → find_env_end → flush + _env_with_mined → [[ENV]] 独立 piece；
                    未命中 → LITERAL+warning
4. 其余（透明容器/未知）:
     顶层   → env_stack.push；吞 ENV_MANDATORY_ARG {arg}；
              [opt] 按 _env_opt_is_format 分流：版式参照吞，
              标题正文（theorem/proof 类）放行随正文进 chunk（F6）；
              \begin 行(含参数) LITERAL
     in_arg → ARG_TRANSPARENT_ENVS（itemize/enumerate/description/center/
              flush*/quote/abstract/minipage 等纯容器）→ \begin 行 → [[ENVTAG]]
              进 run + env_stack.push；
              否则（未知/结构环境）→ find_env_end → [[ENV]] 进 run（不 flush）
     env ∈ macro_table.envs → 按 EnvEntry.kind 选路
```

`_find_env_end`：**两侧 `rstrip('*')` 归一比较**（`\begin{multline*}…\end{multline}` 笔误场景）；未命中返回 None 时调用方一律 LITERAL 化 `\begin` 行（绝不允许 `run.append` 把 begin 行落进 chunk）。

### 3.6 `_handle_chunk_arg`（参数挖 chunk）

```
1. 吞 '*' → [opt]（CHUNK_ARG_SPEC[name] = (argspec 串, 可译参数下标)；
   未登记默认 "[opt]?{arg}"，\captionof 特例 ("mom", 2)）
2. 可译参数 {arg} → 括号匹配取 inner；空 → 整段进 run
3. sub = spawn(mode=MINED_ONLY, in_arg=True, base=参数偏移)
   rendered = sub.scan(inner).protected_tex   # in_arg 规则全生效
4. 父在 arg 内 → run.append(前缀+rendered+'}')        # 嵌套内联
   否则 → flush；emit(前缀 LITERAL)；pieces += CHUNK_REF；emit('}')
```

不变式：`\caption{` / `[[CHUNK_n]]` / `}` 三段各自独立 piece。

### 3.7 `_handle_macro`（宏表命中）

```
ENV_BEGIN   → find_env_end(target_env) → 按 §3.5 env 分类走
ENV_END     → 逐字进 run（裸 \ee 容错）
OPAQUE      → _args(spec) → [[MACRO]] 进 run
TRANSPARENT → _args(spec)；protect_args 位 → [[KEY]]；文本位 →
              spawn(in_arg=True).scan → rendered 进 run；
              括号/参数间空白逐字进 run（identity）
LITERAL     → 已在分派 15 拦下
```

### 3.8 `flush_run`（分块规则）

```
s = ''.join(run)
全空白 → emit LITERAL
mode == MINED_ONLY → emit LITERAL
clean = s 去占位符 → 去 \命令 → 去非字母；|clean|<20 且无 force_chunk → LITERAL
否则：lead/trail 空白 LITERAL；core → CHUNK_REF（context="paragraph"|"item"）
```

`force_chunk`（`\item` 后置位）消费一次即复位。

**分段器硬要求（锚点实证）**：`\input/\include/\label/\bibitem` 必须留占位符侧、绝不进可译 chunk——连续 `\input` 行被当单 chunk 吞掉会连锅端掉 named-destination 锚点与正文（1502.01589 实测 258 锚连锅端）。

**原子 chunk 上限**：超大单 chunk（实测 `\version{}{…}` 内联 109K 字符、ATLAS 作者块 77K）必须超阈值二次切分/宏参数内联上限——不切会爆单请求上下文。

## 4. Scanner 对象模型

```python
class Scanner:
    def __init__(self, state: ScanState, *, mode=NORMAL,
                 in_arg=False, force_chunk=False, base=0):
        self.state = state        # issuer/ph_map/chunks/macros/inputs/warnings
        self.pieces: list[Piece]  # 本扫描器的 piece 流
        self.env_stack: list[str]
        self.math_debt: list[int]

    def spawn(self, *, mode=None, in_arg=None, base=0) -> Scanner:
        # 共享 self.state；env_stack 拷贝；其余按参数覆盖
```

顶层 `scan` 返回时 pieces 必须满足平铺不变式（`p0.start==0`、末 `end==n`、无缝）——单元测试断言。

## 5. 宏表：六类定义 → argspec 编译

| 定义命令                                    | 语法                                 | 登记                                                                       |
| ------------------------------------------- | ------------------------------------ | -------------------------------------------------------------------------- |
| `\newcommand/\renewcommand/\providecommand` | `*? {\cmd}\|\cmd [n]? [def]? {body}` | `spec=[m]*n + 前导 'o'(有 def)`；分类 §5.1                                 |
| `\def`（`\gdef/\edef/\xdef` 同语法）        | `\cmd #1#2… {body}`                  | `spec=[m]*#计数`；delimited 参数记 warning(def_parse_fail) 不登记          |
| `\DeclareMathOperator`                      | `*? {\n} {text}`                     | `spec=[]`、kind=OPAQUE（数学算子不译）                                     |
| `\newenvironment/\renewenvironment`         | `{env} [n]? {begin} {end}`           | `envs[env]=EnvEntry(nargs, kind)`；kind 启发=体含 caption/figure→protected |
| `\NewDocumentCommand` 系                    | `{\cmd}\|\cmd {argspec} {body}`      | `spec=parse_argspec(签名串)`                                               |
| `\newif`                                    | `\ifX`                               | `cmds[Xtrue]=cmds[Xfalse]=LITERAL`                                         |

副表（P2 hook）：`\let` 别名（快照引用）；`\newtheorem`（`envs[thm]=transparent` + 标题可登记待译）。

### 5.1 三分类判定（登记时一次完成，调用点零分析）

```
body.strip() fullmatch '\begin{X}' → ENV_BEGIN(X)
           fullmatch '\end{X}'   → ENV_END(X)
body 无自然文本（去命令/参数后无 ≥2 连续字母）→ OPAQUE
否则 → TRANSPARENT + protect_args = 参数位出现在 \ref/\cite/\label/\url 位 → 该位 [[KEY]]
```

### 5.2 `parse_argspec(spec_str) -> list[ArgSpec]`

逐字符：`m` 强制 `{}`；`o` 可选 `[]`；`O{def}` 带默认；`s` 星号；`d<>/D<>` 定界可选/带默认；`r<>/R<>` 定界强制；`v` 逐字；`e{}/t<>` 修饰/测试（跳过语义）；`b` 环境体（仅 `\NewDocumentEnvironment`）；空白/未知 → skip+warning。

### 5.3 `_args` 签名

```python
_args(tex, i, spec: list[ArgSpec] | int, has_opt=False, *,
      allow_single_token=True) -> tuple[list[ArgSpan], int]
```

`spec` 为 int 等价 `[m]*n`（classic 宏路径）。**`allow_single_token=False` 唯一调用点 = 未知命令保护（分派 19）**——修泄漏机制 A 的第一层（spike 单 token 兜底会吞 `$` 及后续任意字符 → 全局 `$` 配对错位；单 token 参数只保留给已注册宏，那才是 TeX 正确语义）。

**单 token 参数不跨 `\`**（E10 BUG1 补丁，全语料 3452 处切断、1053 在可译 chunk 内、identity 检查盲）：`_args` 的单 token 兜底读到 `\` 必须停止——否则 `\begi|n{abstract}` 式切断。

## 6. 占位符方案

- 格式 `[[TYPE_n]]`；`n` 由单一 `PlaceholderIssuer` 全局单调递增（跨子扫描共享）。
- 两个命名空间：`[[CHUNK_n]]`（可译，`chunks[]` 索引）与 `[[TYPE_n]]`（保护，`ph_map`）——同语法不同表，reconstruct 统一展开。
- 嵌套：chunk.content 可含保护 ph；`[[ENV_n]]` 体可含 `[[CHUNK_k]]`+保护 ph；`[[MATH_n]]`（debt 产物）体可含 `[[CMD_k]]`；`COMMENT/COND/ENVTAG` 只出现在 chunk 内部（in_arg 产物）。深度不限；展开按 DAG（构造上无环，assert 兜底）。
- 碰撞：`[[` 字面在 LaTeX 源概率≈0（259 篇语料 0 碰撞），emit 留 assert。

## 7. 展平（`\input/\include` → Mouth 栈）

**时机：扫描中展平**（gullet 原语），不做扫描前 flatten——宏产出的 `\input` 也能展平；`pos=(file_id, offset)` 天然分文件。

- 触发面：`\input/\include/\InputIfFileExists/\subfile/\import/\subimport/\includestandalone/\CatchFileBetweenTags` + **裸文件名形 `\input file`**（读 `[A-Za-z0-9._/-]+` 至空白/反斜杠）。
- 查找序：including 文件目录 → 项目根 → basename 补 `.tex` → 裸名（勘误 2026-09-17：impl 实为**五级**——including 目录 → 项目根 → **paper top_dir** → basename 补 `.tex` → 裸名，`flatten.py:_resolve`/`gullet/input.py:_resolve_input`；且与 docs/06 §2.4 的 locate 建图序是**两套**——locate `_bases` 用 编译 CWD(主文件目录) → 项目根 → including 目录，`locate.py:_bases`。同一 `\input` 在 locate 建图与 gullet 展开两阶段可能解析到不同文件——分歧记档，以 gullet 序为展开语义权威）。注释内 `\input` 在 Mouth 层吞掉天然不触发；verbatim env 内不触发。
- `\subfile{}` 必须展开且 `\end{document}` **只在顶层截停**（子文件自带 document 壳时——2609.06443 实测 335 chunks 被截成 7 的 bug）。
- 防护：`MAX_INPUTS=8` 深度 + `_seen` 绝对路径集断环（留档偏差：合法重复包含被跳过一次，防环优先）。
- `\includeonly` 忽略（全部包含）。

## 8. 展开层（Mouth / Gullet / Segmenter）

TeX 三段式借用前两段：Mouth（字符→token）→ Gullet（回压式展开，宏展开唯一发生地）→ Segmenter（消费展开后 token 流，产出 pieces/chunks/占位符）。参考实现 plasTeX 3.1（移植位逐条对 `docs/research/latex/expansion-design.md` §12 表）。

### 8.1 Tok 与 Mouth

```python
class Tok:
    kind: str  # cs|lbrace|rbrace|mathshift|param|space|eol_par|letter|other|active
    text: str  # cs→名字 (不含\)，其余→字符本体
    pos: tuple  # (file_id, offset)；展开产物 = 定义体区间 + gen>0
    gen: int = 0  # 展开代数：源 token=0，宏展开产物=触发者 gen+1
```

Mouth 行为（逐条对应 plasTeX Tokenizer）：回压缓冲 `tokbuf` 先空先出、`push_tokens` 逆序塞左端；三态 N/M/S 空白折叠；N 态 `\n`→`eol_par`（`\par` 归一）；**注释整行吞掉不产 token**（`\input`/`% \newcommand` 被注释即消失的保证）；`\`+字母串→cs、`\`+非字母→单字符 cs、cs 后随空白吸收；catcode 表 `cats` 共享可变（`\makeatletter` 翻 `@`——**必须拉取式 tokenize**，预 tokenize 无效；语料实测 14 区 median ~150 字符无害）。

**pos 规则**：宏体 token pos = 定义体区间 + `gen>0`；分段器对 `gen>0` token **不以其 pos 做 splice**，只做类型判定；调用点 splice 一律用调用 token 的 pos（`\be…\ee` 保护时 `[[MATH_n]]` 包的是 `\be` 到 `\ee` 原始字节）。**宏展开是分类器/识别器，不是文本物化器**——与 plasTeX 的本质分歧。

### 8.2 Gullet：回压式不动点展开

```python
class Gullet:
    inputs: list[Mouth]  # 输入栈；read() 拉栈顶、耗尽弹栈
    macros: ScopeMacroTable  # scope 链（§8.5）
    ifflags: dict[str, bool]  # \newif 旗标
    math_depth: int  # $/\(/\[/math env 计数 → \ifmmode 求值（勘误 2026-09-17：
    # impl 无此字段——`\ifmmode` 恒 False，gullet/cond.py:_eval_if；
    # 数学区由分段器 raw 拉取成 [[MATH]]，其内 \ifmmode 不经求值）
    steps: int = 0
    BUDGET = 100_000  # 每文档展开步数上限
    MAX_GEN = 32  # token 代数上限（正常宏嵌套 ≤4 代，8 倍余量）
    MAX_INPUTS = 8
```

`next_expanded()`：拉原始 token → 非 cs/非 expandable 直交分段器 → 命中宏表/原语则按 argspec 读参（**读参读未展开 token**）→ 代入 → `unread` 推回前端 → 继续循环（不动点，不 return）。`\if` 选路分支只推回选中支——被 `\iffalse` 跳过的 `\def` 永不执行（结构化 `\if` 正确的唯一途径）。副作用命令（`\makeatletter`）也在流内，顺序语义天然正确。

expandables = 宏表 ∪ 原语集 `{def,edef,gdef,xdef,let,newcommand*,newenvironment*,newtheorem,DeclareMathOperator,NewDocumentCommand*,newif,input,endinput,include,if族,else,fi,expandafter,csname,endcsname,noexpand,long,outer,makeatletter,makeatother,catcode,ifundefined}`。**LaTeX 内建命令（`\section \cite`…）不展开**，原样交分段器按 argspec 表处理。

**语料依据（expansion-timing 实测，44 主文档）**：正文级 use-before-def = **0 例**（1351 正常序；14 处前置全在 preamble 且落在整调用保护内，损失≈0）→ **单遍即时展开成立**，UBD 命中→未知命令保护 + 日志（新语料回归警报）；重定义 3 事件 → 单遍"覆盖即新义"才是 TeX 语义（二遍 last-wins 反而错）；依赖链最深 4、迭代 ≤5 收敛；69% 定义从不调用。

### 8.3 限制与降级（必须 splice-safe）

| 层         | 机制                                      | 触发后                                        |
| ---------- | ----------------------------------------- | --------------------------------------------- |
| token 代数 | 展开产物 gen = 触发者 gen+1；>32 不再展开 | 该 cs 按不透明宏 `[[MACRO_n]]` 输出（保字节） |
| 全局步数   | steps>BUDGET(100k)                        | 后续 cs 不再展开；记 `expansion_overflow`     |
| 输入栈     | inputs>8 时 `\input` 拒压栈               | `\input` 调用 literal 输出                    |

| 失败                   | 处理                                                                           |
| ---------------------- | ------------------------------------------------------------------------------ |
| 定义语法解析失败       | 不登记；定义区段 literal；后续调用走未知命令路径                               |
| 调用点参数不匹配       | **回吐**：已读 token 全部 unread，`\name` 本体 `[[MACRO_n]]`；字节一个都不能丢 |
| 参数读满前流尽         | 同上回吐                                                                       |
| gen/BUDGET 超限        | `\name`+已读参整体 `[[MACRO_n]]`                                               |
| `\input` 文件不存在    | warning + literal                                                              |
| 宏体畸形（未配对 `}`） | 不登记                                                                         |

### 8.4 `\def` 定界参数（定义时预编译 spec）

参数文本 = `\def\name` 与首个 `{` 之间的全部 token。编译规则：

```
'#' 后 '1'..'9' → 新参数槽 pending
'#' 后 '#'      → 跳过（## 序列，嵌套定义先折叠）
'#' 后 '{'      → 前一参数是 `#{` 型 → kind='until_group'
非 '#' 且 pending → pending.kind='delim', delim += [a]（多 token 定界序列）
非 '#' 且无 pending → 'literal_match' 槽（调用点要求流中下一 token==a）
结尾仍 pending → kind='m'
```

调用点 `invoke_def`：literal_match 逐 token 相等比较（不等→ArgMismatch→回吐降级）；delim 读到定界序列止（**定界 token 消费但不入参**）；until_group 读到 lbrace 回吐不消费；尾随 undelimited 补读。参数 1 基。例：`\def\ra[#1 #2 #3]{…}` → `[literal_match('['), delim(' '), delim(' '), delim(']')]`。

### 8.5 作用域

```
ScopeMacroTable.scopes: list[dict]
'{'/\bgroup/\begin{env} 推；'}'/\end 弹（分段器驱动回报）
\def/\edef/\newcommand/\newenvironment/\let → 顶帧（local——LaTeX 语义，
    plasTeX 一律 global 是简化；局部泄漏代价≈无害）
\gdef/\xdef/\global → 底帧
```

保守退化：分段器没报的组（参数内组被整块读走）scope 不推——组内 `\def` 泄漏到外层可接受（over-expansion ≪ miss）。

`\let`：存"当时的 MacroDef 引用"快照；目标为字符 token→literal 别名。

### 8.6 `\if` 族两档策略（与 plasTeX 全求值的刻意分歧）

| 档位         | 条件族                                                                                                                                                                                                                                                                                                                           | 处理                                                                                                          |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **可求值**   | `\iftrue/\iffalse`；`\newif` 旗标；`\ifmmode`（math_depth——勘误 2026-09-17：impl 恒 False，gullet/cond.py:_eval_if，v2 不追踪数学深度实测未踩坑）；`\ifnum/\ifodd/\ifdim` 全字面量；`\ifdefined`；`\if/\ifcat`；`\ifx` 同 literal；`\ifcsname`；`\ifeof/\ifvoid/\ifhbox/\ifvbox/\ifinner`→恒 False；`\ifhmode/\ifvmode`→模式常量 | 读条件→`process_if(bool)`：case 收集只推回选中支（未选支 token 丢弃，其内 `\def` 不执行——TeX 语义一致）       |
| **不可求值** | 带寄存器/内部量、`\ifx` 对宏、其余一切                                                                                                                                                                                                                                                                                           | 条件部分按语法读掉；`\if/\else/\fi` 发结构界标 literal piece，**两分支都进分段器**——召回优先，编译端 TeX 自决 |

`process_if`：`read_stream` 收集未展开 token 到 `\fi`，`\else/\or` 分案例，`\newif` 对整对保留（`\ifx\newif\ify` 序列特例），任何 `if*` 计嵌套，收尾 `\fi` 不推回，`unread(选中支)`。`\ifcase N`→`which=N`。

判定前置：**先查宏表**——`\ifb` 是单位宏、`\ifAnonymous{T}{F}` 是双参宏（"非原语 `\if` 紧跟 `{` 即宏调用"），`\newif` 旗标名不入条件栈。语料实测：含 prose 块的 `\if` 仅 5 处（4 个 preamble 开关 + 1 个 `\iffalse` 死代码）。

### 8.7 `\makeatletter` 区

`cats` 为 Mouth/Gullet 共享可变结构；`\makeatletter/\makeatother` token 流过时翻转 `cats['@']` 并作为 literal token 交分段器（输出原样）。语料 26% 论文出现、多在序言；`\csname`/`\expandafter` 顺带实现。

## 9. splice 重建

```python
def reconstruct(res: ScanResult, translations: dict[int, str] | None) -> str:
    trans = {"[[CHUNK_k]]": v for k, v in (translations or {}).items()}
    memo = {}

    def expand(token):  # token 形如 [[X_n]]
        if token in memo:
            return memo[token]
        body = trans.get(token) or res.ph_map.get(token) or chunk_content(token)
        memo[token] = PH_RX.sub(lambda m: expand(m.group(0)), body)
        return memo[token]

    out = [p.text if p.kind is LITERAL else expand(p.text) for p in res.pieces]
    return "".join(out)
```

- **identity**：translations=None → 平铺 pieces + ph 体逐字 → 逐字节 = 原文。
- O(总规模)+memo，相对 spike `str.replace` 不动点语义等价（同一替换表迭代至不动点 ≡ DAG 递归展开）。
- **译文侧契约**：译文必须保留 chunk.placeholders 全列；`validate_translation(chunk, text)` 校验缺失/幻觉占位符（由 translate 层消费）。
- `validate_result(res)`：孤儿 chunk、死 ph、pieces 非平铺 → warnings，测试断言 0。
- `cjk_glue_fix`（`\cmd这是`→插空格）是 post-reconstruct 全局修正一步，放 splice 层。

## 10. 已知弱点与留档清单

| #   | 弱点                                                      | 状态                                           |
| --- | --------------------------------------------------------- | ---------------------------------------------- |
| W1  | `_args` 单 token 兜底吞任意字符（泄漏 A 根因）            | 已修（`allow_single_token=False` + 不跨 `\`）  |
| W2  | env 名精确匹配不容 `*` 笔误（泄漏 C1）                    | 已修（`rstrip('*')` 归一）                     |
| W3  | arg 内注释字面落 chunk（泄漏 B）                          | 已修（in_arg→`[[COMMENT]]`）                   |
| W4  | arg 内条件命令字面落 chunk（泄漏 D）                      | 已修（in_arg→`[[COND]]`）                      |
| W5  | arg 内未知 env 透明 begin/end 落 chunk（泄漏 C2）         | 已修（in_arg→`[[ENV]]`）                       |
| W6  | `\newenvironment` 登记死代码                              | 已修（`envs` 表接入 `_handle_env`）            |
| W7  | `_spawn` 手工拷字段易漏                                   | 已修（`ScanState` 容器化）                     |
| W9  | `\verb` 定界符 find 无 EOL 上限                           | 已修（限下一 `\n`）                            |
| W10 | `\lstinline\|…\|` 定界形漏保护                            | 已修（走 verb 通道）                           |
| W11 | `\begin{document}` 正则误判（注释内/`\begin {document}`） | 已修（mask_tex 视图 + `\s*` 变体，593da2d）    |
| W12 | `_seen` 环检测拦合法重复包含                              | 已修（祖先栈语义，5811f83）                    |
| W14 | `$` 配对 O(n²)（44 万字符 253ms）                         | 留档（可接受）                                 |
| W16 | 译文占位符合法性（丢/改 `[[X_n]]`）                       | `validate_translation` hook → translate 层接线 |
| —   | `\def` 定界参（15 例/7 文档）                             | v1 opaque 降级；v2 按 §8.4 编译                |
| —   | 零文本论文（`\includepdf` 包装纸，1412.6980）             | 0 chunks 属正常，走 stub 降级而非 bug          |
| —   | `\if` 求值陷阱（`\ifb` 单位宏/`\ifAnonymous` 双参宏）     | 已修（判定前置查宏表）                         |

scanner-audit（2026-09-15，`bench/results/scanner-audit-2026-09-15.md`）F 系列并入本表：

| #   | 弱点                                                          | 状态                                           |
| --- | ------------------------------------------------------------- | ---------------------------------------------- |
| F1  | `match_bracket` 递归深嵌套爆栈                                | 已修（迭代化）                                 |
| F2  | `\title[opt]{…}` 短题错位当真参                               | 已修（spec `om`,1）                            |
| F3  | `\newenvironment[n][d]` 第二 bracket 未读 → 登记丢 + 尾落文本 | 已修（双 bracket 循环）                        |
| F4  | 命令与参数间 `%` 注释断参                                     | 已修（`ws_skip_arg` 注释透明 + par 重入幂等）  |
| F5  | `$`/`$$` 闭合不跳注释                                         | 已修（对齐 `_find_math_close`）                |
| F6  | theorem 类环境 `[opt]` 标题被吃（8.3%）                       | 已修（`_env_opt_is_format` 内容分流，90f9f09） |
| F7  | `_split_core` 硬切腰斩 `[[X_n]]`                              | 已修（全 core PH_RX 扫描）                     |
| F8  | verbatim 裸 `find` 收尾（注释内 `\end`/`end {env}`）          | 误报（真实 TeX 即字面匹配），不改              |
| F9  | `` `\X `` 字符码读错（ord('\\') + 只吃 2 字符）               | 已修（消费 3 字符取 `ord(X)`）                 |
| F10 | `e`/`b` spec 静默跳过 → 参数位序错位                          | 已修（e 消费修饰段 + 全 kind 零宽占位保位序）  |
| F11 | `\url｜delim｜` 定界形漏保护                                  | 已修（`_protect_call` 定界符分支）             |
| F12 | 未闭合 env `_find_env_end` O(N·n) 性能悬崖                    | 已修（`_EnvDead` 墓标 + 盈余相等 bisect 直答） |

## 11. 验收门（M0 gate）

| 指标                          | spike 基线           | 验收门                                     |
| ----------------------------- | -------------------- | ------------------------------------------ |
| 解析成功                      | 259/259              | ≥259/259，0 异常 0 超时（30s/文件）        |
| 陷阱断言                      | 32/32                | 32/32                                      |
| 泄漏                          | 25/23427（0.11%）    | **≤5（≤0.03%）**，且 `\cite/\ref` 命中仍 0 |
| identity 重建                 | 259/259              | 259/259                                    |
| 死占位符/孤儿 chunk           | 0/0                  | 0/0                                        |
| ph 尾 `\letters`+后继字母切断 | —                    | 0（BUG1 回归断言）                         |
| 性能                          | 中位 1.3ms/max 253ms | 中位 ≤5ms，max ≤500ms                      |

测试面：`tests/latex/` 单元测试矩阵（match_brace/match_bracket/read_cmd_name/find_env_end 星号归一/_args/parse_argspec/math-debt/in_arg 四变体/宏分类/chunk 化/正文内 `\def`/flatten_inputs/reconstruct 三层嵌套）+ bench 回归（corpus39 陷阱集 + corpus_v2 混合集）。

## 12. v2 产品面切换落地记录（2026-09-16）

`parse_tex`/`parse_file` 产品入口切到 scan_v2（Gullet 展开流 → Segmenter 消费），v1 scanner 退役为 parsebench 对照臂。本节目的是留档切换面的语义决策与验收数字；细节实现见 gullet/segmenter docstring。

### 12.1 切换面（相对 S4 的语义决策）

| 面                                                   | 决策                                                                                                          | 动机                                                                           |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| env_begin/env_end 宏端点（`\beq`/`\eeq` 形）         | 不展开：`_EXPAND_KINDS` 只留 `transparent_expand`，raw cs 交 `_dispatch` 按 `m.target_env` 走 `_handle_env_*` | 展开产物的 def 位 gen>0 token 被组吸收成 `[[EXPAND]]`，env 配对丢失            |
| verbatim 宏端点（`\bv`…`\eev`）                      | token 级 `_find_env_end` 配对，`_emit_ph(VERB)`                                                               | 无 `\end{env}` 字面可 `find`                                                   |
| 组内 env 宏                                          | `_grp_env_macro` 经 `state.macros` 解析 → `[[MATH]]/[[VERB]]/[[ENV]]`/`[[ENVTAG]]`                            | 组内配对不进主流                                                               |
| in_arg/子扫宏解析                                    | `_resolve_macro` 回落 `self.state.macros`（v1 平表对应物）                                                    | `\section{$…$\beq…}` 内 `\beq` 恢复 `[[MATH]]`；opaque/IfSetter 同受益         |
| `_ListSource`                                        | `collections.deque`                                                                                           | `pop(0)` O(n) 是 2410.17998 超时根因（2.4M 出队 22s → popleft 4.4s）           |
| 零宽 `_cover_to`（回放/乱序 token）                  | `_ph` 空 body 不签发返 `""`，`_rappend_ph`/`_emit_ph` 跳过                                                    | 已覆盖字节再分派只产空 ph → dead_ph（`_slice_items` 零宽项归段规则的已知后果） |
| 动态文件名 input（`\input{\@journal\substyle@ext}`） | fname 含 `\` → 非输入尝试：gullet 不记 missing_input、segmenter 不记 inputs[]                                 | `\@ifx` 界标档扫双支后死支 `\input` 的幻影登记                                 |
| `e` spec / ArgMismatch                               | `_parse_xparse` e 支消费修饰段；`next_expanded`/`_expand_once` 尾参失配 unread+ 交 trig                       | xparse e 参位序、失配回压                                                      |

### 12.2 验收（corpus_v3 1955 文件，tag `v2prod-final`，697.7s）

| 门                               | 结果                                                                                                                 | 判定                                                                                                                                                |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| parse ok                         | 1955/1955，0 错误 0 超时                                                                                             | PASS                                                                                                                                                |
| identity strict（对 `res.vtex`） | **1955/1955 = 100%**                                                                                                 | PASS                                                                                                                                                |
| leak                             | 58/124772 = 0.046%（v1 对照臂 57/135170 = 0.042%）                                                                   | PASS                                                                                                                                                |
| unresolved_inputs                | **111**（≤111；动态文件名修复前 112）                                                                                | PASS                                                                                                                                                |
| dead_ph / orphan                 | 0 / 0                                                                                                                | PASS                                                                                                                                                |
| vtex_vs_src                      | strict 1906 / normalized 17 / diverged 32                                                                            | 信息项（展开足迹序差：input 内联位序 + 输入尾标保留差；不影响 identity）                                                                            |
| 性能                             | v2 p50 43ms / p95 428ms / max 8.4s（2403.15096）；>500ms 文件 85                                                     | **未达 max≤500ms**——v1 同语料亦未达（p50 7.1 / max 4.7s / >500ms 46 个）；v2 尾部约 1.8× v1；deque 修复已把最坏离群 2410.17998 从 30s 超时压到 4.5s |
| pytest / ruff                    | 1090 passed 16 skipped / 全净                                                                                        | PASS                                                                                                                                                |
| e2e_mock 冒烟                    | 管线三段干净（fault_chunks=0、leftover_ph=0、ctex 注入 ok）；编译 fail 全为环境性缺包（pstricks/revtex4），base 同挂 | PASS（环境受限）                                                                                                                                    |

warn_kinds 对照（v2 vs v1）：`stray_end` 63/33、`unclosed_env` 31/53、`def_parse_fail` 14/293、`missing_input` 149/159、`unpaired_dollar` 168/172、`if_unterminated` 2/1、`env_mismatch` 1/1；v2 独有 `gen_overflow` 1，v1 独有 `debt_repair` 13（math_debt 记账已并入主流退役）。`stray_end`/`unclosed_env` 增量主要来自 env 宏端点不对称配对（`\be{lbl}` 这类带 payload 的 begin 宏仍走展开，纯 `\ee` 端点弹栈 miss）——纯诊断面，字节覆盖不受影响。

### 12.3 遗留

- ~~`res.macros` 消费点未适配~~ **已收敛**：`ScanResult.macros` 单型 `ScopeMacroTable`（v1 平表经 `export_flat_macros` 转换）；臂内 `ScanState.macros` 保留 `MacroTable | ScopeMacroTable` union。（2026-09-19：`MacroTable` 随 v1 臂删除，`ScanState.macros` 单型 `ScopeMacroTable`。）
- ~~性能尾：85 文件 >500ms（最坏 2403.15096 8.4s）~~ **两波 perf 已落**（`0278602`/`55db9bc`，201 文件复测口径）：长尾总和 51476→26723ms（-48%）、>500ms 文件 20→11、identity 201/201 全等；`_collect_group`/env 体扫描残余 11 文件仍是已知热点。
- e2e_mock 编译侧 fail 均为环境性（缺 pstricks/revtex4 系统包），管线三段干净。
- `chunk` 数口径：v2 124772 vs v1 135170——v2 把含 ph 的 run 整段单 chunk（v1 会在 ph 边界再切），leak 持平证明可译覆盖等价，仅分块粒度不同。
