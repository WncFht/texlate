# texlate (open-hjfy)

> 「幻觉翻译」[hjfy.top](https://hjfy.top/) 的开源复现：arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF，双语对照阅读。
>
> _Open-source reimplementation of hjfy.top: fetches arXiv LaTeX sources, translates paragraph-level text with any OpenAI-compatible LLM (BYOK), and recompiles to a bilingual Chinese-English PDF — preserving formulas, references, macros and layout by translating only prose and shielding everything else behind placeholders._

管线：`fetch`(arXiv e-print 钉版缓存) → `parse`(LaTeX 半解析 + 受限宏展开) → `xlat`(LLM 段落翻译，公式/引用/宏全占位符化) → `inject`(ctex 中文环境注入) → `compile`(tectonic/xelatex + fixloop 规则引擎自动修复) → `judge`(编译日志与 CJK 字数核验)。

![texlate 管线全流程图：获取→半解析→翻译→注入→编译→判定→双语 PDF，含降级链、L0/L1 校验门与 fixloop 修复回环，顶部标注各评测臂读数](shots/bench-pipeline.png)

## 安装

需要 Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)（或 Docker，见下）。

```bash
git clone <repo-url> && cd texlate
uv sync --extra server        # server extra 提供 web/API 形态；纯 CLI 可省略
```

再装一个 TeX 引擎（二选一；`texlate doctor` 可逐项自检环境）：

```bash
uv run texlate tools install-tectonic   # 便携引擎，sha256 钉版（推荐，单文件 ~30MB）
# 或系统包装 TeX Live：apt/pacman 安装 texlive-xetex + texlive-lang-chinese
```

## 快速开始

```bash
uv run texlate run 1706.03762     # mock 端到端：真实编译，但译文是占位假译（链路自检用）
```

**注意：本地 `texlate run` 只有 mock 翻译臂**——产出 PDF 的英文段被替换成占位文本，用于零成本验证 fetch→parse→compile 全链。真翻译走 server 形态（下节）。

真翻译（任意 OpenAI 兼容端点 / Anthropic messages 方言均可）：BYOK 配在运行中的 `texlate web` server 上——三 env（另可选 `TEXLATE_DIALECT`）或在 Web Settings 页配置均可：

```bash
export TEXLATE_BASE_URL="https://your-gateway/v1"   # 或自建的本地网关地址
export TEXLATE_API_KEY="sk-..."
export TEXLATE_MODEL="your-model"
uv run texlate web                                  # http://127.0.0.1:8765
```

随后经 SPA 提交 arXiv ID，或用 CLI 瘦客户端向 server 提交任务：

```bash
uv run texlate run 1706.03762 --server http://127.0.0.1:8765   # 真译文 + ctex 重编译 → 双语 PDF
# 按请求覆盖 BYOK：`--model/--api-key/--base-url/--dialect`（x-texlate-* 请求头）
```

三 env 等价于 Web Settings 页配置；本地 `http://127.0.0.1:*` 与 tailnet 主机（`100.64.0.0/10`、`*.ts.net`）放行明文 HTTP，远程端点强制 HTTPS。

## Web 形态

```bash
scripts/build-web.sh            # 构建 SPA → src/texlate/server/static/（需 node/npm）
uv run texlate web              # http://127.0.0.1:8765 —— 提交 arXiv ID → SSE 进度 → 对照阅读器
uv run texlate doctor           # 环境自检：引擎/字体/网关连通/数据目录逐项 ok/warn/fail
```

SPA 是构建产物不入库；未构建时 `texlate web` 只服务 API。BYOK 也可在 Settings 页配置（`TEXLATE_*` env 等价直配）。部署态置 `TEXLATE_MODE=server`（跳过 local-only CSRF 中间件，正式部署请前置反代做 CORS allowlist）。

## Docker

```bash
docker build -t texlate .                                   # 需 BuildKit（COPY --from=外部镜像）
docker run -p 8765:8765 -v texlate-data:/data texlate       # web 形态
docker run --rm texlate fetch 1706.03762                    # 其他子命令同理
```

镜像内置 tectonic + Noto CJK；高成功率编译档（TeX Live xelatex，~4GB）追加步骤见 Dockerfile 头部注释。BabelDOC sidecar（PDF 上传通路）因 AGPL 边界不随镜像分发。

## CLI 一览

| 命令                                                    | 用途                                               |
| ------------------------------------------------------- | -------------------------------------------------- |
| `texlate fetch <id> [--offline]`                        | e-print 获取 + 钉版缓存（`~/.cache/texlate/src/`） |
| `texlate parse <main.tex>`                              | 半解析分块 → chunks.jsonl                          |
| `texlate run <id\|dir>`                                 | 端到端（本地仅 mock 臂；真译加 `--server` 提交）   |
| `texlate web`                                           | FastAPI+SSE+SQLite 服务 + SPA                      |
| `texlate export <docx/epub>`                            | 双语插译导出                                       |
| `texlate share pack/unpack`                             | 任务产物社区共享包（sha256 全量回验）              |
| `texlate doctor` / `version` / `tools install-tectonic` | 自检 / 版本 / 引擎安装                             |

离线总闸：`TEXLATE_OFFLINE=1`（等效 `--offline`，取源只查本地缓存）。

## 架构要点

- **LaTeX 是脚本语言**——必须建宏表做受限展开（v2 `gullet/`+`segmenter/` 为唯一解析路径）；按名匹配的保护不可靠。
- **LLM 看不到就不会错**——公式/引用/宏/verbatim 全部占位符化，模型只翻段落级文本；L0 校验器对 src↔zh 做占位符多重集 diff + brace/env/cite-key 相对判定，L1 tree-sitter 校验为可选增强。
- **编译修复是壁垒**——fixloop：日志解析 → taxonomy 分类 → yaml 规则（`compile/fixloop/rules/` 分片）逐条修复重试；`vendor/` 收 off-CTAN 绝版宏包的真件（许可允许者）与净室 stub（禁分发者，见 NOTICE）。
- **译文缓存**——SQLite 按 arXiv ID+ 版本 + 模型指纹命中秒回；`texlate share` 互通。

## 实测指标

评测设施与产品同仓维护：判分器、对照组驱动、分层语料全部收在 `bench/`，下列读数可复算。口径与原始数据见 [metrics 报告](docs/research/methods/metrics-2026-09-19/report.pdf) 与 [三臂对照基线](docs/research/methods/agent-pipeline-baseline-2026-09-28/README.md)。

| 评测臂         | 测什么                                                               | 现行读数                                                  |
| -------------- | -------------------------------------------------------------------- | --------------------------------------------------------- |
| `e2e_real`     | 端到端真臂：真实 LLM 翻译全链 → 编译 → 终态判分                      | 200 篇验收：98.5% 产出双语 PDF，86.5% 编译零警告（clean） |
| `qualbench`    | 翻译质量：ESA 两步评审，评审模型逐段标注错误后打分，与翻译模型不同款 | 1,200 段基线均分 92.9（95% CI [92.4, 93.3]）              |
| `parsebench`   | 半解析保真：解析成功率、分块往返逐字节一致、占位符泄漏               | 28,904 个 .tex 解析 100%、identity 99.99%、leak 0.004%    |
| `validbench`   | L0 校验器对抗：注入破坏须全检出、好译文不得误报                      | 1,503 对注入破坏全部检出、零误报                          |
| `compilebench` | 对照分母：同一批论文不翻不修裸编译的天花板                           | n=500 union pdf 90.4%、clean 72.4%                        |
| `fixloop`      | 编译修复引擎：日志 → taxonomy → yaml 规则逐条修复重试                | 262 条规则、121 类错误；同口径出片 70.6% → 89.5%          |

**token 成本**：同模型、同网关、同 10 篇三臂对照——管线新输入 1.29M token，为通用 agent 整篇直翻（4.75M）的 27%；毛输入（含缓存读）仅其 2.4%；占位符存活 10/10 篇全 100%。

**底座**：语料 13,266 篇八层钉版（46GB），含 3,020 篇留出评测层（EVAL_ONLY，开发管线不可见）；pytest 10,493 项，干净 clone 全绿。另有 e2e_mock 机械链、soak 失败池浸泡、alignbench 锚点保留等内部回归臂。

口径注记：`e2e_real` 现行读数采样自开发层、为 v4 提示词时代口径；留出层重测在排期。

解析层自研是横评定案：八家第三方 LaTeX 解析库无一通过全部断言（最高 24/26，四家因机制性失败无法计分），`\be` 经宏表展开为 `\begin{equation}` 一类陷阱是分水岭；静默截断不报错，比崩溃更难兜底，校验器因此独立成层。

![八库解析横评：自研 32/32 断言全过，最好第三方 24/26，四库机制性失败无法计分](shots/bench-parse-libs.png)

## 仓库布局

- `src/texlate/` — 产品代码：`arxiv/` 获取层、`latex/` 半解析管线、`xlat/` 翻译编排、`validate/` L0/L1/L2、`compile/` 引擎+fixloop、`server/` Web 后端、`export/`、`cli/` 命令行包
- `web/` — SolidJS+Vite+pdfslick 阅读器（独立 package.json；`npx tsc --noEmit && npx eslint . && npx vitest run`）
- `zotero/` — Zotero 7 插件（TypeScript 瘦客户端，调远端 texlate 服务）
- `tests/` — pytest（corpus/网关/node 依赖用例均有守卫，干净 clone 全绿）
- `docs/` — [`docs/README.md`](docs/README.md) 总索引，六分区：`guide/` 用户文档 + `spec/` 技术规范（实现唯一事实源）+ `decisions/` ADR 决策史 + `dev/` 贡献者文档 + `research/` 调研档案 + `log/` 工程日志；维护规则 [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md)
- `bench/` — 评测 harness（`TIERS.md` 分层契约 + `docs/spec/benchmark.md` 评测器规格 + `docs/spec/bench-trizone.md` 三区账本设计；`py/`=trizone 内核 `kernel/` + 评测 `specs/` + 分析 `verbs/`，统一入口 `bench/py/bench`；`corpus/` 语料清单入库、载荷与产物在 `$TEXLATE_BENCH_ROOT`（缺省 `~/.local/share/texlate-bench`）的 lake/runs/vault 区）
- `tools/` — tracked 诊断/度量脚本（`tools/README.md` 逐件登记）
- `Dockerfile` / `.github/workflows/` — 容器形态与 CI（pre-commit 同源）

## 开发

```bash
uv sync --extra server        # 含 dev group（pytest）
uv run pytest tests/ -q       # 测试
ruff format --check . && ruff check .   # python 门（select=ALL 严格集）
npm ci && npm run format:check          # md/js/yaml/toml 门（pre-commit 同源）
pre-commit install            # 提交钩子：formatter 走 git-format-staged，check 类拦截
```

pre-commit 前置工具：`npm install` + `autocorrect ruff shfmt shellcheck actionlint taplo`（macOS 走 brew；Linux 各发行版包名同名或 `cargo install`/`go install` 等价）。CI 与本地链同源——本地不过 CI 必挂。

## License

Apache-2.0（见 LICENSE）。`compile/fixloop/vendor/files/` 内第三方期刊宏包各随其原许可、`vendor/stubs/` 与 `vendor/shims/` 为本项目净室实现——逐件说明见 NOTICE。

## 致谢

- [hjfy.top](https://hjfy.top/)（吴多益）——产品原型与全部关键设计共识（实现自述：[知乎原文](https://zhuanlan.zhihu.com/p/1905569596599169419)，产品侦察 `docs/research/product/2026-09-14-hjfy-site.md`）
- [ieeA](https://github.com/zcyisiee/ieeA)——参考实现，借鉴模式
