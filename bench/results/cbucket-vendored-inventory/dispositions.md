# C-bucket vendored 候选清单处置（2026-09-17）

接 cbucket-scout 报告：从 83 个 off-CTAN/off-TL 缺件里按格数取 Top ~20（含同族归并共 35 行，`inventory.jsonl`）。格数口径 = stagerun loop1 cases.jsonl 按格去重（一格命中同一文件多次记 1）。

## 处置分布

| 处置 | 文件数 | 代表 |
|---|---|---|
| vendored（许可明确可再分发） | 8 | aastex×2、psfig、iopart、iopams、elsart、emulateapj、imsart |
| vendored-if-header-ok（大概率自由但收前核件头） | 6 | espcrc×2、citesort、texsort、eqsecnum、apjfonts |
| stub（许可禁再分发或无许可） | 18 | aa、tcilatex、JHEP3/jheppub/JHEP/jinstpub、svjour×3、diagrams、slashbox、aipproc、aaspp4、aasms4、axodraw、conm-p-l、siamltex、epl2、undertilde |
| mechanism（非 vendor 事） | 1 | mn2e.cls → peer1 doc→tex 重定位修 |
| unfixable | 1 | default.sty 伪件名 |

## 逐件处置

### vendored 组（许可已核实）

**aastex.cls（257 格）+ aastex62.cls（9）** — AAS 官方 LPPL-1.3c，CTAN 包页明标 "Contained in TeX Live as aastex"（TL 侧 tlpdb 壳无 runfile 是发行缺口非许可问题）。收法：`aastex.cls` 要的是 v5.x/v2 时代真件（arXiv 自带件/wayback 取）；`aastex62.cls` AAS 站 v6.2 直链可取。LPPL 允许原样再分发。

**psfig.sty（188，另 +18 无扩展名命中）** — 209 时代 graphics 宏，CTAN obsolete 区有档。件头自由文本（Darrell 1991）。收前扫一遍件头留证。

**iopart.cls（133）+ iopams.sty（60）** — IOP 期刊 class。关键发现：件头明写 "Licensed under the LPPL … Current Maintainer: IOP Publishing Ltd"——IOP 网站对 *文章* 的版权政策与 class 文件许可无关。**LPPL → vendored 直接收**。

**elsart.cls（87）** — Elsevier 旧 class，件头明写 LPPL-1.2（已核实原文件）。曾在 CTAN `/macros/latex/contrib/supported/elsevier`，被 elsarticle 取代后撤档；wayback/镜像/arXiv 自带件可取。**vendored 收**。

**emulateapj.sty（12）+ emulateapj5.sty（8）** — CTAN 有档 LPPL（ApJ 排版仿真，Vikhlinin/TeXnology）。直接收；5.x 旧版走历史件。

**imsart.cls（14）** — IMS class，CTAN 在档 LPPL；tlpdb 无 imsart 包是 TL 发行缺口。收。

### vendored-if-header-ok 组（收前核件头，核不过降 stub）

**espcrc2.sty（55）/ espcrc1.sty（13）** — Elsevier ESP CRC 套件，与 elsart 同族，大概率同 LPPL；取件核头后定。
**citesort.sty（31）/ texsort.sty（16）/ eqsecnum.sty（27）** — 209 时代小宏，CTAN obsolete 区；自由文本概率高。都是小件，即使核不过 stub 也便宜。
**apjfonts.sty（30）** — AAS 老字体宏，随 aastex 族；核头后定。

### stub 组（许可禁/无再分发）

**svjour.cls（28）/ svjour3.cls（20）/ svjour2.cls（8）** — Springer © 明示 "only allowed to be used when submitting to a journal published by Springer"（已核实）。**不可 vendored**。svjour3 还有 `svglov3.clo` 等 .clo 伴生件——stub 需把 clo 依赖一起吃掉。
**aa.cls（101）** — © EDP Sciences 作者用途限制。已有 aa.cls legacy shim 车道，沿用。
**tcilatex.tex（72）** — MacKichan Scientific Word 运行时宏，商业专有。只 stub。
**JHEP3.cls（41）/ jheppub.sty（37）/ JHEP.cls（10）/ jinstpub.sty（12）** — © SISSA/IOP 投稿用途限制。stub。
**diagrams.sty（31）** — Paul Taylor 交换图宏，CTAN 在档但 "no redistribution"（TL 除名原因）。**不可 vendored**；stub 难——\diagram DSL 只能吃体降级。
**slashbox.sty（28）** — CTAN 在档但无许可声明（TL 除名原因）。**不可 vendored**；stub 极易（\slashbox 单 cs）。
**axodraw.sty（25）** — Vermaseren 非商用许可（TL 除名原因）。stub 难（费曼图 \AXO 族）；替代路线=建议用户迁移 axodraw2（TL 有）——登记为 advisory 类提示也行。
**aipproc.cls（27）/ aaspp4.sty（24）/ aasms4.sty（24）/ conm-p-l.cls（13）/ siamltex.cls（7）/ epl2.cls（8）** — 出版社套件，许可文核过后若 LPPL 可升级；默认 stub。
**undertilde.sty（8）** — 无许可小件，stub \utilde 即可。

### 特殊

**mn2e.cls（127）** — TL mnras 包有真件但发在 doc/ 位，是 install 机制缺口而非 vendored 件，归 peer1 已派的 doc→tex 重定位修，**不建 vendored 件**（建了反而遮蔽机制修的覆盖）。
**default.sty（9）** — 伪件名（本地工程 \input{default}），登记排除。

## 收集面小计

vendored+vendored-if-header-ok 覆盖约 **880 格**（aastex 266+psfig 206+iop 193+elsart 87+emulateapj 20+imsart 14+if-ok 组 ~155），stub 组覆盖 **~470 格**（含 aa.cls 101 既有 shim）。两组合力把 off-CTAN 首命格的主体吃完；死格预期从 72 unfixable 再降一档，degraded→clean 升档面更大。
