# 宏展开层设计 — 扫描中即时展开（mouth/gullet/segmenter 三段流）

> **结论**：宏展开按 TeX 自身三段式移植 plasTeX 3.1 的 mouth→gullet 形态——回压式不动点展开、展开产物只做分类不做物化、`\if` 两档处理；该设计已落地为现行唯一解析路径。
> **状态**：现行（已落地为 `latex/mouth.py` + `latex/gullet/` + `latex/segmenter/`；规范细节见 `spec/latex-pipeline.md`）
> **日期**：2026-09-15

## 1. 为什么需要展开层

字节扫描器（v1）的根本极限是「先定义后使用」假设：语料实测 268 个宏定义出现在 `\begin{document}` 之后（51% 论文在正文内 `\def`）、宏体可藏可译文本（49% 的宏体带自然语言）、`\input` 可由宏产出、`#{` 定界参数存在。这些形态只有「tokenize 与展开分离、展开器回压到同一流」能同时满足——这正是 TeX 的 mouth/gullet/stomach 结构。texlate 借用前两段，用分段器替代 stomach：

```
文件字节流 → Mouth（每输入文件一个，栈式：字符→token，注释整行吞掉不产 token）
          → Gullet（全局一个：拉原始 token，命中宏/原语→读参代入→推回流前端）
          → Segmenter（只见展开后 token，产出 pieces/chunks/placeholders）
```

与参考实现 plasTeX[^plastex] 的关键差异：plasTeX 的展开产物是 DOM 节点，texlate 的产物是**带源位置的 token**——最终目标是区间 splice，不是渲染。这决定了全文的核心策略：**展开是分类器/识别器，不是文本物化器**。

## 2. 展开产物的 pos 规则（硬约束）

展开产生的 token 没有源字节位置。规则：宏体 token 的 `pos` 记定义体区间 `(file_id, def_body_offset)` 并打 `gen>0` 标；分段器对 `gen>0` token 一律不以其 pos 做 splice，只用于类型判定（数学环境？cite？文本？）。调用点 splice 永远用**调用 token 自己的位置**——`\be…\ee` 保护段包的是 `\be` 到 `\ee` 的原始字节，不是展开文本。降级输出同样永远是「原文某连续区间」，保证 splice 后字节级 identity。

## 3. Token 与 Mouth

`Tok{kind, text, pos, gen}`：kind 为归并类别（`cs/lbrace/rbrace/mathshift/param/space/eol_par/letter/other/active`）；`\n\n` 与 `\par` 归一为 `eol_par` 段落边界 token，相邻去重；active 字符（`~`）单独派发。不设全量 catcode 字段——需要的只有结构与参数相关类别。

Mouth 行为对齐 plasTeX tokenizer：回压缓冲（`tokbuf`）先空先出、空白按 N/M/S 三态折叠、注释整行吞掉不产 token（这直接保证 `% \input{x}` 与 `% \newcommand…` 天然不触发——注释在 Mouth 层终结）、cs 名后随空白吸收、`@` 的 catcode 即查即用（§7）。`^^X` 序列语料≈0 留接口未实现。

## 4. Gullet：回压式展开

原始流 `read()` 弹输入栈顶 Mouth，栈空即尽；`unread()` 压回当前 Mouth 的 tokbuf 前端。展开主循环 `next_expanded()`：非 cs 或非可展开名 → 直交分段器；命中可展开集 → `expand()` 产 token 序列 → `unread` 推回前端，继续循环（不动点）。读参一律走 `read()`——**参数读的是未展开 token**（`\foo\bar` 把 `\bar` 原样作参），与 plasTeX 一致。

可展开集 = 宏表 ∪ 原语子集（下列为概览，规范枚举以 `gullet/names.py::_PRIMS` 与 `spec/latex-pipeline.md` §4.5 为准）：定义族（`def/edef/gdef/xdef/let/newcommand/renewcommand/providecommand/DeclareRobustCommand/newenvironment/renewenvironment/DeclareMathOperator/NewDocumentCommand 系/newtheorem/newif`）+ `long/outer/global/protected` 前缀链、作用域原语 `begingroup/endgroup/bgroup/egroup`、`\input` 族（`input/@input/include/InputIfFileExists/subfile/import/subimport/includestandalone/CatchFileBetweenTags` + `endinput`）、`if` 族 + `else/or/fi`、`expandafter/csname/endcsname/noexpand`、`makeatletter/makeatother/catcode`、`ifundefined/@ifundefined/@ifxundefined`、`romannumeral/uppercase/lowercase/par`。LaTeX 内建命令（`\section \cite` 等）不展开，原样交分段器按 argspec 表处理。

### 4.1 三级防护（plasTeX 没有，必须补）

plasTeX 无任何展开限制——`\def\x{\x}` 死循环只能靠外部 alarm 兜底。texlate 三层：

| 层         | 机制                                                            | 触发后                                            |
| ---------- | --------------------------------------------------------------- | ------------------------------------------------- |
| token 代数 | 展开产物 `gen = 触发者 gen+1`；`gen >= 32`（`MAX_GEN`）不再展开 | 该 cs 按不透明宏调用保护输出（保字节）            |
| 全局步数   | 每次 `expand()` 计一步；超 100k/文档                            | 后续所有 cs 不再展开，记 `expansion_overflow`     |
| 输入栈     | `\input` 嵌套 >8 拒绝压栈                                       | 调用本身 literal 输出；循环引用另用绝对路径集去重 |

`MAX_GEN=32` 的取值依据：正常宏嵌套（`\be→\begin`、`\Figref→Figure~\ref`）≤4 代，32 是 8 倍余量。全程迭代实现，无 Python 栈风险。

### 4.2 展开失败降级

定义解析失败 → 不登记、定义区段 literal 原样发出、后续调用走未知命令路径；调用点参数不匹配（定界参数找不到 delimiter、流提前结束）→ 已读 token 全部回吐、调用整体 `[[MACRO_n]]`；gen/预算耗尽 → 同上；`\input` 文件不存在 → warning + 原样 literal；宏体畸形（未配对 `}`）→ 定义时不登记。原则：**任何降级都必须保证 splice 后字节级 identity**——与 plasTeX「参数不匹配时 log 后继续」刻意分歧，因为静默吞字节对 splice 模型更危险。

## 5. 六类定义 → 统一 argspec

定义点在 gullet 内消费并登记，统一编译为 `spec: list[Arg]` + `body: list[Tok]`（`#n` 为 Parameter token）。`Arg.kind ∈ {m, o, star, eq, delim, until_group}`：`m` 强制（`{..}` 或单 token）、`o` 可选带默认、`star` 字面 `*`、`eq` 可选 `=`（`\let\a=\b`）、`delim` 定界参数（读到定界 token 序列为止，定界被消费不入参）、`until_group` 对应 `#{` 尾随组（读到 `{` 回吐不消费）。

逐类要点：`\newcommand{\x}[2][a]` 的可选位计入 N（`#1` 可选 + `#2` 强制）——v1 按 `opt+N` 多读一个是 bug，已修；`\providecommand` 是 `setdefault`、`\renewcommand` 覆盖写；`\edef/\xdef` 体在登记时即时展开（`_expand_eager` 哨兵界标法：体+哨兵推回流、抽展开产物至哨兵止；体内 `\noexpand` 给下一 token 打单发 `xprotect`）；`\newtheorem` 登记 env 透明项 + caption 元数据；`\newif\iffoo` 登记三项（旗标 + `\footrue/\foofalse` setter）；`\let\a\b` 存当时的 MacroDef 快照引用（`\b` 后改不影响 `\a`）。xparse spec 实现 `m o O s t d D r R u g l` 子集，含 `v/b/e/E/x` 的定义整条降级不登记。

### 5.1 `\def` 参数文本编译（前移 plasTeX 调用点逻辑）

plasTeX 在每次调用时重走参数文本；texlate 把同一判定前移到定义时编译成 `spec`，调用点纯查表（语义等价）。参数文本 = `\def\name` 与 `{` 之间全部 token：`#`+数字 → 新参数槽；`#`+`{` → 前一槽改 `until_group`；非 `#` token 在有 pending 槽时累计为该槽 `delim` 序列、无 pending 时编译为 `literal_match`（调用点要求流中下一 token 相等，否则 `ArgMismatch` → 回吐降级）；结尾 pending → `m`。`\def\ra[#1 #2 #3]{…}` 编译为 `[literal_match('['), delim(空格), delim(空格), delim(']')]`。定义体/参数文本中的 `##` 按嵌套规则先折叠再编译。

## 6. 透明宏两子模式 — 解决「宏体藏文本 49%」

定义时一次性分类（调用点零分析）：`env_begin`/`env_end`（体 fullmatch `\begin{X}`/`\end{X}`）、`math`（体含数学特征无可译文本）、`opaque`（体去命令去参数后无 ≥2 连续字母）、`transparent`、`literal`。`protect_args` 位图标记出现在 `\ref/\cite/\label/\url` 参数位的 `#i` → 该实参整体保护。

transparent 分两个子模式：

- **transparent-inline**：可译文本全部经参数位进入（`\todo{...}`）→ 不物化展开，宏名 literal 吐给分段器、参数逐个内联扫，splice 保留 `\todo{译文}` 结构。
- **transparent-expand**：体自带可译文本（`\def\cmsMessage{Submitted to…}`）→ gullet 正常展开推回，分段器在展开 token 上常规分段；但 chunk 的 splice 目标登记为**调用点区间**，content 是展开文本的表面——译文回来时 `\cmsMessage` 整体被译文替换，定义本体原样保留。判据：body 去掉 `#i` 参数位后仍有可译文本。

混合体（参数位与体都有文本）取 expand——体文本是召回率大头。这条机制是 49% 宏体藏文本问题的兜底，不再需要「猜」。

## 7. `\if` 两档策略 — 与 plasTeX 全求值的刻意分歧

plasTeX 对每个 `\if*` 都求值，不可求值者硬编常量。对翻译而言求错值 = 丢一支文本，因此：

- **可求值档**（`\iftrue/\iffalse`、`\newif` 旗标、操作数全字面的 `\ifnum/\ifodd/\ifdim`、`\ifdefined/\ifcsname`、字面可比的 `\if/\ifcat/\ifx`、恒 False 的 `\ifmmode/\ifeof/\ifvoid/\ifhbox/\ifvbox/\ifinner`、按模式常量的 `\ifhmode/\ifvmode`）→ 读条件后收集分案例、只推回选中支，未选支 token 丢弃——其内 `\def` 不执行、文本不进 chunk，与 TeX 语义一致。
- **不可求值档**（带寄存器/内部量的 `\ifnum`、对宏的 `\ifx`、其余一切）→ 条件部分按各自语法读掉（避免 `\count0=1` 泄漏进 chunk），`\if/\else/\fi` 发为结构界标 literal piece，**两分支都进分段器**——召回优先，编译端 TeX 自决。

`process_if` 收集未展开 token 到 `\fi`、按 `\else/\or` 分案例；`if*` 前缀计数嵌套、`\newif` 特例保证 `\ifx\newif\ify` 序列不被误算嵌套；`\ifcase N` 取第 N 支。`\ifmmode` 取恒 False——数学区由分段器 raw 拉取成 `[[MATH]]` 占位，数学体内的 `\ifmmode` 永不抵达求值器（理由注释见 `gullet/cond.py`，行为由 `tests/test_latex_cond.py::test_ifmmode_false` 钉死）。

## 8. 作用域、`\makeatletter`、`\input`

- **scope 链**：`{`/`\bgroup`/`\begin{env}` 推帧、`}`/`\end` 弹帧；`\gdef/\xdef/\global` 写底帧，其余写顶帧——`\newcommand` 按 LaTeX 语义也算局部（其内部是 `\def`），与 plasTeX 一律 addGlobal 的简化分歧；局部泄漏的代价只是组外多认一个宏，无害。推弹由分段器驱动回调。
- **`\makeatletter`**：catcode 表为 Mouth/Gullet 共享可变结构，token 流过时翻转 `@` 的 letter/other 并原样吐给分段器。**必须拉取式 tokenize**——catcode 影响之后字符的归类，预 tokenize 全文再翻无效（这是「扫描前展平 + 预 tokenize」方案做不了 `\input` 之外的第二个理由）。语料 26% 论文出现 `\makeatletter`。
- **`\input`**：gullet 原语，invoke 时把新 Mouth 压输入栈，`\endinput` 提前弹栈——宏产出的 `\input` 也能展平；pos 记 `(file_id, offset)` 天然分文件。文件查找 = kpsewhich 简化版（先所在文件目录、再主目录、再 basename±`.tex`），无 TeX 安装也要工作。注释/verbatim 内的 `\input` 天然不触发。v1 的扫描前 `flatten_inputs` 退役，仅保留其查找顺序。

## 9. 验证：plasTeX oracle 对拍

屏蔽 `.sty/.cls`、只放行主目录 `.tex` 的 kpsewhich 打桩下，plasTeX 3.1 可解析真实语料并提取 DOM `par` 节点（TeX 段落单元）：1706.03762 主文件 0.2s 得 158 段、ATLAS 论文 0.9s 得 329 段；合成样例确认 `\be` 展开为 equation 节点、`\ifdraft` 按旗标选支、`\ifmmode` 取正确分支、`\def\Figref{Figure~\ref{#1}}` 调用点代入正确——oracle 展开语义与本设计一致。对拍方法：两侧文本流同函数规范化后 `SequenceMatcher` 比 recall/noise；注意 `par.textContent` 会把 `\citep{key1,key2}` 的参数泄成文本，规范化时把 `[[*_n]]` 替换为 `*` 哨兵而非删除，让 diff 报「缺失/多余哨兵」而非整段错位。

落地后的语料级验收数据见 `segmenter-integration.md`（identity/leak/条件处理前后对比）。

## 10. 明确不做

active chars 自定义、`\halign`、完整求值器（寄存器算术/盒尺）、`\write/\read/\openout`、xparse `v/b/e/E/x` 参数型、plasTeX 的 DOM/stomach 全部不移植。`\let` 的 Mouth 层解析、`\chardef` 语义同样跳过（与 plasTeX 口径一致）。注：本节成文后若干项已落地——`\catcode` 现为通用机制（任意字符/类别，仅 `\global\catcode` 写透缺）、`\uppercase/\lowercase` 与 `\romannumeral` 已实现、`\edef` 体预展开已落（§5）；e-TeX 面仅 `\unexpanded/\detokenize/\scantokens` 与 `\numexpr` 族算术仍缺——`\protected` 由前缀链消费、`\ifdefined/\ifcsname` 真求值、其余 e-TeX/pdfTeX/XeTeX `if*` 原语走界标档。

### 参考文献

[^plastex]: plasTeX contributors. plasTeX — A Python Framework for Processing LaTeX Documents (3.1). GitHub. [github.com/plastex/plastex](https://github.com/plastex/plastex)

设计移植参考 plasTeX 3.1 源码通读[^plastex]（tokenizer 三态机、`pushTokens` 回压、`processIfContent` 分案例、`Definition.invoke` 定界参数、`expandDef` 代入、Context 作用域）；oracle 实验现场结论已摘要进 §9。宏统计口径（正文内定义 51%、宏体藏文本 49%、`\makeatletter` 26%）出自语料普查，结论已摘要。
