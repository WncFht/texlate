# modeb-dirty — Mode-B dirty 计数 + 门槛 escaped==0 AND dirty==0

> 2026-09-16。改动仅 `bench/py/e2e_mock_bench.py`（+57/-7）。依据 `bench/results/repro-2410b-2026-09-16/report.md` §4a。

## 签名（DIRTY_SIGS，11 字面 — 全部 grep 核对过实际产出串）

L0 反馈字面（`L0Report.feedback()` l0.py:218-220 = `"\n".join(i.message ...)` 直拼）：

- `占位符缺失:` — l0.py:306
- `占位符疑似拼错` — l0.py:299（lev 配对臂）
- `多余/未识别占位符:` — l0.py:373（实际产出是合并字面；裸 `多余` 会对合法 zh 误报）
- `结构占位符` — l0.py:322（"脱离行首位置"）
- `注释区内臆造占位符` — l0.py:396

重试协议字面：

- `[Original]` `[Translation]` `[Error]` — prompts.py:273 三段式
- `previous_validation_error`（裸串，带不带括号都中）— pipeline.py:530
- `slot_validation_failures` — pipeline.py:560 批模式字段
- `[compile_error]` — pipeline.py:627 L2 回灌重译标；同款回显类，任务清单外补充

`[这是译文]` 按规格排除。mock 臂下括号节标会被散文 run 译成 `[这是译文]`（pipeline.py:227 `_PROSE_RUN_RX`）永不命中——保留作真模型 parrot 覆盖；mock 下实际 firing 的是 CJK 反馈字面（CJK 非散文 run → 原样回显）。

## 计数语义

- `delivered = e2e_mod._delivered(r) and r.chunk_id not in reverted` 替换 `spliced_ok`（e2e.py:114 = `ok or (partial and translation)`）。**partial 谓词修复已应用**：partial 交付块此前被 `spliced_ok`（严 ok）记成 caught——脏 partial 连 escaped 都不进的反向漏账。Mode C `spliced`/`dropped` 同口径修正（同样错位存在）。
- `dirty` = 交付破坏块 zh 命中任一签名——caught/recovered/escaped 之上的正交叠加层（脏块仍按 multiset 归 escaped/recovered；repro 案例 = recovered+dirty）。
- 台账新字段：`dirty`、`dirty_ids`、`dirty_detail`（`{chunk, kinds, hits}` 逐块签名命中供分诊）+ `by_kind` 桶内 `dirty`。旧 records 缺键经 `.get(k,0)` 聚合为 0——向后兼容。
- summary.md Mode B 段：台账行不变（escaped 保留）、新增 `- dirty N（…）` 行、门行 `门槛 escaped==0 AND dirty==0: PASS/FAIL`、非空时 `dirty chunk ids:`。

## 验证

1. 内联单测：每个签名命中自身字面；真 repro-2410b `DELIVERED_ZH` 载荷 → `['占位符缺失:']`；负例（`[这是译文]` 独行、裸 `多余`、`未闭合`、无括号 `Error`/`Original`）→ 干净。
2. **实跑** `run_project("2410.17957", ["pipeB-xel"])` 隔离工作目录：`dirty=3, dirty_ids=["2:3","5:3","5:33"], escaped=0`——`2:3` 即报告记录的击杀块；`5:3`/`5:33` 是 docs/6-Experiments.tex 姊妹现场。全 drop_ph kind。该工程门槛现在 FAIL。
3. **modec-expand n=80 在盘扫描**（records.jsonl 无逐块 zh，无法重算逐块）：DIRTY_SIGS grep `bench/work_e2emock/corpus_v3/pipeB-xel/<id>/*.tex` 跑后树 → **63/80 工程盘上残留 `占位符缺失:`**（2410.17957：docs/2-introdution.tex×1 + docs/6-Experiments.tex×2——与实跑 dirty_ids 精确吻合）。对照臂 `pipe-xel` 树 **0 命中**——签名零误报。盘上是台账时 dirty 的下界（L2/fixloop 可能在交付后清理部分现场）。

## 给 leader 的预警

聚合面：modec-expand n=80 有 3123 破坏 / 403 recovered / escaped=0。63/80 工程带盘上回显 → 预计 dirty 会在 `recovered`（corrector 路径）块上大面 firing——产品侧交付守卫（#94 l0-guard）落地前 Mode-B 跑批门槛将持续 FAIL。这是**有意的量测**而非回归，但 summary.md 复跑会读作广泛 FAIL。其余 L0 ERROR 族（env `未闭合 ×N`、`引用/标签 key 丢失:`、`'$' 计数不同`）同样可回显但不在 repro 词表内——若要更宽覆盖可作 DIRTY_SIGS 扩展候选。
