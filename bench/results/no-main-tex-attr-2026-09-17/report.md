# no_main_tex×75 + BrokenProcessPool×4 parse 复验归因（texlate-2f）

> 口径：parse.jsonl 末条 status=reject（全 75 格 errors.code=no_main_tex）+
> status=error（全 4 格 harness:BrokenProcessPool）。复验跑在 `7f20897`
> （find_main_tex 传递正文质量加权）+ `3c2b030` 之后。
> 方法：`stagerun.py parse --dir bench/results/stagerun-loop1-2026-09-16
> --rerun --ids <79格>` + 逐格 src 布局解剖（dc/bd 出现位置、注释/verbatim
> 遮蔽、行尾符、文件指纹）。

## 0. 结论速览

- **`7f20897` 对本池回收 = 0/75**。该 commit 修的是「多候选排序」（standalone
  图档 vs 真 main，1803.02985 E 桶）；本池全是**零候选**问题——没有文件同时
  满足 `\documentclass`∧`\begin{document}` 字面双检——性质不同不矛盾。
- **BrokenProcessPool ×4 → 3/4 转 ok**（0806.2953/2410.00035/2410.17973，
  瞬时池崩，非确定性伤）；2410.17952 报告截稿时仍 error/in-flight。
- **75 格逐格归因**：fixable-detect **12 格**（三个检测层缺口）/
  upstream-wontfix **63 格**（plain-TeX 28 + latex209 22 + 上游垃圾 13）。
- 检测逻辑改动归 1d——本报告只出归因 + 三个提案（§3）。

## 1. 族群分解（75 格）

| 族 | 格数 | 裁定 | 说明 |
|---|---|---|---|
| plain-TeX / AMS-TeX（无 \documentclass 设计） | 28 | upstream | `\magnification`/`harvmac`/`phyzzx`/`amstex`/`epsf` 指纹；xelatex 路由下本不可编——拒绝正确，计 wontfix |
| latex209 `\documentstyle`+裸 `\document` | 22 | upstream | amsppt 族 `…\endtopmatter \document`；route 应归 209 池（与 414 wontfix 同类），no_main_tex 票面掩盖了真实归类 |
| 上游垃圾/真无 driver | 13 | upstream | 见下表 |
| `.TEX` 大写扩展名不可见 | 6 | fixable-detect A | `rglob("*.tex")` 大小写敏感；文件内 dc+bd 俱全 |
| bd/dc 在 `\input` 闭包内 | 4 | fixable-detect B | 编排壳模式：main 有 dc、`\input` 来的文件带 bd（或反） |
| CR/混合 EOL 注释罩死 bd | 2 | fixable-detect C | `%` 注释 masker 只认 `\n`，CR 行尾下注释吞到 EOF |

### 1.1 fixable-detect 明细（12 格 = 可回收池）

| id | 族 | 现场 |
|---|---|---|
| 0806.0433 | A | `EnumerationsforPermutationsbyCircularDescentSets.TEX` dc+bd 俱全 |
| 0806.2109 | A | `lt25CMv7.TEX`（jpconf.cls 同包在 src）dc+bd |
| 0806.3179 | A | `Nb_proceedingsLT25.TEX` dc+bd |
| 1706.00193 | A | `MgO_ElectroNuclearV2.TEX` dc+bd |
| 1109.2086 | A | `PPEFULL.TEX` dc+bd（含 plain 片段，可编译面待验） |
| physics/0104031 | A | `d-suppression.TEX` dc+bd |
| 2105.00092 | B | `main.tex:2 \documentclass{elsarticle}` + `:3 \input{begin}`，bd 在 begin.tex；`:5` 还 `\renewcommand\documentclass` 自中和（下游 dc 行失效是上游设计） |
| cs/0408015 | B | `main.tex:1 \documentclass{tacmconf}` + `:18 \input{body}`，bd 在 body.tex:11 |
| 0905.2435 | B | `body.tex:90 \begin{document}` + `:88 \input seki-deckblatt-3`（dc 在 deckblatt:156）——dc 由 preamble input 传递供给 |
| 0905.4369 | B | 同上构型（body.tex:29 bd / :28 input deckblatt） |
| 1608.02631 | C | `wdlf_arxiv.tex` **CR-only 行尾**——`% My own macros` 注释吞至 EOF，bd 被罩 |
| gr-qc/0605005 | C | `ZM00A.009.tex` 混合 EOL——`\def\sign…% sign function\r\begin{document}`，`\r` 后 bd 被罩 |

### 1.2 upstream-wontfix 明细（63 格）

**上游垃圾 ×13**：0707.1206（59B 撤稿 stub）· 1003.1741/1206.0603/cs/0501042
（仅章节残片无 driver）· 1404.0414/2308.04228（**HTML 伪装 .tex**，EPTCS/ISCS
proceedings 网页）· cs/0408036/cs/0408069（二进制乱码）· math/9901156/
math/9901159（**DVI 伪装 .tex**，`TeX output 1999.01.15` 签名实锤）·
0707.2108（仅 .pstex/.eps 无正文）· 1502.06414（index+preprint bundle 档，
bd 全在注释内）· 1803.03221（.TEX 但 documentstyle+plain，case 修复亦不治）。

**latex209 ×22**：1012.1026 1608.02223 1706.02389 1803.02892 1803.09100
1907.10317 cond-mat/0408247 hep-th/9901029 math-ph/9910014 math/0104013
0104049 0104096 0104117 0104155 0111107 0111109 0111238 0408252 0408373
0501455 9910113 nlin/0104020——全 `\documentstyle`+裸 `\document`（amsppt
顶物族），拒绝正确；建议错误码细分记 `latex209` 而非 no_main_tex。

**plain-TeX ×28**：0905.0581 1003.1273 1206.1737 1502.06120 2003.03567
2105.11374 astro-ph/0104142 astro-ph/0104295 astro-ph/9703094
astro-ph/9910247 cond-mat/9703084 gr-qc/9901068 hep-ph/9703202
hep-th/0104045 0104063 0307226 9703066 9703073 9901004 9901042 9901061
9901094 9910028 math/0104183 0104252 0111033 0408208 nlin/0104018——
`\magnification`/`\input harvmac`/`phyzzx`/amstex/jytex/mn.tex 指纹，
无 LaTeX 结构可译可注——拒绝正确（xetex-plain 路由不存，立不立归产品决策）。

## 2. BrokenProcessPool ×4

| id | 末态 | 裁定 |
|---|---|---|
| 0806.2953 | **ok** | 瞬时池崩，重跑归位 |
| 2410.00035 | **ok** | 同上 |
| 2410.17973 | **ok** | 同上 |
| 2410.17952 | error/in-flight（截稿时） | 预计同族瞬时伤 |

## 3. 提案（检测逻辑 → 1d，不直写）

**P-A `.tex` 枚举大小写**：`find_main_tex` 的 `root.rglob("*.tex")`
（inject.py:322）+ 下游一切同形枚举（normalize `_translate_tree` glob、
splice、`TEX_SOURCE_SUFFIXES`）统一改 suffix 大小写不敏感判定。
回收 ~6 格。**注意修一处不够**——zh arm 复制树后各层 glob 都按 `.tex` 走。

**P-B dc/bd 传递闭包判定**：候选资格从「单文件 dc∧bd 字面命中」扩为
「dc∧bd 在 {文件 ∪ preamble `\input` 闭包} 内命中」——`_resolve_input`/
闭包机制 `_body_mass` 已有，复用即可；main 取编排顶点文件。两向都要：
dc 可经 preamble-input 供给（seki 对），bd 可经 body-input 供给
（2105.00092/cs/0408015）。回收 4 格。

**P-C 注释 masker EOL**：`mask_comments`/`mask_tex` 的注释终止只找 `\n`，
CR/混合 EOL 下一个 `%` 吞到 EOF。修 EOL 判定（`\r\n|\r|\n`）或 decode_tex
先归一。回收 2 格，且是潜伏面 bug（全语料同形态都可能被罩）。

**P-D（可选）错误码细分**：no_main_tex 池里 63/75 是「正确拒绝的上游形态」
（plain/209/garbage），建议探测层顺手细分 `plain_tex`/`latex209`/`garbage`
码——票面从此能一眼分出「可修的检测缺口 vs 不可修的上游伤」，免下轮再解剖。

## 4. 复验记录

- `stagerun.py parse --rerun --ids <78>`：75 reject 格全部 append 新 record，
  verdict 不变（0 回收）；4 BPP 中 3 转 ok。
- 首跑 id 列表因 /tmp 拼接缺换行损失 `physics/0104031`+`0806.2953` 两格
  （合并成 `physics/01040310806.2953`→no_src skip）——已单独补跑归位。
- 对照函数实测：`find_main_tex` 对 7 个 dc/bd 俱全（raw）的 src 全返 NONE，
  逐一定位到 §1.1 三种遮蔽机理，无虚报。

## 5. 过门算术影响

75 格池实际可回收上限 **12 格**（P-A 6 + P-B 4 + P-C 2，需 1d 落地后复验）；
63 格是上游形态正确拒绝——本池对 union pdf 的贡献低于票面直觉，
90% 缺口的主力仍靠 corrosion 27 + fixable-data 18 两线。
