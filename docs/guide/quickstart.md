# 快速上手

这篇带你从零装到出第一份双语 PDF：先装依赖和 TeX 引擎，跑一次不烧配额的 mock 干跑确认链路正常，再配好模型服务做真翻译。全程大约十分钟，翻译本身的耗时取决于论文长度和你的模型端点。

## 前置条件

- Python 3.12 或更高版本。
- [uv][^uv]：包管理器，`uv sync` 一条命令装好全部 Python 依赖。
- 一个 TeX 引擎：tectonic（推荐，单文件免配置）或系统 TeX Live 的 xelatex，二选一，装法见下。
- 要用网页界面提交和阅读，还需要 node/npm 构建一次前端；只用命令行可以跳过。
- 真翻译需要任一 OpenAI 兼容端点的 API key（自建网关或 DeepSeek、OpenAI、Anthropic、Qwen 等服务商均可），没有 key 也能跑 mock 干跑。

## 安装

```bash
git clone <仓库地址> && cd texlate
uv sync --extra server
```

`--extra server` 装上 web 服务依赖；确定只用纯命令行、不碰 `texlate web` 的话可以省略。

## 装 TeX 引擎

推荐用内置安装器拿一份钉版 tectonic：

```bash
uv run texlate tools install-tectonic
```

它把校验过 sha256 的单文件引擎放进数据目录的 `tools/` 下，不污染系统。也可以用系统包管理器装 TeX Live（需要 `xelatex` 与中文语言包，例如 Debian/Ubuntu 的 `texlive-xetex` + `texlive-lang-chinese`）。两个引擎都在时 TeXlate 会自己挑合适的用。

## 自检环境

```bash
uv run texlate doctor
```

输出逐项 `ok`/`warn`/`fail`/`n/a`：Python 版本、tectonic、xelatex、CJK 字体（ctex/fandol/系统中文字体任一可用）、pdftotext、模型端点连通性、数据目录可写、server extra、babeldoc。出现 `fail` 时按该行提示修好再往下走；`warn`/`n/a` 不阻塞（例如没装 babeldoc 只影响 PDF 上传翻译，不影响 arXiv 主链路）。

## 第一步：mock 干跑

```bash
uv run texlate run 1706.03762 -w texlate-demo --keep
```

这条命令做了管线里除「调模型」以外的所有事：从 arXiv 拉取论文源码、半解析分块、用占位译文代替真翻译、注入中文排版环境、真实调 TeX 引擎编译并自动修复常见错误，最后判定产物。`-w texlate-demo --keep` 保留工作目录，编译出的 PDF 落在 `texlate-demo/` 下，文件名与论文主文档同名（这里是 `main.pdf`）。stdout 打印的 JSON 是判定报告，`status` 为 `clean` 或 `partial` 即链路打通。

mock 译文的每段中文是固定占位文本，作用是让「翻译后的论文」长得跟真翻译一样长、一样结构——拿它确认编译链路，不拿它读。

## 第二步：真翻译

真翻译走任务队列，由 web 服务执行。先配好 key 再起服：

```bash
export TEXLATE_BASE_URL="https://api.example.com/v1"   # 换成你的 OpenAI 兼容端点
export TEXLATE_API_KEY="sk-..."
export TEXLATE_MODEL="模型名"
uv run texlate web
```

浏览器打开 `http://127.0.0.1:8765`，在输入框粘 arXiv id（还是 `1706.03762`）点翻译，等进度条走完就进双语对照阅读器。配 key 的完整细节（网页 Settings 页、请求头、端点要求）见 `byok.md`；想留在命令行，可以用瘦客户端把任务提交给正在运行的服务：

```bash
uv run texlate run 1706.03762 --server http://127.0.0.1:8765 --api-key "sk-..." --model "模型名"
```

命令结束打印任务终态并把产物下载到当前目录下的 `texlate-<id>-<任务前缀>/`。

## 前端界面（可选）

`texlate web` 服务的图形界面是构建产物，仓库里不带。要界面先构建一次：

```bash
scripts/build-web.sh
```

不构建时服务照常提供 API，`run --server` 与 curl 都能用，只是浏览器里看不到页面。

## 拿到的产物

每个任务产出：中文 PDF（`zh.pdf`）、原文 PDF（`en.pdf`，由原文源码本地编译得到、源不可编译时缺席；PDF 上传任务则为上传的原文件）、对照数据（`dual.json`）、翻译后源码包（`zh-src.zip`）、编译日志。阅读器里直接看双语对照，下载菜单里取单件。产物默认保留在数据目录的 `tasks/<任务id>/` 下，清理策略见 `faq.md` 的「数据存哪」。

## 卡住了先看这里

`doctor` 有 `fail` 项 → 按提示修环境；arXiv 拉取失败 → 检查网络或对已缓存的论文用 `--offline`；编译失败 → `faq.md` 的「编译失败怎么办」；译文是占位文本 → 没配 key，看 `byok.md`。

[^uv]: Astral. uv 安装文档。[docs.astral.sh](https://docs.astral.sh/uv/getting-started/installation/)
