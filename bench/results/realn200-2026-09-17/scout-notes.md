# scout-realn200 — real-arm n200 样本预备（texlate-2f）

> 状态：**备弹完成，真跑待 token 面确认**（swe-2-medium promo 窗口 2026-10-16 到期，
> 网关 fht-mba:3003）。谱系 = realpostfix2 的 n100 后续规模验证。

## 选样

- 宇宙 = corpus_v3 四层 manifest 并集 5072，逐层保留 layer 出处。
- 排除三类：realpostfix2 已测 24 格（`cases.jsonl` 的 `corpus` 字段，`--`→`/` 还原）
  ＋ 未 extracted 13 格 ＋ **src blob >20MB 重件尾 75 格**（p99≈25.5MB，max 91.5MB；
  此阈值替代 overseer 口径「2410.x 尾聚」——按前缀排会误剔 109 格正常尺寸近期件，
  按体积排才命中真尾聚：2410.00035/17952/17973 等 6 格 >20MB 的 2410.x 仍被剔）。
- 分层 = 按 layer 比例配额（seed=42）：core 39 / booster 7 / hot 2 / expand 152。
- 产出 200 格：`ids.txt`（扁平清单）+ `manifest.jsonl`（全字段行，含
  bytes/n_tex/stratum_cell，供下游直接消费）。

## 分布自核

- 2410.x 保留 4 格（全部 <20MB 正常尺寸），年代/档案馆分布随层自然摊开。
- 与 realpostfix2 n100 零重叠（alumni 排除保证）。
- 规模口径：n200 ≈ realpostfix2 的 2×，覆盖 expand 层 152/200——expands 是主残留
  池（no-pdf 池 80 格 compile:skip 大多在 expand），real-arm 对其最敏感。

## 待办（token 确认后）

1. `e2e_real_bench.py --tag realn200 --ids-file ids.txt`（沿用 postfix2 参数面：
   model=swe-2-medium, base_url=100.105.212.52:3003, concurrency 按 token 余量定，
   base_mode/fixloop_mode=onfail）。
2. src freeze snapshot 到 /tmp（postfix2 惯例：`cp -a src/` → `TEXLATE_SRC`，
   防止波中共仓脏树漂入 real 臂计时）。
3. 产出 cases.jsonl/records.jsonl/results.json/matrix.md/summary.md + report.md，
   与 postfix2 目录同构。

## 报告 caveat（overseer 2026-09-17 补录）

audit 实证 e2e_real `translate_tree` **零文件闸**：.rtx.tex/.code.tex/file_has_prose
全漏——real 臂把 REVTeX dump/support 件也送译，chunk 体积类指标比产品口径虚高。
mock 臂走 `e2e._scan_tree` 有闸 → **两臂口径不对等**。定性：run 不中断（基线
realpostfix2 同码，横向可比）；报告里 chunk ok-rate/送译量类对比须标注此 skew，
pdf/clean/fixloop 救场类终态指标不受影响。

**已修复（2026-09-17，`a08dda3`）**：`translate_tree` 改调 `e2e._scan_tree`，
四门生效；记录键 `parse_fail` → `fault_files`/`support_files`/`support_skipped`。
**口径断点**：本 run（含）之前 real 臂体积类指标不可与修复后新 run 直接比。
