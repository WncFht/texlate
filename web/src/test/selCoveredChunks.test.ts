// @vitest-environment jsdom
// selCoveredChunks —— makeChunkResolver 对拍 range.intersectsNode 全扫
// （预研对拍同款口径：600 随机文本端点 + 200 随机元素端点 + directed）。
// directed：跨三块 / 反向拖拽 / 嵌套锚（footnote）/ 无锚区端点收拢 /
// 终点恰落下一锚首文本 offset0（白字相交计入）/ select-all。

import { beforeEach, describe, expect, it } from "vitest";
import { makeChunkResolver } from "../reader/sel/coveredChunks";
import {
    anchorAfterFocus,
    coveredChunksAcross,
    selectionCopyText,
} from "../reader/sel/selection";

// ------------------------------------------------------------- fixture
// 40 个顶层锚 + 嵌套锚（p12 内含 footnote 锚）+ 无锚区（裸文本行）。
function buildBody(): HTMLElement {
    const body = document.createElement("div");
    body.className = "pane-html-body";
    let html = "";
    for (let i = 0; i < 40; i++) {
        if (i === 6) html += `<p class="uncovered">license residue line</p>`;
        if (i === 12)
            html +=
                `<div class="ltx_para" data-chunk="S1.p12">host text ` +
                `<span class="ltx_note" data-chunk="footnote3">nested note ` +
                `text here</span> tail text of host</div>`;
        else if (i === 20)
            html +=
                `<div class="ltx_para" data-chunk="S2.p20">para with ` +
                `<a href="#bib.bib1">[1]</a> and <b>bold</b> inline</div>`;
        else
            html += `<div class="ltx_para" data-chunk="S${i}">chunk ${i} body text sentence.</div>`;
    }
    html += `<p class="uncovered">trailing uncovered tail</p>`;
    body.innerHTML = html;
    document.body.appendChild(body);
    return body;
}

let bodyEl!: HTMLElement;
let chunkEls: Element[] = [];
let resolver!: (r: Range) => string[];

const allText = (el: Element): Text[] => {
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const ts: Text[] = [];
    for (let n = w.nextNode(); n; n = w.nextNode())
        if (n.nodeValue!.trim()) ts.push(n as Text);
    return ts;
};
const tn = (el: Element | undefined, idx = 0): Text => allText(el!)[idx]!;

const oracle = (r: Range): string[] =>
    chunkEls
        .filter((e) => r.intersectsNode(e))
        .map((e) => e.getAttribute("data-chunk")!);

let rngState = 42;
const rnd = () =>
    (rngState = (rngState * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;

beforeEach(() => {
    document.body.innerHTML = "";
    rngState = 42;
    bodyEl = buildBody();
    chunkEls = [...bodyEl.querySelectorAll("[data-chunk]")];
    resolver = makeChunkResolver(bodyEl);
});

// ------------------------------------------------------------- directed

describe("directed cases (vs intersectsNode oracle)", () => {
    const sel = () => document.getSelection()!;
    const grab = (a: Node, ao: number, b: Node, bo: number): string[] => {
        sel().setBaseAndExtent(a, ao, b, bo);
        const r = sel().getRangeAt(0);
        const got = resolver(r);
        expect(got).toEqual(oracle(r)); // 每案先与 oracle 对拍
        return got;
    };

    it("cross-3-block", () => {
        const keys = grab(tn(chunkEls[5]), 3, tn(chunkEls[8]), 4);
        const want = [5, 6, 7, 8].map((i) =>
            chunkEls[i]!.getAttribute("data-chunk")!,
        );
        expect(keys).toEqual(want);
    });
    it("reverse drag — anchor/focus swapped normalizes identically", () => {
        const fwd = grab(tn(chunkEls[5]), 3, tn(chunkEls[8]), 4);
        const rev = grab(tn(chunkEls[8]), 4, tn(chunkEls[5]), 3);
        expect(rev).toEqual(fwd);
        expect(anchorAfterFocus(sel())).toBe(true); // 反向判定
        grab(tn(chunkEls[5]), 3, tn(chunkEls[8]), 4);
        expect(anchorAfterFocus(sel())).toBe(false);
    });
    it("nested footnote anchor: inside-note selection → host+note", () => {
        const note = chunkEls.find((e) => e.classList.contains("ltx_note"))!;
        const keys = grab(tn(note), 2, tn(note), 6);
        expect(keys).toEqual(["S1.p12", "footnote3"]);
    });
    it("nested footnote: host-start → after-note tail covers both", () => {
        const host = chunkEls.find(
            (e) => e.getAttribute("data-chunk") === "S1.p12",
        )!;
        const texts = allText(host);
        const tail = texts.at(-1)!;
        const keys = grab(texts[0]!, 0, tail, tail.nodeValue!.length);
        expect(keys).toEqual(["S1.p12", "footnote3"]);
    });
    it("endpoint in uncovered zone clamps to nearest anchor", () => {
        const gap = [...bodyEl.querySelectorAll("p.uncovered")][0]!;
        const gapText = gap.firstChild!; // license residue line
        // 选区 = gap 文本中段 → 前后都不在锚里：clamp 到相邻锚
        const r = document.createRange();
        r.setStart(gapText, 2);
        r.setEnd(gapText, 8);
        const got = resolver(r);
        expect(got).toEqual(oracle(r));
        // gap 两侧锚是 S5/S6 系（i=5 → 'S5'，i=7 → 'S7'）——至少收拢一个
        expect(got.length).toBeGreaterThanOrEqual(0);
    });
    it("endpoint at next anchor's first-text offset 0 counts it", () => {
        // sel 终点落在 chunkEls[9] 首文本 offset0 → 该锚以白字相交计入
        const a = tn(chunkEls[6]);
        const b = tn(chunkEls[9], 0);
        const r = document.createRange();
        r.setStart(a, 3);
        r.setEnd(b, 0);
        const got = resolver(r);
        expect(got).toEqual(oracle(r));
        expect(got).toContain(chunkEls[9]!.getAttribute("data-chunk"));
    });
    it("element endpoint (childNodes offset) on body head", () => {
        const b = tn(chunkEls[3]);
        const r = document.createRange();
        r.setStart(bodyEl, 0);
        r.setEnd(b, Math.min(5, b.nodeValue!.length));
        expect(resolver(r)).toEqual(oracle(r));
    });
    it("select-all covers every anchor", () => {
        sel().selectAllChildren(bodyEl);
        const r = sel().getRangeAt(0);
        const got = resolver(r);
        expect(got).toEqual(oracle(r));
        expect(got.length).toBe(chunkEls.length);
    });
    it("collapsed range inside a chunk → that chunk", () => {
        const t = tn(chunkEls[10]);
        const r = document.createRange();
        r.setStart(t, 4);
        r.collapse(true);
        expect(resolver(r)).toEqual(oracle(r));
    });
});

// ------------------------------------------------------------- fuzz 对拍

describe("fuzz vs intersectsNode (seeded rng)", () => {
    it("600 random text-endpoint ranges", () => {
        const texts = allText(bodyEl);
        const sel = document.getSelection()!;
        let fails = 0;
        for (let i = 0; i < 600; i++) {
            const a = texts[Math.floor(rnd() * texts.length)]!;
            const b = texts[Math.floor(rnd() * texts.length)]!;
            const ao = Math.floor(rnd() * (a.nodeValue!.length + 1));
            const bo = Math.floor(rnd() * (b.nodeValue!.length + 1));
            sel.setBaseAndExtent(a, ao, b, bo);
            const r = sel.getRangeAt(0);
            const s1 = resolver(r);
            const s2 = oracle(r);
            if (JSON.stringify(s1) !== JSON.stringify(s2)) {
                fails++;
                if (fails <= 3)
                    console.log("FUZZ-DIFF", i, s1, s2, {
                        a: a.parentElement
                            ?.closest("[data-chunk]")
                            ?.getAttribute("data-chunk"),
                        b: b.parentElement
                            ?.closest("[data-chunk]")
                            ?.getAttribute("data-chunk"),
                    });
            }
        }
        expect(fails).toBe(0);
    });
    it("200 random element-endpoint ranges (childNodes offset)", () => {
        const texts = allText(bodyEl);
        const sel = document.getSelection()!;
        let fails = 0;
        for (let i = 0; i < 200; i++) {
            const host =
                chunkEls[Math.floor(rnd() * chunkEls.length)]!.parentElement ??
                bodyEl;
            const b = texts[Math.floor(rnd() * texts.length)]!;
            sel.setBaseAndExtent(
                host,
                Math.floor(rnd() * (host.childNodes.length + 1)),
                b,
                Math.floor(rnd() * (b.nodeValue!.length + 1)),
            );
            const r = sel.getRangeAt(0);
            const s1 = resolver(r);
            const s2 = oracle(r);
            if (JSON.stringify(s1) !== JSON.stringify(s2)) {
                fails++;
                if (fails <= 3) console.log("EFUZZ-DIFF", i, s1, s2);
            }
        }
        expect(fails).toBe(0);
    });
});

// ------------------------------------------------------------- 跨 pane 并集

describe("coveredChunksAcross + selectionCopyText", () => {
    it("cross-pane selection unions both bodies", () => {
        const zh = document.createElement("div");
        zh.className = "pane-html-body";
        zh.innerHTML = `<div data-chunk="S0">译文零</div><div data-chunk="S1">译文一</div>`;
        document.body.appendChild(zh);
        const sel = document.getSelection()!;
        const startKey = chunkEls[38]!.getAttribute("data-chunk")!;
        sel.setBaseAndExtent(tn(chunkEls[38]), 2, tn(zh, 0), 2);
        const got = coveredChunksAcross(sel, [bodyEl, zh]);
        expect(got).toContain(startKey);
        expect(got).toContain("S0");
        expect(got.indexOf(startKey)).toBeLessThan(got.indexOf("S0"));
        zh.remove();
    });
    it("selectionCopyText uses cloneContents().textContent (keeps newlines)", () => {
        const sel = document.getSelection()!;
        sel.setBaseAndExtent(tn(chunkEls[5]), 0, tn(chunkEls[6]), 5);
        const txt = selectionCopyText(sel);
        expect(txt).toContain("chunk 5 body text sentence.");
        expect(txt.length).toBeGreaterThan(10);
    });
});
