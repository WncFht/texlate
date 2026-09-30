"""arxiv 测试公共件——HTML fixture 语料。

``test_arxiv_html``（解析/锚注/chunk 化）与 ``test_server_arxiv_html``
（服务端 HTML 面板）共用的手工小样本归此一处（``_*kit`` 抽取惯例）。
"""

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
