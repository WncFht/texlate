# bench-harness — gate_scorecard + stagerun 计分正确性审计（2 BUG + 3 suspect，1 项在飞风险）

> 2026-09-17 收口。审计对象 `bench/py/gate_scorecard.py`、`bench/py/stagerun.py`，数据 `bench/results/stagerun-loop1-2026-09-16/`。审计时实跑读数 cells=5059, pdf=4552 (89.98%)（引用值 89.68%/+17 是旧快照——fixloop 记录仍在追加，有一次 `--on all --rerun` 波次在飞）。

## 逐核查点 verdict

**1. end-state 合并语义（末条 record 口径）—— suspect**
`gate_scorecard.py` 原 `f and f["status"] else c["status"]`：fix 记录存在即无条件覆盖 compile。已验证副作用：
- **14 格 stale fix 遮蔽**：fixloop 在 comp=partial 时跑出 post=partial，之后 compile 重跑已 clean（`metrics.compile_status_before=partial` vs 现值 `clean` 可证）。记分显示 fixloop:partial 而非 compile:clean —— **clean 少计 14**。机制同样能反向虚减 pdf（stale fix=fail 盖新 comp=partial/clean），本数据暂未出现。

**2. 在飞 `--on all` 将对 reject 格产生 fix 记录 —— BUG（通胀路径，正在逼近）**
`stagerun.py:1242-1248` `_ON_PRED["all"]=True` 对**所有** compile zh 记录含 reject/skip；`stage_fixloop` 不滤 reject。实测 **414/414 reject 格 splice/ 均在盘**（copytree 先于 inject 拒判，stagerun.py:1004-1026）→ `_fixloop_one` 不 skip → **post-judge 无条件编译该树**（stagerun.py:1188-1194）。这些树是 inject 被拒的 latex209 文档（含 mock 译文 CJK，实测一格 cjk=3472）：post 一旦出 pdf，expect_cjk 检查也过，判 partial/clean → 被计为有 PDF —— **414 格潜在虚增，足够把读数推过 90% 的假 PASS**。且 reject 桶随之消失（`compile:reject`→`fixloop:X`），excl-reject 口径分母也膨胀回 5059。skip 格（65 个，无 splice）只记 fixloop:skip，计数无害但属无效 churn（skip 非 DONE 每次 --on all 重记）。
- 处置：leader 已加 scorecard 白名单兜底（fix 仅当 comp.status∈{fail,partial,clean} 才覆盖 + csb 新鲜度校验）；harness 侧 `--on all` 应排除 reject/skip，fail 救回改 `--ids` 清单——已路由 项目体验方式。

**3. verdict.status vs compile.ok —— correct**
scorecard 用 `rec["status"]`，compile/fixloop 两侧该字段均 = `verdict.status`（stagerun.py:1064, 1205），非 compile.ok。

**4. pdf 判定：status 字段 vs bytes 实计 —— suspect（口径分歧，±1）**
对盘核验：全部 clean+partial 格主文档 pdf 在盘；26/27 fail 格无 pdf。唯一分歧 `1511.06744`：timeout（120s SIGKILL）但 `lrpaper.pdf` 225KB 落盘——judge 有意判 fail（死进程产出不可信，judge.py:135-137），bytes 口径会计 pdf。**scorecard 比 bytes 口径少计 1 格**，不改变门结论。
- 另：`fixloop_verdict=best_effort_pdf` 的格若 post=fail，sig 记 best_effort_pdf 有误导——sig 取自 fixloop 自判非 post 复判。

**5. reject/skip 排除口径 —— suspect**
`excl-reject(n=4645)` 只剔 `compile:reject`(414)。64 格 parse-reject 经 xlat-skip 落到 `compile:skip` +1 格 xlat-fail——同为上游拒稿却留在分母 → excl-reject 口径少剔 64（若一致剔除 pdf=4552/4580=**99.39%** vs 现报 98.00%）。主口径含全部分母合理（端到端交付率），但两个口径排除规则不自洽。

**6. records append vs scorecard 读法 —— correct**
`iter_jsonl` 容错跳坏行，kill 截尾/在写半截行安全；末行胜与 RecLog 语义一致。scorecard 读在写文件 → 动态快照，可接受。
- nit：`last[r["id"]]` 无 KeyError 防护——已随白名单一起修（缺 id 行跳过）。

**7. run_meta/cases 一致性 —— correct**
invocations 逐次在录，`finished_at` 滞后=设计上收尾才推进。cases.jsonl 2974 行 ≈ fixloop() 调用数（crash_rec 路径无 case 行，差值可解）。

**8. `stage_fixloop` 候选选取 `cand[-1]` —— BUG（latent，本数据无伤）**
`stagerun.py:1258-1261`：`comp_recs` 是 `{(id,arm,upstream):rec}` dict，`cand[-1]` 取的是**最后插入的不同 key**（dict 序=首插序），不是末条 record。多 upstream 史 64 id 中 1 例踩中（0905.4046，均 skip 无伤）。若 mock 记录在 real 首录之后追加，fixloop 会拿陈旧 upstream 的 compile 格跑（csb/expect_cjk/upstream 全错配）。
- 修法：按行位或序列取真末条（load_latest 记 append index）——路由 项目体验方式。

**9. 双口径（px∪fix 纯管线 vs 含 base）—— correct**
scorecard `arm="zh"` 过滤 + fixloop 仅 fix 臂 = pf2final 勘误后的纯管线口径，不会犯 ledger 把 base pdf 计入的错误。

**10. 末行胜去重 —— correct**
同 id 多 upstream 记录按 append 序末条胜=物理终态；64 个多 upstream id 末条均一致，0 处 upstream mismatch。

**11. 手工抽查 14 格（每桶 2 格）—— correct**
fixloop:clean/partial 格 post verdict 与 status 一致且 postPdfB>0；fail 格 postPdfB=0；skip/reject 无 compile metrics。归类全对。

## 处置汇总（leader）

- **已修**（gate_scorecard.py，本次 commit）：fix 覆盖白名单（comp.status∈{fail,partial,clean}）+ csb 新鲜度校验（不等→stale 弃）+ 缺 csb 弃 + `r["id"]` KeyError 防护 + dropped 计数打印。修后实跑：**4554/5059=90.02% PASS**（与 M2 宣告值一致），stale 弃 14 格 clean 回升 2944，reject 桶 414 保持归 `inject:latex209`，在飞波次若污染 reject 将落 `over_noncompiled` 弃桶。
- **已路由 项目体验方式**：`--on all` 滤 reject/skip（stagerun.py:1242-1248）、`cand[-1]` 取真末条（1258-1261）、在飞波次建议停改 `--ids`。
- **记档**：timeout-pdf −1 口径差（judge 有意，不改）；excl-reject 分母自洽性（两个口径排除规则可对齐，非阻断）。

## 对门判读的影响（审计原表）

| 项 | 方向 | 量级 |
|---|---|---|
| reject 格将被 --on all 覆盖（在飞） | **虚增** | 至多 +414 pdf → 可致假 PASS（已被 scorecard 白名单兜底） |
| stale fix 遮蔽 comp=clean | clean 偏低 | −14 clean（已修，回升） |
| timeout-pdf 计 fail | pdf 偏低 | −1（vs bytes 口径，记档） |
| excl-reject 未剔上游 reject | excl 口径偏低 | 分母多 64 |
