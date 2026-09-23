# 命令行参考

`texlate` 是全部功能的统一入口。本篇按子命令列出用途、常用旗标与退出码；随时可以用 `texlate <命令> --help` 看权威清单——文档与 help 不符时以 help 为准（发现不符欢迎提 issue）。

全局旗标写在哪一级都生效：`texlate -v run ...` 与 `texlate run -v ...` 等价，子命令位置的 `-v`/`-q` 覆盖全局位。注意一个例外：`fetch -v` 是 `--version`（钉版本号）而不是 verbose。

## fetch —— 拉取 arXiv 源码

```bash
texlate fetch <arxiv_id> [--version N] [--cache 目录] [--offline]
```

接受新旧式 id、arXiv URL 或 `vN` 钉版写法（如 `1706.03762`、`cs/0501001v2`、`https://arxiv.org/abs/1706.03762`）。流程是 HEAD 探测 → 下载 e-print → 嗅探格式 → 解包 → 定位主文档，完成后钉版落进源缓存（缺省主目录下 `.cache/texlate/src/`，用 `--cache` 改）。

瞬时故障（限流、服务器错误、代理断流）自动退避重试并在 stderr 打 WARNING；配置了代理但所有地址都在传输层失败时，会切到直连兜底再试一次。`--offline` 或 `TEXLATE_OFFLINE=1` 时零网络：钉版精确查 `{id}v{ver}`，未钉版取本地已缓存的最高版本，两者都没有时报 `offline_no_cache` 退出 1——不会悄悄退回联网。

## parse —— 半解析单个文件

```bash
texlate parse <main.tex> [-o chunks.jsonl] [--no-flatten]
```

对单个 `.tex` 做半解析分块：统计块数、占位符、警告。`--out` 落逐块明细的 JSONL；`--no-flatten` 不展平 `\input` 引用图（缺省展平）。主要用于调试「这篇论文被切成了什么样」，不是翻译流程的必经步骤。

## run —— 端到端管线

```bash
texlate run <arxiv_id|工程目录> [-w 目录 --keep] [-e 引擎] [--offline]
texlate run <arxiv_id> --server <URL> [--model M --api-key K --base-url U] [-o 目录] [--wait 秒]
```

本地模式跑整条管线：取源（arXiv id 或本机工程目录）→ 规范化 → 翻译 → 注入中文排版 → 编译 → 判定 → 自动修复。**本地 `run` 固定用占位译文**——它验证的是「取源到出 PDF」的链路，产出 PDF 里每段中文是固定占位文本，不是真翻译。真翻译见 `--server` 模式与 `web.md`。

关键旗标：

| 旗标             | 作用                                                                   |
| ---------------- | ---------------------------------------------------------------------- |
| `-e, --engine`   | `auto`（缺省，按论文自动选）\| `xelatex` \| `tectonic`                 |
| `-w, --work-dir` | 指定工作目录；缺省用系统临时目录，跑完即删                             |
| `--keep`         | 保留工作目录——产物 PDF 与编译日志都在里面                              |
| `--timeout`      | 单次编译超时秒数（缺省 240）                                           |
| `--offline`      | 取源零网络（本地目录源无影响）                                         |
| `--front-matter` | 前置内容翻译白名单，逗号分隔 `abstract,title,author`；缺省翻摘要和标题 |
| `-q`             | 关掉 stderr 实况进度                                                   |

`--server` 切到瘦客户端模式：任务提交给一台正在运行的 `texlate web` 服务（本机或远端都行），流式显示进度，终态后把产物校验下载到 `--out` 目录（缺省 `./texlate-<id>-<任务前缀>/`）。`--model`、`--api-key`、`--base-url`、`--dialect` 这四个旗标只在这个模式下有意义，作为请求头逐项覆盖服务端配置——临时换 key 或换模型不用改 Settings。同一论文同一配置重复提交会自动挂到进行中的任务上，不会重复烧配额；`--wait` 控制最长等待秒数（缺省 1800），超时后任务仍在服务端继续，同参数重跑即可重新挂上。

退出码：0 = 完成（clean/partial 或远端 done/partial）；1 = 编译失败（修复链走尽仍无 PDF；`--server` 侧另含 fault/cancelled/interrupted/失联/超时）；2 = 用法错误（未知引擎、--server 选项脱离 `--server`、--work-dir 非空、把本地目录喂给 `--server`）或策略拒绝。

## web —— 起服务

```bash
texlate web [--host 地址] [-p 端口] [--data-dir 目录]
```

起 web 服务（需 `--extra server` 安装的依赖），缺省绑定 `127.0.0.1:8765`。数据目录缺省为 `TEXLATE_DATA_DIR` 或主目录下 `.texlate/`。本地形态有单实例锁：已在跑时再执行 `texlate web` 会打开浏览器指到已运行实例并退出，不会端口冲突或静默双开。日志写 `<数据目录>/logs/texlate.log`（DEBUG 级、脱敏、4MB×3 轮转）。

绑定非回环地址时 CLI 会打警告：本地形态的 API 不带鉴权，可达网段内任何人都能建任务改配置。要多用户部署用 `TEXLATE_MODE=server`（此时所有写操作要求 `X-Texlate-Key` 头），详见 `web.md` 的部署一节。

## export —— 电子书双语插译

```bash
texlate export <书.epub|书.docx> [-o 输出路径] [--model 模型] [--glossary 表.yaml] [--mock]
```

把 EPUB/DOCX 文档翻成双语插译版：每个原文段落后跟译文段落，输出同格式文件（缺省 `{原名}_bilingual{原后缀}`）。按文件内容嗅探格式，不看后缀；带 DRM、fixed-layout 或包损坏的文档在翻译前就拒绝。中断自动留 `{输出}.state/` 续跑现场，下次同命令接着翻。

需要已配置的 BYOK（`TEXLATE_API_KEY` 等，见 `byok.md`）；没配 key 时自动回落 mock 干跑并在 stderr 提示。`--mock` 或 `TEXLATE_TRANSLATOR=mock` 显式干跑；`TEXLATE_TRANSLATOR=gateway` 强制走网关（没 key 会直接报错退出 2，不静默产占位译文）。

## share —— 译文共享包

```bash
texlate share pack <任务id|任务目录> [-o 输出] [--contributor 名字]
texlate share unpack <包.share.zip> [-o 解包目录]
```

`pack` 把一个已完成任务的译文产物打成 `{share_key}.share.zip`：`share_key` 由论文 id、版本、模型、目标语言、提示词与管线版本、术语表哈希七组分推出，任一取不到会显式报错。`--contributor` 可署标识，缺省匿名。`unpack` 校验解包并打印 manifest 摘要——校验包括包格式、share_key 自洽、逐产物 sha256 对账，违例报 `share_invalid`。解包只做机械校验，译文可信度靠消费端导入后重跑编译保证。打包内容、使用场景与服务器侧导入见 `export-share.md`。

## doctor —— 环境自检

```bash
texlate doctor
```

逐项检查：Python ≥3.12、tectonic、xelatex、CJK 字体、pdftotext、模型端点连通、数据目录可写、server extra、babeldoc，每项 `ok`/`warn`/`fail`/`n/a` 加一行说明。任一 `fail` 退出码 1，否则 0。装完跑一遍、出问题跑一遍，是最快的自检手段。

## version / tools

```bash
texlate version                    # 打印版本号
texlate tools install-tectonic     # 探测或安装 tectonic 引擎
```

`install-tectonic` 探测系统件/托管件/缺失三态；缺失时下载钉版构建到数据目录 `tools/` 下（sha256 校验、原子落位）。已可用就报落点退出。`TEXLATE_NO_DOWNLOAD=1` 或 CI 环境下默认不自动下载（CI 里可用 `TEXLATE_NO_DOWNLOAD=0` 强制开）。

## 环境变量

按主题分组，全部 `TEXLATE_` 前缀：

| 变量                                                                                                      | 作用                                                                                                                                                            |
| --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TEXLATE_BASE_URL` / `TEXLATE_API_KEY` / `TEXLATE_MODEL` / `TEXLATE_DIALECT`                              | BYOK 四件套：端点、key、模型、方言（`auto`\|`openai`\|`anthropic`\|`responses`）                                                                                |
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `ANTHROPIC_API_KEY` / `TEXLATE_GATEWAY_KEY` | `TEXLATE_API_KEY` 为空时按端点域名自动认读对应的专名变量；`TEXLATE_GATEWAY_KEY` 对应回环端点（127.0.0.1/localhost/::1，含缺省本地网关 `http://127.0.0.1:3033`） |
| `TEXLATE_OFFLINE`                                                                                         | `=1` 等效 `fetch`/`run` 的 `--offline` 总闸                                                                                                                     |
| `TEXLATE_DATA_DIR`                                                                                        | 数据目录（任务库、设置、日志、共享包、托管引擎），缺省主目录下 `.texlate/`                                                                                      |
| `TEXLATE_LOG`                                                                                             | 日志级别 `debug`\|`info`\|`warning`\|`error`\|`off`；未给 `-v`/`-q` 旗标时生效（旗标优先于 env）                                                                |
| `TEXLATE_LOG_FILE`                                                                                        | 额外落盘的日志文件路径；`=off` 关闭（server 入口缺省落 `<数据目录>/logs/texlate.log`）                                                                          |
| `TEXLATE_TRANSLATOR`                                                                                      | `mock`\|`gateway` 强制翻译臂（export 与 server worker 共用）                                                                                                    |
| `TEXLATE_FRONT_MATTER`                                                                                    | 前置内容翻译集，逗号分隔 `abstract,title,author`                                                                                                                |
| `TEXLATE_NO_FIXLOOP` / `TEXLATE_NO_L2`                                                                    | 关掉编译修复循环 / 译文归因重译                                                                                                                                 |
| `TEXLATE_ENV_JUDGE`                                                                                       | 开启环境可译性判定（缺省关；server 侧作逐任务 `env_judge` 选项的 env 兜底）                                                                                     |
| `TEXLATE_AUTO_GLOSSARY`                                                                                   | 自动术语抽取——仅作用于本地 `run`/e2e（mock 占位管线）与 bench，缺省关；server/web 任务走逐任务选项 `auto_glossary`（缺省已开），此 env 在真实翻译路径无效       |
| `TEXLATE_COMPILE_TIMEOUT`                                                                                 | server 侧编译超时秒数上限调整                                                                                                                                   |
| `TEXLATE_MODE`                                                                                            | `server` 切多租户部署形态（写操作要 `X-Texlate-Key`；缺省 `local`）                                                                                             |
| `TEXLATE_CACHE_SCOPE`                                                                                     | `shared`（缺省，译文缓存跨 key 共享）\| `per_key`（按 key 分桶隔离）                                                                                            |
| `TEXLATE_SHARE_DIR`                                                                                       | 共享包发布目录（缺省 `<数据目录>/share/`）                                                                                                                      |
| `TEXLATE_MODEL_PROBE`                                                                                     | 保存 Settings 时的模型可用性探活，`=0` 关（离线环境用）                                                                                                         |
| `TEXLATE_NO_DOWNLOAD`                                                                                     | 禁止自动下载 tectonic 等外部件                                                                                                                                  |
| `TEXLATE_NODE`                                                                                            | L1 校验用的 node 可执行文件路径（缺省按 PATH 找）                                                                                                               |

## 日志与实况

`texlate` 的日志只走 stderr（stdout 留给 JSON 输出，可以安全管道）。级别判定顺序：旗标 > `TEXLATE_LOG` > 缺省 `WARNING`。`-v`=INFO、`-vv`=DEBUG、`-q`=ERROR 且关实况进度、`-qq`=CRITICAL。`run` 的 stderr 实况包括阶段行、翻译进度条和修复循环的轮帧（每轮一行，形如 `fixloop r1 missing_file:plex-sans.sty err=68 (15.7s)`）；编译修复的细节日志缺省做了过滤只留动作行，`-vv` 或 `TEXLATE_LOG=debug` 放全量。
