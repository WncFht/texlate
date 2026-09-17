# 首轮 loop 批 runbook —— stagerun 分阶段批量操作单

依据 `docs/research/product/2026-09-16-batch-hardening-design.md`（§6 文件协议 / §7 规模并发 / §10.3 首轮范围）写成，命令参数按 `bench/py/stagerun.py` 2026-09-16 落盘版实际 CLI（各子命令 `--help` 可查）。

**批次定义**：corpus_v3 全层（core+booster+hot）跑 mock 全 stage + real n=50 子集 + sabotage 两臂 → 首版 tickets.jsonl。存量 1259（13 篇 withdrawn stub 记 reject）；若扩库层已并入 manifest（目标 ~5000），同套命令自动覆盖，估时按 §7.3 放大——本单表格给存量量级，扩库后量级见各步注记。
**结果目录**：`bench/results/stagerun-loop1-<date>/`（本单统一 `--tag loop1`；`--date` 默认当天，跨天续跑用 `--dir` 钉住）。

## 0. 前置检查（按序，任一不过先修再开批）

```bash
cd ~/src/texlate

# 1) 网关/闸面探活——单行三探，任一 FAIL exit 1
bash scripts/gw-health.sh
#   tunnel 格探的是产品链 ssh 隧道，bench 批量不需要——未起隧道属预期，
#   只要 gwcap+direct 两格 ok 即可；想全绿就 GW_HEALTH_SKIP_TUNNEL=1。
#   gwcap 格 queued 持续积压时别发 real 臂（sem=4 全局共享，排队=别人的活在跑）。

# 2) 批量自检——import walk + mock 链 + 磁盘 + manifest + 工具链 + 网关认证 + gwcap
uv run python bench/py/preflight_batch.py
#   磁盘门默认 50G（存量批 work 树 ~20G；gate 批 5000 篇前调 --min-free-gb 80）。
#   离线自检用 --no-net（跳网关两项）。

# 3) src 快照（churn 期强烈建议——bench 期间 src/ 被并行代理改动时隔离）
cp -a src tmp/src-snap-loop1
export TEXLATE_SRC=$PWD/tmp/src-snap-loop1   # 之后所有 stagerun/preflight 命令都吃到快照
```

另两条人工确认：同一结果目同时只跑**一个** stagerun 进程（records 文件是单写者 append，两个进程同目同 stage 会重复跑 + 行交错）；`git status` 无半截 refactor（import walk 会兜，但先看一眼更稳）。

## 1. 跑批序列

固定：`SR="uv run python bench/py/stagerun.py"`、`LAYERS="core,booster,hot"`（**`--layers` 默认只 core——全存量必须显式三层**）、`--seed 42`。每步先跑一次 stagerun 自带 preflight（import+mock 链，不过关 exit 2 拒绝跑）。

| 序  | 命令                                                                                 | 产物                                                                     | 估时（1259 篇，archbox 12C）              |
| --- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------ | ----------------------------------------- |
| 1   | `$SR ingest --layers $LAYERS --tag loop1`                                            | `work/{id}/src/`、`records/ingest.jsonl`                                 | 分钟级（已物化=copytree；stub 记 reject） |
| 2   | `$SR parse --layers $LAYERS --tag loop1 --jobs 6`                                    | `records/parse.jsonl`、`work/{id}/zh/`（归一英文树）、`parse.json`       | ~10-30min                                 |
| 3   | `$SR xlat --arm mock --layers $LAYERS --tag loop1 --jobs 6`                          | `records/xlat.jsonl`(arm=mock)、zh/ 就地翻译、`xlat-mock.jsonl` 逐块明细 | <1h                                       |
| 4   | `$SR compile --arm zh --xlat-arm mock --layers $LAYERS --tag loop1 --jobs 6`         | `records/compile.jsonl`(upstream=mock)、`splice/`                        | ~40min-1h                                 |
| 5   | `$SR compile --arm base --layers $LAYERS --tag loop1 --jobs 6`                       | compile.jsonl(arm=base)、`build-base/`——首轮全集=**源健康基线**          | ~1.5h                                     |
| 6   | `$SR fixloop --on fail --layers $LAYERS --tag loop1 --jobs 6`                        | `records/fixloop.jsonl`、`cases.jsonl`、splice/ 修复                     | ~2h（n100 推 ~600 格）                    |
| 7   | `$SR fixloop --on clean --n 350 --seed 42 --layers $LAYERS --tag loop1`              | 幂等探针 ~100 clean 格（clean 率 ~28% 估），门：post 全 clean、零 dirty  | ~30min                                    |
| 8   | `$SR xlat --arm real --n 50 --seed 42 --layers $LAYERS --tag loop1`                  | xlat.jsonl(arm=real)、50 篇 zh/ 覆写为真译文                             | ~1-1.5h（sem=4 gwcap 硬闸）               |
| 9   | `$SR compile --arm zh --xlat-arm real --n 50 --seed 42 --layers $LAYERS --tag loop1` | compile.jsonl(upstream=real)                                             | ~25min                                    |
| 10  | `$SR fixloop --on fail --n 50 --seed 42 --layers $LAYERS --tag loop1`                | 补 real-upstream 新 fail 格                                              | 按量                                      |
| 11  | `$SR xlat --arm sabotage-b --layers $LAYERS --tag loop1 --jobs 6`                    | xlat 台账 caught/recovered/escaped——**escaped>0 即 fail 硬门**           | 分钟级                                    |
| 12  | `$SR xlat --arm sabotage-c --layers $LAYERS --tag loop1 --jobs 6`                    | 同上（spliced/dropped 台账）                                             | 分钟级                                    |

扩库后 ~5000 篇的对应量级（设计 §7.3）：parse ~30min、xlat mock <1h、compile zh+base ~7h、fixloop ~2500 格 ~7h、real 臂按子集不变（n=300 ≈ 5-7h，n=50 ≈ 1-1.5h，gwcap sem=4 限死）。

### 排序约束（重要，zh/ 是臂间共享演化树）

- `xlat` 各臂在 zh/ 上**就地翻译**并写 `.xlat-arm.json` 记 provenance；后跑的臂覆写先跑的产物。
- **第 4 步必须早于 8/11/12**：real/sabotage 一旦跑过，zh/ 不再是 mock 树。`--xlat-arm mock` 钉住预期，marker 不符的格记 `arm_mismatch` skip 不硬编。
- 第 9 步 `--n 50 --seed 42 --layers` 与第 8 步完全一致 → `pick_sample` 确定性抽到同一 id 集；`--xlat-arm real` 把 real xlat 半败（marker 仍 mock）的格挡成 skip 而非错编成 real。
- 第 10 步同选样参数 → 只迭代那 50 篇；fixloop 取每篇**末条** compile zh 记录（=当前 splice/ 的 provenance），mock-upstream 格 resume 已 done，只补 real 新 fail。
- **sabotage 两臂放全批最后**——跑完全部 zh/ 均被污染。11→12 连跑时 c 臂输入是 b 臂残树（台账按 chunk source↔translation 对齐，机制仍有效）；要严格隔离两臂/保干净树，用独立 `--tag` 目录重跑 ingest+parse（分钟级 + 10-30min）再各臂单跑。
- sabotage 之后若要回归 compile/zh 臂：`parse --rerun --ids <受影响>` 重建 zh/ → `xlat --arm mock --rerun --ids <同>` 重译 → 再 compile。splice/ 里的编译现场不受影响（compile 时已 copytree 固化）。

## 2. resume 与中断恢复

- **重跑同命令即续**：`records/{stage}.jsonl` 里 `(id, arm, upstream)` 已有终态（ok/partial/clean/fail/reject/fault/dirty_pdf）的格跳过；`skip`（上游门未过）与 `error`（harness 崩）属可重试类自动重跑。
- `--rerun`：无视 records 全量重跑本次选样（append 新行，triage 取末条）。
- `--time-budget S`：到点停发新格，已 append 的保留（xlat 会 cancel 在途任务）。
- Ctrl-C / 机器崩：直接重跑同命令。半截行由 triage 读端容错（坏 json 行跳过并 warn）。
- 跨天续跑：`--tag` 会换日期目录——续跑用 `--dir bench/results/stagerun-loop1-<原date>` 钉住原目录。
- 补跑单篇/小集：`--ids id1,id2` 或 `--only <子串>`。

### 长跑批一律脱管（>30min 强制）

harness（Claude Code）内存看门狗在系统内存尖峰时**优先杀后台任务**——kernel OOM 尚有 17G avail 时后台批已被清（2026-09-17 n200 三连杀实证，每次烧掉在飞格已翻的 LLM chunks）。任何估时 >30min 的批（stagerun 全段、e2e_real_bench）一律脱离任务系统：

```bash
setsid nohup <cmd> >> bench/results/<dir>/run.log 2>&1 < /dev/null &
echo "detached pid=$!"   # 记 pid，监控用
```

- 日志**直写文件**，不要 `| tail`（管道缓冲到进程退出才吐，中途零观测面）。
- 无 task-notification——用 cron/周期查 `kill -0 <pid>` + records 行数增长；records append 真账天然断点续跑（死后重跑同命令，勿带 --rerun）。
- **setsid 会 fork**：`$!` 拿到的常是已退 wrapper，真 pid 用 `pgrep -f '<argv 特征>'` 补；杀批按 pgroup `kill -- -<pgid>`（pgid 未必等于主 pid，`ps -o pgid=` 先查），误杀漏杀都会造成同目双写。
- /tmp 是 usrquota tmpfs 烧 RAM：src 冻结快照、大体 scratch 一律放 repo `tmp/`（disk-backed、gitignored）。

## 3. 产物速查

```
bench/results/stagerun-loop1-<date>/
  records/{ingest,parse,xlat,compile,fixloop}.jsonl   # 每行一格 append；行在=done
  work/{id}/src/         # ingest 物化（base 臂归因基准，永不改）
  work/{id}/zh/          # parse 归一英文树 → xlat 就地译；.xlat-arm.json 记臂
  work/{id}/parse.json   # main_rel/engine_resolved/route/normalize/逐文件 warnings
  work/{id}/xlat-{arm}.jsonl  # 逐块明细（status/attempts/warnings/...）
  work/{id}/splice/      # compile zh 现场（fixloop 就地修复同目）
  work/{id}/build-base/  # base 臂原文直编
  work/{id}/_texmf/      # fixloop 每篇冷 usertree
  cases.jsonl            # fixloop CaseSink（产品回归样本）
  run_meta.json          # created/git_rev/逐次 argv+seed+layers
```

## 4. 失败排查顺序

1. **整批零进展/全 fault** → `bash scripts/gw-health.sh` + `preflight_batch.py`。auth 静默全败是设计 §4 点名头号洞（401 逐 chunk 吞成 skipped）；records 里看 `sig` 是否 auth/* 聚类，网关直测 `curl -H 'Authorization: Bearer 240127' http://100.105.212.52:3003/v1/models` 应 200。
2. **大片 upstream_gate skip** → 回溯上游 stage records：`no_src`（ingest 没收）/`no_parse_tree`/`not_translated`/`arm_mismatch`（zh/ 被后臂覆写，按 §1 排序约束重排）。
3. **parse 大片 reject** → `records/parse.jsonl` 按 sig 聚类（route_reject/no_main_tex/parse_fail）。
4. **xlat real 故障** → gwcap queued 积压（`gw-health.sh`）/模型 probe 失败（stagerun 起臂时自测，不过直接 abort）/`oversize` reject（>250k chars 闸）。
5. **status=error 散点** → `errors[0].code=harness:*` 是 harness 崩而非论文问题，安全重跑。
6. **compile/fixloop 异常签名** → 不逐篇看，直接进 §5 triage 聚类出工单。

## 5. 批后 triage → 工单

```bash
python3 bench/py/triage.py all bench/results/stagerun-loop1-<date>/
# = records（→ tickets.jsonl 按 count 降序）+ metrics（→ bench/results/metrics.jsonl 追加）+ report（→ report.md）
```

之后按设计 §8：tickets 按签名量排序取 top-N → leader 每工单 spawn fixer（验收三门：replay_case 本格 fail→pdf / replay_all 无 regressed / stats_backfill 回填转正）→ 合并后同 seed 重跑受影响 stage，逐 stage 成功率不得跌。

## 6. go/no-go 门（§7.4，triage 后对照）

- parse：expander leak ≤0.05%、identity 100%（records warn_kinds 面 + parsebench 复核）
- xlat：契约率 ≥99.9%（`xlat-{arm}.jsonl` 逐块算）、sabotage escaped==0、auth 熔断生效
- compile：zh 非 clean ∧ base clean 回归集 →0（管线不得引入新 fail）
- fixloop：rescue 率单调不降、`--on clean` 幂等格零 dirty、replay_all 无 regressed
