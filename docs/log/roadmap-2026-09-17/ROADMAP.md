# TeXlate 现状报告与未来发展排期

> **结论**：现状报告与排期：管线实质可用（scorecard pdf 97.89%/clean 84.99%，real 臂 98.5% 与 mock 打平）；promo 死线、共享缓存分发层、测量失真是三大杠杆。
> **状态**：时点证据（2026-09-17 口径）
> **日期**：2026-09-17（2026-09-20 迁入重编）

> 2026-09-17 汇总文档。素材来源：`inputs/` 八轴只读侦察（frontend / architecture / docs-health / measurement / perf / defect-ledger / bench-expansion / product-gaps）+ `../overseer-2026-09-16.md` 车队台账 + 当日各波次实测。所有数字以 records/scorecard 实测为准；标记「在飞」的项以落笔时点状态计。

## 0. 一页结论

**现状**：管线已实质可用——5,117 格语料面 pdf 97.89%、clean 84.76%；real 臂 n200 实证 union pdf 98.5% 与 mock 臂打平；vendored-shim 机制单波把 492 格全 fail 面打到 73.2% clean，证明「机制归因→资产化→重跑」闭环已打通。产品面 hjfy 对标功能基本实装（含其未交付的 EPUB/DOCX 插译），G1 arxiv_html 三级取源链当日贯通。

**主要矛盾**（按对终目标「所有 arXiv 干净翻译」的杠杆排序）：

1. **real 臂证据窗口 ~29 天**（swe-2-medium promo 2026-10-16 到期，实测 40–72 格/h）——免费额度内能拿到的真模型回归面有限，须探针化优先打 hot/expand 缺口。
2. **xlat batch 协议是唯一成族缺陷窝**（P0 非锚定错配**已修** `164a9e0`——非锚定解析整体撤除；4 P1 同批核销）。
3. **测量面有四处失真**正在扭曲读数：scorecard union 名实不符、xlat dur_s 曾 99.6% 是排队（已修）、same-status sig 迁移不可见、taxonomy 物化零消费者。
4. **共享缓存只有本地 pack**——「1 万篇预译秒回」的分发层缺席，是终目标最省钱路径的缺口。
5. **网关翻译 = 单篇墙钟 96.8%**，server concurrency=3 vs 管线 10 是现成的 ~3× 旋钮（BYOK 限流语义待用户裁决）。

## 1. Phase A 战果快照（本日落笔时点）

### 1.1 波次

| 波                     | 规模                   | 结果                                                                                                | 状态                                                                                                               |
| ---------------------- | ---------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| C-bucket vendored-shim | 492 格（全 fail 起点） | **clean 360（73.2%）/ partial 127 / fail 5**；partial→clean 迁移 98；scorecard pdf +24 / clean +101 | 收线，records commit `1584851`；残面 postmortem 在飞（e8）                                                         |
| illegal_unit 深链      | 108 id                 | parse→xlat→compile→fixloop 全链重跑                                                                 | **108/108 闭环**：102 格 96c/6p/0f（`fff5578`）+ held6 ReDoS 修后直出 6 clean（`ddd7d7d`），零回归，unfixable 清零 |
| M1-B 判别波            | 72 格（T1 58+T2 14）   | `--stage deep` 全链                                                                                 | **72/72 收线：fixloop 终态 c53/p19/f0，end-state pdf 100%**（records `1d274bd`）；残余 19 格分簇路由 1d/peer1      |
| n200 real 臂           | 200 id                 | union pdf 197/200=98.5%，real≈mock（clean 150v153，fail 24v24），fixloop 救回 23/24                 | 已收线（昨日）                                                                                                     |

### 1.2 当日落地（节选）

- **vendored_fetch 机制全链**：23 件 off-CTAN 老期刊宏包资产入库（`fixloop/vendor/{files 10,stubs 13}`）+ 规则 @order 11.5 + `_post_install_verify`/`_relocate_doc_only`——「真凶不是 CTAN 缺件而是散件缺席」的定性翻转被 492 格实证。
- **dense-feedback 六点闭环**：dossier.py（per-id 失败链 join + 读侧 taxonomy 重分类 + --diff 跨 run 对账）、mech_ids.py（机制标签→id 集→rerun 管线）、rules.yaml `mechanisms:` 字段（39 规则已标）、taxonomy_cat 物化、verdict-proxy spec。
- **G1 arxiv_html 三级取源**：arxiv/html.py（40 真页 8956 块双射验证）+ worker emit 臂 + 前端 DomPane/source-select——LaTeXML 方案经 spike 否决（AUR/cpan/Docker 2.33GB 全劣）。
- **illegal_unit 修复**：尾参扫四补面 + count 尾种 + ~50 寄存器名 + argspec 多件（`d2c377b`，24/24 live 复现清零，全量 pytest 门收尾中）。
- **组成感知 verdict_sig**：judge 产 error_cats/error_pay，sig 在众数 cat 严格大于首错时改挂众数——1522 可重建单元 46.7% 重新分桶。
- **worker.py 4125 行拆包**：12 个 monkeypatch 缝 `_w.` 查名再导出；stagerun 拆 stage_* 包；env_flag/env_str 单源化收尾。
- **缺陷修复批**：fallback_verdict 裸编验证、D2 确定性重放（blake2s 计划下逃逸复检）、l2 chunk 归因落账、_MODELS_CACHE FIFO64、models 探测告警、health build 戳。

### 1.3 在飞清单（更新时点 ~20:30）

- 1d：ReDoS **已修** `746237f` + pytest 全量 3:46 翻案清零（4940 绿）；S9 env-arg 批（top8）在飞 → M1-B 残余 illegal_unit 4+syntax 3 已路由。
- 1e：batch-fix P0 **已落** `164a9e0`、html-title `083cded`、docs/08 `2006986`、env 规范化 `87e5c52`/`073c91b`；e2e-drift-fix（D2/D3/D7）在飞 → E2 repair/ 下沉已批排队。
- e8：postmortem `6b75761` + D1/D5/D8 `f0a4041` 已落；新批在飞：math--0408287 异常调查 + `_build_dual` zh 位英文 P1 + COMPILE_TIMEOUT 接线 P1。
- peer1：scan_install vendored 兜底 **已落** `1a74204`（穿透型缺件缝闭合+dep_fanout 闭包预装）；待命：M1-B stub 缺件 5 + 判据边界 3 + undefined_cs 48 格分解 + orphan 机制 11 件。
- 2f：illegal_unit 波 + held6 + M1-B 三波全收（clean 84.99%）；判别报告 `m1b-criteria-scout-2026-09-17/` 已交付。
- overseer fork 面：i5a `b2876d8`/i7 `7ac59c6`/export-pin `ea3402c` 已落；i5b（rundiff --deep+dossier taxonomy）+ sandbox-rlimits P1 + sharepack-500 P1 在飞。
- 4f：dense-feedback 用户 lane 已退出。

## 2. 关键数字

- **scorecard**（5,124 格）：pdf **97.89%** / clean **84.99%**（M1-B 后；fixloop:clean 归因 +51 / compile:clean −47 为末条归因迁移非质量位移；illegal_unit 波净 +14，集内 +82 被别线 csb stale/重跑 churn 对冲 68）。
- **墙钟分解**（records 实测）：xlat real 臂 ~24s/id inner、单篇 e2e 中位 77.7s **其中网关翻译占 96.8%**；compile 15.3s/id（xelatex 本体 94.7%，85% 行 2 passes）；fixloop 14s/行（4.55s/round × 均 2.09）；parse 2.1s。
- **real 臂吞吐**：conc20 实测 90s/格 ≈ 40–72 格/h；49-batch 论文 server 侧（conc=3）~260s vs 管线 conc=10 ~78s。
- **规模账**：corpus_v3 四层 5,133 篇（core 1000/booster 200/hot 133/expand 3800）；mechanisms.jsonl 144 条；frame.parquet 抽样宇宙 3,164,528 行。
- **资源**：磁盘 corpus 20G + work 28G + results 45G，卷余 363G；e-print 通道 180/日硬限（bulk 通道无瓶颈）。
- **缺陷账**：P0 **清零**（batch 非锚定错配已修 `164a9e0`）/ P1×22 / P2~43；另新增 `_WS_NOPAR` ReDoS 回归一条（在修）；今日核销 27+ 项。
- **代码量**：src ~51.8k 行 py（98 文件）+ web ~5.6k 行（26 源文件）；rules.yaml 70 规则 + 48 taxonomy。

## 3. 分面调研结论（八轴摘要）

**前端**（inputs/frontend.md）：26 文件 5.6k 行边界清晰；最大工程债 Reader.tsx 1005 行三合一；**真规模缝 = SSE 每任务一 EventSource 无界**（>6 在途撞浏览器 6 连接上限，批量预译必撞）；规格欠账：列表「继续」钮/`?status=` 过滤 UI/swapped 持久化/标题/默认视图/拖拽/暗色；首屏 1069KB 未拆包。

**架构**（inputs/architecture.md）：残余巨件 gullet 2794/builtins 2535/engine 1835；**compile↔fixloop 模块级 2-环**靠 5 处 lazy import 中和（任何提回顶层的顺手改动会引爆）；worker→e2e 私有名 import ×15（E2 倒置，已批下沉 repair/）；未收编双源五族（documentclass 6 站 3 方言/_DOC_BEGIN×3/env-flag×2/_INPUT×2/scan 分流×2）；rules.yaml 是增速第一（4797 行，头注计数已漂）。

**测量**（inputs/measurement.md）：records 五面字段语义盘清；**重大发现：metrics.taxonomy 物化后零消费**——dossier 仍自算（双口径风险）、triage 仍纯 sig；scorecard「union」名实不符（实现=末段胜非 best-of）；csb 校验是 status 字符串等值挡不住同态陈旧；scorecard 无 --json（status_panel 正则解析 stdout）；`code` stamp 只盯 src/texlate 对 bench/py 演进全盲。

**性能**（inputs/perf.md）：top5 = 网关延迟 96.8%（server conc=3→10 是 ~3× 旋钮）/ xelatex 体量（fail-path 可省 40–50%：单遍跳过+post-verify 去重）/ fixloop 白烧轮次（unfixable 437 行可前置预判）/ dur_s t0 伪影（**已修** `174790e`）/ scan 重复+StateStore O(n²)。并行余量：多任务 worker 池是吞吐最平杠杆。

**缺陷**（inputs/defect-ledger.md）：P0×1（batch 非锚定错配，在修）/ P1×22（代码面 6 + scout 面 16——**fixloop 规则面是最密归属 peer1 占 6**）/ P2~43；xlat batch 协议唯一成族窝；陈旧 pin 文档债 ×5 **已清**（`99a4189`）。

**bench 扩展**（inputs/bench-expansion.md）：fetch 非瓶颈（IA/TIGER bulk 零 arxiv 请求）；真约束 = real 臂吞吐+promo 死线 + 磁盘剪枝；覆盖缺口 = mech_tags 仅 booster 200 格、f 带（2026+）242k 未进样、pdf_only ~5% 不在框内；mock/real 终末指标已对齐（98.5% vs 98.5%）支持「mock 全量+real 滚动探针」设计。

**产品**（inputs/product-gaps.md）：hjfy 对标面大体实装（含超额项）；真缺口 = **共享缓存无远端分发**（index 拉取/HTTP serve/上传通道全缺）/ **匿名已译浏览结构性缺席**（mutation 强制 key+ 读面租户隔离）/ 管线全局串行+tasks 无分页 + 零 GC/TTL / 默认网关私网地址开箱即死 / 无反馈 + 换模型重翻通道 / 术语表只覆盖 cs 类目。

**docs 健康**（inputs/docs-health.md）：规则计数四处全漂（36/33/62/67 vs 实 70）；当日拆包灭 ~10 行号锚点；research 索引漏 6+ 件（refactor-audit 决策出处未登记）；上手断点：server extra 未写/run=mock 未声明/默认网关私网地址/SPA 需先 build-web/pre-commit 面向 macOS。

## 4. 排期建议

### 立即（本周，收线在飞 + 速赢）

| #   | 项                                                                                                                                                                                         | 归属               | 修价     | 依据                 |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------ | -------- | -------------------- |
| I1  | ~~illegal_unit 深波~~ 102 格**已收**（96c/6p/0f）；held6 ReDoS 修复补波（1d）→ M1-B 波（criteria 就绪：filtered 72，挂起等 ReDoS 修）                                                      | 1d→2f              | —        | 在飞                 |
| I2  | ~~batch.py P0 五钉修复~~ **已落 `164a9e0`**（非锚定解析撤除+@@ 泄漏闸）                                                                                                                    | 1e                 | M        | defect-ledger P0     |
| I3  | E2 分层倒置：~500 行 L2/env-judge 件下沉 repair/（保符号名、两侧改 import 源）+ D6 glossary 抽共享                                                                                         | 1e（batch-fix 后） | M        | 已裁决               |
| I4  | drift D 件修复（D1/D5/D8→e8 待 E2；D2/D3/D7→1e 在飞）                                                                                                                                      | e8/1e              | S-M each | drift-map            |
| I5  | measurement 速赢四件：fixloop rec 落 `rules_fired`+`post.regressed`、triage 接 `n_actions==0→ruleset_gap` 分流、rundiff `--deep` same-status churn、dossier 消费 `metrics.taxonomy` 替自算 | peer1              | S each   | measurement §6.2-6.4 |
| I6  | C-bucket 残面：5 fail 归因**已落** `6b75761`；orphan 机制立规评估（W31/W37/W49/W79/W102 等 11 件）+ vendored_fetch undefined_cs 触发缝评估                                                 | peer1              | —        | postmortem+mechmap   |
| I7  | ~~`_ERR_FILELINE_RE` 文件名面收紧~~ **已落 `7ac59c6`**（共享 `_ERR_FNAME` 单源四面；strict-xfail 全仓清零）                                                                                | compile/fixloop    | S-M      | defect-ledger P1     |

### 短期（1–2 周）

| #   | 项                                                                                                                                                                         | 修价             | 依据                           |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------------------------------ |
| S1  | **real 臂滚动探针赶 promo 死线**：每波分层抽 n≈200–300（hot/expand 加权），10-16 前把 real 覆盖缺口层跑完；post-promo 预案切备用内部网关 或注册源                       | 0.5d 设计 + 排产 | bench-expansion #5，**硬约束** |
| S2  | scorecard 口径修齐：end-state 正名/best-of 并列、csb 校验升级记录指纹、floor_restored+degraded 数进输出、补 `--json` 替 status_panel 正则                                  | M                | measurement §6.1               |
| S3  | P1 清账批：22 条按归属分派（peer1 fixloop 6 件最重：graphic_repair 三缺口/CJK 缺字路由/救援物自炸/accent 缺字；1d illegal_unit 残余+macro 截断；server/share/worker 各件） | S-L each         | defect-ledger §2.1             |
| S4  | 吞吐旋钮两件：server `concurrency` 3→10（**需用户裁决 BYOK 限流语义**）+ xelatex 无 ref/toc delta 单遍跳过+fixloop post-verify 去重（fail-path −40~50% 引擎秒）            | S / M            | perf #1#2                      |
| S5  | 质量面代理指标回填（leak/term_hit/landmark_density 三件套纯后算 + term_dict.json 一行接线；先 metrics 观测位不进 verdict）                                                 | <1d+1.5h 算      | bench-expansion #2             |
| S6  | base 臂补跑（compile --arm base 全量 → build-base 覆盖 0→全，解锁 alignment_pairs + 源健康基线）                                                                           | ~1.5h 算         | bench-expansion #3             |
| S7  | R3 词法常量层+warning 注册表+capabilities 段处置 + 计数生成化（防已付两次代价的漂移类）                                                                                    | ~0.5d            | architecture R3                |
| S8  | docs-health 三件：入口数字面清零（改指生成源）+research 索引补登+SUPERSEDED 约定成文                                                                                       | ~0.5d            | docs-health §5                 |
| S9  | envarg-scout 19 候选 env argspec 波（varwidth/lrbox/numcases/turn/rotate/boxedminipage/listing/floatingfigure top8）                                                       | S                | 1d 交付物                      |

### 中期（月度）

| #   | 项                                                                                                                                                                             | 修价       | 依据                             |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- | -------------------------------- |
| M1  | **共享缓存分发层**：index.jsonl 远端拉取 + 共享包 HTTP fetch+ 可选公共 registry 端点（静态托管即可）——「1 万篇预译秒回」的 hjfy 对等武器，BYOK 下唯一摊薄社区 token 成本的结构 | 3–5d       | product-gaps #1                  |
| M2  | **批量承载底板**：tasks 分页+status 过滤接线+SSE 收敛/聚合流（消 >6 在途假死）+retention/GC（settings.retention_days+`texlate gc`）+translation_cache LRU——预译灌库前置        | 2–4d       | product-gaps #2 + frontend #1    |
| M3  | 首启可用 + 公网分发收口：默认 base_url 改中性值 + 未配置引导、providers 免费档说明、systemd/compose 样例、`texlate:full` tag 转正、CLI `run --live` 真翻入口                   | 1–3d       | product-gaps #3 + docs-health §3 |
| M4  | R1：compile/engine.py 四关注点拆分 + 掐断 fixloop↔engine 环（log 原语下移 texlog）                                                                                             | ~1d        | architecture R1                  |
| M5  | R2：e2e 共享件扶正余量（_scan_tree/env 表归正层，顺手并 worker/parse 双实现）                                                                                                  | ~1d        | architecture R2                  |
| M6  | mech_tags 全层回填（features.jsonl 沉淀+evidence 改可执行检测器 → 5133 格全标；机制级 burn-down 图随之解锁）                                                                   | 1–2d       | bench-expansion #4               |
| M7  | 领域术语表扩面（cs-only → math/physics/hep/cond-mat/q-bio；LaTeXTrans 外需新源）                                                                                               | 1d+ 内容活 | product-gaps #5                  |
| M8  | 反馈 + 换模型重翻闭环（POST feedback 端点+Reader 重翻钮=新建预填 model）                                                                                                       | 1–2d       | product-gaps #4                  |
| M9  | f 带（2026+）进样+hot 层补齐 27 缺口+pdf_only 类登记（~5% arXiv 无源稿产品会遇到）                                                                                             | 1d         | bench-expansion §1.3             |
| M10 | 50k 扩展前置：work 树剪枝/归档纪律（clean 格只留 records）+ 波次 runbook 更新                                                                                                  | 0.5d 纪律  | bench-expansion §2.3             |

### 远期/战略（季度，形态决策先行）

- **匿名已译浏览/公共实例**：hjfy「已译随便看」与 BYOK 本地优先的形态分叉——做不做公开托管实例是产品路线决策（影响租户模型/配额窗/成本预算器）。
- **多任务 worker 池 + Redis 队列**：吞吐最平杠杆，但依赖存储/并发模型裁决（m3gap G2 pending）。
- **前端打磨包**：暗色主题、Reader 拆分（1005→~500）、路由级 lazy 拆包、拖拽上传/示例论文。
- **fixloop 规则库治理**：rules.yaml ~100 规则时 taxonomy/rules 文件级拆分+builtins 按域拆包（审计裁决维持）。
- **e2e↔stagerun records 双 schema 家族收编**：triage LEGACY_ARM_MAP 续命中，长宜统一。
- **桌面端/M4**：Electron 形态未启动。

## 5. 硬约束与风险

| 约束                    | 数值/死线                     | 应对                                                                    |
| ----------------------- | ----------------------------- | ----------------------------------------------------------------------- |
| swe-2-medium promo 到期 | **2026-10-16（剩 ~29 天）**   | S1 滚动探针优先打 hot/expand real 缺口；备用内部网关+ 注册源预案 |
| 上游网关账号级 429        | 限流非本地可控                | retry 阶梯空转即正确姿势；降并发无用                                    |
| 磁盘                    | 卷余 363G/917G；50k 需 ~185G+ | M10 剪枝纪律先行                                                        |
| arxiv e-print           | 180/日硬限+429 park 翻倍      | hot/版本敏感增补走 bulk 之外唯一受限通道，排产按日切片                  |
| 单点网关                | 私有内网 单地址           | M3 中性默认+failover 链；docs 面首启引导                                |
| real↔mock 口径断点      | a08dda3 前后体积类指标不可比  | 跨波对比按 commit 切段（bench-expansion §3.1）                          |
| pytest 门时长           | 全量 50min+（争用下）         | 波次期定向证据先行、全量后台确认（本次已实操）                          |

## 6. 建议的下一波行动（给用户的决策点）

1. **是否授权 server concurrency 3→10**（BYOK 下 ~3× 提速；风险是用户自付 token 的网关限流面）。
2. **promo 死线前排产**：S1 滚动探针的抽样配额（建议 hot/expand 加权、每波 n≈200–300）。
3. **共享缓存公共 registry 是否立项**（M1 的 §0 形态——静态托管即够，但意味着公开分发已译语料的姿态）。
4. **匿名浏览/公共实例**路线表态（远期分叉，现在只需「暂不」或「调研」两字）。
5. 默认 base_url 改中性值的公关级决定（影响对外发布形态，与 M3 绑定）。

## 7. 附件索引

- `inputs/frontend.md` — 前端面（SSE 缝/规格欠账/三建议）
- `inputs/architecture.md` — 架构面（模块图/残余债/R1–R3）
- `inputs/measurement.md` — 测量面（verdict 五面/判分盲区/scorecard 口径/五改进）
- `inputs/perf.md` — 性能面（墙钟分解/top5 热点/并行余量）
- `inputs/defect-ledger.md` — 缺陷总账（P0×1/P1×22/P2~43/核销表）
- `inputs/bench-expansion.md` — bench 扩展（语料四层/规模账/五建议）
- `inputs/product-gaps.md` — 产品面（hjfy 对账/运维差距/五建议）
- `inputs/docs-health.md` — 文档健康（漂移清单/上手断点/三建议）
- `../overseer-2026-09-16.md` — 车队台账（决策与落地逐条）
- `tmp/drift-scout/drift-map.md` — e2e↔worker 漂移图（8 项）
- `bench/results/mechmap-2026-09-17/` — 规则×机制全量映射（37 映射/11 孤儿）
