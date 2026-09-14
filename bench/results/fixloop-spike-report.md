# 编译自动修复循环 spike 报告

- 日期: 2026-09-14 10:04  |  引擎: xelatex -interaction=nonstopmode, ≤2 pass  |  最大轮数: 8
- 环境: `cold` TEXMFHOME (每格独立沙箱, 复现 TeXLive basic 裸环境)  |  静态预检: True
- clean 阈值: pdf 且 '!' 错误 ≤ 3
- 脚本: `bench/py/fixloop.py`  数据: `bench/results/fixloop-results.json`
- 对照组: `compile-bench.json` 原始 xelatex(暖环境) 结果

## 1. 自动救回率

| 口径 | 数 | 率 |
|---|---|---|
| 总格数 (12项目×3条件) | 22 | |
| 原始 xelatex 即失败(无pdf) | 16 | |
| **循环救回 pdf** | **16** | **16/16 = 100%** |
| 救回且干净(≤3错) | 15 | 94% |
| 路由拒绝(hep-th, 不算救回) | 0 | |
| 终态出pdf总格 | 22 | 22/22 |
| 终态 clean(0错) | 21 | |
| 终态可接受(≤3错) | 21 | |

## 2. 逐格矩阵

| 项目 | 条件 | 原始xelatex | 首错类别 | 轮数 | 装包 | 终态 | 错误数 |
|---|---|---|---|---|---|---|---|
| 1412.6980 | baseline | pdf~ | pdftex_prim:pdfoutput | 2 | 0 | clean (pdf+0错) | 4→0 |
| 1412.6980 | ctex | pdf~ | missing_file:zhnumber.sty | 4 | 2 | clean (pdf+0错) | 2→0 |
| 1412.6980 | zh | pdf~ | missing_file:zhnumber.sty | 4 | 2 | clean (pdf+0错) | 2→0 |
| 1511.06432 | baseline | pdf~ | missing_tfm:phvb | 2 | 2 | clean (pdf+0错) | 2→0 |
| 1511.06432 | ctex | pdf~ | missing_file:zhnumber.sty | 4 | 4 | clean (pdf+0错) | 2→0 |
| 1511.06432 | zh | pdf~ | missing_file:zhnumber.sty | 4 | 4 | clean (pdf+0错) | 2→0 |
| 1512.03385 | baseline | FAIL | missing_tfm:phvb | 2 | 3 | clean (pdf+0错) | 2→0 |
| 1512.03385 | ctex | FAIL | missing_file:zhnumber.sty | 4 | 5 | clean (pdf+0错) | 2→0 |
| 1512.03385 | zh | FAIL | missing_file:zhnumber.sty | 5 | 5 | clean (pdf+0错) | 2→0 |
| 1706.03762 | baseline | FAIL | missing_file:import.sty | 2 | 3 | clean (pdf+0错) | 2→0 |
| 1706.03762 | ctex | FAIL | missing_file:zhnumber.sty | 5 | 5 | clean (pdf+0错) | 2→0 |
| 1706.03762 | zh | FAIL | missing_file:zhnumber.sty | 5 | 5 | clean (pdf+0错) | 2→0 |
| 1810.04805 | baseline | FAIL | missing_tfm:phvb | 5 | 7 | clean (pdf+0错) | 3→0 |
| 1810.04805 | ctex | FAIL | missing_file:zhnumber.sty | 7 | 9 | clean (pdf+0错) | 2→0 |
| 1810.04805 | zh | FAIL | missing_file:zhnumber.sty | 7 | 9 | clean (pdf+0错) | 2→0 |
| 1906.08237 | baseline | FAIL | missing_file:ifmtarg.sty | 3 | 7 | clean (pdf+0错) | 2→0 |
| 1906.08237 | ctex | FAIL | missing_file:zhnumber.sty | 6 | 9 | clean (pdf+0错) | 2→0 |
| 1906.08237 | zh | FAIL | missing_file:zhnumber.sty | 6 | 9 | clean (pdf+0错) | 2→0 |
| 2005.11401 | baseline | FAIL | None: | 1 | 3 | clean (pdf+0错) | 0→0 |
| 2005.11401 | ctex | FAIL | missing_file:zhnumber.sty | 3 | 5 | clean (pdf+0错) | 2→0 |
| 2005.11401 | zh | FAIL | missing_file:zhnumber.sty | 3 | 5 | 带错出pdf (>3错) | 2→6 |
| 2106.09685 | baseline | FAIL | missing_tfm:phvb | 2 | 4 | clean (pdf+0错) | 2→0 |

## 3. 按首错类别的修复成功率

| 首错类别 | 格数 | 救回pdf | 干净(≤3错) | 主要动作 |
|---|---|---|---|---|
| missing_sty | 16 | 16 | 15 | install_file×24, install_sysfont×14, install_tfm×9 |
| missing_tfm | 4 | 4 | 4 | install_tfm×4, install_file×2, px_to_bp×1 |
| none | 1 | 1 | 1 |  |
| pdftex_prim | 1 | 1 | 1 | pdftex_prim_guard×1 |

## 4. 规则表与触发统计

| 规则 | 触发次数 | 所在格最终出pdf | 说明 |
|---|---|---|---|
| `static_precheck` | 22 | 22 | 静态预检: 扫 \usepackage/\RequirePackage/\documentclass → kpsewhich 验证 → 批量 tlmgr install (第0招, 不进循环) |
| `install_file` | 26 | 17 | 缺文件(.sty/.cls/.fd/.def…) → tlmgr search --global --file '/X' → --usermode install → kpsewhich 复核 |
| `install_tfm` | 13 | 13 | 缺TFM字体(Font X not loadable) → 搜 '/{font}.tfm' → 装包 + updmap-user |
| `install_sysfont` | 14 | 14 | fontspec 'font X cannot be found' → 搜 '/{X}.otf|.ttf|.ttc' → 装包 + updmap-user |
| `missing_pfb_updmap` | 0 | 0 | xdvipdfmx 物理字体缺失 → updmap-user 重建 map |
| `pdftex_prim_guard` | 3 | 3 | pdfTeX 原语裸用(\pdfoutput 等11个) → \ifdefined 守卫包裹 |
| `px_to_bp` | 3 | 3 | 非法单位 px → ×0.75 换算 bp (CSS 96dpi) |
| `microtype_off` | 4 | 4 | XeTeXglyph×TFM → microtype [protrusion=false,expansion=false] |
| `times_to_newtx` | 0 | 0 | times/mathptmx → newtxtext/newtxmath |
| `hyphenation_sane` | 1 | 1 | \hyphenation{} 参数剥离非拉丁 token |
| `soul_cjk_mbox` | 0 | 0 | soul 族(\hl\ul\st\so\caps) 参数含 CJK → \mbox 包裹 |
| `thm_sibling_strip` | 0 | 0 | thmtools sibling= 定理计数器冲突 → 剥 sibling 选项 |
| `option_clash_merge` | 0 | 0 | Option clash → 同名包多次加载合并选项 |
| `minted_frozencache` | 0 | 0 | minted frozencache → 有 pygmentize 才去选项(本机无→放弃) |
| `latex209_reject` | 0 | 0 | \documentstyle/LaTeX2.09 → 标记拒绝, 路由 latex+dvips |
| `undefined_cs_guess` | 0 | 0 | 未定义 cs → 占位(需要 cs→包 知识库, 未实现) |

## 5. 修不动的 case

(除路由拒绝对象外全部出pdf)

带错出pdf (>3错, 未达 clean 阈值):
- 2005.11401/zh: 6 errs 终错 `soul_err`
