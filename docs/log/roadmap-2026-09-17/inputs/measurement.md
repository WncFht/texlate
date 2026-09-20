# 测量面/scorecard 质量轴侦察（roadmap-2026-09-17）

> **结论**：测量侦察：verdict 五面字段语义盘清；taxonomy 物化零消费、scorecard union 名实不符、csb 校验挡不住同态陈旧。
> **状态**：时点证据（2026-09-17 口径）
> **日期**：2026-09-17（2026-09-20 迁入重编）

> 只读侦察，2026-09-17。范围：verdict 体系五面字段语义与消费方、组成感知 sig 后残存判分盲区、scorecard 口径（union pdf 端态 vs pipe-xel 记录态）、跨波 drift 检测、records schema 缺口。断言带 `file:line`；行号为当日工作区快照。

## 1. verdict 体系盘点：records 五面字段语义与消费方

records 行骨架由 `stagerun_lib.base_rec` 固定（`bench/py/stagerun_lib.py:130-142`）：`{id, stage, arm, upstream, code, status, dur_s, metrics, errors, sig}`——无 `schema_v`，自由面全压在 `metrics` 子树。

### 1.1 五面字段逐面语义

| 字段                         | 生产处                                                                                                                                                                                                                   | 语义                                                                                                                                                   | 消费方                                                                                                                                                                                                                                                                       |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`                     | `judge()` → `stage_compile.py:180` / fixloop post 复判 → `stage_fixloop.py:182`                                                                                                                                          | `clean`/`partial`/`fail` 三态 + 记录级 `reject`/`skip`/`error`/`fault`/`dirty_pdf`（legacy）                                                           | `gate_scorecard.pick_final`（:60-80）、`rundiff` rank 迁移（rundiff.py:33-35）、`RecLog.is_done`（stagerun_lib.py:98-105，`DONE_STATUS` 单源 benchlib.py:174）、`triage` 聚类门、triage `fixloop_degraded` 回归探测（triage.py:581-597）、dossier、status_panel `n200_stats` |
| `sig`                        | 三个生产点同一键：`verdict_sig`（compile，benchlib.py:351-420，首错/众数 cat:pay）、`fixloop_sig`（stage_fixloop.py:199，fv+final_cat+ 末轮 pay）、`errors_sig`（其余 stage，benchlib.py:182-191，errors[0] 的 cat:pay） | 归一化聚类签名；**同键三种出处语义**——compile sig 是 verdict 主导错误，fixloop sig 是修复循环终局词，其它 stage sig 是 errors[0] 直取                  | `triage.record_sig`/`bucket_sig`（triage.py:142-194）、tickets 聚类键（triage.py:303）、`gate_scorecard` top non-clean（:98-99,132）、rundiff sig_a/sig_b 注解、dossier `_signature`                                                                                         |
| `taxonomy`（wave-5a 新物化） | `benchlib.judge_dict` → `metrics.taxonomy`（compile，benchlib.py:320,332-344）/ `metrics.post.taxonomy`（fixloop post）                                                                                                  | fixloop 内部分类器对 first_error 的二级分类 `{cat,pay}`；advisory——分类故障落 `{cat:None,pay:None}` 不毁卷宗                                           | **零 records 侧消费者**——dossier 仍自算（`_classify_log` 读 `splice/*.log` 末件 dossier.py:215-227,284；`_classify_text` 退 first_error 行 :230-240,389,476-487），triage tickets 聚类仍走 sig 不读 taxonomy。M1 物化已落，M2「待人工面塌半」尚未接线                        |
| `error_cats`/`error_pay`     | `judge._error_composition`（judge.py:157-181）逐错误行分类构成 + cat→首见 payload                                                                                                                                        | bulk 构成纠偏原料：众数 cat 严格大于首错 cat 时 sig 改挂众数（benchlib.py:402-419）；构成外 cat（killed_by_signal/no_pdf 等 verdict 级词）不参与比众数 | 仅 `verdict_sig` 内部消费 + dossier verdict 透传                                                                                                                                                                                                                             |
| `missing_chars`              | `judge._missing_char_check`（judge.py:116-123，nullfont 排除经 redlines 单源 :98-105）                                                                                                                                   | 缺字形计数；`expect_cjk` 时才进 reasons 门控                                                                                                           | `misschar_partial` 谓词（benchlib.py:494-501）双消费点：`stage_fixloop --on misschar`（:204-211）与 `e2e_real_bench._want_fix`；**有意不进 sig**（2026-09-17 裁决：warning 派生信号不混 error sig，benchlib.py:366-368）                                                     |

辅助面：`cjk_chars`（pdftotext 渲染验证，只进 reasons 不进 sig）、`warnings_hit`（→`warn:*` reasons → derived sig）vs `warnings_sys`（→notes 观察项，不进 status，engine.py:129-132,185-240 分裂）、`n_errors`（`!` 行计数）、`first_error` 原文（埋 `metrics.compile.first_error`，errors[] 只载 `{code,cat,payload}` 三键）。

### 1.2 词汇面不对称（既有行为，非 bug 但测绘成本）

status 词表四套并存：`OK_STATUS`/`SKIP_STATUS`/`RESCUED_STATUS`/`DONE_STATUS`/`COMPILED_STATUS`/`STATUS_RANK`/`TERMINAL_WORDS` 全在 benchlib.py:143-178 单源，但各自口径有意不齐（benchlib.py:141-142 自注「单源≠拉齐」）。fixloop 内部 verdict 词表（`clean/acceptable_pdf/dirty_pdf/best_effort_pdf/unfixable:<cat>/stuck/max_rounds/reject:<rid>/no_errors_no_pdf/no_main_tex[:<sub>]`，engine.py:1237-1239）与 post-judge `status` 词表分居 `metrics.fixloop_verdict` 与 `status` 两键——tickets 聚类 sig 会拿到 `unfixable:*` 前缀词而 status 已是 post 三态，两刻度同格并存靠读者脑内换表。

## 2. 组成感知 sig 之后残存的判分盲区

众数纠偏（benchlib.py:402-419）落地后，sig 已能反映 bulk 构成；残存盲区：

### 2.1 same-status sig 迁移对 rundiff 不可见

`rundiff.diff_stage`（rundiff.py:76-91）按 status rank 分 same/improved/degraded 三桶——**同 status 异 sig 的迁移（fail:syntax→fail:missing_file）落进 `same`**，且 same 桶只进计数、md 渲染不列清单（:157-186 只渲 degraded/improved/added/removed）；sig_a/sig_b 字段虽进 JSON（:82-85）但无展示面。修复型波次最常见的「status 未动、根因换了」正是这个盲区。

### 2.2 misschar 维度在 sig 面缺席（裁决使然，但聚合面欠账）

missing_char 不并入 error sig 是 2026-09-17 明文裁决（防 phantom-payload），检索口在 `verdict.missing_chars`——但 **tickets 聚类键是 sig**（triage.py:303），没有任何聚合面按 missing_chars>0 出「含缺字的格」清单；misschar 与 error 并存的格在 sig 视图只显示 error cat。`--on misschar` 谓词链是选格器不是报告器——当前没有「缺字格总数/分布」的现成统计。

### 2.3 partial 掩蔽：多判据坍缩成单 sig

partial 格 reasons 可多判据并立（`errors>3` + `warn:invalid_utf8` + `missing_character×N` + `cjk_chars<20`），sig 只取一错（首错或众数）。reasons 本身在 `metrics.verdict.reasons` 但**是字符串列表非结构化**——`errors>3 (110)` 这类内嵌计数串消费方正则拆（e2e_real_bench.py:734 `split("(")[0].split(":")[0][:60]`），`warn:` 前缀词、`cjk_unverified+missing_chars` 连字符复合词全靠字面前缀约。判据结构化（kind+count 字段）不存在。

### 2.4 unfixable 与「真不可救」区分度在 sig 层不可得

`unfixable:<cat>:<pay>` sig 桶内混两种本质不同的格：**规则没触发**（n_actions=0，ruleset 覆盖缺口）与**触发但修不动**（n_actions>0，规则力不足）。区分原料 `metrics.n_actions` 在 records 里已有（stage_fixloop.py:190），但 `triage.classify` 对 `unfixable:missing_file` 一律归 `rule`/`shim_table`（triage.py:244-250）不读 n_actions——wontfix 裁定面（M6）仍需人工进 cases.jsonl 逐格看 rounds。

### 2.5 catch-all 桶与小盲区

- `verdict:{status}` 兜底 sig（benchlib.py:393）收所有 cat 不可判定的格——`verdict:fail` 是混装桶；timeout/killed 已由 derived 分支解出 `timeout`/`killed_by_signal:N`（:381-391），残余真杂碎才落此桶，体量未知、内容不可见。
- `error_pay` 每 cat 只存首见 payload（judge.py:178-179）——同 cat 多 payload（如一篇缺 3 个 .sty）聚合后只剩首名，payload 级覆盖分析仍要回 log。
- clean+warning 静默伤：warnings 走 `notes`/`warnings_sys` 不产 sig、不产 errors → tickets 跳过（triage.py:299 的 has_sig/has_err 门）——M3 面依旧只有 metrics 深字段可挖，无聚合出口。
- 同分平票归首错（benchlib.py:416 严格大于才换众数）是有意裁决（因果上游优先），但 50/50 构成在 sig 层无痕迹。

## 3. scorecard 口径审计：union pdf 端态 vs pipe-xel 记录态

### 3.1「union」名实不符 + 两工具口径分歧

`gate_scorecard` 文档写 `union_pdf = compile 或 fixloop 产出了 PDF`（gate_scorecard.py:9-10），实现是 `pick_final` **末段胜**：csb 新鲜就无条件取 fixloop 记录态（:80 `return "fixloop", f, None`），**不做优劣比较**。e2e_real_bench 的「union 口径取较好者」注释（e2e_real_bench.py:711-712）是 best-of 语义，且只用于回退检测展示（:713-724），summary.md 根本不算 union 指标——只报 pipe-xel/pipe-fix/base-xel 三条分立 tally（:680-692）。

后果：**fixloop 回退格在两套口径下读数不同**。compile=partial 的格 fixloop 修后 post-judge=fail（floor_restored 只恢复 fixloop 工作区 pdf 文件，post 复判是对修后源码树重编 engine.py:1470-1484——修坏的树可编不出 pdf）：gate 口径记 fail（末段真态），best-of 口径记 partial（曾出过 pdf）。triage 的 `fixloop_degraded` 回归探测（triage.py:581-597）恰好专抓这一族——但 gate_scorecard 不落这个数，同一份 records 在「记分卡」与「回归面」读出两个故事。metrics.floor_restored 在 fixloop 记录里（stage_fixloop.py:192）但 scorecard 不查它——底板兜回的格 post 仍 fail 时无特殊标记。

### 3.2 csb 新鲜度校验是 status 字符串等值

`pick_final` 判陈旧只看 `compile_status_before == compile.status`（gate_scorecard.py:72-76）。compile 重跑后 status 相同但 log/树已换（syntax→syntax 不同 payload）时，旧 fixloop 记录仍判「新鲜」被收编——status 级指纹挡不住同态陈旧。对照物是 compile 记录身份（如 metrics.compile.first_error/seconds 摘要或记录行号），目前没有比它更强的校验。

### 3.3 其余边界坑（已文档化的小坑之外）

- fix 侧 `last_records` 不传 arm（gate_scorecard.py:86）——fixloop 记录恒 `arm="fix"`（stage_fixloop.py:49），现状安全；若未来 fixloop 开多臂需要补 arm 过滤。
- upstream 缺省回填 "mock"（:46）为史前排兼容，已注释自承。
- compile 记录缺席的孤儿 fixloop 记录静默不计（`fix.get(pid)` 只对 comp 键查）——孤儿量无统计面。
- append 账 `latest_by` 末条胜：曾被救回的格若后续波次写来非 clean 新记录，「曾救回」史实只在 cases.jsonl 留痕，scorecard 不可见。
- **scorecard 无 `--json`**：status_panel 靠正则解析 stdout（status_panel.py:196-211 `re.search(r"gate union-pdf >=(90)%")`），人读文本格式变动即断链——rundiff 有 --json 而 scorecard 没有，机读面不齐。

### 3.4 records schema 演进无版本标记

同日新增字段（taxonomy、l2_attr、error_cats/error_pay）后，同一 `records/*.jsonl` 文件混存新旧形状行（实测 stagerun-loop1 的 fixloop.jsonl 尾行已带 `post.taxonomy`/`post.l2_attr` 而 compile.jsonl 旧行没有）。records 无 `schema_v` 键，唯一版本代理是 `code` 字段 = `git rev-parse HEAD` + `src/texlate` dirty 标（benchlib.py:462-480）——**但 stamp 只盯 `src/texlate`，bench/py 自身改动（judge_dict/verdict_sig/triage 逻辑变更）不产生新 stamp**，`--recode` 谓词（stagerun_lib.py:98-105）对 bench 侧演进是盲的。bench 逻辑变了、records 印章没变——schema 漂移零防护。

## 4. 跨波 drift 检测缺什么

已有：`triage metrics` 子命令把每 run 的 stage_rates/fixloop rescue_rate/regressions 追加进 git 跟踪的 `bench/results/metrics.jsonl`（triage.py:489-514,752-779），rate_drop 与上一行逐 stage×arm 比对（:600-615）；`rundiff` 做任意两目录 status 迁移矩阵。缺口：

- **同 status 下的 sig/taxonomy/n_errors/dur_s churn 全盲区**（§2.1）——修规则波最典型的「状态没动、错误构成变了/错误数腰斩」无可视面；n_errors 量级改善（110→5）在 rank 面 invisible。
- **taxonomy 级 diff 无工具**：metrics.taxonomy 物化后跨波对比仍靠手挖——rundiff 不读 metrics 子树。
- **机制覆盖视图缺**：`mechanisms:` 字段已落 rules.yaml（a9bcd5b），`mech_ids.py --rule` 有 rule→id 正向映射，但**反向（一波 run → 哪些 corpus_v3 机制 id 的格被移动）无 join 工具**——机制级 burn-down 表是 Phase B 排期最想要的那张图，现在只能靠 records.id ∩ mechanisms.jsonl 手算。
- **rate_drop 只对「上一行」**：metrics.jsonl 顺序链比的是相邻 run，对任意基线（如 M1 验收 run）的长程 drift 无入口；rundiff 能对任意两目录但只到 status 粒度。
- **混合 code-stamp 目录无告警**：rerun 波在同一 records 文件里混写多版本代码的记录，rundiff/scorecard 不核 `code` 一致性——跨版本格同池比较静默发生。
- **dur_s/性能 drift 无面**：wall_s 落 metrics.jsonl 但无对比展示。

## 5. records schema 还差哪些字段（免手挖清单）

按「补上即消一类手挖」排序：

| 缺口                                                 | 现状代价                                                                                                                                                                        | 落点                                                        |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `metrics.rules_fired`（fixloop 触发的 rule id 列表） | 修了什么只能 join cases.jsonl 的 actions[]——records 只有 `n_actions` 计数（stage_fixloop.py:190）；机制级统计/规则命中率全要跨文件                                              | stage_fixloop `rec["metrics"]` 一行                         |
| `metrics.post.regressed`/`status_delta` 物化         | 「csb vs post status」比较在三个消费方各写一遍：gate_scorecard.pick_final、dossier csb 链（dossier.py:412-422）、triage fixloop_degraded——三处实现同概念，口径漂移温床          | stage_fixloop 写侧一次                                      |
| `first_error` 上提                                   | 原文行埋 `metrics.compile.first_error`（compile）/`metrics.post.compile.first_error`（fixloop），errors[] 只有 {code,cat,payload}——dossier 专门上提它（audit §2 evidence 需求） | errors[] 补 `first_error` 键或顶层 `first_error`            |
| `missing_chars` 字形身份                             | 只有计数；字体检索面（哪些 U+ 码位缺→font_fallback 覆盖矩阵）要回 log 全文挖                                                                                                    | verdict.missing_chars 旁加 `missing_glyphs`（截断列表即可） |
| `schema_v`/`writer` 标记                             | 新旧形状混行无嗅探依据；`code` stamp 不覆盖 bench/py 演进（§3.4）                                                                                                               | base_rec 加一键 + stamp 纳入 benchlib 版本                  |
| `engine_version`/texmf 快照                          | metrics.engine 只有引擎名；跨环境复现（texlive 版本/texmf 内容）无从对账                                                                                                        | metrics.engine_ver                                          |
| `wave`/`run_id`                                      | 波次归属靠目录名隐式承载，records 合并/迁移后丢                                                                                                                                 | base_rec 可选键                                             |

结构性备注：e2e records 与 stagerun records 是**两个 schema 家族**（嵌套 per-condition dict vs 扁平 per-stage 行），triage `LEGACY_ARM_MAP`（triage.py:346-450）把 e2e 三格翻成 pseudo-records 续命；pipe-fix 无对应 stage 映射项，e2e 侧 fixloop 维度在 triage 面表达力更弱。

## 6. 改进项（按排期价值排序 + 修价估计）

1. **scorecard 口径修齐 + `--json`**——定死 union 语义（建议末段胜保留为「end-state」正名，另加 best-of `union_pdf` 并列输出或至少在 docstring 改正名实）；csb 校验升级为 compile 记录身份指纹；`floor_restored`/`fixloop_degraded` 数进 scorecard 输出（与 triage 回归面对齐）；补 `--json` 供 status_panel 机读替正则。修价 **M**（gate_scorecard 单文件 + status_panel 解析点）。防「同名异义读数打架」这一类最贵误导。
2. **rundiff `--deep`：same-status churn 视图**——同 rank 格按 sig/taxonomy/n_errors/dur_s 四维列迁移清单；`same` 桶出清单不只看计数。修价 **S**（rundiff 单文件，字段已在 records）。直接补 Phase B「改了哪条规则→哪批格实质动了」的读数面。
3. **fixloop rec 落 `rules_fired` + `post.regressed`**——写侧两字段，消 cases.jsonl join 与三处 csb 自算；同时给 triage.classify 接上 `n_actions==0 → ruleset_gap` 分流让 unfixable 桶自动拆 wontfix 候选。修价 **S**（stage_fixloop + triage classify 各几行）。
4. **dossier 消费 `metrics.taxonomy` 替代自算**——`_classify_log`/`_classify_text` 改为优先读 `metrics.taxonomy`/`post.taxonomy`，自算降为字段缺席 fallback；消双口径风险（dossier 读的 `splice/*.log` 末件与被 judge 的 log 未必同一份）。修价 **S**。
5. **records `schema_v` + bench/py 演进进 code stamp**——`base_rec` 加 `schema_v`；`_code_stamp` 的 dirty 检查从 `src/texlate` 扩到 `bench/py`（或另加 `bench_rev` 键），让 `--recode` 能抓 bench 侧逻辑变更后的陈账。修价 **S-M**（写侧一键 + stamp 函数；消费方按需嗅探）。建议与第 3 项同波落——schema bump 一次多带几个字段。
