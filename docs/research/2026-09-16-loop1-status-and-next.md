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

- partial→fail 17 格**直编复验后真退化仅 4 格**（1003.1717/1306.0036/2410.00012/astro-ph/0111575），13 格是 pre-`6b23435` 引擎基建杀伤——跨段退化判定必须直编复验，不能只看记录面。
- `no_errors_no_pdf` = TeX `(\end occurred…incomplete)` + `No pages of output` 早夭路径无 `!` 行 → 旧 taxonomy 判 clean 无规则承接；已由 `early_eof` 接住。**rerun 实证补齐机理**：13 格同根因——aastex61/62.cls 内部 `\IfFileExists{revtex4-1.cls}{ok}{…\stop}`，revtex4-1 不在 TL → `\stop` 夹条件内 → 早夭；「类文件求档文」语义。对策 `18ff106`（tail plea 规则抓档名归 missing_file + revtex4-1→4-2 桥）验证 **13/13 出 pdf**（11 acceptable + 2 best_effort）。
- unfixable 大头 `missing_file`×113 = legacy 期刊包簇。经 tlpdb 实证拆两型：**索引可解**（pst-node/pst-arrow/epsf/emulateapj.cls/cite/axodraw2/acmart/revtex——pst-* 可解仍败是独立机理疑点，rerun 归类）与 **TL 真缺席**（svjour2/3、jheppub、jinstpub、espcrc1、epl2、imsart、conm-p-l、citesort、diagrams、texsort、setstack、undertilde、default、emulateapj*.sty）——只能 shim 写 stub（真桥：citesort→cite[sort,compress]、axodraw→axodraw2、conm-p-l→acmart；svjour/epl2/imsart 用 aa/iopart 同款 article+polyfill；余 noop 保底）。
- misschar 663 格 acceptable 档语义 = 「有 pdf 即收」——如需更严口径（缺字数阈值）另议。
- skip 129 格全合法上游门（scout 逐链核实）：79 not_translated（parse 失败级联）+ 49 arm_mismatch + 1 gate——**但暴露排程洞**：zh/ 单槽被 real 臂覆写，real-50 抽样 48 id 永无 mock compile 数据；loop2 若做 real↔mock 同 id 对照需先 compile-mock 再 xlat-real（或 zh/ 分臂）。

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

### 4.3 中线

- **真网关规模验证**（1e 建议）：xlat-real n50 出数后推 n100-200 拿真 clean-rate 分布——mock 臂今日连修 4 个缺陷，真臂还没同等扫过。
- **share 生态闭环**（1e）：worker 完成钩自动产包 + index.jsonl 服务形态（§8）。
- **deferred 清单**：v1 退役（倾向不动）、e2e_real→lib 降级、L2 编排环 e2e↔worker 共享化（跨边界需协商落点）、TokenSource Protocol 重构、L2 真 log fixtures。
- **llm_hook 接线**（1e 已裁）：server 路径走任务 BYOK client 复用 `_make_translator`/usage_sink；有真 api_key 默认开；`kind=share` 一律全关（§5 导入零 token 承诺）。

## 5. 分工（本会收敛）

| 方 | 当前在飞 | 下一步 |
| --- | --- | --- |
| 1d leader | fixer-latex 尾项（`_cov_origin` repro + argspec `%`-arg 红） | loop2 stagerun 驱动、台账维护、commit 收敛 |
| 项目体验方式 | rerun 19 格两轮收官（14/19 出 pdf）；taxonomy derive `5d195c2`、shim_map/`\input` scan `622fc04`、plea+revtex4-1 桥 `18ff106` 已落 | loop2 全量复跑判读；候补：pst-* 可解仍败机理 ticket（~~killed_signal 归一~~已核销——run_process 全程 POSIX 负值约定，rc<0→signal 链路本就正确） |
| 1e | worker-hardening 12 项（#52）、llm_hook BYOK 接线 | #74/#78 残件、share 完成钩、真网关 n100-200 |
