# e2e-residual — e2e_real_bench 残余风险消化（7 修）

> 2026-09-17 收口。scope：`bench/py/e2e_real_bench.py`（+~170 行净）。消化 scout-e2ereal 残余 5 项 + 2 新发现。leader 复核：15 hunks 逐条对账一致。agent 自证误跑两条只读 `git diff`（纪律禁 git）——无写影响，记档。

## 修复

1. **cases.jsonl 双行**：`_dedup_cases()` flock+原地 truncate 重写（刻意不用 os.replace——CaseSink 追加方 open→flock→append，原地写保并发追加落去重后文件末尾不写进旧 inode 丢行）；(corpus,cond) 末行胜、清截尾坏行、缺键行全保留、幂等。启动一次 + `pipe_fix_condition` fixloop 后单点。
2. **空 records 种子**：records 缺失/空/全坏 → 回退 results.json 种子；坏 JSON WARNING 按空起步（原 json.loads 裸奔炸启动）。
3. **抽样漂移**：`_stored_sample()` 读 run_meta.sample_ids（meta 重写前调）；有进度且重抽≠首轮→WARNING+沿用 stored；无 stored 但进度含样本外 id→WARNING 列出。`--ids` 显式不动；全新首跑尊重当次 seed/n。
4. **auth 不停车**：`translate_tree` 返回面加 `auth_all_failed`（AuthGate.all_failed——跨论文熔断由调用方累计的设计口径）；`except AuthTrippedError` 单列→bench_error 即收；连续 `_AUTH_DEAD_STREAK=2` 篇 all_failed→收摊；cached 格不触碰 streak。
5. **run_meta 完成标记**：`_close_meta()` 落 `ended_at`+`end_reason` ∈ completed/time_budget/auth_tripped/auth_dead/probe_failed；缺 ended_at=被杀（取证语义）。
6. **新发现**：`_tr()` 直索引 `t['leftover_ph']`——旧格式种子行续跑 write_reports KeyError 炸停（smoke 复现）→ `.get` 容忍。
7. bench_error 行补 `code` 印章（取证归因）。

## 没修（理由记档）

- rc≥128 信号归因逃逸——judge 车道在裁。
- records 同 id 双行——append 账设计内（末行胜），保留审计痕。
- load_cases 消费端不去重——写侧物理去重已堵源头。

## 验证

ruff 双链净；helper 单测（dedup 双行/坏行/缺键/幂等、stored 三路）全过；amain 离线 smoke A（空 records+种子→cached clean）+B（stored 沿用 WARNING+end_reason=completed）实证。
