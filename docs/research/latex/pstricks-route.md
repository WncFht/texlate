# pstricks 工程编译路由探针：0807.3917 四路线实证

- 日期：2026-09-14
- 语料： `bench/corpus/0807.3917/` （只读；拷贝至 `tmp/exp/pstricks-probe/{A1,A2,A3,B,C,D}/` 实验）
- 判据：沿用引擎矩阵 —— clean = 出 PDF 且末遍 log `!` 错误 ≤3；每步编译上限 240s（实际所有单步均 <10s)
- 动机：引擎矩阵中该项 xelatex 修复后 126 undefined cs（自带 2008 pstricks.sty 遮蔽新版内核）, tectonic 亦死；验证 latex+dvips 与 sty 摘除两条出路

## 0. TL;DR

| 结论                                 | 数据                                                                                                                                                                                                                                       |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **根因不是"pstricks 必须 dvips"**    | vendored `pstricks.sty v0.36(2008)` + 用户 texmf `pstricks.tex v3.22A(2025)` **跨版本错配**: 旧 wrapper 未定义新内核依赖的 `\ifpst@useCalc`/`\pscalculate` 等 → 编译期中后段 undefined cs 级联。**latex 128 err / xelatex 126 err 同根因** |
| **摘除 vendored sty 后两条路线都活** | xelatex 0 err 直出 25 页 PDF; latex→dvips→ps2pdf 出 23 页 PDF（仅 2 个 Invalid UTF-8 错）                                                                                                                                                  |
| **TeXlate 推荐路由 = C**             | sty 摘除 + xelatex + ctex 注入： **0 err, 32 页 PDF** —— 与产品管线（中文输出）完全兼容，不需 dvips                                                                                                                                        |
| latex+dvips 是合格兜底               | pstricks 原生 PostScript 路径；但需要 .pro header 齐全（本机 BasicTeX 用户 texmf 缺 `pst-tools.pro`, 从 tlnet `pst-tools.tar.xz` 补进 cwd 才通）                                                                                           |
| **编码不对称陷阱**                   | latex 对 latin-5 裸字节报 `Invalid UTF-8 byte` **错误**（可见信号）; xelatex 只 warning 并静默输出 U+FFFD(0 err 但正文 `TÜBİTAK→T�UB�ITAK`)。**'!'≤3 判据在 xelatex 下有盲区** —— 已在引擎矩阵报告中预警，本次复确认                       |

## 1. 环境

| 工具                         | 版本                                                  | 备注                                                                                                                              |
| ---------------------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| latex/dvips/dvipdfmx/xelatex | TeX Live **2026basic** (/usr/local/texlive/2026basic) | **BasicTeX 精简发行版** —— dist 无 pstricks/IEEEtran                                                                              |
| ps2pdf/gs                    | homebrew                                              | ps2pdf 警告 transparency ignored, 无碍                                                                                            |
| tectonic                     | 0.17.0                                                | （本探针未复测，矩阵已证死）                                                                                                      |
| pstricks 实际来源            | `~/Library/texmf/` (tlmgr --usermode 安装）           | `pstricks.sty v0.75` + `pstricks.tex v3.22A` + .pro 若干； **缺 `pst-tools.pro`**(pstricks.tex 2025 新增依赖，usermode 安装不全） |

## 2. 语料画像 (0807.3917, Arıkan polar codes)

- `main.tex` 137KB, ISO-8859(latin-5 标记）, **全文仅 2 个高位字节**: byte 0xA8/0xFF 在 `\thanks` 的 `TÜBİTAK` 处（本身就是 mojibake 源）
- vendored 文件： `pstricks.sty v0.36(2008)` ← 元凶； `IEEEtran.cls V1.6b(2002)`（系统无此 cls, **唯一来源，必须保留**); `stfloats.sty 1999`（系统有较新版但旧版仍兼容）
- 图： `fig{1..12}.tex` 内嵌 `\input`(pstricks 绘图） + `fig4.eps`/`fig7.eps` `\includegraphics`
- 无 .bib/.bbl 依赖（内嵌 thebibliography)

## 3. 路线结果

| 路线  | 配置                                                         | 末遍 `!` 错                                                                            | 产物                                                                                        | 判定                 |
| ----- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | -------------------- |
| A1    | latex, vendored sty **保留**                                 | **128** (undefined cs 级联，首错 `\pssetxlength...\ifpst@useCalc` @ pstricks.tex:1228) | 10KB stub DVI                                                                               | **FAIL**             |
| A1-xe | xelatex, vendored sty 保留                                   | **126**（与矩阵实测一致）                                                              | 无                                                                                          | **FAIL**             |
| A2    | latex + sty 摘除 + pst-tools.pro 补位                        | **2**(`Invalid UTF-8 byte "A8` / `"FF`)                                                | dvips OK → ps2pdf OK, **23 页 489KB**                                                       | **clean**            |
| A3    | A2 + 注入 `\usepackage[latin5]{inputenc}`                    | **0**                                                                                  | DVI（未链，同 A2 后续）                                                                     | clean                |
| B     | xelatex + sty 摘除                                           | **0**                                                                                  | **直出 25 页 404KB**; xetex-pstricks/xdvipdfmx.cfg 后端，EPS 正常；文本层 **1×U+FFFD** 静默 | **clean**            |
| C     | B + docclass 前注入 `\usepackage[fontset=fandol,UTF8]{ctex}` | **0**                                                                                  | **32 页 433KB**(ctex linespread 重排，预期）; FFFD×1                                        | **clean**            |
| D     | xelatex `-no-pdf` → `dvipdfmx`（单遍）                       | **0**                                                                                  | 24 页 404KB（单遍故页数略异）                                                               | clean（与 B 同链路） |

页数差异 (23/25/32/24): latex 是 IEEEtran 原生排版基准；xelatex 字体映射微异 → 25; ctex 行距/字号 → 32（译文产品本来就重排，无关对错）。

## 4. 机理：vendored_sty_shadow

1. cwd 文件在 kpsewhich 搜索序最前 → `\usepackage{pstricks}` 拿到 **vendored v0.36**。
2. v0.36 `\input{pstricks.tex}` → 搜到的是 **2025 年新内核 v3.22A**（语料不自带 .tex)。
3. 新内核的 `\pssetxlength` 等引用 v0.36 未定义的 `\ifpst@useCalc`/`\pscalculate` → 首个 undefined cs → 后续 else/fi 错位 → Missing \begin{document} → 百余级联。
4. 对称地，矩阵首轮 xelatex 报 `pstricks.tex not found` 是因当时用户 texmf 尚未装 pstricks —— **同一签名族的两副面孔**: "找不到 .tex" 或 "找到但版本错配"。
5. 反例校准： `IEEEtran.cls` vendored 是**唯一来源**→ 摘除必死； `stfloats.sty` vendored 1999 旧于系统但接口稳定 → 摘除非必需。**规则不能"逢 vendored 必摘", 要按版本 + 错误触发**。

## 5. 推荐路由

**pstricks 工程 ≠ 必须 dvips。** 决策树：

```
工程含 vendored .sty/.cls 且同名存在于 texmf?
  └─ 比较 \ProvidesPackage/\ProvidesFile 日期： vendored 更旧 → 隔离(rename .VENDORED)
      （同名不存在于 texmf → 保留， 如 IEEEtran.cls)
首选 xelatex + ctex 注入 (= 产品管线): 实测 0 err
兜底 latex→dvips→ps2pdf: 当 xelatex 仍失败（pst-* 特性仅 dvips 支持， 如 pst-vue3d/某些透明度）
  或上游要求保真原版排版时启用； 前置 preflight: kpsewhich pstricks.pro pst-tools.pro 等
```

## 6. fixloop 规则建议

### R1 `vendored_pkg_shadow` （新，本探针实证）

- **触发签名**（两条任一）:
  a. **预扫**: 工程目录存在 `*.sty/*.cls`, 与 `kpsewhich -all <name>` 命中文件同名，且 vendored 的 ProvidesPackage/ProvidesFile 日期 < 系统副本；
  b. **错误触发**: log 出现 undefined cs 级联（>10) 或 `File 'X.tex' not found` 且 X.tex 实际存在于 texmf, 首错位置落在某 vendored 包加载之后。
- **动作**: rename vendored 为 `<name>.VENDORED` 重编；vendored 是同名文件唯一来源时**不摘**（如本例 IEEEtran.cls)。
- **收益**: 0807.3917 实测 126/128 err → 0/2 err。应为 fixloop 最高优先级规则之一（零成本 rename, 不依赖网络安装）。

### R2 `non_utf8_source` （编码前置）

- **触发签名**: 预扫主 .tex UTF-8 decode 失败（chardet 探测），或 latex log `Invalid UTF-8 byte`。
- **动作**: xelatex 路线 → 上游先转码 UTF-8 再编译（管线本来就要解码分段）; latex 路线 → 注入 `\usepackage[<探测编码>]{inputenc}`(latin5 实测 2err→0err)。
- **注意盲区**: **xelatex 不报 '!' 错，静默产 U+FFFD** —— clean 判据必须加 "文本层 U+FFFD 扫描" 或 log `Invalid UTF-8.*replaced` warning 扫描，不能只看错误数。

### R3 `pstricks_dvips_fallback` （路由兜底）

- **触发签名**: `\usepackage{pstricks|pst-*}` 且 xelatex 经 R1 后仍失败（或产物校验发现 pspicture 未渲染）。
- **动作**: 切 `latex→dvips→ps2pdf`; preflight `kpsewhich` 检查所需 `.pro`(pstricks.pro/pst-algparser.pro/pst-tools.pro/各 pst-*.pro), 缺失先走 install 链。
- 备注：本机缺 pst-tools.pro 是 BasicTeX+usermode 安装不全的个例；完整 MacTeX/TL 不缺。fixloop 的 missing_file 链对 `.pro` 同样适用（包名 = tlnet 归档名，pst-tools.pro∈pst-tools.tar)。

### R4 对既有 `latex209_reject` 的补充

矩阵已证 `\documentstyle` 工程三引擎全死、**不应**路由 latex+dvips。本探针反向补一条：latex+dvips 的正确用途是 **pstricks/EPS 兜底**, 而非 2.09 救命——路由条件写清 "仅当非 latex209 且含 pst-*/EPS 依赖"。

## 7. 产物位置

`tmp/exp/pstricks-probe/{A1,A2,A3,B,C,D}/` 保留全部 log/dvi/ps/pdf; `pst-tools.pro` 来源 `https://mirror.ctan.org/systems/texlive/tlnet/archive/pst-tools.tar.xz`。
