# PDF 通路设计：BabelDOC + MinerU 深读与 sidecar 规格

> 调研对象：`tmp/refs/BabelDOC`（0.6.4，AGPL-3.0）、`tmp/refs/MinerU`（3.4.5，Apache-2.0+ 附加条款）。
> 所有 `file:line` 引用均相对这两个目录。

## 结论先行

1. **M3 建议直接做 BabelDOC sidecar 出双语 PDF，跳过 MinerU→md 过渡方案。** 理由：冒烟已验证可行（60s/15 页、$0.02-0.05/篇）；dual PDF 即旗舰 UX，主路线的 pdfslick 双栏阅读器可直接复用，零新增前端；MinerU→md 路线反而要自建「双语 md 对照阅读器」+ 部署一个更重的本地模型栈。原 roadmap（M3 MinerU / M4+ BabelDOC）建议对调。MinerU 保留为两类兜底：扫描件/OCR PDF（BabelDOC 会抛 `ScannedPDFError` 或乱版）+ 未来想要 reflow 式 md 阅读的选项。
2. **「静默 fallback 保原文」有可靠检测手段，不必盲信产物。** BabelDOC 会把每段的 `has_error`/`error_message`/`fallback_to_translate` 落盘到 `translate_tracking.json`（只要传了 `--working-dir` 就写，不需要 debug），另有 `Translation completed. Total/Successful/Fallback` 日志行与 token 计数器。sidecar 把 fallback 段数计入响应并打 `degraded` 标记即可堵住假成功。
3. **sidecar 用 in-process `async_translate` 包一层 FastAPI，而不是 spawn CLI 刮 stderr。** `async_translate` yield 的结构化 stage 事件可直接转 SSE；进程边界 = 容器边界即满足 AGPL 隔离。官方树内 `babeldoc.tools.executor` HTTP 服务不建议直接复用（强制 rpc_doclayout8 远程布局 + `pyarrow` 未声明依赖 + `ExecutorTranslator` 硬编码 `temperature:0` 无 `--no-send-temperature` 逃生口），但其 request schema 是现成的接口设计参考。
4. **与主管线的复用点 = OpenAI 兼容网关 + glossary CSV + custom_system_prompt，其余完全独立。** BabelDOC 自带提示词/术语提取/SQLite 缓存/质量校验，我们的 `texlate.translate` 编排不在环路里；把 `--openai-base-url` 指向自有网关即可让 BYOK/限流/语义缓存/计量在网关层统一生效。

---

## 一、BabelDOC 深读笔记

### 1.1 CLI 入口与配置

- 入口 `babeldoc = babeldoc.main:cli`（`pyproject.toml:66-67`），`cli()` → `logging + RichHandler` → `asyncio.run(main())`（`babeldoc/main.py:916-946`）。
- 配置：configargparse + TOML，`[babeldoc]` 节（`main.py:32-41`）；**全部 TOML 键 = CLI 长选项名**（连字符/下划线皆可），完整示例见 `README.md:264-322`。
- 关键 flag 语义（`main.py:36-465`）：

| flag                                                                                 | 语义                                                                                                                                                                                |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--files`                                                                            | append 多文件，串行处理（`main.py:619-631,683`）                                                                                                                                    |
| `--pages`                                                                            | `"1,2,1-,-3,3-5"`，**1-based**，`-1`=无界（`translation_config.py:383-406`）                                                                                                        |
| `--qps`                                                                              | 全局漏桶 RateLimiter，默认 4（`translator.py:28-76`）；`--pool-max-workers` 缺省=qps                                                                                                |
| `--max-pages-per-part`                                                               | `PageCountStrategy` 把文档切成 N 页/段**串行**翻译再 `ResultMerger` 合并（`high_level.py:546-682`、`split_manager.py:24-50`）；进度事件带 `part_index/total_parts`。大 PDF 控内存用 |
| `--rpc-doclayout{,2..7}`                                                             | 用远程布局 RPC host 替代本地 ONNX（`main.py:553-584`）；默认 `DocLayoutModel.load_onnx()` 本地推理                                                                                  |
| `--generate-offline-assets <dir>` / `--restore-offline-assets <zip>`                 | 打包/还原全量资产 zip（sha3-256 逐个校验，文件名编码清单 hash，`assets.py:501-599`）——air-gap/镜像构建利器                                                                          |
| `--warmup`                                                                           | 下载 ONNX+ 全部字体+cmap+tiktoken 后退出（`main.py:489-492`、`assets.py:449-462`）                                                                                                  |
| `--no-send-temperature`                                                              | `OpenAITranslator(send_temperature=False)`，请求体不带 temperature（`main.py:521`、`translator.py:240-241,273-274`）——冒烟坑①的解法                                                 |
| `--no-dual` / `--no-mono`                                                            | 关闭双语/单语产物；`--use-alternating-pages-dual` 交替页双语；`--watermark-output-mode` 水印控制                                                                                    |
| `--working-dir`                                                                      | 工作目录；**非 None 即触发 tracking JSON 落盘**（`translation_config.py:287-296`），不传则 mkdtemp 且不落盘                                                                         |
| `--custom-system-prompt`                                                             | 替换 LLM prompt 的 role_block（`il_translator_llm_only.py:895-899`）——注入我们风格的口子                                                                                            |
| `--glossary-files` / `--no-auto-extract-glossary` / `--save-auto-extracted-glossary` | 用户术语表 CSV / 关自动术语 / 落盘自动术语                                                                                                                                          |
| `--openai` + `--openai-model/-base-url/-api-key`                                     | 唯一翻译服务；`--openai-term-extraction-{model,base-url,api-key,reasoning}` 可给术语提取单独开小模型（`main.py:506-546`）                                                           |
| `--openai-reasoning` / `--openai-thinking`                                           | 塞 `extra_body` 的 reasoning/thinking 字段（`translator.py:248-255`）                                                                                                               |
| `--lang-in/-out`                                                                     | 默认 en→zh                                                                                                                                                                          |
| `--ignore-cache`                                                                     | 跳过翻译缓存                                                                                                                                                                        |
| `--skip-scanned-detection` / `--ocr-workaround` / `--auto-enable-ocr-workaround`     | 扫描件策略三件套                                                                                                                                                                    |
| `--disable-same-text-fallback`                                                       | 只关「同文回退」质量门，**不**影响异常吞没（见 §1.3）                                                                                                                               |
| `--only-include-translated-page`                                                     | 配合 `--pages` 只输出被译页                                                                                                                                                         |

### 1.2 管线、术语提取与缓存

- 阶段与权重（`high_level.py:62-72`）：`DetectScannedFile`(2.45) → `LayoutParser`(14.03) → `TableParser`(1.0) → `ParagraphFinder`(6.26) → `StylesAndFormulas`(1.66) → `AutomaticTermExtractor`(30.0) → `ILTranslator`「Translate Paragraphs」(46.96) → `Typesetting`(4.71) → `FontMapper`(0.61) → `PDFCreater`(1.96)（外加 Save/Subset 子阶段）。
- 翻译主路径 `ILTranslatorLLMOnly`（`high_level.py:997-1003`）：段落打包成 JSON 数组 `[{id,input,layout_label}]` 一次 `llm_translate` 调用；prompt 模板 `PROMPT_TEMPLATE`（`il_translator_llm_only.py:40-95`）约束占位符 `{v1}`/`<style id='n'>` 不改、输出等长 JSON。
- **术语提取**：`AutomaticTermExtractor`（`automatic_term_extractor.py:133-420`），术语学家 prompt（31-66 行）输出 `[{src,tgt}]` JSON；≤600 token 或 ≤12 段一批（254 行）；产出 `auto_extractor_glossary.csv` 并注入后续翻译请求的 glossary block；可用 `--openai-term-extraction-*` 拆独立小模型省钱。
- **翻译缓存**：peewee+SQLite，`~/.cache/babeldoc/cache.v1.db`（`cache.py:148-162,199`、`const.py:11`）；键 = `translate_engine + engine_params + original_text`，params 含 model/prompt/temperature（`translator.py:240-247`）→ 换模型/换 prompt 自动不串；0.1% 概率触发 50k 行裁尾（`cache.py:24-25`）。**注意 cache.py:199 在 import 时即 init db**。

### 1.3 静默 fallback 代码路径（sidecar 检测 hook 点）

三层兜底，**前两层会记 tracker，第三层只 log 不上报**：

1. **批级异常**（JSON 解析失败、返回数量不齐、非 429 的 API 错误）→ `il_translator_llm_only.py:852-884`：log `"try fallback"`，整批段落 `set_fallback_to_translate()`，逐段重投 `ILTranslator.translate_paragraph`（单段 llm 调用，`il_translator.py:1241-1254`）。
2. **质量门**：同文（edit_distance<5 且 >20tok，`il_translator_llm_only.py:793-805`）、长度比出界 0.3-3（783-791）、非字符串/越界 id（742-751）→ 单段 `should_fallback` 重投（823-848）。
3. **单段异常吞没**：`il_translator.py:1273-1278` —— `except Exception → logger.exception("Error translating paragraph") → return`，段落保留原文 unicode，**无重试、无事件上报**；`ContentFilterError` 单独走 1269-1272 加提示。

**为什么会假成功**：OpenAI 层 `@retry` 只覆盖 `RateLimitError`（`translator.py:265-270,297-302`，100 次指数退避）；`BadRequestError`/`AuthenticationError`/连接错误直接冒泡 → 被层 3 吞掉 → PDF 照常产出但含英文原文。`ExecutorTranslator` 同样：非 2xx → `ExecutorTranslatorError`（非 RateLimitError）→ 层 3 吞（`tools/executor/translator.py:114-123`）。

**检测信号（按可靠性排序）**：

| 信号                      | 位置                                                                                                                                                                                                                 | 说明                                                                                                                                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `translate_tracking.json` | `working_dir/<stem>/`（`il_translator_llm_only.py:246-254`、`il_translator.py:418-426`）                                                                                                                             | 段落树 → `llm_translate_trackers[]` → `{has_error,error_message,fallback_to_translate,placeholder_full_match}`（`il_translator.py:293-326`）。**只要 working_dir 非 None 必写**——sidecar 每单传 job 目录即可 |
| 日志行                    | `"Translation completed. Total: T, Successful: S, Fallback: F"`（`il_translator_llm_only.py:255-257`）；`"Error translating paragraph"`（`il_translator.py:1274`）；`"Fallback to simple translation"`（`:828-829`） | in-process 模式挂 logging handler 捕获                                                                                                                                                                       |
| token 计数                | `translator.token_count/prompt_token_count/completion_token_count/cache_hit_prompt_token_count`（`translator.py:260-263,345-364`）；CLI 尾打 `Total tokens`（`main.py:772-777`）                                     | `total==0 且 translate_cache_call_count==0` → 全文未译。**坑：全 cache 命中也是 0**，必须结合 tracking json 判读                                                                                             |
| 产物抽查                  | mono PDF `page.get_text()` 的 CJK 占比                                                                                                                                                                               | 兜底 sanity check，cost 低                                                                                                                                                                                   |
| `error` 事件              | `async_translate` yield `{type:"error"}`（`high_level.py:366-367,722-729`）                                                                                                                                          | 整文失败（如 `ScannedPDFError`，`detect_scanned_file.py:142`）会如实上报——这层不静默                                                                                                                         |

### 1.4 进度事件（SSE 直接转发）

`async_translate` yield dict（`high_level.py:299-376` 文档串 + `progress_monitor.py`）：

- `stage_summary`（建 monitor 时发一次，各 stage 权重）
- `progress_start` / `progress_update` / `progress_end`：`{stage, stage_progress, stage_current, stage_total, overall_progress, part_index, total_parts}`
- `finish`：`{translate_result}`；`error`：`{error}`
- 节流：`report_interval`（默认 0.1s，`main.py:232-236`、`progress_monitor.py:214-235`）

→ sidecar 把每个事件原样转 SSE frame，前端拿 `stage + overall_progress` 渲染。

### 1.5 打包面

- **依赖**（`pyproject.toml:22-64`）：pymupdf、onnx+onnxruntime、openai、peewee、tiktoken、freetype-py、uharfbuzz、opencv-python-headless、scikit-image/scikit-learn/scipy、rtree、hyperscan、xsdata、orjson/msgpack/pyzstd、rich/tqdm、configargparse/toml、httpx[socks]、pydantic、tenacity、Levenshtein、chardet/charset-normalizer、cryptography、psutil、numpy、bitstring。体量粗估 site-packages ~1.2-1.5GB（科学计算栈占大头）。
- **模型资产**（`assets.py`、`embedding_assets_metadata.py`）：`doclayout_yolo_docstructbench_imgsz1024.onnx`（HF/hf-mirror/modelscope 竞速下载）；~127 个嵌入字体（GoNotoKurrent 系，单个最大 ~15MB）；146 个 cmap JSON；1 个 tiktoken blob。全部 sha3-256 校验，落 `~/.cache/babeldoc/{models,fonts,cmap,tiktoken}`。`CACHE_FOLDER = ~/.cache/babeldoc` 硬编码（`const.py:11`）→ **容器里用 `HOME` 环境变量控制位置**。`--warmup`/`--generate-offline-assets` 支撑构建期预热与离线分发。
- **布局推理**：onnxruntime，Linux 走 CPU provider，macOS 自动 CoreML 静态化（`docvision/doclayout.py:41-72`）；`--rpc-doclayout*` 可把布局卸载到远程服务——我们的部署不需要。
- **内存**：`MemoryMonitor` 全程采 PSS（含子进程，`high_level.py:379-438`、`utils/memory.py`），峰值写入 `result.peak_memory_usage`。预算：容器 `--memory=2g` + 单实例单飞 + `OMP_NUM_THREADS=4`。
- **并发模型**：全局 `RateLimiter` 是进程内单例（`translator.py:72`），翻译用 `PriorityThreadPoolExecutor`（`pool_max_workers`）→ **一个 sidecar 实例一次只跑一单**最稳，多实例水平扩展。

### 1.6 树内 executor（官方生产 API，可参考不直用）

`babeldoc/tools/executor/`：`python -m babeldoc.tools.executor --host 127.0.0.1 --port 7860`（`server.py:480-489`）。

- 端点：`POST /v1/executions`（创建，忙→409 单飞）、`GET /v1/executions/{id}/events?after_sequence=N`（NDJSON 事件流 + 回放，环形 1000 条）、`POST /v1/abort`、`GET /healthz`、`POST /v1/pdf/watermark{1,2}`（`server.py`）。
- 执行隔离：`MultiprocessExecutionRunner` forkserver 子进程 + 双 pipe（progress/cancel）（`runner.py:198-340`）；文件经 `BABELDOC_EXECUTOR_WORKROOT` 目录交换（`workroot.py`）。
- 请求 schema（`babeldoc_adapter.py:118-264`）——**我们的 sidecar 接口直接抄这个形状**：

```json
{
  "task_id": "str",
  "paths": {"input_file": "…", "output_dir": "…", "working_dir": "…?"},
  "translation_config": {"lang_in": "en", "lang_out": "zh", "pages": "1-5?",
    "no_dual": false, "no_mono": false, "use_alternating_pages_dual": true,
    "skip_clean": false, "dual_translate_first": false,
    "disable_rich_text_translate": false, "skip_scanned_detection": false,
    "ocr_workaround": false, "auto_enable_ocr_workaround": false,
    "auto_extract_glossary": true, "merge_alternating_line_numbers": true,
    "remove_non_formula_lines": false, "only_include_translated_page": false,
    "use_side_by_side_dual": false, "debug": false,
    "custom_system_prompt": "…?", "primary_font_family": "…?"},
  "runtime_limits": {"qps": 4, "report_interval_seconds": 0.5,
    "max_pages_per_part": 30, "pool_max_workers": 4, "term_pool_max_workers": 4},
  "gateways": {"main_llm": {"model": "…", "base_url": "…", "api_key": "…"},
               "ate_llm": {…},
               "layout": {"adapter": "rpc_doclayout8", "base_url": "…",
                          "requires_line_extraction": false}},
  "assets": {"glossaries": [{"path": "…", "name": "…?"}]},
  "metadata": {"metadata_extra_data": "…?"}
}
```

- 事件：`{type: progress|result|error, payload}`；result payload = `files{mono_pdf,dual_pdf,*_no_watermark,auto_extracted_glossary_csv}` + `metrics{time_consume_seconds,peak_memory_usage,pdf_total_char_count,pdf_total_char_token_count}` + `pages`（`babeldoc_adapter.py:272-306`）。
- **不直用的三个理由**：`import pyarrow` 未在依赖里（`babeldoc_adapter.py:10`，pip 装上即用但说明该路径是内部件）；`ExecutorTranslator` 硬编码 `"temperature": 0` 且无 send_temperature 开关（`tools/executor/translator.py:71-76`）——踩中冒烟坑①时无逃生口；`gateways.layout.adapter` 强制 `rpc_doclayout8`（`babeldoc_adapter.py:357-367`），还得再部署一个布局 RPC 服务，不如本地 ONNX 省事。

---

## 二、MinerU 深读笔记

- 版本 3.4.5；**License = Apache-2.0 + 附加条款**（`LICENSE.md`）：在线服务需显著署名「使用 MinerU」；MAU>1 亿或月营收>2000 万刀才需商业授权。非 AGPL，没有进程边界硬约束（但重依赖仍建议独立容器）。
- **mineru-api**（`mineru/cli/fast_api.py`，entry `mineru-api`，FastAPI+uvicorn 已在 base deps）：

| 端点                     | 说明                                                                                                                            |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `POST /file_parse`       | multipart 同步解析，等到结果一次性返回（`fast_api.py:1228-1273`）                                                               |
| `POST /tasks`            | 异步，202 返 `task_id`（:1276-1293）                                                                                            |
| `GET /tasks/{id}`        | 状态轮询：pending/processing/completed/failed + `queued_ahead`（:1296-1302）                                                    |
| `GET /tasks/{id}/result` | 结果：JSON `{results: {name: {md_content, middle_json, model_output, content_list, images(b64)}}}` 或 zip（:1305-1349,437-605） |
| `GET /health`            | 队列统计 + 协议版本（:1352-1392，`API_PROTOCOL_VERSION=2`）                                                                     |

- 表单参数（`api_request.py:92-254`）：`files`、`lang_list`、`backend=pipeline|vlm-engine|vlm-http-client|hybrid-engine|hybrid-http-client`、`effort=medium|high`、`parse_method=auto|txt|ocr`、`formula_enable`、`table_enable`、`image_analysis`、`server_url`（http-client 后端用）、`return_{md,middle_json,model_output,content_list,images}`、`response_format_zip`、`start/end_page_id`。
- **无细粒度进度**——只有任务状态轮询（对比 BabelDOC 的 stage 事件流，SSE 体验差一档）。
- **content_list.json schema**（`docs/zh/reference/output_files.md:292-394`）：按阅读序平铺 `[{type, text, text_level, bbox, page_idx, img_path, *_caption[], table_body(html), sub_type?}]`；type ∈ text/image/table/equation/code/list/header/footer/page_number/aside_text/page_footnote；`text_level` 0=正文 1/2=标题层级；**bbox 映射到 0-1000 坐标系**，`page_idx` 0-based——做页级对照锚点够用。`middle.json` 是完整块树（para_blocks→lines→spans+page_size）。
- **SDK**：README 宣称 Python/Go/TS SDK + REST API，但本 clone `projects/` 为空（子模块未拉）——HTTP 契约本身就是干净的集成面，SDK 非必需。
- **部署成本**：base 包已带 fastapi/uvicorn；`pipeline` extra = torch+transformers+onnxruntime+shapely（CPU 可跑，RAM ~2-4GB，模型经 `mineru-models-download` 从 modelscope/HF 拉，GB 级）；`vlm` 需 GPU（vllm/lmdeploy，macOS 可 mlx）；官方 `docker/compose.yaml`：`mineru-api:8000` + `mineru-openai-server:30000`（vllm）+ `mineru-router` 聚合多实例，nvidia device 预留 + `ipc: host`。**结论：pipeline 后端是最低可用配置，但仍比 BabelDOC（~50MB ONNX + 无 torch）重一个量级。**
- **角色差异**：MinerU 只解析不翻译。走 MinerU 路线 = PDF→md/content_list → **自跑 `texlate.translate` 编排**（术语/缓存/校验可复用）→ **自建双语 md 对照阅读器**（bbox+page_idx 能做页级锚定，但没有同页版式）。

---

## 三、BabelDOC sidecar 规格（接口定义 ~200 行）

设计取舍：FastAPI 薄壳 **in-process 调 `async_translate`**（拿结构化事件+tracking 文件+token 计数），容器即 AGPL 进程边界；单飞执行 + 队列排队；产物经共享卷回传。

```
babeldoc-sidecar/                       # 独立 repo 或 deploy/sidecar/babeldoc/
├── Dockerfile                          # python:3.12-slim + uv
├── app.py                              # FastAPI, ~200 行接口面
└── worker.py                           # TranslationConfig 组装 + 检测逻辑
```

### HTTP 接口

```
POST /translate                     multipart/form-data
  file:        PDF (≤50MB)
  lang_in:     str = "en"
  lang_out:    str = "zh"
  pages:       str?  "1,2,1-,-3,3-5"         → TranslationConfig.pages
  dual:        bool = true                   → no_dual = !dual
  mono:        bool = true                   → no_mono = !mono
  alternating: bool = true                   → use_alternating_pages_dual
  max_pages_per_part: int = 30               → PageCountStrategy
  qps:         int = 4                       → set_translate_rate_limiter
  model:       str  (必填或由服务端默认)
  base_url:    str?                          → 默认指向 texlate 自有 LLM 网关
  api_key:     str?                          → 默认服务端注入（BYOK 时客户端传）
  send_temperature: bool = false             → 默认 false（冒烟坑①），仅当网关需要才开
  glossary:    file? CSV                     → Glossary.from_csv
  custom_system_prompt: str?
  auto_extract_glossary: bool = true
  no_watermark: bool = true                  → WatermarkOutputMode.NoWatermark
→ 202 {job_id, status_url, events_url}

GET /jobs/{id}        → {status: queued|running|done|failed|degraded,
                         stage, overall_progress, error?,
                         fallback_paragraphs, error_paragraphs, total_paragraphs,
                         total_tokens, prompt_tokens, cache_hit_prompt_tokens,
                         peak_memory_mb, seconds}
GET /jobs/{id}/events → SSE, 逐帧转发 async_translate 事件
                        frame: {type: stage_summary|progress_start|progress_update|
                                     progress_end|finish|error, ...原字段}
GET /jobs/{id}/files/{kind} → kind ∈ dual|mono|dual_no_watermark|mono_no_watermark|
                                     auto_glossary_csv|translate_tracking
GET /healthz          → {ok, active_job, uptime}
POST /jobs/{id}/abort → config.cancel_translation()（cancel_event 已在
                        TranslationConfig 内建，progress_monitor.py:250-259）
```

### worker.py 要点（in-process 组装，等价 main.py:683-760 的翻版）

```python
translator = OpenAITranslator(
    lang_in=...,
    lang_out=...,
    model=...,
    base_url=...,
    api_key=...,
    send_temperature=job.send_temperature,  # 默认 False —— 坑①解法
    ignore_cache=False,  # 复用 babeldoc 自身缓存
)
term_translator = translator  # 或独立小模型
doc_layout = DocLayoutModel.load_onnx()  # 进程级单例，启动时预载
config = TranslationConfig(
    input_file=job_pdf,
    output_dir=job_out,
    working_dir=job_work,  # 必传 → translate_tracking.json 落盘
    translator=translator,
    term_extraction_translator=term_translator,
    doc_layout_model=doc_layout,
    pages=job.pages,
    no_dual=not job.dual,
    no_mono=not job.mono,
    use_alternating_pages_dual=job.alternating,
    qps=job.qps,
    pool_max_workers=job.qps,
    split_strategy=PageCountStrategy(job.max_pages_per_part),
    watermark_output_mode=WatermarkOutputMode.NoWatermark,
    glossaries=loaded,
    auto_extract_glossary=job.auto_extract_glossary,
    custom_system_prompt=job.custom_system_prompt,
    report_interval=0.5,
)
async for event in high_level.async_translate(config):
    sse_push(job_id, event)  # 原样转发
    if event["type"] == "error":
        fail(event["error"])
    if event["type"] == "finish":
        result = event["translate_result"]
```

### fallback 检测（假成功拦截器）

```python
def assess(job_work, result, translator):
    tracking = json.loads((job_work / f"{stem}/translate_tracking.json").read_text())
    errs, fbs, total = [], [], 0
    for page in tracking["page"]:
        for p in page["paragraph"]:
            for t in p["llm_translate_trackers"]:
                total += 1
                if t["has_error"]:
                    errs.append(t["error_message"])
                if t["fallback_to_translate"]:
                    fbs.append(p["input"][:80])
    status = "done"
    if errs and len(errs) >= total * 0.5:  # 过半段落出错 → 判失败
        status = "failed"
        error = errs[0]
    elif errs or fbs:  # 有脏段落 → 降级交付
        status = "degraded"
    if translator.token_count.value == 0 and translator.translate_cache_call_count == 0:
        status = "failed"
        error = "zero_tokens"  # 一次 API 都没打出去
    return status, errs, fbs
```

配套 sanity：mono PDF 抽 `page.get_text()` 算 CJK 占比，<阈值 → `degraded`。`ScannedPDFError` 等整文错误走 `error` 事件如实上报（`high_level.py:722-729`），建议映射 `error.code = scanned_pdf` 让主 app 提示走 MinerU OCR 兜底。

### 进程隔离与资源

- **单飞**：`asyncio.Semaphore(1)`，多余请求排队（或主 app 层排队）。babeldoc 的 RateLimiter/缓存 db 是进程单例，并发混跑没有收益只有风险。
- **容器限额**：`docker run --memory=2g --cpus=2`；`OMP_NUM_THREADS=4`；job 目录用 tmpfs/定期清理（`TranslationConfig.cleanup_temp_files` 已管 temp 目录，working_dir 由 sidecar 自管）。
- **无状态化要求**：`HOME=/data` 挂卷 → 缓存 db/字体/模型跨重启复用；job workroot `/data/jobs/<id>`，TTL 24h。
- **崩溃恢复**：单飞进程内崩 → 容器重启（restart=always），job 标 failed 由主 app 重投；不要指望 babeldoc 内部断点续翻（它没有）。

### Dockerfile 草图

```dockerfile
FROM python:3.12-slim
RUN pip install uv && uv pip install --system "babeldoc==0.6.4" fastapi uvicorn[standard] python-multipart
ENV HOME=/data OMP_NUM_THREADS=4
RUN useradd -m -d /data app && mkdir -p /data/jobs && chown -R app /data
USER app
# 构建期预热资产（onnx+字体+cmap+tiktoken 全量 sha3-256 校验下载）
RUN babeldoc --warmup
# 或离线: COPY offline_assets_*.zip /tmp/ && babeldoc --restore-offline-assets /tmp/offline_assets_*.zip
EXPOSE 8077
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8077", "--workers", "1"]
```

镜像预估：slim 基底 ~150MB + site-packages ~1.3GB + 资产 ~300-500MB ≈ **2GB 上下**。运行内存：doclayout ONNX + pymupdf + 排版峰值，2GB 限额够（`MemoryMonitor` 会把峰值写进 result，实测后校准）。

---

## 四、MinerU 分工建议与 M3 决策

| 维度       | MinerU→md 对照                                         | BabelDOC 双语 PDF                  |
| ---------- | ------------------------------------------------------ | ---------------------------------- |
| 产出物     | md/content_list → 需自建对照阅读器                     | dual/mono PDF → 复用 pdfslick 双栏 |
| 翻译编排   | 走我们 `texlate.translate`（术语/缓存/校验复用）       | BabelDOC 内部闭环（网关层复用）    |
| 进度       | 状态轮询（粗）                                         | stage 事件流（细，SSE 直转）       |
| 部署       | torch/transformers/onnxruntime + GB 级模型；vlm 要 GPU | ~50MB ONNX + 字体，纯 CPU          |
| 扫描件/OCR | pipeline `parse_method=ocr` 能吃                       | `ScannedPDFError` 拒收             |
| 单篇成本   | 解析本地免费 + 我们 LLM 编排成本                       | LLM ~$0.02-0.05 + 本地 ONNX        |
| 检测假成功 | 我们自己的校验器可控                                   | translate_tracking.json（已解）    |

**决策：M3 做 BabelDOC sidecar。** MinerU 不进 M3 主线；其生态位收窄为「扫描件/OCR 兜底 + 远期 reflow 阅读选项」，需要时以同形 sidecar 契约（submit→status/result）后补，主 app 的 job 抽象不用改。若 M3 实测发现 BabelDOC 在真实语料上的「不可接受失败率」（乱版/缺字/公式炸）过高，再回头把 MinerU→md 作为 B 方案——content_list 的 `page_idx`+`text_level` 已足够做页级对照，前端成本是一个 md 双栏渲染器。

---

## 五、与主管线的关系

- **复用**：
    1. **LLM 网关**：`base_url` 指向 texlate 自有 OpenAI 兼容网关 → BYOK/限流/语义缓存/计量/可观测在网关层统一，BabelDOC 无感。这是唯一且正确的复用面——BabelDOC 内部编排（批打包/术语提取/质量门/重试）不动。
    2. **术语表**：主路线产出的用户术语表导出 CSV → `glossaries` 注入，两条路线的译名一致。
    3. **custom_system_prompt**：注入我们的风格规则（简体/术语优先/学术口吻），替代默认 role_block。
    4. **缓存**：BabelDOC 自带 SQLite 缓存（`cache.v1.db`，按 engine+model+prompt+text 键）挂卷复用即可；与主缓存（`arxiv_id@version+model+pipeline_version+target_lang`）不合并——PDF 无 arxiv 版本语义，按 `sha256(pdf)+model+babeldoc_version` 在主 app 层做整文缓存更对口。
- **不复用（保持独立）**：翻译编排、占位符校验、断点续翻、token 计费——全部在 BabelDOC 闭环内；我们只做「提交→事件→产物→fallback 判定」的壳。
- **接入点**：主 app `POST /api/upload`(pdf) → job 路由判 PDF 来源（无 LaTeX 源码）→ sidecar 队列；SSE 事件形状与主路线 `GET /api/task/{id}` 对齐（stage/overall_progress 同名字段）；产物 `{stem}.zh.dual.pdf` 进 `GET /api/files/{id}`。
- **AGPL 边界**：sidecar 进程（容器）独立、HTTP 通信；sidecar 壳代码本身以 AGPL 发布（它 import babeldoc）；主 app 保持 Apache-2.0。可选安装策略：`pip install texlate[pdf]`/独立镜像，缺席时 PDF 上传入口提示未启用。
