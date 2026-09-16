# Sabotage 逃逸基线 — 2026-09-16

SabotageTranslator（Mode B：每段 ~30% 注入占位符丢失/臆造）+ PerturbTranslator（Mode C：每占位符 ~10% 段内挪位）走完整管线：normalize → mock 翻译 → L0 校验链 → splice → prepare_chinese(ctex) → xelatex → judge。`src/` 冻结于 `tmp/exp/src-snapshot-sabotage`；破坏决策为内容哈希 → 确定性可复现。

口径说明：emb 台账经 `_seg_of` 把破坏事件对回 chunk——CRLF 源（`[[SL]]` 解回 `\n` 对不上 `\r\n` 原文）事件对账失败，sabotaged/escaped 双账漏记。**真逃逸以 recount 为准**：`status==ok 且译文占位符 multiset≠源`（事件无关，tmp/exp/sabotage_recount.py，仅重跑翻译半段不编译）。

## corpus39 全量（39 篇）

- base-xel verdict: {'clean': 11, 'fail': 12, 'partial': 16}
- pipe-xel verdict: {'clean': 15, 'fail': 4, 'partial': 20}
- pipeB-xel verdict: {'clean': 10, 'fail': 4, 'partial': 24, 'reject': 1}
- pipeC-xel verdict: {'clean': 4, 'fail': 4, 'partial': 30, 'reject': 1}

### Mode B（pipeB-xel）— 硬门槛 escaped==0

- emb 台账：破坏块 4546（事件 14056）→ caught 4133 / recovered 413 / escaped 0
- **重算（事件无关 + CRLF 修正对账）**：破坏块 4546 → caught 4133 / recovered 413 / **escaped 0**（leftover_ph 0） — 门槛：**PASS**

### Mode C（pipeC-xel）

- 台账：挪位 8426 / 涉块 4580 → 进 splice 4405 / 回退 175
- 重算：挪位 8426 / 涉块 4580 → spliced 4405 / dropped 175（spliced = 挪位译文进文档——multiset 同，L0 位置盲 by design）
- 存活率 vs pipe-xel: 34/35 出 pdf；退化: hep-th/9901001

## corpus_v3 分层抽样（core/booster/hot 等比, seed=42）（180 篇）

- base-xel verdict: {'clean': 89, 'fail': 40, 'partial': 50}
- pipe-xel verdict: {'clean': 107, 'fail': 7, 'partial': 65}
- pipeB-xel verdict: {'clean': 91, 'fail': 17, 'partial': 57, 'reject': 14}
- pipeC-xel verdict: {'clean': 66, 'fail': 19, 'partial': 80, 'reject': 14}

### Mode B（pipeB-xel）— 硬门槛 escaped==0

- emb 台账：破坏块 7056（事件 22656）→ caught 6163 / recovered 893 / escaped 0
- **重算（事件无关 + CRLF 修正对账）**：破坏块 7089 → caught 6195 / recovered 893 / **escaped 1**（leftover_ph 1） — 门槛：**FAIL**
- 对账差：台账 sabotaged 7056 vs 修正 7089（+33 为 _seg_of CRLF 盲点回收）
- escaped 逐案:
  - `1012.5411` chunk `7:1` kind=['fabricate_ph'] detail=['fab [[MATH_966]]@46'] extra=['[[MATH_966]]'] lost=[]

### Mode C（pipeC-xel）

- 台账：挪位 16400 / 涉块 6228 → 进 splice 5938 / 回退 290
- 重算：挪位 16460 / 涉块 6264 → spliced 5973 / dropped 291（spliced = 挪位译文进文档——multiset 同，L0 位置盲 by design）
- 存活率 vs pipe-xel: 146/172 出 pdf；退化: 0806.1415, 1012.1584, 1306.2177, 1306.5813, 1811.03539, 2410.06025, astro-ph/0307344, astro-ph/0605227, astro-ph/9703134, astro-ph/9703152, astro-ph/9703198, astro-ph/9910477, cond-mat/0111297, cond-mat/0501128, cond-mat/9703161, cond-mat/9910246, hep-lat/0111009, hep-ph/0111218, hep-ph/9703228, hep-ph/9910403, hep-th/9703203, math/0605284, physics/0307013, q-alg/9703046, quant-ph/0605071, solv-int/9703010

## 逃逸机制分析

### 已确认逃逸：fabricate-into-comment（L0 mask_comments 洞）

`validate/l0.py:331` `_check_placeholder` 先 `mask_comments(src/zh)` 再做占位符 multiset 比对——`%` 到行尾整段抹空。Mode B 臆造的 `[[MATH_9xx]]` 若落在 zh 的注释行内，校验两侧都看不见它 → status ok → splice 拿它找 ph_map 无果 → 字面残留进文档（`leftover_ph` 告警但不拦截）。

实例：`1012.5411` chunk `7:1`（revtex aiptemplate.tex，CRLF 纯注释块）→ `fab [[MATH_966]]@46`，源 0 占位符、译文 1 个臆造占位符，validate_pair 返回 ok。

影响面评估：① fabricate-into-comment 是该洞唯一逃逸形——drop_ph 丢的是真占位符（真占位符必在非注释区，丢则 missing 捕获）；② 注释内的臆造占位符不渲染进 PDF——损坏限于源码注释层，读者不可见但 artifact 被污染；③ verbatim/lstlisting 等逐字环境有同类遮盖风险（mask_tex 一族），本次样本未触发。

### harness 侧账修正（非产品 bug 但决定门槛真假）

`e2e_mock_bench._seg_of` 对 CRLF 源失配：事件 seg 里 `[[SL]]` 解回 `\n`，而 `r.source` 保留 `\r\n`，子串判定失败 → 该块破坏从 sabotaged/escaped 蒸发（1012.5411 台账 escaped=0、leftover_ph=1 即此漏报）。v3 修正对账回收 sabotaged +33 / moved +60。

### 修复优先级建议（修成 escaped==0 的清单）

1. **L0**：`_check_placeholder` 注释区占位符纳入比对——`mask_comments` 前对 `%` 行内的 PH_RX 命中单独计数，或 comment-only chunk 不抹注释校验（最小修复：zh 注释区多出 PH_RX 命中即 error）。
2. **harness**：`_seg_of` 两侧 `\r\n→\n` 归一（recount 已实现的口径），否则 escaped 指标系统性偏低、门槛不可信。
3. **产品兜底**：`leftover_ph>0` 目前仅告警——splice 把不可解析占位符字面留在文档里应升级终态（至少 partial），否则同类逃逸只剩审计可见。
