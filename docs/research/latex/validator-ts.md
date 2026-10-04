# tree-sitter-latex 译文校验器（L1）— 选型与实测

> **结论**：`@pfoerster/tree-sitter-latex` 0.6.0 经 node 子进程 JSONL 协议作可选增强层（L1）可行——8 类译文破坏 40/40 全检出、干净集 0 误报、chunk 级 <1ms；但 73.7% 真实文件自带 grammar 覆盖空隙产生的 ERROR，生产判定必须用相对模式（vs 译前标记）。
> **状态**：现行（已落地为 `validate/ts/` + `validate/l1.py`；规范见 `spec/latex-pipeline.md`）
> **日期**：2026-09-14

## 1. 选型与落地形态

文法选 `@pfoerster/tree-sitter-latex` 0.6.0[^tslatex]。排除的替代：PyPI `tree-sitter-latex` wheel 未发布；`tree-sitter-languages` 打包集未收录 latex 文法；`web-tree-sitter` WASM 仍需 JS 宿主或 wasmtime glue，工程量大于收益；现场编译 grammar 需 C toolchain，破坏零编译安装体验。

落地形态 = node 子进程 JSONL 协议（`validate/ts/` 内 validator.js + package.json 作包数据分发）：每行一个 record `{id, tex|path, expect?, baseline?}`，每行一个结果。worker 双模——默认读完 stdin 批处理（spawn-per-batch，37ms 摊薄），`--repl` 常驻模式逐行即时响应。无 node 时优雅降级 L0（`shutil.which("node")` 探测）。子进程 env 走白名单注入而非黑名单。

## 2. 检查项

| 输出字段             | 实现                                                                                                                            |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `parse_errors`       | ERROR + MISSING 节点收集（位置/snippet）；干净文件零成本                                                                        |
| `env_mismatches`     | 单次 Query 抓 begin/end/generic_command/裸 `\begin` 裸 `\end` 叶，文档序栈配对：`name_mismatch / dangling_end / unclosed_begin` |
| `unclosed_math`      | 定界符叶计数：`$`/`$$`/`\[`/`\]`/`\(`/`\)`（MISSING 叶不计）                                                                    |
| `brace_balance`      | `{` − `}` 净值                                                                                                                  |
| `placeholders`       | `[[TYPE_n]]` missing/unexpected 集合差 + lev≤2 typo 配对                                                                        |
| `ok` / `ok_relative` | 绝对判定 / 相对判定（各项 ≤ baseline 且占位符干净）                                                                             |

关键是**定界符用 CST 叶计数而非文本计数**——verbatim/comment 内的 `{`、`$`、`\end` 不产生对应节点，天然免疫误报；57 个真实主文件零 env 误报实证了这点。

## 3. 实测

检出率（批处理、绝对判定）：5 个干净主文件 × 8 类破坏（丢 `}`、丢 `$`、`\end` 改名、删 `\end`、删占位符、占位符拼错、`\[` 不配 `\]`、截断尾部）= 40/40 全命中。定位特性：brace 类破坏 ERROR 精确到破坏点 ±1B；math/env 类是容器区域级（破坏使外层 env 整体变 ERROR），对「重译该块」粒度够用。删占位符/占位符拼错是唯一纯契约信号——结构检查完全无感，印证双层分工必要性。

误报：10 个干净原始文件 + 5 个译文态 base 全部 `ok=true`；57 个 arXiv 主文件中 **42 个（73.7%）带既有 baseline ERROR**——全是 grammar 覆盖空隙（`\inferrule`、bussproofs、私类命令、LaTeX2.09 遗留语法），与文件是否被破坏无关。因此绝对判定 `ok` 在真实语料上不可用，**`ok_relative`（译文标记 vs 译前 baseline 按计数比对）是生产形态**；相对模式按计数比对使译文位移不影响判定，破坏造成的新增 ERROR 会计数上涨。

延迟（node v26.8.2）：spawn 空载 ~37ms；进程内 validate 2KB chunk 0.70ms、8KB 1.95ms、32KB 7.7ms；最坏单文件 2.2MB parse 195ms。**必须批处理/常驻进程**——逐块 spawn 50ms/次在长文档上不可行，批处理后摊薄 <1ms/块。

## 4. 实测发现的陷阱（留档）

`\end{X}` 改名不产生 ERROR（`\begin{a}…\end{b}` 语法上仍合法）——env 配对必须自做名字比对，这正是独立校验器的价值；悬空 `\end` 退化为 `generic_command`、ERROR 内 `\end{X}` 碎成 `\end` 叶 + `{X}` 兄弟节点，四种形态都要覆盖（`rawNameOf` 从 sibling 链重建）；MISSING 定界符是零宽节点不计入平衡但进 `parse_errors`；tree-sitter 偏移是 UTF-8 字节，CJK 语料 snippet 截取须用 Buffer 语义；`#eq?` 谓词在该 binding 版本不生效。

## 5. 与 L0 的分工

两层信号互补不重叠：删占位符/占位符拼错只有契约层能抓，`\end` 改名/删 `\end` 行 CST 层定位更准。L0 规则层（`validator-rules.md`）always-on，L1 CST 是可选增强层。超时无需特殊处理——块粒度下超时属异常，python 侧 30s 兜底。

### 参考文献

[^tslatex]: pfoerster. tree-sitter-latex — LaTeX grammar for tree-sitter (0.6.0). GitHub/npm. [github.com/pfoerster/tree-sitter-latex](https://github.com/pfoerster/tree-sitter-latex)
