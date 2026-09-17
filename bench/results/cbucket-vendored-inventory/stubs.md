# Stub 骨架草案（许可禁 vendored 件的替身设计）

目标：让 fixloop `missing_file` 不再命中 + 编译尽量走得下去。stub 三档：**S0**=只喂 `\ProvidesXxx`+吞参（过 missing_file 门槛即可，正文宏缺失留给下游 verdict）；**S1**=再补高频 frontmatter/环境 no-op；**S2**=尽量语义保真（不追求，投入产出差）。所有 stub 首行打 `% texlate vendored stub — provides missing-file shim only` + `\PackageWarning{texlate-stub}{<file> is a shim}`，degraded 输出可被 scorecard 识别。

## class stub 通用骨架

```tex
% <name>.cls — texlate vendored stub (S1)
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{<name>}[texlate stub — original class not redistributable]
\ClassWarningNoLine{texlate-stub}{<name>.cls is a compatibility shim}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass[10pt]{article}
% —— frontmatter/期刊 cs no-op 层（按件补） ——
\providecommand{\journal}[1]{}
\providecommand{\received}[1]{}
\providecommand{\accepted}[1]{}
\providecommand{\publonline}[1]{}
\providecommand{\keywords}[1]{\par\noindent\textbf{Keywords:} #1\par}
\newenvironment{frontmatter}{}{}
```

## 逐件 stub 面

| 文件 | 档 | 最小提供面 |
|---|---|---|
| aa.cls | S1 | 既有 legacy shim 沿用——`\subtitle`、`\institute`、`\authorrunning`、`\titlerunning`、`\abstract` 五参型、`\keywords`、env `abstract`/`acknowledgements`/`onlinelink*` |
| tcilatex.tex | S1 | `\input` 目标件（tex 非 sty）：`\QZW`、`\QQQ`、`\TEX{text}`、`\TeXButton` 族、`\SWP` 注释宏、`\tcilatex` 内部 no-op——SWP 转储稿全靠这些存活 |
| JHEP3.cls | S1 | class 骨架 + `\preprint`、`\keywords`、`\arxivnumber`、`\collaboration`、env `abstract` |
| jheppub.sty | S0+ | `\jheppub` 投稿宏面：`\pubnumber`、`\psfig` 转发 graphics、section 字号重定义——S0 起步 |
| JHEP.cls | S1 | 同 JHEP3 面 |
| jinstpub.sty | S0+ | JINST 版式 cs：`\jinst`、`\titlepage` 件 |
| svjour.cls/svjour2.cls | S1 | class 骨架 + `\journalname`、`\titlerunning`、`\authorrunning`、`\institute`、env `abstract`/`acknowledgements` |
| svjour3.cls | S1 | 同上 + **吃掉 `.clo` 依赖**：真件 `\input{svglov3.clo}` 等 journal-option clo——stub 把 `\journalopt` 路由全部 no-op 掉，防二级 missing_file（svglov3.clo 不在清单也会炸） |
| diagrams.sty | S1 | `\diagram`…`\enddiagram` env：`\newenvironment{diagram}{\begingroup\catcode`\&=4 \diagram@swallow}{\endgroup}`——**DSL 体必须整体吞掉**否则体内容当正文排版出乱字；吞后插占位框 `\fbox{diagram}` |
| slashbox.sty | S1 | `\slashbox[t][b]{tl}{br}` → 退化为单元格文本 `#1/#2`（tabular 内安全）；`\backslashbox` 别名 |
| aipproc.cls | S1 | class 骨架 + `\classification`、`\keywords`、env `thearticle` |
| aaspp4.sty/aasms4.sty | S1 | ASP 会议 frontmatter：`\affil`、`\author`、`\aindex`、`\ssindex`、`\authorindex`、`\index` 安全转发、env `acknowledgments` |
| axodraw.sty | S1（+advisory） | `\AXO` 族、`\Line`、`\ArrowLine`、`\Photon`、`\Gluon` 等全部 no-op 吞参 + 占位 `\fbox{axodraw}`；advisory 口径建议用户迁 axodraw2 |
| conm-p-l.cls | S1 | ACM 老会议 class 骨架 + `\conferenceinfo`、`\CopyrightYear`、`\crdata`、env `abstract` |
| siamltex.cls | S1 | class 骨架 + env `abstract`/`keywords`/`AMS` |
| epl2.cls | S1 | IOP 系 class 骨架 + `\institute`、`\pacs`、`\abstract`（件头若 LPPL 则升 vendored 不建 stub） |
| undertilde.sty | S1 | `\utilde{x}` → `\underaccent{\sim}{x}` 或退化 `\widetilde{x}` |
| citesort.sty/texsort.sty | S0 | 若核头不过：`\citesort` 排序 no-op（cite 原样输出）——cite 族功能件 stub 成本极低 |
| eqsecnum.sty | S0 | 同上（`\eqsecnum` 计数器设置 no-op） |
| espcrc1/2.sty | S1 | 若核头不过：Elsevier CRC frontmatter `\hyphenation`、`\begin{frontmatter}` 系——espcrc 面小 |

## 机制注记（给 peer1）

- stub 落位 = ctan_fetch 同款 cwd 平铺（`.cls/.sty/.tex` 进 workdir 根，`TEXINPUTS` 的 `.` 恒首位命中）——无需引擎分支。
- stub 文件名必须等于缺件名（`JHEP3.cls` 大小写保留——kpsewhich 大小写敏感）。
- 命中名单驱动：fixloop `missing_file` payload 查 vendor 表 → 真件 drop / stub drop / pass-through。名单即 `inventory.jsonl` 的 `file`+`disposition` 两列。
- 建议 vendored 件带 SHA256 清单入库，stub 件统一头注记方便 scorecard 判 degraded。
