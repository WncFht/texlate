# BabelDOC 冒烟测试报告 —— PDF 指令级翻译路线可行性

- 日期: 2026-09-14
- 版本: babeldoc 0.6.4 (PyPI 最新)
- 测试文档: `bench/corpus/1412.6980/0_adam_main.pdf` (Adam, ICLR 2015, 15 页, 534KB, 双栏排版已转单栏的 arXiv 排版)
- 产物目录: `bench/results/babeldoc/` (3 页试跑 + `full/` 全文跑 + PNG 截图 + `full_run.log`)

## 结论先行

**可行, 建议作为"非 arXiv PDF"路线的独立 sidecar 落地。** 管线端到端一次跑通, 15 页论文 60s 出 dual+mono 双语 PDF, 版式/公式/图表/算法框保持质量高, 已知短板集中在"定理陈述类密集内联数学段落"。sidecar 化工作量小(CLI 文件进文件出, ~200 行 FastAPI 封装)。AGPL-3.0 通过进程隔离边界处理, 不污染主仓。

## 1. 安装与依赖

```bash
cd ~/src/texlate/bench/py
uv venv .venv_babeldoc --python 3.12
uv pip install --python .venv_babeldoc/bin/python babeldoc
```

- venv 体积 **702MB**, 86 个包。重依赖: onnxruntime 1.30 + opencv-headless + scipy + numpy + pymupdf 1.28。**无 PyTorch**(DocLayout-YOLO 走 ONNX), 比预期轻。
- 首次 `babeldoc --warmup` 下载资产 **~20s**, 落盘 `~/.cache/babeldoc/` 共 **337MB**: DocLayout-YOLO ONNX 72MB + 思源/Noto CJK 字体 ~100MB + CMap + tiktoken。模型走 modelscope, 国内网络友好。
- 支持 `--generate-offline-assets`/`--restore-offline-assets` 做离线打包 → Docker 镜像可以预烘焙, 部署不用现场下载。
- 小坑: uv venv 不带 pip (正常); pymupdf 有 deprecated-import warning 噪音; 启动开销 ~8s (ONNX 加载+资产校验), 每次 CLI 调用都付一次。

## 2. API key / 端点情况

环境无 OPENAI_API_KEY/DEEPSEEK, 但本机 `127.0.0.1:3003/v1` 是 OpenAI 兼容网关(209 个模型), 直接复用。选 `gemini-3-5-flash-minimal`(非 thinking 型, 输出干净)。

**关键坑(已定位并解决)**: babeldoc 默认发送 `temperature: 0`, 本网关上游对 `temperature=0` 一律返回 `400 invalid_argument`(0.01/0.7 均正常)。加 **`--no-send-temperature`** 后完全正常。真实 OpenAI/DeepSeek 端点无此问题, 但 litellm 类聚合网关可能踩同样的坑。

**隐蔽故障模式(重要)**: 翻译请求失败时 babeldoc 不报错退出, 而是逐段 fallback 为原文 —— 首跑 3 页"成功"产出的 PDF 其实全是英文, 只有 WARNING 级日志。sidecar 封装必须监控日志中的 `Fallback`/`BadRequestError` 或校验输出 token 数(`Total tokens: 0` 即未翻译), 否则会把"未翻译"当成功返回。

## 3. 跑通情况与性能

| 项 | 3 页试跑 | 全文 15 页 |
|---|---|---|
| 墙钟时间 | ~35s | **60s** (babeldoc 自报 48.9s) |
| 峰值内存 | 806MB | **1132MB** |
| LLM tokens | 29.7k + 术语提取 9.1k | **123.9k** (101k in / 22k out) + 术语提取 31.7k |
| 输出 | mono 794KB / dual 1.3MB | mono 1.0MB / dual 1.5MB |

- 全程 0 ERROR; WARNING 7 条, 均为占位符校验失败后的 fallback 提示(见 §4)。
- 成本估算: ~156k tokens/篇, flash 级模型约 **$0.02–0.05/篇**, 可忽略。
- `--pages 1-3`、`--qps 8`、`-c config.toml` 均正常。纯解析模式 `--only-parse-generate-pdf` 可用(但仍要求传 translator 参数)。
- 翻译缓存: 默认开启(`.cache` 内), `--ignore-cache` 可关; 重跑命中后接近秒回。

## 4. 输出质量评估

**结构**: dual PDF = 15 个横向跨页(左原文右译文, 非页交错), mono = 15 页纯中文。默认顶部有一行 BabelDOC 水印, `--watermark-output-mode no_watermark` 可关。

**好的方面**:
- 正文段落翻译质量高, 术语一致(自动术语提取每 3 页抓 ~46 条术语)。
- display 公式、(6)(7) 式编号、算法框(Algorithm 1 伪代码含 α/β₁/gₜ←∇θfₜ 全部原样保留)、参考文献、cite 编号全部保持。
- **图内矢量文字也被翻译**(MNIST 坐标轴 "iterations over entire dataset" → "在整个数据集上的迭代次数"), 且重排版后无溢出 —— 比预期强。
- 中文字数收缩明显(全文 34.8k → 17.7k 字符, ~49%), 框内排布宽裕, 普通段落未见溢出。

**已知短板(目检 PNG 确认)**:
- **密集内联数学段落降级**: 附录定理 10.5 陈述页(13 页)出现占位符乱序 —— `f_t`/`θ_t`/`105` 等碎片散落、译文与公式交叠, 是该页唯一明显坏区。这正是 pdf2zh 系老问题, 与我们 LaTeX 路线的"公式占位符"痛点同源。
- 标题页作者行轻微错位(人名与单位行融合 "DiederikP. Kingma*阿姆斯特丹大学")。
- 偶发碎片: 8 页正文混出一个游离 "RM" 字样; 原超链接文本(如 "two upper bounds")保留下划线样式。
- poppler 渲染输出 PDF 时报大量 `Type 3 glyph` warning —— 打印/显示正常, 属外观级。

## 5. sidecar 化评估

**CLI 接口面**: `--files`(必填, 仅文件路径, **无 stdin/stdout**)、`--output`、`--working-dir`、`--pages`、`--lang-in/out`、`--qps`、`--no-dual/--no-mono`、`--watermark-output-mode`、`--max-pages-per-part`、`--enable-process-pool`、`-c TOML 配置`、`--rpc-doclayout*`(布局分析可拆成独立 RPC 服务, 利于 GPU/CPU 资源分离)。

**Python API**: `high_level.async_translate(TranslationConfig)` 是 async generator, 吐结构化进度事件(progress_start/update/finish/error), 天然适配 SSE。**但上游明确声明 "All APIs of BabelDOC should be considered as internal APIs"**, 官方建议走 pdf2zh-next 的 `do_translate_async_stream`; pdf2zh-next 另带 Gradio WebUI(非 REST)。

**推荐封装形态**: FastAPI sidecar, `POST /translate`(multipart PDF + lang + pages + dual/mono 选项) → 落 tmpdir → `subprocess` 调 CLI → 回传 mono/dual 文件。理由: ①CLI 是稳定接口面, 不依赖内部 API; ②进程隔离同时解决 AGPL 边界(见 §6); ③崩溃/OOM 不传染主服务, 天然支持并发 worker 池。进度上报可解析 stderr 进度行, 或退而求其次按 stage 粒度报。预估 **150–250 行 + Dockerfile**, 1–2 天工作量。容器建议 2GB 内存上限、预热资产进镜像、healthcheck 用 `--warmup`。

## 6. AGPL 边界

- `License-Expression: AGPL-3.0`(dist-info LICENSE 为 FSF 原版 AGPLv3)。pdf2zh-next 同 AGPL; 依赖 PyMuPDF 亦 AGPL/商业双授权 —— **整条链都在 copyleft 内**, 按"整体放进 sidecar"处理即可。
- **import 进我们的 Python 进程 = 不可行**: 合并程序在 convey/网络提供(§13)时整体受 AGPL 约束, 会强制主后端开源。
- **独立进程/容器调用 = 干净**: 主服务经文件系统/HTTP 与其通信属 at-arm's-length, 不构成衍生作品; 我们的封装层按 AGPL 发布(本来就是薄壳, 无所谓)。
- 若改 babeldoc 本体: 改动在网络提供服务时也须公开源码 —— 补丁保持最小并尽量上游化。
- 输出 PDF 不携带 AGPL 义务(GPL 系不约束 output); 默认水印是品牌行非法律要求, 可用 flag 关闭。

## 7. 对 TeXlate 的定位建议

- 与 LaTeX 源码路线互补: **有源码走 TeXlate 主管线(质量上限更高、可缓存译文), 只有 PDF 的走 babeldoc sidecar**。babeldoc 的"段落内联数学占位符重排"问题恰是源码路线能规避的。
- 值得借鉴的工程点: 自动术语提取(每篇先跑一遍 term extraction 再翻)、翻译缓存结构、布局分析 RPC 化、`--max-pages-per-part` 分块策略。
- 待办: ①拿一篇排版更野的非 arXiv PDF(IEEE 双栏/扫描版)复测; ②验证 sidecar 原型 + 失败检测(token=0 校验); ③确认网关可用模型清单里选一个稳定非 thinking 模型写进默认配置。
