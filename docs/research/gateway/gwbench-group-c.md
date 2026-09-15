# gwbench C 组：swe-2-max 减量横评（en→zh LaTeX 段落翻译）

日期：2026-09-14。命令 `python3 tmp/exp/gwbench/bench_free.py --models swe-2-max --runs 1 --samples 14 --out tmp/exp/gwbench/out_c`，原始数据 `tmp/exp/gwbench/out_c/results.jsonl`（含全部 src/zh/usage/reasoning_len）。样例/契约/校验同 A、B 组（`tmp/exp/rule_validator.validate_pair` + ph_order/cs_dropped/en_residue 三条增强判定，见 `bench_free.py` docstring）。串行 1s 间隔、timeout 240s、max_tokens 8192（length 自动重试至 32k，本组未触发）。样例 = 等距抽 10 个真实 chunk（5 篇 × #0/#3）+ 保 4 个合成压力样例（S1–S4），共 14 调用。

## 总览

- **契约 judge.ok = 11/14（78.6%）**；http 200 ×14，finish 全 stop，无重试、无空响应。
- 失败构成：ph_missing 0、ph_invented 0、**ph_order 违例 2**、**cs_dropped 1**（三条增强判定里唯一伤到编译语义的）。
- 延迟：min 5.0s / med 10.4s / mean 13.3s / max 29.7s —— **远低于早前探针记录的 63–124s**（见 `gateway-3003-free-swe.md`），量级与 swe-2-high（同批 med ~10s）持平，属档位间方差/探针最坏 case，非新增观察到的爆炸。
- reasoning_len：min 253 / med 600 / max 1574 字符（对照 swe-2-medium ~100、swe-2-high ~460）。
- token：in med 252 / out med 561（min 202 / max 1357），cached 全 0。
- en_residue（zh 残留英文词，粗质量信号）：11 个 PASS 样例 0–8 词，高点均为专名/URL 合理残留（S1 的 Vaswani/Bahdanau/Luong/Manning/Transformer 计 8；S3 的 `\url{}` 内容计 4 为误报）。散文层面无整句漏译迹象。

## 每样例明细

| sample           | ok  | s    | rsn  | enR | 备注                        |
| ---------------- | --- | ---- | ---- | --- | --------------------------- |
| 1706.03762#0     | ✓   | 20.2 | 319  | 0   |                             |
| 1706.03762#3     | ✓   | 9.8  | 541  | 3   |                             |
| 2305.14335#0     | ✓   | 20.1 | 1574 | 3   |                             |
| 2305.14335#3     | ✓   | 29.7 | 1092 | 2   |                             |
| 2609.09529#0     | ✓   | 6.3  | 266  | 7   | 专名残留                    |
| 2609.09529#3     | ✓   | 9.4  | 788  | 3   |                             |
| 1111.4914#0      | ✓   | 17.6 | 1302 | 3   |                             |
| 1111.4914#3      | ✗   | 10.3 | 392  | 1   | ph_order                    |
| 1207.7214#0      | ✗   | 21.3 | 964  | 0   | cs_dropped + 新增控制序列   |
| 1207.7214#3      | ✓   | 9.8  | 700  | 1   |                             |
| S1-bibitem-lead  | ✓   | 11.3 | 659  | 8   | 专名残留                    |
| S2-multikey-cite | ✓   | 5.0  | 353  | 0   |                             |
| S3-verbatim-pct  | ✗   | 5.2  | 253  | 4   | ph_order（enR 为 url 误报） |
| S4-dense-math    | ✓   | 10.5 | 353  | 0   |                             |

## 契约失败现场

### 1207.7214#0 — cs_dropped，唯一真伤（会破编译）

src 脆弱命令 8 个 = `\,`×4 + `\`×4。zh 保住了全部 `\,`（`[[MATH_3]]\,TeV`、`8\,TeV`、`7\,TeV`×2），但 **4 个 `\` 全部与后续中文字符熔合**：

- `[[MACRO_4]]\ and` → `[[MACRO_4]]\和`
- `\bbbar\ and` → `\bbbar\和`
- `\htollll\ and` → `\htollll\和`
- `[[MACRO_9]]\  channels` → `[[MACRO_9]]\道`

validator 同步报「译文新增控制序列 `\和` ×3、`\道…` ×1」——`\和`/`\道` 是未定义控制序列，重编译必炸。另外 src 行首孤立 `\`（续行残留）被整段丢弃。此样例 swe-2-high（run0）PASS，max 独 fail。

### 1111.4914#3 — ph_order，语法驱动的合理换序

占位符全在、无新增，仅顺序变：src `the ring of Witt vectors [[MATH_1566]] of [[MATH_1567]]` → zh `[[MATH_1567]] 的 Witt 向量环 [[MATH_1566]]`。英文后置 of 修饰 → 中文前置「的」结构，译文本身通顺正确，是严格序守恒契约对自然换序的误报面（E10/E21 类盲区）。swe-2-high 同样在此 fail。

### S3-verbatim-pct — ph_order，整句重构

src `reproduces the baseline of [[CITE_1]] within [[MATH_2]] … using the estimator described in [[REF_3]]` → zh `使用 [[REF_3]] 中描述的估计器，在 [[MATH_2]] 的相对误差范围内复现了 [[CITE_1]] 的基线`。状语前置重构导致占位符序反转；`\url{https://example.org/repo%20texlate}` 原样全保。swe-2-high 同 fail。

## 同一样例集对照（swe-2-high run0，out_b_high 快照）

14 个样例完全同集：high 12/14 vs max 11/14。两者共享 2 个 ph_order 失败（1111.4914#3、S3）；**max 独多一个 1207.7214#0 的 cs_dropped**。

## 判断（对照基线 swe-2-medium：契约 4/4、6.6s/次、rsn ~100）

swe-2-max 把 reasoning 抬到 med 600 字符（medium 的 ~6 倍）、延迟 med 10.4s（medium 的 ~1.6 倍），**没有换来可观测的契约或质量收益**：3 个失败里 2 个是"想得更深→句式更中文→触发序守恒"的副作用，1 个是真伤 `\`→`\和` 熔合且低思考的 high 反而没犯；PASS 面与 high/medium 基线持平，en_residue 也未优于对照——更深的思考投入流向了句式重构而非占位符保护。
