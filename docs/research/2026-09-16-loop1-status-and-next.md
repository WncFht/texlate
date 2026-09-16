# 2026-09-16 管线全局状态与下一步计划（loop1 复盘 + 三方碰头收敛）

> 数据基准：`bench/results/stagerun-loop1-2026-09-16/`（records/cases/metrics/report + `REPORT-fixloop-analysis.md`）。
> 审计全账：`docs/research/audit-2026-09-16/wave2-findings.md`（9 scout ~75 条发现逐条处置）。
> 三方：1d=leader（latex/e2e/fixloop/bench/tests/横切）、项目体验方式（compile/engine.py、xlat/pipeline.py、rules.yaml、loop 执鞭）、1e（server/worker/probe/web）。

## 1. 端到端数字（loop1，n=5059 解析成功集）

| 阶段 | 结果 | 率 |
| --- | --- | --- |
| ingest | 5059/5072 | 99.7% |
| parse | 4980/5059 | 98.4%（残 75 = no_main_tex） |
| xlat mock | 4957/5059 | 98.0% |
| xlat real（n50 隔夜） | 48/50 | 96.0% |
| compile zh（译后注入编译） | clean 2290 / partial 1628 / fail 647 / reject 414 / skip 129 | pdf 77.4% |
| fixloop（on fail647+misschar663） | clean 189 / partial 911 / fail 210 | rescue 84.0% |
| **终态（zh 臂过 fixloop 后）** | **clean 2479 / partial 1876 / fail 210** | **pdf 86.1%（4355/5059），clean 49.0%** |

对照系：同语料原文裸编（不译不注入）双引擎联合 pdf 率 71.3%（3605/5059）、xelatex 单引擎 38.4%——管线（normalize+inject+fixloop）把出 pdf 率抬了 ~15pp，还额外交付了中文译文。

## 2. 今日落地（184 commits，节取）

- **观测链钉死**：records 契约（末条胜去重、run_meta 真墙钟、上游门 skip 豁免出票、sig 合成 benchlib 单源）、triage `fixloop_degraded` 跨段退化探测（`24b4d53`）、`--on misschar` 选取修复（`2d2a412`）、pyproject testpaths（裸 pytest INTERNALERROR 消除）。
- **fixloop 引擎硬化 9 项**（`3c5aae2`）：when/condition 键白名单 + `_when_ok` fail-closed、CtanFetcher overrides 一次性合并视图（共享索引不再原地 mutate）、pdftex_prim subclassify 收窄到主 payload/l.N 行末 cs、missing_char_fix verbatim 防护、`compile_timeout` 透传链、llm_hook 四调用点 opt-in（e2e/stagerun/fixloop_bench/e2e_real）+ escalate 延后到同类规则耗尽、tectonic vendored_shadow advisory 档、`l.N` 行首锚。加挂修掉裸 payload bug（`I can't find file 'epsf'` 裸名补 `.tex` 候选 + shim 归一）。
- **latex 层重构**（`2f3fc67`）：`_group_surface` P0 漂移修（hyperref 排除 + verb 行）、math_debt/math_depth 死机制移除、argspec dispatch 波 + 三 bug、FILENAME_CHARS 单源、`__all__` 收窄、v1 parse_file top_dir 对齐。
- **taxonomy 单源化**（peer 在飞）：engine `_ERROR_RULES`→rules.yaml `Taxonomy` derive（`compile/engine.py` 工作树在飞）；`early_eof` 尾段两条接住「干净日志零页面」早夭（`efa1fa3`）；compile engine 审计簇（bwrap resolve/TMPDIR/`-Z` 白名单/env 降级 `6b23435`）。
- **server/worker**（1e）：doc 管线接线（glossary/progress/token/`_run_doc`）、babeldoc sidecar 契约修、app-polish 波（孤儿目录/staticfiles/chunk_counts）、dispatch 死锁修、share 包导入链 + 部分包容忍。
- **bench 卫生**：死 spike 簇 −3690 行、`unpack_blob` 归并产品 `arxiv.unpack`、clean-clone 验证报告（11 守卫缺陷已修 `6e2659a`）。
- **docs/08 §6 状态词表**（`20e7a8a`）：七套 status/verdict 枚举对照表落地。

## 3. loop1 学到的（实证修正）

- partial→fail 17 格**直编复验后管线真退化收敛到 2 格**（1003.1717/2410.00012；1306.0036 经 1e repro-1306 逐字节 base 复验翻案为 revtex4-1×array TL2026 既有缺陷、记 pre-existing；astro-ph/0111575 已随 epsf 裸 payload 修复自愈），13 格是 pre-`6b23435` 引擎基建杀伤——跨段退化判定必须直编复验，不能只看记录面。
- `no_errors_no_pdf` = TeX `(\end occurred…incomplete)` + `No pages of output` 早夭路径无 `!` 行 → 旧 taxonomy 判 clean 无规则承接；已由 `early_eof` 接住。**rerun 实证补齐机理**：13 格同根因——aastex61/62.cls 内部 `\IfFileExists{revtex4-1.cls}{ok}{…\stop}`，revtex4-1 不在 TL → `\stop` 夹条件内 → 早夭；「类文件求档文」语义。对策 `18ff106`（tail plea 规则抓档名归 missing_file + revtex4-1→4-2 桥）验证 **13/13 出 pdf**（11 acceptable + 2 best_effort）。
- unfixable 大头 `missing_file`×113 = legacy 期刊包簇。经 tlpdb 实证拆两型：**索引可解**（pst-node/pst-arrow/epsf/emulateapj.cls/cite/axodraw2/acmart/revtex——pst-* 可解仍败是独立机理疑点，rerun 归类）与 **TL 真缺席**（svjour2/3、jheppub、jinstpub、espcrc1、epl2、imsart、conm-p-l、citesort、diagrams、texsort、setstack、undertilde、default、emulateapj*.sty）——只能 shim 写 stub（真桥：citesort→cite[sort,compress]、axodraw→axodraw2、conm-p-l→acmart；svjour/epl2/imsart 用 aa/iopart 同款 article+polyfill；余 noop 保底）。
- misschar 663 格 acceptable 档语义 = 「有 pdf 即收」——如需更严口径（缺字数阈值）另议。
- skip 129 格全合法上游门（scout 逐链核实）：79 not_translated（parse 失败级联）+ 49 arm_mismatch + 1 gate——**但暴露排程洞**：zh/ 单槽被 real 臂覆写，real-50 抽样 48 id 永无 mock compile 数据；loop2 若做 real↔mock 同 id 对照需先 compile-mock 再 xlat-real（或 zh/ 分臂）。
- **真退化 4 格归因（scout-regress4 直编复验）= TEXMFHOME 环境不对称遮蔽（3/4）**：入口 `_compile_judge` 见 ambient `~/texmf`，fixloop `_fixloop_one` 冷起 `_texmf`+`texmfhome=` 把 `~/texmf` 整树遮掉——epsf/revtex4-1/mhchem/chemgreek/ltxgrid 全只活在 ~/texmf。底板兜产物层，真修=texmf 串链（engine `_env` peer1 / stagerun 半侧 1d）。1306.0036 是 `pdftex_prim_guard` 自残（`\chardef\ifdefined` 残行跨 rerun 继承）→ **已修 `88d0ab9`**；2410.00012 是 install_file 无依赖闭包；1003.1717 是随包 `aps.rtx.tex` 被 xlat 污染（csname 槽位腐蚀 + 翻译集边界双问题）。

## 4. 下一步计划（收敛后分派）

### 4.1 即时（loop2 前）

1. **定点 rerun 19 格两轮已收官**（peer1 执鞭）：**14/19 出 pdf**。nenp 15→2——early_eof 13 格全救回（11 acceptable + 2 best_effort，`18ff106` plea 规则+revtex4-1 桥）；真退化 4 格：astro-ph/0111575 **痊愈 acceptable**；1003.1717 仍 unfixable:syntax、1306.0036/2410.00012 改判 undefined_cs（subclassify 收窄正确）。残 5：1803.00012（SIGSEGV rc=-11，killed_signal 已记）、1706.02464（bufsize rc=1）、1003.1717、1306.0036、2410.00012。pst-* 可解仍败疑点归 loop2 全量观察。
2. **rules.yaml 内容面**（peer1）：`shim_map` +17 条已落 `622fc04`；`static_precheck` scan_patterns 已补 `\input` 裸名+花括号两形态（lookahead 防 `\includegraphics` 误捕，`engine.py:678` 顺带修 `x.tex`→`x.tex.tex` 双叠）。
3. **worker-hardening 12 项已收口** `7cce5f9`（#74 latest-alias 二次 dedup、#78 L2 归因洞、llm_hook BYOK、share 三闸同批落）；`server/worker.py:2763` 半残 edit 已修（HEAD 语法净）。#78 前置 popped_files 链路 `e32e90e` 已落（texlog-popped），消费侧接线（llm_hook `_resolve_err_file`/`_requester_paths`）转 项目体验方式。
4. **engine taxonomy 单源化已落** `5d195c2`（audit-taxonomy 交付 + peer1 review；死代码 `_match_head/_match_tail` 顺手删）——engine.parse_log 一并被 derive 覆盖，engine↔rules.yaml 双轨漂移源消除。

### 4.2 loop2（全量 fixloop 重跑）

- 触发：上述 4.1 落地后；命令形（同目录 `--rerun` 两闸顺序跑，`--ids` 省略即全量重选）：
  `uv run python bench/py/stagerun.py fixloop --on fail --rerun --dir bench/results/stagerun-loop1-2026-09-16`
  `uv run python bench/py/stagerun.py fixloop --on misschar --rerun --dir bench/results/stagerun-loop1-2026-09-16`
- 判读：`bench/py/rundiff.py`（在飞）出 loop1→loop2 逐格迁移矩阵；triage `fixloop_degraded` 盯跨段退化。
- 目标：rescue ≥90%；missing_file 簇靠 shim_map 扩列 + tlpdb-index 预期消化大半；`fixloop_degraded` ≤4。
- **「不退化底板」已落 `2f12955`**：入口态 pdf 快照（precheck 前现存产物优先、否则 rounds[0]），末态失 pdf 且非 reject → 拷回 + verdict 重落既有公式（`floor_from`/`floor_restored` 留痕，stagerun metrics 带 `floor_restored`，replay_all 门②将兜回计入 regressed）。注意 stagerun post 复判仍直编裸树——record status 反映树真实态，退化观测不受底板遮蔽。

### 4.2+ loop2-delta 收官（peer1 `b4akkgal5`，records 落 `cd17eb5` + 补记 `581f374`）

- 终态 1310 格：**acceptable 669 / best_effort 363 / clean 157 → 出 pdf 90.8%**（loop1 84.0%）；unfixable 112；**missing_file 113→32；nenp 15→1**（残 1803.00012 SIGSEGV）；partial→fail 仅 2。
- **rundiff vs `5acb956` 基线：improved 73 / degraded 0 / same 1237**——fail→clean 16 + fail→partial 57，全部缺文件簇救回（2410.00012 随双修 fail→partial）；**零退化**——partial→fail 从 loop1 记录面 17 格清零。floor_restored 全格 False（底板未触发，与零退化一致）。
- 残格归因落地：pdftex_prim×6=axessibility → `axessibility_xetex_shadow` order157（`7037301`）；axodraw2×5=tlmgr usermode non-relocatable rc=0 假成功 → CTAN overlay=tree 兜底（`9f08bf3`）；pst-all×8=meta-wrapper RequirePackage 连发 11 成员超轮 → **install_file 请求方扇出**（file:line 锚解要求方→依赖全表一轮补装，`8e6d442`）。
- **判读纪律**：烤疤格（pre-`88d0ab9` 套娃残留烤进 splice，`--rerun` 不洗源——1306.0036 型）+ pre-`6752bb0` 假 missing_file 层不计入规则退化；此类格需 pristine-tree 重跑见真值。
- **定点重跑 34 格已收官**（补记7 `e769ebb`，全格先洗 pristine splice）：axessibility 6/6、axodraw2 5/5、pst-all 7/8（扇出一轮补全实证）、1306.0036 best_effort（烤疤实锤）、1003.1717 acceptable、partial→fail 清零、early_eof 13 格全脱 unfixable（子机理两分归下轮签名归因）。终盘 unfixable 面：missing_file ~27 + early_eof 最大残簇。
- **残盘三 scout 归因收官**（详见 wave2-findings 末节）：cjk_chars=0 实为 28 格五桶——splice 层零 bug（A/C 桶已被 `f7822a8` 愈，F 桶 11 格是 verdict 假阳待 tune，E 桶 1 格 main_rel 决策项）；pst 残链根因=pstricks-add.tex 行内 `\input` 裸名链盲区 → **已修 `ca0e748`**（`_dep_stems` 行内扫描 + advisory 全败才落）；尾 127 fail 分布=~24-29 已被晚波覆盖 + **~45-50 机械规则胜场转 peer1**（shim 波二 ~20 名/babel_opt×10/lgrenc×3/hyperref-driver×2/expl3-backend×4/杂簇×5）+ ~10-15 peer 面 + ~5-8 terminal + ~30 长尾。
- **1e real-postfix A/B 终报 `0d1526d`**（100/100）：pipe-xel clean 61.7%；bug-B `\item<Cap>` 融合定位翻转到 **LLM echo 侧**（segmenter 修不到，拟 splice 侧 `\\item(?=[A-Z])` 守卫）；bug-G warmup 终证（fixloop 臂 16/18）；新露头 expl3_backend 失败模态（hep-ph/9910403）。

### 4.2.5 clean 率杠杆（scout-partial/misschar/latex209 实证，已分派）

终态 partial 1890 格唯一阻断分布：错误残留 980（51.9%）、缺字唯一阻断 491（26.0%）、invalid_utf8 唯一阻断 405（21.4%）、cjk 计数 14。已派四 fixer 按杠杆序推进：

| # | 杠杆 | 实证 | 可转化 | 属主 |
| --- | --- | --- | --- | --- |
| 1 | **译文槽位保护**（fixer-slots，segmenter） | 错误簇 42%=407 格同机理：`\vskip3这是译文`(illegal_unit 138)、`{\scJos`/`\csnamebibitemNoStop` 粘连(104)、`Undefined color '这是译文'`+counter/keyval(91)、`\par` 进短参(62)、array preamble(12) | ~407 | 1d（xlat 侧残留归 peer1） |
| 2 | **CJK 字体兜底+缺字真修**（fixer-cjkfont，inject+builtins 缺字段） | **已全落 `f7822a8`**：A 桶双 bug 修（`CJK_PRESENT_RE` 收紧包/类花括号语境灭三假阳 + `find_docclass_ends` 逐缝注入带幂等哨兵，真格 9/9）+ tfm `("XXXX)` 正则补分支（197 格解锁）+ `cjk_glyph` spec 字体门（tfm 数学族不白烧）+ `font_fallback` builtin（西里尔/组合符/拉丁扩展→`\newunicodechar`+Libertinus Serif，rules.yaml 条目已转 peer1 order26）。`CJK_MATH_FALLBACK` `\Umathcode` 顺带治愈 B 桶 336 格数学内 CJK + 西里尔/组合符数学缺字（texlatefb 兜底）；warmup 实证治愈 elsart 首用陷阱（bug-G，cmrepro 10/10） | ~150–220 + B 桶 336 连带 | 1d |
| 3 | **invalid_utf8 净化**（fixer-utf8，normalize 单点） | **已落 `673d8ce`**：四臂（系统包 kpsewhich 遮蔽+EPS 注释净化+ps 驱动 token→xetex+catch-all 转码）单点 `normalize_project`；96% 警告源是系统 texmf 老包 latin-1，真格验证 invalid_utf8=0 | ~530/545 | 1d |
| 4 | **latex209→2e 受限升级器**（fixer-209up，inject 挂点+新模块） | **已交付**（commit 等 inject.py 同提交）：`upgrade_209` 干跑普查 **405/414=97.8% 过门**（远超 40–65% 估）——article 188/revtex4-2 169/mnras 26 等；reject 9 格全 ds@ 机制性死墙记 terminal；白名单 +15 名已落。门后产出由下游 missing_file/fixloop 决定 | 过门面 405（产出另计） | 1d 建器 + peer1 改 gate 路由 |

1+2+3 全落地理论上限 ~1120 格（407+~185+~530，misschar/utf8 取证重画后），clean 率 54.3%→~79%（基数 4565=5108−129skip−414reject）；#4 再额外解锁 reject 池。另：`cjk_chars=0` 14 格实为 splice 没拿到段（上游覆盖问题）；pst-* 可解仍败疑点归 loop2 全量观察。

### 4.3 中线

- **真网关规模验证**（1e 建议）：xlat-real n50 出数后推 n100-200 拿真 clean-rate 分布——mock 臂今日连修 4 个缺陷，真臂还没同等扫过。**postfix n≈81 已出数（在飞收尾，`bench/results/postfix-2026-09-16/`）**：翻译 81/81 篇、chunk ok 8885/8889（4 partial 0 fault）、splice 占位残留 0；pipe-xel clean 50/fail 6/partial 25（clean 61.7% vs mock 臂 45.3%——真译文反而更稳）；pipe-fix 救回 12/13（acceptable 9+best_effort 1+clean 2）。**管线引入退化 9 格**（pipe 非 clean 且 base clean）scout-realreg 归因在飞：0905.4907 已知 bug-E，其余 8 格待归因（疑 bug-B 主场——真臂 latin-token 保留率远高于 mock 四字）。→ **已收官 realpostfix2 n=100**（2026-09-17，`bench/results/realpostfix2-2026-09-16/`）：chunk ok 10706/10717、splice 残留 0；pipe-xel clean76/partial10/fail14，fixloop 后 union pdf **96%**、union clean 87、fail 4；管线引入回归 2 格（0905.4907 翻译裸 cs——已落 L0#11 `de03153`；hep-ph/9910403 expl3_backend）。归因/审计 report：scout-pf2fails、scout-e2ereal。
- **share 生态闭环**（1e）：worker 完成钩自动产包 + index.jsonl 服务形态（§8）。→ **已全闭**（2026-09-17）：完成钩 `746e87f` + 事后 pack 端点 `4b537df` + 前端钮 `aa8759a` + **隐式命中接线** `d3fb38b`（translate 路径 post-parse 查 index → `_stage_share_apply` 零 token 通道）+ docs-sync 对账 `6c9d567`。
- **deferred 清单**：v1 退役（倾向不动）、e2e_real→lib 降级、L2 编排环 e2e↔worker 共享化（跨边界需协商落点）、TokenSource Protocol 重构、L2 真 log fixtures。
- **llm_hook 接线**（1e 已裁）：server 路径走任务 BYOK client 复用 `_make_translator`/usage_sink；有真 api_key 默认开；`kind=share` 一律全关（§5 导入零 token 承诺）。

## 5. 分工（本会收敛）

| 方 | 当前在飞 | 下一步 |
| --- | --- | --- |
| 1d leader | fixer-slots（槽位保护 + bug-B，规格已按 1e 终报翻转：融合在 LLM echo 侧 → splice 守卫层）在飞；fixer-emit（#167 @-opaque 二路径 + #168 短参空行）在飞；fixer-cjkfont 全落 `f7822a8`；扇出 `\input` 链补盲 `ca0e748` | F 桶 verdict-tune（0-chunk main 不吃 cjk_chars=0 partial）；E 桶 main_rel 决策；slots/emit 交付收敛 + expl3_backend 钉签名 |
| 项目体验方式 | **delta `b4akkgal5` 收官**（90.8% 出 pdf、rundiff 73/0）；font_fallback order26 `bd88dc9`、axessibility/axodraw2 对策、定点重跑 34 格全收官 | rules.yaml 机械胜场清单（scout-unfix 枚举 ~45-50 格：shim 波二 ~20/babel_opt/lgrenc pattern/hyperref-driver/expl3 backend/杂簇）+ emulateapj-rtx4/JINST shim 键 + early_eof 子机理签名 + precheck `\input` 扫描切注释 |
| 1e | worker-hardening #52、llm_hook BYOK、**real-postfix A/B 终报 `0d1526d`**、Mode-B echo 三层闭合（`29c196f`/`bb3ecc0`/`e7519ac`）、worker 大批 `7cce5f9`（#74/#78/llm_hook BYOK/share 三闸）、share 链全线（`1cf12e2`/`746e87f`/`05ab768`）、**modec-postfix `75fc518`**（dirty-gate PASS，pipe-xel 54→65）、worker expect_cjk `05a2fab` | 见 §6 深夜波更新 |

## 6. 深夜波更新（2026-09-17 凌晨，总协调 texlate-41 上任）

**大口径**：loop1 末条 record union pdf 89.1%（4506/5059），M2 门 ≥90% 差 ~1pt；真残无 PDF = 59 fixloop:fail + 80 skip + 414 latex209 wontfix。`realpostfix2` 真臂 n100 `--recode` 复跑为正式测量臂（chunk 源近全量漂移 → 实为全量重译臂，ETA ~9-11h/12h budget，records 增量落盘）。

**1e 深夜波落地**（承接 §5 行的 7-agent 波次全交付 + 二波）：

- **归因三件套**：`02312cd` bug-B 机理翻案（管线侧 gap-in-chunk + edge-strip，非 LLM echo，`a6b58d4` 后全愈）；`3833839` modec-postfix 残余全归因（**PH 嵌 cs 名中段**断 cs 新签名 → 路由 1d L0 检查；accent 展开缺字 U+0332/00C5/0131 盲区 → 项目体验方式；JINST shim 草案 → 已落 `e6ecb85`）；`c818199` armed channel 计量（语料 1/3972 带 sigs 永不进 chunk → 基线实证 0）。
- **判定/引擎侧**：`0c4e4b8` invalid_utf8 红线限工程文件源（file-stack 最内层帧归属，系统 texmf 降级 sys_warn 留痕）；`b989fd5` quantumarticle 选项拼写 `allowfontchageintitle`→`allowfontchangeintitle`（**一个字母**——selectfont 陷阱从未被绕过，签名 5 全灭，scout-coreleak 实证归因）。
- **share §6 全链闭环**：`4b537df` POST /api/task/{id}/share/pack 事后打包端点（幂等+守卫阶梯+reuse_hit options 行级标记）→ `aa8759a` done/partial 面板「分享本译文」按钮三挂载面。至此 §6 服务端+前端全闭（此前消费侧 `a6b75c5`、完成钩 `746e87f`）。
- **offline 通道**：`8af61c5` fetch `--offline`/`TEXLATE_OFFLINE` → `7c2f5a5` run 同款透传（残余联网点清单：tectonic bundle 冷拉/env_judge/fixloop_llm/server 模式）。
- **web 波**：`95b3c58` usage 细分面板 + Settings 清 key；`629571c` per-request BYOK key 三建任务路径（server 端 `_auth` 已收头零缺口）。
- **质量波**：`952eac7` server-sweep（heartbeat check-then-use 竞态修真 + spec 常量单源）；`f00b93b` export-sweep（死字段/静默吞错留痕）；`3443add` cli-sweep + `a6b75c5` share-consume + web-polish。
- **Mode-B/C 复证**：`6632cce` modec-core n80s7 门槛 PASS（escaped/dirty/armed 全 0 第二层第二种子）；**Mode-C mid-cs 截断 ×8 同族复证**（两层 14 格 → PH-in-cs L0 检查升最高优先）；新签名 jpsj3 目标类不存在 + CJK 域泄漏（实拆三机理：TS1 `\t` 域绕过/quantumarticle 拼写/jpsj3 盲改）。

**路由给 1d 的 ready-to-apply 规格**（`c4db001`/`eb89d55`）：PH-in-cs 双落点（l0 第 10 条 ERROR + pipeline `_intercept_ph_in_cs` 副层盖续跑/缓存旁路；正则须双侧夹持 `\\[a-zA-Z@]+\[\[..\]\][a-zA-Z@]` + Counter 净差——裸 `\\[a-zA-Z]*\[\[PH` 对 5% 合法尾邻 FP）；latex209 改名场景目标类可解析性检查（rglob 随包 + kpsewhich 系统，kpsewhich 缺席 fail-open → reject `latex209_no_target`）；inject `\DeclareUnicodeAccent{\t}{"0361}` TS1→TU 提升。

**在飞（1e）**：realpostfix2（bg 测量臂 ~3h/9-11h）；xlat-sweep（xlat/+validate/ 残余审计，l0/pipeline 只读避 1d 活面）；epub-nobody（无 body 畸形 xhtml 防崩）；arxiv-sweep（arxiv/ 残余，fetch.py 冻结）；web-idem（Idempotency-Key create 路径接线）——**2026-09-17 五项全收口**（`e6ff7f8`/`ce7d982`+`d600c44`/`8cb1446`+`e07af9c`/`c06b4bb`，realpostfix2 见 §7）。

**1e lane 残余清单**：Idempotency-Key 已核实服务端零缺口、前端三 create 路发头已落 `c06b4bb`；`--offline --server` 互斥与否已裁=维持静默不拒（与既有本地旗标语义一致）；epub export_epub/export_docx 转调包装属公共 API 面预留非死代码；work_e2emock keep-list（1d/fixers-slots 欠，fallback {1206.0197, 2410.17957}，磁盘不紧）；英文 UI/上传进度条/split 栏宽拖动=架构级待立项。

**1d 落地波（深夜续，routing spec 全消化）**：

- **PH-in-cs L0 第 10 条** `607704e`+`9f96f8b`：双侧夹持 `\\[a-zA-Z@]+\[\[..\]\][a-zA-Z@]` + textutil mask_comments + Counter 净差，Severity.ERROR → 重译/回退原文（不进 fixloop——splice 后载荷不可复原）。pipeline 副层 spec 已转 peer1（含 `_route_chunks` emit 护栏补丁）。
- **`\t` TU accent** `ed7b9ac`：tuenc.def 实证 15 项无 `\t`（U+0361）→ TS1 `\accent` 原语绕 xeCJK → CJK 被饰符丢字；inject 块补 `\DeclareUnicodeAccent{\t}{"0361}`（`\UnicodeEncodingName` 门）。
- **slots wave-2** `d54eb74`：`#174` `\)`/`\]` 混排闭符、`#175` accent 两形（`r` 入 ACCENT_CHARS）、`#176` bug-B splice 守卫 `_seg_join`（cs 尾+字母头接缝插空格）+ `_LATIN_ITEM_RX`（`\item(?=[A-Z])` 保险丝）。**镜像漂移实锤并修**：`7817aa1` e2e `_expand_tokens`/`_chunk_spans` 复刻两变换——否则 find 失配 → 块归 None → L2 静默丢归因（`4ce255e` short_arg 同款教训二次应验：reconstruct 译文侧任何字节变换必须同步查镜像）。
- **#169 flake 定案** `1076086`：popped-source 抢跑尾盖 + `id()` 地址复用遮蔽（~1/20 概率）——双闸修复（live_srcs 持引用防地址复用 + tokbuf 残 token 闸门）+ 确定性回归钉（bytearray 垫占 freed 地址，ungated 60/60 必炸）。
- **slot 二分实装** `558c6c1`：`SLOT_MAX_CHARS` spec 参数从死常量变实装（`_make_slots` 走 `batch.split_long_chunk` 句界二分）；`PhValidator` 死协议类删除（签名与真缝不符）。
- **新派发 → 已交付**：jpsj3 目标类可解析守卫 `9c381cf`（`_target_resolvable` rglob+kpsewhich fail-open → reject `latex209_no_target`）；aipcheck.tex bundled 覆写 `1e6ea75`（`JUNK_FILE_STUBS` 名单挂 normalize_project 首步，stub 与 fixloop shim 同文，1109.2354 真编出 4 页 PDF）；hyperref 驱动剥除 → peer1 rules 车道。maintex 附带观察：1206.0565 main 命中 `aipguide.tex` 类指南非论文本体——E 桶 docs-vs-paper 同族，记档。
- **收口**：fixer-slots/209mc/maintex 交付毕全关，1d 侧 subagent roster 清空；scorecard 自查 `b04b96d`——89.17%（+43 到 90%），2f 复验 75 no_main_tex + 4 BrokenProcessPool 在飞（`7f20897` body 加权吃这批）。

## 7. 2026-09-17 扫荡波收口清单

大扫荡波（texlate-41 协调，~24 agent）全数落库；mock 全语料门 4527→**4537/89.68%**（差 +17，机械面枯竭，残路径=2f 再生成波 + catscope 重切 + B/C detect）；realpostfix2 真臂收官 **96%**（union pdf，n=100）。逐 agent 交付物：

| agent | 交付物 | commit | 状态 |
| --- | --- | --- | --- |
| web-idem | create 三路 Idempotency-Key（client.ts+mock+8 vitest）；server 端契约核实零缺口 | `c06b4bb` | 收口 |
| web-tests | sharePack/homeByok/taskStats 三 edge 文件 +25 vitest（118 全绿） | `56904a5` | 收口 |
| web-i18n | 硬编码 5 处接线 + Record 回退 2 处 + title 接线 + i18n 契约测试 | `293c96f` | 收口 |
| mock-parity | mock-api 形态漂移 9 修 + dedup/reuse/idempotency 全链 | `d5c6fe7` | 收口 |
| docs-sync | tools-runbook/web-layer/shared-cache 三文档对齐落地特性 | `6c9d567` | 收口 |
| share-audit | share 安全面 6 修（文件名逃逸/NUL·超长名/异常面/发布竞态/幂等 bytes/跨设备 move） | `9325aa1` | 收口 |
| share-wire | 隐式 share 命中接线（post-parse `index_lookup`→`_stage_share_apply`，零 token） | `d3fb38b` | 收口 |
| upload-hardening | `_parse_multipart` 有界读堵 413 旁路 + share_import 孤儿目录收净 | `ebb4ef0` | 收口 |
| app-contracts | 18 端点守卫阶梯矩阵 + settings server 模式 403 闸 + options intake 清洗 | `08eb73a` | 收口 |
| server-deep | idem_key 一等列+复合索引、cache_key 索引、SSE 队列限界 512、warnings 下推 SQL | `bd8b1ed` | 收口 |
| align-sweep | align.py 4 修（无 /Top 锚排序/畸形 Top/mediabox/Resources 继承）+5 测试 | `47373cb` | 收口 |
| texlog-sweep | missing-char 括弧字形污染修 + 无括弧早退 ~3.4x | `bd12931` | 收口 |
| texlog-popped | `popped_files` 贯通 texlog→ErrReport/LogInfo（#78 L2 归因洞前置） | `e32e90e` | 收口；消费侧接线转 项目体验方式 |
| docx-sweep | docx 8 修（hidden rPr 污染/specVanish/mc:Fallback 双计/paraId 克隆/noBreakHyphen/w:lang 戳/moveFrom/no-body） | `d600c44` | 收口 |
| bench-hygiene | bench/py 12 文件小修（死码 4/路径漂移 2/runner 标注 4/docstring 2） | `3c37ea4` | 收口 |
| scripts-ci | scripts 8 修（CI 必红 2 项：gwcap SC2034、repro.sh shfmt）+ CI 漂移表 | `1c27c8b` | 收口；lint:js 严格度对齐 `89a4065`、gitleaks job `90f9fd2` |
| arxiv-stale | 缓存命中 stale-version hint（`resolve_version` 复用 + warnings 通道） | `e07af9c` | 收口 |
| xlat-sweep | xlat/+validate/ 残余审计 + 3 小修（slots 分支合并/ensure_deps 留痕/十规则计数） | `e6ff7f8` | 收口；SLOT_MAX_CHARS 实装 `558c6c1`、PhValidator 已删 |
| spec-xlat | docs/08 xlat 面对账（只读）：未落地 10 项 + 勘误 5 条 | `6c8fbb5` | 收口；勘误批已落 docs/06/08 |
| scout-e2ereal | e2e_real_bench resume/recode 审计（只读）：9 风险（--date 分叉/印章漂移/rc141 信号归因等） | `6c8fbb5` | 收口 |
| scout-pf2fails | realpostfix2 早期 13 格归因 + 5 新签名（翻译裸 cs/shim 保真/数学字体域 misschar/graphic_repair 缺口/normalize 揭罩） | report（随 `3c37ea4` 入库） | 收口；裸 cs 已落 L0#11 `de03153` |
| corrosion-rerun | 28 格 mock 重译：10 出 pdf、CJK 指纹清零、残 18 归因（真错 11/结构残损 5/YamlishError 2） | `f18a511`/`a9c13a4`/`534e533` | 收口 |
| no-main-tex-attr | 75 reject+4 BPP 归因：fixable-detect 12（A6/B4/C2）/upstream-wontfix 63；BPP 3/4 转 ok | `c1c8f96` | 收口；P-A `7a78b66`、P-C `e840ab0` 已落，P-B 待 1d 裁 |
| utf8-rerun | 545 格复验：compile-clean 387、end-state clean +373、invalid_utf8 残 5（atend-bbox 数据行） | `7629299` | 收口；P-E 提案待 1d 裁 |
| realpostfix2 | 真臂 n=100 收官：union pdf 96%、union clean 87（pipe-xel 76 + fix 救 11）、splice 残留 0、回归 2 格；snapshot manifest 存证 | `a0d8024`（+overseer 台账 `96b9a9c`） | 收口 |
| fixable-data | 35 残格裁定落地（shim bodies/babel_opt/driver rewrites） | `2049ad3`/`1359b9c` | 收口 |
| 1d 落地波 | catcode scope `9a44100` + CR/CRLF EOL `e840ab0` + L0#11 bare_cs `de03153` + ph_in_cs pipeline 副层 `7de27e7` + bare_cs 单源化 `9909f41`（`textutil.bare_cs_net`+`MATH_CS` 导出，`_intercept_bare_cs` 规格转 peer1） | 五 hash | 收口；catscope 后全量重切波在飞 |
| worker-consistency | stage 函数不变量审计 | — | 在飞（#148） |

**留存 open 项**（扫荡波未消化，归下轮路由）：

- **spec-xlat 未落地 10 项**：三表死链（`save_maps` 无生产调用方）、免费集动态发现无生产接线、env_text kind 全链死路、env_judge 默认关 vs spec 标准机制、`invalidation_tags` 未接线、段内规则三缺二、file_cache_key 缺 `base_url`、修复器模型不符（impl `swe-2-medium` vs spec `swe-2-max`）、anthropic `cache_control` 缺字段、e2e `_translate_tree` 裸 pipeline——按归属已转 1d/项目体验方式。**1d 侧 #10 已落 `8ea2b4a`**（e2e 挂 `Glossary.load(placeholders=…)`+段缓存；export `drive_pipeline` ph 恒等注入——`[[IMG_n]]` 实证进 system prompt）。
- **texlog-popped 消费侧**：`llm_hook._resolve_err_file`/`_requester_paths` 接 popped 尾段（#78 正修），归 项目体验方式。
- **scout-e2ereal 风险 9 项**：`--date` 跨日重启分叉、印章只钉 live repo、浅合并残键、rc≥128 信号归因逃逸、cases 双行、results.json 撕写、空 records 种子、抽样漂移、auth 不停车——记档待修。
- **scout-pf2fails 签名残余**：shim 保真 3 子型（aa.cls→natbib author-year、aipproc→theacknowledgments、aastex63→`_` catcode）、数学字体域 misschar 无规则接手、graphic_repair 覆盖缺口——归 项目体验方式规则车道。
- **no-main-tex P-B 已裁并落地** `91d142e`（2026-09-17）：`_walk_inputs` BFS 自 `_body_mass` 抽出共用，bd 存在性谓词放宽到 `\input` 传递闭包（遮盖视图，注释掉的 input/bd 不计），dc 仍本体判定——真格验证 cs/0408015+2105.00092 → main.tex 双翻案；SEKI 双子 0905.2435/0905.4369（封面件 dc + prolog 异形稿）判 wontfix 回归断言钉住。**P-D**（reject 错误码细分 plain_tex/latex209/garbage）、**utf8 P-E**（atend `%%BoundingBox` 头注改写）——待 1d 裁。
- **app-contracts 未修面**：GET settings/health/providers server 模式信息泄漏（产品决策）、`worker.py` `int(options["qps"])` 同型崩溃类、`_auth` 三重读盘 nit。
- **server-deep 取证清单**：`_build_md_zip` 线程约束 docstring、`put_file` loop 停顿 ~100-300ms（修法在 worker 侧）、transition 读-判-写不变量记档。
- **scripts-ci 漂移残余**：bench/results 划出口径分裂（文档措辞 vs 实际 gate）待 leader 定政策；pre-commit eslint glob 不含 ts（CI 比本地严，观察项）。
- **2f 再生成波/全量重切**：catscope `9a44100` 落地后重切波在飞——C 桶×2 实证翻案（1608.02631 chunks=449、gr-qc/0605005 chunks=49，reject→ok 流向 xlat/compile）、0707.4206 chunks 222→186（@-cs 碎块融合）。B 桶裁决见上条（fixer-bdetect 在飞）。
- **新归因在飞**（realpostfix2 recode 露头）：0905.4439 `skip:chunk crash` + 2203.13012/2403.15096/hep-ph/9703228 五新 fault——scout-chunkfault 归因是否 splice/emit/cs 波引入；hep-ph/9910403（唯一 fail 级引入格）scout-pf2final 深掘中（1e 侧）。
- **bundled-shadow 扩展**（scout-bundledshadow 在飞）：aipcheck `\next` 扫描 1109.2354/1206.0565 + svjour 0905.0193 `svepj.clo` 选项文件可见性；**aastex 爆栈**（scout-aastex 在飞）：astro-ph/0104174+0408531 `\begin{document}` 栈溢出，疑 inject×aastex-shim 交互。
- **新残留类（记档）**：pstricks `\psunit 1cm` 的 `1cm` dimen 操作数进 chunk——动态寄存器名进不了槽表，归 fixloop illegal_unit 桶（非 segmenter 切碎）。
- **perf 工单（低优先，不堵门）**：2410.00035/2410.17952/2410.17973 三格 parse 稳定 10-28min（非 catscope 回归），逐 .tex parse_tex <0.1s——嫌疑=巨件非-tex 全量读（2410.17952 带 49.7MB anthology.bib）或 parse_file O(n²)，波每轮拖尾 ~25min。
- **deferred 清单**（§4.3 原位）：v1 退役、e2e_real→lib 降级、L2 编排环共享化、TokenSource Protocol、L2 真 log fixtures——不动。
