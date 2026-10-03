# e2e_eval holdout-200 冻帧评测：抽样与终态指标（2026-10-02）

> **结论**：holdout 留出层 200 篇冻帧全链路实测——zh 可交付 171/200（85.5%），其中 fixloop 修复救回 42 篇（尝试 45 救回 42，修复率 93%）；不可交付 29 篇 = 上游死 26（路由拒绝 19 + 翻译期死 7）+ 修不了 3。死因主体是 off-CTAN 绝版期刊宏包（compile fail 21 篇中 17 篇为 2011 年前物理圈论文）。帧内 2021 年后 CS 仅 14 篇，不足以代表新 CS 论文，需专项帧补测。
> **状态**：时点证据（2026-10-02 口径，rn=1 终态 dedup 还原）
> **日期**：2026-10-02

## 1. 评测设计

spec `e2e_eval`（eval=True，EVAL_LAYERS 闸隔离 dev 池），六段链：

| stage    | 内容                                                           | 付费 |
| -------- | -------------------------------------------------------------- | ---- |
| route    | src 物化 → find_main_tex → route_project                       | 否   |
| xlat     | normalize → translate_tree_async（`swe-2-medium`，devin-2api） | 是   |
| compile  | zh 树 → splice → prepare_chinese → xelatex best-effort + judge | 否   |
| fixloop  | 冷 usertree + TUNA + tlpdb + vendor 兜底修复 → 复判            | 否   |
| base     | 原文直编对照臂（en，无修复）                                   | 否   |
| layoutqc | \pdfsavepos 版面注锚质检                                       | 否   |

唯一付费面是 xlat；fixloop 本臂 `llm_hook=None`（规则修复，不调模型）。

## 2. 帧构建与构成

池 = holdout 留出层（EVAL_ONLY）3,020 篇，按 `stratum_cell` 分层等比抽 200（seed=20261001），冻帧落 `bench/nominations/e2e_eval_holdout.jsonl`，帧 sha 经 route metrics 留痕。构成：

| 年代带          | 篇数 | 学科组    | 篇数 |
| --------------- | ---: | --------- | ---: |
| a_pre2007       | 36   | hep-phys  | 41   |
| b_2007_11       | 37   | math      | 39   |
| c_2012_16       | 36   | cs        | 43   |
| d_2017_20       | 35   | astro-ph  | 25   |
| e_2021_25       | 35   | cond-mat  | 25   |
| holdout\|recent | 21   | eess-stat | 9    |
|                 |      | quant-ph  | 7    |
|                 |      | nucl      | 4    |
|                 |      | recent    | 6    |
|                 |      | other     | 1    |

全年代带配额均衡是设计目标，副作用是新兴切片被摊薄：e_2021_25\|cs 仅 14 篇，加上 recent 层中的 CS 篇也到不了统计可用量。对「新 CS 论文表现如何」这个问题，本帧只能给个位数到十余篇的证据。

## 3. 终态账（rn=1，dedup 还原口径）

### 3.1 分 stage

| stage    | 分布                                                                     |
| -------- | ------------------------------------------------------------------------ |
| route    | ok 181 / reject 19                                                       |
| xlat     | ok 134 / partial 40 / reject 26（上游死 + oversize）                     |
| compile  | clean 132 / partial 21 / fail 21 / skip 26                               |
| fixloop  | clean 34 / partial 8 / fail 3（unfixable）/ reject 155（declined）       |
| base     | clean 119 / partial 33 / fail 29 / error 18 / reject 1                   |
| layoutqc | clean 40 / ok 133 / reject 26（199/200，2111.00241 一格 executor error） |

fixloop 的 `reject` 全部是闸内 decline，不是修复失败：not_wanted 133（编译已可用不值得修）+ route_dead 19 + no_compile 3（编译格从未产出，修复汇无件可修）。

### 3.2 逐篇交付账

| 终态                              | 篇数 |
| --------------------------------- | ---: |
| compile clean，fixloop declined   | 115  |
| compile partial，fixloop declined | 14   |
| fixloop 修出 clean                | 34   |
| fixloop 修出 partial              | 8    |
| fixloop unfixable                 | 3    |
| 上游死（route/xlat 链断）         | 26   |

zh 可交付 = 171/200（85.5%）。对照 en 原文直编臂 clean+partial 152/200（76%）——zh 臂反超的原因是 fixloop 修复环在 en 臂上不存在：base 只做裸编译，坏了不修。

### 3.3 fixloop 判决细目

尝试修复 45 格（`_want_fix` 谓词命中），救回 42：

| 修复判决        | 格数 | 终态映射            |
| --------------- | ---: | ------------------- |
| clean           | 19   | clean               |
| acceptable_pdf  | 17   | clean 12 / 部分 5   |
| best_effort_pdf | 1    | partial             |
| dirty_pdf       | 2    | clean 1 / partial 1 |
| reject-sig      | 3    | clean 2 / partial 1 |
| unfixable       | 3    | fail                |

## 4. 失败归因

### 4.1 compile fail 21 篇：off-CTAN 绝版件为主体

17/21 是期刊私有或废弃宏包，按年代 - 学科聚类：

| 年代      | 学科         | 缺件                                           |
| --------- | ------------ | ---------------------------------------------- |
| 2001-2004 | 物理邻域 ×11 | aastex×4, espcrc2×3, psfig×2, isolatin1, fic-l |
| 2009-2011 | 物理/数学 ×6 | iopart×2, aastex, picins, diagrams, texsort    |
| 2014-2017 | 物理 ×4      | svjour, jheppub, PoS, missing_graphic          |
| 2023      | cs ×1        | musicography（TL 内可装，非孤儿件）            |
| 2025      | other ×1     | syntax（非缺件）                               |

这批缺件里 vendor 库已备 11 种（aastex/iopart/psfig/lgrenc 真件，espcrc2/jheppub/diagrams/texsort 替身，svjour/revtex 桥接）；真孤儿仅 picins.sty、PoS.cls、fic-l.cls、isolatin1.sty 四种——既不在 TeX Live tlpdb 也未备 vendor。fixloop unfixable 3 格全在这四件上。

### 4.2 base 臂 fail 29 + error 18

fail 主签名：`missing_file:revtex.cls`×8（REVTeX 3.1 绝版，vendor 已有桥接件但 base 臂无修复环）、missing_chars warn、syntax、pdftex_prim、undefined_cs 散件。error 18 全部是湖格 unfetchable（extracted 层缺席，hydrate 可救）。

### 4.3 xlat partial 40 / reject 26

partial 按故障块数分级（partial=1~10 不等，译文主体交付）；reject 26 = route 死 19 + oversize 1 + 块故障死 6，全部上游链断非翻译质量问题。

## 5. 付费账

xlat 是唯一付费段。网关账本（key `1edae453`，api `openai-chat`，两跑合并窗）：5,976 次调用，输入 10.35M tok（缓存读 21k），输出 2.62M tok，折合约 $36.7。单篇均摊 ≈59k in / 15k out / $0.19。

## 6. 口径注记

- 全部数字为 rn=1 逐 (idc,stage) 末态取新、dedup 行还原为所复用终态的合并口径；`lost` 墓碑行不入账。
- layoutqc 199/200:2111.00241 一格 executor error 未落终态，属 harness 级缺口非测量结果。
- fixloop reject 与 xlat reject 均是结构化 decline（闸内判定），统计失败率时不计入分子。

## 7. 本帧覆盖不了的问题

- **新 CS 论文**：帧内 e_2021_25|cs 14 篇，不足以下判决。需要专项帧——`manifest_dev_recent` 的 cs 组现有 618 篇可供分层抽样，跑同一条链即可直接对比。
- **孤儿件补齐**：picins/PoS/fic-l/isolatin1 四件补进 vendor 后，unfixable 3 格可回收。
- **湖缺源**：base 臂 18 格 unfetchable + xlat 侧同因死者，走 hydrate 管线补 extracted 层可救。
