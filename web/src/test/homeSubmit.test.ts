// @vitest-environment jsdom
// Home 提交编排（home/submit.ts）：409 duplicate_active → onExisting 直跳
// 既有任务（taskId 字段优先、detail 正则兜底）；id 解析失败 → aria-invalid
// + invalidId 文案且不发请求。这两条路径此前零覆盖。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    health: vi.fn(),
    getSettings: vi.fn(),
    translate: vi.fn(),
}));

// vi.mock 提升限制——工厂体内再引 _homekit（顶层 import 进不了 hoisted 作用域）
vi.mock("../api/client", async (importOriginal) =>
    (await import("./_homekit")).buildApiModule(
        await importOriginal<typeof import("../api/client")>(),
        mocks,
    ),
);

import { ApiError } from "../api/client";
import { t } from "../i18n";
import Home from "../pages/Home";
import { flush, mountHome, resetHomeMocks, type } from "./_homekit";

function submit(form: HTMLFormElement) {
    form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
    );
}

const errText = () =>
    document.body.querySelector(".form-error")?.textContent ?? "";

beforeEach(() => resetHomeMocks(mocks));

describe("Home submit —— 409 duplicate_active 直跳既有任务", () => {
    it("ApiError 带 taskId 字段 → nav #/reader/<taskId>，不落错误文案", async () => {
        mocks.translate.mockRejectedValue(
            new ApiError(
                409,
                "active task exists",
                "duplicate_active",
                "t_aaaabbbbccccdddd",
            ),
        );
        const { nav, input, form } = mountHome(Home);
        type(input, "2501.14787");
        submit(form);

        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();
        await flush();

        expect(nav).toHaveBeenCalledWith("#/reader/t_aaaabbbbccccdddd");
        expect(errText()).toBe("");
    });

    it("409 无 taskId 字段 → detail 正则兜底提出 t_*", async () => {
        mocks.translate.mockRejectedValue(
            new ApiError(409, "active task t_1111222233334444 exists"),
        );
        const { nav, input, form } = mountHome(Home);
        type(input, "2501.14787");
        submit(form);

        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();
        await flush();

        expect(nav).toHaveBeenCalledWith("#/reader/t_1111222233334444");
    });

    it("409 但 detail 也无 t_* → 落错误文案不跳路由", async () => {
        mocks.translate.mockRejectedValue(new ApiError(409, "conflict"));
        const { nav, input, form } = mountHome(Home);
        type(input, "2501.14787");
        submit(form);

        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();
        await flush();

        expect(nav).not.toHaveBeenCalled();
        expect(errText()).toContain("conflict");
    });
});

describe("Home submit —— 非法 id 输入", () => {
    it("解析失败 → aria-invalid + invalidId 文案，不发请求", async () => {
        const { input, form } = mountHome(Home);
        type(input, "not-an-id");
        submit(form);
        await flush();

        expect(mocks.translate).not.toHaveBeenCalled();
        expect(input.getAttribute("aria-invalid")).toBe("true");
        expect(errText()).toContain(t.home.invalidId);
    });

    it("再编辑即消格式错态（aria-invalid 复位 + 文案清空）", async () => {
        const { input, form } = mountHome(Home);
        type(input, "not-an-id");
        submit(form);
        await flush();
        expect(input.getAttribute("aria-invalid")).toBe("true");
        expect(errText()).toContain(t.home.invalidId);

        type(input, "2501.14787");
        await flush();
        expect(input.getAttribute("aria-invalid")).toBe("false");
        expect(errText()).toBe("");
    });
});
