# ctan_fetch 原语验证：tlpdb 索引 + tlnet 拉包 + 工作目录遮蔽

> **结论**：ctan_fetch 降级原语可行——tlpdb 索引亚秒构建、tlnet 拉包秒级、cwd 平铺文件有效遮蔽 bundle；但适用域仅限 TeX 输入层文件（.sty/.cls/.def/.clo 等），物理字体与 EPS 不在射程内，且新版包可能与 bundle 旧 expl3 不兼容，必须带版本判断。
> **状态**：现行（已落地为 `compile/fixloop/ctan.py` + `bbl_stub_shadow`/`font_sub_shim` 规则；规范见 `spec/compile.md`）
> **日期**：2026-09-14

## 1. 动机与顺带推翻的归因

引擎矩阵记录 2305.14335（IEEEtran + 注入 ctex）在 tectonic 下报 `missing \item`@bbl + bbm10 字体死，当时归因为「bundle ctex 2.5.8 旧」。本实验用该工程验证 ctan_fetch 降级原语，**顺带推翻了原归因**——missing \item 与 ctex 版本无关，真凶是 tectonic 自动 bibtex 生成的 stub bbl 遮蔽真实 bbl（§3.3）。

## 2. 索引与拉包

tlpdb 正确路径是 `systems/texlive/tlnet/tlpkg/texlive.tlpdb.xz`——注意 `tlpkg/` 子目录与 `.xz` 后缀（`tlnet/texlive.tlpdb.gz` 404）。下载 2.77MB xz → 解压 20.7MB → 解析 `name <pkg>` 块内 runfiles/docfiles/srcfiles 清单，剥 `RELOC/` 前缀取 basename：**8148 包 → 138,164 唯一 basename，构建 0.14s**；406 个 basename 多包共名（查表需消歧）。扩展名白名单在常规 .sty/.cls/.def/.fd/.tfm/.pfb/.enc/.map/.cfg 外需加 `.clo/.vf/.ofm/.ovp`——ctex 有 `.clo` 字号文件，不索引则无法从缺 `.clo` 反查包。

拉包链路：`mirror.ctan.org/systems/texlive/tlnet/archive/<pkg>.tar.xz`[^ctan]，单包 2–136KB、~1–2.6s；整包拉取含依赖文件，比按文件精确投放稳。踩坑：**tar 顶层前缀不统一**——有的带 `texmf-dist/`、有的直接 `tex/`。落地策略两选一：剥前缀按 relpath 落 `tex/` 树配 `-Z search-path`；或全量平铺 basename 到工程根目录（需先查 basename 冲突，实测 ctex 73 文件无重名可用）。

## 3. 遮蔽验证

### 3.1 cwd 遮蔽成立

tlnet 拉 ctex 2.6.5 平铺进工程根目录 → log 明确 `Package: ctex 2026/08/11 v2.6.5`——cwd 文件优先于 bundle 被加载。毒丸测试证实 `-Z search-path=<dir>` 里的假 `chngcntr.sty` 同样遮蔽 bundle 版；**`TEXINPUTS` 环境变量 tectonic 不认**，等价物是 `-Z search-path`。

### 3.2 missing \item 真凶：stub bbl 遮蔽

换 ctex 2.6.5 后 missing \item 依旧、去掉 ctex 的对照组也照炸——与 ctex 版本无关。根因链：工程有 `\bibliography{reference}` 但无 `reference.bib`（「bbl-no-bib」语料）→ tectonic 自动跑 bibtex → `.blg` 记 `couldn't open database file reference.bib` → bibtex 仍写出 **24 行 stub bbl**（IEEEtran 前言 + 空 thebibliography）→ **stub 在 tectonic 内存文件层遮蔽磁盘上 360 行真 bbl**（log 里 `l.24 \end{thebibliography}` 与真 bbl 行数对不上即铁证）→ 空 list 的 `\endlist` 报 missing \item。修法是改写而非拉包：`\bibliography{reference}` → `\input{main.bbl}`——bibtex 不再跑、真 bbl 被读、missing \item 消失、引用全解析。`--pass tex` 不能局部跳过 bibtex（连带跳过 pdf driver）。

### 3.3 版本兼容陷阱（遮蔽的反例）

tlnet 只发最新版：ctex **2.6.5 对 bundle 的 expl3（2022/07/14 快照）太新**——`Package ctex Error: Support package 'expl3' too old` + 82 个级联错，PDF 能出但中文全部退回 lmroman 丢字形，比 bundle 旧版还差；换与 bundle 同代的 2.5.10 则 0 错误、CJK 正常走 Fandol。**推论：ctan_fetch 必须带版本兼容判断**——tlnet 无历史包，需钉版本时得另找源（historic tlnet/自建 pin cache）或接受「最新可能太新」的失败模式。

### 3.4 物理字体：文件投放死路

bbm10 只有 MF 源 + .tfm（TL 全库无 .pfb）。投放尝试全灭：`.600pk`（mktexpk 产物）/`.pk`/`.pfb` 入 cwd、`-Z search-path`、绝对路径 fonts/、放 outdir——全部被 xdvipdfmx 无视。**tectonic 的 xdvipdfmx 物理字体只查 bundle，无 cwd/search-path/mktexpk 回调。** 此类失败只能靠改写规则：`\usepackage{bbm}` → 注释 + `\mathbbm/\mathbbmss→\mathds`、`\mathbbmtt→\mathtt` shim（工程本就加载 dsfont）→ xdvipdfmx 从 bundle 自动拉 `dsrom10.pfb` → PDF 出（字形为 ds 系黑板体，与 bbm 微小风格差）。

## 4. 可行性结论与实现要点

ctan_fetch **可行，适用域 = TeX 输入层文件**（.sty/.cls/.def/.cfg/.clo/.fd/.tfm 等被 TeX 读的）；物理字体（.pfb/.pk/.vf）与 xdvipdfmx 层不在射程内，须走改写规则或自建 bundle。

实现要点：索引 = tlpdb.xz 离线解析 basename→包，亚秒级，406 个多包 basename 需消歧；下载整包 <150KB 秒级；落地平铺 basename 最简单且遮蔽有效；**版本兼容必须前置检查**（命中包先比对 bundle 版与新版的 expl3/LaTeX2e 要求，新版过新则跳过，否则救成更差）；优先级 = 生成物（内存层）> 本地 cwd/search-path > bundle——**tectonic 生成物遮蔽磁盘文件**这条本身是坑（stub bbl 案）；不可达域（物理字体、EPS 包含）走改写规则兜底。

## 5. 沉淀给 fixloop 的规则（已落地）

- **`bbl_stub_shadow`**：有 .bbl 无 .bib 时 `\bibliography{x}` → `\input{main.bbl}`，阻断自动 bibtex 生成 stub 遮蔽真 bbl。
- **`font_sub_shim`**：MF-only 字体包（bbm 等）→ Type1 近亲（dsfont/dsrom）shim。
- **ctan_fetch 前置检查**：版本兼容判断（新版过新跳过），落地实现见 `compile/fixloop/ctan.py`。

### 参考文献

[^ctan]: CTAN — the Comprehensive TeX Archive Network. [ctan.org](https://ctan.org/)
