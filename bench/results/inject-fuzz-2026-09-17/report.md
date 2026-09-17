# inject-fuzz — compile/inject.py 注入边界对抗测试

> 2026-09-17 收口。交付 `tests/test_fuzz_inject.py`（1019 行，commit `9b7b39b`）：**27 passed + 9 xfailed(strict, 0 xpass)**，ruff check/format 双净。确定性+离线（只用 `_STD_CLASSES`/未映射类名，无 kpsewhich 依赖；`random.Random(20260917)` 240 例碎片拼接）。

## 缺陷台账（9 族，均实证 repro）

| # | 位置 | repro 形态 | 影响 | 修法 |
|---|------|-----------|------|------|
| I1 | inject.py:620 `insert=len(tex)` | `\documentclass{article}\begin{document}x\end{document}`（全文零 `\n`） | 块落 enddoc 后→死注，中文静默缺失 | eol<0 时在 close 插入 |
| I2 | inject.py:552-580 `_docclass_close` 无界前扫 | `\documentclass\cls`（宏类名）吞 `\begin{document}` 的 `{}` | 缝落 enddoc 行→死注 | 首 token 非 `[{` 即收口回退行尾缝 |
| I3 | inject.py:615 `close<len(vis)` 守卫 | `\documentclass\n{article}`（`}` 为末字节） | 误判无花括号→裸缝劈断声明成 `\documentclass\n<BLOCK>\n{article}` | 仅 `vis[close-1]=="}"` 判收 |
| I4 | inject.py:616-622 EOL 缝 | docclass 行尾接 `\begin{verbatim}` | 块落 verbatim 环境体→死注 | 插点取 close 或检测行尾开启的逐字环境 |
| I5 | latex209.py:405 `_DOCSTYLE_RE.search` 非深度感知 | `\newcommand{\ds}{\documentstyle{junk}}` 先于真 `\documentstyle{article}` | 宏体被升级器污染（塞入 \documentclass+COMPAT_SHIM），活 ds 未转还吃 `\usepackage` | 用 find_docclass_ends 深度感知缝位传给升级器 |
| I6 | inject.py:711-712 FLOAT_SIZING dc+bd 同文件谓词 | 编排壳 main（dc 在 main、bd 在 `\input` 子文件——find_main_tex 显式收录的 cs/0408015 形态） | 工程含 figure 也拿不到溢高 float 钩子（返回 0） | dc+bd 不全文件回退文件顶/缝后 |
| I7 | inject.py:456,531 `*.tex` 闸 | `.ltx`-only 工程 | find_main_tex None + classify "garbage"（mask.py:19 TEX_SOURCE_SUFFIXES 已认 .ltx——口径漂移） | 后缀集对齐 TEX_SOURCE_SUFFIXES |
| I8 | inject.py:271 `_DOC_RE` lookahead 放行 `@` | `\makeatletter\def\documentclass@hook#1{#1}` 唯一命中 | 无 docclass 文件被报 injected（locate.py 已用 `(?![a-zA-Z@])`——inject 侧后果实例，非重复报告分歧本身） | lookahead 补 `@` |
| I9 | inject.py:461 候选闸 `\b` 无深度检查 vs 缝扫描有 | `\newcommand{\doc}{\documentclass{article}}\n\doc\n\begin{document}…` | 被选为 main 却永远 no-docline→可编译文档静默零注入 | 闸与缝同深度口径 |

I1/I2/I4 同族（注入物进死代码）；corpus_v3 11602 文件未见病态形态→latent-but-real。

## 未钉观察（characterization 断言已落或仅记录）

- `inject_float_sizing` docstring "0/1"：多 main 工程实际返回 N（双 main 实测 2）——文档漂移，行为合理。
- `mode` 无校验：bogus 走 xeCJK 块且 `info["mode"]` 回显 bogus。
- `CJK_PRESENT_RE` 漏检：`\usepackage{\n ctex}`（`[^\n]` 段跨不过花括号内换行，TeX 合法）与 `\input ctex.sty`——后果良性双注（LaTeX 幂等）。
- `[..]` 不计深度：`\usepackage[\documentclass{x}]{y}` 造幻影缝（哨兵兜住仍 preamble 位）。
- dc 首 ds 尾混合声明不升级、ds 缝吃 `\usepackage`（病态输入）。
- 游离 `}` 使 depth 归负→全量命中被跳→安全降级 no-docline。
- `\bgroup` 不计 depth（组内声明仍成缝）；`\end{env}` 不算 bare `\end` plain 指纹。
- threeparttable 门是裸子串：`\threeparttableish` 宏名良性过触发；注释内不触发。
- 无扩展名 `\input{body}` 只试 `body.tex`（与 probe.py `_find_local` 同口径）；`\input{../x}`/绝对/空白名不跟随。
- `_walk_inputs` docstring 写 BFS 实为 pop（DFS）；cp1252 源经 prepare 重写为 utf-8（xelatex 前置正确）。

## 环境事件

跑测途中 `src/texlate/latex/segmenter/_common.py`（untracked，peer 在写）曾瞬态 SyntaxError 致 1 用例 error——文件落盘后自愈，与交付物无关。
