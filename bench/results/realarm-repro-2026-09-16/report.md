# realarm-repro — e2e-real-n100-postcutover 基线 12 格退化分类 + 修复预测

> 2026-09-16。基线 `bench/results/e2e-real-n100-postcutover-2026-09-16/`（pre-f5da4bf/90aa823）13 格 pipe-xel 退化中除 2203.13109（=F2 已诊）外 12 格。判据：f5da4bf = 展开组副作用 literal 回退 + \text 族参数跳扫；90aa823 = `_cat_surf` cs+text 融合修复（仅 group 路径）+ BOUNDARY_TAIL/`$$` 修复。
> 配套：`bench/results/repro-2410b-2026-09-16/report.md`（Mode-B 内容通道逃逸）；预测表供 real-postfix 复扫 diff。

## 每格签名 + 机理 + 预测

| id | signature | mechanism | prediction | cluster |
|---|---|---|---|---|
| 0707.3950 | partial, 40 err, 60 miss, first main.tex:102 `\spacefactor` in vmode | 用户 \makeatletter 重定义 \section（含 \@startsection）被展开 → 字面 @-cs 泄漏，@ catcode=12 回读即炸 | **predicted-fixed (f5da4bf)**；HEAD 已验证 \section 保 literal | C |
| 0905.4907 | partial, 4 err, 92 miss, Missing $ | LLM 把原文纯单词 "alpha emitters"/"alphas" 译成 caption 内裸 `\alpha` → Missing $ ×4 | **needs-new-fix**：纯翻译内容损伤；可 fixloop 规则（text-mode 裸希腊字母 cs 包 $）或 prompt 侧 | E |
| 1012.1321 | partial, 3 err, undefined_cs | `\item`+latin 首字母翻译融合 `\itemFSU` ×2；源 `\item FSU` 分隔空格被 tokenize 吸收 | **needs-new-fix**：主路径 cs+chunk 边界融合，90aa823 只修 group 路径 | B |
| 1206.1808 | partial, 2 err, undefined_cs | `\par`+`i)`→`\pari`、`\par`+`ii)`→`\parii`；源 `\par%` 注释分隔 | **needs-new-fix**：同 B | B |
| 1511.02908 | partial, 42 err, undefined_cs | 数学 ph 体内 `\dd r`→`\ddr`、`\frac k`→`\frack` ×42；用户宏 \dd | **predicted-fixed (90aa823)**；HEAD parse_file 验证 `\dd r` 空格保留 | A |
| 2003.10959 | partial, 1 err | `\itemNGA` | **needs-new-fix**：B | B |
| 2105.03900 | partial, 2 err | `\itemBalakrishnan`（次 err `\item 针` 连带） | **needs-new-fix**：B | B |
| math/0307301 | partial, 1 err | `\itemFlop` | **needs-new-fix**：B | B |
| cond-mat/0307508 | partial, **0 err / 4379 miss** 全 lmroman10 | elsart3×xeCJK 全局杀伤，见下 | **needs-new-fix**：class×xeCJK 交互 | G |
| hep-ph/9703228 | reject latex209 | 真 \documentstyle；inject.py:283 InjectRejectError("latex209") 有意策略 | **needs-new-fix (policy)**：非缺陷 | F |
| hep-ph/9910403 | **fail no_pdf**, 4 err | (1) `{\rm and}`→`{\rmand}` group 融合 → 90aa823；(2) `\abstract{…}` 展开毁 → 闭合括号丢失 → runaway `\@iiiparbox` no_pdf → f5da4bf 回退覆盖；HEAD 验证 `\abstract`→`[[EXPAND_29]]` literal | **predicted-fixed (f5da4bf+90aa823)** | A+D |
| math/0111203 | reject latex209 | 同上（linking.tex \documentstyle） | **needs-new-fix (policy)** | F |

## 聚类

- **A. group 路径 cs+latin 融合 → 90aa823 已修**：1511.02908 全量、hep-ph/9910403 `\rmand` 部分。`{…\rm and…}` 组内 `\rm` 后空格 tokenize 被吞，`_grp_surfs`/`_cat_surf` 拼接不回补。
- **B. 主路径 cs+chunk/latin 融合 → 未修复（新 bug 类 1，5 格）**：1012.1321 / 1206.1808 / 2003.10959 / 2105.03900 / math/0307301。`\item FSU`/`\par i)` 中 cs 后空格被吞后主循环 piece/chunk 边界直接贴上后续 token。`letters_cut`（segmenter.py:510-518）只告警不修复；reconstruct.py:34 `cjk_glue_fix` 只救 cs+CJK，这批全是 latin 首字母救不到。**复扫预期仍 partial/undefined_cs。**
- **C. @-cs 泄漏 → f5da4bf 已修**：0707.3950。
- **D. 展开组毁参数边界 → f5da4bf 已修**：hep-ph/9910403 runaway 半支。
- **E. LLM 内容损伤**：0905.4907 裸 `\alpha` 进 text mode——fixloop/prompt 层面。
- **F. latex209 策略拒**：hep-ph/9703228、math/0111203——有意 reject，非 bug。
- **G. elsart3 `\proc@elem` 测盒 × `\protect` 污染 → xeCJK 全局绑定崩坏（新 bug 类 2）**：cond-mat/0307508。

## cond-mat/0307508 机理深挖（二分定位到具体行）

签名：0 编译错、4379 missing、全部 "There is no X in font [lmroman10-regular]"——整个 zh 文档 CJK 全蒸发。

链条：
1. zh Rio.tex:59 `\title{欠掺杂铜氧化物中的赝能隙与竞争态}`（\documentclass{elsart3}, frontmatter 内）。
2. elsart.cls:1017 `\title` → `\proc@elem{title}{#1}`（:843）：先 `\no@harm`（:832），再 `\setbox\@tempboxa\hbox{#2}`（:850）——丢弃用测量 hbox 把元素文本先排一遍。
3. `\no@harm` 的 `:841 \def\protect{\noexpand\protect\noexpand}` 是毒源：hbox 里第一个 CJK 字符触发 xeCJK interchartok 字体切换时 `\protect` 处于 edef 形态 → CJK family→font 绑定被算出坏值并**全局缓存** → 之后全文档所有 CJK 全走 lmroman10。`\XeTeXinterchartokenstate` 保持 1——机制仍开，绑定被毒化。

二分证据（/tmp/cmrepro，elsart.cls+ctex）：

- 基线 fm+\title{CJK}：17 miss；**删 `\setbox\@tempboxa\hbox{#2}` 一行 → 0 miss（完全修复）**
- `\title{CJK}` 单独、无 frontmatter：17 miss——frontmatter 非必要条件
- 最小复现：`\begingroup\def\protect{\noexpand\protect\noexpand}\setbox0=\hbox{欠}\endgroup` 后正文 CJK 全灭（article+ctex 同炸，非 elsart 特有）
- `\no@harm` 逐个拆 `\let`：`\rm`、`\\`、`\i/\j`、`\o/\ae/\l/\aa/\ss`、`\d/\b/\c/\bar` 单独均不炸——只有 `\protect` 重定义是必要充分条件
- 真实日志吻合：Rio.log:421 首个 missing 即标题首字「欠」lmroman10——文档第一个被排版 CJK 就在毒盒里

影响面：elsart/elsart3 所有走 `\proc@elem` 的元素（\title/\subtitle/\author/\collab/\address）任一含 CJK 即杀全篇。机制是通用 xeCJK 陷阱（任何 cls/sty 做 `\def\protect{\noexpand\protect\noexpand}`+同组盒内排 CJK 都踩）。修复候选：inject/normalize 对 elsart* cls 补丁（中和 `\proc@elem` 测量盒，已验证 0 miss；或修 `\no@harm` 的 \protect 定义），或 fixloop 规则按 elsart+mass-missing 签名命中。

## 预测-验证对照表（real-postfix 复扫 diff 用）

- predicted-fixed（3 格）：0707.3950（f5da4bf）、1511.02908（90aa823）、hep-ph/9910403（两 commit 合力）
- needs-new-fix（9 格）：1012.1321 / 1206.1808 / 2003.10959 / 2105.03900 / math/0307301（B 簇）、0905.4907（E）、cond-mat/0307508（G）、hep-ph/9703228 + math/0111203（F 策略拒）

工件：二分复现脚本 /tmp/cmrepro/t9–t24.tex（elsart.cls 已拷入）；各 zh 树与日志在 bench/work_e2ereal/pipe-xel/{safe_id}/。
