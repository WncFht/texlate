# ADR-0019 否决登记：被否方案与缓议项总表

> **状态**：现行（登记制——条目只增不改，翻案走新 ADR 并回链）
> **日期**：2026-09-15（初表随 05 冻结）| 更新 2026-09-18（Electron/公共 registry 否决）、2026-09-19（规模化路线重估）

## 上下文

选型期的否决理由散在各 bench 报告与裁决注记里，容易随时间丢失语境——「为什么不直接用 X」是每个后来者最先问的问题。此篇把全部否决/缓议决策集中到一处登记；每条给出否决理由与对位的生效裁决。条目分三级：**否决**（有证据的排除）、**暂缓**（方向不排除、本里程碑不做）、**未决**（已识别决策点）。

## 否决

| 方案 | 否决理由 | 对位裁决 |
| --- | --- | --- |
| 全 TypeScript 技术栈 | LaTeX 工具链/bench harness/网关 SDK 面 Python 生态压倒性；TS 只在阅读器前端成立 | ADR-0001 |
| 全 Python（含前端模板渲染） | 双 pane 锚点同步/高频滚动负载需要真前端；服务端模板撑不起 | ADR-0001/0016 |
| Go/Rust 重写核心 | 宏展开/修复规则是快速生长面，Python 迭代速度优先；无性能瓶颈证据 | ADR-0001 |
| pylatexenc / TexSoup / plasTeX / latex-utensils / unified-latex 作主解析器 | 选型 bench 全部出局：pylatexenc 语义偏离与维护停滞、TexSoup 容错但丢字节、plasTeX 全求值器路线（见下）、JS 系库与 Python 管线跨语言 | ADR-0002 |
| AST round-trip 管线 | LaTeX 无良定义 AST；serialize 保不住逐字节（注释/空白/怪语法即语义） | ADR-0002 |
| plasTeX 真 .sty 加载展开 | 加载即执行任意 LaTeX——慢、脆、安全面大；半解析+受控展开覆盖已实证 | ADR-0002/0003 |
| catcode 表 / `\halign` / active chars / 完整 TeX 求值器 | 覆盖收益对复杂度不划算；资源限额 + 结构化 `\if` 已兜住真实语料 | ADR-0003 |
| 两遍展开（先收集定义再展开） | 定义可被条件/使用点动态改写；单遍即序展开是语义正确序 | ADR-0003 |
| litellm 统一模型层 | 多一层参数透传坑（babeldoc `temperature=0` 被网关 400 实证）；双 SDK 直连更可控 | ADR-0011 |
| huey/Redis 任务队列 @M0 | 单机个位数并发无此问题；SQLite WAL + asyncio.Queue 足够，`REDIS_URL` 留槽 | ADR-0015 |
| EbookLib 生成 EPUB | AGPL 传染；EPUB 手写成本百行级 | ADR-0018 |
| MinerU OCR→md 重构译 PDF | 版面重排质量对论文是倒退；BabelDOC 布局保留路线占优 | ADR-0017 |
| BabelDOC in-process 调用 | AGPL 进程内链接 + torch/onnx 依赖冲突面；spawn-CLI 双隔离 | ADR-0017 |
| 自建 LaTeXML（arXiv HTML 自给） | 09-17 spike 三路全劣：系统包太旧 / cpan 安装脆弱 / Docker 镜像巨型；直取 arXiv 官方 HTML | ADR-0008 |
| Electron 桌面壳（2026-09-18） | 单机 web 已覆盖全部形态；打包/签名/更新链是纯成本无收益 | — |
| 公共共享缓存 registry + 已译浏览实例（2026-09-18） | 需要持续运营面（审核/滥用/成本）；M1 不做公共实例与匿名浏览，share 协议保留自托管形态 | ADR-0012 |
| server 无 key 回退默认网关 | 静默消耗他人配额是安全洞；server 模式显式 needs_auth | ADR-0015 |
| 批量非锚定译文解析 | 译文静默错配通道；09-17 P0 整体撤除，`@@` 泄漏闸兜底 | ADR-0010 |
| `retry{model}` 原地重试 | 模型进 dedup 键材料，原地重试毒化 dedup 面；改判「新建任务」（m3gap） | ADR-0015 |
| arxmliv/unarXive 作评测语料源 | LaTeXML 转换产物非原始 e-print（丢了排版/宏坑真实性）；语料只要钉版原始源码 | ADR-0013 |
| 语料横向扩面（更大均匀层，2026-09-18） | 均匀层边际覆盖递减；改纵深——mech_tags 回填、real 滚动探针、机制归因 | ADR-0013/0014 |
| `swe-1-7`/`swe-1-7-medium` 进翻译池 | 丢命令/BIBITEM 契约史 + reasoning 爆炸；denylist 钉死 | ADR-0011 |
| 任务级 dedup 复用 partial | partial 毒传播实证；只复用 done，`prefer=fresh` 显式绕过 | ADR-0012/0015 |

## 暂缓

| 方案 | 暂缓理由 | 复评条件 |
| --- | --- | --- |
| 公共实例/匿名浏览 | 同 registry 否决——运营面成本；share 协议设计上不挡这条路 | 有运维承诺与滥用治理方案时 |
| 段级共享缓存 | 单段译文无法本地 compile 验证语义，信任模型弱一档 | 段级验证手段出现时 |
| MinerU 作 OCR 兜底槽 | PDF 直译末级已由 BabelDOC 占；扫描版论文才需要 OCR | pdf_only 中扫描件占比实证升高时 |
| 多实例/分布式 worker | 单机负载未到；`REDIS_URL` 槽位与 store 抽象不挡此路 | 自托管多写者需求出现时 |
| 内容签名/贡献者信誉 | v1 信任模型靠消费端重跑，不需要身份担保 | 「可信贡献者快速通道」需求出现时 |
| 全文级术语一致性 + judge 低分重翻 | qualbench 停在冒烟规模，质量基线未建 | qualbench 扩产、质量分布可见后 |

## 未决

| 决策点 | 语境 | 候选 |
| --- | --- | --- |
| S3 requester-pays 批量通道 | 2501+ 段「无损含图+规模」唯一解；约 $80 三年窗/~$150 十年/全量 $260–400 | 付费开通道 / 同区 EC2 免 egress 自跑 ETL / 维持 e-print 慢速 |
| 对外发布默认 base_url | 主仓预置内部网关地址；公开发布形态需中性默认值 | 发布前裁决 |
| 发版载体 | Electron 已否；剩余 web 自托管 / CLI / 库三种形态 | 随 M 验收定 |
