from http import HTTPStatus

import httpx
import pytest
from bs4 import BeautifulSoup
from conftest import FakeClock, mk_fetcher

from texlate.arxiv.html import (
    HtmlBlock,
    HtmlDoc,
    HtmlFetchError,
    HtmlNotAvailableError,
    doc_chunks,
    fetch_html,
    marked_html,
    parse_arxiv_html,
    reinsert,
)

#: 手工小样本——覆盖 para/title/abstract/keywords/caption/bibitem/figure/
#: math/cite/ref/note/listing/pagination + article 外 chrome。
FIXTURE = """<!DOCTYPE html><html><body>
<header class="arxiv-html-header">site chrome</header>
<nav class="ltx_TOC"><ol class="ltx_toclist"><li class="ltx_tocentry">toc</li></ol></nav>
<article class="ltx_document">
<h1 class="ltx_title ltx_title_document">Test Paper Title</h1>
<div class="ltx_authors"><span class="ltx_personname">Some One</span></div>
<div class="ltx_abstract" id="abs1"><h6 class="ltx_title ltx_title_abstract">Abstract</h6>
<p class="ltx_p" id="abs1.1">We propose a method <math alttext="x^2" class="ltx_Math" display="inline"><semantics><mi>x</mi><annotation encoding="application/x-tex">x^2</annotation></semantics></math> for testing.</p></div>
<div class="ltx_classification"><h6 class="ltx_title ltx_title_classification">keywords</h6>Foo, Bar</div>
<section class="ltx_section" id="S1">
<h2 class="ltx_title ltx_title_section"><span class="ltx_tag ltx_tag_section">1 </span>Introduction</h2>
<div class="ltx_para" id="S1.p1"><p class="ltx_p" id="S1.p1.1">First para with cite <cite class="ltx_cite">(<a class="ltx_ref" href="#bib.b1">Doe, 2020</a>)</cite> and ref <a class="ltx_ref" href="#S2">Section 2</a> and ext <a class="ltx_href" href="https://x.dev">code</a>.</p></div>
<div class="ltx_para" id="S1.p2"><p class="ltx_p" id="S1.p2.1">Before eq.</p>
<table class="ltx_equation ltx_eqn_table" id="S1.E1"><tbody><tr><td class="ltx_eqn_cell"><math alttext="E=mc^2" display="block"><mi>E</mi></math></td><td class="ltx_eqn_cell"><span class="ltx_tag ltx_tag_equation">(1)</span></td></tr></tbody></table>
<p class="ltx_p" id="S1.p2.2">After eq <span class="ltx_note ltx_role_footnote" id="fn1"><sup class="ltx_note_mark">1</sup><span class="ltx_note_outer"><span class="ltx_note_content"><sup class="ltx_note_mark">1</sup> <span class="ltx_tag ltx_tag_note">1</span>Note text here.</span></span></span> end.</p>
<ul class="ltx_itemize"><li class="ltx_item" id="S1.i1"><div class="ltx_para" id="S1.i1.p1"><p class="ltx_p">Item text one.</p></div></li></ul>
</div>
<div class="ltx_para" id="S1.p3"><span class="ltx_ERROR undefined">\\badcmd</span></div>
</section>
<section class="ltx_section" id="S2">
<h2 class="ltx_title ltx_title_section"><span class="ltx_tag ltx_tag_section">2 </span>Results</h2>
<figure class="ltx_figure" id="S2.F1"><object class="ltx_graphics" data="f.svg"></object>
<figcaption class="ltx_caption"><span class="ltx_tag ltx_tag_figure">Figure 1: </span>A caption with <math alttext="y" display="inline"><mi>y</mi></math> math.</figcaption></figure>
<div class="ltx_listing" id="S2.L1"><div class="ltx_listingline">code()</div></div>
<div class="ltx_para" id="S2.p1"><p class="ltx_p">Para in section two.</p></div>
</section>
<section class="ltx_bibliography" id="bib">
<h2 class="ltx_title ltx_title_bibliography">References</h2>
<ul class="ltx_biblist"><li class="ltx_bibitem" id="bib.b1"><span class="ltx_tag ltx_tag_bibitem">[1]</span><span class="ltx_bibblock">Doe, J. Title. 2020.</span></li></ul>
</section>
<div class="ltx_pagination ltx_role_newpage"></div>
</article>
<footer class="arxiv-html-footer">site chrome</footer>
</body></html>"""


MIN_CHUNKS = 10


def _doc() -> HtmlDoc:
    return parse_arxiv_html(FIXTURE, arxiv_id="2501.00001")


def _block(doc: HtmlDoc, key: str) -> HtmlBlock:
    """``doc.blocks`` 按 key 取块——找不到即 StopIteration（断言即查找失败）。"""
    return next(b for b in doc.blocks if b.key == key)


def _ctx_seq() -> list[tuple[str, str]]:
    return [(b.key, b.context) for b in _doc().blocks]


def test_parse_no_article_raises() -> None:
    with pytest.raises(HtmlNotAvailableError) as ei:
        parse_arxiv_html("<html><body><p>stub page</p></body></html>")
    assert ei.value.status == HTTPStatus.OK


def test_block_order_and_keys() -> None:
    ctx = _ctx_seq()
    keys = [k for k, _ in ctx]
    # 文档序：题录 → authors(support) → 摘要块 → 关键词 → S1 → S2 → bib
    assert keys[:2] == ["b1", "b2"]  # h1 + authors 无 id → 合成键
    assert ctx[0] == ("b1", "title")  # h1.ltx_title_document
    assert ctx[1] == ("b2", "authors")
    assert ("S1.p1", "para") in ctx
    assert ("S1.p2", "para") in ctx
    assert ("S1.i1.p1", "para") in ctx  # li 内 ltx_para 独立成块
    assert ("fn1", "footnote") in ctx
    assert ("S2.F1", "figure") in ctx
    assert ("bib.b1", "bibitem") in ctx
    # footnote 紧跟宿主 para
    i = keys.index("S1.p2")
    assert keys[i + 1] == "fn1"


def test_title_contexts() -> None:
    doc = _doc()
    sections = [b for b in doc.blocks if b.context == "section"]
    texts = {b.text for b in sections}
    assert {"Introduction", "Results", "References", "Abstract", "keywords"} <= texts
    # h1.ltx_title_document → context title（latex \\title → caption kind）
    assert any(
        b.context == "title" and b.text == "Test Paper Title" for b in doc.blocks
    )


def test_math_placeholder_roundtrip() -> None:
    doc = _doc()
    abs_block = _block(doc, "abs1.1")
    assert "[[MATH_" in abs_block.text
    assert "x^2" not in abs_block.text
    tok = abs_block.text.split("[[")[1].split("]]")[0]
    frag = doc.ph_map[f"[[{tok}]]"]
    assert 'alttext="x^2"' in frag
    out = reinsert(abs_block.text, doc.ph_map)
    assert 'alttext="x^2"' in out
    assert "[[MATH_" not in out


def test_display_eq_token_in_para() -> None:
    doc = _doc()
    p2 = _block(doc, "S1.p2")
    assert "Before eq." in p2.text
    assert "After eq" in p2.text
    assert "[[MATH_" in p2.text
    frag = next(f for t, f in p2.ph.items() if t.startswith("[[MATH"))
    assert 'alttext="E=mc^2"' in frag
    assert "(1)" not in p2.text  # 公式编号 ltx_tag 剥离


def test_cite_ref_extlink() -> None:
    doc = _doc()
    p1 = _block(doc, "S1.p1")
    assert "[[CITE_" in p1.text
    assert "[[REF_" in p1.text
    assert "Doe, 2020" not in p1.text  # cite 渲染文本被保护
    assert "code" in p1.text  # 外链锚文本照译


def test_error_cmd_token() -> None:
    doc = _doc()
    p3 = _block(doc, "S1.p3")
    assert "[[CMD_" in p3.text
    assert "\\badcmd" not in p3.text


def test_footnote_block() -> None:
    doc = _doc()
    fn = _block(doc, "fn1")
    assert fn.context == "footnote"
    assert fn.text == "Note text here."
    p2 = _block(doc, "S1.p2")
    assert "[[NOTE_" in p2.text


def test_caption_inside_figure() -> None:
    doc = _doc()
    caps = [b for b in doc.blocks if b.context == "caption"]
    assert len(caps) == 1
    assert caps[0].text.startswith("A caption with")
    assert "Figure 1:" not in caps[0].text  # ltx_tag 剥离
    assert "[[MATH_" in caps[0].text


def test_support_blocks_no_text() -> None:
    doc = _doc()
    for key, ctx in [("bib.b1", "bibitem"), ("S2.F1", "figure"), ("S2.L1", "listing")]:
        b = _block(doc, key)
        assert b.context == ctx
        assert b.text == ""


def test_doc_chunks() -> None:
    doc = _doc()
    chunks = doc_chunks(doc)
    by_id = {c.chunk_id: c for c in chunks}
    # 可译块：文档题/摘要题/摘要/关键词题/关键词/两节题/3 para/footnote/caption/参考题
    kinds = {c.kind for c in chunks}
    assert kinds == {"para", "caption", "section_title", "abstract"}
    assert by_id["abs1.1"].kind == "abstract"
    assert by_id["b1"].kind == "caption"  # 文档题 context title → caption
    assert by_id["fn1"].kind == "para"  # footnote → para
    cap = next(c for c in chunks if "A caption" in c.content)
    assert cap.kind == "caption"
    # support 不产块
    assert "bib.b1" not in by_id
    assert "S2.F1" not in by_id
    assert "S2.L1" not in by_id
    # ph_fragments 武装
    assert by_id["abs1.1"].ph_fragments
    tok = next(iter(by_id["abs1.1"].ph_fragments))
    assert 'alttext="x^2"' in by_id["abs1.1"].ph_fragments[tok]


def test_doc_chunks_id_prefix() -> None:
    chunks = doc_chunks(_doc(), id_prefix="html:")
    assert all(c.chunk_id.startswith("html:") for c in chunks)


def test_title_field() -> None:
    assert _doc().title == "Test Paper Title"


def test_keywords_block() -> None:
    doc = _doc()
    kw = next(b for b in doc.blocks if b.context == "keywords")
    assert kw.text == "Foo, Bar"


def test_item_para_text() -> None:
    doc = _doc()
    item = _block(doc, "S1.i1.p1")
    assert item.text == "Item text one."
    # 宿主 para 不吞 item 文本
    p2 = _block(doc, "S1.p2")
    assert "Item text" not in p2.text


#: pre-2000 样本——hep-ph/9703228 真实形态：标题是 ltx_titlepage 内
#: font-size:120% 加粗 span（无 ltx_title*），同 p 内还有 ltx_ERROR 兄弟。
TITLEPAGE_FIXTURE = """<!DOCTYPE html><html><body>
<article class="ltx_document">
<div id="id1" class="ltx_titlepage">
<p id="id1.1" class="ltx_p ltx_align_right">CERN-TH/96-339</p>
<p id="id1.2" class="ltx_p"><span id="id1.2.1" class="ltx_ERROR undefined">{centering}</span><span id="id1.2.2" class="ltx_text ltx_font_bold" style="font-size:120%;">Old Style Title
<br class="ltx_break"/>With <math class="ltx_Math" alttext="Q^2" display="inline"><semantics><msup><mi>Q</mi><mn>2</mn></msup><annotation encoding="application/x-tex">Q^2</annotation></semantics></math> Math</span></p>
<p id="id1.3" class="ltx_p"><span class="ltx_text ltx_font_bold">D. Author</span></p>
</div>
<div id="p1" class="ltx_para"><p id="p1.1" class="ltx_p">Body text.</p></div>
</article>
</body></html>"""

#: hep-ph/9910555 真实形态：标题 span（font-size:144%）与作者裸文本同处
#: 一个 p.ltx_p，整个裹在 ltx_logical-block > ltx_para 里。
LOGBLOCK_FIXTURE = """<!DOCTYPE html><html><body>
<article class="ltx_document">
<div id="id1" class="ltx_logical-block">
<div id="p1" class="ltx_para">
<p id="p1.1" class="ltx_p ltx_align_center"><span id="p1.1.1" class="ltx_text ltx_font_bold" style="font-size:144%;">ALL CAPS OLD TITLE
<br class="ltx_break"/></span>
A. AUTHOR, B. AUTHOR</p>
<p id="p1.2" class="ltx_p ltx_align_center"><span class="ltx_text ltx_font_italic">Some Institute</span></p>
</div>
</div>
<div id="p2" class="ltx_para"><p id="p2.1" class="ltx_p">Body text.</p></div>
</article>
</body></html>"""


def test_fallback_title_titlepage() -> None:
    """ltx_titlepage 内 font-size>100% span → title 块 + doc.title，宿主 p 不双计。"""
    doc = parse_arxiv_html(TITLEPAGE_FIXTURE, arxiv_id="hep-ph/9703228")
    title = next(b for b in doc.blocks if b.context == "title")
    assert title.key == "id1.2.2"
    assert title.text == "Old Style Title With [[MATH_2]] Math"
    assert doc.title == "Old Style Title With Q 2 Q^2 Math"
    # 宿主 p 只留 {centering} CMD token——标题文本不双计
    host = _block(doc, "id1.2")
    assert host.text == "[[CMD_1]]"
    # titlepage 其余 p 仍按 para 产出
    keys = [b.key for b in doc.blocks]
    assert keys.index("id1.2.2") == keys.index("id1.2") + 1


def test_fallback_title_logical_block() -> None:
    """ltx_logical-block 内标题 span → title 块；同 p 作者裸文本留宿主 para。"""
    doc = parse_arxiv_html(LOGBLOCK_FIXTURE, arxiv_id="hep-ph/9910555")
    title = next(b for b in doc.blocks if b.context == "title")
    assert title.key == "p1.1.1"
    assert title.text == "ALL CAPS OLD TITLE"
    assert doc.title == "ALL CAPS OLD TITLE"
    host = _block(doc, "p1")
    assert "ALL CAPS" not in host.text
    assert "A. AUTHOR, B. AUTHOR" in host.text


def test_fallback_title_gated_by_titledoc() -> None:
    """有 h1.ltx_title_document 时兜底不点火（1706.02737 形态防回归）。"""
    doc = _doc()  # FIXTURE 无 ltx_titlepage/logical-block
    assert [b.context for b in doc.blocks].count("title") == 1
    # titledoc + 容器共存：兜底关闭，唯一 title 块仍属 h1
    html = FIXTURE.replace(
        '<article class="ltx_document">',
        '<article class="ltx_document"><div class="ltx_logical-block">'
        '<div class="ltx_para"><p class="ltx_p">'
        '<span style="font-size:144%;">DECOY</span></p></div></div>',
    )
    doc2 = parse_arxiv_html(html)
    titles = [b for b in doc2.blocks if b.context == "title"]
    assert len(titles) == 1
    assert titles[0].text == "Test Paper Title"
    assert doc2.title == "Test Paper Title"


def test_fallback_title_marked_anchors() -> None:
    """兜底 title 块锚注在 span 本体，[data-chunk] 序 == blocks key 序。"""
    doc = parse_arxiv_html(TITLEPAGE_FIXTURE)
    soup = BeautifulSoup(marked_html(TITLEPAGE_FIXTURE), "lxml")
    marked = [str(e["data-chunk"]) for e in soup.select("[data-chunk]")]
    assert marked == [b.key for b in doc.blocks]
    el = soup.find(attrs={"data-chunk": "id1.2.2"})
    assert el is not None
    assert el.name == "span"
    assert "ltx_font_bold" in (el.get("class") or [])


# ---------------------------------------------------------------- fetch_html


def test_fetch_ok_versioned() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, text=FIXTURE)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    out = fetch_html("2501.12948v2", fetcher=f)
    assert "ltx_document" in out
    assert "/html/2501.12948v2" in seen[0]


def test_fetch_404() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="withdrawn")

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    with pytest.raises(HtmlNotAvailableError) as ei:
        fetch_html("cond-mat/0501286", fetcher=f)
    assert ei.value.status == HTTPStatus.NOT_FOUND


def test_fetch_stub_200() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<html><body>no html for this paper</body></html>"
        )

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    with pytest.raises(HtmlNotAvailableError) as ei:
        fetch_html("1501.00001", fetcher=f)
    assert ei.value.status == HTTPStatus.OK


def test_fetch_other_status() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    with pytest.raises(HtmlFetchError) as ei:
        fetch_html("1501.00001", fetcher=f)
    assert ei.value.status == HTTPStatus.FORBIDDEN


def test_fetch_transport_retry() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            msg = "boom"
            raise httpx.ConnectError(msg, request=req)
        return httpx.Response(200, text=FIXTURE)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    assert "ltx_document" in fetch_html("1501.00001", fetcher=f)
    assert calls["n"] == 2  # noqa: PLR2004 -- 重试 1 次后成功，断言即调用计数


def test_fetch_bad_id() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    with pytest.raises(ValueError, match="bad arxiv id"):
        fetch_html("../etc/passwd", fetcher=f)


def test_fetch_parse_integration() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=FIXTURE)

    f = mk_fetcher(httpx.MockTransport(handler), FakeClock())
    doc = parse_arxiv_html(fetch_html("1501.00001", fetcher=f))
    chunks = doc_chunks(doc)
    assert len(chunks) >= MIN_CHUNKS
    assert any(c.kind == "abstract" for c in chunks)


# ---------------------------------------------------------------- marked_html


def test_marked_html_anchors_1to1() -> None:
    """``[data-chunk]`` 序与 ``doc.blocks`` key 序严格同源（emit 锚契约）。"""
    doc = _doc()
    soup = BeautifulSoup(marked_html(FIXTURE), "lxml")
    els = soup.select("[data-chunk]")
    assert [str(e["data-chunk"]) for e in els] == [b.key for b in doc.blocks]
    # 锚注在块元素本体上（S1.p1 是 ltx_para div，footnote 锚在 note span）
    el = soup.find(attrs={"data-chunk": "S1.p1"})
    assert el is not None
    assert "ltx_para" in (el.get("class") or [])
    fn = soup.find(attrs={"data-chunk": "fn1"})
    assert fn is not None
    assert "ltx_note" in (fn.get("class") or [])
    # support 块（bibitem/figure）同样带锚——DomPane 几何序含它们
    assert soup.find(attrs={"data-chunk": "bib.b1"}) is not None
    assert soup.find(attrs={"data-chunk": "S2.F1"}) is not None


def test_marked_html_no_article() -> None:
    with pytest.raises(HtmlNotAvailableError):
        marked_html("<html><body><p>stub</p></body></html>")


def test_parse_arxiv_html_unchanged_after_extract() -> None:
    """_enumerate_blocks 抽取回归哨：钉住块 (key, context) 序位与 footnote 相邻。"""
    doc = _doc()
    got = [(b.key, b.context) for b in doc.blocks]
    # 关键序位抽查（FIXTURE 改动时同步更新——锁的是枚举语义不是样本）
    assert got[0] == ("b1", "title")
    assert got[1] == ("b2", "authors")
    keys = [g[0] for g in got]
    assert keys.index("fn1") == keys.index("S1.p2") + 1  # footnote 紧跟宿主
