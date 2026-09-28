# spec/ — 技术规范索引

实现的唯一事实源：与 `src/texlate/`（语料/bench 件与 `bench/`）代码现状对齐。发现与代码漂移以代码为准改本文；实测证据引 `research/` 对应件，不在本文复述实验过程。

| 文件                | 内容                                                                                                                                                        |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `architecture.md`   | 管线与模块架构：端到端管线图、包树与责任边界、数据契约（chunk/缓存键/产物面/事件）、部署形态与横切面                                                        |
| `arxiv-source.md`   | arXiv 获取层：端点与限速纪律、e-print 三态与版本语义、安全解包、主文件定位、钉版缓存、元数据与降级链                                                        |
| `arxiv-id-canon.md` | arXiv 标识符归一化（canon）契约：剥离序管线、新旧形规范与 strict_era 闸、`--`↔`/` 存储拼写归并、server/web/bench 三端薄壳口径；判例实证引 `research/arxiv/` |
| `latex-pipeline.md` | LaTeX 半解析 + 展开机：v2 Gullet+Segmenter 唯一解析路径、占位符族、回写与树扫描分流                                                                         |
| `translate.md`      | 翻译编排：xlat 调度/批量/重试阶梯/缓存口径/术语表/网关客户端、校验链消费点、归一化层                                                                        |
| `validate.md`       | 校验层：L0 规则表/L1 tree-sitter baseline 协议/L2 log 回灌、红线注册表、L2 归因 - 重译簇与 env judge、修复衔接                                              |
| `compile.md`        | 编译引擎与 fixloop：双引擎路由、沙箱/注入/判定、LaTeX 2.09 升级、yaml 修复引擎三件套与 16 分片规则库、vendor 资产、沉淀机制                                 |
| `corpus.md`         | 语料规范：评测底材各层口径、构建管线与治理（bench 侧磁盘现状对齐）                                                                                          |
| `benchmark.md`      | 评测套件规范：B1–B7 评测器矩阵与分层契约                                                                                                                    |
| `bench-trizone.md`  | bench 内核终态设计：trizone 三区账本（事件账唯一事实源 + 字节按再生成本分区 + fail-closed 付费裁决）；架构图 `assets/trizone-arch.svg`                      |
| `seqpos-decoder.md` | seqpos 解码层契约：双解码器 `_char_stream`、标记可信链、有界针配、行幅面栏判定、死区抑制、`_VERSION` 缓存纪律                                               |
