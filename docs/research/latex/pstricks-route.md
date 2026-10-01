# pstricks 工程编译路由探针：四路线实证

> **结论**：pstricks 工程编译失败的根因不是「必须 dvips」而是 vendored 旧 sty 遮蔽新内核的跨版本错配；摘除 vendored sty 后 xelatex + ctex 注入路线 0 错直出，为产品推荐路由。
> **状态**：现行（规则结论已落地为 fixloop `vendored_sty_shadow`/`non_utf8_source`/`pstricks` 路由族；规范见 `spec/compile.md`）
> **日期**：2026-09-14

## 1. 动机与语料画像

引擎矩阵（`engine-matrix.md`）中 0807.3917 一项 xelatex 修复后残留 126 个 undefined cs、tectonic 亦死，疑似「pstricks 必须 dvips」。本探针对该工程跑四路线验证。

语料画像：主文件 137KB，ISO-8859（latin-5 标记），全文仅 2 个高位字节（`\thanks` 的 `TÜBİTAK` 处，本身是 mojibake 源）。vendored 文件三件：`pstricks.sty v0.36(2008)`（根因件）、`IEEEtran.cls V1.6b(2002)`（系统无此 cls，唯一来源必须保留）、`stfloats.sty 1999`（系统有较新版但接口稳定）。图 = 12 个内嵌 `\input` 的 pstricks 绘图 + 2 个 EPS `\includegraphics`；无 .bib/.bbl 依赖（内嵌 thebibliography）。

## 2. 四路线结果

| 路线 | 配置                                              | 末遍 `!` 错                    | 判定                                      |
| ---- | ------------------------------------------------- | ------------------------------ | ----------------------------------------- |
| A1   | latex / xelatex，vendored sty 保留                | 128 / 126（undefined cs 级联） | FAIL                                      |
| A2   | latex + sty 摘除 + 补 `pst-tools.pro`[^ctan-pst]  | 2（`Invalid UTF-8 byte`）      | clean，dvips→ps2pdf 出 23 页              |
| A3   | A2 + 注入 `\usepackage[latin5]{inputenc}`         | 0                              | clean                                     |
| B    | xelatex + sty 摘除                                | 0                              | clean，直出 25 页（文本层 1×U+FFFD 静默） |
| C    | B + 注入 `\usepackage[fontset=fandol,UTF8]{ctex}` | 0                              | clean，32 页——产品管线完全兼容            |
| D    | xelatex `-no-pdf` → dvipdfmx                      | 0                              | clean（与 B 同链路）                      |

页数差异（23/25/32）是排版基准差异：latex 是 IEEEtran 原生排版，xelatex 字体映射微异，ctex 行距/字号重排——译文产品本来就重排，无关对错。

## 3. 根因机理（vendored_sty_shadow）

cwd 文件在 kpsewhich 搜索序最前 → `\usepackage{pstricks}` 拿到 vendored v0.36；v0.36 `\input{pstricks.tex}` 搜到的是 texmf 里的新内核 v3.22A(2025)；新内核的 `\pssetxlength` 等引用 v0.36 未定义的 `\ifpst@useCalc`/`\pscalculate` → undefined cs → else/fi 错位 → `Missing \begin{document}` 百余级联。latex 与 xelatex 的 128/126 错同根因。

对称面孔：矩阵首轮 xelatex 报 `pstricks.tex not found` 是因当时 texmf 尚未装 pstricks——同一签名族的两种形态：「找不到 .tex」或「找到但版本错配」。

反例校准：vendored `IEEEtran.cls` 是唯一来源 → 摘除必死；vendored `stfloats.sty` 旧于系统但接口稳定 → 摘除非必需。**规则不能逢 vendored 必摘，要按版本比较 + 错误触发。**

## 4. 编码不对称陷阱（复确认）

latex 对 latin-5 裸字节报 `Invalid UTF-8 byte` **错误**（可见信号）；xelatex 只 warning 并静默输出 U+FFFD（0 错但正文污染）。`!`≤3 判据在 xelatex 下有盲区——clean 判据必须加文本层 U+FFFD 扫描或 log `Invalid UTF-8.*replaced` warning 扫描。latex 路线的正解是注入 `\usepackage[latin5]{inputenc}`（2 错 → 0 错实测）。

## 5. 落地为规则

决策树：工程含 vendored `.sty/.cls` 且同名存在于 texmf → 比较 `\ProvidesPackage/\ProvidesFile` 日期，vendored 更旧则隔离（rename `.fixloop-iso`），同名不存在于 texmf 则保留；首选 xelatex + ctex 注入；tectonic 遇 pstricks 依赖由 `pstricks_route` 预检改派 xelatex，latex209（`\documentstyle`）+ pstricks 稿走 latex→dvips→ps2pdf 通道（前置 `pstricks_dvips_preflight` 检查 `pst-tools.pro` 等 `.pro` 件齐全）。

对应 fixloop 规则（均已落地，见 `spec/compile.md` 与 `fixloop/rules/85-shim.yaml`、`30-route.yaml`）：

- **R1 `vendored_sty_shadow`**（85-shim.yaml，loop 相 order 150）：触发 = loop 内 `undefined_cs`/`already_def` 类错误 + `vendored_shadow` 条件（builtin 探测工程内副本 `\ProvidesPackage/\ProvidesFile` 日期 < texmf 同名件——日期比较收在 condition 里，无独立预扫臂）；动作 = rename `.fixloop-iso` 隔离重编（`.sty/.cls`，biblatex 同包伴随的 `.def/.bbx/.cbx` 等整组隔离）；texmf 无同名件（唯一来源）条件不中不摘。本例收益 126/128 err → 0/2 err，零成本 rename 不依赖网络，应为最高优先级规则之一。
- **R2 `non_utf8_source`**：预扫 UTF-8 decode 失败或 log `Invalid UTF-8 byte` → xelatex 路线上游先转码、latex 路线注入探测编码的 inputenc。
- **R3 `pstricks_route` + `pstricks_dvips_preflight`**（30-route.yaml，落地为两条而非单条 fallback）：`pstricks_route`（precheck 相 order -10）= 源码行锚命中 pstricks/pst-*/pspicture/`\psset` 依赖且引擎 tectonic → 预检路由 xelatex（tectonic 无 PS 可行路径）；`pstricks_dvips_preflight`（gate 相 order 0，先于 `latex209_reject`）= `\documentstyle`+pstricks 依赖的 latex209 籍走 latex+dvips 前预检 `pst-tools.pro` 存在，缺则 REJECT note 附 advisory。
- **R4 `latex209_reject`**（30-route.yaml，gate 相 order 1）：行锚 `\documentstyle` 或 COMPAT_SHIM 标记确认的 2.09 籍 → 路由拒绝转 latex+dvips 通道——与原稿「2.09 不应走 dvips」的设想相反，落地口径里 latex+dvips 正是 2.09 残留籍的可行通路（`latex209_upgrade` 在 precheck 已转化一批，仍出 209 类错误者归此通道），pstricks 依赖者在 order 0 先经 `pstricks_dvips_preflight` 记 `.pro` 预检。

环境注记：探针期 texmf 为 BasicTeX 精简发行版（dist 无 pstricks/IEEEtran，经 usermode 装），且缺 pstricks.tex 2025 新增依赖 `pst-tools.pro`（从 tlnet `pst-tools` 归档补进 cwd 即通）——完整 TeX Live 不缺，但 fixloop 的 missing_file 链对 `.pro` 同样适用（包名 = tlnet 归档名）。

### 参考文献

[^ctan-pst]: CTAN. pst-tools — pstricks support files. [ctan.org/pkg/pst-tools](https://ctan.org/pkg/pst-tools)
