# EPUB/DOCX 通路规格 —— 双语对照插译

> 调研对象：`tmp/refs/bilingual_book_maker/`(下文引用省略前缀 `book_maker/`)。
> 结论先行：**EPUB 用 stdlib zipfile + bs4 自拆 (~300 行可达成 v1),完整蓝图在 bbm 里，照抄其 DOM 插译/job 枚举/marker 占位/断点协议即可，不碰 EbookLib(AGPL);DOCX 用 python-docx(MIT),deepcopy `w:p` + `addnext` + pPr 继承，边角集中在表格/文本框/脚注三个独立遍历面。两者都复用同一翻译编排契约 `translate(text) / translate_list(texts)`。里程碑:M3 内 EPUB 先行、DOCX 紧随，PDF 不提前 (MinerU→md 已在 M3 过渡，BabelDOC sidecar 留 M4)。**

---

## 1. bbm EPUB 管线精读

参考实现是 `loader/epub_loader.py`(4218 行，上游 ~1000 行版本的重度加固 fork)+ `loader/helper.py` + `loader/plan.py` + `loader/markers.py`。管线七步：

### 1.1 拆包/读入

- `epub.read_epub` 读全本 (`epub_loader.py:459`),读之前先用 **stdlib-only** 的 DRM 检查拒开加密书 (`rights.py:64-123`:看 `META-INF/rights.xml`/`license.lcpl`/`sinf.xml` 存在性 + `encryption.xml` 里 EncryptionMethod 白名单——只有 IDPF/Adobe 字体混淆算法放行，allow-list 而非 deny-list)。
- 两处 monkey patch 值得注意 (`epub_loader.py:428-456`):`_write_items_patch` 让导入过的 nav.xhtml 写出**翻译后的 content** 而不是 ebooklib 默认的从 `book.toc` 重新生成;`rebase_ncx_srcs` 修正子目录 NCX 的相对 src(`helper.py:229-250`)。`_load_spine` patch(`epub_loader.py:463-472`) 容错 spine 里的 XML 注释节点 (ebooklib 会把注释读成 `(None,None)` tuple 在写时崩)。
- 字体：`encryption.xml` 声明的混淆字体读入时解混淆 (`epub_loader.py:480-489`),写出后重新混淆 (`epub_loader.py:921-932`, `font_obfuscation.py`:IDPF/Adobe 两种算法，XOR 前 1040 字节)。**这是 ebooklib 路线的专属成本**——它丢弃 `META-INF/*`;我们 stdlib 照抄 zip 条目，`encryption.xml` 原样保留，只要不改 `dc:identifier` 字体就免处理 (见 §2.6)。

### 1.2 文档枚举 & 资产保留

- 翻译面 = `get_items_of_type(ITEM_DOCUMENT)`(`epub_loader.py:3844-3848`),即 manifest 里所有 `application/xhtml+xml`——**EPUB3 nav.xhtml 也是 EpubHtml 会被翻**,NCX(toc.ncx, `ITEM_NAVIGATION`) 不进翻译流，写时由 `book.toc` 重建。
- 非文档 item(图片/CSS/字体/SMIL) 在翻译开始前**先**全部 add 进新书 (`epub_loader.py:3884-3889`,注释：中断后也能看到图)。文件过滤 (only/exclude_filelist)**只跳过翻译不删文档**——否则 spine/nav/ncx 指向不存在的文件，epubcheck RSC-007(`epub_loader.py:3216-3224` 的注释把这个坑讲得很清楚)。
- spine 整体照抄但滤掉 idref 为空的 tuple 和上一轮的 colophon 页 (`epub_loader.py:737-742`)。

### 1.3 文本提取 (谁是 unit)

两档实现，v1 我们只需要前一档 + 少量后档：

**Tag 模式 (简单档)**:`soup.findAll(translate_tags)`(默认 `"p"`,`epub_loader.py:345`)→ `filter_nest_list` 丢掉含同类嵌套的 (如 `<p><p>` 场景，`epub_loader.py:3098-3108`)→ `p.text` 为源文。抽取前 `_extract_paragraph` 在**副本**上把 exclude_tags(默认 `sup,code`)`extract()` 掉再 `get_text()`(`epub_loader.py:960-968`, `3110-3114`)——原文节点在 DOM 里不动，排除只影响送模型的文本。

**Plan 模式 (完整档，`plan.py`)**:每个文本节点归属最近的 block owner(`_nearest_block`,`plan.py:757-763`),owner 的文本被 barrier 切成 run(Unit,`plan.py:1069-1102`):三类 barrier = 嵌套 block / skip 分类的可见节点 / `<pre>` 外的 `<br>`(`_iter_owner_events`,`plan.py:851-943`)。**内联标签边界不是 barrier**(`plan.py:884-893`:`<a>` 直接把句子切断会毁翻译质量，靠插入规则解决落点)。`<br>` 前插 `\n` 文本节点防 "one<br>two" 粘成 "onetwo"(`_separate_brs`,`plan.py:727-734`)。

**跳过规则 (送模型前的过滤器)**:

| 规则                                                                                       | 位置                                                      |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| 纯数字/空白/纯 URL/全标点                                                                  | `_is_special_text`,`epub_loader.py:507-514`               |
| URL 尾链/`Source:`/`Listing N`/`Figure N`/ISBN                                             | `not_trans`,`helper.py:636-647`                           |
| 整段只剩 exclude 标签内容                                                                  | `_is_content_only_excluded_tags`,`epub_loader.py:970-987` |
| 祖先在 `script/style/head/title/template/svg/math`(NON_CONTENT)                            | `plan.py:111-113`,`_ancestor_skip_reason:662`             |
| ruby 注音 `rt/rp/rtc` 永不送模型                                                           | `plan.py:118`,`_ancestor_skip_reason:664`                 |
| `epub:type=pagebreak`/`role=doc-pagebreak` 页码                                            | `plan.py:668-673`                                         |
| CSS `display:none`/`hidden` 属性 **但** `epub:type=footnote` 等注义豁免 (弹注阅读器仍显示) | `plan.py:674-688`                                         |

### 1.4 插译四种形态 (核心做法)

双语模式永远：**原文节点不动，译文节点是克隆/新节点插在后面**。

1. **普通克隆**(`helper.py:445-476` `insert_trans`):`copy(p)` → `new_p.string = 译文`(摊平成纯文本，译文不带内联标记)→ `strip_duplicate_ids` 去掉克隆上所有 id(防 epubcheck RSC-005 双锚，`helper.py:353-367`)→ `restamp_language` 把源节点声明过的 `lang/xml:lang` 改成目标语言 (`helper.py:400-411`)→ `--translation_style` 加 `style` 属性 → `p.insert_after(new_p)`。
2. **受限容器**(内容模型只准一个该元素):`figcaption/caption/legend/summary`(SINGLETON_TAGS,`helper.py:101`) 及 `<nav>` 后代——译文改为**内部追加** `<br/><span>译文</span>`(`helper.py:326-350` `append_inline_translation`);nav `<li>` 只允许 `(a|span),ol?`,落点定位到 `<a>/<span>` 内 (`translation_host`,`helper.py:310-323`)。
3. **锚定插译**(run 在复杂 owner 里，如 `<div>前文<p>嵌套</p>后文</div>` 的两段 run):译文跟在 run 最后一个文本节点之后;若 run 的最外内联 markup 恰好覆盖整 run 则克隆它 (保 `span.lin` 这类 CSS 钩子),否则 bare `<span>`(`epub_loader.py:2213-2249`)。
4. **含排除标签的段落**(`_insert_trans_preserving_tags`,`epub_loader.py:2609-2682`):双语时克隆副本先 `extract()` 掉 exclude 标签再填译文;单译时把 code 抠出→填译文→挂回末尾 (位置映射是已知弱点，marker 协议才是正解)。

另有 sentence_mode:句级交错 `原文 译文span` 交替 append(`epub_loader.py:2936-2972`)——一种可选呈现，不影响主协议。

### 1.5 marker 占位协议 (内联 `<a>`/`<code>`/`<img>` 怎么保护)

这是和我们的 LaTeX 占位符体系直接对应的一块，设计在 `markers.py`(262 行，全文值得读):

- **什么变 marker**:受保护且*短*的内联元素——exclude 的 `<code>`/`<sup>`、`<img>` 等 RENDERED_VOID、skip 分类的内联。含词文本 ≥40 字符保持 barrier(append 到句尾太毁);无词文本 (URL、排开的公式) 放宽到 400 字符 (`INLINE_MARKER_MAX_CHARS`,`markers.py:41,58`;判定 `is_wordless`,`markers.py:102-110`)。候选判定 `_marker_candidate`,`plan.py:791-848`;`<a href><img></a>` 取**外层 wrapper** 做 marker 源 (`plan.py:833-839`)。
- **token 形态**:`⟦code1⟧`(`MARKER_OPEN/CLOSE`,`markers.py:113-119`)。每文档一份单调序号 (`Ordinals`,`markers.py:134-159`)。
- **碰撞回避**:token 若在源文里已逐字出现就重新编号，保证在被送文本里恰好出现一次 (`markers.py:146-159`)。
- **幻觉清洗**:回复里出现**没发过**的 marker 形 token 一律剥掉;发的丢了则在句尾按源序补回——**宽容调和，绝不因 marker 重试**(`reconcile_markers`,`markers.py:192-221`,置顶 docstring 写明是 pinned 决策)。
- **写回**:译文插进 DOM 后，在**刚插入的节点内**找含 token 的文本节点，`split_on_markers` 切开，bilingual 模式塞入源元素的 `copy()`(再 strip id),single 模式 `extract()` 移动原节点 (`_restore_markers`,`epub_loader.py:2115-2175`)。
- **`<a>` 不是 marker**:内联标记边界不切断 run(§1.3),译文是纯文本，活链接留在原文里。配对 marker(`⟦em4⟧…⟦/em4⟧`) 被明确划出范围 (`markers.py:31`, `plan.py:889-892`:单译模式保内联链接需要配对协议，v1 不建议)。

### 1.6 批量/对齐协议 (与编排层的接口形状)

- 契约：`translate_list(texts)` 返回**恰好等长对齐**的 list，否则抛 `BatchMismatch`(`base_translator.py:1174-1210`)。
- 回复解析三级：先按 `(1)(2)…` 编号正则切 → 再按 `@@` 分隔符切 → 数量不符即 mismatch,**不再**按行硬切 (会把多行回复切成错误的"译文",`base_translator.py:1300-1331`)。
- 对齐梯子：`group → halves → singles`,一次折半重问而非逐条 (8+4+2+1+1 ≈ 2× 成本，`_translate_texts_aligned`/`_divide_and_translate`,`epub_loader.py:2352-2434,2588`)。
- **移位检测**:数量对但槽位错——靠 marker slot 证据 (`_marker_slot_mismatch`,`epub_loader.py:2437`) 和数字指纹漂移 (`_numeric_slot_shift`,`epub_loader.py:2504`) 检出后同样走梯子。
- 分组:tag 模式 `--accumulated_num` 是 **token 预算**(tiktoken cl100k,`utils.py:500`),`_assign_batch_indexes` 给每个 unit 打 batch_index(`epub_loader.py:3121-3141`);plan 模式 group_id→batch_index(`_plan_batch_indexes`,`epub_loader.py:3144-3186`,`max_units`/`max_tokens` 双帽)。

### 1.7 断点续传

- 文件：`.{stem}.temp.bin` pickle，放原书旁边 (`epub_loader.py:493`)。
- 内容 (`_save_progress`,`epub_loader.py:4193-4218`):`{version:3, order:"document", job_ids, translations, run_fingerprint, plan_fingerprint?}`。`p_to_save` 是按 global_index 追加的译文 list,**位置即槽位**。
- job_id = `epub:{document_index}:{file_name}:{node_index}:{sha256(text)[:16]}`(`epub_loader.py:3117-3119`)。resume 时重算全部 job,checkpoint 的 job_ids 必须等于新计划的**前缀**,否则报"EPUB 或过滤器变了，删档重翻"(`epub_loader.py:3853-3862`);run_fingerprint 绑住语言/prompt/模型 (`epub_loader.py:1323-1398`)。
- 每 20 条 save 一次 (`epub_loader.py:2757`);Ctrl-C → save + `_save_temp_book` + exit(130)(`epub_loader.py:4039-4052`)。
- **`_save_temp_book`**(`epub_loader.py:4120-4191`):中断时也产出一本半成品双语书——重读原 epub、重建计划、把 `p_to_save` 按 global_index 回放插译。这个"partial book"思路值得抄。

### 1.8 nav/NCX/metadata/写回

- nav.xhtml 走 §1.4 规则 2 翻译;写出时靠 `_write_items_patch` 保留翻译后的 content 不被重建覆盖 (`epub_loader.py:435-444`)。NCX 不翻文本——它由 `book.toc` 重建，`_fix_toc_uids` 补空 uid 防 TypeError(`epub_loader.py:934-958`),`backfill_toc_hrefs` 给无 href 的 Section 拿首个后代 href(`helper.py:253-283`);源书没 NCX 时主动补一个 (EPUB2 fallback,`epub_loader.py:540-541`)。
- metadata:按 ebooklib 认识的 namespace 白名单逐条拷，失败的收集警告 (`epub_loader.py:601-672`);OPF `prefix` 声明带回 (`helper.py:148-193` `read_package` 就是 stdlib 直读 zip 的范本);dc:language 目标语言置首 (`epub_loader.py:702-717`);dc:source 指回源书 uid(`epub_loader.py:724-728`);新 uuid = `uuid5(source_uid|lang|mode)` 稳定派生 (`helper.py:196-226`)。
- 披露：`stamp_disclosure` 在 guide/landmark 找到的扉页加机翻署名行，可 `--no_disclosure`(`disclosure.py:717+`,`epub_loader.py:878-907`)。
- 写回：`item.content = soup.encode(encoding="utf-8")`(`epub_loader.py:3448`),`epub.write_epub` 收尾 (`epub_loader.py:918`)。bs4 序列化的已知坑：手工造的 `<br>` 要 `can_be_empty_element=True` 否则输出 `<br></br>` 被 HTML5 解析器读成两个换行 (`make_tag`,`helper.py:286-300`)。

---

## 2. texlate EPUB spec(stdlib 自拆，~300 行)

### 2.1 取舍

| 抄                                             | 不抄 (v1)                                                      |
| ---------------------------------------------- | -------------------------------------------------------------- |
| DRM stdlib 预检 (`rights.py` 60 行)            | plan/classify/ledger 全套 (`plan.py` 2226 行)                  |
| unit 枚举 + job_id + 前缀校验断点              | 单译模式 (只做双语)                                            |
| 克隆插译 + 受限容器内联追加                    | sentence_mode、retranslate、披露页、translation_metadata       |
| marker 占位协议 (⟦⟧ 或换成我方 `[[IMG_n]]` 皮) | 字体解/重混淆 (照抄 zip 条目即免疫，见 2.6)                    |
| barrier 切 run 的最小子集：嵌套 block + `<br>` | CSS display 解析器 (v1 只查 `hidden` 属性+`display:none` 内联) |
| (1)(2)/分隔符解析 + 对齐梯子                   | epubcheck 全量对账 (只留 strip id + 内容模型两条硬规则)        |

unit 定义 (v1):最近 block 祖先 = `{p,h1..h6,li,blockquote,figcaption,td,th,caption,dt,dd,div(仅当其不含子 block 时),section 同 div,nav 内 a/span}`,排除 §1.3 表中的 NON_CONTENT/exclude/pagebreak/hidden;run 在嵌套 block 和非 pre `<br>` 处切断。tag 级粗粒度起步也行，但 `<br>` 切 run 很便宜建议直接带。

### 2.2 骨架伪代码 (~280 行)

```python
# epub_pipeline.py — stdlib zipfile + bs4，无 ebooklib
CONTAINER = "META-INF/container.xml"
CNS = "{urn:oasis:names:tc:opendocument:xmlns:container}"
OPF = "{http://www.idpf.org/2007/opf}"
XHTML_MT = {"application/xhtml+xml", "text/html"}
NON_CONTENT = {"script","style","head","title","template","svg","math"}
RUBY_RT = {"rt","rp","rtc"}; EXCLUDE = {"sup","code"}  # 可配
BLOCK = {"p","h1","h2","h3","h4","h5","h6","li","blockquote",
         "figcaption","td","th","caption","dt","dd","div","section","aside"}
SINGLETON = {"figcaption","caption","legend","summary"}

def load(path):                                   # ~60 行，含 rights.check 移植
    if check_drm(path) == "drm": raise DrmError()
    zf = zipfile.ZipFile(path)
    members = {i.filename: zf.read(i) for i in zf.infolist()}
    order = [i.filename for i in zf.infolist()]   # 保序用于回写
    container = etree.fromstring(members[CONTAINER])
    opf_path = container.find(f".//{CNS}rootfile").get("full-path")
    opf_dir = posixpath.dirname(opf_path)
    opf = etree.fromstring(members[opf_path])
    manifest = {it.get("id"): (it.get("href"), it.get("media-type"),
                               it.get("properties") or "")
                for it in opf.iter(f"{OPF}item")}
    spine = [ir.get("idref") for ir in opf.iter(f"{OPF}itemref")]
    docs = [posixpath.join(opf_dir, manifest[i][0])
            for i in spine if manifest[i][1] in XHTML_MT]
    # spine 之外、manifest 里也是 xhtml 的 (如不在 spine 的 nav/封面)追加在尾
    docs += [posixpath.join(opf_dir, h) for _id,(h,mt,_p) in manifest.items()
             if mt in XHTML_MT and posixpath.join(opf_dir,h) not in docs]
    return members, order, docs

def iter_units(members, doc_paths):               # ~90 行:walk→跳过→切 run→marker
    for di, path in enumerate(doc_paths):
        soup = bs(members[path], "html.parser")
        for owner in soup.body.descendants:       # 伪代码：实际先收集 block
            ...  # 对每个 block owner:收集 own 文本节点 (祖先不含 NON_CONTENT/
                 #  RUBY_RT/EXCLUDE/hidden/display:none),遇嵌套 block/<br> 切 run;
                 #  短保护内联 → 分配 ⟦tag{n}⟧ 占位并记 {token: element}
            text = normalize(run_text_with_markers)
            if not text or is_special(text): continue
            yield Unit(job_id=f"epub:{di}:{path}:{ni}:{sha256(text)[:16]}",
                       text=text, owner=owner, run_nodes=nodes, markers=mk,
                       soup=soup, doc_path=path)

def insert_translation(unit, zh_text):            # ~60 行，§1.4 规则 1/2/3
    zh_text = reconcile_markers(unit.text, zh_text, unit.markers)
    el = unit.owner
    if el.name in SINGLETON or el.find_parent("nav"):
        span = make_tag("span", **{"class":"texlate-zh"}); span.string = zh_text
        host = nav_label_or(el); host.append(make_tag("br")); host.append(span)
    else:
        new_p = copy(el)                          # 克隆继承标签名+class(版式)
        strip_ids(new_p); restamp_lang(new_p, "zh-CN")
        new_p["class"] = (new_p.get("class") or []) + ["texlate-zh"]
        new_p.clear(); new_p.string = zh_text     # 多 run owner 用锚定插
        el.insert_after(new_p)
    restore_markers(unit)                         # token→copy(源元素),epub_loader.py:2115

def save(path, members, order, soups):            # ~40 行
    for p, soup in soups.items(): members[p] = soup.encode("utf-8")
    inject_css(members)   # 见 2.4:每篇 <head> 内嵌 <style>,不动 manifest
    with zipfile.ZipFile(path, "w") as out:
        out.writestr("mimetype", "application/epub+zip",
                     compress_type=zipfile.ZIP_STORED)      # 首文件不压缩！
        for name in order:
            if name == "mimetype": continue
            out.writestr(name, members[name],
                         compress_type=zipfile.ZIP_DEFLATED)

def translate_epub(src, dst, orchestrator, resume=True):    # ~50 行
    members, order, docs = load(src)
    ck = load_ckpt(src)                         # {job_ids:[], translations:[]}
    units = list(iter_units(members, docs))
    if ck and ck["job_ids"] != [u.job_id for u in units][:len(ck["job_ids"])]:
        raise ResumeError("EPUB 或过滤变了，删档重翻")
    soups = {}
    for i in range(len(ck["translations"]), len(units)):
        u = units[i]; soups.setdefault(u.doc_path, u.soup)
        zh = ck_get(i) or orchestrator.translate(u.text)   # 批量见 2.5
        insert_translation(u, zh); ck_append(u.job_id, zh)
        if i % 20 == 0: save_ckpt(src, ck)
    save(dst, members, order, soups)
```

### 2.3 断点格式

bbm 的 pickle dict 换成 **JSONL**(纯文本、免 pickle 安全隐患、好 diff):每行 `{job_id, translation}`,头部一行 meta `{version, fingerprint}`。job_id/fingerprint/前缀校验/每 20 条 flush/`_save_temp_book` 半成品回放——语义全部照抄 §1.7。Ctrl-C 时同样写 partial epub。

### 2.4 译文样式注入

两选一并存：

- **class + 内嵌样式 (推荐)**:译文节点统一 `class="texlate-zh"`,在每篇 XHTML `<head>` 里 append 一个 `<style>` 块 `.texlate-zh{color:#555;}`——EPUB2/EPUB3 的 `<head><style>` 都合法，**不需要动 manifest/OPF**(新增独立 css 文件才需要登记 manifest item + `<link>`,不划算)。主题可配置时改这一段 CSS 即可。
- **行内 style(bbm 路线)**:`new_p["style"] = translation_style`(`helper.py:459-460`,`--translation_style` flag `cli.py:1961`)。零文件改动，但样式散在每个节点上不可主题化。

### 2.5 与 LLM 编排层的接口

```python
Unit = {job_id: str, text: str,           # 送模型文本 (已含 ⟦⟧ 占位)
        markers: {token: element},        # 写回用
        context_group: str}               # = doc_path，上下文窗口按章分组
```

- `orchestrator.translate(text) -> str` / `translate_list(texts) -> list[str]`,批量契约与 LaTeX 侧同：`(n)` 编号 + `@@` 兜底 + BatchMismatch + 折半梯子，**编排层零改动复用**。
- 占位符需求：沿用 LaTeX 侧的语义但换 token 面——EPUB 侧受保护的是**元素**而非区间，所以 marker 值是 DOM 节点引用而非字符串。协议三件套照抄：分配防碰撞 (`markers.py:146-159`)→ 回复调和 (`markers.py:192-221`)→ 写回克隆 (`epub_loader.py:2152-2175`)。
- prompt 侧只多一句："⟦…⟧ 是原样保留的占位符，译文中保持在对应位置"。
- 分组建议直接 token 预算 (`accumulated_num` 语义，tiktoken 已在依赖内)。

### 2.6 EPUB 特有注意点

- **mimetype 必须第一且 ZIP_STORED**(OCF 硬性要求，否则严格阅读器拒开);其余成员按原 infolist 顺序 ZIP_DEFLATED。
- **NCX**:`application/x-dtbncx+xml` 不在 XHTML_MT，不进翻译流。`navLabel/text` 想翻就用同一 text-node walk 直接改 XML(便宜),不翻也合法——bbm 干脆重建。v1 建议翻:text 节点替换 + 生成双语 `原文 / 译文` 或直接双语同串。
- **nav.xhtml**:`properties="nav"` 的 manifest item;`<li>` 内容模型限制走 §1.4 规则 2,`translation_host` 把落点定位进 `<a>/<span>`(`helper.py:310-323`)。
- **字体混淆**:照抄 `encryption.xml` + 所有字体条目 + **不改 dc:identifier** → 混淆密钥不变，字体免处理。这是 stdlib 相对 ebooklib 的净赚 (ebooklib 丢 META-INF,bbm 被迫写 340 行 deob/reob)。若将来要换 identifier，才需要移植 `font_obfuscation.py`。
- **fixed-layout**:`<meta property="rendition:layout">pre-paginated</meta>` 的书 (CSS 绝对定位逐页) 插译必破版式 → v1 检测后警告并拒翻或仅元数据标记。
- **entities**:XHTML 里 `&nbsp;` 等命名实体，bs4 html.parser 直接消化 (bbm 全库同款选择，`epub_loader.py:3246`),lxml xml 解析需载 DTD——跟 bbm 选 bs4。
- **SMIL/media-overlay**:同步数据不是正文，不翻，照抄。
- 校验闭环:epubcheck 跑一遍 (`test_epub_output_validity.py` 是按 RSC/OPF 编号组织的现成对账清单，RSC-005 双 id、RSC-007 断链、OPF-049 ncx 悬挂是高频三项)。

---

## 3. DOCX spec(python-docx,MIT)

### 3.1 遍历矩阵

| 面              | API                                                                                                                    | 说明                                              |
| --------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| 正文段落 + 表格 | `doc.iter_inner_content()`(1.1+,产出 Paragraph/Table 按文档序);旧版遍历 `doc.element.body` 的 `w:p`/`w:tbl` 子元素     | `doc.paragraphs` 只给 body 顶层，**漏表格内段落** |
| 表格 (可嵌套)   | `table.rows→cells→cell.iter_inner_content()`(cell 也是 BlockItemContainer)                                             | 单元格 `w:tc` 递归即可                            |
| 页眉页脚        | `section.header/.footer`(及 even/first_page 变体),同 iter_inner_content                                                | 每 section 三份                                   |
| 文本框/形状     | `.//w:txbxContent/w:p` xpath(drawing/VML 内都可能)                                                                     | python-docx 不建模，raw XML                       |
| 内容控件        | `w:sdt→w:sdtContent` 内 `w:p`                                                                                          | 同上                                              |
| 脚注/尾注/批注  | `word/footnotes.xml`/`endnotes.xml`/`comments.xml` 经 `doc.part.package` raw part;1.2 起批注有 `Document.comments` API | 脚注引用的 `w:footnoteReference` 留原文段不动     |
| 跳过            | `w:instrText`/`w:fldSimple`(域代码/TOC)、`w:del`(修订删除)、`m:oMath`(§4)                                              | `w:ins`(修订插入) 翻不翻两可，v1 翻               |

### 3.2 插译 + 样式复制 (核心 30 行)

```python
def insert_after(paragraph, zh_text):
    new_ct_p = copy.deepcopy(paragraph._p)          # CT_P:pPr+runs 全拷
    for child in list(new_ct_p):
        if child.tag != qn('w:pPr'):                # 只留段落属性
            new_ct_p.remove(child)
    paragraph._p.addnext(new_ct_p)                  # lxml addnext = insert_after
    p2 = Paragraph(new_ct_p, paragraph._parent)
    run = p2.add_run(zh_text)
    src_rpr = paragraph._p.find(qn('w:r') + '/' + qn('w:rPr'))  # 取首个 run 的 rPr
    if src_rpr is not None:
        run._r.insert(0, copy.deepcopy(src_rpr))    # 继承字体/字号
    rpr = run._r.get_or_add_rPr()
    rpr.get_or_add_rFonts().set(qn('w:eastAsia'), 'SimSun')   # 中文回退字体
    run.font.color.rgb = RGBColor(0x55, 0x55, 0x55) # 双语区分色 (可配)
```

要点:pPr 深拷**连 numPr/缩进/段落样式 id 一起继承**——译文列表项拿到自己的编号、译文段挂同样式，这正是想要的。更进一步可在 `doc.styles` 建一个 `TeXlateZH` 段落样式 (基于源 style + eastAsia 字体 + 颜色),`p2.style = 'TeXlateZH'`,但列表编号不在 style 里而在 pPr,deepcopy 路线已覆盖，样式对象只做颜色/字体差分。

重打包零成本：`doc.save()` 全量保 part(图片/theme/numbering/styles/settings 原样),**没有 EPUB 的 mimetype 约束**。断点协议与 EPUB 同构:job_id = `docx:{part}:{p_index}:{sha256(text)[:16]}`,JSONL 前缀校验。

### 3.3 与编排层接口

和 EPUB 完全同形：`Unit{job_id,text,markers,context_group=part_name}`;marker 对应 `<w:r>` 里的 drawing/object/math 子树——`⟦img1⟧`/`⟦math1⟧` 写回时在译文段对应位置 deepcopy 原 `w:r`。v1 简化：含 `w:drawing`/`m:oMath` 的段落，抽取文本时只拼非保护 `w:t`,保护物若是整段主体直接 skip 该 unit(双语模式下原文段反正留着)。

---

## 4. 优先级建议

**维持路线图:EPUB/DOCX 都在 M3，顺序 EPUB → DOCX,PDF 不提前。**

1. **EPUB 先行 (M3 第 9-10 周)**:蓝图最完整 (bbm 把 epubcheck 级别的坑全趟过一遍)、stdlib ~300 行可达 v1、DOM 模型与未来 web 双语阅读器同源、且是 hjfy 没有的功能——差异化最高的便宜活。语料用 Gutenberg/epub3-samples(bbm test_books/ 也有 3 本)。
2. **DOCX 紧随 (M3 第 10-11 周)**:python-docx MIT、插译核心只有 30 行，但遍历面多 (§3.1 六行表) 且每面独立——估 ~300-400 行。学术用户需求实 (arXiv 之外的稿件)。
3. **PDF 不提前**:PDF 没有 DOM——段落语义要重建，和 EPUB/DOCX 不是一个宇宙。MinerU→md 已在 M3 当过渡 (有损但零风险),真正的同页双语 PDF 是 BabelDOC sidecar(M4,AGPL 隔离已是既定决策)。把它拉进 M3 等于同时开两条战线。

## 5. 边界一览

| 边界         | EPUB                                                                                                                                    | DOCX                                                                                            |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 图文混排     | `<img>` 短保护 → `⟦imgN⟧` marker(`plan.py:820`,`markers.py:41`);`<a><img>` 取外层 a(`plan.py:833`);figure+figcaption 走受限容器内联追加 | `w:drawing` 在原文段不动，译文段纯文本;纯图段无 `w:t` → 跳过;想保位置用 `⟦imgN⟧`+deepcopy `w:r` |
| 数学         | `<math>` 在 NON_CONTENT(plan.py:112)+ RENDERED_VOID:永不进源文，句中 → wordless marker(400 字符帽)                                      | `m:oMath`/`m:t` 跳过不送模型;句中公式用 `⟦mathN⟧` 保位，或 v1 整段跳过                          |
| 竖排         | CSS `writing-mode` 自动继承，译文克隆节点同向排——**免处理**                                                                             | `w:textDirection`/`w:vert` 在 pPr 里，deepcopy 自动带——**免处理**                               |
| fixed-layout | `rendition:layout=pre-paginated` → 警告拒翻                                                                                             | DOCX 本就固定版式，正常翻                                                                       |
| ruby/注音    | `rt/rp/rtc` 永不送模型 (`plan.py:118`),译文不写回注音                                                                                   | `w:ruby` phonetic 同理跳过                                                                      |
| DRM/加密     | `rights.py` stdlib 预检拒开 (60 行可移植)                                                                                               | 加密 docx python-docx 开不了，异常即拒                                                          |
| 字体         | 照抄 `encryption.xml`+保留 `dc:identifier` → 混淆字体免处理 (§2.6)                                                                      | 嵌入字体随 package 原样保留                                                                     |
| 目录         | nav `<li>` 内联追加 (`helper.py:310`);NCX 翻 `<text>` 或留                                                                              | TOC 域代码跳过 (页码反正失效)                                                                   |
| 表格         | `td/th` 是普通 block owner                                                                                                              | `w:tc` 递归遍历，插译同 body                                                                    |
| 脚注/尾注    | `epub:type=footnote` 即使 CSS 隐藏也翻 (弹注阅读器会显示，`plan.py:674-687`)                                                            | `footnotes.xml` raw part 同法插译                                                               |
| 批注/修订    | —                                                                                                                                       | comments.xml 翻;`w:del` 跳 `w:ins` 翻                                                           |
| 长保护内联   | >40 字符含词/>400 无词 → 保持 barrier 切 run(防 append 到句尾毁版面)                                                                    | 同策略：大 drawing/object 整段跳过                                                              |
| 隐藏文本     | `display:none`/`hidden` 跳过 (footnote 义除外)                                                                                          | `w:vanish`(隐藏文字属性) 跳过                                                                   |

### v1 明确不做

单译 (替换) 模式、paired inline marker(`⟦em⟧…⟦/em⟧`)、CSS 级联 display 解析 (只查内联 `display:none`+`hidden`)、披露/署名页、epubcheck 全量对账、字体混淆改写 (照抄即免疫)、`--retranslate`/`--only_filelist` 族。
