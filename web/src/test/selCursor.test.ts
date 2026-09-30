// @vitest-environment jsdom
// selCursor —— 句游标模态（cursor e2e 剧本的 jsdom 对拍）。
// 14 断言面：v 进入 / j·k 移动 / ]·[ 块跳 / Home·End 端点不环绕 /
// Enter 真 Selection / c 复制 = sentenceRange 文本 / t 对侧同 sid /
// Esc·Tab 退出 / 重入记忆 / 零新增 tab 停点 / 模态按键不透全局。

import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
    type Mock,
} from "vitest";
import { makeCursor, type Cursor } from "../reader/sel/cursor";
import { segmentDoc, sentenceText, type SentMark } from "../reader/sel/sentseg";

const EN_HTML =
    `<div data-chunk="S0">Alpha four. Beta five.</div>` +
    `<figure data-chunk="F0"><img src="x.png"></figure>` + // 空句块——块跳坑位
    `<div data-chunk="S2">Gamma first. Delta other. Epsilon final.</div>` +
    `<div data-chunk="S3">Zeta last.</div>`;
const ZH_HTML =
    `<div data-chunk="S0">甲一。 乙二。</div>` +
    `<figure data-chunk="F0"><img src="x.png"></figure>` +
    `<div data-chunk="S2">丙三。 丁四。 戊五。</div>` +
    `<div data-chunk="S3">己六。</div>`;

let paneEn!: HTMLElement;
let bodyEn!: HTMLElement;
let bodyZh!: HTMLElement;
let live!: HTMLElement;
let sentsEn!: SentMark[];
let sentsZh!: SentMark[];
let fsm: { kind: string; [k: string]: unknown }[] = [];
let clip = "";
let cur!: Cursor;
let leakSpy!: Mock<(e: Event) => void>;

const press = (key: string, init: KeyboardEventInit = {}) => {
    const t = (document.activeElement ?? document.body) as Element;
    const e = new KeyboardEvent("keydown", {
        key,
        bubbles: true,
        cancelable: true,
        ...init,
    });
    t.dispatchEvent(e);
    return e;
};

beforeEach(() => {
    document.body.innerHTML =
        `<div id="paneEn" class="pane" tabindex="0" data-side="original">` +
        `<div id="bodyEn" class="pane-html-body">${EN_HTML}</div></div>` +
        `<div id="paneZh" class="pane" tabindex="0" data-side="translated">` +
        `<div id="bodyZh" class="pane-html-body">${ZH_HTML}</div></div>` +
        `<div id="srLive" aria-live="polite"></div>`;
    paneEn = document.getElementById("paneEn")!;
    bodyEn = document.getElementById("bodyEn")!;
    bodyZh = document.getElementById("bodyZh")!;
    live = document.getElementById("srLive")!;
    sentsEn = segmentDoc(bodyEn, "en");
    sentsZh = segmentDoc(bodyZh, "zh");
    fsm = [];
    clip = "";
    // jsdom 无 clipboard/scrollIntoView——桩面
    Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: {
            writeText: (t: string) => {
                clip = t;
                return Promise.resolve();
            },
        },
    });
    if (!("scrollIntoView" in Element.prototype))
        Object.defineProperty(Element.prototype, "scrollIntoView", {
            configurable: true,
            value: () => {},
        });
    cur = makeCursor({
        pane: paneEn,
        body: bodyEn,
        sents: sentsEn,
        otherSents: sentsZh,
        live,
        hooks: { act: (kind, d) => fsm.push({ kind, ...(d as object) }) },
    });
    // 模态内按键不透全局——sIP 验证哨（后注册者被挡）
    leakSpy = vi.fn((_e: Event) => {});
    document.addEventListener("keydown", leakSpy);
});

afterEach(() => {
    cur.dispose();
    document.removeEventListener("keydown", leakSpy);
    document.body.innerHTML = "";
});

const mode = () => cur.state.mode;
const idx = () => cur.state.cur;
const says = () => fsm.filter((f) => f.kind === "say").map((f) => f.msg);
const lastSay = () => says().at(-1) as string | undefined;
const sentText = (i: number, all = sentsEn) => sentenceText(document, all, i);

describe("cursor modal (roving)", () => {
    it("v on focused pane enters cursor mode at first visible sentence", () => {
        paneEn.focus();
        press("v");
        expect(mode()).toBe("cursor");
        expect(idx()).toBe(0);
        expect(paneEn.classList.contains("cursor-on")).toBe(true);
        expect(document.activeElement).toBe(sentsEn[0]!.marker);
        expect(lastSay()).toContain("S1/6");
    });
    it("v outside pane does NOT enter; non-pane keys untouched", () => {
        document.body.focus?.();
        const e = new KeyboardEvent("keydown", { key: "v", bubbles: true });
        document.body.dispatchEvent(e); // target=body 不在本 pane
        expect(mode()).toBe("idle");
    });
    it("j/k move sentence granularity; endpoint clamps without wrap", () => {
        paneEn.focus();
        press("v");
        press("j");
        expect(idx()).toBe(1);
        press("k");
        expect(idx()).toBe(0);
        press("k"); // 顶端不环绕
        expect(idx()).toBe(0);
        expect(lastSay()).toContain("S1/6");
    });
    it("ArrowDown/ArrowUp mirror j/k", () => {
        paneEn.focus();
        press("v");
        press("ArrowDown");
        expect(idx()).toBe(1);
        press("ArrowUp");
        expect(idx()).toBe(0);
    });
    it("]/l jumps to next block first sentence; skips empty-sentence figure", () => {
        paneEn.focus();
        press("v");
        press("]"); // S0 → 跳过 F0(无句) → S2 首句
        expect(idx()).toBe(2); // sents: 0,1=S0; 2,3,4=S2; 5=S3
        expect(sentsEn[idx()]!.chunkEl.getAttribute("data-chunk")).toBe("S2");
        press("h"); // 回 S0 首句
        expect(idx()).toBe(0);
        press("l");
        press("l"); // S2 → S3
        expect(sentsEn[idx()]!.chunkEl.getAttribute("data-chunk")).toBe("S3");
    });
    it("Home/End first/last, no wrap", () => {
        paneEn.focus();
        press("v");
        press("End");
        expect(idx()).toBe(5);
        press("End");
        expect(idx()).toBe(5);
        press("Home");
        expect(idx()).toBe(0);
    });
    it("Enter places real Selection on the sentence range", () => {
        paneEn.focus();
        press("v");
        press("j");
        press("Enter");
        expect(mode()).toBe("selected");
        const sel = document.getSelection()!;
        expect(sel.isCollapsed).toBe(false);
        expect(sel.toString().trim()).toBe(sentText(1));
        press("Enter"); // 翻转取消
        expect(mode()).toBe("cursor");
        expect(sel.isCollapsed).toBe(true);
    });
    it("c copies payload = sentenceRange text (clipboard stub)", async () => {
        paneEn.focus();
        press("v");
        press("j");
        press("Enter");
        press("c");
        await Promise.resolve();
        expect(clip).toBe(sentText(1));
        expect(fsm.some((f) => f.kind === "copy" && f.ok === true)).toBe(true);
    });
    it("t swaps payload to other-side same-sid sentence", async () => {
        paneEn.focus();
        press("v");
        press("j"); // S0:1
        press("t");
        await Promise.resolve();
        expect(cur.state.payload?.side).toBe("translated");
        expect(cur.state.payload?.text).toBe(sentText(1, sentsZh));
        press("c");
        await Promise.resolve();
        expect(clip).toBe(sentText(1, sentsZh));
    });
    it("Esc exits to idle + refocuses pane", () => {
        paneEn.focus();
        press("v");
        press("j");
        press("Escape");
        expect(mode()).toBe("idle");
        expect(document.activeElement).toBe(paneEn);
        expect(lastSay()).toBe("cursor off");
    });
    it("Tab exits naturally (no refocus, no trap)", () => {
        paneEn.focus();
        press("v");
        press("j");
        const e = new KeyboardEvent("keydown", {
            key: "Tab",
            bubbles: true,
            cancelable: true,
        });
        (document.activeElement ?? document.body).dispatchEvent(e);
        expect(mode()).toBe("idle");
        expect(e.defaultPrevented).toBe(false); // 不拦——焦点走自然序
    });
    it("re-entry memory: second v restores last cursor", () => {
        paneEn.focus();
        press("v");
        press("j");
        press("j");
        press("j");
        press("Escape");
        paneEn.focus();
        press("v");
        expect(idx()).toBe(3);
    });
    it("markers never create tab stops (tabindex=-1 恒)", () => {
        for (const s of sentsEn) expect(s.marker.tabIndex).toBe(-1);
    });
    it("modal keys are suppressed (sIP) — leakSpy sees nothing modal", () => {
        paneEn.focus();
        press("v"); // v 进门不 sIP（idle 相只 preventDefault）
        leakSpy.mockClear(); // 清掉 v 的记录——模态期才开始断言
        press("j");
        press("Enter");
        press("c");
        press("Escape");
        expect(leakSpy).not.toHaveBeenCalled();
    });
    it("input focus inside modal passes keys through + exits", () => {
        paneEn.focus();
        press("v");
        const inp = document.createElement("input");
        bodyEn.appendChild(inp);
        inp.focus();
        const e = press("j");
        expect(e.defaultPrevented).toBe(false);
        expect(mode()).toBe("idle");
        inp.remove();
    });
    it("live region announces moves (aria-live 覆盖)", () => {
        paneEn.focus();
        press("v");
        press("j");
        expect(live.textContent).toContain("S2/6");
        expect(says().length).toBeGreaterThanOrEqual(2);
    });
});
