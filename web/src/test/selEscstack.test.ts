// selEscstack —— Esc 层栈单塌语义（预研 12 层栈剧本的纯逻辑面）。
// 契约：优先级序固定（editor>cite>find>menu>info>help>sel）——「最内层
// 先塌」而非「最后开先塌」；一次 collapseTop 恰好塌一层；passive 层
// （editor）只记账不消费——不 close、不动标记，事件穿透给 pdf.js。

import { describe, expect, it } from "vitest";
import { EscStack, ESC_ORDER, type EscLayer } from "../reader/sel/escstack";

const mk = () => {
    const stack = new EscStack();
    const closed: EscLayer[] = [];
    const layers = new Map<EscLayer, boolean>();
    const openFlag = (l: EscLayer) =>
        stack.push(l, { close: () => closed.push(l) });
    const openQuery = (l: EscLayer) => {
        layers.set(l, true);
        stack.bind(l, {
            isOpen: () => layers.get(l) === true,
            close: () => {
                layers.set(l, false);
                closed.push(l);
            },
        });
    };
    return { stack, closed, layers, openFlag, openQuery };
};

describe("EscStack single-collapse", () => {
    it("empty stack → collapseTop null", () => {
        expect(new EscStack().collapseTop()).toBeNull();
    });
    it("one Esc collapses exactly one layer (flag model)", () => {
        const { stack, closed, openFlag } = mk();
        openFlag("menu");
        openFlag("help");
        // ESC_ORDER: menu(3) 先于 help(5)——与开序无关
        expect(stack.collapseTop()).toEqual({ layer: "menu", consumed: true });
        expect(closed).toEqual(["menu"]);
        expect(stack.collapseTop()).toEqual({ layer: "help", consumed: true });
        expect(stack.collapseTop()).toBeNull();
        expect(closed).toEqual(["menu", "help"]);
    });
    it("priority order beats open order (cite opened before help)", () => {
        const { stack, closed, openFlag } = mk();
        openFlag("help"); // 后开的 help 序位更低
        openFlag("cite");
        expect(stack.top()).toBe("cite");
        stack.collapseTop();
        expect(closed).toEqual(["cite"]);
        expect(stack.top()).toBe("help");
    });
    it("STACKS 剧本：cite+help → [[cite],[help]]", () => {
        const { stack, openQuery } = mk();
        openQuery("cite");
        openQuery("help");
        const seq = [stack.collapseTop()?.layer, stack.collapseTop()?.layer];
        expect(seq).toEqual(["cite", "help"]);
    });
    it("STACKS 剧本：menu+help → [[menu],[help]]（legacy 双塌修复）", () => {
        const { stack, openQuery } = mk();
        openQuery("menu");
        openQuery("help");
        const seq = [stack.collapseTop()?.layer, stack.collapseTop()?.layer];
        expect(seq).toEqual(["menu", "help"]);
    });
    it("STACKS 剧本：info+menu → [[menu],[info]]", () => {
        const { stack, openQuery } = mk();
        openQuery("info");
        openQuery("menu");
        const seq = [stack.collapseTop()?.layer, stack.collapseTop()?.layer];
        expect(seq).toEqual(["menu", "info"]);
    });
    it("STACKS 剧本：cite+find → [[cite],[find]]", () => {
        const { stack, openQuery } = mk();
        openQuery("cite");
        openQuery("find");
        const seq = [stack.collapseTop()?.layer, stack.collapseTop()?.layer];
        expect(seq).toEqual(["cite", "find"]);
    });
    it("passive editor: consumed=false, no close, flag untouched", () => {
        const { stack, closed, openQuery } = mk();
        let selected = true;
        stack.bind("editor", {
            isOpen: () => selected,
            passive: true,
            close: () => closed.push("editor"), // 不应被调
        });
        openQuery("cite");
        const r = stack.collapseTop();
        expect(r).toEqual({ layer: "editor", consumed: false });
        expect(closed).toEqual([]); // passive 不 close
        expect(stack.isOpen("editor")).toBe(true); // 记账层态不动（宿主回写）
        expect(stack.isOpen("cite")).toBe(true); // 下层不连带塌
        // 宿主（pdf.js）自己做 unselectAll → 回写 selected=false 后轮到 cite
        selected = false;
        expect(stack.collapseTop()).toEqual({ layer: "cite", consumed: true });
    });
    it("STACKS 剧本：editor+cite → [[editor],[cite]]", () => {
        const { stack, openQuery } = mk();
        let selected = true;
        stack.bind("editor", { isOpen: () => selected, passive: true });
        openQuery("cite");
        const s1 = stack.collapseTop();
        expect(s1).toEqual({ layer: "editor", consumed: false });
        selected = false; // window 级 pdf.js unselectAll 已跑
        expect(stack.collapseTop()?.layer).toBe("cite");
    });
    it("query-model isOpen is live — closed layers are skipped", () => {
        const { stack, layers, openQuery } = mk();
        openQuery("cite");
        openQuery("find");
        layers.set("cite", false); // 宿主自己关了
        expect(stack.top()).toBe("find");
        expect(stack.openLayers()).toEqual(["find"]);
    });
    it("push disposer pops the layer", () => {
        const stack = new EscStack();
        const d1 = stack.push("menu");
        stack.push("help");
        d1();
        expect(stack.top()).toBe("help");
        expect(stack.isOpen("menu")).toBe(false);
    });
    it("flag-model: collapseTop turns flag off (isOpen false after collapse)", () => {
        const stack = new EscStack();
        stack.push("cite");
        stack.collapseTop();
        expect(stack.isOpen("cite")).toBe(false);
        expect(stack.top()).toBeNull();
    });
    it("ESC_ORDER exposes the canonical priority", () => {
        expect([...ESC_ORDER]).toEqual([
            "editor",
            "cite",
            "find",
            "menu",
            "info",
            "help",
            "sel",
        ]);
    });
});
