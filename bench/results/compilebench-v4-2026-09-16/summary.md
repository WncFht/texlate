# compilebench v4 — corpus_v3 baseline × 双引擎

- 日期: 2026-09-16 02:56:00
- 语料: `/home/fanghaotian/src/texlate/bench/corpus_v3` extracted/ 分层抽样 n=180 (sample.json, seed=20260915, stratum_cell 比例分配)
- 平台: Linux-7.2.4-arch1-2-x86_64-with-glibc2.44
- tectonic: `tectonic 0.15.0Tectonic 0.15.0`
- xelatex: `XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026/Arch Linux)`
- 条件: baseline 原文直编, 不注入不修复; xelatex ≤2pass×240s, tectonic 240s
- 判定: 产品 `texlate.compile.judge`(expect_cjk=False); clean = pdf ∧ err≤3 ∧ 首错非missing_*/undefined_cs ∧ warn红线零命中

## 1. 总成功率

| 引擎 | n | clean | pdf~ | FAIL | clean率 | pdf率 |
|---|---|---|---|---|---|---|
| tectonic | 172 | 53 | 55 | 64 | 30.8% | 62.8% |
| xelatex | 172 | 41 | 16 | 115 | 23.8% | 33.1% |

联合覆盖: 任一引擎出 pdf 127/180 (70.6%); 任一引擎 clean 69/180 (38.3%); 全引擎皆死 53

## 2. per-引擎 × per-带 成功率矩阵 (clean / pdf~ / FAIL)

| 带 | n | tec clean | tec pdf~ | tec FAIL | xel clean | xel pdf~ | xel FAIL |
|---|---|---|---|---|---|---|---|
| a | 36 | 7 | 8 | 18 | 10 | 3 | 20 |
| b | 37 | 9 | 7 | 19 | 9 | 5 | 21 |
| c | 37 | 13 | 8 | 14 | 11 | 3 | 21 |
| d | 35 | 12 | 14 | 8 | 7 | 1 | 26 |
| e | 35 | 12 | 18 | 5 | 4 | 4 | 27 |

## 2b. per-引擎 × cat_group pdf 率

| cat_group | n | tectonic pdf率  |  xelatex pdf率  |
|---|---|---|---|
| astro-ph | 24 | 10/23 | 6/23 |
| cond-mat | 25 | 14/25 | 5/25 |
| cs | 32 | 23/30 | 11/30 |
| eess-stat-etc | 9 | 8/9 | 2/9 |
| hep-phys | 41 | 22/39 | 12/39 |
| math | 37 | 26/35 | 20/35 |
| nucl | 4 | 1/4 | 0/4 |
| quant-ph | 8 | 4/7 | 1/7 |

## 3. route_project 实录 × 结果

| 路由标记 | n篇 | tectonic clean/pdf~/FAIL  |  xelatex clean/pdf~/FAIL  |
|---|---|---|---|
| latex209_suspect(\documentstyle 试编) | 13 | 3/6/4 | 3/1/9 |
| non_utf8 | 19 | 0/11/8 | 0/8/11 |
| eps/pstricks→xel优先 | 55 | 0/4/49 | 13/3/37 |

## 4. top 失败类别 (首错归因, fixloop F 命名)

### tectonic

| 类别 | F映射 | 格数 | 代表 payload |
|---|---|---|---|
| eps_image | 路由 eps/ps→xelatex | 45 | — |
| clean | — | 32 | — |
| missing_file | F1/F4 missing_pkg/cls/file | 20 | psfig.sty |
| undefined_cs | 未定义控制序列 | 9 | — |
| other | 其他 | 6 | — |
| missing_pfb | F3 physical font @xdvipdfmx | 3 | — |
| pdftex_prim | F5 pdfTeX 原语 | 2 | pdfinfo |
| already_def | F11 宏冲突 | 1 | negmedspace |
| syntax | 语法 | 1 | — |

### xelatex

| 类别 | F映射 | 格数 | 代表 payload |
|---|---|---|---|
| missing_file | F1/F4 missing_pkg/cls/file | 110 | psfig.sty |
| clean | — | 7 | — |
| pdftex_prim | F5 pdfTeX 原语 | 7 | pdfinfo |
| other | 其他 | 3 | — |
| undefined_cs | 未定义控制序列 | 2 | — |
| already_def | F11 宏冲突 | 1 | negmedspace |
| latex209 | F12 LaTeX2.09 | 1 | — |

## 5. 逐篇明细

| paper | band | cell | route |tectonic | xelatex |
|---|---|---|---|---|---|
| 0707.1511 | b | b_2007_11|quant-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 0707.2108 | b | b_2007_11|math | — | no_main_tex(-/-) | no_main_tex(-/-) |
| 0707.2125 | b | b_2007_11|math | — | clean(0/clean) | clean(0/clean) |
| 0707.2833 | b | b_2007_11|cs | non-utf8 | FAIL(1/eps_image) | pdf~(1/other) |
| 0707.3950 | b | b_2007_11|math | — | clean(0/clean) | clean(0/clean) |
| 0707.4363 | b | b_2007_11|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 0707.4451 | b | b_2007_11|math | — | clean(0/clean) | clean(0/clean) |
| 0806.0904 | b | b_2007_11|math | 209suspect | FAIL(100/missing_file) | FAIL(2/missing_file) |
| 0806.4589 | b | b_2007_11|hep-phys | — | FAIL(393/missing_file) | FAIL(2/missing_file) |
| 0905.4208 | b | b_2007_11|nucl | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 0905.4371 | b | b_2007_11|math | — | pdf~(491/missing_file) | FAIL(2/missing_file) |
| 1003.1735 | b | b_2007_11|astro-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 1003.1741 | b | b_2007_11|cs | — | no_main_tex(-/-) | no_main_tex(-/-) |
| 1003.1906 | b | b_2007_11|math | — | clean(0/clean) | pdf~(4/missing_file) |
| 1003.2091 | b | b_2007_11|cond-mat | — | FAIL(0/eps_image) | clean(0/clean) |
| 1003.4522 | b | b_2007_11|astro-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1003.5338 | b | b_2007_11|eess-stat-etc | — | clean(0/clean) | clean(0/clean) |
| 1003.5495 | b | b_2007_11|hep-phys | — | FAIL(0/eps_image) | clean(0/clean) |
| 1003.5531 | b | b_2007_11|math | non-utf8 | pdf~(0/clean) | pdf~(0/clean) |
| 1003.5546 | b | b_2007_11|astro-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1012.1124 | b | b_2007_11|quant-ph | non-utf8 | pdf~(1/other) | pdf~(1/other) |
| 1012.1143 | b | b_2007_11|astro-ph | — | pdf~(108/missing_file) | FAIL(2/missing_file) |
| 1012.1177 | b | b_2007_11|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1012.1206 | b | b_2007_11|astro-ph | — | FAIL(1/eps_image) | clean(1/other) |
| 1012.1740 | b | b_2007_11|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 1012.5086 | b | b_2007_11|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 1012.5145 | b | b_2007_11|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1012.5273 | b | b_2007_11|hep-phys | — | FAIL(0/eps_image) | clean(0/clean) |
| 1012.5491 | b | b_2007_11|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1109.1664 | b | b_2007_11|hep-phys | non-utf8 | pdf~(0/clean) | pdf~(0/clean) |
| 1109.1801 | b | b_2007_11|math | non-utf8 | pdf~(0/clean) | FAIL(2/missing_file) |
| 1109.2059 | b | b_2007_11|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1109.5364 | b | b_2007_11|hep-phys | — | FAIL(55/missing_file) | FAIL(2/missing_file) |
| 1109.5682 | b | b_2007_11|hep-phys | — | clean(0/clean) | clean(0/clean) |
| 1109.5931 | b | b_2007_11|cs | — | pdf~(1/other) | FAIL(2/missing_file) |
| 1109.5963 | b | b_2007_11|hep-phys | — | FAIL(1/eps_image) | FAIL(2/missing_file) |
| 1109.6007 | b | b_2007_11|astro-ph | — | FAIL(1076/missing_file) | FAIL(2/missing_file) |
| 1206.1653 | c | c_2012_16|cs | — | pdf~(1/syntax) | FAIL(2/missing_file) |
| 1206.1808 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1206.1993 | c | c_2012_16|math | — | pdf~(2/undefined_cs) | FAIL(2/missing_file) |
| 1206.5375 | c | c_2012_16|hep-phys | — | FAIL(0/missing_pfb) | clean(0/clean) |
| 1206.5620 | c | c_2012_16|astro-ph | — | FAIL(335/missing_file) | FAIL(2/missing_file) |
| 1206.5628 | c | c_2012_16|math | non-utf8 | pdf~(1/other) | FAIL(4/missing_file) |
| 1206.5796 | c | c_2012_16|hep-phys | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1206.5832 | c | c_2012_16|hep-phys | non-utf8 | FAIL(1/eps_image) | FAIL(2/missing_file) |
| 1306.2177 | c | c_2012_16|nucl | — | FAIL(100/missing_file) | FAIL(2/missing_file) |
| 1306.2183 | c | c_2012_16|cond-mat | non-utf8 | pdf~(0/clean) | FAIL(2/missing_file) |
| 1306.5749 | c | c_2012_16|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 1306.6147 | c | c_2012_16|quant-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1306.6222 | c | c_2012_16|math | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1404.2112 | c | c_2012_16|astro-ph | — | FAIL(0/eps_image) | clean(0/clean) |
| 1404.2164 | c | c_2012_16|astro-ph | non-utf8 | FAIL(0/eps_image) | pdf~(0/clean) |
| 1404.2362 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1404.5668 | c | c_2012_16|cs | — | FAIL(2/pdftex_prim) | pdf~(2/pdftex_prim) |
| 1404.5685 | c | c_2012_16|cond-mat | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1404.6154 | c | c_2012_16|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 1404.6180 | c | c_2012_16|hep-phys | non-utf8 | FAIL(309/missing_file) | FAIL(2/missing_file) |
| 1502.02155 | c | c_2012_16|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1502.02285 | c | c_2012_16|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| 1502.06096 | c | c_2012_16|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1502.06131 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1502.06256 | c | c_2012_16|eess-stat-etc | — | clean(0/clean) | clean(0/clean) |
| 1502.06459 | c | c_2012_16|quant-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 1502.06541 | c | c_2012_16|hep-phys | — | pdf~(16/other) | pdf~(15/other) |
| 1511.06628 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1608.02354 | c | c_2012_16|math | — | clean(1/other) | clean(1/other) |
| 1608.02550 | c | c_2012_16|math | — | FAIL(0/missing_pfb) | clean(0/clean) |
| 1608.02631 | c | c_2012_16|astro-ph | — | no_main_tex(-/-) | no_main_tex(-/-) |
| 1608.02645 | c | c_2012_16|astro-ph | — | clean(1/syntax) | clean(0/clean) |
| 1608.02651 | c | c_2012_16|hep-phys | — | clean(0/clean) | clean(0/clean) |
| 1608.06693 | c | c_2012_16|cs | — | no_main_tex(-/-) | no_main_tex(-/-) |
| 1608.06769 | c | c_2012_16|eess-stat-etc | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1608.07013 | c | c_2012_16|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1608.07066 | c | c_2012_16|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| 1706.02550 | d | d_2017_20|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1706.02567 | d | d_2017_20|cond-mat | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1706.02568 | d | d_2017_20|math | — | clean(0/clean) | FAIL(2/missing_file) |
| 1706.02657 | d | d_2017_20|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1706.02671 | d | d_2017_20|math | — | clean(0/clean) | FAIL(2/missing_file) |
| 1706.02694 | d | d_2017_20|cond-mat | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1706.02695 | d | d_2017_20|eess-stat-etc | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1706.07493 | d | d_2017_20|math | — | clean(0/clean) | clean(0/clean) |
| 1706.07613 | d | d_2017_20|cs | — | pdf~(4/undefined_cs) | FAIL(2/missing_file) |
| 1803.02897 | d | d_2017_20|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| 1803.02918 | d | d_2017_20|eess-stat-etc | — | pdf~(3/pdftex_prim) | FAIL(4/pdftex_prim) |
| 1803.02994 | d | d_2017_20|cs | — | clean(2/pdftex_prim) | FAIL(2/missing_file) |
| 1803.03110 | d | d_2017_20|math | — | clean(0/clean) | clean(0/clean) |
| 1803.03235 | d | d_2017_20|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| 1803.03249 | d | d_2017_20|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1803.08846 | d | d_2017_20|math | — | clean(0/clean) | clean(0/clean) |
| 1811.03615 | d | d_2017_20|hep-phys | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1811.03619 | d | d_2017_20|cs | — | pdf~(180/undefined_cs) | FAIL(4/pdftex_prim) |
| 1811.03624 | d | d_2017_20|astro-ph | — | pdf~(54/undefined_cs) | FAIL(2/missing_file) |
| 1811.10012 | d | d_2017_20|nucl | — | FAIL(1/eps_image) | FAIL(2/missing_file) |
| 1811.10029 | d | d_2017_20|hep-phys | — | clean(0/clean) | clean(0/clean) |
| 1811.10050 | d | d_2017_20|cs | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1811.10148 | d | d_2017_20|astro-ph | — | FAIL(0/eps_image) | clean(0/clean) |
| 1907.03602 | d | d_2017_20|quant-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 1907.03821 | d | d_2017_20|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1907.03868 | d | d_2017_20|cs | — | clean(0/clean) | FAIL(2/missing_file) |
| 2003.03387 | d | d_2017_20|astro-ph | — | pdf~(84/undefined_cs) | FAIL(2/missing_file) |
| 2003.03479 | d | d_2017_20|cs | — | pdf~(0/clean) | pdf~(4/pdftex_prim) |
| 2003.03510 | d | d_2017_20|math | — | no_main_tex(-/-) | no_main_tex(-/-) |
| 2003.10723 | d | d_2017_20|math | — | FAIL(0/eps_image) | clean(0/clean) |
| 2009.03673 | d | d_2017_20|cs | — | FAIL(0/eps_image) | clean(0/clean) |
| 2009.03686 | d | d_2017_20|hep-phys | non-utf8 | pdf~(0/clean) | FAIL(2/missing_file) |
| 2009.03699 | d | d_2017_20|eess-stat-etc | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2009.03736 | d | d_2017_20|math | — | FAIL(0/missing_pfb) | FAIL(2/missing_file) |
| 2009.10977 | d | d_2017_20|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 2105.03750 | e | e_2021_25|astro-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 2105.03798 | e | e_2021_25|math | — | FAIL(799/undefined_cs) | FAIL(4/pdftex_prim) |
| 2105.03943 | e | e_2021_25|cs | — | pdf~(273/undefined_cs) | pdf~(2/pdftex_prim) |
| 2105.11393 | e | e_2021_25|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 2203.04298 | e | e_2021_25|cs | — | pdf~(0/clean) | clean(0/clean) |
| 2203.12999 | e | e_2021_25|cs | — | pdf~(0/clean) | pdf~(0/clean) |
| 2203.13055 | e | e_2021_25|cs | — | clean(2/syntax) | FAIL(2/missing_file) |
| 2203.13064 | e | e_2021_25|cs | — | pdf~(598/undefined_cs) | pdf~(2/pdftex_prim) |
| 2203.13079 | e | e_2021_25|eess-stat-etc | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2211.04450 | e | e_2021_25|math | — | clean(0/clean) | FAIL(2/missing_file) |
| 2211.04453 | e | e_2021_25|cond-mat | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2211.04457 | e | e_2021_25|hep-phys | — | pdf~(3/other) | FAIL(2/missing_file) |
| 2211.04503 | e | e_2021_25|astro-ph | — | pdf~(0/clean) | FAIL(0/latex209) |
| 2211.04515 | e | e_2021_25|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2211.12986 | e | e_2021_25|eess-stat-etc | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 2308.04174 | e | e_2021_25|math | non-utf8 | pdf~(2/other) | FAIL(3/missing_file) |
| 2308.04188 | e | e_2021_25|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2308.04212 | e | e_2021_25|eess-stat-etc | — | pdf~(0/clean) | FAIL(4/undefined_cs) |
| 2308.04217 | e | e_2021_25|hep-phys | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2308.04280 | e | e_2021_25|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 2308.12610 | e | e_2021_25|cs | — | clean(0/clean) | clean(0/clean) |
| 2308.12712 | e | e_2021_25|cs | — | clean(0/clean) | FAIL(3/missing_file) |
| 2403.05454 | e | e_2021_25|math | — | clean(0/clean) | FAIL(2/missing_file) |
| 2403.05463 | e | e_2021_25|hep-phys | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2403.05475 | e | e_2021_25|math | — | clean(0/clean) | clean(1/other) |
| 2403.05550 | e | e_2021_25|cs | — | clean(0/clean) | FAIL(2/missing_file) |
| 2403.15075 | e | e_2021_25|cs | — | FAIL(0/clean) | FAIL(2/missing_file) |
| 2403.15096 | e | e_2021_25|math | non-utf8 | pdf~(0/clean) | pdf~(0/clean) |
| 2403.15102 | e | e_2021_25|cs | — | FAIL(3/eps_image) | clean(0/clean) |
| 2403.15126 | e | e_2021_25|astro-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 2403.15129 | e | e_2021_25|hep-phys | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2403.15170 | e | e_2021_25|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2410.05959 | e | e_2021_25|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 2410.06028 | e | e_2021_25|cs | — | clean(0/clean) | FAIL(2/missing_file) |
| 2410.17992 | e | e_2021_25|quant-ph | — | pdf~(0/clean) | FAIL(2/missing_file) |
| astro-ph/0501439 | a | a_pre2007|astro-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| astro-ph/0501590 | a | a_pre2007|astro-ph | — | FAIL(53/missing_file) | FAIL(2/missing_file) |
| astro-ph/0605290 | a | a_pre2007|astro-ph | — | pdf~(64/missing_file) | FAIL(2/missing_file) |
| astro-ph/0605361 | a | a_pre2007|astro-ph | — | FAIL(0/eps_image) | clean(0/clean) |
| astro-ph/9703134 | a | a_pre2007|astro-ph | 209suspect | FAIL(184/missing_file) | FAIL(2/missing_file) |
| astro-ph/9703198 | a | a_pre2007|astro-ph | 209suspect | FAIL(1/missing_file) | FAIL(2/missing_file) |
| astro-ph/9910044 | a | a_pre2007|astro-ph | 209suspect | pdf~(64/missing_file) | FAIL(2/missing_file) |
| cond-mat/0111097 | a | a_pre2007|cond-mat | 209suspect,non-utf8 | pdf~(2/undefined_cs) | pdf~(2/undefined_cs) |
| cond-mat/0307578 | a | a_pre2007|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| cond-mat/0307744 | a | a_pre2007|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| cond-mat/0501109 | a | a_pre2007|cond-mat | — | FAIL(0/eps_image) | pdf~(0/clean) |
| cond-mat/0605032 | a | a_pre2007|cond-mat | — | FAIL(0/eps_image) | clean(0/clean) |
| cond-mat/9703223 | a | a_pre2007|cond-mat | 209suspect | clean(0/clean) | clean(0/clean) |
| cond-mat/9910214 | a | a_pre2007|cond-mat | 209suspect | pdf~(200/missing_file) | FAIL(2/missing_file) |
| cs/0307009 | a | a_pre2007|cs | — | FAIL(0/eps_image) | clean(0/clean) |
| hep-lat/0111059 | a | a_pre2007|hep-phys | — | FAIL(310/missing_file) | FAIL(2/missing_file) |
| hep-ph/0111245 | a | a_pre2007|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| hep-ph/0605178 | a | a_pre2007|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| hep-ph/9703202 | a | a_pre2007|hep-phys | — | no_main_tex(-/-) | no_main_tex(-/-) |
| hep-ph/9703402 | a | a_pre2007|hep-phys | 209suspect | clean(0/clean) | clean(0/clean) |
| hep-ph/9910373 | a | a_pre2007|hep-phys | 209suspect | pdf~(38/missing_file) | FAIL(2/missing_file) |
| hep-ph/9910443 | a | a_pre2007|hep-phys | non-utf8 | pdf~(0/clean) | pdf~(0/clean) |
| hep-th/0501161 | a | a_pre2007|hep-phys | — | clean(0/clean) | clean(0/clean) |
| hep-th/9703099 | a | a_pre2007|hep-phys | 209suspect | clean(0/clean) | clean(0/clean) |
| hep-th/9703173 | a | a_pre2007|hep-phys | 209suspect | pdf~(71/missing_file) | FAIL(2/missing_file) |
| hep-th/9910028 | a | a_pre2007|hep-phys | — | no_main_tex(-/-) | no_main_tex(-/-) |
| math/0307077 | a | a_pre2007|math | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| math/0307301 | a | a_pre2007|math | — | clean(0/clean) | clean(0/clean) |
| math/0501060 | a | a_pre2007|math | — | FAIL(0/eps_image) | clean(0/clean) |
| math/0605628 | a | a_pre2007|math | — | clean(0/clean) | clean(0/clean) |
| nucl-th/0111058 | a | a_pre2007|nucl | 209suspect | pdf~(254/missing_file) | FAIL(2/missing_file) |
| physics/0307021 | a | a_pre2007|hep-phys | — | FAIL(100/missing_file) | FAIL(2/missing_file) |
| physics/0605206 | a | a_pre2007|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| q-alg/9703046 | a | a_pre2007|math | 209suspect | FAIL(2/already_def) | FAIL(4/already_def) |
| quant-ph/0111094 | a | a_pre2007|quant-ph | — | no_main_tex(-/-) | no_main_tex(-/-) |
| quant-ph/0605205 | a | a_pre2007|quant-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |

## 6. 与 corpus_v2 基线对比 (v2: n=40 分层, 同冷沙箱口径)

| 指标 | corpus_v2 (n=40) | corpus_v3 (本轮) |
|---|---|---|
| tectonic clean率 | 8/40 = 20.0% | 53/172 = 30.8% |
| tectonic pdf率 | 24/40 = 60.0% | 108/172 = 62.8% |
| xelatex clean率 | 4/40 = 10.0% | 41/172 = 23.8% |
| xelatex pdf率 | 6/40 = 15.0% | 57/172 = 33.1% |
| 联合pdf | — | 127/180 = 70.6% |

## 7. 对 M2 ≥90% 目标的可行性

- tectonic: pdf 108/172 (62.8%), clean 53/172 (30.8%), top FAIL: eps_image×45, missing_file×12, missing_pfb×3
- xelatex: pdf 57/172 (33.1%), clean 41/172 (23.8%), top FAIL: missing_file×109, pdftex_prim×3, already_def×1
- 联合天花板: 任一引擎 pdf 70.6%, clean 38.3% —— fixloop+路由+normalize 需要补的百分点即 90%−此值

### 口径备注

- xelatex 跑在冷 TEXMF 沙箱(每篇独立 TEXMFHOME/VAR/CONFIG → 不继承用户已装包), tectonic 用自带 bundle(缓存热身后即暖); 判定器为产品 judge(v2 内嵌版退役), 红线集见 engine.WARNING_RED_LINES。
- \documentstyle 已降级为 latex209_suspect 试编标记(route 不再 reject)——真实试编, FAIL 计入管线缺口; fixloop 侧 latex209_reject gate 在真 2.09 错时兜底拒。inject 层拒绝记 inject_reject:latex209 类。

