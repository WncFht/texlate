# TeXlate

> 开源版「幻觉翻译」(hjfy.top): arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF, 双语对照阅读。

## 状态：M0 实施中

- [ADR-001 技术栈决策](docs/01-tech-stack-decision.md) — **Python 核心 + TS 前端 + tectonic 编译层**
- [架构设计](docs/02-architecture.md) — 半解析器 (区间替换) + 宏展开层 + 编译修复循环
- [路线图](docs/03-roadmap.md) — M0 基线 → M1 解析加固 → M2 编译修复 → M3 产品化

已落 `src/texlate/`（uv 管理，`uv sync` 后 `uv run pytest tests/` 全绿）：

| 包                 | 内容                                                              | 验证                                                                |
| ------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------- |
| `arxiv/`           | e-print 获取/解包/主文件定位/限速                                 | 189 tests + corpus39/实网 gated 用例                                |
| `latex/`           | 半解析 + 展平 + splice（miniscanner 重写）                        | corpus_v3 1955 文件 identity 100%、leak 0.04%、fixtures 54 断言全绿 |
| `xlat/`            | 编排层 + 3003 网关客户端（动态免费模型发现/重试/状态续翻/术语表） | 121 tests + MockTranslator E2E                                      |
| `validate/`        | L0 规则校验（7 规则）/ L1 tree-sitter / L2 编译日志               | validbench corpus_v2 7867 用例：破坏 100% 检出 / 0 error-FP         |
| `compile/`         | Engine 协议 (xelatex+tectonic) / ctex 注入 / normalize / 沙箱     | corpus39 mock-E2E：pipe-xel 13/39（base-xel 12/39，注入无损）       |
| `compile/fixloop/` | yaml 规则修复引擎（25 规则全移植）                                | spike 规则等价移植 + 单测                                           |

Benchmark 底材：corpus39（陷阱）+ corpus_v2（137 篇）+ corpus_v3（1000 篇核心随机层 + 200 篇 agent 策展补强层已落盘——机制台账 `mechanisms.jsonl` 143 条，选择器 `select_booster.py`，管线 `build_corpus_v3.py` 可重建）。评测器已扶正：parsebench v2（B1）/ fixtures 断言（B2，tests/test_bench_regression.py）/ validbench（B6）。规格见 `docs/06–10`。

## 关键设计共识 (来自 hjfy 逆向 + ieeA 走读)

1. **LaTeX 是脚本语言** — 必须建宏表做受限展开，按名匹配的保护不可靠
2. **宁粗勿断** — 翻译管线要容错分割+byte-range splice, 不要严格 AST 重建
3. **LLM 看不到就不会错** — 公式/引用/宏全部占位符化，只翻段落级文本
4. **编译修复是壁垒** — log 解析→规则表→修复→重试循环，规则库社区众包
5. **译文缓存是产品壁垒** — arXiv ID 命中秒回

参考实现：`~/src/ieeA` (zcyisiee/ieeA), 只借鉴模式不搬代码。
