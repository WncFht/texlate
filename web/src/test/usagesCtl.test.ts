// @vitest-environment jsdom
// find-usages 交互层测试：attachUsages 三触发委托 + ADR-0021 时序
//   —— hover dwell 150ms / tap 即开 / contextmenu 全类直开并拦菜单 /
//      hoverable 门限（eq/sec/thm 仅右键）/ 锚元素让行 / 关卡宽限 /
//      openFor 命令路 / armTargets tabindex / dispose 摘监听。
// jsdom 无 PointerEvent——用普通 Event + 手工塞 pointerType。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attachUsages, type UsagesOpen } from "../reader/features/findusages";
import { buildUsageIndex } from "../reader/usages";

const DOC = `
    <nav><p><a href="#F1">toc</a></p></nav>
    <figure id="F1" class="ltx_figure"><figcaption>Figure 1: cap</figcaption></figure>
    <section class="ltx_section" id="S1"><h2>Intro</h2>
        <p>See <a href="#F1">Fig 1</a> here.</p></section>
    <div class="ltx_bibitem" id="bib.b1"><span class="ltx_tag_bibitem">[1]</span></div>
`;

function setup() {
    const pane = document.createElement("div");
    const body = document.createElement("div");
    body.innerHTML = DOC;
    pane.appendChild(body);
    document.body.appendChild(pane);
    const idx = buildUsageIndex(body);
    const opened: UsagesOpen[] = [];
    const closed = vi.fn();
    const willOpen = vi.fn();
    const ctl = attachUsages(
        { el: pane, bodyEl: () => body },
        {
            source: () => idx,
            open: (p) => opened.push(p),
            close: closed,
            onWillOpen: willOpen,
        },
    );
    return { pane, body, idx, opened, closed, willOpen, ctl };
}

const over = (t: Element, pointerType = "mouse") => {
    const e = new Event("pointerover", { bubbles: true });
    Object.defineProperty(e, "pointerType", { value: pointerType });
    t.dispatchEvent(e);
};
const out = (t: Element, rel: Element | null = null) => {
    const e = new Event("pointerout", { bubbles: true });
    Object.defineProperty(e, "relatedTarget", { value: rel });
    t.dispatchEvent(e);
};

describe("attachUsages", () => {
    beforeEach(() => {
        vi.useFakeTimers();
        document.body.innerHTML = "";
    });
    afterEach(() => {
        vi.useRealTimers();
        document.body.innerHTML = "";
    });

    it("hover dwell 150ms 开卡；未足时不发", () => {
        const { body, opened, ctl } = setup();
        const fig = body.querySelector("#F1")!;
        over(fig);
        vi.advanceTimersByTime(149);
        expect(opened).toHaveLength(0);
        vi.advanceTimersByTime(1);
        expect(opened).toHaveLength(1);
        expect(opened[0].via).toBe("hover");
        expect(opened[0].entry.target.id).toBe("F1");
        expect(ctl.isOpen()).toBe(true);
        ctl.dispose();
    });
    it("hoverable 门限：section 悬停不开，右键直开并拦菜单", () => {
        const { body, opened } = setup();
        const sec = body.querySelector("#S1")!;
        over(sec.querySelector("h2")!);
        vi.advanceTimersByTime(300);
        expect(opened).toHaveLength(0);
        const cm = new MouseEvent("contextmenu", {
            bubbles: true,
            cancelable: true,
        });
        sec.querySelector("h2")!.dispatchEvent(cm);
        expect(opened).toHaveLength(1);
        expect(opened[0].via).toBe("contextmenu");
        expect(opened[0].entry.target.id).toBe("S1");
        expect(cm.defaultPrevented).toBe(true);
    });
    it("tap/点击即开；bib 条目同权", () => {
        const { body, opened } = setup();
        const bib = body.querySelector('[id="bib.b1"]')!;
        bib.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(opened).toHaveLength(1);
        expect(opened[0].via).toBe("tap");
        expect(opened[0].entry.target.kind).toBe("bib");
    });
    it("锚元素让行：figure 内 a 不触发；点击锚收已开卡", () => {
        const { body, opened, closed } = setup();
        const fig = body.querySelector("#F1")!;
        // figure 内嵌一个锚
        const a = document.createElement("a");
        a.href = "#x";
        fig.appendChild(a);
        over(a);
        vi.advanceTimersByTime(300);
        expect(opened).toHaveLength(0);
        // 先开卡再点锚 → 收
        fig.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(opened).toHaveLength(1);
        a.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(closed).toHaveBeenCalled();
    });
    it("pointerout 关卡宽限 350ms；回入撤关", () => {
        const { body, opened, closed } = setup();
        const fig = body.querySelector("#F1")!;
        over(fig);
        vi.advanceTimersByTime(150);
        expect(opened).toHaveLength(1);
        out(fig, document.body);
        vi.advanceTimersByTime(349);
        expect(closed).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(closed).toHaveBeenCalledTimes(1);
        // 重开后 hover 回宿主内子元素不触发关卡
        over(fig);
        vi.advanceTimersByTime(150);
        const cap = fig.querySelector("figcaption")!;
        out(fig, cap);
        vi.advanceTimersByTime(500);
        expect(closed).toHaveBeenCalledTimes(1); // 未再关
    });
    it("touch 指针不触发 hover 开卡", () => {
        const { body, opened } = setup();
        over(body.querySelector("#F1")!, "touch");
        vi.advanceTimersByTime(500);
        expect(opened).toHaveLength(0);
    });
    it("openFor：id/元素两路 + 未索引 false", () => {
        const { body, opened, ctl } = setup();
        expect(ctl.openFor("S1")).toBe(true);
        expect(opened[0].via).toBe("command");
        expect(ctl.openFor(body.querySelector("#F1"))).toBe(true);
        expect(opened).toHaveLength(2);
        expect(ctl.openFor("NOPE")).toBe(false);
        expect(ctl.openFor(null)).toBe(false);
        ctl.dispose();
    });
    it("openFor 优先用 anchor 元素定位（命令路跳回点）", () => {
        const { body, opened, ctl } = setup();
        const a = body.querySelector('a[href="#F1"]')!;
        expect(ctl.openFor("F1", a)).toBe(true);
        expect(opened[0].trigger).toBe(a);
        ctl.dispose();
    });
    it("contextmenu shiftKey 放行原生菜单；非索引目标不拦", () => {
        const { body, opened } = setup();
        const sec = body.querySelector("#S1")!;
        const cm = new MouseEvent("contextmenu", {
            bubbles: true,
            cancelable: true,
            shiftKey: true,
        });
        sec.dispatchEvent(cm);
        expect(cm.defaultPrevented).toBe(false);
        expect(opened).toHaveLength(0);
        // nav chrome 内（不索引）
        const nav = body.querySelector("nav p")!;
        const cm2 = new MouseEvent("contextmenu", {
            bubbles: true,
            cancelable: true,
        });
        nav.dispatchEvent(cm2);
        expect(cm2.defaultPrevented).toBe(false);
    });
    it("armTargets 注 tabindex；dispose 摘监听", () => {
        const { body, ctl } = setup();
        ctl.armTargets(body);
        expect(body.querySelector("#F1")!.getAttribute("tabindex")).toBe("0");
        expect(
            body.querySelector('[id="bib.b1"]')!.getAttribute("tabindex"),
        ).toBe("0");
        ctl.dispose();
        body.querySelector("#F1")!.dispatchEvent(
            new MouseEvent("click", { bubbles: true }),
        );
        expect(ctl.isOpen()).toBe(false);
    });
});
