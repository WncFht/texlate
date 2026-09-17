# M3 差距侦察（2026-09-17）

派工口径：docs/05 §6 M3 验收行 + §5.7–5.10 规格 + audit-2026-09-16/m3.md 现状页 → 对照 src/texlate/ 实装面，产 M3 差距清单。**不写码，只侦察**。

## 头等结论：审计已大面积过期

`audit-2026-09-16/m3.md` 判 M3「约半程」，但其红/半项的**绝大多数已被实装关闭**（当日下午至今的提交所致）。按当前代码实测，10 个 M3 行里约 **8 绿、1 设计分叉、1 红**；规格层开放项只剩 **2 个**（HTML 降级链、Redis 队列后端）加 **2 个设计分叉待裁决**。

## 逐项对账（M3 名义目标 → 当前实装）

| # | M3 名义目标（docs/05 §6/§5.7–5.10） | 审计昨日判 | 当前实测 | 状态 |
|---|---|---|---|---|
| 1 | FastAPI+SSE+SQLite 服务端 | ✅ | `server/app.py`（1600+ 行）/store/events/worker 拆包后 mixin 装配，管线+断点恢复完整 | 绿（无变化） |
| 2 | BYOK 四级入口+租户指纹 | ✅ | settings.py connections 池 + sha256 指纹 + 脱敏 | 绿（无变化） |
| 3 | SolidJS 阅读器锚点同步 + SPA 可送达 | ⚠️ 前端全/static 断链 | `server/static/`（assets/index.html/pdfjs/LICENSES）已存在；`app.py:1569 mount_spa(app)` 挂载；`pyproject.toml:65 artifacts=["src/texlate/server/static/**"]` 强制入包 | **已闭合** |
| 4 | BabelDOC sidecar（静默 fallback 检测/temperature 兼容/BYOK 透传/SSE 进度） | ⚠️ spawn-only | `server/babeldoc.py` 760 行：`--working-dir`+`assess_tracking` 静默 fallback 检测、`--no-send-temperature` 默认、api_key 走 `-c` TOML（BYOK 透传）、`on_progress` → `pdf.py:204` 进度回弹 SSE | **已闭合** |
| 5 | EPUB/DOCX 双语插译 | ❌ 501 | `export/` 实装（common/docx/epub/filters/markers/rights，lxml+bs4+python-docx）；upload 魔数路由 docx/epub 细分；`app.py:118` zh.docx/zh.epub 产物登记；worker `_run_doc` 通路 | **已闭合** |
| 6 | Dockerfile §5.10 multi-stage | ❌ | `Dockerfile` 存在：node 构建 SPA → tectonic musl sha256 钉死 → python:3.12-slim + fonts-noto-cjk；texlate:full 变体注释在案 | **已闭合** |
| 7 | `uv tool install` 分发（force-include/tectonic 矩阵/单实例锁/瘦客户端） | ⚠️ 骨架 | artifacts 入包 ✓；`compile/toolchain.py` 五平台 sha256 矩阵+原子落位+`--version` 自检 ✓；`cli.py:711 _service_lock` flock 单实例 ✓；`_thin_run/_thin_submit/_thin_wait/_thin_download` 瘦客户端 ✓ | **已闭合** |
| 8 | `texlate web` 一键可用 | ⚠️ `/` 404 | static+mount+lock 齐 → 端到端可达（代码级实证；未起服复测） | 已闭合（建议顺手 curl 复验） |
| 9 | `POST /retry{model}` 升级重翻 | ⚠️ retry 不收 model | app.py:1336 注释明示设计裁决：**model/target_lang 是 cache_key 成员，换值须新建任务**——升级重翻走新任务+cache_key dedup，功能等价但接口形不同 | **设计分叉**（见裁决 A） |
| 10 | tenant 配额可配 | ❌ | `settings.py` quota_max_tasks/quota_max_bytes + `_check_quota`/`_load_quota` | **已闭合** |
| — | fixloop 接入 server 管线 | ❌（跨里程碑缺口） | `worker/compile.py` 实跑 `run_fixloop` + `_fixloop_summary` + reject 降级——M2 收益已进 web 路径 | **已闭合** |
| — | md_zip 生产者→HtmlPane 可达 | ❌（断链） | `compile.py:980 _build_md_zip` 登记产物 | **已闭合** |

## 仍开放项

### G1 — HTML 降级链（规格内真缺口，唯一用户可见功能缺口）

- 名义：`/html/{id}`（先探无版本形式）→ LaTeXML DOM 分块翻译 → HtmlPane 呈现（docs/05 §5.x 行 187「M3 后半实现」）。
- 现状：`latexml` 零命中、无 `/html` 路由、`html` 只出现在 URL 识别/限流白名单。降级链三级仍是 e-print ✓ / **HTML ✗** / BabelDOC ✓。
- 工作量粗估：**3–5 天**。LaTeXML 运行时获取与打包是大头（Perl 重依赖，容器/分发面都要重估——可考虑 latexmls 服务化或仅文档态声明依赖）；DOM 分块翻译器 ~300-500 行（复用 export 包 lxml/bs4 模式与 translate/translate_list 契约）；`/html/{id}` 路由+入库小面 <1 天。
- 建议：**波次一**。它是 M3 规格内唯一用户可见功能项；且与 F 桶观测呼应（e-print 拿不到时的第二条命）。注意 arXiv HTML 覆盖率本身有限（~近年新提交才有），价值=补齐兜底非主通道。

### G2 — Redis 队列后端（server 部署形态项）

- 名义：§5.10 server 形态 REDIS_URL 队列。
- 现状：全仓零命中；TaskRunner 进程内 asyncio.Queue 单写者（本地形态自足）。
- 工作量粗估：**1–2 天**（backend 抽象 + Redis runner + settings + 测试）；若裁决本地-first 形态不需要多实例队列，可直接登记「不适用」消项。
- 建议：**裁决后动**——先定产品形态再花工。本地形态下硬上 Redis 是负资产。

### G3 — retry{model} 接口形（设计分叉，待裁决）

- 规格写 `POST /retry{model}`；实装明示「换 model 建任务」（cache_key 口径）。功能等价（新任务+dedup 即升级重翻），但 API 面与规格不符。
- 裁决项：**A)** 认实装语义 → 改规格文档一行（推荐，语义更干净）；**B)** 认规格 → retry 加 model 旁路（破坏 cache_key 不变式，不建议）。
- 工作量：A 案 <0.5 天。

### G4 — BabelDOC 集成形态（设计分叉，建议维持现状）

- 规格写 in-process `async_translate` FastAPI sidecar ~200 行；实装走 CLI spawn（AGPL 进程边界更安全 + `--working-dir` 已解追踪）。
- 裁决项：维持 spawn（推荐——隔离与追踪双赢），登记规格差异即可。<0.5 天文档账。

## 建议先后

1. **G3 裁决**（0.5 天，阻塞口径统一）
2. **G1 HTML 降级链**（3–5 天，M3 收官最后一项实功；LaTeXML 获取面先评 0.5 天 spike）
3. **G2 Redis 裁决**（形态决策，可能 0 工）
4. **顺手验证**：`texlate web` 起服 curl `/` 200 + `/api/health`——把「代码级闭合」升级为「端到端实证」。

## 残余风险注记

- 所有「已闭合」判定基于代码静态核实（文件存在/接线在/测试在案），未逐项起服复测——G 项收尾时建议一轮 `/`+translate+reader+babeldoc 全链冒烟坐实。
- 审计 m3.md 建议**归档重标**（标 superseded）——否则后续按它派工会重复立项已闭合项。

src/git 未动，45min 内交付。
