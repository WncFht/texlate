# undefined_cs 族归因（leader 批量归因 · scout-ucs 复核待并入）

> 口径：compile.jsonl 末条 `verdict.category==undefined_cs` = **382 格**
> （票面 284 是 triage 抽样口径；另有 7 格末态 unfixable:undefined_cs 属
> 59-fail 集，归 scout-fail59 逐格归因）。全部 partial 有 pdf，非 fail。

## 方法

末条 compile record `verdict.payload` + splice 日志 `Undefined control sequence`
行逐格提取冒犯 cs，按签名聚合分簇。

## 簇分解

| 簇 | 格数 | 机理 | 归属 |
|---|---|---|---|
| `csname*NoStop` 融合 | 48 | REVTeX .bbl 内 `\csname bibitemNoStop\endcsname` 空格被吞 → `\csnamebibitemNoStop`；1206.0279 splice:537 实锤。bug-B cs+latin 融合超簇成员 | fixer-slots / segmenter 半侧（`a6b58d4` gap-bytes 修复已落，重翻即愈） |
| `bibitem` 系 | 20 | .bbl/natbib 域 cs 断裂同族 | 同上 |
| 融合断 cs 长尾 | ~170 | `\rm m`→`\rmm`、`\nnP`、`\item<X>` 型 PH-in-cs 与 cs+latin 融合（bug-B / modec mid-cs 截断同机理） | fixer-slots + l0 `\\[a-zA-Z]*\[\[PH` 检查（spec 已出 `c4db001`，路由 1d） |
| 结构性继发 | ~40 | 上游 error 中断后宏未定义的级联误报（`! Undefined` 打到宿主宏） | 上游修复后自消，不立项 |
| shim 替身宏面缺口 | ~35 | shim body 缺真包导出宏：`\corauth`、`\smartqed`（elsart 系）、`\submitto`（svjour 系）、`\eqntopsep`（elsart shim）、`\iopams`/`iopamstrue`（iopart shim） | **数据提案**见下——shim body 扩列，归 rules.yaml owner（项目体验方式）路由 |
| `\DeclareUnicodeCharacter` | 11 | normalize/引擎侧 unicode 原语在包内未定义（inputenc 未载的 xelatex 文档） | 已落：cs_table polyfill `ea0c73e`（lccode 惯用法），末条多已愈，残格待重跑 |
| 上游 QQQ/真缺宏 | ~30 | 稿本身引用不存在的宏（arXiv 常见上游伤） | wontfix 候选，逐格核 |

## 数据提案（不直写，报 owner）

elsart shim body 增补：`\newcommand{\corauth}[2][]{}`、`\newcommand{\smartqed}{}`；
svjour 系 shim 增补 `\submitto`；elsart/iopart shim 增补 `\eqntopsep`、
`\iopams`/`\iopamstrue`。**属 shim_map body 数据修订（非 append 新键）——
按纪律提交 owner 评审，不直接写。**

## 与已落修复的交叠

`3820f18` cs_targeted_fix 实战已证 hlineCd/pari/parii/itemNGA/itemBalakrishnan
5 键 4/4 clean；`a6b58d4` segmenter gap-bytes 修复把 cs+latin 融合从管线侧掐断
——本族 ~240 格（融合两簇）重翻/重跑后预期大幅消减，是当前 partial 池里
**最容易回收的存量**（优先级建议：rerun > 新规则）。
