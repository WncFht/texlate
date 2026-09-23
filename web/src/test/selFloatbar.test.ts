// @vitest-environment jsdom
// selFloatbar —— placeBar 纯函数不变量 fuzz + createFloatBar 行为面
// （allowShow 闸保锚 / pointercancel 解卡 / 出屏保锚滚回重现 / scroll
// 重估）+ FloatBar 组件面（itemsFor 注入→钮渲染→click 出口→
// suppressed 互斥）。
// jsdom 无 layout：Range.prototype.getBoundingClientRect/getClientRects
// 桩成视口内定值；条 offsetWidth 恒 0 → 走 place() 的 96px 兜底宽。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "solid-js/web";
import {
    BAR_MARGIN,
    createFloatBar,
    FloatBar,
    placeBar,
    type FloatBarApi,
    type RectLike,
} from "../reader/FloatBar";

// ---------------------------------------------------------------- placeBar

const rect = (
    left: number,
    top: number,
    right: number,
    bottom: number,
): RectLike => ({
    left,
    top,
    right,
    bottom,
    width: right - left,
    height: bottom - top,
});

describe("placeBar", () => {
    it("上空间够 → above 不翻；不够且下够 → below 翻", () => {
        const a = rect(100, 200, 200, 220);
        const p1 = placeBar(a, 96, 32, 1024, 768);
        expect(p1.placement).toBe("above");
        expect(p1.flipped).toBe(false);
        expect(p1.top).toBe(200 - 8 - 32); // anchor.top - gap - h
        // 上空间不足（锚贴顶）→ below
        const p2 = placeBar(rect(100, 10, 200, 30), 96, 32, 1024, 768);
        expect(p2.placement).toBe("below");
        expect(p2.flipped).toBe(true);
        expect(p2.top).toBe(30 + 8);
    });

    it("prefer=below 对称翻边", () => {
        const p = placeBar(rect(100, 200, 200, 220), 96, 32, 1024, 768, {
            prefer: "below",
        });
        expect(p.placement).toBe("below");
        expect(p.flipped).toBe(false);
        const p2 = placeBar(rect(100, 740, 200, 760), 96, 32, 1024, 768, {
            prefer: "below",
        });
        expect(p2.placement).toBe("above");
        expect(p2.flipped).toBe(true);
    });

    it("fuzz 5000：w+2m<=vw 且 h+2m<=vh → 落点必在视口内", () => {
        let seed = 0x9e3779b9;
        const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff);
        for (let i = 0; i < 5000; i++) {
            const vw = 300 + (rnd() % 1200);
            const vh = 200 + (rnd() % 900);
            const w = 20 + (rnd() % 200);
            const h = 16 + (rnd() % 80);
            if (w + 2 * BAR_MARGIN > vw || h + 2 * BAR_MARGIN > vh) continue;
            const ax = rnd() % vw;
            const ay = rnd() % vh;
            const a = rect(ax, ay, ax + 1 + (rnd() % 60), ay + 1 + (rnd() % 30));
            const p = placeBar(
                a,
                w,
                h,
                vw,
                vh,
                rnd() % 2 ? { prefer: "below" } : {},
            );
            expect(p.left).toBeGreaterThanOrEqual(BAR_MARGIN);
            expect(p.top).toBeGreaterThanOrEqual(BAR_MARGIN);
            expect(p.left + w).toBeLessThanOrEqual(vw - BAR_MARGIN);
            expect(p.top + h).toBeLessThanOrEqual(vh - BAR_MARGIN);
        }
    });
});

// ---------------------------------------------------------- createFloatBar

const FAKE = rect(100, 200, 200, 216);
let dispose: (() => void) | undefined;
let origGBCR: typeof Range.prototype.getBoundingClientRect;
let origGCR: typeof Range.prototype.getClientRects;
let barRect = FAKE;

const select = (el: Element) => {
    const t = el.firstChild as Text;
    document.getSelection()!.setBaseAndExtent(t, 0, t, t.length);
};

/** 轮询断言前置——release 40ms 静默+rAF 在满载套件下定长 sleep 余量
    不够，一律等到条件成立（上限防死循环） */
const until = async (fn: () => boolean, ms = 800) => {
    const t0 = Date.now();
    while (!fn() && Date.now() - t0 < ms)
        await new Promise((r) => setTimeout(r, 10));
};

beforeEach(() => {
    barRect = FAKE;
    origGBCR = Range.prototype.getBoundingClientRect;
    origGCR = Range.prototype.getClientRects;
    Range.prototype.getBoundingClientRect = function () {
        return { ...barRect, x: barRect.left, y: barRect.top } as DOMRect;
    };
    Range.prototype.getClientRects = function () {
        return [{ ...barRect, x: barRect.left, y: barRect.top }] as unknown as DOMRectList;
    };
    document.body.innerHTML = `
<div class="panes"><div class="pane" data-side="original">
  <div class="pane-html-body"><div data-chunk="0" id="c0">hello world sentence</div></div>
</div></div>`;
});

afterEach(() => {
    Range.prototype.getBoundingClientRect = origGBCR;
    Range.prototype.getClientRects = origGCR;
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
    document.getSelection()?.removeAllRanges();
    vi.unstubAllGlobals();
});

describe("createFloatBar", () => {
    it("live 模式：selectionchange → rAF → 显条（placement 入 dataset）", async () => {
        const api = createFloatBar({ mode: "live" });
        select(document.getElementById("c0")!);
        document.dispatchEvent(new Event("selectionchange"));
        await until(() => api.visible());
        expect(api.visible()).toBe(true);
        expect(api.stats.shows).toBe(1);
        expect(api.el.dataset.placement).toBe("above");
        expect(api.range()).not.toBeNull();
        api.destroy();
    });

    it("release 模式：pointerdown 期压制，pointercancel 同 pointerup 解卡", async () => {
        const api = createFloatBar({ mode: "release" });
        const el = document.getElementById("c0")!;
        select(el);
        // 按下后 selectionchange —— 只记 pending 不排程
        document.dispatchEvent(new Event("pointerdown", { bubbles: true }));
        const before = api.stats.schedules;
        document.dispatchEvent(new Event("selectionchange"));
        expect(api.stats.schedules).toBe(before);
        // pointercancel（触摸滚动夺手势）——与 pointerup 同语义解卡
        document.dispatchEvent(new Event("pointercancel", { bubbles: true }));
        await until(() => api.visible()); // 40ms 静默期 + rAF
        expect(api.visible()).toBe(true);
        api.destroy();
    });

    it("allowShow=false → 收条但保锚；闸松 + refresh → 免 selectionchange 重现", async () => {
        let allow = false;
        const api = createFloatBar({ mode: "live", allowShow: () => allow });
        select(document.getElementById("c0")!);
        document.dispatchEvent(new Event("selectionchange"));
        await until(() => api.range() != null); // update 已跑——锚已存
        expect(api.visible()).toBe(false);
        expect(api.range()).not.toBeNull(); // keepAnchor——锚留存
        allow = true;
        api.refresh();
        await until(() => api.visible());
        expect(api.visible()).toBe(true);
        api.destroy();
    });

    it("锚出视口 → 藏而保锚；滚回视口 → 重现", async () => {
        const api = createFloatBar({ mode: "live" });
        select(document.getElementById("c0")!);
        document.dispatchEvent(new Event("selectionchange"));
        await until(() => api.visible());
        expect(api.visible()).toBe(true);
        // 锚滚出视口（scroll capture 监听在 document）
        barRect = rect(100, -500, 200, -480);
        document.dispatchEvent(new Event("scroll"));
        await until(() => !api.visible());
        expect(api.visible()).toBe(false);
        expect(api.range()).not.toBeNull();
        barRect = FAKE;
        document.dispatchEvent(new Event("scroll"));
        await until(() => api.visible());
        expect(api.visible()).toBe(true);
        api.destroy();
    });

    it("destroy 清理：自带壳 el 从 body 摘除", async () => {
        const api = createFloatBar({ mode: "live" });
        const el = api.el;
        expect(document.body.contains(el)).toBe(true);
        api.destroy();
        expect(document.body.contains(el)).toBe(false);
    });
});

// ------------------------------------------------------------ FloatBar 组件

describe("FloatBar 组件", () => {
    it("itemsFor 注入 → 钮渲染；click → onAction(id) + 收条", async () => {
        const onAction = vi.fn();
        let api: FloatBarApi | null = null;
        vi.stubGlobal(
            "ResizeObserver",
            class {
                observe() {}
                unobserve() {}
                disconnect() {}
            },
        );
        dispose = render(() =>
            FloatBar({
                itemsFor: () => [
                    { id: "sel.copy", label: "Copy" },
                    { id: "sel.find", label: "Find", hint: "L" },
                ],
                onAction,
                observeEls: () => [document.querySelector(".panes")],
                apiRef: (a) => (api = a),
            }),
            document.body,
        );
        select(document.getElementById("c0")!);
        document.dispatchEvent(new Event("selectionchange"));
        await until(() => api?.visible() ?? false); // release 40ms+rAF
        const bar = document.querySelector(".floatbar")!;
        expect(api!.visible()).toBe(true);
        const btns = bar.querySelectorAll("button");
        expect(btns.length).toBe(2);
        expect(btns[0]!.textContent).toContain("Copy");
        (btns[0] as HTMLButtonElement).click();
        expect(onAction).toHaveBeenCalledWith("sel.copy", expect.anything());
        await until(() => !api!.visible());
        expect(api!.visible()).toBe(false); // 动作执行后收条
    });

    it("itemsFor 空集 → 不示条；suppressed → 互斥收条", async () => {
        let suppressed = false;
        let empty = true;
        let api: FloatBarApi | null = null;
        dispose = render(() =>
            FloatBar({
                itemsFor: () => (empty ? [] : [{ id: "sel.copy", label: "C" }]),
                onAction: () => {},
                suppressed: () => suppressed,
                apiRef: (a) => (api = a),
            }),
            document.body,
        );
        select(document.getElementById("c0")!);
        document.dispatchEvent(new Event("selectionchange"));
        await until(() => api?.range() != null); // update 已跑——锚已存
        expect(api!.visible()).toBe(false); // 空集 veto
        expect(api!.range()).not.toBeNull(); // 保锚
        // 非空后闸松重现
        empty = false;
        api!.refresh();
        await until(() => api!.visible());
        expect(api!.visible()).toBe(true);
        // suppressed 互斥（右键菜单开单）
        suppressed = true;
        api!.refresh();
        await until(() => !api!.visible());
        expect(api!.visible()).toBe(false);
    });
});
