# ADR-0008 arXiv 获取层：e-print 主通道 + 限速解包安全 + 三级降级链

> **状态**：现行
> **日期**：2026-09-15（05 裁决 19 + arxiv-layer 规格）| 更新 2026-09-17（mtree 多列化、G1 html 链落地）

## 上下文

arXiv e-print 实测三态：84.6% tar.gz（中位 7 文件、max 80）、15.4% 单 tex.gz、13.3% 只有 PDF。服务端限流真实存在（429 惩罚窗口 ≥3min，原地重试是浪费），tar 解包要面对路径穿越/链接攻击/炸弹，主文件定位有 1.6% 难例（X-raying 60 万篇口径），版本语义（`vN` 精确 vs latest）与缓存键需要钉死。

## 裁决

- **取源**：`arxiv.org/e-print/{id}` 主通道；每个 GET 前先 `HEAD /src/{id}`——content-disposition 白拿 resolved_version + 格式、content-length 上限、etag 重验证。
- **限速**：`arxiv.org`、`export.arxiv.org` 与 `oaipmh.arxiv.org` 端点分桶、各自 ≥3.05s 全局间隔、零并发、UA 强制带联系信息；单请求 429/406/5xx → +10/30/90s jitter；同 (host, path-class) 桶连续 2 次 429/406/403 → park 30min 起步、翻倍封顶 2h、±20% jitter，checkpoint 落盘可恢复。
- **解包**：魔数三态嗅探（`1f8b`→gunzip→ustar 嗅探 / `%PDF`→sidecar / 其他→人工）；逐成员路径安全（`..`/绝对路径/link/setuid 拒、大小写折叠冲突检测、大小与成员数上限）；`mtree.txt` 多列 TSV（path/size/sha256/kind/链接目标/stub）每包一份 + 别名落点对账（经 kept symlink 祖先写穿的成员按赢家实况记账）。
- **主文件定位**：剥注释匹配 `\documentclass|\documentstyle` → `\begin{document}` 优先 → `\input` 拓扑图根 → 文件名先验 → 多根标 `multi_doc` → 零候选走降级。
- **元数据**：export Atom `id_list` 批量（≤200/次、URL ≤8KB 分批）（未落地：产品层仅单篇 `_atom_meta`，批量属语料管线/远期设计，见 spec `arxiv-source.md` §3.1）；primary_category 喂术语表映射；resolved_version 陈旧检测。
- **版本与缓存键**：`id@vN` 精确命中、无版本 resolve 最新；源级缓存键 `arxiv_id@resolved_version`。
- **降级链**：e-print（~87%）→ arXiv HTML 最新版（LaTeXML DOM 分块异构翻译，救「我们解析器崩了」，覆盖率=源码不新增）→ BabelDOC PDF sidecar（无源码 ~13%）。

## 理由

- E14：覆盖基线、限速惩罚、S3 成本模型全部实测；macOS bsdtar 把单文件 gzipped tex 误识为 mtree → 用 gunzip 不用 tar。
- HTML 是异构降级而非替代（LaTeXML 从源码生成，救不了 PDF 直投）；不自建 LaTeXML——09-17 spike 否决（系统包/cpan/Docker 三路全劣），直取 arXiv 官方 HTML。
- 证据：主仓 `docs/05` E14；调研档案 `research/arxiv/layer.md`、`research/arxiv/probes.md`、`research/arxiv/html-path.md`、`research/arxiv/pdf-fidelity.md`。

## 演变

- 2026-09-17：mtree 单文件清单改多列 TSV + 别名落点对账；G1 `options.source=html` 三级取源链落地（`arxiv/html.py` 真页块级双射、worker `arxiv_html` 任务臂、前端 DomPane）——降级链第二级从预留变实装。
- 2026-09-19：枚举/增量职责上收——frame.parquet 抽样框 + OAI-PMH 日增量对账归入批量渠道（ADR-0009）；pdf_only 层列入物化计划。

## 现状

实现落在 `arxiv/` 包：`fetch.py`（HEAD 预检 + 退避 + etag）、`ratelimit.py`（per-host 桶 + path-class 断路器 + 日预算）、`sniff.py`（魔数三态）、`unpack.py`（安全解包 + mtree 对账）、`locate.py`（主文件裁决 + 8 形态 `\input` 拓扑，严格超集 latexpand 与 unarXive flatten）、`meta.py`（Atom + OAI-PMH GetRecord）、`cache.py`（钉版源缓存）、`html.py`（arXiv HTML 链）。恶意 tar 向量与限速窗口均有测试/bench 实证。
