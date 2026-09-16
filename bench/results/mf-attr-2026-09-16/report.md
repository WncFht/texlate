# missing_file 族歼灭战归因报告（M2 攻坚 · texlate-2f）

> 数据：`bench/results/stagerun-loop1-2026-09-16/` records（每 cell 取末条 record 为当前态）+
> `tickets.jsonl`（loop1 时点票面）+ 现行 `rules.yaml`（e6ecb85）+ tlpdb filemap 索引。
> 方法：compile.jsonl 末条 `verdict.category==missing_file` 全集 588 格 × 127 payload，
> 逐格对账 fixloop.jsonl 末态与覆盖现状。

## 0. 结论速览

- **missing_file 族在末条 record 口径下已实质歼灭**：588 格中 566 格出 pdf（healed），
  12 格越过 missing_file 前进到其他错误类（progressed），1 格真 residual（pst-pdf.sty，
  本报告 rerun 后亦愈），5 格从未进 fixloop（partial 不进 `--on fail`，非规则缺口），
  4 格为特殊小桶（腐蚀/图资产，见 §3）。
- **票面 ≠ 现状**：tickets 的 missing_file 计数是 compile 段（fixloop 之前）快照。
  compile 段缺文件天经地义——shim/装包都活在 fixloop 段，票面不构成"shim 没触发"证据。
- **「已 shim 仍出票」归因**：shim 正常触发。loop1 时点 fixloop 首条 record 显示
  aastex 76/82、elsart 21/25、psfig 20/21、iopart 39/44 当场出 pdf；当时仍
  unfixable:missing_file 的细胞全部是**第二档文件**（shim 替身生效后编译前进、
  撞上下一个当时未覆盖的文件，如 aastex 系 → emulateapj5.sty），该类文件后均已入
  shim_map 并实证转愈。
- **无 shim 空白立项结果：零追加**。票面 51 个无 shim payload 经 tlpdb filemap 逐一
  实证全部为 TL 真包（tensor→tensor、llncs→llncs、nicematrix、chemformula、
  har2nat、jpsj2→jpsj、IEEEconf→ieeeconf、kluwer、ptptex、spie、quantumarticle…），
  缺的是当时的安装通路而非替身——`8e6d442` 请求方扇出/`9f08bf3` CTAN overlay/
  `6752bb0` TEXMFHOME 链修复后安装通路实证可用，本报告 pst-pdf 格 rerun 即愈。
  **rules.yaml 对 missing_file 族无需新增 shim_map/filemap.overrides 条目。**
- 真残盘（全部非 missing_file 规则面）：腐蚀文件名 ×2、图资产缺失 ×4
  （taxonomy 路由缺口，提案 §4）、progressed ×12（转交对应族，清单 §5）。

## 1. 口径与方法

票面（loop1 时点 triage）：missing_file 签名 174 条 / 702 票（含 unfixable: 变体），
按 compile.jsonl 末条重算 = 588 格 / 127 payload（差异 = triage 含 fixloop 段 unfixable
票与口径合并）。每格按 fixloop 末条 record 归类：

- `healed`：fixloop_verdict ∈ {clean, acceptable_pdf, best_effort_pdf} —— 出 pdf。
- `prog:<cat>`：越过 missing_file 后收在其他 unfixable 类（规则面使命完成，前进到
  下一个错误类）。
- `resid`：末态仍 unfixable:missing_file。
- `notfx`：未进 fixloop（compile partial 有 pdf，不在 `--on fail` 选择集）。

全量 127 payload 覆盖表：[payload-table.md](payload-table.md)（votes / TL pkg /
shim_map 键 / overrides 键 / healed / prog / resid / notfx 逐行列出）。

## 2. 已 shim 仍出票归因（任务 1）

票面 top 里 shim_map 覆盖的 30+ payload（aastex×82/iopart×44/mn2e×42/aa×33/elsart×25/
tcilatex×23/psfig×21/espcrc2×16/JHEP3×13/svjour×9/slashbox×9/jheppub×9/aipproc/
apjfonts/siamltex/…），归因一致：**shim 活在 fixloop 段且实证触发**。

loop1 时点 fixloop 首条 record 回放（证明当时 shim 已在工作）：

| payload | loop1 时点结局 | 末条结局 | 当时残留机理 |
|---|---|---|---|
| aastex.cls ×82 | 76 pdf / 6 unfixable | 80 healed / 2 capacity | 4 格撞 emulateapj5.sty（当时未 shim→loop1簇扩列已补愈）；2 格 capacity 非本族 |
| iopart.cls ×44 | 39 pdf / 5 unfixable | 44 healed | 5 格撞 setstack.sty（当时未 shim→已补愈） |
| elsart.cls ×25 | 21 pdf / 4 unfixable | 23 healed / illegal_unit+undefined_cs 各 1 | option_clash 1 格（wave-2 规则已愈）、第二档文件 1 格 |
| psfig.sty ×21 | 20 pdf / 1 unfixable | 21 healed | hep-ex/0408061 第二档文件，已愈 |
| jheppub.sty ×9 | 9 unfixable | 9 best_effort | 当时无 shim（wave-2 补）→ 全愈 |
| aa/mn2e/tcilatex/espcrc2/JHEP3/svjour/slashbox/… | 各 ≤1 残 | 全 healed | 同上模式 |

即「已 shim 仍出票」= compile 段快照语义 + 第二档文件时序缺口，两类均已闭合。
**无 shim 未触发的真案例。**

## 3. 无 shim 空白立项（任务 2）

票面 51 个无 shim payload 逐一过 tlpdb filemap：**51/51 全部 TL 真包**（部分名见 §0）。
处置 = 安装通路，已由本轮引擎修复承接（pst-pdf 格实证）。**逐项裁定：不需 shim_map
条目、不需 overrides 钉（索引本名命中）、不需 null 登记（非噪声）。**

剩余特殊小桶：

| 桶 | 细胞 | 机理 | 处置 |
|---|---|---|---|
| 腐蚀文件名 | 0905.1215、1206.5352 | `\input <文件名>` 参数被译文占位符「这是译文」替换，payload 非真实文件名 | 译文腐蚀超簇（fixer-slots 属地），规则面不立项 |
| 图资产缺失 | 1404.5720、1404.6041、2003.10664、1706.00291 | `File 'X.eps' not found`，src 内有同名 .pdf 兄弟档（老稿 pdflatex 预转存） | §4 提案：taxonomy 路由 + 扩展名变体改写 |
| (bare) missing_file | 1003.2165 | 无 payload 票面，实际已前进到 babel_opt | 归 babel_opt 族 |

## 4. 提案（新逻辑，不落盘）

**P1 图资产扩展名变体改写**：`.eps` 缺失但同 stem `.pdf/.png/.jpg` 兄弟档在盘 →
`\includegraphics` 参数去扩展名重写（graphics 扩展名检索自动命真身）。两动件：
(a) taxonomy：`File `X.(eps|png|jpg|pdf)' not found` 在 missing_file 之前改判
missing_graphic（现状走 install_file 死路——.eps 非包、索引恒 miss）；
(b) builtin `graphic_ext_link`（graphic_case_link 姊妹件）：stem 级 ci-glob
命中可载扩展名 → 改参数。盘存无兄弟档 → 落 graphic_repair 的 \fbox 兜底。
覆盖 4 格残盘 + 全语料同形态长尾。**规则逻辑，只提案不直写。**

**P2 腐蚀文件名台账**：`这是译文` 类 payload 不该进 missing_file 归因（CJK payload
本身即腐蚀指纹）——建议 triage/归类层把非 ASCII payload 直挂腐蚀超簇，免占
missing_file 票面。**属 triage 侧建议，不在本战落盘范围。**

## 5. progressed 细胞移交清单（12 格）

越过 missing_file 后收在其他 unfixable 类——规则面已尽职，移交对应族：

| id | 原 payload | 现类 | 备注 |
|---|---|---|---|
| 0707.4206 | elsart.cls | illegal_unit | elsart shim 生效后真错 |
| 1003.2165 | (bare) | babel_opt:polutonikogreek | |
| 1206.0136 | ot1patch.sty | early_eof | ^^M 缺字刷屏截断（补记7已归因） |
| 1306.0281 | acm_proc_article-sp.cls | early_eof | |
| 1608.06693 | svglov3.clo | early_eof | 错误帽 100 终止（补记7） |
| 1706.00016 | tensor.sty | syntax | |
| 1706.00335 | complexity.sty | capacity | |
| 2105.11398 | har2nat.sty | illegal_unit | |
| astro-ph/0104174 | aastex.cls | capacity | |
| astro-ph/0408286 | espcrc1.sty | undefined_cs:maketitle | |
| astro-ph/0408531 | aastex.cls | capacity | |
| hep-lat/0111059 | elsart.cls | undefined_cs:eqntopsep | |

## 6. 复验记录

- `2111.00051`（pst-pdf.sty 唯一 resid）：`stagerun.py fixloop --rerun --on fail --ids`
  → **acceptable_pdf**，installed += pst-pdf.sty/pst-calculate.sty（dep 扇出实锤）。
  delta 两轮未愈系跑在 `8e6d442` 扇出修复之前。
- 全族无新增数据条目 → 无批量 rerun 对象；30 格 clean 抽检查退化在本批无意义
  （零规则变更），留待三族报告的数据提案落地后一并复验。

## 7. 三族归因（leader 批量归因版，scout 复核待并入）

- invalid_utf8（票面 354 / 末条 545）：[scout-invalid-utf8.md](scout-invalid-utf8.md)
- undefined_cs（票面 284 / 当前 partial 382）：[scout-undefined-cs.md](scout-undefined-cs.md)
- illegal_unit（票面 312 / 当前 partial 224）：[scout-illegal-unit.md](scout-illegal-unit.md)

三族共通结论：**大头全是译文腐蚀超簇（bug-B）存量 + 少量 shim 宏面数据缺口 +
上游噪声**——utf8 族 100% 是 TL 包 latin-1 注释（judge 红线已限工程文件源，
`0c4e4b8` 落地后应清零）；ucs/illegal_unit 族 60-90% 是 cs+latin 融合/数值域
腐蚀，`a6b58d4` gap-bytes 修复掐断产生路径后属**重跑即回收**存量。规则面
新增仅一宗：shim body 扩列提案（elsart `\corauth`/`\smartqed`/`\eqntopsep`、
svjour `\submitto`、iopart `\iopams`——数据修订走 owner 评审，见
scout-undefined-cs.md）。

## 7.1 票面 vs 末条 record 口径差（方法论，各族可复用）

**三层口径必须分开报，混用会系统性高估/低估族规模**：

1. **tickets.jsonl（票面）** = loop1 triage 时点快照。compile 段采样 + fixloop
   段 unfixable 票混合，**不随后续重跑更新**。用于排工作量优先级，**不可用于
   现状判断**——missing_file 票面 702 票 vs 末条 588 格（差异 = unfixable 票
   重复计 + triage 抽样）、invalid_utf8 票面 354 vs 末条 545（triage 抽样
   小于末条全集）均为同族不同口径。
2. **records/compile.jsonl 末条** = 当前编译态。append-only，每 cell 取
   `id` 最后一条 record 的 `metrics.verdict`。**族归因与覆盖率必须以此为准**。
   注意末条可能来自不同轮次（loop1/delta/定点 rerun 混排），读 `run_meta`
   或 record 内 code-stamp 判断跑的哪版引擎。
3. **records/fixloop.jsonl 末条** = 修复终态。`metrics.fixloop_verdict` ∈
   {clean, acceptable_pdf, best_effort_pdf} 为出 pdf；unfixable:<cat> /
   max_rounds / no_errors_no_pdf 为残。**「越过原族前进到下一错误类」
   （prog）与「仍卡原族」（resid）必须分列**——前者规则面使命已完成。

**迁移陷阱**：`--rerun` 复用 work dir 不洗源，被已修 bug 写坏的格（如
`88d0ab9` 前的套娃残留）旧伤永存——**rerun 前先 `compile --arm zh --rerun`
重建 pristine splice**（1306.0036 实证必要）。末条 record 的
code-stamp（`ddd4702`）可判该 record 跑在修复前还是修复后。

## 8. fixloop:fail 逐格归因（56 格）

详表：[scout-fail59.md](scout-fail59.md)。末条口径 56 格（overseer 底单 59
为早期快照，期间定点 rerun 愈 3 格）：

- **corrosion ×27**：`这是译文`/PH-in-cs/cs+latin 融合实证（冒犯行 CJK 指纹），
  随 `a6b58d4` 段内修复 + realpostfix2 全量重翻自然回收，非规则面。
- **fixable-data ×18**：6 个数据动件（shim 列型/shim 宏面/thm-restate/
  驱动剥除/aipcheck 覆写/杂项），提案已列明细走 owner 评审——**真增量空间，
  全落地则 fail 池 56→~11**。
- **upstream ×9**：tar-内嵌 sty、WS 类自带不稳健代码、biblatex-apa 错配、
  catcode 戏法、NFSS、acro API 漂移、缺字截断——wontfix/llm_hook 候选。
- **infra ×1**：skak tfm 装配层。**ticket ×1**：1803.00012 SIGSEGV。

## 9. 当前战场地图（clean 率口径，末条 record 全集 5059）

clean 2515（49.7%）/ partial 1990 / reject 414（latex209 终拒，wontfix）/
fail 60 / skip 80（parse 上游无 zh/）。partial 池成分（clean 率真实空间）：
warn 级（category=clean）776 · undefined_cs 382 · other 297 · illegal_unit 224 ·
syntax 206 · already_def 30 · babel_opt 22 · pdftex_prim 10 · hyperref_driver 9 ·
capacity 8 · fontspec_missing 8 · missing_file 6（§3 小桶）· 尾小类 ~10。
