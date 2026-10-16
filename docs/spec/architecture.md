# 管线与责任边界

TeXlate 的 LaTeX 主路径是获取源码、解析可译段、调用模型、回写源码、编译并生成阅读产物。当前代码是行为依据；各层契约随实现更新。

## 管线

```text
arxiv / upload → normalize → latex.gullet + segmenter
  → chunks + placeholders → xlat.pipeline → reconstruct
  → compile → precheck / logfix / fixloop → judge
  → PDF + alignment + registered artifacts
```

`pipecore/` 保存 e2e、服务端 worker 与评测共用的阶段契约和修复策略；`e2e.py` 负责本地编排，`server/worker/` 负责持久化任务执行。修复归因和回灌在顶层 `repair/`，编译规则在 `compile/fixloop/`。修改公共管线语义先核对这三个消费者，避免分别实现不同的失败和重试逻辑。

## 层与所有权

| 层                     | 责任与契约                                                                   |
| ---------------------- | ---------------------------------------------------------------------------- |
| `arxiv/`               | ID、获取、钉版缓存、安全解包和元数据；[获取契约](arxiv-source.md)            |
| `latex/`               | gullet 展开、segmenter 切块、占位符及源码回写；[解析契约](latex-pipeline.md) |
| `xlat/`                | 组批、渠道调用、术语、校验消费、梯级重试与断点状态；[翻译契约](translate.md) |
| `validate/`            | 规则、语法树与日志归因；[校验契约](validate.md)                              |
| `compile/`             | 引擎路由、中文注入、资源限制、修复与判定；[编译契约](compile.md)             |
| `server/`              | SQLite、任务、事件、渠道、上传与产物授权；[服务契约](server.md)              |
| `web/`                 | SolidJS 阅读器，消费 REST/SSE 和定位数据；[阅读器契约](reader.md)            |
| `export/` · `share.py` | EPUB/DOCX 双语插译、共享包校验及复用；[用户操作](../guide/export-share.md)   |
| `bench/py/`            | 评测机制，数据驻仓外；[评测存储契约](bench-trizone.md)                       |

`ChunkIn` 位于顶层 `chunk.py`，获取层不得向上 import 翻译或服务层。`textutil/` 提供跨层文本和环境变量工具；各层消费同一实现。测试替换位置和惰性门面约定见[代码约定](../dev/conventions.md)。

## 入口与产物

CLI 本地执行经过 `cli/` 与 `e2e.py`；`run --server URL` 提交服务任务并下载校验产物。服务端经 `server/app.py` 暴露 API，并可挂载 `web/` 构建产物；Zotero 插件是远端客户端，不另有翻译管线。

LaTeX 任务保留源树、块与翻译状态，生成中文源码、PDF 和对齐数据；具体暴露的文件由服务产物清单控制。占位符还原和 identity 不能因为 PDF 编译成功而跳过。翻译交付、编译交付和版面质量分别判定，失败任务仍可能含不可再生的付费译文。

HTML 路径用 DOM 分块和回插代替 LaTeX 解析编译；PDF 路径调用 BabelDOC 子进程；EPUB/DOCX 复用翻译器进行插译。降级路径不承诺 LaTeX 源码复制能力。BabelDOC 保持进程边界；EPUB 的 DRM 拒绝没有放行开关。

共享和任务去重共同消费 `share.py` 的缓存键与管线版本，不能在客户端重造另一套键。凭据的运行期所有权、缓存隔离和可复用终态见[服务端](server.md)。具体模块的 CLI 与 API 以 `--help`、OpenAPI、实现及测试为准，不在文档复制目录和符号全集。
