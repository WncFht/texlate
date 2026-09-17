// M7：request() 默认 AbortSignal.timeout(15s)——防 health/snapshot 裸挂。
// 调用方传 init.signal 可覆盖（结构验证：spy AbortSignal.timeout 的调用与否）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, REQUEST_TIMEOUT_MS } from "../api/client";

const fetchMock = vi.fn();

beforeEach(() => {
    fetchMock.mockReset().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: () => Promise.resolve({ ok: true }),
        text: () => Promise.resolve(""),
    });
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe("request 默认超时（M7）", () => {
    it("默认带 AbortSignal.timeout(REQUEST_TIMEOUT_MS)", async () => {
        const spy = vi.spyOn(AbortSignal, "timeout");
        await api.health();
        expect(REQUEST_TIMEOUT_MS).toBe(15_000);
        expect(spy).toHaveBeenCalledWith(15_000);
        const init = fetchMock.mock.calls[0][1] as RequestInit;
        expect(init.signal).toBeInstanceOf(AbortSignal);
    });

    it("所有 REST 端点共享同一默认超时（tasks 列表亦带 signal）", async () => {
        await api.tasks();
        const init = fetchMock.mock.calls[0][1] as RequestInit;
        expect(init.signal).toBeInstanceOf(AbortSignal);
    });
});
