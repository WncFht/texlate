# fixer-apjbbx — 1706.00240 bundled apj.bbx ↔ biblatex 3.21

任务 #34（read-only 归因 → 定修形 → 交付 fragment）。Deliverables：`rules-fragment.yaml`（merge-ready）、`verification.txt`（全量 fixloop 复放证据）。

## 归因

biblatex 3.8 (2017-11) 改名 `date+extrayear`→`date+extradate`、`labelyear+extrayear`→`labelyear+extradate`；TL 装 3.21，旧名只剩 authoryear.bbx L20-25 provide-shim（体无 patch find-texts）。bundled apj.bbx 的 `\bbx@patchmacro`（= `\patchcmd` on `\abx@macro@N`，失败走 PackageError）两处致命：

- L192-194 `patch{author}`：现代 author 宏体（L222）调用的是 `+extradate` → find-text 失配
- L197 `patch{date+extrayear}{[parens]}{}`：目标宏只剩 shim 体 → 失配

**修形 = 源级更名**，非 shim/version-gate：更名后双侧皆通（author 体含新名；date+extradate 全部 mergedate 变体含 `\printtext[parens]`）。

## Cluster 面

`Cannot patch` 在 loop1 全量 log 里**只有 1706.00240**。其他 extrayear-bearing 文件良性：acmauthoryear.bbx ×14 pids 是正向 shim（patch 新名，今日成功）；blx-compat.def（1907.00257/2003.10727）本身是字段别名 shim；ms.bbl（2009.11064）数据侧 `\printfield` 走别名。

## 交付物

- taxonomy head sig `cannot_patch_macro` = `Cannot patch (?:bibliography|citation) macro ([\w@:+-]+)`（key_unknown 后；file-line-error 形态无需 `!`，此前零签命中落 `other`）
- rule `biblatex_bbx_rename` order 161，regex_rewrite 更名，exts `[.bbx,.cbx,.sty,.tex]`，when `category=cannot_patch_macro`
- **端到端实证**：`_fixloop_one` 同构复放 —— r1 `cannot_patch_macro/author` → 规则 fire `rewrite in 1 files`（3 处全更名）；r2 推进 `undefined_cs/sortlist`，Cannot-patch 不再现。

## 尾险（写入 fragment 注释）

若被补文件自带 *正向* shim `\providebibmacro*{date+extradate}{\usebibmacro{date+extrayear}}` 且自身新名 patch 先失败，改写会成自指 → capacity 兜住（换墙非静默腐蚀）。今日零 ACM 格发 Cannot-patch，属未来漂移面。

## 后续墙（spec'd，非本 fragment）

- **wall-2**（builtins，1d 车道）：torus.bbl 是 bbl format 2.8；biblatex 3.21 拒收，biber rc=2 且**自删旧 bbl**——`bbl_regen`(o158) 确 fire 但返回 False，删档副作用白做。spec：biber 失败后若 stem.bbl 消失或头标 `bbl format version < 3.0` → invalidate + return True。无 .bib 随稿，drop 是唯一治愈路。
- **wall-3**（新类，builtin）：bundled physics.sty 是 2012 手写 2.4KB stub（`\dbar\ord\dalm\kB\bra\ket\comm\wick\fvec`），siunitx v3 在 `\begin{document}` 对 `\@ifpackageloaded{physics}` 硬报错 → torus.tex:209。需 builtin `physics_stub_detach`（剥 usepackage 项 + neuter ProvidesPackage 后 \input stub）。

## 环境注（复放用）

wave env = `TEXMFHOME=<wid>/_texmf/home:~/texmf` + `TEXMFVAR/TEXMFCONFIG=<wid>/_texmf/{var,config}` + `FONTCONFIG_FILE=<wid>/_texmf/home/fontconfig/fonts.conf`（生成 conf 注册 texmf-dist opentype → fontconfig，解 "Latin Modern Mono" 查找）；siunitx 在 `~/texmf` ambient 尾。
