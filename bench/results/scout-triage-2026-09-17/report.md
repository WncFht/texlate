# Scout 缺陷族路由表（2026-09-17）

输入：illegal-unit-scout / apj-bib-scout / fbucket-scout 三份侦察报告（同目录，均已通读；fbucket 的 7 格 mock/0 格 real 经 `fcells-*.json` 复核一致）。lane 口径：1d=latex/，peer1=compile+rules+engine，1e=bench+server，e8=e2e+repair。

## 路由表

| 缺陷族 | 实测格数 | 严重度 | 建议 lane | 波次形态 |
|---|---|---|---|---|
| illegal_unit 残余 4 簇（逗号小数 dimen / 组参·可选参 dimen / `\\[dimen]` / 散文区寄存器尾参） | ~25 残（90 集中 62 已随在飞 code 转 clean） | 中——全是 mask 下游症状，PDF 多已出（acceptable_pdf） | **1d** | 修代码：`latex/tables.py` 的 `DIMEN_TAIL_KIND`/`TRANSPARENT_HEAD_SPEC` 覆盖度扩展；**明确不落 fixloop 救援规则**（保留定位信号） |
| vendored biblatex 半栈/全栈遮蔽（S2 1907.00257 / S3 2003.10727） | 2 | 中 | **peer1** | 修 builtin 代码：`builtins.py` vendored_sty_shadow 两缺口——`_DATE_RE` 宏间址 fallback（`[\abx@date …]` → 同文件 `\def\abx@date{…}`）+ cohort_map 整组隔离（biblatex.sty 命中即隔同包 .def/.bbx/.cbx/.lbx）；隔离后 bbl_regen 接手，链已通 |
| 旧 .bbl cite-key 裸 `&`/`_`（S4） | 11 | 中低——全 partial/acceptable_pdf | **peer1** | 修规则+新 builtin：`citekey_sanitize`——when syntax + ctx `\.bbl:\d+: (Missing \$|Misplaced alignment tab)`，.bbl `\bibitem{key}` 与 .tex `\cite` 族双侧一致重写 `&`→A、`_`→-，aux 残留同处理 |
| F-font：xeCJK 绑定失效全文灭字 | 2（mock） | 低（real 臂 0） | **peer1** | 修规则/动作路由：fixloop `missing_character` 命中 CJK(U+4E00–9FFF) 时应走 binding/font_fallback 而非 `install`（kotex 治中文缺字错配实证）；本体归 fixer-font-fallback-8bit 车道 |
| F-stub：fixloop 救援物自身缺陷 | 4（mock） | 低——cjk=0 是症状读数不独立出票 | **peer1** | 修代码两钩子：(a) aa.cls legacy shim 三格同炸 `\section{这是译文}`→`Missing \endcsname`，复核 shim 是否把 csname 扫描引到结构 cs；(b) 安装物 `graphicx.tex`（miniltx）`\zap@space` 在 xelatex 下无限递归爆栈，装前 sanity 或换 driver |
| F-echo：MockTranslator 西里尔/希腊源恒等回显 | 1（mock） | 低——bench 保真盲区非管线缺陷 | **1e** | 可选：`_PROSE_RUN_RX` 扩 Unicode 字母 run（`[^\W\d_]` 起锚），或 bench 文档登记已知盲区 |
| quant-ph/9703040 源生 `24ptA` 非法 dimen | 1 | 零——TeX 两臂同式自恢复 | — | 不动 |

## 横向观察（随票带走，不独立开工）

- **verdict.category 首错遮 bulk**：quant-ph/9703040 的 110 错中 108 是 missing_number（`\bffam` 旧字体宏族），illegal_unit 只是 first_error。scorecard/分桶口径建议看 n_errors 构成（归 1e 台账口径）。
- **fixloop "clean" 不查 CJK**：1706.00217 内部判 clean:russian 而 post judge 判 partial——现以 post 覆盖兜底无错乱，e2e/repair 侧无需动作，仅登记口径缝。
- **probe_file 隐式前提**（apj-bib 附带）：裸 kpsewhich 依赖 cwd 不在 workdir，值得注释写明或显式排除（随 peer1 vendored 票顺手）。
- e8（e2e+repair）本批零票面——三族修法全落 1d/peer1/1e。

## 建议波次

1. **波一（1d）**：illegal_unit 4 簇 latex 保护扩展——残量最大、机理最清晰、是在飞修复线的直接延续，预期再清 ~20+ 格。
2. **波二（peer1）**：vendored_sty_shadow 两缺口 + citekey_sanitize 规则——14 格、修法骨架报告已给全。
3. **波三（peer1 顺手 + 1e 可选）**：F-font 动作路由收窄 + F-stub 两救援物钩子 + F-echo mock 登记——格小且 real 臂零命中，优先级垫底。
