# trizone-ledger v2 Phase 0–2 存量普查进场实录

> **状态**：已完成（时点实录 2026-09-22；自 `spec/bench-trizone.md` 文件头迁出——活契约不承载执行叙事）
> **日期**：2026-09-22

Phase 0–2 是 trizone-ledger v2 内核四波构建（Wave A–C，见 [2026-09-22-bench内核wave-d收官.md](2026-09-22-bench内核wave-d收官.md)）同期的存量资产普查进场波次。以下为执行当时的原始记录，逐字保留。

## Phase 0 已收口（2026-09-22）

进程普查零写者（status_panel 只读常驻除外；errsweep timer 已 vanished 不会自动触发，最后实跑 9-20）；zh-store manifest 110 行未 commit delta 拷出双份（sha `2ecd0840`）；`git fsck --connectivity-only` 通过。**真账册勘定**：repo 根 `bench.db` 是 0B 空壳，真身 `tmp/benchxp-sqlite/bench.db`（457MB，sha `3e0a638c`，160 run / 197,460 records + 6,524 eval + 36,904 cases + 7,323 cells，xp.py 于 9-21 17:53 自 records/cases/cells 归并）。异地两份：`$ROOT/backup/phase0-20260922/`（4.3G/24,981 文件）与 fht-mba `~/texlate-bench-backup/phase0-20260922/`（指纹远验一致）。manifest↔字节对账：5,026 账载 id ↔ 297 在盘 id——4,747 有账无字节（丢失总清单）、18 孤儿（recovered-replay-0920）、117 账实不符（账称 has_zh 实仅 splice）+19 zone 错位，报告在两份备份 `docs/` 及 `tmp/phase0-20260922/reconcile.*`。`$ROOT/PAUSE` 已挂：run/plan 拒跑、import 不受影响；`scripts/errsweep.sh` 已接 PAUSE 首检。「errsweep 一轮绿」判据不适用（timer 已撤，重部署裁决推迟到 Phase 3）。

## Phase 1 已收口（2026-09-22）

四源全量进场，ledger 443,612 行——bench.db 248,211 行→225,528 事件+22,683 隔离（160 run）；bench/ 全扫 235,356 行→205,348 事件+28,188 隔离+1,820 重跳（265 run，含补扫的 records/ 目录 stage 账与 eval/cells 恢复账）；flip14/15 车道 294 行全落；zh-store 5,481 行→10,576 事件+3 隔离、0 孤儿。绿判据全过：逐源 行=事件+隔离+重跳 精确平；抽样对拍 200/200 事件 sha 在 dedupe、20/20 隔离 dedup_sha 复算一致、25/25 (run,id,stage) 组 (status,dur_s,code) 多重集逐拍相等；`rebuild-index` 41.5s≤60s；四源重跑 emitted=0 ledger 零增长（幂等）；ledger 全文零命中网关密钥/tailnet 段。修复一处实伤：import 铸的 run 目录无 heartbeat/.lock，全部命中僵尸签名→每写命令重扫 ~172MB 分账并追加 428 条 warn note（已产 1,438 条 note + 2,868 条 seq_conflict 隔离，皆该缺陷产物）；sweep 三处修正后轻量版 85ms、零增长（`da15db34`）。PAUSE 保持挂载。

## Phase 2 已收口（2026-09-22）

zh-store 活字节普查落库（`importer.seed_vault_zhstore`，CLI `bench vault seed --manifest --bytes-root`）——**字节三态对账而非 manifest 重放**：5,026 账载 id 中 294 个在盘目录全数 harvest（452 kind 目录、3.31GB 硬链进场、逐文件 sha256 进 meta.files），物理容器压过账面 zone（_quarantine 下字节一律 quar/quar）；4,729 有账无字节沿用 Phase-1 tombstone 不再重发；3 个 canon 拒收目录（`*.bak-mock` mock 字节）按设计留原地、进 noncanon 报告不进 vault。metas 294/294 带 redacted provenance；zone 分布 primary/verified=252、quar=41、alt=1，与 Phase-1 字节侧计数精确一致；index vault_meta 5,023 行零 live∧tombstone 混居，asset 事件 906=454+452。绿判据：`vault verify --level full` 11,040 文件全量哈希 0 bad/0 meta_missing/0 extra；普查重跑 harvested=0/already=294 ledger 零增长（幂等）；`bench backup` 已挂 `texlate-bench-backup.timer` 日 04:52（首份 tar 1.08G 已产）；`bench doctor` 全绿（stray_dirs 按设计报 zh-store/results/archive 留待 Phase-4 裁决）。Phase-1 两处遗留顺带收口：import 铸 run 补 `.lock` 永生锁文件（429 个回填，`lock_invariants` 转绿）；`mint_run_seq` 同窗补写 runs.jsonl 报表行（429 行回填，`seqfile=events=runs.jsonl=429`）。普查种子格 meta 带 `import_src` 标记，doctor 付费对账 exempt 不误报「无付费凭证字节」（seeded-exempt=294）。**tombstone regen 决策单**交付在 `tmp/phase2-20260922/tombstone-regen-list.jsonl`（4,729 id：zone=4,304 primary/256 alt/169 quarantine；kinds_lost=4,533 zh+splice / 196 splice-only；model=swe-2-medium 2,749 / 空 1,980）。claims 表随播种格上线可租。原树 `bench/zh-store/` 按回退点约定保留到 Phase 3 验证后。PAUSE 保持挂载。
