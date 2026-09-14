# 编译 Benchmark 报告: 真实 arXiv 源码注入 ctex 重编译成功率

- 语料: `/Users/fanghaotian/src/texlate/bench/corpus` — 12 个 arXiv 项目
- 引擎: Tectonic 0.17.0 vs XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026)
- 条件: baseline(原文) / ctex(注入 `\usepackage[fontset=fandol,UTF8]{ctex}`) / zh(英文段落→中文+ctex)
- 判据: 超时 120s; **pdf**=产出PDF; **clean**=全程无 `!` 错误; xelatex `-interaction=nonstopmode` 最多2遍; tectonic `-Z continue-on-errors` (≈nonstopmode)
- 日期: 2026-09-14 15:07

## 1. 总成功率 (12 项目)

| 引擎 | 条件 | pdf 产出 | clean |
|---|---|---|---|
| tectonic | baseline | 9/12 | 7/12 |
| tectonic | ctex | 9/12 | 4/12 |
| tectonic | zh | 9/12 | 2/12 |
| xelatex (原始环境) | baseline | 2/12 | 0/12 |
| xelatex (原始环境) | ctex | 2/12 | 0/12 |
| xelatex (原始环境) | zh | 2/12 | 0/12 |
| xelatex (修复后) | baseline | 11/12 | 7/12 |
| xelatex (修复后) | ctex | 11/12 | 4/12 |
| xelatex (修复后) | zh | 11/12 | 1/12 |

## 2. 逐项目矩阵

PDF=干净出pdf, pdf~=带错误出pdf, FAIL=无pdf; xelatex 列为修复后最终态

| 项目 | base-t | base-x | ctex-t | ctex-x | zh-t | zh-x |
|---|---|---|---|---|---|---|
| 1412.6980 | pdf~ | pdf~ | pdf~ | pdf~ | pdf~ | pdf~ |
| 1511.06432 | PDF | pdf~ | PDF | pdf~ | PDF | pdf~ |
| 1512.03385 | PDF | PDF | PDF | PDF | pdf~ | pdf~ |
| 1706.03762 | PDF | PDF | pdf~ | pdf~ | pdf~ | pdf~ |
| 1810.04805 | FAIL | pdf~ | FAIL | pdf~ | FAIL | pdf~ |
| 1906.08237 | PDF | PDF | pdf~ | pdf~ | pdf~ | pdf~ |
| 2005.11401 | PDF | PDF | PDF | PDF | pdf~ | pdf~ |
| 2106.09685 | PDF | PDF | PDF | PDF | PDF | PDF |
| 2203.02155 | PDF | PDF | pdf~ | pdf~ | pdf~ | pdf~ |
| 2305.14335 | FAIL | PDF | FAIL | PDF | FAIL | pdf~ |
| 2501.14787 | pdf~ | pdf~ | pdf~ | pdf~ | pdf~ | pdf~ |
| hep-th | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL |

## 3. 失败分类学

| 类别 | 次数(失败) | 代表错误 | 涉及项目 |
|---|---|---|---|
| missing_package | 72 | `! LaTeX Error: File `tabulary.sty' not found.` | 1512.03385, 1706.03762, 1810.04805, 1906.08237 |
| missing_class | 36 | `! LaTeX Error: File `ptptex.cls' not found.` | hep-th |
| pdftex_prim | 33 | `! Undefined control sequence.` | 2501.14787 |
| missing_font | 9 | `! Font \cvprtenhv=phvb at 8.0pt not loadable: Metric (TFM) file or ins` | 1512.03385, 1810.04805, 2106.09685 |
| syntax | 5 | `! Illegal unit of measure (pt inserted).` | 1810.04805, 2305.14335 |
| latex209 | 3 | `! LaTeX Error: LaTeX2e command \ensuremath in LaTeX 2.09 document.` | hep-th |
| hyphenation | 1 | `! Not a letter.` | 2305.14335 |

### 带错误但出 pdf 的类别

| 类别 | 次数 | 代表错误 | 涉及项目 |
|---|---|---|---|
| missing_font | 17 | `! Font \iclrtenhv=phvb at 8.0pt not loadable: Metric (TFM) file or ins` | 1511.06432, 1706.03762, 1906.08237, 2203.02155 |
| pdftex_prim | 6 | `! Undefined control sequence.` | 1412.6980, 2501.14787 |
| undefined_cs | 6 | `! Undefined control sequence.` | 1412.6980, 2501.14787 |
| hyphenation | 4 | `! Not a letter.` | 1512.03385, 2305.14335 |
| syntax | 3 | `! Illegal unit of measure (pt inserted).` | 1810.04805 |
| soul_cjk | 2 | `! Package soul Error: Reconstruction failed.` | 2005.11401 |

## 4. ctex/zh 注入新增错误 (首错与 baseline 不同)

### ctex

- `1706.03762` tectonic: `! Cannot use XeTeXglyph with ptmr8c; not a native platform font.`
- `1906.08237` tectonic: `! Cannot use XeTeXglyph with ptmr8c; not a native platform font.`
- `2203.02155` tectonic: `! Cannot use XeTeXglyph with ptmr8c; not a native platform font.`
- `hep-th` tectonic: `! LaTeX Error: LaTeX2e command \usepackage in LaTeX 2.09 document.`

### zh

- `1512.03385` tectonic: `! Not a letter.`
- `1706.03762` tectonic: `! Cannot use XeTeXglyph with ptmr8c; not a native platform font.`
- `1906.08237` tectonic: `! Cannot use XeTeXglyph with ptmr8c; not a native platform font.`
- `2005.11401` tectonic: `! Package soul Error: Reconstruction failed.`
- `2203.02155` tectonic: `! Cannot use XeTeXglyph with ptmr8c; not a native platform font.`
- `2305.14335` tectonic: `! Not a letter.`
- `hep-th` tectonic: `! LaTeX Error: LaTeX2e command \usepackage in LaTeX 2.09 document.`

## 5. 原始记录
```json
{
 "1412.6980": {
  "main": "arxiv.tex",
  "class": "\\documentclass[a4paper]{article}",
  "runs": {
   "baseline": {
    "tectonic": {
     "pdf": true,
     "clean": false,
     "n_errors": 25,
     "cat2": "undefined_cs",
     "pkg2": null,
     "first_error": "! Undefined control sequence.",
     "seconds": 0.7211267948150635
    },
    "xelatex": {
     "pdf": true,
     "clean": false,
     "n_errors": 4,
     "cat2": "pdftex_prim",
     "pkg2": "output",
     "first_error": "! Undefined control sequence.",
     "seconds": 12.130213260650635
    }
   },
   "ctex": {
    "tectonic": {
     "pdf": true,
     "clean": false,
     "n_errors": 25,
     "cat2": "undefined_cs",
     "pkg2": null,
     "first_error": "! Undefined control sequence.",
     "seconds": 1.1541380882263184
    },
    "xelatex": {
     "pdf": true,
     "clean": false,
     "n_errors": 4,
     "cat2": "pdftex_prim",
     "pkg2": "output",
     "first_error": "! Undefined control sequence.",
     "seconds": 11.098964929580688
    }
   },
   "zh": {
    "tectonic": {
     "pdf": true,
     "clean": false,
     "n_errors": 25,
     "cat2": "undefined_cs",
     "pkg2": null,
     "first_error": "! Undefined control sequence.",
     "seconds": 1.1098439693450928
    },
    "xelatex": {
     "pdf": true,
     "clean": false,
     "n_errors": 4,
     "cat2": "pdftex_prim",
     "pkg2": "output",
     "first_error": "! Undefined control sequence.",
     "seconds": 11.658396005630493
    }
   }
  }
 },
 "1511.06432": {
  "main": "iclr2016_conference.tex",
  "class": "\\documentclass{article} % For LaTeX2e",
  "runs": {
   "baseline": {
    "tectonic": {
     "pdf": true,
     "clean": true,
     "n_errors": 0,
     "cat2": null,
     "pkg2": null,
     "first_error": null,
     "seconds": 20.767131805419922
    },
    "xelatex": {
     "pdf": true,
     "clean": false,
     "n_errors": 2,
     "cat2": "missing_font",
     "pkg2": null,
     "first_error": "! Font \\iclrtenhv=phvb at 8.0pt not loadable: Metric (TFM) file or installed fo",
     "seconds": 4.360704660415649
    }
   },
   "ctex": {
    "tectonic": {
     "pdf": true,
     "clean": true,
     "n_errors": 0,
     "cat2": null,
     "pkg2": null,
     "first_error": null,
     "seconds": 1.9052560329437256
    },
    "xelatex": {
     "pdf": true,
     "clean": false,
     "n_errors": 2,
     "cat2": "missing_font",
     "pkg2": null,
     "first_error": "! Font \\iclrtenhv=phvb at 8.0pt not loadable: Metric (TFM) file or installed fo",
     "seconds": 7.056084871292114
    }
   },
   "zh": {
    "tectonic": {
     "pdf": true,
     "clean": true,
     "n_errors": 0,
     "cat2": null,
     "pkg2": null,
     "first_error": null,
     "seconds": 3.263183832168579
    },
    "xelatex": {
     "pdf": true,
     "clean": false,
     "n_errors": 2,
     "cat2": "missing_font",
     "pkg2": null,
     "first_error": "! Font \\iclrtenhv=phvb at 8.0pt not loadable: Metric (TFM) file or installed fo",
     "seconds": 5.513240098953247
    }
   }
  }
 },
 "1512.03385": {
  "main": "residual_v1_arxiv_release.tex",
  "class": "\\documentclass[10pt,twocolumn,letterpaper]{article}",
  "runs": {
   "baseline": {
    "tectonic": {
     "pdf": true,
     "clean": true,
     "n_errors": 0,
     "cat2": null,
     "pkg2": null,
     "first_error": null,
     "seconds": 22.04182004928589
    },
    "xelatex": {
     "pdf": false,
     "clean": false,
     "n_errors": 3,
     "cat2": "missing_font",
     "pkg2": null,
     "first_error": "! Font \\cvprtenhv=phvb at 8.0pt not loadable: Metric (TFM) file or installed fo",
     "seconds": 0.6054830551147461
    },
    "xelatex_r1": {
     "pdf": false,
     "clean": false,
     "n_errors": 2,
     "cat2": "missing_package",
     "pkg2": "tabulary.sty",
     "first_error": "! LaTeX Error: File `tabulary.sty' not found.",
     "seconds": 0.27926015853881836
    },
    "xelatex_r2": {
     "pdf": true,
     "clean": true,
     "n_errors": 0,
     "cat2": null,
     "pkg2": null,
     "first_error": null,
     "seconds": 5.367026329040527
    }
   },
   "ctex": {
    "tectonic": {
     "pdf": true,
     "clean": true,
     "n_errors": 0,
     "cat2": null,
     "pkg2": null,
     "first_error": null,
     "seconds": 4.749580144882202
    },
    "xelatex": {
     "pdf": false,
     "clean": false,
     "n_errors": 3,
     "cat2": "missing_font",
     "pkg2": null,
     "first_error": "! Font \\cvprtenhv=phvb at 8.0pt not loadable: Metric (TFM) file or installed fo",
     "seconds": 1.3358941078186035
    },
    "xelatex_r1": {
     "pdf": false,
     "clean": false,
     "n_errors": 2,
     "cat2": "missing_package",
     "pkg2": "tabulary.sty",
     "first_error": "! LaTeX Error: File `tabulary.sty' not found.",
     "seconds": 1.138535976409912
    },
    "xelatex_r2": {
     "pdf": true,
     "clean": true,
     "n_errors": 0,
     "cat2": null,
     "pkg2": null,
     "first_error": null,
     "seconds": 7.380674123764038
    }
   },
   "zh": {
    "tectonic": {
     "pdf": true,
     "clean": false,
     "n_errors": 2,
     "cat2": "hyphenation",
     "pkg2": null,
     "first_error": "! Not a letter.",
     "seconds": 2.3812379837036133
    },
    "xelatex": {
     "pdf": false,
     "clean": false,
     "n_errors": 3,
     "cat2": "missing_font",
     "pkg2": null,
     "first_error": "! Font \\cvprtenhv=phvb at 8.0pt not loadable: Metric (TFM) file or installed fo",
     "seconds": 2.234266996383667
    },
    "xelatex_r1": {
     "pdf": false,
     "clean": false,
     "n_errors": 2,
     "cat2": "missing_package",
     "pkg2": "tabulary.sty",
     "first_error": "! LaTeX Error: File `tabulary.sty' not found.",
     "seconds": 0.9586429595947266
    },
    "xelatex_r2": {
     "pdf": true,
     "clean": false,
     "n_errors": 4,
     "cat2": "hyphenation",
     "pkg2": null,
     "first_error": "! Not a letter.",
     "seconds": 7.382426977157593
    }
   }
  }
 },
 "1706.03762": {
  "main": "ms.tex",
  "class": "\\documentclass
```
