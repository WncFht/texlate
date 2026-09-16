# share-live-2026-09-16：share 导入链真实 HTTP 验证

> `POST /api/share/import`（8dc644d）此前只有 TestClient 双实例覆盖；本报告用真 server（uvicorn 实进程）+ 真网关配置把 shared-cache.md §5 信任链整条跑通。生产臂复用 live-smoke2 已完成任务现场（`tmp/live-smoke2-data/tasks/t_aea8a22c2e5469d4`，cond-mat/0408438v1，60 chunks），导入臂用全新独立 data dir（`tmp/share-live-b/`，绝对路径，预置 src-cache 走 HIT——OK 路径当日 live-smoke2 已覆盖）。

## 时间线（本地时）

- 16:29 `uv run texlate share pack t_aea8a22c2e5469d4 --data-dir tmp/live-smoke2-data -o bench/results/share-live-2026-09-16/pkg` → `18615c27cff0….share.zip`（586KB）。CLI `_share_verify_pipeline` 对任务行 cache_key 双形态（v1/latest）重算通过——生产任务存的是 latest 形 key（24bea433…）。
- 16:30 实例 B：`TEXLATE_DATA_DIR=/home/fanghaotian/src/texlate/tmp/share-live-b uv run texlate web --port 8917`；`PUT /api/settings` 写真网关（base_url=http://100.105.212.52:3003, model=swe-2-medium, lang=zh-CN）。
- 16:31:24.77 `POST /api/share/import`（multipart `file`）→ 202 `t_a29c5b323a8ee111`。
- 16:31:28.46 **done**——3.7s 全链：fetch（src-cache HIT）→ parse → share_apply → compile（tectonic，verdict clean）→ done。
- 16:35–16:36 重用断言 + 两条负面用例（详见断言矩阵）。
- 16:38 进程全杀（port 8917 释放、gwcap inflight 归 0、采样器已停）。

## 断言矩阵（全 PASS）

| 断言 | 结果 | 证据 |
|---|---|---|
| 任务行 kind=share，arxiv_id/model/lang 记 manifest 真值 | ✅ `cond-mat/0408438v1` / `swe-2-medium` / `zh-CN` | snapshot-import.json, db-dump.json |
| `_stage_share_apply` 对账日志 | ✅ task_events seq7：`share apply: matched=60/60 dropped=0 missed=0 extra=0` | db-dump.json |
| 产物六件登记 + reader 200 + dual.json 全带 zh | ✅ 六件各 GET 200（src.tar/en.pdf/zh.pdf/zh-src.zip/dual.json/compile.log）；reader view=pdf 双 documents；60/60 zh 非空 | reader-import.json |
| 零 token | ✅ tasks.tokens=0；task_usage 空表；import 窗口（16:31:23–16:35:31）gwcap inflight 全程 0；server-B.log 无网关访问 | gwcap-samples.log, db-dump.json |
| 钉版寻址重用 | ✅ `POST /api/arxiv/cond-mat/0408438v1/translate {"model":"swe-2-medium"}` → 200 `reused:true` → 同一 task_id；同包二次 import → 200 reused | translate-pinned-resp.json, reimport-resp.json |
| §5 信任边界（不信包内产物） | ✅ 字节级实证：B 侧 `tasks/t_*/share/zh.pdf` = 生产 zh.pdf（ce014c4e…，证据件不进产物面）；服务端出的 `zh.pdf` = f6c9c572… 本地重编（与 reader version 字段吻合）；dual.json/zh-src.zip 同为本地再生 | 见「哈希对账」 |
| 负面①篡改 zh.pdf 一字节 | ✅ 400 `share_invalid`「sha256 mismatch for artifact: zh.pdf」——端点机械校验层拦，不建行不入队 | import-tampered-resp.json |
| 负面②对账零命中（dual.json en 全换 + key_parts.model=contributor-model-x 绕 dedup） | ✅ 202 → **partial + code=share_verify + reject_at=share_verify + retryable=false**；任务行 model 记 manifest 值（provenance 顺带验证）；tokens=0 | snapshot-zeromatch.json |

### 哈希对账（A 生产 vs B 服务 vs 包内证据）

- src.tar：A=B=包同源（a2b51fe3…，皆取自同一 src-cache raw blob）。
- zh.pdf：A=包内证据=ce014c4e…；B 服务件=f6c9c572…（本地重编，尺寸同 390264B）。
- en.pdf：A=f71fc7f7…，B=694c5d4f…（=reader original version）。
- dual.json / zh-src.zip：A≠B（本地再生；chunks 译文集合 0 差异——见下）。
- compile.log：A=B（TeX 日志字节确定）。
- B 侧 zh/lanlcologne2004.tex 与 A 侧仅一处换行差异（author 块 86–87 行折行），dual.json 60 条 zh 全文 0 差异。

## 缺口与发现（§7 需求清单素材）

1. **latest-alias 请求不命中导入产物（已实证）**。import 侧按钉版存 cache_key（`cond-mat/0408438@v1|…` = 10f47acd…）；`POST /api/arxiv/cond-mat/0408438/translate`（latest 形，`@|` = 24bea433…）→ 202 cache miss 起了新任务 `t_8bcdc8e984deeba4`（进 translating 即 cancel：60 chunks 全 pending、tokens=0；该窗口 gwcap inflight=1 约 10s 与我在飞请求重叠，采样粒度无法完全归因，如实记录）。此不对称非 share 独有（生产任务本身就是 latest 形 key），但 share 导入永远钉版、用户请求大多 latest 形 → 导入产物对最常见请求形态不可见。修法候选：fetch resolve 后二次 dedup，或建行双写两形。
2. **零 token 非结构保证**。`_stage_share_apply` 不调网关（实测 0），但 `_compile_zh` 非 clean 判据 → `_l2_attempt` → `_make_translator` → 真 ChatClient（L2 默认开）。本次 compile clean 故全程 0；若包译文引发可归因编译错，导入会烧 token。决策点：share 任务强制 `l2 off`，或文档明示「修复路径可能耗 token」。（env_judge 默认关、worker fixloop 未接 llm_hook——无其他 LLM 面。）
3. **打包侧现状**：`texlate share pack` CLI 已存在且好用（任务行派生七组分 + cache_key 双形态校验 + glossary 指纹），所谓缺口是「worker 完成钩」——任务终态不自动产包，须手动跑 CLI。小摩擦：(a) 必须有任务行（裸产物目录打不了）；(b) pack 要求三件套全在，无 zh.pdf 的 partial（fixloop_exhausted 型）打不了，而 unpack 侧 REQUIRED_ARTIFACTS 本就允许 zh.pdf 缺席——pack/unpack 不对称；(c) `_share_glossary_hash` 默认并 `~/.texlate/glossary.yaml` 已核实正确（Glossary.load 本就默认加载该层）。
4. **修复经包传播（正面）**：生产臂 partial 根因是编译错，L2 重译修了 chunk 0:1 并回写 → 包内 dual.json 携带修后译文 → B 侧 splice 直接 clean → done。共享缓存天然携带修复成果。
5. **观测性**：worker `self._log` 只进 task_events/SSE；进程 stderr 仅 uvicorn access log——离线排障要读 DB（本现场 db-dump.json 已归档三任务行+事件+files+chunk 状态）。
6. index.jsonl 服务形态仍未实现（既定 §8 后续接线点，非本次新发现）。

## 现场文件

`bench/results/share-live-2026-09-16/`：

- `pkg/18615c27cff0….share.zip` — 真管线产出的分享包
- `server-B.log` — 实例 B uvicorn 进程日志（access log）
- `gwcap-samples.log` — 全程 1s 粒度网关 inflight 采样
- `import-resp.json` / `reimport-resp.json` / `translate-pinned-resp.json` / `translate-latest-resp.json` / `import-tampered-resp.json` / `import-zeromatch-resp.json` — 各端点响应
- `snapshot-import.json` / `snapshot-zeromatch.json` / `reader-import.json` — 终态快照与 reader
- `db-dump.json` — B 库三任务行 + task_events + files + chunk 状态全量
- `evil-tampered-pdf.share.zip` / `3dba843d…share.zip` / `work-evil/` — 负面包构造现场

数据目录留证：`tmp/share-live-b/`（B 实例库与任务树）；生产侧 `tmp/live-smoke2-data/` 未动。进程已全杀，gwcap inflight=0。
