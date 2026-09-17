# sid8 wave-3 交付 (2026-09-17): F-stub 救援物缺陷 ×2 + F-font 路由复核 + llm_hook 转单

范围: fbucket-scout 型三 F-stub 4 格 + 型二 F-font 2 格; 顺手收 1e 转单 llm_hook RecursionError。

## aa.cls shim `\abstract` 吞噬结构 cs (3 格)

**机理**: shim 的 `\renewcommand{\abstract}[5]` 按新 aanda 五段式写, 但 0307062/0501187/0501259 三格全是旧 aa.dem 单参形 `\abstract{...内含 \keywords 段...}`。`[5]` 继续扫参, 把紧随的 `\par`/`\maketitle`/`\section` 吞成 arg2-5 —— `\section` 落进 quotation 组内执行时 `\@sect` 的 `\@@par` 被 expl3 hook 名 csname 扫描 (`env/\@@par/end`) → `Missing \endcsname` ×100 风暴 (实证复现, errorcontextlines 全栈确认)。

**修** (rules.yaml shim_map aa.cls): `[5]`→`[1]` + `\aa@absorb` —— `\peek_catcode_ignore_spaces:NTF \c_group_begin_token` 前瞻, 续组逐段并入 quotation, 非组 token 原样回主流。两式通吃。

**实证**: `$CLAUDE_JOB_DIR/tmp/aa-repro/` — 最小 doc 单参形 100 err→0; 五段形 0 err 且五段全入 PDF; **真档 H4470.tex + shim 0 个 endcsname** (原 100), 残错仅缺 .ps 图件 (eps_to_pdf 通路管, 非本票)。

## graphicx.tex 毒件 (1 格)

**机理**: nucl-ex/0408018 (revtex4) `\input{graphicx}` → missing_file graphicx.tex → install 装上 TL `tex/plain/graphics/graphicx.tex` (Carlisle miniltx plain 包装) → xelatex LaTeX 语境 `\zap@space` 无限递归爆 input stack → 61 错 1 页 stub。

**修**: `filemap.overrides` 钉 `"graphicx.tex": null` (install 两臂短路 —— TlpdbIndex.query 显式 null→[], `_wire_filemap_overrides` 遮蔽 xelatex 通路) → 落 legacy_pkg_shim → 新 stub `\RequirePackage{graphicx}` 桥真包 (epsf.tex 同式先例)。

**实证**: revtex4 + `\input{graphicx}` + `\includegraphics` doc 配 stub → xelatex rc=0 无错, graphicx.sty 真包载入。

## F-font 路由复核 (2 格, 结论: 路由已正确, 本体他车道)

fixloop 记录面: 两格 final_cat=warn_utf8/warn_missing_char —— 缺字警告本就进了 warn 类分诊; `installed:[kotex.sty]` 是 missing_file 规则对文档真 `\usepackage{kotex}` 的正解, 非缺字误路由。缺字族动作面 (`_MC_TABLE`) 全表无 install 动作: CJK+spec 字体 → cjk_warmup; 非 CJK → replace 字面替换。已钉 test_fixloop_wave3_shim.py 三测 (spec 字体 hit / tfm·CJK 字体名 gate / 无 install 动作)。cjk=0 本体 = xeCJK interchartoks 未接管 (chars 绑 lmroman), 属 fixer-font-fallback-8bit 车道, 与 scout 判读一致。

## llm_hook RecursionError 转单 (1e wave3-info 发现)

`_extract_json` 两处 `json.loads` (llm_hook.py:234,240) `except json.JSONDecodeError` 漏 RecursionError —— `[`×50000 超深嵌套撞解释器上限逃逸。已并入坏 JSON 通路 (两处 except 加 RecursionError, 语义不变 = 抽取失败返 None), xlat/client.py:191 同范式。实测 `[`×50000 与 `{`×2000 均返 None。

## 测试

`tests/test_fixloop_wave3_shim.py` 7 测: abstract arity+absorb pin ×2 / graphicx.tex override+shim ×3 / CJK 路由 ×3。fixloop 相关面 147 测全绿 (含 shim_map 全表 every-entry 扫自动盖新条)。
