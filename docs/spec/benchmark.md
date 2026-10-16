# 评测器与分层契约

评测机制使用 `bench/py/kernel/` 与 `specs/`，统一入口为 `uv run python bench/py/bench run <spec> [k=v …]`。先用 `spec list` 和 `run --help` 确认实际入口，再查目标 spec 的参数与 stage。语料见[corpus.md](corpus.md)，持久化与付费规则见[bench-trizone.md](bench-trizone.md)，操作见[运行评测](../dev/bench.md)。

## 评测矩阵

| 类别          | spec                                       | 主要证据                                                  |
| ------------- | ------------------------------------------ | --------------------------------------------------------- |
| B1 解析       | parsebench                                 | 可解析性、identity、可译覆盖、泄漏、死占位符与孤儿段      |
| B2 陷阱       | fixture_assert                             | 与 pytest 共用 `_fixture_matrix/`，固定字节输入的机制断言 |
| B3 编译与修复 | compilebench、fixloop_bench、compilecensus | 源码裸编基线、中文条件、引擎差异、规则触发与救回          |
| B4 翻译       | xlatbench、qualbench                       | 硬契约、延迟、token 用量、错误标注与质量评分              |
| B5 全链       | e2e_mock、e2e_real、e2e_eval 系列          | 获取至版面质检的逐段漏斗和终态                            |
| B6 校验       | validbench                                 | 构造破坏检出、干净对误报、修复建议与耗时                  |
| B7 对齐       | alignbench                                 | named-destination 保留与单调配对；句级定位另测            |

`soak` 提供生产管线自检，`smoke` 提供合成免费链，`census` 审计载荷，`quality` 离线重评代理指标。`gullet`、`wrapfloat` 等专题验证特定机制；语料构建使用 corpus 家族。旧 errsweep 已退役。完整清单由 CLI 从源码生成，不手工复制。

## 验证分层

| 层           | 最小可见问题与入口                 | 时机                     |
| ------------ | ---------------------------------- | ------------------------ |
| L0 单元/断言 | pytest、fixtures 与合成输入        | 提交与 CI                |
| L1 机制覆盖  | parsebench 等语料机制测量          | 解析、归一化或机制变更后 |
| L2 子集回归  | 指定论文、层、seed 的目标 spec     | 定向修复与阶段变更后     |
| L3 全量集成  | 多阶段、多臂真实运行与 gate/triage | 需要总体证据时           |

问题应沉淀到能观察它的最低成本层；低层通过只证明该层语义，不能代替真实编译、翻译或浏览器验证。估时与成本按计划和现场测量，不由层名推断。`bench/TIERS.md` 只保留本节入口。

## 各类判分边界

B1 区分论文、文件和 chunk 分母；identity 的 strict、normalized 和 diverged 分开。泄漏正则只是代理，需保留实际片段人工归因。input 展平覆盖要排除本来未引用的文件。陷阱文件及编码字节不能格式化，新增真实机制应提取最小复现并写入共享断言矩阵。第三方库对照还需检查静默吞字，不能只比较异常次数。

B3 每格区分 paper、condition、engine 和 variant。baseline 是原文直编，中文条件经过归一化与注入；冷 TEXMF 与共享范围要说明。修复比较救回、未救回和回归，fires 不等于救回格数，缺少图片或宏包的有损载荷不能承担完整编译基线。

B4 硬契约与语义评分分开。质量臂采用 ESA esa2 错误标注与 stated/derived 分数，并可对争议项二裁；评审与被评模型解耦。模型、rubric、协议、样本和重试窗口属于实验条件，质量分不能替代确定性结构检查。评测型付费也须声明 dedup key 和预算。

B5 mock 使用产品管线与测试翻译臂验证机械组合，破坏臂必须在编译前可见。MockTranslator 只识别 ASCII prose 的已知限制可能高估非 ASCII 保真。real/eval 依次记录 route、xlat、compile、fixloop、base 和 layoutqc；上游失败、翻译完成、PDF 交付和无版面缺陷分别报告。`partial` 不自动等于应修复或应重译，判断须结合实际缺陷与阶段策略。

B6 在 ph/raw 层分别施加括号、数学、环境、引用、占位符和幻觉宏破坏，干净对同时作负控制。tree-sitter 采用相对源 baseline，原稿已有 grammar ERROR 不能直接归为译后新增。检测器必须有能拒绝的真实反例；建议修复也须验证不误改正常内容。

B7 同源重编译 PDF 的 named destination 可以比较，官方 PDF 与自编译 PDF 不可直接混用锚位。无 hyperref 是降级情形，缺少对侧真值不进入精确对齐分母。前端句级标记、错栏与点击度量见[定位契约](reader-alignment.md)，不能只用锚点保留率代替阅读体验。

## 账务与报告

spec 声明 items、stages、needs、status_class、mutates、code_deps 和付费键；kernel 负责锁、计划、执行、记账和收割。需要的上游终态由该 stage 的契约决定，通用状态词表仅作展示。失败事件可以包含 findings，不能用 errors 非空直接推断任务失败。

每份报告记录源码版本、冻结样本、配置、去重口径、排除项和分母。定向故障池与概率样本分开，核心层同时报告适当的分层加权与宏平均；区间方法与簇结构说明见[评测方法](../research/2026-10-16-评测方法.md)。

历史里程碑曾要求 identity≥99.5%、chunk 泄漏区间上界≤0.15%、已测破坏全检出与干净对零 error 误报、200 篇中文编译交付≥90%、有 hyperref 的锚点保留≥95%。这些是当时的目标，不是当前验收结果，也不是任意样本的服务承诺。新实验须在执行前确定目标、基线和否决条件；实际历史结果见[端到端评测](../research/2026-10-16-端到端评测.md)。
