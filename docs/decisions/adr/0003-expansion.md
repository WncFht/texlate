# ADR-0003 宏展开机：Mouth/Gullet/Segmenter 三段 + 单遍即时展开

> **状态**：现行
> **日期**：2026-09-15（05 裁决 2）| 更新 2026-09-16（gullet/segmenter 独立包切替）

## 上下文

宏展开层是整条管线的 blocker：语料统计 95% 论文有宏（median 47 个）、51% 在正文内定义宏（只扫 preamble 必漏）、49% 宏体藏可译文本。设计上有两个争点：展开时机——扫描中建表 + 调用点即时展开（miniscanner 路线）vs 先建全表再二遍展开（unified-latex 路线）；以及展开深度——哪些 TeX 机制做、哪些不做。

## 裁决

**三段移植 plasTeX 的 mouth/gullet 分层 + 单遍即时展开**：

- Mouth：字节→token 流，`\input`/`\include` 中途压栈展平，makeatletter 可变 catcode 区按普通边界命令处理。
- Gullet：宏表 + 参数代入 + 不动点受限展开；六类定义语法（`\newcommand`/`\renewcommand`/`\def`/`\DeclareMathOperator`/`\newenvironment`/`\NewDocumentCommand`）。
- Segmenter：段落切分 + pieces/chunks/占位符（产出形态见 ADR-0002）。
- **铁律：splice 永远用调用点字节，gen>0 展开产物只做分类器输入，永不进 splice**。
- `\if` 结构化配对不求值：`\iffalse` 丢块 / `\iftrue`·已知旗标留块 / `\ifmmode` 取数学支 / 未知旗标整段字面；判定前置查宏表（`\ifb` 单位宏、`\ifAnonymous{T}{F}` 双参宏两个陷阱）；`\newif` 旗标不入条件栈。
- `\def` 定界参按 opaque 处理（15 例/7 文档，损失十几个调用点）。
- 不做：catcode 重定义/halign/active chars/完整 TeX 求值器（损失 ≤1/39）；绝不加载真实 `.sty`/`.cls`（plasTeX 教训：静默截断）。
- 资源限：gen≤32 / steps≤100k / inputs≤8 / dep≤4，实测余量充足。
- transparent 判据：宏体去控制序列后连续 letters ≥12–20 的宏，调用点参数参与分段；纯结构宏展开为等价命令后按该命令保护。

## 理由

- E4：plasTeX 的 Mouth/Gullet/Segmenter 三段是可移植的成熟设计，移植位已精确到文件级。
- E5 语料统计：**正文级 use-before-def = 0 例**（44 主文档 1351 次正常序；前置调用 14 处全在 preamble 且落在未知命令整体保护内，损失≈0）——单遍即时展开成立，二遍展开的多余一遍没有收益。
- 重定义场景：3 个实测事件全是「覆盖即新义」——单遍才符合 TeX 语义，二遍 last-wins 反而错。
- `\if` 含 prose 块仅 5 例（4 个 preamble 开关 + 1 个 `\iffalse` 死代码）——结构化配对即可，无需真求值。
- UBD 命中走未知命令保护 + 日志，留作新语料回归警报。
- 证据：主仓 `docs/05` E4/E5；调研档案 `research/latex/expansion-design.md`、`research/latex/expansion-timing.md`。

## 演变

- 2026-09-15：初版在 scanner 内嵌展开；E5 抓出的 `\input file` 裸文件名形式补识别。
- 2026-09-16：`gullet/`+`segmenter/` 独立包替换 scanner 内嵌形态，默认切换（splice 残留占位符 1524→0）；`argspec.json` 1820 条签名入包、审计期零装载 GAP。
- E20 回填三缺口：`/subfile{}` 展开且 `\end{document}` 只在顶层截停、巨型原子 chunk 超阈值二次切分、零文本论文优雅跳过走降级。

## 现状

实现落在 `latex/gullet/`（`core`/`expand`/`defcmd`/`entries`/`args`/`cond`/`classify`/`decls`/`input`/`names`/`tokutil`）与 `latex/segmenter/`（`core`/`mainloop`/`args`/`env`/`group`/`pending`）两包，`mouth.py`/`flatten.py` 供输入展平；`latex/data/argspec.json` 调度命令族与参数签名。此形态为唯一解析路径，早期 scanner 内嵌展开已退役。
