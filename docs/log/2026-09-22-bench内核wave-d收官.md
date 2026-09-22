> **结论**：trizone-ledger v2 bench 内核按 `docs/dev/bench-redesign-v2-trizone.md` 四波构建完毕（25 模块 / 约 15.1k 行），Wave-D 对抗验证两轮收口——首轮三车道裁决落 3 个修复提交，第二轮六车道复审 94 条发现全数裁决落 4 个修复提交；`tests/kernel/` 546 例通过 / 2 例按设计跳过。内核件面已齐，全量 bench 重建未启动、待放行。
> **状态**：已完成（构建 + 对抗验证收口；重建为后续阶段）
> **日期**：2026-09-22

## 构建回顾

`bench/py/kernel/` 自 2026-09-21 起按设计文档分波落地：Wave A 基础件（idnorm/locks/ledger/index/fsutil/cas，`0804c246`）；Wave B 分区件（vault/runs/lake/dedup/importer/exporter，`251d927b`）；Wave C 运行径（spec/ctx/paid/kernel、sweep/doctor、cli/specs，`205606d7`，另有 dedup 预修 `45123054`、`f431c4fd`）。Wave D 为本报告主题：多车道对抗评审 + 逐条裁决 + 回归测试钉案。

## 验证方法

评审以 workflow 对抗编排执行，每条发现须附最小复现（repro 脚本与 broot 沙箱留在 `tmp/` 下备查）。车道分两类：只读对抗 reviewer（ids/import/export/events、durability、paid path）与验证测试作者（契约测试 `tests/kernel/test_contracts.py` 25 例、集成测试 `tests/kernel/test_integration.py` 10 例——两轮产出合入测试库）。裁决原则：能复现的缺陷修代码并钉回归测试（`tests/kernel/test_adversarial_fixes.py` 为钉案专件）；判为设计内行为或不可复现者归档记录；修复经私有 index 提交协议逐车道落地，不污染他车道在飞工作。

## Round-2 发现分布

第二轮对修复后整树复审，汇总件 `tmp/jr_wf_7b0ace3b-589.txt` 共 94 条（13 fatal / 43 major / 30 minor / 8 note），按车道：

| 车道 | 总数 | fatal | major | minor | note |
| --- | --- | --- | --- | --- | --- |
| ids/import/export/events（A 面） | 27 | 3 | 13 | 8 | 3 |
| ids/import/export/events（B 面） | 21 | 2 | 11 | 6 | 2 |
| durability（封存/水位/cas/lake 竞态） | 18 | 3 | 7 | 7 | 1 |
| paid path（dedup/claims/locks/paid/kernel） | 18 | 3 | 9 | 6 | 0 |
| 契约测试作者 | 2 | 0 | 2 | 0 | 0 |
| 集成测试作者 | 8 | 2 | 1 | 3 | 2 |

## 裁决提交

| 提交 | 覆盖车道 | 要点 |
| --- | --- | --- |
| `76dc3341` | round-1 ids-import | 事件白名单全域化、redact 补漏（dict 键/顶层字段/quar id/auth 名）、canon 大小写与旧式尾号、export 字符集过滤、eval 车道接通 |
| `bb78edff` | round-1 paid/dedup | oracle 按 kind 裁决（altseq 感知+tombstone 通配）、harvest 全终态封存 mutates 树、paid_pool 强制 stage 过滤 |
| `147e6766` | round-1 paid-path | paid 格 records dedup 全让位 oracle、claim lease 中格不释、客户端私有化、dedup_key 重映射编译期拒 |
| `b7a7dd07` | round-2 paid-path | claims 表按 slot 复用分流（观察镜像 vs 生命周期）、claim 延迟释放灭再烧窗、probe 计配额、cell lock 移出工作树、oracle 封存追赶 |
| `c203c1e6` | round-2 durability | index 回放封存段（raw 优先、zst 须验证）、水位绑 inode 防轮转混叠、scanback 跨段、lake/cas 锁竞态、mtree 符号链接入验 |
| `56a13b12` | round-2 ids-import | minted canon 归一（混档/改名 archive 共享 idc）、事件按型别严校验、`$blob` 标记严形+sha 回验、`_safe_name` 单射编码、mint_run_seq 拒共享 shard |
| `5254b776` | round-2 seal-wiring | 封存机制曾悬空——读侧正确但无调用者；sweep 全 pass 接管 §3.10.5 双触发轮转 + `seal_gc(ingested=)` 水位腿（无 index 时宁留不删） |

## 代表性已修缺陷

export 侧 stage 名未过滤可经 `../` 或绝对路径把 records jsonl 写到导出树外（任写）；redact() 多层漏面使密钥形态串可残留进 events.jsonl/quarantine.jsonl；registry 未跟踪 tail 行可污染 `resolutions` 并覆盖人工裁决（错 cat → 付费额度烧错论文）；sqlite BLOB 等非 JSON 值使整批 import 崩死而非隔离；claim 槽位观察行与生命周期行混表导致各消费面互踩、中格释放开出"absent"再烧窗；index 不消费封存段、轮转后事件对投影永久不可见；mint 的 (kind,date,slug) 可复用致两 run 共享 shard。

## 延期与归档项

以下条目经裁决不阻收口：run 冻结间歇报告（复现失败，未证实）；单次 `dedup` 终态记录（未复现）；PAUSE 检查位裁决维持现状；promote 崩溃原子性（note-only 归档）；`idc_from_safe` 对非 canon 输入有损（latent——现存调用方均传 canon 形）。

## 收尾状态

`tests/kernel/` 546 通过 / 2 跳过（test_cli.py 两条后备路径守卫——真件落地后按设计停测）。zh-store 全程只读未触。内核对外契约面：`bench` CLI 全动词就位，run/spec/ctx/paid 径可驱动 stub 规格端到端（smoke spec 全链实证）。全量 bench 重建（语料注册、历史 import、vault 播种）是下一阶段，开工条件与顺序见设计文档末节。
