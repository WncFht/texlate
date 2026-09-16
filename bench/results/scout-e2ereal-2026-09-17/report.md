# scout-e2ereal — e2e_real_bench resume/--recode 健壮性审计（只读）

> 2026-09-17。审计对象 `bench/py/e2e_real_bench.py`（905 行）+ 依赖面 `benchlib.py`/`xlat/state.py`/`xlat/pipeline.py`/`compile/{engine,judge,sandbox}.py`/`fixloop/cases.py`，对照 live 现场 `bench/results/realpostfix2-2026-09-16/`（截稿 84/100 格，`TEXLATE_SRC=/tmp/texlate-src-realpostfix2` + `--recode --concurrency 2 --time-budget 43200`）。

## 语义真相表（场景 | 行为 | 证据）

| 场景 | 行为 | 证据 |
|---|---|---|
| records.jsonl 追加时机 | **每格完成后一次 append**（翻译+splice+编译+base/fix 全跑完才落行）；格中途 kill → 该格零行，不丢已完成的格 | e2e_real_bench.py:820 |
| 格内崩溃恢复 | chunk 级进度在 `_xlat_state/{sid}/state.json`（每块原子重写，tmp+rename）；工作树重跑时 rmtree+copytree 重建，翻译靠 state 免费续 | state.py:263-291；e2e_real_bench.py:292-294 |
| append 半截行 | `iter_jsonl` 容忍坏行（JSONDecodeError 跳过）→ 该格重跑 | benchlib.py:58-68 |
| 同 id 重记 | **追加双行**，`load_records` 末行胜；`alignbench.load_records_any` 同口径 | benchlib.py:88-94；alignbench.py:381-384 |
| results.json | 每格 `write_text` 全量重写（**非原子**）；仅当 records.jsonl 不存在时作种子 | e2e_real_bench.py:693-697,821-823 |
| matrix.md/summary.md | 每格 `write_reports` 重写（非原子） | e2e_real_bench.py:824 |
| run_meta.json | 启动时写一次，**无完成标记**；started_at=最近一次启动 | e2e_real_bench.py:717-734 |
| 普通续跑（无 flag） | `_paper_done`=有 status ∧ 非 bench_error ∧ translate 无 skipped/fault → cached 跳过；不满足 → 整格重进 run_project，chunk state 续翻 | e2e_real_bench.py:493-506,764-801 |
| --recode | `prev.code != _code_stamp()` → 重跑；**chunk 缓存仍在**（不重翻），parse/splice/compile 全走新码 | e2e_real_bench.py:759-763 |
| chunk 续跑过滤 | completed 只认 ok/partial；skipped/fault 必重试；`prev.source != c.content`（含等长内容变）判 drift 重翻 | pipeline.py:868-872,891-903 |
| 半完成格（翻完编译崩） | 无 records 行 → 重进；翻译命中 state 全免，编译/判读重做 | run()→_load_resumed pipeline.py:1050 |
| 重跑合并 | `results[rel].update(rec)` **浅合并**——新 rec 缺的顶层键（pipe-fix/base-xel/error/reject_at）从旧格残留 | e2e_real_bench.py:816-819 |
| KeyboardInterrupt/异常 | 无 try/finally——靠每格落盘兜底；`except Exception` 记 `status=bench_error` 行（**无 code 键**）；KeyboardInterrupt 属 BaseException 直接穿出，无收尾写 | e2e_real_bench.py:803-815 |
| time-budget | 格间检查，到点格边界干净停 | e2e_real_bench.py:834-840 |
| 并发/节流 | 篇间串行；篇内 `--concurrency`=worker 数（本臂 2）+ 首发单飞暖缓存；ChatClient 无全局信号量，httpx 180s/req；auth 连续 3 块失败 → AuthTrippedError → bench_error（每篇独立烧阈值，闸不跨篇） | pipeline.py:449,1013-1068；client.py:47 |
| 超时/信号格 | `compile.ok = not timed_out`（**ok 只表示没超时，非编译成功**）；`killed_by_signal` 归因只认 killed_signal/rc<0——sandbox(bwrap) 臂信号死被编码成正 rc=141 逃逸归因 | engine.py:1122；judge.py:96-106 |

## 风险清单

1. **【高】`--date` 跨日重启分叉**：`--date` 默认当天 UTC（e2e_real_bench.py:899）。本臂 09-16 起未传 --date → `realpostfix2-2026-09-16`。若崩溃后今天（09-17）原样重启 → 新建 `realpostfix2-2026-09-17` 空 records → 全 100 格重跑，结果劈两目录。**续跑必须显式 `--date 2026-09-16`**。
2. **【高】印章只钉 live repo 不钉快照**：`record.code` = ROOT 的 `git HEAD±dirty`（_code_stamp l:510-535），与 TEXLATE_SRC 内容无关。重启 --recode 时：live repo 被其他代理 commit/dirty 过 → 印章变 → **全部已完成格误判 stale 重跑**（chunk 缓存兜底、编译照烧）；反之快照换字节而 repo 未动 → 印章同 → 陈旧格误判新鲜。`-dirty` 对 src/texlate 任意无关改动都触发，过敏感。
3. **【中】浅合并残键**：recode/重跑后新格若不再产某臂（如 pipe-xel 转 clean → 无 pipe-fix），旧臂数据残留进新 append 行 → matrix/summary 出幻影 fix 行。
4. **【中】rc≥128 信号归因逃逸**：1404.5720 实证——pipe-xel（bwrap）`rc=141, killed_signal=null, ok:true` vs pipe-fix（裸 Popen）`rc=-13, killed=13`，同种 SIGPIPE 死两种记账。`judge._signal_attribution` 不认正 rc≥128，若晚 pass 被杀留了 pdf，可判 clean 而杀痕只剩 rc=141。
5. **【低】cases.jsonl 无去重**：fixloop 重跑同 (corpus,cond) 追加双行，`load_cases`/triage 不去重——分析端须自取末条。
6. **【低】results.json 撕写窗**：非原子重写，live 消费方可能读到截断 JSON；下次启动 records.jsonl 优先可自愈。
7. **【低】空 records 种子边例**：records.jsonl 存在但空 → results.json 种子被无视 → 全量重跑。
8. **【低】抽样确定性依赖 extracted/ 集合**：`pick_sample` 对可用集排序后 seeded sample——corpus 若后续补解压，同 seed 样本漂移。corpus_v3 冻结下无虞。
9. **【低】auth 死亡不停车**：凭证失效时每篇各烧 3 块阈值再 bench_error——全记成可重试行，不收摊。

## realpostfix2 收尾判读注意

- **进度**：84/100 格已落（pipe-xel verdict：clean 66 / fail 10 / partial 8；pipe-fix 补跑 18 格救回 clean 7）。records/cases 均无重复行，全部 `code=c818199-dirty`。
- **完成判据**：run_meta 无 finished 标记——以 `done ->` 日志行 + 进程退出 + records==100 为准。
- **快照存证**：快照与 manifest 原在 `/tmp/texlate-src-realpostfix2/`（重启即没）——**leader 已把 snapshot-manifest.txt 拷进 results 目录**（本报告交付时执行）。
- **3 格非终态**：0905.4439(skipped=1)、2203.13012(fault=1, 现 clean)、2403.15096(fault=3)——`_paper_done` 判未完成，任何重启都会整格重跑并追加双行（末行胜），verdict 可能翻转。
- **重启咒语**：同目录续跑须 `TEXLATE_SRC=<同一快照> ... --recode --date 2026-09-16 --tag realpostfix2`；且重启前先确认 live repo src/texlate 未变，否则印章漂移触发全量重跑。
- **verdict 读取口径**：`compile.ok` 只表示「没超时」；以 `verdict.status` 为准。rc=141 的格注意查 killed 语义（bwrap 信号编码）。
- **cached 补 fix 臂**：done 格续跑时若 `_want_fix` 且 pipe-xel 工作树还在会只补 pipe-fix 并追加双行——设计内行为，不是 bug。
