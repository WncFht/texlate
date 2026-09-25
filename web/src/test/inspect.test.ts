// @vitest-environment jsdom
// ⌘-Inspect 检视层闸行为测试：attachInspect 单 document-capture 闸的
//   —— accel 放行序（无 accel/detail=0/shift/卡内/外链/活选区/pdfjs armed）
//      inspectAt handled→吞 / 未 handled 阅读面内→吞 / math→放行 /
//      ⌘+Alt→inspectDestAt+mirror / armed 揭示（keydown 上类、keyup/blur 摘、
//      pointermove hover 强化 .insp-hot / pdf cursor）/ dispose 摘净。
// jsdom 无 PointerEvent——pointermove 用 MouseEvent 同型派发。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
    attachInspect,
    type InspectDeps,
    type InspectHandle,
} from "../reader/features/inspect";
import type { DocId } from "../reader/alignment";

const IS_MAC = /mac/i.test(
    (navigator as Navigator & { userAgentData?: { platform?: string } })
        .userAgentData?.platform ??
        navigator.platform ??
        "",
);
const ACCEL = IS_MAC ? { metaKey: true } : { ctrlKey: true };
const NON_ACCEL = IS_MAC ? { ctrlKey: true } : { metaKey: true };

function fixture() {
    const root = document.createElement("div");
    root.className = "panes";
    const mkPane = (side: DocId) => {
        const p = document.createElement("div");
        p.className = "pane";
        p.setAttribute("data-side", side);
        const body = document.createElement("div");
        body.className = "body";
        p.appendChild(body);
        root.appendChild(p);
        return { p, body };
    };
    const orig = mkPane("original");
    const trans = mkPane("translated");
    document.body.appendChild(root);
    return { root, orig, trans };
}

interface Fake {
    el: HTMLElement;
    handle: InspectHandle;
    inspectAt: ReturnType<typeof vi.fn>;
    inspectDestAt: ReturnType<typeof vi.fn>;
}

function mkHandle(el: HTMLElement, body: HTMLElement): Fake {
    const inspectAt = vi.fn((_x: number, _y: number) => false);
    const inspectDestAt = vi.fn(
        (_x: number, _y: number): { dest: unknown } | null => null,
    );
    return {
        el,
        inspectAt,
        inspectDestAt,
        handle: {
            el,
            bodyEl: () => body,
            inspectAt: (x, y) => inspectAt(x, y),
            inspectDestAt: (x, y) => inspectDestAt(x, y),
        },
    };
}

function setup(opts?: Partial<InspectDeps>) {
    const { root, orig, trans } = fixture();
    const hO = mkHandle(orig.p, orig.body);
    const hT = mkHandle(trans.p, trans.body);
    const mirror = vi.fn();
    const armed = vi.fn(() => false);
    const deps: InspectDeps = {
        rootEl: () => root,
        handleOf: (s) => (s === "original" ? hO.handle : hT.handle),
        pdfjsArmed: armed,
        anyPdfjsArmed: () => false,
        mirror,
        ...opts,
    };
    const ctl = attachInspect(deps);
    return { root, orig, trans, hO, hT, mirror, armed, ctl };
}

/** 在 target 上派 click（capture 闸跑的同一条路）；返回是否被 preventDefault */
function clickOn(
    target: Element,
    opts: MouseEventInit = {},
): { prevented: boolean } {
    const e = new MouseEvent("click", {
        bubbles: true,
        cancelable: true,
        detail: 1,
        clientX: 10,
        clientY: 10,
        ...opts,
    });
    target.dispatchEvent(e);
    return { prevented: e.defaultPrevented };
}

describe("attachInspect 闸放行序", () => {
    afterEach(() => {
        document.body.innerHTML = "";
    });

    it("无 accel → inspectAt 不查不吞", () => {
        const s = setup();
        const r = clickOn(s.orig.body, { ...NON_ACCEL });
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it("e.detail===0 键盘派发 → 放行", () => {
        const s = setup();
        const e = new MouseEvent("click", {
            bubbles: true,
            cancelable: true,
            detail: 0,
            ...ACCEL,
        });
        s.orig.body.dispatchEvent(e);
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        expect(e.defaultPrevented).toBe(false);
        s.ctl.dispose();
    });

    it("⌘+Shift+click → 原生新标签语义放行", () => {
        const s = setup();
        const r = clickOn(s.orig.body, { ...ACCEL, shiftKey: true });
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it("卡内/控件 → 放行", () => {
        const s = setup();
        const card = document.createElement("div");
        card.className = "cite-card";
        s.orig.body.appendChild(card);
        const r = clickOn(card, ACCEL);
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it("外链 a[href^=http] → 放行", () => {
        const s = setup();
        const a = document.createElement("a");
        a.href = "https://arxiv.org/abs/1";
        s.orig.body.appendChild(a);
        const r = clickOn(a, ACCEL);
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it("活选区 → 放行", () => {
        const s = setup({ hasLiveSelection: () => true });
        const r = clickOn(s.orig.body, ACCEL);
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it("本侧 pdfjs armed → 放行（对侧不 armed 仍正常）", () => {
        const s = setup({
            pdfjsArmed: (side) => side === "original",
        });
        const r1 = clickOn(s.orig.body, ACCEL);
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        expect(r1.prevented).toBe(false);
        s.hT.inspectAt.mockReturnValue(true);
        const r2 = clickOn(s.trans.body, ACCEL);
        expect(s.hT.inspectAt).toHaveBeenCalled();
        expect(r2.prevented).toBe(true);
        s.ctl.dispose();
    });

    it("inspectAt handled → 吞（preventDefault+截停冒泡）", () => {
        const s = setup();
        s.hO.inspectAt.mockReturnValue(true);
        const bub = vi.fn();
        document.addEventListener("click", bub);
        const r = clickOn(s.orig.body, ACCEL);
        expect(s.hO.inspectAt).toHaveBeenCalledWith(10, 10);
        expect(r.prevented).toBe(true);
        expect(bub).not.toHaveBeenCalled();
        document.removeEventListener("click", bub);
        s.ctl.dispose();
    });

    it("未 handled + 阅读面内 → 吞（空白处 ⌘ 点击表 inspect 意图）", () => {
        const s = setup();
        const r = clickOn(s.orig.body, ACCEL);
        expect(s.hO.inspectAt).toHaveBeenCalled();
        expect(r.prevented).toBe(true);
        s.ctl.dispose();
    });

    it("未 handled + math → 放行（copylatex 冒泡委托要收）", () => {
        const s = setup();
        const m = document.createElement("math");
        s.orig.body.appendChild(m);
        const r = clickOn(m, ACCEL);
        expect(s.hO.inspectAt).toHaveBeenCalled();
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it(".katex 容器同 math 放行", () => {
        const s = setup();
        const k = document.createElement("span");
        k.className = "katex";
        s.orig.body.appendChild(k);
        const r = clickOn(k, ACCEL);
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it("未 handled + pane 外（surface 外）→ 放行", () => {
        const s = setup();
        const out = document.createElement("div");
        s.orig.p.appendChild(out); // pane 内但 bodyEl 外
        // dom 臂 surface=bodyEl——body 外不吞
        const r = clickOn(out, ACCEL);
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it("非 .pane 面 → 放行（live-pane 等）", () => {
        const s = setup();
        const live = document.createElement("div");
        live.className = "live-pane";
        s.root.appendChild(live);
        const r = clickOn(live, ACCEL);
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });
});

describe("⌘+Alt 镜像臂", () => {
    afterEach(() => {
        document.body.innerHTML = "";
    });

    it("inspectDestAt 出 dest → 吞 + mirror 对侧", () => {
        const s = setup();
        s.hO.inspectDestAt.mockReturnValue({ dest: "cite.k1" });
        const r = clickOn(s.orig.body, { ...ACCEL, altKey: true });
        expect(r.prevented).toBe(true);
        expect(s.mirror).toHaveBeenCalledWith("translated", "cite.k1");
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        s.ctl.dispose();
    });

    it("dest null + math → 放行", () => {
        const s = setup();
        const m = document.createElement("math");
        s.orig.body.appendChild(m);
        const r = clickOn(m, { ...ACCEL, altKey: true });
        expect(s.mirror).not.toHaveBeenCalled();
        expect(r.prevented).toBe(false);
        s.ctl.dispose();
    });

    it("dest null + surface 内 → 吞", () => {
        const s = setup();
        const r = clickOn(s.orig.body, { ...ACCEL, altKey: true });
        expect(s.mirror).not.toHaveBeenCalled();
        expect(r.prevented).toBe(true);
        s.ctl.dispose();
    });

    it("translated→original 方向 mirror 侧正确", () => {
        const s = setup();
        s.hT.inspectDestAt.mockReturnValue({ dest: { u: 1, id: "k" } });
        clickOn(s.trans.body, { ...ACCEL, altKey: true });
        expect(s.mirror).toHaveBeenCalledWith("original", { u: 1, id: "k" });
        s.ctl.dispose();
    });
});

describe("armed 揭示", () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });
    afterEach(() => {
        vi.useRealTimers();
        document.body.innerHTML = "";
    });

    const key = (type: string, opts: KeyboardEventInit) =>
        document.dispatchEvent(
            new KeyboardEvent(type, { ...opts, bubbles: true }),
        );

    /** jsdom 无 elementFromPoint——直接塞替身（非 spyOn：原函数不存在） */
    const stubEfp = (fn: ((x: number, y: number) => Element | null) | null) => {
        (
            document as unknown as {
                elementFromPoint?:
                    | ((x: number, y: number) => Element | null)
                    | undefined;
            }
        ).elementFromPoint = fn ?? undefined;
    };

    it("keydown accel → .insp-armed 上根；keyup → 摘", () => {
        const s = setup();
        key("keydown", ACCEL);
        expect(s.root.classList.contains("insp-armed")).toBe(true);
        key("keyup", { ...ACCEL, ctrlKey: false, metaKey: false });
        expect(s.root.classList.contains("insp-armed")).toBe(false);
        s.ctl.dispose();
    });

    it("pdfjs armed 时不上揭示类", () => {
        const s = setup({ anyPdfjsArmed: () => true });
        key("keydown", ACCEL);
        expect(s.root.classList.contains("insp-armed")).toBe(false);
        s.ctl.dispose();
    });

    it("blur → 摘类清轨", () => {
        const s = setup();
        key("keydown", ACCEL);
        window.dispatchEvent(new Event("blur"));
        expect(s.root.classList.contains("insp-armed")).toBe(false);
        s.ctl.dispose();
    });

    it("armed hover：dom 锚命中 → .insp-hot 单轨移标", () => {
        const s = setup();
        const a = document.createElement("a");
        a.href = "#F1";
        s.orig.body.appendChild(a);
        stubEfp(() => a);
        key("keydown", ACCEL);
        expect(a.classList.contains("insp-hot")).toBe(true);
        const p = document.createElement("p");
        s.orig.body.appendChild(p);
        stubEfp(() => p);
        document.dispatchEvent(
            new MouseEvent("pointermove", {
                clientX: 5,
                clientY: 5,
                bubbles: true,
            }),
        );
        expect(a.classList.contains("insp-hot")).toBe(false);
        stubEfp(null);
        s.ctl.dispose();
    });

    it("armed hover：pdf 臂 dest 命中 → 容器 cursor:pointer", () => {
        const s = setup();
        // pdf 臂形态：无 bodyEl，有 destAtPoint
        const hP = {
            el: s.orig.p,
            destAtPoint: vi.fn(() => "cite.k1"),
            inspectAt: vi.fn(() => false),
            inspectDestAt: vi.fn(() => null),
        } as unknown as InspectHandle;
        const page = document.createElement("div");
        page.setAttribute("data-page-number", "1");
        s.orig.p.appendChild(page);
        const s2 = attachInspect({
            rootEl: () => s.root,
            handleOf: () => hP,
            pdfjsArmed: () => false,
            anyPdfjsArmed: () => false,
            mirror: vi.fn(),
        });
        stubEfp(() => page);
        key("keydown", ACCEL);
        expect(hP.el.style.cursor).toBe("pointer");
        s2.dispose();
        stubEfp(null);
        s.ctl.dispose();
    });

    it("dispose → 类/热轨/监听全摘", () => {
        const s = setup();
        key("keydown", ACCEL);
        s.ctl.dispose();
        expect(s.root.classList.contains("insp-armed")).toBe(false);
        s.hO.inspectAt.mockReturnValue(true);
        const r = clickOn(s.orig.body, ACCEL);
        expect(s.hO.inspectAt).not.toHaveBeenCalled();
        expect(r.prevented).toBe(false);
    });
});
