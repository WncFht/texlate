# LaTeXML / pandoc(LaTeX reader) 评估报告

日期: 2026-09-14 · 评测者: 评估子代理 · 实测环境: macOS arm64, TeXLive 2026basic

| 工具 | 版本 | 安装 |
|---|---|---|
| LaTeXML (`latexmlc`) | 0.8.8_5 (brew bottle) | `brew install latexml` 直接可用 |
| pandoc | 3.11 (已装) | — |

**一句话结论: 两者都不是"解析器"而是"渲染器/读者"。LaTeXML 是真·TeX 引擎(宏全展开、条件真求值),对单篇可渲染文档质量高但在本机 TeXLive 2026 上有 expl3 死循环坑; pandoc 是宽容的部分展开 reader,极快(<1s)、覆盖更广,但会静默丢内容(参考文献表整个消失)。管线定位: 不当主解析器; pandoc 适合做快速结构体检, LaTeXML 适合做受限的"可渲染性 oracle"; arXiv 官方 HTML 路线对本语料覆盖 11/12,可作备选数据通路。**

---

## 1. 语料实测矩阵

主文件逐个跑(在论文目录内执行),LaTeXML 用 `latexmlc --dest=… main.tex`,pandoc 用 `pandoc -f latex -t html`。

| 论文 | LaTeXML | 耗时 | pandoc | 耗时 |
|---|---|---|---|---|
| 1412.6980 (Adam, 实为 \includepdf 壳) | ✅ 但无内容(2KB) | 2.7s | ✅ 空输出(1B) | 0.1s |
| 1511.06432 (ICLR16, natbib) | ✅ 113KB | 4.5s | ✅ 76KB | 0.4s |
| 1512.03385 (ResNet, CVPR+eps) | ❌ **FATAL** | 6.9s | ❌ **ERROR** | 0.6s |
| 1706.03762 (Transformer, 多文件) | ✅ 127KB | 4.8s | ✅ 98KB | 0.14s |
| 1810.04805 (BERT, acl_natbib+tikz) | ✅ 206KB | 11.7s | ✅ 93KB | 0.15s |
| 1906.08237 (XLNet, custom.tex) | ✅ 267KB | 19.9s | ✅ 145KB | 0.13s |
| 2005.11401 (RAG) | ✅ 190KB | 7.5s | ✅ 79KB | 0.09s |
| 2106.09685 (LoRA, math_commands+tcolorbox) | ❌ **挂死 >300s 杀** | — | ✅ 265KB | 0.7s |
| 2203.02155 (InstructGPT) | ❌ **expl3 死循环, 90s 超时** | — | ✅ 285KB | 0.34s |
| 2305.14335 (IEEEtran) | ✅ 325KB | 10.1s | ✅ 102KB | 0.11s |
| 2501.14787 (minted+kbordermatrix+私有sty) | ❌ **FATAL** | 16.7s | ✅ 1.06MB | 0.35s |
| hep-th/9901001 (LaTeX 2.09!) | ✅ 132KB | 5.8s | ✅ 73KB | 0.07s |

**合计: LaTeXML 7/11 可出全文; pandoc 10/11 可出全文。** 输出均为 HTML; LaTeXML 中间产物 `latexml --dest=x.xml` 可拿到结构化 XML 文档树(实测 tricky 550 行,含 `<equation>/<Math>/<cite>/<theorem>/<listing>` 等标签)。

### LaTeXML 失败详情(全部有最小复现)

1. **expl3 死循环(最严重)**: `2106.09685` 跑 9+ 分钟 CPU 99% 不退,`2203.02155` 90s 超时。根因链实测定位:
   `tcolorbox.sty.ltxml` 绑定里写死 `RequirePackage('xparse')` → `xparse.sty.ltxml`/`expl3.sty.ltxml` 绑定选择 `InputDefinitions(…, noltxml=>1)` 即**原样解释 TeXLive 的 `expl3-code.tex`** → 在 TeXLive 2026 的 expl3-code.tex:35934 处报 `\prg_replicate:nn` Negative argument,随后 `\clist_put_right` 无限复制(log 230KB 全是同一行)。**任何 `\usepackage{xparse}` 都触发**——tricky.tex 挂死就是这个,`\usepackage{xparse}` 单包即可复现(25s+ 不退)。LoRA 的链条是 `tcolorbox`(其 sty 有 expl3 依赖)。arXiv 线上没事是因为他们 pin 旧 TeXLive——**这是版本交互坑,换 TeXLive 2023 即可避开**。
2. **FATAL 但快速**: `1512.03385` — `missing file[cvpr.sty]`(自带会议 sty 未找到/无绑定)+ `\cvprfinalcopy` 未定义 → 101 errors 后 fatal,只产 1.8KB 骨架。`2501.14787` — 7 个缺包(minted/kbordermatrix/lindrew/cleveref/tikz-cd/pgfplots/eso-pic)+ 15 个未定义宏 → fatal。**缺 `\bibliography` 对应的 .bbl/.bst 不致命,缺 sty/cls 致命。**
3. **ctex 直接 fatal**: `\usepackage[UTF8]{ctex}` → Status:conversion:3。**这意味着译文(加 ctex 后)无法直接喂 LaTeXML**——oracle 用法必须在"加 ctex 之前"或"去 ctex 的校验变体"上跑。好消息: 裸 UTF-8 中文文本(不加 ctex)能正常进 HTML。
4. **图形**: 本机无 Perl 图像处理模块,`includegraphics` 全部报 `imageprocessing` 错误,`<img src="">` 空链接。tikzpicture → 生成 **1×1 px 空 SVG**(BERT 实测)。**forest 没有 .ltxml 绑定**(tikz/pgfplots/tikz-cd/circuitikz 有)——hjfy 作者否掉 HTML 路线的直接原因属实。
5. **状态语义**: `Status:conversion:0`=干净 / `2`=有错误警告但出全文 / `3`=fatal 骨架;退出码 fatal→1,ok→0;每篇有 `*.latexml.log` 含结构化错误计数。

### pandoc 失败详情

1. `1512.03385`: `\newcolumntype{x}[1]{…}` → `unexpected #1`,整文件拒绝(唯一一篇 corpus 硬失败)。
2. `tricky.tex`: **单行 verbatim** `\begin{verbatim}100% real data\end{verbatim}`(同一行)→ `unexpected end of input, expecting \end{verbatim}`——pandoc 要求 `\end{verbatim}` 独占一行,否则全文拒收。
3. `tricky-209.tex`: 正文里的旧式 `\rm` 字体开关 → `unexpected macros` 全文拒收(hep-th 论文里 `\bf` 只出现在数学中,降级为 raw TeX 而非致命)。
4. **静默丢失(更危险)**:
   - **`thebibliography` 整个环境不进 AST**(Transformer 40 条 bibitem,native 输出 0 条——被吞进 citeproc 元数据,非 citeproc 输出直接没了);
   - `\includepdf` 静默跳过(1412.6980 出 1 字节);
   - 数学中遇 `\rm/\bf/\small/\textsc` 等遗留命令 → 该条公式**回退为原始 TeX**(hep-th 103/282 条、BERT 41/93、2501 134/2507、tricky 的 `\be` 展开后也因此回退)。
5. 警告可见: 解析 `.sty` include 失败只给 WARNING 继续跑(2106/1511 都有)。

---

## 2. 陷阱构造实测(fixtures)

### tricky.tex(30 构造)

LaTeXML 原版**挂死**(xparse→expl3 循环,>120s 杀)。去 xparse 变体(`tricky-noxp`,把 `\NewDocumentCommand` 换成 `\newcommand`)6.8s 全绿:

| 构造 | LaTeXML(noxp) | pandoc(去 xparse+verbatim 改多行后) |
|---|---|---|
| T01 `\be…\ee` 展开成公式环境 | ✅ **真展开** → `<math display="block" alttext="\widetilde{A}=\mathop{\rm Tr}\nolimits(M^{2})">` | ✅ 也展开了,但 `\rm` 让 texmath 失败 → 整块回退 raw TeX `$$\begin{equation}…$$` |
| T02 `\dR`→`\mathbb{R}` | ✅ MathML `x∈ℝ` | ✅ |
| T03 `\def` | ✅ | ✅ |
| T04 natbib 全族+`\ref`系 | ✅ cite key→`ltx_cite`,`\eqref` 解析 | ✅ key→`data-cites`(无 citeproc 时渲染文本为空) |
| T05 `\section[Short]{Long}` | ✅ | ✅ |
| T06 verbatim/lstlisting 内 % | ✅ 原样 | ⚠️ 多行 OK;**单行同-line verbatim 全文拒收** |
| T07 `\url{..%20}` `\verb|a%b|` | ✅ | ✅ |
| T08 注释边界(`%`含不平衡 brace、`\\%`) | ✅ | ✅ |
| T13 `\newif\ifdraft…\else…\fi` | ✅ **取真分支**(draft 段留,final 段丢) | ✅ **同样真求值** |
| T14 \input/\include 递归+注释掉的\input(tricky-multi) | ✅ 全部展平,注释掉的不出现 | ✅ 同 |
| T16 `\NewDocumentCommand` | ⚠️ **xparse 包本身加载即挂死**(TL2026) | 未展开但也不崩(reader 当未知宏) |
| T11 theorem/href/accents/footnote-in-caption | ✅ | ✅ |
| T24 `\bibliography{refs}` | ✅(缺 .bbl 只警告) | ⚠️ 参考文献表不进 AST |
| 旧式 `\rm/{\bf}` 文本内 | ✅(hep-th 2.09 全文 OK) | ❌ 文本内硬错 / 数学内回退 raw |

### 公式保留方式(两者都保原始 TeX,利于"数学保护"校验)

- **LaTeXML**: MathML(presentation+content 平行标记) + `alttext="原始TeX"`。Transformer 78 式、hep-th 332 式全转。
- **pandoc**: MathML + `<annotation encoding="application/x-tex">原始TeX</annotation>`;转换失败式回退 `<span class="math">$$原样$$</span>`——raw 但没丢。

---

## 3. 架构分析(为什么各自这样失败)

- **LaTeXML = Perl 重写的完整 TeX 执行引擎**(mouth/stomach/gullet 分级,真展开、真条件、真类别码)。包支持靠 `.ltxml` 绑定两层: 要么 Perl 级 DefMacro 桩,要么 `noltxml` 回退**原样解释真 .sty**。强在语义级正确(\if、\be、natbib、LaTeX 2.09 都对);弱在(a)绑定缺失时真 sty 解释跟不上现代 expl3——TL2026 下必死循环;(b)forest/部分私有 sty 无绑定;(c)图片转换依赖外部 Perl 模块。产出是"渲染后的文档树",**宏边界、源码 span、注释全丢**——by design。
- **pandoc LaTeX reader = Haskell 解析器+部分展开层**。会展开 `\newcommand/\def`、求值 `\newif`、递归 `\input/\include`(连 .sty 都当 include 试着读,失败仅警告)。未知宏/环境 → `RawInline/RawBlock` 透传(所以 2501 能活着出来)。数学走 texmath 库,只认现代 LaTeX 数学命令子集,遇 `\rm/\bf/\small` 即回退保 raw。快(单篇 <1s)因为不执行 TeX。**丢弃面**: thebibliography、includepdf、不认识的 env 内容、样式信息——丢得安静,这是它最不适合当 oracle 的地方。

---

## 4. 三条用法评估

### a) 主解析器 — ❌ 两者都否

管线要"段级提取+保护+重建",需要**源码级 span 映射**(哪段文本对应 .tex 哪几字节、宏不展开、注释保留)。两者都做不到: LaTeXML 把一切消化成渲染树; pandoc 丢 bibliography/部分 env 且无源码位置(行号列号在 AST 里基本没有)。它们的 AST 是"文档"不是"源文件"。

### b) 译后校验 oracle — ⚠️ 限定条件可用

- **pandoc 作快速 lint(推荐)**: <1s/篇,译文 .tex 喂 `pandoc -f latex -t native`——真语法断(verbatim 未闭、`\newcolumntype` 类结构坏)会 exit≠0;再比对译前/译后 AST 计数(Header/Cite/Math 数)可抓"结构塌了"。**但它对"内容丢失"失明**(bibitem 整表没了都不报错),只能当冒烟测试不能当完备校验。
- **LaTeXML 作深度 oracle(限制多)**: `Status:conversion`+`.latexml.log` 错误计数确实能反映"还渲不渲得出"。但: ①必须外套 timeout(expl3 类死循环真实存在);②**基线必须同篇对比**——cvpr.sty/minted 类缺包 fatal 是"本来就渲不了"不是"翻译翻坏了",绝对计数无意义,要用 Δ(译后错误数 − 译前错误数);③**译文加了 ctex 后 LaTeXML 直接 fatal**——只能对"不含 ctex 的校验变体"或"加 ctex 前"跑;④无 CJK 语义但裸 UTF-8 中文文本本身能过。
- 结论: 双层用——pandoc 全量快筛 + LaTeXML 只对"它本来就能渲的篇"做 Δerrors 校验。投入产出一般,优先级低。

### c) 无源码备选路线(arXiv 官方 HTML)— ✅ 对本语料可行,值得留作通路

实测 `https://arxiv.org/html/{id}` 对本 corpus **12/12 有页面,11/12 是全文 HTML**(唯一空的 1412.6980 本来就是 \includepdf 壳,无源码可译):

| id | arXiv HTML | 字节 | MathML 数 |
|---|---|---|---|
| 1706.03762 | ✅ | 188KB | 142 |
| 2106.09685(本机挂死!) | ✅ | 504KB | 637 |
| 1512.03385(本机fatal) | ✅ | 362KB | 136 |
| 2501.14787(本机fatal) | ✅ | 1.9MB | 2722 |
| hep-th/9901001 | ✅ | 208KB | 283 |
| 其余全部 | ✅ | — | — |

要点: **本机 LaTeXML 失败/挂死的 4 篇,arXiv 线上全部成功**——证实失败是 TeXLive 2026 expl3 版本交互而非论文本身。arXiv 用 pin 住的 TeXLive+LaTeXML 版本批量预转。
- 可用模式: 对没拿到好源码或自转失败的篇目,`arxiv.org/html/{id}` → 拿到的就是 LaTeXML 渲染树(MathML 公式、`ltx_section` 结构),翻 DOM 文本节点 → 双语 HTML/打印 PDF。
- 边界: ①只覆盖 arXiv 有 LaTeX 源且线上转换成功的篇(线下见到过 conversion-failed 页,需探测);②includepdf 壳类产空页;③无源码位置映射,不能做"回写原 .tex"——所以它只能是**平行备选通路**不是主路。
- 建议: 管线里加一个轻量探测 `HEAD arxiv.org/html/{id}` + 检查页面是否含 `ltx_document`,命中且本地管线失败时降级走 HTML 路线。

---

## 5. 可复用性总结

| 能力 | LaTeXML | pandoc reader |
|---|---|---|
| 单篇成功率(corpus) | 7/11 | 10/11 |
| 速度 | 5–20s/篇,会挂死 | <1s/篇,从不挂 |
| 宏展开 | 完整 TeX 语义 | 部分(\newcommand/\def/\newif/\input) |
| 公式输出 | MathML+alttext | MathML+annotation,失败回退 raw |
| 参考文献 | .bbl 正常渲染进文档 | thebibliography 整个丢弃 |
| LaTeX2.09 | ✅ hep-th 全文 | ⚠️ 数学内回退/文本内硬错 |
| forest | 无绑定 ❌ | 透传 raw(不渲但也不丢源) |
| tikz | 有绑定但本机产空 SVG | 图路径透传为 `<img src>` |
| 源码保真 | ❌ | ❌ |
| 当校验 oracle | 受限(基线对比+timeout+去ctex) | 可作快速 lint |
| 数据通路 | 本地自渲染用 | arxiv.org/html 直接吃其产物 |

**最终建议**: 主解析仍走自研段级保护管线; pandoc 进管线当"译后结构冒烟测试"(便宜、抓灾难性破坏); LaTeXML 不进关键路径,仅作"该篇本来就能渲"集合上的 Δerrors 深度抽查,且必须 timeout+基线对比+不含ctex; arXiv HTML 留作无源码/本地失败篇的降级数据通路,覆盖率实测很高。
