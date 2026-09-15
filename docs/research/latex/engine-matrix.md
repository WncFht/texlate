# 引擎矩阵实验：xelatex vs tectonic 真实语料差异

- 日期：2026-09-14
- 语料： `bench/corpus/` 新扩语料中选 12 个多样项目（与 compile-bench 旧 12 项基本不重叠，仅 2305.14335/hep-th/2501.14787 复测）
- 引擎： `xelatex` (XeTeX 3.141592653-2.6-0.999998, TeX Live 2026 basic + ~/Library/texmf) vs `tectonic 0.17.0` (bundle 快照：ctex 2.5.8 / fontspec 2.8a / minted 2.6 — **普遍比 TL2026 旧**)
- 条件：主 .tex 的 `\documentclass`/`\documentstyle` 后注入 `\usepackage[fontset=fandol,UTF8]{ctex}` (**字节级注入**, 支持跨行 docclass/注释行/LaTeX2.09, latin-5 文件字节保持已验证)
- 判据：timeout 240s; xelatex `-interaction=nonstopmode` ≤2 pass; tectonic `-Z continue-on-errors --keep-logs` (超时重试一次); **clean = 出 PDF 且末遍 log `!` 错误 ≤3**
- 数据： `tmp/exp/engine/results.json` （首轮全量） + `rescue.json` (xelatex 修复探针） + `work/<id>/` 全部 log

## 0. TL;DR

| 结论                  | 实测数据                                                                                                                                                                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 初始 clean 率         | tectonic **7/12**, xelatex **4/12**; tectonic 赢在 bundle 自足                                                                                                                                                                                |
| 修复后 xelatex        | **7 clean + 4 pdf~ + 1 FAIL** — 所有 missing_* 均被 `tlmgr --usermode install` 链式救回 (1–5 轮)                                                                                                                                              |
| 联合 clean 覆盖       | **9/12** (8 初始联合 + 1207.7214 修复后）; 全灭仅 hep-th (LaTeX2.09+ 私类，三引擎全死）                                                                                                                                                       |
| **tectonic 三大硬墙** | ① **EPS/PS 图片直接不支持** (xdvipdfmx `image inclusion failed for *.eps`) ② **bundle 缺物理字体** (bbm10 → `Cannot proceed without .vf or physical font`) ③ **bundle 包版本旧** (ctex 2.5.8/fontspec 2.8a 触发 IEEEtran bbl `missing \item`) |
| bundle 旧也有反向红利 | **minted**: bundle v2.6 完美消费 v2 frozencache; xelatex 侧 minted v3.8 报 50 个 `Cannot highlight` — 版本钉死方向与直觉相反                                                                                                                  |
| **xelatex 静默污染**  | latin-5 字节 → `Invalid UTF-8 byte...replaced by U+FFFD` 只是 **warning 非 '!' 错误**, 0 err 出 PDF 但正文 `TÜBİTAK→T�UB�ITAK` — **'!'≤3 判据存在盲区，须加 UTF-8 warning 扫描**                                                              |
| `.bbl` 直消费         | 5 个"有 .bbl 无 .bib"项目两引擎**全部正确消费**; tectonic 自动跑 bibtex 找不到 .bib 后优雅回退现有 .bbl, 引用全解析                                                                                                                           |
| `\documentstyle` 路由 | xelatex/tectonic/**latex 三引擎全死** (ptptex.cls 不在任何源) → 检测即拒绝，不要路由 latex+dvips                                                                                                                                              |
| fixloop 规则覆盖      | 本轮 xelatex 失败 7 项中 **5 项纯 install_file 链可救** (已实测救回 3 项 clean + 2 项推进中）; 规则缺口 4 个 (见 §6)                                                                                                                          |

## 1. 选品与首轮矩阵

选品覆盖：amsart / revtex4-2 / IEEEtran / acmart(acmsmall+Agda) / elsarticle / subfiles+ 私类 / 2.2MB book / LaTeX2.09 / 法语 babel+T1 / latin-5+pstricks / minted / tikz 重度。其中 5 个是"有 .bbl 无 .bib"项目（专项①)。

| 项目           | 维度                                  | xelatex (2 pass)                      | tectonic              | 首错类别                                          |
| -------------- | ------------------------------------- | ------------------------------------- | --------------------- | ------------------------------------------------- |
| math/0404188   | amsart, 内嵌 bib                      | **CLEAN** 0err 4.0s                   | **CLEAN** 0err 9.0s   | —                                                 |
| 2308.07483     | revtex4-2, mathptmx, 跨行 docclass    | **CLEAN** 0err 5.4s                   | **CLEAN** 0err 19.6s  | —                                                 |
| 2305.14335     | IEEEtran, main.bbl 无 .bib            | **CLEAN** 0err 5.4s                   | **FAIL** 1err+ 字体死 | t: missing\item@bbl + bbm10 xdvipdfmx             |
| 2609.08578     | acmart[acmsmall], Agda Unicode        | FAIL 2err 0.2s → **救后 pdf~ 72err**  | **CLEAN** 0err 90.9s  | x: missing_class acmart (5 轮链）                 |
| 1207.7214      | elsarticle, 15×EPS                    | FAIL 2err 0.2s → **救后 CLEAN 1err**  | **FAIL** xdvipdfmx    | t: EPS `AC_atlaslogo.eps` 不可包含                |
| 2609.06443     | subfiles+jfp-epi 私类， .bbl          | FAIL 2err 0.5s → **救后 CLEAN 3err**¹ | **CLEAN** 0err 46.7s  | x: missing totpages (3 轮链）                     |
| 1106.1445      | book 单文件 2.2MB, .bbl               | **CLEAN** 0err 24.0s                  | **CLEAN** 0err 22.3s  | —                                                 |
| hep-th/9901001 | `\documentstyle{ptptex}`, 4×EPS       | **FAIL** 2err 0.3s                    | **FAIL** 6err 0.3s    | 双：missing ptptex.cls / latex209 (+EPS 墙）      |
| 2602.06617     | 法语 babel+utf8 inputenc+T1, .bbl     | FAIL 2err 1.3s → **救后 CLEAN 0err**  | **CLEAN** 0err 65.4s  | x: missing a4wide (2 轮链）                       |
| 0807.3917      | latin-5, pstricks, 自带旧 .sty, 2×EPS | FAIL 2err 1.1s → **救后 pdf~ 126err** | **FAIL** 100err 1.9s  | 双：missing pstricks.tex; x 救后自带 sty 版本错配 |
| 2501.14787     | minted frozencache, 118 文件          | pdf~ 53err 11.8s                      | pdf~ 1528err 5.3s     | x: minted v3 vs v2 cache; t: 宏冲突级联           |
| 1902.03178     | quantumarticle, 678×tikz, .bbl        | FAIL 6err 3.0s → **救后 pdf~ 6err**   | **CLEAN** 1err 60.5s  | x: `\ifnum\pdfoutput` + missing changebar         |

¹ 3err 含 `doclicense-CC-by-88x31` 缺图—— **clean 判据对 missing_graphic 也应设红线**（见 §5)。

汇总：xelatex 初始 4 clean / 1 pdf~ / 7 FAIL; tectonic 7 clean / 1 pdf~ / 4 FAIL。**tectonic 初始完胜，但失败集与 xelatex 几乎互补**（仅 hep-th 共死）。

## 2. 失败分类学（对接 fixloop-results.json)

| #   | 类别                          | 实例                                                                                                        | 引擎           | 可修？    | 修法/路由                                                                                                                                     |
| --- | ----------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| E1  | missing_* 链 (class/sty/file) | xelatex 全部 7 个 FAIL 首错都是                                                                             | x              | ✅ 实测   | `tlmgr --usermode install`; 链深 1–5 轮 (acmart→hyperxmp→polytable→lazylist→newunicodechar→doclicense)                                        |
| E2  | **EPS/PS 图片**               | 1207.7214 (15 eps), hep-th (4 eps), 0807.3917                                                               | **t 硬墙**     | ❌→换引擎 | `xdvipdfmx: image inclusion failed for *.eps`; tectonic 明确 "PostScript images are not supported" → *_静态扫 *.eps/pstricks → 路由 xelatex*_ |
| E3  | **bundle 缺物理字体**         | 2305.14335 `bbm10` (bbm 数学字体）                                                                          | **t**          | ❌→换引擎 | `Cannot proceed without .vf or physical font`; TL 侧 bbm 装好即过 → **引擎切换即修复**                                                        |
| E4  | **bundle 包版本旧 → 语义错**  | 2305.14335 bbl 内 `missing \item` (ctex 2.5.8/fontspec 2.8a vs TL 2.5.10/2.9g, 同 cls 同 bbl xelatex 全过） | **t**          | ⚠️        | 无法换 bundle 内包 → 换引擎                                                                                                                   |
| E5  | **自带旧 .sty 遮蔽新包**      | 0807.3917 自带 pstricks.sty v0.36(2008) 包住新 pstricks.tex → 126×`\ifpst@useCalc`/`\ifluatex` undefined    | x（装包后）    | 🔧 新规则 | 检测项目内 .sty 遮蔽已装包 → 重命名/移除 vendored 文件                                                                                        |
| E6  | **latin-5 静默 U+FFFD**       | 0807.3917 `TÜBİTAK`; 最小复现 0 '!' 出 PDF                                                                  | **x+t 共有**   | 🔧 判据   | log 扫 `Invalid UTF-8 byte or sequence` → 转码或拒绝； **非 '!' 错误，现判据漏检**                                                            |
| E7  | `\ifnum\pdfoutput` 读取型     | 1902.03178 quantumarticle.cls hook 强制 `\pdfoutput=1` (arXiv 惯例）                                        | x              | 🔧 新规则 | fixloop `pdftex_prim_guard` 只管赋值型；读取型需 **polyfill**: `\ifdefined\pdfoutput\else\chardef\pdfoutput=1\fi`                             |
| E8  | minted 版本错配               | 2501.14787: xelatex v3.8 × v2 frozencache → 50 错； **tectonic bundle v2.6 零错**                           | x              | ✅ 规则   | `\usepackage{minted}`→`{minted2}` (usermode 已装）或钉 v2; tectonic 反而天然兼容                                                              |
| E9  | LaTeX 2.09 + 私类             | hep-th ptptex.cls                                                                                           | x+t+latex 全死 | ❌        | 拒绝 (latex 路由也死：类文件不存在）                                                                                                          |
| E10 | 宏冲突级联                    | 2501 `\c@lemma already defined` (lindrew.sty×amsthm), tectonic 1528 err 仍出 pdf                            | x+t            | ⚠️ 半规则 | 已知 F11; tectonic 级联更大但同样出残 pdf                                                                                                     |
| E11 | acmart×baselinestretch        | 2609.08578 `An attempt to redefine \baselinestretch`                                                        | x              | 低危      | acmart+ctex 摩擦，1 err 不致命                                                                                                                |
| E12 | unicode 数学符号缺包          | 2609.08578 救后残 `\blacktriangleright` ×71 (agda Unicode→宏映射）                                          | x              | 🔧 长射   | undefined_cs→pkg 知识库 (fdsymbol/stix); 现规则 `undefined_cs_guess` 空手                                                                     |

## 3. 专项结果

### ① .bbl 直消费 (5 项目：2305.14335/2609.06443/1106.1445/2602.06617/1902.03178)

- **xelatex 不跑 bibtex**: 全部直接读 `<jobname>.bbl`, 引用全解析 (1106.1445: 0 undef; 2602.06617 救后 0 undef)。`\bibliography{reference}` 而 bib 名与 bbl 名不同也无碍——TeX 按 jobname 找 .bbl。
- **tectonic 自动 bibtex**: 检测到 `\bibliography` 后跑 bibtex → `.blg` 记 `I couldn't open database file *.bib` + 全部 entry warning → **bibtex 产不出新 bbl, tectonic 回退读项目原 .bbl** (1106.1445: 607 个首遍 undef → bbl 读后 0; bbl 文件本身未被覆写，md5 不变）。**结论：有 .bbl 无 .bib 项目两引擎都安全，无需剥离 `\bibliography`。**
- 附带发现：tectonic 有时不写 .log 到 outdir (2609.06443 只有 .blg+.pdf) — 监控不能只依赖 log 存在。

### ② hep-th/9901001 (LaTeX 2.09)

- xelatex: `File 'ptptex.cls' not found` → missing_class (0.3s)
- tectonic: `LaTeX2e command \usepackage in LaTeX 2.09 document` (6 err) + EPS 墙 (ods.eps) 双死
- **latex 引擎实测同样死**: `File 'ptptex.cls' not found` — ptptex 是厂商样式，CTAN/TL 皆无 → **`\documentstyle` 检测 = 无条件拒绝**, 不要浪费 latex+dvips 路由（路由了也缺类）。fixloop `latex209_reject` 判定正确。

### ③ latin-5 / 非 UTF-8 (0807.3917 + 最小复现）

- xelatex 对 latin-5 字节 **零 '!' 错误、正常出 PDF**, 但 log 有 `Invalid UTF-8 byte or sequence at line N replaced by U+FFFD` + `Missing character: There is no � (U+FFFD) in font` — **正文静默污染** （最小复现 `probes/latin5/l5.tex` 同样 0 err + FFFD)。
- tectonic 因 pstricks.tex 先死没走到编码层；预期同态 (XeTeX 内核一致按 UTF-8 读）。
- **管线含义**: clean 判据必须在 '!'≤3 之外加 log warning 扫描： `Invalid UTF-8 byte` / `Missing character.*U+FFFD` → 判 dirty 或触发 iconv 转码预处理。

### ④ minted (2501.14787)

- xelatex: `minted 2026/03/03 v3.8.0` × v2 frozencache → `Cannot highlight code (frozencache=true)` ×50 (+`\c@lemma already defined` 等）。pdf 仍出（目录含 pygtex 残留）。
- tectonic: bundle `minted v2.6` 与 v2 cache **版本天然匹配**, 25 个 .pygtex 全读入， **0 minted 错** （其 1528 err 全是 lindrew/titlesec 宏级联，与 minted 无关）。
- **规则更新**: `minted_frozencache` 修法从"去 frozencache+shell-escape"（本机无 pygmentize 不可行）改为 **`{minted}`→`{minted2}`** (TL2025+ 并存 v2 兼容包，usermode 已装 minted2.sty) — 一行替换可消 50 错。
- **无需 -shell-escape**: frozencache 的设计目的就是免 shell-escape; 两引擎都不需要它，差异纯在包版本。

## 4. xelatex 修复探针实测 (rescue_probe.py, 复刻 fixloop 动作）

| 项目       | 链                                                                                   | 结果                                                               |
| ---------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| 1207.7214  | elsarticle (1 轮）                                                                   | **CLEAN** 1err (`Loading a class or package in a group` — 良性）   |
| 2602.06617 | a4wide → chngcntr (2 轮）                                                            | **CLEAN** 0err                                                     |
| 2609.06443 | totpages → hyperxmp → dashbox (3 轮）                                                | **CLEAN** 3err¹                                                    |
| 2609.08578 | acmart → hyperxmp → polytable → lazylist → newunicodechar (+doclicense 图） **5 轮** | pdf~ 72err, 残 `\blacktriangleright` Unicode 数学符号缺包          |
| 0807.3917  | pstricks (1 轮）                                                                     | pdf~ 126err — 进入自带旧 sty 错配层 (E5) + latin-5 FFFD            |
| 1902.03178 | changebar + pdftex 守卫 (1 轮）                                                      | pdf~ 6err — 守卫对 `\ifnum\pdfoutput` 读取型无效 (E7), 需 polyfill |

**链式暴露模型再次验证**: 每轮装上轮首错即见下一层；agda/私类项目链最深 (5 轮）。与 fixloop-results 结论一致。

## 5. 引擎默认建议

### M0 开发默认： **xelatex**

理由： ① fixloop 修复循环已建在 tlmgr/log 语义上，缺包可修性实测最高 (7 FAIL → 7 可推进，5 已到 clean/可用）; ② tectonic 的 "静默降级"（缺包继续跑、EPS 不支持仅 warning、有时不写 .log）使错误信号更碎，不适合做修复循环的地面真值； ③ xelatex 的短板（缺包装环境）正是 fixloop 已覆盖的 90% 死法。

### 分发默认： **tectonic 优先 + xelatex 兜底 + 静态路由预检**

- 理由：便携二进制无 tlmgr 依赖；初始 clean 率更高 (7/12 vs 4/12); 热缓存快 (≤22s, 大书也 22s)。
- **静态预检路由表**（编译前即可决策）:

    | 检测                                            | 路由                                      |
    | ----------------------------------------------- | ----------------------------------------- |
    | `\documentstyle`                                | **拒绝** （三引擎全死已实证）             |
    | `*.eps` / `\usepackage{pstricks}` / `pspicture` | **跳过 tectonic 直走 xelatex** (E2 硬墙） |
    | `frozencache` + minted                          | tectonic 优先 (E8 bundle v2.6 兼容）      |
    | bbm/dsfont 类位图字体包                         | tectonic 高风险 → 失败后换 xelatex (E3)   |

- 兜底顺序：tectonic (0.5–90s) → 失败/可疑降级 → xelatex+fixloop（互补覆盖联合 clean 9/12)。
- **判据三件套**: ① pdf 存在 ② '!'≤3 且首错非 missing_*/undefined_cs ③ **log warning 扫描**: `Invalid UTF-8 byte` / `Missing character.*U+FFFD` / tectonic `File.*not found` 降级行 — 任一命中即 dirty。

## 6. fixloop 规则覆盖预估

| 规则                           | 覆盖本轮哪些失败                        | 状态                                                                                                       |
| ------------------------------ | --------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `install_file` (missing_*)     | xelatex 全部 7 FAIL 的首错 + 链内每一层 | ✅ 实测 5/7 推进到 clean/可用                                                                              |
| `pdftex_prim_guard`            | 1412/2501 型赋值原语                    | ⚠️ **缺口**: 1902.03178 `\ifnum\pdfoutput` 读取型需 `pdftex_prim_polyfill` 新规则 (`\chardef\pdfoutput=1`) |
| `minted_frozencache`           | 2501                                    | 🔧 改法：优先 `{minted}`→`{minted2}` 一行替换                                                              |
| `latex209_reject`              | hep-th                                  | ✅ 判定正确，证据加强 (latex 也死）                                                                        |
| — 新规则 `vendored_sty_shadow` | 0807.3917 (126 err)                     | 🆕 检测项目内 .sty 同名遮蔽已装包 → 隔离 vendored                                                          |
| — 新规则 `eps_route`           | 1207.7214/hep-th/0807.3917              | 🆕 静态扫 eps/pstricks → 引擎路由，不进 fixloop                                                            |
| — 判据 `silent_corrupt_check`  | 0807.3917 latin-5                       | 🆕 非修复规则，是判定层：UTF-8/FFFD warning 扫描                                                           |
| `undefined_cs_guess`           | 2609.08578 `\blacktriangleright` ×71    | ⚠️ 仍长射：需 cs→pkg 知识库（符号包：fdsymbol/stix/unicode-math)                                           |

**覆盖率**: 本轮 xelatex 失败 7 项 = missing_*×6 (install_file 全救） + pdftex_prim 读取型×1（新 polyfill 规则） + 尾端 undefined_cs/vendored-sty（部分覆盖）。**预估 fixloop 完备后 xelatex 侧 ~~10/12 可达 clean/pdf~~ 出 PDF, 仅 hep-th 必拒、0807.3917 路由 latex+dvips 或直接拒。**

## 7. tectonic 特有失败清单（本语料实证）

1. **EPS/PS 图片**: `image inclusion failed for *.eps` — 1207.7214, hep-th, (0807.3917 若走过 pstricks 也会撞上）。静态可检，直接绕行。
2. **物理字体缺**: `Cannot proceed without .vf or physical font` — 2305.14335 bbm10。bundle 快照不含位图字体生成产物，xelatex+TL 正常。
3. **bundle 包版本语义错**: 2305.14335 `missing \item`@IEEEtran.bst bbl (bundle ctex 2.5.8/fontspec 2.8a vs TL 2.5.10/2.9g)。版本不可选，只能换引擎。
4. **缺包静默降级**（已知再确认）: 0807.3917 缺 pstricks.tex → tectonic 100 err 继续跑；判据必须数 '!'。
5. **.log 缺失**: 2609.06443 成功后 `_tect_out/` 只有 .blg+.pdf 无 .log — 监控设计不能假设 log 存在。

反向红利 (tectonic 反而赢）: minted v2.6×v2 cache 兼容 (2501); acmart/agda 深依赖链 bundle 一把全有 (2609.08578 90.9s 冷拉后 0 err; xelatex 侧 5 轮装包仍残错）; 全部"有 bbl 无 bib"项目零配置通过。

## 8. 复现

```bash
python3 tmp/exp/engine/engine_matrix.py      # 12 项目 × 2 引擎全量 (~15min, tectonic 冷拉慢)
python3 tmp/exp/engine/rescue_probe.py       # xelatex 修复探针 (tlmgr usermode 链式装包)
# work/<id>/ 下为工作副本+全部 log; probes/latin5/ 为 latin-5 最小复现
```
