// @vitest-environment jsdom
// toastStore 契约回归 —— push / key 去重 / TTL / 栈上限 / action
// （spike 14 探针的落地版 + probe2 抓到的 dedupe-换新-action 死角）。
// store 依赖 window.setTimeout——必须 jsdom 环境（node 下 push 抛
// ReferenceError，spike 已实证）；计时断言走 vi.useFakeTimers。

import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "../stores/toastStore";

afterEach(() => {
    vi.useRealTimers();
    toast.clear();
});

describe("toast store", () => {
    it("push：入栈并回 id；ok 默认 4500ms / err 9000ms", () => {
        vi.useFakeTimers();
        const a = toast.ok("done");
        const b = toast.err("boom");
        const list = toast.toasts();
        expect(list.map((x) => x.id)).toEqual([a, b]);
        expect(list[0].kind).toBe("ok");
        expect(list[0].ttl).toBe(4500);
        expect(list[1].kind).toBe("err");
        expect(list[1].ttl).toBe(9000);
    });

    it("TTL：到点自动消条", () => {
        vi.useFakeTimers();
        toast.ok("gone", { ttl: 1000 });
        expect(toast.toasts()).toHaveLength(1);
        vi.advanceTimersByTime(1500);
        expect(toast.toasts()).toHaveLength(0);
    });

    it("key 去重：同 key 重推刷文案+重计计时器，不叠条", () => {
        vi.useFakeTimers();
        const a = toast.push({ kind: "ok", text: "v1", key: "k", ttl: 1000 });
        vi.advanceTimersByTime(600);
        const b = toast.push({ kind: "ok", text: "v2", key: "k" });
        expect(b).toBe(a);
        expect(toast.toasts()).toHaveLength(1);
        expect(toast.toasts()[0].text).toBe("v2");
        // t=600 刷新重计 1000：t=1100 应仍在（旧计时器若没清已死在 t=1000）
        vi.advanceTimersByTime(500);
        expect(toast.toasts()).toHaveLength(1);
        vi.advanceTimersByTime(600);
        expect(toast.toasts()).toHaveLength(0);
    });

    it("栈上限 3：超出逐最旧，新条必落", () => {
        vi.useFakeTimers();
        for (let i = 0; i < 5; i++) toast.ok(`m${i}`, { ttl: 60_000 });
        expect(toast.toasts().map((x) => x.text)).toEqual(["m2", "m3", "m4"]);
    });

    it("action：act() 跑 onClick 并收条；href 挂 toast.action 供 host 渲 <a>", () => {
        vi.useFakeTimers();
        let n = 0;
        const id = toast.err("fail", {
            ttl: 60_000,
            action: { label: "Retry", onClick: () => n++ },
        });
        expect(toast.toasts()[0].action?.label).toBe("Retry");
        toast.act(id);
        expect(n).toBe(1);
        expect(toast.toasts()).toHaveLength(0);

        toast.ok("queued", {
            ttl: 60_000,
            action: { label: "查看", href: "#/reader/t1" },
        });
        expect(toast.toasts()[0].action?.href).toBe("#/reader/t1");
    });

    it("key 去重时显式传入的新 action 整体换新（spike probe2 死角）", () => {
        vi.useFakeTimers();
        let which = 0;
        toast.push({
            kind: "ok",
            text: "v1",
            key: "a",
            ttl: 60_000,
            action: { label: "A1", onClick: () => (which = 1) },
        });
        toast.push({
            kind: "ok",
            text: "v2",
            key: "a",
            ttl: 60_000,
            action: { label: "A2", onClick: () => (which = 2) },
        });
        expect(toast.toasts()).toHaveLength(1);
        expect(toast.toasts()[0].action?.label).toBe("A2");
        toast.act(toast.toasts()[0].id);
        expect(which).toBe(2);
    });

    it("dismiss：手动收条并清计时器（不复活）", () => {
        vi.useFakeTimers();
        const id = toast.ok("x", { ttl: 60_000 });
        toast.dismiss(id);
        expect(toast.toasts()).toHaveLength(0);
        vi.advanceTimersByTime(120_000);
        expect(toast.toasts()).toHaveLength(0);
    });

    it("常驻条：ttl=Infinity 不自动消，dismiss 可收", () => {
        vi.useFakeTimers();
        const id = toast.push({ kind: "ok", text: "sticky", ttl: Infinity });
        vi.advanceTimersByTime(120_000);
        expect(toast.toasts()).toHaveLength(1);
        toast.dismiss(id);
        expect(toast.toasts()).toHaveLength(0);
    });
});
