# B3 compilebench 扩展基线 — corpus_v2 baseline × 双引擎

- 日期: 2026-09-15 10:00
- 语料: `bench/corpus_v2/` extracted/ 分层样本 n=40 (sample.json, seed=20260915)
- 条件: baseline 原文直编, 不注入不修复; 超时 240s
- xelatex: `XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026)` — nonstopmode ≤2 pass, 冷 TEXMF 沙箱
- tectonic: `Tectonic 0.17.0` — --untrusted -Z continue-on-errors
- clean = pdf ∧ err≤3 ∧ 首错非missing_*/undefined_cs ∧ warn扫描零命中

## 1. 总成功率

| 引擎 | n | clean | pdf~ | FAIL | clean率 | pdf率 |
|---|---|---|---|---|---|---|
| xelatex | 40 | 4 | 2 | 34 | 10% | 15% |
| tectonic | 40 | 8 | 16 | 16 | 20% | 60% |

联合覆盖: 任一引擎出 pdf 26/40; 任一引擎 clean 9/40; 双引擎皆死 14

## 2. per-引擎 × per-带 成功率矩阵 (clean / pdf~ / FAIL)

| 带 | n | xel clean | xel pdf~ | xel FAIL | tec clean | tec pdf~ | tec FAIL |
|---|---|---|---|---|---|---|---|
| a | 9 | 1 | 1 | 7 | 1 | 5 | 3 |
| b | 8 | 2 | 1 | 5 | 2 | 2 | 4 |
| c | 8 | 0 | 0 | 8 | 2 | 3 | 3 |
| d | 8 | 1 | 0 | 7 | 1 | 2 | 5 |
| e | 7 | 0 | 0 | 7 | 2 | 4 | 1 |

## 3. 路由标签 × 结果 (静态路由金标准对拍)

| 标签 | n篇 | xel clean/pdf~/FAIL | tec clean/pdf~/FAIL |
|---|---|---|---|
| reject | 5 | 0/0/5 | 0/5/0 |
| xelatex | 12 | 1/1/10 | 0/3/9 |
| non-utf8 | 3 | 0/0/3 | 0/2/1 |
| no-hyperref | 29 | 4/2/23 | 5/13/11 |

## 4. top 失败类别 (首错归因, fixloop F1-F12 命名)

### xelatex

| 类别 | F映射 | 格数 | 代表 payload |
|---|---|---|---|
| missing_file | F1/F4 missing_pkg/cls/file | 34 | psfig.sty |
| missing_tfm | F2 missing_font(TFM) | 1 | phvr8t |
| syntax | — | 1 | — |

### tectonic

| 类别 | F映射 | 格数 | 代表 payload |
|---|---|---|---|
| ps_image | 路由 eps/ps→xelatex | 9 | — |
| missing_file | F1/F4 missing_pkg/cls/file | 6 | psfig.sty |
| clean | — | 6 | — |
| undefined_cs | — | 3 | — |
| syntax | — | 3 | — |
| bib_error | — | 2 | — |
| pdftex_prim | F5 pdfTeX 原语 | 1 | pdfshellescape |
| missing_pfb | F3 physical font @xdvipdfmx | 1 | — |
| inputenc_xetex | — | 1 | — |

## 5. 逐格明细

| paper | band | tags | xel | tec |
|---|---|---|---|---|
| 0812.4521 | b | xelatex | pdf~(18/syntax) | pdf~(9/syntax) |
| 0903.0543 | b | xelatex | FAIL(2/missing_file) | FAIL(0/ps_image) |
| 0909.3990 | b | — | FAIL(2/missing_file) | FAIL(0/ps_image) |
| 0912.2867 | b | — | FAIL(2/missing_file) | clean(0/clean) |
| 0912.5174 | b | non-utf8 | FAIL(2/missing_file) | pdf~(1/inputenc_xetex) |
| 1005.0504 | b | xelatex | FAIL(2/missing_file) | FAIL(0/ps_image) |
| 1009.5340 | b | xelatex | clean(0/clean) | FAIL(0/ps_image) |
| 1011.5681 | b | — | clean(0/clean) | clean(0/clean) |
| 1206.0671 | c | non-utf8 | FAIL(2/missing_file) | pdf~(0/clean) |
| 1404.7186 | c | — | FAIL(2/missing_file) | clean(0/clean) |
| 1406.1994 | c | non-utf8 | FAIL(2/missing_file) | FAIL(0/ps_image) |
| 1503.02052 | c | xelatex | FAIL(2/missing_file) | FAIL(0/ps_image) |
| 1505.00491 | c | xelatex | FAIL(2/missing_file) | pdf~(12/syntax) |
| 1607.00497 | c | — | FAIL(2/missing_file) | clean(1/bib_error) |
| 1608.04155 | c | xelatex | FAIL(2/missing_file) | FAIL(7/missing_file) |
| 1609.01652 | c | — | FAIL(2/missing_file) | pdf~(0/clean) |
| 1801.06287 | d | — | FAIL(2/missing_file) | FAIL(74/pdftex_prim) |
| 1806.06690 | d | xelatex | FAIL(2/missing_file) | FAIL(2/undefined_cs) |
| 1902.11112 | d | xelatex | FAIL(2/missing_file) | FAIL(0/ps_image) |
| 1905.07704 | d | — | clean(0/clean) | clean(0/clean) |
| 1909.05039 | d | — | FAIL(2/missing_file) | FAIL(1/undefined_cs) |
| 1910.12800 | d | — | FAIL(2/missing_file) | pdf~(0/clean) |
| 2002.05660 | d | — | FAIL(2/missing_file) | FAIL(18/syntax) |
| 2007.02320 | d | — | FAIL(2/missing_file) | pdf~(104/undefined_cs) |
| 2104.00776 | e | — | FAIL(2/missing_file) | pdf~(0/clean) |
| 2104.02882 | e | — | FAIL(2/missing_file) | pdf~(1/bib_error) |
| 2109.12648 | e | — | FAIL(2/missing_file) | clean(0/clean) |
| 2110.10462 | e | — | FAIL(2/missing_file) | clean(0/clean) |
| 2201.04035 | e | — | FAIL(2/missing_file) | pdf~(0/clean) |
| 2301.01267 | e | — | FAIL(2/missing_file) | FAIL(0/missing_pfb) |
| 2506.07410 | e | — | FAIL(2/missing_file) | pdf~(0/clean) |
| astro-ph/0306068 | a | — | pdf~(8/missing_tfm) | FAIL(0/ps_image) |
| astro-ph/9702009 | a | reject | FAIL(2/missing_file) | pdf~(6/missing_file) |
| cond-mat/0202090 | a | xelatex | FAIL(2/missing_file) | FAIL(0/ps_image) |
| cond-mat/9601002 | a | reject | FAIL(2/missing_file) | pdf~(99/missing_file) |
| gr-qc/0012020 | a | reject | FAIL(2/missing_file) | pdf~(142/missing_file) |
| hep-ex/0406065 | a | xelatex | FAIL(2/missing_file) | FAIL(1/bib_error) |
| hep-th/0508095 | a | — | clean(0/clean) | clean(0/clean) |
| nucl-th/0104042 | a | reject,xelatex | FAIL(2/missing_file) | pdf~(139/missing_file) |
| quant-ph/9712026 | a | reject | FAIL(2/missing_file) | pdf~(71/missing_file) |

## 6. 与 compile_bench 12 篇结论的一致性

| 旧结论 (corpus39 12篇) | 本轮 (corpus_v2 40篇分层) | 判定 |
|---|---|---|
| tectonic 原文 pdf 率 75% (9/12) | 24/40 = 60% | 偏低——本样本含 5 篇 2.09 reject + 9 篇 eps/ps 硬墙(旧集各仅1篇) |
| xelatex 原始(近冷环境) pdf 率 17% (2/12) | 6/40 = 15% (严格冷 TEXMF 沙箱) | 一致——TL-basic 裸环境缺包主导失败 |
| 双引擎联合 pdf 92% (11/12) | 26/40 = 65% | 缺口≈reject+路由类失败, 属预期不可救(见§7) |
| tectonic 缺包静默降级是暗雷 | pdf~ 16 格中 warn 命中: invalid_utf8×7, file_not_found×5, missing_char×3, ufffd×3 | 坐实, File-not-found 降级真实批量出现 |
| 缺包/缺字体主导 xelatex 失败 | xelatex FAIL 34/34 全为 missing_file (首错), 次错=Emergency stop(文件名提示符) | 一致且更强——static_precheck 在冷环境是必要条件 |
| eps/pstricks→xelatex 路由 | tectonic FAIL 16 格中 ps_image×9 + missing_pfb×1=62% 硬墙 | 路由预测准确; 但发现标签漏检(§7-2) |
| \documentstyle→reject | reject 标签 5 篇: xelatex 5×FAIL, tectonic 5×pdf~(降级残页), clean=0 | 零误杀, reject 路由成立 |

## 7. 对 M2 的启示

1. **冷环境缺包是 xelatex 唯一死因**(34/34 missing_file→Emergency stop): TL2026-basic 缺 revtex4/revtex4-1/revtex.cls(13格)、IEEEtran、subfigure、emulateapj、aastex 等期刊会议类。static_precheck(kpsewhich+filemap 批量装)是 fixloop 的第一杠杆, 与 spike 结论一致。
2. **路由标签有 FN**: `.ps` 扩展名(0909.3990, astro-ph/0306068)与无扩展名 \includegraphics(1406.1994: `{imvp22}` 引用而盘上仅有 imvp22.eps)逃过 `\.eps\b` 文本检测, 实测全撞 xdvipdfmx ps 墙。建议路由检测补 `.ps` 字面量 + **包内 .eps/.ps 文件存在性回查**(不依赖源文引用形态——盘上文件即事实)。
3. **bbm 物理字体墙实证**(2301.01267): `Cannot proceed without .vf or "physical" font` — docs/08 `font_sub_shim`/换引擎规则的目标场景, 首错归 missing_pfb。
4. **tectonic 降级产出必须 warn 扫描兜底**: pdf~ 16 格仅 ~1/3 靠错误数触脏, 其余靠 file_not_found/invalid_utf8/ufffd 命中——"出pdf≠成功"在大样本复现。
5. **基线定标**: 本轮 clean 率 xelatex 10% / tectonic 20% / 联合 22.5%; pdf 率 15%/60%/65%。M2 目标 ≥90%(zh 条件)意味着 fixloop+路由+normalize 要补 ~70pp——主要缺口构成: missing_* 系(xel) + ps/bbm 路由(tec) + 2.09 reject。
6. **引擎互补再次验证**: tectonic 独救 20 篇, xelatex 独救 2 篇(1009.5340 eps 干净过, astro-ph/0306068 带错出pdf)——tectonic 优先 + xelatex 兜底的排序对。

### 口径备注

- xelatex 在冷 TEXMF 沙箱跑(TEXMFHOME/VAR/CONFIG 隔离 → TL2026-basic 裸环境), 不代表用户暖环境(~300 已装包下 12 篇基线 pdf 率 92%);选冷口径=fixloop 的真实起点。
- n_errors 双格式计数(^! + file:line), 两遍 pass 累加——同一缺包在 2 pass 各报一次会算 2, 与上轮口径一致。
- tectonic 的 xdvipdfmx 崩因经 stderr `caused by:` 二次归因: ps_image=PS图硬墙 / missing_pfb=物理字体 / 余下才是 generic dvipdf。
- 1607.00497 等 clean 格带 1 个非 missing_* 错误(missing \item@thebibliography)——按 ≤3 阈值判 clean, zh 条件更严的 CJK 检查本轮不适用。

