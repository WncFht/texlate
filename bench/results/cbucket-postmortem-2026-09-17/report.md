# C-bucket 波后残面分析（492 格 postmortem）

数据源：`bench/results/stagerun-loop1-2026-09-16/`（wave-cbucket.log + records/{compile,fixloop}.jsonl + cases.jsonl）。波定义：`stagerun.py fixloop --rerun --on all --xlat-arm mock --jobs 8` 对 compile 末条 upstream=mock ∧ status=fail 的 492 格全量重跑（missing_file 队列，vendored_fetch `a90978a` 落地后首波）。每格取 fixloop 末条 mode=all 行 + case 末条 + compile 末条交叉核对，终报 clean 360 / partial 127 / fail 5，与波报一致。

## 终局分布与救活机制

492 格原始签名全部 `missing_file:*`。救活机制 × 终态交叉表：

| 救活机制 | clean | partial | fail | 合计 | clean 率 |
|---|---|---|---|---|---|
| vendored_fetch | 271 | 64 | 2 | 337 | 80.4% |
| legacy_pkg_shim | 88 | 62 | 0 | 150 | 58.7% |
| install_file | 1 | 1 | 0 | 2 | — |
| static_precheck 仅触达（未救活） | 0 | 0 | 3 | 3 | 0% |

verdict 分布：clean 295 / best_effort_pdf 121 / acceptable_pdf 70 / unfixable:* 4 / reject:latex209_reject 2。fixloop_verdict=clean 但 status=partial 的 1 格为分歧异常（见末节）。

## 5 个 fail 逐个 dossier

### 0707.4206 — unfixable:early_eof（vendored 接住 → option clash 新层墙）

原签名 `missing_file:elsart.cls`。rounds：missing_file → early_eof → 终。actions：static_precheck 装 8 个 pst-* 件 → `vendored[files] elsart.cls` 命中 → `_best_effort_pass` 兜底 err=3。post first_error：`xcolor.sty:265: LaTeX Error: Unknown option 'override' for package xcolor`——vendored elsart.cls 向系统 xcolor 传 `override` 选项，宿主 TeX Live xcolor 不识别，直接 early_eof。**真凶：vendored 件与系统包版本错位（option clash 层），vendored_fetch 本身工作正常；属 option_clash_passopts 类规则未覆盖的新面。**

### astro-ph/0408286 — unfixable:syntax（vendored-stub 接住 → 真 syntax 墙）

原签名 `missing_file:espcrc1.sty`。rounds：missing_file → undefined_cs:address → syntax → 终。actions：`vendored[stubs] espcrc1.sty` 命中 → cs_targeted_fix polyfill `\address` → 兜底 err=100。post first_error：`lugaroetal.tex:260: Missing } inserted.`**真凶：stub 接住缺件后文档宏面连锁暴露，polyfill 未覆盖的语法层坍塌；非 vendored 机制失效，是 stub 救活后第二/三层墙叠加超出规则面。**

### astro-ph/0104136 — reject:latex209_reject（LaTeX 2.09 设计拒修）

原签名 `missing_file:aaspp4.sty`。rounds 仅 1 轮 missing_file 即 reject，actions 只有 static_precheck，vendored_fetch 未触发。splice 实证 `\documentstyle[apjpt]{article}`（SmithV.tab1.tex:30）——真 LaTeX 2.09 文档。aaspp4.sty 虽在 inventory（stub 档），但 latex209_reject 门禁先行，属设计内拒修而非 shim 没接住。

### astro-ph/9910375 — reject:latex209_reject（同上）

原签名 `missing_file:aaspp4.sty`（round 实测 apjpt4.sty）。splice 实证 `\documentstyle[apjpt4,11pt]{article}`（tab1/tab2/tab3.tex:38-40），同为 2.09 拒修，vendored_fetch 未触达。

### hep-ph/0104121 — unfixable:undefined_cs（vendored 未触达：穿透型缺件）

原签名 `missing_file:eqsecnum.sty`（inventory stub_ready 档，本应可救）。rounds 仅 2：round-1 分类直接落 undefined_cs（missing_file 被 nonstopmode 穿透、未独立成轮），actions 只有 static_precheck + 兜底——**vendored_fetch 条件只在 missing_file 轮触发，穿透场景整个 vendored/shim 面被跳过**。post first_error：`fixes.sty:41: Undefined control sequence`（firstfigfalse，文档自带 fixes.sty 里的宏，推测本由 eqsecnum.sty 提供）。**真凶：round 分类错位导致救活规则未触达，是机制缝而非缺件本身难治。**

## 127 partial 组成

verdict：best_effort_pdf 85 / acceptable_pdf 41 / clean（分歧异常格）1。残墙（post 复判 category）分布：

| post_cat | 格数 | vendored 救活后撞墙 | shim 救活后撞墙 |
|---|---|---|---|
| undefined_cs | 48 | 27 | 20 (+install_file 1) |
| syntax | 37 | 11 | 26 |
| other（未分类错误） | 30 | 20 | 10 |
| env_undefined | 4 | 1 | 3 |
| already_def | 3 | 1 | 2 |
| illegal_unit | 2 | 2 | 0 |
| float_opt | 1 | 0 | 1 |
| missing_file（分歧格） | 1 | 1 | 0 |
| clean（acceptable 缺字格） | 1 | 0 | 1 |

全部 127 格都是「missing_file 被某机制解决后撞下一层墙」：vendored 救活的偏 undefined_cs（真件落地后暴露文档/伴船宏），shim 救活的偏 syntax（stub 面不足直接语法坍塌）。undefined_cs 高频 payload：twocolumn×5、addressmark×4、subclass×3、affiliation/collaboration@sw/plotone 各×2。另 22 格带残余 missing_chars（最高 1003.1956 ×16、1706.00222 ×15、1206.0719 ×12）。

## clean 翻转验真（抽 10 + 机制核对）

抽 10 格（seed=42）：hep-ph/9901283、0806.3715、1206.1777（elsart.cls）、0806.3501、nucl-ex/0408014（iopart.cls→iopart10.clo 二级缺件连锁）、0905.0537（diagrams.sty stub）、0707.3252（siamltex.cls shim）、1306.6282（mn2e.cls shim）、1206.0368（conm-p-l.cls shim）、astro-ph/9901205（aa.cls shim）。逐格核对 vendored_fetch 命中件名 == compile 末条原 missing_file payload（iopart 两格为命中 cls 后下一轮真实暴露 .clo 伴船再命中，链式对齐成立）；无 vendored 的格 actions 均有 `legacy_pkg_shim` stub 注入覆盖原缺件名。**10/10 真救活，无巧合翻转。** 推及全量：360 clean 中 271 走 vendored_fetch、88 走 legacy_pkg_shim、1 走 install_file，actions 面全部有对应救活规则痕迹。

## 分歧异常格：math--0408287

唯一 verdict=clean 而 status=partial 格。case 与 fixloop 终态均 clean（splice/main.log 末编零 `!`、elsart.cls 正常载入、6 页 PDF），vendored_fetch 17:33:22 落盘 splice/elsart.cls；但 post 复判记录 missing_file:elsart.cls + emergency stop（l2_attr 实锤该次编译确实未见此件），post pdf_bytes=74332 与 .fixloop-entry.pdf（缺件降级产物）字节级相同，而盘上 main.pdf=74162 为后续干净编译所覆。推断 post 复判跑在 vendored 落盘前的编译上下文（顺序/面不一致），1 格，建议跟进 stage_fixloop post 与 fixloop 终编的面一致性，不阻塞 ledger。

## 残面分类账

| 类 | 机制归因 | id 清单 |
|---|---|---|
| F-A vendored 接住→option clash 墙 | vendored elsart.cls 传 override 给系统 xcolor | 0707.4206 |
| F-B vendored-stub 接住→syntax 墙 | stub+polyfill 后真语法坍塌 | astro-ph/0408286 |
| F-C latex209 拒修 | 2.09 `\documentstyle` 设计门禁，vendored 未触达 | astro-ph/0104136, astro-ph/9910375 |
| F-D vendored 未触达（穿透型） | round-1 直接落 undefined_cs，vendored_fetch 条件不触发 | hep-ph/0104121 |
| P-undefined_cs | 救活后文档/伴船宏暴露 | 0707.4465, 1003.0732, 1003.4471, 1012.1584, 1206.0026, 1206.0719, 1206.5684, 1306.0259, 1404.0176, 1502.06317, 1706.00221, 1706.00371, 1803.03154, 1907.00292, 1907.03745, 1907.10363, 2105.11405, 2308.00026, astro-ph/0111197, astro-ph/0501259, astro-ph/0501428, astro-ph/9901011, astro-ph/9901037, astro-ph/9901091, astro-ph/9901145, astro-ph/9901236, astro-ph/9901389, astro-ph/9910001, astro-ph/9910131, astro-ph/9910477, chao-dyn/9901009, cond-mat/0104108, cond-mat/0111246, cond-mat/0307193, cond-mat/0307206, cond-mat/9901292, gr-qc/9901082, hep-ex--9910040, hep-ex/9910040, hep-ph/0111044, hep-ph/0408075, hep-ph/0408135, hep-ph/0408300, hep-th/0408113, math/9901064, nucl-th/0104004, patt-sol/9910002, quant-ph/0408002 |
| P-syntax | stub 面不足语法坍塌为主 | 0806.1897, 0905.0639, 0905.1170, 0905.1214, 1003.0067, 1003.0792, 1003.1105, 1012.2012, 1109.5364, 1206.1960, 1206.5304, 1306.6030, 1404.0033, 1404.5993, 1608.06845, 1706.00222, 1706.00224, 1803.03089, 1811.10292, 1907.03780, 2104.00067, 2104.00109, 2112.00025, 2211.04441, astro-ph/0104303, astro-ph/0111599, astro-ph/0307121, astro-ph/9703200, astro-ph/9901328, cond-mat/0104269, cond-mat/0307573, cond-mat/0605337, hep-th--9910145, hep-th/0307148, hep-th/0408134, hep-th/9910145, math/0408122 |
| P-other | 未分类残余错误 | 0806.2594, 0806.3286, 0905.0330, 0905.0946, 0905.2183, 0905.4200, 1003.1956, 1003.5240, 1012.1143, 1012.1161, 1206.0031, 1206.0291, 1206.0576, 1206.1835, 1404.0385, 1907.00076, 2104.00026, 2203.13069, astro-ph--0408445, astro-ph/0408240, astro-ph/0408445, astro-ph/0408494, astro-ph/0605512, astro-ph/9901028, cond-mat/0307221, hep-ph--0605174, hep-ph/0104104, hep-ph/0605174, hep-th/9910106, nlin/0104012 |
| P-env_undefined | 环境级未定义 | 1012.1059, 1206.0593, astro-ph/9901200, math/0104275 |
| P-already_def | 宏重定义 | 1206.0299, 1706.00106, 2105.03808 |
| P-illegal_unit | 非法单位 | hep-ph--0111062, hep-ph/0111062 |
| P-float_opt | 浮动体选项 | 0806.2574 |
| P-divergence | verdict/status 分歧（post 面不一致） | math--0408287 |
