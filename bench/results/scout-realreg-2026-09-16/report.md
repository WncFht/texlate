# scout-realreg — real-arm postfix n100 六格未知回归归因

> 2026-09-16。对象：`bench/results/postfix-2026-09-16/`（n=100 真网关 swe-2-medium）13 格管线引入中剩余 6 格。**时间线前提**：run_meta started_at 17:55，e2e_real_bench 单长驻 asyncio 进程（concurrency=2）模块 import 定版——**a6b58d4**（18:16，gap bytes own literal run item）与 **f7822a8**（20:08，latex209 upgrader + inject 209up）均在本跑代码面之后，解释了全部 6 格。

## 逐格归因

### 1003.4522 — partial/clean，`undefined_cs:hlineCd`

ms.tex:400 `\hlineCd`（l.403 `\hlineNb`，n_errors=2）。deluxetable 表体原文 `\hline\nCd~\textsc{i} & 48 & …`——segmenter 把 `\hline` 后换行 gap 折进下一 chunk 体（state.json `source` 字面以空格起头），译文边缘 strip（`xlat/client.py:702` + `batch.py:83`）吃前导空白 → splice 逐字写回 `\hline`+`Cd` 融合。**译文从未输出 `\hlineCd`——非 LLM echo，纯管线侧**。归属 bug-B（签名扩到 `\hline<Cap>`）。现状已愈：a6b58d4 后该段不产 chunk（整行 literal）；fixloop `cs_targeted_fix` 显式收 `hlineCd`、`split_heads` 兜 `hlineNb`。

### 1206.1808 — partial/clean，`undefined_cs:pari`

main.tex:313 `\pari`（l.316 `\parii`）。原文 `…remarks:\par%\ni) The set`——`\par` 后 `%\n` 注释换行 gap 折进 chunk（`source`=`' i) The set…'`），译文 `i) 在…` 去前导 → `\pari)`。**小写尾也融合**——bug-B 不只大写。已愈（`%\n` 现为 literal）；fixloop 显式收 `pari`/`parii`（yaml 注释本就引本格）。

### 2003.10959 — partial/clean，`undefined_cs:itemNGA`

`\item The NGA algorithm…` → chunk `' The NGA…'` → 译文 `NGA 算法…` → `\itemNGA`。同段其余 `\item`+中文译文因 cs 名解析止于非字母免疫——正是「latin-initial 译文触致命」成因。已愈（`\item ` 空格现为 literal）；`itemNGA` 显式收表。

### 2105.03900 — partial/clean，`undefined_cs:itemBalakrishnan`

`\item the Balakrishnan representation \cite{…}` → 译文 `Balakrishnan 表示…` 融合（l.188 `missing \item` 级联次生）。已愈；`itemBalakrishnan` 显式收表。

### hep-ph/9703228 — partial/clean，reject_at=inject(latex209)

`\documentstyle[epsfig,12pt]{article}` 旧 inject 硬拒；base-xel 直接编 clean → 记管线引入。**inject 已愈**：冻结译文树重跑 `prepare_chinese` converted（epsfig→usepackage + compat shim）。但实编注入树 rc=1——冻结译文 l.184 裸 `\pi` 进 prose（`测量 \pi 介子产生截面` → `Missing $ inserted`）——**潜伏 bug-E 实例**（被 latex209 拒在门口未暴露）。重跑若译文不犯则 clean；rules.yaml 无「裸 cs 进 prose 包 $」专则——fixloop lane 候选。

### math/0111203 — partial/clean，reject_at=inject(latex209)

同型全愈：`prepare_chinese` converted + xelatex 实编 rc=0，PDF 449KB 含 CJK。重跑即 clean。

## 汇总

| id | verdict 对 | first_error | 根因层 | bug 类 | 现状 |
| --- | --- | --- | --- | --- | --- |
| 1003.4522 | partial/clean | `\hlineCd`(+`\hlineNb`) | gap 入 chunk + strip | bug-B | 已愈 a6b58d4 |
| 1206.1808 | partial/clean | `\pari`(+`\parii`) | 同上（`%\n` gap） | bug-B | 已愈 |
| 2003.10959 | partial/clean | `\itemNGA` | 同上 | bug-B | 已愈 |
| 2105.03900 | partial/clean | `\itemBalakrishnan` | 同上 | bug-B | 已愈 |
| hep-ph/9703228 | partial/clean | inject reject | pre-f7822a8 硬拒 | 策略拒（已除） | inject 愈；潜伏 bug-E `\pi` |
| math/0111203 | partial/clean | inject reject | 同上 | 策略拒（已除） | 全愈 |

## 签名与机理修正

- **无新 bug 类**。6 格 = 4×bug-B glue-debris + 2×latex209 策略拒（+1 潜伏 bug-E）。
- **bug-B 机理翻案**：此前记「LLM echo 侧」（模型回显时融合 `\item`+`<Cap>`）——本批 state.json 逐字证据证明是**管线侧**：cs 与译文首词间分隔空白在 chunk span 内被边缘 strip 吃掉。判据扩为 `\<cs><latin>`（含小写尾；中文起首免疫）。a6b58d4 把 gap 收归 literal run item 后该面已封死——`\\item(?=[A-Z])` splice 守卫仍可作为纵深防御但不是根修。
- 建议：4 格补跑 pipe-fix 验收 cs_targeted_fix 实战命中（条目按本跑加的未实战行使过）；hep-ph/9703228 重跑观察 `\pi` 复发则 rules.yaml 收「裸希腊字母进 prose」规则（fixloop lane）。无 pre-existing 翻案格——6 格全管线引入。

证据现场：`tmp/scout-realreg-2026-09-16/`。
