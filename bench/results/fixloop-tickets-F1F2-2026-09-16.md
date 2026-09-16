# fixloop F1+F2 工单证据 —— 退役包 shim 扩表 + undefined_cs 逐签名归因

日期 2026-09-16 · 工单： `docs/research/product/2026-09-16-batch-hardening-design.md` §9 F1/F2 · 数据源： `bench/results/e2e-real-n100-postcutover-2026-09-16/`（cases.jsonl + results.json + `bench/work_e2ereal/pipe-xel/*/​*.log`）· 落点： `src/texlate/compile/fixloop/rules.yaml`（shim_map / cs_table / filemap.overrides 三处追加）+ `tests/test_fixloop_f1f2.py`

## 1. missing_file 签名清单（n100 pipe-xel/pipe-fix 全量轮次）

| payload | 命中案 | 归因 | 处置 |
| --- | --- | --- | --- |
| espcrc2.sty ×2 | hep-lat/0111009, hep-ph/0111218 | Elsevier CRC 会议样式， 不在 TL | shim body (article 面 polyfill) |
| elsart.cls | 0707.4465 | Elsevier 退役类 | loads→elsarticle |
| aa.cls | 0905.4439 | A&A 类， TL 无 （aanda 也不在） | shim body + natbib |
| revtex4.cls | 1003.4522 | revtex 老名 （v4-2 现行； revtex.cls 表项之外另一别名） | shim body→revtex4-2 + frontmatter 提前武装 |
| epsf.sty | 1003.4522 | TL 有 epsf —— 但该轮 filemap 未解出 | tlmgr 可装； 同时挂进 aastex6x needs |
| aipcheck.tex | 1306.2177 | aipproc 版本自检件 | shim body `\endinput` |
| iopart12.clo | 1306.5813 | iopart.cls 自带 \@ptsize 尺寸件 | shim body `\input{size12.clo}` |
| feedforward.eps | 1404.5720 | 图件缺失 （源侧） | 不在本工单面 （graphic 缺失非包名） |
| aastex63.cls | 2105.03750 | AASTeX v6 全退役 | shim body→emulateapj |
| binhex.tex | 2211.04574 | kastrup 包文件； INDEX_EXTS 无 .tex → 索引缺席 | filemap.overrides + shim body 双兜底 |

## 2. F1 shim_map 扩列（rules.yaml `legacy_pkg_shim` params, 共 42 条： 3 存量 + 39 新增）

loads 委托 （有 drop-in 继任）: elsart/elsart1p/elsart3p/elsart5p/elsevier→elsarticle; sig-alternate/sig-alternate-05-2015→acmart; naturemag→nature。

body 类 shim （无继任， article+polyfill 或桥接）: aastex61/62/63/631/AASTeX62→emulateapj+6x 宏面 （共享 `&aastex6x_body` anchor); prl/apl→revtex4-2(aps,prl / aip,apl); revtex4→revtex4-2 默认版式； aipproc （双参 keyval \author); aipcheck.tex （自检件 stub); aa.cls (\inst/\offprints/\abstract 五段式/天文记号 + natbib); iopart.cls (\pacs/\keywords/\eref/\ack 环境）; iopart10/12.clo （借内核 sizeNN.clo); iopams.sty (\b<greek> 35 个 → \boldsymbol); binhex.tex (expl3 可展开进制转换）; espcrc2.sty (\address[tag]/keyword 环境）; scrpage/scrpage2→scrlayer-scrpage; doublespace→setspace+\spacing; siamltex/siamart （共享 `&siam_body`); osajnl/osajnl2 (`&osa_body`); JHEP/JHEP3/jhep/jcap (`&sissa_body`, affiliation 收集制）; jpp （双参 \title/\affiliation 收集）; apjfonts/math (bare stub)。

## 3. F2 undefined_cs 逐签名归因（10 个 first_error 案 + 级联面）

**全部 33 个 payload: 31 条 splice/join 合并残骸 → cs_map 拆回 + 2 条缺包 (citep/citeyear→natbib usepackage 注入）, 无一条原文笔误** → llm_hook 本批无笔误类命中 （机制核见 §5.3 实证候选）。

| 案 | payload | 原型 |
| --- | --- | --- |
| 1012.1321 | itemFSU | `\item FSU` |
| 2003.10959 | itemNGA | `\item NGA` |
| 2009.11013 | itemCM | `\item CM` |
| 2105.03900 | itemBalakrishnan | `\item Balakrishnan` |
| 2410.06025 | itemSPELL | `\item SPELL` |
| math/0307301 | itemFlop | `\item Flop` |
| 1206.1808 | pari, parii | `\par i)` `\par ii)` |
| 2203.13109 | itop | `{\it op.cit.}` |
| 1003.4522 | hlineCd | `\hline Cd` （修复轮次中实测） |
| math/0605301 | linebreakGF | `\linebreak GF` |
| 1511.02908 ×13 | ddr/ddf/ddt/ddR/ddF, frack/fracr, Deltau, nablau, bfr/bfv/bfk, inV | `\dd r`, `\frac k`, `\Delta u`, `\nabla u`, `\bf r`, `\in V` 等 |
| 2401.17274 （级联） | itUhuru/itEinstein/itChandra/itXMM, rmROSAT/rmSRG | `{\it Uhuru}`, `{\rm ROSAT}` 等 |
| hep-ph/9910403 （级联） | rmand | `{\rm and}` |
| 缺包类 | citep, citeyear | natbib (aa.cls shim 已内置； 裸用稿走 usepackage 注入） |

**llm_hook 候选 （笔误/LLM 破坏类， 记入笔记不建实现）**: 0707.3950 —— 源用 `\section`/`\subsection`, 译文把其 `\def` 体内的 `\@startsection{...}{引言}` 原样抄进正文 (@catcode=12 → `\z` 等连环 undefined, errors>3×40; 该案在「管线引入回归」清单内）。cs_map 无法表达 7 参宏改写 → 典型 llm_hook/结构修复面。机制现状： escalate_llm→ctx.llm_hook 通路在， impl 是 stub (undefined_cs_guess 落点）。

## 4. 冒烟期发现并钉住的坑（真 xelatex 验证）

- `\ProvideEnvironment`/`\provideenvironment` 在 LaTeX2e 2025-11 内核**不存在** → 环境 provide 一律 `\@ifundefined{name}{\newenvironment{...}}{}`（espcrc2/siamltex/iopart 三处）。
- expl3 无 `\int_pow:nn`; `\exp_args:Ne \use_none:n {X}` 会整体吞掉展开结果 → binhex 用 `\tl_count:n` 比较 + 递归前缀补零实现 width-pad (kastrup 真身语义： 补零到宽， 不截断）。产出实测： `\nhex{4}{9321}`→`2469`, `\nbinbased{1}{6}{13}`→`001101`。
- revtex4-2 把 frontmatter 机器 (\collaboration@sw/\AU@grp/\CO@grp) 推迟到 `\begin{document}` 的 `\frontmatter@init` 武装 —— revtex3 老稿导言区 `\author` 全炸。shim 在 `\LoadClassWithOptions` 后 `\frontmatter@init` + `\let\frontmatter@init\relax` 冻结， 防 begin-doc 重跑清导言区数据 (prl/apl 两条）。
- emulateapj 自带 revtex 系 `\email`(2 参隐参版， 内部 \@AF@join 未武装会炸）/`\collaboration`/`\keywords`(showkeys 门控） → `\providecommand` 失效， 必须 provide+renew 对 (aastex6x anchor)。
- espcrc2 `\address` 在 `\author` 参数体内 → 落进 article \maketitle 的 tabular cell, 组内 `\\` 崩 → `\newline` + `\let\\\newline` 化参数内 `\\`。
- filemap.overrides `"binhex.tex": "kastrup"` 已挂， 但 **xelatex 通路不读 overrides** (engine._wire_engine L809-829 只接 tectonic CtanFetcher) —— xelatex 侧靠 shim body 兜底， 双轨均有。

## 5. 留给 leader 的口子

1. `filemap.overrides` xelatex 盲区： 索引缺席的文件 （非 .sty/.cls 扩展名， 如 binhex.tex) xelatex 臂永远装不上， 只能靠 shim 兜底 —— 建议 overrides 接到 xelatex install_file 前置， 或 INDEX_EXTS 补 `.tex`/`.rtx`。
2. **通用合并-cs 拆分器建议**: 本批 31 条全是「真 cs + 后 token」粘连， 模式高度规整 （前缀匹配已知 cs 表 + 词边界）； 与其逐案扩 cs_table, 可做一轮「payload 对已知 cs 字典的前缀拆分」规则 —— 2401.17274 单案就有 6 个 {\it/\rm+X} 变体， 逐条进表是 whack-a-mole。
3. `\@startsection` 类 @-cs 入正文 (0707.3950) = LLM 把 \def 体展开抄文 → llm_hook 签名面已实证， 建议 llm_hook 实装时以该案为首测。

## 6. 验证

- `tmp/shimtest/` 真 xelatex 冒烟： 37/37 PASS （每 shim 一份实证宏面 doc, stub 从 rules.yaml 直生）。
- `uv run pytest tests/test_fixloop_f1f2.py`: 62 passed （每表项 transform 级断言： stub 落盘/needs→install_calls/日期前缀/cs_map 改写+词边界/overrides 存在性）。
- `uv run pytest tests/ -x -q -k fixloop`: 207 passed 无回归。
- `uv run ruff check`: clean (select=ALL)。
- 复验依赖： `tlmgr --usermode install revtex nature epsf` 已入 ~/texmf （冒烟前提）。
