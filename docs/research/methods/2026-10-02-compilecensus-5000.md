# compilecensus 5000 篇原文直编普查：缺件面现状（2026-10-02）

> **结论**：全语料非偏抽样 5,000 篇原文直编——clean 57.9% / partial 21.3% / fail 15.3% / reject 5.4%。fail 的 92%（708/767）是 missing_file 单一签名，且其中 91%（645 篇）撞的件 vendor 库已备——缺件病的主体是 2012 年前物理/天文期刊的绝版宏包，已被备件库正面压住；真暴露缺口 63 篇（1.3%），散布在 ~50 种单例文件上。CS 论文缺件率 4.7%，为物理邻域的 1/4 到 1/8，且无一集中签名。
> **状态**：时点证据（compilecensus/2026-10-02/compilecensus run 终态，rn=1 dedup 还原）
> **日期**：2026-10-02

## 1. 设计

spec `compilecensus`（compilebench 兄弟件，stage fn/select 全复用）：13 个非偏 manifest 并集（dev_failmine 刻意剔除，防 fail 富集污染分母）∩ 湖可供应格，stratum_cell 分层等比抽 5,000（seed=20261002）。网格 baseline×xelatex 单格——量的是「原文本身在现代 TeX Live 下缺不缺件」一维；冷 usertree + TUNA tlpdb 自动装包在格内生效，vendor/fixloop 备件不进本臂（它们属修复链资产）。

## 2. 总账

| 终态    | 篇数  | 占比  |
| ------- | ----: | ----: |
| clean   | 2,896 | 57.9% |
| partial | 1,067 | 21.3% |
| fail    | 767   | 15.3% |
| reject  | 270   | 5.4%  |

fail 签名分布：missing_file 708（92.3%）独大；其余为 pdftex_prim 21、syntax 9、inputenc_unicode 4、runaway_output 4 等散件（17 种合计 59 篇）。缺件是原文直编失败的唯一系统性死因。

## 3. missing_file 拆解

708 篇 missing_file 按撞件拆：

| 桶          | 篇数 | 占比  | 说明                                                                       |
| ----------- | ---: | ----: | -------------------------------------------------------------------------- |
| vendor 已备 | 645  | 91.1% | revtex.cls 179、aastex.cls 82、iopart.cls 43、mn2e.cls 39、psfig.sty 37 等 |
| vendor 未备 | 63   | 8.9%  | aastex631.cls 5、psfig.tex 4、PoS.cls 3、crckapb.cls 3 + 一长串单例        |

备件覆盖面的含义：这 645 篇在裸编译臂是 fail，走产品 fixloop 链（vendor 注入 + tlpdb 装包）时可回收——holdout-200 实测 fixloop 修复率 93%（45 试 42 救）支撑该判断。

## 4. 学科 × 年代分布

按 cat_group 的 fail 率（含全部签名）：

| 学科组   | 篇数  | fail | fail 率 |
| -------- | ----: | ---: | ------: |
| astro-ph | 732   | 293  | 40.0%   |
| nucl     | 108   | 31   | 28.7%   |
| cond-mat | 634   | 128  | 20.2%   |
| hep-phys | 1,093 | 178  | 16.3%   |
| quant-ph | 194   | 26   | 13.4%   |
| math     | 953   | 47   | 4.9%    |
| cs       | 815   | 38   | 4.7%    |

missing_file 按年代带集中：a_pre2007 各组合计 412 篇（58%），b_2007_11 约 102 篇——2012 年前物理/天文/核/凝聚态占缺件死的主体。死因明确：这批论文引用的是期刊私有宏包的废弃版本（REVTeX 3.1 `revtex.cls`、AASTeX <6 `aastex.cls`、IOP `iopart.cls`、MNRAS `mn2e.cls`/`mn.cls`、Elsevier `elsart.cls`/`espcrc2.sty` 等），均已从 CTAN/TeX Live 撤下。

CS 详目：38 篇 fail 中 missing_file 21 篇，件名全为单例散布（slashbox.sty 4 为最频），无期刊宏包级集中签名；其余 17 篇为 pdftex_prim 11 等通用故障。CS 缺件不成「病」，属长尾散布。

## 5. 判断

1. 「老论文/非 CS 论文才缺件」的假设在 5,000 尺度上成立：缺件死 92% 是 missing_file，其中近六成压在 2007 年前，学科 fail 率排序 astro-ph 40% > nucl 29% > cond-mat 20% > hep-phys 16%，cs 4.7% 垫底量级。
2. vendor 库的件选是对的——91% 的缺件撞件已在备件面内；裸编普查与修复链实测互相印证（holdout-200 fixloop 93% 修复率）。
3. 真缺口只剩长尾：63 篇散布 ~50 种文件，含已知孤儿件 PoS.cls（picins/fic-l/isolatin1 在本帧未撞见）及一批单例（aastex631.cls 版本文件名、crckapb.cls 等）。补件收益递减，按需补单例即可，不值得再铺面。
4. 对「新 CS 论文翻译交付」这个目标，原文缺件不构成主要风险面；e2e_eval_cs 专项帧（200 篇 2021+ CS）是交付率的直接证据源。
