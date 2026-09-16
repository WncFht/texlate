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

### regress4 归因（scout-regress4 直编复验 4 真退化格）

**主机理：TEXMFHOME 环境不对称遮蔽（3/4 格）**——stagerun `_compile_judge`（:917 入口编译）跑在 ambient 环境，`~/texmf` 可见；`_fixloop_one`（:1128）冷起 `_texmf` 并经 `XelatexEngine(texmfhome=)` → `engine.py:865-870` 写 TEXMFHOME → `~/texmf` 整树不可见。epsf.tex/revtex4-1.cls/mhchem/chemgreek/algorithm/algpseudocode/ltxgrid 全部只活在 `~/texmf` → 入口编译出 partial pdf、fixloop 里同包全部失踪 → 装错分支/装不上 → 退化。**这不是规则 bug 是 bench harness 包宇宙不一致**——「不退化底板」在产物层兜底，真修法是 texmf 可见性对齐（`_texmf` 串链 ambient `$HOME/texmf`，或入口编译同样吃 texmfhome 走全密封）。路由：engine.py `_env` 侧归 peer1、stagerun 半侧归 1d。

- **1306.0036**：`pdftex_prim_guard` regex 重写了自己注入的行——lookbehind 只防 `\ifdefined` 不防 `\chardef` → `\chardef\ifdefined` 杀 e-TeX primitive → 后续 `\ifdefined` 全灭；splice 原地 mutate 无回滚，run-2 继承残行。**已修 `88d0ab9`**（peer1，lookbehind 扩 `\chardef|\let|\def` + spotcolor→xespotcolor shadow）。残留机制缺口：splice in-place 无树级回滚（底板只兜 pdf 产物不兜树）——大设计项，记档。
- **1003.1717**：`install_file` 装 fallback 分支 revtex4 → `\input aps.rtx` 命中被 xlat 污染的 `splice/aps.rtx.tex:322`（`\let\frontmatter@ 这是译文 }{}`——csname 槽位腐蚀，fixer-slots 机理覆盖；但**随包 runtime 文件该不该进翻译集**是 pipeline 边界问题，转 peer1）。
- **2410.00012**：`install_file` 装 mhchem 没带依赖闭包（chemgreek 被 TEXMFHOME 遮蔽）——依赖闭包安装是 install_file 规则面缺口，归 peer1 rules/engine。
- **astro-ph/0111575**：rerun 已自愈 acceptable（epsf 裸 payload 修复起效）。
