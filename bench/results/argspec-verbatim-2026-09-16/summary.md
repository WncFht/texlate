# argspec 分派三缺陷修复 — 2026-09-16

任务 #96 跟进件：verbatim policy `%` 退化、`\hyperref` 族表遮蔽、argspec boundary/transparent 死路径。证据目录：本目录 `parsebench/`（修复后 corpus-cbh 全量复跑）。

## 根因与修复

### 1. verbatim policy `%` 退化（真 bug）

`_handle_argspec_cs` 的 verbatim policy 原走签名 token 读参：`\hyperbaseurl{http://x%20y}` 中 `%` 被 Mouth 当注释吃掉，闭括号丢失 → 组未闭 → 退化为裸名 `[[CMD]]` + `http://x` 泄漏进 chunk（URL 残片会被送翻译）。

verbatim policy 的语义是 ctan-argspec 定界式约定（`\url`/`\path` 同款：参数内 `%`/`#` 字面）。修复：policy == "verbatim" 直接委托 `_protect_cs(t, src, PhType.CMD, mand=<m/v 位数>, verbatim=True)`——字节级 `match_brace(file_texts[fid], pos, verbatim=True)` 配对 + `_skip_past` 按 token 位置 resync，绕过 token 流的注释截断；`\cmd|x|` 定界形同规则覆盖。

可达 verbatim 条目仅 `\hyperbaseurl`/`\nolinkurl`（`\url`/`\path`/`verb` 本就被 row8/row1 先行且已逐字处理）。未闭参数仍回退裸名 `[[CMD]]`。

### 2. `\hyperref` 遮蔽（真 bug）

分派 row7 的 `*ref` 后缀规则以 `mand=1` 罩 `[[REF]]`：`\hyperref[label]{text}` 只罩 `[label]`，text 带括号留在 run；`\hyperref{u}{c}{n}{t}` 同理。hyperref 是全表唯一带 text 角色的 `*ref` 名。

修复两件套：row7 排除表加 `hyperref`（与 `href` 并列）；argspec.json 签名 `o m` → `m m`——`m` 位兼收 `[` 组，故文档形 `[label]{text}` 与民间 `{label}{text}` 皆 key 位留字面、text 位出 chunk。罕见 4 参形 `{u}{c}{n}{t}` 退化可接受：`{c}` 出小 chunk、`{n}{t}` 带括号留 run 仍随段翻译。

刻意保留：expansion 面 `_group_surface` 的 `*ref` 规则仍遮蔽 hyperref（展开上下文无字节级参数可取，保守罩 `[[REF]]`）；v1 `scanner.py` 同款规则不动（fallback 臂）。

### 3. boundary/transparent 死路径（结构性）

证明不可达：argspec 全表 6/6 transparent ∈ TRANSPARENT_NAMES、45/45 boundary ∈ BOUNDARY_NAMES/`\begin`/`\end`——`_dispatch` row13/14 先于 row19 argspec。强制走通验证两分支语义本就正确（transparent 名内联参回吐、boundary flush+LITERAL）。

处置：分支保留（语义正确），到达即表/族漂移 → 记 `ScanWarning("argspec_shadowed")` 但不改语义；docstring 注明不可达口径。新增遮蔽不变式测试枚举全表断言每条都被前段行截获，漂移时测试先响。

## 前后对照

| 输入（`\usepackage{hyperref}` 门控） | 修复前 | 修复后 |
|---|---|---|
| `\hyperbaseurl{http://x%20y}` | `[[CMD]]`=`\hyperbaseurl`，`http://x` 泄漏 | `[[CMD]]`=`\hyperbaseurl{http://x%20y}` 整调用 |
| `\nolinkurl|a%20b|` | 定界形不识，参读签名退化 | `[[CMD]]`=`\nolinkurl|a%20b|` |
| `\hyperref[sec:x]{Words}` | `[[REF]]`=`\hyperref[sec:x]`，text 留 run | key 字面 + chunk ctx=hyperref "Words" |
| `\hyperref{sec:x}{Words}` | 同上 | 同上 |
| 裸 `\hyperref`（无参） | `[[REF]]`=裸名 | 名内联（同未知裸 cs / `\alert` 零参口径） |
| `\autoref{sec:x}` 等 key-only `*ref` | `[[REF]]` 整调用 | 不变 |

## 验证

- 单测：`tests/test_argspec_dispatch.py` + `tests/test_segmenter_semantics.py` + `tests/test_latex_argspec.py` 84 全绿；latex 面 358 全绿。新增钉点：`%` 字面保留 / 定界形 / in_arg / 未闭回退 / `%` 吞外层组闭括号 / hyperref 两形态 / autoref 对照 / 遮蔽不变式 / 死路径强制到达告警。
- ruff：`src/texlate/latex/` + 两测试文件 check+format 干净（`_handle_argspec_cs` 补 `noqa: PLR0911`，与邻函数同款）。
- corpus identity：corpus-cbh 3937 文件全量复跑（`parsebench/`，wall 409.9s）对基线 `parse-v3-full-2026-09-16` 逐文件零差异——parse ok 3937/3937、strict identity 3935（同 2 个既有 diverged）、leak 92/216126=0.04%、n_chunks/n_placeholders/warn_kinds 全等，`argspec_shadowed` 零触发（死路径在语料上仍全遮蔽）。
- 定向快照 diff：语料中 40 个含 `\hyperref`/verbatim-policy 名的文件（快照 `tmp/exp/src-snapshot-parse` 修复前 vs 当前）仅 2 个 `.synctex` 有差异——`\hyperref` 出现在 Windows 路径片段（`\hyperref\hyperref.sty` 裸名无参），修复前出 `[[REF]]` 裸名、修复后名内联，引起下游 `[[MATH_n]]` 重编号；identity 仍 True、chunk 数不变。语料 `.tex` 内 `\hyperref` 均位于 `\newcommand`/`\DeclareRobustCommand` 定义体或注释，不进分派——故 corpus 面零影响，新行为由单测钉住。

## 变更文件

- `src/texlate/latex/segmenter.py` — row7 排除 hyperref；`_handle_argspec_cs` verbatim 委托 `_protect_cs(verbatim=True)` + 死路径告警 + docstring + noqa。
- `src/texlate/latex/data/argspec.json` — `hyperref` 签名 `o m` → `m m`。
- `src/texlate/latex/model.py` — `ScanWarning.kind` 注释补 `argspec_shadowed`。
- `tests/test_argspec_dispatch.py` — verbatim `%` 钉点重写 + 4 新测试（定界/in_arg/吞括号回退/遮蔽不变式+死路径告警）+ hyperref bracket 形。
- `tests/test_segmenter_semantics.py` — `test_family_ref_suffix_beats_argspec_chunk_arg` 重写为 hyperref 两形态 chunk-arg + autoref 对照。
