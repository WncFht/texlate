# repro-2203.00092 归因终稿（patch 已落工作树）

patch 是终稿。`segmenter-sideeffect-literal.patch`（diff -u，5 hunk ~110 行）已由 leader apply 进工作树 segmenter.py（hunk 全落，offsets only）。

## 根因一句话

非原生失败，纯 zh 侧 segmenter 缺陷：gullet 将 `lib/characters.tex` 里用户宏 `\makecommand{sf}{\mathsf}{{CE,Ch,…}}` 展开成 `\foreach \i in {list} {\xdef…}` token 流，**展开组骨架被当作可译 para chunk 的 content**——`\xdef` 体已被 gullet 执行成 `consumed` marker（`xdef:sf\i`）只剩 `{}`，zh splice 用译文换掉 list、空壳骨架回写源文件。两轮 bench 用的是修复前代码，`_tok_surface` 逐 token 拼接缺 cs→letter 空格守卫，`\i`+`in` 粘成 `\iin` → pgffor `\pgffor@var@add` 扫 `in` 关键字 runaway → EOF 报 `preprint.cls:163`。

## 机制链（逐环实证）

1. **expand**：token 流 = `cs(foreach) cs(i) letter(i) letter(n) space lbrace letter(C) letter(E) other(,) …`（probe.py 实测 dump）。
2. **segmenter（旧）**：`\i`+letter `i`+`n` 无守卫拼接 → `\iin`。对拍：同 token 列上 `gullet._surface` 产 `\foreach\i in {CE,`，naive join 产 `\foreach\iin {CE,`。chunk.content = ` \foreach\iin {GL,SL,…} {} `，placeholders 为空（骨架无任何保护）。
3. **translate**：mock/真 LLM 都只被告知"保 CS/占位符"——骨架逐字保留、list 散文翻掉 → `\foreach\iin {这是译文} {}`。
4. **splice**：reconstruct 优先级 trans→ph_map→content，译文命中 trans 分支，content 骨架盖掉 `\makecommand` 源行。
5. **TeX**：`\foreach\iin` retokenize 成 `\foreach`+`\iin`（无 `in` 关键字）→ 行中 blob 撞空行报 `Paragraph ended before \pgffor@var@add was complete`（L2 记录 characters.tex:30/:32 即此），末行 blob 撞 EOF 报 `File ended while scanning use of \pgffor@var@add`。**runaway 错报在父文件 `\input` 续行位**（preprint.cls:163 = `\input{lib/commands.tex}`，characters.tex 是 162 行 input 的）→ L2 file:line 归因只回退行中两颗、漏掉末行 → 仍挂 → fixloop `unfixable:other`。

## en/zh 归属 + 原生判定

- base-xel 出 PDF（partial：missing_chars×2，另有 `\pdfoutput` 良性 undefined）→ **非原生失败**。
- base-tec 挂属独立根因：hyperref `\HyPL@SetPageLabels` undefined at `\end{document}`（xdv 已写 100pp）——tectonic 侧问题，与 pgffor 无关，不在本修复面。
- en 侧零风险：identity 经 `ph_map[[[CHUNK_n]]]→ident` 逐字节还原（`reconstruct(res)==src` 实测 True）；仅 zh 译文面吃 content 骨架。

## `_cat_surf`（0806 修复）必要但不充分

当前工作树 segmenter.py 已有 `_cat_surf`（cs→letter 空格守卫），重验 content 已变 `\foreach\i in {GL,…} {}`。**但实测不够**：`in` 关键字本身是散文 run，MockTranslator 把它翻成 `这是译文` → `\foreach\i 这是译文 {这是译文} {}` → 同款 runaway（`zh_mockzh/` 现场复现：`Paragraph ended`×3 @ characters.tex:15/22/24 + `File ended`@preprint.cls:163，NO PDF，签名与线上完全一致）。且 `\xdef` 体 parse 时已消费——即使 `in` 幸存，`\foreach \i in {…} {}` 也是空循环，`\sfLie`（×17）、`\sfMap`（×7）、`\sfGL`（×5）等 15+ 宏定义全丢 → undefined_cs 换个签名接着挂。真 LLM 同样可能挪动 `in`。

## 修复：F2 副作用守卫（已 apply）

思路：展开组内若出现**非控制流 consumed marker**（def 族/let/catcode/newif/ifundefined…——展开时已改宏表，surface 无法再生其副作用），整组回 literal。这是把顶层 `_on_consumed` 既存不变量（"def 串不落 chunk，否则译文会删 def"）补进组内——组内 consumed 目前被 `_note_input` 静默吞掉不进 `_open_toks`，顶层规则管不到。

patch 内容：`__init__`/`_open_group` 加 `_open_side_effect` 标志；主循环组内 consumed 分支放行 `("input:", "input_tag:", "endinput", "if:", "fi:")` 白名单、其余置标；`_close_group` 置标则 `_flush_run(vspan.start)` + `_emit(vspan)` literal 收尾。

## 验证口径

- patch 后 characters.tex **0 chunks**、`\makecommand` 行逐字保留、identity 不变；
- 源码版 characters.tex 回灌 pipe-xel zh 树（`zh_fixed/`）→ xelatex 一遍过 **0 错误 54pp PDF**；
- 主文件 arXiv_v3.tex 374 chunks 数前后不变（无副作用组过主链，回归面干净）；
- `tests/` latex 相关 patch 前后全绿（PYTHONPATH shadow 实测 222 例）；leader 侧 apply 后 `pytest -k "segmenter or expand or latex or parse"` 413 passed，唯一红是 repro-0806 在飞 #77 的 red-by-design 新用例（`test_math_text_arg_inner_dollar_no_split`），非本 patch 回归。

## zh_fixed / zh_mockzh 口径

- `zh_fixed/` = pipe-xel zh 树 + **源码版** characters.tex（即 F2 产出的等价物）→ 编译全绿，证明 blob 是唯一致命阻塞。
- `zh_mockzh/` = 同树 + **当前代码（含 `_cat_surf`）+ 真 MockTranslator** 产出的 characters.zh.tex → 仍挂，证明胶水修复单独不收敛本篇。
- `characters.zh.tex` = mock 译文产物原文（`\foreach\i 这是译文` 实证）。

## 现场清单（`bench/results/repro-2203-2026-09-16/`）

`probe.py`+`probe.log`（chunk dump + 展开流 A/B）、`segmenter-sideeffect-literal.patch`、`characters.zh.tex`、`zh_fixed/`（含 arXiv_v3.pdf/log）、`zh_mockzh/`（失败 log）、`min_repro.tex`（精简样——注意孤立文件上下文不足以产 chunk，复现以真实文件为准）。

## 残留建议

- `\foreach` 非孤例：任何"展开执行副作用 + 表面含散文样 token"的用户宏同踩此坑；F2 覆盖整类。
- **L2 归因洞**值得另记：runaway 扫描错报父文件续行位，file:line→chunk 归因会漏 EOF 侧 blob（本篇新旧两轮都因此逃过 fallback）。
- pipe-tec 树里 fixloop 曾投放 xkeyval/pst-xkey 等 .sty 到源码树——与本 bug 无关，但说明 fixloop 装包路径会把文件落进工作树，评估口径时留意。
