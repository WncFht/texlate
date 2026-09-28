// @vitest-environment jsdom
// selSentseg —— DOM 内句边界哨兵（exp/ss-a11y/sentseg.js 移植对拍）。
// 断言面：missed_cuts=0（句界不遗漏）、chunkIdx 单调、id 带侧名防撞车、
// SKIP_TAGS 整树跳、缩写豁免、空白闸、sentenceRange/Text 复原原句。

import { beforeEach, describe, expect, it } from "vitest";
import {
    segmentBlock,
    segmentDoc,
    sentenceRange,
    sentenceText,
} from "../reader/sel/sentseg";

const pane = (side: string, inner: string): HTMLElement => {
    const p = document.createElement("div");
    p.className = "pane";
    p.dataset.side = side;
    const b = document.createElement("div");
    b.className = "pane-html-body";
    b.innerHTML = inner;
    p.appendChild(b);
    document.body.appendChild(p);
    return b;
};

beforeEach(() => {
    document.body.innerHTML = "";
});

// ------------------------------------------------------------- en 句读

describe("segmentBlock en", () => {
    it("basic stops .!? split sentences", () => {
        const b = pane(
            "original",
            `<div data-chunk="S1">First sentence. Second longer! Third next? Tail end.</div>`,
        );
        const marks = segmentBlock(b.querySelector("[data-chunk]")!, "S1");
        expect(marks).toHaveLength(4);
        const texts = marks.map((_, i) => sentenceText(document, marks, i));
        expect(texts).toEqual([
            "First sentence.",
            "Second longer!",
            "Third next?",
            "Tail end.",
        ]);
    });
    it("abbrev exemption applies to !? too (≤3-letter tail word)", () => {
        // spike 语义：'Second one!' 尾词 'one' ≤3 → 不切（!? 非恒切——
        // 注释写「?.! 恒切」但代码对全部 stop 跑 abbrevCut，忠实移植）
        const b = pane(
            "original",
            `<div data-chunk="S1">First sentence. Second one! Third? Tail end.</div>`,
        );
        const marks = segmentBlock(b.querySelector("[data-chunk]")!, "S1");
        const texts = marks.map((_, i) => sentenceText(document, marks, i));
        expect(texts).toEqual([
            "First sentence.",
            "Second one! Third?",
            "Tail end.",
        ]);
    });
    it("abbreviation exemption: Dr./e.g./al./Fig. don't cut", () => {
        const b = pane(
            "original",
            `<div data-chunk="S1">Dr. Smith et al. wrote this. See Fig. 2 for details. Done now.</div>`,
        );
        const marks = segmentBlock(b.querySelector("[data-chunk]")!, "S1");
        const texts = marks.map((_, i) => sentenceText(document, marks, i));
        expect(texts).toEqual([
            "Dr. Smith et al. wrote this.",
            "See Fig. 2 for details.",
            "Done now.",
        ]);
    });
    it("whitespace gate: 'end.Next' without space does NOT cut", () => {
        const b = pane(
            "original",
            `<div data-chunk="S1">end.Next sentence. After that. Last</div>`,
        );
        const marks = segmentBlock(b.querySelector("[data-chunk]")!, "S1");
        const texts = marks.map((_, i) => sentenceText(document, marks, i));
        expect(texts).toEqual(["end.Next sentence.", "After that.", "Last"]);
    });
    it("markers are zero-width i.sb with tabindex=-1 role=mark side-named id", () => {
        const b = pane("original", `<div data-chunk="S1">First. Second.</div>`);
        const marks = segmentBlock(b.querySelector("[data-chunk]")!, "S1");
        for (const m of marks) {
            expect(m.marker.tagName).toBe("I");
            expect(m.marker.className).toBe("sb");
            expect(m.marker.tabIndex).toBe(-1); // 零新增 tab 停点
            expect(m.marker.getAttribute("role")).toBe("mark");
            expect(m.marker.id).toMatch(/^sb-original-S1-\d+$/);
            expect(m.marker.textContent).toBe("");
        }
        expect(marks.map((m) => m.sid)).toEqual(["S1:0", "S1:1"]);
    });
    it("cross-inline sentence boundary survives (a/b/math inside)", () => {
        const b = pane(
            "original",
            `<div data-chunk="S1">Start <a href="#bib.bib1">[1]</a> middle. ` +
                `Next <b>bold</b> ending.</div>`,
        );
        const marks = segmentBlock(b.querySelector("[data-chunk]")!, "S1");
        expect(marks).toHaveLength(2);
        const t0 = sentenceText(document, marks, 0);
        expect(t0).toBe("Start [1] middle.");
        expect(sentenceText(document, marks, 1)).toBe("Next bold ending.");
    });
    it("SKIP_TAGS: math/script/svg subtrees excluded from stream", () => {
        const b = pane(
            "original",
            `<div data-chunk="S1">Before <math><mi>x</mi><mo>.</mo><mi>y</mi></math> after. ` +
                `Next<script>var fake = "x.y";</script> tail.</div>`,
        );
        const marks = segmentBlock(b.querySelector("[data-chunk]")!, "S1");
        const texts = marks
            .map((_, i) => sentenceText(document, marks, i))
            .map((t) => t.replace(/\s+/g, " ")); // 被挖空的子树留下双空格
        // math/script 文本不进 stream——"x.y" 的假句读不切
        expect(texts).toEqual(["Before after.", "Next tail."]);
    });
});

// ------------------------------------------------------------- zh 句读

describe("segmentBlock zh", () => {
    it("CJK stops 。！？；cut when followed by space/全角空白", () => {
        const b = pane(
            "translated",
            `<div data-chunk="S1">第一句。 第二句！ 第三句？ 还有； 末句</div>`,
        );
        const marks = segmentBlock(
            b.querySelector("[data-chunk]")!,
            "S1",
            "zh",
        );
        const texts = marks.map((_, i) => sentenceText(document, marks, i));
        expect(texts).toEqual([
            "第一句。",
            "第二句！",
            "第三句？",
            "还有；",
            "末句",
        ]);
    });
    it("CJK stop with no trailing space does NOT cut (空白闸 zh 同款)", () => {
        const b = pane(
            "translated",
            `<div data-chunk="S1">第一句。第二句！末句</div>`,
        );
        const marks = segmentBlock(
            b.querySelector("[data-chunk]")!,
            "S1",
            "zh",
        );
        expect(marks).toHaveLength(1);
    });
    it("zh ids carry the pane's data-side (translated)", () => {
        const b = pane(
            "translated",
            `<div data-chunk="S1">第一句。 第二句。</div>`,
        );
        const marks = segmentBlock(
            b.querySelector("[data-chunk]")!,
            "S1",
            "zh",
        );
        expect(marks[0]!.marker.id).toBe("sb-translated-S1-0");
    });
});

// ------------------------------------------------------------- segmentDoc

describe("segmentDoc", () => {
    it("chunkIdx monotone; empty-sentence blocks contribute none", () => {
        const b = pane(
            "original",
            `<div data-chunk="S0">Alpha. Beta.</div>` +
                `<figure data-chunk="F1"><img src="x.png"></figure>` +
                `<div data-chunk="S2">Gamma.</div>`,
        );
        const all = segmentDoc(b, "en");
        expect(all).toHaveLength(3);
        expect(all.map((m) => m.chunkIdx)).toEqual([0, 0, 2]);
        expect(all.map((m) => m.sid)).toEqual(["S0:0", "S0:1", "S2:0"]);
        // chunkIdx 单调非降
        for (let i = 1; i < all.length; i++)
            expect(all[i]!.chunkIdx).toBeGreaterThanOrEqual(
                all[i - 1]!.chunkIdx,
            );
    });
    it("missed_cuts=0: marker stream covers all gated stops", () => {
        // oracle：同规则独立扫一遍文本流应得切点数 == marker 数
        const b = pane(
            "original",
            `<div data-chunk="S1">First long. Second more! Third next? Last end.</div>`,
        );
        const marks = segmentBlock(b.querySelector("[data-chunk]")!, "S1");
        expect(marks).toHaveLength(4);
        // 复原：拼接 sentenceText 应还原全部文本（无句丢失）
        const joined = marks
            .map((_, i) => sentenceText(document, marks, i))
            .join(" ");
        expect(joined).toBe("First long. Second more! Third next? Last end.");
    });
    it("sentenceRange: last sentence ends at chunk tail", () => {
        const b = pane(
            "original",
            `<div data-chunk="S1">Alpha. Beta.</div><div data-chunk="S2">Gam.</div>`,
        );
        const all = segmentDoc(b, "en");
        const r = sentenceRange(document, all, 1);
        expect(r.toString().trim()).toBe("Beta.");
        // 跨块句界：S1 的末句 range 不收 S2 文本
        expect(r.toString()).not.toContain("Gam");
        r.detach();
    });
    it("double-segment side-named ids don't collide across panes", () => {
        const en = pane("original", `<div data-chunk="S1">Alpha. Beta.</div>`);
        const zh = pane("translated", `<div data-chunk="S1">甲。 乙。</div>`);
        segmentDoc(en, "en");
        segmentDoc(zh, "zh");
        const ids = [...document.querySelectorAll("i.sb")].map(
            (m) => (m as HTMLElement).id,
        );
        expect(new Set(ids).size).toBe(ids.length); // 双侧同 seq 不撞 id
        expect(ids.filter((i) => i.startsWith("sb-original-"))).toHaveLength(2);
        expect(ids.filter((i) => i.startsWith("sb-translated-"))).toHaveLength(
            2,
        );
    });
});
