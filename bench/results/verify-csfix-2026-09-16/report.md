# verify-csfix — cs_targeted_fix 实战验收（4 格 bug-B 全愈）

> 2026-09-16。现场 `tmp/csfix-verify/`：冻结 zh 树直拷自 `bench/work_e2ereal/pipe-xel/`，清编译残留后跑产品化 fixloop（xelatex + 共享 usertree + tlpdb 缓存索引，llm_hook=None 不调网关）。cell JSON 在 `tmp/csfix-verify/<id>.cell.json`，每格 ~2–8s 编译。

## 结果：4/4 再现、4/4 命中、4/4 verdict=clean

| id | 错误再现 (fixloop r1 实编) | cs_targeted_fix 命中 | 命中路径 | 终态 |
| --- | --- | --- | --- | --- |
| 1003.4522 | ✔ r1 `undefined_cs:hlineCd` → r2 `hlineNb` | ✔ r1+r2 两连发 | hlineCd=显式条目；**hlineNb=split_heads 兜底**（cs_table 无此条，head=hline+大写残余 Nb→"hline Nb"——兜底层首获实战证据） | clean（r3 err=0） |
| 1206.1808 | ✔ r1 `pari` → r2 `parii` | ✔ r1+r2 | 均显式条目 → `\par i)` / `\par ii)` | clean |
| 2003.10959 | ✔ r1 `itemNGA` | ✔ r2（r1 先被 vendored_sty_shadow 正当接走：vendored eso-pic.sty 2002<2025 隔离；同 payload 下轮落到 cs_targeted_fix） | 显式条目 → `\item NGA` | clean |
| 2105.03900 | ✔ r1 `itemBalakrishnan`（唯一起步无 pdf 格，started_fail） | ✔ r1 | 显式条目 → `\item Balakrishnan`；**级联 missing\item 同源痊愈**（融合解除后 \item 归位，l.188 次生错不再出现） | clean（r2 直接 err=0+pdf） |

改写后文本目检正确（`\hline Cd`/`\par i`/`\item NGA`/`\item Balakrishnan`），全树无融合 cs 残留。

## 观察

- 规则缺口：这 4 格无缺口。
- 签名面：payload 均为裸 cs 名（无反斜杠），cs_map `\old\b` 词边界改写无越界误伤。
- split_heads 兜底层首获实战命中（hlineNb）——说明显式条目表不必穷举，head 拆分路径本身正确。
- vendored_sty_shadow 优先级高于 cs_targeted_fix 属正当排序（先隔离旧版 vendored sty，再修 cs）。

## 可选收尾（非阻塞，leader 定）

- rules.yaml stats 计数 fires:1→5 / rescued_cells:1→5 属实战新证据，可更新（已转项目体验方式）。
- `hlineNb` 可提为显式条目——纯账目，split_heads 兜底已正确拆对，非必须。
