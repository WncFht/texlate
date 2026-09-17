# apj.bbx↔biblatex 错配族侦察报告

数据源 bench/results/stagerun-loop1-2026-09-16/records/{compile,fixloop}.jsonl（末条胜）+ work/<id>/splice/*.log 现场。侦察日期 2026-09-17。

## 结论

字面的 apj.bbx 格只有 1 个（1706.00240），其 Cannot patch bibliography macro author 已被 fixer-apjbbx 今日落的 biblatex_bbx_rename（rules.yaml:3726，stats fires:1 verified）覆盖。真正未接的尾巴是同族兄弟：e-print 自带整套/半套旧 biblatex（v3.12）撞系统 v3.21/新 kernel 的 2 格（1907.00257、2003.10727），vendored_sty_shadow 有签名有动作但永远不触发——_DATE_RE 只认 \ProvidesPackage{...}[YYYY/MM/DD] 字面日期，biblatex.sty 的日期面是 [\abx@date ...] 宏间址。另有 11 格 ADS 时代 cite key 裸 &/_ 在 .bbl 炸 Missing $/Misplaced alignment tab 的族缘子型。

## 受影响格清单

### 族内：vendored/shipped biblatex 栈错配（3 格）

1706.00240 | 终态 fail（多因） | splice/apj.bbx:194: Package biblatex Error: Cannot patch bibliography macro author | 自带 apj.bbx 2017/07/23 + apj.cbx + apjbib.sty，由系统 biblatex 3.21 装载成功（log L1437），但 \bbx@patchmacro{author} 找 \usebibmacro{date+extrayear} — biblatex>=3.8 改名 date+extradate -> patch 失配。多数 run 被 fontspec/early_eof 抢签遮蔽。

1907.00257 | 终态 partial（best_effort_pdf，113->57 errors） | standard.bbx:10: Undefined control sequence \DeclareBiblatexOption | 自带 biblatex.sty v3.12 + biblatex.def/blx-*.def（无 bbx）-> .sty 遮蔽系统 v3.21，numeric.bbx->standard.bbx 却从系统 texmf 取 v3.21 -> 新 API \DeclareBiblatexOption 在旧 sty 下未定义，113 错级联。

2003.10727 | 终态 partial->clean（best_effort_pdf） | main_MMH.tex:141: Package biblatex Error: Patching \MakeUppercase failed / \MakeLowercase failed | 自带完整 v3.12 栈（biblatex.sty+standard.bbx+alphabetic.bbx/.cbx+english.lbx+*.def）内部一致，但 \AtBeginDocument patch MakeUppercase/Lowercase 在新 kernel 失效。非 fatal，PDF 出。

### 族缘：ADS/apj.bst 时代 .bbl cite-key 字符（11 格）

shipped .bbl 的 \bibitem{...} key 含裸 &（A&A/A&AS bibcode）或 _（Allen_90/Faucher_Gigu_re/SUZAKU_XIS/GW170104_main 形），现代 kernel+natbib 标签机制执行该 token -> Missing $ inserted / Misplaced alignment tab character &。均 partial（acceptable_pdf，错误残留）。

1003.1717   ms.bbl:4 Missing $                          key Allen_90
1206.5852   paper.bbl:111 Misplaced &                   key 2005A&A...429..161T
1306.0013   precursors_final.bbl:17 Misplaced &         key 2012A&A...539A...3B
1306.0179   ms.bbl:5 Misplaced &                        key 2001A&A...370..680A
1306.2317   hoIX_suzaku_feK_astroph.bbl:69 Missing $    key SUZAKU_XIS
1404.0089   syncop-2014.bbl:173 Missing $               _ 在 \doi 值 10.1007/978-1-84800-155-8_7（非 key，亚型略异）
1511.02843  ksz.bbl:28 Misplaced &                      key 1996A&A...313..697B
1706.00024  grb170105.bbl:520 Missing $                 key GW170104_main
1803.00181  M31N2008...bbl:16 Misplaced &               key 1996A&AS..117..393B
1907.03795  bulk_visc.bbl:161 Misplaced &               key 1992A&A...262..131H
2009.11106  GCPviaPSRBHv3.bbl:66 Missing $              key Faucher_Gigu_re_2011

### 阴性对照（不是本族）

- \bibliographystyle{apj}/apj 系 bst 共 94 格：无一格因 \bibliographystyle 本身死——失败全在更上游的 aastex*.cls/apjfonts.sty/emulateapj.sty missing_file（另族，fixer-aastex-stub 在线）。bbl 齐船时 BibTeX 流正常出 partial/clean。
- natbib Bibliography not compatible with author-year citations（0707.1255、astro-ph/0605355、math/0408377 等 ~18 格）：inline numeric thebibliography x natbib author-year 默认，可恢复，终态多 clean/partial——generic natbib 模式错配，不挂 apj 名。
- ACM-Reference-Format.bbx（12 格）、acmauthoryear/acmnumeric.bbx（12 格）、nature.bbx（1 格）shippers：全 clean/partial，未见 Cannot patch 发——biblatex_bbx_rename 若发同型可接住。
- 无格因缺 apj.bbx/*.bbx missing_file 失败（texmf 无 apj.bbx 且无人 style=apj）。

## 机理分类

S1 自带 bbx 补丁撞 biblatex>=3.8 改名宏：1706.00240。Cannot patch bibliography macro <name> 走 PackageError 非 '!' 行——cannot_patch_macro head 签（rules.yaml:411）+ biblatex_bbx_rename 动作（rules.yaml:3726）已覆盖。

S2 自带 biblatex 半栈遮蔽：1907.00257。vendored sty+def 旧、bbx 缺席 -> 系统新 bbx 调新 API 在旧 sty 下 undefined。签名 undefined_cs payload DeclareBiblatexOption。

S3 自带 biblatex 全栈 x 新 kernel：2003.10727。内部一致但 patching \MakeUppercase/\MakeLowercase failed（非 fatal）。同一修法：cohort 隔离让系统 v3.21 全栈接管；shipped .bbl 旧格式由 bbl_regen（rules.yaml:3619，.bcf 在场条件已满足——main_MMH.bcf/graph-transport.bcf 均在 splice）接手。

S4 旧 bbl cite-key 裸 &/_：11 格。老 apj.bst/ADS 导出 key 合法字符，现代 \bibitem/\newlabel 机制不容。

## 修法建议

1. S1 已闭环（fixer-apjbbx）：无需动作。
2. S2/S3 — 修 vendored_sty_shadow 两处缺口（builtins.py:244-331）：
   a. _provides_date 加宏间址 fallback：_DATE_RE 无中且 bracket 形如 [\<cs> ...] 时回读同文件 \def\<cs>{YYYY/MM/DD}（biblatex.sty 即 \def\abx@date{2018/11/02}，vendored 与系统两侧同法可取，比较仍成立）。
   b. cohort 整组隔离：vendored_shadow_isolate 现 exts [.sty,.cls]——只隔 biblatex.sty 会留 vendored *.def（1907.00257）/*.bbx/.cbx/.lbx（2003.10727）继续遮蔽，制造新混合栈。建议 params 加 cohort_map（如 biblatex.sty -> [biblatex.def, biblatex.cfg, blx-*.def, *.bbx, *.cbx, *.lbx, *.dbx]）：命中包的 sty 确证更旧时，同包全部 vendored 伴船一并 .fixloop-iso。隔离后 .bcf 在场走 bbl_regen 重建 bbl，链已通。
   c. 附带观察：probe_file（engine.py:1224）裸 kpsewhich，若 fixloop 进程 cwd 恰在 workdir 内会命中 ./biblatex.sty 自身被 rp==f 跳过——当前实现依赖 cwd 不在 workdir，属隐式前提，值得在注释写明或 probe 时显式排除 cwd。
3. S4 — 新 builtin citekey_sanitize（rules.yaml 新条目骨架）：when { category: syntax } + ctx_suggests 匹配 "\.bbl:\d+: (Missing \$ inserted|Misplaced alignment tab)"；action builtin：扫 .bbl \bibitem[<opt>]{key} 与全部 .tex \cite-族 {key} 参数，key 内 &->A、_->- 双侧一致重写；.aux 残留 \bibcite 同处理或删 aux 重跑。1404.0089 的 \doi 值 _ 不在 key 面——同规则可加 \_->_ 文本侧补丁或归邻族。
4. 不建议 shim apj.bbx stub：真 apj.bbx shipper 仅 1 格且已修；无缺失型需求面。

## 未竟

1706.00240 的终态 fail 是多因叠加（fontspec Noto Mono、draft.sty acro 弃键、torus.tex undefined_cs、early_eof）——apj.bbx 修复后能否出 PDF 取决于邻族（fontspec/acro）战果，非本族责任面。
