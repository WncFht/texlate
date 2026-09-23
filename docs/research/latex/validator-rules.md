# 规则校验器（L0）— 译文机械不变量校验的设计与实测

> **结论**：纯 stdlib 七条 src↔zh 比较规则在 1636 例评测集上对 10 类破坏 100% 检出、0/313 error 误报、0.57ms/对——足以作 LLM 每 chunk 返回时的即时校验层（L0）。
> **状态**：现行（已落地为 `validate/l0.py`，并有 ph 锚点、注释区占位符、bib 豁免等扩展；规范见 `spec/latex-pipeline.md`）
> **日期**：2026-09-15

## 1. 定位与设计原则

L0 是校验链第一层，独立于任何 LaTeX 解析器——pylatexenc 静默截断的教训说明校验器必须与主解析器异构，否则同一盲区穿透两层；同时它也是无 node 环境的降级路径。

核心设计原则是**「译文不得比原文更坏」**：每条检查都是 src↔zh 比较而非 zh 绝对判定。src 自带的括号不平衡、内部不一致不追责（继承容忍），只报 zh 相对 src 的新增损伤。这与 tree-sitter 侧 `baseline`/`ok_relative` 的思路同构（见 `validator-ts.md`），两侧独立收敛到同一设计。

## 2. 七条规则

| rule          | 检查内容                                                                                  | error 条件                                                             | warn 条件                      |
| ------------- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------ |
| `placeholder` | `[[A-Z_]+_\d+]` multiset diff + 模糊候选（`[[..]`、`[X_1]`、`【..】`）lev≤2 配对          | 缺失/多余/拼错（附修复建议）                                           | —                              |
| `brace`       | `{}` 平衡（`\{` `\}` 转义、`%` 注释豁免）                                                 | zh 最小前缀深度 < src，或净余额 ≠ src                                  | 计数不同但净额一致             |
| `env`         | `\begin{X}`/`\end{X}` 栈配对 + 环境名 multiset diff                                       | 多余 end/不匹配/未闭合 begin/环境名增删                                | end 名偏多（栈已覆盖时的补充） |
| `key`         | `\cite*`/`\*ref`/`\label`/`\bibitem`/`\bibliography` key multiset（逗号拆分、可选参豁免） | src−zh 漏 key                                                          | zh−src 新增 key（幻觉引用）    |
| `math`        | 未转义 `$` 计数；`\(` `\)` `\[` `\]` 成对计数                                             | 任一计数 ≠ src                                                         | `$` 奇数个（继承自 src）       |
| `length`      | zh/src 长度比；剥占位符/命令后 CJK 占（CJK+拉丁）比例                                     | —                                                                      | 比出 [0.30, 2.50]；CJK<30%     |
| `macro`       | zh 控制序列集合 − src 集合                                                                | 命中结构族（`begin/end/documentclass/newcommand/usepackage` 等 31 个） | 其余新 cs（幻觉宏清单）        |

> **落地勘误**（本表为 2026-09-15 评测时点的历史快照；现行口径见 `validate/l0.py` 与 `spec/validate.md`）：生产规则集已扩至 **14 条 checker**（placeholder、brace、env、key、math、same_source、length、residual_en、macro、item_glue、ph_in_cs、bare_cs、protocol_echo、comment_eof——`spec/latex-pipeline.md`/`spec/validate.md` 作「14 项」）。表内两处已漂移：① `length` 现行口径是剥后 token 代理 est_tokens 比出 `[0.30,3.00]` 即 **error**（`TOKEN_RATIO_LO/HI`，E24 升级；src est<10 豁免），CJK<30% 仍 warn——原表「warn-only [0.30,2.50] 长度比」已作废；② `macro` 的 zh 新增方向在 E24 下**任何**新控制序列均 error（不只结构族，含 `\`+CJK 熔合 cs），src→zh 丢失方向中脆弱间距命令（`\` `\,` `\;` `\:` `\!` `~`）计数差（cs_dropped）为 error、其余丢失 warn；结构族 `STRUCT_CMDS` 实为 **27** 个（非 31，初版提交即 27）。

## 3. 实测（7 篇语料主文件 × ≤25 chunk，ph/raw 两层，1636 例）

10 类破坏全部 100% 检出（1323 反例无一漏网）：丢 `}`、丢 `$`、`\end` 改名、删 `\end`、丢占位符、占位符拼错、`\[` 不配对、幻觉 `\newcommand`、删 cite key、多余占位符。其中丢 `$`/`\end` 改名/删 `\end`/`\[` 不配对/删 cite key 只在 raw 层有例——ph 层这些构造已被占位符保护，破坏在 ph 层转化为占位符问题仍被同一检查捕获，这正是占位符方案的价值。占位符拼错类 135/138 给出 lev≤2 自动修复建议（3 例数字三位全变 lev=3 退化为「缺失+多余」硬错，仍检出）。性能 0.57ms/对（1636 对共 0.94s），快于 tree-sitter 的 1.15ms。

误报：error 级 0/313——继承容忍设计生效，真实 chunk 自带的轻微不平衡不触发误报。warn-only 2/313 同为「CJK<30%」启发式，命中几乎无可译文本的数学命令密集 chunk（30% 阈值是调过的：早期 50% 版会多报 4 例同类）。设计性 warn 一例：合法删 `\emph{...}` 留「brace 计数不同但净额一致」——这是「内容变了但结构没坏」的正确表达，留给上层聚合。

实现期抓到校验器自身 bug 一个（词法层 cs token 丢反斜杠 → key/env 检查全哑），印证「校验器也必须被测试语料验证」。

## 4. 与 CST 路线的分工

**只有规则能查**（src↔zh 跨语言 diff 本质是集合比较）：cite/ref/label/bib key multiset——CST 能 parse `\cite{..}` 成节点但 key 集合差永远要另写 diff；幻觉宏 diff（zh cs 集 − src cs 集）；长度比/CJK sanity；占位符契约的最简形态（不依赖 node）。

**只有 CST 能查**：ERROR/MISSING 节点级定位（行号/字节区间/snippet）；verbatim/comment 语境免疫（CST 叶计数天然不计 verbatim 内 `{`/`$`，规则的 `%` 豁免在 `\verb|a%b|` 上有盲区）；ERROR 区内退化形态的 env 恢复与未知命令 arity 错。

**重叠区**：brace/env/math 配对——规则栈实测全检出，但 CST 定位质量更高（node 级 vs 「净余额不符」）。

分层：L0 规则（每 chunk 即时，错误信息可直接翻译为修复指令如「`[[MATH_1Z]]` 应为 `[[MATH_12]]`」）→ L1 CST（重组文档或 L0 可疑块，node 级定位）→ L2 编译 fixloop（错误行回灌）。L1 实现见 `validator-ts.md`。

## 5. 已知盲区（留档）

`\verb|a%b|` 内 `%` 按注释吞掉其后 span——src/zh 对称不产生 FP，但该 span 内损伤不可见（ph 层 `[[VERB_n]]` 保护下无此问题，仅 raw 层暴露）；占位符变体 lev>2（全角 `【..】`、改写类型名）只报「缺失+多余」无修复建议；env 签名差分在「src 自身栈不一致」理论上可被巧合遮蔽（实测 313 干净对中 src 栈不一致 0 例）；幻觉非结构宏（`\foo`）为 warn 级，产品策略从严可一键升 error。未覆盖项（有意不做）：`\begin` 环境内容完整性、嵌套深度语义——留给 CST/编译层。
