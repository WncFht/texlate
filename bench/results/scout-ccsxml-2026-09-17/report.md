# scout-ccsxml: 1706.07911 CCSXML exclusion-runaway — HEAD 复跑裁决

2026-09-17, scout-ccsxml. READ-ONLY probe; scratch `tmp/scout-ccsxml/`；无 src/ 改动、零 git 状态命令。

## Verdict

**STALE at HEAD——o164 端到端救回**（`runaway_scan` 分类 rules.yaml:329 + `detab_end_scanlines` rules.yaml:3607，落点 `9d9ebe5`）。底层机理在 compile 层仍真实复现（源稿自带、parse 侧逐字节忠实保留——这是对的），但 fixloop 现能归类并在环内 detab 掉肇事 `\end{` 行；最小 repro 与原样 stagerun zh 树双路均 **clean**。

## 机理（修正版）

`sample-sigconf.tex` L68-L111：`\t\begin{CCSXML}` … `\t\t<ccs2012>` 多行 XML … `\t\end{CCSXML}`——全部源生 tab 缩进。`acmart.cls:1227-1228` `\RequirePackage{comment}` + `\excludecomment{CCSXML}`；comment.sty 排除 gobbler 要求 `\end{env}` 行**顶格**，tab 引导的 `\end{CCSXML}` 永不匹配 → 吞扫至 EOF → `! File ended while scanning use of \next` → job aborted 无 PDF。旧 zh 树里 XML 折单行是 mock-translator 填充形（`[[CHUNK_2]]`→单行 `这是译文…`），非 serializer 折叠——且与 gobbler 无关（它只认 `\end` 行）。

两条前提修正：

- stagerun-loop1 zh 件（`bench/results/stagerun-loop1-2026-09-16/work/1706.07911/zh/sample-sigconf.tex` L97/L99）`\begin`/`\end{CCSXML}` **双侧 tab 都保留**——「丢 tab」判词有误；`\end` 上保留的 tab 正是引爆点。
- `early_eof` 是 compile/e2e 层败类标签，非 `ScanWarning` kind——`res.warnings` 无此 kind（本案 0 告警）。

## Parse 侧 HEAD（`parse_file` v2 默认）

`uv run python tmp/scout-ccsxml/probe.py` 于 `bench/corpus_v3/1706.07911/extracted/sample-sigconf.tex`：

- `len(res.vtex) == len(source) == 59787`——vtex **字节一致**；`\begin{CCSXML}` 保 `\t` 缩进、XML 多行不折。
- `res.warnings == []`。
- env 周 pieces：`LITERAL [2104,2121) '\begin{CCSXML}\n\t\t'` | `CHUNK_REF [2121,3918) env=CCSXML [[CHUNK_2]]`（XML 体）| `LITERAL [3918,3920) '\n\t'` | `LITERAL [3920,3932) '\end{CCSXML}'`。
- `protected_tex` 出 `\begin{CCSXML}\n\t\t[[CHUNK_2]]\n\t\end{CCSXML}`——`\end` tag 在 chunk 外 LITERAL piece，serializer 恒独占行；仅引导 tab（源生）随行。
- v1 臂（`TEXLATE_NO_EXPAND=1`）：同 env 布局、零告警。

parse/serialize 双侧干净——伤从来不在此面。

## Compile 侧 HEAD（真 `fixloop()`，xelatex）

`uv run python tmp/scout-ccsxml/drive_fixloop.py`（全 cell dump `tmp/scout-ccsxml/cellA2.json`）：

- **Case A** 最小 repro（fixer probe 形：acmart + `\t\begin{CCSXML}` + 折行 payload + `\t\end{CCSXML}`）：round1 `category=runaway_scan, payload=\next, pdf=false` → `detab_end_scanlines` 点火（`rewrite in 1 files`，`\end{CCSXML}`→列 0）→ round2 clean，PDF 17554 B。
- **Case B** stagerun-loop1 zh 树原样拷贝：`detab_end_scanlines` + `cjk_font_fallback`（4 字→FandolSong）+ `already_def_undefine`（`\liningnums`）→ 4 rounds **clean**，PDF 4.64MB。

`detab_end_scanlines`  gated `when: {category: runaway_scan}`——两案先真实复现 runaway 再被救回，非旁路。

## Caveats

- 该规则 detab **所有** `\end{` 行（rules.yaml:3605 已接受的副作用：verbatim/minted 字面 `\end` 行被去缩进——仅版式位移）。
- XML 体（下略——交付消息截断点，以上为主体）。

（交付原文由 leader 代落盘——subagent .md 写盘被协议拦。）
