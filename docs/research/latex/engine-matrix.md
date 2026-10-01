# 引擎矩阵实验：xelatex vs tectonic 真实语料差异

> **结论**：tectonic 初始 clean 率更高（7/12 vs 4/12）但有三类硬性限制（EPS/PS 图、bundle 缺物理字体、bundle 包版本旧）；xelatex 的缺包失败全部可被 tlmgr 链式装包救回。两引擎失败集几乎互补，联合覆盖 9/12。默认路由 = 开发态 xelatex、分发态 tectonic 优先 + xelatex 兜底 + 静态预检。
> **状态**：时点证据（2026-09-14 口径；路由结论已落地为 `compile/engine/_route.py` 静态签名集 + fixloop 规则，规范见 `spec/compile.md`）
> **日期**：2026-09-14

## 1. 口径

12 个多样项目语料（amsart/revtex4-2/IEEEtran/acmart+Agda/elsarticle/subfiles+ 私类/2.2MB book/LaTeX2.09/法语 babel+T1/latin-5+pstricks/minted/tikz 重度）。引擎：xelatex（TeX Live 2026）vs tectonic 0.17.0（bundle 快照 ctex 2.5.8/fontspec 2.8a/minted 2.6，普遍比 TL2026 旧）。统一在 `\documentclass` 后字节级注入 `\usepackage[fontset=fandol,UTF8]{ctex}`；timeout 240s；clean 判据 = 出 PDF 且末遍 log `!` 错误 ≤3。

首轮矩阵结果：xelatex 4 clean / 1 pdf~ / 7 FAIL；tectonic 7 clean / 1 pdf~ / 4 FAIL。修复探针后 xelatex 达 7 clean + 4 pdf~ + 1 FAIL；联合 clean 覆盖 9/12，仅 hep-th 三引擎均失败（LaTeX2.09 + 私类）。

## 2. 失败分类学（E1–E12）

| #   | 类别                           | 引擎              | 可修性       | 修法/路由                                                                                                           |
| --- | ------------------------------ | ----------------- | ------------ | ------------------------------------------------------------------------------------------------------------------- |
| E1  | missing_* 链（class/sty/file） | xelatex           | 实测可修     | `tlmgr --usermode install`，链深 1–5 轮（最深 acmart→hyperxmp→polytable→lazylist→newunicodechar）                   |
| E2  | EPS/PS 图片                    | tectonic 硬性限制 | 换引擎       | `xdvipdfmx: image inclusion failed for *.eps`——静态扫 `*.eps`/pstricks/pspicture → 路由 xelatex                     |
| E3  | bundle 缺物理字体              | tectonic          | 换引擎       | `Cannot proceed without .vf or physical font`（bbm10 等位图字体）；TL 侧装好即过                                    |
| E4  | bundle 包版本旧→语义错         | tectonic          | 换引擎       | 同 cls 同 bbl xelatex 全过而 tectonic 报 `missing \item`；bundle 内包不可换                                         |
| E5  | 自带旧 .sty 遮蔽新包           | xelatex           | fixloop 规则 | 项目内 pstricks.sty v0.36 包住新 pstricks.tex → 126 个 undefined；隔离 vendored 文件                                |
| E6  | latin-5 静默 U+FFFD            | 两引擎共有        | 判据层       | `Invalid UTF-8 byte`/`Missing character.*U+FFFD` 只是 warning 非 `!`——clean 判据盲区，须加 warning 扫描或转码预处理 |
| E7  | `\ifnum\pdfoutput` 读取型      | xelatex           | 新规则       | 赋值型守卫对它无效，需 polyfill `\ifdefined\pdfoutput\else\chardef\pdfoutput=1\fi`                                  |
| E8  | minted 版本错配                | xelatex           | 规则         | v3.8 × v2 frozencache → 50 错；`{minted}`→`{minted2}` 一行替换；tectonic bundle v2.6 反而天然兼容（反向收益）       |
| E9  | LaTeX 2.09 + 私类              | 三引擎均失败      | 拒绝         | ptptex.cls 不在任何源——`\documentstyle` 检测即拒绝，latex+dvips 路由了也缺类                                        |
| E10 | 宏冲突级联                     | 两引擎            | 半规则       | `\c@lemma already defined` 类，tectonic 级联更大但同样产出降级 pdf                                                  |
| E11 | acmart × baselinestretch       | xelatex           | 低危         | acmart+ctex 摩擦，1 err 不致命                                                                                      |
| E12 | unicode 数学符号缺包           | xelatex           | 难修         | `\blacktriangleright` ×71：需 cs→pkg 知识库（fdsymbol/stix/unicode-math）                                           |

## 3. 专项发现

**`.bbl` 直消费（5 个「有 .bbl 无 .bib」项目两引擎全过）**：xelatex 不跑 bibtex 直接读 `<jobname>.bbl`；tectonic 检测到 `\bibliography` 自动跑 bibtex，找不到 .bib 后优雅回退读项目原 .bbl（bbl 不被覆写）。结论：有 .bbl 无 .bib 项目两引擎都安全，无需剥离 `\bibliography`。附带：tectonic 有时不写 .log 到 outdir——监控不能只依赖 log 存在。

**LaTeX 2.09**：`\documentstyle{ptptex}` 三引擎（含 latex+dvips）均失败——私类文件不存在于任何源，检测即无条件拒绝。

**latin-5 静默污染**：xelatex 对 latin-5 字节零 `!` 错误正常出 PDF，但 log 有 `Invalid UTF-8 byte or sequence…replaced by U+FFFD` + `Missing character…U+FFFD`——正文静默污染（`TÜBİTAK→TUBITAK`），最小复现同态。**clean 判据必须在 `!`≤3 之外加 UTF-8 warning 扫描。**

**minted**：xelatex 侧 minted v3.8 读不了 v2 frozencache（50 个 `Cannot highlight`）；tectonic bundle minted v2.6 与 v2 cache 版本天然匹配 0 错——版本钉死方向与直觉相反，bundle 旧反而有利。frozencache 的设计目的就是免 shell-escape，两引擎都不需要它。

**修复链式暴露模型**：每轮装上轮首错即见下一层，agda/私类项目链最深 5 轮；本轮 xelatex 全部 7 个 FAIL 的首错都是 missing_* 类。

## 4. 路由决策（已落地）

开发默认 **xelatex**：fixloop 修复循环建在 tlmgr/log 语义上，缺包可修性实测最高；tectonic 的「静默降级」（缺包继续跑、EPS 不支持仅 warning、有时不写 .log）使错误信号更碎，不适合做修复循环的地面真值。

分发默认 **tectonic 优先 + xelatex 兜底 + 静态路由预检**：便携二进制无 tlmgr 依赖、初始 clean 率更高。静态预检表（编译前即可决策）：

| 检测                                            | 路由                                      |
| ----------------------------------------------- | ----------------------------------------- |
| `\documentstyle`                                | 拒绝（三引擎均失败已实证）                |
| `*.eps` / `\usepackage{pstricks}` / `pspicture` | 跳过 tectonic 直走 xelatex（E2 硬性限制） |
| `frozencache` + minted 装载共现                 | tectonic 优先（E8 bundle v2.6 兼容）      |
| bbm/dsfont 类位图字体包                         | tectonic 高风险 → 失败后换 xelatex（E3）  |

clean 判据三件套：① pdf 存在；② `!`≤3 且首错非 missing_*/undefined_cs；③ log warning 扫描（`Invalid UTF-8 byte`/`Missing character.*U+FFFD`/tectonic `File.*not found` 降级行）任一命中即 dirty。

落地注记：现行 `compile/engine/_route.py` 的签名集与上表一致（pstricks 家族名集 = 精确 `pstricks` + 前缀 `pstricks-`/`pst-`，含 pstricks-add；`frozencache` 须与 minted 装载共现才翻 tectonic 优先）；`\documentstyle` 在现行代码中降级为试编标记而非直接拒绝（`latex209_suspect` 槽位），拒绝判定移交 fixloop gate。规则侧落点见 `pstricks-route.md` 与 `fixloop-rules.md`。

### 参考文献

[^tectonic]: Tectonic Project. Tectonic — a modernized, complete, self-contained TeX/LaTeX engine. [tectonic-typesetting.github.io](https://tectonic-typesetting.github.io/)

bundle 版本口径出自 tectonic 0.17.0 默认 bundle 快照[^tectonic]；修复探针与全量 log 为开发机 bench 现场。
