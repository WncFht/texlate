# TeXlate

> 开源版「幻觉翻译」(hjfy.top): arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF, 双语对照阅读。

## 安装与运行

```bash
uv tool install 'texlate[server]'   # web 形态（含 SPA）；纯 CLI 可去 [server]
texlate web                          # http://127.0.0.1:8765，BYOK 在 Settings 页配网关
texlate run 1706.03762               # 或 CLI 直跑整链 → 双语 PDF
```

`uv tool install git+…` 是 CLI-only 路径（`server/static/` 为构建产物未入库，SPA 缺席时 API 仍可用）。容器形态见 `Dockerfile`（`docker build -t texlate .` 需 buildx；代理宿主加 `--network=host`）。开发形态：`uv sync && uv run pytest tests/`。

## 状态：M0 已验收，M1–M3 推进中

- [ADR-001 技术栈决策](docs/01-tech-stack-decision.md) — **Python 核心 + TS 前端 + tectonic 编译层**
- [架构设计](docs/02-architecture.md) — 半解析器 (区间替换) + 宏展开层 + 编译修复循环
- [路线图](docs/03-roadmap.md) — M0 基线 → M1 展开 + 翻译 → M2 编译攻坚 → M3 产品化（里程碑口径以 `docs/05` §6 为准）
- [全仓目标达成审计](docs/research/audit-2026-09-16/README.md) — 13 维度 verdict：M0 达成 / M1 实质达成 / M2 字面未达 / M3 约半程

已落 `src/texlate/`（uv 管理，`uv sync` 后 `uv run pytest tests/` 全绿）：

| 包                 | 内容                                                                                                                                               | 验证                                                                                      |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `arxiv/`           | e-print 获取/解包/主文件定位/限速                                                                                                                  | `tests/test_arxiv_*` 族 + corpus39/实网 gated 用例                                        |
| `latex/`           | 半解析 + 展开机（**v2 Gullet+Segmenter 默认路径**，`TEXLATE_NO_EXPAND=1` 回退 v1）                                                                 | corpus_v3 核心层 identity 100%、leak 0.040%（parsebench 实测）+ fixtures 断言集全绿（`tests/test_bench_regression.py`） |
| `xlat/`            | 编排层 + 3003 网关客户端（动态免费模型发现/重试/状态续翻/术语表）                                                                                  | xlat 测试族 + MockTranslator E2E；e2e-real n100 chunk ok 99.97%                           |
| `validate/`        | L0 规则校验（`_check_*` 检查族，见 `validate/l0.py`）/ L1 tree-sitter / L2 编译日志                                                                 | validbench corpus_v2 7867 用例：破坏 100% 检出 / 0 error-FP                               |
| `compile/`         | Engine 协议 (xelatex+tectonic) / ctex 注入 / normalize / 沙箱                                                                                      | compilebench-v4+fixloop 联合 pdf 154/172=89.5%（`bench/results/compilebench-v4-*/` 归因） |
| `compile/fixloop/` | yaml 规则修复引擎（规则库 = `rules/` 分片目录，自 rules.yaml 拆出；条目数以生成源为准 + cases.jsonl 沉淀）                                                                                   | fixloop-cbv4 臂 344 格实证（tlmgr 真装包 89 格）                                          |
| `server/`+`web/`   | FastAPI+SSE+SQLite(WAL)+BYOK worker 管线；SolidJS+pdfslick 阅读器（SPA 已接打包链：`scripts/build-web.sh` → `server/static/` 入 wheel/Dockerfile） | server/align 测试族 + web vitest                                                          |
| `export/`          | EPUB/DOCX 双语插译（`texlate export <file>`）：bbm 蓝图照抄——DRM 预检 + run 制 unit + `[[TAG_n]]` marker + StateStore 断点续跑                     | export 测试族 + 真书回归（`bench/results/export-realbook-2026-09-16/`：2 本 Gutenberg 全链绿） |
| `e2e.py`/`cli.py`  | `texlate run <arxiv-id>` 整链驱动（fetch→parse→xlat→inject→compile→judge）                                                                         | 实测出双语 PDF（audit-2026-09-16/e2e-func.md）                                            |

Benchmark 底材：corpus39（陷阱）+ corpus_v2（139 篇）+ corpus_v3（core + booster + hot + expand 四层，最新分层口径以 `bench/corpus_v3/MANIFEST.md` 为准；机制台账 `mechanisms.jsonl`，选择器 `select_booster.py`，管线 `bench/py/build_corpus_v3.py` + `build_hot_layer.py` + `build_corpus_expand.py` 可重建）。评测器已扶正：parsebench（B1）/ fixtures 断言（B2，tests/test_bench_regression.py）/ compilebench（B3）/ xlatbench（B4）/ e2e_mock+e2e_real（B5）/ validbench（B6）/ alignbench（B7）。规格见 `docs/06–10`。

## 关键设计共识 (来自 hjfy 逆向 + ieeA 走读)

1. **LaTeX 是脚本语言** — 必须建宏表做受限展开，按名匹配的保护不可靠
2. **宁粗勿断** — 翻译管线要容错分割+byte-range splice, 不要严格 AST 重建
3. **LLM 看不到就不会错** — 公式/引用/宏全部占位符化，只翻段落级文本
4. **编译修复是壁垒** — log 解析→规则表→修复→重试循环，规则库社区众包
5. **译文缓存是产品壁垒** — arXiv ID 命中秒回

参考实现：`~/src/ieeA` (zcyisiee/ieeA), 只借鉴模式不搬代码。
