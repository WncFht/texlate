# realpostfix2 真臂验收报告（n=100 seed42 core, --recode, swe-2-medium, conc=2）

> 2026-09-17 收口。Run: `bench/results/realpostfix2-2026-09-16/`（records/results/matrix/summary/run_meta 全）。code stamp `c818199-dirty`。墙钟 4.03h（13:45:50→17:47 UTC），translate seconds 13729≈96% of wall——near-full re-translation（drift 面：仅 6/100 篇 translate.seconds=0 全命中）。网关零 429/超时簇。snapshot-manifest.txt 已拷入本目录（源快照 /tmp 易失）。

## Verdict 矩阵 vs 上跑（postfix-2026-09-16）

| | old | new | Δ |
|---|---|---|---|
| pipe-xel clean | 56 | **76** | +20 |
| pipe-xel fail | 9 | 14 | +5 |
| pipe-xel partial | 35 | 10 | −25 |
| 管线引入(pipe≠clean∧base=clean) | **13** | **2** | −11 |
| pipe-fix 救回(clean+partial) | 16/18 | 19/24 | 6篇新救回 |
| chunk ok | 10723/10729 | 10706/10717 | partial 5·fault 5·skipped 1 |
| splice leftover_ph | 0 | 0 | gate PASS |

## 13 格 pipeline-introduced 逐格对照

**11/13 复 clean（本轮修复有效）**：0707.3950、1003.4522、1012.1321、1109.5963、1206.1808、2003.10959、2105.03900、2211.04495、cond-mat/0307508、hep-ph/9703228、math/0111203 —— 全部 partial→clean，base 不再触发。

**残留 2 格**：

- `0905.4907`：partial(errors>3=4 syntax) vs base clean。改善点：missing_chars 92→0、cjk 1438→1478（缺字面修好），剩 4 个 syntax error 仍非 clean。
- `hep-ph/9910403`：fail no_pdf vs base clean。签名迁移 expl3_backend(n_errors=3)→other(n_errors=2)，仍未出 PDF——需要单独深挖，这是唯一一个 fail 级引入格。

## 新露头签名

1. **`already_def:Ref`（1511.06879）**：clean→fail，但 base 同签名同 n_errors=21 → 源生问题非管线引入（疑环境/texmf 漂移致源编译行为变化，上跑 pipe clean 时未触发 base）。pipe-fix 救回 clean(9473 CJK)。
2. **missing_file 集群 partial→fail（4 篇）**：astro-ph/9703134(aaspp4.sty)/9703152(amssym.sty)/9703198(crckapb.cls)/cond-mat/9703161(eqsecnum.sty)。旧 verdict latex209(出PDF)；新 no_pdf。**base 同样 fail → 不算引入**，但行为变了：编译面对缺 legacy sty 的旧稿不再出部分 PDF。这批加上原有 7 个 missing_file fail（elsart/aa/aipcheck/iopart12/aastex63/espcrc2×2，逐格签名与上跑完全一致）构成 era 天花板，fail 9→14 的 +5 全部由此解释。
3. **chunk 级非 ok 11 块/7 篇**（上跑 6 partial/0 fault）：fault=2203.13012×1、2403.15096×3、hep-ph/9703228×1；skipped=0905.4439×1（warn_kinds「skip:chunk crash」——新签名，单块 crash 被跳过）；partial×5。ok 率 99.90% vs 99.94%，量级正常但 fault 类是新露头。
4. fix 臂增益：0806.1079/1608.02516 partial→clean、1206.5921→clean、2308.12712 fail→partial、1511.06879→clean。

## 门槛判决

- splice leftover_ph=0 PASS；翻译执行 100/100 PASS；chunk ok 率 99.9% PASS。
- **管线引入 13→2：本轮 splice/emit 修复验收 PASS**（11 格复 clean，0 格新引入——新 fail 全为 base 同挂的源生 missing_file）。
- 残留：hep-ph/9910403（fail 级引入，签名 expl3_backend→other）、0905.4907（4 syntax errors）；新观测签名 already_def:Ref（源生）、skip:chunk crash、missing_file partial→fail 行为迁移（compile/judge overlay 这轮动过，待确认是否有意）。

## 附：gate_scorecard（stagerun-loop1 正式 M2 判读，同刻快照）

`python3 bench/py/gate_scorecard.py`：cells=5059，union-pdf **89.68%**（门 ≥90%，差 +17）；excl-reject(n=4645) pdf 97.67%。stagerun 记录仍在随 fixable-data 波次追加，分数为动态值。

- end-state top：compile:clean 2669 / fixloop:partial 1031 / compile:partial 593 / compile:reject 414 / fixloop:clean 244。
- top non-clean sigs：acceptable_pdf 518 / inject:latex209 414 / undefined_cs 181 / best_effort_pdf 150 / errors>3 130 / illegal_unit 115。

## 收尾判读备忘（scout-e2ereal 取证）

- `compile.ok` 只表示没超时——verdict 以 `verdict.status` 为准；rc=141 格查 bwrap 信号编码逃逸。
- 3 格非终态（0905.4439/2203.13012/2403.15096）任何重启会重跑且 verdict 可翻转。
- 续跑须 `TEXLATE_SRC=<同一快照> --recode --date 2026-09-16 --tag realpostfix2`，且重启前确认 live repo src/texlate 未变（code 印章钉 live repo 不钉快照）。
