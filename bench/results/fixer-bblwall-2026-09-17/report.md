# fixer-bblwall 交付报告 (#222)

**Lane**: `builtins.py` + `rules.yaml` 对应条目 + `inject.py`(A6) + `tests/test_bblwall_audit.py`（新）。Builtin 先于 yaml 条目落盘 ✓。提交：leader `48cddfa`（builtins/inject/tests 三件；rules.yaml 条目随 peer1 批八同文件 commit）。

## 逐项

**W2 bbl_regen stale-drop ✅** — builtins.py L377-446: `_BBL_VER_RE`/`_bbl_format_version` + rc≠0 后三叉——`had_bbl`（运行前快照）且 post-run 消失 → invalidate + `dropped(biber-rm)`；`bbl format version X.Y < 3.0` → unlink+invalidate+`dropped(fmt X.Y)`；否则 `failed`。`done or dropped` 非空 → True；note 分 `regen:`/`stale-dropped:`/`failed:` 三段。

**W3 physics_stub_detach ✅** — builtins.py L923-1040 区 + rules.yaml order 163。三步：usepackage 名单摘 physics 原位 `\input{physics.sty}` 续载（`\input` 不进 ver@ 注册）+ stub `\ProvidesPackage{physics}`→`{physics-stub}` 中和 + `\txlatephysstub` 双载守卫。命中位走 `mask_tex`（注释假装载点不动）；元素级 `=="physics"` 滤 `physics-tools`；已有 `\input` 不重复补；真 CTAN physics(`\DeclareDocumentCommand` 形，`params.real_marker` 可覆）弃权归 LLM。`when: any:[undefined_cs, other]`;condition `cache_dir_glob: physics.sty` + `source_contains` 名单正则。

**A3 glyphtounicode_shadow ✅** — rules.yaml order 46，先于 guard(50)/polyfill(51) 截同格 payload。`bundled_class_shadow` 复用：`cs_set=[pdfglyphtounicode, pdfgentounicode]`、`target=glyphtounicode.tex`、body=`\def\pdfglyphtounicode#1#2{}`+`\newcount\pdfgentounicode`(count 赋值形）+`\endinput`；condition `source_contains: "glyphtounicode"`。

**A5 undefine_for_redef ✅** — builtins.py L1043-1100 区。`_ALLOC_CS_RE`（裸 cs 形：newbox/count/dimen/skip/muskip/toks/read/write/if/insert/marks/font/language + chardef/mathchardef/*def primitives) + `_ALLOC_BRACE_RE`(newlength/newsavebox 直给名、newcounter→`c@`、newboolean→`if`+`Xtrue`/`Xfalse`) + `\newif` 伴生。命中分配集（mask 视图）→ abstain；否则 `_inject_after_docclass` 落 `\let\X\@undefined`（吃 A1 eol+1 缝）。`already_def_undefine` order 113 转 builtin_transform。

**A6 TEXT_8BIT_FALLBACK ✅（deviation)** — inject.py L192-263 + `inject_cjk` block 尾。`\ifdefined\XeTeXversion`+`\IfFileExists{cmunrm.otf}` 双门 → NFSS `texlatecmu`(cmunrm/bx/ti/bi+ssub) → `\newXeTeXintercharclass` → 20 段码位（西里尔/希腊/拉丁扩展/组合符/IPA/FB00 连字）→ interchartoks 类 0..31 双向+边界 255(+4095 门控）→ tokenstate=1。**deviation**: 弃用 ucharclasses——它给全部 block 含 CJKUnified 派 class，后载砸 xeCJK 类分配；手搓等效物不碰 CJK 码位。

**A4 记档未修** — `LoopCtx.read` utf-8/errors=replace 无探测、write 恒 utf-8；latin-1 往返 U+FFFD 坐实，建议单独条目（per-file 编码探测+回写，面大留裁决）。

**A1/A2** — 已在树（misschar 交付 `827674d`），零触碰。

## 验证

- `pytest tests/test_bblwall_audit.py` — **29 passed**
- `pytest tests/ -k "fixloop or misschar or bbl or physics"` — **416 passed**（忽略 `test_fuzz_normalize.py`：并发代理未跟踪文件 collection 即 `UnicodeEncodeError`，非本 wave)
- `ruff check` builtins.py / inject.py / 新测试文件 全绿；`Ruleset.load()` 三条目解析无悬空 function

## 碰撞处理

- `test_fixloop_yamlish.py` 规则计数断言 65→**67**（本 wave +2）已更新（随 rules.yaml commit 走 peer1 批八批）
- `test_fixloop_f1f2.py` elsart* 4 红系并发代理把 elsart1p/3p/5p/elsevier.cls 迁 `body: *elsart_body`（yaml 注释自述实证）而断言仍要 `loads`——拆 parametrize + 新 `test_shim_map_elsart_siblings_body_form` 断言 body 含 `\LoadClassWithOptions{elsarticle}`（**批八耦合件**，随批八 commit）
- **自查失误已录**: 比对 HEAD 时误跑 `git stash -- rules.yaml`（违反零 git 状态命令铁律），已 `stash pop` 恢复并经 diff 复核（并发改动 + 本 wave 三 hunk 完好）

（交付原文由 leader 代落盘——subagent report.md 写盘被协议拦。）
