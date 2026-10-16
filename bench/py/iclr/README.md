# ICLR 章节长度研究

本目录为独立研究工具，不属于 TeXlate 产品使用文档。目标为 ICLR 2017–2026 accepted 论文的章节词数分布，按年份与 track 分层；研究于 2026-09-19 暂停。下述状态是历史快照，恢复前必须重新核对实际资产。

## 历史进度与丢失材料

accepted 名单曾导出 16,563 篇，映射确认 5,297 个 arXiv id；PDF 切分曾记录 663/663 成功，LaTeX 臂当时 25 篇。随后旧工作区清理导致 accepted/map/fetch 等台账丢失，旧文档一度仍错误声称 active。不能按历史数字认定这些结果仍完整可用。

恢复时先核对全局 paper-search 的 OpenReview 缓存、现有 corpus manifest 和实验 lake，重新导出 accepted 清单；缺失的映射需重跑，而不是猜测 id。旧 `sections_pdf.jsonl` 可在对应 PDF 仍存在时重建。不要对旧 `bench/work_*`、`corpus_iclr_pdf` 路径直接启动下载，载荷现由仓外存储管理。

## 工具与方法

本目录包含映射、获取、章节切分和统计模块，实际参数查询各模块 help。映射按缓存、标题归一匹配与 S2 仲裁分层；外部 API 拒绝或空结果不作为永久 no-arxiv 结论。OpenReview 旧/新 API 按论文代际处理，认证不跨域复用。

切分先做 `pdftotext -layout`，处理字距标题、编号顺序与附录边界，再归入 canonical bucket。`1 I NTRODUCTION` 不能误判为附录字母；标题与编号分行时也不能盲拼。统计以 LaTeX 优先、PDF 兜底，并需保留双臂校准与缺失率。

## 恢复条件

恢复前建立受版本管理的轻量样本清单、持久映射账与独立备份，再估算 API 成本和磁盘。原研究的产物不因未调用 LLM 就可免费重建；论文映射包含已消费的外部查询工作。研究是否继续由任务授权决定，不随产品文档重构自动恢复。
