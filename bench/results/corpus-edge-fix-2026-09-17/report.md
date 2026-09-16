# corpus-edge-fix — 存疑待裁项裁决落地交付

> 2026-09-17 收口。落地 `4cfcd4c`（build_corpus_expand.py +13/-3）。全部改动单文件，探针 `tmp/corpus-edge-fix/`（gitignored，先复现后验证）。

## 修复 1 — n100_rates 空输入（裁决：诚实报告而非崩）

- build_corpus_expand.py:164-166 — `res` 为空时 `log("n100 结果为空 … — band/cat/global 故障率报 0")`（走 b3.log → stderr）并早退 `({}, {}, 0.0)`。
- build_corpus_expand.py:308-313 — **同一崩溃链的下游补闸**：cmd_plan 里 `rel = …/ fr_all` 在 `fr_all=0` 时仍会 ZeroDivisionError（不只空输入，n100 非空但零 bad 也必踩）。`fr_all` 为 0 时 `rel=1.0`——无故障信号可加偏，配额退化为纯按 cell 规模分配。属裁决「空集应诚实报告而非崩」的端到端落地。

## 修复 2 — largest_remainder 负权重（裁决：契约违例 fail fast）

- build_corpus_expand.py:193-196 — 入口收集全部负权重 `{k: w}`，违则 `raise ValueError(f"negative weights: {neg}")`，消息指名每个负权重 cell 及其值（沿用本文件 `msg = …; raise` 风格）。

## 探针

- probe_n100_empty.py：修前 `n100_rates([])` 与 `cmd_plan` 均 ZeroDivisionError；修后函数返回 `({}, {}, 0.0)`，cmd_plan 真索引全程跑通（38 cells、sum=100、quotas 与 `largest_remainder(cell_counts)` 纯比例逐项相等）；非空回归 global=0.690 正常。probe 内将 PLAN_JSON 重定向 tmp，未碰真 expand_plan.json。
- probe_largest_remainder.py：修前 `{"cellA|x":-1,"cellB|y":2}` 静默产 `{'cellA|x': -10, 'cellB|y': 20}` 负配额；修后 ValueError 指名 cellA|x 与 -1.0，多负值全指名；正常/零权重/空 dict 回归全过。

## 自验

`python3 -m py_compile` ok；`ruff check` 净；`ruff format` 已应用并复 check 净。leader 复核同净。

## 追加裁决（在飞）

- `largest_remainder` 全零权重 `s=0` → ZeroDivisionError——agent 发现并留裁。leader 裁决：**同属契约违例 fail fast**（静默均分会掩盖上游 bug），已派回补闸。
- bench-tsl partial-tree timeout：按要求仅核实为记录在案观察项，未动。
