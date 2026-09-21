# ADR-0005 中文注入与源码归一化：ctex 默认 + xeCJK 降级 + normalize 手术层

> **状态**：现行
> **日期**：2026-09-15（05 裁决 12/16）| 更新 2026-09-17（inject 先走 upgrade_209）

## 上下文

英文 LaTeX 工程要出中文 PDF 需要注入 CJK 支持。hjfy 用 `\usepackage[fontset=windows,UTF8]{ctex}`；texglot 则弃 ctex 改走 xeCJK+fontspec（理由是类冲突）。同时 arXiv 真实工程带大量 pdfTeX 时代残留——`[utf8]{inputenc}`、`[T1]{fontenc}`、OT1 字体声明、`px` 单位、`\pdfinfo/\pdfoutput`——在 XeTeX 下会报错或行为漂移；而 LaTeX 2.09 时代的 `\documentstyle` 工程注入 ctex 是最坏静默失败（ctex 不加载、PDF 照出、0 中文字节）。

## 裁决

- **默认 ctex `[fontset=fandol,UTF8]` 注入**——hjfy 同款、双引擎实测可编译、白拿节名汉化；服务端可切 fontset。注入缝两个：`\documentclass{}` 后（字体系块）+ `\begin{document}` 前（兼容块），两条注入路径共用。
- **xeCJK+fontspec 为降级路径**：ctex 与类冲突签名命中时由 fixloop 或探测编译切换到同缝 xeCJK 注入。
- **新增归一化层 `compile/normalize.py`**（texglot「源码归一化」先例落地）：visible_tex 遮蔽视图定位（verbatim/comment/`\verb` 变等长空格、`\n` 保留行号不变）+ 编辑列表逆序 span 替换。**无条件手术** = 剥 inputenc/fontenc、pdftex→xetex 驱动选项改写、`px`→`\pdfpxdimen`、`\pdfinfo/\pdfoutput` 删除、legacy CJK→xeCJK、OT1/T1 族→fontspec+TeXGyre；**条件手术留 fixloop**（microtype/times→newtx 等）——两边不得重复改同一处。
- `\documentstyle` → 注入层兜底拒（`inject_reject:latex209`），路由语义见 ADR-0006。
- 条件注入件：FLOAT_SIZING 仅在有 figure/table 时注入、TABLE_FITTING hook threeparttable、PIXEL/XETEX 兼容块按签名。

## 理由

- E9/E10：ctex 注入对 12 项目 0% 破坏；E10 hep-th 实证 `\documentstyle` 注入是最坏静默失败（pdf~ 出 8 页、5954 Missing character、0 中文字节）——必须有拒注入与「中文实际进 PDF」判定兜底。
- E12：texglot 引擎兼容手术（XeTeX 前导/OT1→TU/剥 inputenc）证明归一化层思路可行且必要。
- 证据：主仓 `docs/05` E9/E10/E12；调研档案 `research/latex/engine-matrix.md`、`research/latex/texglot-patterns.md`。

## 演变

- 2026-09-17：`inject_cjk` 遇 `\documentstyle` 先走 `upgrade_209` 转换器尝试升级文档类，仅不可转（ds@ 类/no_target）才抛拒——「禁止注入」收敛为兜底语义。

## 现状

实现落在 `compile/`：`inject.py`（`inject_cjk` 双缝 + 条件块，遇 `\documentstyle` 调 `upgrade_209`）、`normalize.py`（归一化手术）、`latex209.py`（2.09 识别/`upgrade_209` 转换/gate）、`transcode.py`（非 UTF-8 源码转码）、`cjkmap.py` + `cmaps/`（GB1 ToUnicode 资产，CJK 文本抽取校验用）、`mask.py`/`seams.py`（遮蔽与缝定位）。两条注入路径与同缝切换均已接线产品链。
