# bench 工作区最终方案：**thin-runner + 薄门面**(kernel 收敛样板 + 契约钉死承重面 + exec 单入口）

> **已取代（2026-09-23 Wave-F）**：本方案（v1 thin-runner 路线）未实施即被 trizone-ledger v2 全量重写取代——实际落地见 `spec/bench-trizone.md` 与 `bench/py/kernel/`；保留作方案评审史记录，其中 stagerun/records/results 面均已是历史。
>
> 骨架 = 排名第一 thin-runner（零存储/schema 移动、函数式 run_bench 内核、additive benchlib helpers);嫁接 = 亚军 bench-cli-facade 的单入口薄门面（修正为 exec-only + 更名 bench_cli.py);全部 fatal/major 攻击逐条处置（无 fatal 成立，major 共 19 条，对策内嵌于步骤与风险节）。已逐条实证关键行号。

---

## 1. 目标布局

```
bench/
├── results/{tool}-{tag}-{YYYY-MM-DD}/      # 唯一命名公式,UTC 单源,+隔日分叉警告
│   ├── records/{stage}.jsonl               # dag 专用:append-only 10键行(+auth_tripped 可选)
│   ├── cases.jsonl / run_meta.json / work/{id}/ / .gitignore   # dag 五件套原样
│   ├── {cases,pairs,rows,files,results}.jsonl + cells.json + summary.md   # eval 三件套原样异构
│   └── records.jsonl + results.json + matrix.md   # e2e 扁形双写原样(不收编)
├── corpus/ corpus_daily/ zh-store/ fixtures/ frame/  # 零触碰
└── py/                                      # 扁平不动(pythonpath=['bench/py'] 钉死)
    ├── benchlib.py          # 原语层 +additive helpers(每条落地必须同 commit 接 ≥1 真实调用方)
    ├── benchrun.py          # 【新 ~320行】纯 stdlib 函数式内核:BenchSpec + run_bench + Ledger
    ├── bench_cli.py         # 【新 ~150行】薄门面:COMMANDS 数据表 + exec-only 转发 + list/runs
    ├── stagerun.py          # 5臂 if/elif(:267-294)→STAGE_DISPATCH 表;STAGES tuple re-export 不动
    ├── stagerun_lib.py      # +select_todo 前导(gate_fn 自写 gate 记录);run_meta 走原子纯写
    ├── stage_{ingest,parse,xlat,compile,fixloop}.py   # 内部接 select_todo;xlat async 不动
    ├── <12 个平铺 bench>     # 文件名/main() 不动,惰性接 helpers;gullet 是内核第一采用者
    ├── e2e_{mock,real}_bench.py  # 最小触碰:seed_run_records 接线 + meta 原子写;四层守卫原样
    ├── corpus/              # 不动;eprint_to_layer 仅在下个新层立项时落(惰性)
    └── report/              # −6 实证死件;l2_attr_probe 保留并修 RESULTS_JSON 指向 archive
scripts/bench                # 【新 3行】exec uv run --project "$ROOT" python "$ROOT/bench/py/bench_cli.py" "$@"
tests/
├── test_layout_contract.py  # 【新 ~300行】承重面机器钉(见 §6 契约清单)
└── test_bench_cli.py        # 【新 ~120行】名册双向完整性 + exec 转发断言
```

---

## 2. 新运行方式

```bash
# 跑法一行不变(在跑管线零改动)
uv run python bench/py/stagerun.py xlat --arm real --layers core --n 500
uv run python bench/py/compilebench_v3.py --corpus bench/corpus --engines xelatex,tectonic
scripts/daily-soak.sh / scripts/errsweep.sh        # 照旧,方案全程不碰其调用面

# 新增可选单入口(纯便利,直跑路径永远是一等公民)
scripts/bench list          # 全部仪器一行说明(含 corpus builders + report 工具,三代同册)
scripts/bench runs [--json] # 按 COMMANDS 声明的 outputs 表列 run(不做签名推断)
scripts/bench parsebench --layers core --n 200      # exec 转发,argv 原样透传,--help 也透传
```

**新 bench 上线 (~80 行，对比今天 ~300 行样板）**:

```python
# bench/py/mybench.py —— 无基类无注册表，SPEC 只是 callable dataclass
SPEC = BenchSpec(
    name="mybench",
    ledger="cases.jsonl",
    iter_units=lambda args, out: plan(...),  # 收 out_dir(实证 compilebench 需要)
    key_fn=lambda r: (r["paper_id"], r["arm"]),  # 必传，无默认——内部绝不 canon
    done_pred=lambda r: True,  # 必传，显式声明终态政策
    eval_one=lambda u, ctx: [rec],  # 返回行列表 (支持逐单元多行)
    summarize=lambda rows, out, args: ...,
    on_crash="print",  # 显式:'print'=今语义 (崩溃格留待重跑)
)


def main():
    run_bench(SPEC)


# bench_cli.COMMANDS 加一行 ('mybench.py', '一句话') —— 删除=删文件 + 删行，无牵连
```

---

## 3. 存储布局（磁盘）

**零字节搬迁、零改名、零 schema 变更**——这是「最终保存简单」的答案：物理模型本就接近最优，要修的是写侧约定。

- `records/{stage}.jsonl`:append-only、行=10 键 `{id,stage,arm,upstream,code,status,dur_s,metrics,errors,sig}`(+`auth_tripped` 可选；实证 base_rec stagerun_lib.py:189、stage_xlat.py:368)。**契约钉的是必填子集不是精确 9 字段**(attack 证实 "9 字段" 是旧传说）。文件名=stage 的 glob 契约（triage.load_records:88-91）由契约测试钉白名单——**sidecar 账永不入 records/**(quality-metrics.jsonl 先例）。
- `run_meta.json`:additive 增量 `{kind:'dag'|'eval'|'e2e', tool, outputs:{ledger,aggregate,report}}`;`invocations[]` append-history 子 schema 逐字节冻结（gate_scorecard window_suspects:399-415 解析 argv/ts)。写径改原子写（mode 0o644 跟 umask——非 0o600，多 uid 读方在）；读径对 460 个 archive 旧目录永远保 glob 兜底。
- `corpus/{id}/{meta.json,raw.*,extracted/}` + `manifest_{layer}.jsonl` 文件名=层身份、`work/{id}/{src,zh,splice,build-base,_texmf}` 树、zh-store 三区、corpus_daily 独立根、fixtures byte-exact、archive-2026-09-20 全部 460 目录——一律不动。
- eval 侧三件套文件名异构（cases/pairs/rows/files.jsonl、cells/results/papers.json、summary/report/matrix.md)**保留为特性**——`bench runs` 靠 COMMANDS 声明的 outputs 表分类，不发明签名谓词（实证 archive 里 66/460 才有 run_meta、5/8 e2e 目录无 records.jsonl，签名推断必然误分类）。

---

## 4. 迁移步骤（每步独立可落、独立可绿）

**步骤 0|契约先行（独立 commit，纯新增）**：落 `tests/test_layout_contract.py`——钉 ①records 行必填键子集（10 键 + 可选键清单，非"9 字段")②records/ 文件名白名单 {ingest,parse,xlat,compile,fixloop}.jsonl ③run-dir 三形签名 ④corpus cell 形态+manifest 文件名=层 ⑤work/{id} 子树名（按格可选——harvest 后掏空是常态）⑥zh-store zones ⑦fixtures 关键字节锚（xlat-traps @X1–@X4、tricky T01–T29，非仅存在性）⑧metrics.jsonl 在 results 根、quality-metrics 不在 records/ ⑨写侧 canon/审计 raw 双轨键 ⑩run_meta invocations append-only+finished_at 单调。**负例断言必含：decoy-run(smoke/verify 目录不得被 latest_run 误选）、append-history（两次 touch 后 invocations 追加非覆盖）、双拼写键（math--X 与 math/X 不得并键）**。数据面被 gitignore 的部分用 writer-schema 断言（base_rec 产出行键集）+tmp_path 合成树+skipif 兜底。顺带决断 corpus 测试黑洞：conftest 加 bench/py/corpus sys.path 激活两条 importorskip（推荐）或契约断言其不可 import——不留不确定态。

**步骤 1|死面清理 + 两个实证真 bug（最高 ROI,-~4400 LOC)**:

- 删 report/ **6** 个实证死件（v2_diff/texsoup_diverge/bench_pylatexenc/plastex_bench/texsoup_bench/ieeA_bench);**l2_attr_probe 保留**——docs/dev/archive/2026-09-20-benches.md:50 标 active 且目标在 archive，只把 RESULTS_JSON 重指 archive-2026-09-20(1 行）;export_realbook 存疑则留原位打 dormant 注。删 tests/_benchkit.py(0 importer)。同 commit 同步 docs/dev/archive/2026-09-20-benches.md/tools-runbook.md 普查行。
- 修 compilebench_v3:**传缺引擎子集 + engines 合并而非覆盖**——`papers_agg[pid].setdefault("engines",{}).update(paper["engines"])`(:876 整条覆盖会把旧引擎从 cells.json 抹掉，fixloop_bench 经 BASE_CELLS:411 读 engines{} 会静默失基线）;cells.json 逐 future 重写（:882）换 atomic_write_text（真竞态）;fixloop 的 cases 读者加 (pid,engine) 去重（重复行会向下游传播）。回归测试：--engines xelatex 后续跑 --engines xelatex,tectonic→cases 无重复行且 cells 双引擎俱全。
- 修 xlatbench cmd_report 聚合前末条胜去重（消重试行双计）。
- benchlib 删 cond_status/RETRIABLE_STATUS;quantile 只接**实证 ceil-rank 三站**(alignbench._pct_vals.q:679、validbench._pct.q:784、parsebench.percentile:172+CI 点）——xlatbench._med/_p95(median 插值/floor+clamp :501-509)、gullet pct(floor-index :199)、alignbench:264(round-over-(n-1))**就地保留**(benchlib:822 docstring 明写勿互套；换接=n=偶数时 p50 静默漂移）。

**步骤 2|benchlib helpers 批 A（每条同 commit 接线 ≥1 调用方）**:

- `init_run_dir(name, tag, out, date, kind)`：收**完整计算后名**（validbench:1037 名含 corpus.name;e2e 用 `f"{tag}-{date}"` 异式被 docstring 明禁误用）;UTC 日期单源（杀 compilebench:823 local strftime 分叉——本机 UTC+8，每日 00:00-08:00 两钟已分叉）;**内嵌 \_warn_date_fork 同级目探测**(e2e_real:498-524 移植——隔日原样重跑新建空目全量重跑烧 swe-2 配额是代价最高的 footgun，一处接入全 adopt 者免疫）;`has_work` 参数控 .gitignore(wrapfloat:353 把 work/ 写进 run 目，eval 形也需此件）。首个调用方=stagerun.py:228-237 引导段。
- `dump_run_meta(path, meta_dict)`:**纯原子写原语**——load→mutate→append 语义所有者仍是 touch_run_meta/mark_run_finished(stagerun_lib:274-308 两站同 commit 换掉；invocations 历史坍缩=波次窗信号死）。mode 0o644。
- `done_keys(path, key_fn, pred, gen_key, gen)`:**key_fn/pred 均必传无默认**——五驱动终态口径实证全异（compilebench 行在=done 且 stub 行无 status 字段、alignbench 错误行算 done、xlatbench 要 http==200+content、qualbench 要 score≠None、stagerun DONE_STATUS 含 fail——双向都不可统一）;docstring 写死禁建 latest_records(canon）之上。首个调用方 compilebench:847。
- `compact_jsonl(path, rows)`：原子压实；**对 records/ 与 cases.jsonl 等 append 账硬 raise**；返回 {kept,dropped} 计数（iter_jsonl 静默跳坏行不得被压实洗成数据丢失）。首个调用方 parsebench:1241（消 'w'-truncate 丢全行窗；同批收 alignbench:948、xlatbench:468 rejudge——后者是两方案清扫名单的漏项）。gullet:155-160 已是原子正确示范，不动。validbench:1072 单独处置：非空 cases.jsonl 存在时拒绝 'w' 截断除非 --force（杀窗类同但政策不同）。
- `emit_json/emit_summary`+`md_table`：原子快照与 md 表单源；首个调用方 fixture_assert。**原子化只落在承重处**(run_meta、cells.json 赛中重写、压实点）——普通 summary.md 的 torn write 低 stakes 不扫荡。
- `find_runs/latest_run`:**全参数化**(glob 前缀、签名形态、排序键）——实证四家选择政策全异：gate_scorecard 要 records/+run_meta 按 max（文件）mtime、wave 要 records/ 目+loop 优先 + 目录 mtime、status_panel 要扁 records.jsonl+realn200-_/e2e-_ 前缀+meta mtime、dossier 逐 pid 全列。首个调用方只接 gate_scorecard._default_records_dir(M2 门最高值）+picked-dir golden test;wave/status_panel 暂保 bespoke。

**步骤 3|bench_cli.py 薄门面（纯加法）**:COMMANDS 手工名册 `name→(script_rel_path, one-liner)`,**exec-only 分发** `execv(uv run --project $ROOT python script *argv)`——import 模式会弄瞎两处 pgrep 活性闸（实证 wave.py:201 `pgrep -f 'stagerun.py.*{dir}'` 单写者闸、status_panel.py:664 n200 runner 发现；import 模式 cmdline 无脚本名子串→双写者开在在飞 run 目上）,exec 顺带消灭 sys.argv 杂耍/懒 import 全部复杂度，且 corpus//report/ 不在 pythonpath 本就只能 exec(build_corpus_* importorskip 实证静默 skip)。`bench runs` 用 COMMANDS 声明的 outputs 表分类不用签名推断。**test_bench_cli 双向钉**：名册每条可解析 + 每个可执行 _.py 必在名册或 UNLISTED frozenset(benchlib/stagerun_lib/stage__/translators_bench/quality_proxies/benchrun 显式排除——translators_bench 无 main() 是 xlat 臂工厂库）。文件命名 bench_cli.py 不命名 bench.py(`import bench` 与仓根 bench/ 目录 PEP420 撞名）。shim 用 `uv run --project "$ROOT"` 与 CWD 解耦。

**步骤 4|benchrun.py 内核 + 第一采用者 gullet（不是 compilebench)**:BenchSpec 字段 `{name, ledger, iter_units(args,out_dir)->units, key_fn, done_pred(必传), eval_one(u,ctx)->list[dict], summarize, on_crash='print'|'row'(默认 print 保今语义), extra_args, jobs_default, upstream}`。Ledger 拥 done 扫描+append/compact 双模式 + 路径自检拒 records/。内核收编：共享旗标 parser(--out/--tag/--date/--seed/--jobs/--only/--limit/--rerun——语义差异经 spec 参数表达，**绝不静默统一 --corpus 三义/--only substr-vs-CSV/--resume opt-in 反转**，异构写进 flag-quirks 文档表）、init_run_dir、executor(as_completed+ 进度+time_budget)、append flush、原子聚合。**第一采用者 gullet_bench**（单模式、行/单元、241 行，实证最贴合）;validbench/wrapfloat 随后；compilebench 待内核有 ≥2 个无聊用户后再迁（它有 --gen-sample/--report 旁路 + 逐单元多行 + 赛中快照，旁路留 main 前半 bespoke)。**现实采用面 4-5 家**，不承诺全 flat 覆盖——xlatbench/qualbench 子命令 CLI 与 asyncio gather 不适单发 ThreadPool，留 bespoke 是正确终态；半采用被接受、helper 死沉不被接受。

**步骤 5|stagerun internals（选 soak 批间隙落，pgrep 门禁）**:stagerun.py 5 臂 if/elif→**STAGE_DISPATCH** 表（不撞名 :97 STAGES tuple re-export;report/dossier.py:58 第二份硬编 stage 表同 commit 改指 stagerun_lib.STAGES);compile 臂 --post l2 note 做成表内可选 pre-hook。stagerun_lib.`select_todo(ids, log, gate_fn)` 只收编实证同型骨架（dedup_wids→is_done/rerun 过滤→todo→print,~8 行）;**gate_fn 持有 log 自写 gate 记录**(stage_parse:155-163 no_src、stage_xlat:545 upstream_gate、stage_ingest:107 _missing_rec 的 cat/payload 形状是 triage 归桶+errsweep 聚类输入，helper 代写=records 语义变更）;stage_xlat async 显式排除。stage_parse 单点先落看 diff 再推。**落地门前机械检查：pgrep -f 'stagerun.py|daily_arxiv.py' 为空才动 stage_***(soak.sh 顺序 spawn 五个 stage 子进程，半途换码会同批前后不一）。**

**步骤 6|惰性收编（改到谁接谁，无 flag-day)**:alignbench Ledger compact、parsebench emit/原子、qualbench done_keys+md、xlatbench done_keys+ 末条胜、e2e 双件最小触碰（seed_run_records 接线 e2e_mock:750-760+e2e_real:687-701 带 on_bad_seed——参数本就为它的 WARNING 形状设计；四层守卫 + 扁 schema 双写+`{tag}-{date}` 命名原样，_warn_date_fork 成为 latest_run 的首个 e2e 形调用方）。

**步骤 7|soak 三处小硬化（独立小 commit)**:daily-soak.sh:45 glob→`manifest_2*.jsonl`;daily_arxiv cmd_prune **双侧归一 + 末条胜**(~6 行：`latest[canon_id(r['id'])]=status` 扫描→`keep={safe_id(c) for c,s in latest if s not in clean}` 再比 d.name——实证今 raw canon 键对 flat d.name 永不匹配，slash-id 异常格正被误删）;errsweep.sh:17 DATE 改 `date -u +%F` 与 soak 同源（消日界错位一日）。

**步骤 8|文档收口**:benchmark.md §7 命名 dag-run/eval-run/e2e 三形+outputs-map 约定+records/=stage 账专用+sidecar 禁入；flag-quirks 表成文（异构语义文档化不统一）;RETENTION.md/benches.md 同步；bench_cli docstring 写禁区。

**步骤 9|可选尾项**:`stamp_run_meta` 一次性回填 live results/(kind 键，460 个 archive 不回填——读径 glob 兜底永存）;corpus eprint_to_layer 共享写手仅在下个新层立项时落；wilson_ci/largest_remainder/resample_ci 各带真实调用方才上移。

---

## 5. 不做清单（明确排除的过度设计）

| 排除项                                          | 理由                                                                                  |
| ----------------------------------------------- | ------------------------------------------------------------------------------------- |
| records/ 压实/合并/原子重写统一                 | gate_scorecard freeze 四信号+errsweep 契约+triage glob 全押 append-only，一改全死     |
| id canon 归一进 helper                          | math--X/math/X 双拼写分裂本身是审计信号（wave-5 漏 253 格），key_fn 永远调用方注入    |
| 统一 cells.json/payload schema                  | 三种顶层是特性；fixloop 读 compilebench papers[].engines{} 是承重基线                 |
| registry CLI/基类/插件发现/import 模式 dispatch | flag 语义异构+pytest 钉名已证死路；pgrep 闸实证要求 exec                              |
| runs.jsonl/INDEX 注册表                         | 新写面=新腐化面；签名探测+COMMANDS 表零新状态                                         |
| e2e 收编进 RecLog/records 契轨                  | 双写账+StateStore+_paper_done+sample-drift+date-fork 四层守卫承重                     |
| 异步内核收编 stage_xlat/e2e_real                | req_timing contextvar/auth_tripped/AUTH_DEAD_STREAK 表达不了就别建；2 份 bespoke 可忍 |
| flag 语义归一                                   | --corpus 三义/--only/--n/--resume 异构是事实；只允许文档化不允许静默改                |
| corpus/ 搬迁合并、manifest 并轨                 | append-only 加层不删层；daily soak 在跑                                               |
| 任何存量数据/文件名迁移                         | 460 archive 目录 + 在跑管线零容忍                                                     |

---

## 6. 风险与对策（fatal/major 逐条处置映射）

| #   | 攻击（实证行号）                                                                                                                                                                           | 处置落点                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | quantile 同口径清单事实错误：xlatbench._p95 floor+clamp(:509)、gullet floor(:199)、_med 插值（:501)，换接=metric 静默漂移                                                                  | 步骤 1：只接实证 ceil-rank 三站，余者就地保留 + 注释防再提                                                                              |
| M2  | done_pred 默认 DONE_STATUS 对 flat 全错（compilebench stub 行无 status 字段→永不 done→重复行+report 双计）                                                                                 | BenchSpec/Ledger/done_keys 的 key_fn+pred **必传无默认**；采用前在真实 ledger diff 新旧 done 集做验收                                   |
| M3  | import 模式弄瞎 pgrep 活性闸（wave.py:201 单写者、status_panel:664)→双写者开在在飞 run                                                                                                     | bench_cli **exec-only**;test 断言注册名与 cmdline 可见脚本名一致                                                                        |
| M4  | compilebench 缺引擎子集修法若整条覆盖→cells.json 丢旧引擎→fixloop 静默失基线                                                                                                               | 步骤 1:setdefault().update() 合并 + 回归测试+fixloop 读者去重                                                                           |
| M5  | select_todo 高估同型：gate 记录形状承重（no_src/upstream_gate/_missing_rec 进 triage/errsweep 聚类）                                                                                       | gate_fn 自写账，helper 永不写账；sig 形状入契约测试                                                                                     |
| M6  | daily_arxiv prune canon/raw 失配：keep.add(raw id) vs d.name(flat)→slash-id 异常格今已误删                                                                                                 | 步骤 7:canon_id+safe_id 双侧归一+per-id 末条胜 + 双拼写单测                                                                             |
| M7  | fixloop :84 BASE 是 baseline 输入依赖必须钉死，只有 :85 OUT 该活                                                                                                                           | 只接 OUT;BASE 加注释钉死 + 可选 --allow-stale-base 闸；qualdrift 默认改必填不指 archive                                                 |
| M8  | find_runs 签名/排序坍缩会改 M2 门选目（四家政策实证全异）                                                                                                                                  | 全参数化；gate_scorecard 首接+picked-dir golden;decoy-run 负例                                                                          |
| M9  | records/ 文件名=stage glob 契约：sidecar 入内=幻影 stage 进 triage                                                                                                                         | 契约测试钉白名单；compact_jsonl 拒 records/+append 账                                                                                   |
| M10 | dump_run_meta 若建成 meta-builder 会坍缩 invocations append-history→波次窗死；0o600 断跨 uid 读                                                                                            | 纯写原语 docstring 禁传新建 dict;mode 0o644；契约钉 append-only+finished_at 单调                                                        |
| M11 | STAGES dict 撞名 :97 tuple re-export;dossier.py:58 第二份 stage 表                                                                                                                         | 命名 STAGE_DISPATCH;dossier 同 commit 改指单源                                                                                          |
| M12 | crash 包装语义未指明：写行=标 done 永不重试+report() KeyError；不写=空噱头                                                                                                                 | on_crash 显式字段，eval 默认 'print' 保今语义；契约钉 report(args)/seed_results 签名                                                    |
| M13 | corpus 测试 importorskip 静默 skip（实证 10 passed 2 skipped)                                                                                                                              | conftest sys.path 激活或契约断言不可 import，二选一                                                                                     |
| M14 | COMMANDS 单向完整性：漏注册=静默不全，重现发现性失败                                                                                                                                       | 双向钉：每条可解析 + 每个可执行文件必在名册或 UNLISTED                                                                                  |
| M15 | exec env 断档：bare python3 起再 exec python3→缺 defusedxml/httpx                                                                                                                          | exec 目标写死 `uv run --project $ROOT python`；文档：bare python3 仅 list/runs                                                          |
| M16 | 隔日重跑分叉烧 swe-2 配额（promo 2026-10-16 到期）——最锋利 footgun 两方案原本都没接                                                                                                        | _warn_date_fork 移植进 init_run_dir，一处接入全 adopt 者免疫+`--date latest` 约定                                                       |
| M17 | 半采用抽象净负（_benchkit/三死导出是前车）                                                                                                                                                 | helper DoD=同 commit ≥1 调用方；内核现实采用面写死 4-5 家，不摊大饼                                                                     |
| M18 | run 目分类学发明 vs 实存（archive 66/460 有 run_meta、5/8 e2e 无 records.jsonl)                                                                                                            | bench runs 用 COMMANDS outputs 表；find_dag_runs 只认 records/*.jsonl（盖全部实证消费方）;contract 文档按真实文件名清单写               |
| M19 | compact_jsonl 静默吞坏行=新数据丢失通道                                                                                                                                                    | 返回 {kept,dropped};dropped>0 打印警告                                                                                                  |
| —   | minor 批：validbench 'w' 杀窗/xlatbench:468 漏项/e2e `{tag}-{date}` 异式/errsweep 本地日/harvest 后 work 格可选/fixtures 字节锚/iter_units 需 out_dir/compilebench 非理想首 adopt/诚实账目 | 全部并入对应步骤（1/2/4/7)；账目诚实化：死面 -4400 LOC 是大头，活码 dedup 近盈亏平衡，真收益是约定单源；~30 文件、10-14 commit 现实估计 |

**铁律复核**（方案不违反任一硬约束）:corpus/corpus_daily/zh-store/fixtures 零触碰；records/ append-only 不动；id 双轨键全 helper 注入式；soak/errsweep 调用面零变化、写侧 internals 改动带 pgrep 门禁；bench 可弃性=删文件 + 删行，无框架税。
