# 端到端 mock 管线实验报告

> 复现 hjfy.top 机械链路验证：miniscanner 解析 → 占位符保护 → 分块 → mock 翻译 → 译文拼接 → ctex 注入 → xelatex 重编译。
> 无 LLM，全部译文为确定性 mock；目的是验证**机械链路**正确性并枚举失败模式。
> 代码：`tmp/exp/e2e/pipeline.py`（~640 行，stdlib + `import miniscanner`，bench 源码零改动，补丁全部 monkeypatch）。
> 数据：`tmp/exp/e2e/results.json`、`work/`（A）`workBase/`（原文对照）`workB/`（B）、`base-verdicts.json`、`tlmgr-search-cache.json`。
> 日期：2026-09-14。

## 0. 结论先行

1. **链路走通**：16/16 个代表性 arXiv 项目，mock 翻译 + ctex 注入后 **16/16 产出 PDF，0 个 FAIL**；13 clean（错误 ≤3），3 个 pdf~ 全部由**预存在错误**主导（与原文 base 对照逐条相同）。中文确实进了 PDF（页数普遍上涨，如 1106.1445 778→864 页）。
2. **identity + 占位符守恒全绿**：111 个 .tex、9945 chunks、42341 个占位符出现，`reconstruct(原文) == 原文` 字节级一致 111/111，译文占位符计数 src==zh 全等，`leftover_ph=0`。
3. **"出了 PDF ≠ 成功"被实锤**（Mock B）：4 个项目注入 132 处损坏译文，**4 个全部仍然产出 PDF**；其中 56 处丢占位符损坏**产生 0 条编译错误**（静默内容丢失），76 处断花括号损坏产生 ~78 条错误（响亮）。v0 校验器 132/132 捕获（100%），证明**校验层必须在编译前**，编译不能当校验器用。
4. **发现 miniscanner 一个语科级 bug（BUG1）**：`_args` 单 token 参数会吃掉 `\`，未知命令把后续控制序列名拦腰切断。全语料 39 项目共 **3452 处切断**，其中 **1053 处切口落在可译 chunk 内**（译文必坏）。打补丁后 0 处。这是最恶性的一例：`math/0404188/main.tex:111` `\subjclass{...}\n\n\begi|n{abstract}` —— `\begin{abstract}` 被切成 `[[CMD_n]]` + chunk 里的 `n{abstract}`，abstract 环境直接没了。
5. **LaTeX 2.09 路由是静默死路**：hep-th/9901001（`\documentstyle`）注入 `\usepackage{ctex}` → "LaTeX2e command \usepackage in LaTeX 2.09 document" 报错、ctex 根本不加载 → PDF 照出（8 页）但 **5954 个 Missing character 警告、0 个中文进 PDF**。管线必须在 `\documentstyle` 处**拒绝或改走转换路由**。
6. 机械链路上真实译器不需要面对、但 v0 必须处理的细节还有：CJK 粘连（`\item这是` 合并成未定义 cs）、bare `\input file` 文件名被翻、bare 尺寸参数（`\vglue -10mm`）混进 chunk、定界符命令（`\left(`/`\\[2mm]`）参数泄漏、latin-5 非 UTF-8 源、21 种缺包（tlmgr usermode 可解，hyperxmp 不可重定位需手工 `.ins`）。
7. mock 假设了"位置忠实"的译器（占位符原地保留、控制序列不动）——真实 LLM 不满足此假设，**占位符位置敏感性**（`\bibitem` 前缀、`\href` 邻接、verbatim 内 `%`）是下一阶段必须单独验证的风险，本实验**没有**覆盖。

## 1. 实验设置

- **项目集**（16 个，覆盖语料主要构造维度）：amsart、amsart 多文件 thesis、revtex4-1 自带 cls、revtex4 原版、revtex4-2 多行 docclass、IEEEtran 自带 cls、IEEEtran+latin5+pstricks、acmart（docclass 被注释）、acmart-manuscript、elsarticle×2、多 `\input` 文件、subfiles 类、2.2MB 单文件 book、**LaTeX 2.09 `\documentstyle`**、aa.cls 103 文件。
- **per-file 翻译模式**：每个 `*.tex` 原地翻译（不 flatten）——正确处理 `\subfile`/`\input` 各自编译的语义（2609.06443 subfiles、1706.03762 十文件、1502.01589 三十五文件均 clean）。
- **Mock A**（位置忠实译器）：`TOKEN_RX` 把 chunk 切成占位符 `[[X_n]]` / 控制序列 `\cs` / 括号 `[](){}|` / 散文段，前三类**原位保留**，非空散文段 → 固定句 `这是一个用于验证编译的测试段落。`（`pipeline.py:266` 起）。
- **Mock B**（幻觉译器）：每 10 个 chunk 损坏 1 个——半数丢首个占位符、半数追加 `}`（`mock_b`）。
- **注入**：`find_docclass_end` 找首个非注释 `\documentclass`/`\documentstyle`，括号配平确定调用终点（支持多行、穿插注释），其后插 `\usepackage[fontset=fandol,UTF8]{ctex}`。
- **编译**：`xelatex -interaction=nonstopmode -file-line-error`，≤2 pass，timeout 180s；`max_print_line=10000`；verdict = 出 pdf 且错误行 ≤3 → clean / 出 pdf → pdf~ / 否则 FAIL。错误行同时计 `!` 前缀**和** `./file:line:` file-line-error 两种格式（只数 `!` 会漏掉全部引擎级错误）。
- **校验器 v0**（`validate_chunk`，pipeline.py:300）：占位符多重集相等 + 非转义花括号配平。

## 2. 每项目结果（Mode A）

| 项目           | tag                      | tex 数 | chunks | 占位符 | identity | 注入行 | base      | A         | A 错误 (前 3)                  | 页数 b→A |
| -------------- | ------------------------ | ------ | ------ | ------ | -------- | ------ | --------- | --------- | ------------------------------ | -------- |
| math/0404188   | amsart                   | 1      | 235    | 2905   | ✓        | 1      | clean     | **clean** | 0                              | 56→77    |
| 1111.4914      | amsart-thesis            | 1      | 531    | 3207   | ✓        | 1      | clean     | clean     | 1: `\textfont 6 is undefined`  | 51→76    |
| 1403.3985      | revtex4-1 自带 cls       | 2      | 220    | 779    | ✓        | 5      | clean(2)  | clean(2)  | 同 base                        | 26→27    |
| 0906.1291      | revtex4 原版             | 1      | 58     | 333    | ✓        | 33     | clean     | clean     | 0                              | 11→12    |
| 2308.07483     | revtex4-2 多行 docclass  | 1      | 104    | 384    | ✓        | 13     | clean     | clean     | 0                              | 10→12    |
| 2305.14335     | IEEEtran 自带 cls        | 7      | 94     | 286    | ✓        | 53     | clean     | clean     | 0                              | 13→12    |
| 0807.3917      | IEEEtran latin5 pstricks | 11     | 313    | 1969   | ✓        | 11     | pdf~(126) | pdf~(126) | 同 base（pstricks dvips-only） | 2→3      |
| 1712.01208     | acmart 注释掉            | 12     | 380    | 369    | ✓        | 3      | clean     | clean     | 0                              | 31→26    |
| 2602.19229     | acmart-manuscript        | 12     | 307    | 1924   | ✓        | 47     | pdf~(73)  | pdf~(77)  | +4 新错见 §3-F9                | 26→42    |
| 1207.7214      | elsarticle ATLAS         | 2      | 328    | 4905   | ✓        | 1      | clean(1)  | clean(1)  | 同 base                        | 41→81    |
| 2609.09529     | elsarticle 中文注释      | 1      | 375    | 1590   | ✓        | 5      | clean     | clean     | 0                              | 48→68    |
| 1706.03762     | 多 `\input`              | 10     | 157    | 262    | ✓        | 1      | clean     | clean     | 2: tikz 字体上下文             | 15→15    |
| 2609.06443     | subfiles 类              | 13     | 709    | 3790   | ✓        | 1      | clean     | clean     | 0                              | 82→126   |
| 1106.1445      | book 2.2MB               | 1      | 5572   | 16455  | ✓        | 16     | clean     | clean     | 0                              | 778→864  |
| hep-th/9901001 | **LaTeX 2.09**           | 1      | 33     | 299    | ✓        | 4      | pdf~(4)   | pdf~(6)   | +2: `\usepackage` in 2.09      | 13→8     |
| 1502.01589     | aa.cls 103 文件          | 35     | 529    | 2884   | ✓        | 2      | clean     | clean     | 0                              | 72→83    |

**合计**：111 tex / 9945 chunks / 42341 占位符出现；identity 111/111；`ph_src==ph_zh` 全部相等；`leftover_ph=0`；注入点 16/16 找对（含注释掉的、多行、`\documentstyle`）；中文归因新错误仅 **7 条**（§3-F9），其余错误与 base 逐条相同。

注入点抽查：`work/1712.01208/main_tr.tex` 第 1 行是 `%\documentclass[sigconf]{acmart}`（注释），正确跳过并在第 3 行真 `\documentclass[11pt]{article}` 后注入；`work/2308.07483/PIRT-2023VGG.tex` 的 `\documentclass[% aip, %jmp, ... ]{revtex4-2}` 跨 1–13 行且选项里穿插注释，正确在 13 行末尾后注入。

## 3. 失败分类学

按发现顺序编号；F1–F5 是**管线自身 bug 类**（已修，补丁均在 pipeline.py monkeypatch），F6–F9 是**路由/环境类**，F10 是**译器幻觉类**（Mock B 注入）。

### F1 ★ 扫描器 `_args` 吃掉 `\` 切断控制序列名（最恶性）

`bench/py/miniscanner.py:537`：`_args` 的单 token 参数分支 `elif tex[pos] not in " \t\n"` **不排除 `\`**。未知命令按 `nargs=6` 读参时，把下一个命令的 `\`+字母逐字符吃成"参数"。实例：

```
bench/corpus/math/0404188/main.tex:111   \subjclass{11N13, 11B25, 374A5}\n\n\begi | n{abstract}
bench/corpus/1706.03762/ms.tex:121       \color{red}\n    \larg | e
bench/corpus/2609.09529/…Logic.tex:145   …(M. Wang).}\n\n\addr | ess[A]
bench/corpus/1712.01208/acmart_old.tex:40 \NeedsTeXFormat{LaTeX2e}\n\Prov | idesClass{acmart}
```

全语料 39 项目实测：**3452 处切断**（顶层 2399 + chunk 内 1053）。chunk 内的 1053 处必然破坏译文——`\begi` 进了占位符、`n{abstract}` 留在 chunk 被翻成中文，abstract 环境整个消失，而且 **identity 检查对此不可见**（拼回去字节一致）。分布集中在 2609.08578（555）、1902.03178（152）、1612.09375（67）、2602.19229（54）、1712.01208（43）等。
**修复**：`_args_patched`——单 token 参数只在"紧邻 + 非 `\`"时取（pipeline.py）。补丁后全语料切断 **0**。
**教训**：占位符边界的完整性校验（"ph 尾部 `\letters` + 后续字母 = 切断"）可以做进 validator 或回归测试。

### F2 CJK 粘连：`\cmd这是` → 未定义控制序列

xeCJK/ctex 下 CJK 字符 catcode=11（字母类），译文中 `\item这是` 粘连成一个控制序列 → Undefined control sequence。最小复现验证过。**修复**：`cjk_glue_fix`（pipeline.py:235）`CJK_RX = (\\[a-zA-Z@]+\*?)(CJK)` → `\1 \2`，`\cmd`+CJK 之间插空格恒安全。post-reconstruct 全局应用一次即可。

### F3 bare `\input file`（无花括号）文件名进 chunk

`\input introduction` 的文件名落在散文 run 里被翻成中文 → `I can't find file '这是…'` emergency stop。**修复**：dispatch 里识别 bare `\input`，文件名 `[^\s{}%\\]+` 整段消费为 literal 并记入 `inputs[]`。

### F4 bare 尺寸参数混进 chunk 参数

`\title{\vglue -10mm\textit{Planck} 2015 results}`：`\vglue` 是未知命令但其参数 `-10mm` 是 bare token 不进 `{}`，留在 chunk → `Missing number, treated as zero`。**关键认知**：**chunk 内的 literal piece 依然会被翻译**——保护必须用 `run.append(self._ph("CMD", …))`（chunk 内免疫的占位符），`flush_run()+_emit` 的 literal 形态不够。**修复**：`DIM_BOUNDARY`（vglue/hglue/vskip/kern/parindent/baselineskip 等 ~20 个）+ `ARG_BOUNDARY`（vspace/hspace/cline/setcounter/setlength/newtheorem/linebreak 等 ~20 个），均以 ph-in-run 保护其 `* [opt] {arg}`/bare-dim 参数。

### F5 定界符命令与 `\\[dim]`

`\left(`、`\bigm|`、itemize 后 `\\[2mm]`：未知命令只在下一字符是 `{`/`[` 才保护，`\left(` 的 `(` 是普通字符 → `(` 单独进 chunk。`\\[2mm]` 的 `[2mm]` 同理（且 `[这是]` 会被当可选参数翻）。**修复**：`DELIM_BOUNDARY`（left/right/middle/big*/Big*/bigm* 族，`*`+一个定界 token）+ `\\` 后仅在内容形如 `[-+0-9.…]` 时才吃 `[opt]`（`_ws1` 帮助器：跳过空格和至多一个换行，不跨段落）。

### F6 ★ LaTeX 2.09 路由：ctex 静默不加载（最严重的产品级失败）

hep-th/9901001 是 `\documentstyle{ptptex}` 的 2.09 文档。注入发生在第 4 行后（`\usepackage` 落在第 5 行）：

```
./imamura2.tex:5: LaTeX Error: LaTeX2e command \usepackage in LaTeX 2.09 document.
./imamura2.tex:5: LaTeX Error: \usepackage before \documentclass.
```

xelatex nonstopmode 报错继续跑，**PDF 照出 8 页**，但 ctex 从未加载：日志 5954 条 `Missing character: There is no 这 ("8FD9) in font rm-lmbx12!`，PDF 里 Fandol 字体、UTF-8 中文字节均为 0（`Fandol in pdf: False`）。**这是全实验最坏的形态：verdict=pdf~ 看似半成功，实际译文 0% 渲染**。v0 必须在检测 `\documentstyle` 时走"拒绝/转换/回退 pdflatex+2.09 专用方案"路由，且 verdict 体系需要"中文实际进 PDF"检查（抽查 PDF 字体表或日志 Missing character 计数）。

### F7 非 UTF-8 源

0807.3917 main.tex 是 ISO-8859(latin-5)，`read_text(utf-8)` 抛异常 → `errors=replace` 读入、`utf-8` 写出。111 个 tex 仅此 1 个非 UTF-8。base/A 错误数相同（126，全是 pstricks 在 xelatex 下 dvips-only 的预存在错误），编码替换没有引入可观测差异，但**替换字符 `U+FFFD` 会进译文**——v0 应先 chardet 探测再按原编码读、写出前回编码或统一转 UTF-8。

### F8 缺包 → tlmgr usermode fixloop

编译失败日志 → 缺文件正则（`File \`x.sty' not found`/`I can't find file`/ TFM / font not loadable 四类）→`tlmgr search --global --file`→`tlmgr --usermode install`→ 重编译。全程共解析 **21 种缺失文件**（tlmgr-search-cache.json：xypic/revtex4/pstricks/bbold/acmart/elsarticle/subfigure/changepage/hypernat/ptptex/epsf/txfonts/ncctools/contour/lkproof/bussproofs/mathpartir/dashbox/mleftright/totpages），usermode 装进`~/Library/texmf`。**例外**：`hyperxmp`标记 not relocatable，usermode install 拒绝 → 手工`tex hyperxmp.ins` 生成 .sty 拷进 TEXMFHOME。v0 fixloop 需要"不可重定位 → 本地生成/放弃"的兜底分支。

### F9 CJK 进非 Unicode 字体上下文（残余噪音，无修复必要但需知晓）

zh+ctex 后仍新增的错误共 7 条 / 3 项目，全部是"CJK 落在显式 TFM 字体/盒子里"：`1706.03762 model_architecture.tex:102` tikz 节点用 `ptmr8c` → `Cannot use XeTeXglyph with ptmr8c` + `Missing number`（2 条）；`1111.4914` abstract 内 `\textfont 6 is undefined`（1 条）；`2602.19229` bussproofs `\hbox`/`math` 上下文 → `Extra }, or forgotten $.`+`Missing $`+`\baselinestretch`（4 条）。均产 PDF，属 xeCJK 已知边界（CJK 回退字体不覆盖 `\hbox{}`+硬编码 TFM 字体场景）。真实译器同样会踩——v0 可把 "CJK in \hbox/\textfont/tikz font spec" 列为已知残余。

### F10 译器幻觉（Mock B 注入，校验器验证）

| 项目         | 损坏 | 丢占位符 | 断 `}` | validator 捕获 | B 编译错误                      | B verdict         |
| ------------ | ---- | -------- | ------ | -------------- | ------------------------------- | ----------------- |
| math/0404188 | 24   | 11       | 13     | 24/24          | 13（全 `Too many }`/`Extra }`） | pdf~（77 页照出） |
| 1111.4914    | 54   | 25       | 29     | 54/54          | 30                              | pdf~              |
| 1207.7214    | 34   | 14       | 20     | 34/34          | 21                              | pdf~              |
| 1706.03762   | 20   | 6        | 14     | 20/20          | 14                              | pdf~              |

**132/132 = 100% 编译前捕获**。错误数 ≈ 断 `}` 数（13/30/21/14 vs 13/29/20/14）；**56 处丢占位符产生 0 条编译错误**——静默删内容（cite 消失、公式消失、整条 `\bibitem` key 消失）PDF 毫无异常。这从两个方向证明校验层必须独立存在：响亮损坏靠编译抓得到但为时已晚且 PDF 仍出，静默损坏编译永远抓不到。

**validator v0 误报（已识别）**：Mode A 有 22 个 `brace_unbalanced` flag，全部是**源 chunk 自身花括号跨边界**的合法情形（如 1207.7214 chunk287/288 把 `{\em …}` bibitem 条目一切为二，src 平衡 ±2 非零）。v0 改进：比较 `balance(zh) == balance(src)` 而非 `== 0`。

### 预存在错误（非管线问题，作对照）

- 0807.3917：pstricks 是 dvips-only，xelatex 下 126 错，base/zh 完全一致 → 该项目本身就不是 xelatex 兼容稿，v0 路由应识别 pstricks→dvips 链或直接判不适合。
- 2602.19229：acmart+biblatex `xkeyval` 73 错 base 就有（acmnumeric.bbx 选项），中文再加 4 条 F9。
- 1403.3985、1207.7214：各 1–2 条 `\endgroup`/`Loading a class or package in a group`，base 原样。

## 4. 本实验证明了什么 / 没证明什么

**证明了**：

- miniscanner（打 5 个补丁后）作为分块器：16 项目 9945 chunk 的切分→保位 mock→拼回→编译全链路闭环，identity 字节级、占位符零泄漏。
- ctex[fandol] 一行注入对 15/16 项目足够（2.09 除外）；注入点定位算法（注释感知 + 括号配平）对多行/注释干扰 docclass 全部正确。
- "per-file 原地翻译"模式正确处理 subfiles/multi-input/103 文件项目，无需 flatten。
- 校验器必须存在且能在编译前 100% 抓住两类典型幻觉。
- 错误计数必须同时数 `!` 与 file:line 两种格式，否则引擎级错误全漏。
- tlmgr `--usermode` fixloop 能把缺包项目救活，需要不可重定位兜底。

**没证明**（需要真实 LLM 或专门实验）：

- **占位符位置敏感性**：mock 原位保留占位符；真实 LLM 可能移动/重复/改写 `[[X_n]]`。已知敏感点：`\bibitem{key}` 必须在其文本前、`\href` 必须贴着 `{url}`、`\url{..%..}` verbatim 参数里的 `%` 占位符落到裸文本会变活注释符。
- **译文长度/形态的编译影响**：固定短句不会撑爆 `\hbox`、长 caption、数学下标文本位；真实中文长句可能。
- **chunk 语义完整性**：固定句不检验 chunk 边界是否是可翻译单元（本实验只验机械性）。
- **字体覆盖**：fandol 覆盖 mock 句的 15 个汉字没问题；真实语料罕见字可能缺字形。
- **多 pass 收敛**：目录/交叉引用在 2 pass 内都收敛了，但 bibliography-heavy 项目没跑 bibtex 链。

## 5. 对 v0 管线形状的具体建议

1. **把 5 个扫描器补丁上游化进 miniscanner**（或作为 texlate 自有 fork 的起点）：`_args` 单 token 不跨 `\`、bare `\input` 文件名消费、DIM_BOUNDARY、ARG_BOUNDARY、DELIM_BOUNDARY+`\\[dim]`。这些是机械正确性问题，与译器无关。回归断言：全语料"ph 尾 `\letters`+后继字母"=0。
2. **管线分四层，校验层独立于编译层**：
   `parse → [validator: ph 多重集 + 相对 brace 平衡 + ph-边界完整性] → 译 → [validator: 同上对 zh] → splice → cjk_glue_fix → inject → compile → [verdict: pdf∧err≤3∧中文字体进 PDF]`。
    - brace 检查改**相对比较**（`balance(zh)==balance(src)`）消除 22/9945 那类误报。
    - verdict 增加"译文渲染确认"：日志 `Missing character` 计数 == 0，或 PDF 字体表含 CJK 字体。否则 hep-th 式静默失败会漏网。
3. **路由前置探测**：扫 `\documentstyle`→2.09 路由（v0 直接拒绝并提示"不支持 2.09"）；扫 pstricks/epsf-only → 标记"非 xelatex 友好"；chardet 非 UTF-8 → 显式转码而非 errors=replace。
4. **错误计数双格式** `^!` + `^\S+?:\d+: \S`，阈值 ≤3 判 clean 在 16 项目规模验证可用。
5. **fixloop**：缺文件正则四类 → `tlmgr search --global --file` → `--usermode install`；`not relocatable` 落兜底（下载 .ins 生成 / 放弃并标记）。全程搜索缓存落盘。
6. **mock 之外的第一步真实验证**：用"占位符会移位"的 mock C（随机挪动 10% 占位符）先量化位置敏感性，再上真 LLM——本实验已留好接口（`mock_b(cid, content)` 换实现即可）。

## 6. 复现

```bash
cd tmp/exp/e2e
python3 pipeline.py --modes A                      # 16 项目全链路 (~10min)
python3 pipeline.py --modes B --projects 0,1,9,11  # 幻觉注入 4 项目
python3 pipeline.py --modes base                   # 原文对照编译
python3 classify.py workB                          # 错误归类
```

输入：`bench/corpus/<id>/`（只读）；miniscanner 经 `sys.path` 导入 `bench/py/` 并 monkeypatch（`bench/` 零改动）。
