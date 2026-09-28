// @vitest-environment jsdom
// pdfmarks —— zh.pdf seq 锚消费面单测。
//   seqOfMarkedSpan/seqOfTextItem：id 尾 _mc<N>（N≥50000）解码 + tag 校验；
//   MARKED_SPEC + makeChunkResolver：textLayer 选区 → 数值 seq 串（文档序）。
// fixture：span.markedContent 锚与裸文本/文档自有锚（mc<50000）混合——
// 自有锚参与端点收拢但不产 key（keyOf null 跳过）。

import { beforeEach, describe, expect, it } from "vitest";
import {
    MARKED_SPEC,
    MARKED_SEL,
    MCID_BASE,
    seqOfMarkedSpan,
    seqOfTextItem,
} from "../reader/pdf/pdfmarks";
import { makeChunkResolver } from "../reader/sel/coveredChunks";

// ------------------------------------------------------------- 解码面

describe("seqOfMarkedSpan / seqOfTextItem", () => {
    const span = (id: string | null): Element => {
        const el = document.createElement("span");
        el.className = "markedContent";
        if (id != null) el.id = id;
        return el;
    };

    it("id 尾 _mc<N> 且 N≥50000 → N-50000", () => {
        expect(seqOfMarkedSpan(span(`p0_mc${MCID_BASE + 42}`))).toBe(42);
        expect(seqOfMarkedSpan(span(`p3_mc${MCID_BASE}`))).toBe(0);
        expect(seqOfMarkedSpan(span(`x_mc${MCID_BASE + 7}`))).toBe(7);
    });
    it("非锚 id / 低 MCID / 缺 id → null", () => {
        expect(seqOfMarkedSpan(span(`p0_mc${MCID_BASE - 1}`))).toBeNull();
        expect(seqOfMarkedSpan(span("p0_mc123"))).toBeNull();
        expect(seqOfMarkedSpan(span("page_42"))).toBeNull();
        expect(seqOfMarkedSpan(span(null))).toBeNull();
        expect(seqOfMarkedSpan(null)).toBeNull();
    });
    it("item 层：id 解码 + TLXC tag 校验（无 tag 放行，异 tag 拒）", () => {
        const id = `p0_mc${MCID_BASE + 9}`;
        expect(seqOfTextItem({ id, tag: "TLXC0" })).toBe(9);
        expect(seqOfTextItem({ id, tag: "TLXC" })).toBe(9);
        expect(seqOfTextItem({ id })).toBe(9); // 无 tag 字段放行
        expect(seqOfTextItem({ id, tag: "Span" })).toBeNull();
        expect(seqOfTextItem({ id: "p0_mc123", tag: "TLXC1" })).toBeNull();
        expect(seqOfTextItem({ tag: "TLXC0" })).toBeNull();
        expect(seqOfTextItem(null)).toBeNull();
        expect(seqOfTextItem("p0_mc50009")).toBeNull();
    });
});

// ------------------------------------------------------------- resolver 面

function buildTextLayer(): HTMLElement {
    const body = document.createElement("div");
    body.className = "textLayer";
    // 混合锚序：TLXC 锚(seq 7) → 裸文本 → 文档自有锚(mc 12，无 seq)
    // → TLXC 锚(seq 9 跨两枚 span，模拟 pdf.js 切片) → TLXC 锚(seq 42)
    body.innerHTML =
        `<span class="markedContent" id="p0_mc${MCID_BASE + 7}">alpha beta ` +
        `gamma</span> loose words ` +
        `<span class="markedContent" id="p0_mc12">document own tag</span> ` +
        `<span class="markedContent" id="p1_mc${MCID_BASE + 9}">delta eps</span>` +
        `<span class="markedContent" id="p1_mc${MCID_BASE + 9}"> zeta eta</span> ` +
        `tail <span class="markedContent" id="p2_mc${MCID_BASE + 42}">theta` +
        `</span>`;
    document.body.appendChild(body);
    return body;
}

const allText = (el: Element): Text[] => {
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const ts: Text[] = [];
    for (let n = w.nextNode(); n; n = w.nextNode())
        if (n.nodeValue!.trim()) ts.push(n as Text);
    return ts;
};

let layer!: HTMLElement;
let resolver!: (r: Range) => string[];

beforeEach(() => {
    document.body.innerHTML = "";
    layer = buildTextLayer();
    resolver = makeChunkResolver(layer, undefined, MARKED_SPEC);
});

describe("MARKED_SPEC resolver (textLayer → seq keys)", () => {
    const sel = () => document.getSelection()!;

    it("选区跨三锚 → 数值 seq 串按文档序（同 seq 两枚各计）", () => {
        const ts = allText(layer);
        // "beta" (seq7 内) → "eta" (seq9 第二枚内)——途经 seq9 双 span
        sel().setBaseAndExtent(ts[0]!, 6, ts[4]!, 7);
        expect(resolver(sel().getRangeAt(0))).toEqual(["7", "9", "9"]);
    });
    it("同 seq 跨页续段两枚 span 各产一次 key（去重归调用方）", () => {
        const ts = allText(layer);
        // "delta" → "zeta"——两枚都是 mc50009
        sel().setBaseAndExtent(ts[3]!, 0, ts[4]!, 4);
        expect(resolver(sel().getRangeAt(0))).toEqual(["9", "9"]);
    });
    it("文档自有锚（mc<50000）收拢但不产 key", () => {
        const ts = allText(layer);
        // 选区恰在自有锚内部 → 收拢两侧 TLXC 锚还是空集均诚实；
        // 自有锚在端点间时只作边界不计 key
        sel().setBaseAndExtent(ts[2]!, 3, ts[2]!, 10);
        const got = resolver(sel().getRangeAt(0));
        expect(got).not.toContain("12");
        for (const k of got) expect(Number(k)).toBeGreaterThanOrEqual(0);
    });
    it("选区从自有锚跨到 seq42 → 自有锚无 key", () => {
        const ts = allText(layer);
        sel().setBaseAndExtent(
            ts[2]!,
            3,
            ts[ts.length - 1]!,
            ts[ts.length - 1]!.nodeValue!.length,
        );
        // 自有锚收拢进区间但 keyOf null 跳过——key 只出 TLXC seq
        expect(resolver(sel().getRangeAt(0))).toEqual(["9", "9", "42"]);
    });
    it("全选 → 全部 TLXC seq（重复 seq 各计）", () => {
        sel().selectAllChildren(layer);
        expect(resolver(sel().getRangeAt(0))).toEqual(["7", "9", "9", "42"]);
    });
    it("MARKED_SEL 命中全部 markedContent 锚（含自有）", () => {
        expect(layer.querySelectorAll(MARKED_SEL).length).toBe(5);
    });
});
