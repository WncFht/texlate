# report.md — modec-v3-tailfix-2026-09-16（Mode B/C 全尾段口径复跑 vs 旧基线）

## 运行面

- 样本：旧跑 `modec-v3-2026-09-16/sample.json` 同 50 id（`--ids` 精确对齐）；臂 `base-xel,pipe-xel,pipeB-xel,pipeC-xel`；时长 ~21min。
- 代码面：harness=工作树 `bench/py/e2e_mock_bench.py`（post-c69353e）；`texlate.*` 冻结在 `tmp/exp/src-snapshot-tailfix`（TEXLATE_SRC，隔离在途改动）。
- 产出：`bench/results/modec-v3-tailfix-2026-09-16/`（records.jsonl/results.json/matrix.md/summary.md/run.log + compare.py/provenance.json/ids.txt）。

## verdict 分布 old→new

- base-xel：clean 22→23/48（1306.1931 fail→clean——环境漂移归因见下）
- pipe-xel：clean 27→30（fail 6→3：1511.02951/1511.06763/astro-ph/0605325 全救回）
- pipeB-xel：clean 24→30，reject 5→0，fail 8→3 —— 12 篇变好 / 0 篇变差
- pipeC-xel：clean 17→29，reject 5→0，fail 8→3 —— 18 篇变好 / 0 篇变差

## Mode B 门槛：escaped==0 仍 PASS

台账逐字节不动：1564 破坏块 / 4932 事件 → caught 1345 / recovered 219 / escaped 0；by_kind 三分项（drop_ph / fabricate_ph / 复合）与旧跑全等。破坏注入在翻译层按内容哈希定死，尾段拉齐不碰它——事实验证了这一点。

## Mode C

- splice：挪位 2537→2516 / 涉块 1590→1572 → 进 splice 1557（99.0%）/ 回退 15。全部漂移集中在 nucl-th/0307063 一篇（events 25→9，chunks 同为 103——ChunkIn 内容因 ph_map 武装变化→哈希决策漂移，确定性偏移非噪声）。
- 存活：35/42 → **45/45（100%）**，旧 broke 7 篇全救回。

## 逐篇差集归因（30 个变好格，0 个变差格）

- reject→partial ×5（astro-ph/0104134、astro-ph/0501428、cond-mat/9910284、math/9901064、nucl-th/0307063）：全是 `latex209` inject 策略拒绝。pipe 臂新旧都是 `partial + reject_at: inject`（F3 口径）；B/C 臂旧口径记 `reject`，现拉齐——纯口径修正，非修复。
- fail→clean/partial：L2+fixloop 尾段真实救回（如 quant-ph/0307209 fail→clean、hep-th/0408076 fail→partial）。
- 剩余 pipeC fail 3 篇全部与 pipe-xel 同步 fail，非 Mode-C 特异性：1306.0364、2308.00072 是原生失败（base 也 fail）；2203.00092 是 `lib/preprint.cls:163` pgffor 扫描错——pipe 层既有缺口，新旧一致（fixloop 判 unfixable:other）。

## 退化清单变化

- 管线引入（pipe 非clean ∧ base clean）：旧 `[0806.3472]` → 新 `[0806.3472, 1306.1931]`。
  - 0806.3472 不变（repro-0806 在查）。
  - **1306.1931 是名单口径假象，非真回归**：base 臂 fail→clean 是因 `youngtab.sty` 已落 `~/texmf/tex/generic/youngtab/`（此前某次 fixloop ctan 安装残留给 base 也受益）；pipe 维持 partial（missing_chars×80 warn + illegal_unit，fixloop 1 轮后 acceptable_pdf）。pipe 没变差，是对照线抬高了。**注意：fixloop ctan 装包装进用户级 texmf 会污染后续 base 对照——跨跑环境漂移源。**

- 破坏臂 < pipe 臂：旧 pipeB 8 篇 / pipeC 15 篇 → 新各仅 `hep-th/0408076` 1 篇（pipe clean，B/C partial——破坏真实代价面：B 臂 72 块中 65 caught 回退英文原文、C 臂 75 处挪位进 splice，残 4/7 个编译错；已从 fail 改善到 partial）。

## 信号检查

fault_chunks 只在 pipeB 大量出现（L0 拦破坏块→fault 计数，预期行为）+ pipeC 零星；leftover_ph 全零——无占位符泄漏。

## 结论

尾段拉齐后 B/C 臂 verdict 与 pipe 严格可比：三臂 clean 30/30/29（pipe 30），旧口径 reject 5 + fail 8 的假象全部消解。escaped==0 门槛 PASS。新增"引入"名单成员 1306.1931 为 base 环境漂移假象；真实遗留缺口三处：0806.3472（repro 在查）、2203.00092 pgffor、hep-th/0408076 破坏代价。
