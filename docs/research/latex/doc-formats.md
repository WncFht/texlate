# EPUB/DOCX 通路 — 双语对照插译的设计与落地

> **结论**：EPUB 用 stdlib zipfile + 自拆（~300 行达成 v1），照 bilingual_book_maker 的 DOM 插译/job 枚举/marker 占位/断点协议，不碰 EbookLib（AGPL 隐患规避）；DOCX 用 python-docx（MIT），deepcopy `w:p` + `addnext` + pPr 继承。两者复用同一翻译编排契约。
> **状态**：现行（2026-09-16 已落地为 `export/`：epub/docx/markers/rights/filters/common，公共口 `export_document`/`sniff_format`，CLI `texlate export`；规范由 spec/ 承载）
> **日期**：2026-09-17

## 1. 参考蓝图：bilingual_book_maker 的机制清单

调研对象是 bilingual_book_maker[^bbm] 的 EPUB loader（上游 ~1000 行版本的重度加固 fork）。可移植的机制设计：

- **DRM stdlib 预检**：看 `META-INF/rights.xml`/`license.lcpl`/`sinf.xml` 存在性 + `encryption.xml` 里 EncryptionMethod **白名单**——只放行 IDPF/Adobe 字体混淆算法，其余加密书拒开。allow-list 而非 deny-list。
- **文档枚举**：翻译面 = manifest 里所有 `application/xhtml+xml`（EPUB3 nav.xhtml 也进翻译流）；NCX 不进翻译流由 toc 重建。非文档 item（图/CSS/字体/SMIL）翻译开始前先全部入新书（中断后也能看到图）。**文件过滤只跳翻译不删文档**——否则 spine/nav/ncx 指向不存在的文件（epubcheck RSC-007）。
- **unit 划分**：文本节点归属最近 block owner，owner 文本被 barrier 切成 run——barrier = 嵌套 block / skip 分类可见节点 / `<pre>` 外的 `<br>`；**内联标签边界不是 barrier**（`<a>` 切断句子毁翻译质量）。`<br>` 前插 `\n` 文本节点防 "one<br>two" 粘粘。
- **送模型前过滤**：纯数字/空白/纯 URL/全标点、`Source:`/`Figure N`/ISBN 尾链、整段只剩 exclude 标签、祖先在 `script/style/head/title/template/svg/math`、ruby 注音 `rt/rp/rtc`、`epub:type=pagebreak` 页码、`display:none`/`hidden`（`epub:type=footnote` 等注义豁免——弹注阅读器仍显示）。
- **插译四形态**（双语 = 原文节点不动、译文节点克隆插后）：普通克隆（`copy(p)` → 译文 string → strip 重复 id → restamp lang → `insert_after`）；受限容器（`figcaption/caption/legend/summary` 及 nav 后代——内容模型只准一个该元素，改内部追加 `<br/><span>`，nav `<li>` 落点定位进 `<a>/<span>`）；锚定插译（run 在复杂 owner 里，译文跟 run 最后文本节点）；含排除标签段落（克隆副本先 extract exclude 再填译文）。
- **marker 占位协议**（与 LaTeX `[[TYPE_n]]` 体系同构）：受保护且短的内联元素（exclude 的 `<code>/<sup>`、`<img>` 等 void）变 `⟦code1⟧` token——含词文本 ≥40 字符保持 barrier、无词文本（URL/公式）放宽到 400；`<a><img></a>` 取外层 wrapper。三件套：**分配防碰撞**（token 在源文已逐字出现则重新编号）、**幻觉调和**（回复里没发过的 marker 剥掉、发的丢了按源序补回——宽容调和绝不因 marker 重试）、**写回克隆**（在刚插入节点内找 token 文本节点切开，塞源元素 `copy()`）。`<a>` 不是 marker；配对 marker（`⟦em4⟧…⟦/em4⟧`）划出 v1 范围。
- **批量对齐契约**：`translate_list` 返回恰好等长对齐的 list 否则 `BatchMismatch`；回复解析三级（`(n)` 编号正则 → `@@` 分隔符 → 数量不符即 mismatch，不按行硬切）；对齐梯子 `group → halves → singles` 折半重问；移位检测靠 marker slot 证据 + 数字指纹漂移。
- **断点续传**：job_id = `epub:{doc}:{file}:{node}:{sha256(text)[:16]}`；checkpoint 的 job_ids 必须等于新计划的前缀否则报「书或过滤器变了删档重翻」；`run_fingerprint` 绑语言/prompt/模型；每 20 条 save；Ctrl-C 写 partial book（重读原 epub、回放已翻插译产半成品双语书）。

## 2. texlate EPUB v1 取舍

| 抄 | 不抄（v1） |
| --- | --- |
| DRM stdlib 预检 | plan/classify/ledger 全套 |
| unit 枚举 + job_id + 前缀校验断点 | 单译模式（只做双语） |
| 克隆插译 + 受限容器内联追加 | sentence_mode、retranslate、披露页 |
| marker 占位协议三件套 | 字体解/重混淆（照抄 zip 条目即免疫） |
| barrier 最小子集：嵌套 block + `<br>` | CSS display 解析器（只查 `hidden` 属性 + 内联 `display:none`） |
| `(n)`/`@@` 解析 + 对齐梯子 | epubcheck 全量对账（只留 strip id + 内容模型两条硬规则） |

EPUB 特有注意点：**mimetype 必须第一且 ZIP_STORED**（OCF 硬性要求）；nav.xhtml 走受限容器内联追加；字体混淆照抄 `encryption.xml` + 不改 `dc:identifier` 即免疫（这是 stdlib 相对 ebooklib 的净赚——后者丢 META-INF 被迫写 deob/reob）；fixed-layout（`rendition:layout=pre-paginated`）检测后警告拒翻；译文样式用 `class="texlate-zh"` + `<head>` 内嵌 `<style>`（不动 manifest）；NCX 的 `navLabel/text` 可直接 text-node 替换便宜翻掉。

## 3. DOCX 方案

python-docx[^python-docx]（MIT）。插译核心 ~30 行：`copy.deepcopy(paragraph._p)` → 只留 `w:pPr`（段落属性连 numPr/缩进/样式 id 一起继承——译文列表项拿到自己的编号）→ `addnext` → `add_run(译文)` → 首个 run 的 rPr 深拷继承字体字号 → `w:eastAsia` 中文回退字体 + 双语区分色。重打包零成本（`doc.save()` 全量保 part，无 mimetype 约束）。

遍历矩阵（每面独立）：正文+表格 `iter_inner_content()`（`doc.paragraphs` 只给 body 顶层漏表格内段落）；表格 cell 递归（`w:tc` 也是 BlockItemContainer）；页眉页脚每 section 三份（even/first_page 变体）；文本框/形状 `.//w:txbxContent/w:p`（raw XML，python-docx 不建模）；内容控件 `w:sdt→w:sdtContent`；脚注/尾注/批注经 `word/footnotes.xml` 等 raw part。跳过面：`w:instrText`/`w:fldSimple`（域代码/TOC）、`w:del`（修订删除）、`m:oMath`；`w:ins`（修订插入）v1 翻。marker 对应 `w:r` 里的 drawing/object/math 子树——`⟦img1⟧`/`⟦math1⟧` 写回时 deepcopy 原 `w:r`；v1 简化：保护物是整段主体直接 skip（双语下原文段反正留着）。

## 4. 落地实况与有意偏差（2026-09-16 实装 + 09-17 勘误）

实现在 `export/`（epub/docx/markers/rights/filters/common）。与本 spec 的有意偏差：

1. **编排层**：不是伪码的 `translate_list` 直调，而是 `xlat.XlatPipeline` 全量复用（`[n]` 批协议 + retry 阶梯 + StateStore 断点）——`chunk_id` 即 `epub:{doc}:{unit}:{sha256}` job_id，键控断点替代位置序 JSONL，对源漂移免疫。
2. **marker 皮**：`[[TAG_n]]` 而非 ⟦⟧——与 LaTeX `PH_RX` 同构，placeholders.diff/`encode_newlines`/MockTranslator 零改动。
3. **XML 解析面**：container/OPF/`encryption.xml` 走 defusedxml，NCX 与 DOCX 裸 part 走加固 lxml（DOCX 侧用 python-docx `oxml_parser` 产 CT_* 类型元素）；未用 bs4 "xml"（其后端是无实体防护的裸 `XMLParser`）。
4. **CSS**：`.texlate-zh` 仅在有插译时注入。
5. **勘误**（实装细节）：href→成员名解析先试 `unquote` 再试原样（percent-encoded 与字面 `%` 两态兼容）；缺 `mimetype` 时写规范值兜底；文档枚举按 path 去重；受限容器判定新增 `owner.name == "nav"`（克隆 nav 会复制成第二个 landmark）；语言码过 `safe_language`（`[\w-]+` fullmatch 的 BCP47 子集——`_restamp_opf` 是正则文本替换，不校验会造成 XML 注入）；marker 哨兵用 PUA `{i}` 而非控制字符（normalize 剥 XML 非法字符，`\x00` 哨兵活不过归一化）。

验证：`tests/test_export_{epub,docx}.py` + 真书回归（2 本 Gutenberg 全链绿、EbookLib 可读）。

## 5. 边界一览

| 边界 | EPUB | DOCX |
| --- | --- | --- |
| 图文混排 | `<img>` 短保护→marker；`<a><img>` 取外层 a；figure+figcaption 走受限容器 | `w:drawing` 原文段不动译文段纯文本；纯图段 skip；保位用 marker+deepcopy `w:r` |
| 数学 | `<math>` 永不进源文；句中→wordless marker | `m:oMath`/`m:t` 跳过；句中公式 `⟦mathN⟧` 保位或整段跳过 |
| 竖排 | CSS `writing-mode` 克隆继承免处理 | `w:textDirection` 在 pPr 里 deepcopy 自带 |
| fixed-layout | `pre-paginated` 警告拒翻 | 本就固定版式正常翻 |
| ruby/注音 | `rt/rp/rtc` 永不送模型 | `w:ruby` phonetic 跳过 |
| DRM/加密 | stdlib 预检拒开 | python-docx 开不了即拒 |
| 字体 | 照抄 `encryption.xml`+保留 `dc:identifier` | 嵌入字体随 package 原样保留 |
| 目录 | nav `<li>` 内联追加；NCX 翻 `<text>` 或留 | TOC 域代码跳过 |
| 表格 | `td/th` 普通 block owner | `w:tc` 递归遍历 |
| 脚注/尾注 | `epub:type=footnote` 即使 CSS 隐藏也翻 | `footnotes.xml` raw part 同法插译 |
| 批注/修订 | — | comments.xml 翻；`w:del` 跳 `w:ins` 翻 |
| 长保护内联 | >40 字符含词/>400 无词保持 barrier | 大 drawing/object 整段跳过 |
| 隐藏文本 | `display:none`/`hidden` 跳（footnote 义除外） | `w:vanish` 跳过 |

## 6. 优先级裁决回顾

EPUB 先行、DOCX 紧随、PDF 不提前——bbm 把 epubcheck 级别的坑全趟过一遍使 EPUB 蓝图最完整；PDF 没有 DOM（段落语义要重建，不是一个宇宙），其路径另见 `pdf-path.md`（BabelDOC sidecar）。v1 明确不做：单译模式、paired inline marker、CSS 级联 display 解析、披露/署名页、epubcheck 全量对账、字体混淆改写、retranslate/only_filelist 族。

### 参考文献

[^bbm]: bilingual_book_maker contributors. bilingual_book_maker — bilingual EPUB translation tool. GitHub. [github.com/yihong0618/bilingual_book_maker](https://github.com/yihong0618/bilingual_book_maker)
[^python-docx]: python-openxml. python-docx — Create and update Microsoft Word .docx files (MIT). GitHub. [github.com/python-openxml/python-docx](https://github.com/python-openxml/python-docx)
