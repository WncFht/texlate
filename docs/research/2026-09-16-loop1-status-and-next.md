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
3. **worker-hardening 12 项落地**（1e 在飞 #52）+ 残两件：#74 latest-alias 二次 dedup、#78 L2 归因洞。**注意 `server/worker.py:2763` 有半残 edit（await 外置 SyntaxError）断 test 收集——在飞方收尾。**
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

- **真网关规模验证**（1e 建议）：xlat-real n50 出数后推 n100-200 拿真 clean-rate 分布——mock 臂今日连修 4 个缺陷，真臂还没同等扫过。**postfix n≈81 已出数（在飞收尾，`bench/results/postfix-2026-09-16/`）**：翻译 81/81 篇、chunk ok 8885/8889（4 partial 0 fault）、splice 占位残留 0；pipe-xel clean 50/fail 6/partial 25（clean 61.7% vs mock 臂 45.3%——真译文反而更稳）；pipe-fix 救回 12/13（acceptable 9+best_effort 1+clean 2）。**管线引入退化 9 格**（pipe 非 clean 且 base clean）scout-realreg 归因在飞：0905.4907 已知 bug-E，其余 8 格待归因（疑 bug-B 主场——真臂 latin-token 保留率远高于 mock 四字）。
- **share 生态闭环**（1e）：worker 完成钩自动产包 + index.jsonl 服务形态（§8）。
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

**在飞（1e）**：realpostfix2（bg 测量臂 ~3h/9-11h）；xlat-sweep（xlat/+validate/ 残余审计，l0/pipeline 只读避 1d 活面）；epub-nobody（无 body 畸形 xhtml 防崩）；arxiv-sweep（arxiv/ 残余，fetch.py 冻结）；web-idem（Idempotency-Key create 路径接线）。

**1e lane 残余清单**：Idempotency-Key server 端契约待 web-idem 核实（缺口则纯前端发头）；`--offline --server` 互斥与否已裁=维持静默不拒（与既有本地旗标语义一致）；epub export_epub/export_docx 转调包装属公共 API 面预留非死代码；work_e2emock keep-list（1d/fixers-slots 欠，fallback {1206.0197, 2410.17957}，磁盘不紧）；英文 UI/上传进度条/split 栏宽拖动=架构级待立项。
