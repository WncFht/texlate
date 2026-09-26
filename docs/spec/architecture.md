# 架构规范

TeXlate 把 arXiv LaTeX 源码经 LLM 段落级翻译重编译为中文 PDF，供双语对照阅读。本文描述现行实现的管线形态、模块边界与数据契约——与代码冲突以代码为准；各层细节规范与同名单元（`spec/arxiv-source.md` 等）互补，实测证据引 `research/` 对应件不复述。

## 1. 端到端管线

一条管线脊椎（`pipecore.py`）承载三种部署形态（§4）；worker 与 e2e 两臂消费同一组 `*_job`/`*_run` 函数，无双份实现。

```
取源                    解析                        翻译                 编译出件
─────────────────  ────────────────────────  ─────────────────  ──────────────────────────────
acquire_source ──► route_project(引擎路由) ──► XlatPipeline      splice 写回 zh/ 树
  (e-print/upload/    find_main_tex            ·异步 worker       prepare_chinese(ctex 注入)
   share/html)        normalize_project        ·[n] 批协议        engine.compile(tectonic/xelatex)
                    scan_tex_tree             ·占位符 reconcile    judge(clean/partial/fail)
                     ·v2 Gullet+Segmenter     ·L0 校验           修复链: precheck→L2→fixloop
                     ·四级分流                ·段缓存/断点续       embed ToUnicode(cmap)
                     ·chunks 入库             ·glossary 5 层      build_alignment(dual.json)
                                                                   → 产物登记(files 表)
```

异构臂共用同骨架：HTML 臂（`kind=arxiv_html`）以 `arxiv/html.py` DOM 分块替代 LaTeX 解析、splice 以 `reinsert` 回插、`zh.html` 替代 PDF；PDF 臂（`kind=arxiv_pdf`）走 babeldoc sidecar[^pdf-path]；share 臂以 `_stage_share_apply` 对账包译文替代翻译段（`server/worker/core.py::_run_tex`/`_run_share`）。

## 2. 阶段契约

### 2.1 取源（`arxiv/`）

输入 arXiv id（可钉版）→ 钉版缓存目录 `extracted/` 源树。限速/退避/断路器/日预算、HEAD 预检、三态判别、安全解包、主文件定位、降级裁决全部在本层收口，规范见 `spec/arxiv-source.md`。server 侧 upload 物化走同一解包件（`unpack_sniffed`/`unpack_zip`）。

### 2.2 路由与规范化（`compile/`）

`route_project`（`compile/engine/_route.py`）在编译前静态决策引擎序[^engine-matrix]：EPS/pstricks 硬墙 → xelatex 优先；minted frozencache → tectonic 优先；`\documentstyle` 降 `latex209_suspect` 标记（试编不定死，fixloop gate 兜底）；产物 `RouteDecision(engines, reasons, non_utf8, latex209_suspect)`。`find_main_tex`/`classify_no_main`（`compile/mainfile.py`、`compile/inject.py`）定位主文件；`normalize_project`（`compile/normalize.py`）做引擎前工程规整（aux/bib 转码、宏件归位等）。

### 2.3 半解析（`latex/`）

唯一解析路径 = v2 token 流：`gullet/`（宏展开嘴）+ `segmenter/`（块切分），入口 `latex/api.py::parse_tex`/`parse_file`/`scan_tex_tree`[^seg-integration]。产出 `ScanResult`：`chunks[]`（可译块，byte span + content + context）、`ph_map`（占位符↔原片段）、`inputs[]`（`\input` 解析记录）。`scan_tex_tree` 四级分流：dotfile 跳过 → `.rtx.tex` 跳过 → `.code.tex` 记 support → 解析崩记 fault → 无散文记 support → 余者 parsed——单文件崩不拖全树。`\input` 展平由 gullet 在 `flatten=True` 时内联；占位符件 `placeholder.py` 管 `[[TYPE_n]]` 令牌。回写面 `reconstruct.py`：identity 校验 + splice + `cjk_glue_fix`/`cjk_punct_close_guard`/`unicode_math_fix` 等译后修整。

### 2.4 翻译（`xlat/`）

`XlatPipeline`（`xlat/pipeline.py`）异步 worker 池消费 `ChunkIn`：`batch.py` 组批（≤12000 字符/≤32 项/≥2500 字符下限，`CHUNK_HARD_LIMIT=6000` 超长块先 `split_long_chunk`），线上协议 `[n]` 编号对位 + `@@` 分隔兜底（`placeholders.py` reconcile 防令牌漂移）；`client.py` 多 dialect 网关客户端（auto/openai/anthropic/responses，缺省指向内部 OpenAI 兼容网关）；`glossary.py` 五层术语（user > paper-local > category > default > ph）；`state.py` 原子 `state.json` 断点续翻；`retry.py` 重试阶梯；`validate/l0.py` 规则校验器随批执行。译文经 `ChunkResult` 落 chunks 表，失败块按 `delivered` 口径记 status。

### 2.5 编译与判定（`compile/`）

splice（`latex/reconstruct.py`）把译文写回 `zh/` 树 → `prepare_chinese`（`compile/inject.py`：`CTEX_LINE`/`XECJK_BLOCK` 注入，拒则 `InjectRejectError` → `partial`+`reject_at=inject`，zh-src.zip 先行落盘）→ `engine.compile`（`compile/engine/`：`Engine` 协议 + xelatex/tectonic 两实现，`engine_for` 构造；caps/sandbox/proc 圈资源界）→ `judge`（`compile/judge.py`：`Verdict` clean/partial/fail，`expect_cjk` 门=chunks≠0 要求 CJK 字形）。产物对账 `target_probe`/`deps_diff`（`compile/probe.py`），编译日志解析 `texlog.py`/`compile/logparse.py`/`loginfo.py`。

### 2.6 修复链（`pipecore` + `repair*.py` + `compile/fixloop/`）

三段阶梯，两闸决议（`RepairPolicy`：L2/fixloop 各自 显式参 > options > `TEXLATE_NO_*` env，默认全开；precheck 无独立闸、随 fixloop 开关）：

1. **precheck**（`precheck_job`/`repair.py`）：编译前环境级修复（缺包探测补装、209 预处理等）。
2. **L2 修复**（`l2_repair_job`/`repair_l2.py`）：日志归因到 chunk/环境 → 回灌译文重 splice 重编（归因簇 + env judge）。
3. **fixloop**（`fixloop_job`/`compile/fixloop/`[^fixloop-rules]）：yaml 规则引擎（`engine.py`/`actions.py`/`ruleset.py` 三件套 + `builtins` 十二叶 facade + `cases`/`ctan`/`logparse`/`_yamlish` 支撑 + `llm_hook`），按日志签名改写源树迭代重编；`fixloop_flags_tail` 携跨引擎臂（tectonic 丢 flag → xelatex 重编）。

修复走尽仍 fail → `fault`/`fixloop_exhausted`；成功出 PDF 后经 `repair.py::embed_tounicode_quiet` + `compile/cjkmap.py`（GB1 cmap 资产 `compile/cmaps/`）嵌 ToUnicode 层，保证复制/搜索可用。

### 2.7 对齐与出件（`align.py`/`share.py`/`export/`）

`build_alignment`（`align.py`[^align-probe]）对 en/zh 双 PDF 做 named-dest 锚点配对 → `dual.json`（阅读器滚动同步依据）。`share.py` 打 `.share.zip`（manifest.json + zh-src.zip + dual.json + 可选 zh.pdf）供他人免翻译复用，`share_key` = sha256(arxiv_id|ver|model|prompt_ver|lang|glossary_hash|pipeline_ver) 七组分；`index_lookup`/`share_pack_publish` 消费侧对账。`export/` 产双语 EPUB/DOCX（`epub/`/`docx.py`/`filters.py`/`markers.py`，复用 `XlatPipeline` 插译；`rights.py` EPUB DRM 检测——命中即拒，无放行开关）。

## 3. 包结构与责任边界

```
texlate/
  arxiv/      获取层：fetch/ratelimit/sniff/unpack/cache/locate/meta/html（spec/arxiv-source.md）
  latex/      半解析：api/model/reconstruct/placeholder/prose/tables/flatten/macro_table
              + gullet/ 展开机 + segmenter/ 块切分（唯一解析路径）
  xlat/       翻译编排：pipeline/client/batch/prompts/glossary/autogloss/state/retry/
              placeholders/mock + terms/ 术语表资产
  validate/   校验三层：l0 规则 / l1 tree-sitter / l2 日志 + report.aggregate
  compile/    编译面：engine/(route+xelatex+tectonic) inject normalize probe judge
              fixloop/ cjkmap mask toolchain sandbox deps ctan loginfo logparse
              latex209 layout mainfile proc seams shadow transcode + cmaps/ 资产
  server/     Web 后端：app/settings/auth/store/events/upload/babeldoc/staticfiles/
              providers/http/logredact + routers/ + worker/（管线执行器）
  cli/        typer 命令面：fetch/parse/run/web/export/share/tools/version/doctor
  export/     EPUB/DOCX 双语出件
  textutil/   编码/文本/正则/env 单源件（cjk/decls/encoding/mask/cite/ifscan/nets/osutil）
  chunk.py    ChunkIn 数据契约（顶层——arxiv 层不许上向 import，契约只能居根）
  pipecore.py 管线政策脊椎：状态映射/扫描/翻译/编译判定/修复三段/RepairPolicy/ReportSink
  e2e.py      本地编排：pipeline_run/pipe_condition/base_condition（CLI run 与 bench 共用）
  align.py    双语锚点对齐     share.py   分享包构建/消费     redlines.py 红线注册表
  repair.py   修复低层件      repair_l2.py L2 归因簇         texlog.py  日志 file-stack
  logsetup.py 日志装配单源
web/          SolidJS+Vite+pdfslick 阅读器前端（独立 toolchain）
```

边界纪律：`arxiv/` 不 import 上层（`ChunkIn` 因此居 `chunk.py` 顶层）；`pipecore.py` 是 e2e 与 worker 的公共脊椎，管线语义改动先落这里；`server/worker/seams.py` 是 worker 唯一 monkeypatch 面；`textutil/` 承载跨层正则与 `TEXLATE_*` env 名单源；babeldoc 只经子进程边界调用（AGPL 隔离，`server/babeldoc.py`）。

## 4. 部署形态

| 形态         | 入口                                                                | 管线承载                                                                                   | 状态/产物                         |
| ------------ | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------- |
| CLI          | `texlate run\|fetch\|parse\|export\|share\|tools\|doctor`（`cli/`） | `e2e.py` 本地链（mock 或真翻译[^e2e-mock]）                                                | 工作目录内 report/产物            |
| CLI 瘦客户端 | `texlate run --server URL`（`cli/thin.py`）                         | 提交到 server，2s 快照轮询                                                                 | 产物下载 + sha256 校验            |
| Server       | `texlate web` / `python -m texlate.server`（`server/app.py`）       | `PipelineWorker` mixin 组合（fetch/parse/translate/compile/share/pdf/html/retranslate 段） | SQLite Store + SSE + 任务目录产物 |
| SPA          | `server/staticfiles.py` 挂载 `web/` 构建物                          | 经 REST/SSE 消费 server                                                                    | 双语阅读器                        |

server 侧要点[^web-layer]：`Store`（`server/store/`）SQLite 六表（tasks/chunks/files/translation_cache/task_events/task_usage）；任务 11 态机 = active `{queued,fetching,parsing,translating,compiling}` + terminal `{done,partial,fault,cancelled,interrupted,needs_auth}`，retry 只允许自 `{fault,partial,cancelled,interrupted,needs_auth}`；`TaskRunner`（`worker/runner.py`）`asyncio.Queue` 串行执行 + 心跳 + 取消 + retranslate 工作项；`EventBus`（`events.py`）SSE，`task_events` 滚动上限 2000 供断线 replay；启动恢复扫中断任务与孤儿任务目录（`app.py` lifespan）。BYOK：`X-Texlate-*` 请求头携带的 key/base_url/dialect 只进内存 `Secrets`，永不落盘；`request_gate_mw` 收敛 loopback + Host + Origin/Sec-Fetch-Site，server 模式另要 401 鉴权（`auth.py`/`settings.py`）。

## 5. 数据契约

### 5.1 块模型

`chunk.py::ChunkIn(chunk_id, content, kind, ph_fragments)` 是翻译面最小单元；`kind` 归一六类 `para/caption/section_title/abstract/table_text/env_text`（`KIND_ALIASES` + `xlat/prompts.py::normalize_kind`）。server 落库行形 `{seq, chunk_id, src_file, byte_start, byte_end, kind, src_text}`，`chunk_id` 由 `chunk_db_id(rel, start, end)` 派生——与 `ScanResult.chunks` 按 byte span 对账；`ph_fragments` 携占位符↔原片段映射武装 placeholder 修复臂。HTML 臂同契约（`doc_chunks` 产 `ChunkIn`，`data-chunk` 锚与 `chunk_id` 1:1）。

### 5.2 两级缓存与幂等

- **source tier**：`SourceCache` `{id}v{ver}` 钉版目录（`spec/arxiv-source.md` §4）。
- **task tier**：`cache_key_for(arxiv_id@ver|model|pipeline_version|lang[|src=][|fm=][|k=])` 任务级 dedup——只复用 `done` 行产物（partial 不克隆，防毒传播）；latest-alias 任务定版后 `_post_resolve_reuse` 补查钉版键并 re-key。idempotency_key 单列唯一索引防重复入队。
- **segment tier**：`SegmentCache` 读写 `translation_cache` 表 `{cfg_hash}:{seg_key}`——跨任务/跨文献段级复用[^shared-cache]。
- **哨兵幂等**：`.fetch-done`/`.base-done`/`.splice-done`/`.compile-done` 四个盘哨兵实现段级幂等与 resume 快进；译文变更摘 `.splice-done` 逼重 splice（`worker/translate.py::_invalidate_splice`）。
- **xlat 断点**：`xlat/state.py` 原子 `state.json` 记批级进度，重跑跳过已交付块。

### 5.3 产物面与事件

`files` 表登记任务产物，`KIND_URL`（`worker/_common.py`）映射下载 URL：`src.tar/en.pdf/zh.pdf/dual.pdf/dual.json/zh-src.zip/compile.log/md/zh.docx/zh.epub/src.html/en.html/zh.html/share.zip`。`task_events` 承载 stage/progress/chunk 实况与 done 终帧（warnings 截 200 条）；`snapshot` 供迟到客户端一次性还原。`PROGRESS` 表（`worker/_common.py`）是各段进度百分比的单源。

## 6. 横切面

- **日志**：`logsetup.py::configure_logging` 唯一装配点——RichHandler stderr + 轮转文件 + `RedactFilter` 脱敏（`server/logredact.py` 同款服务端面）；`TEXLATE_LOG`/`TEXLATE_LOG_FILE` 控制级别与落盘。
- **离线**：`--offline`/`TEXLATE_OFFLINE=1` → 取源零网络（`acquire_source` `_offline_phase`：钉版精确查/最高已缓存版/`offline_no_cache`），不静默联网；本地目录源不受影响。
- **front-matter**：`FRONT_MATTER_NAMES={abstract,title,author}`，`TEXLATE_FRONT_MATTER` env 缺省（默认 `abstract,title`），任务 `options.front_matter` 覆盖，实跑集以 `options.front_matter` 布尔图持久化（`ran_front_matter` 还原）。
- **BYOK/密钥面**：LLM 凭据只存在请求内存 `Secrets` 与（可选）`settings` 配置；日志面经 RedactFilter 脱敏；段缓存按 key 指纹分桶（`k=` 段），跨租户不串。
- **修复开关**：`TEXLATE_NO_L2`/`TEXLATE_NO_FIXLOOP` env 经 `RepairPolicy` 三级解析（显式参 > options > env > 默认开）；precheck 无独立闸，随 fixloop 开关。
- **env 名单源**：`textutil` 提供 `env_flag`/`env_str` 解析件；各层 `TEXLATE_*` 变量经它读，不各自 `os.environ`。

### 参考文献

[^web-layer]: TeXlate 调研档案 `research/product/2026-09-15-web-layer.md`：server API/SSE/SQLite/BYOK/前端形态规格。

[^e2e-mock]: TeXlate 调研档案 `research/product/2026-09-14-e2e-mock-pipeline.md`：mock 管线全链验证记录。

[^seg-integration]: TeXlate 调研档案 `research/latex/segmenter-integration.md`：v2 Gullet+Segmenter 唯一解析路径的切换过程。

[^engine-matrix]: TeXlate 调研档案 `research/latex/engine-matrix.md`：tectonic/xelatex 路由矩阵实测。

[^fixloop-rules]: TeXlate 调研档案 `research/latex/fixloop-rules.md`：fixloop 规则引擎设计。

[^shared-cache]: TeXlate 调研档案 `research/product/2026-09-16-shared-cache.md`：段缓存分桶与跨租户取舍。

[^pdf-path]: TeXlate 调研档案 `research/latex/pdf-path.md`：babeldoc sidecar 规格与 AGPL 边界。

[^align-probe]: TeXlate 调研档案 `research/latex/alignment-probe.md`：named-dest 锚点同步实测。
