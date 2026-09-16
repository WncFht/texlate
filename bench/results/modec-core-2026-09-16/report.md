# modec-core — core 层 n=80 seed=7 Mode B/C 门槛复证

> 2026-09-16。快照 `/tmp/texlate-src-modec-core`（post-`3443add` + 在飞覆盖层 @13:31:46Z；src/ 脏文件 rules.yaml/argspec.json/segmenter.py/tables.py）。产物：records.jsonl / results.json / matrix.md / summary.md / sample.json / snapshot-manifest.txt + run log `/tmp/modec-core-run.log`。工作区 `bench/work_e2emock/corpus_v3/{pipe-xel,pipeB-xel,pipeC-xel}/<id>/`。

## 门槛判决：PASS

Mode-B 台账（pipeB）：events 9386 / sabotaged 2797 → caught 549 / recovered 2248 / **escaped 0 / dirty 0 / armed 0（armed_zh 0）**。逐篇复核无非零。by_kind：fabricate 207c/1254r、drop 106c/535r、drop+fab 236c/459r。门槛 `escaped==0 AND dirty==0` 复证于第二层第二种子。

## verdict 矩阵（clean/partial/fail）

| 臂 | core n80s7 | （对照）postfix expand n80s42 |
| --- | --- | --- |
| base-xel | 48/22/10 | 44/24/12 |
| pipe-xel | 68/11/1 | 65/12/3 |
| pipeB-xel | 69/10/1 | 67/10/3 |
| pipeC-xel | 60/19/1 | 59/18/3 |

管线引入非 clean（任一 pipe 臂 non-clean ∧ base clean）：3 篇全 partial 零 fail——2003.10723（三臂 mc=1）、solv-int/9910006（pipe+pipeC mc=1，pipeB clean）、1206.2072（仅 pipeC undefined_cs:tex）。

Mode-C 台账（pipeC）：moved 5254 / 涉块 2808 → spliced 2791 / dropped 17；存活率 79/79=100%；verdict {clean 60, partial 19, fail 1}。

## 新败签名逐格归因

1. **Mode-C mid-cs 截断簇 ×8**（pipe clean→pipeC partial，全 undefined_cs）：0806.1498 `\e`、1012.1738 `\e`、1109.5364 `\te`、1206.2072 `\tex`、1907.10345 `\emp`、2009.03701 `\noi`、math-ph/0501022 `\noinden`、cs/0111043 `\e`、1706.02550 `\textb`。日志实证 splice 缝落在 cs 名中间（`\textbf`→`\te`+`xtbf{`）。与 postfix `meth/noin` **同族**——签名级复证，非 expand 层特有，是 Mode-C 主导代价（8/19 partials）。已并案转 1d（PH-in-cs-name L0 检查）。
2. **upgrade209 不存在目标类（新签名）**：cond-mat/0111097 `\documentstyle[epsfig,seceq,twocolumn]{jpsj}` → 改写 `\documentclass[…]{jpsj3}`，jpsj3.cls TL/随包皆无 → 三臂 missing_file fail；base 走 compat 载随包 jpsj.sty 得 partial。postfix revtex4-2+multicol 姊妹病：upgrade209 不校验目标类存在性（epsfig 已正确剥除）。partial→fail 劣化。转 1d。
3. **CJK 域泄漏型缺字（新签名）**：2003.10723 `这`(U+8FD9) 落 lmroman12 ×1（zh 逃出 CJK 字体域，页边界/走字类元素）；2410.17992 `这是译文` 落 lmsans17 ×20（quantumarticle \title 盒内）。与 postfix「末字形兜底」不同族——域泄漏非覆盖率缺口。转 1d（inject/font 域）。
4. **组合符缺字**：solv-int/9910006、1706.02550、1608.02685 U+0327 组合 cedilla 落 lmroman——accent 展开盲区同族（U+0332/00C5/0131 簇 +1）。solv-int pipeB clean 系 sabotage drop 抹掉载符块所致，非保真收益。转项目体验方式（规则面）。
5. **quantumarticle 类约束**：2410.17992 polyfill 后 class 拒 \title 内字体命令 ×2–3err + 签名 3 缺字。转项目体验方式。
6. **预存破损放大**：2009.11053 随包 mystyle.sty `Missing \begin{document}`（chngcntr/numberwithin 域）5err→35→74 随臂放大 +pipeC mc=1；astro-ph/0501080 `Use of \ doesn't match its definition` ×80（\author/\affil 字面 `\ ` 与注入前导冲突）+ FFFD + 罕见字缺字。
7. **clean 带疤**（status clean、rc=1、终 log 残 err、pdf 正常）三臂同疤：1003.1717 bbl Missing $、1206.5646 illegal_unit、1803.03106 `setup` not found、2003.03508 preamble-only、2003.03533 input stack 10000、2009.11002 \Bbbk 已定义、2211.13040 soul 重建失败；pipeC 独有：0905.4796 missing \item、1306.5977/1502.06013/1608.02550 Extra }/Missing $、1608.02331 `\@lbibitem`、2203.04383 Extra \endcsname——Mode-C 结构损伤低于 partial 阈的亚签名群。
8. **base-fail 回收 9/10**：missing cls/sty（jheppub/iopart/quantumarticle/aastex/slashbox/feynmp-auto/tcilatex）polyfill 4 clean 5 partial；inputenc_unicode ×2 → clean。残余：1907.03745 `undefined_cs:allowdisplaybreaks` ×8、2009.11125 `undefined_cs:eqnobysec` ×33（缺类桩后的下游 cs 真空）。

## 与 expand 层（postfix）签名级差异

- 门槛双 PASS、armed 通道双层零发生——dirty-gate 证据面扩展成功。
- Mode-C 截断签名复证（同族同机制），本层主导代价。
- 无 revtex4-2+multicol、无 early_eof、无 aux-trunc `\@LN@`、无 tabular Extra \or——postfix 签名簇本样本均未复现（无 revtex/209 高危源）。
- 新出签名：upgrade209 目标类不存在（jpsj3）、CJK 域泄漏缺字、组合变音符缺口、quantumarticle 类约束。
- 不变量双跑一致：leftover_ph=0、fault_files=∅ 全臂；无 timeout/kill。
