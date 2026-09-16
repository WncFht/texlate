# artifact-map — 清理前产物溯源（2026-09-16 19:00）

磁盘：`/` 917G 用 855G 余 16G（99%）。本表覆盖 `bench/results/`、`bench/work_*/`、`bench/corpus*/`、`tmp/`、`dist/`、`web/dist`、`web/scripts/`。

判定口径：**可删** = 证据已落库且磁盘内容可再生；**在飞勿动** = 有进程在写或被在飞任务引用；**资产** = 重建代价大（语料/真实网关翻译缓存/参考 clone）；**保留** = 证据本体已入库但体积小、删除无收益；**再确认** = 信息不足。

## 在飞实况（19:00 快照，`ps` 实锤）

- PID 429194 `stagerun.py fixloop --on fail --rerun --dir bench/results/stagerun-loop1-2026-09-16`（18:45 起，xelatex 正在写 `stagerun-loop1/work/1206.1954/`；后面还排了 `--on misschar` rerun）
- PID 38740 `e2e_real_bench.py --tag postfix --ids <n100 同表>`（17:55 起，nohup，写 `bench/results/postfix-2026-09-16/` + `bench/work_e2ereal/`）
- `bench/results/repro-1306-2026-09-16/`、`repro-2410b-2026-09-16/`：未入库，文件 mtime 到 18:55——revtex/article 探针证据包正在产出
- `tmp/cjkfont/`、`tmp/latex209-verify/`：18:00 后仍在写（配合未入库新模块 `src/texlate/compile/latex209.py` + `tests/test_latex209.py`）
- `texlate web --port 8765`（PID 2375544）常驻，数据目录不在本表范围内

## bench/results/（119 子目录 + 65 散装文件）

散装文件 65 个全部已入库（macro-stats、parsebench/compilebench json、各库 walkthrough/report、fixloop tickets 等，共 ~2.5M）——保留。

`run_meta.json` 存在的目录其 cmd 摘自该文件；无 run_meta 的按 summary/report 与目录名推断产出者。**除标注外全部已入库**（`git ls-files` 非空），证据 = 目录内 report/summary/jsonl。

| 路径 | 大小 | 产出者/脚本 | 证据落点 | 最后写入 | 判定 |
|---|---|---|---|---|---|
| stagerun-loop1-2026-09-16 | **44G**（work/ 占 44G，records/ 11M，5059 case 目录） | `stagerun.py` 全管线 loop1：ingest+parse+xlat(mock+real50)+compile zh+fixloop，corpus_v3 四层 5072 篇 | report.md / REPORT-fixloop-analysis.md / cases.jsonl / metrics.json / tickets.jsonl / records/*.jsonl（13 文件已入库，work/ 被目录内 .gitignore 排除）；汇总进 audit-2026-09-16 | 09-16 18:53（**正在写**） | **在飞勿动**——fixloop rerun 进行中，且 `rerun-ids-loop2delta.txt` 提示还有 loop2；rerun 全部结束后 work/ 44G 可删 |
| base-v3-full-2026-09-16 | 35M | compilebench_v3.py baseline，sample_n=6000（run_meta：work=work_base_v3full） | REPORT.md + summary.md 已入库 | 09-16 15:59 | 保留 |
| validbench-corpus_v2-2026-09-15 | 13M | validbench.py on corpus_v2 | summary.md | 09-15 14:45 | 保留 |
| babeldoc | 9.1M | babeldoc 对照实验（PDF/PNG：dual/mono/full/parseonly） | **未入库**（`.gitignore` 第 20 行刻意排除）；结论散见 babeldoc-e2e report 与 docs/research | 09-14 17:27 | 再确认——刻意 ignore 的对照产物，删则不可恢复，先问是否还需原件 |
| babeldoc-e2e-2026-09-16 | 8.1M | server babeldoc sidecar 真链路 e2e（upload_pdf 通路 6 bug 修复复验，report 自述） | report.md + artifacts + sse*.log 已入库 | 09-16 16:43 | 保留 |
| parse-v3-full-2026-09-16 | 7.5M | parsebench.py v2(Gullet+Segmenter) 全量 corpus_v3 | REPORT.md + summary.md | 09-16 13:58 | 保留 |
| argspec-verbatim-2026-09-16 | 6.0M | parsebench argspec/verbatim 探针 | summary.md | 09-16 14:26 | 保留 |
| parsebench-v2textfix-2026-09-16 | 4.6M | parsebench.py v2 textfix 轮 | summary.md | 09-16 17:52 | 保留 |
| parsebench-audit-full-2026-09-15 | 4.3M | parsebench.py audit 全量 | summary.md | 09-15 14:51 | 保留 |
| parsebench-v2prod-final-2026-09-15 | 3.9M | parsebench.py v2prod final | summary.md | 09-16 07:26 | 保留 |
| parsebench-v2prod-cutover-2026-09-15 | 3.9M | parsebench.py v2prod cutover 判定 | summary.md | 09-16 06:51 | 保留 |
| parsebench-v2full-s4-2026-09-15 | 3.9M | parsebench.py v2full s4 切片 | summary.md | 09-16 03:57 | 保留 |
| parsebench-v2full-s3c-2026-09-15 | 3.9M | parsebench.py v2full s3c | summary.md | 09-16 02:23 | 保留 |
| parsebench-v2full-s3b-2026-09-15 | 3.9M | parsebench.py v2full s3b | summary.md | 09-16 01:50 | 保留 |
| parsebench-v2full1955-2026-09-16 | 3.9M | parsebench.py v2full 1955 tex 全量 | summary.md + 外挂 report.md | 09-16 00:34 | 保留 |
| stagerun-smoke-2026-09-16 | 3.6M | stagerun.py n=3 全链冒烟（ingest→parse→xlat mock→compile zh，run_meta 全） | report.md + run_meta.json | 09-16 13:29 | 保留 |
| validbench-replay1636-2026-09-15 | 3.2M | validbench.py replay 1636 | summary.md | 09-15 14:14 | 保留 |
| parsebench-v3-post-wfix-2026-09-15 | 3.2M | parsebench.py v3 post-wfix | summary.md | 09-15 18:10 | 保留 |
| parsebench-textutil-verbatim-2026-09-15 | 3.2M | parsebench.py textutil verbatim 轮 | summary.md | 09-15 15:44 | 保留 |
| parsebench-textutil-full2-2026-09-15 | 3.2M | parsebench.py textutil full r2 | summary.md | 09-15 15:52 | 保留 |
| parsebench-textutil-full-2026-09-15 | 3.2M | parsebench.py textutil full | summary.md | 09-15 15:50 | 保留 |
| parsebench-corpus_v3-postf6-2026-09-15 | 3.2M | parsebench.py corpus_v3 postf6 | summary.md | 09-15 18:59 | 保留 |
| parsebench-corpus_v3-postf-2026-09-15 | 3.2M | parsebench.py corpus_v3 postf | summary.md | 09-15 18:35 | 保留 |
| parsebench-corpus_v3-2026-09-15 | 3.2M | parsebench.py corpus_v3 首轮 | summary.md | 09-15 14:43 | 保留 |
| parsebench-audit-final-2026-09-15 | 3.2M | parsebench.py audit final | summary.md | 09-15 14:55 | 保留 |
| parsebench-audit-defnl-2026-09-15 | 3.2M | parsebench.py audit defnl | summary.md | 09-15 15:06 | 保留 |
| share-live-2026-09-16 | 2.4M | share.py live 链路验证（tmp/share-live-b 数据目录） | report.md | 09-16 16:54 | 保留 |
| export-verify-2026-09-16 | 2.1M | export EPUB/DOCX 验证 | report.md + report.json | 09-16 14:27 | 保留 |
| fixloop-cbv4-2026-09-16 | 2.0M | fixloop_bench.py on compilebench-v4 case 集 | summary.md | 09-16 08:50 | 保留 |
| fixloop-zh-cbv3-2026-09-16 | 1.9M | fixloop_bench.py zh 臂 cbv3 | summary.md | 09-16 10:18 | 保留 |
| stagerun-sabsmoke-2026-09-16 | 1.8M | stagerun.py sabotage-b 臂冒烟（3 id，run_meta 全） | run_meta.json + 记录 | 09-16 13:36 | 保留 |
| repro-2203-2026-09-16 | 1.4M | 手动复现证据包（2203.x case） | report.md | 09-16 17:32 | 保留 |
| parsebench-corpus_v3-booster-2026-09-15 | 1.3M | parsebench.py booster 层 | summary.md | 09-15 14:51 | 保留 |
| compilebench-v4-2026-09-16 | 1.3M | compilebench_v3.py v4 变体（work=work_compile_v4） | summary.md + summary-diff-v3.md | 09-16 08:50 | 保留 |
| compilebench-v3-zh-2026-09-16 | 1.3M | compilebench_v3.py zh 条件（work=work_compile_v3） | summary.md | 09-16 10:22 | 保留 |
| compilebench-v3-2026-09-15 | 1.3M | compilebench_v3.py（work=work_compile_v3） | summary.md | 09-15 16:04 | 保留 |
| xlatbench-contract-2026-09-15 | 1.2M | xlatbench.py 契约测试 | summary.md | 09-15 17:02 | 保留 |
| live-smoke-2026-09-16 | 1.2M | server live 冒烟（tmp/live-smoke-data） | report.md | 09-16 14:08 | 保留 |
| modec-expand-2026-09-16 | 1.1M | modec 展开探针证据包 | report.md + summary.md | 09-16 18:31 | 保留 |
| alignbench-post-shim-2026-09-16 | 1012K | alignbench.py post-shim | report.md + summary.md | 09-16 16:07 | 保留 |
| live-smoke2-2026-09-16 | 892K | server live 冒烟 r2（tmp/live-smoke2-data） | report.md | 09-16 16:20 | 保留 |
| mock-sabotage-v3-2026-09-16 | 816K | sabotage mock 臂（tmp/exp/run_sabotage_v3.py；work=work_sabotage_v3/mock） | REPORT.md + summary.md | 09-16 14:38 | 保留 |
| b7-pipefix-2026-09-16 | 816K | B7（2410.17902）pipefix 验证包 | summary.md | 09-16 14:13 | 保留 |
| fixloop-v3-missing-file-r2-2026-09-16 | 732K | fixloop_bench.py missing-file r2 | summary.md | 09-16 01:21 | 保留 |
| fixloop-v3-missing-file-2026-09-16 | 660K | fixloop_bench.py missing-file | summary.md | 09-16 01:10 | 保留 |
| parsebench-audit-fix-2026-09-15 | 652K | parsebench.py audit fix | summary.md | 09-15 14:50 | 保留 |
| modec-v3-tailfix-2026-09-16 | 648K | modec v3 tailfix 探针 | report.md + summary.md | 09-16 16:27 | 保留 |
| parsebench-v2dual200-2026-09-15 | 572K | parsebench.py v2 dual 200 | summary.md | 09-15 20:40 | 保留 |
| doc-e2e-2026-09-16 | 524K | server 文档 e2e（tmp/doc-e2e-data*） | report.md | 09-16 15:52 | 保留 |
| fixloop-v2-rules-2026-09-15 | 520K | fixloop_bench.py v2 rules | summary.md | 09-15 22:40 | 保留 |
| parsebench-v2reg-s3grp2-2026-09-15 | 500K | parsebench.py v2reg s3grp2 | summary.md | 09-16 01:28 | 保留 |
| parsebench-v2reg-s3grp-2026-09-15 | 500K | parsebench.py v2reg s3grp | summary.md | 09-16 01:12 | 保留 |
| fixloop-corpusv2-2026-09-15 | 444K | fixloop_bench.py corpus_v2 | summary.md | 09-15 23:07 | 保留 |
| xlatbench-v3-matrix-2026-09-15 | 432K | xlatbench.py v3 matrix | summary.md | 09-15 18:40 | 保留 |
| modec-v3-2026-09-16 | 432K | modec v3 探针 | report.md + summary.md | 09-16 15:09 | 保留 |
| parsebench-corpus_v2-2026-09-15 | 416K | parsebench.py corpus_v2 | summary.md | 09-15 14:17 | 保留 |
| alignbench-e2ereal-2026-09-16 | 404K | alignbench.py e2ereal | summary.md | 09-16 10:00 | 保留 |
| parsebench-corpusv2-2026-09-15 | 388K | parsebench.py corpusv2（早轮） | summary.md | 09-15 09:44 | 保留 |
| e2e-real-n100-postcutover-2026-09-16 | 376K | e2e_real_bench.py n100 postcutover（run_meta 全；**postfix 正在复跑同表**） | report.md + summary.md + cases.jsonl | 09-16 12:47 | 保留 |
| qual-run-2026-09-16 | 320K | qualbench.py from `_xlat_state` | report.md + run_meta.json | 09-16 14:51 | 保留 |
| **postfix-2026-09-16** | 288K（在涨） | e2e_real_bench.py --tag postfix（PID 38740 实锤在跑） | **未入库** | 09-16 18:37 | **在飞勿动** |
| modec-tec-v3-2026-09-16 | 252K | modec tec v3 探针 | summary.md | 09-16 15:34 | 保留 |
| e2emock-corpus39-2026-09-15 | 220K | e2e_mock_bench.py corpus39 | summary.md | 09-15 12:07 | 保留 |
| repro-1306-2026-09-16 | 208K（在涨） | 手动复现探针（probe-revtex*/article tex+log+pdf） | **未入库** | 09-16 18:55 | **在飞勿动** |
| parsebench-corpus39-2026-09-15 | 208K | parsebench.py corpus39 | summary.md | 09-15 14:43 | 保留 |
| fixloop-replay-baseline-2026-09-16 | 208K | fixloop replay baseline（run_meta：cases 来自 e2e-real-n100-postcutover，work=work_fixloop_replay） | SUMMARY.md + run_meta.json | 09-16 14:38 | 保留 |
| perf-tail-2026-09-16 | 192K | perf tail 探针 | summary.md | 09-16 13:26 | 保留 |
| compilebench-corpusv2-2026-09-15 | 188K | compilebench_v2.py corpus_v2（work=work_compile_v2） | summary.md | 09-15 10:00 | 保留 |
| e2e-real-n100-2026-09-15 | 172K | e2e_real_bench.py n100 首轮（run_meta 全） | summary.md + 外挂 report.md | 09-16 00:38 | 保留 |
| v3-100-2026-09-15 | 164K | e2e_real_bench.py v3-100（run_meta 全） | summary.md | 09-15 21:44 | 保留 |
| fixloop-v3-docstyle-2026-09-16 | 128K | fixloop_bench.py docstyle（work=work_fixloop_v3_ds） | summary.md | 09-16 01:10 | 保留 |
| parsebench-argspec-smoke-2026-09-16 | 124K | parsebench.py argspec 冒烟 | summary.md | 09-16 10:54 | 保留 |
| modec-tail-2026-09-16 | 124K | modec tail 探针 | report.md + summary.md | 09-16 15:50 | 保留 |
| fixloop-rules-2026-09-16 | 104K | fixloop_bench.py rules | summary.md | 09-16 01:11 | 保留 |
| repro-0806-2026-09-16 | 96K | 手动复现（0806.x，textfix 双报告） | report.md + report-77-textfix.md | 09-16 18:05 | 保留 |
| qualbench-2026-09-16 | 96K | qualbench.py | report.md | 09-16 13:50 | 保留 |
| xlatbench-v3-smoke-2026-09-15 | 88K | xlatbench.py v3 冒烟 | summary.md | 09-15 17:44 | 保留 |
| l2-attr-probe-2026-09-16 | 84K | l2_attr_probe.py | summary.json | 09-16 11:28 | 保留 |
| fixloop-v3-docstyle-tec-r2-2026-09-16 | 80K | fixloop_bench.py docstyle tec r2 | summary.md | 09-16 01:31 | 保留 |
| e2e-real-s40-r2-2026-09-15 | 80K | e2e_real_bench.py s40 r2 | summary.md | 09-15 18:48 | 保留 |
| e2e-real-s40-2026-09-15 | 80K | e2e_real_bench.py s40 | summary.md | 09-15 16:36 | 保留 |
| e2e-modes-2026-09-16 | 80K | e2e 模式对照 | summary.md | 09-16 10:33 | 保留 |
| e2e-hotfix-smoke-2026-09-16 | 68K | e2e_real_bench.py hot 层 8 篇 hotfix（run_meta 全） | summary.md | 09-16 10:31 | 保留 |
| alignbench-e2ereal-2026-09-15 | 68K | alignbench.py e2ereal 早轮 | summary.md | 09-15 22:05 | 保留 |
| server-smoke-2026-09-16 | 64K | server 冒烟 | （无 meta 文件） | 09-16 10:56 | 保留 |
| ctex-anchor-2026-09-16 | 52K | ctex 锚点验证 | report.md | 09-16 15:29 | 保留 |
| alignbench-selftest-2026-09-15 | 52K | alignbench.py selftest | summary.md | 09-15 16:21 | 保留 |
| docker-smoke-2026-09-16 | 48K | docker 冒烟 | report.md | 09-16 14:15 | 保留 |
| repro-2501-2026-09-16 | 40K | 手动复现（2501.x） | README.md | 09-16 18:35 | 保留 |
| e2e-postcutover-n10-2026-09-15 | 36K | e2e_real_bench.py n10 postcutover | summary.md | 09-16 07:52 | 保留 |
| **repro-2410b-2026-09-16** | 32K（在涨） | 手动复现探针（2410.x） | **未入库** | 09-16 18:50 | **在飞勿动** |
| gullet-corpus-2026-09-15 | 28K | gullet_bench.py | summary.json + 外挂 .md | 09-15 20:05 | 保留 |
| e2e-verify-residue-2026-09-16 | 28K | e2e_real_bench.py residue 验证（run_meta 全） | summary.md + 外挂 report.md | 09-16 02:02 | 保留 |
| repro-0806-textfix-2026-09-16 | 24K | 手动复现 textfix 变体 | summary.md | 09-16 17:32 | 保留 |
| repro-0806-head-2026-09-16 | 24K | 手动复现 head 变体 | summary.md | 09-16 17:15 | 保留 |
| parsebench-maskfix-probe-2026-09-15 | 24K | parsebench.py maskfix 探针 | summary.md | 09-16 03:22 | 保留 |
| smoke-2026-09-15 | 20K | e2e_real_bench.py 冒烟（run_meta 全） | summary.md | 09-15 15:02 | 保留 |
| parsebench-fixtures-2026-09-15 | 20K | parsebench.py fixtures | summary.md | 09-15 09:41 | 保留 |
| fixloop-v2-salvage-2026-09-16 | 20K | fixloop_bench.py v2 salvage | summary.md | 09-16 01:20 | 保留 |
| e2emock-v2prod-smoke-2026-09-15 | 20K | e2e_mock_bench.py v2prod 冒烟 | summary.md | 09-16 06:42 | 保留 |
| demo-2026-09-16 | 20K | e2e_real_bench.py demo（run_meta：n40 core） | summary.md | 09-16 08:15 | 保留 |
| e2emock-smoke-2026-09-15 | 16K | e2e_mock_bench.py 冒烟 | summary.md | 09-15 13:47 | 保留 |
| b7-attribution-2026-09-16 | 16K | B7 归因包 | summary.md | 09-16 12:23 | 保留 |
| share-wire-2026-09-16 | 12K | share wire 验证 | report.md | 09-16 14:53 | 保留 |
| share-apply-2026-09-16 | 12K | share apply 验证 | report.md | 09-16 16:12 | 保留 |
| modec-misschar-2026-09-16 | 12K | modec misschar 探针 | report.md | 09-16 18:37 | 保留 |
| filemap-fix-2026-09-16 | 12K | filemap fix 验证 | summary.md | 09-16 15:13 | 保留 |
| export-realbook-2026-09-16 | 12K | export_realbook.py（tmp/realbook pg 书源） | README.md + report.json | 09-16 10:36 | 保留 |
| doc-polish-2026-09-16 | 12K | 文档打磨验证 | report.md | 09-16 16:45 | 保留 |
| dist-smoke-2026-09-16 | 12K | dist 产物冒烟（对应 dist/ wheel） | report.md | 09-16 14:33 | 保留 |
| clean-clone-2026-09-16 | 12K | 干净 clone 验证（两轮） | report.md + report-round2.md | 09-16 17:56 | 保留 |
| api-cover-2026-09-16 | 12K | API 覆盖验证 | report.md | 09-16 14:56 | 保留 |
| web-resmoke-2026-09-16 | 8K | web 复冒烟（web/scripts/smoke.mjs） | report.md | 09-16 17:33 | 保留 |
| web-docview-2026-09-16 | 8K | web 文档视图验证 | report.md | 09-16 16:48 | 保留 |
| probe-wire-2026-09-16 | 8K | wire 探针 | report.md | 09-16 14:49 | 保留 |
| corpus-expand-qc-2026-09-16 | 8K | corpus_v3 expand 层 QC（build_corpus_expand.py） | （数据文件，已入库） | 09-16 13:32 | 保留 |
| cli-doctor-2026-09-16 | 8K | cli doctor 验证 | report.md | 09-16 15:28 | 保留 |

## bench/work_*/（全部 gitignore：`bench/work_*/`）

| 路径 | 大小 | 产出者/结构 | 证据落点 | 最后写入 | 判定 |
|---|---|---|---|---|---|
| work_v3 | 28G | build_corpus_v3.py / build_corpus_expand.py / build_hot_layer.py 构建现场：`tars/` 26G（IA arxiv-bulk 月 chunk + TIGER blob 原件）、`staging/` 1.4G、features/members/meta/zipsum/expand/hot ~35M、frame_lookup.tsv.gz 19M、qc_report/sample_report/chunks/download_progress | 已抽出 `bench/corpus_v3/`（四层 5072 manifest + MANIFEST.md 入库）+ qc_report 自证 ok | 09-16 12:52 | **可删 ~27.5G**——抽取完毕（leader 确认 ok=3740 err=0）；删前建议把 `tars/` 清单落一行进 MANIFEST 备查（重下 IA chunk 成本高） |
| work_base_v3full | 17G | compilebench baseline per-paper 编译现场（6000 样本，tectonic+xelatex） | results/base-v3-full-2026-09-16 REPORT.md | 09-16 15:55 | **可删** |
| work_sabotage_v3 | 5.2G | sabotage 臂编译现场：base-xel 1.3G / pipe-xel 1.4G / pipeB-xel 1.4G / pipeC-xel 1.3G | results/mock-sabotage-v3-2026-09-16 + stagerun-sabsmoke | 09-16 13:34 | **可删** |
| work_e2emock | 2.2G | e2e_mock_bench 臂：base-tec/base-xel/pipe-tec/pipe-xel/pipeB/pipeC + corpus_v3 src 缓存 1.5G | results/e2emock-* + e2e-modes | 09-16 14:43 | **可删**（mock 臂可再生） |
| work_e2ereal | 1.6G | e2e_real_bench 臂：pipe-xel 607M / base-xel 487M / pipe-fix 295M / base-rescue 115M / _texmf 59M / **_xlat_state 25M（111 篇真实网关翻译 state.json）** / _src_snapshot* 5M | results/e2e-real-* + postfix（在飞落点） | 09-16 13:54（在写） | **在飞勿动**——postfix run 引用；且 `_xlat_state` 是真实网关翻译缓存 = **资产子集**，跑完也建议单独保留 |
| work_fixloop_zh | 1.5G | fixloop zh 臂 per-paper 现场 | results/fixloop-zh-cbv3-2026-09-16 | 09-16 09:52 | **可删** |
| work_fixloop_cbv4 | 1.5G | fixloop cbv4 现场 | results/fixloop-cbv4-2026-09-16 | 09-16 03:04 | **可删** |
| work_compile_v3 | 1.1G | compilebench_v3 现场（v3 + v3-zh 两轮共用） | results/compilebench-v3* | 09-16 09:37 | **可删** |
| work_sabotage_mock | 694M | sabotage mock 臂（4 臂） | results/mock-sabotage-v3-2026-09-16 | 09-16 13:30 | **可删** |
| work_compile_v4 | 676M | compilebench v4 现场 | results/compilebench-v4-2026-09-16 | 09-16 02:54 | **可删** |
| work_fixloop | 628M | 初代 fixloop bench 现场（corpus39 id 结构） | results/fixloop-results.json + fixloop-spike-report.md | 09-14 18:11 | **可删** |
| work_fixloop_v3 | 579M | fixloop v3 现场 | results/fixloop-v3-* 系列 | 09-16 01:31 | **可删** |
| work_fixloop_v2 | 221M | fixloop v2 现场（corpus_v2 id） | results/fixloop-corpusv2-2026-09-15 | 09-15 15:42 | **可删** |
| work_fixloop_replay | 187M | fixloop replay baseline 现场（cases 来自 e2e-real-n100-postcutover，rules_sha256 钉版） | results/fixloop-replay-baseline-2026-09-16 | 09-16 13:37 | **可删** |
| work_compile | 140M | 初代 compilebench 现场（corpus39） | results/compile-bench.json + compile-report.md | 09-14 15:59 | **可删** |
| work_sabotage_probe | 97M | 单篇 sabotage 探针 1012.5411（+head 变体） | tmp/exp/probe_1012.5411.json + splice-residue-probe-2026-09-16.md | 09-16 14:38 | **可删** |
| work_compile_v2 | 77M | compilebench_v2 现场 | results/compilebench-corpusv2-2026-09-15 | 09-15 10:00 | **可删** |
| work_fixloop_v3_ds | 14M | fixloop docstyle 子集现场 | results/fixloop-v3-docstyle-* | 09-16 01:10 | **可删** |

## bench/corpus*/

| 路径 | 大小 | 产出者/内容 | 证据落点 | 最后写入 | 判定 |
|---|---|---|---|---|---|
| corpus_v3 | 20G | 四层 5072 篇 e-print 解压原样（core 1000 + booster 200 + expand 3800 + hot 72） | MANIFEST.md + manifest*.jsonl（5072 行）+ mechanisms/selection 入库 | — | **资产**（终极 benchmark 语料，勿动） |
| corpus_v2 | 255M | 139 篇分层随机（serial2+coverage+补抽），manifest.jsonl 217 行 | MANIFEST.md 入库 | — | **资产** |
| corpus | 114M | 39 篇手挑陷阱语料（12 旧 + 27 新） | MANIFEST.md 入库 | — | **资产** |

## tmp/（整目录 gitignored）

| 路径 | 大小 | 是什么 | 证据落点 | 判定 |
|---|---|---|---|---|
| exp/corpus-cbh | 7.7G（**独占仅 0.6M**） | corpus-by-hardlink 农场：25819 文件 nlink=2 → `bench/corpus_v3/*/raw.tar.gz` 同一 inode | 本体即 corpus_v3 的硬链接视图 | 可删但**几乎无收益**（独占 648K）；删它不等于省 7.7G |
| exp/post2020 | 794M | post-2020 / IA-bulk vs TIGER 对照探针（meta、lossy/member diff、extract_tiger.py） | docs/09 语料选型结论 | 可删 |
| exp/hyperref-versions | 111M | hyperref 版本矩阵探针 | docs/research/latex 相关 | 可删 |
| exp/frame | 91M | corpus_v3 抽样 frame 构建现场 | work_v3/frame_lookup.tsv.gz + MANIFEST | 可删 |
| exp/labels | 89M | 抽样 label/类别标注现场 | 同上 | 可删 |
| exp/ia-pilot | 73M | IA arxiv-bulk 试点抓取 | docs/research/arxiv | 可删 |
| exp/hf-datasets | 69M | HF TIGER-Lab 数据集探针 | docs/research/arxiv | 可删 |
| exp/pdf-fidelity | 29M | PDF 保真度探针 | docs/research | 可删 |
| exp/arxiv-serial2 | 29M | serial2 批次语料源（喂 corpus_v2） | corpus_v2 MANIFEST（serial2 85 篇） | 可删 |
| exp/src-snapshot-{modec,tailfix,sabotage,replay,parse,base} | 各 ~13M 共 ~80M | 钉版 src 快照（replay/对照 bench 用；fixloop-replay run_meta 引用 src-snapshot-replay） | 对应 results 目录 | 可删（对应 run 均已完成；留亦无害） |
| exp/seg-fix + seg-nofix | 28M | segmenter fix A/B 对照现场 | parsebench 相关 results | 可删 |
| exp/corpus-sources + bulk-channels | 27M | 渠道源探测 | docs/09 | 可删 |
| exp/{pstricks-probe,ctanfetch,gate,oai-probes,arxiv-probes,ts-validator,rule-validator,atp-src,fixloop-demo,gwbench,b7-241017902-ctex,export-probes,ctan,engine,atp-runs,html-dom,costmodel,datasets,e2e,corpus-profile,macro-stats,cbv3-base,selfcheck,align-probe,fixrules,fixloop-replay,arxiv-probe,fixture_assert_smoke,oracle,modelbench,trace-0806,misc,curator-c,l0-comment} | 共 ~60M | 各一次性探针/验证现场 | 对应 results/docs 已落 | 可删 |
| exp 散装文件 | ~1M | run_v3.py / run_sabotage_v3.py / run_parsebench_snap.py / run_gate.py / s3*.py / spotcheck.py 等**产出脚本本体** + 日志 | — | 再确认：脚本若未入库则是唯一留存（work_v3/sabotage 的产出者），建议先把 `run_*.py`/`s3*.py` 挪进 bench/py 或确认已有等价物再删 |
| refs | 538M | 12 个参考仓库 clone（LaTeXTrans 211M、ieeA 98M、texglot 52M、MathTranslate 50M、MinerU 39M、BabelDOC 36M、LaTeX.js 20M 等） | docs/research/* 调研档案 | **资产**（重 clone 成本低但调研上下文已消费；可删，标资产偏保守） |
| babeldoc-e2e-data | 321M | babeldoc e2e 的 TEXLATE_DATA_DIR（server db + tasks + babeldoc 工作产物） | results/babeldoc-e2e-2026-09-16 report | 可删 |
| latex209-probe | 57M | LaTeX 2.09 documentstyle 探针（prep/convert/logs） | 配合 src/texlate/compile/latex209.py | 再确认（配套未入库新模块） |
| t017 | 26M | tectonic 单探针（fixture t017 相关） | 探针结论 | 可删 |
| audit-e2e | 17M | audit e2e 现场（run-0906.1291/run-1412.6980/parse jsonl/bad.tex/pdfonly） | docs/research/audit-2026-09-16 | 可删 |
| web-check | 14M | web 检查 harness（check.mjs + node_modules + shots） | web-* results | 可删 |
| cjkfont | 13M | CJK 字体编译探针（c0707/c1003/…/t*.tex） | 进行中 | **在飞勿动**（18:00+ 仍在写） |
| share-live-b | 9M | share live server 数据目录 | results/share-live-2026-09-16 | 可删 |
| live-smoke2-data + live-smoke-data | 12M | live 冒烟 server 数据目录 ×2 | results/live-smoke* | 可删 |
| stash-recovery-0958 | 5.3M | pre-commit stash 事故恢复备份（tracked/untracked 两堆） | — | 再确认（恢复备份，确认无未恢复内容再删） |
| live-smoke 各 dbg/probe 散装 .py + probe_dispatch_out.json + __pycache__ | ~1.5M | tmp 根散装探针脚本 | — | 可删 |
| e2e-n100-postcutover-src | 2.7M | postcutover run 的 src 快照 | results/e2e-real-n100-postcutover | 可删 |
| transcript-mining | 2.0M | 会话挖掘 md 导出（本次保全用） | tmp/preclean | 保留（在飞任务产出物） |
| shimtest | 1.5M | documentclass shim 测试现场（d_aastex* 等 39 项） | fixloop shim 规则 | 可删 |
| realbook | 972K | Gutenberg epub 测试书源 | results/export-realbook-2026-09-16 | 可删 |
| doc-e2e-data + doc-e2e-data2 | 1.2M | doc e2e server 数据目录 | results/doc-e2e-2026-09-16 | 可删 |
| latex209-verify | 696K | latex209 模块验证编译现场（c0707/c0806/c1003/c2501） | 进行中 | **在飞勿动**（18:00+ 仍在写） |
| alignbench-smoke + audit-spec06 + repro2203 + preclean | <300K | 小探针 + 本目录 | — | 保留（preclean 是本产出） |

## dist / web

| 路径 | 大小 | 是什么 | 判定 |
|---|---|---|---|
| dist/ | 21M | `texlate-0.1.0` wheel + sdist（uv build 产物；results/dist-smoke 已验） | 可删（`uv build` 可再生） |
| web/dist | 8.9M | vite 构建产物（assets + pdfjs + index.html） | 可删（`npm run build` 可再生） |
| web/scripts | 14M | web 冒烟 harness（smoke.mjs 源码 + node_modules + shots） | 源码保留；node_modules+shots ~13M 可删（npm ci 可再生） |

## 顺带（超出指定范围但占磁盘）

| 路径 | 大小 | 判定 |
|---|---|---|
| bench/py/.venv_babeldoc | 664M | **可删**——babeldoc-e2e report 自述「Mac 残留、shebang 已失效」，现用 `uv tool install babeldoc==0.6.4` |
| web/node_modules | 295M | 可删（npm ci 可再生；常用建议留） |
| bench/ts/node_modules | 70M | 可删（npm ci 可再生） |
| .venv | 56M | 留（产品 venv，`uv sync` 可再生但天天用） |

## 汇总

- **立即可删（无在飞依赖）：~63G** — work_base_v3full 17G + work_v3 tars/staging ~27.5G + work_sabotage_v3 5.2G + work_e2emock 2.2G + fixloop 全家 4.6G + compile 全家 2.0G + sabotage_mock/probe 0.8G + tmp/exp 非 cbh ~1.6G + tmp 杂项 ~0.5G + .venv_babeldoc 0.66G + dist/web 构建产物 ~43M
- **在飞勿动（跑完再判）：~46G** — stagerun-loop1/work 44G（fixloop rerun + 疑似 loop2 排队）+ work_e2ereal 1.6G（postfix；其中 `_xlat_state` 25M 建议跑完也保留）+ postfix/repro-1306/repro-2410b 结果目录 + tmp/cjkfont + tmp/latex209-verify
- **资产（勿删）：~21G** — corpus_v3 20G + corpus_v2 255M + corpus 114M + work_e2ereal/_xlat_state 25M +（tmp/refs 538M 偏保守算资产）
- **再确认** — results/babeldoc 9.1M（刻意 gitignore）、exp 散装 run_*/s3* 脚本（唯一留存风险）、stash-recovery-0958、latex209-probe
- 删 corpus-cbh 只省 0.6M（7.7G 是硬链接幻象）；删 results/ 已入库目录总收益 <150M，不建议动
