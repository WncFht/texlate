# fixer-bblwall spec — builtins.py lane (2026-09-17)

Owner files: `src/texlate/compile/fixloop/builtins.py` + `rules.yaml` 对应条目 + `tests/` 新增用例。
**硬规矩：builtin 实装先于 yaml 条目落盘**（wave 按 write-time 拾取，悬空引用曾毒 321 格）。
交付 = 实现 + 测试全绿 + report；**不 commit**（leader 统一提交并即时 signal 41）。

## W2 — bbl_regen stale-bbl drop（peer1 wall-2）

现场（builtins.py:379-406）：逐 `*.bcf` 跑 `biber <stem>`，rc==0 → done +
`ctx.invalidate(bbl)`；rc!=0 → failed 集，`if not done: return False`。
缺陷：biber rc=2 会**自删** stem.bbl（陈旧格式拒载时清场），陈旧 bbl 消失
但 builtin 返 False → loop 不记 applied，而残留旧格式 bbl（rc 非自删形）
继续毒化后续每轮 compile。

修法（peer1 规格 + 落点）：rc!=0 分支后加 stale 判定——
`bbl = bcf.with_suffix(".bbl")`：
(a) `not bbl.exists()` → biber 已自删 poison → `ctx.invalidate(bbl)` 计 progress；
(b) bbl 在但首行 `bbl format version X.Y` < 3.0 → `bbl.unlink()` +
`ctx.invalidate(bbl)` 计 progress（陈旧格式 bbl 是 poison：biblatex 硬拒，
删掉后变 "no bbl" 软缺——无文献但出 PDF，比硬错强）。
任一 progress 或 done 非空 → return True；note 区分 `regen:`/`stale-dropped:`。
回归测试：MockEngine run_tool rc=2 + 预置 format 2.8 bbl → True 且 bbl 消失；
rc=2 + bbl 已被删 → True；rc=0 正常路径不变。

## W3 — physics_stub_detach（peer1 wall-3）

症状：bundled 2012 physics.sty stub（或残缺真包）与 siunitx v3 的
`\@ifpackageloaded{physics}` 硬错误对撞。修法：检测 source `\usepackage{physics}`
且 wdir physics.sty 是 stub 形 → 从 `\usepackage` 列表剥掉 physics + stub 文件
`\ProvidesPackage` 中和 + `\input` 侧也断。具体以 peer1 规格为准
（bench/results 下 peer1 wall spec 或 41 转述）。

## ~~A1~~ — 已由 fixer-misschar 迟交付落工作树（builtins.py:927-959）

缝位已移 eol+1（`at<len 且 out[at]=="\n"` → at+1；末行无尾换行先补 `\n`）。
测试 `test_inject_after_docclass_trailing_comment` 已随 test_misschar_audit.py。
**bblwall 勿重做**；提交时与 misschar 主件并账。

## ~~A2~~ — 已由 fixer-misschar 迟交付落工作树

`params.fallback_cs`（默认 txlatefallback）+ `params.font_not`（字体名正则
跳字，builtins.py:1621-1634）+ 跨 cs `\newunicodechar` 逐字去重 + 幂等
`\ifdefined` 守卫全在（_fb_snippet_lines:1455-1477、_inject_fallback_lines:1480）。
peer1 的 cjk_font_fallback 合并可直接用 `fallback_cs: txlatecjkfb` +
`font_not` 复用 `_CJK_FONT_RE`。**bblwall 勿重做**。

## A3 — glyphtounicode stub shadow（41 recut 新伤 2105.03753）

链条：bundled lipics-v2021.cls:510 `\IfFileExists{glyphtounicode.tex}{\input glyphtounicode}`
→ texmf-dist 里文件存在故守卫开火 → 体首 `\pdfglyphtounicode` xelatex 未定义。
修法：signature `pdftex_prim`/`undefined_cs` payload=`\pdfglyphtounicode`（或
`\pdfgentounicode`）→ wdir 落 `glyphtounicode.tex` 空 stub（`\endinput`），
cwd 搜索优先遮蔽真文件。可复用 bundled_class_shadow 或等价 file-drop builtin；
若 cls 同时裸置 `\pdfgentounicode=1` 需一并 noop（`\def\pdfgentounicode{...}` 不可行——
它是 count 赋值形，用 `\newcount\pdfgentounicode` 或 `\let\pdfgentounicode\count255`）。

## A5 — `undefine_for_redef` builtin（peer1 规约级发现，2211.04482 实证）

`already_def_undefine` 是 regex_rewrite 规则（order 113）——规则层无法做寄存器护栏。
负效应实锤：aastex62.cls `\newbox\splitbox` 被 undefine → adjustbox 占名 →
类内 `\setbox\splitbox` 变 Missing number。修法：undefine 逻辑升级为 builtin
`undefine_for_redef`，内置前置扫描——payload cs 若由
`\newbox/\newcount/\newdimen/\newskip/\newtoks/\newread/\newwrite/\newif`
分配（寄存器/盒型，undefine 后名可被后载包抢占且原分配语义丢失）→ abstain；
普通 `\newcommand`/`\def` 定义维持原 `\let\X\@undefined` 路径。rules.yaml 条目
改 `kind: builtin_transform` 指过来。**builtin 先于 yaml 条目落盘**。

## A6 — lmroman 8-bit 覆盖缺口（41 转 peer1，~49 格）

症状：西里尔/希腊/重音拉丁字符在 ec-lmr/tfm 8-bit 文本字体域缺字——
font_fallback 的 `\newunicodechar` 逐字绑定只盖 in-band 带，8-bit 字体
域（ec-lmr12/aer10/futr8t/t1xr/mdbchr8t 族）整族漏。修法（41 建议）：
inject/preamble 层加 CMU Serif 全谱回退（`\newfontfamily` + ucharclasses
分块 `\setTransitionsFor...` 或 `\defaultfontfeatures` 级），一网打尽
西里尔/希腊/重音拉丁。落点 = `compile/inject.py` zh preamble 块（A1 同
文件可同批）。先读 inject.py `inject_cjk` 现有 preamble 结构再定缝位；
与 A2 params 联动——若 fallback_cs 参数化后 preamble 级默认带可引用同 cs。
**注意 file lane**：inject.py 归本批同 agent（builtins.py 同 neighborhood）。

## A4 — ctx.read/write 非 utf8 transcode 腐蚀面（fixer-misschar 发现）

`LoopCtx.read`/`write` 对 latin-1 等非 utf8 源文件往返 → U+FFFD 替换。
所有 `_inject_after_docclass` 调用方共享此面（misschar 已加空列表早退止血）。
本 wave 核实：ctx.read 是否有 encoding 探测/`errors=` 策略；若没有，记档为
单独条目（不硬修——改动面大，需 leader 裁决）。

## 测试纪律

- 每项至少 1 个新 pytest（MockEngine + make_proj 惯例，参 test_misschar_audit.py）；
- `uv run pytest tests/ -k "fixloop or misschar or bbl or physics"` 全绿；
- `uv run ruff check src/texlate/compile/fixloop/builtins.py` 全绿；
- rules.yaml 新条目 `Ruleset.load()` 验证过再写盘。

## 交付报告写到 bench/results/fixer-bblwall-2026-09-17/report.md

列：每项 状态/改动位置/测试名/deviation。SendMessage texlate-1d 交付摘要即关。
