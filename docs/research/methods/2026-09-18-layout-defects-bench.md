# 版式损伤 bench：zihao 字号膨胀与不可断段落——机制、量化与修复

> **结论**：对「表格溢出/图片漂移留白/多栏破坏」版式损伤做成体系实证 bench（en/zh 双臂 log 度量 + ink 渲染对照），定位出两个可修复的系统性损伤源并已部署：① ctex 默认 `scheme=chinese` 在未收到显式字号选项时把全体字号重映射到中文字号 bp 尺寸（5 号=10.53937pt，+5.4%）——修法注入 `zihao=false`；② CJK 散文夹不可断内容（长 inline math/hash/URL/作者块）前两遍断行失败 → 段落 overfull——修法注入 `\AtBeginDocument{\emergencystretch=1.5em}`。另有若干候选假设被证伪（CJK 落进 display math 的「34%」是朴素正则误判、浮动体丢失 zh 新增 0 例、最大单点出血是 biber 版本错配非版式缺陷）。
> **状态**：现行（双修复已落地产品代码：`compile/inject.py` 的 `CTEX_LINE` 含 `zihao=false`、`OVERFLOW_MITIGATION` 块含 emergencystretch；度量件 `bench/py/report/layout_bench.py`）。数据为 2026-09-18 口径时点证据。
> **日期**：2026-09-18（2026-09-20 迁入重编）

## Bench 构成

真实臂：301 篇真实 arXiv 论文过整链（normalize → 网关真翻 → prepare_chinese → xelatex）的四类工作区（pipe-xel/base-xel/base-rescue/pipe-fix；en 基线 base-xel 153 篇 + stagerun build-base 补齐）。Mock 臂：stagerun-loop1 批次 4,994 篇，翻译用「这是译文」占位符——结构级损伤可信、文本宽度损伤会高估。度量件 `layout_bench.py`（metrics/features/ink/report 四子命令）。

## 根因一（已修复）：ctex `zihao=5` 全局字号膨胀

机制链钉死到 ctex 源码：注入行 `\usepackage[fontset=fandol,UTF8]{ctex}` 不带字号选项时，默认 `scheme=chinese` 走 `ctex-scheme-chinese.def`——`\g__ctex_font_size_int` 仍为初值 −1 时被强设为 0 → 加载 `ctex-c5size.clo` → `\normalsize`…`\tiny` 全体按 `\ctex_set_font_size:Nnn` 重映射到中文字号 bp 尺寸（5 号=10.5bp=10.53937pt，+5.4%）。实测 `\f@size=10.53937`、`\f@baselineskip=12.64725`（vs 类原生 10pt/12pt），数学字体同比例放大（`cmsy10 at 10.53937pt`），版式几何全面变宽变长。

触发条件是「`\documentclass` 未带全局 pt 字号选项」——类选项 `10pt/11pt/12pt` 会被 ctex 当作显式字号（`ctex.sty` 置 int=2 跳过重映射）。与文档类是否标准无关：`article` 裸写一样中招（「ctex 只祸害非标准类」的判断是错的，`\@ifclassloaded{article}` 那段只管 heading 方案不管 zihao）。Mock 语料交叉验证：无字号选项的论文 2,267 篇命中 zihao 尺寸、带字号选项的 1,749 篇干净（110 篇例外主要是 features 抽取把子文件选项记到主文档头上）。

命中率：真实臂 89/301（29.6%）、mock 臂 2,377/4,994（47.6%）的 zh log 出现字号 bp 尺寸；en log 4,994 篇仅 1 篇（类自带），归因干净。

A/B 修复效果（89 篇真实臂全体，改行重编译）：

- 相对 en 的总页数超出：+249 → +67（−73%）；zh>en 的论文 65 → 35 篇；66 篇变短、3 篇变长、20 篇不变。
- overfull 总数：en=266、zh-old=495、zh-new=346（相对 en 的超出量 229 → 80，−65%）；45 篇改善、8 篇略恶化（多为临界翻转）；of_max 向 en 收敛 41/54。
- 页数 ±1 内对齐 en：43 → 47 篇。
- 典型：`0905.2110` 对齐 overfull 53.86→26.33pt（与 en 完全一致）、22→21 页；`1803.00181` 51→38 页（en 42）；`2211.04495` 33→21 页（en 28）。

部署：`CTEX_LINE` 加 `zihao=false`（唯一注入点）。`scheme=plain` 备选被否——`zihao=false` 保住中文方案红利（`\refname`=参考文献、`\tablename`=表、CJK 缩进约定），只杀字号重映射。

## 根因二（已修复）：CJK 散文夹不可断内容 → 段落 overfull

残余损伤的主体：长 inline math / 不可断串（hash、URL、作者块）嵌在 CJK 散文里，前两遍断行失败。真实臂非 zihao 族 residual overfull 超出 en 仅 +57（13/43 篇受损），但单点可以很肥（`2410.17958` 一处 137pt、`2203.13109` 一处 104.6pt——均为 CJK 散文中的长数学行）。

修复：注入块追加 `OVERFLOW_MITIGATION` = `\AtBeginDocument{\emergencystretch=1.5em}`（第三遍断行给虚拟伸缩量；只救本来要炸的段，不动排得好的段；`\AtBeginDocument` 包裹保证晚于类自设）。16 篇重灾 offender A/B：of_n 205→155（−24%），137pt/73.8pt 两处巨型溢出血崩清零，页数不变，无回退。

## 证伪与归因

- CJK 落进 display math：此前「34%」是朴素正则把 `$$`-close+散文+`$$`-open 误判；TeX 语义态机复扫真值 ≈0–1/301，非缺陷源。
- 对齐/公式 overfull 多为 en 固有：36 篇 zh 超标里大部分 en 臂同坏或更坏（`0707.2318` 双臂同 74.8pt；`1003.4522` en 65.7 > zh 53.2）；真 zh 加重仅个位数，且大半由 zihao 膨胀解释。
- 最大单点出血（`1502.02341` 686pt）是 biber/biblatex 版本错配（`.bbl` 由异版 biber 生成→`\blx@dlist@type` 未定义→文献段整段塌方），en 臂同损 585pt——基础设施问题（tectonic biber mismatch，另案），不是版式缺陷。
- 浮动体丢失 zh 新增 0 例；`TeXlate-Float-Fit` 在 zh 臂触发 196 次（FLOAT_SIZING 机制在干活）。
- mock 臂文本宽度损伤系统性高估：「这是译文」等宽占位串与真实译文密度不同；多栏（`multicols`）论文的 overfull 主要是「窄行宽 + 不可断内容」同族，未见栏塌/逃逸级破坏。

## 残留缺陷清单（已知未修）

- 对齐/公式超宽残余：zihao 修复后相对 en 仍有 +80 超出——要再压需数学级断行（风险高，暂不动）。
- 不可断串 overfull：emergencystretch 只解一部分（hash 型作者块、`2112.00045` 1→6 页爆是翻译产物非版式）。
- 翻译驱动的页数增长：CJK 全宽字使真翻页数可涨（`2403.15096` 73→82，非 zihao 所能解）。

## 方法学要点

- en/zh 双臂对照是归因的关键——只看 zh 臂会把 en 固有缺陷（biber 错配、类本身排版差）误算成管线损伤；「相对 en 的超出量」才是管线净效应。
- 机制链钉到上游源码（ctex `.def` 逐行读）再动手修，避免「对症状打补丁」；触发条件用 mock 大语料交叉验证（4,994 篇分层命中率 vs en 臂基线）。
- 朴素正则计数会被 LaTeX 语法骗（`$$` 配对误判）；语义级复扫（TeX 态机）才能给真值——「测量工具本身先过校验」。
