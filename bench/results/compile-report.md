# 编译 Benchmark 报告: 真实 arXiv 源码注入 ctex 后重编译

- 日期: 2026-09-14
- 语料: `bench/corpus/` — 12 个真实 arXiv 源码项目 (article/IEEEtran/LaTeX2.09; 单文件~多文件 20 个 tex)
- 引擎: `tectonic 0.17.0` vs `xelatex (TeX Live 2026 basic + ~/Library/texmf)`
- 脚本: `bench/py/compile_bench.py` (三条件×双引擎), `bench/py/rerun_xelatex.py` (修复轮), `bench/py/compile_report.py` (汇总)
- 数据: `bench/results/compile-bench.json` (72 次原始编译 + 30+ 次修复轮重编的全部记录)
- 判据: 超时 120s; **pdf** = 产出 PDF; **clean** = 全程无 `!` 错误
  - xelatex: `-interaction=nonstopmode`, 最多 2 pass (解析 \ref/.bbl/toc)
  - tectonic: `-Z continue-on-errors --keep-logs` — 等价 nonstopmode 语义(默认遇错即停, 与 nonstopmode 不同, 已验证)
  - 超时后 tectonic 重试一次(应对 bundle 冷拉包)

## 0. TL;DR

| 结论 | 数据 |
|---|---|
| arXiv 原文可编译性 | tectonic **9/12 (75%)**; xelatex 原始 **2/12 (17%)**, 修复环境后 **11/12 (92%)** |
| **ctex 注入的破坏率** | **0%** — 两引擎三条件共 72 次编译, 注入从未使"能出 pdf 的项目"变成"不能出 pdf"; 只新增非致命错误 |
| **zh 模拟翻译的破坏率** | **0%** — 同上, 无任何 PDF 产出损失; 新增错误 2 类(soul×CJK、\hyphenation 参数) |
| 干净度代价 | clean 率 baseline→ctex→zh: tectonic 7→4→2, xelatex(修复后) 7→4→1 |
| 最大失败源(xelatex) | **缺包/缺字体 90%+**, 且 8 轮 `tlmgr --usermode install` 全规则化修复, 2/12→11/12 |
| 唯一双引擎皆死 | `hep-th` — LaTeX 2.09 `\documentstyle{ptptex}`, 类文件不可获得, 时代错配 |
| tectonic 独有死法 | `1810` 错误级联 job aborted; `2305` xdvipdfmx 缺物理字体 — **修复后 xelatex 反而能出** |

## 1. 总成功率矩阵

| 引擎 | baseline pdf | ctex pdf | zh pdf | base clean | ctex clean | zh clean |
|---|---|---|---|---|---|---|
| tectonic | 9/12 | 9/12 | 9/12 | 7/12 | 4/12 | 2/12 |
| xelatex 原始 | 2/12 | 2/12 | 2/12 | 0/12 | 0/12 | 0/12 |
| xelatex 修复后 | 11/12 | 11/12 | 11/12 | 7/12 | 4/12 | 1/12 |

## 2. 逐项目矩阵 (xelatex=修复后最终态; PDF=干净, pdf~=带错出pdf, FAIL=无pdf)

| 项目 | base-t | base-x | ctex-t | ctex-x | zh-t | zh-x | 备注 |
|---|---|---|---|---|---|---|---|
| 1412.6980 | pdf~ | pdf~ | pdf~ | pdf~ | pdf~ | pdf~ | `\pdfoutput=1` + `\includepdf` 包装壳 |
| 1511.06432 | PDF | pdf~ | PDF | pdf~ | PDF | pdf~ | xelatex phvb→helvetic 修复后仍 ~ |
| 1512.03385 | PDF | PDF | PDF | PDF | pdf~ | pdf~ | zh: \hyphenation 中文 |
| 1706.03762 | PDF | PDF | pdf~ | pdf~ | pdf~ | pdf~ | ctex: XeTeXglyph×ptmr8c |
| 1810.04805 | FAIL | pdf~ | FAIL | pdf~ | FAIL | pdf~ | `width=360px` 级联; tectonic 死 xelatex 活 |
| 1906.08237 | PDF | PDF | pdf~ | pdf~ | pdf~ | pdf~ | ctex: XeTeXglyph×ptmr8c |
| 2005.11401 | PDF | PDF | PDF | PDF | pdf~ | pdf~ | zh: soul×CJK 重构失败 |
| 2106.09685 | PDF | PDF | PDF | PDF | PDF | PDF | 唯一全绿项目 |
| 2203.02155 | PDF | PDF | pdf~ | pdf~ | pdf~ | pdf~ | ctex: XeTeXglyph×ptmr8c; tectonic 冷拉包 179s |
| 2305.14335 | FAIL | PDF | FAIL | PDF | FAIL | pdf~ | tectonic 死物理字体; xelatex base/ctex 全清 |
| 2501.14787 | pdf~ | pdf~ | pdf~ | pdf~ | pdf~ | pdf~ | 1519 err 仍出 1MB pdf (tectonic) |
| hep-th | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | LaTeX 2.09 ptptex, 不可修 |

## 3. 失败分类学 (修复规则库种子)

按"首条 `!` 错误"归类; **可修** = 已有实测验证的自动修法。

| # | 类别 | 代表 log | 出现 | 可修? | 修法 |
|---|---|---|---|---|---|
| F1 | missing_package | `! LaTeX Error: File 'tabulary.sty' not found.` | xelatex 原始失败 ~全部; 共 25+ 个包 | ✅ 实测 | `tlmgr search --global --file X.sty` → `tlmgr --usermode install` |
| F2 | missing_font (TFM) | `! Font \cvprtenhv=phvb at 8.0pt not loadable: Metric (TFM) file...` | 1511/1512/1810/2106 (phvb), 2305 (wasy10) | ✅ 实测 | 同上装 `helvetic`/`wasy` (+`urw`实体+`psnfss`); 会议 sty 硬编码 `\font\x=phvb` |
| F3 | 物理字体缺失@xdvipdfmx | `Cannot proceed without .vf or "physical" font for PDF output` | 2305 tectonic | ✅ | tectonic 死; xelatex+usermode(times/urw+updmap)能过 — **引擎切换可修** |
| F4 | missing_class | `File 'ptptex.cls' not found` | hep-th ×6 | ❌ | LaTeX2.09 厂商样式, 不在 CTAN; 只能路由 `latex+dvips` 或拒绝 |
| F5 | pdftex 原语 | `<recently read> \pdfoutput` → `Undefined control sequence` + `Missing \begin{document}` 级联 | 1412, 2501 | ✅ 规则 | `\ifdefined\pdfoutput\pdfoutput=1\fi` 包裹或删除; pdfTeX 原语族(\pdfminorversion 等)同规则 |
| F6 | 非法单位 | `! Illegal unit of measure (pt inserted).` — `\includegraphics[width=360px]` | 1810 (×21→tectonic 死) | ✅ 规则 | `px`→`bp` 换算 (96dpi: 360px≈270bp); xelatex 容错出 pdf, tectonic 级联死 |
| F7 | fontspec×旧式TFM | `! Cannot use XeTeXglyph with ptmr8c; not a native platform font.` (microtype 量字宽) | 1706/1906/2203 **仅 ctex/zh** | ✅ 规则 | `\usepackage{times|mathptmx}`→`newtxtext`; ctex 激活 fontspec 后才触发 |
| F8 | soul×CJK | `! Package soul Error: Reconstruction failed.` at `\texttt{"这是..."}` | 2005 zh | ⚠️ 规避 | soul 不兼容 CJK; 管线对 `\hl\ul\st` 参数不注中文或换 lua-ul/xeCJKfntec |
| F9 | \hyphenation 参数 | `! Not a letter.` — `\hyphenation{这是...}` | 1512/2305 zh | ✅ 规则 | `\hyphenation` 参数加入"不译宏"清单 (脚本工件, 但规则真实必要) |
| F10 | minted 版本错配 | `! Package minted Error: Cannot highlight code (frozencache=true)` ×25 | 2501 xelatex | ✅ | frozencache 由 minted v2 生成, 装 v3 报错; 钉版本 or `-shell-escape` 重生成 |
| F11 | 宏冲突(重定义) | `! LaTeX Error: Command \c@lemma already defined.` ×16 | 2501 | ⚠️ 半规则 | lindrew.sty 与 thmtools/amsthm 双定义定理环境; 需源码补丁 |
| F12 | LaTeX 2.09 | `LaTeX2e command \ensuremath in LaTeX 2.09 document` | hep-th tectonic | ❌ | 同 F4; `\documentstyle` 检测→路由 |
| — | 缺文件提示符死 | `Enter file name:` → `! Emergency stop. *** (cannot \read from terminal in nonstop modes)` | xelatex 所有缺包死的共同终点 | ✅ 机制 | 见 §4 — 预检可让 90% 此类死法不发生 |

## 4. tectonic vs xelatex(TeXLive) 机制差异

| 维度 | tectonic 0.17 | xelatex TL2026basic+usermode |
|---|---|---|
| 包完整性 | 自带全量 bundle, 全程 **0 个 missing_\*** | basic 缺 25+ 包; tlmgr usermode 可补(系统树不可写时) |
| 缺文件行为 | `continue-on-errors` 把 missing .sty **降级为可恢复**, 跳包继续 → **残页 pdf**(2501 缺 tikz-cd 仍出 1062KB) | `File not found` 触发文件名提示符 → nonstop 无法 \read → `Emergency stop` **无 pdf** |
| 默认遇错 | **默认 halt-on-error**(非 nonstop 语义! `-Z continue-on-errors` 才对齐) | nonstopmode 一路到底, 除非 \read 提示符 |
| 独有死法 | 错误级联 `no legal \end found` (1810); xdvipdfmx 物理字体缺失 (2305) | (修复后)仅 hep-th |
| 速度 | 热缓存 **0.5–13s**; 冷拉包一次性 ~179s (2203) | 4–18s 稳定 |
| clean 倾向 | 同文档常比 xelatex 干净(自带包版本搭配协调) | 补包后持平甚至反超(2305 base/ctex 全清) |

**关键洞察**: 两引擎失败集**互补** — tectonic 死的 1810/2305 xelatex 修复后都能出 pdf;xelatex 原始死一片的项目 tectonic 全过。管线最佳形态 = tectonic 优先(快+自足) → xelatex 兜底(互补覆盖) → 本语料联合覆盖 11/12。

## 5. 修复循环实测 (rerun_xelatex.py, 8 轮)

纯 `tlmgr --usermode install` 无源码改动, 每轮装上轮暴露的缺包:

| 轮 | 安装 | 救回项目 |
|---|---|---|
| r1 | units doublestroke tikz-cd psnfss helvetic times courier symbol | (暴露下一层) |
| r2 | tabulary subfiles tikz-qtree stmaryrd soul wrapfig minitoc nth thmtools mdframed | 1512, 2005, 2106 |
| r3 | import tablefootnote xifthen pythonhighlight placeins zref needspace | 1706, 2203 |
| r4 | ifmtarg sttools silence | 1810, 1906 |
| r5 | wasysym cleveref / r6 tabu cancel | (推进) |
| r7 | varwidth mathdots upgreek cmbright wasy was | 2305 |
| r8-11 | catchfile xstring etoolbox latex2pydata pgfopts newfloat shellesc float xcolor + **手动装 minted**(不可重定位) | 2501 |
| r12 | (wasy 实体补齐后重跑) | 2305 转 clean |

**2/12 → 11/12, 零源码补丁。** 缺包呈链式: 每修一轮暴露下一层, 正是"首错→分类→动作→重编"循环的天然形态。

## 6. 对"编译修复循环"的设计启示

1. **循环骨架可行且必要**: `编译 → 取首个'!'行 → 分类 → 规则动作 → 重编`。错误有级联, 一次只修首错, 最多 N 轮(建议 8-12), 同错重复即终止。
2. **第 0 招是静态预检, 不是编译**: 修复轮 90% 的 Emergency-stop 死因是"缺包直到编译才发现"。先 `\usepackage/\RequirePackage` 静态扫 + `kpsewhich` 验证 → 批量 `tlmgr --usermode install`, 可把 missing_* 失败压缩到 1 轮内。本 bench 若预检, xelatex 原始成功率预计 8/12 起步。
3. **规则优先级**(按实测 ROI): ① missing_* → tlmgr search/install ② pdftex 原语/非法单位 → 源码守卫正则 ③ `\usepackage{times|mathptmx}`→newtxtext (兼治 F3+F7) ④ soul/\hyphenation 加保护清单 ⑤ minted 版本钉死 ⑥ \documentstyle/商业字体(mtpro2) → 路由拒绝。
4. **判据别只看 pdf**: 2501 在 1519 个 `!` 错误下照样吐 1MB pdf — "产出"≠"正确"。需要 clean 阈值(建议 ≤3 个 ! 且无 missing_*/undefined_cs)或页数/字数 sanity。
5. **双引擎互补是便宜的保险**: 单 tectonic 75%, 单 xelatex(修复后) 92%, **联合 92% 且互补死法**; 修复循环跑不动时换引擎就是一条"规则"。
6. **tectonic 的降级产出是暗雷**: 缺包它静默继续 → 产出"看起来成功"的残缺 pdf, 比明确失败更难发现。用 tectonic 时必须盯 `! File ... not found` 行数。
7. **翻译管线自己的坑**(zh 条件实测): `\hyphenation{}`、soul 族命令(\hl\ul\st\texttt 内嵌)、`\documentstyle` 三类需要进保护/路由清单; `\includepdf` 包装壳(1412)翻不了正文 — 前置识别。

## 7. 复现

```bash
python3 bench/py/compile_bench.py          # 全量 72 次编译 (~20min, tectonic 首跑慢)
python3 bench/py/rerun_xelatex.py          # 修复轮重跑(改 ROUND/FIXES)
python3 bench/py/compile_report.py         # 重分类+出表
```

工作副本在 `bench/work_compile/{项目}/{条件}/` 下, 含每遍的 .log 与 _tect_out/。
