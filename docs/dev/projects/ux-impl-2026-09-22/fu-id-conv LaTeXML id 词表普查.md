# en.html `id` 命名约定全集（2026-09-22 普查，终版 28 文档）

> **结论**：LaTeXML `GenerateID` 产 `Parent.TypeN` 层级 id 语法——`S/SS/SSS`=节、`F`=图、`T`=表、`E/Ex/EGx`=公式、`Thm<env>`=定理、`bib.bibN`=文献、裸 `.N` 数字段占 59.6%；浮动体 100% 带 id、bibitem 0 缺、eq 内行 58.2% 无 id 但外层 `table.ltx_equation` 恒有——find-usages 的宿主分类器与「eq 行级无 id 取最近 table.ltx_equation 祖先」策略以此词表为底据。
>
> **状态**：时点证据（28 文档 70,157 id 普查口径，2026-09-22）——find-usages lane 已落地引用本词表
> **日期**：2026-09-22

语料：25 篇真实 `arxiv.org/html/{id}` 抓取件（texlate `en.html` 的直接上游——`worker/html.py::_sanitize_dom` 不动 `id`，只剥 form/dialog/button/script 等），外加本地 `arxiv_html_1706.html`、ar5iv / latexmlpost 各 1 件对照。生成器语义核自 LaTeXML `lib/LaTeXML/Package.pm::GenerateID`：`id = <最近带id祖先>.<idprefix><n>`，空前缀退化为裸 `.N` 数字段，无祖先时 `idN` 兜底。

sanitize 影响面：raw 70314 → 存活 70157（剥 157 个 id，全部位于被 decompose 的 form/dialog/modal 内：modal-form*/modal-title/form_title/description/selectedTextModalDescription + latexmlpost 的 `_fed_an_ua_tag`）；新增 0。

## 主语法：`Parent.Type n`（LaTeXML 计数器 idprefix）

| 终段                                   | 元素                                    | 含义                                                                    |
| -------------------------------------- | --------------------------------------- | ----------------------------------------------------------------------- |
| `S<n>`                                 | section.ltx_section                     | 编号节                                                                  |
| `SS<n>`/`SSS<n>`                       | ltx_subsection/subsubsection            | 子节/子子节                                                             |
| `Ch<n>`/`Chx<n>`                       | section.ltx_chapter                     | 章（book 类文档，如 2403.14606）                                        |
| `Pt<n>`                                | ltx_part                                | part                                                                    |
| `Px<n>`/`P<n>`                         | section.ltx_paragraph                   | 段落标题块（article 里恒无号→Px）                                       |
| `A<n>`/`Ax<n>`                         | ltx_appendix                            | 附录（`Ax`=无号）                                                       |
| `F<n>`                                 | figure.ltx_figure                       | 图（**含无 caption 者，100% 带 id**）                                   |
| `T<n>`                                 | figure.ltx_table                        | 表                                                                      |
| `sf<n>`/`sf<n><字母>`/`st<n>`          | ltx_figure/ltx_table + ltx_figure_panel | 子图/子表（SAM2 有 `sf2a` 字母变体）                                    |
| `g<n>`                                 | object/img.ltx_graphics                 | 图内图形件（`Sx1.F5.g2`）                                               |
| `pic<n>`                               | svg.ltx_picture                         | tikz 图（嵌在字母子图内 `A5.F10.sf2a.pic1`）                            |
| `fig<n>`                               | figure.ltx_figure_panel                 | 嵌在表单元格里的图板                                                    |
| `E<n>`/`Ex<n>`                         | table.ltx_equation                      | 公式（x=无号；`Ex42Xa` 中 X+字母=子公式 (a)(b)）                        |
| `EG<n>`/`EGx<n>`                       | table.ltx_equationgroup                 | 公式组                                                                  |
| `Thm<env><n>`                          | div.ltx_theorem                         | 定理——前缀嵌环境类名：Thmtheorem/Thmthm/Thmfact/Thmclaim/Thmmaintheorem |
| `I<n>`/`i<n>`/`ix<n>`                  | ltx_itemize/ltx_enumerate/ltx_item      | 列表/项（itemize 项恒无号→ix）                                          |
| `algorithm<n>`/`alg<n>`/`alg<n><字母>` | figure.ltx_float_algorithm              | algorithm 浮动体（两种前缀并存；字母后缀变体如 alg4b）                  |
| `l<n>`/`l<n><字母>`                    | div.ltx_listingline                     | 算法/代码行（`alg1.l0a`=algorithm 1 第 0a 行）                          |
| `m<n>`                                 | math.ltx_Math                           | 数学式（最大头 16150/70157）                                            |
| `p<n>`                                 | div.ltx_para                            | 段落                                                                    |
| `footnote<n>`/`footnotex<n>`           | span.ltx_note                           | 脚注（文档级计数器；x=无号如 \thanks）                                  |
| `abstract<n>`/`acknowledgements<n>`    | div                                     | 摘要/致谢块                                                             |
| `bib.bib<n>`                           | li.ltx_bibitem                          | 参考文献（顶层 `bib` 区段 + 项；内部还有 `.N`/`.m<n>` 子件）            |
| `id<n>`                                | sup.ltx_sup/span.ltx_text 等            | 无 id 祖先兜底（frontmatter 件，140 例）                                |

无号变体规则：类型字母后插 `x`（`Sx,SSx,SSSx,Ax,Ex,Px,ix,EGx,footnotex,Chx`）。字母后缀：子公式 `Ex<n>X<a>`（2 篇：2609.19608 9 例、2403.14606 25 例）、子图 `sf<n><a>`、算法 `alg<n><a-e>`、算法行 `l<n><a>`。

## 裸数字终段 `.N`（占全量 id 的 59.6%，41806/70157）

`GenerateID('')` 空前缀产物：带 id 祖先下的内部件——`td/th.ltx_td`、`tr.ltx_tr`、`table.ltx_tabular`（表格行列格，深度最深 13 段）、`p.ltx_p`、`span.ltx_text`、`em.ltx_emph`、`sup/sub`、`div.ltx_proof`、`div.ltx_listingline`（部分）、`bib.bib<n>.N`（bibitem 内部 tag）。深度直方图：5 段最多（18034），1–13 段。

## 非 LaTeXML 语法 id（en.html 中实际存活的）

arXiv 页面家具（`article.ltx_document` 之外，sanitize 后仍留）每篇恰好 6 个：`announcement-banner`、`disable-reading-mode-btn`、`fixed-buttons-container`、`infobox`、`license-tr`、`watermark-tr`（26 篇 × 6 = 156）。（`modal-form*`/`form_title`/`description`/`selectedTextModalDescription`/`modal-title` 在 `<form>/<dialog>` 内，sanitize 已剥。）latexmlpost 对照件另有 `latexmlpost_*` 下划线 id 9 个——非 arxiv_html 链产物。

## 无 id 率（sanitize 后口径）

- `figure.ltx_figure`：**0/453 无 id（0%）**——含 captionless、panel、table 嵌图
- 任意 `<figure>` tag：0/653；全部浮动体（figure+table+float+listing+algorithm）：0/681
- `.ltx_graphics`：2/502 无 id（仅 latexmlpost 对照件的 img.ltx_graphics；arxiv 件 0）
- `ltx_section/subsection/paragraph`：1/1235（latexmlpost 的 authors_1line 边例；arxiv 件 0）
- `ltx_bibitem`：0/1439
- `ltx_equation(+group)`：**2367/4067 无 id（58.2%）**——但全是内行 `tr.ltx_eqn_row`（1915）/`span.ltx_eqn_row`（452）；外层 table.ltx_equation/group 恒有 id（E/Ex/EGx），eq_noid_anc_all_have_id=true

## 边例

- 3/25 抓取件是 "Untitled Document" 转换失败 stub（1412.6980、1603.08199、1707.06347）：en.html 只剩 8 个 id（6 chrome + `p1`、`p1.1`）——无章节树可锚。
- 全库 70157 个存活 id 零重复。
- `m<n>` 终端段一家占 23%（16150）；`S*` 节树仅占少数——id 面以数学/表格内件为主。
