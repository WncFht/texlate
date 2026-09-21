// @vitest-environment jsdom
// Segmented radio 组键盘契约（U15）：方向键循环、Home/End 跳首尾、
// roving tabindex（仅现值项 tabIndex=0）；空 options / 现值越表不炸。

import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "solid-js/web";
import Segmented from "../components/Segmented";

let dispose: (() => void) | undefined;
afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

type V = "a" | "b" | "c";
const OPTS: { value: V; label: string }[] = [
    { value: "a", label: "A" },
    { value: "b", label: "B" },
    { value: "c", label: "C" },
];

function mount(options: { value: V; label: string }[], value: string) {
    const onChange = vi.fn();
    dispose = render(
        () =>
            Segmented({
                options,
                value: value as V,
                onChange,
            }),
        document.body,
    );
    const group = document.body.querySelector<HTMLElement>(".segmented")!;
    const items = () => [
        ...group.querySelectorAll<HTMLElement>("[role='radio']"),
    ];
    const key = (k: string, from?: HTMLElement) =>
        (from ?? group).dispatchEvent(
            new KeyboardEvent("keydown", { key: k, bubbles: true }),
        );
    return { onChange, group, items, key };
}

describe("Segmented 键盘漫游", () => {
    it("ArrowRight 从末项回卷到首项", () => {
        const { onChange, items, key } = mount(OPTS, "c");
        key("ArrowRight", items()[2]);
        expect(onChange).toHaveBeenCalledWith("a");
    });

    it("ArrowLeft 从首项回卷到末项", () => {
        const { onChange, items, key } = mount(OPTS, "a");
        key("ArrowLeft", items()[0]);
        expect(onChange).toHaveBeenCalledWith("c");
    });

    it("ArrowDown/ArrowUp 等价右/左", () => {
        const { onChange, items, key } = mount(OPTS, "a");
        key("ArrowDown", items()[0]);
        expect(onChange).toHaveBeenCalledWith("b");
        key("ArrowUp", items()[0]);
        expect(onChange).toHaveBeenCalledWith("c");
    });

    it("Home/End 跳首尾", () => {
        const { onChange, items, key } = mount(OPTS, "b");
        key("End", items()[1]);
        expect(onChange).toHaveBeenCalledWith("c");
        key("Home", items()[1]);
        expect(onChange).toHaveBeenCalledWith("a");
    });

    it("方向键把焦点移到目标项", () => {
        const { items, key } = mount(OPTS, "a");
        key("ArrowRight", items()[0]);
        expect(document.activeElement).toBe(items()[1]);
    });

    it("roving tabindex：仅现值项 tabIndex=0", () => {
        const { items } = mount(OPTS, "b");
        expect(items().map((el) => el.tabIndex)).toEqual([-1, 0, -1]);
    });

    it("非导航键不触发 onChange", () => {
        const { onChange, items, key } = mount(OPTS, "a");
        key("Enter", items()[0]);
        key("x", items()[0]);
        expect(onChange).not.toHaveBeenCalled();
    });

    it("空 options：方向键不炸、不触发 onChange", () => {
        const { onChange, group, key } = mount([], "a");
        expect(() => key("ArrowRight")).not.toThrow();
        expect(onChange).not.toHaveBeenCalled();
        expect(group.querySelectorAll("[role='radio']")).toHaveLength(0);
    });

    it("现值越表：首项兜底 tabIndex=0、ArrowRight 走第二项", () => {
        const { onChange, items, key } = mount(OPTS, "z");
        expect(items().map((el) => el.tabIndex)).toEqual([0, -1, -1]);
        key("ArrowRight", items()[0]);
        expect(onChange).toHaveBeenCalledWith("b");
    });

    it("现值越表：Home 选中首项（移动即选中愈合取值）", () => {
        const { onChange, items, key } = mount(OPTS, "z");
        key("Home", items()[0]);
        expect(onChange).toHaveBeenCalledWith("a");
    });
});
