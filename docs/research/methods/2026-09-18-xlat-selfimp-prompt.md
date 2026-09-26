# selfimp-qual 自改进环协议 —— dense-feedback 四层反馈与波次车道

> **结论**：把「评估→改进」做成全自动闭环的关键设计 = dense feedback 三原则（反馈局部可归因、廉价及时、可客观验证）+ 四层反馈塔（L0 确定性 → L1 单发 judge 探针 → L2 批层基线 → L3 人锚）+ 波次车道（W0 协议落地 → W1 基线 → W2 假设实装）+ 假设池状态机（open → adopted/rejected 留档防重派）。每个实验只回答一个具体问题，动手前先写「出现什么结果说明想错了」。
> **状态**：时点证据（2026-09-18 协议口径）。协议形态与 qualbench ESA 改造均已落地（`bench/py/qualbench.py` protocol_v=esa2、`bench/py/report/qual*.py` 五件套）；假设池收割结果见同域 `2026-09-19-selfimp-skeleton.md`。硬边界中的具体模型名/网关细节为当时运营约束，方法论通用。
> **日期**：2026-09-18（2026-09-20 迁入重编）

目标：先落地 qualbench 的 ESA 协议改造，再跑出可信基线，然后持续从假设池取假设做「探针→实装→回归」波次。方法论锚定 dense feedback 三原则：反馈必须局部可归因（绑定到具体 chunk/类目/机制，不是一句「质量下降了」）、廉价及时（便宜层能答的绝不上升一层）、可客观验证（用测试、确定性信号、可比较指标判定，不靠观感）。

## 硬边界（人守的线）

- 模型池只用内部网关列出的免费档；与被评同型的模型永不任 judge；judge≠translator 按每条 chunk 的 meta.model 强制。
- judge 调用参数：temperature=0.1（temp=0 会触发网关 502）、max_tokens≥8192（reasoning 烧预算）、read timeout 300s、3 次重试。
- > 30min 的批一律脱管运行（setsid+nohup + run.log 直写 + 文件面监控），绝不前台阻塞等。
- 不碰正在运行的进程、不读写他队在飞状态；scratch 只写仓库内 scratch 区。
- 对外语义改动要升级给人确认：judge 协议形态、contested 触发阈值、门禁线、新模型入网、假设池 REVIEW 级条目。其余全自主，不等批准。

## dense feedback 分层（核心纪律）

| 层            | 成本              | 内容                                                                                                                                     |
| ------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| L0 确定性层   | 免费秒回          | ph_missing/ph_invented、en_residue≥8、same-as-source 回显、长度比带、scoped pytest、parsebench identity/leak。这层能判死的假设不许烧模型 |
| L1 单发 judge | 极廉价            | ESA 协议一次调用出 `{errors[], stated100}`；探针规模 n≤10，先探针后批量                                                                  |
| L2 批层       | ~1.6 万 mult·call | 1200-chunk 分层基线 + frozen-300 回归子集 + contested→第二 judge 二裁                                                                    |
| L3 人锚层     | 人工              | ~200-chunk ESA^AI 半标注（judge 预标、人核改判），产校准读数                                                                             |

## 车队结构（20 lane，波次发车，文件归属互斥登记进台账）

**Wave-0 协议落地**（先行，全并行）：

1. proto-core：qualbench 改 ESA 两步单发——输出 `{errors:[{span,category,severity,note}], score:0-100}`，record 增 span_verified/stated100/derived100/score_delta，resume key 并入 protocol_v（防旧协议分数静默截留）。
2. proto-prompt：MQM 化类目表——六 flag 映射 + convention 窄枚举（防 GEMBA-MQM 的 locale 滥用）+ fluency-register report-only + critical 收窄到枚举致命类目。
3. proto-route：judge 路由——主 judge 异尺寸强模型；二裁弱一档模型，触发：|Δ|>15、stated≤55、任一 critical、L0 信号矛盾。
4. proto-records：records schema 迁移 + aggregate/report 新字段（per-category×severity 表、contested 率）。
5. proto-probe：改造前后 n=8 对照冒烟。
6. proto-test：pytest 钉——parse 新 JSON 形态、key 迁移、trigger 逻辑、span_verified 子串校验。

**Wave-1 基线**（依赖 W0 合并）：

7. sample：译文池分层抽样 ~300-400 篇×3-4 chunk（para 长度三分层、caption/section_title 各保底 ~150）→ sample.jsonl。
8. batch：脱管 judge 批驱动（resume、限速、失败重排、judge_error 台账）。
9. anchor：~200-chunk ESA^AI 人审包（judge 预标 span + 人核模板 + 回收格式）。
10. stats：block bootstrap CI（paper 簇 B=1000）+ tie-calibrated pairwise acc + report 生成器。
11. freeze：frozen-300 钉集 + 分布漂移门禁（分数分布/flag 率/per-kind 均值，不走逐 chunk 比对）。

**Wave-2 改进环**（依赖基线读数；假设从池 open 区按证据强度取）：

12. skel-curate：假设池卫生——去重、状态流转、证据指针校验、upstream 挖掘补新。
    13–18. 每假设一 lane（一轮 ≤4 并发实装）：如低分块重翻闭环、abstract-context、auto-extract-glossary、c0-json-strip、output-sanity-gate、glossary-ws-flex…
13. drift-watch：监控 contested 率/flag 分布/en_residue 漂移，异常即报。
14. triangulate：XCOMET-QE 非 LLM 对照臂可行性评估件（CC-BY-NC-SA 仅内部用）。

## 单 lane 循环协议

取假设（条目必须带证据指针，没有的先侦察补证据）→ L1 探针 n≤10 判死/放行 → 实装（文件归属先登记）→ L0 钉测 + frozen-300 漂移检查 → 收或弃 → 假设池回流：adopted 附适用条件 + 验证证据，rejected 附判死数据。僵尸代理即交即关，roster 不留闲名。

## 台账与汇报

台账 append-only，每条一行：时间/lane/commit/证据指针；lane 报告统一纯文本落盘。里程碑/事故/跨会话冲突即时记。每波末汇总：stated100 mean±CI、contested 率、错误分类×severity 表、pairwise acc、mult 消耗，附下波发车单。

## 验收口径

- 基线 report：stated100 分布带 paper-簇 CI、per-kind 均值、分类×severity 错误表、contested 率。
- 校准读数：锚定集 pairwise acc（目标 ≥0.65）、stated−人 分类别 Δ、同家族残余自偏好实测面。
- frozen-300 门禁活着：后续任何改动跑出分布漂移即拦。
- 成本回执：judge 面消耗占翻译臂 <5%。
