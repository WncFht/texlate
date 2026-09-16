# modec-postfix — n=80 Mode B/C 复跑（post-e7519ac 在飞覆盖层）

> 2026-09-16。对 modec-expand 基线的同种子复跑（seed-42 ids 逐一对账一致），验收面：dirty-gate + `_cover_gap` + CJK_FIRST_USE_WARMUP + DeclareUnicodeCharacter shim + eof_file 归因五项修复的合并效果。快照 `/tmp/texlate-src-modec-postfix` = worktree src/ @ 2026-09-16T12:12:41Z，code-state「worktree post-e7519ac + 在飞覆盖层」。

## 判决矩阵（base → new，clean/partial/fail）

| 臂 | baseline | postfix |
| --- | --- | --- |
| base-xel | 44/24/12 | 44/24/12（恒等） |
| pipe-xel | 54/24/2 | **65/12/3** |
| pipeB-xel | 56/21/3 | **67/10/3** |
| pipeC-xel | 47/31/2 | **59/18/3** |

管线引入非 clean（pipe non-clean ∧ base clean）：8/80 → **5/80**，全 partial 零 fail。

## Mode-B 台账（pipeB）

events 10102→10376，sabotaged 3123→3114（同确定性块集）；caught 2720→548、recovered 403→2566、**escaped 0、dirty 0**——门槛 `escaped==0 AND dirty==0` **PASS**。by_kind：fabricate 183c/1521r、drop 129c/586r、drop+fab 236c/459r。

caught→recovered 大挪移的归因（agent 高置信）：slots_fn 调用带 response_format → SabotageTranslator 返回未污染原文 → slots 救援恒产干净 zh；echo-guard 错误把块推向 ladder 深处触发 slots 救援，叠加 #94 COMMENT-ph 锚定修复让获救块通过锚定。dirty=0 部分结构性——guard 在 L0 拒掉 net-extra echo 后这些块根本到不了 `delivered`，`_dirty_hits` 只扫 delivered zh；残余武装通道 = src 自身合法含签名时的 raw containment（本次零发生）。

## 关键 verdict 迁移

- **2410.17957** pipeB fail→clean（预测命中：caught 7/recovered 38/escaped 0/dirty 0；基线 41c/4r fail early_eof）。pipeC 仍 partial undefined_cs:meth——与基线同 Mode-C 截断代价签名。
- **missing_char 簇**：0806.1984/0905.0795/1003.0112 三臂全 clean（mc→0）；0806.3144 partial mc=1、1706.00265 partial mc=3 残余与基线逐字一致——字体兜底未覆盖的末字形。
- **1306.0067**（基线簇 #4，tabular col-spec `Extra \or` 三臂确定性 fail）：pipe fail→clean、pipeB fail→clean、pipeC fail→partial(undefined_cs:noin)——`_cover_gap` 修复实证。
- **1404.0275** aux-trunc 仍 partial（`\@LN@` 扫描 EOF 残留，pipeB 臂 partial→clean）。
- 其余 partial→clean 升级：0707.1871、1306.0068、1206.0526(C)、2403.05542(C)、2410.00019、2410.00059、astro-ph/9901302、hep-ph/9703322、hep-th/9901062。

## Mode-C 台账（pipeC）

moved 5368→5428、spliced 2822→2889、dropped 82→**12**（splice 覆盖率提升）。存活率 77/77=100%。clean→partial 退化 6 篇（基线 7）：1206.0197、1206.0358、1306.0067、2211.04436、2308.12593、2410.17957；1206.0526 与 2403.05542 回升 clean。

## 新败签名：revtex4-2 + multicol opt clash

cond-mat/9901156、cond-mat/9901347：三 pipe 臂 partial(latex209 inject-reject) → **fail(early_eof)**。first_error=`Class revtex4-2 Error: The multicol package cannot be used with revtex4-2.`，fixloop 无规则。latex209 upgrader 把 `\documentstyle[...multicol...]{revtex}` 升级 revtex4-2 但 multicol 留在 pkg_opts → class 级致命。修法=升级目标 revtex4-2 时剥 multicol（顺带审计 epsf/epsfig 兼容）——已转 1d。

upgrade209 普查（8 转化）：3 个 base-fail→clean（astro-ph/9901302、hep-ph/9703322、hep-th/9901062——管线反超源码）、3 partial（astro-ph/9901044、hep-ph/0104029 undefined_cs:abstract ×71err、hep-th/0408064）、2 fail（cond-mat 对）。1404.0527 仍 latex209_ds_at reject（不同 209 风味）。定性：诚实编译尝试替换人造 inject-reject partial——覆盖率缺口，非 sabotage-gate 回归；两篇 base-xel 本就 fail。

## 不变项

1306.0302 fail missing_file（JINST.cls 缺席，真缺）；fault_files=∅、leftover_ph=0 全臂双跑。

## 产物

`records.jsonl`（80）/ `results.json` / `matrix.md` / `summary.md` / `sample.json` / `run.log` / `diff-vs-modec-expand.txt` / `snapshot-manifest.txt`。
