# repro-2501-2026-09-16 — 2501.14787 "partial" 根因

任务现场：`/tmp/tw-8932/tasks/t_1eb25aae917fc304/`（web-resmoke，mock 翻译臂）。
结果：14 errors → fixloop 无规则命中 → `dirty_pdf` + L2 误判归因 → `retryable:True` → partial。

## 错误清单（compile.log，zh 臂）

| # | log 行 | 错误 | 归属 |
|---|--------|------|------|
| 1 | 1298 | `! Undefined control sequence. l.88 \DeclareUnicodeCharacter{03B5}...` | 缺陷 A |
| 2 | 1308 | `! LaTeX Error: Missing \begin{document}.` (l.88 恢复级联) | 缺陷 A |
| 3–10 | 1329–1392 | `! Undefined control sequence.` l.89–96（其余 8 个调用） | 缺陷 A |
| 11–14 | 1820–1856 | `! Package xcolor Error: Undefined color '这是译文'.` ×4 | 缺陷 B 残留 |

en 臂（`build-en/_tect_out/main.log`）：10 errors — 同样 9 个 `\DeclareUnicodeCharacter` undefined_cs（l.60–68）+ 1 Missing-\begin{document}，**无** xcolor 错误。

## 缺陷 A：`\DeclareUnicodeCharacter` 在 XeTeX 下未定义（源级不兼容）

**机制链**：论文 preamble（`src/main.tex` l.60–68，lindrew 风格遗留）调用 9 次 `\DeclareUnicodeCharacter{XXXX}{$...$}` —— 这是 pdfLaTeX/inputenc 私有命令，在**所有** XeTeX 内核下未定义（tectonic 2021-11-15 与 xelatex 2025-11-01 双内核实测）。normalize 的 `strip_input_encodings` 无辜：`\usepackage[utf8]{inputenc}` 在 XeTeX 下本就是 no-op（"inputenc package ignored with utf8 based engines"），utf8.def 从不加载，命令从未被定义。9 个 undefined_cs + 首错恢复级联出 Missing-\begin{document} = 10 errors。**en/zh 两臂同炸** → 与翻译无关，源级缺陷。

**修复**（已直接落 `src/texlate/compile/normalize.py`，`normalize.py.patch` 为留档 diff）：`XETEX_COMPATIBILITY` 前导块尾追加 lccode 惯用法 shim——

```latex
\providecommand{\DeclareUnicodeCharacter}[2]{%
\begingroup\lccode`\~="#1\relax
\lowercase{\endgroup\catcode`~\active\protected\def~}{#2}}
```

把目标码位 catcode 13 化并 `\protected\def` 为替换文本，语义与 utf8.def 一致；`\providecommand` 保证任何包真定义时以包为准。

**验证**：build-zh 副本打 shim（`normalize_engine` 实注入位、文件最顶）→ `tectonic -X compile -Z continue-on-errors`：14 → 4 errors（DUC 10 全清，仅剩缺陷 B 的 4 个 xcolor），`main.pdf` 887.66 KiB 产出。61 个 missing-char 警告不变——全部位于 `_minted/*.pygtex` 逐字文件（lmmono 无希腊字形，verbatim 内 catcode 冻结 shim 够不到），与 shim 无关的预存问题。

## 缺陷 B：`\textcolor{blue}` 色名漏译 → `Undefined color '这是译文'`

**机制链**：`TRANSPARENT_NAMES`（tables.py:266-267）含 `textcolor`/`colorbox`，dispatch 第 13 步先于第 19 步 argspec 兜底命中 → `{color}` 被当散文内联进 chunk content → mock 翻成 `这是译文` → xcolor `Undefined color`。argspec.json 里两命令本有 chunk-arg 条目（textcolor=pkg xcolor `[skip,key,text]`，colorbox=latex2e 恒激活）——**表遮蔽 bug**：TRANSPARENT 查表在 argspec 之前， curated 条目永远够不到。

**为何不是「从 TRANSPARENT 删掉就行」**（实测两路皆回归）：(a) 顶层 argspec chunk-arg 形把命令前后 <CHUNK_MIN=20 的散文碎片（"The"/"from"/"and"/"here."）切为独立 mini-run 全部落 literal 丢译文；(b) caption 内 `in_arg` 分支把 key 参留**字面**——`{blue}` 照样漏进 caption chunk。故需专用 handler（href 同构）。

**修复**（patch handoff，`segmenter.py.patch` + `tables.py.patch`，**须同批落地**——tables 单独摘除会退回上述回归）：

- tables.py：`TRANSPARENT_NAMES` 摘除 `textcolor`/`colorbox`，新增 `COLOR_TEXT_NAMES`；
- segmenter.py：dispatch 9b（href 后）+ grp-walk 对价分支 + `_handle_color_text`——cs 与间隙字面进 run，`[model]?{color}` 整段出 `[[KEY_n]]`，`{text}` 不消费留主流续扫。产出形 `\textcolor[[KEY_n]]{output}`。

**验证**（`PYTHONPATH=/tmp/texlate-shadow`，shadow = 现树 + 补丁）：

- mini.tex（顶层）/mini2.tex（caption 内）/mini3.tex（宏展开 `\hlout` + `[rgb]` opt 形）全绿：单 chunk 不碎、`{blue}`→`[[KEY]]`、identity round-trip TRUE ×3；
- 原论文 `src/main.tex`：672 → 672 chunks、ph 3194 → 3196（恰 +2 KEY：`{blue}`/`{red}`）、仅 chunk 383 语义变化（caption 内两处 textcolor），其余 204 chunk 差异纯下游 ph 重编号；
- `pytest -k "segmenter or expand or latex or parse or recon or placeholder or argspec"`：536 passed。

## L2 / fixloop 观察（非本任务修复面）

- L2 把 preamble 错误 `main.tex:88` 归到 chunk "15:0" → 白烧一次重译 + `fallback_unverified`。与在飞任务 #78（file:line→chunk 归因洞）同族。
- fixloop 无 `DeclareUnicodeCharacter` 的 undefined_cs 规则、无 `Undefined color` 规则 → dirty_pdf 收场。shim 落地后缺陷 A 类从源头消失，规则可不补；xcolor 规则可作为兜底。

## 复现

见 `repro.sh`。mock 臂（`settings.json` `"model": "mock"`，产出 `这是译文`）已够触发——两缺陷暴露均结构性，与真实 LLM 无关；真实臂下色名会被译为中文词（如同 `这是译文`）同样触发 xcolor undefined color。

## 文件

- `normalize.py.patch` — 缺陷 A（已应用于工作树，未提交）
- `tables.py.patch` + `segmenter.py.patch` — 缺陷 B（patch handoff，须同批 `git apply`）
- `compile-log-excerpts.txt` — 基线 14 错 + shim 后 4 错的日志摘录
- `repro.sh` — 复现/验证命令
- 验证现场：`/tmp/duc-norm-test/`（打 shim 的 build-zh 副本 + `_tect_out/main.pdf`）、`/tmp/duc-repro/`（mini{,2,3}.tex + verify_shadow.py + verify_diff.py + dump_{base,shadow}.json）、`/tmp/texlate-shadow/`（影子包）
