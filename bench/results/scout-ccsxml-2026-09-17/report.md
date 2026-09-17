# scout-ccsxml: 1706.07911 CCSXML exclusion-runaway — HEAD 复跑裁决

## Verdict: STALE（o164 已端到端救回）

- **最小 repro**：round1 归类 runaway_scan payload=`\next` →
  `detab_end_scanlines` 点火 → round2 clean PDF 出。
- **full stagerun zh 树**：4 rounds clean（detab + cjk_font_fallback +
  already_def_undefine 依次点火）。
- **parse 侧无罪**：vtex 与源字节一致（59787 B），`\begin{CCSXML}`/`\end`
  双侧 tab 缩进保留、XML 多行不折、warnings=[]。
- **旧判修正**：上轮「`\begin{CCSXML}` zh 树丢 tab」判词不准确——旧 zh
  文件双侧 tag 都带 tab；XML 折单行是 mock-translator payload 形，非
  serializer 新伤。

## 机理

源文件原形 `\t\end{CCSXML}`（行首 tab）触发 comment.sty gobbler 的
runaway 扫描——compile 层残留实跑仍在，但 fixloop 现 chain 完整兜回，
终判 clean。无 segmenter/serializer 面新伤。

（scout-ccsxml 交付原文由 leader 代落盘——subagent .md 写盘被协议拦。）
