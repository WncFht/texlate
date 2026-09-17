# 全仓现状审查（重构/优化/清理向）——refactor-audit-2026-09-17

> 2026-09-17。四只读子件并行（refactor-src / refactor-debt / refactor-testsdocs / refactor-harness），全部发现带 file:line + 碍点 + 建议形态；leader 抽查验证（F3 e2e_real 零闸扫描、PH_FUZZY_RX 漂移、documentclass lookahead 分叉——均实证属实）。本报告只列**结构性债**，缺陷台账另见各 fuzz report（bench/results/*-fuzz-2026-09-17/）。

## 执行摘要——Top 6 高优先重构面

| 优先级 | 面 | 位置 | 碍点 | 建议形态 |
|--------|----|------|------|----------|
| ★1 | **e2e↔worker 双编排器漂移** | e2e.py vs server/worker.py | 私有名跨模块 import ×12（worker.py:73-86）；`_log_text_of` 已实证漂移（e2e.py:379 空 log 返""，worker.py:2740 有 stdout_tail 兜底——worker-share-fix 只落了 server 臂）；`_LastResEngine`≡`_RecEngine` 同型 proxy；`_slim_cell`/`_fixloop_summary` 同变换异构输出；cross-engine flag-drop 重试双写互注 | 抽 `texlate/repair.py`（log_text_of/ResProxy/cell→summary/fixloop_wrap 单源），两臂变瘦编排 |
| ★2 | **红线语义四源** | engine.py:183 WARNING_RED_LINES / rules.yaml:142 `warnings:` / judge.py:96 `_MISSCHAR_*_RX` / l2.py:144 `_REDLINE_CLASSES` | 同概念三套拼写（missing_chars/missing_char/missing_glyph），同步纯靠注释（"同口径"×3），名已分叉——nullfont 裁决刚付过一次同步成本 | 单一 registry：rules.yaml warnings: 扩成全源（canonical id + 各层别名表）或新建 compile/redlines.py |
| ★3 | **bench 侧三代 runner 各自 fork 扫描/翻译/records** | stagerun.py:649-668 vs e2e_real_bench.py:191-202 | e2e_real `translate_tree` **零文件闸**（.rtx.tex/.code.tex/file_has_prose 全漏）——不是漂移是**在产测量腐蚀**：real 臂送译 REVTeX dump/support 件；stagerun 重实现且 `rglob("*.tex")` 大小写敏感漏 .TEX | 全收敛到 `e2e._scan_tree` 包装（e2e_mock 已是正例） |
| ★4 | **records/jsonl 读层 ~6 实现 + 状态词表 4 处声明** | benchlib（正源）vs triage._read_jsonl:79 / gate_scorecard.last_records:31（裸 id 末行胜，与 (id,arm,upstream) resume 键静默分歧）/ e2e_real._dedup_cases:598 / stagerun.load_latest:201 | 「append账/末行胜/tolerate-truncated-tail」契约逐消费方重推；triage SKIP_STATUS 认 legacy 词而 gate_scorecard 不认→同 records 不同分类 | benchlib 加 `iter_jsonl(on_bad)` + `latest_by(keyfn)` + 状态词表 + `fixloop_sig()`（sig 合成 3 处）+ `run_meta()` union schema |
| ★5 | **segmenter.py 5163 行 god-class** | latex/segmenter.py:497 | ~4600 行 ~120 方法 ~25 实例 attr；多代理会战下合冲突保证命中 | 按既有 banner 拆 `latex/segmenter/` 包（core/group/pending/dispatch/args），状态仍单一 Segmenter（mixin 或 helper 注入） |
| ★6 | **stagerun.py 1580 行 5 阶段巨块 + 反向依赖 peer runner** | stagerun.py:1-1580 / :84 import e2e_real_bench | kernel+run_meta+5 stage driver+内联翻译引擎+argparse 全塞一文件；stagerun 依赖 e2e_real 的 pick_sample/_code_stamp(私有)/preflight/load_manifest/MAX_TOTAL_CHARS——erb 不能退休；且丢 e2e_real 的 auth 断路器（AuthTrippedError 被 per-paper `except Exception` 吞，死 key 烧全批 auth_fail_threshold） | stagerun 拆包（kernel+per-stage+薄 CLI）；erb 五件通用件下沉 benchlib；auth 断路器回补 stage_xlat |

## A. src/texlate 模块边界（refactor-src，12 项）

| sev | 位置 | 发现→建议 |
|-----|------|-----------|
| hi | segmenter.py:497 | 见 ★5——机制族已 banner 分位，拆分纯机械 |
| hi | e2e.py↔worker.py | 见 ★1 |
| hi | 红线四源 | 见 ★2 |
| med | worker.py:1136 | PipelineWorker ~2830 行/~60 方法：banner 可切 events/fetch/parse/translate/share(~560,散落 2146-3412)/compile+fixloop(~930)/pdf——`server/worker/` 包按 stage 拆；unpack_zip/sniff_upload（921-1100）与类无关→server/upload.py |
| med | compile/engine.py | 1849 行 4 关注点：log 模型+parse_log+redlines（106-305）/taxonomy 适配/bwrap 沙箱机械（574-887 与 sandbox.py 同层分居两文件）/Engine+router——`compile/loginfo.py` + `_bwrap_*`→sandbox.py |
| med | fixloop/engine.py | 1513 行 5 关注点：ruleset.py(load/validate/Rule/Ruleset) + deps.py(install 闭包+filemap) + engine.py 留 LoopCtx+dispatch+loop |
| med | fixloop/builtins.py | 2401 行 24 TRANSFORM_FNS：按域拆 builtins/ 包（fonts/graphics/packages/support），共享 helper→_common.py |
| med | TeX 扫描正则重复且 lookahead 分叉 | `\\(documentclass\|documentstyle)` 5 站两版 lookahead：`(?![a-zA-Z])`×4（api.py:29/segmenter.py:5108/inject.py:271/fixloop engine.py:55）vs `(?![a-zA-Z@])`（arxiv/locate.py:37——@ 在 cls 文件是合法控制符名符，**已分叉**）；`\\begin{document}` 有正源 textutil.BEGIN_DOC_RX 仍两处重复编译；`\input` 族正则 inject.py:278-280≡probe.py:49-51,56，_resolve_input≈_find_local 近似双写 | 常量集单源（DOCCLASS_RX 一次裁决 @，复用 BEGIN_DOC_RX，INPUT_* 三件套）+ 共享 _resolve_input_name |
| lo-med | rules.yaml 4445 行 | meta/capabilities/filemap/warnings/taxonomy(~500)+62 平铺 rules(~3900)；order 键显式（文件位置非语义）→拆分零风险；taxonomy 被 Ruleset.load 与 engine._taxonomy lru_cache 双解析——taxonomy.yaml 独立是自然缝；rules.d/{gate,precheck,loop}.yaml 待 ~100 条再议 |
| lo | app.py:415 | create_app ~1120 行工厂 ~20 路由闭包捕获——「端点面即规格表」是有意平直设计，增长时再上 deps dataclass+APIRouter 分域 |
| lo | textutil.py | 两半无关（LaTeX splice-guard L70-438 vs 编码探测 L439-1000），18 importer——纯外观拆分 |
| lo | cli.py 1526 行 | share 子 app(~345)/doctor 块(~270)自足——下次触碰时切 cli_share/cli_doctor |

**死代码**：验证干净——所有候选均为活口（typer 装饰器/Protocol TokenSource/`__all__` Patch/babeldoc helper）；v2 文件内无 v1 死径。**边界健康度**：leaf utils（textutil/texlog/mask）单源良好，既往 dedupe 全守住；真实结构债就两处——e2e↔worker 双编排 + 红线四源。latex/ 是重量轴（segmenter 5163+gullet 2794+scanner v1 1698≈全仓 48.8k 中 9.7k）；gullet 复杂但内聚（宏展开器本质多分支），segmenter 是最需拆的文件。

## B. 落地未清账机械（refactor-debt，12 项）

| sev | 位置 | 发现→建议 |
|-----|------|-----------|
| med | scanner.py(1698ln)+api.py:46-95 | **v1 臂逃逸价值部分失效**：scanner.py:30 模块级 `from .gullet import export_flat_macros`——gullet 导入失败 v1 同死，`TEXLATE_NO_EXPAND` 只挡运行时分叉；但 v1 仍是**唯一独立再实现**（parsebench S5 对拍门 parsebench.py:457 用 parse_file_v1 当 oracle）。成本实付：~2060 行+ScanState 臂分裂字段（model.py:215-222 ifflags/steps v1-only vs pkgs v2-only）+9 文件 delenv boilerplate+v1-only 审计修复在持续落地。**裁决建议**：明定保留判据=对拍 oracle 仍产出 actionable diff；无论存废，`TEXLATE_NO_EXPAND` 退出产品 dispatch（bench 显式调 `*_v1` 不破） |
| lo | flatten.py:55-334 | `flatten_inputs` 名义 v1 臂实为 parsebench `flatten_reach`（:162-186）的 \input 可达图 oracle——**不可当 v1 代码批删**；v1 退则迁 bench/（产品侧保留成本也低） |
| lo | api.py:29-30/segmenter.py:5108-5109/flatten.py:35 | `_PREAMBLE_RX`/`_DOC_BEGIN_RX` 三份逐字拷贝——正是已产 PH_FUZZY_RX 漂移的模式；单源化 |
| med | placeholders.py:51-106 | **sentinel 四相是开放回归**（实证：源含字面 `[[__TEXLATE_SL_LIT2__]]` 解码成 `[[__TEXLATE_SL_LIT__]]` 有损——定深链每层是上一层的补丁，新增 bare token 需 4 常量，现 32 常量×8 族；SL/PL 两腿硬编码在 _SPACE_FAM 表外因 literal 是换行游程）。建议二选一：(a) 程序化闭链 `while literal in text` 无限深度同 wire format；(b) 整体坍缩——对不匹配 token 形的源字面量转义 `[[` 引导符（一条规则退全部逐 token 链）。**勿加第五层** |
| med | placeholders.py:43-48 vs l0.py:80-85 | **PH_FUZZY_RX 已实证漂移**：l0 版带 `(?=[^\[\]\n]{0,47}[A-Za-z])` lookahead（排 `【1】`/`[[图]]` 自然 CJK 括号 FP），placeholders 版没有；placeholders.py:9「与 L0 同口径」已不真。`_ph_in_comments`（placeholders.py:237 mask-diff Counter vs l0.py:444 _lex tokenizer 双机制）+ `diff()`vs`_check_placeholder` ~80% 平行实现——**修复臂现在会标 L0 永不标的 fuzzy 候选**。单源 PH_FUZZY_RX+comment-zone counter 到共享低层（latex/placeholder.py 或 textutil——validate 不能 import xlat） |
| lo-med | xlat/__init__.py | 137 行 60-name `__all__` 死 facade：零消费者用平名 import，且 `import texlate.xlat.placeholders` 经包 init 拉 httpx——纯正则消费者白付 HTTP 栈导入。掏成 docstring-only 或 `__getattr__` 惰 facade |
| lo | worker.py:2762-2767/e2e.py:103-108/engine.py:569 | `{"1","true","yes","on"}` env-flag 解析三份；worker.py:2762 手搓但同文件 :79 已 import `_env_flag`；私有名被 cli.py:48/worker.py:79 跨模块 import。textutil.py 提 `env_flag(name, default)` 公共件 |
| lo | settings.py:98 | `tenant` 作为 `per_key` legacy 别名——若未发货即一词删除 |
| lo | state.py:35 | `STATE_VERSION="1.0"` 写入每个 state.json 但 load() 从不检查——装饰字段：要么 enforce 要么删 |
| info | store.py:125-147 | `_COLUMN_MIGRATIONS`+`_POST_DDL` 顺序依赖是合法前向迁移机械——保留 |
| info | pipeline.py:580-595 | poisoned-cache 驱逐（`_interceptable`）是 pre-intercept-net 缓存兼容——自愈近零成本，永久保留 |
| info | TODO/FIXME 台账 | src/ **零真 marker**——债记 docstring：state.py:357 save_cache O(n²)（v0 保正确性，per-paper 规模下可留）、api.py:58 W11 受认可未修。台账干净 |

## C. tests/ + docs 漂移（refactor-testsdocs）

### C1 覆盖空洞（pytest-cov 实证：3595 pass/4 skip/73 xfail）

| 模块 | 覆盖 | 洞 |
|------|------|-----|
| latex/scanner.py | **47.5%** | 最大单洞——v1 臂 `_split_core`(:312-347 CHUNK_MAX 分裂）+`_dispatch_cmd` env 分支（:765+）零执行；全部 test_latex_* helper 默认 v2。**v1 回退臂回归可绿着出货**——需 `v1_scan` fixture+定向测试（与 B 节 v1 裁决联动） |
| latex/api.py | 74.6% | v1 入口函数体 |
| validate/report.py | 76.3% | feedback/hard_failures 渲染分支（:77-94） |
| latex/macro_table.py | 78.0% | 数据驱动表项未触发 |
| fixloop/builtins.py | 79.0% | 67 规则函数多在 pytest 外（bench-only）——**parametrize 遍历 load_ruleset() 逐规则喂合成 log，便宜且灭整类** |
| validate/l1.py | 81.8% | worker 子进程错误路径（非零 exit/JSON 坏/计数不符 :245-265） |
| gullet.py 82.3% / segmenter.py 82.7% | — | 缺尾全是 error/resync 路径（`verb_resync_failed` emission gullet.py:979/992/997 无直测） |

### C2 xfail 台账健康

78 xfail decorator **全 strict=True 零非 strict**，全带 file:line 理由；最近干净跑 73 xfailed/0 xpass——strict 自执行（修复即 XPASS 红）。两处 probe.py 钉行号漂移 ±35（缺陷仍真）——建议钉格式 `file:symbol` 而非 `file:line`。

### C3 docs 实证漂移（doc:line ↔ code:line）

- docs/06:108 `\bibliography{x}`→`\jobname.bbl` ↔ locate.py:253-272 `_resolve_bib` 另探 arg-stem `x.bbl`/`x.bib`（superset，真 TeX 不读）——doc 缺双探注记（#189 已裁决 probe 范围）。
- docs/07:96-100「impl 共 13 种 ScanWarning」↔ 实发 **20** 种——未记 7：`dangling_chunk_ref/dangling_ph/dead_ph/keyarg_unbound/orphan_chunk/pieces_gap/verb_resync_failed`。warning-kind 消费者无法分辨哪些 kind 是契约。
- docs/07:144 钉 `_dispatch_cmd` scanner.py:745↔实 :765；:359+:423 钉 `\ifmmode` gullet.py:2387-2390↔实 :2447-2449——陈旧钉×3。
- docs/09:29/:123「入库 72」↔ manifest_hot.jsonl **133** 行（day-1 快照数，层在续填；MANIFEST.md:7 的 5133 已对）；:121「台账 143」↔ mechanisms.jsonl **144**。
- docs/10:48「54 用例」↔ test_bench_regression 现收 **98**；:79「×25 规则库」↔ rules.yaml **67** 条。
- **CLAUDE.md 头「yaml 修复引擎 36 规则」↔ 67**——全仓爆炸半径最大的陈旧计数（每个 agent 先读它）。
- 抽查为真的钉（不报漂移）：ratelimit 常量/fetch UA+RETRY_DELAYS+150MB、unpack caps、PaperMeta、share KEY_PART_FIELDS、align 权重、tables 常量、`_EXPAND_KINDS`、30 簇表、docs/06:107 locate 基序。

### C4 flake 面 + 重复

干净——前波 hygiene 守住。余：test_bench_regression:153-165 SIGALRM POSIX-only（Windows 目标出现时加 skipif）；本会话两起在飞件 collection 杀手（normalize em-dash、logpipe 未终结串——均已即时修；**建议 fuzz 交付协议加 `pytest --collect-only` 前置**）。

重复（conftest 候选）：`DOC = "\\documentclass{article}..."` 逐字同文 ~13 文件+各带本地 scan/parse wrapper（~12-15 份）；tar-builder boilerplate ~5 文件（conftest 已有 make_targz）；ChunkIn-builder `_mk` 4 文件；server task-dict `_mk` 5 文件。

## D. bench harness + 工具链（refactor-harness，14 项）

| # | 位置 | 发现→建议 |
|---|------|-----------|
| F1 | stagerun.py:1-1580 | 见 ★6——kernel/stage/translate/CLI 四层混；stage_* 签名已同形 `(args,out_dir,ids,log,upstream_recs)`，拆包纯机械 |
| F2 | stagerun.py:84 | 依赖 peer-runner e2e_real 五件（pick_sample:140/_code_stamp 私有:168/preflight:1540/load_manifest:1532/MAX_TOTAL_CHARS:796）——下沉 benchlib |
| F3 | stagerun._translate_tree:649 vs e2e_real.translate_tree:191 | 见 ★3——**e2e_real 零闸是活测量腐蚀** |
| F4 | ~6 份 records/jsonl 读实现 | 见 ★4 |
| F5 | 状态词表 4 处声明 | stagerun DONE/RETRIABLE(:120-121)、triage OK/SKIP/RESCUED/STATUS_RANK(:40-65)、gate_scorecard COMPILED(:28)、e2e_real._paper_done(:517-530) 内联——benchlib 单源 |
| F6 | sig 合成 3 份 | make_sig:210 + fixloop sig merge 逐字双写（stagerun._fixloop_one:1324-1330 ∧ triage.legacy_records:419-423）——`benchlib.fixloop_sig(cell)` |
| F7 | run_meta schema 分叉 | stagerun {created_at,started_at,invocations,finished_at,git_rev} vs e2e_real {seed,code,layers,...,ended_at,end_reason}；triage._wall_s:499 已付兼容成本（三键或）；另 stagerun 对同名文件用非原子 write_text | `benchlib.run_meta()` union schema+单写径 |
| F8 | atomic-write 双实现 | benchlib.atomic_write_text:88（固定 .tmp 名同径并发碰撞）vs e2e_real._atomic_write:573（mkstemp 随机后缀严格更优）——留 mkstemp 版 |
| F9 | preflight 双实现 | e2e_real.preflight:118-157 vs preflight_batch.check_imports/check_mock_chain:49-109 近逐字（docstring 自认同构）——benchlib 单实现，preflight_batch 只包资源检查 |
| F10 | fixloop recipe 接线 ~50 行×3 | texmf cold usertree→_init_usertree→_NoSandbox(XelatexEngine)→filemap→fixloop(runner)→post-judge 在 fixloop_bench.run_paper:295-348/e2e_real.pipe_fix_condition:394-438/stagerun._fixloop_one:1244-1297 三写+harness_crash fallback dict 三写——`flb.fixloop_cell(...)` 收口 |
| F11 | stagerun 丢 auth 断路器 | e2e_real AuthTrippedError→停批(:1006-1016)+_AUTH_DEAD_STREAK(:1048-1055)；stagerun._xlat_one:772 `except Exception→crash_rec` 逐篇吞 AuthTrippedError——死 key 烧全批；另 `_on_misschar`:1335-1342 自称「与 _want_fix 同口径」实分歧（_want_fix 收 partial∧(missing_chars>0∨n_errors>0)，stagerun 只收前者——error 级 partial 恰是 fixloop 最佳救场目标被排除） | 回补断路器+修口径或修声称 |
| F12 | 年代仪器滞留 | fixloop_bench.py:81/compilebench_v2.py:52 硬编 `ROOT=~/src/texlate`（别家都用 `Path(__file__).parents[2]`）；compilebench_v2:69 TECTONIC macOS 路径本机死；fixloop_bench **正被当库 import**（stagerun:85/e2e_real:71）其破 ROOT 休眠中但异地运行静默指错树；gate_scorecard:24 钉死 stagerun-loop1-2026-09-16+烘 upstream="mock"——处置：fixloop_bench ROOT 走 __file__；compilebench_v2（v3 已代）标历史仪器；gate_scorecard 并入 triage `gate` 子命令（triage 键/词表已正确）或至少参数化 --dir/--upstream |
| F13 | bench→tests 反向 import | fixture_assert.py:24-27 sys.path.insert tests/ import test_bench_regression 当断言库——共享断言函数应进 bench/py 模块由测试 import（反转边） |
| F14 | CI/pre-commit 微漂移 | (a) autocorrect 在本地 md 链但 CI lint:md 只 markdownlint——CJK 空格改写 CI 不可验（过 CI 后被本地重写）；(b) ci.yml:91-95 内联重实现 fmt-shell.sh 的 zsh-skip 判定；(c) release.yml action 版本旧（checkout@v4/setup-uv@v5 vs ci.yml v7/v10）；(d) rules-yaml-load pre-commit 闸无专属 CI 步但经 pytest 间接覆盖 |

**harness 分层健康度**：benchlib 是真共享层（13 importer）+两个好复用范（expand→b3 批发 import、e2e_mock 委托 e2e._scan_tree），但**层偏小**——records schema 词表/sig 合成/run_meta/扫描闸管线住在最大 runner 或 peer runner（私有函数当库）。每代 runner（e2e_mock→e2e_real→stagerun）fork 前代而不抽层。修复序：(1) records-schema+jsonl+sig+状态词表→benchlib（F4-F8 机械，解锁 triage/scorecard 收敛）；(2) erb 五件下沉（F2）；(3) 全扫描收敛 e2e._scan_tree（F3 修活在产的测量 bug）；(4) stagerun 按 stage 拆（F1）；(5) gate_scorecard 并 triage、年代仪器标记（F12）。scripts/ 与 bench/ts 健康；语料管线复用是可抄范式。

## 附：执行记录

- 子件全只读零 git 零 src 写；scratch 各自 tmp/refactor-*/（gitignored）；testsdocs 附 cov.json 证据。
- leader 抽查 3 项（e2e_real 零闸、PH_FUZZY_RX 漂移、documentclass lookahead 分叉）逐字核实属实。
- 会话插曲：两份在飞 fuzz 件 collection 杀手（normalize em-dash L145/logpipe 未终结串 L113）由 leader 直修——fuzz 协议应补 `pytest --collect-only` 交付前自检。
