// @vitest-environment jsdom
// selHitctx —— snapshotHit 命中语境快照（DomPane 真标记夹具）。
// 断言面：cite 锚分类（bibitem/figure/equation/section + dest 名兜底）、
// cite-ref data-key、math alttext/annotation、chunk_id→seq 映射、
// pending 闸、counterpartAvail、zh badge、caps 缺省、flattenCtx 谓词键。

import { beforeEach, describe, expect, it } from "vitest";
import {
    classifyDestName,
    classifyLtxEl,
    flattenCtx,
    snapshotHit,
    CTX_KEYS,
} from "../reader/cmd/hitctx";

const FIXTURE = `
<div id="paneEn" class="pane pane-dom" tabindex="0" data-side="original">
  <div class="pane-html-body" id="bodyEn">
    <div class="ltx_para" data-chunk="S1.p1">Intro text
      <span class="ltx_cite">(<a class="ltx_ref" href="#bib.bib13">13</a>)</span>
      tail.</div>
    <div class="ltx_para" data-chunk="S1.p2">See
      <a class="ltx_ref" href="#S2.fig1" id="figRef">Fig. 1</a> and
      <a class="cite-ref" data-key="k7,k9" id="cref">[7,9]</a>.</div>
    <figure class="ltx_figure" id="S2.fig1" data-chunk="S2.fig1">
      <figcaption>Cap text</figcaption></figure>
    <div class="ltx_para" data-chunk="S1.p3">Formula
      <math class="ltx_Math" alttext="h_{t}" id="m1"><semantics>
        <annotation encoding="application/x-tex">h_{t}</annotation>
      </semantics></math> inline.</div>
    <section class="ltx_section" id="S2" data-chunk="S2">
      <a class="ltx_ref" href="#S2" id="secRef">§2</a> body</section>
    <ol class="ltx_bibliography"><li class="ltx_bibitem" id="bib.bib13"
      data-chunk="bib.bib13">Smith et al. arXiv:2105.12345
      doi:10.1234/foo.bar</li></ol>
  </div>
</div>
<div id="paneZh" class="pane pane-dom" tabindex="0" data-side="translated">
  <div class="pane-html-body" id="bodyZh">
    <div class="ltx_para" data-chunk="S1.p1">译<span class="chunk-badge">未译</span>文</div>
  </div>
</div>`;

const q = <T extends Element = Element>(sel: string): T =>
    document.querySelector<T>(sel)!;

beforeEach(() => {
    document.body.innerHTML = FIXTURE;
});

describe("classify vocab", () => {
    it("classifyLtxEl: host element classes", () => {
        const mk = (cls: string) => {
            const el = document.createElement("div");
            el.className = cls;
            return el;
        };
        expect(classifyLtxEl(mk("ltx_bibitem"))).toBe("bib");
        expect(classifyLtxEl(mk("ltx_figure ltx_flex"))).toBe("figure");
        expect(classifyLtxEl(mk("ltx_table"))).toBe("table");
        expect(classifyLtxEl(mk("ltx_equation"))).toBe("equation");
        expect(classifyLtxEl(mk("ltx_theorem ltx_theorem_lemma"))).toBe(
            "theorem",
        );
        expect(classifyLtxEl(mk("ltx_section"))).toBe("section");
        expect(classifyLtxEl(mk("ltx_para"))).toBe("other");
        expect(classifyLtxEl(null)).toBe("other");
    });
    it("classifyLtxEl: inner caption climbs to nearest ltx_ ancestor", () => {
        const fig = document.querySelector('[id="S2.fig1"]')!;
        const cap = fig.querySelector("figcaption")!;
        cap.className = "ltx_caption";
        expect(classifyLtxEl(cap)).toBe("figure");
    });
    it("classifyDestName: dest/id prefix vocab", () => {
        expect(classifyDestName("bib.bib13")).toBe("bib");
        expect(classifyDestName("cite.foo")).toBe("bib");
        expect(classifyDestName("equation.3")).toBe("equation");
        expect(classifyDestName("S3.E2")).toBe("equation");
        expect(classifyDestName("figure.1")).toBe("figure");
        expect(classifyDestName("S1.F2")).toBe("figure");
        expect(classifyDestName("table.4")).toBe("table");
        expect(classifyDestName("theorem.2")).toBe("theorem");
        expect(classifyDestName("section.intro")).toBe("section");
        expect(classifyDestName("S2")).toBe("section");
        expect(classifyDestName("S2.SS1")).toBe("section");
        expect(classifyDestName("something-else")).toBe("other");
    });
});

describe("snapshotHit: cite lane", () => {
    it("bib anchor → bib kind, resolved target, entryText, ids", () => {
        const hit = snapshotHit(q("#paneEn a.ltx_ref"), null);
        expect(hit.view).toBe("dom");
        expect(hit.paneSide).toBe("en");
        expect(hit.cite.targetKind).toBe("bib");
        expect(hit.cite.bibkey).toBe("bib.bib13");
        expect(hit.cite.targetExists).toBe(true);
        expect(hit.cite.targetEl?.classList.contains("ltx_bibitem")).toBe(
            true,
        );
        expect(hit.cite.entryText).toContain("Smith et al.");
        expect(hit.cite.cardFillable).toBe(true);
        expect(hit.cite.arxivId).toBe("2105.12345");
        expect(hit.cite.doi).toBe("10.1234/foo.bar");
        // 谓词面
        const flat = flattenCtx(hit);
        expect(flat["cite.targetKind"]).toBe("bib");
        expect(flat["cite.targetExists"]).toBe(true);
        expect(flat["cite.cardFillable"]).toBe(true);
        expect(flat["cite.arxivId"]).toBe("2105.12345");
    });
    it("figure anchor → figure kind via target ltx_figure", () => {
        const hit = snapshotHit(q("#figRef"), null);
        expect(hit.cite.targetKind).toBe("figure");
        expect(hit.cite.targetExists).toBe(true);
        expect(hit.cite.cardFillable).toBe(false);
    });
    it("section self-ref → section kind", () => {
        const hit = snapshotHit(q("#secRef"), null);
        expect(hit.cite.targetKind).toBe("section");
    });
    it("cite-ref data-key → first key wins", () => {
        const hit = snapshotHit(q("#cref"), null);
        expect(hit.cite.bibkey).toBe("k7");
        expect(hit.cite.anchorEl?.classList.contains("cite-ref")).toBe(true);
        // 无 #k7 元素 → dest 名兜底分类（k7 不识别 → other）
        expect(hit.cite.targetKind).toBe("other");
        expect(hit.cite.targetExists).toBe(false);
    });
    it("pdf linkAnnotation 裸锚 → figure kind，dests 证明存在", () => {
        // pdf 批注层锚无类无文本——唯一入口是裸 a[href^='#'] + dests 集
        const pane = document.createElement("div");
        pane.className = "pane pane-pdf";
        pane.setAttribute("data-side", "original");
        pane.innerHTML =
            `<div class="pane-body"><section class="linkAnnotation">` +
            `<a href="#figure.caption.3"></a>` +
            `<a href="#page.5"></a></section></div>`;
        document.body.appendChild(pane);
        const [figA, pageA] = [...pane.querySelectorAll("a")];
        const hit = snapshotHit(figA, null, {
            dests: new Set(["figure.caption.3", "page.5"]),
        });
        expect(hit.view).toBe("pdf");
        expect(hit.cite.targetId).toBe("figure.caption.3");
        expect(hit.cite.targetKind).toBe("figure");
        expect(hit.cite.targetExists).toBe(true);
        expect(hit.cite.anchorEl).toBe(figA);
        // page.N/Doc-Start 归 other——cite.usages 谓词（!=other）不收
        const ph = snapshotHit(pageA, null, { dests: new Set(["page.5"]) });
        expect(ph.cite.targetKind).toBe("other");
        expect(ph.cite.targetExists).toBe(true);
    });
    it("unresolvable id + deps.dests hit → targetExists via pdf dests", () => {
        // 造一个 DOM 里不存在的 dest 锚
        const a = document.createElement("a");
        a.className = "ltx_ref";
        a.setAttribute("href", "#equation.3");
        a.textContent = "(3)";
        q("[data-chunk='S1.p2']").appendChild(a);
        const hit = snapshotHit(a, null, {
            dests: new Set(["equation.3"]),
        });
        expect(hit.cite.targetExists).toBe(true);
        expect(hit.cite.targetEl).toBeNull();
        expect(hit.cite.targetKind).toBe("equation");
    });
    it("citeIndex fallback supplies entryText + ids", () => {
        const a = document.createElement("a");
        a.className = "cite-ref";
        a.setAttribute("data-key", "ghostkey");
        q("[data-chunk='S1.p2']").appendChild(a);
        const hit = snapshotHit(a, null, {
            citeIndex: {
                lookup: (k) =>
                    k === "ghostkey"
                        ? { text: "Ghost Entry", arxivId: "2401.00001" }
                        : undefined,
            },
        });
        expect(hit.cite.entryText).toBe("Ghost Entry");
        expect(hit.cite.arxivId).toBe("2401.00001");
    });
});

describe("snapshotHit: math/chunk/caps lanes", () => {
    it("math target → tex + mathml payload", () => {
        const hit = snapshotHit(q("#m1"), null);
        expect(hit.math.tex).toBe("h_{t}");
        expect(hit.math.mathml).toContain("<math");
        expect(flattenCtx(hit)["math.tex"]).toBe("h_{t}");
    });
    it("chunk lane: dom key → intSeq via seqOf Map; pending flag", () => {
        const p2 = q("[data-chunk='S1.p2']");
        const hit = snapshotHit(p2, null, {
            seqOf: new Map([["S1.p2", 12]]),
            pending: new Set([12]),
        });
        expect(hit.chunk.key).toBe("S1.p2");
        expect(hit.chunk.intSeq).toBe(12);
        expect(hit.chunk.pending).toBe(true);
        expect(hit.chunk.hasPh).toBe(false);
        const flat = flattenCtx(hit);
        expect(flat["chunk.intSeq"]).toBe(true); // 布尔化——seq=0 免疫
        expect(flat["chunk.seq"]).toBe("S1.p2");
    });
    it("chunk lane: html-side numeric key resolves intSeq directly", () => {
        const div = document.createElement("div");
        div.setAttribute("data-chunk", "7");
        div.textContent = "x";
        q("#bodyEn").appendChild(div);
        const hit = snapshotHit(div, null);
        expect(hit.chunk.intSeq).toBe(7);
    });
    it("chunk lane: unmapped key → intSeq null (bibitem 类无行锚)", () => {
        const hit = snapshotHit(q('[id="bib.bib13"]'), null, {
            seqOf: new Map(),
        });
        expect(hit.chunk.intSeq).toBeNull();
        expect(flattenCtx(hit)["chunk.intSeq"]).toBe(false);
    });
    it("zh side: chunk-badge → zhUntranslated; counterpartAvail via chunkText", () => {
        const zhChunk = q("#bodyZh [data-chunk='S1.p1']");
        const hit = snapshotHit(zhChunk, null, {
            chunkText: (k, lang) =>
                k === "S1.p1" && lang === "en" ? "Intro text" : null,
        });
        expect(hit.paneSide).toBe("zh");
        expect(hit.chunk.zhUntranslated).toBe(true);
        expect(hit.chunk.counterpartAvail).toBe(true);
        expect(hit.chunk.hasEn).toBe(true); // 对侧文本解析到
        expect(hit.chunk.hasZh).toBe(true); // 本侧有文本
    });
    it("caps defaults all false; overrides merge", () => {
        const hit = snapshotHit(q("#paneEn"), null);
        expect(hit.caps).toEqual({
            findInPane: false,
            assist: false,
            retx: false,
            discover: false,
            navBack: false,
            navFwd: false,
            linkScheme: false,
        });
        const hit2 = snapshotHit(q("#paneEn"), null, {
            caps: { retx: true, navBack: true },
        });
        expect(hit2.caps.retx).toBe(true);
        expect(hit2.caps.navBack).toBe(true);
        expect(hit2.caps.assist).toBe(false); // assist 只能经 caps 显式翻
    });
});

describe("snapshotHit: sel lane", () => {
    it("live selection → text + covered chunks + inChunk", () => {
        const body = q("#bodyEn");
        const sel = document.getSelection()!;
        const p1 = q("[data-chunk='S1.p1']");
        const p2 = q("[data-chunk='S1.p2']");
        const t1 = p1.firstChild as Text; // "Intro text\n      "
        const t2 = p2.firstChild as Text;
        sel.setBaseAndExtent(t1, 0, t2, 3);
        const hit = snapshotHit(p1, sel, { bodies: [body] });
        expect(hit.sel.text).toContain("Intro text");
        expect(hit.sel.chunks).toEqual(["S1.p1", "S1.p2"]);
        expect(hit.sel.inChunk).toBe(true);
        expect(flattenCtx(hit)["sel.text"]).toBeTruthy();
        expect(flattenCtx(hit)["sel.chunks"]).toBe(true);
    });
    it("select-all on body → all chunks + inChunk (容器端点含锚)", () => {
        const body = q("#bodyEn");
        const sel = document.getSelection()!;
        sel.selectAllChildren(body);
        const hit = snapshotHit(q("#paneEn"), sel, { bodies: [body] });
        expect(hit.sel.chunks.length).toBe(6);
        expect(hit.sel.inChunk).toBe(true);
    });
    it("CTX_KEYS ⊆ flattenCtx output keys (audit 基准自洽)", () => {
        const hit = snapshotHit(null, null, {});
        const produced = new Set(Object.keys(flattenCtx(hit)));
        expect(CTX_KEYS.filter((k) => !produced.has(k))).toEqual([]);
    });
});
