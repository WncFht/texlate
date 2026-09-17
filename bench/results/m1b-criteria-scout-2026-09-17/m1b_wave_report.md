# M1-B 判别面波报告：72 格深链残余清单（texlate-2f）

> 链：`parse --rerun → xlat --arm mock --rerun → compile --arm zh --xlat-arm mock --rerun → fixloop --on all --rerun`（rerun-wave.sh `--stage deep`，jobs 8），id 集 `m1b_filtered_ids.txt`（T1 58 arg-被吃确诊 + T2 14 数学吃），跑于 `746237f`（_WS_NOPAR 原子组 ReDoS 修）+ illegal_unit parse 修法全落地后的当前码。records commit 见 git log。
> 本波为**判别面产出**：清单 = 当前码下真损伤残余，供 peer1/1d 立规/段修判据。逐格明细 `m1b_wave_residue.jsonl`。

## 0. 链上结果

parse 72/72 ok → xlat mock 72/72 ok → compile clean49/partial15/fail8 → fixloop **clean53/partial19/fail0**。

**end-state pdf 72/72 = 100%**（clean 53 + partial 19）。零 unfixable、零 fail。

## 1. 残余面 = 19 格 partial（按机制簇归并）

| 簇 | 格数 | 格 | 判据素材 |
|---|---|---|---|
| illegal_unit 残漏 | 4 | 0806.2890、1404.5889、1706.02769、hep-th/9703214 | 修法后主面已消但 `Missing number` 族仍漏（error_cats 带 illegal_unit:2-14）——段修判据：数字尾参覆盖未全 |
| syntax 重伤（疑 T2 数学吃残） | 3 | math/9901091（5843 errs, syntax 4976）、1404.0443（333, syntax 182）、hep-ph/0104029（61, syntax 59） | 数学/对齐环境级联错位——Misplaced &/\cr、Bad math delimiter 族 |
| stub/shim 宏包缺件 | 5 | 1206.1835（diagrams.sty PostScript opt）、hep-ph/0605174（citesort.sty）、2104.00109（jinstpub.sty）、2104.00118（hxetex.def）、hep-th/9703214（fivmi 字体） | vendored 面外的非 vendored 包——stub 影子不承接 option/字体 |
| env/cs 未定义 | 3 | 0707.1588（proof env undefined）、hep-th/9703071（FEYNMAN + undefined_cs 127）、2104.00109（同 stub 簇交集） | 环境/宏未定义族 |
| 其他单点 | 4 | 1608.02624（float opt `H`）、1803.02902（babel catalan opt）、nlin/0104012（revtex \pacs 序）、1502.06189+2403.15096+physics/9901057（errs=0 但 partial——verdict 面零错仍 partial 的边界格 3） | 单点机制 |

sig 分布：clean 53 无 sig；acceptable_pdf 7 + 带负载 8（proof/H/hxetex.def/citesort.sty/FEYNMAN/catalan/diagrams.sty/jinstpub.sty）；best_effort_pdf 4（abstract×2、fivmi、裸 1）。

## 2. 对 T1/T2 判别的读法

- T1 arg-被吃 58 格：compile 后 49 clean 落袋——arg-吃的主伤在 illegal_unit+ReDoS 两修后**大面积已消**；残 9 格 partial 内 illegal_unit 簇 4 + 单点簇为主，stub 簇是编译层缺件非 arg-吃。
- T2 数学吃 14 格：syntax 重伤簇 3 格是本簇真残（math/9901091 5843 errs 为最重单格——align 环境吃透伤），其余 T2 格已翻 clean/acceptable。
- **errs=0 仍 partial 3 格**（1502.06189、2403.15096、physics/9901057）：post-compile verdict 零 error 但 verdict=partial——verdict 口径边界格，值得 peer1 看一眼是否判据偏保守。

## 3. scorecard 位移

波后 cells=5124 pdf=5016(97.89%) clean=4355(84.99%)——cells/pdf 各 +7 系他线新格入分母非本波位移；本集格原已在 pdf 面（fixloop acceptable/best_effort 历史末条），翻转收益主要体现在 partial→clean 质量面（集内 end-clean 53）而非 pdf 计数。end-state 归因面 fixloop:clean 796→847(+51)、compile:clean 3555→3508(-47)——compile-clean 格经 fixloop 末条重写后归 fixloop:clean 桶，同 clean 终态不同归因。

## 4. 残余清单文件

`m1b_wave_residue.jsonl`——72 行逐格：fix_status/verdict/sig/csb/n_errors/error_cats/first_error/rounds。peer1 立规取 sig+first_error+error_cats 面；1d 段修取 illegal_unit 簇与 syntax 簇格。
