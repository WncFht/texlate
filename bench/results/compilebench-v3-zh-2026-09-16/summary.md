# compilebench v3 — corpus_v3 zh × 双引擎

- 日期: 2026-09-16 10:22:27
- 语料: `/home/fanghaotian/src/texlate/bench/corpus_v3` extracted/ 分层抽样 n=180 (sample.json, seed=20260915, stratum_cell 比例分配)
- 平台: Linux-7.2.4-arch1-2-x86_64-with-glibc2.44
- tectonic: `tectonic 0.15.0Tectonic 0.15.0`
- xelatex: `XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026/Arch Linux)`
- 条件: zh — normalize_project + prepare_chinese(ctex) 后直编, 不修复; xelatex ≤2pass×240s, tectonic 240s
- 判定: 产品 `texlate.compile.judge`(expect_cjk=False); clean = pdf ∧ err≤3 ∧ 首错非missing_*/undefined_cs ∧ warn红线零命中

## 1. 总成功率

| 引擎 | n | clean | pdf~ | FAIL | clean率 | pdf率 |
|---|---|---|---|---|---|---|
| tectonic | 175 | 62 | 40 | 60 | 35.4% | 58.3% |
| xelatex | 175 | 48 | 6 | 108 | 27.4% | 30.9% |

联合覆盖: 任一引擎出 pdf 120/180 (66.7%); 任一引擎 clean 80/180 (44.4%); 全引擎皆死 60

## 2. per-引擎 × per-带 成功率矩阵 (clean / pdf~ / FAIL)

| 带 | n | tec clean | tec pdf~ | tec FAIL | xel clean | xel pdf~ | xel FAIL |
|---|---|---|---|---|---|---|---|
| a | 36 | 4 | 2 | 16 | 8 | 2 | 12 |
| b | 37 | 11 | 4 | 19 | 13 | 1 | 20 |
| c | 37 | 16 | 7 | 13 | 12 | 2 | 22 |
| d | 35 | 15 | 13 | 7 | 8 | 0 | 27 |
| e | 35 | 16 | 14 | 5 | 7 | 1 | 27 |

## 2b. per-引擎 × cat_group pdf 率

| cat_group | n | tectonic pdf率  |  xelatex pdf率  |
|---|---|---|---|
| astro-ph | 24 | 8/23 | 6/23 |
| cond-mat | 25 | 11/25 | 3/25 |
| cs | 32 | 23/31 | 10/31 |
| eess-stat-etc | 9 | 8/9 | 2/9 |
| hep-phys | 41 | 19/39 | 10/39 |
| math | 37 | 29/36 | 21/36 |
| nucl | 4 | 0/4 | 0/4 |
| quant-ph | 8 | 4/8 | 2/8 |

## 3. route_project 实录 × 结果

| 路由标记 | n篇 | tectonic clean/pdf~/FAIL  |  xelatex clean/pdf~/FAIL  |
|---|---|---|---|
| latex209_suspect(\documentstyle 试编) | 13 | 0/0/0 | 0/0/0 |
| non_utf8 | 19 | 5/5/8 | 4/3/11 |
| eps/pstricks→xel优先 | 55 | 0/2/47 | 15/1/33 |

## 4. top 失败类别 (首错归因, fixloop F 命名)

### tectonic

| 类别 | F映射 | 格数 | 代表 payload |
|---|---|---|---|
| eps_image | 路由 eps/ps→xelatex | 46 | — |
| clean | — | 36 | — |
| missing_file | F1/F4 missing_pkg/cls/file | 13 | espcrc2.sty |
| other | 其他 | 3 | — |
| undefined_cs | 未定义控制序列 | 2 | — |

### xelatex

| 类别 | F映射 | 格数 | 代表 payload |
|---|---|---|---|
| missing_file | F1/F4 missing_pkg/cls/file | 106 | espcrc2.sty |
| clean | — | 5 | — |
| other | 其他 | 1 | — |
| latex209 | F12 LaTeX2.09 | 1 | — |
| undefined_cs | 未定义控制序列 | 1 | — |

## 5. 逐篇明细

| paper | band | cell | route |tectonic | xelatex |
|---|---|---|---|---|---|
| 0707.1511 | b | b_2007_11|quant-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 0707.2108 | b | b_2007_11|math | — | no_main_tex(-/-) | no_main_tex(-/-) |
| 0707.2125 | b | b_2007_11|math | — | clean(0/clean) | clean(0/clean) |
| 0707.2833 | b | b_2007_11|cs | non-utf8 | FAIL(0/eps_image) | clean(0/clean) |
| 0707.3950 | b | b_2007_11|math | — | clean(0/clean) | clean(0/clean) |
| 0707.4363 | b | b_2007_11|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 0707.4451 | b | b_2007_11|math | — | clean(0/clean) | clean(0/clean) |
| 0806.0904 | b | b_2007_11|math | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| 0806.4589 | b | b_2007_11|hep-phys | — | FAIL(393/missing_file) | FAIL(2/missing_file) |
| 0905.4208 | b | b_2007_11|nucl | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 0905.4371 | b | b_2007_11|math | — | pdf~(491/missing_file) | FAIL(2/missing_file) |
| 1003.1735 | b | b_2007_11|astro-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 1003.1741 | b | b_2007_11|cs | — | no_main_tex(-/-) | no_main_tex(-/-) |
| 1003.1906 | b | b_2007_11|math | — | clean(3/other) | clean(3/other) |
| 1003.2091 | b | b_2007_11|cond-mat | — | FAIL(0/eps_image) | clean(0/clean) |
| 1003.4522 | b | b_2007_11|astro-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1003.5338 | b | b_2007_11|eess-stat-etc | — | clean(0/clean) | clean(0/clean) |
| 1003.5495 | b | b_2007_11|hep-phys | — | FAIL(0/eps_image) | clean(0/clean) |
| 1003.5531 | b | b_2007_11|math | non-utf8 | clean(0/clean) | clean(0/clean) |
| 1003.5546 | b | b_2007_11|astro-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1012.1124 | b | b_2007_11|quant-ph | non-utf8 | pdf~(0/clean) | pdf~(0/clean) |
| 1012.1143 | b | b_2007_11|astro-ph | — | FAIL(95/missing_file) | FAIL(2/missing_file) |
| 1012.1177 | b | b_2007_11|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1012.1206 | b | b_2007_11|astro-ph | — | FAIL(1/eps_image) | clean(1/other) |
| 1012.1740 | b | b_2007_11|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 1012.5086 | b | b_2007_11|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 1012.5145 | b | b_2007_11|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1012.5273 | b | b_2007_11|hep-phys | — | FAIL(0/eps_image) | clean(0/clean) |
| 1012.5491 | b | b_2007_11|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1109.1664 | b | b_2007_11|hep-phys | non-utf8 | clean(0/clean) | clean(0/clean) |
| 1109.1801 | b | b_2007_11|math | non-utf8 | pdf~(0/clean) | FAIL(2/missing_file) |
| 1109.2059 | b | b_2007_11|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1109.5364 | b | b_2007_11|hep-phys | — | FAIL(55/missing_file) | FAIL(2/missing_file) |
| 1109.5682 | b | b_2007_11|hep-phys | — | clean(0/clean) | clean(0/clean) |
| 1109.5931 | b | b_2007_11|cs | — | pdf~(1/other) | FAIL(2/missing_file) |
| 1109.5963 | b | b_2007_11|hep-phys | — | FAIL(1/eps_image) | FAIL(2/missing_file) |
| 1109.6007 | b | b_2007_11|astro-ph | — | FAIL(1061/missing_file) | FAIL(2/missing_file) |
| 1206.1653 | c | c_2012_16|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1206.1808 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1206.1993 | c | c_2012_16|math | — | pdf~(2/undefined_cs) | FAIL(2/missing_file) |
| 1206.5375 | c | c_2012_16|hep-phys | — | clean(0/clean) | clean(0/clean) |
| 1206.5620 | c | c_2012_16|astro-ph | — | FAIL(332/missing_file) | FAIL(2/missing_file) |
| 1206.5628 | c | c_2012_16|math | non-utf8 | pdf~(0/clean) | FAIL(3/missing_file) |
| 1206.5796 | c | c_2012_16|hep-phys | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1206.5832 | c | c_2012_16|hep-phys | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1306.2177 | c | c_2012_16|nucl | — | FAIL(100/missing_file) | FAIL(2/missing_file) |
| 1306.2183 | c | c_2012_16|cond-mat | non-utf8 | clean(0/clean) | FAIL(2/missing_file) |
| 1306.5749 | c | c_2012_16|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 1306.6147 | c | c_2012_16|quant-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1306.6222 | c | c_2012_16|math | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1404.2112 | c | c_2012_16|astro-ph | — | FAIL(0/eps_image) | clean(0/clean) |
| 1404.2164 | c | c_2012_16|astro-ph | non-utf8 | FAIL(0/eps_image) | clean(0/clean) |
| 1404.2362 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1404.5668 | c | c_2012_16|cs | — | FAIL(0/clean) | pdf~(0/clean) |
| 1404.5685 | c | c_2012_16|cond-mat | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1404.6154 | c | c_2012_16|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 1404.6180 | c | c_2012_16|hep-phys | non-utf8 | FAIL(308/missing_file) | FAIL(2/missing_file) |
| 1502.02155 | c | c_2012_16|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1502.02285 | c | c_2012_16|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| 1502.06096 | c | c_2012_16|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1502.06131 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1502.06256 | c | c_2012_16|eess-stat-etc | — | clean(0/clean) | clean(0/clean) |
| 1502.06459 | c | c_2012_16|quant-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 1502.06541 | c | c_2012_16|hep-phys | — | pdf~(15/other) | pdf~(15/other) |
| 1511.06628 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1608.02354 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1608.02550 | c | c_2012_16|math | — | clean(0/clean) | clean(0/clean) |
| 1608.02631 | c | c_2012_16|astro-ph | — | no_main_tex(-/-) | no_main_tex(-/-) |
| 1608.02645 | c | c_2012_16|astro-ph | — | clean(0/clean) | clean(0/clean) |
| 1608.02651 | c | c_2012_16|hep-phys | — | clean(0/clean) | clean(0/clean) |
| 1608.06693 | c | c_2012_16|cs | — | FAIL(100/missing_file) | FAIL(2/missing_file) |
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
| 1706.07613 | d | d_2017_20|cs | — | clean(0/clean) | FAIL(2/missing_file) |
| 1803.02897 | d | d_2017_20|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| 1803.02918 | d | d_2017_20|eess-stat-etc | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1803.02994 | d | d_2017_20|cs | — | clean(0/clean) | FAIL(2/missing_file) |
| 1803.03110 | d | d_2017_20|math | — | clean(0/clean) | clean(0/clean) |
| 1803.03235 | d | d_2017_20|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| 1803.03249 | d | d_2017_20|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1803.08846 | d | d_2017_20|math | — | clean(0/clean) | clean(0/clean) |
| 1811.03615 | d | d_2017_20|hep-phys | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1811.03619 | d | d_2017_20|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1811.03624 | d | d_2017_20|astro-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 1811.10012 | d | d_2017_20|nucl | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1811.10029 | d | d_2017_20|hep-phys | — | clean(0/clean) | clean(0/clean) |
| 1811.10050 | d | d_2017_20|cs | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 1811.10148 | d | d_2017_20|astro-ph | — | FAIL(0/eps_image) | clean(0/clean) |
| 1907.03602 | d | d_2017_20|quant-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 1907.03821 | d | d_2017_20|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 1907.03868 | d | d_2017_20|cs | — | clean(0/clean) | FAIL(2/missing_file) |
| 2003.03387 | d | d_2017_20|astro-ph | — | pdf~(90/undefined_cs) | FAIL(2/missing_file) |
| 2003.03479 | d | d_2017_20|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2003.03510 | d | d_2017_20|math | — | pdf~(0/clean) | clean(0/clean) |
| 2003.10723 | d | d_2017_20|math | — | FAIL(0/eps_image) | clean(0/clean) |
| 2009.03673 | d | d_2017_20|cs | — | FAIL(0/eps_image) | clean(0/clean) |
| 2009.03686 | d | d_2017_20|hep-phys | non-utf8 | clean(0/clean) | FAIL(2/missing_file) |
| 2009.03699 | d | d_2017_20|eess-stat-etc | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2009.03736 | d | d_2017_20|math | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2009.10977 | d | d_2017_20|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 2105.03750 | e | e_2021_25|astro-ph | — | clean(0/clean) | FAIL(2/missing_file) |
| 2105.03798 | e | e_2021_25|math | — | FAIL(0/clean) | FAIL(2/missing_file) |
| 2105.03943 | e | e_2021_25|cs | — | clean(0/clean) | clean(0/clean) |
| 2105.11393 | e | e_2021_25|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 2203.04298 | e | e_2021_25|cs | — | pdf~(0/clean) | clean(0/clean) |
| 2203.12999 | e | e_2021_25|cs | — | clean(0/clean) | clean(0/clean) |
| 2203.13055 | e | e_2021_25|cs | — | clean(2/syntax) | FAIL(2/missing_file) |
| 2203.13064 | e | e_2021_25|cs | — | clean(0/clean) | clean(0/clean) |
| 2203.13079 | e | e_2021_25|eess-stat-etc | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2211.04450 | e | e_2021_25|math | — | clean(0/clean) | FAIL(2/missing_file) |
| 2211.04453 | e | e_2021_25|cond-mat | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2211.04457 | e | e_2021_25|hep-phys | — | pdf~(3/other) | FAIL(2/missing_file) |
| 2211.04503 | e | e_2021_25|astro-ph | — | pdf~(0/clean) | FAIL(0/latex209) |
| 2211.04515 | e | e_2021_25|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2211.12986 | e | e_2021_25|eess-stat-etc | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| 2308.04174 | e | e_2021_25|math | non-utf8 | clean(0/clean) | FAIL(2/missing_file) |
| 2308.04188 | e | e_2021_25|cs | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2308.04212 | e | e_2021_25|eess-stat-etc | — | pdf~(0/clean) | FAIL(4/undefined_cs) |
| 2308.04217 | e | e_2021_25|hep-phys | — | pdf~(0/clean) | FAIL(2/missing_file) |
| 2308.04280 | e | e_2021_25|cond-mat | — | clean(0/clean) | FAIL(2/missing_file) |
| 2308.12610 | e | e_2021_25|cs | — | clean(0/clean) | clean(0/clean) |
| 2308.12712 | e | e_2021_25|cs | — | clean(1/other) | FAIL(3/missing_file) |
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
| 2410.06028 | e | e_2021_25|cs | — | clean(1/other) | FAIL(2/missing_file) |
| 2410.17992 | e | e_2021_25|quant-ph | — | pdf~(0/clean) | FAIL(2/missing_file) |
| astro-ph/0501439 | a | a_pre2007|astro-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| astro-ph/0501590 | a | a_pre2007|astro-ph | — | FAIL(53/missing_file) | FAIL(2/missing_file) |
| astro-ph/0605290 | a | a_pre2007|astro-ph | — | pdf~(64/missing_file) | FAIL(2/missing_file) |
| astro-ph/0605361 | a | a_pre2007|astro-ph | — | FAIL(0/eps_image) | clean(0/clean) |
| astro-ph/9703134 | a | a_pre2007|astro-ph | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| astro-ph/9703198 | a | a_pre2007|astro-ph | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| astro-ph/9910044 | a | a_pre2007|astro-ph | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| cond-mat/0111097 | a | a_pre2007|cond-mat | 209suspect,non-utf8 | reject(-/inject_reject) | reject(-/inject_reject) |
| cond-mat/0307578 | a | a_pre2007|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| cond-mat/0307744 | a | a_pre2007|cond-mat | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| cond-mat/0501109 | a | a_pre2007|cond-mat | — | FAIL(0/eps_image) | pdf~(0/clean) |
| cond-mat/0605032 | a | a_pre2007|cond-mat | — | FAIL(0/eps_image) | clean(0/clean) |
| cond-mat/9703223 | a | a_pre2007|cond-mat | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| cond-mat/9910214 | a | a_pre2007|cond-mat | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| cs/0307009 | a | a_pre2007|cs | — | FAIL(0/eps_image) | clean(0/clean) |
| hep-lat/0111059 | a | a_pre2007|hep-phys | — | FAIL(334/missing_file) | FAIL(2/missing_file) |
| hep-ph/0111245 | a | a_pre2007|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| hep-ph/0605178 | a | a_pre2007|hep-phys | — | clean(0/clean) | FAIL(2/missing_file) |
| hep-ph/9703202 | a | a_pre2007|hep-phys | — | no_main_tex(-/-) | no_main_tex(-/-) |
| hep-ph/9703402 | a | a_pre2007|hep-phys | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| hep-ph/9910373 | a | a_pre2007|hep-phys | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| hep-ph/9910443 | a | a_pre2007|hep-phys | non-utf8 | pdf~(0/clean) | pdf~(0/clean) |
| hep-th/0501161 | a | a_pre2007|hep-phys | — | clean(0/clean) | clean(0/clean) |
| hep-th/9703099 | a | a_pre2007|hep-phys | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| hep-th/9703173 | a | a_pre2007|hep-phys | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| hep-th/9910028 | a | a_pre2007|hep-phys | — | no_main_tex(-/-) | no_main_tex(-/-) |
| math/0307077 | a | a_pre2007|math | non-utf8 | FAIL(0/eps_image) | FAIL(2/missing_file) |
| math/0307301 | a | a_pre2007|math | — | clean(0/clean) | clean(0/clean) |
| math/0501060 | a | a_pre2007|math | — | FAIL(0/eps_image) | clean(0/clean) |
| math/0605628 | a | a_pre2007|math | — | clean(0/clean) | clean(0/clean) |
| nucl-th/0111058 | a | a_pre2007|nucl | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| physics/0307021 | a | a_pre2007|hep-phys | — | FAIL(100/missing_file) | FAIL(2/missing_file) |
| physics/0605206 | a | a_pre2007|hep-phys | — | FAIL(0/eps_image) | FAIL(2/missing_file) |
| q-alg/9703046 | a | a_pre2007|math | 209suspect | reject(-/inject_reject) | reject(-/inject_reject) |
| quant-ph/0111094 | a | a_pre2007|quant-ph | — | FAIL(0/eps_image) | clean(0/clean) |
| quant-ph/0605205 | a | a_pre2007|quant-ph | — | FAIL(0/eps_image) | FAIL(2/missing_file) |

## 6. 与 corpus_v2 基线对比 (v2: n=40 分层, 同冷沙箱口径)

| 指标 | corpus_v2 (n=40) | corpus_v3 (本轮) |
|---|---|---|
| tectonic clean率 | 8/40 = 20.0% | 62/175 = 35.4% |
| tectonic pdf率 | 24/40 = 60.0% | 102/175 = 58.3% |
| xelatex clean率 | 4/40 = 10.0% | 48/175 = 27.4% |
| xelatex pdf率 | 6/40 = 15.0% | 54/175 = 30.9% |
| 联合pdf | — | 120/180 = 66.7% |

## 7. 对 M2 ≥90% 目标的可行性

- tectonic: pdf 102/175 (58.3%), clean 62/175 (35.4%), top FAIL: eps_image×46, missing_file×11, clean×3
- xelatex: pdf 54/175 (30.9%), clean 48/175 (27.4%), top FAIL: missing_file×106, latex209×1, undefined_cs×1
- 联合天花板: 任一引擎 pdf 66.7%, clean 44.4% —— fixloop+路由+normalize 需要补的百分点即 90%−此值

### 口径备注

- xelatex 跑在冷 TEXMF 沙箱(每篇独立 TEXMFHOME/VAR/CONFIG → 不继承用户已装包), tectonic 用自带 bundle(缓存热身后即暖); 判定器为产品 judge(v2 内嵌版退役), 红线集见 engine.WARNING_RED_LINES。
- \documentstyle 已降级为 latex209_suspect 试编标记(route 不再 reject)——真实试编, FAIL 计入管线缺口; fixloop 侧 latex209_reject gate 在真 2.09 错时兜底拒。inject 层拒绝记 inject_reject:latex209 类。

