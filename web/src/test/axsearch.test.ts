// @vitest-environment jsdom
// axsearch 防抖搜索状态机回归：
//  - 300ms 防抖合并：连打只发末次查询
//  - 空串/gate 命中 → onClear 清场不发起
//  - seq 代次闸：feed/cancel 同步换代，防抖窗内被顶替的慢响应丢弃
//  - 失败 → onError；alive 闸挡卸载后落地

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    discoverSearch: vi.fn(),
}));

vi.mock("../api/client", () => ({
    api: { discoverSearch: mocks.discoverSearch },
}));

import type { DiscoverHit } from "../api/client";
import { createDebouncedAxSearch } from "../axsearch";

type Deps = Parameters<typeof createDebouncedAxSearch>[0];

const hit = (title: string): DiscoverHit => ({ title });

const deferred = <T>() => {
    let resolve!: (v: T) => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
};

const make = (over: Partial<Deps> = {}) => {
    const cbs = { onClear: vi.fn(), onResult: vi.fn(), onError: vi.fn() };
    const search = createDebouncedAxSearch({ ...cbs, ...over });
    return { cbs, search };
};

beforeEach(() => {
    vi.useFakeTimers();
    mocks.discoverSearch.mockReset().mockResolvedValue([hit("x")]);
});

afterEach(() => {
    vi.useRealTimers();
});

describe("createDebouncedAxSearch", () => {
    it("300ms 防抖合并：连打只发末次查询", async () => {
        const { cbs, search } = make();
        search.feed("alpha");
        search.feed("alph");
        search.feed("al");
        await vi.advanceTimersByTimeAsync(299);
        expect(mocks.discoverSearch).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(1);
        expect(mocks.discoverSearch).toHaveBeenCalledTimes(1);
        expect(mocks.discoverSearch).toHaveBeenCalledWith("al");
        await vi.advanceTimersByTimeAsync(0);
        expect(cbs.onResult).toHaveBeenCalledWith([hit("x")]);
        expect(cbs.onClear).not.toHaveBeenCalled();
    });

    it("空串与 gate 命中 → onClear 清场不发起", async () => {
        const { cbs, search } = make({
            gate: (q: string) => q.startsWith("#"),
        });
        search.feed("   ");
        expect(cbs.onClear).toHaveBeenCalledTimes(1);
        search.feed("#tag");
        expect(cbs.onClear).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(1000);
        expect(mocks.discoverSearch).not.toHaveBeenCalled();
        expect(cbs.onResult).not.toHaveBeenCalled();
    });

    it("seq 闸：防抖窗内 feed 顶替的慢响应不落地", async () => {
        const first = deferred<DiscoverHit[]>();
        mocks.discoverSearch.mockImplementationOnce(() => first.promise);
        const { cbs, search } = make();
        search.feed("old");
        await vi.advanceTimersByTimeAsync(300);
        expect(mocks.discoverSearch).toHaveBeenCalledWith("old");
        // feed 同步换代——old 响应落在新 timer 点火前也必须作废
        search.feed("new");
        first.resolve([hit("stale")]);
        await vi.advanceTimersByTimeAsync(0);
        expect(cbs.onResult).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(300);
        expect(mocks.discoverSearch).toHaveBeenCalledWith("new");
        await vi.advanceTimersByTimeAsync(0);
        expect(cbs.onResult).toHaveBeenCalledWith([hit("x")]);
    });

    it("失败 → onError", async () => {
        mocks.discoverSearch.mockRejectedValueOnce(new Error("boom"));
        const { cbs, search } = make();
        search.feed("x");
        await vi.advanceTimersByTimeAsync(300);
        await vi.advanceTimersByTimeAsync(0);
        expect(cbs.onError).toHaveBeenCalledTimes(1);
        expect(cbs.onResult).not.toHaveBeenCalled();
    });

    it("cancel() 换代：在飞响应被丢弃", async () => {
        const first = deferred<DiscoverHit[]>();
        mocks.discoverSearch.mockImplementationOnce(() => first.promise);
        const { cbs, search } = make();
        search.feed("x");
        await vi.advanceTimersByTimeAsync(300);
        search.cancel();
        first.resolve([hit("late")]);
        await vi.advanceTimersByTimeAsync(0);
        expect(cbs.onResult).not.toHaveBeenCalled();
        expect(cbs.onError).not.toHaveBeenCalled();
    });

    it("alive 闸：卸载后落地的响应被丢弃", async () => {
        const first = deferred<DiscoverHit[]>();
        mocks.discoverSearch.mockImplementationOnce(() => first.promise);
        let alive = true;
        const { cbs, search } = make({ alive: () => alive });
        search.feed("x");
        await vi.advanceTimersByTimeAsync(300);
        alive = false;
        first.resolve([hit("late")]);
        await vi.advanceTimersByTimeAsync(0);
        expect(cbs.onResult).not.toHaveBeenCalled();
    });
});
