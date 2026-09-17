# peer1 下一梯次排期 — M1-B 残余收尾 (2026-09-17)

收线指令快照：41 批的 5 件序中 1-2 + rules_declined 已交付（见下方清单）；3-5 件与遗留面转本档，下一梯次开工时按序取。

## 已交付（本批，待 41 统一 commit）

| 项 | 文件 | 证据 |
|---|---|---|
| 1. ell 表条目 | `src/texlate/compile/fixloop/rules.yaml` | char_table 尾 `ell 0x2113 → \ensuremath{\ell}` |
| 2. diagrams stub 富化 | `src/texlate/compile/fixloop/vendor/stubs/diagrams.sty` | 1206.1835 splice 重编 172→0 errs、main.pdf 出 |
| R. rules_declined 物化 | `engine.py` + `cases.py` + `tests/test_fixloop_cases.py` | decline 面落 cell→cases.jsonl，白名单键已加 |
| 钉 | `tests/test_fixloop_wave4_vendor.py` | +1 真编译钉（options/&-\cr/\newarrow/嵌 equation/plain 式） |

## 待开工（按 41 原序）

### 3. font_cs_shim builtin (M)

- 目标格：fivmi 类 —— doc 的 `\skewchar\fivmi` 撞从未 `\font` 定义的字体 cs（定义在 `\doit{0}` 死块里，原始 arXiv 源即如此）→ undefined_cs 抢占 missing_tfm，install_tfm 链够不到。
- 路线：新 builtin 把 AMS 系 `<size>mi/sy/ex/bf` 字体名 shim 到 cmmi/cmsy/cmex/cmbx 等价件。批准在案（41 裁决第 3 项）。

### 4. cs_rebind 第三子路径 (M)

- 目标格：command-generated missing_char —— `\S`→U+00A7、`\o`→U+00F8 等在 TU 编码下产出码位、TFM 字体无槽；字面 replace 与 newunicodechar 都够不到（无字面部）。
- 起步 produced_by 码位表 9 项：A7→`\S`、F8→`\o`、D8→`\O`、141→`\l`、B6→`\P`、A9→`\copyright`、2020→`\dag`、2021→`\ddag`、A3→`\pounds`。批准在案（41 裁决第 4 项）。

### 5. jinstpub stub (M)

- 先盘点 doc 用量再定厚度（41 原话）。其余残余：env/cs 未定义 3 格 + 单点 4 格，待两簇收完后归并。

## Backlog（不回本）

- owrart.cls `\bm`-CJK 守卫（41 裁决第 6 项，同意进 backlog）。

## 备注

- rules_declined 是在收线指令到达前已实现+全绿的，是否随本批入库由 41 定。
- `peer1-residue-routes.md`（逐格证据路由文档）同目录，尚未入 git。
