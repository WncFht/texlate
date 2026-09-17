# C-bucket true-CTAN-missing 侦察（2026-09-17）

派工口径：摸清 C 桶"真·CTAN 缺件"残量——实测格数与签名分布、缺席 cls/sty 清单、本机 tlmgr 装不了的原因归类、tectonic bundle 方案可行性与体积代价、更轻的 vendored-shim 路线。只读侦察，src/git 未动。

数据源：`stagerun-loop1-2026-09-16/cases.jsonl`（6573 fixloop 格，xelatex 唯一臂）+ `records/{compile,fixloop}.jsonl` + `realn200-2026-09-17/results.json`（200 id × pipe-xel 臂）。**两数据集均无 tectonic 臂**——C 桶 deferred 理由是前瞻性的（产品路由 `route.engines` 已产 `["tectonic","xelatex"]`），非现有数据里的实际死格。

## 一句话结论

"true-CTAN-missing ~80 格"这个存量在 xelatex 臂上**基本不存在**：missing_file 命中格 87.5% 已被 install 机制救回，真残 22 格且没有一格是"CTAN 有但装不上"。真缺口是 **off-CTAN 期刊宏**（无包可装，靠 shim/平铺遮蔽）与 **tectonic 臂的前瞻通路**（无 tlmgr，bundle 无解 off-CTAN）。

## 实测格数与分布

### stagerun loop1 fixloop 臂（主口径）

- 2177 格在 ≥1 个 fixloop round 命中 `missing_file`，涉及 **207 个不同文件名**。
- 结局分布：rescued **1904 格（87.5%）**＝clean 609 + acceptable_pdf 605 + best_effort_pdf 681 + max_rounds 9；`unfixable`（last-cat 已非 missing_file，死在他错上）251 格；**last round 仍 missing_file 仅 22 格**。
- 按文件 on/off CTAN 拆（同一格可命中多文件，归类按是否命中 off-CTAN 名单优先）：
  - **命中 off-CTAN 件的格：1131** → clean 340 / acceptable 364 / best_effort 353 / unfixable 72 / reject 2。缺件不必然死 PDF——nonstopmode 跳过缺文件继续编，宏未被调用处照常出纸（degraded 口径）。
  - **只命中 on-CTAN 件的格：870** → clean 227 + acceptable 204 + best_effort 276（81% 收敛）/ unfixable 152 / max_rounds 9。
- fixloop `installed` 清单实证 install 通路大规模生效：revtex4.cls ×430、epsf ×325、ulem ×163、pst-node ×129、revtex4-1 ×115、algorithm ×112、llncs.cls ×85、tensor ×83、pstricks ×81……（tlmgr usermode 直装，全 tex/ 树下可寻址件）。

### n200 real 臂（旁证）

- `compile.first_error` missing_file 20 格 / 14 文件；final verdict missing_file **19 格 / 14 文件**——名单高度重合于 off-CTAN：aastex.cls 3、iopart.cls 3、mathcomp 2、elsart/aa/mn2e/vaucanson-g/diagrams/diagxy/eqnarray/autobreak/misccorr/slashbox/xetex-inputenc 各 1。
- n200 无 fixloop 救援臂（实录即终态），数字是"裸管线自然残量"，与 stagerun 装后残量口径不同。

### last-round 仍 missing_file 的 22 格成分

全是**非 cls/sty 缺件**：`.eps` 图源缺失（FIGS/bz_aa.eps、normal.eps、bar_plot.eps…——源包本身没带图，任何安装通路都救不了）、`aaspp4.sty`/`apjpt4.sty`（latex209 reject 策略格）、`这是译文` ×4（mask 伪件名，非真文件）。**无一格是"CTAN 有件但装不上"**。

## 缺席件分类

### OFF-CTAN（无包可装，shim/vendored 唯一出路）——83 文件 / 首轮命中 ~510 格

期刊绝版宏件为主，tlmgr/CTAN 均无发行：

| 文件 | 首命格数 | 性质 |
|---|---|---|
| aastex.cls | 85 | AAS 旧版 class（aastex6 才是现行） |
| psfig.sty | 69 | psfrag 时代图形宏，pslatex 陪葬品 |
| iopart.cls | 44 | IOP 期刊 class，期刊站直发 |
| aa.cls | 33 | A&A class——已有 legacy shim 车道 |
| elsart.cls | 27 | Elsevier 绝版（elsarticle 是现行） |
| tcilatex.tex | 23 | TCI Scientific Word 转储宏 |
| eqsecnum / JHEP3 / aaspp4 / svjour / slashbox / jheppub / apjfonts / aipproc / diagrams / aasms4 / citesort | 7–15 各 | 期刊/史前宏群 |

（格数为首轮命中口径；多数格经 degraded/best_effort 仍出 PDF。）

### ON-CTAN（tlmgr 可装，机制已工作）——60 文件 / 首轮命中 ~195 格

mn2e.cls ×42、tensor.sty ×18、llncs.cls ×16、pst-* 簇 ~50、simplewick ×7、lgrenc.def ×7（→greek-fontenc）、feynmp-auto ×6、kotex.sty ×3（→cjk-ko）等。`tlmgr search --file` 逐件核实：**除 mn2e.cls 外全部落 `texmf-dist/tex/latex/` 可寻址位**，usermode install 直接救。

## "tlmgr 装不了"归因——本机实测结论

本机 tlmgr usermode **工作是常态**（stagerun installed 清单上千次成功为证；`tlmgr search --global --file` 实测连通）。真缺口只有三类：

1. **off-CTAN 件**（上表）——根本不是"装不了"，是"没包可装"。占真残量的绝对主体。
2. **doc-only 位**（mn2e.cls 唯一实证）——mnras 包把它发在 `texmf-dist/doc/latex/mnras/LEGACY/mn2e.cls`，tlmgr 装完 kpsewhich 仍找不到（doc 树不在 TEXINPUTS）。`_fetch_into_usertree` 按 tlpdb relpath 放件同样落 doc/，救不了。n200 mn2e 格即此死法（verdict 终态 missing_file）。修法不是 bundle，是**装后重定位**：install 后 kpsewhich 复核，miss 则从 usertree doc 位 copy/link 进 `tex/latex/` 或 cwd 平铺。
3. **tectonic 臂无 install 通路**——`TectonicEngine.caps={"bundle"}`，`install_file` 本机无解，全靠 fixloop 注入的 `ctan_fetch`（`fixloop/engine.py:1181-1203` 接 `CtanFetcher`）把件平铺进 workdir。cwd 平铺对 on-CTAN 件有效，对 off-CTAN 件连源都没有，对 bundle 缺件同样无解。

## tectonic bundle 方案评估

- 现状：pin `TECTONIC_BUNDLE_PIN=tlextras-2022.0r0.tar`（engine.py:65）；本机 tectonic 0.15.0，`--web-bundle` 才收 URL（`--bundle` 只吃本地路径，0.17+ 才合并）；`~/.cache/Tectonic` 已存 216M。
- 官方 bundle 解决不了问题：tlextras 系列同样只发 CTAN 现役件，aastex/psfig/iopart 这类绝版件不在任何官方 bundle 里——换 bundle 对 off-CTAN 主体**零收益**。
- 自建 bundle 可行但代价不划算：tectonic bundle = tar + SHA256SUM 索引，技术上可把 off-CTAN vendored 件打进去，但每格都要 `--web-bundle` 指向自建源（或本地 tar），部署/分发/版本管理成本全来了，而受益面只是 tectonic 臂的 off-CTAN 格。
- 体积代价参考：全量官方 bundle ~GB 级下载 / 216M+ 缓存；自建最小 bundle（~20 个 cls/sty，<1MB）虽轻但要自建索引与托管。**结论：bundle 路线对这个桶是重炮打蚊子。**

## 更轻路线：vendored-shim（推荐）

`ctan_fetch` 的 cwd 平铺遮蔽已是实证机制——文件落进 workdir 即被两臂同式解析（TEXINPUTS 的 `.` 恒在首位）。把这个原语从"CTAN 拉件"扩成"repo vendored 件直放"即可覆盖整个 off-CTAN 桶：

- 路线：`texlate/vendor/`（或 fixloop rules 资源位）收 ~20 个绝版 cls/sty 真件或最小 stub（aa.cls legacy shim、aastex-stub fixer 是既有先例车道）；fixloop `missing_file` 命中 off-CTAN 名单时 `vendored_fetch` 平铺进 workdir——xelatex/tectonic 两臂同式生效，零 bundle、零安装、零网络。
- 版权注意：期刊 class 多为 LPPL/自有许可，vendored 真件需逐件核许可；核不过的走 stub（提供最小宏面让编译过，输出 degraded 标）。
- 与 mn2e 修法同构：mn2e 可以不走 vendor，直接"install 后 doc→tex 重定位"或 ctan_fetch 平铺（mnras 在 CTAN，fetcher 能拉到真件）。

## 建议（给下一波备弹药）

1. **不建 tectonic bundle**——对 off-CTAN 主体无效，成本不对称。
2. **vendored-shim 车道**（归 peer1 compile/fixloop 或 1d）：off-CTAN 名单 ~20 件收 vendor/stub，fixloop 加 `vendored_fetch` 动作（复用 ctan_fetch 平铺原语）——覆盖 ~1131 格中的 unfixable 72 死格 + 把 717 格 degraded 提升档。许可核不过的上 stub。
3. **mn2e 重定位小修**（peer1）：`install_file` 后 kpsewhich 复核 miss → usertree doc 位捞件进 tex/ 或 cwd；连带覆盖一切 doc-only 件。
4. `.eps` 图源缺格（残 22 中主体）不是本桶事——源包缺资产，登记口径即可。

30min 硬停前完成：口径实测、on/off-CTAN 拆分、tlmgr 归因、bundle 评估、shim 路线。未动 src/git。
