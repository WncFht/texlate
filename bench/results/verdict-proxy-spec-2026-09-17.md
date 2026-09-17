# verdict 代理指标评估 spec —— landmark 覆盖 / expander leak / 术语一致性（texlate-2f → peer1 接线用）

> 目标：翻译质量面指标进 verdict/metrics。现状 verdict（`src/texlate/compile/judge.py` Verdict dataclass）只有 status + n_errors/error_cats/cjk_chars/missing_chars——编译健康面，零翻译质量面。本 spec 定三候选指标的口径、接线点、成本与裁决序。
> 摸底实据（2026-09-17）：`bench/work_e2ereal/_xlat_state/{sid}/state.json` 逐 chunk 存 `source`+`translation`；stagerun `work/{id}/xlat-state/` 同构 → leak 与术语**完全可后算**，零改码先出数。

## 1. 指标定义与口径

### A. landmark 锚点存活率（`landmark_*`）

双口径，按输入可用性分层：

| 子指标 | 定义 | 输入 | 可行性 |
|---|---|---|---|
| `landmark_density` | zh pdf named-dest 分类计数（`align.extract_landmarks` 的 `_category` 分桶：section/figtable/equation/cite）÷ 源结构期望数（\section 系 + float env + numbered eq + bibitem，从 zh/ 树或 parse.json 数）→ 各类存活比 | zh pdf（splice/pipe-xel 必有）+ 源树计数 | **无条件**——无需 en pdf |
| `alignment_pairs` | `align.build_alignment(en_pdf, zh_pdf)` 输出的 pairs 数、en 侧 dest 被配对的覆盖率、mean offset | **en pdf + zh pdf** | **条件可行**——需 base 臂编译产物 |

现状缺口：stagerun-loop1 `build-base/` 未跑（0 pdf）；e2e `--base onfail` 只有非 clean 格有 base pdf（realn200: 48/200）。`alignment_pairs` 要全量覆盖须先补 `compile --arm base` 段（runbook 估 ~1.5h/5k）。`landmark_density` 不受此限。

### B. expander leak 率（`leak_n`/`leak_rate`/`leak_hits`）

口径直接**复用 parsebench**（`bench/py/parsebench.py` `LEAK_PATTERNS` 六族正则：dollar/cite_family/ref_family/begin_env/conditional/input_include，`scan_chunks` 命中任一 → leaked）。corpus_v3 官方口径 0.040% 就是这套。

计算对象 = 送译 chunk 的 `source` 文本——state.json `results[].source` 即逐 chunk 原文，后算零重扫。定义 `leak_rate = n_leaked / n_translatable`，`leak_hits` 保六族计数供归因。

注意与既有 `leftover_ph`（splice 侧占位符残留，已是 fail 硬线）正交：leak 是**送译前**的展开残留（上游 parse/gullet 质量面），leftover_ph 是**译后**残留。

### C. 术语表一致性（`term_applicable`/`term_hit`/`term_hit_rate`/`term_misses`）

定义：chunk `source` 命中术语 en（词边界正则 `glossary._TERM_BOUNDARY`）→ 该 chunk `translation` 是否含对应 zh。`term_hit_rate = hits / applicable`，`term_misses` 列 ≤10 条 `{en, zh, chunk_id}` 供归因。

术语集重建口径：cell primary_cat（manifest `cat_group`）→ `terms/index.yaml` 映射 category csv + `default.csv` + `glossary.doc_filter`（只留文档中出现的词）——与 pipeline 实际注入同层。**缺口**：`StateStore.GLOSSARY_FILE=term_dict.json` 已定义但 pipeline 未传 `term_dict=` 实参（realn200/stagerun 均 0 落盘）——spec 建议**顺手补这一行接线**（pipeline 物化期 save_maps(term_dict=glossary_flat)），今后以落盘术语集为准，重建只作 backfill。

**臂限定**：mock 臂译文是 echo 占位，术语指标无意义——只在 real 臂（或任何真 LLM 臂）计；mock 格字段留 null。

## 2. 接线点（文件:函数级）

| 链 | 挂点 | 改动 |
|---|---|---|
| stagerun xlat | `bench/py/stage_xlat.py` `stats` dict（~L151-168，现产 leftover_ph/warn_kinds）→ `rec["metrics"]["translate"]` | +`leak_*`/`term_*` 键；chunk 文本在 stage 内本就有（state.results 或重扫 zh/） |
| stagerun compile | `bench/py/stage_compile.py` `rec["metrics"]`（L126-178，verdict/inject/engine 同层）→ `rec["metrics"]["landmark"]` | 编译成功后 `extract_landmarks` on splice pdf + 源树期望计数 |
| e2e_real | `bench/py/e2e_real_bench.py` `rec["translate"]`（translate_tree 返回 dict，L272 附近）→ 同 stats 键 | 同 A 方案；landmark 挂 `rec["pipe-xel"]["landmark"]`，`alignment_pairs` 仅 base-xel 存在格 |
| fixloop 复判 | `metrics.post` 已有 post-compile 面 | landmark 可在 fix 后重算（可选，二期） |
| 产品侧单源 | `LEAK_PATTERNS` 现住 bench/py/parsebench.py——建议挪 `src/texlate/latex/`（或 xlat/）导出入口，parsebench 改 import，避免 bench/产品两套口径漂移 | ~20 行移动 |

## 3. 成本

| 指标 | 单格成本 | 5117 格全量 | 常态开？ |
|---|---|---|---|
| leak | state.json 读 + 6 正则扫 ~百 KB 文本 ≈ 10-50ms | <5min | 是（便宜到可忽略） |
| term | glossary rebuild（yaml 装载 cache）+ 逐 chunk 边界正则 ≈ 20-80ms | <10min | 是（real 臂） |
| landmark_density | pypdf 开 zh pdf + dest 枚举 ≈ 0.3-1s | ~1-1.5h 串行 / jobs8 ~10min | 是 |
| alignment_pairs | +base pdf 编译（若未跑 ~30s/格）+ build_alignment ~1-2s | 视 base 覆盖 | 条件——先 backfill base 或只 onfail 格 |

**全部可先纯后算**（读 state.json/现有 pdf，零改码零重跑）出一遍分布校准阈值，再接进 stage metrics——推荐路径，本 spec 不主张跳过校准直接动 verdict。

## 4. 风险与裁决序

1. **先 metrics 后 verdict**：三指标一律先入 metrics 观测字段，不进 status/reasons——阈值校准前不得影响 clean/partial/fail 判定（landmark_density 对无 hyperref 稿（老 plain/无书签 pdf）恒低，leak 对合法 `\eqref` 密集稿有误报面，term 对词形变体宽容度未知——都需要分布数据定门）。
2. **口径不稳定面**：landmark dest 名是 hyperref 派生编号（section.N 非 \label 名）——density 按「类别计数比」不按名配对，天然容忍编号漂移；alignment_pairs 才是名级配对。
3. **与现有裁决的关系**：leak/term/landmark 是质量面**观测**不是红线；`leftover_ph` 仍是唯一 splice 硬线。若将来升级，建议序：`term_hit_rate`（最贴近译文质量）→ `landmark_density`（结构完整性）→ `alignment_pairs`（双 pdf 对齐，最重但最贵）。
4. **mock 臂口径**：term/leak 在 mock 臂含义不同（echo 不犯术语错但 leak 照样有效——leak 是上游质量面两臂同义，term 是翻译质量面 mock 恒 null）。scorecard/triage 聚合时按臂过滤。
5. **state.json 依赖**：后算依赖 `_xlat_state` 未清理（work_e2ereal 是 gitignored scratch——stagerun work/{id}/xlat-state 随结果目存活更稳）。若 state 被清，leak 可退化重扫 zh/ 源 chunks（~1-3s/篇），term 无源不可重建（translation 还在 zh/ 里但 chunk 边界丢了——只能粗算文件级命中率，口径降级须注明）。

## 5. 建议落地序

1. 后算脚本（bench/py/ 或 tmp/）扫 stagerun-loop1 + realn200 全量 → 三指标分布 + 异常簇清单（校准数据）。
2. `LEAK_PATTERNS` 挪产品侧 + `term_dict.json` 接线（两行级改动）。
3. stage_xlat/stage_compile metrics 加键（观测字段）。
4. 分布稳定后评审是否任何指标升 verdict reasons（默认不升）。
