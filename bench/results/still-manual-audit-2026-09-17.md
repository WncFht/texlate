# still-manual 归因环节审计 —— dossier 工具需求输入（texlate-2f）

> 数据源：`bench/results/stagerun-loop1-2026-09-16/`（records 5117 格 + tickets.jsonl 455 + cases.jsonl 6573 行）。
> 给 e8 dossier 工具当字段需求底稿：目标是把「签名→证据→历史→规则」链从人肉拼装变一键出卷。

## 0. 数据现状（dossier 的料已有多少）

| 字段面 | 位置 | 深度 |
|---|---|---|
| sig（归一化签名） | records/*.jsonl `sig` + triage `bucket_sig()` | 一级 cat:pay，聚合桶（other/errors>3/syntax）不再细分 |
| errors[] | records 行 | **薄**：仅 `{code,cat,payload}`，无 first_error 原文行 |
| first_error 原文 | compile `metrics.compile.first_error` / fixloop `metrics.post.compile.first_error` | **有但埋深**——tri­age 不消费，人工找要进 metrics 子树挖 |
| verdict | `metrics.verdict`{status,reasons,n_errors,category,payload,cjk_chars,missing_chars,warnings_hit} | 一级分类，与 sig 同层 |
| 修复轨迹 | cases.jsonl `rounds[]`/`actions[]`/`installed`/`log_excerpt` | **dossier 级**——逐轮 cat/n_errors + rule→result + 日志摘录，但只覆盖跑过 fixloop 的格（6573 行） |
| 工单 | tickets.jsonl {sig_id,stage,signature,count,example_ids,repro_path,fix_class,notes} | fix_class 四值：rule 402/core 30/shim_table 22/wontfix 1 |

## 1. 人工环节清单

| # | 环节 | 现状 | 能否机械化 | 缺口 |
|---|---|---|---|---|
| M1 | **聚合桶二次细分** | `other`/`errors>3`/`syntax`/`unfixable:other` 桶人工读 first_error 拆子类（2211.04482 missing_number 就是这么人肉归的） | **可**——first_error 原文已在 metrics，差一个 first_error→taxonomy 二级分类器 | fixloop 内部分类器（rules.yaml taxonomy）没暴露给 records/triage 复用 |
| M2 | **修复落点判定** | classify() 对 missing_file/undefined_cs/missing_character/latex209 机械归路；fallback「待人工归因」= 243 票 4278 格次（含 clean 1998 噪音） | **半可**——syntax/other/errors>3 若能先 M1 细分，多数能落既有规则族 | 细分表不存在；真实待人工面 ≈ syntax 166+errors>3 140+other 131+no_pdf 23+chunks_bad 22（去掉 clean/acceptable_pdf 噪音） |
| M3 | **静默伤侦察** | compile:clean 但带 warning sig（regression-watch 309 格）无 sig 可挂，纯人工 scan | **难**——本质是「没有签名的质量伤」，需要 verdict 代理指标（见 (c) 单） | 无自动探测面；align.py landmark/leak 指标未接 verdict |
| M4 | **工单排序派单** | tickets 按 count 降序出表后 leader 人工选 top-N 派 fixer | **半可**——count 排序已机械，选单要看边际收益（修复面重叠/攻坚难度）需判断 | 缺 sig→预计救回格数的先验表 |
| M5 | **验收回归判读** | fixer 三门（replay_case/replay_all/stats_backfill）机械跑，但**判读**仍人工（stale 回落是否预期、csb 级联影响面） | **可**——规则已明：stale=compile 重跑后旧裁决自动回落是设计行为 | 缺一键「波前后 end-state diff」工具（我每波手写 python 对账） |
| M6 | **unfixable 终态归因** | unfixable:other 6/early_eof 4/capacity 3/syntax 3… 判 wontfix vs 规则缺口人工定 | **半可**——early_eof/capacity 多数 wontfix 可机械判；other 需先 M1 | taxonomy 终态词表与 wontfix 裁定面没对齐 |
| M7 | **upstream 断供归因** | upstream:zh_missing 64/xlat_fail 1 + route reject（no_main_tex 75）回溯上游 stage 人工查 | **可**——records 链式回溯是纯机械（runbook §4 排查顺序可程序化） | 无工具；手工逐格翻 records |

## 2. dossier 字段需求（签名→证据→历史→规则 链）

```
dossier(id):
  identity:   {id, layer, era, main_rel, engine, uncompressed_bytes}
  signature:  {sig_raw, sig_bucketed, verdict{category,payload,n_errors,reasons,cjk,missing_chars,warnings_hit}}
  evidence:   {first_error_line            # metrics.compile.first_error 上提一级
               log_excerpt                # cases.jsonl 同名字段对齐
               repro_path                 # work/{id}/ 存在性
               splice_dir, texmf_tree}
  history:    {records 全 stage 时间线      # parse→xlat→compile→fixloop 逐行 + status/dur_s
               csb 链                     # fixloop.compile_status_before vs compile.status 逐条
               stale_flag                 # csb 不匹配的回落标记
               prior_tickets: [sig_id]    # 该格历史命中过的工单
               prior_waves: [wave]        # recut/recut2/尾单等波及记录}
  rules:      {candidate_rules            # sig→rules.yaml 候选（classify 雏形扩展：missing_file→install_file+shim_map、undefined_cs→cs_table、missing_char→char_table…）
               rule_hit_history           # cases.actions[] 的 rule→result 轨迹
               retired_name?              # missing_file payload ∈ retired_names() → shim_table 单
               taxonomy_class}            # fixloop 内部分类器复用输出（M1 缺口）
  gap_flags:  {needs_subclass             # sig ∈ {other,errors>3,syntax,unfixable:other}
               needs_probe                # clean+warning sigs（M3 静默伤面）
               unrunnable                 # compile 末条 reject/skip/error（rerun-wave.sh 口径复用）
               wontfix_candidate}         # early_eof/capacity/latex209/inject 面
```

## 3. 一句话缺口

**最大缺口 = M1 二级分类器**：first_error 原文已在 records（metrics 深处），
fixloop taxonomy 分类器已存在但没暴露成 records 可消费的字段——dossier 工具
若先把 `first_error→taxonomy_class` 物化进逐格卷宗，M2/M6 的待人工面会
塌掉大半（syntax 166+errors>3 140+other 131 可细分归路）。
