# 端到端 mock 管线实验（一次性过程件）

> **结论**：机械链路（解析→占位符→mock 译→拼接→ctex 注入→xelatex 重编译）16/16 项目出 PDF；实验同时实锤两件事——「出了 PDF ≠ 成功」（静默损坏 0 编译错误）与「校验层必须独立于编译层」（v0 校验器 132/132 捕获幻觉损坏）。
> **状态**：时点证据（2026-09-14 口径）；结论已沉淀进 `src/texlate/latex/`、`validate/`、`compile/` 实现
> **日期**：2026-09-14

复现 hjfy.top 机械链路验证：miniscanner 解析 → 占位符保护 → 分块 → mock 翻译（无 LLM，确定性 mock）→ 译文拼接 → ctex 注入 → xelatex 重编译。目的是验证**机械链路**正确性并枚举失败模式；实验代码与结果均未入库（一次性 scratch 现场）。

## 验证结论

- **链路走通**：16 个代表性 arXiv 项目（amsart/revtex/IEEEtran/acmart/elsarticle/subfiles/103 文件 book/LaTeX 2.09 等），mock 翻译 + ctex[fandol] 注入后 16/16 产出 PDF，0 FAIL；中文确实进 PDF（页数普遍上涨）。
- **identity + 占位符守恒**：111 个 .tex、9945 chunks、42341 个占位符出现，`reconstruct(原文) == 原文` 字节级一致 111/111，译文占位符计数 src==zh 全等，零泄漏。
- **per-file 原地翻译**模式正确处理 subfiles/multi-`\input`/多文件项目，无需 flatten。
- **注入点定位算法**（注释感知 + 括号配平）对注释掉的、多行跨页的、选项穿插注释的 `\documentclass` 全部找对。
- **错误计数必须双格式**（`^!` + file-line-error `file:line:`），只数 `!` 会漏掉全部引擎级错误。
- **tlmgr `--usermode` fixloop** 能救缺包项目（21 种缺失文件实测），`hyperxmp` 类 not-relocatable 包需要手工 `.ins` 生成兜底。

## 修复项与关键失败模式

- **F1 扫描器 `_args` 吃掉 `\` 切断控制序列名（最恶性 bug）**：未知命令按 nargs=6 读参时把下一命令的 `\`+字母逐字符吃成"参数"。全语料 39 项目 **3452 处切断**，其中 **1053 处切口落在可译 chunk 内**（`\begin{abstract}` 被切成占位符 + 残留的 `n{abstract}`，环境整个消失，且 identity 检查对此不可见）。修复：单 token 参数只在紧邻且非 `\` 时取，补丁后 0 处。
- **F6 LaTeX 2.09 路由是静默死路（最严重产品级失败）**：`\documentstyle` 文档注入 `\usepackage{ctex}` 报"LaTeX2e command in LaTeX 2.09 document"，xelatex nonstopmode 继续跑，**PDF 照出但 ctex 从未加载**——5954 条 Missing character、0 中文进 PDF。verdict 体系必须加「译文渲染确认」（日志 Missing character 计数或 PDF 字体表含 CJK 字体），路由层须在 `\documentstyle` 处拒绝或走转换。
- **F10 译器幻觉对照（Mock B）**：4 项目注入 132 处损坏译文，**4 个全部仍产出 PDF**；56 处丢占位符损坏产生 **0 条编译错误**（cite/公式/`\bibitem` key 静默消失），76 处断花括号产生 ~78 条错误。编译前校验器 132/132 = 100% 捕获——两个方向证明校验层必须独立存在。
- 其余机械类修复：CJK 粘连（`\item这是` 合成未定义控制序列，需 `\cmd`+CJK 间插空格）、bare `\input file` 文件名进 chunk、bare 尺寸参数（`\vglue -10mm`）混入 chunk、定界符命令（`\left(`/`\\[2mm]`）参数泄漏、非 UTF-8 源（latin-5 需 chardet 而非 errors=replace）。

## 未覆盖项（留给真实 LLM 阶段）

mock 假设「位置忠实」译器（占位符原地保留、控制序列不动），真实 LLM 不满足：**占位符位置敏感性**（`\bibitem` 前缀、`\href` 邻接、verbatim 内 `%` 变活注释符）、译文长度对 `\hbox`/caption/下标的编译影响、chunk 语义完整性、罕见字字体覆盖、bibliography-heavy 多 pass 收敛——均未覆盖。
