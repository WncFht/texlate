# tree-sitter-latex 译文校验器原型 —— 实测报告

> 日期：2026-09-14 · 代码：`tmp/exp/ts-validator/` · 数据：`tmp/exp/ts-validator/results/results.json`

## 结论先行

- **检出率 40/40 = 100%**: 5 个干净主文件 × 8 类 LLM 译文破坏 (丢 `}`、丢 `$`、`\end` 改名、删 `\end` 行、删占位符、占位符拼错、`\[ 不配 \]`、截断尾部) 全部命中，无漏检。
- **误报 0/15**: 10 个干净原始文件 + 5 个译文态 base(带占位符契约) 全部 `ok=true`。
- **真实语料上 env/brace/math/占位符检查零误报**: 57 个 arXiv 主文件全部跑过，自定义检查 (环境配对、括号平衡、数学配对、占位符)**一次误报都没有**;唯一噪声源是 grammar 覆盖不全产生的 baseline ERROR 节点 —— **42/57(73.7%)真实主文件带既有 ERROR**,与译文质量无关。→ **生产判定必须用相对模式**(译文 vs 译前签名 diff),已实现 `baseline` 协议字段 + `ok_relative`。
- **延迟**: spawn 空载 37ms;段落级 chunk(2–8KB) 校验 0.7–2ms;32KB 文件 49ms 单次 spawn;194KB 117ms。**必须批处理/常驻进程** —— 逐块 spawn 一次 50ms 不可接受，批处理模式下 spawn 成本摊薄到 <1ms/块。
- **工程建议**: python 自写规则 (brace/占位符/cite key diff) 做 always-on 层，node 子进程 CST 校验做**可选增强层**(`texlate[ts-validator]`),无 node 时优雅降级 —— 与 ADR"自写规则 + 独立 CST 校验"的双层设计一致。uv 分发:validator.js + 两个 npm 依赖随包作 data，首次运行 `npm i --prefix` 或要求用户装 node。

## 交付物

```
tmp/exp/ts-validator/
├── validator.js        # 校验器本体(亦可 import: module.exports.validate)
├── gen_cases.js        # 破坏样本生成器(语料对)
├── run_eval.js         # 评测驱动: 检出率/误报/延迟 → results/results.json
├── py_spawn_demo.py    # 生产路径演示: python spawn node + JSONL (~35 行)
├── probe_query.js      # Query API 探针(开发留档)
├── cases/              # 45 个样本: 5 base + 40 破坏 + cases.jsonl 清单
└── results/results.json
```

复现：`node gen_cases.js && node run_eval.js`;演示：`python3 py_spawn_demo.py`。
依赖复用 `bench/ts/node_modules`(tree-sitter 0.25 + @pfoerster/tree-sitter-latex 0.6.0),绝对路径 require，免安装。

## 设计

### 协议 (JSONL,stdin/stdout)

每行一个 record:`{"id", "tex"|"path", "expect"?, "baseline"?}` → 每行一个结果。
单行即单文件模式;非 JSONL 输入兜底按裸 .tex 处理。

- `expect`: scanner 发出的 `[[TYPE_n]]` 占位符契约 (multiset)。
- `baseline`: 译前源文件签名 `{parse_errors, env_mismatches, unclosed_math, brace_balance}` → 启用 `ok_relative` 相对判定。

### 检查项与实现

| 输出字段             | 实现                                                                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `parse_errors`       | `hasError` 剪枝遍历收集 ERROR + MISSING 节点 (startByte/row/snippet);**干净文件零成本**                                                                                                    |
| `env_mismatches`     | 单次 tree-sitter **Query**(C++ 遍历) 抓 `begin/end/generic_command/裸\begin裸\end` 叶，文档序进栈配对;记录 `{begin_env, end_env, line, kind: name_mismatch\|dangling_end\|unclosed_begin}` |
| `unclosed_math`      | Query 抓定界符叶计数：`$`/`$$`/`\[`/`\]`/`\(`/`\)`(missing 叶不计)→ 奇偶/差值                                                                                                              |
| `brace_balance`      | 同上，`{` − `}` 净值                                                                                                                                                                       |
| `placeholders`       | 文本正则抓 `[[TYPE_n]]` → missing/unexpected 集合差 + **Levenshtein ≤2 typo 配对**(可自动修复)                                                                                             |
| `ok` / `ok_relative` | 绝对判定 (全部为零)/相对判定 (各项 ≤ baseline 且占位符干净)                                                                                                                                |

**关键：定界符用 CST 叶计数而非文本计数** —— verbatim/comment 内的 `{`、`$`、`\end` 不产生对应节点，天然免疫误报。57 个真实主文件零 env 误报实证了这点。

## 实测

### 检出率 (批处理模式，绝对判定)

| 破坏类型        | 检出 | 命中信号       | 备注                                                      |
| --------------- | ---- | -------------- | --------------------------------------------------------- |
| ①丢 `}`         | 5/5  | err:5, brace:5 | ERROR 定位精确 (破坏点 +1B)                               |
| ②丢 `$`         | 5/5  | err:5, math:5  | unclosed_math 兜底，MISSING `$` 常在 EOF                  |
| ③`\end{X}` 改名 | 5/5  | env:5, err:3   | 精确报 `{begin_env:"equation",end_env:"equationx",line}`  |
| ④删 `\end` 行   | 5/5  | err:5, env:5   | 报 `equation` vs 下一个 `\end{document}` 的 name_mismatch |
| ⑤删占位符       | 5/5  | ph-miss:5      | **唯一纯占位符信号** —— 结构检查完全无感，契约 diff 兜底  |
| ⑥占位符拼错     | 5/5  | ph-typo:5      | `MTH_2`↔`MATH_2` Levenshtein=1 配对成功                   |
| ⑦`\[ 不配 \]`   | 5/5  | err:5, math:5  | MISSING `$$`(grammar 内部把 `\]` 记作 `$$`)               |
| ⑧截断尾部       | 5/5  | err:5, env:5   | unclosed_begin(document + 当前 env)                       |

定位特性：brace 类破坏 ERROR 精确到破坏点 ±1B;math/env 类破坏 ERROR 是"容器区域"级 —— 破坏使外层 env(常为 `document`) 整个变成 ERROR，起点在 `\begin{...}` 处。可定位到出错 env/节,对"重译该块"够用。

### 误报

| 集合                                    | flagged                                               |
| --------------------------------------- | ----------------------------------------------------- |
| 10 个干净原始文件 (1.7KB–283KB)         | **0/10**                                              |
| 5 个译文态 base(带 8×`[[MATH_n]]` 契约) | **0/5**                                               |
| 57 个主文件绝对判定                     | 42/57 —— **全部 err>0;env/math/brace/占位符误报为 0** |

42 个 flagged 主文件全是 grammar 覆盖空隙 (`\inferrule`、bussproofs、私类命令、LaTeX2.09 遗留语法等),文件本身无破坏。→ `ok`(绝对判定) 在真实语料上不可用;`ok_relative`(vs 译前签名) 是生产形态。注意相对模式按**计数**比对，译文位移不影响;破坏造成的新增 ERROR 会计数上涨 (破坏常级联放大计数，见 rename-end 把 `\begin{document}` 到 EOF 吞成一个 ERROR)。

### 延迟 (M 系列 Mac, node v26.8.2)

| 模式                                               | 实测                                         |
| -------------------------------------------------- | -------------------------------------------- |
| spawn 空载 (node + binding 加载)                   | med **36.8ms**                               |
| 单文件 spawn: 32KB                                 | med 49.2ms                                   |
| 单文件 spawn: 194KB                                | med 117ms                                    |
| 批处理 JSONL: 107 文件 (含 2.2MB/395KB/283KB 怪物) | med 3.77s → **摊薄 35ms/文件**(被大文件拉高) |
| 进程内 validate: ~2KB chunk                        | med **0.70ms**                               |
| 进程内 validate: ~8KB chunk                        | med 1.95ms                                   |
| 进程内 validate: ~32KB                             | med 7.7ms                                    |
| 进程内 parse(全部 107):                            | med 3.0ms,max 195ms(2.2MB qit-notes)         |

validate 总耗时 ≈ parse + Query 捕获封送:189KB 文件 parse 20ms + Query ~44ms;2.2MB qit-notes(10 万 + 捕获)parse 195ms + Query ~540ms。**Query 重写已比初版递归 walkAll 快 ~2.5×**(qit-notes 1842→735ms);若需再压，方向是"verbatim/comment 区间掩码 + 文本计数"替代定界符捕获 (#eq? 谓词在本 binding 版本实测不生效，0 捕获)。对段落级 chunk(1–5KB) 全部 <1ms，无优化必要。

## 关键坑 (实测发现)

1. **`\end{X}` 改名不产生 ERROR**: `\begin{a}…\end{b}` 语法上仍是合法 `generic_environment` —— env 配对**必须**自做名字比对，这正是独立校验器价值所在。
2. **悬空 `\end` 退化为 `generic_command`**;`\begin` 无配对则进 ERROR;ERROR 内 `\end{X}` 碎成 `\end` 叶 + `{X}` 兄弟节点 —— 四种形态都要覆盖 (已实现，`rawNameOf` 从 sibling 链重建)。
3. **MISSING 定界符不计入平衡计数**(零宽节点),但进 `parse_errors`。
4. **占位符删除/拼错对结构检查完全无感** —— ⑤⑥ 只能由契约 diff 抓，印证 ADR"自写规则 + CST"分层必要性。
5. 生成器教训 (自证有效): 初版破坏器把 `\end`/`\]` 打进注释 (文件实际未坏 → 校验器正确不报) 和嵌套数学 `$\ketbra{\textrm{$U$}}$` 拦腰切断 (产生真实 brace 失衡 → 被抓)。两次"误报/漏检"都是生成器 bug，校验器行为均正确。
6. tree-sitter 偏移是 **UTF-8 字节**;本批语料纯 ASCII 无影响，处理 CJK/法语语料时 snippet 截取要用 Buffer 语义。

## 工程评估：node 子进程作为生产路径

**协议已验证可行**: `py_spawn_demo.py`(~35 行)Popen + JSONL 一次 spawn 校验 9 文件，行为与 node 侧一致。生产形态建议：

- **默认走批处理/常驻 worker**: 当前实现读全部 stdin 再处理，适合"每块译文回来就 spawn 一次喂 N 条";若做常驻进程，把 IPC 循环改成 readline 逐行即时响应即可 (~10 行改动)。逐块单 spawn(50ms/次) 在长文档上不可行，批处理后 spawn 摊薄 <1ms/块。
- **uv 分发时的 node 依赖处理**(按推荐度排序):
    1. **可选组件 `texlate[ts-validator]`(推荐)**: validator.js + `package.json`(tree-sitter + @pfoerster/tree-sitter-latex，均有 prebuilt) 打进 wheel 作 package data;运行期 `shutil.which("node")`,有 node 则 `npm i --prefix <data>`(一次性，~5s) 后启用，无 node → 警告降级到 python 自写规则层。自写层 (brace/占位符/cite key/env 名文本配对) 本来就要写 (占位符契约 diff 只能 python 侧做),CST 层是纯增量。
    2. **要求系统 node**(文档前置条件): 最省事，但把"解析正确性"绑在外部依赖上 —— 校验是质量闸，降级方案必须存在，故不推荐单独用。
    3. **web-tree-sitter WASM 打进包内**: wasm 单文件可随 wheel 分发，但仍需 JS 宿主 (node/deno) 或 python wasm 运行时 (wasmtime + 手写 binding glue),工程量大于收益;仅当目标环境禁 native 时考虑。
    4. py-tree-sitter + 现场编译 grammar C 源码：需用户有 C toolchain，破坏 uv 零编译体验，排除。
- **双层校验分工**(与 ADR 一致): python 自写规则 always-on(占位符契约、brace token-diff、cite/ref key 集合、长度比 —— 全是集合运算，零依赖);node CST 层提供"能 parse 但错了"的独立视角 (env 配对、MISSING 节点、结构级 ERROR)—— 本实测证明两层的信号**互补不重叠**(⑤⑥ 只有契约层能抓，③④ CST 层定位更准)。
- 超时：无需特殊处理，实测最坏文件 (2.2MB)parse 195ms;块粒度下超时属异常，python 侧 `subprocess timeout=30s` 兜底即可。
