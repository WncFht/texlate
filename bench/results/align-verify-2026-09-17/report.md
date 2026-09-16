# align-verify — align.py 真实产物端到端验证（全 PASS，零缺陷）

> 2026-09-17 收口。验证型零代码改动。align-sweep `47373cb` 4 项修复全部在真 PDF/手术件上实证生效。证据 `tmp/align-verify/`（MATRIX.md + crosscheck.jsonl + e2ereal/ + tex/out 手术件）。

## 矩阵（全 PASS）

**A 评测侧**：`alignbench --e2e-real bench/work_e2ereal` → 490 对：35 ok（retention 全 1.0）/452 degraded/3 invalid_pdf/0 error，gates 全过。

**B 产品侧交叉**（496 对=490 e2ereal+live-smoke/smoke2/babeldoc/stagerun×3）：38 landmarks/458 pages；0 异常、0 越界 fraction、0 单调性违例、120 regions 边界全合法。
- live-smoke 录制 dual.json 逐位复现：129/129 pairs 全同（regions 现产 7 vs 录制 0——特性后于产物）。
- 3 invalid_pdf → kind=pages 优雅降级；4 个 eval-vs-prod chain 分歧全部归因真锚 /Top=847.867>页高 841.89（yfrac 1.0071）——产品钳 [0,1] 预期分歧，两侧各自单调。

**C 4 修复实测**：
1. 无 /Top 页顶排序：真 /Fit dest（dvipdfmx `\special{pdf:dest}`）→ 链首 fraction 0.0 单调（旧代码非单调）✓
2. 畸形 /Top 三形态（text/NullObject/indirect）侧全存活 ✓
3. mediabox 0 高/-842 负高→792 回退、heights 归一、fractions 界内（旧代码 -842 泄漏 fraction 1.85）✓
4. regions：(b) indirect /Rotate 0 → region=1（旧 int(IndirectObject) TypeError 整页丢）✓；(c) 坏 XObject 兄弟只丢坏图真图 region=1 ✓；(a) 继承 /Resources 无回归 ✓
- 附加：乱序锚被单调链正确丢弃；letter×a4 各自归一；单侧无锚/50% 截断→kind=pages 不崩。

## 观察（非缺陷）

- O1：非数值 /Top 文本被 pypdf 预转 FloatObject(0.0) 落页底锚（fraction 1.0）而非页顶回退——归一化发生在 `_dest_yfrac` 上游；输出仍单调，仅语义差异。
- O2：live-smoke 录制 dual.json regions=0 vs 现产 7——产物先于 regions 特性。
- O3：`extract_landmarks` 坏 PDF 抛异常 vs `build_alignment` 降级——契约差异一致。
- O4：fix 4a（get_inherited）文件层新旧不可区分——pypdf 页树遍历已扁平可继承属性；修复属纵深防御，单测的读后手术才是真判别面。
- O5：/Rotate 90 页图形检出+签名匹配但 caption 容差几何上不归属→region 缺省 pairs 插值，非吞错。

## 结论

align.py 锚点同步在 496 对真实产物上零缺陷；`47373cb` 四项修复实证生效。现场可重跑。
