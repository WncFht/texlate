# fixer-filemap — binhex.tex + numberofauthors verify-only 两格

任务 #32/#33（verify-only，目标均已前置修复，实测绘新残面）。Deliverables：`replay.py`（隔离复放驱动）、`replay-results.json`、`verdict-<pid>.json`×2、`cases.jsonl`；`work/`/`probe/` 复现树 gitignored。

## 1706.07911 (binhex.tex) — 目标 RESOLVED，新 residual

- binhex.tex 端到端解决：static_precheck 未再报缺；`.fls` 显示 `INPUT ~/texmf/tex/generic/kastrup/binhex.tex`×5（前期 install_file 装入 user texmf），编译越过该点。missing_file 签名路由实测无新问题（#32 闭合）。
- **新 residual（unfixable:other）**：`! File ended while scanning use of \next.` → Emergency stop。
  - 定位：comment.sty 的 CCSXML 排除扫描器不识别 **tab 缩进的 `\end{CCSXML}`**（src L111 源生 tab，非翻译引入）→ 扫到 EOF。最小复现：顶格过、ascii+tab 挂 —— 纯 tab 触发，与 CJK 无关。
  - 落地（批六）：新 head sig `runaway_scan` + `detab_end_scanlines` 规则（`\end{` 行去前导空白）。
  - 附带：static_precheck 把 acmart.cls 自带 `\InputIfFileExists{acmart-preload-hook.tex}` 误报 missing（benign 可选 hook）；CCSXML 的 XML payload 被 mock 译成 `这是译文`（xlat 臂产物，非编译阻塞）。

## 1306.0281 (numberofauthors) — 目标 HEALED，新 residual

- r1 `undefined_cs:numberofauthors`@l.186 → `cs_targeted_fix` polyfill 注入，`\providecommand{\numberofauthors}[1]{}` 落 main.tex:31（`\n` 前缀避开 docclass 行尾 seam）✓
- **新 residual（unfixable:early_eof）**：main.tex:235 `\maketitle` — `\@xfootnotemark doesn't match its definition` + `\__text_expand`/`Missing \endcsname` 风暴 → ~100 errs → Emergency。
  - 根因：splice 的 `acm_proc_article-sp.cls` 是 4 行 shim（`\LoadClassWithOptions{acmart}`）；老类作者块命令簇（`\alignauthor`/`\affaddr`/`\titlenote` 在 `\author{}` 外独立行文）在 acmart 的 `\__text_expand` 作者展开路径里爆炸 —— **shim 完备性缺口，超单 cs polyfill 范围**。
  - 路由：fixer-legacy-acm 接作者块族改写/stub 设计（shim body 扩展）。
