# partial-taxonomy — non-clean 2129 格缺陷聚类（质量战情报图）

> 2026-09-17 收口。只读侦察。底账 stagerun-loop1-2026-09-16。scratch+平铺表在 `tmp/partial-taxonomy/`（nonclean.jsonl 2129 行可直接切片复核）。

## 口径（源码钉死）

终态=compile(zh)末条 ∨ fixloop末条（白名单版 scorecard）；pdf=status∈{clean,partial}。judge：clean=有pdf∧错≤3∧首错类别∉DIRTY_FIRST∧warn红线零命中∧CJK≥20。分布：clean 2930(57.92%)/partial 1624/reject 414/skip 65/fail 26；pdf 4554(90.02% PASS)。

## ⚠️ 头等警告：账本大面积陈码

compile-end 非clean 1072 格中 code=NONE（前产码印章）908 格；`expect_cjk` 字段 973/1072 缺失。misschar 波次跑在 missing_char_fix+font_fallback 两规则落地前——**644 格 warn_missing_char 终态的 actions 只有 static_precheck**；后半夜 rerun 中 missing_char_fix 只 fire 16 次(6→clean)、font_fallback 7 次(4→clean)。**桶大小只能当上限——先 `--recode` 复活波再谈规则排期。**

## non-clean 分层

partial 1624（fixloop-end 1031=acceptable_pdf 677/best_effort 353 + compile-end 593）；reject 414 全 `inject:latex209`；skip 65（64=parse no_main_tex 下游影子+1 xlat-fail）；fail 26（early_eof 7/capacity 6/other 6/syntax 2/timeout 3 等）。

## partial 主桶（优先级 cjk→killed→first_error→warn→misschar→errors）

| 桶 | 格数 | 归属层 |
|---|---|---|
| E 缺字 | 581 | fixloop 已有规则未覆盖 + latex 臂数学泄漏 |
| F 纯错误洪峰(仅errors>3) | 451 | latex 臂为主 |
| C 首错 undefined_cs | 378 | splice/reconstruct + fixloop polyfill |
| D warn:invalid_utf8 | 128 | normalize 扩 recode 面（1e 车道） |
| A cjk 渲染失败 | 52 | 半数 stale 判词，半数真丢中文 |
| missing_graphic | 25 | fixloop graphic fallback/上游 |
| killed(SIGPIPE×6+SIGSEGV) | 7 | engine/沙箱 |
| FontAwesome/missing_file/散件 | ~20 | — |

**关键事实：451+593 个 compile-end partial 从没进过 fixloop**（fixloop 只跑过 --on fail 与 --on misschar）——illegal_unit/option_clash/already_def 等已有规则收益完全未知。

## E 缺字桶内部（422 纯 misschar 格逐字扫 log）

- 纯非CJK缺字 283：西里尔/组合符/Å±–┬Ł×——font_fallback 正为此设计，**rerun 即收**。
- 纯CJK缺字 120 两机制：(a) `Missing character ... in font cmr7/cmr10`——**中文进数学**：0707.1871 作者 `\bea...\eea` 宏别名未认成数学区，内容被切块翻译（`\Pi_这是译文`）——latex 臂用户宏数学环境保护缺口；(b) lmroman CJK——xeCJK 绑定污染，missing_char_fix 预热对 (a) 型无效。
- mixed 19。

## F 错误洪峰（451 纯桶）——译文进结构位实锤

zh 树直 grep：`\rule{0.9\columnwidth}{0.5这是译文}`（dimarg 形态 237 格 1950 处）、`\setcounter{这是译文}{0}`(15)、`\input 这是译文`、`/tikz/这是译文`、tabular 前导、`_这`/`^这` 357+146 格、`这是译文`贴`&` 504 格。洪峰格 362/451 的错误行本身含这是译文——**泄漏驱动是主流**（混原稿自带错 \hboxto/xcolor 色名）。

## C undefined_cs（378 主桶）

- **字体cs熔合族 ≥100 格**：`\emPhys \itJHK \scpin \bfB \rmeff \itProof \emcf \PARstart`——实证 1206.0481：`\def\PRD{{\em Phys. Rev.} D}` → zh `{\emPhys. 这是译文.}`——**宏展开后 reconstruct 把 `\em` 保护块尾随空格丢了**（splice/reconstruct 或 mouth 展开丢空白）。「已知字体cs+大写词」还原 regex 可整族收。
- **期刊/类宏缺位族**：`\csnamebibitemNoStop`(45)/`\corauth`/`\smartqed`/`\submitto`/`\eqnobysec`/`\maketitle`/`\end`(!)/`\DeclareUnicodeCharacter`(11)/`\hboxto`(15 作者笔误)/`\keywords`——cs_targeted_fix 扩表；`\end` 未定义暗示环境名参数被译。

## A cjk 桶（48）

12 格 stale 判词（pre-expect_cjk，recode 即翻 clean）；~20 真丢中文（泄漏+绑定污染终局）；4-5 格 chunks>0 但 cjk=0 且 miss=0（1206.0294/1803.02985/math.9901091/2105.00141——译文没落编译路径，逐格看 zh 树覆盖）；1 格口径分歧（1706.00217 fixloop clean vs post-judge cjk=0）。

## 非-pdf 桶

- reject 414 全是 stale：当前 upgrade_209 实测 **converted 399(96%)**（article 188/revtex 169/mn 26/amsart 5/aipproc 3/crckapb 3/elsart 2 等），仍拒 14（ds_at 9+no_target 5）。
- skip 65 重判：plain_tex 28 / latex209-amsppt 23 / garbage 10 / none 3 / 0905.4046 已能找 main。
- fail 26：early_eof 7 是 \typein 交互稿（typein_neutralize 规则存在但格跑在规则前）。

## 行动排序

0. **先行：`--recode` 全量复判 compile zh + `fixloop --on nonclean`**——~1000 格免费判词回收（latex209 399 + cjk-shell 12 + pre-rule misschar ~600），重测后桶排名才真。
1. **latex 臂结构位泄漏**（最大单机制，跨 E/F/C）：用户宏数学别名保护；dimarg/计数器/环境名/keyval/tikz路径/文件名/tabular前导 等 mandatory-arg 位禁切块；`\em`/`\it` 后空白保留。
2. misschar 复跑覆盖（~600 格未见规则，按已 fire 样本预期 40-50% clean）。
3. invalid_utf8：normalize recode 扩 `.sty/.cls/.def`（algorithm.sty L11/algorithm2e L284 集中）+ 二进 epsi 降 notes——144 格。
4. 期刊宏 polyfill + 字体cs还原 regex（~200 格合计）。
5. 散件：missing_graphic fallback(25)、FontAwesome(6)、SIGPIPE 引擎死因(6)、early_eof 复跑(7)。
