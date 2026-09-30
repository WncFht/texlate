# PDF 通路设计：BabelDOC + MinerU 深读与 sidecar 决策

> **结论**：PDF 双语通路选 BabelDOC sidecar 而非 MinerU→md——dual PDF 即旗舰 UX 且复用现有双栏阅读器，MinerU 收窄为扫描件/OCR 兜底。「静默 fallback 保原文」有可靠检测手段（translate_tracking.json），复用面收敛到 OpenAI 兼容网关 + glossary CSV + custom_system_prompt。
> **状态**：现行（已落地为 `server/babeldoc.py`；**实现形与本文 §4 的 in-process 提案有偏差——实际选 spawn-CLI 契约**，落地形态见 §4.4 注记）
> **日期**：2026-09-15

## 1. 路线裁决

冒烟验证 BabelDOC 可行（60s/15 页、LLM ~$0.02–0.05/篇）。选它的理由：dual PDF 即旗舰 UX，主管线 pdfslick 双栏阅读器直接复用、零新增前端；MinerU→md 路线反而要自建「双语 md 对照阅读器」+ 部署更重的本地模型栈（torch/transformers/GB 级模型，vlm 要 GPU）。MinerU 保留两类兜底：扫描件/OCR PDF（BabelDOC 抛 `ScannedPDFError` 或乱版）+ 远期 reflow 式 md 阅读选项。

## 2. BabelDOC 深读要点（0.6.4，AGPL-3.0）[^babeldoc]

### 2.1 关键 flag

`--pages` 1-based 页选；`--qps` 全局漏桶（默认 4，`--pool-max-workers` 缺省=qps）；`--max-pages-per-part` 分段串行翻译再合并（大 PDF 控内存，进度事件带 `part_index/total_parts`）；`--generate-offline-assets`/`--restore-offline-assets` 打包/还原全量资产 zip（sha3-256 逐个校验——air-gap/镜像构建利器）；`--warmup` 预热 ONNX+ 字体+cmap+tiktoken；`--no-send-temperature` 请求体不带 temperature（私有网关兼容性坑的解法）；`--no-dual`/`--no-mono`/`--use-alternating-pages-dual`/`--watermark-output-mode` 产物控制；**`--working-dir` 非 None 即触发 tracking JSON 落盘**（检测假成功的关键，见 §3）；`--custom-system-prompt` 替换 LLM prompt 的 role_block（注入风格的口子）；`--glossary-files`/`--no-auto-extract-glossary` 术语表；`--openai{,-model,-base-url,-api-key}` 唯一翻译服务；`--openai-term-extraction-*` 术语提取可拆独立小模型；`--only-include-translated-page` 配合 pages 只出被译页。全部 TOML 键 = CLI 长选项名。

### 2.2 管线与缓存

阶段权重：DetectScannedFile(2.45) → LayoutParser(14.03) → TableParser(1.0) → ParagraphFinder(6.26) → StylesAndFormulas(1.66) → AutomaticTermExtractor(30.0) → ILTranslator(46.96) → Typesetting(4.71) → FontMapper(0.61) → PDFCreater(1.96)。翻译主路径把段落打包 JSON 数组 `[{id,input,layout_label}]` 一次调用；术语提取（术语学家 prompt 产 `[{src,tgt}]`）≤600 token 或 ≤12 段一批，产出 CSV 注入后续翻译请求。翻译缓存 peewee+SQLite 落用户缓存目录（`babeldoc/cache.v1.db`），键 = `engine + engine_params(model/prompt/temperature) + original_text`——换模型/换 prompt 自动不串；`CACHE_FOLDER` 缺省为用户缓存目录，容器里用 `HOME` 控制位置。

### 2.3 静默 fallback —— 检测是可行的

三层兜底，前两层记 tracker、第三层只 log 不上报：

1. **批级异常**（JSON 解析失败、数量不齐、非 429 API 错误）→ 整批 `set_fallback_to_translate()` 逐段重投单段调用；
2. **质量门**（同文 edit_distance<5 且 >20tok、长度比出界 0.3–3、非字符串/越界 id）→ 单段 `should_fallback` 重投；
3. **单段异常吞没**：`except Exception → log → return`，段落保留原文，**无重试无事件**——OpenAI 层 `@retry` 只覆盖 `RateLimitError`（100 次退避），`BadRequestError`/连接错误冒泡后被这层吞掉，PDF 照常产出但含英文原文，这就是「假成功」。

检测信号按可靠性排序：`translate_tracking.json`（**只要 `--working-dir` 非 None 必写**——段落树 → `llm_translate_trackers[]` → `{has_error, error_message, fallback_to_translate, placeholder_full_match}`，sidecar 每单传 job 目录即可）；日志行 `Translation completed. Total/Successful/Fallback`；token 计数器（`total==0 且 cache_call==0` → 全文未译，坑：全 cache 命中也是 0，必须结合 tracking json）；mono PDF `page.get_text()` CJK 占比抽查兜底。整文失败（`ScannedPDFError` 等）走 `error` 事件如实上报，这层不静默。

### 2.4 进度事件与打包

`async_translate` yield 结构化 dict：`stage_summary`（各 stage 权重，一次）→ `progress_start/update/end`（`{stage, stage_progress, overall_progress, part_index, total_parts}`）→ `finish{translate_result}` / `error{error}`，节流 `report_interval`（默认 0.1s）——可直接转 SSE。

打包面：依赖粗估 site-packages ~1.2–1.5GB（科学计算栈占大头）；资产 = doclayout ONNX（~50MB，HF/modelscope 竞速）+ ~127 个嵌入字体 + 146 个 cmap + tiktoken blob，全量 sha3-256 校验；Linux CPU provider、macOS CoreML；`MemoryMonitor` 全程采 PSS 峰值写进 result；全局 RateLimiter 是进程内单例 → **一个实例一次只跑一单**最稳。官方树内 executor 服务不建议直用：强制 rpc_doclayout 远程布局、`pyarrow` 未声明依赖、`ExecutorTranslator` 硬编码 `temperature:0` 无逃生口——但其 request schema（paths/translation_config/runtime_limits/gateways/assets 分组）是现成的接口设计参考。

## 3. MinerU 摘要（兜底生态位）

MinerU[^mineru] 3.4.5，Apache-2.0 + 附加条款（在线服务需署名、超大 MAU/营收才需商业授权），非 AGPL 无进程边界硬约束。自带 `mineru-api`（FastAPI）：`POST /file_parse` 同步、`POST /tasks` 异步 + 状态轮询 + `/result` 取 `{md_content, middle_json, content_list, images}`——**无细粒度进度只有状态轮询，SSE 体验差 BabelDOC 一档**。`content_list.json` 按阅读序平铺 `{type, text, text_level, bbox(0-1000 系), page_idx(0-based)}`，做页级对照锚点够用。只解析不翻译：走它 = PDF→content_list → 自跑 texlate 翻译编排 → 自建双语 md 阅读器。pipeline 后端 CPU 可跑但仍比 BabelDOC 重一个量级。

## 4. sidecar 规格

### 4.1 接口面

`POST /translate`（multipart：file/pages/dual/mono/alternating/max_pages_per_part/qps/model/base_url/api_key/send_temperature/glossary/custom_system_prompt/auto_extract_glossary/no_watermark）→ 202 `{job_id, status_url, events_url}`；`GET /jobs/{id}` → `{status: queued|running|done|failed|degraded, stage, overall_progress, fallback_paragraphs, error_paragraphs, total_tokens, peak_memory_mb, seconds}`；`GET /jobs/{id}/events` SSE 逐帧转发；`GET /jobs/{id}/files/{kind}` kind ∈ dual/mono/no_watermark/auto_glossary_csv/translate_tracking；`POST /jobs/{id}/abort`（`cancel_translation` 内建）。

### 4.2 fallback 判定（假成功拦截器）

解析 `working_dir/<stem>/translate_tracking.json` 累计段落树：过半段落 `has_error` → `failed`；有错或有 `fallback_to_translate` 段 → `degraded`；`token_count==0 && cache_call==0` → `failed(zero_tokens)`；配套 mono PDF CJK 占比 sanity。`ScannedPDFError` 映射 `error.code=scanned_pdf` 让主 app 提示走 MinerU 兜底。

### 4.3 进程隔离与资源

单飞（Semaphore(1) 或队列排队）——RateLimiter/缓存 db 是进程单例，并发混跑没有收益只有风险；容器 `--memory=2g --cpus=2` + `OMP_NUM_THREADS=4`；`HOME=/data` 挂卷使缓存/字体/模型跨重启复用；job workroot TTL 24h；崩溃 → 容器重启 + job 标 failed 由主 app 重投（babeldoc 没有断点续翻）。镜像预估 ~2GB（slim + site-packages + 资产），构建期 `babeldoc --warmup` 预热。

### 4.4 落地形注记（2026-09-20 核代码）

原提案是 in-process `async_translate` 包 FastAPI 壳；**实际实现选择 spawn-CLI 契约**（`server/babeldoc.py`）：babeldoc 不进产品 venv/import，只 spawn CLI——AGPL 隔离目标相同、机制更轻。要点：`--working-dir` 必传（tracking JSON 落盘的前提）；`--no-send-temperature` 默认；api_key 经 `-c` TOML 注入而非 argv（防进程列表泄漏）；pty 合并 stderr 到 stdout 刮进度事件；不用 `--max-pages-per-part`（part 目录会被 rmtree）。

## 5. 与主管线的关系

复用三点：**LLM 网关**（`base_url` 指向内部 OpenAI 兼容网关 → BYOK/限流/语义缓存/计量在网关层统一，BabelDOC 无感——唯一且正确的复用面，其内部编排不动）；**术语表**（主路线用户术语表导出 CSV → `glossaries` 注入，两路线译名一致）；**custom_system_prompt**（注入风格规则替代默认 role_block）。缓存各自独立——BabelDOC 自带 SQLite 键按 engine+model+prompt+text；主 app 层按 `sha256(pdf)+model+babeldoc_version` 做整文缓存更对口（PDF 无 arxiv 版本语义）。翻译编排/占位符校验/断点续翻/token 计费全在 BabelDOC 闭环内，我们只做「提交→事件→产物→fallback 判定」的壳。

**AGPL 边界**：sidecar 进程独立、HTTP 通信；sidecar 壳代码本身以 AGPL 发布（它 import/spawn babeldoc），主 app 保持 Apache-2.0。可选安装策略 `texlate[pdf]`/独立镜像，缺席时 PDF 上传入口提示未启用。

## 6. 决策矩阵

| 维度       | MinerU→md 对照                        | BabelDOC 双语 PDF                  |
| ---------- | ------------------------------------- | ---------------------------------- |
| 产出物     | md/content_list → 需自建对照阅读器    | dual/mono PDF → 复用现有双栏阅读器 |
| 翻译编排   | 走 texlate 编排（术语/缓存/校验复用） | BabelDOC 内部闭环（网关层复用）    |
| 进度       | 状态轮询（粗）                        | stage 事件流（细，SSE 直转）       |
| 部署       | torch + GB 级模型；vlm 要 GPU         | ~50MB ONNX + 字体，纯 CPU          |
| 扫描件/OCR | `parse_method=ocr` 能吃               | `ScannedPDFError` 拒收             |
| 单篇成本   | 解析本地免费 + LLM 编排成本           | LLM ~$0.02–0.05 + 本地 ONNX        |
| 假成功检测 | 自有校验器可控                        | translate_tracking.json（已解）    |

若实测发现 BabelDOC 在真实语料上的不可接受失败率（乱版/缺字/公式炸）过高，回头把 MinerU→md 作 B 方案——`page_idx`+`text_level` 已足够做页级对照。

### 参考文献

[^babeldoc]: funstory-ai. BabelDOC — PDF scientific paper translation and bilingual comparison library (0.6.4, AGPL-3.0). GitHub. [github.com/funstory-ai/BabelDOC](https://github.com/funstory-ai/BabelDOC)

[^mineru]: opendatalab. MinerU — document parsing tool (3.4.5, Apache-2.0 + 附加条款). GitHub. [github.com/opendatalab/MinerU](https://github.com/opendatalab/MinerU)
