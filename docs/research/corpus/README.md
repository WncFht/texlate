# corpus 域索引

语料构建、渠道调研与画像的调研档案。现行层口径的唯一事实源是主仓 `bench/corpus_v3/MANIFEST.md`（2026-09-20 七库合一后 ~14,161 extracted 树 / ~54.9GB）；本域文件多为 2026-09-14 普查/设计时点口径，状态逐件标注在文件头。

## 现状与构建

| 文件 | 一句话内容 |
| --- | --- |
| `v3-plan.md` | corpus_v3 设计定稿：核心 1,000 概率样本 + 补强 ~200 agent 策展两桶、measure-then-sample、零在线 API、钉版与可发布子集（含 sizing 论证与管线 S0–S7） |
| `frame-and-allocation.md` | 3.16M 行分层 frame 建成与验证（新式覆盖 99.9994%）、year_band×cat_group/license 分层表、30 簇清单与配额口径、字段坑清单 |
| `ia-pilot.md` | IA arxiv-bulk pilot 实测：3,242 item/352 月无缺、~11MB/s、三态占比、zipsum==tar 序 offset 重建、Range 抽取逐字节核验 |
| `post2020-sourcing.md` | post-2020 渠道裁决：TIGER-5T byte-exact 实证（123/165 sha256 全同）为主源、scholarweave 有损定量（73% 文件丢弃、.tex 零丢失）只做文本层 |
| `2026-09-16-expand-layer.md` | expand 层 +3,800 落地记录：规模轴定位、故障率加权配额、QC 全过与 append 残留运维教训 |

## 渠道与数据集调研

| 文件 | 一句话内容 |
| --- | --- |
| `datasets.md` | arXiv 开放数据集全渠道普查：GCS 匿名可读实证、S3 requester-pays、OpenAlex/DataCite 免 key 通道、需求→渠道映射与中国可达性 |
| `hf-latex-datasets.md` | HF/Kaggle/Zenodo/IA LaTeX 源码数据集分级普查：A 级五家（scholarweave/TIGER/IA/Mithilss/KiteFishAI）+ B 级相邻资产 + 推荐组合 |
| `labels.md` | 分层键与真值标签源：snapshot 字段覆盖矩阵、license 词表（64.1 万可再分发）、LaTeXML severity 标签渠道、被引权重与撤稿弱标 |
| `arxmliv-unarxive.md` | arXMLiv/unarXive 深挖裁决：两家均无源码（HTML/JSONL 产物 + NDA/C-UDA/CC-BY 授权矩阵），unarXive 生成代码四件可借鉴 |

## 基线与画像

| 文件 | 一句话内容 |
| --- | --- |
| `parsebench-v1.md` | miniscanner 在 137 篇无偏语料上的基准：ok/identity 100%、leak 0.086% [0.05%,0.14%] Wilson、泄漏四机制归因（时点证据，解析器已换代） |
| `corpus39-profile.md` | 39 篇手挑语料机器画像：2.09×1、多主文件/wrapper+\jobname、\input 深度 4 无环、裸 \input×25、.svn 残留、MANIFEST 不一致金标准表 |
| `2026-09-15-parsebench-icc.md` | 月簇 ICC(1) 分析：管线指标簇效应≈0 → 逐篇 pooling 足够、分层保的是时代覆盖面 |
| `2026-09-19-iclr章节长度.md` | ICLR 2017–2026 accepted 章节长度管线：16,563 名单/5,297 映射/663 PDF 臂完成，2026-09-19 暂停快照（10 月续做） |

## 归入 methods/ 的两件

原 `docs/research/corpus/` 下两件已归入 `research/methods/`（域级方法学而非 corpus 私有，服务全部 bench 域）：

- `research/methods/parse-metrics-literature.md` — 解析/转换质量指标的学理口径（severity 分级、漏斗+归因、三档匹配、Wilson CI 惯例），被本域 parsebench-v1、v3-plan §7 引用。
- `research/methods/bench-construction-methods.md` — benchmark 语料构建方法学（20 个先例的抽样/规模论证/发布形态 + 统计方法菜单），被 v3-plan §2/§4 引用。
