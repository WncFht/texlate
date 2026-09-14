# TeXlate

> 开源版「幻觉翻译」(hjfy.top): arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF, 双语对照阅读。

## 状态：调研规划完成，待开工

- [ADR-001 技术栈决策](docs/01-tech-stack-decision.md) — **Python 核心 + TS 前端 + tectonic 编译层**
- [架构设计](docs/02-architecture.md) — 半解析器 (区间替换) + 宏展开层 + 编译修复循环
- [路线图](docs/03-roadmap.md) — M0 基线 → M1 解析加固 → M2 编译修复 → M3 产品化

## 关键设计共识 (来自 hjfy 逆向 + ieeA 走读)

1. **LaTeX 是脚本语言** — 必须建宏表做受限展开，按名匹配的保护不可靠
2. **宁粗勿断** — 翻译管线要容错分割+byte-range splice, 不要严格 AST 重建
3. **LLM 看不到就不会错** — 公式/引用/宏全部占位符化，只翻段落级文本
4. **编译修复是壁垒** — log 解析→规则表→修复→重试循环，规则库社区众包
5. **译文缓存是产品壁垒** — arXiv ID 命中秒回

参考实现：`~/src/ieeA` (zcyisiee/ieeA), 只借鉴模式不搬代码。
