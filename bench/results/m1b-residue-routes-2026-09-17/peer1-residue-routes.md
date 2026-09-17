# M1-B 残余逐格路线裁决（peer1，2026-09-17）

> 对 2f `m1b_wave_report.md` 残余清单的逐格取证。证据点：`bench/results/stagerun-loop1-2026-09-16/{cases.jsonl,work/<id>/splice/*}`，行号为当日快照。

## 簇 B：errs=0 仍 partial ×3 —— 判据诚实，非口径件

三格同形：round-1 `warn_missing_char` 分类正确触发，但 `_match_apply` 无规则落 → `dirty_pdf`→`acceptable_pdf`（engine.py:1544-1551）。逐格缺字身份：

| 格 | 缺字 | 来源 | 判定 |
|---|---|---|---|
| 1502.06189 | ℓ U+2113 ×2 in lmroman9 | **字面**在 .bbl:157,275（"ℓ1 minimization"）；.tex 内仅注释 | `_MC_TABLE` 无此码位 → unmatched decline |
| 2403.15096 | § U+00A7 ×1 in cmr10 | **非字面**——源里是 `\S` cs（main.tex:480/482/484/1041 `\cite[\S 7]`），TU 编码下 `\S`→U+00A7 请求 TFM cmr10 无槽 | 字面替换无靶 → decline |
| physics--9901057 | ø U+00F8 ×2 in cmr9 | **非字面**——`Gr{\o}nbech-Jensen`/`{\o}` (phos.tex:545,778) 同理 | 同上 |

**结论：judge 无过**——缺字是真实静默丢字（ø 掉后人名 "Grnbech"），partial 判得对。修复面缺口两条：

1. **表扩列（S，立即可做）**：rules.yaml `missing_char_fix.params.char_table` 加 `{id: ell, cps: [0x2113], replace: "\\ensuremath{\\ell}"}` → 1502.06189 应清。
2. **cs 生成面（M，新机制）**：§/ø 类缺字由 `\S`/`\o` cs 在 TFM 字体下生成，literal-replace 与 newunicodechar 都够不到。需要 `cs_rebind` 子路径：cp 命中表但源无字面时，`params.char_table` 条目带 `produced_by: "S"`（产出 cs 名）→ 注入 `\renewcommand\S{{\txlatefallback §}}` 式回退字体绑定（复用 `_fb_snippet_lines` 的字体族）。建议挂 missing_char_fix 同规则内第三子路径，~40 行。覆盖码位→cs 映射小表：A7→S、F8→o、D8→O、141→l、B6→P、A9→copyright、2020→dag、2021→ddag、A3→pounds。

**records 副发现**：decline 注记走 `ctx.events` 不落 cases.jsonl（无 `log` 键）——"规则看见了但拒修"在记录面不可见，本次靠 work 目录重推。与 measurement.md §5 的 `rules_fired` 互补：`rules_declined`/`decline_notes` 是下一块该物化的字段。

## 簇 A：非 vendored 包缺件 ×5 —— 逐格路线

| 格 | 缺件 | 实际路径 | 残余 | 路线裁决 |
|---|---|---|---|---|
| 1206.1835 | diagrams.sty | vendored_fetch 命中 stubs 落位 ✅ | 172 errs：`Misplaced \cr`×22（stub 把体包进 `\[` 但没 `\let\cr`）+ `\rEqualto`/`\dEqualto`/`\newarrow`/`\xyoption` 未定义 | **stub 富化**——stubs/diagrams.sty 补 ~20 行：`\cr`→行分隔、Equalto 族、`\newarrow` 空宏、`\xyoption` gobble |
| hep-ph/0605174 | citesort.sty + elsart.cls | 两件均 vendored 落位 ✅（files+stubs 各一） | 1 err：`Extended mathchar used as mathchar`——`\bm{这是译文}` CJK 进 bm 提字码 | **非缺件面**：splice 边缘（CJK 泄进 `\bm{}`）。可选 normalize 侧 `\bm` CJK→`\mbox` 守卫，单 err 低值 |
| 2104.00109 | jinstpub.sty | 不在 inventory → legacy_pkg_shim 通用壳 | r2 syntax + salvage 39 errs | **新 vendor stub**——JINST 刊包 off-CTAN，stub 需载 doc 实际用到的 env/cs 面（先盘点 \jinstpub 用量再定厚度，~M） |
| 2104.00118 | hxetex.def（+owrart.cls） | hxetex 驱动已被 hyperref_driver_neutralize 解 ✅ | 1 err：cleveref `\cref@override@label@type` 定义不配——owrart.cls 缺→类回落二阶伤 | **低优先**：1 err 值不回一个 class stub 成本；owrart 韩系刊件可查许可后入 vendor files/ |
| hep-th/9703214 | fivmi 族 TFM | 无 `\font` 装载动作（定义在 `\doit{0}` 死块内）→ `\skewchar\fivmi` 落 undefined_cs 非 missing_tfm，install_tfm 接不到 | 83 errs：`\skewchar\<cs>` 对未定义字体 cs | **新 builtin `font_cs_shim`**：扫 `\skewchar\<cs>`/`\font\<cs>=` 用而未定义者，AMS 命名 `<size>mi/sy/ex/bf` → `\font\<cs>=cm*` 等价注入（fivmi→cmmi5 等）。~30 行，对老 AMS 档通用 |

## 优先级建议

1. ell 表条目（S）→ 立即清 1502.06189
2. diagrams stub 富化（S-M）→ 172-err 最大单格残余
3. font_cs_shim（M）→ 83-err + 对老 AMS 族普适
4. cs_rebind 子路径（M）→ §/ø 两格 + 未来同类
5. jinstpub stub（M，先盘点用量）
6. owrart.cls / `\bm`-CJK 守卫（低值，进 backlog）
