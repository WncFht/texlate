# 验证分层契约 —— 什么问题在哪级验证

> 对照 `docs/spec/benchmark.md`（B1–B7 评测器矩阵）：它定义**评测器是什么**，本文定义**一个问题该在哪一层被抓**——修复不算完，直到它能看见的最便宜那层被钉住；更高层只接低层结构性看不见的东西。

## 层级与入口

| 层           | 入口                                                                                                                                      | 底材                                                                                               | 量级                     | 时机                                  |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------ | ------------------------------------- |
| L0 单元/断言 | `uv run pytest tests/`（含 `test_bench_regression.py` 72 条 dict 断言 / 133 pytest 用例；契约产出走 `bench/py/fixture_assert.py`）        | 合成输入 + `bench/fixtures/*.tex`（@Tnn/@Wnn/@Xn，逐字节即语义）                                   | 秒级/单文件，分钟级/全套 | 每 commit、CI 硬门                    |
| L1 机制覆盖  | `uv run python bench/py/parsebench.py --corpus corpus`（v1 陷阱 39 + v2 渠道敏感 139 + 分层全量）                                         | `bench/corpus/` 统一物理根（v1/v2/m1k/iclr 层均已并入）                                            | 分钟级                   | 解析/扫描/归一化改动后，开批前        |
| L2 子集回归  | `uv run python bench/py/stagerun.py {parse,xlat,compile,fixloop} --n N --seed S` 或 `--ids` 定点（records/{stage}.jsonl append + resume） | corpus `mechanisms.jsonl` 机制台账（2026-09-18 时点 248 条，续增中以文件实数为准）+ 分层 manifest  | 分钟–小时                | 管线 stage 改动、新机制落账后定向重放 |
| L3 全量集成  | stagerun 全层全臂 + fixloop + sabotage 两臂 → `gate_scorecard.py` + `triage.py`（操作单 `bench/py/runbook_loop.md`）                      | corpus 全层（core 1000 + booster 200 + hot 166 + expand 3866——2026-09-18 时点，expand 新批续增中） | 过夜（1259 篇基线 ~7h+） | 里程碑门（M 验收）、发版前            |

## 问题 → 层 对照

| 问题类型                                 | 首选层       | 说明                                                                                                                                 |
| ---------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| 纯函数/codec/mask/正则/边界逻辑          | L0           | 合成输入 property/对拍测试，当场钉                                                                                                   |
| 日志判定（l2 分类/红线/verdict）         | L0 + L3      | 合成 log 进 `parse_log_text` 钉语义；真 `-file-line-error` log 只有 L3 生产面见得到                                                  |
| 解析机制（新坑/回归坑）                  | L0 → L1 → L2 | 最小复现 fixture 化登记 @Tnn（B2 生长机制：found-in-wild → covered → fixture）；L1 确认分布面；`mechanisms.jsonl` 落账后 L2 定向重放 |
| 翻译臂/台账契约（mock/sabotage/perturb） | L0 + L2      | 台账谓词单测钉口径；臂行为用 L2 子集跑真 records                                                                                     |
| 编译/fixloop 规则触发                    | L0 + L2/L3   | 合成 log 钉判定；救回率/规则谱只在批量上有意义                                                                                       |
| 逃逸面/对抗闸（sabotage/gate 红线）      | L2 + L3      | sabotage 臂分钟级台账；`escaped>0` 是 L3 硬门                                                                                        |
| resume/StateStore/跨进程状态             | L2           | records append + (id,arm,upstream) resume 语义跨运行才成立，L0 测不到                                                                |
| 性能/规模/并发/资源闸                    | L3           | 低层无代表性负载，preflight_batch.py 只做批前一票闸                                                                                  |
| 接口漂移（harness↔产品）                 | L0 + L2      | `is` 绑定/spy 钉接线；真跑是 L2 起                                                                                                   |

## 规则

1. **能低不高**：L0 能钉的（合成输入可复现）不许只在 L2/L3 靠批量撞见——批量发现的每个真坑都要沉淀回 L0 断言或 fixture。
2. **逐层语义**：每层绿只证明该层契约成立，不证明下层问题不存在（L0 全绿 ≠ 分布面无漂；L3 闸过 ≠ 单点逻辑无残余）。
3. **跨层不重复**：同一断言不重复钉在两层——高层存在的理由是低层看不见（规模/真料/跨进程），看得见的归低层。
4. **量级兑现**：估时以 `runbook_loop.md` 表为唯一事实源；层级归属争议按「cheapest tier that can see it」裁决。
