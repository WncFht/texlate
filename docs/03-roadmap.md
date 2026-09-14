# 路线图

## Milestone 0 — 基线与骨架 (第 1-2 周)

目标：端到端跑通"能翻出来"的最小链路，建立度量基线。

- [ ] uv 项目骨架 + CLI (`texlate translate <arxiv-id>`)
- [ ] arXiv 下载器 (e-print, 限速 + 重试+tar 过滤 + 单文件兼容)
- [ ] LaTeX 半解析器 v0: 段落提取 + 核心保护 (数学/cite/ref/url/作者块/verbatim) + 占位符 + 区间重建
- [ ] 翻译编排 v0: OpenAI 兼容 provider + 批量/单条 + 重试降级
- [ ] 编译 v0: tectonic 子进程 + ctex 注入
- [ ] **黄金语料集**: 20 篇真实 arXiv 源码 (覆盖 amsart/REVTeX/IEEEtran/自定义宏/多文件), 每环节成功率基线

验收：20 篇语料端到端成功率 ≥60% (hjfy 说开源同类 <60%, 先追平)

## Milestone 1 — 解析器加固 (第 3-5 周)

- [ ] 宏展开层 (宏表建 + 受限展开 + 递归保护)
- [ ] 保护清单补全：natbib 全族/\section[opt]/全数学环境族/\footnote/\subcaption
- [ ] 校验器：brace token-diff + cite/ref key diff + math env 配对 + 占位符修复 (Levenshtein)
- [ ] 校验失败 → 重译/回退策略接线
- [ ] 上下文窗口 + 术语表自动提取 v0
- [ ] 语料扩到 100 篇，成功率 ≥85%

## Milestone 2 — 编译修复循环 (第 6-8 周，差异化攻坚)

- [ ] LaTeX log 解析器 (错误定位/包冲突识别)
- [ ] 修复规则表 (yaml, 社区可贡献): 包冲突替换/字体声明改写/命令缺失注入
- [ ] LLM 修复器 (log+ 源文件上下文 → 最小 patch)
- [ ] 修复案例沉淀机制 (每次成功修复自动记录 pattern)
- [ ] 语料 200 篇，编译成功率 ≥90% (hjfy 水平 ~95%)

## Milestone 3 — 产品化 (第 9-12 周)

- [ ] FastAPI 服务 + SSE 逐段流式 + SQLite 队列
- [ ] Web 双语对照阅读器 (pdfslick 双栏同步滚动)
- [ ] 译文缓存层 (arXiv ID+ 版本 + 模型 命中秒回)
- [ ] EPUB/DOCX 翻译 (DOM 插译模式)
- [ ] PDF 过渡方案：MinerU HTTP API → md 对照
- [ ] Docker 一体化镜像

## Milestone 4+ — 远期

- [ ] BabelDOC sidecar (同页双语 PDF 导出，AGPL 隔离)
- [ ] 高引论文批量预译 (S3 bulk + 引用排序)
- [ ] BYOK 桌面版 (Electron + PyInstaller, 抄 texglot 答案)
- [ ] 更多目标语言 (日/韩/…)

## 对标与差异化

| | hjfy.top | texlate |
| --- | --- | --- |
| 开源 | ❌ | ✅ Apache-2.0 |
| 模型 | qwen-turbo/doubao-lite 固定 | BYOK 任意 OpenAI 兼容 |
| 编译修复 | 人肉固化 (黑盒) | 规则库众包 + LLM 自动修 (白盒) |
| 译文缓存 | 1 万篇预译 | 社区共享缓存 + 本地缓存 |
| PDF 指令级 | 开发中 | BabelDOC sidecar (现成) |
| 价格 | 内测免费→将收费 | 永远免费 (自付 LLM 成本) |
