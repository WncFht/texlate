# illegal_unit 分类账（2026-09-17, scout）

结论先行：**90/90 id 全是 mask**（真因在上游——dimen 语境里的单位词元 `pt/cm/em/ex/bp/mm` 被当可译文本段发出，mock 翻成 `这是译文`，编译期才以 `! Illegal unit of measure` 爆出来）；**0 格**是"illegal_unit 之前已有更早 `!` 错"的严格 mask，**0 格**是 fixloop 注入物炸坏 `<dimen>`；仅 1 格 borderline 真族（quant-ph/9703040，源文件 `24ptA` 单位后跟字母本就非法，但 TeX 两臂同式自恢复，无修法价值）。真族占比 **≈1%（0~1/90）**，不值得为 illegal_unit 单立 fixloop 修法——该族会随 segmenter/xlat 单位保护覆盖度扩大而清零（本轮 rerun 已实证：62/90 转 clean）。

## 集合界定

口径：compile.jsonl + fixloop.jsonl 按 `(id, arm)` 末条胜去重；errors[] 或 sig 含 `illegal_unit` 的格。

- compile 侧 **29 格**（全部 `arm=zh`）：18 partial（sig=`illegal_unit`，判定参与）+ 11 clean（errors 含 illegal_unit 但 ≤3 未破阈值，sig 空）。verdict.category 全为 illegal_unit。
- fixloop 侧 **72 格**（`arm=fix`）：71 `acceptable_pdf`（post 编译出 PDF 但残余错误首位为 illegal_unit）+ 1 `unfixable:illegal_unit`（hep-th/9901150，已随新 code 转 clean）。
- 两集合按 id 取并 = **90 unique id**。题面 "~126 格" 的 727/202 是原始记录行数（含历次重跑），去重后为本口径。
- 全部 90 id 在新 code（`561368d`/`fa73c4c-dirty`）下均有记录：**62 格转 clean**（含 3 格换了残余 cat：1706.00352 hyperref_driver、q-alg/9703033 invalid_char、1306.6242 other），**28 格末条仍 illegal_unit**——其中 3 格（2211.00113/2308.00148/2403.00028）现场 log 已被在飞 rerun 刷成 0 错，实际残量 ≈25。
- 生命周期例证（0806.2724）：旧 code compile partial/illegal_unit×17 → fixloop acceptable_pdf → `561368d` compile clean×0。78% 的格走同一条曲线，证明上游修复（`latex/tables.py` 的 `DIMEN_TAIL_KIND` 尾参保护 + `TRANSPARENT_HEAD_SPEC` 头参保护）就是这个族的修法。

## mask vs 真族分类

判据执行结果：所有残留格 log 中 illegal_unit 均为**首个 `!` 错**，且 `<to be read again>` token **100% 是 CJK 译文标记**（自动扫 28 格，非 CJK offending token = 0）；splice 现场均见 `<num>这是译文` 而 src 同位是合法 `<num><unit>`。腐蚀发生在 **xlat 段**（zh/ 层文件已带 `这是译文`，如 0806.4653 `zh/microgel3.tex:118`），非 splice 写回。fixloop 侧无注入点证伪：fixloop 跑之前同 id compile 记录已带 illegal_unit。

### 分类账（90 id → 类别 + 一句证据）

类别口径：`mask`=管线腐蚀所致；`true*`=源文件确有畸形 dimen。cluster 为腐蚀语境聚类（fixed-inflight=最新 code 下已 clean，无现场可取）。

| id | 类 | cluster | 证据 |
|---|---|---|---|
| 0806.2724 | mask | fixed-inflight | 旧记录 illegal_unit×17，561368d 后 0 错 21 页 PDF |
| 0806.3249 | mask | fixed-inflight | 同族，fa73c4c 后 clean |
| 0806.4203 | mask | B-tassign | `\raise 1,5pt`→`\raise 1,5 这是译文`（逗号小数 dimen，l.758） |
| 0806.4653 | mask | A-graphics | `\resizebox{4.5cm}`→`{4.5这是译文}`（嵌于 `\rotatebox{0}{}` 文本参内） |
| 0806.4713 | mask | A-graphics | `\resizebox{8.1cm}`→`{8.1这是译文}` |
| 0905.0060 | mask | A-graphics | `\includegraphics` 外围 resizebox 族，l.227 |
| 0905.0514 | mask | fixed-inflight | base undefined_cs×31 → fa73c4c clean |
| 0905.0575 | mask | C-newline | `\\[1,5cm]`→`\\[1,5这是译文]`（逗号小数） |
| 0905.1090 | mask | fixed-inflight | — |
| 1003.0550 | mask | fixed-inflight | — |
| 1003.0662 | mask | fixed-inflight | base reject → 39c671f 起 illegal_unit → clean |
| 1003.1529 | mask | A-graphics | `\resizebox{12cm}{17.0cm}`→双参 `{12这是译文}{17.0这是译文}`，14 处 |
| 1012.1537 | mask | fixed-inflight | — |
| 1012.1814 | mask | fixed-inflight | — |
| 1206.0181 | mask | fixed-inflight | — |
| 1206.0210 | mask | fixed-inflight | — |
| 1206.0474 | mask | fixed-inflight | — |
| 1206.0490 | mask | fixed-inflight | — |
| 1206.2048 | mask | fixed-inflight | — |
| 1206.5646 | mask | A-boxopt | `\multirow{-4}{*}[1.25cm]`→`[1.25这是译文]`（bigstrut/fixup 可选参） |
| 1306.0160 | mask | fixed-inflight | — |
| 1306.0272 | mask | fixed-inflight | — |
| 1306.0375 | mask | fixed-inflight | — |
| 1306.1931 | mask | fixed-inflight | — |
| 1306.6242 | mask | fixed-inflight | 现 clean/other（`Dimension too large` 残留，别族） |
| 1404.0034 | mask | fixed-inflight | — |
| 1404.0144 | mask | B-setlength | `\parsep0ex \itemsep.2ex plus.1ex` 内联赋值→`0ex`→`0这是译文` 等 |
| 1404.0338 | mask | fixed-inflight | — |
| 1404.2096 | mask | fixed-inflight | — |
| 1404.2334 | mask | B-setlength | `\setlength\parskip{0ex plus0.1ex minus0.1ex}`→`{0这是译文}` |
| 1404.2471 | mask | fixed-inflight | — |
| 1511.02686 | mask | B-tassign | `\hskip.5em` 类→`\hskip.这 是译文1`（bbl 文献区） |
| 1511.06628 | mask | C-newline | `\\[0cm]`→`\\[0这是译文]` |
| 1511.02818 | mask | fixed-inflight | — |
| 1608.02270 | mask | B-setlength | `\setlength\arraycolsep{2pt}`→`{2这是译文}`，34 处残留 |
| 1608.02289 | mask | A-boxopt | `\multirow{2}{*}[2.5em]`→`[2.5这是译文]` |
| 1608.06705 | mask | fixed-inflight | — |
| 1608.06760 | mask | A-boxopt | `\makebox[2cm][c]`→`[2这是译文][这是译文]` |
| 1608.06785 | mask | fixed-inflight | — |
| 1706.00130 | mask | fixed-inflight | — |
| 1706.00216 | mask | fixed-inflight | — |
| 1706.00229 | mask | fixed-inflight | — |
| 1706.00265 | mask | fixed-inflight | — |
| 1706.00352 | mask | fixed-inflight | 现 clean/hyperref_driver（别族残留） |
| 1706.02447 | mask | A-envarg | `\begin{adjustwidth*}{1cm}{0cm}`→`{1这是译文}{0这是译文}` |
| 1706.02682 | mask | fixed-inflight | — |
| 1706.02690 | mask | fixed-inflight | — |
| 1706.02723 | mask | fixed-inflight | — |
| 1706.07675 | mask | fixed-inflight | — |
| 1803.00075 | mask | fixed-inflight | — |
| 1803.00111 | mask | A-envarg | `\begin{hangparas}{.25em}{1}`→`{.25这是译文}{1}`，36 处 |
| 1803.00116 | mask | A-tikz | tikz scope/node 内 dimen（l.350 `}` 处爆，块内腐蚀） |
| 1907.00220 | mask | B-setlength | `\setlength \arraycolsep{4pt}`→`{4这是译文}` |
| 1907.03635 | mask | fixed-inflight | — |
| 1907.03899 | mask | fixed-inflight | — |
| 1907.10397 | mask | fixed-inflight | — |
| 2009.11016 | mask | A-boxopt | `\multirow{1}{*}[40pt]`→`[40这是译文]` |
| 2104.00138 | mask | A-boxopt | `\multirow{2}{4em}[-1em]`→`{4这是译文}[-1这是译文]`，105 错 |
| 2105.00030 | mask | B-tassign | bibitem 区 `1em\relax`→`1这是译文\relax`（同页 `\hskip 1em plus…` 完好） |
| 2105.03798 | mask | fixed-inflight | — |
| 2203.00091 | mask | fixed-inflight | — |
| 2203.13025 | mask | fixed-inflight | — |
| 2211.00113 | mask | A-graphics | `\includegraphics[height=\FigHeight mm]` cs+单位模式（记录格，现场已净） |
| 2308.00148 | mask | A-graphics | `\includegraphics[trim={0cm 96bp 0cm 95.25bp}]` trim 列表（记录格，现场已净） |
| 2308.04175 | mask | A-matharg | `\genfrac{}{}{0pt}`→`{0这是译文}`（math 参内 dimen） |
| 2308.12591 | mask | fixed-inflight | — |
| 2308.12641 | mask | fixed-inflight | — |
| 2403.00028 | mask | ? | arxiv-v2.tex:278/186/272 记录格，现场已净 |
| 2403.00048 | mask | fixed-inflight | — |
| 2403.00092 | mask | fixed-inflight | base undefined_cs×14 → clean |
| 2403.05490 | mask | fixed-inflight | base syntax×55 → clean |
| 2404.03001 | mask | fixed-inflight | — |
| 2410.17949 | mask | fixed-inflight | — |
| astro-ph/0104004 | mask | fixed-inflight | — |
| gr-qc/9901080 | mask | fixed-inflight | base reject → illegal_unit → clean |
| hep-ph/0307177 | mask | fixed-inflight | — |
| hep-ph/0307181 | mask | B-titlepg | `\maketitle` 处爆（titlepage/author 块 `\\[8?]` dimen） |
| hep-ph/0605090 | mask | fixed-inflight | — |
| hep-ph/0605151 | mask | fixed-inflight | — |
| hep-th/0104206 | mask | fixed-inflight | — |
| hep-th/9901150 | mask | fixed-inflight | 唯一 fixloop `unfixable:illegal_unit` 格，561368d 后 clean |
| math/0408128 | mask | fixed-inflight | base undefined_cs×15 → clean |
| nucl-ex/9910015 | mask | fixed-inflight | base reject → illegal_unit×4 → clean |
| nucl-th/0104063 | mask | fixed-inflight | base reject → illegal_unit×10 → clean |
| physics/9901057 | mask | B-tassign | `\baselineskip=10pt` 在 center 块内漏（同件 `\newcommand` 体内的完好） |
| q-alg/9703033 | mask | fixed-inflight | base reject → illegal_unit×17 → clean/invalid_char |
| quant-ph/0104053 | mask | fixed-inflight | — |
| quant-ph/9703040 | true* | B-tassign | 源 `24ptA`/`24ptSoon` 单位后跟字母本就非法；TeX 两臂同式 pt 自恢复；bulk 实为 108×missing_number（`\bffam` 族，别的问题） |
| quant-ph/9910050 | mask | B-tassign | `\baselineskip=10pt` center 块同族 |
| solv-int/9910006 | mask | fixed-inflight | — |

汇总：**mask 89 / true\* 1 / true 0**。比例估计：真族 ≤ ~1%。

## 修法建议

illegal_unit 是下游症状，**修法落点在上游 segmenter/xlat 单位保护**（`src/texlate/latex/tables.py` 的 `DIMEN_TAIL_KIND` + `TRANSPARENT_HEAD_SPEC` 体系），不在 fixloop。残留 25 格按语境缝隙分四簇：

1. **逗号小数 dimen**：`\raise 1,5pt`、`\\[1,5cm]`——TeX 接受 `,` 为小数点（欧陆惯例），保护正则只认 `.`。改动面：dimen-atom 扫描加 `,` 等价物。代表格 0806.4203、0905.0575。
2. **组参/可选参内 dimen 漏保护**：`\setlength\cs{dimen}` 第二参（1404.2334、1608.02270、1907.00220）、`\multirow{n}{w}[bigstrut]`（1206.5646、1608.02289、2009.11016、2104.00138）、`\begin{adjustwidth*}{l}{r}`/`\begin{hangparas}{i}{n}` 环境参（1706.02447、1803.00111）、`\genfrac` 第三参（2308.04175）、`\makebox/\framebox[w]`（1608.06760——已在 SPEC 里仍漏，疑嵌套/组内路径未生效）、`\resizebox` 嵌在 `\rotatebox{0}{…}` 可译文本参内时头参保护丢失（0806.4653 等 4 格）、`\includegraphics` 的 `height=<cs> mm`/`trim=` 列表（2211.00113、2308.00148）、tikz node 选项（1803.00116）。
3. **`\\[dimen]` 换行可选参**：0905.0575、1511.06628、hep-ph/0307181（titlepage 区）。
4. **散文中位的寄存器尾参**：`\baselineskip=10pt` 在 `\newcommand`/minipage 体内被护住、在 `\begin{center}` 散文区漏（physics/9901057、quant-ph/9910050）——`DIMEN_TAIL_KIND` 已收 baselineskip，漏的是"组内 surface 是否走尾扫"的分支；`\hskip.` 分数写法（1511.02686）、`1em\relax`（2105.00030）、内联 `\parsep0ex \itemsep.2ex`（1404.0144）。

次级观察：

- verdict.category 取首错类别会遮 bulk：quant-ph/9703040 的 110 错里 108 是 `Missing number`（`\bffam/\slfam/\itfam` 旧字体宏族），illegal_unit 只是 first_error。打分/分桶时建议同时看 n_errors 构成，别让首错标签独占归因。
- fixloop `acceptable_pdf` 终态=出 PDF 但残错——这批格不是"没修好"，是"PDF 已出、余波未清"，上游修完后应自然转 clean。
- 不建议在 fixloop 加 `<num><CJK>`→补 pt 的救援规则：签名虽清晰，但会把上游漏保护的症状就地糊住，反而丢掉定位信号；让 compile 继续报 illegal_unit 是更健康的暴露方式。
- quant-ph/9703040（唯一 true\*）：源 `24ptA` 本就触发同款非致命错，两臂输出等价。若要洁癖可用 normalize 把 `(\d)(pt|cm|em|ex|mm|in|bp|pc)(?=[A-Za-z])` 断个空格，但零收益——TeX 已自恢复。
