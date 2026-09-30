# vendor/ MANIFEST — offline LaTeX package assets for fixloop

`vendor/` ships package assets fixloop drops into a workdir when a missing
file cannot be installed (off-CTAN / legacy packages with no TeX Live
source). `_vendored_source` resolves a missing-file payload by basename,
`files/`→`stubs/`→`shims/` order, casefold fallback, bare names also try
`+.tex`. Served by `vendored_fetch`/`_multi`, `legacy_pkg_shim`
(`rules/90-shim-legacy.yaml`), and rules/builtins naming files below.
`files/` = real upstream files (per-file license checked); `stubs/` =
texlate minimal macro-surface stubs; `shims/` = texlate `.cls` stand-ins
(originals not redistributable). cl `a`=named in code/rules (evidence
file:line, `+N`=more); `b`=basename-reachable — `lib` stock / `twin:`
byte-copy / `dep:` vendored sibling loads it (`~name`=stem match,
`*`=constructed name); `c`=orphan (none). files 183 (a49/b134), shims 15
(a14/b1), stubs 32 (a20/b12). `repository.md` §2.7's 183/9/26 is stale —
this file is authoritative. Generated 2026-09-30; full census +sha256:
`tmp/vendor-census-20260930.jsonl` (ephemeral). Regenerate:
`python3 tools/vendor_census.py` (census files, parse first
`\ProvidesX{name}[ver]`/`{n}{date}{v}`, grep basenames in `fixloop/**/*.py`,
`fixloop/rules/*.yaml`, `compile/**/*.py`, sibling files for inter-vendor
loads incl. constructed `jabbrv-ltwa-\jabbrv@lang.ldf`).

## `files/`

| path                          |  bytes | \ProvidesX                        | cl  | evidence                                        |
| ----------------------------- | -----: | --------------------------------- | --- | ----------------------------------------------- |
| `IEEEconf.cls`                |   6629 | IEEEconf@2009/04/05 v1.4 IEEE Co… | a   | compile/fixloop/builtins/vendored.py:476        |
| `VCColor-names.def`           |   3931 | —                                 | b   | dep:files/vaucanson-g.sty+1                     |
| `VCPref-beamer.tex`           |   1374 | —                                 | b   | dep:files/VCPref-slides.tex~VCPref-beamer+2     |
| `VCPref-default.tex`          |   5984 | —                                 | b   | dep:files/vaucanson-g.sty+1                     |
| `VCPref-mystyle.tex`          |   3360 | —                                 | b   | dep:files/VCPref-default.tex~VCPref-mystyle+2   |
| `VCPref-slides.tex`           |   1390 | —                                 | b   | dep:files/VCPref-beamer.tex~VCPref-slides+2     |
| `Vaucanson-G.tex`             |  43530 | —                                 | b   | dep:files/VCColor-names.def~Vaucanson-G+4       |
| `aapm4-2.rtx`                 |  17058 | aapm4-2.rtx                       | b   | lib                                             |
| `aastex.cls`                  |  66189 | aastex@2005/06/22 5.2/AAS markup… | a   | compile/fixloop/rules/40-install.yaml:336+13    |
| `aastex62.cls`                | 203680 | aastex62@2017/10/16 Version 6.2/… | a   | compile/fixloop/rules/75-syntax.yaml:542+2      |
| `aeguill.sty`                 |   5629 | aeguill@2003/08/02 1.02 % AE fon… | b   | lib                                             |
| `aip4-2.rtx`                  |  31338 | aip4-2.rtx@2022/06/05 4.2f AIP s… | b   | lib                                             |
| `aligned-overset.sty`         |   2882 | aligned-overset@2018/04/04        | b   | lib                                             |
| `aps10pt4-2.rtx`              |   4721 | aps10pt4-2@2022/06/05 4.2f (http… | b   | lib                                             |
| `aps11pt4-2.rtx`              |   4885 | aps11pt4-2@2022/06/05 4.2f (http… | b   | lib                                             |
| `aps12pt4-2.rtx`              |   4805 | aps12pt4-2@2022/06/05 4.2f (http… | b   | lib                                             |
| `aps4-2.rtx`                  |  16396 | aps4-2@2022/06/05 4.2f (https://… | b   | lib                                             |
| `apsrmp4-2.rtx`               |   7653 | apsrmp4-2@2022/06/05 4.2f (https… | b   | lib                                             |
| `ascmac.sty`                  |    590 | ascmac@2020/01/15 v2.1 ascmac wr… | b   | dep:files/tascmac.sty                           |
| `autobreak.sty`               |   8266 | autobreak@2017/02/23 v0.3 simple… | b   | lib                                             |
| `axodraw2.sty`                | 137039 | axodraw2@2018/10/10 v2.1.2        | b   | dep:stubs/axodraw.sty~axodraw2                  |
| `bpchem.sty`                  |   7752 | bpchem@2004/08/21 v1.1 Chemical … | b   | lib                                             |
| `ccfonts.sty`                 |   3370 | ccfonts@2020/03/25 v1.2 (WaS)     | b   | lib                                             |
| `chemformula.sty`             | 120104 | chemformula@\c_chemformula_date_… | b   | lib                                             |
| `chessfss.sty`                |  25613 | chessfss@2006/06/14 v1.2a chess … | b   | dep:files/skak.sty~chessfss                     |
| `citehack.sty`                |   3476 | citehack                          | b   | lib                                             |
| `complexity.sty`              |  26143 | complexity@09/16/17 \space v0.81a | b   | dep:files/pst-tools.tex~complexity              |
| `csvsimple-l3.sty`            |  47780 | csvsimple-l3@2024/09/27           | a   | compile/fixloop/builtins/vendored.py:45+7       |
| `delimset.sty`                |  17403 | delimset@2026-03-26 v2.3.1 conve… | b   | lib                                             |
| `derivative.sty`              |  58190 | derivative@2024/02/08             | b   | dep:files/pstricks-add.tex~derivative           |
| `dhucs.sty`                   |   4770 | dhucs@2015/08/21 v5.4 typesettin… | b   | lib                                             |
| `diagxy.tex`                  |  49248 | —                                 | b   | lib                                             |
| `dirtree.sty`                 |   1883 | dirtree@\filedate\space v\fileve… | b   | dep:files/dirtree.tex                           |
| `dirtree.tex`                 |   5890 | —                                 | b   | dep:files/dirtree.sty                           |
| `ecltree.sty`                 |   4680 | —                                 | b   | lib                                             |
| `elsart.cls`                  |  54373 | \@shortjid@\esp@filedate, \esp@f… | a   | compile/fixloop/rules/70-pkgopt.yaml:415+2      |
| `emulateapj.sty`              |  41056 | emulateapj                        | a   | compile/fixloop/rules/90-shim-legacy.yaml:1049  |
| `emulateapj5.sty`             |  26119 | emulateapj5                       | a   | compile/fixloop/rules/85-shim.yaml:161+4        |
| `epsf`                        |  27123 | —                                 | a   | compile/fixloop/builtins/gfx_missing.py:66+95   |
| `epsf.tex`                    |  27123 | —                                 | a   | compile/fixloop/builtins/shim.py:345+5          |
| `epsfx.tex`                   |  16007 | —                                 | b   | lib                                             |
| `eqnarray.sty`                |   4712 | eqnarray                          | b   | dep:files/aastex.cls~eqnarray+11                |
| `faktor.sty`                  |   1832 | —                                 | b   | lib                                             |
| `feynmp-auto.sty`             |   3566 | feynmp-auto@2013/05/03 v1.1 Auto… | b   | lib                                             |
| `feynmp.sty`                  |  12551 | feynmp@\filedate\space\fileversi… | b   | dep:files/feynmp-auto.sty~feynmp                |
| `greek-fontenc.def`           |  26758 | greek-fontenc.def@2023-09-12 2.5… | b   | dep:files/lgrenc.def+1                          |
| `har2nat.sty`                 |   1356 | har2nat@2005/12/01 1.0 Harvard t… | b   | lib                                             |
| `harmony.sty`                 |  12762 | harmony@2024/08/01                | a   | compile/fixloop/rules/10-taxonomy.yaml:106      |
| `hepunits.sty`                |   4234 | hepunits@\filedate\space High-en… | b   | lib                                             |
| `hxetex.def`                  |  44484 | hxetex.def@2026-01-29 v7.01p % H… | b   | lib                                             |
| `inputenc.sty`                |    964 | inputenc@2026/09/20 fixloop noop… | a   | compile/fixloop/builtins/pkgload.py:96+8        |
| `iopams.sty`                  |   3139 | iopams@1997/02/13 v1.0            | a   | compile/fixloop/rules/90-shim-legacy.yaml:528+2 |
| `iopart.cls`                  |  40451 | iopart@1996/06/10 v0.0 IOP Journ… | a   | compile/fixloop/builtins/vendored.py:595+5      |
| `iopart10.clo`                |   4700 | iopart10.clo@1997/01/13 v1.0 IOP… | a   | compile/fixloop/rules/90-shim-legacy.yaml:528   |
| `iopart12.clo`                |   4698 | iopart12.clo@1997/01/15 v1.0 LaT… | a   | compile/fixloop/rules/90-shim-legacy.yaml:528   |
| `jabbrv-ltwa-all.ldf`         |  49107 | —                                 | b   | dep:files/jabbrv.sty                            |
| `jabbrv-ltwa-en.ldf`          | 268657 | —                                 | b   | dep:files/jabbrv.sty:496*                       |
| `jabbrv.sty`                  |  15480 | jabbrv@2010/08/18 v0.2 Automatic… | a   | compile/fixloop/rules/10-taxonomy.yaml:75+2     |
| `jpsj2.cls`                   |  31037 | jpsj2@2007/03/01 v.1.2.2 JPSJ do… | b   | lib                                             |
| `kluwer.cls`                  |  97215 | kluwer@\filedate\space \kluclass… | b   | lib                                             |
| `kotex.sty`                   |   2691 | kotex@2015/04/19 v1.6 Korean TeX… | b   | lib                                             |
| `lams1.mf`                    |  20768 | —                                 | a   | compile/fixloop/rules/40-install.yaml:944       |
| `lams1.tfm`                   |    700 | —                                 | a   | compile/fixloop/rules/40-install.yaml:939       |
| `lams2.mf`                    |  19922 | —                                 | a   | compile/fixloop/rules/40-install.yaml:945       |
| `lams2.tfm`                   |    680 | —                                 | a   | compile/fixloop/rules/40-install.yaml:940       |
| `lams3.mf`                    |  28879 | —                                 | a   | compile/fixloop/rules/40-install.yaml:946       |
| `lams3.tfm`                   |    684 | —                                 | a   | compile/fixloop/rules/40-install.yaml:941       |
| `lams4.mf`                    |  19195 | —                                 | a   | compile/fixloop/rules/40-install.yaml:947       |
| `lams4.tfm`                   |    676 | —                                 | a   | compile/fixloop/rules/40-install.yaml:942       |
| `lams5.mf`                    |  16748 | —                                 | a   | compile/fixloop/rules/40-install.yaml:948       |
| `lams5.tfm`                   |    692 | —                                 | a   | compile/fixloop/rules/40-install.yaml:943       |
| `lgrenc.def`                  |  44064 | lgrenc.def@2023-09-12 2.5 LGR Gr… | a   | compile/fixloop/builtins/misschar.py:1178+3     |
| `listofitems.sty`             |    195 | —                                 | b   | dep:files/listofitems.tex                       |
| `listofitems.tex`             |  29855 | —                                 | b   | dep:files/listofitems.sty                       |
| `llncs.cls`                   |  43405 | llncs@2025/02/25 v2.26 ^^J LaTeX… | b   | lib                                             |
| `ltxdocext.sty`               |   9996 | ltxdocext.sty@2018/12/26 1.0a lt… | b   | lib                                             |
| `ltxfront.sty`                |  30263 | ltxfront.sty@2022/06/05 4.2f fro… | b   | dep:files/revtex4-2.cls~ltxfront                |
| `ltxgrid.sty`                 |  74109 | ltxgrid.sty@2022/06/05 4.2f page… | b   | dep:files/quantumarticle.cls~ltxgrid+1          |
| `ltxutil.sty`                 |  54952 | ltxutil.sty@2022/06/05 4.2f util… | a   | compile/fixloop/builtins/paralong.py:143+1      |
| `mathcomp.sty`                |   1664 | mathcomp@\filedate\space\filever… | b   | lib                                             |
| `mathtext.sty`                |   4742 | mathtext@2018/04/14 v1.0 transpa… | a   | compile/fixloop/rules/95-targeted.yaml:1059+1   |
| `misccorr.sty`                |  10309 | —                                 | b   | lib                                             |
| `mnras.cls`                   |  62897 | mnras@\@releasedate\ v\@version\… | a   | compile/fixloop/rules/40-install.yaml:465+28    |
| `multido`                     |   9097 | —                                 | a   | compile/fixloop/rules/40-install.yaml:623       |
| `multido.sty`                 |    814 | multido@2004/05/17 package wrapp… | b   | dep:files/multido+16                            |
| `multido.tex`                 |   9097 | —                                 | b   | dep:files/multido+16                            |
| `nicematrix.sty`              | 448337 | nicematrix@\myfiledate            | a   | compile/fixloop/rules/40-install.yaml:364+1     |
| `ot1patch.sty`                |   4167 | ot1patch@\filedate\space\filever… | b   | lib                                             |
| `ot2enc.def`                  |   6152 | ot2enc.def@2022/06/11 v3.3b Cyri… | b   | lib                                             |
| `oz.sty`                      |  38537 | oz@\filedate\space\fileversion\s… | b   | lib                                             |
| `pdftricks.sty`               |  13205 | pdftricks@\filedate\space\fileve… | b   | lib                                             |
| `pseudocode.sty`              |   7187 | pseudocode                        | b   | lib                                             |
| `psfig.sty`                   |    837 | psfig@2026/09/20 fixloop epsfig … | a   | compile/fixloop/rules/45-graphics.yaml:532+10   |
| `pst-3d`                      |   8560 | —                                 | b   | twin:pst-3d.tex                                 |
| `pst-3d.sty`                  |    443 | pst-3d@2009/07/28 package wrappe… | b   | dep:files/pst-3d~pst-3d+11                      |
| `pst-3d.tex`                  |   8560 | —                                 | b   | dep:files/pst-3d+11                             |
| `pst-3dplot.sty`              |    551 | pst-3dplot@2010/01/01 package wr… | b   | dep:files/pst-3dplot.tex~pst-3dplot             |
| `pst-3dplot.tex`              |  94042 | —                                 | b   | dep:files/pst-3dplot.sty                        |
| `pst-all.sty`                 |   1107 | pst-all@2008/01/01 the main pstr… | a   | compile/fixloop/actions.py:655+1                |
| `pst-arrow`                   |  10366 | —                                 | b   | twin:pst-arrow.tex                              |
| `pst-arrow.sty`               |    527 | pst-arrow@2016/09/01 v. 0.01 pac… | b   | dep:files/pst-arrow~pst-arrow+2                 |
| `pst-arrow.tex`               |  10366 | —                                 | b   | dep:files/pst-arrow+2                           |
| `pst-calculate.sty`           |   1528 | pst-calculate@% 2019/01/24 v. \p… | b   | dep:files/pst-math.sty~pst-calculate+2          |
| `pst-code-arc.tex`            |  11811 | —                                 | b   | dep:files/pstricks~pst-code-arc+2               |
| `pst-code-box.tex`            |  15490 | —                                 | b   | dep:files/pstricks~pst-code-box+2               |
| `pst-code-circle_ellipse.tex` |   5143 | —                                 | b   | dep:files/pstricks~pst-code-circle_ellipse+2    |
| `pst-code-grid.tex`           |   3753 | —                                 | b   | dep:files/pstricks~pst-code-grid+2              |
| `pst-code-pspicture.tex`      |   9315 | —                                 | b   | dep:files/pstricks~pst-code-pspicture+2         |
| `pst-code-put.tex`            |   7846 | —                                 | b   | dep:files/pstricks~pst-code-put+2               |
| `pst-code-ref_rot.tex`        |   3858 | —                                 | b   | dep:files/pstricks~pst-code-ref_rot+2           |
| `pst-coil.sty`                |    437 | pst-coil@2010/02/01 package wrap… | b   | dep:files/pst-all.sty~pst-coil+3                |
| `pst-coil.tex`                |   8929 | —                                 | b   | dep:files/pst-all.sty~pst-coil+6                |
| `pst-eps.sty`                 |    213 | pst-eps@2005/05/20 package wrapp… | b   | dep:files/pst-all.sty~pst-eps+1                 |
| `pst-eps.tex`                 |   6626 | —                                 | b   | dep:files/pst-all.sty~pst-eps+1                 |
| `pst-fill.sty`                |    746 | pst-fill@2010/03/20 package wrap… | b   | dep:files/pst-all.sty~pst-fill+1                |
| `pst-fill.tex`                |  13563 | —                                 | b   | dep:files/pst-all.sty~pst-fill+1                |
| `pst-fp.tex`                  |  23495 | —                                 | b   | dep:files/pst-plot+5                            |
| `pst-grad.tex`                |   4824 | —                                 | b   | dep:files/pst-all.sty~pst-grad                  |
| `pst-key.sty`                 |    249 | pst-key@2004/07/15 package wrapp… | a   | compile/fixloop/rules/40-install.yaml:621       |
| `pst-key.tex`                 |   2787 | —                                 | a   | compile/fixloop/rules/40-install.yaml:621       |
| `pst-math`                    |    758 | —                                 | b   | twin:pst-math.tex                               |
| `pst-math.sty`                |   2903 | pst-math@2023/07/03 v 0.67 packa… | b   | dep:files/pst-math~pst-math+3                   |
| `pst-math.tex`                |    758 | —                                 | b   | dep:files/pst-math+3                            |
| `pst-node`                    |  71120 | —                                 | a   | compile/fixloop/actions.py:572+6                |
| `pst-node.sty`                |   1483 | pst-node@2024/07/10 v1.02 LaTeX … | b   | dep:files/pst-3dplot.sty~pst-node+13            |
| `pst-node.tex`                |  71120 | —                                 | b   | dep:files/pst-3dplot.sty~pst-node+19            |
| `pst-node97.tex`              |  12029 | —                                 | b   | dep:files/pst-node.sty                          |
| `pst-pdf.sty`                 |  14642 | pst-pdf@2020/10/10 v1.2f PS grap… | b   | dep:files/pstricks-pdf.sty~pst-pdf              |
| `pst-plot`                    | 106121 | —                                 | a   | compile/engine/_route.py:40                     |
| `pst-plot.sty`                |   1128 | pst-plot@2011/06/05 v1.00 LaTeX … | b   | dep:files/pst-3dplot.sty~pst-plot+9             |
| `pst-plot.tex`                | 106121 | —                                 | b   | dep:files/pst-3dplot.sty~pst-plot+10            |
| `pst-plot97.tex`              |  16502 | —                                 | b   | dep:files/pst-plot.sty                          |
| `pst-poly.tex`                |   9432 | —                                 | b   | lib                                             |
| `pst-text.sty`                |    420 | pst-text@2018/12/28 package wrap… | b   | dep:files/pst-all.sty~pst-text+1                |
| `pst-text.tex`                |   6745 | —                                 | b   | dep:files/pst-all.sty~pst-text+1                |
| `pst-tools.tex`               |   9677 | —                                 | a   | compile/fixloop/builtins/shim.py:1038+2         |
| `pst-tree.sty`                |    272 | pst-tree@2009/01/25 package wrap… | b   | dep:files/pst-all.sty~pst-tree+1                |
| `pst-tree.tex`                |  34225 | —                                 | b   | dep:files/pst-all.sty~pst-tree+1                |
| `pst-xkey`                    |   2437 | pst-xkey.tex@2005/11/25 v1.6 PST… | a   | compile/fixloop/rules/40-install.yaml:413       |
| `pst-xkey.sty`                |   1762 | pst-xkey@2005/11/25 v1.6 package… | b   | dep:files/pst-3d~pst-xkey+18                    |
| `pst-xkey.tex`                |   2437 | pst-xkey.tex@2005/11/25 v1.6 PST… | b   | dep:files/pst-3d~pst-xkey+24                    |
| `pstcol.sty`                  |    899 | pstcol@2007/04/11 v1.3 LaTeX wra… | a   | compile/fixloop/rules/70-pkgopt.yaml:422+1      |
| `pstricks`                    |  70970 | —                                 | a   | compile/fixloop/builtins/gfx_missing.py:4+108   |
| `pstricks-add.sty`            |    639 | pstricks-add@2021/09/10 v. 0.17 … | a   | compile/fixloop/rules/40-install.yaml:446       |
| `pstricks-add.tex`            |  91623 | —                                 | a   | compile/fixloop/actions.py:572+7                |
| `pstricks-arrows`             |  19134 | —                                 | b   | twin:pstricks-arrows.tex                        |
| `pstricks-arrows.tex`         |  19134 | —                                 | b   | dep:files/pstricks~pstricks-arrows+3            |
| `pstricks-color`              |   4629 | —                                 | b   | twin:pstricks-color.tex                         |
| `pstricks-color.tex`          |   4629 | —                                 | b   | dep:files/pstricks~pstricks-color+3             |
| `pstricks-dots.tex`           |  10017 | —                                 | b   | dep:files/pstricks~pstricks-dots+2              |
| `pstricks-pdf.sty`            |   5261 | pstricks-pdf@2020/06/11 v0.02 cr… | b   | lib                                             |
| `pstricks-plain.tex`          |  76815 | —                                 | b   | lib                                             |
| `pstricks-tex.def`            |   3362 | —                                 | b   | dep:files/pstricks+2                            |
| `pstricks-xetex.def`          |   1026 | —                                 | b   | dep:files/pstricks.sty                          |
| `pstricks.con`                |  15065 | —                                 | b   | dep:files/Vaucanson-G.tex~pstricks+44           |
| `pstricks.sty`                |   8163 | pstricks@2024/02/02 v0.75 LaTeX … | a   | compile/fixloop/builtins/vendored.py:209+3      |
| `pstricks.tex`                |  70970 | —                                 | a   | compile/fixloop/builtins/vendored.py:79+3       |
| `pstricks97.tex`              |  70662 | —                                 | b   | dep:files/pst-node97.tex+1                      |
| `ptptex.cls`                  |  35434 | ptptex@2008/11/20 ver.0.91 LaTeX… | b   | lib                                             |
| `puenc-greek.def`             |  26371 | puenc-greek.def@2023-09-12 2.5 G… | b   | lib                                             |
| `pxrubrica.sty`               |  81970 | pxrubrica@2023/03/01 v1.3e PX Ja… | b   | lib                                             |
| `quantikz.sty`                |    591 | quantikz@2023/05/24 typeset quan… | b   | lib                                             |
| `quantumarticle.cls`          |  58247 | quantumarticle                    | b   | lib                                             |
| `revsymb4-2.sty`              |   5569 | revsymb4-2@2022/06/05 4.2f (http… | b   | dep:files/revtex4-2.cls~revsymb4-2              |
| `revtex4-2.cls`               | 202907 | revtex4-2@2022/06/05 4.2f (https… | a   | compile/fixloop/builtins/paralong.py:138+16     |
| `sgame.sty`                   |  15196 | —                                 | b   | lib                                             |
| `simplekv.tex`                |  12655 | —                                 | b   | dep:files/systeme.sty~simplekv+1                |
| `simplewick.sty`              |   5472 | simplewick@\filedate\space\filev… | b   | lib                                             |
| `sistyle.sty`                 |  12044 | sistyle@2008/07/16 v2.3a SI unit… | b   | dep:files/siunitx.sty~sistyle                   |
| `siunitx.sty`                 | 362831 | siunitx@2026-09-15                | a   | compile/fixloop/rules/85-shim.yaml:613          |
| `skak.sty`                    |  63275 | skak@2018/01/08 v1.5.3 Chess typ… | b   | dep:files/chessfss.sty                          |
| `sor4-2.rtx`                  |  20046 | sor4-2.rtx                        | b   | lib                                             |
| `spie.cls`                    |  13396 | spie@2007/04/14 v3.25 SPIE Proce… | b   | lib                                             |
| `systeme.sty`                 |   1250 | —                                 | b   | dep:files/systeme.tex                           |
| `systeme.tex`                 |  55120 | —                                 | b   | dep:files/systeme.sty                           |
| `t2aenc.def`                  |  12179 | t2aenc.def@2023/11/07 v1.0k Cyri… | a   | compile/fixloop/builtins/misschar.py:1178+2     |
| `tascmac.sty`                 |  11463 | tascmac@2020/01/15 v2.1 ascmac p… | b   | dep:files/ascmac.sty                            |
| `tensor.sty`                  |   5283 | tensor@2023/07/18 v2.2 tensor in… | b   | dep:files/revsymb4-2.sty~tensor                 |
| `turnstile.sty`               |   9182 | turnstile@2007/06/23 v1.0 turnst… | b   | lib                                             |
| `vaucanson-g.sty`             |   2651 | vaucanson-g@2026/06/01 package w… | b   | dep:files/VCPref-mystyle.tex+1                  |
| `vaucanson.sty`               |   2788 | vaucanson-g@2026/06/01 package w… | b   | lib                                             |
| `yhmath.sty`                  |   4859 | yhmath@2020/03/17 v1.6            | b   | lib                                             |
| `yquant-tools.tex`            |  30304 | —                                 | b   | lib                                             |

## `shims/`

| path           | bytes | \ProvidesX                        | cl  | evidence                                         |
| -------------- | ----: | --------------------------------- | --- | ------------------------------------------------ |
| `JHEP.cls`     | 10845 | JHEP@2026/09/19 texlate stub — o… | a   | compile/fixloop/rules/90-shim-legacy.yaml:710+1  |
| `JHEP3.cls`    | 11802 | JHEP3@2026/09/19 texlate stub — … | a   | compile/fixloop/rules/90-shim-legacy.yaml:710+1  |
| `aastex63.cls` |  4560 | aastex63@2026/09/28 texlate stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:447    |
| `aipproc.cls`  |  7345 | aipproc@2026/09/19 texlate stub … | a   | compile/fixloop/builtins/misc.py:518+8           |
| `appolb.cls`   |  1317 | appolb@2026/09/28 texlate stub —… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1505+1 |
| `conm-p-l.cls` |  1027 | conm-p-l@2026/09/28 texlate stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1215+1 |
| `epl2.cls`     |  3159 | epl2@2026/09/28 texlate stub — o… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1097+3 |
| `imsart.cls`   |  4529 | imsart@2026/09/19 texlate stub —… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1212   |
| `memo-l.cls`   |  1800 | memo-l@2026/09/28 texlate stub —… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1316+1 |
| `mn.cls`       |  1237 | mn@2026/09/18 texlate stub -> mn… | b   | dep:shims/mn2e.cls                               |
| `mn2e.cls`     |  1479 | mn2e@2026/09/19 texlate stub — o… | a   | compile/fixloop/builtins/paralong.py:137+14      |
| `revtex.cls`   |  3805 | revtex@2026/09/19 texlate stub —… | a   | compile/fixloop/builtins/shim.py:1614+10         |
| `siamltex.cls` |  3997 | siamltex@2026/09/28 texlate stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:609    |
| `svjour.cls`   |  8219 | svjour@2026/09/19 texlate stub —… | a   | compile/fixloop/builtins/shim.py:489+5           |
| `svjour3.cls`  |  8097 | svjour3@2026/09/19 texlate stub … | a   | compile/fixloop/rules/90-shim-legacy.yaml:1054   |

## `stubs/`

| path              | bytes | \ProvidesX                        | cl  | evidence                                         |
| ----------------- | ----: | --------------------------------- | --- | ------------------------------------------------ |
| `BoxedEPS.tex`    |  1673 | —                                 | a   | compile/fixloop/rules/90-shim-legacy.yaml:2045+1 |
| `aa.cls`          | 17317 | aa@2026/09/19 texlate stub — ori… | a   | compile/fixloop/builtins/paralong.py:136+23      |
| `aaai23.sty`      |  2530 | aaai23@2026/09/20 texlate stub —… | b   | lib                                              |
| `aasms4.sty`      | 10223 | aasms4@2026/09/19 texlate stub —… | a   | compile/fixloop/rules/90-shim-legacy.yaml:64+2   |
| `aaspp4.sty`      | 10467 | aaspp4@2026/09/19 texlate stub —… | a   | compile/fixloop/builtins/csfix.py:234+3          |
| `apjfonts.sty`    |   487 | apjfonts@2026/09/19 texlate stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:918    |
| `axodraw.sty`     |  5417 | axodraw@2026/09/19 texlate stub … | a   | compile/fixloop/rules/90-shim-legacy.yaml:1045   |
| `bibmods.sty`     |   587 | bibmods@2026/09/28 texlate stub … | b   | lib                                              |
| `binhex.tex`      |  2797 | —                                 | a   | compile/fixloop/rules/00-base.yaml:124+5         |
| `citesort.sty`    |   450 | citesort@2026/09/19 texlate stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1042   |
| `diagrams.sty`    |  8566 | diagrams@2026/09/19 texlate stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1738   |
| `diagrams.tex`    |  6264 | —                                 | a   | compile/fixloop/rules/90-shim-legacy.yaml:1707+2 |
| `emlines.sty`     |  1425 | emlines@2026/09/28 texlate stub … | b   | dep:stubs/emlines2.sty~emlines                   |
| `emlines2.sty`    |  1124 | emlines2@2026/09/28 texlate stub… | b   | lib                                              |
| `eqsecnum.sty`    |   516 | eqsecnum@2026/09/19 texlate stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:265    |
| `espcrc1.sty`     |  1814 | espcrc1@2026/09/19 texlate stub … | b   | dep:stubs/espcrc2.sty~espcrc1                    |
| `espcrc2.sty`     |  1784 | espcrc2@2026/09/19 texlate stub … | a   | compile/fixloop/rules/90-shim-legacy.yaml:566    |
| `ifacconf.cls`    |  4341 | ifacconf@2026/09/20 texlate stub… | a   | compile/fixloop/rules/40-install.yaml:75         |
| `jheppub.sty`     |  5210 | jheppub@2026/09/19 texlate stub … | b   | lib                                              |
| `jinstpub.sty`    |  4905 | jinstpub@2026/09/19 texlate stub… | b   | dep:shims/JHEP.cls~jinstpub+17                   |
| `jmlr2e.sty`      |  4157 | jmlr2e@2026/09/20 texlate stub —… | a   | compile/fixloop/rules/40-install.yaml:75         |
| `numcompress.sty` |   585 | numcompress@2026/09/28 texlate s… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1648   |
| `opex3.sty`       |  1267 | opex3@2026/09/28 texlate stub — … | b   | lib                                              |
| `osajnl.sty`      |  1361 | osajnl@2026/09/28 texlate stub —… | b   | lib                                              |
| `siam10.clo`      |  1035 | siam10.clo@2026/09/20 texlate st… | b   | dep:stubs/siam11.clo+1                           |
| `siam11.clo`      |   594 | siam11.clo@2026/09/20 texlate st… | b   | dep:stubs/siam10.clo~siam11                      |
| `siam12.clo`      |   594 | siam12.clo@2026/09/20 texlate st… | b   | dep:stubs/siam10.clo~siam12                      |
| `slashbox.sty`    |  3256 | slashbox@2026/09/19 texlate stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:934    |
| `svglov3.clo`     |  2016 | svglov3.clo@2026/09/19 texlate s… | a   | compile/fixloop/builtins/common.py:248+7         |
| `sw20lart.sty`    |  2616 | sw20lart@2026/09/19 fixloop stub… | a   | compile/fixloop/rules/90-shim-legacy.yaml:1647   |
| `tcilatex.tex`    |  5975 | —                                 | a   | compile/fixloop/builtins/vendored.py:484+6       |
| `texsort.sty`     |  3689 | texsort@2026/09/19 texlate stub … | a   | compile/fixloop/rules/90-shim-legacy.yaml:1738   |
