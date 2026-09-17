# scorecard-fuzz — bench verdict/scorecard 聚合不变量对抗测试

> 2026-09-17 收口。交付 `tests/test_fuzz_scorecard.py`（~1350 行，commit `b79ef28`）：**27 passed + 57 xfailed(strict, 0 xpass)**，ruff select=ALL 净 + format 净。真实数据回放执行（stagerun-loop1 records + results.json 在场）。

## 守恒结论——全部聚合器无违例

合成 fuzz + 真实记录字段级变异回放（status/sig/id/arm/upstream/dur_s/csb/errval/popjunk）下守恒不变量全成立：

- **gate_scorecard.main**：Σ end == cells；pdf ≤ cells；clean ≤ pdf；90% 门边界 need 公式逐点正确（10格9pdf→PASS、10格8pdf→need+1、100格90pdf→PASS）。
- **pick_final** 真值表封闭：fix 接管 iff `c.status∈COMPILED ∧ csb==status ∧ upstream 相容`；drop_reason ∈ {over_noncompiled,no_csb,stale,upstream_mismatch}。
- **triage.load_records**：输出行数 == Σ文件（唯一 (id,arm,upstream) 键 + 无 id dict 行）；同键末条胜。
- **build_tickets**：Σ count == 非豁免记录数；每记录恰一 (stage,sig) 桶；排序 (-count,stage,signature)；sig_id 唯一；example_ids ≤ MAX_EXAMPLES 去重。
- **compute_metrics**：逐 cell Σby_status==total；rate∈[0,1]；pipeline_introduced 归因口径正确（compile zh 非 ok/skip/error ∧ base ok）。

## 缺陷台账（9 族，57 strict xfail 钉；全为类型脏逃逸）

| # | 缺陷 | 位置 | 影响 | 修法 |
|---|------|------|------|------|
| 1 | `last_records` 比账侧娇气三处 | gate_scorecard.py:37-55 | kill 截尾 UTF-8→UnicodeDecodeError（严格解码）；非 dict 行→AttributeError；errors 含非 dict→AttributeError——正是 append-ledger 声称容忍的场景 | errors="replace"+isinstance 双闸 |
| 2 | `iter_jsonl`/`load_records` 同族 | benchlib.py:58-101 | read_text 严格→截尾 UTF-8 崩；`key in r`/`r[key]` 对 int/float/bool/None 行 TypeError、str/list 静默错 | 容错解码+isinstance dict |
| 3 | `verdict_sig` 类型脏 | benchlib.py:177/194 | reasons 非可迭代→TypeError；非 str first_error→re.search TypeError；**reasons=str 逐字符迭代产垃圾 sig**（"m"） | isinstance(reasons,list)+isinstance(first_error,str) |
| 4 | `pick_final` metrics 非 dict | gate_scorecard.py:70 | 真值非 dict→AttributeError（0/""/{} 靠 `or {}` 侥幸活）；compute_metrics degraded 探测 triage.py:593 同型 | isinstance 闸 |
| 5 | errors 字段为 dict | record_sig/bucket_sig/_upstream_gated/classify | `errs[0]`→dict KeyError 连带 build_tickets 崩；dict 型 errors 产错误 sig（"upstream:x"） | isinstance 闸 |
| 6 | `_wall_s` dur_s 非数值 | triage.py:508 | ValueError/TypeError；nan/inf 不崩但 wall_s=nan 写进 git 跟踪 metrics.jsonl——非严格 JSON 行腐化下游 | try/except+isfinite |
| 7 | `fixloop_degraded` 遍历全体非 attempted | triage.py:590-601 | STATUS_RANK 表外词按 -1；skip+csb 记录假阳退化（现潜伏：真实 skip 记录在 metrics.update 前 return 不带 csb） | `for r in attempted` |
| 8 | **missing_character:xN 按 N 碎票** | triage sig 归一 | fault=N 归一而 xN 不归一——loop1 实证同缺陷类碎成 ≥15 票（x1:286/x2:111/x3:49…x18+，另有裸 459） | `x\d+` 归一或 missing_character 进 _SIG_DROP_PAY |
| 9 | `legacy_records` results.json 类型脏 | triage.py:368-476 | 截尾→JSONDecodeError；顶层非 dict→AttributeError；verdict/rounds 类型混淆→AttributeError/KeyError/TypeError——与账侧容忍坏行设计不一致 | isinstance+容错解码 |

## 备注

缺陷清单同步写在文件 docstring「已钉缺陷」节（file:line/机理/修法）；修复后 XPASS(strict) 自动提醒拆钉。#8 碎票是 triage 可用性缺陷——同缺陷类 15+ 票摊薄了真实 top 签名排序。
