# 术语表与冻结名登记

本仓词汇契约：**改名前先查 §1 冻结表与 §3 撞名表**；新增术语/新冻结键登记进对应节。写作与引用纪律见 `../dev/conventions.md`。

## 1. 冻结名（wire/数据键——改名 = 烧缓存/断链）

下列 token 已落盘：改名将使既有账本、缓存、产物失读。**永不改名**；需要新语义时另起新名 + 读侧兼容层。

| 名                                 | 位置                                                        | 义                                                                                                                  | 落盘点                               |
| ---------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| `arm`                              | events 必填字段                                             | 实验臂（mock/zh/perturb/… 评测臂次）                                                                                | `events.jsonl` cell/claim/asset 行   |
| `id` / `idc`                       | events 必填双字段                                           | 原始拼写 / canon 归一形                                                                                             | cell/asset/claim/tombstone 行        |
| `zone`                             | asset/tombstone 可选字段                                    | vault 分区词（`pending`/`verified`/…）                                                                              | asset/tombstone 行                   |
| `cat`                              | cell 可选字段                                               | 终态细分（`CATS` 枚举：claimed/regen_gate/upstream-lost/…）                                                         | cell 行                              |
| `status` 词表                      | `cell.status`                                               | 终态 `ok/partial/clean/fail/reject/fault/dirty_pdf` + 可重试 `skip/error` + 内核态 `dedup/claimed/lost/unpaid_gate` | `kernel/events.py` `STATUS_*`        |
| asset `kind`                       | asset.kind                                                  | `zh`/`splice`/`state`/`layoutqc`/`pdf`/`report`                                                                     | `ASSET_KINDS`                        |
| asset `state`                      | asset.state                                                 | `pending`/`verified`/`tombstone`/`adopted`/`staged`                                                                 | `ASSET_STATES`                       |
| lake `state`                       | lake_cell.state                                             | `skeleton`/`hydrating`/`hydrated`/`pinned`/`raw_only`/`failed`/`evicted`/`empty`                                    | `LAKE_STATES`                        |
| `qc_tier`                          | metrics 键 + `qc.json`                                      | QC 严重度分级 `clean`/`warn`/`hard`（`_layoutqc._tier_of`）                                                         | e2e_real cell metrics、runs 产物     |
| `sentry:`                          | cell payload 前缀                                           | 活哨截杀归因 token（`sentry:<reason>` 挂 pay= 槽）                                                                  | fixloop engine 轮内归因              |
| fixloop `detail` 文案              | builtin 返回注记文本                                        | 注记全文落盘即冻结——`tier2`/`loosen dose upgraded` 等旧措辞勿随改名清扫「纠正」                                     | cell `actions[].detail`、engine 事件 |
| `spec_hash` / `fp` / `fp_input`    | 指纹键                                                      | spec/cell 指纹材料——变动即旧缓存全废                                                                                | run_registered/cell_queued 行        |
| `run_seq` / `seq`                  | 序数双名                                                    | run 序 / 格序                                                                                                       | 各事件行                             |
| `safe_id`                          | note 可选字段                                               | 文件系统安全 id 形                                                                                                  | note 行、lake 路径拼写               |
| `canon_drift_of` / `import_src`    | events 公共键                                               | 归一漂移/导入源标注                                                                                                 | `COMMON_KEYS`                        |
| `PIPELINE_VERSION` / `cache_scope` | dedup 键材                                                  | 缓存命中口径                                                                                                        | `share.py` 单源                      |
| run 名形态                         | `<date>/<slug>`                                             | run id 目录拼写                                                                                                     | `$TEXLATE_BENCH_ROOT/runs/`          |
| 数据目录名                         | `corpus`/`corpus_iclr_pdf`/`frame`/`corpus_daily`（已退役） | 语料/产物落盘区                                                                                                     | `bench/`、`$TEXLATE_BENCH_ROOT/`     |
| `redirect_model`                   | endpoints.json `profiles[].models[]` 条目键                 | 线上请求名（空串 = 本名直发）——别名重定向真语义，旧 str 条目读径归一为空串                                          | `server/endpoints.py` store/probe    |

## 2. 域词一词一义

| 词           | 义项                                                                                                                       | 备注                                                                        |
| ------------ | -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 格           | bench cell——一篇×一档位的评测单元                                                                                          | ledger `cell` 事件的口语形                                                  |
| 波           | run 批次实例（如 `soak-2026-09-27` 一批）                                                                                  | 新名一律日期戳，不编号                                                      |
| 支           | fixloop 判定分支（taxonomy 分类树的一支）                                                                                  | 勿与 ledger `arm` 字段混；bench 评测臂义的旧 `arm` 注释归一为「臂」非「支」 |
| 臂           | bench 评测臂（`zh 臂`/`real 臂`/`mock 臂`——ledger `arm` 字段的中文注称）                                                   | 注释统一用「臂」；wire/标识符仍写 `arm`（§1 冻结）                          |
| 缝           | monkeypatch seam——测试可替换件的模块级收口面                                                                               | 三缝辨见 §3                                                                 |
| lane         | 并行工作面（多会话/多 runner 互不叠加通道）                                                                                | 散文可用，不作变量名                                                        |
| canon 双形   | `cat/id` 原始拼写 ↔ `cat--id` 归一拼写                                                                                     | 匹配走 `idnorm.idc_from_safe` 双侧归一                                      |
| 三区         | runs（执行档案）/vault（付费字节）/lake（免费载荷）                                                                        | trizone-ledger 骨架                                                         |
| 账三层       | events.jsonl（append-only 事实源）→ index.sqlite（可弃投影）→ report（读面）                                               | index 可重建                                                                |
| hydrate      | lake cell `skeleton→hydrated` 物化                                                                                         | 对应 evict 反向                                                             |
| claim        | paid 闸认领行（`acquire`/`release`/`reap` 三 op）                                                                          | `CLAIM_OPS`                                                                 |
| 本地名/线名  | 端点档案模型条目双名：`model` = 档案本地名（展示/探针报告键），线名 `wire_model` = `redirect_model \|\| model`（上游实收） | 探测发线名、报告键恒本地名；激活写回 `settings.model` 的是线名              |
| case         | 逐样本评审行（cell 终态批内 buffer，崩格不留孤儿）                                                                         | `T_CASE`                                                                    |
| blob offload | metrics/errors >4KB 外置 `derived/blobs/<sha>.json`                                                                        | `{"$blob":…,"$bytes":…}` 标记形                                             |
| 活哨         | sentry——编译期 watchdog 截杀（page_flood/killsem/超时）                                                                    | 归因回吐 `sentry:` payload                                                  |
| 入场/derive  | 历史账普查进 ledger / 投影重建                                                                                             | importer/report 边界件                                                      |

## 3. 同名异义登记表

新增同名件义务：(a) 两侧 docstring 互辨；(b) 登记本表。

| 名              | 件                                                                                                                         | 义                                                                    |
| --------------- | -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `patchseams.py` | `compile/`                                                                                                                 | compile 层 monkeypatch 面（`_SOURCES` map 全惰性 `__getattr__` 回指） |
| `seams.py`      | `server/worker/`                                                                                                           | worker 层 monkeypatch 面（eager bind + 两名惰性回指）                 |
| `_docseams.py`  | `compile/`                                                                                                                 | docclass 注入缝几何原语——**非** monkeypatch 面，名近义异              |
| `decls.py`      | `latex/gullet/` vs `textutil/`                                                                                             | 同名双件域不同（gullet 声明表 vs 文本声明表）                         |
| `endpoints.py`  | `server/` vs `server/routers/` vs `cli/`                                                                                   | 三方同名：档案数据层（store+探针+凭据阶梯）vs HTTP 薄壳 vs 命令行面   |
| `kernel`        | `bench/py/kernel/` vs `tests/bench_kernel/`                                                                                | bench 账本内核 vs 其测试套件（原 `tests/kernel` 改名消歧）            |
| `arm`           | ledger 字段（冻结，§1） / 注释面「臂」（bench 评测臂）与「支/分支」（taxonomy 判定分支） / web `armed*`（二次确认 arming） | 三义分层：wire 字段 / 中文注释两词分义 / UI 确认态                    |
| `tier`          | `qc_tier`（冻结 metrics 键） / `_MATHRUN_STRONG`（layoutfix 剂量档，原 `tier2`） / `validate` rules/cst/logattr 校验层     | 三义：QC 分级 / 修复剂量档 / 校验层号                                 |
| `zone`          | ledger asset `zone`（冻结枚举） / `reconstruct.in_env_args`（原 `_env_arg_zone` 判位）                                     | 数据枚举 vs 位置谓词                                                  |
| `clean`         | `cell.status` 终态词（compile verdict） / `qc_tier` 档（零 finding）                                                       | 两个 clean 不同义                                                     |

## 4. 新规锚点

- **新数据键 / epoch / run slug / 产物目录：日期戳形态**（`@YYYY-MM-DD`、`-YYYY-MM-DD` 后缀、`<date>/<slug>`）。禁编号代号作新标识符（`vN`、`W1`–`W5`、`第N波`、`格N`、`lane N`）。
- 版本语义用功能 slug 承载（`patchseams`/`in_env_args`/`armedId` 式自说明名），代数后缀只允许在数字即协议号处（HTTP/2、LaTeX2e 这类外部定名）。
- 改名流程：grep 全仓（含注释/backtick 引用）→ 查 §1 冻结表 → 查 §3 撞名表 → 落改 + 同步登记表。
