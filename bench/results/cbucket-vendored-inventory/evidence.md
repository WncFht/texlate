# Vendored 件取证（2026-09-17）

`files/` = vendored 真件（8 件，peer1 机制件照此平移）；`files/_stubref/` = 非 vendored 但已取真件作 stub 设计参照（5 件）。fetch_failed 2 件：espcrc2.sty、texsort.sty（均降 stub）。

## files/ vendored 真件（8）

### aastex.cls（66KB，v5.2 时代真件）

- 来源：`bench/corpus_v3/1003.0049/extracted/aastex.cls`（arXiv e-print 自带件；备选同档 1502.01989/1109.2053/1306.0346）
- 许可行（L44-48）：`copyright = "Copyright (C) 2003 American Astronomical Society ... This work may be distributed and/or modified under the conditions of the LaTeX Project Public License, either version 1.3 of this license or (at your option) any later version. The latest version of this license is in http://www.latex-project.org/lppl.txt`
- 判定：**LPPL-1.3 → vendored**。佐证：CTAN pkg aastex 现行版（aastex701.cls）同标 LPPL-1.3c。

### aastex62.cls（210KB）

- 来源：`https://journals.aas.org/wp-content/uploads/2018/08/aastex62.cls`（AAS 官网 classfile-only 直链，页面 journals.aas.org/aastex-package-for-manuscript-preparation/）
- 许可：AASTeX62 系 AAS 发行，同族 LPPL（件头在 \ProvidesClass 前版权声明段，取件时留 AAS 直链为证）
- 判定：**vendored**

### psfig.sty（29KB）

- 来源：`https://mirrors.ctan.org/graphics/psfig/psfig.sty`（CTAN 现行档，pkg 页 license=nosell）
- 许可行（L8-10）：`Permission is granted for use and non-profit distribution of psfig/tex ... The right to distribute any portion of psfig/tex for profit or as part of any commercial product is specifically reserved for the author(s)`
- 判定：**非盈利再分发明示允许 → vendored**（nosell 许可；我们非营利 shim 用途合规）

### iopart.cls（40KB）

- 来源：`https://git0.fmf.uni-lj.si/horvat/qra/raw/abb7e635f02d2972f7ee0bbe60cb735429534271/paper_MD/iopart.cls`（Ljubljana git mirror；IOP 官方渠道 publishingsupport.iopscience.iop.org 模板 zip 同源）
- 许可行（头部）：`Licensed under the LPPL: http://www.latex-project.org/lppl.txt / Current Maintainer: IOP Publishing Ltd`
- 判定：**LPPL → vendored**（IOP 文章版权政策与 cls 文件许可无关——侦察翻转已坐实）

### iopams.sty（3KB）

- 来源：同 mirror `paper_MD/iopams.sty`
- 许可：件头无独立许可行；为 iopart 发行套件随件（iopart.cls LPPL 覆盖 "all files listed in the work"）
- 判定：**随 iopart LPPL → vendored**（备注：若想更稳可让 stub 化 amsgen/amsfonts 需求——件本身 \RequirePackage 四个 AMS 包，TL 都有）

### elsart.cls（54KB）

- 来源：`https://hallaweb.jlab.org/experiment/E05-007/paper/som%5Fv1%5FRM/elsart.cls`（JLab mirror；原 CTAN `/macros/latex/contrib/supported/elsevier` 已撤档，wayback/各镜像同源）
- 许可行（头部）：`elsart.cls Copyright (C) 1994-2001 Elsevier Science ... This file may be distributed and/or modified under the conditions of the LaTeX Project Public License, either version 1.2`
- 判定：**LPPL-1.2 → vendored**

### emulateapj.sty（41KB）

- 来源：`bench/corpus_v3/1306.0013/extracted/emulateapj.sty`（arXiv 自带件；备选 astro-ph/0104161/9901371/9910351）。注意 CTAN pkg emulateapj 只发 emulateapj.cls，无 .sty——真件就得走 arXiv 自带件。
- 许可行（L61-64）：`This program can be redistributed and/or modified under the terms of the LaTeX Project Public License available from CTAN archives in directory macros/latex/base/lppl.txt. This means you are free to use and distribute this package; however, if you modify anything, please change the ...`
- 判定：**LPPL → vendored**

### emulateapj5.sty（26KB）

- 来源：`bench/corpus_v3/astro-ph/0408531/extracted/emulateapj5.sty`（备选 corpus_v2 astro-ph/0305062、corpus_v3 astro-ph/0104174/0806.3090）
- 许可行（L116-119）：同 emulateapj LPPL 段（`Copyright 2000-2001 Alexey Vikhlinin ... redistributed and/or modified under the terms of the LaTeX Project Public License`）
- 判定：**LPPL → vendored**

## files/_stubref/（取到真件但不可 vendored → 留作 stub 设计参照）

| 件 | 来源 | 许可行原文 | 判定 |
|---|---|---|---|
| espcrc1.sty | corpus_v3/1306.0085（备选 nucl-ex/9910015） | `% You are NOT ALLOWED to distribute this file alone. You are NOT ALLOWED to take money for the distribution ... allowed to distribute this file under the condition that it is distributed together with espcrc1.tex.` | **stub**（Elsevier 明示不可独立分发） |
| citesort.sty | CTAN obsolete latex209/contrib/misc/citesort.sty | 无许可行——`Based on cite.sty by Donald Arseneau ... -- Donald Arseneau 1989`（衍生无授权文） | **stub**（无显式授权） |
| eqsecnum.sty | CTAN obsolete latex209/contrib/aasmacros/eqsecnum.sty | 无许可行（596B 小件） | **stub** |
| apjfonts.sty | corpus_v3/1306.0013（备选 0806.2882/0806.0627/1706.07875） | 无许可行——`Alexey Vikhlinin / Maxim Markevitch ... Report any bugs`（1996 非授权文本） | **stub**（无显式授权；字体替身成本极低） |
| aasms4.sty | corpus_v3/0806.3090（备选 astro-ph/0104060） | `Copyright \cpr@year\space by the ASP.`（© ASP 随件宏） | **stub**（原属 stub 组，顺手取真件供 stub 面设计） |

## fetch_failed（→ stub 组）

- **espcrc2.sty**（55 格）：CTAN contrib+obsolete 无档，corpus 无自带件；同族 espcrc1 许可已证 Elsevier 禁独立分发，本就走 stub。
- **texsort.sty**（16 格）：CTAN obsolete latex209 misc/aasmacros 无档，corpus 无件；stub 成本极低（cite 排序 no-op）。
- **imsart.cls**（14 格）：CTAN API 无此包（此前 dispositions 标 vendored 有误——imsart 由 VTEX/IMS 直发，许可核不到）→ **stub**。

## 判定汇总

- vendored 真件 8 件落位 `files/`：覆盖 aastex.cls 257 + aastex62 9 + psfig 188(+18) + iopart 133 + iopams 60 + elsart 87 + emulateapj 12 + emulateapj5 8 ≈ **772 首命格**。
- _stubref 5 件供 stub 面设计；stub 组新增 espcrc×2/citesort/texsort/eqsecnum/apjfonts/imsart/aasms4（后者原已 stub）。
