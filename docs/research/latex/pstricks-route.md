# pstricks 工程编译路由探针：四路线实证

> **结论**：pstricks 工程编译失败的根因不是「必须 dvips」而是 vendored 旧 sty 遮蔽新内核的跨版本错配；摘除 vendored sty 后 xelatex + ctex 注入路线 0 错直出，为产品推荐路由。
> **状态**：现行（规则结论已落地为 fixloop `vendored_sty_shadow`/`non_utf8_source`/`pstricks` 路由族；规范见 `spec/compile.md`）
> **日期**：2026-09-14

## 1. 动机与语料画像

引擎矩阵（`engine-matrix.md`）中 0807.3917 一项 xelatex 修复后残留 126 个 undefined cs、tectonic 亦死，疑似「pstricks 必须 dvips」。本探针对该工程跑四路线验证。

语料画像：主文件 137KB，ISO-8859（latin-5 标记），全文仅 2 个高位字节（`\thanks` 的 `TÜBİTAK` 处，本身是 mojibake 源）。vendored 文件三件：`pstricks.sty v0.36(2008)`（元凶）、`IEEEtran.cls V1.6b(2002)`（系统无此 cls，唯一来源必须保留）、`stfloats.sty 1999`（系统有较新版但接口稳定）。图 = 12 个内嵌 `\input` 的 pstricks 绘图 + 2 个 EPS `\includegraphics`；无 .bib/.bbl 依赖（内嵌 thebibliography）。

## 2. 四路线结果

| 路线 | 配置 | 末遍 `!` 错 | 判定 |
| --- | --- | --- | --- |
| A1 | latex / xelatex，vendored sty 保留 | 128 / 126（undefined cs 级联） | FAIL |
| A2 | latex + sty 摘除 + 补 `pst-tools.pro`[^ctan-pst] | 2（`Invalid UTF-8 byte`） | clean，dvips→ps2pdf 出 23 页 |
| A3 | A2 + 注入 `\usepackage[latin5]{inputenc}` | 0 | clean |
| B | xelatex + sty 摘除 | 0 | clean，直出 25 页（文本层 1×U+FFFD 静默） |
| C | B + 注入 `\usepackage[fontset=fandol,UTF8]{ctex}` | 0 | clean，32 页——产品管线完全兼容 |
| D | xelatex `-no-pdf` → dvipdfmx | 0 | clean（与 B 同链路） |

页数差异（23/25/32）是排版基准差异：latex 是 IEEEtran 原生排版，xelatex 字体映射微异，ctex 行距/字号重排——译文产品本来就重排，无关对错。

## 3. 根因机理（vendored_sty_shadow）

cwd 文件在 kpsewhich 搜索序最前 → `\usepackage{pstricks}` 拿到 vendored v0.36；v0.36 `\input{pstricks.tex}` 搜到的是 texmf 里的新内核 v3.22A(2025)；新内核的 `\pssetxlength` 等引用 v0.36 未定义的 `\ifpst@useCalc`/`\pscalculate` → undefined cs → else/fi 错位 → `Missing \begin{document}` 百余级联。latex 与 xelatex 的 128/126 错同根因。

对称面孔：矩阵首轮 xelatex 报 `pstricks.tex not found` 是因当时 texmf 尚未装 pstricks——同一签名族的两副面孔：「找不到 .tex」或「找到但版本错配」。

反例校准：vendored `IEEEtran.cls` 是唯一来源 → 摘除必死；vendored `stfloats.sty` 旧于系统但接口稳定 → 摘除非必需。**规则不能逢 vendored 必摘，要按版本比较 + 错误触发。**

## 4. 编码不对称陷阱（复确认）

latex 对 latin-5 裸字节报 `Invalid UTF-8 byte` **错误**（可见信号）；xelatex 只 warning 并静默输出 U+FFFD（0 错但正文污染）。`!`≤3 判据在 xelatex 下有盲区——clean 判据必须加文本层 U+FFFD 扫描或 log `Invalid UTF-8.*replaced` warning 扫描。latex 路线的正解是注入 `\usepackage[latin5]{inputenc}`（2 错 → 0 错实测）。

## 5. 落地为规则

决策树：工程含 vendored `.sty/.cls` 且同名存在于 texmf → 比较 `\ProvidesPackage/\ProvidesFile` 日期，vendored 更旧则隔离（rename `.VENDORED`），同名不存在于 texmf 则保留；首选 xelatex + ctex 注入；latex→dvips→ps2pdf 作兜底（仅当 xelatex 仍失败——pst-* 特性仅 dvips 支持——或要求保真原版排版；前置 preflight 用 kpsewhich 检查 `.pro` 文件齐全）。

对应 fixloop 规则（均已落地，见 `spec/compile.md`）：

- **R1 `vendored_pkg_shadow`**：触发 = 预扫同名 vendored 更旧，或 log undefined cs 级联 >10 且首错落在 vendored 包加载后；动作 = rename `.VENDORED` 重编；唯一来源不摘。本例收益 126/128 err → 0/2 err，零成本 rename 不依赖网络，应为最高优先级规则之一。
- **R2 `non_utf8_source`**：预扫 UTF-8 decode 失败或 log `Invalid UTF-8 byte` → xelatex 路线上游先转码、latex 路线注入探测编码的 inputenc。
- **R3 `pstricks_dvips_fallback`**：pstricks/pst-* 依赖且 xelatex 经 R1 后仍失败 → 切 latex→dvips→ps2pdf + `.pro` preflight。
- **R4 对 `latex209_reject` 的补充**：`\documentstyle` 工程不应路由 latex+dvips；latex+dvips 的正确用途是 pstricks/EPS 兜底而非 2.09 救命——路由条件须写清「仅当非 latex209 且含 pst-*/EPS 依赖」。

环境注记：探针期 texmf 为 BasicTeX 精简发行版（dist 无 pstricks/IEEEtran，经 usermode 装），且缺 pstricks.tex 2025 新增依赖 `pst-tools.pro`（从 tlnet `pst-tools` 归档补进 cwd 即通）——完整 TeX Live 不缺，但 fixloop 的 missing_file 链对 `.pro` 同样适用（包名 = tlnet 归档名）。

### 参考文献

[^ctan-pst]: CTAN. pst-tools — pstricks support files. [ctan.org/pkg/pst-tools](https://ctan.org/pkg/pst-tools)
