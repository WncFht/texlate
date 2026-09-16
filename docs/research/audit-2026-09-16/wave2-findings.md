# 审计波二（2026-09-16 午后）— 9-scout 发现台账与路由

> 触发：leader（texlate-1d）派 9 只读 scout 全仓复扫，配合「优化改进重构整理」目标。
> 本台账记每条发现的处置：**fixed**=已落 commit、**fixer**=修复 agent 在飞、
> **routed**=按文件归属转 peer、**deferred**=收敛决策项、**wontfix**=判定不动。
> 归属约定：latex/e2e/fixloop/bench/tests/横切=1d；compile/engine.py、
> xlat/pipeline.py、fixloop/rules.yaml=项目体验方式；server/worker/probe/web=1e。

## scout 交付总览

| scout | 范围 | 条数 | 处置分布 |
| --- | --- | --- | --- |
| audit-latex-core | segmenter/gullet/mouth | 12+琐 | fixer-latex |
| audit-latex-periph | scanner v1/macro_table/flatten/api/model/tables/init | 9+退役清单 | fixer-latex + deferred(v1 退役) |
| audit-compile | compile 七件 | 10+附记 | routed 项目体验方式（engine.py），judge 小项 fixed |
| audit-fixloop | fixloop 全件+接线 | 12 | fixer-fixloop + routed(rules.yaml) |
| audit-xlat | xlat/*+接线面 | 11 | routed 1e(worker)/项目体验方式(pipeline)，client 项 fixer-e2e-misc |
| audit-server-e2e | server/e2e/cli/align/export | 12 | routed 1e ×9，leader 侧 fixer-e2e-misc ×3 |
| audit-tests-2 | tests/ 92 文件 | 10 | fixer-tests ×5 + routed 1e(staticfiles) |
| audit-bench | bench/py 全件 | 10 | fixed(misschar P0) + fixer-triage + fixer-bench-hygiene |
| audit-crosscut | TODO/docs/命名/依赖 | 7 | fixed 5583176（三件 doc 漂移+超集注释）+ deferred ×3 |

## P0 / 实证缺陷（已修）

- **`stagerun --on misschar` 恒选 0**：`_on_misschar` 读顶层 `crec["verdict"]`，compile rec 实际嵌 `metrics.verdict` → `2d2a412`（实证：修后 663 格 partial / 154906 缺字入闸）。peer 确认 misschar 轮未跑、直接吃活代码。
- **`_group_surface` 复刻 `_dispatch` 漂移**（segmenter.py:979 vs 1270）：组内 REF 判定漏 `"hyperref"` 排除 → 展开组内 `\hyperref[o]{text}` 可译参被 REF 整吞；缺 verb 行 → 组内 `\verb` 泄进 surface。→ fixer-latex P0。
- **triage `leftover_ph→core` 不可达**：xlat 错误写 `cat="xlat",code="leftover_ph"`，classify 按 cat 路由 → 全归 rule 且 `xlat:fault=N` 按计数碎 sig。→ fixer-triage。

## 修复交付（6 fixer 全落）

- **fixer-triage**（triage/stagerun/benchlib）：末行胜去重（compile.jsonl 已有 79 重复行）、run_meta `started_at/finished_at` 字段、skip 豁免失效+`stub_format:{member}` 碎票、sig 合成单源化（`_verdict_sig` vs `_legacy_sig` 漂移、`_judge_tail` vs `judge_dict` 差 payload）。→ `8460336` + `test_bench_triage.py` 13 例。
- **fixer-bench-hygiene**：死 spike 簇 ~2900 行验证删除（fixloop.py/fixloop_report/compile_bench/compile_report/rerun_xelatex/macro_scan）、`fixloop_bench` 模块级 RS IO 惰性化、`unpack_blob` 归并产品 `arxiv.unpack`。→ `36e195a`。
- **fixer-tests**：pyproject `testpaths`/`norecursedirs`（裸 pytest INTERNALERROR）、`_HAS_RUN_DOC` 遗迹门、SSE `_FEED_DELAY` flake、`_StageError` code 覆盖、file:line 重复钉评估。→ `4a37980` + `pyproject.toml`。
- **fixer-latex**：上列 P0 + `math_debt`/`math_depth` 死机制 + 切点链/input marker/env→PhType 三分收敛 + `FILENAME_CHARS` 单源 + `__init__` 24 死 re-export + `parse_file_v1` top_dir 转发 + `_cov_origin` 复现验证。→ `2f3fc67`（latex slice 346 绿）。
- **fixer-e2e-misc**：e2e mock 臂 partial 译文准入对齐、cli `_thin_submit` KeyError+退出码表、align 错误路径 `heights` 缺席、export epub/docx 双驱同构评估、client 死公共 API 标注。→ `0fe05c1`。
- **fixer-fixloop**：`_when_ok` fail-open→对称 fail-closed+键白名单、`regex_rewrite` 0 命中落 flags、`_gate_eval` dedup 前置、`CtanFetcher.index` 共享索引 mutate、`pdftex_prim` subclassify 误路由、`missing_char_fix` verbatim 防护、`timeout_sec` 消费+timeout 透传链、`stats_backfill` project/corpus 口径、llm_hook 我侧四调用点 opt-in 接线、加挂 vendored_sty_shadow tectonic advisory 档 + `l.N` 行首锚。→ `3c5aae2`（含 peer texmfhome hunk 带署名）。尾项收官：emulateapj/epsf shim-bypass = **裸 payload 机制 bug**（`I can't find file 'epsf'` 裸名 vs 全带扩展名的 filemap/shim_map/stub 键 → `_apply_install_file` 补 `.tex` 候选 + `legacy_pkg_shim` 归一 `X.tex`，随 `3c5aae2` 落）；emulateapj*.sty 实为 TL 内容缺口（只发 .cls）→ shim_map 扩列转 peer1（rules.yaml）；另揭 static_precheck scan_patterns 疑不覆盖 `\input` 裸名（同转）。

## 已路由 peer

**项目体验方式**（compile/engine.py + pipeline.py + rules.yaml）：

- pipeline：LengthTruncatedError 双重放大（已裁 `max_tries=2`，落 `f22c0fe`）、`_route_chunks` 纯占位符绕拦截面（已堵）、`_one_chunk` 缓存丢 batch_id（已补）、skipped 双轨（缓行另立 ticket）、leftover_ph 集合差保持（注释留证）。
- engine.py：`_ERROR_RULES` vs rules.yaml taxonomy 双轨漂移（缺 8 id+3 变体组）、env 降级模式 `-shell-escape` 无兜底（安全）、tectonic `-Z` 直通后门、latex209 head 松版残留、`sandbox_wrap` extra_rw 不转发、`run_process` OSError 无捕获、`parse_log` vs `logparse` 口径差（ctx 9v8/l.N 锚位/warnings 词表）、路由信号双表（与 1e 的 probe.py 跨边界）、`include_eps` 死参、TMPDIR 沙箱内空挂、`_TECTONIC_ATTEMPTS` 真超时翻倍。
- rules.yaml：死配置面（capabilities/denylist_*/oracle/cache/params 若干净）、注释反转（epsf/binhex 通路描述、头注 25→36）、`vendored_sty_shadow` tectonic `mode:same` 撒谎（probe 无 cwd 恒 None）。

**texlate-1e**（worker/store/app/probe/web）：

- worker：`ph_fragments` 主路径不武装（recover_copied_tokens 生产死臂）、cancel `run_task` 孤儿化、env_judge/L2 旁路丢 glossary+usage_sink 且污染共享缓存、`_run_fixloop` 不吃 `reject:*`/`engine_flags`（reject_at 缺 fixloop 档+跨引擎臂缺席）、`_build_dual` loop 线程跑 pypdf、cancel TOCTOU force 覆写、`unpack_zip` 单层 parent 检查、`_run_doc` fallback client 泄漏、`_iter_pdf_fonts` IndirectObject、两次 `asyncio.run` 跨 loop 开关 client。
- store/app：`recover_startup` 僵尸 queued、`upload()` 孤儿目录、`chunk_counts["cached"]`/`warnings` 死字段、`staticfiles.py` 孤儿模块+SPA 挂载零测试。

## deferred / 决策项（leader 收敛）

1. **v1 退役**：periph 给了完整切线清单（api/scanner/macro_table/model/tables/gullet/init + ~5 测试文件 + parsebench v1 臂 + TEXLATE_NO_EXPAND 语义）。`flatten_inputs` 与 model 字节原语 bench 承重必留。**判定输入**：v2 已默认且 corpus_v3 3937 全绿——退役收益=删 ~1653 行 scanner+~430 行专属机械+消双臂字段并集；成本=失回退臂。倾向：本轮先不退役（pipeline 仍在演化，回退臂保险费低），清单存档待 M3 前再决。
2. **e2e_real_bench↔stagerun real 臂双轨**：判分同义（同 judge+flb 配方），差异仅记录形状。倾向：e2e_real 退 lib、main 标 legacy；e2e_mock 保留（tectonic 臂+L2 回灌+Mode B/C 唯一事实源）；compilebench_v3 残值=分层抽样+tectonic base。
3. **L2 编排环 e2e↔worker 双份**（`_l2_repair`↔`_l2_repair_zh`、`_env_judge_pass`↔`_env_judge_filter`）：底层原语已共享，编排环漂移中。抽注入 compile_fn/writeback_fn 的驱动函数——跨 1d/1e 边界，需与 1e 协商落点。
4. **status 词表四套混用**（verdict clean/partial/fail+reject、段 ok/fault/skipped、inject already/no-docline/injected、job 11 态）：**已收口**——docs/08 §6 状态词表（20e7a8a）。
5. **`skipped` 语义双轨**（status vs bool 反向命名）：peer1 缓行裁决，另立 rename ticket。
6. **taxonomy 单源化方向**（engine↔rules.yaml）：peer1 裁决中，实现重活在他们侧。
7. **L2 真 log/spikereplay 干净 clone 永跳**：裁 1-2 条小真 log 入库 tests/fixtures/（M，下轮）。
8. **`TokenSource` Protocol 名存实亡**（声明 4 方法实触 8+ 成员 + isinstance 特判×4）：M 重构，列入 backlog。
9. **llm_hook 生产接线**：我侧 bench/e2e opt-in 已在飞；worker 侧等 1e 按 options 开关裁决。

## wontfix / 已核健康

- `_merge_ranges`/`_in_ranges` 公共化：唯一消费面 12 区间线性扫，收益边际——只落超集注释（5583176）。
- `json.loads(read_text)` ×5：单行重复，不动。
- stagerun TODO×2：活标记，保留。
- SSE 500ms 性能门：刻意 spec 门，观察项。
- 依赖表/web package.json/默认引擎序/PH_RX 形状/TEXLATE_LIVE 门/平台门/conftest helper：核实健康。
- fixloop 程序化交叉验证：36 规则 category 全由 taxonomy 产出、17 builtin+2 rewrite 全命中注册表、无 order 冲突/重复 id；8 taxonomy 无规则承接=刻意留白。
- server 哨兵顺序/done 事件配对/单写者纪律/share 对账/dispatcher 死锁修复/L2 cache 跨线程接线：核实干净。
- 观察项：`test_verbatim_policy_pct_inside_unclosed_group` 随机序下挂一次（KeyError `[[CMD_1]]`，隔离+串行全绿）——排序依赖/共享 argspec 态污染嫌疑，立 ticket 待复现 seed（不阻塞）。

## loop1 fixloop 结果分析（stagerun-loop1-2026-09-16；聚合报告 REPORT-fixloop-analysis.md 由项目体验方式执笔，本节为 leader 对账+补充）

数据：1310 格入闸（fail647+misschar663）→ clean 144 / acceptable 663 / best_effort 295 / unfixable ~208 / no_errors_no_pdf 15 / stuck 1，rescue 84.0%。迁移 fail→clean 181 / fail→partial 273 / partial→clean 8。**注意：本轮跑在 engine 修复 6b23435 之前**，环境杀伤需打折。

### partial→fail 17 格：实证后真退化仅 4 格

peer 直编修复后 splice/ 树复验：**13 格为基建杀伤假象**（12/15 修复后引擎直出 pdf），真规则退化只 1003.1717 / 1306.0036 / 2410.00012 / astro-ph/0111575 四格 + 三个硬单案（1803.00012 SIGSEGV rc139、1803.00054 `\usepackage{color}` 真错、1706.02464 bufsize 溢出）。`no_errors_no_pdf` 机理实例（1706.00175）：`(\end occurred when \ifx ... was incomplete)` + `No pages of output` —— TeX 早夭无 `!` 行 → taxonomy 判 clean → 无规则承接。修复方向：a) taxonomy 尾段加 `No pages of output`/`\\end occurred when` pattern 给真类别（rules.yaml，peer1）；b) fixloop 引擎「不退化底板」——快照入口态 PDF、末态判决不低于入口态（mine，下轮候选）；c) judge 记 `killed_signal`（SIGSEGV 类）。triage `regressions:[]` 未捕此簇——探测器只同段同臂比；已补 `fixloop_degraded` 跨段口径（24b4d53，回扫 loop1 全中 17 格）。

### unfixable 大头 = missing_file legacy 包（113 格，fail 残留 59%）

pst-node×11 / jheppub×9 / citesort×7 / diagrams×7 / axodraw×5 / pst-arrow×5 / svjour3×5 + texsort/epsf/emulateapj5/setstack/conm-p-l/imsart/jinstpub/espcrc1 等——CTAN filemap 解不出。**正中在飞的 vendored_sty_shadow tlpdb-index 修复**（tlpdb 索引含 revtex4-1→cls 这类精确映射）；处置面=shim_map/overrides 扩列或真缺档承认。疑点：emulateapj*/epsf 有 shim 仍报 missing_file → vendored_shadow/install 通路未接住，疑规则 bug。`unfixable:pdftex_prim:pdfcompresslevel`×6 部分被 #131 subclassify 收窄覆盖。

### 定点 rerun 第一轮（19 格，peer1 执鞭，`18ff106` 对策已落）

- **nenp 15→2**：misschar 池 12 格 + fail 池 1803.00054 全部改判 `early_eof` 系——**同根因**：稿自带 aastex61/62.cls 内部 `\IfFileExists{revtex4-1.cls}{ok}{…\stop}`，revtex4-1 不在 TL → `\stop` 夹条件内 → `\end occurred when \ifx incomplete` + No pages、rc=0、无 `!`。「类文件求档文」语义非文档 bug。对策：tail plea 规则（`include|download|install|get|need + X.cls/sty` + guard `No pages of output` → missing_file 抓档名，排 early_eof 前）+ shim_map `revtex4-1.cls`→revtex4-2 桥；4 篇抽样全改判 `missing_file:revtex4-1.cls`，13 格二次 rerun 在飞。
- **真退化 4 格**：astro-ph/0111575 → **acceptable_pdf 痊愈**（epsf 裸 payload 修复起效）；1003.1717 仍 unfixable:syntax；1306.0036 stuck→undefined_cs；2410.00012 pdftex_prim→undefined_cs（#131 收窄正确改判）。
- **硬单案**：1803.00012 仍 nenp（post.rc=-11，killed_signal 已记 SIGSEGV）；1706.02464 仍 nenp（rc=1 bufsize 真 bug）。
- **scan_patterns 实证**：1907.00121 装上 epsf.sty/epsf.tex/ulem.sty——`\input` 裸名预检链路通。
- **二轮（13 格 early_eof 复跑）**：全数出 pdf（11 acceptable + 2 best_effort）——plea 规则+revtex4-1 桥闭环。19 格累计 14 出 pdf；残 5 = 1803.00012（SIGSEGV）、1706.02464（bufsize）、1003.1717（syntax）、1306.0036/2410.00012（undefined_cs）。
- **「不退化底板」#20 已落 `2f12955`**（leader 侧 fixloop engine）：入口 pdf 快照双源（precheck 前现存 / rounds[0]）+ 末态失 pdf 非 reject 兜回 + `floor_from`/`floor_restored` 观测面；replay 门②将兜回计入 regressed；stagerun post 复判仍直编裸树保持退化观测真实。killed_signal 归一化 ticket 核销（run_process POSIX 负值约定本就正确）。
- **skip 分布核实**（scout）：compile zh skip 实为 129 格全合法上游门——79 not_translated（parse 失败级联）+49 arm_mismatch+1 gate；**发现排程洞**：zh/ 单槽被 real 臂覆写 → real-50 抽样 48 id 永无 mock compile 数据，loop2 runbook 需先 compile-mock 再 xlat-real（或 zh/ 分臂）。

### regress4 归因（scout-regress4 + 1e repro-1306 收官：管线真退化收敛到 2 格）

**主机理：TEXMFHOME 环境不对称遮蔽（3/4 格）**——stagerun `_compile_judge`（:917 入口编译）跑在 ambient 环境，`~/texmf` 可见；`_fixloop_one`（:1128）冷起 `_texmf` 并经 `XelatexEngine(texmfhome=)` → `engine.py:865-870` 写 TEXMFHOME → `~/texmf` 整树不可见。epsf.tex/revtex4-1.cls/mhchem/chemgreek/algorithm/algpseudocode/ltxgrid 全部只活在 `~/texmf` → 入口编译出 partial pdf、fixloop 里同包全部失踪 → 装错分支/装不上 → 退化。**这不是规则 bug 是 bench harness 包宇宙不一致**——「不退化底板」在产物层兜底，真修法是 texmf 可见性对齐。**已修 `6752bb0`**（peer1：`_env` 内 ambient `~/texmf` 串链进 usertree，签名稳定、worker/bench 零接线；1e 确认 worker `_engine()` 同机理、若未来加参有 followup 预案）。

- **1306.0036**：**翻案——非管线 bug**（1e repro-1306 直编判决 `d2d82e8`）：revtex4-1 4.1s × array v2.6n 在 TL2026 上的既有缺陷，base 臂逐字节同源码同点位同炸（`\document@inithook` 对 array 快照校验失败但 `\let` 交换无条件执行 → `\@classz` 在 `\xdef\@preamble` 内失衡 → 孤儿 `\or`×30）。pipe-vs-base delta 门应记 pre-existing。曾误诊的 prim-guard 自残属实且已修 `88d0ab9`，但修掉后此格仍死于上游缺陷。**转机**：1e 已验证修复规则草案 `bench/results/repro-1306-2026-09-16/revtex4-array-guard.yaml`（order 170 / syntax / gate=revtex4 docclass+`Extra \or` ctx / 在 `\begin{document}` 前注入 `\@mkpream`+`\insert@column` 保存、`\AtBeginDocument` 恢复——**必须 mkpream+insert 对**，仅 mkpream 会 HANG；真源 e2e：补丁后 rc=0 七页 PDF）——转 peer1 落 rules.yaml，TL≥2024 所有 m/p/b 列 revtex 文档受益。残留缺口：splice in-place 无树级回滚（大设计项记档）；guard regex 命中注释行（IEEEtran.cls:552）——转 peer1。
- **1003.1717**：`install_file` 装 fallback 分支 revtex4 → `\input aps.rtx` 命中被 xlat 污染的 `splice/aps.rtx.tex:322`（`\let\frontmatter@ 这是译文 }{}`——csname 槽位腐蚀，fixer-slots 机理覆盖；但**随包 runtime 文件该不该进翻译集**是 pipeline 边界问题，转 peer1 `.rtx` 翻译集边界项）。
- **2410.00012**：完整链 = `install_file` 装 mhchem 不带依赖闭包（chemgreek 缺席）→ 续编译在 log 尾 `Emergency stop` + `File 'chemgreek.sty' not found` + Enter-file-name 死，但**first-error-wins 把头错当类别，尾部真杀手永远拿不到路由**。双修已落（本波）：a) `_apply_install_file` 依赖闭包——装/探测命中的包文件行首 `\RequirePackage`/`\LoadClass` 逐层补装（engine.py `_install_dep_closure`，depth≤2）；b) logparse tail 条目新增 `preempts` 弱类别表——致命收尾可夺路由（字段待 peer1 在 rules.yaml tail 条目上加挂）。另 polyfill 恒头注入同波落（cls 内部读取发生在 `\documentclass` 加载期，类行后注入太晚）。
- **astro-ph/0111575**：rerun 已自愈 acceptable（epsf 裸 payload 修复起效）——off-books。

管线真退化账终值：**2 格**——1003.1717（xlat .rtx 污染，slots 车道覆盖 + peer1 边界决策）与 2410.00012（本波双修后预期转可修）；1306.0036 记 pre-existing 上游缺陷（修复规则已备）。底板设计注记：快照必须是**编译期 PDF 产物字节**（precheck 前现存产物优先）而非 fixloop 环境重编译——astro-ph 型在 fixloop 包宇宙下零 action 也会死；1306.0036 型另需树级回滚（splice 原地 mutate 跨 rerun 继承残行）。

### misschar/invalid_utf8 取证翻案（scout-misschar + fixer-utf8，杠杆面重画）

**misschar 663 格**（scout-misschar，逐格/逐行归因）：96.4% 缺字行是 mock 四字（这是译文）假象；真修组件——**A 桶 114 格整文中文静默消失**（inject 两 bug：`CJK_PRESENT_RE` 被 `\CTeXPreproc` 宏体字面量/`\ctext` 宏名假阳跳注入 + `find_docclass_end` 落死分支）；`_MISSING_CHAR_RE` 只认 `(U+XXXX)` 不认 tfm `("XXXX)` → 416/433 格 missing_char_fix 未触发主因（tfm_only 197 + 码位表外 106 + 无 log 92）；B 桶 336 格数学内 CJK 是 xeCJK interchartoks 够不到的结构洞（warmup 无效，不建议规则修）；D 桶西里尔/拉丁扩展走 `font_fallback` 动作（`\newunicodechar`+fallback 字体）。已全派 fixer-cjkfont（inject.py + builtins 缺字段）；rules.yaml char_table/新条目待交付后转 peer1。

**invalid_utf8 545 格**（fixer-utf8，按 log 括号栈归因到打开文件）：scout 框架「源文件 latin-1」只占小头——**96%（514/538）是系统/用户 texmf 老 CTAN 包自带坏字节**（algorithm.sty 325、algorithmic 206、algorithm2e 120；`/usr/share/texmf-dist` 同族），EPS 头注释 ~20、`[dvips]` 驱动 4（1404.0103 单格 15.7 万条=jpg 全文件扫描）。方案：normalize.py 单点四件套（cwd 包影遮蔽/EPS 注释净化/ps 驱动 token 改写/catch-all 转码），已批准带三防护（不写原工程、vendored 同名跳过、二进制 allowlist 保守）。**judge 语义跟进项**：invalid_utf8 redline 应限定工程文件产生者——物理修复后自然消解，记档待 audit 线裁。

**1e modec-misschar/repro-2501 包**（5 实症，证据 `8fead4c`）：`_on_math` `\)`/`\]` closer 洞 + accent 参数保护 + textcolor/colorbox argspec 遮蔽补丁对 → fixer-slots（并入非文本槽位超簇）；alias-macro opaque（`\nc{\be}{\begin{equation}}` 链断裂）+ `_do_newenv` math-role 推断 → fixer-gullet（新派）。rules.yaml 缺口两枚（DeclareUnicodeCharacter undefined_cs + `Undefined color 'X'` pattern）→ peer1 backstop（`ea0c73e` 已落）。

**fixer-gullet 交付 `ce1dc9f`**：裸 cs 体宏 → `transparent_expand`（`\nc{\be}{\begin{equation}}` 别名链执行，`\[` 开数学符真展开）+ `\newenvironment` body_role 数学角色推断（before 体尾形：mathshift/`\begin{X}`/cs 链解析，v1+v2 双臂对称）——0905.0795/1003.0112a 两格 miss×100/180 修复，9 新测试，全套 2107 绿。

**1e realarm-repro 包**（12 基线真臂退化归因，`253caab`）：预测-fixed 3 格待 real-postfix A/B；新浮出两 bug 类——**bug-B 主路径 cs+latin 融合**（`\item FSU`→`\itemFSU`，5 格；`_cat_surf` `90aa823` 只修了 group 路径，主路径同款洞；`letters_cut` 只告警）→ fixer-slots 追加。bfuse-scout 定规模（`314af54`，`bench/results/bfuse-scout-2026-09-16/`）：**top-5 系统洞**——spec'd-13 触 48% 篇、宽类并集（`{\it X}` 字体声明组 75% 篇为最大头，bib 条目不译同走 writer 融合）触 **90.4%**、每篇 ~13 暴露点；修复面=通用「cs+latin 首 token」边界（\item-only 只买 35%）；cs+CJK 方向无害（cjk_glue_fix 已盖）；致命条件=译文保 latin 首字母（专名/缩写）；**bug-G elsart `\protect` 测盒 × xeCJK 绑定崩坏**（cond-mat/0307508 全文 4379 缺字，最小 repro `\def\protect{\noexpand\protect\noexpand}`+hbox CJK 通用陷阱）→ peer1 rules 车道，但 cjkfont `CJK_FIRST_USE_WARMUP` 疑似同根已兜（1003.5459 elsart 5485→0），peer1 复核中。gtrap-scout（`7896c7f`，报告 `bench/results/gtrap-scout-2026-09-16/report.md`）补面：**autart.cls 同载体**（`\proc@elem` 与 elsart 逐字节相同，corpus_v3 4 篇：1306.5836/1706.02495/2003.03498/2308.04287），Tier-A trap-live 全表 17 篇即本类验证集；升级标志=「warmup 后 miss 仍在」（接 misschar 判读口径）；若 warmup 有缺口，fixloop 反应式签名+主动 cls 扫描草案在报告 §c 已转 peer1。bug-E（0905.4907 caption 裸 `\alpha`）→ peer1 backstop/prompt。

**fixer-utf8 交付 `673d8ce`**：normalize 四臂（系统包 kpsewhich 遮蔽 ≤8 轮闭包 / EPS `%`-行净化 / ps 驱动 token→xetex / catch-all 转码），真格 invalid_utf8=0；judge 按「警告来源是否工程文件」分流记档待裁。**fixer-209up 交付**：`upgrade_209` + inject 挂点 + 414 普查 **97.8% 过门**（405 格；reject 9 全 ds@ terminal），白名单 +15。**fixer-cjkfont phase-2 五项全落 `f7822a8`**（inject 包同 commit）：CJK_PRESENT_RE 包/类语境收紧灭三假阳 + find_docclass_ends 逐缝注入（depth>0 宏体命中跳过、`\if` 双臂幂等哨兵，真格 9/9）+ `_MISSING_CHAR_RE` tfm `("XXXX)` 分支（197 格解锁）+ `cjk_glyph` spec 字体门 + `font_fallback` builtin（西里尔/组合符/拉丁扩展→`\newunicodechar`+Libertinus Serif；rules.yaml order26 条目草案已转 peer1）。**B 桶 336 格连带治愈**：`CJK_MATH_FALLBACK` \Umathcode 九段重映与是否触发 fixloop 无关，数学内 CJK + texlatefb 兜底西里尔数学缺字——scout「不修」判词被机制性覆盖。

## loop2-delta `b4akkgal5` 收官（records `cd17eb5` + 补记 `581f374`）

- 终态 1310 格：acceptable 669 / best_effort 363 / clean 157 → **出 pdf 90.8%**（loop1 84.0%）；unfixable 112；missing_file **113→32**；nenp **15→1**（残 1803.00012 SIGSEGV）；partial→fail 仅 2。
- **rundiff vs `5acb956`：improved 73 / degraded 0**——fail→clean 16 + fail→partial 57 全为缺文件簇救回；floor_restored 全格 False。
- 残格归因三落：axessibility×6 → `axessibility_xetex_shadow` order157（`7037301`）；axodraw2×5 → CTAN overlay=tree 兜底 tlmgr non-relocatable rc=0 假成功（`9f08bf3`，同机理或覆盖其他 postaction 包）；pst-all×8 → **install_file 请求方扇出**（`8e6d442`：file:line 锚解要求方→`\RequirePackage` 全表一轮补装）。
- **peer1 裁定回执**：bug-E 不立规则归 llm_hook（单格半径不值）；prim-guard 注释行命中接受不改；latex209 gate order:1 已 terminal 无需补；bug-G 终裁 warmup 10/10 治愈不落签名规则（autart 同构预期同治，real-postfix 复扫给终证）。
- **方法论旗标（判读纪律）**：烤疤格=被已修 bug 写坏的 splice 跨 `--rerun` 永存（1306.0036 第30行 `\chardef\ifdefined\pdfoutput\pdfoutput=1\fi` 残行实证），需 pristine-tree 重跑见真值，rundiff 不计入规则退化。

### 定点重跑 34 格收官（peer1 补记7 `e769ebb`，全部先 `--rerun` 洗 pristine splice）

- axessibility×6 → **6/6 pdf**（shadow stub 实证）；axodraw2×5 → **5/5 pdf**（CTAN tree 兜底实证，含 real 臂 hep-ph/0501163）；pst-all×8 → **7/8 pdf**（请求方扇出一轮补全 11 成员实证；残 2105.11398 越过 missing_file 改判 illegal_unit——前进非退化）。
- 烤疤格实锤：1306.0036 pristine 树 → best_effort（relax 格确为旧套娃残留）；1003.1717 → acceptable（`.rtx` 排除 + revtex4 guard 合流）。**partial→fail 清零**。
- early_eof×13 → 全数脱离 unfixable；子机理两分：**(a)** `\end occurred when \ifx incomplete`（条件未闭合+稿自带 \errmessage）vs **(b)** `job aborted, no legal \end found`（输入截断/`\endinput` 吞 `\end`）——不同源，归下轮签名归因（rules.yaml peer1 面）。
- 终盘 unfixable：missing_file ~27（余皆 TL 真缺席 legacy 簇）、pdftex_prim 0、max_rounds 1、**early_eof 成最大残簇**。

## postfix 真臂 9 格管线引入退化归因（scout-realreg，`postfix-2026-09-16` n≈81 收尾中）

| id | 归因 | 签名 |
| --- | --- | --- |
| 1012.1321 / 2003.10959 / 2105.03900 / 2211.04495 | **bug-B**（`\item`+latin 首词空格融合） | `\itemFSU`/`\itemNGA`/`\itemBalakrishnan`/`\itemOC` |
| 1003.4522 | bug-B 换行屏障变体 | `\hline`+⏎→`\hlineCd`/`\hlineNb` |
| 1206.1808 | bug-B `%`-EOL 屏障变体 | `\par`+`%`+⏎→`\pari)`/`\parii)` |
| 0905.4907 | bug-E（模型直译 "alpha"→裸 `\alpha` 进 caption） | Missing $ ×4；pipe-fix acceptable 兜底 |
| 0707.3950 | **新机理A**：用户 `\def\section` 替换体含 @-cs 被展开泄漏到非 makeatletter 语境 | `\@`→`\spacefactor` 40 err；pipe-fix best_effort 兜底 |
| 1109.5963 | **新机理B**：caption 短参被塞进空行 → `\par` 撞 `\NR@gettitle` runaway + Extra } 级联 | l.362/364 五错级联 |

聚合：**bug-B 家族 6/9 是真臂头号杀手**（mock 四字译文 CJK 首字天然免疫，真臂 latin-token 保留才暴露）——修复面=cs+latin 边界的空格/换行/`%`-EOL 三屏障（已转 fixer-slots）。bug-G 残余 0/9 → warmup 真臂成立。新机理 A（含 @-token 宏不应展开/应回写调用形式）与 B（caption 短参空行）记 1d 队列。pipe-fix 仅 2/9 格有记录——`onfail` 覆盖语义已向 1e 求证。

## delta 残盘归因三件套（scout-cjk0 / scout-pst / scout-unfix）+ 1e postfix A/B 终报

### scout-cjk0：`cjk_chars=0` 实为 28 格（旧账 14），splice/ph_map 丢失 = **0 bug**

| 桶 | 格数 | 归因 | 处置 |
| --- | --- | --- | --- |
| A | 8 | inject 落死 `\if` 分支 | **已愈** `f7822a8` find_docclass_ends 逐缝注入 |
| C | 7 | `CJK_PRESENT_RE` 假阳跳注入 | **已愈** `f7822a8` 包/类语境收紧 |
| D | 1 | 1206.0294 dimen→中文（slots 腐蚀） | fixer-slots 机理覆盖 |
| E | 1 | 1803.02985 standalone main 与论文正文章节 disjoint | **决策项**：main_rel 选取 vs 翻译集边界——无属主，记档 |
| F | 11 | includepdf 壳文档本就零可译 chunk | **verdict 假阳**：0-chunk main 不该吃 `cjk_chars=0` partial → verdict-tune 项（判分侧，1d） |

附带实证：fixloop warmup 首编同样锚进死分支（pre-fix），`f7822a8` 后共用 find_docclass_ends 一并覆盖。**结论：splice 层无 cjk=0 缺陷，全为上游/判分侧伪影。**

### scout-pst：六家族逐格归因（pst 残链根因 = `\input` 裸名扫描盲区）

| 家族 | 根因 | 处置 |
| --- | --- | --- |
| pst-node/pst-arrow | pstricks-add.tex l.27-32 `\ifx\else \input stem \fi` **行内**裸名链——`_DEP_DECL_RE` 只认行首 RequirePackage/LoadClass/usepackage → 一轮暴露一个烧光 8 轮 | **已修 `ca0e748`**：`_dep_stems` 加行内 `\input` 扫描（注释切尾 + `\endinput` 不误伤）+ advisory 全败才落（裸名 miss→`.tex` fallback 常态路径不再污染归因） |
| axodraw×5 | shim→axodraw2 non-relocatable usermode rc=0 假成功 | 已修 `6752bb0`/`9f08bf3`，定点 rerun 5/5 |
| emulateapj | 6/7 noop stub 救回；残 = `emulateapj-rtx4.cls` 无 shim 键（1404.2351） | → peer1 shim_map 补键 |
| citesort | 7/7 救回 | — |
| revtex4-1.cls | **误标签非 missing_file**——filemap 可解恒装上；残 = capacity×2 + syntax（.rtx 污染，已修） | 签名归仍需按真错记 |

附带发现已落：precheck `scan_patterns` 扫 `\input` 裸名**不切注释**（`% \input x` 照装 x——本波测试实锤 `pst-notreal.tex` 被 precheck 装出）→ 小项转 peer1。

### scout-unfix：delta 尾 127 fail 行（123 唯一格）残盘分布——零回归

- **~24-29 格**已被 19:00 后落地波覆盖（cjkfont/precheck/fanout 等）。
- **~45-50 格机械新规则胜场**（逐名枚举已转 peer1）：shim 波二 ~20 个 tlpdb 外出版商文件（svmult/cimento/eptcs/PoS/nature2/…）、babel_opt×10（剥 legacy babel 选项新规则）、lgrenc pattern×3（head pattern 缺 `Cannot find the file X` 措辞 → +1 pattern 归 missing_file）、hyperref-driver×2、expl3 backend×4、option_clash/already_def/pkg_order/JINST×5。
- ~10-15 peer 侧（signature/taxonomy 面）；~5-8 terminal（SIGSEGV/capacity/pstricks-xetex 硬墙）；~30 长尾。
- 判读纪律：污染 wdir 格须 pristine 重跑非 rerun；tail-preempt 增益尚未计入此表。

### 1e real-postfix A/B 终报（`0d1526d`，100/100 零异常）——bug-B 定位翻转

- 预测核销：1511.02908 ✓（`90aa823`）；0707.3950 ✗ 仍炸（gullet-opaque **第二路径**，fixer-emit #167 在飞）；hep-ph/9910403 半——`f5da4bf`+`90aa823` 灭 runaway/rmand 但露出 **expl3_backend 新失败模态**（fixloop unfixable，与 scout-unfix expl3×4 疑似同簇 → peer1）；math/0307301 意外转 clean（`\itemFlop` 被 re-roll 自发消）。
- **bug-B 重解读（fixer-slots 关键）**：`\item<Cap>` 融合 flat 10→9——segmenter 修不动它，因融合发生在 **LLM echo 侧**（模型回显把 `\item` 粘后随大写 token）；re-roll 29% 双向 churn（2211.04495 `\itemOC` 新生）。segmenter/writer 修只治「源有分隔被吞」半边；LLM 产出融合需**交付侧/splice 侧守卫**——候选 `\\item(?=[A-Z])` 强插空格（无合法 `\item<Cap>` 先例，bfuse 普查真融合仅痕量；splice-time repair 优于 L0 fault——意图无歧义不必重试）。
- **bug-G 终证**：cond-mat/0307508 pipe-xel 仍 4379 miss 但 pipe-fix 经 warmup 救回 clean——warmup 仅 fixloop 臂生效（首编不戴）；1706 外 18 臂救回 16/18。
- latex209 两格 reject→partial（shim/209up 后不再硬拒）；`419cf13` 后 postfix 臂 18 跑 vs 基线 40 跑不可直比（indicative）。

### peer1 回执与二轮落地（`3010310` / 口头确认）

- **lgrenc×3 已独立落地**：textgreek.sty:39 `\PackageError` 报 `Cannot find the file lgrenc.def`（无反引号对）逃出两条 head 签名，halt 后 tail 被 early_eof 抢路由——head 加第三 pattern `Cannot find the file\s+([\w@.+-]+\.[a-zA-Z0-9]+)` → greek-fontenc 通吃，重跑 3/3 best_effort。
- **early_eof ×13 全格归因**（REPORT 补记7 修订）：missing_file 伪装 ×3（上条已愈）、`\read` 交互档 ×1（hep-ph/0111248 bundled aipcheck.tex:259，wdir stub 候选）、`no legal \end` ×4 四根各异（^^M 截断/`{` runaway/`\if` 缺 `\fi`/command-ignored Emergency——无统一规则面，逐格或 llm_hook）、错误帽 100 ×2（1608.06693/2308.12612 上游个案）、svjour 选项 errmessage ×1（0905.0193）、腐蚀 ×1（1404.0519 `\c{S}` 口音参数改写 → slots 超簇）、SIGKILL ×1（2211.13028 infra）。
- **peer1 接单**：shim 波二 ~20 名 + emulateapj-rtx4/JINST 键 + babel_opt×10 + hyperref-driver/expl3×4(含 hep-ph/9910403)/option_clash/already_def/pkg_order 小簇，顺序 shim→babel_opt→小簇。
- **回弹我侧两项已落 `450b1ad`**：precheck `\input` 扫描逐行切注释（`_apply_scan_install` code-portion 化，pst-notreal 不再被装）；F 桶 verdict 修——`expect_cjk` 全 zh 臂调用点改由 translate chunks 派生（e2e/stagerun×2/e2e_real×2/e2e_mock；worker 侧已转 1e）。
- **E 桶裁定 pipeline 面收**（peer1）：main_rel 选取加「`\begin{document}` 后实质 body」权重——落点 inject.py `find_main_tex`（1d，task #170）。
- **L2 红旗哨**：`test_l2_runs_before_fixloop` 持续红（done≠partial，纯 `\badcs` 假 log 与 taxonomy 无关，HEAD 复现）——dirty 树 gullet/macro_table/reconstruct（fixer-slots 在飞）嫌疑最大，slots 交付后仍红则升 ticket（#171 观察项）。

### L2 红旗闭环 + emit 交付入库（`e65c56c` / `4ce255e`）

- **L2 红根因 = 归因镜像漂移，非 slots 断面**：emit 的 `reconstruct.expand` 短参 `\n\n`→`\n` 折叠（#168）落盘字节变了，但 e2e `_expand_tokens`/`_chunk_spans`（L2 tex_line→chunk 归因的预测器）没同步——resplice 后算出的未折叠 body `find` 失败 → `spans[cid]=None` → 二次归因 hits2 全空 → `fallback_src`/`unresolved` 双空 → 无 fallback_orig → fixloop 下一编转绿 → **partial→done**。已修（`4ce255e`）：`_expand_tokens.rep` 对「已译 ∧ context∉{para,item}」的 `[[CHUNK_n]]` 同压折叠，`_chunk_spans` 改走 token 入口与 reconstruct 同构。test_server_l2 11/11 绿、全套 2201 绿（余红仅 #169 序依赖 flake）。**教训留档：splice 侧折叠/改写规则今后每动一处，e2e.py `_expand_tokens` 是同改点**。
- **emit #167 入库 `e65c56c`**：`_has_at_cs`（gullet `_classify`）+ `_AT_CS_RX`/`_AT_CSNAME_RX`（macro_table OPAQUE 判据）双臂——含 csname 合成 @-cs 第二路径。0707.3950 "修复后仍炸"证为 **`_paper_done` 陈字节**（record `translate.seconds=0.0` 整篇 carry-over，postfix 臂编译打 17:55 旧 tex）；新代码全臂复验 0 err 0 spacefactor。
- **`_paper_done` 陈字节立 #173**（我车道 e2e_real_bench.py）：resume 谓词对 splice/parse 层修复会误判 done——下次真臂重跑（n100+）前必落强制重 translate 条件，1e 侧已对齐等它再发。
- **modec-postfix n=80（1e `75fc518`）**：gate PASS（escaped=0 dirty=0），pipe-xel 54→65 / pipeB 56→67 / pipeC 47→59；新败签名 revtex4-2+multicol opt clash（9901156/9901347 partial→fail）收 #172——升级器升 revtex4-2 时剥 multicol + epsf/epsfig 兼容审计。该批 8 个 upgrade209 净正（3 死→clean / 3 partial / 2 此对 fail），覆盖率缺口非回归。
- **1e worker expect_cjk `05a2fab`**：`TaskCtx.expect_cjk` 字段携带（`chunk_counts(task_id)["total"] != 0`，与 `450b1ad` 同口径；loop 线程算一次避开 sqlite 线程亲和），五处 judge 点全换。
- **keep-list 链路**：work_e2emock 2.2G + stagerun-loop1/work 44G 挂 fixer-slots preserve-list（在催）；兜底口径已放行 48——名单不到只留报告点名 cell（1206.0197、2410.17957 保底）。

### 路由项落库状态（09-17 凌晨收口，ledger 只记新事实）

| 路由项 | 状态 | 落点 |
| --- | --- | --- |
| PH-in-cs L0 第 10 条（双侧夹持+净差，ERROR→重译非 fixloop） | **已落** | `607704e`+`9f96f8b`；pipeline 副层 spec→peer1 |
| `\t` TS1→TU accent 提升 | **已落** | `ed7b9ac`（tuenc.def 15 项无 `\t` 实证） |
| jpsj3 目标类可解析守卫 | **已落** | `9c381cf`（`_target_resolvable` rglob+kpsewhich fail-open → reject `latex209_no_target`） |
| hyperref 驱动剥除 ×2 | 已裁已转 | peer1 rules.yaml（`\\usepackage[dvips\|pdftex]{hyperref}` 剥 key） |
| aipcheck.tex bundled 覆写 ×2 | **已落** | `1e6ea75`（`JUNK_FILE_STUBS` 挂 normalize_project；maintex 附带：1206.0565 main=aipguide.tex 类指南非论文——E 桶 docs-vs-paper 同族） |
| slots wave-2（#174/#175/#176 `_seg_join`+`_LATIN_ITEM_RX`） | **已落** | `d54eb74` + e2e 镜像 `7817aa1` |
| #169 flake | **定案已修** | `1076086`（双闸 + 确定性回归钉） |
| SLOT_MAX_CHARS / PhValidator（1e xlat-sweep 残余） | **已落** | `558c6c1` |
| no_main_tex 75 格 | 在飞 | 2f 复验 parse 段回收率；探测改动仍 1d |

**镜像漂移二次应验**（教训升级）：`short_arg` 之后 `_seg_join`/`_LATIN_ITEM_RX` 又一次漏镜像——`reconstruct` 译文侧任何字节变换（折叠/保险丝/接缝守卫）必须同查 `e2e._expand_tokens`/`_chunk_spans`，失配=find 失败→spans None→L2 丢块→partial→done 假愈。本波已加 `TestChunkSpansMirror` 回归钉把两类变换锁死。
