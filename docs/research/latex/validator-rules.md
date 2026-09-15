# 规则校验器原型 — 译文机械不变量校验（纯 stdlib 兜底路径）

> 交付物：`tmp/exp/rule-validator/rule_validator.py`（校验器，512 行，零依赖）+
> `tmp/exp/rule-validator/`（`gen_cases.py` 语料生成、`run_eval.py` 评测、
> `cases/cases.jsonl` 1636 例、`eval_out.json` 全量结果）。
> 定位：校验链 L0，独立于任何 LaTeX 解析器（pylatexenc 静默截断的教训），
> 也是 node 不可用时的降级（docs/04 §3 方案③）。

## 结论先行

- **10 类破坏（8 必测 + 2 补充）在 ph/raw 两层全部 100% 检出**（1323 反例无一漏网）。
- **313 干净对 0 error 误报**；2 例 warn-only（几乎无可译文本的数学命令密集 chunk 命中"CJK<30%"启发式，warn 级不影响判定）。
- **0.57 ms/对**（1636 对共 0.94s），比 tree-sitter 的 1.15ms 还快，纯 stdlib 即插即用。
- 占位符拼错类 **135/138 给出 lev≤2 自动修复建议**；3 例因数字三位全变（lev=3）退化为"缺失 + 多余"硬错，仍检出。
- 实现期抓到自身 bug 一个（词法层 cs token 丢反斜杠 → key/env 检查全哑），印证"校验器也必须被测试语料验证"——不是写完就算。

## 设计：译文不得比原文更坏

每条检查都是 **src↔zh 比较** 而非 zh 绝对判定：src 自带的括号/定界不平衡、内部不一致不追责（继承容忍），只报 zh 相对 src 的新增损伤。与 `tmp/exp/ts-validator` 的 `baseline`/`ok_relative` 是同构思想，两侧独立收敛到同一设计。

| rule          | 检查内容                                                                                         | error 条件                                                                     | warn 条件                      |
| ------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ | ------------------------------ |
| `placeholder` | `[[A-Z_]+_\d+]` multiset diff + 模糊候选（`[[..]`、`[X_1]`、`【..】`）lev≤2 配对                 | 缺失 / 多余 / 拼错（附修复建议）                                               | —                              |
| `brace`       | `{}` 平衡（`\{` `\}` 转义、`%` 注释豁免）                                                        | zh 最小前缀深度 < src，或净余额 ≠ src                                          | 计数不同但净额一致             |
| `env`         | `\begin{X}`/`\end{X}` 栈配对 + 环境名 multiset diff（签名差分）                                  | 多余 end/不匹配/未闭合 begin/新增或丢失环境名                                  | end 名偏多（栈已覆盖时的补充） |
| `key`         | `\cite*`/`\*ref`/`\label`/`\bibitem`/`\bibliography` key multiset（逗号拆分、`[..]` 可选参豁免） | src−zh 漏 key                                                                  | zh−src 新增 key（幻觉引用）    |
| `math`        | 未转义 `$` 计数；`\(` `\)` `\[` `\]` 成对计数                                                    | 任一计数 ≠ src                                                                 | `$` 奇数个（继承自 src）       |
| `length`      | zh/src 长度比；剥占位符/命令后 CJK 占 (CJK+ 拉丁) 比例                                           | —                                                                              | 比出 [0.30,2.50]；CJK<30%      |
| `macro`       | zh 控制序列集合 − src 集合                                                                       | 命中结构族（`begin`/`end`/`documentclass`/`newcommand`/`usepackage` 等 31 个） | 其余新 cs（幻觉宏清单）        |

## 实测检出率（cases.jsonl，7 篇 corpus 主文件 × ≤25 chunk，ph/raw 两层）

| 破坏类                 | level    | n       | 检出     | 命中规则                                    |
| ---------------------- | -------- | ------- | -------- | ------------------------------------------- |
| clean（对照）          | ph / raw | 175/138 | —        | 0 error                                     |
| ① 丢 `}`               | ph / raw | 44/133  | **100%** | brace（raw 层附带 key/env 级联）            |
| ② 丢 `$`               | raw      | 70      | **100%** | math                                        |
| ③ `\end` 改名          | raw      | 23      | **100%** | env                                         |
| ④ 删 `\end`            | raw      | 23      | **100%** | env                                         |
| ⑤ 丢占位符             | ph       | 138     | **100%** | placeholder                                 |
| ⑥ 占位符拼错           | ph       | 138     | **100%** | placeholder（135 修复建议 + 3 缺失 + 多余） |
| ⑦ `\[` 不配对          | raw      | 6       | **100%** | math                                        |
| ⑧ 幻觉宏 `\newcommand` | ph / raw | 175/138 | **100%** | macro                                       |
| ⑨ 删 cite key（补充）  | raw      | 122     | **100%** | key                                         |
| ⑩ 多余占位符（补充）   | ph / raw | 175/138 | **100%** | placeholder                                 |

说明：②③④⑦⑨ 只在 raw 层有例（ph 层 `$`/`\cite`/`\end` 已被占位符保护——这正是占位符方案的价值：这些破坏在 ph 层转化为 ⑤⑥ 占位符问题，仍被同一检查捕获）。⑧ 在 ph 层有 17 例附带 placeholder 命中——随机插入点恰好截断 `[[X_n]]` token，仍检出。

手工边界探针（补充语料外的对抗样例）：合法改写（掉 `\emph` 组）PASS；src 自带不平衡被 zh 继承 PASS；占位符换序 PASS；`\cite {k}` 带空格 PASS；`\cite{a,b,c}`→`\cite{a,b}` 抓出漏 `c`；全角 `【MATH_1】` 检出但无修复建议（lev=3）。

## 误报分析

- error-FP：**0/313**。继承容忍设计生效——真实 corpus chunk 里自带的轻微不平衡没有触发误报。
- warn-only：**2/313**，同一条"CJK<30%"启发式，命中 raw 层几乎无可译文本的数学命令密集 chunk（伪译文对 `$..$`/`\cmd{key}` 原样保留 → 拉丁占比高）。warn 级不影响 ok 判定；真实 LLM 译文里这类 chunk（公式夹缝句）本来就拉丁多，30% 阈值合理（早期 50% 版会多报 4 例类似 chunk）。
- 设计性 warn（非 FP）：合法删 `\emph{...}` 会留一条"brace 计数不同但净额一致"warn——这是"内容变了但结构没坏"的正确表达，留给上层聚合用。

## 与 tree-sitter（CST）路线的分工

`tmp/exp/ts-validator`（@pfoerster/tree-sitter-latex，ERROR/MISSING 节点 + CST env 配对 + 定界符叶计数 + 占位符契约）已并行实测。分工边界：

**只有规则能查（src↔zh 跨语言 diff，本质是集合比较，不是 parse 问题）：**

- cite/ref/label/bib key multiset diff——CST 能把 `\cite{..}` parse 成节点，但"key 集合 ⊆"永远要另写 diff；规则侧 5 行。
- 幻觉宏 diff（zh cs 集 − src cs 集）——CST 给命令节点，差集仍是规则活。
- 长度比 / CJK 语言 sanity——与语法树无关。
- 占位符 diff 两侧都有实现；规则版不依赖 node，是契约检查的最简形态。

**只有 CST 能查：**

- ERROR/MISSING 节点级定位（行号/字节区间/snippet）——规则只报"不平衡"，CST 报"哪个 node 坏在哪"。
- verbatim/comment 语境免疫——CST 叶计数天然不计 verbatim 内 `{`/`$`；规则的 `\x`/`%` 豁免在 `\verb|a%b|` 这类构造上有盲区（见下）。
- ERROR 区内退化形态（`\end` 碎成叶 + 兄弟节点）的 env 恢复、未知命令 arity 错。

**重叠区：** brace/env/math 配对。规则栈实测对全部结构类破坏 100% 检出，但 CST 的定位质量更高（node 级 vs "净余额不符"）。

**分层顺序建议：**

1. **L0 规则（本原型）**：LLM 每返回一个 chunk 立即校验，0.57ms、零依赖、错误信息可直接翻译为修复指令（"占位符 [[MATH_1Z]] 应为 [[MATH_12]]"），不过 → 重译该块/回退原文。
2. **L1 CST**：重组文档或 L0 判可疑的块过 tree-sitter，拿 node 级定位和深层结构保证。
3. **L2 编译 fixloop**：tectonic 错误行回灌。

规则先行还有一个独立理由：校验器必须独立于解析器——若 L1 与主解析器同族，同一盲区会穿透两层；stdlib 规则与 CST 文法零共享代码，是天然异构。

## 已知盲区（如实记录）

- `\verb|a%b|` / verbatim 环境内的 `%` 被注释规则吞掉其后 span：src/zh 对称吞→不产生 FP，但该 span 内的损伤不可见（ph 层 `[[VERB_n]]` 保护下无此问题；raw 层才暴露）。
- 占位符变体 lev>2（如全角 `【..】`、改写类型名）只报"缺失 + 多余"，无修复建议——可放宽阈值到 3 或加正规化预处理。
- env 签名差分在"src 自身栈不一致"的场景按类别计数比对，理论上存在"zh 改掉 A 处同时又坏 B 处"的签名巧合遮蔽；实测 313 干净对中 src 栈不一致为 0 例，未触发。
- 幻觉非结构宏（`\foo`）目前 warn 级——LLM 译文里新 cs 几乎全是幻觉，若产品策略从严可一键升 error。
- 未覆盖项（有意不做）：`\begin` 环境内容完整性、嵌套深度 >2 的语义正确性——留给 CST/编译层。

## 复现

```bash
python3 tmp/exp/rule-validator/gen_cases.py   # 重新生成 cases/cases.jsonl
python3 tmp/exp/rule-validator/run_eval.py    # 检出率表 + eval_out.json
python3 tmp/exp/rule-validator/rule_validator.py src.tex zh.tex  # 单对校验
```
