# e2e pipe-fix 救回臂 + corpus_v3 hot 层 —— 落地与冒烟证据（2026-09-16）

> 背景：全仓审计 `docs/research/audit-2026-09-16/` 指出编排断链——fixloop 未接
> e2e/worker；同日立项的语料侧缺口是 corpus_v3 抽样框（IA ≤2020-10 + TIGER
> ≤2412 均匀层）与真实负载分布不匹配。本笔记记录两块扩展的落地与首轮联合冒烟。

## 1. hot 语料层（第三层，扩展不替换）

`bench/py/build_hot_layer.py` 三子命令：candidates（OpenAlex 抽样 +
全 manifest/目录去重）→ fetch（产品 `acquire_source` 钉版取源 →
`corpus_v3/{id}/{meta.json,raw.*,extracted/}` + `manifest_hot.jsonl` 追加，
可重入）→ report。两个子层：`hot-cite`（`from_publication_date≥2024-01-01`
按 `cited_by_count` 降序，目标 120）与 `hot-recent`（2025-06-01+ `sample=`
随机，目标 40）。

首日 85 发（arxiv 日预算护栏 `--limit 85`）：入库 **72 篇**（594 个 .tex、
671MB raw），yymm 分布 {15:2, 16:3, 17:2, 20:1, 23:5, 24:47, 25:11, 26:1}，
CS 37/72≈51%（核心层仅 18%）；13 篇 `pdf_only` 跳过（无 TeX 源——高引
论文里固有的一类，记 `bench/work_v3/hot/fetch_fail.jsonl`）。余 75 候选
次日续跑（同命令，manifest/目录双侧去重已内建）。

## 2. pipe-fix 救回臂（e2e_real_bench）

pipe-xel 非终态时把产物树 copy 到 `work_e2ereal/pipe-fix/{sid}` 跑
`fixloop()`——xelatex usermode + TUNA 钉 + tlpdb 离线索引 + `_NoSandbox`，
配方经 `import fixloop_bench` 单源复用；随后 xelatex(halt_on_error=False,
同 usertree) + `judge(expect_cjk)` 复判，verdict 刻度与 pipe-xel/base-xel
一致可直读。`--fixloop onfail|always|never`（默认 onfail），结果沉淀
`results/{tag}/cases.jsonl`（CaseSink 原生 case）。cached 记录有
pipe-fix 回填路径（pipe-xel 工作区仍在则只补救回臂，不重翻）。

**语义校准（冒烟实证）**：`onfail` 只接 pipe-xel `fail`。partial 已产出
PDF、其判据是 warning 级（invalid_utf8/missing_chars——非编译错误，
fixloop 规则无能为力），而 fixloop 的 halt_on_error 引擎 + 树改写
（vendored sty 隔离、tlmgr 装包改变宏定义环境）会把已有 PDF 弄丢：
冒烟中 partial→fail 回退 2/3。reject 不救（inject 拒绝=无 ctex）。
always 模式保留全跑能力作幂等/回退率探针。

## 3. 联合冒烟（`e2e-hotfix-smoke-2026-09-16`，hot 层 9 篇，swe-2-medium）

翻译 9/9 执行、chunk ok 3037/3039、splice 残留 0（硬门 PASS）。
管线引入回归 0（无 pipe-xel 挂而 base-xel clean 的样本）。

| 论文                          | pipe-xel | pipe-fix    | base-xel |
| ----------------------------- | -------- | ----------- | -------- |
| 1502.03167（BatchNorm）       | partial  | fail        | partial  |
| 1610.05828                    | clean    | ·           | ·        |
| 1710.09412（Adam）            | fail     | **partial** | partial  |
| 2401.17274（eRASS1 DR1）      | partial  | partial     | partial  |
| 2403.17888                    | partial  | fail        | partial  |
| 2405.08810                    | fail     | fail        | fail     |
| 2409.11654                    | clean    | ·           | ·        |
| 2410.08770                    | fail     | **clean**   | fail     |
| 2504.01669（1893-chunk 综述） | fail     | **partial** | fail     |

救回 3 篇：2410.08770 fail→**clean**（base 亦 fail，纯 fixloop 功劳）、
1710.09412 与 2504.01669 fail→partial。回退 2 篇均为 partial 样本
（§2 语义校准的实证来源）。2405.08810 base 即 fail 且未救回
（missing_file 长尾）。union 口径（pipe-xel∨pipe-fix 取优）usable PDF
**5/9 → 8/9**。

## 4. 产物索引

- 语料：`bench/corpus_v3/manifest_hot.jsonl`（72 行）、`MANIFEST.md` 热层一节、
  `.gitignore` 白名单；候选审计 `bench/work_v3/hot/candidates.jsonl`
- 代码：`bench/py/build_hot_layer.py`、`bench/py/e2e_real_bench.py`
  （`pipe_fix_condition`/`_want_fix`/backfill/`--fixloop`）
- 结果：`bench/results/e2e-hotfix-smoke-2026-09-16/{results.json,matrix.md,
summary.md,cases.jsonl,run_meta.json}`
- 规格注记：docs/09 §4 后增补块、docs/10 B5 增补块
