# ctan_fetch 原语验证：tlpdb 索引 + tlnet 拉包 + 工作目录遮蔽

- 日期：2026-09-14
- 环境：tectonic 0.17.0 (bundle 快照 ~TL2022 早期：ctex 2.5.8 / expl3 2022/07/14), macOS, 网络仅 mirror.ctan.org
- 现场： `tmp/exp/ctanfetch/` （解析器 `tlpdb_index.py`, 索引 `filemap.json`, 包缓存 `pkgs/`, 实验工程 `work-2305/` `work-2305-noctex/`)
- 起因：engine-matrix 记录 2305.14335 (IEEEtran+ 注入 ctex) 在 tectonic 下 `missing \item`@bbl + bbm10 字体死，当时归因为 "bundle ctex 2.5.8 旧"。本实验用该工程验证 ctan_fetch 降级原语， **顺带推翻了原归因**

## 0. TL;DR

| 环节                   | 结论                                                                                                                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| tlpdb 索引             | **可行**: 20.7MB tlpdb → 8148 包 / 138,164 basename 索引，构建 **0.14s**, filemap.json 5.5MB                                                                                                     |
| tlnet 拉包             | **可行**: `archive/<pkg>.tar.xz` 单包 2–136KB, ~1–2.6s/个                                                                                                                                        |
| 工作目录遮蔽           | **成立**: 平铺进 cwd 的 `ctex.sty` 2.5.10/2.6.5 均被优先加载，遮蔽 bundle 2.5.8                                                                                                                  |
| TEXINPUTS env          | **不认**; 等价物是 `-Z search-path=<dir>` （毒丸测试证实遮蔽 bundle)                                                                                                                             |
| **missing \item 根因** | **不是 ctex 旧**: 无 ctex 复测照样炸。真凶 = tectonic 自动跑 bibtex, 无 reference.bib → 生成 24 行 stub bbl **在虚拟 FS 里遮蔽真实 main.bbl** → 空 thebibliography → `\endlist` 报 missing \item |
| bbm10 字体死           | **文件投放救不了**: cwd/search-path/outdir 放 .pk/.pfb 全被 xdvipdfmx 无视（物理字体只认 bundle)。出路 = 改写规则 (bbm→dsfont shim, 已实测出 PDF)                                                |
| 最终战绩               | work-2305: **0 错误，17 页 6.97MB PDF**, 与 xelatex 结果持平                                                                                                                                     |

## 1. 索引构建

tlpdb 正确路径是 `systems/texlive/tlnet/tlpkg/texlive.tlpdb.xz` （任务书给的 `tlnet/texlive.tlpdb.gz` 404 — **注意 tlpkg/ 子目录 + .xz 后缀**)。

- 下载：2.77MB xz / 2.0s; 解压后 20.7MB
- 解析 (`tlpdb_index.py`): `name <pkg>` 块内 `runfiles`/`docfiles`/`srcfiles` 缩进清单，剥 `RELOC/` 前缀取 basename
- 产出：8148 包 → 138,164 唯一 basename (138,734 条记录）, **406 个 basename 多包共名** （查表需消歧）, 构建 0.14s
- 扩展名白名单在任务给定 (.sty/.cls/.def/.fd/.tfm/.pfb/.enc/.map/.cfg) 外加了 `.clo/.vf/.ofm/.ovp` — ctex 有 `.clo` 字号文件，不索引则无法从缺 `.clo` 反查包

## 2. 拉包链路实测

| 文件             | 命中包   | tar.xz 大小 | 耗时  | tar 内目标 relpath                           |
| ---------------- | -------- | ----------- | ----- | -------------------------------------------- |
| hyperxmp.sty     | hyperxmp | 15,232 B    | 1.16s | `texmf-dist/tex/latex/hyperxmp/hyperxmp.sty` |
| chngcntr.sty     | chngcntr | 2,080 B     | 1.13s | `tex/latex/chngcntr/chngcntr.sty`            |
| totpages.sty     | totpages | 3,020 B     | 1.09s | `tex/latex/totpages/totpages.sty`            |
| ctex.sty（追加） | ctex     | 136,228 B   | 2.65s | `tex/latex/ctex/ctex.sty` (74 文件）         |

**踩坑：tar 顶层前缀不统一** — 有的包带 `texmf-dist/`, 有的直接 `tex/`。落地策略两选一： ① 剥前缀后按 relpath 落 `tex/` 树 + `-Z search-path`; ② **全量平铺 basename 到工程根目录** （需先查 basename 冲突，ctex 73 文件无重名，实测可用）。

## 3. 遮蔽验证 (2305.14335)

### 3.1 复现基线

工作副本跑 `tectonic -Z continue-on-errors --keep-logs`: 复现与矩阵一致的失败 — bundle `ctex 2021/12/12 v2.5.8`, `! LaTeX Error: Something's wrong--perhaps a missing \item` @ `main.bbl` 的 `\end{thebibliography}`, xdvipdfmx 死於 `bbm10`。

### 3.2 遮蔽本身：成立

tlnet 拉 ctex 2.6.5 平铺进工程根目录 → log 明确 `Package: ctex 2026/08/11 v2.6.5` — **cwd 文件优先于 bundle 被加载**。毒丸测试同样证实 `-Z search-path=<dir>` 里的假 `chngcntr.sty` 遮蔽 bundle 版。

### 3.3 但 missing \item 不是 ctex 的锅

- 换 2.6.5 后 missing \item **依旧**; 去掉 ctex 的对照组也照炸 → 与 ctex 版本无关
- 根因链： `main.tex` 有 `\bibliography{reference}` 但无 `reference.bib` ("bbl-no-bib" 语料） → tectonic 自动跑 bibtex → `main.blg` 记录 "couldn't open database file reference.bib" → bibtex 仍写出 **24 行 stub bbl** (IEEEtran 前言 + 空 thebibliography) → **该 stub 在 tectonic 内存文件层遮蔽磁盘上 360 行真 bbl** (log 里 `l.24 \end{thebibliography}` 与真 bbl 的行数对不上就是铁证） → 空 list 的 `\endlist` 报 missing \item
- 修法（改写非拉包）: `\bibliography{reference}` → `\input{main.bbl}` → bibtex 不再跑，真 bbl 被读， **missing \item 消失，引用全解析**。`--pass tex` 不能局部跳过 bibtex（连带跳过 pdf driver)

### 3.4 ctex 版本兼容陷阱（遮蔽的反例）

- tlnet 只发最新版。ctex **2.6.5 对 bundle 的 expl3 (2022/07/14) 太新**: `! Package ctex Error: Support package 'expl3' too old` + 82 个级联错误；PDF 能出但中文全部退回 lmroman 丢失字形 — **比 bundle 旧版还差**
- 换 **2.5.10** （本地 `~/Library/texmf` 同款，模拟版本钉死拉取）: **0 错误**, CJK 正常走 Fandol, 17 页 6.97MB PDF, 与 xelatex 结果持平
- **推论：ctan_fetch 必须带版本兼容判断**。tlnet 无历史包；需要钉版本时得另找源 (historic tlnet / 自建 pin cache) 或接受 "最新可能太新" 的失败模式

### 3.5 物理字体：文件投放死路

`bbm10` 只有 MF 源 + .tfm (TL 全库无 .pfb — 索引里 `bbm10.pfb` MISS)。投放尝试全灭：

| 投放                                                      | 结果           |
| --------------------------------------------------------- | -------------- |
| `bbm10.600pk` (mktexpk 产物）入 cwd                       | xdvipdfmx 无视 |
| `bbm10.pk` / `bbm10.pfb` (dsrom10.pfb 改名）入 cwd        | 无视           |
| `.pfb` + `-Z search-path=.` / 绝对路径 fonts/ / 放 outdir | 全无视         |

**tectonic 的 xdvipdfmx 物理字体只查 bundle, 无 cwd/search-path/mktexpk 回调**。此类失败只能靠改写： `\usepackage{bbm}` → 注释 + `\mathbbm/\mathbbmss→\mathds, \mathbbmtt→\mathtt` shim（文档本就加载 dsfont) → xdvipdfmx 从 bundle 自动拉 `dsrom10.pfb` → **PDF 出**。字形为 ds 系黑板体，与 bbm 有微小风格差。

## 4. ctan_fetch 可行性结论与实现要点

**可行，但适用范围 = TeX 输入层文件** (.sty/.cls/.def/.cfg/.clo/.fd/.tfm 等被 TeX 读的）; **物理字体 (.pfb/.pk/.vf) 与 xdvipdfmx 层不在射程内**, 须走改写规则或自建 bundle。

实现要点：

1. **索引**: tlpdb.xz (~2.8MB) 离线解析，basename→包，构建亚秒级；406 个多包 basename 需消歧策略（按 depend 树/常见度排序或报歧义）
2. **下载**: `mirror.ctan.org/systems/texlive/tlnet/archive/<pkg>.tar.xz`, 包普遍 <150KB, 秒级；整包拉取含依赖文件，比按文件精确投放稳
3. **落地**: 剥 `texmf-dist/`/`tex/` 前缀；工程根目录平铺 basename 最简单且实测遮蔽有效；或保留 `tex/` 树配 `-Z search-path`
4. **版本兼容**: bundle expl3/LaTeX2e 是 ~2022 中快照，最新包可能拒载 (ctex 2.6.5 实证）。要么版本钉死（需非 tlnet 的历史源）, 要么失败回退 bundle 版
5. **优先级**: 生成物（内存层） > 本地 cwd/search-path > bundle; **tectonic 生成物遮蔽磁盘文件**这条也是坑 (stub bbl 案）
6. **不可达域**: xdvipdfmx 物理字体、EPS 包含 — 改写规则兜底

## 5. 沉淀给 fixloop 的规则

- **R-bbl-shadow** (tectonic): 有 .bbl 无 .bib 时 `\bibliography{x}` → `\input{main.bbl}`, 阻断自动 bibtex 生成 stub 遮蔽真 bbl
- **R-font-sub** (tectonic): MF-only 字体包 (bbm 等） → Type1 近亲 (dsfont/dsrom) shim
- **ctan_fetch 前置检查**: 命中包先比对 bundle 版与新版的 expl3/LaTeX2e 要求，新版过新则跳过（否则救成更差）
