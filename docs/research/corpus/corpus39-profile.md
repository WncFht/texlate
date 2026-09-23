# Corpus Profile — bench/corpus/ 39 篇手挑语料机器级统计画像

> **结论**：39 篇手挑陷阱语料（2,819 文件 / ~107MB / 256 .tex）的机器级画像：LaTeX2e×38 + 2.09×1（ptptex hep-th/9901001）、多主文件 3 例（含 wrapper+\jobname 条件编译 1 例）、\input 最大深度 4 无环、裸 `\input file` 25 处全在 1502.01589、4 目录非 UTF-8（含主源孤立 0xa9 一例）、`.svn` 残留 736 文件一例、vendored 依赖 26/39——画像直接支撑 locate/flatten 模块的边界口径与陷阱 fixture 设计。
> **状态**：时点证据（2026-09-14 口径；v1 39 篇已并入统一物理根 `bench/corpus/` 作裸布局层）。MANIFEST 不一致清单（§8）仍是对照金标准。
> **日期**：2026-09-14

方法：逐行剥注释（奇数前导 `\` 的 `\%` 视为转义不剥）→ 全文 regex 提取 `\documentclass`/`\documentstyle` 与 `\input` 族；`\input` 解析按 **TeX 语义 = 相对编译 CWD（主文件目录）**，fallback 到 paper root → 当前文件目录。hyperref 等为静态检测（类内部 `\RequirePackage` 不可见，见 §9 注）。

## 1. documentclass / LaTeX 版本

- **LaTeX2e × 38，LaTeX2.09 × 1，plain/ConTeXt × 0。** 唯一 2.09：`hep-th/9901001` `\documentstyle[epsf,seceq,preprint]{ptptex}` → 路由 reject。
- `2308.07483` 的 documentclass 选项跨 11 行、5 个整行注释穿插——剥注释后正确抽出 `[aip,cp,amsmath,amssymb,reprint]{revtex4-2}`。
- 类分布：article ×11，amsart ×4，acmart ×4，IEEEtran/revtex/elsarticle 各 2–3，私类（cms-tdr/iopart/cambridge7A/eptcs/jfp-epi/quantumarticle/llncs/aastex61/aa/subfiles/ptptex）×12。

## 2. 多主文件

| 口径                                                      | 目录                                         | 说明                                                                                                                                                                             |
| --------------------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| docclass 文件数 >1                                        | 2201.05989(2)、2501.14787(5)、2609.06443(12) | —                                                                                                                                                                                |
| **独立根（排除 {subfiles} 类）>1**                        | **2201.05989、2501.14787**                   | 后者是 MANIFEST 未标注的新发现：main + psets/{Pset1,Pset1sol,Pset2,Pset2sol} 四个独立 article 根                                                                                 |
| wrapper root（无 docclass、全文仅一条 `\input` 指向真根） | **2609.08578**                               | `Paper-with-appendices.tex` = `\input{Paper.processed.tex}`，配合 `Setup.tex` 里 `\IfBeginWith*{\jobname}{Paper-with-appendices}` **按输出文件名切换内容**——同一源码两个编译入口 |

## 3. `\input` 拓扑

- 命令使用：`\input` 178（braced 153 + **裸 `\input file` 25 处，全部在 1502.01589**）、`\include` 16（1612.09375×14、2203.02155×2）、`\subfile` 11（2609.06443）、`\import`/`\includestandalone` 0。
- **最大深度**：1502.01589 = **4**（main → grid.tex → LCDM_result_table.tex → tables/LCDM_compare.tex）；1810.04805、2602.19229 = 3；1712.01208、2201.05989 = 2；其余 ≤1。**环 = 0**。
- 死文件（root 不可达 .tex）17 个/11 目录：注释掉的 `\input`（1706.03762×2、2602.19229/conclusion）、未接线残片（1902.03178×5、0906.4725/front-matter、2005.11401/tables/main_results、1801.02634/widetab）、改名 `.tex` 的 cls（1712.01208/acmart_old=docstrip 产物）、EPTCS 元数据（2606.31863/eptcsdata）、wrapper（2609.08578）。
- 未解析目标仅 1：死文件 acmart_old.tex 里 `\input{glyphtounicode}`（TeXLive 系统文件，属正常外部引用）。
- **两个静态分析陷阱（locate 模块须知）**：
    1. `2602.19229`：`tex/structure.tex` 在 `tex/` 内却写 `\input{tex/introduction}`——按「当前文件相对」解析必死，按 CWD（主文件目录）解析才对。本批所有解析命中都是 cwd 基（basis=cwd 全部，`src` 基 0 命中）。
    2. `1902.03178`：`\tikzfig{name}` 宏包内部 `\IfFileExists{#1.tikz}{\input{...}}`——108 个**宏包裹的动态 tex include**，静态正则不可见；且 `\input{zx.tikzdefs}` 目标**无 .tex 后缀**（tikzit 约定）。

## 4. 编码（strict UTF-8 + `file -I` 辅助）

| 目录          | 文件                                     | 事实                                                                                     |
| ------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------- |
| 0807.3917     | main.tex                                 | 已知 latin-5（`T\xa8UB\xffITAK` = TÜBİTAK）                                              |
| **0906.4725** | **iqo-v5.tex（主源）**                   | MANIFEST 未标注：偏移 125957 处孤立 `0xa9`（©），xeLaTeX 下会静默 U+FFFD                 |
| 1507.02284    | sieve.bbl、algorithm2e.sty、icml2016.bst | latin-1 人名字节（0xfc/0xf6/0xd0）；.bbl/.sty 会被引擎读取 → 同风险；.bst 仅 bibtex 消费 |
| 1612.09375    | cambridge7A.cls                          | `0x92`（cp1252 弯引号）                                                                  |

其余 35 目录全文本文件 UTF-8（含中文注释 2609.09529、Agda Unicode 2609.08578、法语×2）。UTF-16/BOM ×0。

## 5. 图格式

- `.eps`：0807.3917×2、0906.1291×1、1207.7214×15、hep-th×4（→ xelatex 路由触发）；`.ps`/`.mps` ×0。
- pdf 图普遍；png/jpg 大户：1507.02284(476)、0906.4725(395)、1106.1445(116 png)、2201.05989(88 jpg)。
- `.tikz` 文件：1902.03178×128（tikzit 图库）。
- **0906.4725 内含 `.svn/` 目录**（736 个 `.svn-base` 残留）——e-print 里夹带 VCS 元数据的真实案例；工作 PDF 实为 395 个。

## 6. vendored 依赖（.sty/.cls/.bst/.def/.clo 等）

26/39 目录自带依赖，值得注意：`2201.05989` 同时带 acmart.cls + **未使用的 cvpr.cls**；`1712.01208` 带 acmart.cls + acmart_old.tex（改名 cls）；`0807.3917` 带 IEEEtran.cls+pstricks.sty（vendored_sty_shadow 机制案例）；私类全套：IEEEtran×2、revtex4-1、aastex61、aa、iopart(+iopams/setstack)、cms-tdr、cambridge7A、eptcs、jfp-epi、quantumarticle、llncs、acmart×3。

## 7. 静态路由预演（路由表逐目录）

判据：`documentstyle`→reject；`*.eps` 文件在场或 pstricks 包/命令 →xelatex；minted →tectonic；其余 tectonic 优先。修饰 flag：non_utf8_source、no_hyperref_anchor_fallback。

| id             | class            | TeX      | tex | files | inputs | depth | 根数      | 图       | hyperref | 路由          | flags                             |
| -------------- | ---------------- | -------- | --- | ----- | ------ | ----- | --------- | -------- | -------- | ------------- | --------------------------------- |
| 0807.3917      | IEEEtran         | 2e       | 11  | 16    | 10     | 1     | 1         | eps:2    | N        | xelatex       | pstricks+eps+non_utf8+no_hyperref |
| 0906.1291      | revtex4          | 2e       | 1   | 2     | 0      | 0     | 1         | eps:1    | N        | xelatex       | eps+no_hyperref                   |
| 0906.4725      | iopart           | 2e       | 3   | 1142  | 1      | 1     | 1         | pdf:395  | N        | tectonic_pref | **non_utf8（主源）**+no_hyperref  |
| 1106.1445      | book             | 2e       | 1   | 120   | 0      | 0     | 1         | png:116  | Y        | tectonic_pref | –                                 |
| 1111.4914      | amsart           | 2e       | 1   | 4     | 0      | 0     | 1         | pdf:2    | N        | tectonic_pref | no_hyperref                       |
| 1207.7214      | elsarticle       | 2e       | 2   | 20    | 1      | 1     | 1         | eps:15   | Y        | xelatex       | eps                               |
| 1207.7235      | cms-tdr          | 2e       | 1   | 31    | 0      | 0     | 1         | pdf:22   | Y        | tectonic_pref | –                                 |
| 1403.3985      | revtex4-1        | 2e       | 2   | 21    | 1      | 1     | 1         | pdf:16   | Y        | tectonic_pref | –                                 |
| 1412.6980      | article          | 2e       | 1   | 2     | 0      | 0     | 1         | pdf:1    | Y        | tectonic_pref | –                                 |
| 1502.01589     | aa               | 2e       | 35  | 103   | 34     | **4** | 1         | pdf:63   | Y        | tectonic_pref | bare_input×25                     |
| 1507.02284     | article          | 2e       | 1   | 528   | 0      | 0     | 1         | 476 图   | Y        | tectonic_pref | non_utf8(aux)                     |
| 1511.06432     | article          | 2e       | 1   | 11    | 0      | 0     | 1         | pdf:2    | Y        | tectonic_pref | –                                 |
| 1512.03385     | article          | 2e       | 1   | 13    | 0      | 0     | 1         | pdf:7    | Y        | tectonic_pref | –                                 |
| 1612.09375     | cambridge7A      | 2e       | 18  | 34    | 17     | 1     | 1         | pdf:13   | Y        | tectonic_pref | non_utf8(cls)                     |
| 1706.03762     | article          | 2e       | 10  | 23    | 7      | 1     | 1         | pdf:6    | Y        | tectonic_pref | –                                 |
| 1712.01208     | **article**      | 2e       | 12  | 27    | 9      | 2     | 1         | pdf:12   | Y        | tectonic_pref | –                                 |
| 1801.02634     | aastex61         | 2e       | 5   | 22    | 3      | 1     | 1         | pdf:7    | N*       | tectonic_pref | no_hyperref（静态）               |
| 1810.04805     | article          | 2e       | 20  | 28    | 19     | 3     | 1         | pdf:4    | Y        | tectonic_pref | –                                 |
| 1902.03178     | quantumarticle   | 2e       | 6   | 148   | 5      | 1     | 1         | tikz:128 | Y        | tectonic_pref | 动态\tikzfig×108                  |
| 1906.08237     | article          | 2e       | 10  | 39    | 9      | 1     | 1         | pdf:10   | Y        | tectonic_pref | –                                 |
| 2003.08934     | llncs            | 2e       | 9   | 70    | 8      | 1     | 1         | jpg:46   | N        | tectonic_pref | no_hyperref                       |
| 2005.11401     | article          | 2e       | 10  | 18    | 8      | 1     | 1         | pdf:4    | Y        | tectonic_pref | –                                 |
| 2106.09685     | article          | 2e       | 3   | 18    | 2      | 1     | 1         | pdf:8    | Y        | tectonic_pref | –                                 |
| 2201.05989     | acmart           | 2e       | 18  | 119   | 18     | 2     | **2**     | jpg:88   | N*       | tectonic_pref | multi_doc                         |
| 2203.02155     | article          | 2e       | 6   | 32    | 5      | 1     | 1         | pdf:22   | Y        | tectonic_pref | –                                 |
| 2305.14335     | IEEEtran         | 2e       | 7   | 15    | 6      | 1     | 1         | pdf:6    | Y        | tectonic_pref | –                                 |
| 2308.07483     | revtex4-2        | 2e       | 1   | 7     | 0      | 0     | 1         | pdf:4    | Y        | tectonic_pref | –                                 |
| 2501.14787     | article          | 2e       | 20  | 118   | 15     | 1     | **5**     | pdf:16   | Y        | tectonic      | minted+multi_doc                  |
| 2512.03164     | amsart           | 2e       | 1   | 5     | 0      | 0     | 1         | –        | Y        | tectonic_pref | –                                 |
| 2602.06617     | article          | 2e       | 1   | 3     | 0      | 0     | 1         | –        | Y        | tectonic_pref | –                                 |
| 2602.09511     | amsart           | 2e       | 1   | 3     | 0      | 0     | 1         | –        | Y        | tectonic_pref | –                                 |
| 2602.19229     | acmart           | 2e       | 12  | 17    | 10     | 3     | 1         | –        | Y        | tectonic_pref | CWD 解析陷阱                      |
| 2606.31863     | eptcs            | 2e       | 3   | 8     | 1      | 1     | 1         | –        | Y        | tectonic_pref | –                                 |
| 2609.06443     | jfp-epi+subfiles | 2e       | 13  | 16    | 12     | 1     | **12**    | –        | Y        | tectonic_pref | subfiles 多根                     |
| 2609.08578     | acmart           | 2e       | 5   | 10    | 4      | 1     | 1+wrapper | –        | N*       | tectonic_pref | wrapper+\jobname                  |
| 2609.09529     | elsarticle       | 2e       | 1   | 2     | 0      | 0     | 1         | –        | Y        | tectonic_pref | –                                 |
| 2609.11777     | article          | 2e       | 1   | 17    | 0      | 0     | 1         | png:14   | Y        | tectonic_pref | –                                 |
| hep-th/9901001 | ptptex           | **2.09** | 1   | 6     | 0      | 0     | 1         | eps:4    | N        | **reject**    | documentstyle                     |
| math/0404188   | amsart           | 2e       | 1   | 1     | 0      | 0     | 1         | –        | N        | tectonic_pref | no_hyperref                       |

路由汇总：**reject×1、xelatex×3、tectonic×1、tectonic_pref×34**。hyperref 静态未检出 10 家，其中 acmart(2201.05989/2609.08578)、aastex61(1801.02634) 类内部自带 → 真·无 hyperref ≈ 7/39（18%）。inputenc×12 / fontenc×11（normalize 手术面）、babel×5、epsfig×6、listings×3、pstricks×1、minted×1、fontspec/polyglossia/ctex ×0。

## 8. 与 MANIFEST 标注不一致处

| 目录       | MANIFEST                                | 实测                                                                                                                   |
| ---------- | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| 1712.01208 | `acmart[sigconf]`                       | **生效类是 `article[11pt]`**；acmart 那行在注释里（line 1 被 `%` 注释）                                                |
| 2201.05989 | "camera.tex=CVPR / paper.tex=TOG"       | 两个根**都是 acmart**（camera=`[acmtog,authorversion,nonacm]`、paper=`[acmtog,authorversion]`）；cvpr.cls 在场但无引用 |
| 0906.4725  | "1134 个 PDF 图文件"                    | 工作 PDF=395；余量是 `.svn/text-base` 残留 736 个（e-print 夹带 .svn）                                                 |
| 1502.01589 | `aa[referee,...]`、"9×\input"           | referee 变体在注释里，生效 `[traditabstract,longauth]`；braced \input=9 ✓，另有 25 处裸 `\input file`                  |
| 1507.02284 | "自带 4 个 .sty"                        | 实为 6 .sty + 1 .bst（多 fancyhdr/icml2016.sty/icml2016.bst）                                                          |
| 2501.14787 | 未提多根                                | **5 个独立根**（main + 4 psets）                                                                                       |
| 2609.06443 | "13 tex 各自可编译"                     | 12 个有 docclass（macros.tex 是支援文件）                                                                              |
| 2609.08578 | `acmart[acmsmall,authorversion,nonacm]` | 实际多 `screen`；且 MANIFEST 未提 wrapper root + `\jobname` 条件编译                                                   |
| 1111.4914  | babel                                   | `\usepackage[american]{babel}` 在注释里，未生效                                                                        |
| 2602.19229 | `acmart[manuscript,screen,review]`      | 生效 `[manuscript,natbib=false,nonacm]`                                                                                |
| 非 UTF-8   | 仅标 0807.3917                          | 另有 0906.4725 主源 + 1507.02284/1612.09375 的消费文件                                                                 |
| eps        | 仅标 hep-th/0807.3917                   | 0906.1291(1)、1207.7214(15) 也有 .eps → 同样触发 xelatex 路由                                                          |

## 9. 备注/口径

- 「文件数」含隐藏目录产物（.svn）；tex_files 仅计 `*.tex`。
- `\input` 计数含 preamble/body 全部出现（注释已剥）；`\includegraphics` 经控制序列边界排除不误计。
- hyperref/babel 等 feature 为静态扫描下限：`\usepackage[hyperref]{othersty}`（1810.04805 naaclhlt2019）已按 option 捕获；类内部加载不可见。
- 2609.11777 装了 newclude 但全 corpus 零 `\include*`——「装备未使用」。
