# ADR-0004 译文校验三层：L0 规则 always-on + L1 tree-sitter 可选 + L2 编译 log 回灌

> **状态**：现行
> **日期**：2026-09-15（05 裁决 3）| 更新 2026-09-17（L0 判据修订、L2 回落补验）

## 上下文

「能 parse」≠「parse 对」已有实证（pylatexenc 假阳性、tree-sitter `\verb|a%b|` 静默错）；「出 PDF」≠「成功」更被两次实锤——mock 注入 132 处译文损坏时编译 0 报错、56 处丢失占位符的 PDF 全照出。校验必须独立于解析器与编译器。同时 tree-sitter 文法在真实文件上有 baseline 噪声，原生接入方式（native binding/node 子进程/纯自写）待定。

## 裁决

三层纵深，**全部 src↔zh 相对判定**（「不得比源更坏」，绝对判定在脏语料上误报）：

- **L0 自写规则 always-on**（stdlib 零依赖）：占位符多重集 diff + Levenshtein≤2 修复建议、brace 相对平衡、`\begin/\end` env 名配对、cite/ref/label/bib key 集合 diff（含 `\cite{a,b,c}` 逗号拆分）、math 定界计数、长度比 + CJK 占比 sanity、幻觉宏名单。
- **L1 tree-sitter CST 可选增强**（`texlate[ts-validator]`）：node 子进程跑批处理 JSONL 校验器（摊薄 <1ms/块），**必须 baseline 相对模式**——73.7% 真实文件自带 grammar 空隙 ERROR，绝对模式全是噪声；不让 native/node 依赖卡住 uv 分发。
- **L2 编译 log 回灌**：`!` 错误行 + `l.N` 行号 + paren 文件栈归因；错误计数**双格式** `^!` + `file:line:`（只数 `!` 漏全部引擎级错误）；L2 失败 → 逐块回退原文重 splice。
- 回路：校验不过 → 带错误描述重译该块 → 再不过 → `fallback_orig` 回原文。

## 理由

- E6：L0 规则对 10 类破坏 1323 例 100% 检出、313 干净对 0 error-FP、0.57ms/对——always-on 层成立。
- E7：L1 40/40 检出、0/15 FP、chunk 级 0.7–2ms；42/57 真实文件带 baseline ERROR——相对模式是生产前提。
- E10 Mode B：132 处损坏 validator 编译前 132/132 捕获——校验独立层价值实锤。
- 证据：主仓 `docs/05` E6/E7/E10；调研档案 `research/latex/validator-rules.md`、`research/latex/validator-ts.md`。

## 演变

- E21/E22 大样本修面（2026-09-14/15）：幻觉宏名单改**双向**（补「src 命令多重集 ⊆ zh」方向，抓 sonnet 删 `\` 脆弱间距命令）；长度比下界 0.3→~0.25（恰压正常 CJK 压缩线）；占位符严格序守恒降软信号（~95% 违例是合法中文换序，硬判据只留结构占位符脱离文本位）；`cs_dropped` 升硬判据（抓到 `\`+中文熔成未定义 cs 的真编译炸弹）。
- 2026-09-17：L2 回落原文重 splice 后**补一次裸编验证**（`fallback_verdict` 三态记录）——回落态即交付树，zh-src.zip 不装未验证树；`fallback_unverified` 旗标退役。

## 现状

实现落在 `validate/` 包：`l0.py`（规则层）、`l1.py` + `ts/validator.js`（node 批处理 CST 校验）、`l2.py`（编译 log 归因）、`report.py`；`repair.py`/`repair_l2.py` 承载 L2→重 splice→补验的回灌环（e2e/worker 双臂共享）。L1 为可选组件，未进默认依赖。
