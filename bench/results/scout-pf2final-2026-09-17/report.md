# scout-pf2final — realpostfix2 高覆盖归因（n=100 已收官）

> 2026-09-17。只读归因，数据源 = records.jsonl 原始行（末行胜去重），非 results.json 浅合并。Run 已完结（summary/matrix 生成，无在飞格）。

## 完成度 + 分布

- pipe-xel：clean 76 / partial 10 / fail 14 → on-rail **86.0%**
- pipe-fix（24 格全非 clean 触发）：clean 9 / partial 10 / fail 5
- **union pdf（px∪fix 纯管线口径，bytes 实计）= 95/100 = 95.0%**；union clean = 85；终态无 pdf 4 格（astro-ph×3 + cond-mat/9703161）
- splice leftover_ph=0 全样本 ✓；chunk 终态 ok 10706 / partial 5 / fault 5 / skipped 1——全部 fallback 保原文，无注入伤
- 早读 64 格 ~90.6% → 终值 86.0%：尾部 36 格（pos 65–100）集中 1997–2003 旧式 id 段，on-rail 仅 77.8%，fail 增量全在旧式段
- **口径勘误**：ledger 所记 union 96%/clean 87/fail 4 把 hep-ph/9910403 的 **base 臂** pdf 计入 union；px∪fix 纯管线口径 = **95/85/5**

## fail 格逐格归因（14 格）

| 格 | 签名 | 归因 | fix 结果 |
|---|---|---|---|
| 0707.4465 | elsart.cls 缺 | 源稿专有 sty | shim→clean |
| 0905.4439 | aa.cls 缺 | 源稿专有 cls | shim→partial（natbib biblio 残） |
| 1306.2177 | aipcheck.tex+aipproc.cls 双缺 | 源稿 | shim×2→clean |
| 1306.5813 | iopart12.clo 缺 | 源稿 | shim→clean |
| 1511.06879 | `\Ref` already_def→调用内存爆（5000001 words） | 源稿宏撞 revtex4 | newcmd_renew→clean |
| 2105.03750 | aastex63.cls 缺 | 源稿 | shim→partial（91 err） |
| 2308.12712 | hyperxmp 先于 hyperref + nicematrix | 源稿 pkg_order | relocate+install→partial |
| hep-lat/0111009 | espcrc2.sty 缺 | 源稿 | shim→clean |
| hep-ph/0111218 | espcrc2.sty 缺 | 源稿 | shim→clean |
| astro-ph/9703134 | aaspp4.sty 缺 | 源稿 209+专有 sty | **shim 表无此条目**→fail |
| astro-ph/9703152 | amssym.sty(1.x 旧名)+flushrt.sty 缺 | 源稿 209 | shim 缺→fail |
| astro-ph/9703198 | crckapb.cls+psfig.sty 缺 | 源稿 209 | shim 缺→fail |
| cond-mat/9703161 | eqsecnum.sty 缺 | 源稿 209 | shim 缺→fail |
| hep-ph/9910403 | `\@iiiparbox` runaway | **管线引入（新签名）** | cat=other 无规则→fail |

## hep-ph/9910403 —— 新浮出的管线硬伤

base-xel **clean**，px/fix 均 fail → 明确管线引入。ledger 所记 expl3_backend 是**前次 run 签名**；本次新 log expl3 加载正常（plb-rev.log:25），死因不同：splice 在 `\abstract{en}`（用户 `\renewcommand` 自定义 macro）后回放 macro 体片段 `\vspace{2ex} \parbox{\absize}{<zh>\setlength{\baselineskip}{2.5ex}`——#1 换 zh 但在 `\par` 处截断，丢 `\par}`+`\end{center}}` → parbox 参不闭合 → "File ended while scanning use of \@iiiparbox" → no_pdf（plb-rev.tex:247）。fixloop 归 'other' 无规则。**归因：splice/segmenter 的 macro-body 回放截断在 `\par` 边界**——归 1d（latex/）。

## partial 格归因（10 格）

- missing_chars 字体病（源稿，均有 pdf）：1003.1464（ø/cmmi8）、2403.15096（§/cmr10）、math/0605301（£/cmr10）——**missing_char_fix 不覆盖 Latin-1 散字**仅 static_precheck 空转；1511.02820（ĳ/txmi）→font_fallback→acceptable
- missing_char_fix 救回：0806.1079（≠×3）、1608.02516（−）→ clean
- 1206.5921 figure1.pdf 缺 → graphic_repair fbox stub→clean
- 1404.5720 feedforward.eps 缺+9 err，**rc=141=SIGPIPE 且 killed_signal=None 未解码**（watch：rc>128 逃逸 killed 语义）→ best_effort
- cond-mat/0501128 `\twocolumn` undefined_cs——**pipeline-cured**：upgrade209 revtex→revtex4-2 出 pdf（base 撞 revtex.cls 缺 fail）
- 0905.4907 **管线引入**：zh 裸 `\alpha` 出 math（caption 内），syntax 无规则→acceptable（pdf 在）

## fix 臂战果 + 缺招清单

命中：legacy_pkg_shim×8、missing_char_fix×2、font_fallback×1、graphic_repair×1、already_def_newcmd_renew×1、pkg_order_hyperxmp_relocate×1、_best_effort_pass×8、static_precheck×24。救回 px-fail→clean 6、→partial 3；px-partial→clean 3；净增 pdf +9。
缺招：① shim 表白名单缺口（aaspp4/amssym→amssymb 别名/flushrt/psfig/apjprepr/crckapb/eqsecnum——amssym→amssymb 零成本）；② syntax/other/undefined_cs 无修复路径；③ missing_char_fix Latin-1 盲区（ø§£ĳ）。

## 跨臂翻转（vs postfix-2026-09-16）

- **partial→clean 21 格痊愈**；**clean→fail 1**：1511.06879（同 `\Ref` 撞，源稿病+运气差，fix 已兜——watch 非真退化）；**partial→fail 4**：astro-ph×3+cond-mat/9703161——**语义翻转非退化**（旧 run latex209 桶记 partial 但 pdf=None，新 run upgrade209 真编译撞缺 sty，物理产出相同）。
- bytes 实计 pdf：px 83→86（+3），union 93→95（+2）；管线引入名单 13→2。
- hep-ph/9703228（bug-E 规则候选挂载格）：upgrade209→article verdict clean（pdf 389KB），bug-E 未复发——peer1「不立规则归 llm_hook」裁定维持有效。

## 路由结论

- 管线引入 2 格：0905.4907（partial，已知 bug-E→L0#11 已落）+ hep-ph/9910403（fail，splice macro-body 回放截断→**1d**）。
- 终态无 pdf 4 格全为 1997 专有 sty/cls 缺席——源稿病理+shim 覆盖缺口→**项目体验方式**（rules.yaml shim 表）。
- watch：1404.5720 rc=141 SIGPIPE 逃逸 killed 解码（judge 信号归因，项目体验方式在裁）；missing_char_fix Latin-1 盲区→项目体验方式。
