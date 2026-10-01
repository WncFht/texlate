# miniscanner 扶正重写实施规格 — `texlate.latex`

> **结论**：单遍字节扫描架构（pieces 平铺 + `[[TYPE_n]]` 占位符 + splice 重建）经 259/259 语料与 32/32 陷阱夹具证明可扶正；重写 = 结构化 + 修 4 类残留泄漏机制，非换架构。
> **状态**：已改判（→ `spec/latex-pipeline.md` + `segmenter-integration.md`）
> **日期**：2026-09-15
>
> **⚠️ SUPERSEDED 2026-09-20**：本文设计的字节扫描器（v1）曾按此规格落地为 `latex/scanner.py`，随后被 v2 记号流管线（`latex/mouth.py` + `latex/gullet/` + `latex/segmenter/`）整体取代，`scanner.py` 已从产品代码移除。pieces 平铺不变式、`[[TYPE_n]]`/`[[CHUNK_n]]` 占位符双命名空间、`Piece`/`Chunk`/`PhType` 数据模型与 splice 重建语义均被 v2 继承，仍属现行契约。现状唯一事实源 = `spec/latex-pipeline.md`；本文仅留设计动机、泄漏机制归因与验收口径作历史参考。

## 1. 问题与目标

输入是 bench 阶段的 1176 行 spike（单遍逐字符扫描 → pieces → 占位符模板 → 不动点重建），语料基线 259/259 解析成功、32/32 陷阱断言、identity 重建 100%，残留泄漏 25/23427 chunk（0.11%）。目标是按既定架构（`byte_range + kind` 段流 + 占位符 + splice）扶正为正式模块，并把 25 处泄漏修到 ≤3 处（~0.01%）。

关键判断：泄漏不是架构问题。25 处归为 4 个局部机制，修复全部落在分派规则与参数消费层，主循环骨架不变。

## 2. 架构决策

### 2.1 pieces 平铺不变式

`pieces` 是一组带 `src_span` 的段，无缝平铺 `[0, n)`：首段 `start==0`、末段 `end==n`、相邻无重叠无空洞。每段为三种之一——`LITERAL`（逐字段：注释/preamble/边界命令/环境 tag/宏定义/兜底）、`PROTECTED`（渲染形为 `[[TYPE_n]]`，本体在 `ph_map`）、`CHUNK_REF`（渲染形为 `[[CHUNK_n]]`，本体在 `chunks[]`）。块级结构（`\caption{`、`[[CHUNK_n]]`、`}`）必须各自独立 piece——这是 splice 可逐段写回的前提。

spike 的 `(kind, str)` 二元组升级为 `Piece(kind, span, text, env)`，`text` 是渲染形而非原文切片，原文经 `span` 回查。

### 2.2 占位符双命名空间

`[[CHUNK_n]]` 索引 `chunks[]`（可译单元），`[[TYPE_n]]` 索引 `ph_map`（保护本体）。两者共用 `[[…]]` 语法但不同表，reconstruct 统一展开。编号由单一 `PlaceholderIssuer` 单调递增、跨子扫描器共享——spike 用 list-hack 传计数器曾造成编号冲突，扶正为显式 issuer。

嵌套规则：chunk.content 可含任意保护 ph；`[[ENV_n]]` 体可含 `[[CHUNK_k]]`（保护环境内挖 caption）；debt-repair 产出的 `[[MATH_n]]` 体可含 `[[CMD_k]]`；in_arg 产物 `[[COMMENT_n]]`/`[[COND_n]]`/`[[ENVTAG_n]]` 只出现在 chunk 内部。嵌套构成 DAG（ph 体要么是原文切片、要么含更晚发出的占位符，构造上无环），深度不限，展开层递归解决。

### 2.3 共享可变状态容器化

一切可变状态（issuer、ph_map、chunks、macro 表、inputs、warnings）收敛进单个 `ScanState`；递归子扫描器经 `spawn` 共享同一 `state` 引用，`env_stack` 拷贝、其余按参数覆盖。这把 spike 的教训正式化——「递归子扫描的一切可变状态必须引用共享」，手工逐字段拷贝在新增状态时必漏。

### 2.4 主循环分支顺序即语义

逐字符单调递增、绝不回退、绝不抛异常。分支顺序固定：`\` 命令分派 → `%` 注释 → `$` 数学配对 → 空行分段 → 其余入 run。`\` 分支内部把 `\verb|..|`、`\url{..%..}`、verbatim 环境整段消费，使 `%` 判定永远看不到 verbatim 体内的 `%`——这是修 ieeA「注释剥离跑在 verbatim 识别前导致 `\url{a%20b}` 截断」的机制性不变式：**凡内容可含 `%` 的构造，必须在 `%` 分支判定之前被整段消费**。`\verb` 定界符搜索加下一换行上限（TeX 中 verb 不跨行），`\lstinline` 归入定界符通道以覆盖 `|…|` 形。

## 3. 命令分派

名称解析后按固定顺序分派 19 行（顺序即语义不得调换）：verb → 定义命令（登记宏表 + 整段 LITERAL）→ `newif`（注册 `\Xtrue/\Xfalse` 为 LITERAL 宏）→ `begin`/`end` → cite 族 → ref 族 → protect 名表（`[[LABEL/URL/GRAPHICS/BIB/CMD]]`）→ `href`（第一参 verbatim 括号 → `\href[[HREF]]{`，第二参继续扫）→ `input/include`（LITERAL + 记 `inputs[]`）→ chunk-arg 命令（参数挖 chunk）→ protect-block（`[[AUTHOR]]`）→ 透明命令（名逐字、参数随主流）→ 边界命令（LITERAL，`item` 置 `force_chunk`）→ 条件命令/LITERAL 宏 → `\[ \(` 数学 → 单字符/重音逐字 → 宏表命中 → 未知命令兜底。

`in_arg` 上下文（chunk-arg 参数子扫描）改变七行行为：注释发 `[[COMMENT]]`、`\end` 发 `[[ENVTAG]]`、`input` 发 `[[CMD]]`（arg 内不展平）、边界命令连参保护为 `[[CMD]]`、条件命令发 `[[COND]]`、未知环境整体 `[[ENV]]`、protect-block 不 flush 进 run。

cite/ref 用词族规则而非名单：`startswith("cite")` / `endswith("ref")` 覆盖 natbib 全族与未收录派生，显式排除 `href` 与 TRANSPARENT 宏。

## 4. 数学配对与 math-debt repair

`$`/`$$` 配对找未转义闭符、`$$` 域内不得含 `\n\n`；失败逐字落 `$` 并记 `unpaired_dollar` warning。

新增 debt 机制作为保护段误吞 `$` 的第二层兜底：一切占位符经 `_ph_into_run` 进 run 时，体内未转义 `$` 计数为奇则压 `math_debt` 栈（记 run 下标）；此后首个 `$` 判定为「占位符体内开出的数学的闭合符」，把栈位到该 `$` 的整段（占位符串 + 其间字面 + 闭合符）合并重发为 `[[MATH_n]]`。`flush_run` 时清空（跨段不追）。正确性依据：保护段体含奇数 `$` 意味着它在原文开启了未闭合数学，其后第一个 `$` 必为闭合符；合并后 identity 保持（内嵌 ph 由展开层还原）、泄漏归零。这把「保护段吞 `$`」从全局配对错位降级为局部自愈合。

## 5. 宏表与参数签名

六类定义命令登记宏表：`\newcommand/\renewcommand/\providecommand`（`spec=[m]*n` + 前导 `o`）、`\def/\gdef/\edef/\xdef`（连续 `#n` 计数；delimited 参数如 `\def\f(#1){}` 只数连续 `#n` 并记 `def_parse_fail`）、`\DeclareMathOperator`（语料 115 次/8 篇，OPAQUE）、`\newenvironment`（登记 `envs` 表，kind 启发式 = 体含 caption/figure → protected 否则 transparent）、`\NewDocumentCommand` 系（xparse argspec 逐字符解析）、`\newif`。

宏五分类在**登记时**一次判定：体 fullmatch `\begin{X}` → ENV_BEGIN；`\end{X}` → ENV_END；体无自然文本 → OPAQUE（整调用 `[[MACRO]]`）；否则 TRANSPARENT + `protect_args` 位图（`\figref→figure~\ref{#1}` 这类半文本半引用宏的关键：保护位发 `[[KEY]]`、文本位 in_arg 子扫描进 run）；`\newif` 产物为 LITERAL。

xparse argspec 覆盖 `m o O{def} s d<> D<> r<> R<> v e t b`；`_args` 按签名逐项消费，`spec=int` 等价 `[m]*n`。未知命令走 `spec=[m]*6, has_opt=True, allow_single_token=False` → `[[CMD]]` 整段保护——保守防 key 泄漏，代价是自定义文本宏（`\ours{方法名}`）不译，接受为已知边界。

`CHUNK_ARG_SPEC` 按名查 `(argspec, 可译参下标)`：`\captionof` 为 `("mom", 2)`（修掉误把 `{type}` 当可译参），`section/footnote/caption` 等为 `("om", 1)`，`title/thanks` 为 `("m", 0)`；未登记默认 `[opt]?{arg}`。

## 6. 25 处泄漏 → 4 机制修复映射

| 机制 | 现象                                                                                | 处数 | 修复                                                                                               |
| ---- | ----------------------------------------------------------------------------------- | ---- | -------------------------------------------------------------------------------------------------- |
| A    | `_args` 单 token 参数兜底让 `[[CMD]]` 吞掉 `$` 及后续字符 → 全局 `$` 配对错位       | 12   | 未知命令禁用单 token 参数（第一层）+ math-debt repair（第二层）                                    |
| B    | caption/footnote 参数内注释行（含 `$`）字面落进 chunk                               | 5    | in_arg 注释改发 `[[COMMENT_n]]`                                                                    |
| C1   | `\begin{multline*}…\end{multline}` 星号笔误 → `find_env_end` 失败 → `\begin` 落 run | 1    | env 名 `rstrip('*')` 归一匹配；未命中一律 `\begin` 行 LITERAL + warning                            |
| C2   | arg 内未知环境（如 lhs2TeX `code`）begin/end 字面落 chunk                           | 2    | in_arg 未知 env 走 `_env_with_mined` → `[[ENV_n]]`；`ARG_TRANSPARENT_ENVS` 纯白容器仍 `[[ENVTAG]]` |
| D    | `\ifAnonymous{a}{b}` 等条件命令在 arg 子扫描被当字面                                | 4    | in_arg 条件命令发 `[[COND_n]]`                                                                     |
| —    | 源文件自身未配对 `$`                                                                | 1    | 不可修，记 warning 豁免                                                                            |

实证锚点：`\num{53807} $(2.5` 被单 token 吞 5 字符、`$\mHy` 前缀被 `\lrinhypersequent{}\n` 后的单 token 吞、`%% 注释行` 含 `$*$`/`$\dagger$`/`$Y_1$` 等均为语料实测。目标泄漏 ≤3 处（~0.01%）。

## 7. splice 重建

按 pieces 顺序输出：LITERAL 落 `text`，其余递归展开占位符——译文表优先、`ph_map` 次之、CHUNK 落 `chunk.content` 原文；体内占位符经 `PH_RX.sub` 单遍替换 + memo，DAG 保证无环无须不动点轮次。相对 spike 的 `str.replace` 不动点，复杂度 O(轮×文本) → O(总规模)。`translations=None` 时逐字节还原原文（identity）。`validate_translation` 校验译文保留 `chunk.placeholders` 全列（缺失/幻觉占位符 → 报错回退原文，消费侧在 translate 层）。

## 8. 验收口径与实测

| 指标                | spike 基线            | 验收                                |
| ------------------- | --------------------- | ----------------------------------- |
| 解析成功            | 259/259               | ≥259/259，0 异常 0 超时（30s/文件） |
| 陷阱断言            | 32/32                 | 32/32                               |
| 泄漏                | 25/23427（0.11%）     | ≤5（≤0.03%），`\cite/\ref` 命中 0   |
| identity 重建       | 259/259               | 259/259                             |
| 死占位符/孤儿 chunk | 0/0                   | 0/0                                 |
| 性能                | 中位 1.3ms、max 253ms | 中位 ≤5ms、max ≤500ms               |

按此规格落地的 v1 通过了上述口径，但其字节级扫描与「先定义后使用」的假设在真实语料上暴露结构性极限（宏体藏文本、正文内 `\def`、展开时序），最终被 v2 记号流管线取代——演进过程见 `segmenter-integration.md`，现行模型见 `spec/latex-pipeline.md`。

## 9. 遗留弱点（留档）

- `\let\a\b` 别名（语料 15 例）与 `\newtheorem` 标题文本登记（148 例）只留 hook 未实现。
- `_seen` 环检测同时拦合法重复 `\input`（第二次跳过展开，identity 不破坏但漏译一次）——防环优先，留档为已知偏差。
- `$` 配对最坏 O(n²)（44 万字符 253ms 可接受）；`\begin{document}` 用正则判定（注释内/带空格形误判，低频留档）；env kind 的「体含 caption」启发式粗糙。
- 译文占位符合法性属 translate 层契约，本层只供校验函数。

### 参考文献

[^ieea]: zcyisiee. ieeA. GitHub. [github.com/zcyisiee/ieeA](https://github.com/zcyisiee/ieeA)

文中 `\url%` 截断缺陷的归因参照 ieeA 实现[^ieea]；spike 基线、泄漏逐条清单与宏统计出自开发机 bench 现场。plasTeX、unified-latex 等替代解析路线的取舍见 `spec/latex-pipeline.md` 与 `expansion-design.md`。
