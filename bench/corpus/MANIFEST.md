# Corpus Manifest — arXiv LaTeX 源码语料

真实 arXiv e-print 源码(`arxiv.org/e-print/{id}` 解压，未修改)。用于 LaTeX 解析库 benchmark + ctex 注入重编译 benchmark。
旧版 ID(`math/0404188`、`hep-th/9901001`)按类别嵌套存放，与 arXiv 目录结构一致。

## 原有语料 (12)

| ID | 类 | 特征 |
|---|---|---|
| 1412.6980 | article | Adam 优化器 |
| 1511.06432 | article (ICLR'16) | ICLR 模板 |
| 1512.03385 | article (CVPR) | ResNet,babel |
| 1706.03762 | article | Attention Is All You Need，多文件 \input |
| 1810.04805 | article | BERT，多文件，tikz |
| 1906.08237 | article (NeurIPS'19) | 自带 math_commands.tex 宏 |
| 2005.11401 | article (NeurIPS'20) | GPT-3,subfig |
| 2106.09685 | article (ICLR'22) | algorithmic |
| 2203.02155 | article (NeurIPS'21) | subcaption |
| 2305.14335 | IEEEtran[journal] | 自带 IEEEtran.cls |
| 2501.14787 | article | MIT 讲义 118 文件，minted+frozencache，自带 lindrew.sty/kbordermatrix.sty |
| hep-th/9901001 | ptptex (LaTeX 2.09!) | `\documentstyle`，epsf,EPS 图 |

## 新增 (27,2026-09-14)

### AMS 家族

| ID | 标题 | 类 | 特征构造 | 文件数 | 大小 |
|---|---|---|---|---|---|
| math/0404188 | The primes contain arbitrarily long arithmetic progressions (Green–Tao) | `amsart[12pt,a4paper,reqno]` | amsthm 定理环境(proposition/lemma/theorem/conjecture)，内嵌 .bbl,\def 宏 | 1 | 192K |
| 1111.4914 | Perfectoid Spaces (Scholze) | `amsart[a4paper,reqno,11pt]` | PhD thesis(文件名 PhDThesis.tex),75 处 newtheorem/theorem/proof,xypic,babel | 4 | 224K |
| 2512.03164 | A Cut-Free Sequent Calculus… | `amsart[11pt]` | **bussproofs 重度：153×prooftree env**,tkz-euclide,modalops,listings,stmaryrd,framed | 5 | 268K |
| 2602.09511 | Invariance galoisienne des zéros centraux… | `amsart[12pt,french]` | **法语论文**:`[french]{babel}`(激活 `;:!?` shorthand),1033 行非 ASCII(é à ç 等 UTF-8),tikz | 3 | 320K |

### REVTeX 三代同堂

| ID | 标题 | 类 | 特征构造 | 文件数 | 大小 |
|---|---|---|---|---|---|
| 1403.3985 | Detection of B-mode… (BICEP2) | `revtex4-1[prd,reprint,superscriptaddress,bibnotes]` | 自带 revtex4-1.cls + apsrev4-1.bst,showpacs | 21 | 2.0M |
| 0906.1291 | Small-ε behavior of Non-Hermitian PT-Symmetric… | `revtex4`(原版!) | aps/pre,tightenlines,titlepage 选项 | 2 | 112K |
| 2308.07483 | The Scale Invariant Vacuum Paradigm | `revtex4-2[aip,cp,reprint]` | **documentclass 参数被注释穿插**(aip/jmp/bmf/sd/rsi 五选一注释),mathptmx | 7 | 1.1M |

### 天文/物理学会类

| ID | 标题 | 类 | 特征构造 | 文件数 | 大小 |
|---|---|---|---|---|---|
| 1801.02634 | The Astropy Project v2.0 | `aastex61[modern]` | 自带 aastex61.cls + aasjournal.bst,registry 表格文件 | 22 | 1.9M |
| 1502.01589 | Planck 2015 cosmological parameters | `aa[referee,traditabstract,longauth]` | 自带 aa.cls + 2 bst,**103 文件/35 tex**,9×\input | 103 | 14M |
| 1207.7214 | Observation of a new boson at 125 GeV (ATLAS) | `elsarticle[final,3p,times,twocolumn]` | Elsevier elsarticle,\papertitle 宏间接化，subfig | 20 | 2.6M |
| 2609.09529 | Frobenius–Galois expansions of substructural logics | `elsarticle[final,12pt,times]` | **中文注释** `% 引入booktabs包`,Unicode弯引号,listings,algorithmic,tikz,xypic,epsfig,stmaryrd,latexsym(废弃包三连) | 2 | 140K |
| 1207.7235 | Observation of a new boson at 125 GeV (CMS) | `cms-tdr[cmspaper]` | CMS 私类，\GeV 等物理单位宏 | 31 | 2.2M |
| 0906.4725 | Interacting Quantum Observables (ZX-calculus) | `iopart` | 自带 iopart.cls + iopams.sty + setstack.sty,**xy/xymatrix 交换图**,epsfig,**1134 个 PDF 图文件** | 1142 | 7.2M |

### ACM/Springer 类

| ID | 标题 | 类 | 特征构造 | 文件数 | 大小 |
|---|---|---|---|---|---|
| 1712.01208 | The Case for Learned Index Structures | `acmart[sigconf]` | ACM sigconf,algorithm2e,12 tex 文件 | 27 | 1.2M |
| 2201.05989 | Instant Neural Graphics Primitives (Instant-NGP) | `acmart[acmtog,authorversion,nonacm]` + `cvpr` | **双 documentclass 双版本**(camera.tex=CVPR / paper.tex=TOG),**algorithm2e[ruled]**,pgfplots groupplots,80×tikz,Figures/ 独立 tikzpicture 文件 | 119 | 19M |
| 2602.19229 | Hypersequent Calculi Have Ackermannian Complexity | `acmart[manuscript,screen,review]` | **bussproofs:152×AxiomC**,tex/ 子目录组织 | 17 | 360K |
| 2609.08578 | Erased Postulates, Identity Types and Quotients (Cubical Agda) | `acmart[acmsmall,authorversion,nonacm]` | **agda.sty(Agda 生成的 LaTeX)**,newunicodechar 定义数学符号,**1264 行非 ASCII**(Agda Unicode),mathpartir×182 inferrule,polytable,ifxetex/ifluatex | 10 | 412K |
| 2003.08934 | NeRF (ECCV'20) | `llncs[runningheads]` | Springer LNCS，自带 splncs04.bst | 70 | 8.3M |

### 书/长文档/多文件

| ID | 标题 | 类 | 特征构造 | 文件数 | 大小 |
|---|---|---|---|---|---|
| 1106.1445 | From Classical to Quantum Shannon Theory (Wilde) | `book[12pt]` | **单文件 2.2MB**(qit-notes.tex),95 定理环境 | 120 | 6.8M |
| 1612.09375 | Basic Category Theory (Leinster) | `cambridge7A[spanningrule]` | Cambridge 出版社私类，**14×\include 章节组织** | 34 | 696K |
| 2609.06443 | Expressive power of one-shot control operators | `subfiles[./main.tex]` + `jfp-epi` | **subfiles 类多文件**(13 tex 各自可编译),mathpartir×53 inferrule | 16 | 476K |

### 编码/字体/图形坑

| ID | 标题 | 类 | 特征构造 | 文件数 | 大小 |
|---|---|---|---|---|---|
| 1902.03178 | Graph-theoretic Simplification of Quantum Circuits (ZX) | `quantumarticle[superscriptaddress,accepted=…]` | **678×tikz 引用**,tikzit+tikzstyles/tikzfigures 分离,algorithmicx+algpseudocode,babel,inputenc+fontenc | 148 | 1.3M |
| 0807.3917 | Channel polarization (Arikan, polar codes) | `IEEEtran[journal,letterpaper]` | **ISO-8859 编码非 UTF-8**(latin-5 字节 0xA8/0xFF),pstricks(dvips-only!),自带 IEEEtran.cls+stfloats+pstricks.sty,EPS 图 | 16 | 488K |
| 2602.06617 | Une formule des traces pour les espaces symétriques | `article[10pt,leqno]` | **法语**:`[french]{babel}`+utf8 inputenc+T1 fontenc,842 行非 ASCII | 3 | 416K |
| 1507.02284 | The Information Sieve (ICML'16) | `article` + icml2016.sty | **自带 4 个 .sty**(algorithm/algorithm2e/algorithmic/natbib),algorithmic env×3 | 528 | 11M |
| 2609.11777 | Differentially Private EEG Feature Anonymization | `article[11pt]` | **厨房水槽 preamble**:newclude(\include*),subfloat×6,longtable,rotating+pdflscape,algpseudocode,hyphenat[none],pifont | 17 | 11M |
| 2606.31863 | Most Properties are Undecidable for Transitive Tense Logics | `eptcs[submission,copyright,creativecommons]` | EPTCS 私类 + 自带 aiml26.sty,bussproofs preamble,00README.json | 8 | 108K |

## 维度覆盖表

| 目标维度 | 覆盖 |
|---|---|
| amsart/amsbook | math/0404188, 1111.4914, 2512.03164, 2602.09511(+amsart[french]) |
| REVTeX | revtex4-1 (1403.3985) + revtex4 (0906.1291) + revtex4-2 (2308.07483) 三代 |
| tikz/pgf 重度 | 1902.03178 (678×tikz+tikzstyles), 2201.05989 (pgfplots+80 tikz) |
| algorithm2e/algorithmicx/algorithmic | 2201.05989 (alg2e), 1902.03178 (algx/algpseudocode), 1507.02284+2609.11777 (algorithmic) |
| IEEEeqnarray/subfig/subfigure | 真用 IEEEeqnarray 的论文未找到(现代 IEEE 全用 align)；已有 0807.3917(IEEEtran+pstricks),2609.11777(subfloat×6),2005.11401(subfig),2203.02155(subcaption) |
| forest/bussproofs/prooftree | forest 本体未找到(多在语言学期刊，不上 arXiv 源码)；代替：2512.03164 (153 prooftree), 2602.19229 (152 AxiomC), 2609.06443+2609.08578 (mathpartir inferrule), 2606.31863 (bussproofs preamble) |
| beamer/thesis/书 | beamer 未找到(arXiv 几乎无 slides 源码)；代替：book (1106.1445), cambridge7A (1612.09375), amsart PhD thesis (1111.4914) |
| 非英文/非 ASCII | 2602.09511+2602.06617 (法语 babel+UTF-8), 2609.09529 (中文注释), 0807.3917 (latin-5 编码), 2609.08578 (Agda Unicode) |
| acmart | 1712.01208 (sigconf), 2201.05989 (acmtog), 2602.19229 (manuscript), 2609.08578 (acmsmall) 四种模式 |
| aastex/elsarticle/svjour | aastex61 (1801.02634), aa (1502.01589), elsarticle (1207.7214+2609.09529);svjour 未找到(EPJ/Springer 数学稿多用私类) |
| includeonly/subimport/standalone | 2609.06443 (subfiles 类!), 1612.09375 (\include×14), 2609.11777 (newclude\include*) |
| minted/listings | 2512.03164+2609.09529 (listings), 2501.14787 (minted,原有) |
| >500KB 单 tex | 1106.1445 (qit-notes.tex 2.2MB!) |
| pdflatex-only (inputenc/fontenc) | 1902.03178, 2602.06617, 2308.07483, 1801.02634, 2609.11777 等 |
| fontspec/polyglossia/babel | babel: 2602.09511/2602.06617/1902.03178/1111.4914/2609.11777;fontspec/polyglossia 未找到(XeLaTeX 稿在 arXiv 极稀有，找到的都是注释掉的) |
| 额外赠送坑 | xy/xymatrix+epsfig (0906.4725), pstricks dvips-only (0807.3917), 双 documentclass (2201.05989), cms-tdr/eptcs/jfp-epi/lmcs 私类, latin-5 编码, Agda Unicode, 中文注释, 注释穿插的 documentclass (2308.07483) |

## 下载方法备注

- `curl -A "Mozilla/5.0…" https://arxiv.org/e-print/{id}` + `tar xzf`
- 限速：e-print 3–6s/次;API/list 页更易触发 "Rate exceeded"（多次被封后等 60–90s)
- **macOS bsdtar 坑**：单文件 gzipped tex 会被误识别为 mtree 解压成"每行一个文件"，须改用 `gunzip`（本语料已清理）
- PDF-only 无源码而放弃的：1602.03837 (GW150914), 1906.11238 (EHT M87-I), 1610.07594, 1409.4222
