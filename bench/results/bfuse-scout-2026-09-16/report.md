# bfuse-scout — B 类 cs+latin 融合语料流行度评估

> 2026-09-16。源自 realarm-repro bug 类 B（主路径 cs+latin 融合 `\itemFSU`/`\pari`）。方法：全 .tex regex 扫描，注释+verbatim 屏蔽；头条数另做数学屏蔽（`$..$`/`$$..$$`/`\[..\]`/`\(..\)`/equation/align/gather/multline/eqnarray 等环境）。工件：`report*.txt`、`stats*.json`、`samples*.json`。

## 头条（corpus_v3，5051 篇；模式 = cs + 空格/换行 + latin 字母）

| 组 | 篇数 | 占比 | 次数 |
|---|---|---|---|
| `\item` | 1787 | 35.4% | ~23.9k |
| `\noindent` | 1015 | 20.1% | ~5.9k |
| `\par` | 124 | 2.5% | ~2.4k |
| 带参 cs 裸用（`\section`…`\url`） | 44 | 0.9% | ~100 |
| **spec'd-13 并集** | **2423** | **48.0%** | |
| 字体声明 `{\it Foo}` 系（`\it \bf \em \rm \sc \sl \sf \tt` + size 声明 + `*shape/*series/*family`） | 3801 | 75.3% | ~150k |
| 表线 `\hline/\midrule/\toprule\nCell` | 1295 | 25.6% | ~8.6k |
| 间距类（`\quad \hfill \newline \indent \smallskip` …） | 886 | 17.5% | |
| **宽类并集（以上全部）** | **4565** | **90.4%** | |

corpus（39）：spec 并集 66.7%、宽类 97.4%。corpus_v2（137）：spec 48.9%、宽类 90.5%。三语料一致。

逐 cs 明细（v3，数学屏蔽后）：`\it` 2154+309 篇、`\bf` 1902+185、`\em` 1299+240、`\rm` 1140+116、`\tt` 432+64、`\sc` 415+32、`\hline:nl` 1077 篇/6538 次、`\midrule:nl` 229/1328、`\toprule:nl` 199/624、`\quad` 245+113。

## 模式 (c) `\<cs>%\n<latin>` 注释分隔变体 —— 稀有但真实

v3 item:cmt 8 篇/39 次、par:cmt 3/19、noindent:cmt 4/4。抽样全为真命中（含 1206.1808 自己的 `\par%\nLet us` main.tex:113,199——报告案例实证）。

## 源内已融合（`\itemFoo` 字面）—— 噪声非信号

被合法长 cs 名主导（`\partial` 57k、`\paragraph` 4.5k、`\footnotesize` 4.3k、`\itemsep`、`\captionsetup`、`\urlprefix`）。真融合 `\item<Cap>` 痕量级。

## FP 估计（每主模式 ~25 蓄水池抽样 + 扩展抽查）

- spec'd 集：~0–5% FP。抽样全真实文本（`\item Let/If/We`、`\noindent Differential…`、`\par In order…`）。`\emph X` 裸参惯用法仍危险。
- 扩展集：`\it/\bf/\em/\sc` 命中全真实文本（含 `{\it J. Chem. Phys.}` 文献条目——bib 或不译但同走 writer → 照样融合）。`\rm`（~50% FP：自定义数学环境 `\be/\ee` 未屏蔽 + preamble `\def` 体）、`\quad/\qquad`（~50% FP 同因）、`\underline` 多为 def-体 FP。不动摇头条数。

## 严重度修正

暴露 ≠ 致命：融合只在译文保持 latin 首字母时编译致命（专名/缩写/单字母标签——`\item FSU`、`\par i)`）；CJK 首字输出（`\item中文`）无害。`\item` 后词频：The/If/We/For 主导（→CJK，良性），但每篇 ~13 次给专名首字母命中留足机会。

## 判定

**B 类是 top-5 系统洞，非长尾。** 窄 spec'd 集已触半数的论文；宽类 ~90%。通用 segmenter 侧修复（cs 与字母首 token 间发空格/`{}`）买下整个 90%；仅 `\item` 修只买 ~35%。与 realarm 吻合：基线 12 格退化中 5 格是本类。
