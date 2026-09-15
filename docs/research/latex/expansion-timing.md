# 宏展开时机语料实验 — 即时展开 vs 二遍展开

**结论先行：混合方案 —— 扫描中即时建表 + 调用点查表展开，单遍即可，不需要"先建全表再二遍展开"。**

39 篇语料、44 个主文档 (含多 main/双版本)、55 个文档级分析单元中，`\begin{document}` 之后的**真·use-before-def = 0 例**。单遍模型唯一会漏的是 preamble 内 12 个宏名的前置使用，且全部落在"整调用保护"的未知命令参数里，可见损失 ≈ 0。宏体依赖链最深 4 层，不动点展开 ≤5 轮收敛——展开量没有爆炸风险。

数据：`tmp/exp/macro-stats/macro_stats2.py` → `tmp/exp/macro-stats/macro_stats2.json`。口径：从每个含 `\documentclass` 的主文件展平 `\input/\include/\subfile` (含**裸文件名形式** `\input file`)，再对展平文本做逐字符词法扫描 (注释/verbatim/def 体分层)，44 个 primary 文档 + 11 个 subfiles 子文档。

## 1. use-before-def —— 单遍的核心风险实测为零

对每个被定义宏名 (newcommand/renewcommand/def/DeclareMathOperator/newenvironment/NewDocumentCommand + providecommand/newtheorem 等同类)，比较其**首个流式调用位置**与**首个定义位置**:

| 分类                                | 宏名数            | 说明                                          |
| ----------------------------------- | ----------------- | --------------------------------------------- |
| 正常序 (def < 首用)                 | 1351              | 单遍展开天然正确                              |
| **正文级 use-before-def**           | **0**             | 首用在 `\begin{document}` 后且早于一切定义    |
| preamble 级 use-before-def          | 12                | 首用在 preamble、定义更晚 (见下)              |
| 首用后重定义 (redef)                | 3 事件            | `\renewcommand` 覆盖——单遍语义**与 TeX 一致** |
| 潜伏乱序 (外层宏被调用时内层未定义) | 1                 | 见下                                          |
| 定义但从未在文本流调用              | 3035 / 4398 (69%) | 模板宏集 + LaTeX 内部配置类 renew             |
| 定义前调用的 callsite 总数          | 14                | 全部在 preamble                               |

**正文级 0 例的含义**: 对"扫描中遇到 `\newcommand` 就登记、遇到 `\foo` 就查表"的单遍管线，正文内**没有任何一个调用会扑空**。51% 论文把定义写在 `\begin{document}` 之后 (macro-stats 268 个)，但全部遵守"先定义后使用"的线性序——作者本来就按 TeX 的顺序语义写。

**preamble 12 例全部良性**，分三类：

- **1207.7214 (5 个)**: `\papertitle` `\hgg` `\htollll` `\hWWenmun` `\massresultStatSys`——首用在 `\PreprintCoverPaperTitle{\papertitle}`/`\PreprintCoverAbstract{...}` 里 (pos ~400–1200)，定义在 5k–11k。但这些 `\PreprintCover*` 是未知命令，翻译管线**无论展开时机如何都会整调用保护**，内部宏展不展开无差别 → 实际损失 0。
- **`\left`/`\right` 的 renew (6 个，3 篇)**: `\renewcommand{\left}` 之前的 `\left` 是**原语使用**，本就不该按后来的定义展开——单遍"先按原语处理"反而正确。
- **`\def\@` (1 个，2602.09511)**: catcode/`@` 宏技巧，角落 case。

**潜伏乱序 1 例** (1207.7214): `\massresultStatSys` 体引用 `\masspeak`，外层首用在 preamble。数学上下文，可见损失 0。

**重定义 (3 事件) 反而是单遍的优势**: 2609.09529 `\CFAD` 在 L77 `\newcommand`、L2403 `\renewcommand`；2003.08934 `\resultsfigwidth` 跨 `\input` 文件 redefine。先全量建表 (last-wins) 反而会让早期调用拿到晚定义——**顺序单遍才是 TeX 语义**。

## 2. \if 族复杂度 —— 结构化配对即可，无需真求值

| 指标                      | 值                                |
| ------------------------- | --------------------------------- |
| 配对 `\if…\fi` 块         | **61 块 / 10 文档**               |
| 带 `\else`                | 47                                |
| 未闭合 / 孤儿 `\fi`       | 0 / 2                             |
| 块内含 ≥20 字符可译 prose | **仅 5 块** (4 preamble + 1 正文) |
| `\newif` 自定义旗标       | 8 个 (全部在 2005.11401)          |

opener 直方图：`\ifmmode` 36 (几乎全是 1502.01589 的 `\def\L2{\ifmmode L_2\else $L_2$\fi}` 家族)、`\ifnum` 8、`\newif` 旗标 8、`\iffalse` 2、类文件旗标 (`\if@ACM@anonymous` `\ifCLASSINFOpdf` `\ifCLASSOPTIONcaptionsoff` `\ifpdf`) 5、`\ifx`/`\ifhmode` 各 1。

含 prose 的 5 块：4 个是 preamble 包/版式开关 (`\ifnum\commentType=3` 包加载、`\ifCLASSINFOpdf`、`\ifpdf`)，1 个是正文 `\iffalse` 死代码块 (2203.02155 把附录塞在 `\iffalse…\fi` 里)。**没有任何 `\if` 块把可译正文劈成两半**。

**实现期发现的两个分类陷阱** (已计入扫描器口径): ① `\ifb` 不是条件——是 1207.7214 定义的物理单位宏 (inverse fb)，全小写 `\if`+小写名需先查宏表再判条件；② `\ifAnonymous{T}{F}` 型——类文件把 `if` 前缀名定义成**双花括号参数宏** (2609.08578 `\newcommand{\ifAnonymous}[2]{\if@ACM@anonymous #1\else #2\fi}`)，判据"非原语 `\if` 紧跟 `{` 即宏调用"可正确区分。另有 `\ifthenelse` 6 次 (花括号条件，无 `\fi`)。

**处置建议**: `\if…\else…\fi` 作结构整体处理——`\iffalse` 丢块、`\iftrue`/已知真旗标留块、`\ifmmode` 取数学分支、未知旗标整段字面保留 (或取 else 分支)。条件求值**不需要**。

## 3. `\def` 定界参数 —— 可放弃

非纯 `#n+空白` 参数段的 `\def`: **15 例 / 7 文档** (44 文档的 16%)。真定界参数约一半：1502.01589 的坐标解析宏 `\def\ra[#1 #2 #3.#4]`/`\def\dec[...]`/`\def\deco/`\def\rra`、2201.05989`\def\equationautorefname~#1\null`；另一半是`\def\@xxx`/`\def\csname…\endcsname`型伪判定。→ v1 把这类`\def` 当 opaque 宏整体保护，不做参数代入，损失限定在 ~7 篇里的十几个调用点。

## 4. `\input/\include` —— 展平必须做，注意裸文件名

| 指标                                           | 值                                                                    |
| ---------------------------------------------- | --------------------------------------------------------------------- |
| 引用事件 (input 174 / include 16 / subfile 11) | 201                                                                   |
| 嵌套深度                                       | **1 层 159、2 层 35、3 层 6、4 层 1** —— 深度 ≤4                      |
| 解析失败                                       | **0** (全部命中文件)                                                  |
| 注释掉的 `\input`                              | 8 处 / 7 文件 —— 不得展开 (已正确跳过)                                |
| `\includeonly`                                 | **0**                                                                 |
| subfiles 宏包                                  | 2 篇：2609.06443 真用 `\subfile`×11；1706.03762 只装包，实际 `\input` |
| docmute / standalone / import                  | 1 / 0 / 0                                                             |

**关键发现——裸文件名形式**: `\input macros.tex`、`\input grid_1param_result_table` (1502.01589 有 20+ 处，含嵌套 `\input grid` → `\input grid_DE`)。**miniscanner 的 `flatten_inputs` 目前只认 `{file}` 形式 → 真实 bug**，必须补裸文件名解析 (读 `[A-Za-z0-9._/-]+` 至空白/反斜杠)。subfiles 子文档 = 父 preamble + 本体 body，本实验按语义合成 (父 preamble 拼 `\begin{document}` + 子 body)，11 个子文档均正确继承父级 ~142 个定义。

## 5. 透明宏率复核 —— 严口径 9 篇 / 宽口径 21 篇

定义体去控制序列后：

| 口径                                  | 定义数 | 论文覆盖       |
| ------------------------------------- | ------ | -------------- |
| 连续 prose run ≥20 字符 (本实验，严)  | **48** | **9/39 (23%)** |
| 字母总数 >20 (macro-stats 同口径，宽) | 130    | 21/39 (54%)    |

macro-stats 的 49% (19/39) 与宽口径复核一致 (21/39)。两口径差异说明：多数"含文本"宏体其实是 `Figure~\ref{#1}`/`section~\ref` 这类短词 + 引用混合 (run <20 但 letters 合计 >20)，真·整段句子藏在宏里的 ~9 篇 (1207.7214 `\papertitle`、1207.7235 `\cmsMessage`、1403.3985 期刊名族、2003.08934 五个 caption 句等)。**结论：宏体文本提取仍必要 (1/4–1/2 论文受影响)，但"含 ≥20 字符连续 prose"作 transparent 判据会漏短词型——建议保留 letters 总数口径或降到 ~12。**

## 6. `\makeatletter` 区 —— 小且无害

14 区 / 10 文档，长度 60–531 字符 (median ~150)，区内 `\def` 合计 15 个。`@` 已在命令名字符集内，区域无需特殊处理——把 `\makeatletter`/`\makeatother` 当普通边界命令即可。

## 7. 展开爆炸风险 —— 不存在

| 指标                         | 值                                                     |
| ---------------------------- | ------------------------------------------------------ |
| stream 调用总数 (限已定义名) | **40,731**                                             |
| 定义总数                     | 4,398                                                  |
| 调用/定义比                  | ~9.3× (单文档最高 7012 次调用)                         |
| 宏体互引 token               | 1,052                                                  |
| **依赖链最大深度**           | **4** (分布：0 层 21 文档 / 1 层 14 / 2 层 8 / 4 层 1) |

每调用展开一次、体引用惰性解析，迭代 ≤5 轮即不动点；无自增/递归宏迹象。循环引用未见。

## 决策：混合单遍 (推荐) vs 二遍

**采用：扫描中即时建表 + 调用点查表展开 (+事后补救日志)。** 数据依据：

1. 正文级 use-before-def **0 例** —— 二遍的唯一收益场景不存在;
2. 重定义 3 事件 —— 单遍"覆盖即新义"是 TeX 语义，先全量建表 (last-wins) 反而错;
3. preamble 已由 `_register_macros_in` 式预扫描一次性登记 (定义不产生文本输出，前置使用不构成问题);
4. 展开量小 (链深 4、迭代 ≤5)，调用点展开的代价可忽略。

**补救兜底** (便宜可加): 展开阶段若遇到"当前未知但后来被定义"的宏名，记一条 use-before-def 日志；仿真预期语料内 ≈0 触发，主要价值是**新语料上的回归警报**。

### 接受损失的角落 case 清单

| 角落 case                          | 规模              | 损失                                                               |
| ---------------------------------- | ----------------- | ------------------------------------------------------------------ |
| preamble 前置使用 (未定义先调)     | 12 名 / 5 文档    | ≈0 (都在整调用保护的未知命令参数内)                                |
| `\def` 定界参数                    | 15 例 / 7 文档    | 该宏当 opaque 保护，不代参                                         |
| `\ifXxx{T}{F}` 双参 if 宏 (类定义) | ~20 次 / 2-3 文档 | 整调用保护；内层 `\if@` 不求值                                     |
| 非原语 `\if` 块分支选择            | 5 个 prose 块     | 取 else 或整段字面，最多漏 1 个 `\iffalse` 附录段 (它本来就死代码) |
| `\let` 定义                        | 15 / corpus       | 未建表 → 调用当未知命令保护                                        |
| `\input` 于宏体内                  | 0 观测            | 不展开，记日志                                                     |
| `\includeonly` 过滤                | 0                 | 无损失                                                             |
| active-char/catcode/`\halign`      | ~1-3 篇           | 已知放弃 (同 macro-stats 结论)                                     |

### 顺带的两个实现修正 (回输 miniscanner)

1. `flatten_inputs` 支持裸文件名 `\input file` (否则 1502.01589 全部 35 文件展不开);
2. `\if` 判定前置查宏表 (`\ifb` 单位宏) + "非原语 if 紧跟 `{` 即宏调用"规则 (`\ifAnonymous{T}{F}`)；`\newif\ifX` 的旗标名 token 不入条件栈。
