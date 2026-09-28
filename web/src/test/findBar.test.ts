// @vitest-environment jsdom
// FindBar 组件面：eventBus 订阅 / find 派发载荷 / 250ms 输入防抖 /
// Enter→again（shiftKey→findPrevious）/ 选项变更即时派发 / Escape 与 ✕ 的
// findbarclose+onClose 语义。Escape 回归钉：keydown 是 Solid 委托事件
// （监听挂 document），须 stopImmediatePropagation 才拦得住同节点注册的
// document 级 Esc 监听（DocInfo 弹层/菜单）——只 stopPropagation 会双关。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "solid-js/web";
import type { PDFSlick } from "@pdfslick/solid";
import FindBar from "../reader/panes/FindBar";

interface Bus {
    dispatch: ReturnType<typeof vi.fn>;
    on: ReturnType<typeof vi.fn>;
    off: ReturnType<typeof vi.fn>;
}

let dispose: (() => void) | undefined;
let bus: Bus;

const slickOf = () => ({ eventBus: bus }) as unknown as PDFSlick;
const input = () => document.body.querySelector<HTMLInputElement>(".fb-input")!;

const type = (v: string) => {
    const el = input();
    el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
};

const mount = (onClose = vi.fn()) => {
    dispose = render(
        () => FindBar({ slick: slickOf, open: true, onClose }),
        document.body,
    );
    return onClose;
};

beforeEach(() => {
    bus = { dispatch: vi.fn(), on: vi.fn(), off: vi.fn() };
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
    vi.useRealTimers();
});

describe("FindBar", () => {
    it("挂载即订阅 updatefindmatchescount / updatefindcontrolstate", () => {
        mount();
        const chans = bus.on.mock.calls.map((c) => c[0]);
        expect(chans).toContain("updatefindmatchescount");
        expect(chans).toContain("updatefindcontrolstate");
    });

    it("输入走 250ms 防抖，合并派发完整 find 载荷", async () => {
        vi.useFakeTimers();
        mount();
        type("atten");
        type("attention");
        await vi.advanceTimersByTimeAsync(249);
        expect(bus.dispatch).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(1);
        expect(bus.dispatch).toHaveBeenCalledTimes(1);
        const [ev, payload] = bus.dispatch.mock.calls[0];
        expect(ev).toBe("find");
        expect(payload.type).toBeUndefined(); // type 缺省 = 新查询
        expect(payload).toMatchObject({
            query: "attention",
            phraseSearch: true,
            caseSensitive: false,
            entireWord: false,
            highlightAll: true,
            matchDiacritics: false,
            findPrevious: false,
        });
    });

    it("Enter 即时派发 again；Shift+Enter 带 findPrevious", () => {
        mount();
        type("x");
        input().dispatchEvent(
            new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
        );
        expect(bus.dispatch).toHaveBeenCalledTimes(1);
        expect(bus.dispatch.mock.calls[0][1]).toMatchObject({
            type: "again",
            findPrevious: false,
        });
        input().dispatchEvent(
            new KeyboardEvent("keydown", {
                key: "Enter",
                shiftKey: true,
                bubbles: true,
            }),
        );
        expect(bus.dispatch).toHaveBeenCalledTimes(2);
        expect(bus.dispatch.mock.calls[1][1]).toMatchObject({
            type: "again",
            findPrevious: true,
        });
    });

    it("选项变更即时派发——highlightallchange 携带新 hlAll 态", () => {
        mount();
        document.body
            .querySelectorAll<HTMLInputElement>(
                ".fb-opts input[type=checkbox]",
            )[0]
            .click(); // highlightAll: true → false
        expect(bus.dispatch).toHaveBeenCalledTimes(1);
        expect(bus.dispatch.mock.calls[0][1]).toMatchObject({
            type: "highlightallchange",
            highlightAll: false,
        });
    });

    it("Escape → findbarclose+onClose，document 级监听吃不到（DocInfo 双关回归）", () => {
        const onClose = mount();
        const docSpy = vi.fn();
        document.addEventListener("keydown", docSpy);
        try {
            input().dispatchEvent(
                new KeyboardEvent("keydown", {
                    key: "Escape",
                    bubbles: true,
                }),
            );
        } finally {
            document.removeEventListener("keydown", docSpy);
        }
        expect(bus.dispatch).toHaveBeenCalledWith("findbarclose", {});
        expect(onClose).toHaveBeenCalledTimes(1);
        expect(docSpy).not.toHaveBeenCalled();
    });

    it("✕ 关闭钮 → findbarclose+onClose", () => {
        const onClose = mount();
        // .fb-row 三钮序：↑ prev / ↓ next / ✕ close
        document.body.querySelectorAll<HTMLButtonElement>(".fb-btn")[2].click();
        expect(bus.dispatch).toHaveBeenCalledWith("findbarclose", {});
        expect(onClose).toHaveBeenCalledTimes(1);
    });
});
