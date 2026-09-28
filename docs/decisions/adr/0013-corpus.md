# ADR-0013 语料分层治理：钉版四层组 + 加层不删层 + 评测/dev 分轨

> **状态**：现行
> **日期**：2026-09-15（corpus v1/v2 成库）| 更新 2026-09-19（八层分轨收官）、2026-09-20（七库合一）

## 上下文

「所有 arXiv 论文干净翻译」的目标要求评测语料既有年代/领域长尾覆盖，又贴真实用户负载分布（近期高引 CS 论文压倒性多），还要能定向挖机制陷阱。单一抽样口径无法同时满足：均匀层覆盖长尾但与负载不匹配，热度层贴负载但漏旧时代陷阱。语料还要服务两种矛盾用途——池化估计要求无偏，dev 训练/调试要求往「爱挂的底材」倾斜。

## 裁决

- **钉版为纲**：每篇语料以 `(channel, item, member, blob_sha256)` 四元组钉版——IA `arxiv-bulk` 月 chunk / TIGER `arxiv-latex-5T` / e-print `acquire_source` 三渠道统一记账，manifest.jsonl 入库、数据 gitignored。
- **加层不删层**：新需求一律开新层不重构旧层——v1 手挑陷阱 39（裸布局）、v2 分层随机（139 在场）、v3 核心 1000（30 月簇 × 33–34，old/new = IA/TIGER 双源）、booster 200（B01–B07 机制配额策展 + nominations 审计轨迹）、expand 3866、hot 166（OpenAlex arXiv 源 cited_by_count 降序 hot-cite 124 + 随机 hot-recent 42，e-print 渠道含 OpenAlex 字段）。
- **评测/dev 分轨**：holdout 3020 篇（`EVAL_ONLY` 治理——`dev_layers()` 枚举自动排除、`exclude_cluster_months` 剔核心簇月保月间零泄漏、评测侧须显式 `--layers holdout`）；dev_vol 2000（fbias 配额往历史高失败率 cell 倾斜）、dev_failmine 1500（FLAG_RX 机制旗标定向挖 deadpkg/docstyle209/epsfig 等旧时代陷阱）、dev_recent 1514（scholarweave 脱水 1065 有损只进 dev + eprint 449）。八层时点合计 13,266 篇。
- **机制台账**：`mechanisms.jsonl`（B 配额 + T 系 fixture + W 系野例，时点 255 条续增）是层间共享资产——found-in-wild → covered → fixture 生长链。
- **横向扩面否决**：2026-09-18 裁决语料横向扩张（更大均匀层）停做，改纵深——mech_tags 回填、real 滚动探针、机制归因增厚（见 ADR-0019）。

## 理由

- 核心层三十年均匀抽样保证长尾覆盖正确性（astro-ph→cs 全 cat_group），hot 层补需求轴（首日 72 篇 CS 占 51% vs 核心层 18%——负载分布实证差异）。
- pdf_only 是真实负载固有类：hot 层取源 13–28% 候选无 TeX 源，记录 `fetch_fail.jsonl` 不删——分布证据本身有值。
- 证据：主仓 `bench/corpus/MANIFEST.md`（含四层扩层收官记录与 QC）、`docs/09` S0–S5 抽样管线（原编号档已随 2026-09-20 文档库重建撤编，后继 `docs/spec/corpus.md`）；调研档案 `research/corpus/v3-plan.md`、`research/corpus/frame-and-allocation.md`。

## 演变

- 2026-09-15：v1 39 → v2 139 → v3 core 1000 + booster 200。
- 2026-09-16→17：expand 3866 + hot 166 增补，合计 5232（勘误链：原记 5133，后核 5232，再核八层 13,266）。
- 2026-09-19：评测/dev 分轨扩层 +8,034（holdout/dev_vol/dev_failmine/dev_recent），八层 13,266 篇 · 46GB；并发事故留痕（supp 清单互没去重 + cell-adoption 不分层 → 5 id 跨层双落，已清账修管线）。
- 2026-09-20：**七库合一**——`bench/corpus/` 成唯一物理根（~14k 篇 · 54.9G），corpus_v2/corpus_m1k/corpus_iclr 树 rename 并入（947 搬移 + 251 去重 + 3 冲突版本双保留进 `_alt-versions/`），兼容壳 symlink 拆除；`corpus_daily`（滚动 soak）与 `corpus_iclr_pdf`（PDF 产物库）生命周期不同不并入。物理拆分至 `corpus_v3/`/`corpus_m1k/`/`corpus_v2/` 独立根的再分层在途（以 `dev/repository.md` 与 MANIFEST 实数为准）。
- 2026-09-21：`corpus_daily` 滚动层整体下线删除（`daily_arxiv` 管线同撤）。
- 2026-09-23（Wave-F/trizone-ledger v2）：「再分层在途」由 trizone 口径实质取代——不走分库目录，改清单/数据分离：`bench/corpus/` 只留 tracked manifest 与台账，物化载荷迁仓外 `$TEXLATE_BENCH_ROOT/lake/corpus/`；构建管线重写为 `bench/py/specs/corpus_*.py` spec；`benchlib.EVAL_ONLY_LAYERS` 治理件随 benchlib 删除，EVAL_ONLY 口径移 `kernel/spec.py::EVAL_LAYERS`（`{"holdout","eval_only"}`，spec 须声明 `eval=True` 才进帧）。

## 现状

清单根 `bench/corpus/`：层 manifest（v1/v2/core/booster/expand/hot/holdout/dev_vol/dev_failmine/dev_recent/m1k-*/iclr）+ `mechanisms.jsonl` + `nominations/` + `eval_coverage.json`（B04/B06 覆盖簿记）——trizone 后只存 tracked 清单与台账，物化载荷在仓外 `$TEXLATE_BENCH_ROOT/lake/corpus/`；构建管线 `bench/py/specs/`（`frame_build` + `corpus_{v3,layers,expand,hot,sw,hydrate}`，`bench run <spec>` 入口；v2/m1k 系一次性构建无 spec 继任）；治理件 `kernel/spec.py::EVAL_LAYERS`（holdout/eval_only 层仅 `eval=True` spec 进帧）。滚动层 `bench/corpus_daily/` 已退役（2026-09-21）。
