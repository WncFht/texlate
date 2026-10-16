# 评测账本与资产契约

数据根由 `TEXLATE_BENCH_ROOT` 指定，默认 `~/.local/share/texlate-bench`，必须在 Git checkout 外。各区可由 `TEXLATE_{LEDGER,RUNS,VAULT,LAKE}_ROOT` 分卷。具体路径由 `kernel/paths.py` 定义，操作见[运行评测](../dev/bench.md)，理由见[存储决策](../../.agents/notes/implemented/architecture/2026-09-21-评测账本与资产.md)。

## 1. 分区与所有权

| 区域   | 内容与恢复性质                                                                            |
| ------ | ----------------------------------------------------------------------------------------- |
| ledger | events 热尾、sealed 段、seals 哈希链、运行登记和 seq 高水位；index.sqlite 为可重建投影    |
| runs   | 按 kind/date/slug 保存 spec、环境、invocations、冻结 plan、事件分片、报告与私有 work      |
| vault  | zh、splice、state 等付费字节、逐副本 meta 和 manifest；不能因可重新调用模型而称为免费缓存 |
| lake   | 免费源码载荷、CAS 对象、catalog、缓存与 durable 构建资产；durable 不参加普通载荷驱逐      |

run 日期按 UTC。manifest 与提名集留在代码仓，物化语料进入 lake。runs 的手写报告和翻译断点不是任意可删的临时件；产品 Web 任务的数据与去重不属于本内核的管理域。

## 2. 运行与互斥

### 2.1 计划与执行

spec 校验后冻结 items 和依赖计划，登记运行并取得 run 锁，再执行 cell、记账和收割。resume 复用原计划；重新枚举需要显式 replan。计划期去重不是首次付费请求前的最终裁决。

cell 在运行内按规范 ID 串行，跨 run 的付费互斥由 claim 锁承担。活 claim 不作为执行失败；缺失资产和 tombstone 不能被当作首次运行。计划、queued 和终态集合之间的账务关系由完成检查核对，不以 finished 标记代替逐格对账。

### 2.2 批跑与观测

`bench status` 查询索引，`bench/py/ops/status_panel/` 是只读看板。长批可 detach；子进程先取锁并回执后，父进程才退出。付费运行须给预算。旧 daily-soak 与 errsweep 自动化已退役。

### 2.3 定时维护

备份和巡检样例在 `scripts/systemd/`。需要脱离 checkout 存活的入口使用安装副本，更新时停止调度、排空写者、切换并重新加载 unit。`bench doctor --switch-ok` 只检查其实现覆盖的内核条件，不能证明所有外部进程和 unit 均已排空。

### 2.4 收割与恢复

sweep 处理失活运行、claim 和 pending 资产；不能因心跳过期单独认定进程已死，还需检查 run/cell 锁。失活运行的事件、付费字节与遗留工作树分别对账，收编账外字节不能自动删除唯一副本。

## 3. 持久化与付费不变量

### 3.1 事件与身份

事件包含 queued、started、cell 终态、claim、asset、tombstone、note、finished 及运行登记等类型，实际 schema 见 `kernel/events.py`。保留原始 `id` 与规范 `idc`；cell 身份区分 `idc/arm/up/variant/stage`，不能把重复实验挤进另一个字段。

规范 ID 在计划期解析并冻结；运行事件沿用冻结值，避免外部解析表变化使已付费结果丢账。异常原始拼写仍有审计价值。状态由 stage 自己的 status_class 分类，未分类不能默认为可重试；付费阶段的错误分类可能触发重复消费。

`errors` 是 findings 通道，clean 事件也可能有记录。`errors[0].cat=upstream` 同时影响归因与下游过滤，不可随意改义。`sig`、metrics 和落盘字段的冻结规则见[术语表](glossary.md)。

### 3.2 索引与顺序

事件先持久化再投影到 SQLite；投影失败标记 index dirty，付费裁决停止放行。索引重建和重封必须排除在飞写者，不能在 claim 暂时消失的窗口继续执行。

追加位置是历史顺序，run_seq/seq 用于身份和幂等。水位只到完整换行，不使用未完成行的文件大小。发生同键不同 payload 的冲突须报警并隔离，不能当作重复数据静默跳过。

### 3.3 追加与锁

ledger emit 是追加入口：持 ledger 锁、修复撕裂尾行、整行写入并 fsync，再在同一临界区写 run 事件分片。句柄不跨锁保留；复制账本或分片均不能独自证明资产已持久化。

锁文件不 unlink/rename 后重建，否则不同进程可持不同 inode。涉及活动追加文件的修复使用同锁下的原地协议，不能用替换路径使旧持有者继续写旧 inode。锁序为 run→cell→claim→叶锁；叶锁内不得反向阻塞取高层锁。

### 3.4 指纹与新鲜度

fp 由测具及声明依赖的源码内容、输入与有效参数组成，不能用 repo HEAD 或 dirty 状态替代。n、seed、jobs、layer 等选择旋钮不作为同一 cell 的语义参数。未获取输入可延后补输入指纹。

fp 不参与付费 done 判定，失配表示 stale；不能因为代码变化自动重新付费。模型、prompt、术语与上下文等缓存维度另按实际 key 契约维护。

### 3.5 vault 提交与回载

资产先进入 vault 同卷 staging，校验并落位，再写逐副本 meta 和 manifest，最后让事件与索引可见。pending 需要 reconcile，目录存在不构成已提交证据。meta 必须说明它自己的副本、状态与资产摘要；部分资产缺席按声明判断，不能假定每个副本都同时有 zh 和 splice。

恢复编译使用副本；硬链接共享 inode，写入或 chmod 会影响所有别名。可变工作树默认复制，禁止在只读 farm 上补写权限。pending 引用中的 staging 不得作为普通临时目录直接清除。

### 3.6 付费保护

去重裁决按 unsealed、claimed、verified、missing、absent 检查。unsealed/dirty 或证据分歧一律停止付费；claimed 等待其他写者；verified 复用；missing 进入 regen 闸；只有可信封存投影下无历史与字节证据的 absent 才可放行。顺序与字节证据规则以 `kernel/dedup.py` 为准。

claim 文件锁是真实互斥，表和事件提供审计；付费 slot 限制并发。stage.paid 与 gateway 构造路径共同检查付费边界，不能靠忘标付费绕过。`--max-cost` 是预算熔断，不能保证取消已在飞的上游请求。

`--regen` 需要明确 selector、预算和 yes，并进入 allow-regen 闸；普通重试或代码指纹变化没有该效力。认证失败按内核计数触发任务/运行熔断与共享哨兵，避免并发运行继续消耗；具体阈值与锁持有期由 `claims.py`、`paid.py` 和所属测试维护。

needs 只读当前 run、显式 foreign_runs 和可核验的 vault 证据。账有结果但字节丢失属于 upstream-lost，不得自动重排付费上游。

### 3.7 归一化与审计

workdir 从规范 ID 派生，文件系统 safe_id 不是论文 ID。旧式 archive 改名不能直接改写铸发标识；歧义数字尾需有可信来源裁决。triage 原始形匹配和 selector 的 id/idc 双谓词保留审计差异，读侧不能随意把所有输入再归一遍。

### 3.8 资产状态与阶段

有有效字节的 primary、alt 和 quarantine 可避免重译；quarantine 允许免费重编修复。缺字节的 quarantine 与 tombstone 属 missing 证据，须经 regen 闸。pending 不当作已验证字节，其在飞互斥仍由 claim 维护。译文完成和编译可交付按各自 stage 判定。

### 3.9 段缓存

缓存键包含原文、prompt、端点、模型、语言、术语和上下文等实际语义维度。写入前验证，不能将失败任务的状态文件冒充可复用译文。断点状态应受保护；收割到 vault 前不得因 work 瘦身丢弃。

### 3.10 容量、去重与生命周期

#### 3.10.1 容量与删除

容量帽是驱逐水位，免费语料按需水化；不能为了填满容量预拉全部留出集。分区余量和阈值以 `kernel/lake/` 与 doctor 实际配置为准，不把旧机器盘点当默认值。

`remove_cell_tree` 是工作格删除入口；有付费字节而无有效 vault 保护时必须 block。保留 receipt、诊断壳、已付费断点与 authored 报告。僵尸收割还需 run/cell 锁探测，活格不删。

#### 3.10.2 CAS 与物化

CAS 保存只读规范对象，extracted 为可重建投影。可变 zh/splice/build 树通过剥离只读 mode 的复制物化，不对硬链接 chmod。跨设备用复制并校验；EXDEV 不能退化为移动后删唯一源。

#### 3.10.3 lazy 生命周期

区分 skeleton、hydrating、hydrated、pinned、raw_only 和 failed。先驱逐 extracted 再考虑 raw；有损或特殊源的重建成本另记。水化使用独占锁、临时构建与原子发布，消费方不在共享锁里就地解包。目录、meta 与实际文件完整性都满足才可交付给付费 stage。

#### 3.10.4 校验与备份

vault 保持可直接读取的资产树，大文件可按摘要硬链接去重；同 inode 损坏会影响全部别名，verify 和修复按共享关系处理。逐副本 meta 和 manifest 的身份需包括 altseq，不能用一张凭证覆盖多个物理副本。

`bench backup` 与仓库备份脚本的最小 tar 主要保存元数据，不包含全部 vault 载荷。完整备份必须独立涵盖付费字节、ledger、durable 和必要的手写报告；恢复后核对摘要并重建投影。镜像任务退出成功不代表所有 meta、提升状态和数据都一致。部署方需有独立副本与恢复演练，不能从代码存在推断异地备份已配置。

#### 3.10.5 ledger 规模与封存

seq 铸号在事实源锁内，结合高水位与账本尾部恢复，不能从可弃索引或 runs 报表单独铸号。热尾轮换为封存段，seals 哈希链保留校验证据；具体轮换阈值由 ledger 常量管理。

删除 raw 封存段前须确认压缩件回验、宽限期与消费方水位。实现的 seal_gc 自身不覆盖全部外部水位条件，调用方仍需核验。大 metrics 的卸载数据也是账本可解释性的一部分，备份不能只留一个摘要而丢失所需 blob。

#### 3.10.6 fail-closed 裁决

付费闸结合索引世代/水位、dirty 标记、耐久 manifest/meta、冻结 paid_pool 与活 claim，索引只作可核验的投影。release verified 必须晚于资产与付费历史可见。证据不齐时停止付费并报告原因，不“修复”为 absent。

#### 3.10.7 ID 快照

计划与 resume 使用钉住的 resolver 快照；新 overrides 不改写旧计划。来源不明或多解的数字尾进入裁决队列。导入在边界处理坏 ID，已执行的 run 事件优先保存冻结身份并报警漂移。

#### 3.10.8 重建与上游失败

免费语料按密度选择成员获取或整包流扫，完成后按目录原子发布。返回 HTML 错页或不符魔数不能记为论文不存在。不同 bulk 渠道的图件、版本与可重建性分开，阈值和重试由相应 corpus spec 管理。

#### 3.10.9 进场对账

迁移前记录快照并排空写者；有字节无账则隔离收编，有账无字节则记 tombstone，缺资产按 meta 逐件核。历史脏目录只报告与收编，不自动删除；跨卷复制校验成功前保留原件。版本控制中的 manifest 不随载荷整体搬出仓库。

#### 3.10.10 验证缺口

IA/HF 限速、行组传输放大、水化吞吐、源再提取一致性、旧 ID 覆盖和大规模恢复都需现场实验。旧设计中的机器容量与排期不构成当前已验证承诺，历史经验见[评测存储经验](../research/2026-10-16-评测存储经验.md)。

## 4. 编写 spec

从可运行的 `bench/py/specs/smoke.py` 或领域相近 spec 开始。声明参数、items、stage、needs、status_class、mutates 与 code_deps；付费阶段额外声明 dedup key 和预算。items 的 ID、arm、up、variant 各有独立语义，不通过拼字符串绕过身份维度。

通过 ctx 获取工作区、上游记录、源与 gateway，锁、记账和收割交给内核。thread、process 和 async-owned 的事件循环、进程边界和上下文传播要求不同；修改执行器时使用相应契约测试。新增 spec 不能以声明齐全替代领域逻辑的分母和状态审计。

## 运行范围

内核采用单宿主文件锁，不支持 NFS 共享根或多机共同写账。付费再生成需要明确授权；保留策略不能覆盖未知所有权的资产。规范描述应保持与代码及测试一致，不因文档清理改变现有资产、锁或付费策略。
