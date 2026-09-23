# 失败签名 × strata 挖掘 —— fixloop 规则候选的方法与清单

> **结论**：把多臂编译结果（baseline 直编 / zh 注入编译 / fixloop 修复现场 / e2e 真翻译）按失败签名 × 语料分层（era × 学科组）交叉统计，能同时回答三件事——哪些失败集中在哪些 strata（booster 抽样 + 规则优先级用）、rules.yaml 还缺哪些签名覆盖、已有规则的实测 fires 与声明 stats 对不对得上。本批挖掘产出 ~20 条规则候选与 5 处分类学/路由层缺口，全部带 replay 验收标准。
> **状态**：时点证据（2026-09-16 数据口径）。清单中的高优先项已陆续落地为 fixloop 规则（missing_graphic、babel_opt、hyperref_driver、float_opt、latex209 tail 锚定、gate error-driven 化等，rules 分片以主仓为准）；方法论本身仍现行——任何新批次 bench 都可复跑同一挖掘流程。
> **日期**：2026-09-16（2026-09-20 迁入重编）

## 数据源与口径

| 源（评测产物轮次）      | 样本                                  | 口径                                        |
| ----------------------- | ------------------------------------- | ------------------------------------------- |
| compilebench-v4 批次    | 172 格 × 2 引擎（corpus_v3 分层抽样） | baseline 原文直编，judge 归因               |
| compilebench-v3-zh 批次 | 175 格 × 2 引擎                       | zh 注入 + mock 翻译后编译                   |
| fixloop-cbv4 批次       | 同上 344 格                           | fixloop 冷 texmf 修复现场                   |
| e2e-real-n100 批次      | 100 篇 core 层，真翻译                | per-paper verdict + 40 格 pipe-fix          |
| corpus_v3 manifest      | 1,272 篇                              | stratum_cell / era / cat_group / cluster_id |

注意两套分类学并存：judge 走引擎层硬编码规则（类别名 `eps_image`），fixloop 走 rules.yaml taxonomy（类别名 `ps_image`，另有 `inputenc_unicode`/`aux_scan_eof`/`warn_*` 等新条目）——同一错误两边可能归不同类别，统计按签名实质合并。cbv4/cbv3zh 跑在 rules.yaml 扩列之前，当时 unfixable 的 `elsart.cls`/`aastex63.cls`/`aipproc.cls`/`iopart*.clo`/`binhex.tex`/`espcrc2.sty`/`apjfonts.sty` 等已入 `legacy_pkg_shim` shim_map（41 键），归入「已覆盖待回放」而非新规则候选。

## 1. 签名 × stratum 交叉表

### 1a. 签名 × era（cbv4+cbv3zh+n100 非 clean 格，按篇次）

| 签名                     | 篇次 | a_pre2007 | b_2007_11 | c_2012_16 | d_2017_20 | e_2021_25 |
| ------------------------ | ---- | --------- | --------- | --------- | --------- | --------- |
| missing_file             | 288  | 48        | 66        | 62        | 54        | 58        |
| eps_image(=ps_image)     | 91   | 25        | 30        | 16        | 14        | 6         |
| other                    | 26   | 1         | 10        | 8         | 0         | 7         |
| inject_reject(=latex209) | 26   | 24        | 2         | 0         | 0         | 0         |
| undefined_cs             | 24   | 4         | 1         | 4         | 7         | 8         |
| pdftex_prim              | 10   | 0         | 0         | 2         | 5         | 3         |
| syntax                   | 8    | 0         | 3         | 2         | 0         | 3         |
| missing_pfb              | 3    | 0         | 0         | 2         | 1         | 0         |
| already_def              | 2    | 2         | 0         | 0         | 0         | 0         |
| latex209                 | 2    | 0         | 0         | 0         | 0         | 2         |

### 1b. 签名 × cat_group

| 签名          | 篇次 | 主要集中                                                  |
| ------------- | ---- | --------------------------------------------------------- |
| missing_file  | 288  | hep-phys 79 · astro-ph 50 · cond-mat 46 · cs 42 · math 32 |
| eps_image     | 91   | cond-mat 22 · hep-phys 22 · astro-ph 16                   |
| other         | 26   | math 10 · hep-phys 7 · cs 5                               |
| inject_reject | 26   | hep-phys 8 · astro-ph 6 · cond-mat 6                      |
| undefined_cs  | 24   | math 8 · cs 7 · astro-ph 4                                |
| pdftex_prim   | 10   | cs 7 · eess-stat-etc 2                                    |

读法与扩库含义：missing_file 全 era 均匀但 payload 有年代分层——`revtex4.cls` 集中 a/b/c、`revtex4-1.cls` 集中 b/c/d、`IEEEtran.cls`/`elsarticle.cls` 集中 d/e、化石 cls（`revtex.cls`/`aaspp4.sty`/`mn2e.cls`/`elsart.cls` 等）几乎全在 a/b。eps_image 前旧后少（a+b 占 55/91）——2007 前论文几乎人手 .eps 图。inject_reject 纯 a_pre2007（24/26）——2.09 `\documentstyle` 稿，inject 层拒注入 ctex，属路由级缺口而非 fixloop 规则能修。undefined_cs/pdftex_prim 偏新（d+e 占 15/24 和 8/10）——新稿撞新包版本漂移 + pdfTeX 原语裸用。booster 抽样对应：a/b×hep-phys/cond-mat/astro-ph 命中化石 cls + eps_image；d/e×cs/math 命中 undefined_cs/pdftex_prim；a×* 命中 2.09 路由缺口。

## 2. 未覆盖签名清单（按出现篇数排序）

「未覆盖」= 挖掘时点的 rules.yaml 仍无对应规则/条目；count 为去重篇数。

### 2.1 missing_file 残部 —— shim_map 缺口（filemap 查无之后）

| payload                                                            | 篇  | 建议修复面                                                                                               |
| ------------------------------------------------------------------ | --- | -------------------------------------------------------------------------------------------------------- |
| `mn2e.cls`                                                         | 2   | shim_map：`mn2e.cls → mnras.cls`（MNRAS 类 2015 改名，filemap 已提示 candidates）+ 少量别名宏            |
| `svjour.cls`                                                       | 2   | shim_map：article + svjour 宏面 polyfill（`\journalname`/`\titlerunning`/`ack`），同 iopart/aa 先例      |
| `slashbox.sty`                                                     | 1   | shim_map：slashbox→diagbox（TL 内），`\slashbox{tl}{br}` → `\diagbox` 参数适配                           |
| `geom.sty`                                                         | 1   | shim_map：geom→geometry 桥接（API 近亲）；或 stub+geometry 装载                                          |
| `tcilatex.tex`                                                     | 1   | 先 stub `\endinput` 回放看炸哪些 cs，再补 polyfill；复杂则 llm_hook                                      |
| `epsf.tex`                                                         | 1   | INDEX_EXTS 扩 `.tex`（tex/ 子树限定，防 doc/ 噪声）→ filemap 直解 epsf 包                                |
| 2.09 化石 cls（`revtex.cls`/`aaspp4.sty`/`crckapb.cls`/`laa.cls`） | 7   | 不加 shim——这些是正确 reject（等 latex+dvips 通道）；shim_map 已有 revtex.cls 条目但被 gate 先拦，属预期 |

已覆盖待回放（跑后入库的 shim，勿重复造）：`elsart.cls`、`aa.cls`、`aipproc.cls`、`aipcheck.tex`、`iopart12.clo`、`aastex63.cls`、`binhex.tex`、`espcrc2.sty`、`psfig.sty`、`apjfonts.sty`、`AASTeX62.cls`、`aastex61.cls`。

### 2.2 `other` 类细分 —— 无规则兜底族（fixloop 终态 unfixable 主源）

| 子签名                         | 篇             | 建议修复面                                                                                                                                                                                             |
| ------------------------------ | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| graphic 大小写不符             | 2              | taxonomy 新增 `missing_graphic`（pattern 接 `Unable to load picture or PDF file` 与 `image inclusion failed`，payload=文件名）+ builtins `graphic_case_link`：wdir 大小写不敏感 glob 命中 → 建符号链接 |
| graphic 存在但加载失败         | 2              | 同上 `missing_graphic` 类 → builtins `graphic_repair`（gs/qpdf 重蒸馏）或 `graphic_stub`（`\fbox` 占位保编译）                                                                                         |
| metapost 数字扩展名图          | 1              | taxonomy ps_image pattern 扩 `\.\d+` 数字扩展（metapost 输出实为 EPS）→ eps_to_pdf 复用                                                                                                                |
| hyperref 驱动选项              | 2              | taxonomy `hyperref_driver` → builtins 剥 `\usepackage[hypertex/dvips]{hyperref}` 驱动键                                                                                                                |
| babel 未知语言选项             | 2              | taxonomy `babel_opt` payload=语言名 → 先 filemap 查 `<lang>.ldf` 装 `babel-<lang>`，查无则剥选项降级                                                                                                   |
| hyperxmp/hyperref 装载序       | 1              | taxonomy `pkg_order`（`Package (\w+) Error: (\w+) must be loaded before`）→ builtins 交换两行或后注 hyperxmp                                                                                           |
| float 未知选项                 | 2              | taxonomy `float_opt`（`Unknown float option '(\w)'`）→ builtins：`H`→补 `\usepackage{float}`；其他字母 → 改写 `!ht`                                                                                    |
| expl3 backend 矛盾             | 1              | 与 hyperref_driver 同族：源码/类选项里有 dvips 系 backend 声明 → builtins 剥 backend 选项                                                                                                              |
| 源码非法字节                   | 1              | taxonomy 加 head 级 `invalid_char` → 复用 `non_utf8_source` 动作                                                                                                                                       |
| acmart `\baselinestretch` 冲突 | 2（仅 zh-tec） | inject 层缺陷（ctex 注入改写 \baselinestretch 撞 acmart 禁令）→ 修 inject，非 fixloop                                                                                                                  |
| fontconfig 配置错              | 1              | 环境问题非源问题 → engine 层 FONTCONFIG_FILE 隔离，不加规则                                                                                                                                            |
| 外部工具失败                   | 1              | 待 log 深挖，先记名                                                                                                                                                                                    |
| textgreek 依赖缺件             | 1              | install_file 装整包 runfiles 而非单文件                                                                                                                                                                |
| `!` 行误判                     | 1              | taxonomy `!` 行过滤加 `\S+:`/`Error` 锚，低优先                                                                                                                                                        |

### 2.3 undefined_cs / already_def / pdftex_prim 残部

| 签名                    | 篇  | 建议修复面                                                                                                                             |
| ----------------------- | --- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `Hy@pdfmajorversion`    | 1   | cs_targeted_fix/journal_cs_polyfill 加 cs 条目（hyperref 新版改名）                                                                    |
| `pst@cntm`              | 1   | install_file 装包级 runfiles（pstricks.con 等伴生件），引擎层修                                                                        |
| `\pdfinfo` 多行形态     | 1   | pdftex_prim_guard pattern 允许 `{` 前换行（`[^\n]*` 是缺口）                                                                           |
| already_def 非 thm 载荷 | 2   | gate `latex209_reject` 扩为 `main_head_contains \documentstyle` 不限 category；generic `already_def_relax`（`\let\cs\relax` 前置）兜底 |
| `\hlineCd`              | 1   | cs 表低频，可不动                                                                                                                      |

### 2.4 分类学/路由层缺口（非规则但同档）

| 缺口                   | 篇  | 修复面                                                                                                                                                                                                                                |
| ---------------------- | --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| latex209 tail 误报     | 4   | 全是 LaTeX2e 稿，log 里 aastex banner「Original \LaTeX2.09 style」命中 tail 模式——tail pattern `LaTeX ?2\.09` 需锚定（要 `LaTeX2e command .* in LaTeX 2\.09` 错行或源码 `\documentstyle`）；真实阻塞是 apjfonts/AASTeX62（已入 shim） |
| warn→fixloop 路由断    | 8   | e2e 只把 fail 送 fixloop；missing_char_fix 有规则无入口 → verdict=partial+missing_chars>0 也应进 fixloop 轮                                                                                                                           |
| gate 误杀已出 pdf 格   | 7   | gate 应 error-driven：先编一轮见 pstricks/latex209 签名才拒，纯 source_contains 前置拒会丢 degraded pdf                                                                                                                               |
| 管线引入签名           | ~13 | `\item<A-Z>` 粘合、`\@` 裸入正文、数学符丢失等 splice/xlat 侧缺陷——主修在 xlat/splice 校验，fixloop 可选安全网 `item_glue_fix`                                                                                                        |
| inject_reject latex209 | 13  | 产品通道缺口（latex+dvips），非规则                                                                                                                                                                                                   |
| 休眠类别               | 0   | capacity / emergency / env_mismatch 三套语料零命中，保留作兜底                                                                                                                                                                        |

## 3. 已有规则 fires 核对（声明 stats vs 实测）

rules.yaml 内 `stats:` 是历次 bench 快照、非累计口径——与 cbv4(344 格)/n100(40 格) 对账：

| 规则                                                                                                                                                                                                                                                                     | yaml stats     | cbv4 实测 (xel/tec)       | n100 实测         | 核对                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------- | ------------------------- | ----------------- | ------------------------------------------------------------------------------------------- |
| static_precheck                                                                                                                                                                                                                                                          | 22/22 格       | 172/0 fires，145 格出 pdf | 40 fires，27 救回 | 量级跨样本放大，语义一致                                                                    |
| install_file                                                                                                                                                                                                                                                             | 26 fires/17 救 | 12+1 fires，10+0 救       | 2 fires/2 救      | 一致；tec 侧 ctan_fetch 弱（version_guard 拒装多）                                          |
| eps_to_pdf                                                                                                                                                                                                                                                               | 11/11          | 0/40 fires，38 救         | 0                 | 扩样本验证，2 格残为 graphic 加载失败                                                       |
| inputenc_strip                                                                                                                                                                                                                                                           | 5/5            | 5+5 全救                  | 0                 | 一致                                                                                        |
| non_utf8_source                                                                                                                                                                                                                                                          | 0 proposed     | 8/0 全救                  | 0                 | stats 待更新（已实证）                                                                      |
| pdftex_prim_guard                                                                                                                                                                                                                                                        | 3/3            | 8+1 fires 全救            | 0                 | 一致；多行 `\pdfinfo\n{` 漏 1 格                                                            |
| bbl_stub_shadow                                                                                                                                                                                                                                                          | 0 proposed     | 0/3 全救                  | 0                 | stats 待更新                                                                                |
| font_sub_shim                                                                                                                                                                                                                                                            | 0 proposed     | 0/3 全救                  | 0                 | stats 待更新                                                                                |
| legacy_pkg_shim                                                                                                                                                                                                                                                          | 1/1            | 2+1 全救                  | 0                 | 扩列后预期大涨，待回放                                                                      |
| pstricks_route                                                                                                                                                                                                                                                           | —              | 0/2 fires → 双双 reject   | 0                 | 1 格误杀 baseline-clean                                                                     |
| latex209_reject                                                                                                                                                                                                                                                          | 0              | 14 fires（7 篇×2 引擎）   | 0                 | 全为真 2.09 稿，但 5 格丢了 baseline degraded pdf                                           |
| _best_effort_pass                                                                                                                                                                                                                                                        | —              | 33/22 fires，13/0 救      | 17/4              | other 类的实际兜底，救回率 ~40%                                                             |
| install_tfm · install_sysfont · px_to_bp · microtype_off · hyphenation_sane · aastex_bundle_shadow · cs_targeted_fix                                                                                                                                                     | 各自旧实证     | cbv4+n100 均 0 fires      | 0                 | 样本未覆盖对应类别（missing_tfm/fontspec_missing/illegal_unit 等在 v3+n100 零命中），非失效 |
| missing_pfb_updmap · pdftex_prim_polyfill · times_to_newtx · aux_purge_regen · soul_cjk_mbox · thm_sibling_strip · option_clash_merge · minted_frozencache · minted_v3_rewrite · vendored_sty_shadow · journal_cs_polyfill · undefined_cs_guess(stub) · missing_char_fix | 0 proposed     | 0                         | 0                 | proposed 未验证；missing_char_fix 因路由断在 e2e 不可达                                     |

## 4. 候选规则验收标准（replay 目标）

| 候选                                                       | replay case                     | 验收                                                     |
| ---------------------------------------------------------- | ------------------------------- | -------------------------------------------------------- |
| mn2e→mnras shim                                            | cbv4 双引擎 4 格                | 出 pdf 且 n_errors≤3                                     |
| missing_graphic + case_link                                | 大小写不符 2 篇（tec）          | `Unable to load picture` 消失，出 pdf                    |
| graphic_repair/stub                                        | 加载失败 2 篇                   | 重蒸馏后载入 / 占位出 pdf                                |
| ps_image 扩数字扩展                                        | metapost 图 1 篇                | 归 ps_image → eps_to_pdf 转换成功                        |
| babel_opt                                                  | finnish/french 各 1             | babel-<lang> 装上或选项剥除 → 出 pdf                     |
| hyperref_driver/backend 剥除                               | 3 篇                            | 驱动错消失 → 出 pdf                                      |
| float_opt                                                  | `u`/`H` 各 1                    | `H`→float 载入 / `u`→改写后出 pdf                        |
| pkg_order(hyperxmp)                                        | 1 篇                            | hyperxmp 错消失 → 出 pdf                                 |
| invalid_char→non_utf8_source                               | 1 篇                            | 非法字节错消失                                           |
| svjour/slashbox/geom/tcilatex/epsf.tex/svglov3 shim + 索引 | 各 payload                      | payload 消失 → 出 pdf（tcilatex 允许降 best_effort）     |
| latex209 tail 锚定 + 现有 shim                             | 误报 4 篇                       | 不再归 latex209；走 missing_file→shim → 出 pdf           |
| gate 改 error-driven                                       | baseline clean 被误杀回归格     | baseline clean 格不被 precheck 拒                        |
| pdftex_prim 多行                                           | `\pdfinfo\n{` 跨行 1 篇         | 被 guard 套住                                            |
| already_def gate 扩展 + relax                              | 2.09 稿 + `\Ref` 各 1           | 前者归 reject:latex209，后者 relax 后出 pdf              |
| missing_char 路由接通                                      | missing_chars>0 的 partial 3 篇 | partial+missing_chars 进 fixloop → missing_char_fix 点火 |

汇总：cbv4 终态 unfixable+reject 共 58 格 / 40 篇（xel 27 + tec 31），n100 13 格——按上表落地后预期残部收敛到「2.09 路由缺口 + tcilatex 级硬骨 + 环境项」三类，约 10 篇以内。

## 5. 落地优先级

1. 修 taxonomy 两处 bug 先行：latex209 tail 误报（4 篇白死）+ `!` 行过宽；成本一行 regex。
2. shim_map 长尾（mn2e/svjour/slashbox/geom/epsf.tex/svglov3.clo/tcilatex）：全部是 replay 可验证的小条目；INDEX_EXTS 加 `.tex` 一并做（tex/ 子树限定）。
3. `other` 拆家：missing_graphic + babel_opt + hyperref_driver + float_opt + pkg_order + invalid_char 六个新 taxonomy 行吃掉大半 unfixable:other；graphic_case_link 是其中 ROI 最高（大小写不符在跨平台 e-print 里会反复出现）。
4. gate error-driven 化：防再丢 baseline 已出 pdf 的格。
5. 管线引入签名上交 xlat：`\item<大写>` 粘合 8 篇是同根缺陷，fixloop 安全网可选。
6. missing_char_fix 路由：cond-mat/0307508 级（4379 缺字）不进 fixloop 等于规则白写。
