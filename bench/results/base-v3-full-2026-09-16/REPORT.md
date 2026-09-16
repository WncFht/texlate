# base-v3-full — corpus_v3 全量 base 编译基线（§7.4 compile 门）

两轮合跑：R1 三 manifest（core+booster+hot, n=1259）14:16 收；按 leader 指示增量并入 manifest_expand（+3800）续跑，~15:35 全部完成。**终态 n=5059 papers × 双引擎 = 9968 格，0 harness_crash**。`compilebench_v3.py` baseline 臂（原文直编，不注入不修复），jobs=4。

- 语料：corpus_v3 全部已物化篇目——core 1000 + booster 187 + hot 72 + expand 3800（booster 另 13 条未物化未入样）。
- 75 篇 `no_main_tex`（core 10 / booster 21 / expand 44）无编译格 → 每引擎实跑 n=4984；no_source 0。
- src 冻结：脚本不认 `TEXLATE_SRC`，走镜像树 `tmp/exp/cbv3-base/`（src→`tmp/exp/src-snapshot-base` 软链 + 脚本原样拷贝）。**快照早于 bwrap Linux 沙箱（task #15）**——本轮 sandbox=env 白名单口径，与历史 v3/v4 run 一致。

## 1. 总分布

| 引擎 | n | clean | pdf~ | FAIL | clean率 | pdf率 |
|---|---|---|---|---|---|---|
| xelatex | 4984 | 1392 | 520 | 3072 | 27.9% | 38.4% |
| tectonic | 4984 | 1536 | 1436 | 2012 | 30.8% | 59.6% |

联合覆盖（5059 篇）：任一引擎出 pdf **3605 (71.3%)**；任一引擎 clean 2034 (40.2%)；**双引擎皆死 1454 (28.7%)**。全集口径与此前 n=180 抽样同向（抽样 xel pdf 33.1%/tec 62.8%），无抽样偏差。

## 2. FAIL 归因直方图（verdict=FAIL 格）

xelatex 3072 FAIL：missing_file **2918 (95%)**、pdftex_prim 81、latex209 44、emergency 6、syntax 4、other 4、already_def 3、fontspec_missing 2、undefined_cs 2。

tectonic 2012 FAIL：eps_image **1311 (65%)**、missing_file 348、missing_pfb 78、undefined_cs 77、syntax 46、pdftex_prim 38、other 35、already_def 10。

xelatex missing_file top payload：revtex4.cls 747、revtex4-1.cls 289、algorithm.sty 174、revtex.cls 166、IEEEtran.cls 113、epsf.sty 109、binhex.tex 87、aastex.cls 82、ulem.sty 78、elsarticle.cls 71、algorithmic.sty 65、revtex4-2.cls 64。**口径**：baseline 臂 compile() 不触发 tlmgr usermode 安装（装包是 fixloop 职责）——missing_file = 「宿主 TeX Live 缺包」的源依赖缺口，正是 fixloop install 规则主战场；revtex 家族合计 ~1300 格，是单一最大可修簇。

tectonic missing_file top：aa.cls 32、iopart.cls 28、mn2e.cls 27、tcilatex.tex 24、elsart.cls 21、pstricks.sty 20、revtex.cls 17、psfig.sty 16。eps_image 1311 是引擎能力边界（.eps/.ps 不可含），非源缺陷。

## 3. 按 era / layer 的 fail 率

| 维度 | n篇 | xel clean/pdf/FAIL | tec clean/pdf/FAIL |
|---|---|---|---|
| era=old | 1099 | 34% / 41% / 59% | 23% / 47% / 53% |
| era=new | 3960 | 26% / 38% / 62% | 33% / **63%** / 37% |
| layer=core | 1000 | 29% / 40% / 60% | 32% / 61% / 39% |
| layer=booster | 187 | 25% / 40% / 60% | 21% / 64% / 36% |
| layer=expand | 3800 | 28% / 38% / 62% | 31% / 59% / 41% |
| layer=hot | 72 | 17% / 32% / 68% | 18% / **76%** / 24% |

模式稳定：**xelatex 老论文更好**（old FAIL 59% < new 62%）——老论文依赖朴素；**tectonic 新论文碾压**（new 63% vs old 47% pdf）——bundle 新但吃不了 eps/209。expand 层分布与 core 几乎重合（38% vs 40% xel pdf），证明 expand 抽样与核心层同质。

## 4. xelatex vs tectonic 差异（agreement matrix，5059 篇）

| xelatex \ tectonic | clean | pdf~ | FAIL | no_main |
|---|---|---|---|---|
| clean | 894 | 55 | 443 | — |
| pdf~ | 22 | 309 | 189 | — |
| FAIL | 620 | 1072 | 1380 | — |
| no_main_tex | — | — | — | 75 |

- tectonic 救回 xelatex-FAIL **1692 篇**（620 clean + 1072 pdf~）——基本是 xelatex missing_file 被 tectonic 自拉 bundle 解决。
- xelatex 救回 tectonic-FAIL **632 篇**（443 clean + 189 pdf~）——eps_image/209 侧。
- 同 clean 894；同死 1380（真·双引擎都救不了的源缺陷核）。

## 5. 杂项实录

- 超时：tectonic 15 格（240s cap）、xelatex 1 格。单格中位 xel 0.4s / tec 1.0s；p95 4.1s / 12.2s；max 240.1s / 480.3s。
- route 实录：latex209_suspect 441 篇（真判 latex209 仅 44——多数 suspect 并非 2.09 或先倒在 missing_file）；non_utf8 500 篇。
- FAIL 但 category=clean/None 的 ~52 格 = 无 pdf 且 parse_log 未归类，留待人工抽查。
- no_main_tex 75 篇明细在 cells.json（expand 44 篇偏多——IA member 里有 tcilatex 碎片/无主文档树）。

## 6. 对 M2 ≥90% 的含义

双引擎联合 pdf 天花板 **71.3%** → fixloop+路由+normalize 需补 **18.7pp** 到 90%；单 xelatex（产品主引擎）缺口 **51.6pp**，其中 95% 由 missing_file 构成——**usermode 装包是决定性的单一杠杆**（revtex4 一族即 ~26% 的 xel FAIL）。tectonic 臂 eps_image(1311) 归路由选 xelatex 可解；同死核 1380 篇（27%）是 fixloop 的真实战场。
